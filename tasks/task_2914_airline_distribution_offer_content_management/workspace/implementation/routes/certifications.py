"""Connectivity certification, shared test environments and the airline's
decision (PRD 3.8)."""
from datetime import timedelta

from flask import Blueprint

import calc
import validators as v
from auth import (ROLE_AGENCY, ROLE_COMPLIANCE_AUDITOR, ROLE_DISTRIBUTION_MANAGER,
                  ROLE_PLATFORM_ADMIN, ROLE_TECHNOLOGY_PARTNER, authenticate)
from envelope import paginate, pagination, respond_list, respond_object
from errors import ApiError
from routing import Pending, precheck_self, resolve_owned
from serializers import certification_out, connectivity_test_out
from services import (recompute_reserved_minutes, refresh_readiness,
                      reinstate_agreements_for_pair, scheduled_tests_on_env,
                      set_partner_certification_status, suspend_agreements_for_pair,
                      tests_for_certification)
from store import bump, common_fields, db, get_or_404, sort_key

bp = Blueprint("certifications", __name__)

ENV_CODES = ("CERT_ENV_A", "CERT_ENV_B")
CERT_STATES = ("TESTING", "CERTIFIED", "SUSPENDED", "REVOKED")
TEST_STATES = ("SCHEDULED", "PASSED", "FAILED", "CANCELLED")
OUTCOMES = ("PASSED", "FAILED", "CANCELLED")
DECISIONS = ("CERTIFY", "SUSPEND", "REINSTATE", "REVOKE")
READINESS_VARIANTS = ("STRICT", "PROVISIONAL")
OPEN_CERT_STATES = ("TESTING", "CERTIFIED", "SUSPENDED")
ELIGIBLE_PARTNER_TYPES = ("TECH_PROVIDER", "TRAVEL_AGENCY")


@bp.post("/partner-certifications")
def open_certification():
    actor = authenticate([ROLE_TECHNOLOGY_PARTNER, ROLE_PLATFORM_ADMIN])
    body = v.json_body()
    precheck_self(actor, body, "partner_id")
    partner_id = v.req_string(body, "partner_id", 1, None)
    channel_id = v.req_string(body, "channel_id", 1, None)
    env_code = v.req_enum(body, "env_code", ENV_CODES)

    partner = db.partners.get(partner_id)
    if partner is None:
        raise ApiError("ERR_PARTNER_NOT_FOUND", "partner_id does not resolve.")
    channel = db.channels.get(channel_id)
    if channel is None:
        raise ApiError("ERR_CHANNEL_NOT_FOUND", "channel_id does not resolve.")

    # Step 13: one live certification per partner-and-channel pair.
    for existing in db.certifications.values():
        if (existing["partner_id"] == partner["id"]
                and existing["channel_id"] == channel["id"]
                and existing["status"] in OPEN_CERT_STATES):
            raise ApiError("ERR_CERTIFICATION_ALREADY_OPEN",
                           "A certification for this pair is already open.")
    # Step 20.
    if partner["partner_type"] not in ELIGIBLE_PARTNER_TYPES:
        raise ApiError("ERR_PARTNER_TYPE_NOT_ELIGIBLE",
                       "A CORPORATE partner may not be certified.")

    cert = common_fields()
    cert.update({
        "partner_id": partner["id"],
        "channel_id": channel["id"],
        "env_code": env_code,
        "reserved_test_minutes": 0,
        "readiness_score_strict": 0,
        "readiness_score_provisional": 0,
        "mandatory_failed_count": 0,
        "certified_variant": None,
        "tested_by_user_id": actor.user_id,
        "status": "TESTING",
    })
    db.certifications[cert["id"]] = cert
    set_partner_certification_status(partner, "IN_CERTIFICATION")
    return respond_object(certification_out(cert), 201)


@bp.get("/partner-certifications/<certification_id>")
def read_certification(certification_id):
    actor = authenticate([ROLE_PLATFORM_ADMIN, ROLE_DISTRIBUTION_MANAGER,
                          ROLE_COMPLIANCE_AUDITOR, ROLE_AGENCY,
                          ROLE_TECHNOLOGY_PARTNER])
    pending, cert = resolve_owned(db.certifications, certification_id,
                                 "ERR_CERTIFICATION_NOT_FOUND", actor)
    pending.raise_if_missing()
    return respond_object(certification_out(cert))


@bp.get("/partner-certifications")
def list_certifications():
    authenticate([ROLE_PLATFORM_ADMIN, ROLE_DISTRIBUTION_MANAGER,
                  ROLE_COMPLIANCE_AUDITOR, ROLE_TECHNOLOGY_PARTNER])
    limit, offset = pagination()
    partner_id = v.query_string("partner_id")
    channel_id = v.query_string("channel_id")
    status = v.query_enum("status", CERT_STATES)
    env_code = v.query_enum("env_code", ENV_CODES)

    rows = []
    for cert in db.certifications.values():
        if partner_id is not None and cert["partner_id"] != partner_id:
            continue
        if channel_id is not None and cert["channel_id"] != channel_id:
            continue
        if status is not None and cert["status"] != status:
            continue
        if env_code is not None and cert["env_code"] != env_code:
            continue
        rows.append(cert)
    rows.sort(key=sort_key)
    page, total = paginate(rows, limit, offset)
    return respond_list([certification_out(c) for c in page], limit, offset, total)


@bp.post("/partner-certifications/<certification_id>/connectivity-tests")
def schedule_connectivity_test(certification_id):
    actor = authenticate([ROLE_TECHNOLOGY_PARTNER])
    pending, cert = resolve_owned(db.certifications, certification_id,
                                 "ERR_CERTIFICATION_NOT_FOUND", actor)
    body = v.json_body()
    test_code = v.req_string(body, "test_code", 1, 32)
    is_mandatory = v.opt_bool(body, "is_mandatory", False)
    scheduled_start = v.req_instant(body, "scheduled_start")
    duration_minutes = v.req_int(body, "duration_minutes", 1, 240)
    pending.raise_if_missing()

    if cert["status"] != "TESTING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a certification in TESTING may schedule tests.")

    scheduled_end = scheduled_start + timedelta(minutes=duration_minutes)
    buffer_delta = timedelta(minutes=calc.TEST_TEARDOWN_BUFFER_MINUTES)
    occupants = scheduled_tests_on_env(cert["env_code"])

    # Step 25: the pairwise teardown buffer on (env_code, test_code).
    for other in occupants:
        if other["test_code"] != test_code:
            continue
        if calc.intervals_share_instant(
                scheduled_start, scheduled_end,
                other["scheduled_start"] - buffer_delta,
                other["scheduled_end"] + buffer_delta):
            raise ApiError("ERR_TEST_SLOT_CONFLICT",
                           "The slot violates the teardown buffer for %s." % test_code)

    # Step 26: aggregate environment capacity, raw closed intervals.
    overlapping = 0
    for other in occupants:
        if calc.intervals_share_instant(scheduled_start, scheduled_end,
                                        other["scheduled_start"],
                                        other["scheduled_end"]):
            overlapping += 1
    if overlapping + 1 > calc.MAX_CONCURRENT_TESTS_PER_ENV:
        raise ApiError("ERR_TEST_ENV_CAPACITY_EXCEEDED",
                       "The environment cannot hold another concurrent test.")

    test = common_fields()
    test.update({
        "certification_id": cert["id"],
        "test_code": test_code,
        "is_mandatory": is_mandatory,
        "scheduled_start": scheduled_start,
        "duration_minutes": duration_minutes,
        "scheduled_end": scheduled_end,
        "score": None,
        "status": "SCHEDULED",
    })
    db.connectivity_tests[test["id"]] = test
    cert["reserved_test_minutes"] = cert["reserved_test_minutes"] + duration_minutes
    bump(cert)
    return respond_object(connectivity_test_out(test), 201)


@bp.get("/partner-certifications/<certification_id>/connectivity-tests")
def list_connectivity_tests(certification_id):
    actor = authenticate([ROLE_PLATFORM_ADMIN, ROLE_DISTRIBUTION_MANAGER,
                          ROLE_COMPLIANCE_AUDITOR, ROLE_TECHNOLOGY_PARTNER])
    limit, offset = pagination()
    status = v.query_enum("status", TEST_STATES)
    pending, cert = resolve_owned(db.certifications, certification_id,
                                 "ERR_CERTIFICATION_NOT_FOUND", actor)
    pending.raise_if_missing()

    rows = [t for t in tests_for_certification(cert["id"])
            if status is None or t["status"] == status]
    page, total = paginate(rows, limit, offset)
    return respond_list([connectivity_test_out(t) for t in page], limit, offset, total)


@bp.post("/connectivity-tests/<test_id>/outcome")
def report_test_outcome(test_id):
    actor = authenticate([ROLE_TECHNOLOGY_PARTNER])
    pending = Pending()
    test = pending.resolve(db.connectivity_tests, test_id,
                           "ERR_CONNECTIVITY_TEST_NOT_FOUND")
    cert = db.certifications.get(test["certification_id"]) if test else None
    actor.require_owner(cert["partner_id"] if cert is not None else None)

    body = v.json_body()
    outcome = v.req_enum(body, "outcome", OUTCOMES)
    score = v.opt_int(body, "score", 0, 100)
    if outcome in ("PASSED", "FAILED") and score is None:
        v.bad("score is required on a pass or a failure.")
    pending.raise_if_missing()

    if test["status"] != "SCHEDULED" or cert["status"] != "TESTING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a SCHEDULED test on a TESTING certification may report.")

    test["status"] = outcome
    if outcome == "CANCELLED":
        # A cancellation leaves no trace in either readiness figure.
        test["score"] = None
    else:
        test["score"] = score
    bump(test)

    cert["reserved_test_minutes"] = max(
        cert["reserved_test_minutes"] - test["duration_minutes"], 0)
    if outcome == "FAILED" and test["is_mandatory"]:
        cert["mandatory_failed_count"] = cert["mandatory_failed_count"] + 1
    if outcome in ("PASSED", "FAILED"):
        refresh_readiness(cert)
    bump(cert)
    return respond_object(connectivity_test_out(test))


DECISION_LEGAL_FROM = {
    "CERTIFY": ("TESTING",),
    "SUSPEND": ("CERTIFIED",),
    "REINSTATE": ("SUSPENDED",),
    "REVOKE": ("TESTING", "CERTIFIED", "SUSPENDED"),
}


def _cancel_scheduled_tests(cert):
    for test in tests_for_certification(cert["id"]):
        if test["status"] == "SCHEDULED":
            test["status"] = "CANCELLED"
            bump(test)
    cert["reserved_test_minutes"] = 0


@bp.post("/partner-certifications/<certification_id>/decision")
def record_certification_decision(certification_id):
    authenticate([ROLE_PLATFORM_ADMIN])
    body = v.json_body()
    decision = v.req_enum(body, "decision", DECISIONS)
    readiness_variant = v.opt_enum(body, "readiness_variant", READINESS_VARIANTS,
                                   "STRICT")
    cert = get_or_404(db.certifications, certification_id,
                      "ERR_CERTIFICATION_NOT_FOUND")

    current = cert["status"]
    if current not in DECISION_LEGAL_FROM[decision]:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "%s is not legal from %s." % (decision, current))
    if decision == "CERTIFY":
        # An outstanding slot makes the decision premature.
        for test in tests_for_certification(cert["id"]):
            if test["status"] == "SCHEDULED":
                raise ApiError("ERR_INVALID_STATE_TRANSITION",
                               "A test is still SCHEDULED on this certification.")
        score = (cert["readiness_score_strict"] if readiness_variant == "STRICT"
                 else cert["readiness_score_provisional"])
        if score < calc.CERT_MIN_READINESS:
            raise ApiError("ERR_READINESS_BELOW_MINIMUM",
                           "The %s readiness score is below the minimum."
                           % readiness_variant)

    partner = db.partners[cert["partner_id"]]
    if decision == "CERTIFY":
        cert["status"] = "CERTIFIED"
        cert["certified_variant"] = readiness_variant
        bump(cert)
        set_partner_certification_status(partner, "CERTIFIED")
        reinstate_agreements_for_pair(cert["partner_id"], cert["channel_id"])
    elif decision == "SUSPEND":
        cert["status"] = "SUSPENDED"
        bump(cert)
        set_partner_certification_status(partner, "IN_CERTIFICATION")
        suspend_agreements_for_pair(cert["partner_id"], cert["channel_id"])
    elif decision == "REINSTATE":
        cert["status"] = "CERTIFIED"
        bump(cert)
        set_partner_certification_status(partner, "CERTIFIED")
        reinstate_agreements_for_pair(cert["partner_id"], cert["channel_id"])
    else:
        _cancel_scheduled_tests(cert)
        cert["status"] = "REVOKED"
        bump(cert)
        set_partner_certification_status(partner, "UNCERTIFIED")
        # Only a revocation from CERTIFIED pulls the commercial standing down.
        if current == "CERTIFIED":
            suspend_agreements_for_pair(cert["partner_id"], cert["channel_id"])
    return respond_object(certification_out(cert))
