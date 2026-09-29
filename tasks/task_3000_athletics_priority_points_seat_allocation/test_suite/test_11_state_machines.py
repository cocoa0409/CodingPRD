"""State-machine corner cases: entry states, loops, terminals and cascades.

Every test here drives one declared status axis to a corner the axis itself
defines - an edge that must be admitted, an edge that must not exist, a
terminal state that must lock down, or a single transition whose side effects
must fan out across several entities in the same request.
"""

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_INVALID_STATE,
    ERR_SEAT_DONATION_SHORTFALL,
)
from test_helpers.assertions import (
    assert_donor_points,
    assert_instant,
    assert_object_envelope,
    assert_page_meta,
    assert_points,
    assert_cents,
    assert_seat_inventory,
    validate_error,
    validate_list,
    validate_success,
)
from test_helpers.constants import (
    ATHLETICS_ANNUAL,
    BASIS_DEATH,
    CORPORATION,
    DONOR_ACTIVE,
    DONOR_DECEASED,
    DONOR_DISSOLVED_ENTITY,
    DONOR_LAPSED,
    DONOR_SUSPENDED,
    DISPUTE_SUBMITTED,
    DISPUTE_UNDER_REVIEW,
    ELIGIBLE,
    EVENT_CLOSED,
    EVENT_DRAFT,
    EVENT_OPEN,
    EVENT_POSTSEASON,
    EVENT_SLOTS_PUBLISHED,
    EVENT_SLOTS_STALE,
    GIFT_PLEDGED,
    GIFT_RECEIVED,
    GIFT_REFUNDED,
    NON_ALUMNUS,
    OCCUPANCY_ASSIGNED,
    OCCUPANCY_HELD,
    OCCUPANCY_RELEASED,
    PAYMENT_INVOICED,
    PAYMENT_PAID,
    PAYMENT_UNBILLED,
    POLICY_GRANT,
    POLICY_REFUSE,
    PRICING_MARKET,
    POSTURE_NORMAL,
    POSTURE_PREMIUM,
    RECALC_COMMUNICATED,
    RECALC_DRAFT,
    RELEASE_DONOR_RELEASE,
    RELEASE_NONE,
    RELOCATION_AWAITING_SELECTION,
    RELOCATION_BLOCKED,
    RELOCATION_DENIED,
    RELOCATION_GRANTED,
    REQUEST_UPGRADE,
    SEAT_ASSIGNED,
    SEAT_AVAILABLE,
    SEAT_HELD,
    SLOT_CONSUMED,
    SLOT_FORFEITED,
    SLOT_SCHEDULED,
    SLOT_STALE,
    TRANSFER_DENIED,
    TRANSFER_EXCEPTION_PENDING,
    TRANSFER_REQUESTED,
)
from test_helpers.fixtures import (
    add_gift,
    bill,
    add_received_gift,
    certified_cycle,
    change_status,
    communicated_cycle,
    create_event,
    create_section_with_seats,
    file_dispute,
    file_relocation_request,
    gate_event,
    open_cycle,
    pick_seat_ok,
    publish_and_open,
    publish_slots,
    read_assignment,
    read_cycle,
    read_donor,
    read_event,
    read_relocation_request,
    read_seat,
    read_section,
    read_slot,
    register_donor,
    run_cycle,
    set_clock,
    slot_for_donor,
)
from test_helpers.test_users import (
    ADMIN,
    ANALYST,
    ANALYST_USER_ID,
    CERTIFIER,
    OFFICER,
    POLICY,
    POLICY_USER_ID,
    make_donor_headers,
)

GRANT_NOTE = "The policy committee reviewed the supporting documentation."


def _transfer_row(client, donor_id, transfer_id, headers=OFFICER):
    """Read one transfer back through the donor's transfer collection."""
    rows, _meta = validate_list(
        client.list_donor_point_transfers(
            donor_id, headers=headers, params={"limit": 100}
        )
    )
    matches = [row for row in rows if row["id"] == transfer_id]
    assert len(matches) == 1, "expected transfer {0} in the donor's transfer list, saw {1}".format(
        transfer_id, [row["id"] for row in rows]
    )
    return matches[0]


class TestDonorStatusMachine:
    """The five-valued donor axis, its loop, and its single terminal state."""

    def test_lapsing_stamps_the_supplied_effective_date_not_the_clock(self, client):
        """status_effective_date is the request value, never the logical clock.

        PRD 3.1: "A status change carries `new_status`, an `effective_date`, a
        free-text `reason`, and `expected_donor_version`; on success it writes
        `effective_date` into `status_effective_date` and advances the donor's
        `version` by 1."

        PRD 3.1: "Lapsing a donor moves `ACTIVE → LAPSED` and requires both that
        the donor is currently `ACTIVE` and that `effective_date` is not later
        than the current logical clock instant."

        Design: Corner/state_machines/donor_status_change_active_to_lapsed_stamps_the_effective_date
        """
        donor = register_donor(client, alumni_status=NON_ALUMNUS)
        assert donor["donor_status"] == DONOR_ACTIVE
        assert donor["version"] == 1

        response = client.change_donor_status(
            donor["id"],
            f.status_change_payload(
                DONOR_LAPSED, f.instant(2026, 7, 1), donor["version"]
            ),
            headers=OFFICER,
        )
        assert_object_envelope(response)
        lapsed = validate_success(response)

        assert lapsed["donor_status"] == DONOR_LAPSED
        assert_instant(
            lapsed["status_effective_date"],
            "2026-07-01T00:00:00.000Z",
            "status_effective_date",
        )
        assert lapsed["version"] == 2
        assert_donor_points(
            lapsed,
            certified_base_points="0.00",
            certified_points="0.00",
            cumulative_giving_cents=0,
        )

    def test_the_reactivation_loop_preserves_the_donors_giving(self, client):
        """ACTIVE -> LAPSED -> ACTIVE twice re-stamps and leaves giving intact.

        PRD 3.1: "Reactivation runs the loop back the other way, `LAPSED →
        ACTIVE`, and requires only that the donor is currently `LAPSED`; because
        the alumni bonus is granted for `ACTIVE` and `LAPSED` alike, this round
        trip leaves the donor's scoring unchanged, and a `LAPSED` donor remains
        rankable with `certified_base_points` untouched."

        Design: Corner/state_machines/donor_lapsed_to_active_reactivation_loop_preserves_points
        """
        set_clock(client, f.instant(2026, 4, 1))
        donor = register_donor(client, alumni_status=NON_ALUMNUS)
        add_received_gift(client, donor["id"], 1000000, f.instant(2026, 3, 1))
        assert read_donor(client, donor["id"])["version"] == 2

        # PRD 3.1 admits a lapse only when effective_date is not later than the
        # current logical clock instant, so the clock moves past both dates
        # before the round trip is driven.
        set_clock(client, f.instant(2026, 4, 3))

        lapsed = change_status(client, donor, DONOR_LAPSED, f.instant(2026, 4, 2))
        assert lapsed["donor_status"] == DONOR_LAPSED
        assert lapsed["version"] == 3

        reactivated = change_status(client, donor, DONOR_ACTIVE, f.instant(2026, 4, 3))
        assert reactivated["donor_status"] == DONOR_ACTIVE
        assert_instant(
            reactivated["status_effective_date"],
            "2026-04-03T00:00:00.000Z",
            "status_effective_date",
        )
        assert reactivated["version"] == 4
        assert_donor_points(reactivated, cumulative_giving_cents=1000000)

    def test_no_edge_leaves_deceased_so_a_reversal_attempt_is_a_state_error(self, client):
        """DECEASED -> ACTIVE is a 409, not a 400 and not a silent no-op.

        PRD 3.1: "Death is recorded from either of the two live statuses: `ACTIVE
        → DECEASED` and `LAPSED → DECEASED` both require that the donor is
        currently `ACTIVE` or `LAPSED`."

        PRD 3.1: "A status change whose starting state does not admit the
        requested destination is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/donor_status_change_out_of_deceased_returns_invalid_state
        """
        donor = register_donor(client)
        deceased = change_status(
            client, donor, DONOR_DECEASED, f.instant(2026, 7, 15)
        )
        assert deceased["donor_status"] == DONOR_DECEASED
        assert deceased["version"] == 2

        refused = client.change_donor_status(
            donor["id"],
            f.status_change_payload(
                DONOR_ACTIVE, f.instant(2026, 7, 20), deceased["version"]
            ),
            headers=OFFICER,
        )
        validate_error(refused, ERR_INVALID_STATE, 409)

        after = read_donor(client, donor["id"])
        assert after["donor_status"] == DONOR_DECEASED
        assert_instant(
            after["status_effective_date"],
            "2026-07-15T00:00:00.000Z",
            "status_effective_date",
        )
        assert after["version"] == 2

    def test_dissolved_entity_locks_down_every_further_change(self, client):
        """The sole terminal status refuses reinstatement and suspension alike.

        PRD 3.1: "The `donor_status` axis has five values — `ACTIVE`, `LAPSED`,
        `DECEASED`, `DISSOLVED_ENTITY` and `SUSPENDED` — and one terminal value,
        `DISSOLVED_ENTITY`."

        PRD 3.1: "Suspension is a platform-operator lever: `ACTIVE → SUSPENDED`
        requires the donor to be `ACTIVE` and removes them from every
        selection-event candidate pool, and `SUSPENDED → ACTIVE` requires the
        donor to be `SUSPENDED` and puts them back."

        Design: Corner/state_machines/donor_dissolved_entity_locks_down_every_further_status_change
        """
        donor = register_donor(
            client, alumni_status=NON_ALUMNUS, entity_type=CORPORATION
        )
        dissolved = change_status(
            client, donor, DONOR_DISSOLVED_ENTITY, f.instant(2026, 6, 30)
        )
        assert dissolved["donor_status"] == DONOR_DISSOLVED_ENTITY
        assert dissolved["version"] == 2

        reinstate = client.change_donor_status(
            donor["id"],
            f.status_change_payload(DONOR_ACTIVE, f.instant(2026, 7, 1), 2),
            headers=OFFICER,
        )
        validate_error(reinstate, ERR_INVALID_STATE, 409)

        suspend = client.change_donor_status(
            donor["id"],
            f.status_change_payload(DONOR_SUSPENDED, f.instant(2026, 7, 2), 2),
            headers=ADMIN,
        )
        validate_error(suspend, ERR_INVALID_STATE, 409)

        after = read_donor(client, donor["id"])
        assert after["donor_status"] == DONOR_DISSOLVED_ENTITY
        assert after["version"] == 2
        assert_instant(
            after["status_effective_date"],
            "2026-06-30T00:00:00.000Z",
            "status_effective_date",
        )


def _gift_row(client, donor_id, gift_id, headers=OFFICER):
    """Read one gift back through the donor's gift collection."""
    rows, _meta = validate_list(
        client.list_donor_gifts(donor_id, headers=headers, params={"limit": 100})
    )
    matches = [row for row in rows if row["id"] == gift_id]
    assert len(matches) == 1, "expected gift {0} in the donor's gift list, saw {1}".format(
        gift_id, [row["id"] for row in rows]
    )
    return matches[0]


class TestGiftSettlementMachine:
    """PLEDGED is the entry state and REFUNDED is the terminal one."""

    def test_settling_then_clawing_back_reconciles_giving_to_zero(self, client):
        """1,000,000 cents in and the same 1,000,000 cents out, with no drift.

        PRD 3.2: "Settling `PLEDGED → RECEIVED` requires the gift to be
        `PLEDGED`; it stamps `settled_at` with the current logical clock instant,
        adds `amount_cents` to the donor's `cumulative_giving_cents`, sets
        `counts_toward_points` to true when `designation` is `ATHLETICS_ANNUAL`
        or `CAPITAL`, makes the gift eligible for the CERTIFIED point variant in
        addition to the PROVISIONAL one, and advances both the gift's `version`
        and the donor's `version` by 1."

        PRD 3.2: "Clawing back settled money, `RECEIVED → REFUNDED`, requires
        the gift to be `RECEIVED`; it subtracts `amount_cents` from the donor's
        `cumulative_giving_cents`, sets `counts_toward_points` to false, and
        advances both the gift's `version` and the donor's `version` by 1."

        Design: Corner/state_machines/gift_settlement_then_refund_reconciles_cumulative_giving_to_zero
        """
        set_clock(client, f.instant(2026, 4, 1))
        donor = register_donor(client, alumni_status=NON_ALUMNUS)
        gift = add_gift(
            client,
            donor["id"],
            1000000,
            f.instant(2026, 3, 1),
            designation=ATHLETICS_ANNUAL,
            gift_status=GIFT_PLEDGED,
        )
        assert read_donor(client, donor["id"])["cumulative_giving_cents"] == 0
        # A PLEDGED gift touches nothing on the donor row: PRD 3.2 advances the
        # donor's version only when the gift is recorded already RECEIVED.
        assert read_donor(client, donor["id"])["version"] == 1

        received = validate_success(
            client.settle_gift(
                gift["id"], f.settle_gift_payload(GIFT_RECEIVED), headers=OFFICER
            )
        )
        assert received["gift_status"] == GIFT_RECEIVED
        assert_instant(received["settled_at"], "2026-04-01T00:00:00.000Z", "settled_at")
        assert received["counts_toward_points"] is True
        assert received["version"] == 2

        credited = read_donor(client, donor["id"])
        assert_donor_points(credited, cumulative_giving_cents=1000000)
        assert credited["version"] == 2

        refunded = validate_success(
            client.settle_gift(
                gift["id"], f.settle_gift_payload(GIFT_REFUNDED), headers=OFFICER
            )
        )
        assert refunded["gift_status"] == GIFT_REFUNDED
        assert refunded["counts_toward_points"] is False
        assert refunded["version"] == 3

        reconciled = read_donor(client, donor["id"])
        assert_donor_points(
            reconciled,
            cumulative_giving_cents=0,
            certified_base_points="0.00",
        )
        assert reconciled["version"] == 3

    def test_refunded_is_terminal_and_refuses_re_settlement(self, client):
        """A pledge refunded straight from PLEDGED cannot later be received.

        PRD 3.2: "Settlement drives the gift's own small state machine, whose
        initial state is `PLEDGED` and whose terminal state is `REFUNDED`; the
        call carries only `new_status`."

        PRD 3.2: "Refunding an unsettled pledge, `PLEDGED → REFUNDED`, likewise
        requires the gift to be `PLEDGED`; it stamps `settled_at`, sets
        `counts_toward_points` to false, removes the gift from both the
        PROVISIONAL and the CERTIFIED input set, and advances only the gift's
        `version` by 1 — the donor's cumulative giving never included this money,
        so nothing is subtracted."

        Design: Corner/state_machines/gift_refunded_is_terminal_and_refuses_re_settlement
        """
        donor = register_donor(client, alumni_status=NON_ALUMNUS)
        gift = add_gift(
            client,
            donor["id"],
            750000,
            f.instant(2026, 2, 14),
            designation=ATHLETICS_ANNUAL,
            gift_status=GIFT_PLEDGED,
        )
        validate_success(
            client.settle_gift(
                gift["id"], f.settle_gift_payload(GIFT_REFUNDED), headers=OFFICER
            )
        )

        refused = client.settle_gift(
            gift["id"], f.settle_gift_payload(GIFT_RECEIVED), headers=OFFICER
        )
        validate_error(refused, ERR_INVALID_STATE, 409)

        stored = _gift_row(client, donor["id"], gift["id"])
        assert stored["gift_status"] == GIFT_REFUNDED
        assert stored["version"] == 2
        assert stored["counts_toward_points"] is False
        assert read_donor(client, donor["id"])["cumulative_giving_cents"] == 0


def _communicated_cycle_with_one_donor(client, cycle_year=2026):
    """One 15.00-point donor on a COMMUNICATED cycle, clock inside the window."""
    set_clock(client, f.instant(2026, 4, 1))
    donor = register_donor(client, alumni_status=NON_ALUMNUS)
    add_received_gift(client, donor["id"], 1000000, f.instant(2026, 3, 1))
    cycle = communicated_cycle(client, cycle_year)
    return donor, cycle


class TestRecalculationBackwardEdgeAndItsDisputeGate:
    """The COMMUNICATED -> COMPUTED detour and the wider gate at certification."""

    def test_a_dispute_under_review_freezes_the_re_run(self, client):
        """The backward edge is refused while an analyst holds the dispute.

        PRD 3.4: "From here the cycle can go forward to certification, or it can
        be pulled backwards for a second pass: re-running a communicated cycle
        moves `COMMUNICATED → COMPUTED`, and is admitted only when the
        recalculation is in `COMMUNICATED` **and** no dispute on it is currently
        in `UNDER_REVIEW` or `INFO_REQUESTED`."

        Design: Corner/state_machines/recalculation_recompute_blocked_while_a_dispute_is_under_review
        """
        donor, cycle = _communicated_cycle_with_one_donor(client)
        dispute = file_dispute(client, donor["id"], cycle["id"], 5.00)
        reviewed = validate_success(
            client.review_dispute(dispute["id"], headers=ANALYST)
        )
        assert reviewed["reviewed_by_user_id"] == ANALYST_USER_ID

        refused = client.run_recalculation(cycle["id"], headers=OFFICER)
        validate_error(refused, ERR_INVALID_STATE, 409)

        assert read_cycle(client, cycle["id"])["status"] == RECALC_COMMUNICATED
        held = validate_success(client.get_dispute(dispute["id"], headers=OFFICER))
        assert held["status"] == DISPUTE_UNDER_REVIEW
        assert held["reviewed_by_user_id"] == ANALYST_USER_ID
        assert_donor_points(
            read_donor(client, donor["id"]),
            certified_base_points="15.00",
            certified_points="15.00",
        )

    def test_a_merely_submitted_dispute_blocks_certification(self, client):
        """The certification gate is wider: SUBMITTED is enough to refuse.

        PRD 3.5: "Moving a cycle `COMMUNICATED → CERTIFIED` requires four things
        at once: the recalculation is in `COMMUNICATED`; the supplied
        `expected_recalculation_version` equals the recalculation's current
        `version`; the certifier's `X-User-ID` differs from
        `initiated_by_user_id`; and no dispute on this recalculation remains in
        `SUBMITTED`, `UNDER_REVIEW` or `INFO_REQUESTED`."

        PRD 3.5: "Note that the dispute gate at certification is wider than the
        one on the backward re-run edge — a merely `SUBMITTED` dispute nobody has
        looked at yet blocks certification, even though it does not block a
        re-score."

        Design: Corner/state_machines/certify_blocked_while_a_submitted_dispute_is_outstanding
        """
        donor, cycle = _communicated_cycle_with_one_donor(client)
        dispute = file_dispute(client, donor["id"], cycle["id"], 3.00)

        current = read_cycle(client, cycle["id"], headers=CERTIFIER)
        refused = client.certify_recalculation(
            cycle["id"], f.certify_payload(current["version"]), headers=CERTIFIER
        )
        validate_error(refused, ERR_INVALID_STATE, 409)

        after = read_cycle(client, cycle["id"])
        assert after["status"] == RECALC_COMMUNICATED
        assert after["certified_at"] is None
        assert after["certified_by_user_id"] is None
        assert read_donor(client, donor["id"])["rank_position"] is None
        assert (
            validate_success(client.get_dispute(dispute["id"], headers=OFFICER))["status"]
            == DISPUTE_SUBMITTED
        )


def _one_seat_section_with_a_hold(client):
    """A single 100000-cent seat held by a 15.00-point donor, unbilled."""
    set_clock(client, f.instant(2026, 4, 1))
    section, seats = create_section_with_seats(
        client,
        [("M", 1)],
        seat_capacity=1,
        per_seat_requirement_cents=100000,
        required_points_per_seat=0.00,
    )
    donor = register_donor(client, alumni_status=NON_ALUMNUS)
    add_received_gift(client, donor["id"], 1000000, f.instant(2026, 3, 1))
    cycle = certified_cycle(client, 2026)
    event = publish_and_open(
        client, cycle["id"], f.instant(2026, 9, 1), f.instant(2026, 9, 5), 2880
    )
    slot = slot_for_donor(client, event["id"], donor["id"])

    set_clock(client, f.instant(2026, 9, 1, 12))
    assignment = pick_seat_ok(client, slot["id"], seats[0]["id"], donor["id"])
    return section, seats[0], assignment


class TestOccupancyConfirmationIsGatedOnTheMoney:
    """HELD -> ASSIGNED is the only edge in the catalogue answering 402."""

    def test_the_held_row_is_priced_from_the_section_at_the_pick(self, client):
        """A SEASON_TICKET row costs the market requirement with no fee.

        PRD 3.8: "For a `SEASON_TICKET` event, `handling_fee_cents` is 0 and
        `total_due_cents` equals `requirement_cents`."

        PRD 3.9: "Its hold window is closed at both ends: `hold_start` is the
        current logical clock instant and `hold_end` is 72 hours later — a hold
        lasts 4,320 minutes."

        Design: Corner/state_machines/occupancy_to_assigned_without_full_payment_returns_donation_shortfall
        """
        _section, _seat, assignment = _one_seat_section_with_a_hold(client)

        assert assignment["requirement_cents"] == 100000
        assert assignment["handling_fee_cents"] == 0
        assert assignment["total_due_cents"] == 100000
        assert assignment["pricing_mode"] == PRICING_MARKET
        assert assignment["eligibility_status"] == ELIGIBLE
        assert_instant(assignment["hold_start"], "2026-09-01T12:00:00.000Z", "hold_start")
        assert_instant(assignment["hold_end"], "2026-09-04T12:00:00.000Z", "hold_end")

    def test_confirming_an_unpaid_hold_is_refused_with_payment_required(self, client):
        """An unbilled row owes the whole requirement, so the confirm is a 402.

        PRD 3.9: "Confirming a hold moves the assignment `HELD → ASSIGNED` and
        requires four things: the row is in `HELD`; the version stamp matches;
        `amount_paid_cents` is at least `total_due_cents`; and
        `eligibility_status` is `ELIGIBLE`."

        PRD 3.9: "A row that has not been paid up is refused with
        `ERR_SEAT_DONATION_SHORTFALL`, and a row that has drifted to `UNDERWATER`
        cannot be confirmed at all."

        Design: Corner/state_machines/occupancy_to_assigned_without_full_payment_returns_donation_shortfall
        """
        section, seat, assignment = _one_seat_section_with_a_hold(client)
        assert assignment["version"] == 1

        refused = client.set_occupancy(
            assignment["id"],
            f.occupancy_payload(OCCUPANCY_ASSIGNED, assignment["version"]),
            headers=OFFICER,
        )
        validate_error(refused, ERR_SEAT_DONATION_SHORTFALL, 402)

        after = read_assignment(client, assignment["id"])
        assert after["occupancy_status"] == OCCUPANCY_HELD
        assert after["payment_status"] == PAYMENT_UNBILLED
        assert after["amount_paid_cents"] == 0
        assert after["version"] == 1
        assert read_seat(client, seat["id"])["seat_status"] == SEAT_HELD
        assert read_section(client, section["id"])["assigned_seat_count"] == 1

    def test_paying_exactly_the_total_lets_the_identical_call_through(self, client):
        """The fiscal guard was the only blocker: 100000 cents clears it.

        PRD 3.9: "Paying moves either `INVOICED → PAID` or `DELINQUENT → PAID` —
        both require the row to be in `INVOICED` or `DELINQUENT` and require the
        tendered `amount_cents` to be at least `total_due_cents`, and both set
        `amount_paid_cents` to the tendered `amount_cents`; a short tender is
        refused with `ERR_SEAT_DONATION_SHORTFALL`."

        PRD 3.9: "On success the seat itself moves `HELD → ASSIGNED`, the
        section's `assigned_seat_count` increments, the seat's `version` advances
        by 1, and — if this assignment satisfies an outstanding relocation request
        — that request is set to `GRANTED` with its `granted_seat_assignment_id`
        pointed at this row."

        Design: Corner/state_machines/occupancy_to_assigned_without_full_payment_returns_donation_shortfall
        """
        section, seat, assignment = _one_seat_section_with_a_hold(client)
        client.set_occupancy(
            assignment["id"],
            f.occupancy_payload(OCCUPANCY_ASSIGNED, assignment["version"]),
            headers=OFFICER,
        )

        invoiced = bill(client, assignment["id"], PAYMENT_INVOICED)
        assert invoiced["version"] == 2
        paid = bill(client, assignment["id"], PAYMENT_PAID, amount_cents=100000)
        assert paid["payment_status"] == PAYMENT_PAID
        assert paid["amount_paid_cents"] == 100000
        assert paid["version"] == 3

        confirmed = validate_success(
            client.set_occupancy(
                assignment["id"],
                f.occupancy_payload(OCCUPANCY_ASSIGNED, paid["version"]),
                headers=OFFICER,
            )
        )
        assert confirmed["occupancy_status"] == OCCUPANCY_ASSIGNED
        assert confirmed["version"] == 4
        assert read_seat(client, seat["id"])["seat_status"] == SEAT_ASSIGNED
        assert_seat_inventory(
            read_section(client, section["id"]),
            seats_available=0,
            seats_committed_count=1,
            decommissioned_seat_count=0,
            seat_row_count=1,
        )


class TestASlotIsAOneShotRight:
    """Consuming a slot twice is refused even against a different free seat."""

    def test_the_second_pick_through_one_slot_is_a_state_error(self, client):
        """CONSUMED does not admit a second pick, whatever seat is named.

        PRD 3.7: "It moves the slot `SCHEDULED → CONSUMED` and requires all of
        the following: the slot is in `SCHEDULED`; the caller's `X-User-ID` equals
        the slot's `donor_id`; the parent event is in `OPEN`; the current logical
        clock instant lies inside the slot's half-open window, at or after
        `slot_start` and strictly before `slot_end`; the section holding the
        target seat has `status` `OPEN`; and the target seat is either in
        `seat_status` `AVAILABLE` or already in `HELD` with spare capacity under
        its `max_concurrent_holds`."

        PRD 3.7: "A slot's four states are `SCHEDULED`, `STALE`, `CONSUMED` and
        `FORFEITED`, of which `CONSUMED` and `FORFEITED` are terminal."

        Design: Corner/state_machines/picking_twice_through_one_slot_returns_invalid_state_on_the_second_attempt
        """
        set_clock(client, f.instant(2026, 4, 1))
        section, seats = create_section_with_seats(
            client,
            [("T", 1), ("T", 2)],
            seat_capacity=2,
            per_seat_requirement_cents=100000,
            required_points_per_seat=0.00,
        )
        donor = register_donor(client, alumni_status=NON_ALUMNUS)
        add_received_gift(client, donor["id"], 1000000, f.instant(2026, 3, 1))
        cycle = certified_cycle(client, 2026)
        event = publish_and_open(
            client, cycle["id"], f.instant(2026, 9, 1), f.instant(2026, 9, 5), 2880
        )
        slot = slot_for_donor(client, event["id"], donor["id"])

        set_clock(client, f.instant(2026, 9, 1, 12))
        pick_seat_ok(client, slot["id"], seats[0]["id"], donor["id"])

        second_seat = read_seat(client, seats[1]["id"])
        refused = client.pick_seat(
            slot["id"],
            f.pick_payload(second_seat["id"], second_seat["version"]),
            headers=make_donor_headers(donor["id"]),
        )
        validate_error(refused, ERR_INVALID_STATE, 409)

        assert read_slot(client, slot["id"])["slot_status"] == SLOT_CONSUMED
        untouched = read_seat(client, seats[1]["id"])
        assert untouched["seat_status"] == SEAT_AVAILABLE
        assert untouched["version"] == 1

        rows, meta = validate_list(
            client.list_seat_assignments(
                headers=OFFICER, params={"donor_id": donor["id"]}
            )
        )
        assert len(rows) == 1
        assert_page_meta(meta, total_count=1)

        assert_seat_inventory(
            read_section(client, section["id"]),
            seats_available=1,
            seats_committed_count=1,
            decommissioned_seat_count=0,
            seat_row_count=2,
        )
        after_event = read_event(client, event["id"])
        assert after_event["status"] == EVENT_OPEN
        assert after_event["scheduled_slot_count"] == 0


class TestSelectionEventEntryStateAndItsFirstEdge:
    """An event may be drafted against a DRAFT cycle but cannot skip a state."""

    def test_a_new_event_lands_in_draft_with_defaulted_geometry(self, client):
        """The two optional geometry inputs default to 0, not to null.

        PRD 3.6: "Creating one supplies `event_type`, which is `SEASON_TICKET`,
        `POSTSEASON` or `AWAY_GAME`; `window_start` and `window_end`, the bounds
        of the event's occupation window on its recalculation, where `window_end`
        must be strictly later than `window_start`; `slot_minutes`, the length of
        each donor's individual selection slot, at least 1; an optional
        `slot_buffer_minutes`, the gap inserted between consecutive slots,
        defaulting to 0 and at least 0; and an optional
        `eligible_donor_min_points`, the points floor for inclusion in the
        candidate pool, defaulting to 0, at least 0 and carried to 2 decimal
        places."

        PRD 3.6: "The event's `recalculation_id` comes from the path it was
        created under, never from the body."

        PRD 3.6: "It starts in `DRAFT` with `published_slot_count` and
        `scheduled_slot_count` both zero."

        Design: Corner/state_machines/selection_event_created_starts_in_draft_with_default_slot_geometry
        """
        cycle = open_cycle(client, 2026)
        assert cycle["status"] == RECALC_DRAFT

        response = client.create_selection_event(
            cycle["id"],
            f.selection_event_payload(
                f.instant(2026, 10, 1),
                f.instant(2026, 10, 3),
                60,
                event_type=EVENT_POSTSEASON,
            ),
            headers=OFFICER,
        )
        assert_object_envelope(response)
        event = validate_success(response, 201)

        assert event["status"] == EVENT_DRAFT
        assert event["recalculation_id"] == cycle["id"]
        assert event["slot_buffer_minutes"] == 0
        assert_points(
            event["eligible_donor_min_points"], "0.00", "eligible_donor_min_points"
        )
        assert event["published_slot_count"] == 0
        assert event["scheduled_slot_count"] == 0
        assert event["version"] == 1

        assert read_cycle(client, cycle["id"])["status"] == RECALC_DRAFT
        rows, meta = validate_list(
            client.list_selection_slots(
                headers=OFFICER, params={"selection_event_id": event["id"]}
            )
        )
        assert rows == []
        assert_page_meta(meta, total_count=0)

    def test_opening_a_draft_event_is_refused_before_any_overlap_arithmetic(
        self, client
    ):
        """OPEN is reachable only from SLOTS_PUBLISHED, so DRAFT gating is a 409.

        PRD 3.6: "The event lifecycle is `DRAFT → SLOTS_PUBLISHED → OPEN →
        CLOSED`, with `CLOSED` terminal and a cyclic detour through `SLOTS_STALE`
        described below."

        PRD 3.6: "Opening it moves `SLOTS_PUBLISHED → OPEN`, requires the event
        to be in `SLOTS_PUBLISHED`, and additionally requires that no other event
        on the same recalculation whose status is `SLOTS_PUBLISHED` or `OPEN` has
        a window overlapping this event's window; an interior overlap is rejected
        with `ERR_SELECTION_WINDOW_OVERLAP`, while a shared boundary instant is
        permitted."

        Design: Corner/state_machines/gating_an_event_open_straight_from_draft_returns_invalid_state
        """
        cycle = open_cycle(client, 2026)
        event = create_event(
            client, cycle["id"], f.instant(2026, 9, 1), f.instant(2026, 9, 5), 2880
        )
        assert event["status"] == EVENT_DRAFT

        refused = client.gate_selection_event(
            event["id"], f.gate_payload(EVENT_OPEN), headers=OFFICER
        )
        validate_error(refused, ERR_INVALID_STATE, 409)

        after = read_event(client, event["id"])
        assert after["status"] == EVENT_DRAFT
        assert after["version"] == 1
        assert after["published_slot_count"] == 0


class TestTransferEntryStateForksOnTheBasisPrecondition:
    """The declared initial state is REQUESTED, but the data decides."""

    def test_a_death_basis_against_a_living_donor_forks_to_exception_pending(
        self, client
    ):
        """The fork is a successful 201 creation that moves no points.

        PRD 3.4: "A `DEATH` basis expects the source donor's `donor_status` to be
        `DECEASED`."

        PRD 3.4: "When it does not hold, `exception_required` is true and the
        transfer is created directly in `EXCEPTION_PENDING` — the entry state of
        a brand-new transfer therefore depends on the source donor's own status
        and type, not on anything the requester supplies."

        PRD 3.4: "From it, `max_transferable_points` is computed once, at creation
        time, as the source donor's `certified_points` multiplied by
        `transfer_pct_cap`, rounded half up to 2 decimal places."

        PRD 3.4: "Creation is a development-office or platform-operator act, and
        it advances the source donor's `version` by 1."

        Design: Corner/state_machines/transfer_creation_forks_to_exception_pending_when_the_basis_precondition_fails
        """
        set_clock(client, f.instant(2026, 4, 1))
        source = register_donor(client, alumni_status=NON_ALUMNUS)
        add_received_gift(client, source["id"], 1000000, f.instant(2026, 3, 1))
        recipient = register_donor(client, alumni_status=NON_ALUMNUS)
        cycle = open_cycle(client, 2026)
        run_cycle(client, cycle["id"])

        scored = read_donor(client, source["id"])
        assert scored["donor_status"] == DONOR_ACTIVE
        assert_donor_points(scored, certified_points="15.00", label="source")

        response = client.create_point_transfer(
            f.transfer_payload(
                source["id"], recipient["id"], BASIS_DEATH, 10.00, scored["version"]
            ),
            headers=OFFICER,
        )
        transfer = validate_success(response, 201)

        assert transfer["status"] == TRANSFER_EXCEPTION_PENDING
        assert transfer["exception_required"] is True
        assert_points(transfer["transfer_pct_cap"], "1.00", "transfer_pct_cap")
        assert_points(
            transfer["max_transferable_points"], "15.00", "max_transferable_points"
        )
        assert transfer["exception_granted_by_user_id"] is None
        assert transfer["approved_by_user_id"] is None
        assert transfer["decision_note"] is None
        assert transfer["reversed_at"] is None
        assert transfer["version"] == 1

        after_source = read_donor(client, source["id"])
        assert_donor_points(
            after_source,
            transferred_points_out="0.00",
            certified_points="15.00",
            label="source",
        )
        assert after_source["version"] == 4
        assert_donor_points(
            read_donor(client, recipient["id"]),
            transferred_points_in="0.00",
            certified_points="0.00",
            label="recipient",
        )


def _exception_pending_death_transfer(client):
    """A DEATH-basis transfer forked to EXCEPTION_PENDING by a living source."""
    set_clock(client, f.instant(2026, 4, 1))
    source = register_donor(client, alumni_status=NON_ALUMNUS)
    add_received_gift(client, source["id"], 1000000, f.instant(2026, 3, 1))
    recipient = register_donor(client, alumni_status=NON_ALUMNUS)
    cycle = open_cycle(client, 2026)
    run_cycle(client, cycle["id"])

    scored = read_donor(client, source["id"])
    transfer = validate_success(
        client.create_point_transfer(
            f.transfer_payload(
                source["id"], recipient["id"], BASIS_DEATH, 10.00, scored["version"]
            ),
            headers=OFFICER,
        ),
        201,
    )
    return source, recipient, transfer


class TestPolicyDecisionsOnTheTransferFork:
    """GRANT is an authorisation edge; REFUSE reaches a terminal state."""

    def test_a_grant_returns_the_transfer_to_requested_without_moving_points(
        self, client
    ):
        """The committee unblocks the request; the certifier still has to approve.

        PRD 3.4: "Granting the exception moves `EXCEPTION_PENDING → REQUESTED`,
        requires the transfer to be in `EXCEPTION_PENDING`, stamps
        `exception_granted_by_user_id` with the committee member's `X-User-ID`,
        records the note as `decision_note`, and advances the transfer's `version`
        by 1."

        PRD 3.4: "On success it adds `points_amount` to the recipient's
        `transferred_points_in` and the same amount to the source's
        `transferred_points_out`, recomputes `certified_points` for both donors,
        and stamps `approved_by_user_id` with the certifier's `X-User-ID`."

        Design: Corner/state_machines/policy_grant_returns_an_exception_pending_transfer_to_requested
        """
        source, recipient, transfer = _exception_pending_death_transfer(client)
        assert transfer["status"] == TRANSFER_EXCEPTION_PENDING

        granted = validate_success(
            client.transfer_policy_decision(
                transfer["id"],
                f.transfer_policy_decision_payload(POLICY_GRANT),
                headers=POLICY,
            )
        )

        assert granted["status"] == TRANSFER_REQUESTED
        assert granted["exception_granted_by_user_id"] == POLICY_USER_ID
        assert granted["decision_note"] == GRANT_NOTE
        assert granted["approved_by_user_id"] is None
        assert granted["exception_required"] is True
        assert granted["version"] == 2

        assert_donor_points(
            read_donor(client, source["id"]),
            transferred_points_out="0.00",
            certified_points="15.00",
            label="source",
        )
        assert_donor_points(
            read_donor(client, recipient["id"]),
            transferred_points_in="0.00",
            certified_points="0.00",
            label="recipient",
        )

    def test_a_refused_transfer_is_denied_terminal_and_rejects_a_later_approve(
        self, client
    ):
        """A DECEASED source needs no exception, and DENIED locks the row down.

        PRD 3.4: "When the precondition for the invoked basis holds,
        `exception_required` is false and the transfer is created in `REQUESTED`."

        PRD 3.4: "The committee may also refuse a transfer that never needed an
        exception at all: `REQUESTED → DENIED` requires the transfer to be in
        `REQUESTED`, records `decision_note`, and advances the `version` by 1."

        PRD 3.4: "Attempting approval while the transfer is still in
        `EXCEPTION_PENDING` is not reported as an ordinary state error; it is
        reported specifically as `ERR_TRANSFER_POLICY_EXCEPTION_REQUIRED`, so that
        the caller learns *what* is missing rather than merely that the state is
        wrong."

        Design: Corner/state_machines/refused_transfer_is_denied_terminal_and_rejects_a_later_approve
        """
        refuse_note = "Beneficiary is not an eligible transferee under the policy."
        set_clock(client, f.instant(2026, 4, 1))
        source = register_donor(client, alumni_status=NON_ALUMNUS)
        add_received_gift(client, source["id"], 1000000, f.instant(2026, 3, 1))
        recipient = register_donor(client, alumni_status=NON_ALUMNUS)
        cycle = open_cycle(client, 2026)
        run_cycle(client, cycle["id"])
        change_status(client, source, DONOR_DECEASED, f.instant(2026, 3, 20))

        current = read_donor(client, source["id"])
        transfer = validate_success(
            client.create_point_transfer(
                f.transfer_payload(
                    source["id"],
                    recipient["id"],
                    BASIS_DEATH,
                    10.00,
                    current["version"],
                ),
                headers=OFFICER,
            ),
            201,
        )
        assert transfer["status"] == TRANSFER_REQUESTED
        assert transfer["exception_required"] is False
        assert_points(transfer["transfer_pct_cap"], "1.00", "transfer_pct_cap")
        assert_points(
            transfer["max_transferable_points"], "15.00", "max_transferable_points"
        )

        denied = validate_success(
            client.transfer_policy_decision(
                transfer["id"],
                f.transfer_policy_decision_payload(POLICY_REFUSE, note=refuse_note),
                headers=POLICY,
            )
        )
        assert denied["status"] == TRANSFER_DENIED
        assert denied["decision_note"] == refuse_note
        assert denied["version"] == 2

        refused = client.approve_point_transfer(transfer["id"], headers=CERTIFIER)
        validate_error(refused, ERR_INVALID_STATE, 409)

        stored = _transfer_row(client, source["id"], transfer["id"])
        assert stored["status"] == TRANSFER_DENIED
        assert stored["version"] == 2
        assert stored["approved_by_user_id"] is None

        assert_donor_points(
            read_donor(client, source["id"]),
            transferred_points_out="0.00",
            certified_points="15.00",
            label="source",
        )
        assert_donor_points(
            read_donor(client, recipient["id"]),
            transferred_points_in="0.00",
            certified_points="0.00",
            label="recipient",
        )


def _staled_event_with_a_blocked_upgrade_request(client):
    """Certify a second cycle so a rank flip stales an OPEN event's schedule."""
    set_clock(client, f.instant(2026, 4, 1))
    _section_r, seats_r = create_section_with_seats(
        client,
        [("R", 1)],
        seat_capacity=2,
        per_seat_requirement_cents=100000,
        required_points_per_seat=0.00,
    )
    section_s, _seats_s = create_section_with_seats(
        client,
        [("S", 1)],
        seat_capacity=1,
        per_seat_requirement_cents=200000,
        required_points_per_seat=0.00,
    )
    donor_a = register_donor(client, alumni_status=NON_ALUMNUS)
    add_received_gift(client, donor_a["id"], 2000000, f.instant(2026, 3, 1))
    donor_b = register_donor(client, alumni_status=NON_ALUMNUS)
    add_received_gift(client, donor_b["id"], 1000000, f.instant(2026, 3, 1))

    cycle_2026 = certified_cycle(client, 2026)
    event = publish_and_open(
        client, cycle_2026["id"], f.instant(2026, 9, 1), f.instant(2026, 9, 5), 2880
    )
    slot_a = slot_for_donor(client, event["id"], donor_a["id"])
    slot_b = slot_for_donor(client, event["id"], donor_b["id"])

    set_clock(client, f.instant(2026, 9, 1, 12))
    assignment = pick_seat_ok(client, slot_a["id"], seats_r[0]["id"], donor_a["id"])
    bill(client, assignment["id"], PAYMENT_INVOICED)
    bill(client, assignment["id"], PAYMENT_PAID, amount_cents=100000)
    request = validate_success(
        file_relocation_request(
            client,
            donor_a["id"],
            assignment["id"],
            section_s["id"],
            event["id"],
            request_type=REQUEST_UPGRADE,
        ),
        201,
    )

    add_received_gift(client, donor_b["id"], 6000000, f.instant(2026, 5, 1))
    certified_cycle(client, 2027)

    return {
        "donor_a": donor_a,
        "donor_b": donor_b,
        "event": event,
        "slot_a": slot_a,
        "slot_b": slot_b,
        "assignment": assignment,
        "request": request,
    }


def _slots(client, event_id, **params):
    """The slot rows and page meta for one event under arbitrary filters."""
    params["selection_event_id"] = event_id
    params.setdefault("limit", 100)
    return validate_list(client.list_selection_slots(headers=OFFICER, params=params))


class TestRepublicationIsTheRecoveryEdge:
    """SLOTS_PUBLISHED -> SLOTS_STALE -> SLOTS_PUBLISHED is a genuine loop."""

    def test_certifying_the_next_cycle_stales_the_open_event(self, client):
        """The rank flip invalidates the SCHEDULED slot and blocks the request.

        PRD 3.5: "Every selection slot still in `SCHEDULED` whose
        `rank_at_publish` no longer equals its donor's freshly assigned
        `rank_position` moves `SCHEDULED → STALE`, and each such slot decrements
        its event's `scheduled_slot_count` and has its own `version` advanced by
        1."

        PRD 3.5: "Any selection event that just had at least one slot marked
        `STALE` and that retains no slot in `SCHEDULED` at all is itself moved to
        `SLOTS_STALE`, whether it was sitting in `SLOTS_PUBLISHED` or already
        `OPEN`, with its `version` advanced by 1."

        PRD 3.5: "Finally, every relocation request in `AWAITING_SELECTION` that
        names one of those newly stale events moves `AWAITING_SELECTION →
        BLOCKED`, records the cascade reason in its `decision_note`, decrements
        its donor's `pending_request_count`, and has its `version` advanced by 1."

        Design: Corner/state_machines/republishing_a_stale_event_returns_blocked_relocation_requests_to_awaiting
        """
        state = _staled_event_with_a_blocked_upgrade_request(client)

        risen = read_donor(client, state["donor_b"]["id"])
        assert_donor_points(risen, certified_points="97.50", label="donor B")
        assert risen["rank_position"] == 1
        fallen = read_donor(client, state["donor_a"]["id"])
        assert_donor_points(fallen, certified_points="25.00", label="donor A")
        assert fallen["rank_position"] == 2
        assert fallen["pending_request_count"] == 0

        assert read_slot(client, state["slot_b"]["id"])["slot_status"] == SLOT_STALE
        assert read_slot(client, state["slot_a"]["id"])["slot_status"] == SLOT_CONSUMED

        staled = read_event(client, state["event"]["id"])
        assert staled["status"] == EVENT_SLOTS_STALE
        assert staled["scheduled_slot_count"] == 0

        blocked = read_relocation_request(client, state["request"]["id"])
        assert blocked["status"] == RELOCATION_BLOCKED

    def test_republication_lays_a_fresh_generation_in_the_new_rank_order(self, client):
        """The stale generation is discarded and the consumed slot survives.

        PRD 3.6: "When an event has fallen to `SLOTS_STALE`, publishing again
        moves `SLOTS_STALE → SLOTS_PUBLISHED`, discards the `STALE` slots, and
        lays down a fresh generation from the current ranking under the same
        preconditions as a first publication."

        PRD 3.6: "Taking the ranked pool in order with a zero-based counter, each
        donor's `slot_index` is their position in that order; their `slot_start`
        is `window_start` advanced by the counter multiplied by the sum of
        `slot_minutes` and `slot_buffer_minutes`, expressed in minutes; and their
        `slot_end` is their `slot_start` advanced by `slot_minutes`."

        Design: Corner/state_machines/republishing_a_stale_event_returns_blocked_relocation_requests_to_awaiting
        """
        state = _staled_event_with_a_blocked_upgrade_request(client)
        event_id = state["event"]["id"]

        republished = validate_success(
            client.publish_slots(event_id, headers=OFFICER)
        )
        assert republished["status"] == EVENT_SLOTS_PUBLISHED
        assert republished["published_slot_count"] == 2
        assert republished["scheduled_slot_count"] == 2

        _stale_rows, stale_meta = _slots(client, event_id, slot_status=SLOT_STALE)
        assert_page_meta(stale_meta, total_count=0)
        consumed_rows, consumed_meta = _slots(
            client, event_id, slot_status=SLOT_CONSUMED
        )
        assert_page_meta(consumed_meta, total_count=1)
        assert consumed_rows[0]["id"] == state["slot_a"]["id"]
        _all_rows, all_meta = _slots(client, event_id)
        assert_page_meta(all_meta, total_count=3)

        first_rows, _meta = _slots(
            client,
            event_id,
            donor_id=state["donor_b"]["id"],
            slot_status=SLOT_SCHEDULED,
        )
        assert len(first_rows) == 1
        assert first_rows[0]["slot_index"] == 0
        assert first_rows[0]["rank_at_publish"] == 1
        assert_instant(first_rows[0]["slot_start"], "2026-09-01T00:00:00.000Z")
        assert_instant(first_rows[0]["slot_end"], "2026-09-03T00:00:00.000Z")

        second_rows, _meta = _slots(
            client,
            event_id,
            donor_id=state["donor_a"]["id"],
            slot_status=SLOT_SCHEDULED,
        )
        assert len(second_rows) == 1
        assert second_rows[0]["slot_index"] == 1
        assert second_rows[0]["rank_at_publish"] == 2
        assert_instant(second_rows[0]["slot_start"], "2026-09-03T00:00:00.000Z")
        assert_instant(second_rows[0]["slot_end"], "2026-09-05T00:00:00.000Z")

    def test_republication_lifts_the_blocked_request_and_leaves_the_seat_alone(
        self, client
    ):
        """The recovery edge repairs what the cascade broke, and nothing else.

        PRD 3.6: "It also repairs what the staleness cascade broke: every
        relocation request on this event sitting in `BLOCKED` moves `BLOCKED →
        AWAITING_SELECTION`, its donor's `pending_request_count` is incremented
        again, and its `version` advances by 1."

        Design: Corner/state_machines/republishing_a_stale_event_returns_blocked_relocation_requests_to_awaiting
        """
        state = _staled_event_with_a_blocked_upgrade_request(client)
        publish_slots(client, state["event"]["id"])

        restored = read_relocation_request(client, state["request"]["id"])
        assert restored["status"] == RELOCATION_AWAITING_SELECTION
        assert (
            read_donor(client, state["donor_a"]["id"])["pending_request_count"] == 1
        )

        untouched = read_assignment(client, state["assignment"]["id"])
        assert untouched["occupancy_status"] == OCCUPANCY_HELD
        assert untouched["payment_status"] == PAYMENT_PAID


def _two_adjacent_events_and_a_pending_request(client, open_second_event):
    """One seated donor, a second abutting event, and an UPGRADE naming it."""
    set_clock(client, f.instant(2026, 4, 1))
    section_k, seats_k = create_section_with_seats(
        client,
        [("K", 1), ("K", 2)],
        seat_capacity=2,
        per_seat_requirement_cents=100000,
        required_points_per_seat=0.00,
    )
    section_l, seats_l = create_section_with_seats(
        client,
        [("L", 1)],
        seat_capacity=1,
        per_seat_requirement_cents=200000,
        required_points_per_seat=0.00,
    )
    donor = register_donor(client, alumni_status=NON_ALUMNUS)
    add_received_gift(client, donor["id"], 1000000, f.instant(2026, 3, 1))
    cycle = certified_cycle(client, 2026)

    first_event = publish_and_open(
        client, cycle["id"], f.instant(2026, 9, 1), f.instant(2026, 9, 5), 2880
    )
    first_slot = slot_for_donor(client, first_event["id"], donor["id"])

    set_clock(client, f.instant(2026, 9, 1, 12))
    assignment = pick_seat_ok(
        client, first_slot["id"], seats_k[0]["id"], donor["id"]
    )
    bill(client, assignment["id"], PAYMENT_INVOICED)
    bill(client, assignment["id"], PAYMENT_PAID, amount_cents=100000)

    second_event = create_event(
        client, cycle["id"], f.instant(2026, 9, 5), f.instant(2026, 9, 9), 2880
    )
    publish_slots(client, second_event["id"])
    if open_second_event:
        gate_event(client, second_event["id"], EVENT_OPEN)
    second_slot = slot_for_donor(client, second_event["id"], donor["id"])

    # SEC-L carries the higher per-seat requirement, so PRD 3.9 types the move
    # as an UPGRADE rather than a lateral RELOCATION.
    request = validate_success(
        file_relocation_request(
            client,
            donor["id"],
            assignment["id"],
            section_l["id"],
            second_event["id"],
            request_type=REQUEST_UPGRADE,
        ),
        201,
    )
    return {
        "donor": donor,
        "section_k": section_k,
        "section_l": section_l,
        "seat_k1": seats_k[0],
        "seat_l1": seats_l[0],
        "first_event": first_event,
        "first_slot": first_slot,
        "second_event": second_event,
        "second_slot": second_slot,
        "assignment": assignment,
        "request": request,
    }


class TestClosingAnEventFansOutToTwoChildTypes:
    """One gate CLOSED forfeits slots and denies requests in one transaction."""

    def test_closing_forfeits_the_scheduled_slot_and_denies_the_request(self, client):
        """The fan-out reaches both child types and stops the schedule dead.

        PRD 3.6: "Closing it moves `OPEN → CLOSED` and requires the event to be
        in `OPEN`; it moves every slot still in `SCHEDULED` to `FORFEITED` and
        denies every outstanding relocation request on the event."

        Design: Corner/state_machines/gating_an_event_closed_forfeits_scheduled_slots_and_denies_outstanding_requests
        """
        state = _two_adjacent_events_and_a_pending_request(client, True)
        second = read_event(client, state["second_event"]["id"])
        assert second["status"] == EVENT_OPEN
        assert second["published_slot_count"] == 1
        assert second["scheduled_slot_count"] == 1
        assert (
            read_slot(client, state["second_slot"]["id"])["slot_status"]
            == SLOT_SCHEDULED
        )
        assert (
            read_relocation_request(client, state["request"]["id"])["status"]
            == RELOCATION_AWAITING_SELECTION
        )
        assert read_donor(client, state["donor"]["id"])["pending_request_count"] == 1

        closed = gate_event(client, state["second_event"]["id"], EVENT_CLOSED)
        assert closed["status"] == EVENT_CLOSED
        assert closed["scheduled_slot_count"] == 0
        assert closed["published_slot_count"] == 1

        assert (
            read_slot(client, state["second_slot"]["id"])["slot_status"]
            == SLOT_FORFEITED
        )
        denied = read_relocation_request(client, state["request"]["id"])
        assert denied["status"] == RELOCATION_DENIED
        assert isinstance(denied["decision_note"], str)
        assert denied["decision_note"] != ""
        assert denied["granted_seat_assignment_id"] is None
        assert denied["version"] == 2

    def test_the_fan_out_is_scoped_to_the_event_that_was_closed(self, client):
        """The sibling event, its consumed slot and the seated row are untouched.

        PRD 2.5: "`seat_row_count` is the number of seat rows in the section;
        `seats_available` counts those whose `seat_status` is `AVAILABLE`;
        `seats_committed_count` counts those whose `seat_status` is either `HELD`
        or `ASSIGNED`; and `decommissioned_seat_count` counts those whose
        `seat_status` is `DECOMMISSIONED`."

        Design: Corner/state_machines/gating_an_event_closed_forfeits_scheduled_slots_and_denies_outstanding_requests
        """
        state = _two_adjacent_events_and_a_pending_request(client, True)
        gate_event(client, state["second_event"]["id"], EVENT_CLOSED)

        assert read_event(client, state["first_event"]["id"])["status"] == EVENT_OPEN
        assert (
            read_slot(client, state["first_slot"]["id"])["slot_status"] == SLOT_CONSUMED
        )

        kept = read_assignment(client, state["assignment"]["id"])
        assert kept["occupancy_status"] == OCCUPANCY_HELD
        assert kept["payment_status"] == PAYMENT_PAID
        assert kept["amount_paid_cents"] == 100000

        assert read_seat(client, state["seat_k1"]["id"])["seat_status"] == SEAT_HELD
        assert_seat_inventory(
            read_section(client, state["section_k"]["id"]),
            seats_available=1,
            seats_committed_count=1,
            decommissioned_seat_count=0,
            seat_row_count=2,
            label="SEC-K",
        )
        assert read_seat(client, state["seat_l1"]["id"])["seat_status"] == SEAT_AVAILABLE
        assert_seat_inventory(
            read_section(client, state["section_l"]["id"]),
            seats_available=1,
            seats_committed_count=0,
            decommissioned_seat_count=0,
            seat_row_count=1,
            label="SEC-L",
        )


GRANT_DECISION_NOTE = "Upgrade to SEC-L approved on point standing"


def _upgrade_request_on_a_published_event(client):
    """A seated donor with an AWAITING_SELECTION UPGRADE request onto SEC-L."""
    state = _two_adjacent_events_and_a_pending_request(client, False)
    request = state["request"]
    assert request["status"] == RELOCATION_AWAITING_SELECTION
    return state


def _grant(client, state):
    return validate_success(
        client.decide_relocation_request(
            state["request"]["id"],
            f.relocation_decision_payload(
                POLICY_GRANT,
                target_seat_id=state["seat_l1"]["id"],
                decision_note=GRANT_DECISION_NOTE,
            ),
            headers=OFFICER,
        )
    )


class TestGrantingARelocationIsAFourEntitySwap:
    """One decide GRANT mints, releases, forfeits and reprices in one hop."""

    def test_the_grant_mints_a_market_priced_row_with_no_consuming_slot(self, client):
        """The new row pays SEC-L's market rate and records no slot.

        PRD 3.9: "On success a new seat assignment is created on the target seat
        with `pricing_mode` `MARKET` — a relocation always pays the market rate,
        never a grandfathered one — and with `selection_slot_id` left null
        because no slot was consumed; `granted_seat_assignment_id` is pointed at
        the new row; the assignment named by `current_seat_assignment_id` is
        released with `release_reason` `DONOR_RELEASE`; the donor's
        `pending_request_count` decrements; and the request's `version` advances
        by 1."

        Design: Corner/state_machines/granting_a_relocation_mints_a_market_priced_row_and_releases_the_prior_seat
        """
        state = _upgrade_request_on_a_published_event(client)

        granted = _grant(client, state)
        assert granted["status"] == RELOCATION_GRANTED
        assert granted["version"] == 2
        assert granted["request_type"] == REQUEST_UPGRADE
        new_assignment_id = granted["granted_seat_assignment_id"]
        assert new_assignment_id is not None

        minted = read_assignment(client, new_assignment_id)
        assert minted["seat_id"] == state["seat_l1"]["id"]
        assert minted["donor_id"] == state["donor"]["id"]
        assert minted["selection_slot_id"] is None
        assert minted["pricing_mode"] == PRICING_MARKET
        assert minted["version"] == 1

    def test_the_minted_row_prices_off_the_target_sections_market_rate(self, client):
        """SEC-L's 200000 cents flows through with no handling fee.

        PRD 3.9: "Under `MARKET` pricing, `requirement_cents` is simply the
        section's current `per_seat_requirement_cents`, with no escalator and no
        ceiling."

        Design: Corner/state_machines/granting_a_relocation_mints_a_market_priced_row_and_releases_the_prior_seat
        """
        state = _upgrade_request_on_a_published_event(client)
        granted = _grant(client, state)
        minted = read_assignment(client, granted["granted_seat_assignment_id"])

        assert minted["first_occupied_cycle_year"] == 2026
        assert_cents(
            minted["grandfathered_requirement_cents"],
            200000,
            "grandfathered_requirement_cents",
        )
        assert_cents(minted["requirement_cents"], 200000, "requirement_cents")
        assert_cents(minted["handling_fee_cents"], 0, "handling_fee_cents")
        assert_cents(minted["total_due_cents"], 200000, "total_due_cents")
        assert_cents(minted["amount_paid_cents"], 0, "amount_paid_cents")

    def test_the_minted_row_opens_as_an_unbilled_hold_on_the_clock(self, client):
        """It is a fresh hold: HELD, UNBILLED, ELIGIBLE, 72 hours long.

        PRD 3.9: "The row starts with `occupancy_status` `HELD` and
        `payment_status` `UNBILLED`, `amount_paid_cents` at 0,
        `eligibility_status` `ELIGIBLE` and `release_reason` `NONE`."

        Design: Corner/state_machines/granting_a_relocation_mints_a_market_priced_row_and_releases_the_prior_seat
        """
        state = _upgrade_request_on_a_published_event(client)
        granted = _grant(client, state)
        minted = read_assignment(client, granted["granted_seat_assignment_id"])

        assert minted["occupancy_status"] == OCCUPANCY_HELD
        assert minted["payment_status"] == PAYMENT_UNBILLED
        assert minted["release_reason"] == RELEASE_NONE
        assert minted["eligibility_status"] == ELIGIBLE
        assert_points(minted["required_points"], "0.00", "required_points")
        assert_points(minted["points_at_pick"], "15.00", "points_at_pick")
        assert_instant(minted["hold_start"], "2026-09-01T12:00:00.000Z", "hold_start")
        assert_instant(minted["hold_end"], "2026-09-04T12:00:00.000Z", "hold_end")

    def test_the_prior_row_is_released_and_its_consumed_slot_walks_back(self, client):
        """The vacated row keeps its payment history and its slot is forfeited.

        PRD 3.9: "That last step is worth dwelling on: `CONSUMED` looks terminal
        but is not a lockdown state, and a release moves the slot to the *other*
        terminal state rather than restoring the donor's turn."

        Design: Corner/state_machines/granting_a_relocation_mints_a_market_priced_row_and_releases_the_prior_seat
        """
        state = _upgrade_request_on_a_published_event(client)
        _grant(client, state)

        vacated = read_assignment(client, state["assignment"]["id"])
        assert vacated["occupancy_status"] == OCCUPANCY_RELEASED
        assert vacated["release_reason"] == RELEASE_DONOR_RELEASE
        assert vacated["payment_status"] == PAYMENT_PAID
        assert_cents(vacated["amount_paid_cents"], 100000, "amount_paid_cents")
        assert vacated["version"] == 4

        assert (
            read_slot(client, state["first_slot"]["id"])["slot_status"] == SLOT_FORFEITED
        )
        assert read_seat(client, state["seat_k1"]["id"])["seat_status"] == SEAT_AVAILABLE
        assert read_seat(client, state["seat_l1"]["id"])["seat_status"] == SEAT_HELD

    def test_both_sections_repost_their_posture_after_the_swap(self, client):
        """SEC-K empties to NORMAL while the now-full SEC-L reaches PREMIUM.

        PRD 2.9: "The branch order is pinned and `SOFT` is evaluated first and
        wins outright — when the ratio is at least 0.30 the posture is `SOFT`;
        otherwise, when the ratio is exactly zero **and** `seats_available` is
        zero, the posture is `PREMIUM`; otherwise it is `NORMAL`."

        Design: Corner/state_machines/granting_a_relocation_mints_a_market_priced_row_and_releases_the_prior_seat
        """
        state = _upgrade_request_on_a_published_event(client)
        _grant(client, state)

        vacated_section = read_section(client, state["section_k"]["id"])
        assert_seat_inventory(
            vacated_section,
            seats_available=2,
            seats_committed_count=0,
            decommissioned_seat_count=0,
            assigned_seat_count=0,
            underwater_seat_count=0,
            seat_row_count=2,
            label="SEC-K",
        )
        assert vacated_section["pricing_posture"] == POSTURE_NORMAL

        target_section = read_section(client, state["section_l"]["id"])
        assert_seat_inventory(
            target_section,
            seats_available=0,
            seats_committed_count=1,
            decommissioned_seat_count=0,
            assigned_seat_count=1,
            underwater_seat_count=0,
            seat_row_count=1,
            label="SEC-L",
        )
        assert target_section["pricing_posture"] == POSTURE_PREMIUM

    def test_the_donor_leaves_the_pending_bucket_and_keeps_both_rows(self, client):
        """pending_request_count returns to 0 and the donor has two rows on file.

        PRD 2.9: "Because `pending_request_count` is simply the number of the
        donor's requests currently in `AWAITING_SELECTION`, a donor's *first*
        request increments it while a *replacement* leaves it unchanged — the old
        row leaves the bucket exactly as the new one enters it."

        Design: Corner/state_machines/granting_a_relocation_mints_a_market_priced_row_and_releases_the_prior_seat
        """
        state = _upgrade_request_on_a_published_event(client)
        assert read_donor(client, state["donor"]["id"])["pending_request_count"] == 1

        _grant(client, state)

        assert read_donor(client, state["donor"]["id"])["pending_request_count"] == 0
        rows, meta = validate_list(
            client.list_seat_assignments(
                headers=OFFICER, params={"donor_id": state["donor"]["id"]}
            )
        )
        assert_page_meta(meta, total_count=2)
        assert len(rows) == 2
