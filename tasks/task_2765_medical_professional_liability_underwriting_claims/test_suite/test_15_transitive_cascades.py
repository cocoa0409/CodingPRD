"""Multi-hop cascades radiating out of a rate approval, a panel removal and a
settlement disbursement.

Covers the rate filing that rewrites the manual and reprices pending quotes, the
panel removal that unwinds live counsel assignments and shrinks the next
selection pool, and the settlement payment that resolves a claim, erodes the
aggregate limit, re-scores the insured and mints a data bank obligation.
"""
from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures
from test_helpers.assertions import assert_money
from test_helpers.constants import CLOCK_EPOCH, OPERATOR_IDS
from test_helpers.test_users import TEST_USERS

UW = TEST_USERS["underwriting_officer_headers"]
ADJ = TEST_USERS["claims_adjuster_headers"]
APPROVER = TEST_USERS["claims_committee_approver_headers"]
ANALYST = TEST_USERS["actuarial_analyst_headers"]


# --------------------------------------------------------------------------
# Composite books built from the public endpoints only.
# --------------------------------------------------------------------------
def _orthopedic_quote_awaiting_a_filing_decision(api):
    """An orthopedic class at 24800.00 with one unissued DRAFT quote and a
    submitted rate filing seeking a ten percent increase."""
    fixtures.advance_clock(api, CLOCK_EPOCH)
    specialty = fixtures.build_orthopedic_class(api, base_rate_per_million=24800.00)
    insured = fixtures.build_insured(
        api, specialty["id"],
        legal_name="Desert Orthopedics PLLC",
        venue_code="MARICOPA_AZ",
        high_severity_procedure_pct=30,
    )
    policy = fixtures.build_policy(api, insured["id"], prior_acts_step_credit=4)
    term = fixtures.build_term(api, policy["id"], "2026-08-01", "2027-08-01")
    filing = fixtures.build_rate_filing(
        api, specialty["id"],
        indication_method="LOSS_RATIO_METHOD",
        proposed_rate_change_pct=10.00,
        experience_period_start="2026-08-01",
        experience_period_end="2027-08-01",
        effective_date="2027-08-01",
    )
    filing = fixtures.submit_rate_filing(api, filing["id"])
    return {
        "specialty": specialty,
        "insured": insured,
        "policy": policy,
        "term": term,
        "filing": filing,
    }


def _two_firm_panel_with_counsel_assigned(api):
    """A covered obstetrics claim in investigation with the higher-scored of two
    admitted Cook County firms holding the assignment."""
    fixtures.advance_clock(api, CLOCK_EPOCH)
    specialty = fixtures.build_specialty_class(api)
    insured = fixtures.build_credentialed_insured(api, specialty["id"])
    policy = fixtures.build_policy(api, insured["id"])
    term = fixtures.build_term(api, policy["id"], "2026-08-01", "2027-08-01")
    term = fixtures.issue_term(api, term["id"])
    halloran = fixtures.build_counsel_firm(
        api, firm_name="Halloran Defense LLP",
        admitted_venue_codes=["COOK_IL"],
        allegation_specialties=["OBSTETRIC_INJURY"],
        blended_hourly_rate=500.00, quality_score=95,
        max_concurrent_assignments=5, conflict_insured_ids=[],
    )
    vance = fixtures.build_counsel_firm(
        api, firm_name="Vance & Cole LLP",
        admitted_venue_codes=["COOK_IL"],
        allegation_specialties=["OBSTETRIC_INJURY"],
        blended_hourly_rate=400.00, quality_score=80,
        max_concurrent_assignments=5, conflict_insured_ids=[],
    )
    claim = fixtures.build_investigated_claim(
        api, insured["id"], "COVERED",
        incident_date="2026-08-05", report_date="2026-09-01",
        venue_code="COOK_IL", allegation_category="OBSTETRIC_INJURY",
        demand_amount=800000.00,
    )
    assignment = fixtures.assign_counsel(api, claim["id"])
    return {
        "specialty": specialty,
        "insured": insured,
        "policy": policy,
        "term": term,
        "halloran": halloran,
        "vance": vance,
        "claim": claim,
        "assignment": assignment,
    }


def _authorised_settlement_on_a_litigated_claim(api):
    """A litigated obstetrics claim with 400000.00 of committee authority granted
    against a 400000.00 offer under no consent clause."""
    fixtures.advance_clock(api, CLOCK_EPOCH)
    specialty = fixtures.build_specialty_class(api)
    insured = fixtures.build_credentialed_insured(api, specialty["id"])
    policy = fixtures.build_policy(api, insured["id"])
    term = fixtures.build_term(api, policy["id"], "2026-08-01", "2027-08-01")
    term = fixtures.issue_term(api, term["id"])
    claim = fixtures.build_litigated_claim(
        api, insured["id"], suit_filed_on="2026-09-15",
        incident_date="2026-08-05", report_date="2026-09-01",
        venue_code="COOK_IL", allegation_category="OBSTETRIC_INJURY",
        demand_amount=800000.00,
    )
    negotiation = fixtures.open_negotiation(
        api, claim["id"], proposed_amount=400000.00,
        authority_requested=400000.00, headers=ADJ,
    )
    negotiation = fixtures.decide_authority(
        api, negotiation["id"], "GRANT", 400000.00, headers=APPROVER,
    )
    return {
        "specialty": specialty,
        "insured": insured,
        "policy": policy,
        "term": term,
        "claim": claim,
        "negotiation": negotiation,
    }


class TestApprovedFilingCascadesToTheQuote:
    """One approval walks filing to class to term to policy."""

    def test_approval_rewrites_the_published_base_rate(self, api):
        """A ten percent approval lifts the manual base rate from 24800.00 to
        27280.00 and records the approved change on the filing.

        PRD: "`DRAFT` → `SUBMITTED` → `APPROVED` sets `approved_rate_change_pct`
        to the filing's `proposed_rate_change_pct`, records `decided_by_user_id`
        and the note, and then rewrites the class's manual rate: the new
        `base_rate_per_million` is the old base rate multiplied by one plus the
        approved change expressed as a fraction of 100, rounded half up to two
        decimal places."

        Design: Difficulty/transitive_cascade/approved_rate_filing_cascades_base_rate_through_draft_term_to_policy_total
        """
        book = _orthopedic_quote_awaiting_a_filing_decision(api)

        filing = fixtures.decide_rate_filing(
            api, book["filing"]["id"], "APPROVE",
            "indication supported by countrywide trend",
        )
        assert filing["status"] == "APPROVED"
        assert_money(
            filing["approved_rate_change_pct"], 10.00, "approved_rate_change_pct"
        )
        assert filing["decided_by_user_id"] == OPERATOR_IDS["ChiefActuary"]
        assert filing["prepared_by_user_id"] == OPERATOR_IDS["ActuarialAnalyst"]
        specialty = validate_success(
            api.get_specialty_class(book["specialty"]["id"], ANALYST)
        )
        assert_money(
            specialty["base_rate_per_million"], 27280.00, "base_rate_per_million"
        )

    def test_approval_advances_the_manual_edition(self, api):
        """The class moves to revision index one and remembers the change just
        approved.

        PRD: "The class's `rate_revision_index` increments by 1 and its
        `last_approved_rate_change_pct` records the change just approved."

        Design: Difficulty/transitive_cascade/approved_rate_filing_cascades_base_rate_through_draft_term_to_policy_total
        """
        book = _orthopedic_quote_awaiting_a_filing_decision(api)

        assert book["specialty"]["rate_revision_index"] == 0
        fixtures.decide_rate_filing(api, book["filing"]["id"], "APPROVE", "approved")
        specialty = validate_success(
            api.get_specialty_class(book["specialty"]["id"], ANALYST)
        )
        assert specialty["rate_revision_index"] == 1
        assert_money(
            specialty["last_approved_rate_change_pct"], 10.00,
            "last_approved_rate_change_pct",
        )

    def test_pending_quote_is_rerated_and_rolls_up_to_the_policy(self, api):
        """The unissued DRAFT term reprices from 25363.13 to a term total of
        28127.25 and the policy's quoted total follows it.

        PRD: "Finally every policy term still in `DRAFT` on the policies of
        insureds belonging to that class is re-rated against the new base rate,
        and each affected policy's `quoted_premium_total` is recomputed."

        Design: Difficulty/transitive_cascade/approved_rate_filing_cascades_base_rate_through_draft_term_to_policy_total
        """
        book = _orthopedic_quote_awaiting_a_filing_decision(api)

        assert_money(book["term"]["term_total"], 25363.13, "term_total before")
        fixtures.decide_rate_filing(api, book["filing"]["id"], "APPROVE", "approved")
        term = validate_success(api.get_policy_term(book["term"]["id"], UW))
        assert term["status"] == "DRAFT"
        assert_money(term["premium_manual"], 27280.00, "premium_manual")
        assert_money(term["premium_net"], 27280.00, "premium_net")
        assert_money(term["term_total"], 28127.25, "term_total")
        policy = validate_success(api.get_policy(book["policy"]["id"], UW))
        assert_money(
            policy["quoted_premium_total"], 28127.25, "quoted_premium_total"
        )

    def test_rerating_carries_the_quote_over_the_fee_tier(self, api):
        """The repriced net premium of 27280.00 reads the middle fee tier, so the
        flat charge rises from 250.00 to 500.00.

        PRD: "`administrative_fee` is a flat charge selected from three tiers on
        `premium_net` alone — 250.00 when `premium_net` is below 25000.00, 500.00
        when it is at least 25000.00 but below 100000.00, and 900.00 when it is
        100000.00 or more."

        Design: Difficulty/transitive_cascade/approved_rate_filing_cascades_base_rate_through_draft_term_to_policy_total
        """
        book = _orthopedic_quote_awaiting_a_filing_decision(api)

        assert_money(
            book["term"]["administrative_fee"], 250.00, "administrative_fee before"
        )
        fixtures.decide_rate_filing(api, book["filing"]["id"], "APPROVE", "approved")
        term = validate_success(api.get_policy_term(book["term"]["id"], UW))
        assert_money(term["administrative_fee"], 500.00, "administrative_fee")

    def test_rerating_reassesses_the_guaranty_fund_charge(self, api):
        """The assessment is recomputed on the new net premium plus the new fee,
        giving 347.25.

        PRD: "`guaranty_fund_assessment` is one and a quarter percent of the sum
        of `premium_net` and `administrative_fee`, rounded half up to two decimal
        places."

        Design: Difficulty/transitive_cascade/approved_rate_filing_cascades_base_rate_through_draft_term_to_policy_total
        """
        book = _orthopedic_quote_awaiting_a_filing_decision(api)

        fixtures.decide_rate_filing(api, book["filing"]["id"], "APPROVE", "approved")
        term = validate_success(api.get_policy_term(book["term"]["id"], UW))
        assert_money(
            term["guaranty_fund_assessment"], 347.25, "guaranty_fund_assessment"
        )

    def test_rerated_term_snapshots_the_new_manual_edition(self, api):
        """The re-rated term records that edition one of the rate manual produced
        its figures.

        PRD: "The term also snapshots `rate_revision_index_used` from the
        specialty class's `rate_revision_index` at the moment it was last rated,
        so a reader can tell which edition of the rate manual produced the
        figures."

        Design: Difficulty/transitive_cascade/approved_rate_filing_cascades_base_rate_through_draft_term_to_policy_total
        """
        book = _orthopedic_quote_awaiting_a_filing_decision(api)

        assert book["term"]["rate_revision_index_used"] == 0
        fixtures.decide_rate_filing(api, book["filing"]["id"], "APPROVE", "approved")
        term = validate_success(api.get_policy_term(book["term"]["id"], UW))
        assert term["rate_revision_index_used"] == 1

    def test_claimless_book_leaves_the_adequacy_review_unevaluable(self, api):
        """With no claim in scope the filing carries no adequacy ratio and is
        flagged NOT_EVALUABLE.

        PRD: "When `required_reserve_total` is zero, `reserve_adequacy_ratio` is
        null and `adequacy_flag` is `NOT_EVALUABLE`; otherwise the ratio is the
        carried total divided by the required total, rounded half up to four
        decimal places."

        Design: Difficulty/transitive_cascade/approved_rate_filing_cascades_base_rate_through_draft_term_to_policy_total
        """
        book = _orthopedic_quote_awaiting_a_filing_decision(api)

        filing = fixtures.decide_rate_filing(
            api, book["filing"]["id"], "APPROVE", "approved"
        )
        assert filing["adequacy_flag"] == "NOT_EVALUABLE"
        assert filing["reserve_adequacy_ratio"] is None


class TestPanelRemovalCascadesToTheClaim:
    """Striking a firm off the panel unwinds its work and shrinks the next pool."""

    def test_selector_ranks_the_higher_scored_firm_first(self, api):
        """Halloran at quality score 95 outranks Vance at 80 and takes the
        assignment at rank one.

        PRD: "The survivors are ranked by `quality_score` descending, then by
        `blended_hourly_rate` ascending, then by creation timestamp ascending —
        never by identifier — and the first-ranked firm is selected, so
        `selection_rank_snapshot` on the resulting assignment is 1."

        Design: Difficulty/transitive_cascade/panel_removal_cascades_to_assignment_claim_exclusions_and_capacity
        """
        book = _two_firm_panel_with_counsel_assigned(api)

        assert book["assignment"]["counsel_firm_id"] == book["halloran"]["id"]
        assert book["assignment"]["selection_rank_snapshot"] == 1

    def test_first_selection_sees_both_admitted_firms(self, api):
        """Both Cook County obstetric firms pass the eligibility filter, so the
        pool recorded on the assignment is two.

        PRD: "`candidate_pool_size` records how many firms passed that filter."

        Design: Difficulty/transitive_cascade/panel_removal_cascades_to_assignment_claim_exclusions_and_capacity
        """
        book = _two_firm_panel_with_counsel_assigned(api)

        assert book["assignment"]["candidate_pool_size"] == 2

    def test_removal_replaces_the_assignment_and_releases_capacity(self, api):
        """Removing Halloran flips its live assignment to REPLACED, drops its open
        count to zero, excludes it from the claim and flags the claim for
        reassignment.

        PRD: "Moving a firm to `REMOVED` also unwinds its live work: every
        assignment it holds in `ASSIGNED` status moves `ASSIGNED` → `REPLACED`
        with `closed_at` recorded, the firm's `open_assignment_count` is
        decremented once for each, the firm's identifier is appended to each
        affected claim's `excluded_counsel_firm_ids`, and each affected claim's
        `counsel_reassignment_required` is set to true — the signal that those
        claims need a fresh selector run."

        Design: Difficulty/transitive_cascade/panel_removal_cascades_to_assignment_claim_exclusions_and_capacity
        """
        book = _two_firm_panel_with_counsel_assigned(api)

        firm = fixtures.change_panel_status(
            api, book["halloran"]["id"], "REMOVED", "billing guideline breaches"
        )
        assert firm["panel_status"] == "REMOVED"
        assert firm["open_assignment_count"] == 0
        assignment = validate_success(
            api.get_counsel_assignment(book["assignment"]["id"], ADJ)
        )
        assert assignment["assignment_status"] == "REPLACED"
        assert assignment["closed_at"] is not None
        claim = validate_success(api.get_claim(book["claim"]["id"], ADJ))
        assert book["halloran"]["id"] in claim["excluded_counsel_firm_ids"]
        assert claim["counsel_reassignment_required"] is True

    def test_exclusion_shrinks_the_next_selection_pool(self, api):
        """The fresh selector run sees only Vance, the excluded firm no longer
        passing the eligibility filter.

        PRD: "`candidate_pool_size` records how many firms passed that filter."

        Design: Difficulty/transitive_cascade/panel_removal_cascades_to_assignment_claim_exclusions_and_capacity
        """
        book = _two_firm_panel_with_counsel_assigned(api)

        fixtures.change_panel_status(
            api, book["halloran"]["id"], "REMOVED", "billing guideline breaches"
        )
        replacement = fixtures.assign_counsel(api, book["claim"]["id"])
        assert replacement["candidate_pool_size"] == 1
        assert replacement["counsel_firm_id"] == book["vance"]["id"]

    def test_replacement_assignment_reopens_capacity_and_clears_the_flag(self, api):
        """Vance opens its assignment, takes one unit of panel capacity and the
        claim's reassignment flag drops back to false.

        PRD: "A successful assignment records `claim_id` and the selected
        `counsel_firm_id`, opens in `ASSIGNED` status with `assigned_at` at the
        current logical timestamp, `billed_expense_amount` at 0.00 and
        `decline_reason` and `closed_at` null, increments the firm's
        `open_assignment_count` by 1, and sets the claim's
        `counsel_reassignment_required` back to false."

        Design: Difficulty/transitive_cascade/panel_removal_cascades_to_assignment_claim_exclusions_and_capacity
        """
        book = _two_firm_panel_with_counsel_assigned(api)

        fixtures.change_panel_status(
            api, book["halloran"]["id"], "REMOVED", "billing guideline breaches"
        )
        replacement = fixtures.assign_counsel(api, book["claim"]["id"])
        assert replacement["assignment_status"] == "ASSIGNED"
        assert replacement["closed_at"] is None
        assert_money(
            replacement["billed_expense_amount"], 0.00, "billed_expense_amount"
        )
        vance = validate_success(api.get_counsel_firm(book["vance"]["id"], APPROVER))
        assert vance["open_assignment_count"] == 1
        claim = validate_success(api.get_claim(book["claim"]["id"], ADJ))
        assert claim["counsel_reassignment_required"] is False


class TestSettlementPaymentCascade:
    """One disbursement reaches the claim, the term, the insured and the data bank."""

    def test_disbursement_pays_the_offered_amount(self, api):
        """The payment disburses the 400000.00 that was offered, the authority
        having been granted at the same figure.

        PRD: "From `AUTHORITY_GRANTED` or `CONSENT_GRANTED`, `paid_amount` is the
        `proposed_amount`."

        Design: Difficulty/transitive_cascade/settlement_payment_cascades_limit_insured_score_and_npdb_obligation
        """
        book = _authorised_settlement_on_a_litigated_claim(api)

        negotiation = fixtures.pay_settlement(
            api, book["negotiation"]["id"], payment_date="2026-10-01"
        )
        assert_money(negotiation["paid_amount"], 400000.00, "paid_amount")

    def test_paid_negotiation_records_the_payment_date(self, api):
        """The negotiation terminates in PAID with the disbursement date on the
        record.

        PRD: "In all three cases — `AUTHORITY_GRANTED` → `PAID`,
        `CONSENT_GRANTED` → `PAID` and `HAMMER_INVOKED` → `PAID` — the status
        becomes `PAID`, `payment_date` is recorded, and the full claim resolution
        cascade of §3.9 runs against the disbursed amount."

        Design: Difficulty/transitive_cascade/settlement_payment_cascades_limit_insured_score_and_npdb_obligation
        """
        book = _authorised_settlement_on_a_litigated_claim(api)

        negotiation = fixtures.pay_settlement(
            api, book["negotiation"]["id"], payment_date="2026-10-01"
        )
        assert negotiation["status"] == "PAID"
        assert negotiation["payment_date"] == "2026-10-01"

    def test_payment_resolves_the_litigated_claim(self, api):
        """The claim leaves litigation for RESOLVED with the disbursement date as
        its resolution date.

        PRD: "The claim moves `INVESTIGATION` → `RESOLVED` or `LITIGATION` →
        `RESOLVED`, and `resolved_on` is recorded."

        Design: Difficulty/transitive_cascade/settlement_payment_cascades_limit_insured_score_and_npdb_obligation
        """
        book = _authorised_settlement_on_a_litigated_claim(api)

        fixtures.pay_settlement(
            api, book["negotiation"]["id"], payment_date="2026-10-01"
        )
        claim = validate_success(api.get_claim(book["claim"]["id"], ADJ))
        assert claim["claim_status"] == "RESOLVED"
        assert claim["resolved_on"] == "2026-10-01"

    def test_disbursement_is_what_records_a_settled_disposition(self, api):
        """The claim reads SETTLED only because the negotiation was disbursed.

        PRD: "`SETTLED` is a declared member of the disposition enumeration but is
        rejected here with `ERR_VALIDATION`: a settlement is recorded only by
        disbursing a negotiation, never by asserting the disposition directly."

        Design: Difficulty/transitive_cascade/settlement_payment_cascades_limit_insured_score_and_npdb_obligation
        """
        book = _authorised_settlement_on_a_litigated_claim(api)

        fixtures.pay_settlement(
            api, book["negotiation"]["id"], payment_date="2026-10-01"
        )
        claim = validate_success(api.get_claim(book["claim"]["id"], ADJ))
        assert claim["disposition"] == "SETTLED"

    def test_settlement_erodes_the_aggregate_limit_by_the_paid_amount(self, api):
        """The claim's paid indemnity rises to 400000.00 and the responding term's
        aggregate falls from 3000000.00 to 2600000.00.

        PRD: "Indemnity moves: on a `PLAINTIFF_VERDICT` the claim's
        `paid_indemnity` increases by the lesser of `verdict_amount` and the
        policy's `limit_per_claim`, and the responding term's
        `aggregate_limit_remaining` is debited by that same capped figure, so a
        verdict above the per-claim limit erodes the aggregate only to the extent
        the carrier actually owes it; on a settlement the increase and the debit
        are both the negotiation's `paid_amount`."

        Design: Difficulty/transitive_cascade/settlement_payment_cascades_limit_insured_score_and_npdb_obligation
        """
        book = _authorised_settlement_on_a_litigated_claim(api)

        fixtures.pay_settlement(
            api, book["negotiation"]["id"], payment_date="2026-10-01"
        )
        claim = validate_success(api.get_claim(book["claim"]["id"], ADJ))
        assert_money(claim["paid_indemnity"], 400000.00, "paid_indemnity")
        term = validate_success(api.get_policy_term(book["term"]["id"], UW))
        assert_money(
            term["aggregate_limit_remaining"], 2600000.00,
            "aggregate_limit_remaining",
        )

    def test_resolution_zeroes_reserves_and_converges_the_two_incurreds(self, api):
        """The resolved claim carries no reserve and both incurred figures settle
        on the 400000.00 actually paid.

        PRD: "Both `indemnity_reserve` and `expense_reserve` are then set to 0.00
        — a resolved claim carries no reserve, whatever its last reserve entry
        said, though the postings themselves remain in the append-only history —
        and `case_incurred` and `actuarial_incurred` are recomputed from the new
        figures, which after resolution converge on the sum of the payments."

        Design: Difficulty/transitive_cascade/settlement_payment_cascades_limit_insured_score_and_npdb_obligation
        """
        book = _authorised_settlement_on_a_litigated_claim(api)

        fixtures.pay_settlement(
            api, book["negotiation"]["id"], payment_date="2026-10-01"
        )
        claim = validate_success(api.get_claim(book["claim"]["id"], ADJ))
        assert_money(claim["indemnity_reserve"], 0.00, "indemnity_reserve")
        assert_money(claim["expense_reserve"], 0.00, "expense_reserve")
        assert_money(claim["case_incurred"], 400000.00, "case_incurred")
        assert_money(claim["actuarial_incurred"], 400000.00, "actuarial_incurred")

    def test_paid_claim_reprices_the_insureds_own_classification(self, api):
        """The insured's counters move from one open claim to one closed paid
        claim and the snapshot score re-derives to 4.70 in band R2.

        PRD: "Finally the insured's `open_claim_count` and
        `closed_paid_claim_count` are recomputed and its `risk_class_code`,
        `risk_class_score` and `risk_class_factor` re-derived from the new
        counters."

        Design: Difficulty/transitive_cascade/settlement_payment_cascades_limit_insured_score_and_npdb_obligation
        """
        book = _authorised_settlement_on_a_litigated_claim(api)

        before = validate_success(api.get_insured(book["insured"]["id"], UW))
        assert before["open_claim_count"] == 1
        assert_money(before["risk_class_score"], 4.20, "risk_class_score before")
        fixtures.pay_settlement(
            api, book["negotiation"]["id"], payment_date="2026-10-01"
        )
        insured = validate_success(api.get_insured(book["insured"]["id"], UW))
        assert insured["open_claim_count"] == 0
        assert insured["closed_paid_claim_count"] == 1
        assert_money(insured["risk_class_score"], 4.70, "risk_class_score")
        assert insured["risk_class_code"] == "R2"

    def test_physician_settlement_opens_a_reportable_obligation(self, api):
        """A settled physician payment above zero is reportable and the obligation
        opens pending transmission.

        PRD: "When all three hold, `reportable` is true, `non_reportable_reason`
        is null and the obligation opens in `PENDING` status awaiting
        transmission."

        Design: Difficulty/transitive_cascade/settlement_payment_cascades_limit_insured_score_and_npdb_obligation
        """
        book = _authorised_settlement_on_a_litigated_claim(api)

        fixtures.pay_settlement(
            api, book["negotiation"]["id"], payment_date="2026-10-01"
        )
        report = fixtures.npdb_report_for_claim(api, book["claim"]["id"])
        assert report is not None, "a settlement payment must mint one obligation"
        assert report["reportable"] is True
        assert report["non_reportable_reason"] is None
        assert report["report_status"] == "PENDING"
        assert report["insured_id"] == book["insured"]["id"]
        assert_money(report["payment_amount"], 400000.00, "payment_amount")

    def test_obligation_is_due_thirty_days_after_the_payment(self, api):
        """The statutory deadline on a 2026-10-01 payment falls on 2026-10-31.

        PRD: "Regardless of reportability, `due_date` is set to `payment_date`
        plus 30 calendar days, the statutory submission deadline."

        Design: Difficulty/transitive_cascade/settlement_payment_cascades_limit_insured_score_and_npdb_obligation
        """
        book = _authorised_settlement_on_a_litigated_claim(api)

        fixtures.pay_settlement(
            api, book["negotiation"]["id"], payment_date="2026-10-01"
        )
        report = fixtures.npdb_report_for_claim(api, book["claim"]["id"])
        assert report is not None, "a settlement payment must mint one obligation"
        assert report["payment_date"] == "2026-10-01"
        assert report["due_date"] == "2026-10-31"
