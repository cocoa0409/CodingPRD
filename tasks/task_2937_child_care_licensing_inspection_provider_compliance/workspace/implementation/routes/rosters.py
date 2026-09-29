"""Age-group rooms, their three compliance flags and explicit verification (PRD §3.2)."""

from flask import Blueprint, request

import calc
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

bp = Blueprint("rosters", __name__)

ROSTER_READERS = (
    "AgencyAdmin",
    "Applicant",
    "LicensingSupervisor",
    "LicensingInspector",
)


def _lead_check(age_group, lead):
    if lead is None:
        return
    if not derive.lead_is_eligible(age_group, lead):
        raise ApiError(
            "ERR_SUPERVISION_INELIGIBLE_LEAD",
            "The named room lead is not eligible to supervise this age group.",
        )


def _capacity_check(provider, roster_id, approved_group_size):
    total = approved_group_size
    for room in store.rosters_of(provider["id"]):
        if room["id"] != roster_id:
            total += room["approved_group_size"]
    if total > derive.roster_capacity_limit(provider):
        raise ApiError(
            "ERR_ROSTER_CAPACITY_MISMATCH",
            "Approved group sizes exceed the provider's authorised capacity.",
        )


@bp.post("/licensing/age-group-rosters")
def create_roster():
    user_id, role = authenticate(("Applicant", "AgencyAdmin"))
    vals = validate.body(
        [
            F("provider_id", "string", required=True),
            F("age_group", "enum", required=True, values=K.AGE_GROUPS),
            F("requested_group_size", "int", required=True, min_val=1),
            F("enrolled_count", "int", min_val=0),
            F("staff_assigned_count", "int", min_val=0),
            F("lead_staff_member_id", "string"),
        ]
    )
    provider = helpers.need("provider", vals["provider_id"])
    lead = None
    if vals.get("lead_staff_member_id") is not None:
        lead = helpers.need("staff_member", vals["lead_staff_member_id"])
    require_provider_owner(role, user_id, provider["id"])

    age_group = vals["age_group"]
    enrolled = vals.get("enrolled_count", 0)
    _lead_check(age_group, lead)
    if vals["requested_group_size"] > K.AGE_GROUP_MAX_SIZE[age_group]:
        raise ApiError(
            "ERR_GROUP_SIZE_EXCEEDED",
            "The requested group size exceeds the statutory maximum for this age group.",
        )
    if enrolled > calc.effective_group_cap(age_group, 0):
        raise ApiError(
            "ERR_GROUP_SIZE_EXCEEDED",
            "The enrolled count exceeds the room's effective capacity.",
        )
    for room in store.rosters_of(provider["id"]):
        if room["age_group"] == age_group:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "A roster already exists for this provider and age group.",
            )
    _capacity_check(provider, None, 0)

    record = {
        "provider_id": provider["id"],
        "age_group": age_group,
        "requested_group_size": vals["requested_group_size"],
        "approved_group_size": 0,
        "enrolled_count": enrolled,
        "staff_assigned_count": vals.get("staff_assigned_count", 0),
        "lead_staff_member_id": lead["id"] if lead else None,
        "required_staff_count": 0,
        "ratio_compliant": True,
        "group_size_compliant": True,
        "supervision_compliant": True,
        "last_verified_at": None,
    }
    derive.recompute_roster_flags(record)
    store.create(store.rosters, record)
    return envelope.created(serialize.roster(record))


@bp.get("/licensing/age-group-rosters")
def list_rosters():
    authenticate(ROSTER_READERS)
    limit, offset = envelope.pagination(request.args)
    age_group = validate.query_enum("age_group", K.AGE_GROUPS)
    provider_id = validate.query_str("provider_id")
    lead_id = validate.query_str("lead_staff_member_id")
    rows = store.ordered(store.rosters)
    if provider_id is not None:
        rows = [r for r in rows if r["provider_id"] == provider_id]
    if lead_id is not None:
        rows = [r for r in rows if r.get("lead_staff_member_id") == lead_id]
    if age_group is not None:
        rows = [r for r in rows if r["age_group"] == age_group]
    return helpers.listing(rows, serialize.roster, limit, offset)


@bp.get("/licensing/age-group-rosters/<roster_id>")
def read_roster(roster_id):
    authenticate(ROSTER_READERS)
    record = helpers.need("roster", roster_id)
    return envelope.ok(serialize.roster(record))


@bp.patch("/licensing/age-group-rosters/<roster_id>")
def update_roster(roster_id):
    user_id, role = authenticate(("Applicant", "AgencyAdmin"))
    vals = validate.body(
        [
            F("enrolled_count", "int", min_val=0),
            F("staff_assigned_count", "int", min_val=0),
            F("lead_staff_member_id", "string"),
        ]
    )
    roster = helpers.need("roster", roster_id)
    lead_id = roster.get("lead_staff_member_id")
    if vals.get("lead_staff_member_id") is not None:
        lead_id = helpers.need("staff_member", vals["lead_staff_member_id"])["id"]
    provider = store.providers[roster["provider_id"]]
    require_provider_owner(role, user_id, provider["id"])

    age_group = roster["age_group"]
    enrolled = vals.get("enrolled_count", roster["enrolled_count"])
    assigned = vals.get("staff_assigned_count", roster["staff_assigned_count"])
    lead = store.staff_members.get(lead_id)
    if vals.get("lead_staff_member_id") is not None:
        _lead_check(age_group, lead)
    if assigned < calc.required_staff_count(age_group, enrolled):
        raise ApiError(
            "ERR_RATIO_NONCOMPLIANT",
            "The assigned staff count is below the required staff count.",
        )
    if enrolled > calc.effective_group_cap(age_group, roster["approved_group_size"]):
        raise ApiError(
            "ERR_GROUP_SIZE_EXCEEDED",
            "The enrolled count exceeds the room's effective capacity.",
        )
    _capacity_check(provider, roster["id"], roster["approved_group_size"])

    roster["enrolled_count"] = enrolled
    roster["staff_assigned_count"] = assigned
    roster["lead_staff_member_id"] = lead_id
    derive.recompute_roster_flags(roster)
    store.touch(roster)
    return envelope.ok(serialize.roster(roster))


@bp.post("/licensing/age-group-rosters/<roster_id>/verify-ratio")
def verify_ratio(roster_id):
    authenticate(("LicensingInspector", "LicensingSupervisor"))
    validate.body([])
    roster = helpers.need("roster", roster_id)
    age_group = roster["age_group"]
    lead = store.staff_members.get(roster.get("lead_staff_member_id"))
    if roster.get("lead_staff_member_id") is not None:
        _lead_check(age_group, lead)
    derive.recompute_roster_flags(roster)
    if not roster["ratio_compliant"]:
        raise ApiError(
            "ERR_RATIO_NONCOMPLIANT",
            "The assigned staff count is below the required staff count.",
        )
    if not roster["group_size_compliant"]:
        raise ApiError(
            "ERR_GROUP_SIZE_EXCEEDED",
            "The enrolled count exceeds the room's effective capacity.",
        )
    if not roster["supervision_compliant"]:
        raise ApiError(
            "ERR_SUPERVISION_INELIGIBLE_LEAD",
            "The room has no eligible lead for its enrolled children.",
        )
    roster["last_verified_at"] = clock.now()
    store.touch(roster)
    return envelope.ok(serialize.roster(roster))
