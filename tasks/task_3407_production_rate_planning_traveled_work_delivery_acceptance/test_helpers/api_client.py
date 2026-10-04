"""API client: one method per endpoint defined in PRD §4 (all under /api)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """PRD §4 endpoint surface. Creates return 201; actions on existing
    resources return 200; reads return 200."""

    # --- Logical clock (PRD §2.4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # --- Programs (PRD §3.1, §3.2) ---
    def create_program(self, payload, headers):
        return self._request("POST", "/api/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/api/programs/{program_id}", headers=headers)

    def create_rate_case(self, program_id, payload, headers):
        return self._request("POST", f"/api/programs/{program_id}/rate-cases", payload, headers)

    def list_rate_cases(self, program_id, headers, params=None):
        return self._request("GET", f"/api/programs/{program_id}/rate-cases", headers=headers, params=params)

    def announce_rate_case(self, rate_case_id, headers):
        return self._request("POST", f"/api/rate-cases/{rate_case_id}/announce", headers=headers)

    def request_gating_review(self, rate_case_id, headers):
        return self._request("POST", f"/api/rate-cases/{rate_case_id}/request-gating-review", headers=headers)

    def commit_rate_case(self, rate_case_id, headers):
        return self._request("POST", f"/api/rate-cases/{rate_case_id}/commit", headers=headers)

    def shelve_rate_case(self, rate_case_id, headers):
        return self._request("POST", f"/api/rate-cases/{rate_case_id}/shelve", headers=headers)

    # --- Suppliers and capacity commitments (PRD §3.3) ---
    def create_supplier(self, payload, headers):
        return self._request("POST", "/api/suppliers", payload, headers)

    def get_supplier(self, supplier_id, headers):
        return self._request("GET", f"/api/suppliers/{supplier_id}", headers=headers)

    def create_capacity_commitment(self, supplier_id, payload, headers):
        return self._request("POST", f"/api/suppliers/{supplier_id}/capacity-commitments", payload, headers)

    def list_supplier_commitments(self, supplier_id, headers, params=None):
        return self._request("GET", f"/api/suppliers/{supplier_id}/capacity-commitments", headers=headers, params=params)

    def list_program_commitments(self, program_id, headers, params=None):
        return self._request("GET", f"/api/programs/{program_id}/capacity-commitments", headers=headers, params=params)

    def confirm_commitment(self, commitment_id, headers):
        return self._request("POST", f"/api/capacity-commitments/{commitment_id}/confirm", headers=headers)

    def place_order(self, commitment_id, payload, headers):
        return self._request("POST", f"/api/capacity-commitments/{commitment_id}/place-order", payload, headers)

    def cancel_commitment(self, commitment_id, headers, payload=None):
        return self._request("POST", f"/api/capacity-commitments/{commitment_id}/cancel", payload, headers)

    # --- Workforce plans (PRD §3.1) ---
    def create_workforce_plan(self, program_id, payload, headers):
        return self._request("POST", f"/api/programs/{program_id}/workforce-plans", payload, headers)

    def list_workforce_plans(self, program_id, headers, params=None):
        return self._request("GET", f"/api/programs/{program_id}/workforce-plans", headers=headers, params=params)

    def hire(self, workforce_plan_id, payload, headers):
        return self._request("POST", f"/api/workforce-plans/{workforce_plan_id}/hire", payload, headers)

    # --- Customers (PRD §3.1) ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/api/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/api/customers/{customer_id}", headers=headers)

    # --- Aircraft units (PRD §3.1, §3.8) ---
    def create_aircraft_unit(self, program_id, payload, headers):
        return self._request("POST", f"/api/programs/{program_id}/aircraft-units", payload, headers)

    def get_aircraft_unit(self, aircraft_id, headers):
        return self._request("GET", f"/api/aircraft-units/{aircraft_id}", headers=headers)

    def list_program_aircraft(self, program_id, headers, params=None):
        return self._request("GET", f"/api/programs/{program_id}/aircraft-units", headers=headers, params=params)

    def list_customer_aircraft(self, customer_id, headers, params=None):
        return self._request("GET", f"/api/customers/{customer_id}/aircraft-units", headers=headers, params=params)

    # --- Work packages (PRD §3.4) ---
    def create_work_package(self, aircraft_id, payload, headers):
        return self._request("POST", f"/api/aircraft-units/{aircraft_id}/work-packages", payload, headers)

    def list_work_packages(self, aircraft_id, headers, params=None):
        return self._request("GET", f"/api/aircraft-units/{aircraft_id}/work-packages", headers=headers, params=params)

    def get_work_package(self, work_package_id, headers):
        return self._request("GET", f"/api/work-packages/{work_package_id}", headers=headers)

    def complete_work_package(self, work_package_id, headers):
        return self._request("POST", f"/api/work-packages/{work_package_id}/complete", headers=headers)

    def travel_work_package(self, work_package_id, payload, headers):
        return self._request("POST", f"/api/work-packages/{work_package_id}/travel", payload, headers)

    # --- Rework orders (PRD §3.5) ---
    def create_escape_rework_order(self, escape_id, payload, headers):
        return self._request("POST", f"/api/quality-escapes/{escape_id}/rework-orders", payload, headers)

    def list_aircraft_rework_orders(self, aircraft_id, headers, params=None):
        return self._request("GET", f"/api/aircraft-units/{aircraft_id}/rework-orders", headers=headers, params=params)

    def list_work_package_rework_orders(self, work_package_id, headers, params=None):
        return self._request("GET", f"/api/work-packages/{work_package_id}/rework-orders", headers=headers, params=params)

    def list_escape_rework_orders(self, escape_id, headers, params=None):
        return self._request("GET", f"/api/quality-escapes/{escape_id}/rework-orders", headers=headers, params=params)

    def close_rework_order(self, rework_order_id, payload, headers):
        return self._request("POST", f"/api/rework-orders/{rework_order_id}/close", payload, headers)

    def credit_rework_order(self, rework_order_id, headers):
        return self._request("POST", f"/api/rework-orders/{rework_order_id}/credit", headers=headers)

    # --- Quality escapes (PRD §3.6) ---
    def report_quality_escape(self, aircraft_id, payload, headers):
        return self._request("POST", f"/api/aircraft-units/{aircraft_id}/quality-escapes", payload, headers)

    def get_quality_escape(self, escape_id, headers):
        return self._request("GET", f"/api/quality-escapes/{escape_id}", headers=headers)

    def list_quality_escapes(self, aircraft_id, headers, params=None):
        return self._request("GET", f"/api/aircraft-units/{aircraft_id}/quality-escapes", headers=headers, params=params)

    def notify_regulator(self, escape_id, headers):
        return self._request("POST", f"/api/quality-escapes/{escape_id}/notify-regulator", headers=headers)

    def begin_root_cause(self, escape_id, payload, headers):
        return self._request("POST", f"/api/quality-escapes/{escape_id}/begin-root-cause", payload, headers)

    def disposition_escape(self, escape_id, payload, headers):
        return self._request("POST", f"/api/quality-escapes/{escape_id}/disposition", payload, headers)

    def reopen_escape(self, escape_id, headers):
        return self._request("POST", f"/api/quality-escapes/{escape_id}/reopen", headers=headers)

    def close_escape(self, escape_id, headers):
        return self._request("POST", f"/api/quality-escapes/{escape_id}/close", headers=headers)

    # --- Flight tests and delivery pipeline (PRD §3.8) ---
    def schedule_flight_test(self, aircraft_id, payload, headers):
        return self._request("POST", f"/api/aircraft-units/{aircraft_id}/flight-tests", payload, headers)

    def list_flight_tests(self, aircraft_id, headers, params=None):
        return self._request("GET", f"/api/aircraft-units/{aircraft_id}/flight-tests", headers=headers, params=params)

    def record_flight_test_outcome(self, flight_test_id, payload, headers):
        return self._request("POST", f"/api/flight-tests/{flight_test_id}/record-outcome", payload, headers)

    def begin_delivery(self, aircraft_id, headers):
        return self._request("POST", f"/api/aircraft-units/{aircraft_id}/begin-delivery", headers=headers)

    def verify_configuration(self, aircraft_id, headers):
        return self._request("POST", f"/api/aircraft-units/{aircraft_id}/verify-configuration", headers=headers)

    def conduct_walkthrough(self, aircraft_id, payload, headers):
        return self._request("POST", f"/api/aircraft-units/{aircraft_id}/conduct-walkthrough", payload, headers)

    def accept_delivery(self, aircraft_id, headers):
        return self._request("POST", f"/api/aircraft-units/{aircraft_id}/accept-delivery", headers=headers)

    # --- Storage and preservation (PRD §3.7) ---
    def create_storage_preservation(self, aircraft_id, payload, headers):
        return self._request("POST", f"/api/aircraft-units/{aircraft_id}/storage-preservations", payload, headers)

    def list_storage_preservations(self, aircraft_id, headers, params=None):
        return self._request("GET", f"/api/aircraft-units/{aircraft_id}/storage-preservations", headers=headers, params=params)

    def maintain_storage(self, storage_id, headers):
        return self._request("POST", f"/api/storage-preservations/{storage_id}/maintain", headers=headers)

    def release_storage(self, storage_id, headers):
        return self._request("POST", f"/api/storage-preservations/{storage_id}/release", headers=headers)

    # --- Delivery negotiations (PRD §3.9) ---
    def create_delivery_negotiation(self, aircraft_id, payload, headers):
        return self._request("POST", f"/api/aircraft-units/{aircraft_id}/delivery-negotiations", payload, headers)

    def list_delivery_negotiations(self, aircraft_id, headers, params=None):
        return self._request("GET", f"/api/aircraft-units/{aircraft_id}/delivery-negotiations", headers=headers, params=params)

    def counter_negotiation(self, negotiation_id, payload, headers):
        return self._request("POST", f"/api/delivery-negotiations/{negotiation_id}/counter", payload, headers)

    def agree_negotiation(self, negotiation_id, headers):
        return self._request("POST", f"/api/delivery-negotiations/{negotiation_id}/agree", headers=headers)


api_client = ApiClient()
