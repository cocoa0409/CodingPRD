"""Shared domain machinery: record creation, cascade recomputation, the
validation ladder and the region posture engine (PRD 2.4, 2.9, 2.10, 3.8).
"""

from clock import CLOCK, new_id, now_iso, parse_iso8601
from constants import (
    MARGIN_FREEZE_FLOOR_CENTS,
    PANEL_RATE_CENTS,
    REFERRAL_TRIAGE_WINDOW_DAYS,
)
from calculations import (
    capitation_rate_cents,
    panel_capitation_component_cents,
    provider_comp_total_cents,
    quality_bonus_cents as calc_quality_bonus,
)
from db import STORE
from errors import (
    ERR_BUDGET_FISCAL_LINE_EXCEEDED,
    ERR_REFERENTIAL_INTEGRATION_NOT_FOUND,
    ERR_CAPACITY_PLAN_NOT_FOUND,
    ERR_CARE_SITE_NOT_FOUND,
    ERR_CROSS_REGION_REFERENCE,
    ERR_DEPARTMENT_NOT_FOUND,
    ERR_MEMBER_NOT_FOUND,
    ERR_MEMBER_TRANSFER_NOT_FOUND,
    ERR_OUTSIDE_CLAIM_NOT_FOUND,
    ERR_PROVIDER_NOT_FOUND,
    ERR_QUALITY_METRIC_NOT_FOUND,
    ERR_REFERENCED_RESOURCE_NOT_FOUND,
    ERR_REFERRAL_NOT_FOUND,
    ERR_REGION_NOT_FOUND,
    ERR_REGION_POSTURE_FROZEN,
    ERR_REGIONAL_BUDGET_NOT_FOUND,
    ERR_STALE_VERSION,
    raise_error,
)
from projections import (
    IN_FORCE_MEMBER_STATUSES,
    period_of,
    region_view,
)

PENDING_TRANSFER_STATUSES = ("REQUESTED", "PENDING_EFFECTIVE")
NON_CANCELLED_APPOINTMENT_STATUSES = ("REQUESTED", "SCHEDULED", "COMPLETED")


# ---------------------------------------------------------------- creation

def new_record(**fields):
    stamp = now_iso()
    row = {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
    }
    row.update(fields)
    return row


def touch(row):
    row["updated_at"] = now_iso()
    row["version"] = int(row.get("version", 1)) + 1
    return row


def store_row(table, row):
    getattr(STORE, table)[row["id"]] = row
    return row


# ------------------------------------------------------------- lookups

def _lookup(table, row_id, spec):
    row = getattr(STORE, table).get(row_id)
    if row is None:
        raise_error(spec)
    return row


def get_region(region_id):
    return _lookup("regions", region_id, ERR_REGION_NOT_FOUND)


def get_member(member_id):
    return _lookup("members", member_id, ERR_MEMBER_NOT_FOUND)


def get_care_site(site_id):
    return _lookup("care_sites", site_id, ERR_CARE_SITE_NOT_FOUND)


def get_department(department_id):
    return _lookup("departments", department_id, ERR_DEPARTMENT_NOT_FOUND)


def get_provider(provider_id):
    return _lookup("providers", provider_id, ERR_PROVIDER_NOT_FOUND)


def get_appointment(appointment_id):
    from errors import ERR_APPOINTMENT_NOT_FOUND
    return _lookup("appointments", appointment_id, ERR_APPOINTMENT_NOT_FOUND)


def get_referral(referral_id):
    return _lookup("referrals", referral_id, ERR_REFERRAL_NOT_FOUND)


def get_claim(claim_id):
    return _lookup("claims", claim_id, ERR_OUTSIDE_CLAIM_NOT_FOUND)


def get_budget(budget_id):
    return _lookup("budgets", budget_id, ERR_REGIONAL_BUDGET_NOT_FOUND)


def get_capacity_plan(plan_id):
    return _lookup("capacity_plans", plan_id, ERR_CAPACITY_PLAN_NOT_FOUND)


def get_transfer(transfer_id):
    return _lookup("transfers", transfer_id, ERR_MEMBER_TRANSFER_NOT_FOUND)


def get_quality_metric(metric_id):
    return _lookup("quality_metrics", metric_id, ERR_QUALITY_METRIC_NOT_FOUND)


def get_integration(integration_id):
    return _lookup("integrations", integration_id,
                   ERR_REFERENTIAL_INTEGRATION_NOT_FOUND)


def get_alert(alert_id):
    from errors import ERR_ALERT_NOT_FOUND
    return _lookup("alerts", alert_id, ERR_ALERT_NOT_FOUND)


def body_lookup(table, row_id, spec):
    row = getattr(STORE, table).get(row_id)
    if row is None:
        raise_error(spec)
    return row


def require_body_reference(table, row_id):
    """Body-supplied ids resolve to a stored row or ERR_REFERENCED_RESOURCE_NOT_FOUND."""
    if row_id is None:
        return None
    row = getattr(STORE, table).get(row_id)
    if row is None:
        raise_error(ERR_REFERENCED_RESOURCE_NOT_FOUND)
    return row


def require_body_reference_any(table, row_id, as_id=True):
    row = getattr(STORE, table).get(row_id)
    if row is None:
        raise_error(ERR_REFERENCED_RESOURCE_NOT_FOUND)
    return row["id"] if as_id else row


# -------------------------------------------------------- optimistic concurrency

def check_member_version(member, supplied):
    if supplied is None:
        raise_error(ERR_STALE_VERSION)
    try:
        supplied_int = int(supplied)
    except (TypeError, ValueError):
        raise_error(ERR_STALE_VERSION)
    if supplied_int != int(member.get("version", 1)):
        raise_error(ERR_STALE_VERSION)
    return True


# --------------------------------------------------------------- posture gate

def posture_of_region(region_id):
    region = STORE.regions.get(region_id)
    if region is None:
        return None
    return region_view(region)["posture"]


def enforce_posture_gate(region_id):
    region = STORE.regions.get(region_id)
    if region is None:
        return
    if region_view(region)["posture"] == "FROZEN":
        raise_error(ERR_REGION_POSTURE_FROZEN)


# -------------------------------------------------------------- fiscal line

def staffing_and_facility_of(region_id):
    return int(region_view(get_region(region_id))["staffing_and_facility_cents"])


def latest_budget_for(region_id):
    budgets = [b for b in STORE.budgets.values()
               if b.get("region_id") == region_id]
    if not budgets:
        return None
    budgets.sort(key=lambda b: (b.get("created_at", ""), b.get("id", "")))
    return budgets[-1]


def perfor_m_fiscal_line_check(region_id):
    """PRD 2.10: staffing_and_facility_cents must not exceed the latest
    RegionalBudget staffing line; and when the figure has reached that line
    while the latest budget is not APPROVED the write is refused."""
    budget = latest_budget_for(region_id)
    if budget is None:
        return
    figure = staffing_and_facility_of(region_id)
    line = int(budget.get("staffing_budget_cents") or 0)
    if figure > line:
        raise_error(ERR_BUDGET_FISCAL_LINE_EXCEEDED)
    if figure >= line and budget.get("status") != "APPROVED":
        raise_error(ERR_BUDGET_FISCAL_LINE_EXCEEDED)


# --------------------------------------------------------- membership rollups

def recompute_provider_panel(provider):
    panel = [m for m in STORE.members.values()
             if m.get("attributed_provider_id") == provider["id"]
             and m.get("status") == "ACTIVE"]
    provider["panel_size_assigned"] = len(panel)
    component = panel_capitation_component_cents(
        provider["panel_size_assigned"], provider["specialty"])
    provider["panel_capitation_component_cents"] = component
    provider["quality_bonus_cents"] = calc_quality_bonus(
        provider.get("base_component_cents", 0), component,
        provider.get("quality_score", 0))
    provider["volume_component_cents"] = 0
    provider["comp_total_cents"] = provider_comp_total_cents(
        provider.get("base_component_cents", 0), component,
        provider["quality_bonus_cents"], 0)
    return provider


def recompute_region_providers(region_id, bump_versions=True):
    touched = []
    for provider in STORE.providers.values():
        if provider.get("region_id") != region_id:
            continue
        recompute_provider_panel(provider)
        if bump_versions:
            touch(provider)
        touched.append(provider)
    return touched


def recompute_member_capitation(member):
    region = STORE.regions.get(member["region_id"])
    if region is None:
        return member
    member["capitation_rate_cents"] = capitation_rate_cents(
        member["plan_product"], member.get("risk_score", 1),
        region.get("capitation_index", 1))
    return member


def recompute_region_aggregates(region_id, bump_version=True):
    region = STORE.regions.get(region_id)
    if region is None:
        return None
    view = region_view(region)
    for field in ("premium_revenue_cents", "employed_delivery_cost_cents",
                  "outside_services_spend_cents", "staffing_and_facility_cents",
                  "operating_margin_cents", "computed_margin_cents",
                  "referential_integration_credit_cents", "open_alert_count",
                  "capacity_budget_appointments",
                  "capacity_committed_appointments", "access_breach_pct",
                  "quality_composite_score", "member_count"):
        region[field] = view[field]
    if bump_version:
        touch(region)
    return region


def replay_region_capitation(region_id):
    for member in STORE.members.values():
        if member.get("region_id") == region_id:
            recompute_member_capitation(member)


# ------------------------------------------------------------- alert machinery

def raise_alert(region_id, alert_type, severity, ref_type, ref_id):
    row = new_record(
        region_id=region_id,
        alert_type=alert_type,
        severity=severity,
        payload_ref_type=ref_type,
        payload_ref_id=ref_id,
        raised_at=now_iso(),
        status="RAISED",
    )
    store_row("alerts", row)
    return row


# ------------------------------------------------------- appointment helpers

def appointments_of_department(department_id):
    return [a for a in STORE.appointments.values()
            if a.get("department_id") == department_id]


def committed_appointments_for(department_id, period=None):
    rows = []
    for appointment in appointments_of_department(department_id):
        if appointment.get("fulfillment_status") not in NON_CANCELLED_APPOINTMENT_STATUSES:
            continue
        if period is not None and period_of(appointment.get("start_utc")) != period:
            continue
        rows.append(appointment)
    return rows


def capacity_plan_for(department_id, period):
    for plan in STORE.capacity_plans.values():
        if plan.get("department_id") == department_id and plan.get("period") == period:
            return plan
    return None


def refresh_capacity_plan(plan):
    """Recompute committed_slots / shortfall and advance recalculation_epoch."""
    plan["recalculation_epoch"] = int(plan.get("recalculation_epoch", 1) or 1) + 1
    return plan


def auto_review_overcommitted_plans(region_id):
    """An ACTIVE plan whose committed_slots grows past its budgeted_slots is
    moved back to UNDER_REVIEW automatically (PRD 3.3 / the ACTIVE ->
    UNDER_REVIEW trigger)."""
    changed = False
    for plan in STORE.capacity_plans.values():
        if plan.get("region_id") != region_id:
            continue
        if plan.get("status") != "ACTIVE":
            continue
        committed = len(committed_appointments_for(
            plan["department_id"], plan.get("period")))
        if committed > int(plan.get("budgeted_slots") or 0):
            plan["status"] = "UNDER_REVIEW"
            touch(plan)
            changed = True
    return changed


def referrals_targeting_region(region_id):
    out = []
    for referral in STORE.referrals.values():
        department = STORE.departments.get(referral.get("target_department_id"))
        if department is not None and department.get("region_id") == region_id:
            out.append(referral)
    return out


def region_has_open_capacity_breach(region_id):
    view = region_view(get_region(region_id))
    return view["capacity_committed_appointments"] > view["capacity_budget_appointments"]


# -------------------------------------------------------- the posture engine

def run_posture_ladder(region_id, depth=0):
    """PRD 2.4 / 3.8. Evaluated automatically; carries its tier cascades."""
    if depth > 6:
        return
    region = STORE.regions.get(region_id)
    if region is None:
        return
    view = region_view(region)
    margin = view["operating_margin_cents"]
    posture = view["posture"]
    capacity_breach = (view["capacity_committed_appointments"]
                       > view["capacity_budget_appointments"])

    if posture == "OPEN" and margin < 0:
        _enter_restricted_fiscal(region, view)
        return
    if posture == "OPEN" and capacity_breach:
        _enter_restricted_capacity(region, view)
        return
    if posture == "RESTRICTED" and margin < -MARGIN_FREEZE_FLOOR_CENTS:
        _enter_frozen(region, view)
        return
    if posture == "RESTRICTED" and margin >= 0:
        region["posture"] = "OPEN"
        for referral in referrals_targeting_region(region_id):
            if referral.get("status") == "HELD":
                referral["status"] = "PENDING_TRIAGE"
                touch(referral)
        touch(region)
        recompute_region_aggregates(region_id, bump_version=False)
        return
    if posture == "FROZEN" and margin >= 0:
        region["posture"] = "RESTRICTED"
        touch(region)
        recompute_region_aggregates(region_id, bump_version=False)
        return
    _ = depth


def _enter_restricted_fiscal(region, view):
    """OPEN -> RESTRICTED on a negative settled margin, with the wide tier."""
    region_id = region["id"]
    region["posture"] = "RESTRICTED"
    touch(region)

    for plan in STORE.capacity_plans.values():
        if plan.get("region_id") != region_id:
            continue
        if plan.get("status") not in ("PLANNING", "UNDER_REVIEW", "ACTIVE", "ADJUSTED"):
            continue
        refresh_capacity_plan(plan)
        touch(plan)

    for department in STORE.departments.values():
        if department.get("region_id") != region_id:
            continue
        committed = len(committed_appointments_for(department["id"]))
        budgeted = int(department.get("appointment_slots_budgeted") or 0)
        if committed >= budgeted or department.get("status") == "CONSTRAINED":
            if department.get("status") == "OPEN":
                department["status"] = "CONSTRAINED"
                touch(department)

    for referral in referrals_targeting_region(region_id):
        if referral.get("status") != "PENDING_TRIAGE":
            continue
        referral["status"] = "HELD"
        touch(referral)
        _hold_requested_appointments(referral["id"])

    raise_alert(region_id, "POSTURE_CHANGE", "INFO", "Region", region_id)
    recompute_region_aggregates(region_id, bump_version=False)
    _ = view


def _enter_restricted_capacity(region, view):
    """OPEN -> RESTRICTED on a capacity overshoot, with the narrow tier."""
    region_id = region["id"]
    region["posture"] = "RESTRICTED"
    touch(region)

    for referral in referrals_targeting_region(region_id):
        if referral.get("status") == "PENDING_TRIAGE":
            referral["status"] = "HELD"
            touch(referral)

    for provider in STORE.providers.values():
        if provider.get("region_id") != region_id:
            continue
        if provider.get("status") == "ACTIVE":
            provider["status"] = "PANEL_CLOSED"
            touch(provider)

    raise_alert(region_id, "CAPACITY_SHORTFALL", "WARNING", "Region", region_id)
    recompute_region_aggregates(region_id, bump_version=False)
    _ = view


def _enter_frozen(region, view):
    region_id = region["id"]
    region["posture"] = "FROZEN"
    touch(region)

    for provider in STORE.providers.values():
        if provider.get("region_id") == region_id and provider.get("status") == "ACTIVE":
            provider["status"] = "PANEL_CLOSED"
            touch(provider)

    for plan in STORE.capacity_plans.values():
        if plan.get("region_id") == region_id and plan.get("status") == "ACTIVE":
            plan["status"] = "FROZEN"
            touch(plan)

    raise_alert(region_id, "POSTURE_CHANGE", "CRITICAL", "Region", region_id)
    recompute_region_aggregates(region_id, bump_version=False)
    _ = view


def _hold_requested_appointments(referral_id):
    for appointment in STORE.appointments.values():
        if appointment.get("referral_id") != referral_id:
            continue
        if appointment.get("fulfillment_status") == "REQUESTED":
            appointment["hold_status"] = "REFERRAL_HOLD"
            touch(appointment)


# --------------------------------------------------- referral helpers

def specialty_of_service(service_code):
    """PRD 3.5: a referral's service_code is a specialty enum value verbatim."""
    return service_code


def qualifying_departments(region_id, service_code, exclude_closed=True):
    rows = []
    for department in STORE.departments.values():
        if department.get("region_id") != region_id:
            continue
        if department.get("specialty") != specialty_of_service(service_code):
            continue
        if not department.get("accepting_internal_referrals", True):
            continue
        if exclude_closed and department.get("status") not in ("OPEN", "CONSTRAINED"):
            continue
        rows.append(department)
    return rows


def in_network_available(region_id, service_code):
    return len(qualifying_departments(region_id, service_code)) > 0


def rank_candidate_departments(region_id, service_code):
    candidates = qualifying_departments(region_id, service_code)
    candidates.sort(key=lambda d: (
        -(int(d.get("appointment_slots_budgeted") or 0)
          - len(committed_appointments_for(d["id"]))),
        d.get("created_at", ""),
        d.get("id", ""),
    ))
    return candidates


def referral_is_expired(referral):
    expires_at = referral.get("expires_at")
    if not expires_at:
        return False
    return CLOCK.now() >= parse_iso8601(expires_at)


def expire_authorized_referrals():
    """PRD 3.5: an AUTHORIZED referral at or past expires_at becomes EXPIRED."""
    for referral in STORE.referrals.values():
        if referral.get("status") == "AUTHORIZED" and referral_is_expired(referral):
            referral["status"] = "EXPIRED"
            touch(referral)


def triage_window_expired(referral):
    created = parse_iso8601(referral["created_at"])
    window_end = created.timestamp() + REFERRAL_TRIAGE_WINDOW_DAYS * 86400
    return CLOCK.now().timestamp() > window_end


# ------------------------------------------------------- panel rate helpers

def panel_rate_for(specialty):
    return PANEL_RATE_CENTS.get(specialty, 0)


def cross_region_ok(referral_type, claim_type):
    """The two declared cross-region exceptions (PRD 2.5)."""
    return referral_type == "OUTSIDE_NETWORK" or claim_type == "OUT_OF_AREA"


def enforce_same_region(reference_region_id, *region_ids):
    for candidate in region_ids:
        if candidate is None:
            continue
        if candidate != reference_region_id:
            raise_error(ERR_CROSS_REGION_REFERENCE)


def flip_appointment_status(appointment, status):
    appointment["fulfillment_status"] = status
    touch(appointment)


def region_of_department(department):
    return department.get("region_id")


def region_of_provider(provider):
    return provider.get("region_id")


def region_of_member(member):
    return member.get("region_id")


def in_force(member):
    return member.get("status") in IN_FORCE_MEMBER_STATUSES