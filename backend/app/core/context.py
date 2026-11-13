"""Request-scoped context (request id) shared by logging and the audit log."""

from contextvars import ContextVar

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
