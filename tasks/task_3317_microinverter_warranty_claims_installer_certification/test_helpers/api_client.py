"""API client: one method per endpoint defined in the PRD (PRD §4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Installer ─────────────────────────────────────
    def create_installer(self, payload, headers):
        return self._request("POST", "/warranty/installers", payload, headers)

    def get_installer(self, installer_id, headers):
        return self._request("GET", f"/warranty/installers/{installer_id}", headers=headers)

    def activate_installer(self, installer_id, headers, payload=None):
        return self._request("POST", f"/warranty/installers/{installer_id}/activate",
                             payload if payload is not None else {}, headers)

    def suspend_installer(self, installer_id, headers, payload=None):
        return self._request("POST", f"/warranty/installers/{installer_id}/suspend",
                             payload if payload is not None else {}, headers)

    def reinstate_installer(self, installer_id, headers, payload=None):
        return self._request("POST", f"/warranty/installers/{installer_id}/reinstate",
                             payload if payload is not None else {}, headers)

    def get_installer_portfolio(self, installer_id, headers):
        return self._request("GET", f"/warranty/installers/{installer_id}/portfolio", headers=headers)

    def set_installer_level(self, payload, headers):
        return self._request("POST", "/warranty/installer-levels", payload, headers)

    # ── Design project ────────────────────────────────
    def create_design_project(self, payload, headers):
        return self._request("POST", "/warranty/design-projects", payload, headers)

    def list_design_projects(self, headers, params=None):
        return self._request("GET", "/warranty/design-projects", params, headers)

    def get_design_project(self, project_id, headers):
        return self._request("GET", f"/warranty/design-projects/{project_id}", headers=headers)

    def submit_design_project(self, project_id, headers, payload=None):
        return self._request("POST", f"/warranty/design-projects/{project_id}/submit",
                             payload if payload is not None else {}, headers)

    def approve_design_project(self, project_id, headers, payload=None):
        return self._request("POST", f"/warranty/design-projects/{project_id}/approve",
                             payload if payload is not None else {}, headers)

    def reject_design_project(self, project_id, payload, headers):
        return self._request("POST", f"/warranty/design-projects/{project_id}/reject", payload, headers)

    # ── Production lot ────────────────────────────────
    def create_production_lot(self, payload, headers):
        return self._request("POST", "/warranty/production-lots", payload, headers)

    def get_production_lot(self, lot_id, headers):
        return self._request("GET", f"/warranty/production-lots/{lot_id}", headers=headers)

    def list_lot_units(self, lot_id, headers, params=None):
        return self._request("GET", f"/warranty/production-lots/{lot_id}/units", params, headers)

    def lot_action(self, payload, headers):
        return self._request("POST", "/warranty/lot-actions", payload, headers)

    # ── System registration ───────────────────────────
    def create_system_registration(self, payload, headers):
        return self._request("POST", "/warranty/system-registrations", payload, headers)

    def list_system_registrations(self, headers, params=None):
        return self._request("GET", "/warranty/system-registrations", params, headers)

    def get_system_registration(self, system_id, headers):
        return self._request("GET", f"/warranty/system-registrations/{system_id}", headers=headers)

    def list_system_units(self, system_id, headers, params=None):
        return self._request("GET", f"/warranty/system-registrations/{system_id}/units", params, headers)

    def get_system_coverage(self, system_id, headers):
        return self._request("GET", f"/warranty/system-registrations/{system_id}/coverage", headers=headers)

    def get_monitoring_summary(self, system_id, headers):
        return self._request("GET", f"/warranty/system-registrations/{system_id}/monitoring-summary",
                             headers=headers)

    # ── Unit ──────────────────────────────────────────
    def list_units(self, headers, params=None):
        return self._request("GET", "/warranty/units", params, headers)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/warranty/units/{unit_id}", headers=headers)

    def observe_unit(self, unit_id, payload, headers):
        return self._request("POST", f"/warranty/units/{unit_id}/observations", payload, headers)

    def run_unit_diagnostics(self, unit_id, payload, headers):
        return self._request("POST", f"/warranty/units/{unit_id}/diagnostics", payload, headers)

    # ── Warranty claim ────────────────────────────────
    def create_claim(self, payload, headers):
        return self._request("POST", "/warranty/claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/warranty/claims", params, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/warranty/claims/{claim_id}", headers=headers)

    def submit_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/warranty/claims/{claim_id}/submit",
                             payload if payload is not None else {}, headers)

    def diagnose_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/warranty/claims/{claim_id}/diagnose",
                             payload if payload is not None else {}, headers)

    def approve_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/warranty/claims/{claim_id}/approve",
                             payload if payload is not None else {}, headers)

    def deny_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/warranty/claims/{claim_id}/deny", payload, headers)

    def dispatch_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/warranty/claims/{claim_id}/dispatch",
                             payload if payload is not None else {}, headers)

    def close_claim_unreplaced(self, claim_id, headers, payload=None):
        return self._request("POST", f"/warranty/claims/{claim_id}/close-unreplaced",
                             payload if payload is not None else {}, headers)

    def reopen_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/warranty/claims/{claim_id}/reopen",
                             payload if payload is not None else {}, headers)

    # ── Labor reimbursement ───────────────────────────
    def create_labor_reimbursement(self, payload, headers):
        return self._request("POST", "/warranty/labor-reimbursements", payload, headers)

    def list_labor_reimbursements(self, headers, params=None):
        return self._request("GET", "/warranty/labor-reimbursements", params, headers)

    def get_labor_reimbursement(self, reimbursement_id, headers):
        return self._request("GET", f"/warranty/labor-reimbursements/{reimbursement_id}", headers=headers)

    def get_labor_quote(self, reimbursement_id, headers):
        return self._request("GET", f"/warranty/labor-reimbursements/{reimbursement_id}/quote", headers=headers)

    def reject_labor_reimbursement(self, reimbursement_id, payload, headers):
        return self._request("POST", f"/warranty/labor-reimbursements/{reimbursement_id}/reject",
                             payload, headers)

    # ── Warranty transfer ─────────────────────────────
    def create_warranty_transfer(self, payload, headers):
        return self._request("POST", "/warranty/warranty-transfers", payload, headers)

    def list_warranty_transfers(self, headers, params=None):
        return self._request("GET", "/warranty/warranty-transfers", params, headers)

    def get_warranty_transfer(self, transfer_id, headers):
        return self._request("GET", f"/warranty/warranty-transfers/{transfer_id}", headers=headers)

    def approve_warranty_transfer(self, transfer_id, headers, payload=None):
        return self._request("POST", f"/warranty/warranty-transfers/{transfer_id}/approve",
                             payload if payload is not None else {}, headers)

    def reject_warranty_transfer(self, transfer_id, payload, headers):
        return self._request("POST", f"/warranty/warranty-transfers/{transfer_id}/reject", payload, headers)

    def reopen_warranty_transfer(self, transfer_id, headers, payload=None):
        return self._request("POST", f"/warranty/warranty-transfers/{transfer_id}/reopen",
                             payload if payload is not None else {}, headers)

    # ── Proactive campaign ────────────────────────────
    def create_campaign(self, payload, headers):
        return self._request("POST", "/warranty/proactive-campaigns", payload, headers)

    def list_campaigns(self, headers, params=None):
        return self._request("GET", "/warranty/proactive-campaigns", params, headers)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/warranty/proactive-campaigns/{campaign_id}", headers=headers)

    def get_campaign_preview(self, campaign_id, headers):
        return self._request("GET", f"/warranty/proactive-campaigns/{campaign_id}/preview", headers=headers)

    def activate_campaign(self, campaign_id, headers, payload=None):
        return self._request("POST", f"/warranty/proactive-campaigns/{campaign_id}/activate",
                             payload if payload is not None else {}, headers)

    def close_campaign(self, campaign_id, headers, payload=None):
        return self._request("POST", f"/warranty/proactive-campaigns/{campaign_id}/close",
                             payload if payload is not None else {}, headers)

    def cancel_campaign(self, campaign_id, headers, payload=None):
        return self._request("POST", f"/warranty/proactive-campaigns/{campaign_id}/cancel",
                             payload if payload is not None else {}, headers)

    # ── Replacement order ─────────────────────────────
    def create_replacement_order(self, payload, headers):
        return self._request("POST", "/warranty/replacement-orders", payload, headers)

    def list_replacement_orders(self, headers, params=None):
        return self._request("GET", "/warranty/replacement-orders", params, headers)

    def get_replacement_order(self, order_id, headers):
        return self._request("GET", f"/warranty/replacement-orders/{order_id}", headers=headers)

    def dispatch_replacement_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/warranty/replacement-orders/{order_id}/dispatch",
                             payload if payload is not None else {}, headers)

    def install_replacement_order(self, order_id, payload, headers):
        return self._request("POST", f"/warranty/replacement-orders/{order_id}/install", payload, headers)

    def cancel_replacement_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/warranty/replacement-orders/{order_id}/cancel",
                             payload if payload is not None else {}, headers)

    def reactivate_replacement_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/warranty/replacement-orders/{order_id}/reactivate",
                             payload if payload is not None else {}, headers)

    # ── Billing / entitlements / share links / clock ──
    def create_billing_correction(self, payload, headers):
        return self._request("POST", "/warranty/billing-corrections", payload, headers)

    def create_billing_entitlement(self, payload, headers):
        return self._request("POST", "/warranty/billing-entitlements", payload, headers)

    def list_billing_entitlements(self, headers, params=None):
        return self._request("GET", "/warranty/billing-entitlements", params, headers)

    def create_share_link(self, payload, headers):
        return self._request("POST", "/warranty/share-links", payload, headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()