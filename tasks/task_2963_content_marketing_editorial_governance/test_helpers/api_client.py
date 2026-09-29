"""
Endpoint client for the Content Marketing Editorial Governance API.

One method per row of the PRD's endpoint table, all rooted at the
``/editorial`` prefix. Every method returns the raw response so tests can
assert both status codes and envelope contents.

The module also owns instant canonicalisation. The PRD renders every
timestamp as an ISO 8601 UTC instant with exactly three fractional digits,
so comparisons go through :func:`canonical_instant` here rather than being
re-normalised in individual tests.
"""

import re
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX

_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:?\d{2})$"
)


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """
    Normalise an ISO 8601 UTC instant to exactly three fractional digits.

    ``None`` passes through untouched, as do strings that are not instants
    (a ``YYYY-MM-DD`` slot week date, for example). A sub-second field that is
    shorter than three digits is right-padded and one that is longer is
    truncated, so ``2026-08-01T00:00:00Z`` and ``2026-08-01T00:00:00.000000Z``
    both canonicalise to ``2026-08-01T00:00:00.000Z``.
    """
    if not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value)
    if not match:
        return value
    date_part, time_part, fraction, _offset = match.groups()
    fraction = (fraction or "")[:3].ljust(3, "0")
    return f"{date_part}T{time_part}.{fraction}Z"


def instants_equal(left: Optional[str], right: Optional[str]) -> bool:
    """Compare two instants after canonicalising both to three fractional digits."""
    return canonical_instant(left) == canonical_instant(right)


class ApiClient(GenericApiClient):
    """Typed endpoint surface for the editorial governance service."""

    # ─── Logical clock (PRD 2.4) ──────────────────────

    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{API_PREFIX}/_clock/set_current_utc",
            {"current_utc": current_utc},
            headers,
        )

    def set_clock_raw(self, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/_clock/set_current_utc", payload, headers
        )

    # ─── Governance sweep (PRD 3.11) ──────────────────

    def run_governance_sweep(self, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/_ops/governance-sweep", {}, headers
        )

    # ─── Campaigns (PRD 3.1) ──────────────────────────

    def create_campaign(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/campaigns", payload, headers)

    def activate_campaign(self, campaign_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/campaigns/{campaign_id}/activate", {}, headers
        )

    def close_campaign(self, campaign_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/campaigns/{campaign_id}/close", {}, headers
        )

    def list_campaigns(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/campaigns", headers=headers, params=params
        )

    def get_campaign(self, campaign_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/campaigns/{campaign_id}", headers=headers
        )

    # ─── Calendar slots (PRD 3.1) ─────────────────────

    def create_calendar_slot(
        self, campaign_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/campaigns/{campaign_id}/calendar-slots",
            payload,
            headers,
        )

    def list_campaign_calendar_slots(
        self, campaign_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/campaigns/{campaign_id}/calendar-slots",
            headers=headers,
            params=params,
        )

    def list_calendar_slots(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/calendar-slots", headers=headers, params=params
        )

    def get_calendar_slot(self, slot_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/calendar-slots/{slot_id}", headers=headers
        )

    def lock_calendar_slot(self, slot_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/calendar-slots/{slot_id}/lock", {}, headers
        )

    # ─── Experts (PRD 3.2) ────────────────────────────

    def create_expert(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/experts", payload, headers)

    def set_expert_availability(
        self, expert_id: str, status: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/experts/{expert_id}/availability",
            {"status": status},
            headers,
        )

    def set_expert_availability_raw(
        self, expert_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/experts/{expert_id}/availability", payload, headers
        )

    def list_experts(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/experts", headers=headers, params=params
        )

    def get_expert(self, expert_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/experts/{expert_id}", headers=headers
        )

    # ─── Briefs (PRD 3.3) ─────────────────────────────

    def create_brief(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/briefs", payload, headers)

    def assign_sme(self, brief_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/briefs/{brief_id}/assign-sme", payload, headers
        )

    def approve_brief(
        self, brief_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"{API_PREFIX}/briefs/{brief_id}/approve", payload or {}, headers
        )

    def request_brief_changes(
        self, brief_id: str, headers: Dict[str, str], notes: Optional[str] = None
    ):
        payload: Dict[str, Any] = {}
        if notes is not None:
            payload["notes"] = notes
        return self._request(
            "POST",
            f"{API_PREFIX}/briefs/{brief_id}/request-changes",
            payload,
            headers,
        )

    def list_briefs(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/briefs", headers=headers, params=params
        )

    def get_brief(self, brief_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{API_PREFIX}/briefs/{brief_id}", headers=headers)

    # ─── Content items (PRD 3.4) ──────────────────────

    def create_content_item(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/content-items", payload, headers)

    def submit_for_review(self, item_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{API_PREFIX}/content-items/{item_id}/submit-for-review",
            {},
            headers,
        )

    def publish_content_item(self, item_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/content-items/{item_id}/publish", payload, headers
        )

    def retract_content_item(
        self, item_id: str, headers: Dict[str, str], reason: Optional[str] = None
    ):
        payload: Dict[str, Any] = {}
        if reason is not None:
            payload["reason"] = reason
        return self._request(
            "POST", f"{API_PREFIX}/content-items/{item_id}/retract", payload, headers
        )

    def audit_content_item(self, item_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/content-items/{item_id}/audit", payload, headers
        )

    def refresh_content_item(self, item_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/content-items/{item_id}/refresh", {}, headers
        )

    def prune_content_item(self, item_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/content-items/{item_id}/prune", {}, headers
        )

    def list_content_items(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/content-items", headers=headers, params=params
        )

    def get_content_item(self, item_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/content-items/{item_id}", headers=headers
        )

    # ─── Claims and evidence (PRD 3.6) ────────────────

    def create_claim(self, item_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/content-items/{item_id}/claims", payload, headers
        )

    def list_item_claims(
        self, item_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/content-items/{item_id}/claims",
            headers=headers,
            params=params,
        )

    def get_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{API_PREFIX}/claims/{claim_id}", headers=headers)

    def file_evidence(self, claim_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/claims/{claim_id}/evidence", payload, headers
        )

    def list_claim_evidence(
        self, claim_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/claims/{claim_id}/evidence",
            headers=headers,
            params=params,
        )

    def decide_claim(
        self,
        claim_id: str,
        decision: str,
        headers: Dict[str, str],
        notes: Optional[str] = None,
    ):
        payload: Dict[str, Any] = {"decision": decision}
        if notes is not None:
            payload["decision_notes"] = notes
        return self._request(
            "POST", f"{API_PREFIX}/claims/{claim_id}/decide", payload, headers
        )

    def decide_claim_raw(self, claim_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/claims/{claim_id}/decide", payload, headers
        )

    # ─── Review gates (PRD 3.5) ───────────────────────

    def list_review_gates(
        self, item_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/content-items/{item_id}/review-gates",
            headers=headers,
            params=params,
        )

    def get_review_gate(self, gate_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/review-gates/{gate_id}", headers=headers
        )

    def decide_review_gate(
        self,
        gate_id: str,
        decision: str,
        headers: Dict[str, str],
        decision_notes: Optional[str] = None,
    ):
        payload: Dict[str, Any] = {"decision": decision}
        if decision_notes is not None:
            payload["decision_notes"] = decision_notes
        return self._request(
            "POST", f"{API_PREFIX}/review-gates/{gate_id}/decide", payload, headers
        )

    def decide_review_gate_raw(
        self, gate_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/review-gates/{gate_id}/decide", payload, headers
        )

    # ─── Assets and usages (PRD 3.7) ──────────────────

    def create_asset(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/assets", payload, headers)

    def renew_asset(
        self, asset_id: str, new_license_end: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/assets/{asset_id}/renew",
            {"new_license_end": new_license_end},
            headers,
        )

    def renew_asset_raw(self, asset_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/assets/{asset_id}/renew", payload, headers
        )

    def list_assets(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/assets", headers=headers, params=params
        )

    def get_asset(self, asset_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{API_PREFIX}/assets/{asset_id}", headers=headers)

    def list_asset_usages(
        self, asset_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/assets/{asset_id}/usages",
            headers=headers,
            params=params,
        )

    def attach_asset_usage(self, item_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{API_PREFIX}/content-items/{item_id}/asset-usages",
            payload,
            headers,
        )

    def list_item_asset_usages(
        self, item_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/content-items/{item_id}/asset-usages",
            headers=headers,
            params=params,
        )

    # ─── Distributions (PRD 3.8) ──────────────────────

    def list_distributions(
        self, item_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/content-items/{item_id}/distributions",
            headers=headers,
            params=params,
        )

    # ─── Measurement (PRD 3.9) ────────────────────────

    def create_performance_snapshot(
        self, item_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/content-items/{item_id}/performance-snapshots",
            payload,
            headers,
        )

    def list_performance_snapshots(
        self, item_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/content-items/{item_id}/performance-snapshots",
            headers=headers,
            params=params,
        )

    # ─── Generic helpers ──────────────────────────────

    def get_path(
        self, path: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        """GET an arbitrary path under the service prefix."""
        return self._request("GET", f"{API_PREFIX}{path}", headers=headers, params=params)

    def post_path(self, path: str, payload: Any, headers: Dict[str, str]):
        """POST to an arbitrary path under the service prefix."""
        return self._request("POST", f"{API_PREFIX}{path}", payload, headers)


__all__: List[str] = ["ApiClient", "canonical_instant", "instants_equal"]
