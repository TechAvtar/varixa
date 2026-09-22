/** Mirrors `app/enums.py::EvidenceLevel`. Classifications of evidence, never claims of truth. */
export type EvidenceLevel =
  "VERIFIED" | "STRONG" | "PROBABLE" | "POSSIBLE" | "UNKNOWN";

export type EvidenceKind = "fact" | "signal" | "unknown" | "conflict";

/** Mirrors `app/schemas/evidence.py`: one leveled, traceable record from the evidence engine. */
export interface EvidenceRecord {
  id: string;
  rule: string;
  category: string;
  level: EvidenceLevel;
  kind: EvidenceKind;
  claim: string;
  source: string;
  confidence: number | null;
  detail: string | null;
  limitation: string | null;
  /** Pointers to raw observations: "step:<name>", "provider_call:<id>", "row:<table>". */
  refs: string[];
  provider_version: string | null;
  conflicts_with: string[];
  data: Record<string, unknown>;
  created_at: string;
}

export interface EvidenceListResponse {
  engine_version: string;
  generated_at: string;
  counts: Record<string, number>;
  conflicts: number;
  /** Strongest leveled record minus a penalty per conflict, in [0, 1]. */
  synthesis_confidence: number;
  /** Thresholds in force for this deployment. */
  thresholds: Record<string, unknown>;
  items: EvidenceRecord[];
}

/** Mirrors `app/schemas/timeline.py`. */
export interface TimelineEvent {
  id: string;
  event_type: string;
  /** Null when the recorded time could not be parsed; `raw_time` is always kept. */
  event_time: string | null;
  raw_time: string | null;
  tz_known: boolean;
  certainty: EvidenceLevel;
  description: string;
  source: string;
  source_evidence_ids: string[];
  data: Record<string, unknown>;
}

export interface TimelineResponse {
  version: string;
  generated_at: string;
  events: TimelineEvent[];
  limitations: string[];
}

/** Mirrors `app/schemas/synthesis.py`: the model's grounded explanation of the evidence. */
export interface SynthesisCitation {
  id: string;
  rule: string;
  level: EvidenceLevel;
  claim: string;
}

export interface SynthesisSection {
  key: string;
  question: string;
  text: string;
  citations: SynthesisCitation[];
  grounded: boolean;
  dropped_citations: number;
}

export interface SynthesisResponse {
  provider: string;
  model: string;
  model_version: string;
  prompt_version: string;
  generated_at: string;
  /** False when the evidence changed after this synthesis was produced. */
  current: boolean;
  grounded: boolean;
  warnings: string[];
  sections: SynthesisSection[];
  cached: boolean;
  latency_ms: number | null;
  tokens_in: number | null;
  tokens_out: number | null;
  estimated_cost: number | null;
  limitations: string[];
  raw: Record<string, unknown>;
}

export const EVIDENCE_LEVELS: readonly EvidenceLevel[] = [
  "VERIFIED",
  "STRONG",
  "PROBABLE",
  "POSSIBLE",
  "UNKNOWN",
];
