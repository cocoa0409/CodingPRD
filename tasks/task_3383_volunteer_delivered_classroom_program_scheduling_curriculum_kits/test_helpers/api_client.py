"""API client: one method per endpoint defined in the PRD §4 table."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/ja-programs"


class ApiClient(GenericApiClient):
    # ---- logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # ---- area offices ----
    def create_area_office(self, payload, headers):
        return self._request("POST", f"{PREFIX}/area-offices", payload, headers)

    # ---- districts ----
    def create_district(self, payload, headers):
        return self._request("POST", f"{PREFIX}/districts", payload, headers)

    def get_district(self, district_id, headers):
        return self._request("GET", f"{PREFIX}/districts/{district_id}", headers=headers)

    def list_districts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/districts", headers=headers, params=params)

    def transition_district(self, district_id, payload, headers):
        return self._request("POST", f"{PREFIX}/districts/{district_id}/transition", payload, headers)

    # ---- schools ----
    def create_school(self, payload, headers):
        return self._request("POST", f"{PREFIX}/schools", payload, headers)

    def get_school(self, school_id, headers):
        return self._request("GET", f"{PREFIX}/schools/{school_id}", headers=headers)

    def list_schools(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/schools", headers=headers, params=params)

    # ---- corporate partners ----
    def create_corporate_partner(self, payload, headers):
        return self._request("POST", f"{PREFIX}/corporate-partners", payload, headers)

    def transition_corporate_partner(self, partner_id, payload, headers):
        return self._request("POST", f"{PREFIX}/corporate-partners/{partner_id}/transition", payload, headers)

    # ---- volunteers ----
    def create_volunteer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/volunteers", payload, headers)

    def get_volunteer(self, volunteer_id, headers):
        return self._request("GET", f"{PREFIX}/volunteers/{volunteer_id}", headers=headers)

    def list_volunteers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/volunteers", headers=headers, params=params)

    def create_credential_event(self, volunteer_id, payload, headers):
        return self._request("POST", f"{PREFIX}/volunteers/{volunteer_id}/credential-events", payload, headers)

    # ---- program catalog ----
    def create_program_catalog(self, payload, headers):
        return self._request("POST", f"{PREFIX}/program-catalogs", payload, headers)

    def get_program_catalog(self, program_id, headers):
        return self._request("GET", f"{PREFIX}/program-catalogs/{program_id}", headers=headers)

    # ---- partnership agreements ----
    def create_partnership_agreement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/partnership-agreements", payload, headers)

    def get_partnership_agreement(self, agreement_id, headers):
        return self._request("GET", f"{PREFIX}/partnership-agreements/{agreement_id}", headers=headers)

    def list_partnership_agreements(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/partnership-agreements", headers=headers, params=params)

    def transition_partnership_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"{PREFIX}/partnership-agreements/{agreement_id}/transition", payload, headers)

    def get_evaluation(self, agreement_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/partnership-agreements/{agreement_id}/evaluation", headers=headers, params=params)

    # ---- classroom deliveries ----
    def create_delivery(self, payload, headers):
        return self._request("POST", f"{PREFIX}/deliveries", payload, headers)

    def get_delivery(self, delivery_id, headers):
        return self._request("GET", f"{PREFIX}/deliveries/{delivery_id}", headers=headers)

    def list_deliveries(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/deliveries", headers=headers, params=params)

    def transition_delivery(self, delivery_id, payload, headers):
        return self._request("POST", f"{PREFIX}/deliveries/{delivery_id}/transition", payload, headers)

    # ---- sessions ----
    def create_session(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sessions", payload, headers)

    def get_session(self, session_id, headers):
        return self._request("GET", f"{PREFIX}/sessions/{session_id}", headers=headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/sessions", headers=headers, params=params)

    def transition_session(self, session_id, payload, headers):
        return self._request("POST", f"{PREFIX}/sessions/{session_id}/transition", payload, headers)

    def substitute_session(self, session_id, payload, headers):
        return self._request("POST", f"{PREFIX}/sessions/{session_id}/substitute", payload, headers)

    # ---- kit inventories ----
    def create_kit_inventory(self, payload, headers):
        return self._request("POST", f"{PREFIX}/kit-inventories", payload, headers)

    def get_kit_inventory(self, inventory_id, headers):
        return self._request("GET", f"{PREFIX}/kit-inventories/{inventory_id}", headers=headers)

    def list_kit_inventories(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/kit-inventories", headers=headers, params=params)

    def transition_kit_inventory(self, inventory_id, payload, headers):
        return self._request("POST", f"{PREFIX}/kit-inventories/{inventory_id}/transition", payload, headers)

    # ---- capstone events ----
    def create_capstone_event(self, payload, headers):
        return self._request("POST", f"{PREFIX}/capstone-events", payload, headers)

    def get_capstone_event(self, capstone_id, headers):
        return self._request("GET", f"{PREFIX}/capstone-events/{capstone_id}", headers=headers)

    def list_capstone_events(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/capstone-events", headers=headers, params=params)

    def transition_capstone_event(self, capstone_id, payload, headers):
        return self._request("POST", f"{PREFIX}/capstone-events/{capstone_id}/transition", payload, headers)

    # ---- students ----
    def create_students(self, payload, headers):
        return self._request("POST", f"{PREFIX}/students", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"{PREFIX}/students/{student_id}", headers=headers)

    def list_students(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/students", headers=headers, params=params)

    def transition_student(self, student_id, payload, headers):
        return self._request("POST", f"{PREFIX}/students/{student_id}/transition", payload, headers)


api_client = ApiClient()
