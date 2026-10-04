"""Enforcement referrals (with examining-authority routing and interpretation
guidance) and the append-only solicitation ledger (fiduciary standard)."""
from flask import Blueprint, request

import serializers
import services
import store
from errors import (
    ApiError,
    ERR_AMBIGUOUS_SUBJECT,
    ERR_DISCLOSURE_REQUIRED,
    ERR_FEE_CAP_EXCEEDED,
    ERR_INVALID_STATE,
    ERR_ORG_NOT_FOUND,
    ERR_ORG_SUSPENDED,
    ERR_ORG_TYPE_NOT_PERMITTED,
    ERR_PROFESSIONAL_NOT_FOUND,
    ERR_REFERRAL_NOT_FOUND,
    ERR_RULE_NOT_EFFECTIVE,
    ERR_RULE_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES,
)
from respond import ok, ok_list
from validators import (
    forbid_cross_org,
    get_body,
    opt_str,
    paginate,
    req_bool,
    req_enum,
    req_int,
    req_nonempty_str,
    req_str,
    require_auth,
    require_role,
    _bad,
)

bp = Blueprint("enforcement", __name__)

REFERRAL_SUBJECT_ORG_TYPES = ("BROKER_DEALER", "MUNICIPAL_ADVISOR")
REFERRAL_READ_ROLES = ("ComplianceOfficer", "Regulator")
COMPENSATION_TYPES = ("FIXED", "HOURLY", "CONTINGENT")
CONTINGENT_FEE_CAP_CENTS = 2500000

CLOSE_STATES = ("CLOSED_ACTION_TAKEN", "CLOSED_NO_ACTION")


@bp.route("/msrb/enforcement-referrals", methods=["POST"])
def create_referral():
    uid, role = require_auth()
    require_role(role, ("ComplianceOfficer",))
    body = get_body()
    rule_code = req_str(body, "rule_code")
    violation_summary = req_str(body, "violation_summary")
    subject_org_id = opt_str(body, "subject_org_id")
    subject_professional_id = opt_str(body, "subject_professional_id")
    # Priority 5: body-referenced existence (subjects first, then rule_code).
    subject_org = None
    if subject_org_id is not None:
        subject_org = store.organizations.get(subject_org_id)
        if subject_org is None:
            raise ApiError(ERR_ORG_NOT_FOUND, "subject_org_id does not exist.", 404)
    subject_professional = None
    if subject_professional_id is not None:
        subject_professional = store.professionals.get(subject_professional_id)
        if subject_professional is None:
            raise ApiError(
                ERR_PROFESSIONAL_NOT_FOUND,
                "subject_professional_id does not exist.",
                404,
            )
    proposal = None
    for candidate in store.rule_proposals.values():
        if candidate["rule_code"] == rule_code:
            proposal = candidate
            break
    if proposal is None:
        raise ApiError(
            ERR_RULE_NOT_FOUND, "rule_code matches no existing rule proposal.", 404
        )
    # Priority 19: a subject organization must be BROKER_DEALER or MUNICIPAL_ADVISOR.
    if subject_org is not None and subject_org["org_type"] not in REFERRAL_SUBJECT_ORG_TYPES:
        raise ApiError(
            ERR_ORG_TYPE_NOT_PERMITTED,
            "Referral subject organization must be BROKER_DEALER or MUNICIPAL_ADVISOR.",
            422,
        )
    # Priority 20: exactly one subject must be set.
    if (subject_org_id is None) == (subject_professional_id is None):
        raise ApiError(
            ERR_AMBIGUOUS_SUBJECT,
            "Exactly one of subject_org_id / subject_professional_id must be set.",
            422,
        )
    # Priority 21: the cited rule must be EFFECTIVE.
    if proposal["status"] != "EFFECTIVE":
        raise ApiError(
            ERR_RULE_NOT_EFFECTIVE,
            "The cited rule proposal is not EFFECTIVE.",
            422,
        )
    # calculations.examining_authority_selection.
    if subject_org is not None:
        subject_org_type = subject_org["org_type"]
    else:
        employer = store.organizations.get(subject_professional["employer_org_id"])
        subject_org_type = employer["org_type"] if employer is not None else None
    if subject_org_type == "BROKER_DEALER":
        examining_authority = "DEALER_EXAM_AUTHORITY"
    else:
        examining_authority = "ADVISOR_EXAM_AUTHORITY"
    now = store.now()
    referral = {
        "id": store.new_id(),
        "rule_code": rule_code,
        "subject_org_id": subject_org_id,
        "subject_professional_id": subject_professional_id,
        "violation_summary": violation_summary,
        "examining_authority": examining_authority,
        "status": "OPEN",
        "created_by_user_id": uid,
        "referred_at": None,
        "closed_by_user_id": None,
        "closure_notes": None,
        "guidance_text": None,
        "needs_rule_review": False,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.enforcement_referrals[referral["id"]] = referral
    return ok(serializers.enforcement_referral(referral), 201)


@bp.route("/msrb/enforcement-referrals", methods=["GET"])
def list_referrals():
    _uid, role = require_auth()
    require_role(role, REFERRAL_READ_ROLES)
    items = list(store.enforcement_referrals.values())
    org_filter = request.args.get("subject_org_id")
    if org_filter is not None:
        items = [r for r in items if r["subject_org_id"] == org_filter]
    prof_filter = request.args.get("subject_professional_id")
    if prof_filter is not None:
        items = [r for r in items if r["subject_professional_id"] == prof_filter]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [r for r in items if r["status"] == status_filter]
    items.sort(key=lambda r: r["created_at"])
    page, limit, offset, total = paginate(items)
    return ok_list(
        [serializers.enforcement_referral(r) for r in page], limit, offset, total
    )


@bp.route("/msrb/enforcement-referrals/<referral_id>", methods=["GET"])
def get_referral(referral_id):
    _uid, role = require_auth()
    require_role(role, REFERRAL_READ_ROLES)
    referral = store.enforcement_referrals.get(referral_id)
    if referral is None:
        raise ApiError(ERR_REFERRAL_NOT_FOUND, "Enforcement referral not found.", 404)
    return ok(serializers.enforcement_referral(referral), 200)


@bp.route("/msrb/enforcement-referrals/<referral_id>/advance", methods=["POST"])
def advance_referral(referral_id):
    uid, role = require_auth()
    require_role(role, ("ComplianceOfficer",))
    body = get_body()
    to_state = req_enum(body, "to_state", ("REFERRED",) + CLOSE_STATES)
    guidance_text = None
    if to_state == "CLOSED_ACTION_TAKEN":
        guidance_text = req_nonempty_str(body, "guidance_text")
    closure_notes = opt_str(body, "closure_notes")
    referral = store.enforcement_referrals.get(referral_id)
    if referral is None:
        raise ApiError(ERR_REFERRAL_NOT_FOUND, "Enforcement referral not found.", 404)
    # Segregation of duties (close transitions only), priority 6 — before the
    # generic state gate at priority 7.
    if to_state in CLOSE_STATES and uid == referral["created_by_user_id"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            "The closing ComplianceOfficer must differ from the referral's creator.",
            403,
        )
    current = referral["status"]
    if current == "OPEN" and to_state == "REFERRED":
        referral["status"] = "REFERRED"
        referral["referred_at"] = store.now()
    elif current == "REFERRED" and to_state in CLOSE_STATES:
        referral["status"] = to_state
        referral["closed_by_user_id"] = uid
        if closure_notes is not None:
            referral["closure_notes"] = closure_notes
        if to_state == "CLOSED_ACTION_TAKEN":
            referral["guidance_text"] = guidance_text
    else:
        raise ApiError(
            ERR_INVALID_STATE,
            "Referral cannot advance from %s to %s." % (current, to_state),
            409,
        )
    services.bump(referral)
    return ok(serializers.enforcement_referral(referral), 200)


@bp.route("/msrb/solicitation-records", methods=["POST"])
def create_solicitation_record():
    uid, role = require_auth()
    require_role(role, ("DealerRep",))
    body = get_body()
    # Priority 2 ownership: DealerRep's X-User-ID must equal advisor_org_id.
    forbid_cross_org(uid, body.get("advisor_org_id"))
    # Priority 3 schema checks.
    municipal_entity_name = req_str(body, "municipal_entity_name")
    compensation_type = req_enum(body, "compensation_type", COMPENSATION_TYPES)
    compensation_cents = req_int(body, "compensation_cents")
    if compensation_cents < 0:
        raise _bad("compensation_cents must be >= 0.")
    disclosure_provided = req_bool(body, "disclosure_provided")
    advisor_org_id = req_str(body, "advisor_org_id")
    # Priority 5: referenced organization must exist.
    org = store.organizations.get(advisor_org_id)
    if org is None:
        raise ApiError(ERR_ORG_NOT_FOUND, "advisor_org_id does not exist.", 404)
    # Priority 10: organization must be ACTIVE.
    if org["status"] != "ACTIVE":
        raise ApiError(ERR_ORG_SUSPENDED, "The advisor organization is SUSPENDED.", 409)
    # Priority 12: fiduciary compensation disclosure is mandatory.
    if not disclosure_provided:
        raise ApiError(
            ERR_DISCLOSURE_REQUIRED,
            "The fiduciary compensation disclosure must be delivered to the municipal entity.",
            422,
        )
    # Priority 19: advisor type gate.
    if org["org_type"] != "MUNICIPAL_ADVISOR":
        raise ApiError(
            ERR_ORG_TYPE_NOT_PERMITTED,
            "Solicitation advisor must be a MUNICIPAL_ADVISOR.",
            422,
        )
    # Priority 23: contingent-fee cap.
    if (
        compensation_type == "CONTINGENT"
        and compensation_cents > CONTINGENT_FEE_CAP_CENTS
    ):
        raise ApiError(
            ERR_FEE_CAP_EXCEEDED,
            "CONTINGENT compensation may not exceed 2500000 cents.",
            422,
        )
    record = {
        "id": store.new_id(),
        "advisor_org_id": advisor_org_id,
        "municipal_entity_name": municipal_entity_name,
        "compensation_type": compensation_type,
        "compensation_cents": compensation_cents,
        "disclosure_provided": disclosure_provided,
        "created_at": store.now(),
    }
    store.solicitation_records[record["id"]] = record
    return ok(serializers.solicitation_record(record), 201)
