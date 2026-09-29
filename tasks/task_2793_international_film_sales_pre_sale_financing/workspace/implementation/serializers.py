"""Row -> JSON projections. Territories, comparable titles and distribution
runs carry neither updated_at nor version at all (PRD 2.4)."""
from __future__ import annotations

import calc
from util import iso, money_out, num_out, pct4_out


def _common(row, payload):
    payload["created_at"] = iso(row["created_at"])
    if "version" in row:
        payload["updated_at"] = iso(row["updated_at"])
        payload["version"] = row["version"]
    return payload


def film_out(row):
    counters = calc.film_counters(row)
    return _common(
        row,
        {
            "id": row["id"],
            "title": row["title"],
            "genre": row["genre"],
            "production_budget_usd": money_out(row["production_budget_usd"]),
            "principal_cast_score": row["principal_cast_score"],
            "completion_status": row["completion_status"],
            "estimated_delivery_date": iso(row["estimated_delivery_date"]),
            "theatrical_release_date": iso(row["theatrical_release_date"]),
            "sales_status": row["sales_status"],
            "total_mg_committed_usd": money_out(counters["total_mg_committed_usd"]),
            "total_mg_collected_usd": money_out(counters["total_mg_collected_usd"]),
            "financing_gap_usd": money_out(counters["financing_gap_usd"]),
            "published_territory_count": counters["published_territory_count"],
            "licensed_territory_count": counters["licensed_territory_count"],
        },
    )


def agreement_out(row):
    return _common(
        row,
        {
            "id": row["id"],
            "film_id": row["film_id"],
            "commission_pct": num_out(row["commission_pct"]),
            "expense_cap_usd": money_out(row["expense_cap_usd"]),
            "term_months": row["term_months"],
            "term_start_date": iso(row["term_start_date"]),
            "term_end_date": iso(row["term_end_date"]),
            "status": row["status"],
            "expenses_incurred_usd": money_out(row["expenses_incurred_usd"]),
            "expenses_recouped_usd": money_out(row["expenses_recouped_usd"]),
            "commission_earned_usd": money_out(row["commission_earned_usd"]),
            "gross_collected_usd": money_out(row["gross_collected_usd"]),
            "executed_by_user_id": row["executed_by_user_id"],
        },
    )


def territory_out(row):
    return _common(
        row,
        {
            "id": row["id"],
            "code": row["code"],
            "name": row["name"],
            "region": row["region"],
            "market_tier": row["market_tier"],
            "currency_code": row["currency_code"],
            "base_value_index": num_out(row["base_value_index"]),
        },
    )


def comparable_out(row):
    return _common(
        row,
        {
            "id": row["id"],
            "territory_id": row["territory_id"],
            "name": row["name"],
            "genre": row["genre"],
            "cast_score": row["cast_score"],
            "gross_license_fee_usd": money_out(row["gross_license_fee_usd"]),
            "release_year": row["release_year"],
            "verified": row["verified"],
        },
    )


def valuation_out(row):
    return _common(
        row,
        {
            "id": row["id"],
            "film_id": row["film_id"],
            "territory_id": row["territory_id"],
            "method": row["method"],
            "comp_sample_size": row["comp_sample_size"],
            "comp_median_usd": money_out(row["comp_median_usd"]),
            "cast_multiplier": num_out(row["cast_multiplier"]),
            "estimate_usd": money_out(row["estimate_usd"]),
            "ask_price_usd": money_out(row["ask_price_usd"]),
            "floor_price_usd": money_out(row["floor_price_usd"]),
            "status": row["status"],
            "published_by_user_id": row["published_by_user_id"],
            "published_at": iso(row["published_at"]),
        },
    )


def market_out(row):
    return _common(
        row,
        {
            "id": row["id"],
            "name": row["name"],
            "city": row["city"],
            "start_date": iso(row["start_date"]),
            "end_date": iso(row["end_date"]),
            "screening_room_count": row["screening_room_count"],
            "meeting_table_count": row["meeting_table_count"],
            "status": row["status"],
        },
    )


def slot_out(row):
    return _common(
        row,
        {
            "id": row["id"],
            "market_id": row["market_id"],
            "film_id": row["film_id"],
            "room_number": row["room_number"],
            "start_at": iso(row["start_at"]),
            "end_at": iso(row["end_at"]),
            "slot_type": row["slot_type"],
            "capacity": row["capacity"],
            "status": row["status"],
        },
    )


def buyer_out(row):
    return _common(
        row,
        {
            "id": row["id"],
            "territory_id": row["territory_id"],
            "company_name": row["company_name"],
            "credit_rating": row["credit_rating"],
            "exposure_limit_usd": money_out(row["exposure_limit_usd"]),
            "status": row["status"],
            "outstanding_exposure_usd": money_out(
                calc.buyer_gross_exposure(row["id"])
            ),
            "net_unpaid_exposure_usd": money_out(
                calc.buyer_net_unpaid_exposure(row["id"])
            ),
        },
    )


def meeting_out(row):
    return _common(
        row,
        {
            "id": row["id"],
            "market_id": row["market_id"],
            "buyer_id": row["buyer_id"],
            "film_id": row["film_id"],
            "table_number": row["table_number"],
            "start_at": iso(row["start_at"]),
            "end_at": iso(row["end_at"]),
            "duration_minutes": row["duration_minutes"],
            "status": row["status"],
            "outcome": row["outcome"],
        },
    )


def contract_out(row):
    return _common(
        row,
        {
            "id": row["id"],
            "film_id": row["film_id"],
            "buyer_id": row["buyer_id"],
            "territory_id": row["territory_id"],
            "minimum_guarantee_usd": money_out(row["minimum_guarantee_usd"]),
            "license_term_months": row["license_term_months"],
            "holdback_days": row["holdback_days"],
            "negotiation_round": row["negotiation_round"],
            "negotiation_status": row["negotiation_status"],
            "delivery_status": row["delivery_status"],
            "collection_status": row["collection_status"],
            "counter_minimum_guarantee_usd": money_out(
                row["counter_minimum_guarantee_usd"]
            ),
            "license_start_date": iso(row["license_start_date"]),
            "license_end_date": iso(row["license_end_date"]),
            "holdback_release_date": iso(row["holdback_release_date"]),
            "offered_by_user_id": row["offered_by_user_id"],
            "executed_by_user_id": row["executed_by_user_id"],
            "milestone_pct_total": pct4_out(calc.contract_pct_total(row["id"])),
            "unpaid_amount_usd": money_out(calc.contract_unpaid(row["id"])),
            "received_amount_usd": money_out(calc.contract_received(row["id"])),
        },
    )


def milestone_out(row):
    return _common(
        row,
        {
            "id": row["id"],
            "contract_id": row["contract_id"],
            "label": row["label"],
            "pct_of_mg": pct4_out(row["pct_of_mg"]),
            "amount_usd": money_out(row["amount_usd"]),
            "due_date": iso(row["due_date"]),
            "status": row["status"],
            "received_at": iso(row["received_at"]),
            "received_amount_usd": money_out(row["received_amount_usd"]),
            "received_by_user_id": row["received_by_user_id"],
            "accrued_commission_usd": money_out(row["accrued_commission_usd"]),
        },
    )


def package_out(row):
    return _common(
        row,
        {
            "id": row["id"],
            "contract_id": row["contract_id"],
            "technical_items_count": row["technical_items_count"],
            "legal_items_count": row["legal_items_count"],
            "revision_round": row["revision_round"],
            "submitted_at": iso(row["submitted_at"]),
            "status": row["status"],
            "qc_result": row["qc_result"],
            "rejection_reason": row["rejection_reason"],
            "cure_deadline": iso(row["cure_deadline"]),
            "submitted_by_user_id": row["submitted_by_user_id"],
        },
    )


def facility_out(row):
    return _common(
        row,
        {
            "id": row["id"],
            "film_id": row["film_id"],
            "lender_name": row["lender_name"],
            "discount_rate_pct": num_out(row["discount_rate_pct"]),
            "advance_rate_pct": num_out(row["advance_rate_pct"]),
            "facility_cap_usd": money_out(row["facility_cap_usd"]),
            "completion_bond_required": row["completion_bond_required"],
            "completion_bond_posted": row["completion_bond_posted"],
            "bond_provider": row["bond_provider"],
            "bond_amount_usd": money_out(row["bond_amount_usd"]),
            "eligible_collateral_usd": money_out(row["eligible_collateral_usd"]),
            "advance_amount_usd": money_out(row["advance_amount_usd"]),
            "drawn_amount_usd": money_out(row["drawn_amount_usd"]),
            "outstanding_debt_usd": money_out(row["outstanding_debt_usd"]),
            "status": row["status"],
            "approved_by_user_id": row["approved_by_user_id"],
        },
    )


def account_out(row):
    return _common(
        row,
        {
            "id": row["id"],
            "film_id": row["film_id"],
            "bank_name": row["bank_name"],
            "account_reference": row["account_reference"],
            "balance_usd": money_out(calc.account_balance(row)),
            "total_receipts_usd": money_out(row["total_receipts_usd"]),
            "total_distributed_usd": money_out(row["total_distributed_usd"]),
            "run_count": row["run_count"],
            "status": row["status"],
        },
    )


def tier_out(row):
    return _common(
        row,
        {
            "id": row["id"],
            "account_id": row["account_id"],
            "tier_order": row["tier_order"],
            "tier_type": row["tier_type"],
            "recipient_name": row["recipient_name"],
            "pct_of_available": num_out(row["pct_of_available"]),
            "cap_usd": money_out(row["cap_usd"]),
            "recouped_usd": money_out(row["recouped_usd"]),
            "status": calc.tier_status(row),
        },
    )


def run_out(row):
    return _common(
        row,
        {
            "id": row["id"],
            "account_id": row["account_id"],
            "run_index": row["run_index"],
            "amount_in_usd": money_out(row["amount_in_usd"]),
            "amount_allocated_usd": money_out(row["amount_allocated_usd"]),
            "residual_usd": money_out(row["residual_usd"]),
            "allocations": [
                {
                    "tier_id": entry["tier_id"],
                    "tier_type": entry["tier_type"],
                    "recipient_name": entry["recipient_name"],
                    "amount_usd": money_out(entry["amount_usd"]),
                }
                for entry in row["allocations"]
            ],
            "run_by_user_id": row["run_by_user_id"],
        },
    )
