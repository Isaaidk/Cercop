"""
Punto de entrada del backend (MVC: model -> controller -> view).

Ejecutar en desarrollo:

    uvicorn main:app --reload --port 8000

Documentación interactiva: http://127.0.0.1:8000/docs
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from Consultoria.controller.contrataciones_controller import router as procesos_router
from Consultoria.controller.necesidades_controller import router as necesidades_router
from Consultoria.controller.ofertas_controller import router as ofertas_router
from Consultoria.model import necesidades


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Precarga el listado de necesidades para que la primera consulta sea rápida."""
    try:
        df = await necesidades.obtener_necesidades()
        print(f"[startup] Necesidades precargadas: {len(df)} registros.")
    except Exception as exc:  # noqa: BLE001
        print(f"[startup] No se pudieron precargar las necesidades: {exc}")
    yield


app = FastAPI(
    title="API SERCOP - Consultoría",
    description=(
        "Tabla de Necesidades de Contratación (NCO) y Procesos publicados (OCDS) "
        "del Servicio Nacional de Contratación Pública del Ecuador."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

# CORS: permite que el frontend Vue (Vite) consuma la API sin bloqueos del navegador.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En producción, reemplazar por la URL del frontend.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rutas del dashboard (una por cada controlador).
app.include_router(necesidades_router)
app.include_router(ofertas_router)
app.include_router(procesos_router)


@app.get("/", tags=["Salud"])
async def raiz():
    """Verificación rápida del servicio."""
    return {
        "servicio": "API SERCOP - Consultoría",
        "estado": "ok",
        "endpoints": [
            "/api/necesidades",
            "/api/necesidades/filtros",
            "/api/necesidades/estadisticas",
            "/api/necesidades/exportar",
            "/api/ofertas",
            "/api/ofertas/exportar",
            "/api/contrataciones",
            "/api/exportar",
            "/api/procesos/{ocid}/detalle",
            "/docs",
        ],
    }
