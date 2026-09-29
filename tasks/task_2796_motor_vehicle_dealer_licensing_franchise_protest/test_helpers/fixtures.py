"""Composite setup helpers.

Every helper builds its state from scratch through the board's own endpoints,
using the lenient setup validator so a broken precondition reports itself as a
setup failure. Ownership-gated calls always carry the acting row's own `id` in
`X-User-ID`.
"""
from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client as api
from .test_users import (
    BOARD_ADMIN,
    HEARING_CLERK,
    LICENSING_ANALYST,
    make_dealer_headers,
    make_investigator_headers,
    make_manufacturer_headers,
)

# ── The logical clock ────────────────────────────────────────────────


def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock and run the operational sweep."""
    return get_success_data(api.advance_clock(to_iso8601, BOARD_ADMIN))


def set_clock_date(date_str: str) -> dict:
    """Advance the clock to midnight UTC on the given calendar date."""
    return set_clock(f"{date_str}T00:00:00Z")


# ── Reference data ───────────────────────────────────────────────────


def create_manufacturer(**overrides) -> dict:
    """Register a franchisor."""
    return get_success_data(
        api.create_manufacturer(f.manufacturer_payload(**overrides), BOARD_ADMIN))


def create_hearing_room(**overrides) -> dict:
    """Create a board hearing room."""
    return get_success_data(
        api.create_hearing_room(f.hearing_room_payload(**overrides), BOARD_ADMIN))


def create_dealer(**overrides) -> dict:
    """Open a prospective dealership record."""
    return get_success_data(api.create_dealer(f.dealer_payload(**overrides), BOARD_ADMIN))


def create_used_only_dealer(**overrides) -> dict:
    """Open a prospective used-only dealership record."""
    return get_success_data(
        api.create_dealer(f.used_only_dealer_payload(**overrides), BOARD_ADMIN))


# ── Dealer licensure ─────────────────────────────────────────────────


def open_application(dealer_id, **overrides) -> dict:
    """Open a licence application in draft as the dealership's own act."""
    return get_success_data(api.create_license_application(
        f.license_application_payload(dealer_id, **overrides),
        make_dealer_headers(dealer_id),
    ))


def submit_application(application_id, dealer_id) -> dict:
    """Submit a draft application, running the sufficiency scan and the quote."""
    return get_success_data(
        api.submit_license_application(application_id, make_dealer_headers(dealer_id)))


def return_application_as_deficient(application_id, **overrides) -> dict:
    """Return a submitted application for correction as the licensing analyst."""
    return get_success_data(api.issue_deficiency_notice(
        application_id, f.deficiency_notice_payload(**overrides), LICENSING_ANALYST))


def resubmit_application(application_id, dealer_id, **payload) -> dict:
    """Correct a deficient application and resubmit it."""
    return get_success_data(api.resubmit_license_application(
        application_id, payload, make_dealer_headers(dealer_id)))


def decide_application(application_id, outcome="APPROVED", **overrides) -> dict:
    """Decide a submitted application as the board."""
    return get_success_data(api.decide_license_application(
        application_id, f.application_decision_payload(outcome, **overrides), BOARD_ADMIN))


def license_dealer(dealer_id, **application_overrides) -> dict:
    """Walk a dealership all the way to LICENSED: open a deficiency-free
    application, submit it and approve it. Returns the approved application."""
    application = open_application(dealer_id, **application_overrides)
    submit_application(application["id"], dealer_id)
    return decide_application(application["id"], "APPROVED")


def setup_licensed_dealer(clock="2026-09-01T00:00:00Z", dealer_overrides=None,
                          application_overrides=None, manufacturer_overrides=None) -> dict:
    """Clock, franchisor, dealership, approved INITIAL application.

    Returns {"manufacturer", "dealer", "application", "dealer_headers",
    "manufacturer_headers"} with the dealership read back after approval.
    """
    if clock:
        set_clock(clock)
    manufacturer = create_manufacturer(**(manufacturer_overrides or {}))
    dealer = create_dealer(**(dealer_overrides or {}))
    application = license_dealer(dealer["id"], **(application_overrides or {}))
    dealer = get_success_data(api.get_dealer(dealer["id"], BOARD_ADMIN))
    return {
        "manufacturer": manufacturer,
        "dealer": dealer,
        "application": application,
        "dealer_headers": make_dealer_headers(dealer["id"]),
        "manufacturer_headers": make_manufacturer_headers(manufacturer["id"]),
    }


def setup_licensed_used_only_dealer(clock="2026-09-01T00:00:00Z",
                                    dealer_overrides=None,
                                    application_overrides=None) -> dict:
    """A licensed used-only dealership. Its franchise dimension stays NONE."""
    if clock:
        set_clock(clock)
    dealer = create_used_only_dealer(**(dealer_overrides or {}))
    payload = f.used_only_application_payload(dealer["id"], **(application_overrides or {}))
    application = get_success_data(api.create_license_application(
        payload, make_dealer_headers(dealer["id"])))
    submit_application(application["id"], dealer["id"])
    application = decide_application(application["id"], "APPROVED")
    dealer = get_success_data(api.get_dealer(dealer["id"], BOARD_ADMIN))
    return {
        "dealer": dealer,
        "application": application,
        "dealer_headers": make_dealer_headers(dealer["id"]),
    }


# ── Salesperson licensure ────────────────────────────────────────────


def sponsor_salesperson(dealer_id, **overrides) -> dict:
    """Put a salesperson forward as the sponsoring dealership's own act."""
    return get_success_data(api.create_salesperson(
        f.salesperson_payload(dealer_id, **overrides), make_dealer_headers(dealer_id)))


def decide_salesperson(salesperson_id, outcome="APPROVED", **overrides) -> dict:
    """Decide a pending salesperson licence as the licensing analyst."""
    return get_success_data(api.decide_salesperson_license(
        salesperson_id, f.salesperson_decision_payload(outcome, **overrides),
        LICENSING_ANALYST,
    ))


def license_salesperson(dealer_id, **overrides) -> dict:
    """Sponsor a salesperson and approve the licence. Returns the licensed row."""
    salesperson = sponsor_salesperson(dealer_id, **overrides)
    return decide_salesperson(salesperson["id"], "APPROVED")


def request_salesperson_renewal(salesperson_id, dealer_id) -> dict:
    """Request a renewal as the sponsoring dealership."""
    return get_success_data(
        api.renew_salesperson(salesperson_id, make_dealer_headers(dealer_id)))


# ── Franchise filings ────────────────────────────────────────────────


def open_termination_filing(manufacturer_id, affected_dealer_id,
                            proposed_effective_on="2026-12-01", **overrides) -> dict:
    """Open a TERMINATION filing in draft as the franchisor."""
    return get_success_data(api.create_franchise_filing(
        f.termination_filing_payload(manufacturer_id, affected_dealer_id,
                                     proposed_effective_on, **overrides),
        make_manufacturer_headers(manufacturer_id),
    ))


def open_relocation_filing(manufacturer_id, affected_dealer_id,
                           proposed_effective_on="2026-12-01",
                           site_x_km=10, site_y_km=0, **overrides) -> dict:
    """Open a RELOCATION filing in draft as the franchisor."""
    return get_success_data(api.create_franchise_filing(
        f.relocation_filing_payload(manufacturer_id, affected_dealer_id,
                                    proposed_effective_on, site_x_km, site_y_km,
                                    **overrides),
        make_manufacturer_headers(manufacturer_id),
    ))


def open_additional_point_filing(manufacturer_id, proposed_effective_on="2026-11-01",
                                 site_x_km=9, site_y_km=12, **overrides) -> dict:
    """Open an ADDITIONAL_POINT filing in draft as the franchisor."""
    return get_success_data(api.create_franchise_filing(
        f.additional_point_filing_payload(manufacturer_id, proposed_effective_on,
                                          site_x_km, site_y_km, **overrides),
        make_manufacturer_headers(manufacturer_id),
    ))


def serve_notice(filing_id, manufacturer_id) -> dict:
    """Serve statutory notice, opening the 30-day protest window."""
    return get_success_data(
        api.serve_filing_notice(filing_id, make_manufacturer_headers(manufacturer_id)))


def amend_filing(filing_id, manufacturer_id, proposed_effective_on, **overrides) -> dict:
    """Amend a served notice, restarting the protest window."""
    return get_success_data(api.amend_franchise_filing(
        filing_id, f.amendment_payload(proposed_effective_on, **overrides),
        make_manufacturer_headers(manufacturer_id),
    ))


def finalize_filing(filing_id) -> dict:
    """Let a filing take effect as the board."""
    return get_success_data(api.finalize_franchise_filing(filing_id, BOARD_ADMIN))


def setup_served_termination_notice(clock="2026-09-01T00:00:00Z",
                                    proposed_effective_on="2026-12-01",
                                    dealer_overrides=None,
                                    manufacturer_overrides=None,
                                    application_overrides=None,
                                    filing_overrides=None) -> dict:
    """A licensed, FRANCHISED dealership under a served TERMINATION notice.

    Returns the licensed-dealer context plus {"filing"} as it stands after
    service, so the caller can read the filing's `version` comparand.
    """
    ctx = setup_licensed_dealer(
        clock=clock,
        dealer_overrides=dealer_overrides,
        application_overrides=application_overrides,
        manufacturer_overrides=manufacturer_overrides,
    )
    filing = open_termination_filing(
        ctx["manufacturer"]["id"], ctx["dealer"]["id"], proposed_effective_on,
        **(filing_overrides or {}),
    )
    ctx["filing"] = serve_notice(filing["id"], ctx["manufacturer"]["id"])
    return ctx


def file_protest(filing_id, dealer_id, expected_version,
                 grounds_code="NO_GOOD_CAUSE_FOR_TERMINATION", **overrides) -> dict:
    """Lodge a protest against a served filing as the protestant dealership."""
    return get_success_data(api.create_protest(
        f.protest_payload(filing_id, dealer_id, expected_version, grounds_code, **overrides),
        make_dealer_headers(dealer_id),
    ))


def setup_filed_protest(protest_clock="2026-09-15T00:00:00Z", **kwargs) -> dict:
    """A served TERMINATION notice with the incumbent's protest on file.

    Returns the served-notice context plus {"protest"}.
    """
    ctx = setup_served_termination_notice(**kwargs)
    if protest_clock:
        set_clock(protest_clock)
    ctx["protest"] = file_protest(
        ctx["filing"]["id"], ctx["dealer"]["id"], ctx["filing"]["version"])
    return ctx


def setup_served_additional_point_notice(clock="2026-09-01T00:00:00Z",
                                        notice_clock="2026-09-10T00:00:00Z",
                                        proposed_effective_on="2026-11-15",
                                        site_x_km=9, site_y_km=12,
                                        dealer_overrides=None,
                                        manufacturer_overrides=None,
                                        application_overrides=None) -> dict:
    """A licensed incumbent at the origin under a served ADDITIONAL_POINT notice.

    The default destination sits 15.00 km from the incumbent, inside the
    relevant market, so the incumbent has standing to protest.
    """
    ctx = setup_licensed_dealer(
        clock=clock,
        dealer_overrides=dealer_overrides,
        application_overrides=application_overrides,
        manufacturer_overrides=manufacturer_overrides,
    )
    filing = open_additional_point_filing(
        ctx["manufacturer"]["id"], proposed_effective_on, site_x_km, site_y_km)
    if notice_clock:
        set_clock(notice_clock)
    ctx["filing"] = serve_notice(filing["id"], ctx["manufacturer"]["id"])
    return ctx


def setup_filed_additional_point_protest(protest_clock="2026-09-15T00:00:00Z",
                                         grounds_code="MARKET_ENCROACHMENT",
                                         **kwargs) -> dict:
    """A served ADDITIONAL_POINT notice with the incumbent's protest on file."""
    ctx = setup_served_additional_point_notice(**kwargs)
    if protest_clock:
        set_clock(protest_clock)
    ctx["protest"] = file_protest(
        ctx["filing"]["id"], ctx["dealer"]["id"], ctx["filing"]["version"],
        grounds_code=grounds_code)
    return ctx


def tender_comparable_study(protest_id, dealer_id, **overrides) -> dict:
    """Tender a COMPARABLE_MARKET study as the protestant dealership."""
    return get_success_data(api.create_market_study(
        protest_id, f.comparable_study_payload("PROTESTANT", **overrides),
        make_dealer_headers(dealer_id),
    ))


def schedule_hearing(protest_id, room_id, room_version,
                     hearing_start_at="2026-11-02T10:00:00Z",
                     hearing_end_at="2026-11-02T13:00:00Z",
                     hearing_session_count=1) -> dict:
    """Docket a protest hearing into a room as the hearing clerk."""
    return get_success_data(api.schedule_protest_hearing(
        protest_id,
        f.schedule_payload(room_id, hearing_start_at, hearing_end_at,
                           room_version, hearing_session_count),
        HEARING_CLERK,
    ))


def setup_scheduled_protest(room_overrides=None,
                            hearing_start_at="2026-11-02T10:00:00Z",
                            hearing_end_at="2026-11-02T13:00:00Z",
                            hearing_session_count=1, **kwargs) -> dict:
    """A filed protest docketed into a freshly created hearing room.

    Returns the filed-protest context plus {"room", "protest"} where the
    protest is the SCHEDULED row.
    """
    ctx = setup_filed_protest(**kwargs)
    ctx["room"] = create_hearing_room(**(room_overrides or {}))
    ctx["protest"] = schedule_hearing(
        ctx["protest"]["id"], ctx["room"]["id"], ctx["room"]["version"],
        hearing_start_at, hearing_end_at, hearing_session_count,
    )
    return ctx


def tender_protestant_study(protest_id, dealer_id, **overrides) -> dict:
    """Tender a market study as the protest's protestant dealership."""
    return get_success_data(api.create_market_study(
        protest_id, f.statewide_study_payload("PROTESTANT", **overrides),
        make_dealer_headers(dealer_id),
    ))


def tender_manufacturer_study(protest_id, manufacturer_id, **overrides) -> dict:
    """Tender a market study as the protested filing's franchisor."""
    return get_success_data(api.create_market_study(
        protest_id, f.statewide_study_payload("MANUFACTURER", **overrides),
        make_manufacturer_headers(manufacturer_id),
    ))


def tender_protestant_exhibit(protest_id, dealer_id, **overrides) -> dict:
    """Tender an exhibit as the protestant dealership."""
    return get_success_data(api.create_evidence_submission(
        protest_id, f.exhibit_payload("PROTESTANT", **overrides),
        make_dealer_headers(dealer_id),
    ))


def tender_manufacturer_exhibit(protest_id, manufacturer_id, **overrides) -> dict:
    """Tender an exhibit as the franchisor."""
    return get_success_data(api.create_evidence_submission(
        protest_id, f.exhibit_payload("MANUFACTURER", **overrides),
        make_manufacturer_headers(manufacturer_id),
    ))


def convene_hearing(protest_id) -> dict:
    """Convene the docketed hearing as the hearing clerk."""
    return get_success_data(api.convene_protest_hearing(protest_id, HEARING_CLERK))


def decide_protest(protest_id, outcome="SUSTAINED", **overrides) -> dict:
    """Decide a heard protest as the board."""
    return get_success_data(api.decide_protest(
        protest_id, f.protest_decision_payload(outcome, **overrides), BOARD_ADMIN))


def setup_heard_protest(protestant_study_overrides=None,
                        manufacturer_study_overrides=None,
                        exhibit_pages=None,
                        hearing_start_at="2026-11-02T10:00:00Z",
                        **kwargs) -> dict:
    """A protest docketed, evidenced and convened, standing at HEARD.

    `exhibit_pages` is a list of page counts tendered by the protestant before
    the evidence cut-off. `manufacturer_study_overrides` adds a franchisor
    study so the access component stops being neutral.
    """
    ctx = setup_scheduled_protest(hearing_start_at=hearing_start_at, **kwargs)
    protest_id = ctx["protest"]["id"]
    ctx["protestant_study"] = tender_protestant_study(
        protest_id, ctx["dealer"]["id"], **(protestant_study_overrides or {}))
    if manufacturer_study_overrides is not None:
        ctx["manufacturer_study"] = tender_manufacturer_study(
            protest_id, ctx["manufacturer"]["id"], **manufacturer_study_overrides)
    for index, pages in enumerate(exhibit_pages or []):
        tender_protestant_exhibit(
            protest_id, ctx["dealer"]["id"],
            exhibit_label=f"EX-{index + 1}", page_count=pages,
        )
    set_clock(hearing_start_at)
    ctx["protest"] = convene_hearing(protest_id)
    return ctx


# ── Consumer complaints and the restitution ledger ───────────────────


def intake_complaint(dealer_id, investigator_id="investigator-op-1", **overrides) -> dict:
    """Intake a consumer complaint as a board investigator."""
    return get_success_data(api.create_consumer_complaint(
        f.complaint_payload(dealer_id, **overrides),
        make_investigator_headers(investigator_id),
    ))


def open_investigation(complaint_id, investigator_id="investigator-op-1", **overrides) -> dict:
    """Open the investigation, stamping investigator_user_id with the caller."""
    return get_success_data(api.open_complaint_investigation(
        complaint_id, f.investigation_payload(**overrides),
        make_investigator_headers(investigator_id),
    ))


def resolve_complaint(complaint_id, substantiated=True, sanction_type="CIVIL_PENALTY",
                      **overrides) -> dict:
    """Resolve the complaint as the board (never as its own investigator)."""
    return get_success_data(api.resolve_consumer_complaint(
        complaint_id, f.resolution_payload(substantiated, sanction_type, **overrides),
        BOARD_ADMIN,
    ))


def sanction_complaint(dealer_id, sanction_type="CIVIL_PENALTY",
                       alleged_loss_cents=100000,
                       allegation_code="ODOMETER_MISREPRESENTATION",
                       salesperson_id=None,
                       investigator_id="investigator-op-1",
                       findings_code="MISREPRESENTATION_CONFIRMED") -> dict:
    """Intake, investigate and substantiate one complaint against a dealership.

    Returns the SANCTIONED complaint carrying its points and its ledger.
    """
    overrides = {"allegation_code": allegation_code,
                 "alleged_loss_cents": alleged_loss_cents}
    if salesperson_id is not None:
        overrides["salesperson_id"] = salesperson_id
    complaint = intake_complaint(dealer_id, investigator_id, **overrides)
    open_investigation(complaint["id"], investigator_id, findings_code=findings_code)
    return resolve_complaint(complaint["id"], True, sanction_type)


def sanction_complaints(dealer_id, sanction_types, alleged_loss_cents=100000,
                        allegation_code="ODOMETER_MISREPRESENTATION",
                        salesperson_id=None) -> list:
    """Accumulate a dealership's rolling point total by sanctioning one
    complaint per entry in `sanction_types`, in order."""
    return [
        sanction_complaint(dealer_id, sanction_type, alleged_loss_cents,
                           allegation_code, salesperson_id)
        for sanction_type in sanction_types
    ]


def pay_restitution(complaint_id, dealer_id, amount_cents) -> dict:
    """Pay restitution as the dealership complained of."""
    return get_success_data(api.pay_restitution(
        complaint_id, f.restitution_payment_payload(amount_cents),
        make_dealer_headers(dealer_id),
    ))


# ── Warranty reimbursement rate disputes ─────────────────────────────


def file_rate_dispute(dealer_id, manufacturer_id, repair_order_lines=None,
                      **overrides) -> dict:
    """File a rate dispute as the dealership."""
    return get_success_data(api.create_warranty_rate_dispute(
        f.rate_dispute_payload(dealer_id, manufacturer_id, repair_order_lines, **overrides),
        make_dealer_headers(dealer_id),
    ))


def answer_rate_dispute(dispute_id, manufacturer_id,
                        manufacturer_response_type="REBUT", **overrides) -> dict:
    """Answer a rate dispute as the franchisor."""
    return get_success_data(api.respond_to_warranty_rate_dispute(
        dispute_id, f.dispute_response_payload(manufacturer_response_type, **overrides),
        make_manufacturer_headers(manufacturer_id),
    ))


def decide_rate_dispute(dispute_id, outcome="APPROVED", **overrides) -> dict:
    """Set the reimbursement rate or deny the dispute as the board."""
    return get_success_data(api.decide_warranty_rate_dispute(
        dispute_id, f.dispute_decision_payload(outcome, **overrides), BOARD_ADMIN))


# ── Read-back helpers ────────────────────────────────────────────────


def read_dealer(dealer_id) -> dict:
    return get_success_data(api.get_dealer(dealer_id, BOARD_ADMIN))


def read_manufacturer(manufacturer_id) -> dict:
    return get_success_data(api.get_manufacturer(manufacturer_id, BOARD_ADMIN))


def read_application(application_id) -> dict:
    return get_success_data(api.get_license_application(application_id, BOARD_ADMIN))


def read_salesperson(salesperson_id) -> dict:
    return get_success_data(api.get_salesperson(salesperson_id, BOARD_ADMIN))


def read_filing(filing_id) -> dict:
    return get_success_data(api.get_franchise_filing(filing_id, BOARD_ADMIN))


def read_protest(protest_id) -> dict:
    return get_success_data(api.get_protest(protest_id, BOARD_ADMIN))


def read_room(room_id) -> dict:
    return get_success_data(api.get_hearing_room(room_id, BOARD_ADMIN))


def read_dispute(dispute_id) -> dict:
    return get_success_data(api.get_warranty_rate_dispute(dispute_id, BOARD_ADMIN))


def read_complaint(complaint_id) -> dict:
    return get_success_data(api.get_consumer_complaint(complaint_id, BOARD_ADMIN))


def read_good_cause_analysis(protest_id) -> dict:
    return get_success_data(api.get_good_cause_analysis(protest_id, BOARD_ADMIN))
