"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # --- customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/rideshare/customers", payload, headers)

    # --- missions ---
    def create_mission(self, payload, headers):
        return self._request("POST", "/rideshare/missions", payload, headers)

    def get_mission(self, mission_id, headers):
        return self._request("GET", f"/rideshare/missions/{mission_id}", headers=headers)

    def lock_manifest(self, mission_id, headers):
        return self._request(
            "POST", f"/rideshare/missions/{mission_id}/lock-manifest", {}, headers
        )

    def launch_mission(self, mission_id, headers):
        return self._request(
            "POST", f"/rideshare/missions/{mission_id}/launch", {}, headers
        )

    def scrub_mission(self, mission_id, reason_code, headers):
        return self._request(
            "POST",
            f"/rideshare/missions/{mission_id}/scrub",
            {"reason_code": reason_code},
            headers,
        )

    def delay_mission(self, mission_id, payload, headers):
        return self._request(
            "POST", f"/rideshare/missions/{mission_id}/delay", payload, headers
        )

    def create_dispenser_port(self, mission_id, payload, headers):
        return self._request(
            "POST", f"/rideshare/missions/{mission_id}/dispenser-ports", payload, headers
        )

    def list_dispenser_ports(self, mission_id, headers, params=None):
        return self._request(
            "GET",
            f"/rideshare/missions/{mission_id}/dispenser-ports",
            headers=headers,
            params=params,
        )

    def list_mission_range_slots(self, mission_id, headers, params=None):
        return self._request(
            "GET",
            f"/rideshare/missions/{mission_id}/range-slots",
            headers=headers,
            params=params,
        )

    def list_mission_delay_events(self, mission_id, headers, params=None):
        return self._request(
            "GET",
            f"/rideshare/missions/{mission_id}/delay-events",
            headers=headers,
            params=params,
        )

    def list_mission_anomalies(self, mission_id, headers, params=None):
        return self._request(
            "GET",
            f"/rideshare/missions/{mission_id}/anomalies",
            headers=headers,
            params=params,
        )

    # --- contracts & payloads ---
    def create_contract(self, payload, headers):
        return self._request("POST", "/rideshare/contracts", payload, headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/rideshare/contracts", headers=headers, params=params)

    def get_contract(self, contract_id, headers):
        return self._request(
            "GET", f"/rideshare/contracts/{contract_id}", headers=headers
        )

    def sign_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/rideshare/contracts/{contract_id}/sign", {}, headers
        )

    def rebook_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/rideshare/contracts/{contract_id}/rebook", payload, headers
        )

    def list_contract_payloads(self, contract_id, headers, params=None):
        return self._request(
            "GET",
            f"/rideshare/contracts/{contract_id}/payloads",
            headers=headers,
            params=params,
        )

    # --- manifest assignments ---
    def create_assignment(self, payload, headers):
        return self._request("POST", "/rideshare/assignments", payload, headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/rideshare/assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/rideshare/assignments/{assignment_id}", headers=headers
        )

    def confirm_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/rideshare/assignments/{assignment_id}/confirm", {}, headers
        )

    def remove_assignment(self, assignment_id, headers, reason_code=None):
        payload = {} if reason_code is None else {"reason_code": reason_code}
        return self._request(
            "POST", f"/rideshare/assignments/{assignment_id}/remove", payload, headers
        )

    def create_verification(self, assignment_id, payload, headers):
        return self._request(
            "POST",
            f"/rideshare/assignments/{assignment_id}/verifications",
            payload,
            headers,
        )

    def list_verifications(self, assignment_id, headers, params=None):
        return self._request(
            "GET",
            f"/rideshare/assignments/{assignment_id}/verifications",
            headers=headers,
            params=params,
        )

    def create_safety_review(self, assignment_id, payload, headers):
        return self._request(
            "POST",
            f"/rideshare/assignments/{assignment_id}/safety-reviews",
            payload,
            headers,
        )

    def list_safety_reviews(self, assignment_id, headers, params=None):
        return self._request(
            "GET",
            f"/rideshare/assignments/{assignment_id}/safety-reviews",
            headers=headers,
            params=params,
        )

    # --- regulatory licensing ---
    def create_license(self, payload, headers):
        return self._request("POST", "/rideshare/licenses", payload, headers)

    def list_licenses(self, headers, params=None):
        return self._request("GET", "/rideshare/licenses", headers=headers, params=params)

    def get_license(self, license_id, headers):
        return self._request("GET", f"/rideshare/licenses/{license_id}", headers=headers)

    def transition_license(self, license_id, to_state, headers):
        return self._request(
            "POST",
            f"/rideshare/licenses/{license_id}/transition",
            {"to_state": to_state},
            headers,
        )

    # --- range scheduling ---
    def create_range_slot(self, payload, headers):
        return self._request("POST", "/rideshare/range-slots", payload, headers)

    def reserve_range_slot(self, slot_id, headers):
        return self._request(
            "POST", f"/rideshare/range-slots/{slot_id}/reserve", {}, headers
        )

    def confirm_range_slot(self, slot_id, headers):
        return self._request(
            "POST", f"/rideshare/range-slots/{slot_id}/confirm", {}, headers
        )

    def create_exclusion_window(self, payload, headers):
        return self._request("POST", "/rideshare/exclusion-windows", payload, headers)

    # --- post-launch ---
    def list_separation_events(self, headers, params=None):
        return self._request(
            "GET", "/rideshare/separation-events", headers=headers, params=params
        )

    def get_separation_event(self, event_id, headers):
        return self._request(
            "GET", f"/rideshare/separation-events/{event_id}", headers=headers
        )

    def report_separation_outcome(self, event_id, payload, headers):
        return self._request(
            "POST",
            f"/rideshare/separation-events/{event_id}/report-outcome",
            payload,
            headers,
        )

    def transition_anomaly(self, anomaly_id, payload, headers):
        return self._request(
            "POST", f"/rideshare/anomalies/{anomaly_id}/transition", payload, headers
        )


api_client = ApiClient()
