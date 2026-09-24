import type {
  AIDetectionResponse,
  AnalysisResponse,
  EvidenceLevel,
  EvidenceListResponse,
  EvidenceRecord,
  ImageFingerprintsResponse,
  ImageForensicsResponse,
  ImageMetadataResponse,
  ImageProvenanceResponse,
  SourceMatchesResponse,
  TextAnalysisResponse,
  TextFingerprintsResponse,
} from "@verixa/shared-types";

/**
 * Preliminary, deterministic evidence derived on the web side from the
 * pipeline outputs, following the initial rules in docs/07-EVIDENCE-ENGINE.md.
 * The server-side evidence engine (T029+) replaces this with persisted,
 * traceable records; until then every item is explicitly labelled "preliminary".
 */

export type EvidenceKind = "fact" | "signal" | "unknown" | "conflict";

export interface EvidenceItem {
  id: string;
  category:
    | "file"
    | "provenance"
    | "metadata"
    | "matches"
    | "ai"
    | "forensics"
    | "sources"
    | "text"
    | "synthesis";
  kind: EvidenceKind;
  level: EvidenceLevel;
  claim: string;
  source: string;
  detail?: string;
  limitation?: string;
  confidence?: number | null;
  refs?: string[];
  conflictsWith?: string[];
  /** Raw observation values the rule recorded (numbers, ids, names); never a level. */
  data?: Record<string, unknown>;
}

/** Records produced by the server-side evidence engine, in the report's item shape. */
export function fromServerEvidence(list: EvidenceListResponse): EvidenceItem[] {
  return recordsToItems(list.items);
}

export function recordsToItems(records: EvidenceRecord[]): EvidenceItem[] {
  return records.map((r) => ({
    id: r.id,
    category: (r.category === "synthesis" ? "forensics" : r.category) as EvidenceItem["category"],
    kind: r.kind,
    level: r.level,
    claim: r.claim,
    source: r.source,
    detail: r.detail ?? undefined,
    limitation: r.limitation ?? undefined,
    confidence: r.confidence,
    refs: r.refs,
    conflictsWith: r.conflicts_with,
    data: r.data && Object.keys(r.data).length > 0 ? r.data : undefined,
  }));
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
  text: TextAnalysisResponse | null = null,
  textFingerprints: TextFingerprintsResponse | null = null,
  ai: AIDetectionResponse | null = null,
  sources: SourceMatchesResponse | null = null,
  forensics: ImageForensicsResponse | null = null,
): EvidenceItem[] {
  const items: EvidenceItem[] = [];
  if (a.type === "text") return deriveTextEvidence(a, text, textFingerprints, ai, sources);

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
  items.push(aiEvidence(ai));
  items.push(...forensicsEvidence(forensics));
  items.push(sourcesEvidence(sources, "reverse-image"));

  return items;
}

/**
 * docs/07: a single ELA anomaly is POSSIBLE at most. ELA, compression and noise
 * are correlated, so later methods must not each add an independent item.
 */
function forensicsEvidence(f: ImageForensicsResponse | null): EvidenceItem[] {
  if (!f) {
    return [
      {
        id: "forensics.unavailable",
        category: "forensics",
        kind: "unknown",
        level: "UNKNOWN",
        claim: "Forensic analysis was not run.",
        source: "forensics",
      },
    ];
  }
  const items: EvidenceItem[] = [];
  const skipped = f.skipped.find((s) => s.method === "ela");
  if (skipped) {
    items.push({
      id: "forensics.ela.na",
      category: "forensics",
      kind: "unknown",
      level: "UNKNOWN",
      claim: "Error Level Analysis is not applicable to this file format.",
      source: "ela",
      detail: skipped.reason,
    });
  } else if (f.ela?.anomaly) {
    const r = f.ela.regions[0];
    items.push({
      id: "forensics.ela.anomaly",
      category: "forensics",
      kind: "signal",
      level: "POSSIBLE",
      claim: `ELA shows ${f.ela.regions.length} localised region(s) re-compressing differently from the rest of the image.`,
      source: "ela",
      detail: r
        ? `Largest region at (${r.x}, ${r.y}), ${r.width} × ${r.height} px; ${(f.ela.outlier_block_fraction * 100).toFixed(1)}% of blocks are outliers.`
        : undefined,
      limitation:
        "ELA is a heuristic: sharp detail, text and saturated colour produce the same pattern. This is not proof of editing.",
    });
  } else if (f.ela) {
    items.push({
      id: "forensics.ela.none",
      category: "forensics",
      kind: "signal",
      level: "UNKNOWN",
      claim: "ELA found no localised error-level pattern.",
      source: "ela",
      detail: f.ela.observation,
      limitation:
        "Absence of an ELA pattern is not evidence of no editing; whole-image resaves and same-quality edits leave no trace.",
    });
  } else {
    items.push({
      id: "forensics.ela.failed",
      category: "forensics",
      kind: "unknown",
      level: "UNKNOWN",
      claim: "Error Level Analysis produced no result.",
      source: "ela",
    });
  }

  const c = f.compression;
  if (c?.anomaly) {
    items.push({
      id: "forensics.compression.offset-grid",
      category: "forensics",
      kind: "signal",
      level: "POSSIBLE",
      claim: `A second JPEG block grid offset by (${c.grid.offset_x}, ${c.grid.offset_y}) px is detectable.`,
      source: "compression",
      detail:
        "Consistent with cropping or shifting after an earlier JPEG save, then saving again. Repeating texture can produce the same pattern.",
      limitation:
        "Correlated with ELA; not an independent indicator. Crop-and-resave is a routine, legitimate workflow.",
    });
  } else if (c?.prior_jpeg_grid) {
    items.push({
      id: "forensics.compression.prior-jpeg",
      category: "forensics",
      kind: "signal",
      level: "POSSIBLE",
      claim: `This ${c.format} file carries an 8×8 JPEG-style block grid.`,
      source: "compression",
      detail: "The content was probably JPEG-compressed before being saved in its current format.",
      limitation:
        "Says something about the file's history, not about editing. Scaling or texture can mimic a grid.",
    });
  } else if (c?.encoding) {
    const e = c.encoding;
    items.push({
      id: "forensics.compression.encoding",
      category: "forensics",
      kind: "signal",
      level: "UNKNOWN",
      claim: `Last saved as a ${e.progressive ? "progressive" : "baseline"} JPEG, ${
        e.subsampling ?? "unknown"
      } subsampling, ${
        e.standard_tables ? "standard tables" : "custom tables"
      } at quality ≈ ${e.estimated_quality ?? "?"}.`,
      source: "compression",
      detail: "Encoder settings of the most recent save. They do not indicate editing.",
    });
  } else if (c) {
    items.push({
      id: "forensics.compression.none",
      category: "forensics",
      kind: "signal",
      level: "UNKNOWN",
      claim: `${c.format} container; no JPEG block grid stands out.`,
      source: "compression",
      detail: c.observation,
    });
  }

  const r = f.resampling;
  if (r?.detected) {
    const p = r.peaks[0];
    items.push({
      id: "forensics.resampling.detected",
      category: "forensics",
      kind: "signal",
      level: "POSSIBLE",
      claim:
        "Periodic pixel correlations consistent with the picture having been rescaled or rotated.",
      source: "resampling",
      detail: p
        ? `${r.peaks.length} spectral peak(s); strongest ${p.ratio}× its surroundings at (${p.fx}, ${p.fy}) cycles/px.`
        : undefined,
      limitation:
        "Resizing for the web or by a camera pipeline leaves the same trace. This says the image was resampled at some point, not that it was edited.",
    });
  } else if (r?.measured) {
    items.push({
      id: "forensics.resampling.none",
      category: "forensics",
      kind: "signal",
      level: "UNKNOWN",
      claim: "No global resampling trace stands out.",
      source: "resampling",
      detail: r.observation,
      limitation:
        "Downscaling, strong compression and some scale factors leave no detectable trace.",
    });
  } else if (r) {
    items.push({
      id: "forensics.resampling.unmeasured",
      category: "forensics",
      kind: "unknown",
      level: "UNKNOWN",
      claim: "The image is too small for a resampling measurement.",
      source: "resampling",
    });
  }

  const n = f.noise;
  if (n?.anomaly) {
    const reg = n.regions[0];
    items.push({
      id: "forensics.noise.anomaly",
      category: "forensics",
      kind: "signal",
      level: "POSSIBLE",
      claim: `Noise level differs from the rest of the image in ${n.regions.length} compact region(s).`,
      source: "noise",
      detail: reg
        ? `Baseline about ${n.baseline_sigma} grey levels; largest region at (${reg.x}, ${reg.y}), ${reg.width} × ${reg.height} px, about ${reg.sigma}.`
        : undefined,
      limitation:
        "Depth of field, sky versus foliage and in-camera denoising produce the same differences. Not proof of editing.",
    });
  } else if (n?.measured && n.blocks_smooth > 0) {
    items.push({
      id: "forensics.noise.consistent",
      category: "forensics",
      kind: "signal",
      level: "UNKNOWN",
      claim: "Noise level is consistent across the smooth areas that could be compared.",
      source: "noise",
      detail: n.observation,
      limitation:
        "Only smooth areas are compared; strong compression flattens noise and hides differences.",
    });
  } else if (n) {
    items.push({
      id: "forensics.noise.unmeasured",
      category: "forensics",
      kind: "unknown",
      level: "UNKNOWN",
      claim: "Noise consistency could not be measured.",
      source: "noise",
      detail: n.observation,
    });
  }

  const cm = f.copy_move;
  if (cm?.detected) {
    const m = cm.matches[0];
    items.push({
      id: "forensics.copy-move.detected",
      category: "forensics",
      kind: "signal",
      level: "POSSIBLE",
      claim: `${cm.matches.length} region(s) of the image reappear elsewhere in the same image, shifted by a constant offset.`,
      source: "copy_move",
      detail: m
        ? `Largest: ${m.width} × ${m.height} px at (${m.source_x}, ${m.source_y}) reappears at (${m.target_x}, ${m.target_y}); ${m.pairs} matching block pairs.`
        : undefined,
      limitation:
        "Tiles, brickwork, text and identical products repeat legitimately. Consistent with cloning, not proof of it.",
    });
  } else if (cm?.measured) {
    items.push({
      id: "forensics.copy-move.none",
      category: "forensics",
      kind: "signal",
      level: "UNKNOWN",
      claim: "No translated duplicate regions were found.",
      source: "copy_move",
      detail: cm.observation,
      limitation:
        "Rotated, scaled or retouched copies and clones inside flat areas are not detected.",
    });
  } else if (cm) {
    items.push({
      id: "forensics.copy-move.unmeasured",
      category: "forensics",
      kind: "unknown",
      level: "UNKNOWN",
      claim: "The image is too small for block matching.",
      source: "copy_move",
    });
  }

  // docs/07: several *independent* anomalies are STRONG. ELA and the compression grid are one
  // correlated family; noise and copy-move are independent of it and of each other. Resampling
  // is routine processing history and never counts as an anomaly.
  const families: string[] = [];
  if (f.ela?.anomaly || f.compression?.anomaly) families.push("error level / compression");
  if (n?.anomaly) families.push("noise");
  if (cm?.detected) families.push("copy-move");
  if (families.length >= 2) {
    items.unshift({
      id: "forensics.multiple",
      category: "forensics",
      kind: "signal",
      level: "STRONG",
      claim: `${families.length} independent forensic methods flag anomalies (${families.join(", ")}).`,
      source: "forensics",
      detail:
        "Independent heuristics agreeing raises the weight of the observation. Each remains a heuristic with the failure modes listed on its card.",
      limitation:
        "Repeated content, depth of field and detail-rich areas can trip more than one method on an unedited photo. Strong is not proof.",
    });
  }
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

function deriveTextEvidence(
  a: AnalysisResponse,
  text: TextAnalysisResponse | null,
  fingerprints: TextFingerprintsResponse | null,
  ai: AIDetectionResponse | null,
  sources: SourceMatchesResponse | null,
): EvidenceItem[] {
  const items: EvidenceItem[] = [];
  if (a.file) {
    items.push({
      id: "text.identity",
      category: "file",
      kind: "fact",
      level: "VERIFIED",
      claim: `The submitted text is ${a.file.size_bytes ?? "?"} bytes of UTF-8 with SHA-256 ${a.file.sha256.slice(0, 12)}…`,
      source: "storage",
      detail: "Stored exactly as received; the normalised working copy is hashed separately.",
    });
  }
  if (!text) {
    items.push({
      id: "text.unprocessed",
      category: "text",
      kind: "unknown",
      level: "UNKNOWN",
      claim: "Text statistics are not available yet.",
      source: "text",
    });
  } else {
    const s = text.statistics;
    items.push({
      id: "text.stats",
      category: "text",
      kind: "fact",
      level: "VERIFIED",
      claim: `${Number(s.word_count ?? 0).toLocaleString()} words, ${Number(
        s.sentence_count ?? 0,
      ).toLocaleString()} sentences, ${Number(s.paragraph_count ?? 0).toLocaleString()} paragraphs.`,
      source: "statistics",
      detail: "Deterministic counts over the normalised text.",
    });
    if (text.language?.language) {
      items.push({
        id: "text.language",
        category: "text",
        kind: "signal",
        level: (text.language.confidence ?? 0) >= 0.9 ? "PROBABLE" : "POSSIBLE",
        claim: `The text is most likely written in "${text.language.language}" (p≈${text.language.confidence?.toFixed(2)}).`,
        source: `language/${text.language.engine}`,
        limitation: "Statistical detection; short or mixed-language texts are often misclassified.",
      });
    } else {
      items.push({
        id: "text.language.unknown",
        category: "text",
        kind: "unknown",
        level: "UNKNOWN",
        claim: "The language could not be determined.",
        source: "language",
        limitation: text.language?.reason ?? undefined,
      });
    }
    const hidden =
      Number(text.normalization.zero_width_removed ?? 0) +
      Number(text.normalization.bidi_controls_removed ?? 0) +
      Number(text.normalization.control_chars_removed ?? 0);
    if (hidden > 0) {
      items.push({
        id: "text.hidden",
        category: "text",
        kind: "signal",
        level: "POSSIBLE",
        claim: `${hidden} hidden or control characters were present in the original text.`,
        source: "normalize",
        limitation:
          "Such characters can come from ordinary copy-paste, but also from watermarking or obfuscation.",
      });
    }
    if (Number(s.repeated_sentence_count ?? 0) > 0) {
      items.push({
        id: "text.repetition",
        category: "text",
        kind: "signal",
        level: "POSSIBLE",
        claim: `${s.repeated_sentence_count} sentence(s) are repeated verbatim.`,
        source: "statistics",
        limitation: "Repetition is a stylistic observation, not evidence of machine authorship.",
      });
    }
  }
  if (fingerprints) {
    const identical = fingerprints.similar.filter((s) => s.relation !== "near");
    const near = fingerprints.similar.filter((s) => s.relation === "near");
    if (identical.length) {
      items.push({
        id: "matches.text.identical",
        category: "matches",
        kind: "fact",
        level: "VERIFIED",
        claim: `${identical.length} of your other text analyses contain the same text (identical bytes, or identical after normalisation / ignoring case and punctuation).`,
        source: "fingerprints",
        limitation: "Identity says nothing about which copy came first.",
      });
    }
    if (near.length) {
      items.push({
        id: "matches.text.near",
        category: "matches",
        kind: "signal",
        level: "POSSIBLE",
        claim: `${near.length} of your other text analyses share many 5-word sequences (estimated Jaccard ≥ ${fingerprints.near_threshold.toFixed(2)}).`,
        source: "fingerprints",
        limitation:
          "Shared phrasing can come from quotation, templates or common idiom, not only copying.",
      });
    }
  }
  items.push(aiEvidence(ai), sourcesEvidence(sources, "phrase"));
  return items;
}

/** Search results per docs/07: a reverse/phrase match is POSSIBLE; no search is UNKNOWN. */
function sourcesEvidence(
  sources: SourceMatchesResponse | null,
  kind: "reverse-image" | "phrase",
): EvidenceItem {
  if (!sources) {
    return {
      id: "sources.unavailable",
      category: "sources",
      kind: "unknown",
      level: "UNKNOWN",
      claim: `No ${kind} search was performed.`,
      source: "search",
      limitation: "No source-search provider is configured.",
    };
  }
  const src = `search/${sources.provider}@${sources.provider_version}`;
  if (sources.matches.length === 0) {
    return {
      id: "sources.none",
      category: "sources",
      kind: "unknown",
      level: "UNKNOWN",
      claim: `The ${kind} search returned no matches.`,
      source: src,
      limitation:
        "The provider's index is not the whole web; no matches is not evidence of originality.",
    };
  }
  const withDates = sources.matches.filter((m) => m.published_at).length;
  return {
    id: "sources.matches",
    category: "sources",
    kind: "signal",
    level: "POSSIBLE",
    claim: `The ${kind} search found ${sources.matches.length} similar ${sources.matches.length === 1 ? "source" : "sources"}${withDates ? ` (${withDates} with a reported date)` : ""}.`,
    source: src,
    limitation:
      kind === "phrase"
        ? "Shared wording can come from quotation, common phrasing or the same upstream source; a phrase match is not plagiarism."
        : "A reverse-image hit shows where similar content was found, not where it came from or which copy is earlier.",
  };
}

/** Detector output per docs/07: high -> PROBABLE, medium -> POSSIBLE; never a fact. */
function aiEvidence(ai: AIDetectionResponse | null): EvidenceItem {
  if (!ai) {
    return {
      id: "ai.unavailable",
      category: "ai",
      kind: "unknown",
      level: "UNKNOWN",
      claim: "AI-generation signals were not evaluated.",
      source: "ai-detector",
      limitation: "No detector is configured. Detector output is never proof of authorship.",
    };
  }
  const src = `ai/${ai.provider}:${ai.model}@${ai.provider_version}`;
  if (ai.score == null) {
    return {
      id: "ai.noscore",
      category: "ai",
      kind: "unknown",
      level: "UNKNOWN",
      claim: "The AI detector returned no usable score.",
      source: src,
    };
  }
  const pct = Math.round(ai.score * 100);
  if (ai.evidence_level === "UNKNOWN") {
    return {
      id: "ai.weak",
      category: "ai",
      kind: "signal",
      level: "UNKNOWN",
      claim: `The AI detector reported a weak signal (${pct}/100, below the medium threshold).`,
      source: src,
      limitation:
        "A low score does not establish human authorship; detectors miss much AI text and imagery.",
    };
  }
  return {
    id: "ai.signal",
    category: "ai",
    kind: "signal",
    level: ai.evidence_level,
    claim: `The AI detector reported a ${ai.evidence_level === "PROBABLE" ? "strong" : "medium"} AI-generation signal (${pct}/100).`,
    source: src,
    limitation: ai.calibrated
      ? "Detector scores have known false-positive and false-negative rates; this is not proof of AI authorship."
      : "The score is not calibrated and has known false-positive and false-negative rates; this is not proof of AI authorship.",
  };
}
