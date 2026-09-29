"""Diagnostic studies and the device trial economy (PRD 3.7)."""
from flask import Blueprint

import calc
import common
import envelope
import shape
import store
from errors import ApiError

bp = Blueprint("audiology", __name__)

DEVICE_SERIAL_RE = r"^[A-Z]{2}[0-9]{6}$"
AUDIOMETRY_METRICS = ("pta_db_hl", "word_recognition_pct")
SLEEP_METRICS = ("ahi",)


def _lot_blocked(lot):
    if lot["status"] == "QUARANTINED":
        return True
    expires = store.parse_instant(lot["expires_at"])
    return expires is not None and store.now() >= expires


# --- diagnostic studies ------------------------------------------------------
@bp.post("/diagnostic-studies")
def create_study():
    common.begin(["Otolaryngologist"])
    values, _provided = shape.read_body([
        ("patient_id", True, shape.v_ref(), False),
        ("study_type", True, shape.v_enum(calc.STUDY_TYPES), False),
    ])
    patient = common.find_ref("patients", values["patient_id"])
    row = common.new_row("diagnostic_studies", {
        "patient_id": patient["id"],
        "study_type": values["study_type"],
        "status": "ORDERED",
        "pta_db_hl": None,
        "word_recognition_pct": None,
        "ahi": None,
        "recommendation": None,
        "performed_at": None,
        "performed_by_user_id": None,
        "interpreted_by_user_id": None,
        "superseded_dispense_count": 0,
    })
    return envelope.created(common.public("diagnostic_studies", row))


@bp.get("/diagnostic-studies/<study_id>")
def read_study(study_id):
    common.begin(shape.ALL_ROLES)
    shape.read_query({})
    shape.no_body()
    row = common.find("diagnostic_studies", study_id)
    return envelope.ok(common.public("diagnostic_studies", row))


@bp.get("/diagnostic-studies")
def list_studies():
    common.begin(shape.ALL_ROLES)
    filters = shape.read_query({
        "patient_id": shape.q_string(),
        "study_type": shape.q_enum(calc.STUDY_TYPES),
        "status": shape.q_enum(calc.STUDY_STATUSES),
        "recommendation": shape.q_enum(calc.RECOMMENDATIONS),
    })
    limit, offset = shape.pagination()
    shape.no_body()
    items = common.sorted_rows("diagnostic_studies",
                               lambda r: common.matches(r, filters))
    page = common.paginate(items, limit, offset)
    return envelope.listing(
        [common.public("diagnostic_studies", r) for r in page],
        limit, offset, len(items),
    )


@bp.post("/diagnostic-studies/<study_id>/results")
def record_results(study_id):
    ctx = common.begin(["Audiologist"])
    values, provided = shape.read_body([
        ("pta_db_hl", False, shape.v_number(0, 120, 1), False),
        ("word_recognition_pct", False, shape.v_number(0, 100, 1), False),
        ("ahi", False, shape.v_number(0, 120, 1), False),
    ])
    study = common.find("diagnostic_studies", study_id)
    # PRD 3.7: the metric set is fixed by study_type and is a rung-3 failure
    if study["study_type"] == "AUDIOMETRY":
        required, forbidden = AUDIOMETRY_METRICS, SLEEP_METRICS
    else:
        required, forbidden = SLEEP_METRICS, AUDIOMETRY_METRICS
    for name in required:
        if name not in provided:
            shape.bad("%s is required for a %s study" % (name, study["study_type"]))
    for name in forbidden:
        if name in provided:
            shape.bad("%s is not accepted for a %s study" % (name, study["study_type"]))

    if study["status"] != "ORDERED":
        raise ApiError("ERR_STUDY_STATE_INVALID")

    for name in required:
        study[name] = values[name]
    study["status"] = "PERFORMED"
    study["performed_at"] = store.iso(store.now())
    study["performed_by_user_id"] = ctx.user_id
    common.touch(study)
    return envelope.ok(common.public("diagnostic_studies", study))


@bp.post("/diagnostic-studies/<study_id>/interpretation")
def interpret_study(study_id):
    ctx = common.begin(["Otolaryngologist", "Audiologist"])
    shape.no_body()
    study = common.find("diagnostic_studies", study_id)
    if study["status"] != "PERFORMED":
        raise ApiError("ERR_STUDY_STATE_INVALID")
    if ctx.user_id == study["performed_by_user_id"]:
        raise ApiError("ERR_SELF_INTERPRETATION_FORBIDDEN")
    study["status"] = "INTERPRETED"
    study["interpreted_by_user_id"] = ctx.user_id
    study["recommendation"] = calc.study_recommendation(study)
    common.touch(study)
    return envelope.ok(common.public("diagnostic_studies", study))


# --- device dispenses --------------------------------------------------------
@bp.post("/device-dispenses")
def create_dispense():
    ctx = common.begin(["Audiologist"])
    values, _provided = shape.read_body([
        ("diagnostic_study_id", True, shape.v_ref(), False),
        ("supply_lot_id", True, shape.v_ref(), False),
        ("device_type", True, shape.v_enum(calc.DEVICE_TYPES), False),
        ("device_serial", True, shape.v_string(8, 8, DEVICE_SERIAL_RE), False),
        ("ear", True, shape.v_enum(calc.EARS), False),
        ("price_cents", True, shape.v_int(1, 2000000), False),
        ("expected_study_version", True, shape.v_int(), False),
    ])
    study = common.find_ref("diagnostic_studies", values["diagnostic_study_id"])
    lot = common.find_ref("supply_lots", values["supply_lot_id"])
    # rung 6
    if values["expected_study_version"] != study["version"]:
        raise ApiError("ERR_STALE_STUDY_VERSION")
    # rung 7
    if study["status"] != "INTERPRETED":
        raise ApiError("ERR_STUDY_STATE_INVALID")
    if _lot_blocked(lot):
        raise ApiError("ERR_LOT_STATE_INVALID")
    # rung 8
    for row in store.rows("device_dispenses"):
        if row["device_serial"] == values["device_serial"]:
            raise ApiError("ERR_DUPLICATE_DEVICE_SERIAL")
    # rung 12
    if calc.RECOMMENDED_DEVICE.get(study["recommendation"]) != values["device_type"]:
        raise ApiError("ERR_DEVICE_TYPE_NOT_RECOMMENDED")
    if lot["item_type"] != values["device_type"]:
        raise ApiError("ERR_LOT_ITEM_TYPE_MISMATCH")
    # rung 13
    patient = store.db["patients"][study["patient_id"]]
    policy = common.policy_of_patient(patient)
    if values["device_type"] == "ORAL_APPLIANCE" and not policy["appliance_covered"]:
        raise ApiError("ERR_APPLIANCE_NOT_COVERED")
    # rung 14
    if calc.lot_available(lot) < 1:
        raise ApiError("ERR_SUPPLY_EXHAUSTED")

    earlier = [d for d in store.rows("device_dispenses")
               if d["diagnostic_study_id"] == study["id"]]
    dispensed_at = store.iso(store.now())
    row = common.new_row("device_dispenses", {
        "diagnostic_study_id": study["id"],
        "supply_lot_id": lot["id"],
        "device_type": values["device_type"],
        "device_serial": values["device_serial"],
        "ear": values["ear"],
        "price_cents": values["price_cents"],
        "dispensed_at": dispensed_at,
        "trial_end_at": store.iso(
            store.plus_days(store.now(), policy["device_trial_days"])
        ),
        "fit_status": "FITTED",
        "billing_status": "INVOICED",
        "adjustment_count": 0,
        "days_used": 0,
        "refund_variant": None,
        "restock_fee_cents": 0,
        "refund_cents": 0,
        "dispensed_by_user_id": ctx.user_id,
        "settled_by_user_id": None,
    })

    lot["quantity_on_hand"] = lot["quantity_on_hand"] - 1
    lot["quantity_consumed"] = lot["quantity_consumed"] + 1
    common.lot_exhaustion_check(lot)
    common.touch(lot)

    if earlier:
        study["superseded_dispense_count"] = study["superseded_dispense_count"] + 1
    common.touch(study)
    return envelope.created(common.public("device_dispenses", row))


@bp.get("/device-dispenses/<dispense_id>")
def read_dispense(dispense_id):
    common.begin(shape.ALL_ROLES)
    shape.read_query({})
    shape.no_body()
    row = common.find("device_dispenses", dispense_id)
    return envelope.ok(common.public("device_dispenses", row))


@bp.get("/device-dispenses")
def list_dispenses():
    common.begin(shape.ALL_ROLES)
    filters = shape.read_query({
        "diagnostic_study_id": shape.q_string(),
        "supply_lot_id": shape.q_string(),
        "fit_status": shape.q_enum(calc.FIT_STATUSES),
        "billing_status": shape.q_enum(calc.BILLING_STATUSES),
    })
    limit, offset = shape.pagination()
    shape.no_body()
    items = common.sorted_rows("device_dispenses",
                               lambda r: common.matches(r, filters))
    page = common.paginate(items, limit, offset)
    return envelope.listing(
        [common.public("device_dispenses", r) for r in page],
        limit, offset, len(items),
    )


@bp.post("/device-dispenses/<dispense_id>/adjustments")
def adjust_dispense(dispense_id):
    common.begin(["Audiologist"])
    _values, _provided = shape.read_body([
        ("adjustment_note", False, shape.v_string(1, 200), False),
    ])
    row = common.find("device_dispenses", dispense_id)
    if row["fit_status"] not in ("FITTED", "ADJUSTED"):
        raise ApiError("ERR_DISPENSE_STATE_INVALID")
    if store.now() >= store.parse_instant(row["trial_end_at"]):
        raise ApiError("ERR_DISPENSE_STATE_INVALID")
    if row["adjustment_count"] >= 3:
        raise ApiError("ERR_ADJUSTMENT_LIMIT_REACHED")
    row["fit_status"] = "ADJUSTED"
    row["adjustment_count"] = row["adjustment_count"] + 1
    common.touch(row)
    return envelope.ok(common.public("device_dispenses", row))


@bp.post("/device-dispenses/<dispense_id>/trial-return")
def return_dispense(dispense_id):
    common.begin(["Audiologist"])
    _values, _provided = shape.read_body([
        ("return_reason", True, shape.v_enum(calc.RETURN_REASONS), False),
    ])
    row = common.find("device_dispenses", dispense_id)
    if (row["fit_status"] not in ("FITTED", "ADJUSTED")
            or row["billing_status"] != "INVOICED"):
        raise ApiError("ERR_DISPENSE_STATE_INVALID")
    study = store.db["diagnostic_studies"][row["diagnostic_study_id"]]
    patient = store.db["patients"][study["patient_id"]]
    policy = common.policy_of_patient(patient)
    result = calc.trial_refund(row, policy)
    row["fit_status"] = "RETURNED"
    row["days_used"] = result["days_used"]
    row["refund_variant"] = result["refund_variant"]
    row["restock_fee_cents"] = result["restock_fee_cents"]
    row["refund_cents"] = result["refund_cents"]
    row["billing_status"] = result["billing_status"]
    common.touch(row)
    return envelope.ok(common.public("device_dispenses", row))


@bp.post("/device-dispenses/<dispense_id>/finalize")
def finalize_dispense(dispense_id):
    common.begin(["Audiologist"])
    shape.no_body()
    row = common.find("device_dispenses", dispense_id)
    if (row["fit_status"] not in ("FITTED", "ADJUSTED")
            or row["billing_status"] != "INVOICED"):
        raise ApiError("ERR_DISPENSE_STATE_INVALID")
    if store.now() < store.parse_instant(row["trial_end_at"]):
        raise ApiError("ERR_TRIAL_NOT_COMPLETE")
    row["fit_status"] = "FINALIZED"
    row["billing_status"] = "RETAINED"
    common.touch(row)
    return envelope.ok(common.public("device_dispenses", row))


@bp.post("/device-dispenses/<dispense_id>/refund-settlement")
def settle_refund(dispense_id):
    ctx = common.begin(["PracticeAdmin"])
    shape.no_body()
    row = common.find("device_dispenses", dispense_id)
    if row["billing_status"] != "REFUND_PENDING":
        raise ApiError("ERR_DISPENSE_STATE_INVALID")
    if ctx.user_id == row["dispensed_by_user_id"]:
        raise ApiError("ERR_SELF_SETTLEMENT_FORBIDDEN")
    row["billing_status"] = "REFUNDED"
    row["settled_by_user_id"] = ctx.user_id
    common.touch(row)

    lot = store.db["supply_lots"].get(row["supply_lot_id"])
    if lot is not None:
        lot["quantity_consumed"] = lot["quantity_consumed"] - 1
        lot["quantity_wasted"] = lot["quantity_wasted"] + 1
        calc.refresh_lot(lot)
        common.touch(lot)
    return envelope.ok(common.public("device_dispenses", row))
