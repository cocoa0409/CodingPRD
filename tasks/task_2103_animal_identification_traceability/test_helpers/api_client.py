"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- Producer ----------------
    def create_producer(self, payload, headers):
        return self._request("POST", "/producers", payload, headers)

    def get_producer(self, producer_id, headers):
        return self._request("GET", f"/producers/{producer_id}", headers=headers)

    def enroll_producer(self, producer_id, headers):
        return self._request("POST", f"/producers/{producer_id}/enroll", {}, headers)

    def list_producer_incentive_awards(self, producer_id, headers, params=None):
        return self._request(
            "GET", f"/producers/{producer_id}/incentive-awards", headers=headers, params=params
        )

    # ---------------- Premises ----------------
    def create_premises(self, payload, headers):
        return self._request("POST", "/premises", payload, headers)

    def get_premises(self, premises_id, headers):
        return self._request("GET", f"/premises/{premises_id}", headers=headers)

    def list_premises(self, headers, params=None):
        return self._request("GET", "/premises", headers=headers, params=params)

    def approve_premises(self, premises_id, headers):
        return self._request("POST", f"/premises/{premises_id}/approve", {}, headers)

    def list_premises_reconciliation_runs(self, premises_id, headers, params=None):
        return self._request(
            "GET", f"/premises/{premises_id}/reconciliation-runs", headers=headers, params=params
        )

    # ---------------- DeviceSupplier ----------------
    def create_device_supplier(self, payload, headers):
        return self._request("POST", "/device-suppliers", payload, headers)

    def get_device_supplier(self, supplier_id, headers):
        return self._request("GET", f"/device-suppliers/{supplier_id}", headers=headers)

    def approve_device_supplier(self, supplier_id, headers):
        return self._request("POST", f"/device-suppliers/{supplier_id}/approve", {}, headers)

    def report_device_defects(self, supplier_id, payload, headers):
        return self._request(
            "POST", f"/device-suppliers/{supplier_id}/defect-reports", payload, headers
        )

    def reinstate_device_supplier(self, supplier_id, payload, headers):
        return self._request(
            "POST", f"/device-suppliers/{supplier_id}/reinstate", payload, headers
        )

    # ---------------- TagLot ----------------
    def create_tag_lot(self, payload, headers):
        return self._request("POST", "/tag-lots", payload, headers)

    def get_tag_lot(self, lot_id, headers):
        return self._request("GET", f"/tag-lots/{lot_id}", headers=headers)

    def list_tag_lots(self, headers, params=None):
        return self._request("GET", "/tag-lots", headers=headers, params=params)

    def void_tag_lot(self, lot_id, headers):
        return self._request("POST", f"/tag-lots/{lot_id}/void", {}, headers)

    def apply_tag(self, lot_id, payload, headers):
        return self._request("POST", f"/tag-lots/{lot_id}/apply-tag", payload, headers)

    # ---------------- Tag ----------------
    def get_tag(self, tag_id, headers):
        return self._request("GET", f"/tags/{tag_id}", headers=headers)

    def list_tags(self, headers, params=None):
        return self._request("GET", "/tags", headers=headers, params=params)

    def replace_tag(self, tag_id, payload, headers):
        return self._request("POST", f"/tags/{tag_id}/replace", payload, headers)

    def retire_tag(self, tag_id, payload, headers):
        return self._request("POST", f"/tags/{tag_id}/retire", payload, headers)

    def void_tag_application(self, tag_id, headers):
        return self._request("POST", f"/tags/{tag_id}/void-application", {}, headers)

    # ---------------- Animal & Sighting ----------------
    def get_animal(self, animal_id, headers):
        return self._request("GET", f"/animals/{animal_id}", headers=headers)

    def list_animals(self, headers, params=None):
        return self._request("GET", "/animals", headers=headers, params=params)

    def get_sighting(self, sighting_id, headers):
        return self._request("GET", f"/sightings/{sighting_id}", headers=headers)

    def list_sightings(self, headers, params=None):
        return self._request("GET", "/sightings", headers=headers, params=params)

    # ---------------- MovementEvent ----------------
    def create_movement_event(self, payload, headers):
        return self._request("POST", "/movement-events", payload, headers)

    def get_movement_event(self, movement_id, headers):
        return self._request("GET", f"/movement-events/{movement_id}", headers=headers)

    def list_movement_events(self, headers, params=None):
        return self._request("GET", "/movement-events", headers=headers, params=params)

    def receive_movement_event(self, movement_id, payload, headers):
        return self._request("POST", f"/movement-events/{movement_id}/receive", payload, headers)

    def dispute_movement_event(self, movement_id, payload, headers):
        return self._request("POST", f"/movement-events/{movement_id}/dispute", payload, headers)

    def correct_movement_event(self, movement_id, payload, headers):
        return self._request("POST", f"/movement-events/{movement_id}/correct", payload, headers)

    def void_movement_event(self, movement_id, headers):
        return self._request("POST", f"/movement-events/{movement_id}/void", {}, headers)

    # ---------------- TraceRequest ----------------
    def create_trace_request(self, payload, headers):
        return self._request("POST", "/trace-requests", payload, headers)

    def get_trace_request(self, trace_id, headers):
        return self._request("GET", f"/trace-requests/{trace_id}", headers=headers)

    def list_trace_requests(self, headers, params=None):
        return self._request("GET", "/trace-requests", headers=headers, params=params)

    def run_trace_request(self, trace_id, headers):
        return self._request("POST", f"/trace-requests/{trace_id}/run", {}, headers)

    def respond_trace_hit(self, trace_id, animal_id, payload, headers):
        return self._request(
            "POST", f"/trace-requests/{trace_id}/hits/{animal_id}/respond", payload, headers
        )

    def close_trace_request(self, trace_id, headers):
        return self._request("POST", f"/trace-requests/{trace_id}/close", {}, headers)

    def cancel_trace_request(self, trace_id, headers):
        return self._request("POST", f"/trace-requests/{trace_id}/cancel", {}, headers)

    # ---------------- HoldOrder ----------------
    def create_hold_order(self, payload, headers):
        return self._request("POST", "/hold-orders", payload, headers)

    def get_hold_order(self, hold_id, headers):
        return self._request("GET", f"/hold-orders/{hold_id}", headers=headers)

    def list_hold_orders(self, headers, params=None):
        return self._request("GET", "/hold-orders", headers=headers, params=params)

    def activate_hold_order(self, hold_id, headers):
        return self._request("POST", f"/hold-orders/{hold_id}/activate", {}, headers)

    def appeal_hold_order(self, hold_id, payload, headers):
        return self._request("POST", f"/hold-orders/{hold_id}/appeal", payload, headers)

    def deny_hold_appeal(self, hold_id, headers):
        return self._request("POST", f"/hold-orders/{hold_id}/deny-appeal", {}, headers)

    def release_hold_order(self, hold_id, headers):
        return self._request("POST", f"/hold-orders/{hold_id}/release", {}, headers)

    # ---------------- ReconciliationRun ----------------
    def create_reconciliation_run(self, payload, headers):
        return self._request("POST", "/reconciliation-runs", payload, headers)

    def submit_reconciliation_run(self, run_id, payload, headers):
        return self._request("POST", f"/reconciliation-runs/{run_id}/submit", payload, headers)

    def approve_reconciliation_run(self, run_id, headers):
        return self._request("POST", f"/reconciliation-runs/{run_id}/approve", {}, headers)

    # ---------------- IncentiveAward ----------------
    def create_incentive_award(self, payload, headers):
        return self._request("POST", "/incentive-awards", payload, headers)

    def pay_incentive_award(self, award_id, headers):
        return self._request("POST", f"/incentive-awards/{award_id}/pay", {}, headers)

    def clawback_incentive_award(self, award_id, headers):
        return self._request("POST", f"/incentive-awards/{award_id}/clawback", {}, headers)

    # ---------------- Programme clock ----------------
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
