class ExportError(Exception):
    """An actionable failure that is safe to display without raw response data."""


class EmptyResultError(ExportError):
    """An empty response cannot prove that the account has product access."""


class RetryableError(ExportError):
    """A completed HTTP request returned a temporary server failure."""
