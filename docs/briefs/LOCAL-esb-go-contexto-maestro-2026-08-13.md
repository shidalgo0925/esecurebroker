# ESecureBroker GO — Contexto Maestro

**Fecha de corte:** 2026-08-13  
**Producto:** ESecureBroker GO  
**Alias:** ESB GO  
**Plataforma:** Android / Flutter  
**Responsable de ejecución:** LOCAL  
**Backend:** ESecureBroker DEV  
**Estado:** F1–F3 certificados · F4/F5 pendientes

Landing público (posicionamiento): sección `#go` en `landing.html` (commit `ea1b30b`).

---

# 1. Qué es ESB GO

ESecureBroker GO es la aplicación móvil companion de ESecureBroker.

NO es:

* un WebView;
* una copia reducida del portal web;
* un sistema independiente de seguros;
* otro backend;
* otra base de datos operativa.

ESB GO es una experiencia móvil diseñada específicamente para el corredor/productor que trabaja fuera de oficina.

Arquitectura:

`ESB GO` → `ESB Mobile API` → `ESecureBroker` → `EN1 cuando corresponda`

ESB continúa siendo el System of Record operativo de seguros.

EN1 continúa siendo control plane comercial/identidad/suscripción/entitlements según los ADR vigentes.

---

# 2. Repositorio

ESB GO tiene repositorio Flutter independiente:

`ESecureBroker-Go`

No mezclar código Flutter dentro del proyecto web ESB.

---

# 3. Principio UX

La aplicación debe responder principalmente:

> ¿Qué necesita hacer el corredor ahora desde su teléfono?

No intentar colocar todas las pantallas administrativas del portal web dentro de GO.

Web ESB está orientado a operación completa/administración.

GO está orientado a:

* acción inmediata;
* consulta;
* seguimiento;
* captura;
* movilidad;
* contacto con cliente;
* evidencias;
* cartera asignada;
* notificaciones.

---

# 4. Navegación principal

**Hoy | Clientes | + | Cartera | Más**

## Hoy

Resumen operativo y acciones prioritarias.

## Clientes

Buscar/consultar clientes.

## +

Acción rápida/captura.

Debe convertirse progresivamente en punto central para:

* nueva póliza;
* documento;
* foto;
* interacción;
* reclamo;
* otras capturas móviles autorizadas.

## Cartera

Pólizas/cartera accesible según scope.

## Más

Funciones secundarias y configuración.

Las funciones todavía no implementadas deben permanecer correctamente deshabilitadas; no simular capacidades.

---

# 5. F1 — Shell

**Estado: DONE**

Se construyó: aplicación Flutter, estructura base, navegación, shell, rutas, estados principales.

No reconstruir F1.

---

# 6. F2 — Identity

**Estado: CERTIFIED**

Implementado: Login contra ESB, sesión, `/me`, logout, refresh/session, organization context, roles/scopes del backend.

La identidad NO se resuelve directamente contra EN1 desde GO.

Flujo: `ESB GO → ESB Mobile API → identidad/contexto`

---

# 7. F3 — Vertical Slice

**Estado: CERTIFIED**

Flujo E2E: `Login → Me → Hoy → Cliente Demo → 360° → Póliza` — **PASS**

Multi-organización Alfa / Beta — Tests **9 PASS**

Baseline certificado: `c85430f742af39259af09cc375181e087c60a92f`  
Evidencia: `ad813b1`

No degradar esta vertical slice durante F4/F5.

---

# 8. Backend Mobile API

ESB dispone en DEV de API Mobile v1.

Documentación: `/docs` · Tag: `mobile-v1`

Capacidades: auth/login, auth/logout, auth/refresh, me, organizations, today, customers, client_360, policies, health.

GO debe consumir contratos publicados. No inventar endpoints locales para ocultar una ausencia del backend.

---

# 9. Multi-tenant

ESB GO es multi-tenant porque ESB lo es.

Un usuario puede pertenecer a una o varias Organizations.

Caso certificado: Usuario → Organization Alfa o Beta.

La Organization activa debe formar parte explícita del contexto. Nunca mezclar datos entre organizaciones.

---

# 10. ADR-008 — Producer / Portfolio / RBAC

Fundamental para continuar GO.

Modelo: `Organization → Producer → PortfolioAssignment → Policy`

Scopes: `ORGANIZATION` · `ASSIGNED_PORTFOLIO` · `PLATFORM`

---

# 11. Producer

Un productor/agente interno NO es otra Organization.

Una correduría puede tener OWNER, ejecutivos, productores/agentes, personal administrativo — todos en el mismo tenant según permisos.

No crear Organization por productor.

---

# 12. Portfolio Assignment

Las pólizas pueden asignarse a productores.

Regla P0: una póliza puede tener un productor `PRIMARY` vigente.

El productor con `ASSIGNED_PORTFOLIO` solo debe poder acceder a su cartera autorizada.

---

# 13. Anti-IDOR

Si el usuario no tiene acceso a cliente/póliza/documento/reclamo/recurso, no debe obtenerlo por ID manual.

Respuesta según contrato: `404` cuando corresponda.

La seguridad se aplica en backend. No confiar en ocultar botones Flutter.

---

# 14. Estado ADR-008

**ACCEPTED** · Schema/migración DEV aplicada · `producer_profiles` · `portfolio_assignments`

La evolución de GO debe reconocer PRODUCER/portfolio una vez certificado el enforcement backend.

No implementar filtrado de seguridad únicamente en Flutter.

---

# 15. Carrier Agent Code ≠ Producer

`CarrierAgentCode ≠ Producer`

Una aseguradora puede identificar producción con un código de agente (ej. ASSA → 12345) que corresponde a toda la correduría, mientras varios productores administran pólizas de ese código.

GO no debe asumir equivalencia.

---

# 16. F4 — Mobile Capture / Uploads

**Estado: NO INICIADO**

P0 esperado: cámara, foto de póliza/documento, selección de archivo, upload, asociación segura, metadata, estado, retry, confirmación backend.

---

# 17. Regla de uploads

Nunca mostrar un documento como cargado definitivamente hasta confirmación del backend.

`CAPTURED → UPLOADING → CONFIRMED` o `FAILED / RETRY`

Evitar duplicados en retry.

---

# 18. Uso del botón +

Evolucionar hacia **Acción rápida**. No menú gigantesco.

Candidatas: capturar documento, registrar interacción, nueva póliza/captura, iniciar reclamo.

Activar únicamente lo que tenga contrato backend implementado.

---

# 19. F5 — Notifications / Cobranza móvil

**Estado: NO INICIADO**

Cuota próxima, pago vencido, renovación, reclamo, documento requerido, tarea, oportunidad.

No construir un sistema de notificaciones paralelo. GO consume eventos de ESB.

---

# 20. Cobranza

Estados conceptuales: `RECEIVED → PENDING_CARRIER_CONFIRMATION → CONFIRMED`

GO nunca debe presentar como pago oficialmente aplicado una transacción que espera confirmación de la aseguradora.

---

# 21. Trabajo offline

NO offline-first equivalente a EP1.

Manejar: pérdida temporal, loading, retry, timeout, uploads pendientes.

No crear DB paralela completa de seguros sin ADR.

---

# 22. Hoy móvil

Filosofía ESB: dinero del día · requiere tu atención · el sistema trabajó por ti · oportunidades.

Para PRODUCER, todos los datos respetan su scope.

---

# 23. Cliente 360°

No replicar toda la ficha web. Priorizar: identidad, contacto, pólizas, riesgos, cobranza, renovaciones, reclamos, documentos, interacciones.

Acciones: llamar, WhatsApp/contactar, capturar documento, registrar seguimiento.

---

# 24. Cartera

Consultar pólizas autorizadas. Filtros progresivos. Para `ASSIGNED_PORTFOLIO`, backend determina la cartera.

---

# 25. Integraciones con aseguradoras

`Carrier ↔ ESB Backend ↔ ESB GO`  
Nunca: `ESB GO → Carrier API`

Credenciales de aseguradoras permanecen en backend.

---

# 26. EN1

`GO → ESB` y `ESB ↔ EN1` según M2M.

No consumir EN1 directamente desde GO para operación normal.

---

# 27. Seguridad

Nunca almacenar en Flutter: M2M EN1, Carrier API keys, secretos backend, credenciales administrativas.

Solo tokens de sesión del usuario móvil en almacenamiento seguro de plataforma.

---

# 28. Entitlements

EN1 determina suscripción/licencia; ESB aplica la regla; GO consume el resultado.

No duplicar reglas comerciales de planes en Flutter.

---

# 29. Errores

Distinguir: sin conexión, sesión expirada, no autorizado, no encontrado, error backend, upload fallido, operación pendiente.

No mostrar stack traces al usuario final.

---

# 30. No hacer

* No WebView como solución.
* No conectar GO directamente con EN1.
* No conectar GO directamente con aseguradoras.
* No implementar seguridad solo ocultando widgets.
* No duplicar DB completa de ESB.
* No inventar datos para completar pantallas.
* No crear Organization por Producer.
* No equiparar CarrierAgentCode con Producer.
* No marcar pagos como oficiales antes de confirmación.
* No iniciar F4/F5 destruyendo F1–F3 certificados.

---

# 31. Orden recomendado de continuación

1. **Gate RBAC** — certificar backend `PRODUCER + ASSIGNED_PORTFOLIO` con anti-IDOR.
2. **F4A** — Acción `+` + captura documento/foto.
3. **F4B** — Upload resiliente + asociación.
4. **F4C** — Interacciones móviles.
5. **F5A** — Infra notificaciones.
6. **F5B** — Cobranza/renovaciones/reclamos.

---

# 32. Gate F4

Antes de declarar F4 DONE:

`Login → Producer → Cartera asignada → Cliente → 360 → Póliza → Capturar documento → Upload → Confirmación backend → Documento visible`

y:

`Producer intenta póliza ajena → 404 / acceso denegado según contrato`

---

# 33. Regla de ejecución

Trabajar únicamente sobre el repositorio/localización de desarrollo de **ESecureBroker GO**.

* No tocar ESB PROD.
* No tocar EN1 PROD.
* No modificar contratos backend unilateralmente.

Si falta endpoint: **STOP → documentar contrato requerido → solicitarlo a ESB backend.**

No simularlo como solución definitiva.

---

# 34. Punto de continuación

| Frente | Estado |
|--------|--------|
| F1 Shell | DONE |
| F2 Identity | CERTIFIED |
| F3 Vertical Slice | CERTIFIED |
| F4 | PENDING |
| F5 | PENDING |

**Baseline:** `c85430f742af39259af09cc375181e087c60a92f`  
**Tests:** 9 PASS  

**Siguiente gate:** ADR-008 Producer/Portfolio Scope Enforcement → certificación móvil → F4.

No rehacer trabajo certificado.
