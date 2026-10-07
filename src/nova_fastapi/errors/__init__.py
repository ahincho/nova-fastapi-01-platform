"""
El módulo de errores de Nova (ADR-031), sin framework.

Se lanza un error por capa con su fábrica, y la plataforma decide el status, el
código y el mensaje que ve el cliente:

    from nova_fastapi.errors import DomainError

    raise DomainError.not_found("Pedido no encontrado", code="ORDER_NOT_FOUND")
"""

from nova_fastapi.errors.catalog import (
    DEFAULT_ERROR_CODE,
    INTERNAL_ERROR_CODE,
    VALIDATION_ERROR_CODE,
    ErrorCodes,
    NovaErrorCatalog,
    status_to_error_message,
)
from nova_fastapi.errors.failure import ApiFailure, ApiFailureItem, ApiFailureKind, ApiWire
from nova_fastapi.errors.layer import (
    ApplicationErrorType,
    DomainErrorType,
    ErrorType,
    InfrastructureErrorType,
    Layer,
    PlatformErrorType,
)
from nova_fastapi.errors.nova_error import (
    ApplicationError,
    DomainError,
    FieldError,
    InfrastructureError,
    NovaError,
    PlatformError,
)
from nova_fastapi.errors.ports import (
    ErrorCatalog,
    ErrorClassification,
    ErrorDescription,
    ErrorSerializer,
    ErrorStatusMapper,
    SanitizedError,
)
from nova_fastapi.errors.status_mapper import NovaErrorStatusMapper

__all__ = [
    "ApiFailure",
    "ApiFailureItem",
    "ApiFailureKind",
    "ApiWire",
    "DEFAULT_ERROR_CODE",
    "INTERNAL_ERROR_CODE",
    "VALIDATION_ERROR_CODE",
    "ApplicationError",
    "ApplicationErrorType",
    "DomainError",
    "DomainErrorType",
    "ErrorCatalog",
    "ErrorClassification",
    "ErrorCodes",
    "ErrorDescription",
    "ErrorSerializer",
    "ErrorStatusMapper",
    "ErrorType",
    "FieldError",
    "InfrastructureError",
    "InfrastructureErrorType",
    "Layer",
    "NovaError",
    "NovaErrorCatalog",
    "NovaErrorStatusMapper",
    "PlatformError",
    "PlatformErrorType",
    "SanitizedError",
    "status_to_error_message",
]
