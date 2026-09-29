"""Per-entity JSON projections, including the fields derived on read."""

import derive
import ledger
import money


def _num(value):
    """A Decimal-carried quantity rendered as a JSON number."""
    if value is None:
        return None
    return float(value)


def _audit(record, payload):
    payload["created_at"] = record["created_at"]
    payload["updated_at"] = record["updated_at"]
    payload["version"] = int(record["version"])
    return payload


def funding_unit(unit):
    amounts = ledger.unit_amounts(unit)
    payload = {
        "id": unit["id"],
        "name": unit["name"],
        "unit_type": unit["unit_type"],
        "parent_unit_id": unit["parent_unit_id"],
        "cost_share_pool_cents": int(unit["cost_share_pool_cents"]),
        "reserved_cents": amounts["reserved_cents"],
        "committed_cents": amounts["committed_cents"],
        "disbursed_cents": amounts["disbursed_cents"],
        "refunded_cents": amounts["refunded_cents"],
        "available_pool_cents": amounts["available_pool_cents"],
    }
    return _audit(unit, payload)


def faculty(record):
    payload = {
        "id": record["id"],
        "full_name": record["full_name"],
        "rank": record["rank"],
        "funding_unit_id": record["funding_unit_id"],
        "appointment_status": record["appointment_status"],
        "planned_start_date": record["planned_start_date"],
        "activated_on": record["activated_on"],
        "departure_intent": record["departure_intent"],
        "departure_effective_on": record["departure_effective_on"],
        "target_funding_unit_id": record["target_funding_unit_id"],
        "separated_on": record["separated_on"],
        "retention_round": int(record["retention_round"]),
    }
    return _audit(record, payload)


def package(record):
    rollup = ledger.package_rollup(record)
    payload = {
        "id": record["id"],
        "faculty_id": record["faculty_id"],
        "package_kind": record["package_kind"],
        "superseded_package_id": record["superseded_package_id"],
        "department_unit_id": record["department_unit_id"],
        "college_unit_id": record["college_unit_id"],
        "dean_unit_id": record["dean_unit_id"],
        "dept_share_pct": int(record["dept_share_pct"]),
        "college_share_pct": int(record["college_share_pct"]),
        "dean_share_pct": int(record["dean_share_pct"]),
        "proposed_total_cents": int(record["proposed_total_cents"]),
        "spend_deadline_on": record["spend_deadline_on"],
        "negotiation_status": record["negotiation_status"],
        "spend_status": record["spend_status"],
        "negotiation_round": int(record["negotiation_round"]),
        "counter_total_cents": record["counter_total_cents"],
        "proposed_by_user_id": record["proposed_by_user_id"],
        "endorsed_by_user_id": record["endorsed_by_user_id"],
        "approved_by_user_id": record["approved_by_user_id"],
        "total_committed_cents": rollup["total_committed_cents"],
        "total_encumbered_cents": rollup["total_encumbered_cents"],
        "total_disbursed_cents": rollup["total_disbursed_cents"],
        "total_available_cents": rollup["total_available_cents"],
        "total_expired_cents": rollup["total_expired_cents"],
        "total_recaptured_cents": rollup["total_recaptured_cents"],
        "spend_down_ratio": _num(rollup["spend_down_ratio"]),
        "settlement_variant": record["settlement_variant"],
        "recaptured_unspent_cents": int(record["recaptured_unspent_cents"]),
        "transferred_balance_cents": int(record["transferred_balance_cents"]),
        "college_holdback_cents": int(record["college_holdback_cents"]),
        "activated_on": record["activated_on"],
        "closed_out_on": record["closed_out_on"],
    }
    return _audit(record, payload)


def tranche(record):
    balances = ledger.tranche_balances(record)
    payload = {
        "id": record["id"],
        "package_id": record["package_id"],
        "category": record["category"],
        "fiscal_year": int(record["fiscal_year"]),
        "amount_cents": int(record["amount_cents"]),
        "available_on": record["available_on"],
        "expires_on": record["expires_on"],
        "carryforward_policy": record["carryforward_policy"],
        "carryforward_cap_pct": record["carryforward_cap_pct"],
        "status": record["status"],
        "carried_in_cents": balances["carried_in_cents"],
        "carried_out_cents": balances["carried_out_cents"],
        "encumbered_cents": balances["encumbered_cents"],
        "disbursed_cents": balances["disbursed_cents"],
        "expired_cents": balances["expired_cents"],
        "recaptured_cents": balances["recaptured_cents"],
        "available_balance_cents": balances["available_balance_cents"],
        "opened_on": record["opened_on"],
    }
    return _audit(record, payload)


def lab_space(record):
    payload = {
        "id": record["id"],
        "building_code": record["building_code"],
        "room_number": record["room_number"],
        "net_sq_ft": int(record["net_sq_ft"]),
        "space_class": record["space_class"],
        "status": record["status"],
        "power_kw_capacity": _num(record["power_kw_capacity"]),
        "chilled_water_available": bool(record["chilled_water_available"]),
        "fume_hood_count": int(record["fume_hood_count"]),
        "floor_load_psf": int(record["floor_load_psf"]),
        "allocated_share_pct": derive.allocated_share_pct(record),
        "installed_power_kw": _num(derive.installed_power_kw(record)),
        "installed_fume_hoods": derive.installed_fume_hoods(record),
    }
    return _audit(record, payload)


def space_assignment(record):
    payload = {
        "id": record["id"],
        "space_id": record["space_id"],
        "faculty_id": record["faculty_id"],
        "share_pct": int(record["share_pct"]),
        "effective_from": record["effective_from"],
        "effective_to": record["effective_to"],
        "status": record["status"],
        "released_on": record["released_on"],
    }
    return _audit(record, payload)


def renovation_project(record):
    payload = {
        "id": record["id"],
        "package_id": record["package_id"],
        "space_id": record["space_id"],
        "scope_tier": record["scope_tier"],
        "estimate_cents": int(record["estimate_cents"]),
        "awarded_cents": record["awarded_cents"],
        "status": record["status"],
        "rescope_count": int(record["rescope_count"]),
        "subsidy_estimate_cents": record["subsidy_estimate_cents"],
        "package_charge_estimate_cents": record["package_charge_estimate_cents"],
        "actual_total_cents": record["actual_total_cents"],
        "subsidy_final_cents": record["subsidy_final_cents"],
        "package_charge_final_cents": record["package_charge_final_cents"],
        "cost_variance_cents": record["cost_variance_cents"],
        "awarded_on": record["awarded_on"],
        "completed_on": record["completed_on"],
    }
    return _audit(record, payload)


def renovation_phase(record):
    payload = {
        "id": record["id"],
        "project_id": record["project_id"],
        "sequence_no": int(record["sequence_no"]),
        "name": record["name"],
        "planned_start": record["planned_start"],
        "planned_end": record["planned_end"],
        "budget_cents": int(record["budget_cents"]),
        "actual_cost_cents": record["actual_cost_cents"],
        "actual_start": record["actual_start"],
        "actual_end": record["actual_end"],
        "status": record["status"],
    }
    return _audit(record, payload)


def equipment_order(record):
    amounts = derive.order_amounts(record)
    payload = {
        "id": record["id"],
        "package_id": record["package_id"],
        "install_space_id": record["install_space_id"],
        "vendor_name": record["vendor_name"],
        "item_description": record["item_description"],
        "quoted_cents": int(record["quoted_cents"]),
        "lead_time_days": int(record["lead_time_days"]),
        "required_power_kw": _num(record["required_power_kw"]),
        "requires_chilled_water": bool(record["requires_chilled_water"]),
        "required_fume_hoods": int(record["required_fume_hoods"]),
        "required_floor_load_psf": int(record["required_floor_load_psf"]),
        "status": record["status"],
        "utility_block_reason": record["utility_block_reason"],
        "placed_on": record["placed_on"],
        "expected_delivery_on": record["expected_delivery_on"],
        "delivered_on": record["delivered_on"],
        "installed_on": record["installed_on"],
        "encumbered_cents": amounts["encumbered_cents"],
        "disbursed_cents": amounts["disbursed_cents"],
        "transfer_disposition": record["transfer_disposition"],
    }
    return _audit(record, payload)


def staff_appointment(record):
    amounts = derive.appointment_amounts(record)
    payload = {
        "id": record["id"],
        "package_id": record["package_id"],
        "appointment_type": record["appointment_type"],
        "fte": _num(record["fte"]),
        "monthly_cost_cents": int(record["monthly_cost_cents"]),
        "start_date": record["start_date"],
        "end_date": record["end_date"],
        "status": record["status"],
        "committed_months": int(record["committed_months"]),
        "encumbered_cents": amounts["encumbered_cents"],
        "disbursed_cents": amounts["disbursed_cents"],
        "ended_on": record["ended_on"],
    }
    return _audit(record, payload)


def spend_transaction(record):
    return {
        "id": record["id"],
        "package_id": record["package_id"],
        "tranche_id": record["tranche_id"],
        "kind": record["kind"],
        "amount_cents": int(record["amount_cents"]),
        "source_kind": record["source_kind"],
        "source_id": record["source_id"],
        "reverses_transaction_id": record["reverses_transaction_id"],
        "dept_share_cents": int(record["dept_share_cents"]),
        "college_share_cents": int(record["college_share_cents"]),
        "dean_share_cents": int(record["dean_share_cents"]),
        "memo": record["memo"],
        "created_at": record["created_at"],
    }


def spend_summary(record):
    rollup = ledger.package_rollup(record)
    dept = 0
    college = 0
    dean = 0
    for row in ledger.rows_for_package(record["id"]):
        dept += int(row["dept_share_cents"])
        college += int(row["college_share_cents"])
        dean += int(row["dean_share_cents"])
    identity_holds = True
    for item in ledger.tranches_of_package(record["id"]):
        balances = ledger.tranche_balances(item)
        left = int(item["amount_cents"]) + balances["carried_in_cents"]
        right = (
            balances["available_balance_cents"]
            + balances["encumbered_cents"]
            + balances["disbursed_cents"]
            + balances["carried_out_cents"]
            + balances["expired_cents"]
            + balances["recaptured_cents"]
        )
        if left != right:
            identity_holds = False
    return {
        "total_committed_cents": rollup["total_committed_cents"],
        "total_encumbered_cents": rollup["total_encumbered_cents"],
        "total_disbursed_cents": rollup["total_disbursed_cents"],
        "total_available_cents": rollup["total_available_cents"],
        "total_expired_cents": rollup["total_expired_cents"],
        "total_recaptured_cents": rollup["total_recaptured_cents"],
        "total_carried_out_cents": rollup["total_carried_out_cents"],
        "total_carried_in_cents": rollup["total_carried_in_cents"],
        "spend_down_ratio": _num(rollup["spend_down_ratio"]),
        "dept_share_cents": dept,
        "college_share_cents": college,
        "dean_share_cents": dean,
        "balance_identity_holds": identity_holds,
    }
