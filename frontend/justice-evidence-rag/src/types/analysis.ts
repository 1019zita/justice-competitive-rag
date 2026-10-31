import type { EvidenceItem, ProvenanceStatus } from "./evidence";

export type AnalysisMode = "case-analysis" | "viewpoint-check";

export type CanonicalArtifactMetadata = {
  version: string;
  internalConditionArtifactVersion?: string;
  sourcePaths: string[];
  contentHashEquivalent: {
    hg2_0004: {
      vignetteManifest: "YES" | "NO";
      keySentenceAudit: "YES" | "NO";
      conditionArtifacts: "YES" | "NO";
    };
    hg2_0003: {
      vignetteManifest: "YES" | "NO";
      keySentenceAudit: "YES" | "NO";
      conditionArtifacts: "YES" | "NO";
    };
  };
};

export type CoverageField = "sourceCounts" | "candidateCount" | "authorityPassedCount" | "applicabilityPassedCount" | "citedCount" | "timeRange" | "coveredSources" | "knownGaps";

export type CoverageFieldProvenance = {
  status: ProvenanceStatus;
  source?: string;
  note?: string;
};

export type RetrievalCoverageProvenance = Record<CoverageField, CoverageFieldProvenance>;

export type AnalysisInput = {
  facts: string;
  question?: string;
  viewpoint?: string;
};

export type AnalysisIssue = {
  id: string;
  title: string;
  description?: string;
};

export type UnresolvedFact = {
  id: string;
  fact: string;
  whyItMatters: string;
  severity: "high" | "medium" | "low";
};

export type AnalysisResult = {
  analysisId: string;
  mode: AnalysisMode;
  createdAt: string;
  input: AnalysisInput;
  canonicalArtifact: CanonicalArtifactMetadata;
  caseSummary: string;
  issues: AnalysisIssue[];
  overallAssessment: {
    summary: string;
    strength: "strong" | "moderate" | "mixed" | "insufficient";
    uncertaintySummary?: string;
  };
  supportingEvidence: EvidenceItem[];
  weakeningEvidence: EvidenceItem[];
  alternativeExplanations: {
    id: string;
    text: string;
    issueIds?: string[];
  }[];
  unresolvedFacts: UnresolvedFact[];
  retrievalCoverage: {
    sourceCounts: Record<string, number>;
    candidateCount: number;
    authorityPassedCount: number;
    applicabilityPassedCount: number;
    citedCount: number;
    timeRange?: string;
    coveredSources?: string[];
    knownGaps?: string[];
    provenance: RetrievalCoverageProvenance;
  };
  followUpSuggestions: string[];
};
