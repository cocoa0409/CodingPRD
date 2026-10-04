"""Business services: compliance recompute, cascades, clock sweep."""
from datetime import timedelta

import store
from store import new_id, now

GRACE_PERIOD_DAYS = 90
DEPOT_RETURN_WINDOW_DAYS = 30
ADVANCE_4H_SECONDS = 14400
ADVANCE_NBD_SECONDS = 86400

NON_TERMINAL_RMA = {"OPENED", "REPLACEMENT_SHIPPED", "REPLACEMENT_DELIVERED", "DEFECTIVE_RETURNED"}


def stamp(row):
    row["updated_at"] = now()


def bump(row):
    row["version"] += 1
    stamp(row)


def make_row(with_version=True):
    ts = now()
    row = {"id": new_id(), "created_at": ts}
    if with_version:
        row["updated_at"] = ts
        row["version"] = 1
    return row


def pool_account(pool):
    va = store.DB["virtual_accounts"].get(pool["virtual_account_id"])
    if not va:
        return None
    return store.DB["smart_accounts"].get(va["smart_account_id"])


def effective_purchased(pool):
    if pool["license_model"] == "SUBSCRIPTION" and pool["subscription_expires_at"] is not None:
        if now() >= pool["subscription_expires_at"]:
            return 0
    return pool["purchased_quantity"]


def add_compliance_event(pool, event_type):
    ev = make_row(with_version=False)
    ev.update({
        "license_pool_id": pool["id"],
        "event_type": event_type,
        "occurred_at": now(),
        "consumed_quantity": pool["consumed_quantity"],
        "purchased_quantity": pool["purchased_quantity"],
    })
    store.DB["compliance_events"][ev["id"]] = ev


def latest_accepted_reports():
    """device_id -> latest ACCEPTED usage report (max reported_at; latest created on tie)."""
    latest = {}
    seq = {}
    for rep in store.DB["usage_reports"].values():
        if rep["status"] != "ACCEPTED":
            continue
        seq[rep["id"]] = len(seq)
        cur = latest.get(rep["device_id"])
        if cur is None:
            latest[rep["device_id"]] = rep
            continue
        if (rep["reported_at"], seq[rep["id"]]) >= (cur["reported_at"], seq[cur["id"]]):
            latest[rep["device_id"]] = rep
    return latest


def recompute_pool(pool):
    """PRD 3.2 reconciled consumption + compliance state machine."""
    latest = latest_accepted_reports()
    consumed = 0
    for a in store.DB["assignments"].values():
        if a["license_pool_id"] != pool["id"] or a["status"] != "ACTIVE":
            continue
        if a["device_id"] in latest:
            continue  # device's report truth supersedes its assignments
        consumed += a["quantity"]
    for rep in latest.values():
        for line in rep["lines"]:
            if line.get("license_pool_id") == pool["id"]:
                consumed += line.get("quantity", 0)
    pool["consumed_quantity"] = consumed

    eff = effective_purchased(pool)
    state = pool["compliance_state"]
    if consumed > eff:
        if state == "COMPLIANT":
            pool["overage_detected_at"] = now()
            pool["grace_deadline"] = now() + timedelta(days=GRACE_PERIOD_DAYS)
            pool["compliance_state"] = "IN_GRACE"
            add_compliance_event(pool, "OVERAGE_DETECTED")
            add_compliance_event(pool, "GRACE_STARTED")
            bump(pool)
        elif state == "IN_GRACE" and now() > pool["grace_deadline"]:
            pool["compliance_state"] = "OUT_OF_COMPLIANCE"
            add_compliance_event(pool, "GRACE_EXPIRED")
            bump(pool)
    else:
        if state in ("IN_GRACE", "OUT_OF_COMPLIANCE"):
            pool["compliance_state"] = "COMPLIANT"
            pool["overage_detected_at"] = None
            pool["grace_deadline"] = None
            add_compliance_event(pool, "RESTORED_TO_COMPLIANCE")
            bump(pool)
    recompute_posture(pool)


def recompute_posture(pool):
    acct = pool_account(pool)
    if not acct:
        return
    states = [
        p["compliance_state"]
        for p in store.DB["license_pools"].values()
        if (lambda va: va and va["smart_account_id"] == acct["id"])(
            store.DB["virtual_accounts"].get(p["virtual_account_id"]))
    ]
    if any(s == "OUT_OF_COMPLIANCE" for s in states):
        acct["compliance_posture"] = "NON_COMPLIANT"
    elif any(s == "IN_GRACE" for s in states):
        acct["compliance_posture"] = "GRACE"
    else:
        acct["compliance_posture"] = "COMPLIANT"


def void_coverage(cov):
    if cov["status"] == "ACTIVE":
        cov["status"] = "VOIDED"
        bump(cov)


def cancel_contract(contract):
    if contract["status"] != "ACTIVE":
        return
    contract["status"] = "CANCELLED"
    bump(contract)
    for cov in store.DB["contract_coverages"].values():
        if cov["service_contract_id"] == contract["id"]:
            void_coverage(cov)


def expire_contract(contract):
    if contract["status"] != "ACTIVE":
        return
    contract["status"] = "EXPIRED"
    bump(contract)
    for cov in store.DB["contract_coverages"].values():
        if cov["service_contract_id"] == contract["id"]:
            void_coverage(cov)


def refresh_rma_sla(case):
    """Lazy sla_breached evaluation per rma_ship_by / depot_return_sla."""
    if case["status"] in ("CLOSED", "CANCELLED"):
        return
    cov = store.DB["contract_coverages"].get(case["contract_coverage_id"])
    contract = store.DB["service_contracts"].get(cov["service_contract_id"]) if cov else None
    if not contract:
        return
    level = contract["service_level"]
    changed = False
    if level in ("ADVANCE_4H", "ADVANCE_NBD"):
        if case["status"] == "OPENED" and case["ship_by"] is not None and now() > case["ship_by"]:
            if not case["sla_breached"]:
                case["sla_breached"] = True
                changed = True
        if case["status"] == "REPLACEMENT_DELIVERED" and case.get("delivered_at") is not None:
            deadline = case["delivered_at"] + timedelta(days=DEPOT_RETURN_WINDOW_DAYS)
            if now() > deadline and not case["sla_breached"]:
                case["sla_breached"] = True
                changed = True
    if changed:
        bump(case)


def sweep_clock():
    """Lazy evaluation on clock advance (PRD 2.4 / clock endpoint)."""
    for pool in store.DB["license_pools"].values():
        recompute_pool(pool)
    for contract in store.DB["service_contracts"].values():
        if contract["status"] == "ACTIVE" and now() >= contract["end_date"]:
            expire_contract(contract)
    for case in store.DB["rma_cases"].values():
        refresh_rma_sla(case)


def close_account_cascade(acct):
    for va in store.DB["virtual_accounts"].values():
        if va["smart_account_id"] == acct["id"] and va["status"] == "ACTIVE":
            va["status"] = "ARCHIVED"
            bump(va)
    for contract in store.DB["service_contracts"].values():
        if contract["smart_account_id"] == acct["id"] and contract["status"] == "ACTIVE":
            cancel_contract(contract)
    for d in store.DB["partner_delegations"].values():
        if d["smart_account_id"] == acct["id"] and d["status"] == "ACTIVE":
            d["status"] = "REVOKED"
            d["revoked_at"] = now()
            bump(d)
