"""Entity serializers. Housekeeping fields (created_at/updated_at) render with
exactly three fractional digits; domain datetimes render exactly as the
logical clock reads (PRD §2.5)."""
from store import render_house, render_domain


def _common(e, out):
    out["id"] = e["id"]
    out["created_at"] = render_house(e["created_at"])
    out["updated_at"] = render_house(e["updated_at"])
    out["version"] = e["version"]
    return out


def band_plan(e):
    return _common(e, {
        "band_name": e["band_name"],
        "frequency_start_mhz": e["frequency_start_mhz"],
        "frequency_end_mhz": e["frequency_end_mhz"],
        "technical_rules": e["technical_rules"],
        "status": e["status"],
    })


def license_area(e):
    return _common(e, {
        "band_plan_id": e["band_plan_id"],
        "area_code": e["area_code"],
        "name": e["name"],
        "population": e["population"],
    })


def license_block(e):
    return _common(e, {
        "band_plan_id": e["band_plan_id"],
        "category": e["category"],
        "mhz_size": e["mhz_size"],
        "supply_per_area": e["supply_per_area"],
        "price_per_mhz_pop_cents": e["price_per_mhz_pop_cents"],
    })


def auction(e):
    return _common(e, {
        "band_plan_id": e["band_plan_id"],
        "name": e["name"],
        "application_deadline": render_domain(e["application_deadline"]),
        "status": e["status"],
        "current_round_number": e["current_round_number"],
        "total_proceeds_cents": e["total_proceeds_cents"],
        "forfeited_deposits_cents": e["forfeited_deposits_cents"],
        "available_supply": [dict(x) for x in e["available_supply"]],
    })


def applicant(e):
    return _common(e, {
        "auction_id": e["auction_id"],
        "legal_name": e["legal_name"],
        "claims_small_business": e["claims_small_business"],
        "claims_rural_credit": e["claims_rural_credit"],
        "own_annual_revenue_cents": e["own_annual_revenue_cents"],
        "service_population": e["service_population"],
        "ownership_interests": [dict(x) for x in e["ownership_interests"]],
        "attributable_revenue_cents": e["attributable_revenue_cents"],
        "credit_pct": e["credit_pct"],
        "upfront_paid_cents": e["upfront_paid_cents"],
        "upfront_held_cents": e["upfront_held_cents"],
        "upfront_refunded_cents": e["upfront_refunded_cents"],
        "upfront_forfeited_cents": e["upfront_forfeited_cents"],
        "eligibility_units": e["eligibility_units"],
        "initial_eligibility_units": e["initial_eligibility_units"],
        "status": e["status"],
    })


def clock_round(e):
    return _common(e, {
        "auction_id": e["auction_id"],
        "round_number": e["round_number"],
        "stage": e["stage"],
        "prices": [dict(x) for x in e["prices"]],
        "aggregate_demand": [dict(x) for x in e["aggregate_demand"]],
        "status": e["status"],
    })


def bid(e):
    return _common(e, {
        "round_id": e["round_id"],
        "bidder_applicant_id": e["bidder_applicant_id"],
        "area_code": e["area_code"],
        "category": e["category"],
        "quantity": e["quantity"],
        "units_snapshot": e["units_snapshot"],
        "status": e["status"],
    })


def assignment_bid(e):
    return _common(e, {
        "auction_id": e["auction_id"],
        "bidder_applicant_id": e["bidder_applicant_id"],
        "area_code": e["area_code"],
        "category": e["category"],
        "amount_cents": e["amount_cents"],
        "status": e["status"],
    })


def license_(e):
    return _common(e, {
        "auction_id": e["auction_id"],
        "area_id": e["area_id"],
        "area_code": e["area_code"],
        "category": e["category"],
        "frequency_block_index": e["frequency_block_index"],
        "holder_applicant_id": e["holder_applicant_id"],
        "credit_pct": e["credit_pct"],
        "gross_clock_price_cents": e["gross_clock_price_cents"],
        "assignment_bid_cents": e["assignment_bid_cents"],
        "gross_final_price_cents": e["gross_final_price_cents"],
        "provisional_net_price_cents": e["provisional_net_price_cents"],
        "net_price_cents": e["net_price_cents"],
        "credit_amount_cents": e["credit_amount_cents"],
        "paid_cents": e["paid_cents"],
        "grant_date": render_domain(e["grant_date"]),
        "term_end": render_domain(e["term_end"]),
        "payment_deadline": render_domain(e["payment_deadline"]),
        "active_lease_start": render_domain(e["active_lease_start"]),
        "active_lease_end": render_domain(e["active_lease_end"]),
        "leased_to_applicant_id": e["leased_to_applicant_id"],
        "relocation_share_owed_cents": e["relocation_share_owed_cents"],
        "status": e["status"],
    })


def milestone(e):
    return _common(e, {
        "license_id": e["license_id"],
        "milestone_type": e["milestone_type"],
        "due_date": render_domain(e["due_date"]),
        "required_coverage_pct": e["required_coverage_pct"],
        "covered_population": e["covered_population"],
        "status": e["status"],
    })


def transfer(e):
    return _common(e, {
        "license_id": e["license_id"],
        "transferor_applicant_id": e["transferor_applicant_id"],
        "transferee_applicant_id": e["transferee_applicant_id"],
        "transfer_type": e["transfer_type"],
        "lease_start": render_domain(e["lease_start"]),
        "lease_end": render_domain(e["lease_end"]),
        "unjust_enrichment_cents": e["unjust_enrichment_cents"],
        "status": e["status"],
    })


def incumbent(e):
    return _common(e, {
        "band_plan_id": e["band_plan_id"],
        "area_id": e["area_id"],
        "callsign": e["callsign"],
        "relocation_cost_cents": e["relocation_cost_cents"],
        "transition_window_start": render_domain(e["transition_window_start"]),
        "transition_window_end": render_domain(e["transition_window_end"]),
        "shares_proportional": (
            None if e["shares_proportional"] is None
            else [dict(x) for x in e["shares_proportional"]]),
        "shares_equal": (
            None if e["shares_equal"] is None
            else [dict(x) for x in e["shares_equal"]]),
        "status": e["status"],
    })


def renewal(e):
    return _common(e, {
        "license_id": e["license_id"],
        "status": e["status"],
    })
