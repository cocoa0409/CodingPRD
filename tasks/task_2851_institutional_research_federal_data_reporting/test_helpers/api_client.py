"""
HTTP client for the Institutional Research & Federal Data Reporting API.

One method per endpoint of the PRD's endpoint table, all mounted under the /ir
prefix apart from the logical-clock endpoint. Every method takes the caller's
headers explicitly so that a test can name the acting role and the acting opaque
operator identifier, and every method returns the raw response so that a test can
assert on the HTTP status as well as the envelope.

The module also exposes canonical_instant(), which normalises an ISO 8601 UTC
instant to exactly three fractional digits. The PRD declares that format for every
server-written timestamp, and comparing through this helper keeps a test from
failing on nothing more than sub-second width.
"""

import re
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH

_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:?\d{2})?$"
)


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """
    Normalise an ISO 8601 UTC instant to exactly three fractional digits.

    '2026-11-01T00:00:00Z', '2026-11-01T00:00:00.0Z' and
    '2026-11-01T00:00:00.000000Z' all canonicalise to '2026-11-01T00:00:00.000Z'.
    Values that are not instants (including None and calendar dates) are returned
    unchanged so that the helper is safe to apply to any field.
    """
    if not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value.strip())
    if not match:
        return value
    seconds, fraction, _offset = match.groups()
    millis = (fraction or "")[:3].ljust(3, "0")
    return f"{seconds}.{millis}Z"


def _prune(payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Drop keys whose value is the _OMIT sentinel, keeping explicit nulls."""
    if payload is None:
        return None
    return {k: v for k, v in payload.items() if v is not _OMIT}


class _Omit:
    """Sentinel distinguishing 'field not supplied' from 'field supplied as null'."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return "<OMIT>"


_OMIT = _Omit()
OMIT = _OMIT


class ApiClient(GenericApiClient):
    """Endpoint methods for the institutional research reporting API."""

    # ─── Logical clock ────────────────────────────────────────────

    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        """Set the server's logical clock, which every temporal rule reads."""
        return self._request("POST", CLOCK_PATH, {"to_iso8601": to_iso8601}, headers)

    def set_clock_raw(self, payload: Dict[str, Any], headers: Dict[str, str]):
        """Set the logical clock with an arbitrary payload."""
        return self._request("POST", CLOCK_PATH, _prune(payload), headers)

    # ─── Reporting cycles ─────────────────────────────────────────

    def create_reporting_cycle(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/reporting-cycles", _prune(payload), headers)

    def get_reporting_cycle(self, cycle_id: str, headers):
        return self._request("GET", f"{API_PREFIX}/reporting-cycles/{cycle_id}", None, headers)

    def census_lock_cycle(self, cycle_id: str, headers, payload: Optional[Dict] = None):
        return self._request(
            "POST", f"{API_PREFIX}/reporting-cycles/{cycle_id}/census-lock", payload or {}, headers
        )

    def freeze_cycle(self, cycle_id: str, headers, payload: Optional[Dict] = None):
        return self._request(
            "POST", f"{API_PREFIX}/reporting-cycles/{cycle_id}/freeze", payload or {}, headers
        )

    def reopen_cycle(self, cycle_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{API_PREFIX}/reporting-cycles/{cycle_id}/reopen", _prune(payload), headers
        )

    # ─── Census extracts (frozen files) ───────────────────────────

    def register_frozen_file(self, cycle_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{API_PREFIX}/reporting-cycles/{cycle_id}/frozen-files", _prune(payload), headers
        )

    def get_frozen_file(self, frozen_file_id: str, headers):
        return self._request("GET", f"{API_PREFIX}/frozen-files/{frozen_file_id}", None, headers)

    def list_frozen_files(self, headers, **filters):
        return self._request("GET", f"{API_PREFIX}/frozen-files", _prune(filters), headers)

    # ─── Survey components ────────────────────────────────────────

    def create_survey_component(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/survey-components", _prune(payload), headers)

    def get_survey_component(self, component_id: str, headers):
        return self._request("GET", f"{API_PREFIX}/survey-components/{component_id}", None, headers)

    def list_survey_components(self, headers, **filters):
        return self._request("GET", f"{API_PREFIX}/survey-components", _prune(filters), headers)

    def prepare_component(self, component_id: str, headers, payload: Optional[Dict] = None):
        return self._request(
            "POST", f"{API_PREFIX}/survey-components/{component_id}/prepare", payload or {}, headers
        )

    def certify_component(self, component_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{API_PREFIX}/survey-components/{component_id}/certify", _prune(payload), headers
        )

    def submit_component(self, component_id: str, headers, payload: Optional[Dict] = None):
        return self._request(
            "POST", f"{API_PREFIX}/survey-components/{component_id}/submit", payload or {}, headers
        )

    def revert_component_to_draft(self, component_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/survey-components/{component_id}/revert-to-draft",
            _prune(payload),
            headers,
        )

    # ─── Reported metrics ─────────────────────────────────────────

    def add_component_metric(self, component_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{API_PREFIX}/survey-components/{component_id}/metrics", _prune(payload), headers
        )

    def get_component_metric(self, metric_id: str, headers):
        return self._request("GET", f"{API_PREFIX}/component-metrics/{metric_id}", None, headers)

    def list_component_metrics(self, headers, **filters):
        return self._request("GET", f"{API_PREFIX}/component-metrics", _prune(filters), headers)

    def correct_component_metric(self, metric_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "PATCH", f"{API_PREFIX}/component-metrics/{metric_id}", _prune(payload), headers
        )

    # ─── Edit checks ──────────────────────────────────────────────

    def get_edit_check(self, edit_check_id: str, headers):
        return self._request("GET", f"{API_PREFIX}/edit-checks/{edit_check_id}", None, headers)

    def list_edit_checks(self, headers, **filters):
        return self._request("GET", f"{API_PREFIX}/edit-checks", _prune(filters), headers)

    def explain_edit_check(self, edit_check_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{API_PREFIX}/edit-checks/{edit_check_id}/explain", _prune(payload), headers
        )

    def adjudicate_edit_check(self, edit_check_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{API_PREFIX}/edit-checks/{edit_check_id}/adjudicate", _prune(payload), headers
        )

    # ─── Cohorts, members and exclusions ──────────────────────────

    def create_cohort(self, cycle_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{API_PREFIX}/reporting-cycles/{cycle_id}/cohorts", _prune(payload), headers
        )

    def get_cohort(self, cohort_id: str, headers):
        return self._request("GET", f"{API_PREFIX}/cohorts/{cohort_id}", None, headers)

    def list_cohorts(self, headers, **filters):
        return self._request("GET", f"{API_PREFIX}/cohorts", _prune(filters), headers)

    def lock_cohort(self, cohort_id: str, headers, payload: Optional[Dict] = None):
        return self._request("POST", f"{API_PREFIX}/cohorts/{cohort_id}/lock", payload or {}, headers)

    def get_cohort_rate_summary(self, cohort_id: str, headers):
        return self._request("GET", f"{API_PREFIX}/cohorts/{cohort_id}/rate-summary", None, headers)

    def add_cohort_member(self, cohort_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{API_PREFIX}/cohorts/{cohort_id}/members", _prune(payload), headers
        )

    def get_cohort_member(self, member_id: str, headers):
        return self._request("GET", f"{API_PREFIX}/cohort-members/{member_id}", None, headers)

    def list_cohort_members(self, headers, **filters):
        return self._request("GET", f"{API_PREFIX}/cohort-members", _prune(filters), headers)

    def record_member_outcome(self, member_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "PATCH", f"{API_PREFIX}/cohort-members/{member_id}", _prune(payload), headers
        )

    def file_exclusion_claim(self, member_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{API_PREFIX}/cohort-members/{member_id}/exclusion-claim", _prune(payload), headers
        )

    def review_exclusion_claim(self, member_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{API_PREFIX}/cohort-members/{member_id}/exclusion-review", _prune(payload), headers
        )

    # ─── Federal definition library ───────────────────────────────

    def create_federal_definition(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/federal-definitions", _prune(payload), headers)

    def get_federal_definition(self, definition_id: str, headers):
        return self._request(
            "GET", f"{API_PREFIX}/federal-definitions/{definition_id}", None, headers
        )

    def list_federal_definitions(self, headers, **filters):
        return self._request("GET", f"{API_PREFIX}/federal-definitions", _prune(filters), headers)

    # ─── Element mappings ─────────────────────────────────────────

    def propose_element_mapping(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/element-mappings", _prune(payload), headers)

    def get_element_mapping(self, mapping_id: str, headers):
        return self._request("GET", f"{API_PREFIX}/element-mappings/{mapping_id}", None, headers)

    def list_element_mappings(self, headers, **filters):
        return self._request("GET", f"{API_PREFIX}/element-mappings", _prune(filters), headers)

    def validate_element_mapping(self, mapping_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{API_PREFIX}/element-mappings/{mapping_id}/validate", _prune(payload), headers
        )

    def revise_element_mapping(self, mapping_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{API_PREFIX}/element-mappings/{mapping_id}/revise", _prune(payload), headers
        )

    # ─── External submissions ─────────────────────────────────────

    def create_external_submission(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/external-submissions", _prune(payload), headers)

    def get_external_submission(self, submission_id: str, headers):
        return self._request(
            "GET", f"{API_PREFIX}/external-submissions/{submission_id}", None, headers
        )

    def list_external_submissions(self, headers, **filters):
        return self._request("GET", f"{API_PREFIX}/external-submissions", _prune(filters), headers)

    def reconcile_submission(self, submission_id: str, headers, payload: Optional[Dict] = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/external-submissions/{submission_id}/reconcile",
            payload or {},
            headers,
        )

    def override_submission_variance(self, submission_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/external-submissions/{submission_id}/variance-override",
            _prune(payload),
            headers,
        )

    def transmit_submission(self, submission_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/external-submissions/{submission_id}/transmit",
            _prune(payload),
            headers,
        )

    # ─── Dashboard publications ───────────────────────────────────

    def create_publication(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/publications", _prune(payload), headers)

    def get_publication(self, publication_id: str, headers):
        return self._request("GET", f"{API_PREFIX}/publications/{publication_id}", None, headers)

    def list_publications(self, headers, **filters):
        return self._request("GET", f"{API_PREFIX}/publications", _prune(filters), headers)

    def withdraw_publication(self, publication_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{API_PREFIX}/publications/{publication_id}/withdraw", _prune(payload), headers
        )

    def file_restatement(self, publication_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/publications/{publication_id}/restatements",
            _prune(payload),
            headers,
        )

    # ─── Restatement requests ─────────────────────────────────────

    def get_restatement(self, restatement_id: str, headers):
        return self._request("GET", f"{API_PREFIX}/restatements/{restatement_id}", None, headers)

    def list_restatements(self, headers, **filters):
        return self._request("GET", f"{API_PREFIX}/restatements", _prune(filters), headers)

    def approve_restatement(self, restatement_id: str, headers, payload: Optional[Dict] = None):
        return self._request(
            "POST", f"{API_PREFIX}/restatements/{restatement_id}/approve", _prune(payload) or {}, headers
        )

    def reject_restatement(self, restatement_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{API_PREFIX}/restatements/{restatement_id}/reject", _prune(payload), headers
        )

    # ─── Data requests and disclosure cells ───────────────────────

    def create_data_request(self, cycle_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{API_PREFIX}/reporting-cycles/{cycle_id}/data-requests", _prune(payload), headers
        )

    def get_data_request(self, request_id: str, headers):
        return self._request("GET", f"{API_PREFIX}/data-requests/{request_id}", None, headers)

    def list_data_requests(self, headers, **filters):
        return self._request("GET", f"{API_PREFIX}/data-requests", _prune(filters), headers)

    def screen_data_request(self, request_id: str, headers, payload: Optional[Dict] = None):
        return self._request(
            "POST", f"{API_PREFIX}/data-requests/{request_id}/screen", payload or {}, headers
        )

    def release_data_request(self, request_id: str, headers, payload: Optional[Dict] = None):
        return self._request(
            "POST", f"{API_PREFIX}/data-requests/{request_id}/release", _prune(payload) or {}, headers
        )

    def add_disclosure_cell(self, request_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{API_PREFIX}/data-requests/{request_id}/cells", _prune(payload), headers
        )

    def get_disclosure_cell(self, cell_id: str, headers):
        return self._request("GET", f"{API_PREFIX}/disclosure-cells/{cell_id}", None, headers)

    def list_disclosure_cells(self, headers, **filters):
        return self._request("GET", f"{API_PREFIX}/disclosure-cells", _prune(filters), headers)
