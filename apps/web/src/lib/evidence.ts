import type {
  AnalysisResponse,
  EvidenceLevel,
  ImageFingerprintsResponse,
  ImageMetadataResponse,
  ImageProvenanceResponse,
} from "@verixa/shared-types";

/**
 * Preliminary, deterministic evidence derived on the web side from the
 * pipeline outputs, following the initial rules in docs/07-EVIDENCE-ENGINE.md.
 * The server-side evidence engine (T029+) replaces this with persisted,
 * traceable records; until then every item is explicitly labelled "preliminary".
 */

export type EvidenceKind = "fact" | "signal" | "unknown";

export interface EvidenceItem {
  id: string;
  category: "file" | "provenance" | "metadata" | "matches" | "ai" | "forensics" | "sources";
  kind: EvidenceKind;
  level: EvidenceLevel;
  claim: string;
  source: string;
  detail?: string;
  limitation?: string;
}

export const LEVEL_STYLES: Record<EvidenceLevel, { label: string; className: string }> = {
  VERIFIED: {
    label: "VERIFIED",
    className: "bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200",
  },
  STRONG: {
    label: "STRONG",
    className: "bg-teal-100 text-teal-900 dark:bg-teal-950 dark:text-teal-200",
  },
  PROBABLE: {
    label: "PROBABLE",
    className: "bg-sky-100 text-sky-900 dark:bg-sky-950 dark:text-sky-200",
  },
  POSSIBLE: {
    label: "POSSIBLE",
    className: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200",
  },
  UNKNOWN: { label: "UNKNOWN", className: "bg-muted text-muted-foreground" },
};

export function deriveEvidence(
  a: AnalysisResponse,
  metadata: ImageMetadataResponse | null,
  provenance: ImageProvenanceResponse | null,
  fingerprints: ImageFingerprintsResponse | null,
): EvidenceItem[] {
  const items: EvidenceItem[] = [];

  // -- file: deterministic facts about the stored bytes -------------------------------
  if (a.file) {
    items.push({
      id: "file.identity",
      category: "file",
      kind: "fact",
      level: "VERIFIED",
      claim: `The stored file is ${a.file.mime_type ?? "of unknown type"}, ${a.file.width ?? "?"} × ${
        a.file.height ?? "?"
      } px, ${a.file.size_bytes ?? "?"} bytes, SHA-256 ${a.file.sha256.slice(0, 12)}…`,
      source: "validation",
      detail: "Type and dimensions were decoded from the content, not read from the name.",
    });
  }

  // -- provenance -------------------------------------------------------------------------
  if (!provenance) {
    items.push({
      id: "provenance.uninspected",
      category: "provenance",
      kind: "unknown",
      level: "UNKNOWN",
      claim: "Content credentials were not inspected.",
      source: "c2pa",
      limitation: "No C2PA engine ran for this analysis.",
    });
  } else if (!provenance.normalized.has_c2pa) {
    items.push({
      id: "provenance.absent",
      category: "provenance",
      kind: "unknown",
      level: "UNKNOWN",
      claim: "No content credentials (C2PA) are embedded in this file.",
      source: `c2pa/${provenance.normalized.engine}`,
      limitation:
        "Absence does not establish whether the file was edited or generated; most images carry none.",
    });
  } else if (provenance.normalized.valid_signature) {
    items.push({
      id: "provenance.valid",
      category: "provenance",
      kind: "fact",
      level: "VERIFIED",
      claim: `A C2PA manifest is present and its signature validates (issuer as stated: ${
        provenance.normalized.signer ?? "unknown"
      }).`,
      source: `c2pa/${provenance.normalized.engine}`,
      detail: provenance.normalized.claim_generator
        ? `Claim generator: ${provenance.normalized.claim_generator}.`
        : undefined,
      limitation:
        "Validity shows the manifest is intact, not that its claims are true; issuer trust is not evaluated.",
    });
  } else {
    items.push({
      id: "provenance.invalid",
      category: "provenance",
      kind: "signal",
      level: "POSSIBLE",
      claim: "A C2PA manifest is present but validation reported problems.",
      source: `c2pa/${provenance.normalized.engine}`,
      detail: provenance.normalized.validation_failures.map((f) => f.code).join(", "),
      limitation: "The manifest may be damaged, or the file changed after signing.",
    });
  }

  // -- metadata -----------------------------------------------------------------------------
  if (metadata) {
    const n = metadata.normalized;
    if (n.software) {
      items.push({
        id: "metadata.software",
        category: "metadata",
        kind: "signal",
        level: "STRONG",
        claim: `Metadata records the software "${n.software}".`,
        source: `metadata/${n.engine}`,
        limitation:
          "A software tag shows what wrote the metadata, not the full edit history; tags can be altered.",
      });
    }
    if (n.camera_make || n.camera_model) {
      items.push({
        id: "metadata.camera",
        category: "metadata",
        kind: "signal",
        level: "POSSIBLE",
        claim: `Metadata records the camera "${[n.camera_make, n.camera_model]
          .filter(Boolean)
          .join(" ")}".`,
        source: `metadata/${n.engine}`,
        limitation: "Camera fields are recorded values and can be copied or edited.",
      });
    }
    if (n.captured_at) {
      items.push({
        id: "metadata.captured",
        category: "metadata",
        kind: "signal",
        level: "POSSIBLE",
        claim: `Metadata records a capture time of ${n.captured_at.raw}${
          n.captured_at.tz_known ? "" : " (timezone not recorded)"
        }.`,
        source: `metadata/${n.engine}`,
        limitation: "Device clocks and edits can make recorded times wrong.",
      });
    }
    if (n.gps_present) {
      items.push({
        id: "metadata.gps",
        category: "metadata",
        kind: "signal",
        level: "POSSIBLE",
        claim: "Metadata contains GPS location fields.",
        source: `metadata/${n.engine}`,
        limitation: "Coordinates are not shown here and can be inaccurate or fabricated.",
      });
    }
    if (!n.has_exif && !n.has_xmp && !n.has_iptc) {
      items.push({
        id: "metadata.none",
        category: "metadata",
        kind: "unknown",
        level: "UNKNOWN",
        claim: "No EXIF, XMP or IPTC metadata is present.",
        source: `metadata/${n.engine}`,
        limitation:
          "Missing metadata does not establish editing; many platforms strip it on upload.",
      });
    }
  } else {
    items.push({
      id: "metadata.unavailable",
      category: "metadata",
      kind: "unknown",
      level: "UNKNOWN",
      claim: "Metadata was not extracted.",
      source: "metadata",
    });
  }

  // -- matches (own account) ----------------------------------------------------------------
  if (fingerprints) {
    const exact = fingerprints.similar.filter((s) => s.relation === "exact");
    const near = fingerprints.similar.filter((s) => s.relation === "near");
    if (exact.length) {
      items.push({
        id: "matches.exact",
        category: "matches",
        kind: "fact",
        level: "VERIFIED",
        claim: `${exact.length} of your other analyses contain byte-identical content (same SHA-256).`,
        source: "fingerprints",
        limitation: "Identity of bytes says nothing about which copy came first.",
      });
    }
    if (near.length) {
      items.push({
        id: "matches.near",
        category: "matches",
        kind: "signal",
        level: "POSSIBLE",
        claim: `${near.length} of your other analyses look perceptually similar (pHash/dHash within ${fingerprints.near_threshold} bits).`,
        source: "fingerprints",
        limitation:
          "Perceptual similarity can come from recompression, resizing or unrelated look-alikes.",
      });
    }
  }

  // -- not yet available ----------------------------------------------------------------------
  items.push(
    {
      id: "ai.unavailable",
      category: "ai",
      kind: "unknown",
      level: "UNKNOWN",
      claim: "AI-generation signals were not evaluated.",
      source: "ai-detector",
      limitation: "No detector ran in this build. Detector output is never proof of authorship.",
    },
    {
      id: "forensics.unavailable",
      category: "forensics",
      kind: "unknown",
      level: "UNKNOWN",
      claim: "Forensic analysis (ELA, compression, noise, resampling, copy-move) was not run.",
      source: "forensics",
    },
    {
      id: "sources.unavailable",
      category: "sources",
      kind: "unknown",
      level: "UNKNOWN",
      claim: "No reverse or source search was performed.",
      source: "search",
    },
  );

  return items;
}

export function summarise(items: EvidenceItem[]): Record<EvidenceLevel, number> {
  const counts: Record<EvidenceLevel, number> = {
    VERIFIED: 0,
    STRONG: 0,
    PROBABLE: 0,
    POSSIBLE: 0,
    UNKNOWN: 0,
  };
  for (const i of items) counts[i.level] += 1;
  return counts;
}
