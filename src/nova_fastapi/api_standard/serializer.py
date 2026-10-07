"""El `ErrorSerializer` de Nova: el sobre, con `metadata.traceId` y `Retry-After`."""

from nova_fastapi.api_standard.envelope import ApiErrorItem, failed
from nova_fastapi.errors.catalog import ErrorCodes
from nova_fastapi.errors.failure import ApiFailure, ApiWire


class NovaErrorSerializer:
    """
    Escribe un fallo con el sobre de Nova. Es también lo que contesta
    `NovaEnvelopeStandard` para un error, así que el sobre se escribe en un solo
    lugar.

        # ApplicationError.rate_limited("Demasiadas solicitudes", retry_after=30)
        # Retry-After: 30
        {
          "success": false, "status": 429, "data": null,
          "errors": [{"code": "TOO_MANY_REQUESTS", "message": "Demasiadas solicitudes", "field": null}],
          "metadata": {"traceId": "b3f1c2d4-..."}
        }
    """

    def __init__(self, codes: ErrorCodes | None = None) -> None:
        self._codes = codes or ErrorCodes()

    def serialize(self, failure: ApiFailure) -> ApiWire:
        envelope = failed(
            failure.status,
            [
                ApiErrorItem(
                    # El núcleo siempre trae el código. Sin él -alguien llamó al
                    # serializador a mano- se usa el del catálogo.
                    code=item.code or self._codes.code_for(failure.status, failure.kind),
                    message=item.message,
                    field=item.field,
                )
                for item in failure.errors
            ],
            trace_id=failure.trace_id,
        )
        headers = {} if failure.retry_after is None else {"Retry-After": str(failure.retry_after)}
        return ApiWire(body=envelope.model_dump(mode="json", by_alias=True), headers=headers)
