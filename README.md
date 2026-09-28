# Cercop

Panel de seguimiento de la contratación pública del Ecuador (SERCOP).

Ingesta las **necesidades de contratación** y los **procesos publicados** en los datos abiertos, y
los reúne en un panel con mapa de las 24 provincias, gráficas, tabla filtrable y exportable a Excel,
palabras clave vigiladas y gestión de usuarios por empresa.

## Estructura

```
.
├── backend/          API y worker (FastAPI + PostgreSQL, arquitectura hexagonal)  → :8001
├── frontend/         Panel (Vue 3 + Vite + Chart.js)                             → :5174
├── Consultoria/      Sistema legado, en migración por fases                      → :8000
├── docs/             Documentación por fases
├── .env.example      Plantilla de variables de entorno (copiar a .env)
└── .env              Valores reales — NO se versiona
```

## Puesta en marcha

### 1 · Configuración

```powershell
Copy-Item .env.example .env
# Completar los valores OBLIGATORIOS: DATABASE_URL, JWT_SECRETO,
# CLAVE_CIFRADO_DATOS y CLAVE_PEPPER_HMAC.
```

### 2 · Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

alembic upgrade head                          # crea el esquema
uvicorn contratacion.asgi:app --port 8001 --reload --reload-dir src
```

### 3 · Worker de ingesta

Es un **proceso aparte** del API y tiene que estar corriendo: es el que consulta la fuente oficial.
Sin él, el histórico se queda congelado.

```powershell
cd backend
.\.venv\Scripts\Activate.ps1

python -m contratacion.tareas.worker             # bucle continuo (recomendado)
python -m contratacion.tareas.worker --una-vez   # un solo ciclo, para cron externo
```

### 4 · Frontend

```powershell
cd frontend
npm install
npm run dev        # http://localhost:5174
```

### 5 · Sistema legado (opcional)

```powershell
.\venv\Scripts\Activate.ps1
python -m uvicorn main:app --port 8000
```

## Verificación

```powershell
cd backend
ruff check .
ruff format --check .
mypy src pruebas scripts
pytest pruebas/unidad

# Pruebas de integración: necesitan base de datos real
$env:PRUEBAS_INTEGRACION = 1; pytest pruebas/integracion

# Guiones de comprobación contra la base real
python scripts/verificar_exportacion.py
python scripts/verificar_terminos_lote.py
```

| Ruta | Qué comprueba |
|---|---|
| `GET /salud` | Que el proceso vive |
| `GET /listo` | Que las dependencias responden (503 si alguna falla) |

## Documentación

- `backend/README.md` — arquitectura, estructura interna y variables obligatorias.
- `docs/` — decisiones y alcance por fases.
- `documentacion.md` — documentación general del producto.

## Dos advertencias

**`.env` no se versiona y nunca debe versionarse.** Contiene la contraseña de la base de datos en
texto plano. Si alguna vez se sube por error, hay que rotar las credenciales: borrar el archivo del
histórico no basta, sigue estando en los commits anteriores.

**No uses `uvicorn --reload` sin `--reload-dir src`.** El canal de presencia deja una conexión
abierta y el apagado ordenado la espera indefinidamente, así que el servidor se queda sin responder
al recargar. Y con `--reload` a secas vigila también `pruebas/` y `scripts/`, de modo que cada
`pytest` reinicia el servidor.
