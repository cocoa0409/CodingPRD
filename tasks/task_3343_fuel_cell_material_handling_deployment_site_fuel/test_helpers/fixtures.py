"""Composite setup helpers.

Every fixture builds preconditions from scratch via PRD-declared endpoints —
each test runs against a freshly restarted server with an empty database.
Setup calls use get_success_data() so failures surface as clear setup errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_OCT_2026
from .factories import (
    create_site_payload, create_assessment_payload, create_supply_contract_payload,
    create_station_payload, create_permit_payload, create_technician_payload,
    create_conversion_plan_payload, create_conversion_event_payload,
    create_service_agreement_payload, create_downtime_report_payload,
    create_fueling_event_payload, create_invoice_payload,
    create_incentive_claim_payload, create_training_record_payload,
)
from .test_users import TEST_USERS, make_conversion_technician_headers

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["site_manager_headers"]
SAFETY = TEST_USERS["safety_officer_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
BILLING = TEST_USERS["billing_operator_headers"]


# ---------------------------------------------------------------- clock

def set_clock(to_iso8601=CLOCK_OCT_2026):
    """Advance the logical clock (PlatformAdmin-only, PRD §2.5)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------- sites

def create_site(clock=CLOCK_OCT_2026, **overrides):
    """Set the clock and create an ACTIVE site. Returns the site dict."""
    if clock is not None:
        set_clock(clock)
    return get_success_data(api_client.create_site(create_site_payload(**overrides), MANAGER))


def get_site(site_id):
    return get_success_data(api_client.get_site(site_id, MANAGER))


# ---------------------------------------------------------------- assessments

def create_approved_assessment(site_id, **overrides):
    """Create an assessment and walk it DRAFT -> SUBMITTED -> APPROVED."""
    ass = get_success_data(api_client.create_assessment(
        site_id, create_assessment_payload(**overrides), MANAGER))
    get_success_data(api_client.submit_assessment(site_id, ass["id"], MANAGER))
    return get_success_data(api_client.approve_assessment(site_id, ass["id"], SAFETY))


# ---------------------------------------------------------------- contracts

def create_active_contract(site_id, **overrides):
    """Create a supply contract and activate it. Returns the ACTIVE contract."""
    contract = get_success_data(api_client.create_supply_contract(
        site_id, create_supply_contract_payload(**overrides), MANAGER))
    return get_success_data(
        api_client.activate_supply_contract(site_id, contract["id"], MANAGER))


# ---------------------------------------------------------------- stations

def create_planned_station(site_id, **overrides):
    return get_success_data(api_client.create_station(
        site_id, create_station_payload(**overrides), MANAGER))


def file_and_issue_permit(station_id, permit_type, issued_date="2026-10-01",
                           expiry_date="2027-01-01"):
    permit = get_success_data(api_client.create_permit(
        station_id, create_permit_payload(
            permit_type=permit_type, issued_date=issued_date, expiry_date=expiry_date),
        MANAGER))
    get_success_data(api_client.issue_permit(station_id, permit["id"], COMPLIANCE))
    return permit


def create_commissioned_station(site_id, location_type="OUTDOOR", **overrides):
    """Station walked to COMMISSIONED: CONSTRUCTION+FIRE permits issued (plus
    DISPENSING_INDOOR for INDOOR siting), construction started, commissioned."""
    station = create_planned_station(site_id, location_type=location_type, **overrides)
    file_and_issue_permit(station["id"], "CONSTRUCTION")
    file_and_issue_permit(station["id"], "FIRE")
    if location_type == "INDOOR":
        file_and_issue_permit(station["id"], "DISPENSING_INDOOR")
    get_success_data(api_client.start_construction(station["id"], MANAGER))
    return get_success_data(api_client.commission_station(station["id"], COMPLIANCE))


# ---------------------------------------------------------------- technicians

def create_technician(**overrides):
    return get_success_data(api_client.create_technician(
        create_technician_payload(**overrides), ADMIN))


def tech_headers(technician_id):
    """Ownership-gated ConversionTechnician headers (PRD §2.1 identity)."""
    return make_conversion_technician_headers(technician_id)


# ---------------------------------------------------------------- plans & events

def create_scheduled_plan(site_id, **overrides):
    """Create a plan and schedule it (assumes the site already has an APPROVED
    assessment covering target_forklift_count). Returns the SCHEDULED plan."""
    plan = get_success_data(api_client.create_conversion_plan(
        site_id, create_conversion_plan_payload(**overrides), MANAGER))
    return get_success_data(api_client.schedule_plan(
        site_id, plan["id"], {"expected_plan_version": plan["version"]}, MANAGER))


def create_event(plan_id, technician_id, **overrides):
    return get_success_data(api_client.create_conversion_event(
        plan_id, create_conversion_event_payload(
            technician_id=technician_id, **overrides), MANAGER))


def start_event(plan_id, event_id, technician_id):
    return get_success_data(api_client.start_event(
        plan_id, event_id, tech_headers(technician_id)))


def complete_event(plan_id, event_id, technician_id):
    return get_success_data(api_client.complete_event(
        plan_id, event_id, tech_headers(technician_id)))


def create_completed_plan(site_id, technician_id, num_events=1, plan_overrides=None,
                          event_overrides=None):
    """Site must already hold an APPROVED assessment. Creates a plan, schedules
    it, creates all events up front (completing the last event while others are
    still live must bubble the plan to COMPLETED only when every sibling is
    terminal, so no event may be created after another completed), then runs
    each through start+complete. Returns (plan, [events])."""
    plan = create_scheduled_plan(
        site_id, target_forklift_count=num_events, **(plan_overrides or {}))
    events = []
    for i in range(num_events):
        overrides = dict(event_overrides or {})
        overrides.setdefault("forklift_id", f"FL-{i + 1}")
        day = 2 + i  # keep windows disjoint per technician
        overrides.setdefault("scheduled_start", f"2026-10-{day:02d}T08:00:00Z")
        overrides.setdefault("scheduled_end", f"2026-10-{day:02d}T12:00:00Z")
        events.append(create_event(plan["id"], technician_id, **overrides))
    done = []
    for ev in events:
        start_event(plan["id"], ev["id"], technician_id)
        done.append(complete_event(plan["id"], ev["id"], technician_id))
    return get_success_data(api_client.get_conversion_plan(plan["id"], MANAGER)), done


# ---------------------------------------------------------------- agreements & downtime

def create_active_agreement(site_id, **overrides):
    agr = get_success_data(api_client.create_service_agreement(
        site_id, create_service_agreement_payload(**overrides), MANAGER))
    return get_success_data(
        api_client.activate_service_agreement(site_id, agr["id"], MANAGER))


def report_downtime(site_id, **overrides):
    return get_success_data(api_client.create_downtime_report(
        site_id, create_downtime_report_payload(**overrides), MANAGER))


# ---------------------------------------------------------------- fueling & invoices

def create_fueling_event(station_id, contract_id, **overrides):
    return get_success_data(api_client.create_fueling_event(
        station_id, create_fueling_event_payload(
            supply_contract_id=contract_id, **overrides), MANAGER))


def create_draft_invoice(site_id, contract_id, **overrides):
    return get_success_data(api_client.create_invoice(
        create_invoice_payload(site_id=site_id, supply_contract_id=contract_id,
                               **overrides), BILLING))


def add_line(invoice_id, fueling_event_id, expected_invoice_version):
    """Add a line under the OCC guard (PRD §2.9). Returns the line-item dict."""
    return get_success_data(api_client.add_line_item(
        invoice_id, {"fueling_event_id": fueling_event_id,
                     "expected_invoice_version": expected_invoice_version}, BILLING))


def create_invoice_with_lines(site_id, contract_id, event_ids,
                              period_start="2026-10-01", period_end="2026-11-01"):
    """DRAFT invoice with one line per event id; threads the OCC version —
    each line add bumps the invoice version by exactly 1 (PRD §2.4, §3.6).
    Returns (invoice_dict_after_first_read, [lines])."""
    invoice = create_draft_invoice(site_id, contract_id,
                                   period_start=period_start, period_end=period_end)
    version = invoice["version"]
    lines = []
    for event_id in event_ids:
        lines.append(add_line(invoice["id"], event_id, version))
        version += 1
    fresh = get_success_data(api_client.get_invoice(invoice["id"], BILLING))
    return fresh, lines


def setup_billing_scenario(site_code="S-BILL", supply_mode="PIPELINE",
                           base_price_per_kg=2.5, committed_monthly_kg=100,
                           contract_overrides=None, station_overrides=None):
    """ACTIVE site + ACTIVE contract + COMMISSIONED OUTDOOR station.
    Returns (site, contract, station)."""
    site = create_site(code=site_code)
    contract_kw = dict(supply_mode=supply_mode, base_price_per_kg=base_price_per_kg,
                       committed_monthly_kg=committed_monthly_kg)
    contract_kw.update(contract_overrides or {})
    contract = create_active_contract(site["id"], **contract_kw)
    station = create_commissioned_station(site["id"], **(station_overrides or {}))
    return site, contract, station


# ---------------------------------------------------------------- incentive claims

def create_submitted_claim(site_id, **overrides):
    claim = get_success_data(api_client.create_incentive_claim(
        site_id, create_incentive_claim_payload(**overrides), MANAGER))
    get_success_data(api_client.submit_claim(site_id, claim["id"], MANAGER))
    return get_success_data(api_client.get_incentive_claim(claim["id"], COMPLIANCE))


def setup_site_with_completed_conversion(site_code, technician_name, num_events=1,
                                         plan_overrides=None, assessment_overrides=None,
                                         record_productivity=None):
    """Full conversion lifecycle: site + APPROVED assessment + technician +
    COMPLETED plan with `num_events` COMPLETED events; optionally records
    productivity (record_productivity = (measurement_mode, reported_units)).
    Returns (site, plan, events, technician)."""
    site = create_site(code=site_code)
    tech = create_technician(name=technician_name)
    create_approved_assessment(site["id"], **(assessment_overrides or {}))
    plan, events = create_completed_plan(
        site["id"], tech["id"], num_events=num_events,
        plan_overrides=plan_overrides)
    if record_productivity is not None:
        mode, reported = record_productivity
        get_success_data(api_client.record_productivity(
            site["id"], {"measurement_mode": mode, "reported_units_per_hour": reported},
            MANAGER))
    return site, plan, events, tech
