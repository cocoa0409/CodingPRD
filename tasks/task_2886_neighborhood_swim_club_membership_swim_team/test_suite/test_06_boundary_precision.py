"""Two boundaries measured on different metrics through different endpoints."""

from test_helpers import (
    AssignmentStatus,
    JobCode,
    MeetStatus,
    Squad,
    Zone,
    assertions as a,
    canonical_instant,
    fixtures as fx,
    validate_success,
)
from test_helpers.test_users import POOL_MANAGER

PROBE_ISO = "2027-07-20T15:00:00Z"
PARTY_WINDOW = ("2027-07-20T14:00:00Z", "2027-07-20T18:00:00Z")


def _two_hosting_households(api):
    """Two separate COUPLE households, each with its own invoiced membership.

    They must be separate: a household holding an unpaid party charge is
    delinquent under PRD §3.4 and could not book the second party.
    """
    ctx = fx.setup_club(
        api,
        clock_iso="2027-07-06T09:00:00Z",
        category="COUPLE",
        member_count=2,
        household_overrides={
            "primary_contact_name": "Xu Household",
            "address_line": "21 Kickboard Row",
            "prior_member": False,
        },
        join_date="2027-05-22",
    )
    ctx["membership"] = fx.invoice_membership(api, ctx["membership"]["id"])
    second = fx.add_household(
        api, ctx, "Yates Household", member_count=2,
        address_line="23 Kickboard Row", prior_member=False,
    )
    second["membership"] = fx.invoice_membership(api, second["membership"]["id"])
    ctx["second"] = second
    return ctx


def _probe(api, season_id):
    return validate_success(
        api.get_staffing_window(season_id, POOL_MANAGER,
                                {"at_iso": PROBE_ISO}),
        200,
    )


def _book(api, membership_id, zone, guest_count, host_party_size):
    """Request a party over the shared window.

    PRD §3.7 pins the two headcount inputs asymmetrically: "a `guest_count` of
    non-member guests expected (which may be 0) and a `host_party_size` of
    household attendees of at least 1". A single-bather booking is therefore
    ``guest_count=0, host_party_size=1`` — ``host_party_size=0`` is refused as
    `ERR_VALIDATION` before the load is ever projected.
    """
    start_iso, end_iso = PARTY_WINDOW
    return fx.request_party(
        api, membership_id, zone=zone, start_iso=start_iso, end_iso=end_iso,
        guest_count=guest_count, host_party_size=host_party_size,
    )


class TestGuardRatioBoundaryAtFiftyBathers:
    """Fifty bathers need two guards; fifty-one need three."""

    def test_a_load_of_exactly_fifty_requires_two_guards(self, api):
        """The exact ratio multiple buys no extra guard.

        PRD §3.8: "The requirement is that load divided by the twenty-five
        bathers one guard may cover, rounded up to the next whole number, taken
        against the standing minimum of one guard, whichever is larger — plus one
        further guard when any of the overlapping reservations books
        `WHOLE_FACILITY`."

        Design: Difficulty/boundary_precision_check/guard_ratio_boundary_50_vs_51_bathers
        """
        ctx = _two_hosting_households(api)
        pavilion = _book(api, ctx["membership"]["id"], Zone.PAVILION, 45, 5)
        assert pavilion["projected_bather_load"] == 50

        window = _probe(api, ctx["season"]["id"])
        a.assert_staffing_window(
            window, bather_load=50, required_guard_count=2,
            scheduled_guard_count=0, compliant=False,
        )

    def test_one_bather_past_the_multiple_costs_a_whole_guard(self, api):
        """Fifty-one bathers over two zones demand a third pair of eyes.

        PRD §3.8: "The load is the sum of `guest_count` plus `host_party_size`
        over the season's reservations in `REQUESTED` or `CONFIRMED` whose window
        contains the instant, where a reservation's window is half-open: it
        includes `start_iso` and excludes `end_iso`, so back-to-back parties do
        not stack their loads."

        Design: Difficulty/boundary_precision_check/guard_ratio_boundary_50_vs_51_bathers
        """
        ctx = _two_hosting_households(api)
        _book(api, ctx["membership"]["id"], Zone.PAVILION, 45, 5)
        shallow = _book(api, ctx["second"]["membership"]["id"],
                        Zone.SHALLOW_END, 0, 1)
        assert shallow["projected_bather_load"] == 1

        window = _probe(api, ctx["season"]["id"])
        a.assert_staffing_window(
            window, bather_load=51, required_guard_count=3,
            scheduled_guard_count=0, compliant=False,
        )

    def test_each_reservation_prices_its_own_load_and_not_the_aggregate(
        self, api
    ):
        """Pricing sees one booking; the aggregate view is the window's job.

        PRD §3.7: "`required_guard_count` is derived from that load: divide the
        load by the twenty-five bathers each guard may cover and round up to the
        next whole number, take the larger of that figure and the standing
        minimum of one guard whenever the facility is open, and then add one
        further guard when the reserved `zone` is `WHOLE_FACILITY`, because the
        deep end needs its own eyes."

        Design: Difficulty/boundary_precision_check/guard_ratio_boundary_50_vs_51_bathers
        """
        ctx = _two_hosting_households(api)
        pavilion = _book(api, ctx["membership"]["id"], Zone.PAVILION, 45, 5)
        shallow = _book(api, ctx["second"]["membership"]["id"],
                        Zone.SHALLOW_END, 0, 1)

        assert pavilion["required_guard_count"] == 2
        assert shallow["required_guard_count"] == 1

    def test_no_confirmed_shift_means_no_coverage_at_either_boundary(self, api):
        """Scheduled_guard_count stays 0, so only the requirement moves.

        PRD §3.8: "Shifts merely `SCHEDULED` do not count toward coverage,
        because an unconfirmed guard may not show, and `SUPERVISOR` shifts never
        count at all."

        Design: Difficulty/boundary_precision_check/guard_ratio_boundary_50_vs_51_bathers
        """
        ctx = _two_hosting_households(api)
        _book(api, ctx["membership"]["id"], Zone.PAVILION, 45, 5)
        first = _probe(api, ctx["season"]["id"])
        _book(api, ctx["second"]["membership"]["id"], Zone.SHALLOW_END, 0, 1)
        second = _probe(api, ctx["season"]["id"])

        assert first["scheduled_guard_count"] == 0
        assert second["scheduled_guard_count"] == 0
        assert first["compliant"] is False
        assert second["compliant"] is False
        assert second["required_guard_count"] - first["required_guard_count"] == 1


def _three_meets_and_one_volunteer(api):
    """One CONFIRMED swimmer and three SCHEDULED meets at the degenerate end."""
    ctx = fx.setup_club(
        api,
        clock_iso="2027-07-06T09:00:00Z",
        category="COUPLE",
        member_count=2,
        household_overrides={
            "primary_contact_name": "Bhatt Household",
            "address_line": "9 Cabana Court",
            "prior_member": False,
        },
        join_date="2027-05-22",
    )
    ctx["membership"] = fx.invoice_membership(api, ctx["membership"]["id"])
    registration = fx.setup_confirmed_registration(
        api, ctx, swimmer_name="Anya Bhatt",
        swimmer_birthdate="2014-02-02", squad=Squad.JUNIOR,
    )

    zero_slot = fx.create_meet(
        api, ctx["season"]["id"], name="Zero Slot Time Trial",
        start_iso="2027-07-20T09:00:00Z", end_iso="2027-07-20T12:00:00Z",
        expected_swimmers=12, volunteer_slots_required=0,
    )
    one_filled = fx.create_meet(
        api, ctx["season"]["id"], name="Exactly One Slot Dual",
        start_iso="2027-07-21T09:00:00Z", end_iso="2027-07-21T12:00:00Z",
        expected_swimmers=20, volunteer_slots_required=1,
    )
    assignment = fx.assign_volunteer(
        api, one_filled["id"], registration["id"], JobCode.TIMER
    )
    one_empty = fx.create_meet(
        api, ctx["season"]["id"], name="One Slot Unfilled Dual",
        start_iso="2027-07-22T09:00:00Z", end_iso="2027-07-22T12:00:00Z",
        expected_swimmers=20, volunteer_slots_required=1,
    )
    ctx.update({
        "registration": registration,
        "zero_slot": zero_slot,
        "one_filled": one_filled,
        "one_empty": one_empty,
        "assignment": assignment,
    })
    return ctx


class TestRosterCloseBoundaryOnVolunteerCredits:
    """The inclusive comparison at the degenerate end of the credit scale."""

    def test_a_meet_requiring_zero_credits_closes_as_staffed(self, api):
        """The empty assignment set satisfies the requirement, not fails it.

        PRD §3.6: "When `volunteer_slots_filled` is greater than or equal to
        `volunteer_slots_required` the meet becomes `STAFFED`; the comparison is
        inclusive, so equality is sufficient and a meet requiring 0 credits
        qualifies with no assignments at all."

        Design: Difficulty/boundary_precision_check/volunteer_slots_required_zero_closes_roster_as_staffed_empty_set
        """
        ctx = _three_meets_and_one_volunteer(api)

        closed = fx.close_roster(api, ctx["zero_slot"]["id"])

        assert closed["status"] == MeetStatus.STAFFED
        assert closed["volunteer_slots_filled"] == 0
        assert closed["understaffed_penalty_cents"] == 0
        assert canonical_instant(closed["roster_closed_at"]) == \
            "2027-07-06T09:00:00Z"

    def test_exactly_one_credit_against_one_required_is_also_staffed(self, api):
        """Equality is sufficient, and the assignment keeps counting.

        PRD §3.6: "On that branch `roster_closed_at` is stamped with the logical
        clock and `understaffed_penalty_cents` is set to 0."

        Design: Difficulty/boundary_precision_check/volunteer_slots_required_zero_closes_roster_as_staffed_empty_set
        """
        ctx = _three_meets_and_one_volunteer(api)
        assert ctx["assignment"]["credit_value"] == 1

        closed = fx.close_roster(api, ctx["one_filled"]["id"])

        assert closed["status"] == MeetStatus.STAFFED
        assert closed["volunteer_slots_filled"] == 1
        assert closed["understaffed_penalty_cents"] == 0
        assert fx.read_assignment(
            api, ctx["assignment"]["id"]
        )["status"] == AssignmentStatus.ASSIGNED

    def test_one_credit_short_costs_7500_cents(self, api):
        """A single missing credit is the whole per-credit penalty.

        PRD §3.6: "When `volunteer_slots_filled` is strictly below
        `volunteer_slots_required` the meet becomes `UNDERSTAFFED`;
        `roster_closed_at` is stamped identically, and
        `understaffed_penalty_cents` is set to the credit shortfall — the
        requirement less the filled count — multiplied by seven thousand five
        hundred cents per missing credit."

        Design: Difficulty/boundary_precision_check/volunteer_slots_required_zero_closes_roster_as_staffed_empty_set
        """
        ctx = _three_meets_and_one_volunteer(api)

        closed = fx.close_roster(api, ctx["one_empty"]["id"])

        assert closed["status"] == MeetStatus.UNDERSTAFFED
        assert closed["volunteer_slots_filled"] == 0
        assert closed["understaffed_penalty_cents"] == 7500
        assert closed["roster_closed_at"] is not None

    def test_closing_a_roster_earns_nobody_any_credit(self, api):
        """Only COMPLETED assignments earn, and no meet has been hosted.

        PRD §3.6: "Moving an assignment to `COMPLETED` leaves
        `volunteer_slots_filled` unchanged, since `COMPLETED` remains inside the
        counted set, and raises the owning membership's
        `volunteer_credits_earned` by the assignment's `credit_value`."

        Design: Difficulty/boundary_precision_check/volunteer_slots_required_zero_closes_roster_as_staffed_empty_set
        """
        ctx = _three_meets_and_one_volunteer(api)
        for key in ("zero_slot", "one_filled", "one_empty"):
            fx.close_roster(api, ctx[key]["id"])

        membership = fx.read_membership(api, ctx["membership"]["id"])
        assert membership["volunteer_credits_earned"] == 0
