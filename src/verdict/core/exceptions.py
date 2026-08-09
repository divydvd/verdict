class VerdictError(Exception):
    """Base exception for all Verdict platform errors."""


class DriverError(VerdictError):
    """Raised when a DeviceDriver operation fails."""


class ElementNotFoundError(DriverError):
    """Raised when a Selector matches no element in the current UI hierarchy."""


class WaitTimeoutError(DriverError):
    """Raised when wait_for exceeds its timeout without the selector appearing."""


class ScenarioValidationError(VerdictError):
    """Raised when a scenario spec fails schema validation."""
