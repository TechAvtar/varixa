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
  /** Recorded GPS values (decimal degrees, metres, receiver UTC time); editable, never verified. */
  gps_latitude: number | null;
  gps_longitude: number | null;
  gps_altitude_m: number | null;
  gps_time: ParsedTimestamp | null;
  color_profile: string | null;
  /** Declared lineage: generator markers, IPTC digital source type, XMP document ids/history. */
  generator: string | null;
  generator_signals: GeneratorSignal[];
  digital_source_type: string | null;
  creator_tool: string | null;
  document_id: string | null;
  instance_id: string | null;
  original_document_id: string | null;
  derived_from_document_id: string | null;
  edit_history: EditEvent[];
  image_width: number | null;
  image_height: number | null;
  tag_counts: Record<string, number>;
  warnings: string[];
}

export interface GeneratorSignal {
  generator: string;
  /** Where the marker was found, e.g. "PNG:Parameters". */
  tag: string;
  /** Bounded text of the marker; may contain the generation prompt. */
  excerpt: string;
}

export interface EditEvent {
  action: string;
  software: string | null;
  /** As recorded in XMP. */
  when: string | null;
  changed: string | null;
  instance_id: string | null;
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
