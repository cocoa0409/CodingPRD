"""Queue A - rule ``boundary_precision_check``.

Three instances, each pinning a closed bound to the millisecond and naming the
figure an off-by-one implementation would produce instead.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_charge_money_invariant,
    assert_end_of_day,
    assert_instant_eq,
    assert_subset_equal,
)
from test_helpers.constants import (
    BASIS_ACTUAL,
    BASIS_STORAGE_HOURLY,
    CHARGE_FINAL,
    CHARGE_KIND_DEMURRAGE,
    CHARGE_KIND_STORAGE,
    CYCLE_A_ACTUAL_EXPIRY,
    CYCLE_A_CHARGEABLE_DAYS,
    CYCLE_A_GROSS_CENTS,
    DEFAULT_GATE_CLOSE_HOUR,
    DEFAULT_STORAGE_DAILY_RATE_CENTS,
    DEFAULT_STORAGE_FREE_HOURS,
    DEFAULT_TIER1_RATE_RAILROAD,
    DEFAULT_TIER2_RATE_RAILROAD,
    EVIDENCE_GATE_LOG,
    EVIDENCE_SWITCH_LIST,
    EVIDENCE_TRACK_EMBARGO_NOTICE,
    EVIDENCE_WEIGHT_CERTIFICATE,
    EVIDENCE_WEIGHT_POINTS,
    DISPUTE_SUBMITTED,
    DUE_AT_BASE_20_MULT_1_50_WEIGHT_CAPPED,
    FACILITY_KIND_INTERMODAL_TERMINAL,
    GROUNDS_RATE_UNREASONABLE,
    MOVEMENT_CONSTRUCTIVELY_PLACED,
    MOVEMENT_RELEASED,
    SCOPE_SINGLE_CHARGE,
    STORAGE_CLOCK_HOURLY,
)
from test_helpers.test_users import OFFICER

# --- instance 15 literals --------------------------------------------------
CLOCK_AT_GATE_CLOSE = "2026-08-11T16:00:00.000Z"
RELEASE_ONE_MS_BEFORE_CLOSE = "2026-08-11T15:59:59.999Z"
RELEASE_AT_GATE_CLOSE = "2026-08-11T16:00:00.000Z"
DAYS_WITHOUT_THE_RELEASE_DATE = CYCLE_A_CHARGEABLE_DAYS  # 3
DAYS_WITH_THE_RELEASE_DATE = 4
GROSS_WITHOUT_THE_RELEASE_DATE = CYCLE_A_GROSS_CENTS  # 12550 + 12550 + 22450
GROSS_WITH_THE_RELEASE_DATE = 70000  # + a second tier-2 day
ONE_MILLISECOND_IS_WORTH = DEFAULT_TIER2_RATE_RAILROAD  # 22450, not 12550

# --- instance 16 literals --------------------------------------------------
STORAGE_ARRIVAL_AT = "2026-08-03T08:00:00.000Z"
RELEASE_AT_EXACTLY_48_HOURS = "2026-08-05T08:00:00.000Z"
RELEASE_AT_48_HOURS_PLUS_1_MS = "2026-08-05T08:00:00.001Z"
STORAGE_CLOCK = "2026-08-05T09:00:00.000Z"
STORAGE_OVERRIDES = {
    "kind": FACILITY_KIND_INTERMODAL_TERMINAL,
    "storage_clock_mode": STORAGE_CLOCK_HOURLY,
    "storage_free_hours": DEFAULT_STORAGE_FREE_HOURS,
    "storage_daily_rate_cents": DEFAULT_STORAGE_DAILY_RATE_CENTS,
    "operates_weekends": True,
    "car_spot_capacity": 4,
    "switch_buffer_minutes": 0,
}

# --- instance 17 literals --------------------------------------------------
CLOCK_AT_ISSUE_R6I3 = "2026-08-15T00:00:00.000Z"
CLOCK_AT_SUBMIT_R6I3 = "2026-08-15T10:00:00.000Z"
WEIGHT_TEN_TYPES = (
    EVIDENCE_TRACK_EMBARGO_NOTICE,
    EVIDENCE_GATE_LOG,
    EVIDENCE_SWITCH_LIST,
)  # 4 + 3 + 3
WEIGHT_TWELVE_TYPES = WEIGHT_TEN_TYPES + (EVIDENCE_WEIGHT_CERTIFICATE,)  # + 2
EVIDENCE_WEIGHT_TEN = 10
EVIDENCE_WEIGHT_TWELVE = 12
SATURATED_DISCOUNT_DAYS = 5
WRONG_DUE_AT_UNSATURATED_DISCOUNT = "2026-09-17T23:59:59.999Z"


def _two_identical_spotted_cycles(api):
    """Two cars on byte-identical timelines at one gate-close-16 industry track.

    Both are spotted at 2026-08-05T10:00:00Z, so both carry the same
    ``free_time_expires_at`` and the only thing that will ever differ between
    them is the millisecond on their release.
    """
    world = fx.reference_world(
        api, facility_overrides={"gate_close_hour": DEFAULT_GATE_CLOSE_HOUR}
    )
    early = fx.actually_placed_cycle(api, world)
    late = fx.actually_placed_cycle(api, world)
    for cycle in (early, late):
        assert_instant_eq(
            cycle["free_time_expires_at"],
            CYCLE_A_ACTUAL_EXPIRY,
            "free_time_expires_at",
        )
    fx.set_clock(api, CLOCK_AT_GATE_CLOSE)
    return world, early, late


# ===========================================================================
# instance: release_at_gate_close_hour_to_the_millisecond_adds_a_tier_two_day
# ===========================================================================
def test_release_one_millisecond_before_the_gate_closes_omits_the_release_date(api):
    """15:59:59.999Z bills 3 days; 16:00:00.000Z bills 4 from the same history.

    PRD 3.5: "the release date itself counts as a chargeable day exactly when the
    time-of-day component of `released_at` is at or after the facility's
    `gate_close_hour` on the hour - that is, at or after `gate_close_hour` hours,
    0 minutes, 0 seconds and 0 milliseconds."

    Design: Difficulty/boundary_precision_check/release_at_gate_close_hour_to_the_millisecond_adds_a_tier_two_day
    """
    world, early, late = _two_identical_spotted_cycles(api)

    fx.release_cycle(api, early["id"], RELEASE_ONE_MS_BEFORE_CLOSE, world["customer_id"])
    fx.release_cycle(api, late["id"], RELEASE_AT_GATE_CLOSE, world["customer_id"])

    early_cycle = fx.get_cycle(api, early["id"])
    late_cycle = fx.get_cycle(api, late["id"])
    assert_subset_equal(
        early_cycle,
        {
            "movement_status": MOVEMENT_RELEASED,
            "chargeable_days": DAYS_WITHOUT_THE_RELEASE_DATE,
            "early_release_days": 0,
        },
    )
    assert_subset_equal(
        late_cycle,
        {
            "movement_status": MOVEMENT_RELEASED,
            "chargeable_days": DAYS_WITH_THE_RELEASE_DATE,
            "early_release_days": 0,
        },
    )
    # The bound is closed from above and open from below, to the millisecond.
    assert early_cycle["chargeable_days"] + 1 == late_cycle["chargeable_days"]

    early_charge = fx.charge_of_cycle(api, early["id"])
    assert_subset_equal(
        early_charge,
        {
            "status": CHARGE_FINAL,
            "charge_kind": CHARGE_KIND_DEMURRAGE,
            "computation_basis": BASIS_ACTUAL,
            "chargeable_days": DAYS_WITHOUT_THE_RELEASE_DATE,
            "gross_amount_cents": GROSS_WITHOUT_THE_RELEASE_DATE,
        },
    )
    # A truncate-to-second reader would have billed the early car 70000 too.
    assert early_charge["gross_amount_cents"] != GROSS_WITH_THE_RELEASE_DATE
    assert_charge_money_invariant(early_charge)


def test_the_extra_release_day_is_priced_at_the_tier_two_rate(api):
    """One millisecond is worth 22450 cents, because day four is a tier-2 day.

    PRD 3.1: "The rate ladder is expressed as three tiers: `tier1_day_count` days
    at the tier-one rate, defaulting to 2 days; `tier2_day_count` days at the
    tier-two rate immediately after, defaulting to 3 days; and every further day
    at the tier-three rate."

    Design: Difficulty/boundary_precision_check/release_at_gate_close_hour_to_the_millisecond_adds_a_tier_two_day
    """
    world, early, late = _two_identical_spotted_cycles(api)

    fx.release_cycle(api, early["id"], RELEASE_ONE_MS_BEFORE_CLOSE, world["customer_id"])
    fx.release_cycle(api, late["id"], RELEASE_AT_GATE_CLOSE, world["customer_id"])

    early_charge = fx.charge_of_cycle(api, early["id"])
    late_charge = fx.charge_of_cycle(api, late["id"])
    assert late_charge["gross_amount_cents"] == GROSS_WITH_THE_RELEASE_DATE
    assert late_charge["billable_days"] == DAYS_WITH_THE_RELEASE_DATE
    assert_charge_money_invariant(late_charge)

    delta = late_charge["gross_amount_cents"] - early_charge["gross_amount_cents"]
    assert delta == ONE_MILLISECOND_IS_WORTH
    assert delta != DEFAULT_TIER1_RATE_RAILROAD
    # 12550 + 12550 + 22450 + 22450 is the whole of the late figure.
    assert (
        late_charge["gross_amount_cents"]
        == 2 * DEFAULT_TIER1_RATE_RAILROAD + 2 * DEFAULT_TIER2_RATE_RAILROAD
    )


def _two_stored_cars_at_an_intermodal_terminal(api):
    """Two CONSTRUCTIVELY_PLACED cycles at an hourly-clock intermodal terminal.

    Neither cycle is notified, and neither is ever actually placed: PRD 3.5
    permits ``CONSTRUCTIVELY_PLACED -> RELEASED`` precisely because the facility's
    ``kind`` is ``INTERMODAL_TERMINAL``, and PRD 3.5 works the storage clock from
    ``constructive_placement_at`` rather than from ``clock_start_at``.
    """
    world = fx.reference_world(api, facility_overrides=dict(STORAGE_OVERRIDES))
    assert world["facility"]["kind"] == FACILITY_KIND_INTERMODAL_TERMINAL
    assert world["facility"]["storage_clock_mode"] == STORAGE_CLOCK_HOURLY
    assert world["facility"]["storage_free_hours"] == DEFAULT_STORAGE_FREE_HOURS

    exact = fx.constructively_placed_cycle(api, world, at=STORAGE_ARRIVAL_AT)
    plus_one = fx.constructively_placed_cycle(api, world, at=STORAGE_ARRIVAL_AT)
    for cycle in (exact, plus_one):
        assert cycle["movement_status"] == MOVEMENT_CONSTRUCTIVELY_PLACED
        assert cycle["notification_sent_at"] is None
        assert_instant_eq(
            cycle["constructive_placement_at"], STORAGE_ARRIVAL_AT,
            "constructive_placement_at",
        )
    fx.set_clock(api, STORAGE_CLOCK)
    return world, exact, plus_one


# ===========================================================================
# instance: hourly_storage_free_time_expires_on_a_closed_48_hour_bound
# ===========================================================================
def test_a_dwell_of_exactly_the_free_hours_ceils_to_zero_storage_days(api):
    """CEIL of exactly 0.0 must stay 0: a 48-hour dwell is free, 48h+1ms is not.

    PRD 3.5: "Under `HOURLY_FROM_ARRIVAL`, take the whole-millisecond dwell from
    `constructive_placement_at` to `released_at`, subtract `storage_free_hours`
    converted to milliseconds by multiplying by 3,600,000, floor the result at
    zero, then divide by 86,400,000 - the milliseconds in a day - and round **up**
    to the next whole number."

    Design: Difficulty/boundary_precision_check/hourly_storage_free_time_expires_on_a_closed_48_hour_bound
    """
    world, exact, plus_one = _two_stored_cars_at_an_intermodal_terminal(api)

    fx.release_cycle(
        api, exact["id"], RELEASE_AT_EXACTLY_48_HOURS, world["customer_id"]
    )
    fx.release_cycle(
        api, plus_one["id"], RELEASE_AT_48_HOURS_PLUS_1_MS, world["customer_id"]
    )

    exact_charge = fx.charge_of_cycle(api, exact["id"])
    plus_one_charge = fx.charge_of_cycle(api, plus_one["id"])
    assert_subset_equal(
        exact_charge,
        {
            "status": CHARGE_FINAL,
            "charge_kind": CHARGE_KIND_STORAGE,
            "computation_basis": BASIS_STORAGE_HOURLY,
            "chargeable_days": 0,
            "billable_days": 0,
            "gross_amount_cents": 0,
            "credit_applied_cents": 0,
            "net_amount_cents": 0,
        },
    )
    assert_subset_equal(
        plus_one_charge,
        {
            "status": CHARGE_FINAL,
            "charge_kind": CHARGE_KIND_STORAGE,
            "computation_basis": BASIS_STORAGE_HOURLY,
            "chargeable_days": 1,
            "billable_days": 1,
            "gross_amount_cents": DEFAULT_STORAGE_DAILY_RATE_CENTS,
        },
    )
    assert_charge_money_invariant(exact_charge)
    assert_charge_money_invariant(plus_one_charge)

    # A bare CEIL over the total dwell would have billed both cars one day.
    assert exact_charge["chargeable_days"] != plus_one_charge["chargeable_days"]
    # Storage is flat-rate, so the per-diem ladder never appears.
    for charge in (exact_charge, plus_one_charge):
        assert charge["gross_amount_cents"] != DEFAULT_TIER1_RATE_RAILROAD

    assert fx.get_cycle(api, exact["id"])["movement_status"] == MOVEMENT_RELEASED
    assert fx.get_cycle(api, plus_one["id"])["movement_status"] == MOVEMENT_RELEASED


def test_the_zero_cent_storage_charge_is_still_an_attachable_final_line(api):
    """A zero charge is not a missing charge: both lines attach to the invoice.

    PRD 3.7: "Every charge line whose status is `FINAL`, whose `invoice_id` is
    still null, whose cycle belongs to this consignee, and whose cycle's
    `released_at` falls inside the closed billing period is attached - its
    `invoice_id` is set to the new invoice - and each attached cycle's
    `billing_status` moves `UNBILLED -> INVOICED`."

    Design: Difficulty/boundary_precision_check/hourly_storage_free_time_expires_on_a_closed_48_hour_bound
    """
    world, exact, plus_one = _two_stored_cars_at_an_intermodal_terminal(api)
    fx.release_cycle(
        api, exact["id"], RELEASE_AT_EXACTLY_48_HOURS, world["customer_id"]
    )
    fx.release_cycle(
        api, plus_one["id"], RELEASE_AT_48_HOURS_PLUS_1_MS, world["customer_id"]
    )

    zero_line = fx.charge_of_cycle(api, exact["id"])
    assert zero_line["gross_amount_cents"] == 0
    assert zero_line["status"] == CHARGE_FINAL
    assert zero_line["invoice_id"] is None

    invoice = fx.draft_invoice(api, world)
    assert invoice["attached_charge_count"] == 2

    attached = fx.charges_of_invoice(api, invoice["id"])
    assert len(attached) == 2
    grosses = sorted(row["gross_amount_cents"] for row in attached)
    assert grosses == [0, DEFAULT_STORAGE_DAILY_RATE_CENTS]
    assert fx.charge_of_cycle(api, exact["id"])["invoice_id"] == invoice["id"]
    assert fx.charge_of_cycle(api, plus_one["id"])["invoice_id"] == invoice["id"]


def _two_disputes_at_weight_ten_and_twelve(api):
    """Two SINGLE_CHARGE disputes on one invoice, differing only by one exhibit.

    Both plead ``RATE_UNREASONABLE`` against a tariff whose
    ``adjudication_days_base`` is the default 20, and both are submitted at
    2026-08-15T10:00:00Z, so the only input that differs between them is the
    evidence weight.
    """
    world = fx.reference_world(api)
    cycle_a, cycle_b, invoice = fx.two_line_invoice(
        api, world, issue_clock=CLOCK_AT_ISSUE_R6I3
    )
    charge_a = fx.charge_of_cycle(api, cycle_a["id"])
    charge_b = fx.charge_of_cycle(api, cycle_b["id"])

    weight_ten = fx.submitted_dispute(
        api,
        invoice,
        world["customer_id"],
        charge_a["gross_amount_cents"],
        CLOCK_AT_SUBMIT_R6I3,
        list(WEIGHT_TEN_TYPES),
        scope=SCOPE_SINGLE_CHARGE,
        grounds=GROUNDS_RATE_UNREASONABLE,
        demurrage_charge_id=charge_a["id"],
    )
    weight_twelve = fx.submitted_dispute(
        api,
        invoice,
        world["customer_id"],
        charge_b["gross_amount_cents"],
        CLOCK_AT_SUBMIT_R6I3,
        list(WEIGHT_TWELVE_TYPES),
        scope=SCOPE_SINGLE_CHARGE,
        grounds=GROUNDS_RATE_UNREASONABLE,
        demurrage_charge_id=charge_b["id"],
    )
    return world, invoice, weight_ten, weight_twelve


# ===========================================================================
# instance: evidence_weight_discount_saturates_at_five_business_days
# ===========================================================================
def test_the_evidence_discount_saturates_so_weight_ten_and_twelve_agree(api):
    """MIN(5, FLOOR(w/2)) is flat above 10, so both deadlines are 2026-09-18.

    PRD 3.8: "On the first round, take the base times the multiplier and round it
    **up** to a whole day, then subtract the evidence credit, which is the
    evidence weight halved and rounded **down** and then capped at 5 days; the
    allowance is the larger of that result and a floor of 5 days."

    Design: Difficulty/boundary_precision_check/evidence_weight_discount_saturates_at_five_business_days
    """
    _world, _invoice, weight_ten, weight_twelve = _two_disputes_at_weight_ten_and_twelve(
        api
    )

    assert weight_ten["status"] == DISPUTE_SUBMITTED
    assert weight_twelve["status"] == DISPUTE_SUBMITTED
    assert weight_ten["evidence_weight"] == EVIDENCE_WEIGHT_TEN
    assert weight_twelve["evidence_weight"] == EVIDENCE_WEIGHT_TWELVE
    assert weight_twelve["evidence_weight"] > weight_ten["evidence_weight"]

    for dispute in (weight_ten, weight_twelve):
        assert_instant_eq(dispute["submitted_at"], CLOCK_AT_SUBMIT_R6I3, "submitted_at")
        assert_end_of_day(dispute["adjudication_due_at"], "adjudication_due_at")
        assert_instant_eq(
            dispute["adjudication_due_at"],
            DUE_AT_BASE_20_MULT_1_50_WEIGHT_CAPPED,
            "adjudication_due_at",
        )

    # Byte-identical deadlines from unequal evidence: that is the saturation.
    assert weight_twelve["adjudication_due_at"] == weight_ten["adjudication_due_at"]
    # An unsaturated FLOOR(12 / 2) == 6 discount would have moved it a day earlier.
    assert weight_twelve["adjudication_due_at"] != WRONG_DUE_AT_UNSATURATED_DISCOUNT
    assert (
        EVIDENCE_WEIGHT_TWELVE // 2 > SATURATED_DISCOUNT_DAYS
        and EVIDENCE_WEIGHT_TEN // 2 == SATURATED_DISCOUNT_DAYS
    )


def test_the_exhibit_that_buys_nothing_still_carries_its_own_weight_points(api):
    """The saturation lives in the deadline formula, not in the exhibit rows.

    PRD 3.8: "Each exhibit's `weight_points` is fixed by its class and derived
    server-side, with any caller-supplied value ignored: a `SWITCH_LIST` is worth
    3, a `GATE_LOG` 3, an `EMAIL_NOTICE` 1, a `TRACK_EMBARGO_NOTICE` 4, and a
    `WEIGHT_CERTIFICATE` 2."

    Design: Difficulty/boundary_precision_check/evidence_weight_discount_saturates_at_five_business_days
    """
    _world, _invoice, weight_ten, weight_twelve = _two_disputes_at_weight_ten_and_twelve(
        api
    )

    exhibits = get_success_data(api.list_evidence(weight_twelve["id"], OFFICER))
    assert len(exhibits) == len(WEIGHT_TWELVE_TYPES)
    by_type = {row["evidence_type"]: row for row in exhibits}
    assert set(by_type) == set(WEIGHT_TWELVE_TYPES)
    for evidence_type, row in by_type.items():
        assert row["weight_points"] == EVIDENCE_WEIGHT_POINTS[evidence_type]
    assert by_type[EVIDENCE_WEIGHT_CERTIFICATE]["weight_points"] == 2

    assert (
        sum(row["weight_points"] for row in exhibits) == EVIDENCE_WEIGHT_TWELVE
    )
    ten_exhibits = get_success_data(api.list_evidence(weight_ten["id"], OFFICER))
    assert (
        sum(row["weight_points"] for row in ten_exhibits) == EVIDENCE_WEIGHT_TEN
    )
