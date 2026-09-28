# Fase 4 — Autenticación, sesiones, presencia y super administrador

| Campo | Valor |
|---|---|
| Estado | Pendiente |
| Depende de | F1 |
| Casos de uso | CU-01, CU-08, CU-10, CU-14 |
| Requisitos | RF-02, RF-03, RF-04, RF-14, RF-15, RNF-06, OE-7, OE-8 |

## 1. Objetivo

Multiusuario seguro con visibilidad operativa en tiempo real: quién está conectado, quién no y
**por qué**.

## 2. Alcance

**Incluido:** login con Argon2id · access token JWT (claim `sid`) + refresh token opaco en Redis
con rotación y detección de reuso · máximo 2 sesiones simultáneas con evicción de la más antigua
por `ultimo_uso` · estados de usuario y de sesión · RBAC (`super_admin`, `admin_negocio`,
`consultor`, `lector`) · presencia en Redis con heartbeat · cierre inmediato por
`navigator.sendBeacon` · notificación asíncrona al panel del administrador mediante SSE
respaldado por Redis Pub/Sub · semáforo por colores · auditoría de acciones sensibles.

**Excluido:** gate de consentimiento (F5), gestión de exportaciones (F6).

## 3. Reglas de sesión y presencia

| Elemento | Definición |
|---|---|
| Estados de usuario | `activo`, `inactivo`, `bloqueado`, `pendiente` |
| Estados de sesión | `activa`, `inactiva`, `revocada`, `expirada`, `reemplazada` |
| Motivos de cierre | `logout`, `cierre_ventana`, `heartbeat_vencido`, `expirado`, `eviccion`, `admin` |
| Evicción | Al 3.er login se revoca la sesión activa con `ultimo_uso` más antiguo, se audita y se avisa al usuario expulsado |
| Presencia | Clave en Redis con TTL 60 s, refrescada por heartbeat cada 30 s |
| Verde | Presencia viva **y** token activo |
| Rojo | Sin presencia, o token revocado/expirado |
| Piso de detección | Cierre abrupto del navegador → el rojo se refleja al vencer el TTL (≤60 s) |

## 4. Criterios de aceptación

- [ ] Un 3.er login revoca la sesión más antigua en <2 s y deja registro en `auditoria`
- [ ] El refresh token rota; reutilizar uno ya usado revoca toda la familia de sesiones
- [ ] El panel del administrador cambia verde→rojo **sin recargar** la página
- [ ] Cerrar la ventana marca al usuario como desconectado de forma proactiva
- [ ] Un usuario de un negocio no puede ver sesiones de otro negocio
- [ ] Los estados de sesión expiran por inactividad según configuración
- [ ] Argon2id verificado: la base nunca almacena la contraseña en claro

## 5. Riesgos

| Riesgo | Mitigación |
|---|---|
| RS-07 Evicción usada como ataque | Auditoría + notificación + rate limit de login + bloqueo por intentos |
| SSE con varias réplicas | Redis Pub/Sub como bus de eventos |
| Falsos positivos de presencia en redes inestables | TTL como piso, no como medida exacta; documentado en la interfaz |

## 6. Implementaciones realizadas

_(Se completa al cerrar la fase.)_

## 7. Pruebas ejecutadas y resultado real

_(Se completa al cerrar la fase.)_

## 8. Evidencia de aceptación

```
(Se completa al cerrar la fase.)
```
