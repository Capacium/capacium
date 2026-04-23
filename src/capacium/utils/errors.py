class CapaciumError(Exception):
    pass


class CapabilityNotFoundError(CapaciumError):
    pass


class CapabilityAlreadyInstalledError(CapaciumError):
    pass


class InvalidManifestError(CapaciumError):
    pass


class FingerprintMismatchError(CapaciumError):
    pass


class FrameworkNotSupportedError(CapaciumError):
    pass
