"""One method per endpoint of the Public Records Data Journalism Desk API.

The inventory mirrors PRD S4 exactly, including the fact that the logical-clock
endpoint is the single path that does not live under ``/records-desk``.

The module also owns instant canonicalisation. PRD S2.4 pins exactly three
fractional digits on ``created_at`` and ``updated_at``, and PRD S2.2 pins them
on ``api_request_timestamp``, but every other instant the API echoes back (a
stamped deadline, a notice instant, a window bound) has no pinned fractional
width. Tests therefore compare instants as instants -- never as strings --
through :func:`canonical_instant` and :func:`instants_equal`.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from . import constants as C


def canonical_instant(value: str) -> datetime:
    """Parse any ISO-8601 UTC instant into a timezone-aware ``datetime``.

    Accepts a trailing ``Z`` or an explicit offset, and accepts zero through six
    fractional digits, so a server that answers ``2026-08-17T23:59:59Z`` and one
    that answers ``2026-08-17T23:59:59.000000Z`` compare equal.
    """
    assert isinstance(value, str), f"expected an ISO-8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def instants_equal(left: str, right: str) -> bool:
    """True when two ISO-8601 strings denote the same instant."""
    return canonical_instant(left) == canonical_instant(right)


class ApiClient(GenericApiClient):
    """Typed wrapper over every path in PRD S4."""

    # ---------------------------------------------------------------- clock

    def set_clock(self, to_iso8601: str, headers: Dict[str, str]) -> requests.Response:
        """POST /_clock/set_current_utc (PRD S2.6). Answers ``current_utc``."""
        return self._request(
            "POST", C.CLOCK_PATH, payload={"to_iso8601": to_iso8601}, headers=headers
        )

    # ---------------------------------------------------------------- desks

    def create_desk(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", C.DESKS_PATH, payload=payload, headers=headers)

    def get_desk(self, desk_id: str, headers) -> requests.Response:
        return self._request("GET", f"{C.DESKS_PATH}/{desk_id}", headers=headers)

    def create_budget_adjustment(
        self, desk_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{C.DESKS_PATH}/{desk_id}/budget-adjustments",
            payload=payload,
            headers=headers,
        )

    def create_source_exposure_incident(
        self, desk_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{C.DESKS_PATH}/{desk_id}/source-exposure-incidents",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------- agencies

    def create_agency(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", C.AGENCIES_PATH, payload=payload, headers=headers)

    def get_agency(self, agency_id: str, headers) -> requests.Response:
        return self._request("GET", f"{C.AGENCIES_PATH}/{agency_id}", headers=headers)

    # ------------------------------------------------------ records requests

    def create_records_request(
        self, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", C.RECORDS_REQUESTS_PATH, payload=payload, headers=headers
        )

    def get_records_request(self, request_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{C.RECORDS_REQUESTS_PATH}/{request_id}", headers=headers
        )

    def list_records_requests(
        self, headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", C.RECORDS_REQUESTS_PATH, payload=params, headers=headers
        )

    def submit_records_request(
        self, request_id: str, headers, payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{C.RECORDS_REQUESTS_PATH}/{request_id}/submit",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def determine_fee(
        self, request_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{C.RECORDS_REQUESTS_PATH}/{request_id}/fee-determination",
            payload=payload,
            headers=headers,
        )

    def request_clarification(
        self, request_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{C.RECORDS_REQUESTS_PATH}/{request_id}/clarification-request",
            payload=payload,
            headers=headers,
        )

    def respond_clarification(
        self, request_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{C.RECORDS_REQUESTS_PATH}/{request_id}/clarification-response",
            payload=payload,
            headers=headers,
        )

    def record_agency_decision(
        self, request_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{C.RECORDS_REQUESTS_PATH}/{request_id}/agency-decision",
            payload=payload,
            headers=headers,
        )

    def withdraw_records_request(
        self, request_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{C.RECORDS_REQUESTS_PATH}/{request_id}/withdrawal",
            payload=payload,
            headers=headers,
        )

    # -------------------------------------------------------------- appeals

    def create_appeal(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", C.APPEALS_PATH, payload=payload, headers=headers)

    def get_appeal(self, appeal_id: str, headers) -> requests.Response:
        return self._request("GET", f"{C.APPEALS_PATH}/{appeal_id}", headers=headers)

    def list_appeals(
        self, headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", C.APPEALS_PATH, payload=params, headers=headers)

    def decide_appeal(
        self, appeal_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{C.APPEALS_PATH}/{appeal_id}/decision",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------- datasets

    def create_dataset(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", C.DATASETS_PATH, payload=payload, headers=headers)

    def get_dataset(self, dataset_id: str, headers) -> requests.Response:
        return self._request("GET", f"{C.DATASETS_PATH}/{dataset_id}", headers=headers)

    def list_datasets(
        self, headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", C.DATASETS_PATH, payload=params, headers=headers)

    def deliver_dataset(
        self, dataset_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{C.DATASETS_PATH}/{dataset_id}/delivery",
            payload=payload,
            headers=headers,
        )

    def create_field_definition(
        self, dataset_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{C.DATASETS_PATH}/{dataset_id}/field-definitions",
            payload=payload,
            headers=headers,
        )

    def list_field_definitions(
        self, dataset_id: str, headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{C.DATASETS_PATH}/{dataset_id}/field-definitions",
            payload=params,
            headers=headers,
        )

    def suppress_field(
        self, dataset_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{C.DATASETS_PATH}/{dataset_id}/field-suppressions",
            payload=payload,
            headers=headers,
        )

    def lock_cleaning(
        self, dataset_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{C.DATASETS_PATH}/{dataset_id}/cleaning-lock",
            payload=payload,
            headers=headers,
        )

    def quarantine_dataset(
        self, dataset_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{C.DATASETS_PATH}/{dataset_id}/quarantine",
            payload=payload,
            headers=headers,
        )

    def requalify_dataset(
        self, dataset_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{C.DATASETS_PATH}/{dataset_id}/requalification",
            payload=payload,
            headers=headers,
        )

    # -------------------------------------------------------- investigations

    def create_investigation(
        self, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", C.INVESTIGATIONS_PATH, payload=payload, headers=headers
        )

    def get_investigation(self, investigation_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{C.INVESTIGATIONS_PATH}/{investigation_id}", headers=headers
        )

    def list_investigations(
        self, headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", C.INVESTIGATIONS_PATH, payload=params, headers=headers
        )

    def lock_findings(
        self,
        investigation_id: str,
        headers,
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{C.INVESTIGATIONS_PATH}/{investigation_id}/lock-findings",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def grant_legal_clearance(
        self, investigation_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{C.INVESTIGATIONS_PATH}/{investigation_id}/legal-clearance",
            payload=payload,
            headers=headers,
        )

    def publish_investigation(
        self, investigation_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{C.INVESTIGATIONS_PATH}/{investigation_id}/publication",
            payload=payload,
            headers=headers,
        )

    def preview_disclosure_risk(
        self,
        investigation_id: str,
        headers,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{C.INVESTIGATIONS_PATH}/{investigation_id}/disclosure-risk-preview",
            payload=params,
            headers=headers,
        )

    # --------------------------------------------------------- analysis runs

    def create_analysis_run(
        self, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", C.ANALYSIS_RUNS_PATH, payload=payload, headers=headers
        )

    def get_analysis_run(self, run_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{C.ANALYSIS_RUNS_PATH}/{run_id}", headers=headers
        )

    def list_analysis_runs(
        self, headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", C.ANALYSIS_RUNS_PATH, payload=params, headers=headers
        )

    def allocate_cost(
        self, run_id: str, headers, payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """POST .../cost-allocation -- PRD S3.7: "it takes no payload at all"."""
        return self._request(
            "POST",
            f"{C.ANALYSIS_RUNS_PATH}/{run_id}/cost-allocation",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def submit_peer_review(
        self, run_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{C.ANALYSIS_RUNS_PATH}/{run_id}/peer-review",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------- findings

    def create_finding(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", C.FINDINGS_PATH, payload=payload, headers=headers)

    def get_finding(self, finding_id: str, headers) -> requests.Response:
        return self._request("GET", f"{C.FINDINGS_PATH}/{finding_id}", headers=headers)

    def list_findings(
        self, headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", C.FINDINGS_PATH, payload=params, headers=headers)

    def match_document(
        self, finding_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{C.FINDINGS_PATH}/{finding_id}/document-match",
            payload=payload,
            headers=headers,
        )

    def revoke_verification(
        self, finding_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{C.FINDINGS_PATH}/{finding_id}/verification-revocation",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------ expert reviewers

    def create_expert_reviewer(
        self, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", C.EXPERT_REVIEWERS_PATH, payload=payload, headers=headers
        )

    def get_expert_reviewer(self, reviewer_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{C.EXPERT_REVIEWERS_PATH}/{reviewer_id}", headers=headers
        )

    # ----------------------------------------------------- review assignments

    def create_review_assignment(
        self, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", C.REVIEW_ASSIGNMENTS_PATH, payload=payload, headers=headers
        )

    def get_review_assignment(self, assignment_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{C.REVIEW_ASSIGNMENTS_PATH}/{assignment_id}", headers=headers
        )

    def list_review_assignments(
        self, headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", C.REVIEW_ASSIGNMENTS_PATH, payload=params, headers=headers
        )

    def submit_verdict(
        self, assignment_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{C.REVIEW_ASSIGNMENTS_PATH}/{assignment_id}/verdict",
            payload=payload,
            headers=headers,
        )

    # ---------------------------------------------- subject response requests

    def create_subject_response_request(
        self, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", C.SUBJECT_RESPONSE_REQUESTS_PATH, payload=payload, headers=headers
        )

    def get_subject_response_request(
        self, subject_request_id: str, headers
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{C.SUBJECT_RESPONSE_REQUESTS_PATH}/{subject_request_id}",
            headers=headers,
        )

    def list_subject_response_requests(
        self, headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", C.SUBJECT_RESPONSE_REQUESTS_PATH, payload=params, headers=headers
        )

    def record_attempt(
        self, subject_request_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{C.SUBJECT_RESPONSE_REQUESTS_PATH}/{subject_request_id}/attempts",
            payload=payload,
            headers=headers,
        )

    def record_subject_response(
        self, subject_request_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{C.SUBJECT_RESPONSE_REQUESTS_PATH}/{subject_request_id}/response",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------- secure enclaves and sessions

    def create_secure_enclave(
        self, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", C.SECURE_ENCLAVES_PATH, payload=payload, headers=headers
        )

    def create_enclave_session(
        self, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", C.ENCLAVE_SESSIONS_PATH, payload=payload, headers=headers
        )

    def get_enclave_session(self, session_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{C.ENCLAVE_SESSIONS_PATH}/{session_id}", headers=headers
        )

    def list_enclave_sessions(
        self, headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", C.ENCLAVE_SESSIONS_PATH, payload=params, headers=headers
        )

    def close_enclave_session(
        self, session_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{C.ENCLAVE_SESSIONS_PATH}/{session_id}/closure",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------- raw path escape

    def raw_get(
        self, path: str, headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """GET an arbitrary path -- used only for pagination-bound probes."""
        return self._request("GET", path, payload=params, headers=headers)

    def raw_post(
        self, path: str, payload: Optional[Dict[str, Any]], headers
    ) -> requests.Response:
        """POST an arbitrary path -- used only for role-matrix probes."""
        return self._request("POST", path, payload=payload, headers=headers)
