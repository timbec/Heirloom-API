"""Error responses shaped like Laravel's, because heirloom-web reads `message`.

- HTTP errors:       {"message": "..."}
- Validation errors: 422 {"message": "...", "errors": {"field": ["..."]}}
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse({"message": exc.detail}, status_code=exc.status_code, headers=exc.headers)


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors: dict[str, list[str]] = {}
    for error in exc.errors():
        # Drop the leading "body"/"query"/"path" so keys match Laravel's field names.
        location = [str(part) for part in error["loc"][1:]] or [str(error["loc"][0])]
        errors.setdefault(".".join(location), []).append(error["msg"])

    first_field, first_messages = next(iter(errors.items()))
    return JSONResponse(
        {"message": f"{first_field}: {first_messages[0]}", "errors": errors},
        status_code=422,
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
