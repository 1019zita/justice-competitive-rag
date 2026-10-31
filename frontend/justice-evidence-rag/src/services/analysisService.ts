import type { AnalysisInput, AnalysisMode, AnalysisResult } from "../types/analysis";

export interface AnalysisService {
  analyzeCase(input: AnalysisInput): Promise<AnalysisResult>;
  checkViewpoint(input: AnalysisInput): Promise<AnalysisResult>;
  refineAnalysis(input: AnalysisInput & { analysisId: string }): Promise<AnalysisResult>;
}

export function serviceMethodForMode(mode: AnalysisMode): keyof AnalysisService {
  return mode === "case-analysis" ? "analyzeCase" : "checkViewpoint";
}
