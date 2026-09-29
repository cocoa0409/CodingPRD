"""Term, tail endorsement and rate filing lifecycles.

Covers the policy term status machine from the opening DRAFT quote through
issuance, pro rata and flat cancellation and clock-driven expiry, the tail
endorsement issuance guard and its flat-cancellation rescission, and the
rate filing submission gate — together with the policy-level and insured-level
statuses those transitions bubble up to.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories, fixtures as fx
from test_helpers.assertions import assert_money
from test_helpers.constants import OPERATOR_IDS

UW = fx.UW
ANALYST = fx.ANALYST

# The pinned obstetrics quote: 38000.00 base at the one-million limit, COOK_IL
# venue, risk class R2 and step year one.
STEP_ONE_NET = 19285.00
STEP_ONE_TOTAL = 19779.19
STEP_TWO_NET = 33060.00


def _obgyn_policy(api, credentialing_expires_on="2028-01-01"):
    """The recurring obstetrics book: rated class, credentialed insured, policy."""
    specialty = fx.build_specialty_class(api)
    insured = fx.build_credentialed_insured(
        api, specialty["id"], credentialing_expires_on
    )
    policy = fx.build_policy(api, insured["id"])
    return {"specialty": specialty, "insured": insured, "policy": policy}


def _first_term(api, policy_id):
    """A first, step-one term running 2026-08-01 to 2027-08-01."""
    return fx.build_term(api, policy_id, "2026-08-01", "2027-08-01")


def _in_force_first_term(api, policy_id):
    """The same term issued while the clock still sits on its effective date."""
    term = _first_term(api, policy_id)
    return fx.issue_term(api, term["id"])


def _ortho_occurrence_policy(api):
    """The Maricopa orthopaedic book: an occurrence form at a 24800.00 base."""
    specialty = fx.build_orthopedic_class(api, base_rate_per_million=24800.00)
    insured = fx.build_credentialed_insured(
        api, specialty["id"], "2028-01-01",
        legal_name="Desert Orthopedics PLLC",
        venue_code="MARICOPA_AZ",
        high_severity_procedure_pct=30,
    )
    policy = fx.build_policy(
        api, insured["id"], coverage_form="OCCURRENCE", retroactive_date=None
    )
    return {"specialty": specialty, "insured": insured, "policy": policy}


class TestFirstTermOpensAsAQuote:
    """The opening DRAFT term and the policy and insured statuses around it."""

    def test_a_new_term_opens_in_draft_with_nothing_returned_or_surrendered(self, api):
        """A first obstetrics term is quoted but unbound.

        PRD: "A newly created term opens in `DRAFT` status with `return_premium` at 0, `aggregate_limit_remaining` at 0, and `cancel_effective_date` and `issued_at` null."

        Design: Corner/state_machines/a_new_term_starts_in_draft_and_leaves_its_policy_quoted
        """
        book = _obgyn_policy(api)
        term = _first_term(api, book["policy"]["id"])

        assert term["status"] == "DRAFT"
        assert_money(term["return_premium"], 0, "return_premium")
        assert_money(term["aggregate_limit_remaining"], 0, "aggregate_limit_remaining")
        assert term["cancel_effective_date"] is None
        assert term["issued_at"] is None

    def test_a_term_with_no_predecessor_takes_index_one(self, api):
        """The insured's first year of cover is term one of the policy.

        PRD: "`term_index` is 1 when no predecessor is supplied and one more than the predecessor's index otherwise."

        Design: Corner/state_machines/a_new_term_starts_in_draft_and_leaves_its_policy_quoted
        """
        book = _obgyn_policy(api)
        term = _first_term(api, book["policy"]["id"])

        assert term["term_index"] == 1

    def test_the_quote_lands_in_the_policys_quoted_premium_total(self, api):
        """The 19779.19 quote is visible on the policy while the term is DRAFT.

        PRD: "`quoted_premium_total` is the sum of `term_total` over that policy's terms in `DRAFT` status, rounded to two decimal places."

        Design: Corner/state_machines/a_new_term_starts_in_draft_and_leaves_its_policy_quoted
        """
        book = _obgyn_policy(api)
        term = _first_term(api, book["policy"]["id"])

        assert_money(term["term_total"], STEP_ONE_TOTAL, "term_total")
        policy = validate_success(api.get_policy(book["policy"]["id"], UW))
        assert_money(
            policy["quoted_premium_total"], STEP_ONE_TOTAL, "quoted_premium_total"
        )

    def test_the_policy_stays_quoted_until_a_term_is_bound(self, api):
        """No term has reached issuance, so the policy is still an offer.

        PRD: "A policy is `QUOTED` until at least one of its terms reaches `ISSUED` or `IN_FORCE`, at which point it becomes `ACTIVE`."

        Design: Corner/state_machines/a_new_term_starts_in_draft_and_leaves_its_policy_quoted
        """
        book = _obgyn_policy(api)
        _first_term(api, book["policy"]["id"])

        policy = validate_success(api.get_policy(book["policy"]["id"], UW))
        assert policy["status"] == "QUOTED"

    def test_the_insured_stays_a_prospect_until_the_first_issuance(self, api):
        """A quoted-only physician has not yet been written.

        PRD: "An insured moves from `PROSPECT` to `ACTIVE` when the first term on one of its policies is issued."

        Design: Corner/state_machines/a_new_term_starts_in_draft_and_leaves_its_policy_quoted
        """
        book = _obgyn_policy(api)
        _first_term(api, book["policy"]["id"])

        insured = validate_success(api.get_insured(book["insured"]["id"], UW))
        assert insured["status"] == "PROSPECT"


class TestProRataCancellationOfALiveTerm:
    """Cancelling mid-term returns the unearned span and keeps the aggregate."""

    def test_the_unearned_span_comes_back_as_return_premium(self, api):
        """181 of 365 days remain, so 12298.08 of the 24800.00 is refunded.

        PRD: "`IN_FORCE` → `CANCELLED_PRO_RATA` records the cancellation date and returns only the unearned portion of the premium: the term's whole span in calendar days is measured from `effective_date` to `expiration_date`, the unearned span is measured from `cancel_effective_date` to `expiration_date`, and `return_premium` is `premium_net` multiplied by the unearned span divided by the whole span, with that single ratio applied at full precision and the result rounded half up to two decimal places once."

        Design: Corner/state_machines/pro_rata_cancellation_returns_the_unearned_half_and_keeps_the_aggregate
        """
        book = _ortho_occurrence_policy(api)
        term = _in_force_first_term(api, book["policy"]["id"])
        assert term["status"] == "IN_FORCE"
        assert_money(term["premium_net"], 24800.00, "premium_net")
        fx.advance_clock(api, "2027-02-01T00:00:00Z")

        cancelled = fx.cancel_term(api, term["id"], "PRO_RATA", "2027-02-01")

        assert cancelled["status"] == "CANCELLED_PRO_RATA"
        assert cancelled["cancel_effective_date"] == "2027-02-01"
        assert_money(cancelled["return_premium"], 12298.08, "return_premium")

    def test_pro_rata_cancellation_leaves_the_aggregate_limit_intact(self, api):
        """Unlike a rescission, a mid-term cancellation surrenders no limit.

        PRD: "`aggregate_limit_remaining` is left exactly as it was, claims already reported under the term keep the coverage position they had, no tail endorsement is voided, the policy's `written_premium_net_total` is recomputed, its `current_term_id` re-derived, and its `status` set to `CANCELLED`."

        Design: Corner/state_machines/pro_rata_cancellation_returns_the_unearned_half_and_keeps_the_aggregate
        """
        book = _ortho_occurrence_policy(api)
        term = _in_force_first_term(api, book["policy"]["id"])
        fx.advance_clock(api, "2027-02-01T00:00:00Z")

        cancelled = fx.cancel_term(api, term["id"], "PRO_RATA", "2027-02-01")

        assert_money(
            cancelled["aggregate_limit_remaining"], 3000000.00,
            "aggregate_limit_remaining",
        )
        policy = validate_success(api.get_policy(book["policy"]["id"], UW))
        assert policy["status"] == "CANCELLED"
        assert policy["current_term_id"] is None

    def test_the_written_ledger_keeps_only_the_earned_premium(self, api):
        """24800.00 written less 12298.08 returned leaves 12501.92 on the books.

        PRD: "`written_premium_net_total` is the sum, over that policy's terms in `ISSUED`, `IN_FORCE`, `EXPIRED`, `CANCELLED_FLAT` or `CANCELLED_PRO_RATA` status, of each term's `premium_net` less its `return_premium`, rounded to two decimal places."

        Design: Corner/state_machines/pro_rata_cancellation_returns_the_unearned_half_and_keeps_the_aggregate
        """
        book = _ortho_occurrence_policy(api)
        term = _in_force_first_term(api, book["policy"]["id"])
        fx.advance_clock(api, "2027-02-01T00:00:00Z")
        fx.cancel_term(api, term["id"], "PRO_RATA", "2027-02-01")

        policy = validate_success(api.get_policy(book["policy"]["id"], UW))
        assert_money(
            policy["written_premium_net_total"], 12501.92, "written_premium_net_total"
        )


class TestIssuanceIsOnlyAvailableOutOfDraft:
    """Replaying issuance on a term that already went live is refused."""

    def test_issuing_an_in_force_term_again_is_refused(self, api):
        """The underwriter cannot bind the same year of cover twice.

        PRD: "Only a term in `DRAFT` may be issued — any other status is refused with `ERR_TERM_STATE_INVALID`, and an unknown term with `ERR_POLICY_TERM_NOT_FOUND`."

        Design: Corner/state_machines/issuance_on_an_already_in_force_term_returns_term_state_invalid
        """
        book = _obgyn_policy(api)
        term = _in_force_first_term(api, book["policy"]["id"])
        assert term["status"] == "IN_FORCE"

        response = api.issue_policy_term(term["id"], UW)

        validate_error(response, "ERR_TERM_STATE_INVALID", 409)
        assert validate_success(
            api.get_policy_term(term["id"], UW)
        )["status"] == "IN_FORCE"

    def test_the_refused_replay_does_not_rebook_the_premium(self, api):
        """The written ledger still carries one year of cover, not two.

        PRD: "`written_premium_net_total` is the sum, over that policy's terms in `ISSUED`, `IN_FORCE`, `EXPIRED`, `CANCELLED_FLAT` or `CANCELLED_PRO_RATA` status, of each term's `premium_net` less its `return_premium`, rounded to two decimal places."

        Design: Corner/state_machines/issuance_on_an_already_in_force_term_returns_term_state_invalid
        """
        book = _obgyn_policy(api)
        term = _in_force_first_term(api, book["policy"]["id"])

        validate_error(api.issue_policy_term(term["id"], UW), "ERR_TERM_STATE_INVALID", 409)

        policy = validate_success(api.get_policy(book["policy"]["id"], UW))
        assert_money(
            policy["written_premium_net_total"], STEP_ONE_NET,
            "written_premium_net_total",
        )


class TestFlatCancellationIsTerminal:
    """A rescinded term cannot be cancelled a second time."""

    def test_cancelling_a_flat_cancelled_term_is_refused(self, api):
        """The rescission already ended the term, so nothing is left to cancel.

        PRD: "The term must be `ISSUED` or `IN_FORCE`, or the request is refused with `ERR_TERM_STATE_INVALID`."

        Design: Corner/state_machines/cancellation_of_a_flat_cancelled_term_is_locked_out
        """
        book = _obgyn_policy(api)
        term = _in_force_first_term(api, book["policy"]["id"])
        fx.cancel_term(api, term["id"], "FLAT", "2026-08-01")

        response = api.cancel_policy_term(
            term["id"], factories.cancellation_payload("PRO_RATA", "2027-02-01"), UW
        )

        validate_error(response, "ERR_TERM_STATE_INVALID", 409)
        after = validate_success(api.get_policy_term(term["id"], UW))
        assert after["status"] == "CANCELLED_FLAT"
        assert after["cancel_effective_date"] == "2026-08-01"

    def test_the_whole_net_premium_is_not_returned_twice(self, api):
        """The flat return stays at the single 19285.00 already refunded.

        PRD: "`IN_FORCE` → `CANCELLED_FLAT` records the cancellation date, returns the whole net premium by setting `return_premium` to `premium_net`, and surrenders the limit by setting `aggregate_limit_remaining` to 0.00."

        Design: Corner/state_machines/cancellation_of_a_flat_cancelled_term_is_locked_out
        """
        book = _obgyn_policy(api)
        term = _in_force_first_term(api, book["policy"]["id"])
        fx.cancel_term(api, term["id"], "FLAT", "2026-08-01")

        validate_error(
            api.cancel_policy_term(
                term["id"], factories.cancellation_payload("PRO_RATA", "2027-02-01"), UW
            ),
            "ERR_TERM_STATE_INVALID", 409,
        )

        after = validate_success(api.get_policy_term(term["id"], UW))
        assert_money(after["return_premium"], STEP_ONE_NET, "return_premium")
        assert_money(after["premium_net"], STEP_ONE_NET, "premium_net")
        assert_money(after["aggregate_limit_remaining"], 0.00, "aggregate_limit_remaining")


class TestRateFilingSubmissionHappensOnce:
    """A filing leaves DRAFT once; the replay is refused."""

    def _drafted_filing(self, api):
        specialty = fx.build_specialty_class(api)
        return fx.build_rate_filing(
            api, specialty["id"],
            proposed_rate_change_pct=8.00,
            experience_period_start="2024-01-01",
            experience_period_end="2025-12-31",
            effective_date="2026-09-01",
        )

    def test_a_second_submission_on_the_same_filing_is_refused(self, api):
        """The actuary cannot re-file a rate change already with the regulator.

        PRD: "Any decision attempted from a status the filing is not in is refused with `ERR_FILING_STATE_INVALID`, and a submission attempted on a filing that is not `DRAFT` is refused the same way."

        Design: Corner/state_machines/replaying_a_rate_filing_submission_is_rejected_on_the_second_call
        """
        filing = self._drafted_filing(api)
        submitted = fx.submit_rate_filing(api, filing["id"])
        assert submitted["status"] == "SUBMITTED"

        response = api.submit_rate_filing(filing["id"], ANALYST)

        validate_error(response, "ERR_FILING_STATE_INVALID", 409)
        after = validate_success(api.get_rate_filing(filing["id"], ANALYST))
        assert after["status"] == "SUBMITTED"
        assert after["decided_by_user_id"] is None

    def test_the_filing_keeps_its_original_filing_number_and_drafter(self, api):
        """The first filing on the books is RF-000001, drafted by the analyst.

        PRD: "The filing receives a `filing_number` of the form `RF-` followed by a six-digit zero-padded creation sequence, assigned in creation-timestamp ascending order beginning at `RF-000001`; `prepared_by_user_id` records the drafting actor; and the filing opens in `DRAFT`."

        Design: Corner/state_machines/replaying_a_rate_filing_submission_is_rejected_on_the_second_call
        """
        filing = self._drafted_filing(api)
        assert filing["status"] == "DRAFT"
        fx.submit_rate_filing(api, filing["id"])

        validate_error(
            api.submit_rate_filing(filing["id"], ANALYST),
            "ERR_FILING_STATE_INVALID", 409,
        )

        after = validate_success(api.get_rate_filing(filing["id"], ANALYST))
        assert after["filing_number"] == "RF-000001"
        assert after["prepared_by_user_id"] == OPERATOR_IDS["ActuarialAnalyst"]

    def test_a_filing_with_no_carried_reserves_is_not_evaluable(self, api):
        """With no claims behind the class there is no adequacy ratio to publish.

        PRD: "When `required_reserve_total` is zero, `reserve_adequacy_ratio` is null and `adequacy_flag` is `NOT_EVALUABLE`; otherwise the ratio is the carried total divided by the required total, rounded half up to four decimal places."

        Design: Corner/state_machines/replaying_a_rate_filing_submission_is_rejected_on_the_second_call
        """
        filing = self._drafted_filing(api)
        submitted = fx.submit_rate_filing(api, filing["id"])

        assert submitted["adequacy_flag"] == "NOT_EVALUABLE"
        assert submitted["reserve_adequacy_ratio"] is None


def _expired_term_with_an_issued_tail(api):
    """One expired obstetrics term carrying an issued five-year reporting tail."""
    book = _obgyn_policy(api, "2030-01-01")
    term = _in_force_first_term(api, book["policy"]["id"])
    fx.advance_clock(api, "2027-08-01T00:00:00Z")
    quoted_tail = fx.build_tail(
        api, book["policy"]["id"], term["id"],
        trigger_reason="CARRIER_CHANGE", effective_date="2027-08-01",
    )
    issued_tail = fx.issue_tail(api, quoted_tail["id"])
    return book, term, issued_tail


class TestOneLiveTailPerTriggeringTerm:
    """A second reporting tail on the same expired term cannot be issued."""

    def test_a_window_disjoint_second_tail_is_still_refused(self, api):
        """A 2032 window does not overlap the first tail, yet it is refused.

        PRD: "At most one tail per triggering term may be live: if another endorsement on the same `triggering_term_id` is already `ISSUED`, issuance is refused with `ERR_TAIL_ALREADY_ISSUED`."

        Design: Corner/state_machines/a_second_tail_on_the_same_triggering_term_cannot_be_issued
        """
        book, term, issued_tail = _expired_term_with_an_issued_tail(api)
        later_tail = fx.build_tail(
            api, book["policy"]["id"], term["id"],
            trigger_reason="PRACTICE_CLOSURE", effective_date="2032-08-01",
        )

        response = api.issue_tail_endorsement(later_tail["id"], UW)

        validate_error(response, "ERR_TAIL_ALREADY_ISSUED", 409)
        after = validate_success(api.get_tail_endorsement(later_tail["id"], UW))
        assert after["status"] == "QUOTED"
        assert after["issued_at"] is None
        assert validate_success(
            api.get_tail_endorsement(issued_tail["id"], UW)
        )["status"] == "ISSUED"

    def test_the_tail_basis_divides_the_step_factor_out_of_the_term(self, api):
        """19285.00 at step factor 0.35 reconstructs a 55100.00 mature premium.

        PRD: "`mature_premium_basis` is the triggering term's `premium_manual` divided by that term's `step_factor`, rounded half up to two decimal places — dividing the step factor out reconstructs the mature, step-five premium the term would have carried at full maturity."

        Design: Corner/state_machines/a_second_tail_on_the_same_triggering_term_cannot_be_issued
        """
        _book, _term, issued_tail = _expired_term_with_an_issued_tail(api)

        assert_money(
            issued_tail["mature_premium_basis"], 55100.00, "mature_premium_basis"
        )

    def test_the_five_year_tail_prices_at_one_and_a_half_times_the_basis(self, api):
        """The ERP_5YR factor of 1.55 lifts 55100.00 to an 85405.00 tail premium.

        PRD: "`tail_factor` is 1.55 for `ERP_5YR`, 2.00 for `ERP_UNLIMITED` and 0.00 for `DEATH_DISABILITY_RETIREMENT`, and `tail_premium` is `mature_premium_basis` multiplied by `tail_factor`, rounded half up to two decimal places."

        Design: Corner/state_machines/a_second_tail_on_the_same_triggering_term_cannot_be_issued
        """
        _book, _term, issued_tail = _expired_term_with_an_issued_tail(api)

        assert float(issued_tail["tail_factor"]) == 1.55
        assert_money(issued_tail["tail_premium"], 85405.00, "tail_premium")

    def test_the_reporting_window_closes_five_years_less_a_day_later(self, api):
        """A tail effective 2027-08-01 reports claims through 2032-07-31.

        PRD: "`reporting_window_end` closes the window: for `ERP_5YR` it is five years after the `effective_date` less one day, so that the closed window spans exactly five years; for `ERP_UNLIMITED` and `DEATH_DISABILITY_RETIREMENT` it is `9999-12-31`, an effectively unlimited window."

        Design: Corner/state_machines/a_second_tail_on_the_same_triggering_term_cannot_be_issued
        """
        _book, _term, issued_tail = _expired_term_with_an_issued_tail(api)

        assert issued_tail["effective_date"] == "2027-08-01"
        assert issued_tail["reporting_window_end"] == "2032-07-31"


def _renewed_book_with_two_tails(api):
    """An expired first term, a live renewal, one issued tail and one quoted tail."""
    book = _obgyn_policy(api, "2030-01-01")
    first_term = _in_force_first_term(api, book["policy"]["id"])
    fx.advance_clock(api, "2027-08-01T00:00:00Z")
    renewal = fx.build_term(
        api, book["policy"]["id"], "2027-08-01", "2028-08-01",
        predecessor_term_id=first_term["id"],
    )
    renewal = fx.issue_term(api, renewal["id"])
    issued_tail = fx.issue_tail(api, fx.build_tail(
        api, book["policy"]["id"], first_term["id"],
        trigger_reason="CARRIER_CHANGE", effective_date="2027-08-01",
    )["id"])
    quoted_tail = fx.build_tail(
        api, book["policy"]["id"], first_term["id"],
        trigger_reason="PRACTICE_CLOSURE", effective_date="2032-08-01",
    )
    return book, first_term, renewal, issued_tail, quoted_tail


class TestFlatCancellationRescindsDependentCover:
    """Rescinding the renewal voids the issued tail and spares the quoted one."""

    def test_the_issued_tail_is_voided_and_the_quoted_tail_is_left_alone(self, api):
        """Only the endorsement actually in force is rescinded with the policy.

        PRD: "It then rescinds what the term supported: every claim whose responding term is this term and whose coverage position is not already `DENIED` has its `coverage_status` set to `DENIED` with `denial_reason` `TERM_VOIDED`; every settlement negotiation on those claims whose status is neither `PAID` nor `ABANDONED` is moved to `ABANDONED`; and every tail endorsement on the same policy that is `ISSUED` is moved `ISSUED` → `VOID` with `void_reason` recorded as `POLICY_RESCINDED_BY_FLAT_CANCELLATION`, because rescinding the relationship from inception leaves no reporting obligation for a tail to extend."

        Design: Corner/state_machines/a_flat_cancellation_voids_the_issued_tail_but_leaves_a_quoted_one_alone
        """
        _book, _first, renewal, issued_tail, quoted_tail = _renewed_book_with_two_tails(api)

        fx.cancel_term(api, renewal["id"], "FLAT", "2027-08-01")

        voided = validate_success(api.get_tail_endorsement(issued_tail["id"], UW))
        assert voided["status"] == "VOID"
        assert voided["void_reason"] == "POLICY_RESCINDED_BY_FLAT_CANCELLATION"
        untouched = validate_success(api.get_tail_endorsement(quoted_tail["id"], UW))
        assert untouched["status"] == "QUOTED"
        assert untouched["void_reason"] is None

    def test_the_rescinded_renewal_returns_everything_and_surrenders_its_limit(self, api):
        """The step-two renewal hands back all 33060.00 and keeps no limit.

        PRD: "`IN_FORCE` → `CANCELLED_FLAT` records the cancellation date, returns the whole net premium by setting `return_premium` to `premium_net`, and surrenders the limit by setting `aggregate_limit_remaining` to 0.00."

        Design: Corner/state_machines/a_flat_cancellation_voids_the_issued_tail_but_leaves_a_quoted_one_alone
        """
        _book, _first, renewal, _issued, _quoted = _renewed_book_with_two_tails(api)

        cancelled = fx.cancel_term(api, renewal["id"], "FLAT", "2027-08-01")

        assert cancelled["status"] == "CANCELLED_FLAT"
        assert cancelled["cancel_effective_date"] == "2027-08-01"
        assert_money(cancelled["premium_net"], STEP_TWO_NET, "premium_net")
        assert_money(cancelled["return_premium"], STEP_TWO_NET, "return_premium")
        assert_money(
            cancelled["aggregate_limit_remaining"], 0.00, "aggregate_limit_remaining"
        )

    def test_the_written_ledger_drops_back_to_the_expired_year_alone(self, api):
        """52345.00 written across two years falls to the 19285.00 first year.

        PRD: "`written_premium_net_total` is the sum, over that policy's terms in `ISSUED`, `IN_FORCE`, `EXPIRED`, `CANCELLED_FLAT` or `CANCELLED_PRO_RATA` status, of each term's `premium_net` less its `return_premium`, rounded to two decimal places."

        Design: Corner/state_machines/a_flat_cancellation_voids_the_issued_tail_but_leaves_a_quoted_one_alone
        """
        book, _first, renewal, _issued, _quoted = _renewed_book_with_two_tails(api)
        before = validate_success(api.get_policy(book["policy"]["id"], UW))
        assert_money(
            before["written_premium_net_total"], 52345.00, "written_premium_net_total"
        )

        fx.cancel_term(api, renewal["id"], "FLAT", "2027-08-01")

        after = validate_success(api.get_policy(book["policy"]["id"], UW))
        assert_money(
            after["written_premium_net_total"], STEP_ONE_NET,
            "written_premium_net_total",
        )

    def test_the_policy_itself_ends_up_cancelled(self, api):
        """With the renewal rescinded and the first year expired, cover has ended.

        PRD: "The policy's `written_premium_net_total` is recomputed, its `current_term_id` re-derived, and its `status` set to `CANCELLED` once no term on it remains in `DRAFT`, `ISSUED` or `IN_FORCE`."

        Design: Corner/state_machines/a_flat_cancellation_voids_the_issued_tail_but_leaves_a_quoted_one_alone
        """
        book, first_term, renewal, _issued, _quoted = _renewed_book_with_two_tails(api)

        fx.cancel_term(api, renewal["id"], "FLAT", "2027-08-01")

        assert validate_success(
            api.get_policy_term(first_term["id"], UW)
        )["status"] == "EXPIRED"
        policy = validate_success(api.get_policy(book["policy"]["id"], UW))
        assert policy["status"] == "CANCELLED"
        assert policy["current_term_id"] is None


class TestExpiryBubblesUpFromTheTerm:
    """The clock sweep ends the term, and the policy follows without a call."""

    def test_the_clock_sweep_expires_the_live_term(self, api):
        """Reaching 2027-08-01 ends the year of cover that started 2026-08-01.

        PRD: "Third, every term in `IN_FORCE` status whose expiration date is on or before the new date becomes `EXPIRED`, in the same ordering, after which each affected policy's compound status and current-term pointer are re-derived."

        Design: Corner/state_machines/the_policy_expires_by_itself_once_its_only_term_expires
        """
        book = _obgyn_policy(api)
        term = _in_force_first_term(api, book["policy"]["id"])
        assert term["status"] == "IN_FORCE"

        fx.advance_clock(api, "2027-08-01T00:00:00Z")

        assert validate_success(
            api.get_policy_term(term["id"], UW)
        )["status"] == "EXPIRED"

    def test_the_policy_expires_with_its_only_term(self, api):
        """No underwriting call is made, yet the policy leaves ACTIVE.

        PRD: "Once no term remains in `DRAFT`, `ISSUED` or `IN_FORCE`, the policy becomes `EXPIRED` if at least one term is `EXPIRED`, and `CANCELLED` if at least one term is `CANCELLED_FLAT` or `CANCELLED_PRO_RATA`."

        Design: Corner/state_machines/the_policy_expires_by_itself_once_its_only_term_expires
        """
        book = _obgyn_policy(api)
        _in_force_first_term(api, book["policy"]["id"])
        before = validate_success(api.get_policy(book["policy"]["id"], UW))
        assert before["status"] == "ACTIVE"

        fx.advance_clock(api, "2027-08-01T00:00:00Z")

        after = validate_success(api.get_policy(book["policy"]["id"], UW))
        assert after["status"] == "EXPIRED"

    def test_the_current_term_pointer_clears_once_nothing_is_live(self, api):
        """The pointer names the live term, then names nothing at all.

        PRD: "`current_term_id` names the term with the latest effective date among terms in `ISSUED` or `IN_FORCE` status, breaking ties by creation timestamp ascending, and is null when no term qualifies."

        Design: Corner/state_machines/the_policy_expires_by_itself_once_its_only_term_expires
        """
        book = _obgyn_policy(api)
        term = _in_force_first_term(api, book["policy"]["id"])
        before = validate_success(api.get_policy(book["policy"]["id"], UW))
        assert before["current_term_id"] == term["id"]

        fx.advance_clock(api, "2027-08-01T00:00:00Z")

        after = validate_success(api.get_policy(book["policy"]["id"], UW))
        assert after["current_term_id"] is None

    def test_expiry_leaves_the_written_premium_on_the_books(self, api):
        """An expired term was still written, so the 19285.00 stays counted.

        PRD: "`written_premium_net_total` is the sum, over that policy's terms in `ISSUED`, `IN_FORCE`, `EXPIRED`, `CANCELLED_FLAT` or `CANCELLED_PRO_RATA` status, of each term's `premium_net` less its `return_premium`, rounded to two decimal places."

        Design: Corner/state_machines/the_policy_expires_by_itself_once_its_only_term_expires
        """
        book = _obgyn_policy(api)
        _in_force_first_term(api, book["policy"]["id"])

        fx.advance_clock(api, "2027-08-01T00:00:00Z")

        after = validate_success(api.get_policy(book["policy"]["id"], UW))
        assert_money(
            after["written_premium_net_total"], STEP_ONE_NET,
            "written_premium_net_total",
        )
