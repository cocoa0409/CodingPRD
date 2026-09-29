"""The recompute cascade of PRD 2.8 — every link runs before the response returns."""
import calc
import store


def refresh_balance(account):
    """Recompute a custody account's balance from its entries and bump its version."""
    total = 0
    for entry in store.DB["ledger_entries"].values():
        if entry["custody_account_id"] == account["id"]:
            total += int(entry["amount_cents"])
    account["balance_cents"] = total
    store.touch(account)
    return account


def refresh_complaint_rate(partner):
    partner["complaint_rate_bps"] = calc.complaint_rate_bps(partner)


def refresh_open_sanctions(partner):
    count = 0
    for alert in store.DB["alerts"].values():
        if alert["partner_id"] == partner["id"] and alert["alert_type"] == "SANCTIONS_HIT" \
                and alert["disposition"] in ("OPEN", "PARTNER_RESPONSE_PENDING"):
            count += 1
    partner["open_sanctions_alert_count"] = count


def refresh_unreconciled_variance(partner):
    total = 0
    for batch in store.DB["settlement_batches"].values():
        if batch["partner_id"] == partner["id"] and \
                batch["reconciliation_status"] == "VARIANCE_OPEN":
            total += abs(int(batch["variance_cents"]))
    partner["unreconciled_variance_cents"] = total


def refresh_reserve(partner):
    required, shortfall = calc.required_reserve(partner)
    partner["required_reserve_cents"] = required
    partner["reserve_shortfall_cents"] = shortfall


def refresh_concentration(partner):
    """The ratio is a group property: every member is written the same value."""
    numerator, denominator, members = calc.concentration_parts(partner)
    ratio = calc.concentration_ratio(numerator, denominator)
    for member in members:
        member["concentration_ratio_pct"] = ratio
    return ratio


def refresh_posture(partner):
    partner["oversight_posture"] = calc.posture_for(partner)
    return partner["oversight_posture"]


def freeze_custody_if_frozen(partner):
    """PRD 2.8: FROZEN posture moves ACTIVE accounts to FROZEN inside this request."""
    if partner["oversight_posture"] != "FROZEN":
        return 0
    frozen = 0
    for account in store.rows("custody_accounts"):
        if account["partner_id"] == partner["id"] and account["status"] == "ACTIVE":
            account["status"] = "FROZEN"
            account["frozen_at"] = store.clock()
            store.touch(account)
            frozen += 1
    return frozen


def group_reserve_and_concentration(partner):
    """Reserve, shortfall and concentration for every partner in the group."""
    members = calc.group_members(partner)
    for member in members:
        refresh_reserve(member)
    refresh_concentration(partner)


def money_cascade(partner):
    """The tail shared by ledger inserts, funding, clawback and variance clearing."""
    group_reserve_and_concentration(partner)
    refresh_posture(partner)
    freeze_custody_if_frozen(partner)


def new_partner_record(user_id, legal_name, parent_partner_id, business_model,
                       funding_stage, months_runway, disclosed, account_count):
    return {
        "legal_name": legal_name,
        "parent_partner_id": parent_partner_id,
        "business_model": business_model,
        "funding_stage": funding_stage,
        "months_runway": months_runway,
        "disclosed_complaints_per_10k": disclosed,
        "end_user_account_count": account_count,
        "status": "PROSPECT",
        "oversight_posture": "OPEN",
        "capability_tier": "UNRATED",
        "latest_composite_score": 0.0,
        "complaint_rate_bps": 0,
        "total_complaint_count": 0,
        "open_complaint_count": 0,
        "escalated_complaint_count": 0,
        "resolved_complaint_count": 0,
        "withdrawn_complaint_count": 0,
        "open_sanctions_alert_count": 0,
        "unreconciled_variance_cents": 0,
        "required_reserve_cents": 0,
        "reserve_shortfall_cents": 0,
        "consecutive_shortfall_cycles": 0,
        "growth_breach_count": 0,
        "concentration_ratio_pct": 0.00,
        "monthly_growth_pct": 0.00,
        "cumulative_paid_out_cents": 0,
        "cumulative_bank_fee_cents": 0,
        "created_by_user_id": user_id,
        "systemic_root_cause_code": None,
    }
