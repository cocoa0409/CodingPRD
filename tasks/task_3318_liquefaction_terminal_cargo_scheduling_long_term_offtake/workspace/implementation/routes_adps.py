"""ADPs and cargo slots: creation, revision/supersede, approval gauntlet, reconcile, cancellation."""
import math
from datetime import datetime, timezone
from flask import Blueprint, request

import db
from errors import ok_object, paginate, fail
from util import (auth, require_role, body, req_int, req_num, stamp_new, touch,
                  pub, parse_dt, dt_to_iso, logical_now_iso, is_int)
import services
from services import (apply_spa_expiry, recompute_adp_quantities, spa_of_adp,
                      adp_of_slot, spa_of_slot, owning_customer_id_of_slot,
                      check_customer_owner, feed_gas_requirement, invoice_amount,
                      recompute_schedule_totals, prorate, money2, D, dec2,
                      HANDLING_FEE_PCT, PIPELINE_TARIFF)

bp = Blueprint("adps", __name__)


@bp.post("/api/adps")
def create_adp():
    user_id, role = auth()
    require_role(role, ["CommercialManager"])
    data = body()
    spa_id = data.get("spa_id")
    if not isinstance(spa_id, str) or not spa_id:
        fail("ERR_INVALID_REQUEST", "spa_id is required")
    contract_year = req_int(data, "contract_year")
    has_expected = "expected_spa_version" in data
    expected = data.get("expected_spa_version")
    if has_expected and not is_int(expected):
        fail("ERR_INVALID_REQUEST", "expected_spa_version must be an integer")
    spa = db.spas.get(spa_id)
    if not spa:
        fail("ERR_NOT_FOUND", "spa_id does not exist")
    apply_spa_expiry(spa)
    if has_expected and expected != spa["version"]:
        fail("ERR_STALE_VERSION", "expected_spa_version does not match SPA version")
    if not (spa["contract_year_start"] <= contract_year < spa["contract_year_start"] + spa["term_years"]):
        fail("ERR_INVALID_REQUEST", "contract_year outside SPA term")
    priors = [a for a in db.adps.values()
              if a["spa_id"] == spa_id and a["contract_year"] == contract_year and a["status"] != "SUPERSEDED"]
    revision_no = 1
    prior = None
    if priors:
        prior = max(priors, key=lambda a: a["revision_no"])
        revision_no = prior["revision_no"] + 1
    adp = stamp_new({
        "spa_id": spa_id,
        "contract_year": contract_year,
        "revision_no": revision_no,
        "status": "DRAFT",
        "scheduled_quantity_mmbtu": 0,
        "cancelled_quantity_mmbtu": 0,
        "unallocated_quantity_mmbtu": spa["annual_contract_quantity_mmbtu"],
        "delivered_equivalent_mmbtu": None,
        "shortfall_mmbtu": None,
        "deficiency_amount_usd": None,
    })
    db.adps[adp["id"]] = adp
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        for slot in db.cargo_slots.values():
            if slot["adp_id"] == prior["id"] and slot["lift_status"] != "CANCELLED":
                slot["adp_id"] = adp["id"]
                touch(slot)
        recompute_adp_quantities(prior)
        recompute_adp_quantities(adp)
    # SPA version increments when a new revision is created
    touch(spa)
    return ok_object(pub(adp), 201)


@bp.get("/api/adps/<aid>")
def get_adp(aid):
    auth()
    adp = db.adps.get(aid)
    if not adp:
        fail("ERR_NOT_FOUND", "adp not found")
    return ok_object(pub(adp))


@bp.post("/api/adps/<aid>/propose")
def propose_adp(aid):
    user_id, role = auth()
    require_role(role, ["CommercialManager"])
    adp = db.adps.get(aid)
    if not adp:
        fail("ERR_NOT_FOUND", "adp not found")
    if adp["status"] != "DRAFT":
        fail("ERR_ADP_INVALID_STATE", "ADP is not DRAFT")
    if not any(s["adp_id"] == aid for s in db.cargo_slots.values()):
        fail("ERR_ADP_INVALID_STATE", "ADP has no cargo slots")
    adp["status"] = "PROPOSED"
    touch(adp)
    return ok_object(pub(adp))


@bp.post("/api/adps/<aid>/confirm")
def confirm_adp(aid):
    user_id, role = auth()
    require_role(role, ["CustomerRep"])
    adp = db.adps.get(aid)
    if not adp:
        fail("ERR_NOT_FOUND", "adp not found")
    spa = spa_of_adp(adp)
    check_customer_owner(user_id, spa["customer_id"])
    if adp["status"] != "PROPOSED":
        fail("ERR_ADP_INVALID_STATE", "ADP is not PROPOSED")
    total = sum(s["quantity_mmbtu"] for s in db.cargo_slots.values()
                if s["adp_id"] == aid and s["lift_status"] != "CANCELLED")
    if total > spa["annual_contract_quantity_mmbtu"]:
        fail("ERR_ACQ_EXCEEDED", "slot quantities exceed SPA ACQ")
    adp["status"] = "CONFIRMED"
    touch(adp)
    return ok_object(pub(adp))


@bp.post("/api/adps/<aid>/lock")
def lock_adp(aid):
    user_id, role = auth()
    require_role(role, ["CommercialManager"])
    adp = db.adps.get(aid)
    if not adp:
        fail("ERR_NOT_FOUND", "adp not found")
    if adp["status"] != "CONFIRMED":
        fail("ERR_ADP_INVALID_STATE", "ADP is not CONFIRMED")
    adp["status"] = "LOCKED"
    touch(adp)
    return ok_object(pub(adp))


@bp.post("/api/adps/<aid>/reconcile")
def reconcile_adp(aid):
    user_id, role = auth()
    require_role(role, ["CommercialManager"])
    adp = db.adps.get(aid)
    if not adp:
        fail("ERR_NOT_FOUND", "adp not found")
    data = body()
    ref_price = req_num(data, "reference_index_price_usd_per_mmbtu", min_value=0, min_exclusive=True)
    if adp["status"] != "LOCKED":
        fail("ERR_RECONCILE_PREMATURE", "ADP is not LOCKED")
    year_end = datetime(adp["contract_year"] + 1, 1, 1, tzinfo=timezone.utc)
    if db.get_clock() < year_end:
        fail("ERR_RECONCILE_PREMATURE", "contract year has not ended")
    spa = spa_of_adp(adp)
    slots = [s for s in db.cargo_slots.values() if s["adp_id"] == aid]
    delivered = sum(s["quantity_mmbtu"] for s in slots if s["lift_status"] in ("LOADED", "CANCELLED"))
    lower = spa["annual_contract_quantity_mmbtu"] * (1 - spa["tolerance_pct"])
    shortfall = max(0, math.floor(lower) - delivered)
    deficiency = money2(D(shortfall) * (D(spa["fixed_liquefaction_fee_usd_per_mmbtu"])
                                        + D(spa["commodity_multiplier"]) * D(ref_price)))
    adp["delivered_equivalent_mmbtu"] = delivered
    adp["shortfall_mmbtu"] = shortfall
    adp["deficiency_amount_usd"] = deficiency
    touch(adp)
    return ok_object(pub(adp))


# ---- Cargo slots ----

@bp.post("/api/adps/<aid>/cargo-slots")
def create_cargo_slot(aid):
    user_id, role = auth()
    require_role(role, ["CommercialManager"])
    adp = db.adps.get(aid)
    if not adp:
        fail("ERR_NOT_FOUND", "adp not found")
    data = body()
    ws_raw = data.get("window_start")
    we_raw = data.get("window_end")
    quantity = req_int(data, "quantity_mmbtu")
    if quantity <= 0:
        fail("ERR_INVALID_REQUEST", "quantity_mmbtu must be > 0")
    ws = parse_dt(ws_raw, "window_start")
    we = parse_dt(we_raw, "window_end")
    if adp["status"] != "DRAFT":
        fail("ERR_ADP_INVALID_STATE", "cargo slots may only be added to a DRAFT ADP")
    year_start = datetime(adp["contract_year"], 1, 1, tzinfo=timezone.utc)
    year_end = datetime(adp["contract_year"] + 1, 1, 1, tzinfo=timezone.utc)
    if ws >= we or ws < year_start or we > year_end:
        fail("ERR_SLOT_WINDOW_INVALID", "slot window invalid or outside the contract year")
    slot = stamp_new({
        "adp_id": aid,
        "window_start": dt_to_iso(ws),
        "window_end": dt_to_iso(we),
        "quantity_mmbtu": quantity,
        "lift_status": "SCHEDULED",
        "billing_status": "UNBILLED",
        "scheduled_feed_gas_mmbtu": feed_gas_requirement(quantity),
        "provisional_invoice_usd": None,
        "final_invoice_usd": None,
        "_window_start_dt": ws,
        "_window_end_dt": we,
    })
    db.cargo_slots[slot["id"]] = slot
    recompute_adp_quantities(adp)
    return ok_object(pub(slot), 201)


@bp.get("/api/adps/<aid>/cargo-slots")
def list_adp_slots(aid):
    auth()
    adp = db.adps.get(aid)
    if not adp:
        fail("ERR_NOT_FOUND", "adp not found")
    items = [s for s in db.cargo_slots.values() if s["adp_id"] == aid]
    items.sort(key=lambda s: (s["created_at"], s["id"]))
    return paginate([pub(s) for s in items], request.args)


@bp.get("/api/cargo-slots/<sid>")
def get_cargo_slot(sid):
    auth()
    slot = db.cargo_slots.get(sid)
    if not slot:
        fail("ERR_NOT_FOUND", "cargo slot not found")
    return ok_object(pub(slot))


@bp.get("/api/cargo-slots/<sid>/vessel-calls")
def list_slot_calls(sid):
    auth()
    slot = db.cargo_slots.get(sid)
    if not slot:
        fail("ERR_NOT_FOUND", "cargo slot not found")
    items = [c for c in db.vessel_calls.values() if c["cargo_slot_id"] == sid]
    items.sort(key=lambda c: (c["created_at"], c["id"]))
    return paginate([pub(c) for c in items], request.args)


@bp.get("/api/cargo-slots/<sid>/cancellations")
def list_slot_cancellations(sid):
    auth()
    slot = db.cargo_slots.get(sid)
    if not slot:
        fail("ERR_NOT_FOUND", "cargo slot not found")
    items = [c for c in db.cancellations.values() if c["cargo_slot_id"] == sid]
    items.sort(key=lambda c: (c["created_at"], c["id"]))
    return paginate([pub(c) for c in items], request.args)


@bp.get("/api/cargo-slots/<sid>/nominations")
def list_slot_nominations(sid):
    auth()
    slot = db.cargo_slots.get(sid)
    if not slot:
        fail("ERR_NOT_FOUND", "cargo slot not found")
    items = [n for n in db.nominations.values() if n["cargo_slot_id"] == sid]
    items.sort(key=lambda n: (n["created_at"], n["id"]))
    return paginate([pub(n) for n in items], request.args)


@bp.post("/api/cargo-slots/<sid>/issue-final-invoice")
def issue_final_invoice(sid):
    user_id, role = auth()
    require_role(role, ["CommercialManager"])
    slot = db.cargo_slots.get(sid)
    if not slot:
        fail("ERR_NOT_FOUND", "cargo slot not found")
    data = body()
    actual = req_num(data, "actual_index_price_usd_per_mmbtu", min_value=0, min_exclusive=True)
    if slot["lift_status"] != "LOADED" or slot["billing_status"] != "PROVISIONALLY_INVOICED":
        fail("ERR_SLOT_INVALID_STATE", "slot is not LOADED with PROVISIONALLY_INVOICED billing")
    spa = spa_of_slot(slot)
    slot["final_invoice_usd"] = invoice_amount(
        slot["quantity_mmbtu"], spa["fixed_liquefaction_fee_usd_per_mmbtu"],
        spa["commodity_multiplier"], actual)
    slot["billing_status"] = "FINAL_INVOICED"
    touch(slot)
    return ok_object(pub(slot))


# ---- Cancellation ----

@bp.post("/api/cargo-slots/<sid>/cancellations")
def cancel_slot(sid):
    user_id, role = auth()
    require_role(role, ["CustomerRep"])
    slot = db.cargo_slots.get(sid)
    if not slot:
        fail("ERR_NOT_FOUND", "cargo slot not found")
    spa = spa_of_slot(slot)
    check_customer_owner(user_id, spa["customer_id"])
    if slot["lift_status"] not in ("SCHEDULED", "VESSEL_NOMINATED", "BERTH_ASSIGNED"):
        fail("ERR_SLOT_INVALID_STATE", "slot cannot be cancelled from its current state")
    now = db.get_clock()
    delta_seconds = (slot["_window_start_dt"] - now).total_seconds()
    notice_days = math.floor(delta_seconds / 86400)
    if notice_days < spa["cancellation_notice_days"]:
        fail("ERR_INSUFFICIENT_NOTICE", "insufficient cancellation notice")

    slot["lift_status"] = "CANCELLED"
    touch(slot)

    # supersede any NOMINATED or ACCEPTED vessel call (frees berth window)
    for call in db.vessel_calls.values():
        if call["cargo_slot_id"] == sid and call["status"] in ("NOMINATED", "ACCEPTED"):
            call["status"] = "SUPERSEDED"
            touch(call)

    # cut nominations, then re-prorate each affected CLOSED schedule once
    affected = {}
    for nom in db.nominations.values():
        if nom["cargo_slot_id"] == sid and nom["status"] in ("SUBMITTED", "CONFIRMED"):
            nom["status"] = "CUT"
            nom["confirmed_mmbtu"] = 0
            nom["cut_mmbtu"] = nom["nominated_mmbtu"]
            touch(nom)
            affected[nom["pipeline_day_schedule_id"]] = db.day_schedules[nom["pipeline_day_schedule_id"]]
    for sched in affected.values():
        if sched["status"] == "CLOSED":
            prorate(sched)
        recompute_schedule_totals(sched)
        touch(sched)

    cancellation = stamp_new({
        "cargo_slot_id": sid,
        "cancelled_at": logical_now_iso(),
        "notice_days_provided": notice_days,
        "fixed_fee_due_usd": money2(D(slot["quantity_mmbtu"]) * D(spa["fixed_liquefaction_fee_usd_per_mmbtu"])),
        "resale_credit_usd": 0,
        "net_due_usd": None,
        "status": "REGISTERED",
    })
    db.cancellations[cancellation["id"]] = cancellation

    adp = adp_of_slot(slot)
    recompute_adp_quantities(adp)
    return ok_object(pub(cancellation), 201)
