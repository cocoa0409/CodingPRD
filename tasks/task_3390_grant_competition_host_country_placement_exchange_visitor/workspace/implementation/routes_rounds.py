"""PlacementRound endpoints: open a round (HostCommission, OCC-guarded),
list rounds, and respond to / expire an offer."""

from flask import Blueprint

import domain
import envelope
import serialize
from auth import auth, require_roles, check_owner
from constants import (
    ROLE_APPLICANT,
    ROLE_PROGRAM_OFFICER,
    ROLE_HOST_COMMISSION,
    ROLE_PLATFORM_ADMIN,
    MAX_PLACEMENT_ROUNDS,
)
from errors import ApiError
from store import STORE, stamp_new, bump, now, now_iso
from timeutil import parse_iso, fmt
from validate import (
    body,
    check_unknown,
    req,
    as_str,
    as_enum,
    as_dt,
    as_version,
    pagination,
    page_slice,
    V,
)

bp = Blueprint("rounds", __name__)

ROUND_LIST_ROLES = (ROLE_PLATFORM_ADMIN, ROLE_PROGRAM_OFFICER, ROLE_HOST_COMMISSION, ROLE_APPLICANT)
INSTITUTION_BANDS = ("STANDARD", "HIGH")
ROUND_ACTIONS = ("ACCEPT", "DECLINE", "EXPIRE")


@bp.post("/exchange/applications/<aid>/placement-rounds")
def create_round(aid):
    _, role = auth()
    require_roles(role, [ROLE_HOST_COMMISSION])
    application = STORE.applications.get(aid)
    if application is None:
        raise ApiError("ERR_APPLICATION_NOT_FOUND", 404, "No application with the given id")
    payload = body()
    # Priority 4: optimistic concurrency on Application.version.
    if "expected_application_version" not in payload or payload["expected_application_version"] is None:
        raise V("Missing required field: expected_application_version")
    expected = as_version(payload["expected_application_version"])
    if expected != application["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            412,
            "expected_application_version does not match the application's current version",
        )
    # Priority 6: rounds open only for SELECTED (first) or PLACEMENT applications.
    if application["status"] not in ("SELECTED", "PLACEMENT"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Placement rounds can only be opened for a SELECTED or PLACEMENT application",
        )
    # Priority 9: structural validation.
    check_unknown(
        payload,
        {"institution_name", "institution_band", "response_deadline", "expected_application_version"},
    )
    institution = as_str(req(payload, "institution_name"), "institution_name")
    band = as_enum(req(payload, "institution_band"), "institution_band", INSTITUTION_BANDS)
    deadline = as_dt(req(payload, "response_deadline"), "response_deadline")
    # Priority 9: at most one non-terminal (OFFERED) round per application.
    for r in STORE.rounds.values():
        if r["application_id"] == aid and r["status"] == "OFFERED":
            raise ApiError(
                "ERR_ACTIVE_ROUND_EXISTS",
                409,
                "Application already has a non-terminal placement round",
            )
    rnd = {
        "application_id": aid,
        "round_number": application["placement_rounds_used"] + 1,
        "institution_name": institution,
        "institution_band": band,
        "response_deadline": fmt(deadline),
        "status": "OFFERED",
        "responded_at": None,
    }
    stamp_new(rnd)
    STORE.rounds[rnd["id"]] = rnd
    application["placement_rounds_used"] += 1
    if application["status"] == "SELECTED":
        application["status"] = "PLACEMENT"
    bump(application)
    return envelope.ok(serialize.round_out(rnd), 201)


@bp.get("/exchange/applications/<aid>/placement-rounds")
def list_rounds(aid):
    user, role = auth()
    require_roles(role, ROUND_LIST_ROLES)
    application = STORE.applications.get(aid)
    if application is None:
        raise ApiError("ERR_APPLICATION_NOT_FOUND", 404, "No application with the given id")
    check_owner(role, user, application["applicant_id"])
    limit, offset = pagination()
    items = [r for r in STORE.rounds.values() if r["application_id"] == aid]
    page, total = page_slice(items, limit, offset)
    return envelope.ok_list([serialize.round_out(r) for r in page], total, limit, offset)


@bp.post("/exchange/placement-rounds/<rid>/transition")
def round_transition(rid):
    user, role = auth()
    require_roles(role, [ROLE_APPLICANT, ROLE_PROGRAM_OFFICER])
    payload = body()
    action = payload.get("action")
    # Priority 2: action-family role binding for known actions.
    if isinstance(action, str):
        if action in ("ACCEPT", "DECLINE"):
            if role != ROLE_APPLICANT:
                raise ApiError("ERR_UNAUTHORIZED", 403, "Action %s is an Applicant action" % action)
        elif action == "EXPIRE":
            if role != ROLE_PROGRAM_OFFICER:
                raise ApiError("ERR_UNAUTHORIZED", 403, "EXPIRE is a ProgramOfficer action")

    # Priority 3: path existence precedes every other domain check (PRD 2.9).
    rnd = STORE.rounds.get(rid)
    if rnd is None:
        raise ApiError("ERR_ROUND_NOT_FOUND", 404, "No placement round with the given id")
    application = STORE.applications[rnd["application_id"]]
    check_owner(role, user, application["applicant_id"])

    if action is None:
        raise V("Missing required field: action")
    check_unknown(payload, {"action"})
    if action not in ROUND_ACTIONS:
        raise V("Unknown action for placement round transition: %r" % action)
    # Priority 6: the round must be OFFERED.
    if rnd["status"] != "OFFERED":
        raise ApiError("ERR_ROUND_NOT_OFFERED", 409, "Placement round is not OFFERED")
    clock = now()
    deadline = parse_iso(rnd["response_deadline"])

    if action in ("ACCEPT", "DECLINE"):
        # Priority 8: inclusive response deadline.
        if clock > deadline:
            raise ApiError("ERR_OFFER_EXPIRED", 409, "The placement offer has expired")
        rnd["responded_at"] = now_iso()
        if action == "ACCEPT":
            rnd["status"] = "ACCEPTED"
            bump(rnd)
            application["status"] = "GRANT_PENDING"
            bump(application)
        else:  # DECLINE
            rnd["status"] = "DECLINED"
            bump(rnd)
            if rnd["round_number"] == MAX_PLACEMENT_ROUNDS:
                domain.fail_placement(application)
    else:  # EXPIRE
        # The clock must be strictly past the deadline; earlier is invalid.
        if clock <= deadline:
            raise ApiError(
                "ERR_INVALID_STATE", 409, "An offer cannot be expired before its deadline"
            )
        rnd["status"] = "EXPIRED"
        bump(rnd)
        if rnd["round_number"] == MAX_PLACEMENT_ROUNDS:
            domain.fail_placement(application)
    return envelope.ok(serialize.round_out(rnd))
