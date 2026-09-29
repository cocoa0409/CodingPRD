"""The two temporal guards on an award: half-open rate-interval
non-intersection per community, and the carrier re-entry buffer."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_instant,
    assert_money,
)
from test_helpers.constants import (
    AGREEMENT_ACTIVE,
    AGREEMENT_TERMINATE,
    AGREEMENT_TERMINATED,
    COMMUNITY_ELIGIBLE,
    COMMUNITY_SUBSIDIZED,
    DEFAULT_CLOCK,
    EVAL_UNDER_EVALUATION,
    SOLICITATION_AWARDED,
    SOLICITATION_CLOSED,
)
from test_helpers.test_users import ADMIN, OFFICER


# ─── half_open_rate_intervals_per_community ───────────────────────────

def test_second_award_intersecting_a_live_rate_interval_is_refused(api: ApiClient):
    """A second agreement for the same community whose rate interval falls inside a live one is refused.

    "The first is **rate-interval non-intersection**: the new agreement's half-open interval must not intersect the corresponding interval of any other agreement for the same community whose `status` is `ACTIVE` or `SUSPENDED`."

    Design: Difficulty/resource_temporal_overlap/half_open_rate_intervals_per_community
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    first = award.agreement
    assert_instant(first["rate_effective_from"], DEFAULT_CLOCK, "rate_effective_from")
    assert_instant(
        first["rate_effective_to"], "2028-08-01T00:00:00Z", "rate_effective_to"
    )

    fx.set_clock(api, "2026-09-01T00:00:00Z")
    fx.publish_fuel_index(api, "2026-09", 2.4000)
    second_round = fx.open_solicitation(
        api, award.community_id, closes_at="2026-09-20T00:00:00Z"
    )
    rival = fx.submitted_proposal(
        api,
        second_round["id"],
        award.ref.second_carrier_id,
        award.ref.aircraft_type_id,
    )
    fx.close_solicitation(api, second_round["id"])

    refused = api.create_selection_order(
        second_round["id"], f.selection_order_payload(), OFFICER
    )
    validate_error(refused, E.ERR_RATE_INTERVAL_OVERLAP, 409)

    reread_round = validate_success(api.get_solicitation(second_round["id"], ADMIN))
    assert reread_round["status"] == SOLICITATION_CLOSED
    assert reread_round.get("selected_proposal_id") is None

    reread_rival = validate_success(api.get_proposal(rival["id"], ADMIN))
    assert reread_rival["evaluation_state"] == EVAL_UNDER_EVALUATION

    assert award.reload()["status"] == AGREEMENT_ACTIVE
    community = validate_success(api.get_community(award.community_id, ADMIN))
    assert community["active_agreement_count"] == 1


def test_second_award_whose_interval_merely_touches_the_first_is_accepted(api: ApiClient):
    """An award made exactly at the incumbent's `rate_effective_to` merely touches its interval and is booked.

    "Agreements in `HOLD_IN` or `TERMINATED` status are excluded from that sweep entirely, and two intervals that merely touch — one's `rate_effective_to` exactly equal to the other's `rate_effective_from` — do not intersect."

    Design: Difficulty/resource_temporal_overlap/half_open_rate_intervals_per_community
    """
    award = fx.build_award(
        api, clock=DEFAULT_CLOCK, proposal_overrides={"term_months": 12}
    )
    first = award.agreement
    assert_instant(
        first["rate_effective_to"], "2027-08-01T00:00:00Z", "rate_effective_to"
    )

    fx.set_clock(api, "2027-08-01T00:00:00Z")
    fx.publish_fuel_index(api, "2027-08", 2.4000)
    second_round = fx.open_solicitation(
        api, award.community_id, closes_at="2027-08-20T00:00:00Z"
    )
    fx.submitted_proposal(
        api,
        second_round["id"],
        award.ref.second_carrier_id,
        award.ref.aircraft_type_id,
        term_months=12,
    )
    fx.close_solicitation(api, second_round["id"])

    second = fx.issue_selection_order(api, second_round["id"])
    assert second["status"] == AGREEMENT_ACTIVE
    assert_instant(
        second["rate_effective_from"],
        first["rate_effective_to"],
        "touching rate_effective_from",
    )
    assert_instant(
        second["rate_effective_to"], "2028-08-01T00:00:00Z", "rate_effective_to"
    )
    assert second.get("predecessor_agreement_id") is None

    assert award.reload()["status"] == AGREEMENT_ACTIVE
    community = validate_success(api.get_community(award.community_id, ADMIN))
    assert community["status"] == COMMUNITY_SUBSIDIZED
    assert community["active_agreement_count"] == 2

    awarded_round = validate_success(api.get_solicitation(second_round["id"], ADMIN))
    assert awarded_round["status"] == SOLICITATION_AWARDED


def test_hold_in_predecessor_is_invisible_to_the_rate_interval_sweep(api: ApiClient):
    """A hold-in agreement is excluded from the sweep, so the replacement award is booked squarely inside its interval.

    "This is what allows a community to hold more than one `ACTIVE` agreement at a time, provided their rate periods are disjoint."

    Design: Difficulty/resource_temporal_overlap/half_open_rate_intervals_per_community
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    assert_instant(
        award.agreement["rate_effective_from"], DEFAULT_CLOCK, "rate_effective_from"
    )
    assert_instant(
        award.agreement["rate_effective_to"],
        "2028-08-01T00:00:00Z",
        "rate_effective_to",
    )
    hold_in = fx.build_hold_in(api, award)
    replacement = hold_in["replacement_solicitation"]

    fx.set_clock(api, "2026-09-01T00:00:00Z")
    fx.publish_fuel_index(api, "2026-09", 2.4000)
    fx.submitted_proposal(
        api,
        replacement["id"],
        award.ref.second_carrier_id,
        award.ref.aircraft_type_id,
    )
    fx.close_solicitation(api, replacement["id"])

    successor = fx.issue_selection_order(api, replacement["id"])
    assert successor["status"] == AGREEMENT_ACTIVE
    assert successor["predecessor_agreement_id"] == award.agreement_id
    # The successor's interval starts inside the excluded hold-in interval.
    assert_instant(
        successor["rate_effective_from"],
        "2026-09-01T00:00:00Z",
        "successor rate_effective_from",
    )
    assert_instant(
        successor["rate_effective_to"],
        "2028-09-01T00:00:00Z",
        "successor rate_effective_to",
    )

    predecessor = award.reload()
    assert predecessor["status"] == AGREEMENT_TERMINATED

    community = validate_success(api.get_community(award.community_id, ADMIN))
    assert community["status"] == COMMUNITY_SUBSIDIZED
    assert community["active_agreement_count"] == 1


# ─── carrier_reentry_buffer_after_termination ─────────────────────────

def test_reaward_one_day_before_the_reentry_buffer_point_is_refused(api: ApiClient):
    """Re-awarding the same carrier for the same community 13 days after termination is refused.

    "The second is the **carrier re-entry buffer**: if the winning carrier's previous agreement for this same community reached `TERMINATED`, the new agreement may not begin until the logical clock is at or after that agreement's `terminated_at` advanced by 14 days."

    Design: Difficulty/resource_temporal_overlap/carrier_reentry_buffer_after_termination
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    terminated = validate_success(
        api.agreement_status_action(
            award.agreement_id, f.agreement_status_payload(AGREEMENT_TERMINATE), ADMIN
        )
    )
    assert terminated["status"] == AGREEMENT_TERMINATED
    assert_instant(terminated["terminated_at"], DEFAULT_CLOCK, "terminated_at")

    fx.set_clock(api, "2026-08-14T00:00:00Z")
    second_round = fx.open_solicitation(
        api, award.community_id, closes_at="2026-08-25T00:00:00Z"
    )
    fx.submitted_proposal(
        api, second_round["id"], award.carrier_id, award.ref.aircraft_type_id
    )
    fx.close_solicitation(api, second_round["id"])

    refused = api.create_selection_order(
        second_round["id"], f.selection_order_payload(), OFFICER
    )
    validate_error(refused, E.ERR_CARRIER_REENTRY_BUFFER, 409)

    reread_round = validate_success(api.get_solicitation(second_round["id"], ADMIN))
    assert reread_round["status"] == SOLICITATION_CLOSED

    community = validate_success(api.get_community(award.community_id, ADMIN))
    assert community["status"] == COMMUNITY_ELIGIBLE
    assert community["active_agreement_count"] == 0


def test_reaward_exactly_at_the_reentry_buffer_point_is_accepted(api: ApiClient):
    """Exactly 14 days after termination the same carrier may be awarded the same community again.

    "Exactly at the buffer boundary the award proceeds; strictly before it, the order is refused with `ERR_CARRIER_REENTRY_BUFFER`."

    Design: Difficulty/resource_temporal_overlap/carrier_reentry_buffer_after_termination
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    validate_success(
        api.agreement_status_action(
            award.agreement_id, f.agreement_status_payload(AGREEMENT_TERMINATE), ADMIN
        )
    )

    fx.set_clock(api, "2026-08-15T00:00:00Z")
    second_round = fx.open_solicitation(
        api, award.community_id, closes_at="2026-08-25T00:00:00Z"
    )
    fx.submitted_proposal(
        api, second_round["id"], award.carrier_id, award.ref.aircraft_type_id
    )
    fx.close_solicitation(api, second_round["id"])

    second = fx.issue_selection_order(api, second_round["id"])
    assert second["status"] == AGREEMENT_ACTIVE
    assert second["carrier_id"] == award.carrier_id
    assert_instant(
        second["rate_effective_from"],
        "2026-08-15T00:00:00Z",
        "rate_effective_from",
    )
    assert_instant(
        second["rate_effective_to"], "2028-08-15T00:00:00Z", "rate_effective_to"
    )
    assert_money(second["total_committed_usd"], 3200000.00, "total_committed_usd")

    community = validate_success(api.get_community(award.community_id, ADMIN))
    assert community["status"] == COMMUNITY_SUBSIDIZED
    assert community["active_agreement_count"] == 1


def test_reentry_buffer_does_not_reach_a_different_community(api: ApiClient):
    """The buffer is scoped to the carrier-and-community pair, so the same carrier may start elsewhere inside the window.

    "Note the difference in shape between the two: the first compares two intervals, while the second compares a single instant against one buffered point."

    Design: Difficulty/resource_temporal_overlap/carrier_reentry_buffer_after_termination
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    validate_success(
        api.agreement_status_action(
            award.agreement_id, f.agreement_status_payload(AGREEMENT_TERMINATE), ADMIN
        )
    )
    other_community = fx.register_second_community(api)

    fx.set_clock(api, "2026-08-14T00:00:00Z")
    other_round = fx.open_solicitation(
        api, other_community["id"], closes_at="2026-08-25T00:00:00Z"
    )
    fx.submitted_proposal(
        api, other_round["id"], award.carrier_id, award.ref.aircraft_type_id
    )
    fx.close_solicitation(api, other_round["id"])

    other = fx.issue_selection_order(api, other_round["id"])
    assert other["status"] == AGREEMENT_ACTIVE
    assert other["carrier_id"] == award.carrier_id
    assert other["community_id"] == other_community["id"]
    assert_instant(
        other["rate_effective_from"], "2026-08-14T00:00:00Z", "rate_effective_from"
    )

    served = validate_success(api.get_community(other_community["id"], ADMIN))
    assert served["status"] == COMMUNITY_SUBSIDIZED
    assert served["active_agreement_count"] == 1

    original = validate_success(api.get_community(award.community_id, ADMIN))
    assert original["status"] == COMMUNITY_ELIGIBLE
    assert original["active_agreement_count"] == 0
