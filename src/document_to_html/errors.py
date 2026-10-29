class ConversionError(Exception):
    """An actionable conversion failure safe to display to the user."""


class BackendUnavailable(ConversionError):
    """A Word-to-PDF backend is not installed or cannot start."""
