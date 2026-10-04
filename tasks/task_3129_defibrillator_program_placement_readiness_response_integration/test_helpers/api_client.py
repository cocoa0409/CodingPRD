"""API client: one method per endpoint defined in the PRD (all under /api)."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # --- Campus ---
    def create_campus(self, payload, headers):
        return self._request("POST", "/api/campuses", payload, headers)

    def get_campus(self, campus_id, headers):
        return self._request("GET", f"/api/campuses/{campus_id}", headers=headers)

    def list_campuses(self, headers, params=None):
        return self._request("GET", "/api/campuses", headers=headers, params=params)

    def get_coverage_report(self, campus_id, headers, params=None):
        return self._request(
            "GET", f"/api/campuses/{campus_id}/coverage-report",
            headers=headers, params=params,
        )

    # --- Zone ---
    def create_zone(self, payload, headers):
        return self._request("POST", "/api/zones", payload, headers)

    def get_zone(self, zone_id, headers):
        return self._request("GET", f"/api/zones/{zone_id}", headers=headers)

    def list_zones(self, headers, params=None):
        return self._request("GET", "/api/zones", headers=headers, params=params)

    # --- DeviceModel ---
    def create_device_model(self, payload, headers):
        return self._request("POST", "/api/device-models", payload, headers)

    def get_device_model(self, device_model_id, headers):
        return self._request(
            "GET", f"/api/device-models/{device_model_id}", headers=headers
        )

    # --- Cabinet ---
    def create_cabinet(self, payload, headers):
        return self._request("POST", "/api/cabinets", payload, headers)

    def get_cabinet(self, cabinet_id, headers):
        return self._request("GET", f"/api/cabinets/{cabinet_id}", headers=headers)

    def list_cabinets(self, headers, params=None):
        return self._request("GET", "/api/cabinets", headers=headers, params=params)

    def open_cabinet(self, cabinet_id, headers, payload=None):
        return self._request(
            "POST", f"/api/cabinets/{cabinet_id}/open", payload or {}, headers
        )

    # --- Device ---
    def create_device(self, payload, headers):
        return self._request("POST", "/api/devices", payload, headers)

    def get_device(self, device_id, headers):
        return self._request("GET", f"/api/devices/{device_id}", headers=headers)

    def list_devices(self, headers, params=None):
        return self._request("GET", "/api/devices", headers=headers, params=params)

    def install_device(self, device_id, payload, headers):
        return self._request(
            "POST", f"/api/devices/{device_id}/install", payload, headers
        )

    def commission_device(self, device_id, headers, payload=None):
        return self._request(
            "POST", f"/api/devices/{device_id}/commission", payload or {}, headers
        )

    def send_device_to_maintenance(self, device_id, headers, payload=None):
        return self._request(
            "POST", f"/api/devices/{device_id}/send_to_maintenance",
            payload or {}, headers,
        )

    def return_device_to_service(self, device_id, headers, payload=None):
        return self._request(
            "POST", f"/api/devices/{device_id}/return_to_service",
            payload or {}, headers,
        )

    def decommission_device(self, device_id, headers, payload=None):
        return self._request(
            "POST", f"/api/devices/{device_id}/decommission", payload or {}, headers
        )

    # --- ConsumableLot ---
    def create_consumable_lot(self, payload, headers):
        return self._request("POST", "/api/consumable-lots", payload, headers)

    def get_consumable_lot(self, lot_id, headers):
        return self._request(
            "GET", f"/api/consumable-lots/{lot_id}", headers=headers
        )

    def list_consumable_lots(self, headers, params=None):
        return self._request(
            "GET", "/api/consumable-lots", headers=headers, params=params
        )

    # --- Install ---
    def create_install(self, payload, headers):
        return self._request("POST", "/api/installs", payload, headers)

    def get_install(self, install_id, headers):
        return self._request("GET", f"/api/installs/{install_id}", headers=headers)

    def list_installs(self, headers, params=None):
        return self._request("GET", "/api/installs", headers=headers, params=params)

    def remove_install(self, install_id, headers, payload=None):
        return self._request(
            "POST", f"/api/installs/{install_id}/remove", payload or {}, headers
        )

    # --- Inspection ---
    def create_inspection(self, payload, headers):
        return self._request("POST", "/api/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request(
            "GET", f"/api/inspections/{inspection_id}", headers=headers
        )

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/api/inspections", headers=headers, params=params)

    def submit_inspection(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"/api/inspections/{inspection_id}/submit", payload, headers
        )

    # --- SelfTestReport ---
    def create_self_test_report(self, payload, headers):
        return self._request("POST", "/api/self-test-reports", payload, headers)

    def list_self_test_reports(self, headers, params=None):
        return self._request(
            "GET", "/api/self-test-reports", headers=headers, params=params
        )

    # --- Responder ---
    def create_responder(self, payload, headers):
        return self._request("POST", "/api/responders", payload, headers)

    def get_responder(self, responder_id, headers):
        return self._request("GET", f"/api/responders/{responder_id}", headers=headers)

    def list_responders(self, headers, params=None):
        return self._request("GET", "/api/responders", headers=headers, params=params)

    # --- TrainingSession ---
    def create_training_session(self, payload, headers):
        return self._request("POST", "/api/training-sessions", payload, headers)

    def get_training_session(self, session_id, headers):
        return self._request(
            "GET", f"/api/training-sessions/{session_id}", headers=headers
        )

    def list_training_sessions(self, headers, params=None):
        return self._request(
            "GET", "/api/training-sessions", headers=headers, params=params
        )

    def enroll_training_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"/api/training-sessions/{session_id}/enroll", payload, headers
        )

    def complete_training_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"/api/training-sessions/{session_id}/complete", payload, headers
        )

    def cancel_training_session(self, session_id, headers, payload=None):
        return self._request(
            "POST", f"/api/training-sessions/{session_id}/cancel",
            payload or {}, headers,
        )

    # --- EmergencyEvent ---
    def get_emergency_event(self, event_id, headers):
        return self._request(
            "GET", f"/api/emergency-events/{event_id}", headers=headers
        )

    def list_emergency_events(self, headers, params=None):
        return self._request(
            "GET", "/api/emergency-events", headers=headers, params=params
        )

    def acknowledge_emergency_event(self, event_id, headers, payload=None):
        return self._request(
            "POST", f"/api/emergency-events/{event_id}/acknowledge",
            payload or {}, headers,
        )

    def resolve_emergency_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"/api/emergency-events/{event_id}/resolve", payload, headers
        )

    def close_emergency_event_no_patient(self, event_id, headers, payload=None):
        return self._request(
            "POST", f"/api/emergency-events/{event_id}/close_no_patient",
            payload or {}, headers,
        )

    # --- CaseReview ---
    def create_case_review(self, payload, headers):
        return self._request("POST", "/api/case-reviews", payload, headers)

    def get_case_review(self, review_id, headers):
        return self._request("GET", f"/api/case-reviews/{review_id}", headers=headers)

    def list_case_reviews(self, headers, params=None):
        return self._request("GET", "/api/case-reviews", headers=headers, params=params)

    def submit_case_review(self, review_id, headers, payload=None):
        return self._request(
            "POST", f"/api/case-reviews/{review_id}/submit", payload or {}, headers
        )

    def accept_case_review(self, review_id, headers, payload=None):
        return self._request(
            "POST", f"/api/case-reviews/{review_id}/accept", payload or {}, headers
        )

    def reopen_case_review(self, review_id, headers, payload=None):
        return self._request(
            "POST", f"/api/case-reviews/{review_id}/reopen", payload or {}, headers
        )

    # --- ReplenishmentOrder ---
    def get_replenishment_order(self, order_id, headers):
        return self._request(
            "GET", f"/api/replenishment-orders/{order_id}", headers=headers
        )

    def list_replenishment_orders(self, headers, params=None):
        return self._request(
            "GET", "/api/replenishment-orders", headers=headers, params=params
        )

    def receive_replenishment_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/api/replenishment-orders/{order_id}/receive", payload, headers
        )

    def cancel_replenishment_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"/api/replenishment-orders/{order_id}/cancel",
            payload or {}, headers,
        )


api_client = ApiClient()
