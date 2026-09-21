/** Mirrors `app/schemas/analysis.py` and `app/models/enums.py`. */

export type AnalysisType = "image" | "text";
export type AnalysisStatus = "queued" | "processing" | "completed" | "failed";

export interface AnalysisResponse {
  id: string;
  type: AnalysisType;
  status: AnalysisStatus;
  title: string | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
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
