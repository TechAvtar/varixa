/** Mirrors `app/schemas/report.py`. */

export interface ReportCreate {
  format: "pdf";
}

export interface ReportResponse {
  id: string;
  analysis_id: string;
  format: string;
  status: "completed" | "failed" | "expired";
  created_at: string;
  size_bytes: number | null;
  sha256: string | null;
  page_count: number | null;
  summary: Record<string, unknown>;
  error_code: string | null;
  error_message: string | null;
}

export interface ReportListResponse {
  items: ReportResponse[];
}

/** Short-lived signed URL for the rendered file; never a storage key. */
export interface ReportFileLink {
  url: string;
  expires_in_seconds: number;
  content_type: string;
}
