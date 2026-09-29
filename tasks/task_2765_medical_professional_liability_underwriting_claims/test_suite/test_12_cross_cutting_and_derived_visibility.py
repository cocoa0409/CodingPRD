"""Cross-cutting behaviour of the claim and premium model: the claim version
guarding two competing writes, the pinned checkpoint sweep of one clock advance,
the reconciliation of the insured and panel-firm counters, and the immediate
visibility of derived figures in the response that caused them
(PRD 2.6, 2.9, 2.10).
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions, factories
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.fixtures import (
    advance_clock,
    assign_counsel,
    build_claim,
    build_counsel_firm,
    build_credentialed_insured,
    build_policy,
    build_specialty_class,
    build_term,
    complete_enrolment,
    decide_coverage,
    dispose_claim,
    enrol_insured,
    issue_term,
    pay_expense,
    post_reserve,
)
from test_helpers.test_users import TEST_USERS

UW = TEST_USERS["underwriting_officer_headers"]
ADJ = TEST_USERS["claims_adjuster_headers"]
APPROVER = TEST_USERS["claims_committee_approver_headers"]

LIVE_EFFECTIVE = "2026-08-01"
LIVE_EXPIRATION = "2027-08-01"


def _live_book(api):
    """A rated class, a credentialed insured and one live claims-made term."""
    advance_clock(api, CLOCK_EPOCH)
    specialty = build_specialty_class(api)
    insured = build_credentialed_insured(api, specialty["id"])
    policy = build_policy(api, insured["id"])
    term = build_term(
        api, policy["id"],
        effective_date=LIVE_EFFECTIVE, expiration_date=LIVE_EXPIRATION,
    )
    return {
        "specialty": specialty,
        "insured": insured,
        "policy": policy,
        "term": issue_term(api, term["id"]),
    }


class TestNegotiationOptimisticConcurrency:
    def test_the_reserve_posting_invalidates_the_claim_version_the_negotiation_carries(
        self, api
    ):
        """A reserve posting and a settlement negotiation are guarded by the same claim version, so the offer prepared against the pre-posting version is refused and the identical payload succeeds after one re-read.

        PRD: "Opening a settlement negotiation on a claim likewise requires `expected_claim_version` matching the claim's current `version`, and a mismatch is rejected with `ERR_STALE_CLAIM_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/negotiation_create_occ_rejects_the_claim_version_a_reserve_posting_invalidated
        """
        book = _live_book(api)
        claim = build_claim(
            api, book["insured"]["id"],
            incident_date="2026-08-05", report_date="2026-09-01",
            demand_amount=800000.00,
        )
        decide_coverage(api, claim["id"], "COVERED")

        version_before_posting = validate_success(api.get_claim(claim["id"], ADJ))["version"]
        posting = post_reserve(
            api, claim["id"],
            method="CASE_BASIS",
            effective_at="2026-09-02T00:00:00Z",
            claim_version=version_before_posting,
            indemnity_amount=300000.00,
            expense_amount=90000.00,
            rationale="initial case reserve",
        )
        assert posting["method"] == "CASE_BASIS"

        stale_offer = factories.negotiation_payload(
            proposed_amount=250000.00,
            authority_requested=250000.00,
            expected_claim_version=version_before_posting,
        )
        validate_error(
            api.create_settlement_negotiation(claim["id"], stale_offer, ADJ),
            ApiErrorId.ERR_STALE_CLAIM_VERSION.value,
            412,
        )

        version_after_posting = validate_success(api.get_claim(claim["id"], ADJ))["version"]
        assert version_after_posting == version_before_posting + 1, (
            "the reserve posting bumps the claim once and the refusal bumps it not at all"
        )

        negotiation = validate_success(
            api.create_settlement_negotiation(
                claim["id"],
                factories.negotiation_payload(
                    proposed_amount=250000.00,
                    authority_requested=250000.00,
                    expected_claim_version=version_after_posting,
                ),
                ADJ,
            ),
            201,
        )
        assert negotiation["status"] == "AUTHORITY_REQUESTED"
        assertions.assert_money(negotiation["proposed_amount"], 250000.00, "proposed_amount")
        assert negotiation["round_index"] == 1

        after = validate_success(api.get_claim(claim["id"], ADJ))
        assert after["version"] == version_after_posting + 1, (
            "the accepted negotiation bumps the claim version again"
        )
        assertions.assert_money(after["indemnity_reserve"], 300000.00, "indemnity_reserve")

        _rows, meta = validate_paginated(
            api.list_settlement_negotiations(ADJ, {"claim_id": claim["id"]})
        )
        assert meta["total_count"] == 1, (
            "the refused attempt must have created no negotiation"
        )


class TestOneClockAdvanceRunsTheCheckpointStepsInPinnedOrder:
    def test_a_term_whose_whole_period_is_skipped_is_promoted_and_then_expired(self, api):
        """A single jump past a renewal term's whole period promotes it and then expires it, lapsing the credentialing and closing the run-off claim in the same sweep.

        PRD: "Because promotion runs before expiry inside the same call, a term whose whole period lies in the skipped interval is promoted and then expired by a single clock advance."

        Design: Corner/cross_cutting_complexity_layers/one_clock_advance_promotes_and_then_expires_the_same_term_in_pinned_order
        """
        book = _live_book(api)
        policy_id = book["policy"]["id"]
        term_a = book["term"]
        assert term_a["status"] == "IN_FORCE"

        renewal = build_term(
            api, policy_id,
            effective_date="2027-08-01", expiration_date="2028-08-01",
            predecessor_term_id=term_a["id"],
        )
        renewal = issue_term(api, renewal["id"])
        assert renewal["status"] == "ISSUED", (
            "a term effective in the future waits for the sweep to promote it"
        )

        claim = build_claim(
            api, book["insured"]["id"],
            incident_date="2026-08-05", report_date="2026-08-20",
            demand_amount=400000.00,
        )
        decide_coverage(api, claim["id"], "COVERED")
        resolved = dispose_claim(api, claim["id"], "DISMISSED", "2026-09-01")
        assert resolved["claim_status"] == "RESOLVED"

        swept = validate_success(api.set_clock("2028-09-01T00:00:00Z", UW))
        assertions.assert_same_instant(
            swept["current_utc"], "2028-09-01T00:00:00Z", "current_utc"
        )
        assert renewal["id"] in swept["promoted_term_ids"]
        assert term_a["id"] in swept["expired_term_ids"]
        assert renewal["id"] in swept["expired_term_ids"], (
            "the skipped renewal is promoted at step two and expired at step three"
        )
        assert book["insured"]["id"] in swept["lapsed_insured_ids"]
        assert claim["id"] in swept["closed_claim_ids"]

        assert validate_success(api.get_policy_term(term_a["id"], UW))["status"] == "EXPIRED"
        assert validate_success(api.get_policy_term(renewal["id"], UW))["status"] == "EXPIRED"

        policy_after = validate_success(api.get_policy(policy_id, UW))
        assert policy_after["status"] == "EXPIRED"
        assert policy_after["current_term_id"] is None

        insured_after = validate_success(api.get_insured(book["insured"]["id"], UW))
        assert insured_after["credentialing_status"] == "LAPSED"
        assert insured_after["status"] == "SUSPENDED"
        assert insured_after["open_claim_count"] == 0

        claim_after = validate_success(api.get_claim(claim["id"], ADJ))
        assert claim_after["claim_status"] == "CLOSED"
        assert claim_after["closed_on"] == "2028-09-01"


def _panel_book_with_two_open_claims(api):
    """A live term, one admitted COOK_IL panel firm and two intaken claims."""
    book = _live_book(api)
    firm = build_counsel_firm(
        api,
        firm_name="Halloran Defense LLP",
        admitted_venue_codes=["COOK_IL"],
        allegation_specialties=["OBSTETRIC_INJURY", "SURGICAL_ERROR"],
        blended_hourly_rate=500.00,
        quality_score=95,
        max_concurrent_assignments=5,
        conflict_insured_ids=[],
    )
    obstetric_claim = build_claim(
        api, book["insured"]["id"],
        incident_date="2026-08-05", report_date="2026-09-01",
        allegation_category="OBSTETRIC_INJURY", demand_amount=400000.00,
    )
    surgical_claim = build_claim(
        api, book["insured"]["id"],
        incident_date="2026-08-06", report_date="2026-09-02",
        allegation_category="SURGICAL_ERROR", demand_amount=300000.00,
    )
    book["firm"] = firm
    book["obstetric_claim"] = obstetric_claim
    book["surgical_claim"] = surgical_claim
    return book


class TestDerivedCounterReconciliation:
    def test_two_intakes_raise_the_open_count_and_a_dismissal_drops_it_back(self, api):
        """Two intakes carry the insured's open claim count to two, and dismissing one drops it to one while leaving the closed-paid count at nought.

        PRD: "Finally the insured's `open_claim_count` and `closed_paid_claim_count` are recomputed and its `risk_class_code`, `risk_class_score` and `risk_class_factor` re-derived from the new counters."

        Design: Corner/cross_cutting_complexity_layers/insured_and_firm_derived_counters_reconcile_after_create_and_after_resolution
        """
        book = _panel_book_with_two_open_claims(api)
        insured_id = book["insured"]["id"]

        after_intakes = validate_success(api.get_insured(insured_id, UW))
        assert after_intakes["open_claim_count"] == 2
        assert after_intakes["closed_paid_claim_count"] == 0

        obstetric_id = book["obstetric_claim"]["id"]
        decide_coverage(api, obstetric_id, "COVERED")
        assignment = assign_counsel(api, obstetric_id)
        pay_expense(api, obstetric_id, assignment["id"], 12000.00, "INV-RECON-1")
        resolved = dispose_claim(api, obstetric_id, "DISMISSED", "2026-10-01")

        assert resolved["claim_status"] == "RESOLVED"
        assert resolved["disposition"] == "DISMISSED"

        after_dismissal = validate_success(api.get_insured(insured_id, UW))
        assert after_dismissal["open_claim_count"] == 1, (
            "the resolved claim leaves the open population, the untouched one stays"
        )
        assert after_dismissal["closed_paid_claim_count"] == 0, (
            "a dismissal pays no indemnity, so it never joins the closed-paid count"
        )

        untouched = validate_success(api.get_claim(book["surgical_claim"]["id"], ADJ))
        assert untouched["claim_status"] == "INTAKE"

    def test_the_expense_payment_moves_the_claim_and_firm_ledgers_together(self, api):
        """One defence invoice raises the claim's paid expense, the assignment's billed amount and the firm's running ledger by the same figure.

        PRD: "The payment increases the claim's `paid_expense`, the assignment's `billed_expense_amount` and the firm's `billed_expense_total` each by the paid amount, and recomputes both incurred figures — which is the point at which `case_incurred` and `actuarial_incurred` begin to diverge, since paid expense erodes the carried expense reserve in the first figure and sits on top of it in the second."

        Design: Corner/cross_cutting_complexity_layers/insured_and_firm_derived_counters_reconcile_after_create_and_after_resolution
        """
        book = _panel_book_with_two_open_claims(api)
        obstetric_id = book["obstetric_claim"]["id"]
        decide_coverage(api, obstetric_id, "COVERED")
        assignment = assign_counsel(api, obstetric_id)

        firm_before = validate_success(api.get_counsel_firm(book["firm"]["id"], APPROVER))
        assert firm_before["open_assignment_count"] == 1
        assertions.assert_money(firm_before["billed_expense_total"], 0.00,
                                "billed_expense_total")

        billed = pay_expense(api, obstetric_id, assignment["id"], 12000.00, "INV-RECON-1")
        assertions.assert_money(billed["paid_expense"], 12000.00, "paid_expense")
        assertions.assert_money(billed["case_incurred"], 12000.00, "case_incurred")

        assignment_after = validate_success(
            api.get_counsel_assignment(assignment["id"], ADJ)
        )
        assertions.assert_money(assignment_after["billed_expense_amount"], 12000.00,
                                "billed_expense_amount")
        firm_after = validate_success(api.get_counsel_firm(book["firm"]["id"], APPROVER))
        assertions.assert_money(firm_after["billed_expense_total"], 12000.00,
                                "billed_expense_total")

    def test_the_dismissal_releases_panel_capacity_without_unwinding_the_ledger(self, api):
        """Resolving the claim closes its live assignment and hands the panel slot back, while the firm's billed expense stands.

        PRD: "Every counsel assignment on the claim whose `assignment_status` is `ASSIGNED` moves `ASSIGNED` → `CLOSED` with `closed_at` recorded, and each affected firm's `open_assignment_count` is decremented by 1, releasing panel capacity."

        Design: Corner/cross_cutting_complexity_layers/insured_and_firm_derived_counters_reconcile_after_create_and_after_resolution
        """
        book = _panel_book_with_two_open_claims(api)
        obstetric_id = book["obstetric_claim"]["id"]
        decide_coverage(api, obstetric_id, "COVERED")
        assignment = assign_counsel(api, obstetric_id)
        pay_expense(api, obstetric_id, assignment["id"], 12000.00, "INV-RECON-1")

        dispose_claim(api, obstetric_id, "DISMISSED", "2026-10-01")

        assignment_after = validate_success(
            api.get_counsel_assignment(assignment["id"], ADJ)
        )
        assert assignment_after["assignment_status"] == "CLOSED"
        assert assignment_after["closed_at"] is not None
        assertions.assert_money(assignment_after["billed_expense_amount"], 12000.00,
                                "billed_expense_amount")

        firm_after = validate_success(api.get_counsel_firm(book["firm"]["id"], APPROVER))
        assert firm_after["open_assignment_count"] == 0, (
            "the resolution releases the slot the assignment held"
        )
        assertions.assert_money(firm_after["billed_expense_total"], 12000.00,
                                "billed_expense_total")

        claim_after = validate_success(api.get_claim(obstetric_id, ADJ))
        assertions.assert_money(claim_after["paid_expense"], 12000.00, "paid_expense")
        assertions.assert_money(claim_after["case_incurred"], 12000.00, "case_incurred")


def _draft_quote_with_a_live_enrolment(api):
    """A DRAFT term quoted uncredited, plus an ENROLLED simulation-lab place."""
    advance_clock(api, CLOCK_EPOCH)
    specialty = build_specialty_class(api)
    insured = build_credentialed_insured(api, specialty["id"])
    policy = build_policy(api, insured["id"])
    term = build_term(
        api, policy["id"],
        effective_date="2026-09-01", expiration_date="2027-09-01",
    )
    enrolment = enrol_insured(api, insured["id"], "SIM_LAB", "2026-08-05")
    return {
        "insured": insured,
        "policy": policy,
        "term": term,
        "enrolment": enrolment,
    }


class TestDerivedFieldsAreVisibleImmediately:
    def test_the_completion_body_already_carries_the_credit_snapshot_and_expiry(self, api):
        """Recording the simulation-lab completion returns the frozen credit percentage and the two-year expiry in that very response.

        PRD: "`ENROLLED` → `COMPLETED` freezes `credit_pct_snapshot` at the credit percentage published for that programme, sets `expires_on` to 730 calendar days after `completed_on`, recomputes the insured's stacked credit, re-rates every `DRAFT` term on the insured's policies and recomputes each affected policy's `quoted_premium_total`."

        Design: Corner/consistency_model/derived_fields_are_visible_in_the_same_response_that_caused_them
        """
        book = _draft_quote_with_a_live_enrolment(api)
        assert book["enrolment"]["status"] == "ENROLLED"

        completed = complete_enrolment(
            api, book["enrolment"]["id"], "2026-08-10", "SIM-2026-0001"
        )
        assert completed["status"] == "COMPLETED"
        assertions.assert_ratio(completed["credit_pct_snapshot"], 0.05,
                                "credit_pct_snapshot")
        assert completed["expires_on"] == "2028-08-09"
        assert completed["expires_on"] == assertions.days_after("2026-08-10", 730)

    def test_the_drafted_quote_shows_the_credited_premium_on_the_next_read(self, api):
        """The completion re-rates the unbound quote at once, so the very next read of the term and its policy already shows the credited figures with no further write.

        PRD: "A great deal of this system's state is derived, and the derivation is always immediate: by the time a write returns, every roll-up affected by it has been recomputed."

        Design: Corner/consistency_model/derived_fields_are_visible_in_the_same_response_that_caused_them
        """
        book = _draft_quote_with_a_live_enrolment(api)
        term_before = book["term"]
        assertions.assert_ratio(term_before["credit_pct_applied"], 0.00,
                                "credit_pct_applied")
        assertions.assert_money(term_before["premium_manual"], 19285.00, "premium_manual")

        complete_enrolment(api, book["enrolment"]["id"], "2026-08-10", "SIM-2026-0001")

        term_after = validate_success(api.get_policy_term(term_before["id"], UW))
        assert term_after["status"] == "DRAFT"
        assertions.assert_ratio(term_after["credit_pct_applied"], 0.05,
                                "credit_pct_applied")
        assertions.assert_money(term_after["premium_manual"], 19285.00, "premium_manual")
        assertions.assert_money(term_after["premium_net"], 18320.75, "premium_net")
        assertions.assert_money(term_after["administrative_fee"], 250.00,
                                "administrative_fee")
        assertions.assert_money(term_after["guaranty_fund_assessment"], 232.13,
                                "guaranty_fund_assessment")
        assertions.assert_money(term_after["term_total"], 18802.88, "term_total")
        assertions.assert_fee_ladder(term_after)

        policy_after = validate_success(api.get_policy(book["policy"]["id"], UW))
        assertions.assert_money(
            policy_after["quoted_premium_total"], term_after["term_total"],
            "quoted_premium_total",
        )
