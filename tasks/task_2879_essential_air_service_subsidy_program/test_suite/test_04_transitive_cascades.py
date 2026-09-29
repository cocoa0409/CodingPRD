"""Multi-level cascades: replacement award, hold-in grant, deficient review.

Each cascade is triggered by a single request and has to run to completion
inside it, so every test here drives one trigger and then re-reads every
register the chain is supposed to have moved.
"""


from prd_bench_local_runner.testing import (
    get_success_data,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_instant,
    assert_money,
    assert_obligation_identity,
    assert_ratio,
    assert_score,
)
from test_helpers.constants import (
    AGREEMENT_ACTIVE,
    AGREEMENT_HOLD_IN,
    AGREEMENT_SUSPENDED,
    AGREEMENT_TERMINATED,
    BASIS_STRICT,
    CARRIER_ACTIVE,
    CARRIER_SUSPENDED,
    COMMUNITY_HOLD_IN,
    COMMUNITY_SUBSIDIZED,
    CREATED_REASON_INITIAL,
    CREATED_REASON_REPLACEMENT,
    DECISION_GRANT_WITH_HOLD_IN,
    DEFAULT_CLOCK,
    ENFORCEMENT_SUSPEND_HOLD_IN,
    EVAL_SELECTED,
    PAYMENT_BASIS_SCHEDULED_FLIGHT_FLAT,
    PAYMENT_COMPUTED,
    PAYMENT_DISBURSED,
    PERIOD_PAID,
    PETITION_CLOSED,
    PETITION_GRANTED_WITH_HOLD_IN,
    PETITION_REASON_CARRIER_NONPERFORMANCE,
    PETITION_UNDER_REVIEW,
    REVIEW_DEFICIENT,
    SERVICE_LEVEL_ENHANCED,
    SOLICITATION_AWARDED,
    SOLICITATION_OPEN,
)
from test_helpers.test_users import (
    ADMIN,
    ADMIN_REVIEWER,
    OFFICER,
    USER_ADMIN_REVIEWER,
    USER_OFFICER,
)


def _hold_in_after_a_settled_month(api):
    """Award, settle 2026-08, then grant a hold-in petition over it.

    Returns (award, larger_aircraft_type_id, settled_month, hold_in).
    """
    ref = fx.make_reference_data(api, clock=DEFAULT_CLOCK)
    larger = get_success_data(
        api.create_aircraft_type(f.larger_aircraft_type_payload(), ADMIN)
    )
    award = fx.build_award(api, ref=ref)
    settled = fx.settled_month(api, award.agreement_id, award.carrier_id, "2026-08")
    hold_in = fx.build_hold_in(
        api,
        award,
        reason_code=PETITION_REASON_CARRIER_NONPERFORMANCE,
        narrative="chronic cancellations on the Hays rotation",
        requested_effective_at="2026-11-01T00:00:00Z",
    )
    return award, larger["id"], settled, hold_in


def _bid_on_the_replacement(api, award, aircraft_type_id, replacement):
    """Submit the successor bid on the replacement round and close it."""
    proposal = fx.submitted_proposal(
        api,
        replacement["id"],
        award.ref.second_carrier_id,
        aircraft_type_id,
        service_level=SERVICE_LEVEL_ENHANCED,
        weekly_round_trips=14,
        seats_per_departure=30,
        annual_subsidy_request_usd=2900000.00,
        term_months=24,
        payment_basis=PAYMENT_BASIS_SCHEDULED_FLIGHT_FLAT,
    )
    fx.close_solicitation(api, replacement["id"])
    return proposal


# ─── replacement_award_cascade_releases_the_hold_in_predecessor ───────

def test_replacement_award_books_a_successor_naming_the_predecessor(api):
    """Awarding the replacement round resolves predecessor_agreement_id to the hold-in row.

    "When the community is in `HOLD_IN`, the award resolves the new agreement's `predecessor_agreement_id` to the community's hold-in agreement — the agreement for this community whose `status` is `HOLD_IN`, choosing the one with the earliest `created_at` if somehow more than one qualifies, and leaving the field empty when none does."

    Design: Difficulty/transitive_cascade/replacement_award_cascade_releases_the_hold_in_predecessor
    """
    award, larger_id, _settled, hold_in = _hold_in_after_a_settled_month(api)
    replacement = hold_in["replacement_solicitation"]
    assert replacement is not None, "the hold-in grant must open a replacement round"
    successor_bid = _bid_on_the_replacement(api, award, larger_id, replacement)

    successor = validate_success(
        api.create_selection_order(
            replacement["id"],
            f.selection_order_payload(order_note="replacement carrier secured"),
            OFFICER,
        ),
        201,
    )
    assert successor["status"] == AGREEMENT_ACTIVE
    assert successor["carrier_id"] == award.ref.second_carrier_id
    assert successor["predecessor_agreement_id"] == award.agreement_id
    assert successor["proposal_id"] == successor_bid["id"]
    assert_money(successor["annual_subsidy_usd"], 2900000.00, "annual_subsidy_usd")

    selected = validate_success(api.get_proposal(successor_bid["id"], ADMIN))
    assert selected["evaluation_state"] == EVAL_SELECTED
    assert_ratio(selected["composite_score"], 60.0000, "composite_score")

    awarded_round = validate_success(api.get_solicitation(replacement["id"], ADMIN))
    assert awarded_round["status"] == SOLICITATION_AWARDED
    assert awarded_round["created_reason"] == CREATED_REASON_REPLACEMENT
    assert_instant(awarded_round["closes_at"], "2026-09-30T00:00:00Z", "closes_at")


def test_successor_booking_releases_the_predecessor_unspent_obligation(api):
    """Booking the successor terminates the hold-in row and strips its remaining obligation.

    "This is the statutory hold-in requirement, and the release therefore happens as a cascade of the replacement award rather than as an administrative act: when the successor is booked, the hold-in agreement moves `HOLD_IN → TERMINATED` with `terminated_at` stamped, its `total_committed_usd` reset to `disbursed_to_date_usd` and its `obligated_remaining_usd` set to 0.00, its petition moves `GRANTED_WITH_HOLD_IN → CLOSED`, and the community closes the loop `SUBSIDIZED → HOLD_IN → SUBSIDIZED`."

    Design: Difficulty/transitive_cascade/replacement_award_cascade_releases_the_hold_in_predecessor
    """
    award, larger_id, settled, hold_in = _hold_in_after_a_settled_month(api)
    replacement = hold_in["replacement_solicitation"]
    assert hold_in["agreement"]["status"] == AGREEMENT_HOLD_IN
    assert_money(
        hold_in["agreement"]["obligated_remaining_usd"],
        3084903.97,
        "obligated_remaining_usd before the release",
    )
    _bid_on_the_replacement(api, award, larger_id, replacement)

    get_success_data(
        api.create_selection_order(
            replacement["id"], f.selection_order_payload(), OFFICER
        ),
        expected_status=201,
    )

    predecessor = validate_success(
        api.get_service_agreement(award.agreement_id, ADMIN)
    )
    assert predecessor["status"] == AGREEMENT_TERMINATED
    assert_instant(
        predecessor["terminated_at"], "2026-08-01T00:00:00Z", "terminated_at"
    )
    assert_money(predecessor["disbursed_to_date_usd"], 115096.03, "disbursed_to_date_usd")
    assert_money(predecessor["total_committed_usd"], 115096.03, "total_committed_usd")
    assert_money(predecessor["obligated_remaining_usd"], 0.00, "obligated_remaining_usd")
    assert_obligation_identity(predecessor)

    # The settled month is history and the cascade must not disturb it.
    period = validate_success(api.get_service_period(settled["period"]["id"], ADMIN))
    assert period["status"] == PERIOD_PAID
    payment = validate_success(api.get_subsidy_payment(settled["payment"]["id"], ADMIN))
    assert payment["status"] == PAYMENT_DISBURSED
    assert_money(payment["net_payment_usd"], 115096.03, "net_payment_usd")


def test_replacement_award_closes_the_petition_and_restores_the_community(api):
    """The petition and the community reach their end states in the awarding request itself.

    "Cascades run to completion within the single request that triggered them; there is no deferred or eventual settlement anywhere in this system."

    Design: Difficulty/transitive_cascade/replacement_award_cascade_releases_the_hold_in_predecessor
    """
    award, larger_id, _settled, hold_in = _hold_in_after_a_settled_month(api)
    replacement = hold_in["replacement_solicitation"]
    assert hold_in["petition"]["status"] == PETITION_GRANTED_WITH_HOLD_IN
    assert hold_in["community"]["status"] == COMMUNITY_HOLD_IN
    assert hold_in["community"]["active_agreement_count"] == 0
    _bid_on_the_replacement(api, award, larger_id, replacement)

    get_success_data(
        api.create_selection_order(
            replacement["id"], f.selection_order_payload(), OFFICER
        ),
        expected_status=201,
    )

    petition = validate_success(
        api.get_termination_petition(hold_in["petition"]["id"], ADMIN)
    )
    assert petition["status"] == PETITION_CLOSED

    community = validate_success(api.get_community(award.community_id, ADMIN))
    assert community["status"] == COMMUNITY_SUBSIDIZED
    assert community["active_agreement_count"] == 1


# ─── hold_in_grant_cascade_opens_the_replacement_solicitation ─────────

def test_hold_in_grant_parks_the_agreement_without_releasing_money(api):
    """Granting with hold-in freezes the agreement but leaves its ledger fully obligated.

    "The second is **continuity of service**: a community that loses its carrier enters a hold-in period during which the incumbent keeps flying at a premium rate and a replacement solicitation is opened automatically, and the incumbent's agreement cannot be released until a successor agreement is actually in force."

    Design: Difficulty/transitive_cascade/hold_in_grant_cascade_opens_the_replacement_solicitation
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    petition = fx.petition_under_review(api, award.agreement)
    assert petition["status"] == PETITION_UNDER_REVIEW

    granted = validate_success(
        api.petition_decision(
            petition["id"],
            f.petition_decision_payload(
                DECISION_GRANT_WITH_HOLD_IN,
                decision_note="granted subject to hold-in",
            ),
            OFFICER,
        )
    )
    assert granted["status"] == PETITION_GRANTED_WITH_HOLD_IN
    assert granted["decided_by_user_id"] == USER_OFFICER

    agreement = award.reload()
    assert agreement["status"] == AGREEMENT_HOLD_IN
    assert agreement["terminated_at"] is None
    assert_money(agreement["total_committed_usd"], 3200000.00, "total_committed_usd")
    assert_money(
        agreement["obligated_remaining_usd"], 3200000.00, "obligated_remaining_usd"
    )
    assert_money(agreement["disbursed_to_date_usd"], 0.00, "disbursed_to_date_usd")
    assert_obligation_identity(agreement)

    community = validate_success(api.get_community(award.community_id, ADMIN))
    assert community["status"] == COMMUNITY_HOLD_IN
    assert community["active_agreement_count"] == 0


def test_hold_in_grant_opens_one_replacement_round_sixty_days_out(api):
    """The terminal link of the grant cascade creates a fresh replacement solicitation.

    "In the same request the community moves `SUBSIDIZED → HOLD_IN` with its `active_agreement_count` decreased by 1, and the program opens a replacement solicitation for that community with `created_reason` `REPLACEMENT`, `status` `OPEN`, `round_number` 1 and a `closes_at` 60 days after the current logical clock reading."

    Design: Difficulty/transitive_cascade/hold_in_grant_cascade_opens_the_replacement_solicitation
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    original_solicitation_id = award.solicitation_id
    petition = fx.petition_under_review(api, award.agreement)

    get_success_data(
        api.petition_decision(
            petition["id"],
            f.petition_decision_payload(DECISION_GRANT_WITH_HOLD_IN),
            OFFICER,
        )
    )

    replacements = validate_success(
        api.list_community_solicitations(
            award.community_id,
            ADMIN,
            {"created_reason": CREATED_REASON_REPLACEMENT},
        )
    )
    assert len(replacements) == 1
    replacement = replacements[0]
    assert replacement["status"] == SOLICITATION_OPEN
    assert replacement["round_number"] == 1
    assert replacement["created_reason"] == CREATED_REASON_REPLACEMENT
    assert replacement["community_id"] == award.community_id
    assert replacement["preference_filing_count"] == 0
    assert_instant(replacement["closes_at"], "2026-09-30T00:00:00Z", "closes_at")

    # The round that produced the incumbent award is untouched.
    original = validate_success(api.get_solicitation(original_solicitation_id, ADMIN))
    assert original["status"] == SOLICITATION_AWARDED
    assert original["created_reason"] == CREATED_REASON_INITIAL
    winner = validate_success(api.get_proposal(award.proposal_id, ADMIN))
    assert winner["evaluation_state"] == EVAL_SELECTED


# ─── deficient_review_cascade_suspends_carrier_agreement_and_community ─

_BAD_AUGUST = {
    "scheduled_departures": 104,
    "completed_departures": 85,
    "cancelled_carrier_departures": 15,
    "cancelled_weather_departures": 4,
    "seats_offered": 1615,
    "passengers_enplaned": 580,
}


def _certified_bad_august(api):
    """Award, then certify one month poor enough to score DEFICIENT."""
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    month = fx.certified_month(
        api, award.agreement_id, award.carrier_id, "2026-08", **_BAD_AUGUST
    )
    return award, month


def test_deficient_completion_factor_is_computed_and_recorded(api):
    """A strict completion factor below 0.9000 lands the review in the DEFICIENT tier.

    "The completion factor selects the compliance `tier`: 0.9500 or better is `COMPLIANT`, from 0.9000 up to but not including 0.9500 is `WATCH`, and anything below 0.9000 is `DEFICIENT`."

    Design: Difficulty/transitive_cascade/deficient_review_cascade_suspends_carrier_agreement_and_community
    """
    award, _month = _certified_bad_august(api)
    assert award.agreement["min_monthly_seats"] == 1976

    review = validate_success(
        api.create_performance_review(
            f.performance_review_payload(
                award.agreement_id, "2026-08", "2026-08", basis=BASIS_STRICT
            ),
            ADMIN_REVIEWER,
        ),
        201,
    )
    assert review["basis"] == BASIS_STRICT
    assert review["months_in_window"] == 1
    assert review["included_period_count"] == 1
    assert review["sum_scheduled_departures"] == 104
    assert review["sum_completed_departures"] == 85
    assert_ratio(review["completion_factor"], 0.8173, "completion_factor")
    assert review["tier"] == REVIEW_DEFICIENT
    assert_ratio(review["seat_fulfillment"], 0.8173, "seat_fulfillment")
    assert_ratio(review["load_factor"], 0.3591, "load_factor")
    assert_score(review["quality_score"], 83.13)
    assert review["action_taken"] == ENFORCEMENT_SUSPEND_HOLD_IN
    assert review["reviewed_by_user_id"] == USER_ADMIN_REVIEWER


def test_deficient_review_suspends_both_the_carrier_and_the_agreement(api):
    """The severe branch moves the carrier and the reviewed agreement to SUSPENDED.

    "A `DEFICIENT` review is the severe branch and records `AGREEMENT_SUSPENDED_AND_HOLD_IN`: a carrier whose `status` is `ACTIVE` or `PROBATION` moves to `SUSPENDED`, the reviewed agreement moves `ACTIVE → SUSPENDED`, the served community moves `SUBSIDIZED → HOLD_IN` with its `active_agreement_count` decreased by 1, and the program immediately opens a replacement solicitation for that community with `created_reason` `REPLACEMENT`, `status` `OPEN`, `round_number` 1 and a `closes_at` 60 days after the current logical clock reading."

    Design: Difficulty/transitive_cascade/deficient_review_cascade_suspends_carrier_agreement_and_community
    """
    award, month = _certified_bad_august(api)
    assert validate_success(api.get_carrier(award.carrier_id, ADMIN))["status"] == (
        CARRIER_ACTIVE
    )

    get_success_data(
        api.create_performance_review(
            f.performance_review_payload(
                award.agreement_id, "2026-08", "2026-08", basis=BASIS_STRICT
            ),
            ADMIN_REVIEWER,
        ),
        expected_status=201,
    )

    carrier = validate_success(api.get_carrier(award.carrier_id, ADMIN))
    assert carrier["status"] == CARRIER_SUSPENDED
    assert carrier["latest_performance_tier"] == REVIEW_DEFICIENT
    assert_ratio(carrier["latest_completion_factor"], 0.8173, "latest_completion_factor")
    assert_score(carrier["latest_quality_score"], 83.13)
    assert carrier["consecutive_watch_count"] == 0

    agreement = award.reload()
    assert agreement["status"] == AGREEMENT_SUSPENDED
    assert agreement["terminated_at"] is None

    # Money already computed at certification is not unwound by the cascade.
    payment = validate_success(api.get_subsidy_payment(month["payment"]["id"], ADMIN))
    assert payment["status"] == PAYMENT_COMPUTED


def test_deficient_review_holds_the_community_in_and_opens_a_replacement(api):
    """One review request also moves the community and creates a replacement round.

    "A performance review that finds a carrier deficient, for example, mutates the carrier, the reviewed agreement and the served community, and creates a replacement solicitation — four rows, four version bumps, one request."

    Design: Difficulty/transitive_cascade/deficient_review_cascade_suspends_carrier_agreement_and_community
    """
    award, _month = _certified_bad_august(api)
    before = validate_success(api.get_community(award.community_id, ADMIN))
    assert before["status"] == COMMUNITY_SUBSIDIZED
    assert before["active_agreement_count"] == 1
    assert fx.replacement_solicitations(api, award.community_id) == []

    get_success_data(
        api.create_performance_review(
            f.performance_review_payload(
                award.agreement_id, "2026-08", "2026-08", basis=BASIS_STRICT
            ),
            ADMIN_REVIEWER,
        ),
        expected_status=201,
    )

    community = validate_success(api.get_community(award.community_id, ADMIN))
    assert community["status"] == COMMUNITY_HOLD_IN
    assert community["active_agreement_count"] == 0

    replacements = validate_success(
        api.list_community_solicitations(
            award.community_id,
            ADMIN,
            {"created_reason": CREATED_REASON_REPLACEMENT},
        )
    )
    assert len(replacements) == 1
    replacement = replacements[0]
    assert replacement["created_reason"] == CREATED_REASON_REPLACEMENT
    assert replacement["status"] == SOLICITATION_OPEN
    assert replacement["round_number"] == 1
    assert_instant(replacement["closes_at"], "2026-09-30T00:00:00Z", "closes_at")
