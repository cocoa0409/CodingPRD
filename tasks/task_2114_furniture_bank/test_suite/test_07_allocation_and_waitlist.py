"""The waterfall allocation selector, the unmet-need waitlist and its report."""

import pytest

from test_helpers import (
    ADMIN,
    WAREHOUSE,
    allocate,
    cancel_voucher,
    create_truck,
    donation_item_payload,
    list_inventory,
    list_voucher_lines,
    list_waitlist,
    prepare_offer_for_intake,
    run_intake,
    set_clock,
    setup_allocated_voucher,
    setup_issued_voucher,
    supply_clean_stock,
    unmet_need_report,
    validate_paginated,
    validate_success,
    voucher_line_payload,
)
from test_helpers.assertions import (
    assert_line_stock_conservation,
    assert_voucher,
    assert_voucher_money_identity,
    assert_waitlist_entry,
)


def _voucher_waitlisted_for_two_beds():
    """A CENTRAL household asks for two BEDs against an empty warehouse."""
    set_clock("2026-08-04T09:00:00Z")
    scenario = setup_issued_voucher(
        lines=[voucher_line_payload("BED", 2, "B")],
        agency_name="Willow Bank Aid",
    )
    scenario["allocated"] = allocate(
        scenario["voucher"]["id"], scenario["voucher"]["version"]
    )
    return scenario


# ─── Corner: the selector's eligibility, ranking and tie-break ─────────

def test_allocation_spends_the_worst_acceptable_grade_first(api):
    """PRD §3.6: "Qualifying units are then ranked so that the worst acceptable
    grade is spent first, keeping A-grade stock for households that demand it:
    units are ordered by condition rank descending, so `C` before `B` before
    `A`; then by ascending `available_since`, so the unit that has been on the
    floor longest goes first; and ties are broken by ascending `created_at`."
    PRD §3.6: "A round that fills every line completely moves the voucher
    `ISSUED → ALLOCATED`, reserving the selected units, setting every line's
    `status` to `FILLED`, and recomputing `fill_ratio` and the provisional money
    fields."

    Design: Corner/calculations/corner_allocation_spends_worst_acceptable_condition_grade_first
    """
    set_clock("2026-08-04T09:00:00Z")
    scenario = setup_issued_voucher(
        lines=[voucher_line_payload("BED", 1, "C")],
        agency_name="Alder Court Aid",
    )
    truck = create_truck(label="BOX-30", capacity_cubic_feet=600,
                         home_county="CENTRAL", crew_minimum=1)
    supply = supply_clean_stock(
        truck["id"],
        [donation_item_payload("BED", "B", False, 30.0),
         donation_item_payload("BED", "C", False, 30.0)],
        grades=["A", "C"], donor_name="Vera Popescu", donor_phone="555-0601",
    )
    unit_a = list_inventory(donation_item_id=supply["items"][0]["id"])[0]
    unit_c = list_inventory(donation_item_id=supply["items"][1]["id"])[0]

    allocate(scenario["voucher"]["id"], scenario["voucher"]["version"])

    unit_c_now = validate_success(api.get_inventory_item(unit_c["id"], WAREHOUSE))
    unit_a_now = validate_success(api.get_inventory_item(unit_a["id"], WAREHOUSE))
    assert unit_c_now["status"] == "RESERVED", "the C-grade unit is spent first"
    assert unit_a_now["status"] == "AVAILABLE", "the A-grade unit is kept back"
    assert unit_a_now["reserved_for_voucher_line_id"] is None

    voucher_now = validate_success(api.get_voucher(scenario["voucher"]["id"], ADMIN))
    assert voucher_now["status"] == "ALLOCATED"
    assert voucher_now["fill_ratio"] == pytest.approx(1.0, abs=0.0005)


def test_allocation_tie_break_prefers_the_longest_standing_available_unit(api):
    """PRD §3.6: "Qualifying units are then ranked so that the worst acceptable
    grade is spent first, keeping A-grade stock for households that demand it:
    units are ordered by condition rank descending, so `C` before `B` before
    `A`; then by ascending `available_since`, so the unit that has been on the
    floor longest goes first; and ties are broken by ascending `created_at`."
    PRD §3.5: "On the **clean branch** — no inspection reported
    `live_pest_observed` true *and* no accepted piece on the offer has
    `soft_surface` true — the offer moves `PICKUP_SCHEDULED → INSPECTED` and
    every minted unit is created directly in `status` `AVAILABLE` with its
    `available_since` set to the current instant and its
    `reserved_for_voucher_line_id` null."

    Design: Corner/calculations/corner_allocation_tie_break_is_available_since_ascending
    """
    set_clock("2026-08-04T09:00:00Z")
    scenario = setup_issued_voucher(
        lines=[voucher_line_payload("BED", 1, "B")],
        agency_name="Bramble Lane Trust",
    )
    truck = create_truck(label="BOX-31", capacity_cubic_feet=600,
                         home_county="CENTRAL", crew_minimum=1)

    early_supply = supply_clean_stock(
        truck["id"], [donation_item_payload("BED", "B", False, 30.0)],
        donor_name="Early Donor", donor_phone="555-0611",
    )
    early_unit = list_inventory(donation_item_id=early_supply["items"][0]["id"])[0]
    assert early_unit["available_since"] == "2026-08-04T09:00:00.000Z"

    set_clock("2026-08-04T14:00:00Z")
    late_supply = supply_clean_stock(
        truck["id"], [donation_item_payload("BED", "B", False, 30.0)],
        donor_name="Late Donor", donor_phone="555-0612",
        window_start="2026-08-04T15:00:00Z", window_end="2026-08-04T17:00:00Z",
    )
    late_unit = list_inventory(donation_item_id=late_supply["items"][0]["id"])[0]
    assert late_unit["available_since"] == "2026-08-04T14:00:00.000Z"

    allocate(scenario["voucher"]["id"], scenario["voucher"]["version"])

    early_now = validate_success(api.get_inventory_item(early_unit["id"], WAREHOUSE))
    late_now = validate_success(api.get_inventory_item(late_unit["id"], WAREHOUSE))
    assert early_now["status"] == "RESERVED", "the older unit goes first"
    assert late_now["status"] == "AVAILABLE"

    voucher_now = validate_success(api.get_voucher(scenario["voucher"]["id"], ADMIN))
    assert voucher_now["status"] == "ALLOCATED"


def test_allocation_never_draws_from_quarantined_stock(api):
    """PRD §3.6: "Units sitting in `QUARANTINED` are invisible to allocation; a
    unit becomes selectable only once a clean intake or a quarantine release has
    moved it to `AVAILABLE`."
    PRD §3.6: "A round that yields nothing at all leaves the voucher `ISSUED →
    ISSUED`: every unfilled line becomes `WAITLISTED` with a `WAITING` entry
    recorded, `fill_ratio` stays 0.0, and because no stock is held the money
    fields stay at 0 and `fee_basis` stays null."

    Design: Corner/calculations/corner_allocation_never_draws_from_quarantined_stock
    """
    set_clock("2026-08-04T09:00:00Z")
    scenario = setup_issued_voucher(
        lines=[voucher_line_payload("SOFA", 1, "C")],
        agency_name="Cinderpath Relief",
    )
    truck = create_truck(label="BOX-32", capacity_cubic_feet=600,
                         home_county="CENTRAL", crew_minimum=1)
    prepared = prepare_offer_for_intake(
        truck["id"],
        [donation_item_payload("SOFA", "B", True, 40.0),
         donation_item_payload("DRESSER", "B", False, 20.0),
         donation_item_payload("TABLE_SET", "B", False, 20.0)],
        donor_name="Wren Halloway", donor_phone="555-0621",
    )
    run_intake(prepared["offer"]["id"], prepared["items"])

    response = api.allocate_voucher(
        scenario["voucher"]["id"],
        {"expected_voucher_version": scenario["voucher"]["version"]},
        WAREHOUSE,
    )
    voucher_after = validate_success(response, 200)

    assert_voucher(voucher_after)
    assert voucher_after["status"] == "ISSUED", "finding nothing is never an error"
    assert voucher_after["fill_ratio"] == pytest.approx(0.0, abs=0.0005)
    assert voucher_after["gross_fee_cents"] == 0
    assert voucher_after["fee_basis"] is None

    quarantined, _ = validate_paginated(
        api.list_inventory_items(WAREHOUSE, {"status": "QUARANTINED", "limit": 100})
    )
    assert len(quarantined) == 3, "every unit is still off the floor"
    reserved, _ = validate_paginated(
        api.list_inventory_items(WAREHOUSE, {"status": "RESERVED", "limit": 100})
    )
    assert reserved == []

    entries = list_waitlist(client_id=scenario["client"]["id"], status="WAITING")
    assert len(entries) == 1
    assert_waitlist_entry(entries[0])
    assert entries[0]["category"] == "SOFA"
    assert entries[0]["quantity_unmet"] == 1


def test_allocation_response_already_carries_every_derived_field(api):
    """PRD §3.6: "A round that fills every line completely moves the voucher
    `ISSUED → ALLOCATED`, reserving the selected units, setting every line's
    `status` to `FILLED`, and recomputing `fill_ratio` and the provisional money
    fields."
    PRD §3.9: "From that basis the gross fee is assembled in a strict order.
    First, a base amount is taken from the service county: 4000 cents for
    `NORTH`, 3000 cents for `CENTRAL`, and 5000 cents for `SOUTH`."
    PRD §3.9: "Money is then settled with exactly one rounding step:
    `subsidy_cents` is `gross_fee_cents` multiplied by that percentage, rounded
    half up to whole cents, and `client_due_cents` is `gross_fee_cents` minus
    `subsidy_cents`, never re-rounded."

    Design: Corner/consistency_model/corner_allocation_response_already_reflects_every_derived_field
    """
    set_clock("2026-08-04T09:00:00Z")
    scenario = setup_allocated_voucher(
        lines=[voucher_line_payload("BED", 1, "B")],
        offer_items=[donation_item_payload("BED", "B", False, 30.0)],
        truck_label="BOX-66", agency_name="Dunbarrow Household Bank",
    )
    body = scenario["allocated"]

    assert body["status"] == "ALLOCATED", "the response already carries the new state"
    assert body["fill_ratio"] == pytest.approx(1.0, abs=0.0005)
    assert body["gross_fee_cents"] == 5700, "CENTRAL 3000 + one bulk 1200 + lift 1500"
    assert body["subsidy_cents"] == 3990
    assert body["client_due_cents"] == 1710
    assert body["fee_basis"] == "PROVISIONAL"
    assert_voucher_money_identity(body)

    unit = list_inventory(donation_item_id=scenario["donation_items"][0]["id"])[0]
    assert unit["status"] == "RESERVED", "an immediate read already shows the hold"

    lines = list_voucher_lines(scenario["voucher"]["id"])
    assert len(lines) == 1
    assert lines[0]["status"] == "FILLED"
    assert lines[0]["quantity_allocated"] == 1
    assert list_waitlist(client_id=scenario["client"]["id"]) == []


def test_unmet_need_report_groups_two_categories_for_one_household(api):
    """PRD §3.6: "The surviving entries are grouped by the pair of `county` and
    `category`, one row per group that has at least one entry, ordered by county
    in the literal sequence `NORTH`, then `CENTRAL`, then `SOUTH`, and within a
    county by the same category priority the allocator uses, so `BED` first and
    `KITCHEN_KIT` last."
    PRD §3.6: "Alongside the rows the response carries `generated_at`, the array
    `rows`, `total_unmet_quantity` as the sum of `unmet_quantity` across all
    rows, and `total_households_waiting` as the count of distinct `client_id`
    values across the entire filtered source set — which is not the sum of the
    per-row counts, because one household can wait in several categories."

    Design: Corner/calculations/corner_unmet_need_report_groups_two_categories_for_one_household
    """
    set_clock("2026-08-04T09:00:00Z")
    scenario = setup_issued_voucher(
        lines=[voucher_line_payload("BED", 2, "B"),
               voucher_line_payload("LINENS", 1, "C")],
        categories=["BED", "LINENS"], agency_name="Elmsworth Family Net",
    )
    allocate(scenario["voucher"]["id"], scenario["voucher"]["version"])

    report = unmet_need_report()

    rows = report["rows"]
    assert len(rows) == 2, f"one row per county/category group, got {len(rows)}"
    assert rows[0]["category"] == "BED", "BED outranks LINENS in category priority"
    assert rows[0]["county"] == "CENTRAL"
    assert rows[0]["unmet_quantity"] == 2
    assert rows[1]["category"] == "LINENS"
    assert rows[1]["county"] == "CENTRAL"
    assert rows[1]["unmet_quantity"] == 1
    assert rows[0]["households_waiting"] == 1
    assert rows[1]["households_waiting"] == 1
    assert rows[0]["fill_rate_pct"] == pytest.approx(0.0, abs=0.05)
    assert rows[1]["fill_rate_pct"] == pytest.approx(0.0, abs=0.05)
    assert report["total_unmet_quantity"] == 3
    assert report["total_households_waiting"] == 1, (
        "one household waiting in two categories counts once"
    )


# ─── Difficulty: the empty-set edge of the unmet-need report ───────────

def test_unmet_need_report_for_a_county_with_no_waiting_demand_is_empty(api):
    """PRD §3.6: "When nothing is waiting, the answer is an empty `rows` array
    with `total_unmet_quantity` and `total_households_waiting` both 0; it is
    never a 404 and never a row with zeroed fields."
    PRD §3.6: "It accepts two optional filters, `county` and `category`, each
    narrowing the source set to entries carrying that value."

    Design: Difficulty/boundary_precision_check/unmet_need_report_on_empty_county_group_returns_empty_rows
    """
    scenario = _voucher_waitlisted_for_two_beds()

    report = unmet_need_report(county="SOUTH")

    assert report["rows"] == [], "a county with no waiting entry produces no row"
    assert report["total_unmet_quantity"] == 0
    assert report["total_households_waiting"] == 0

    voucher_now = validate_success(api.get_voucher(scenario["voucher"]["id"], ADMIN))
    assert voucher_now["status"] == "ISSUED"


def test_unmet_need_report_for_the_waiting_county_reports_one_row(api):
    """PRD §3.6: "Each row reports `unmet_quantity`, the sum of `quantity_unmet`
    across the group's entries; `households_waiting`, the number of distinct
    `client_id` values in the group; `max_wait_days`, the largest number of
    whole 24-hour days elapsed between an entry's `waiting_since` and now,
    rounded down; `top_priority_score`, the highest `priority_score` in the
    group; `requested_units`, the total demand ever raised in that county and
    category, being the sum of `quantity_requested` over every voucher line of
    that category whose household's `county` matches the group and whose
    `status` is not `CANCELLED`; `allocated_units`, the sum of
    `quantity_allocated` over those same lines; and `fill_rate_pct`, which is
    100 multiplied by `allocated_units` divided by `requested_units`, rounded
    half up to one decimal place, or null when `requested_units` is zero."

    Design: Difficulty/boundary_precision_check/unmet_need_report_on_empty_county_group_returns_empty_rows
    """
    _voucher_waitlisted_for_two_beds()

    report = unmet_need_report(county="CENTRAL")

    rows = report["rows"]
    assert len(rows) == 1, f"one BED group in CENTRAL, got {len(rows)}"
    row = rows[0]
    assert row["county"] == "CENTRAL"
    assert row["category"] == "BED"
    assert row["unmet_quantity"] == 2
    assert row["households_waiting"] == 1
    assert row["max_wait_days"] == 0, "the entry was created at the current instant"
    assert row["fill_rate_pct"] == pytest.approx(0.0, abs=0.05), (
        "two units requested and none allocated"
    )
    assert report["total_unmet_quantity"] == 2
    assert report["total_households_waiting"] == 1


# ─── Difficulty: stock units conserved across allocate then cancel ─────

def test_allocation_reserves_only_the_requested_units(api):
    """PRD §3.6: "The selector takes the first units in that order up to the
    line's shortfall. Each taken unit moves `AVAILABLE → RESERVED`, records the
    line in its `reserved_for_voucher_line_id`, raises the line's
    `quantity_allocated` by 1, and has its `version` bumped."
    PRD §2.10: "The second is physical stock. `VoucherLine.quantity_allocated`
    must always equal the number of inventory units whose
    `reserved_for_voucher_line_id` points at that line and whose `status` is
    `RESERVED`, `STAGED` or `DELIVERED`."

    Design: Difficulty/compensating_invariant/inventory_units_conserved_across_allocate_then_voucher_cancel
    """
    set_clock("2026-08-04T09:00:00Z")
    scenario = setup_allocated_voucher(
        lines=[voucher_line_payload("BED", 2, "B")],
        offer_items=[donation_item_payload("BED", "B", False, 30.0)] * 3,
        truck_label="BOX-12", agency_name="Copperfield Mutual Aid",
    )

    assert scenario["allocated"]["status"] == "ALLOCATED"
    assert scenario["allocated"]["fill_ratio"] == pytest.approx(1.0, abs=0.0005)

    lines = list_voucher_lines(scenario["voucher"]["id"])
    assert len(lines) == 1
    assert lines[0]["quantity_allocated"] == 2, "two of the three BEDs are reserved"
    assert_line_stock_conservation(lines[0], list_inventory())

    available, _ = validate_paginated(
        api.list_inventory_items(WAREHOUSE, {"status": "AVAILABLE",
                                             "category": "BED", "limit": 100})
    )
    assert len(available) == 1, "one BED is left on the floor"


def test_voucher_cancellation_returns_every_reserved_unit_to_the_floor(api):
    """PRD §3.3: "From `PARTIALLY_ALLOCATED → CANCELLED` and from `ALLOCATED →
    CANCELLED` the effects are identical to each other and add stock release:
    every inventory unit reserved against those lines moves `RESERVED →
    AVAILABLE`, its `reserved_for_voucher_line_id` is cleared, its
    `available_since` is restamped to the current instant, and the owning line's
    `quantity_allocated` drops by one per released unit; then every line moves
    to `CANCELLED`, every `WAITING` waitlist entry for those lines moves to
    `CANCELLED`, and the voucher's `version` is bumped."
    PRD §2.10: "For every category, the count of `AVAILABLE` units therefore
    returns to its pre-allocation value once every unit reserved for the line
    has been released — although `available_since` is restamped on the way back,
    so the returned unit re-enters the allocation ranking at the back of its
    grade's queue."

    Design: Difficulty/compensating_invariant/inventory_units_conserved_across_allocate_then_voucher_cancel
    """
    set_clock("2026-08-04T09:00:00Z")
    scenario = setup_allocated_voucher(
        lines=[voucher_line_payload("BED", 2, "B")],
        offer_items=[donation_item_payload("BED", "B", False, 30.0)] * 3,
        truck_label="BOX-12", agency_name="Copperfield Mutual Aid",
    )
    line = list_voucher_lines(scenario["voucher"]["id"])[0]

    cancelled = cancel_voucher(
        scenario["voucher"]["id"], scenario["agency"]["id"],
        reason="Household relocated out of the service area",
    )
    assert cancelled["status"] == "CANCELLED"

    line_now = list_voucher_lines(scenario["voucher"]["id"])[0]
    assert line_now["id"] == line["id"]
    assert line_now["quantity_allocated"] == 0, "every held unit is given back"
    assert line_now["status"] == "CANCELLED"

    available, _ = validate_paginated(
        api.list_inventory_items(WAREHOUSE, {"status": "AVAILABLE",
                                             "category": "BED", "limit": 100})
    )
    assert len(available) == 3, "the AVAILABLE BED count returns to its former value"

    reserved, _ = validate_paginated(
        api.list_inventory_items(WAREHOUSE, {"status": "RESERVED", "limit": 100})
    )
    assert reserved == []

    still_held, _ = validate_paginated(
        api.list_inventory_items(WAREHOUSE,
                                 {"reserved_for_voucher_line_id": line["id"],
                                  "limit": 100})
    )
    assert still_held == [], "no unit still points at the cancelled line"
    assert_line_stock_conservation(line_now, list_inventory())
