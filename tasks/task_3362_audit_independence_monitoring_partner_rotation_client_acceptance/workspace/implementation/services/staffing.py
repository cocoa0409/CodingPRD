"""Rotation tenure and workload calculations (scaffold §1.3)."""

from decimal import Decimal

from core import constants as C
from core.utils import add_months, months_between, round_half_up_int


def rotation_variant(client):
    if client is not None and client.get("is_public_interest_entity"):
        return "PIE_ACCELERATED"
    return "STANDARD"


def time_on_limit(client, role):
    return C.TIME_ON_LIMIT[rotation_variant(client)].get(role, 0)


def time_off_months(client, role):
    return C.TIME_OFF_MONTHS[rotation_variant(client)].get(role, 0)


def effective_end(assignment, now):
    """ended_on when stamped, otherwise the earlier of scheduled_end_on and now."""
    ended_on = assignment.get("ended_on")
    if ended_on is not None:
        return ended_on
    scheduled = assignment.get("scheduled_end_on")
    if scheduled is None:
        return now
    return scheduled if scheduled < now else now


def triple_rows(assignments, engagements, professional_id, client_id, role):
    """All rows sharing the (professional, client, role) triple, ordered."""
    rows = []
    for row in assignments:
        if row.get("professional_id") != professional_id:
            continue
        if row.get("role") != role:
            continue
        engagement = engagements.get(row.get("engagement_id"))
        if engagement is None or engagement.get("client_id") != client_id:
            continue
        rows.append(row)
    rows.sort(key=lambda r: (r.get("started_on"), r.get("_created_dt"), r.get("_seq", 0)))
    return rows


def run_months_upto(rows, target, now):
    """Accumulate the consecutive-service run, stopping at the target row."""
    run = 0
    previous_end = None
    for row in rows:
        end = effective_end(row, now)
        if previous_end is None:
            run = months_between(row.get("started_on"), end)
        else:
            gap = months_between(previous_end, row.get("started_on"))
            if gap <= C.GAP_TOLERANCE_MONTHS:
                run = run + months_between(row.get("started_on"), end)
            else:
                run = months_between(row.get("started_on"), end)
        previous_end = end
        if row is target:
            break
    return run


def consecutive_service_for(assignment, assignments, engagements, now):
    engagement = engagements.get(assignment.get("engagement_id"))
    client_id = engagement.get("client_id") if engagement else None
    rows = triple_rows(
        assignments, engagements,
        assignment.get("professional_id"), client_id, assignment.get("role"),
    )
    return run_months_upto(rows, assignment, now)


def candidate_run_months(professional_id, client_id, role, started_on, scheduled_end_on,
                         assignments, engagements, now):
    """Simulate the run a not-yet-created assignment would land in."""
    candidate = {
        "id": None,
        "professional_id": professional_id,
        "role": role,
        "started_on": started_on,
        "scheduled_end_on": scheduled_end_on,
        "ended_on": None,
        "status": "ACTIVE",
        "_created_dt": now,
        "_seq": 10 ** 9,
    }
    rows = triple_rows(assignments, engagements, professional_id, client_id, role)
    rows.append(candidate)
    rows.sort(key=lambda r: (r.get("started_on"), r.get("_created_dt"), r.get("_seq", 0)))
    return run_months_upto(rows, candidate, now)


def rotation_status_for(assignment, client, now):
    limit = time_on_limit(client, assignment.get("role"))
    if assignment.get("status") == "ACTIVE":
        if limit == 0:
            return "ON_SERVICE"
        if int(assignment.get("consecutive_service_months") or 0) >= limit:
            return "ROTATION_DUE"
        return "ON_SERVICE"
    eligible_return_on = assignment.get("eligible_return_on")
    if eligible_return_on is None:
        return "ELIGIBLE"
    if now < eligible_return_on:
        return "IN_TIME_OFF"
    return "ELIGIBLE"


def eligible_return_for(assignment, client):
    ended_on = assignment.get("ended_on")
    if ended_on is None:
        return None
    months = time_off_months(client, assignment.get("role"))
    return add_months(ended_on, months)


def refresh_rotation(assignment, assignments, engagements, clients, now):
    """Recompute tenure-derived fields on one assignment row."""
    engagement = engagements.get(assignment.get("engagement_id"))
    client = clients.get(engagement.get("client_id")) if engagement else None
    months = consecutive_service_for(assignment, assignments, engagements, now)
    assignment["consecutive_service_months"] = months
    assignment["time_off_months_required"] = time_off_months(client, assignment.get("role"))
    if assignment.get("status") == "ENDED":
        assignment["eligible_return_on"] = eligible_return_for(assignment, client)
    else:
        assignment["eligible_return_on"] = None
    assignment["rotation_status"] = rotation_status_for(assignment, client, now)
    return assignment


# ---------------------------------------------------------------------------
# assignment_workload_points — fixed four-step order
# ---------------------------------------------------------------------------
def assignment_base_points(role, risk_tier):
    base = Decimal(str(C.BASE_POINTS.get(role, 0)))
    multiplier = Decimal(str(C.TIER_MULTIPLIER.get(risk_tier or "LOW", 1.0)))
    return round_half_up_int(base * multiplier)


def base_points_for_assignment(assignment, engagements):
    engagement = engagements.get(assignment.get("engagement_id"))
    tier = engagement.get("risk_tier") if engagement else "LOW"
    return assignment_base_points(assignment.get("role"), tier)


def professional_base_sum(professional_id, assignments, engagements):
    total = 0
    for row in assignments:
        if row.get("professional_id") != professional_id:
            continue
        if row.get("status") != "ACTIVE":
            continue
        total += base_points_for_assignment(row, engagements)
    return total


def overload_surcharge(base_sum):
    surcharge = 0
    for threshold, points in C.OVERLOAD_TIERS:
        if base_sum > threshold:
            surcharge = points
    return surcharge


def professional_points(professional_id, assignments, engagements):
    base_sum = professional_base_sum(professional_id, assignments, engagements)
    surcharge = overload_surcharge(base_sum)
    return base_sum + surcharge


def engagement_assigned_points(engagement_id, assignments, engagements):
    total = 0
    for row in assignments:
        if row.get("engagement_id") != engagement_id:
            continue
        if row.get("status") != "ACTIVE":
            continue
        total += base_points_for_assignment(row, engagements)
    return total


def availability_for(professional, assignments, now, active_points=None):
    if active_points is None:
        active_points = professional.get("active_workload_points") or 0
    if active_points > int(professional.get("max_workload_points") or 0):
        return "OVERLOADED"
    has_active = False
    for row in assignments:
        if row.get("professional_id") != professional.get("id"):
            continue
        if row.get("status") == "ACTIVE":
            has_active = True
            break
    if not has_active:
        for row in assignments:
            if row.get("professional_id") != professional.get("id"):
                continue
            if row.get("status") != "ENDED":
                continue
            eligible = row.get("eligible_return_on")
            if eligible is not None and now < eligible:
                return "IN_TIME_OFF"
    return "AVAILABLE"


def rotation_exposure(professional_id, assignments, engagements, now):
    """Longest consecutive-service run across all of this professional's rows."""
    longest = 0
    for row in assignments:
        if row.get("professional_id") != professional_id:
            continue
        months = consecutive_service_for(row, assignments, engagements, now)
        if months > longest:
            longest = months
    return longest


def refresh_professional(professional, assignments, engagements, now):
    points = professional_points(professional.get("id"), assignments, engagements)
    professional["active_workload_points"] = points
    professional["availability"] = availability_for(professional, assignments, now, points)
    professional["rotation_exposure_months"] = rotation_exposure(
        professional.get("id"), assignments, engagements, now)
    return professional


def refresh_engagement_staffing(engagement, assignments, engagements):
    engagement["assigned_workload_points"] = engagement_assigned_points(
        engagement.get("id"), assignments, engagements)
    lead = None
    concurring = None
    for row in assignments:
        if row.get("engagement_id") != engagement.get("id"):
            continue
        if row.get("status") != "ACTIVE":
            continue
        if row.get("role") == "LEAD_PARTNER" and lead is None:
            lead = row.get("professional_id")
        if row.get("role") == "CONCURRING_PARTNER" and concurring is None:
            concurring = row.get("professional_id")
    engagement["lead_partner_id"] = lead
    engagement["concurring_partner_id"] = concurring
    return engagement
