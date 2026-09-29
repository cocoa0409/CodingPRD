"""Policies and aircraft schedules."""

from flask import Blueprint, request

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

bp = Blueprint("policies", __name__)

ALL = C.ALL_ROLES
OPEN_WRITE = ["Underwriter", "Broker"]


# --- policies -----------------------------------------------------------------

@bp.route("/aviation/policies", methods=["POST"])
@auth.endpoint(OPEN_WRITE)
def create_policy():
    body = V.json_body()
    operator = services.resolve_fk(body, "operator_id", services.get_operator)

    policy_type = V.get_str(body, "policy_type")
    effective_from = V.get_instant(body, "effective_from")
    effective_to = V.get_instant(body, "effective_to")
    territorial_limit_code = V.get_str(body, "territorial_limit_code")
    base_hull_rate_ppm = V.get_int(body, "base_hull_rate_ppm")
    hull_deductible_ppm = V.get_int(body, "hull_deductible_ppm")
    liability_limit_cents = V.get_int(body, "liability_limit_cents")
    hull_aggregate_limit_cents = V.get_int(body, "hull_aggregate_limit_cents")
    permitted_use_classes = V.get_array(body, "permitted_use_classes", required=False)
    automatic_acquisition_enabled = V.get_bool(body, "automatic_acquisition_enabled",
                                               required=False, default=False)
    acquisition_reporting_days = V.get_int(body, "acquisition_reporting_days",
                                           required=False, default=30)
    war_risk_required = V.get_bool(body, "war_risk_required", required=False, default=False)

    V.check_enum(policy_type, "policy_type", C.POLICY_TYPES)
    V.check_enum(territorial_limit_code, "territorial_limit_code", C.TERRITORIES)
    V.check_before(effective_from, effective_to, "effective_from must precede effective_to.")
    V.check_range(base_hull_rate_ppm, "base_hull_rate_ppm", 1, 100000)
    V.check_range(hull_deductible_ppm, "hull_deductible_ppm", 0, 200000)
    V.check_range(liability_limit_cents, "liability_limit_cents", 1)
    V.check_range(hull_aggregate_limit_cents, "hull_aggregate_limit_cents", 1)
    V.check_range(acquisition_reporting_days, "acquisition_reporting_days", 1, 180)
    if permitted_use_classes is None:
        permitted_use_classes = list(C.USE_CLASSES)
    else:
        if not permitted_use_classes:
            raise V.invalid("permitted_use_classes must be a non-empty subset of the four use classes.")
        for item in permitted_use_classes:
            if not isinstance(item, str) or item not in C.USE_CLASSES:
                raise V.invalid("permitted_use_classes must be a subset of the four use classes.")
        permitted_use_classes = list(permitted_use_classes)

    rec = new_record(db.policies, {
        "operator_id": operator["id"],
        "policy_number": db.next_policy_number(),
        "policy_type": policy_type,
        "status": "DRAFT",
        "effective_from": effective_from,
        "effective_to": effective_to,
        "term_days": util.day_diff(effective_from, effective_to),
        "territorial_limit_code": territorial_limit_code,
        "permitted_use_classes": permitted_use_classes,
        "base_hull_rate_ppm": base_hull_rate_ppm,
        "hull_deductible_ppm": hull_deductible_ppm,
        "liability_limit_cents": liability_limit_cents,
        "hull_aggregate_limit_cents": hull_aggregate_limit_cents,
        "premises_liability_extension": False,
        "product_liability_extension": False,
        "automatic_acquisition_enabled": automatic_acquisition_enabled,
        "acquisition_reporting_days": acquisition_reporting_days,
        "war_risk_required": war_risk_required,
    })
    return envelope.ok(serialize.policy(rec), 201)


@bp.route("/aviation/policies", methods=["GET"])
@auth.endpoint(ALL)
def list_policies():
    limit, offset = V.pagination()
    rows = ordered(db.policies)
    own = auth.visible_operator_id()
    if own is not None:
        rows = [r for r in rows if r["operator_id"] == own]
    rows = V.filter_eq(rows, "operator_id", request.args.get("operator_id"))
    rows = V.filter_eq(rows, "status", request.args.get("status"))
    rows = V.filter_eq(rows, "policy_type", request.args.get("policy_type"))
    total = len(rows)
    window = V.page(rows, limit, offset)
    return envelope.ok_list(serialize.many(serialize.policy, window), limit, offset, total)


@bp.route("/aviation/policies/<row_id>", methods=["GET"])
@auth.endpoint(ALL)
def read_policy(row_id):
    policy = services.get_policy(row_id)
    services.scope_policy(policy)
    return envelope.ok(serialize.policy(policy))


@bp.route("/aviation/policies/<row_id>/bind", methods=["POST"])
@auth.endpoint(["Underwriter"])
def bind_policy(row_id):
    policy = services.get_policy(row_id)
    if policy["status"] != "DRAFT":
        raise ApiError("ERR_POLICY_NOT_DRAFT")

    schedules = derive.schedules_of_policy(policy["id"])
    if not any(s["coverage_status"] == "PENDING" for s in schedules):
        raise ApiError("ERR_POLICY_HAS_NO_SCHEDULES")

    if policy["war_risk_required"]:
        services.require_placement_covering(policy["id"], policy["effective_from"])

    policy["status"] = "BOUND"
    activated_premium = 0
    for schedule in schedules:
        if schedule["coverage_status"] != "PENDING":
            continue
        if schedule["acquisition_source"] != "SCHEDULED":
            continue
        services.activate_schedule(schedule)
        activated_premium += schedule["hull_premium_cents"]

    services.append_transaction(policy["id"], "INITIAL_PREMIUM", activated_premium,
                                policy["effective_from"], "ANNUAL",
                                "bind of policy %s" % policy["id"])
    touch(policy)
    return envelope.ok(serialize.policy(policy))


# --- aircraft schedules -------------------------------------------------------

@bp.route("/aviation/schedules", methods=["POST"])
@auth.endpoint(OPEN_WRITE)
def create_schedule():
    body = V.json_body()
    policy = services.resolve_fk(body, "policy_id", services.get_policy)
    services.scope_policy(policy)
    aircraft = services.resolve_fk(body, "aircraft_id", services.get_aircraft)
    pilot = services.resolve_fk(body, "named_pilot_id", services.get_pilot)

    use_class = V.get_str(body, "use_class")
    agreed_value_cents = V.get_int(body, "agreed_value_cents")
    effective_from = V.get_instant(body, "effective_from")
    effective_to = V.get_instant(body, "effective_to")
    acquisition_source = V.get_str(body, "acquisition_source", required=False, default="SCHEDULED")

    V.check_enum(use_class, "use_class", C.USE_CLASSES)
    V.check_enum(acquisition_source, "acquisition_source", C.ACQUISITION_SOURCES)
    V.check_range(agreed_value_cents, "agreed_value_cents", 1)
    V.check_before(effective_from, effective_to, "effective_from must precede effective_to.")

    if acquisition_source == "SCHEDULED":
        if policy["status"] != "DRAFT":
            raise ApiError("ERR_POLICY_NOT_DRAFT")
    else:
        if policy["status"] != "BOUND":
            raise ApiError("ERR_POLICY_NOT_BOUND")

    services.check_medical(pilot, effective_from)

    operator = db.operators[policy["operator_id"]]
    services.check_use_class(policy, operator, use_class)

    if effective_from < policy["effective_from"] or effective_to > policy["effective_to"]:
        raise ApiError("ERR_SCHEDULE_WINDOW_OUTSIDE_POLICY")

    services.check_aircraft_overlap(aircraft["id"], effective_from, effective_to)

    if acquisition_source == "AUTOMATIC_ACQUISITION" and not policy["automatic_acquisition_enabled"]:
        raise ApiError("ERR_AUTO_ACQUISITION_DISABLED")

    services.check_over_insurance(aircraft, effective_from.year, agreed_value_cents)
    services.check_hull_aggregate(
        policy, derive.total_hull_sum_insured(policy["id"]) + agreed_value_cents)

    min_total, min_type = services.warranty_minima(use_class)
    basis = services.basis_for(pilot)
    band = calc.pilot_band(pilot, basis, db.clock)
    live_count = services.live_count_including_new(policy["id"])
    rate, premium = services.price(policy, agreed_value_cents, use_class, band, live_count)

    rec = new_record(db.schedules, {
        "policy_id": policy["id"],
        "aircraft_id": aircraft["id"],
        "named_pilot_id": pilot["id"],
        "use_class": use_class,
        "agreed_value_cents": agreed_value_cents,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "coverage_status": "PENDING",
        "warranty_status": "PENDING_EVIDENCE",
        "warranty_basis": basis,
        "warranted_min_total_hours": min_total,
        "warranted_min_hours_on_type": min_type,
        "rated_pilot_band": band,
        "rate_ppm": rate,
        "hull_premium_cents": premium,
        "acquisition_source": acquisition_source,
        "reported_declaration_id": None,
        "warranty_breach_reason": None,
    })
    return envelope.ok(serialize.schedule(rec), 201)


@bp.route("/aviation/schedules", methods=["GET"])
@auth.endpoint(ALL)
def list_schedules():
    limit, offset = V.pagination()
    rows = ordered(db.schedules)
    visible = services.visible_policy_ids()
    if visible is not None:
        rows = [r for r in rows if r["policy_id"] in visible]
    rows = V.filter_eq(rows, "policy_id", request.args.get("policy_id"))
    rows = V.filter_eq(rows, "aircraft_id", request.args.get("aircraft_id"))
    rows = V.filter_eq(rows, "named_pilot_id", request.args.get("named_pilot_id"))
    rows = V.filter_eq(rows, "reported_declaration_id", request.args.get("reported_declaration_id"))
    rows = V.filter_eq(rows, "coverage_status", request.args.get("coverage_status"))
    rows = V.filter_eq(rows, "warranty_status", request.args.get("warranty_status"))
    total = len(rows)
    window = V.page(rows, limit, offset)
    return envelope.ok_list(serialize.many(serialize.schedule, window), limit, offset, total)


@bp.route("/aviation/schedules/<row_id>", methods=["GET"])
@auth.endpoint(ALL)
def read_schedule(row_id):
    schedule = services.get_schedule(row_id)
    services.scope_schedule(schedule)
    return envelope.ok(serialize.schedule(schedule))


@bp.route("/aviation/schedules/<row_id>/value-revisions", methods=["POST"])
@auth.endpoint(["Underwriter"])
def revise_agreed_value(row_id):
    schedule = services.get_schedule(row_id)
    body = V.json_body()
    new_agreed_value_cents = V.get_int(body, "new_agreed_value_cents")
    expected_schedule_version = V.get_int(body, "expected_schedule_version")
    V.check_range(new_agreed_value_cents, "new_agreed_value_cents", 1)

    services.require_live_schedule(schedule)

    if expected_schedule_version != schedule["version"]:
        raise ApiError("ERR_STALE_SCHEDULE_VERSION")

    if schedule["warranty_status"] == "BREACHED":
        raise ApiError("ERR_PILOT_WARRANTY_BREACHED")

    policy = db.policies[schedule["policy_id"]]
    aircraft = db.aircraft[schedule["aircraft_id"]]
    services.check_over_insurance(aircraft, schedule["effective_from"].year, new_agreed_value_cents)
    prospective = (derive.total_hull_sum_insured(policy["id"])
                   - schedule["agreed_value_cents"] + new_agreed_value_cents)
    services.check_hull_aggregate(policy, prospective)

    schedule["agreed_value_cents"] = new_agreed_value_cents
    old_premium = services.rerate_schedule(schedule, policy)
    touch(schedule)
    services.post_rerate_adjustment(schedule, policy, old_premium,
                                    "value revision of schedule %s" % schedule["id"])
    return envelope.ok(serialize.schedule(schedule))


@bp.route("/aviation/schedules/<row_id>/warranty-findings", methods=["POST"])
@auth.endpoint(["Underwriter"])
def record_warranty_finding(row_id):
    schedule = services.get_schedule(row_id)
    body = V.json_body()
    finding = V.get_str(body, "finding")
    breach_reason = V.get_str(body, "breach_reason", required=False)
    V.check_enum(finding, "finding", ("EVIDENCE_VERIFIED", "BREACH", "WAIVER"))

    services.require_live_schedule(schedule)

    if finding == "BREACH" and breach_reason is None:
        raise ApiError("ERR_CONDITIONAL_FIELD_REQUIRED",
                       "breach_reason is mandatory for a finding of BREACH.")

    current = schedule["warranty_status"]
    if finding == "EVIDENCE_VERIFIED":
        if current in ("PENDING_EVIDENCE", "BREACHED"):
            schedule["warranty_status"] = "COMPLIANT"
            schedule["warranty_breach_reason"] = None
            touch(schedule)
            services.reinstate_cover(schedule)
    elif finding == "BREACH":
        if current in ("PENDING_EVIDENCE", "COMPLIANT"):
            schedule["warranty_status"] = "BREACHED"
            schedule["warranty_breach_reason"] = breach_reason
            touch(schedule)
            services.suspend_for_breach(schedule)
    else:
        if current == "BREACHED":
            schedule["warranty_status"] = "WAIVED"
            touch(schedule)
            if schedule["coverage_status"] == "SUSPENDED_WARRANTY":
                schedule["warranty_breach_reason"] = None
                services.reinstate_cover(schedule)
    return envelope.ok(serialize.schedule(schedule))
