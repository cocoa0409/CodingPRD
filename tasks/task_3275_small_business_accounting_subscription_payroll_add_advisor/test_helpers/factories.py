"""Payload factories — one per entity, input fields only.

Server-stamped fields (id, version, created_at, computed, status) are never
part of an input payload.  Each factory exposes only the fields the PRD
lists as input for that endpoint.
"""


# --- Plans ------------------------------------------------------------------


def create_plan_payload(**overrides):
    defaults = {
        "plan_code": "PLUS",
        "list_price_cents": 8000,
        "max_seats": 5,
        "feature_inventory": True,
        "feature_project_profitability": True,
        "feature_multi_currency": True,
        "feature_bank_rules": True,
        "plan_rank": 3,
    }
    defaults.update(overrides)
    return defaults


def simple_start_plan_payload(**overrides):
    """SIMPLE_START tier per PRD 3.1: cheapest, no advanced features."""
    defaults = {
        "plan_code": "SIMPLE_START",
        "list_price_cents": 3000,
        "max_seats": 1,
        "feature_inventory": False,
        "feature_project_profitability": False,
        "feature_multi_currency": False,
        "feature_bank_rules": False,
        "plan_rank": 1,
    }
    defaults.update(overrides)
    return defaults


def essentials_plan_payload(**overrides):
    """ESSENTIALS tier per PRD 3.1."""
    defaults = {
        "plan_code": "ESSENTIALS",
        "list_price_cents": 5000,
        "max_seats": 3,
        "feature_inventory": False,
        "feature_project_profitability": False,
        "feature_multi_currency": True,
        "feature_bank_rules": True,
        "plan_rank": 2,
    }
    defaults.update(overrides)
    return defaults


def plus_plan_payload(**overrides):
    """PLUS tier per PRD 3.1 — all four feature flags on."""
    return create_plan_payload(**overrides)


def advanced_plan_payload(**overrides):
    """ADVANCED tier per PRD 3.1."""
    defaults = {
        "plan_code": "ADVANCED",
        "list_price_cents": 10000,
        "max_seats": 25,
        "feature_inventory": True,
        "feature_project_profitability": True,
        "feature_multi_currency": True,
        "feature_bank_rules": True,
        "plan_rank": 4,
    }
    defaults.update(overrides)
    return defaults


# --- Firms ------------------------------------------------------------------


def create_firm_payload(**overrides):
    defaults = {
        "firm_name": "Fiesta CPAs",
        "wholesale_discount_pct": 0.25,
        "proadvisor_tier": "GOLD",
    }
    defaults.update(overrides)
    return defaults


def create_firm_user_payload(firm_id, **overrides):
    defaults = {
        "firm_id": firm_id,
        "full_name": "Firm Admin",
        "email": "admin@firm.example",
        "is_firm_admin": True,
    }
    defaults.update(overrides)
    return defaults


# --- Companies ------------------------------------------------------------------


def create_company_payload(plan_id, **overrides):
    defaults = {
        "legal_name": "Alpha Corp",
        "admin_email": "admin@alpha.example",
        "home_country": "US",
        "data_region": "US",
        "plan_id": plan_id,
    }
    defaults.update(overrides)
    return defaults


def create_company_user_payload(company_id, **overrides):
    defaults = {
        "company_id": company_id,
        "email": "user@alpha.example",
        "display_name": "User",
        "permission_level": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def primary_admin_payload(company_id, **overrides):
    defaults = {
        "company_id": company_id,
        "email": "pa@alpha.example",
        "display_name": "Primary Admin",
        "permission_level": "PRIMARY_ADMIN",
    }
    defaults.update(overrides)
    return defaults


# --- Subscription lifecycle --------------------------------------------------------


def activate_subscription_payload(**overrides):
    defaults = {"payment_method_token": "pm_card_visa"}
    defaults.update(overrides)
    return defaults


def change_plan_payload(plan_id, expected_subscription_version, **overrides):
    payload = {
        "plan_id": plan_id,
        "expected_subscription_version": expected_subscription_version,
    }
    payload.update(overrides)
    return payload


def cancel_subscription_payload(**overrides):
    defaults = {"reason": "test"}
    defaults.update(overrides)
    return defaults


def reactivate_subscription_payload(**overrides):
    defaults = {"payment_method_token": "pm_card_visa"}
    defaults.update(overrides)
    return defaults


# --- Payroll ------------------------------------------------------------------


def create_payroll_payload(subscription_id, **overrides):
    defaults = {
        "subscription_id": subscription_id,
        "service_level": "SELF_SERVICE",
    }
    defaults.update(overrides)
    return defaults


def create_payroll_employee_payload(payroll_addon_id, **overrides):
    defaults = {
        "payroll_addon_id": payroll_addon_id,
        "legal_name": "Emp One",
        "hire_date": "2026-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def terminate_employee_payload(expected_payroll_addon_version, **overrides):
    payload = {"expected_payroll_addon_version": expected_payroll_addon_version}
    payload.update(overrides)
    return payload


# --- Bank connections and transactions --------------------------------------------


def create_bank_connection_payload(company_id, **overrides):
    defaults = {
        "company_id": company_id,
        "institution_name": "Chase",
        "external_account_mask": "1234",
        "consent_expires_at": "2027-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def ingest_txn_payload(**overrides):
    defaults = {
        "posted_at": "2026-09-15T00:00:00Z",
        "amount_cents": -100,
        "payee_raw": "TEST PAYEE",
    }
    defaults.update(overrides)
    return defaults


def categorize_txn_payload(category_id, **overrides):
    payload = {"category_id": category_id}
    payload.update(overrides)
    return payload


def reauthorize_connection_payload(**overrides):
    defaults = {"consent_expires_at": "2027-09-01T00:00:00Z"}
    defaults.update(overrides)
    return defaults


# --- Categories and rules ---------------------------------------------------------


def create_category_payload(company_id, **overrides):
    defaults = {
        "company_id": company_id,
        "name": "Misc",
        "tax_line": "SCH-C-L27",
    }
    defaults.update(overrides)
    return defaults


def create_rule_payload(company_id, assign_category_id, **overrides):
    defaults = {
        "company_id": company_id,
        "rule_name": "Default rule",
        "match_field": "PAYEE_CONTAINS",
        "match_value": "X",
        "assign_category_id": assign_category_id,
        "priority": 1,
        "auto_apply": True,
    }
    defaults.update(overrides)
    return defaults


# --- Reconciliations ---------------------------------------------------------


def create_reconciliation_payload(company_id, bank_connection_id, **overrides):
    defaults = {
        "company_id": company_id,
        "bank_connection_id": bank_connection_id,
        "statement_period_start": "2026-08-01T00:00:00Z",
        "statement_period_end": "2026-08-31T00:00:00Z",
        "statement_ending_balance_cents": 0,
    }
    defaults.update(overrides)
    return defaults


# --- Integrations and conflicts --------------------------------------------


def create_integration_payload(company_id, **overrides):
    defaults = {
        "company_id": company_id,
        "app_code": "SHOPIFY",
        "sync_direction": "BIDIRECTIONAL",
    }
    defaults.update(overrides)
    return defaults


def record_conflict_payload(**overrides):
    defaults = {
        "conflict_field": "customer_name",
        "local_value": "Local Co",
        "remote_value": "Remote Co",
    }
    defaults.update(overrides)
    return defaults


def resolve_conflict_payload(resolution, **overrides):
    payload = {"resolution": resolution}
    payload.update(overrides)
    return payload


# --- Migration jobs -----------------------------------------------------------


def create_migration_job_payload(company_id, **overrides):
    defaults = {
        "company_id": company_id,
        "source_product": "DESKTOP_PRO",
        "source_file_size_bytes": 1000000,
        "target_list_entries": 50000,
    }
    defaults.update(overrides)
    return defaults


def complete_migration_payload(outcome, **overrides):
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


# --- Billing transfers -----------------------------------------------------------


def create_billing_transfer_payload(company_id, subscription_id, initiating_firm_id, **overrides):
    defaults = {
        "company_id": company_id,
        "subscription_id": subscription_id,
        "initiating_firm_id": initiating_firm_id,
        "to_owner": "FIRM",
    }
    defaults.update(overrides)
    return defaults


def accept_transfer_payload(expected_subscription_version, **overrides):
    payload = {"expected_subscription_version": expected_subscription_version}
    payload.update(overrides)
    return payload


def decline_transfer_payload(**overrides):
    defaults = {"decline_reason": "not now"}
    defaults.update(overrides)
    return defaults


# --- Access grants ------------------------------------------------------------------


def create_access_grant_payload(company_id, accountant_user_id, firm_id, **overrides):
    defaults = {
        "company_id": company_id,
        "accountant_user_id": accountant_user_id,
        "firm_id": firm_id,
        "access_level": "FULL_BOOKKEEPING",
    }
    defaults.update(overrides)
    return defaults


# --- Exports -------------------------------------------------------------------------


def create_export_payload(company_id, requested_by_user_id, **overrides):
    defaults = {
        "company_id": company_id,
        "requested_by_user_id": requested_by_user_id,
        "format": "CSV",
        "scope": "TRANSACTIONS_ONLY",
    }
    defaults.update(overrides)
    return defaults
