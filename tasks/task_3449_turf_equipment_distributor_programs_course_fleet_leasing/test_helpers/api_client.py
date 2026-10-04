"""API client: one method per endpoint defined in the PRD (§4 endpoint table).

The logical clock endpoint lives at /turf/_clock/set_current_utc and the
season rollover at /turf/admin/run_season_rollover — both under the /turf
prefix, as given in PRD §4. Lease transitions carry the OCC input
expected_lease_version and claim transitions carry expected_claim_version
(PRD §2.7).
"""
from prd_bench_local_runner.testing import GenericApiClient

from .constants import CLOCK_DEFAULT_ISO


class ApiClient(GenericApiClient):
    def __init__(self, base_url=None):
        super().__init__(base_url)
        # Client-side mirror of the last clock value reported by the server;
        # the startup default is fixed by the PRD.
        self._current_utc = CLOCK_DEFAULT_ISO

    # -- Distributors --------------------------------------------------------
    def create_distributor(self, payload, headers):
        return self._request("POST", "/turf/distributors", payload, headers)

    def get_distributor(self, distributor_id, headers):
        return self._request("GET", f"/turf/distributors/{distributor_id}", headers=headers)

    def run_compliance_review(self, distributor_id, headers):
        return self._request(
            "POST", f"/turf/distributors/{distributor_id}/compliance_review", headers=headers
        )

    # -- Technicians ----------------------------------------------------------
    def create_technician(self, payload, headers):
        return self._request("POST", "/turf/technicians", payload, headers)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/turf/technicians/{technician_id}", headers=headers)

    def list_technicians(self, headers, params=None):
        return self._request("GET", "/turf/technicians", headers=headers, params=params)

    def certify_technician(self, technician_id, payload, headers):
        return self._request(
            "POST", f"/turf/technicians/{technician_id}/certify", payload, headers
        )

    # -- Golf courses ----------------------------------------------------------
    def create_course(self, payload, headers):
        return self._request("POST", "/turf/courses", payload, headers)

    def get_course(self, course_id, headers):
        return self._request("GET", f"/turf/courses/{course_id}", headers=headers)

    def list_courses(self, headers, params=None):
        return self._request("GET", "/turf/courses", headers=headers, params=params)

    # -- Equipment models ------------------------------------------------------
    def create_model(self, payload, headers):
        return self._request("POST", "/turf/models", payload, headers)

    # -- Parts -----------------------------------------------------------------
    def create_part(self, payload, headers):
        return self._request("POST", "/turf/parts", payload, headers)

    def get_part(self, part_id, headers):
        return self._request("GET", f"/turf/parts/{part_id}", headers=headers)

    def list_parts(self, headers, params=None):
        return self._request("GET", "/turf/parts", headers=headers, params=params)

    def transition_part(self, part_id, to, headers, successor_part_id=None):
        payload = {"to": to}
        if successor_part_id is not None:
            payload["successor_part_id"] = successor_part_id
        return self._request("POST", f"/turf/parts/{part_id}/transition", payload, headers)

    # -- Parts orders -----------------------------------------------------------
    def create_parts_order(self, payload, headers):
        return self._request("POST", "/turf/parts-orders", payload, headers)

    def get_parts_order(self, order_id, headers):
        return self._request("GET", f"/turf/parts-orders/{order_id}", headers=headers)

    def list_parts_orders(self, headers, params=None):
        return self._request("GET", "/turf/parts-orders", headers=headers, params=params)

    def transition_parts_order(self, order_id, to, headers, received_lines=None):
        payload = {"to": to}
        if received_lines is not None:
            payload["received_lines"] = received_lines
        return self._request(
            "POST", f"/turf/parts-orders/{order_id}/transition", payload, headers
        )

    # -- Fleet leases -----------------------------------------------------------
    def create_lease(self, payload, headers):
        return self._request("POST", "/turf/leases", payload, headers)

    def get_lease(self, lease_id, headers):
        return self._request("GET", f"/turf/leases/{lease_id}", headers=headers)

    def list_leases(self, headers, params=None):
        return self._request("GET", "/turf/leases", headers=headers, params=params)

    def transition_lease(self, lease_id, to, expected_lease_version, headers):
        """OCC-guarded lease transition (PRD §2.7): expected_lease_version is
        a non-optional input holding the client's last observed version."""
        payload = {"to": to, "expected_lease_version": expected_lease_version}
        return self._request("POST", f"/turf/leases/{lease_id}/transition", payload, headers)

    # -- Lease units -------------------------------------------------------------
    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/turf/units/{unit_id}", headers=headers)

    def list_units(self, headers, params=None):
        return self._request("GET", "/turf/units", headers=headers, params=params)

    def transition_unit(
        self,
        unit_id,
        to,
        headers,
        serial_number=None,
        hours_used=None,
        condition_grade=None,
    ):
        payload = {"to": to}
        if serial_number is not None:
            payload["serial_number"] = serial_number
        if hours_used is not None:
            payload["hours_used"] = hours_used
        if condition_grade is not None:
            payload["condition_grade"] = condition_grade
        return self._request("POST", f"/turf/units/{unit_id}/transition", payload, headers)

    # -- Trade-in appraisals ------------------------------------------------------
    def create_appraisal(self, payload, headers):
        return self._request("POST", "/turf/appraisals", payload, headers)

    def get_appraisal(self, appraisal_id, headers):
        return self._request("GET", f"/turf/appraisals/{appraisal_id}", headers=headers)

    def list_appraisals(self, headers, params=None):
        return self._request("GET", "/turf/appraisals", headers=headers, params=params)

    def transition_appraisal(
        self, appraisal_id, to, headers, hours=None, condition_grade=None, policy=None
    ):
        payload = {"to": to}
        if hours is not None:
            payload["hours"] = hours
        if condition_grade is not None:
            payload["condition_grade"] = condition_grade
        if policy is not None:
            payload["policy"] = policy
        return self._request(
            "POST", f"/turf/appraisals/{appraisal_id}/transition", payload, headers
        )

    # -- Warranty claims -----------------------------------------------------------
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/turf/warranty-claims", payload, headers)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/turf/warranty-claims/{claim_id}", headers=headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/turf/warranty-claims", headers=headers, params=params)

    def transition_warranty_claim(
        self, claim_id, to, expected_claim_version, headers, approved_labor_hours=None
    ):
        """OCC-guarded claim transition (PRD §2.7): expected_claim_version is
        a non-optional input holding the client's last observed version."""
        payload = {"to": to, "expected_claim_version": expected_claim_version}
        if approved_labor_hours is not None:
            payload["approved_labor_hours"] = approved_labor_hours
        return self._request(
            "POST", f"/turf/warranty-claims/{claim_id}/transition", payload, headers
        )

    # -- Irrigation projects ---------------------------------------------------------
    def create_irrigation_project(self, payload, headers):
        return self._request("POST", "/turf/irrigation-projects", payload, headers)

    def get_irrigation_project(self, project_id, headers):
        return self._request(
            "GET", f"/turf/irrigation-projects/{project_id}", headers=headers
        )

    def list_irrigation_projects(self, headers, params=None):
        return self._request(
            "GET", "/turf/irrigation-projects", headers=headers, params=params
        )

    def transition_irrigation_project(
        self,
        project_id,
        to,
        headers,
        controller_model_id=None,
        install_window_start=None,
        install_window_end=None,
        controller_program_version=None,
    ):
        payload = {"to": to}
        if controller_model_id is not None:
            payload["controller_model_id"] = controller_model_id
        if install_window_start is not None:
            payload["install_window_start"] = install_window_start
        if install_window_end is not None:
            payload["install_window_end"] = install_window_end
        if controller_program_version is not None:
            payload["controller_program_version"] = controller_program_version
        return self._request(
            "POST", f"/turf/irrigation-projects/{project_id}/transition", payload, headers
        )

    # -- Logical clock and season rollover (PRD §2.5) --------------------------------
    def set_current_utc(self, to_iso8601, headers):
        """Set the logical clock; the response reports the resulting current_utc."""
        resp = self._request(
            "POST", "/turf/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )
        try:
            body = resp.json()
            if resp.status_code == 200 and isinstance(body, dict):
                reported = (body.get("data") or {}).get("current_utc")
                if reported:
                    self._current_utc = reported
        except ValueError:
            pass
        return resp

    @property
    def current_utc(self):
        """Last clock value reported by the server (startup default per PRD)."""
        return self._current_utc

    def run_season_rollover(self, headers):
        return self._request("POST", "/turf/admin/run_season_rollover", headers=headers)


api_client = ApiClient()
