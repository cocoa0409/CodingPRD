"""HTTP client for the Military Transition Internship API.

One method per endpoint declared in PRD §4. Every method returns the raw
``requests.Response`` so tests can assert on status codes as well as bodies.
All routes live under the ``/skillbridge`` prefix.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for every route the contract declares."""

    # ── Logical clock ─────────────────────────────────────────────────────

    def set_clock(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", "/skillbridge/_clock/set_current_utc", payload, headers)

    # ── Installations ─────────────────────────────────────────────────────

    def create_installation(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", "/skillbridge/installations", payload, headers)

    # ── Service members ───────────────────────────────────────────────────

    def create_service_member(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", "/skillbridge/service-members", payload, headers)

    def list_service_members(self, headers: Optional[Dict[str, str]], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/skillbridge/service-members", headers=headers, params=params)

    def get_service_member(self, member_id: str, headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("GET", f"/skillbridge/service-members/{member_id}", headers=headers)

    def patch_service_member(self, member_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("PATCH", f"/skillbridge/service-members/{member_id}", payload, headers)

    def tap_advance(self, member_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", f"/skillbridge/service-members/{member_id}/tap-advance", payload, headers)

    # ── Internship applications ───────────────────────────────────────────

    def create_application(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", "/skillbridge/internship-applications", payload, headers)

    def list_applications(self, headers: Optional[Dict[str, str]], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/skillbridge/internship-applications", headers=headers, params=params)

    def get_application(self, application_id: str, headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("GET", f"/skillbridge/internship-applications/{application_id}", headers=headers)

    def commander_decision(self, application_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", f"/skillbridge/internship-applications/{application_id}/commander-decision", payload, headers)

    def appeal_application(self, application_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", f"/skillbridge/internship-applications/{application_id}/appeal", payload, headers)

    def adjudicate_appeal(self, application_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", f"/skillbridge/internship-applications/{application_id}/adjudicate-appeal", payload, headers)

    # ── Employers ─────────────────────────────────────────────────────────

    def create_employer(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", "/skillbridge/employers", payload, headers)

    def get_employer(self, employer_id: str, headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("GET", f"/skillbridge/employers/{employer_id}", headers=headers)

    def authorize_employer(self, employer_id: str, headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", f"/skillbridge/employers/{employer_id}/authorize", {}, headers)

    def periodic_review(self, employer_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", f"/skillbridge/employers/{employer_id}/periodic-review", payload, headers)

    def list_employer_audits(self, employer_id: str, headers: Optional[Dict[str, str]], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/skillbridge/employers/{employer_id}/compliance-audits", headers=headers, params=params)

    def get_hiring_rate(self, employer_id: str, headers: Optional[Dict[str, str]], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/skillbridge/employers/{employer_id}/hiring-rate", headers=headers, params=params)

    # ── Employer openings ─────────────────────────────────────────────────

    def create_opening(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", "/skillbridge/employer-openings", payload, headers)

    def list_openings(self, headers: Optional[Dict[str, str]], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/skillbridge/employer-openings", headers=headers, params=params)

    def get_opening(self, opening_id: str, headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("GET", f"/skillbridge/employer-openings/{opening_id}", headers=headers)

    def close_opening(self, opening_id: str, headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", f"/skillbridge/employer-openings/{opening_id}/close", {}, headers)

    # ── Internship matches ────────────────────────────────────────────────

    def create_match(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", "/skillbridge/internship-matches", payload, headers)

    def list_matches(self, headers: Optional[Dict[str, str]], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/skillbridge/internship-matches", headers=headers, params=params)

    def get_match(self, match_id: str, headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("GET", f"/skillbridge/internship-matches/{match_id}", headers=headers)

    def installation_decision(self, match_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", f"/skillbridge/internship-matches/{match_id}/installation-decision", payload, headers)

    def submit_plan(self, match_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", f"/skillbridge/internship-matches/{match_id}/submit-plan", payload, headers)

    def review_plan(self, match_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", f"/skillbridge/internship-matches/{match_id}/review-plan", payload, headers)

    def terminate_match(self, match_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", f"/skillbridge/internship-matches/{match_id}/terminate", payload, headers)

    def complete_match(self, match_id: str, headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", f"/skillbridge/internship-matches/{match_id}/complete", {}, headers)

    def list_supervision_reports(self, match_id: str, headers: Optional[Dict[str, str]], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/skillbridge/internship-matches/{match_id}/supervision-reports", headers=headers, params=params)

    def list_wage_records(self, match_id: str, headers: Optional[Dict[str, str]], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/skillbridge/internship-matches/{match_id}/wage-records", headers=headers, params=params)

    def list_conversion_records(self, match_id: str, headers: Optional[Dict[str, str]], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/skillbridge/internship-matches/{match_id}/conversion-records", headers=headers, params=params)

    # ── Child records ─────────────────────────────────────────────────────

    def create_supervision_report(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", "/skillbridge/supervision-reports", payload, headers)

    def create_wage_record(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", "/skillbridge/wage-records", payload, headers)

    def create_audit(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", "/skillbridge/compliance-audits", payload, headers)

    def close_audit(self, audit_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", f"/skillbridge/compliance-audits/{audit_id}/close", payload, headers)

    def create_conversion_record(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", "/skillbridge/conversion-records", payload, headers)


api_client = ApiClient()
