import type { AnalysisInput, AnalysisResult } from "../types/analysis";
import type { AnalysisService } from "./analysisService";

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";
type RuntimeAnalysisPayload = Omit<AnalysisInput, "viewpoint"> & { mode: string; viewpoint?: string | null };


export class HttpAnalysisService implements AnalysisService {
  analyzeCase(input: AnalysisInput): Promise<AnalysisResult> {
    return this.submit({ ...input, mode: "case-analysis", viewpoint: null });
  }

  checkViewpoint(input: AnalysisInput): Promise<AnalysisResult> {
    return this.submit({ ...input, mode: "viewpoint-check" });
  }

  refineAnalysis(_input: AnalysisInput & { analysisId: string }): Promise<AnalysisResult> {
    return Promise.reject(new Error("后续追问尚未接入真实重新检索；请提交新的案件分析。"));
  }

  private async submit(payload: RuntimeAnalysisPayload): Promise<AnalysisResult> {
    const baseUrl = (import.meta.env.VITE_API_BASE_URL || DEFAULT_API_BASE_URL).replace(/\/$/, "");
    const endpoint = `${baseUrl}/api/analysis`;
    let response: Response;
    try {
      response = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    } catch (error) {
      throw new Error(`无法连接实时分析 API：${error instanceof Error ? error.message : "network error"}`);
    }

    const body = await response.json().catch(() => null) as { error?: { message?: string } } | AnalysisResult | null;
    if (!response.ok) {
      const message = body && "error" in body ? body.error?.message : undefined;
      throw new Error(message || `实时分析 API 返回 HTTP ${response.status}`);
    }
    if (!body || "error" in body || !("analysisId" in body)) {
      throw new Error("实时分析 API 返回了不完整的 AnalysisResult");
    }
    return body as AnalysisResult;
  }
}
