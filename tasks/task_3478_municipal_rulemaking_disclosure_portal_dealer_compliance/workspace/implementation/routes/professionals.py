"""Municipal professional registration, standing, CE credits, and exam attempts."""
from datetime import timedelta

from flask import Blueprint, request

import serializers
import services
import store
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_ORG_NOT_FOUND,
    ERR_ORG_SUSPENDED,
    ERR_ORG_TYPE_NOT_PERMITTED,
    ERR_PROFESSIONAL_NOT_FOUND,
    ERR_RETAKE_WINDOW_ACTIVE,
)
from respond import ok, ok_list
from validators import (
    get_body,
    opt_str,
    paginate,
    req_enum,
    req_int,
    req_number,
    req_str,
    require_auth,
    require_role,
    _bad,
)

bp = Blueprint("professionals", __name__)

PROFESSIONAL_CLASSES = (
    "MUNICIPAL_DEALER_REP",
    "MUNICIPAL_ADVISOR_REP",
    "MUNICIPAL_PRINCIPAL",
)
SERIES_CODES = ("MSRB_50", "MSRB_52", "MSRB_53", "MSRB_54")
EMPLOYER_ORG_TYPES = ("BROKER_DEALER", "MUNICIPAL_ADVISOR")
PROFESSIONAL_READ_ROLES = ("ExamAdmin", "ComplianceOfficer")


def _get_professional(professional_id):
    prof = store.professionals.get(professional_id)
    if prof is None:
        raise ApiError(ERR_PROFESSIONAL_NOT_FOUND, "Municipal professional not found.", 404)
    return prof


@bp.route("/msrb/professionals", methods=["POST"])
def create_professional():
    _uid, role = require_auth()
    require_role(role, ("ExamAdmin",))
    body = get_body()
    full_name = req_str(body, "full_name")
    employer_org_id = req_str(body, "employer_org_id")
    professional_class = req_enum(body, "professional_class", PROFESSIONAL_CLASSES)
    org = store.organizations.get(employer_org_id)
    if org is None:
        raise ApiError(ERR_ORG_NOT_FOUND, "employer_org_id does not exist.", 404)
    if org["status"] != "ACTIVE":
        raise ApiError(ERR_ORG_SUSPENDED, "The employer organization is SUSPENDED.", 409)
    if org["org_type"] not in EMPLOYER_ORG_TYPES:
        raise ApiError(
            ERR_ORG_TYPE_NOT_PERMITTED,
            "Professional employer must be BROKER_DEALER or MUNICIPAL_ADVISOR.",
            422,
        )
    now = store.now()
    prof = {
        "id": store.new_id(),
        "full_name": full_name,
        "employer_org_id": employer_org_id,
        "professional_class": professional_class,
        "qualification_status": "UNQUALIFIED",
        "standing": "ACTIVE",
        "qualified_at": None,
        "ce_cycle_end": None,
        "ce_grace_end": None,
        "ce_credits_total": 0,
        "ce_ethics_credits": 0,
        "may_transact": False,
        "_lapsed_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.professionals[prof["id"]] = prof
    org["active_professional_count"] += 1
    return ok(serializers.professional(prof), 201)


@bp.route("/msrb/professionals", methods=["GET"])
def list_professionals():
    _uid, role = require_auth()
    require_role(role, PROFESSIONAL_READ_ROLES)
    items = list(store.professionals.values())
    employer_filter = request.args.get("employer_org_id")
    if employer_filter is not None:
        items = [m for m in items if m["employer_org_id"] == employer_filter]
    qualification_filter = request.args.get("qualification_status")
    if qualification_filter is not None:
        items = [m for m in items if m["qualification_status"] == qualification_filter]
    items.sort(key=lambda m: m["created_at"])
    page, limit, offset, total = paginate(items)
    return ok_list([serializers.professional(m) for m in page], limit, offset, total)


@bp.route("/msrb/professionals/<professional_id>", methods=["GET"])
def get_professional(professional_id):
    _uid, role = require_auth()
    require_role(role, PROFESSIONAL_READ_ROLES)
    return ok(serializers.professional(_get_professional(professional_id)), 200)


@bp.route("/msrb/professionals/<professional_id>/standing", methods=["POST"])
def set_standing(professional_id):
    _uid, role = require_auth()
    require_role(role, ("ComplianceOfficer",))
    body = get_body()
    standing = req_enum(body, "standing", ("ACTIVE", "SUSPENDED"))
    opt_str(body, "reason")  # accepted, not persisted (no such field)
    prof = _get_professional(professional_id)
    if prof["standing"] == standing:
        raise ApiError(
            ERR_INVALID_STATE,
            "Professional standing is already %s." % standing,
            409,
        )
    org = store.organizations.get(prof["employer_org_id"])
    prof["standing"] = standing
    if org is not None:
        if standing == "SUSPENDED":
            org["active_professional_count"] -= 1
        else:
            org["active_professional_count"] += 1
    services.recompute_may_transact(prof)
    services.bump(prof)
    return ok(serializers.professional(prof), 200)


@bp.route("/msrb/professionals/<professional_id>/ce-credits", methods=["POST"])
def record_ce_credits(professional_id):
    _uid, role = require_auth()
    require_role(role, ("ExamAdmin",))
    body = get_body()
    credits_total = req_number(body, "credits_total")
    ethics_credits = req_number(body, "ethics_credits")
    prof = _get_professional(professional_id)
    if prof["qualification_status"] not in ("QUALIFIED", "CE_DUE"):
        raise ApiError(
            ERR_INVALID_STATE,
            "CE credits may be recorded only while QUALIFIED or CE_DUE.",
            409,
        )
    prof["ce_credits_total"] += credits_total
    prof["ce_ethics_credits"] += ethics_credits
    if (
        prof["qualification_status"] == "CE_DUE"
        and prof["ce_credits_total"] >= services.CE_TOTAL_REQUIRED
        and prof["ce_ethics_credits"] >= services.CE_ETHICS_REQUIRED
    ):
        # Cure satisfies the current cycle only: anchors are unchanged.
        prof["qualification_status"] = "QUALIFIED"
        services.recompute_may_transact(prof)
    services.bump(prof)
    return ok(serializers.professional(prof), 200)


@bp.route("/msrb/exam-attempts", methods=["POST"])
def create_exam_attempt():
    _uid, role = require_auth()
    require_role(role, ("ExamAdmin",))
    body = get_body()
    professional_id = req_str(body, "professional_id")
    series_code = req_enum(body, "series_code", SERIES_CODES)
    score = req_int(body, "score")
    if not (0 <= score <= 100):
        raise _bad("score must be an integer in [0, 100].")
    prof = store.professionals.get(professional_id)
    if prof is None:
        raise ApiError(ERR_PROFESSIONAL_NOT_FOUND, "professional_id does not exist.", 404)
    employer = store.organizations.get(prof["employer_org_id"])
    if employer is not None and employer["status"] != "ACTIVE":
        raise ApiError(
            ERR_ORG_SUSPENDED, "The professional's employer organization is SUSPENDED.", 409
        )
    if prof["standing"] != "ACTIVE":
        raise ApiError(
            ERR_INVALID_STATE,
            "A SUSPENDED professional may not sit examinations.",
            409,
        )
    now = store.now()
    retake_threshold = now - timedelta(days=services.RETAKE_WINDOW_DAYS)
    for attempt in store.exam_attempts.values():
        if (
            attempt["professional_id"] == professional_id
            and attempt["series_code"] == series_code
            and attempt["created_at"] > retake_threshold
        ):
            raise ApiError(
                ERR_RETAKE_WINDOW_ACTIVE,
                "A prior attempt on this (professional, series) pair is younger than 30 days.",
                422,
            )
    result = "PASS" if score >= services.PASS_SCORES[series_code] else "FAIL"
    attempt = {
        "id": store.new_id(),
        "professional_id": professional_id,
        "series_code": series_code,
        "score": score,
        "result": result,
        "created_at": now,
    }
    store.exam_attempts[attempt["id"]] = attempt
    required = services.REQUIRED_SERIES[prof["professional_class"]]
    if prof["qualification_status"] == "UNQUALIFIED":
        passed = {
            a["series_code"]
            for a in store.exam_attempts.values()
            if a["professional_id"] == professional_id and a["result"] == "PASS"
        }
        if all(series in passed for series in required):
            services.qualify(prof)
    elif prof["qualification_status"] == "LAPSED":
        # Only attempts recorded after the lapse timestamp count.
        lapsed_at = prof["_lapsed_at"]
        passed = {
            a["series_code"]
            for a in store.exam_attempts.values()
            if a["professional_id"] == professional_id
            and a["result"] == "PASS"
            and (lapsed_at is None or a["created_at"] > lapsed_at)
        }
        if all(series in passed for series in required):
            services.qualify(prof)
    return ok(serializers.exam_attempt(attempt), 201)


@bp.route("/msrb/professionals/<professional_id>/exam-attempts", methods=["GET"])
def list_exam_attempts(professional_id):
    _uid, role = require_auth()
    require_role(role, PROFESSIONAL_READ_ROLES)
    _get_professional(professional_id)
    items = [
        a for a in store.exam_attempts.values() if a["professional_id"] == professional_id
    ]
    series_filter = request.args.get("series_code")
    if series_filter is not None:
        items = [a for a in items if a["series_code"] == series_filter]
    items.sort(key=lambda a: a["created_at"])
    page, limit, offset, total = paginate(items)
    return ok_list([serializers.exam_attempt(a) for a in page], limit, offset, total)
