# ADR-008 — pointer

Formal ADR (**ACCEPTED**):

`/opt/easynodeone/Easy-Wiki/05_Proyectos/corredores-seguros/adr/ADR-008_producer_portfolio_rbac.md`

| Fase | Estado | Notas |
|------|--------|-------|
| F1 Schema | **DONE** | `docs/ADR-008_F1_SCHEMA.md` |
| F2 AccessContext / RBAC | **DONE** | `docs/ADR-008_F2_ACCESS_CONTEXT.md` |
| F3 Scope enforcement | **DONE** | `docs/ADR-008_F3_SCOPE.md` |
| F4 Producer Admin | **DONE** | `docs/ADR-008_F4_PRODUCER_ADMIN.md` |
| F5 Seats EN1 | **DONE** | `docs/ADR-008_F5_SEATS.md` |
| F6 ESB GO Producer | **DONE** | `docs/ADR-008_F6_ESB_GO_PRODUCER.md` |
| DEV live alignment | **DONE** | `docs/ADR-008_DEV_LIVE_ALIGNMENT.md` · restart after `b3101dd` |
| **F7 Colaboradores / Roles admin** | **F1–F6/F8 DEV** | Contrato: `docs/ADR-008_F7_COLLABORATORS_RBAC_CONTRACT.md` · F0: `docs/ADR-008_F7_F0_INSPECTION.md` · UI: `/configuracion/colaboradores` + `/configuracion/roles` |

Solo DEV. PROD no tocado. ADR-037 sigue como gate M2M PROD.

ADR-008 fases F1–F6 cerradas en DEV.  
F7 Colaboradores/Roles/Invitaciones implementado en DEV (ver `ADR-008_F7_IMPLEMENTATION.md`).  
ESB GO F5A congelado mientras se cierra Cliente canónico EN1.  
Paralelo CODITO: `docs/briefs/CODITO-en1-cliente-canonico-vs-commercial.md`.  
Roadmap ESB: `docs/ROADMAP_ESECUREBROKER.md` · Companion Ana: `docs/briefs/ANA-roadmap-esb-en1-contexto.md`.  
Posteriores (SECONDARY / comisiones por producer) = ADR futuro + GO.
