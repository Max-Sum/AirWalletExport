from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

EXIT_OK = 0
EXIT_OPERATION_ERROR = 1
EXIT_USAGE = 2
EXIT_RECOVERY_REQUIRED = 3
EXIT_UNSUPPORTED = 4


@dataclass(eq=False)
class AirWalletError(Exception):
    message: str
    exit_code: int = EXIT_OPERATION_ERROR
    recovery_required: bool = False
    context: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__init__(self.message)


class UsageError(AirWalletError):
    def __init__(self, message: str) -> None:
        super().__init__(message, exit_code=EXIT_USAGE)


class OperationError(AirWalletError):
    pass


class MissingResource(OperationError):
    pass


class RecoveryRequiredError(AirWalletError):
    def __init__(self, message: str, **context: Any) -> None:
        super().__init__(
            message,
            exit_code=EXIT_RECOVERY_REQUIRED,
            recovery_required=True,
            context=context,
        )


class UnsupportedError(AirWalletError):
    def __init__(self, message: str) -> None:
        super().__init__(message, exit_code=EXIT_UNSUPPORTED)
