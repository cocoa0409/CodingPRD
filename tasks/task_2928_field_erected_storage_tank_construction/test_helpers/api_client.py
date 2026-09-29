"""Typed HTTP client: one method per endpoint of the PRD's endpoint reference.

Every method returns the raw ``requests.Response`` so tests can assert on the
status code as well as the envelope.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .types import Headers, Json


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Reduce an ISO-8601 UTC instant to a fixed-width canonical spelling.

    The PRD requires timestamps "with exactly three fractional-second digits",
    but the literals the API is compared against are frequently written without
    a fractional part. Both spellings denote the same instant, so instant
    comparisons run through this canonicaliser rather than raw string equality.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    if "+" in text[10:]:
        text = text[: text.index("+", 10)]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = (frac + "000")[:3]
        if frac == "000":
            return head + "Z"
        return f"{head}.{frac}Z"
    return text + "Z"


class ApiClient(GenericApiClient):
    """One method per endpoint listed in the PRD's API Endpoint Reference."""

    # --- Logical clock -------------------------------------------------
    def set_clock(self, to_iso8601: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def set_clock_raw(self, payload: Any, headers: Headers) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Tanks ---------------------------------------------------------
    def create_tank(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/tanks", payload, headers)

    def list_tanks(
        self, headers: Headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/tanks", params or {}, headers)

    def get_tank(self, tank_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/tanks/{tank_id}", None, headers)

    def get_tank_summary(self, tank_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/tanks/{tank_id}/summary", None, headers)

    def phase_transition(
        self, tank_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/tanks/{tank_id}/phase-transitions", payload, headers
        )

    # --- Foundation packages -------------------------------------------
    def create_foundation_package(
        self, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/foundation-packages", payload, headers)

    def list_foundation_packages(
        self, headers: Headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/foundation-packages", params or {}, headers)

    def get_foundation_package(
        self, foundation_package_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"/foundation-packages/{foundation_package_id}", None, headers
        )

    def foundation_acceptance(
        self, foundation_package_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/foundation-packages/{foundation_package_id}/acceptance",
            payload,
            headers,
        )

    # --- Settlement surveys --------------------------------------------
    def create_settlement_survey(
        self, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/settlement-surveys", payload, headers)

    def list_settlement_surveys(
        self, headers: Headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/settlement-surveys", params or {}, headers)

    def get_settlement_survey(
        self, settlement_survey_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"/settlement-surveys/{settlement_survey_id}", None, headers
        )

    # --- Plate lots ----------------------------------------------------
    def create_plate_lot(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/plate-lots", payload, headers)

    def list_plate_lots(
        self, headers: Headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/plate-lots", params or {}, headers)

    def get_plate_lot(self, plate_lot_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/plate-lots/{plate_lot_id}", None, headers)

    def plate_lot_status_transition(
        self, plate_lot_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/plate-lots/{plate_lot_id}/status-transitions", payload, headers
        )

    def plate_lot_allocation(
        self, plate_lot_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/plate-lots/{plate_lot_id}/allocations", payload, headers
        )

    # --- Shell courses -------------------------------------------------
    def create_shell_course(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/shell-courses", payload, headers)

    def list_shell_courses(
        self, headers: Headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/shell-courses", params or {}, headers)

    def get_shell_course(
        self, shell_course_id: str, headers: Headers
    ) -> requests.Response:
        return self._request("GET", f"/shell-courses/{shell_course_id}", None, headers)

    def allocation_release(
        self, shell_course_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/shell-courses/{shell_course_id}/allocation-release", payload, headers
        )

    def fitup(
        self, shell_course_id: str, headers: Headers, payload: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/shell-courses/{shell_course_id}/fitup", payload or {}, headers
        )

    # --- Welders -------------------------------------------------------
    def create_welder(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/welders", payload, headers)

    def list_welders(
        self, headers: Headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/welders", params or {}, headers)

    def get_welder(self, welder_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/welders/{welder_id}", None, headers)

    def welder_qualification_action(
        self, welder_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/welders/{welder_id}/qualification-actions", payload, headers
        )

    # --- Weld seams ----------------------------------------------------
    def create_weld_seam(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/weld-seams", payload, headers)

    def list_weld_seams(
        self, headers: Headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/weld-seams", params or {}, headers)

    def get_weld_seam(self, weld_seam_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/weld-seams/{weld_seam_id}", None, headers)

    def weld_log(
        self, weld_seam_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/weld-seams/{weld_seam_id}/weld-log", payload, headers
        )

    def repair_start(
        self, weld_seam_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/weld-seams/{weld_seam_id}/repair-start", payload, headers
        )

    # --- Examination reports -------------------------------------------
    def create_nde_report(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/nde-reports", payload, headers)

    def list_nde_reports(
        self, headers: Headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/nde-reports", params or {}, headers)

    def get_nde_report(self, nde_report_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/nde-reports/{nde_report_id}", None, headers)

    def nde_result(
        self, nde_report_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/nde-reports/{nde_report_id}/result", payload, headers
        )

    def nde_void(
        self, nde_report_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/nde-reports/{nde_report_id}/void", payload, headers
        )

    # --- Water sources -------------------------------------------------
    def create_water_source(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/water-sources", payload, headers)

    def list_water_sources(
        self, headers: Headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/water-sources", params or {}, headers)

    def get_water_source(
        self, water_source_id: str, headers: Headers
    ) -> requests.Response:
        return self._request("GET", f"/water-sources/{water_source_id}", None, headers)

    # --- Hydrostatic test plans ----------------------------------------
    def create_hydrotest_plan(
        self, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/hydrotest-plans", payload, headers)

    def list_hydrotest_plans(
        self, headers: Headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/hydrotest-plans", params or {}, headers)

    def get_hydrotest_plan(
        self, hydrotest_plan_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"/hydrotest-plans/{hydrotest_plan_id}", None, headers
        )

    def plan_approval(
        self, hydrotest_plan_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/hydrotest-plans/{hydrotest_plan_id}/approval", payload, headers
        )

    def fill_advance(
        self, hydrotest_plan_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/hydrotest-plans/{hydrotest_plan_id}/fill-advance",
            payload,
            headers,
        )

    def plan_completion(
        self, hydrotest_plan_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/hydrotest-plans/{hydrotest_plan_id}/completion", payload, headers
        )

    # --- Water withdrawals ---------------------------------------------
    def create_water_withdrawal(
        self, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/water-withdrawals", payload, headers)

    def list_water_withdrawals(
        self, headers: Headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/water-withdrawals", params or {}, headers)

    def get_water_withdrawal(
        self, water_withdrawal_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"/water-withdrawals/{water_withdrawal_id}", None, headers
        )

    def withdrawal_cancellation(
        self, water_withdrawal_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/water-withdrawals/{water_withdrawal_id}/cancellation",
            payload,
            headers,
        )

    # --- Coating applications ------------------------------------------
    def create_coating_application(
        self, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/coating-applications", payload, headers)

    def list_coating_applications(
        self, headers: Headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/coating-applications", params or {}, headers)

    def get_coating_application(
        self, coating_application_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"/coating-applications/{coating_application_id}", None, headers
        )

    def surface_prep(
        self, coating_application_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/coating-applications/{coating_application_id}/surface-prep",
            payload,
            headers,
        )

    def dft_readings(
        self, coating_application_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/coating-applications/{coating_application_id}/dft-readings",
            payload,
            headers,
        )

    def holiday_test(
        self, coating_application_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/coating-applications/{coating_application_id}/holiday-test",
            payload,
            headers,
        )

    # --- Appurtenances -------------------------------------------------
    def create_appurtenance(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/appurtenances", payload, headers)

    def list_appurtenances(
        self, headers: Headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/appurtenances", params or {}, headers)

    def get_appurtenance(
        self, appurtenance_id: str, headers: Headers
    ) -> requests.Response:
        return self._request("GET", f"/appurtenances/{appurtenance_id}", None, headers)

    def appurtenance_installation(
        self, appurtenance_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/appurtenances/{appurtenance_id}/installation", payload, headers
        )

    # --- Commissioning packages ----------------------------------------
    def create_commissioning_package(
        self, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/commissioning-packages", payload, headers)

    def list_commissioning_packages(
        self, headers: Headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/commissioning-packages", params or {}, headers)

    def get_commissioning_package(
        self, commissioning_package_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"/commissioning-packages/{commissioning_package_id}", None, headers
        )

    def add_commissioning_document(
        self, commissioning_package_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/commissioning-packages/{commissioning_package_id}/documents",
            payload,
            headers,
        )

    def package_submission(
        self, commissioning_package_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/commissioning-packages/{commissioning_package_id}/submission",
            payload,
            headers,
        )

    def package_review(
        self, commissioning_package_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/commissioning-packages/{commissioning_package_id}/review",
            payload,
            headers,
        )
