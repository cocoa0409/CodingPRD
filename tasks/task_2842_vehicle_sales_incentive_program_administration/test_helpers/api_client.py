"""API client: one method per endpoint defined in the PRD."""
from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/incentives"


class ApiClient(GenericApiClient):
    """Endpoint methods for the Vehicle Sales Incentive Program Administration API."""

    # --- Logical clock -----------------------------------------------------
    def set_clock(self, payload: dict, headers: dict):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Incentive programs ------------------------------------------------
    def create_program(self, payload: dict, headers: dict):
        return self._request("POST", f"{BASE}/programs", payload, headers)

    def list_programs(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{BASE}/programs", headers=headers, params=params)

    def get_program(self, program_id: str, headers: dict):
        return self._request("GET", f"{BASE}/programs/{program_id}", headers=headers)

    def create_eligibility_rule(self, program_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{BASE}/programs/{program_id}/eligibility-rules", payload, headers
        )

    def list_eligibility_rules(
        self, program_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"{BASE}/programs/{program_id}/eligibility-rules",
            headers=headers,
            params=params,
        )

    def create_stackability_constraint(
        self, program_id: str, payload: dict, headers: dict
    ):
        return self._request(
            "POST",
            f"{BASE}/programs/{program_id}/stackability-constraints",
            payload,
            headers,
        )

    def list_stackability_constraints(
        self, program_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"{BASE}/programs/{program_id}/stackability-constraints",
            headers=headers,
            params=params,
        )

    def submit_program(self, program_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"{BASE}/programs/{program_id}/submit", payload or {}, headers
        )

    def revise_program(self, program_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"{BASE}/programs/{program_id}/revise", payload or {}, headers
        )

    def approve_program(self, program_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"{BASE}/programs/{program_id}/approve", payload or {}, headers
        )

    def close_program(self, program_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"{BASE}/programs/{program_id}/close", payload or {}, headers
        )

    def create_repricing(self, program_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{BASE}/programs/{program_id}/repricings", payload, headers
        )

    def list_repricings(self, program_id: str, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET",
            f"{BASE}/programs/{program_id}/repricings",
            headers=headers,
            params=params,
        )

    def run_accrual(self, program_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{BASE}/programs/{program_id}/accruals", payload, headers
        )

    def list_accruals(self, program_id: str, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET",
            f"{BASE}/programs/{program_id}/accruals",
            headers=headers,
            params=params,
        )

    def get_spend_summary(self, program_id: str, headers: dict):
        return self._request(
            "GET", f"{BASE}/programs/{program_id}/spend-summary", headers=headers
        )

    # --- Dealer objectives and protests ------------------------------------
    def create_objective(self, program_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{BASE}/programs/{program_id}/objectives", payload, headers
        )

    def list_program_objectives(
        self, program_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"{BASE}/programs/{program_id}/objectives",
            headers=headers,
            params=params,
        )

    def get_objective(self, objective_id: str, headers: dict):
        return self._request("GET", f"{BASE}/objectives/{objective_id}", headers=headers)

    def list_objectives(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{BASE}/objectives", headers=headers, params=params)

    def create_protest(self, objective_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{BASE}/objectives/{objective_id}/protests", payload, headers
        )

    def list_protests(self, objective_id: str, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET",
            f"{BASE}/objectives/{objective_id}/protests",
            headers=headers,
            params=params,
        )

    def resolve_protest(
        self, objective_id: str, protest_id: str, payload: dict, headers: dict
    ):
        return self._request(
            "POST",
            f"{BASE}/objectives/{objective_id}/protests/{protest_id}/resolve",
            payload,
            headers,
        )

    def finalize_objective(
        self, objective_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST", f"{BASE}/objectives/{objective_id}/finalize", payload or {}, headers
        )

    # --- Dealers -----------------------------------------------------------
    def create_dealer(self, payload: dict, headers: dict):
        return self._request("POST", f"{BASE}/dealers", payload, headers)

    def get_dealer(self, dealer_id: str, headers: dict):
        return self._request("GET", f"{BASE}/dealers/{dealer_id}", headers=headers)

    def set_dealer_status(self, dealer_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{BASE}/dealers/{dealer_id}/status", payload, headers
        )

    # --- Retail deliveries -------------------------------------------------
    def create_delivery(self, payload: dict, headers: dict):
        return self._request("POST", f"{BASE}/deliveries", payload, headers)

    def get_delivery(self, delivery_id: str, headers: dict):
        return self._request("GET", f"{BASE}/deliveries/{delivery_id}", headers=headers)

    def list_deliveries(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{BASE}/deliveries", headers=headers, params=params)

    def validate_delivery(
        self, delivery_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST", f"{BASE}/deliveries/{delivery_id}/validate", payload or {}, headers
        )

    def reject_delivery(self, delivery_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{BASE}/deliveries/{delivery_id}/reject", payload, headers
        )

    def unwind_delivery(self, delivery_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{BASE}/deliveries/{delivery_id}/unwind", payload, headers
        )

    def get_eligible_programs(self, delivery_id: str, headers: dict):
        return self._request(
            "GET", f"{BASE}/deliveries/{delivery_id}/eligible-programs", headers=headers
        )

    # --- Claims ------------------------------------------------------------
    def create_claim(self, payload: dict, headers: dict):
        return self._request("POST", f"{BASE}/claims", payload, headers)

    def get_claim(self, claim_id: str, headers: dict):
        return self._request("GET", f"{BASE}/claims/{claim_id}", headers=headers)

    def list_claims(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{BASE}/claims", headers=headers, params=params)

    def adjudicate_claim(self, claim_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{BASE}/claims/{claim_id}/adjudicate", payload, headers
        )

    def create_chargeback(self, claim_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{BASE}/claims/{claim_id}/chargebacks", payload, headers
        )

    def list_chargebacks(self, claim_id: str, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"{BASE}/claims/{claim_id}/chargebacks", headers=headers, params=params
        )

    # --- Chargeback resolution --------------------------------------------
    def recover_chargeback(
        self, chargeback_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST", f"{BASE}/chargebacks/{chargeback_id}/recover", payload or {}, headers
        )

    def write_off_chargeback(
        self, chargeback_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST",
            f"{BASE}/chargebacks/{chargeback_id}/write-off",
            payload or {},
            headers,
        )

    # --- Payment batches ---------------------------------------------------
    def create_payment_batch(self, payload: dict, headers: dict):
        return self._request("POST", f"{BASE}/payment-batches", payload, headers)

    def get_payment_batch(self, batch_id: str, headers: dict):
        return self._request(
            "GET", f"{BASE}/payment-batches/{batch_id}", headers=headers
        )

    def schedule_claims(self, batch_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{BASE}/payment-batches/{batch_id}/schedule-claims", payload, headers
        )

    def lock_batch(self, batch_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"{BASE}/payment-batches/{batch_id}/lock", payload or {}, headers
        )

    def disburse_batch(self, batch_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"{BASE}/payment-batches/{batch_id}/disburse", payload or {}, headers
        )

    def cancel_batch(self, batch_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"{BASE}/payment-batches/{batch_id}/cancel", payload or {}, headers
        )


api_client = ApiClient()
