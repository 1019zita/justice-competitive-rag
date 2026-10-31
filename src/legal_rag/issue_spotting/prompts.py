"""Versioned prompt loading for Dynamic Legal Issue Spotting."""
from __future__ import annotations

from pathlib import Path
from typing import Mapping

from ..data import REPO_ROOT

DEFAULT_PROMPT_DIR = REPO_ROOT / "prompts" / "issue_spotting"


class PromptRepository:
    def __init__(self, prompt_dir: str | Path = DEFAULT_PROMPT_DIR) -> None:
        self.prompt_dir = Path(prompt_dir)
        if not self.prompt_dir.is_absolute():
            self.prompt_dir = REPO_ROOT / self.prompt_dir

    def load(self, version: str) -> str:
        path = self.prompt_dir / f"{version}.txt"
        if not path.is_file():
            raise FileNotFoundError(f"issue spotting prompt missing: {path}")
        return path.read_text(encoding="utf-8")

    def render(self, version: str, values: Mapping[str, str]) -> str:
        text = self.load(version)
        for key, value in values.items():
            text = text.replace("{{" + key + "}}", value)
        return text

    def path(self, version: str) -> Path:
        return self.prompt_dir / f"{version}.txt"
