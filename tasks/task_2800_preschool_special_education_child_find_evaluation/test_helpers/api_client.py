"""API client for the Preschool Child Find API: one method per documented endpoint.

Every endpoint is mounted under ``/child-find`` and requires the ``X-User-ID``
and ``X-User-Role`` headers.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/child-find"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------ children
    def create_child(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/children", payload, headers)

    def get_child(self, child_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/children/{child_id}", headers=headers)

    def list_children(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/children", headers=headers, params=params)

    # ----------------------------------------------------------- community sites
    def create_community_site(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/community-sites", payload, headers)

    def get_community_site(self, site_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/community-sites/{site_id}", headers=headers
        )

    def list_community_sites(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/community-sites", headers=headers, params=params
        )

    # ----------------------------------------------------------------- providers
    def create_provider(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/providers", payload, headers)

    def get_provider(self, provider_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/providers/{provider_id}", headers=headers)

    def list_providers(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/providers", headers=headers, params=params)

    def update_provider(
        self, provider_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"{PREFIX}/providers/{provider_id}", payload, headers
        )

    def get_provider_caseload(self, provider_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/providers/{provider_id}/caseload", headers=headers
        )

    # ---------------------------------------------------------- screening events
    def create_screening_event(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/screening-events", payload, headers)

    def get_screening_event(self, event_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/screening-events/{event_id}", headers=headers
        )

    def list_screening_events(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/screening-events", headers=headers, params=params
        )

    def set_screening_event_status(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/screening-events/{event_id}/status", payload, headers
        )

    def book_screening_slot(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/screening-events/{event_id}/slots", payload, headers
        )

    # ----------------------------------------------------------- screening slots
    def get_screening_slot(self, slot_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/screening-slots/{slot_id}", headers=headers
        )

    def list_screening_slots(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/screening-slots", headers=headers, params=params
        )

    def record_slot_outcome(
        self, slot_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/screening-slots/{slot_id}/outcome", payload, headers
        )

    # ----------------------------------------------------------------- referrals
    def create_referral(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/referrals", payload, headers)

    def get_referral(self, referral_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/referrals", headers=headers, params=params)

    def get_referral_timeline(self, referral_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/referrals/{referral_id}/timeline", headers=headers
        )

    def issue_consent_request(
        self, referral_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/referrals/{referral_id}/consent-requests", payload, headers
        )

    def open_evaluation_case(
        self, referral_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/referrals/{referral_id}/evaluation-cases", payload, headers
        )

    # ----------------------------------------------------------- consent records
    def get_consent_record(self, consent_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/consent-records/{consent_id}", headers=headers
        )

    def list_consent_records(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/consent-records", headers=headers, params=params
        )

    def record_consent_decision(
        self, consent_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/consent-records/{consent_id}/decision", payload, headers
        )

    # --------------------------------------------------------- evaluation cases
    def get_evaluation_case(self, case_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/evaluation-cases/{case_id}", headers=headers
        )

    def list_evaluation_cases(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/evaluation-cases", headers=headers, params=params
        )

    def get_eligibility_profile(self, case_id: str, headers: Dict[str, str]):
        return self._request(
            "GET",
            f"{PREFIX}/evaluation-cases/{case_id}/eligibility-profile",
            headers=headers,
        )

    def schedule_domain_assessment(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/evaluation-cases/{case_id}/domain-assessments",
            payload,
            headers,
        )

    def draft_report(self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/evaluation-cases/{case_id}/report", payload, headers
        )

    def request_revision(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/evaluation-cases/{case_id}/revision-requests",
            payload,
            headers,
        )

    def determine_eligibility(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/evaluation-cases/{case_id}/service-plans", payload, headers
        )

    # -------------------------------------------------------- domain assessments
    def get_domain_assessment(self, assessment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/domain-assessments/{assessment_id}", headers=headers
        )

    def list_domain_assessments(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/domain-assessments", headers=headers, params=params
        )

    def complete_domain_assessment(
        self, assessment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/domain-assessments/{assessment_id}/completion",
            payload,
            headers,
        )

    def invalidate_domain_assessment(
        self, assessment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/domain-assessments/{assessment_id}/invalidation",
            payload,
            headers,
        )

    # ------------------------------------------------------------- service plans
    def get_service_plan(self, plan_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/service-plans/{plan_id}", headers=headers)

    def list_service_plans(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/service-plans", headers=headers, params=params
        )

    def add_service_line(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/service-plans/{plan_id}/service-lines", payload, headers
        )

    def submit_plan_for_consent(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/service-plans/{plan_id}/consent-submission",
            payload,
            headers,
        )

    def kindergarten_transition(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/service-plans/{plan_id}/kindergarten-transition",
            payload,
            headers,
        )

    # ------------------------------------------------------------- service lines
    def get_service_line(self, line_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/service-lines/{line_id}", headers=headers)

    def list_service_lines(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/service-lines", headers=headers, params=params
        )

    def staff_service_line(
        self, line_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/service-lines/{line_id}/staff", payload, headers
        )

    def unstaff_service_line(
        self, line_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/service-lines/{line_id}/unstaff", payload, headers
        )

    # ------------------------------------------------------------- logical clock
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", payload, headers
        )

    # ------------------------------------------- raw escape hatch for edge cases
    def raw(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ):
        """Send an arbitrary request under the API prefix (relative path)."""
        return self._request(method, f"{PREFIX}{path}", payload, headers, params)


api_client = ApiClient()
