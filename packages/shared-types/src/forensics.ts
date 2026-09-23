/** Mirrors `app/schemas/forensics.py`. */

export type ForensicConfidence = "low" | "medium" | "high";

/** Bounding box in original image pixels. */
export interface ForensicRegion {
  x: number;
  y: number;
  width: number;
  height: number;
  blocks: number;
  mean_error: number;
}

export interface ELAFinding {
  method: "ela";
  version: string;
  observation: string;
  confidence: ForensicConfidence;
  /** Localised outlier regions were found within the configured band. Never proof on its own. */
  anomaly: boolean;
  quality: number;
  original_width: number;
  original_height: number;
  working_width: number;
  working_height: number;
  downscaled: boolean;
  mean_error: number;
  std_error: number;
  p95_error: number;
  max_error: number;
  block_size: number;
  outlier_sigma: number;
  outlier_block_fraction: number;
  regions: ForensicRegion[];
  limitations: string[];
}

/** Facts read from the JPEG headers (last save only). */
export interface CompressionEncoding {
  progressive: boolean;
  subsampling: string | null;
  table_count: number;
  estimated_quality: number | null;
  standard_tables: boolean;
  luma_table_error: number | null;
  chroma_estimated_quality: number | null;
  has_jfif: boolean;
  has_adobe: boolean;
}

export interface BlockGrid {
  measured: boolean;
  aligned_strength: number;
  offset_x: number;
  offset_y: number;
  offset_strength: number;
  detected_aligned: boolean;
  detected_offset: boolean;
  profile_x: number[];
  profile_y: number[];
}

export interface CompressionFinding {
  method: "compression";
  version: string;
  observation: string;
  confidence: ForensicConfidence;
  format: string;
  lossless_container: boolean;
  encoding: CompressionEncoding | null;
  grid: BlockGrid;
  /** JPEG with a second, offset block grid (crop/shift then re-save). */
  anomaly: boolean;
  /** Non-JPEG file carrying a JPEG block grid (was probably a JPEG once). */
  prior_jpeg_grid: boolean;
  limitations: string[];
}

/** Normalised frequency (cycles per pixel) and magnitude relative to the local background. */
export interface SpectralPeak {
  fx: number;
  fy: number;
  ratio: number;
}

export interface ResamplingFinding {
  method: "resampling";
  version: string;
  observation: string;
  confidence: ForensicConfidence;
  measured: boolean;
  width: number;
  height: number;
  tiles: number;
  tile_size: number;
  peak_ratio: number;
  peaks: SpectralPeak[];
  /** Periodic correlations consistent with a global rescale/rotation. Not evidence of editing. */
  detected: boolean;
  limitations: string[];
}

/** Bounding box in original image pixels; `sigma` is the region's mean noise estimate. */
export interface NoiseRegion {
  x: number;
  y: number;
  width: number;
  height: number;
  blocks: number;
  sigma: number;
}

export interface NoiseFinding {
  method: "noise";
  version: string;
  observation: string;
  confidence: ForensicConfidence;
  measured: boolean;
  width: number;
  height: number;
  block_size: number;
  blocks_total: number;
  blocks_smooth: number;
  baseline_sigma: number;
  spread_sigma: number;
  outlier_fraction: number;
  regions: NoiseRegion[];
  /** Compact regions whose noise level departs from the baseline. Never proof on its own. */
  anomaly: boolean;
  limitations: string[];
}

/** A source region that reappears displaced by (shift_x, shift_y); original pixel coords. */
export interface CloneMatch {
  source_x: number;
  source_y: number;
  target_x: number;
  target_y: number;
  width: number;
  height: number;
  shift_x: number;
  shift_y: number;
  pairs: number;
  density: number;
}

export interface CopyMoveFinding {
  method: "copy_move";
  version: string;
  observation: string;
  confidence: ForensicConfidence;
  measured: boolean;
  width: number;
  height: number;
  working_width: number;
  working_height: number;
  downscaled: boolean;
  blocks_total: number;
  blocks_textured: number;
  candidate_pairs: number;
  matches: CloneMatch[];
  /** Translated duplicate region(s) found. Repeated real content gives the same signal. */
  detected: boolean;
  limitations: string[];
}

export interface ThumbnailRegion {
  x: number;
  y: number;
  width: number;
  height: number;
  blocks: number;
  /** Mean normalised-intensity difference over the region. */
  mean_diff: number;
}

export interface ThumbnailFinding {
  method: "thumbnail";
  version: string;
  observation: string;
  confidence: ForensicConfidence;
  has_thumbnail: boolean;
  thumbnail_width: number;
  thumbnail_height: number;
  original_width: number;
  original_height: number;
  aspect_ratio_thumbnail: number;
  aspect_ratio_image: number;
  aspect_mismatch: boolean;
  correlation: number;
  correlation_outside_regions: number;
  best_transform: "none" | "flip_h" | "flip_v" | "rotate_180";
  best_transform_correlation: number;
  orientation_mismatch: boolean;
  block_size: number;
  outlier_sigma: number;
  outlier_block_fraction: number;
  regions: ThumbnailRegion[];
  /** The thumbnail depicts different content from the current image. */
  mismatch_global: boolean;
  /** Only part of the image differs from its thumbnail. */
  anomaly: boolean;
  flagged: boolean;
  limitations: string[];
}

export interface GhostRegion {
  x: number;
  y: number;
  width: number;
  height: number;
  blocks: number;
  /** Normalised dip depth of the ghost over the region. */
  depth: number;
}

export interface DoubleCompressionFinding {
  method: "double_compression";
  version: string;
  observation: string;
  confidence: ForensicConfidence;
  original_width: number;
  original_height: number;
  working_width: number;
  working_height: number;
  cropped: boolean;
  last_quality: number | null;
  standard_tables: boolean | null;
  qualities: number[];
  curve: number[];
  primary_quality: number;
  secondary_quality: number | null;
  secondary_depth: number;
  dc_periodicity: number;
  dc_period: number | null;
  periodic: boolean;
  block_size: number;
  ghost_block_fraction: number;
  ghost_quality_local: number | null;
  regions: GhostRegion[];
  /** Whole image compressed at least twice (earlier at a lower quality). */
  detected: boolean;
  /** Only part of the image carries the ghost. */
  anomaly: boolean;
  limitations: string[];
}

export interface ForensicSkipped {
  method: string;
  reason: string;
}

export interface ForensicArtifact {
  name: string;
  method: string;
  content_type: string;
  width: number;
  height: number;
  /** Short-lived signed URL. */
  url: string;
  expires_in_seconds: number;
}

export interface ImageForensicsResponse {
  ela: ELAFinding | null;
  compression: CompressionFinding | null;
  resampling: ResamplingFinding | null;
  noise: NoiseFinding | null;
  copy_move: CopyMoveFinding | null;
  thumbnail: ThumbnailFinding | null;
  double_compression: DoubleCompressionFinding | null;
  skipped: ForensicSkipped[];
  artifacts: ForensicArtifact[];
  limitations: string[];
}
