"""API client: one method per endpoint exposed by the PRD (§4)."""

from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Thin domain client. Every method returns the raw response."""

    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Stores ---
    def create_store(self, payload, headers):
        return self._request("POST", "/stores", payload, headers)

    def list_stores(self, headers, params=None):
        return self._request("GET", "/stores", headers=headers, params=params)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/stores/{store_id}", headers=headers)

    def activate_store(self, store_id, headers):
        return self._request("POST", f"/stores/{store_id}/activate", {}, headers)

    def suspend_store(self, store_id, headers):
        return self._request("POST", f"/stores/{store_id}/suspend", {}, headers)

    def reinstate_store(self, store_id, headers):
        return self._request("POST", f"/stores/{store_id}/reinstate", {}, headers)

    def list_store_repairs(self, store_id, headers, params=None):
        return self._request("GET", f"/stores/{store_id}/repairs",
                             headers=headers, params=params)

    def list_store_credit_applications(self, store_id, headers, params=None):
        return self._request("GET", f"/stores/{store_id}/credit-applications",
                             headers=headers, params=params)

    def list_store_registrations(self, store_id, headers, params=None):
        return self._request("GET", f"/stores/{store_id}/service-plan-registrations",
                             headers=headers, params=params)

    def list_store_inspection_visits(self, store_id, headers, params=None):
        return self._request("GET", f"/stores/{store_id}/inspection-visits",
                             headers=headers, params=params)

    def list_store_purchases(self, store_id, headers, params=None):
        return self._request("GET", f"/stores/{store_id}/purchases",
                             headers=headers, params=params)

    # --- Credit limit registry ---
    def create_registry_row(self, payload, headers):
        return self._request("POST", "/credit-limit-registry-state", payload, headers)

    def list_registry_rows(self, headers, params=None):
        return self._request("GET", "/credit-limit-registry-state",
                             headers=headers, params=params)

    # --- Service plan regulations ---
    def create_regulation(self, payload, headers):
        return self._request("POST", "/service-plan-regulations", payload, headers)

    def list_regulations(self, headers, params=None):
        return self._request("GET", "/service-plan-regulations",
                             headers=headers, params=params)

    # --- Vendor shops ---
    def create_vendor_shop(self, payload, headers):
        return self._request("POST", "/vendor-shops", payload, headers)

    def list_vendor_shops(self, headers, params=None):
        return self._request("GET", "/vendor-shops", headers=headers, params=params)

    def list_shop_repairs(self, shop_id, headers, params=None):
        return self._request("GET", f"/vendor-shops/{shop_id}/repairs",
                             headers=headers, params=params)

    # --- Protection bundles ---
    def create_bundle(self, payload, headers):
        return self._request("POST", "/protection-bundles", payload, headers)

    def list_bundles(self, headers, params=None):
        return self._request("GET", "/protection-bundles", headers=headers, params=params)

    def retire_bundle(self, bundle_id, headers):
        return self._request("POST", f"/protection-bundles/{bundle_id}/retire", {}, headers)

    def list_bundle_registrations(self, bundle_id, headers, params=None):
        return self._request("GET", f"/protection-bundles/{bundle_id}/service-plan-registrations",
                             headers=headers, params=params)

    # --- Customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def reinstate_customer(self, customer_id, headers):
        return self._request("POST", f"/customers/{customer_id}/reinstate", {}, headers)

    def close_customer(self, customer_id, headers):
        return self._request("POST", f"/customers/{customer_id}/close", {}, headers)

    def list_customer_credit_applications(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/credit-applications",
                             headers=headers, params=params)

    def list_customer_plans(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/promotional-plans",
                             headers=headers, params=params)

    def list_customer_registrations(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/service-plan-registrations",
                             headers=headers, params=params)

    def list_customer_diamonds(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/diamonds",
                             headers=headers, params=params)

    def list_customer_purchases(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/purchases",
                             headers=headers, params=params)

    def list_customer_custom_design_orders(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/custom-design-orders",
                             headers=headers, params=params)

    def list_customer_statements(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/billing-statements",
                             headers=headers, params=params)

    # --- Credit applications ---
    def create_credit_application(self, payload, headers):
        return self._request("POST", "/credit-applications", payload, headers)

    def list_credit_applications(self, headers, params=None):
        return self._request("GET", "/credit-applications", headers=headers, params=params)

    def get_credit_application(self, application_id, headers):
        return self._request("GET", f"/credit-applications/{application_id}", headers=headers)

    def decide_credit_application(self, application_id, payload, headers):
        return self._request("POST", f"/credit-applications/{application_id}/decision",
                             payload, headers)

    def accept_credit_application(self, application_id, headers):
        return self._request("POST", f"/credit-applications/{application_id}/accept", {}, headers)

    def decline_credit_application(self, application_id, headers):
        return self._request("POST", f"/credit-applications/{application_id}/decline-counter",
                             {}, headers)

    def expire_credit_applications_due(self, headers):
        return self._request("POST", "/credit-applications/expire-due", {}, headers)

    # --- Promotional plans ---
    def create_promotional_plan(self, payload, headers):
        return self._request("POST", "/promotional-plans", payload, headers)

    def list_promotional_plans(self, headers, params=None):
        return self._request("GET", "/promotional-plans", headers=headers, params=params)

    def get_promotional_plan(self, plan_id, headers):
        return self._request("GET", f"/promotional-plans/{plan_id}", headers=headers)

    def payoff_promotional_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/promotional-plans/{plan_id}/payoff", payload, headers)

    def reinstate_promotional_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/promotional-plans/{plan_id}/reinstate", payload, headers)

    def cancel_promotional_plan(self, plan_id, headers):
        return self._request("POST", f"/promotional-plans/{plan_id}/cancel", {}, headers)

    def capitalize_plans_due(self, headers):
        return self._request("POST", "/plans/capitalize-due", {}, headers)

    def default_plans_due(self, headers):
        return self._request("POST", "/plans/default-due", {}, headers)

    def list_plan_ledger_entries(self, plan_id, headers, params=None):
        return self._request("GET", f"/promotional-plans/{plan_id}/payoff-ledger-entries",
                             headers=headers, params=params)

    # --- Payoff ledger ---
    def create_ledger_entry(self, payload, headers):
        return self._request("POST", "/payoff-ledger-entries", payload, headers)

    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/payoff-ledger-entries", headers=headers, params=params)

    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/payoff-ledger-entries/{entry_id}", headers=headers)

    def list_repair_ledger_entries(self, repair_id, headers, params=None):
        return self._request("GET", f"/repairs/{repair_id}/payoff-ledger-entries",
                             headers=headers, params=params)

    # --- Diamonds ---
    def create_diamond(self, payload, headers):
        return self._request("POST", "/diamonds", payload, headers)

    def list_diamonds(self, headers, params=None):
        return self._request("GET", "/diamonds", headers=headers, params=params)

    def get_diamond(self, diamond_id, headers):
        return self._request("GET", f"/diamonds/{diamond_id}", headers=headers)

    def list_diamond_registrations(self, diamond_id, headers, params=None):
        return self._request("GET", f"/diamonds/{diamond_id}/service-plan-registrations",
                             headers=headers, params=params)

    # --- Service plan registrations ---
    def create_registration(self, payload, headers):
        return self._request("POST", "/service-plan-registrations", payload, headers)

    def list_registrations(self, headers, params=None):
        return self._request("GET", "/service-plan-registrations",
                             headers=headers, params=params)

    def get_registration(self, registration_id, headers):
        return self._request("GET", f"/service-plan-registrations/{registration_id}",
                             headers=headers)

    def log_inspection_exam(self, registration_id, payload, headers):
        return self._request("POST", f"/service-plan-registrations/{registration_id}/exams",
                             payload, headers)

    def renew_registration(self, registration_id, headers):
        return self._request("POST", f"/service-plan-registrations/{registration_id}/renew",
                             {}, headers)

    def terminate_registration(self, registration_id, headers):
        return self._request("POST", f"/service-plan-registrations/{registration_id}/terminate",
                             {}, headers)

    def void_registration(self, registration_id, headers):
        return self._request("POST", f"/service-plan-registrations/{registration_id}/void",
                             {}, headers)

    def run_inspection_reminders(self, headers):
        return self._request("POST", "/inspection-reminders/run", {}, headers)

    def lapse_registrations_due(self, headers):
        return self._request("POST", "/service-plan-registrations/lapse-due", {}, headers)

    def list_registration_inspection_visits(self, registration_id, headers, params=None):
        return self._request("GET", f"/service-plan-registrations/{registration_id}/inspection-visits",
                             headers=headers, params=params)

    def list_registration_repairs(self, registration_id, headers, params=None):
        return self._request("GET", f"/service-plan-registrations/{registration_id}/repairs",
                             headers=headers, params=params)

    # --- Inspection visits ---
    def create_inspection_visit(self, payload, headers):
        return self._request("POST", "/inspection-visits", payload, headers)

    def list_inspection_visits(self, headers, params=None):
        return self._request("GET", "/inspection-visits", headers=headers, params=params)

    def get_inspection_visit(self, visit_id, headers):
        return self._request("GET", f"/inspection-visits/{visit_id}", headers=headers)

    def claim_inspection_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/inspection-visits/{visit_id}/claim", payload, headers)

    def no_show_inspection_visit(self, visit_id, headers):
        return self._request("POST", f"/inspection-visits/{visit_id}/no-show", {}, headers)

    # --- Repairs ---
    def create_repair(self, payload, headers):
        return self._request("POST", "/repairs", payload, headers)

    def list_repairs(self, headers, params=None):
        return self._request("GET", "/repairs", headers=headers, params=params)

    def get_repair(self, repair_id, headers):
        return self._request("GET", f"/repairs/{repair_id}", headers=headers)

    def list_repair_appraisals(self, repair_id, headers, params=None):
        return self._request("GET", f"/repairs/{repair_id}/appraisals",
                             headers=headers, params=params)

    def list_repair_holds(self, repair_id, headers, params=None):
        return self._request("GET", f"/repairs/{repair_id}/holds",
                             headers=headers, params=params)

    def route_repair(self, repair_id, headers):
        return self._request("POST", f"/repairs/{repair_id}/route", {}, headers)

    def arrive_repair_at_vendor(self, repair_id, headers):
        return self._request("POST", f"/repairs/{repair_id}/arrive-vendor", {}, headers)

    def submit_repair_for_qc(self, repair_id, headers):
        return self._request("POST", f"/repairs/{repair_id}/submit-qc", {}, headers)

    def verify_repair(self, repair_id, headers):
        return self._request("POST", f"/repairs/{repair_id}/verify", {}, headers)

    def declare_repair_unrepairable(self, repair_id, headers):
        return self._request("POST", f"/repairs/{repair_id}/declare-unrepairable", {}, headers)

    def declare_repair_loss(self, repair_id, headers):
        return self._request("POST", f"/repairs/{repair_id}/declare-loss", {}, headers)

    def create_repair_hold(self, repair_id, payload, headers):
        return self._request("POST", f"/repairs/{repair_id}/holds", payload, headers)

    def abandon_repairs_overdue(self, headers):
        return self._request("POST", "/repairs/abandon-overdue", {}, headers)

    # --- Appraisals ---
    def create_appraisal(self, payload, headers):
        return self._request("POST", "/appraisals", payload, headers)

    def list_appraisals(self, headers, params=None):
        return self._request("GET", "/appraisals", headers=headers, params=params)

    def get_appraisal(self, appraisal_id, headers):
        return self._request("GET", f"/appraisals/{appraisal_id}", headers=headers)

    def advise_insurer(self, appraisal_id, payload, headers):
        return self._request("POST", f"/appraisals/{appraisal_id}/advise-insurer",
                             payload, headers)

    # --- Purchases ---
    def create_purchase(self, payload, headers):
        return self._request("POST", "/purchases", payload, headers)

    def list_purchases(self, headers, params=None):
        return self._request("GET", "/purchases", headers=headers, params=params)

    def get_purchase(self, purchase_id, headers):
        return self._request("GET", f"/purchases/{purchase_id}", headers=headers)

    def stamp_trade_up_credit(self, purchase_id, payload, headers):
        return self._request("POST", f"/purchases/{purchase_id}/trade-up-credit",
                             payload, headers)

    def preview_trade_up(self, purchase_id, headers, params=None):
        return self._request("GET", f"/purchases/{purchase_id}/trade-up-preview",
                             headers=headers, params=params)

    def complete_purchase(self, purchase_id, headers):
        return self._request("POST", f"/purchases/{purchase_id}/complete", {}, headers)

    def list_purchase_plans(self, purchase_id, headers, params=None):
        return self._request("GET", f"/purchases/{purchase_id}/promotional-plans",
                             headers=headers, params=params)

    def list_purchase_registrations(self, purchase_id, headers, params=None):
        return self._request("GET", f"/purchases/{purchase_id}/service-plan-registrations",
                             headers=headers, params=params)

    def list_purchase_trade_ups(self, purchase_id, headers, params=None):
        return self._request("GET", f"/purchases/{purchase_id}/purchases",
                             headers=headers, params=params)

    # --- Custom design orders ---
    def create_custom_design_order(self, payload, headers):
        return self._request("POST", "/custom-design-orders", payload, headers)

    def list_custom_design_orders(self, headers, params=None):
        return self._request("GET", "/custom-design-orders", headers=headers, params=params)

    def get_custom_design_order(self, design_id, headers):
        return self._request("GET", f"/custom-design-orders/{design_id}", headers=headers)

    def request_cad_revision(self, design_id, headers):
        return self._request("POST", f"/custom-design-orders/{design_id}/revisions", {}, headers)

    def approve_cad(self, design_id, headers):
        return self._request("POST", f"/custom-design-orders/{design_id}/cad-approval", {}, headers)

    def start_design_production(self, design_id, headers):
        return self._request("POST", f"/custom-design-orders/{design_id}/start-production",
                             {}, headers)

    def recall_design(self, design_id, payload, headers):
        return self._request("POST", f"/custom-design-orders/{design_id}/recall",
                             payload, headers)

    def complete_custom_design_order(self, design_id, headers):
        return self._request("POST", f"/custom-design-orders/{design_id}/complete", {}, headers)

    def cancel_custom_design_order(self, design_id, headers):
        return self._request("POST", f"/custom-design-orders/{design_id}/cancel", {}, headers)

    # --- Billing statements ---
    def create_billing_statement(self, payload, headers):
        return self._request("POST", "/billing-statements", payload, headers)

    def list_billing_statements(self, headers, params=None):
        return self._request("GET", "/billing-statements", headers=headers, params=params)

    def get_billing_statement(self, statement_id, headers):
        return self._request("GET", f"/billing-statements/{statement_id}", headers=headers)

    def close_billing_statement(self, statement_id, headers):
        return self._request("POST", f"/billing-statements/{statement_id}/close", {}, headers)


api_client = ApiClient()

__all__ = ["api_client", "ApiClient", "Optional"]