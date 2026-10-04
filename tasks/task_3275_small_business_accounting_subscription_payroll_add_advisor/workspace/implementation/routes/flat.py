"""Flat filtered-list GET endpoints for FK reverse-reachability."""
from flask import Blueprint
import db
from auth import require_role
from errors import ok, ok_list
from helpers import get_or_404, paginate, sort_by_created, filter_items
import serializers

bp = Blueprint("flat", __name__, url_prefix="/api")

ANY_ROLE = ["PlatformAdmin", "CompanyUser", "AccountantUser"]


def _list(table, serializer, filters):
    require_role(ANY_ROLE)
    items = filter_items(list(db.TABLES[table].values()), filters)
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list([serializer(i) for i in page], limit, offset, total)


def _get(table, serializer, entity_id):
    require_role(ANY_ROLE)
    rec = get_or_404(table, entity_id)
    return ok(serializer(rec))


@bp.get("/subscriptions/<sid>")
def get_subscription_flat(sid):
    rec = get_or_404("Subscription", sid)
    require_role(ANY_ROLE)
    import services
    rec["monthly_price_cents"] = services.monthly_price_cents(rec)
    return ok(serializers.serialize_subscription(rec))


@bp.get("/subscriptions")
def list_subscriptions():
    return _list("Subscription", serializers.serialize_subscription,
                 [("company_id", "company_id"), ("plan_id", "plan_id"),
                  ("billing_firm_id", "billing_firm_id")])


@bp.get("/payroll_addons/<aid>")
def get_payroll_addon_flat(aid):
    return _get("PayrollAddon", serializers.serialize_payroll_addon, aid)


@bp.get("/payroll_addons")
def list_payroll_addons():
    return _list("PayrollAddon", serializers.serialize_payroll_addon,
                 [("subscription_id", "subscription_id")])


@bp.get("/payroll_employees/<eid>")
def get_payroll_employee_flat(eid):
    return _get("PayrollEmployee", serializers.serialize_payroll_employee, eid)


@bp.get("/payroll_employees")
def list_payroll_employees():
    return _list("PayrollEmployee", serializers.serialize_payroll_employee,
                 [("payroll_addon_id", "payroll_addon_id")])


@bp.get("/invoices/<iid>")
def get_invoice_flat(iid):
    return _get("Invoice", serializers.serialize_invoice, iid)


@bp.get("/invoices")
def list_invoices_flat():
    return _list("Invoice", serializers.serialize_invoice,
                 [("company_id", "company_id"), ("subscription_id", "subscription_id")])


@bp.get("/bank_transactions/<tid>")
def get_txn_flat(tid):
    return _get("BankTransaction", serializers.serialize_bank_transaction, tid)


@bp.get("/bank_transactions")
def list_txns_flat():
    return _list("BankTransaction", serializers.serialize_bank_transaction,
                 [("bank_connection_id", "bank_connection_id"),
                  ("category_id", "category_id"),
                  ("matched_rule_id", "matched_rule_id"),
                  ("reconciled_in_id", "reconciled_in_id")])


@bp.get("/categorization_rules/<rid>")
def get_rule_flat(rid):
    return _get("CategorizationRule", serializers.serialize_rule, rid)


@bp.get("/categorization_rules")
def list_rules_flat():
    return _list("CategorizationRule", serializers.serialize_rule,
                 [("company_id", "company_id"),
                  ("assign_category_id", "assign_category_id")])


@bp.get("/reconciliations/<rid>")
def get_recon_flat(rid):
    import services
    require_role(ANY_ROLE)
    rec = get_or_404("Reconciliation", rid)
    services.recon_recompute(rec)
    return ok(serializers.serialize_reconciliation(rec))


@bp.get("/reconciliations")
def list_recons_flat():
    return _list("Reconciliation", serializers.serialize_reconciliation,
                 [("company_id", "company_id"),
                  ("bank_connection_id", "bank_connection_id")])


@bp.get("/sync_conflicts/<cid>")
def get_conflict_flat(cid):
    return _get("SyncConflict", serializers.serialize_sync_conflict, cid)


@bp.get("/sync_conflicts")
def list_conflicts_flat():
    return _list("SyncConflict", serializers.serialize_sync_conflict,
                 [("app_integration_id", "app_integration_id")])


@bp.get("/billing_transfers/<tid>")
def get_transfer_flat(tid):
    return _get("BillingTransfer", serializers.serialize_billing_transfer, tid)


@bp.get("/billing_transfers")
def list_transfers_flat():
    return _list("BillingTransfer", serializers.serialize_billing_transfer,
                 [("company_id", "company_id"), ("subscription_id", "subscription_id"),
                  ("initiating_firm_id", "initiating_firm_id")])


@bp.get("/access_grants/<gid>")
def get_grant_flat(gid):
    return _get("AccessGrant", serializers.serialize_access_grant, gid)


@bp.get("/access_grants")
def list_grants_flat():
    return _list("AccessGrant", serializers.serialize_access_grant,
                 [("company_id", "company_id"), ("accountant_user_id", "accountant_user_id"),
                  ("firm_id", "firm_id")])


@bp.get("/export_requests/<eid>")
def get_export_flat(eid):
    return _get("ExportRequest", serializers.serialize_export_request, eid)


@bp.get("/export_requests")
def list_exports_flat():
    return _list("ExportRequest", serializers.serialize_export_request,
                 [("company_id", "company_id"),
                  ("requested_by_user_id", "requested_by_user_id")])
