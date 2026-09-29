"""One client method per route of the PRD §4 endpoint table.

Two conventions are enforced here rather than in every test:

* Money and rate fields travel as JSON numbers.  §2.6: "All monetary amounts in
  this system are integer counts of cents" and "Any field whose name ends in
  `_bps` is an integer count of basis points", so the client refuses to send a
  string where the contract declares an integer.
* Instants travel with exactly three fractional digits.  §2.4 fixes the shape
  as "an ISO 8601 UTC timestamp with three fractional digits (for example
  `2026-08-01T00:00:00.000Z`)", so every instant-valued request field is
  canonicalised to that width before it leaves the client.
"""

import re
from typing import Any, Dict, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

from .constants import INSTANT_REQUEST_FIELDS

_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(Z|\+00:00)$"
)


def canonical_instant(value: Any) -> Any:
    """Render an ISO 8601 UTC instant with exactly three fractional digits."""
    if not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value)
    if not match:
        return value
    fraction = (match.group(2) or "")[:3].ljust(3, "0")
    return f"{match.group(1)}.{fraction}Z"


def _canonicalise(payload: Any) -> Any:
    """Canonicalise every instant-valued field inside a request payload."""
    if isinstance(payload, dict):
        canonical: Dict[str, Any] = {}
        for key, value in payload.items():
            if key in INSTANT_REQUEST_FIELDS:
                canonical[key] = canonical_instant(value)
            else:
                canonical[key] = _canonicalise(value)
        return canonical
    if isinstance(payload, list):
        return [_canonicalise(item) for item in payload]
    return payload


class AffiliateProgramApiClient(GenericApiClient):
    """Thin, typed wrapper over the affiliate program routes."""

    # ── plumbing ────────────────────────────────────────────────────────────

    def call(
        self,
        method: str,
        path: str,
        payload: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Send an arbitrary request; used by role and envelope probes."""
        return self._request(method, path, _canonicalise(payload), headers)

    def _post(self, path, payload, headers) -> requests.Response:
        return self._request("POST", path, _canonicalise(payload), headers)

    def _get(self, path, params, headers) -> requests.Response:
        return self._request("GET", path, _canonicalise(params or {}), headers)

    # ── §2.9 logical clock ──────────────────────────────────────────────────

    def set_clock(self, to_iso8601: str, headers) -> requests.Response:
        return self._post(
            "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ── §3.1 networks ───────────────────────────────────────────────────────

    def create_network(self, payload, headers) -> requests.Response:
        return self._post("/networks", payload, headers)

    def get_network(self, network_id, headers) -> requests.Response:
        return self._get(f"/networks/{network_id}", None, headers)

    # ── §3.1 partners ───────────────────────────────────────────────────────

    def create_affiliate(self, payload, headers) -> requests.Response:
        return self._post("/affiliates", payload, headers)

    def get_affiliate(self, affiliate_id, headers) -> requests.Response:
        return self._get(f"/affiliates/{affiliate_id}", None, headers)

    def list_affiliates(self, headers, params=None) -> requests.Response:
        return self._get("/affiliates", params, headers)

    def change_affiliate_status(self, affiliate_id, payload, headers):
        return self._post(
            f"/affiliates/{affiliate_id}/status-change", payload, headers
        )

    def list_monitoring_scans(self, affiliate_id, headers, params=None):
        return self._get(
            f"/affiliates/{affiliate_id}/monitoring-scans", params, headers
        )

    def list_tax_documents(self, affiliate_id, headers, params=None):
        return self._get(f"/affiliates/{affiliate_id}/tax-documents", params, headers)

    def file_tax_document(self, affiliate_id, payload, headers):
        return self._post(
            f"/affiliates/{affiliate_id}/tax-documents", payload, headers
        )

    def create_application(self, affiliate_id, payload, headers):
        return self._post(f"/affiliates/{affiliate_id}/applications", payload, headers)

    def create_tracking_link(self, affiliate_id, payload, headers):
        return self._post(
            f"/affiliates/{affiliate_id}/tracking-links", payload, headers
        )

    def list_tracking_links(self, affiliate_id, headers, params=None):
        return self._get(
            f"/affiliates/{affiliate_id}/tracking-links", params, headers
        )

    # ── §3.2 applications ───────────────────────────────────────────────────

    def get_application(self, application_id, headers) -> requests.Response:
        return self._get(f"/affiliate-applications/{application_id}", None, headers)

    def list_applications(self, headers, params=None) -> requests.Response:
        return self._get("/affiliate-applications", params, headers)

    def screen_application(self, application_id, payload, headers):
        return self._post(
            f"/affiliate-applications/{application_id}/screen", payload, headers
        )

    def decide_application(self, application_id, payload, headers):
        return self._post(
            f"/affiliate-applications/{application_id}/decide", payload, headers
        )

    def resubmit_application(self, application_id, payload, headers):
        return self._post(
            f"/affiliate-applications/{application_id}/resubmit", payload, headers
        )

    # ── §3.3 rate cards ─────────────────────────────────────────────────────

    def create_commission_policy(self, payload, headers) -> requests.Response:
        return self._post("/commission-policies", payload, headers)

    def get_commission_policy(self, policy_id, headers) -> requests.Response:
        return self._get(f"/commission-policies/{policy_id}", None, headers)

    def list_commission_policies(self, headers, params=None) -> requests.Response:
        return self._get("/commission-policies", params, headers)

    def activate_commission_policy(self, policy_id, payload, headers):
        return self._post(
            f"/commission-policies/{policy_id}/activate", payload, headers
        )

    # ── §3.4 tracking links and clicks ──────────────────────────────────────

    def get_tracking_link(self, link_id, headers) -> requests.Response:
        return self._get(f"/tracking-links/{link_id}", None, headers)

    def disable_tracking_link(self, link_id, payload, headers):
        return self._post(f"/tracking-links/{link_id}/disable", payload, headers)

    def ingest_click(self, link_id, payload, headers) -> requests.Response:
        return self._post(f"/tracking-links/{link_id}/clicks", payload, headers)

    def list_clicks(self, link_id, headers, params=None) -> requests.Response:
        return self._get(f"/tracking-links/{link_id}/clicks", params, headers)

    # ── §3.5 orders and attribution ─────────────────────────────────────────

    def create_conversion(self, payload, headers) -> requests.Response:
        return self._post("/conversions", payload, headers)

    def get_conversion(self, conversion_id, headers) -> requests.Response:
        return self._get(f"/conversions/{conversion_id}", None, headers)

    def list_conversions(self, headers, params=None) -> requests.Response:
        return self._get("/conversions", params, headers)

    def attribute_conversion(self, conversion_id, payload, headers):
        return self._post(f"/conversions/{conversion_id}/attribute", payload, headers)

    def adjust_order(self, conversion_id, payload, headers) -> requests.Response:
        return self._post(
            f"/conversions/{conversion_id}/order-adjustment", payload, headers
        )

    def list_attribution_decisions(self, conversion_id, headers, params=None):
        return self._get(
            f"/conversions/{conversion_id}/attribution-decisions", params, headers
        )

    # ── §3.7 monitoring and violation cases ─────────────────────────────────

    def create_monitoring_scan(self, payload, headers) -> requests.Response:
        return self._post("/monitoring-scans", payload, headers)

    def create_violation_case(self, payload, headers) -> requests.Response:
        return self._post("/policy-violation-cases", payload, headers)

    def get_violation_case(self, case_id, headers) -> requests.Response:
        return self._get(f"/policy-violation-cases/{case_id}", None, headers)

    def list_violation_cases(self, headers, params=None) -> requests.Response:
        return self._get("/policy-violation-cases", params, headers)

    def transition_violation_case(self, case_id, payload, headers):
        return self._post(
            f"/policy-violation-cases/{case_id}/transition", payload, headers
        )

    # ── §3.8 tax documents ──────────────────────────────────────────────────

    def verify_tax_document(self, document_id, payload, headers):
        return self._post(f"/tax-documents/{document_id}/verify", payload, headers)

    # ── §3.6 ledger ─────────────────────────────────────────────────────────

    def get_ledger_entry(self, entry_id, headers) -> requests.Response:
        return self._get(f"/commission-ledger-entries/{entry_id}", None, headers)

    def list_ledger_entries(self, headers, params=None) -> requests.Response:
        return self._get("/commission-ledger-entries", params, headers)

    # ── §3.9 settlement ─────────────────────────────────────────────────────

    def create_payout_batch(self, payload, headers) -> requests.Response:
        return self._post("/payout-batches", payload, headers)

    def get_payout_batch(self, batch_id, headers) -> requests.Response:
        return self._get(f"/payout-batches/{batch_id}", None, headers)

    def list_payout_batches(self, headers, params=None) -> requests.Response:
        return self._get("/payout-batches", params, headers)

    def validate_payout_batch(self, batch_id, payload, headers):
        return self._post(f"/payout-batches/{batch_id}/validate", payload, headers)

    def approve_payout_batch(self, batch_id, payload, headers):
        return self._post(f"/payout-batches/{batch_id}/approve", payload, headers)

    def pay_payout_batch(self, batch_id, payload, headers):
        return self._post(f"/payout-batches/{batch_id}/pay", payload, headers)

    def void_payout_batch(self, batch_id, payload, headers):
        return self._post(f"/payout-batches/{batch_id}/void", payload, headers)

    def get_payout_line(self, line_id, headers) -> requests.Response:
        return self._get(f"/payout-lines/{line_id}", None, headers)

    def list_payout_lines(self, headers, params=None) -> requests.Response:
        return self._get("/payout-lines", params, headers)

    def release_hold(self, line_id, payload, headers) -> requests.Response:
        return self._post(f"/payout-lines/{line_id}/release-hold", payload, headers)
