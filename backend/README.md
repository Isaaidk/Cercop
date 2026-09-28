# Backend — Plataforma SERCOP Multi-Tenant

Monolito modular con arquitectura hexagonal. Dos procesos comparten el mismo código:

| Proceso | Rol | Puerto |
|---|---|---|
| `api` | Atiende a los usuarios | 8001 |
| `worker` | Ingesta, exportaciones, retención | — |

> El sistema legado (`/main.py` y `/Consultoria/`) sigue funcionando en el puerto 8000 durante la
> migración por fases. No se toca hasta la fase F6.

## Estructura

```
backend/
├── pyproject.toml            Dependencias, ruff, mypy y pytest
├── src/contratacion/
│   ├── asgi.py               Punto de entrada del API
│   ├── dominio/              Entidades y reglas — sin dependencias externas
│   ├── aplicacion/           Casos de uso y puertos (contratos)
│   │   └── puertos/
│   ├── infraestructura/
│   │   ├── config/           Ajustes validados desde .env (fallo rápido)
│   │   ├── app.py            Factoría de la aplicación
│   │   └── adaptadores/
│   │       ├── entrada/http/ Adaptador de entrada: enrutadores
│   │       └── salida/       Adaptadores de salida: bd, cache, fuentes, excel, seguridad
│   └── tareas/               Proceso worker (F2)
└── pruebas/
    ├── unidad/               Sin red, sin base, sin caché
    ├── integracion/          Postgres y Redis reales
    ├── contrato/             Respuestas grabadas de la fuente oficial
    └── e2e/                  Flujo completo
```

**Regla de dependencias:** `dominio` no importa nada de fuera; `aplicacion` depende de `dominio`;
`infraestructura` implementa los puertos de `aplicacion`. Nunca al revés.

## Puesta en marcha

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

Copy-Item ..\.env.example ..\.env    # completar los valores OBLIGATORIOS

uvicorn contratacion.asgi:app --port 8001 --reload
```

## Verificación

```powershell
ruff check .
ruff format --check .
mypy
pytest

# Auditoría: se excluye el propio paquete editable, que no está en PyPI
pip freeze --exclude-editable > deps-a-auditar.txt
pip-audit -r deps-a-auditar.txt
Remove-Item deps-a-auditar.txt
```

| Ruta | Qué comprueba |
|---|---|
| `GET /salud` | Que el proceso vive |
| `GET /listo` | Que Postgres y Redis responden (503 si alguno falla) |

## Variables obligatorias

`DATABASE_URL` · `REDIS_URL` · `JWT_SECRETO` · `CLAVE_CIFRADO_DATOS` · `CLAVE_PEPPER_HMAC`

Sin ellas la aplicación **no arranca**. Es intencional: evita correr en producción con valores por
defecto. `CORS_ORIGINS` rechaza el comodín `*`.
