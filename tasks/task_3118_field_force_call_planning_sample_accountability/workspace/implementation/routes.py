"""All API routes for the Field Force Sample Accountability API."""

import datetime as dt
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import store
from store import now
from util import (
    ApiError, fail, ok, paged, get_json, fresh_entity, bump, now_iso, parse_dt, dt_iso,
)
from domain import (
    req_str, opt_str, req_int, opt_int, req_num, req_bool, req_enum, req_dt, req_field,
    find, get_or_create_balance, find_balance, recalc_balance, check_lot_releasable,
    recompute_attainment, prescriber_ytd, check_prescriber_eligible,
    void_pending_disbursements_for_visit, void_pending_disbursements_for_lot,
    suspend_rep_cascade, supersede_plan, temperature_severity, quarantine_cascade,
)


# ---------------------------------------------------------------------------
# Authentication / authorization
# ---------------------------------------------------------------------------
VALID_ROLES = {"PlatformAdmin", "DistrictManager", "FieldRep", "ComplianceOfficer", "QualityAssurance"}
ANY_ROLE = None  # any of the five


def auth(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not uid.strip():
        fail("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
             "Missing X-User-ID header")
    if not role or role not in VALID_ROLES:
        fail("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
             "Missing or invalid X-User-Role header")
    if allowed_roles is not None and role not in allowed_roles:
        fail("ERR_INSUFFICIENT_PERMISSIONS", 403,
             "Role %s not permitted for this endpoint" % role)
    return uid, role


GET_ADMIN = ["PlatformAdmin"]
GET_ALL = ["PlatformAdmin", "DistrictManager", "FieldRep", "ComplianceOfficer", "QualityAssurance"]
GET_NO_QA = ["PlatformAdmin", "DistrictManager", "FieldRep", "ComplianceOfficer"]
GET_REPS = ["PlatformAdmin", "DistrictManager", "ComplianceOfficer"]


def _flt(value):
    return request.args.get(value)


def _list(items, **filters):
    out = []
    for e in items:
        keep = True
        for field, wanted in filters.items():
            if wanted is None:
                continue
            if e.get(field) != wanted:
                keep = False
                break
        if keep:
            out.append(e)
    return paged(out)


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def clock_set():
    auth(["PlatformAdmin"])
    body = get_json()
    to = req_dt(body, "to_iso8601")
    store.set_clock(to)
    return ok({"current_utc": now_iso()})


# ---------------------------------------------------------------------------
# Regions
# ---------------------------------------------------------------------------
def regions_create():
    auth(["PlatformAdmin"])
    body = get_json()
    code = req_str(body, "region_code")
    name = req_str(body, "name")
    for r in store.regions.values():
        if r["region_code"] == code:
            fail("ERR_INVALID_REQUEST", 400, "region_code must be unique")
    r = fresh_entity({"region_code": code, "name": name, "status": "ACTIVE"})
    store.regions[r["id"]] = r
    return ok(r, 201)


def regions_list():
    auth(GET_ALL)
    return _list(store.regions.values(), status=_flt("status"))


def regions_get(rid):
    auth(GET_ALL)
    return ok(find(store.regions, rid, "Region"))


# ---------------------------------------------------------------------------
# Territories
# ---------------------------------------------------------------------------
def territories_create(region_id):
    auth(["PlatformAdmin"])
    region = find(store.regions, region_id, "Region")
    body = get_json()
    code = req_str(body, "territory_code")
    name = req_str(body, "name")
    cs = req_dt(body, "cycle_start_date")
    ce = req_dt(body, "cycle_end_date")
    budget = opt_int(body, "cycle_sample_budget_units", minimum=0)
    for t in store.territories.values():
        if t["region_id"] == region["id"] and t["territory_code"] == code:
            fail("ERR_INVALID_REQUEST", 400,
                 "territory_code must be unique within the region")
    t = fresh_entity({
        "region_id": region["id"],
        "territory_code": code,
        "name": name,
        "cycle_start_date": dt_iso(cs),
        "cycle_end_date": dt_iso(ce),
        "cycle_sample_budget_units": budget,
        "alignment_posture": "DRAFT",
        "status": "ACTIVE",
    })
    store.territories[t["id"]] = t
    return ok(t, 201)


def territories_list():
    auth(GET_ALL)
    return _list(store.territories.values(), status=_flt("status"),
                 region_id=_flt("region_id"))


def territories_in_region(region_id):
    auth(GET_ALL)
    find(store.regions, region_id, "Region")
    return _list(store.territories.values(), status=_flt("status"),
                 region_id=region_id)


def territories_get(tid):
    auth(GET_ALL)
    return ok(find(store.territories, tid, "Territory"))


# ---------------------------------------------------------------------------
# Representatives
# ---------------------------------------------------------------------------
def reps_create(territory_id):
    auth(["PlatformAdmin"])
    terr = find(store.territories, territory_id, "Territory")
    body = get_json()
    employee_id = req_str(body, "employee_id")
    full_name = req_str(body, "full_name")
    manager_rep_id = opt_str(body, "manager_rep_id")
    hire = req_dt(body, "hire_date")
    for r in store.representatives.values():
        if r["employee_id"] == employee_id:
            fail("ERR_INVALID_REQUEST", 400, "employee_id must be unique")
    if manager_rep_id is not None:
        mgr = store.representatives.get(manager_rep_id)
        if mgr is None:
            fail("ERR_INVALID_REQUEST", 400, "manager_rep_id does not reference a representative")
    r = fresh_entity({
        "territory_id": terr["id"],
        "employee_id": employee_id,
        "full_name": full_name,
        "manager_rep_id": manager_rep_id,
        "hire_date": dt_iso(hire),
        "compliance_standing": "GOOD",
        "status": "ACTIVE",
    })
    store.representatives[r["id"]] = r
    return ok(r, 201)


def reps_in_territory(territory_id):
    auth(GET_REPS)
    find(store.territories, territory_id, "Territory")
    return _list(store.representatives.values(), status=_flt("status"),
                 territory_id=territory_id)


def reps_list():
    auth(GET_REPS)
    return _list(store.representatives.values(), status=_flt("status"),
                 territory_id=_flt("territory_id"),
                 manager_rep_id=_flt("manager_rep_id"))


def reps_get(rid):
    auth(GET_NO_QA)
    return ok(find(store.representatives, rid, "Representative"))


# ---------------------------------------------------------------------------
# Prescribers
# ---------------------------------------------------------------------------
def prescribers_create():
    auth(["PlatformAdmin"])
    body = get_json()
    npi = req_str(body, "npi_number")
    full_name = req_str(body, "full_name")
    lic = req_str(body, "state_license_number")
    dea = opt_str(body, "dea_number")
    spec = req_str(body, "specialty_code")
    for p in store.prescribers.values():
        if p["npi_number"] == npi:
            fail("ERR_INVALID_REQUEST", 400, "npi_number must be unique")
    p = fresh_entity({
        "npi_number": npi,
        "full_name": full_name,
        "state_license_number": lic,
        "dea_number": dea,
        "specialty_code": spec,
        "eligibility_status": "PENDING_REVIEW",
        "eligibility_checked_at": None,
    })
    store.prescribers[p["id"]] = p
    return ok(p, 201)


def prescribers_list():
    auth(GET_NO_QA)
    return _list(store.prescribers.values(),
                 eligibility_status=_flt("eligibility_status"))


def prescribers_get(pid):
    auth(GET_NO_QA)
    return ok(find(store.prescribers, pid, "Prescriber"))


def prescribers_verify(pid):
    auth(["ComplianceOfficer"])
    p = find(store.prescribers, pid, "Prescriber")
    body = get_json()
    outcome = req_enum(body, "outcome", ("PASS", "FAIL"))
    p["eligibility_status"] = "ELIGIBLE" if outcome == "PASS" else "EXPIRED_LICENSE"
    p["eligibility_checked_at"] = now_iso()
    bump(p)
    return ok(p)


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------
def products_create():
    auth(["PlatformAdmin"])
    body = get_json()
    ndc = req_str(body, "ndc_code")
    brand = req_str(body, "brand_name")
    controlled = req_bool(body, "controlled")
    per_visit = req_int(body, "per_visit_max_units", minimum=0)
    annual = req_int(body, "annual_max_units_per_prescriber", minimum=0)
    tmin = req_num(body, "storage_temp_min_c")
    tmax = req_num(body, "storage_temp_max_c")
    for p in store.products.values():
        if p["ndc_code"] == ndc:
            fail("ERR_INVALID_REQUEST", 400, "ndc_code must be unique")
    p = fresh_entity({
        "ndc_code": ndc,
        "brand_name": brand,
        "controlled": controlled,
        "per_visit_max_units": per_visit,
        "annual_max_units_per_prescriber": annual,
        "storage_temp_min_c": tmin,
        "storage_temp_max_c": tmax,
        "status": "MARKETED",
    })
    store.products[p["id"]] = p
    return ok(p, 201)


def products_list():
    auth(GET_ALL)
    return _list(store.products.values())


def products_get(pid):
    auth(GET_ALL)
    return ok(find(store.products, pid, "Product"))


# ---------------------------------------------------------------------------
# Sample lots
# ---------------------------------------------------------------------------
def lots_create(product_id):
    auth(["PlatformAdmin"])
    product = find(store.products, product_id, "Product")
    body = get_json()
    lot_number = req_str(body, "lot_number")
    exp = req_dt(body, "expiration_date")
    qty = req_int(body, "quantity_received", minimum=1)
    for lot in store.sample_lots.values():
        if lot["product_id"] == product["id"] and lot["lot_number"] == lot_number:
            fail("ERR_INVALID_REQUEST", 400,
                 "lot_number must be unique per product")
    lot = fresh_entity({
        "product_id": product["id"],
        "lot_number": lot_number,
        "expiration_date": dt_iso(exp),
        "quantity_received": qty,
        "quantity_available": qty,
        "status": "RELEASED",
        "quarantine_reason": "NONE",
    })
    store.sample_lots[lot["id"]] = lot
    return ok(lot, 201)


def lots_list():
    auth(GET_ALL)
    return _list(store.sample_lots.values(), status=_flt("status"),
                 product_id=_flt("product_id"))


def lots_in_product(product_id):
    auth(GET_ALL)
    find(store.products, product_id, "Product")
    return _list(store.sample_lots.values(), status=_flt("status"),
                 product_id=product_id)


def lots_get(lid):
    auth(GET_ALL)
    return ok(find(store.sample_lots, lid, "SampleLot"))


# ---------------------------------------------------------------------------
# Rep lot balances / issuance
# ---------------------------------------------------------------------------
def balances_issue(rep_id):
    auth(["PlatformAdmin"])
    rep = find(store.representatives, rep_id, "Representative")
    body = get_json()
    lot_id = req_str(body, "lot_id")
    quantity = req_int(body, "quantity", minimum=1)
    lot = find(store.sample_lots, lot_id, "SampleLot")
    if lot["quantity_available"] < quantity:
        fail("ERR_QUANTITY_LIMIT_EXCEEDED", 422,
             "Lot availability is insufficient for this issuance")
    b = get_or_create_balance(rep["id"], lot)
    lot["quantity_available"] -= quantity
    bump(lot)
    b["qty_issued"] += quantity
    recalc_balance(b)
    bump(b)
    return ok(b, 201)


def balances_for_rep(rep_id):
    auth(GET_NO_QA)
    find(store.representatives, rep_id, "Representative")
    return _list(store.lot_balances.values(), lot_id=_flt("lot_id"),
                 representative_id=rep_id)


def balances_list():
    auth(GET_NO_QA)
    return _list(store.lot_balances.values(),
                 representative_id=_flt("representative_id"),
                 lot_id=_flt("lot_id"), product_id=_flt("product_id"))


def balances_get(bid):
    auth(GET_NO_QA)
    return ok(find(store.lot_balances, bid, "RepLotBalance"))


# ---------------------------------------------------------------------------
# Target list entries
# ---------------------------------------------------------------------------
TIER_CALLS = {"A": 12, "B": 6, "C": 2}


def entries_create(territory_id):
    auth(["DistrictManager"])
    terr = find(store.territories, territory_id, "Territory")
    body = get_json()
    prescriber_id = req_str(body, "prescriber_id")
    product_id = req_str(body, "product_id")
    tier = req_enum(body, "tier", ("A", "B", "C"))
    planned_units = req_int(body, "planned_sample_units", minimum=0)
    find(store.prescribers, prescriber_id, "Prescriber")
    find(store.products, product_id, "Product")
    # No target-list edits while the territory's plan is LOCKED
    for plan in store.call_plans.values():
        if plan["territory_id"] == terr["id"] and plan["status"] == "LOCKED":
            fail("ERR_INVALID_STATE", 409,
                 "Target list is locked while a plan is LOCKED for this territory")
    e = fresh_entity({
        "territory_id": terr["id"],
        "prescriber_id": prescriber_id,
        "product_id": product_id,
        "tier": tier,
        "planned_calls_per_cycle": TIER_CALLS[tier],
        "delivered_calls": 0,
        "planned_sample_units": planned_units,
        "delivered_sample_units": 0,
        "call_attainment_pct_planned_basis": 0.0,
        "call_attainment_pct_delivered_basis": 0.0,
        "status": "ACTIVE",
    })
    store.target_entries[e["id"]] = e
    return ok(e, 201)


def entries_in_territory(territory_id):
    auth(GET_NO_QA)
    find(store.territories, territory_id, "Territory")
    return _list(store.target_entries.values(), status=_flt("status"),
                 territory_id=territory_id)


def entries_list():
    auth(GET_NO_QA)
    return _list(store.target_entries.values(), status=_flt("status"),
                 territory_id=_flt("territory_id"),
                 prescriber_id=_flt("prescriber_id"),
                 product_id=_flt("product_id"))


def entries_get(eid):
    auth(GET_NO_QA)
    return ok(find(store.target_entries, eid, "TargetListEntry"))


# ---------------------------------------------------------------------------
# Call plans
# ---------------------------------------------------------------------------
TIER_WEIGHTS = {"A": 6, "B": 3, "C": 1}


def plans_create():
    auth(["DistrictManager"])
    body = get_json()
    territory_id = req_str(body, "territory_id")
    cycle_label = req_str(body, "cycle_label")
    expected_version = req_int(body, "expected_territory_version")
    terr = find(store.territories, territory_id, "Territory")
    # OCC (priority 5)
    if terr["version"] != expected_version:
        fail("ERR_STALE_VERSION", 412,
             "Territory version has advanced since it was last observed")
    # Budget check + auto-seed (priority 13)
    active_entries = [e for e in store.target_entries.values()
                      if e["territory_id"] == terr["id"] and e["status"] == "ACTIVE"]
    seeded = []
    if terr.get("cycle_sample_budget_units") is not None and active_entries:
        budget = terr["cycle_sample_budget_units"]
        sum_weights = sum(TIER_WEIGHTS[e["tier"]] for e in active_entries)
        for e in active_entries:
            raw = (Decimal(budget) * Decimal(TIER_WEIGHTS[e["tier"]])
                   / Decimal(sum_weights))
            per_entry = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            seeded.append((e, per_entry))
        consumed = sum(u for _, u in seeded)
        if consumed > budget:
            fail("ERR_TERRITORY_BUDGET_EXCEEDED", 422,
                 "Sum of per-entry planned units exceeds the territory cycle budget")
    # Supersede prior plans
    for plan in list(store.call_plans.values()):
        if plan["territory_id"] != terr["id"]:
            continue
        if plan["status"] == "LOCKED":
            fail("ERR_PLAN_LOCKED", 409,
                 "A LOCKED plan exists for this territory and cannot be superseded")
        if plan["status"] in ("DRAFT", "PUBLISHED"):
            if plan["status"] == "PUBLISHED":
                completed = any(
                    v["call_plan_id"] == plan["id"] and v["call_status"] == "COMPLETED"
                    for v in store.call_visits.values()
                )
                if completed:
                    fail("ERR_PLAN_LOCKED", 409,
                         "The existing PUBLISHED plan already has completed visits")
            supersede_plan(plan)
    p = fresh_entity({
        "territory_id": terr["id"],
        "cycle_label": cycle_label,
        "status": "DRAFT",
        "published_at": None,
        "total_planned_calls": sum(e["planned_calls_per_cycle"] for e in active_entries),
    })
    store.call_plans[p["id"]] = p
    for e, units in seeded:
        e["planned_sample_units"] = units
        bump(e)
    bump(terr)
    return ok(p, 201)


def plans_list():
    auth(GET_NO_QA)
    return _list(store.call_plans.values(), status=_flt("status"),
                 territory_id=_flt("territory_id"))


def plans_get(pid):
    auth(GET_NO_QA)
    return ok(find(store.call_plans, pid, "CallPlan"))


def plans_publish(pid):
    auth(["DistrictManager"])
    plan = find(store.call_plans, pid, "CallPlan")
    if plan["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", 409, "Only a DRAFT plan can be published")
    terr = find(store.territories, plan["territory_id"], "Territory")
    if terr["status"] != "ACTIVE":
        fail("ERR_TERRITORY_NOT_ACTIVE", 409, "Territory is not ACTIVE")
    active_entries = [e for e in store.target_entries.values()
                      if e["territory_id"] == terr["id"] and e["status"] == "ACTIVE"]
    if len(active_entries) < 1:
        fail("ERR_EMPTY_TARGET_LIST", 409,
             "Publish requires at least one ACTIVE target-list entry")
    cs = parse_dt(terr["cycle_start_date"])
    ce = parse_dt(terr["cycle_end_date"])
    for other in store.call_plans.values():
        if other["id"] == plan["id"]:
            continue
        if other["territory_id"] != terr["id"] or other["status"] != "PUBLISHED":
            continue
        oterr = store.territories.get(other["territory_id"])
        if oterr is None:
            continue
        ocs = parse_dt(oterr["cycle_start_date"])
        oce = parse_dt(oterr["cycle_end_date"])
        if ocs < ce and cs < oce:
            fail("ERR_PLAN_CYCLE_OVERLAP", 409,
                 "Another PUBLISHED plan overlaps this territory cycle window")
    plan["status"] = "PUBLISHED"
    plan["published_at"] = now_iso()
    bump(plan)
    terr["alignment_posture"] = "PUBLISHED"
    bump(terr)
    return ok(plan)


# ---------------------------------------------------------------------------
# Call visits
# ---------------------------------------------------------------------------
def _intervals_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def visits_create(uid, role):
    body = get_json()
    call_plan_id = req_str(body, "call_plan_id")
    entry_id = req_str(body, "target_list_entry_id")
    ss = req_dt(body, "scheduled_start")
    se = req_dt(body, "scheduled_end")
    plan = find(store.call_plans, call_plan_id, "CallPlan")
    entry = find(store.target_entries, entry_id, "TargetListEntry")
    # Schedule-overlap check (same rep, non-cancelled visits)
    for v in store.call_visits.values():
        if v["representative_id"] != uid or v["call_status"] == "CANCELLED":
            continue
        vs = parse_dt(v["scheduled_start"])
        ve = parse_dt(v["scheduled_end"])
        if _intervals_overlap(ss, se, vs, ve):
            fail("ERR_VISIT_SCHEDULE_OVERLAP", 409,
                 "New visit overlaps an existing visit of this representative")
    v = fresh_entity({
        "call_plan_id": plan["id"],
        "representative_id": uid,
        "target_list_entry_id": entry["id"],
        "prescriber_id": entry["prescriber_id"],
        "scheduled_start": dt_iso(ss),
        "scheduled_end": dt_iso(se),
        "call_status": "SCHEDULED",
        "signature_status": "NONE",
        "completed_at": None,
    })
    store.call_visits[v["id"]] = v
    return ok(v, 201)


def visits_list():
    auth(GET_NO_QA)
    return _list(store.call_visits.values(),
                 representative_id=_flt("representative_id"),
                 call_plan_id=_flt("call_plan_id"),
                 prescriber_id=_flt("prescriber_id"),
                 call_status=_flt("call_status"),
                 target_list_entry_id=_flt("target_list_entry_id"))


def visits_get(vid):
    auth(GET_NO_QA)
    return ok(find(store.call_visits, vid, "CallVisit"))


def visits_complete(vid, uid, role):
    v = find(store.call_visits, vid, "CallVisit")
    if v["call_status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE", 409, "Only a SCHEDULED visit can be completed")
    if v["representative_id"] != uid:
        fail("ERR_NOT_VISIT_OWNER", 403,
             "Only the owning representative may complete this visit")
    presc = find(store.prescribers, v["prescriber_id"], "Prescriber")
    check_prescriber_eligible(presc)
    entry = find(store.target_entries, v["target_list_entry_id"], "TargetListEntry")
    if entry["status"] != "ACTIVE":
        fail("ERR_TARGET_ENTRY_INACTIVE", 409, "Target-list entry is not ACTIVE")
    rep = find(store.representatives, v["representative_id"], "Representative")
    if rep["compliance_standing"] == "SUSPENDED":
        fail("ERR_REP_SUSPENDED", 403, "Representative is SUSPENDED")
    ss = parse_dt(v["scheduled_start"])
    se = parse_dt(v["scheduled_end"])
    if not (ss <= now() < se + dt.timedelta(hours=24)):
        fail("ERR_VISIT_WINDOW_EXPIRED", 422,
             "Completion is outside [scheduled_start, scheduled_end + 24h)")
    v["call_status"] = "COMPLETED"
    v["completed_at"] = now_iso()
    bump(v)
    entry["delivered_calls"] += 1
    recompute_attainment(entry)
    bump(entry)
    plan = store.call_plans.get(v["call_plan_id"])
    if plan is not None and plan["status"] == "PUBLISHED":
        plan["status"] = "LOCKED"
        bump(plan)
        terr = store.territories.get(plan["territory_id"])
        if terr is not None:
            terr["alignment_posture"] = "LOCKED"
            bump(terr)
    return ok(v)


def visits_cancel(vid, uid, role):
    v = find(store.call_visits, vid, "CallVisit")
    if v["call_status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE", 409, "Only a SCHEDULED visit can be cancelled")
    v["call_status"] = "CANCELLED"
    bump(v)
    entry = store.target_entries.get(v["target_list_entry_id"])
    if entry is not None:
        recompute_attainment(entry)
        bump(entry)
    void_pending_disbursements_for_visit(v)
    return ok(v)


def visits_no_show(vid, uid, role):
    v = find(store.call_visits, vid, "CallVisit")
    if v["call_status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE", 409, "Only a SCHEDULED visit can be marked NO_SHOW")
    se = parse_dt(v["scheduled_end"])
    if now() < se:
        fail("ERR_VISIT_NOT_DUE", 422, "Visit has not reached its scheduled_end yet")
    v["call_status"] = "NO_SHOW"
    bump(v)
    return ok(v)


# ---------------------------------------------------------------------------
# Sample disbursements
# ---------------------------------------------------------------------------
def disbursements_create(uid, role):
    body = get_json()
    call_visit_id = req_str(body, "call_visit_id")
    lot_id = req_str(body, "lot_id")
    quantity = req_int(body, "quantity", minimum=1)
    visit = find(store.call_visits, call_visit_id, "CallVisit")
    lot = find(store.sample_lots, lot_id, "SampleLot")
    presc = find(store.prescribers, visit["prescriber_id"], "Prescriber")
    product = find(store.products, lot["product_id"], "Product")
    entry = find(store.target_entries, visit["target_list_entry_id"], "TargetListEntry")
    # Priority 7: prescriber eligibility (incl. DEA for controlled product)
    check_prescriber_eligible(presc, product)
    # Priority 8: lot releasable
    check_lot_releasable(lot)
    # Priority 12: four-term cap
    bal = get_or_create_balance(visit["representative_id"], lot)
    remaining_annual = max(product["annual_max_units_per_prescriber"]
                           - prescriber_ytd(presc["id"]), 0)
    remaining_entry = max(entry["planned_sample_units"]
                          - entry["delivered_sample_units"], 0)
    cap = min(product["per_visit_max_units"],
              remaining_annual,
              bal["qty_available_forward"],
              remaining_entry)
    if quantity > cap:
        fail("ERR_QUANTITY_LIMIT_EXCEEDED", 422,
             "Quantity %d exceeds the applicable cap of %d" % (quantity, cap))
    d = fresh_entity({
        "call_visit_id": visit["id"],
        "representative_id": visit["representative_id"],
        "prescriber_id": visit["prescriber_id"],
        "lot_id": lot["id"],
        "quantity": quantity,
        "signature_payload": None,
        "signed_at": None,
        "reconciliation_status": "PENDING_SIGNATURE",
    })
    store.disbursements[d["id"]] = d
    bump(lot)
    return ok(d, 201)


def disbursements_list():
    auth(GET_NO_QA)
    return _list(store.disbursements.values(),
                 representative_id=_flt("representative_id"),
                 prescriber_id=_flt("prescriber_id"),
                 lot_id=_flt("lot_id"),
                 reconciliation_status=_flt("reconciliation_status"))


def disbursements_get(did):
    auth(GET_NO_QA)
    return ok(find(store.disbursements, did, "SampleDisbursement"))


def disbursements_capture(did, uid, role):
    d = find(store.disbursements, did, "SampleDisbursement")
    body = get_json()
    payload = body.get("signature_payload")
    if not isinstance(payload, str) or len(payload) < 32:
        fail("ERR_SIGNATURE_REQUIRED", 400,
             "signature_payload is required and must be at least 32 characters")
    if d["reconciliation_status"] != "PENDING_SIGNATURE":
        fail("ERR_INVALID_STATE", 409,
             "Only a PENDING_SIGNATURE disbursement can be signed")
    visit = find(store.call_visits, d["call_visit_id"], "CallVisit")
    if visit["call_status"] != "COMPLETED":
        fail("ERR_VISIT_NOT_COMPLETED", 409,
             "The parent visit must be COMPLETED before signature capture")
    lot = find(store.sample_lots, d["lot_id"], "SampleLot")
    check_lot_releasable(lot)
    d["reconciliation_status"] = "SIGNED"
    d["signature_payload"] = payload
    d["signed_at"] = now_iso()
    bump(d)
    visit["signature_status"] = "CAPTURED"
    bump(visit)
    # Cascade hop 1: settle the rep's balance
    bal = get_or_create_balance(d["representative_id"], lot)
    bal["qty_dispensed"] += d["quantity"]
    recalc_balance(bal)
    bump(bal)
    # Cascade hop 2: entry progress + cap exhaustion
    entry = store.target_entries.get(visit["target_list_entry_id"])
    if entry is not None:
        entry["delivered_sample_units"] += d["quantity"]
        if entry["delivered_sample_units"] >= entry["planned_sample_units"]:
            entry["status"] = "CAP_EXHAUSTED"
        bump(entry)
    # Cascade hop 3: prescriber annual cap -> INELIGIBLE -> cancel future visits
    product = store.products.get(lot["product_id"])
    presc = store.prescribers.get(d["prescriber_id"])
    if product is not None and presc is not None:
        ytd = prescriber_ytd(presc["id"])
        if ytd >= product["annual_max_units_per_prescriber"] and \
                presc["eligibility_status"] == "ELIGIBLE":
            presc["eligibility_status"] = "INELIGIBLE"
            bump(presc)
            for v in store.call_visits.values():
                if v["prescriber_id"] == presc["id"] and v["call_status"] == "SCHEDULED":
                    v["call_status"] = "CANCELLED"
                    bump(v)
                    e2 = store.target_entries.get(v["target_list_entry_id"])
                    if e2 is not None:
                        recompute_attainment(e2)
                        bump(e2)
                    void_pending_disbursements_for_visit(v)
    return ok(d)


def disbursements_reject(did, uid, role):
    d = find(store.disbursements, did, "SampleDisbursement")
    if d["reconciliation_status"] != "PENDING_SIGNATURE":
        fail("ERR_INVALID_STATE", 409,
             "Only a PENDING_SIGNATURE disbursement can be rejected")
    d["reconciliation_status"] = "REJECTED"
    bump(d)
    visit = store.call_visits.get(d["call_visit_id"])
    if visit is not None:
        visit["signature_status"] = "REJECTED"
        bump(visit)
    return ok(d)


def disbursements_of_visit(vid):
    auth(GET_NO_QA)
    find(store.call_visits, vid, "CallVisit")
    return _list(store.disbursements.values(), call_visit_id=vid)


# ---------------------------------------------------------------------------
# Count lines
# ---------------------------------------------------------------------------
def count_lines_list():
    auth(GET_NO_QA)
    return _list(store.count_lines.values(), session_id=_flt("session_id"),
                 lot_id=_flt("lot_id"))


def count_lines_get(cid):
    auth(GET_NO_QA)
    return ok(find(store.count_lines, cid, "CountLine"))


# ---------------------------------------------------------------------------
# Sample transfers
# ---------------------------------------------------------------------------
def transfers_create(uid, role):
    body = get_json()
    to_rep_id = req_str(body, "to_rep_id")
    lot_id = req_str(body, "lot_id")
    quantity = req_int(body, "quantity", minimum=1)
    reason = req_enum(body, "reason_code",
                      ("REBALANCE", "TERRITORY_REALIGN", "SHORTAGE_COVER", "REP_DEPARTURE"))
    note = req_str(body, "documentation_note", minlen=20)
    expected_lot_version = req_int(body, "expected_lot_version")
    lot = find(store.sample_lots, lot_id, "SampleLot")
    # OCC (priority 5)
    if lot["version"] != expected_lot_version:
        fail("ERR_STALE_VERSION", 412,
             "SampleLot version has advanced since it was last observed")
    to_rep = find(store.representatives, to_rep_id, "Representative")
    # Priority 11: segregation of duties
    if to_rep["id"] == uid:
        fail("ERR_SEGREGATION_OF_DUTIES_VIOLATION", 422,
             "Transfer sender and receiver must differ")
    # Priority 8: lot releasable
    check_lot_releasable(lot)
    # Priority 12: quantity vs forward availability
    bal = get_or_create_balance(uid, lot)
    if quantity > bal["qty_available_forward"]:
        fail("ERR_QUANTITY_LIMIT_EXCEEDED", 422,
             "Transfer quantity exceeds the sender's available balance")
    t = fresh_entity({
        "from_rep_id": uid,
        "to_rep_id": to_rep["id"],
        "lot_id": lot["id"],
        "quantity": quantity,
        "reason_code": reason,
        "documentation_note": note,
        "expected_lot_version": expected_lot_version,
        "status": "REQUESTED",
    })
    store.transfers[t["id"]] = t
    bal["qty_in_transit_out"] += quantity
    recalc_balance(bal)
    bump(bal)
    bump(lot)
    return ok(t, 201)


def transfers_list():
    auth(GET_NO_QA)
    return _list(store.transfers.values(), from_rep_id=_flt("from_rep_id"),
                 to_rep_id=_flt("to_rep_id"), lot_id=_flt("lot_id"),
                 status=_flt("status"))


def transfers_get(tid):
    auth(GET_NO_QA)
    return ok(find(store.transfers, tid, "SampleTransfer"))


def _rep_and_territory_active(rep_id):
    rep = store.representatives.get(rep_id)
    if rep is None or rep["status"] != "ACTIVE":
        return False
    terr = store.territories.get(rep["territory_id"])
    if terr is None or terr["status"] != "ACTIVE":
        return False
    return True


def transfers_accept(tid, uid, role):
    t = find(store.transfers, tid, "SampleTransfer")
    if t["status"] != "REQUESTED":
        fail("ERR_INVALID_STATE", 409, "Only a REQUESTED transfer can be accepted")
    if t["to_rep_id"] != uid:
        fail("ERR_NOT_TRANSFER_RECEIVER", 403,
             "Only the transfer receiver may accept")
    lot = find(store.sample_lots, t["lot_id"], "SampleLot")
    check_lot_releasable(lot)
    if not _rep_and_territory_active(t["from_rep_id"]) or \
            not _rep_and_territory_active(t["to_rep_id"]):
        fail("ERR_REP_INACTIVE", 409,
             "Both transfer parties must be ACTIVE reps in ACTIVE territories")
    sender_bal = get_or_create_balance(t["from_rep_id"], lot)
    if sender_bal["qty_in_transit_out"] < t["quantity"]:
        fail("ERR_INSUFFICIENT_RESERVED", 422,
             "The sender's in-transit reserve no longer covers this quantity")
    sender_bal["qty_transferred_out"] += t["quantity"]
    sender_bal["qty_in_transit_out"] -= t["quantity"]
    recalc_balance(sender_bal)
    bump(sender_bal)
    receiver_bal = get_or_create_balance(t["to_rep_id"], lot)
    receiver_bal["qty_transferred_in"] += t["quantity"]
    recalc_balance(receiver_bal)
    bump(receiver_bal)
    t["status"] = "ACCEPTED"
    bump(t)
    return ok(t)


def transfers_reject(tid, uid, role):
    t = find(store.transfers, tid, "SampleTransfer")
    if t["status"] != "REQUESTED":
        fail("ERR_INVALID_STATE", 409, "Only a REQUESTED transfer can be rejected")
    if t["to_rep_id"] != uid:
        fail("ERR_NOT_TRANSFER_RECEIVER", 403,
             "Only the transfer receiver may reject")
    sender_bal = find_balance(t["from_rep_id"], t["lot_id"])
    if sender_bal is not None:
        sender_bal["qty_in_transit_out"] = max(
            sender_bal["qty_in_transit_out"] - t["quantity"], 0)
        recalc_balance(sender_bal)
        bump(sender_bal)
    t["status"] = "REJECTED"
    bump(t)
    return ok(t)


def transfers_cancel(tid, uid, role):
    t = find(store.transfers, tid, "SampleTransfer")
    if t["status"] != "REQUESTED":
        fail("ERR_INVALID_STATE", 409, "Only a REQUESTED transfer can be cancelled")
    if t["from_rep_id"] != uid:
        fail("ERR_NOT_TRANSFER_SENDER", 403,
             "Only the transfer sender may cancel")
    sender_bal = find_balance(t["from_rep_id"], t["lot_id"])
    if sender_bal is not None:
        sender_bal["qty_in_transit_out"] = max(
            sender_bal["qty_in_transit_out"] - t["quantity"], 0)
        recalc_balance(sender_bal)
        bump(sender_bal)
    t["status"] = "CANCELLED"
    bump(t)
    return ok(t)


def transfers_reverse(tid, uid, role):
    t = find(store.transfers, tid, "SampleTransfer")
    if t["status"] != "ACCEPTED":
        fail("ERR_INVALID_STATE", 409, "Only an ACCEPTED transfer can be reversed")
    lot = find(store.sample_lots, t["lot_id"], "SampleLot")
    if lot["status"] != "RELEASED":
        fail("ERR_LOT_NOT_RELEASABLE", 422,
             "The lot must still be RELEASED to reverse a transfer")
    sender_bal = find_balance(t["from_rep_id"], t["lot_id"])
    if sender_bal is not None:
        sender_bal["qty_transferred_out"] = max(
            sender_bal["qty_transferred_out"] - t["quantity"], 0)
        recalc_balance(sender_bal)
        bump(sender_bal)
    receiver_bal = find_balance(t["to_rep_id"], t["lot_id"])
    if receiver_bal is not None:
        receiver_bal["qty_transferred_in"] = max(
            receiver_bal["qty_transferred_in"] - t["quantity"], 0)
        recalc_balance(receiver_bal)
        bump(receiver_bal)
    t["status"] = "REVERSED"
    bump(t)
    return ok(t)


# ---------------------------------------------------------------------------
# Inventory count sessions
# ---------------------------------------------------------------------------
def sessions_create(uid, role):
    body = get_json()
    custodian_id = req_str(body, "representative_id")
    counter_id = req_str(body, "counter_rep_id")
    ws = req_dt(body, "window_start")
    we = req_dt(body, "window_end")
    custodian = find(store.representatives, custodian_id, "Representative")
    counter = find(store.representatives, counter_id, "Representative")
    # Priority 11: segregation of duties
    if counter["id"] == custodian["id"] or \
            (custodian.get("manager_rep_id") is not None
             and counter["id"] == custodian["manager_rep_id"]):
        fail("ERR_SEGREGATION_OF_DUTIES_VIOLATION", 422,
             "The counter must differ from the custodian and the custodian's manager")
    # Priority 10: window overlap + 24h minimum gap
    for s in store.count_sessions.values():
        if s["representative_id"] != custodian["id"] or s["status"] == "VOIDED":
            continue
        sws = parse_dt(s["window_start"])
        swe = parse_dt(s["window_end"])
        if ws < swe and sws < we:
            fail("ERR_COUNT_WINDOW_CONFLICT", 409,
                 "The count window overlaps another session for this custodian")
        if swe <= ws and ws - swe < dt.timedelta(hours=24):
            fail("ERR_COUNT_WINDOW_CONFLICT", 409,
                 "A minimum 24h gap is required between count sessions")
        if we <= sws and sws - we < dt.timedelta(hours=24):
            fail("ERR_COUNT_WINDOW_CONFLICT", 409,
                 "A minimum 24h gap is required between count sessions")
    s = fresh_entity({
        "representative_id": custodian["id"],
        "counter_rep_id": counter["id"],
        "window_start": dt_iso(ws),
        "window_end": dt_iso(we),
        "status": "OPEN",
        "variance_pct": None,
        "disciplinary_tier": "NONE",
        "reopen_count": 0,
    })
    store.count_sessions[s["id"]] = s
    # Auto-create CountLines from forward availability snapshot
    for b in store.lot_balances.values():
        if b["representative_id"] == custodian["id"] and \
                b["qty_available_forward"] > 0:
            line = fresh_entity({
                "session_id": s["id"],
                "lot_id": b["lot_id"],
                "expected_qty": b["qty_available_forward"],
                "counted_qty": None,
                "variance_qty": None,
            })
            store.count_lines[line["id"]] = line
    return ok(s, 201)


def sessions_list():
    auth(GET_NO_QA)
    return _list(store.count_sessions.values(),
                 representative_id=_flt("representative_id"),
                 counter_rep_id=_flt("counter_rep_id"),
                 status=_flt("status"))


def sessions_get(sid):
    auth(GET_NO_QA)
    return ok(find(store.count_sessions, sid, "InventoryCountSession"))


def sessions_count_lines(sid):
    auth(GET_NO_QA)
    find(store.count_sessions, sid, "InventoryCountSession")
    return _list(store.count_lines.values(), session_id=sid)


def sessions_submit_count(sid, uid, role):
    s = find(store.count_sessions, sid, "InventoryCountSession")
    if s["status"] != "OPEN":
        fail("ERR_INVALID_STATE", 409,
             "Counts can only be submitted on an OPEN session")
    if s["counter_rep_id"] != uid:
        fail("ERR_NOT_COUNT_COUNTER", 403,
             "Only the designated counter may submit counts")
    body = get_json()
    lines_in = body.get("lines")
    if not isinstance(lines_in, list):
        fail("ERR_INVALID_REQUEST", 400, "lines must be a list")
    counts = {}
    for item in lines_in:
        if not isinstance(item, dict):
            fail("ERR_INVALID_REQUEST", 400, "each count line must be an object")
        lid = item.get("lot_id")
        cq = item.get("counted_qty")
        if not isinstance(lid, str):
            fail("ERR_INVALID_REQUEST", 400, "each line requires a lot_id")
        if isinstance(cq, bool) or not isinstance(cq, int) or cq < 0:
            fail("ERR_INVALID_REQUEST", 400,
                 "each line requires a non-negative integer counted_qty")
        counts[lid] = cq
    session_lines = [cl for cl in store.count_lines.values()
                     if cl["session_id"] == s["id"]]
    for cl in session_lines:
        if cl["lot_id"] not in counts:
            fail("ERR_INCOMPLETE_COUNT", 422,
                 "Every CountLine of the session must receive a counted_qty")
    for cl in session_lines:
        cl["counted_qty"] = counts[cl["lot_id"]]
        cl["variance_qty"] = cl["counted_qty"] - cl["expected_qty"]
        bump(cl)
    s["status"] = "COUNTED"
    bump(s)
    return ok(s)


def sessions_reconcile(sid, uid, role):
    s = find(store.count_sessions, sid, "InventoryCountSession")
    if s["status"] != "COUNTED":
        fail("ERR_INVALID_STATE", 409,
             "Only a COUNTED session can be reconciled")
    custodian = find(store.representatives, s["representative_id"], "Representative")
    if custodian.get("manager_rep_id") is None or custodian["manager_rep_id"] != uid:
        fail("ERR_NOT_CUSTODIAN_MANAGER", 403,
             "Only the custodian's direct manager may reconcile")
    lines = [cl for cl in store.count_lines.values() if cl["session_id"] == s["id"]]
    abs_var = sum(abs(cl["variance_qty"]) for cl in lines)
    expected_sum = sum(cl["expected_qty"] for cl in lines)
    pct = float(
        (Decimal(abs_var) * Decimal(100) / Decimal(max(expected_sum, 1)))
        .quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    )
    s["variance_pct"] = pct
    if pct < 2.0:
        tier = "NONE"
    elif pct < 5.0:
        tier = "COUNSELING"
    elif pct < 10.0:
        tier = "WRITTEN_WARNING"
    else:
        tier = "SUSPENSION_REVIEW"
    s["disciplinary_tier"] = tier
    s["status"] = "RECONCILED"
    bump(s)
    if tier == "WRITTEN_WARNING":
        custodian["compliance_standing"] = "WATCH"
        bump(custodian)
    elif tier == "SUSPENSION_REVIEW":
        suspend_rep_cascade(custodian)
    return ok(s)


def sessions_reopen(sid, uid, role):
    s = find(store.count_sessions, sid, "InventoryCountSession")
    if s["status"] != "RECONCILED":
        fail("ERR_INVALID_STATE", 409,
             "Only a RECONCILED session can be reopened")
    if s.get("reopen_count", 0) >= 3:
        fail("ERR_REOPEN_LIMIT_EXCEEDED", 409,
             "This session has already been reopened 3 times")
    s["status"] = "OPEN"
    s["reopen_count"] = s.get("reopen_count", 0) + 1
    s["variance_pct"] = None
    s["disciplinary_tier"] = "NONE"
    bump(s)
    custodian = store.representatives.get(s["representative_id"])
    if custodian is not None:
        custodian["compliance_standing"] = "GOOD"
        bump(custodian)
    for cl in store.count_lines.values():
        if cl["session_id"] == s["id"]:
            cl["counted_qty"] = None
            cl["variance_qty"] = None
            bump(cl)
    return ok(s)


def sessions_close(sid, uid, role):
    s = find(store.count_sessions, sid, "InventoryCountSession")
    if s["status"] != "RECONCILED":
        fail("ERR_INVALID_STATE", 409,
             "Only a RECONCILED session can be closed")
    s["status"] = "CLOSED"
    bump(s)
    return ok(s)


def sessions_void(sid, uid, role):
    s = find(store.count_sessions, sid, "InventoryCountSession")
    if s["status"] != "OPEN":
        fail("ERR_INVALID_STATE", 409,
             "Only an OPEN session can be voided")
    s["status"] = "VOIDED"
    bump(s)
    return ok(s)


# ---------------------------------------------------------------------------
# Temperature excursions
# ---------------------------------------------------------------------------
def excursions_create(uid, role):
    body = get_json()
    product_id = req_str(body, "product_id")
    location = req_enum(body, "location_type", ("VEHICLE", "HOME_OFFICE"))
    temp = req_num(body, "observed_temp_c")
    minutes = req_int(body, "excursion_minutes", minimum=0)
    product = find(store.products, product_id, "Product")
    severity = temperature_severity(product, temp, minutes)
    e = fresh_entity({
        "representative_id": uid,
        "product_id": product["id"],
        "location_type": location,
        "observed_temp_c": temp,
        "excursion_minutes": minutes,
        "severity": severity,
        "status": "REPORTED",
    })
    store.excursions[e["id"]] = e
    return ok(e, 201)


def excursions_list():
    auth(GET_ALL)
    return _list(store.excursions.values(),
                 representative_id=_flt("representative_id"),
                 product_id=_flt("product_id"), status=_flt("status"),
                 severity=_flt("severity"))


def excursions_get(eid):
    auth(GET_ALL)
    return ok(find(store.excursions, eid, "TemperatureExcursion"))


def excursions_assess(eid):
    auth(["QualityAssurance"])
    e = find(store.excursions, eid, "TemperatureExcursion")
    if e["status"] != "REPORTED":
        fail("ERR_INVALID_STATE", 409,
             "Only a REPORTED excursion can be assessed")
    e["status"] = "ASSESSED"
    bump(e)
    if e["severity"] == "CRITICAL":
        quarantine_cascade(e["representative_id"], e["product_id"])
    return ok(e)


def excursions_resolve(eid):
    auth(["QualityAssurance"])
    e = find(store.excursions, eid, "TemperatureExcursion")
    if e["status"] != "ASSESSED":
        fail("ERR_INVALID_STATE", 409,
             "Only an ASSESSED excursion can be resolved")
    if e["severity"] == "CRITICAL":
        for b in store.lot_balances.values():
            if b["representative_id"] != e["representative_id"]:
                continue
            lot = store.sample_lots.get(b["lot_id"])
            if lot is None or lot["product_id"] != e["product_id"]:
                continue
            if lot["status"] == "QUARANTINED" and \
                    lot.get("quarantine_reason") == "TEMPERATURE_EXCURSION":
                fail("ERR_QUARANTINE_OPEN", 409,
                     "Quarantined lots must be destroyed or returned before resolution")
    e["status"] = "RESOLVED"
    bump(e)
    return ok(e)


# ---------------------------------------------------------------------------
# Sample returns
# ---------------------------------------------------------------------------
def returns_create(uid, role):
    body = get_json()
    lot_id = req_str(body, "lot_id")
    quantity = req_int(body, "quantity", minimum=1)
    reason = req_enum(body, "return_reason", ("EXPIRED", "DAMAGED", "RECALLED"))
    method = req_enum(body, "destruction_method",
                      ("INCINERATION", "CHEMICAL_NEUTRALIZATION", "RETURN_TO_MANUFACTURER"))
    lot = find(store.sample_lots, lot_id, "SampleLot")
    r = fresh_entity({
        "representative_id": uid,
        "lot_id": lot["id"],
        "quantity": quantity,
        "return_reason": reason,
        "destruction_method": method,
        "destruction_report_ref": None,
        "status": "DRAFT",
    })
    store.sample_returns[r["id"]] = r
    return ok(r, 201)


def returns_list():
    auth(GET_NO_QA)
    return _list(store.sample_returns.values(),
                 representative_id=_flt("representative_id"),
                 lot_id=_flt("lot_id"), status=_flt("status"))


def returns_get(rid):
    auth(GET_NO_QA)
    return ok(find(store.sample_returns, rid, "SampleReturn"))


def returns_submit(rid, uid, role):
    r = find(store.sample_returns, rid, "SampleReturn")
    if r["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", 409, "Only a DRAFT return can be submitted")
    lot = find(store.sample_lots, r["lot_id"], "SampleLot")
    bal = find_balance(r["representative_id"], lot["id"])
    forward = bal["qty_available_forward"] if bal is not None else 0
    if r["quantity"] > forward:
        fail("ERR_INSUFFICIENT_BALANCE", 422,
             "Return quantity exceeds the rep's available balance for this lot")
    if r["return_reason"] == "EXPIRED":
        exp = parse_dt(lot["expiration_date"])
        if exp > now():
            fail("ERR_RETURN_REASON_MISMATCH", 422,
                 "An EXPIRED return requires the lot's expiration_date to be at or before now")
    if bal is None:
        bal = get_or_create_balance(r["representative_id"], lot)
    bal["qty_returned"] += r["quantity"]
    recalc_balance(bal)
    bump(bal)
    r["status"] = "SUBMITTED"
    bump(r)
    return ok(r)


def returns_confirm(rid, uid, role):
    r = find(store.sample_returns, rid, "SampleReturn")
    if r["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", 409,
             "Only a SUBMITTED return can have its destruction confirmed")
    if uid == r["representative_id"]:
        fail("ERR_SELF_CONFIRM_FORBIDDEN", 403,
             "The returning representative may not confirm their own destruction")
    r["status"] = "DESTRUCTION_CONFIRMED"
    r["destruction_report_ref"] = store.next_destruction_ref()
    bump(r)
    lot = store.sample_lots.get(r["lot_id"])
    if lot is not None:
        dispensed = sum(
            d["quantity"] for d in store.disbursements.values()
            if d["lot_id"] == lot["id"] and d["reconciliation_status"] == "SIGNED"
        )
        returned = sum(
            x["quantity"] for x in store.sample_returns.values()
            if x["lot_id"] == lot["id"] and x["status"] == "DESTRUCTION_CONFIRMED"
        )
        if lot["quantity_received"] == dispensed + returned:
            exp = parse_dt(lot["expiration_date"])
            if exp <= now():
                lot["status"] = "DESTROYED"
        bump(lot)
    return ok(r)
