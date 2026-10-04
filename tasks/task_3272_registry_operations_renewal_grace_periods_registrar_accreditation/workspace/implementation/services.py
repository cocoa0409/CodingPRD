from datetime import timedelta
from decimal import Decimal

import db
import clock
from util import fmt_iso, parse_iso, add_years, round_half_up_cents, is_leap_year

PREMIUM_SURCHARGE_RATE = Decimal("0.10")
AUTO_RENEW_GRACE_DAYS = 45
REDEMPTION_GRACE_DAYS = 30
PENDING_DELETE_DAYS = 5
NOTICE_DAYS = 180
ANNUAL_CAP_RATE = Decimal("0.10")
CAPACITY_COMMITMENT_QPS = 8000
MIN_NAMESERVER_QPS = 2000

LIVE_DOMAIN_STATUSES = {"ACTIVE", "AUTO_RENEW_GRACE", "REDEMPTION_GRACE", "TRANSFERRING"}


# ---------------------------------------------------------------- serializers

def registrar_view(r):
    return {
        "id": r["id"],
        "iana_number": r["iana_number"],
        "legal_name": r["legal_name"],
        "application_fee_cents": r["application_fee_cents"],
        "annual_fee_cents": r["annual_fee_cents"],
        "escrow_deposit_cents": r["escrow_deposit_cents"],
        "technical_test_score": r["technical_test_score"],
        "financial_statement_verified": r["financial_statement_verified"],
        "credit_hold": r["credit_hold"],
        "status": r["status"],
        "accredited_on": r["accredited_on"],
        "accredited_version": r["accredited_version"],
        "all_in_cost_cents": r["all_in_cost_cents"],
        "annual_fee_mode": r["annual_fee_mode"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def schedule_view(s):
    return {
        "id": s["id"],
        "create_fee_cents": s["create_fee_cents"],
        "renew_fee_cents": s["renew_fee_cents"],
        "restore_fee_cents": s["restore_fee_cents"],
        "transfer_fee_cents": s["transfer_fee_cents"],
        "effective_on": s["effective_on"],
        "announced_at": s["announced_at"],
        "supersedes_schedule_id": s["supersedes_schedule_id"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def domain_view(d):
    return {
        "id": d["id"],
        "name": d["name"],
        "registrar_id": d["registrar_id"],
        "years": d["years"],
        "premium": d["premium"],
        "expires_on": d["expires_on"],
        "grace_deadline": d["grace_deadline"],
        "status": d["status"],
        "lock_status": d["lock_status"],
        "suspension_status": d["suspension_status"],
        "registry_lock_token_hash": d["registry_lock_token_hash"],
        "auto_renewed_on": d["auto_renewed_on"],
        "delete_scheduled_on": d["delete_scheduled_on"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def nameserver_view(n):
    return {
        "id": n["id"],
        "hostname": n["hostname"],
        "ip_addresses": n["ip_addresses"],
        "capacity_qps": n["capacity_qps"],
        "created_at": n["created_at"],
        "updated_at": n["updated_at"],
        "version": n["version"],
    }


def link_view(l):
    return {
        "id": l["id"],
        "domain_id": l["domain_id"],
        "nameserver_id": l["nameserver_id"],
        "created_at": l["created_at"],
    }


def transfer_view(t, include_auth_code=False):
    v = {
        "id": t["id"],
        "domain_id": t["domain_id"],
        "from_registrar_id": t["from_registrar_id"],
        "to_registrar_id": t["to_registrar_id"],
        "auth_code_expires_at": t["auth_code_expires_at"],
        "requested_at": t["requested_at"],
        "status": t["status"],
        "dispute_reason": t["dispute_reason"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }
    if include_auth_code:
        v["auth_code"] = t.get("_plaintext_auth_code")
    return v


def invoice_view(i):
    return {
        "id": i["id"],
        "registrar_id": i["registrar_id"],
        "domain_id": i["domain_id"],
        "kind": i["kind"],
        "base_cents": i["base_cents"],
        "premium_surcharge_cents": i["premium_surcharge_cents"],
        "total_cents": i["total_cents"],
        "price_schedule_id": i["price_schedule_id"],
        "status": i["status"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def ledger_view(e):
    return {
        "id": e["id"],
        "registrar_id": e["registrar_id"],
        "invoice_id": e["invoice_id"],
        "amount_cents": e["amount_cents"],
        "entry_type": e["entry_type"],
        "created_at": e["created_at"],
    }


def abuse_view(a):
    return {
        "id": a["id"],
        "domain_id": a["domain_id"],
        "reporter_contact": a["reporter_contact"],
        "category": a["category"],
        "detail": a["detail"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def court_view(c):
    return {
        "id": c["id"],
        "case_reference": c["case_reference"],
        "domain_id": c["domain_id"],
        "action": c["action"],
        "effective_immediately": c["effective_immediately"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def notice_view(n):
    return {
        "id": n["id"],
        "registrar_id": n["registrar_id"],
        "price_schedule_id": n["price_schedule_id"],
        "notice_kind": n["notice_kind"],
        "sent_at": n["sent_at"],
        "created_at": n["created_at"],
    }
