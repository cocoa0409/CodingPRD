"""Composite setup helpers.

Every fixture builds its preconditions from scratch against a freshly started
server using only PRD-declared endpoints. Identity threading is mandatory:
TPAAdministrator calls carry the acting TPA's id, ProviderRep calls carry the
acting provider's id, and Veteran calls carry the acting veteran's id.

Clock discipline: the logical clock starts at CLOCK_START_ISO
(2026-09-01T00:00:00Z). Fixtures that need a specific clock set it explicitly
via set_clock(). Helpers that must push a deadline into the past
(make_documentation_overdue, record_urgent_visits_on_days) advance the clock
for you; every clock target used here is reachable from the startup instant.
"""
from datetime import date, datetime, timedelta

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import constants as C
from .api_client import api_client
from .factories import (
    adjudicate_claim_payload,
    claim_service_line,
    create_appointment_payload,
    create_care_station_payload,
    create_claim_payload,
    create_eligibility_assessment_payload,
    create_extension_request_payload,
    create_provider_payload,
    create_referral_authorization_payload,
    create_rx_appointment_payload,
    create_rx_urgent_payload,
    create_tpa_payload,
    create_urgent_care_visit_payload,
    create_veteran_payload,
    credential_decision_payload,
    decide_extension_request_payload,
    decide_rx_payload,
    resubmit_claim_payload,
    reverse_payment_payload,
    review_documentation_payload,
    submit_documentation_payload,
)
from .test_users import (
    TEST_USERS,
    make_provider_rep_headers,
    make_tpa_admin_headers,
    make_veteran_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CLERK = TEST_USERS["eligibility_clerk_headers"]
COORD = TEST_USERS["care_coordinator_headers"]
NETMGR = TEST_USERS["network_manager_headers"]
PHARM = TEST_USERS["system_pharmacist_headers"]


# ---------------------------------------------------------------------------
# Date / clock helpers
# ---------------------------------------------------------------------------

def iso_at(day: str, hour: int = 10, minute: int = 0) -> str:
    """Format a calendar date plus time as an ISO8601 UTC instant."""
    return f"{day}T{hour:02d}:{minute:02d}:00Z"


def add_days_to_date(day: str, days: int) -> str:
    return (date.fromisoformat(day) + timedelta(days=days)).isoformat()


def add_days_to_iso(ts: str, days: int) -> str:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00")) + timedelta(days=days)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def set_clock(to_iso8601: str = C.CLOCK_START_ISO) -> str:
    """Drive the logical clock (PlatformAdmin); returns the resulting current_utc."""
    data = get_success_data(api_client.set_clock(to_iso8601, ADMIN))
    return data["current_utc"]


def reset_clock() -> str:
    """Re-pin the clock to the startup instant 2026-09-01T00:00:00Z."""
    return set_clock(C.CLOCK_START_ISO)


# ---------------------------------------------------------------------------
# Leaf creators: station / tpa / provider / veteran / assessment
# ---------------------------------------------------------------------------

def create_station(**overrides) -> dict:
    resp = api_client.create_care_station(create_care_station_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_tpa(**overrides) -> dict:
    resp = api_client.create_tpa(create_tpa_payload(**overrides), ADMIN)
    return get_success_data(resp)


def get_tpa(tpa_id: str) -> dict:
    return get_success_data(api_client.get_tpa(tpa_id, COORD))


def onboard_provider(tpa: dict, credential: bool = True, **overrides) -> dict:
    """Onboard a provider into tpa's network (acting TPAAdministrator == tpa.id).
    credential=True also drives PENDING -> CREDENTIALED via NetworkManager."""
    resp = api_client.create_provider(
        tpa["id"], create_provider_payload(**overrides),
        make_tpa_admin_headers(tpa["id"]),
    )
    provider = get_success_data(resp)
    if credential:
        decide_credential(provider, "CREDENTIALED")
        provider = get_provider(tpa["id"], provider["id"])
    return provider


def decide_credential(provider: dict, target_status: str = "CREDENTIALED") -> dict:
    resp = api_client.decide_credential(
        provider["id"], credential_decision_payload(target_status), NETMGR
    )
    return get_success_data(resp)


def get_provider(tpa_id: str, provider_id: str) -> dict:
    """No single-provider GET exists; read through the TPA's roster."""
    items, _meta = validate_paginated(api_client.list_providers(tpa_id, COORD))
    for p in items:
        if p["id"] == provider_id:
            return p
    raise AssertionError(f"Setup failed: provider {provider_id} not found under TPA {tpa_id}")


def create_veteran(station: dict, **overrides) -> dict:
    resp = api_client.create_veteran(
        create_veteran_payload(station["id"], **overrides), CLERK
    )
    return get_success_data(resp)


def get_veteran(veteran_id: str) -> dict:
    return get_success_data(api_client.get_veteran(veteran_id, CLERK))


def run_assessment(veteran_id: str, expect_eligible=None, **overrides) -> dict:
    """Create an eligibility assessment. Re-reads the veteran so the OCC field
    expected_veteran_version always matches the current version."""
    vet = get_veteran(veteran_id)
    payload = create_eligibility_assessment_payload(vet["version"], **overrides)
    assessment = get_success_data(
        api_client.create_eligibility_assessment(veteran_id, payload, CLERK)
    )
    if expect_eligible is not None:
        assert assessment["eligible"] is expect_eligible, (
            f"Setup failed: assessment eligible == {assessment['eligible']}, expected "
            f"{expect_eligible} (drive_failed={assessment['drive_standard_failed']}, "
            f"wait_failed={assessment['wait_standard_failed']}, "
            f"service_available={assessment['service_available']}, "
            f"choice_granted={assessment['choice_granted']})"
        )
    return assessment


def create_eligible_assessment(veteran_id: str, **overrides) -> dict:
    """Assessment with eligible == True (defaults: PRIMARY_CARE / URBAN with the
    shared fixture geography, so the 30-minute drive standard fails at 37.9)."""
    return run_assessment(veteran_id, expect_eligible=True, **overrides)


# ---------------------------------------------------------------------------
# Referral authorizations and the full episode composite
# ---------------------------------------------------------------------------

def create_referral(veteran: dict, assessment: dict, provider: dict,
                    **overrides) -> dict:
    """Create a PENDING_REVIEW authorization. service_code defaults to the
    assessment's service_code (the PRD requires them to match)."""
    overrides.setdefault("service_code", assessment["service_code"])
    payload = create_referral_authorization_payload(
        veteran["id"], assessment["id"], provider["id"], **overrides
    )
    return get_success_data(api_client.create_referral_authorization(payload, COORD))


def get_authorization(auth_id: str) -> dict:
    return get_success_data(api_client.get_referral_authorization(auth_id, COORD))


def authorize_referral(auth: dict) -> dict:
    return get_success_data(api_client.authorize_referral(auth["id"], COORD))


def cancel_referral(auth: dict, veteran: dict = None) -> dict:
    """Cancel as CareCoordinator, or as the owning Veteran when veteran is given."""
    headers = make_veteran_headers(veteran["id"]) if veteran is not None else COORD
    return get_success_data(api_client.cancel_referral(auth["id"], headers))


def setup_episode(station: dict = None, tpa: dict = None, provider: dict = None,
                  veteran: dict = None, scheduling: str = "TPA",
                  service_code: str = C.DEFAULT_SERVICE_CODE,
                  service_category: str = "PRIMARY_CARE",
                  geo_classification: str = "URBAN",
                  priority_group: int = C.DEFAULT_PRIORITY_GROUP,
                  authorized_visits: int = 2, duration_days: int = 60,
                  start_date: str = C.DEFAULT_START_DATE,
                  authorize: bool = True, contract_rates: dict = None,
                  provider_overrides: dict = None) -> dict:
    """Full chain: station -> TPA -> CREDENTIALED provider -> veteran ->
    CURRENT eligible assessment -> PENDING_REVIEW authorization, then
    AUTHORIZED when authorize=True.

    Returns dict(station, tpa, provider, veteran, assessment, authorization).
    Default eligibility comes from the URBAN drive-time leg (37.9 > 30 min);
    pass geo_classification/service_category/priority_group overrides for other
    eligibility paths (the fixture asserts eligible == True either way).
    """
    station = station or create_station()
    tpa = tpa or create_tpa()
    if provider is None:
        p_over = {"contract_scheduling": scheduling}
        if contract_rates is not None:
            p_over["contract_rates"] = contract_rates
        if provider_overrides:
            p_over.update(provider_overrides)
        provider = onboard_provider(tpa, credential=True, **p_over)
    if veteran is None:
        veteran = create_veteran(station, priority_group=priority_group)
    assessment = create_eligible_assessment(
        veteran["id"], service_code=service_code,
        service_category=service_category, geo_classification=geo_classification,
    )
    auth = create_referral(
        veteran, assessment, provider, authorized_visits=authorized_visits,
        duration_days=duration_days, start_date=start_date,
    )
    if authorize:
        auth = authorize_referral(auth)
    return {
        "station": station, "tpa": tpa, "provider": provider,
        "veteran": veteran, "assessment": assessment, "authorization": auth,
    }


# ---------------------------------------------------------------------------
# Appointments and medical documentation
# ---------------------------------------------------------------------------

def default_slot_start(slot_index: int = 0,
                       base_date: str = C.DEFAULT_APPOINTMENT_DATE) -> str:
    """Distinct non-overlapping slot: base_date + slot_index days at 10:00Z.
    For same-day multi-slot scenarios pass an explicit scheduled_start."""
    return iso_at(add_days_to_date(base_date, slot_index), 10)


def schedule_appointment(auth: dict, scheduled_start: str = None,
                         requested_date: str = C.DEFAULT_REQUESTED_DATE,
                         headers: dict = None) -> dict:
    """Schedule against auth with the caller the scheduling split assigns:
    the owning TPAAdministrator (auth.tpa_id) when scheduling_responsibility
    is TPA, else a CareCoordinator. Pass headers explicitly only to exercise
    the wrong-caller path."""
    if headers is None:
        if auth["scheduling_responsibility"] == "TPA":
            headers = make_tpa_admin_headers(auth["tpa_id"])
        else:
            headers = COORD
    payload = create_appointment_payload(
        scheduled_start=scheduled_start, requested_date=requested_date
    )
    return get_success_data(
        api_client.create_appointment(auth["id"], payload, headers)
    )


def get_appointment(appointment_id: str) -> dict:
    return get_success_data(api_client.get_appointment(appointment_id, COORD))


def list_appointments(auth_id: str, params: dict = None):
    return validate_paginated(api_client.list_appointments(auth_id, COORD, params=params))


def complete_appointment(appointment: dict, provider: dict) -> dict:
    """The treating provider completes its own appointment."""
    return get_success_data(api_client.complete_appointment(
        appointment["id"], make_provider_rep_headers(provider["id"])
    ))


def get_documentation_for_appointment(appointment_id: str):
    """Documentation read-back is a collection of length 0 or 1."""
    items, _meta = validate_paginated(
        api_client.get_documentation(appointment_id, COORD)
    )
    return items[0] if items else None


def complete_appointment_with_doc(appointment: dict, provider: dict):
    """Complete and return (appointment, auto-created AWAITED documentation)."""
    appt = complete_appointment(appointment, provider)
    doc = get_documentation_for_appointment(appt["id"])
    assert doc is not None and doc["status"] == "AWAITED", (
        f"Setup failed: completion must auto-create AWAITED documentation, "
        f"got {doc and doc['status']}"
    )
    return appt, doc


def submit_documentation(appointment: dict, provider: dict,
                         content_ref: str = "bundle-v1") -> dict:
    return get_success_data(api_client.submit_documentation(
        appointment["id"], submit_documentation_payload(content_ref=content_ref),
        make_provider_rep_headers(provider["id"]),
    ))


def review_documentation(doc_id: str, decision: str = "ACCEPTED", **overrides) -> dict:
    return get_success_data(api_client.review_documentation(
        doc_id, review_documentation_payload(decision, **overrides), COORD
    ))


def accept_documentation(appointment: dict, provider: dict,
                         content_ref: str = "bundle-v1") -> dict:
    """Provider submits the bundle, CareCoordinator accepts it."""
    doc = submit_documentation(appointment, provider, content_ref)
    return review_documentation(doc["id"], "ACCEPTED")


def make_documentation_overdue(appointment: dict, provider: dict,
                               complete_at: str = "2026-09-06T12:00:00Z"):
    """Complete the appointment at a known clock, then advance the clock past
    the 30-day documentation deadline so the record flips OVERDUE (which
    cascades the authorization to DOCS_SUSPENDED and auto-denies its PENDING
    extension requests). The episode window must outlive the clock jump —
    build the episode with duration_days >= 60.

    Returns (appointment, documentation) after the sweep."""
    set_clock(complete_at)
    appt, doc = complete_appointment_with_doc(appointment, provider)
    past_deadline = add_days_to_iso(complete_at, C.DOC_RETURN_DEADLINE_DAYS + 1)
    set_clock(past_deadline)
    doc = get_documentation_for_appointment(appt["id"])
    assert doc["status"] == "OVERDUE", (
        f"Setup failed: documentation status {doc['status']} after clock {past_deadline}"
    )
    return appt, doc


# ---------------------------------------------------------------------------
# Extension requests
# ---------------------------------------------------------------------------

def create_extension_request(auth: dict, requested_visits: int = 2,
                             requested_extra_days: int = 0,
                             as_provider: dict = None) -> dict:
    """Create a PENDING extension request. as_provider threads a ProviderRep
    identity (extension create is shared CareCoordinator/ProviderRep)."""
    payload = create_extension_request_payload(
        requested_visits=requested_visits, requested_extra_days=requested_extra_days
    )
    headers = (make_provider_rep_headers(as_provider["id"])
               if as_provider is not None else COORD)
    return get_success_data(
        api_client.create_extension_request(auth["id"], payload, headers)
    )


def list_extension_requests(auth_id: str, params: dict = None):
    return validate_paginated(
        api_client.list_extension_requests(auth_id, COORD, params=params)
    )


def decide_extension_request(auth_id: str, ext_id: str, decision: str = "APPROVED",
                             denial_reason: str = None) -> dict:
    """Re-reads the authorization so expected_referral_authorization_version
    always matches the current version before deciding."""
    auth = get_authorization(auth_id)
    payload = decide_extension_request_payload(decision, auth["version"])
    if denial_reason is not None:
        payload["denial_reason"] = denial_reason
    return get_success_data(
        api_client.decide_extension_request(auth_id, ext_id, payload, COORD)
    )


def approve_extension(auth_id: str, ext_id: str) -> dict:
    return decide_extension_request(auth_id, ext_id, "APPROVED")


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------

def create_claim_for_appointment(auth: dict, appointment: dict, provider: dict,
                                 service_lines: list = None,
                                 service_date: str = None) -> dict:
    """Submit a claim as the authorization's provider. service_date defaults
    to the appointment's scheduled date, which the PRD requires to match a
    COMPLETED appointment's date."""
    service_date = service_date or appointment["scheduled_start"][:10]
    payload = create_claim_payload(auth["id"], service_date, service_lines)
    return get_success_data(
        api_client.create_claim(payload, make_provider_rep_headers(provider["id"]))
    )


def get_claim(claim_id: str) -> dict:
    return get_success_data(api_client.get_claim(claim_id, COORD))


def list_claims(params: dict = None):
    return validate_paginated(api_client.list_claims(COORD, params=params))


def adjudicate_claim(claim_id: str, tpa: dict, decision: str = "PAID",
                     denial_reason: str = None) -> dict:
    """The owning TPAAdministrator (tpa.id) adjudicates."""
    payload = adjudicate_claim_payload(decision)
    if denial_reason is not None:
        payload["denial_reason"] = denial_reason
    return get_success_data(
        api_client.adjudicate_claim(claim_id, payload, make_tpa_admin_headers(tpa["id"]))
    )


def resubmit_claim(claim_id: str, provider: dict, service_lines: list = None) -> dict:
    return get_success_data(api_client.resubmit_claim(
        claim_id, resubmit_claim_payload(service_lines),
        make_provider_rep_headers(provider["id"]),
    ))


def reverse_claim_payment(claim_id: str, tpa: dict, reason: str = "recoupment") -> dict:
    return get_success_data(api_client.reverse_claim_payment(
        claim_id, reverse_payment_payload(reason=reason),
        make_tpa_admin_headers(tpa["id"]),
    ))


# ---------------------------------------------------------------------------
# Lifecycle composites (claims and episodes in specific states)
# ---------------------------------------------------------------------------

def setup_episode_with_completed_appointments(num_appointments: int = 1,
                                              authorized_visits: int = None,
                                              duration_days: int = 300,
                                              **episode_kw) -> dict:
    """ACTIVE episode with N completed appointments (one per day starting at
    DEFAULT_APPOINTMENT_DATE). authorized_visits defaults to
    num_appointments + 1 so completion does NOT exhaust the episode; pass an
    explicit authorized_visits == num_appointments to reach EXHAUSTED.
    Each completion auto-creates an AWAITED documentation record.

    Returns the setup_episode dict plus appointments=[...] and
    documentations=[...]; authorization is refreshed after the completions.
    """
    if authorized_visits is None:
        authorized_visits = num_appointments + 1
    env = setup_episode(authorized_visits=authorized_visits,
                        duration_days=duration_days, **episode_kw)
    auth = env["authorization"]
    appts, docs = [], []
    for i in range(num_appointments):
        appt = schedule_appointment(auth, scheduled_start=default_slot_start(i))
        appt, doc = complete_appointment_with_doc(appt, env["provider"])
        appts.append(appt)
        docs.append(doc)
    env["appointments"] = appts
    env["documentations"] = docs
    env["authorization"] = get_authorization(auth["id"])
    return env


def setup_received_claim(**kw) -> dict:
    """Episode with one COMPLETED appointment plus one RECEIVED claim billed
    against it. Returns the env dict plus claim."""
    env = setup_episode_with_completed_appointments(num_appointments=1, **kw)
    env["claim"] = create_claim_for_appointment(
        env["authorization"], env["appointments"][0], env["provider"]
    )
    return env


def setup_paid_claim(**kw) -> dict:
    """RECEIVED claim adjudicated PAID by the owning TPA."""
    env = setup_received_claim(**kw)
    env["claim"] = adjudicate_claim(env["claim"]["id"], env["tpa"], "PAID")
    return env


def setup_denied_claim(denial_reason: str = "CLINICAL_REVIEW", **kw) -> dict:
    """RECEIVED claim adjudicated DENIED by the owning TPA."""
    env = setup_received_claim(**kw)
    env["claim"] = adjudicate_claim(
        env["claim"]["id"], env["tpa"], "DENIED", denial_reason
    )
    return env


def setup_closed_episode(**kw) -> dict:
    """One-visit episode driven to CLOSED: the only visit completes
    (EXHAUSTED), then its documentation is submitted and ACCEPTED, which
    auto-closes the authorization."""
    kw.setdefault("authorized_visits", 1)
    env = setup_episode_with_completed_appointments(num_appointments=1, **kw)
    auth = get_authorization(env["authorization"]["id"])
    assert auth["status"] == "EXHAUSTED", (
        f"Setup failed: expected EXHAUSTED after final completion, got {auth['status']}"
    )
    accept_documentation(env["appointments"][0], env["provider"])
    auth = get_authorization(env["authorization"]["id"])
    assert auth["status"] == "CLOSED", (
        f"Setup failed: expected CLOSED after documentation accepted, got {auth['status']}"
    )
    env["authorization"] = auth
    return env


def setup_docs_suspended_episode(**kw) -> dict:
    """ACTIVE episode suspended by an OVERDUE documentation: one appointment
    completed at a known clock, then the clock advanced past its 30-day
    return deadline. duration_days must outlive the jump (default 300).

    Returns the env dict plus appointment and documentation; the
    authorization is refreshed and asserted DOCS_SUSPENDED."""
    kw.setdefault("duration_days", 300)
    env = setup_episode(**kw)
    appt = schedule_appointment(env["authorization"])
    appt, doc = make_documentation_overdue(appt, env["provider"])
    env["appointment"] = appt
    env["documentation"] = doc
    auth = get_authorization(env["authorization"]["id"])
    assert auth["status"] == "DOCS_SUSPENDED", (
        f"Setup failed: expected DOCS_SUSPENDED, got {auth['status']}"
    )
    env["authorization"] = auth
    return env


# ---------------------------------------------------------------------------
# Urgent care
# ---------------------------------------------------------------------------

def record_urgent_visit(veteran: dict, facility_name: str = "QuickCare",
                        clock_iso: str = None, as_clerk: bool = False) -> dict:
    """Record an urgent care visit. clock_iso sets the logical clock first
    (visit_date comes from the clock). Default caller is the veteran themself;
    as_clerk=True uses an EligibilityClerk registering on the veteran's behalf."""
    if clock_iso is not None:
        set_clock(clock_iso)
    headers = CLERK if as_clerk else make_veteran_headers(veteran["id"])
    return get_success_data(api_client.create_urgent_care_visit(
        create_urgent_care_visit_payload(veteran["id"], facility_name=facility_name),
        headers,
    ))


def record_urgent_visits_on_days(veteran: dict, days: list,
                                 facility_name: str = "QuickCare",
                                 hour: int = 8) -> list:
    """Record one visit per calendar day (the same-day rule forbids a second
    RECORDED visit on one date), advancing the clock to each day first.
    Returns the visits in recording order."""
    return [
        record_urgent_visit(veteran, facility_name, clock_iso=iso_at(day, hour))
        for day in days
    ]


def list_urgent_care_visits(veteran_id: str, params: dict = None):
    return validate_paginated(
        api_client.list_urgent_care_visits(veteran_id, COORD, params=params)
    )


# ---------------------------------------------------------------------------
# Prescription fill requests
# ---------------------------------------------------------------------------

def create_rx_for_urgent_visit(visit: dict, provider: dict, **overrides) -> dict:
    """Urgent-care-linked fill request (days_supply cap 14) from a CREDENTIALED
    provider representative."""
    payload = create_rx_urgent_payload(visit["id"], **overrides)
    return get_success_data(api_client.create_prescription_fill_request(
        payload, make_provider_rep_headers(provider["id"])
    ))


def create_rx_for_appointment(appointment: dict, provider: dict, **overrides) -> dict:
    """Appointment-linked fill request (days_supply cap 90); the appointment
    must be COMPLETED and owned by the calling provider."""
    payload = create_rx_appointment_payload(appointment["id"], **overrides)
    return get_success_data(api_client.create_prescription_fill_request(
        payload, make_provider_rep_headers(provider["id"])
    ))


def decide_rx(request_id: str, decision: str = "FILLED",
              refusal_reason: str = None) -> dict:
    payload = decide_rx_payload(decision)
    if refusal_reason is not None:
        payload["refusal_reason"] = refusal_reason
    return get_success_data(
        api_client.decide_prescription_fill_request(request_id, payload, PHARM)
    )
