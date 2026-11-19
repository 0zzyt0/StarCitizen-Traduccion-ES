"""Excepciones con mensajes en español pensados para el jugador."""


class SCTradError(Exception):
    """Error base. El mensaje se puede mostrar tal cual al jugador."""

    def __init__(self, message: str, detail: str | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail

    def __str__(self) -> str:
        return self.message


class ConfigError(SCTradError):
    pass


class NetworkError(SCTradError):
    pass


class RateLimitError(NetworkError):
    pass


class IntegrityError(SCTradError):
    pass


class ManifestError(SCTradError):
    pass


class IncompatibleError(SCTradError):
    pass


class GameRunningError(SCTradError):
    pass


class UnsafePathError(SCTradError):
    pass


class ForeignFileError(SCTradError):
    pass


class InstallError(SCTradError):
    pass


class PermissionNeededError(InstallError):
    pass


class BusyError(SCTradError):
    pass
