"""Series-order negotiation with the studio and the greenlight fork-join."""

from flask import Blueprint, request

import domain as d
from auth import (COMMITTEE_ROLE, ROLE_BUSINESS_AFFAIRS, ROLE_DEV_EXEC,
                  ROLE_FINANCE, ROLE_PLATFORM_ADMIN, ROLE_STUDIO, authorize)
from errors import ApiError
from responses import object_response, paginated
from store import new_row, store, touch
from validators import json_body, peek, require_body, v_enum, v_int, v_string

bp = Blueprint("series", __name__)

GREENLIGHT_READ_ROLES = (ROLE_PLATFORM_ADMIN, ROLE_DEV_EXEC, ROLE_BUSINESS_AFFAIRS,
                         ROLE_FINANCE)

DECISION_FIELDS = {
    "CREATIVE": ("creative_decision", "creative_decided_by_user_id"),
    "BUSINESS": ("business_decision", "business_decided_by_user_id"),
    "FINANCE": ("finance_decision", "finance_decided_by_user_id"),
}


def _read_terms(body):
    return {
        "episode_count": v_int(body, "episode_count", minimum=1),
        "license_fee_per_episode_cents": v_int(
            body, "license_fee_per_episode_cents", minimum=1),
        "backend_points_bps": v_int(body, "backend_points_bps",
                                    minimum=0, maximum=10000),
        "network_ownership_pct": v_int(body, "network_ownership_pct",
                                       minimum=0, maximum=100),
        "studio_ownership_pct": v_int(body, "studio_ownership_pct",
                                      minimum=0, maximum=100),
    }


def _check_term_sheet(terms, slate):
    # 37 -- internal coherence.
    if terms["network_ownership_pct"] + terms["studio_ownership_pct"] != 100:
        raise ApiError("ERR_TERM_SHEET_INVALID")
    if terms["backend_points_bps"] > slate["max_backend_points_bps"]:
        raise ApiError("ERR_TERM_SHEET_INVALID")
    if terms["episode_count"] < 1:
        raise ApiError("ERR_TERM_SHEET_INVALID")
    # 38 -- the license fee cap.
    if terms["license_fee_per_episode_cents"] > slate["license_fee_cap_per_episode_cents"]:
        raise ApiError("ERR_LICENSE_FEE_ABOVE_CAP")


# ---------------------------------------------------------------------------
# negotiations
# ---------------------------------------------------------------------------

@bp.post("/negotiations")
@authorize(ROLE_BUSINESS_AFFAIRS)
def open_negotiation(principal):
    body = require_body(json_body())
    project = d.get_project(body.get("project_id"))
    terms = _read_terms(body)

    # 11 -- the project must have a delivered pilot.
    if project["dev_status"] != "PILOT_DELIVERED":
        raise ApiError("ERR_INVALID_PROJECT_STATE")

    slate = d.slate_of_project(project)

    # 33 -- posture, evaluated before any commercial gate.
    d.require_slate_not_locked(slate)

    _check_term_sheet(terms, slate)

    # 43 / 44 -- research gates.
    latest = d.latest_certified_screening(project)
    if latest is None:
        raise ApiError("ERR_NO_CERTIFIED_TEST")
    if latest["norm_adjusted_score"] < d.TEST_SCORE_FLOOR:
        raise ApiError("ERR_TEST_SCORE_BELOW_FLOOR")

    # 46 -- episode inventory.
    if d.slate_available_episode_count(slate) < terms["episode_count"]:
        raise ApiError("ERR_EPISODE_CAPACITY_EXCEEDED")

    row = new_row(
        project_id=project["id"],
        status="NETWORK_OFFER",
        round_number=1,
        last_offer_side="NETWORK",
        agreed_at=None,
        withdrawn_reason=None,
        **terms
    )
    store.negotiations[row["id"]] = row
    touch(slate)
    return object_response(d.serialize_negotiation(row), 201)


@bp.post("/negotiations/<negotiation_id>/rounds")
@authorize(ROLE_BUSINESS_AFFAIRS, ROLE_STUDIO)
def counter_negotiation(principal, negotiation_id):
    negotiation = d.get_negotiation(negotiation_id)
    body = require_body(json_body())
    terms = _read_terms(body)

    # 17 -- the negotiation must be open, and each side counters the other.
    if negotiation["status"] not in ("NETWORK_OFFER", "STUDIO_COUNTER"):
        raise ApiError("ERR_INVALID_NEGOTIATION_STATE")
    if principal.role == ROLE_STUDIO and negotiation["status"] != "NETWORK_OFFER":
        raise ApiError("ERR_INVALID_NEGOTIATION_STATE")
    if principal.role == ROLE_BUSINESS_AFFAIRS and negotiation["status"] != "STUDIO_COUNTER":
        raise ApiError("ERR_INVALID_NEGOTIATION_STATE")

    # 36 -- four term sheets is the ceiling.
    if negotiation["round_number"] >= d.MAX_NEGOTIATION_ROUNDS:
        raise ApiError("ERR_NEGOTIATION_ROUNDS_EXHAUSTED")

    project = store.projects[negotiation["project_id"]]
    slate = d.slate_of_project(project)
    _check_term_sheet(terms, slate)

    # 46 -- the capacity check is a delta against this negotiation's own hold.
    headroom = d.slate_available_episode_count(slate) + negotiation["episode_count"]
    if headroom < terms["episode_count"]:
        raise ApiError("ERR_EPISODE_CAPACITY_EXCEEDED")

    negotiation.update(terms)
    if negotiation["status"] == "NETWORK_OFFER":
        negotiation["status"] = "STUDIO_COUNTER"
        negotiation["last_offer_side"] = "STUDIO"
    else:
        negotiation["status"] = "NETWORK_OFFER"
        negotiation["last_offer_side"] = "NETWORK"
    negotiation["round_number"] = negotiation["round_number"] + 1
    touch(negotiation)
    touch(slate)
    return object_response(d.serialize_negotiation(negotiation))


@bp.post("/negotiations/<negotiation_id>/accept")
@authorize(ROLE_BUSINESS_AFFAIRS, ROLE_STUDIO)
def accept_negotiation(principal, negotiation_id):
    negotiation = d.get_negotiation(negotiation_id)

    # 17 -- only an open negotiation may be accepted.
    if negotiation["status"] not in ("NETWORK_OFFER", "STUDIO_COUNTER"):
        raise ApiError("ERR_INVALID_NEGOTIATION_STATE")

    # 20 -- the side that tabled the standing sheet may not accept it.
    acting_side = "STUDIO" if principal.role == ROLE_STUDIO else "NETWORK"
    if negotiation["last_offer_side"] == acting_side:
        raise ApiError("ERR_ACCEPT_BY_OFFERING_SIDE")

    negotiation["status"] = "AGREED"
    negotiation["agreed_at"] = store.now()
    touch(negotiation)

    project = store.projects[negotiation["project_id"]]
    touch(d.slate_of_project(project))
    return object_response(d.serialize_negotiation(negotiation))


# ---------------------------------------------------------------------------
# greenlight requests
# ---------------------------------------------------------------------------

@bp.post("/greenlight-requests")
@authorize(ROLE_BUSINESS_AFFAIRS)
def file_greenlight(principal):
    body = require_body(json_body())
    project = d.get_project(body.get("project_id"))
    negotiation = d.get_negotiation(body.get("negotiation_id"))
    expected_version = v_int(body, "expected_project_version", minimum=0)

    # 11 -- the project must be at PILOT_DELIVERED.
    if project["dev_status"] != "PILOT_DELIVERED":
        raise ApiError("ERR_INVALID_PROJECT_STATE")

    # 17 -- the term sheet must be AGREED.
    if negotiation["status"] != "AGREED":
        raise ApiError("ERR_INVALID_NEGOTIATION_STATE")

    # 21 -- stale-read protection on the project.
    if expected_version != project["version"]:
        raise ApiError("ERR_STALE_PROJECT_VERSION")

    # 42 -- the negotiation must belong to this project.
    if negotiation["project_id"] != project["id"]:
        raise ApiError("ERR_NEGOTIATION_PROJECT_MISMATCH")

    row = new_row(
        project_id=project["id"],
        negotiation_id=negotiation["id"],
        project_version_at_request=project["version"],
        creative_decision="PENDING",
        business_decision="PENDING",
        finance_decision="PENDING",
        creative_decided_by_user_id=None,
        business_decided_by_user_id=None,
        finance_decided_by_user_id=None,
        status="OPEN",
        decided_at=None,
    )
    store.greenlights[row["id"]] = row

    d.supersede_greenlights(project, row["id"])
    touch(project)
    return object_response(d.serialize_greenlight(row), 201)


@bp.get("/greenlight-requests/<greenlight_id>")
@authorize(*GREENLIGHT_READ_ROLES)
def read_greenlight(principal, greenlight_id):
    row = d.get_greenlight(greenlight_id)
    return object_response(d.serialize_greenlight(row))


@bp.get("/greenlight-requests")
@authorize(*GREENLIGHT_READ_ROLES)
def list_greenlights(principal):
    rows = d.ordered(list(store.greenlights.values()))
    project_id = request.args.get("project_id")
    if project_id is not None:
        rows = [r for r in rows if r["project_id"] == project_id]
    negotiation_id = request.args.get("negotiation_id")
    if negotiation_id is not None:
        rows = [r for r in rows if r["negotiation_id"] == negotiation_id]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginated(rows, d.serialize_greenlight)


@bp.post("/greenlight-requests/<greenlight_id>/decisions")
@authorize(ROLE_DEV_EXEC, ROLE_BUSINESS_AFFAIRS, ROLE_FINANCE)
def record_decision(principal, greenlight_id):
    body = json_body()

    # 4 -- the committee must match the acting role, ahead of path existence.
    raw_committee = peek(body, "committee")
    if raw_committee in COMMITTEE_ROLE and COMMITTEE_ROLE[raw_committee] != principal.role:
        raise ApiError("ERR_UNAUTHORIZED")

    greenlight = d.get_greenlight(greenlight_id)

    # 6 -- one opaque identifier decides at most one committee per request.
    for _, decided_by_field in DECISION_FIELDS.values():
        if greenlight[decided_by_field] == principal.user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    require_body(body)
    committee = v_enum(body, "committee", d.COMMITTEES)
    decision = v_enum(body, "decision", d.DECISIONS)
    v_string(body, "note", required=False, max_len=1000, allow_null=True, default=None)

    # 18 -- the request must still be OPEN.
    if greenlight["status"] != "OPEN":
        raise ApiError("ERR_INVALID_GREENLIGHT_STATE")

    decision_field, decided_by_field = DECISION_FIELDS[committee]

    # 19 -- this committee must not have decided already.
    if greenlight[decision_field] != "PENDING":
        raise ApiError("ERR_COMMITTEE_ALREADY_DECIDED")

    project = store.projects[greenlight["project_id"]]
    negotiation = store.negotiations[greenlight["negotiation_id"]]

    # 47 -- a FINANCE approval re-runs feasibility on the PATTERN basis.
    if committee == "FINANCE" and decision == "APPROVED":
        result = d.feasibility(project, "PATTERN", negotiation["episode_count"])
        if result["verdict"] == "INFEASIBLE":
            raise ApiError("ERR_FEASIBILITY_FAILED")

    greenlight[decision_field] = decision
    greenlight[decided_by_field] = principal.user_id

    if decision == "REJECTED":
        greenlight["status"] = "REJECTED"
        greenlight["decided_at"] = store.now()
        touch(greenlight)
        return object_response(d.serialize_greenlight(greenlight))

    all_approved = all(
        greenlight[field] == "APPROVED" for field, _ in DECISION_FIELDS.values()
    )
    if all_approved:
        d.cascade_greenlight_approved(greenlight, project)
        touch(greenlight)
    else:
        touch(greenlight)
    return object_response(d.serialize_greenlight(greenlight))
