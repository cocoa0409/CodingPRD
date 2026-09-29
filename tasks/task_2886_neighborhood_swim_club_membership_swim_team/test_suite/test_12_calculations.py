"""Arithmetic corners: arm boundaries, inclusive tiers and disagreeing inputs.

Each case here pins a figure that a plausible simplification gets wrong — the
unprorated arm collapsed into the ratio arm, a strict discount boundary, a
half-cent rounded down, a filter applied on the wrong field, or a standing map
read from one of its two inputs instead of both.
"""

from test_helpers import (
    AccessStatus,
    CaseSeverity,
    CaseStatus,
    DuesStatus,
    FacilityPosture,
    FindingSeverity,
    FindingStatus,
    GuestSettlementPolicy,
    HouseholdStanding,
    ProrationBasis,
    RegistrationStatus,
    SanctionType,
    SeasonStatus,
    Squad,
    Zone,
    assertions as a,
    canonical_instant,
    fixtures as fx,
)
from test_helpers.test_users import (
    BOARD_PRESIDENT,
    HEALTH_INSPECTOR,
    HEALTH_INSPECTOR_2,
    POOL_MANAGER,
)


def _two_couple_memberships_one_day_apart(api):
    """One category, one season, two join dates one day apart.

    The season runs 2027-05-22 .. 2027-09-06, so `total_days` is 108 with both
    endpoints included, and its `dues_due_date` of 2027-04-15 is already behind
    the clock, which keeps the late-penalty line live on both invoices.
    """
    fx.set_clock(api, "2027-05-23T09:00:00Z")
    category = fx.create_couple_category(api)
    season = fx.setup_open_season(api)
    house_a = fx.create_household(
        api, primary_contact_name="Household On Open Date",
        address_line="121 Cedar Court", member_count=2, prior_member=False,
    )
    house_b = fx.create_household(
        api, primary_contact_name="Household One Day Later",
        address_line="122 Cedar Court", member_count=2, prior_member=False,
    )
    return {
        "category": category,
        "season": season,
        "membership_a": fx.setup_membership(
            api, house_a["id"], category["id"], season["id"],
            join_date="2027-05-22",
        ),
        "membership_b": fx.setup_membership(
            api, house_b["id"], category["id"], season["id"],
            join_date="2027-05-23",
        ),
    }


class TestJoiningOnTheOpenDateBillsTheUnproratedDues:
    """The second arm returns the category figure, not a 108/108 ratio."""

    def test_a_join_on_the_open_date_takes_the_category_figure_unchanged(
        self, api
    ):
        """30000 exactly, stamped before any invoice exists.

        PRD §3.3: "Otherwise, if the effective start is at or before the season's
        `open_date`, the household is charged the category's full
        `seasonal_dues_cents` with no proration whatsoever."

        PRD §3.3: "`assessed_dues_cents` is stamped exactly once, while the
        membership is still `UNBILLED`, and is never re-derived."

        Design: Corner/calculations/correct_result_joining_on_the_open_date_bills_the_unprorated_dues
        """
        ctx = _two_couple_memberships_one_day_apart(api)

        assert ctx["season"]["proration_basis"] == ProrationBasis.CALENDAR_DAY
        membership = ctx["membership_a"]
        a.assert_membership(membership, DuesStatus.UNBILLED,
                            AccessStatus.PENDING)
        assert membership["assessed_dues_cents"] == 30000
        assert (
            membership["assessed_dues_cents"]
            == ctx["category"]["seasonal_dues_cents"]
        )

    def test_one_day_later_the_ratio_arm_fires_and_the_answer_differs(self, api):
        """29722 is round_half_up(30000 * 107 / 108), 278 cents below A.

        PRD §3.3: "under `CALENDAR_DAY` the assessment is the category's
        `seasonal_dues_cents` multiplied by the remaining calendar days and
        divided by the total calendar days, with the single final result rounded
        half up to a whole cent"

        Design: Corner/calculations/correct_result_joining_on_the_open_date_bills_the_unprorated_dues
        """
        ctx = _two_couple_memberships_one_day_apart(api)

        assert ctx["membership_b"]["assessed_dues_cents"] == 29722
        assert (
            ctx["membership_a"]["assessed_dues_cents"]
            - ctx["membership_b"]["assessed_dues_cents"]
        ) == 278

    def test_each_invoice_reuses_its_own_stamped_figure_for_the_penalty(
        self, api
    ):
        """1050 against 30000 and 1040 against 29722; no shared constant works.

        PRD §3.4: "Line 5 is the late penalty, written to `late_penalty_cents`:
        take the sum of the four already-rounded lines above as the penalty base,
        and when the logical clock's date is strictly later than the season's
        `dues_due_date`, the penalty is that base multiplied by three and one half
        per cent, rounded half up to a whole cent; when the clock's date is at or
        before the due date the penalty is 0."

        Design: Corner/calculations/correct_result_joining_on_the_open_date_bills_the_unprorated_dues
        """
        ctx = _two_couple_memberships_one_day_apart(api)

        invoice_a = fx.invoice_membership(api, ctx["membership_a"]["id"])
        invoice_b = fx.invoice_membership(api, ctx["membership_b"]["id"])

        a.assert_invoice_lines(
            invoice_a, dues=30000, initiation=0, bond_installment=0,
            swim_team_fee=0, late_penalty=1050, invoice_total=31050,
        )
        a.assert_invoice_lines(
            invoice_b, dues=29722, initiation=0, bond_installment=0,
            swim_team_fee=0, late_penalty=1040, invoice_total=30762,
        )
        assert invoice_a["late_penalty_cents"] != invoice_b["late_penalty_cents"]


def _a_settled_membership_with_one_confirmed_swimmer(api):
    """One swimmer registered before the invoice and confirmed after it.

    The registration is `PENDING` when Line 4 is assembled, so it is billed, and
    `CONFIRMED` afterwards, so the volunteer requirement appears only once the
    invoice has already been cut and settled.
    """
    fx.set_clock(api, "2027-05-22T09:00:00Z")
    category = fx.create_couple_category(api)
    season = fx.setup_open_season(api)
    household = fx.create_household(
        api, primary_contact_name="Buyout Household",
        address_line="131 Cedar Court", member_count=2, prior_member=False,
    )
    created = fx.setup_membership(
        api, household["id"], category["id"], season["id"],
        join_date="2027-05-22",
    )
    registration = fx.register_swimmer(
        api, created["id"], season["id"], swimmer_name="Tess Alard",
        swimmer_birthdate="2013-04-04", squad=Squad.JUNIOR,
    )
    invoiced = fx.invoice_membership(api, created["id"])
    fx.transition_registration(api, registration["id"],
                               RegistrationStatus.CONFIRMED)
    confirmed = fx.read_membership(api, created["id"])
    return {
        "season": season,
        "household": household,
        "created": created,
        "registration": registration,
        "invoiced": invoiced,
        "confirmed": confirmed,
        "paid": fx.pay_membership_in_full(api, created["id"]),
    }


class TestVolunteerBuyoutAtSeasonCloseReopensASettledBalance:
    """The one backwards edge on the money dimension, and what it may not touch."""

    def test_the_invoice_bills_the_pending_swimmer_and_no_credits_yet(self, api):
        """Line 4 is 14500 while the requirement is still 0.

        PRD §3.6: "each swimmer past the first earns a further six and one quarter
        per cent off the base swim-team fee of fourteen thousand five hundred
        cents, and the accumulated discount rate is capped at twenty-five per
        cent, so the fourth and every later swimmer share the same capped rate"

        PRD §3.6: "A membership's `volunteer_credits_required` is not a fixed
        number but a derived one: the category's `volunteer_credits_required`
        multiplied by the count of that membership's registrations whose `status`
        is `CONFIRMED` or `COMPLETED`, with the product capped at ten credits."

        Design: Corner/calculations/correct_result_volunteer_buyout_at_season_close_reopens_a_settled_balance
        """
        ctx = _a_settled_membership_with_one_confirmed_swimmer(api)

        assert ctx["registration"]["squad_seq"] == 1
        assert ctx["registration"]["assessed_fee_cents"] == 14500
        assert ctx["created"]["volunteer_credits_required"] == 0
        assert ctx["invoiced"]["swim_team_fee_cents"] == 14500
        assert ctx["invoiced"]["volunteer_credits_required"] == 0

    def test_the_penalty_rounds_the_half_cent_up_on_a_44500_base(self, api):
        """44500 * 0.035 is 1557.5 exactly, so the answer is 1558 and not 1557.

        PRD §3.4: "`invoice_total_cents` is the penalty base plus the penalty."

        Design: Corner/calculations/correct_result_volunteer_buyout_at_season_close_reopens_a_settled_balance
        """
        ctx = _a_settled_membership_with_one_confirmed_swimmer(api)

        a.assert_invoice_lines(
            ctx["invoiced"], dues=30000, initiation=0, bond_installment=0,
            swim_team_fee=14500, late_penalty=1558, invoice_total=46058,
        )

    def test_confirming_the_swimmer_raises_the_requirement_after_the_invoice(
        self, api
    ):
        """The requirement becomes 2 while the buyout stays 0 until close.

        PRD §3.6: "Either confirmation recomputes the membership's
        `volunteer_credits_required` and its `swim_team_fee_cents`."

        PRD §3.4: "a payment equal to the balance — driving `balance_due_cents` to
        0 — moves `INVOICED → PAID` or `DELINQUENT → PAID`"

        Design: Corner/calculations/correct_result_volunteer_buyout_at_season_close_reopens_a_settled_balance
        """
        ctx = _a_settled_membership_with_one_confirmed_swimmer(api)

        assert ctx["confirmed"]["volunteer_credits_required"] == 2
        assert ctx["confirmed"]["volunteer_credits_earned"] == 0
        assert ctx["confirmed"]["volunteer_buyout_cents"] == 0

        paid = ctx["paid"]
        a.assert_membership(paid, DuesStatus.PAID, AccessStatus.ACTIVE)
        assert paid["amount_paid_cents"] == 46058
        assert paid["balance_due_cents"] == 0

    def test_closing_the_season_assesses_the_buyout_and_reopens_the_balance(
        self, api
    ):
        """7000 of buyout, a 7000 balance, and PAID walks back to INVOICED.

        PRD §3.1: "Then, for each membership of the season, the earned volunteer
        credits are recomputed, the volunteer buyout is assessed as described in
        §3.6 and folded into `balance_due_cents` — and any membership whose
        recomputed `balance_due_cents` is greater than zero while its
        `dues_status` was `PAID` moves `dues_status` backwards to `INVOICED`."

        PRD §3.6: "The shortfall is the required figure less the earned figure,
        floored at 0, and `volunteer_buyout_cents` is that shortfall multiplied by
        three thousand five hundred cents per unworked credit."

        Design: Corner/calculations/correct_result_volunteer_buyout_at_season_close_reopens_a_settled_balance
        """
        ctx = _a_settled_membership_with_one_confirmed_swimmer(api)
        fx.set_clock(api, "2027-09-06T20:00:00Z")

        closed = fx.close_season(api, ctx["season"]["id"])
        a.assert_season(closed, SeasonStatus.CLOSED, FacilityPosture.CLOSED)

        registration = fx.read_registration(api, ctx["registration"]["id"])
        assert registration["status"] == RegistrationStatus.COMPLETED

        membership = fx.read_membership(api, ctx["created"]["id"])
        a.assert_membership(membership, DuesStatus.INVOICED,
                            AccessStatus.LAPSED)
        assert membership["volunteer_credits_required"] == 2
        assert membership["volunteer_credits_earned"] == 0
        assert membership["volunteer_buyout_cents"] == 7000
        assert membership["balance_due_cents"] == 7000

    def test_the_reopening_re_derives_nothing_but_the_buyout_and_balance(
        self, api
    ):
        """The invoice total, the payment and Line 1 are all left alone.

        PRD §3.1: "On that edge, `invoice_total_cents`, `amount_paid_cents` and
        `assessed_dues_cents` are **not** re-derived; only the buyout line and the
        balance move."

        Design: Corner/calculations/correct_result_volunteer_buyout_at_season_close_reopens_a_settled_balance
        """
        ctx = _a_settled_membership_with_one_confirmed_swimmer(api)
        fx.set_clock(api, "2027-09-06T20:00:00Z")
        fx.close_season(api, ctx["season"]["id"])

        membership = fx.read_membership(api, ctx["created"]["id"])
        a.assert_invoice_lines(
            membership, dues=30000, initiation=0, bond_installment=0,
            swim_team_fee=14500, late_penalty=1558, invoice_total=46058,
        )
        assert membership["amount_paid_cents"] == 46058


MINOR_FINDINGS = (
    ("SIGNAGE-01", "Depth marker paint faded at the 3-foot mark."),
    ("SIGNAGE-02", "Rescue-tube storage clip missing from the north stand."),
    ("SIGNAGE-03", "Bather-load placard illegible at the gate."),
)
CHLORINE_NARRATIVE = (
    "Free chlorine below the required minimum on two consecutive readings."
)
GATE_NARRATIVE = "Self-latching gate fails to latch from the pull side."
REMEDIATION_NOTE = "Chlorinator feed rate corrected; two clear readings logged."


def _three_minor_findings(api, season_id):
    """Three MINOR citations filed by hi-001 against an otherwise clean season."""
    return [
        fx.file_finding(
            api, season_id, FindingSeverity.MINOR, headers=HEALTH_INSPECTOR,
            inspected_on="2027-06-10", finding_code=code, narrative=narrative,
        )
        for code, narrative in MINOR_FINDINGS
    ]


def _file_major(api, season_id, finding_code, narrative):
    return fx.file_finding(
        api, season_id, FindingSeverity.MAJOR, headers=HEALTH_INSPECTOR,
        inspected_on="2027-06-11", finding_code=finding_code,
        narrative=narrative,
    )


class TestOnlyOpenMajorFindingsMoveThePosture:
    """Three independent filters — severity, status and verification."""

    def test_three_minor_findings_change_neither_counter_nor_posture(self, api):
        """MINOR is excluded by severity however many of them are open.

        PRD §3.1: "Among those open findings, `open_critical_finding_count` is the
        number whose `severity` is `CRITICAL` and `open_major_finding_count` is
        the number whose `severity` is `MAJOR`. Findings of `severity` `MINOR` are
        counted in neither and never affect posture at all."

        Design: Corner/calculations/input_set_filtering_only_open_major_findings_move_the_posture
        """
        season = fx.setup_open_season(api, clock_iso="2027-06-10T09:00:00Z")
        a.assert_season(season, SeasonStatus.OPEN, FacilityPosture.OPEN)
        assert season["open_major_finding_count"] == 0
        assert season["open_critical_finding_count"] == 0

        minors = _three_minor_findings(api, season["id"])
        assert len(minors) == 3

        after = fx.read_season(api, season["id"])
        a.assert_season(after, SeasonStatus.OPEN, FacilityPosture.OPEN)
        assert after["open_major_finding_count"] == 0

    def test_the_major_threshold_is_inclusive_and_fires_at_exactly_two(
        self, api
    ):
        """One MAJOR leaves the pool open; the second restricts it.

        PRD §3.1: "otherwise, if at least one critical finding is open, the
        posture is `CLOSED`; otherwise, if two or more major findings are open,
        the posture is `RESTRICTED`; otherwise the posture is `OPEN`. Two major
        findings restrict the facility — the threshold is inclusive."

        Design: Corner/calculations/input_set_filtering_only_open_major_findings_move_the_posture
        """
        season = fx.setup_open_season(api, clock_iso="2027-06-10T09:00:00Z")
        _three_minor_findings(api, season["id"])

        first = _file_major(api, season["id"], "CHEM-04", CHLORINE_NARRATIVE)
        a.assert_inspection_finding(first, FindingStatus.OPEN)
        one_major = fx.read_season(api, season["id"])
        a.assert_season(one_major, SeasonStatus.OPEN, FacilityPosture.OPEN)
        assert one_major["open_major_finding_count"] == 1

        _file_major(api, season["id"], "FENCE-07", GATE_NARRATIVE)

        two_majors = fx.read_season(api, season["id"])
        a.assert_season(two_majors, SeasonStatus.OPEN,
                        FacilityPosture.RESTRICTED)
        assert two_majors["open_major_finding_count"] == 2
        assert two_majors["closure_started_at"] is None

    def test_a_submitted_remediation_is_still_an_open_finding(self, api):
        """Submitting a fix keeps the finding inside the counted set.

        PRD §3.1: "The derivation first counts the season's **open findings**,
        meaning findings whose `status` is `OPEN`, `REMEDIATION_SUBMITTED` or
        `REOPENED`; findings in `VERIFIED_CLOSED` never contribute no matter how
        severe they were."

        Design: Corner/calculations/input_set_filtering_only_open_major_findings_move_the_posture
        """
        season = fx.setup_open_season(api, clock_iso="2027-06-10T09:00:00Z")
        _three_minor_findings(api, season["id"])
        first = _file_major(api, season["id"], "CHEM-04", CHLORINE_NARRATIVE)
        _file_major(api, season["id"], "FENCE-07", GATE_NARRATIVE)

        submitted = fx.transition_finding(
            api, first["id"], FindingStatus.REMEDIATION_SUBMITTED,
            POOL_MANAGER, remediation_note=REMEDIATION_NOTE,
        )
        assert submitted["status"] == FindingStatus.REMEDIATION_SUBMITTED

        after = fx.read_season(api, season["id"])
        a.assert_season(after, SeasonStatus.OPEN, FacilityPosture.RESTRICTED)
        assert after["open_major_finding_count"] == 2

    def test_only_verification_removes_a_finding_from_the_input_set(self, api):
        """The count falls to one and the restriction lifts; the MINORs are still open.

        PRD §3.1: "Only the inspector may verify-close: moving
        `REMEDIATION_SUBMITTED → VERIFIED_CLOSED` requires that `X-User-ID` differ
        from the finding's `recorded_by_user_id`, stamps `verified_by_user_id` with
        the acting user, recomputes both finding counters, re-derives the posture"

        Design: Corner/calculations/input_set_filtering_only_open_major_findings_move_the_posture
        """
        season = fx.setup_open_season(api, clock_iso="2027-06-10T09:00:00Z")
        minors = _three_minor_findings(api, season["id"])
        first = _file_major(api, season["id"], "CHEM-04", CHLORINE_NARRATIVE)
        _file_major(api, season["id"], "FENCE-07", GATE_NARRATIVE)
        fx.transition_finding(
            api, first["id"], FindingStatus.REMEDIATION_SUBMITTED,
            POOL_MANAGER, remediation_note=REMEDIATION_NOTE,
        )

        verified = fx.transition_finding(
            api, first["id"], FindingStatus.VERIFIED_CLOSED, HEALTH_INSPECTOR_2
        )
        assert verified["status"] == FindingStatus.VERIFIED_CLOSED

        after = fx.read_season(api, season["id"])
        a.assert_season(after, SeasonStatus.OPEN, FacilityPosture.OPEN)
        assert after["open_major_finding_count"] == 1
        for minor in minors:
            assert fx.read_finding(
                api, minor["id"]
            )["status"] == FindingStatus.OPEN


def _two_zero_pass_households(api):
    """Two SINGLE memberships whose category grants no guest passes at all.

    The clock sits at 2027-07-11T09:00Z, later than both visit instants, and the
    two visits are recorded against separate households because the first fee
    would otherwise make its own household delinquent.
    """
    fx.set_clock(api, "2027-07-11T09:00:00Z")
    category = fx.create_single_category(api)
    season = fx.setup_open_season(
        api, guest_settlement_policy=GuestSettlementPolicy.PASS_FIRST
    )
    ctx = {"category": category, "season": season}
    for key, name, address in (
        ("a", "Weekend Guest Household", "141 Cedar Court"),
        ("b", "Weekday Guest Household", "142 Cedar Court"),
    ):
        household = fx.create_household(
            api, primary_contact_name=name, address_line=address,
            member_count=1, prior_member=False,
        )
        membership = fx.setup_membership(
            api, household["id"], category["id"], season["id"],
            join_date="2027-07-01",
        )
        ctx[f"household_{key}"] = household
        ctx[f"membership_{key}"] = fx.invoice_membership(api, membership["id"])
    return ctx


def _record_the_saturday_visit(api, ctx):
    return fx.record_visit(
        api, ctx["membership_a"]["id"], ctx["household_a"]["id"],
        guest_count=3, visit_start_iso="2027-07-10T14:00:00Z",
        sponsor_name="Saturday Trio",
    )


def _record_the_thursday_visit(api, ctx):
    return fx.record_visit(
        api, ctx["membership_b"]["id"], ctx["household_b"]["id"],
        guest_count=3, visit_start_iso="2027-07-08T14:00:00Z",
        sponsor_name="Thursday Trio",
    )


class TestWeekendAndWeekdayGuestFeesUseDistinctRates:
    """Identical guest counts, two days of the week, two different fees."""

    def test_the_pass_arm_is_inert_and_the_variant_comes_from_the_season(
        self, api
    ):
        """Zero passes granted, and the visit copies the season's policy.

        PRD §3.3: "The household's `guest_pass_allotment_granted` rises by the
        category's `guest_pass_allotment` and its `guest_pass_balance` rises by
        the same number, so the passes are in hand before the gate ever opens."

        PRD §3.5: "depends on the day of the week and on the season's
        `guest_settlement_policy`, which is copied onto the visit as its
        `settlement_variant` so the historical record survives a later policy
        change"

        Design: Corner/calculations/constants_applied_weekend_and_weekday_guest_fees_use_distinct_rates
        """
        ctx = _two_zero_pass_households(api)

        assert ctx["category"]["guest_pass_allotment"] == 0
        assert (
            ctx["season"]["guest_settlement_policy"]
            == GuestSettlementPolicy.PASS_FIRST
        )
        household = fx.read_household(api, ctx["household_a"]["id"])
        a.assert_household_pass_ledger(
            household, granted=0, consumed=0, balance=0, fee_owed_cents=0,
        )

        visit = _record_the_saturday_visit(api, ctx)
        assert visit["settlement_variant"] == GuestSettlementPolicy.PASS_FIRST

    def test_the_same_three_guests_cost_2400_on_saturday_and_1500_on_thursday(
        self, api
    ):
        """Eight hundred against five hundred cents a guest, and nothing else.

        PRD §3.5: "`is_weekend` is derived from `visit_start_iso` and is true when
        that instant falls on a Saturday or a Sunday in UTC. The unit fee follows
        from it: eight hundred cents per guest on a weekend, five hundred cents
        per guest on a weekday."

        PRD §3.5: "The billable guest count is `guest_count` less `passes_used`,
        and `fee_charged_cents` is that billable count multiplied by the unit fee;
        every term is an integer, so no rounding arises."

        Design: Corner/calculations/constants_applied_weekend_and_weekday_guest_fees_use_distinct_rates
        """
        ctx = _two_zero_pass_households(api)

        weekend = _record_the_saturday_visit(api, ctx)
        weekday = _record_the_thursday_visit(api, ctx)

        a.assert_visit_settlement(
            weekend, passes_used=0, fee_charged_cents=2400, is_weekend=True,
            settlement_variant=GuestSettlementPolicy.PASS_FIRST,
        )
        a.assert_visit_settlement(
            weekday, passes_used=0, fee_charged_cents=1500, is_weekend=False,
            settlement_variant=GuestSettlementPolicy.PASS_FIRST,
        )
        assert weekend["guest_count"] == weekday["guest_count"] == 3
        assert weekend["fee_charged_cents"] != weekday["fee_charged_cents"]

    def test_each_fee_lands_on_its_own_household_and_moves_no_pass_counter(
        self, api
    ):
        """Two ledgers, two different amounts, and no pass anywhere to spend.

        PRD §3.5: "The household's ledgers then move together:
        `guest_pass_balance` falls by `passes_used`, `guest_passes_consumed` rises
        by `passes_used`, and `guest_fee_owed_cents` rises by
        `fee_charged_cents`."

        Design: Corner/calculations/constants_applied_weekend_and_weekday_guest_fees_use_distinct_rates
        """
        ctx = _two_zero_pass_households(api)
        _record_the_saturday_visit(api, ctx)
        _record_the_thursday_visit(api, ctx)

        weekend_household = fx.read_household(api, ctx["household_a"]["id"])
        weekday_household = fx.read_household(api, ctx["household_b"]["id"])

        a.assert_household_pass_ledger(
            weekend_household, granted=0, consumed=0, balance=0,
            fee_owed_cents=2400,
        )
        a.assert_household_pass_ledger(
            weekday_household, granted=0, consumed=0, balance=0,
            fee_owed_cents=1500,
        )


PARTY_LOAD = dict(guest_count=12, host_party_size=14)


def _two_party_ready_households(api):
    """Two COUPLE households whose bond is settled at zero cents.

    The category's `bond_cents` is 0, so the bond gate of §3.7 is satisfied
    without a payment, and each household books at most once because a household
    carrying an unsettled party charge would fail the delinquency gate.
    """
    fx.set_clock(api, "2027-07-01T09:00:00Z")
    category = fx.create_couple_category(api)
    season = fx.setup_open_season(api)
    ctx = {"category": category, "season": season}
    for key, name, address in (
        ("a", "Four Hour Party Household", "151 Cedar Court"),
        ("b", "Three Hour Party Household", "152 Cedar Court"),
    ):
        household = fx.create_household(
            api, primary_contact_name=name, address_line=address,
            member_count=2, prior_member=False,
        )
        membership = fx.setup_membership(
            api, household["id"], category["id"], season["id"],
            join_date="2027-07-01",
        )
        ctx[f"household_{key}"] = household
        ctx[f"membership_{key}"] = fx.invoice_membership(api, membership["id"])
    return ctx


def _book_the_four_hour_party(api, ctx):
    return fx.request_party(
        api, ctx["membership_a"]["id"], zone=Zone.PAVILION,
        start_iso="2027-07-15T14:00:00Z", end_iso="2027-07-15T18:00:00Z",
        **PARTY_LOAD
    )


def _book_the_three_hour_party(api, ctx):
    return fx.request_party(
        api, ctx["membership_b"]["id"], zone=Zone.PAVILION,
        start_iso="2027-07-16T14:00:00Z", end_iso="2027-07-16T17:00:00Z",
        **PARTY_LOAD
    )


class TestPartyDiscountTierLowerBoundIsInclusive:
    """A subtotal landing exactly on the tier earns the discount."""

    def test_a_subtotal_of_exactly_25000_earns_the_ten_per_cent_discount(
        self, api
    ):
        """Nine steps to 25000, then 2500 off; a strict boundary would give 0.

        PRD §3.7: "Eighth, the member discount rate is chosen from
        `subtotal_cents` against two inclusive lower bounds: a subtotal of at
        least forty-five thousand cents earns fifteen per cent, a subtotal of at
        least twenty-five thousand cents earns ten per cent, and anything below
        twenty-five thousand cents earns nothing."

        PRD §3.7: "Ninth, `member_discount_cents` is `subtotal_cents` multiplied
        by that rate and rounded half up to a whole cent, and
        `total_charge_cents` is `subtotal_cents` less `member_discount_cents`."

        Design: Corner/calculations/precision_party_discount_tier_lower_bound_is_inclusive
        """
        ctx = _two_party_ready_households(api)

        party = _book_the_four_hour_party(api, ctx)

        a.assert_party_pricing(
            party, projected_bather_load=26, required_guard_count=2,
            duration_hours_ceil=4, lifeguard_surcharge_cents=17600,
            base_facility_fee_cents=6000, guest_overage_fee_cents=1400,
            subtotal_cents=25000, member_discount_cents=2500,
            total_charge_cents=22500,
        )

    def test_one_hour_less_falls_below_the_tier_and_earns_nothing(self, api):
        """20600 is under the bound, so the discount is 0 and the total is the subtotal.

        PRD §3.7: "Third, `duration_hours_ceil` is the reservation's length in
        minutes divided by sixty and rounded up to the next whole hour, so a
        four-and-a-half-hour party is billed as five hours."

        PRD §3.7: "Fourth, `lifeguard_surcharge_cents` is `required_guard_count`
        multiplied by `duration_hours_ceil` multiplied by two thousand two hundred
        cents per guard-hour."

        Design: Corner/calculations/precision_party_discount_tier_lower_bound_is_inclusive
        """
        ctx = _two_party_ready_households(api)
        four_hours = _book_the_four_hour_party(api, ctx)

        three_hours = _book_the_three_hour_party(api, ctx)

        a.assert_party_pricing(
            three_hours, projected_bather_load=26, required_guard_count=2,
            duration_hours_ceil=3, lifeguard_surcharge_cents=13200,
            base_facility_fee_cents=6000, guest_overage_fee_cents=1400,
            subtotal_cents=20600, member_discount_cents=0,
            total_charge_cents=20600,
        )
        assert three_hours["guest_count"] == four_hours["guest_count"]
        assert three_hours["host_party_size"] == four_hours["host_party_size"]
        assert three_hours["zone"] == four_hours["zone"]

    def test_each_household_is_charged_its_own_post_discount_total(self, api):
        """22500 and 20600 are booked, not the two subtotals.

        PRD §3.7: "A new reservation is born `REQUESTED` with `refunded_cents` at
        0, and its `total_charge_cents` is booked onto the household immediately:
        `party_charges_owed_cents` rises by that amount and the household's
        `version` advances."

        Design: Corner/calculations/precision_party_discount_tier_lower_bound_is_inclusive
        """
        ctx = _two_party_ready_households(api)
        _book_the_four_hour_party(api, ctx)
        _book_the_three_hour_party(api, ctx)

        discounted = fx.read_household(api, ctx["household_a"]["id"])
        undiscounted = fx.read_household(api, ctx["household_b"]["id"])
        assert discounted["party_charges_owed_cents"] == 22500
        assert undiscounted["party_charges_owed_cents"] == 20600


def _two_households_with_cases_under_review(api):
    """Two membership-free households, each holding one case at UNDER_REVIEW.

    Neither household holds a membership, so no cascade runs and the standing
    each one lands on is read from the conduct rule alone.
    """
    fx.set_clock(api, "2027-06-20T09:00:00Z")
    ctx = {}
    for key, name, address, severity in (
        ("a", "Severe Warning Household", "161 Cedar Court",
         CaseSeverity.SEVERE),
        ("b", "Minor Probation Household", "162 Cedar Court",
         CaseSeverity.MINOR),
    ):
        household = fx.create_household(
            api, primary_contact_name=name, address_line=address,
            member_count=3, prior_member=False,
        )
        case = fx.report_case(
            api, household["id"], severity, headers=POOL_MANAGER,
            subject_name="Adult guest of the household",
        )
        ctx[f"household_{key}"] = household
        ctx[f"case_{key}"] = case
    for key in ("a", "b"):
        fx.transition_case(api, ctx[f"case_{key}"]["id"],
                           CaseStatus.UNDER_REVIEW, BOARD_PRESIDENT)
    return ctx


class TestStandingTakesTheMoreSevereOfSanctionAndPoints:
    """The two inputs disagree in both directions across the two households."""

    def test_both_households_and_both_cases_start_from_zero(self, api):
        """No points are assessed until the board decides.

        PRD §3.2: "A household is born in `GOOD_STANDING` with `conduct_points` at
        0, with `bond_status` `NONE` and `bond_paid_cents` at 0"

        PRD §3.9: "The case opens at `REPORTED` with the reporter's identity
        captured in `reported_by_user_id`, `points_assessed` at 0 and
        `appeal_count` at 0; `decided_by_user_id`, `sanction_type` and
        `sanctioned_at` are all null until the board decides."

        Design: Corner/calculations/constants_applied_standing_takes_the_more_severe_of_sanction_and_points
        """
        ctx = _two_households_with_cases_under_review(api)

        for key in ("a", "b"):
            household = fx.read_household(api, ctx[f"household_{key}"]["id"])
            a.assert_household(household, HouseholdStanding.GOOD_STANDING)
            assert household["conduct_points"] == 0
            assert ctx[f"case_{key}"]["points_assessed"] == 0
            assert ctx[f"case_{key}"]["status"] == CaseStatus.REPORTED
            assert ctx[f"case_{key}"]["sanctioned_at"] is None

    def test_a_severe_incident_suspends_despite_the_mildest_sanction(self, api):
        """A WARNING maps to GOOD_STANDING, but eight points outrank it.

        PRD §3.9: "The point values are two for a `MINOR` incident, four for a
        `MAJOR` one and eight for a `SEVERE` one, all integers, so a single severe
        incident sits one point below the expulsion line and two minor incidents
        sit two points below suspension."

        PRD §3.9: "Ranking the four values as `GOOD_STANDING` below `PROBATION`
        below `SUSPENDED` below `EXPELLED`, the new standing is whichever of the
        three candidates ranks most severe."

        Design: Corner/calculations/constants_applied_standing_takes_the_more_severe_of_sanction_and_points
        """
        ctx = _two_households_with_cases_under_review(api)

        sanctioned = fx.transition_case(
            api, ctx["case_a"]["id"], CaseStatus.SANCTIONED, BOARD_PRESIDENT,
            sanction_type=SanctionType.WARNING,
        )
        a.assert_conduct_case(sanctioned, CaseStatus.SANCTIONED)
        assert sanctioned["sanction_type"] == SanctionType.WARNING
        assert sanctioned["points_assessed"] == 8
        assert canonical_instant(
            sanctioned["sanctioned_at"]
        ) == "2027-06-20T09:00:00Z"

        household = fx.read_household(api, ctx["household_a"]["id"])
        assert household["conduct_points"] == 8
        a.assert_household(household, HouseholdStanding.SUSPENDED)

    def test_a_minor_incident_takes_its_standing_from_the_sanction_instead(
        self, api
    ):
        """Two points is below every threshold, so PROBATION comes from the decision.

        PRD §3.9: "The recomputed point total maps independently: ten points or
        more means `EXPELLED`, six or more but fewer than ten means `SUSPENDED`,
        and anything below six means `GOOD_STANDING`, both comparisons inclusive
        so exactly six suspends and exactly ten expels."

        PRD §3.9: "The sanction just handed down maps directly: `WARNING` to
        `GOOD_STANDING`, `PROBATION` to `PROBATION`, `SUSPENSION` to `SUSPENDED`
        and `EXPULSION` to `EXPELLED`."

        Design: Corner/calculations/constants_applied_standing_takes_the_more_severe_of_sanction_and_points
        """
        ctx = _two_households_with_cases_under_review(api)
        fx.transition_case(
            api, ctx["case_a"]["id"], CaseStatus.SANCTIONED, BOARD_PRESIDENT,
            sanction_type=SanctionType.WARNING,
        )

        sanctioned = fx.transition_case(
            api, ctx["case_b"]["id"], CaseStatus.SANCTIONED, BOARD_PRESIDENT,
            sanction_type=SanctionType.PROBATION,
        )
        assert sanctioned["status"] == CaseStatus.SANCTIONED
        assert sanctioned["points_assessed"] == 2

        household = fx.read_household(api, ctx["household_b"]["id"])
        assert household["conduct_points"] == 2
        a.assert_household(household, HouseholdStanding.PROBATION)
