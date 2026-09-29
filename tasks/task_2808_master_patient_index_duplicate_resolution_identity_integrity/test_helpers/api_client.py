"""One client method per endpoint in the PRD's §4 endpoint table.

Every method returns the raw requests.Response so tests can assert on status
codes as well as on the response envelope.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import CLOCK_PATH, MPI


class MpiApiClient(GenericApiClient):
    """HTTP client for the Master Patient Index Identity Integrity API."""

    # ─── Logical clock ────────────────────────────────
    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._request(
            "POST", CLOCK_PATH, {"current_utc": current_utc}, headers
        )

    # ─── Registration sites ───────────────────────────
    def create_site(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{MPI}/registration-sites", payload, headers)

    def patch_site(self, site_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "PATCH", f"{MPI}/registration-sites/{site_id}", payload, headers
        )

    def get_site(self, site_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{MPI}/registration-sites/{site_id}", None, headers
        )

    # ─── Match rule sets ──────────────────────────────
    def create_rule_set(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{MPI}/match-rule-sets", payload, headers)

    def activate_rule_set(self, rule_set_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{MPI}/match-rule-sets/{rule_set_id}/activate", {}, headers
        )

    def get_rule_set(self, rule_set_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{MPI}/match-rule-sets/{rule_set_id}", None, headers
        )

    # ─── Registration search attempts ─────────────────
    def create_search_attempt(
        self, site_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{MPI}/registration-sites/{site_id}/search-attempts",
            payload,
            headers,
        )

    def list_search_attempts(
        self, site_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{MPI}/registration-sites/{site_id}/search-attempts",
            params,
            headers,
        )

    # ─── Patient records ──────────────────────────────
    def create_record(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{MPI}/patient-records", payload, headers)

    def get_record(self, record_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{MPI}/patient-records/{record_id}", None, headers)

    def list_records(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{MPI}/patient-records", params, headers)

    # ─── Candidate pairs ──────────────────────────────
    def create_pair(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{MPI}/candidate-pairs", payload, headers)

    def get_pair(self, pair_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{MPI}/candidate-pairs/{pair_id}", None, headers)

    def list_pairs(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{MPI}/candidate-pairs", params, headers)

    def rescore_pair(
        self, pair_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{MPI}/candidate-pairs/{pair_id}/rescore", payload, headers
        )

    def triage_pair(
        self, pair_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{MPI}/candidate-pairs/{pair_id}/triage", payload, headers
        )

    def start_review(self, pair_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{MPI}/candidate-pairs/{pair_id}/start-review", {}, headers
        )

    def add_evidence(
        self, pair_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{MPI}/candidate-pairs/{pair_id}/evidence", payload, headers
        )

    def list_evidence(
        self, pair_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{MPI}/candidate-pairs/{pair_id}/evidence", params, headers
        )

    def recommend(
        self, pair_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{MPI}/candidate-pairs/{pair_id}/recommend", payload, headers
        )

    def return_to_review(
        self, pair_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{MPI}/candidate-pairs/{pair_id}/return-to-review",
            payload,
            headers,
        )

    def resolve_distinct(
        self, pair_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{MPI}/candidate-pairs/{pair_id}/resolve-distinct",
            payload,
            headers,
        )

    # ─── Merge operations ─────────────────────────────
    def create_merge(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{MPI}/merge-operations", payload, headers)

    def get_merge(self, merge_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{MPI}/merge-operations/{merge_id}", None, headers)

    def list_merges(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{MPI}/merge-operations", params, headers)

    def unmerge(self, merge_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"{MPI}/merge-operations/{merge_id}/unmerge", payload, headers
        )

    # ─── Overlay corrections ──────────────────────────
    def create_overlay(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{MPI}/overlay-corrections", payload, headers)

    def get_overlay(self, overlay_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{MPI}/overlay-corrections/{overlay_id}", None, headers
        )

    def list_overlays(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{MPI}/overlay-corrections", params, headers)

    def apply_overlay(self, overlay_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{MPI}/overlay-corrections/{overlay_id}/apply", {}, headers
        )

    def complete_overlay(
        self, overlay_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{MPI}/overlay-corrections/{overlay_id}/complete",
            payload,
            headers,
        )

    # ─── Contamination remediations ───────────────────
    def get_remediation(self, remediation_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{MPI}/contamination-remediations/{remediation_id}", None, headers
        )

    def list_remediations(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{MPI}/contamination-remediations", params, headers
        )

    def quarantine(
        self, remediation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{MPI}/contamination-remediations/{remediation_id}/quarantine",
            payload,
            headers,
        )

    def reassign(
        self, remediation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{MPI}/contamination-remediations/{remediation_id}/reassign",
            payload,
            headers,
        )

    def close_remediation(
        self, remediation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{MPI}/contamination-remediations/{remediation_id}/close",
            payload,
            headers,
        )

    # ─── Downstream systems ───────────────────────────
    def create_system(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{MPI}/downstream-systems", payload, headers)

    def patch_system(
        self, system_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"{MPI}/downstream-systems/{system_id}", payload, headers
        )

    def get_system(self, system_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{MPI}/downstream-systems/{system_id}", None, headers
        )

    # ─── Propagation tasks ────────────────────────────
    def get_task(self, task_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{MPI}/propagation-tasks/{task_id}", None, headers
        )

    def list_tasks(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{MPI}/propagation-tasks", params, headers)

    def send_task(self, task_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"{MPI}/propagation-tasks/{task_id}/send", payload, headers
        )

    def ack_task(self, task_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{MPI}/propagation-tasks/{task_id}/ack", {}, headers
        )

    def fail_task(self, task_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"{MPI}/propagation-tasks/{task_id}/fail", payload, headers
        )

    # ─── Fraud investigations ─────────────────────────
    def create_investigation(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{MPI}/fraud-investigations", payload, headers)

    def get_investigation(self, investigation_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{MPI}/fraud-investigations/{investigation_id}", None, headers
        )

    def list_investigations(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", f"{MPI}/fraud-investigations", params, headers)

    def substantiate(
        self, investigation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{MPI}/fraud-investigations/{investigation_id}/substantiate",
            payload,
            headers,
        )

    def unsubstantiate(
        self, investigation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{MPI}/fraud-investigations/{investigation_id}/unsubstantiate",
            payload,
            headers,
        )

    def refer(
        self, investigation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{MPI}/fraud-investigations/{investigation_id}/refer",
            payload,
            headers,
        )

    # ─── External match requests ──────────────────────
    def create_external_match(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"{MPI}/external-match-requests", payload, headers
        )

    def get_external_match(self, request_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{MPI}/external-match-requests/{request_id}", None, headers
        )

    def list_external_matches(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", f"{MPI}/external-match-requests", params, headers)

    # ─── Duplicate metric runs ────────────────────────
    def create_metric_run(
        self, site_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{MPI}/registration-sites/{site_id}/duplicate-metric-runs",
            payload,
            headers,
        )

    def list_metric_runs(
        self, site_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{MPI}/registration-sites/{site_id}/duplicate-metric-runs",
            params,
            headers,
        )
