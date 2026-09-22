"""Application error types with stable client-facing codes.

Services raise these; the API layer renders them in the documented error
format. Messages must be safe to show to clients (no internals, no secrets).
"""


class AppError(Exception):
    status_code: int = 400
    code: str = "BAD_REQUEST"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code


class ValidationError(AppError):
    status_code = 422
    code = "VALIDATION_ERROR"


class UnauthorizedError(AppError):
    status_code = 401
    code = "UNAUTHORIZED"


class ForbiddenError(AppError):
    status_code = 403
    code = "FORBIDDEN"


class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"


class ConflictError(AppError):
    status_code = 409
    code = "CONFLICT"


class LimitExceededError(AppError):
    """A configured usage limit would be exceeded (monthly count, storage, provider budget)."""

    status_code = 429
    code = "USAGE_LIMIT_EXCEEDED"


class RateLimitedError(AppError):
    """Too many attempts in the window; ``retry_after`` becomes the Retry-After header."""

    status_code = 429
    code = "RATE_LIMITED"

    def __init__(self, message: str, *, retry_after: int, code: str | None = None) -> None:
        super().__init__(message, code=code)
        self.retry_after = max(1, int(retry_after))
