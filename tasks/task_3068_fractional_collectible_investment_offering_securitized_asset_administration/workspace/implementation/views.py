"""Response views — exact field ordering per the entity table (§1.1)."""
from calc import (
    day_gap, value_per_share, bps_floor, management_fee, presentation_amount,
    preferred_return,
)
from store import parse_dt, to_ms
from models import newest_appraisal, vetted_appraisal
from catalog import DAYS_PER_YEAR

COMMON = ["id", "created_at", "updated_at", "version"]


def base(row, fields, common=True):
    out = {}
    if common:
        out["id"] = row["id"]
        out["created_at"] = row["created_at"]
        out["updated_at"] = row.get("updated_at")
    for name in fields:
        out[name] = row.get(name)
    if common:
        out["version"] = row.get("version")
    return out


def artist(row):
    return base(row, ["legal_name", "attribution_status", "nationality_country_code",
                      "birth_year", "death_year", "catalogue_raisonne_published"])


def investor(row):
    return base(row, ["email", "legal_name", "password", "citizenship_country_code",
                      "residency_country_code", "residency_state_code", "birth_date",
                      "suitability_status", "suitability_verified_at",
                      "suitability_expires_at", "is_accredited", "annual_income_cents",
                      "net_worth_cents", "affiliated_with_issuer", "restriction_until",
                      "lifetime_invested_cents"])


def artwork(row):
    return base(row, ["title", "artist_id", "creation_year", "medium",
                      "condition_grade", "acquisition_cost_cents",
                      "reserve_price_cents", "status", "last_appraised_value_cents",
                      "last_appraisal_at", "next_appraisal_due_at", "artifacts_overview"])


def asset_report(row):
    out = {"id": row["id"], "created_at": row["created_at"]}
    out.update({
        "artwork_id": row["artwork_id"],
        "report_type": row["report_type"],
        "outcome": row["outcome"],
        "firm_name": row["firm_name"],
        "condition_grade": row.get("condition_grade"),
        "filed_at": row["filed_at"],
    })
    return out


def appraisal(row):
    out = {"id": row["id"], "created_at": row["created_at"]}
    out.update({
        "artwork_id": row["artwork_id"],
        "appraised_value_cents": row["appraised_value_cents"],
        "appraiser_firm": row["appraiser_firm"],
        "appraisal_method": row["appraisal_method"],
        "filed_at": row["filed_at"],
        "is_selected": bool(row.get("is_selected")),
    })
    return out


def offering(row):
    return base(row, ["artwork_id", "total_shares", "price_per_share_cents",
                      "gross_proceeds_cents", "exemption_type", "registration_cap_pct",
                      "liquidity_ratio_bps", "hold_period_days",
                      "holding_clock_started_at", "holding_period_end_at",
                      "management_fee_bps", "profit_participation_bps",
                      "cost_pass_through_bps", "preferred_return_bps", "status",
                      "circular_filed_at", "qualification_deadline_at",
                      "accepted_shares", "unsubscribed_shares", "reserved_shares",
                      "cash_ledger_cents", "custody_cost_ledger_cents"])


def subscription(row):
    return base(row, ["offering_id", "investor_id", "requested_shares",
                      "accepted_shares", "amount_due_cents",
                      "collected_subscription_cents", "refunded_cents",
                      "waitlist_rank", "status", "created_at_seq"])


def custody_record(row):
    return base(row, ["offering_id", "custodian_name", "facility_code", "is_freeport",
                      "custodian_dea_registered", "status", "custody_started_at",
                      "custody_ended_at"])


def holding_decision(row):
    return base(row, ["offering_id", "decision_type", "status", "proposed_gross_cents",
                      "executed_gross_cents", "created_by_user_id",
                      "approved_by_user_id"])


def transfer_order(row):
    return base(row, ["offering_id", "seller_id", "shares", "limit_price_cents",
                      "bid_price_cents", "buyer_id", "execution_price_cents", "status",
                      "created_by_user_id"])


def lot(row):
    return base(row, ["offering_id", "lot_type", "cost_amount_cents", "incurred_on",
                      "pass_through_allowed", "pass_through_amount_cents"])


def policy(row):
    return base(row, ["offering_id", "carrier_name", "coverage_cents",
                      "annual_premium_cents", "status"])


def report(row):
    out = {"id": row["id"], "created_at": row["created_at"]}
    out.update({
        "offering_id": row["offering_id"],
        "report_kind": row["report_kind"],
        "as_of_date": row["as_of_date"],
        "filed_at": row["filed_at"],
        "shareholder_count": row.get("shareholder_count"),
        "value_per_share_cents": row.get("value_per_share_cents"),
        "is_quarter_marker": bool(row.get("is_quarter_marker")),
    })
    return out


def accrual(row):
    out = {"id": row["id"], "created_at": row["created_at"]}
    out.update({
        "offering_id": row["offering_id"],
        "accrual_type": row["accrual_type"],
        "basis_value_cents": row["basis_value_cents"],
        "amount_cents": row["amount_cents"],
        "presentation_amount_cents": row.get("presentation_amount_cents"),
        "settle_amount_cents": row.get("settle_amount_cents"),
        "accrued_at": row["accrued_at"],
    })
    return out


def distribution(row):
    out = {"id": row["id"], "created_at": row["created_at"]}
    out.update({
        "offering_id": row["offering_id"],
        "sale_gross_cents": row["sale_gross_cents"],
        "distributable_cents": row["distributable_cents"],
        "distributed_cost_cents": row["distributed_cost_cents"],
        "management_fee_cents": row["management_fee_cents"],
        "profit_participation_cents": row["profit_participation_cents"],
        "preferred_return_cents": row.get("preferred_return_cents"),
        "investor_residual_cents": row["investor_residual_cents"],
        "per_share_cents": row["per_share_cents"],
        "remainder_cents": row.get("remainder_cents"),
        "status": row["status"],
    })
    return out


def platform_account(row):
    return base(row, ["account_name", "balance_cents", "investor_funds_held_cents",
                      "total_paid_out_cents"])


VIEW = {
    "artists": artist, "investors": investor, "artworks": artwork,
    "asset_reports": asset_report, "appraisals": appraisal, "offerings": offering,
    "subscriptions": subscription, "custody_records": custody_record,
    "holding_decisions": holding_decision, "transfer_orders": transfer_order,
    "lots": lot, "insurance_policies": policy, "offering_reports": report,
    "fee_accruals": accrual, "distributions": distribution,
    "platform_accounts": platform_account,
}


def view(kind, row):
    if row is None:
        return None
    return VIEW[kind](row)


# ---------------------------------------------------------------------------
# valuation variants
# ---------------------------------------------------------------------------

def valuation(offering):
    artwork_row = None
    from store import DB
    artwork_row = DB.artworks.get(offering["artwork_id"])
    total = int(offering["total_shares"])
    legacy_row = newest_appraisal(offering["artwork_id"])
    restated_row = vetted_appraisal(offering["artwork_id"])
    legacy_basis = legacy_row["appraised_value_cents"] if legacy_row else 0
    restated_basis = restated_row["appraised_value_cents"] if restated_row else 0
    legacy = value_per_share(legacy_basis, total)
    restated = value_per_share(restated_basis, total)
    return {
        "legacy_value_per_share_cents": legacy,
        "restated_value_per_share_cents": restated,
        "valuation_delta_cents": legacy - restated,
        "valuation_basis_filed_at": legacy_row["filed_at"] if legacy_row else None,
    }


def holding_days_pair(offering):
    """(presentation_days, settle_days) — off-by-one readings of §1.3."""
    start = parse_dt(offering.get("holding_clock_started_at"))
    end = parse_dt(offering.get("holding_period_end_at"))
    if start is None or end is None:
        return None, None
    plain = (end - start).days
    return plain, plain + 1


def accrued_management(offering, artwork_row):
    presentation_days, settle_days = holding_days_pair(offering)
    if presentation_days is None:
        return 0, 0, 0
    value = int(artwork_row.get("last_appraised_value_cents") or 0)
    pres = presentation_amount(value, offering["management_fee_bps"], presentation_days)
    settle = management_fee(value, offering["management_fee_bps"], settle_days)
    return value, pres, settle


def held_for_days_now(offering):
    start = parse_dt(offering.get("holding_clock_started_at"))
    if start is None:
        return 0
    from store import DB
    return (parse_dt(DB.now()) - start).days