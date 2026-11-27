class UpstreamError(Exception):
    """An upstream HTTP attempt failed."""


class UpstreamTimeoutError(UpstreamError):
    """The HTTP attempt exceeded its deadline or an HTTPX I/O timeout."""


class UpstreamConnectionError(UpstreamError):
    """The connection to the upstream node failed."""


class UpstreamPoolTimeoutError(UpstreamError):
    """The local HTTP client could not acquire a pooled connection in time."""
