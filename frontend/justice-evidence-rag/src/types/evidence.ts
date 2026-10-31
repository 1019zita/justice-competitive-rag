export type EvidenceDirection =
  | "supporting"
  | "weakening"
  | "alternative"
  | "neutral";

export type ApplicabilityLevel = "high" | "medium" | "low";
export type ProvenanceStatus = "verified" | "simulated" | "unavailable";

export type EvidenceItem = {
  id: string;
  issueIds: string[];
  direction: EvidenceDirection;
  title: string;
  sourceType: string;
  authorityLevel: string;
  authorityReason?: string;
  sourceEvidenceStatus: ProvenanceStatus;
  sourceEvidenceSource?: string;
  authorityAudit?: {
    status: "verified" | "plausible" | "unknown" | "unavailable";
    sourceIdentityStatus: "verified" | "unknown" | "unavailable";
    authorityLevel: string;
    validityStatus: string;
    publisher?: string | null;
    reason: string;
    provenanceFields: string[];
  };
  applicabilityAudit?: {
    status: "directly_relevant" | "supportive_reference" | "limited" | "uncertain" | "not_applicable" | "unavailable";
    issueRelevance: string;
    jurisdictionFit: string;
    temporalFit: string;
    factualLegalFit: string;
    reason: string;
    provenanceFields: string[];
  };
  keySentence: string;
  relevanceReason: string;
  applicability: {
    level: ApplicabilityLevel;
    reason: string;
    status: ProvenanceStatus;
  };
  fullText?: string;
  source: {
    publisher?: string | null;
    origin?: string;
    url?: string;
    documentId?: string;
    publicationDate?: string;
  };
  retrievalProvenance?: {
    status: ProvenanceStatus;
    query?: string;
    rank?: number;
    score?: number;
    chunkId?: string;
    retrievalChannel?: string;
    authorityAudit?: string;
    authorityAuditStatus?: ProvenanceStatus;
    applicabilityAudit?: string;
    applicabilityAuditStatus?: ProvenanceStatus;
    retrievalRoute?: string;
  };
};
