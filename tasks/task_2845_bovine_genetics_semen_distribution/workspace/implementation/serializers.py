"""Entity serialisers.

Derived (`source: computed`) fields are re-derived on every read so that a
resource is always a function of the current logical clock and current data;
they are never stored and therefore never bump a `version`.
"""

import calc
import store

AUDIT = ("created_at", "updated_at", "version")


def _audit(rec, out):
    for key in AUDIT:
        out[key] = rec[key]
    return out


def facility(rec):
    out = {
        "id": rec["id"],
        "code": rec["code"],
        "country_code": rec["country_code"],
        "housing_capacity": rec["housing_capacity"],
        "bench_capacity": rec["bench_capacity"],
        "approved_export_countries": list(rec["approved_export_countries"]),
        "approval_status": rec["approval_status"],
        "suspension_reason": rec["suspension_reason"],
        "resident_sire_count": resident_sire_count(rec["id"]),
    }
    return _audit(rec, out)


def resident_sire_count(facility_id):
    total = 0
    for sire in store.DB["sires"].values():
        if sire["housing_facility_id"] == facility_id and sire["acquisition_status"] == "RESIDENT":
            total += 1
    return total


def country_requirement(rec):
    out = {
        "id": rec["id"],
        "country_code": rec["country_code"],
        "required_test_types": list(rec["required_test_types"]),
        "max_test_age_days": rec["max_test_age_days"],
        "min_isolation_days": rec["min_isolation_days"],
        "sexed_semen_allowed": rec["sexed_semen_allowed"],
        "embryo_allowed": rec["embryo_allowed"],
    }
    return _audit(rec, out)


def collection_count(sire_id):
    total = 0
    for booking in store.DB["collection_bookings"].values():
        if booking["sire_id"] == sire_id and booking["status"] == "COMPLETED":
            total += 1
    return total


def sire(rec):
    out = {
        "id": rec["id"],
        "registration_code": rec["registration_code"],
        "breed": rec["breed"],
        "birth_date": rec["birth_date"],
        "sire_id": rec["sire_id"],
        "dam_sire_id": rec["dam_sire_id"],
        "acquisition_cost_cents": rec["acquisition_cost_cents"],
        "contract_price_cents": rec["contract_price_cents"],
        "acquisition_status": rec["acquisition_status"],
        "collection_status": rec["collection_status"],
        "housing_facility_id": rec["housing_facility_id"],
        "isolation_ends_at": rec["isolation_ends_at"],
        "isolation_days_applied": rec["isolation_days_applied"],
        "suspension_reason": rec["suspension_reason"],
        "published_production_index": rec["published_production_index"],
        "published_health_index": rec["published_health_index"],
        "published_composite_index": rec["published_composite_index"],
        "published_evaluation_effective_at": rec["published_evaluation_effective_at"],
        "progeny_daughter_count": rec["progeny_daughter_count"],
        "pedigree_depth": rec["pedigree_depth"],
        "collection_count": collection_count(rec["id"]),
        "retirement_reason": rec.get("retirement_reason"),
    }
    return _audit(rec, out)


def genomic_evaluation(rec):
    out = {
        "id": rec["id"],
        "sire_id": rec["sire_id"],
        "milk_kg": rec["milk_kg"],
        "fat_kg": rec["fat_kg"],
        "protein_kg": rec["protein_kg"],
        "somatic_cell_score": rec["somatic_cell_score"],
        "fertility_pct": rec["fertility_pct"],
        "longevity_months": rec["longevity_months"],
        "reliability_pct": rec["reliability_pct"],
        "progeny_daughter_count": rec["progeny_daughter_count"],
        "effective_at": rec["effective_at"],
        "evaluation_basis": rec["evaluation_basis"],
        "parent_average_index": rec["parent_average_index"],
        "parent_average_weight": rec["parent_average_weight"],
        "production_index": rec["production_index"],
        "health_index": rec["health_index"],
        "composite_index": rec["composite_index"],
        "status": rec["status"],
        "supersedes_evaluation_id": rec["supersedes_evaluation_id"],
        "published_at": rec["published_at"],
        "revaluation_delta_cents": rec["revaluation_delta_cents"],
    }
    return _audit(rec, out)


def health_test(rec):
    out = {
        "id": rec["id"],
        "sire_id": rec["sire_id"],
        "facility_id": rec["facility_id"],
        "test_type": rec["test_type"],
        "sample_date": rec["sample_date"],
        "validity_days": rec["validity_days"],
        "result": rec["result"],
        "valid_until": rec["valid_until"],
        "resulted_at": rec["resulted_at"],
        "recorded_by_user_id": rec["recorded_by_user_id"],
        "retest_of_test_id": rec["retest_of_test_id"],
    }
    return _audit(rec, out)


def collection_booking(rec):
    out = {
        "id": rec["id"],
        "sire_id": rec["sire_id"],
        "facility_id": rec["facility_id"],
        "start_at": rec["start_at"],
        "end_at": rec["end_at"],
        "status": rec["status"],
        "cancel_reason": rec["cancel_reason"],
        "completed_at": rec["completed_at"],
        "collected_by_ref": rec["collected_by_ref"],
    }
    return _audit(rec, out)


def ejaculate(rec):
    out = {
        "id": rec["id"],
        "booking_id": rec["booking_id"],
        "sire_id": rec["sire_id"],
        "volume_ml": rec["volume_ml"],
        "concentration_m_per_ml": rec["concentration_m_per_ml"],
        "motility_pct": rec["motility_pct"],
        "collected_at": rec["collected_at"],
        "collected_by_ref": rec["collected_by_ref"],
        "total_doses_theoretical": rec["total_doses_theoretical"],
        "qc_status": rec["qc_status"],
        "post_thaw_motility_pct": rec["post_thaw_motility_pct"],
        "morphology_normal_pct": rec["morphology_normal_pct"],
        "evaluated_by_user_id": rec["evaluated_by_user_id"],
        "qc_decided_at": rec["qc_decided_at"],
    }
    return _audit(rec, out)


def straw_lot(rec):
    out = {
        "id": rec["id"],
        "ejaculate_id": rec["ejaculate_id"],
        "sire_id": rec["sire_id"],
        "product_line": rec["product_line"],
        "straw_count": rec["straw_count"],
        "sexing_purity_pct": rec["sexing_purity_pct"],
        "processing_cost_cents": rec["processing_cost_cents"],
        "distribution_status": rec["distribution_status"],
        "doses_available": rec["doses_available"],
        "doses_reserved": rec["doses_reserved"],
        "doses_consigned": rec["doses_consigned"],
        "doses_used": rec["doses_used"],
        "doses_destroyed": rec["doses_destroyed"],
        "unit_book_value_cents": rec["unit_book_value_cents"],
        "valuation_basis": rec["valuation_basis"],
        "pre_revaluation_unit_value_cents": rec["pre_revaluation_unit_value_cents"],
        "released_by_user_id": rec["released_by_user_id"],
        "rejected_reason": rec["rejected_reason"],
        "release_note": rec.get("release_note"),
    }
    return _audit(rec, out)


def export_certificate(rec):
    out = {
        "id": rec["id"],
        "sire_id": rec["sire_id"],
        "straw_lot_id": rec["straw_lot_id"],
        "country_requirement_id": rec["country_requirement_id"],
        "destination_country_code": rec["destination_country_code"],
        "status": rec["status"],
        "submission_round": rec["submission_round"],
        "rejection_reason": rec["rejection_reason"],
        "issued_by_user_id": rec["issued_by_user_id"],
        "issued_at": rec["issued_at"],
        "expires_at": rec["expires_at"],
        "revocation_reason": rec["revocation_reason"],
    }
    return _audit(rec, out)


def distributor(rec):
    out = {
        "id": rec["id"],
        "name": rec["name"],
        "country_code": rec["country_code"],
        "credit_limit_cents": rec["credit_limit_cents"],
        "consignment_enabled": rec["consignment_enabled"],
    }
    out.update(calc.distributor_exposure(rec["id"]))
    return _audit(rec, out)


def tank(rec):
    level, next_due, status = calc.tank_derived(rec)
    out = {
        "id": rec["id"],
        "serial": rec["serial"],
        "distributor_id": rec["distributor_id"],
        "capacity_straws": rec["capacity_straws"],
        "service_interval_days": rec["service_interval_days"],
        "assigned_technician_name": rec["assigned_technician_name"],
        "technician_cert_expiry_at": rec["technician_cert_expiry_at"],
        "last_service_at": rec["last_service_at"],
        "last_service_fill_pct": rec["last_service_fill_pct"],
        "next_service_due_at": next_due,
        "ln2_level_pct": calc.num(level),
        "service_count": rec["service_count"],
        "tank_status": status,
        "straws_on_hand": calc.tank_straws_on_hand(rec["id"]),
    }
    return _audit(rec, out)


def consignment_transfer(rec):
    out = {
        "id": rec["id"],
        "straw_lot_id": rec["straw_lot_id"],
        "distributor_id": rec["distributor_id"],
        "tank_id": rec["tank_id"],
        "export_certificate_id": rec["export_certificate_id"],
        "doses": rec["doses"],
        "unit_price_cents": rec["unit_price_cents"],
        "status": rec["status"],
        "approved_by_user_id": rec["approved_by_user_id"],
        "rejection_reason": rec["rejection_reason"],
        "tank_service_count_at_dispatch": rec["tank_service_count_at_dispatch"],
        "doses_used": rec["doses_used"],
        "doses_returned": rec["doses_returned"],
        "doses_on_hand": calc.transfer_doses_on_hand(rec),
        "carried_value_cents": calc.transfer_carried_value(rec),
        "gross_cents": rec["gross_cents"],
        "service_fee_cents": rec["service_fee_cents"],
        "rebate_cents": rec["rebate_cents"],
        "settlement_total_cents": rec["settlement_total_cents"],
        "received_at": rec["received_at"],
    }
    return _audit(rec, out)


def recommendation_count(herd_id):
    total = 0
    for rec in store.DB["mating_recommendations"].values():
        if rec["customer_herd_id"] == herd_id and rec["status"] in ("PROPOSED", "ACCEPTED"):
            total += 1
    return total


def customer_herd(rec):
    out = {
        "id": rec["id"],
        "herd_name": rec["herd_name"],
        "distributor_id": rec["distributor_id"],
        "base_sire_id": rec["base_sire_id"],
        "country_code": rec["country_code"],
        "target_product_line": rec["target_product_line"],
        "max_inbreeding_pct": rec["max_inbreeding_pct"],
        "recommendation_count": recommendation_count(rec["id"]),
    }
    return _audit(rec, out)


def mating_recommendation(rec):
    out = {
        "id": rec["id"],
        "customer_herd_id": rec["customer_herd_id"],
        "dam_ref": rec["dam_ref"],
        "dam_sire_id": rec["dam_sire_id"],
        "requested_product_line": rec["requested_product_line"],
        "doses_requested": rec["doses_requested"],
        "excluded_sire_ids": list(rec["excluded_sire_ids"]),
        "recommended_sire_id": rec["recommended_sire_id"],
        "straw_lot_id": rec["straw_lot_id"],
        "inbreeding_pct": rec["inbreeding_pct"],
        "expected_conception_rate": rec["expected_conception_rate"],
        "candidate_pool_size": rec["candidate_pool_size"],
        "status": rec["status"],
        "doses_committed": rec["doses_committed"],
        "decided_at": rec["decided_at"],
    }
    return _audit(rec, out)
