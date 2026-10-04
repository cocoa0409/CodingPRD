"""API client: one method per operation the API exposes."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- CapacityAgreement ---
    def create_agreement(self, payload, headers):
        return self._request("POST", "/carriers/capacity-agreements", payload, headers)

    def get_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/carriers/capacity-agreements/{agreement_id}", headers=headers
        )

    def activate_agreement(self, agreement_id, headers, payload=None):
        return self._request(
            "POST",
            f"/carriers/capacity-agreements/{agreement_id}/activate",
            payload or {},
            headers,
        )

    def suspend_agreement(self, agreement_id, headers, payload=None):
        return self._request(
            "POST",
            f"/carriers/capacity-agreements/{agreement_id}/suspend",
            payload or {},
            headers,
        )

    def reactivate_agreement(self, agreement_id, headers, payload=None):
        return self._request(
            "POST",
            f"/carriers/capacity-agreements/{agreement_id}/reactivate",
            payload or {},
            headers,
        )

    def close_agreement(self, agreement_id, headers, payload=None):
        return self._request(
            "POST",
            f"/carriers/capacity-agreements/{agreement_id}/close",
            payload or {},
            headers,
        )

    def resolve_purchase(self, agreement_id, headers, payload=None):
        return self._request(
            "POST",
            f"/carriers/capacity-agreements/{agreement_id}/resolve-purchase",
            payload or {},
            headers,
        )

    def get_usage_summary(self, agreement_id, headers):
        return self._request(
            "GET",
            f"/carriers/capacity-agreements/{agreement_id}/usage-summary",
            headers=headers,
        )

    # --- Plan ---
    def create_plan(self, payload, headers):
        return self._request("POST", "/carriers/plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/carriers/plans/{plan_id}", headers=headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/carriers/plans", headers=headers, params=params)

    def offer_plan(self, plan_id, headers, payload=None):
        return self._request(
            "POST", f"/carriers/plans/{plan_id}/offer", payload or {}, headers
        )

    def withdraw_plan(self, plan_id, headers, payload=None):
        return self._request(
            "POST", f"/carriers/plans/{plan_id}/withdraw", payload or {}, headers
        )

    # --- Subscriber ---
    def create_subscriber(self, payload, headers):
        return self._request("POST", "/carriers/subscribers", payload, headers)

    def get_subscriber(self, subscriber_id, headers):
        return self._request(
            "GET", f"/carriers/subscribers/{subscriber_id}", headers=headers
        )

    def list_subscribers(self, headers, params=None):
        return self._request(
            "GET", "/carriers/subscribers", headers=headers, params=params
        )

    def cancel_subscriber(self, subscriber_id, headers, payload=None):
        return self._request(
            "POST",
            f"/carriers/subscribers/{subscriber_id}/cancel",
            payload or {},
            headers,
        )

    def suspend_subscriber(self, subscriber_id, headers, payload=None):
        return self._request(
            "POST",
            f"/carriers/subscribers/{subscriber_id}/suspend",
            payload or {},
            headers,
        )

    def resume_subscriber(self, subscriber_id, headers, payload=None):
        return self._request(
            "POST",
            f"/carriers/subscribers/{subscriber_id}/resume",
            payload or {},
            headers,
        )

    def consume_data(self, subscriber_id, headers, payload):
        return self._request(
            "POST",
            f"/carriers/subscribers/{subscriber_id}/consume_data",
            payload,
            headers,
        )

    def run_cycle(self, subscriber_id, headers, payload=None):
        return self._request(
            "POST",
            f"/carriers/subscribers/{subscriber_id}/run_cycle",
            payload or {},
            headers,
        )

    def support_top_up(self, subscriber_id, headers, payload):
        return self._request(
            "POST",
            f"/carriers/subscribers/{subscriber_id}/support_top_ups",
            payload,
            headers,
        )

    # --- PrepaidTerm ---
    def create_term(self, payload, headers):
        return self._request("POST", "/carriers/prepaid-terms", payload, headers)

    def get_term(self, term_id, headers):
        return self._request("GET", f"/carriers/prepaid-terms/{term_id}", headers=headers)

    def list_terms(self, headers, params=None):
        return self._request(
            "GET", "/carriers/prepaid-terms", headers=headers, params=params
        )

    def purchase_term(self, term_id, headers, payload=None):
        return self._request(
            "POST", f"/carriers/prepaid-terms/{term_id}/purchase", payload or {}, headers
        )

    def accept_step_up(self, term_id, headers, payload=None):
        return self._request(
            "POST",
            f"/carriers/prepaid-terms/{term_id}/accept_step_up",
            payload or {},
            headers,
        )

    def cancel_term(self, term_id, headers, payload=None):
        return self._request(
            "POST", f"/carriers/prepaid-terms/{term_id}/cancel", payload or {}, headers
        )

    # --- CycleRecord ---
    def get_cycle(self, cycle_id, headers):
        return self._request("GET", f"/carriers/cycles/{cycle_id}", headers=headers)

    def list_cycles(self, headers, params=None):
        return self._request("GET", "/carriers/cycles", headers=headers, params=params)

    # --- Activation ---
    def create_activation(self, payload, headers):
        return self._request("POST", "/carriers/activations", payload, headers)

    def get_activation(self, activation_id, headers):
        return self._request(
            "GET", f"/carriers/activations/{activation_id}", headers=headers
        )

    def list_activations(self, headers, params=None):
        return self._request(
            "GET", "/carriers/activations", headers=headers, params=params
        )

    def provision_activation(self, activation_id, headers, payload=None):
        return self._request(
            "POST",
            f"/carriers/activations/{activation_id}/provision",
            payload or {},
            headers,
        )

    def complete_activation(self, activation_id, headers, payload=None):
        return self._request(
            "POST",
            f"/carriers/activations/{activation_id}/complete",
            payload or {},
            headers,
        )

    def fail_activation(self, activation_id, headers, payload):
        return self._request(
            "POST", f"/carriers/activations/{activation_id}/fail", payload, headers
        )

    def submit_port(self, activation_id, headers, payload):
        return self._request(
            "POST",
            f"/carriers/activations/{activation_id}/submit-port",
            payload,
            headers,
        )

    def reject_port(self, activation_id, headers, payload):
        return self._request(
            "POST",
            f"/carriers/activations/{activation_id}/reject-port",
            payload,
            headers,
        )

    def confirm_port(self, activation_id, headers, payload=None):
        return self._request(
            "POST",
            f"/carriers/activations/{activation_id}/confirm-port",
            payload or {},
            headers,
        )

    def cancel_port(self, activation_id, headers, payload=None):
        return self._request(
            "POST",
            f"/carriers/activations/{activation_id}/cancel-port",
            payload or {},
            headers,
        )

    # --- RetailPartner ---
    def create_partner(self, payload, headers):
        return self._request("POST", "/carriers/retail-partners", payload, headers)

    def get_partner(self, partner_id, headers):
        return self._request(
            "GET", f"/carriers/retail-partners/{partner_id}", headers=headers
        )

    def suspend_partner(self, partner_id, headers, payload=None):
        return self._request(
            "POST",
            f"/carriers/retail-partners/{partner_id}/suspend",
            payload or {},
            headers,
        )

    def reinstate_partner(self, partner_id, headers, payload=None):
        return self._request(
            "POST",
            f"/carriers/retail-partners/{partner_id}/reinstate",
            payload or {},
            headers,
        )

    # --- SimInventory ---
    def create_inventory(self, payload, headers):
        return self._request("POST", "/carriers/sim-inventories", payload, headers)

    def get_inventory(self, inventory_id, headers):
        return self._request(
            "GET", f"/carriers/sim-inventories/{inventory_id}", headers=headers
        )

    def list_inventories(self, headers, params=None):
        return self._request(
            "GET", "/carriers/sim-inventories", headers=headers, params=params
        )

    def return_inventory(self, inventory_id, headers, payload=None):
        return self._request(
            "POST",
            f"/carriers/sim-inventories/{inventory_id}/return",
            payload or {},
            headers,
        )

    # --- SupportCase ---
    def create_case(self, payload, headers):
        return self._request("POST", "/carriers/support-cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/carriers/support-cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request(
            "GET", "/carriers/support-cases", headers=headers, params=params
        )

    def assign_case(self, case_id, headers, payload=None):
        return self._request(
            "POST", f"/carriers/support-cases/{case_id}/assign", payload or {}, headers
        )

    def resolve_self_service(self, case_id, headers, payload=None):
        return self._request(
            "POST",
            f"/carriers/support-cases/{case_id}/resolve_self_service",
            payload or {},
            headers,
        )

    def resolve_agent(self, case_id, headers, payload):
        return self._request(
            "POST",
            f"/carriers/support-cases/{case_id}/resolve_agent",
            payload,
            headers,
        )

    def escalate_case(self, case_id, headers, payload=None):
        return self._request(
            "POST", f"/carriers/support-cases/{case_id}/escalate", payload or {}, headers
        )

    # --- AddOn ---
    def create_addon(self, payload, headers):
        return self._request("POST", "/carriers/add-ons", payload, headers)

    def get_addon(self, addon_id, headers):
        return self._request("GET", f"/carriers/add-ons/{addon_id}", headers=headers)

    def list_addons(self, headers, params=None):
        return self._request("GET", "/carriers/add-ons", headers=headers, params=params)

    def activate_addon(self, addon_id, headers, payload=None):
        return self._request(
            "POST", f"/carriers/add-ons/{addon_id}/activate", payload or {}, headers
        )

    # --- Logical clock ---
    def set_clock(self, headers, current_utc):
        return self._request(
            "POST",
            "/carriers/_clock/set_current_utc",
            {"current_utc": current_utc},
            headers,
        )


api_client = ApiClient()