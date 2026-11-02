"""The FastAPI application.

Run with:  uvicorn orderbridge.api.main:app --reload --port 8000
Docs at:   http://localhost:8000/docs
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse

from orderbridge import __version__
from orderbridge.api.routers import inventory, orders
from orderbridge.dashboard.router import router as dashboard_router
from orderbridge.services.errors import DomainError

app = FastAPI(
    title="OrderBridge API",
    version=__version__,
    description=(
        "Mock ERP / order hub for the OrderBridge portfolio project. "
        "POST /orders requires an `Idempotency-Key` header. "
        "Live dashboard: [/dashboard](/dashboard)."
    ),
)
app.include_router(orders.router)
app.include_router(inventory.router)
app.include_router(dashboard_router)


@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    """Business errors become clean JSON with the right HTTP status (404, 409, 422...)."""
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Turn Pydantic's verbose errors into short, readable messages."""
    errors = []
    for err in exc.errors():
        field = ".".join(str(part) for part in err["loc"] if part != "body")
        errors.append({"field": field, "message": err["msg"]})
    summary = "; ".join(f"{e['field']}: {e['message']}" for e in errors)
    return JSONResponse(
        status_code=422, content={"detail": f"Validation failed: {summary}", "errors": errors}
    )


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/docs")


@app.get("/health", tags=["ops"])
def health() -> dict:
    return {"status": "ok", "version": __version__}
