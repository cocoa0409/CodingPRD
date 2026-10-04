"""Entity serializers — explicit field-by-field projections so internal keys
(e.g. _seq) never leak. Datetimes serialize as ISO 8601 UTC with 3 fractional
digits; absent nullable fields serialize as JSON null.

Common fields (PRD §2.5): id, created_at, updated_at, version on every primary
resource; FormulationComponent carries id + created_at only."""

from store import iso


def _common(r):
    return {
        "id": r["id"],
        "created_at": iso(r["created_at"]),
        "updated_at": iso(r["updated_at"]),
        "version": r["version"],
    }


def jurisdiction(r):
    out = {
        "code": r["code"],
        "name": r["name"],
        "declaration_threshold_ppm": r["declaration_threshold_ppm"],
        "full_disclosure_threshold_ppm": r["full_disclosure_threshold_ppm"],
        "review_sla_days": r["review_sla_days"],
    }
    out.update(_common(r))
    return out


def substance(r):
    out = {
        "cas_number": r["cas_number"],
        "name": r["name"],
        "restriction_class": r["restriction_class"],
    }
    out.update(_common(r))
    return out


def formulation(r):
    out = {
        "product_code": r["product_code"],
        "name": r["name"],
        "base_polymer_family": r["base_polymer_family"],
        "status": r["status"],
        "revision_number": r["revision_number"],
        "successor_of_id": r["successor_of_id"],
        "active_clearance_count": r["active_clearance_count"],
        "discontinued_at": iso(r["discontinued_at"]),
        "ltb_deadline": iso(r["ltb_deadline"]),
        "last_ship_date": iso(r["last_ship_date"]),
        "ltb_pool_quantity": r["ltb_pool_quantity"],
        "ltb_pool_remaining": r["ltb_pool_remaining"],
    }
    out.update(_common(r))
    return out


def component(r):
    # Immutable join row: id + created_at only, no updated_at/version.
    return {
        "id": r["id"],
        "formulation_id": r["formulation_id"],
        "substance_id": r["substance_id"],
        "concentration_ppm": r["concentration_ppm"],
        "created_at": iso(r["created_at"]),
    }


def clearance(r):
    out = {
        "formulation_id": r["formulation_id"],
        "jurisdiction_id": r["jurisdiction_id"],
        "disclosure_package_level": r["disclosure_package_level"],
        "required_disclosure_level": r["required_disclosure_level"],
        "status": r["status"],
        "submission_count": r["submission_count"],
        "decided_by": r["decided_by"],
        "decided_at": iso(r["decided_at"]),
    }
    out.update(_common(r))
    return out


def converter(r):
    out = {
        "name": r["name"],
        "home_territory_code": r["home_territory_code"],
        "status": r["status"],
        "quality_audit_score": r["quality_audit_score"],
        "audit_standard": r["audit_standard"],
        "audited_by": r["audited_by"],
    }
    out.update(_common(r))
    return out


def distributor(r):
    out = {
        "name": r["name"],
        "home_territory_code": r["home_territory_code"],
    }
    out.update(_common(r))
    return out


def authorization(r):
    out = {
        "converter_id": r["converter_id"],
        "capability": r["capability"],
        "territory_code": r["territory_code"],
        "valid_from": iso(r["valid_from"]),
        "valid_to": iso(r["valid_to"]),
    }
    out.update(_common(r))
    return out


def application_case(r):
    out = {
        "formulation_id": r["formulation_id"],
        "customer_ref": r["customer_ref"],
        "substrate_class": r["substrate_class"],
        "application_description": r["application_description"],
        "status": r["status"],
        "failure_count": r["failure_count"],
        "bench_id": r["bench_id"],
        "bench_date": iso(r["bench_date"]),
        "bench_hours": r["bench_hours"],
        "peel_strength_n_per_25mm": r["peel_strength_n_per_25mm"],
        "test_temp_c": r["test_temp_c"],
        "test_standard": r["test_standard"],
        "pass_threshold_applied": r["pass_threshold_applied"],
    }
    out.update(_common(r))
    return out


def price_agreement(r):
    out = {
        "formulation_id": r["formulation_id"],
        "jurisdiction_id": r["jurisdiction_id"],
        "converter_id": r["converter_id"],
        "distributor_id": r["distributor_id"],
        "tier": r["tier"],
        "base_price_cents": r["base_price_cents"],
        "volume_breakpoints": [dict(bp) for bp in r["volume_breakpoints"]],
        "effective_from": iso(r["effective_from"]),
        "effective_to": iso(r["effective_to"]),
    }
    out.update(_common(r))
    return out


def order(r):
    out = {
        "agreement_id": r["agreement_id"],
        "converter_id": r["converter_id"],
        "distributor_id": r["distributor_id"],
        "formulation_id": r["formulation_id"],
        "ship_to_jurisdiction_id": r["ship_to_jurisdiction_id"],
        "quantity": r["quantity"],
        "requested_ship_date": iso(r["requested_ship_date"]),
        "intended_capability": r["intended_capability"],
        "lot_code": r["lot_code"],
        "unit_price_cents": r["unit_price_cents"],
        "line_total_cents": r["line_total_cents"],
        "is_ltb_order": r["is_ltb_order"],
        "fulfillment_status": r["fulfillment_status"],
        "compliance_status": r["compliance_status"],
        "shipped_at": iso(r["shipped_at"]),
        "flagged_by_report_id": r["flagged_by_report_id"],
    }
    out.update(_common(r))
    return out


def rebate_program(r):
    out = {
        "formulation_id": r["formulation_id"],
        "partner_type": r["partner_type"],
        "converter_id": r["converter_id"],
        "distributor_id": r["distributor_id"],
        "period_start": iso(r["period_start"]),
        "period_end": iso(r["period_end"]),
        "rebate_tiers": [dict(t) for t in r["rebate_tiers"]],
        "budget_cap_cents": r["budget_cap_cents"],
        "status": r["status"],
        "created_by": r["created_by"],
        "paid_out_cents": r["paid_out_cents"],
    }
    out.update(_common(r))
    return out


def rebate_accrual(r):
    out = {
        "program_id": r["program_id"],
        "converter_id": r["converter_id"],
        "distributor_id": r["distributor_id"],
        "provisional_amount_cents": r["provisional_amount_cents"],
        "final_amount_cents": r["final_amount_cents"],
        "excluded_order_count": r["excluded_order_count"],
        "status": r["status"],
    }
    out.update(_common(r))
    return out


def phaseout_program(r):
    out = {
        "substance_id": r["substance_id"],
        "jurisdiction_codes": list(r["jurisdiction_codes"]),
        "trigger_concentration_ppm": r["trigger_concentration_ppm"],
        "status": r["status"],
        "successor_formulation_id": r["successor_formulation_id"],
        "qualified_customers": list(r["qualified_customers"]),
        "qualified_customer_count": r["qualified_customer_count"],
    }
    out.update(_common(r))
    return out


def counterfeit_report(r):
    out = {
        "formulation_id": r["formulation_id"],
        "lot_code": r["lot_code"],
        "channel_description": r["channel_description"],
        "implicated_converter_id": r["implicated_converter_id"],
        "reporter_role": r["reporter_role"],
        "status": r["status"],
        "investigator_note": r["investigator_note"],
    }
    out.update(_common(r))
    return out
