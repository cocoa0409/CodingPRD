"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- licensees ---
    def create_licensee(self, payload, headers):
        return self._request("POST", "/licensing/licensees", payload, headers)

    def get_licensee(self, licensee_id, headers):
        return self._request("GET", f"/licensing/licensees/{licensee_id}", headers=headers)

    def list_licensees(self, headers, params=None):
        return self._request("GET", "/licensing/licensees", headers=headers, params=params)

    # --- host venues ---
    def create_host_venue(self, payload, headers):
        return self._request("POST", "/licensing/host-venues", payload, headers)

    def get_host_venue(self, venue_id, headers):
        return self._request("GET", f"/licensing/host-venues/{venue_id}", headers=headers)

    def list_host_venues(self, headers, params=None):
        return self._request("GET", "/licensing/host-venues", headers=headers, params=params)

    def update_host_venue(self, venue_id, payload, headers):
        return self._request("PATCH", f"/licensing/host-venues/{venue_id}", payload, headers)

    # --- license agreements ---
    def create_license_agreement(self, payload, headers):
        return self._request("POST", "/licensing/license-agreements", payload, headers)

    def get_license_agreement(self, agreement_id, headers):
        return self._request("GET", f"/licensing/license-agreements/{agreement_id}", headers=headers)

    def list_license_agreements(self, headers, params=None):
        return self._request("GET", "/licensing/license-agreements", headers=headers, params=params)

    def submit_license_agreement(self, agreement_id, headers):
        return self._request("POST", f"/licensing/license-agreements/{agreement_id}/submit", {}, headers)

    def accept_license_agreement(self, agreement_id, headers):
        return self._request("POST", f"/licensing/license-agreements/{agreement_id}/accept", {}, headers)

    def suspend_license_agreement(self, agreement_id, headers):
        return self._request("POST", f"/licensing/license-agreements/{agreement_id}/suspend", {}, headers)

    def reinstate_license_agreement(self, agreement_id, headers):
        return self._request("POST", f"/licensing/license-agreements/{agreement_id}/reinstate", {}, headers)

    def terminate_license_agreement(self, agreement_id, headers):
        return self._request("POST", f"/licensing/license-agreements/{agreement_id}/terminate", {}, headers)

    def sweep_expiry_license_agreement(self, agreement_id, headers):
        return self._request("POST", f"/licensing/license-agreements/{agreement_id}/sweep-expiry", {}, headers)

    def amend_license_agreement(self, agreement_id, payload, headers):
        return self._request("PATCH", f"/licensing/license-agreements/{agreement_id}", payload, headers)

    # --- stores ---
    def create_store(self, agreement_id, payload, headers):
        return self._request("POST", f"/licensing/license-agreements/{agreement_id}/stores", payload, headers)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/licensing/stores/{store_id}", headers=headers)

    def list_agreement_stores(self, agreement_id, headers, params=None):
        return self._request("GET", f"/licensing/license-agreements/{agreement_id}/stores", headers=headers, params=params)

    def request_store_certification(self, store_id, headers):
        return self._request("POST", f"/licensing/stores/{store_id}/request-certification", {}, headers)

    def begin_store_operations(self, store_id, headers):
        return self._request("POST", f"/licensing/stores/{store_id}/begin-operations", {}, headers)

    def suspend_store(self, store_id, headers):
        return self._request("POST", f"/licensing/stores/{store_id}/suspend", {}, headers)

    def resume_store(self, store_id, headers):
        return self._request("POST", f"/licensing/stores/{store_id}/resume", {}, headers)

    def delicense_store(self, store_id, headers):
        return self._request("POST", f"/licensing/stores/{store_id}/delicense", {}, headers)

    # --- product items ---
    def create_product_item(self, payload, headers):
        return self._request("POST", "/licensing/product-items", payload, headers)

    def get_product_item(self, product_item_id, headers):
        return self._request("GET", f"/licensing/product-items/{product_item_id}", headers=headers)

    def list_product_items(self, headers, params=None):
        return self._request("GET", "/licensing/product-items", headers=headers, params=params)

    # --- assortment items ---
    def create_assortment_item(self, store_id, payload, headers):
        return self._request("POST", f"/licensing/stores/{store_id}/assortment-items", payload, headers)

    def get_assortment_item(self, assortment_item_id, headers):
        return self._request("GET", f"/licensing/store-assortment-items/{assortment_item_id}", headers=headers)

    def list_assortment_items(self, headers, params=None):
        return self._request("GET", "/licensing/store-assortment-items", headers=headers, params=params)

    def delete_assortment_item(self, assortment_item_id, headers):
        return self._request("DELETE", f"/licensing/store-assortment-items/{assortment_item_id}", headers=headers)

    # --- distributors ---
    def create_distributor(self, payload, headers):
        return self._request("POST", "/licensing/distributors", payload, headers)

    def get_distributor(self, distributor_id, headers):
        return self._request("GET", f"/licensing/distributors/{distributor_id}", headers=headers)

    def list_distributors(self, headers, params=None):
        return self._request("GET", "/licensing/distributors", headers=headers, params=params)

    def update_distributor(self, distributor_id, payload, headers):
        return self._request("PATCH", f"/licensing/distributors/{distributor_id}", payload, headers)

    # --- supply orders ---
    def create_supply_order(self, store_id, payload, headers):
        return self._request("POST", f"/licensing/stores/{store_id}/supply-orders", payload, headers)

    def get_supply_order(self, order_id, headers):
        return self._request("GET", f"/licensing/supply-orders/{order_id}", headers=headers)

    def list_supply_orders(self, headers, params=None):
        return self._request("GET", "/licensing/supply-orders", headers=headers, params=params)

    def submit_supply_order(self, order_id, headers):
        return self._request("POST", f"/licensing/supply-orders/{order_id}/submit", {}, headers)

    def approve_supply_order(self, order_id, headers):
        return self._request("POST", f"/licensing/supply-orders/{order_id}/approve", {}, headers)

    def reject_supply_order(self, order_id, payload, headers):
        return self._request("POST", f"/licensing/supply-orders/{order_id}/reject", payload, headers)

    def ship_supply_order(self, order_id, headers):
        return self._request("POST", f"/licensing/supply-orders/{order_id}/ship", {}, headers)

    def receive_supply_order(self, order_id, payload, headers):
        return self._request("POST", f"/licensing/supply-orders/{order_id}/receive", payload, headers)

    def dispute_supply_order(self, order_id, payload, headers):
        return self._request("POST", f"/licensing/supply-orders/{order_id}/dispute", payload, headers)

    def resolve_supply_order_dispute(self, order_id, payload, headers):
        return self._request("POST", f"/licensing/supply-orders/{order_id}/resolve-dispute", payload, headers)

    def cancel_supply_order(self, order_id, headers):
        return self._request("POST", f"/licensing/supply-orders/{order_id}/cancel", {}, headers)

    # --- supply order lines ---
    def get_supply_order_line(self, line_id, headers):
        return self._request("GET", f"/licensing/supply-order-lines/{line_id}", headers=headers)

    def list_supply_order_lines(self, headers, params=None):
        return self._request("GET", "/licensing/supply-order-lines", headers=headers, params=params)

    # --- employees ---
    def create_employee(self, licensee_id, payload, headers):
        return self._request("POST", f"/licensing/licensees/{licensee_id}/employees", payload, headers)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/licensing/employees/{employee_id}", headers=headers)

    def list_employees(self, headers, params=None):
        return self._request("GET", "/licensing/employees", headers=headers, params=params)

    # --- certifications ---
    def create_certification(self, employee_id, payload, headers):
        return self._request("POST", f"/licensing/employees/{employee_id}/certifications", payload, headers)

    def get_certification(self, certification_id, headers):
        return self._request("GET", f"/licensing/certifications/{certification_id}", headers=headers)

    def list_certifications(self, headers, params=None):
        return self._request("GET", "/licensing/certifications", headers=headers, params=params)

    def record_certification_exam(self, certification_id, payload, headers):
        return self._request("POST", f"/licensing/certifications/{certification_id}/record-exam", payload, headers)

    def audit_verify_certification(self, certification_id, headers):
        return self._request("POST", f"/licensing/certifications/{certification_id}/audit-verify", {}, headers)

    def audit_reject_certification(self, certification_id, payload, headers):
        return self._request("POST", f"/licensing/certifications/{certification_id}/audit-reject", payload, headers)

    def sweep_certification_expiry(self, headers):
        return self._request("POST", "/licensing/certifications/sweep-expiry", {}, headers)

    # --- sales reports ---
    def create_sales_report(self, store_id, payload, headers):
        return self._request("POST", f"/licensing/stores/{store_id}/sales-reports", payload, headers)

    def get_sales_report(self, report_id, headers):
        return self._request("GET", f"/licensing/sales-reports/{report_id}", headers=headers)

    def list_sales_reports(self, headers, params=None):
        return self._request("GET", "/licensing/sales-reports", headers=headers, params=params)

    def finalize_sales_report(self, report_id, headers):
        return self._request("POST", f"/licensing/sales-reports/{report_id}/finalize", {}, headers)

    # --- royalty statements ---
    def create_royalty_statement(self, agreement_id, payload, headers):
        return self._request("POST", f"/licensing/license-agreements/{agreement_id}/royalty-statements", payload, headers)

    def get_royalty_statement(self, statement_id, headers):
        return self._request("GET", f"/licensing/royalty-statements/{statement_id}", headers=headers)

    def list_royalty_statements(self, headers, params=None):
        return self._request("GET", "/licensing/royalty-statements", headers=headers, params=params)

    def issue_royalty_statement(self, statement_id, headers):
        return self._request("POST", f"/licensing/royalty-statements/{statement_id}/issue", {}, headers)

    def dispute_royalty_statement(self, statement_id, payload, headers):
        return self._request("POST", f"/licensing/royalty-statements/{statement_id}/dispute", payload, headers)

    def adjust_royalty_statement(self, statement_id, payload, headers):
        return self._request("POST", f"/licensing/royalty-statements/{statement_id}/adjust", payload, headers)

    def finalize_royalty_statement(self, statement_id, headers):
        return self._request("POST", f"/licensing/royalty-statements/{statement_id}/finalize", {}, headers)

    # --- inspections ---
    def create_inspection(self, store_id, payload, headers):
        return self._request("POST", f"/licensing/stores/{store_id}/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/licensing/inspections/{inspection_id}", headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/licensing/inspections", headers=headers, params=params)

    def complete_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/licensing/inspections/{inspection_id}/complete", payload, headers)

    def cancel_inspection(self, inspection_id, headers):
        return self._request("POST", f"/licensing/inspections/{inspection_id}/cancel", {}, headers)

    # --- corrective actions ---
    def get_corrective_action(self, corrective_action_id, headers):
        return self._request("GET", f"/licensing/corrective-actions/{corrective_action_id}", headers=headers)

    def list_corrective_actions(self, headers, params=None):
        return self._request("GET", "/licensing/corrective-actions", headers=headers, params=params)

    def submit_corrective_action_evidence(self, corrective_action_id, payload, headers):
        return self._request("POST", f"/licensing/corrective-actions/{corrective_action_id}/submit-evidence", payload, headers)

    def verify_corrective_action(self, corrective_action_id, headers):
        return self._request("POST", f"/licensing/corrective-actions/{corrective_action_id}/verify", {}, headers)

    def reopen_corrective_action(self, corrective_action_id, payload, headers):
        return self._request("POST", f"/licensing/corrective-actions/{corrective_action_id}/reopen", payload, headers)

    def sweep_overdue_corrective_actions(self, headers):
        return self._request("POST", "/licensing/corrective-actions/sweep-overdue", {}, headers)

    # --- loyalty members and events ---
    def create_loyalty_member(self, payload, headers):
        return self._request("POST", "/licensing/loyalty-members", payload, headers)

    def get_loyalty_member(self, member_id, headers):
        return self._request("GET", f"/licensing/loyalty-members/{member_id}", headers=headers)

    def create_loyalty_event(self, member_id, payload, headers):
        return self._request("POST", f"/licensing/loyalty-members/{member_id}/events", payload, headers)

    def get_loyalty_event(self, event_id, headers):
        return self._request("GET", f"/licensing/loyalty-account-events/{event_id}", headers=headers)

    def list_loyalty_events(self, headers, params=None):
        return self._request("GET", "/licensing/loyalty-account-events", headers=headers, params=params)

    # --- promotion campaigns ---
    def create_promotion_campaign(self, store_id, payload, headers):
        return self._request("POST", f"/licensing/stores/{store_id}/promotion-campaigns", payload, headers)

    def get_promotion_campaign(self, campaign_id, headers):
        return self._request("GET", f"/licensing/promotion-campaigns/{campaign_id}", headers=headers)

    def list_promotion_campaigns(self, headers, params=None):
        return self._request("GET", "/licensing/promotion-campaigns", headers=headers, params=params)

    def activate_promotion_campaign(self, campaign_id, headers):
        return self._request("POST", f"/licensing/promotion-campaigns/{campaign_id}/activate", {}, headers)

    def end_promotion_campaign(self, campaign_id, headers):
        return self._request("POST", f"/licensing/promotion-campaigns/{campaign_id}/end", {}, headers)

    def reconcile_promotion_campaign(self, campaign_id, headers):
        return self._request("POST", f"/licensing/promotion-campaigns/{campaign_id}/reconcile", {}, headers)

    def preview_promotion_price(self, campaign_id, payload, headers):
        return self._request("POST", f"/licensing/promotion-campaigns/{campaign_id}/price-preview", payload, headers)


api_client = ApiClient()
