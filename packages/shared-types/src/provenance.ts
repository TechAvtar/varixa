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
  /** Signed declarations read from the active manifest (T045). */
  assertions: ProvenanceAssertions;
  software_agents: ProvenanceSoftwareAgent[];
  /** Ingredient tree with per-ingredient validation codes. */
  ingredients: ProvenanceIngredient[];
  ingredient_failures: number;
  /** Every manifest in the store, active first, with signing times. */
  manifest_chain: ProvenanceManifestLink[];
  manifest_order_conflict: boolean;
  /** Certificate subject common name (0.28+ engines). */
  signer_common_name: string | null;
  /** embedded | remote | sidecar | none | unknown */
  manifest_location: string;
  /** Host of a remote manifest the engine did not fetch (fetching is disabled). */
  remote_manifest_host: string | null;
}

export interface ProvenanceHashCoverage {
  label: string;
  alg: string | null;
  name: string | null;
  exclusion_count: number;
  exclusions: Array<{ start: number; length: number | null }>;
}

export interface ProvenanceSourceType {
  action: string | null;
  uri: string;
  short: string;
}

export interface ProvenanceIdentity {
  present: boolean;
  kind: string | null;
  names: string[];
  referenced_assertions?: number;
}

export interface ProvenanceAssertions {
  hash_data?: ProvenanceHashCoverage;
  source_types?: ProvenanceSourceType[];
  training_mining?: Record<string, string>;
  identity?: ProvenanceIdentity;
}

export interface ProvenanceSoftwareAgent {
  name: string;
  version: string | null;
  origin: string;
}

export interface ProvenanceIngredient {
  title: string | null;
  format: string | null;
  relationship: string | null;
  document_id: string | null;
  instance_id: string | null;
  manifest_label: string | null;
  validation_codes: string[];
  failure_codes: string[];
  thumbnail_identifier: string | null;
  children: ProvenanceIngredient[];
}

export interface ProvenanceManifestLink {
  label: string;
  parent: string | null;
  signed_at: string | null;
  claim_generator: string | null;
  signer: string | null;
  signed_after_parent?: boolean;
}

export interface ImageProvenanceResponse {
  normalized: NormalizedProvenance;
  manifests: Record<string, unknown>;
  validation_status: Array<Record<string, unknown>>;
  limitations: string[];
  /** `c2patool --tree` text diagram, when produced. */
  tree: string | null;
}
