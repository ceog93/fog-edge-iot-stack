"""FastAPI entry point. Run from backend/: uvicorn app:app --workers 1."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from config import MAX_INTERVAL_SECONDS, MAX_NODE_COUNT, Settings
from simulation import ConfigurationConflict, Simulation


class SimulationParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)

    node_count: int = Field(default=10, ge=1, le=MAX_NODE_COUNT)
    interval_seconds: float = Field(default=2, gt=0, le=MAX_INTERVAL_SECONDS)
    alarm_threshold: int = Field(default=1500, ge=0, le=4094)
    alarm_probability: float = Field(default=0.1, ge=0, le=1)


def create_app(settings: Settings | None = None, client_factory=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
        options = {} if client_factory is None else {"client_factory": client_factory}
        app.state.simulation = Simulation(settings or Settings.from_env(), **options)
        try:
            yield
        finally:
            await app.state.simulation.stop()

    api = FastAPI(title="Simulador ESP32 virtual", version="2.0.0", lifespan=lifespan)

    @api.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # Avoid echoing raw inputs: an overflowing JSON number becomes inf and
        # cannot itself be serialized into the validation error response.
        errors = [{key: error[key] for key in ("loc", "msg", "type")} for error in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": errors})

    @api.get("/status")
    async def status(request: Request):
        """Estado de la simulación y conexiones; no expone credenciales."""
        return request.app.state.simulation.snapshot()

    @api.post("/simulation/start")
    async def start(request: Request, parameters: SimulationParameters | None = None):
        """Configura e inicia de forma atómica. Sin cuerpo conserva la configuración."""
        try:
            changes = parameters.model_dump(exclude_unset=True) if parameters else None
            return await request.app.state.simulation.start(changes)
        except ConfigurationConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        except Exception:
            logging.getLogger("esp32_simulator").exception("No se pudo iniciar la simulación")
            raise HTTPException(status_code=503, detail="No se pudo iniciar la simulación; consulte los logs") from None

    @api.post("/simulation/stop")
    async def stop(request: Request):
        """Detención idempotente; espera el cierre de los clientes MQTT."""
        return await request.app.state.simulation.stop()

    return api


app = create_app()
