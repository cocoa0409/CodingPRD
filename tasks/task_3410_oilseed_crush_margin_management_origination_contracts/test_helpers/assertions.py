"""Entity assertions and domain invariant checkers.

Each assert_<entity>(data) checks the PRD-declared field set and types. Fields
the PRD declares null until a later lifecycle point (ticket grading fields
before apply, settlement figures before settle, realized margins before
complete/offset) are asserted present-or-null, and type-checked when non-null.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    BoardPositionStatus,
    BuyerStatus,
    CertStandard,
    Commodity,
    ContractType,
    CrushRunStatus,
    ElectionOrigin,
    FulfillmentStatus,
    LaneMode,
    PositionStatus,
    PricingStatus,
    Product,
    ProgramStatus,
    SalesContractStatus,
    ScheduleStatus,
    ShipmentStatus,
    TicketStatus,
    PlantStatus,
    CarryDecision,
)


# =============================================================================
# Shared field helpers
# =============================================================================

def assert_identity_block(data: dict):
    """Full identity block (PRD §2.4): id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an int >= 1, got {data.get('version')!r}"
    )


def assert_append_only_identity(data: dict):
    """Append-only identity (PRD §2.4): id + created_at, and updated_at /
    version must be absent."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only resource must not carry updated_at"
    assert "version" not in data, "append-only resource must not carry version"


def assert_money_cents(value, field="value"):
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be integer cents, got {value!r}"
    )


def assert_bushel_quantity(value, field="value"):
    """Bushels carry three decimal places (PRD §2.7); accept int or float whose
    value is exact at 3 decimals."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be numeric bushels, got {value!r}"
    )
    rounded = round(float(value), 3)
    assert abs(float(value) - rounded) < 1e-9, (
        f"{field} must carry at most 3 decimals, got {value!r}"
    )


def assert_spread_value(value, field="spread_cents_per_bushel"):
    """Crush spreads carry two decimal places (PRD §2.7)."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be numeric, got {value!r}"
    )
    rounded = round(float(value), 2)
    assert abs(float(value) - rounded) < 1e-9, (
        f"{field} must carry at most 2 decimals, got {value!r}"
    )


def _assert_optional_str(data, field):
    assert field in data, f"{field} missing"
    assert data[field] is None or isinstance(data[field], str), (
        f"{field} must be null or a string, got {data[field]!r}"
    )


def _assert_optional_int(data, field):
    assert field in data, f"{field} missing"
    if data[field] is not None:
        assert_money_cents(data[field], field)


def _assert_optional_number(data, field):
    assert field in data, f"{field} missing"
    if data[field] is not None:
        assert isinstance(data[field], (int, float)) and not isinstance(data[field], bool), (
            f"{field} must be null or numeric, got {data[field]!r}"
        )


def _assert_optional_timestamp(data, field):
    assert field in data, f"{field} missing"
    if data[field] is not None:
        assert is_iso8601_timestamp(data[field]), f"{field} must be ISO 8601, got {data[field]!r}"


# =============================================================================
# Per-entity assertions
# =============================================================================

def assert_farmer(data: dict):
    assert_identity_block(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["county"], str) and data["county"]


def assert_elevator(data: dict):
    assert_identity_block(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region"], str) and data["region"]
    assert_bushel_quantity(data["storage_capacity_bushels"], "storage_capacity_bushels")
    assert data["storage_capacity_bushels"] > 0
    assert is_valid_uuid(data.get("active_discount_schedule_id", "")), (
        "active_discount_schedule_id must be a UUID"
    )
    assert_bushel_quantity(data["stored_bushels"], "stored_bushels")
    assert_bushel_quantity(data["certified_stored_bushels"], "certified_stored_bushels")
    assert isinstance(data["receiving_open"], bool), "receiving_open must be boolean"
    assert_elevator_counters(data)


def assert_elevator_counters(data: dict):
    """Derived-counter invariants (PRD §2.10): the gate is false exactly when
    stored_bushels has reached storage_capacity_bushels."""
    assert data["certified_stored_bushels"] <= data["stored_bushels"], (
        "certified_stored_bushels is a subset of stored_bushels"
    )
    expected_open = data["stored_bushels"] < data["storage_capacity_bushels"]
    assert data["receiving_open"] == expected_open, (
        f"receiving_open {data['receiving_open']} inconsistent with stored "
        f"{data['stored_bushels']} vs capacity {data['storage_capacity_bushels']}"
    )


def assert_quality_discount_schedule(data: dict):
    assert_identity_block(data)
    assert isinstance(data["name"], str) and data["name"]
    for f in ("moisture_base_pct", "moisture_shrink_pct_per_point", "damage_free_pct",
              "fm_free_pct", "reject_moisture_pct"):
        assert isinstance(data[f], (int, float)), f"{f} must be numeric"
    for f in ("moisture_discount_cents_per_point", "damage_discount_cents_per_point",
              "fm_discount_cents_per_point"):
        assert_money_cents(data[f], f)
    assert data["status"] in [s.value for s in ScheduleStatus]


def assert_sustainability_program(data: dict):
    assert_identity_block(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["cert_standard"] in [s.value for s in CertStandard]
    assert_money_cents(data["premium_cents_per_bushel"], "premium_cents_per_bushel")
    assert data["premium_cents_per_bushel"] >= 0
    assert data["status"] in [s.value for s in ProgramStatus]


def assert_market_quote(data: dict):
    assert_append_only_identity(data)
    assert data["commodity"] in [c.value for c in Commodity]
    assert isinstance(data["quote_month"], str) and len(data["quote_month"]) == 7
    assert_money_cents(data["price_cents"], "price_cents")
    assert is_iso8601_timestamp(data["quote_date"]), "quote_date must be ISO 8601"


def assert_crush_plant(data: dict):
    assert_identity_block(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["daily_crush_capacity_bushels"], int)
    assert data["daily_crush_capacity_bushels"] > 0
    assert isinstance(data["daily_refinery_capacity_lbs"], int)
    assert data["daily_refinery_capacity_lbs"] > 0
    assert 0 <= data["biodiesel_feedstock_share_pct"] <= 100
    assert_bushel_quantity(data["bean_inventory_bushels"], "bean_inventory_bushels")
    assert data["status"] in [s.value for s in PlantStatus]


def assert_buyer(data: dict):
    assert_identity_block(data)
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert data["status"] in [s.value for s in BuyerStatus]
    assert isinstance(data["open_claims_count"], int) and data["open_claims_count"] >= 0
    if data["open_claims_count"] >= 3:
        # PRD §3.9: the buyer suspends the moment the count reaches three.
        assert data["status"] == BuyerStatus.SUSPENDED.value, (
            "a buyer at three open claims must be SUSPENDED"
        )


def assert_pricing_election(entry: dict):
    assert_bushel_quantity(entry["bushels"], "election.bushels")
    assert entry["bushels"] > 0
    assert_money_cents(entry["unit_price_cents"], "election.unit_price_cents")
    assert is_iso8601_timestamp(entry["elected_at"]), "election.elected_at must be ISO 8601"
    assert entry["origin"] in [o.value for o in ElectionOrigin]


def assert_origination_contract(data: dict):
    assert_identity_block(data)
    assert is_valid_uuid(data.get("farmer_id", "")), "farmer_id must be a UUID"
    assert is_valid_uuid(data.get("elevator_id", "")), "elevator_id must be a UUID"
    _assert_optional_str(data, "program_id")
    if data.get("program_id") is not None:
        assert is_valid_uuid(data["program_id"]), "program_id must be a UUID"
    assert data["contract_type"] in [c.value for c in ContractType]
    assert_bushel_quantity(data["quantity_bushels"], "quantity_bushels")
    assert data["quantity_bushels"] > 0
    # Type-matched price fields (PRD §3.2).
    if data["contract_type"] == ContractType.CASH.value:
        assert_money_cents(data["cash_price_cents_per_bushel"], "cash_price_cents_per_bushel")
    else:
        assert isinstance(data.get("futures_month"), str) and len(data["futures_month"]) == 7
    # Server-maintained pools.
    assert_bushel_quantity(data["delivered_bushels"], "delivered_bushels")
    assert_bushel_quantity(data["priced_bushels"], "priced_bushels")
    assert_money_cents(data["priced_value_cents"], "priced_value_cents")
    assert isinstance(data["elections"], list)
    for entry in data["elections"]:
        assert_pricing_election(entry)
    assert_money_cents(data["accrued_storage_cents"], "accrued_storage_cents")
    assert_bushel_quantity(data["unpriced_pool_bushels"], "unpriced_pool_bushels")
    _assert_optional_timestamp(data, "last_accrual_date")
    _assert_optional_int(data, "estimated_settlement_cents")
    _assert_optional_int(data, "settlement_line_total_cents")
    _assert_optional_int(data, "settlement_accrual_deduction_cents")
    _assert_optional_int(data, "settlement_net_payable_cents")
    assert data["pricing_status"] in [s.value for s in PricingStatus]
    assert data["fulfillment_status"] in [s.value for s in FulfillmentStatus]
    assert_contract_pool_invariants(data)


def assert_contract_pool_invariants(data: dict):
    """PRD §3.2: a contract is PRICED exactly when priced_bushels equals
    quantity_bushels; PARTIALLY_PRICED whenever some but not all is priced."""
    if data["pricing_status"] == PricingStatus.PRICED.value:
        assert data["priced_bushels"] == data["quantity_bushels"], (
            "PRICED requires priced_bushels == quantity_bushels"
        )
    elif data["pricing_status"] == PricingStatus.PARTIALLY_PRICED.value:
        assert 0 < data["priced_bushels"] < data["quantity_bushels"], (
            "PARTIALLY_PRICED requires 0 < priced_bushels < quantity_bushels"
        )
    elif data["pricing_status"] == PricingStatus.UNPRICED.value:
        assert data["priced_bushels"] == 0, "UNPRICED requires priced_bushels == 0"
    if data["fulfillment_status"] == "SETTLED":
        # PRD §3.4: settlement consumes both pools exactly and defines the
        # three settlement figures.
        assert data["settlement_line_total_cents"] is not None
        assert data["settlement_accrual_deduction_cents"] is not None
        assert data["settlement_net_payable_cents"] is not None
        assert (
            data["settlement_line_total_cents"]
            - data["settlement_accrual_deduction_cents"]
            == data["settlement_net_payable_cents"]
        ), "net payable must equal line total minus accrual deduction"


def assert_delivery_ticket(data: dict):
    assert_identity_block(data)
    assert is_valid_uuid(data.get("contract_id", "")), "contract_id must be a UUID"
    assert is_valid_uuid(data.get("elevator_id", "")), "elevator_id must be a UUID"
    _assert_optional_str(data, "program_id")
    assert_bushel_quantity(data["gross_bushels"], "gross_bushels")
    assert data["gross_bushels"] > 0
    for f in ("moisture_pct", "damage_pct", "foreign_material_pct"):
        assert isinstance(data[f], (int, float)) and data[f] >= 0, f"{f} must be >= 0"
    assert data["status"] in [s.value for s in TicketStatus]
    if data["status"] == TicketStatus.RECEIVED.value:
        # PRD §3.3: until the apply, all computed fields are null.
        for f in ("schedule_id", "shrink_bushels", "net_bushels",
                  "discount_cents_per_bushel", "premium_cents_per_bushel", "applied_date"):
            assert data.get(f) is None, f"RECEIVED ticket must have null {f}"
    else:
        # Both apply branches pin the schedule and compute the grading fields
        # (PRD §3.3: on the rejected branch "the grading fields are still
        # computed for the record").
        assert is_valid_uuid(data.get("schedule_id", "")), "applied ticket pins schedule_id"
        assert_bushel_quantity(data["shrink_bushels"], "shrink_bushels")
        assert_bushel_quantity(data["net_bushels"], "net_bushels")
        assert_money_cents(data["discount_cents_per_bushel"], "discount_cents_per_bushel")
        assert_money_cents(data["premium_cents_per_bushel"], "premium_cents_per_bushel")
        assert abs(data["gross_bushels"] - data["shrink_bushels"]
                   - data["net_bushels"]) < 0.0015, (
            "net_bushels must equal gross minus shrink at 3-decimal precision"
        )
        if data["status"] == TicketStatus.APPLIED.value:
            # PRD §3.3 stamps applied_date on the applied branch; the rejected
            # branch's applied_date is unspecified, so it is not asserted.
            assert is_iso8601_timestamp(data["applied_date"]), (
                "applied_date must be ISO 8601 on an APPLIED ticket"
            )


def assert_storage_position(data: dict):
    assert_identity_block(data)
    assert is_valid_uuid(data.get("elevator_id", "")), "elevator_id must be a UUID"
    assert is_valid_uuid(data.get("source_ticket_id", "")), "source_ticket_id must be a UUID"
    _assert_optional_str(data, "program_id")
    assert_bushel_quantity(data["bushels_initial"], "bushels_initial")
    assert_bushel_quantity(data["current_bushels"], "current_bushels")
    assert 0 <= data["current_bushels"] <= data["bushels_initial"]
    assert data["status"] in [s.value for s in PositionStatus]
    # PRD §3.5: DEPLETED iff current_bushels == 0.
    expected = PositionStatus.DEPLETED.value if data["current_bushels"] == 0 else PositionStatus.OPEN.value
    assert data["status"] == expected, (
        f"position status {data['status']} inconsistent with current_bushels {data['current_bushels']}"
    )


def assert_freight_lane(data: dict):
    assert_identity_block(data)
    assert is_valid_uuid(data.get("origin_elevator_id", "")), "origin_elevator_id must be a UUID"
    assert is_valid_uuid(data.get("destination_plant_id", "")), "destination_plant_id must be a UUID"
    assert data["mode"] in [m.value for m in LaneMode]
    assert_money_cents(data["freight_cents_per_bushel"], "freight_cents_per_bushel")
    assert data["freight_cents_per_bushel"] >= 0
    assert isinstance(data["transit_days"], int) and data["transit_days"] >= 0
    assert isinstance(data["daily_capacity_bushels"], int) and data["daily_capacity_bushels"] > 0


def assert_shipment(data: dict):
    assert_identity_block(data)
    assert is_valid_uuid(data.get("lane_id", "")), "lane_id must be a UUID"
    assert_bushel_quantity(data["bushels"], "bushels")
    assert data["bushels"] > 0
    assert is_iso8601_timestamp(data["departure_date"]), "departure_date must be ISO 8601"
    _assert_optional_str(data, "certified_program_id")
    assert is_iso8601_timestamp(data["arrival_date"]), "arrival_date must be ISO 8601"
    assert_money_cents(data["freight_cost_cents"], "freight_cost_cents")
    assert isinstance(data["draws"], list)
    for draw in data["draws"]:
        assert is_valid_uuid(draw.get("position_id", "")), "draw.position_id must be a UUID"
        assert_bushel_quantity(draw["bushels"], "draw.bushels")
        assert draw["bushels"] > 0
    assert data["status"] in [s.value for s in ShipmentStatus]
    drawn_total = sum(d["bushels"] for d in data["draws"])
    assert abs(drawn_total - data["bushels"]) < 0.0015, (
        "draws must cover exactly the shipped bushels"
    )


def assert_crush_run(data: dict):
    assert_identity_block(data)
    assert is_valid_uuid(data.get("plant_id", "")), "plant_id must be a UUID"
    assert is_iso8601_timestamp(data["run_date"]), "run_date must be ISO 8601"
    assert isinstance(data["planned_bushels"], int) and data["planned_bushels"] > 0
    assert isinstance(data["futures_month"], str) and len(data["futures_month"]) == 7
    assert_crush_run_economics(data)


def assert_crush_run_economics(data: dict):
    """PRD §3.6: yields come off the standard crush; margin is spread x bushels
    rounded half up; realized is null until COMPLETE."""
    from .constants import MEAL_YIELD_LBS_PER_BUSHEL, OIL_YIELD_LBS_PER_BUSHEL

    assert data["expected_oil_lbs"] == data["planned_bushels"] * OIL_YIELD_LBS_PER_BUSHEL
    assert data["expected_meal_lbs"] == data["planned_bushels"] * MEAL_YIELD_LBS_PER_BUSHEL
    assert_spread_value(data["spread_cents_per_bushel"])
    assert_money_cents(data["planned_margin_cents"], "planned_margin_cents")
    assert data["status"] in [s.value for s in CrushRunStatus]
    if data["status"] == CrushRunStatus.COMPLETE.value:
        assert_money_cents(data["realized_margin_cents"], "realized_margin_cents")
    else:
        assert data.get("realized_margin_cents") is None, (
            "realized_margin_cents is null until COMPLETE"
        )


def assert_board_crush_position(data: dict):
    assert_identity_block(data)
    assert isinstance(data["futures_month"], str) and len(data["futures_month"]) == 7
    assert isinstance(data["bean_lots_long"], int) and data["bean_lots_long"] >= 1
    assert isinstance(data["oil_lots_short"], int) and data["oil_lots_short"] >= 0
    assert isinstance(data["meal_lots_short"], int) and data["meal_lots_short"] >= 0
    assert is_iso8601_timestamp(data["expiry_date"]), "expiry_date must be ISO 8601"
    assert_spread_value(data["locked_spread_cents_per_bushel"])
    assert_money_cents(data["locked_margin_cents"], "locked_margin_cents")
    assert isinstance(data["entered_by_user_id"], str) and data["entered_by_user_id"]
    assert data["status"] in [s.value for s in BoardPositionStatus]
    if data["status"] == BoardPositionStatus.ENTERED.value:
        assert data.get("realized_pnl_cents") is None
    if data["status"] == BoardPositionStatus.OFFSET.value:
        assert_money_cents(data["realized_pnl_cents"], "realized_pnl_cents")
    if data["status"] in (BoardPositionStatus.CONFIRMED.value, BoardPositionStatus.OFFSET.value):
        assert isinstance(data["confirmed_by_user_id"], str) and data["confirmed_by_user_id"]
        # PRD §3.7 segregation of duties.
        assert data["confirmed_by_user_id"] != data["entered_by_user_id"], (
            "confirmer must differ from the entering trader"
        )


def assert_sales_delivery_entry(entry: dict):
    assert is_iso8601_timestamp(entry["delivery_date"]), "delivery_date must be ISO 8601"
    assert isinstance(entry["quantity_lbs"], int) and entry["quantity_lbs"] > 0
    assert is_iso8601_timestamp(entry["recorded_at"]), "recorded_at must be ISO 8601"


def assert_product_sales_contract(data: dict):
    assert_identity_block(data)
    assert is_valid_uuid(data.get("buyer_id", "")), "buyer_id must be a UUID"
    assert is_valid_uuid(data.get("plant_id", "")), "plant_id must be a UUID"
    assert data["product"] in [p.value for p in Product]
    assert isinstance(data["quantity_lbs"], int) and data["quantity_lbs"] > 0
    assert_money_cents(data["price_cents_per_lb"], "price_cents_per_lb")
    assert data["price_cents_per_lb"] > 0
    assert is_iso8601_timestamp(data["delivery_window_start"])
    assert is_iso8601_timestamp(data["delivery_window_end"])
    assert data["delivery_window_end"] > data["delivery_window_start"]
    if data["product"] == Product.SOY_MEAL.value:
        _assert_optional_number(data, "min_protein_pct")
    else:
        _assert_optional_number(data, "max_ffa_pct")
    assert isinstance(data["delivered_lbs"], int) and 0 <= data["delivered_lbs"] <= data["quantity_lbs"]
    assert isinstance(data["deliveries"], list)
    for entry in data["deliveries"]:
        assert_sales_delivery_entry(entry)
    assert data["status"] in [s.value for s in SalesContractStatus]
    if data["status"] == SalesContractStatus.FULFILLED.value:
        assert data["delivered_lbs"] == data["quantity_lbs"]
        assert data.get("claim_cents") is None
    if data["status"] == SalesContractStatus.DEFAULTED.value:
        assert_money_cents(data["claim_cents"], "claim_cents")
        assert data["delivered_lbs"] < data["quantity_lbs"]
    else:
        assert data.get("claim_cents") is None, "claim_cents is null until default"


def assert_carry_assessment(data: dict):
    assert_money_cents(data["nearby_price_cents"], "nearby_price_cents")
    assert_money_cents(data["deferred_price_cents"], "deferred_price_cents")
    assert_money_cents(data["storage_cost_cents_per_bushel"], "storage_cost_cents_per_bushel")
    assert_money_cents(data["signal_cents_per_bushel"], "signal_cents_per_bushel")
    assert data["decision"] in [d.value for d in CarryDecision]
    # PRD §3.3: signal = deferred - nearby - storage cost; CARRY iff strictly > 0.
    assert data["signal_cents_per_bushel"] == (
        data["deferred_price_cents"] - data["nearby_price_cents"] - data["storage_cost_cents_per_bushel"]
    ), "signal must equal deferred minus nearby minus storage cost"
    expected = CarryDecision.CARRY.value if data["signal_cents_per_bushel"] > 0 else CarryDecision.FLAT.value
    assert data["decision"] == expected, (
        f"decision {data['decision']} inconsistent with signal {data['signal_cents_per_bushel']}"
    )


__all__ = [
    "assert_identity_block",
    "assert_append_only_identity",
    "assert_money_cents",
    "assert_bushel_quantity",
    "assert_spread_value",
    "assert_farmer",
    "assert_elevator",
    "assert_elevator_counters",
    "assert_quality_discount_schedule",
    "assert_sustainability_program",
    "assert_market_quote",
    "assert_crush_plant",
    "assert_buyer",
    "assert_pricing_election",
    "assert_origination_contract",
    "assert_contract_pool_invariants",
    "assert_delivery_ticket",
    "assert_storage_position",
    "assert_freight_lane",
    "assert_shipment",
    "assert_crush_run",
    "assert_crush_run_economics",
    "assert_board_crush_position",
    "assert_sales_delivery_entry",
    "assert_product_sales_contract",
    "assert_carry_assessment",
]
