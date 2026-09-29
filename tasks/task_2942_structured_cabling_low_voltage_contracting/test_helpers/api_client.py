"""API client: one method per endpoint defined in the PRD.

All business collections are mounted under the /cabling prefix; the test-only
logical clock control sits outside it.

The client also exposes `canonical_instant` / `instants_equal`, which normalise an
ISO 8601 UTC instant to a fixed three-fractional-digit form so that an
implementation reporting "2026-08-14T09:00:00Z" and one reporting
"2026-08-14T09:00:00.000Z" are compared as the same instant.
"""
import re
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/cabling"

_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?"
    r"(Z|[+-]\d{2}:?\d{2})$"
)


def canonical_instant(value: Any) -> Any:
    """Normalise an ISO 8601 UTC instant to exactly three fractional digits.

    Non-instant values (including None) are returned untouched so the helper can
    be applied to any field without a type guard.
    """
    if not isinstance(value, str):
        return value
    m = _INSTANT_RE.match(value.strip())
    if not m:
        return value
    year, month, day, hh, mm, ss, frac, tz = m.groups()
    frac = (frac or "")[:3].ljust(3, "0")
    if tz != "Z":
        # A non-UTC offset is left as-is: the PRD only ever emits UTC.
        return value
    return f"{year}-{month}-{day}T{hh}:{mm}:{ss}.{frac}Z"


def instants_equal(actual: Any, expected: Any) -> bool:
    """True when two ISO 8601 UTC instants denote the same moment."""
    return canonical_instant(actual) == canonical_instant(expected)


class ApiClient(GenericApiClient):
    # ── Logical site clock (§2.5) ────────────────────────────────────────────
    def set_clock(self, to_iso8601: str, headers: Optional[Dict[str, str]] = None):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ── Projects ────────────────────────────────────────────────────────────
    def create_project(self, payload, headers):
        return self._request("POST", f"{PREFIX}/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"{PREFIX}/projects/{project_id}", headers=headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/projects", headers=headers, params=params)

    def declare_occupancy(self, project_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/projects/{project_id}/occupancy", payload, headers
        )

    def get_certification_summary(self, project_id, headers):
        return self._request(
            "GET", f"{PREFIX}/projects/{project_id}/certification-summary", headers=headers
        )

    # ── Telecom rooms ───────────────────────────────────────────────────────
    def create_telecom_room(self, payload, headers):
        return self._request("POST", f"{PREFIX}/telecom-rooms", payload, headers)

    def get_telecom_room(self, room_id, headers):
        return self._request("GET", f"{PREFIX}/telecom-rooms/{room_id}", headers=headers)

    def list_telecom_rooms(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/telecom-rooms", headers=headers, params=params
        )

    def verify_grounding(self, room_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/telecom-rooms/{room_id}/grounding-verification",
            payload, headers,
        )

    def energize_room(self, room_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/telecom-rooms/{room_id}/energize", payload or {}, headers
        )

    # ── Racks ───────────────────────────────────────────────────────────────
    def create_rack(self, payload, headers):
        return self._request("POST", f"{PREFIX}/racks", payload, headers)

    def get_rack(self, rack_id, headers):
        return self._request("GET", f"{PREFIX}/racks/{rack_id}", headers=headers)

    def list_racks(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/racks", headers=headers, params=params)

    # ── Rack elevation placements ───────────────────────────────────────────
    def create_rack_unit_assignment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/rack-unit-assignments", payload, headers)

    def get_rack_unit_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/rack-unit-assignments/{assignment_id}", headers=headers
        )

    def list_rack_unit_assignments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/rack-unit-assignments", headers=headers, params=params
        )

    def release_rack_unit_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/rack-unit-assignments/{assignment_id}/release",
            payload, headers,
        )

    # ── Pathway segments ────────────────────────────────────────────────────
    def create_pathway_segment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/pathway-segments", payload, headers)

    def get_pathway_segment(self, segment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/pathway-segments/{segment_id}", headers=headers
        )

    def list_pathway_segments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/pathway-segments", headers=headers, params=params
        )

    def condemn_pathway_segment(self, segment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/pathway-segments/{segment_id}/condemn", payload, headers
        )

    def reparent_pathway_segment(self, segment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/pathway-segments/{segment_id}/reparent", payload, headers
        )

    # ── Cable catalogue ─────────────────────────────────────────────────────
    def create_cable_type(self, payload, headers):
        return self._request("POST", f"{PREFIX}/cable-types", payload, headers)

    def get_cable_type(self, cable_type_id, headers):
        return self._request(
            "GET", f"{PREFIX}/cable-types/{cable_type_id}", headers=headers
        )

    def list_cable_types(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/cable-types", headers=headers, params=params
        )

    # ── Links ───────────────────────────────────────────────────────────────
    def create_link(self, payload, headers):
        return self._request("POST", f"{PREFIX}/links", payload, headers)

    def get_link(self, link_id, headers):
        return self._request("GET", f"{PREFIX}/links/{link_id}", headers=headers)

    def list_links(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/links", headers=headers, params=params)

    def pull_link(self, link_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/links/{link_id}/pull", payload or {}, headers
        )

    def terminate_link(self, link_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/links/{link_id}/terminate", payload or {}, headers
        )

    def label_link(self, link_id, payload, headers):
        return self._request("POST", f"{PREFIX}/links/{link_id}/label", payload, headers)

    def record_link(self, link_id, payload, headers):
        return self._request("POST", f"{PREFIX}/links/{link_id}/record", payload, headers)

    def certify_link(self, link_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/links/{link_id}/certify", payload or {}, headers
        )

    def get_certification_report(self, link_id, headers):
        return self._request(
            "GET", f"{PREFIX}/links/{link_id}/certification-report", headers=headers
        )

    # ── Link routings ───────────────────────────────────────────────────────
    def create_link_route(self, payload, headers):
        return self._request("POST", f"{PREFIX}/link-routes", payload, headers)

    def get_link_route(self, route_id, headers):
        return self._request("GET", f"{PREFIX}/link-routes/{route_id}", headers=headers)

    def list_link_routes(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/link-routes", headers=headers, params=params
        )

    def withdraw_link_route(self, route_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/link-routes/{route_id}/withdraw", payload, headers
        )

    # ── Field test results ──────────────────────────────────────────────────
    def create_test_result(self, payload, headers):
        return self._request("POST", f"{PREFIX}/test-results", payload, headers)

    def get_test_result(self, test_result_id, headers):
        return self._request(
            "GET", f"{PREFIX}/test-results/{test_result_id}", headers=headers
        )

    def list_test_results(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/test-results", headers=headers, params=params
        )

    # ── Warranty registrations ──────────────────────────────────────────────
    def create_warranty_registration(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/warranty-registrations", payload, headers
        )

    def get_warranty_registration(self, registration_id, headers):
        return self._request(
            "GET", f"{PREFIX}/warranty-registrations/{registration_id}", headers=headers
        )

    def list_warranty_registrations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/warranty-registrations", headers=headers, params=params
        )

    def submit_warranty_registration(self, registration_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/warranty-registrations/{registration_id}/submit",
            payload, headers,
        )

    def decide_warranty_registration(self, registration_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/warranty-registrations/{registration_id}/decision",
            payload, headers,
        )

    def reopen_warranty_registration(self, registration_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/warranty-registrations/{registration_id}/reopen",
            payload or {}, headers,
        )

    # ── Moves-adds-changes tickets ──────────────────────────────────────────
    def create_mac_ticket(self, payload, headers):
        return self._request("POST", f"{PREFIX}/mac-tickets", payload, headers)

    def get_mac_ticket(self, ticket_id, headers):
        return self._request("GET", f"{PREFIX}/mac-tickets/{ticket_id}", headers=headers)

    def list_mac_tickets(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/mac-tickets", headers=headers, params=params
        )

    def schedule_mac_ticket(self, ticket_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/mac-tickets/{ticket_id}/schedule", payload, headers
        )

    def reject_mac_ticket(self, ticket_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/mac-tickets/{ticket_id}/reject", payload or {}, headers
        )

    def start_mac_ticket(self, ticket_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/mac-tickets/{ticket_id}/start", payload or {}, headers
        )

    def rework_mac_ticket(self, ticket_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/mac-tickets/{ticket_id}/rework", payload or {}, headers
        )

    def complete_mac_ticket(self, ticket_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/mac-tickets/{ticket_id}/complete", payload, headers
        )

    # ── Trade coordinations ─────────────────────────────────────────────────
    def create_trade_coordination(self, payload, headers):
        return self._request("POST", f"{PREFIX}/trade-coordinations", payload, headers)

    def get_trade_coordination(self, coordination_id, headers):
        return self._request(
            "GET", f"{PREFIX}/trade-coordinations/{coordination_id}", headers=headers
        )

    def list_trade_coordinations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/trade-coordinations", headers=headers, params=params
        )

    def confirm_trade_coordination(self, coordination_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/trade-coordinations/{coordination_id}/confirm",
            payload, headers,
        )

    def release_trade_coordination(self, coordination_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/trade-coordinations/{coordination_id}/release",
            payload or {}, headers,
        )

    def block_trade_coordination(self, coordination_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/trade-coordinations/{coordination_id}/block",
            payload, headers,
        )

    def unblock_trade_coordination(self, coordination_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/trade-coordinations/{coordination_id}/unblock",
            payload or {}, headers,
        )

    # ── Raw helpers for negative shape tests ────────────────────────────────
    def raw_post(self, path, payload, headers):
        """POST an arbitrary path under the /cabling prefix."""
        return self._request("POST", f"{PREFIX}{path}", payload, headers)

    def raw_get(self, path, headers, params=None):
        return self._request("GET", f"{PREFIX}{path}", headers=headers, params=params)


api_client = ApiClient()
