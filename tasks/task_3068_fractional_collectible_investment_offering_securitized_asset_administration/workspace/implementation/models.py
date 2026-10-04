"""Entity construction — exact field sets from the entity table (§1.1)."""
from store import DB, to_ms, new_row, add_days
from catalog import (
    APPRAISAL_CADENCE_DAYS, QUALIFICATION_DEADLINE_DAYS, SUITABILITY_DAYS,
)
from calc import cadence_flag, day_gap


def make_artist(data):
    row = new_row({
        "legal_name": data.get("legal_name"),
        "attribution_status": data.get("attribution_status"),
        "nationality_country_code": data.get("nationality_country_code"),
        "birth_year": data.get("birth_year"),
        "death_year": data.get("death_year"),
        "catalogue_raisonne_published": bool(data.get("catalogue_raisonne_published") or False),
        "version": 1,
    })
    DB.register("artists", row)
    row["updated_at"] = row["created_at"]
    DB.artists[row["id"]] = row
    return row


def make_investor(data):
    row = new_row({
        "email": data.get("email"),
        "legal_name": data.get("legal_name"),
        "password": data.get("password"),
        "citizenship_country_code": data.get("citizenship_country_code"),
        "residency_country_code": data.get("residency_country_code"),
        "residency_state_code": data.get("residency_state_code"),
        "birth_date": data.get("birth_date"),
        "suitability_status": "PENDING",
        "suitability_verified_at": None,
        "suitability_expires_at": None,
        "is_accredited": bool(data.get("is_accredited") or False),
        "annual_income_cents": int(data.get("annual_income_cents") or 0),
        "net_worth_cents": int(data.get("net_worth_cents") or 0),
        "affiliated_with_issuer": bool(data.get("affiliated_with_issuer") or False),
        "restriction_until": None,
        "lifetime_invested_cents": 0,
        "version": 1,
    })
    DB.register("investors", row)
    row["restriction_until"] = row["created_at"]
    row["updated_at"] = row["created_at"]
    DB.investors[row["id"]] = row
    return row


def make_artwork(data):
    row = new_row({
        "title": data.get("title"),
        "artist_id": data.get("artist_id"),
        "creation_year": data.get("creation_year"),
        "medium": data.get("medium"),
        "condition_grade": "PENDING",
        "acquisition_cost_cents": int(data.get("acquisition_cost_cents") or 0),
        "reserve_price_cents": int(data.get("reserve_price_cents") or 0),
        "status": "APPRAISED",
        "last_appraised_value_cents": 0,
        "last_appraisal_at": None,
        "next_appraisal_due_at": None,
        "artifacts_overview": {},
        "version": 1,
    })
    DB.register("artworks", row)
    row["updated_at"] = row["created_at"]
    DB.artworks[row["id"]] = row
    refresh_overview(row, bump=False)
    row["version"] = 1
    return row


def make_asset_report(artwork, data):
    row = new_row({
        "artwork_id": artwork["id"],
        "report_type": data.get("report_type"),
        "outcome": data.get("outcome"),
        "firm_name": data.get("firm_name"),
        "condition_grade": data.get("condition_grade"),
        "filed_at": to_ms(DB.now()),
    })
    DB.register("asset_reports", row)
    DB.asset_reports[row["id"]] = row
    return row


def make_appraisal(artwork, data):
    row = new_row({
        "artwork_id": artwork["id"],
        "appraised_value_cents": int(data.get("appraised_value_cents") or 0),
        "appraiser_firm": data.get("appraiser_firm"),
        "appraisal_method": data.get("appraisal_method"),
        "filed_at": to_ms(DB.now()),
        "is_selected": True,
    })
    DB.register("appraisals", row)
    DB.appraisals[row["id"]] = row
    return row


def make_offering(artwork, data):
    total = int(data.get("total_shares") or 0)
    price = int(data.get("price_per_share_cents") or 0)
    row = new_row({
        "artwork_id": artwork["id"],
        "total_shares": total,
        "price_per_share_cents": price,
        "gross_proceeds_cents": total * price,
        "exemption_type": data.get("exemption_type"),
        "registration_cap_pct": int(data.get("registration_cap_pct") or 0),
        "liquidity_ratio_bps": int(data.get("liquidity_ratio_bps") or 0),
        "hold_period_days": int(data.get("hold_period_days") or 0),
        "holding_clock_started_at": None,
        "holding_period_end_at": None,
        "management_fee_bps": int(data.get("management_fee_bps") or 0),
        "profit_participation_bps": int(data.get("profit_participation_bps") or 0),
        "cost_pass_through_bps": int(data.get("cost_pass_through_bps") or 0),
        "preferred_return_bps": int(data.get("preferred_return_bps") or 0),
        "status": "DRAFT",
        "circular_filed_at": None,
        "qualification_deadline_at": None,
        "accepted_shares": 0,
        "unsubscribed_shares": total,
        "reserved_shares": 0,
        "cash_ledger_cents": 0,
        "custody_cost_ledger_cents": 0,
        "version": 1,
    })
    DB.register("offerings", row)
    row["updated_at"] = row["created_at"]
    DB.offerings[row["id"]] = row
    return row


def make_subscription(offering, data):
    row = new_row({
        "offering_id": offering["id"],
        "investor_id": data.get("investor_id"),
        "requested_shares": int(data.get("requested_shares") or 0),
        "accepted_shares": 0,
        "amount_due_cents": 0,
        "collected_subscription_cents": 0,
        "refunded_cents": 0,
        "waitlist_rank": None,
        "status": "RECEIVED",
        "created_at_seq": DB.next_seq(),
        "version": 1,
    })
    DB.register("subscriptions", row)
    row["updated_at"] = row["created_at"]
    DB.subscriptions[row["id"]] = row
    return row


def make_custody_record(offering, data):
    row = new_row({
        "offering_id": offering["id"],
        "custodian_name": data.get("custodian_name"),
        "facility_code": data.get("facility_code"),
        "is_freeport": bool(data.get("is_freeport") or False),
        "custodian_dea_registered": bool(data.get("custodian_dea_registered") or False),
        "status": "PENDING",
        "custody_started_at": None,
        "custody_ended_at": None,
        "version": 1,
    })
    DB.register("custody_records", row)
    row["updated_at"] = row["created_at"]
    DB.custody_records[row["id"]] = row
    return row


def make_holding_decision(offering, data, user_id):
    row = new_row({
        "offering_id": offering["id"],
        "decision_type": data.get("decision_type"),
        "status": "PENDING",
        "proposed_gross_cents": data.get("proposed_gross_cents"),
        "executed_gross_cents": None,
        "created_by_user_id": user_id,
        "approved_by_user_id": None,
        "version": 1,
    })
    DB.register("holding_decisions", row)
    row["updated_at"] = row["created_at"]
    DB.holding_decisions[row["id"]] = row
    return row


def make_transfer_order(offering, data, user_id):
    row = new_row({
        "offering_id": offering["id"],
        "seller_id": data.get("seller_id"),
        "shares": int(data.get("shares") or 0),
        "limit_price_cents": int(data.get("limit_price_cents") or 0),
        "bid_price_cents": None,
        "buyer_id": None,
        "execution_price_cents": None,
        "status": "OPEN",
        "created_by_user_id": user_id,
        "version": 1,
    })
    DB.register("transfer_orders", row)
    row["updated_at"] = row["created_at"]
    DB.transfer_orders[row["id"]] = row
    return row


def make_lot(offering, data):
    row = new_row({
        "offering_id": offering["id"],
        "lot_type": data.get("lot_type"),
        "cost_amount_cents": int(data.get("cost_amount_cents") or 0),
        "incurred_on": data.get("incurred_on"),
        "pass_through_allowed": False,
        "pass_through_amount_cents": 0,
        "version": 1,
    })
    DB.register("lots", row)
    row["updated_at"] = row["created_at"]
    DB.lots[row["id"]] = row
    return row


def make_policy(offering, data):
    row = new_row({
        "offering_id": offering["id"],
        "carrier_name": data.get("carrier_name"),
        "coverage_cents": int(data.get("coverage_cents") or 0),
        "annual_premium_cents": int(data.get("annual_premium_cents") or 0),
        "status": "PENDING",
        "version": 1,
    })
    DB.register("insurance_policies", row)
    row["updated_at"] = row["created_at"]
    DB.insurance_policies[row["id"]] = row
    return row


def make_report(offering, data):
    row = new_row({
        "offering_id": offering["id"],
        "report_kind": data.get("report_kind"),
        "as_of_date": data.get("as_of_date"),
        "filed_at": to_ms(DB.now()),
        "shareholder_count": 0,
        "value_per_share_cents": data.get("value_per_share_cents"),
        "is_quarter_marker": False,
    })
    DB.register("offering_reports", row)
    DB.offering_reports[row["id"]] = row
    return row


def make_accrual(offering, accrual_type, basis, presentation, settle):
    row = new_row({
        "offering_id": offering["id"],
        "accrual_type": accrual_type,
        "basis_value_cents": basis,
        "amount_cents": settle,
        "presentation_amount_cents": presentation,
        "settle_amount_cents": settle,
        "accrued_at": to_ms(DB.now()),
    })
    DB.register("fee_accruals", row)
    DB.fee_accruals[row["id"]] = row
    return row


def make_distribution(offering, wf):
    row = new_row({
        "offering_id": offering["id"],
        "sale_gross_cents": wf["sale_gross_cents"],
        "distributable_cents": wf["distributable_cents"],
        "distributed_cost_cents": wf["distributed_cost_cents"],
        "management_fee_cents": wf["management_fee_cents"],
        "profit_participation_cents": wf["profit_participation_cents"],
        "preferred_return_cents": wf["preferred_return_cents"],
        "investor_residual_cents": wf["investor_residual_cents"],
        "per_share_cents": wf["per_share_cents"],
        "remainder_cents": wf["remainder_cents"],
        "status": "CALCULATED",
    })
    DB.register("distributions", row)
    DB.distributions[row["id"]] = row
    return row


def make_platform_account(data):
    row = new_row({
        "account_name": data.get("account_name"),
        "balance_cents": 0,
        "investor_funds_held_cents": 0,
        "total_paid_out_cents": 0,
        "version": 1,
    })
    DB.register("platform_accounts", row)
    row["updated_at"] = row["created_at"]
    DB.platform_accounts[row["id"]] = row
    return row


# ---------------------------------------------------------------------------
# derived projections
# ---------------------------------------------------------------------------

def insert_index(obj):
    """Monotone insertion index of a row (ties broken the way §2.3 prescribes)."""
    return DB.order_index.get(obj.get("id"), 0)


def sort_by_creation(rows):
    return sorted(rows, key=lambda r: (r.get("created_at") or "", insert_index(r)))


def appraisals_of(artwork_id):
    rows = [a for a in DB.appraisals.values() if a["artwork_id"] == artwork_id]
    return sorted(rows, key=lambda a: (a["filed_at"], insert_index(a)))


def selected_appraisals(artwork_id):
    return [a for a in appraisals_of(artwork_id) if a.get("is_selected")]


def newest_appraisal(artwork_id):
    rows = selected_appraisals(artwork_id)
    return rows[-1] if rows else None


def oldest_appraisal(artwork_id):
    rows = appraisals_of(artwork_id)
    return rows[0] if rows else None


def vetted_appraisal(artwork_id):
    """Newest SELECTED appraisal whose provenance attestation (VERIFIED
    PROVENANCE report) was filed at or before that appraisal's filed_at."""
    prov_dates = [r["filed_at"] for r in DB.asset_reports.values()
                  if r["artwork_id"] == artwork_id
                  and r["report_type"] == "PROVENANCE" and r["outcome"] == "VERIFIED"]
    out = None
    for a in selected_appraisals(artwork_id):
        if any(p <= a["filed_at"] for p in prov_dates):
            out = a
    return out


def refresh_overview(artwork, bump=True):
    aid = artwork["id"]
    reports = [r for r in DB.asset_reports.values() if r["artwork_id"] == aid]
    auth_ok = any(r["report_type"] == "AUTHENTICATION" and r["outcome"] == "VERIFIED"
                  for r in reports)
    prov_ok = any(r["report_type"] == "PROVENANCE" and r["outcome"] == "VERIFIED"
                  for r in reports)
    newest = newest_appraisal(aid)
    custody_started = None
    for rec in DB.custody_records.values():
        off = DB.offerings.get(rec["offering_id"])
        if off and off["artwork_id"] == aid and rec["custody_started_at"]:
            if custody_started is None or rec["custody_started_at"] < custody_started:
                custody_started = rec["custody_started_at"]
    elapsed = 0
    if custody_started:
        elapsed = max(0, day_gap(DB.now(), custody_started) or 0)
    due = cadence_flag(elapsed)
    artwork["artifacts_overview"] = {
        "is_authenticated": bool(auth_ok and prov_ok),
        "has_good_provenance": bool(prov_ok),
        "latest_appraisal_value_cents": (newest["appraised_value_cents"] if newest else 0),
        "latest_appraisal_filed_at": (newest["filed_at"] if newest else None),
        "custody_started_at": custody_started,
        "holding_period_elapsed_days": elapsed,
        "appraisal_due": due == "REQUIRED",
    }
    artwork["updated_at"] = to_ms(DB.now())
    if bump:
        artwork["version"] = int(artwork.get("version") or 1) + 1
    return artwork["artifacts_overview"]