"""Prescription, SigningSession and RoutingAttempt routes."""

from flask import Blueprint, request

import clock
import db
import serializers
from clock import ok
from errors import (
    ApiError,
    ERR_ATTEMPT_PRESCRIPTION_MISMATCH,
    ERR_CONTROLLED_NOT_SUPPORTED_BY_STANDARD,
    ERR_CRITICAL_ORDER_DELIVERY_REQUIRED,
    ERR_ENDPOINT_COVERAGE_WARNING,
    ERR_FALLBACK_CHANNEL_UNAVAILABLE,
    ERR_FALLBACK_HOP_LIMIT_EXCEEDED,
    ERR_FALLBACK_NOT_PERMITTED,
    ERR_IDENTITY_PROOFING_REQUIRED,
    ERR_INVALID_STATE,
    ERR_MESSAGE_STANDARD_MISMATCH,
    ERR_NO_FAILED_ATTEMPT_TO_FALL_BACK,
    ERR_NO_ROUTE_AVAILABLE,
    ERR_OTP_INVALID,
    ERR_ACCOUNT_LOCKED,
    ERR_PHARMACY_NOT_CERTIFIED_FOR_CONTROLLED,
    ERR_ROUTE_ATTEMPT_IN_PROGRESS,
    ERR_STALE_VERSION,
)
from request_context import (
    actor,
    allowed,
    body,
    created_order,
    enum_value,
    int_value,
    need_attempt,
    need_endpoint,
    need_patient,
    need_prescription,
    need_session,
    page_args,
    paginate,
    same_resource,
    string_value,
)
from services import billing, certification, directory, routing

bp = Blueprint("prescriptions", __name__)

TRANSACTION_TYPES = ("NEW_RX", "REFILL_REQUEST", "REFILL_RESPONSE", "CHANGE_REQUEST",
                     "CHANGE_RESPONSE", "CANCEL_REQUEST", "CANCEL_RESPONSE")
CONTROLLED_SCHEDULES = ("NON_CONTROLLED", "SCHEDULE_II", "SCHEDULE_III",
                        "SCHEDULE_IV", "SCHEDULE_V")
MESSAGE_STANDARDS = ("NCPDP_SCRIPT_2017071", "NCPDP_SCRIPT_2022011")
CHANNELS = ("NETWORK", "FAX", "PRINT")

UNDELIVERABLE_FAILURE_CODES = {
    "NO_ROUTE", "CF_0000", "CF_0001", "CF_0002", "CF_0003", "CF_0004",
    "CF_0005", "CF_0006", "CF_0007", "TRANSMISSION_TIMEOUT",
}
REJECTION_FAILURE_CODES = {"CF_0003", "CF_0007", "POST_DELIVERY"}
FALLBACK_EXEMPT_CODES = {"PATIENT_UNKNOWN", "BENEFIT_EXHAUSTED"}

FALLBACK_CHANNEL_MAX_ATTEMPTS = 3

PRESCRIPTION_ROLES = ["Prescriber", "Pharmacy", "NetworkOperator", "HubOperator"]


# --------------------------------------------------------------------------
# Prescriptions
# --------------------------------------------------------------------------

@bp.post("/network/prescriptions")
def create_prescription():
    role, user_id = actor()
    allowed(role, ["Prescriber"])
    payload = body(
        required=("prescriber_id", "receiving_pharmacy_id", "patient_id", "drug_ndc",
                  "transaction_type", "controlled_schedule", "message_standard",
                  "days_supply", "quantity", "refills_authorized"),
        optional=(),
    )
    prescriber = db.get("participants", payload["prescriber_id"])
    if prescriber is None:
        raise ApiError("ERR_PARTICIPANT_NOT_FOUND")
    same_resource(role, user_id, prescriber["id"])
    pharmacy = db.get("participants", payload["receiving_pharmacy_id"])
    if pharmacy is None:
        raise ApiError("ERR_PARTICIPANT_NOT_FOUND")
    patient = need_patient(payload["patient_id"])

    drug_ndc = string_value(payload["drug_ndc"], "drug_ndc")
    transaction_type = enum_value(payload["transaction_type"], "transaction_type", TRANSACTION_TYPES)
    controlled_schedule = enum_value(payload["controlled_schedule"], "controlled_schedule",
                                    CONTROLLED_SCHEDULES)
    message_standard = enum_value(payload["message_standard"], "message_standard", MESSAGE_STANDARDS)
    days_supply = int_value(payload["days_supply"], "days_supply", minimum=0)
    quantity = int_value(payload["quantity"], "quantity", minimum=0)
    refills_authorized = int_value(payload["refills_authorized"], "refills_authorized", minimum=0)

    row = db.new_resource()
    row.update({
        "prescriber_id": prescriber["id"],
        "receiving_pharmacy_id": pharmacy["id"],
        "patient_id": patient["id"],
        "drug_ndc": drug_ndc,
        "transaction_type": transaction_type,
        "controlled_schedule": controlled_schedule,
        "message_standard": message_standard,
        "days_supply": days_supply,
        "quantity": quantity,
        "refills_authorized": refills_authorized,
        "refills_used": 0,
        "is_controlled": False,
        "clinical_status": "DRAFT",
        "routing_status": "NOT_ROUTED",
        "significance": "STANDARD",
        "monitored_under_consent": False,
        "routing_attempt_count": 0,
        # §3.1: the participant declares how it prefers to receive undeliverable
        # traffic, and §3.5's fallback channel is that declaration — so the order
        # carries the authoring clinic's channel and number.
        "fallback_channel": prescriber.get("fallback_channel"),
        "fax_number": prescriber.get("fax_number"),
        "routed_endpoint_id": None,
        "active_routing_attempt_id": None,
        "signature_audit_id": None,
    })
    db.add("prescriptions", row)
    routing.recompute_derived(row)
    return ok(serializers.prescription(row), status=201)


@bp.get("/network/prescriptions")
def list_prescriptions():
    role, _ = actor()
    allowed(role, PRESCRIPTION_ROLES)
    limit, offset = page_args()
    rows = db.all_rows("prescriptions")
    for field in ("prescriber_id", "receiving_pharmacy_id", "patient_id", "clinical_status",
                  "routing_status", "significance", "routed_endpoint_id"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    rows = created_order(rows)
    window, meta = paginate(rows, limit, offset)
    return ok([serializers.prescription(p) for p in window], **meta)


@bp.get("/network/prescriptions/<rid>")
def get_prescription(rid):
    role, _ = actor()
    allowed(role, PRESCRIPTION_ROLES)
    prescription = need_prescription(rid)
    routing.refresh_prescription_views(prescription)
    return ok(serializers.prescription(prescription))


@bp.get("/network/prescriptions/<rid>/attempts")
def prescription_attempts(rid):
    role, _ = actor()
    allowed(role, PRESCRIPTION_ROLES)
    prescription = need_prescription(rid)
    rows = created_order([a for a in db.all_rows("routing_attempts")
                          if a["prescription_id"] == prescription["id"]])
    return ok([serializers.routing_attempt(a) for a in rows])


@bp.get("/network/prescriptions/<rid>/active-attempt")
def prescription_active_attempt(rid):
    role, _ = actor()
    allowed(role, PRESCRIPTION_ROLES)
    prescription = need_prescription(rid)
    attempt = db.find_one("routing_attempts",
                          lambda a: a["prescription_id"] == prescription["id"]
                          and a["outcome"] == "IN_PROGRESS")
    return ok([serializers.routing_attempt(attempt)] if attempt else [])


@bp.get("/network/prescriptions/<rid>/routed-endpoint")
def prescription_routed_endpoint(rid):
    role, _ = actor()
    allowed(role, ["Prescriber", "Pharmacy", "NetworkOperator"])
    prescription = need_prescription(rid)
    endpoint = db.get("endpoints", prescription.get("routed_endpoint_id"))
    return ok([serializers.endpoint(endpoint)] if endpoint else [])


@bp.get("/network/prescriptions/<rid>/signing-sessions")
def prescription_sessions(rid):
    role, _ = actor()
    allowed(role, ["Prescriber", "NetworkOperator"])
    prescription = need_prescription(rid)
    rows = created_order([s for s in db.all_rows("signing_sessions")
                          if s["prescription_id"] == prescription["id"]])
    return ok([serializers.signing_session(s) for s in rows])


@bp.get("/network/prescriptions/<rid>/signature-session")
def prescription_signature_session(rid):
    role, _ = actor()
    allowed(role, ["Prescriber", "NetworkOperator"])
    prescription = need_prescription(rid)
    session = db.get("signing_sessions", prescription.get("signature_audit_id"))
    return ok(serializers.signature_session(session))


@bp.get("/network/prescriptions/<rid>/benefit-checks")
def prescription_benefit_checks(rid):
    role, _ = actor()
    allowed(role, ["Prescriber", "Pharmacy", "NetworkOperator"])
    prescription = need_prescription(rid)
    rows = created_order([b for b in db.all_rows("benefit_checks")
                          if b["prescription_id"] == prescription["id"]])
    return ok([serializers.benefit_check(b) for b in rows])


# --------------------------------------------------------------------------
# Signing
# --------------------------------------------------------------------------

@bp.post("/network/prescriptions/<rid>/sign")
def sign_prescription(rid):
    role, user_id = actor()
    allowed(role, ["Prescriber"])
    payload = body(required=("signing_session_id",), optional=())
    prescription = need_prescription(rid)
    same_resource(role, user_id, prescription["prescriber_id"])

    session = db.get("signing_sessions", payload["signing_session_id"])
    if session is None:
        raise ApiError("ERR_SIGNING_SESSION_NOT_FOUND")

    routing.recompute_derived(prescription)
    # §3.3/§2.9: the controlled-substance safety preconditions are evaluated ahead of the
    # structural ones, so an order that is controlled and missing two-factor evidence
    # surfaces the safety error even when its session also fails the structural band.
    if prescription["is_controlled"] and session["two_factor_status"] != "PASSED":
        raise ApiError(ERR_IDENTITY_PROOFING_REQUIRED)

    if prescription["clinical_status"] not in ("DRAFT", "SIGNED"):
        raise ApiError(ERR_INVALID_STATE)
    if session["prescription_id"] != prescription["id"]:
        raise ApiError(ERR_INVALID_STATE)
    if session["session_status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE)
    if session["identity_proofing_status"] != "PASSED":
        raise ApiError(ERR_INVALID_STATE)
    if session["two_factor_status"] != "PASSED":
        raise ApiError(ERR_INVALID_STATE)
    if routing.active_attempt_id(prescription["id"]) is not None:
        raise ApiError(ERR_INVALID_STATE)

    if prescription["is_controlled"]:
        if (session["identity_proofing_status"] != "PASSED"
                or session["two_factor_status"] != "PASSED"):
            raise ApiError(ERR_IDENTITY_PROOFING_REQUIRED)
        if prescription["message_standard"] == "NCPDP_SCRIPT_2017071":
            raise ApiError(ERR_CONTROLLED_NOT_SUPPORTED_BY_STANDARD)
        holds = any(
            e["participant_id"] == prescription["receiving_pharmacy_id"]
            and e["service_set"] == "NEW_RX"
            and e["status"] == "ACTIVE"
            for e in db.all_rows("endpoints")
        )
        if not holds:
            raise ApiError(ERR_PHARMACY_NOT_CERTIFIED_FOR_CONTROLLED)

    prescription["clinical_status"] = "SIGNED"
    prescription["signature_audit_id"] = session["id"]
    db.touch(prescription)
    session["session_status"] = "SIGNED"
    session["signed_at"] = clock.now_iso()
    db.touch(session)
    routing.refresh_prescription_views(prescription)
    return ok(serializers.prescription(prescription))


# --------------------------------------------------------------------------
# Routing
# --------------------------------------------------------------------------

def _create_attempt(prescription, channel, target_endpoint_id):
    prescription["routing_attempt_count"] += 1
    row = db.new_resource()
    row.update({
        "prescription_id": prescription["id"],
        "attempt_no": prescription["routing_attempt_count"],
        "channel": channel,
        "target_endpoint_id": target_endpoint_id,
        "outcome": "IN_PROGRESS",
        "failure_code": None,
        "error_code_returned": None,
        "reported_at": None,
        "correction_entry_id": None,
    })
    db.add("routing_attempts", row)
    prescription["active_routing_attempt_id"] = row["id"]
    return row


@bp.post("/network/prescriptions/<rid>/route")
def route_prescription(rid):
    role, user_id = actor()
    allowed(role, ["Prescriber"])
    payload = body(required=("expected_prescription_version",), optional=())
    prescription = need_prescription(rid)
    same_resource(role, user_id, prescription["prescriber_id"])

    rerouting = False
    if prescription["clinical_status"] == "ROUTED":
        if prescription["routing_status"] not in ("ROUTED", "BACKUP_SELECTION"):
            raise ApiError(ERR_INVALID_STATE)
        rerouting = True
    elif prescription["clinical_status"] in ("DELIVERED", "REJECTED"):
        # §3.5: acknowledge, post-delivery rejection and ...→ROUTED are re-entry
        # edges, so an order that has already been delivered or rejected may be
        # routed again — the self-loop "is how refill, change, and cancel
        # responses travel" and it closes the cyclic routing machine.
        if prescription["routing_status"] not in ("ROUTED", "BACKUP_SELECTION",
                                                  "ROUTE_FAILED", "FALLBACK_SENT"):
            raise ApiError(ERR_INVALID_STATE)
        rerouting = True
    elif prescription["clinical_status"] == "SIGNED":
        if prescription["routing_status"] != "NOT_ROUTED":
            raise ApiError(ERR_INVALID_STATE)
    else:
        raise ApiError(ERR_INVALID_STATE)

    expected = int_value(payload["expected_prescription_version"],
                         "expected_prescription_version", minimum=0)
    if expected != prescription["version"]:
        raise ApiError(ERR_STALE_VERSION)
    if routing.active_attempt_id(prescription["id"]) is not None:
        raise ApiError(ERR_ROUTE_ATTEMPT_IN_PROGRESS)

    winner = routing.select_endpoint(prescription)
    if (rerouting
            and prescription["transaction_type"] in routing.STANDARD_AGREEMENT_TYPES
            and winner["message_standard"] != prescription["message_standard"]):
        raise ApiError(ERR_MESSAGE_STANDARD_MISMATCH)

    attempt = _create_attempt(prescription, "NETWORK", winner["id"])
    prescription["routed_endpoint_id"] = winner["id"]
    # §3.4: "a successful route ... advances the prescription's `clinical_status` from
    # `SIGNED` to `ROUTED`". A re-route from a closed state — a post-delivery rejection
    # or a delivery — returns the order to the wire, so it is `ROUTED` again.
    prescription["clinical_status"] = "ROUTED"
    prescription["routing_status"] = "ROUTED"
    if prescription["transaction_type"] == "REFILL_RESPONSE":
        prescription["refills_used"] += 1
    prescription["version"] += 1
    db.touch(prescription, bump_version=False)

    directory.recompute_endpoint_counters(winner)
    if winner["reliability_ratio"] < 0.90:
        certification.degrade_endpoint(winner)
    directory.recompute_directory_listed_by_id(winner["participant_id"])
    routing.refresh_prescription_views(prescription)
    return ok(serializers.prescription(prescription))


@bp.post("/network/prescriptions/<rid>/route-fallback")
def route_fallback(rid):
    role, user_id = actor()
    allowed(role, ["Prescriber"])
    body(required=(), optional=())
    prescription = need_prescription(rid)
    same_resource(role, user_id, prescription["prescriber_id"])

    # §3.5 lists this endpoint's preconditions in order: an order that has nothing to
    # fall back on is refused for that reason, then an order with a failed attempt in
    # hand is examined for a usable channel, and only then is the routing status, which
    # the ordinary `BACKUP_SELECTION` path shares with the `ROUTE_FAILED` re-entry edge.
    failed = [a for a in db.all_rows("routing_attempts")
              if a["prescription_id"] == prescription["id"]
              and a["outcome"] in ("UNDELIVERABLE", "REJECTED")]
    if not failed:
        raise ApiError(ERR_NO_FAILED_ATTEMPT_TO_FALL_BACK)

    channel = prescription.get("fallback_channel")
    if channel not in ("FAX", "PRINT"):
        raise ApiError(ERR_FALLBACK_CHANNEL_UNAVAILABLE)
    if channel == "FAX" and not prescription.get("fax_number"):
        raise ApiError(ERR_FALLBACK_CHANNEL_UNAVAILABLE)

    if prescription["routing_status"] in ("ROUTE_FAILED", "BACKUP_SELECTION"):
        # §3.5: "The ordinary path into `FALLBACK_PENDING` is from `BACKUP_SELECTION`,
        # where no remaining endpoint in `ACTIVE` or `DEGRADED` exists, and that route
        # is refused with `ERR_NO_ROUTE_AVAILABLE` when one does." The same holds on
        # the `ROUTE_FAILED` re-entry edge: an order that still has a live endpoint to
        # nominate is routed rather than faxed.
        target_set = routing.service_set_for(prescription["transaction_type"])
        if routing.has_live_endpoint_for_set(prescription["receiving_pharmacy_id"], target_set):
            raise ApiError(ERR_NO_ROUTE_AVAILABLE)
    else:
        raise ApiError(ERR_INVALID_STATE)

    prescription["routing_status"] = "FALLBACK_PENDING"
    db.touch(prescription)
    routing.refresh_prescription_views(prescription)
    return ok(serializers.prescription(prescription))


@bp.post("/network/prescriptions/<rid>/fallback-attempts")
def create_fallback_attempt(rid):
    role, _ = actor()
    allowed(role, ["Prescriber", "HubOperator"])
    payload = body(required=("channel",), optional=())
    prescription = need_prescription(rid)
    channel = enum_value(payload["channel"], "channel", CHANNELS)
    non_network = sum(1 for a in db.all_rows("routing_attempts")
                      if a["prescription_id"] == prescription["id"] and a["channel"] != "NETWORK")
    if non_network >= FALLBACK_CHANNEL_MAX_ATTEMPTS:
        raise ApiError(ERR_FALLBACK_HOP_LIMIT_EXCEEDED)
    attempt = _create_attempt(prescription, channel, None)
    db.touch(prescription)
    return ok(serializers.routing_attempt(attempt), status=201)


@bp.post("/network/prescriptions/<rid>/cancel")
def cancel_prescription(rid):
    role, user_id = actor()
    allowed(role, ["Prescriber"])
    body(required=(), optional=())
    prescription = need_prescription(rid)
    same_resource(role, user_id, prescription["prescriber_id"])

    if prescription["clinical_status"] == "ROUTED":
        if prescription["routing_status"] not in ("ROUTED", "BACKUP_SELECTION"):
            raise ApiError(ERR_INVALID_STATE)
        routing.recompute_derived(prescription)
        if prescription["significance"] == "CRITICAL":
            raise ApiError(ERR_CRITICAL_ORDER_DELIVERY_REQUIRED)
        prescription["clinical_status"] = "CANCELLED"
        for attempt in db.all_rows("routing_attempts"):
            if attempt["prescription_id"] == prescription["id"] and attempt["outcome"] == "IN_PROGRESS":
                attempt["outcome"] = "REJECTED"
                attempt["failure_code"] = "PRESCRIPTION_CANCELLED"
                attempt["reported_at"] = clock.now_iso()
                db.touch(attempt)
        db.touch(prescription)
    elif prescription["clinical_status"] == "SIGNED":
        if prescription["routing_status"] not in ("NOT_ROUTED", "FALLBACK_PENDING"):
            raise ApiError(ERR_INVALID_STATE)
        prescription["clinical_status"] = "CANCELLED"
        prescription["routing_status"] = "NOT_ROUTED"
        db.touch(prescription)
    else:
        raise ApiError(ERR_INVALID_STATE)

    routing.refresh_prescription_views(prescription)
    return ok(serializers.prescription(prescription))


# --------------------------------------------------------------------------
# Signing sessions
# --------------------------------------------------------------------------

@bp.post("/network/signing-sessions")
def open_signing_session():
    role, user_id = actor()
    allowed(role, ["Prescriber"])
    payload = body(required=("prescription_id",), optional=())
    prescription = need_prescription(payload["prescription_id"])
    same_resource(role, user_id, prescription["prescriber_id"])

    row = db.new_resource()
    row.update({
        "prescription_id": prescription["id"],
        "prescriber_id": prescription["prescriber_id"],
        "opened_at": clock.now_iso(),
        "identity_proofing_status": "NOT_STARTED",
        "two_factor_status": "NOT_STARTED",
        "otp_challenge_code": None,
        "otp_attempt_count": 0,
        "session_status": "OPEN",
        "signed_at": None,
    })
    db.add("signing_sessions", row)
    return ok(serializers.signing_session(row), status=201)


@bp.get("/network/signing-sessions")
def list_signing_sessions():
    role, _ = actor()
    allowed(role, ["Prescriber", "NetworkOperator", "HubOperator"])
    limit, offset = page_args()
    rows = db.all_rows("signing_sessions")
    prescriber_id = request.args.get("prescriber_id")
    if prescriber_id is not None:
        rows = [r for r in rows if r["prescriber_id"] == prescriber_id]
    patient_id = request.args.get("patient_id")
    if patient_id is not None:
        rows = [r for r in rows
                if (db.get("prescriptions", r["prescription_id"]) or {}).get("patient_id") == patient_id]
    rows = created_order(rows)
    window, meta = paginate(rows, limit, offset)
    return ok([serializers.signing_session(s) for s in window], **meta)


@bp.get("/network/signing-sessions/<sid>")
def get_signing_session(sid):
    role, _ = actor()
    allowed(role, ["Prescriber", "NetworkOperator"])
    session = need_session(sid)
    return ok(serializers.signing_session(session))


@bp.post("/network/signing-sessions/<sid>/identity-proof")
def identity_proof(sid):
    role, _ = actor()
    allowed(role, ["Prescriber"])
    payload = body(required=("outcome",), optional=())
    session = need_session(sid)
    outcome = enum_value(payload["outcome"], "outcome", ("PASSED", "FAILED"))
    if session["session_status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE)

    prescription = db.get("prescriptions", session["prescription_id"])
    if prescription is not None:
        routing.recompute_derived(prescription)
        if prescription.get("is_controlled") and routing.active_attempt_id(prescription["id"]) is not None:
            raise ApiError(ERR_ROUTE_ATTEMPT_IN_PROGRESS)

    session["identity_proofing_status"] = outcome
    if outcome == "FAILED":
        session["two_factor_status"] = "FAILED"
        session["otp_challenge_code"] = None
    db.touch(session)
    return ok(serializers.signing_session(session))


@bp.post("/network/signing-sessions/<sid>/request-otp")
def request_otp(sid):
    role, _ = actor()
    allowed(role, ["Prescriber"])
    body(required=(), optional=())
    session = need_session(sid)
    if session["session_status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE)
    if session["two_factor_status"] == "LOCKED":
        raise ApiError(ERR_ACCOUNT_LOCKED)
    if session["identity_proofing_status"] != "PASSED":
        raise ApiError(ERR_IDENTITY_PROOFING_REQUIRED)

    session["otp_challenge_code"] = f"{clock.next_seq() % 1000000:06d}"
    session["two_factor_status"] = "PENDING"
    db.touch(session)
    return ok(serializers.signing_session(session))


@bp.post("/network/signing-sessions/<sid>/verify-otp")
def verify_otp(sid):
    role, _ = actor()
    allowed(role, ["Prescriber"])
    payload = body(required=("otp_code",), optional=())
    session = need_session(sid)
    if session["session_status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE)
    if session["two_factor_status"] == "LOCKED":
        raise ApiError(ERR_ACCOUNT_LOCKED)
    if session["otp_attempt_count"] >= 3:
        session["two_factor_status"] = "LOCKED"
        db.touch(session)
        raise ApiError(ERR_ACCOUNT_LOCKED)
    if session["two_factor_status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE)

    supplied = payload["otp_code"]
    if not isinstance(supplied, str):
        supplied = str(supplied)
    if supplied == session["otp_challenge_code"]:
        session["two_factor_status"] = "PASSED"
        session["otp_challenge_code"] = None
        db.touch(session)
        return ok(serializers.signing_session(session))

    session["otp_attempt_count"] += 1
    if session["otp_attempt_count"] >= 3:
        # §3.3: "when the increment carries `otp_attempt_count` to three,
        # `two_factor_status` becomes `LOCKED`" — the lock is the outcome of this
        # attempt, so the third mismatch reports the lock rather than a plain
        # invalid code.
        session["two_factor_status"] = "LOCKED"
        session["otp_challenge_code"] = None
        db.touch(session)
        raise ApiError(ERR_ACCOUNT_LOCKED)
    db.touch(session)
    raise ApiError(ERR_OTP_INVALID)


@bp.post("/network/signing-sessions/<sid>/abandon")
def abandon_session(sid):
    role, _ = actor()
    allowed(role, ["Prescriber"])
    body(required=(), optional=())
    session = need_session(sid)
    if session["session_status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE)
    session["session_status"] = "ABANDONED"
    session["otp_challenge_code"] = None
    db.touch(session)
    return ok(serializers.signing_session(session))


# --------------------------------------------------------------------------
# Routing attempt reports
# --------------------------------------------------------------------------

@bp.get("/network/routing-attempts")
def list_routing_attempts():
    role, _ = actor()
    allowed(role, ["NetworkOperator", "HubOperator", "Prescriber", "Pharmacy"])
    limit, offset = page_args()
    rows = db.all_rows("routing_attempts")
    for field in ("prescription_id", "outcome", "channel", "target_endpoint_id"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    rows = created_order(rows)
    window, meta = paginate(rows, limit, offset)
    return ok([serializers.routing_attempt(a) for a in window], **meta)


@bp.get("/network/routing-attempts/<aid>")
def get_routing_attempt(aid):
    role, _ = actor()
    allowed(role, PRESCRIPTION_ROLES)
    attempt = need_attempt(aid)
    return ok(serializers.routing_attempt(attempt))


@bp.get("/network/routing-attempts/<aid>/prescriptions")
def attempt_prescription(aid):
    role, _ = actor()
    allowed(role, PRESCRIPTION_ROLES)
    attempt = need_attempt(aid)
    prescription = db.get("prescriptions", attempt["prescription_id"])
    return ok([serializers.prescription(prescription)] if prescription else [])


def _recompute_after_report(attempt):
    if attempt.get("target_endpoint_id"):
        endpoint = db.get("endpoints", attempt["target_endpoint_id"])
        if endpoint is not None:
            directory.recompute_endpoint_counters(endpoint)
            # §2.11: "That recompute can itself move the endpoint's status, either
            # upward from `DEGRADED` or downward from `ACTIVE` subject to the coverage
            # invariant." The upward move is the explicit reactivate endpoint; the
            # downward move travels on every reported outcome, so a rejection is "a
            # real revert path rather than a dead end" (§3.5) and an acknowledged
            # report that drags the ratio below the gate degrades too (§2.6).
            if (endpoint["status"] == "ACTIVE"
                    and float(endpoint.get("reliability_ratio", 1.0)) < 0.90):
                certification.degrade_endpoint(endpoint)
            directory.recompute_directory_listed_by_id(endpoint["participant_id"])


@bp.post("/network/routing-attempts/<aid>/report-acknowledged")
def report_acknowledged(aid):
    role, _ = actor()
    allowed(role, ["NetworkOperator", "HubOperator"])
    body(required=(), optional=())
    attempt = need_attempt(aid)
    if attempt["outcome"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE)
    prescription = db.get("prescriptions", attempt["prescription_id"])
    if prescription is None:
        raise ApiError(ERR_INVALID_STATE)
    if prescription["clinical_status"] in ("CANCELLED", "REJECTED", "UNDELIVERABLE"):
        raise ApiError(ERR_INVALID_STATE)

    route_status = prescription["routing_status"]
    if route_status == "FALLBACK_SENT":
        if attempt["channel"] != "NETWORK":
            raise ApiError(ERR_INVALID_STATE)
    elif route_status not in ("ROUTED", "BACKUP_SELECTION"):
        raise ApiError(ERR_INVALID_STATE)

    doubled = any(
        a["prescription_id"] == prescription["id"]
        and a["id"] != attempt["id"]
        and a["outcome"] != "IN_PROGRESS"
        for a in db.all_rows("routing_attempts")
    )

    attempt["outcome"] = "ACKNOWLEDGED"
    attempt["reported_at"] = clock.now_iso()
    db.touch(attempt)

    prescription["clinical_status"] = "DELIVERED"
    prescription["routing_status"] = "ROUTED"
    db.touch(prescription)
    routing.refresh_prescription_views(prescription)

    correction_id = billing.accrue_report(prescription, doubled)
    attempt["correction_entry_id"] = correction_id
    db.touch(attempt, bump_version=False)
    _recompute_after_report(attempt)
    payload = serializers.routing_attempt(attempt)
    if correction_id is not None:
        # The correction row's own `fee_cents`/`period_net_total_cents` are visible on
        # its identifier (§2.7).
        correction = db.get("fee_entries", correction_id)
        if correction is not None:
            payload["correction_entry"] = billing.entry_payload(correction)
    return ok(payload)


@bp.post("/network/routing-attempts/<aid>/report-undeliverable")
def report_undeliverable(aid):
    role, _ = actor()
    allowed(role, ["NetworkOperator", "HubOperator"])
    payload = body(required=("failure_code",), optional=())
    attempt = need_attempt(aid)
    prescription = db.get("prescriptions", attempt["prescription_id"])
    if prescription is None:
        raise ApiError(ERR_INVALID_STATE)
    # §3.5: "The routing machine permits this move only while the prescription's
    # `routing_status` is `ROUTED` or `BACKUP_SELECTION`" — and the delivery edge is a
    # re-entry edge, so a network attempt may be reported undeliverable again once an
    # acknowledged report has closed it and moved the order back to `ROUTED`.
    reentrant = (attempt["outcome"] == "ACKNOWLEDGED"
                 and attempt["channel"] == "NETWORK"
                 and prescription["routing_status"] in ("ROUTED", "BACKUP_SELECTION"))
    if attempt["outcome"] != "IN_PROGRESS" and not reentrant:
        raise ApiError(ERR_INVALID_STATE)
    if prescription["clinical_status"] == "CANCELLED" and not reentrant:
        raise ApiError(ERR_INVALID_STATE)

    failure_code = string_value(payload["failure_code"], "failure_code")
    if failure_code not in UNDELIVERABLE_FAILURE_CODES:
        raise ApiError(ERR_INVALID_STATE)
    if (not prescription.get("fallback_channel")) and failure_code in FALLBACK_EXEMPT_CODES:
        raise ApiError(ERR_FALLBACK_NOT_PERMITTED)

    endpoint = db.get("endpoints", attempt.get("target_endpoint_id"))
    if not reentrant and endpoint is not None and certification.coverage_warning(endpoint):
        # §3.5's `ERR_ENDPOINT_COVERAGE_WARNING` is the shape of *this* report path's
        # answer; a report that re-enters a state the order already occupied has
        # already paid that price, so the retry is not measured against it again.
        raise ApiError(ERR_ENDPOINT_COVERAGE_WARNING)

    failed_endpoint_id = attempt.get("target_endpoint_id")
    attempt["outcome"] = "UNDELIVERABLE"
    attempt["failure_code"] = failure_code
    attempt["reported_at"] = clock.now_iso()
    db.touch(attempt)

    degraded = certification.degrade_endpoint(endpoint) if endpoint is not None else False
    _recompute_after_report(attempt)

    route_status = prescription["routing_status"]
    if route_status == "ROUTED":
        if degraded:
            # §3.5: "the endpoint's status transition is applied first, and the routing
            # move observes the post-transition state." The endpoint has been moved to
            # DEGRADED by this point, so the selector is asked for the next-best
            # candidate among the endpoints that remain live.
            winner = None
            try:
                winner = routing.select_endpoint(prescription, backup=True)
            except ApiError:
                winner = None
            if winner is not None:
                # §3.5: no new attempt row is created for this — a prescription's
                # `active_routing_attempt_id` has one-to-one cardinality, so the same
                # in-flight attempt is re-pointed at the next-ranked endpoint and the
                # endpoint that just failed is folded back into its recomputed history.
                directory.archive_report(attempt, failed_endpoint_id)
                attempt["target_endpoint_id"] = winner["id"]
                attempt["outcome"] = "IN_PROGRESS"
                attempt["failure_code"] = None
                attempt["error_code_returned"] = None
                attempt["reported_at"] = None
                prescription["routed_endpoint_id"] = winner["id"]
                prescription["routing_status"] = "BACKUP_SELECTION"
                db.touch(prescription)
            else:
                # §3.5: "When no such alternative endpoint exists, the report instead
                # drives the prescription to `ROUTE_FAILED`", and the prescription's
                # delivery outcome follows from its `fallback_channel` — the channel is
                # what carries it from there, not whether one was provisioned.
                prescription["routing_status"] = "ROUTE_FAILED"
                # §3.5: an order that had already been delivered once stays on the wire
                # so its fallback channel can carry it (that is the `FALLBACK_SENT` →
                # `ROUTED` half of the cycle); one that was never acknowledged returns to
                # the signature desk, where its `SIGNED` clinical status still admits a
                # fresh route.
                if any(a["outcome"] == "ACKNOWLEDGED"
                       for a in db.all_rows("routing_attempts")
                       if a["prescription_id"] == prescription["id"]):
                    prescription["clinical_status"] = "ROUTED"
                else:
                    prescription["clinical_status"] = "SIGNED"
                db.touch(prescription)
        else:
            # §2.11's routing machine returns the order to the wire: the attempt closed
            # as UNDELIVERABLE, so the order is no longer delivered.
            if prescription["clinical_status"] == "DELIVERED":
                prescription["clinical_status"] = "ROUTED"
                db.touch(prescription)
    elif route_status == "BACKUP_SELECTION":
        if attempt.get("target_endpoint_id") != prescription.get("routed_endpoint_id"):
            raise ApiError(ERR_ATTEMPT_PRESCRIPTION_MISMATCH)
        prescription["routing_status"] = "ROUTE_FAILED"
        db.touch(prescription)

    routing.refresh_prescription_views(prescription)
    return ok(serializers.routing_attempt(attempt))


@bp.post("/network/routing-attempts/<aid>/report-rejected")
def report_rejected(aid):
    role, _ = actor()
    allowed(role, ["NetworkOperator", "HubOperator"])
    payload = body(required=("failure_code",), optional=("error_code_returned",))
    attempt = need_attempt(aid)
    prescription = db.get("prescriptions", attempt["prescription_id"])
    if prescription is None:
        raise ApiError(ERR_INVALID_STATE)

    failure_code = string_value(payload["failure_code"], "failure_code")
    error_code_returned = payload.get("error_code_returned")
    post_delivery = (prescription["clinical_status"] == "DELIVERED"
                     and failure_code == "POST_DELIVERY")

    if post_delivery:
        pass
    else:
        if attempt["outcome"] != "IN_PROGRESS":
            raise ApiError(ERR_INVALID_STATE)
        if failure_code not in REJECTION_FAILURE_CODES:
            raise ApiError(ERR_INVALID_STATE)

    attempt["outcome"] = "REJECTED"
    attempt["failure_code"] = failure_code
    if error_code_returned is not None:
        attempt["error_code_returned"] = error_code_returned
    attempt["reported_at"] = clock.now_iso()
    db.touch(attempt)

    prescription["clinical_status"] = "REJECTED"
    if prescription["routing_status"] in ("ROUTED", "BACKUP_SELECTION",
                                          "FALLBACK_SENT", "FALLBACK_PENDING"):
        prescription["routing_status"] = "ROUTE_FAILED"
    db.touch(prescription)
    routing.refresh_prescription_views(prescription)

    _recompute_after_report(attempt)
    billing.accrue_report(prescription, False)
    return ok(serializers.routing_attempt(attempt))


@bp.post("/network/routing-attempts/<aid>/report-fallback")
def report_fallback(aid):
    role, _ = actor()
    allowed(role, ["NetworkOperator", "HubOperator"])
    payload = body(required=("outcome",), optional=("failure_code",))
    attempt = need_attempt(aid)
    if attempt["channel"] == "NETWORK":
        raise ApiError(ERR_INVALID_STATE)
    if attempt["outcome"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE)
    outcome = enum_value(payload["outcome"], "outcome", ("ACKNOWLEDGED", "UNDELIVERABLE"))

    attempt["outcome"] = outcome
    if payload.get("failure_code") is not None:
        attempt["failure_code"] = string_value(payload["failure_code"], "failure_code")
    attempt["reported_at"] = clock.now_iso()
    db.touch(attempt)

    prescription = db.get("prescriptions", attempt["prescription_id"])
    if outcome == "ACKNOWLEDGED" and prescription is not None:
        prescription["routing_status"] = "FALLBACK_SENT"
        prescription["clinical_status"] = "DELIVERED"
        db.touch(prescription)
    if prescription is not None:
        routing.refresh_prescription_views(prescription)
    return ok(serializers.routing_attempt(attempt))