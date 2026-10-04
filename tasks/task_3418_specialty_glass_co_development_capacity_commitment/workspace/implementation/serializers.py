"""Entity serializers: internal dicts (datetimes / Decimals) -> wire dicts."""
from clock import iso_ms


def _ts(value):
    return None if value is None else iso_ms(value)


def _num(value):
    return None if value is None else float(value)


def _common(e):
    return {
        "created_at": iso_ms(e["created_at"]),
        "updated_at": iso_ms(e["updated_at"]),
        "version": e["version"],
    }


def device_maker(e):
    d = {
        "id": e["id"],
        "name": e["name"],
        "region": e["region"],
        "standing_tier": e["standing_tier"],
        "ip_review_status": e["ip_review_status"],
    }
    d.update(_common(e))
    return d


def program(e):
    d = {
        "id": e["id"],
        "device_maker_id": e["device_maker_id"],
        "name": e["name"],
        "primary_market": e["primary_market"],
        "confidentiality_tier": e["confidentiality_tier"],
        "status": e["status"],
        "nda_reference": e["nda_reference"],
        "design_freeze_date": _ts(e["design_freeze_date"]),
    }
    d.update(_common(e))
    return d


def composition(e):
    d = {
        "id": e["id"],
        "program_id": e["program_id"],
        "composition_code": e["composition_code"],
        "complexity_multiplier": e["complexity_multiplier"],
        "status": e["status"],
    }
    d.update(_common(e))
    return d


def qual_cycle(e):
    d = {
        "id": e["id"],
        "composition_id": e["composition_id"],
        "test_plan_ref": e["test_plan_ref"],
        "attempt_number": e["attempt_number"],
        "status": e["status"],
        "result_recorded_at": _ts(e["result_recorded_at"]),
    }
    d.update(_common(e))
    return d


def tank(e):
    d = {
        "id": e["id"],
        "commitment_id": e["commitment_id"],
        "capacity_units_per_day": e["capacity_units_per_day"],
        "status": e["status"],
        "construction_ready_date": _ts(e["construction_ready_date"]),
    }
    d.update(_common(e))
    return d


def campaign(e):
    d = {
        "id": e["id"],
        "tank_id": e["tank_id"],
        "composition_id": e["composition_id"],
        "start_date": _ts(e["start_date"]),
        "end_date": _ts(e["end_date"]),
        "planned_units": e["planned_units"],
        "status": e["status"],
        "expected_good_units": e["expected_good_units"],
        "unallocated_units": e["unallocated_units"],
        "cumulative_good_units": e["cumulative_good_units"],
        "cumulative_scrap_units": e["cumulative_scrap_units"],
        "realized_yield": _num(e["realized_yield"]),
        "provisional_unit_cost_cents": e["provisional_unit_cost_cents"],
        "final_unit_cost_cents": e["final_unit_cost_cents"],
    }
    d.update(_common(e))
    return d


def commitment(e):
    d = {
        "id": e["id"],
        "program_id": e["program_id"],
        "device_maker_id": e["device_maker_id"],
        "committed_units": e["committed_units"],
        "required_units": e["required_units"],
        "prepayment_cents": e["prepayment_cents"],
        "status": e["status"],
        "coverage_tier": e["coverage_tier"],
        "effective_units": e["effective_units"],
        "fulfilled_units": e["fulfilled_units"],
        "supply_coverage": _num(e["supply_coverage"]),
        "prepayment_applied_cents": e["prepayment_applied_cents"],
        "prepayment_remaining_cents": e["prepayment_remaining_cents"],
        "prepayment_refunded_cents": e["prepayment_refunded_cents"],
        "breach_deadline": _ts(e["breach_deadline"]),
        "countersigned_by": e["countersigned_by"],
        "signed_at": _ts(e["signed_at"]),
    }
    d.update(_common(e))
    return d


def allocation(e):
    d = {
        "id": e["id"],
        "commitment_id": e["commitment_id"],
        "campaign_id": e["campaign_id"],
        "units": e["units"],
        "status": e["status"],
    }
    d.update(_common(e))
    return d


def license_(e):
    d = {
        "id": e["id"],
        "device_maker_id": e["device_maker_id"],
        "program_id": e["program_id"],
        "market": e["market"],
        "effective_date": _ts(e["effective_date"]),
        "expiry_date": _ts(e["expiry_date"]),
        "license_status": e["license_status"],
        "marketing_status": e["marketing_status"],
        "suspension_reason": e["suspension_reason"],
        "cumulative_royalty_cents": e["cumulative_royalty_cents"],
    }
    d.update(_common(e))
    return d


def usage_report(e):
    d = {
        "id": e["id"],
        "license_id": e["license_id"],
        "period_start": _ts(e["period_start"]),
        "period_end": _ts(e["period_end"]),
        "lines": e["lines"],
        "status": e["status"],
        "royalty_rate_applied": _num(e["royalty_rate_applied"]),
        "provisional_royalty_cents": e["provisional_royalty_cents"],
        "final_royalty_cents": e["final_royalty_cents"],
    }
    d.update(_common(e))
    return d
