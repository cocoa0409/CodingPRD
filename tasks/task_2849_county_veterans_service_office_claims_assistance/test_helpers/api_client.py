"""
One method per endpoint of the County Veterans Service Office API.

Every path is mounted under the /cvso prefix. Collection reads take their
query parameters through `params` so pagination bounds can be driven
explicitly. The module also carries the instant canonicaliser used whenever a
test needs to compare a server-stamped datetime with a literal: the PRD fixes
the wire format at three fractional digits, so comparisons go through
canonical_instant() rather than against a raw string.
"""

import re
from typing import Any, Dict, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX

_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.(\d+))?(?:Z|\+00:00)$"
)


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """
    Normalise an ISO 8601 UTC instant to exactly three fractional digits.

    The PRD says a datetime field is "an ISO 8601 UTC instant with exactly
    three fractional-second digits, ending in Z". Sub-second width is the one
    detail that differs harmlessly between serialisers, so tests canonicalise
    both sides here instead of asserting on raw text.
    """
    if value is None:
        return None
    match = _INSTANT_RE.match(value)
    if not match:
        return value
    date_part, time_part, frac = match.groups()
    frac = (frac or "")[:3].ljust(3, "0")
    return f"{date_part}T{time_part}.{frac}Z"


def instants_equal(left: Optional[str], right: Optional[str]) -> bool:
    """True when two instants denote the same moment at millisecond width."""
    return canonical_instant(left) == canonical_instant(right)


class ApiClient(GenericApiClient):
    """Endpoint methods for every row in the PRD's endpoint table."""

    # ─── Raw escape hatch ─────────────────────────────

    def raw(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ) -> requests.Response:
        """Send an arbitrary request, for header-level and shape-level probes."""
        return self._request(method, f"{API_PREFIX}{path}", payload, headers, params)

    # ─── Logical clock ────────────────────────────────

    def set_clock(self, payload: Dict, headers: Dict) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/_clock/set_current_utc", payload, headers
        )

    # ─── Representatives ──────────────────────────────

    def create_representative(self, payload: Dict, headers: Dict) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/representatives", payload, headers)

    def list_representatives(
        self, headers: Dict, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/representatives", headers=headers, params=params
        )

    def get_representative(
        self, representative_id: str, headers: Dict
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/representatives/{representative_id}", headers=headers
        )

    def update_representative(
        self, representative_id: str, payload: Dict, headers: Dict
    ) -> requests.Response:
        return self._request(
            "PATCH",
            f"{API_PREFIX}/representatives/{representative_id}",
            payload,
            headers,
        )

    def representative_accreditation(
        self, representative_id: str, payload: Dict, headers: Dict
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/representatives/{representative_id}/accreditation",
            payload,
            headers,
        )

    def list_representative_outreach_events(
        self, representative_id: str, headers: Dict, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/representatives/{representative_id}/outreach-events",
            headers=headers,
            params=params,
        )

    def get_representative_caseload(
        self, representative_id: str, headers: Dict
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/representatives/{representative_id}/caseload",
            headers=headers,
        )

    # ─── Veterans ─────────────────────────────────────

    def create_veteran(self, payload: Dict, headers: Dict) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/veterans", payload, headers)

    def list_veterans(
        self, headers: Dict, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/veterans", headers=headers, params=params
        )

    def get_veteran(self, veteran_id: str, headers: Dict) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/veterans/{veteran_id}", headers=headers
        )

    def update_veteran(
        self, veteran_id: str, payload: Dict, headers: Dict
    ) -> requests.Response:
        return self._request(
            "PATCH", f"{API_PREFIX}/veterans/{veteran_id}", payload, headers
        )

    def create_discharge_document(
        self, veteran_id: str, payload: Dict, headers: Dict
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/veterans/{veteran_id}/discharge-documents",
            payload,
            headers,
        )

    def screen_veteran(
        self, veteran_id: str, headers: Dict, payload: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/veterans/{veteran_id}/screen", payload, headers
        )

    def list_veteran_eligibility_screens(
        self, veteran_id: str, headers: Dict, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/veterans/{veteran_id}/eligibility-screens",
            headers=headers,
            params=params,
        )

    def assign_representative(
        self, veteran_id: str, payload: Dict, headers: Dict
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/veterans/{veteran_id}/assign-representative",
            payload,
            headers,
        )

    def veteran_status(
        self, veteran_id: str, payload: Dict, headers: Dict
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/veterans/{veteran_id}/status", payload, headers
        )

    # ─── Discharge documents ──────────────────────────

    def list_discharge_documents(
        self, headers: Dict, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/discharge-documents", headers=headers, params=params
        )

    def get_discharge_document(
        self, document_id: str, headers: Dict
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/discharge-documents/{document_id}", headers=headers
        )

    def review_discharge_document(
        self, document_id: str, payload: Dict, headers: Dict
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/discharge-documents/{document_id}/review",
            payload,
            headers,
        )

    def resubmit_discharge_document(
        self, document_id: str, payload: Dict, headers: Dict
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/discharge-documents/{document_id}/resubmit",
            payload,
            headers,
        )

    # ─── Powers of attorney ───────────────────────────

    def create_power_of_attorney(
        self, payload: Dict, headers: Dict
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/powers-of-attorney", payload, headers
        )

    def list_powers_of_attorney(
        self, headers: Dict, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/powers-of-attorney", headers=headers, params=params
        )

    def get_power_of_attorney(self, poa_id: str, headers: Dict) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/powers-of-attorney/{poa_id}", headers=headers
        )

    def accept_power_of_attorney(
        self, poa_id: str, payload: Dict, headers: Dict
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/powers-of-attorney/{poa_id}/accept", payload, headers
        )

    def revoke_power_of_attorney(
        self, poa_id: str, payload: Dict, headers: Dict
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/powers-of-attorney/{poa_id}/revoke", payload, headers
        )

    # ─── Claims ───────────────────────────────────────

    def create_claim(self, payload: Dict, headers: Dict) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/claims", payload, headers)

    def list_claims(
        self, headers: Dict, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/claims", headers=headers, params=params
        )

    def get_claim(self, claim_id: str, headers: Dict) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/claims/{claim_id}", headers=headers)

    def update_claim(
        self, claim_id: str, payload: Dict, headers: Dict
    ) -> requests.Response:
        return self._request(
            "PATCH", f"{API_PREFIX}/claims/{claim_id}", payload, headers
        )

    def claim_transition(
        self, claim_id: str, payload: Dict, headers: Dict
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/claims/{claim_id}/transitions", payload, headers
        )

    def record_decision(
        self, claim_id: str, payload: Dict, headers: Dict
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/claims/{claim_id}/record-decision", payload, headers
        )

    def create_evidence_item(
        self, claim_id: str, payload: Dict, headers: Dict
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/claims/{claim_id}/evidence-items", payload, headers
        )

    def list_claim_evidence_items(
        self, claim_id: str, headers: Dict, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/claims/{claim_id}/evidence-items",
            headers=headers,
            params=params,
        )

    # ─── Evidence items ───────────────────────────────

    def list_evidence_items(
        self, headers: Dict, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/evidence-items", headers=headers, params=params
        )

    def get_evidence_item(self, item_id: str, headers: Dict) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/evidence-items/{item_id}", headers=headers
        )

    def evidence_item_status(
        self, item_id: str, payload: Dict, headers: Dict
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/evidence-items/{item_id}/status", payload, headers
        )

    # ─── Examination sites ────────────────────────────

    def create_exam_site(self, payload: Dict, headers: Dict) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/exam-sites", payload, headers)

    def list_exam_sites(
        self, headers: Dict, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/exam-sites", headers=headers, params=params
        )

    def get_exam_site(self, site_id: str, headers: Dict) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/exam-sites/{site_id}", headers=headers
        )

    def update_exam_site(
        self, site_id: str, payload: Dict, headers: Dict
    ) -> requests.Response:
        return self._request(
            "PATCH", f"{API_PREFIX}/exam-sites/{site_id}", payload, headers
        )

    # ─── Examination appointments ─────────────────────

    def create_exam_appointment(
        self, payload: Dict, headers: Dict
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/exam-appointments", payload, headers)

    def list_exam_appointments(
        self, headers: Dict, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/exam-appointments", headers=headers, params=params
        )

    def get_exam_appointment(
        self, appointment_id: str, headers: Dict
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/exam-appointments/{appointment_id}", headers=headers
        )

    def exam_appointment_status(
        self, appointment_id: str, payload: Dict, headers: Dict
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/exam-appointments/{appointment_id}/status",
            payload,
            headers,
        )

    # ─── Decision reviews ─────────────────────────────

    def create_decision_review(self, payload: Dict, headers: Dict) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/decision-reviews", payload, headers)

    def list_decision_reviews(
        self, headers: Dict, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/decision-reviews", headers=headers, params=params
        )

    def get_decision_review(self, review_id: str, headers: Dict) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/decision-reviews/{review_id}", headers=headers
        )

    def decision_review_status(
        self, review_id: str, payload: Dict, headers: Dict
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/decision-reviews/{review_id}/status",
            payload,
            headers,
        )

    def sweep_decision_review_expirations(
        self, headers: Dict, payload: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/decision-reviews/sweep-expirations", payload, headers
        )

    # ─── State programs ───────────────────────────────

    def create_state_program(self, payload: Dict, headers: Dict) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/state-programs", payload, headers)

    def list_state_programs(
        self, headers: Dict, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/state-programs", headers=headers, params=params
        )

    def get_state_program(self, program_id: str, headers: Dict) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/state-programs/{program_id}", headers=headers
        )

    def update_state_program(
        self, program_id: str, payload: Dict, headers: Dict
    ) -> requests.Response:
        return self._request(
            "PATCH", f"{API_PREFIX}/state-programs/{program_id}", payload, headers
        )

    # ─── State benefit applications ───────────────────

    def create_state_benefit_application(
        self, payload: Dict, headers: Dict
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/state-benefit-applications", payload, headers
        )

    def list_state_benefit_applications(
        self, headers: Dict, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/state-benefit-applications",
            headers=headers,
            params=params,
        )

    def get_state_benefit_application(
        self, application_id: str, headers: Dict
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/state-benefit-applications/{application_id}",
            headers=headers,
        )

    def application_determination(
        self, application_id: str, payload: Dict, headers: Dict
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/state-benefit-applications/{application_id}/determination",
            payload,
            headers,
        )

    def application_disbursement(
        self, application_id: str, payload: Dict, headers: Dict
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/state-benefit-applications/{application_id}/disbursement",
            payload,
            headers,
        )

    # ─── Outreach events ──────────────────────────────

    def create_outreach_event(self, payload: Dict, headers: Dict) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/outreach-events", payload, headers)

    def list_outreach_events(
        self, headers: Dict, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/outreach-events", headers=headers, params=params
        )

    def get_outreach_event(self, event_id: str, headers: Dict) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/outreach-events/{event_id}", headers=headers
        )

    def outreach_event_status(
        self, event_id: str, payload: Dict, headers: Dict
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/outreach-events/{event_id}/status", payload, headers
        )

    # ─── Outcome reports ──────────────────────────────

    def create_outcome_report(self, payload: Dict, headers: Dict) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/outcome-reports", payload, headers)

    def list_outcome_reports(
        self, headers: Dict, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/outcome-reports", headers=headers, params=params
        )

    def get_outcome_report(self, report_id: str, headers: Dict) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/outcome-reports/{report_id}", headers=headers
        )

    def compute_outcome_report(
        self, report_id: str, payload: Dict, headers: Dict
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/outcome-reports/{report_id}/compute", payload, headers
        )

    def submit_outcome_report(
        self, report_id: str, headers: Dict, payload: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/outcome-reports/{report_id}/submit", payload, headers
        )

    def review_outcome_report(
        self, report_id: str, payload: Dict, headers: Dict
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/outcome-reports/{report_id}/review", payload, headers
        )

    def reopen_outcome_report(
        self, report_id: str, headers: Dict, payload: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/outcome-reports/{report_id}/reopen", payload, headers
        )


api_client = ApiClient()
