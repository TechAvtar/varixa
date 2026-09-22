/** Mirrors `app/schemas/metadata.py`. */

export interface ParsedTimestamp {
  /** Exactly as recorded in the file. */
  raw: string;
  /** ISO-8601 when parseable; carries an offset only when `tz_known`. */
  parsed: string | null;
  tz_known: boolean;
}

export interface NormalizedMetadata {
  engine: string;
  engine_version: string;
  has_exif: boolean;
  has_xmp: boolean;
  has_iptc: boolean;
  has_icc: boolean;
  has_makernotes: boolean;
  camera_make: string | null;
  camera_model: string | null;
  lens: string | null;
  software: string | null;
  captured_at: ParsedTimestamp | null;
  modified_at: ParsedTimestamp | null;
  orientation: number | null;
  orientation_label: string | null;
  gps_present: boolean;
  color_profile: string | null;
  image_width: number | null;
  image_height: number | null;
  tag_counts: Record<string, number>;
  warnings: string[];
}

export type RawTagGroup = Record<string, unknown>;

export interface ImageMetadataResponse {
  normalized: NormalizedMetadata;
  exif: RawTagGroup;
  xmp: RawTagGroup;
  iptc: RawTagGroup;
  icc: RawTagGroup;
  other: Record<string, RawTagGroup>;
  /** Plain-language caveats that must be shown alongside the values. */
  limitations: string[];
}
