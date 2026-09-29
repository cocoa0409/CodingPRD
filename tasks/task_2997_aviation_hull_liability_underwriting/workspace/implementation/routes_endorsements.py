"""Mid-term endorsements: submission, the negotiation cycle, binding and voiding."""

from flask import Blueprint, g, request

import auth
import calc
import constants as C
import derive
import envelope
import serialize
import services
import util
import validate as V
from errors import ApiError
from store import db, new_record, ordered, touch

bp = Blueprint("endorsements", __name__)

ALL = C.ALL_ROLES
OPEN_WRITE = ["Underwriter", "Broker"]

TARGETED_TYPES = ("VALUE_REVISION", "USE_CLASS_CHANGE", "REMOVE_AIRCRAFT")


def _conditional(message):
    return ApiError("ERR_CONDITIONAL_FIELD_REQUIRED", message)


def _check_conditional_payload(endorsement_type, target_schedule_id, aircraft_id, named_pilot_id,
                              new_agreed_value_cents, new_use_class, territory_code,
                              exposure_member_count, per_seat_limit_cents):
    """PRD 3.6: the discriminated payload rules are strict in both directions."""
    if endorsement_type in TARGETED_TYPES:
        if target_schedule_id is None:
            raise _conditional("target_schedule_id is mandatory for %s." % endorsement_type)
    elif target_schedule_id is not None:
        raise _conditional("target_schedule_id must be null for %s." % endorsement_type)

    if endorsement_type == "ADD_AIRCRAFT":
        for name, value in (("aircraft_id", aircraft_id), ("named_pilot_id", named_pilot_id),
                            ("new_agreed_value_cents", new_agreed_value_cents),
                            ("new_use_class", new_use_class)):
            if value is None:
                raise _conditional("%s is mandatory for ADD_AIRCRAFT." % name)
    else:
        if aircraft_id is not None:
            raise _conditional("aircraft_id must be null for %s." % endorsement_type)
        if named_pilot_id is not None:
            raise _conditional("named_pilot_id must be null for %s." % endorsement_type)

    if endorsement_type == "VALUE_REVISION" and new_agreed_value_cents is None:
        raise _conditional("new_agreed_value_cents is mandatory for VALUE_REVISION.")
    if (endorsement_type not in ("ADD_AIRCRAFT", "VALUE_REVISION")
            and new_agreed_value_cents is not None):
        raise _conditional("new_agreed_value_cents must be null for %s." % endorsement_type)

    if endorsement_type == "USE_CLASS_CHANGE" and new_use_class is None:
        raise _conditional("new_use_class is mandatory for USE_CLASS_CHANGE.")
    if endorsement_type not in ("ADD_AIRCRAFT", "USE_CLASS_CHANGE") and new_use_class is not None:
        raise _conditional("new_use_class must be null for %s." % endorsement_type)

    if endorsement_type == "TERRITORY_EXTENSION":
        if territory_code is None:
            raise _conditional("territory_code is mandatory for TERRITORY_EXTENSION.")
    elif territory_code is not None:
        raise _conditional("territory_code must be null for %s." % endorsement_type)

    if endorsement_type in C.EXPOSURE_TYPES:
        if exposure_member_count is None:
            raise _conditional("exposure_member_count is mandatory for %s." % endorsement_type)
        if per_seat_limit_cents is None:
            raise _conditional("per_seat_limit_cents is mandatory for %s." % endorsement_type)
    else:
        if exposure_member_count is not None:
            raise _conditional("exposure_member_count must be null for %s." % endorsement_type)
        if per_seat_limit_cents is not None:
            raise _conditional("per_seat_limit_cents must be null for %s." % endorsement_type)


@bp.route("/aviation/endorsements", methods=["POST"])
@auth.endpoint(OPEN_WRITE)
def create_endorsement():
    body = V.json_body()
    policy = services.resolve_fk(body, "policy_id", services.get_policy)
    services.scope_policy(policy)
    aircraft = services.optional_fk(body, "aircraft_id", services.get_aircraft)
    pilot = services.optional_fk(body, "named_pilot_id", services.get_pilot)
    target = services.optional_fk(body, "target_schedule_id", services.get_schedule)

    endorsement_type = V.get_str(body, "endorsement_type")
    effective_date = V.get_instant(body, "effective_date")
    new_agreed_value_cents = V.get_int(body, "new_agreed_value_cents", required=False)
    new_use_class = V.get_str(body, "new_use_class", required=False)
    territory_code = V.get_str(body, "territory_code", required=False)
    exposure_member_count = V.get_int(body, "exposure_member_count", required=False)
    per_seat_limit_cents = V.get_int(body, "per_seat_limit_cents", required=False)

    V.check_enum(endorsement_type, "endorsement_type", C.ENDORSEMENT_TYPES)
    V.check_enum(new_use_class, "new_use_class", C.USE_CLASSES)
    V.check_enum(territory_code, "territory_code", C.TERRITORY_CODES)
    V.check_range(new_agreed_value_cents, "new_agreed_value_cents", 1)
    V.check_range(exposure_member_count, "exposure_member_count", 1, 500)
    V.check_range(per_seat_limit_cents, "per_seat_limit_cents", 1)

    _check_conditional_payload(
        endorsement_type,
        target["id"] if target else None,
        aircraft["id"] if aircraft else None,
        pilot["id"] if pilot else None,
        new_agreed_value_cents, new_use_class, territory_code,
        exposure_member_count, per_seat_limit_cents)

    if policy["status"] != "BOUND":
        raise ApiError("ERR_POLICY_NOT_BOUND")

    if endorsement_type in ("ADD_AIRCRAFT", "USE_CLASS_CHANGE"):
        operator = db.operators[policy["operator_id"]]
        services.check_use_class(policy, operator, new_use_class)

    if not (policy["effective_from"] <= effective_date < policy["effective_to"]):
        raise ApiError("ERR_EFFECTIVE_DATE_OUT_OF_TERM")

    if target is not None and target["policy_id"] != policy["id"]:
        raise ApiError("ERR_SCHEDULE_POLICY_MISMATCH")

    if endorsement_type == "ADD_AIRCRAFT":
        services.check_over_insurance(aircraft, effective_date.year, new_agreed_value_cents)
    elif endorsement_type == "VALUE_REVISION":
        target_aircraft = db.aircraft[target["aircraft_id"]]
        services.check_over_insurance(target_aircraft, target["effective_from"].year,
                                      new_agreed_value_cents)

    rec = new_record(db.endorsements, {
        "policy_id": policy["id"],
        "endorsement_type": endorsement_type,
        "status": "SUBMITTED",
        "effective_date": effective_date,
        "target_schedule_id": target["id"] if target else None,
        "aircraft_id": aircraft["id"] if aircraft else None,
        "named_pilot_id": pilot["id"] if pilot else None,
        "new_agreed_value_cents": new_agreed_value_cents,
        "new_use_class": new_use_class,
        "territory_code": territory_code,
        "exposure_member_count": exposure_member_count,
        "per_seat_limit_cents": per_seat_limit_cents,
        "quote_round": 0,
        "quoted_premium_delta_cents": None,
        "premium_delta_cents": None,
        "quoted_by_user_id": None,
        "referral_reason": None,
        "void_reason": None,
        "_prebind": None,
    })
    return envelope.ok(serialize.endorsement(rec), 201)


@bp.route("/aviation/endorsements", methods=["GET"])
@auth.endpoint(ALL)
def list_endorsements():
    limit, offset = V.pagination()
    rows = ordered(db.endorsements)
    visible = services.visible_policy_ids()
    if visible is not None:
        rows = [r for r in rows if r["policy_id"] in visible]
    rows = V.filter_eq(rows, "policy_id", request.args.get("policy_id"))
    rows = V.filter_eq(rows, "target_schedule_id", request.args.get("target_schedule_id"))
    rows = V.filter_eq(rows, "aircraft_id", request.args.get("aircraft_id"))
    rows = V.filter_eq(rows, "named_pilot_id", request.args.get("named_pilot_id"))
    rows = V.filter_eq(rows, "status", request.args.get("status"))
    rows = V.filter_eq(rows, "endorsement_type", request.args.get("endorsement_type"))
    total = len(rows)
    window = V.page(rows, limit, offset)
    return envelope.ok_list(serialize.many(serialize.endorsement, window), limit, offset, total)


@bp.route("/aviation/endorsements/<row_id>", methods=["GET"])
@auth.endpoint(ALL)
def read_endorsement(row_id):
    rec = services.get_endorsement(row_id)
    services.scope_via_policy(rec["policy_id"])
    return envelope.ok(serialize.endorsement(rec))


# --- the premium delta --------------------------------------------------------

def _compute_delta(rec, policy):
    """PRD 3.6: exactly one branch runs, selected by endorsement_type."""
    unexpired = services.unexpired_days(rec["effective_date"], policy)
    term = policy["term_days"]
    kind = rec["endorsement_type"]

    if kind == "ADD_AIRCRAFT":
        pilot = db.pilots[rec["named_pilot_id"]]
        basis = services.basis_for(pilot)
        band = calc.pilot_band(pilot, basis, db.clock)
        live_count = services.live_count_including_new(policy["id"])
        _, annual = services.price(policy, rec["new_agreed_value_cents"],
                                   rec["new_use_class"], band, live_count)
        return calc.pro_rata_up(annual, unexpired, term)

    if kind in ("VALUE_REVISION", "USE_CLASS_CHANGE"):
        target = db.schedules[rec["target_schedule_id"]]
        agreed = (rec["new_agreed_value_cents"] if kind == "VALUE_REVISION"
                  else target["agreed_value_cents"])
        use_class = (rec["new_use_class"] if kind == "USE_CLASS_CHANGE"
                     else target["use_class"])
        live_count = derive.live_schedule_count(policy["id"])
        if target["coverage_status"] not in C.LIVE_COVERAGE:
            live_count += 1
        _, annual = services.price(policy, agreed, use_class,
                                   target["rated_pilot_band"], live_count)
        return calc.pro_rata_up(annual - target["hull_premium_cents"], unexpired, term)

    if kind == "REMOVE_AIRCRAFT":
        target = db.schedules[rec["target_schedule_id"]]
        return -calc.short_rate_return(target["hull_premium_cents"], unexpired, term)

    if kind == "TERRITORY_EXTENSION":
        flat = C.TERRITORY_EXTENSION_FLAT_CENTS[rec["territory_code"]]
        return calc.pro_rata_up(flat, unexpired, term)

    if kind == "PREMISES_LIABILITY":
        return calc.pro_rata_up(C.PREMISES_EXTENSION_FLAT_CENTS, unexpired, term)

    if kind == "PRODUCT_LIABILITY":
        return calc.pro_rata_up(C.PRODUCT_EXTENSION_FLAT_CENTS, unexpired, term)

    base = calc.exposure_base_annual(kind, rec["exposure_member_count"],
                                     rec["per_seat_limit_cents"])
    return calc.pro_rata_up(base, unexpired, term)


# --- the negotiation cycle ----------------------------------------------------

@bp.route("/aviation/endorsements/<row_id>/quote", methods=["POST"])
@auth.endpoint(["Underwriter"])
def quote_endorsement(row_id):
    rec = services.get_endorsement(row_id)
    policy = db.policies[rec["policy_id"]]

    if rec["status"] != "SUBMITTED":
        raise ApiError("ERR_ENDORSEMENT_INVALID_STATE")
    if policy["status"] != "BOUND":
        raise ApiError("ERR_POLICY_NOT_BOUND")
    if rec["quote_round"] >= C.MAX_QUOTE_ROUNDS:
        raise ApiError("ERR_QUOTE_ROUNDS_EXHAUSTED")

    rec["quote_round"] += 1
    rec["quoted_premium_delta_cents"] = _compute_delta(rec, policy)
    rec["quoted_by_user_id"] = g.user_id
    rec["status"] = "QUOTED"
    touch(rec)
    return envelope.ok(serialize.endorsement(rec))


@bp.route("/aviation/endorsements/<row_id>/referral", methods=["POST"])
@auth.endpoint(["Underwriter"])
def refer_endorsement(row_id):
    rec = services.get_endorsement(row_id)
    body = V.json_body()
    referral_reason = V.get_str(body, "referral_reason")

    if rec["status"] != "QUOTED":
        raise ApiError("ERR_ENDORSEMENT_INVALID_STATE")
    if rec["quote_round"] >= C.MAX_QUOTE_ROUNDS:
        raise ApiError("ERR_QUOTE_ROUNDS_EXHAUSTED")

    rec["status"] = "SUBMITTED"
    rec["quoted_premium_delta_cents"] = None
    rec["quoted_by_user_id"] = None
    rec["referral_reason"] = referral_reason
    touch(rec)
    return envelope.ok(serialize.endorsement(rec))


# --- binding ------------------------------------------------------------------

def _add_aircraft_schedule(rec, policy):
    aircraft = db.aircraft[rec["aircraft_id"]]
    pilot = db.pilots[rec["named_pilot_id"]]
    min_total, min_type = services.warranty_minima(rec["new_use_class"])
    basis = services.basis_for(pilot)
    band = calc.pilot_band(pilot, basis, db.clock)
    live_count = services.live_count_including_new(policy["id"])
    rate, premium = services.price(policy, rec["new_agreed_value_cents"],
                                   rec["new_use_class"], band, live_count)
    return new_record(db.schedules, {
        "policy_id": policy["id"],
        "aircraft_id": aircraft["id"],
        "named_pilot_id": pilot["id"],
        "use_class": rec["new_use_class"],
        "agreed_value_cents": rec["new_agreed_value_cents"],
        "effective_from": rec["effective_date"],
        "effective_to": policy["effective_to"],
        "coverage_status": "ACTIVE",
        "warranty_status": "PENDING_EVIDENCE",
        "warranty_basis": basis,
        "warranted_min_total_hours": min_total,
        "warranted_min_hours_on_type": min_type,
        "rated_pilot_band": band,
        "rate_ppm": rate,
        "hull_premium_cents": premium,
        "acquisition_source": "SCHEDULED",
        "reported_declaration_id": None,
        "warranty_breach_reason": None,
    })


def _apply_structure(rec, policy):
    """Returns the snapshot that a later void needs in order to undo this bind."""
    kind = rec["endorsement_type"]
    snap = {}

    if kind == "ADD_AIRCRAFT":
        created = _add_aircraft_schedule(rec, policy)
        rec["target_schedule_id"] = created["id"]
        snap["created_schedule_id"] = created["id"]
        return snap

    if kind == "REMOVE_AIRCRAFT":
        target = db.schedules[rec["target_schedule_id"]]
        snap["removed_schedule_id"] = target["id"]
        target["coverage_status"] = "REMOVED"
        touch(target)
        return snap

    if kind in ("VALUE_REVISION", "USE_CLASS_CHANGE"):
        target = db.schedules[rec["target_schedule_id"]]
        snap["schedule_id"] = target["id"]
        snap["agreed_value_cents"] = target["agreed_value_cents"]
        snap["use_class"] = target["use_class"]
        snap["warranted_min_total_hours"] = target["warranted_min_total_hours"]
        snap["warranted_min_hours_on_type"] = target["warranted_min_hours_on_type"]
        snap["rate_ppm"] = target["rate_ppm"]
        snap["hull_premium_cents"] = target["hull_premium_cents"]
        if kind == "VALUE_REVISION":
            target["agreed_value_cents"] = rec["new_agreed_value_cents"]
        else:
            target["use_class"] = rec["new_use_class"]
            min_total, min_type = services.warranty_minima(rec["new_use_class"])
            target["warranted_min_total_hours"] = min_total
            target["warranted_min_hours_on_type"] = min_type
        services.rerate_schedule(target, policy)
        touch(target)
        return snap

    if kind == "TERRITORY_EXTENSION":
        snap["territorial_limit_code"] = policy["territorial_limit_code"]
        if rec["territory_code"] in ("CONTINENTAL", "WORLDWIDE"):
            policy["territorial_limit_code"] = rec["territory_code"]
        return snap

    if kind == "PREMISES_LIABILITY":
        snap["premises_liability_extension"] = policy["premises_liability_extension"]
        policy["premises_liability_extension"] = True
        return snap

    if kind == "PRODUCT_LIABILITY":
        snap["product_liability_extension"] = policy["product_liability_extension"]
        policy["product_liability_extension"] = True
        return snap

    return snap


@bp.route("/aviation/endorsements/<row_id>/bind", methods=["POST"])
@auth.endpoint(["Underwriter"])
def bind_endorsement(row_id):
    rec = services.get_endorsement(row_id)
    policy = db.policies[rec["policy_id"]]
    kind = rec["endorsement_type"]
    target = (db.schedules[rec["target_schedule_id"]]
              if rec["target_schedule_id"] is not None else None)

    if rec["status"] != "QUOTED":
        raise ApiError("ERR_ENDORSEMENT_INVALID_STATE")
    if policy["status"] != "BOUND":
        raise ApiError("ERR_POLICY_NOT_BOUND")

    if target is not None:
        services.require_live_schedule(target)

    if kind == "ADD_AIRCRAFT":
        services.check_medical(db.pilots[rec["named_pilot_id"]], rec["effective_date"])

    if target is not None and target["warranty_status"] == "BREACHED":
        raise ApiError("ERR_PILOT_WARRANTY_BREACHED")

    if kind == "TERRITORY_EXTENSION" and rec["territory_code"] == "WAR_ZONE_A":
        services.require_placement_covering(policy["id"], rec["effective_date"])

    if g.user_id == rec["quoted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if rec["effective_date"] < db.clock:
        raise ApiError("ERR_EFFECTIVE_DATE_OUT_OF_TERM")

    if kind == "ADD_AIRCRAFT":
        services.check_aircraft_overlap(rec["aircraft_id"], rec["effective_date"],
                                        policy["effective_to"])

    if kind == "ADD_AIRCRAFT":
        services.check_hull_aggregate(
            policy,
            derive.total_hull_sum_insured(policy["id"]) + rec["new_agreed_value_cents"])
    elif kind == "VALUE_REVISION":
        services.check_hull_aggregate(
            policy,
            derive.total_hull_sum_insured(policy["id"]) - target["agreed_value_cents"]
            + rec["new_agreed_value_cents"])

    if kind == "REMOVE_AIRCRAFT":
        for claim in derive.claims_of_schedule(target["id"]):
            if claim["adjustment_status"] in ("NOTIFIED", "INVESTIGATING",
                                              "COVERAGE_REFERRED", "RESERVED"):
                raise ApiError(
                    "ERR_CLAIM_INVALID_STATE",
                    "The target schedule carries an open claim and cannot be removed.")

    rec["premium_delta_cents"] = rec["quoted_premium_delta_cents"]
    services.append_transaction(policy["id"], "ENDORSEMENT_PREMIUM",
                                rec["premium_delta_cents"], rec["effective_date"],
                                "PRO_RATA", "bind of endorsement %s" % rec["id"],
                                endorsement_id=rec["id"])
    rec["_prebind"] = _apply_structure(rec, policy)
    rec["status"] = "BOUND"
    touch(rec)
    touch(policy)
    return envelope.ok(serialize.endorsement(rec))


# --- voiding ------------------------------------------------------------------

def _undo_structure(rec, policy):
    snap = rec.get("_prebind") or {}

    if "created_schedule_id" in snap:
        created = db.schedules.get(snap["created_schedule_id"])
        if created is not None and created["coverage_status"] != "REMOVED":
            created["coverage_status"] = "REMOVED"
            touch(created)
        return

    if "removed_schedule_id" in snap:
        removed = db.schedules.get(snap["removed_schedule_id"])
        if removed is not None and removed["coverage_status"] == "REMOVED":
            removed["coverage_status"] = "ACTIVE"
            touch(removed)
            if removed["warranty_status"] == "BREACHED":
                services.suspend_for_breach(removed)
        return

    if "schedule_id" in snap:
        target = db.schedules.get(snap["schedule_id"])
        if target is not None:
            target["agreed_value_cents"] = snap["agreed_value_cents"]
            target["use_class"] = snap["use_class"]
            target["warranted_min_total_hours"] = snap["warranted_min_total_hours"]
            target["warranted_min_hours_on_type"] = snap["warranted_min_hours_on_type"]
            target["rate_ppm"] = snap["rate_ppm"]
            target["hull_premium_cents"] = snap["hull_premium_cents"]
            touch(target)
        return

    if "territorial_limit_code" in snap:
        policy["territorial_limit_code"] = snap["territorial_limit_code"]
        return

    if "premises_liability_extension" in snap:
        policy["premises_liability_extension"] = snap["premises_liability_extension"]
        return

    if "product_liability_extension" in snap:
        policy["product_liability_extension"] = snap["product_liability_extension"]


@bp.route("/aviation/endorsements/<row_id>/void", methods=["POST"])
@auth.endpoint(["Underwriter"])
def void_endorsement(row_id):
    rec = services.get_endorsement(row_id)
    policy = db.policies[rec["policy_id"]]
    body = V.json_body()
    void_reason = V.get_str(body, "void_reason")

    if rec["status"] == "VOID":
        raise ApiError("ERR_ENDORSEMENT_INVALID_STATE")

    if rec["status"] == "BOUND":
        if db.clock >= rec["effective_date"]:
            raise ApiError("ERR_ENDORSEMENT_INVALID_STATE",
                           "A bound endorsement can only be voided before it attaches.")
        services.append_transaction(policy["id"], "RETURN_PREMIUM",
                                    -rec["premium_delta_cents"], db.clock, "PRO_RATA",
                                    "void of endorsement %s" % rec["id"],
                                    endorsement_id=rec["id"])
        _undo_structure(rec, policy)
        touch(policy)

    rec["void_reason"] = void_reason
    rec["status"] = "VOID"
    touch(rec)
    return envelope.ok(serialize.endorsement(rec))
