"""Serializers: convert internal records to wire format.
Plans and Categories deliberately omit updated_at / version."""
import db


def _base(rec, with_version=True):
    out = {"id": rec["id"], "created_at": rec["created_at"]}
    if with_version:
        out["updated_at"] = rec.get("updated_at")
        out["version"] = rec.get("version")
    return out


def serialize_plan(p):
    out = _base(p, with_version=False)
    out.update({
        "plan_code": p["plan_code"],
        "list_price_cents": p["list_price_cents"],
        "max_seats": p["max_seats"],
        "feature_inventory": p["feature_inventory"],
        "feature_project_profitability": p["feature_project_profitability"],
        "feature_multi_currency": p["feature_multi_currency"],
        "feature_bank_rules": p["feature_bank_rules"],
        "plan_rank": p["plan_rank"],
    })
    return out


def serialize_firm(f):
    out = _base(f)
    out.update({
        "firm_name": f["firm_name"],
        "wholesale_discount_pct": f["wholesale_discount_pct"],
        "proadvisor_tier": f["proadvisor_tier"],
        "firm_status": f["firm_status"],
    })
    return out


def serialize_accountant_user(u):
    out = _base(u)
    out.update({
        "firm_id": u["firm_id"],
        "full_name": u["full_name"],
        "email": u["email"],
        "is_firm_admin": u["is_firm_admin"],
        "user_status": u["user_status"],
    })
    return out


def serialize_company(c):
    out = _base(c)
    out.update({
        "legal_name": c["legal_name"],
        "admin_email": c["admin_email"],
        "home_country": c["home_country"],
        "data_region": c["data_region"],
        "company_status": c["company_status"],
        "primary_admin_user_id": c.get("primary_admin_user_id"),
    })
    return out


def serialize_company_user(u):
    out = _base(u)
    out.update({
        "company_id": u["company_id"],
        "email": u["email"],
        "display_name": u["display_name"],
        "permission_level": u["permission_level"],
        "user_status": u["user_status"],
    })
    return out


def serialize_subscription(s):
    out = _base(s)
    out.update({
        "company_id": s["company_id"],
        "plan_id": s["plan_id"],
        "billing_owner": s["billing_owner"],
        "billing_firm_id": s.get("billing_firm_id"),
        "lifecycle_status": s["lifecycle_status"],
        "billing_status": s["billing_status"],
        "anchor_day": s.get("anchor_day"),
        "started_at": s["started_at"],
        "trial_ends_at": s["trial_ends_at"],
        "cancelled_at": s.get("cancelled_at"),
        "read_only_expires_at": s.get("read_only_expires_at"),
        "monthly_price_cents": s.get("monthly_price_cents"),
        "pending_upgrade_prompt": s.get("pending_upgrade_prompt", False),
    })
    return out


def serialize_payroll_addon(a):
    out = _base(a)
    out.update({
        "subscription_id": a["subscription_id"],
        "service_level": a["service_level"],
        "base_fee_cents": a["base_fee_cents"],
        "per_employee_fee_cents": a["per_employee_fee_cents"],
        "addon_status": a["addon_status"],
        "tax_filing_status": a.get("tax_filing_status"),
        "activated_at": a["activated_at"],
    })
    return out


def serialize_payroll_employee(e):
    out = _base(e)
    out.update({
        "payroll_addon_id": e["payroll_addon_id"],
        "legal_name": e["legal_name"],
        "hire_date": e["hire_date"],
        "employment_status": e["employment_status"],
        "terminated_at": e.get("terminated_at"),
    })
    return out


def serialize_invoice(i):
    out = _base(i)
    out.update({
        "company_id": i["company_id"],
        "subscription_id": i["subscription_id"],
        "period_start": i["period_start"],
        "period_end": i["period_end"],
        "billed_to": i["billed_to"],
        "list_subscription_cents": i["list_subscription_cents"],
        "wholesale_discount_cents": i["wholesale_discount_cents"],
        "payroll_base_cents": i["payroll_base_cents"],
        "payroll_per_employee_cents": i["payroll_per_employee_cents"],
        "tax_cents": i["tax_cents"],
        "total_cents": i["total_cents"],
        "invoice_status": i["invoice_status"],
    })
    return out


def serialize_bank_connection(c):
    out = _base(c)
    out.update({
        "company_id": c["company_id"],
        "institution_name": c["institution_name"],
        "external_account_mask": c["external_account_mask"],
        "connection_status": c["connection_status"],
        "last_sync_at": c.get("last_sync_at"),
        "consent_expires_at": c.get("consent_expires_at"),
    })
    return out


def serialize_bank_transaction(t):
    out = _base(t)
    out.update({
        "bank_connection_id": t["bank_connection_id"],
        "posted_at": t["posted_at"],
        "amount_cents": t["amount_cents"],
        "payee_raw": t["payee_raw"],
        "category_id": t.get("category_id"),
        "matched_rule_id": t.get("matched_rule_id"),
        "txn_status": t["txn_status"],
        "reconciled_in_id": t.get("reconciled_in_id"),
    })
    return out


def serialize_category(c):
    out = _base(c, with_version=False)
    out.update({
        "company_id": c["company_id"],
        "name": c["name"],
        "tax_line": c["tax_line"],
    })
    return out


def serialize_rule(r):
    out = _base(r)
    out.update({
        "company_id": r["company_id"],
        "rule_name": r["rule_name"],
        "match_field": r["match_field"],
        "match_value": r["match_value"],
        "assign_category_id": r["assign_category_id"],
        "priority": r["priority"],
        "auto_apply": r.get("auto_apply", True),
        "rule_status": r["rule_status"],
    })
    return out


def serialize_reconciliation(r):
    out = _base(r)
    out.update({
        "company_id": r["company_id"],
        "bank_connection_id": r["bank_connection_id"],
        "statement_period_start": r["statement_period_start"],
        "statement_period_end": r["statement_period_end"],
        "statement_ending_balance_cents": r["statement_ending_balance_cents"],
        "beginning_balance_cents": r["beginning_balance_cents"],
        "cleared_cents": r["cleared_cents"],
        "difference_cents": r["difference_cents"],
        "recon_status": r["recon_status"],
        "completed_at": r.get("completed_at"),
    })
    return out


def serialize_integration(i):
    out = _base(i)
    out.update({
        "company_id": i["company_id"],
        "app_code": i["app_code"],
        "sync_direction": i["sync_direction"],
        "integration_status": i["integration_status"],
        "conflict_count": i.get("conflict_count", 0),
        "last_sync_at": i.get("last_sync_at"),
    })
    return out


def serialize_sync_conflict(c):
    out = _base(c)
    out.update({
        "app_integration_id": c["app_integration_id"],
        "conflict_field": c["conflict_field"],
        "local_value": c["local_value"],
        "remote_value": c["remote_value"],
        "conflict_status": c["conflict_status"],
    })
    return out


def serialize_migration_job(m):
    out = _base(m)
    out.update({
        "company_id": m["company_id"],
        "source_product": m["source_product"],
        "source_file_size_bytes": m["source_file_size_bytes"],
        "target_list_entries": m["target_list_entries"],
        "migration_status": m["migration_status"],
        "limitation_codes": m.get("limitation_codes", []),
    })
    return out


def serialize_billing_transfer(t):
    out = _base(t)
    out.update({
        "company_id": t["company_id"],
        "subscription_id": t["subscription_id"],
        "from_owner": t["from_owner"],
        "to_owner": t["to_owner"],
        "initiating_firm_id": t["initiating_firm_id"],
        "transfer_status": t["transfer_status"],
        "proforma_monthly_cents": t["proforma_monthly_cents"],
        "expires_at": t["expires_at"],
        "decline_reason": t.get("decline_reason"),
    })
    return out


def serialize_access_grant(g):
    out = _base(g)
    out.update({
        "company_id": g["company_id"],
        "accountant_user_id": g["accountant_user_id"],
        "firm_id": g["firm_id"],
        "access_level": g["access_level"],
        "grant_status": g["grant_status"],
        "expires_at": g.get("expires_at"),
    })
    return out


def serialize_export_request(e):
    out = _base(e)
    out.update({
        "company_id": e["company_id"],
        "requested_by_user_id": e["requested_by_user_id"],
        "format": e["format"],
        "scope": e["scope"],
        "export_status": e["export_status"],
        "ready_at": e.get("ready_at"),
        "download_expires_at": e.get("download_expires_at"),
    })
    return out
