"""One transport method per endpoint in PRD section 4.

Every method returns the raw HTTP response so a test may assert on both
status code and envelope.  All paths live here and nowhere else.
"""

import os
import re

from prd_bench_local_runner.testing import GenericApiClient

from .constants import CLOCK_PATH

_INSTANT_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})[Tt]"
    r"(?P<time>\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<frac>\d+))?"
    r"(?P<tz>[Zz]|[+-]\d{2}:?\d{2})$"
)


def canonical_instant(value):
    """Render an ISO 8601 UTC instant with exactly three fractional digits."""
    if not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value.strip())
    if not match:
        return value
    frac = (match.group("frac") or "")[:6]
    frac = (frac + "000")[:3]
    tz = match.group("tz")
    if tz in ("Z", "z"):
        suffix = "Z"
    else:
        suffix = tz.replace(":", "")
        suffix = "{0}:{1}".format(suffix[:3], suffix[3:])
    return "{0}T{1}.{2}{3}".format(
        match.group("date"), match.group("time"), frac, suffix
    )


def same_instant(left, right):
    """True when two ISO 8601 renderings denote the same UTC instant."""
    return canonical_instant(left) == canonical_instant(right)


class ApiClient(GenericApiClient):
    """Thin, endpoint-shaped facade over the shared HTTP client."""

    def __init__(self, base_url=None):
        if base_url is None:
            base_url = os.environ.get("API_BASE_URL") or os.environ.get(
                "_PRD_BENCH_API_URL"
            )
        super().__init__(base_url=base_url)

    # --- Test drivers ---------------------------------------------------------

    def set_clock(self, current_utc, headers=None):
        return self.post(CLOCK_PATH, json={"current_utc": current_utc}, headers=headers)

    def simulate_payment(self, invoice_id, outcome, headers=None):
        return self.post(
            "/api/_payments/simulate",
            json={"invoice_id": invoice_id, "outcome": outcome},
            headers=headers,
        )

    def bank_feed_tick(self, bank_connection_id, headers=None):
        return self.post(
            "/api/_sync/bank_feed_tick",
            json={"bank_connection_id": bank_connection_id},
            headers=headers,
        )

    # --- Plans -----------------------------------------------------------------

    def create_plan(self, payload, headers=None):
        return self.post("/api/plans", json=payload, headers=headers)

    def list_plans(self, headers=None, params=None):
        return self.get("/api/plans", headers=headers, params=params)

    def get_plan(self, plan_id, headers=None):
        return self.get("/api/plans/{0}".format(plan_id), headers=headers)

    # --- Firms -----------------------------------------------------------------

    def create_firm(self, payload, headers=None):
        return self.post("/api/firms", json=payload, headers=headers)

    def get_firm(self, firm_id, headers=None):
        return self.get("/api/firms/{0}".format(firm_id), headers=headers)

    def suspend_firm(self, firm_id, headers=None):
        return self.post("/api/firms/{0}/suspend".format(firm_id), json={}, headers=headers)

    def reactivate_firm(self, firm_id, headers=None):
        return self.post(
            "/api/firms/{0}/reactivate".format(firm_id), json={}, headers=headers
        )

    def close_firm(self, firm_id, headers=None):
        return self.post("/api/firms/{0}/close".format(firm_id), json={}, headers=headers)

    def create_firm_user(self, firm_id, payload, headers=None):
        return self.post(
            "/api/firms/{0}/users".format(firm_id), json=payload, headers=headers
        )

    def list_firm_users(self, firm_id, headers=None, params=None):
        return self.get(
            "/api/firms/{0}/users".format(firm_id), headers=headers, params=params
        )

    def get_firm_user(self, firm_id, user_id, headers=None):
        return self.get(
            "/api/firms/{0}/users/{1}".format(firm_id, user_id), headers=headers
        )

    # --- Companies and company users -------------------------------------------

    def create_company(self, payload, headers=None):
        return self.post("/api/companies", json=payload, headers=headers)

    def list_companies(self, headers=None, params=None):
        return self.get("/api/companies", headers=headers, params=params)

    def get_company(self, company_id, headers=None):
        return self.get("/api/companies/{0}".format(company_id), headers=headers)

    def create_company_user(self, company_id, payload, headers=None):
        return self.post(
            "/api/companies/{0}/users".format(company_id), json=payload, headers=headers
        )

    def list_company_users(self, company_id, headers=None, params=None):
        return self.get(
            "/api/companies/{0}/users".format(company_id),
            headers=headers,
            params=params,
        )

    def get_company_user(self, company_id, user_id, headers=None):
        return self.get(
            "/api/companies/{0}/users/{1}".format(company_id, user_id),
            headers=headers,
        )

    def accept_company_user(self, company_id, user_id, headers=None):
        return self.post(
            "/api/companies/{0}/users/{1}/accept".format(company_id, user_id),
            json={},
            headers=headers,
        )

    def disable_company_user(self, company_id, user_id, headers=None):
        return self.post(
            "/api/companies/{0}/users/{1}/disable".format(company_id, user_id),
            json={},
            headers=headers,
        )

    # --- Subscription -------------------------------------------------------------

    def get_subscription(self, company_id, headers=None):
        return self.get(
            "/api/companies/{0}/subscription".format(company_id), headers=headers
        )

    def activate_subscription(self, company_id, payload, headers=None):
        return self.post(
            "/api/companies/{0}/subscription/activate".format(company_id),
            json=payload,
            headers=headers,
        )

    def change_subscription_plan(self, company_id, payload, headers=None):
        return self.post(
            "/api/companies/{0}/subscription/change_plan".format(company_id),
            json=payload,
            headers=headers,
        )

    def cancel_subscription(self, company_id, payload, headers=None):
        return self.post(
            "/api/companies/{0}/subscription/cancel".format(company_id),
            json=payload,
            headers=headers,
        )

    def reactivate_subscription(self, company_id, payload, headers=None):
        return self.post(
            "/api/companies/{0}/subscription/reactivate".format(company_id),
            json=payload,
            headers=headers,
        )

    def resume_subscription(self, company_id, headers=None):
        return self.post(
            "/api/companies/{0}/subscription/resume".format(company_id),
            json={},
            headers=headers,
        )

    # --- Payroll -------------------------------------------------------------------

    def create_payroll(self, company_id, payload, headers=None):
        return self.post(
            "/api/companies/{0}/payroll".format(company_id), json=payload, headers=headers
        )

    def get_payroll(self, company_id, headers=None):
        return self.get("/api/companies/{0}/payroll".format(company_id), headers=headers)

    def pause_payroll(self, company_id, headers=None):
        return self.post(
            "/api/companies/{0}/payroll/pause".format(company_id),
            json={},
            headers=headers,
        )

    def resume_payroll(self, company_id, headers=None):
        return self.post(
            "/api/companies/{0}/payroll/resume".format(company_id),
            json={},
            headers=headers,
        )

    def cancel_payroll(self, company_id, headers=None):
        return self.post(
            "/api/companies/{0}/payroll/cancel".format(company_id),
            json={},
            headers=headers,
        )

    def create_payroll_employee(self, company_id, payload, headers=None):
        return self.post(
            "/api/companies/{0}/payroll/employees".format(company_id),
            json=payload,
            headers=headers,
        )

    def list_payroll_employees(self, company_id, headers=None, params=None):
        return self.get(
            "/api/companies/{0}/payroll/employees".format(company_id),
            headers=headers,
            params=params,
        )

    def get_payroll_employee(self, company_id, employee_id, headers=None):
        return self.get(
            "/api/companies/{0}/payroll/employees/{1}".format(company_id, employee_id),
            headers=headers,
        )

    def terminate_payroll_employee(self, company_id, employee_id, payload, headers=None):
        return self.post(
            "/api/companies/{0}/payroll/employees/{1}/terminate".format(
                company_id, employee_id
            ),
            json=payload,
            headers=headers,
        )

    # --- Invoices ------------------------------------------------------------------

    def list_company_invoices(self, company_id, headers=None, params=None):
        return self.get(
            "/api/companies/{0}/invoices".format(company_id),
            headers=headers,
            params=params,
        )

    def get_company_invoice(self, company_id, invoice_id, headers=None):
        return self.get(
            "/api/companies/{0}/invoices/{1}".format(company_id, invoice_id),
            headers=headers,
        )

    def issue_invoice(self, company_id, invoice_id, headers=None):
        return self.post(
            "/api/companies/{0}/invoices/{1}/issue".format(company_id, invoice_id),
            json={},
            headers=headers,
        )

    def pay_invoice(self, company_id, invoice_id, headers=None):
        return self.post(
            "/api/companies/{0}/invoices/{1}/pay".format(company_id, invoice_id),
            json={},
            headers=headers,
        )

    def void_invoice(self, company_id, invoice_id, headers=None):
        return self.post(
            "/api/companies/{0}/invoices/{1}/void".format(company_id, invoice_id),
            json={},
            headers=headers,
        )

    # --- Bank connections and transactions ------------------------------------------

    def create_bank_connection(self, company_id, payload, headers=None):
        return self.post(
            "/api/companies/{0}/bank_connections".format(company_id),
            json=payload,
            headers=headers,
        )

    def list_bank_connections(self, company_id, headers=None, params=None):
        return self.get(
            "/api/companies/{0}/bank_connections".format(company_id),
            headers=headers,
            params=params,
        )

    def get_bank_connection(self, company_id, connection_id, headers=None):
        return self.get(
            "/api/companies/{0}/bank_connections/{1}".format(company_id, connection_id),
            headers=headers,
        )

    def authorize_bank_connection(self, company_id, connection_id, headers=None):
        return self.post(
            "/api/companies/{0}/bank_connections/{1}/authorize".format(
                company_id, connection_id
            ),
            json={},
            headers=headers,
        )

    def reauthorize_bank_connection(self, company_id, connection_id, payload, headers=None):
        return self.post(
            "/api/companies/{0}/bank_connections/{1}/reauthorize".format(
                company_id, connection_id
            ),
            json=payload,
            headers=headers,
        )

    def disconnect_bank_connection(self, company_id, connection_id, headers=None):
        return self.post(
            "/api/companies/{0}/bank_connections/{1}/disconnect".format(
                company_id, connection_id
            ),
            json={},
            headers=headers,
        )

    def revoke_bank_connection(self, company_id, connection_id, headers=None):
        return self.post(
            "/api/companies/{0}/bank_connections/{1}/revoke".format(
                company_id, connection_id
            ),
            json={},
            headers=headers,
        )

    def ingest_bank_transaction(self, company_id, connection_id, payload, headers=None):
        return self.post(
            "/api/companies/{0}/bank_connections/{1}/transactions".format(
                company_id, connection_id
            ),
            json=payload,
            headers=headers,
        )

    def list_bank_transactions_for_connection(
        self, company_id, connection_id, headers=None, params=None
    ):
        return self.get(
            "/api/companies/{0}/bank_connections/{1}/transactions".format(
                company_id, connection_id
            ),
            headers=headers,
            params=params,
        )

    def list_bank_transactions(self, company_id, headers=None, params=None):
        return self.get(
            "/api/companies/{0}/bank_transactions".format(company_id),
            headers=headers,
            params=params,
        )

    def get_bank_transaction(self, company_id, txn_id, headers=None):
        return self.get(
            "/api/companies/{0}/bank_transactions/{1}".format(company_id, txn_id),
            headers=headers,
        )

    def categorize_bank_transaction(self, company_id, txn_id, payload, headers=None):
        return self.post(
            "/api/companies/{0}/bank_transactions/{1}/categorize".format(
                company_id, txn_id
            ),
            json=payload,
            headers=headers,
        )

    def accept_suggestion(self, company_id, txn_id, headers=None):
        return self.post(
            "/api/companies/{0}/bank_transactions/{1}/accept_suggestion".format(
                company_id, txn_id
            ),
            json={},
            headers=headers,
        )

    def reject_suggestion(self, company_id, txn_id, headers=None):
        return self.post(
            "/api/companies/{0}/bank_transactions/{1}/reject_suggestion".format(
                company_id, txn_id
            ),
            json={},
            headers=headers,
        )

    def uncategorize_bank_transaction(self, company_id, txn_id, headers=None):
        return self.post(
            "/api/companies/{0}/bank_transactions/{1}/uncategorize".format(
                company_id, txn_id
            ),
            json={},
            headers=headers,
        )

    def exclude_bank_transaction(self, company_id, txn_id, headers=None):
        return self.post(
            "/api/companies/{0}/bank_transactions/{1}/exclude".format(
                company_id, txn_id
            ),
            json={},
            headers=headers,
        )

    def unexclude_bank_transaction(self, company_id, txn_id, headers=None):
        return self.post(
            "/api/companies/{0}/bank_transactions/{1}/unexclude".format(
                company_id, txn_id
            ),
            json={},
            headers=headers,
        )

    # --- Categories ------------------------------------------------------------------

    def create_category(self, company_id, payload, headers=None):
        return self.post(
            "/api/companies/{0}/categories".format(company_id),
            json=payload,
            headers=headers,
        )

    def list_categories(self, company_id, headers=None, params=None):
        return self.get(
            "/api/companies/{0}/categories".format(company_id),
            headers=headers,
            params=params,
        )

    # --- Categorization rules ---------------------------------------------------------

    def create_categorization_rule(self, company_id, payload, headers=None):
        return self.post(
            "/api/companies/{0}/categorization_rules".format(company_id),
            json=payload,
            headers=headers,
        )

    def list_categorization_rules(self, company_id, headers=None, params=None):
        return self.get(
            "/api/companies/{0}/categorization_rules".format(company_id),
            headers=headers,
            params=params,
        )

    def get_categorization_rule(self, company_id, rule_id, headers=None):
        return self.get(
            "/api/companies/{0}/categorization_rules/{1}".format(company_id, rule_id),
            headers=headers,
        )

    def pause_categorization_rule(self, company_id, rule_id, headers=None):
        return self.post(
            "/api/companies/{0}/categorization_rules/{1}/pause".format(
                company_id, rule_id
            ),
            json={},
            headers=headers,
        )

    def resume_categorization_rule(self, company_id, rule_id, headers=None):
        return self.post(
            "/api/companies/{0}/categorization_rules/{1}/resume".format(
                company_id, rule_id
            ),
            json={},
            headers=headers,
        )

    def delete_categorization_rule(self, company_id, rule_id, headers=None):
        return self.delete(
            "/api/companies/{0}/categorization_rules/{1}".format(company_id, rule_id),
            headers=headers,
        )

    # --- Reconciliations ----------------------------------------------------------------

    def create_reconciliation(self, company_id, payload, headers=None):
        return self.post(
            "/api/companies/{0}/reconciliations".format(company_id),
            json=payload,
            headers=headers,
        )

    def list_reconciliations(self, company_id, headers=None, params=None):
        return self.get(
            "/api/companies/{0}/reconciliations".format(company_id),
            headers=headers,
            params=params,
        )

    def get_reconciliation(self, company_id, recon_id, headers=None):
        return self.get(
            "/api/companies/{0}/reconciliations/{1}".format(company_id, recon_id),
            headers=headers,
        )

    def start_reconciliation(self, company_id, recon_id, headers=None):
        return self.post(
            "/api/companies/{0}/reconciliations/{1}/start".format(company_id, recon_id),
            json={},
            headers=headers,
        )

    def complete_reconciliation(self, company_id, recon_id, headers=None):
        return self.post(
            "/api/companies/{0}/reconciliations/{1}/complete".format(
                company_id, recon_id
            ),
            json={},
            headers=headers,
        )

    def abandon_reconciliation(self, company_id, recon_id, headers=None):
        return self.post(
            "/api/companies/{0}/reconciliations/{1}/abandon".format(
                company_id, recon_id
            ),
            json={},
            headers=headers,
        )

    # --- Integrations and conflicts ---------------------------------------------------

    def create_integration(self, company_id, payload, headers=None):
        return self.post(
            "/api/companies/{0}/integrations".format(company_id),
            json=payload,
            headers=headers,
        )

    def list_integrations(self, company_id, headers=None, params=None):
        return self.get(
            "/api/companies/{0}/integrations".format(company_id),
            headers=headers,
            params=params,
        )

    def get_integration(self, company_id, integration_id, headers=None):
        return self.get(
            "/api/companies/{0}/integrations/{1}".format(company_id, integration_id),
            headers=headers,
        )

    def activate_integration(self, company_id, integration_id, headers=None):
        return self.post(
            "/api/companies/{0}/integrations/{1}/activate".format(
                company_id, integration_id
            ),
            json={},
            headers=headers,
        )

    def resume_integration(self, company_id, integration_id, headers=None):
        return self.post(
            "/api/companies/{0}/integrations/{1}/resume".format(
                company_id, integration_id
            ),
            json={},
            headers=headers,
        )

    def disconnect_integration(self, company_id, integration_id, headers=None):
        return self.post(
            "/api/companies/{0}/integrations/{1}/disconnect".format(
                company_id, integration_id
            ),
            json={},
            headers=headers,
        )

    def record_sync_conflict(self, company_id, integration_id, payload, headers=None):
        return self.post(
            "/api/companies/{0}/integrations/{1}/conflicts".format(
                company_id, integration_id
            ),
            json=payload,
            headers=headers,
        )

    def list_sync_conflicts(self, company_id, integration_id, headers=None, params=None):
        return self.get(
            "/api/companies/{0}/integrations/{1}/conflicts".format(
                company_id, integration_id
            ),
            headers=headers,
            params=params,
        )

    def resolve_sync_conflict(self, company_id, integration_id, conflict_id, payload, headers=None):
        return self.post(
            "/api/companies/{0}/integrations/{1}/conflicts/{2}/resolve".format(
                company_id, integration_id, conflict_id
            ),
            json=payload,
            headers=headers,
        )

    # --- Migration jobs ------------------------------------------------------------------

    def create_migration_job(self, company_id, payload, headers=None):
        return self.post(
            "/api/companies/{0}/migration_jobs".format(company_id),
            json=payload,
            headers=headers,
        )

    def list_migration_jobs(self, company_id, headers=None, params=None):
        return self.get(
            "/api/companies/{0}/migration_jobs".format(company_id),
            headers=headers,
            params=params,
        )

    def get_migration_job(self, company_id, migration_id, headers=None):
        return self.get(
            "/api/companies/{0}/migration_jobs/{1}".format(company_id, migration_id),
            headers=headers,
        )

    def start_migration_job(self, company_id, migration_id, headers=None):
        return self.post(
            "/api/companies/{0}/migration_jobs/{1}/start".format(
                company_id, migration_id
            ),
            json={},
            headers=headers,
        )

    def complete_migration_job(self, company_id, migration_id, payload, headers=None):
        return self.post(
            "/api/companies/{0}/migration_jobs/{1}/complete".format(
                company_id, migration_id
            ),
            json=payload,
            headers=headers,
        )

    def cancel_migration_job(self, company_id, migration_id, headers=None):
        return self.post(
            "/api/companies/{0}/migration_jobs/{1}/cancel".format(
                company_id, migration_id
            ),
            json={},
            headers=headers,
        )

    # --- Billing transfers ----------------------------------------------------------------

    def create_billing_transfer(self, company_id, payload, headers=None):
        return self.post(
            "/api/companies/{0}/billing_transfers".format(company_id),
            json=payload,
            headers=headers,
        )

    def list_billing_transfers(self, company_id, headers=None, params=None):
        return self.get(
            "/api/companies/{0}/billing_transfers".format(company_id),
            headers=headers,
            params=params,
        )

    def get_billing_transfer(self, company_id, transfer_id, headers=None):
        return self.get(
            "/api/companies/{0}/billing_transfers/{1}".format(company_id, transfer_id),
            headers=headers,
        )

    def client_accept_billing_transfer(self, company_id, transfer_id, payload, headers=None):
        return self.post(
            "/api/companies/{0}/billing_transfers/{1}/accept".format(
                company_id, transfer_id
            ),
            json=payload,
            headers=headers,
        )

    def counter_billing_transfer(self, company_id, transfer_id, headers=None):
        return self.post(
            "/api/companies/{0}/billing_transfers/{1}/counter".format(
                company_id, transfer_id
            ),
            json={},
            headers=headers,
        )

    def decline_billing_transfer(self, company_id, transfer_id, payload, headers=None):
        return self.post(
            "/api/companies/{0}/billing_transfers/{1}/decline".format(
                company_id, transfer_id
            ),
            json=payload,
            headers=headers,
        )

    def cancel_billing_transfer(self, company_id, transfer_id, headers=None):
        return self.post(
            "/api/companies/{0}/billing_transfers/{1}/cancel".format(
                company_id, transfer_id
            ),
            json={},
            headers=headers,
        )

    def firm_accept_billing_transfer(self, firm_id, transfer_id, headers=None):
        return self.post(
            "/api/firms/{0}/billing_transfers/{1}/accept".format(firm_id, transfer_id),
            json={},
            headers=headers,
        )

    # --- Access grants ---------------------------------------------------------------------

    def create_access_grant(self, company_id, payload, headers=None):
        return self.post(
            "/api/companies/{0}/access_grants".format(company_id),
            json=payload,
            headers=headers,
        )

    def list_access_grants(self, company_id, headers=None, params=None):
        return self.get(
            "/api/companies/{0}/access_grants".format(company_id),
            headers=headers,
            params=params,
        )

    def get_access_grant(self, company_id, grant_id, headers=None):
        return self.get(
            "/api/companies/{0}/access_grants/{1}".format(company_id, grant_id),
            headers=headers,
        )

    def revoke_access_grant(self, company_id, grant_id, headers=None):
        return self.post(
            "/api/companies/{0}/access_grants/{1}/revoke".format(company_id, grant_id),
            json={},
            headers=headers,
        )

    def accept_access_grant(self, firm_id, grant_id, headers=None):
        return self.post(
            "/api/firms/{0}/access_grants/{1}/accept".format(firm_id, grant_id),
            json={},
            headers=headers,
        )

    # --- Exports ---------------------------------------------------------------------------

    def create_export_request(self, company_id, payload, headers=None):
        return self.post(
            "/api/companies/{0}/exports".format(company_id),
            json=payload,
            headers=headers,
        )

    def list_export_requests(self, company_id, headers=None, params=None):
        return self.get(
            "/api/companies/{0}/exports".format(company_id),
            headers=headers,
            params=params,
        )

    def get_export_request(self, company_id, export_id, headers=None):
        return self.get(
            "/api/companies/{0}/exports/{1}".format(company_id, export_id),
            headers=headers,
        )

    def mark_export_ready(self, company_id, export_id, headers=None):
        return self.post(
            "/api/companies/{0}/exports/{1}/mark_ready".format(company_id, export_id),
            json={},
            headers=headers,
        )

    def download_export(self, company_id, export_id, headers=None):
        return self.post(
            "/api/companies/{0}/exports/{1}/download".format(company_id, export_id),
            json={},
            headers=headers,
        )

    # --- Flat filtered-list GETs (FK reverse reachability) ----------------------------------

    def get_subscription_by_id(self, subscription_id, headers=None):
        return self.get(
            "/api/subscriptions/{0}".format(subscription_id), headers=headers
        )

    def list_subscriptions(self, headers=None, params=None):
        return self.get("/api/subscriptions", headers=headers, params=params)

    def get_payroll_addon_by_id(self, addon_id, headers=None):
        return self.get("/api/payroll_addons/{0}".format(addon_id), headers=headers)

    def list_payroll_addons(self, headers=None, params=None):
        return self.get("/api/payroll_addons", headers=headers, params=params)

    def get_payroll_employee_by_id(self, employee_id, headers=None):
        return self.get(
            "/api/payroll_employees/{0}".format(employee_id), headers=headers
        )

    def list_payroll_employees_flat(self, headers=None, params=None):
        return self.get("/api/payroll_employees", headers=headers, params=params)

    def get_invoice_by_id(self, invoice_id, headers=None):
        return self.get("/api/invoices/{0}".format(invoice_id), headers=headers)

    def list_invoices_flat(self, headers=None, params=None):
        return self.get("/api/invoices", headers=headers, params=params)

    def get_bank_transaction_by_id(self, txn_id, headers=None):
        return self.get("/api/bank_transactions/{0}".format(txn_id), headers=headers)

    def list_bank_transactions_flat(self, headers=None, params=None):
        return self.get("/api/bank_transactions", headers=headers, params=params)

    def get_categorization_rule_by_id(self, rule_id, headers=None):
        return self.get(
            "/api/categorization_rules/{0}".format(rule_id), headers=headers
        )

    def list_categorization_rules_flat(self, headers=None, params=None):
        return self.get("/api/categorization_rules", headers=headers, params=params)

    def get_reconciliation_by_id(self, recon_id, headers=None):
        return self.get("/api/reconciliations/{0}".format(recon_id), headers=headers)

    def list_reconciliations_flat(self, headers=None, params=None):
        return self.get("/api/reconciliations", headers=headers, params=params)

    def get_sync_conflict_by_id(self, conflict_id, headers=None):
        return self.get("/api/sync_conflicts/{0}".format(conflict_id), headers=headers)

    def list_sync_conflicts_flat(self, headers=None, params=None):
        return self.get("/api/sync_conflicts", headers=headers, params=params)

    def get_billing_transfer_by_id(self, transfer_id, headers=None):
        return self.get(
            "/api/billing_transfers/{0}".format(transfer_id), headers=headers
        )

    def list_billing_transfers_flat(self, headers=None, params=None):
        return self.get("/api/billing_transfers", headers=headers, params=params)

    def get_access_grant_by_id(self, grant_id, headers=None):
        return self.get("/api/access_grants/{0}".format(grant_id), headers=headers)

    def list_access_grants_flat(self, headers=None, params=None):
        return self.get("/api/access_grants", headers=headers, params=params)

    def get_export_request_by_id(self, export_id, headers=None):
        return self.get("/api/export_requests/{0}".format(export_id), headers=headers)

    def list_export_requests_flat(self, headers=None, params=None):
        return self.get("/api/export_requests", headers=headers, params=params)


api_client = ApiClient()
