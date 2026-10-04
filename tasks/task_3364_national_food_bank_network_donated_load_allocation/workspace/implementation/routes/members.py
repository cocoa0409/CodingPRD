"""Member food bank registration, reads, certification posture and the
member-scoped reverse-reachability collections."""

import re

from flask import Blueprint, request

import auth
import envelope
import serializers
import store
from errors import (
    ERR_INVALID_REQUEST,
    ERR_MEMBER_NOT_FOUND,
    ERR_MEMBER_NOT_PENDING,
    fail,
)
from services import audit as audit_svc
from services import members as member_svc

bp = Blueprint("members", __name__)

STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")
RESERVING_STATUSES = ("PENDING_CERTIFICATION", "CERTIFIED", "PROBATION")
TRANSPORT_ABILITIES = ("NONE", "LOCAL", "REGIONAL", "NATIONAL")
AUDIT_STATUSES = ("IN_PROGRESS", "PASSED", "FAILED")
PROGRAM_STATUSES = ("PENDING", "ACTIVE", "SUSPENDED")


def get_member_or_404(member_id):
    member = store.members.get(member_id)
    if member is None:
        fail(ERR_MEMBER_NOT_FOUND, "no member food bank matches id %s" % member_id)
    return member


@bp.route("/network/members", methods=["POST"])
def create_member():
    auth.require_roles("NetworkAdmin")
    data = auth.json_body()

    name = auth.req_str(data, "name")
    state_code = auth.req_str(data, "state_code")
    if not STATE_CODE_RE.match(state_code):
        fail(ERR_INVALID_REQUEST, "state_code must be exactly two uppercase letters")
    population = auth.req_int(data, "food_insecure_population")
    if population < 0:
        fail(ERR_INVALID_REQUEST, "food_insecure_population must be zero or greater")
    storage = auth.req_int(data, "storage_capacity_lbs")
    if storage <= 0:
        fail(ERR_INVALID_REQUEST, "storage_capacity_lbs must be strictly positive")
    refrigerated = auth.req_int(data, "refrigerated_capacity_lbs")
    if refrigerated < 0 or refrigerated > storage:
        fail(ERR_INVALID_REQUEST,
             "refrigerated_capacity_lbs must be between 0 and storage_capacity_lbs")
    transport = auth.req_enum(data, "transport_ability", TRANSPORT_ABILITIES)

    for other in store.members.values():
        if (other["state_code"] == state_code and other["name"] == name
                and other["certification_status"] in RESERVING_STATUSES):
            fail(ERR_INVALID_REQUEST,
                 "a member with this name already exists in %s" % state_code)

    member = store.new_record(
        name=name,
        state_code=state_code,
        food_insecure_population=population,
        storage_capacity_lbs=storage,
        refrigerated_capacity_lbs=refrigerated,
        transport_ability=transport,
        certification_status="PENDING_CERTIFICATION",
        share_balance=0,
        share_reserved=0,
        audit_score=0,
        last_grant_epoch=None,
        active_bid_count=0,
    )
    store.insert("members", member)
    return envelope.ok_object(serializers.member(member), 201)


@bp.route("/network/members/<member_id>", methods=["GET"])
def read_member(member_id):
    auth.require_roles("NetworkAdmin", "MemberFoodBank", "NetworkAuditor")
    return envelope.ok_object(serializers.member(get_member_or_404(member_id)))


@bp.route("/network/members/<member_id>/certify", methods=["POST"])
def certify_member(member_id):
    auth.require_roles("NetworkAdmin")
    member = get_member_or_404(member_id)
    if member["certification_status"] != "PENDING_CERTIFICATION":
        fail(ERR_MEMBER_NOT_PENDING, "member is not in PENDING_CERTIFICATION")

    latest = None
    for row in store.ordered(store.audits.values()):
        if (row["member_id"] == member["id"] and row["audit_type"] == "COMPREHENSIVE"
                and row["audit_status"] == "PASSED"):
            latest = row
    if latest is None:
        fail(ERR_INVALID_REQUEST,
             "certification requires a passed COMPREHENSIVE audit")
    if int(member["storage_capacity_lbs"]) <= 0:
        fail(ERR_INVALID_REQUEST, "storage_capacity_lbs must be strictly positive")

    member["certification_status"] = "CERTIFIED"
    member["audit_score"] = audit_svc.floor_score(latest["weighted_score"])
    store.touch(member)
    member_svc.activate_pending_programs(member, "PENDING")
    return envelope.ok_object(serializers.member(member))


@bp.route("/network/members/<member_id>/reinstate", methods=["POST"])
def reinstate_member(member_id):
    auth.require_roles("NetworkAdmin")
    member = get_member_or_404(member_id)
    status = member["certification_status"]
    if status not in ("PROBATION", "SUSPENDED"):
        fail(ERR_MEMBER_NOT_PENDING,
             "reinstatement requires a member in PROBATION or SUSPENDED")

    if int(member["audit_score"]) < audit_svc.AUDIT_PASS_THRESHOLD:
        fail(ERR_INVALID_REQUEST, "reinstatement requires an audit_score of at least 85")
    if status == "PROBATION":
        if int(member["share_balance"]) < 100:
            fail(ERR_INVALID_REQUEST,
                 "reinstatement to CERTIFIED requires at least 100 shares")

    if status == "PROBATION":
        member["certification_status"] = "CERTIFIED"
        store.touch(member)
        member_svc.activate_pending_programs(member, "SUSPENDED")
    else:
        member["certification_status"] = "PROBATION"
        store.touch(member)
    return envelope.ok_object(serializers.member(member))


@bp.route("/network/members/<member_id>/audits", methods=["GET"])
def list_member_audits(member_id):
    auth.require_roles("NetworkAdmin", "MemberFoodBank", "NetworkAuditor")
    member = get_member_or_404(member_id)
    rows = [a for a in store.ordered(store.audits.values()) if a["member_id"] == member["id"]]
    status_filter = request.args.get("audit_status")
    if status_filter:
        rows = [a for a in rows if a["audit_status"] == status_filter]
    page, limit, offset, total = auth.paginate(rows)
    return envelope.ok_array([serializers.audit(a) for a in page], limit, offset, total)


@bp.route("/network/members/<member_id>/share-ledger", methods=["GET"])
def list_member_ledger(member_id):
    auth.require_roles("NetworkAdmin", "MemberFoodBank")
    member = get_member_or_404(member_id)
    rows = [e for e in store.ordered(store.ledger.values()) if e["member_id"] == member["id"]]
    epoch = request.args.get("epoch")
    if epoch:
        rows = [e for e in rows if e["epoch"] == epoch]
    page, limit, offset, total = auth.paginate(rows)
    return envelope.ok_array([serializers.ledger_entry(e) for e in page], limit, offset, total)


@bp.route("/network/members/<member_id>/store-programs", methods=["GET"])
def list_member_programs(member_id):
    auth.require_roles("NetworkAdmin", "MemberFoodBank")
    member = get_member_or_404(member_id)
    rows = [p for p in store.ordered(store.programs.values()) if p["member_id"] == member["id"]]
    status_filter = request.args.get("program_status")
    if status_filter:
        rows = [p for p in rows if p["program_status"] == status_filter]
    page, limit, offset, total = auth.paginate(rows)
    return envelope.ok_array([serializers.program(p) for p in page], limit, offset, total)
