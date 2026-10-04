"""Composite setup helpers for multi-step prerequisites.

Every helper builds its preconditions from scratch using PRD-declared endpoints;
the harness restarts the service before each test, so nothing is carried over.
Uses the lenient get_success_data() so a broken precondition reports a clear
"setup failed" error rather than a confusing assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS as D
from .test_users import TEST_USERS


# ─── Tier 1: state progression ───────────────────────────────────────────────


def set_clock(current_utc: str = "2026-09-01T00:00:00Z"):
    """Set the logical clock. Every computation in the program reads it."""
    res = api_client.set_current_utc(
        {"current_utc": current_utc}, TEST_USERS["platform_admin_headers"]
    )
    return get_success_data(res)


def create_fund(**overrides):
    """Create the donor fund the whole program draws on."""
    payload = {
        "fund_code": D["FUND_CODE"],
        "fiscal_year": D["FISCAL_YEAR"],
        "fundraising_raised_cents": D["RAISED_CENTS"],
        "research_allocation_pct": D["RESEARCH_ALLOCATION_PCT"],
        "federal_grant_cents": D["FEDERAL_GRANT_CENTS"],
    }
    payload.update(overrides)
    return get_success_data(api_client.create_fund(payload, TEST_USERS["platform_admin_headers"]))


def create_protocol(fund_id, **overrides):
    payload = {
        "fund_id": fund_id,
        "protocol_code": D["PROTOCOL_CODE"],
        "disease_group": D["DISEASE_GROUP"],
        "age_min_years": D["AGE_MIN_YEARS"],
        "age_max_years": D["AGE_MAX_YEARS"],
        "required_stage": D["REQUIRED_STAGE"],
        "protocol_budget_cents": D["PROTOCOL_BUDGET_CENTS"],
        "capacity": D["CAPACITY"],
    }
    payload.update(overrides)
    return get_success_data(
        api_client.create_protocol(payload, TEST_USERS["protocol_coordinator_headers"])
    )


def create_open_protocol(fund_id, **overrides):
    protocol = create_protocol(fund_id, **overrides)
    return get_success_data(
        api_client.open_protocol(protocol["id"], TEST_USERS["protocol_coordinator_headers"])
    )


def create_facility(**overrides):
    payload = {
        "facility_code": D["FACILITY_ON_CAMPUS_CODE"],
        "name": D["FACILITY_ON_CAMPUS_NAME"],
        "tier": "ON_CAMPUS",
        "total_beds": 4,
        "buffer_beds": 0,
    }
    payload.update(overrides)
    return get_success_data(
        api_client.create_facility(payload, TEST_USERS["housing_coordinator_headers"])
    )


def create_referral(protocol_id, **overrides):
    payload = {
        "protocol_id": protocol_id,
        "child_name": D["CHILD_NAME"],
        "child_date_of_birth": D["CHILD_DOB"],
        "disease_group": D["DISEASE_GROUP"],
        "disease_stage": D["REQUIRED_STAGE"],
        "household_state_code": D["HOUSEHOLD_STATE"],
        "traveling_family_member_count": D["TRAVELING_COUNT"],
        "expected_treatment_days": D["EXPECTED_DAYS"],
        "is_immunosuppressed": False,
        "insurance_coverage_cents": D["INSURANCE_CENTS"],
    }
    payload.update(overrides)
    return get_success_data(
        api_client.create_referral(payload, TEST_USERS["intake_coordinator_headers"])
    )


# ─── Tier 2: the standard funnel preamble ────────────────────────────────────


def setup_fund_and_open_protocol(**protocol_overrides):
    """Clock + fund + one OPEN protocol. The commonest two-entity preamble."""
    set_clock()
    fund = create_fund()
    protocol = create_open_protocol(fund["id"], **protocol_overrides)
    return fund, protocol


def screen_referral(referral_id, protocol_version):
    return get_success_data(api_client.screen_referral(
        referral_id,
        {"expected_protocol_version": protocol_version},
        TEST_USERS["intake_coordinator_headers"],
    ))


def current_protocol_version(protocol_id):
    """The protocol's current `version`, which §2.11 requires the screen to
    re-assert. PRD §3.1 names the funding-posture read as exactly the read a
    client should perform immediately before screening, because the
    `protocol_version` it returns is the value the screen must carry."""
    posture = get_success_data(api_client.get_funding_posture(
        protocol_id, TEST_USERS["any_headers"]))
    return posture["protocol_version"]


def screen_referral_now(referral_id, protocol_id):
    """Screen with a freshly-read OCC token, as PRD §3.1 prescribes.

    A screen advances the host protocol's `version`, so any token read before an
    earlier screen in the same flow is stale by the time the next one runs.
    """
    return get_success_data(api_client.screen_referral(
        referral_id,
        {"expected_protocol_version": current_protocol_version(protocol_id)},
        TEST_USERS["intake_coordinator_headers"],
    ))


def arrive_referral(referral_id, referral_version):
    return get_success_data(api_client.arrive_referral(
        referral_id,
        {"expected_referral_version": referral_version},
        TEST_USERS["intake_coordinator_headers"],
    ))


def sign_consent(enrollment_id, **overrides):
    payload = {
        "consent_signer": "GUARDIAN_AND_CHILD",
        "guardian_consent_signature_code": D["GUARDIAN_SIGNATURE"],
        "child_assent_signature_code": D["CHILD_SIGNATURE"],
    }
    payload.update(overrides)
    return get_success_data(
        api_client.sign_consent(enrollment_id, payload, TEST_USERS["intake_coordinator_headers"])
    )


def setup_screened_referral(fund, protocol, **referral_overrides):
    """One SUBMITTED referral screened to ACCEPTED. Returns (referral, screened)."""
    referral = create_referral(protocol["id"], **referral_overrides)
    screened = screen_referral(referral["id"], protocol["version"])
    return referral, screened


def ensure_facility(facility_code=None, **overrides):
    """Return the residence with this `facility_code`, registering it if absent.

    A `facility_code` is unique across the program (PRD §2.13), so a fixture that
    needs "a campus residence to exist" must reuse the one a test already
    registered rather than attempting a second create.
    """
    facility_code = facility_code or D["FACILITY_ON_CAMPUS_CODE"]
    existing = get_success_data(
        api_client.list_facilities(TEST_USERS["any_headers"]))
    for facility in existing:
        if facility["facility_code"] == facility_code:
            return facility
    return create_facility(facility_code=facility_code, **overrides)


def setup_arrived_enrollment(fund, protocol, facility=None, **referral_overrides):
    """Referral -> screened -> arrived. Returns (referral, referral_after, enrollment_id).

    A facility is registered first when the housing selector needs a candidate.
    """
    if facility is None:
        facility = ensure_facility(
            total_beds=max(referral_overrides.get("_beds", 4), 4)
            if "_beds" in referral_overrides else 4
        )
    referral = create_referral(protocol["id"], **{
        k: v for k, v in referral_overrides.items() if not k.startswith("_")
    })
    screened = screen_referral(referral["id"], protocol["version"])
    arrived = arrive_referral(referral["id"], screened["version"])
    return referral, arrived, arrived["enrollment_id"]


def setup_enrolled_family(fund, protocol, facility=None, **referral_overrides):
    """Full path to ENROLLED: arrived -> signed consent.

    Returns (referral, enrollment_id).
    """
    referral, arrived, enrollment_id = setup_arrived_enrollment(
        fund, protocol, facility=facility, **referral_overrides
    )
    sign_consent(enrollment_id)
    return referral, enrollment_id


def setup_housed_family(fund, protocol, facility=None, activate=True,
                        start_at="2026-09-01T00:00:00Z", end_at="2026-09-02T00:00:00Z",
                        **referral_overrides):
    """ENROLLED -> one SCHEDULED (or ACTIVE) housing assignment.

    Returns (referral, enrollment_id, assignment).
    """
    created_facility = facility is None
    if facility is None:
        facility = ensure_facility(total_beds=4)
    referral, enrollment_id = setup_enrolled_family(
        fund, protocol, facility=facility,
        **{k: v for k, v in referral_overrides.items() if not k.startswith("_")}
    )
    assignment = get_success_data(api_client.create_assignment(
        {
            "enrollment_id": enrollment_id,
            "start_at": start_at,
            "end_at": end_at,
            "buffer_window_days": 1,
        },
        TEST_USERS["housing_coordinator_headers"],
    ))
    if activate:
        assignment = get_success_data(api_client.activate_assignment(
            assignment["id"], TEST_USERS["housing_coordinator_headers"]
        ))
    if created_facility:
        assignment["_facility"] = facility
    return referral, enrollment_id, assignment


def setup_treated_family(fund, protocol, facility=None, **referral_overrides):
    """Housed + treatment started. Returns (referral, enrollment_id, assignment)."""
    referral, enrollment_id, assignment = setup_housed_family(
        fund, protocol, facility=facility, **referral_overrides
    )
    get_success_data(api_client.start_treatment(
        enrollment_id, TEST_USERS["intake_coordinator_headers"]
    ))
    return referral, enrollment_id, assignment


# ─── Tier 3: lifecycle shortcuts ─────────────────────────────────────────────


def create_pledge(enrollment_id, budget_cents=None):
    return get_success_data(api_client.create_pledge(
        {
            "enrollment_id": enrollment_id,
            "patient_support_budget_cents": (
                budget_cents if budget_cents is not None else D["PATIENT_SUPPORT_BUDGET_CENTS"]
            ),
        },
        TEST_USERS["patient_support_officer_headers"],
    ))


def accrue_pledge(pledge_id, days):
    return get_success_data(api_client.accrue_pledge(
        pledge_id, {"days": days}, TEST_USERS["patient_support_officer_headers"]
    ))


def settle_pledge(pledge_id):
    return get_success_data(api_client.settle_pledge(
        pledge_id, TEST_USERS["patient_support_officer_headers"]
    ))


def setup_hiatused_pledge(fund, protocol, facility=None, accrue_days=4,
                          pledge_budget_cents=12000, **referral_overrides):
    """Reach the settled-pledge precondition used by the family-day-rate cases.

    ENROLLED -> ACTIVE occupancy -> treatment started -> pledge created and
    accrued `accrue_days` -> enrollment placed ON_HIATUS so the pledge may settle.

    Returns (referral, enrollment_id, pledge, assignment).
    """
    referral, enrollment_id, assignment = setup_treated_family(
        fund, protocol, facility=facility, **referral_overrides
    )
    pledge = create_pledge(enrollment_id, budget_cents=pledge_budget_cents)
    if accrue_days:
        accrue_pledge(pledge["id"], accrue_days)
    get_success_data(api_client.hiatus(
        enrollment_id,
        {"hiatus_reason": "AFFILIATE_TRANSFER"},
        TEST_USERS["intake_coordinator_headers"],
    ))
    return referral, enrollment_id, pledge, assignment


def setup_require_switch(fund, protocol, facility_beds=12, referrers=7):
    """Seven ON_CAMPUS acceptances, leaving reserved_cents at 8750000 on a
    10000000-cent budget. Returns the list of accepted referrals plus the protocol.

    Each screen re-reads the funding posture so the OCC token is fresh.
    """
    facility = create_facility(facility_code="ONC-01", total_beds=facility_beds)
    accepted = []
    for index in range(referrers):
        referral = create_referral(
            protocol["id"],
            child_name=f"Seed {index + 1}",
            is_immunosuppressed=True,
        )
        posture = get_success_data(api_client.get_funding_posture(
            protocol["id"], TEST_USERS["any_headers"]
        ))
        accepted.append(screen_referral(referral["id"], posture["protocol_version"]))
    return accepted, facility


def open_protocol_with_reservations(fund, protocol, count=7, facility_beds=12,
                                    child_prefix="Seed"):
    """Register a wide campus residence and take `count` ON_CAMPUS acceptances."""
    facility = create_facility(facility_code="ONC-01", total_beds=facility_beds)
    accepted = []
    for index in range(count):
        referral = create_referral(
            protocol["id"], child_name=f"{child_prefix} {index + 1}", is_immunosuppressed=True
        )
        posture = get_success_data(api_client.get_funding_posture(
            protocol["id"], TEST_USERS["any_headers"]
        ))
        accepted.append(screen_referral(referral["id"], posture["protocol_version"]))
    protocol_now = get_success_data(api_client.get_protocol(
        protocol["id"], TEST_USERS["any_headers"]
    ))
    return facility, accepted, protocol_now


# ─── Tier 4: accumulation / threshold targeting ──────────────────────────────


def setup_ledger_at_backing(service_code="MEALS", base_allowance_cents=20000,
                            stimulation_rate=0.3, stimulation_cap_cents=5000,
                            family_count=1, **fund_overrides):
    """Create a fund, one stimulation-eligible service line, and accrue once.

    Returns (fund, service, ledger_id, accrual_response).
    """
    set_clock()
    fund = create_fund(**fund_overrides)
    service = get_success_data(api_client.create_service(
        {
            "fund_id": fund["id"],
            "service_code": service_code,
            "display_name": service_code,
            "base_allowance_cents": base_allowance_cents,
            "is_stimulation_eligible": True,
            "stimulation_rate": stimulation_rate,
            "stimulation_cap_cents": stimulation_cap_cents,
        },
        TEST_USERS["patient_support_officer_headers"],
    ))
    accrual = get_success_data(api_client.accrue_allowance(
        service["id"], {"family_count": family_count},
        TEST_USERS["patient_support_officer_headers"],
    ))
    return fund, service, accrual["family_service_ledger_id"], accrual


def setup_three_tiered_ledgers(fund):
    """Three eligible service lines whose accumulated cents bracket their caps.

    PRD §3.10: the ops checkpoint "freezes every ledger whose `accumulated_cents`
    exceeds its service's `stimulation_cap_cents`" — the comparison is on the
    ledger's accumulated cents, not on the markup. Ledger A lands exactly on its
    cap after one accrual, ledger B lands exactly on its cap after two, and
    ledger C lands one cent past its cap.
    Returns (service_a, service_b, service_c, ledger_a, ledger_b, ledger_c).
    """
    service_a = get_success_data(api_client.create_service({
        "fund_id": fund["id"], "service_code": "MEALS", "display_name": "Meals",
        "base_allowance_cents": 20000, "is_stimulation_eligible": True,
        "stimulation_rate": 0.3, "stimulation_cap_cents": 20000,
    }, TEST_USERS["patient_support_officer_headers"]))
    service_b = get_success_data(api_client.create_service({
        "fund_id": fund["id"], "service_code": "HOUSING", "display_name": "Housing",
        "base_allowance_cents": 20000, "is_stimulation_eligible": True,
        "stimulation_rate": 0.3, "stimulation_cap_cents": 40000,
    }, TEST_USERS["patient_support_officer_headers"]))
    service_c = get_success_data(api_client.create_service({
        "fund_id": fund["id"], "service_code": "TRAVEL", "display_name": "Travel",
        "base_allowance_cents": 20000, "is_stimulation_eligible": True,
        "stimulation_rate": 0.3, "stimulation_cap_cents": 19999,
    }, TEST_USERS["patient_support_officer_headers"]))

    accrual_a = get_success_data(api_client.accrue_allowance(
        service_a["id"], {"family_count": 1}, TEST_USERS["patient_support_officer_headers"]))
    accrual_b = get_success_data(api_client.accrue_allowance(
        service_b["id"], {"family_count": 1}, TEST_USERS["patient_support_officer_headers"]))
    get_success_data(api_client.accrue_allowance(
        service_b["id"], {"family_count": 1}, TEST_USERS["patient_support_officer_headers"]))
    accrual_c = get_success_data(api_client.accrue_allowance(
        service_c["id"], {"family_count": 1}, TEST_USERS["patient_support_officer_headers"]))
    return (
        service_a, service_b, service_c,
        accrual_a["family_service_ledger_id"],
        accrual_b["family_service_ledger_id"],
        accrual_c["family_service_ledger_id"],
    )


def setup_sibling_pair(fund, protocol, facility=None, sessions_first=3):
    """A TN and an MA household, each ACTIVE_TREATMENT with a sibling service
    holding `sessions_first` delivered sessions.

    Returns a dict keyed by state with referral, enrollment and sibling service.
    """
    if facility is None:
        facility = create_facility(facility_code="ONC-01", total_beds=4)
    result = {}
    for state in ("TN", "MA"):
        referral = create_referral(
            protocol["id"],
            child_name=("Ava Reyes" if state == "TN" else "Noah Patel"),
            household_state_code=state,
            is_immunosuppressed=True,
        )
        screened = screen_referral(referral["id"], protocol["version"])
        arrived = arrive_referral(referral["id"], screened["version"])
        enrollment_id = arrived["enrollment_id"]
        sign_consent(enrollment_id)
        assignment = get_success_data(api_client.create_assignment(
            {"enrollment_id": enrollment_id, "start_at": "2026-09-01T00:00:00Z",
             "end_at": "2026-09-02T00:00:00Z", "buffer_window_days": 1},
            TEST_USERS["housing_coordinator_headers"]))
        get_success_data(api_client.activate_assignment(
            assignment["id"], TEST_USERS["housing_coordinator_headers"]))
        get_success_data(api_client.start_treatment(
            enrollment_id, TEST_USERS["intake_coordinator_headers"]))
        sibling = get_success_data(api_client.create_sibling_service(
            enrollment_id,
            {"sibling_alias": ("R-Sib" if state == "TN" else "P-Sib"),
             "service_type": "SIBLING_CAMP",
             "delivery_window_start_at": "2026-09-01T00:00:00Z",
             "delivery_window_end_at": "2026-10-01T00:00:00Z"},
            TEST_USERS["patient_support_officer_headers"]))
        if sessions_first:
            get_success_data(api_client.deliver_sibling_sessions(
                sibling["id"], {"session_count": sessions_first},
                TEST_USERS["patient_support_officer_headers"]))
        result[state] = {
            "referral": referral, "enrollment_id": enrollment_id,
            "assignment": assignment, "sibling": sibling,
        }
    return result


# ─── Tier 5: finalization / terminal state ───────────────────────────────────


def setup_active_survivorship_study(protocol, **overrides):
    payload = {"study_code": "SURV-001", "follow_up_interval_months": 12,
               "min_years_after_completion": 5}
    payload.update(overrides)
    return get_success_data(api_client.create_study(
        protocol["id"], payload, TEST_USERS["survivorship_coordinator_headers"]
    ))


def setup_milestone_course(enrollment_id, execute_first=True, **first_overrides):
    """Register two milestones, execute the first so the second reads DUE.

    Returns (milestone_one, milestone_two).
    """
    first = get_success_data(api_client.create_milestone(
        enrollment_id,
        {"milestone_sequence": 1, "description": "Induction",
         "requires_main_campus": True, "target_at": "2026-09-02T00:00:00Z", **first_overrides},
        TEST_USERS["protocol_coordinator_headers"],
    ))
    second = get_success_data(api_client.create_milestone(
        enrollment_id,
        {"milestone_sequence": 2, "description": "Consolidation",
         "requires_main_campus": False, "target_at": "2026-09-05T00:00:00Z"},
        TEST_USERS["protocol_coordinator_headers"],
    ))
    if execute_first:
        get_success_data(api_client.execute_milestone(
            first["id"], TEST_USERS["affiliate_clinic_coordinator_headers"]))
        second = get_success_data(api_client.get_milestone(
            second["id"], TEST_USERS["any_headers"]))
    return first, second


def setup_completion_ready(fund, protocol, facility=None, **referral_overrides):
    """Reach the point where complete-treatment can succeed.

    Study created, family housed and treated, one milestone executed, a sibling
    service and a pledge in place. Returns a dict of the pieces.
    """
    study = setup_active_survivorship_study(protocol)
    referral, enrollment_id, assignment = setup_treated_family(
        fund, protocol, facility=facility, **referral_overrides
    )
    milestone = get_success_data(api_client.create_milestone(
        enrollment_id,
        {"milestone_sequence": 1, "description": "Induction",
         "requires_main_campus": True, "target_at": "2026-09-02T00:00:00Z"},
        TEST_USERS["protocol_coordinator_headers"],
    ))
    get_success_data(api_client.execute_milestone(
        milestone["id"], TEST_USERS["affiliate_clinic_coordinator_headers"]))
    sibling = get_success_data(api_client.create_sibling_service(
        enrollment_id,
        {"sibling_alias": "R-Sib", "service_type": "SIBLING_CAMP",
         "delivery_window_start_at": "2026-09-01T00:00:00Z",
         "delivery_window_end_at": "2026-10-01T00:00:00Z"},
        TEST_USERS["patient_support_officer_headers"]))
    pledge = create_pledge(enrollment_id, budget_cents=400000)
    return {
        "study": study, "referral": referral, "enrollment_id": enrollment_id,
        "assignment": assignment, "milestone": milestone,
        "sibling": sibling, "pledge": pledge,
    }


def setup_enrolled_with_scheduled_housing(fund, protocol, facility=None,
                                          **referral_overrides):
    """ENROLLED with a SCHEDULED (not yet active) occupancy and an ACTIVE pledge.

    Returns (referral, enrollment_id, assignment, pledge).
    """
    created = facility is None
    if facility is None:
        facility = create_facility(facility_code="ONC-01", total_beds=4)
    referral = create_referral(protocol["id"], **{
        k: v for k, v in referral_overrides.items() if not k.startswith("_")
    })
    screened = screen_referral(referral["id"], protocol["version"])
    arrived = arrive_referral(referral["id"], screened["version"])
    enrollment_id = arrived["enrollment_id"]
    assignment = get_success_data(api_client.create_assignment(
        {"enrollment_id": enrollment_id, "start_at": "2026-09-01T00:00:00Z",
         "end_at": "2026-09-02T00:00:00Z", "buffer_window_days": 1},
        TEST_USERS["housing_coordinator_headers"]))
    sign_consent(enrollment_id)
    pledge = create_pledge(enrollment_id, budget_cents=400000)
    return referral, enrollment_id, assignment, pledge


def setup_confirmed_travel(fund, protocol, facility=None,
                           departure="2026-09-05T00:00:00Z",
                           return_at="2026-09-12T00:00:00Z", **travel_overrides):
    """ACTIVE_TREATMENT plus one CONFIRMED leg.

    Returns (enrollment_id, leg).
    """
    referral, enrollment_id, assignment = setup_treated_family(
        fund, protocol, facility=facility
    )
    payload = {"mode": "AIR_ECONOMY", "traveler_count": 2,
               "departure_at": departure, "return_at": return_at,
               "trip_reason": "PROTOCOL_REVIEW", "is_required_travel": True}
    payload.update(travel_overrides)
    leg = get_success_data(api_client.request_travel(
        enrollment_id, payload, TEST_USERS["patient_support_officer_headers"]))
    leg = get_success_data(api_client.confirm_travel(
        leg["id"], TEST_USERS["patient_support_officer_headers"]))
    return enrollment_id, leg