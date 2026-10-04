"""Read-side projections.

Stored rows hold the persisted fields; these functions fill in every
`source: computed` field so that reads always report live aggregates.
"""

from constants import (
    FTE_COST_CENTS,
    INTEGRATION_CREDIT_RATE,
    WEIGHT_BY_METRIC,
    PANEL_RATE_CENTS,
)
from calculations import (
    access_breach_pct,
    mean_wait_days,
    panel_capitation_component_cents,
    quality_bonus_cents as calc_quality_bonus,
    region_quality_composite_score,
    staffing_and_facility_cents as calc_staffing,
    supply_shortfall_slots,
    utilization_pct,
)
from db import STORE
from rounding import dec, round_half_up_int

IN_FORCE_MEMBER_STATUSES = ("ACTIVE", "TRANSFER_PENDING")
CAPACITY_PLAN_OPEN_STATUSES = ("ACTIVE", "ADJUSTED", "UNDER_REVIEW")
COMMITTED_APPOINTMENT_STATUSES = ("REQUESTED", "SCHEDULED", "COMPLETED")
NON_TERMINAL_INTEGRATION_STATUSES = ("BOUND", "ENROLLED", "CONTRACTED")
BOOKED_CLAIM_STATUSES = ("PAID", "ADJUDICATED")


# ------------------------------------------------------------------ helpers

def children(table, **filters):
    rows = []
    for row in getattr(STORE, table).values():
        if all(row.get(key) == value for key, value in filters.items()):
            rows.append(row)
    return rows


def departments_of_region(region_id):
    return [d for d in STORE.departments.values() if d["region_id"] == region_id]


def providers_of_region(region_id):
    return [p for p in STORE.providers.values() if p["region_id"] == region_id]


def members_of_region(region_id):
    return [m for m in STORE.members.values() if m["region_id"] == region_id]


def period_of(start_utc):
    """The YYYY-MM period a start instant falls in."""
    if not start_utc:
        return None
    return str(start_utc)[:7]


def member_is_in_force(member):
    return member.get("status") in IN_FORCE_MEMBER_STATUSES


# ------------------------------------------------------------- member view

def member_view(member):
    return dict(member)


# ----------------------------------------------------------- provider view

def provider_view(provider):
    out = dict(provider)
    panel = [m for m in STORE.members.values()
             if m.get("attributed_provider_id") == provider["id"]
             and m.get("status") == "ACTIVE"]
    out["panel_size_assigned"] = len(panel)
    component = panel_capitation_component_cents(
        out["panel_size_assigned"], provider["specialty"])
    out["panel_capitation_component_cents"] = component
    bonus = calc_quality_bonus(provider["base_component_cents"], component,
                               provider.get("quality_score", 0))
    out["quality_bonus_cents"] = bonus
    out["volume_component_cents"] = 0
    out["comp_total_cents"] = (int(provider["base_component_cents"])
                               + component + bonus)
    return out


# -------------------------------------------------------------- department

def department_view(department):
    out = dict(department)
    committed = 0
    for appointment in STORE.appointments.values():
        if appointment["department_id"] != department["id"]:
            continue
        if appointment["fulfillment_status"] in COMMITTED_APPOINTMENT_STATUSES:
            committed += 1
    out["appointment_slots_committed"] = committed
    return out


# ------------------------------------------------------------- care site

def care_site_view(site):
    return dict(site)


# ---------------------------------------------------------- appointment

def appointment_view(appointment):
    return dict(appointment)


# ------------------------------------------------------------- referral

def referral_view(referral):
    return dict(referral)


# ----------------------------------------------------------- network service

def network_service_view(service):
    providers = [p for p in providers_of_region(service["region_id"])
                 if p.get("status") == "ACTIVE"
                 and p.get("specialty") == service["service_code"]]
    out = dict(service)
    out["available_provider_count"] = len(providers)
    return out


# ------------------------------------------------------------ claim view

def claim_view(claim):
    out = dict(claim)
    out["final_liability_cents"] = int(claim.get("final_liability_cents") or 0)
    return out


# ---------------------------------------------------- regional budget view

def _integration_outside_reported(region_id):
    """The unposted remainder of each integration, reported as outside-services
    spending on the region's budget (PRD 3.11)."""
    return int(STORE.integration_outside.get(region_id, 0) or 0)


def regional_budget_view(budget):
    region_id = budget["region_id"]
    period = budget.get("period")
    committed = _integration_outside_reported(region_id)
    for claim in STORE.claims.values():
        if claim.get("region_id") != region_id:
            continue
        if claim.get("status") in ("ADJUDICATED", "PAID"):
            committed += int(claim.get("final_liability_cents") or 0)
        elif claim.get("status") not in ("DENIED", "CANCELLED"):
            # A claim books its forward-looking provisional at submission, so
            # the budget's committed figure leads the settled one (PRD 3.6).
            committed += int(claim.get("provisional_liability_cents") or 0)

    deductible = int(budget.get("system_deductible_cents") or 0)
    out = dict(budget)
    out["outside_services_committed_cents"] = committed
    out["division_deductible_cents"] = deductible
    out["division_deductible_original_cents"] = deductible
    rate = dec(budget.get("ort_contract_rate", 1) or 1)
    division_liability = round_half_up_int(dec(committed) * rate) - deductible
    out["division_liability_cents"] = division_liability
    out["net_liability_cents"] = division_liability - deductible
    region = STORE.regions.get(region_id)
    premium = int(region.get("premium_revenue_cents", 0)) if region else 0
    employed = int(region.get("employed_delivery_cost_cents", 0)) if region else 0
    out["premium_revenue_cents"] = premium
    out["employed_delivery_cost_cents"] = employed
    out["operating_margin_cents"] = (
        premium
        - int(budget.get("staffing_budget_cents") or 0)
        - committed
        - int(budget.get("facility_investment_cents") or 0)
        - employed)
    _ = period
    return out


# ------------------------------------------------------- capacity plan view

def capacity_plan_view(plan):
    out = dict(plan)
    committed = 0
    department_id = plan.get("department_id")
    period = plan.get("period")
    for appointment in STORE.appointments.values():
        if appointment.get("department_id") != department_id:
            continue
        if appointment.get("fulfillment_status") not in COMMITTED_APPOINTMENT_STATUSES:
            continue
        if period is not None and period_of(appointment.get("start_utc")) != period:
            continue
        committed += 1
    out["committed_slots"] = committed
    out["supply_shortfall_slots"] = supply_shortfall_slots(
        committed, plan.get("budgeted_slots", 0))
    out["utilization_pct"] = utilization_pct(
        committed, plan.get("budgeted_slots", 0))
    out["recalculation_epoch"] = int(plan.get("recalculation_epoch", 1) or 1)
    return out


# ------------------------------------------------------ member transfer view

def member_transfer_view(transfer):
    return dict(transfer)


# -------------------------------------------------------- quality metric view

def quality_metric_view(metric):
    return dict(metric)


# --------------------------------------------------- referential integration

def referential_integration_view(integration):
    return dict(integration)


# ------------------------------------------------------------------- alert

def alert_view(alert):
    return dict(alert)


# ------------------------------------------------------------------ region

def region_view(region):
    region_id = region["id"]
    members = members_of_region(region_id)
    in_force = [m for m in members if member_is_in_force(m)]
    premium = sum(int(m.get("capitation_rate_cents") or 0) for m in in_force)
    # A referential integration's posted settlement is premium revenue the
    # region actually received (PRD 3.11), held separately from member
    # capitation so that the member-derived rollup stays exactly as defined.
    premium += int(STORE.integration_premium.get(region_id, 0) or 0)

    providers = providers_of_region(region_id)
    employed = 0
    for provider in providers:
        view = provider_view(provider)
        employed += int(view["comp_total_cents"])

    outside = 0
    for claim in STORE.claims.values():
        if claim.get("region_id") != region_id:
            continue
        if claim.get("status") in BOOKED_CLAIM_STATUSES:
            outside += int(claim.get("final_liability_cents") or 0)

    sites = [s for s in STORE.care_sites.values()
             if s.get("region_id") == region_id]
    staffing = calc_staffing(sites)

    operating_margin = premium - employed - outside - staffing

    # Forward variant: live risk scores plus integration credit.
    expected_premium = sum(
        _recompute_member_capitation(m, region) for m in in_force)
    credit = 0
    for integration in STORE.integrations.values():
        if integration.get("region_id") != region_id:
            continue
        if integration.get("status") not in NON_TERMINAL_INTEGRATION_STATUSES:
            continue
        rate = INTEGRATION_CREDIT_RATE.get(
            integration.get("risk_sharing_model"), dec(0))
        credit += round_half_up_int(
            dec(integration.get("cost_reporting_basis_cents") or 0) * rate)
    computed_margin = expected_premium - employed - outside - staffing

    plans = [p for p in STORE.capacity_plans.values()
             if p.get("region_id") == region_id
             and p.get("status") in CAPACITY_PLAN_OPEN_STATUSES]
    budget_appointments = sum(int(p.get("budgeted_slots") or 0) for p in plans)
    committed_appointments = 0
    for plan in plans:
        committed_appointments += capacity_plan_view(plan)["committed_slots"]

    department_ids = {d["id"] for d in departments_of_region(region_id)}
    appointments = [a for a in STORE.appointments.values()
                    if a.get("department_id") in department_ids]
    non_cancelled = [a for a in appointments
                     if a.get("fulfillment_status") != "CANCELLED"]
    breached = [a for a in non_cancelled
                if a.get("access_status") == "BREACHED_ACCESS_TARGET"]

    metrics = [m for m in STORE.quality_metrics.values()
               if m.get("region_id") == region_id]

    alerts = [a for a in STORE.alerts.values()
              if a.get("region_id") == region_id and a.get("status") == "RAISED"]

    out = dict(region)
    out["premium_revenue_cents"] = premium
    out["employed_delivery_cost_cents"] = employed
    out["outside_services_spend_cents"] = outside
    out["staffing_and_facility_cents"] = staffing
    out["operating_margin_cents"] = operating_margin
    out["computed_margin_cents"] = computed_margin
    out["referential_integration_credit_cents"] = credit
    out["open_alert_count"] = len(alerts)
    out["capacity_budget_appointments"] = budget_appointments
    out["capacity_committed_appointments"] = committed_appointments
    out["access_breach_pct"] = access_breach_pct(len(breached), len(non_cancelled))
    out["quality_composite_score"] = region_quality_composite_score(metrics)
    out["member_count"] = len(in_force)
    target_pct = dec(region.get("margin_target_pct") or 0)
    out["margin_gap_cents"] = operating_margin - round_half_up_int(
        dec(premium) * target_pct)
    return out


def _recompute_member_capitation(member, region):
    from calculations import capitation_rate_cents
    return capitation_rate_cents(
        member["plan_product"], member.get("risk_score", 1),
        region.get("capitation_index", 1))


VIEWS = {
    "regions": region_view,
    "members": member_view,
    "care_sites": care_site_view,
    "departments": department_view,
    "providers": provider_view,
    "network_services": network_service_view,
    "appointments": appointment_view,
    "referrals": referral_view,
    "claims": claim_view,
    "budgets": regional_budget_view,
    "capacity_plans": capacity_plan_view,
    "transfers": member_transfer_view,
    "quality_metrics": quality_metric_view,
    "integrations": referential_integration_view,
    "alerts": alert_view,
}


def view(table, row):
    fn = VIEWS.get(table)
    if fn is None:
        return dict(row)
    return fn(row)


def commit_current_period(appointment):
    """Unused placeholder retained for symmetry with the capacity rule."""
    return period_of(appointment.get("start_utc"))


def mean_wait_for(region_id, period):
    department_ids = {d["id"] for d in departments_of_region(region_id)}
    rows = []
    for appointment in STORE.appointments.values():
        if appointment.get("department_id") not in department_ids:
            continue
        if appointment.get("fulfillment_status") == "CANCELLED":
            continue
        if period is not None and period_of(appointment.get("start_utc")) != period:
            continue
        rows.append(appointment)
    return mean_wait_days(rows)


def panel_rate_for(specialty):
    return PANEL_RATE_CENTS.get(specialty, 0)


def fte_cost_cents():
    return FTE_COST_CENTS


def metric_weight(metric_code):
    return WEIGHT_BY_METRIC.get(metric_code, dec(0))