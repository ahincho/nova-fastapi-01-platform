# nova-fastapi

Meta-framework de **Nova Platform** para FastAPI. Es el equivalente en Python de
[`@ahincho/nova-nestjs`](https://github.com/ahincho/nova-nestjs-01-platform) y de
los starters de Spring Boot y Quarkus: un servicio instala Nova con una línea y
responde como cualquier otro servicio de la plataforma.

Lo que trae hoy es el estándar de API: el sobre de las respuestas, el módulo de
errores por capas de
[ADR-031](https://github.com/ahincho/nova-shared-01-docs/blob/main/adrs/shared/ADR-031-modulo-de-errores-por-capas-con-trazabilidad.md)
y la correlación de cada petición de ADR-037. La decisión de sumar Python como
stack de Nova está en ADR-057.

## Instalación

GitHub Packages no tiene registro de Python, así que el paquete se instala desde
este repositorio, fijado a un tag:

```toml
# pyproject.toml del servicio
dependencies = [
  "nova-fastapi @ git+https://github.com/ahincho/nova-fastapi-01-platform@v0.1.0",
]
```

Es la única dependencia de runtime que hace falta: FastAPI llega con ella.

## Uso

```python
from fastapi import FastAPI
from nova_fastapi import install_nova

app = FastAPI()
install_nova(app)
```

Con eso:

- **Toda excepción sale con el sobre de Nova**: las de Nova, las de FastAPI y
  Starlette, la validación (400, con un error por campo) y lo no previsto (500,
  sin nada interno). Cada una deja una línea de log con su capa.
- **Cada petición tiene su id**: el que trae en `x-request-id`, o uno nuevo. Se
  devuelve en la misma cabecera y va en `metadata.traceId` de cada error.
- **Las rutas de `app` envuelven su éxito en el sobre.** Las de un `APIRouter`,
  con `route_class=NovaRoute`.
- **`/docs` documenta los errores con el sobre**, y no con el 422 de FastAPI.

Conviene llamar a `install_nova` antes de agregar otros middlewares, como CORS:
los que se agregan después quedan por fuera, así que también un error no
previsto sale con sus cabeceras.

### Lanzar un error

Quien lanza no sabe de HTTP: elige la capa y el tipo, y la plataforma decide el
status, el código y el mensaje que ve el cliente.

```python
from nova_fastapi import ApplicationError, DomainError, FieldError, InfrastructureError

# 404
raise DomainError.not_found("Pedido no encontrado", code="ORDER_NOT_FOUND")
# 422
raise DomainError.rule_violation("No te alcanzan las monedas", code="INSUFFICIENT_COINS")
# 400, con una entrada por campo
raise ApplicationError.invalid_input("Datos inválidos", [FieldError("email", "Falta el correo")])
# 429, con Retry-After: 12
raise ApplicationError.rate_limited("Demasiadas búsquedas", retry_after=12)
# 504: el proveedor va al log, no al cliente
raise InfrastructureError.timeout("gemini", cause=e)
```

| Capa | Fábricas | HTTP | Log |
|---|---|---|---|
| `domain` | `not_found`, `conflict`, `rule_violation` | 404, 409, 422 | `warning`, sin stack |
| `application` | `invalid_input`, `conflict`, `unprocessable`, `unauthenticated`, `forbidden`, `rate_limited` | 400, 409, 422, 401, 403, 429 | `warning`, sin stack |
| `infrastructure` | `unavailable`, `timeout`, `bad_gateway` | 503, 504, 502 | `error`, con la causa |
| `platform` | `internal` | 500 | `error`, con la causa |

Un código propio llega al cliente solo en un 4xx. En un 5xx el cuerpo lleva el
código y el mensaje genéricos de su status; el proveedor y la causa van solo al
log.

### Lo que responde

```json
{
  "success": false,
  "status": 404,
  "data": null,
  "errors": [{ "code": "ORDER_NOT_FOUND", "message": "Pedido no encontrado", "field": null }],
  "metadata": { "traceId": "3f2b8c1e-5d4a-4f6b-9a7c-2e1d0b9f8a6c" }
}
```

Un éxito no lleva `metadata`: el id ya viaja en la cabecera.

```json
{ "success": true, "status": 200, "data": { "id": 7, "name": "Álgebra" }, "errors": [] }
```

### Rutas

```python
from fastapi import APIRouter
from nova_fastapi import NovaRoute, error_responses, skip_envelope

router = APIRouter(prefix="/courses", route_class=NovaRoute)


@router.get("/{course_id}", responses=error_responses(404))
def read(course_id: int) -> Course: ...


@router.get("/health")
@skip_envelope
def health() -> dict: ...
```

No se envuelve lo que no tiene cuerpo (un 204), lo que no es JSON (un
`PlainTextResponse`), una `Response` que el endpoint arma él mismo, ni lo que ya
es un sobre. El status del sobre es el que declara la ruta. Para combinar
`NovaRoute` con otra ruta propia, se hereda de las dos:
`class Route(NovaRoute, LimitedRoute)`.

### Perfiles y puertos

Lo que una organización comparte se declara una vez en su perfil (ADR-036). El
orden es siempre el mismo: lo de Nova, encima el perfil, encima el servicio.

```python
from nova_fastapi import Profile, install_nova

UTP = Profile(
    name="utp",
    request_id_accept=("transaction-id", "x-request-id"),
    catalog=UtpErrorCatalog(),
)

install_nova(app, profile=UTP)
```

Los tres puertos de ADR-031 se reemplazan igual, por perfil o por servicio:
`status_mapper` (el HTTP de cada capa y tipo), `catalog` (el código y el mensaje
que ve el cliente) y `serializer` (el cuerpo de los errores). Ningún puerto ve
el proveedor ni la causa: los recibe ya saneados, así que uno propio no puede
romper la regla del 5xx. El estándar entero se reemplaza con `standard`.

## Estructura

```
src/nova_fastapi/
├── errors/          # el modelo de ADR-031, los puertos y el catálogo; sin framework
├── api_standard/    # el sobre y el estándar de Nova; sin framework
├── observability/   # el id de la petición: el contexto y su middleware
└── api/             # el conector: install_nova, NovaRoute, los manejadores y /docs
```

`errors` y `api_standard` no importan FastAPI ni Starlette, y el paquete carga
el conector solo cuando se pide. Lo vigilan un contrato de import-linter en el
CI y una prueba que importa el núcleo en un proceso limpio.

## Diferencias con los otros stacks

- **La validación sale con `BAD_REQUEST`**, como pide ADR-031 y como responden
  Spring Boot y Quarkus. NestJS hoy responde `VALIDATION_ERROR`.
- **Sin métricas todavía**: el contador `nova.errors{layer,code}` llega cuando el
  stack tenga observabilidad.
- **El status del sobre de un éxito es el que declara la ruta.** Un endpoint que
  contesta otro status arma su propia respuesta.

## Desarrollo

```bash
uv sync
uv run ruff check . && uv run ruff format --check .
uv run pytest
uv run lint-imports
```

`tests/test_contract.py` es la suite de contrato de ADR-031: los mismos nueve
casos que corren los otros stacks.

Los commits siguen Conventional Commits (ADR-006) y las versiones las publica
release-please con un tag `vX.Y.Z` (ADR-007).

## Licencia

[EPL-2.0](LICENSE), como el resto de Nova.
