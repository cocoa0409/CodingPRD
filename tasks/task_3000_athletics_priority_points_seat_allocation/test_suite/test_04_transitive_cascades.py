"""Single calls whose effects travel three or four resources deep.

Certifying a cycle restamps ranks, which stales slots, which stales events,
which blocks relocation requests.  Approving a transfer moves points, which
flips seat eligibility, which moves a section's posture and its recommended
price.
"""

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_cents,
    assert_donor_points,
    assert_points,
    assert_ratio,
    validate_success,
)
from test_helpers.constants import (
    BASIS_DEATH,
    DONOR_DECEASED,
    ELIGIBLE,
    EVENT_CLOSED,
    EVENT_SLOTS_STALE,
    NON_ALUMNUS,
    POSTURE_SOFT,
    RELOCATION_AWAITING_SELECTION,
    RELOCATION_BLOCKED,
    REQUEST_UPGRADE,
    SLOT_CONSUMED,
    SLOT_STALE,
    TRANSFER_APPROVED,
    TRANSFER_REQUESTED,
    UNDERWATER,
)
from test_helpers.fixtures import (
    add_received_gift,
    certified_cycle,
    certify_cycle,
    change_status,
    communicate_cycle,
    create_event,
    create_section_with_seats,
    file_relocation_request,
    gate_event,
    invoice_and_pay,
    open_cycle,
    pick_through_event,
    publish_and_open,
    publish_slots,
    read_assignment,
    read_donor,
    read_event,
    read_relocation_request,
    read_section,
    read_slot,
    register_donor,
    request_transfer_ok,
    run_cycle,
    sensitivity,
    set_clock,
    slot_for_donor,
)
from test_helpers.test_users import CERTIFIER


def _certification_cascade_scenario(client):
    """A seated donor whose rank is overtaken a year later by a bigger giver."""
    set_clock(client, f.instant(2026, 4, 1))
    section, seats = create_section_with_seats(
        client,
        [("E", 1), ("E", 2), ("E", 3)],
        seat_capacity=4,
        per_seat_requirement_cents=100000,
        required_points_per_seat=0.00,
    )
    early = register_donor(client, alumni_status=NON_ALUMNUS)
    add_received_gift(client, early["id"], 5000000, f.instant(2026, 3, 1))
    later = register_donor(client, alumni_status=NON_ALUMNUS)

    cycle_2026 = certified_cycle(client, 2026)
    first_event = publish_and_open(
        client, cycle_2026["id"], f.instant(2026, 9, 1), f.instant(2026, 9, 5), 2880
    )
    set_clock(client, f.instant(2026, 9, 1, 12))
    consumed_slot = slot_for_donor(client, first_event["id"], early["id"])
    assignment = pick_through_event(
        client, first_event["id"], seats[0]["id"], early["id"]
    )
    invoice_and_pay(client, assignment["id"])
    gate_event(client, first_event["id"], EVENT_CLOSED)

    second_event = create_event(
        client, cycle_2026["id"], f.instant(2026, 9, 6), f.instant(2026, 9, 12), 2880
    )
    publish_slots(client, second_event["id"])

    request = validate_success(
        file_relocation_request(
            client,
            early["id"],
            assignment["id"],
            section["id"],
            second_event["id"],
            request_type=REQUEST_UPGRADE,
        ),
        expected_status=201,
    )
    assert request["status"] == RELOCATION_AWAITING_SELECTION

    set_clock(client, f.instant(2027, 4, 1))
    add_received_gift(client, later["id"], 10000000, f.instant(2027, 3, 1))
    cycle_2027 = open_cycle(client, 2027)
    run_cycle(client, cycle_2027["id"])
    communicate_cycle(client, cycle_2027["id"])
    certify_cycle(client, cycle_2027["id"])

    return {
        "early": early,
        "later": later,
        "first_event": first_event,
        "second_event": second_event,
        "consumed_slot": consumed_slot,
        "request": request,
    }


class TestCertificationCascade:
    """One certify call reaches ranks, slots, events and relocation requests."""

    def test_certification_restamps_the_whole_ranked_pool(self, client):
        """The bigger 2027 giver takes rank 1 and the incumbent drops to rank 2.

        PRD 3.5: "The pool is ordered on four keys, applied in strict sequence:
        `certified_points` descending, then `cumulative_giving_cents`
        descending, then `consecutive_giving_years` descending, then
        `created_at` ascending."

        Design: Difficulty/transitive_cascade/certify_recalculation_cascades_rank_slot_event_relocation
        """
        scene = _certification_cascade_scenario(client)

        overtaker = read_donor(client, scene["later"]["id"])
        incumbent = read_donor(client, scene["early"]["id"])
        assert_donor_points(overtaker, certified_points="142.50", rank_position=1)
        assert_donor_points(incumbent, certified_points="67.50", rank_position=2)

    def test_a_rank_shift_stales_the_published_slot(self, client):
        """A scheduled slot whose rank_at_publish no longer matches goes STALE.

        PRD 3.5: "Every selection slot still in `SCHEDULED` whose
        `rank_at_publish` no longer equals its donor's freshly assigned
        `rank_position` moves `SCHEDULED → STALE`, and each such slot decrements
        its event's `scheduled_slot_count` and has its own `version` advanced by
        1."

        Design: Difficulty/transitive_cascade/certify_recalculation_cascades_rank_slot_event_relocation
        """
        scene = _certification_cascade_scenario(client)

        slot = slot_for_donor(
            client, scene["second_event"]["id"], scene["early"]["id"]
        )
        assert slot["slot_status"] == SLOT_STALE

    def test_an_event_left_without_a_scheduled_slot_falls_to_slots_stale(self, client):
        """The published count stands while the scheduled count empties out.

        PRD 3.5: "Any selection event that just had at least one slot marked
        `STALE` and that retains no slot in `SCHEDULED` at all is itself moved
        to `SLOTS_STALE`, whether it was sitting in `SLOTS_PUBLISHED` or already
        `OPEN`, with its `version` advanced by 1."

        Design: Difficulty/transitive_cascade/certify_recalculation_cascades_rank_slot_event_relocation
        """
        scene = _certification_cascade_scenario(client)

        staled = read_event(client, scene["second_event"]["id"])
        assert staled["status"] == EVENT_SLOTS_STALE
        assert staled["published_slot_count"] == 2
        assert staled["scheduled_slot_count"] == 0

    def test_the_relocation_request_on_that_event_is_blocked(self, client):
        """The request leaves the pending bucket without being decided.

        PRD 3.5: "Finally, every relocation request in `AWAITING_SELECTION`
        that names one of those newly stale events moves `AWAITING_SELECTION →
        BLOCKED`, records the cascade reason in its `decision_note`, decrements
        its donor's `pending_request_count`, and has its `version` advanced by
        1."

        Design: Difficulty/transitive_cascade/certify_recalculation_cascades_rank_slot_event_relocation
        """
        scene = _certification_cascade_scenario(client)

        blocked = read_relocation_request(client, scene["request"]["id"])
        assert blocked["status"] == RELOCATION_BLOCKED
        assert read_donor(client, scene["early"]["id"])["pending_request_count"] == 0

    def test_a_closed_event_and_its_consumed_slot_are_left_alone(self, client):
        """The cascade only reaches slots that were still SCHEDULED.

        PRD 3.5: "The chain exists so that a rank shift can never let a donor
        pick out of turn: the published order is invalidated wholesale rather
        than partially honoured."

        Design: Difficulty/transitive_cascade/certify_recalculation_cascades_rank_slot_event_relocation
        """
        scene = _certification_cascade_scenario(client)

        assert read_event(client, scene["first_event"]["id"])["status"] == EVENT_CLOSED
        assert (
            read_slot(client, scene["consumed_slot"]["id"])["slot_status"]
            == SLOT_CONSUMED
        )


def _transfer_cascade_scenario(client):
    """A seated donor who gives away enough points to sink her own seat."""
    set_clock(client, f.instant(2026, 4, 1))
    section, seats = create_section_with_seats(
        client,
        [("F", 1), ("F", 2)],
        seat_capacity=2,
        per_seat_requirement_cents=100000,
        required_points_per_seat=50.00,
    )
    source = register_donor(client, alumni_status=NON_ALUMNUS)
    add_received_gift(client, source["id"], 5000000, f.instant(2026, 3, 1))
    recipient = register_donor(client, alumni_status=NON_ALUMNUS)

    cycle = certified_cycle(client, 2026)
    event = publish_and_open(
        client, cycle["id"], f.instant(2026, 9, 1), f.instant(2026, 9, 5), 2880
    )
    set_clock(client, f.instant(2026, 9, 1, 12))
    assignment = pick_through_event(client, event["id"], seats[0]["id"], source["id"])

    change_status(client, source, DONOR_DECEASED, f.instant(2026, 9, 2))
    set_clock(client, f.instant(2026, 9, 3))
    transfer = request_transfer_ok(
        client, source["id"], recipient["id"], BASIS_DEATH, 40.00
    )
    return section, source, recipient, assignment, transfer


class TestTransferApprovalCascade:
    """Approving a transfer reaches points, eligibility, counters and pricing."""

    def test_the_cap_and_the_ceiling_are_computed_at_creation(self, client):
        """A DEATH basis on a deceased donor needs no policy exception.

        PRD 3.6: "When the precondition for the invoked basis holds,
        `exception_required` is false and the transfer is created in
        `REQUESTED`."

        Design: Difficulty/transitive_cascade/approve_transfer_cascades_points_eligibility_section_posture
        """
        _section, _source, _recipient, _assignment, transfer = (
            _transfer_cascade_scenario(client)
        )

        assert transfer["status"] == TRANSFER_REQUESTED
        assert transfer["exception_required"] is False
        assert_points(transfer["transfer_pct_cap"], "1.00", "transfer_pct_cap")
        assert_points(
            transfer["max_transferable_points"], "67.50", "max_transferable_points"
        )

    def test_approval_moves_the_points_and_recomputes_both_balances(self, client):
        """certified_base_points is untouched while certified_points moves.

        PRD 3.6: "On success it adds `points_amount` to the recipient's
        `transferred_points_in` and the same amount to the source's
        `transferred_points_out`, recomputes `certified_points` for both donors,
        and stamps `approved_by_user_id` with the certifier's `X-User-ID`."

        Design: Difficulty/transitive_cascade/approve_transfer_cascades_points_eligibility_section_posture
        """
        _section, source, recipient, _assignment, transfer = (
            _transfer_cascade_scenario(client)
        )

        approved = validate_success(
            client.approve_point_transfer(transfer["id"], headers=CERTIFIER)
        )
        assert approved["status"] == TRANSFER_APPROVED

        giver = read_donor(client, source["id"])
        assert_donor_points(
            giver,
            certified_base_points="67.50",
            transferred_points_out="40.00",
            certified_points="27.50",
        )
        taker = read_donor(client, recipient["id"])
        assert_donor_points(
            taker, transferred_points_in="40.00", certified_points="40.00"
        )

    def test_the_source_donors_own_seat_falls_underwater(self, client):
        """Eligibility is judged against the live figure, not points_at_pick.

        PRD 2.9: "A seat assignment's `eligibility_status` is `UNDERWATER`
        whenever the donor's *current* `certified_points` is below that row's
        `required_points`, and `ELIGIBLE` otherwise — the row's own frozen
        `points_at_pick` records what the donor had at the moment of the pick,
        but eligibility is always judged against the live figure."

        Design: Difficulty/transitive_cascade/approve_transfer_cascades_points_eligibility_section_posture
        """
        _section, _source, _recipient, assignment, transfer = (
            _transfer_cascade_scenario(client)
        )
        assert read_assignment(client, assignment["id"])["eligibility_status"] == ELIGIBLE

        validate_success(client.approve_point_transfer(transfer["id"], headers=CERTIFIER))

        sunk = read_assignment(client, assignment["id"])
        assert sunk["eligibility_status"] == UNDERWATER
        assert_points(sunk["required_points"], "50.00", "required_points")
        assert_points(sunk["points_at_pick"], "67.50", "points_at_pick")

    def test_the_section_posture_turns_soft_on_the_flip(self, client):
        """One underwater seat out of one assigned seat is a ratio of 1.

        PRD 3.7: "The branch order is pinned and `SOFT` is evaluated first and
        wins outright — when the ratio is at least 0.30 the posture is `SOFT`;
        otherwise, when the ratio is exactly zero **and** `seats_available` is
        zero, the posture is `PREMIUM`; otherwise it is `NORMAL`."

        Design: Difficulty/transitive_cascade/approve_transfer_cascades_points_eligibility_section_posture
        """
        section, _source, _recipient, _assignment, transfer = (
            _transfer_cascade_scenario(client)
        )

        validate_success(client.approve_point_transfer(transfer["id"], headers=CERTIFIER))

        moved = read_section(client, section["id"])
        assert moved["underwater_seat_count"] == 1
        assert moved["assigned_seat_count"] == 1
        assert moved["pricing_posture"] == POSTURE_SOFT

    def test_the_sensitivity_read_recommends_the_soft_discount(self, client):
        """A SOFT posture recommends 90% of the current market rate.

        PRD 3.7: "That recommendation is `per_seat_requirement_cents`
        multiplied by 0.90 and rounded half up to whole cents when the posture
        is `SOFT`, multiplied by 1.10 and rounded half up to whole cents when
        the posture is `PREMIUM`, and simply `per_seat_requirement_cents`
        unchanged when the posture is `NORMAL`."

        Design: Difficulty/transitive_cascade/approve_transfer_cascades_points_eligibility_section_posture
        """
        section, _source, _recipient, _assignment, transfer = (
            _transfer_cascade_scenario(client)
        )

        validate_success(client.approve_point_transfer(transfer["id"], headers=CERTIFIER))

        reading = sensitivity(client, section["id"])
        assert_ratio(reading["underwater_ratio"], "1.0000", "underwater_ratio")
        assert reading["pricing_posture"] == POSTURE_SOFT
        assert_cents(
            reading["recommended_requirement_cents"],
            90000,
            "recommended_requirement_cents",
        )
