"""Composite setup helpers.

The harness restarts the server before every test, so every fixture builds
its preconditions from scratch using only PRD-declared endpoints. Setup calls
use get_success_data() (lenient): a setup failure raises a clear "Setup step
failed" error instead of a confusing assertion mismatch.

Identity threading (PRD §2.1): every ownership-gated call is made with
make_business_rep_headers(business["id"]) or make_consumer_headers(
consumer["id"]) built from the actual entity — never a shared constant.

Clock discipline (PRD §2.4): the logical clock starts at exactly
2026-09-01T00:00:00Z. Fixtures pin the clock explicitly before stamping
time-sensitive state and advance it only through POST /_clock/set_current_utc
plus the daily close; nothing here assumes wall-clock time.
"""

from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import api_client
from .constants import (
    CLOCK_START_ISO,
    MEDIATION_OFFER_ACCEPT_DAYS,
    RESPONSE_WINDOW_DAYS,
)
from .test_users import (
    TEST_USERS,
    make_business_rep_headers,
    make_consumer_headers,
)

__all__ = [
    # clock helpers
    "set_clock", "parse_iso", "format_iso",
    "iso_plus_days", "iso_plus_minutes", "iso_plus_seconds",
    # atomic creators
    "create_bureau", "create_consumer", "create_business",
    # reads used by fixtures
    "get_business", "get_complaint", "get_invoice", "get_application",
    "fresh_business_version", "run_daily_close",
    # world
    "setup_world",
    # accreditation journey
    "create_application", "submit_application", "approve_application",
    "deny_application", "setup_submitted_application",
    "setup_approved_application", "pay_invoice_in_full", "post_refund",
    "setup_accredited_business",
    # complaint lifecycle
    "file_complaint", "forward_complaint", "file_and_forward_complaint",
    "business_respond", "consumer_rebuttal", "consumer_accept",
    "consumer_reject", "reopen_complaint", "setup_resolved_complaint",
    "setup_unresolved_complaint", "expire_forwarded_complaint",
    "setup_unanswered_complaint",
    # mediation
    "offer_mediation", "answer_mediation", "accept_mediation",
    "schedule_mediation_session", "conclude_mediation_case",
    "setup_mediation_offered", "setup_mediation_accepted",
    "setup_mediation_scheduled", "setup_mediation_concluded",
    "expire_mediation_offer",
    # arbitration
    "escalate_to_arbitration", "schedule_arbitration_hearing",
    "render_arbitration_decision", "setup_arbitration_filed",
    "setup_arbitration_hearing_scheduled", "setup_arbitration_decided",
    # rating
    "compute_snapshot", "file_rating_dispute", "decide_appeal",
    "publish_and_close_day",
    # advertising reviews
    "open_advertising_review", "conclude_advertising_review",
    # scam reports
    "file_scam_report", "publish_scam_report",
    "setup_published_scam_reports",
    # accumulation targeting
    "setup_business_with_unanswered_complaints",
    "setup_business_with_resolved_complaints",
    "setup_business_with_unresolved_complaints",
]

ADMIN = TEST_USERS["bureau_admin_headers"]
REVIEWER = TEST_USERS["standards_reviewer_headers"]


# ---------------------------------------------------------------------------
# Clock helpers (PRD §2.4)
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str = CLOCK_START_ISO) -> dict:
    """Set the logical clock; returns {"current_utc": ...}."""
    resp = api_client.set_clock(factories.set_clock_payload(to_iso8601),
                                ADMIN)
    return get_success_data(resp)


def parse_iso(iso: str) -> datetime:
    """Parse an ISO 8601 'Z' instant, tolerating optional fractional digits."""
    text = iso.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"not an ISO 8601 Z instant: {iso!r}")


def format_iso(dt: datetime) -> str:
    """Format back to second-precision 'Z' form used by the clock endpoint."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_plus_days(iso: str, days: int) -> str:
    return format_iso(parse_iso(iso) + timedelta(days=days))


def iso_plus_minutes(iso: str, minutes: int) -> str:
    return format_iso(parse_iso(iso) + timedelta(minutes=minutes))


def iso_plus_seconds(iso: str, seconds: int) -> str:
    return format_iso(parse_iso(iso) + timedelta(seconds=seconds))


# ---------------------------------------------------------------------------
# Atomic creators (201 creation endpoints)
# ---------------------------------------------------------------------------
def create_bureau(**overrides) -> dict:
    resp = api_client.create_bureau(factories.create_bureau_payload(
        **overrides), ADMIN)
    return get_success_data(resp)


def create_consumer(**overrides) -> dict:
    resp = api_client.create_consumer(factories.create_consumer_payload(
        **overrides), ADMIN)
    return get_success_data(resp)


def create_business(**overrides) -> dict:
    """Create a business; a bureau covering home_state_code must exist."""
    resp = api_client.create_business(factories.create_business_payload(
        **overrides), ADMIN)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Reads used by fixtures (admin read access is broad — PRD §2.1)
# ---------------------------------------------------------------------------
def get_business(business_id: str) -> dict:
    return get_success_data(api_client.get_business(business_id, ADMIN))


def get_complaint(complaint_id: str) -> dict:
    return get_success_data(api_client.get_complaint(complaint_id, ADMIN))


def get_invoice(business_id: str, invoice_id: str) -> dict:
    """There is no single-invoice GET; list the business's invoices and
    pick the row by id."""
    data = get_success_data(api_client.list_dues_invoices(business_id, ADMIN))
    for row in data:
        if row.get("id") == invoice_id:
            return row
    raise AssertionError(
        f"Setup failed: invoice {invoice_id} not found on business "
        f"{business_id}")


def get_application(business_id: str, application_id: str) -> dict:
    data = get_success_data(
        api_client.list_accreditation_applications(business_id, ADMIN))
    for row in data:
        if row.get("id") == application_id:
            return row
    raise AssertionError(
        f"Setup failed: application {application_id} not found on business "
        f"{business_id}")


def fresh_business_version(business_id: str) -> int:
    """Current Business.version — for the rating-dispute OCC field
    (PRD §2.8)."""
    return get_business(business_id)["version"]


def run_daily_close(bureau_id: str) -> dict:
    """Run the bureau's daily close (PRD §2.4); returns the Bureau row."""
    return get_success_data(api_client.run_daily_close(bureau_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2 — canonical world
# ---------------------------------------------------------------------------
def setup_world(clock: str = CLOCK_START_ISO,
                territory_state_codes=("IA", "NE"),
                local_dues_fee_cents: int = 0,
                bureau_overrides: dict = None,
                consumer_overrides: dict = None,
                business_overrides: dict = None) -> dict:
    """Pin the clock, create one bureau, one consumer, one business.

    Returns {"bureau": ..., "consumer": ..., "business": ...}.
    """
    set_clock(clock)
    bureau_kwargs = {
        "territory_state_codes": list(territory_state_codes),
        "local_dues_fee_cents": local_dues_fee_cents,
    }
    bureau_kwargs.update(bureau_overrides or {})
    bureau = create_bureau(**bureau_kwargs)
    consumer = create_consumer(**(consumer_overrides or {}))
    business = create_business(**(business_overrides or {}))
    return {"bureau": bureau, "consumer": consumer, "business": business}


# ---------------------------------------------------------------------------
# Tier 3 — accreditation application journey (PRD §3.2 / §3.3)
# ---------------------------------------------------------------------------
def create_application(business: dict, billing_plan: str = "ANNUAL_PREPAID",
                       license_number: str = None, **overrides) -> dict:
    """Create a DRAFT application as the owning BusinessRep."""
    payload_kwargs = {"billing_plan": billing_plan}
    if license_number is not None:
        payload_kwargs["license_number"] = license_number
    payload_kwargs.update(overrides)
    resp = api_client.create_accreditation_application(
        business["id"], factories.create_application_payload(
            **payload_kwargs),
        make_business_rep_headers(business["id"]))
    return get_success_data(resp)


def submit_application(application: dict) -> dict:
    """DRAFT -> SUBMITTED as the owning BusinessRep (PRD §3.2 age gate)."""
    resp = api_client.submit_application(
        application["id"],
        make_business_rep_headers(application["business_id"]))
    return get_success_data(resp)


def approve_application(application: dict) -> tuple:
    """SUBMITTED -> APPROVED_PENDING_DUES as StandardsReviewer; issues the
    dues invoice. Returns (application, invoice)."""
    resp = api_client.decide_application(
        application["id"], factories.decide_application_payload(), REVIEWER)
    decided = get_success_data(resp)
    invoice = get_invoice(application["business_id"],
                          decided["dues_invoice_id"])
    return decided, invoice


def deny_application(application: dict, denial_reason: str = None,
                     **checklist) -> dict:
    """SUBMITTED -> DENIED as StandardsReviewer."""
    payload = factories.deny_application_payload(
        denial_reason=denial_reason or "standards not met", **checklist)
    resp = api_client.decide_application(application["id"], payload,
                                         REVIEWER)
    return get_success_data(resp)


def setup_submitted_application(business: dict, **app_overrides) -> dict:
    """DRAFT application submitted. Requires the business to be at least
    183 days old at the current clock (PRD §3.2)."""
    app = create_application(business, **app_overrides)
    return submit_application(app)


def setup_approved_application(business: dict, **app_overrides) -> tuple:
    """Application approved; dues invoice ISSUED. Returns (app, invoice)."""
    app = setup_submitted_application(business, **app_overrides)
    return approve_application(app)


def pay_invoice_in_full(invoice_id: str, business: dict) -> dict:
    """Post a PAYMENT ledger entry covering the exact balance; invoice moves
    to PAID and the accreditation cascade fires (PRD §3.3). Returns the
    invoice as returned by the ledger-entry response."""
    invoice = get_invoice(business["id"], invoice_id)
    resp = api_client.post_ledger_entry(
        invoice_id,
        factories.ledger_entry_payload(
            kind="PAYMENT", amount_cents=invoice["balance_cents"]),
        make_business_rep_headers(business["id"]))
    return get_success_data(resp)


def post_refund(invoice_id: str, amount_cents: int) -> dict:
    """Post a REFUND ledger entry as BureauAdmin (PRD §3.3)."""
    resp = api_client.post_ledger_entry(
        invoice_id,
        factories.ledger_entry_payload(
            kind="REFUND", amount_cents=amount_cents), ADMIN)
    return get_success_data(resp)


def setup_accredited_business(world: dict = None, **business_overrides
                              ) -> dict:
    """Full lifecycle through ACCREDITED: world (or reuse one) -> DRAFT ->
    SUBMITTED -> APPROVED_PENDING_DUES -> invoice paid in full.

    Returns {"world":..., "business": <re-read, ACCREDITED>,
             "application":..., "invoice":...}.
    """
    if world is None:
        world = setup_world(business_overrides=business_overrides or None)
    business = world["business"]
    app, invoice = setup_approved_application(business)
    pay_invoice_in_full(invoice["id"], business)
    return {
        "world": world,
        "business": get_business(business["id"]),
        "application": get_application(business["id"], app["id"]),
        "invoice": get_invoice(business["id"], invoice["id"]),
    }


# ---------------------------------------------------------------------------
# Tier 3 — complaint lifecycle (PRD §3.4)
# ---------------------------------------------------------------------------
def file_complaint(consumer: dict, business: dict, **overrides) -> dict:
    """Consumer files a complaint (status RECEIVED). Ownership: the filing
    consumer's own headers carry consumer_id == X-User-ID."""
    resp = api_client.create_complaint(
        factories.create_complaint_payload(consumer["id"], business["id"],
                                           **overrides),
        make_consumer_headers(consumer["id"]))
    return get_success_data(resp)


def forward_complaint(complaint: dict) -> dict:
    """RECEIVED -> FORWARDED; stamps forwarded_at and the 14-day
    response_deadline_at (PRD §3.4)."""
    resp = api_client.forward_complaint(complaint["id"], ADMIN)
    return get_success_data(resp)


def file_and_forward_complaint(consumer: dict, business: dict,
                               **overrides) -> dict:
    return forward_complaint(file_complaint(consumer, business, **overrides))


def business_respond(complaint: dict, business: dict,
                     body: str = None) -> dict:
    """Append BUSINESS_RESPONSE as the owning BusinessRep; FORWARDED (or
    CONSUMER_REBUTTED) -> RESPONSE_RECEIVED."""
    resp = api_client.add_complaint_response(
        complaint["id"],
        factories.complaint_response_payload(kind="BUSINESS_RESPONSE",
                                             body=body),
        make_business_rep_headers(business["id"]))
    return get_success_data(resp)


def consumer_rebuttal(complaint: dict, consumer: dict,
                      body: str = None) -> dict:
    """Append CONSUMER_REBUTTAL as the filing consumer; RESPONSE_RECEIVED ->
    CONSUMER_REBUTTED."""
    resp = api_client.add_complaint_response(
        complaint["id"],
        factories.complaint_response_payload(kind="CONSUMER_REBUTTAL",
                                             body=body),
        make_consumer_headers(consumer["id"]))
    return get_success_data(resp)


def consumer_accept(complaint: dict, consumer: dict,
                    body: str = None) -> dict:
    """Append CONSUMER_ACCEPT as the filing consumer; RESPONSE_RECEIVED ->
    RESOLVED (closed)."""
    resp = api_client.add_complaint_response(
        complaint["id"],
        factories.complaint_response_payload(kind="CONSUMER_ACCEPT",
                                             body=body),
        make_consumer_headers(consumer["id"]))
    return get_success_data(resp)


def consumer_reject(complaint: dict, consumer: dict,
                    body: str = None) -> dict:
    """Append CONSUMER_REJECT as the filing consumer; RESPONSE_RECEIVED ->
    UNRESOLVED."""
    resp = api_client.add_complaint_response(
        complaint["id"],
        factories.complaint_response_payload(kind="CONSUMER_REJECT",
                                             body=body),
        make_consumer_headers(consumer["id"]))
    return get_success_data(resp)


def reopen_complaint(complaint: dict) -> dict:
    """RESOLVED/UNANSWERED -> FORWARDED with a fresh 14-day window
    (PRD §3.4)."""
    resp = api_client.reopen_complaint(complaint["id"], ADMIN)
    return get_success_data(resp)


def setup_resolved_complaint(consumer: dict, business: dict,
                             **overrides) -> dict:
    """File -> forward -> business response -> consumer accept: RESOLVED."""
    complaint = file_and_forward_complaint(consumer, business, **overrides)
    complaint = business_respond(complaint, business)
    return consumer_accept(complaint, consumer)


def setup_unresolved_complaint(consumer: dict, business: dict,
                               **overrides) -> dict:
    """File -> forward -> business response -> consumer reject: UNRESOLVED
    with last_unresolved_at stamped at the rejection instant."""
    complaint = file_and_forward_complaint(consumer, business, **overrides)
    complaint = business_respond(complaint, business)
    return consumer_reject(complaint, consumer)


def expire_forwarded_complaint(bureau: dict, complaint: dict,
                               days_after_forward: int =
                               RESPONSE_WINDOW_DAYS + 1) -> dict:
    """Advance the clock past the complaint's response deadline and run the
    daily close: FORWARDED -> UNANSWERED (PRD §2.4 / §3.4). The clock is left
    at the advanced instant."""
    forwarded_at = complaint.get("forwarded_at")
    assert forwarded_at, "complaint must be FORWARDED (forwarded_at set)"
    set_clock(iso_plus_days(forwarded_at, days_after_forward))
    run_daily_close(bureau["id"])
    return get_complaint(complaint["id"])


def setup_unanswered_complaint(bureau: dict, consumer: dict, business: dict,
                               **overrides) -> dict:
    """File -> forward -> clock +15 days -> daily close: UNANSWERED with
    resolution_outcome AUTO_UNANSWERED. Clock left advanced."""
    complaint = file_and_forward_complaint(consumer, business, **overrides)
    return expire_forwarded_complaint(bureau, complaint)


# ---------------------------------------------------------------------------
# Tier 3 — mediation (PRD §3.5)
# ---------------------------------------------------------------------------
def offer_mediation(complaint: dict) -> dict:
    """Offer mediation on an UNRESOLVED complaint; creates an OFFERED case
    with offer_deadline_at = offered_at + 7 days and moves the complaint to
    MEDIATION_OFFERED."""
    resp = api_client.create_mediation_case(complaint["id"], ADMIN)
    return get_success_data(resp)


def answer_mediation(case: dict, party: str, response: str, business: dict,
                     consumer: dict) -> dict:
    """Record one party's answer. party BUSINESS uses the owning business's
    headers; party CONSUMER uses the filing consumer's headers (PRD §2.1)."""
    if party == "BUSINESS":
        headers = make_business_rep_headers(business["id"])
    else:
        headers = make_consumer_headers(consumer["id"])
    resp = api_client.mediation_party_response(
        case["id"],
        factories.party_response_payload(party=party, response=response),
        headers)
    return get_success_data(resp)


def accept_mediation(case: dict, business: dict, consumer: dict) -> dict:
    """Both parties accept; case becomes ACCEPTED and the complaint moves to
    IN_MEDIATION."""
    answer_mediation(case, "BUSINESS", "ACCEPTED", business, consumer)
    resp = api_client.mediation_party_response(
        case["id"],
        factories.party_response_payload(party="CONSUMER",
                                         response="ACCEPTED"),
        make_consumer_headers(consumer["id"]))
    return get_success_data(resp)


def schedule_mediation_session(case: dict, mediator_id: str = "med-1",
                               session_start_at: str = "2026-09-21T10:00:00Z",
                               session_end_at: str = "2026-09-21T11:00:00Z"
                               ) -> dict:
    """ACCEPTED -> SCHEDULED (BureauAdmin)."""
    resp = api_client.schedule_mediation(
        case["id"],
        factories.schedule_mediation_payload(
            mediator_id=mediator_id, session_start_at=session_start_at,
            session_end_at=session_end_at), ADMIN)
    return get_success_data(resp)


def conclude_mediation_case(case: dict, outcome: str = "AGREEMENT") -> dict:
    """SCHEDULED -> CONCLUDED_AGREEMENT / CONCLUDED_NO_AGREEMENT
    (BureauAdmin)."""
    resp = api_client.conclude_mediation(
        case["id"], factories.conclude_mediation_payload(outcome=outcome),
        ADMIN)
    return get_success_data(resp)


def setup_mediation_offered(consumer: dict, business: dict) -> tuple:
    """UNRESOLVED complaint + OFFERED mediation case.
    Returns (complaint [MEDIATION_OFFERED], case)."""
    complaint = setup_unresolved_complaint(consumer, business)
    case = offer_mediation(complaint)
    return get_complaint(complaint["id"]), case


def setup_mediation_accepted(consumer: dict, business: dict) -> tuple:
    """Mediation accepted by both parties; complaint IN_MEDIATION.
    Returns (complaint, case)."""
    complaint, case = setup_mediation_offered(consumer, business)
    case = accept_mediation(case, business, consumer)
    return get_complaint(complaint["id"]), case


def setup_mediation_scheduled(consumer: dict, business: dict,
                              **schedule_kwargs) -> tuple:
    """Mediation SCHEDULED. Returns (complaint, case)."""
    complaint, case = setup_mediation_accepted(consumer, business)
    case = schedule_mediation_session(case, **schedule_kwargs)
    return get_complaint(complaint["id"]), case


def setup_mediation_concluded(consumer: dict, business: dict,
                              outcome: str = "AGREEMENT",
                              **schedule_kwargs) -> tuple:
    """Mediation concluded. AGREEMENT -> complaint MEDIATION_RESOLVED;
    NO_AGREEMENT -> complaint MEDIATION_FAILED. Returns (complaint, case)."""
    complaint, case = setup_mediation_scheduled(consumer, business,
                                                **schedule_kwargs)
    case = conclude_mediation_case(case, outcome=outcome)
    return get_complaint(complaint["id"]), case


def expire_mediation_offer(bureau: dict, case: dict,
                           days_after_offer: int =
                           MEDIATION_OFFER_ACCEPT_DAYS + 1) -> dict:
    """Advance the clock past offer_deadline_at and run the daily close:
    OFFERED -> DECLINED_EXPIRED, complaint back to UNRESOLVED without
    refreshing last_unresolved_at (PRD §3.5). Clock left advanced."""
    set_clock(iso_plus_days(case["offered_at"], days_after_offer))
    run_daily_close(bureau["id"])
    data = get_success_data(api_client.list_mediation_cases(
        case["complaint_id"], ADMIN))
    for row in data:
        if row.get("id") == case["id"]:
            return row
    raise AssertionError(f"Setup failed: mediation case {case['id']} gone")


# ---------------------------------------------------------------------------
# Tier 3 — arbitration (PRD §3.5)
# ---------------------------------------------------------------------------
def escalate_to_arbitration(complaint: dict) -> dict:
    """MEDIATION_FAILED -> IN_ARBITRATION; creates a FILED arbitration case
    whose source_mediation_case_id is informational lineage."""
    resp = api_client.create_arbitration_case(complaint["id"], ADMIN)
    return get_success_data(resp)


def schedule_arbitration_hearing(
        case: dict, hearing_room_id: str = "room-A",
        hearing_start_at: str = "2026-10-05T10:00:00Z",
        hearing_end_at: str = "2026-10-05T11:00:00Z") -> dict:
    """FILED -> HEARING_SCHEDULED (BureauAdmin); the 30-minute same-room
    buffer rule applies (PRD §3.5)."""
    resp = api_client.schedule_hearing(
        case["id"],
        factories.schedule_hearing_payload(
            hearing_room_id=hearing_room_id,
            hearing_start_at=hearing_start_at,
            hearing_end_at=hearing_end_at), ADMIN)
    return get_success_data(resp)


def render_arbitration_decision(case: dict,
                                outcome: str = "ADVERSE_TO_BUSINESS"
                                ) -> dict:
    """HEARING_SCHEDULED -> DECIDED (BureauAdmin); the complaint closes
    ARBITRATED with the matching resolution outcome."""
    resp = api_client.render_arbitration_decision(
        case["id"], factories.render_decision_payload(outcome=outcome),
        ADMIN)
    return get_success_data(resp)


def setup_arbitration_filed(consumer: dict, business: dict,
                            **schedule_kwargs) -> tuple:
    """Complaint mediated to NO_AGREEMENT then escalated.
    Returns (complaint [IN_ARBITRATION], arbitration case [FILED])."""
    complaint, _case = setup_mediation_concluded(
        consumer, business, outcome="NO_AGREEMENT", **schedule_kwargs)
    arb = escalate_to_arbitration(complaint)
    return get_complaint(complaint["id"]), arb


def setup_arbitration_hearing_scheduled(consumer: dict, business: dict,
                                        **hearing_kwargs) -> tuple:
    """Returns (complaint, arbitration case [HEARING_SCHEDULED])."""
    complaint, arb = setup_arbitration_filed(consumer, business)
    arb = schedule_arbitration_hearing(arb, **hearing_kwargs)
    return get_complaint(complaint["id"]), arb


def setup_arbitration_decided(consumer: dict, business: dict,
                              outcome: str = "ADVERSE_TO_BUSINESS",
                              **hearing_kwargs) -> tuple:
    """Returns (complaint [ARBITRATED], arbitration case [DECIDED])."""
    complaint, arb = setup_arbitration_hearing_scheduled(
        consumer, business, **hearing_kwargs)
    arb = render_arbitration_decision(arb, outcome=outcome)
    return get_complaint(complaint["id"]), arb


# ---------------------------------------------------------------------------
# Tier 4 — rating snapshots, disputes (PRD §3.6 / §3.7)
# ---------------------------------------------------------------------------
def compute_snapshot(business: dict, variant: str = "PUBLISHED") -> dict:
    """Compute a RatingSnapshot as BureauAdmin. PUBLISHED stamps published_at
    and increments Business.version by 1; PROVISIONAL updates the current
    provisional mirror (PRD §3.7)."""
    resp = api_client.create_rating_snapshot(
        business["id"], factories.create_rating_snapshot_payload(
            variant=variant), ADMIN)
    return get_success_data(resp)


def file_rating_dispute(business: dict, snapshot_id: str,
                        reason: str = None,
                        disputed_complaint_id: str = None,
                        expected_business_version: int = None) -> dict:
    """File a rating dispute as the owning BusinessRep. When
    expected_business_version is omitted, the business's current version is
    read fresh (PRD §2.8 OCC field)."""
    version = (expected_business_version if expected_business_version
               is not None else fresh_business_version(business["id"]))
    kwargs = {}
    if disputed_complaint_id is not None:
        kwargs["disputed_complaint_id"] = disputed_complaint_id
    resp = api_client.create_rating_dispute(
        business["id"],
        factories.create_rating_dispute_payload(
            snapshot_id=snapshot_id, expected_business_version=version,
            reason=reason, **kwargs),
        make_business_rep_headers(business["id"]))
    return get_success_data(resp)


def decide_appeal(dispute: dict, decision: str = "UPHELD") -> dict:
    """UNDER_APPEAL_REVIEW -> UPHELD / OVERRULED (BureauAdmin)."""
    resp = api_client.decide_appeal(
        dispute["id"], factories.appeal_decision_payload(decision=decision),
        ADMIN)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 4 — advertising reviews (PRD §3.8)
# ---------------------------------------------------------------------------
def open_advertising_review(business: dict, claim_description: str = None,
                            as_reviewer: bool = False) -> dict:
    """Open an advertising-practices review (BureauAdmin or
    StandardsReviewer). Business moves CLEAR -> UNDER_AD_REVIEW."""
    kwargs = {}
    if claim_description is not None:
        kwargs["claim_description"] = claim_description
    resp = api_client.create_advertising_review(
        business["id"], factories.create_advertising_review_payload(
            **kwargs),
        REVIEWER if as_reviewer else ADMIN)
    return get_success_data(resp)


def conclude_advertising_review(review: dict, outcome: str = "CLEARED",
                                regulator_name: str = None) -> dict:
    """Conclude a review (StandardsReviewer only)."""
    if outcome == "SUBSTANTIATED_DECEPTIVE":
        payload = factories.conclude_review_deceptive_payload(
            regulator_name=regulator_name or "FTC")
    else:
        payload = factories.conclude_advertising_review_payload(
            outcome=outcome)
    resp = api_client.conclude_advertising_review(review["id"], payload,
                                                  REVIEWER)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 4 — scam reports (PRD §3.8)
# ---------------------------------------------------------------------------
def file_scam_report(consumer: dict, business: dict, **overrides) -> dict:
    """Consumer files a scam report (status RECEIVED); consumer_id must equal
    the caller's X-User-ID."""
    resp = api_client.create_scam_report(
        factories.create_scam_report_payload(consumer["id"], business["id"],
                                             **overrides),
        make_consumer_headers(consumer["id"]))
    return get_success_data(resp)


def publish_scam_report(report: dict) -> dict:
    """RECEIVED -> PUBLISHED (BureauAdmin); recomputes the business's
    published_scam_count_12m."""
    resp = api_client.publish_scam_report(report["id"], ADMIN)
    return get_success_data(resp)


def setup_published_scam_reports(consumer: dict, business: dict,
                                 count: int) -> list:
    """File and publish `count` scam reports against the business."""
    reports = []
    for _ in range(count):
        reports.append(publish_scam_report(
            file_scam_report(consumer, business)))
    return reports


# ---------------------------------------------------------------------------
# Tier 4 — accumulation / threshold targeting for rating inputs
# ---------------------------------------------------------------------------
def setup_business_with_unanswered_complaints(bureau: dict, consumer: dict,
                                              business: dict, count: int
                                              ) -> list:
    """File and forward `count` complaints, then advance the clock past the
    response window and run the daily close: all become UNANSWERED.
    Clock left advanced. Returns the re-read complaints."""
    complaints = [file_and_forward_complaint(consumer, business)
                  for _ in range(count)]
    latest_forward = max(c["forwarded_at"] for c in complaints)
    set_clock(iso_plus_days(latest_forward, RESPONSE_WINDOW_DAYS + 1))
    run_daily_close(bureau["id"])
    return [get_complaint(c["id"]) for c in complaints]


def setup_business_with_resolved_complaints(consumer: dict, business: dict,
                                            count: int) -> list:
    """`count` complaints driven to RESOLVED (answer + accept)."""
    return [setup_resolved_complaint(consumer, business)
            for _ in range(count)]


def setup_business_with_unresolved_complaints(consumer: dict, business: dict,
                                              count: int) -> list:
    """`count` complaints driven to UNRESOLVED (answer + reject)."""
    return [setup_unresolved_complaint(consumer, business)
            for _ in range(count)]


# ---------------------------------------------------------------------------
# Tier 5 — suspension-scan helpers (PRD §3.7)
# ---------------------------------------------------------------------------
def publish_and_close_day(bureau: dict, business: dict) -> tuple:
    """Publish a PUBLISHED snapshot and run the daily close so the
    suspension scan evaluates it. Returns (snapshot, business re-read)."""
    snapshot = compute_snapshot(business, variant="PUBLISHED")
    run_daily_close(bureau["id"])
    return snapshot, get_business(business["id"])
