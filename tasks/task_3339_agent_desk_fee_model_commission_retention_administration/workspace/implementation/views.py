"""Entity serialization — public views per entity."""
import clock
from clock import parse


def office_view(o):
    return {
        "id": o["id"],
        "office_name": o["office_name"],
        "market_code": o["market_code"],
        "status": o["status"],
        "recruiting_target_agents": o["recruiting_target_agents"],
        "active_agent_count": o["active_agent_count"],
        "trust_balance_cents": o["trust_balance_cents"],
        "closed_at": o.get("closed_at"),
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def schedule_view(s):
    return {
        "id": s["id"],
        "schedule_name": s["schedule_name"],
        "desk_fee_cents": s["desk_fee_cents"],
        "overhead_share_bps": s["overhead_share_bps"],
        "retention_bps": s["retention_bps"],
        "referral_fee_bps": s["referral_fee_bps"],
        "tech_subscription_monthly_cents": s["tech_subscription_monthly_cents"],
        "marketing_monthly_cents": s["marketing_monthly_cents"],
        "effective_from": s["effective_from"],
        "effective_to": s["effective_to"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def agent_view(a):
    return {
        "id": a["id"],
        "office_id": a["office_id"],
        "full_name": a["full_name"],
        "email": a["email"],
        "license_number": a["license_number"],
        "status": a["status"],
        "onboarded_at": a.get("onboarded_at"),
        "termination_requested_at": a.get("termination_requested_at"),
        "terminated_at": a.get("terminated_at"),
        "supervision_cadence_days": a["supervision_cadence_days"],
        "unearned_advance_balance_cents": a["unearned_advance_balance_cents"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def assignment_view(fa):
    return {
        "id": fa["id"],
        "agent_id": fa["agent_id"],
        "fee_schedule_id": fa["fee_schedule_id"],
        "effective_from": fa["effective_from"],
        "effective_to": fa["effective_to"],
        "expected_agent_version": fa.get("expected_agent_version"),
        "status": fa["status"],
        "created_at": fa["created_at"],
        "updated_at": fa["updated_at"],
        "version": fa["version"],
    }


def offer_view(o):
    return {
        "id": o["id"],
        "office_id": o["office_id"],
        "listing_reference": o["listing_reference"],
        "buyer_name": o["buyer_name"],
        "offer_price_cents": o["offer_price_cents"],
        "offer_round": o["offer_round"],
        "status": o["status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def transaction_view(t):
    return {
        "id": t["id"],
        "office_id": t["office_id"],
        "listing_agent_id": t["listing_agent_id"],
        "selling_agent_id": t["selling_agent_id"],
        "offer_id": t["offer_id"],
        "sale_price_cents": t["sale_price_cents"],
        "gross_commission_cents": t["gross_commission_cents"],
        "status": t["status"],
        "closed_at": t.get("closed_at"),
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def cda_view(c):
    return {
        "id": c["id"],
        "transaction_id": c["transaction_id"],
        "authorizing_broker_id": c["authorizing_broker_id"],
        "review_ladder": c["review_ladder"],
        "current_rung": c["current_rung"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def closing_line_view(l):
    return {
        "id": l["id"],
        "transaction_id": l["transaction_id"],
        "line_type": l["line_type"],
        "agent_id": l.get("agent_id"),
        "amount_cents": l["amount_cents"],
        "applied_invoice_line_id": l.get("applied_invoice_line_id"),
        "variant": l["variant"],
        "status": l["status"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def invoice_view(inv):
    return {
        "id": inv["id"],
        "office_id": inv["office_id"],
        "agent_id": inv["agent_id"],
        "billing_month": inv["billing_month"],
        "origin": inv["origin"],
        "amount_due_cents": inv["amount_due_cents"],
        "due_date": inv.get("due_date"),
        "amount_paid_cents": inv["amount_paid_cents"],
        "status": inv["status"],
        "created_at": inv["created_at"],
        "updated_at": inv["updated_at"],
        "version": inv["version"],
    }


def invoice_line_view(l):
    return {
        "id": l["id"],
        "invoice_id": l["invoice_id"],
        "line_kind": l["line_kind"],
        "period_label": l["period_label"],
        "amount_cents": l["amount_cents"],
        "applied_at_closing_cents": l["applied_at_closing_cents"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def entry_view(e):
    return {
        "id": e["id"],
        "office_id": e["office_id"],
        "transaction_id": e.get("transaction_id"),
        "entry_kind": e["entry_kind"],
        "amount_cents": e["amount_cents"],
        "entry_month": e["entry_month"],
        "status": e["status"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def referral_view(r):
    return {
        "id": r["id"],
        "referring_office_id": r["referring_office_id"],
        "receiving_office_id": r["receiving_office_id"],
        "agent_id": r["agent_id"],
        "referral_fee_bps": r["referral_fee_bps"],
        "status": r["status"],
        "replaces_agreement_id": r.get("replaces_agreement_id"),
        "fulfilled_transaction_id": r.get("fulfilled_transaction_id"),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def report_view(r):
    return {
        "id": r["id"],
        "office_id": r["office_id"],
        "period_month": r["period_month"],
        "headcount_start": r["headcount_start"],
        "headcount_end": r["headcount_end"],
        "retention_bps": r["retention_bps"],
        "churned_agent_count": r["churned_agent_count"],
        "report_variant": r["report_variant"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }
