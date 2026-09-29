"""Typed HTTP client for the multifamily physical inspection readiness API.

One method per endpoint of the contract, so the test suite never spells a URL
inline. Every response passes through a canonicalising proxy that rewrites
ISO-8601 instants to exactly three fractional digits, which is the precision
the contract declares; tests can therefore compare instant strings directly
without depending on how many digits the server chose to emit.
"""

import re
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .types import Headers, Payload

# 2026-08-01T00:00:00Z / ...T00:00:00.5Z / ...T00:00:00.123456Z / ...+00:00
_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?"
    r"(Z|[+-]\d{2}:?\d{2})$"
)


def canonicalize_instant(value: str) -> str:
    """Rewrite one ISO-8601 instant to `YYYY-MM-DDTHH:MM:SS.mmmZ`.

    Values that are not instants are returned untouched.
    """
    match = _INSTANT_RE.match(value)
    if match is None:
        return value
    date_part, time_part, fraction, offset = match.groups()
    if offset not in ("Z", "+00:00", "+0000", "-00:00", "-0000"):
        # A non-UTC offset is not something this contract emits; leave it be
        # rather than silently shifting the instant.
        return value
    millis = (fraction or "")[:3].ljust(3, "0")
    return "{0}T{1}.{2}Z".format(date_part, time_part, millis)


def canonicalize_instants(node: Any) -> Any:
    """Recursively canonicalise every ISO-8601 instant string in a JSON tree."""
    if isinstance(node, str):
        return canonicalize_instant(node)
    if isinstance(node, list):
        return [canonicalize_instants(item) for item in node]
    if isinstance(node, dict):
        return {key: canonicalize_instants(value) for key, value in node.items()}
    return node


class _CanonicalResponse:
    """Proxy around a response whose `json()` has canonical instants."""

    def __init__(self, response: Any) -> None:
        self._response = response

    def json(self, **kwargs: Any) -> Any:
        return canonicalize_instants(self._response.json(**kwargs))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._response, name)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<CanonicalResponse {0}>".format(repr(self._response))


class ApiClient(GenericApiClient):
    """Endpoint-per-method client with instant canonicalisation."""

    # -- plumbing ----------------------------------------------------------
    def _call(
        self,
        method: str,
        path: str,
        payload: Optional[Payload] = None,
        headers: Optional[Headers] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        response = self._request(
            method, path, payload=payload, headers=headers, params=params
        )
        return _CanonicalResponse(response)

    # -- inspection standards ---------------------------------------------
    def create_standard(self, payload: Payload, headers: Headers) -> Any:
        return self._call("POST", "/inspection-standards", payload, headers)

    def adopt_standard(
        self, standard_id: str, payload: Payload, headers: Headers
    ) -> Any:
        return self._call(
            "POST",
            "/inspection-standards/{0}/adopt".format(standard_id),
            payload,
            headers,
        )

    def get_standard(self, standard_id: str, headers: Headers) -> Any:
        return self._call(
            "GET", "/inspection-standards/{0}".format(standard_id), None, headers
        )

    def list_standards(self, headers: Headers, **params: Any) -> Any:
        return self._call("GET", "/inspection-standards", None, headers, params)

    # -- defect definitions ------------------------------------------------
    def create_defect_definition(self, payload: Payload, headers: Headers) -> Any:
        return self._call("POST", "/defect-definitions", payload, headers)

    def get_defect_definition(self, definition_id: str, headers: Headers) -> Any:
        return self._call(
            "GET", "/defect-definitions/{0}".format(definition_id), None, headers
        )

    def list_defect_definitions(self, headers: Headers, **params: Any) -> Any:
        return self._call("GET", "/defect-definitions", None, headers, params)

    # -- properties ---------------------------------------------------------
    def create_property(self, payload: Payload, headers: Headers) -> Any:
        return self._call("POST", "/properties", payload, headers)

    def get_property(self, property_id: str, headers: Headers) -> Any:
        return self._call("GET", "/properties/{0}".format(property_id), None, headers)

    def list_properties(self, headers: Headers, **params: Any) -> Any:
        return self._call("GET", "/properties", None, headers, params)

    def patch_property(
        self, property_id: str, payload: Payload, headers: Headers
    ) -> Any:
        return self._call(
            "PATCH", "/properties/{0}".format(property_id), payload, headers
        )

    # -- units --------------------------------------------------------------
    def create_unit(self, payload: Payload, headers: Headers) -> Any:
        return self._call("POST", "/units", payload, headers)

    def get_unit(self, unit_id: str, headers: Headers) -> Any:
        return self._call("GET", "/units/{0}".format(unit_id), None, headers)

    def list_units(self, headers: Headers, **params: Any) -> Any:
        return self._call("GET", "/units", None, headers, params)

    def patch_unit(self, unit_id: str, payload: Payload, headers: Headers) -> Any:
        return self._call("PATCH", "/units/{0}".format(unit_id), payload, headers)

    # -- self-assessment sweeps --------------------------------------------
    def create_sweep(self, payload: Payload, headers: Headers) -> Any:
        return self._call("POST", "/self-assessment-sweeps", payload, headers)

    def get_sweep(self, sweep_id: str, headers: Headers) -> Any:
        return self._call(
            "GET", "/self-assessment-sweeps/{0}".format(sweep_id), None, headers
        )

    def list_sweeps(self, headers: Headers, **params: Any) -> Any:
        return self._call("GET", "/self-assessment-sweeps", None, headers, params)

    def start_sweep(self, sweep_id: str, payload: Payload, headers: Headers) -> Any:
        return self._call(
            "POST",
            "/self-assessment-sweeps/{0}/start".format(sweep_id),
            payload,
            headers,
        )

    def record_finding(self, sweep_id: str, payload: Payload, headers: Headers) -> Any:
        return self._call(
            "POST",
            "/self-assessment-sweeps/{0}/findings".format(sweep_id),
            payload,
            headers,
        )

    def close_sweep(self, sweep_id: str, payload: Payload, headers: Headers) -> Any:
        return self._call(
            "POST",
            "/self-assessment-sweeps/{0}/close".format(sweep_id),
            payload,
            headers,
        )

    # -- work orders --------------------------------------------------------
    def get_work_order(self, work_order_id: str, headers: Headers) -> Any:
        return self._call(
            "GET", "/work-orders/{0}".format(work_order_id), None, headers
        )

    def list_work_orders(self, headers: Headers, **params: Any) -> Any:
        return self._call("GET", "/work-orders", None, headers, params)

    def complete_work_order(
        self, work_order_id: str, payload: Payload, headers: Headers
    ) -> Any:
        return self._call(
            "POST",
            "/work-orders/{0}/complete".format(work_order_id),
            payload,
            headers,
        )

    def verify_work_order_closure(
        self, work_order_id: str, payload: Payload, headers: Headers
    ) -> Any:
        return self._call(
            "POST",
            "/work-orders/{0}/verify-closure".format(work_order_id),
            payload,
            headers,
        )

    def void_work_order(
        self, work_order_id: str, payload: Payload, headers: Headers
    ) -> Any:
        return self._call(
            "POST", "/work-orders/{0}/void".format(work_order_id), payload, headers
        )

    # -- inspections --------------------------------------------------------
    def create_inspection(self, payload: Payload, headers: Headers) -> Any:
        return self._call("POST", "/inspections", payload, headers)

    def get_inspection(self, inspection_id: str, headers: Headers) -> Any:
        return self._call(
            "GET", "/inspections/{0}".format(inspection_id), None, headers
        )

    def list_inspections(self, headers: Headers, **params: Any) -> Any:
        return self._call("GET", "/inspections", None, headers, params)

    def draw_sample(
        self, inspection_id: str, payload: Payload, headers: Headers
    ) -> Any:
        return self._call(
            "POST",
            "/inspections/{0}/draw-sample".format(inspection_id),
            payload,
            headers,
        )

    def start_inspection(
        self, inspection_id: str, payload: Payload, headers: Headers
    ) -> Any:
        return self._call(
            "POST", "/inspections/{0}/start".format(inspection_id), payload, headers
        )

    def record_deficiency(
        self, inspection_id: str, payload: Payload, headers: Headers
    ) -> Any:
        return self._call(
            "POST",
            "/inspections/{0}/deficiencies".format(inspection_id),
            payload,
            headers,
        )

    def score_inspection(
        self, inspection_id: str, payload: Payload, headers: Headers
    ) -> Any:
        return self._call(
            "POST", "/inspections/{0}/score".format(inspection_id), payload, headers
        )

    def finalize_inspection(
        self, inspection_id: str, payload: Payload, headers: Headers
    ) -> Any:
        return self._call(
            "POST", "/inspections/{0}/finalize".format(inspection_id), payload, headers
        )

    def cancel_inspection(
        self, inspection_id: str, payload: Payload, headers: Headers
    ) -> Any:
        return self._call(
            "POST", "/inspections/{0}/cancel".format(inspection_id), payload, headers
        )

    # -- sample selections --------------------------------------------------
    def get_sample_selection(self, selection_id: str, headers: Headers) -> Any:
        return self._call(
            "GET", "/sample-selections/{0}".format(selection_id), None, headers
        )

    def list_sample_selections(self, headers: Headers, **params: Any) -> Any:
        return self._call("GET", "/sample-selections", None, headers, params)

    def issue_notice(
        self, selection_id: str, payload: Payload, headers: Headers
    ) -> Any:
        return self._call(
            "POST",
            "/sample-selections/{0}/notice".format(selection_id),
            payload,
            headers,
        )

    def record_access(
        self, selection_id: str, payload: Payload, headers: Headers
    ) -> Any:
        return self._call(
            "POST",
            "/sample-selections/{0}/access".format(selection_id),
            payload,
            headers,
        )

    # -- deficiencies -------------------------------------------------------
    def get_deficiency(self, deficiency_id: str, headers: Headers) -> Any:
        return self._call(
            "GET", "/deficiencies/{0}".format(deficiency_id), None, headers
        )

    def list_deficiencies(self, headers: Headers, **params: Any) -> Any:
        return self._call("GET", "/deficiencies", None, headers, params)

    def record_correction(
        self, deficiency_id: str, payload: Payload, headers: Headers
    ) -> Any:
        return self._call(
            "POST",
            "/deficiencies/{0}/correction".format(deficiency_id),
            payload,
            headers,
        )

    def record_verification(
        self, deficiency_id: str, payload: Payload, headers: Headers
    ) -> Any:
        return self._call(
            "POST",
            "/deficiencies/{0}/verification".format(deficiency_id),
            payload,
            headers,
        )

    # -- appeals ------------------------------------------------------------
    def create_appeal(self, payload: Payload, headers: Headers) -> Any:
        return self._call("POST", "/appeals", payload, headers)

    def get_appeal(self, appeal_id: str, headers: Headers) -> Any:
        return self._call("GET", "/appeals/{0}".format(appeal_id), None, headers)

    def list_appeals(self, headers: Headers, **params: Any) -> Any:
        return self._call("GET", "/appeals", None, headers, params)

    def review_appeal(self, appeal_id: str, payload: Payload, headers: Headers) -> Any:
        return self._call(
            "POST", "/appeals/{0}/review".format(appeal_id), payload, headers
        )

    def resubmit_appeal(
        self, appeal_id: str, payload: Payload, headers: Headers
    ) -> Any:
        return self._call(
            "POST", "/appeals/{0}/resubmit".format(appeal_id), payload, headers
        )

    # -- corrective action plans -------------------------------------------
    def create_cap(self, payload: Payload, headers: Headers) -> Any:
        return self._call("POST", "/corrective-action-plans", payload, headers)

    def get_cap(self, plan_id: str, headers: Headers) -> Any:
        return self._call(
            "GET", "/corrective-action-plans/{0}".format(plan_id), None, headers
        )

    def list_caps(self, headers: Headers, **params: Any) -> Any:
        return self._call("GET", "/corrective-action-plans", None, headers, params)

    def review_cap(self, plan_id: str, payload: Payload, headers: Headers) -> Any:
        return self._call(
            "POST",
            "/corrective-action-plans/{0}/review".format(plan_id),
            payload,
            headers,
        )

    def resubmit_cap(self, plan_id: str, payload: Payload, headers: Headers) -> Any:
        return self._call(
            "POST",
            "/corrective-action-plans/{0}/resubmit".format(plan_id),
            payload,
            headers,
        )

    def schedule_follow_up(
        self, plan_id: str, payload: Payload, headers: Headers
    ) -> Any:
        return self._call(
            "POST",
            "/corrective-action-plans/{0}/schedule-follow-up".format(plan_id),
            payload,
            headers,
        )

    # -- capital needs ------------------------------------------------------
    def recompute_capital_needs(self, payload: Payload, headers: Headers) -> Any:
        return self._call("POST", "/capital-needs/recompute", payload, headers)

    def get_capital_need(self, item_id: str, headers: Headers) -> Any:
        return self._call("GET", "/capital-needs/{0}".format(item_id), None, headers)

    def list_capital_needs(self, headers: Headers, **params: Any) -> Any:
        return self._call("GET", "/capital-needs", None, headers, params)

    # -- operator endpoints -------------------------------------------------
    def set_clock(self, payload: Payload, headers: Headers) -> Any:
        return self._call("POST", "/_clock/set_current_utc", payload, headers)

    def inject_completed_inspection_history(
        self, payload: Payload, headers: Headers
    ) -> Any:
        return self._call(
            "POST", "/_inject/completed-inspection-history", payload, headers
        )


api_client = ApiClient()
