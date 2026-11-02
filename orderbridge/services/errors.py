"""Business errors. Each carries the HTTP status code the REST API should use."""


class DomainError(Exception):
    """Base class for expected, user-facing business errors."""

    status_code = 400


class NotFoundError(DomainError):
    status_code = 404


class InvalidInputError(DomainError):
    status_code = 422


class ConflictError(DomainError):
    status_code = 409
