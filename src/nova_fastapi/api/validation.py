"""
De un fallo de validación de FastAPI a los errores por campo de Nova.

Cada campo sale con un mensaje en español para la persona y nunca con el valor
recibido: puede ser el contenido de un documento o un dato personal.
"""

from collections.abc import Iterable, Mapping
from typing import Any

from nova_fastapi.errors.nova_error import FieldError

# El mensaje de cada tipo de error de pydantic. Puede usar los límites del error
# (`ctx`), nunca el valor recibido.
FIELD_MESSAGES: Mapping[str, str] = {
    "missing": "Falta este dato",
    "extra_forbidden": "Este dato no se acepta",
    "string_too_short": "Debe tener al menos {min_length} caracteres",
    "string_too_long": "Puede tener hasta {max_length} caracteres",
    "too_short": "Debe tener al menos {min_length} elementos",
    "too_long": "Puede tener hasta {max_length} elementos",
    "greater_than": "Debe ser mayor que {gt}",
    "greater_than_equal": "Debe ser como mínimo {ge}",
    "less_than": "Debe ser menor que {lt}",
    "less_than_equal": "Puede ser como máximo {le}",
    "string_pattern_mismatch": "No tiene el formato esperado",
    "enum": "No es una de las opciones válidas",
    "literal_error": "No es una de las opciones válidas",
    "int_parsing": "Debe ser un número entero",
    "int_type": "Debe ser un número entero",
    "float_parsing": "Debe ser un número",
    "float_type": "Debe ser un número",
    "bool_parsing": "Debe ser verdadero o falso",
    "bool_type": "Debe ser verdadero o falso",
    "string_type": "Debe ser un texto",
    "uuid_parsing": "No es un identificador válido",
    "date_from_datetime_parsing": "No es una fecha válida",
    "datetime_from_date_parsing": "No es una fecha y hora válida",
    "json_invalid": "El cuerpo no es un JSON válido",
}
DEFAULT_FIELD_MESSAGE = "Este dato no es válido"

# Las partes de la petición: no son parte del nombre del campo.
_SOURCES = {"body", "query", "path", "header", "cookie"}


def field_error(error: Mapping[str, Any]) -> FieldError:
    """Un error de pydantic como error de campo de Nova."""
    location = [str(part) for part in error.get("loc", ())]
    if location and location[0] in _SOURCES:
        location = location[1:]
    template = FIELD_MESSAGES.get(error.get("type", ""), DEFAULT_FIELD_MESSAGE)
    try:
        message = template.format(**error.get("ctx", {}))
    except (KeyError, IndexError):
        message = DEFAULT_FIELD_MESSAGE
    # Un error del objeto entero, sin un campo propio, lleva `field` vacío.
    return FieldError(field=".".join(location), message=message)


def field_errors(errors: Iterable[Mapping[str, Any]]) -> tuple[FieldError, ...]:
    return tuple(field_error(error) for error in errors)
