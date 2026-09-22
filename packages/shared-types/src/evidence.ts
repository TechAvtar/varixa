/** Mirrors `app/enums.py::EvidenceLevel`. Classifications of evidence, never claims of truth. */
export type EvidenceLevel = "VERIFIED" | "STRONG" | "PROBABLE" | "POSSIBLE" | "UNKNOWN";

export const EVIDENCE_LEVELS: readonly EvidenceLevel[] = [
  "VERIFIED",
  "STRONG",
  "PROBABLE",
  "POSSIBLE",
  "UNKNOWN",
];
