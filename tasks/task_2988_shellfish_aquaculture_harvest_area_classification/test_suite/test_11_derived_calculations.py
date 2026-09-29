"""Derived figures the API materialises on write (PRD §3.2, §3.3, §3.5, §3.6,
§3.8, §3.9).

Each test pins one computation at the point the PRD states it: the inclusive
`MIN_NURSERY_DAYS` comparison and the two-decimal half-up survival rate (§3.5),
the gear-dependent short circuit in husbandry currency (§3.6), the two
time-to-temperature bases and the six settlement steps (§3.8), the inclusive
rainfall threshold and the closure clock derived from `observed_at` (§3.3), and
the `NARROW`/`BROAD` traceback scopes over one stored set of lots (§3.9). Every
expected number here was recomputed from the PRD's own rounding rules rather
than read back from an implementation.
"""
from test_helpers import (
    api_client,
    assert_governing_basis_consistent,
    assert_harvest_lot,
    assert_illness_investigation,
    assert_lot_settlement_consistent,
    assert_rainfall_event,
    assert_seed_lot,
    days_between,
    DEFAULT_RAINFALL_CLOSURE_HOURS,
    design_world,
    dw_assemble_shipment,
    DW_FIRST_OUT,
    DW_HARVEST_CLOCK,
    DW_INSPECTION_AT,
    dw_land_lot,
    DW_LAST_OUT,
    DW_PLACED_IN_CONTROL,
    dw_ship,
    dw_tag_lot,
    DW_WINDOW_END,
    DW_WINDOW_START,
    get_success_data,
    harvest_authorization_payload,
    harvest_lot_payload,
    INSPECTION_FEE_CENTS,
    iso,
    MIN_NURSERY_DAYS,
    nursery_complete_payload,
    open_investigation,
    rainfall_event_payload,
    record_classification_decision,
    set_clock,
    SURVIVAL_FLOOR_PCT,
    TEST_USERS,
    TIER1_RATE_CENTS,
    to_millis,
    traceback_payload,
    validate_success,
)

AUTHORITY = TEST_USERS["authority_headers"]
OPERATOR = TEST_USERS["operator_headers"]

# The reference nursery calendar: shipped 2026-04-01, screened 2026-04-03,
# nursery started 2026-04-05, with the logical clock at 2026-08-01T00:00:00Z.
NURSERY_STARTED_ON = "2026-04-05"
NURSERY_AT_MINIMUM_ON = "2026-04-26"
NURSERY_WELL_PAST_MINIMUM_ON = "2026-05-01"

# LOT-B sits later in the same 06:00-18:00 authorization window than the
# reference LOT-A, so its own two bases are shorter.
LOT_B_FIRST_OUT = iso(2026, 8, 10, 9)
LOT_B_LAST_OUT = iso(2026, 8, 10, 9, 30)
LOT_B_PLACED_IN_CONTROL = iso(2026, 8, 10, 10, 45)


def _seed_lot_in_nursery(received_seed_count):
    """The reference world walked as far as a seed lot in NURSERY. The hatchery
    certificate runs to 2027-03-31 and the disease certificate was issued
    2026-03-15, 17 days before the 2026-04-01 shipment, so all three sanitary
    gates of §3.5 are clear and the only rule left to exercise is the nursery
    period itself."""
    return design_world(
        stage="seed", seed_stage="nursery",
        seed_lot_overrides={"received_seed_count": received_seed_count},
    )


def test_nursery_completed_exactly_at_the_minimum_period_succeeds():
    """`MIN_NURSERY_DAYS` is 21 and the comparison is "at or after
    `nursery_started_on` plus 21 days", so a nursery run from 2026-04-05 to
    2026-04-26 — exactly 21 calendar days, not 22 — is accepted rather than
    refused with ERR_NURSERY_PERIOD_TOO_SHORT. 60 000 survivors out of 100 000
    received is 60.00 %, comfortably above `SURVIVAL_FLOOR_PCT` 40.00, so the lot
    reaches READY_FOR_PLANTING with its whole survivor count unallocated.

    Design: Corner/calculations/nursery_completed_exactly_at_the_minimum_period_succeeds
    """
    world = _seed_lot_in_nursery(100000)
    assert days_between(NURSERY_STARTED_ON, NURSERY_AT_MINIMUM_ON) == MIN_NURSERY_DAYS

    lot = validate_success(api_client.complete_nursery(
        world["seed_lot"]["id"],
        nursery_complete_payload(NURSERY_AT_MINIMUM_ON, 60000), OPERATOR))

    assert_seed_lot(lot)
    assert lot["status"] == "READY_FOR_PLANTING"
    assert lot["nursery_started_on"] == NURSERY_STARTED_ON
    assert lot["nursery_completed_on"] == NURSERY_AT_MINIMUM_ON
    assert lot["surviving_seed_count"] == 60000
    assert lot["survival_rate_pct"] == 60.00
    assert lot["survival_rate_pct"] >= SURVIVAL_FLOOR_PCT
    assert lot["allocated_seed_count"] == 0
    assert lot["unallocated_seed_count"] == 60000


def test_survival_rate_is_rounded_half_up_to_two_decimals():
    """100 x 60 000 / 90 000 is 66.6666...%, and §2.9 rounds seed survival half-up
    to exactly 2 decimal places, so the stored `survival_rate_pct` is 66.67 —
    neither truncated to 66.66 nor left at full float precision. The figure is
    far above the 40.00 floor either way, so nothing about the outcome depends on
    which side of the rounding the comparison sees: the lot reaches
    READY_FOR_PLANTING with 60 000 seed unallocated.

    Design: Corner/calculations/survival_rate_is_rounded_half_up_to_two_decimals
    """
    world = _seed_lot_in_nursery(90000)

    lot = validate_success(api_client.complete_nursery(
        world["seed_lot"]["id"],
        nursery_complete_payload(NURSERY_WELL_PAST_MINIMUM_ON, 60000), OPERATOR))

    assert lot["received_seed_count"] == 90000
    assert lot["surviving_seed_count"] == 60000
    assert lot["survival_rate_pct"] == 66.67
    assert lot["survival_rate_pct"] != 66.66
    assert lot["survival_rate_pct"] != 66.66666666666667
    assert lot["status"] == "READY_FOR_PLANTING"
    assert lot["unallocated_seed_count"] == 60000


# --------------------------------------------------------------------------
# The two traceback scopes over one stored set of lots (PRD §3.9)
# --------------------------------------------------------------------------
SHIPPED_AT = iso(2026, 8, 10, 10, 50)
# LOT-B is landed one logical hour after LOT-A so that the two rows carry
# distinct `created_at` stamps.
LOT_B_LANDED_CLOCK = iso(2026, 8, 10, 12)
REPORT_CLOCK = iso(2026, 8, 11, 9)
REPORTED_AT = iso(2026, 8, 11, 8)


def _investigation_over_one_shipped_lot_with_a_tagged_sibling():
    """Two lots are landed and tagged under the one authorization on GA-114, so
    both carry `tag_area_code` GA-114 and `tag_harvest_date` 2026-08-10: LOT-A
    (10 bushels, first out 06:00Z) and LOT-B (20 bushels, first out 09:00Z).
    Only LOT-A rides shipment SH-1 to Virginia, released at 10:50Z; LOT-B stays
    TAGGED with `shipment_id` null. The clock then moves to 2026-08-11T09:00:00Z
    and an OPEN investigation is filed against SH-1."""
    world = design_world(stage="tagged")
    # `traced_lot_ids` is ordered by `tag_harvest_date` then `created_at`, and
    # both lots share the harvest date, so the clock is advanced between the two
    # landings to give LOT-B a strictly later `created_at` (PRD §2.4, §3.9).
    set_clock(LOT_B_LANDED_CLOCK)
    world["lot_b"] = dw_tag_lot(world, dw_land_lot(
        world, LOT_B_FIRST_OUT, LOT_B_LAST_OUT, LOT_B_PLACED_IN_CONTROL,
        bushels=20))
    world["shipment"] = dw_ship(
        world,
        dw_assemble_shipment(world, [world["lot"]["id"]],
                             destination_state="VA"),
        SHIPPED_AT,
    )
    set_clock(REPORT_CLOCK)
    world["investigation"] = open_investigation(
        world, world["shipment"], REPORTED_AT)
    return world


def test_narrow_and_broad_traceback_diverge_on_the_same_stored_data():
    """`NARROW` traces exactly the source shipment's own lots, so it returns
    LOT-A alone. Re-run on the same investigation with no new data, `BROAD`
    additionally pulls in every TAGGED, SHIPPED or EMBARGOED lot sharing a seed
    lot's `tag_area_code` whose `tag_harvest_date` is within the one-day
    `TRACEBACK_DAY_WINDOW`, which admits the sibling LOT-B even though it never
    rode a shipment — `traced_lot_count` goes 1 then 2, ordered by
    `tag_harvest_date` then `created_at` so LOT-A precedes LOT-B. The
    TRACEBACK -> TRACEBACK self-edge means the second run replaces the first
    analysis rather than appending to it, and neither run is a cascade: LOT-B is
    still TAGGED, SH-1 is still SHIPPED, the dealer still holds zero strikes,
    and `confirmed_at` and `recalled_shipment_count` are untouched.

    Design: Corner/calculations/narrow_and_broad_traceback_diverge_on_the_same_stored_data
    """
    world = _investigation_over_one_shipped_lot_with_a_tagged_sibling()
    investigation_id = world["investigation"]["id"]

    narrow = validate_success(api_client.run_traceback(
        investigation_id, traceback_payload("NARROW"), AUTHORITY))
    broad = validate_success(api_client.run_traceback(
        investigation_id, traceback_payload("BROAD"), AUTHORITY))

    assert_illness_investigation(narrow)
    assert narrow["status"] == "TRACEBACK"
    assert narrow["scope_variant"] == "NARROW"
    assert narrow["traced_lot_count"] == 1
    assert narrow["traced_lot_ids"] == [world["lot"]["id"]]

    assert_illness_investigation(broad)
    assert broad["status"] == "TRACEBACK"
    assert broad["scope_variant"] == "BROAD"
    assert broad["traced_lot_count"] == 2
    assert broad["traced_lot_ids"] == [world["lot"]["id"], world["lot_b"]["id"]]
    assert broad["confirmed_at"] is None
    assert broad["recalled_shipment_count"] == 0

    lot_b = get_success_data(
        api_client.get_harvest_lot(world["lot_b"]["id"], AUTHORITY))
    shipment = get_success_data(
        api_client.get_shipment(world["shipment"]["id"], AUTHORITY))
    dealer = get_success_data(
        api_client.get_dealer(world["dealer"]["id"], AUTHORITY))
    assert lot_b["status"] == "TAGGED"
    assert lot_b["shipment_id"] is None
    assert shipment["status"] == "SHIPPED"
    assert dealer["recall_strike_count"] == 0


# --------------------------------------------------------------------------
# The governing time-to-temperature basis is read at landing time (PRD §3.8)
# --------------------------------------------------------------------------
def _active_world_then_area_downgraded_to_restricted():
    """Five ACCEPTED MPN-2 samples give the area the `MIN_SAMPLES_FOR_DECISION`
    five accepted samples a classification decision needs. The authorization is
    issued and activated while the area is still APPROVED; only then is the area
    downgraded to RESTRICTED. A strict downgrade needs no data support and never
    touches `harvest_status`, so the area is RESTRICTED and still OPEN when the
    lot is landed. The area is re-read first because issuing the authorization
    recomputed `open_authorization_count` and so advanced the area's version."""
    world = design_world(stage="active", sample_mpns=[2, 2, 2, 2, 2])
    area = get_success_data(
        api_client.get_growing_area(world["area"]["id"], AUTHORITY))
    world["area"] = record_classification_decision(
        area, "RESTRICTED",
        {"decision_note": "downgrade on rainfall-season review"})
    set_clock(DW_HARVEST_CLOCK)
    return world


def test_time_to_temperature_basis_switches_to_last_out_of_water_after_a_downgrade():
    """`ttt_basis_variant` is read from the growing area's `classification` at the
    moment of landing, not at authorization time. The same instants that would
    have been governed by the 270-minute first basis under APPROVED are governed
    by the 150-minute last basis under RESTRICTED, and both bases are still
    persisted. The allowance is unaffected by the downgrade: 300 baseline minus
    60 because 24.0 C is at or above the plan's 23.0 C, minus 30 for BOTTOM gear,
    plus 60 for MECHANICAL refrigeration, floored at 60, gives 270 — so the lot
    is COMPLIANT at 150. Settlement runs the six steps over a 10-bushel season
    total: rate 115, royalty 1150, the flat 2500 fee because 1150 is below the
    50 000-cent waiver, a half-up surcharge of 0.03 x 3650 = 110, and 3760 in all.

    Design: Corner/calculations/time_to_temperature_basis_switches_to_last_out_of_water_after_a_downgrade
    """
    world = _active_world_then_area_downgraded_to_restricted()

    lot = validate_success(api_client.create_harvest_lot(
        world["authorization"]["id"],
        harvest_lot_payload(DW_FIRST_OUT, DW_LAST_OUT, DW_PLACED_IN_CONTROL,
                            lot_code="LOT-A", bushels=10, water_temp_c=24.0),
        OPERATOR), 201)

    assert_harvest_lot(lot)
    assert lot["ttt_minutes_first_basis"] == 270
    assert lot["ttt_minutes_last_basis"] == 150
    assert lot["ttt_basis_variant"] == "LAST_HARVEST_BASIS"
    assert lot["governing_ttt_minutes"] == 150
    assert_governing_basis_consistent(lot)
    assert lot["allowed_ttt_minutes"] == 270
    assert lot["vibrio_plan_month"] == 8
    assert lot["vibrio_control_plan_id"] == world["plan"]["id"]
    assert lot["compliance_status"] == "COMPLIANT"

    assert lot["season_total_bushels_at_creation"] == 10
    assert lot["royalty_rate_cents_per_bushel"] == TIER1_RATE_CENTS
    assert lot["royalty_cents"] == 1150
    assert lot["inspection_fee_cents"] == INSPECTION_FEE_CENTS
    assert lot["conservation_surcharge_cents"] == 110
    assert lot["lot_settlement_cents"] == 3760
    assert_lot_settlement_consistent(lot)

    area = get_success_data(
        api_client.get_growing_area(world["area"]["id"], AUTHORITY))
    assert area["classification"] == "RESTRICTED"
    assert area["harvest_status"] == "OPEN"


# --------------------------------------------------------------------------
# The lease ledger is the plain sum of the per-lot settlements (PRD §3.8)
# --------------------------------------------------------------------------
def _land(world, lot_code, bushels, first_out, last_out, placed):
    """Land one lot under the reference authorization as the FarmOperator,
    asserting the 201 the PRD promises for a creation."""
    return validate_success(api_client.create_harvest_lot(
        world["authorization"]["id"],
        harvest_lot_payload(first_out, last_out, placed,
                            lot_code=lot_code, bushels=bushels,
                            water_temp_c=24.0),
        OPERATOR), 201)


def test_lease_accrual_reconciles_with_the_sum_of_per_lot_settlements():
    """Each landing adds its own `lot_settlement_cents` to the lease's
    `royalty_accrued_cents`, so after a 10-bushel and then a 20-bushel lot the
    ledger reads 3760 + 4944 = 8704. The tier is chosen from the season total
    including the lot being landed, but 30 bushels is still inside
    `TIER1_MAX_BUSHELS` 500, so both lots are rated at 115: LOT-A pays royalty
    1150 and surcharge half-up(0.03 x 3650) = 110; LOT-B pays royalty 2300 and
    surcharge half-up(0.03 x 4800) = 144. Both royalties are below the
    50 000-cent waiver so both pay the flat 2500 inspection fee. Rounding once
    per lot matters: one rounded sum over 8450 would be 254, not 110 + 144 = 254
    here by coincidence, so the reconciliation is asserted on the totals.

    Design: Corner/calculations/lease_accrual_reconciles_with_the_sum_of_per_lot_settlements
    """
    world = design_world(stage="active")
    set_clock(DW_HARVEST_CLOCK)

    lot_a = _land(world, "LOT-A", 10, DW_FIRST_OUT, DW_LAST_OUT,
                  DW_PLACED_IN_CONTROL)
    lot_b = _land(world, "LOT-B", 20, LOT_B_FIRST_OUT, LOT_B_LAST_OUT,
                  LOT_B_PLACED_IN_CONTROL)

    assert lot_a["season_total_bushels_at_creation"] == 10
    assert lot_a["royalty_rate_cents_per_bushel"] == TIER1_RATE_CENTS
    assert lot_a["royalty_cents"] == 1150
    assert lot_a["inspection_fee_cents"] == INSPECTION_FEE_CENTS
    assert lot_a["conservation_surcharge_cents"] == 110
    assert lot_a["lot_settlement_cents"] == 3760
    assert lot_a["compliance_status"] == "COMPLIANT"
    assert lot_a["status"] == "HARVESTED"
    assert_lot_settlement_consistent(lot_a)

    assert lot_b["season_total_bushels_at_creation"] == 30
    assert lot_b["royalty_rate_cents_per_bushel"] == TIER1_RATE_CENTS
    assert lot_b["royalty_cents"] == 2300
    assert lot_b["inspection_fee_cents"] == INSPECTION_FEE_CENTS
    assert lot_b["conservation_surcharge_cents"] == 144
    assert lot_b["lot_settlement_cents"] == 4944
    assert lot_b["compliance_status"] == "COMPLIANT"
    assert lot_b["status"] == "HARVESTED"
    assert_lot_settlement_consistent(lot_b)

    lease = get_success_data(
        api_client.get_lease(world["lease"]["id"], AUTHORITY))
    authorization = get_success_data(api_client.get_harvest_authorization(
        world["authorization"]["id"], OPERATOR))

    assert lease["royalty_accrued_cents"] == 8704
    assert lease["royalty_accrued_cents"] == (
        lot_a["lot_settlement_cents"] + lot_b["lot_settlement_cents"])
    assert authorization["harvested_bushels"] == 30
    assert authorization["projected_bushels"] == 600
    assert authorization["status"] == "ACTIVE"


# --------------------------------------------------------------------------
# The rainfall threshold is inclusive and the closure clock is the observation
# (PRD §3.3)
# --------------------------------------------------------------------------
RAINFALL_CLOCK = iso(2026, 8, 6)
RAINFALL_OBSERVED_AT = iso(2026, 8, 5)
REOPEN_ELIGIBLE_AT = iso(2026, 8, 9)


def test_rainfall_exactly_at_the_threshold_opens_a_ninety_six_hour_closure():
    """The comparison is "at or above" the area's
    `rainfall_closure_threshold_in`, so 1.00 inches against a 1.00-inch threshold
    triggers the closure rather than falling just short of it. The closure window
    is anchored on the event's own `observed_at` and not on the logical clock:
    the event is observed a full day in the past, at 2026-08-05T00:00:00Z, so
    `last_closure_started_at` is that instant and
    `closure_reopen_eligible_at` is 96 hours later at 2026-08-09T00:00:00Z --
    not 2026-08-10T00:00:00Z, which is what anchoring on the 2026-08-06 clock
    would give. `classification` is a separate dimension from `harvest_status`
    and so is untouched, no authorization exists to void, and the closure does
    not reset the clean-sample counter's starting value of zero.

    Design: Corner/calculations/rainfall_exactly_at_the_threshold_opens_a_ninety_six_hour_closure
    """
    world = design_world(stage="area")
    set_clock(RAINFALL_CLOCK)

    event = validate_success(api_client.create_rainfall_event(
        world["area"]["id"],
        rainfall_event_payload(gauge_code="RG-7",
                               observed_at=RAINFALL_OBSERVED_AT,
                               inches_24h=1.00),
        AUTHORITY), 201)

    assert_rainfall_event(event)
    assert event["triggered_closure"] is True
    assert event["inches_24h"] == 1.00
    assert event["observed_at"] == to_millis(RAINFALL_OBSERVED_AT)
    assert event["voided_authorization_count"] == 0

    area = get_success_data(
        api_client.get_growing_area(world["area"]["id"], AUTHORITY))
    assert area["harvest_status"] == "CLOSED_RAINFALL"
    assert area["rainfall_closure_threshold_in"] == 1.00
    assert area["rainfall_closure_hours"] == DEFAULT_RAINFALL_CLOSURE_HOURS
    assert area["last_closure_started_at"] == to_millis(RAINFALL_OBSERVED_AT)
    assert area["closure_reopen_eligible_at"] == to_millis(REOPEN_ELIGIBLE_AT)
    assert area["classification"] == "APPROVED"
    assert area["consecutive_clean_samples"] == 0


# --------------------------------------------------------------------------
# Husbandry currency is gear-dependent (PRD §3.6)
# --------------------------------------------------------------------------
def test_rack_and_bag_gear_carries_no_predator_control_obligation():
    """Husbandry currency is the conjunction of an inspection test and a predator
    test, but the predator test auto-passes for any gear type other than BOTTOM.
    A RACK_AND_BAG unit that has only ever filed an INSPECTION log is therefore
    `husbandry_current` with `last_predator_control_at` still null: the
    11-day-old inspection is well inside `INSPECTION_MAX_AGE_DAYS` 30, and the
    absent predator-control log is simply not consulted. Issuing an authorization
    against that unit succeeds with 201 ISSUED rather than being refused for a
    lapsed predator control or lapsed husbandry, and the vessel's
    `active_authorization_count` picks the new authorization up.

    Design: Corner/calculations/rack_and_bag_gear_carries_no_predator_control_obligation
    """
    world = design_world(
        stage="unit",
        unit_overrides={"gear_type": "RACK_AND_BAG"},
        predator_control_at=None,
    )

    unit = get_success_data(
        api_client.get_growout_unit(world["unit"]["id"], OPERATOR))
    authorization = validate_success(api_client.create_harvest_authorization(
        harvest_authorization_payload(
            world["lease"]["id"], world["unit"]["id"], world["vessel"]["id"],
            world["dealer"]["id"], DW_WINDOW_START, DW_WINDOW_END,
            projected_bushels=600),
        OPERATOR), 201)

    assert unit["gear_type"] == "RACK_AND_BAG"
    assert unit["last_inspection_at"] == to_millis(DW_INSPECTION_AT)
    assert unit["last_predator_control_at"] is None
    assert unit["husbandry_current"] is True

    assert authorization["status"] == "ISSUED"
    assert authorization["growout_unit_id"] == world["unit"]["id"]

    vessel = get_success_data(
        api_client.get_harvest_vessel(world["vessel"]["id"], OPERATOR))
    assert vessel["active_authorization_count"] == 1
