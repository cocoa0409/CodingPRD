"""Domain helpers: path lookups, serializers, derived-field recomputation."""
from datetime import timedelta

import db
from errors import ApiError
from util import now_iso, touch
import calc


# ---------- path lookups (left-to-right nesting) ----------

def get_contract(cid):
    c = db.contracts.get(cid)
    if c is None:
        raise ApiError("ERR_CONTRACT_NOT_FOUND", 404, "contract not found")
    return c


def get_baseline(cid, bid):
    c = get_contract(cid)
    b = db.baselines.get(bid)
    if b is None or b["contract_id"] != c["id"]:
        raise ApiError("ERR_BASELINE_NOT_FOUND", 404, "baseline not found under the contract")
    return c, b


def get_bundle(cid, bid):
    c = get_contract(cid)
    b = db.bundles.get(bid)
    if b is None or b["contract_id"] != c["id"]:
        raise ApiError("ERR_BUNDLE_NOT_FOUND", 404, "bundle not found under the contract")
    return c, b


def get_measure(cid, bid, mid):
    c, b = get_bundle(cid, bid)
    m = db.measures.get(mid)
    if m is None or m["bundle_id"] != b["id"]:
        raise ApiError("ERR_MEASURE_NOT_FOUND", 404, "measure not found under the bundle")
    return c, b, m


def get_facility(cid, fid):
    c = get_contract(cid)
    f = db.facilities.get(fid)
    if f is None or f["contract_id"] != c["id"]:
        raise ApiError("ERR_FACILITY_NOT_FOUND", 404, "facility not found under the contract")
    return c, f


def get_draw(cid, fid, did):
    c, f = get_facility(cid, fid)
    d = db.draws.get(did)
    if d is None or d["facility_id"] != f["id"]:
        raise ApiError("ERR_DRAW_NOT_FOUND", 404, "draw not found under the facility")
    return c, f, d


def get_phase(cid, pid):
    c = get_contract(cid)
    p = db.phases.get(pid)
    if p is None or p["contract_id"] != c["id"]:
        raise ApiError("ERR_PHASE_NOT_FOUND", 404, "phase not found under the contract")
    return c, p


def get_report(cid, rid):
    c = get_contract(cid)
    r = db.reports.get(rid)
    if r is None or r["contract_id"] != c["id"]:
        raise ApiError("ERR_REPORT_NOT_FOUND", 404, "report not found under the contract")
    return c, r


def get_adjustment(cid, aid):
    c = get_contract(cid)
    a = db.adjustments.get(aid)
    if a is None or a["contract_id"] != c["id"]:
        raise ApiError("ERR_ADJUSTMENT_NOT_FOUND", 404, "adjustment not found under the contract")
    return c, a


def get_dispute(cid, did):
    c = get_contract(cid)
    d = db.disputes.get(did)
    if d is None or d["contract_id"] != c["id"]:
        raise ApiError("ERR_DISPUTE_NOT_FOUND", 404, "dispute not found under the contract")
    return c, d


# ---------- serializers ----------

from decimal import Decimal


def _num(v):
    if isinstance(v, Decimal):
        f = float(v)
        return int(f) if f == int(f) and v == v.to_integral_value() else f
    return v


def ser_contract(c):
    return dict(c)


def ser_baseline(b):
    out = dict(b)
    out["heating_degree_days"] = _num(b["heating_degree_days"])
    out["cooling_degree_days"] = _num(b["cooling_degree_days"])
    out["occupancy_factor"] = _num(b["occupancy_factor"])
    return out


def ser_bundle(b):
    return dict(b)


def ser_measure(m):
    out = dict(m)
    sp = m.get("simple_payback_years")
    out["simple_payback_years"] = None if sp is None else float(sp)
    return out


def ser_facility(f):
    out = dict(f)
    out["annual_rate_pct"] = _num(f["annual_rate_pct"])
    return out


def ser_draw(d):
    return dict(d)


def ser_phase(p):
    return dict(p)


def ser_disruption(d):
    return dict(d)


def ser_report(r):
    out = dict(r)
    out["period_hdd"] = _num(r["period_hdd"])
    out["period_cdd"] = _num(r["period_cdd"])
    out["period_occupancy_factor"] = _num(r["period_occupancy_factor"])
    return out


def ser_adjustment(a):
    out = dict(a)
    if a.get("occupancy_factor_override") is not None:
        out["occupancy_factor_override"] = _num(a["occupancy_factor_override"])
    return out


def ser_dispute(d):
    return dict(d)


# ---------- derived-field recomputation ----------

def bundle_measures(bundle_id):
    return [m for m in db.measures.values() if m["bundle_id"] == bundle_id]


def bundle_counted_measures(bundle):
    ms = bundle_measures(bundle["id"])
    if bundle["status"] in ("DRAFT", "PROPOSED"):
        return [m for m in ms if m["status"] in ("PROPOSED", "INCLUDED")]
    return [m for m in ms if m["status"] == "INCLUDED"]


def recompute_bundle(bundle, mutate=True):
    counted = bundle_counted_measures(bundle)
    bundle["blended_payback_years"] = calc.blended_payback(counted)
    bundle["subsidy_pool_cents"] = calc.subsidy_pool(counted)
    if mutate:
        touch(bundle)


def run_waterfall(bundle):
    included = [m for m in bundle_measures(bundle["id"]) if m["status"] == "INCLUDED"]
    calc.subsidy_waterfall(included, bundle["subsidy_pool_cents"])
    for m in included:
        touch(m)


def verified_measures_savings_total(contract_id):
    return sum(m["annual_savings_cents"] for m in db.measures.values()
               if m["contract_id"] == contract_id and m["status"] == "VERIFIED")


def recompute_report_savings(contract, baseline, report):
    report["verified_savings_cents"] = calc.verified_savings(
        contract, baseline, report, verified_measures_savings_total(contract["id"]))
    report["shortfall_cents"] = max(
        0, contract["guaranteed_annual_savings_cents"] - report["verified_savings_cents"])


def recompute_contract_ledgers(contract):
    reconciled = [r for r in db.reports.values()
                  if r["contract_id"] == contract["id"] and r["status"] == "RECONCILED"]
    contract["cumulative_verified_savings_cents"] = sum(
        r["verified_savings_cents"] for r in reconciled)
    reserve = sum(r["shortfall_cents"] for r in reconciled)
    contract["guarantee_shortfall_reserve_cents"] = max(0, reserve)


def add_years(dt, years):
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:
        # Feb 29 -> Feb 28 in non-leap years
        return dt.replace(year=dt.year + years, day=28)


def period_end_threshold(guarantee_start, period_year):
    return add_years(guarantee_start, period_year) - timedelta(days=1)
