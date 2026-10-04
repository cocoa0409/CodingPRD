"""Composite setup helpers.

Every helper builds its preconditions from scratch through the API, because
the server is restarted before each test and no state survives between tests.
Setup calls use the lenient validator so a broken precondition reports
"Setup failed" rather than an assertion mismatch deep inside a test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START_UTC
from .factories import (
    STANDARD_DIMENSIONS,
    WEAK_DIMENSIONS,
    create_analyst_payload,
    create_briefing_payload,
    create_client_payload,
    create_conference_event_payload,
    create_document_payload,
    create_inclusion_payload,
    create_inquiry_payload,
    create_sales_relationship_payload,
    create_seat_payload,
    create_session_payload,
    create_sponsorship_payload,
    create_vendor_payload,
)
from .test_users import (
    TEST_USERS,
    make_analyst_headers,
    make_client_admin_headers,
    make_seat_holder_headers,
    make_vendor_rep_headers,
)

PLATFORM = TEST_USERS["platform_admin_headers"]
DIRECTOR = TEST_USERS["research_director_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
PROGRAMMER = TEST_USERS["event_programmer_headers"]
SALES = TEST_USERS["sales_rep_headers"]


# ─── Clock ────────────────────────────────────────────

def set_clock(current_utc):
    """Advance the logical clock; this operation carries no auth headers."""
    resp = api_client.set_clock(current_utc)
    assert resp.status_code == 200, (
        f"Setup failed: clock advance to {current_utc} returned {resp.status_code}: {resp.text}"
    )
    return current_utc


# ─── Tier 1: entity creation and state progression ────

def create_account(**overrides):
    resp = api_client.create_client(create_client_payload(**overrides), PLATFORM)
    return get_success_data(resp, expected_status=201)


def get_account(account, headers=None):
    resp = api_client.get_client(account["id"], headers or PLATFORM)
    return get_success_data(resp, expected_status=200)


def create_analyst(**overrides):
    resp = api_client.create_analyst(create_analyst_payload(**overrides), PLATFORM)
    return get_success_data(resp, expected_status=201)


def get_analyst(analyst, headers=None):
    resp = api_client.get_analyst(analyst["id"], headers or PLATFORM)
    return get_success_data(resp, expected_status=200)


def create_vendor(**overrides):
    resp = api_client.create_vendor(create_vendor_payload(**overrides), PLATFORM)
    return get_success_data(resp, expected_status=201)


def get_vendor(vendor, headers=None):
    resp = api_client.get_vendor(vendor["id"], headers or PLATFORM)
    return get_success_data(resp, expected_status=200)


def create_seat(account, **overrides):
    headers = make_client_admin_headers(account["id"])
    resp = api_client.create_seat(create_seat_payload(account["id"], **overrides), headers)
    return get_success_data(resp, expected_status=201)


def activate_seat(account, seat):
    headers = make_client_admin_headers(account["id"])
    resp = api_client.activate_seat(seat["id"], headers)
    return get_success_data(resp, expected_status=200)


def revoke_seat(account, seat):
    headers = make_client_admin_headers(account["id"])
    resp = api_client.revoke_seat(seat["id"], headers)
    return get_success_data(resp, expected_status=200)


def create_active_seat(account, **overrides):
    seat = create_seat(account, **overrides)
    return activate_seat(account, seat)


def get_seat(seat, headers=None):
    resp = api_client.get_seat(seat["id"], headers or PLATFORM)
    return get_success_data(resp, expected_status=200)


def setup_account_with_active_seat(seat_count_contracted=10, inquiry_allowance_total=10,
                                   seat_email="nina@acme.example",
                                   research_role="PRACTITIONER",
                                   account_overrides=None, seat_overrides=None,
                                   analyst_overrides=None):
    """Account + one ACTIVE seat + one ACTIVE analyst on CLOUD_COST.

    Returns (account, seat, analyst).
    """
    account = create_account(
        seat_count_contracted=seat_count_contracted,
        inquiry_allowance_total=inquiry_allowance_total,
        **(account_overrides or {}),
    )
    seat = create_active_seat(
        account, seat_email=seat_email, research_role=research_role,
        **(seat_overrides or {}),
    )
    analyst = create_analyst(**(analyst_overrides or {}))
    return account, seat, analyst


def setup_account_with_active_seats(seat_count_contracted, inquiry_allowance_total,
                                    active_count, email_prefix="seat",
                                    account_overrides=None, role="PRACTITIONER"):
    """Account + `active_count` ACTIVE seats. Returns (account, [seats])."""
    account = create_account(
        seat_count_contracted=seat_count_contracted,
        inquiry_allowance_total=inquiry_allowance_total,
        **(account_overrides or {}),
    )
    seats = []
    for index in range(active_count):
        seats.append(create_active_seat(
            account,
            seat_email=f"{email_prefix}{index + 1}@example.com",
            research_role=role,
        ))
    return account, seats


def create_document(lead, omit_fields=None, **overrides):
    """Open a document; `omit_fields` drops optional keys from the payload."""
    payload = create_document_payload(lead["id"], **overrides)
    for field in omit_fields or []:
        payload.pop(field, None)
    headers = make_analyst_headers(lead["id"])
    resp = api_client.create_document(payload, headers)
    return get_success_data(resp, expected_status=201)


def get_document(document, headers=None):
    resp = api_client.get_document(document["id"], headers or PLATFORM)
    return get_success_data(resp, expected_status=200)


def create_inclusion(document, vendor, dimensions=None, **overrides):
    """Propose a vendor on a document, always using the document's live version."""
    fresh = get_document(document)
    headers = make_analyst_headers(fresh["lead_analyst_id"])
    payload = create_inclusion_payload(
        vendor["id"], fresh["version"],
        dimension_scores=[dict(row) for row in (dimensions or STANDARD_DIMENSIONS)],
        **overrides,
    )
    resp = api_client.create_inclusion(fresh["id"], payload, headers)
    return get_success_data(resp, expected_status=201)


def create_event(**overrides):
    resp = api_client.create_conference_event(
        create_conference_event_payload(**overrides), PROGRAMMER
    )
    return get_success_data(resp, expected_status=201)


def get_event(event, headers=None):
    resp = api_client.get_conference_event(event["id"], headers or PROGRAMMER)
    return get_success_data(resp, expected_status=200)


def append_session(event, **overrides):
    resp = api_client.append_session(
        event["id"], create_session_payload(**overrides), PROGRAMMER
    )
    return get_success_data(resp, expected_status=200)


def create_sponsorship(event, vendor, **overrides):
    """Sell a package, always presenting the event's live version."""
    fresh = get_event(event)
    resp = api_client.create_sponsorship(
        create_sponsorship_payload(fresh["id"], vendor["id"], fresh["version"], **overrides),
        SALES,
    )
    return get_success_data(resp, expected_status=201)


def lock_agenda(event, headers=None):
    resp = api_client.lock_agenda(event["id"], headers or PROGRAMMER)
    return get_success_data(resp, expected_status=200)


def activate_sponsorship(sponsorship):
    resp = api_client.activate_sponsorship(sponsorship["id"], PROGRAMMER)
    return get_success_data(resp, expected_status=200)


def cancel_sponsorship(sponsorship, reason="Vendor withdrew"):
    resp = api_client.cancel_sponsorship(
        sponsorship["id"], {"cancel_reason": reason}, PROGRAMMER
    )
    return get_success_data(resp, expected_status=200)


def create_sales_relationship(analyst, vendor, **overrides):
    """Register a commercial tie against the analyst's live version."""
    fresh = get_analyst(analyst)
    resp = api_client.create_sales_relationship(
        create_sales_relationship_payload(fresh["id"], vendor["id"], fresh["version"],
                                          **overrides),
        SALES,
    )
    return get_success_data(resp, expected_status=201)


def create_briefing(vendor, **overrides):
    headers = make_vendor_rep_headers(vendor["id"])
    resp = api_client.create_briefing(create_briefing_payload(vendor["id"], **overrides), headers)
    return get_success_data(resp, expected_status=201)


def get_briefing(briefing, headers=None):
    resp = api_client.get_briefing(briefing["id"], headers or PLATFORM)
    return get_success_data(resp, expected_status=200)


# ─── Tier 2: inquiry lifecycle ────────────────────────

def create_routed_inquiry(account, seat, **overrides):
    """Submit an inquiry from `seat`; topic routing assigns an analyst."""
    headers = make_seat_holder_headers(seat["id"])
    resp = api_client.create_inquiry(create_inquiry_payload(seat["id"], **overrides), headers)
    return get_success_data(resp, expected_status=201)


def schedule_inquiry(analyst, inquiry, scheduled_start_utc):
    headers = make_analyst_headers(analyst["id"])
    resp = api_client.schedule_inquiry(
        inquiry["id"], {"scheduled_start_utc": scheduled_start_utc}, headers
    )
    return get_success_data(resp, expected_status=200)


def create_scheduled_inquiry(account, seat, analyst, scheduled_start_utc, **overrides):
    overrides.setdefault("requested_start_utc", scheduled_start_utc)
    inquiry = create_routed_inquiry(account, seat, **overrides)
    return schedule_inquiry(analyst, inquiry, scheduled_start_utc)


def complete_inquiry(analyst, inquiry, at_clock, outcome="COMPLETED",
                     note_delivered=True, note_reference="NOTE-1"):
    """Advance the clock to `at_clock` and close the inquiry out."""
    set_clock(at_clock)
    headers = make_analyst_headers(analyst["id"])
    resp = api_client.complete_inquiry(
        inquiry["id"],
        {"outcome": outcome, "note_delivered": note_delivered,
         "note_reference": note_reference},
        headers,
    )
    return get_success_data(resp, expected_status=200)


def create_completed_inquiry(account, seat, analyst, scheduled_start_utc, complete_at,
                             **overrides):
    """Create -> schedule -> complete one inquiry. Returns the settled inquiry."""
    inquiry = create_scheduled_inquiry(
        account, seat, analyst, scheduled_start_utc, **overrides
    )
    return complete_inquiry(analyst, inquiry, complete_at)


def setup_account_with_completed_inquiries(completed_count, seat_count_contracted=10,
                                           inquiry_allowance_total=10,
                                           first_start="2026-09-02T10:00:00Z",
                                           complete_at="2026-09-02T13:00:00Z",
                                           account_overrides=None,
                                           analyst_overrides=None):
    """Account + ACTIVE seat + analyst with `completed_count` settled inquiries.

    Each inquiry is scheduled 30 minutes apart on 2026-09-02 and completed
    after the clock has moved past the last slot.
    """
    account, seat, analyst = setup_account_with_active_seat(
        seat_count_contracted=seat_count_contracted,
        inquiry_allowance_total=inquiry_allowance_total,
        account_overrides=account_overrides,
        analyst_overrides=analyst_overrides,
    )
    base_hour = 10
    inquiries = []
    for index in range(completed_count):
        start = f"2026-09-02T{base_hour + index:02d}:00:00Z"
        inquiries.append(
            create_completed_inquiry(
                account, seat, analyst, start, complete_at,
                question_summary=f"Completed inquiry {index + 1}",
            )
        )
    return account, seat, analyst, inquiries


# ─── Tier 3: document lifecycle shortcuts ─────────────

def finalize_inclusion(inclusion, outcome="INCLUDE", headers=None):
    resp = api_client.finalize_inclusion(
        inclusion["id"], {"outcome": outcome}, headers or DIRECTOR
    )
    return get_success_data(resp, expected_status=200)


def submit_for_review(document, lead, reviewer):
    headers = make_analyst_headers(lead["id"])
    resp = api_client.submit_for_review(
        document["id"], {"peer_reviewer_analyst_id": reviewer["id"]}, headers
    )
    return get_success_data(resp, expected_status=200)


def record_peer_verdict(document, reviewer, verdict="APPROVE"):
    headers = make_analyst_headers(reviewer["id"])
    resp = api_client.record_peer_verdict(
        document["id"], {"verdict": verdict, "comments": "Methodology sound."}, headers
    )
    return get_success_data(resp, expected_status=200)


def respond_fact_check(inclusion, vendor, summary="Revenue figure restated.",
                       correction_offered=True):
    headers = make_vendor_rep_headers(vendor["id"])
    resp = api_client.respond_fact_check(
        inclusion["id"],
        {"response_summary": summary, "correction_offered": correction_offered},
        headers,
    )
    return get_success_data(resp, expected_status=200)


def decide_fact_check(inclusion, outcome="ACCEPT"):
    resp = api_client.decide_fact_check(inclusion["id"], {"outcome": outcome}, DIRECTOR)
    return get_success_data(resp, expected_status=200)


def publish_document(document, headers=None):
    resp = api_client.publish_document(document["id"], headers or DIRECTOR)
    return get_success_data(resp, expected_status=200)


def revise_document(document, lead, reason="Vendor supplied corrected revenue figures"):
    headers = make_analyst_headers(lead["id"])
    resp = api_client.revise_document(document["id"], {"revision_reason": reason}, headers)
    return get_success_data(resp, expected_status=200)


def setup_document_with_inclusion(lead=None, reviewer=None, vendor=None,
                                  doc_overrides=None, inclusion_overrides=None,
                                  dimensions=None, criteria=5,
                                  vendor_overrides=None, analyst_overrides=None,
                                  reviewer_overrides=None):
    """Lead analyst + reviewer analyst + vendor + DRAFT document + one inclusion.

    Returns a dict with keys: lead, reviewer, vendor, document, inclusion.
    """
    lead = lead or create_analyst(**(analyst_overrides or {}))
    reviewer = reviewer or create_analyst(
        full_name="Ravi Menon", seniority="SENIOR", topic_routes=["CLOUD_COST"],
        **(reviewer_overrides or {}),
    )
    vendor = vendor or create_vendor(**(vendor_overrides or {}))
    document = create_document(lead, **(doc_overrides or {}))
    inclusion = create_inclusion(
        document, vendor, dimensions=dimensions,
        inclusion_criteria_met_count=criteria,
        **(inclusion_overrides or {}),
    )
    return {
        "lead": lead, "reviewer": reviewer, "vendor": vendor,
        "document": document, "inclusion": inclusion,
    }


def advance_document_to_cleared(scenario):
    """Finalize the inclusion INCLUDE, run peer review and the fact-check cycle.

    Returns the CLEARED document.
    """
    finalize_inclusion(scenario["inclusion"], "INCLUDE")
    submit_for_review(scenario["document"], scenario["lead"], scenario["reviewer"])
    record_peer_verdict(scenario["document"], scenario["reviewer"], "APPROVE")
    respond_fact_check(scenario["inclusion"], scenario["vendor"])
    decide_fact_check(scenario["inclusion"], "ACCEPT")
    return get_document(scenario["document"])


def setup_published_document(exclude_vendor=False, second_vendor=None,
                             second_vendor_overrides=None,
                             second_inclusion_overrides=None,
                             second_dimensions=None, second_criteria=3,
                             publish=True, clock=CLOCK_START_UTC, **kwargs):
    """Walk a document all the way to PUBLISHED with one INCLUDED vendor.

    When `exclude_vendor` is true a second vendor is proposed, evaluated with
    weak dimensions and finalized EXCLUDE before peer review runs.

    Returns a dict with keys: lead, reviewer, vendor, document, inclusion and,
    when requested, excluded_vendor and excluded_inclusion.
    """
    set_clock(clock)
    scenario = setup_document_with_inclusion(**kwargs)
    if exclude_vendor:
        scenario["excluded_vendor"] = second_vendor or create_vendor(
            vendor_name="Bluepeak Systems", hq_region="EMEA",
            employee_count_band="MIDMARKET",
            **(second_vendor_overrides or {}),
        )
        fresh = get_document(scenario["document"])
        scenario["excluded_inclusion"] = create_inclusion(
            fresh, scenario["excluded_vendor"],
            dimensions=second_dimensions or WEAK_DIMENSIONS,
            inclusion_criteria_met_count=second_criteria,
            **(second_inclusion_overrides or {}),
        )
        finalize_inclusion(scenario["excluded_inclusion"], "EXCLUDE")
    scenario["document"] = advance_document_to_cleared(scenario)
    if publish:
        scenario["document"] = publish_document(scenario["document"])
    return scenario
