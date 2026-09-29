"""Queue B - corner section ``calculations``.

Eight instances on the arithmetic itself: the two predicates that read a car's
ownership for different purposes, the constant that moves a deadline instead of
discounting money, the two clocks that decide when a notice becomes effective,
the input-set filters the invoice rollup applies before it sums anything, the
three-tier ladder, the backwards credit waterfall and the floored agreement cap.

Two rendering conventions apply to the PRD quotations in the docstrings below:
the PRD's em dashes are written as ASCII hyphens and its transition arrows as
``->``.  Nothing else is altered, so every quoted sentence is greppable in
``workspace/PRD.md`` once those two substitutions are made.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    add_calendar_days,
    assert_charge_money_invariant,
    assert_end_of_day,
    assert_instant_eq,
    assert_invoice_money_invariant,
    assert_pagination_meta,
    assert_subset_equal,
    end_of,
)
from test_helpers.constants import (
    AGREEMENT_MONTH,
    AGREEMENT_OPEN,
    AGREEMENT_RECONCILED,
    BASIS_ACTUAL,
    BILLING_INVOICED,
    BILLING_UNBILLED,
    CHANNEL_FAX,
    CHARGE_ADJUSTED,
    CHARGE_FINAL,
    CHARGE_KIND_DEMURRAGE,
    CHARGE_KIND_DETENTION,
    CHARGE_PROVISIONAL,
    CHARGE_VOIDED,
    CLOCK_AFTER_RELEASE,
    CLOCK_BASIS_ACTUAL,
    CLOCK_BASIS_CONSTRUCTIVE,
    CLOCK_BASIS_NONE,
    COLD_START_CLOCK,
    CYCLE_A_ACTUAL_AT,
    CYCLE_A_ACTUAL_EXPIRY,
    CYCLE_A_CHARGEABLE_DAYS,
    CYCLE_A_CONSTRUCTIVE_EXPIRY,
    CYCLE_A_CONSTRUCTIVE_START,
    CYCLE_A_GROSS_CENTS,
    CYCLE_A_NOTICE_SENT_AT,
    CYCLE_B_CHARGEABLE_DAYS,
    CYCLE_B_GROSS_CENTS,
    DECISION_PARTIALLY_ALLOWED,
    DEFAULT_CREDIT_CAP_RATIO,
    DEFAULT_FREE_TIME_HOURS_PRIVATE,
    DEFAULT_FREE_TIME_HOURS_RAILROAD,
    DEFAULT_GATE_CLOSE_HOUR,
    DEFAULT_NOTIFICATION_GRACE_HOURS,
    DEFAULT_TIER1_RATE_PRIVATE,
    DEFAULT_TIER1_RATE_RAILROAD,
    DEFAULT_TIER2_RATE_PRIVATE,
    DEFAULT_TIER2_RATE_RAILROAD,
    DEFAULT_TIER3_RATE_RAILROAD,
    DELIVERY_ACKNOWLEDGED,
    INVOICE_ADJUSTED,
    INVOICE_DRAFT,
    INVOICE_ISSUED,
    MOVEMENT_ACTUALLY_PLACED,
    MOVEMENT_RELEASED,
    MOVEMENT_VOIDED,
    NOTIFICATION_METHOD_FAX,
    OWNERSHIP_PRIVATE_ASSIGNED,
    SCOPE_WHOLE_INVOICE,
    TWO_LINE_ALLOWANCE_PCT,
    TWO_LINE_CREDIT_TOTAL,
    TWO_LINE_GROSS_TOTAL,
    TWO_LINE_PER_LINE_CREDIT,
)
from test_helpers.test_users import ADMIN, AGENT

# --- shared money-chain stations -------------------------------------------
ISSUE_CLOCK_MID_AUGUST = "2026-08-15T00:00:00.000Z"
SUBMIT_CLOCK_MID_AUGUST = "2026-08-15T10:00:00.000Z"
DISPUTE_DEADLINE_FROM_MID_AUGUST = "2026-09-14T23:59:59.999Z"

# --- instance 1 literals (the FAX consignee) -------------------------------
FAX_ACK_AT = "2026-08-03T20:00:00.000Z"
FAX_LOGICAL_CLOCK = "2026-08-08T12:00:00.000Z"
FAX_LATE_SPOT_AT = "2026-08-08T10:00:00.000Z"
FAX_PROVISIONAL_DAYS = 2  # 2026-08-06 and 2026-08-07; the clock date is not charged
FAX_PROVISIONAL_GROSS_CENTS = 25100  # 2 x 12550, entirely inside tier one
FREE_DAYS_RAILROAD = 2

# --- instance 2 literals (PRIVATE_ASSIGNED) --------------------------------
PRIVATE_ASSIGNED_RELEASE_AT = "2026-08-11T16:00:00.000Z"
PRIVATE_ASSIGNED_DAYS = 4  # 2026-08-08, 09, 10 and 11
PRIVATE_ASSIGNED_GROSS_CENTS = 46200  # 2 x 8150 + 2 x 14950 on the private ladder
RAILROAD_LADDER_WOULD_HAVE_BEEN = 70000  # 2 x 12550 + 2 x 22450

# --- instance 3 literals (72 free hours) -----------------------------------
FREE_TIME_HOURS_SEVENTY_TWO = 72
FREE_DAYS_THREE = 3
EXPIRY_UNDER_SEVENTY_TWO = "2026-08-08T23:59:59.999Z"
SEVENTY_TWO_HOUR_DAYS = 2  # 2026-08-09 and 2026-08-10 only
SEVENTY_TWO_HOUR_GROSS_CENTS = 25100

# --- instance 4 literals ---------------------------------------------------
WRONG_CONSIGNEE_REASON = "Car was billed to the wrong consignee."

# --- instance 5 literals (the July release outside the period) -------------
JULY_CLOCK = "2026-07-27T00:00:00.000Z"
JULY_CONSTRUCTIVE_AT = "2026-07-28T08:00:00.000Z"
JULY_NOTICE_AT = "2026-07-28T09:00:00.000Z"
JULY_ACTUAL_AT = "2026-07-29T10:00:00.000Z"
JULY_RELEASE_AT = "2026-07-31T09:00:00.000Z"

# --- instance 6 literals (six days across three tiers) ---------------------
SIX_DAY_RELEASE_AT = "2026-08-13T16:00:00.000Z"
SIX_DAY_COUNT = 6
SIX_DAY_GROSS_CENTS = 127500  # 2 x 12550 + 3 x 22450 + 1 x 35050
SIX_DAYS_AT_TIER_ONE = 75300  # the flat-rate answer, wrong by 52200 cents

# --- instance 7 literals (the backwards waterfall) -------------------------
ADJUDICATOR_WATERFALL = "adj-c9c7-a"
WATERFALL_CLAIM_CENTS = 35000
WATERFALL_CREDITS = (30908, 4092)  # line A untouched, line B trimmed
WATERFALL_NETS = (16642, 8458)
WATERFALL_INVOICE_NET_CENTS = 25100

# --- instance 8 literals (the floored agreement cap) -----------------------
EARLY_ACTUAL_AT = "2026-08-04T10:00:00.000Z"
EARLY_RELEASE_AT = "2026-08-04T15:00:00.000Z"
EARLY_RELEASE_DAYS = 2  # 2026-08-05 and 2026-08-06, handed back
CAPPED_CREDIT_CENTS = 3765  # FLOOR(12550 x 0.30)
AGREEMENT_INVOICE_NET_CENTS = 8785


# ===========================================================================
# instance: fax_clock_starts_at_the_acknowledgement_and_ignores_the_grace_window
# ===========================================================================
def test_a_fax_consignee_starts_the_clock_only_when_it_acknowledges(api):
    """No grace hours are added at all: 09:00 plus 4 is not the answer, 20:00 is.

    PRD 3.3: "For a consignee whose `notification_method` is `FAX`, the effective
    instant is the cycle's `notification_acknowledged_at`, full stop: a fax is
    effective only on positive acknowledgement, and until the consignee
    acknowledges, there is no effective notice however many faxes were sent."

    Design: Corner/calculations/fax_clock_starts_at_the_acknowledgement_and_ignores_the_grace_window
    """
    world = fx.reference_world(
        api, customer_overrides={"notification_method": NOTIFICATION_METHOD_FAX}
    )
    assert world["customer"]["notification_method"] == NOTIFICATION_METHOD_FAX
    assert world["facility"]["gate_close_hour"] == DEFAULT_GATE_CLOSE_HOUR
    assert world["tariff"]["notification_grace_hours"] == DEFAULT_NOTIFICATION_GRACE_HOURS
    assert world["tariff"]["free_time_hours_railroad"] == DEFAULT_FREE_TIME_HOURS_RAILROAD

    cycle = fx.constructively_placed_cycle(api, world)
    fx.send_notice(api, cycle["id"], CYCLE_A_NOTICE_SENT_AT, CHANNEL_FAX)

    # A matching FAX notice is merely SENT, so it does qualify as the cycle's
    # notification_sent_at - and still starts nothing.
    waiting = fx.get_cycle(api, cycle["id"])
    assert_instant_eq(
        waiting["notification_sent_at"], CYCLE_A_NOTICE_SENT_AT, "notification_sent_at"
    )
    assert_subset_equal(
        waiting,
        {
            "clock_basis": CLOCK_BASIS_NONE,
            "clock_start_at": None,
            "free_time_expires_at": None,
            "notification_acknowledged_at": None,
        },
    )

    fx.acknowledge(api, cycle["id"], FAX_ACK_AT, world["customer_id"])
    listed = api.list_notifications(cycle["id"], AGENT, {"limit": 10, "offset": 0})
    notices = get_success_data(listed)
    assert_pagination_meta(
        listed.json()["meta"], limit=10, offset=0, total_count=1, has_more=False
    )
    assert_subset_equal(
        notices[0],
        {
            "placement_cycle_id": cycle["id"],
            "channel": CHANNEL_FAX,
            "delivery_status": DELIVERY_ACKNOWLEDGED,
            "sequence_number": 1,
        },
    )
    assert_instant_eq(notices[0]["acknowledged_at"], FAX_ACK_AT, "acknowledged_at")

    started = fx.get_cycle(api, cycle["id"])
    assert_subset_equal(
        started,
        {"clock_basis": CLOCK_BASIS_CONSTRUCTIVE, "free_days": FREE_DAYS_RAILROAD},
    )
    assert_instant_eq(started["clock_start_at"], FAX_ACK_AT, "clock_start_at")
    assert_instant_eq(
        started["notification_acknowledged_at"],
        FAX_ACK_AT,
        "notification_acknowledged_at",
    )
    # 09:00 plus the four grace hours is 13:00, and it is not what the fax bought.
    assert started["clock_start_at"] != CYCLE_A_CONSTRUCTIVE_START
    assert_instant_eq(
        started["free_time_expires_at"],
        CYCLE_A_CONSTRUCTIVE_EXPIRY,
        "free_time_expires_at",
    )
    assert_end_of_day(started["free_time_expires_at"], "free_time_expires_at")

    # PRD 3.3: "when `actual_placement_at` is after the constructive expiry, the
    # railroad blew through the free time, the constructive clock stands, and the
    # late spot buys the consignee nothing".
    fx.set_clock(api, FAX_LOGICAL_CLOCK)
    fx.place_actually(api, cycle["id"], FAX_LATE_SPOT_AT)
    late = fx.get_cycle(api, cycle["id"])
    assert_subset_equal(
        late,
        {
            "movement_status": MOVEMENT_ACTUALLY_PLACED,
            "clock_basis": CLOCK_BASIS_CONSTRUCTIVE,
        },
    )
    assert_instant_eq(late["clock_start_at"], FAX_ACK_AT, "clock_start_at")
    assert_instant_eq(
        late["free_time_expires_at"], CYCLE_A_CONSTRUCTIVE_EXPIRY, "free_time_expires_at"
    )

    # PRD 3.5: "the reference instant is the current logical clock and the
    # reference date is *never* charged, because today is still running."
    charge = fx.charge_of_cycle(api, cycle["id"])
    assert_subset_equal(
        charge,
        {
            "status": CHARGE_PROVISIONAL,
            "charge_kind": CHARGE_KIND_DEMURRAGE,
            "chargeable_days": FAX_PROVISIONAL_DAYS,
            "billable_days": FAX_PROVISIONAL_DAYS,
            "bunching_exempt_days": 0,
            "gross_amount_cents": FAX_PROVISIONAL_GROSS_CENTS,
            "credit_applied_cents": 0,
            "net_amount_cents": FAX_PROVISIONAL_GROSS_CENTS,
        },
    )
    assert_charge_money_invariant(charge)
    assert charge["gross_amount_cents"] == FAX_PROVISIONAL_DAYS * DEFAULT_TIER1_RATE_RAILROAD


# ===========================================================================
# instance: private_assigned_car_takes_railroad_free_time_and_the_private_ladder
# ===========================================================================
def test_a_private_assigned_car_mixes_railroad_free_time_with_private_rates(api):
    """One ownership value, two different predicates, and a DETENTION line.

    PRD 3.6: "A `PRIVATE_ASSIGNED` car therefore receives the railroad free-time
    allowance while paying the private rates, and an implementation that decides
    both questions with one branch will misprice it."

    Design: Corner/calculations/private_assigned_car_takes_railroad_free_time_and_the_private_ladder
    """
    world = fx.reference_world(api)
    car = fx.make_rail_car(api, ownership=OWNERSHIP_PRIVATE_ASSIGNED)
    assert car["ownership"] == OWNERSHIP_PRIVATE_ASSIGNED

    cycle = fx.released_cycle(
        api, world, released_at=PRIVATE_ASSIGNED_RELEASE_AT, rail_car=car
    )

    # PRD 3.3: "for `RAILROAD_OWNED` and for `PRIVATE_ASSIGNED` alike, it is
    # `free_time_hours_railroad` divided by 24 the same way."
    assert_subset_equal(
        cycle,
        {
            "movement_status": MOVEMENT_RELEASED,
            "clock_basis": CLOCK_BASIS_ACTUAL,
            "free_days": DEFAULT_FREE_TIME_HOURS_RAILROAD // 24,
            "chargeable_days": PRIVATE_ASSIGNED_DAYS,
            "early_release_days": 0,
        },
    )
    assert cycle["free_days"] != DEFAULT_FREE_TIME_HOURS_PRIVATE // 24
    assert_instant_eq(cycle["clock_start_at"], CYCLE_A_ACTUAL_AT, "clock_start_at")
    assert_instant_eq(
        cycle["free_time_expires_at"], CYCLE_A_ACTUAL_EXPIRY, "free_time_expires_at"
    )
    assert_instant_eq(cycle["released_at"], PRIVATE_ASSIGNED_RELEASE_AT, "released_at")

    # PRD 3.2: "a `PRIVATE` or `PRIVATE_ASSIGNED` car on an `INDUSTRY_TRACK`
    # produces a `DETENTION` line".
    charge = fx.charge_of_cycle(api, cycle["id"])
    assert_subset_equal(
        charge,
        {
            "status": CHARGE_FINAL,
            "charge_kind": CHARGE_KIND_DETENTION,
            "computation_basis": BASIS_ACTUAL,
            "chargeable_days": PRIVATE_ASSIGNED_DAYS,
            "billable_days": PRIVATE_ASSIGNED_DAYS,
            "gross_amount_cents": PRIVATE_ASSIGNED_GROSS_CENTS,
            "credit_applied_cents": 0,
            "net_amount_cents": PRIVATE_ASSIGNED_GROSS_CENTS,
        },
    )
    assert charge["charge_kind"] != CHARGE_KIND_DEMURRAGE
    assert_charge_money_invariant(charge)
    assert PRIVATE_ASSIGNED_GROSS_CENTS == (
        2 * DEFAULT_TIER1_RATE_PRIVATE + 2 * DEFAULT_TIER2_RATE_PRIVATE
    )
    # Reading ownership once and using it for both decisions overbills by 23800.
    assert charge["gross_amount_cents"] != RAILROAD_LADDER_WOULD_HAVE_BEEN
    assert RAILROAD_LADDER_WOULD_HAVE_BEEN == (
        2 * DEFAULT_TIER1_RATE_RAILROAD + 2 * DEFAULT_TIER2_RATE_RAILROAD
    )


# ===========================================================================
# instance: seventy_two_free_hours_shrinks_the_same_timeline_to_two_days
# ===========================================================================
def test_seventy_two_free_hours_moves_the_expiry_rather_than_the_money(api):
    """The constant comes off the front of the timeline, not off the invoice.

    PRD 3.3: "When the car's `ownership` is `PRIVATE`, it is the tariff's
    `free_time_hours_private` divided by 24 with any remainder discarded; for
    `RAILROAD_OWNED` and for `PRIVATE_ASSIGNED` alike, it is
    `free_time_hours_railroad` divided by 24 the same way."

    Design: Corner/calculations/seventy_two_free_hours_shrinks_the_same_timeline_to_two_days
    """
    world = fx.reference_world(
        api,
        tariff_overrides={"free_time_hours_railroad": FREE_TIME_HOURS_SEVENTY_TWO},
    )
    assert world["tariff"]["free_time_hours_railroad"] == FREE_TIME_HOURS_SEVENTY_TWO

    cycle = fx.released_cycle_a(api, world)
    assert_subset_equal(
        cycle,
        {
            "clock_basis": CLOCK_BASIS_ACTUAL,
            "free_days": FREE_DAYS_THREE,
            "chargeable_days": SEVENTY_TWO_HOUR_DAYS,
        },
    )
    assert cycle["free_days"] == FREE_TIME_HOURS_SEVENTY_TWO // 24
    assert_instant_eq(cycle["clock_start_at"], CYCLE_A_ACTUAL_AT, "clock_start_at")
    assert_instant_eq(
        cycle["free_time_expires_at"], EXPIRY_UNDER_SEVENTY_TWO, "free_time_expires_at"
    )
    # The default-48 run of this identical timeline expires two dates earlier.
    assert cycle["free_time_expires_at"] != CYCLE_A_ACTUAL_EXPIRY
    assert cycle["chargeable_days"] != CYCLE_A_CHARGEABLE_DAYS

    charge = fx.charge_of_cycle(api, cycle["id"])
    assert_subset_equal(
        charge,
        {
            "status": CHARGE_FINAL,
            "computation_basis": BASIS_ACTUAL,
            "billable_days": SEVENTY_TWO_HOUR_DAYS,
            "gross_amount_cents": SEVENTY_TWO_HOUR_GROSS_CENTS,
            "net_amount_cents": SEVENTY_TWO_HOUR_GROSS_CENTS,
        },
    )
    assert_charge_money_invariant(charge)
    # Two days, both inside tier one - not three days discounted after the fact.
    assert SEVENTY_TWO_HOUR_GROSS_CENTS == (
        SEVENTY_TWO_HOUR_DAYS * DEFAULT_TIER1_RATE_RAILROAD
    )
    assert charge["gross_amount_cents"] != CYCLE_A_GROSS_CENTS


# ===========================================================================
# instance: voiding_a_charge_removes_it_from_the_invoice_rollup_inputs
# ===========================================================================
def test_a_voided_line_leaves_the_rollup_without_being_detached(api):
    """The count moves as well as the money, and the row keeps pointing at the invoice.

    PRD 3.7: "The rollup sets `attached_charge_count` to the number of live lines,
    `total_gross_cents` to the sum of their `gross_amount_cents`,
    `total_credit_cents` to the sum of their `credit_applied_cents`,
    `total_net_cents` to the gross less the credit, and `dispute_count` to the
    number of disputes filed against this invoice."

    Design: Corner/calculations/voiding_a_charge_removes_it_from_the_invoice_rollup_inputs
    """
    world = fx.reference_world(api)
    cycle_a, cycle_b, invoice = fx.two_line_invoice(
        api, world, issue_clock=ISSUE_CLOCK_MID_AUGUST
    )
    assert_subset_equal(
        invoice,
        {
            "status": INVOICE_ISSUED,
            "attached_charge_count": 2,
            "total_gross_cents": TWO_LINE_GROSS_TOTAL,
            "total_credit_cents": 0,
            "total_net_cents": TWO_LINE_GROSS_TOTAL,
        },
    )
    assert fx.charge_of_cycle(api, cycle_b["id"])["invoice_id"] == invoice["id"]

    voided = fx.void_cycle(api, cycle_b["id"], void_reason=WRONG_CONSIGNEE_REASON)
    assert voided["movement_status"] == MOVEMENT_VOIDED

    # PRD 3.7: "A line is live when its status is not `VOIDED`; voided lines are
    # invisible to every aggregate."
    dead_line = fx.charge_of_cycle(api, cycle_b["id"])
    assert_subset_equal(
        dead_line,
        {"status": CHARGE_VOIDED, "invoice_id": invoice["id"]},
    )
    assert dead_line["invoice_id"] is not None

    rerolled = fx.get_invoice(api, invoice["id"])
    assert_subset_equal(
        rerolled,
        {
            "attached_charge_count": 1,
            "total_gross_cents": CYCLE_A_GROSS_CENTS,
            "total_credit_cents": 0,
            "total_net_cents": CYCLE_A_GROSS_CENTS,
            "status": INVOICE_ISSUED,
            "version": invoice["version"] + 1,
        },
    )
    assert_invoice_money_invariant(rerolled)
    # A naive sum over invoice_id would still be charging for the voided car.
    assert rerolled["total_gross_cents"] != TWO_LINE_GROSS_TOTAL
    assert fx.charge_of_cycle(api, cycle_a["id"])["status"] == CHARGE_FINAL
    assert fx.get_car(api, cycle_b["rail_car_id"])["active_cycle_count"] == 0


# ===========================================================================
# instance: invoice_rollup_sums_only_the_charges_released_inside_the_billing_period
# ===========================================================================
def test_a_july_release_stays_off_an_august_invoice(api):
    """The July line is FINAL, uninvoiced and worth nothing - and the count proves it.

    PRD 3.7: "Every charge line whose status is `FINAL`, whose `invoice_id` is
    still null, whose cycle belongs to this consignee, and whose cycle's
    `released_at` falls inside the closed billing period is attached - its
    `invoice_id` is set to the new invoice - and each attached cycle's
    `billing_status` moves `UNBILLED -> INVOICED`."

    Design: Corner/calculations/invoice_rollup_sums_only_the_charges_released_inside_the_billing_period
    """
    world = fx.reference_world(api, clock=JULY_CLOCK)
    july_track = fx.make_industry_track(api)
    july = fx.released_cycle(
        api,
        world,
        constructive_at=JULY_CONSTRUCTIVE_AT,
        sent_at=JULY_NOTICE_AT,
        actual_at=JULY_ACTUAL_AT,
        released_at=JULY_RELEASE_AT,
        facility_id=july_track["id"],
    )
    # Released on the last date of its own free time: a real line worth 0 cents.
    assert_subset_equal(july, {"movement_status": MOVEMENT_RELEASED, "chargeable_days": 0})
    july_line = fx.charge_of_cycle(api, july["id"])
    assert_subset_equal(
        july_line,
        {"status": CHARGE_FINAL, "invoice_id": None, "gross_amount_cents": 0},
    )

    fx.set_clock(api, COLD_START_CLOCK)
    cycle_a, cycle_b = fx.released_pair(api, world)

    draft = fx.draft_invoice(api, world, clock=CLOCK_AFTER_RELEASE)
    assert_subset_equal(
        draft,
        {
            "status": INVOICE_DRAFT,
            "attached_charge_count": 2,
            "total_gross_cents": 0,
            "total_credit_cents": 0,
            "total_net_cents": 0,
            "agreement_credit_cents": 0,
            "dispute_count": 0,
            "dispute_deadline_at": None,
        },
    )
    # The zero-money July line is the trap: a sum-based check passes, a count fails.
    assert fx.charge_of_cycle(api, july["id"])["invoice_id"] is None
    assert fx.get_cycle(api, july["id"])["billing_status"] == BILLING_UNBILLED

    fx.set_clock(api, ISSUE_CLOCK_MID_AUGUST)
    issued = get_success_data(api.issue_invoice(draft["id"], ADMIN))
    assert_subset_equal(
        issued,
        {
            "status": INVOICE_ISSUED,
            "attached_charge_count": 2,
            "total_gross_cents": TWO_LINE_GROSS_TOTAL,
            "total_credit_cents": 0,
            "agreement_credit_cents": 0,
            "total_net_cents": TWO_LINE_GROSS_TOTAL,
            "version": draft["version"] + 1,
        },
    )
    assert_invoice_money_invariant(issued)

    # PRD 3.7: "sets `dispute_deadline_at` to the last millisecond -
    # `23:59:59.999Z` - of the date 30 **calendar** days after the logical-clock
    # date at the moment of issue."
    assert_end_of_day(issued["dispute_deadline_at"], "dispute_deadline_at")
    assert_instant_eq(
        issued["dispute_deadline_at"],
        end_of(add_calendar_days(ISSUE_CLOCK_MID_AUGUST, 30)),
        "dispute_deadline_at",
    )
    assert_instant_eq(
        issued["dispute_deadline_at"],
        DISPUTE_DEADLINE_FROM_MID_AUGUST,
        "dispute_deadline_at",
    )

    assert fx.get_cycle(api, cycle_a["id"])["billing_status"] == BILLING_INVOICED
    assert fx.get_cycle(api, cycle_b["id"])["billing_status"] == BILLING_INVOICED
    assert fx.get_cycle(api, july["id"])["billing_status"] == BILLING_UNBILLED
    assert fx.charge_of_cycle(api, july["id"])["invoice_id"] is None


# ===========================================================================
# instance: six_chargeable_days_walk_all_three_rate_tiers
# ===========================================================================
def test_six_chargeable_days_touch_every_tier_of_the_ladder(api):
    """Two at tier one, three at tier two and one at tier three, from one release.

    PRD 3.6: "At the tariff defaults of 2 tier-one days and 3 tier-two days:
    exactly 2 billable days bills entirely at the tier-one rate; 3 billable days
    straddle into tier two for exactly one day; exactly 5 billable days bill
    nothing at the tier-three rate; and a sixth day adds exactly one tier-three
    day."

    Design: Corner/calculations/six_chargeable_days_walk_all_three_rate_tiers
    """
    world = fx.reference_world(api)
    cycle = fx.released_cycle_a(api, world, released_at=SIX_DAY_RELEASE_AT)
    assert_subset_equal(
        cycle,
        {
            "clock_basis": CLOCK_BASIS_ACTUAL,
            "chargeable_days": SIX_DAY_COUNT,
            "early_release_days": 0,
        },
    )
    assert_instant_eq(
        cycle["free_time_expires_at"], CYCLE_A_ACTUAL_EXPIRY, "free_time_expires_at"
    )

    # PRD 3.6: "`gross_amount_cents` is the tier-one day count multiplied by the
    # tier-one rate, plus the tier-two day count multiplied by the tier-two rate,
    # plus the tier-three day count multiplied by the tier-three rate."
    charge = fx.charge_of_cycle(api, cycle["id"])
    assert_subset_equal(
        charge,
        {
            "status": CHARGE_FINAL,
            "computation_basis": BASIS_ACTUAL,
            "charge_kind": CHARGE_KIND_DEMURRAGE,
            "chargeable_days": SIX_DAY_COUNT,
            "billable_days": SIX_DAY_COUNT,
            "bunching_exempt_days": 0,
            "gross_amount_cents": SIX_DAY_GROSS_CENTS,
            "credit_applied_cents": 0,
            "net_amount_cents": SIX_DAY_GROSS_CENTS,
        },
    )
    assert_charge_money_invariant(charge)
    assert SIX_DAY_GROSS_CENTS == (
        2 * DEFAULT_TIER1_RATE_RAILROAD
        + 3 * DEFAULT_TIER2_RATE_RAILROAD
        + 1 * DEFAULT_TIER3_RATE_RAILROAD
    )
    # The steep ladder is why no average rate per day is ever a usable shortcut.
    assert SIX_DAYS_AT_TIER_ONE == SIX_DAY_COUNT * DEFAULT_TIER1_RATE_RAILROAD
    assert charge["gross_amount_cents"] != SIX_DAYS_AT_TIER_ONE


# ===========================================================================
# instance: dispute_credit_waterfall_trims_the_last_line_to_the_claim_cap
# ===========================================================================
def test_the_claim_ceiling_comes_off_the_last_line_only(api):
    """39066 overshoots a 35000 claim, and the 4066 excess is charged to line B alone.

    PRD 3.8: "Third, enforce the consignee's own `claimed_credit_cents` ceiling
    with a **backwards** waterfall: if the total exceeds the claim, take the excess
    off the last line in the resolved order first, then the second-to-last, and so
    on until the excess is exhausted, so the earliest-released line keeps its
    credit intact and the total lands exactly on the claim."

    Design: Corner/calculations/dispute_credit_waterfall_trims_the_last_line_to_the_claim_cap
    """
    world = fx.reference_world(api)
    cycle_a, cycle_b, invoice = fx.two_line_invoice(
        api, world, issue_clock=ISSUE_CLOCK_MID_AUGUST
    )
    dispute = fx.under_review_dispute(
        api,
        invoice,
        world["customer_id"],
        WATERFALL_CLAIM_CENTS,
        ADJUDICATOR_WATERFALL,
        submit_clock=SUBMIT_CLOCK_MID_AUGUST,
        scope=SCOPE_WHOLE_INVOICE,
    )
    assert dispute["claimed_credit_cents"] == WATERFALL_CLAIM_CENTS
    assert dispute["target_charge_count"] == 2

    decided = fx.decide(
        api,
        dispute["id"],
        ADJUDICATOR_WATERFALL,
        DECISION_PARTIALLY_ALLOWED,
        TWO_LINE_ALLOWANCE_PCT,
    )
    assert_subset_equal(
        decided,
        {
            "decision": DECISION_PARTIALLY_ALLOWED,
            "allowance_pct": TWO_LINE_ALLOWANCE_PCT,
            "allowed_credit_cents": WATERFALL_CLAIM_CENTS,
        },
    )
    # The total lands exactly on the claim, not on the uncapped 39066.
    assert decided["allowed_credit_cents"] == dispute["claimed_credit_cents"]
    assert decided["allowed_credit_cents"] != TWO_LINE_CREDIT_TOTAL

    line_a = fx.charge_of_cycle(api, cycle_a["id"])
    line_b = fx.charge_of_cycle(api, cycle_b["id"])
    assert_subset_equal(
        line_a,
        {
            "status": CHARGE_ADJUSTED,
            "credit_applied_cents": WATERFALL_CREDITS[0],
            "net_amount_cents": WATERFALL_NETS[0],
        },
    )
    assert_subset_equal(
        line_b,
        {
            "status": CHARGE_ADJUSTED,
            "credit_applied_cents": WATERFALL_CREDITS[1],
            "net_amount_cents": WATERFALL_NETS[1],
        },
    )
    assert_charge_money_invariant(line_a)
    assert_charge_money_invariant(line_b)
    # The earliest-released line kept its full half-up credit; the last one paid.
    assert line_a["credit_applied_cents"] == TWO_LINE_PER_LINE_CREDIT[0]
    assert line_b["credit_applied_cents"] != TWO_LINE_PER_LINE_CREDIT[1]
    assert (
        TWO_LINE_PER_LINE_CREDIT[1] - line_b["credit_applied_cents"]
        == TWO_LINE_CREDIT_TOTAL - WATERFALL_CLAIM_CENTS
    )
    assert (
        line_a["credit_applied_cents"] + line_b["credit_applied_cents"]
        == WATERFALL_CLAIM_CENTS
    )

    rolled = fx.get_invoice(api, invoice["id"])
    assert_subset_equal(
        rolled,
        {
            "status": INVOICE_ADJUSTED,
            "total_gross_cents": TWO_LINE_GROSS_TOTAL,
            "total_credit_cents": WATERFALL_CLAIM_CENTS,
            "total_net_cents": WATERFALL_INVOICE_NET_CENTS,
        },
    )
    assert_invoice_money_invariant(rolled)
    assert (
        fx.get_customer(api, world["customer_id"])["credit_balance_cents"]
        == WATERFALL_CLAIM_CENTS
    )


# ===========================================================================
# instance: average_agreement_reconcile_freezes_the_capped_credit
# ===========================================================================
def test_reconcile_freezes_the_capped_credit_rather_than_recomputing_it(api):
    """One spendable credit day worth 12550 is capped to 3765, and stays there.

    PRD 3.7: "Sixth, apply the contractual ceiling, which uses **floor** and not
    rounding: the cap is the month's gross multiplied by `credit_cap_ratio`,
    truncated to a whole cent."

    Design: Corner/calculations/average_agreement_reconcile_freezes_the_capped_credit
    """
    world = fx.reference_world(api)
    agreement = fx.open_agreement(api, world["customer_id"])
    assert_subset_equal(
        agreement,
        {
            "status": AGREEMENT_OPEN,
            "agreement_month": AGREEMENT_MONTH,
            "credit_cap_ratio": DEFAULT_CREDIT_CAP_RATIO,
            "credit_days_earned": 0,
            "debit_days_incurred": 0,
            "net_days": 0,
            "agreement_credit_cents": 0,
        },
    )

    track_b = fx.make_industry_track(api)
    early = fx.released_cycle(
        api, world, actual_at=EARLY_ACTUAL_AT, released_at=EARLY_RELEASE_AT
    )
    assert_subset_equal(
        early,
        {"chargeable_days": 0, "early_release_days": EARLY_RELEASE_DAYS},
    )
    assert fx.charge_of_cycle(api, early["id"])["gross_amount_cents"] == 0

    cycle_b = fx.released_cycle_b(api, world, facility_id=track_b["id"])
    assert cycle_b["chargeable_days"] == CYCLE_B_CHARGEABLE_DAYS

    # PRD 3.7: "Fourth, the spendable credit days are the lesser of
    # `credit_days_earned` and `debit_days_incurred` - a consignee can only spend
    # credit days against days it actually owes".
    ledger = fx.get_agreement(api, world["customer_id"], agreement["id"])
    assert_subset_equal(
        ledger,
        {
            "status": AGREEMENT_OPEN,
            "credit_days_earned": EARLY_RELEASE_DAYS,
            "debit_days_incurred": CYCLE_B_CHARGEABLE_DAYS,
            "net_days": EARLY_RELEASE_DAYS - CYCLE_B_CHARGEABLE_DAYS,
            "agreement_credit_cents": 0,
        },
    )

    invoice = fx.issued_invoice(api, world, issue_clock=ISSUE_CLOCK_MID_AUGUST)
    assert_subset_equal(
        invoice,
        {
            "status": INVOICE_ADJUSTED,
            "attached_charge_count": 2,
            "total_gross_cents": CYCLE_B_GROSS_CENTS,
            "agreement_credit_cents": CAPPED_CREDIT_CENTS,
            "total_credit_cents": CAPPED_CREDIT_CENTS,
            "total_net_cents": AGREEMENT_INVOICE_NET_CENTS,
        },
    )
    assert_invoice_money_invariant(invoice)
    # The single spendable day was worth 12550; the contractual ceiling is 3765.
    assert invoice["agreement_credit_cents"] != CYCLE_B_GROSS_CENTS
    assert CAPPED_CREDIT_CENTS == int(CYCLE_B_GROSS_CENTS * 30 // 100)
    credited_line = fx.charge_of_cycle(api, cycle_b["id"])
    assert credited_line["credit_applied_cents"] == CAPPED_CREDIT_CENTS
    assert_charge_money_invariant(credited_line)

    # PRD 3.7: "`agreement_credit_cents` on the agreement is the lesser of the
    # uncapped credit and the cap, and the same figure is written to the invoice's
    # own `agreement_credit_cents`."
    landed = fx.get_agreement(api, world["customer_id"], agreement["id"])
    assert_subset_equal(
        landed,
        {"status": AGREEMENT_OPEN, "agreement_credit_cents": CAPPED_CREDIT_CENTS},
    )

    # PRD 3.7: "When `net_days` is zero or positive the agreement moves
    # `OPEN -> RECONCILED` and its `agreement_credit_cents` is frozen at the value
    # landed at issue time - the credit is honoured."
    reconciled = fx.reconcile(api, agreement["id"])
    assert_subset_equal(
        reconciled,
        {
            "status": AGREEMENT_RECONCILED,
            "agreement_credit_cents": CAPPED_CREDIT_CENTS,
            "credit_days_earned": EARLY_RELEASE_DAYS,
            "debit_days_incurred": CYCLE_B_CHARGEABLE_DAYS,
            "net_days": EARLY_RELEASE_DAYS - CYCLE_B_CHARGEABLE_DAYS,
            "version": landed["version"] + 1,
        },
    )

    # Reconciliation settles the month without touching the invoice it credited.
    assert fx.get_invoice(api, invoice["id"]) == invoice
    assert fx.charge_of_cycle(api, cycle_b["id"]) == credited_line
