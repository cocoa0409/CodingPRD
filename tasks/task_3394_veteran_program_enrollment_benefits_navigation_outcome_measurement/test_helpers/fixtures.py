"""Composite setup helpers. Every fixture builds its state from scratch through
the declared API endpoints (the server is restarted before each test, so the
database starts empty and the logical clock starts at 2026-09-01T00:00:00Z).

Setup calls use the lenient get_success_data validator so failures surface as
clear setup errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import api_client
from .constants import CLOCK_START_ISO
from .test_users import (
    TEST_USERS,
    make_benefits_officer_headers,
    make_clinical_partner_headers,
    make_program_member_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]
REP = TEST_USERS["accredited_representative_headers"]
OFFICER_A = TEST_USERS["benefits_officer_headers"]  # X-User-ID "officer-a"
CAREER = TEST_USERS["career_counselor_headers"]
EVENT = TEST_USERS["event_coordinator_headers"]
ANALYST = TEST_USERS["outcome_analyst_headers"]


# ---- logical clock ------------------------------------------------------
def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock; every set runs the full clock sweep."""
    return get_success_data(api_client.set_clock(factories.clock_payload(to_iso8601), ADMIN))


def reset_clock() -> dict:
    """Pin the clock to the documented startup instant (idempotent safety)."""
    return set_clock(CLOCK_START_ISO)


# ---- program tracks -----------------------------------------------------
def create_program_track(track_code="MENTAL_HEALTH", name=None, capacity=10) -> dict:
    payload = factories.create_program_track_payload(
        track_code=track_code, name=name or f"{track_code.title()} Track", capacity=capacity)
    return get_success_data(api_client.create_program_track(payload, ADMIN))


def get_track_by_code(track_code) -> dict:
    data, _meta = _paginate(api_client.list_program_tracks(ADMIN, params={"track_code": track_code}))
    return next(t for t in data if t["track_code"] == track_code)


def list_program_tracks() -> list:
    data, _meta = _paginate(api_client.list_program_tracks(ADMIN))
    return data


# ---- members -------------------------------------------------------------
def create_member(full_name="Test Veteran", member_type="VETERAN",
                  branch_of_service="ARMY", service_era_claimed="POST_911",
                  injury_connection_claimed="SERVICE_CONNECTED") -> dict:
    if member_type == "FAMILY_SUPPORT":
        payload = factories.create_family_member_payload(
            full_name=full_name, service_era_claimed=service_era_claimed,
            injury_connection_claimed=injury_connection_claimed)
    else:
        payload = factories.create_member_payload(
            full_name=full_name, member_type=member_type,
            branch_of_service=branch_of_service,
            service_era_claimed=service_era_claimed,
            injury_connection_claimed=injury_connection_claimed)
    return get_success_data(api_client.create_member(payload, INTAKE))


def get_member(member_id) -> dict:
    return get_success_data(api_client.get_member(member_id, INTAKE))


def get_member_version(member_id) -> int:
    return get_member(member_id)["version"]


# ---- eligibility cases ----------------------------------------------------
def open_eligibility_case(member_id, expected_member_version) -> dict:
    payload = factories.create_eligibility_case_payload(member_id, expected_member_version)
    return get_success_data(api_client.create_eligibility_case(payload, INTAKE))


def transition_case(case_id, target_status, **fields) -> dict:
    payload = factories.case_transition_payload(target_status, **fields)
    return get_success_data(api_client.transition_eligibility_case(case_id, payload, INTAKE))


def verify_member(member, verified_service_era="POST_911",
                  verified_injury_connection="SERVICE_CONNECTED") -> dict:
    """Open an eligibility case for the member and decide it VERIFIED.

    Returns the re-fetched member (verification_status VERIFIED, version bumped
    once by case creation and once by the decision).
    """
    case = open_eligibility_case(member["id"], member["version"])
    transition_case(
        case["id"], "VERIFIED",
        verified_service_era=verified_service_era,
        verified_injury_connection=verified_injury_connection)
    return get_member(member["id"])


def create_verified_member(full_name="Test Veteran", member_type="VETERAN",
                           branch_of_service="ARMY", service_era_claimed="POST_911",
                           injury_connection_claimed="SERVICE_CONNECTED",
                           verified_service_era="POST_911",
                           verified_injury_connection="SERVICE_CONNECTED") -> dict:
    member = create_member(
        full_name=full_name, member_type=member_type,
        branch_of_service=branch_of_service,
        service_era_claimed=service_era_claimed,
        injury_connection_claimed=injury_connection_claimed)
    return verify_member(member, verified_service_era, verified_injury_connection)


def list_eligibility_cases(member_id) -> list:
    data, _meta = _paginate(api_client.list_eligibility_cases(member_id, INTAKE))
    return data


# ---- external service records ---------------------------------------------
def create_external_service_record(member_id, service_category="BENEFITS",
                                   organization_name="VetHelp Alliance",
                                   start_date="2026-08-01T00:00:00Z",
                                   end_date=None) -> dict:
    overrides = {}
    if end_date is not None:
        overrides["end_date"] = end_date
    payload = factories.create_external_service_record_payload(
        member_id, organization_name=organization_name,
        service_category=service_category, start_date=start_date, **overrides)
    return get_success_data(api_client.create_external_service_record(payload, INTAKE))


def list_external_service_records(member_id, **filters) -> list:
    params = {k: v for k, v in filters.items() if v is not None}
    data, _meta = _paginate(api_client.list_external_service_records(member_id, INTAKE, params=params or None))
    return data


# ---- enrollments and assessments -------------------------------------------
def create_enrollment(member_id, program_track_id, coordination_consent=None) -> dict:
    overrides = {}
    if coordination_consent is not None:
        overrides["coordination_consent"] = coordination_consent
    payload = factories.create_enrollment_payload(member_id, program_track_id, **overrides)
    return get_success_data(api_client.create_enrollment(payload, INTAKE))


def get_enrollment(enrollment_id) -> dict:
    return get_success_data(api_client.get_enrollment(enrollment_id, INTAKE))


def list_enrollments(**filters) -> list:
    params = {k: v for k, v in filters.items() if v is not None}
    data, _meta = _paginate(api_client.list_enrollments(INTAKE, params=params or None))
    return data


def add_assessment(enrollment_id, psych=5, phys=5, voc=5, soc=5, **overrides) -> dict:
    payload = factories.create_assessment_payload(
        psych_score=psych, phys_score=phys, voc_score=voc, soc_score=soc, **overrides)
    return get_success_data(api_client.create_assessment(enrollment_id, payload, INTAKE))


def list_assessments(enrollment_id) -> list:
    data, _meta = _paginate(api_client.list_assessments(enrollment_id, INTAKE))
    return data


def transition_enrollment(enrollment_id, target_status, **fields) -> dict:
    payload = factories.enrollment_transition_payload(target_status, **fields)
    return get_success_data(api_client.transition_enrollment(enrollment_id, payload, INTAKE))


def create_active_enrollment(member_id, program_track_id, scores=(5, 5, 5, 5),
                             coordination_consent=None) -> dict:
    """Enrollment walked to ACTIVE via its first assessment."""
    enrollment = create_enrollment(member_id, program_track_id, coordination_consent)
    add_assessment(enrollment["id"], *scores)
    return get_enrollment(enrollment["id"])


def setup_verified_member_with_enrollment(track_code="MENTAL_HEALTH", capacity=10,
                                          scores=(5, 5, 5, 5),
                                          member_name="Test Veteran",
                                          member_type="VETERAN",
                                          injury_connection_claimed="SERVICE_CONNECTED",
                                          verified_injury_connection="SERVICE_CONNECTED"):
    """Track + VERIFIED member + ACTIVE enrollment. Returns (member, track, enrollment)."""
    track = create_program_track(track_code=track_code, capacity=capacity)
    member = create_verified_member(
        full_name=member_name, member_type=member_type,
        injury_connection_claimed=injury_connection_claimed,
        verified_injury_connection=verified_injury_connection)
    enrollment = create_active_enrollment(member["id"], track["id"], scores)
    return get_member(member["id"]), track, enrollment


def setup_intensive_member(region_track_code="MENTAL_HEALTH", capacity=10,
                           member_name="Intensive Veteran"):
    """VERIFIED veteran with an ACTIVE MENTAL_HEALTH enrollment at INTENSIVE tier
    (all-10 scores -> acuity 100). Returns (member, track, enrollment)."""
    return setup_verified_member_with_enrollment(
        track_code=region_track_code, capacity=capacity, scores=(10, 10, 10, 10),
        member_name=member_name)


# ---- benefits claims and appeals --------------------------------------------
def create_claim(member_id, claim_type="DISABILITY_COMPENSATION",
                 claimed_rating_pct=40, dependent_count=0,
                 coordination_consent=None, omit_rating=False,
                 omit_dependent_count=False) -> dict:
    overrides = {}
    if coordination_consent is not None:
        overrides["coordination_consent"] = coordination_consent
    payload = factories.create_claim_payload(
        member_id, claim_type=claim_type,
        claimed_rating_pct=claimed_rating_pct,
        dependent_count=dependent_count, **overrides)
    if omit_rating:
        payload.pop("claimed_rating_pct", None)
    if omit_dependent_count:
        payload.pop("dependent_count", None)
    return get_success_data(api_client.create_claim(payload, REP))


def get_claim(claim_id, headers=None) -> dict:
    return get_success_data(api_client.get_claim(claim_id, headers or OFFICER_A))


def decide_claim(claim_id, outcome="GRANTED", decided_rating_pct=40,
                 officer_id="officer-a") -> dict:
    payload = factories.claim_decision_payload(outcome, decided_rating_pct)
    return get_success_data(
        api_client.decide_claim(claim_id, payload, make_benefits_officer_headers(officer_id)))


def create_decided_claim(member_id, claimed_rating_pct=40, decided_rating_pct=40,
                         dependent_count=0, outcome="GRANTED", officer_id="officer-a",
                         claim_type="DISABILITY_COMPENSATION") -> dict:
    claim = create_claim(member_id, claim_type=claim_type,
                         claimed_rating_pct=claimed_rating_pct,
                         dependent_count=dependent_count,
                         omit_rating=(claim_type == "HEALTHCARE_ACCESS"))
    decide_claim(claim["id"], outcome, decided_rating_pct, officer_id)
    return get_claim(claim["id"])


def create_appeal(claim_id, grounds=None) -> dict:
    overrides = {}
    if grounds is not None:
        overrides["grounds"] = grounds
    payload = factories.create_appeal_payload(claim_id, **overrides)
    return get_success_data(api_client.create_appeal(payload, REP))


def decide_appeal(appeal_id, outcome="UPHELD", new_rating_pct=None,
                  officer_id="officer-b") -> dict:
    overrides = {}
    if new_rating_pct is not None:
        overrides["new_rating_pct"] = new_rating_pct
    payload = factories.appeal_decision_payload(outcome, **overrides)
    return get_success_data(
        api_client.decide_appeal(appeal_id, payload, make_benefits_officer_headers(officer_id)))


def list_appeals(claim_id) -> list:
    data, _meta = _paginate(api_client.list_appeals(claim_id, REP))
    return data


def list_claims(member_id, **filters) -> list:
    params = {k: v for k, v in filters.items() if v is not None}
    data, _meta = _paginate(api_client.list_claims(member_id, INTAKE, params=params or None))
    return data


# ---- partner sites and referrals ---------------------------------------------
def create_partner_site(name="Partner IOP", region="SE", specialties=("PTSD",),
                        capacity=4) -> dict:
    payload = factories.create_partner_site_payload(
        name=name, region=region, specialties=list(specialties), capacity=capacity)
    return get_success_data(api_client.create_partner_site(payload, ADMIN))


def list_partner_sites(**filters) -> list:
    params = {k: v for k, v in filters.items() if v is not None}
    data, _meta = _paginate(api_client.list_partner_sites(ADMIN, params=params or None))
    return data


def create_referral(member_id, expected_member_version=None, region="SE",
                    required_specialty="PTSD",
                    treatment_start="2026-10-01T00:00:00Z",
                    treatment_end="2026-11-01T00:00:00Z",
                    coordination_consent=None) -> dict:
    """Create a referral; the member's current version is fetched fresh when the
    caller does not pin an expected_member_version."""
    if expected_member_version is None:
        expected_member_version = get_member_version(member_id)
    overrides = {}
    if coordination_consent is not None:
        overrides["coordination_consent"] = coordination_consent
    payload = factories.create_referral_payload(
        member_id, expected_member_version, region=region,
        required_specialty=required_specialty,
        treatment_start=treatment_start, treatment_end=treatment_end, **overrides)
    return get_success_data(api_client.create_referral(payload, INTAKE))


def get_referral(referral_id) -> dict:
    return get_success_data(api_client.get_referral(referral_id, INTAKE))


def list_referrals(**filters) -> list:
    params = {k: v for k, v in filters.items() if v is not None}
    data, _meta = _paginate(api_client.list_referrals(INTAKE, params=params or None))
    return data


def transition_referral(referral_id, action, site_id) -> dict:
    """ADMIT or DISCHARGE as the ClinicalPartner staffing the given PartnerSite."""
    payload = factories.referral_transition_payload(action)
    return get_success_data(api_client.transition_referral(
        referral_id, payload, make_clinical_partner_headers(site_id)))


# ---- employer partners and placements ------------------------------------------
def create_employer_partner(name="Employer Co", industry="RETAIL",
                            open_requisitions=1) -> dict:
    payload = factories.create_employer_partner_payload(
        name=name, industry=industry, open_requisitions=open_requisitions)
    return get_success_data(api_client.create_employer_partner(payload, CAREER))


def list_employer_partners() -> list:
    data, _meta = _paginate(api_client.list_employer_partners(CAREER))
    return data


def get_employer_by_name(name) -> dict:
    return next(e for e in list_employer_partners() if e["name"] == name)


def create_placement(member_id, employer_partner_id,
                     start_date="2026-09-15T00:00:00Z", salary_cents=5000000) -> dict:
    payload = factories.create_placement_payload(
        member_id, employer_partner_id, start_date=start_date, salary_cents=salary_cents)
    return get_success_data(api_client.create_placement(payload, CAREER))


def transition_placement(placement_id, action, **fields) -> dict:
    payload = factories.placement_transition_payload(action, **fields)
    return get_success_data(api_client.transition_placement(placement_id, payload, CAREER))


def list_placements(**filters) -> list:
    params = {k: v for k, v in filters.items() if v is not None}
    data, _meta = _paginate(api_client.list_placements(CAREER, params=params or None))
    return data


def setup_member_with_active_career_enrollment(capacity=10, member_name="Career Veteran"):
    """CAREER track + VERIFIED veteran + ACTIVE career enrollment."""
    return setup_verified_member_with_enrollment(
        track_code="CAREER", capacity=capacity, scores=(5, 5, 5, 5),
        member_name=member_name)


# ---- community events and registrations ----------------------------------------
def create_community_event(name="Community Event",
                           starts_at="2026-10-20T09:00:00Z",
                           ends_at="2026-10-20T11:00:00Z", capacity=5,
                           accessibility_seat_count=0, travel_budget_cents=0) -> dict:
    payload = factories.create_community_event_payload(
        name=name, starts_at=starts_at, ends_at=ends_at, capacity=capacity,
        accessibility_seat_count=accessibility_seat_count,
        travel_budget_cents=travel_budget_cents)
    return get_success_data(api_client.create_community_event(payload, EVENT))


def list_community_events() -> list:
    data, _meta = _paginate(api_client.list_community_events(EVENT))
    return data


def get_community_event(event_id) -> dict:
    return next(e for e in list_community_events() if e["id"] == event_id)


def create_event_registration(member_id, community_event_id,
                              accommodation_needs=None,
                              travel_request_cents=None) -> dict:
    overrides = {}
    if accommodation_needs is not None:
        overrides["accommodation_needs"] = accommodation_needs
    if travel_request_cents is not None:
        overrides["travel_request_cents"] = travel_request_cents
    payload = factories.create_event_registration_payload(
        member_id, community_event_id, **overrides)
    return get_success_data(api_client.create_event_registration(payload, EVENT))


def get_event_registration(registration_id) -> dict:
    return get_success_data(api_client.get_event_registration(registration_id, EVENT))


def list_event_registrations(**filters) -> list:
    params = {k: v for k, v in filters.items() if v is not None}
    data, _meta = _paginate(api_client.list_event_registrations(EVENT, params=params or None))
    return data


def transition_event_registration(registration_id, action) -> dict:
    payload = factories.registration_transition_payload(action)
    return get_success_data(
        api_client.transition_event_registration(registration_id, payload, EVENT))


# ---- outcome surveys and donor reports -------------------------------------------
def list_surveys(enrollment_id, wave=None) -> list:
    params = {"wave": wave} if wave else None
    data, _meta = _paginate(api_client.list_surveys(enrollment_id, ANALYST, params=params))
    return data


def get_survey_by_wave(enrollment_id, wave) -> dict:
    rows = list_surveys(enrollment_id, wave=wave)
    assert len(rows) == 1, f"expected exactly 1 {wave} survey, got {len(rows)}"
    return rows[0]


def submit_survey_as_member(survey_id, member_id, q1=3, q2=3, q3=3, q4=3, q5=3) -> dict:
    payload = factories.survey_submission_payload(q1, q2, q3, q4, q5)
    return get_success_data(api_client.submit_survey(
        survey_id, payload, make_program_member_headers(member_id)))


def create_donor_report(period_start, period_end, methodology="ITT",
                        track_weights=None) -> dict:
    overrides = {}
    if track_weights is not None:
        overrides["track_weights"] = track_weights
    payload = factories.create_donor_report_payload(
        period_start, period_end, methodology, **overrides)
    return get_success_data(api_client.create_donor_report(payload, ANALYST))


def get_donor_report(report_id) -> dict:
    return get_success_data(api_client.get_donor_report(report_id, ANALYST))


def complete_enrollment(enrollment_id, exit_reason="program complete") -> dict:
    return transition_enrollment(enrollment_id, "COMPLETED", exit_reason=exit_reason)


# ---- internal ------------------------------------------------------------------
def _paginate(resp):
    """Lenient paginated read for setup paths (any 2xx)."""
    body = resp.json()
    assert 200 <= resp.status_code < 300, f"Setup list call failed: {body}"
    return body["data"], body.get("meta", {})
