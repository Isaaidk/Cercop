"""Tareas del proceso `worker`.

Segundo punto de entrada del monolito modular. Separar la ingesta del tráfico de usuarios es lo que
garantiza que ninguna petición de un usuario llegue a la fuente oficial.

Se implementa en la fase 2:

- `planificador.py`  bucle de 15 minutos con bloqueo de exclusión mutua
- `ingesta.py`       extraer → normalizar → mapear → upsert → invalidar caché
- `exportacion.py`   generación de Excel fuera del proceso del API (fase 6)
- `retencion.py`     anonimización y borrado por vencimiento (fase 5)
"""

from __future__ import annotations
