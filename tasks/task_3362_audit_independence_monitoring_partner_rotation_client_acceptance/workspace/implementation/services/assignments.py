"""Engagement role assignments: OCC-guarded staffing and the end action."""

from core import constants as C
from core.clock import now as clock_now
from core.db import all_rows, new_row, store, touch
from core.errors import (
    ERR_BACKDATED_ASSIGNMENT,
    ERR_COOLING_OFF_ACTIVE,
    ERR_DUPLICATE_ROLE_HOLDER,
    ERR_ENGAGEMENT_FROZEN,
    ERR_INVALID_STATE,
    ERR_MATERIAL_INTEREST_CONFLICT,
    ERR_ROLE_ASSIGNMENT_OVERLAP,
    ERR_ROTATION_LIMIT_REACHED,
    ERR_STALE_VERSION,
    ERR_WORKLOAD_LIMIT_EXCEEDED,
    ApiError,
)
from services import staffing
from services.independence import (
    commit_engagement,
    refresh_assignments_for,
)
from services.threats import cooling_off_bar, material_interest_bar

SINGLE_HOLDER_ROLES = ("LEAD_PARTNER", "CONCURRING_PARTNER", "EQ_REVIEWER")


def _intervals_overlap(start_a, end_a, start_b, end_b):
    if start_a is None or end_a is None or start_b is None or end_b is None:
        return False
    return start_a < end_b and start_b < end_a


def create_assignment_row(engagement, professional, role, started_on, scheduled_end_on,
                          expected_engagement_version):
    now = clock_now()
    assignments = all_rows("assignments")
    engagements = store.engagements
    # 6 — state admissibility
    if engagement.get("status") not in C.STAFFABLE_ENGAGEMENT_STATUSES:
        raise ApiError(ERR_INVALID_STATE,
                       "The engagement's status does not admit new staffing.")
    # 7 — optimistic concurrency
    if expected_engagement_version != engagement.get("version"):
        raise ApiError(ERR_STALE_VERSION,
                       "expected_engagement_version does not match the engagement's current version.")
    client_id = engagement.get("client_id")
    # 9 — material financial interest
    if material_interest_bar(professional.get("id"), client_id):
        raise ApiError(ERR_MATERIAL_INTEREST_CONFLICT,
                       "The professional holds a material financial interest in this client.")
    # 10 — cooling-off window
    if cooling_off_bar(professional.get("id"), client_id, started_on, now):
        raise ApiError(ERR_COOLING_OFF_ACTIVE,
                       "The professional is inside a cooling-off window for this client.")
    # 11 — single-holder roles
    if role in SINGLE_HOLDER_ROLES:
        for row in assignments:
            if row.get("engagement_id") == engagement.get("id") \
                    and row.get("role") == role and row.get("status") == "ACTIVE":
                raise ApiError(ERR_DUPLICATE_ROLE_HOLDER,
                               "An ACTIVE assignment already holds this role on the engagement.")
    # 12 — interval overlap
    for row in assignments:
        if row.get("engagement_id") != engagement.get("id") or row.get("role") != role:
            continue
        if _intervals_overlap(started_on, scheduled_end_on,
                              row.get("started_on"), row.get("scheduled_end_on")):
            raise ApiError(ERR_ROLE_ASSIGNMENT_OVERLAP,
                           "The requested interval overlaps an existing assignment on this role.")
    # 14 — rotation limit
    limit = staffing.time_on_limit(store.clients.get(client_id), role)
    if limit > 0:
        run = staffing.candidate_run_months(
            professional.get("id"), client_id, role, started_on, scheduled_end_on,
            assignments, engagements, now)
        if run >= limit:
            raise ApiError(ERR_ROTATION_LIMIT_REACHED,
                           "The consecutive service run is at or beyond the time-on limit.")
    # 15 — workload ceiling
    candidate_base = staffing.assignment_base_points(role, engagement.get("risk_tier"))
    base_sum = staffing.professional_base_sum(professional.get("id"), assignments, engagements)
    projected = base_sum + candidate_base
    projected_total = projected + staffing.overload_surcharge(projected)
    if projected_total > int(professional.get("max_workload_points") or 0):
        raise ApiError(ERR_WORKLOAD_LIMIT_EXCEEDED,
                       "The assignment would push the professional above their workload ceiling.")
    # 20 — assignment dating
    if started_on < now:
        raise ApiError(ERR_BACKDATED_ASSIGNMENT,
                       "started_on must not be earlier than the logical clock.")
    # 21 — frozen engagement
    if engagement.get("independence_status") == "FROZEN":
        raise ApiError(ERR_ENGAGEMENT_FROZEN, "A frozen engagement may not be staffed.")
    row = new_row("assignments", {
        "engagement_id": engagement.get("id"),
        "professional_id": professional.get("id"),
        "role": role,
        "started_on": started_on,
        "scheduled_end_on": scheduled_end_on,
        "ended_on": None,
        "status": "ACTIVE",
        "consecutive_service_months": 0,
        "time_off_months_required": staffing.time_off_months(store.clients.get(client_id), role),
        "eligible_return_on": None,
        "rotation_status": "ON_SERVICE",
        "workload_points": candidate_base,
    })
    refresh_assignments_for(engagement.get("id"))
    touch(engagement)
    return row


def end_assignment_row(assignment, now=None):
    now = now or clock_now()
    if assignment.get("status") != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "Only an ACTIVE assignment may be ended.")
    assignment["status"] = "ENDED"
    assignment["ended_on"] = now
    touch(assignment)
    engagement_id = assignment.get("engagement_id")
    refresh_assignments_for(engagement_id)
    engagement = store.engagements.get(engagement_id)
    if engagement is not None:
        touch(engagement)
    return assignment
