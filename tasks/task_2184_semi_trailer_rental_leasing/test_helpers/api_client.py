"""API client: one method per endpoint defined in the PRD.

Every path is mounted under the `/fleet` prefix.
"""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/fleet"


class ApiClient(GenericApiClient):
    # ---------------------------------------------------------------- clock
    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # --------------------------------------------------------------- yards
    def create_branch(self, payload, headers):
        return self._request("POST", f"{PREFIX}/branches", payload, headers)

    def get_branch(self, branch_id, headers):
        return self._request("GET", f"{PREFIX}/branches/{branch_id}", headers=headers)

    def list_branches(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/branches", payload=params, headers=headers)

    def get_branch_availability(self, branch_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/branches/{branch_id}/availability",
            payload=params, headers=headers,
        )

    # ---------------------------------------------------- equipment classes
    def create_trailer_type(self, payload, headers):
        return self._request("POST", f"{PREFIX}/trailer-types", payload, headers)

    def get_trailer_type(self, trailer_type_id, headers):
        return self._request(
            "GET", f"{PREFIX}/trailer-types/{trailer_type_id}", headers=headers
        )

    def list_trailer_types(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/trailer-types", payload=params, headers=headers)

    # --------------------------------------------------------------- units
    def create_trailer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/trailers", payload, headers)

    def get_trailer(self, trailer_id, headers):
        return self._request("GET", f"{PREFIX}/trailers/{trailer_id}", headers=headers)

    def list_trailers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/trailers", payload=params, headers=headers)

    def retire_trailer(self, trailer_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/trailers/{trailer_id}/retire", payload, headers
        )

    # ------------------------------------------------------------- lessees
    def create_customer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"{PREFIX}/customers/{customer_id}", headers=headers)

    def get_customer_risk_review(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/customers/{customer_id}/risk-review",
            payload=params, headers=headers,
        )

    # -------------------------------------------------------- certificates
    def create_insurance_certificate(self, payload, headers):
        return self._request("POST", f"{PREFIX}/insurance-certificates", payload, headers)

    def get_insurance_certificate(self, certificate_id, headers):
        return self._request(
            "GET", f"{PREFIX}/insurance-certificates/{certificate_id}", headers=headers
        )

    def list_insurance_certificates(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/insurance-certificates", payload=params, headers=headers
        )

    def revoke_insurance_certificate(self, certificate_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/insurance-certificates/{certificate_id}/revoke",
            payload, headers,
        )

    # ---------------------------------------------------------- rate cards
    def create_rate_card(self, payload, headers):
        return self._request("POST", f"{PREFIX}/rate-cards", payload, headers)

    def get_rate_card(self, rate_card_id, headers):
        return self._request("GET", f"{PREFIX}/rate-cards/{rate_card_id}", headers=headers)

    def list_rate_cards(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/rate-cards", payload=params, headers=headers)

    # ---------------------------------------------------------- agreements
    def create_agreement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/agreements", payload, headers)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"{PREFIX}/agreements/{agreement_id}", headers=headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/agreements", payload=params, headers=headers)

    def submit_agreement(self, agreement_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/agreements/{agreement_id}/submit", payload or {}, headers
        )

    def verify_agreement_insurance(self, agreement_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/agreements/{agreement_id}/verify-insurance",
            payload or {}, headers,
        )

    def allocate_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/agreements/{agreement_id}/allocate", payload, headers
        )

    def attach_agreement_unit(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/agreements/{agreement_id}/units", payload, headers
        )

    def activate_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/agreements/{agreement_id}/activate", payload, headers
        )

    def cancel_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/agreements/{agreement_id}/cancel", payload, headers
        )

    def settle_agreement(self, agreement_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/agreements/{agreement_id}/settle", payload or {}, headers
        )

    def exercise_purchase_option(self, agreement_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/agreements/{agreement_id}/exercise-purchase-option",
            payload or {}, headers,
        )

    def decline_purchase_option(self, agreement_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/agreements/{agreement_id}/decline-purchase-option",
            payload or {}, headers,
        )

    # --------------------------------------------------- contract unit lines
    def get_agreement_unit(self, agreement_unit_id, headers):
        return self._request(
            "GET", f"{PREFIX}/agreement-units/{agreement_unit_id}", headers=headers
        )

    def list_agreement_units(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/agreement-units", payload=params, headers=headers
        )

    def return_agreement_unit(self, agreement_unit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/agreement-units/{agreement_unit_id}/return", payload, headers
        )

    def create_damage_assessment(self, agreement_unit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/agreement-units/{agreement_unit_id}/damage-assessments",
            payload, headers,
        )

    # -------------------------------------------------------- shop events
    def create_maintenance_event(self, payload, headers):
        return self._request("POST", f"{PREFIX}/maintenance-events", payload, headers)

    def get_maintenance_event(self, maintenance_event_id, headers):
        return self._request(
            "GET", f"{PREFIX}/maintenance-events/{maintenance_event_id}", headers=headers
        )

    def list_maintenance_events(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/maintenance-events", payload=params, headers=headers
        )

    # -------------------------------------------------- damage assessments
    def get_damage_assessment(self, damage_assessment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/damage-assessments/{damage_assessment_id}", headers=headers
        )

    def list_damage_assessments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/damage-assessments", payload=params, headers=headers
        )

    def submit_damage_assessment(self, damage_assessment_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/damage-assessments/{damage_assessment_id}/submit",
            payload or {}, headers,
        )

    # --------------------------------------------------------- chargebacks
    def get_chargeback(self, chargeback_id, headers):
        return self._request("GET", f"{PREFIX}/chargebacks/{chargeback_id}", headers=headers)

    def list_chargebacks(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/chargebacks", payload=params, headers=headers)

    def approve_chargeback(self, chargeback_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/chargebacks/{chargeback_id}/approve", payload or {}, headers
        )

    def dispute_chargeback(self, chargeback_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/chargebacks/{chargeback_id}/dispute", payload, headers
        )

    def reopen_chargeback(self, chargeback_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/chargebacks/{chargeback_id}/reopen", payload or {}, headers
        )

    def waive_chargeback(self, chargeback_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/chargebacks/{chargeback_id}/waive", payload, headers
        )

    def record_chargeback_payment(self, chargeback_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/chargebacks/{chargeback_id}/record-payment", payload, headers
        )

    # --------------------------------------------------- relocation orders
    def create_relocation_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/relocation-orders", payload, headers)

    def get_relocation_order(self, relocation_order_id, headers):
        return self._request(
            "GET", f"{PREFIX}/relocation-orders/{relocation_order_id}", headers=headers
        )

    def list_relocation_orders(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/relocation-orders", payload=params, headers=headers
        )

    def approve_relocation_order(self, relocation_order_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/relocation-orders/{relocation_order_id}/approve",
            payload or {}, headers,
        )

    def reject_relocation_order(self, relocation_order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/relocation-orders/{relocation_order_id}/reject",
            payload, headers,
        )

    def dispatch_relocation_order(self, relocation_order_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/relocation-orders/{relocation_order_id}/dispatch",
            payload or {}, headers,
        )

    def complete_relocation_order(self, relocation_order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/relocation-orders/{relocation_order_id}/complete",
            payload, headers,
        )

    def abort_relocation_order(self, relocation_order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/relocation-orders/{relocation_order_id}/abort",
            payload, headers,
        )

    # ------------------------------------------------------------ raw call
    def raw_get(self, path, headers=None, params=None):
        """Escape hatch for header-negative tests: sends exactly the headers given."""
        return self._request("GET", f"{PREFIX}{path}", payload=params, headers=headers)


api_client = ApiClient()
