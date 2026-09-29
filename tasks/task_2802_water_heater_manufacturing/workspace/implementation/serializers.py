"""Entity -> JSON projection, including every `source: computed` field."""

from datetime import datetime

import db
from db import fmt_ts
from services import calc

DRAWN_STATUSES = ("ASSEMBLED", "LABELED", "SHIPPED", "HELD")


def _v(value):
    if isinstance(value, datetime):
        return fmt_ts(value)
    return calc.out_num(value)


def _common(row, mutable=True):
    out = {"id": row["id"], "created_at": fmt_ts(row["created_at"])}
    if mutable:
        out["updated_at"] = fmt_ts(row["updated_at"])
        out["version"] = row["version"]
    return out


def _project(row, fields, mutable=True):
    out = {}
    for name in fields:
        out[name] = _v(row.get(name))
    out.update(_common(row, mutable))
    return out


# --------------------------------------------------------------------------
# Supplier
# --------------------------------------------------------------------------

SUPPLIER_FIELDS = (
    "name",
    "component_category",
    "audit_score",
    "defect_ppm",
    "open_capa_count",
    "qualification_score",
    "qualification_status",
    "qualified_until",
    "disqualification_reason_code",
)


def blocked_lot_count(supplier_id):
    return sum(
        1
        for lot in db.db.component_lots.values()
        if lot["supplier_id"] == supplier_id and lot["status"] == "BLOCKED"
    )


def supplier(row):
    out = _project(row, SUPPLIER_FIELDS)
    out["blocked_lot_count"] = blocked_lot_count(row["id"])
    return out


# --------------------------------------------------------------------------
# ComponentLot
# --------------------------------------------------------------------------

COMPONENT_LOT_FIELDS = (
    "supplier_id",
    "part_number",
    "category",
    "quantity",
    "certificate_of_conformance",
    "status",
    "reject_reason_code",
)


def consumed_quantity(lot_id):
    total = 0
    for unit in db.db.units.values():
        if unit["build_status"] not in DRAWN_STATUSES:
            continue
        if unit.get("gas_control_lot_id") == lot_id or unit.get("safety_valve_lot_id") == lot_id:
            total += 1
    return total


def component_lot(row):
    out = _project(row, COMPONENT_LOT_FIELDS)
    consumed = consumed_quantity(row["id"])
    out["consumed_quantity"] = consumed
    out["remaining_quantity"] = row["quantity"] - consumed
    return out


# --------------------------------------------------------------------------
# Furnace / GlassLiningBatch
# --------------------------------------------------------------------------

FURNACE_FIELDS = ("furnace_code", "max_firing_temp_c")


def furnace(row):
    out = _project(row, FURNACE_FIELDS)
    out["occupied_window_count"] = sum(
        1
        for b in db.db.batches.values()
        if b["furnace_id"] == row["id"] and b["status"] in ("MIXED", "FIRED")
    )
    return out


BATCH_FIELDS = (
    "furnace_id",
    "batch_code",
    "slurry_mix_code",
    "firing_temp_c",
    "firing_start",
    "firing_end",
    "status",
    "rejected_lot_count",
    "quarantine_reason_code",
)


def batch(row):
    out = _project(row, BATCH_FIELDS)
    out["assigned_lot_count"] = sum(
        1
        for lot in db.db.tank_lots.values()
        if lot.get("glass_lining_batch_id") == row["id"]
    )
    return out


# --------------------------------------------------------------------------
# TankLot / LiningInspection
# --------------------------------------------------------------------------

TANK_LOT_FIELDS = (
    "product_model_id",
    "glass_lining_batch_id",
    "lot_code",
    "planned_quantity",
    "wip_quantity",
    "good_quantity",
    "scrapped_quantity",
    "rework_count",
    "last_scrap_quantity",
    "weld_operator_user_id",
    "production_period",
    "status",
    "foam_density_kg_m3",
    "foam_thickness_mm",
    "achieved_r_value",
    "cascade_rejected",
)


def tank_lot(row):
    out = _project(row, TANK_LOT_FIELDS)
    out["unit_count"] = sum(
        1
        for u in db.db.units.values()
        if u["tank_lot_id"] == row["id"] and u["build_status"] != "SCRAPPED"
    )
    return out


INSPECTION_FIELDS = (
    "tank_lot_id",
    "inspection_type",
    "sample_size",
    "holiday_count",
    "adhesion_class",
    "scrap_quantity",
    "holidays_per_tank",
    "result",
    "inspector_user_id",
    "record_status",
)


def lining_inspection(row):
    # Immutable record: no updated_at, no version.
    return _project(row, INSPECTION_FIELDS, mutable=False)


# --------------------------------------------------------------------------
# ProductModel / TestCell / EfficiencyTest / RatingCertification
# --------------------------------------------------------------------------

PRODUCT_MODEL_FIELDS = (
    "model_code",
    "fuel_type",
    "nominal_capacity_gallons",
    "channel",
    "insulation_r_value",
    "base_model_id",
    "is_private_label",
    "brand_label",
    "certification_status",
    "release_status",
    "uef_rated",
    "fhr_rated",
    "recovery_rate_rated",
    "label_serial_prefix",
)


def held_unit_count(model_id):
    return sum(
        1
        for u in db.db.units.values()
        if u["product_model_id"] == model_id and u["build_status"] == "HELD"
    )


def product_model(row):
    out = _project(row, PRODUCT_MODEL_FIELDS)
    out["held_unit_count"] = held_unit_count(row["id"])
    accrued = row["warranty_reserve_accrued_cents"]
    paid = row["warranty_paid_cents"]
    out["warranty_reserve_accrued_cents"] = accrued
    out["warranty_paid_cents"] = paid
    out["warranty_reserve_balance_cents"] = accrued - paid
    return out


TEST_CELL_FIELDS = ("cell_code", "parallel_slots", "cooldown_hours")


def test_cell(row):
    return _project(row, TEST_CELL_FIELDS)


EFFICIENCY_TEST_FIELDS = (
    "product_model_id",
    "test_cell_id",
    "test_type",
    "sample_size",
    "window_start",
    "window_end",
    "measured_value",
    "effective_minimum",
    "margin",
    "status",
    "recorded_at",
)


def efficiency_test(row):
    return _project(row, EFFICIENCY_TEST_FIELDS)


CERTIFICATION_FIELDS = (
    "product_model_id",
    "status",
    "certified_uef",
    "certified_fhr",
    "certified_recovery",
    "uef_test_count",
    "submitted_by_user_id",
    "approved_by_user_id",
    "effective_date",
    "label_serial_prefix",
    "reason_code",
)


def certification(row):
    return _project(row, CERTIFICATION_FIELDS)


# --------------------------------------------------------------------------
# HeaterUnit / WarrantyClaim
# --------------------------------------------------------------------------

HEATER_UNIT_FIELDS = (
    "tank_lot_id",
    "product_model_id",
    "gas_control_lot_id",
    "safety_valve_lot_id",
    "serial_number",
    "build_status",
    "held_from_status",
    "label_status",
    "production_period",
    "install_water_hardness_gpg",
    "water_hardness_band",
    "hardness_factor",
    "shipped_at",
    "hold_reason_code",
)


def heater_unit(row):
    out = _project(row, HEATER_UNIT_FIELDS)
    out["months_in_service"] = calc.months_in_service(row.get("shipped_at"), db.db.now())
    return out


WARRANTY_CLAIM_FIELDS = (
    "heater_unit_id",
    "failure_mode",
    "reported_water_hardness_gpg",
    "months_in_service_at_report",
    "coverage_pct",
    "approved_payout_cents",
    "status",
    "paid_at",
    "reason_code",
)


def warranty_claim(row):
    return _project(row, WARRANTY_CLAIM_FIELDS)


# --------------------------------------------------------------------------
# RecallCampaign / RecallNotice
# --------------------------------------------------------------------------

RECALL_CAMPAIGN_FIELDS = (
    "campaign_code",
    "scope_product_model_id",
    "remedy_type",
    "budget_cents",
    "serial_range_start",
    "serial_range_end",
    "affected_unit_count",
    "per_unit_remedy_cost_cents",
    "estimated_remedy_cost_cents",
    "status",
    "reason_code",
)


def campaign_counts(campaign_id):
    notices = [n for n in db.db.notices.values() if n["recall_campaign_id"] == campaign_id]
    remedied = sum(1 for n in notices if n["status"] == "REMEDIED")
    unreachable = sum(1 for n in notices if n["status"] == "UNREACHABLE")
    return len(notices), remedied, unreachable


def recall_campaign(row):
    out = _project(row, RECALL_CAMPAIGN_FIELDS)
    notice_count, remedied, _ = campaign_counts(row["id"])
    out["notice_count"] = notice_count
    out["remedied_count"] = remedied
    out["completion_pct_notice_based"] = calc.out_num(
        calc.completion_pct(remedied, notice_count)
    )
    out["completion_pct_population_based"] = calc.out_num(
        calc.completion_pct(remedied, row.get("affected_unit_count"))
    )
    return out


RECALL_NOTICE_FIELDS = (
    "recall_campaign_id",
    "heater_unit_id",
    "status",
    "remedy_cost_cents",
    "notified_at",
    "remedied_at",
    "reason_code",
)


def recall_notice(row):
    return _project(row, RECALL_NOTICE_FIELDS)
