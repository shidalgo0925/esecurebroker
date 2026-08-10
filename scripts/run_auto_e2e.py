"""Run P0 AUTO E2E certification path against local DB."""

from __future__ import annotations

import json

from corredores.db import SessionLocal
from corredores.services.auto_e2e import collection_snapshot, run_auto_e2e_demo


def main() -> None:
    with SessionLocal() as session:
        result = run_auto_e2e_demo(session)
        snap = collection_snapshot(session, result.policy_id)
    print(
        json.dumps(
            {
                "ok": True,
                "flow": "Cliente→Submission→VehicleRisk→Policy/Term→PaymentPlan→Payment→Commission→Renewal",
                "result": {
                    "organization_id": result.organization_id,
                    "policy_id": result.policy_id,
                    "payment_id": result.payment_id,
                    "commission_id": result.commission_id,
                    "renewal_id": result.renewal_id,
                    "installments": len(result.installment_ids),
                    "paid_or_status_sample": {
                        k: v
                        for k, v in list(result.installment_statuses.items())[:3]
                    },
                },
                "collection_snapshot_head": snap[:3],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
