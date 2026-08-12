#!/usr/bin/env python3
"""Live HTTP smoke: PRODUCER list IDs must all detail/360 200 (ADR-008 P0).

DEV only. Targets ESB_DEV_BASE (default https://esecurebroker-dev.etsrv.site).
Password: ESB_DEV_SEED_PASSWORD (default secreto123 for local ops).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("ESB_DEV_BASE", "https://esecurebroker-dev.etsrv.site").rstrip("/")
EMAIL = os.environ.get("ESB_DEV_PRODUCER_EMAIL", "producer.alfa@example.invalid")
PW = os.environ.get("ESB_DEV_SEED_PASSWORD", "secreto123")
UA = os.environ.get("ESB_DEV_SMOKE_UA", "Mozilla/5.0 (compatible; ESB-Smoke/1.0)")


def call(method: str, path: str, body: dict | None = None, token: str | None = None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", UA)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode() or "{}"
            return r.status, json.loads(raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw": raw[:300]}
        return e.code, payload


def main() -> int:
    st, login = call(
        "POST", "/api/mobile/v1/auth/login", {"username": EMAIL, "password": PW}
    )
    if st != 200:
        print("LOGIN_FAIL", st, login)
        return 1
    token = login["access_token"]
    st, me = call("GET", "/api/mobile/v1/me", token=token)
    if st != 200 or me.get("scope") != "ASSIGNED_PORTFOLIO":
        print("ME_FAIL", st, me)
        return 1
    print("ME", me["role"], me["scope"], me.get("producer_profile_id"))

    failures: list[tuple] = []

    st, cust = call("GET", "/api/mobile/v1/customers", token=token)
    if st != 200:
        print("CUSTOMERS_FAIL", st, cust)
        return 1
    items = cust.get("items") or []
    print("CUSTOMERS", len(items))
    for c in items:
        cid = c["id"]
        sd, _ = call("GET", f"/api/mobile/v1/customers/{cid}", token=token)
        sz, zbody = call("GET", f"/api/mobile/v1/customers/{cid}/360", token=token)
        npol = len((zbody or {}).get("policies") or [])
        print(
            f"  {c.get('name')!r} {cid[:8]} detail={sd} 360={sz} policies={npol}"
        )
        if sd != 200 or sz != 200 or npol < 1:
            failures.append(("customer", cid, sd, sz, npol))

    st, pols = call("GET", "/api/mobile/v1/policies", token=token)
    if st != 200:
        print("POLICIES_FAIL", st, pols)
        return 1
    pitems = pols.get("items") or []
    print("POLICIES", len(pitems))
    for p in pitems:
        pid = p["id"]
        sd, _ = call("GET", f"/api/mobile/v1/policies/{pid}", token=token)
        print(f"  {p.get('policy_number')} {pid[:8]} detail={sd}")
        if sd != 200:
            failures.append(("policy", pid, sd))

    if failures:
        print("SMOKE_FAIL", failures)
        return 1
    print("SMOKE_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
