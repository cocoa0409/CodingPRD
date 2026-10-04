"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Platform setup / logical clock / test-driving ────────────────────────
    def set_clock(self, current_utc, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"current_utc": current_utc}, headers)

    def seed_reference(self, headers, payload=None):
        return self._request("POST", "/_scenarios/seed-reference", payload or {}, headers)

    def create_service_center(self, payload, headers):
        return self._request("POST", "/psc/service-centers", payload, headers)

    def get_service_center(self, service_center_id, headers):
        return self._request("GET", f"/psc/service-centers/{service_center_id}", headers=headers)

    def run_ops(self, service_center_id, headers):
        return self._request("POST", "/psc/run-ops",
                             {"service_center_id": service_center_id}, headers)

    # ─── Patients ─────────────────────────────────────────────────────────────
    def create_patient(self, payload, headers):
        return self._request("POST", "/psc/patients", payload, headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/psc/patients", headers=headers, params=params)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/psc/patients/{patient_id}", headers=headers)

    def patch_patient(self, patient_id, payload, headers):
        return self._request("PATCH", f"/psc/patients/{patient_id}", payload, headers)

    # ─── Phlebotomists ────────────────────────────────────────────────────────
    def create_phlebotomist(self, payload, headers):
        return self._request("POST", "/psc/phlebotomists", payload, headers)

    def patch_phlebotomist(self, phlebotomist_id, payload, headers):
        return self._request("PATCH", f"/psc/phlebotomists/{phlebotomist_id}", payload, headers)

    def list_phlebotomists(self, headers, params=None):
        return self._request("GET", "/psc/phlebotomists", headers=headers, params=params)

    def get_phlebotomist(self, phlebotomist_id, headers):
        return self._request("GET", f"/psc/phlebotomists/{phlebotomist_id}", headers=headers)

    # ─── Insurance plans / necessity rules / tube requirements ────────────────
    def create_insurance_plan(self, payload, headers):
        return self._request("POST", "/psc/insurance-plans", payload, headers)

    def list_insurance_plans(self, headers, params=None):
        return self._request("GET", "/psc/insurance-plans", headers=headers, params=params)

    def get_insurance_plan(self, insurance_plan_id, headers):
        return self._request("GET", f"/psc/insurance-plans/{insurance_plan_id}", headers=headers)

    def patch_insurance_plan(self, insurance_plan_id, payload, headers):
        return self._request("PATCH", f"/psc/insurance-plans/{insurance_plan_id}", payload, headers)

    def create_necessity_rule(self, payload, headers):
        return self._request("POST", "/psc/medical-necessity-rules", payload, headers)

    def list_necessity_rules(self, headers, params=None):
        return self._request("GET", "/psc/medical-necessity-rules", headers=headers, params=params)

    def create_tube_requirement(self, payload, headers):
        return self._request("POST", "/psc/tube-requirements", payload, headers)

    def list_tube_requirements(self, headers, params=None):
        return self._request("GET", "/psc/tube-requirements", headers=headers, params=params)

    def transition_tube_requirement(self, tube_requirement_id, payload, headers):
        return self._request("POST", f"/psc/tube-requirements/{tube_requirement_id}/transition",
                             payload, headers)

    def delete_tube_requirement(self, tube_requirement_id, headers):
        return self._request("DELETE", f"/psc/tube-requirements/{tube_requirement_id}",
                             headers=headers)

    # ─── Test orders ──────────────────────────────────────────────────────────
    def create_test_order(self, payload, headers):
        return self._request("POST", "/psc/test-orders", payload, headers)

    def list_test_orders(self, headers, params=None):
        return self._request("GET", "/psc/test-orders", headers=headers, params=params)

    def get_test_order(self, test_order_id, headers):
        return self._request("GET", f"/psc/test-orders/{test_order_id}", headers=headers)

    def get_tube_plan(self, test_order_id, headers):
        return self._request("GET", f"/psc/test-orders/{test_order_id}/tube-plan", headers=headers)

    def necessity_check(self, test_order_id, headers):
        return self._request("POST", f"/psc/test-orders/{test_order_id}/necessity-check",
                             {}, headers)

    def insurance_resolve(self, test_order_id, headers):
        return self._request("POST", f"/psc/test-orders/{test_order_id}/insurance-resolve",
                             {}, headers)

    def schedule_test_order(self, test_order_id, headers):
        return self._request("POST", f"/psc/test-orders/{test_order_id}/schedule", {}, headers)

    def cancel_test_order(self, test_order_id, headers):
        return self._request("POST", f"/psc/test-orders/{test_order_id}/cancel", {}, headers)

    def create_estimate(self, test_order_id, payload, headers):
        return self._request("POST", f"/psc/test-orders/{test_order_id}/estimates",
                             payload, headers)

    def list_order_estimates(self, test_order_id, headers, params=None):
        return self._request("GET", f"/psc/test-orders/{test_order_id}/estimates",
                             headers=headers, params=params)

    def get_estimate(self, estimate_id, headers):
        return self._request("GET", f"/psc/responsibility-estimates/{estimate_id}", headers=headers)

    def list_estimates(self, headers, params=None):
        return self._request("GET", "/psc/responsibility-estimates", headers=headers, params=params)

    # ─── Appointments ─────────────────────────────────────────────────────────
    def create_appointment(self, payload, headers):
        return self._request("POST", "/psc/appointments", payload, headers)

    def create_walk_in(self, payload, headers):
        return self._request("POST", "/psc/appointments/walk-in", payload, headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/psc/appointments", headers=headers, params=params)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/psc/appointments/{appointment_id}", headers=headers)

    def queue_status(self, appointment_id, headers):
        return self._request("GET", f"/psc/appointments/{appointment_id}/queue-status",
                             headers=headers)

    def check_in(self, appointment_id, headers, payload=None):
        return self._request("POST", f"/psc/appointments/{appointment_id}/check-in",
                             payload or {}, headers)

    def call_appointment(self, appointment_id, headers):
        return self._request("POST", f"/psc/appointments/{appointment_id}/call", {}, headers)

    def start_draw(self, appointment_id, headers):
        return self._request("POST", f"/psc/appointments/{appointment_id}/start-draw", {}, headers)

    def finish_draw(self, appointment_id, headers):
        return self._request("POST", f"/psc/appointments/{appointment_id}/finish-draw", {}, headers)

    def reschedule_appointment(self, appointment_id, scheduled_start_utc, headers):
        return self._request("POST", f"/psc/appointments/{appointment_id}/reschedule",
                             {"scheduled_start_utc": scheduled_start_utc}, headers)

    def prepay(self, appointment_id, amount_cents, headers):
        return self._request("POST", f"/psc/appointments/{appointment_id}/prepay",
                             {"amount_cents": amount_cents}, headers)

    # ─── Specimens ────────────────────────────────────────────────────────────
    def create_specimen(self, payload, headers):
        return self._request("POST", "/psc/specimens", payload, headers)

    def list_specimens(self, headers, params=None):
        return self._request("GET", "/psc/specimens", headers=headers, params=params)

    def list_recollection_candidates(self, headers, params=None):
        return self._request("GET", "/psc/specimens/selector", headers=headers, params=params)

    def get_specimen(self, specimen_id, headers):
        return self._request("GET", f"/psc/specimens/{specimen_id}", headers=headers)

    def assign_courier(self, specimen_id, courier_run_id, headers, expected_specimen_version=None):
        payload = {"courier_run_id": courier_run_id}
        if expected_specimen_version is not None:
            payload["expected_specimen_version"] = expected_specimen_version
        return self._request("POST", f"/psc/specimens/{specimen_id}/assign-courier",
                             payload, headers)

    def compromise_specimen(self, specimen_id, compromise_reason, headers):
        return self._request("POST", f"/psc/specimens/{specimen_id}/compromise",
                             {"compromise_reason": compromise_reason}, headers)

    def reject_specimen(self, specimen_id, headers):
        return self._request("POST", f"/psc/specimens/{specimen_id}/reject", {}, headers)

    def recollect_specimen(self, specimen_id, headers):
        return self._request("POST", f"/psc/specimens/{specimen_id}/recollect", {}, headers)

    # ─── Courier runs ─────────────────────────────────────────────────────────
    def create_courier_run(self, payload, headers):
        return self._request("POST", "/psc/courier-runs", payload, headers)

    def list_courier_runs(self, headers, params=None):
        return self._request("GET", "/psc/courier-runs", headers=headers, params=params)

    def list_eligible_courier_runs(self, headers, specimen_id=None):
        params = {"specimen_id": specimen_id} if specimen_id else None
        return self._request("GET", "/psc/courier-runs/eligible", headers=headers, params=params)

    def get_courier_run(self, courier_run_id, headers):
        return self._request("GET", f"/psc/courier-runs/{courier_run_id}", headers=headers)

    def commit_all(self, courier_run_id, headers):
        return self._request("POST", f"/psc/courier-runs/{courier_run_id}/commit-all", {}, headers)

    def dispatch_courier_run(self, courier_run_id, headers):
        return self._request("POST", f"/psc/courier-runs/{courier_run_id}/dispatch", {}, headers)

    def deliver_courier_run(self, courier_run_id, headers):
        return self._request("POST", f"/psc/courier-runs/{courier_run_id}/deliver", {}, headers)

    def cancel_courier_run(self, courier_run_id, headers):
        return self._request("POST", f"/psc/courier-runs/{courier_run_id}/cancel", {}, headers)


api_client = ApiClient()