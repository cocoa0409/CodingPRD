"""The consistency model: every declared side effect is durable before the reply.

Nothing in this service is eventually consistent. A write that touches five
entities must have all five durable before its own status line is emitted, so
the very first read of each collateral entity already shows the new value - no
second read, no retry, no reconciliation pass. Read-only endpoints are the mirror
image: a derived payload is a pure function of stored state, so calling it twice
must return the same numbers and must leave every version stamp exactly where it
was.
"""

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_cents,
    assert_instant,
    assert_points,
    assert_ratio,
    assert_seat_inventory,
    assert_version_unchanged,
    as_decimal,
    validate_success,
)
from test_helpers.constants import (
    ATHLETICS_ANNUAL,
    ELIGIBLE,
    EVENT_OPEN,
    INDIVIDUAL,
    NON_ALUMNUS,
    OCCUPANCY_HELD,
    PAYMENT_UNBILLED,
    PRICING_MARKET,
    RECALC_CERTIFIED,
    RELEASE_NONE,
    SEAT_AVAILABLE,
    SEAT_HELD,
    SLOT_CONSUMED,
)
from test_helpers.fixtures import (
    add_received_gift,
    certified_cycle,
    communicated_cycle,
    create_section_with_seats,
    pick_seat,
    publish_and_open,
    read_cycle,
    read_donor,
    read_event,
    read_seat,
    read_section,
    read_slot,
    register_donor,
    retention,
    set_clock,
    slot_for_donor,
)
from test_helpers.test_users import CERTIFIER, CERTIFIER_USER_ID, OFFICER

CLOCK_SETUP = f.instant(2026, 4, 1)
GIFT_INSTANT = f.instant(2026, 3, 1)
WINDOW_START = f.instant(2026, 9, 1)
WINDOW_END = f.instant(2026, 9, 2)
SLOT_MINUTES = 1440
PICK_INSTANT = f.instant(2026, 9, 1, 6)
HOLD_END = f.instant(2026, 9, 4, 6)


def _two_seats_and_one_open_slot(client):
    """A two-seat section and a donor whose slot is open at PICK_INSTANT.

    The section deliberately carries two seats so that a correct decrement of
    ``seats_available`` lands on 1 rather than on 0, which a counter that was
    merely clamped at zero could also produce.
    """
    set_clock(client, CLOCK_SETUP)
    section, seats = create_section_with_seats(
        client,
        [("S", 1), ("S", 2)],
        section_code="SEC-S",
        venue_code="STADIUM-S",
        seat_capacity=2,
        per_seat_requirement_cents=120000,
        required_points_per_seat=0.00,
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
        client, cycle["id"], WINDOW_START, WINDOW_END, SLOT_MINUTES
    )
    slot = slot_for_donor(client, event["id"], donor["id"])
    set_clock(client, PICK_INSTANT)
    return section, seats, donor, event, slot


class TestThePickCascadeIsDurableBeforeTheStatusLineIsWritten:
    """One pick, six side effects, four collateral entities, zero second reads."""

    def test_the_pick_response_itself_already_carries_the_finished_row(self, client):
        """The 201 body is complete: both axes, both snapshots, both prices.

        PRD 4: "Status codes follow one rule with no exceptions: an operation
        that brings a new resource into existence returns **201 Created**, and
        every other successful operation — including every read and every state
        transition on an existing resource — returns **200 OK**."

        PRD 3.8: "The pick names `seat_id`, the seat being taken, and
        `expected_seat_version`, which must equal that seat's current `version`."

        PRD 3.8: "The pick creates a seat assignment."

        PRD 3.8: "Its `donor_id` is copied from the slot's `donor_id` and never
        read from the body, and its `selection_slot_id` records the slot it came
        through."

        PRD 3.8: "The row starts with `occupancy_status` `HELD` and
        `payment_status` `UNBILLED`, `amount_paid_cents` at 0,
        `eligibility_status` `ELIGIBLE` and `release_reason` `NONE`."

        PRD 3.8: "Its hold window is closed at both ends: `hold_start` is the
        current logical clock instant and `hold_end` is 72 hours later — a hold
        lasts 4,320 minutes."

        PRD 3.8: "Two snapshots are frozen onto the row at creation and never
        move afterwards: `required_points` copies the section's
        `required_points_per_seat`, and `points_at_pick` copies the donor's
        `certified_points` as they stood at the moment of the pick."

        PRD 3.8: "Under `MARKET` pricing, `requirement_cents` is simply the
        section's current `per_seat_requirement_cents`, with no escalator and no
        ceiling."

        PRD 3.8: "For a `SEASON_TICKET` event, `handling_fee_cents` is 0 and
        `total_due_cents` equals `requirement_cents`."

        Design: Corner/consistency_model/the_pick_response_and_the_first_read_after_it_already_show_every_cascaded_counter
        """
        _section, seats, donor, _event, slot = _two_seats_and_one_open_slot(client)

        response = pick_seat(client, slot["id"], seats[0]["id"], donor["id"])
        row = validate_success(response, 201)

        assert row["donor_id"] == donor["id"]
        assert row["seat_id"] == seats[0]["id"]
        assert row["selection_slot_id"] == slot["id"]
        assert row["occupancy_status"] == OCCUPANCY_HELD
        assert row["payment_status"] == PAYMENT_UNBILLED
        assert row["eligibility_status"] == ELIGIBLE
        assert row["release_reason"] == RELEASE_NONE
        assert row["pricing_mode"] == PRICING_MARKET
        assert_cents(row["requirement_cents"], 120000, "requirement_cents")
        assert_cents(row["handling_fee_cents"], 0, "handling_fee_cents")
        assert_cents(row["total_due_cents"], 120000, "total_due_cents")
        assert_cents(row["amount_paid_cents"], 0, "amount_paid_cents")
        assert_points(row["required_points"], "0.00", "required_points")
        assert_points(row["points_at_pick"], "15.00", "points_at_pick")
        assert_instant(row["hold_start"], PICK_INSTANT, "hold_start")
        assert_instant(row["hold_end"], HOLD_END, "hold_end")
        assert row["version"] == 1, "a freshly created row starts at version 1"

    def test_the_first_read_of_the_seat_and_the_section_shows_the_commitment(
        self, client
    ):
        """No second read: the seat is HELD and the section has already moved one.

        PRD 3.8: "On success the seat moves `AVAILABLE → HELD`, one seat shifts
        out of the section's `seats_available` and into its
        `seats_committed_count`, the event's `scheduled_slot_count` decrements,
        and the `version` of the seat, the section and the slot each advance by
        1."

        PRD 2.9: "A great deal of this service's state is derived, and derived
        state is recomputed **immediately and within the same request** as the
        change that invalidated it — there is no deferred sweep, no eventual
        reconciliation, and no endpoint whose only purpose is to refresh a
        counter."

        PRD 2.9: "When one request touches several resources, every touched
        resource has its `updated_at` refreshed and its `version` advanced by 1,
        and this document names each such resource explicitly at each transition
        rather than leaving cascades to be inferred."

        PRD 2.9: "After every request, including every cascade, the sum of
        `seats_available`, `seats_committed_count` and
        `decommissioned_seat_count` must equal `seat_row_count`."

        Design: Corner/consistency_model/the_pick_response_and_the_first_read_after_it_already_show_every_cascaded_counter
        """
        section, seats, donor, _event, slot = _two_seats_and_one_open_slot(client)
        assert seats[0]["version"] == 1, "seat is untouched before the pick"

        validate_success(
            pick_seat(client, slot["id"], seats[0]["id"], donor["id"]), 201
        )

        seat = read_seat(client, seats[0]["id"])
        assert seat["seat_status"] == SEAT_HELD
        assert seat["version"] == 2, "the seat's very first read shows the bump"

        current = read_section(client, section["id"])
        assert_seat_inventory(
            current,
            seat_row_count=2,
            seats_available=1,
            seats_committed_count=1,
            decommissioned_seat_count=0,
        )
        assert current["version"] == section["version"] + 1

    def test_the_first_read_of_the_slot_and_the_event_shows_the_consumption(
        self, client
    ):
        """The slot is CONSUMED and the event's counter is already decremented.

        PRD 3.8: "Consuming a slot is the donor's own act and the only way a
        seat is claimed through an event."

        PRD 3.8: "It moves the slot `SCHEDULED → CONSUMED` and requires all of
        the following: the slot is in `SCHEDULED`; the caller's `X-User-ID`
        equals the slot's `donor_id`; the parent event is in `OPEN`; the current
        logical clock instant lies inside the slot's half-open window, at or
        after `slot_start` and strictly before `slot_end`; the section holding
        the target seat has `status` `OPEN`; and the target seat is either in
        `seat_status` `AVAILABLE` or already in `HELD` with spare capacity under
        its `max_concurrent_holds`."

        PRD 3.8: "On success the seat moves `AVAILABLE → HELD`, one seat shifts
        out of the section's `seats_available` and into its
        `seats_committed_count`, the event's `scheduled_slot_count` decrements,
        and the `version` of the seat, the section and the slot each advance by
        1."

        PRD 3.8: "`published_slot_count` and `scheduled_slot_count` are both set
        to the pool size, every new slot starts in `slot_status` `SCHEDULED`, and
        the event's `version` advances by 1."

        Design: Corner/consistency_model/the_pick_response_and_the_first_read_after_it_already_show_every_cascaded_counter
        """
        _section, seats, donor, event, slot = _two_seats_and_one_open_slot(client)
        assert event["published_slot_count"] == 1
        assert event["scheduled_slot_count"] == 1

        validate_success(
            pick_seat(client, slot["id"], seats[0]["id"], donor["id"]), 201
        )

        consumed = read_slot(client, slot["id"])
        assert consumed["slot_status"] == SLOT_CONSUMED
        assert consumed["version"] == 2, "the slot's first read shows the bump"

        after = read_event(client, event["id"])
        assert after["scheduled_slot_count"] == 0
        assert after["published_slot_count"] == 1, "publication history is not rewritten"
        assert after["status"] == EVENT_OPEN, "a pick does not close the event"

    def test_the_seat_nobody_picked_is_left_exactly_as_it_was(self, client):
        """The decrement moved one specific seat, not the whole inventory.

        PRD 3.8: "On success the seat moves `AVAILABLE → HELD`, one seat shifts
        out of the section's `seats_available` and into its
        `seats_committed_count`, the event's `scheduled_slot_count` decrements,
        and the `version` of the seat, the section and the slot each advance by
        1."

        PRD 3.7: "A new seat starts in `seat_status` `AVAILABLE`, increments the
        section's `seat_row_count` and `seats_available`, and advances the
        section's `version` by 1."

        Design: Corner/consistency_model/the_pick_response_and_the_first_read_after_it_already_show_every_cascaded_counter
        """
        _section, seats, donor, _event, slot = _two_seats_and_one_open_slot(client)

        validate_success(
            pick_seat(client, slot["id"], seats[0]["id"], donor["id"]), 201
        )

        bystander = read_seat(client, seats[1]["id"])
        assert bystander["seat_status"] == SEAT_AVAILABLE
        assert_version_unchanged(bystander, 1, "untouched seat")


def _a_communicated_cycle_over_two_donors(client):
    """Two donors ten points apart, on a cycle that is one call from CERTIFIED."""
    set_clock(client, CLOCK_SETUP)
    top = register_donor(client, alumni_status=NON_ALUMNUS, entity_type=INDIVIDUAL)
    add_received_gift(
        client, top["id"], 2000000, GIFT_INSTANT, designation=ATHLETICS_ANNUAL
    )
    bottom = register_donor(client, alumni_status=NON_ALUMNUS, entity_type=INDIVIDUAL)
    add_received_gift(
        client, bottom["id"], 1000000, GIFT_INSTANT, designation=ATHLETICS_ANNUAL
    )
    cycle = communicated_cycle(client, 2026)
    return cycle, top, bottom


def _certify(client, cycle):
    """Certify with a freshly read version stamp, returning the raw response."""
    current = read_cycle(client, cycle["id"], headers=OFFICER)
    return client.certify_recalculation(
        cycle["id"], f.certify_payload(current["version"]), headers=CERTIFIER
    )


class TestCertificationAggregatesAndStampsInsideItsOwnRequest:
    """The sum is in the 200 body and the ranks are in the very next donor read."""

    def test_the_certifier_stamps_are_still_empty_before_the_certification(
        self, client
    ):
        """Setup proof: the run scored both donors but stamped no rank and no certifier.

        PRD 3.3: "The new recalculation starts in `DRAFT` with
        `donors_processed_count`, `communication_sent_count` and
        `certified_points_sum` at zero, `certified_by_user_id` and `certified_at`
        null, and `initiated_by_user_id` set to the caller's `X-User-ID` — the
        value that will later be compared against the certifier's identity."

        PRD 3.3: "The run also recomputes each donor's `certified_points`, sets
        `donors_processed_count` to the number of donors scored, and advances the
        recalculation's `version` by 1 along with the `version` of every scored
        donor."

        PRD 3.1: "`rank_position` stays null until the donor's first
        certification, and once set is a 1-based rank of at least 1."

        Design: Corner/consistency_model/the_certify_response_carries_the_points_sum_computed_in_that_same_request
        """
        cycle, top, bottom = _a_communicated_cycle_over_two_donors(client)

        pending = read_cycle(client, cycle["id"])
        assert pending["donors_processed_count"] == 2
        # PRD 2.9 recomputes certified_points_sum whenever a scored donor's
        # certified_points changes, and the run changed both of them, so the
        # aggregate already tracks the pair rather than sitting at its DRAFT zero.
        assert_points(
            pending["certified_points_sum"],
            as_decimal(read_donor(client, top["id"])["certified_points"])
            + as_decimal(read_donor(client, bottom["id"])["certified_points"]),
            "certified_points_sum",
        )
        assert pending["certified_by_user_id"] is None
        assert pending["certified_at"] is None

        assert read_donor(client, top["id"])["rank_position"] is None
        assert read_donor(client, bottom["id"])["rank_position"] is None

    def test_the_certify_response_already_carries_the_summed_points(self, client):
        """The 200 body holds the aggregate; no follow-up read is needed to see it.

        PRD 4: "Status codes follow one rule with no exceptions: an operation
        that brings a new resource into existence returns **201 Created**, and
        every other successful operation — including every read and every state
        transition on an existing resource — returns **200 OK**."

        PRD 3.5: "On success the recalculation records `certified_by_user_id`
        from the certifier's `X-User-ID` and `certified_at` from the current
        logical clock instant, sets `certified_points_sum` to the sum of
        `certified_points` across every donor it processed, and advances its own
        `version` by 1."

        PRD 3.5: "Moving a cycle `COMMUNICATED → CERTIFIED` requires four things
        at once: the recalculation is in `COMMUNICATED`; the supplied
        `expected_recalculation_version` equals the recalculation's current
        `version`; the certifier's `X-User-ID` differs from
        `initiated_by_user_id`; and no dispute on this recalculation remains in
        `SUBMITTED`, `UNDER_REVIEW` or `INFO_REQUESTED`."

        Design: Corner/consistency_model/the_certify_response_carries_the_points_sum_computed_in_that_same_request
        """
        cycle, _top, _bottom = _a_communicated_cycle_over_two_donors(client)
        before = read_cycle(client, cycle["id"])

        certified = validate_success(_certify(client, cycle), 200)

        assert certified["status"] == RECALC_CERTIFIED
        # 40.00 is neither donor's own score, so the body cannot be echoing one
        # of them: 25.00 + 15.00 was summed inside this very request.
        assert_points(
            certified["certified_points_sum"], "40.00", "certified_points_sum"
        )
        assert certified["certified_by_user_id"] == CERTIFIER_USER_ID
        assert_instant(certified["certified_at"], CLOCK_SETUP, "certified_at")
        assert certified["version"] == before["version"] + 1
        assert certified["donors_processed_count"] == 2

    def test_the_first_read_of_each_donor_already_carries_its_rank(self, client):
        """The ranks are durable before the certify reply, not computed on read.

        PRD 3.5: "It then stamps `rank_position` across the ranked donor pool,
        and that stamping is what sets off a three-step cascade."

        PRD 3.5: "The pool is ordered on four keys, applied in strict sequence:
        `certified_points` descending, then `cumulative_giving_cents`
        descending, then `consecutive_giving_years` descending, then
        `created_at` ascending."

        PRD 3.5: "`rank_position` is the 1-based index in that order."

        PRD 3.5: "At certification the pool is every donor whose `donor_status`
        is `ACTIVE` or `LAPSED`."

        Design: Corner/consistency_model/the_certify_response_carries_the_points_sum_computed_in_that_same_request
        """
        cycle, top, bottom = _a_communicated_cycle_over_two_donors(client)

        validate_success(_certify(client, cycle), 200)

        leader = read_donor(client, top["id"])
        assert_points(leader["certified_points"], "25.00", "certified_points")
        assert leader["rank_position"] == 1

        follower = read_donor(client, bottom["id"])
        assert_points(follower["certified_points"], "15.00", "certified_points")
        assert follower["rank_position"] == 2


class TestADerivedReadIsAPureFunctionOfStoredState:
    """Two identical retention reads: same numbers, and nothing moved underneath."""

    def test_the_first_read_buckets_both_donors_and_divides_by_two_divisors(
        self, client
    ):
        """One payload, two different denominators, both spelled out by 3.5.

        PRD 3.5: "This computed read requires the recalculation to be in
        `CERTIFIED` and is rejected with `ERR_RECALCULATION_NOT_CERTIFIED`
        otherwise."

        PRD 3.5: "It buckets the donors the cycle scored by the streak the cycle
        actually computed: `retained_donor_count` is the number of donors whose
        `consecutive_giving_years` is at least 2, `new_donor_count` is the number
        whose `consecutive_giving_years` equals exactly 1, and
        `lapsed_risk_donor_count` is the number whose `consecutive_giving_years`
        equals 0 while their `cumulative_giving_cents` is strictly greater than
        zero — a donor who has given historically but did not give in the streak
        window."

        PRD 3.5: "The `retention_rate` is `retained_donor_count` divided by the
        sum of `retained_donor_count` and `lapsed_risk_donor_count`, except that
        the divisor is 1 whenever that sum is zero, and the quotient is rounded
        half up to 4 decimal places."

        PRD 3.5: "The `average_certified_points` is the sum of
        `certified_points` across all scored donors divided by
        `donors_processed_count`, except that the divisor is 1 whenever
        `donors_processed_count` is zero, rounded half up to 2 decimal places."

        PRD 3.5: "The response returns `cycle_year`,
        `donors_processed_count`, `retained_donor_count`, `new_donor_count`,
        `lapsed_risk_donor_count`, `retention_rate`, `average_certified_points`
        and `certified_points_sum` inline as a single object rather than as a
        stored resource."

        Design: Corner/consistency_model/two_identical_reads_of_a_derived_payload_return_the_same_values_and_advance_nothing
        """
        cycle, _top, _bottom = _a_communicated_cycle_over_two_donors(client)
        validate_success(_certify(client, cycle), 200)

        report = retention(client, cycle["id"])

        assert report["cycle_year"] == 2026
        assert report["donors_processed_count"] == 2
        assert report["retained_donor_count"] == 0
        assert report["new_donor_count"] == 2
        assert report["lapsed_risk_donor_count"] == 0
        assert_points(
            report["certified_points_sum"], "40.00", "certified_points_sum"
        )
        # The two divisors are deliberately different: the rate divides by
        # max(1, 0 + 0) == 1 while the average divides by
        # donors_processed_count == 2, so one shared denominator cannot produce
        # 0.0000 and 20.00 at the same time.
        assert_ratio(report["retention_rate"], "0.0000", "retention_rate")
        assert_points(
            report["average_certified_points"], "20.00", "average_certified_points"
        )

    def test_a_second_read_by_another_role_returns_the_identical_payload(
        self, client
    ):
        """Field for field: a derived read materialises nothing on first access.

        PRD 3.5: "Once a cycle is certified, the office can read a retention
        picture off it."

        PRD 3.5: "The response returns `cycle_year`,
        `donors_processed_count`, `retained_donor_count`, `new_donor_count`,
        `lapsed_risk_donor_count`, `retention_rate`, `average_certified_points`
        and `certified_points_sum` inline as a single object rather than as a
        stored resource."

        PRD 2.9: "`seats_available`, `scheduled_slot_count`,
        `pending_request_count` and every other counter named in this document is
        a stored, readable field, not a value the client is expected to compute."

        Design: Corner/consistency_model/two_identical_reads_of_a_derived_payload_return_the_same_values_and_advance_nothing
        """
        cycle, _top, _bottom = _a_communicated_cycle_over_two_donors(client)
        validate_success(_certify(client, cycle), 200)

        first = retention(client, cycle["id"], headers=OFFICER)
        second = retention(client, cycle["id"], headers=CERTIFIER)

        for key in (
            "cycle_year",
            "donors_processed_count",
            "retained_donor_count",
            "new_donor_count",
            "lapsed_risk_donor_count",
        ):
            assert second[key] == first[key], (
                "{0} drifted between two reads: {1} then {2}".format(
                    key, first[key], second[key]
                )
            )
        assert_ratio(second["retention_rate"], first["retention_rate"], "retention_rate")
        assert_points(
            second["average_certified_points"],
            first["average_certified_points"],
            "average_certified_points",
        )
        assert_points(
            second["certified_points_sum"],
            first["certified_points_sum"],
            "certified_points_sum",
        )

    def test_neither_read_advanced_a_version_or_disturbed_a_donor(self, client):
        """A read is not a mutation, so no version stamp may move under it.

        PRD 2.4: "Most resources also carry `updated_at`, in the same format,
        refreshed on every mutation, and `version`, an integer that starts at 1
        on creation and increases by exactly 1 on each mutation that the
        specification says advances it."

        PRD 2.9: "A great deal of this service's state is derived, and derived
        state is recomputed **immediately and within the same request** as the
        change that invalidated it — there is no deferred sweep, no eventual
        reconciliation, and no endpoint whose only purpose is to refresh a
        counter."

        PRD 3.5: "The response returns `cycle_year`,
        `donors_processed_count`, `retained_donor_count`, `new_donor_count`,
        `lapsed_risk_donor_count`, `retention_rate`, `average_certified_points`
        and `certified_points_sum` inline as a single object rather than as a
        stored resource."

        Design: Corner/consistency_model/two_identical_reads_of_a_derived_payload_return_the_same_values_and_advance_nothing
        """
        cycle, top, _bottom = _a_communicated_cycle_over_two_donors(client)
        validate_success(_certify(client, cycle), 200)
        settled_cycle = read_cycle(client, cycle["id"])
        settled_donor = read_donor(client, top["id"])

        retention(client, cycle["id"], headers=OFFICER)
        retention(client, cycle["id"], headers=CERTIFIER)

        assert_version_unchanged(
            read_cycle(client, cycle["id"]),
            settled_cycle["version"],
            "recalculation",
        )
        after = read_donor(client, top["id"])
        assert_version_unchanged(after, settled_donor["version"], "donor")
        assert_points(after["certified_points"], "25.00", "certified_points")
        assert after["rank_position"] == 1
