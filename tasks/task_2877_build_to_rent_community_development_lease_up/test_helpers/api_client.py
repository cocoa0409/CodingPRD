"""API client: one method per endpoint defined in the PRD (§4)."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Communities ---
    def create_community(self, payload, headers):
        return self._request("POST", "/communities", payload, headers)

    def get_community(self, community_id, headers):
        return self._request("GET", f"/communities/{community_id}", headers=headers)

    def list_communities(self, headers, params=None):
        return self._request("GET", "/communities", headers=headers, params=params)

    def get_community_valuation(self, community_id, headers, params=None):
        return self._request(
            "GET", f"/communities/{community_id}/valuation", headers=headers, params=params
        )

    def submit_plat(self, community_id, payload, headers):
        return self._request(
            "POST", f"/communities/{community_id}/plat-submissions", payload, headers
        )

    def decide_plat(self, community_id, payload, headers):
        return self._request(
            "POST", f"/communities/{community_id}/plat-decisions", payload, headers
        )

    def create_absorption_review(self, community_id, payload, headers):
        return self._request(
            "POST", f"/communities/{community_id}/absorption-reviews", payload, headers
        )

    def create_pm_transition(self, community_id, payload, headers):
        return self._request(
            "POST", f"/communities/{community_id}/pm-transitions", payload, headers
        )

    def resize_facility_commitment(self, community_id, payload, headers):
        return self._request(
            "POST", f"/communities/{community_id}/facility-commitments", payload, headers
        )

    def convert_facility(self, community_id, payload, headers):
        return self._request(
            "POST", f"/communities/{community_id}/facility-conversions", payload, headers
        )

    # --- Phases ---
    def create_phase(self, payload, headers):
        return self._request("POST", "/phases", payload, headers)

    def get_phase(self, phase_id, headers):
        return self._request("GET", f"/phases/{phase_id}", headers=headers)

    def list_phases(self, headers, params=None):
        return self._request("GET", "/phases", headers=headers, params=params)

    def start_construction(self, phase_id, payload, headers):
        return self._request(
            "POST", f"/phases/{phase_id}/construction-start", payload, headers
        )

    def release_section(self, phase_id, payload, headers):
        return self._request(
            "POST", f"/phases/{phase_id}/section-releases", payload, headers
        )

    def complete_phase(self, phase_id, payload, headers):
        return self._request("POST", f"/phases/{phase_id}/completion", payload, headers)

    def halt_phase(self, phase_id, payload, headers):
        return self._request("POST", f"/phases/{phase_id}/halt", payload, headers)

    def resume_phase(self, phase_id, payload, headers):
        return self._request("POST", f"/phases/{phase_id}/resume", payload, headers)

    # --- Homesites ---
    def create_homesite(self, payload, headers):
        return self._request("POST", "/homesites", payload, headers)

    def get_homesite(self, homesite_id, headers):
        return self._request("GET", f"/homesites/{homesite_id}", headers=headers)

    def list_homesites(self, headers, params=None):
        return self._request("GET", "/homesites", headers=headers, params=params)

    def record_occupancy_certificate(self, homesite_id, payload, headers):
        return self._request(
            "POST", f"/homesites/{homesite_id}/occupancy-certificates", payload, headers
        )

    # --- Market rent schedules ---
    def publish_market_rent_schedule(self, payload, headers):
        return self._request("POST", "/market-rent-schedules", payload, headers)

    def get_market_rent_schedule(self, schedule_id, headers):
        return self._request(
            "GET", f"/market-rent-schedules/{schedule_id}", headers=headers
        )

    def list_market_rent_schedules(self, headers, params=None):
        return self._request(
            "GET", "/market-rent-schedules", headers=headers, params=params
        )

    # --- Concession programs ---
    def create_concession_program(self, payload, headers):
        return self._request("POST", "/concession-programs", payload, headers)

    def get_concession_program(self, program_id, headers):
        return self._request("GET", f"/concession-programs/{program_id}", headers=headers)

    def list_concession_programs(self, headers, params=None):
        return self._request("GET", "/concession-programs", headers=headers, params=params)

    # --- Households ---
    def create_household(self, payload, headers):
        return self._request("POST", "/households", payload, headers)

    def get_household(self, household_id, headers):
        return self._request("GET", f"/households/{household_id}", headers=headers)

    def list_households(self, headers, params=None):
        return self._request("GET", "/households", headers=headers, params=params)

    # --- Leases ---
    def create_lease(self, payload, headers):
        return self._request("POST", "/leases", payload, headers)

    def get_lease(self, lease_id, headers):
        return self._request("GET", f"/leases/{lease_id}", headers=headers)

    def list_leases(self, headers, params=None):
        return self._request("GET", "/leases", headers=headers, params=params)

    def request_concession(self, lease_id, payload, headers):
        return self._request(
            "POST", f"/leases/{lease_id}/concession-requests", payload, headers
        )

    def decide_concession(self, lease_id, payload, headers):
        return self._request(
            "POST", f"/leases/{lease_id}/concession-decisions", payload, headers
        )

    def submit_lease(self, lease_id, payload, headers):
        return self._request("POST", f"/leases/{lease_id}/submissions", payload, headers)

    def sign_lease(self, lease_id, payload, headers):
        return self._request("POST", f"/leases/{lease_id}/signature", payload, headers)

    def activate_lease(self, lease_id, payload, headers):
        return self._request("POST", f"/leases/{lease_id}/activation", payload, headers)

    def apply_concession_credit(self, lease_id, payload, headers):
        return self._request(
            "POST", f"/leases/{lease_id}/concession-credit-applications", payload, headers
        )

    def give_notice(self, lease_id, payload, headers):
        return self._request("POST", f"/leases/{lease_id}/notices", payload, headers)

    def cancel_lease(self, lease_id, payload, headers):
        return self._request("POST", f"/leases/{lease_id}/cancellation", payload, headers)

    # --- Turn work orders ---
    def create_turn_work_order(self, payload, headers):
        return self._request("POST", "/turn-work-orders", payload, headers)

    def get_turn_work_order(self, order_id, headers):
        return self._request("GET", f"/turn-work-orders/{order_id}", headers=headers)

    def list_turn_work_orders(self, headers, params=None):
        return self._request("GET", "/turn-work-orders", headers=headers, params=params)

    def complete_turn_work_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/turn-work-orders/{order_id}/completion", payload, headers
        )

    # --- Absorption reviews ---
    def get_absorption_review(self, review_id, headers):
        return self._request("GET", f"/absorption-reviews/{review_id}", headers=headers)

    def list_absorption_reviews(self, headers, params=None):
        return self._request("GET", "/absorption-reviews", headers=headers, params=params)

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
