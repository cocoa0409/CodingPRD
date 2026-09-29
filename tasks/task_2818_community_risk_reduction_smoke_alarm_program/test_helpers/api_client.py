"""Endpoint surface of the Community Risk Reduction API.

One method per path documented in the PRD's endpoint table, plus the logical
clock control endpoint. Every method returns the raw ``requests.Response`` so
tests can assert on HTTP status codes as well as on the envelope.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_SET_PATH


class CrrApiClient(GenericApiClient):
    """Typed client for the program's 46 documented endpoints."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request(
            "POST", CLOCK_SET_PATH, {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------------
    # Risk zones
    # ------------------------------------------------------------------
    def create_zone(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/zones", payload, headers)

    def list_zones(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{API_PREFIX}/zones", params, headers)

    def get_zone(self, zone_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{API_PREFIX}/zones/{zone_id}", None, headers)

    def create_assessment(
        self, zone_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/zones/{zone_id}/assessments", payload, headers
        )

    def list_assessments(
        self, zone_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/zones/{zone_id}/assessments", params, headers
        )

    def create_fire_incident(
        self, zone_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/zones/{zone_id}/fire-incidents", payload, headers
        )

    def list_fire_incidents(
        self, zone_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/zones/{zone_id}/fire-incidents", params, headers
        )

    def get_outcome_summary(self, zone_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/zones/{zone_id}/outcome-summary", None, headers
        )

    # ------------------------------------------------------------------
    # Households and follow-ups
    # ------------------------------------------------------------------
    def create_household(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/households", payload, headers)

    def list_households(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{API_PREFIX}/households", params, headers)

    def get_household(self, household_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/households/{household_id}", None, headers
        )

    def list_household_follow_ups(
        self, household_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/households/{household_id}/follow-ups",
            params,
            headers,
        )

    def create_follow_up(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/follow-ups", payload, headers)

    # ------------------------------------------------------------------
    # Crews and routes
    # ------------------------------------------------------------------
    def create_crew(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/crews", payload, headers)

    def create_route(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/routes", payload, headers)

    def list_routes(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{API_PREFIX}/routes", params, headers)

    def get_route(self, route_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{API_PREFIX}/routes/{route_id}", None, headers)

    def publish_route(self, route_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/routes/{route_id}/publish", {}, headers
        )

    def close_route(
        self,
        route_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"{API_PREFIX}/routes/{route_id}/close", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Home safety visits
    # ------------------------------------------------------------------
    def create_visit(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/visits", payload, headers)

    def list_visits(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{API_PREFIX}/visits", params, headers)

    def get_visit(self, visit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{API_PREFIX}/visits/{visit_id}", None, headers)

    def reschedule_visit(
        self, visit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/visits/{visit_id}/reschedule", payload, headers
        )

    def cancel_visit(
        self, visit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/visits/{visit_id}/cancel", payload, headers
        )

    def arrive_visit(
        self, visit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/visits/{visit_id}/arrive", payload, headers
        )

    def record_education(
        self, visit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/visits/{visit_id}/education", payload, headers
        )

    def complete_visit(
        self, visit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/visits/{visit_id}/complete", payload, headers
        )

    # ------------------------------------------------------------------
    # Partners, grants and device lots
    # ------------------------------------------------------------------
    def create_partner(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/partners", payload, headers)

    def create_grant(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/grants", payload, headers)

    def list_grants(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{API_PREFIX}/grants", params, headers)

    def get_grant(self, grant_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{API_PREFIX}/grants/{grant_id}", None, headers)

    def activate_grant(self, grant_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/grants/{grant_id}/activate", {}, headers
        )

    def create_device_lot(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/device-lots", payload, headers)

    def list_device_lots(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{API_PREFIX}/device-lots", params, headers)

    def get_device_lot(self, lot_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/device-lots/{lot_id}", None, headers
        )

    # ------------------------------------------------------------------
    # Alarm installations
    # ------------------------------------------------------------------
    def create_installation(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/installations", payload, headers)

    def list_installations(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", f"{API_PREFIX}/installations", params, headers)

    def get_installation(self, installation_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/installations/{installation_id}", None, headers
        )

    def verify_installation(self, installation_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{API_PREFIX}/installations/{installation_id}/verify",
            {},
            headers,
        )

    def void_installation(
        self, installation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/installations/{installation_id}/void",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Escape plans
    # ------------------------------------------------------------------
    def create_escape_plan(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/escape-plans", payload, headers)

    def list_escape_plans(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{API_PREFIX}/escape-plans", params, headers)

    def get_escape_plan(self, plan_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/escape-plans/{plan_id}", None, headers
        )

    def issue_escape_plan(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/escape-plans/{plan_id}/issue", payload, headers
        )

    # ------------------------------------------------------------------
    # Grant reports
    # ------------------------------------------------------------------
    def create_grant_report(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/grant-reports", payload, headers)

    def list_grant_reports(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", f"{API_PREFIX}/grant-reports", params, headers)

    def get_grant_report(self, report_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/grant-reports/{report_id}", None, headers
        )

    def submit_grant_report(
        self, report_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/grant-reports/{report_id}/submit", payload, headers
        )

    def decide_grant_report(
        self, report_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/grant-reports/{report_id}/decision",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Raw escape hatches for header-less / malformed request tests
    # ------------------------------------------------------------------
    def raw_post(
        self,
        path: str,
        payload: Optional[Dict[str, Any]],
        headers: Optional[Dict[str, str]],
    ):
        return self._request("POST", path, payload, headers)

    def raw_get(
        self,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ):
        return self._request("GET", path, params, headers)
