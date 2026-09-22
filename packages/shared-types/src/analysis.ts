/** Mirrors `app/schemas/analysis.py` and `app/enums.py`. */

export type AnalysisType = "image" | "text";
export type AnalysisStatus = "queued" | "processing" | "completed" | "failed";

/** Client-safe view of the stored original; storage keys are never exposed. */
export interface AnalysisFileResponse {
  original_filename: string | null;
  mime_type: string | null;
  size_bytes: number | null;
  sha256: string;
  width: number | null;
  height: number | null;
}

export interface AnalysisResponse {
  id: string;
  type: AnalysisType;
  status: AnalysisStatus;
  title: string | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
  file: AnalysisFileResponse | null;
}

export interface AnalysisCreatedResponse {
  id: string;
  status: AnalysisStatus;
  type: AnalysisType;
}

export interface AnalysisListResponse {
  items: AnalysisResponse[];
  page: number;
  page_size: number;
  total: number;
}

export interface AnalysisCounts {
  total: number;
  image: number;
  text: number;
}

/** Upload constraints enforced by the API (client checks are a courtesy only). */
export const IMAGE_UPLOAD = {
  acceptedMimeTypes: ["image/jpeg", "image/png", "image/webp", "image/tiff"],
  maxBytes: 25 * 1024 * 1024,
} as const;
