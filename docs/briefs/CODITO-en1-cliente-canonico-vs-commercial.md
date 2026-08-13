# CODITO — Inspección: Cliente canónico EN1 vs comprador comercial

**DESTINO:** CODITO / EasyNodeOne (DEV)  
**AMBIENTE:** `https://appdev.easynodeone.com` · no PROD  
**PEDIDO POR:** ESB / SPAGHETTI — tras E2E M2M registro → EN1 → entitlement OK  
**ESB:** no implementa esto; solo consume entitlement  
**Relacionado:** `docs/briefs/CODITO-en1-commercial-cliente-visible.md` · ADR-037

---

## Decisión de producto (congelada, lado ESB)

> Una persona/empresa = **un Cliente** en EN1.  
> Contacto, miembro, usuario, comprador, suscriptor y productos contratados son **relaciones** de ese cliente.  
> **No** crear otra figura denominada «Cliente Comercial».

El comprador SaaS de ESecureBroker debe materializarse en el **Cliente canónico** de EN1, no quedar solo en `ets_commercial_customer` invisible al CRM/UI de Clientes.

---

## Contexto ESB (lo que ya vimos)

1. E2E M2M desde `/registro` funciona: bootstrap → checkout $0/promo → entitlement → org ESB → `/hoy`.  
2. En EN1, el comprador aparece en capa comercial (`ets_commercial_customer` / customer_id) pero **no** como Cliente canónico en UI (ej. Organizations / Clientes).  
3. ESB guarda `Organization.external_en1_org_id` ≈ commercial `customer_id` (espejo), no necesariamente el id del Cliente canónico.

---

## Pedido CODITO — SOLO INSPECCIÓN (no implementar aún)

Mapear y documentar cómo se relacionan hoy:

| Concepto | Preguntas |
|----------|-----------|
| User | ¿Login EN1 vs comprador SaaS? |
| Contacto / Party | ¿Persona/empresa canónica? |
| Cliente / Customer | ¿Tabla/UI «Cliente» canónica? PK? |
| Member / Membership | ¿Relación org↔persona? |
| `ets_commercial_customer` | ¿Es proyección comercial del Cliente o entidad paralela? |
| Organization (`saas_organization` / provider) | ¿Provider ETS (#1) vs buyer? |
| Contracts | ¿Cómo se atan al Cliente? |
| Subscriptions | ¿Entitlement C1 apunta a qué FK? |

**Entregar:**

1. Diagrama actual (as-is) de entidades y FKs.  
2. Gap: por qué el bootstrap C1 no crea/enlaza Cliente canónico visible.  
3. Propuesta to-be **sin** inventar «Cliente Comercial»:  
   - una sola entidad Cliente  
   - comprador/suscriptor = roles/relaciones  
4. Impacto en contrato C1 (paths M2M) — ¿breaking o additive?  
5. Plan mínimo para que un registro desde ESB `/registro` deje el Cliente visible en UI EN1.  
6. Riesgos de migración de customers comerciales huérfanos en DEV.

**NO implementar en este turno.**  
**NO tocar PROD.**  
Tras inspección → decisión conjunta → re-probar E2E desde ESB `/registro`.

---

## Frontera con ESB Colaboradores (ADR-008 F7)

| EN1 Cliente | ESB Colaborador |
|-------------|-----------------|
| Comprador/suscriptor del producto SaaS | Persona que trabaja *dentro* de la correduría |
| SoR comercial / seats del plan | OrgMembership + roles + ProducerProfile |

No mezclar: el OWNER de una correduría ESB es **colaborador** de su org; en EN1 es (debe ser) el **Cliente** que contrata el plan.
