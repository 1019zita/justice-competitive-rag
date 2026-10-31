"""Minimal stdlib HTTP API for the live analysis runtime."""
from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Mapping, Optional

from .runtime_analysis import RuntimeAnalysisError, RuntimeAnalysisService


MAX_BODY_BYTES = 2_000_000


def _cors_origins() -> str:
    return os.environ.get(
        "LEGAL_RAG_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    )


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")


def _error(code: str, message: str, *, details: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"error": {"code": code, "message": message}}
    if details and os.environ.get("LEGAL_RAG_DEBUG") == "1":
        payload["error"]["details"] = details
    return payload


class AnalysisRequestHandler(BaseHTTPRequestHandler):
    server_version = "LegalRagRuntime/1.0"

    def _write(self, status: int, payload: Mapping[str, Any]) -> None:
        body = _json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", self._origin())
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _origin(self) -> str:
        allowed = {item.strip() for item in _cors_origins().split(",") if item.strip()}
        origin = self.headers.get("Origin", "")
        return origin if origin in allowed else next(iter(allowed), "http://localhost:5173")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._write(204, {})

    def do_GET(self) -> None:  # noqa: N802
        if self.path not in {"/health", "/api/health"}:
            self._write(404, _error("NOT_FOUND", "endpoint not found"))
            return
        self._write(200, {"status": "ok", "service": "live-analysis-runtime", "api_version": "v1"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/analysis":
            self._write(404, _error("NOT_FOUND", "endpoint not found"))
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._write(400, _error("INVALID_CONTENT_LENGTH", "Content-Length must be an integer"))
            return
        if length <= 0 or length > MAX_BODY_BYTES:
            self._write(400, _error("INVALID_BODY_SIZE", "request body is empty or too large"))
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._write(400, _error("INVALID_JSON", "request body must be UTF-8 JSON", details=str(exc)))
            return
        if not isinstance(payload, dict):
            self._write(400, _error("INVALID_REQUEST", "request body must be an object"))
            return
        try:
            result = self._analyze(payload)
        except RuntimeAnalysisError as exc:
            self._write(422, _error("ANALYSIS_FAILED", str(exc)))
        except Exception as exc:  # noqa: BLE001
            self._write(500, _error("RUNTIME_ERROR", "live analysis failed", details=f"{type(exc).__name__}: {exc}"))
        else:
            self._write(200, result)

    @staticmethod
    def _analyze(payload: Mapping[str, Any]) -> Dict[str, Any]:
        mode = payload.get("mode", "case-analysis")
        facts = payload.get("facts")
        viewpoint = payload.get("viewpoint")
        question = payload.get("question")
        exclusions = payload.get("exclude_doc_ids") or []
        if not isinstance(mode, str) or not isinstance(facts, str):
            raise RuntimeAnalysisError("mode and facts are required strings")
        if not isinstance(exclusions, list) or not all(isinstance(item, str) for item in exclusions):
            raise RuntimeAnalysisError("exclude_doc_ids must be a list of strings when provided")
        service = RuntimeAnalysisService(exclude_doc_ids=exclusions)
        return service.analyze(
            facts=facts,
            mode=mode,
            viewpoint=viewpoint if isinstance(viewpoint, str) else None,
            question=question if isinstance(question, str) else None,
        )

    def log_message(self, format: str, *args: Any) -> None:
        # Keep the API usable from a terminal without dumping request bodies.
        print(f"[runtime-api] {self.address_string()} - {format % args}")


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    server = ThreadingHTTPServer((host, port), AnalysisRequestHandler)
    print(f"live analysis API listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping live analysis API")
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Live Dynamic Issue Spotting + Retrieval + G1 API")
    parser.add_argument("--host", default=os.environ.get("LEGAL_RAG_API_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("LEGAL_RAG_API_PORT", "8000")))
    args = parser.parse_args()
    serve(args.host, args.port)


if __name__ == "__main__":
    main()
