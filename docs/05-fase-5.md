# Fase 5 — Cumplimiento legal (LOPDP) y protección de datos personales

| Campo | Valor |
|---|---|
| Estado | Pendiente |
| Depende de | F4 |
| Casos de uso | CU-02, CU-11, CU-13 |
| Requisitos | RF-05, RF-06, RF-16, RF-17, RF-18, RNF-07, RNF-08, OE-6 |

## 1. Objetivo

Cumplir la Ley Orgánica de Protección de Datos Personales del Ecuador y, sobre todo, **poder
demostrarlo**. El objetivo legítimo es reducir el riesgo y acreditar diligencia: ninguna
arquitectura otorga inmunidad legal.

## 2. Base legal adoptada

- **Consentimiento** para las cuentas de usuario: se recoge en el primer login mediante lectura
  completa y aceptación explícita, con evidencia versionada.
- **Interés legítimo documentado** para los datos de contacto de funcionarios publicados por la
  fuente oficial, con canal de oposición disponible.
- **Roles:** para los datos que el cliente consulta, el **cliente es Responsable** y la plataforma
  **Encargado** (Acuerdo de Encargado). Para las cuentas de usuario, la plataforma es Responsable.
- Pendiente de validación con asesoría legal ecuatoriana (ver riesgos).

## 3. Alcance

**Incluido:** gate de primer login (el aplicativo queda bloqueado hasta aceptar; el botón de
aceptación se habilita al llegar al final del documento) · registro de consentimiento con tipo,
versión, hash del texto, fecha, IP, user-agent y método · re-aceptación automática al publicar una
versión nueva · aviso de privacidad y términos versionados · canal de derechos ARCO con
vencimiento calculado a 15 días hábiles · cifrado en columna (AES-256-GCM) del contacto de
funcionarios en tabla separada con permisos propios · retención automática por `vigente_hasta` ·
exportación del Registro de Actividades de Tratamiento (RAT) · auditoría inmutable de accesos a
datos personales · política de cookies.

**Excluido:** gestión de brechas con notificación automática a la autoridad (procedimiento
documentado, no automatizado en v1).

## 4. Criterios de aceptación

- [ ] Es **imposible** usar el aplicativo sin aceptar los términos
- [ ] El botón de aceptación permanece deshabilitado hasta finalizar la lectura
- [ ] Cada aceptación guarda versión, hash, fecha, IP y user-agent
- [ ] Publicar una versión nueva obliga a todos los usuarios a re-aceptar
- [ ] Al crear una solicitud ARCO se calcula y almacena el vencimiento a 15 días hábiles
- [ ] El contacto de funcionarios se almacena cifrado y **nunca** en claro en la base
- [ ] Los usuarios con rol `lector` no pueden ver el contacto de funcionarios
- [ ] El job de retención anonimiza o elimina lo que supera el plazo configurado
- [ ] El RAT se puede exportar desde el propio sistema
- [ ] Un usuario puede revocar su consentimiento y el sistema lo registra

## 5. Riesgos

| Riesgo | Mitigación |
|---|---|
| Aplicabilidad de la excepción de fuentes de acceso público | **No apoyarse en ella sin confirmación legal** |
| Base legal mal elegida (consentimiento revocable vs. interés legítimo) | Documentar la ponderación del interés legítimo |
| Retención sin control | Job automático + verificación por prueba |
| Secretos de cifrado mal gestionados | Claves fuera del repositorio, rotación por `clave_id` |

## 6. Implementaciones realizadas

_(Se completa al cerrar la fase.)_

## 7. Pruebas ejecutadas y resultado real

_(Se completa al cerrar la fase.)_

## 8. Evidencia de aceptación

```
(Se completa al cerrar la fase.)
```

## 9. Documentos legales a producir (fuera del código)

- Términos y condiciones de uso.
- Aviso de privacidad (versión breve + extendida).
- Política de cookies.
- Acuerdo de Encargado de Tratamiento (cláusulas mínimas exigidas por la normativa).
- Procedimiento de gestión de incidentes y brechas.
- Política de retención y eliminación.
