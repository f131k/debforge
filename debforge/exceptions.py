class DebforgeError(Exception):
    pass


class ConfigError(DebforgeError):
    pass


class DownloadError(DebforgeError):
    pass


class BuildError(DebforgeError):
    pass


class SigningError(DebforgeError):
    pass


class PublishError(DebforgeError):
    pass


class DockerError(DebforgeError):
    pass
