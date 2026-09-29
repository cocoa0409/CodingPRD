"""One method per endpoint of the rail interchange car hire accounting API."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .assertions import assert_instant_equals, canonical_instant

CAR_HIRE = "/car-hire"


class ApiClient(GenericApiClient):
    """Thin transport wrapper: every method returns the raw response."""

    # ---------------------------------------------------------------- clock
    def set_clock(self, current_utc: str, headers: Optional[Dict[str, str]] = None):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ------------------------------------------------------------ railroads
    def create_railroad(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{CAR_HIRE}/railroads", payload, headers)

    def get_railroad(self, railroad_id: str, headers=None):
        return self._request("GET", f"{CAR_HIRE}/railroads/{railroad_id}", None, headers)

    def list_railroads(self, headers=None, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{CAR_HIRE}/railroads", params, headers)

    def get_railroad_exposure(self, railroad_id: str, headers=None,
                              params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"{CAR_HIRE}/railroads/{railroad_id}/exposure", params, headers
        )

    # ------------------------------------------------------------ car types
    def create_car_type(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{CAR_HIRE}/car-types", payload, headers)

    def get_car_type(self, car_type_id: str, headers=None):
        return self._request("GET", f"{CAR_HIRE}/car-types/{car_type_id}", None, headers)

    def list_car_types(self, headers=None, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{CAR_HIRE}/car-types", params, headers)

    # ------------------------------------------------------------ junctions
    def create_junction(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{CAR_HIRE}/junctions", payload, headers)

    def get_junction(self, junction_id: str, headers=None):
        return self._request("GET", f"{CAR_HIRE}/junctions/{junction_id}", None, headers)

    def list_junctions(self, headers=None, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{CAR_HIRE}/junctions", params, headers)

    # ----------------------------------------------------------------- cars
    def create_car(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{CAR_HIRE}/cars", payload, headers)

    def get_car(self, car_id: str, headers=None):
        return self._request("GET", f"{CAR_HIRE}/cars/{car_id}", None, headers)

    def list_cars(self, headers=None, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{CAR_HIRE}/cars", params, headers)

    def report_bad_order(self, car_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"{CAR_HIRE}/cars/{car_id}/bad-order-report", payload, headers
        )

    def release_to_service(self, car_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"{CAR_HIRE}/cars/{car_id}/release-to-service", payload, headers
        )

    def issue_empty_routing_obligation(self, car_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"{CAR_HIRE}/cars/{car_id}/empty-routing-obligation", payload, headers
        )

    # --------------------------------------------------- interchange events
    def create_interchange_event(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{CAR_HIRE}/interchange-events", payload, headers)

    def get_interchange_event(self, interchange_event_id: str, headers=None):
        return self._request(
            "GET", f"{CAR_HIRE}/interchange-events/{interchange_event_id}", None, headers
        )

    def list_interchange_events(self, headers=None, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{CAR_HIRE}/interchange-events", params, headers)

    # ------------------------------------------------------- hire movements
    def get_movement(self, movement_id: str, headers=None):
        return self._request(
            "GET", f"{CAR_HIRE}/hire-movements/{movement_id}", None, headers
        )

    def list_movements(self, headers=None, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{CAR_HIRE}/hire-movements", params, headers)

    # ------------------------------------------------------- reclaim claims
    def create_reclaim_claim(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{CAR_HIRE}/reclaim-claims", payload, headers)

    def get_reclaim_claim(self, reclaim_claim_id: str, headers=None):
        return self._request(
            "GET", f"{CAR_HIRE}/reclaim-claims/{reclaim_claim_id}", None, headers
        )

    def list_reclaim_claims(self, headers=None, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{CAR_HIRE}/reclaim-claims", params, headers)

    def allow_reclaim_claim(self, reclaim_claim_id: str, payload=None, headers=None):
        return self._request(
            "POST", f"{CAR_HIRE}/reclaim-claims/{reclaim_claim_id}/allow",
            payload if payload is not None else {}, headers,
        )

    def disallow_reclaim_claim(self, reclaim_claim_id: str, payload=None, headers=None):
        return self._request(
            "POST", f"{CAR_HIRE}/reclaim-claims/{reclaim_claim_id}/disallow",
            payload if payload is not None else {}, headers,
        )

    def withdraw_reclaim_claim(self, reclaim_claim_id: str, payload=None, headers=None):
        return self._request(
            "POST", f"{CAR_HIRE}/reclaim-claims/{reclaim_claim_id}/withdraw",
            payload if payload is not None else {}, headers,
        )

    # -------------------------------------------------------- embargo orders
    def create_embargo_order(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{CAR_HIRE}/embargo-orders", payload, headers)

    def get_embargo_order(self, embargo_order_id: str, headers=None):
        return self._request(
            "GET", f"{CAR_HIRE}/embargo-orders/{embargo_order_id}", None, headers
        )

    def list_embargo_orders(self, headers=None, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{CAR_HIRE}/embargo-orders", params, headers)

    def lift_embargo_order(self, embargo_order_id: str, payload=None, headers=None):
        return self._request(
            "POST", f"{CAR_HIRE}/embargo-orders/{embargo_order_id}/lift",
            payload if payload is not None else {}, headers,
        )

    # ---------------------------------------------------------- repair bills
    def create_repair_bill(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{CAR_HIRE}/repair-bills", payload, headers)

    def get_repair_bill(self, repair_bill_id: str, headers=None):
        return self._request(
            "GET", f"{CAR_HIRE}/repair-bills/{repair_bill_id}", None, headers
        )

    def list_repair_bills(self, headers=None, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{CAR_HIRE}/repair-bills", params, headers)

    def submit_repair_bill(self, repair_bill_id: str, payload=None, headers=None):
        return self._request(
            "POST", f"{CAR_HIRE}/repair-bills/{repair_bill_id}/submit",
            payload if payload is not None else {}, headers,
        )

    def counter_repair_bill(self, repair_bill_id: str, payload=None, headers=None):
        return self._request(
            "POST", f"{CAR_HIRE}/repair-bills/{repair_bill_id}/counter-bill",
            payload if payload is not None else {}, headers,
        )

    def accept_repair_bill(self, repair_bill_id: str, payload=None, headers=None):
        return self._request(
            "POST", f"{CAR_HIRE}/repair-bills/{repair_bill_id}/accept",
            payload if payload is not None else {}, headers,
        )

    def settle_repair_bill(self, repair_bill_id: str, payload=None, headers=None):
        return self._request(
            "POST", f"{CAR_HIRE}/repair-bills/{repair_bill_id}/settle",
            payload if payload is not None else {}, headers,
        )

    # ----------------------------------------------------- settlement cycles
    def create_settlement_cycle(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{CAR_HIRE}/settlement-cycles", payload, headers)

    def get_settlement_cycle(self, settlement_cycle_id: str, headers=None):
        return self._request(
            "GET", f"{CAR_HIRE}/settlement-cycles/{settlement_cycle_id}", None, headers
        )

    def list_settlement_cycles(self, headers=None, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{CAR_HIRE}/settlement-cycles", params, headers)

    def compute_settlement_cycle(self, settlement_cycle_id: str, payload=None, headers=None):
        return self._request(
            "POST", f"{CAR_HIRE}/settlement-cycles/{settlement_cycle_id}/compute",
            payload if payload is not None else {}, headers,
        )

    def exchange_settlement_cycle(self, settlement_cycle_id: str, payload=None, headers=None):
        return self._request(
            "POST", f"{CAR_HIRE}/settlement-cycles/{settlement_cycle_id}/exchange",
            payload if payload is not None else {}, headers,
        )

    def settle_settlement_cycle(self, settlement_cycle_id: str, payload=None, headers=None):
        return self._request(
            "POST", f"{CAR_HIRE}/settlement-cycles/{settlement_cycle_id}/settle",
            payload if payload is not None else {}, headers,
        )

    def reopen_settlement_cycle(self, settlement_cycle_id: str, payload=None, headers=None):
        return self._request(
            "POST", f"{CAR_HIRE}/settlement-cycles/{settlement_cycle_id}/reopen",
            payload if payload is not None else {}, headers,
        )

    def archive_settlement_cycle(self, settlement_cycle_id: str, payload=None, headers=None):
        return self._request(
            "POST", f"{CAR_HIRE}/settlement-cycles/{settlement_cycle_id}/archive",
            payload if payload is not None else {}, headers,
        )

    def get_settlement_statement(self, settlement_cycle_id: str, headers=None,
                                 params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"{CAR_HIRE}/settlement-cycles/{settlement_cycle_id}/statement",
            params, headers,
        )

    # -------------------------------------------------------------- disputes
    def create_dispute(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{CAR_HIRE}/disputes", payload, headers)

    def get_dispute(self, dispute_id: str, headers=None):
        return self._request("GET", f"{CAR_HIRE}/disputes/{dispute_id}", None, headers)

    def list_disputes(self, headers=None, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{CAR_HIRE}/disputes", params, headers)

    def counter_dispute(self, dispute_id: str, payload=None, headers=None):
        return self._request(
            "POST", f"{CAR_HIRE}/disputes/{dispute_id}/counter",
            payload if payload is not None else {}, headers,
        )

    def accept_dispute(self, dispute_id: str, payload=None, headers=None):
        return self._request(
            "POST", f"{CAR_HIRE}/disputes/{dispute_id}/accept",
            payload if payload is not None else {}, headers,
        )

    def withdraw_dispute(self, dispute_id: str, payload=None, headers=None):
        return self._request(
            "POST", f"{CAR_HIRE}/disputes/{dispute_id}/withdraw",
            payload if payload is not None else {}, headers,
        )

    # --------------------------------------------------- correction requests
    def create_correction_request(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{CAR_HIRE}/correction-requests", payload, headers)

    def get_correction_request(self, correction_request_id: str, headers=None):
        return self._request(
            "GET", f"{CAR_HIRE}/correction-requests/{correction_request_id}", None, headers
        )

    def list_correction_requests(self, headers=None, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{CAR_HIRE}/correction-requests", params, headers)

    def confirm_correction_request(self, correction_request_id: str, payload=None, headers=None):
        return self._request(
            "POST", f"{CAR_HIRE}/correction-requests/{correction_request_id}/confirm",
            payload if payload is not None else {}, headers,
        )

    def reject_correction_request(self, correction_request_id: str, payload=None, headers=None):
        return self._request(
            "POST", f"{CAR_HIRE}/correction-requests/{correction_request_id}/reject",
            payload if payload is not None else {}, headers,
        )

    def apply_correction_request(self, correction_request_id: str, payload=None, headers=None):
        return self._request(
            "POST", f"{CAR_HIRE}/correction-requests/{correction_request_id}/apply",
            payload if payload is not None else {}, headers,
        )

    def expire_due_correction_requests(self, payload=None, headers=None):
        return self._request(
            "POST", f"{CAR_HIRE}/correction-requests/expire-due",
            payload if payload is not None else {}, headers,
        )

    # --------------------------------------------------------- ledger entries
    def get_ledger_entry(self, hire_ledger_entry_id: str, headers=None):
        return self._request(
            "GET", f"{CAR_HIRE}/ledger-entries/{hire_ledger_entry_id}", None, headers
        )

    def list_ledger_entries(self, headers=None, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{CAR_HIRE}/ledger-entries", params, headers)


__all__ = ["ApiClient", "assert_instant_equals", "canonical_instant"]
