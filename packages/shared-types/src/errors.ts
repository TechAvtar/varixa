/** Mirrors the error envelope rendered by `app/api/errors.py`. */
export interface ApiErrorBody {
  error: {
    /** Stable, machine-readable code, e.g. "UNAUTHORIZED", "VALIDATION_ERROR". */
    code: string;
    /** Safe, human-readable message. Never contains internals. */
    message: string;
    /** Correlation id; also returned in the `X-Request-ID` header. */
    request_id: string;
  };
}
