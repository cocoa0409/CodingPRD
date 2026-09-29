"""Two conserved quantities and their compensating actions.

The guest-pass ledger is a non-monetary entitlement count whose every field
returns to its prior value; the capital reserve is a two-sided money identity
whose append-only side deliberately never returns.
"""

from test_helpers import (
    GuestSettlementPolicy,
    GuestVisitStatus,
    ProjectStatus,
    assertions as a,
    canonical_instant,
    fixtures as fx,
    validate_success,
)
from test_helpers.factories import transition_payload
from test_helpers.test_users import (
    BOARD_PRESIDENT,
    BOARD_PRESIDENT_USER_ID,
    TREASURER_USER_ID,
)

VOID_REASON = "Gate double-scanned the same party; duplicate entry removed"
CONTRIBUTION_NOTE = "Special assessment for the 2028 resurfacing programme"


def _household_holding_four_passes(api):
    """A FAMILY membership granting exactly four passes, invoiced and ACTIVE.

    The clock sits at 2027-07-20T12:00:00Z, an hour after the visit instant, so
    the visit is never recorded in the future.
    """
    ctx = fx.setup_club(
        api,
        clock_iso="2027-07-20T12:00:00Z",
        category="FAMILY",
        member_count=4,
        household_overrides={
            "primary_contact_name": "Alvarez Household",
            "address_line": "14 Poolside Lane",
            "prior_member": False,
        },
        join_date="2027-07-05",
        bond_payment_plan="INSTALLMENTS",
    )
    ctx["membership"] = fx.invoice_membership(api, ctx["membership"]["id"])
    ctx["household"] = fx.read_household(api, ctx["household"]["id"])
    return ctx


def _record_the_six_guest_visit(api, ctx):
    return fx.record_visit(
        api, ctx["membership"]["id"], ctx["household"]["id"],
        guest_count=6, visit_start_iso="2027-07-20T11:00:00Z",
        sponsor_name="Rosa Alvarez",
    )


class TestGuestPassConservationUnderVisitVoid:
    """Balance plus consumed always equals granted, and granted never moves."""

    def test_the_membership_puts_four_passes_in_hand_before_the_gate_opens(
        self, api
    ):
        """State zero: four granted, four in hand, none consumed, nothing owed.

        PRD §3.3: "The household's `guest_pass_allotment_granted` rises by the
        category's `guest_pass_allotment` and its `guest_pass_balance` rises by
        the same number, so the passes are in hand before the gate ever opens."

        Design: Difficulty/compensating_invariant/guest_pass_conservation_under_visit_void
        """
        ctx = _household_holding_four_passes(api)

        a.assert_household_pass_ledger(
            ctx["household"], granted=4, consumed=0, balance=4,
            fee_owed_cents=0,
        )

    def test_a_weekday_party_of_six_burns_four_passes_and_bills_two_guests(
        self, api
    ):
        """PASS_FIRST takes the smaller of balance and headcount, any day.

        PRD §3.5: "Under the `PASS_FIRST` variant, `passes_used` is the smaller
        of the household's current `guest_pass_balance` and the visit's
        `guest_count`, on every day of the week alike."

        Design: Difficulty/compensating_invariant/guest_pass_conservation_under_visit_void
        """
        ctx = _household_holding_four_passes(api)

        visit = _record_the_six_guest_visit(api, ctx)

        a.assert_visit_settlement(
            visit, passes_used=4, fee_charged_cents=1000, is_weekend=False,
            settlement_variant=GuestSettlementPolicy.PASS_FIRST,
        )

    def test_the_visit_moves_three_counters_and_leaves_the_grant_alone(self, api):
        """State one: the invariant holds at zero balance just as well.

        PRD §3.5: "The household's ledgers then move together:
        `guest_pass_balance` falls by `passes_used`, `guest_passes_consumed`
        rises by `passes_used`, and `guest_fee_owed_cents` rises by
        `fee_charged_cents`."

        Design: Difficulty/compensating_invariant/guest_pass_conservation_under_visit_void
        """
        ctx = _household_holding_four_passes(api)
        _record_the_six_guest_visit(api, ctx)

        household = fx.read_household(api, ctx["household"]["id"])
        a.assert_household_pass_ledger(
            household, granted=4, consumed=4, balance=0,
            fee_owed_cents=1000,
        )

    def test_the_void_keeps_its_compensation_amounts_on_the_visit_row(self, api):
        """A voided visit is not blanked; its figures are what get reversed.

        PRD §3.5: "Voiding moves the visit `RECORDED → VOIDED`, stamps
        `voided_at` with the logical clock, and reverses the ledger exactly:
        because a `VOIDED` visit no longer sits inside the `RECORDED` filter,
        `guest_passes_consumed` falls by that visit's `passes_used` and
        `guest_pass_balance` rises by the same number, while
        `guest_fee_owed_cents` falls by that visit's `fee_charged_cents`."

        Design: Difficulty/compensating_invariant/guest_pass_conservation_under_visit_void
        """
        ctx = _household_holding_four_passes(api)
        visit = _record_the_six_guest_visit(api, ctx)

        voided = fx.void_visit(api, visit["id"], reason=VOID_REASON)

        assert voided["status"] == GuestVisitStatus.VOIDED
        assert canonical_instant(voided["voided_at"]) == "2027-07-20T12:00:00Z"
        assert voided["passes_used"] == 4
        assert voided["fee_charged_cents"] == 1000

    def test_the_ledger_returns_bit_identical_on_all_four_counters(self, api):
        """State two equals state zero exactly, so the void drifted nothing.

        PRD §3.5: "`guest_pass_allotment_granted` is deliberately left untouched,
        which preserves the club's conservation identity: a household's
        `guest_pass_balance` plus its `guest_passes_consumed` always equals its
        `guest_pass_allotment_granted`."

        Design: Difficulty/compensating_invariant/guest_pass_conservation_under_visit_void
        """
        ctx = _household_holding_four_passes(api)
        before = ctx["household"]
        visit = _record_the_six_guest_visit(api, ctx)
        fx.void_visit(api, visit["id"], reason=VOID_REASON)

        after = fx.read_household(api, ctx["household"]["id"])
        a.assert_household_pass_ledger(
            after, granted=4, consumed=0, balance=4, fee_owed_cents=0,
        )
        counters = (
            "guest_pass_allotment_granted", "guest_passes_consumed",
            "guest_pass_balance", "guest_fee_owed_cents",
        )
        assert [after[f] for f in counters] == [before[f] for f in counters]
        assert after["party_charges_owed_cents"] == 0

    def test_the_compensation_is_a_forward_write_not_a_rollback(self, api):
        """Both writes advanced the household's version; history is not rewound.

        PRD §3.5: "Both the visit's `version` and the household's `version`
        advance."

        Design: Difficulty/compensating_invariant/guest_pass_conservation_under_visit_void
        """
        ctx = _household_holding_four_passes(api)
        versions = [ctx["household"]["version"]]
        visit = _record_the_six_guest_visit(api, ctx)
        versions.append(fx.read_household(api, ctx["household"]["id"])["version"])
        fx.void_visit(api, visit["id"], reason=VOID_REASON)
        versions.append(fx.read_household(api, ctx["household"]["id"])["version"])

        assert versions[0] < versions[1] < versions[2]


def _season_with_an_approved_project(api):
    """A season holding 200000 cents of reserve and one APPROVED project."""
    season = fx.setup_open_season(api, clock_iso="2027-07-06T09:00:00Z")
    season = fx.contribute_reserve(api, season["id"], 200000,
                                   note=CONTRIBUTION_NOTE)
    project = fx.setup_approved_project(
        api, season["id"], budget_cents=180000,
        title="Main tank plaster and tile",
    )
    return {"season": season, "project": project}


class TestCapitalReserveIdentityUnderFundThenCancel:
    """The identity is restored by moving money back, not by rewinding a total."""

    def test_the_assessment_raises_both_sides_and_allocates_nothing(self, api):
        """State zero: 200000 contributed, 200000 unallocated, 0 funded.

        PRD §3.10: "The `Treasurer` may book a lump special assessment against
        the season by naming an `amount_cents` and, optionally, a `note`
        explaining what the assessment is for; both `reserve_contributions_cents`
        and `reserve_unallocated_cents` rise by that amount and the season's
        `version` advances."

        Design: Difficulty/compensating_invariant/capital_reserve_identity_under_fund_then_cancel
        """
        ctx = _season_with_an_approved_project(api)

        a.assert_reserve_counters(ctx["season"], contributions=200000,
                                  unallocated=200000)
        assert ctx["project"]["funded_cents"] == 0
        a.assert_reserve_identity(ctx["season"], [ctx["project"]])

    def test_the_approval_is_under_two_person_control(self, api):
        """The treasurer proposed it and a different user approved it.

        PRD §3.10: "From `PROPOSED` the `BoardPresident` either approves the
        project — which records their own `X-User-ID` in `approved_by_user_id` —
        or rejects it, and both decisions are under the same two-person control
        that governs conduct sanctions: the deciding user may not be the
        `requested_by_user_id`, and a treasurer-turned-president approving their
        own proposal is `ERR_SEGREGATION_OF_DUTIES`."

        Design: Difficulty/compensating_invariant/capital_reserve_identity_under_fund_then_cancel
        """
        ctx = _season_with_an_approved_project(api)

        project = ctx["project"]
        a.assert_capital_project(project, ProjectStatus.APPROVED)
        assert project["requested_by_user_id"] == TREASURER_USER_ID
        assert project["approved_by_user_id"] == BOARD_PRESIDENT_USER_ID
        assert project["approved_by_user_id"] != project["requested_by_user_id"]

    def test_the_draw_moves_money_across_the_identity_and_creates_none(self, api):
        """State two: 50000 unallocated, 150000 funded, contributions unmoved.

        PRD §3.10: "A draw that passes raises `funded_cents` by the drawn amount
        and lowers `reserve_unallocated_cents` by the same amount while leaving
        `reserve_contributions_cents` untouched — money moves across the
        identity, it is not created or destroyed — and advances both the
        project's `version` and the season's `version`."

        Design: Difficulty/compensating_invariant/capital_reserve_identity_under_fund_then_cancel
        """
        ctx = _season_with_an_approved_project(api)

        funded = fx.draw_funds(api, ctx["project"]["id"], 150000,
                               ctx["project"]["version"])
        assert funded["status"] == ProjectStatus.FUNDED
        assert funded["funded_cents"] == 150000

        season = fx.read_season(api, ctx["season"]["id"])
        a.assert_reserve_counters(season, contributions=200000,
                                  unallocated=50000)
        a.assert_reserve_identity(season, [funded])

    def test_the_cancellation_returns_every_cent_it_held(self, api):
        """State three: funded zeroed, unallocated whole again, total unmoved.

        PRD §3.10: "The `BoardPresident` may cancel a project from `APPROVED`,
        from `FUNDED` or from `IN_PROGRESS`; every cent the project holds returns
        to `reserve_unallocated_cents`, `funded_cents` is set to 0,
        `reserve_contributions_cents` is again untouched, and both the project's
        and the season's `version` advance."

        Design: Difficulty/compensating_invariant/capital_reserve_identity_under_fund_then_cancel
        """
        ctx = _season_with_an_approved_project(api)
        fx.draw_funds(api, ctx["project"]["id"], 150000,
                      ctx["project"]["version"])

        cancelled = validate_success(
            api.transition_capital_project(
                ctx["project"]["id"],
                transition_payload(ProjectStatus.CANCELLED), BOARD_PRESIDENT,
            ),
            200,
        )
        assert cancelled["status"] == ProjectStatus.CANCELLED
        assert cancelled["funded_cents"] == 0

        season = fx.read_season(api, ctx["season"]["id"])
        a.assert_reserve_counters(season, contributions=200000,
                                  unallocated=200000)
        a.assert_reserve_identity(season, [cancelled])

    def test_a_cancelled_project_is_excluded_twice_and_subtracted_once(self, api):
        """Zeroed money and an excluded status agree, so nothing double-counts.

        PRD §3.10: "Projects in `PROPOSED`, `APPROVED` or `REJECTED` contribute
        nothing to the allocated side because they hold no money, and a
        `CANCELLED` project contributes nothing because its `funded_cents` has
        been zeroed, so the identity holds arithmetically for every project in
        the system without special-casing any status."

        Design: Difficulty/compensating_invariant/capital_reserve_identity_under_fund_then_cancel
        """
        ctx = _season_with_an_approved_project(api)
        fx.draw_funds(api, ctx["project"]["id"], 150000,
                      ctx["project"]["version"])
        validate_success(
            api.transition_capital_project(
                ctx["project"]["id"],
                transition_payload(ProjectStatus.CANCELLED), BOARD_PRESIDENT,
            ),
            200,
        )

        project = fx.read_project(api, ctx["project"]["id"])
        season = fx.read_season(api, ctx["season"]["id"])
        assert project["status"] == ProjectStatus.CANCELLED
        assert project["funded_cents"] == 0
        assert season["reserve_unallocated_cents"] == 200000
        a.assert_reserve_identity(season, [project])

    def test_the_append_only_side_never_moved_at_any_observation(self, api):
        """Contributions read 200000 four times over; both versions advanced.

        PRD §3.10: "`reserve_contributions_cents` is append-only in the
        strictest sense: it never decreases."

        Design: Difficulty/compensating_invariant/capital_reserve_identity_under_fund_then_cancel
        """
        ctx = _season_with_an_approved_project(api)
        contributions = [ctx["season"]["reserve_contributions_cents"]]
        season_versions = [ctx["season"]["version"]]
        project_versions = [ctx["project"]["version"]]

        funded = fx.draw_funds(api, ctx["project"]["id"], 150000,
                               ctx["project"]["version"])
        season = fx.read_season(api, ctx["season"]["id"])
        contributions.append(season["reserve_contributions_cents"])
        season_versions.append(season["version"])
        project_versions.append(funded["version"])

        cancelled = validate_success(
            api.transition_capital_project(
                ctx["project"]["id"],
                transition_payload(ProjectStatus.CANCELLED), BOARD_PRESIDENT,
            ),
            200,
        )
        season = fx.read_season(api, ctx["season"]["id"])
        contributions.append(season["reserve_contributions_cents"])
        season_versions.append(season["version"])
        project_versions.append(cancelled["version"])

        assert contributions == [200000, 200000, 200000]
        assert season_versions[0] < season_versions[1] < season_versions[2]
        assert project_versions[0] < project_versions[1] < project_versions[2]
