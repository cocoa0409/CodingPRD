"""API client: one method per endpoint defined in the PRD (mounted under /vdr)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Volunteers ---
    def create_volunteer(self, payload, headers):
        return self._request("POST", "/vdr/volunteers", payload, headers)

    def get_volunteer(self, volunteer_id, headers):
        return self._request("GET", f"/vdr/volunteers/{volunteer_id}", headers=headers)

    def patch_volunteer(self, volunteer_id, payload, headers):
        return self._request("PATCH", f"/vdr/volunteers/{volunteer_id}", payload, headers)

    # --- Certifications ---
    def create_certification(self, volunteer_id, payload, headers):
        return self._request("POST", f"/vdr/volunteers/{volunteer_id}/certifications", payload, headers)

    def list_certifications(self, headers, params=None):
        return self._request("GET", "/vdr/certifications", headers=headers, params=params)

    def get_certification(self, certification_id, headers):
        return self._request("GET", f"/vdr/certifications/{certification_id}", headers=headers)

    def patch_certification(self, certification_id, payload, headers):
        return self._request("PATCH", f"/vdr/certifications/{certification_id}", payload, headers)

    # --- Incidents ---
    def create_incident(self, payload, headers):
        return self._request("POST", "/vdr/incidents", payload, headers)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/vdr/incidents/{incident_id}", headers=headers)

    def patch_incident(self, incident_id, payload, headers):
        return self._request("PATCH", f"/vdr/incidents/{incident_id}", payload, headers)

    # --- Operations ---
    def create_operation(self, incident_id, payload, headers):
        return self._request("POST", f"/vdr/incidents/{incident_id}/operations", payload, headers)

    def list_operations(self, headers, params=None):
        return self._request("GET", "/vdr/operations", headers=headers, params=params)

    def get_operation(self, operation_id, headers):
        return self._request("GET", f"/vdr/operations/{operation_id}", headers=headers)

    def patch_operation(self, operation_id, payload, headers):
        return self._request("PATCH", f"/vdr/operations/{operation_id}", payload, headers)

    def retype_operation(self, operation_id, payload, headers):
        return self._request("POST", f"/vdr/operations/{operation_id}/retype", payload, headers)

    # --- Deployments ---
    def offer_deployment(self, operation_id, payload, headers):
        return self._request("POST", f"/vdr/operations/{operation_id}/deployments", payload, headers)

    def list_deployments(self, headers, params=None):
        return self._request("GET", "/vdr/deployments", headers=headers, params=params)

    def get_deployment(self, deployment_id, headers):
        return self._request("GET", f"/vdr/deployments/{deployment_id}", headers=headers)

    def patch_deployment(self, deployment_id, payload, headers):
        return self._request("PATCH", f"/vdr/deployments/{deployment_id}", payload, headers)

    # --- FOB sites ---
    def create_fob_site(self, operation_id, payload, headers):
        return self._request("POST", f"/vdr/operations/{operation_id}/fob-sites", payload, headers)

    def list_fob_sites(self, operation_id, headers):
        return self._request("GET", f"/vdr/operations/{operation_id}/fob-sites", headers=headers)

    # --- Duty shifts ---
    def create_duty_shift(self, operation_id, payload, headers):
        return self._request("POST", f"/vdr/operations/{operation_id}/duty-shifts", payload, headers)

    def list_duty_shifts(self, headers, params=None):
        return self._request("GET", "/vdr/duty-shifts", headers=headers, params=params)

    def get_duty_shift(self, duty_shift_id, headers):
        return self._request("GET", f"/vdr/duty-shifts/{duty_shift_id}", headers=headers)

    # --- Work orders ---
    def create_work_order(self, incident_id, payload, headers):
        return self._request("POST", f"/vdr/incidents/{incident_id}/work-orders", payload, headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/vdr/work-orders", headers=headers, params=params)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/vdr/work-orders/{work_order_id}", headers=headers)

    def triage_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/vdr/work-orders/{work_order_id}/triage", payload, headers)

    def patch_work_order(self, work_order_id, payload, headers):
        return self._request("PATCH", f"/vdr/work-orders/{work_order_id}", payload, headers)

    # --- Partner agencies ---
    def create_partner(self, payload, headers):
        return self._request("POST", "/vdr/partners", payload, headers)

    # --- Training ---
    def create_training_course(self, payload, headers):
        return self._request("POST", "/vdr/training-courses", payload, headers)

    def get_training_course(self, course_id, headers):
        return self._request("GET", f"/vdr/training-courses/{course_id}", headers=headers)

    def create_enrollment(self, course_id, payload, headers):
        return self._request("POST", f"/vdr/training-courses/{course_id}/enrollments", payload, headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/vdr/training-enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/vdr/training-enrollments/{enrollment_id}", headers=headers)

    def patch_enrollment(self, enrollment_id, payload, headers):
        return self._request("PATCH", f"/vdr/training-enrollments/{enrollment_id}", payload, headers)

    # --- Wellness ---
    def list_wellness_checks(self, deployment_id, headers):
        return self._request("GET", f"/vdr/deployments/{deployment_id}/wellness-checks", headers=headers)

    def patch_wellness_check(self, wellness_check_id, payload, headers):
        return self._request("PATCH", f"/vdr/wellness-checks/{wellness_check_id}", payload, headers)

    # --- Test-driving endpoints ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/vdr/_clock/set_current_utc", payload, headers)

    def run_ops(self, headers):
        return self._request("POST", "/vdr/_ops/run", {}, headers)


api_client = ApiClient()
