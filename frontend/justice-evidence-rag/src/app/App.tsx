import { useState } from "react";
import { AnalysisPipeline } from "../components/analysis/AnalysisPipeline";
import { HttpAnalysisService } from "../services/httpAnalysisService";
import { AnalysisInputPage } from "../pages/AnalysisInputPage";
import { AnalysisWorkspacePage } from "../pages/AnalysisWorkspacePage";
import { HomePage } from "../pages/HomePage";
import type { AnalysisInput, AnalysisMode, AnalysisResult } from "../types/analysis";

type Screen = "home" | "input" | "pipeline" | "workspace";

const analysisService = new HttpAnalysisService();

export function App() {
  const [screen, setScreen] = useState<Screen>("home");
  const [mode, setMode] = useState<AnalysisMode>("case-analysis");
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [pipelineStep, setPipelineStep] = useState(0);
  const [pipelineError, setPipelineError] = useState<string>();

  function openInput(nextMode: AnalysisMode) { setMode(nextMode); setScreen("input"); }
  function startAnalysis(input: AnalysisInput) {
    setPipelineError(undefined);
    setPipelineStep(0);
    setScreen("pipeline");
    const method = mode === "case-analysis" ? "analyzeCase" : "checkViewpoint";
    const progressTimer = window.setInterval(() => setPipelineStep(step => Math.min(step + 1, 7)), 700);
    analysisService[method](input).then(nextResult => {
      window.clearInterval(progressTimer);
      setPipelineStep(7);
      setResult(nextResult);
      setScreen("workspace");
    }).catch((error: unknown) => {
      window.clearInterval(progressTimer);
      setPipelineError(error instanceof Error ? error.message : "实时分析失败，请检查本地 API。");
    });
  }
  function resetToHome() { setResult(null); setScreen("home"); }

  if (screen === "home") return <HomePage onSelectMode={openInput} />;
  if (screen === "input") return <AnalysisInputPage mode={mode} onBack={resetToHome} onSubmit={startAnalysis} />;
  if (screen === "pipeline") return <AnalysisPipeline activeStep={pipelineStep} error={pipelineError} />;
  return result ? <AnalysisWorkspacePage result={result} onNewAnalysis={resetToHome} /> : <AnalysisPipeline activeStep={pipelineStep} error="分析结果为空，请返回重新提交。" />;
}
