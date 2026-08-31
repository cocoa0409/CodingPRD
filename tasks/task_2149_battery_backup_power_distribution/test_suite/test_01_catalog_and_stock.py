"""Catalog, sites and stock: derived postures, refresh charging and the logical clock."""
import pytest

from test_helpers import (
    validate_error, validate_success, validate_paginated, ApiErrorId, TEST_USERS,
    create_warehouse, create_battery_model, receive_lot, refresh_charge, set_clock,
    read_lot, api_client,
)

OPERATOR = TEST_USERS["warehouse_operator_headers"]
ADMIN = TEST_USERS["admin_headers"]


def _lot_refreshed_at_the_default_clock():
    warehouse = create_warehouse(code="TX-DAL", state_code="TX", hazmat_endorsement=True,
                                 storm_reserve_pct=0.0, dock_capacity_kg_per_window=100000.0)
    model = create_battery_model("IB-SLF-5")
    lot = receive_lot(model["id"], warehouse["id"], manufactured_on="2026-03-01",
                      quantity_on_hand=20)
    refreshed = refresh_charge(lot["id"], 12.75)
    return {"warehouse": warehouse, "model": model, "lot": lot, "refreshed": refreshed}


def test_refresh_landing_exactly_on_the_cooldown_upper_bound_is_refused(api):
    """PRD §3.2: "And a lot that was refresh-charged recently is refused with
    `ERR_REFRESH_COOLDOWN_ACTIVE` (HTTP 409): the cooldown runs 72 hours — three
    full days — from `last_refresh_charged_at`, and the interval is **closed at
    both ends**, so a request whose clock instant lands exactly on the upper
    bound is inside the cooldown and is rejected. Only a clock instant strictly
    beyond that upper bound is admitted."
    PRD §2.4: "Before the clock is ever set, it reads exactly
    `2026-08-01T00:00:00Z`, and it never falls back to real time."

    Design: Difficulty/resource_temporal_overlap/refresh_cooldown_closed_interval_rejects_exact_upper_bound
    """
    ctx = _lot_refreshed_at_the_default_clock()
    assert ctx["lot"]["state_of_charge_pct"] == pytest.approx(75.0, abs=1e-9)
    assert ctx["refreshed"]["refresh_charge_count"] == 1
    assert ctx["refreshed"]["state_of_charge_pct"] == pytest.approx(100.0, abs=1e-9)

    set_clock("2026-08-04T00:00:00Z")
    resp = api.refresh_charge_lot(ctx["lot"]["id"],
                                  {"measured_open_circuit_voltage": 12.80}, OPERATOR)
    validate_error(resp, ApiErrorId.ERR_REFRESH_COOLDOWN_ACTIVE.value)


def test_refresh_one_second_beyond_the_cooldown_succeeds_and_resets_the_baseline(api):
    """PRD §3.2: "It sets `last_refresh_charged_at` to the current logical clock
    instant, increments `refresh_charge_count` by 1, and resets the storage
    baseline so that `state_of_charge_pct` re-derives to exactly 100.0 and the
    lot lands on `SELLABLE`."
    PRD §3.2: "Only a clock instant strictly beyond that upper bound is
    admitted."

    Design: Difficulty/resource_temporal_overlap/refresh_cooldown_closed_interval_rejects_exact_upper_bound
    """
    ctx = _lot_refreshed_at_the_default_clock()
    set_clock("2026-08-04T00:00:00Z")
    api.refresh_charge_lot(ctx["lot"]["id"], {"measured_open_circuit_voltage": 12.80},
                           OPERATOR)

    set_clock("2026-08-04T00:00:01Z")
    second = refresh_charge(ctx["lot"]["id"], 12.80)

    assert second["refresh_charge_count"] == 2, \
        f"Expected a second cycle, got {second['refresh_charge_count']}"
    assert str(second["last_refresh_charged_at"]).startswith("2026-08-04T00:00:01"), \
        f"The stamp comes from the logical clock, got {second['last_refresh_charged_at']}"
    assert second["condition_state"] == "SELLABLE"
    assert second["state_of_charge_pct"] == pytest.approx(100.0, abs=1e-9)


# --------------------------------------------------------------------------
# Catalog creation and its derived physics
# --------------------------------------------------------------------------

def test_creating_a_model_derives_its_watt_hours_class_and_severity_rank(api):
    """PRD §3.1: "The `watt_hour_rating` is the nominal voltage multiplied by
    the amp-hour capacity, rounded half up to two decimal places."
    PRD §3.1: "The classification rules are exhaustive and mutually exclusive: a
    flooded lead-acid model is always `UN2794`; a nickel-cadmium model is always
    `UN2795`; an AGM or gel model is `UN2800_EXCEPTED` when its unit weight is
    at most 30.0 kilograms and `UN2800` when it is heavier, so a unit weighing
    exactly 30.0 kilograms is excepted; and a lithium-iron-phosphate model is
    `NON_REGULATED` when its watt-hour rating is at most 20.0 watt-hours,
    `UN3480_SECTION_II` when the rating is greater than 20.0 but at most 100.0
    watt-hours, so a cell rated at exactly 100.0 watt-hours is Section II, and
    `UN3480_SECTION_IA` above that."
    PRD §3.1: "The third derived field, `hazmat_severity_rank`, is the ordinal
    of that class on a fixed severity scale where `NON_REGULATED` ranks 0,
    `UN2800_EXCEPTED` ranks 1, `UN2795` ranks 2, `UN2800` ranks 3, `UN2794`
    ranks 4, `UN3480_SECTION_II` ranks 5 and `UN3480_SECTION_IA` ranks 6."
    PRD §3.1: "A model opens with `status` set to `ACTIVE` and
    `replacement_model_id` null."

    Design: Corner/entities/create_battery_model_derives_hazmat_and_watt_hour_fields
    """
    model = create_battery_model("IB-31-FLD")
    read = validate_success(api.get_battery_model(model["id"], TEST_USERS["sales_rep_headers"]))

    assert read["watt_hour_rating"] == pytest.approx(1200.0, abs=0.005)
    assert read["hazmat_class_code"] == "UN2794"
    assert read["hazmat_severity_rank"] == 4
    assert read["status"] == "ACTIVE"
    assert read["replacement_model_id"] is None
    assert read["version"] == 1, f"version starts at 1, got {read['version']}"


def test_new_account_takes_the_declared_defaults(api):
    """PRD §3.1: "An account may optionally declare a `storm_priority_rank`, its
    contractual storm-callout rank, where 1 is the highest priority and 9 the
    lowest; when the caller omits it the account is ranked 9, and any supplied
    value outside the inclusive range 1 through 9 is a malformed request."
    PRD §3.1: "A new account opens with `status` set to `ACTIVE` — the only
    other posture is `CREDIT_HOLD`, and only `ACTIVE` permits order submission —
    and with all four of its ledger fields at zero: `open_receivable_cents`,
    `core_deposit_balance_cents`, `warranty_credit_cents` and
    `lifetime_lead_recovered_kg`, the last of which is a cumulative lead mass
    carried to three decimals."

    Design: Corner/entities/create_account_applies_declared_defaults
    """
    resp = api.create_account({
        "name": "Default Ranch Supply", "account_tier": "STANDARD",
        "state_code": "TX", "credit_limit_cents": 500000,
    }, ADMIN)
    account = validate_success(resp, 201)

    assert account["storm_priority_rank"] == 9
    assert account["status"] == "ACTIVE"
    assert account["open_receivable_cents"] == 0
    assert account["core_deposit_balance_cents"] == 0
    assert account["warranty_credit_cents"] == 0
    assert account["lifetime_lead_recovered_kg"] == pytest.approx(0.0, abs=0.0005)


def test_model_with_an_undeclared_chemistry_is_rejected(api):
    """PRD §3.1: "The body carries the cell `chemistry`, one of
    `FLOODED_LEAD_ACID`, `AGM`, `GEL`, `LITHIUM_IRON_PHOSPHATE` or
    `NICKEL_CADMIUM`"
    PRD §2.6: "The request body being well formed — every required field
    present, every value of its declared type, every enum value a declared
    member — otherwise `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_battery_model_with_undeclared_chemistry_returns_invalid_request
    """
    resp = api.create_battery_model({
        "sku": "IB-NA-99", "chemistry": "SODIUM_ION", "nominal_voltage": 12,
        "amp_hour_capacity": 100, "peukert_exponent": 1.15, "unit_weight_kg": 20.0,
        "lead_content_kg": 0.0, "core_deposit_cents": 0, "list_price_cents": 40000,
        "warranty_free_replacement_months": 12, "warranty_prorata_months": 12,
        "shelf_life_days": 700, "self_discharge_pct_per_month": 2.0,
    }, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_a_second_model_reusing_a_sku_is_refused(api):
    """PRD §3.1: "Its `sku` must be unique across every model row regardless of
    that row's `status`, and a collision is refused with `ERR_DUPLICATE_SKU`
    (HTTP 409); the same code guards the uniqueness of a warehouse `code` and of
    a carrier `code` within their own collections."

    Design: Corner/entities/duplicate_battery_model_sku_returns_duplicate_sku
    """
    create_battery_model("IB-31-FLD")

    resp = api.create_battery_model({
        "sku": "IB-31-FLD", "chemistry": "AGM", "nominal_voltage": 12,
        "amp_hour_capacity": 95, "peukert_exponent": 1.10, "unit_weight_kg": 28.0,
        "lead_content_kg": 13.0, "core_deposit_cents": 2500, "list_price_cents": 26000,
        "warranty_free_replacement_months": 24, "warranty_prorata_months": 36,
        "shelf_life_days": 730, "self_discharge_pct_per_month": 3.0,
    }, ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SKU.value)

    models, meta = validate_paginated(
        api.list_battery_models(ADMIN, params={"limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 1, f"The collision created nothing, got {meta['total_count']}"


def test_discontinued_model_is_reachable_through_its_successor(api):
    """PRD §3.1: "Retiring a model — an administrator-only action that flips its
    `status` to `DISCONTINUED` — takes a `replacement_model_id` in the body
    naming the successor model, and writes that pointer onto the retired row."
    PRD §3.1: "The pointer is self-referential: it names another catalog model,
    and the catalog listing accepts `replacement_model_id` as a filter so
    callers can walk the supersession edge in reverse and find every model
    pointing at a given successor."

    Design: Corner/entities/discontinued_model_is_reachable_through_replacement_model_id_filter
    """
    old = create_battery_model("IB-31-FLD")
    new = create_battery_model("IB-31-FLD", sku="IB-31-FLD2", amp_hour_capacity=105,
                               peukert_exponent=1.24, unit_weight_kg=26.5,
                               lead_content_kg=12.8, list_price_cents=19500)
    retired = validate_success(
        api.discontinue_battery_model(old["id"], {"replacement_model_id": new["id"]}, ADMIN)
    )
    assert retired["status"] == "DISCONTINUED"
    assert retired["replacement_model_id"] == new["id"]

    rows, meta = validate_paginated(api.list_battery_models(
        TEST_USERS["sales_rep_headers"],
        params={"replacement_model_id": new["id"], "limit": 10, "offset": 0},
    ))
    assert meta["total_count"] == 1, f"Expected exactly the predecessor, got {meta['total_count']}"
    assert rows[0]["id"] == old["id"]
    assert validate_success(api.get_battery_model(new["id"], ADMIN))["status"] == "ACTIVE"


def test_new_lot_derives_its_charge_and_posture_from_the_logical_clock(api):
    """PRD §3.2: "The number of whole storage months elapsed is the number of
    whole days from that baseline date to the logical clock's current date,
    divided by 30 and rounded down to a whole number."
    PRD §3.2: "Fourth: if its state of charge is below 75.0 percent, the lot is
    `REFRESH_REQUIRED`. Otherwise the lot is `SELLABLE`."
    PRD §3.2: "The lot's `quantity_reserved` opens at 0 and its posture is
    derived immediately against the logical clock."
    PRD §3.2: "Alongside `condition_state`, every read re-derives
    `quantity_available`, which is the units on hand less the units reserved,
    reduced further by the storm carve-out described in Section 3.4 when the
    caller's purpose is ordinary non-storm allocation."

    Design: Corner/entities/new_inventory_lot_starts_sellable_with_derived_charge
    """
    warehouse = create_warehouse(code="TX-DAL", state_code="TX", hazmat_endorsement=True,
                                 storm_reserve_pct=0.0, dock_capacity_kg_per_window=100000.0)
    model = create_battery_model("IB-31-FLD")

    resp = api.create_inventory_lot({
        "battery_model_id": model["id"], "warehouse_id": warehouse["id"],
        "manufactured_on": "2026-06-01", "quantity_on_hand": 40,
    }, OPERATOR)
    lot = validate_success(resp, 201)

    assert lot["state_of_charge_pct"] == pytest.approx(88.0, abs=1e-9), \
        f"Two storage months at 6.0 points each, got {lot['state_of_charge_pct']}"
    assert lot["condition_state"] == "SELLABLE"
    assert lot["quantity_available"] == 40
    assert lot["quantity_reserved"] == 0


def test_agm_at_exactly_thirty_kilograms_is_the_excepted_class():
    """PRD §3.1: "an AGM or gel model is `UN2800_EXCEPTED` when its unit weight
    is at most 30.0 kilograms and `UN2800` when it is heavier, so a unit
    weighing exactly 30.0 kilograms is excepted"
    PRD §3.1: "The third derived field, `hazmat_severity_rank`, is the ordinal
    of that class on a fixed severity scale where `NON_REGULATED` ranks 0,
    `UN2800_EXCEPTED` ranks 1, `UN2795` ranks 2, `UN2800` ranks 3, `UN2794`
    ranks 4, `UN3480_SECTION_II` ranks 5 and `UN3480_SECTION_IA` ranks 6."

    Design: Corner/calculations/agm_at_exactly_thirty_kilograms_is_non_spillable_excepted
    """
    on_boundary = create_battery_model(
        "IB-AGM-95", sku="IB-AGM-30", amp_hour_capacity=100, unit_weight_kg=30.0,
        lead_content_kg=14.0, list_price_cents=27000)
    assert on_boundary["hazmat_class_code"] == "UN2800_EXCEPTED"
    assert on_boundary["hazmat_severity_rank"] == 1

    over_boundary = create_battery_model(
        "IB-AGM-95", sku="IB-AGM-31", amp_hour_capacity=100, unit_weight_kg=30.1,
        lead_content_kg=14.1, list_price_cents=27500)
    assert over_boundary["hazmat_class_code"] == "UN2800", \
        f"30.1 kg is heavier than the excepted ceiling, got {over_boundary['hazmat_class_code']}"
    assert over_boundary["hazmat_severity_rank"] == 3


def test_lithium_at_exactly_one_hundred_watt_hours_is_section_two():
    """PRD §3.1: "a lithium-iron-phosphate model is `NON_REGULATED` when its
    watt-hour rating is at most 20.0 watt-hours, `UN3480_SECTION_II` when the
    rating is greater than 20.0 but at most 100.0 watt-hours, so a cell rated at
    exactly 100.0 watt-hours is Section II, and `UN3480_SECTION_IA` above that"
    PRD §3.1: "The `watt_hour_rating` is the nominal voltage multiplied by the
    amp-hour capacity, rounded half up to two decimal places."

    Design: Corner/calculations/lithium_at_exactly_one_hundred_watt_hours_is_section_two
    """
    on_boundary = create_battery_model(
        "IB-LFP-100", sku="IB-LFP-100WH", nominal_voltage=10, amp_hour_capacity=10,
        unit_weight_kg=2.0, list_price_cents=21000)
    assert on_boundary["watt_hour_rating"] == pytest.approx(100.0, abs=0.005)
    assert on_boundary["hazmat_class_code"] == "UN3480_SECTION_II"
    assert on_boundary["hazmat_severity_rank"] == 5

    over_boundary = create_battery_model(
        "IB-LFP-100", sku="IB-LFP-101WH", nominal_voltage=10, amp_hour_capacity=10.1,
        unit_weight_kg=2.1, list_price_cents=21500)
    assert over_boundary["watt_hour_rating"] == pytest.approx(101.0, abs=0.005)
    assert over_boundary["hazmat_class_code"] == "UN3480_SECTION_IA"
    assert over_boundary["hazmat_severity_rank"] == 6


def test_a_fourth_refresh_charge_is_refused(api):
    """PRD §3.2: "A lot that has already absorbed 3 refresh charges is refused
    with `ERR_REFRESH_CYCLES_EXHAUSTED` (HTTP 409), and once that ceiling is
    reached a lot whose charge subsequently falls below 75.0 percent goes
    straight to `SHELF_EXPIRED` rather than back to `REFRESH_REQUIRED`."
    PRD §3.2: "It sets `last_refresh_charged_at` to the current logical clock
    instant, increments `refresh_charge_count` by 1, and resets the storage
    baseline so that `state_of_charge_pct` re-derives to exactly 100.0 and the
    lot lands on `SELLABLE`."

    Design: Corner/validations/fourth_refresh_charge_returns_cycles_exhausted
    """
    warehouse = create_warehouse(code="TX-DAL", state_code="TX", hazmat_endorsement=True,
                                 storm_reserve_pct=0.0, dock_capacity_kg_per_window=100000.0)
    model = create_battery_model("IB-SLF-5")
    lot = receive_lot(model["id"], warehouse["id"], manufactured_on="2026-03-01",
                      quantity_on_hand=20)

    refresh_charge(lot["id"], 12.75)
    set_clock("2026-08-04T00:00:01Z")
    refresh_charge(lot["id"], 12.76)
    set_clock("2026-08-07T00:00:02Z")
    third = refresh_charge(lot["id"], 12.77)
    assert third["refresh_charge_count"] == 3
    assert third["condition_state"] == "SELLABLE"

    set_clock("2026-08-10T00:00:03Z")
    resp = api.refresh_charge_lot(lot["id"], {"measured_open_circuit_voltage": 12.78},
                                  OPERATOR)
    error = validate_error(resp, ApiErrorId.ERR_REFRESH_CYCLES_EXHAUSTED.value)
    assert error["error_id"] != ApiErrorId.ERR_REFRESH_COOLDOWN_ACTIVE.value, \
        "The cooldown has fully elapsed"

    stored = read_lot(lot["id"])
    assert stored["refresh_charge_count"] == 3
    assert str(stored["last_refresh_charged_at"]).startswith("2026-08-07T00:00:02")


def test_lithium_at_exactly_twenty_watt_hours_is_non_regulated():
    """PRD §3.1: "a lithium-iron-phosphate model is `NON_REGULATED` when its
    watt-hour rating is at most 20.0 watt-hours, `UN3480_SECTION_II` when the
    rating is greater than 20.0 but at most 100.0 watt-hours, so a cell rated at
    exactly 100.0 watt-hours is Section II, and `UN3480_SECTION_IA` above that"
    PRD §3.1: "`NON_REGULATED` is reachable only through the lithium branch;
    every other chemistry always lands on one of the six regulated codes."

    Design: Corner/calculations/tiny_lithium_cell_at_exactly_twenty_watt_hours_is_non_regulated
    """
    on_boundary = create_battery_model(
        "IB-LFP-100", sku="IB-LFP-20WH", nominal_voltage=10, amp_hour_capacity=2,
        unit_weight_kg=0.4, list_price_cents=6500)
    assert on_boundary["watt_hour_rating"] == pytest.approx(20.0, abs=0.005)
    assert on_boundary["hazmat_class_code"] == "NON_REGULATED"
    assert on_boundary["hazmat_severity_rank"] == 0

    over_boundary = create_battery_model(
        "IB-LFP-100", sku="IB-LFP-21WH", nominal_voltage=10, amp_hour_capacity=2.1,
        unit_weight_kg=0.45, list_price_cents=6800)
    assert over_boundary["watt_hour_rating"] == pytest.approx(21.0, abs=0.005)
    assert over_boundary["hazmat_class_code"] == "UN3480_SECTION_II"
    assert over_boundary["hazmat_severity_rank"] == 5
