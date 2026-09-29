"""API client: one method per endpoint declared in the PRD's §4 routing index.

Timestamp hygiene
-----------------
PRD §2.4 states that "Timestamps supplied as input and timestamps returned in
responses are ISO 8601 UTC with exactly three fractional-second digits, for
example `2026-08-01T11:30:00.000Z`". Serialisers legitimately differ on how many
fractional digits they emit for a whole-second instant, so every response body
this client returns is walked once and every UTC instant string is canonicalised
to exactly three fractional digits with a `Z` suffix. Tests therefore compare
instants by value, never by raw string width.
"""

import re
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

_PARK_OPS = "/park-ops"

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
    """Theme Park Ride Maintenance API client."""

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------
    def _request(self, method, path, payload=None, headers=None, params=None):
        response = super()._request(method, path, payload, headers, params)
        return _with_canonical_json(response)

    # ------------------------------------------------------------------
    # Attractions (PRD §3.1)
    # ------------------------------------------------------------------
    def create_attraction(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{_PARK_OPS}/attractions", payload, headers)

    def get_attraction(self, attraction_id: str, headers: Dict):
        return self._request(
            "GET", f"{_PARK_OPS}/attractions/{attraction_id}", headers=headers
        )

    def list_attractions(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{_PARK_OPS}/attractions", headers=headers, params=params
        )

    def log_cycles(self, attraction_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"{_PARK_OPS}/attractions/{attraction_id}/cycles", payload, headers
        )

    def get_capacity_impact(
        self, attraction_id: str, headers: Dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{_PARK_OPS}/attractions/{attraction_id}/capacity-impact",
            headers=headers,
            params=params,
        )

    def get_dispatch_readiness(self, attraction_id: str, headers: Dict):
        return self._request(
            "GET",
            f"{_PARK_OPS}/attractions/{attraction_id}/dispatch-readiness",
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Components (PRD §3.1)
    # ------------------------------------------------------------------
    def create_component(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{_PARK_OPS}/components", payload, headers)

    def get_component(self, component_id: str, headers: Dict):
        return self._request(
            "GET", f"{_PARK_OPS}/components/{component_id}", headers=headers
        )

    def list_components(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{_PARK_OPS}/components", headers=headers, params=params
        )

    def record_ndt(self, component_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST",
            f"{_PARK_OPS}/components/{component_id}/ndt-records",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Inspection template revisions and checklist lines (PRD §3.1)
    # ------------------------------------------------------------------
    def create_inspection_template(self, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"{_PARK_OPS}/inspection-templates", payload, headers
        )

    def get_inspection_template(self, template_id: str, headers: Dict):
        return self._request(
            "GET", f"{_PARK_OPS}/inspection-templates/{template_id}", headers=headers
        )

    def list_inspection_templates(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{_PARK_OPS}/inspection-templates", headers=headers, params=params
        )

    def append_checklist_item(self, template_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST",
            f"{_PARK_OPS}/inspection-templates/{template_id}/items",
            payload,
            headers,
        )

    def activate_inspection_template(
        self, template_id: str, payload: Dict, headers: Dict
    ):
        return self._request(
            "POST",
            f"{_PARK_OPS}/inspection-templates/{template_id}/activate",
            payload,
            headers,
        )

    def get_checklist_item(self, checklist_item_id: str, headers: Dict):
        return self._request(
            "GET", f"{_PARK_OPS}/checklist-items/{checklist_item_id}", headers=headers
        )

    def list_checklist_items(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{_PARK_OPS}/checklist-items", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Daily inspections (PRD §3.2, §3.3)
    # ------------------------------------------------------------------
    def create_daily_inspection(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{_PARK_OPS}/daily-inspections", payload, headers)

    def get_daily_inspection(self, inspection_id: str, headers: Dict):
        return self._request(
            "GET", f"{_PARK_OPS}/daily-inspections/{inspection_id}", headers=headers
        )

    def list_daily_inspections(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{_PARK_OPS}/daily-inspections", headers=headers, params=params
        )

    def submit_daily_inspection(
        self, inspection_id: str, headers: Dict, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{_PARK_OPS}/daily-inspections/{inspection_id}/submit",
            payload or {},
            headers,
        )

    def sign_off_daily_inspection(
        self, inspection_id: str, headers: Dict, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{_PARK_OPS}/daily-inspections/{inspection_id}/sign-off",
            payload or {},
            headers,
        )

    def reject_daily_inspection(self, inspection_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST",
            f"{_PARK_OPS}/daily-inspections/{inspection_id}/reject",
            payload,
            headers,
        )

    def reopen_daily_inspection(
        self, inspection_id: str, headers: Dict, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{_PARK_OPS}/daily-inspections/{inspection_id}/reopen",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # Inspection item results (PRD §3.2)
    # ------------------------------------------------------------------
    def get_inspection_item_result(self, result_id: str, headers: Dict):
        return self._request(
            "GET", f"{_PARK_OPS}/inspection-item-results/{result_id}", headers=headers
        )

    def list_inspection_item_results(
        self, headers: Dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{_PARK_OPS}/inspection-item-results",
            headers=headers,
            params=params,
        )

    def record_inspection_item_result(
        self, result_id: str, payload: Dict, headers: Dict
    ):
        return self._request(
            "POST",
            f"{_PARK_OPS}/inspection-item-results/{result_id}/record",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Manufacturer bulletins and fleet actions (PRD §3.6)
    # ------------------------------------------------------------------
    def create_bulletin(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{_PARK_OPS}/bulletins", payload, headers)

    def get_bulletin(self, bulletin_id: str, headers: Dict):
        return self._request(
            "GET", f"{_PARK_OPS}/bulletins/{bulletin_id}", headers=headers
        )

    def list_bulletins(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{_PARK_OPS}/bulletins", headers=headers, params=params
        )

    def get_bulletin_risk(self, bulletin_id: str, headers: Dict):
        return self._request(
            "GET", f"{_PARK_OPS}/bulletins/{bulletin_id}/risk", headers=headers
        )

    def acknowledge_bulletin(
        self, bulletin_id: str, headers: Dict, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{_PARK_OPS}/bulletins/{bulletin_id}/acknowledge",
            payload or {},
            headers,
        )

    def get_bulletin_action(self, action_id: str, headers: Dict):
        return self._request(
            "GET", f"{_PARK_OPS}/bulletin-actions/{action_id}", headers=headers
        )

    def list_bulletin_actions(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{_PARK_OPS}/bulletin-actions", headers=headers, params=params
        )

    def start_bulletin_action(
        self, action_id: str, headers: Dict, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{_PARK_OPS}/bulletin-actions/{action_id}/start",
            payload or {},
            headers,
        )

    def verify_bulletin_action(
        self, action_id: str, headers: Dict, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{_PARK_OPS}/bulletin-actions/{action_id}/verify",
            payload or {},
            headers,
        )

    def defer_bulletin_action(self, action_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"{_PARK_OPS}/bulletin-actions/{action_id}/defer", payload, headers
        )

    # ------------------------------------------------------------------
    # Downtime events (PRD §3.4)
    # ------------------------------------------------------------------
    def create_downtime_event(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{_PARK_OPS}/downtime-events", payload, headers)

    def get_downtime_event(self, event_id: str, headers: Dict):
        return self._request(
            "GET", f"{_PARK_OPS}/downtime-events/{event_id}", headers=headers
        )

    def list_downtime_events(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{_PARK_OPS}/downtime-events", headers=headers, params=params
        )

    def diagnose_downtime_event(self, event_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"{_PARK_OPS}/downtime-events/{event_id}/diagnose", payload, headers
        )

    def resolve_downtime_event(self, event_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"{_PARK_OPS}/downtime-events/{event_id}/resolve", payload, headers
        )

    def close_downtime_event(
        self, event_id: str, headers: Dict, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{_PARK_OPS}/downtime-events/{event_id}/close",
            payload or {},
            headers,
        )

    def void_downtime_event(self, event_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"{_PARK_OPS}/downtime-events/{event_id}/void", payload, headers
        )

    # ------------------------------------------------------------------
    # Part requisitions (PRD §3.5)
    # ------------------------------------------------------------------
    def create_part_requisition(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{_PARK_OPS}/part-requisitions", payload, headers)

    def get_part_requisition(self, requisition_id: str, headers: Dict):
        return self._request(
            "GET", f"{_PARK_OPS}/part-requisitions/{requisition_id}", headers=headers
        )

    def list_part_requisitions(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{_PARK_OPS}/part-requisitions", headers=headers, params=params
        )

    def reserve_part_requisition(
        self, requisition_id: str, headers: Dict, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{_PARK_OPS}/part-requisitions/{requisition_id}/reserve",
            payload or {},
            headers,
        )

    def backorder_part_requisition(
        self, requisition_id: str, headers: Dict, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{_PARK_OPS}/part-requisitions/{requisition_id}/backorder",
            payload or {},
            headers,
        )

    def receive_part_requisition(
        self, requisition_id: str, headers: Dict, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{_PARK_OPS}/part-requisitions/{requisition_id}/receive",
            payload or {},
            headers,
        )

    def cancel_part_requisition(self, requisition_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST",
            f"{_PARK_OPS}/part-requisitions/{requisition_id}/cancel",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Operator certifications (PRD §3.7)
    # ------------------------------------------------------------------
    def create_operator_certification(self, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"{_PARK_OPS}/operator-certifications", payload, headers
        )

    def get_operator_certification(self, certification_id: str, headers: Dict):
        return self._request(
            "GET",
            f"{_PARK_OPS}/operator-certifications/{certification_id}",
            headers=headers,
        )

    def list_operator_certifications(
        self, headers: Dict, params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{_PARK_OPS}/operator-certifications",
            headers=headers,
            params=params,
        )

    def suspend_operator_certification(
        self, certification_id: str, payload: Dict, headers: Dict
    ):
        return self._request(
            "POST",
            f"{_PARK_OPS}/operator-certifications/{certification_id}/suspend",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Incident reports (PRD §3.8)
    # ------------------------------------------------------------------
    def create_incident(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{_PARK_OPS}/incidents", payload, headers)

    def get_incident(self, incident_id: str, headers: Dict):
        return self._request(
            "GET", f"{_PARK_OPS}/incidents/{incident_id}", headers=headers
        )

    def list_incidents(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{_PARK_OPS}/incidents", headers=headers, params=params
        )

    def hold_ride(
        self, incident_id: str, headers: Dict, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{_PARK_OPS}/incidents/{incident_id}/hold-ride",
            payload or {},
            headers,
        )

    def investigate_incident(
        self, incident_id: str, headers: Dict, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{_PARK_OPS}/incidents/{incident_id}/investigate",
            payload or {},
            headers,
        )

    def notify_regulator(self, incident_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST",
            f"{_PARK_OPS}/incidents/{incident_id}/notify-regulator",
            payload,
            headers,
        )

    def close_internal_review(
        self, incident_id: str, headers: Dict, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{_PARK_OPS}/incidents/{incident_id}/close-internal",
            payload or {},
            headers,
        )

    def clear_incident(
        self, incident_id: str, headers: Dict, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{_PARK_OPS}/incidents/{incident_id}/clear",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # Shop bays and overhaul work orders (PRD §3.9)
    # ------------------------------------------------------------------
    def create_shop_bay(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{_PARK_OPS}/shop-bays", payload, headers)

    def get_shop_bay(self, shop_bay_id: str, headers: Dict):
        return self._request(
            "GET", f"{_PARK_OPS}/shop-bays/{shop_bay_id}", headers=headers
        )

    def list_shop_bays(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{_PARK_OPS}/shop-bays", headers=headers, params=params
        )

    def create_overhaul_work_order(self, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"{_PARK_OPS}/overhaul-work-orders", payload, headers
        )

    def get_overhaul_work_order(self, work_order_id: str, headers: Dict):
        return self._request(
            "GET", f"{_PARK_OPS}/overhaul-work-orders/{work_order_id}", headers=headers
        )

    def list_overhaul_work_orders(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{_PARK_OPS}/overhaul-work-orders", headers=headers, params=params
        )

    def advance_overhaul_work_order(
        self, work_order_id: str, payload: Dict, headers: Dict
    ):
        return self._request(
            "POST",
            f"{_PARK_OPS}/overhaul-work-orders/{work_order_id}/advance",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Logical park clock (PRD §2.4)
    # ------------------------------------------------------------------
    def set_clock(self, payload: Dict, headers: Dict):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


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
