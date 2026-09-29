"""Transitions on one register that read the live state of another: carrier
standing, successor agreements and the parent agreement of a reported month."""

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
    assert_obligation_identity,
    assert_ratio,
)
from test_helpers.constants import (
    AGREEMENT_ACTIVE,
    AGREEMENT_HOLD_IN,
    AGREEMENT_REINSTATE,
    AGREEMENT_SUSPEND,
    AGREEMENT_SUSPENDED,
    AGREEMENT_TERMINATE,
    AGREEMENT_TERMINATED,
    CARRIER_ACTIVE,
    CARRIER_DEBARRED,
    CARRIER_PROBATION,
    CARRIER_SUSPENDED,
    COMMUNITY_ELIGIBLE,
    COMMUNITY_HOLD_IN,
    COMMUNITY_SUBSIDIZED,
    DEFAULT_CLOCK,
    PERIOD_REPORTED,
    PETITION_CLOSED,
    PETITION_GRANTED_WITH_HOLD_IN,
    STANDING_DEBAR,
    STANDING_PLACE_ON_PROBATION,
    STANDING_REINSTATE,
    STANDING_SUSPEND,
)
from test_helpers.test_users import ADMIN


# ─── agreement_reinstatement_reads_the_carrier_standing ───────────────

def test_agreement_reinstate_blocked_by_a_suspended_carrier_then_allowed_once_active(
    api: ApiClient,
):
    """Reinstating an agreement is refused while its carrier is SUSPENDED and succeeds only after the carrier itself is reinstated.

    "Reinstating one moves it `SUSPENDED → ACTIVE` but only while the obligated carrier's `status` is `ACTIVE` or `PROBATION`; a suspended or debarred carrier blocks the reinstatement with `ERR_CARRIER_NOT_IN_GOOD_STANDING`."

    Design: Difficulty/cross_entity_state_dependency/agreement_reinstatement_reads_the_carrier_standing
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)

    carrier = validate_success(
        api.carrier_standing_action(
            award.carrier_id, f.carrier_standing_payload(STANDING_SUSPEND), ADMIN
        )
    )
    assert carrier["status"] == CARRIER_SUSPENDED
    assert award.reload()["status"] == AGREEMENT_SUSPENDED

    blocked = api.agreement_status_action(
        award.agreement_id, f.agreement_status_payload(AGREEMENT_REINSTATE), ADMIN
    )
    validate_error(blocked, E.ERR_CARRIER_NOT_IN_GOOD_STANDING, 409)
    assert award.reload()["status"] == AGREEMENT_SUSPENDED

    reinstated_carrier = validate_success(
        api.carrier_standing_action(
            award.carrier_id, f.carrier_standing_payload(STANDING_REINSTATE), ADMIN
        )
    )
    assert reinstated_carrier["status"] == CARRIER_ACTIVE
    assert reinstated_carrier["consecutive_watch_count"] == 0

    agreement = validate_success(
        api.agreement_status_action(
            award.agreement_id, f.agreement_status_payload(AGREEMENT_REINSTATE), ADMIN
        )
    )
    assert agreement["status"] == AGREEMENT_ACTIVE

    community = validate_success(api.get_community(award.community_id, ADMIN))
    assert community["status"] == COMMUNITY_SUBSIDIZED


def test_agreement_reinstate_succeeds_while_the_carrier_is_on_probation(api: ApiClient):
    """A carrier on PROBATION is still in good enough standing for its agreement to be reinstated.

    "Placing a carrier on probation moves it `ACTIVE → PROBATION` and requires the carrier to be `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/agreement_reinstatement_reads_the_carrier_standing
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)

    suspended = validate_success(
        api.agreement_status_action(
            award.agreement_id, f.agreement_status_payload(AGREEMENT_SUSPEND), ADMIN
        )
    )
    assert suspended["status"] == AGREEMENT_SUSPENDED

    carrier = validate_success(
        api.carrier_standing_action(
            award.carrier_id,
            f.carrier_standing_payload(STANDING_PLACE_ON_PROBATION),
            ADMIN,
        )
    )
    assert carrier["status"] == CARRIER_PROBATION

    agreement = validate_success(
        api.agreement_status_action(
            award.agreement_id, f.agreement_status_payload(AGREEMENT_REINSTATE), ADMIN
        )
    )
    assert agreement["status"] == AGREEMENT_ACTIVE
    assert_obligation_identity(agreement)


def test_agreement_reinstate_blocked_while_the_carrier_is_debarred(api: ApiClient):
    """A debarred carrier permanently blocks the reinstatement of its suspended agreement.

    "Debarring moves it to `DEBARRED` from `ACTIVE`, `PROBATION` or `SUSPENDED`, and withdraws the carrier from every open competition by moving each of its proposals whose `submission_state` is `DRAFT` to `WITHDRAWN`; `DEBARRED` is terminal, so any standing action against an already-debarred carrier is refused with `ERR_CARRIER_NOT_ACTIONABLE`."

    Design: Difficulty/cross_entity_state_dependency/agreement_reinstatement_reads_the_carrier_standing
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)

    validate_success(
        api.agreement_status_action(
            award.agreement_id, f.agreement_status_payload(AGREEMENT_SUSPEND), ADMIN
        )
    )
    carrier = validate_success(
        api.carrier_standing_action(
            award.carrier_id, f.carrier_standing_payload(STANDING_DEBAR), ADMIN
        )
    )
    assert carrier["status"] == CARRIER_DEBARRED

    blocked = api.agreement_status_action(
        award.agreement_id, f.agreement_status_payload(AGREEMENT_REINSTATE), ADMIN
    )
    validate_error(blocked, E.ERR_CARRIER_NOT_IN_GOOD_STANDING, 409)
    assert award.reload()["status"] == AGREEMENT_SUSPENDED


# ─── hold_in_release_reads_the_successor_agreement_state ──────────────

def test_hold_in_agreement_cannot_be_terminated_without_an_active_successor(
    api: ApiClient,
):
    """Direct termination of a hold-in agreement is refused while no successor has reached ACTIVE.

    "A hold-in agreement may only be released once a successor agreement whose `predecessor_agreement_id` equals it has actually reached `ACTIVE` status; until then the attempt is refused with `ERR_REPLACEMENT_AGREEMENT_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/hold_in_release_reads_the_successor_agreement_state
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    hold_in = fx.build_hold_in(api, award)
    assert hold_in["agreement"]["status"] == AGREEMENT_HOLD_IN
    assert hold_in["community"]["status"] == COMMUNITY_HOLD_IN
    assert hold_in["replacement_solicitation"] is not None

    refused = api.agreement_status_action(
        award.agreement_id, f.agreement_status_payload(AGREEMENT_TERMINATE), ADMIN
    )
    validate_error(refused, E.ERR_REPLACEMENT_AGREEMENT_REQUIRED, 409)

    agreement = award.reload()
    assert agreement["status"] == AGREEMENT_HOLD_IN
    assert not agreement.get("terminated_at")
    assert_money(agreement["total_committed_usd"], 3200000.00, "total_committed_usd")
    assert_money(
        agreement["obligated_remaining_usd"], 3200000.00, "obligated_remaining_usd"
    )

    petition = validate_success(
        api.get_termination_petition(hold_in["petition"]["id"], ADMIN)
    )
    assert petition["status"] == PETITION_GRANTED_WITH_HOLD_IN

    community = validate_success(api.get_community(award.community_id, ADMIN))
    assert community["status"] == COMMUNITY_HOLD_IN


def test_replacement_award_releases_the_hold_in_predecessor(api: ApiClient):
    """Booking the successor is what releases the hold-in agreement, closes its petition and returns the community to SUBSIDIZED.

    "This is the statutory hold-in requirement, and the release therefore happens as a cascade of the replacement award rather than as an administrative act: when the successor is booked, the hold-in agreement moves `HOLD_IN → TERMINATED` with `terminated_at` stamped, its `total_committed_usd` reset to `disbursed_to_date_usd` and its `obligated_remaining_usd` set to 0.00, its petition moves `GRANTED_WITH_HOLD_IN → CLOSED`, and the community closes the loop `SUBSIDIZED → HOLD_IN → SUBSIDIZED`."

    Design: Difficulty/cross_entity_state_dependency/hold_in_release_reads_the_successor_agreement_state
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
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
    assert_instant(
        successor["rate_effective_from"],
        "2026-09-01T00:00:00Z",
        "successor rate_effective_from",
    )

    predecessor = award.reload()
    assert predecessor["status"] == AGREEMENT_TERMINATED
    assert_instant(
        predecessor["terminated_at"], "2026-09-01T00:00:00Z", "terminated_at"
    )
    assert_money(predecessor["total_committed_usd"], 0.00, "total_committed_usd")
    assert_money(predecessor["obligated_remaining_usd"], 0.00, "obligated_remaining_usd")
    assert_obligation_identity(predecessor)

    petition = validate_success(
        api.get_termination_petition(hold_in["petition"]["id"], ADMIN)
    )
    assert petition["status"] == PETITION_CLOSED

    community = validate_success(api.get_community(award.community_id, ADMIN))
    assert community["status"] == COMMUNITY_SUBSIDIZED
    assert community["active_agreement_count"] == 1


def test_suspended_agreement_without_a_successor_terminates_cleanly(api: ApiClient):
    """A merely SUSPENDED agreement needs no successor: direct termination releases its unspent obligation.

    "Termination stamps `terminated_at` from the logical clock and releases the unspent obligation: `total_committed_usd` is reset to `disbursed_to_date_usd` rounded to cents and `obligated_remaining_usd` is set to 0.00, so the conservation identity still holds with nothing left committed."

    Design: Difficulty/cross_entity_state_dependency/hold_in_release_reads_the_successor_agreement_state
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    validate_success(
        api.agreement_status_action(
            award.agreement_id, f.agreement_status_payload(AGREEMENT_SUSPEND), ADMIN
        )
    )

    terminated = validate_success(
        api.agreement_status_action(
            award.agreement_id, f.agreement_status_payload(AGREEMENT_TERMINATE), ADMIN
        )
    )
    assert terminated["status"] == AGREEMENT_TERMINATED
    assert_instant(terminated["terminated_at"], DEFAULT_CLOCK, "terminated_at")
    assert_money(terminated["total_committed_usd"], 0.00, "total_committed_usd")
    assert_money(terminated["obligated_remaining_usd"], 0.00, "obligated_remaining_usd")
    assert_obligation_identity(terminated)

    community = validate_success(api.get_community(award.community_id, ADMIN))
    assert community["status"] == COMMUNITY_ELIGIBLE
    assert community["active_agreement_count"] == 0


# ─── period_report_reads_the_parent_agreement_status ──────────────────

def test_report_refused_while_the_parent_agreement_is_suspended(api: ApiClient):
    """A month cannot be reported while its agreement is SUSPENDED, and reinstating only the carrier is not enough.

    "A report is admissible only while the period's `status` is `OPEN` — otherwise `ERR_PERIOD_NOT_REPORTABLE` — and only while the parent agreement's `status` is `ACTIVE` or `HOLD_IN`, since a suspended or terminated agreement has no service to report; a report against any other agreement status is refused with `ERR_AGREEMENT_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/period_report_reads_the_parent_agreement_status
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    period = fx.open_period(api, award.agreement_id, "2026-08")

    validate_success(
        api.carrier_standing_action(
            award.carrier_id, f.carrier_standing_payload(STANDING_SUSPEND), ADMIN
        )
    )
    assert award.reload()["status"] == AGREEMENT_SUSPENDED

    refused = api.report_service_period(
        period["id"], f.report_payload(), award.carrier_headers
    )
    validate_error(refused, E.ERR_AGREEMENT_NOT_ACTIVE, 409)

    validate_success(
        api.carrier_standing_action(
            award.carrier_id, f.carrier_standing_payload(STANDING_REINSTATE), ADMIN
        )
    )
    still_refused = api.report_service_period(
        period["id"], f.report_payload(), award.carrier_headers
    )
    validate_error(still_refused, E.ERR_AGREEMENT_NOT_ACTIVE, 409)

    validate_success(
        api.agreement_status_action(
            award.agreement_id, f.agreement_status_payload(AGREEMENT_REINSTATE), ADMIN
        )
    )
    reported = validate_success(
        api.report_service_period(
            period["id"], f.report_payload(), award.carrier_headers
        )
    )
    assert reported["status"] == PERIOD_REPORTED
    assert_ratio(reported["period_completion_factor"], 0.8750, "period_completion_factor")

    agreement = award.reload()
    assert agreement["status"] == AGREEMENT_ACTIVE
    assert agreement["cumulative_scheduled_departures"] == 104
    assert agreement["cumulative_completed_departures"] == 91


def test_report_accepted_while_the_parent_agreement_is_in_hold_in(api: ApiClient):
    """A hold-in agreement is still flying, so its month reports normally.

    "A report is admissible only while the period's `status` is `OPEN` — otherwise `ERR_PERIOD_NOT_REPORTABLE` — and only while the parent agreement's `status` is `ACTIVE` or `HOLD_IN`, since a suspended or terminated agreement has no service to report; a report against any other agreement status is refused with `ERR_AGREEMENT_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/period_report_reads_the_parent_agreement_status
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    hold_in = fx.build_hold_in(api, award)
    assert hold_in["agreement"]["status"] == AGREEMENT_HOLD_IN

    period = fx.open_period(api, award.agreement_id, "2026-08")
    reported = validate_success(
        api.report_service_period(
            period["id"], f.report_payload(), award.carrier_headers
        )
    )
    assert reported["status"] == PERIOD_REPORTED
    assert_ratio(reported["period_completion_factor"], 0.8750, "period_completion_factor")

    agreement = award.reload()
    assert agreement["status"] == AGREEMENT_HOLD_IN
    assert agreement["cumulative_scheduled_departures"] == 104
