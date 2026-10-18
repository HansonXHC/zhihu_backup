"""Exception types used by the backup tool."""


class ZhihuBackupError(Exception):
    """Base exception for all expected failures."""


class AuthError(ZhihuBackupError):
    """Cookies are missing, expired or rejected by Zhihu."""


class ApiError(ZhihuBackupError):
    """A Zhihu API request failed or returned an unusable payload."""


class EnumerationError(ZhihuBackupError):
    """Enumerating a user's content failed part-way through."""

    def __init__(self, message, seen_ids=None):
        super().__init__(message)
        self.seen_ids = set(seen_ids or ())


class ParseError(ZhihuBackupError):
    """A page or API payload could not be parsed."""


class ImageDownloadError(ZhihuBackupError):
    """An image could not be downloaded."""


class VideoDownloadError(ZhihuBackupError):
    """A video or video segment could not be downloaded."""
