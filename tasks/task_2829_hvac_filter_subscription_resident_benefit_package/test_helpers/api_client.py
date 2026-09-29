"""
Typed API client — one method per endpoint in the PRD endpoint catalog (§4).

Every method returns the raw ``requests.Response`` so tests can assert on
status codes as well as bodies. Timestamps returned by the API are canonicalised
nowhere here: comparisons are done by the assertion helpers, which normalise
fractional-second width before comparing instants.
"""

from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """HTTP surface of the HVAC filter subscription API."""

    # ─── Logical clock ────────────────────────────────────────────────────────

    def set_clock(self, payload: dict, headers: dict):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── FilterSku ────────────────────────────────────────────────────────────

    def create_filter_sku(self, payload: dict, headers: dict):
        return self._request("POST", "/filter-skus", payload, headers)

    def get_filter_sku(self, sku_id: str, headers: dict):
        return self._request("GET", f"/filter-skus/{sku_id}", None, headers)

    def discontinue_filter_sku(self, sku_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"/filter-skus/{sku_id}/discontinue", payload or {}, headers
        )

    # ─── Property ─────────────────────────────────────────────────────────────

    def create_property(self, payload: dict, headers: dict):
        return self._request("POST", "/properties", payload, headers)

    def get_property(self, property_id: str, headers: dict):
        return self._request("GET", f"/properties/{property_id}", None, headers)

    def list_properties(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/properties", params, headers)

    def activate_property(self, property_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"/properties/{property_id}/activate", payload or {}, headers
        )

    def suspend_property(self, property_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/properties/{property_id}/suspend", payload, headers
        )

    def reactivate_property(self, property_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"/properties/{property_id}/reactivate", payload or {}, headers
        )

    def offboard_property(self, property_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"/properties/{property_id}/offboard", payload or {}, headers
        )

    # ─── Unit ─────────────────────────────────────────────────────────────────

    def list_property_units(self, property_id: str, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"/properties/{property_id}/units", params, headers)

    def create_unit(self, property_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/properties/{property_id}/units", payload, headers)

    def get_unit(self, unit_id: str, headers: dict):
        return self._request("GET", f"/units/{unit_id}", None, headers)

    def capture_filter_size(self, unit_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/units/{unit_id}/filter-size-captures", payload, headers
        )

    def create_runtime_reading(self, unit_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/units/{unit_id}/runtime-readings", payload, headers
        )

    def list_runtime_readings(self, unit_id: str, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"/units/{unit_id}/runtime-readings", params, headers
        )

    # ─── Resident ─────────────────────────────────────────────────────────────

    def create_resident(self, payload: dict, headers: dict):
        return self._request("POST", "/residents", payload, headers)

    def get_resident(self, resident_id: str, headers: dict):
        return self._request("GET", f"/residents/{resident_id}", None, headers)

    # ─── Subscription ─────────────────────────────────────────────────────────

    def create_subscription(self, payload: dict, headers: dict):
        return self._request("POST", "/subscriptions", payload, headers)

    def get_subscription(self, subscription_id: str, headers: dict):
        return self._request("GET", f"/subscriptions/{subscription_id}", None, headers)

    def list_subscriptions(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/subscriptions", params, headers)

    def activate_subscription(self, subscription_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/activate", payload or {}, headers
        )

    def cancel_subscription(self, subscription_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/cancel", payload, headers
        )

    def get_settlement(self, subscription_id: str, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"/subscriptions/{subscription_id}/settlement", params, headers
        )

    def list_benefit_entitlements(self, subscription_id: str, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET",
            f"/subscriptions/{subscription_id}/benefit-entitlements",
            params,
            headers,
        )

    def list_ledger_entries(self, subscription_id: str, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"/subscriptions/{subscription_id}/ledger-entries", params, headers
        )

    def list_subscription_claims(self, subscription_id: str, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"/subscriptions/{subscription_id}/claims", params, headers
        )

    def list_subscription_cases(self, subscription_id: str, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"/subscriptions/{subscription_id}/non-install-cases", params, headers
        )

    def create_shipment(self, subscription_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/shipments", payload, headers
        )

    def create_renewal_survey(self, subscription_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/renewal-surveys", payload, headers
        )

    def list_renewal_surveys(self, subscription_id: str, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"/subscriptions/{subscription_id}/renewal-surveys", params, headers
        )

    def create_non_install_evaluation(self, subscription_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"/subscriptions/{subscription_id}/non-install-evaluations",
            payload,
            headers,
        )

    # ─── Shipment ─────────────────────────────────────────────────────────────

    def get_shipment(self, shipment_id: str, headers: dict):
        return self._request("GET", f"/shipments/{shipment_id}", None, headers)

    def list_shipments(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/shipments", params, headers)

    def ship_shipment(self, shipment_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/shipments/{shipment_id}/ship", payload, headers)

    def deliver_shipment(self, shipment_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/shipments/{shipment_id}/deliver", payload, headers
        )

    def request_shipment_return(self, shipment_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/shipments/{shipment_id}/request-return", payload, headers
        )

    def return_shipment(self, shipment_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/shipments/{shipment_id}/return", payload, headers
        )

    def write_off_shipment(self, shipment_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"/shipments/{shipment_id}/write-off", payload or {}, headers
        )

    # ─── NonInstallCase ───────────────────────────────────────────────────────

    def get_non_install_case(self, case_id: str, headers: dict):
        return self._request("GET", f"/non-install-cases/{case_id}", None, headers)

    def send_case_notice(self, case_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"/non-install-cases/{case_id}/send-notice", payload or {}, headers
        )

    def confirm_case(self, case_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"/non-install-cases/{case_id}/confirm", payload or {}, headers
        )

    def remediate_case(self, case_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/non-install-cases/{case_id}/remediate", payload, headers
        )

    def close_case_unsubstantiated(self, case_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            f"/non-install-cases/{case_id}/close-unsubstantiated",
            payload or {},
            headers,
        )

    # ─── BenefitEntitlement ───────────────────────────────────────────────────

    def get_benefit_entitlement(self, entitlement_id: str, headers: dict):
        return self._request(
            "GET", f"/benefit-entitlements/{entitlement_id}", None, headers
        )

    # ─── Claim ────────────────────────────────────────────────────────────────

    def create_claim(self, payload: dict, headers: dict):
        return self._request("POST", "/claims", payload, headers)

    def get_claim(self, claim_id: str, headers: dict):
        return self._request("GET", f"/claims/{claim_id}", None, headers)

    def list_claims(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/claims", params, headers)

    def triage_claim(self, claim_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/claims/{claim_id}/triage", payload or {}, headers)

    def request_claim_info(self, claim_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/claims/{claim_id}/request-info", payload, headers
        )

    def resubmit_claim(self, claim_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"/claims/{claim_id}/resubmit", payload or {}, headers
        )

    def decide_claim(self, claim_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/claims/{claim_id}/decide", payload, headers)

    def pay_claim(self, claim_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/claims/{claim_id}/pay", payload or {}, headers)

    def reverse_claim_payment(self, claim_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/claims/{claim_id}/reverse-payment", payload, headers
        )

    def withdraw_claim(self, claim_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"/claims/{claim_id}/withdraw", payload or {}, headers
        )

    # ─── SubscriptionTransfer ─────────────────────────────────────────────────

    def create_subscription_transfer(self, payload: dict, headers: dict):
        return self._request("POST", "/subscription-transfers", payload, headers)

    def get_subscription_transfer(self, transfer_id: str, headers: dict):
        return self._request(
            "GET", f"/subscription-transfers/{transfer_id}", None, headers
        )

    def list_subscription_transfers(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/subscription-transfers", params, headers)

    def remap_transfer_sku(self, transfer_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            f"/subscription-transfers/{transfer_id}/remap-sku",
            payload or {},
            headers,
        )

    def complete_transfer(self, transfer_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            f"/subscription-transfers/{transfer_id}/complete",
            payload or {},
            headers,
        )

    def reject_transfer(self, transfer_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/subscription-transfers/{transfer_id}/reject", payload, headers
        )
