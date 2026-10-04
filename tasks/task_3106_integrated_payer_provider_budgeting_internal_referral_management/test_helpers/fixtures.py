"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch with PRD-declared endpoints
only, because the harness restarts the server (empty database) before each test.
``get_success_data()`` is used internally so a setup failure surfaces as a
clear "Setup step failed" error rather than a confusing assertion failure.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START_UTC, TEST_DEFAULTS
from .factories import (
    create_appointment_payload,
    create_capacity_plan_payload,
    create_care_site_payload,
    create_department_payload,
    create_member_payload,
    create_member_transfer_payload,
    create_outside_service_claim_payload,
    create_provider_payload,
    create_quality_metric_payload,
    create_referral_payload,
    create_region_payload,
    create_regional_budget_payload,
    set_clock_payload,
)
from .test_users import TEST_USERS

RFO = TEST_USERS["regional_finance_officer_headers"]
UR = TEST_USERS["utilization_reviewer_headers"]
AS = TEST_USERS["access_scheduler_headers"]
QRB = TEST_USERS["quality_review_board_headers"]
BAC = TEST_USERS["budget_appropriations_committee_headers"]
CTM = TEST_USERS["care_team_member_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ─── Tier 1: State progression / foundations ──────────

def set_logical_clock(to_iso8601=CLOCK_START_UTC):
    """Pin the logical clock. Returns the response data."""
    res = api_client.set_clock(set_clock_payload(to_iso8601), ADMIN)
    return get_success_data(res)


def create_open_region(**overrides) -> dict:
    """Create one region; it starts in the OPEN posture."""
    res = api_client.create_region(create_region_payload(**overrides), ADMIN)
    return get_success_data(res)


def create_care_site(region_id, **overrides) -> dict:
    res = api_client.create_care_site(
        region_id, create_care_site_payload(**overrides), RFO
    )
    return get_success_data(res)


def create_department(care_site_id, **overrides) -> dict:
    res = api_client.create_department(
        care_site_id, create_department_payload(**overrides), AS
    )
    return get_success_data(res)


def create_provider(care_site_id, **overrides) -> dict:
    res = api_client.create_provider(
        care_site_id, create_provider_payload(**overrides), RFO
    )
    return get_success_data(res)


def enroll_member(region_id, attributed_provider_id=None, **overrides) -> dict:
    res = api_client.create_member(
        region_id,
        create_member_payload(attributed_provider_id, **overrides),
        RFO,
    )
    return get_success_data(res)


def get_region(region_id) -> dict:
    return get_success_data(api_client.get_region(region_id, RFO))


def get_member(member_id) -> dict:
    return get_success_data(api_client.get_member(member_id, RFO))


def current_member_version(member_id) -> int:
    return get_member(member_id)["version"]


def get_capacity_plan(plan_id) -> dict:
    return get_success_data(api_client.get_capacity_plan(plan_id, RFO))


def get_provider(provider_id) -> dict:
    return get_success_data(api_client.get_provider(provider_id, RFO))


def get_referral(referral_id) -> dict:
    return get_success_data(api_client.get_referral(referral_id, UR))


def get_department(department_id) -> dict:
    return get_success_data(api_client.get_department(department_id, AS))


# ─── Tier 2: Entity hierarchy ─────────────────────────

def setup_region_site_department_provider(
    region_overrides=None,
    site_overrides=None,
    department_overrides=None,
    provider_overrides=None,
):
    """Region + CareSite + Department + Provider with no member yet.

    Returns (region, care_site, department, provider).
    """
    region = create_open_region(**(region_overrides or {}))
    care_site = create_care_site(region["id"], **(site_overrides or {}))
    department = create_department(care_site["id"], **(department_overrides or {}))
    provider = create_provider(care_site["id"], **(provider_overrides or {}))
    return region, care_site, department, provider


def setup_basic_scenario(
    region_overrides=None,
    site_overrides=None,
    department_overrides=None,
    provider_overrides=None,
    member_overrides=None,
):
    """Region + CareSite + Department + Provider + one attributed Member.

    Returns (region, care_site, department, provider, member).
    """
    region, care_site, department, provider = setup_region_site_department_provider(
        region_overrides, site_overrides, department_overrides, provider_overrides
    )
    member = enroll_member(region["id"], provider["id"], **(member_overrides or {}))
    return region, care_site, department, provider, member


def setup_two_sibling_departments(
    first_overrides=None,
    second_overrides=None,
    provider_overrides=None,
):
    """Region + site + two departments + one provider + one member.

    Returns (region, care_site, first_department, second_department, provider, member).
    """
    region = create_open_region()
    care_site = create_care_site(region["id"])
    first = create_department(care_site["id"], **(first_overrides or {}))
    second = create_department(care_site["id"], **(second_overrides or {}))
    provider = create_provider(care_site["id"], **(provider_overrides or {}))
    member = enroll_member(region["id"], provider["id"])
    return region, care_site, first, second, provider, member


def setup_two_regions_each_with_member(provider_overrides=None):
    """Two OPEN regions, each with a site, department, provider and member.

    Returns (region_a, region_b, site_a, site_b, dept_a, dept_b,
             provider_a, provider_b, member_a, member_b).
    """
    region_a = create_open_region(name="Source Region")
    site_a = create_care_site(region_a["id"], site_name="Source Office")
    dept_a = create_department(site_a["id"])
    provider_a = create_provider(
        site_a["id"], provider_name="Dr Source", **(provider_overrides or {})
    )
    member_a = enroll_member(region_a["id"], provider_a["id"], member_ref="M-SRC-1")

    region_b = create_open_region(
        name="Destination Region", state_codes=["NV"]
    )
    site_b = create_care_site(region_b["id"], site_name="Destination Office")
    dept_b = create_department(site_b["id"])
    provider_b = create_provider(
        site_b["id"], provider_name="Dr Destination", **(provider_overrides or {})
    )
    member_b = enroll_member(region_b["id"], provider_b["id"], member_ref="M-DST-1")

    return (region_a, region_b, site_a, site_b, dept_a, dept_b,
            provider_a, provider_b, member_a, member_b)


# ─── Tier 3: Lifecycle shortcuts ──────────────────────

def create_regional_budget(region_id, payload=None, **overrides) -> dict:
    """Open a RegionalBudget from an explicit payload or from defaults."""
    merged = dict(payload) if payload else {}
    merged.update(overrides)
    res = api_client.create_regional_budget(
        region_id, create_regional_budget_payload(**merged), RFO
    )
    return get_success_data(res)


def create_and_approve_budget(region_id, **overrides) -> dict:
    """Open a RegionalBudget, submit it and approve it. Returns the budget."""
    budget = get_success_data(
        api_client.create_regional_budget(
            region_id, create_regional_budget_payload(**overrides), RFO
        )
    )
    get_success_data(api_client.submit_budget(budget["id"], {}, RFO))
    return get_success_data(api_client.approve_budget(budget["id"], {}, BAC))


def create_submitted_budget(region_id, **overrides) -> dict:
    """Open a RegionalBudget and submit it, leaving it SUBMITTED."""
    budget = get_success_data(
        api_client.create_regional_budget(
            region_id, create_regional_budget_payload(**overrides), RFO
        )
    )
    return get_success_data(api_client.submit_budget(budget["id"], {}, RFO))


def create_and_approve_budget_for(region_id, **overrides) -> dict:
    return create_and_approve_budget(region_id, **overrides)


def setup_approved_budget_scenario(budget_overrides=None, member_overrides=None):
    """Basic scenario plus an APPROVED operating budget for 2026-09.

    Returns (region, care_site, department, provider, member, budget).
    """
    region, care_site, department, provider, member = setup_basic_scenario(
        member_overrides=member_overrides
    )
    budget = create_and_approve_budget(region["id"], **(budget_overrides or {}))
    return region, care_site, department, provider, member, budget


def submit_claim(region_id, member_id, expected_member_version, **overrides) -> dict:
    res = api_client.submit_outside_service_claim(
        region_id,
        create_outside_service_claim_payload(
            member_id, expected_member_version, **overrides
        ),
        RFO,
    )
    return get_success_data(res)


def create_and_adjudicate_claim(region_id, member_id, expected_member_version,
                                **overrides) -> dict:
    claim = submit_claim(region_id, member_id, expected_member_version, **overrides)
    return get_success_data(api_client.adjudicate_claim(claim["id"], {}, RFO))


def create_and_authorize_referral(region, department, member, provider=None,
                                  **overrides):
    """Raise an INTERNAL referral and authorize it. Returns (referral, member)."""
    referral = get_success_data(
        api_client.create_referral(
            create_referral_payload(
                member["id"], department["id"], department["id"],
                member["version"], **overrides
            ),
            AS,
        )
    )
    authorized = get_success_data(
        api_client.authorize_referral(referral["id"], {}, UR)
    )
    return authorized, member


def create_and_book_appointment(region, department, provider, member,
                                **overrides):
    """Book a ROUTINE appointment. Returns the SCHEDULED appointment."""
    version = current_member_version(member["id"])
    res = api_client.book_appointment(
        create_appointment_payload(
            department["id"], provider["id"], member["id"], version, **overrides
        ),
        AS,
    )
    return get_success_data(res)


def create_scheduled_specialty_appointment(department, provider, member,
                                           referral, **overrides):
    """Book a SPECIALTY appointment against an AUTHORIZED referral."""
    version = current_member_version(member["id"])
    res = api_client.book_appointment(
        create_appointment_payload(
            department["id"], provider["id"], member["id"], version,
            referral_id=referral["id"], appointment_type="SPECIALTY", **overrides
        ),
        AS,
    )
    return get_success_data(res)


def create_reviewed_capacity_plan(region_id, department_id, **overrides):
    """Create a CapacityPlan and move it to UNDER_REVIEW. Returns the plan."""
    plan = get_success_data(
        api_client.create_capacity_plan(
            region_id, create_capacity_plan_payload(department_id, **overrides), RFO
        )
    )
    return get_success_data(api_client.review_capacity_plan(plan["id"], {}, AS))


def create_active_capacity_plan(region_id, department_id, **overrides):
    """Create a CapacityPlan and drive it to ACTIVE. Returns the plan."""
    plan = create_reviewed_capacity_plan(region_id, department_id, **overrides)
    return get_success_data(api_client.activate_capacity_plan(plan["id"], {}, RFO))


def create_quality_metric(region_id, provider_id, **overrides) -> dict:
    res = api_client.create_quality_metric(
        region_id, create_quality_metric_payload(provider_id, **overrides), QRB
    )
    return get_success_data(res)


def set_metric_outcome(metric_id, measured_value, weighted_component_score=None):
    """Write a metric's measured value and scored outcome directly."""
    payload = {"measured_value": measured_value}
    payload["weighted_component_score"] = (
        weighted_component_score if weighted_component_score is not None
        else measured_value
    )
    return get_success_data(api_client.set_outcome_targets(metric_id, payload, ADMIN))


def create_finalized_quality_metric(region_id, provider_id, measured_value=90,
                                    target_value=80, metric_code="QUALITY_COMPOSITE",
                                    period=None, **overrides):
    """Open a metric, seed its outcome and finalize it. Returns the metric.

    A metric can only finalize once internal-referral logging is complete, so a
    region with no referrals at all satisfies the gate.
    """
    metric = create_quality_metric(
        region_id, provider_id,
        metric_code=metric_code, target_value=target_value,
        period=period or TEST_DEFAULTS["BUDGET_PERIOD"], **overrides
    )
    set_metric_outcome(metric["id"], measured_value)
    return get_success_data(api_client.finalize_quality_metric(metric["id"], {}, QRB))


def request_and_accept_transfer(member, from_region_id, to_region_id,
                                effective_utc="2026-09-10T00:00:00Z",
                                member_version=None):
    """Request a MemberTransfer and accept it. Returns (transfer, member)."""
    version = (
        member_version if member_version is not None
        else current_member_version(member["id"])
    )
    transfer = get_success_data(
        api_client.create_member_transfer(
            create_member_transfer_payload(
                member["id"], from_region_id, to_region_id, version,
                effective_utc=effective_utc,
            ),
            RFO,
        )
    )
    accepted = get_success_data(
        api_client.accept_member_transfer(transfer["id"], {}, RFO)
    )
    return accepted, member


# ─── Tier 4: Accumulation / threshold targeting ───────

def setup_department_with_committed_slots(department_slots, committed_slots,
                                          provider_overrides=None,
                                          member_overrides=None):
    """Build a department holding exactly ``committed_slots`` booked slots.

    Each booking consumes one slot and schedules one appointment. Returns
    (region, care_site, department, provider, members, appointments).
    """
    region = create_open_region()
    care_site = create_care_site(region["id"])
    department = create_department(
        care_site["id"], appointment_slots_budgeted=department_slots
    )
    provider = create_provider(care_site["id"], **(provider_overrides or {}))
    create_and_approve_budget(region["id"])
    members = []
    appointments = []
    for index in range(committed_slots):
        member = enroll_member(
            region["id"], provider["id"], member_ref=f"M-BULK-{index}",
            **(member_overrides or {})
        )
        members.append(member)
        appointments.append(
            create_and_book_appointment(
                region, department, provider, member,
                start_utc=f"2026-09-{10 + index:02d}T09:00:00Z",
            )
        )
    return region, care_site, department, provider, members, appointments


def setup_region_at_staffing_line(staffing_fte_budget, staffing_fte_filled,
                                  budget_overrides=None):
    """Region whose filled staffing sits exactly at a chosen level.

    The budget's staffing line defaults to the region's own
    ``staffing_and_facility_cents`` so that the fiscal line of §2.10 is
    satisfied (the figure sits at, not above, the line) and the subsequent
    business checks under test are reachable. An explicit
    ``staffing_budget_cents`` override wins.

    Returns (region, care_site, department, provider, member, budget).
    """
    region = create_open_region()
    care_site = create_care_site(
        region["id"], staffing_fte_budget=staffing_fte_budget,
        facility_investment_budget_cents=0,
    )
    get_success_data(
        api_client.set_staffing(
            care_site["id"], {"staffing_fte_filled": staffing_fte_filled}, RFO
        )
    )
    department = create_department(care_site["id"])
    provider = create_provider(care_site["id"])
    member = enroll_member(region["id"], provider["id"])
    merged = dict(budget_overrides or {})
    if "staffing_budget_cents" not in merged:
        merged["staffing_budget_cents"] = get_region(
            region["id"])["staffing_and_facility_cents"]
    budget = create_and_approve_budget(region["id"], **merged)
    return region, care_site, department, provider, member, budget


def setup_region_with_negative_margin(provider_base_cents=5000000,
                                      facility_investment_cents=0):
    """Region whose single member's capitation cannot cover the provider cost.

    The region therefore settles to RESTRICTED through the posture ladder.
    Returns (region, care_site, department, provider, member).
    """
    region = create_open_region()
    care_site = create_care_site(
        region["id"], staffing_fte_budget=1.0, facility_investment_budget_cents=0
    )
    department = create_department(care_site["id"])
    provider = create_provider(
        care_site["id"],
        compensation_model="SALARY",
        base_component_cents=provider_base_cents,
    )
    member = enroll_member(region["id"], provider["id"])
    return region, care_site, department, provider, member


def setup_multi_region_claims(claim_overrides_a=None, claim_overrides_b=None):
    """Two regions, each with an approved budget and one submitted claim.

    Returns (region_a, region_b, claim_a, claim_b, member_a, member_b).
    """
    region_a = create_open_region(name="Region A")
    site_a = create_care_site(region_a["id"], site_name="Region A Office")
    create_department(site_a["id"])
    provider_a = create_provider(site_a["id"], provider_name="Dr A")
    member_a = enroll_member(region_a["id"], provider_a["id"], member_ref="M-RA-1")
    create_and_approve_budget(region_a["id"])
    claim_a = submit_claim(
        region_a["id"], member_a["id"], member_a["version"],
        **(claim_overrides_a or {})
    )

    region_b = create_open_region(name="Region B")
    site_b = create_care_site(region_b["id"], site_name="Region B Office")
    create_department(site_b["id"])
    provider_b = create_provider(site_b["id"], provider_name="Dr B")
    member_b = enroll_member(region_b["id"], provider_b["id"], member_ref="M-RB-1")
    create_and_approve_budget(region_b["id"])
    claim_b = submit_claim(
        region_b["id"], member_b["id"], member_b["version"],
        **(claim_overrides_b or {})
    )

    return region_a, region_b, claim_a, claim_b, member_a, member_b


# ─── Tier 5: Terminal / specialization helpers ────────

def setup_referral_ready_for_completion():
    """Referral driven to COMPLETED through authorize -> book -> complete.

    Returns (region, department, provider, member, referral, appointment).
    """
    region, care_site, department, provider, member = setup_basic_scenario()
    referral = get_success_data(
        api_client.create_referral(
            create_referral_payload(
                member["id"], department["id"], department["id"], member["version"]
            ),
            AS,
        )
    )
    get_success_data(api_client.authorize_referral(referral["id"], {}, UR))
    appointment = create_scheduled_specialty_appointment(
        department, provider, member, referral
    )
    get_success_data(api_client.complete_appointment(appointment["id"], {}, CTM))
    return region, department, provider, member, referral, appointment


def setup_bookable_scenario(
    site_overrides=None,
    department_overrides=None,
    provider_overrides=None,
    member_overrides=None,
    budget_overrides=None,
):
    """Basic scenario plus an APPROVED budget with a generous staffing line.

    Booking, claim submission and enrollment all consult the region's latest
    budget line, so scenarios that exercise those paths build one first.
    Returns (region, care_site, department, provider, member, budget).
    """
    region, care_site, department, provider, member = setup_basic_scenario(
        site_overrides=site_overrides,
        department_overrides=department_overrides,
        provider_overrides=provider_overrides,
        member_overrides=member_overrides,
    )
    budget = create_and_approve_budget(region["id"], **(budget_overrides or {}))
    return region, care_site, department, provider, member, budget


def complete_internal_referral_log(region_id, department, member):
    """Leave the region's internal-referral log complete (1.0) for the period.

    A metric can only be scored once every referral decision for the period is
    logged; authorizing the only referral raised satisfies that gate.
    Returns the authorized referral.
    """
    referral = get_success_data(
        api_client.create_referral(
            create_referral_payload(
                member["id"], department["id"], department["id"],
                current_member_version(member["id"]),
            ),
            AS,
        )
    )
    return get_success_data(api_client.authorize_referral(referral["id"], {}, UR))


def setup_capacity_breach_scenario(plan_budgeted_slots=1, department_slots=100,
                                   plan_period="2026-09"):
    """Pre-state for the capacity-driven posture hop.

    An ACTIVE plan budgeted at ``plan_budgeted_slots`` covering a department
    with ``department_slots`` weekly slots, one booking already made, and a
    PENDING_TRIAGE referral aimed at that department. The booking and the plan
    share ``plan_period`` so the booking is counted toward the plan's
    ``committed_slots``, and the region is held at ``OPEN`` (a provisioned
    staffing line keeps the settled margin non-negative) so that the only
    posture trigger left is the capacity overshoot. A further booking in the
    same period that pushes the plan past its budgeted supply drives the
    region's capacity posture branch.

    Returns (region, department, provider, first_member, second_member, plan,
             referral, plan_period).
    """
    region = create_open_region()
    care_site = create_care_site(region["id"], facility_investment_budget_cents=0)
    department = create_department(
        care_site["id"], appointment_slots_budgeted=department_slots
    )
    provider = create_provider(care_site["id"], base_component_cents=0)
    create_and_approve_budget(
        region["id"], staffing_budget_cents=0, outside_services_budget_cents=0,
        facility_investment_cents=0,
    )
    first_member = enroll_member(region["id"], provider["id"], member_ref="M-CAP-1")
    second_member = enroll_member(region["id"], provider["id"], member_ref="M-CAP-2")

    plan = create_active_capacity_plan(
        region["id"], department["id"],
        budgeted_slots=plan_budgeted_slots, panel_target=1,
        period=plan_period,
    )
    create_and_book_appointment(
        region, department, provider, first_member,
        start_utc="%s-10T09:00:00Z" % plan_period,
    )
    referral = get_success_data(
        api_client.create_referral(
            create_referral_payload(
                second_member["id"], department["id"], department["id"],
                current_member_version(second_member["id"]),
            ),
            AS,
        )
    )
    return (region, department, provider, first_member, second_member,
            get_capacity_plan(plan["id"]), referral, plan_period)


def setup_region_driven_to_capacity_restricted(plan_budgeted_slots=1,
                                               plan_panel_target=1):
    """Drive a region RESTRICTED through the capacity-driven posture branch.

    Returns (region, department, provider, member, capacity_plan).
    """
    region, care_site, department, provider, member = setup_basic_scenario()
    plan = create_active_capacity_plan(
        region["id"], department["id"],
        budgeted_slots=plan_budgeted_slots, panel_target=plan_panel_target,
    )
    version = current_member_version(member["id"])
    get_success_data(
        api_client.book_appointment(
            create_appointment_payload(
                department["id"], provider["id"], member["id"], version,
                start_utc="2026-09-10T09:00:00Z",
            ),
            AS,
        )
    )
    return region, department, provider, member, plan