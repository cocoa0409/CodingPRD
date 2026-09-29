"""Entity serialisers. Computed fields are derived at read time."""
import calc
import derive
from store import db
from util import D, iso, rhu


def _common(row, out):
    out["created_at"] = iso(row["created_at"])
    if "updated_at" in row:
        out["updated_at"] = iso(row["updated_at"])
        out["version"] = row["version"]
    return out


def plant_out(plant):
    _credited, total, score, lcfs = derive.ci_state()
    generated, separated, retired = derive.rin_counts()
    out = {
        "id": plant["id"],
        "name": plant["name"],
        "nameplate_capacity_gallons": plant["nameplate_capacity_gallons"],
        "base_grind_cap_bushels": plant["base_grind_cap_bushels"],
        "coverage_floor_bushels": plant["coverage_floor_bushels"],
        "baseline_ci_g_per_mj": plant["baseline_ci_g_per_mj"],
        "rin_generation_enabled": plant["rin_generation_enabled"],
        "mark_corn_cents_per_bushel": plant["mark_corn_cents_per_bushel"],
        "mark_ethanol_cents_per_gallon": plant["mark_ethanol_cents_per_gallon"],
        "mark_natgas_cents_per_mmbtu": plant["mark_natgas_cents_per_mmbtu"],
        "mark_soybean_meal_usd_per_ton": plant["mark_soybean_meal_usd_per_ton"],
        "mark_sbo_cents_per_lb": plant["mark_sbo_cents_per_lb"],
        "marks_effective_month": plant["marks_effective_month"],
        "marks_updated_at": iso(plant["marks_updated_at"]),
        "corn_inventory_bushels": derive.plant_corn_inventory(),
        "ddgs_inventory_tons": derive.plant_ddgs_inventory(),
        "corn_oil_inventory_lbs": derive.plant_corn_oil_inventory(),
        "open_contract_coverage_bushels": derive.open_contract_coverage(),
        "procurement_posture": derive.procurement_posture(),
        "compliance_posture": derive.compliance_posture(),
        "daily_grind_cap_bushels": derive.daily_grind_cap(),
        "rolling_yield_gal_per_bushel": derive.rolling_yield(),
        "ci_score_g_per_mj": score,
        "lcfs_credit_tonnes_per_million_gal": lcfs,
        "rin_generated_count": generated,
        "rin_separated_count": separated,
        "rin_retired_count": retired,
    }
    return _common(plant, out)


def contract_out(contract):
    out = {
        "id": contract["id"],
        "supplier_name": contract["supplier_name"],
        "delivery_month": contract["delivery_month"],
        "bushels_contracted": contract["bushels_contracted"],
        "basis_cents_per_bushel": contract["basis_cents_per_bushel"],
        "futures_price_cents_per_bushel": contract["futures_price_cents_per_bushel"],
        "pricing_status": contract["pricing_status"],
        "priced_at": iso(contract["priced_at"]),
        "status": contract["status"],
        "bushels_delivered": derive.contract_bushels_delivered(contract["id"]),
        "rolled_from_contract_id": contract["rolled_from_contract_id"],
        "roll_basis_adjustment_cents": contract["roll_basis_adjustment_cents"],
    }
    return _common(contract, out)


def delivery_out(delivery):
    out = {
        "id": delivery["id"],
        "contract_id": delivery["contract_id"],
        "ticket_number": delivery["ticket_number"],
        "gross_weight_lbs": delivery["gross_weight_lbs"],
        "tare_weight_lbs": delivery["tare_weight_lbs"],
        "moisture_pct": delivery["moisture_pct"],
        "test_weight_lb_per_bu": delivery["test_weight_lb_per_bu"],
        "foreign_material_pct": delivery["foreign_material_pct"],
        "damaged_kernels_pct": delivery["damaged_kernels_pct"],
        "aflatoxin_ppb": delivery["aflatoxin_ppb"],
        "grading_status": delivery["grading_status"],
        "rejection_reason": delivery["rejection_reason"],
        "gross_wet_bushels": delivery["gross_wet_bushels"],
        "net_dry_bushels": delivery["net_dry_bushels"],
        "moisture_discount_cents": delivery["moisture_discount_cents"],
        "test_weight_discount_cents": delivery["test_weight_discount_cents"],
        "foreign_material_discount_cents": delivery["foreign_material_discount_cents"],
        "damage_discount_cents": delivery["damage_discount_cents"],
        "discount_cents_per_bushel": delivery["discount_cents_per_bushel"],
        "net_price_cents_per_bushel": delivery["net_price_cents_per_bushel"],
        "settlement_amount_cents": delivery["settlement_amount_cents"],
        "graded_by_user_id": delivery["graded_by_user_id"],
        "settled_by_user_id": delivery["settled_by_user_id"],
        "settled_at": iso(delivery["settled_at"]),
    }
    return _common(delivery, out)


def batch_out(batch):
    out = {
        "id": batch["id"],
        "batch_code": batch["batch_code"],
        "corn_bushels_charged": batch["corn_bushels_charged"],
        "charge_test_weight_lb_per_bu": batch["charge_test_weight_lb_per_bu"],
        "destination_tank_id": batch["destination_tank_id"],
        "charged_at": iso(batch["charged_at"]),
        "status": batch["status"],
        "intervention_count": batch["intervention_count"],
        "fermentation_health_index": batch["fermentation_health_index"],
        "starch_bonus_gal_per_bushel": batch["starch_bonus_gal_per_bushel"],
        "health_penalty_gal_per_bushel": batch["health_penalty_gal_per_bushel"],
        "intervention_penalty_gal_per_bushel": batch["intervention_penalty_gal_per_bushel"],
        "effective_yield_gal_per_bushel": batch["effective_yield_gal_per_bushel"],
        "ethanol_gallons_produced": batch["ethanol_gallons_produced"],
        "ddgs_tons_produced": batch["ddgs_tons_produced"],
        "corn_oil_lbs_produced": batch["corn_oil_lbs_produced"],
        "distillation_started_at": iso(batch["distillation_started_at"]),
        "completed_at": iso(batch["completed_at"]),
        "dumped_at": iso(batch["dumped_at"]),
        "dump_reason": batch["dump_reason"],
    }
    return _common(batch, out)


def health_reading_out(reading):
    return {
        "id": reading["id"],
        "created_at": iso(reading["created_at"]),
        "batch_id": reading["batch_id"],
        "hours_elapsed": reading["hours_elapsed"],
        "lactic_acid_ppm": reading["lactic_acid_ppm"],
        "acetic_acid_ppm": reading["acetic_acid_ppm"],
        "temperature_c": reading["temperature_c"],
        "reading_score": reading["reading_score"],
    }


def tank_out(tank):
    out = {
        "id": tank["id"],
        "tank_code": tank["tank_code"],
        "product_type": tank["product_type"],
        "capacity_gallons": tank["capacity_gallons"],
        "opening_gallons": tank["opening_gallons"],
        "settling_buffer_minutes": tank["settling_buffer_minutes"],
        "service_status": tank["service_status"],
        "hold_reason": tank["hold_reason"],
        "held_at": iso(tank["held_at"]),
        "current_gallons": derive.tank_current_gallons(tank),
        "available_gallons": derive.tank_available_gallons(tank),
    }
    return _common(tank, out)


def blend_out(blend):
    out = {
        "id": blend["id"],
        "blend_code": blend["blend_code"],
        "neat_source_tank_id": blend["neat_source_tank_id"],
        "denaturant_source_tank_id": blend["denaturant_source_tank_id"],
        "destination_tank_id": blend["destination_tank_id"],
        "expected_destination_tank_version": blend["expected_destination_tank_version"],
        "neat_gallons": blend["neat_gallons"],
        "denaturant_gallons": blend["denaturant_gallons"],
        "window_start": iso(blend["window_start"]),
        "window_end": iso(blend["window_end"]),
        "occupancy_end": iso(blend["occupancy_end"]),
        "status": blend["status"],
        "output_gallons": blend["output_gallons"],
        "denaturant_pct": blend["denaturant_pct"],
        "executed_at": iso(blend["executed_at"]),
        "cancelled_at": iso(blend["cancelled_at"]),
    }
    return _common(blend, out)


def track_out(track):
    out = {
        "id": track["id"],
        "track_code": track["track_code"],
        "spot_capacity": track["spot_capacity"],
        "loading_rate_cars_per_hour": track["loading_rate_cars_per_hour"],
        "is_active": track["is_active"],
        "committed_railcars": derive.track_committed_railcars(track["id"]),
    }
    return _common(track, out)


def shipment_out(shipment):
    out = {
        "id": shipment["id"],
        "shipment_code": shipment["shipment_code"],
        "track_id": shipment["track_id"],
        "expected_track_version": shipment["expected_track_version"],
        "source_tank_id": shipment["source_tank_id"],
        "destination_terminal": shipment["destination_terminal"],
        "railcar_count": shipment["railcar_count"],
        "gallons_per_railcar": shipment["gallons_per_railcar"],
        "window_start": iso(shipment["window_start"]),
        "window_end": iso(shipment["window_end"]),
        "price_cents_per_gallon": shipment["price_cents_per_gallon"],
        "loading_status": shipment["loading_status"],
        "billing_status": shipment["billing_status"],
        "planned_gallons": shipment["planned_gallons"],
        "loaded_gallons": shipment["loaded_gallons"],
        "invoice_amount_cents": shipment["invoice_amount_cents"],
        "bol_number": shipment["bol_number"],
        "bol_issued_at": iso(shipment["bol_issued_at"]),
        "invoiced_at": iso(shipment["invoiced_at"]),
        "loaded_at": iso(shipment["loaded_at"]),
        "cancelled_at": iso(shipment["cancelled_at"]),
    }
    return _common(shipment, out)


def sale_out(sale):
    out = {
        "id": sale["id"],
        "sale_code": sale["sale_code"],
        "buyer_name": sale["buyer_name"],
        "product": sale["product"],
        "pricing_basis": sale["pricing_basis"],
        "quantity": sale["quantity"],
        "quoted_price": sale["quoted_price"],
        "index_pct": sale["index_pct"],
        "freight_rate_per_unit": sale["freight_rate_per_unit"],
        "quote_expires_at": iso(sale["quote_expires_at"]),
        "status": sale["status"],
        "quote_reference_mark": sale["quote_reference_mark"],
        "settlement_price": sale["settlement_price"],
        "collar_floor": sale["collar_floor"],
        "collar_ceiling": sale["collar_ceiling"],
        "subtotal_usd": sale["subtotal_usd"],
        "volume_rebate_usd": sale["volume_rebate_usd"],
        "freight_usd": sale["freight_usd"],
        "invoice_amount_cents": sale["invoice_amount_cents"],
        "responded_at": iso(sale["responded_at"]),
        "shipped_at": iso(sale["shipped_at"]),
    }
    return _common(sale, out)


def rin_out(rin):
    out = {
        "id": rin["id"],
        "fermentation_batch_id": rin["fermentation_batch_id"],
        "rin_year": rin["rin_year"],
        "d_code": rin["d_code"],
        "rin_eligible_gallons": rin["rin_eligible_gallons"],
        "rin_count": rin["rin_count"],
        "status": rin["status"],
        "separated_shipment_id": rin["separated_shipment_id"],
        "separated_at": iso(rin["separated_at"]),
        "retired_at": iso(rin["retired_at"]),
        "retirement_reference": rin["retirement_reference"],
    }
    return _common(rin, out)


def project_out(project):
    out = {
        "id": project["id"],
        "project_code": project["project_code"],
        "project_name": project["project_name"],
        "project_type": project["project_type"],
        "claimed_reduction_g_per_mj": project["claimed_reduction_g_per_mj"],
        "capital_cost_cents": project["capital_cost_cents"],
        "predecessor_project_id": project["predecessor_project_id"],
        "verification_status": project["verification_status"],
        "certification_tier": project["certification_tier"],
        "verification_body": project["verification_body"],
        "verified_reduction_g_per_mj": project["verified_reduction_g_per_mj"],
        "credited_reduction_g_per_mj": project["credited_reduction_g_per_mj"],
        "submitted_at": iso(project["submitted_at"]),
        "reviewed_at": iso(project["reviewed_at"]),
        "certified_at": iso(project["certified_at"]),
        "revision_count": project["revision_count"],
        "review_note": project["review_note"],
    }
    return _common(project, out)


def position_out(position):
    contracts_open = int(position["contracts"]) - int(position["contracts_closed"])
    out = {
        "id": position["id"],
        "position_code": position["position_code"],
        "commodity": position["commodity"],
        "direction": position["direction"],
        "contract_month": position["contract_month"],
        "contracts": position["contracts"],
        "entry_price": position["entry_price"],
        "status": position["status"],
        "contracts_closed": position["contracts_closed"],
        "contracts_open": contracts_open,
        "unit_size": calc.HEDGE_UNIT_SIZE[position["commodity"]],
        "realized_pnl_cents": position["realized_pnl_cents"],
        "unrealized_pnl_cents": position["unrealized_pnl_cents"],
        "opened_at": iso(position["opened_at"]),
        "closed_at": iso(position["closed_at"]),
    }
    return _common(position, out)


def condition_window_readings(condition):
    """Readings inside (now - averaging_period_hours, now]: start exclusive,
    end inclusive."""
    from datetime import timedelta
    now = db.clock
    start = now - timedelta(hours=int(condition["averaging_period_hours"]))
    rows = []
    for reading in db.permit_readings.values():
        if reading["condition_id"] != condition["id"]:
            continue
        measured = reading["measured_at"]
        if start < measured <= now:
            rows.append(reading)
    return rows


def condition_rolling(condition):
    rows = condition_window_readings(condition)
    return calc.rolling_average([r["value"] for r in rows])


def condition_out(condition):
    average, count = condition_rolling(condition)
    out = {
        "id": condition["id"],
        "condition_code": condition["condition_code"],
        "permit_type": condition["permit_type"],
        "parameter_name": condition["parameter_name"],
        "limit_value": condition["limit_value"],
        "unit": condition["unit"],
        "averaging_period_hours": condition["averaging_period_hours"],
        "severity": condition["severity"],
        "status": condition["status"],
        "rolling_average_value": average,
        "readings_in_window": count,
        "exceedance_count": condition["exceedance_count"],
        "last_exceedance_at": iso(condition["last_exceedance_at"]),
        "resolution_note": condition["resolution_note"],
    }
    return _common(condition, out)


def permit_reading_out(reading):
    return {
        "id": reading["id"],
        "created_at": iso(reading["created_at"]),
        "condition_id": reading["condition_id"],
        "measured_at": iso(reading["measured_at"]),
        "value": reading["value"],
        "sample_reference": reading["sample_reference"],
    }


def clock_out():
    return {"current_utc": iso(db.clock)}
