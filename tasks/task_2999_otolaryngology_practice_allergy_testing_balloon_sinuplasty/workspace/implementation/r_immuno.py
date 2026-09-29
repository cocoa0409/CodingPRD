"""Immunotherapy compounding, verification, dosing and escalation (PRD 3.5)."""
from decimal import Decimal

from flask import Blueprint

import calc
import common
import envelope
import shape
import store
from errors import ApiError

bp = Blueprint("immuno", __name__)


def _expires_date_part(expires_at):
    return expires_at.strip()[0:10]


def _vial_of(dose):
    return store.db["immunotherapy_vials"][dose["immunotherapy_vial_id"]]


def _settle_vial(vial):
    """Refresh the four volume buckets and apply the volume-driven arcs."""
    remaining = calc.refresh_vial_ledger(vial)
    if vial["status"] == "IN_USE" and remaining < calc.MIN_DOSE_ML:
        vial["status"] = "EXHAUSTED"
    elif vial["status"] == "EXHAUSTED" and remaining >= calc.MIN_DOSE_ML:
        vial["status"] = "IN_USE"
    return remaining


# --- vials -------------------------------------------------------------------
@bp.post("/immunotherapy-vials")
def compound_vial():
    ctx = common.begin(["AllergyNurse"])
    values, _provided = shape.read_body([
        ("patient_id", True, shape.v_ref(), False),
        ("supply_lot_id", True, shape.v_ref(), False),
        ("dilution_code", True, shape.v_enum(calc.DILUTION_CODES), False),
        ("label_text", True, shape.v_string(1, 120), False),
        ("expires_at", True, shape.v_instant(), False),
        ("volume_ml_initial", False, shape.v_number(1, 10, 2), False),
        ("expected_patient_version", True, shape.v_int(), False),
    ])
    expires_at = store.parse_instant(values["expires_at"])
    now = store.now()
    if expires_at <= now:
        shape.bad("expires_at must fall strictly after the current logical clock")
    if expires_at > store.plus_days(now, 365):
        shape.bad("expires_at may not fall more than 365 days after the clock")

    patient = common.find_ref("patients", values["patient_id"])
    expected_label = "%s|%s|%s" % (
        patient["mrn"], values["dilution_code"],
        _expires_date_part(values["expires_at"]),
    )
    if values["label_text"] != expected_label:
        shape.bad("label_text must be composed as mrn|dilution_code|expiry date")

    lot = common.find_ref("supply_lots", values["supply_lot_id"])
    # rung 6
    if values["expected_patient_version"] != patient["version"]:
        raise ApiError("ERR_STALE_PATIENT_VERSION")
    # rung 7
    if lot["status"] == "QUARANTINED":
        raise ApiError("ERR_LOT_STATE_INVALID")
    # rung 12
    if lot["item_type"] != "ALLERGEN_CONCENTRATE":
        raise ApiError("ERR_LOT_ITEM_TYPE_MISMATCH")

    initial = calc.dec(values.get("volume_ml_initial", "5.00"))
    vial = common.new_row("immunotherapy_vials", {
        "patient_id": patient["id"],
        "supply_lot_id": lot["id"],
        "dilution_code": values["dilution_code"],
        "label_text": values["label_text"],
        "volume_ml_initial": calc.vol_out(initial),
        "volume_ml_remaining": calc.vol_out(initial),
        "volume_ml_dispensed_total": calc.vol_out(Decimal("0.00")),
        "volume_ml_wasted": calc.vol_out(Decimal("0.00")),
        "expires_at": values["expires_at"],
        "status": "MIXED",
        "mixed_by_user_id": ctx.user_id,
        "verified_by_user_id": None,
        "requires_supervised_administration": False,
        "discard_reason": None,
    })

    # supersession cascade
    for older in common.sorted_rows(
            "immunotherapy_vials",
            lambda r: r["patient_id"] == patient["id"] and r["id"] != vial["id"]
            and r["status"] in ("LABEL_VERIFIED", "IN_USE")):
        older["volume_ml_wasted"] = calc.vol_out(
            calc.dec(older["volume_ml_wasted"]) + calc.dec(older["volume_ml_remaining"])
        )
        older["status"] = "DISCARDED"
        older["discard_reason"] = "SUPERSEDED"
        calc.refresh_vial_ledger(older)
        common.touch(older)

    common.touch(patient)
    return envelope.created(common.public("immunotherapy_vials", vial))


@bp.get("/immunotherapy-vials/<vial_id>")
def read_vial(vial_id):
    common.begin(shape.ALL_ROLES)
    shape.read_query({})
    shape.no_body()
    row = common.find("immunotherapy_vials", vial_id)
    return envelope.ok(common.public("immunotherapy_vials", row))


@bp.get("/immunotherapy-vials")
def list_vials():
    common.begin(shape.ALL_ROLES)
    filters = shape.read_query({
        "patient_id": shape.q_string(),
        "supply_lot_id": shape.q_string(),
        "status": shape.q_enum(calc.VIAL_STATUSES),
        "dilution_code": shape.q_enum(calc.DILUTION_CODES),
    })
    limit, offset = shape.pagination()
    shape.no_body()
    items = common.sorted_rows("immunotherapy_vials",
                              lambda r: common.matches(r, filters))
    page = common.paginate(items, limit, offset)
    return envelope.listing(
        [common.public("immunotherapy_vials", r) for r in page],
        limit, offset, len(items),
    )


@bp.post("/immunotherapy-vials/<vial_id>/label-verification")
def verify_vial(vial_id):
    ctx = common.begin(["AllergyNurse"])
    values, _provided = shape.read_body([
        ("label_text_confirmation", True, shape.v_string(1, 120), False),
    ])
    vial = common.find("immunotherapy_vials", vial_id)
    if vial["status"] != "MIXED":
        raise ApiError("ERR_VIAL_STATE_INVALID")
    if ctx.user_id == vial["mixed_by_user_id"]:
        raise ApiError("ERR_SELF_VERIFICATION_FORBIDDEN")
    if values["label_text_confirmation"] != vial["label_text"]:
        raise ApiError("ERR_VIAL_LABEL_MISMATCH")
    if store.now() >= store.parse_instant(vial["expires_at"]):
        raise ApiError("ERR_VIAL_EXPIRED")

    vial["status"] = "LABEL_VERIFIED"
    vial["verified_by_user_id"] = ctx.user_id
    common.touch(vial)
    patient = store.db["patients"][vial["patient_id"]]
    patient["immunotherapy_status"] = common.derive_immunotherapy_status(
        patient["immunotherapy_escalation_step"]
    )
    common.touch(patient)
    return envelope.ok(common.public("immunotherapy_vials", vial))


@bp.post("/immunotherapy-vials/<vial_id>/discard")
def discard_vial(vial_id):
    common.begin(["AllergyNurse"])
    values, _provided = shape.read_body([
        ("discard_reason", True, shape.v_enum(calc.DISCARD_REASONS_INPUT), False),
    ])
    vial = common.find("immunotherapy_vials", vial_id)
    if vial["status"] not in ("MIXED", "LABEL_VERIFIED", "IN_USE"):
        raise ApiError("ERR_VIAL_STATE_INVALID")
    vial["volume_ml_wasted"] = calc.vol_out(
        calc.dec(vial["volume_ml_wasted"]) + calc.dec(vial["volume_ml_remaining"])
    )
    vial["status"] = "DISCARDED"
    vial["discard_reason"] = values["discard_reason"]
    calc.refresh_vial_ledger(vial)
    common.touch(vial)
    return envelope.ok(common.public("immunotherapy_vials", vial))


# --- doses -------------------------------------------------------------------
@bp.post("/immunotherapy-doses")
def administer_dose():
    ctx = common.begin(["AllergyNurse"])
    values, _provided = shape.read_body([
        ("immunotherapy_vial_id", True, shape.v_ref(), False),
        ("supervising_user_id", False, shape.v_string(1, 120), True),
    ])
    vial = common.find_ref("immunotherapy_vials", values["immunotherapy_vial_id"])
    patient = store.db["patients"][vial["patient_id"]]
    # rung 7
    if vial["status"] not in ("LABEL_VERIFIED", "IN_USE"):
        raise ApiError("ERR_VIAL_STATE_INVALID")
    # rung 10, in the order PRD 3.5 states the gates
    if store.now() >= store.parse_instant(vial["expires_at"]):
        raise ApiError("ERR_VIAL_EXPIRED")
    if (patient["risk_score"] >= calc.RISK_OBSERVATION_THRESHOLD
            and not patient["epinephrine_on_file"]):
        raise ApiError("ERR_EPINEPHRINE_NOT_ON_FILE")
    plan = calc.next_dose_plan(patient)
    if vial["dilution_code"] != plan["required_dilution"]:
        raise ApiError("ERR_DILUTION_MISMATCH")
    supervisor = values.get("supervising_user_id")
    if vial["requires_supervised_administration"] and not supervisor:
        raise ApiError("ERR_SUPERVISION_REQUIRED")
    # rung 14
    remaining = calc.refresh_vial_ledger(vial)
    if remaining < plan["volume"]:
        raise ApiError("ERR_INSUFFICIENT_VIAL_VOLUME")

    policy = common.policy_of_patient(patient)
    administered_at = store.iso(store.now())
    dose = common.new_row("immunotherapy_doses", {
        "immunotherapy_vial_id": vial["id"],
        "escalation_step_at_dose": plan["effective_step"],
        "volume_ml": calc.vol_out(plan["volume"]),
        "observation_required_minutes": calc.observation_minutes(
            patient, policy, "IMMUNO_DOSE", plan["effective_step"]
        ),
        "administered_at": administered_at,
        "administered_by_user_id": ctx.user_id,
        "supervising_user_id": supervisor,
        "observation_cleared_at": None,
        "status": "ADMINISTERED",
        "reaction_grade": 0,
        "gap_days_at_dose": plan["gap_days"],
    })

    if vial["status"] == "LABEL_VERIFIED":
        vial["status"] = "IN_USE"
    _settle_vial(vial)
    common.touch(vial)
    patient["last_dose_administered_at"] = administered_at
    common.touch(patient)
    return envelope.created(common.public("immunotherapy_doses", dose))


@bp.get("/immunotherapy-doses/<dose_id>")
def read_dose(dose_id):
    common.begin(shape.ALL_ROLES)
    shape.read_query({})
    shape.no_body()
    row = common.find("immunotherapy_doses", dose_id)
    return envelope.ok(common.public("immunotherapy_doses", row))


@bp.get("/immunotherapy-doses")
def list_doses():
    common.begin(shape.ALL_ROLES)
    filters = shape.read_query({
        "immunotherapy_vial_id": shape.q_string(),
        "patient_id": shape.q_string(),
        "status": shape.q_enum(calc.DOSE_STATUSES),
    })
    limit, offset = shape.pagination()
    shape.no_body()
    patient_id = filters.pop("patient_id", None)

    def keep(row):
        if not common.matches(row, filters):
            return False
        if patient_id is not None:
            vial = store.db["immunotherapy_vials"].get(row["immunotherapy_vial_id"])
            if vial is None or vial["patient_id"] != patient_id:
                return False
        return True

    items = common.sorted_rows("immunotherapy_doses", keep)
    page = common.paginate(items, limit, offset)
    return envelope.listing(
        [common.public("immunotherapy_doses", r) for r in page],
        limit, offset, len(items),
    )


@bp.post("/immunotherapy-doses/<dose_id>/clear-observation")
def clear_observation(dose_id):
    common.begin(["AllergyNurse"])
    shape.no_body()
    dose = common.find("immunotherapy_doses", dose_id)
    if dose["status"] != "ADMINISTERED" or dose["observation_cleared_at"] is not None:
        raise ApiError("ERR_DOSE_STATE_INVALID")
    if dose["reaction_grade"] > 1:
        raise ApiError("ERR_DOSE_STATE_INVALID")
    elapsed = store.whole_minutes_between(
        store.parse_instant(dose["administered_at"]), store.now()
    )
    if elapsed < dose["observation_required_minutes"]:
        raise ApiError("ERR_OBSERVATION_NOT_COMPLETE")

    dose["status"] = "CLEARED"
    dose["observation_cleared_at"] = store.iso(store.now())
    common.touch(dose)

    patient = common.patient_of_dose(dose)
    patient["immunotherapy_escalation_step"] = min(
        12, dose["escalation_step_at_dose"] + 1
    )
    patient["immunotherapy_status"] = common.derive_immunotherapy_status(
        patient["immunotherapy_escalation_step"]
    )
    common.touch(patient)

    vial = _vial_of(dose)
    before = vial["status"]
    _settle_vial(vial)
    if vial["status"] != before:
        common.touch(vial)
    return envelope.ok(common.public("immunotherapy_doses", dose))


@bp.post("/immunotherapy-doses/<dose_id>/void")
def void_dose(dose_id):
    common.begin(["AllergyNurse"])
    _values, _provided = shape.read_body([
        ("void_reason", True, shape.v_enum(calc.VOID_REASONS), False),
    ])
    dose = common.find("immunotherapy_doses", dose_id)
    if dose["status"] != "ADMINISTERED" or dose["observation_cleared_at"] is not None:
        raise ApiError("ERR_DOSE_STATE_INVALID")
    elapsed = store.whole_minutes_between(
        store.parse_instant(dose["administered_at"]), store.now()
    )
    if elapsed > calc.VOID_WINDOW_MINUTES:
        raise ApiError("ERR_VOID_WINDOW_CLOSED")

    dose["status"] = "VOIDED"
    common.touch(dose)

    vial = _vial_of(dose)
    _settle_vial(vial)
    common.touch(vial)

    patient = common.patient_of_dose(dose)
    vial_ids = set(v["id"] for v in store.rows("immunotherapy_vials")
                   if v["patient_id"] == patient["id"])
    live = [d for d in store.rows("immunotherapy_doses")
            if d["immunotherapy_vial_id"] in vial_ids
            and d["status"] in calc.DISPENSING_DOSES]
    if live:
        live.sort(key=lambda d: (d["administered_at"], d["created_at"], d["_seq"]))
        patient["last_dose_administered_at"] = live[-1]["administered_at"]
    else:
        patient["last_dose_administered_at"] = None
    common.touch(patient)
    return envelope.ok(common.public("immunotherapy_doses", dose))
