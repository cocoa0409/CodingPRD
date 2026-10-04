"""HTTP client: one method per endpoint the contract declares.

Every method returns the raw response so a test can assert on the status code
as well as on the body. Query filters and pagination travel as ``params``;
request bodies as ``payload``.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO 8601 UTC instant so two spellings of one instant match.

    The contract renders instants with three fractional digits, but the same
    instant may legitimately arrive with none, with fewer digits, or with
    trailing zeroes. Comparisons therefore run on the canonical form
    ``YYYY-MM-DDTHH:MM:SS.mmmZ`` instead of on the raw strings.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    if "+" in text[10:]:
        text = text[: 10 + text[10:].index("+")]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = (frac + "000")[:3]
    else:
        head, frac = text, "000"
    return f"{head}.{frac}Z"


def instant_matches(actual: Optional[str], expected: str) -> bool:
    """True when ``actual`` names the same instant as ``expected``."""
    return canonical_instant(actual) == canonical_instant(expected)


class ApiClient(GenericApiClient):
    """Endpoint methods for every route the contract declares."""

    # ── Logical clock ──────────────────────────────────────────────────────

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/audit/_clock/set_current_utc", payload, headers)

    # ── Clients ────────────────────────────────────────────────────────────

    def create_client(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/audit/clients", payload, headers)

    def list_clients(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/audit/clients", headers=headers, params=params)

    def get_client(self, client_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/audit/clients/{client_id}", headers=headers)

    # ── Engagements ────────────────────────────────────────────────────────

    def create_engagement(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/audit/engagements", payload, headers)

    def list_engagements(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/audit/engagements", headers=headers, params=params)

    def get_engagement(self, engagement_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/audit/engagements/{engagement_id}", headers=headers)

    def get_independence_summary(
        self, engagement_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/audit/engagements/{engagement_id}/independence-summary", headers=headers
        )

    def transition_engagement(
        self, engagement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/audit/engagements/{engagement_id}/transitions", payload, headers
        )

    # ── Client acceptances ─────────────────────────────────────────────────

    def create_acceptance(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/audit/client-acceptances", payload, headers)

    def list_acceptances(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/audit/client-acceptances", headers=headers, params=params)

    def get_acceptance(self, acceptance_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/audit/client-acceptances/{acceptance_id}", headers=headers)

    def submit_acceptance(self, acceptance_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"/audit/client-acceptances/{acceptance_id}/submit", {}, headers
        )

    def decide_acceptance(
        self, acceptance_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/audit/client-acceptances/{acceptance_id}/decision", payload, headers
        )

    def create_integrity_assessment(
        self, acceptance_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/audit/client-acceptances/{acceptance_id}/integrity-assessments", payload, headers
        )

    def list_integrity_assessments(
        self, acceptance_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/audit/client-acceptances/{acceptance_id}/integrity-assessments", headers=headers
        )

    # ── Affiliates ─────────────────────────────────────────────────────────

    def create_affiliate(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/audit/affiliates", payload, headers)

    def list_affiliates(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/audit/affiliates", headers=headers, params=params)

    def get_affiliate(self, affiliate_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/audit/affiliates/{affiliate_id}", headers=headers)

    # ── Professionals ──────────────────────────────────────────────────────

    def create_professional(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/audit/professionals", payload, headers)

    def list_professionals(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/audit/professionals", headers=headers, params=params)

    def get_professional(self, professional_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/audit/professionals/{professional_id}", headers=headers)

    # ── Engagement role assignments ────────────────────────────────────────

    def create_assignment(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/audit/role-assignments", payload, headers)

    def list_assignments(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/audit/role-assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/audit/role-assignments/{assignment_id}", headers=headers)

    def end_assignment(self, assignment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/audit/role-assignments/{assignment_id}/end", {}, headers)

    # ── Independence findings ──────────────────────────────────────────────

    def create_finding(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/audit/independence-findings", payload, headers)

    def list_findings(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/audit/independence-findings", headers=headers, params=params)

    def get_finding(self, finding_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/audit/independence-findings/{finding_id}", headers=headers)

    def transition_finding(
        self, finding_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/audit/independence-findings/{finding_id}/transitions", payload, headers
        )

    # ── Independence threats ───────────────────────────────────────────────

    def create_threat(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/audit/independence-threats", payload, headers)

    def list_threats(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/audit/independence-threats", headers=headers, params=params)

    def get_threat(self, threat_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/audit/independence-threats/{threat_id}", headers=headers)

    def transition_threat(
        self, threat_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/audit/independence-threats/{threat_id}/transitions", payload, headers
        )

    # ── Non-audit services ─────────────────────────────────────────────────

    def create_service(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/audit/non-audit-services", payload, headers)

    def list_services(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/audit/non-audit-services", headers=headers, params=params)

    def get_service(self, service_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/audit/non-audit-services/{service_id}", headers=headers)

    def transition_service(
        self, service_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/audit/non-audit-services/{service_id}/transitions", payload, headers
        )

    # ── Affiliate attestations ─────────────────────────────────────────────

    def create_attestation(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/audit/affiliate-attestations", payload, headers)

    def list_attestations(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/audit/affiliate-attestations", headers=headers, params=params)

    def get_attestation(self, attestation_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/audit/affiliate-attestations/{attestation_id}", headers=headers)

    def transition_attestation(
        self, attestation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/audit/affiliate-attestations/{attestation_id}/transitions", payload, headers
        )

    # ── Quality reviews ────────────────────────────────────────────────────

    def create_review(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/audit/quality-reviews", payload, headers)

    def list_reviews(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/audit/quality-reviews", headers=headers, params=params)

    def get_review(self, review_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/audit/quality-reviews/{review_id}", headers=headers)

    def transition_review(
        self, review_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/audit/quality-reviews/{review_id}/transitions", payload, headers
        )


api_client = ApiClient()
