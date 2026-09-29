"""Validation precedence: which rule speaks when two of them fail at once.

The PRD does not leave the choice open.  §2.11 lays the rules out as a strict
ladder from rank 1 to rank 43, and the highest-ranked failing rule — the one with
the lowest rank number — decides the response.  The requests built here are
constructed so that two rules genuinely fail together, and each pairing is one
the ladder ranks explicitly, so the expected identifier is fixed rather than
plausible.  A companion test isolates the lower-ranked rule to prove it really
would have fired had the higher-ranked one not spoken first.
"""

from test_helpers import (
    AdjustmentStatus,
    ApiErrorId,
    CoverageDecision,
    CoverageStatus,
    PolicyStatus,
    PolicyType,
    TerritorialLimit,
    UseClass,
    assert_field_values,
    validate_error,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users

HULL_TERMS = f.schedule_payload("policy", "aircraft", "pilot")
AGREED_VALUE_CENTS = HULL_TERMS["agreed_value_cents"]

# A reserve one cent above the agreed value of the hull it protects: the smallest
# figure that breaches the exposure ceiling of §3.9 for a hull loss.
RESERVE_ABOVE_HULL_EXPOSURE_CENTS = AGREED_VALUE_CENTS + 1
DENIAL_REASON = f.coverage_decision_payload(decision=CoverageDecision.DENIED)[
    "denial_reason"
]


def denied_claim(api):
    """An investigated hull claim whose coverage decision came back as a denial."""
    book = fx.bound_policy_with_hull(api, clock=f.CLOCK_MID_TERM)
    book = fx.investigated_claim(api, book)
    book["claim"] = fx.decide_coverage(
        api, book["claim_id"], decision=CoverageDecision.DENIED
    )
    return book


def reserve_over_the_ceiling(api, claim_id):
    """Ask for a reserve above the hull's agreed value, as the claims adjuster."""
    return api.decide_coverage(
        claim_id,
        f.coverage_decision_payload(
            decision=CoverageDecision.COVERED,
            reserve_cents=RESERVE_ABOVE_HULL_EXPOSURE_CENTS,
        ),
        headers=users.CLAIMS_ADJUSTER,
    )


class TestStateBeatsFiscalOnADeniedClaim:
    """Rank 15, the claim's state, outranks rank 42, the reserve ceiling."""

    def test_reserving_a_denied_claim_above_the_ceiling_fails_on_state(self, api):
        """PRD §2.11: "When a single request would fail more than one rule, the outcome
        is not free choice: the rules form a strict ladder and the highest-ranked
        failing rule decides the response."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_reserving_a_denied_claim
        """
        book = denied_claim(api)
        assert book["claim"]["adjustment_status"] == AdjustmentStatus.DENIED

        response = reserve_over_the_ceiling(api, book["claim_id"])

        validate_error(response, ApiErrorId.CLAIM_INVALID_STATE)

    def test_the_refused_decision_leaves_the_denied_claim_exactly_as_it_was(self, api):
        """PRD §3.9: "The adjustment dimension is owned entirely by the `ClaimsAdjuster`
        role, and `SETTLED` and `DENIED` are its terminal states: a claim that has
        reached either refuses every further action with `ERR_CLAIM_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_reserving_a_denied_claim
        """
        book = denied_claim(api)
        before = fx.fetch_claim(api, book["claim_id"])

        validate_error(
            reserve_over_the_ceiling(api, book["claim_id"]),
            ApiErrorId.CLAIM_INVALID_STATE,
        )

        after = fx.fetch_claim(api, book["claim_id"])
        assert_field_values(
            after,
            adjustment_status=AdjustmentStatus.DENIED,
            reserve_cents=0,
            denial_reason=DENIAL_REASON,
        )
        assert after["version"] == before["version"], (
            "a refused request advances no version"
        )

    def test_the_refused_decision_writes_nothing_to_the_policy_reserve(self, api):
        """PRD §2.9: "`outstanding_reserve_cents` is the sum of `reserve_cents` over the
        claims on the policy whose `adjustment_status` is `RESERVED`, and no other
        claims."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_reserving_a_denied_claim
        """
        book = denied_claim(api)
        before = fx.fetch_policy(api, book["policy_id"])
        assert before["outstanding_reserve_cents"] == 0

        validate_error(
            reserve_over_the_ceiling(api, book["claim_id"]),
            ApiErrorId.CLAIM_INVALID_STATE,
        )

        after = fx.fetch_policy(api, book["policy_id"])
        assert after["outstanding_reserve_cents"] == 0
        assert after["version"] == before["version"]

    def test_the_same_oversized_reserve_is_refused_on_amount_while_the_claim_is_open(
        self, api
    ):
        """PRD §3.9: "And the reserve must not exceed the exposure it protects:
        `reserve_cents` must be no greater than the schedule's `agreed_value_cents` for a
        hull loss, and no greater than the policy's `liability_limit_cents` for a
        liability loss, with a breach refused as `ERR_RESERVE_EXCEEDS_LIMIT`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_reserving_a_denied_claim
        """
        book = fx.bound_policy_with_hull(api, clock=f.CLOCK_MID_TERM)
        book = fx.investigated_claim(api, book)
        assert (
            fx.fetch_claim(api, book["claim_id"])["adjustment_status"]
            == AdjustmentStatus.INVESTIGATING
        )

        response = reserve_over_the_ceiling(api, book["claim_id"])

        validate_error(response, ApiErrorId.RESERVE_EXCEEDS_LIMIT)
        assert (
            fx.fetch_claim(api, book["claim_id"])["adjustment_status"]
            == AdjustmentStatus.INVESTIGATING
        )


# ----------------------------------------------------------------------
# A second policy on the same operator, whose hull is covered only next year.
# ----------------------------------------------------------------------
NEXT_YEAR_COVER_FROM = "2027-01-01T00:00:00Z"
NEXT_YEAR_LOSS_DATE = "2027-02-01T00:00:00Z"
NEXT_YEAR_CLOCK = "2027-02-15T00:00:00Z"
PRIVATE_AGREED_VALUE_CENTS = 30000000
THIS_YEAR_LOSS_DATE = f.claim_payload("policy", "schedule")["loss_date"]


def two_bound_policies(api):
    """One operator, two bound policies, each carrying a hull of its own.

    The second policy's hull does not come on risk until the following January,
    so a loss dated this September is outside its window while remaining safely
    in the past relative to the clock.
    """
    book = fx.registered_book(api, clock=f.CLOCK_MID_TERM)
    fleet_policy = fx.make_policy(api, book["operator_id"])
    instructional_hull = fx.make_schedule(
        api, fleet_policy["id"], book["aircraft_id"], book["pilot_id"]
    )
    fleet_policy = fx.bind_policy(api, fleet_policy["id"])
    single_policy = fx.make_policy(
        api,
        book["operator_id"],
        policy_type=PolicyType.SINGLE_AIRCRAFT,
        territorial_limit_code=TerritorialLimit.DOMESTIC,
        permitted_use_classes=[UseClass.PRIVATE],
    )
    next_year_hull = fx.make_schedule(
        api,
        single_policy["id"],
        book["single_id"],
        book["pilot_id"],
        use_class=UseClass.PRIVATE,
        agreed_value_cents=PRIVATE_AGREED_VALUE_CENTS,
        effective_from=NEXT_YEAR_COVER_FROM,
    )
    single_policy = fx.bind_policy(api, single_policy["id"])
    book.update(
        {
            "fleet_policy": fleet_policy,
            "fleet_policy_id": fleet_policy["id"],
            "instructional_hull": instructional_hull,
            "instructional_hull_id": instructional_hull["id"],
            "single_policy": single_policy,
            "single_policy_id": single_policy["id"],
            "next_year_hull": next_year_hull,
            "next_year_hull_id": next_year_hull["id"],
        }
    )
    return book


def notify_across_the_policies(api, book, loss_date):
    """Name the fleet policy but the other policy's hull — a coherence failure."""
    return api.create_claim(
        f.claim_payload(
            book["fleet_policy_id"], book["next_year_hull_id"], loss_date=loss_date
        ),
        headers=users.BROKER,
    )


class TestTemporalBeatsReferentialOnANotification:
    """Rank 30, the loss date, outranks rank 33, cross-aggregate coherence."""

    def test_a_notification_failing_both_the_loss_date_and_the_coherence_check_reports_the_loss_date(
        self, api
    ):
        """PRD §2.11: "When a single request would fail more than one rule, the outcome
        is not free choice: the rules form a strict ladder and the highest-ranked
        failing rule decides the response."

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_referential_on_cross_policy_loss_notification
        """
        book = two_bound_policies(api)
        assert book["single_policy"]["status"] == PolicyStatus.BOUND
        hull = fx.fetch_schedule(api, book["next_year_hull_id"])
        assert hull["coverage_status"] == CoverageStatus.ACTIVE, (
            "the hull is live, so the liveness rule above rank 30 does not bite"
        )
        assert hull["policy_id"] == book["single_policy_id"]

        response = notify_across_the_policies(api, book, THIS_YEAR_LOSS_DATE)

        validate_error(response, ApiErrorId.LOSS_DATE_NOT_COVERED)

    def test_the_refused_notification_files_no_claim_on_either_policy(self, api):
        """PRD §3.9: "The `loss_date` must fall inside the schedule's coverage window
        treated as a half-open interval that includes `effective_from` and excludes
        `effective_to`, and must not lie in the future relative to the current logical
        clock; either failure is refused with `ERR_LOSS_DATE_NOT_COVERED`."

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_referential_on_cross_policy_loss_notification
        """
        book = two_bound_policies(api)

        validate_error(
            notify_across_the_policies(api, book, THIS_YEAR_LOSS_DATE),
            ApiErrorId.LOSS_DATE_NOT_COVERED,
        )

        assert fx.claims_of_policy(api, book["fleet_policy_id"]) == []
        assert fx.claims_of_policy(api, book["single_policy_id"]) == []

    def test_the_coherence_rule_speaks_alone_once_the_loss_date_is_covered(self, api):
        """PRD §3.9: "The `schedule_id` must belong to the `policy_id`, or the
        notification is refused with `ERR_SCHEDULE_POLICY_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_referential_on_cross_policy_loss_notification
        """
        book = two_bound_policies(api)
        fx.advance_clock(api, NEXT_YEAR_CLOCK)
        assert (
            fx.fetch_policy(api, book["fleet_policy_id"])["status"]
            == PolicyStatus.BOUND
        )

        response = notify_across_the_policies(api, book, NEXT_YEAR_LOSS_DATE)

        validate_error(response, ApiErrorId.SCHEDULE_POLICY_MISMATCH)
        assert fx.claims_of_policy(api, book["fleet_policy_id"]) == []
