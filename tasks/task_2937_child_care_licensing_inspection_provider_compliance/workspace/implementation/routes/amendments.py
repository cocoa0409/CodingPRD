"""Licence amendments and their effect on the licence record (PRD §3.9)."""

from flask import Blueprint, request

import clock
import constants as K
import derive
import envelope
import helpers
import serialize
import store
import validate
from auth import authenticate, require_provider_owner
from errors import ApiError
from validate import F

bp = Blueprint("amendments", __name__)

AMENDMENT_READERS = ("AgencyAdmin", "Applicant", "LicensingSupervisor")

CAPACITY_TYPES = ("CAPACITY_INCREASE", "CAPACITY_DECREASE")

REQUIRED_BY_TYPE = {
    "CAPACITY_INCREASE": ("requested_capacity",),
    "CAPACITY_DECREASE": ("requested_capacity",),
    "SITE_MOVE": ("new_site_address",),
    "AGE_GROUP_ADD": ("new_age_group", "new_group_size"),
    "DIRECTOR_CHANGE": ("new_director_staff_member_id",),
}


@bp.post("/licensing/license-amendments")
def request_amendment():
    user_id, role = authenticate(("Applicant",))
    vals = validate.body(
        [
            F("provider_id", "string", required=True),
            F("amendment_type", "enum", required=True, values=K.AMENDMENT_TYPES),
            F("expected_provider_version", "int", required=True),
            F("requested_capacity", "int", min_val=1),
            F("new_site_address", "string", min_len=1, max_len=300, not_blank=True),
            F("new_age_group", "enum", values=K.AGE_GROUPS),
            F("new_group_size", "int", min_val=1),
            F("new_director_staff_member_id", "string"),
        ]
    )
    amendment_type = vals["amendment_type"]
    for name in REQUIRED_BY_TYPE[amendment_type]:
        if vals.get(name) is None:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "Field '%s' is required for a %s amendment." % (name, amendment_type),
            )
    provider = helpers.need("provider", vals["provider_id"])
    director = None
    if vals.get("new_director_staff_member_id") is not None:
        director = helpers.need("staff_member", vals["new_director_staff_member_id"])
    require_provider_owner(role, user_id, provider["id"])
    if vals["expected_provider_version"] != provider["version"]:
        raise ApiError(
            "ERR_STALE_PROVIDER_VERSION",
            "expected_provider_version does not match the provider's current version.",
        )

    if amendment_type in CAPACITY_TYPES:
        delta = vals["requested_capacity"] - provider["licensed_capacity"]
    elif amendment_type == "AGE_GROUP_ADD":
        delta = vals["new_group_size"]
    else:
        delta = 0
    requires_inspection = amendment_type in ("SITE_MOVE", "AGE_GROUP_ADD") or (
        amendment_type in CAPACITY_TYPES and delta > 0
    )

    for other in store.by_provider(store.amendments, provider["id"]):
        if other["amendment_type"] == amendment_type and other["status"] in (
            "SUBMITTED",
            "PRE_INSPECTION_REQUIRED",
        ):
            other["status"] = "SUPERSEDED"
            other["decided_at"] = clock.now()
            store.touch(other)

    record = {
        "provider_id": provider["id"],
        "pre_move_inspection_id": None,
        "new_director_staff_member_id": director["id"] if director else None,
        "amendment_type": amendment_type,
        "requested_capacity": vals.get("requested_capacity"),
        "new_site_address": vals.get("new_site_address"),
        "new_age_group": vals.get("new_age_group"),
        "new_group_size": vals.get("new_group_size"),
        "requires_inspection": requires_inspection,
        "status": "PRE_INSPECTION_REQUIRED" if requires_inspection else "SUBMITTED",
        "submitted_at": clock.now(),
        "decided_at": None,
        "decision_rationale": None,
        "effective_capacity_delta": delta,
        "expected_provider_version": vals["expected_provider_version"],
    }
    store.create(store.amendments, record)
    store.touch(provider)
    return envelope.created(serialize.amendment(record))


@bp.get("/licensing/license-amendments")
def list_amendments():
    authenticate(AMENDMENT_READERS)
    limit, offset = envelope.pagination(request.args)
    status = validate.query_enum("status", K.AMENDMENT_STATUSES)
    amendment_type = validate.query_enum("amendment_type", K.AMENDMENT_TYPES)
    provider_id = validate.query_str("provider_id")
    inspection_id = validate.query_str("pre_move_inspection_id")
    director_id = validate.query_str("new_director_staff_member_id")
    rows = store.ordered(store.amendments)
    if provider_id is not None:
        rows = [r for r in rows if r["provider_id"] == provider_id]
    if inspection_id is not None:
        rows = [r for r in rows if r.get("pre_move_inspection_id") == inspection_id]
    if director_id is not None:
        rows = [r for r in rows if r.get("new_director_staff_member_id") == director_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if amendment_type is not None:
        rows = [r for r in rows if r["amendment_type"] == amendment_type]
    return helpers.listing(rows, serialize.amendment, limit, offset)


@bp.get("/licensing/license-amendments/<amendment_id>")
def read_amendment(amendment_id):
    authenticate(AMENDMENT_READERS)
    record = helpers.need("amendment", amendment_id)
    return envelope.ok(serialize.amendment(record))


@bp.post("/licensing/license-amendments/<amendment_id>/attach-inspection")
def attach_inspection(amendment_id):
    authenticate(("LicensingSupervisor",))
    vals = validate.body([F("pre_move_inspection_id", "string", required=True)])
    amendment = helpers.need("amendment", amendment_id)
    inspection = helpers.need("inspection", vals["pre_move_inspection_id"])
    if inspection["status"] != "FINALIZED":
        raise ApiError("ERR_INVALID_INSPECTION_STATE", "The pre-move visit is not FINALIZED.")
    if amendment["status"] != "PRE_INSPECTION_REQUIRED":
        raise ApiError(
            "ERR_INVALID_AMENDMENT_STATE", "The amendment does not await a pre-move visit."
        )
    if inspection["inspection_type"] != "AMENDMENT_PRE_MOVE":
        raise ApiError(
            "ERR_INVALID_INSPECTION_TYPE",
            "The attached visit must be of type AMENDMENT_PRE_MOVE.",
        )
    if inspection["provider_id"] != amendment["provider_id"]:
        raise ApiError(
            "ERR_VIOLATION_INSPECTION_MISMATCH",
            "The attached visit belongs to a different provider.",
        )
    amendment["pre_move_inspection_id"] = inspection["id"]
    amendment["status"] = "SUBMITTED"
    store.touch(amendment)
    return envelope.ok(serialize.amendment(amendment))


@bp.post("/licensing/license-amendments/<amendment_id>/decide")
def decide_amendment(amendment_id):
    authenticate(("AgencyAdmin",))
    vals = validate.body(
        [
            F("decision", "enum", required=True, values=K.AMENDMENT_DECISIONS),
            F("decision_rationale", "string", min_len=1, max_len=2000, not_blank=True),
        ]
    )
    if vals["decision"] == "DENY" and vals.get("decision_rationale") is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", "decision_rationale is required when denying an amendment."
        )
    amendment = helpers.need("amendment", amendment_id)
    if amendment["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_AMENDMENT_STATE", "The amendment is not SUBMITTED.")
    provider = store.providers[amendment["provider_id"]]
    delta = amendment["effective_capacity_delta"]
    is_capacity = amendment["amendment_type"] in CAPACITY_TYPES

    if vals["decision"] == "APPROVE":
        if is_capacity and delta > 0 and provider["critical_open_count"] != 0:
            raise ApiError(
                "ERR_UNRESOLVED_CRITICAL_VIOLATION",
                "An open critical violation blocks a capacity increase.",
            )
        for action in store.by_provider(store.actions, provider["id"]):
            if action["status"] == "EFFECTIVE" and action["action_type"] in (
                "SUSPENSION",
                "REVOCATION",
            ):
                raise ApiError(
                    "ERR_ACTIVE_ENFORCEMENT_BLOCKS_AMENDMENT",
                    "An effective suspension or revocation blocks an amendment.",
                )
        if is_capacity:
            total = provider["licensed_capacity"] + provider["suspended_capacity"] + delta
            if total > provider["capacity_ceiling"]:
                raise ApiError(
                    "ERR_CAPACITY_CEILING_EXCEEDED",
                    "The amended capacity exceeds the statutory ceiling for this programme.",
                )

    amendment["decided_at"] = clock.now()
    if vals.get("decision_rationale") is not None:
        amendment["decision_rationale"] = vals["decision_rationale"]
    if vals["decision"] == "DENY":
        amendment["status"] = "DENIED"
        store.touch(amendment)
        return envelope.ok(serialize.amendment(amendment))

    amendment["status"] = "APPROVED"
    if is_capacity:
        provider["licensed_capacity"] += delta
    elif amendment["amendment_type"] == "SITE_MOVE":
        provider["site_address"] = amendment["new_site_address"]
    elif amendment["amendment_type"] == "AGE_GROUP_ADD":
        room = {
            "provider_id": provider["id"],
            "age_group": amendment["new_age_group"],
            "requested_group_size": amendment["new_group_size"],
            "approved_group_size": amendment["new_group_size"],
            "enrolled_count": 0,
            "staff_assigned_count": 0,
            "lead_staff_member_id": None,
            "required_staff_count": 0,
            "ratio_compliant": True,
            "group_size_compliant": True,
            "supervision_compliant": True,
            "last_verified_at": None,
        }
        derive.recompute_roster_flags(room)
        store.create(store.rosters, room)
    store.touch(amendment)
    store.touch(provider)
    return envelope.ok(serialize.amendment(amendment))


@bp.post("/licensing/license-amendments/<amendment_id>/withdraw")
def withdraw_amendment(amendment_id):
    user_id, role = authenticate(("Applicant",))
    validate.body([])
    amendment = helpers.need("amendment", amendment_id)
    require_provider_owner(role, user_id, amendment["provider_id"])
    if amendment["status"] not in ("SUBMITTED", "PRE_INSPECTION_REQUIRED"):
        raise ApiError(
            "ERR_INVALID_AMENDMENT_STATE", "Only an open amendment can be withdrawn."
        )
    amendment["status"] = "WITHDRAWN"
    amendment["decided_at"] = clock.now()
    store.touch(amendment)
    return envelope.ok(serialize.amendment(amendment))
