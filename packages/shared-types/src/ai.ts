/** Mirrors `app/schemas/ai.py`. A detector result is a probabilistic signal, never proof. */

export type AILabel = "likely_ai" | "uncertain" | "likely_human" | "unavailable";

export interface AIDetectionResponse {
  modality: "image" | "text";
  provider: string;
  model: string;
  provider_version: string;
  /** 0 = no AI signal … 1 = strongest, as reported by the provider. Not calibrated. */
  score: number | null;
  label: AILabel;
  calibrated: boolean;
  cached: boolean;
  latency_ms: number | null;
  evaluated_at: string;
  thresholds: { high: number; medium: number };
  evidence_level: "PROBABLE" | "POSSIBLE" | "UNKNOWN";
  raw: Record<string, unknown>;
  limitations: string[];
}
