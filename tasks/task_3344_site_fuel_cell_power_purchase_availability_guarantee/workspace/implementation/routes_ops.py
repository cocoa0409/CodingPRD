"""Portfolio batch operations and the logical clock."""

from flask import Blueprint, request

import calc
import constants as C
import middleware
import settle_calc
import store
import transitions
from errors import ERR_INVALID_REQUEST, ERR_SITE_NOT_FOUND, ApiError
from fields import Body

bp = Blueprint("ops", __name__)


def target_sites(body):
    site_id = body.opt("site_id", "string")
    if site_id:
        site = store.get_site(site_id)
        if site is None:
            raise ApiError(ERR_SITE_NOT_FOUND, "no site exists with that id", 404)
        return [site]
    return store.by_created(list(store.sites.values()))


@bp.route("/power/_ops/recompute-index-bases", methods=["POST"])
def recompute_index_bases():
    middleware.authenticate(request.headers, ("POST", "/power/_ops/recompute-index-bases"))
    body = Body(request.get_json(silent=True))
    sites = target_sites(body)
    contracts = 0
    for site in sites:
        for ppa in store.site_ppas(site["id"]):
            calc.recompute_ppa(ppa)
            contracts += 1
        calc.recompute_site(site)
        store.touch(site)
    return middleware.ok({
        "operation": "recompute-index-bases",
        "processed_count": len(sites),
        "contracts_processed": contracts,
        "site_ids": [s["id"] for s in sites],
        "current_utc": store.now_iso(),
    })


@bp.route("/power/_ops/rollover-period", methods=["POST"])
def rollover_period():
    middleware.authenticate(request.headers, ("POST", "/power/_ops/rollover-period"))
    body = Body(request.get_json(silent=True))
    sites = target_sites(body)
    settled_ids = []
    carry = C.POOL_OPENING_CENTS
    savings = 0
    for site in sites:
        candidates = [ln for ln in store.settlement_lines.values()
                      if ln.get("status") == "SETTLEMENT_APPROVED"
                      and (store.get_ppa(ln["ppa_id"]) or {}).get("site_id") == site["id"]
                      and store.parse_dt(ln["period_end"]) <= store.clock()]
        candidates.sort(key=lambda ln: (ln.get("period_end") or "", ln.get("created_at") or "",
                                        -int(ln.get("net_charge_cents") or 0)))
        pool = C.POOL_OPENING_CENTS
        for line in candidates:
            settled = int(line.get("net_charge_cents") or 0)
            pool -= settled
            if pool < 0:
                line["settled_cents"] = settled + pool
                pool = 0
            else:
                line["settled_cents"] = settled
            line["status"] = "SETTLEMENT_APPLIED"
            line["applied_at"] = store.now_iso()
            store.touch(line)
            for accrual in store.by_created(store.ppa_accruals(line["ppa_id"])):
                if accrual.get("lifecycle_state") == "ACCRUAL_OPEN" \
                        and (accrual.get("created_at") or "") <= (line.get("created_at") or ""):
                    accrual["lifecycle_state"] = "ACCRUAL_RECONCILED"
                    store.touch(accrual)
            settled_ids.append(line["id"])
            ppa = store.get_ppa(line["ppa_id"])
            if ppa is not None:
                calc.recompute_ppa(ppa)
        carry = pool
        applied = [ln for ln in store.settlement_lines.values()
                   if ln.get("status") == "SETTLEMENT_APPLIED"
                   and (store.get_ppa(ln["ppa_id"]) or {}).get("site_id") == site["id"]]
        if applied:
            savings = settle_calc.availability_savings(site, applied)
        for ppa in store.site_ppas(site["id"]):
            calc.recompute_customer(store.get_customer(ppa["customer_id"]))
        calc.recompute_site(site)
        store.touch(site)
    return middleware.ok({
        "operation": "rollover-period",
        "processed_count": len(sites),
        "settled_line_ids": settled_ids,
        "site_ids": [s["id"] for s in sites],
        "carry_pool_cents": carry,
        "customer_savings_cents": savings,
        "current_utc": store.now_iso(),
    })


@bp.route("/power/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    middleware.authenticate(request.headers, ("POST", "/power/_clock/set_current_utc"))
    body = Body(request.get_json(silent=True))
    current = body.req("current_utc", "string")
    if current is None:
        raise ApiError(ERR_INVALID_REQUEST, "current_utc is required", 400)
    try:
        store.set_clock(current)
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, "current_utc is not a valid instant", 400)
    transitions.process_deferred()
    return middleware.ok({
        "current_utc": store.now_iso(),
        "logical_clock": store.now_iso(),
    })
