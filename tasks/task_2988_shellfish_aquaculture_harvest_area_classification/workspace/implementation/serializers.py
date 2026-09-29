"""Resource serialisation (PRD 2.4): every computed field is materialised on
the resource and returned in `data` on both reads and writes.  HusbandryLog,
WaterSample and RainfallEvent deliberately carry neither updated_at nor
version; every other resource carries the full quartet.
"""

import calc
from core import iso, iso_date, num


def _identity(row):
    return {
        "id": row["id"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def _append_only_identity(row):
    return {"id": row["id"], "created_at": iso(row["created_at"])}


def growing_area(row):
    out = {
        "code": row["code"],
        "water_body": row["water_body"],
        "classification": row["classification"],
        "harvest_status": row["harvest_status"],
        "rainfall_closure_threshold_in": num(row["rainfall_closure_threshold_in"]),
        "rainfall_closure_hours": row["rainfall_closure_hours"],
        "reopen_sample_count_required": row["reopen_sample_count_required"],
        "clean_sample_mpn_limit": num(row["clean_sample_mpn_limit"]),
        "conditional_management_plan_on_file": row[
            "conditional_management_plan_on_file"
        ],
        "last_closure_started_at": iso(row["last_closure_started_at"]),
        "closure_reopen_eligible_at": iso(row["closure_reopen_eligible_at"]),
        "consecutive_clean_samples": row["consecutive_clean_samples"],
        "accepted_sample_count": row["accepted_sample_count"],
        "geometric_mean_mpn": num(row["geometric_mean_mpn"]),
        "p90_mpn": num(row["p90_mpn"]),
        "eligible_classification": row["eligible_classification"],
        "open_authorization_count": row["open_authorization_count"],
    }
    out.update(_identity(row))
    return out


def lease(row):
    out = {
        "growing_area_id": row["growing_area_id"],
        "operator_user_id": row["operator_user_id"],
        "lease_code": row["lease_code"],
        "requested_acreage": num(row["requested_acreage"]),
        "plot_codes": list(row["plot_codes"]),
        "gear_types_permitted": list(row["gear_types_permitted"]),
        "authorized_gear_units": row["authorized_gear_units"],
        "deployed_gear_units": row["deployed_gear_units"],
        "status": row["status"],
        "navigation_clearance": row["navigation_clearance"],
        "environmental_clearance": row["environmental_clearance"],
        "navigation_reviewer_user_id": row["navigation_reviewer_user_id"],
        "environmental_reviewer_user_id": row["environmental_reviewer_user_id"],
        "revision_round": row["revision_round"],
        "rent_paid_through_date": iso_date(row["rent_paid_through_date"]),
        "royalty_accrued_cents": row["royalty_accrued_cents"],
        "decided_at": iso(row["decided_at"]),
    }
    out.update(_identity(row))
    return out


def hatchery(row):
    out = {
        "name": row["name"],
        "state_code": row["state_code"],
        "ncsp_certificate_no": row["ncsp_certificate_no"],
        "certificate_expires_on": iso_date(row["certificate_expires_on"]),
        "pathogen_free_species": list(row["pathogen_free_species"]),
    }
    out.update(_identity(row))
    return out


def seed_lot(row):
    out = {
        "hatchery_id": row["hatchery_id"],
        "lease_id": row["lease_id"],
        "species": row["species"],
        "received_seed_count": row["received_seed_count"],
        "disease_certificate_no": row["disease_certificate_no"],
        "disease_cert_issued_on": iso_date(row["disease_cert_issued_on"]),
        "shipped_on": iso_date(row["shipped_on"]),
        "status": row["status"],
        "screening_result": row["screening_result"],
        "screened_on": iso_date(row["screened_on"]),
        "nursery_started_on": iso_date(row["nursery_started_on"]),
        "nursery_system": row["nursery_system"],
        "nursery_completed_on": iso_date(row["nursery_completed_on"]),
        "surviving_seed_count": row["surviving_seed_count"],
        "survival_rate_pct": num(row["survival_rate_pct"]),
        "allocated_seed_count": row["allocated_seed_count"],
        "unallocated_seed_count": row["unallocated_seed_count"],
    }
    out.update(_identity(row))
    return out


def growout_unit(row):
    out = {
        "lease_id": row["lease_id"],
        "seed_lot_id": row["seed_lot_id"],
        "plot_code": row["plot_code"],
        "gear_type": row["gear_type"],
        "gear_units": row["gear_units"],
        "seed_count_planted": row["seed_count_planted"],
        "deployed_on": iso_date(row["deployed_on"]),
        "planned_retrieval_on": iso_date(row["planned_retrieval_on"]),
        "status": row["status"],
        "retrieved_on": iso_date(row["retrieved_on"]),
        "void_reason": row["void_reason"],
        "last_inspection_at": iso(row["last_inspection_at"]),
        "last_predator_control_at": iso(row["last_predator_control_at"]),
        "husbandry_current": calc.husbandry_current(row),
        "mortality_count_total": row["mortality_count_total"],
    }
    out.update(_identity(row))
    return out


def husbandry_log(row):
    out = {
        "growout_unit_id": row["growout_unit_id"],
        "log_type": row["log_type"],
        "performed_at": iso(row["performed_at"]),
        "performed_by_user_id": row["performed_by_user_id"],
        "predator_species": row["predator_species"],
        "control_method": row["control_method"],
        "mortality_count": row["mortality_count"],
        "notes": row["notes"],
    }
    out.update(_append_only_identity(row))
    return out


def water_sample(row):
    out = {
        "growing_area_id": row["growing_area_id"],
        "station_code": row["station_code"],
        "collected_at": iso(row["collected_at"]),
        "fecal_coliform_mpn": num(row["fecal_coliform_mpn"]),
        "water_temp_c": num(row["water_temp_c"]),
        "salinity_ppt": num(row["salinity_ppt"]),
        "sample_status": row["sample_status"],
        "is_adverse_condition": calc.is_adverse_condition(row),
        "counted_clean": calc.counted_clean(row),
    }
    out.update(_append_only_identity(row))
    return out


def rainfall_event(row):
    out = {
        "growing_area_id": row["growing_area_id"],
        "gauge_code": row["gauge_code"],
        "observed_at": iso(row["observed_at"]),
        "inches_24h": num(row["inches_24h"]),
        "triggered_closure": row["triggered_closure"],
        "voided_authorization_count": row["voided_authorization_count"],
    }
    out.update(_append_only_identity(row))
    return out


def vessel(row):
    out = {
        "name": row["name"],
        "registration_no": row["registration_no"],
        "refrigeration_type": row["refrigeration_type"],
        "concurrent_authorization_capacity": row["concurrent_authorization_capacity"],
        "active_authorization_count": row["active_authorization_count"],
    }
    out.update(_identity(row))
    return out


def authorization(row):
    out = {
        "lease_id": row["lease_id"],
        "growout_unit_id": row["growout_unit_id"],
        "vessel_id": row["vessel_id"],
        "dealer_id": row["dealer_id"],
        "growing_area_id": row["growing_area_id"],
        "window_start": iso(row["window_start"]),
        "window_end": iso(row["window_end"]),
        "projected_bushels": row["projected_bushels"],
        "harvested_bushels": row["harvested_bushels"],
        "status": row["status"],
        "harvest_start_at": iso(row["harvest_start_at"]),
        "harvest_end_at": iso(row["harvest_end_at"]),
        "void_reason": row["void_reason"],
    }
    out.update(_identity(row))
    return out


def harvest_lot(row):
    out = {
        "harvest_authorization_id": row["harvest_authorization_id"],
        "dealer_id": row["dealer_id"],
        "shipment_id": row["shipment_id"],
        "lot_code": row["lot_code"],
        "bushels": row["bushels"],
        "first_out_of_water_at": iso(row["first_out_of_water_at"]),
        "last_out_of_water_at": iso(row["last_out_of_water_at"]),
        "placed_in_temperature_control_at": iso(
            row["placed_in_temperature_control_at"]
        ),
        "water_temp_c": num(row["water_temp_c"]),
        "ttt_minutes_first_basis": row["ttt_minutes_first_basis"],
        "ttt_minutes_last_basis": row["ttt_minutes_last_basis"],
        "ttt_basis_variant": row["ttt_basis_variant"],
        "governing_ttt_minutes": row["governing_ttt_minutes"],
        "allowed_ttt_minutes": row["allowed_ttt_minutes"],
        "vibrio_control_plan_id": row["vibrio_control_plan_id"],
        "vibrio_plan_month": row["vibrio_plan_month"],
        "compliance_status": row["compliance_status"],
        "status": row["status"],
        "tag_harvest_date": iso_date(row["tag_harvest_date"]),
        "tag_area_code": row["tag_area_code"],
        "tag_lease_code": row["tag_lease_code"],
        "tag_dealer_certification_no": row["tag_dealer_certification_no"],
        "season_total_bushels_at_creation": row["season_total_bushels_at_creation"],
        "royalty_rate_cents_per_bushel": row["royalty_rate_cents_per_bushel"],
        "royalty_cents": row["royalty_cents"],
        "inspection_fee_cents": row["inspection_fee_cents"],
        "conservation_surcharge_cents": row["conservation_surcharge_cents"],
        "lot_settlement_cents": row["lot_settlement_cents"],
        "embargo_reason": row["embargo_reason"],
        "void_reason": row["void_reason"],
    }
    out.update(_identity(row))
    return out


def dealer(row):
    out = {
        "name": row["name"],
        "state_code": row["state_code"],
        "certification_category": row["certification_category"],
        "certification_no": row["certification_no"],
        "certified_through": iso_date(row["certified_through"]),
        "icssl_listed_through": iso_date(row["icssl_listed_through"]),
        "listing_status": row["listing_status"],
        "recall_strike_count": row["recall_strike_count"],
        "suspension_reason": row["suspension_reason"],
    }
    out.update(_identity(row))
    return out


def shipment(row):
    out = {
        "dealer_id": row["dealer_id"],
        "destination_state": row["destination_state"],
        "carrier": row["carrier"],
        "lot_ids": list(row["lot_ids"]),
        "lot_count": row["lot_count"],
        "total_bushels": row["total_bushels"],
        "is_interstate": row["is_interstate"],
        "status": row["status"],
        "shipped_at": iso(row["shipped_at"]),
        "held_reason": row["held_reason"],
        "recall_reason": row["recall_reason"],
    }
    out.update(_identity(row))
    return out


def investigation(row):
    out = {
        "source_shipment_id": row["source_shipment_id"],
        "reported_at": iso(row["reported_at"]),
        "illness_count": row["illness_count"],
        "pathogen": row["pathogen"],
        "scope_variant": row["scope_variant"],
        "status": row["status"],
        "traced_lot_ids": list(row["traced_lot_ids"]),
        "traced_lot_count": row["traced_lot_count"],
        "recalled_shipment_count": row["recalled_shipment_count"],
        "confirmed_at": iso(row["confirmed_at"]),
    }
    out.update(_identity(row))
    return out


def vibrio_plan(row):
    out = {
        "season_month": row["season_month"],
        "max_time_to_temperature_minutes": row["max_time_to_temperature_minutes"],
        "high_water_temp_c": num(row["high_water_temp_c"]),
        "high_temp_reduction_minutes": row["high_temp_reduction_minutes"],
        "status": row["status"],
    }
    out.update(_identity(row))
    return out


def classification_summary(stats):
    return {
        "variant": stats["variant"],
        "sample_count": stats["sample_count"],
        "mean_log10": num(stats["mean_log10"]),
        "geometric_mean_mpn": num(stats["geometric_mean_mpn"]),
        "p90_mpn": num(stats["p90_mpn"]),
        "eligible_classification": stats["eligible_classification"],
        "window_start_at": iso(stats["window_start_at"]),
        "window_end_at": iso(stats["window_end_at"]),
    }
