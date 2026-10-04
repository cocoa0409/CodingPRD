"""Composite setup helpers for the care navigation test suite.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before each test). Setup calls use
the lenient get_success_data validator so failures surface as clear
"Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK, TEST_DEFAULTS
from .factories import (
    create_employer_payload,
    create_member_payload,
    create_provider_payload,
    create_quality_snapshot_payload,
    create_consent_payload,
    create_navigation_case_payload,
    create_appointment_payload,
    create_record_request_payload,
    create_expert_opinion_payload,
    create_claim_payload,
    create_billing_case_payload,
    create_authorization_payload,
    claim_line,
)
from .test_users import (
    TEST_USERS,
    make_member_headers,
    make_care_advocate_headers,
    make_nurse_navigator_headers,
    make_records_specialist_headers,
    make_expert_reviewer_headers,
    make_billing_advocate_headers,
    make_plan_administrator_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PLAN_ADMIN = TEST_USERS["plan_administrator_headers"]


# ---------------------------------------------------------------------------
# Tier 1: clock + employer + member basics
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=DEFAULT_CLOCK):
    return get_success_data(api_client.set_clock(
        {"to_iso8601": to_iso8601}, ADMIN))


def setup_employer(emo_benefit_enabled=False, **overrides):
    """Create an employer. Returns the employer dict."""
    return get_success_data(api_client.create_employer(
        create_employer_payload(emo_benefit_enabled=emo_benefit_enabled,
                                **overrides),
        ADMIN))


def setup_employer_with_member(emo_benefit_enabled=False,
                               member_overrides=None, employer_overrides=None):
    """Create an employer plus one ACTIVE SELF member.
    Returns (employer, member)."""
    emp = setup_employer(emo_benefit_enabled=emo_benefit_enabled,
                         **(employer_overrides or {}))
    member = get_success_data(api_client.create_member(
        emp["id"], create_member_payload(**(member_overrides or {})), ADMIN))
    return emp, member


def grant_consent(member, scope, expires_at=None):
    """Grant the member an ACTIVE consent of the given scope (self call)."""
    payload = create_consent_payload(
        scope=scope,
        expires_at=expires_at or TEST_DEFAULTS["FAR_FUTURE_EXPIRY"])
    return get_success_data(api_client.create_consent(
        member["id"], payload, make_member_headers(member["id"])))


def setup_provider(**overrides):
    """Register a provider. Returns the provider dict."""
    return get_success_data(api_client.create_provider(
        create_provider_payload(**overrides), ADMIN))


def setup_provider_with_snapshot(provider_overrides=None, snapshot_overrides=None):
    """Provider plus one quality snapshot. Returns (provider, snapshot)."""
    prov = setup_provider(**(provider_overrides or {}))
    snap = get_success_data(api_client.create_quality_snapshot(
        prov["id"], create_quality_snapshot_payload(
            **(snapshot_overrides or {})), ADMIN))
    return prov, snap


# ---------------------------------------------------------------------------
# Tier 2: navigation cases
# ---------------------------------------------------------------------------

def setup_navigation_case(member, case_overrides=None, navigator_id=None,
                          navigator_role=None, start=False):
    """Create a navigation case for the member (opened by the member).

    Optionally start it with the given navigator identity. Returns the case
    dict as of the last call."""
    case = get_success_data(api_client.create_navigation_case(
        member["id"],
        create_navigation_case_payload(**(case_overrides or {})),
        make_member_headers(member["id"])))
    if start:
        role = navigator_role or "CareAdvocate"
        uid = navigator_id or "adv-1"
        if role == "CareAdvocate":
            headers = make_care_advocate_headers(uid)
        elif role == "NurseNavigator":
            headers = make_nurse_navigator_headers(uid)
        else:
            from .test_users import make_physician_advisor_headers
            headers = make_physician_advisor_headers(uid)
        case = get_success_data(api_client.start_navigation_case(
            case["id"], headers))
    return case


def setup_closed_navigation_case(member, navigator_id="adv-1"):
    """BENEFIT case driven ROUTED -> IN_PROGRESS -> RESOLVED -> CLOSED."""
    case = setup_navigation_case(member, {"question_type": "BENEFIT"})
    headers = make_care_advocate_headers(navigator_id)
    get_success_data(api_client.start_navigation_case(case["id"], headers))
    get_success_data(api_client.resolve_navigation_case(case["id"], headers))
    return get_success_data(api_client.close_navigation_case(case["id"], headers))


# ---------------------------------------------------------------------------
# Tier 2: appointments
# ---------------------------------------------------------------------------

def setup_booked_appointment(member, provider, slot_start, slot_end,
                             navigation_case_id=None,
                             redirected_from_out_of_network=None,
                             booker_id="adv-1", booker_role="CareAdvocate"):
    """Book an appointment for the member (consent must already exist)."""
    payload = create_appointment_payload(
        provider_id=provider["id"], slot_start=slot_start, slot_end=slot_end)
    if navigation_case_id is not None:
        payload["navigation_case_id"] = navigation_case_id
    if redirected_from_out_of_network is not None:
        payload["redirected_from_out_of_network"] = redirected_from_out_of_network
    if booker_role == "CareAdvocate":
        headers = make_care_advocate_headers(booker_id)
    else:
        headers = make_nurse_navigator_headers(booker_id)
    return get_success_data(api_client.create_appointment(
        member["id"], payload, headers))


def fill_provider_day(member, provider, day, count=8):
    """Book `count` non-overlapping 30-minute appointments for the provider on
    the given UTC date (hours 08..). Returns the list of appointments."""
    appointments = []
    for i in range(count):
        hour = 8 + i
        appt = setup_booked_appointment(
            member, provider,
            f"{day}T{hour:02d}:00:00Z", f"{day}T{hour:02d}:30:00Z")
        appointments.append(appt)
    return appointments


# ---------------------------------------------------------------------------
# Tier 2: claims
# ---------------------------------------------------------------------------

def setup_claim(member, provider, **overrides):
    """Import a RECEIVED claim. Returns the claim dict."""
    payload = create_claim_payload(
        member_id=member["id"], provider_id=provider["id"], **overrides)
    return get_success_data(api_client.create_claim(payload, PLAN_ADMIN))


def setup_adjudicated_claim(member, provider, **overrides):
    """Import + adjudicate a claim. Returns the adjudicated claim dict."""
    claim = setup_claim(member, provider, **overrides)
    return get_success_data(api_client.adjudicate_claim(claim["id"], PLAN_ADMIN))


# ---------------------------------------------------------------------------
# Tier 3: billing cases in target states
# ---------------------------------------------------------------------------

def setup_billing_case_opened(member, provider=None, claim_overrides=None):
    """Member (BILLING_ADVOCACY consent expected already granted by caller) +
    adjudicated claim + OPENED billing case.
    Returns (claim, billing_case)."""
    if provider is None:
        provider = setup_provider()
    claim = setup_adjudicated_claim(member, provider,
                                    **(claim_overrides or {}))
    bc = get_success_data(api_client.create_billing_case(
        member["id"], create_billing_case_payload(claim_id=claim["id"]),
        make_billing_advocate_headers("ba-1")))
    return claim, bc


def setup_billing_case_error_identified(member, provider=None,
                                        claim_overrides=None):
    """OPENED -> ERROR_IDENTIFIED. Returns (claim, billing_case)."""
    claim, bc = setup_billing_case_opened(member, provider, claim_overrides)
    bc = get_success_data(api_client.identify_errors(
        bc["id"], make_billing_advocate_headers("ba-1")))
    return claim, bc


# ---------------------------------------------------------------------------
# Tier 3: record requests
# ---------------------------------------------------------------------------

def setup_record_request(member, provider, specialist_id="rs-1"):
    """Create a REQUESTED record request (consent must exist)."""
    return get_success_data(api_client.create_record_request(
        member["id"], create_record_request_payload(provider_id=provider["id"]),
        make_records_specialist_headers(specialist_id)))


def setup_received_record_request(member, provider, pages=10,
                                  specialist_id="rs-1"):
    """Create + receive a record request. Returns the RECEIVED request."""
    rr = setup_record_request(member, provider, specialist_id)
    return get_success_data(api_client.receive_record_request(
        rr["id"], {"record_pages": pages},
        make_records_specialist_headers(specialist_id)))


# ---------------------------------------------------------------------------
# Tier 3: authorizations
# ---------------------------------------------------------------------------

def setup_authorization(member, service_code="EXPERT_MEDICAL_OPINION", units=1):
    """Member requests an authorization (REQUESTED). Returns the auth."""
    return get_success_data(api_client.create_authorization(
        member["id"], create_authorization_payload(
            service_code=service_code, units=units),
        make_member_headers(member["id"])))


def setup_approved_authorization(member, service_code="EXPERT_MEDICAL_OPINION",
                                 units=1, plan_admin_id="pa-1"):
    auth = setup_authorization(member, service_code, units)
    return get_success_data(api_client.approve_authorization(
        auth["id"], make_plan_administrator_headers(plan_admin_id)))


# ---------------------------------------------------------------------------
# Tier 4: expert opinion pipeline
# ---------------------------------------------------------------------------

def setup_emo_member(emo_benefit_enabled=True, employer_overrides=None,
                     member_overrides=None):
    """Employer (benefit on) + member with RECORD_RETRIEVAL and EMO_REVIEW
    consents. Returns (employer, member)."""
    emp, member = setup_employer_with_member(
        emo_benefit_enabled=emo_benefit_enabled,
        employer_overrides=employer_overrides,
        member_overrides=member_overrides)
    grant_consent(member, "RECORD_RETRIEVAL")
    grant_consent(member, "EMO_REVIEW")
    return emp, member


def setup_emo_case_with_records(member, num_received=3,
                                with_approved_auth=True,
                                condition_summary="Expert review",
                                navigation_case_id=None,
                                specialist_id="rs-1",
                                num_providers=3):
    """Build an opinion case in RECORDS_COLLECTION with num_received RECEIVED
    record requests attached. Returns (opinion, [record_requests], [providers]).
    """
    if with_approved_auth:
        setup_approved_authorization(member)
    providers = [setup_provider(name=f"EMO Clinic {i + 1}")
                 for i in range(max(num_providers, num_received, 1))]
    requests = []
    for i in range(num_received):
        requests.append(setup_received_record_request(
            member, providers[i], pages=5 + i, specialist_id=specialist_id))
    payload = create_expert_opinion_payload(
        condition_summary=condition_summary)
    if navigation_case_id is not None:
        payload["navigation_case_id"] = navigation_case_id
    opinion = get_success_data(api_client.create_expert_opinion(
        member["id"], payload, make_member_headers(member["id"])))
    for rr in requests:
        get_success_data(api_client.attach_records(
            opinion["id"], {"record_request_id": rr["id"]},
            make_records_specialist_headers(specialist_id)))
    opinion = get_success_data(api_client.get_expert_opinion(
        opinion["id"], make_member_headers(member["id"])))
    return opinion, requests, providers


def setup_emo_case_compiling(member, num_received=3, specialist_id="rs-1",
                             with_approved_auth=True, **kwargs):
    """Opinion case driven to COMPILING by specialist_id.
    Returns (opinion, requests, providers)."""
    opinion, requests, providers = setup_emo_case_with_records(
        member, num_received=num_received,
        with_approved_auth=with_approved_auth,
        specialist_id=specialist_id, **kwargs)
    opinion = get_success_data(api_client.compile_expert_opinion(
        opinion["id"], make_records_specialist_headers(specialist_id)))
    return opinion, requests, providers


def setup_emo_case_ready_for_review(member, specialist_id="rs-1", **kwargs):
    """Opinion case driven to READY_FOR_REVIEW.
    Returns (opinion, requests, providers)."""
    opinion, requests, providers = setup_emo_case_compiling(
        member, specialist_id=specialist_id, **kwargs)
    opinion = get_success_data(api_client.submit_for_review(
        opinion["id"], make_records_specialist_headers(specialist_id)))
    return opinion, requests, providers


def setup_emo_case_in_review(member, specialist_id="rs-1", reviewer_id="er-1",
                             **kwargs):
    """Opinion case driven to IN_REVIEW (compiler != reviewer).
    Returns (opinion, requests, providers)."""
    opinion, requests, providers = setup_emo_case_ready_for_review(
        member, specialist_id=specialist_id, **kwargs)
    opinion = get_success_data(api_client.claim_review(
        opinion["id"], make_expert_reviewer_headers(reviewer_id)))
    return opinion, requests, providers
