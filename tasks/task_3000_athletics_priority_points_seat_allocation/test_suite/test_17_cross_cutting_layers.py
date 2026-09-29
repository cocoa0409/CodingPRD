"""Optimistic concurrency and cascades, exercised across whole request chains.

The two version stamps that matter most are the ones section 2.5 singles out:
creating a relocation request and picking a seat, because in both cases no state
precondition would reject the second writer. Each chain below therefore runs the
same body three times - it succeeds, it fails on a spent stamp, and it succeeds
again on a re-read stamp - so a 412 can only be an optimistic-concurrency
verdict and never a disguised state gate. The last chain follows one operator
request as it rewrites a section, its seat inventory and the money axis of a row
that had already been settled.
"""

from test_helpers import factories as f
from test_helpers.api_errors import ERR_STALE_VERSION
from test_helpers.assertions import (
    assert_cents,
    assert_instant,
    assert_points,
    assert_seat_inventory,
    assert_ratio,
    validate_error,
    validate_list,
    validate_success,
)
from test_helpers.constants import (
    ACTION_COMPLETE,
    ATHLETICS_ANNUAL,
    DONOR_ACTIVE,
    DONOR_LAPSED,
    ELIGIBLE,
    GIFT_PLEDGED,
    GIFT_RECEIVED,
    INDIVIDUAL,
    NON_ALUMNUS,
    OCCUPANCY_ASSIGNED,
    OCCUPANCY_HELD,
    PAYMENT_INVOICED,
    PAYMENT_PAID,
    PAYMENT_UNBILLED,
    POSTURE_PREMIUM,
    PRICING_MARKET,
    RELEASE_NONE,
    RELOCATION_AWAITING_SELECTION,
    RELOCATION_SUPERSEDED,
    RENOVATION_COMPLETED,
    RENOVATION_REPRICED,
    RENOVATION_RESEATING,
    REQUEST_RELOCATION,
    REQUEST_UPGRADE,
    SEAT_ASSIGNED,
    SEAT_AVAILABLE,
    SEAT_HELD,
    SECTION_OPEN,
    SECTION_UNDER_RENOVATION,
    SLOT_SCHEDULED,
)
from test_helpers.fixtures import (
    add_gift,
    add_received_gift,
    certified_cycle,
    create_section_with_seats,
    open_cycle,
    publish_and_open,
    read_assignment,
    read_donor,
    read_relocation_request,
    read_seat,
    read_section,
    read_slot,
    register_donor,
    renew_season,
    renovation_action,
    reprice_renovation,
    run_cycle,
    seated_donor,
    sensitivity,
    set_clock,
    slot_for_donor,
    start_reseating,
    survey_section,
)
from test_helpers.test_users import OFFICER, make_donor_headers

CLOCK_SETUP = f.instant(2026, 4, 1)
GIFT_INSTANT = f.instant(2026, 3, 1)
WINDOW_START = f.instant(2026, 9, 1)
WINDOW_END_ONE_SLOT = f.instant(2026, 9, 2)
WINDOW_END_TWO_SLOTS = f.instant(2026, 9, 3)
SLOT_MINUTES = 1440
FIRST_PICK_INSTANT = f.instant(2026, 9, 1, 6)
SECOND_PICK_INSTANT = f.instant(2026, 9, 2, 6)
FIRST_HOLD_END = f.instant(2026, 9, 4, 6)
SECOND_HOLD_END = f.instant(2026, 9, 5, 6)


def _a_seated_donor_and_a_target_section(client):
    """A fully paid ASSIGNED row, plus a second OPEN section to ask for.

    Nothing here stands between the donor and a relocation request: the event is
    OPEN, the clock is inside the donor's slot, and the current assignment is
    paid in full, so the only thing left that can refuse the create is the
    donor's version stamp.
    """
    set_clock(client, CLOCK_SETUP)
    source, source_seats = create_section_with_seats(
        client,
        [("P", 1)],
        seat_capacity=1,
        per_seat_requirement_cents=100000,
        required_points_per_seat=0.00,
        venue_code="STADIUM-P",
    )
    target, _target_seats = create_section_with_seats(
        client,
        [("Q", 1)],
        seat_capacity=1,
        per_seat_requirement_cents=100000,
        required_points_per_seat=0.00,
        venue_code="STADIUM-Q",
    )
    donor = register_donor(
        client, alumni_status=NON_ALUMNUS, entity_type=INDIVIDUAL
    )
    add_received_gift(
        client,
        donor["id"],
        1000000,
        GIFT_INSTANT,
        designation=ATHLETICS_ANNUAL,
    )
    cycle = certified_cycle(client, 2026)
    event = publish_and_open(
        client, cycle["id"], WINDOW_START, WINDOW_END_ONE_SLOT, SLOT_MINUTES
    )
    set_clock(client, FIRST_PICK_INSTANT)
    assignment = seated_donor(
        client, event["id"], source_seats[0]["id"], donor["id"]
    )
    return donor, source, target, event, assignment


def _file_request(client, donor, assignment, target, event, donor_version, **overrides):
    """File a relocation request under the donor's own headers."""
    payload = f.relocation_request_payload(
        donor["id"],
        assignment["id"],
        target["id"],
        event["id"],
        donor_version,
        **overrides
    )
    return client.create_relocation_request(
        payload, headers=make_donor_headers(donor["id"])
    )


def _requests_for(client, donor):
    """Every relocation request on file for this donor, newest ordering aside."""
    response = client.list_relocation_requests(
        headers=OFFICER, params={"donor_id": donor["id"], "limit": 100}
    )
    return validate_list(response)


def _one_seat_and_two_ranked_donors(client):
    """One seat that admits two simultaneous holds, and two ranked pickers.

    ``max_concurrent_holds`` is 2 so that the second pick is genuinely allowed:
    a refusal can then only be the version stamp, never seat availability and
    never a hold conflict.
    """
    set_clock(client, CLOCK_SETUP)
    section, seats = create_section_with_seats(
        client,
        [("R", 1, {"max_concurrent_holds": 2})],
        seat_capacity=1,
        per_seat_requirement_cents=100000,
        required_points_per_seat=0.00,
        venue_code="STADIUM-R",
    )
    high = register_donor(
        client, alumni_status=NON_ALUMNUS, entity_type=INDIVIDUAL
    )
    add_received_gift(
        client, high["id"], 2000000, GIFT_INSTANT, designation=ATHLETICS_ANNUAL
    )
    low = register_donor(
        client, alumni_status=NON_ALUMNUS, entity_type=INDIVIDUAL
    )
    add_received_gift(
        client, low["id"], 1000000, GIFT_INSTANT, designation=ATHLETICS_ANNUAL
    )
    cycle = certified_cycle(client, 2026)
    event = publish_and_open(
        client, cycle["id"], WINDOW_START, WINDOW_END_TWO_SLOTS, SLOT_MINUTES
    )
    return section, seats[0], high, low, event


def _pick(client, slot_id, seat_id, donor_id, seat_version):
    """Consume a slot for a seat, echoing exactly the version handed in."""
    return client.pick_seat(
        slot_id,
        f.pick_payload(seat_id, seat_version),
        headers=make_donor_headers(donor_id),
    )


def _a_paid_row_in_a_repriced_section(client):
    """A PAID, ASSIGNED row on a section whose renovation is REPRICED.

    The renovation is left one action short of START_RESEATING so that a test
    can observe the row on both sides of that single request.
    """
    set_clock(client, CLOCK_SETUP)
    section, seats = create_section_with_seats(
        client,
        [("W", 1)],
        seat_capacity=1,
        per_seat_requirement_cents=250000,
        required_points_per_seat=0.00,
        venue_code="STADIUM-W",
    )
    donor = register_donor(
        client, alumni_status=NON_ALUMNUS, entity_type=INDIVIDUAL
    )
    add_received_gift(
        client, donor["id"], 1000000, GIFT_INSTANT, designation=ATHLETICS_ANNUAL
    )
    cycle = certified_cycle(client, 2026)
    event = publish_and_open(
        client, cycle["id"], WINDOW_START, WINDOW_END_ONE_SLOT, SLOT_MINUTES
    )
    set_clock(client, FIRST_PICK_INSTANT)
    assignment = seated_donor(client, event["id"], seats[0]["id"], donor["id"])
    survey_section(client, section["id"])
    reprice_renovation(client, section["id"], 1, 500000)
    return donor, section, seats[0], cycle, assignment


class TestTheRelocationCreateIsGuardedByTheDonorVersionAlone:
    """A supersede is legal, so only the version stamp can refuse the second create."""

    def test_the_first_filing_lands_awaiting_selection_and_counts_once(self, client):
        """The create returns 201, nulls its decision fields and moves the donor on.

        PRD 3.9: "The new request lands in `AWAITING_SELECTION` with
        `granted_seat_assignment_id` and `decision_note` null, and the donor's
        `version` advances by 1."

        PRD 3.9: "Because `pending_request_count` is simply the number of the
        donor's requests currently in `AWAITING_SELECTION`, a donor's *first*
        request increments it while a *replacement* leaves it unchanged — the old
        row leaves the bucket exactly as the new one enters it."

        PRD 4: "Status codes follow one rule with no exceptions: an operation that
        brings a new resource into existence returns **201 Created**, and every
        other successful operation — including every read and every state
        transition on an existing resource — returns **200 OK**."

        Design: Corner/cross_cutting_complexity_layers/relocation_request_create_with_a_stale_donor_version_returns_412
        """
        donor, _source, target, event, assignment = (
            _a_seated_donor_and_a_target_section(client)
        )
        before = read_donor(client, donor["id"])

        filed = validate_success(
            _file_request(
                client, donor, assignment, target, event, before["version"]
            ),
            201,
        )
        assert filed["status"] == RELOCATION_AWAITING_SELECTION
        assert filed["request_type"] == REQUEST_RELOCATION
        assert filed["version"] == 1
        assert filed["granted_seat_assignment_id"] is None
        assert filed["decision_note"] is None

        after = read_donor(client, donor["id"])
        assert after["pending_request_count"] == 1
        assert after["version"] == before["version"] + 1

    def test_replaying_a_spent_donor_version_is_a_412_with_no_partial_effect(
        self, client
    ):
        """The create's own side effect invalidates the stamp it was made with.

        PRD 2.5: "A create whose `expected_donor_version` does not match the
        donor's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412)
        — the stale stamp is the only signal that the writer's picture of the
        donor, including the request it is about to supersede, is out of date."

        PRD 2.8: "The supplied version stamp equals the parent's current
        `version`. This applies to a donor status change, a household link,
        certification, transfer creation, a section reprice, a renovation action,
        a seat pick, an occupancy change, and relocation-request creation.
        Violation: `ERR_STALE_VERSION` (412)."

        Design: Corner/cross_cutting_complexity_layers/relocation_request_create_with_a_stale_donor_version_returns_412
        """
        donor, _source, target, event, assignment = (
            _a_seated_donor_and_a_target_section(client)
        )
        before = read_donor(client, donor["id"])
        first = validate_success(
            _file_request(
                client, donor, assignment, target, event, before["version"]
            ),
            201,
        )

        validate_error(
            _file_request(
                client,
                donor,
                assignment,
                target,
                event,
                before["version"],
                request_type=REQUEST_UPGRADE,
            ),
            ERR_STALE_VERSION,
            412,
        )

        rows, meta = _requests_for(client, donor)
        assert meta["total_count"] == 1, "the refused create must not have landed"
        assert len(rows) == 1
        still = read_relocation_request(client, first["id"])
        assert still["status"] == RELOCATION_AWAITING_SELECTION
        assert still["request_type"] == REQUEST_RELOCATION
        assert still["version"] == 1

        donor_after = read_donor(client, donor["id"])
        assert donor_after["pending_request_count"] == 1
        assert donor_after["version"] == before["version"] + 1

    def test_the_same_body_succeeds_on_a_re_read_version_and_supersedes(self, client):
        """The refusal was purely an OCC verdict, and the two counters compose to 1.

        PRD 2.5: "Creating a relocation request — `POST
        /athletics/relocation-requests`, whose parent for this purpose is the
        `Donor` — is one: a donor is explicitly permitted to file a replacement
        request that supersedes their own prior outstanding one, so the request's
        own state machine cannot tell a legitimate replacement apart from a client
        working from an outdated view."

        PRD 3.9: "The donor's prior request in `AWAITING_SELECTION` moves
        `AWAITING_SELECTION → SUPERSEDED`, requires that prior request to be in
        `AWAITING_SELECTION`, requires the new filing to carry the donor's current
        `version` in `expected_donor_version`, records the supersede reason in the
        superseded request's `decision_note`, and advances that request's
        `version` by 1."

        PRD 3.9: "Because `pending_request_count` is simply the number of the
        donor's requests currently in `AWAITING_SELECTION`, a donor's *first*
        request increments it while a *replacement* leaves it unchanged — the old
        row leaves the bucket exactly as the new one enters it."

        Design: Corner/cross_cutting_complexity_layers/relocation_request_create_with_a_stale_donor_version_returns_412
        """
        donor, _source, target, event, assignment = (
            _a_seated_donor_and_a_target_section(client)
        )
        stale = read_donor(client, donor["id"])["version"]
        first = validate_success(
            _file_request(client, donor, assignment, target, event, stale), 201
        )
        validate_error(
            _file_request(
                client,
                donor,
                assignment,
                target,
                event,
                stale,
                request_type=REQUEST_UPGRADE,
            ),
            ERR_STALE_VERSION,
            412,
        )

        fresh = read_donor(client, donor["id"])["version"]
        second = validate_success(
            _file_request(
                client,
                donor,
                assignment,
                target,
                event,
                fresh,
                request_type=REQUEST_UPGRADE,
            ),
            201,
        )
        assert second["status"] == RELOCATION_AWAITING_SELECTION
        assert second["request_type"] == REQUEST_UPGRADE

        superseded = read_relocation_request(client, first["id"])
        assert superseded["status"] == RELOCATION_SUPERSEDED
        assert superseded["version"] == 2
        assert superseded["decision_note"] is not None
        assert superseded["decision_note"] != ""

        donor_after = read_donor(client, donor["id"])
        assert donor_after["pending_request_count"] == 1, (
            "the create's increment and the supersede's hold-steady compose to 1"
        )
        _rows, meta = _requests_for(client, donor)
        assert meta["total_count"] == 2

    def test_filing_never_touches_the_seat_the_donor_is_asking_to_leave(self, client):
        """The seat only moves when the request is granted, not when it is filed.

        PRD 3.9: "The new request lands in `AWAITING_SELECTION` with
        `granted_seat_assignment_id` and `decision_note` null, and the donor's
        `version` advances by 1."

        PRD 3.9: "On success a new seat assignment is created on the target seat
        with `pricing_mode` `MARKET` — a relocation always pays the market rate,
        never a grandfathered one — and with `selection_slot_id` left null because
        no slot was consumed; `granted_seat_assignment_id` is pointed at the new
        row; the assignment named by `current_seat_assignment_id` is released with
        `release_reason` `DONOR_RELEASE`; the donor's `pending_request_count`
        decrements; and the request's `version` advances by 1."

        Design: Corner/cross_cutting_complexity_layers/relocation_request_create_with_a_stale_donor_version_returns_412
        """
        donor, source, target, event, assignment = (
            _a_seated_donor_and_a_target_section(client)
        )
        stale = read_donor(client, donor["id"])["version"]
        validate_success(
            _file_request(client, donor, assignment, target, event, stale), 201
        )
        validate_error(
            _file_request(client, donor, assignment, target, event, stale),
            ERR_STALE_VERSION,
            412,
        )

        held = read_assignment(client, assignment["id"])
        assert held["occupancy_status"] == OCCUPANCY_ASSIGNED
        assert held["payment_status"] == PAYMENT_PAID
        assert held["release_reason"] == RELEASE_NONE
        assert_cents(held["amount_paid_cents"], 100000, "amount_paid_cents")

        section = read_section(client, source["id"])
        assert_seat_inventory(
            section,
            seat_row_count=1,
            seats_available=0,
            seats_committed_count=1,
            decommissioned_seat_count=0,
        )


class TestTheSeatVersionStampGuardsAContendedPick:
    """Two donors contend over one seat's version counter - the lost-update shape."""

    def test_the_published_slots_follow_the_certified_points_order(self, client):
        """Setup proof: rank 1 picks first, rank 2 the day after, seat untouched.

        PRD 3.5: "The pool is ordered on four keys, applied in strict sequence:
        `certified_points` descending, then `cumulative_giving_cents` descending,
        then `consecutive_giving_years` descending, then `created_at` ascending."

        PRD 3.5: "`rank_position` is the 1-based index in that order."

        PRD 3.8: "It ranks the eligible pool on the four keys of §3.5 and creates
        one slot per ranked donor, each carrying the donor's `donor_id`, its
        `selection_event_id`, a `slot_index`, a `slot_start`, a `slot_end`, and
        `rank_at_publish` — the donor's `rank_position` as observed at publication,
        which is the comparand the staleness check later reads."

        PRD 3.8: "Taking the ranked pool in order with a zero-based counter, each
        donor's `slot_index` is their position in that order; their `slot_start` is
        `window_start` advanced by the counter multiplied by the sum of
        `slot_minutes` and `slot_buffer_minutes`, expressed in minutes; and their
        `slot_end` is their `slot_start` advanced by `slot_minutes`."

        Design: Corner/cross_cutting_complexity_layers/seat_pick_with_a_stale_seat_version_returns_412_then_succeeds_on_a_re_read
        """
        _section, seat, high, low, event = _one_seat_and_two_ranked_donors(client)

        fresh_seat = read_seat(client, seat["id"])
        assert fresh_seat["version"] == 1
        assert fresh_seat["seat_status"] == SEAT_AVAILABLE

        high_donor = read_donor(client, high["id"])
        low_donor = read_donor(client, low["id"])
        assert_points(high_donor["certified_points"], "25.00", "high certified_points")
        assert_points(low_donor["certified_points"], "15.00", "low certified_points")
        assert high_donor["rank_position"] == 1
        assert low_donor["rank_position"] == 2

        high_slot = slot_for_donor(client, event["id"], high["id"])
        low_slot = slot_for_donor(client, event["id"], low["id"])
        assert high_slot["slot_index"] == 0
        assert high_slot["rank_at_publish"] == 1
        assert high_slot["slot_status"] == SLOT_SCHEDULED
        assert_instant(high_slot["slot_start"], WINDOW_START, "high slot_start")
        assert_instant(high_slot["slot_end"], WINDOW_END_ONE_SLOT, "high slot_end")
        assert low_slot["slot_index"] == 1
        assert low_slot["rank_at_publish"] == 2
        assert_instant(low_slot["slot_start"], WINDOW_END_ONE_SLOT, "low slot_start")
        assert_instant(low_slot["slot_end"], WINDOW_END_TWO_SLOTS, "low slot_end")

    def test_the_first_pick_holds_the_seat_and_advances_its_version(self, client):
        """The hold is closed at both ends and runs 72 hours from the pick instant.

        PRD 3.8: "The row starts with `occupancy_status` `HELD` and
        `payment_status` `UNBILLED`, `amount_paid_cents` at 0, `eligibility_status`
        `ELIGIBLE` and `release_reason` `NONE`."

        PRD 3.8: "Its hold window is closed at both ends: `hold_start` is the
        current logical clock instant and `hold_end` is 72 hours later — a hold
        lasts 4,320 minutes."

        PRD 3.8: "On success the seat moves `AVAILABLE → HELD`, one seat shifts out
        of the section's `seats_available` and into its `seats_committed_count`,
        the event's `scheduled_slot_count` decrements, and the `version` of the
        seat, the section and the slot each advance by 1."

        PRD 3.8: "Under `MARKET` pricing, `requirement_cents` is simply the
        section's current `per_seat_requirement_cents`, with no escalator and no
        ceiling."

        Design: Corner/cross_cutting_complexity_layers/seat_pick_with_a_stale_seat_version_returns_412_then_succeeds_on_a_re_read
        """
        _section, seat, high, _low, event = _one_seat_and_two_ranked_donors(client)
        high_slot = slot_for_donor(client, event["id"], high["id"])
        set_clock(client, FIRST_PICK_INSTANT)
        seat_v1 = read_seat(client, seat["id"])["version"]

        assignment = validate_success(
            _pick(client, high_slot["id"], seat["id"], high["id"], seat_v1), 201
        )
        assert assignment["occupancy_status"] == OCCUPANCY_HELD
        assert assignment["payment_status"] == PAYMENT_UNBILLED
        assert assignment["eligibility_status"] == ELIGIBLE
        assert assignment["release_reason"] == RELEASE_NONE
        assert assignment["pricing_mode"] == PRICING_MARKET
        assert_cents(assignment["requirement_cents"], 100000, "requirement_cents")
        assert_instant(assignment["hold_start"], FIRST_PICK_INSTANT, "hold_start")
        assert_instant(assignment["hold_end"], FIRST_HOLD_END, "hold_end")

        after = read_seat(client, seat["id"])
        assert after["version"] == seat_v1 + 1
        assert after["seat_status"] == SEAT_HELD

    def test_a_pick_on_a_spent_seat_version_is_a_412_not_an_availability_refusal(
        self, client
    ):
        """Priority 8 outranks priorities 17 and 18, so the OCC verdict is reported.

        PRD 2.5: "A pick whose `expected_seat_version` does not match the seat's
        current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), telling
        the picker that the seat was chosen from an inventory view that has since
        changed."

        PRD 2.8: "Checks run strictly in the sequence below; the **first** rule
        that a request violates determines the response, and no later rule is
        evaluated."

        PRD 2.8: "The target seat is neither already `ASSIGNED` nor
        `DECOMMISSIONED`. This applies to a seat pick and to a relocation decision.
        Violation: `ERR_SEAT_NOT_AVAILABLE` (409)."

        PRD 2.8: "The number of the seat's hold windows whose closed intervals
        contain the pick instant is strictly below the seat's
        `max_concurrent_holds`. This applies to seat picks only. Violation:
        `ERR_SEAT_HOLD_CONFLICT` (409)."

        Design: Corner/cross_cutting_complexity_layers/seat_pick_with_a_stale_seat_version_returns_412_then_succeeds_on_a_re_read
        """
        _section, seat, high, low, event = _one_seat_and_two_ranked_donors(client)
        high_slot = slot_for_donor(client, event["id"], high["id"])
        low_slot = slot_for_donor(client, event["id"], low["id"])
        set_clock(client, FIRST_PICK_INSTANT)
        seat_v1 = read_seat(client, seat["id"])["version"]
        validate_success(
            _pick(client, high_slot["id"], seat["id"], high["id"], seat_v1), 201
        )

        set_clock(client, SECOND_PICK_INSTANT)
        validate_error(
            _pick(client, low_slot["id"], seat["id"], low["id"], seat_v1),
            ERR_STALE_VERSION,
            412,
        )

        rows, meta = validate_list(
            client.list_seat_assignments(
                headers=OFFICER, params={"seat_id": seat["id"], "limit": 100}
            )
        )
        assert meta["total_count"] == 1, "the refused pick must not have landed"
        assert len(rows) == 1
        assert read_slot(client, low_slot["id"])["slot_status"] == SLOT_SCHEDULED
        assert read_seat(client, seat["id"])["version"] == seat_v1 + 1

    def test_the_retry_on_a_re_read_version_creates_a_second_coexisting_hold(
        self, client
    ):
        """The identical body succeeds once the stamp is fresh, and both holds live.

        PRD 3.8: "It moves the slot `SCHEDULED → CONSUMED` and requires all of the
        following: the slot is in `SCHEDULED`; the caller's `X-User-ID` equals the
        slot's `donor_id`; the parent event is in `OPEN`; the current logical clock
        instant lies inside the slot's half-open window, at or after `slot_start`
        and strictly before `slot_end`; the section holding the target seat has
        `status` `OPEN`; and the target seat is either in `seat_status` `AVAILABLE`
        or already in `HELD` with spare capacity under its `max_concurrent_holds`."

        PRD 3.8: "When the seat already carries a hold whose closed interval has
        ended before the pick instant, that earlier assignment is moved `HELD →
        RELEASED` by the system with `release_reason` set to
        `SUPERSEDED_BY_NEW_HOLD` and its `version` advanced by 1 — and, unlike a
        donor-initiated release, the seat is **left in `HELD`** for the incoming
        assignment rather than returned to `AVAILABLE`, because the seat never
        actually became free."

        PRD 2.9: "`seat_row_count` is the number of seat rows in the section;
        `seats_available` counts those whose `seat_status` is `AVAILABLE`;
        `seats_committed_count` counts those whose `seat_status` is either `HELD`
        or `ASSIGNED`; and `decommissioned_seat_count` counts those whose
        `seat_status` is `DECOMMISSIONED`."

        PRD 2.9: "After every request, including every cascade, the sum of
        `seats_available`, `seats_committed_count` and `decommissioned_seat_count`
        must equal `seat_row_count`."

        Design: Corner/cross_cutting_complexity_layers/seat_pick_with_a_stale_seat_version_returns_412_then_succeeds_on_a_re_read
        """
        section, seat, high, low, event = _one_seat_and_two_ranked_donors(client)
        high_slot = slot_for_donor(client, event["id"], high["id"])
        low_slot = slot_for_donor(client, event["id"], low["id"])
        set_clock(client, FIRST_PICK_INSTANT)
        seat_v1 = read_seat(client, seat["id"])["version"]
        first = validate_success(
            _pick(client, high_slot["id"], seat["id"], high["id"], seat_v1), 201
        )

        set_clock(client, SECOND_PICK_INSTANT)
        validate_error(
            _pick(client, low_slot["id"], seat["id"], low["id"], seat_v1),
            ERR_STALE_VERSION,
            412,
        )
        seat_v2 = read_seat(client, seat["id"])["version"]
        second = validate_success(
            _pick(client, low_slot["id"], seat["id"], low["id"], seat_v2), 201
        )
        assert second["occupancy_status"] == OCCUPANCY_HELD
        assert_instant(second["hold_start"], SECOND_PICK_INSTANT, "hold_start")
        assert_instant(second["hold_end"], SECOND_HOLD_END, "hold_end")

        after_seat = read_seat(client, seat["id"])
        assert after_seat["version"] == seat_v2 + 1
        assert after_seat["seat_status"] == SEAT_HELD

        earlier = read_assignment(client, first["id"])
        assert earlier["occupancy_status"] == OCCUPANCY_HELD, (
            "an unexpired hold is not superseded"
        )
        assert earlier["release_reason"] == RELEASE_NONE

        rows, meta = validate_list(
            client.list_seat_assignments(
                headers=OFFICER, params={"seat_id": seat["id"], "limit": 100}
            )
        )
        assert meta["total_count"] == 2
        assert {row["occupancy_status"] for row in rows} == {OCCUPANCY_HELD}

        assert_seat_inventory(
            read_section(client, section["id"]),
            seat_row_count=1,
            seats_available=0,
            seats_committed_count=1,
            decommissioned_seat_count=0,
        )


class TestTheDonorVersionCounterTracksWritesTheClientNeverAimedAtTheDonor:
    """A gift settlement, a renewal and a cycle run all move Donor.version."""

    def _a_fresh_donor(self, client):
        set_clock(client, CLOCK_SETUP)
        return register_donor(
            client, alumni_status=NON_ALUMNUS, entity_type=INDIVIDUAL
        )

    def test_a_read_never_advances_the_donor_version(self, client):
        """Two fetches in a row leave the counter exactly where creation put it.

        PRD 2.4: "Most resources also carry `updated_at`, in the same format,
        refreshed on every mutation, and `version`, an integer that starts at 1 on
        creation and increases by exactly 1 on each mutation that the specification
        says advances it."

        PRD 3.1: "A newly registered donor lands in `donor_status` `ACTIVE` with
        `status_effective_date` set to the current logical clock instant, and every
        point and counter field starts at zero: `season_ticket_seasons_purchased`,
        `cumulative_giving_cents`, `consecutive_giving_years`, `provisional_points`,
        `certified_base_points`, `certified_points`, `transferred_points_in`,
        `transferred_points_out`, `dispute_adjustment_points` and
        `pending_request_count` are all `0`, while `household_partner_donor_id` and
        `rank_position` are both null."

        Design: Corner/cross_cutting_complexity_layers/donor_version_advances_on_every_write_including_cascaded_ones_and_never_on_a_read
        """
        donor = self._a_fresh_donor(client)
        assert donor["version"] == 1

        first = read_donor(client, donor["id"])
        second = read_donor(client, donor["id"])
        assert first["version"] == 1
        assert second["version"] == 1
        assert second["donor_status"] == DONOR_ACTIVE
        assert_instant(
            second["status_effective_date"], CLOCK_SETUP, "status_effective_date"
        )
        assert second["rank_position"] is None

    def test_the_settlement_the_renewal_and_the_run_each_advance_the_counter(
        self, client
    ):
        """Three writes aimed elsewhere, three increments on the donor row.

        PRD 3.2: "A gift is recorded against a donor with three required values —
        `gift_date`, the instant the gift was made; `amount_cents`, which must be
        strictly greater than zero; and `designation`, one of `ATHLETICS_ANNUAL`,
        `CAPITAL` or `ENDOWMENT` — plus an optional `gift_status` that defaults to
        `PLEDGED` when omitted and is otherwise `RECEIVED` or `REFUNDED`."

        PRD 3.2: "Settling `PLEDGED → RECEIVED` requires the gift to be `PLEDGED`;
        it stamps `settled_at` with the current logical clock instant, adds
        `amount_cents` to the donor's `cumulative_giving_cents`, sets
        `counts_toward_points` to true when `designation` is `ATHLETICS_ANNUAL` or
        `CAPITAL`, makes the gift eligible for the CERTIFIED point variant in
        addition to the PROVISIONAL one, and advances both the gift's `version` and
        the donor's `version` by 1."

        PRD 3.1: "The renewal operation carries a single `cycle_year`, and each
        distinct `cycle_year` counts once: recording a year not already on file
        increments `season_ticket_seasons_purchased` by 1 and advances the donor's
        `version` by 1, and if `season_ticket_first_cycle_year` was previously unset
        it is filled in from this call."

        PRD 3.3: "The run also recomputes each donor's `certified_points`, sets
        `donors_processed_count` to the number of donors scored, and advances the
        recalculation's `version` by 1 along with the `version` of every scored
        donor."

        PRD 3.3: "The CERTIFIED variant writes the *gift-and-attribute part* — the
        multiplied giving component plus the consecutive-year, tenure and alumni
        components, before the net transfer term and before dispute adjustments —
        to `certified_base_points`, and writes the full final figure to
        `certified_points`."

        Design: Corner/cross_cutting_complexity_layers/donor_version_advances_on_every_write_including_cascaded_ones_and_never_on_a_read
        """
        donor = self._a_fresh_donor(client)
        gift = add_gift(client, donor["id"], 1000000, GIFT_INSTANT)
        assert gift["version"] == 1
        assert gift["gift_status"] == GIFT_PLEDGED
        assert gift["settled_at"] is None

        before_settle = read_donor(client, donor["id"])["version"]
        settled = validate_success(
            client.settle_gift(
                gift["id"], f.settle_gift_payload(GIFT_RECEIVED), headers=OFFICER
            )
        )
        assert settled["gift_status"] == GIFT_RECEIVED
        assert settled["version"] == 2
        after_settle = read_donor(client, donor["id"])
        assert after_settle["version"] == before_settle + 1
        assert_cents(
            after_settle["cumulative_giving_cents"], 1000000, "cumulative_giving_cents"
        )

        renew_season(client, donor["id"], 2026)
        after_renew = read_donor(client, donor["id"])
        assert after_renew["version"] == after_settle["version"] + 1
        assert after_renew["season_ticket_seasons_purchased"] == 1
        assert after_renew["season_ticket_first_cycle_year"] == 2026

        cycle = open_cycle(client, 2026)
        before_run = read_donor(client, donor["id"])["version"]
        run_cycle(client, cycle["id"])
        after_run = read_donor(client, donor["id"])
        assert after_run["version"] == before_run + 1
        assert_points(after_run["certified_base_points"], "18.00", "certified_base_points")
        assert_points(after_run["certified_points"], "18.00", "certified_points")
        assert after_run["consecutive_giving_years"] == 1

    def test_the_run_invalidates_a_token_the_client_never_spent_on_the_donor(
        self, client
    ):
        """The cached stamp dies with the cycle run; the refusal changes nothing.

        PRD 2.5: "In every such case the echoed value is a required field of the
        request body, not an optional hint, and a mismatch against the parent's
        current `version` is reported as `ERR_STALE_VERSION` (HTTP 412)."

        PRD 3.1: "A status change carries `new_status`, an `effective_date`, a
        free-text `reason`, and `expected_donor_version`; on success it writes
        `effective_date` into `status_effective_date` and advances the donor's
        `version` by 1."

        PRD 3.1: "Lapsing a donor moves `ACTIVE → LAPSED` and requires both that
        the donor is currently `ACTIVE` and that `effective_date` is not later than
        the current logical clock instant."

        PRD 3.3: "`certified_base_points` is never re-derived outside a
        recalculation run, which is precisely why moving a donor to `DECEASED` does
        not retroactively strip the alumni bonus out of a cycle that has already
        been certified."

        Design: Corner/cross_cutting_complexity_layers/donor_version_advances_on_every_write_including_cascaded_ones_and_never_on_a_read
        """
        lapse_effective = f.instant(2026, 3, 20)
        donor = self._a_fresh_donor(client)
        gift = add_gift(client, donor["id"], 1000000, GIFT_INSTANT)
        validate_success(
            client.settle_gift(
                gift["id"], f.settle_gift_payload(GIFT_RECEIVED), headers=OFFICER
            )
        )
        renew_season(client, donor["id"], 2026)
        cached = read_donor(client, donor["id"])["version"]

        cycle = open_cycle(client, 2026)
        run_cycle(client, cycle["id"])

        validate_error(
            client.change_donor_status(
                donor["id"],
                f.status_change_payload(DONOR_LAPSED, lapse_effective, cached),
                headers=OFFICER,
            ),
            ERR_STALE_VERSION,
            412,
        )

        refused = read_donor(client, donor["id"])
        assert refused["donor_status"] == DONOR_ACTIVE
        assert_instant(
            refused["status_effective_date"], CLOCK_SETUP, "status_effective_date"
        )
        assert refused["version"] == cached + 1, "the run advanced it exactly once"

        lapsed = validate_success(
            client.change_donor_status(
                donor["id"],
                f.status_change_payload(
                    DONOR_LAPSED, lapse_effective, refused["version"]
                ),
                headers=OFFICER,
            )
        )
        assert lapsed["donor_status"] == DONOR_LAPSED
        assert_instant(
            lapsed["status_effective_date"], lapse_effective, "status_effective_date"
        )
        assert lapsed["version"] == refused["version"] + 1
        assert_points(lapsed["certified_points"], "18.00", "certified_points")


class TestAReseatingRewritesFourEntitiesInOneRequest:
    """One operator call moves the section, the inventory, the price and the money."""

    def test_the_row_is_paid_in_full_before_the_reseating_begins(self, client):
        """Setup proof: PAID and ASSIGNED at the market rate, renovation REPRICED.

        PRD 3.7: "It also opens `requirement_history` with a single entry pairing
        the opening `per_seat_requirement_cents` with a `cycle_year` taken from the
        UTC calendar year of the current logical clock instant."

        PRD 3.7: "Its side effect is to set `status` to `UNDER_RENOVATION`, which
        blocks every pick into this section for the duration."

        PRD 3.7: "It stores both values on the section without applying either one
        yet; `post_renovation_capacity` and `post_renovation_requirement_cents` must
        each be strictly greater than zero when present, and both remain null until
        this action runs."

        PRD 3.9: "Confirming a hold moves the assignment `HELD → ASSIGNED` and
        requires four things: the row is in `HELD`; the version stamp matches;
        `amount_paid_cents` is at least `total_due_cents`; and `eligibility_status`
        is `ELIGIBLE`."

        Design: Corner/cross_cutting_complexity_layers/reseating_drags_a_fully_paid_assignment_backwards_on_the_payment_axis_only
        """
        _donor, section, _seat, _cycle, assignment = (
            _a_paid_row_in_a_repriced_section(client)
        )

        row = read_assignment(client, assignment["id"])
        assert_cents(row["requirement_cents"], 250000, "requirement_cents")
        assert_cents(row["total_due_cents"], 250000, "total_due_cents")
        assert_cents(row["amount_paid_cents"], 250000, "amount_paid_cents")
        assert row["payment_status"] == PAYMENT_PAID
        assert row["occupancy_status"] == OCCUPANCY_ASSIGNED
        assert row["pricing_mode"] == PRICING_MARKET
        assert row["eligibility_status"] == ELIGIBLE

        current = read_section(client, section["id"])
        assert current["status"] == SECTION_UNDER_RENOVATION
        assert current["renovation_status"] == RENOVATION_REPRICED
        assert_cents(
            current["per_seat_requirement_cents"], 250000, "per_seat_requirement_cents"
        )
        assert current["post_renovation_capacity"] == 1
        assert_cents(
            current["post_renovation_requirement_cents"],
            500000,
            "post_renovation_requirement_cents",
        )
        history = current["requirement_history"]
        assert len(history) == 1, "only the opening entry exists yet"
        assert history[0]["cycle_year"] == 2026
        assert_cents(
            history[0]["per_seat_requirement_cents"],
            250000,
            "requirement_history[0].per_seat_requirement_cents",
        )

    def test_start_reseating_applies_the_post_renovation_figures_and_appends_history(
        self, client
    ):
        """The capacity and the rate land, and the history gains the new pairing.

        PRD 3.7: "**`START_RESEATING`** moves `REPRICED → RESEATING` and requires
        `renovation_status` to be `REPRICED` and the supplied
        `reseating_recalculation_id` to reference a recalculation in `CERTIFIED`; a
        recalculation in any other status is rejected with
        `ERR_RECALCULATION_NOT_CERTIFIED`."

        PRD 3.7: "The section's `seat_capacity` is replaced by
        `post_renovation_capacity` and its `per_seat_requirement_cents` by
        `post_renovation_requirement_cents`, and a new `requirement_history` entry
        is appended pairing the new requirement with the `cycle_year` of the
        reseating recalculation."

        PRD 3.7: "Seats beyond the new capacity are retired: taking the section's
        seats in `created_at` ascending order — never in `id` order — every seat
        still in `seat_status` `AVAILABLE` whose ordinal position in that order
        exceeds `post_renovation_capacity` moves `AVAILABLE → DECOMMISSIONED`,
        shifting one seat out of `seats_available` and into
        `decommissioned_seat_count` and advancing that seat's `version` by 1."

        PRD 3.7: "`reseating_invoice_total_cents` is that running total and
        `reseated_donor_count` is the number of rows visited."

        Design: Corner/cross_cutting_complexity_layers/reseating_drags_a_fully_paid_assignment_backwards_on_the_payment_axis_only
        """
        _donor, section, seat, cycle, _assignment = (
            _a_paid_row_in_a_repriced_section(client)
        )

        reseating = start_reseating(client, section["id"], cycle["id"])
        assert reseating["renovation_status"] == RENOVATION_RESEATING
        assert reseating["seat_capacity"] == 1
        assert_cents(
            reseating["per_seat_requirement_cents"],
            500000,
            "per_seat_requirement_cents",
        )
        assert reseating["reseated_donor_count"] == 1
        assert_cents(
            reseating["reseating_invoice_total_cents"],
            291667,
            "reseating_invoice_total_cents",
        )
        assert reseating["reseating_recalculation_id"] == cycle["id"]

        history = reseating["requirement_history"]
        assert len(history) == 2, "creation plus the reseating append"
        assert history[0]["cycle_year"] == 2026
        assert_cents(
            history[0]["per_seat_requirement_cents"],
            250000,
            "requirement_history[0].per_seat_requirement_cents",
        )
        assert history[1]["cycle_year"] == 2026
        assert_cents(
            history[1]["per_seat_requirement_cents"],
            500000,
            "requirement_history[1].per_seat_requirement_cents",
        )

        assert read_seat(client, seat["id"])["seat_status"] == SEAT_ASSIGNED
        assert_seat_inventory(
            read_section(client, section["id"]),
            seat_row_count=1,
            seats_available=0,
            seats_committed_count=1,
            decommissioned_seat_count=0,
        )

    def test_the_prorated_share_overwrites_the_price_and_only_the_money_axis_moves(
        self, client
    ):
        """PAID is dragged back to INVOICED while the payment and occupancy survive.

        PRD 3.7: "Then every seat assignment on the section's seats whose
        `occupancy_status` is `HELD` or `ASSIGNED` is repriced under its own
        `pricing_mode`, and invoiced."

        PRD 3.7: "The invoice is prorated for the remaining months of the cycle at
        seven twelfths, and **the order of operations is load-bearing**: visiting
        those assignments in `created_at` ascending order, each row's
        `requirement_cents` is multiplied by 7, divided by 12, and rounded half up
        to whole cents; that rounded per-seat share is written back as the row's new
        `requirement_cents` and added to a running total."

        PRD 3.7: "Every row the cascade touched has its `payment_status` moved to
        `INVOICED`, and this includes rows that had already been paid: an assignment
        in `payment_status` `PAID` whose `requirement_cents` changed during the
        cascade is dragged backwards `PAID → INVOICED`, with `total_due_cents`
        raised to the reseating amount while `amount_paid_cents` keeps the prior
        payment, so the outstanding balance is visible."

        PRD 3.7: "The row's `occupancy_status` is untouched by any of this."

        PRD 3.9: "A seat assignment carries **two independent status axes on the
        same row**, and neither constrains the other."

        Design: Corner/cross_cutting_complexity_layers/reseating_drags_a_fully_paid_assignment_backwards_on_the_payment_axis_only
        """
        _donor, section, seat, cycle, assignment = (
            _a_paid_row_in_a_repriced_section(client)
        )
        start_reseating(client, section["id"], cycle["id"])

        row = read_assignment(client, assignment["id"])
        assert_cents(row["requirement_cents"], 291667, "requirement_cents")
        assert_cents(row["total_due_cents"], 291667, "total_due_cents")
        assert_cents(row["amount_paid_cents"], 250000, "amount_paid_cents")
        assert row["payment_status"] == PAYMENT_INVOICED
        assert row["occupancy_status"] == OCCUPANCY_ASSIGNED
        assert row["pricing_mode"] == PRICING_MARKET
        assert row["release_reason"] == RELEASE_NONE
        assert read_seat(client, seat["id"])["seat_status"] == SEAT_ASSIGNED

    def test_completing_the_renovation_reopens_the_section_and_lifts_the_posture(
        self, client
    ):
        """COMPLETE puts the section back in OPEN and recomputes the posture.

        PRD 3.7: "**`COMPLETE`** moves `RESEATING → COMPLETED` and requires
        `renovation_status` to be `RESEATING`. It sets `status` back to `OPEN`,
        unblocking picks, and recomputes `pricing_posture` from the post-reseating
        underwater ratio."

        PRD 3.7: "The branch order is pinned and `SOFT` is evaluated first and wins
        outright — when the ratio is at least 0.30 the posture is `SOFT`; otherwise,
        when the ratio is exactly zero **and** `seats_available` is zero, the
        posture is `PREMIUM`; otherwise it is `NORMAL`."

        PRD 3.7: "That recommendation is `per_seat_requirement_cents` multiplied by
        0.90 and rounded half up to whole cents when the posture is `SOFT`,
        multiplied by 1.10 and rounded half up to whole cents when the posture is
        `PREMIUM`, and simply `per_seat_requirement_cents` unchanged when the
        posture is `NORMAL`."

        PRD 2.9: "A seat assignment's `eligibility_status` is `UNDERWATER` whenever
        the donor's *current* `certified_points` is below that row's
        `required_points`, and `ELIGIBLE` otherwise — the row's own frozen
        `points_at_pick` records what the donor had at the moment of the pick, but
        eligibility is always judged against the live figure."

        Design: Corner/cross_cutting_complexity_layers/reseating_drags_a_fully_paid_assignment_backwards_on_the_payment_axis_only
        """
        _donor, section, _seat, cycle, _assignment = (
            _a_paid_row_in_a_repriced_section(client)
        )
        start_reseating(client, section["id"], cycle["id"])

        completed = renovation_action(client, section["id"], ACTION_COMPLETE)
        assert completed["renovation_status"] == RENOVATION_COMPLETED
        assert completed["status"] == SECTION_OPEN

        report = sensitivity(client, section["id"])
        assert_cents(
            report["per_seat_requirement_cents"], 500000, "per_seat_requirement_cents"
        )
        assert report["assigned_seat_count"] == 1
        assert report["underwater_seat_count"] == 0
        assert_ratio(report["underwater_ratio"], "0.0000", "underwater_ratio")
        assert report["pricing_posture"] == POSTURE_PREMIUM
        assert_cents(
            report["recommended_requirement_cents"],
            550000,
            "recommended_requirement_cents",
        )
        assert len(report["requirement_history"]) == 2
