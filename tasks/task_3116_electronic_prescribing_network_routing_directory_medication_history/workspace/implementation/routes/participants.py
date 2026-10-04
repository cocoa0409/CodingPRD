"""NetworkParticipant and DirectoryEndpoint routes."""

import re

from flask import Blueprint, request

import db
import serializers
from clock import ok, parse_dt
from errors import (
    ApiError,
    ERR_DUPLICATE_PARTICIPANT_NPI,
    ERR_ENDPOINT_INTERVAL_OVERLAP,
    ERR_INVALID_REQUEST,
)
from request_context import (
    actor,
    allowed,
    body,
    created_order,
    enum_value,
    int_value,
    need_endpoint,
    need_participant,
    number_value,
    page_args,
    paginate,
    same_resource,
    string_value,
)
from services import certification, directory, history

bp = Blueprint("participants", __name__)

ALL_ROLES = [
    "NetworkOperator", "ParticipantAdmin", "Prescriber",
    "Pharmacy", "HubOperator", "PatientService",
]

PARTICIPANT_TYPES = ("PRESCRIBER_CLINIC", "PHARMACY", "PAYER", "HUB")
CERTIFICATION_STATUSES = ("UNCERTIFIED", "IN_CERTIFICATION", "CERTIFIED", "SUSPENDED")
VOLUME_BILLING_MODES = ("MONTHLY", "ROLLING_90_DAY")
FALLBACK_CHANNELS = ("FAX", "PRINT")
SERVICE_SETS = ("NEW_RX", "REFILL_RX", "CHANGE_CANCEL", "MED_HISTORY",
                "BENEFIT_COST", "ELIGIBILITY_FORMULARY")
ENDPOINT_ROLES = ("SENDER", "RECEIVER", "BOTH")
SERVICE_LEVELS = ("ELIGIBLE_A", "ELIGIBLE_B", "ELIGIBLE_C")
MESSAGE_STANDARDS = ("NCPDP_SCRIPT_2017071", "NCPDP_SCRIPT_2022011")

_NPI_RE = re.compile(r"^\d{10}$")

NUMBER_FIELDS = (
    "plan_copay_cents", "plan_deductible_cents", "plan_deductible_met_cents",
    "plan_brand_fee_cents", "plan_benefit_cap_cents",
)
FRACTION_FIELDS = ("plan_coinsurance_pct", "formulary_preferred_pct")


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


@bp.post("/network/participants")
def register_participant():
    role, user_id = actor()
    allowed(role, ["ParticipantAdmin", "NetworkOperator"])
    payload = body(
        required=("name", "participant_type", "npi"),
        optional=("volume_billing_mode", "fallback_channel", "fax_number",
                  "plan_copay_cents", "plan_coinsurance_pct", "plan_deductible_cents",
                  "plan_deductible_met_cents", "plan_brand_fee_cents",
                  "formulary_preferred_pct", "plan_benefit_cap_cents"),
    )
    name = string_value(payload["name"], "name")
    participant_type = enum_value(payload["participant_type"], "participant_type", PARTICIPANT_TYPES)
    npi = payload["npi"]
    if not isinstance(npi, str) or not _NPI_RE.match(npi):
        raise ApiError(ERR_INVALID_REQUEST, "'npi' must be exactly ten digits.")
    for field in NUMBER_FIELDS:
        if field in payload and not isinstance(payload[field], int):
            raise ApiError(ERR_INVALID_REQUEST, f"'{field}' must be an integer number of cents.")
    for field in FRACTION_FIELDS:
        if field in payload and not _is_number(payload[field]):
            raise ApiError(ERR_INVALID_REQUEST, f"'{field}' must be a number.")

    volume_billing_mode = payload.get("volume_billing_mode", "MONTHLY")
    enum_value(volume_billing_mode, "volume_billing_mode", VOLUME_BILLING_MODES)
    fallback_channel = payload.get("fallback_channel", "FAX")
    if fallback_channel is not None:
        enum_value(fallback_channel, "fallback_channel", FALLBACK_CHANNELS)

    for existing in db.all_rows("participants"):
        if existing["participant_type"] == participant_type and existing["npi"] == npi:
            raise ApiError(ERR_DUPLICATE_PARTICIPANT_NPI)

    row = db.new_resource()
    row.update({
        "name": name,
        "participant_type": participant_type,
        "npi": npi,
        "certification_status": "UNCERTIFIED",
        "certification_tests_passed": [],
        "volume_billing_mode": volume_billing_mode,
        "directory_listed": False,
        "open_route_attempt_count": 0,
        "fallback_channel": fallback_channel,
        "fax_number": payload.get("fax_number"),
        "plan_copay_cents": payload.get("plan_copay_cents", 1500),
        "plan_coinsurance_pct": payload.get("plan_coinsurance_pct", 0.2),
        "plan_deductible_cents": payload.get("plan_deductible_cents", 10000),
        "plan_deductible_met_cents": payload.get("plan_deductible_met_cents", 0),
        "plan_brand_fee_cents": payload.get("plan_brand_fee_cents", 300),
        "formulary_preferred_pct": payload.get("formulary_preferred_pct", 0.3),
        "plan_benefit_cap_cents": payload.get("plan_benefit_cap_cents", 50000),
        "last_certified_seq": 0,
    })
    db.add("participants", row)
    return ok(serializers.participant(row), status=201)


@bp.get("/network/participants")
def list_participants():
    role, _ = actor()
    allowed(role, ALL_ROLES)
    limit, offset = page_args()
    rows = db.all_rows("participants")
    for field in ("participant_type", "certification_status", "npi"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    rows = created_order(rows)
    window, meta = paginate(rows, limit, offset)
    return ok([serializers.participant(r) for r in window], **meta)


@bp.get("/network/participants/<pid>")
def get_participant(pid):
    role, _ = actor()
    allowed(role, ALL_ROLES)
    participant = need_participant(pid)
    return ok(serializers.participant(participant))


@bp.post("/network/participants/<pid>/certification/start")
def certification_start(pid):
    role, user_id = actor()
    allowed(role, ["ParticipantAdmin"])
    body(required=(), optional=())
    participant = need_participant(pid)
    same_resource(role, user_id, participant["id"])
    certification.restart_certification(participant)
    return ok(serializers.participant(participant))


@bp.post("/network/participants/<pid>/certification/tests")
def certification_test(pid):
    role, user_id = actor()
    allowed(role, ["ParticipantAdmin"])
    payload = body(required=("test_code", "outcome"), optional=())
    participant = need_participant(pid)
    same_resource(role, user_id, participant["id"])
    outcome = enum_value(payload["outcome"], "outcome", ("PASS", "FAIL"))
    if participant["certification_status"] != "IN_CERTIFICATION":
        raise ApiError("ERR_INVALID_STATE")
    certification.record_test(participant, payload["test_code"], outcome)
    return ok(serializers.participant(participant))


@bp.post("/network/participants/<pid>/certify")
def certify(pid):
    role, user_id = actor()
    allowed(role, ["ParticipantAdmin"])
    payload = body(required=("expected_participant_version",), optional=())
    participant = need_participant(pid)
    same_resource(role, user_id, participant["id"])
    if participant["certification_status"] != "IN_CERTIFICATION":
        raise ApiError("ERR_INVALID_STATE")
    expected = int_value(payload["expected_participant_version"],
                         "expected_participant_version", minimum=0)
    certification.promote(participant, expected)
    return ok(serializers.participant(participant))


@bp.post("/network/participants/<pid>/suspend")
def suspend(pid):
    role, _ = actor()
    allowed(role, ["NetworkOperator"])
    body(required=(), optional=())
    participant = need_participant(pid)
    if participant["certification_status"] != "CERTIFIED":
        raise ApiError("ERR_INVALID_STATE")
    certification.suspend_participant(participant)
    return ok(serializers.participant(participant))


@bp.get("/network/participants/<pid>/delivery-reachability")
def delivery_reachability(pid):
    role, _ = actor()
    allowed(role, ["NetworkOperator", "ParticipantAdmin", "HubOperator"])
    participant = need_participant(pid)
    return ok(serializers.reachability_report(participant))


@bp.get("/network/participants/<pid>/endpoints")
def participant_endpoints(pid):
    role, _ = actor()
    allowed(role, ALL_ROLES)
    participant = need_participant(pid)
    rows = created_order(certification.endpoints_of(participant["id"]))
    return ok([serializers.endpoint(e) for e in rows])


@bp.get("/network/participants/<pid>/patients")
def participant_patients(pid):
    role, _ = actor()
    allowed(role, ["NetworkOperator", "ParticipantAdmin", "Prescriber", "PatientService"])
    limit, offset = page_args()
    participant = need_participant(pid)
    rows = [p for p in db.all_rows("patients") if p.get("covered_plan_payer_id") == participant["id"]]
    rows = created_order(rows)
    window, meta = paginate(rows, limit, offset)
    return ok([serializers.patient(p) for p in window], **meta)


@bp.get("/network/participants/<pid>/fee-entries")
def participant_fee_entries(pid):
    role, _ = actor()
    allowed(role, ["NetworkOperator", "ParticipantAdmin"])
    limit, offset = page_args()
    participant = need_participant(pid)
    rows = [e for e in db.all_rows("fee_entries") if e["participant_id"] == participant["id"]]
    month_key = request.args.get("month_key")
    if month_key is not None:
        rows = [e for e in rows if e["month_key"] == month_key]
    rows = created_order(rows)
    window, meta = paginate(rows, limit, offset)
    return ok([serializers.fee_entry(e) for e in window], **meta)


@bp.post("/network/participants/<pid>/endpoints")
def register_endpoint(pid):
    role, user_id = actor()
    allowed(role, ["ParticipantAdmin", "NetworkOperator"])
    payload = body(
        required=("service_set", "endpoint_role", "service_level",
                  "sla_response_minutes", "message_standard", "effective_from"),
        optional=("effective_to",),
    )
    participant = need_participant(pid)
    if role == "ParticipantAdmin":
        same_resource(role, user_id, participant["id"])

    service_set = enum_value(payload["service_set"], "service_set", SERVICE_SETS)
    endpoint_role = enum_value(payload["endpoint_role"], "endpoint_role", ENDPOINT_ROLES)
    service_level = enum_value(payload["service_level"], "service_level", SERVICE_LEVELS)
    message_standard = enum_value(payload["message_standard"], "message_standard", MESSAGE_STANDARDS)
    sla = int_value(payload["sla_response_minutes"], "sla_response_minutes", minimum=0)
    effective_from = parse_dt(payload["effective_from"], "effective_from")
    effective_to = None
    if payload.get("effective_to") is not None:
        effective_to = parse_dt(payload["effective_to"], "effective_to")
        if effective_to <= effective_from:
            raise ApiError(ERR_INVALID_REQUEST,
                           "'effective_to' must be later than 'effective_from'.")

    for existing in certification.endpoints_of(participant["id"]):
        # §2.6: "Two endpoints of the same participant that share a `service_set`, an
        # `endpoint_role`, and a `message_standard` may not hold overlapping
        # intervals". The contracted `service_level` is part of the same statement of
        # capability: §3.4's selector ranks several live candidates of one pharmacy
        # ("Among those, the `service_level` ordinal decides") and §3.5's backup
        # nomination speaks of "at least one other endpoint of the same participant
        # and the same `service_set`", so two endpoints of one service set that
        # contracted *different* service levels are distinct contracts and their
        # intervals may overlap. `sla_response_minutes` is not part of the identity —
        # re-contracting the same service level at a different SLA is a modification
        # of one contract, so its intervals must not overlap.
        if (existing["service_set"] != service_set
                or existing["endpoint_role"] != endpoint_role
                or existing["service_level"] != service_level
                or existing["message_standard"] != message_standard):
            continue
        existing_end = existing.get("effective_to")
        other_end = (parse_dt(existing_end, "effective_to")
                     if existing_end is not None else None)
        if history.windows_overlap(effective_from, effective_to,
                                   existing["effective_from"], other_end):
            raise ApiError(ERR_ENDPOINT_INTERVAL_OVERLAP)

    row = db.new_resource()
    row.update({
        "participant_id": participant["id"],
        "service_set": service_set,
        "endpoint_role": endpoint_role,
        "service_level": service_level,
        "sla_response_minutes": sla,
        "message_standard": message_standard,
        "tier_schedule": None,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "status": "PENDING_CERT",
        "reported_attempt_count": 0,
        "acknowledged_count": 0,
        "reliability_ratio": 1.0,
        "reliability_ratio_ewma": 1.0,
    })
    db.add("endpoints", row)
    directory.recompute_directory_listed(participant)
    return ok(serializers.endpoint(row), status=201)