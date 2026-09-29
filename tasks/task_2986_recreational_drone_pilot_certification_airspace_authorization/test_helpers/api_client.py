"""Typed HTTP client for the Drone Operations Service.

One method per endpoint declared in the PRD's endpoint table. Every method returns
the raw `requests.Response` so tests can assert status codes as well as bodies.
All paths are mounted under the `/drone-ops` prefix.
"""

from typing import Any, Dict, List, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/drone-ops"


def _clean(payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Drop keys whose value is the sentinel `_OMIT` so callers can omit fields."""
    if payload is None:
        return None
    return {k: v for k, v in payload.items() if v is not _OMIT}


class _Omit:
    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<OMIT>"


_OMIT = _Omit()
OMIT = _OMIT


class ApiClient(GenericApiClient):
    """One method per PRD endpoint."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(self, to_iso8601: Any, headers=None) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/_clock/set_current_utc",
            payload={"to_iso8601": to_iso8601},
            headers=headers,
        )

    def set_clock_raw(self, payload: Dict[str, Any], headers=None) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/_clock/set_current_utc", payload=payload, headers=headers
        )

    # ------------------------------------------------------------------
    # Pilots
    # ------------------------------------------------------------------

    def create_pilot(self, payload: Dict[str, Any], headers=None) -> requests.Response:
        return self._request("POST", f"{BASE}/pilots", payload=_clean(payload), headers=headers)

    def get_pilot(self, pilot_id: str, headers=None) -> requests.Response:
        return self._request("GET", f"{BASE}/pilots/{pilot_id}", headers=headers)

    def list_pilots(self, params: Optional[Dict[str, Any]] = None, headers=None) -> requests.Response:
        return self._request("GET", f"{BASE}/pilots", params=params, headers=headers)

    def suspend_pilot(
        self, pilot_id: str, payload: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/pilots/{pilot_id}/suspend", payload=_clean(payload), headers=headers
        )

    def reinstate_pilot(
        self, pilot_id: str, payload: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/pilots/{pilot_id}/reinstate", payload=_clean(payload), headers=headers
        )

    def revoke_pilot(
        self, pilot_id: str, payload: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/pilots/{pilot_id}/revoke", payload=_clean(payload), headers=headers
        )

    def currency_review(
        self, pilot_id: str, payload: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/pilots/{pilot_id}/currency-review",
            payload=_clean(payload),
            headers=headers,
        )

    def get_currency_projection(
        self, pilot_id: str, params: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/pilots/{pilot_id}/currency-projection", params=params, headers=headers
        )

    def get_flight_summary(
        self, pilot_id: str, params: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/pilots/{pilot_id}/flight-summary", params=params, headers=headers
        )

    # ------------------------------------------------------------------
    # Knowledge tests and certifications
    # ------------------------------------------------------------------

    def schedule_knowledge_test(
        self, pilot_id: str, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/pilots/{pilot_id}/knowledge-tests",
            payload=_clean(payload),
            headers=headers,
        )

    def get_knowledge_test(self, test_id: str, headers=None) -> requests.Response:
        return self._request("GET", f"{BASE}/knowledge-tests/{test_id}", headers=headers)

    def list_knowledge_tests(
        self, params: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/knowledge-tests", params=params, headers=headers)

    def grade_knowledge_test(
        self, test_id: str, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/knowledge-tests/{test_id}/grade",
            payload=_clean(payload),
            headers=headers,
        )

    def get_certification(self, certification_id: str, headers=None) -> requests.Response:
        return self._request("GET", f"{BASE}/certifications/{certification_id}", headers=headers)

    def list_certifications(
        self, params: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/certifications", params=params, headers=headers)

    # ------------------------------------------------------------------
    # Airframes and remote-ID modules
    # ------------------------------------------------------------------

    def create_aircraft(self, payload: Dict[str, Any], headers=None) -> requests.Response:
        return self._request("POST", f"{BASE}/aircraft", payload=_clean(payload), headers=headers)

    def get_aircraft(self, aircraft_id: str, headers=None) -> requests.Response:
        return self._request("GET", f"{BASE}/aircraft/{aircraft_id}", headers=headers)

    def list_aircraft(
        self, params: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/aircraft", params=params, headers=headers)

    def register_aircraft(
        self, aircraft_id: str, payload: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/aircraft/{aircraft_id}/register", payload=_clean(payload), headers=headers
        )

    def ground_aircraft(
        self, aircraft_id: str, payload: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/aircraft/{aircraft_id}/ground", payload=_clean(payload), headers=headers
        )

    def return_aircraft_to_service(
        self, aircraft_id: str, payload: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/aircraft/{aircraft_id}/return-to-service",
            payload=_clean(payload),
            headers=headers,
        )

    def create_remote_id_module(
        self, aircraft_id: str, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/aircraft/{aircraft_id}/remote-id-modules",
            payload=_clean(payload),
            headers=headers,
        )

    def get_remote_id_module(self, module_id: str, headers=None) -> requests.Response:
        return self._request("GET", f"{BASE}/remote-id-modules/{module_id}", headers=headers)

    def list_remote_id_modules(
        self, params: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/remote-id-modules", params=params, headers=headers)

    def submit_module_verification(
        self, module_id: str, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/remote-id-modules/{module_id}/submit-verification",
            payload=_clean(payload),
            headers=headers,
        )

    def verify_remote_id_module(
        self, module_id: str, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/remote-id-modules/{module_id}/verify",
            payload=_clean(payload),
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Airspace zones and temporary flight restrictions
    # ------------------------------------------------------------------

    def create_zone(self, payload: Dict[str, Any], headers=None) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/airspace-zones", payload=_clean(payload), headers=headers
        )

    def get_zone(self, zone_id: str, headers=None) -> requests.Response:
        return self._request("GET", f"{BASE}/airspace-zones/{zone_id}", headers=headers)

    def list_zones(self, params: Optional[Dict[str, Any]] = None, headers=None) -> requests.Response:
        return self._request("GET", f"{BASE}/airspace-zones", params=params, headers=headers)

    def create_tfr(self, payload: Dict[str, Any], headers=None) -> requests.Response:
        return self._request("POST", f"{BASE}/tfrs", payload=_clean(payload), headers=headers)

    def get_tfr(self, tfr_id: str, headers=None) -> requests.Response:
        return self._request("GET", f"{BASE}/tfrs/{tfr_id}", headers=headers)

    def list_tfrs(self, params: Optional[Dict[str, Any]] = None, headers=None) -> requests.Response:
        return self._request("GET", f"{BASE}/tfrs", params=params, headers=headers)

    def lift_tfr(
        self, tfr_id: str, payload: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/tfrs/{tfr_id}/lift", payload=_clean(payload), headers=headers
        )

    # ------------------------------------------------------------------
    # Airspace authorizations
    # ------------------------------------------------------------------

    def create_authorization(self, payload: Dict[str, Any], headers=None) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/airspace-authorizations", payload=_clean(payload), headers=headers
        )

    def get_authorization(self, authorization_id: str, headers=None) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/airspace-authorizations/{authorization_id}", headers=headers
        )

    def list_authorizations(
        self, params: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/airspace-authorizations", params=params, headers=headers
        )

    def decide_authorization(
        self, authorization_id: str, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/airspace-authorizations/{authorization_id}/decide",
            payload=_clean(payload),
            headers=headers,
        )

    def revoke_authorization(
        self, authorization_id: str, payload: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/airspace-authorizations/{authorization_id}/revoke",
            payload=_clean(payload),
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Waivers and safety cases
    # ------------------------------------------------------------------

    def create_waiver(self, payload: Dict[str, Any], headers=None) -> requests.Response:
        return self._request("POST", f"{BASE}/waivers", payload=_clean(payload), headers=headers)

    def get_waiver(self, waiver_id: str, headers=None) -> requests.Response:
        return self._request("GET", f"{BASE}/waivers/{waiver_id}", headers=headers)

    def list_waivers(
        self, params: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/waivers", params=params, headers=headers)

    def create_safety_case(
        self, waiver_id: str, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/waivers/{waiver_id}/safety-cases",
            payload=_clean(payload),
            headers=headers,
        )

    def get_safety_case(self, safety_case_id: str, headers=None) -> requests.Response:
        return self._request("GET", f"{BASE}/safety-cases/{safety_case_id}", headers=headers)

    def list_safety_cases(
        self, params: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/safety-cases", params=params, headers=headers)

    def submit_waiver(
        self, waiver_id: str, payload: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/waivers/{waiver_id}/submit", payload=_clean(payload), headers=headers
        )

    def begin_waiver_review(
        self, waiver_id: str, payload: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/waivers/{waiver_id}/begin-review",
            payload=_clean(payload),
            headers=headers,
        )

    def request_waiver_revision(
        self, waiver_id: str, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/waivers/{waiver_id}/request-revision",
            payload=_clean(payload),
            headers=headers,
        )

    def clear_waiver_safety_case(
        self, waiver_id: str, payload: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/waivers/{waiver_id}/clear-safety-case",
            payload=_clean(payload),
            headers=headers,
        )

    def decide_waiver(
        self, waiver_id: str, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/waivers/{waiver_id}/decide", payload=_clean(payload), headers=headers
        )

    # ------------------------------------------------------------------
    # Insurance policies
    # ------------------------------------------------------------------

    def create_policy(self, payload: Dict[str, Any], headers=None) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/insurance-policies", payload=_clean(payload), headers=headers
        )

    def get_policy(self, policy_id: str, headers=None) -> requests.Response:
        return self._request("GET", f"{BASE}/insurance-policies/{policy_id}", headers=headers)

    def list_policies(
        self, params: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/insurance-policies", params=params, headers=headers)

    def verify_policy(
        self, policy_id: str, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/insurance-policies/{policy_id}/verify",
            payload=_clean(payload),
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Flights
    # ------------------------------------------------------------------

    def create_flight(self, payload: Dict[str, Any], headers=None) -> requests.Response:
        return self._request("POST", f"{BASE}/flights", payload=_clean(payload), headers=headers)

    def get_flight(self, flight_id: str, headers=None) -> requests.Response:
        return self._request("GET", f"{BASE}/flights/{flight_id}", headers=headers)

    def list_flights(
        self, params: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/flights", params=params, headers=headers)

    def preflight_check(
        self, flight_id: str, payload: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/flights/{flight_id}/preflight-check",
            payload=_clean(payload),
            headers=headers,
        )

    def list_preflight_checks(
        self, flight_id: str, params: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/flights/{flight_id}/preflight-checks", params=params, headers=headers
        )

    def launch_flight(
        self, flight_id: str, payload: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/flights/{flight_id}/launch", payload=_clean(payload), headers=headers
        )

    def complete_flight(
        self, flight_id: str, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/flights/{flight_id}/complete", payload=_clean(payload), headers=headers
        )

    def cancel_flight(
        self, flight_id: str, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/flights/{flight_id}/cancel", payload=_clean(payload), headers=headers
        )

    # ------------------------------------------------------------------
    # Accident reports
    # ------------------------------------------------------------------

    def create_accident_report(self, payload: Dict[str, Any], headers=None) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/accident-reports", payload=_clean(payload), headers=headers
        )

    def get_accident_report(self, report_id: str, headers=None) -> requests.Response:
        return self._request("GET", f"{BASE}/accident-reports/{report_id}", headers=headers)

    def list_accident_reports(
        self, params: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/accident-reports", params=params, headers=headers)

    def open_investigation(
        self, report_id: str, payload: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/accident-reports/{report_id}/open-investigation",
            payload=_clean(payload),
            headers=headers,
        )

    def require_remediation(
        self, report_id: str, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/accident-reports/{report_id}/require-remediation",
            payload=_clean(payload),
            headers=headers,
        )

    def resume_investigation(
        self, report_id: str, payload: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/accident-reports/{report_id}/resume-investigation",
            payload=_clean(payload),
            headers=headers,
        )

    def close_accident_report(
        self, report_id: str, payload: Dict[str, Any], headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/accident-reports/{report_id}/close",
            payload=_clean(payload),
            headers=headers,
        )

    def withdraw_accident_report(
        self, report_id: str, payload: Optional[Dict[str, Any]] = None, headers=None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/accident-reports/{report_id}/withdraw",
            payload=_clean(payload),
            headers=headers,
        )
