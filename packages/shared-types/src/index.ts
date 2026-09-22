/**
 * Types shared between the web app and the API.
 * Keep these in sync with the Pydantic schemas in `services/api/app/schemas/`.
 */

export type {
  AnalysisCounts,
  AnalysisCreatedResponse,
  AnalysisFileResponse,
  AnalysisListResponse,
  AnalysisResponse,
  AnalysisStatus,
  AnalysisStepResponse,
  AnalysisType,
  StepStatus,
} from "./analysis";
export { IMAGE_UPLOAD } from "./analysis";
export type {
  LoginRequest,
  RefreshRequest,
  RegisterRequest,
  TokenPair,
  UserResponse,
  UserRole,
} from "./auth";
export type { ApiErrorBody } from "./errors";
export type { EvidenceLevel } from "./evidence";
export { EVIDENCE_LEVELS } from "./evidence";
export type { Fingerprints, ImageFingerprintsResponse, SimilarAnalysis } from "./fingerprints";
export type {
  ImageProvenanceResponse,
  NormalizedProvenance,
  ProvenanceAction,
  ProvenanceValidationFailure,
} from "./provenance";
export type {
  ImageMetadataResponse,
  NormalizedMetadata,
  ParsedTimestamp,
  RawTagGroup,
} from "./metadata";
export type { HealthResponse } from "./health";
