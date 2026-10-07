"""El estándar de API de Nova: el sobre de las respuestas, sin framework."""

from nova_fastapi.api_standard.envelope import (
    ApiErrorItem,
    ApiMetadata,
    ApiResponse,
    failed,
    is_api_response,
    ok,
)
from nova_fastapi.api_standard.serializer import NovaErrorSerializer
from nova_fastapi.api_standard.standard import ApiStandard, NovaEnvelopeStandard

__all__ = [
    "ApiErrorItem",
    "ApiMetadata",
    "ApiResponse",
    "ApiStandard",
    "NovaEnvelopeStandard",
    "NovaErrorSerializer",
    "failed",
    "is_api_response",
    "ok",
]
