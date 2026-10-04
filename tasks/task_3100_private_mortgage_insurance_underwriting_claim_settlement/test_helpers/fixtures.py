"""Composite setup helpers.

The server is restarted before every test, so every helper here builds its
preconditions from scratch through the API and nothing is carried over.

Identity threading: `Lender` and `Servicer` are entity-backed roles, so every
call they make is issued with `make_lender_headers(<real Lender.id>)` or
`make_servicer_headers(<real Servicer.id>)` once the owning row exists.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from . import factories
from .test_users import TEST_USERS, make_lender_headers, make_servicer_headers

from .constants import DEFAULT_CLOCK_UTC

ADMIN = TEST_USERS["admin_headers"]
UNDERWRITER = TEST_USERS["underwriter_headers"]
BORROWER = TEST_USERS["borrower_headers"]


def set_clock(current_utc=DEFAULT_CLOCK_UTC):
    """Move the server's logical clock to a known instant."""
    return get_success_data(api_client.set_clock(current_utc, ADMIN))


def create_book(policy_overrides=None, rate_card_overrides=None,
                lender_overrides=None, servicer_overrides=None,
                with_rate_card=True, with_lender=True, with_servicer=True,
                lender_delegated=True, lender_cap=200_000_000,
                servicer_tier="TIER_2",
                servicer_capability="PARTICIPATION_COMPLETE"):
    """Master policy (+ optional rate card, lender, servicer).

    Returns a dict carrying the created rows plus the role headers each of them
    needs. Rate cards are created twice (BPM and LPM) only when the caller asks
    for a specific plan through `rate_card_overrides`.
    """
    set_clock()
    mp = get_success_data(api_client.create_master_policy(
        factories.create_master_policy_payload(**(policy_overrides or {})), ADMIN))

    book = {
        "policy": mp,
        "mp_id": mp["id"],
        "lender_headers": None,
        "servicer_headers": None,
    }

    if with_rate_card:
        rc_payload = factories.create_rate_card_payload(**(rate_card_overrides or {}))
        rc_payload["master_policy_id"] = mp["id"]
        rc = get_success_data(api_client.create_rate_card(rc_payload, ADMIN))
        book["rate_card"] = rc
        book["rate_card_id"] = rc["id"]

    if with_lender:
        lender_payload = factories.create_lender_payload(
            delegated_underwriting=lender_delegated,
            policy_exposure_cap_cents=lender_cap,
            **(lender_overrides or {}))
        lender = get_success_data(api_client.create_lender(lender_payload, ADMIN))
        book["lender"] = lender
        book["lender_id"] = lender["id"]
        book["lender_headers"] = make_lender_headers(lender["id"])

    if with_servicer:
        servicer_payload = factories.create_servicer_payload(
            tier=servicer_tier,
            loss_mitigation_capability=servicer_capability,
            **(servicer_overrides or {}))
        servicer = get_success_data(api_client.create_servicer(servicer_payload, ADMIN))
        book["servicer"] = servicer
        book["servicer_id"] = servicer["id"]
        book["servicer_headers"] = make_servicer_headers(servicer["id"])

    return book


def add_rate_card(book, **overrides):
    """Create an additional rate card on an existing policy."""
    payload = factories.create_rate_card_payload(**overrides)
    payload["master_policy_id"] = book["mp_id"]
    return get_success_data(api_client.create_rate_card(payload, ADMIN))


def add_treaty(**overrides):
    return get_success_data(api_client.create_treaty(
        factories.create_treaty_payload(**overrides), ADMIN))


def add_servicer(**overrides):
    return get_success_data(api_client.create_servicer(
        factories.create_servicer_payload(**overrides), ADMIN))


def add_lender(**overrides):
    return get_success_data(api_client.create_lender(
        factories.create_lender_payload(**overrides), ADMIN))


def submit_application(book, **overrides):
    """Submit a coverage application as the owning lender."""
    payload = factories.create_application_payload(**overrides)
    payload["lender_id"] = book["lender_id"]
    payload["master_policy_id"] = book["mp_id"]
    payload.setdefault("rate_card_id", book["rate_card_id"])
    return get_success_data(api_client.create_application(payload, book["lender_headers"]))


def approve_delegated(book, application_id):
    return get_success_data(api_client.delegated_approve_application(
        application_id, book["lender_headers"]))


def underwrite_and_approve(application_id):
    get_success_data(api_client.underwrite_application(application_id, UNDERWRITER))
    return get_success_data(api_client.approve_application(application_id, UNDERWRITER))


def approve_non_delegated(application_id):
    return underwrite_and_approve(application_id)


def issue_loan(book, application_id, treaty_id=None):
    """Issue a loan from an approved application.

    PRD 3.3 describes issuance as electing a treaty "through
    `reinsurance_treaty_id`" and adds that the identifier "may name a treaty that
    is not yet in force". The only absent-reference case PRD 3.10 names is a
    reference that is absent, so `None` (an explicit JSON null) is the canonical
    no-treaty election; a fabricated identifier would be a body-supplied foreign
    key that does not resolve, which PRD 2.8 requires to be refused.
    """
    payload = {
        "application_id": application_id,
        "servicer_id": book["servicer_id"],
        "reinsurance_treaty_id": treaty_id,
    }
    return get_success_data(api_client.create_loan(payload, ADMIN))


def issue_delegated_loan(book, **application_overrides):
    """A delegated application driven to APPROVED, then issued as a loan."""
    application = submit_application(book, **application_overrides)
    approved = approve_delegated(book, application["id"])
    loan = issue_loan(book, application["id"])
    return loan, approved


def setup_loan(policy_overrides=None, rate_card_overrides=None,
               lender_cap=200_000_000, application_overrides=None,
               treaty_id=None, issue=True, **book_kwargs):
    """The canonical scenario: policy, rate card, delegated lender, servicer and
    one issued loan carrying an 8500000-cent coverage base."""
    book = create_book(policy_overrides=policy_overrides,
                       rate_card_overrides=rate_card_overrides,
                       lender_cap=lender_cap, **book_kwargs)
    application = submit_application(book, **(application_overrides or {}))
    approve_delegated(book, application["id"])
    book["application"] = application
    book["application_id"] = application["id"]
    if issue:
        loan = issue_loan(book, application["id"], treaty_id=treaty_id)
        book["loan"] = loan
        book["loan_id"] = loan["id"]
    return book


def setup_loan_with_treaty(treaty_overrides=None, **loan_kwargs):
    """Canonical loan ceded into a treaty.

    The default treaty window covers the claim event instants the scenarios use;
    passing `expiration` / `inception` overrides narrows it.
    """
    treaty = add_treaty(**(treaty_overrides or {}))
    book = setup_loan(treaty_id=treaty["id"], **loan_kwargs)
    book["treaty"] = treaty
    book["treaty_id"] = treaty["id"]
    return book


def setup_two_loans(lender_cap=200_000_000, **application_overrides):
    """Canonical book with two identically priced issued loans."""
    book = create_book(lender_cap=lender_cap)
    app_a = submit_application(book, borrower_reference="TWO-A", **application_overrides)
    app_b = submit_application(book, borrower_reference="TWO-B", **application_overrides)
    approve_delegated(book, app_a["id"])
    approve_delegated(book, app_b["id"])
    loan_a = issue_loan(book, app_a["id"])
    loan_b = issue_loan(book, app_b["id"])
    book["application_a_id"] = app_a["id"]
    book["application_b_id"] = app_b["id"]
    book["loan_a"] = loan_a
    book["loan_b"] = loan_b
    book["loan_a_id"] = loan_a["id"]
    book["loan_b_id"] = loan_b["id"]
    return book


def setup_bpm_and_lpm_loans():
    """Two loans differing only in premium plan and payer, both approved on the
    non-delegated path."""
    book = create_book(lender_delegated=False,
                       rate_card_overrides={"premium_plan": "BPM"})
    rc_lpm = add_rate_card(book, premium_plan="LPM")
    app_bpm = submit_application(book, borrower_reference="BPM-1",
                                 premium_plan="BPM", borrower_paid=True,
                                 rate_card_id=book["rate_card_id"])
    app_lpm = submit_application(book, borrower_reference="LPM-1",
                                 premium_plan="LPM", borrower_paid=False,
                                 rate_card_id=rc_lpm["id"])
    approve_non_delegated(app_bpm["id"])
    approve_non_delegated(app_lpm["id"])
    loan_bpm = issue_loan(book, app_bpm["id"])
    loan_lpm = issue_loan(book, app_lpm["id"])
    book["loan_bpm"] = loan_bpm
    book["loan_lpm"] = loan_lpm
    book["loan_bpm_id"] = loan_bpm["id"]
    book["loan_lpm_id"] = loan_lpm["id"]
    return book


def setup_loan_with_filed_claim(**loan_kwargs):
    """Canonical loan plus a FILED claim carrying the canonical items."""
    book = setup_loan(**loan_kwargs)
    claim = get_success_data(api_client.create_claim(
        dict(factories.create_claim_payload(), loan_id=book["loan_id"]),
        book["lender_headers"]))
    book["claim"] = claim
    book["claim_id"] = claim["id"]
    return book


def file_claim(book, loan_id=None, **overrides):
    """File a claim against a loan and register it on the book.

    Returns the claim row and threads it onto the book as `claim`/`claim_id`, so
    a scenario that files a claim and then disputes it satisfies the
    `target_claim_id` requirement of PRD 3.11 without re-listing the claim.
    """
    payload = factories.create_claim_payload(**overrides)
    payload["loan_id"] = loan_id or book["loan_id"]
    claim = get_success_data(api_client.create_claim(payload, book["lender_headers"]))
    book["claim"] = claim
    book["claim_id"] = claim["id"]
    return claim


def begin_claim_review(claim_id):
    return get_success_data(api_client.begin_claim_review(claim_id, UNDERWRITER))


def approve_claim(claim_id):
    return get_success_data(api_client.approve_claim(claim_id, UNDERWRITER))


def setup_loan_with_approved_claim(claim_overrides=None,
                                   in_review=False, **loan_kwargs):
    """Canonical loan plus an APPROVED claim with its four priced options."""
    book = setup_loan(**loan_kwargs)
    claim = file_claim(book, **(claim_overrides or {}))
    begin_claim_review(claim["id"])
    if not in_review:
        claim = approve_claim(claim["id"])
    book["claim"] = claim
    book["claim_id"] = claim["id"]
    return book


def setup_loan_with_claim_in_review(claim_overrides=None, **loan_kwargs):
    return setup_loan_with_approved_claim(claim_overrides=claim_overrides,
                                          in_review=True, **loan_kwargs)


def refresh_loan(book, loan_id=None):
    """Re-read a loan and return the row."""
    loan_id = loan_id or book["loan_id"]
    return get_success_data(api_client.get_loan(loan_id, UNDERWRITER))


def settle_claim(book, claim_id, option="CASH"):
    """Settle with freshly observed claim and loan versions."""
    claim = get_success_data(api_client.get_claim(claim_id, UNDERWRITER))
    loan = refresh_loan(book, claim["loan_id"])
    payload = {
        "settlement_option_kind": option,
        "expected_claim_version": claim["version"],
        "expected_loan_version": loan["version"],
    }
    return get_success_data(api_client.settle_claim(claim_id, payload, book["lender_headers"]))


def setup_settled_claim(option="CASH", claim_overrides=None, **loan_kwargs):
    """Canonical loan whose claim has already been settled."""
    book = setup_loan_with_approved_claim(claim_overrides=claim_overrides, **loan_kwargs)
    settle_claim(book, book["claim_id"], option=option)
    book["claim"] = get_success_data(api_client.get_claim(book["claim_id"], UNDERWRITER))
    return book


def setup_loan_with_treaty_and_approved_claim(treaty_overrides=None):
    """Delegated loan inside a treaty with an approved claim."""
    book = setup_loan_with_treaty(treaty_overrides=treaty_overrides)
    claim = file_claim(book)
    begin_claim_review(claim["id"])
    claim = approve_claim(claim["id"])
    book["claim"] = claim
    book["claim_id"] = claim["id"]
    return book


def file_delinquency_report(book, loan_id=None, **overrides):
    payload = factories.create_delinquency_report_payload(**overrides)
    payload["loan_id"] = loan_id or book["loan_id"]
    payload["servicer_id"] = book["servicer_id"]
    return get_success_data(api_client.create_delinquency_report(
        payload, book["servicer_headers"]))


def setup_loan_with_deficient_reports(periods=("2026-01", "2026-02"),
                                      activities=None, **loan_kwargs):
    """Loan whose Class-A reports met only outreach and intake, so the
    PARTICIPATION_COMPLETE standard was missed."""
    book = setup_loan(**loan_kwargs)
    if activities is None:
        activities = [
            {"activity_kind": "OUTREACH_SENT", "outcome": "COMPLETED",
             "activity_utc": "2026-01-10T00:00:00Z"},
        ]
    for period in periods:
        file_delinquency_report(book, as_of_period=period,
                                months_delinquent=2, loss_mitigation_activities=activities)
    return book


def setup_loan_with_cancellation(**notice_overrides):
    """Canonical loan with a borrower-request cancellation notice filed."""
    book = setup_loan()
    notice = get_success_data(api_client.create_cancellation_notice(
        book["loan_id"],
        factories.create_cancellation_notice_payload(**(notice_overrides or {})),
        book["lender_headers"]))
    book["notice"] = notice
    book["notice_id"] = notice["id"]
    return book


def setup_normalized_loan_with_confirmed_delinquency():
    """A delegated loan with a Class-A January report and a matching loan row."""
    book = setup_loan()
    file_delinquency_report(book, as_of_period="2026-01")
    book["loan"] = refresh_loan(book)
    return book


def setup_dispute(book, grounds="ORIGINATION_OMISSION", in_review=False,
                  claim_id=None):
    """Open a curtailment dispute against the scenario's claim."""
    claim_id = claim_id or book["claim_id"]
    dispute = get_success_data(api_client.create_dispute({
        "loan_id": book["loan_id"],
        "lender_id": book["lender_id"],
        "target_claim_id": claim_id,
        "grounds": grounds,
        "asserted_coverage_percent": 25,
    }, book["lender_headers"]))
    if in_review:
        dispute = get_success_data(api_client.begin_dispute_review(dispute["id"], ADMIN))
    book["dispute"] = dispute
    book["dispute_id"] = dispute["id"]
    return dispute


def setup_two_loans_with_one_exposure_cap(lender_cap=2_975_000):
    """A lender whose single canonical loan contributes exactly its cap."""
    return setup_loan(lender_cap=lender_cap)


def setup_canonical_exposure_book(lender_cap=200_000_000):
    """Two canonical loans under a policy whose contribution rate is 0.35."""
    return setup_two_loans(lender_cap=lender_cap)


# --- Tier 5: terminal states --------------------------------------------------

def amortize(book, current_upb_cents, loan_id=None):
    """Record an amortization milestone against the loan's balance."""
    loan_id = loan_id or book["loan_id"]
    return get_success_data(api_client.record_amortization_milestone(
        loan_id, {"current_upb_cents": current_upb_cents}, ADMIN))


# A balance that sits in the 80-percent window: above the 78-percent line (so the
# automatic LTV-milestone termination does not fire) but below 80 percent of the
# 40000000-cent origination value (so the milestone can be recorded at all).
AT80_UPB_CENTS = 31_500_000
# The maximum refund this balance implies: floor(31500000 * 25 / 100) = 7875000,
# so round_half_up(10000 * (8500000 - 7875000) / 8500000) = 735 cents.
AT80_MAX_REFUND_CENTS = 735


def amortize_into_at80(book, loan_id=None):
    """Amortize a canonical loan into the AT_80 window with coverage still ACTIVE
    and a non-zero maximum refund available."""
    amortize(book, AT80_UPB_CENTS, loan_id=loan_id)
    return refresh_loan(book, loan_id)


def setup_loan_at_milestone(current_upb_cents, **loan_kwargs):
    """Canonical loan whose balance has amortized to the given value."""
    book = setup_loan(**loan_kwargs)
    amortize(book, current_upb_cents)
    book["loan"] = refresh_loan(book)
    return book


def file_borrower_cancellation(book, evidence_cents, notice_utc="2026-09-01T00:00:00Z",
                               applied_utc="2026-10-15T00:00:00Z", loan_id=None):
    loan_id = loan_id or book["loan_id"]
    notice = get_success_data(api_client.create_cancellation_notice(
        loan_id,
        factories.create_cancellation_notice_payload(
            request_kind="BORROWER_REQUEST", requested_by_role="BORROWER",
            notice_utc=notice_utc, evidence_cents=evidence_cents, applied_utc=applied_utc),
        book["lender_headers"]))
    return notice


def file_servicer_cancellation(book, notice_utc="2026-09-01T00:00:00Z",
                               applied_utc="2026-09-01T00:00:00Z",
                               evidence_cents=0, loan_id=None):
    loan_id = loan_id or book["loan_id"]
    return get_success_data(api_client.create_cancellation_notice(
        loan_id,
        factories.create_cancellation_notice_payload(
            request_kind="SERVICER_LOSS_MITIGATION_FAILURE",
            requested_by_role="SERVICER", notice_utc=notice_utc,
            evidence_cents=evidence_cents, applied_utc=applied_utc),
        book["servicer_headers"]))


def setup_cancelled_loan(notice_overrides=None):
    """Canonical loan, amortized into the AT_80 window and then cancelled on a
    borrower request, driven all the way to CANCELLED."""
    book = setup_loan()
    amortize_into_at80(book)
    notice = get_success_data(api_client.create_cancellation_notice(
        book["loan_id"],
        factories.create_cancellation_notice_payload(
            evidence_cents=AT80_MAX_REFUND_CENTS, **(notice_overrides or {})),
        book["lender_headers"]))
    book["notice"] = notice
    book["notice_id"] = notice["id"]
    set_clock("2026-11-01T00:00:00Z")
    book["loan"] = refresh_loan(book)
    return book


def setup_cancelled_via_servicer(periods=("2026-01", "2026-02", "2026-03")):
    """Canonical loan whose Class-A reports all missed the participation
    standard, so the streak reaches three and the coverage auto-terminates."""
    book = setup_loan()
    for period in periods:
        file_delinquency_report(
            book, as_of_period=period, months_delinquent=2,
            loss_mitigation_activities=[
                {"activity_kind": "OUTREACH_SENT", "outcome": "COMPLETED",
                 "activity_utc": f"{period}-10T00:00:00Z"},
            ])
    book["loan"] = refresh_loan(book)
    return book


def compensate_clock(book, current_utc):
    """Advance the logical clock; system-driven transitions may fire."""
    set_clock(current_utc)
    book["loan"] = refresh_loan(book)
    return book["loan"]


def reconcile_exposure(book, lender_id=None, loan_id=None):
    """Reconcile a lender's exposure using the loan's current version."""
    lender_id = lender_id or book["lender_id"]
    loan_id = loan_id or book["loan_id"]
    loan = refresh_loan(book, loan_id)
    return api_client.reconcile_lender_exposure(
        lender_id, {"expected_loan_version": loan["version"], "loan_id": loan_id},
        UNDERWRITER)


def issue_treaty_loan(treaty_overrides, loan_kwargs=None):
    """One delegated loan ceded into a treaty with the given window."""
    return setup_loan_with_treaty(treaty_overrides=treaty_overrides,
                                  **(loan_kwargs or {}))


def setup_approved_claim_for_loan(book, claim_overrides=None):
    claim = file_claim(book, **(claim_overrides or {}))
    begin_claim_review(claim["id"])
    claim = approve_claim(claim["id"])
    book["claim"] = claim
    book["claim_id"] = claim["id"]
    return claim


def setup_guaranteed_relief_loan(**loan_kwargs):
    """A loan with two consecutive free Class-A reporting cycles, so its
    rescission-relief status is GUARANTEED.

    The two defining reports are more than a year apart, so neither cycle
    contains the other; the logical clock is moved past both reporting months
    first so the second report is not filed for a future month.
    """
    set_clock("2027-04-01T00:00:00Z")
    book = setup_loan(issue=False, **loan_kwargs)
    book["rate_card"] = get_success_data(api_client.get_rate_card(
        book["rate_card_id"], ADMIN))
    loan = issue_loan(book, book["application_id"])
    book["loan"] = loan
    book["loan_id"] = loan["id"]
    set_clock("2027-04-01T00:00:00Z")

    file_delinquency_report(book, as_of_period="2026-02", months_delinquent=1,
                            loss_mitigation_activities=_complete_activities("2026-02"))
    file_delinquency_report(book, as_of_period="2027-03", months_delinquent=1,
                            loss_mitigation_activities=_complete_activities("2027-03"))
    book["loan"] = refresh_loan(book)
    return book


def _complete_activities(prefix):
    """The four graded activities PARTICIPATION_COMPLETE requires, all completed
    inside the reporting month that defines the cycle."""
    return [
        {"activity_kind": "OUTREACH_SENT", "outcome": "COMPLETED",
         "activity_utc": f"{prefix}-10T00:00:00Z"},
        {"activity_kind": "INTAKE_COMPLETE", "outcome": "COMPLETED",
         "activity_utc": f"{prefix}-15T00:00:00Z"},
        {"activity_kind": "EVALUATION_COMPLETE", "outcome": "COMPLETED",
         "activity_utc": f"{prefix}-20T00:00:00Z"},
        {"activity_kind": "PROGRAM_ACCEPTED", "outcome": "COMPLETED",
         "activity_utc": f"{prefix}-25T00:00:00Z"},
    ]