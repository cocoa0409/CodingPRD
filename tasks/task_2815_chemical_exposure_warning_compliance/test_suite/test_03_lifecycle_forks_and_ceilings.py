"""Lifecycles that fork, rejoin, loop under a counter, or run two dimensions at once.

The enforcement fork's cure branch, the peer-review revision cycle and its
rejection ceiling, and the product row that carries a commercial state and a
derived posture side by side.
"""

import pytest

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import factories as f
from test_helpers.api_errors import ERR_REJECTION_LIMIT_REACHED
from test_helpers.assertions import (
    assert_assessment_verdict,
    assert_instant,
    assert_lifecycle,
    assert_money_waterfall,
    assert_posture,
    assert_status,
)
from test_helpers.constants import (
    ASSESSMENT_DRAFT,
    ASSESSMENT_REJECTED,
    ASSESSMENT_SUBMITTED,
    DEFAULT_CLOCK,
    DISCLOSURE_VERIFIED,
    LIFECYCLE_DEVELOPMENT,
    LIFECYCLE_MARKETED,
    METHOD_MODELED,
    NOTICE_CURE_ELECTED,
    NOTICE_CURE_FAILED,
    NOTICE_DISMISSED,
    NOTICE_RECEIVED,
    NOTICE_SETTLEMENT_NEGOTIATION,
    NOTICE_UNDER_EVALUATION,
    POSTURE_CLEAR,
    POSTURE_ENFORCEMENT_HOLD,
    RESULT_BELOW,
    ROUTE_DERMAL,
)
from test_helpers.fixtures import (
    add_component,
    advance_disclosure,
    dismiss_notice,
    elect_cure,
    escalate_notice_to_negotiation,
    evaluate_notice,
    link_chemical,
    make_assessment,
    make_bpa,
    make_final_assessment,
    make_material,
    make_notice,
    make_product,
    make_supplier,
    market_product,
    peer_review_assessment,
    propose_settlement,
    read_product,
    set_clock,
    submit_assessment,
)
from test_helpers.test_users import (
    COMPLIANCE_ANALYST,
    REGULATORY_COUNSEL,
    TOXICOLOGY_REVIEWER,
)


# ─────────────────────────────────────────────────────────────────────────────
# Setups
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def curable_notice(api):
    """A curable notice served 2026-06-01 on a product with no components at all.

    50000 annual units sits under the cure ceiling and the theory is a failure
    to warn from a private party, so all four eligibility conditions hold.
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    chemical = make_bpa(api)
    product = make_product(
        api, "SKU-NL1", product_name="Trellis Clip", annual_units=50000
    )
    notice = make_notice(
        api,
        product["id"],
        chemical["id"],
        earliest_violation_date="2026-06-01T00:00:00Z",
        served_at="2026-06-01T00:00:00Z",
        noticing_party_name="Coastal Compliance Group",
    )
    return {"chemical": chemical, "product": product, "notice": notice}


def _read_notice(api, notice_id):
    return get_success_data(api.get_notice(notice_id, REGULATORY_COUNSEL))


def _abandon_cure(api, notice_id):
    return get_success_data(
        api.notice_transition(
            notice_id, f.action_payload("ABANDON_CURE"), REGULATORY_COUNSEL
        )
    )


@pytest.fixture
def submitted_assessment(api):
    """A DRAFT assessment on a product with one ACTIVE verified component, then submitted."""
    set_clock(api, DEFAULT_CLOCK)
    chemical = make_bpa(api)
    supplier = make_supplier(api, "Northgate Polymers")
    material = make_material(api, "RM-100", supplier["id"])
    link_chemical(api, material["id"], chemical["id"], 40.0)
    advance_disclosure(api, material["id"], DISCLOSURE_VERIFIED)
    product = make_product(
        api, "SKU-NL2", product_name="Hose Coupler", annual_units=50000
    )
    add_component(api, product["id"], material["id"], 0.25, 0.5)
    assessment = make_assessment(
        api, product["id"], chemical["id"], METHOD_MODELED, ROUTE_DERMAL, 1.0
    )
    assessment = submit_assessment(api, assessment["id"])
    return {"chemical": chemical, "product": product, "assessment": assessment}


def _read_assessment(api, assessment_id):
    return get_success_data(api.get_assessment(assessment_id, COMPLIANCE_ANALYST))


def _reject(api, assessment_id, note):
    return get_success_data(
        api.assessment_transition(
            assessment_id, f.reject_action(note), TOXICOLOGY_REVIEWER
        )
    )


def _reopen(api, assessment_id):
    return get_success_data(
        api.assessment_transition(
            assessment_id, f.action_payload("REOPEN"), COMPLIANCE_ANALYST
        )
    )


@pytest.fixture
def clear_product(api):
    """A product whose single FINAL assessment lands at 0.499 ug/day, below the 0.5 limit."""
    set_clock(api, DEFAULT_CLOCK)
    chemical = make_bpa(api)
    supplier = make_supplier(api, "Northgate Polymers")
    material = make_material(api, "RM-100", supplier["id"])
    link_chemical(api, material["id"], chemical["id"], 40.0)
    advance_disclosure(api, material["id"], DISCLOSURE_VERIFIED)
    product = make_product(
        api, "SKU-NL3", product_name="Garden Kneeler", annual_units=50000
    )
    add_component(api, product["id"], material["id"], 0.25, 0.5)
    assessment = make_final_assessment(
        api, product["id"], chemical["id"], METHOD_MODELED, ROUTE_DERMAL, 0.998
    )
    return {"chemical": chemical, "product": product, "assessment": assessment}


# ─────────────────────────────────────────────────────────────────────────────
# The enforcement fork: cure branch and its rejoin
# ─────────────────────────────────────────────────────────────────────────────


class TestCureForkAndRejoin:
    def test_intake_prices_the_window_and_evaluation_opens_the_branch(
        self, api, curable_notice
    ):
        """Sixty days from 2026-06-01 is 2026-07-31, and eligibility only appears at evaluation.

        PRD: "Intake computes `cure_deadline_at` as `served_at` plus a cure window of exactly sixty days, that is sixty times eighty-six thousand four hundred seconds, and the window is **inclusive** of that instant."

        Design: Difficulty/non_linear_state_machine/notice_cure_fork_and_join_rejoins_settlement
        """
        bundle = curable_notice
        notice = bundle["notice"]
        assert_status(notice, NOTICE_RECEIVED)
        assert_instant(
            notice["cure_deadline_at"], "2026-07-31T00:00:00Z", "cure_deadline_at"
        )
        assert notice["cure_eligible"] is None
        assert notice["cure_attempted"] is False

        evaluated = evaluate_notice(api, notice["id"])
        assert_status(evaluated, NOTICE_UNDER_EVALUATION)
        assert evaluated["cure_eligible"] is True

    def test_abandoning_the_cure_keeps_the_durable_flag_set(
        self, api, curable_notice
    ):
        """CURE_FAILED no longer says a cure happened, but the flag still does.

        PRD: "Election sets `cure_attempted` to true, and **that flag is never cleared** — it is the durable marker of the cure fork, and the settlement calculation reads it rather than the notice's current status."

        Design: Difficulty/non_linear_state_machine/notice_cure_fork_and_join_rejoins_settlement
        """
        bundle = curable_notice
        evaluate_notice(api, bundle["notice"]["id"])
        elected = elect_cure(api, bundle["notice"]["id"])
        assert_status(elected, NOTICE_CURE_ELECTED)
        assert elected["cure_attempted"] is True

        failed = _abandon_cure(api, bundle["notice"]["id"])
        assert_status(failed, NOTICE_CURE_FAILED)
        assert failed["cure_attempted"] is True
        assert failed["cure_completed_at"] is None

    def test_escalation_rejoins_the_two_branches_in_one_state(
        self, api, curable_notice
    ):
        """A failed cure escalates into the same SETTLEMENT_NEGOTIATION the direct path reaches.

        PRD: "The same escalation action is what rejoins the two branches: from `CURE_FAILED → SETTLEMENT_NEGOTIATION`, so a failed cure converges on exactly the same negotiation state."

        Design: Difficulty/non_linear_state_machine/notice_cure_fork_and_join_rejoins_settlement
        """
        bundle = curable_notice
        evaluate_notice(api, bundle["notice"]["id"])
        elect_cure(api, bundle["notice"]["id"])
        _abandon_cure(api, bundle["notice"]["id"])
        negotiating = escalate_notice_to_negotiation(
            api, bundle["notice"]["id"], evaluate_first=False
        )
        assert_status(negotiating, NOTICE_SETTLEMENT_NEGOTIATION)
        assert negotiating["cure_attempted"] is True
        assert negotiating["cure_completed_at"] is None

    def test_the_cure_factor_still_applies_after_the_join(self, api, curable_notice):
        """The mitigation factor reads the flag, so the rejoined notice mitigates at 0.5000.

        PRD: "The cure branch counts as taken when the notice's `cure_attempted` flag is true or its `cure_completed_at` is non-null; it is deliberately not read off the notice's current status, because a settlement can only be created from `SETTLEMENT_NEGOTIATION`, which the cure branch reaches only by way of `CURE_FAILED`, so a status-based test would make the cure factor unreachable."

        Design: Difficulty/non_linear_state_machine/notice_cure_fork_and_join_rejoins_settlement
        """
        bundle = curable_notice
        evaluate_notice(api, bundle["notice"]["id"])
        elect_cure(api, bundle["notice"]["id"])
        _abandon_cure(api, bundle["notice"]["id"])
        escalate_notice_to_negotiation(
            api, bundle["notice"]["id"], evaluate_first=False
        )

        set_clock(api, DEFAULT_CLOCK)
        settlement = propose_settlement(
            api, bundle["notice"]["id"], 500000, reformulation_commitment=False
        )
        assert_money_waterfall(
            settlement,
            violation_days=61,
            base_penalty_cents=2000000,
            mitigation_factor=0.5,
            adjusted_penalty_cents=1000000,
            fee_cap_cents=600000,
            allowed_fees_cents=500000,
            state_share_cents=750000,
            noticing_party_share_cents=250000,
            total_settlement_cents=1500000,
        )


# ─────────────────────────────────────────────────────────────────────────────
# The revision cycle and its rejection ceiling
# ─────────────────────────────────────────────────────────────────────────────


class TestRevisionCycleCeiling:
    def test_rejection_counts_and_reopening_clears_only_the_submitter(
        self, api, submitted_assessment
    ):
        """One lap of the cycle: REJECT counts 1, REOPEN drops the submitter but keeps the count.

        PRD: "Reopening clears `submitted_by_user_id` back to null but **deliberately preserves** `reviewed_by_user_id`, which is what allows an assessment that was peer-reviewed on an earlier turn of the cycle to be finalized directly out of `SUBMITTED` on a later turn."

        Design: Difficulty/non_linear_state_machine/assessment_reject_reopen_cycle_hits_rejection_ceiling
        """
        assessment_id = submitted_assessment["assessment"]["id"]
        rejected = _reject(api, assessment_id, "route assumption unsupported")
        assert_status(rejected, ASSESSMENT_REJECTED)
        assert rejected["rejection_count"] == 1

        reopened = _reopen(api, assessment_id)
        assert_status(reopened, ASSESSMENT_DRAFT)
        assert reopened["submitted_by_user_id"] is None
        assert reopened["rejection_count"] == 1

    def test_the_counter_is_monotone_across_laps(self, api, submitted_assessment):
        """A second lap through the cycle takes the count to 2 rather than resetting it.

        PRD: "Rejection is available from both `SUBMITTED → REJECTED` and `PEER_REVIEWED → REJECTED`, requires `review_note` in the payload, stores that note and increments `rejection_count` by 1; from `SUBMITTED` it additionally carries the same submitter-cannot-review separation."

        Design: Difficulty/non_linear_state_machine/assessment_reject_reopen_cycle_hits_rejection_ceiling
        """
        assessment_id = submitted_assessment["assessment"]["id"]
        _reject(api, assessment_id, "route assumption unsupported")
        _reopen(api, assessment_id)
        submit_assessment(api, assessment_id)
        rejected = _reject(api, assessment_id, "still unsupported")
        assert_status(rejected, ASSESSMENT_REJECTED)
        assert rejected["rejection_count"] == 2
        assert rejected["review_note"] == "still unsupported"

    def test_the_third_rejection_is_refused_and_the_row_does_not_move(
        self, api, submitted_assessment
    ):
        """The loop is bounded by the counter, not by a missing edge: the row stays SUBMITTED.

        PRD: "Rejection is capped: an assessment whose `rejection_count` already equals 2 refuses a further rejection with `ERR_REJECTION_LIMIT_REACHED`."

        Design: Difficulty/non_linear_state_machine/assessment_reject_reopen_cycle_hits_rejection_ceiling
        """
        assessment_id = submitted_assessment["assessment"]["id"]
        _reject(api, assessment_id, "route assumption unsupported")
        _reopen(api, assessment_id)
        submit_assessment(api, assessment_id)
        _reject(api, assessment_id, "still unsupported")
        _reopen(api, assessment_id)
        submit_assessment(api, assessment_id)

        response = api.assessment_transition(
            assessment_id, f.reject_action("third attempt"), TOXICOLOGY_REVIEWER
        )
        validate_error(response, ERR_REJECTION_LIMIT_REACHED)

        unchanged = _read_assessment(api, assessment_id)
        assert_status(unchanged, ASSESSMENT_SUBMITTED)
        assert unchanged["rejection_count"] == 2

    def test_a_peer_review_from_an_earlier_lap_survives_the_reopen(
        self, api, submitted_assessment
    ):
        """The preserved reviewer is what lets the cycle be re-entered without a fresh review.

        PRD: "Peer review takes the assessment `SUBMITTED → PEER_REVIEWED` and stamps `reviewed_by_user_id` with the acting `X-User-ID`; it is refused with `ERR_SEGREGATION_OF_DUTIES` when the acting `X-User-ID` equals the assessment's `submitted_by_user_id`."

        Design: Difficulty/non_linear_state_machine/assessment_reject_reopen_cycle_hits_rejection_ceiling
        """
        assessment_id = submitted_assessment["assessment"]["id"]
        reviewed = peer_review_assessment(api, assessment_id)
        reviewer_id = reviewed["reviewed_by_user_id"]
        assert reviewer_id is not None

        _reject(api, assessment_id, "route assumption unsupported")
        reopened = _reopen(api, assessment_id)
        assert reopened["reviewed_by_user_id"] == reviewer_id
        assert reopened["submitted_by_user_id"] is None


# ─────────────────────────────────────────────────────────────────────────────
# Two state dimensions on one product row
# ─────────────────────────────────────────────────────────────────────────────


class TestParallelStateDimensions:
    def test_the_below_limit_assessment_puts_the_posture_on_the_fallback_clause(
        self, api, clear_product
    ):
        """0.499 ug/day against a 0.5 limit is strictly below, so the ladder falls through to CLEAR.

        PRD: "`compliance_posture` is evaluated as a **top-down ladder in which the first matching clause wins**, and the value is one of `EXPOSURE_UNKNOWN`, `CLEAR`, `WARNING_REQUIRED`, `WARNING_ACTIVE` or `ENFORCEMENT_HOLD`."

        Design: Difficulty/non_linear_state_machine/product_parallel_dimensions_evolve_independently
        """
        bundle = clear_product
        assert_assessment_verdict(bundle["assessment"], 0.499, 0.998, RESULT_BELOW, 1)
        product = read_product(api, bundle["product"]["id"])
        assert_lifecycle(product, LIFECYCLE_DEVELOPMENT)
        assert_posture(product, POSTURE_CLEAR)

    def test_marketing_moves_only_the_commercial_dimension(self, api, clear_product):
        """MARKET advances lifecycle_state and leaves the posture exactly where it was.

        PRD: "Both actions are reserved to a `RegistryAdmin`, both increment the product's `version` by 1, and neither touches `compliance_posture` — the two dimensions are genuinely independent."

        Design: Difficulty/non_linear_state_machine/product_parallel_dimensions_evolve_independently
        """
        bundle = clear_product
        marketed = market_product(api, bundle["product"]["id"])
        assert_lifecycle(marketed, LIFECYCLE_MARKETED)
        assert_posture(marketed, POSTURE_CLEAR)

    def test_a_notice_holds_the_posture_without_demoting_the_lifecycle(
        self, api, clear_product
    ):
        """MARKETED with ENFORCEMENT_HOLD is a legal combined state on one row.

        PRD: "Intake also increments the product's `open_notice_count` by 1 and, through clause 1 of the posture ladder, drives the product's `compliance_posture` to `ENFORCEMENT_HOLD` — which outranks every other clause and freezes the bill of materials — and increments the product's `version` by 1."

        Design: Difficulty/non_linear_state_machine/product_parallel_dimensions_evolve_independently
        """
        bundle = clear_product
        market_product(api, bundle["product"]["id"])
        make_notice(
            api,
            bundle["product"]["id"],
            bundle["chemical"]["id"],
            earliest_violation_date="2026-07-01T00:00:00Z",
            served_at="2026-07-15T00:00:00Z",
            noticing_party_name="Coastal Compliance Group",
        )
        held = read_product(api, bundle["product"]["id"])
        assert_lifecycle(held, LIFECYCLE_MARKETED)
        assert_posture(held, POSTURE_ENFORCEMENT_HOLD)
        assert held["open_notice_count"] == 1

    def test_dismissal_releases_the_hold_and_the_product_stays_marketed(
        self, api, clear_product
    ):
        """The posture returns to CLEAR while the commercial dimension never moved.

        PRD: "The third branch dismisses the notice, taking it `UNDER_EVALUATION → DISMISSED`; that action requires `evaluation_note` in the payload, decrements the product's `open_notice_count` by 1 and recomputes `compliance_posture`, which leaves `ENFORCEMENT_HOLD` when the count reaches 0."

        Design: Difficulty/non_linear_state_machine/product_parallel_dimensions_evolve_independently
        """
        bundle = clear_product
        market_product(api, bundle["product"]["id"])
        notice = make_notice(
            api,
            bundle["product"]["id"],
            bundle["chemical"]["id"],
            earliest_violation_date="2026-07-01T00:00:00Z",
            served_at="2026-07-15T00:00:00Z",
            noticing_party_name="Coastal Compliance Group",
        )
        evaluate_notice(api, notice["id"])
        dismissed = dismiss_notice(api, notice["id"])
        assert_status(dismissed, NOTICE_DISMISSED)

        released = read_product(api, bundle["product"]["id"])
        assert released["open_notice_count"] == 0
        assert_posture(released, POSTURE_CLEAR)
        assert_lifecycle(released, LIFECYCLE_MARKETED)
        assert _read_notice(api, notice["id"])["status"] == NOTICE_DISMISSED
