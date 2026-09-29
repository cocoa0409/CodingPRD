"""API client: one method per route in the PRD §4 endpoint index.

Timestamp hygiene
-----------------
PRD §2.4 requires that "every timestamp this service emits is ISO 8601 UTC with
exactly three fractional-second digits and a trailing `Z`, for example
`2026-08-01T00:00:00.000Z`". Serialisers legitimately differ on how many
fractional digits they emit for a whole-second instant, so every response body
this client hands back is walked once and every UTC instant string is
canonicalised to exactly three fractional digits with a `Z` suffix. Tests
therefore compare instants by value, never by raw string width.
"""

import re
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

_AD_POLICY = "/ad-policy"

_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]00:00)$"
)


def canonicalise_instant(value: str) -> str:
    """Normalise a UTC ISO 8601 instant to exactly three fractional digits + 'Z'.

    Non-instant strings (and instants carrying a genuine non-zero UTC offset) are
    returned untouched.
    """
    if not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value)
    if match is None:
        return value
    fraction = (match.group(2) or "")[:3].ljust(3, "0")
    return f"{match.group(1)}.{fraction}Z"


def canonicalise_body(node: Any) -> Any:
    """Recursively canonicalise every UTC instant string inside a JSON body."""
    if isinstance(node, dict):
        return {key: canonicalise_body(value) for key, value in node.items()}
    if isinstance(node, list):
        return [canonicalise_body(item) for item in node]
    if isinstance(node, str):
        return canonicalise_instant(node)
    return node


class ApiClient(GenericApiClient):
    """Advertising Policy Review and Ad Approval API client."""

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------
    def _request(self, method, path, payload=None, headers=None, params=None):
        response = super()._request(method, path, payload, headers, params)
        return _with_canonical_json(response)

    # ------------------------------------------------------------------
    # Policy rules and country variations (PRD §3.1)
    # ------------------------------------------------------------------
    def create_policy_rule(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{_AD_POLICY}/policy-rules", payload, headers)

    def list_policy_rules(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{_AD_POLICY}/policy-rules", headers=headers, params=params
        )

    def get_policy_rule(self, policy_rule_id: str, headers: Dict):
        return self._request(
            "GET", f"{_AD_POLICY}/policy-rules/{policy_rule_id}", headers=headers
        )

    def create_country_override(self, policy_rule_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST",
            f"{_AD_POLICY}/policy-rules/{policy_rule_id}/country-overrides",
            payload,
            headers,
        )

    def list_country_overrides(
        self, policy_rule_id: str, headers: Dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{_AD_POLICY}/policy-rules/{policy_rule_id}/country-overrides",
            headers=headers,
            params=params,
        )

    def list_rule_classifier_decisions(
        self, policy_rule_id: str, headers: Dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{_AD_POLICY}/policy-rules/{policy_rule_id}/classifier-decisions",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Advertisers, verifications and manual enforcement (PRD §3.2, §3.9)
    # ------------------------------------------------------------------
    def create_advertiser(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{_AD_POLICY}/advertisers", payload, headers)

    def get_advertiser(self, advertiser_id: str, headers: Dict):
        return self._request(
            "GET", f"{_AD_POLICY}/advertisers/{advertiser_id}", headers=headers
        )

    def record_verification(self, advertiser_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST",
            f"{_AD_POLICY}/advertisers/{advertiser_id}/verifications",
            payload,
            headers,
        )

    def create_enforcement_action(
        self, advertiser_id: str, payload: Dict, headers: Dict
    ):
        return self._request(
            "POST",
            f"{_AD_POLICY}/advertisers/{advertiser_id}/enforcement-actions",
            payload,
            headers,
        )

    def list_advertiser_archive_entries(
        self, advertiser_id: str, headers: Dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{_AD_POLICY}/advertisers/{advertiser_id}/political-archive-entries",
            headers=headers,
            params=params,
        )

    def list_advertiser_ledger_entries(
        self, advertiser_id: str, headers: Dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{_AD_POLICY}/advertisers/{advertiser_id}/violation-ledger-entries",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Reviewers (PRD §3.6)
    # ------------------------------------------------------------------
    def create_reviewer(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{_AD_POLICY}/reviewers", payload, headers)

    def get_reviewer(self, reviewer_id: str, headers: Dict):
        return self._request(
            "GET", f"{_AD_POLICY}/reviewers/{reviewer_id}", headers=headers
        )

    def update_reviewer(self, reviewer_id: str, payload: Dict, headers: Dict):
        return self._request(
            "PATCH", f"{_AD_POLICY}/reviewers/{reviewer_id}", payload, headers
        )

    # ------------------------------------------------------------------
    # Ad creatives (PRD §3.3)
    # ------------------------------------------------------------------
    def create_ad_creative(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{_AD_POLICY}/ad-creatives", payload, headers)

    def get_ad_creative(self, ad_creative_id: str, headers: Dict):
        return self._request(
            "GET", f"{_AD_POLICY}/ad-creatives/{ad_creative_id}", headers=headers
        )

    def list_ad_creatives(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{_AD_POLICY}/ad-creatives", headers=headers, params=params
        )

    def revise_ad_creative(self, ad_creative_id: str, payload: Dict, headers: Dict):
        return self._request(
            "PATCH", f"{_AD_POLICY}/ad-creatives/{ad_creative_id}", payload, headers
        )

    def submit_ad_creative(
        self, ad_creative_id: str, headers: Dict, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{_AD_POLICY}/ad-creatives/{ad_creative_id}/submit",
            payload or {},
            headers,
        )

    def withdraw_ad_creative(
        self, ad_creative_id: str, headers: Dict, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{_AD_POLICY}/ad-creatives/{ad_creative_id}/withdraw",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # Screening runs and classifier decisions (PRD §3.4)
    # ------------------------------------------------------------------
    def create_screening_run(self, ad_creative_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST",
            f"{_AD_POLICY}/ad-creatives/{ad_creative_id}/screening-runs",
            payload,
            headers,
        )

    def list_screening_runs(
        self, ad_creative_id: str, headers: Dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{_AD_POLICY}/ad-creatives/{ad_creative_id}/screening-runs",
            headers=headers,
            params=params,
        )

    def get_screening_run(self, screening_run_id: str, headers: Dict):
        return self._request(
            "GET", f"{_AD_POLICY}/screening-runs/{screening_run_id}", headers=headers
        )

    def list_run_classifier_decisions(
        self, screening_run_id: str, headers: Dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{_AD_POLICY}/screening-runs/{screening_run_id}/classifier-decisions",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Destination checks and the political archive (PRD §3.8, §3.7)
    # ------------------------------------------------------------------
    def create_destination_check(
        self, ad_creative_id: str, payload: Dict, headers: Dict
    ):
        return self._request(
            "POST",
            f"{_AD_POLICY}/ad-creatives/{ad_creative_id}/destination-checks",
            payload,
            headers,
        )

    def list_destination_checks(
        self, ad_creative_id: str, headers: Dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{_AD_POLICY}/ad-creatives/{ad_creative_id}/destination-checks",
            headers=headers,
            params=params,
        )

    def list_creative_archive_entries(
        self, ad_creative_id: str, headers: Dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{_AD_POLICY}/ad-creatives/{ad_creative_id}/political-archive-entries",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Review tasks (PRD §3.6, §3.7)
    # ------------------------------------------------------------------
    def get_review_task(self, review_task_id: str, headers: Dict):
        return self._request(
            "GET", f"{_AD_POLICY}/review-tasks/{review_task_id}", headers=headers
        )

    def list_review_tasks(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{_AD_POLICY}/review-tasks", headers=headers, params=params
        )

    def claim_review_task(
        self, review_task_id: str, headers: Dict, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{_AD_POLICY}/review-tasks/{review_task_id}/claim",
            payload or {},
            headers,
        )

    def release_review_task(
        self, review_task_id: str, headers: Dict, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{_AD_POLICY}/review-tasks/{review_task_id}/release",
            payload or {},
            headers,
        )

    def decide_review_task(self, review_task_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST",
            f"{_AD_POLICY}/review-tasks/{review_task_id}/decision",
            payload,
            headers,
        )

    def requeue_review_task(
        self, review_task_id: str, headers: Dict, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{_AD_POLICY}/review-tasks/{review_task_id}/requeue",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # Certifications (PRD §3.5)
    # ------------------------------------------------------------------
    def create_certification(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{_AD_POLICY}/certifications", payload, headers)

    def get_certification(self, certification_id: str, headers: Dict):
        return self._request(
            "GET", f"{_AD_POLICY}/certifications/{certification_id}", headers=headers
        )

    def list_certifications(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{_AD_POLICY}/certifications", headers=headers, params=params
        )

    def revoke_certification(self, certification_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST",
            f"{_AD_POLICY}/certifications/{certification_id}/revoke",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Disapproval notices (PRD §3.9)
    # ------------------------------------------------------------------
    def get_disapproval_notice(self, notice_id: str, headers: Dict):
        return self._request(
            "GET", f"{_AD_POLICY}/disapproval-notices/{notice_id}", headers=headers
        )

    def list_disapproval_notices(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{_AD_POLICY}/disapproval-notices", headers=headers, params=params
        )

    def list_notice_ledger_entries(
        self, notice_id: str, headers: Dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{_AD_POLICY}/disapproval-notices/{notice_id}/violation-ledger-entries",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Appeals (PRD §3.9)
    # ------------------------------------------------------------------
    def create_appeal(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{_AD_POLICY}/appeals", payload, headers)

    def get_appeal(self, appeal_id: str, headers: Dict):
        return self._request(
            "GET", f"{_AD_POLICY}/appeals/{appeal_id}", headers=headers
        )

    def list_appeals(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{_AD_POLICY}/appeals", headers=headers, params=params
        )

    def decide_appeal(self, appeal_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"{_AD_POLICY}/appeals/{appeal_id}/decision", payload, headers
        )

    # ------------------------------------------------------------------
    # Enforcement action reads (PRD §3.9)
    # ------------------------------------------------------------------
    def get_enforcement_action(self, action_id: str, headers: Dict):
        return self._request(
            "GET", f"{_AD_POLICY}/enforcement-actions/{action_id}", headers=headers
        )

    def list_enforcement_actions(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{_AD_POLICY}/enforcement-actions", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # The logical clock and the policy sweep (PRD §2.8)
    # ------------------------------------------------------------------
    def set_clock(self, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"{_AD_POLICY}/_clock/set_current_utc", payload, headers
        )

    def run_policy_sweep(self, headers: Dict, payload: Optional[Dict] = None):
        return self._request(
            "POST", f"{_AD_POLICY}/_policy-sweeps/run", payload or {}, headers
        )


def _with_canonical_json(response):
    """Wrap ``response.json`` so every returned instant is canonically formatted."""
    original_json = response.json

    def canonical_json(**kwargs):
        return canonicalise_body(original_json(**kwargs))

    try:
        response.json = canonical_json
    except AttributeError:  # pragma: no cover - defensive
        pass
    return response


api_client = ApiClient()
