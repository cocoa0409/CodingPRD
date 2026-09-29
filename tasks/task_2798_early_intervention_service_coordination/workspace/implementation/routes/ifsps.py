"""IFSP authoring and parental consent."""
from flask import Blueprint, g, request

import domain as D
from auth import STAFF_READ, endpoint, require_owner
from envelope import paginate, single
from errors import fail
from helpers import get_ifsp, get_referral, not_future, ser_ifsp
from services import cascades, compute
from store import db, flush, mark, new_row, ordered, set_field, set_fields
from validate import (Field, parse_body, v_date, v_enum, v_id, v_int, v_list,
                      v_str)

bp = Blueprint("ifsps", __name__)

IFSP_AUTHORING_STATUSES = ("IFSP_PENDING", "ACTIVE_SERVICES")


@bp.route("/ei/ifsps", methods=["POST"])
@endpoint(["ProgramAdmin"])
def create_ifsp():
    payload = parse_body([
        Field("referral_id", v_id()),
        Field("ifsp_type", v_enum(D.IFSP_TYPES)),
        Field("meeting_date", v_date()),
        Field("authoring_coordinator_id", v_id()),
        Field("expected_referral_version", v_int(1)),
        Field("supersedes_ifsp_id", v_id(), required=False),
        Field("natural_environment_justification", v_str(20), required=False),
    ])
    referral = get_referral(payload["referral_id"])
    target = None
    if payload["supersedes_ifsp_id"] is not None:
        target = get_ifsp(payload["supersedes_ifsp_id"])
    if referral["version"] != payload["expected_referral_version"]:
        fail("ERR_STALE_REFERRAL_VERSION",
             "The case has been modified since version "
             "%s was observed." % payload["expected_referral_version"])
    if referral["status"] not in IFSP_AUTHORING_STATUSES:
        fail("ERR_REFERRAL_STATE_INVALID",
             "A plan cannot be authored against a case in status "
             "'%s'." % referral["status"])
    _check_supersede(referral, payload["ifsp_type"], target)
    not_future(payload["meeting_date"], "meeting_date")
    plan = new_row({
        "referral_id": referral["id"],
        "ifsp_type": payload["ifsp_type"],
        "meeting_date": payload["meeting_date"],
        "supersedes_ifsp_id": payload["supersedes_ifsp_id"],
        "authoring_coordinator_id": payload["authoring_coordinator_id"],
        "natural_environment_justification":
            payload["natural_environment_justification"],
        "status": "DRAFT",
        "consent_scope": None,
        "consent_signed_date": None,
        "consent_user_id": None,
        "activated_date": None,
        "service_line_count": 0,
        "non_natural_setting_line_count": 0,
    })
    db.ifsps[plan["id"]] = plan
    if plan["ifsp_type"] == "INITIAL":
        compute.recompute_initial_meeting_date(referral)
        compute.recompute_timeline(referral)
    mark(referral, bump=True)
    flush()
    return single(ser_ifsp(plan), 201)


def _check_supersede(referral, ifsp_type, target):
    if ifsp_type == "ANNUAL":
        if target is None:
            fail("ERR_SUPERSEDE_TARGET_INVALID",
                 "An ANNUAL plan must name the plan it supersedes.")
    elif target is not None:
        fail("ERR_SUPERSEDE_TARGET_INVALID",
             "An INITIAL plan may not supersede another plan.")
    if target is None:
        return
    if target["referral_id"] != referral["id"]:
        fail("ERR_SUPERSEDE_TARGET_INVALID",
             "The superseded plan belongs to a different case.")
    if target["status"] != "ACTIVE":
        fail("ERR_SUPERSEDE_TARGET_INVALID",
             "Only an ACTIVE plan may be superseded.")
    for other in ordered(db.ifsps):
        if (other["supersedes_ifsp_id"] == target["id"]
                and other["status"] != "WITHDRAWN"):
            fail("ERR_SUPERSEDE_TARGET_INVALID",
                 "That plan is already claimed by another successor.")


@bp.route("/ei/ifsps/<ifsp_id>", methods=["GET"])
@endpoint(STAFF_READ)
def read_ifsp(ifsp_id):
    return single(ser_ifsp(get_ifsp(ifsp_id)))


@bp.route("/ei/ifsps", methods=["GET"])
@endpoint(STAFF_READ)
def list_ifsps():
    rows = ordered(db.ifsps)
    referral_id = request.args.get("referral_id")
    supersedes_ifsp_id = request.args.get("supersedes_ifsp_id")
    authoring_coordinator_id = request.args.get("authoring_coordinator_id")
    status = request.args.get("status")
    if referral_id is not None:
        rows = [r for r in rows if r["referral_id"] == referral_id]
    if supersedes_ifsp_id is not None:
        rows = [r for r in rows if r["supersedes_ifsp_id"] == supersedes_ifsp_id]
    if authoring_coordinator_id is not None:
        rows = [r for r in rows
                if r["authoring_coordinator_id"] == authoring_coordinator_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, ser_ifsp)


@bp.route("/ei/ifsps/<ifsp_id>/consent", methods=["POST"])
@endpoint(["FamilyRepresentative"])
def consent_ifsp(ifsp_id):
    payload = parse_body([
        Field("consent_scope", v_enum(D.CONSENT_SCOPES)),
        Field("consent_signed_date", v_date()),
        Field("declined_service_ids", v_list(v_id()), required=False),
    ])
    plan = get_ifsp(ifsp_id)
    referral = db.referrals.get(plan["referral_id"])
    require_owner(referral["child_id"] if referral else None)
    if plan["status"] not in ("PENDING_CONSENT", "AMENDMENT_PENDING"):
        fail("ERR_IFSP_STATE_INVALID",
             "Consent may only be recorded on a plan awaiting it.")
    if plan["non_natural_setting_line_count"] > 0:
        justification = plan["natural_environment_justification"]
        if not justification or len(justification) < 20:
            fail("ERR_NATURAL_ENVIRONMENT_JUSTIFICATION_REQUIRED",
                 "A plan offering clinic or office services requires a "
                 "plan-level natural environment justification.")
    declined = []
    if payload["consent_scope"] == "PARTIAL":
        declined = payload["declined_service_ids"] or []
        plan_line_ids = [l["id"] for l in compute.ifsp_lines(plan["id"])]
        live_ids = [l["id"] for l in compute.ifsp_lines(plan["id"])
                    if l["status"] != "DISCONTINUED"]
        if not declined:
            fail("ERR_ALL_SERVICES_DECLINED",
                 "A partial consent must name the declined service lines.")
        if any(sid not in plan_line_ids for sid in declined):
            fail("ERR_ALL_SERVICES_DECLINED",
                 "A declined service line does not belong to this plan.")
        if not [sid for sid in live_ids if sid not in declined]:
            fail("ERR_ALL_SERVICES_DECLINED",
                 "A partial consent must leave at least one service line "
                 "in place.")
    not_future(payload["consent_signed_date"], "consent_signed_date")
    set_fields(plan, {
        "status": "ACTIVE",
        "consent_scope": payload["consent_scope"],
        "consent_signed_date": payload["consent_signed_date"],
        "consent_user_id": g.user_id,
        "activated_date": payload["consent_signed_date"],
    })
    for line in compute.ifsp_lines(plan["id"]):
        if line["id"] not in declined:
            continue
        set_fields(line, {
            "declined_by_family": True,
            "status": "DISCONTINUED",
        })
        compute.recompute_line_pool(line)
    compute.recompute_ifsp_counts(plan)
    if plan["supersedes_ifsp_id"]:
        prior = db.ifsps.get(plan["supersedes_ifsp_id"])
        if prior is not None and prior["status"] == "ACTIVE":
            cascades.supersede_plan(prior)
    if referral is not None:
        if plan["ifsp_type"] == "INITIAL" and referral["status"] == "IFSP_PENDING":
            set_fields(referral, {
                "status": "ACTIVE_SERVICES",
                "services_start_date": payload["consent_signed_date"],
            }, bump=False)
        compute.recompute_case_weight(referral)
        compute.recompute_monthly_contact(referral)
        compute.recompute_service_gap(referral)
        compute.recompute_coordinator(
            db.coordinators.get(referral["coordinator_id"]))
    flush()
    return single(ser_ifsp(plan))
