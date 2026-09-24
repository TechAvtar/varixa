/** Mirrors `app/schemas/provenance.py`. */

export interface ProvenanceAction {
  action: string | null;
  when: string | null;
  software_agent: string | null;
  parameters?: unknown;
}

export interface ProvenanceValidationFailure {
  code: string;
  explanation: string | null;
}

export interface NormalizedProvenance {
  engine: string;
  engine_version: string;
  has_c2pa: boolean;
  /** null when no manifest exists (nothing to validate). */
  valid_signature: boolean | null;
  signer: string | null;
  signature_alg: string | null;
  signed_at: string | null;
  claim_generator: string | null;
  title: string | null;
  active_manifest: string | null;
  manifest_count: number;
  ingredient_count: number;
  assertion_labels: string[];
  actions: ProvenanceAction[];
  authors: string[];
  validation_codes: string[];
  validation_failures: ProvenanceValidationFailure[];
  warnings: string[];
  /** Structured validation view: engine state, per-family codes, per-ingredient results. */
  validation: {
    state?: string | null;
    source?: string;
    active_manifest?: {
      success: string[];
      informational: string[];
      failure: string[];
    };
    ingredients?: Record<
      string,
      { success: string[]; informational: string[]; failure: string[] }
    >;
  };
  /** `--info` facts reported by the engine (manifest store size, count, validated). */
  info: Record<string, unknown>;
}

export interface ImageProvenanceResponse {
  normalized: NormalizedProvenance;
  manifests: Record<string, unknown>;
  validation_status: Array<Record<string, unknown>>;
  limitations: string[];
}
