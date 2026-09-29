"""Resource representations.  Derived fields are computed at read time."""

from numeric import out_num
from services import derive
from timeutil import iso


def _common(rec, versioned=True):
    out = {"id": rec["id"], "created_at": iso(rec["created_at"])}
    if versioned:
        out["updated_at"] = iso(rec["updated_at"])
        out["version"] = rec["version"]
    return out


def advertiser(rec):
    out = {
        "name": rec["name"],
        "category_code": rec["category_code"],
        "payment_terms_days": rec["payment_terms_days"],
        "sequential_liability_enabled": rec["sequential_liability_enabled"],
        "credit_limit_cents": rec["credit_limit_cents"],
        "credit_status": rec["credit_status"],
        "late_payment_count": rec["late_payment_count"],
        "outstanding_receivable_cents": derive.outstanding_receivable_cents(rec),
    }
    out.update(_common(rec))
    return out


def campaign(rec):
    view = derive.campaign_view(rec)
    out = {
        "advertiser_id": rec["advertiser_id"],
        "name": rec["name"],
        "target_demo": rec["target_demo"],
        "universe_thousands": rec["universe_thousands"],
        "reach_goal_pct": out_num(rec["reach_goal_pct"]),
        "frequency_goal": out_num(rec["frequency_goal"]),
        "total_budget_cents": rec["total_budget_cents"],
        "flight_start": iso(rec["flight_start"]),
        "flight_end": iso(rec["flight_end"]),
        "fiscal_quarter": rec["fiscal_quarter"],
        "plan_status": rec["plan_status"],
        "funding_status": rec["funding_status"],
        "plan_posture": view["plan_posture"],
        "funded_cents": rec["funded_cents"],
        "allocated_budget_cents": view["allocated_budget_cents"],
        "unallocated_budget_cents": view["unallocated_budget_cents"],
        "committed_gross_cents": view["committed_gross_cents"],
        "uncommitted_budget_cents": view["uncommitted_budget_cents"],
        "planned_impressions_total": view["planned_impressions_total"],
        "planned_grp_total": out_num(view["planned_grp_total"]),
    }
    out.update(_common(rec))
    return out


def allocation(rec):
    view = derive.allocation_view(rec)
    out = {
        "campaign_id": rec["campaign_id"],
        "channel": rec["channel"],
        "allocation_pct": out_num(rec["allocation_pct"]),
        "planned_cpm_cents": rec["planned_cpm_cents"],
        "planned_market": rec["planned_market"],
        "primary_daypart": rec["primary_daypart"],
        "allocated_cents": view["allocated_cents"],
        "effective_planned_cpm_cents": view["effective_planned_cpm_cents"],
        "planned_impressions": view["planned_impressions"],
        "planned_grp": out_num(view["planned_grp"]),
        "planned_frequency": out_num(view["planned_frequency"]),
        "committed_cents": view["committed_cents"],
        "posture": view["posture"],
        "status": rec["status"],
    }
    out.update(_common(rec))
    return out


def seller(rec):
    exposure = derive.seller_exposure(rec)
    out = {
        "name": rec["name"],
        "platform_types": list(rec["platform_types"]),
        "make_good_capacity_impressions": rec["make_good_capacity_impressions"],
        "open_make_good_impressions": exposure["open_make_good_impressions"],
        "scheduled_make_good_impressions": exposure["scheduled_make_good_impressions"],
    }
    out.update(_common(rec))
    return out


def forecast(rec):
    out = {
        "seller_id": rec["seller_id"],
        "market": rec["market"],
        "fiscal_quarter": rec["fiscal_quarter"],
        "daypart": rec["daypart"],
        "program": rec["program"],
        "platform": rec["platform"],
        "window_start": iso(rec["window_start"]),
        "window_end": iso(rec["window_end"]),
        "total_impressions": rec["total_impressions"],
        "available_impressions": derive.available_impressions(rec),
        "forecast_cpm_cents": rec["forecast_cpm_cents"],
        "exclusivity_mode": rec["exclusivity_mode"],
        "status": rec["status"],
    }
    out.update(_common(rec))
    return out


def negotiation(rec):
    out = {
        "campaign_id": rec["campaign_id"],
        "seller_id": rec["seller_id"],
        "channel_allocation_id": rec["channel_allocation_id"],
        "market": rec["market"],
        "channel": rec["channel"],
        "requested_impressions": rec["requested_impressions"],
        "opening_cpm_cents": rec["opening_cpm_cents"],
        "guarantee_pct": out_num(rec["guarantee_pct"]),
        "make_good_provision": rec["make_good_provision"],
        "option_pct_ceiling": out_num(rec["option_pct_ceiling"]),
        "current_cpm_cents": rec["current_cpm_cents"],
        "current_impressions": rec["current_impressions"],
        "round_number": rec["round_number"],
        "last_offer_actor": rec["last_offer_actor"],
        "status": rec["status"],
        "accepted_cpm_cents": rec["accepted_cpm_cents"],
        "accepted_impressions": rec["accepted_impressions"],
        "withdraw_reason": rec["withdraw_reason"],
    }
    out.update(_common(rec))
    return out


def buy(rec):
    credits = derive.delivery_credits(rec)
    out = {
        "campaign_id": rec["campaign_id"],
        "seller_id": rec["seller_id"],
        "negotiation_id": rec["negotiation_id"],
        "channel_allocation_id": rec["channel_allocation_id"],
        "market": rec["market"],
        "channel": rec["channel"],
        "guaranteed_impressions": rec["guaranteed_impressions"],
        "agreed_cpm_cents": rec["agreed_cpm_cents"],
        "net_media_cost_cents": rec["net_media_cost_cents"],
        "commission_rate": out_num(rec["commission_rate"]),
        "agency_commission_cents": rec["agency_commission_cents"],
        "gross_cost_cents": rec["gross_cost_cents"],
        "placed_impressions": derive.placed_impressions(rec),
        "credited_impressions_provisional": credits["credited_impressions_provisional"],
        "credited_impressions_final": credits["credited_impressions_final"],
        "provisional_delivery_index": out_num(credits["provisional_delivery_index"]),
        "final_delivery_index": out_num(credits["final_delivery_index"]),
        "open_shortfall_impressions": derive.open_shortfall_impressions(rec),
        "made_good_impressions": rec["made_good_impressions"],
        "waived_impressions": rec["waived_impressions"],
        "buy_status": rec["buy_status"],
        "stewardship_status": rec["stewardship_status"],
        "settlement_status": rec["settlement_status"],
        "flight_start": iso(rec["flight_start"]),
        "flight_end": iso(rec["flight_end"]),
        "option_window_close": iso(rec["option_window_close"]),
        "cancel_window_1_close": iso(rec["cancel_window_1_close"]),
        "cancel_window_2_close": iso(rec["cancel_window_2_close"]),
        "option_pct_ceiling": out_num(rec["option_pct_ceiling"]),
        "cancelled_pct_cumulative": out_num(derive.cumulative_pct(rec, "CANCELLATION")),
        "option_pct_cumulative": out_num(derive.cumulative_pct(rec, "OPTION_ROLL")),
        "make_good_provision": rec["make_good_provision"],
        "placed_by_user_id": rec["placed_by_user_id"],
    }
    out.update(_common(rec))
    return out


def buy_unit(rec):
    out = {
        "buy_id": rec["buy_id"],
        "forecast_id": rec["forecast_id"],
        "make_good_id": rec["make_good_id"],
        "daypart": rec["daypart"],
        "program": rec["program"],
        "platform": rec["platform"],
        "units": rec["units"],
        "unit_rate_cents": rec["unit_rate_cents"],
        "projected_impressions": rec["projected_impressions"],
        "actual_impressions": rec["actual_impressions"],
        "air_window_start": iso(rec["air_window_start"]),
        "air_window_end": iso(rec["air_window_end"]),
        "exclusive": rec["exclusive"],
        "line_net_cents": rec["line_net_cents"],
        "line_commission_cents": rec["line_commission_cents"],
        "line_gross_cents": rec["line_gross_cents"],
        "status": rec["status"],
    }
    out.update(_common(rec))
    return out


def delivery_report(rec):
    out = {
        "buy_id": rec["buy_id"],
        "measurement_basis": rec["measurement_basis"],
        "period_start": iso(rec["period_start"]),
        "period_end": iso(rec["period_end"]),
        "delivered_impressions": rec["delivered_impressions"],
        "delivered_demo_impressions": rec["delivered_demo_impressions"],
        "is_post_buy_final": rec["is_post_buy_final"],
        "dispute_reason": rec["dispute_reason"],
        "status": rec["status"],
    }
    out.update(_common(rec))
    return out


def make_good(rec):
    out = {
        "buy_id": rec["buy_id"],
        "offered_forecast_id": rec["offered_forecast_id"],
        "shortfall_impressions": rec["shortfall_impressions"],
        "shortfall_value_cents": rec["shortfall_value_cents"],
        "offered_impressions": rec["offered_impressions"],
        "offered_window_start": iso(rec["offered_window_start"]),
        "offered_window_end": iso(rec["offered_window_end"]),
        "offer_round": rec["offer_round"],
        "rejection_reason": rec["rejection_reason"],
        "waived_credit_cents": rec["waived_credit_cents"],
        "status": rec["status"],
    }
    out.update(_common(rec))
    return out


def rights_exercise(rec):
    out = {
        "buy_id": rec["buy_id"],
        "kind": rec["kind"],
        "requested_pct": out_num(rec["requested_pct"]),
        "applied_ceiling_pct": out_num(rec["applied_ceiling_pct"]),
        "delta_impressions": rec["delta_impressions"],
        "delta_gross_cents": rec["delta_gross_cents"],
        "cancelled_unit_count": rec["cancelled_unit_count"],
        "exercised_at": iso(rec["exercised_at"]),
        "exercised_by_user_id": rec["exercised_by_user_id"],
    }
    out.update(_common(rec, versioned=False))
    return out


def reconciliation_run(rec):
    out = {
        "campaign_id": rec["campaign_id"],
        "dedup_method": rec["dedup_method"],
        "aggregate_duplication_pct": out_num(rec["aggregate_duplication_pct"]),
        "linear_ctv_duplication_pct": out_num(rec["linear_ctv_duplication_pct"]),
        "ctv_digital_duplication_pct": out_num(rec["ctv_digital_duplication_pct"]),
        "linear_digital_duplication_pct": out_num(rec["linear_digital_duplication_pct"]),
        "group_reach_pct": {
            key: out_num(value) for key, value in rec["group_reach_pct"].items()
        },
        "gross_reach_pct_total": out_num(rec["gross_reach_pct_total"]),
        "unduplicated_reach_pct": out_num(rec["unduplicated_reach_pct"]),
        "implied_frequency": out_num(rec["implied_frequency"]),
        "included_report_count": rec["included_report_count"],
        "status": rec["status"],
        "computed_at": iso(rec["computed_at"]),
    }
    out.update(_common(rec, versioned=False))
    return out


def invoice(rec):
    out = {
        "buy_id": rec["buy_id"],
        "billing_period_start": iso(rec["billing_period_start"]),
        "billing_period_end": iso(rec["billing_period_end"]),
        "line_count": rec["line_count"],
        "gross_billable_cents": rec["gross_billable_cents"],
        "agency_commission_cents": rec["agency_commission_cents"],
        "seller_payable_cents": rec["seller_payable_cents"],
        "make_good_credit_cents": rec["make_good_credit_cents"],
        "net_payable_cents": rec["net_payable_cents"],
        "max_remittable_cents": rec["max_remittable_cents"],
        "client_paid_cents": rec["client_paid_cents"],
        "seller_remitted_cents": rec["seller_remitted_cents"],
        "due_date": iso(rec["due_date"]),
        "issued_at": iso(rec["issued_at"]),
        "late_payment_flag": rec["late_payment_flag"],
        "approver_user_id": rec["approver_user_id"],
        "client_status": rec["client_status"],
        "seller_status": rec["seller_status"],
    }
    out.update(_common(rec))
    return out


SERIALIZERS = {
    "advertisers": advertiser,
    "campaigns": campaign,
    "allocations": allocation,
    "sellers": seller,
    "forecasts": forecast,
    "negotiations": negotiation,
    "buys": buy,
    "units": buy_unit,
    "reports": delivery_report,
    "make_goods": make_good,
    "rights": rights_exercise,
    "runs": reconciliation_run,
    "invoices": invoice,
}


def serialize(collection, rec):
    return SERIALIZERS[collection](rec)
