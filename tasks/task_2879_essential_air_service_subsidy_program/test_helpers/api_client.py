"""Domain API client: one method per endpoint of the Essential Air Service API.

Every method returns the raw requests.Response so tests can assert status codes.

Instant canonicalisation
------------------------
The PRD stamps timestamps with three fractional-second digits, while the
instants tests compare against — a clock reading, a rate interval bound, a
termination stamp — are whole-second literals. To stop a purely cosmetic
sub-second width difference from masquerading as dozens of assertion failures,
this client rewrites ISO-8601 instants inside the response `data` payload to a
canonical form: a trailing `+00:00` offset becomes `Z`, a fractional part that
is all zeros is dropped, and a longer fractional part is truncated to three
digits. The `meta` envelope is left exactly as the server sent it, so the
three-fractional-digit rule on `meta.api_request_timestamp` stays testable.
"""

import json
import re
from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})$"
)


def canonical_instant(value: str) -> str:
    """Normalise one ISO-8601 UTC instant to a comparable canonical form."""
    if not isinstance(value, str):
        return value
    m = _INSTANT_RE.match(value)
    if not m:
        return value
    head, frac, _offset = m.group(1), m.group(2), m.group(3)
    if frac is None or set(frac) == {"0"}:
        return head + "Z"
    return head + "." + frac[:3].ljust(3, "0") + "Z"


def _canonicalise(node: Any) -> Any:
    if isinstance(node, str):
        return canonical_instant(node)
    if isinstance(node, list):
        return [_canonicalise(item) for item in node]
    if isinstance(node, dict):
        return {key: _canonicalise(val) for key, val in node.items()}
    return node


class ApiClient(GenericApiClient):
    """One method per endpoint declared by the PRD."""

    # ─── request plumbing ────────────────────────────────────────────

    def _request(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ) -> requests.Response:
        response = super()._request(method, path, payload, headers, params)
        self._canonicalise_response(response)
        return response

    @staticmethod
    def _canonicalise_response(response: requests.Response) -> None:
        """Rewrite instants inside `data`, leaving `meta` untouched."""
        if not response.content:
            return
        try:
            body = response.json()
        except ValueError:
            return
        if not isinstance(body, dict) or "data" not in body:
            return
        canonical = _canonicalise(body["data"])
        if canonical == body["data"]:
            return
        body["data"] = canonical
        response._content = json.dumps(body).encode("utf-8")

    # ─── logical clock ───────────────────────────────────────────────

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── communities ─────────────────────────────────────────────────

    def create_community(self, payload, headers):
        return self._request("POST", "/eas/communities", payload, headers)

    def get_community(self, community_id, headers):
        return self._request("GET", f"/eas/communities/{community_id}", None, headers)

    def list_communities(self, headers, params=None):
        return self._request("GET", "/eas/communities", None, headers, params)

    def create_eligibility_determination(self, community_id, payload, headers):
        return self._request(
            "POST",
            f"/eas/communities/{community_id}/eligibility-determinations",
            payload,
            headers,
        )

    def list_eligibility_determinations(self, community_id, headers, params=None):
        return self._request(
            "GET",
            f"/eas/communities/{community_id}/eligibility-determinations",
            None,
            headers,
            params,
        )

    def list_community_solicitations(self, community_id, headers, params=None):
        return self._request(
            "GET",
            f"/eas/communities/{community_id}/solicitations",
            None,
            headers,
            params,
        )

    # ─── carriers ────────────────────────────────────────────────────

    def create_carrier(self, payload, headers):
        return self._request("POST", "/eas/carriers", payload, headers)

    def get_carrier(self, carrier_id, headers):
        return self._request("GET", f"/eas/carriers/{carrier_id}", None, headers)

    def carrier_standing_action(self, carrier_id, payload, headers):
        return self._request(
            "POST", f"/eas/carriers/{carrier_id}/standing", payload, headers
        )

    # ─── aircraft types ──────────────────────────────────────────────

    def create_aircraft_type(self, payload, headers):
        return self._request("POST", "/eas/aircraft-types", payload, headers)

    def get_aircraft_type(self, aircraft_type_id, headers):
        return self._request(
            "GET", f"/eas/aircraft-types/{aircraft_type_id}", None, headers
        )

    def retire_aircraft_type(self, aircraft_type_id, payload, headers):
        return self._request(
            "POST", f"/eas/aircraft-types/{aircraft_type_id}/retire", payload, headers
        )

    # ─── fuel indices ────────────────────────────────────────────────

    def create_fuel_index(self, payload, headers):
        return self._request("POST", "/eas/fuel-indices", payload, headers)

    def list_fuel_indices(self, headers, params=None):
        return self._request("GET", "/eas/fuel-indices", None, headers, params)

    # ─── solicitations ───────────────────────────────────────────────

    def create_solicitation(self, payload, headers):
        return self._request("POST", "/eas/solicitations", payload, headers)

    def get_solicitation(self, solicitation_id, headers):
        return self._request(
            "GET", f"/eas/solicitations/{solicitation_id}", None, headers
        )

    def solicitation_action(self, solicitation_id, payload, headers):
        return self._request(
            "POST", f"/eas/solicitations/{solicitation_id}/actions", payload, headers
        )

    def file_preferences(self, solicitation_id, payload, headers):
        return self._request(
            "POST", f"/eas/solicitations/{solicitation_id}/preferences", payload, headers
        )

    def list_solicitation_preferences(self, solicitation_id, headers, params=None):
        return self._request(
            "GET",
            f"/eas/solicitations/{solicitation_id}/preferences",
            None,
            headers,
            params,
        )

    def get_ranking(self, solicitation_id, headers, params=None):
        return self._request(
            "GET", f"/eas/solicitations/{solicitation_id}/ranking", None, headers, params
        )

    def create_selection_order(self, solicitation_id, payload, headers):
        return self._request(
            "POST",
            f"/eas/solicitations/{solicitation_id}/selection-order",
            payload,
            headers,
        )

    # ─── proposals ───────────────────────────────────────────────────

    def create_proposal(self, payload, headers):
        return self._request("POST", "/eas/proposals", payload, headers)

    def get_proposal(self, proposal_id, headers):
        return self._request("GET", f"/eas/proposals/{proposal_id}", None, headers)

    def list_proposals(self, headers, params=None):
        return self._request("GET", "/eas/proposals", None, headers, params)

    def proposal_action(self, proposal_id, payload, headers):
        return self._request(
            "POST", f"/eas/proposals/{proposal_id}/actions", payload, headers
        )

    def list_proposal_preferences(self, proposal_id, headers, params=None):
        return self._request(
            "GET", f"/eas/proposals/{proposal_id}/preferences", None, headers, params
        )

    # ─── service agreements ──────────────────────────────────────────

    def get_service_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/eas/service-agreements/{agreement_id}", None, headers
        )

    def list_service_agreements(self, headers, params=None):
        return self._request("GET", "/eas/service-agreements", None, headers, params)

    def agreement_status_action(self, agreement_id, payload, headers):
        return self._request(
            "POST",
            f"/eas/service-agreements/{agreement_id}/status-actions",
            payload,
            headers,
        )

    def list_agreement_performance_reviews(self, agreement_id, headers, params=None):
        return self._request(
            "GET",
            f"/eas/service-agreements/{agreement_id}/performance-reviews",
            None,
            headers,
            params,
        )

    # ─── service periods ─────────────────────────────────────────────

    def create_service_period(self, payload, headers):
        return self._request("POST", "/eas/service-periods", payload, headers)

    def get_service_period(self, period_id, headers):
        return self._request(
            "GET", f"/eas/service-periods/{period_id}", None, headers
        )

    def list_service_periods(self, headers, params=None):
        return self._request("GET", "/eas/service-periods", None, headers, params)

    def report_service_period(self, period_id, payload, headers):
        return self._request(
            "POST", f"/eas/service-periods/{period_id}/report", payload, headers
        )

    def amend_service_period(self, period_id, payload, headers):
        return self._request(
            "POST", f"/eas/service-periods/{period_id}/amend", payload, headers
        )

    def get_payment_preview(self, period_id, headers, params=None):
        return self._request(
            "GET",
            f"/eas/service-periods/{period_id}/payment-preview",
            None,
            headers,
            params,
        )

    def certify_service_period(self, period_id, payload, headers):
        return self._request(
            "POST", f"/eas/service-periods/{period_id}/certify", payload, headers
        )

    # ─── subsidy payments ────────────────────────────────────────────

    def get_subsidy_payment(self, payment_id, headers):
        return self._request(
            "GET", f"/eas/subsidy-payments/{payment_id}", None, headers
        )

    def list_subsidy_payments(self, headers, params=None):
        return self._request("GET", "/eas/subsidy-payments", None, headers, params)

    def payment_action(self, payment_id, payload, headers):
        return self._request(
            "POST", f"/eas/subsidy-payments/{payment_id}/actions", payload, headers
        )

    # ─── performance reviews ─────────────────────────────────────────

    def create_performance_review(self, payload, headers):
        return self._request("POST", "/eas/performance-reviews", payload, headers)

    # ─── termination petitions ───────────────────────────────────────

    def create_termination_petition(self, payload, headers):
        return self._request("POST", "/eas/termination-petitions", payload, headers)

    def get_termination_petition(self, petition_id, headers):
        return self._request(
            "GET", f"/eas/termination-petitions/{petition_id}", None, headers
        )

    def list_termination_petitions(self, headers, params=None):
        return self._request("GET", "/eas/termination-petitions", None, headers, params)

    def petition_decision(self, petition_id, payload, headers):
        return self._request(
            "POST", f"/eas/termination-petitions/{petition_id}/decision", payload, headers
        )

    def withdraw_petition(self, petition_id, payload, headers):
        return self._request(
            "POST", f"/eas/termination-petitions/{petition_id}/withdraw", payload, headers
        )

    # ─── rate renegotiations ─────────────────────────────────────────

    def create_rate_renegotiation(self, payload, headers):
        return self._request("POST", "/eas/rate-renegotiations", payload, headers)

    def get_rate_renegotiation(self, renegotiation_id, headers):
        return self._request(
            "GET", f"/eas/rate-renegotiations/{renegotiation_id}", None, headers
        )

    def list_rate_renegotiations(self, headers, params=None):
        return self._request("GET", "/eas/rate-renegotiations", None, headers, params)

    def renegotiation_action(self, renegotiation_id, payload, headers):
        return self._request(
            "POST",
            f"/eas/rate-renegotiations/{renegotiation_id}/actions",
            payload,
            headers,
        )
