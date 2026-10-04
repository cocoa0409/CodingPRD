"""API client: one method per endpoint defined in PRD §4 (all under /creamery)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.5) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/creamery/_clock/set_current_utc", payload, headers)

    # --- Suppliers, commitments, certifications, audits (PRD §3.1, §3.2) ---
    def create_supplier(self, payload, headers):
        return self._request("POST", "/creamery/suppliers", payload, headers)

    def get_supplier(self, supplier_id, headers):
        return self._request("GET", f"/creamery/suppliers/{supplier_id}", headers=headers)

    def suspend_supplier(self, supplier_id, headers):
        return self._request("POST", f"/creamery/suppliers/{supplier_id}/suspend", headers=headers)

    def reinstate_supplier(self, supplier_id, headers):
        return self._request("POST", f"/creamery/suppliers/{supplier_id}/reinstate", headers=headers)

    def terminate_supplier(self, supplier_id, headers):
        return self._request("POST", f"/creamery/suppliers/{supplier_id}/terminate", headers=headers)

    def create_commitment(self, supplier_id, payload, headers):
        return self._request("POST", f"/creamery/suppliers/{supplier_id}/commitments", payload, headers)

    def list_commitments(self, supplier_id, headers, params=None):
        return self._request("GET", f"/creamery/suppliers/{supplier_id}/commitments", headers=headers, params=params)

    def create_certification(self, supplier_id, payload, headers):
        return self._request("POST", f"/creamery/suppliers/{supplier_id}/certifications", payload, headers)

    def list_certifications(self, supplier_id, headers, params=None):
        return self._request("GET", f"/creamery/suppliers/{supplier_id}/certifications", headers=headers, params=params)

    def verify_certification(self, cert_id, payload, headers):
        return self._request("POST", f"/creamery/certifications/{cert_id}/verify", payload, headers)

    def revoke_certification(self, cert_id, headers):
        return self._request("POST", f"/creamery/certifications/{cert_id}/revoke", headers=headers)

    def create_audit(self, supplier_id, payload, headers):
        return self._request("POST", f"/creamery/suppliers/{supplier_id}/audits", payload, headers)

    def list_audits(self, supplier_id, headers, params=None):
        return self._request("GET", f"/creamery/suppliers/{supplier_id}/audits", headers=headers, params=params)

    def start_audit(self, audit_id, headers):
        return self._request("POST", f"/creamery/audits/{audit_id}/start", headers=headers)

    def complete_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/creamery/audits/{audit_id}/complete", payload, headers)

    def verify_audit(self, audit_id, headers):
        return self._request("POST", f"/creamery/audits/{audit_id}/verify", headers=headers)

    # --- Dairy farm program (PRD §3.3) ---
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/creamery/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/creamery/enrollments/{enrollment_id}", headers=headers)

    def assess_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/creamery/enrollments/{enrollment_id}/assess", payload, headers)

    def create_premium_payment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/creamery/enrollments/{enrollment_id}/premium-payments", payload, headers)

    def list_premium_payments(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/creamery/enrollments/{enrollment_id}/premium-payments", headers=headers, params=params)

    def get_premium_payment(self, payment_id, headers):
        return self._request("GET", f"/creamery/premium-payments/{payment_id}", headers=headers)

    def finalize_payment(self, payment_id, payload, headers):
        return self._request("POST", f"/creamery/premium-payments/{payment_id}/finalize", payload, headers)

    def approve_payment(self, payment_id, headers):
        return self._request("POST", f"/creamery/premium-payments/{payment_id}/approve", headers=headers)

    def pay_payment(self, payment_id, headers):
        return self._request("POST", f"/creamery/premium-payments/{payment_id}/pay", headers=headers)

    def void_payment(self, payment_id, headers):
        return self._request("POST", f"/creamery/premium-payments/{payment_id}/void", headers=headers)

    # --- Flavors, claims, revival (PRD §3.4, §3.5, §3.6) ---
    def create_flavor(self, payload, headers):
        return self._request("POST", "/creamery/flavors", payload, headers)

    def get_flavor(self, flavor_id, headers):
        return self._request("GET", f"/creamery/flavors/{flavor_id}", headers=headers)

    def promote_flavor(self, flavor_id, payload, headers):
        return self._request("POST", f"/creamery/flavors/{flavor_id}/promote", payload, headers)

    def retire_flavor(self, flavor_id, headers):
        return self._request("POST", f"/creamery/flavors/{flavor_id}/retire", headers=headers)

    def return_flavor_to_line(self, flavor_id, headers):
        return self._request("POST", f"/creamery/flavors/{flavor_id}/return-to-line", headers=headers)

    def substantiate_claim(self, flavor_id, payload, headers):
        return self._request("POST", f"/creamery/flavors/{flavor_id}/substantiate-claim", payload, headers)

    def publish_claim(self, flavor_id, headers):
        return self._request("POST", f"/creamery/flavors/{flavor_id}/publish-claim", headers=headers)

    def challenge_claim(self, flavor_id, headers):
        return self._request("POST", f"/creamery/flavors/{flavor_id}/challenge-claim", headers=headers)

    def create_revival_request(self, flavor_id, payload, headers):
        return self._request("POST", f"/creamery/flavors/{flavor_id}/revival-requests", payload, headers)

    def list_revival_requests(self, flavor_id, headers, params=None):
        return self._request("GET", f"/creamery/flavors/{flavor_id}/revival-requests", headers=headers, params=params)

    def sign_revival_request(self, request_id, payload, headers):
        return self._request("POST", f"/creamery/revival-requests/{request_id}/sign", payload, headers)

    def adopt_revival_request(self, request_id, headers):
        return self._request("POST", f"/creamery/revival-requests/{request_id}/adopt", headers=headers)

    def decline_revival_request(self, request_id, headers):
        return self._request("POST", f"/creamery/revival-requests/{request_id}/decline", headers=headers)

    # --- Production slots (PRD §3.4) ---
    def create_production_slot(self, payload, headers):
        return self._request("POST", "/creamery/production-slots", payload, headers)

    def list_production_slots(self, headers, params=None):
        return self._request("GET", "/creamery/production-slots", headers=headers, params=params)

    def get_production_slot(self, slot_id, headers):
        return self._request("GET", f"/creamery/production-slots/{slot_id}", headers=headers)

    def confirm_production_slot(self, slot_id, headers):
        return self._request("POST", f"/creamery/production-slots/{slot_id}/confirm", headers=headers)

    def cancel_production_slot(self, slot_id, headers):
        return self._request("POST", f"/creamery/production-slots/{slot_id}/cancel", headers=headers)

    # --- Campaigns (PRD §3.7) ---
    def create_campaign(self, payload, headers):
        return self._request("POST", "/creamery/campaigns", payload, headers)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/creamery/campaigns/{campaign_id}", headers=headers)

    def board_decision(self, campaign_id, payload, headers):
        return self._request("POST", f"/creamery/campaigns/{campaign_id}/board-decision", payload, headers)

    def schedule_ops(self, campaign_id, headers):
        return self._request("POST", f"/creamery/campaigns/{campaign_id}/schedule-ops", headers=headers)

    def dispatch_retail_notices(self, campaign_id, headers):
        return self._request("POST", f"/creamery/campaigns/{campaign_id}/dispatch-retail-notices", headers=headers)

    def launch_campaign(self, campaign_id, headers):
        return self._request("POST", f"/creamery/campaigns/{campaign_id}/launch", headers=headers)

    def veto_campaign(self, campaign_id, headers):
        return self._request("POST", f"/creamery/campaigns/{campaign_id}/veto", headers=headers)

    # --- Scoop shops and supply orders (PRD §3.8) ---
    def create_scoop_shop(self, payload, headers):
        return self._request("POST", "/creamery/scoop-shops", payload, headers)

    def get_scoop_shop(self, shop_id, headers):
        return self._request("GET", f"/creamery/scoop-shops/{shop_id}", headers=headers)

    def approve_site(self, shop_id, headers):
        return self._request("POST", f"/creamery/scoop-shops/{shop_id}/approve-site", headers=headers)

    def reject_site(self, shop_id, headers):
        return self._request("POST", f"/creamery/scoop-shops/{shop_id}/reject-site", headers=headers)

    def open_shop(self, shop_id, headers):
        return self._request("POST", f"/creamery/scoop-shops/{shop_id}/open", headers=headers)

    def suspend_shop(self, shop_id, headers):
        return self._request("POST", f"/creamery/scoop-shops/{shop_id}/suspend", headers=headers)

    def reopen_shop(self, shop_id, headers):
        return self._request("POST", f"/creamery/scoop-shops/{shop_id}/reopen", headers=headers)

    def create_supply_order(self, shop_id, payload, headers):
        return self._request("POST", f"/creamery/scoop-shops/{shop_id}/supply-orders", payload, headers)

    def list_supply_orders(self, shop_id, headers, params=None):
        return self._request("GET", f"/creamery/scoop-shops/{shop_id}/supply-orders", headers=headers, params=params)

    def get_supply_order(self, order_id, headers):
        return self._request("GET", f"/creamery/supply-orders/{order_id}", headers=headers)

    def confirm_supply_order(self, order_id, headers):
        return self._request("POST", f"/creamery/supply-orders/{order_id}/confirm", headers=headers)

    def allocate_supply_order(self, order_id, payload, headers):
        return self._request("POST", f"/creamery/supply-orders/{order_id}/allocate", payload, headers)

    def deliver_supply_order(self, order_id, headers):
        return self._request("POST", f"/creamery/supply-orders/{order_id}/deliver", headers=headers)

    def cancel_supply_order(self, order_id, headers):
        return self._request("POST", f"/creamery/supply-orders/{order_id}/cancel", headers=headers)


api_client = ApiClient()
