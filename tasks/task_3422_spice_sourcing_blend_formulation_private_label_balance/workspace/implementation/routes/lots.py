"""RawLot receiving, listing, safety tests, and disposition (PRD 3.1-3.2).

Includes the pinned lot-state automations:
- first test: RECEIVED -> IN_TEST; retest: QUARANTINED -> IN_TEST
- ADULTERANT_SCREEN FAIL: IN_TEST|ACCEPTED -> QUARANTINED + adulterant cascade
- REJECT: quantity_wasted_kg += quantity_remaining_kg; remaining -> 0
- ACCEPT releasing a quarantine episode unwinds cascade batch holds /
  auto-closes DRAFT AUTO_QUARANTINE recalls naming the lot.
"""
from decimal import Decimal
from uuid import uuid4

from flask import Blueprint, g, request

from errors import ApiError
from helpers import (ALLERGEN_PROFILES, SPICE_CODES, TEST_TYPES, D, F,
                     filter_enum, invalid_state, new_entity, not_found, paged,
                     pub, q3, require_roles, respond, stamp, touch,
                     validate_body, validation_error)
from services.recall import adulterant_cascade, release_cascade
from state import DB

bp = Blueprint("lots", __name__)

LOT_STATUSES = ["RECEIVED", "IN_TEST", "ACCEPTED", "QUARANTINED", "REJECTED", "DEPLETED"]
LOT_READ_ROLES = ("SupplyPlanner", "QualityAnalyst", "QualityManager",
                  "FlavorScientist", "ProductionScheduler", "SupplierRep")

# calculations.lot_test_result — pinned action levels
LEAD_LIMIT_PPM = Decimal("2.00")        # ADULTERANT_SCREEN: FAIL when >= 2.00
PESTICIDE_LIMIT_PPM = Decimal("0.10")   # PESTICIDE: FAIL when >= 0.10
MICRO_LIMIT_CFU_G = Decimal("100000")   # MICRO: FAIL when > 100000 (at-limit passes)
MOISTURE_LIMIT_PCT = Decimal("12.0")    # MOISTURE: FAIL when > 12.0 (at-limit passes)
REQUIRED_TEST_SUITE = ["MICRO", "ADULTERANT_SCREEN", "MOISTURE"]

CROP_YEAR_MIN = 2000
CROP_YEAR_MAX = 2100


@bp.post("/spice/lots")
@require_roles("SupplyPlanner")
def create_lot():
    data = validate_body({
        "supplier_id": F("str", required=True),
        "spice_code": F("enum", enum=SPICE_CODES, required=True),
        "origin_region": F("str", required=True),
        "crop_year": F("int", required=True),
        "quantity_kg": F("num", required=True),
        "flavor_intensity_units": F("num", required=True),
        "moisture_pct": F("num", required=True),
        "cost_per_kg_cents": F("int", required=True),
        "allergen_profile": F("enum", enum=ALLERGEN_PROFILES, required=True),
        "organic_certified": F("bool", default=False),
    })
    if data["quantity_kg"] <= 0:
        validation_error("quantity_kg must be > 0")
    if not (CROP_YEAR_MIN <= data["crop_year"] <= CROP_YEAR_MAX):
        validation_error("crop_year must be within %d..%d" % (CROP_YEAR_MIN, CROP_YEAR_MAX))
    if data["flavor_intensity_units"] <= 0:
        validation_error("flavor_intensity_units must be > 0")
    if not (D(0) <= data["moisture_pct"] <= D(100)):
        validation_error("moisture_pct must be within 0..100")
    if data["cost_per_kg_cents"] < 0:
        validation_error("cost_per_kg_cents must be >= 0")
    if data["supplier_id"] not in DB.suppliers:
        not_found("supplier not found")
    qty = q3(data["quantity_kg"])
    lot = new_entity({
        "supplier_id": data["supplier_id"],
        "spice_code": data["spice_code"],
        "origin_region": data["origin_region"],
        "crop_year": data["crop_year"],
        "quantity_kg": qty,
        "quantity_remaining_kg": qty,
        "quantity_consumed_kg": D(0),
        "quantity_wasted_kg": D(0),
        "flavor_intensity_units": data["flavor_intensity_units"],
        "moisture_pct": data["moisture_pct"],
        "cost_per_kg_cents": data["cost_per_kg_cents"],
        "allergen_profile": data["allergen_profile"],
        "organic_certified": data["organic_certified"],
        "status": "RECEIVED",
    })
    DB.lots[lot["id"]] = lot
    return respond(pub(lot), 201)


def _visible_lot_or_404(lot_id):
    lot = DB.lots.get(lot_id)
    if lot is None:
        not_found("lot not found")
    # Entity-backed ownership: another supplier's lot is invisible (404).
    if g.user_role == "SupplierRep" and lot["supplier_id"] != g.user_id:
        not_found("lot not found")
    return lot


@bp.get("/spice/lots/<lot_id>")
@require_roles(*LOT_READ_ROLES)
def get_lot(lot_id):
    return respond(pub(_visible_lot_or_404(lot_id)))


@bp.get("/spice/lots")
@require_roles(*LOT_READ_ROLES)
def list_lots():
    supplier_id = request.args.get("supplier_id")
    status = filter_enum("status", LOT_STATUSES)
    spice_code = filter_enum("spice_code", SPICE_CODES)
    crop_year = None
    raw_crop_year = request.args.get("crop_year")
    if raw_crop_year is not None:
        try:
            crop_year = int(raw_crop_year)
        except (ValueError, TypeError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "crop_year must be an integer")
    items = []
    for lot in DB.lots.values():
        if g.user_role == "SupplierRep" and lot["supplier_id"] != g.user_id:
            continue
        if supplier_id is not None and lot["supplier_id"] != supplier_id:
            continue
        if status is not None and lot["status"] != status:
            continue
        if spice_code is not None and lot["spice_code"] != spice_code:
            continue
        if crop_year is not None and lot["crop_year"] != crop_year:
            continue
        items.append(lot)
    data, meta = paged(items)
    return respond(data, page=meta)


# ---------------------------------------------------------------------------
# SafetyTest (append-only; only id + created_at, no updated_at/version)
# ---------------------------------------------------------------------------
def compute_result(test_type, measured):
    if test_type == "ADULTERANT_SCREEN":
        return "FAIL" if measured >= LEAD_LIMIT_PPM else "PASS"
    if test_type == "PESTICIDE":
        return "FAIL" if measured >= PESTICIDE_LIMIT_PPM else "PASS"
    if test_type == "MICRO":
        return "FAIL" if measured > MICRO_LIMIT_CFU_G else "PASS"
    if test_type == "MOISTURE":
        return "FAIL" if measured > MOISTURE_LIMIT_PCT else "PASS"
    return "PASS"


@bp.post("/spice/lots/<lot_id>/tests")
@require_roles("QualityAnalyst")
def post_test(lot_id):
    data = validate_body({
        "test_type": F("enum", enum=TEST_TYPES, required=True),
        "measured_value": F("num", required=True),
        "lab_code": F("str", required=True),
    })
    if data["measured_value"] < 0:
        validation_error("measured_value must be >= 0")
    lot = DB.lots.get(lot_id)
    if lot is None:
        not_found("lot not found")
    if lot["status"] in ("REJECTED", "DEPLETED"):
        raise ApiError("ERR_LOT_TERMINAL", 409,
                       "Cannot post tests on a %s lot" % lot["status"])
    result = compute_result(data["test_type"], data["measured_value"])
    test = {
        "id": str(uuid4()),
        "lot_id": lot["id"],
        "test_type": data["test_type"],
        "measured_value": data["measured_value"],
        "result": result,
        "lab_code": data["lab_code"],
        "analyst_user_id": g.user_id,
        "created_at": stamp(),
        "_seq": DB.seq,
    }
    DB.tests[test["id"]] = test
    changed = False
    if lot["status"] == "RECEIVED":
        lot["status"] = "IN_TEST"   # first test
        changed = True
    elif lot["status"] == "QUARANTINED":
        lot["status"] = "IN_TEST"   # retest
        changed = True
    if (data["test_type"] == "ADULTERANT_SCREEN" and result == "FAIL"
            and lot["status"] in ("IN_TEST", "ACCEPTED")):
        lot["status"] = "QUARANTINED"
        changed = True
        adulterant_cascade(lot, new_entity, touch)
    if changed:
        touch(lot)
    return respond(pub(test), 201)


@bp.get("/spice/lots/<lot_id>/tests")
@require_roles("QualityAnalyst", "QualityManager", "SupplyPlanner")
def list_tests(lot_id):
    lot = DB.lots.get(lot_id)
    if lot is None:
        not_found("lot not found")
    items = [t for t in DB.tests.values() if t["lot_id"] == lot["id"]]
    data, meta = paged(items)
    return respond(data, page=meta)


# ---------------------------------------------------------------------------
# Disposition (segregation of duties + ACCEPT gates)
# ---------------------------------------------------------------------------
@bp.post("/spice/lots/<lot_id>/disposition")
@require_roles("QualityManager")
def disposition(lot_id):
    data = validate_body({
        "action": F("enum", enum=["ACCEPT", "QUARANTINE", "REJECT"], required=True),
        "reason": F("str", nullable=True, default=None),
    })
    lot = DB.lots.get(lot_id)
    if lot is None:
        not_found("lot not found")
    if lot["status"] in ("REJECTED", "DEPLETED"):
        raise ApiError("ERR_LOT_TERMINAL", 409,
                       "Cannot disposition a %s lot" % lot["status"])
    action = data["action"]
    legal_from = {
        "ACCEPT": ("IN_TEST", "QUARANTINED"),
        "QUARANTINE": ("IN_TEST",),
        "REJECT": ("IN_TEST", "QUARANTINED"),
    }
    if lot["status"] not in legal_from[action]:
        invalid_state("Lot in status %s does not allow %s" % (lot["status"], action))
    tests = sorted((t for t in DB.tests.values() if t["lot_id"] == lot["id"]),
                   key=lambda t: t["_seq"])
    # Segregation of duties: the analyst who posted any test may not disposition.
    if any(t["analyst_user_id"] == g.user_id for t in tests):
        raise ApiError("ERR_DISPOSITION_FORBIDDEN", 403,
                       "Segregation of duties: caller posted a safety test on this lot")
    if action == "ACCEPT":
        latest = {}
        for t in tests:
            latest[t["test_type"]] = t   # tests are in created_at order
        if any(t["result"] == "FAIL" for t in latest.values()):
            raise ApiError("ERR_LOT_HAS_FAILING_TEST", 409,
                           "The latest test of a type on this lot is FAIL")
        passed = {t["test_type"] for t in tests if t["result"] == "PASS"}
        if not set(REQUIRED_TEST_SUITE).issubset(passed):
            raise ApiError("ERR_TEST_SUITE_INCOMPLETE", 409,
                           "Required test suite (MICRO, ADULTERANT_SCREEN, MOISTURE) incomplete")
        lot["status"] = "ACCEPTED"
        touch(lot)
        # PRD 3.2/3.7: releasing a lot from quarantine via accept unwinds the
        # adulterant cascade. An exonerating retest moves QUARANTINED ->
        # IN_TEST before the release accept (and the zero-FAIL gate makes that
        # the only reachable release path after an adulterant FAIL), so the
        # unwind is keyed to the cascade artifacts — batch holds naming this
        # lot and DRAFT AUTO_QUARANTINE recall cases — and is a no-op for a
        # lot that was never cascade-quarantined.
        release_cascade(lot, touch)
    elif action == "QUARANTINE":
        lot["status"] = "QUARANTINED"
        touch(lot)
    else:  # REJECT — mass invariant INV-1
        lot["quantity_wasted_kg"] += lot["quantity_remaining_kg"]
        lot["quantity_remaining_kg"] = D(0)
        lot["status"] = "REJECTED"
        touch(lot)
    return respond(pub(lot))
