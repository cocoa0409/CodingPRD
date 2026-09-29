"""One method per endpoint of PRD §4, plus instant canonicalisation.

PRD §2.4 requires every system-recorded instant to be "ISO 8601 UTC with three
fractional digits". Servers legitimately differ in how they spell an equivalent
instant (`Z` versus `+00:00`, six fractional digits versus three), and comparing
raw strings would turn one formatting choice into dozens of unrelated failures.
Every response body is therefore canonicalised here — instants are rewritten to
`YYYY-MM-DDTHH:MM:SS.mmmZ` — while the untouched parse stays reachable through
`original_json()` for the tests that assert the wire format itself.
"""

import copy
import json
import re
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import GenericApiClient

_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(\.\d+)?(Z|z|[+-]\d{2}:?\d{2})$"
)


def canonicalize_instant(value: str) -> str:
    """Rewrite one ISO 8601 UTC instant to exactly three fractional digits and `Z`."""
    match = _INSTANT_RE.match(value)
    if not match:
        return value
    date_part, time_part, fraction, offset = match.groups()
    if offset not in ("Z", "z", "+00:00", "-00:00", "+0000", "-0000"):
        return value
    digits = (fraction or ".")[1:]
    digits = (digits + "000")[:3]
    return f"{date_part}T{time_part}.{digits}Z"


def _canonicalize(node: Any) -> Any:
    if isinstance(node, str):
        return canonicalize_instant(node)
    if isinstance(node, list):
        return [_canonicalize(item) for item in node]
    if isinstance(node, dict):
        return {key: _canonicalize(value) for key, value in node.items()}
    return node


def original_json(response) -> Any:
    """The response body exactly as the server spelled it, before canonicalisation."""
    stashed = getattr(response, "original_json_body", None)
    if stashed is not None:
        return stashed
    return response.json()


def original_data(response) -> Any:
    """The `data` payload exactly as the server spelled it."""
    return original_json(response)["data"]


class ApiClient(GenericApiClient):
    """Typed wrapper over the endpoints published in PRD §4."""

    def _request(self, method, path, payload=None, headers=None, params=None):
        response = super()._request(method, path, payload, headers, params)
        try:
            body = response.json()
        except Exception:
            return response
        response.original_json_body = copy.deepcopy(body)
        canonical = _canonicalize(body)
        response._content = json.dumps(canonical).encode("utf-8")
        return response

    # ------------------------------------------------------------------ studios
    def create_studio(self, payload: Dict, headers: Dict) -> Any:
        return self._request("POST", "/studios", payload, headers)

    def get_studio(self, studio_id: str, headers: Dict) -> Any:
        return self._request("GET", f"/studios/{studio_id}", None, headers)

    # --------------------------------------------------------------- publishers
    def create_publisher(self, payload: Dict, headers: Dict) -> Any:
        return self._request("POST", "/publishers", payload, headers)

    def get_publisher(self, publisher_id: str, headers: Dict) -> Any:
        return self._request("GET", f"/publishers/{publisher_id}", None, headers)

    # ---------------------------------------------------------- publisher users
    def create_publisher_user(self, payload: Dict, headers: Dict) -> Any:
        return self._request("POST", "/publisher-users", payload, headers)

    def get_publisher_user(self, user_id: str, headers: Dict) -> Any:
        return self._request("GET", f"/publisher-users/{user_id}", None, headers)

    def list_publisher_users(self, headers: Dict, params: Optional[Dict] = None) -> Any:
        return self._request("GET", "/publisher-users", params, headers)

    # ----------------------------------------------------------- agreements
    def create_agreement(self, payload: Dict, headers: Dict) -> Any:
        return self._request("POST", "/development-agreements", payload, headers)

    def get_agreement(self, agreement_id: str, headers: Dict) -> Any:
        return self._request(
            "GET", f"/development-agreements/{agreement_id}", None, headers
        )

    def list_agreements(self, headers: Dict, params: Optional[Dict] = None) -> Any:
        return self._request("GET", "/development-agreements", params, headers)

    def activate_agreement(
        self, agreement_id: str, headers: Dict, payload: Optional[Dict] = None
    ) -> Any:
        return self._request(
            "POST", f"/development-agreements/{agreement_id}/activate", payload or {}, headers
        )

    def suspend_agreement(
        self, agreement_id: str, headers: Dict, payload: Optional[Dict] = None
    ) -> Any:
        return self._request(
            "POST", f"/development-agreements/{agreement_id}/suspend", payload or {}, headers
        )

    def reinstate_agreement(
        self, agreement_id: str, headers: Dict, payload: Optional[Dict] = None
    ) -> Any:
        return self._request(
            "POST", f"/development-agreements/{agreement_id}/reinstate", payload or {}, headers
        )

    def terminate_agreement(
        self, agreement_id: str, headers: Dict, payload: Optional[Dict] = None
    ) -> Any:
        return self._request(
            "POST", f"/development-agreements/{agreement_id}/terminate", payload or {}, headers
        )

    def cure_sweep(
        self, agreement_id: str, headers: Dict, payload: Optional[Dict] = None
    ) -> Any:
        return self._request(
            "POST", f"/development-agreements/{agreement_id}/cure-sweep", payload or {}, headers
        )

    def create_live_ops_draw(self, agreement_id: str, payload: Dict, headers: Dict) -> Any:
        return self._request(
            "POST", f"/development-agreements/{agreement_id}/live-ops-draws", payload, headers
        )

    def get_recoupment_summary(self, agreement_id: str, headers: Dict) -> Any:
        return self._request(
            "GET", f"/development-agreements/{agreement_id}/recoupment-summary", None, headers
        )

    def list_agreement_royalty_statements(
        self, agreement_id: str, headers: Dict, params: Optional[Dict] = None
    ) -> Any:
        return self._request(
            "GET", f"/development-agreements/{agreement_id}/royalty-statements", params, headers
        )

    # ------------------------------------------------------------- milestones
    def create_milestone(self, payload: Dict, headers: Dict) -> Any:
        return self._request("POST", "/milestones", payload, headers)

    def get_milestone(self, milestone_id: str, headers: Dict) -> Any:
        return self._request("GET", f"/milestones/{milestone_id}", None, headers)

    def list_milestones(self, headers: Dict, params: Optional[Dict] = None) -> Any:
        return self._request("GET", "/milestones", params, headers)

    def get_budget_summary(self, milestone_id: str, headers: Dict) -> Any:
        return self._request(
            "GET", f"/milestones/{milestone_id}/budget-summary", None, headers
        )

    def list_milestone_builds(
        self, milestone_id: str, headers: Dict, params: Optional[Dict] = None
    ) -> Any:
        return self._request("GET", f"/milestones/{milestone_id}/builds", params, headers)

    # ----------------------------------------------------------------- builds
    def create_build(self, payload: Dict, headers: Dict) -> Any:
        return self._request("POST", "/milestone-builds", payload, headers)

    def get_build(self, build_id: str, headers: Dict) -> Any:
        return self._request("GET", f"/milestone-builds/{build_id}", None, headers)

    # ---------------------------------------------------------------- reviews
    def create_review(self, payload: Dict, headers: Dict) -> Any:
        return self._request("POST", "/publisher-reviews", payload, headers)

    def get_review(self, review_id: str, headers: Dict) -> Any:
        return self._request("GET", f"/publisher-reviews/{review_id}", None, headers)

    def list_reviews(self, headers: Dict, params: Optional[Dict] = None) -> Any:
        return self._request("GET", "/publisher-reviews", params, headers)

    # --------------------------------------------------------------- payments
    def get_payment(self, payment_id: str, headers: Dict) -> Any:
        return self._request("GET", f"/milestone-payments/{payment_id}", None, headers)

    def list_payments(self, headers: Dict, params: Optional[Dict] = None) -> Any:
        return self._request("GET", "/milestone-payments", params, headers)

    def authorize_payment(
        self, payment_id: str, headers: Dict, payload: Optional[Dict] = None
    ) -> Any:
        return self._request(
            "POST", f"/milestone-payments/{payment_id}/authorize", payload or {}, headers
        )

    # ---------------------------------------------------------- change orders
    def create_change_order(self, payload: Dict, headers: Dict) -> Any:
        return self._request("POST", "/change-orders", payload, headers)

    def get_change_order(self, order_id: str, headers: Dict) -> Any:
        return self._request("GET", f"/change-orders/{order_id}", None, headers)

    def list_change_orders(self, headers: Dict, params: Optional[Dict] = None) -> Any:
        return self._request("GET", "/change-orders", params, headers)

    def decide_change_order(self, order_id: str, payload: Dict, headers: Dict) -> Any:
        return self._request("POST", f"/change-orders/{order_id}/decide", payload, headers)

    # ------------------------------------------------------------ engagements
    def create_engagement(self, payload: Dict, headers: Dict) -> Any:
        return self._request("POST", "/contractor-engagements", payload, headers)

    def get_engagement(self, engagement_id: str, headers: Dict) -> Any:
        return self._request(
            "GET", f"/contractor-engagements/{engagement_id}", None, headers
        )

    def list_engagements(self, headers: Dict, params: Optional[Dict] = None) -> Any:
        return self._request("GET", "/contractor-engagements", params, headers)

    def complete_engagement(
        self, engagement_id: str, headers: Dict, payload: Optional[Dict] = None
    ) -> Any:
        return self._request(
            "POST", f"/contractor-engagements/{engagement_id}/complete", payload or {}, headers
        )

    def cancel_engagement(
        self, engagement_id: str, headers: Dict, payload: Optional[Dict] = None
    ) -> Any:
        return self._request(
            "POST", f"/contractor-engagements/{engagement_id}/cancel", payload or {}, headers
        )

    def list_engagement_invoices(
        self, engagement_id: str, headers: Dict, params: Optional[Dict] = None
    ) -> Any:
        return self._request(
            "GET", f"/contractor-engagements/{engagement_id}/invoices", params, headers
        )

    # --------------------------------------------------------------- invoices
    def create_invoice(self, payload: Dict, headers: Dict) -> Any:
        return self._request("POST", "/contractor-invoices", payload, headers)

    def get_invoice(self, invoice_id: str, headers: Dict) -> Any:
        return self._request("GET", f"/contractor-invoices/{invoice_id}", None, headers)

    def decide_invoice(self, invoice_id: str, payload: Dict, headers: Dict) -> Any:
        return self._request(
            "POST", f"/contractor-invoices/{invoice_id}/decide", payload, headers
        )

    # ------------------------------------------------------ royalty statements
    def create_royalty_statement(self, payload: Dict, headers: Dict) -> Any:
        return self._request("POST", "/royalty-statements", payload, headers)

    def get_royalty_statement(self, statement_id: str, headers: Dict) -> Any:
        return self._request("GET", f"/royalty-statements/{statement_id}", None, headers)

    def finalize_royalty_statement(
        self, statement_id: str, headers: Dict, payload: Optional[Dict] = None
    ) -> Any:
        return self._request(
            "POST", f"/royalty-statements/{statement_id}/finalize", payload or {}, headers
        )

    # ------------------------------------------------------------ logical clock
    def set_clock(self, current_utc: str, headers: Dict) -> Any:
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ------------------------------------------------------------- raw helpers
    def get_path(self, path: str, headers: Dict, params: Optional[Dict] = None) -> Any:
        return self._request("GET", path, params, headers)

    def post_path(self, path: str, payload: Optional[Dict], headers: Dict) -> Any:
        return self._request("POST", path, payload, headers)
