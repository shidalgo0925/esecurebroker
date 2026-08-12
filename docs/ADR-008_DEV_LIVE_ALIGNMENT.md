# ADR-008 — DEV live alignment (2026-08-12)

## Root cause

`esecurebroker-dev` process started **08:22 CEST**, before SHA `b3101dd` (~09:35+).
Running code was **F2-era**: detail/360 scoped, **lists still ORGANIZATION-wide**.

That made LOCAL see:

| Listed (org-wide) | Detail/360 |
|-------------------|------------|
| Prod Alfa (producer party, 0 policies) | 404 |
| Cliente Demo `17843a80` (AUTO-DEMO-20260811, no PRIMARY) | 404 |
| Cliente Demo `e08bbec4` (AUTO-DEMO-20260812, PRIMARY) | 200 |
| Policy AUTO-DEMO-20260811 | 404 |
| Policy AUTO-DEMO-20260812 | 200 |

## Data (correct under P0)

Producer `producer.alfa@example.invalid`:

- `producer_profile_id` = `68fedd90-…`
- PRIMARY vigente → only `AUTO-DEMO-20260812` / party `e08bbec4-…`
- `AUTO-DEMO-20260811` + `17843a80` + Prod Alfa = **intentional out-of-scope** (404)

No ADR rule change. No data wipe required.

## Fix

```bash
sudo systemctl restart esecurebroker-dev
# ActiveEnterTimestamp ≥ commit time; WorkingDirectory=/opt/corredores-dev
ESB_DEV_BASE=http://127.0.0.1:8092 python scripts/smoke_producer_live_dev.py
```

## Smoke

∀ listed customer → detail 200 + 360 200  
∀ listed policy → detail 200  
OOS IDs → 404
