from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class AppError(Exception):
    status_code = 400

    def __init__(self, code: str, detail: str, params: dict | None = None):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.params = params or {}


class NotFoundError(AppError):
    status_code = 404


class ConflictError(AppError):
    status_code = 409


class UnprocessableError(AppError):
    status_code = 422


class PayloadTooLargeError(AppError):
    status_code = 413


class UnsupportedMediaTypeError(AppError):
    status_code = 415


class UpstreamError(AppError):
    status_code = 502


class TooManyRequestsError(AppError):
    status_code = 429


def install_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "params": exc.params, "detail": exc.detail},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        # `input` echoes the offending value (for model-level errors the whole body, incl. API keys): never send it
        errors = [{k: v for k, v in e.items() if k != "input"} for e in exc.errors()]
        return JSONResponse(
            status_code=422,
            content={
                "code": "validation_error",
                "params": {"errors": jsonable_encoder(errors, custom_encoder={Exception: str})},
                "detail": "Validation error",
            },
        )
