/**
 * Types shared between the web app and the API.
 * Keep these in sync with the Pydantic schemas in `services/api/app/schemas/`.
 */

export type { AIDetectionResponse, AILabel } from "./ai";
export type {
  AnalysisCounts,
  AnalysisCreatedResponse,
  AnalysisFileLink,
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
export type {
  EvidenceKind,
  EvidenceLevel,
  EvidenceListResponse,
  EvidenceRecord,
  SynthesisCitation,
  SynthesisResponse,
  SynthesisSection,
  TimelineEvent,
  TimelineResponse,
} from "./evidence";
export { EVIDENCE_LEVELS } from "./evidence";
export type {
  Fingerprints,
  ImageFingerprintsResponse,
  SimilarAnalysis,
  SimilarText,
  TextFingerprints,
  TextFingerprintsResponse,
} from "./fingerprints";
export type {
  ImageProvenanceResponse,
  NormalizedProvenance,
  ProvenanceAction,
  ProvenanceValidationFailure,
} from "./provenance";
export type {
  BlockGrid,
  CloneMatch,
  CompressionEncoding,
  CompressionFinding,
  CopyMoveFinding,
  ELAFinding,
  ForensicArtifact,
  ForensicConfidence,
  ForensicRegion,
  ForensicSkipped,
  ImageForensicsResponse,
  NoiseFinding,
  NoiseRegion,
  ResamplingFinding,
  SpectralPeak,
} from "./forensics";
export type {
  ImageMetadataResponse,
  NormalizedMetadata,
  ParsedTimestamp,
  RawTagGroup,
} from "./metadata";
export type { HealthResponse } from "./health";
export type { SourceKind, SourceMatch, SourceMatchesResponse } from "./matches";
export type {
  ProviderCall,
  ProviderCallsResponse,
  ProviderCallStatus,
} from "./provider-calls";
export type {
  LanguageGuess,
  TextAnalysisCreate,
  TextAnalysisResponse,
} from "./text";
export { TEXT_INPUT } from "./text";
