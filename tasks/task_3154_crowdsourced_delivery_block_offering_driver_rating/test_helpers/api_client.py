"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Thin, typed wrapper over the PRD's endpoint surface."""

    # ------------------------------------------------------------------
    # Logical clock (test-driving)
    # ------------------------------------------------------------------
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Stations
    # ------------------------------------------------------------------
    def create_station(self, payload, headers):
        return self._request("POST", "/stations", payload, headers)

    def get_station(self, station_id, headers):
        return self._request("GET", f"/stations/{station_id}", None, headers)

    def list_station_blocks(self, station_id, headers, params=None):
        return self._request("GET", f"/stations/{station_id}/blocks", None, headers, params)

    def create_block(self, station_id, payload, headers):
        return self._request("POST", f"/stations/{station_id}/blocks", payload, headers)

    def run_surge_cycle(self, station_id, payload, headers):
        return self._request(
            "POST", f"/stations/{station_id}/run-surge-cycle", payload, headers
        )

    # ------------------------------------------------------------------
    # Drivers and screening
    # ------------------------------------------------------------------
    def register_driver(self, payload, headers):
        return self._request("POST", "/drivers/register", payload, headers)

    def get_driver(self, driver_id, headers):
        return self._request("GET", f"/drivers/{driver_id}", None, headers)

    def list_driver_screenings(self, driver_id, headers, params=None):
        return self._request("GET", f"/drivers/{driver_id}/screenings", None, headers, params)

    def begin_screening_review(self, screening_id, headers):
        return self._request("POST", f"/screenings/{screening_id}/begin-review", None, headers)

    def decide_screening(self, screening_id, payload, headers):
        return self._request("POST", f"/screenings/{screening_id}/decide", payload, headers)

    def reopen_screening(self, screening_id, headers):
        return self._request("POST", f"/screenings/{screening_id}/reopen", None, headers)

    def activate_driver(self, driver_id, headers):
        return self._request("POST", f"/drivers/{driver_id}/activate", None, headers)

    def deactivate_driver(self, driver_id, payload, headers):
        return self._request("POST", f"/drivers/{driver_id}/deactivate", payload, headers)

    # ------------------------------------------------------------------
    # Vehicles
    # ------------------------------------------------------------------
    def create_vehicle(self, driver_id, payload, headers):
        return self._request("POST", f"/drivers/{driver_id}/vehicles", payload, headers)

    def list_driver_vehicles(self, driver_id, headers, params=None):
        return self._request("GET", f"/drivers/{driver_id}/vehicles", None, headers, params)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/vehicles/{vehicle_id}", None, headers)

    def attest_insurance(self, vehicle_id, payload, headers):
        return self._request(
            "POST", f"/vehicles/{vehicle_id}/attest-insurance", payload, headers
        )

    def retire_vehicle(self, vehicle_id, headers):
        return self._request("POST", f"/vehicles/{vehicle_id}/retire", None, headers)

    def list_vehicle_assignments(self, vehicle_id, headers, params=None):
        return self._request("GET", f"/vehicles/{vehicle_id}/assignments", None, headers, params)

    # ------------------------------------------------------------------
    # Blocks
    # ------------------------------------------------------------------
    def get_block(self, block_id, headers):
        return self._request("GET", f"/blocks/{block_id}", None, headers)

    def publish_block(self, block_id, headers):
        return self._request("POST", f"/blocks/{block_id}/publish", None, headers)

    def revise_block(self, block_id, payload, headers):
        return self._request("POST", f"/blocks/{block_id}/revise", payload, headers)

    def cancel_block(self, block_id, headers):
        return self._request("POST", f"/blocks/{block_id}/cancel", None, headers)

    def accept_block(self, block_id, payload, headers):
        return self._request("POST", f"/blocks/{block_id}/accept", payload, headers)

    def list_block_offers(self, block_id, headers, params=None):
        return self._request("GET", f"/blocks/{block_id}/offers", None, headers, params)

    def list_block_assignments(self, block_id, headers, params=None):
        return self._request("GET", f"/blocks/{block_id}/assignments", None, headers, params)

    def create_offer(self, block_id, payload, headers):
        return self._request("POST", f"/blocks/{block_id}/offers", payload, headers)

    # ------------------------------------------------------------------
    # Offers
    # ------------------------------------------------------------------
    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/offers/{offer_id}", None, headers)

    def accept_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/offers/{offer_id}/accept", payload, headers)

    def decline_offer(self, offer_id, headers):
        return self._request("POST", f"/offers/{offer_id}/decline", None, headers)

    def list_offer_assignments(self, offer_id, headers):
        return self._request("GET", f"/offers/{offer_id}/assignments", None, headers)

    # ------------------------------------------------------------------
    # Driver-scoped reverse lists
    # ------------------------------------------------------------------
    def list_driver_assigned_blocks(self, driver_id, headers, params=None):
        return self._request(
            "GET", f"/drivers/{driver_id}/assigned-blocks", None, headers, params
        )

    def list_driver_rating_events(self, driver_id, headers, params=None):
        return self._request(
            "GET", f"/drivers/{driver_id}/rating-events", None, headers, params
        )

    def list_driver_assignments(self, driver_id, headers, params=None):
        return self._request("GET", f"/drivers/{driver_id}/assignments", None, headers, params)

    def list_driver_offers(self, driver_id, headers, params=None):
        return self._request("GET", f"/drivers/{driver_id}/offers", None, headers, params)

    # ------------------------------------------------------------------
    # Assignments
    # ------------------------------------------------------------------
    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}", None, headers)

    def check_in_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/check-in", None, headers)

    def load_packages(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/assignments/{assignment_id}/load-packages", payload, headers
        )

    def list_assignment_packages(self, assignment_id, headers, params=None):
        return self._request(
            "GET", f"/assignments/{assignment_id}/packages", None, headers, params
        )

    def list_assignment_rating_events(self, assignment_id, headers):
        return self._request(
            "GET", f"/assignments/{assignment_id}/rating-events", None, headers
        )

    def depart_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/depart", None, headers)

    def forfeit_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/assignments/{assignment_id}/forfeit", payload, headers)

    def complete_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/complete", None, headers)

    def get_assignment_pay_statement(self, assignment_id, headers):
        return self._request(
            "GET", f"/assignments/{assignment_id}/pay-statement", None, headers
        )

    # ------------------------------------------------------------------
    # Packages
    # ------------------------------------------------------------------
    def deliver_package(self, package_id, payload, headers):
        return self._request("POST", f"/packages/{package_id}/deliver", payload, headers)

    def report_package_failed(self, package_id, payload, headers):
        return self._request("POST", f"/packages/{package_id}/report-failed", payload, headers)

    # ------------------------------------------------------------------
    # Pay statements
    # ------------------------------------------------------------------
    def settle_pay_statement(self, pay_statement_id, headers):
        return self._request(
            "POST", f"/pay-statements/{pay_statement_id}/settle", None, headers
        )

    def void_pay_statement(self, pay_statement_id, headers):
        return self._request("POST", f"/pay-statements/{pay_statement_id}/void", None, headers)

    # ------------------------------------------------------------------
    # Appeals
    # ------------------------------------------------------------------
    def create_appeal(self, driver_id, payload, headers):
        return self._request("POST", f"/drivers/{driver_id}/appeals", payload, headers)

    def list_driver_appeals(self, driver_id, headers, params=None):
        return self._request("GET", f"/drivers/{driver_id}/appeals", None, headers, params)

    def submit_appeal_evidence(self, appeal_id, payload, headers):
        return self._request(
            "POST", f"/appeals/{appeal_id}/submit-evidence", payload, headers
        )

    def request_appeal_evidence(self, appeal_id, payload, headers):
        return self._request(
            "POST", f"/appeals/{appeal_id}/request-evidence", payload, headers
        )

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/appeals/{appeal_id}/decide", payload, headers)

    # ------------------------------------------------------------------
    # Driver feed
    # ------------------------------------------------------------------
    def get_driver_feed(self, headers, params=None):
        return self._request("GET", "/driver-feed/blocks", None, headers, params)


api_client = ApiClient()
