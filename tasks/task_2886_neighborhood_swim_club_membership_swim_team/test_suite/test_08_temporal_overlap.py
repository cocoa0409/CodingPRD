"""Two overlap rules with opposite adjacency verdicts on the same shape.

Guard shifts use a closed interval plus a thirty-minute separation buffer, so
touching is a violation; party zones use a half-open interval with no buffer, so
touching is legal. A single shared overlap helper cannot satisfy both.
"""

from test_helpers import (
    ApiErrorId,
    GuardShiftStatus,
    ReservationStatus,
    ShiftRole,
    Zone,
    assertions as a,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import guard_shift_payload, party_reservation_payload
from test_helpers.test_users import POOL_MANAGER

ANCHOR_START = "2027-07-20T09:00:00Z"
ANCHOR_END = "2027-07-20T13:00:00Z"
CANDIDATE_END = "2027-07-20T17:00:00Z"
CERTS_THROUGH = "2027-12-31"


def _guard_with_a_scheduled_anchor_shift(api):
    """One certified guard holding a SCHEDULED 09:00-13:00 watch.

    Both cards run through 2027-12-31, which is at or after the date of every
    candidate window's ``end_iso``, so the certification wall never fires and the
    rest buffer is the only rule left that can reject anything.
    """
    season = fx.setup_open_season(api, clock_iso="2027-07-06T09:00:00Z")
    guard = fx.setup_certified_guard(
        api, full_name="Ivy Okafor", expires_on=CERTS_THROUGH,
        hire_date="2027-05-01",
    )
    anchor = fx.schedule_shift(
        api, guard["lifeguard"]["id"], season["id"], ANCHOR_START, ANCHOR_END,
        shift_role=ShiftRole.PRIMARY,
    )
    assert anchor["status"] == GuardShiftStatus.SCHEDULED
    assert anchor["duration_hours"] == 4
    return {
        "season": season,
        "lifeguard_id": guard["lifeguard"]["id"],
        "anchor": anchor,
    }


def _attempt_shift(api, ctx, start_iso):
    payload = guard_shift_payload(
        lifeguard_id=ctx["lifeguard_id"], season_id=ctx["season"]["id"],
        shift_role=ShiftRole.SECONDARY, start_iso=start_iso,
        end_iso=CANDIDATE_END,
    )
    return api.create_guard_shift(payload, POOL_MANAGER)


class TestGuardShiftRestBufferIsClosedAndThirtyMinutesWide:
    """Touching is rejected, twenty-five minutes is rejected, thirty is allowed."""

    def test_two_shifts_that_merely_touch_are_rejected(self, api):
        """A zero-minute gap violates the buffer under the closed convention.

        PRD §3.8: "Two shifts that merely touch, where the earlier `end_iso`
        equals the new `start_iso`, are rejected; a gap of exactly thirty minutes
        is allowed."

        Design: Difficulty/resource_temporal_overlap/guard_shift_rest_buffer_closed_interval_rejects_adjacency_allows_exact_30_minutes
        """
        ctx = _guard_with_a_scheduled_anchor_shift(api)

        body = validate_error(
            _attempt_shift(api, ctx, "2027-07-20T13:00:00Z"),
            ApiErrorId.SHIFT_REST_BUFFER_VIOLATION, 409,
        )
        assert body["error_id"] != ApiErrorId.CERT_NOT_VALID_FOR_SHIFT

    def test_one_minute_short_of_the_buffer_is_still_a_violation(self, api):
        """Twenty-five minutes comes within thirty, so the guard gets no rest.

        PRD §3.8: "The scheduling conflict itself is the rest buffer: the guard
        may hold no other shift in `SCHEDULED` or `CONFIRMED` whose closed
        interval comes within thirty minutes of the new one."

        Design: Difficulty/resource_temporal_overlap/guard_shift_rest_buffer_closed_interval_rejects_adjacency_allows_exact_30_minutes
        """
        ctx = _guard_with_a_scheduled_anchor_shift(api)

        body = validate_error(
            _attempt_shift(api, ctx, "2027-07-20T13:25:00Z"),
            ApiErrorId.SHIFT_REST_BUFFER_VIOLATION, 409,
        )
        assert body["error_id"] != ApiErrorId.CERT_NOT_VALID_FOR_SHIFT

    def test_a_gap_of_exactly_thirty_minutes_is_accepted(self, api):
        """The buffer comparison is inclusive at exactly thirty minutes.

        PRD §3.8: "Two shifts that merely touch, where the earlier `end_iso`
        equals the new `start_iso`, are rejected; a gap of exactly thirty minutes
        is allowed."

        Design: Difficulty/resource_temporal_overlap/guard_shift_rest_buffer_closed_interval_rejects_adjacency_allows_exact_30_minutes
        """
        ctx = _guard_with_a_scheduled_anchor_shift(api)
        _attempt_shift(api, ctx, "2027-07-20T13:00:00Z")
        _attempt_shift(api, ctx, "2027-07-20T13:25:00Z")

        accepted = validate_success(
            _attempt_shift(api, ctx, "2027-07-20T13:30:00Z"), 201
        )
        assert accepted["status"] == GuardShiftStatus.SCHEDULED
        assert accepted["duration_hours"] == 3.5

    def test_only_the_accepted_attempt_adds_to_the_scheduled_hours(self, api):
        """Four hours plus three and a half; the rejections contributed nothing.

        PRD §3.8: "The guard's `scheduled_hours` — the sum of `duration_hours`
        over their shifts in `SCHEDULED`, `CONFIRMED` or `COMPLETED` — is
        recomputed and the guard's `version` advances."

        Design: Difficulty/resource_temporal_overlap/guard_shift_rest_buffer_closed_interval_rejects_adjacency_allows_exact_30_minutes
        """
        ctx = _guard_with_a_scheduled_anchor_shift(api)
        _attempt_shift(api, ctx, "2027-07-20T13:00:00Z")
        _attempt_shift(api, ctx, "2027-07-20T13:25:00Z")
        _attempt_shift(api, ctx, "2027-07-20T13:30:00Z")

        shifts, _ = validate_paginated(
            api.list_guard_shifts(
                POOL_MANAGER, {"lifeguard_id": ctx["lifeguard_id"]}
            )
        )
        assert len(shifts) == 2
        assert fx.read_lifeguard(
            api, ctx["lifeguard_id"]
        )["scheduled_hours"] == 7.5


PARTY_LOAD = dict(guest_count=4, host_party_size=2)


def _four_hosts_and_one_pavilion_anchor(api):
    """Four separate COUPLE households, the first holding a PAVILION booking.

    Each household books at most once: a household carrying an unsettled party
    charge is delinquent under PRD §3.4 and could not book again.
    """
    ctx = fx.setup_club(
        api,
        clock_iso="2027-07-06T09:00:00Z",
        category="COUPLE",
        member_count=2,
        household_overrides={
            "primary_contact_name": "Host One Household",
            "address_line": "1 Lane Line Way",
            "prior_member": False,
        },
        join_date="2027-05-22",
    )
    ctx["membership"] = fx.invoice_membership(api, ctx["membership"]["id"])

    hosts = []
    for index, name in enumerate(
        ("Host Two Household", "Host Three Household", "Host Four Household")
    ):
        host = fx.add_household(
            api, ctx, name, member_count=2,
            address_line=f"{index + 2} Lane Line Way", prior_member=False,
        )
        host["membership"] = fx.invoice_membership(api, host["membership"]["id"])
        hosts.append(host)
    ctx["hosts"] = hosts

    ctx["anchor"] = fx.request_party(
        api, ctx["membership"]["id"], zone=Zone.PAVILION,
        start_iso="2027-07-20T14:00:00Z", end_iso="2027-07-20T18:00:00Z",
        **PARTY_LOAD
    )
    return ctx


def _attempt_party(api, membership_id, zone, start_iso, end_iso):
    payload = party_reservation_payload(
        membership_id=membership_id, zone=zone, start_iso=start_iso,
        end_iso=end_iso, **PARTY_LOAD
    )
    return api.create_party_reservation(payload, POOL_MANAGER)


class TestPartyZoneConflictIsHalfOpenAndAsymmetric:
    """Adjacency is legal, a different zone is legal, WHOLE_FACILITY is not."""

    def test_the_anchor_prices_a_six_bather_pavilion_party(self, api):
        """Nothing in the setup approaches the capacity or the discount tiers.

        PRD §3.7: "Seventh, `subtotal_cents` is `base_facility_fee_cents` plus
        `guest_overage_fee_cents` plus `lifeguard_surcharge_cents` — the guard
        surcharge sits **inside** the discount base, and that is the step most
        easily got wrong."

        Design: Difficulty/resource_temporal_overlap/party_zone_half_open_interval_allows_adjacency_and_whole_facility_conflicts_every_zone
        """
        ctx = _four_hosts_and_one_pavilion_anchor(api)

        anchor = ctx["anchor"]
        assert anchor["projected_bather_load"] == 6
        assert anchor["required_guard_count"] == 1
        assert anchor["guest_overage_fee_cents"] == 0
        assert anchor["subtotal_cents"] == 14800
        assert anchor["member_discount_cents"] == 0
        assert anchor["total_charge_cents"] == 14800

    def test_a_party_starting_where_the_anchor_ends_is_accepted(self, api):
        """The opposite verdict from the guard-shift rule on the same shape.

        PRD §3.7: "Reservation windows are treated as half-open intervals that
        include the start instant and exclude the end instant, so two parties
        that merely abut — where one ends at the exact instant the next begins —
        do not overlap."

        Design: Difficulty/resource_temporal_overlap/party_zone_half_open_interval_allows_adjacency_and_whole_facility_conflicts_every_zone
        """
        ctx = _four_hosts_and_one_pavilion_anchor(api)

        adjacent = validate_success(
            _attempt_party(
                api, ctx["hosts"][0]["membership"]["id"], Zone.PAVILION,
                "2027-07-20T18:00:00Z", "2027-07-20T20:00:00Z",
            ),
            201,
        )
        assert adjacent["status"] == ReservationStatus.REQUESTED
        assert adjacent["zone"] == Zone.PAVILION

    def test_a_different_zone_inside_the_same_window_is_accepted(self, api):
        """The conflict relation is per-zone, not per-facility.

        PRD §3.7: "a `WHOLE_FACILITY` booking conflicts with every zone including
        itself, while `PAVILION` and `SHALLOW_END` conflict only with themselves,
        and a conflict is `ERR_ZONE_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/party_zone_half_open_interval_allows_adjacency_and_whole_facility_conflicts_every_zone
        """
        ctx = _four_hosts_and_one_pavilion_anchor(api)

        other_zone = validate_success(
            _attempt_party(
                api, ctx["hosts"][1]["membership"]["id"], Zone.SHALLOW_END,
                "2027-07-20T15:00:00Z", "2027-07-20T17:00:00Z",
            ),
            201,
        )
        assert other_zone["status"] == ReservationStatus.REQUESTED
        assert other_zone["zone"] == Zone.SHALLOW_END

    def test_whole_facility_collides_with_both_narrower_bookings(self, api):
        """Eighteen bathers is nowhere near capacity, so the zone rule fired.

        PRD §3.7: "The aggregate bather load of every `REQUESTED` and `CONFIRMED`
        reservation overlapping the requested half-open window, plus this
        reservation's own load, must not exceed the season's
        `bather_load_capacity`, or the request is
        `ERR_BATHER_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/party_zone_half_open_interval_allows_adjacency_and_whole_facility_conflicts_every_zone
        """
        ctx = _four_hosts_and_one_pavilion_anchor(api)
        _attempt_party(
            api, ctx["hosts"][0]["membership"]["id"], Zone.PAVILION,
            "2027-07-20T18:00:00Z", "2027-07-20T20:00:00Z",
        )
        _attempt_party(
            api, ctx["hosts"][1]["membership"]["id"], Zone.SHALLOW_END,
            "2027-07-20T15:00:00Z", "2027-07-20T17:00:00Z",
        )

        body = validate_error(
            _attempt_party(
                api, ctx["hosts"][2]["membership"]["id"], Zone.WHOLE_FACILITY,
                "2027-07-20T16:00:00Z", "2027-07-20T17:00:00Z",
            ),
            ApiErrorId.ZONE_DOUBLE_BOOKED, 409,
        )
        assert body["error_id"] != ApiErrorId.BATHER_CAPACITY_EXCEEDED

    def test_the_rejected_booking_leaves_no_row_and_no_charge(self, api):
        """Three reservations stand and the fourth host owes nothing.

        PRD §3.7: "A new reservation is born `REQUESTED` with `refunded_cents` at
        0, and its `total_charge_cents` is booked onto the household
        immediately: `party_charges_owed_cents` rises by that amount and the
        household's `version` advances."

        Design: Difficulty/resource_temporal_overlap/party_zone_half_open_interval_allows_adjacency_and_whole_facility_conflicts_every_zone
        """
        ctx = _four_hosts_and_one_pavilion_anchor(api)
        _attempt_party(
            api, ctx["hosts"][0]["membership"]["id"], Zone.PAVILION,
            "2027-07-20T18:00:00Z", "2027-07-20T20:00:00Z",
        )
        _attempt_party(
            api, ctx["hosts"][1]["membership"]["id"], Zone.SHALLOW_END,
            "2027-07-20T15:00:00Z", "2027-07-20T17:00:00Z",
        )
        _attempt_party(
            api, ctx["hosts"][2]["membership"]["id"], Zone.WHOLE_FACILITY,
            "2027-07-20T16:00:00Z", "2027-07-20T17:00:00Z",
        )

        rows, _ = validate_paginated(api.list_party_reservations(POOL_MANAGER))
        assert len(rows) == 3
        fourth = fx.read_household(api, ctx["hosts"][2]["household"]["id"])
        assert fourth["party_charges_owed_cents"] == 0

    def test_back_to_back_parties_do_not_stack_at_the_handover_instant(self, api):
        """At 18:00 only the later party counts, so the load is six not twelve.

        PRD §3.8: "The load is the sum of `guest_count` plus `host_party_size`
        over the season's reservations in `REQUESTED` or `CONFIRMED` whose window
        contains the instant, where a reservation's window is half-open: it
        includes `start_iso` and excludes `end_iso`, so back-to-back parties do
        not stack their loads."

        Design: Difficulty/resource_temporal_overlap/party_zone_half_open_interval_allows_adjacency_and_whole_facility_conflicts_every_zone
        """
        ctx = _four_hosts_and_one_pavilion_anchor(api)
        _attempt_party(
            api, ctx["hosts"][0]["membership"]["id"], Zone.PAVILION,
            "2027-07-20T18:00:00Z", "2027-07-20T20:00:00Z",
        )

        window = validate_success(
            api.get_staffing_window(
                ctx["season"]["id"], POOL_MANAGER,
                {"at_iso": "2027-07-20T18:00:00Z"},
            ),
            200,
        )
        a.assert_staffing_window(
            window, bather_load=6, required_guard_count=1,
            scheduled_guard_count=0, compliant=False,
        )
