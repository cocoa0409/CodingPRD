"""Per-entity output projections.

The four immutable reference records (Commodity, CompatibilityRule,
FuelIndexPosting, RiverStageReading) deliberately carry only `id` and
`created_at` - no `updated_at` and no `version` (PRD 2.4).
"""
from datetime import datetime
from decimal import Decimal

from common import fmt_dt

COMMON = ["created_at", "updated_at", "version"]
COMMON_IMMUTABLE = ["created_at"]

FIELDS = {
    "Shipper": ["id", "name", "credit_limit_cents", "outstanding_balance_cents",
                "status", "open_claim_count"] + COMMON,
    "Commodity": ["id", "code", "commodity_group", "residue_class", "hazard_flag",
                  "stowage_factor"] + COMMON_IMMUTABLE,
    "CompatibilityRule": ["id", "prior_commodity_group", "next_commodity_group",
                          "required_cleaning_level", "prohibited"] + COMMON_IMMUTABLE,
    "TariffFiling": ["id", "tariff_code", "commodity_group",
                     "base_rate_cents_per_ton_mile", "min_charge_cents",
                     "demurrage_rate_cents_per_hour", "fuel_surcharge_table",
                     "effective_from", "effective_to", "status",
                     "filed_by_user_id", "effectuated_by_user_id",
                     "supersedes_tariff_filing_id"] + COMMON,
    "FuelIndexPosting": ["id", "posting_date",
                         "diesel_price_cents_per_gallon"] + COMMON_IMMUTABLE,
    "RiverStageReading": ["id", "gauge_station", "reading_at", "stage_feet",
                          "draft_restriction_band", "max_draft_feet",
                          "tow_size_cap_barges"] + COMMON_IMMUTABLE,
    "Barge": ["id", "hull_number", "capacity_tons", "light_draft_feet",
              "tons_per_inch_immersion", "operational_status",
              "cleanliness_status", "last_cargo_commodity_id",
              "last_cleaning_certificate_number"] + COMMON,
    "CleaningOrder": ["id", "barge_id", "required_for_commodity_id",
                      "freight_contract_id", "required_cleaning_level",
                      "performed_level", "inspection_passed", "certificate_number",
                      "status", "fee_cents"] + COMMON,
    "FleetingBerth": ["id", "harbor_name", "river_mile", "capacity_barges",
                      "daily_fee_cents_per_barge", "switch_fee_cents",
                      "occupied_barge_count"] + COMMON,
    "FleetingAssignment": ["id", "barge_id", "fleeting_berth_id",
                           "freight_contract_id", "start_at", "end_at",
                           "released_at", "status", "estimated_fee_cents",
                           "billable_days", "fee_cents"] + COMMON,
    "Lock": ["id", "lock_name", "river_mile", "chamber_capacity_barges",
             "cycle_minutes", "turnback_buffer_minutes", "status",
             "granted_reservation_count"] + COMMON,
    "LockReservation": ["id", "lock_id", "tow_id", "requested_start_at",
                        "cut_count", "scheduled_start_at", "scheduled_end_at",
                        "occupied_until_at", "actual_start_at", "actual_end_at",
                        "delay_minutes", "priority_class", "status"] + COMMON,
    "Tow": ["id", "towboat_name", "horsepower", "origin_mile", "destination_mile",
            "controlling_gauge_station", "status", "barge_count",
            "total_loaded_tons", "max_draft_feet", "allowed_draft_feet",
            "draft_restriction_band", "accrued_delay_minutes",
            "pending_lock_reservation_count", "departed_at",
            "arrived_at"] + COMMON,
    "BargeAssignment": ["id", "tow_id", "barge_id", "freight_contract_id",
                        "cut_position", "loaded_tons", "barge_draft_feet",
                        "status", "discharge_status", "arrived_at",
                        "unload_started_at", "unload_finished_at",
                        "discharged_tons", "gross_laytime_hours",
                        "net_laytime_hours", "delay_attributed_minutes"] + COMMON,
    "FreightContract": ["id", "shipper_id", "commodity_id", "contracted_tons",
                        "origin_mile", "destination_mile", "distance_miles",
                        "laytime_hours", "declared_value_cents_per_ton",
                        "claim_settlement_basis", "pinned_tariff_filing_id",
                        "pinned_fuel_price_cents_per_gallon",
                        "pinned_fuel_surcharge_pct", "movement_status",
                        "billing_status", "accrued_delay_minutes",
                        "delay_protection_applied", "linehaul_cents",
                        "fuel_surcharge_cents", "fleeting_fee_cents",
                        "cleaning_fee_cents", "demurrage_cents", "subtotal_cents",
                        "volume_rebate_cents", "claim_credit_cents",
                        "total_cents"] + COMMON,
    "CargoClaim": ["id", "freight_contract_id", "barge_assignment_id",
                   "claim_type", "claimed_tons", "claimed_amount_cents",
                   "shortage_tons", "tolerance_tons",
                   "settlement_deductible_cents", "settlement_franchise_cents",
                   "settlement_cents", "revision_round", "status",
                   "assessed_by_user_id", "approved_by_user_id", "denial_reason",
                   "info_request_note", "response_note"] + COMMON,
}


def _value(v):
    if isinstance(v, datetime):
        return fmt_dt(v)
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, list):
        return [_value(x) for x in v]
    if isinstance(v, dict):
        return {k: _value(x) for k, x in v.items()}
    return v


def make_serializer(entity):
    fields = FIELDS[entity]

    def _ser(rec):
        return {f: _value(rec.get(f)) for f in fields}

    return _ser


ser_shipper = make_serializer("Shipper")
ser_commodity = make_serializer("Commodity")
ser_rule = make_serializer("CompatibilityRule")
ser_filing = make_serializer("TariffFiling")
ser_posting = make_serializer("FuelIndexPosting")
ser_reading = make_serializer("RiverStageReading")
ser_barge = make_serializer("Barge")
ser_cleaning = make_serializer("CleaningOrder")
ser_berth = make_serializer("FleetingBerth")
ser_fleeting = make_serializer("FleetingAssignment")
ser_lock = make_serializer("Lock")
ser_reservation = make_serializer("LockReservation")
ser_tow = make_serializer("Tow")
ser_assignment = make_serializer("BargeAssignment")
ser_contract = make_serializer("FreightContract")
ser_claim = make_serializer("CargoClaim")
