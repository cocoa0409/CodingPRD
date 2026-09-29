"""API client: one method per endpoint the PRD defines.

Every collection is mounted at the top level of the URL space; there are no
nested resource paths, so each method targets a flat path and passes parent
references inside the request body.
"""

import re
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

# The PRD fixes ISO 8601 UTC timestamps at three fractional digits. Tests
# compare instants through this canonicaliser rather than raw string equality
# so that a server emitting a different sub-second width is still compared on
# the value the PRD pins.
_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?Z$"
)


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO 8601 UTC instant to exactly three fractional digits."""
    if not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value.strip())
    if not match:
        return value
    day, hour, minute, second, fraction = match.groups()
    millis = (fraction or "")[:3].ljust(3, "0")
    return f"{day}T{hour}:{minute}:{second}.{millis}Z"


def calendar_date_of(instant: Optional[str]) -> Optional[str]:
    """Return the YYYY-MM-DD calendar date carried by an instant."""
    if not isinstance(instant, str) or "T" not in instant:
        return instant
    return instant.split("T", 1)[0]


class ApiClient(GenericApiClient):
    """PRD endpoint surface for the Portable Restroom Rental API."""

    # ─── Logical clock ────────────────────────────────────────────────
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def set_clock_raw(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Rental accounts ──────────────────────────────────────────────
    def create_rental_account(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/rental-accounts", payload, headers)

    def get_rental_account(self, account_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/rental-accounts/{account_id}", headers=headers)

    def list_account_service_sites(
        self, account_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/rental-accounts/{account_id}/service-sites",
            headers=headers, params=params,
        )

    # ─── Service sites ────────────────────────────────────────────────
    def create_service_site(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/service-sites", payload, headers)

    def get_service_site(self, site_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/service-sites/{site_id}", headers=headers)

    def list_site_permits(
        self, site_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/service-sites/{site_id}/permits", headers=headers, params=params
        )

    # ─── Placement permits ────────────────────────────────────────────
    def create_placement_permit(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/placement-permits", payload, headers)

    def get_placement_permit(self, permit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/placement-permits/{permit_id}", headers=headers)

    def submit_placement_permit(
        self, permit_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"/placement-permits/{permit_id}/submit", payload or {}, headers
        )

    def approve_placement_permit(
        self, permit_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/placement-permits/{permit_id}/approve", payload, headers
        )

    def reject_placement_permit(
        self, permit_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/placement-permits/{permit_id}/reject", payload, headers
        )

    # ─── Asset units ──────────────────────────────────────────────────
    def create_asset_unit(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/asset-units", payload, headers)

    def get_asset_unit(self, asset_unit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/asset-units/{asset_unit_id}", headers=headers)

    # ─── Disposal sites ───────────────────────────────────────────────
    def create_disposal_site(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/disposal-sites", payload, headers)

    def get_disposal_site(self, disposal_site_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/disposal-sites/{disposal_site_id}", headers=headers
        )

    # ─── Routes ───────────────────────────────────────────────────────
    def create_route(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/routes", payload, headers)

    def get_route(self, route_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/routes/{route_id}", headers=headers)

    # ─── Rental contracts ─────────────────────────────────────────────
    def create_rental_contract(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/rental-contracts", payload, headers)

    def get_rental_contract(self, contract_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/rental-contracts/{contract_id}", headers=headers)

    def list_rental_contracts(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/rental-contracts", headers=headers, params=params)

    def list_quote_lines(
        self, contract_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/rental-contracts/{contract_id}/quote-lines",
            headers=headers, params=params,
        )

    def quote_rental_contract(
        self, contract_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/rental-contracts/{contract_id}/quote", payload, headers
        )

    def activate_rental_contract(
        self, contract_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"/rental-contracts/{contract_id}/activate", payload or {}, headers
        )

    def demobilize_rental_contract(
        self, contract_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"/rental-contracts/{contract_id}/demobilize",
            payload or {}, headers,
        )

    def invoice_rental_contract(
        self, contract_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"/rental-contracts/{contract_id}/invoice", payload or {}, headers
        )

    def settle_rental_contract_invoice(
        self, contract_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"/rental-contracts/{contract_id}/settle-invoice",
            payload or {}, headers,
        )

    # ─── Unit deployments ─────────────────────────────────────────────
    def create_unit_deployment(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/unit-deployments", payload, headers)

    def get_unit_deployment(self, deployment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/unit-deployments/{deployment_id}", headers=headers
        )

    def list_unit_deployments(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/unit-deployments", headers=headers, params=params)

    def relocate_unit_deployment(
        self, deployment_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/unit-deployments/{deployment_id}/relocate", payload, headers
        )

    # ─── Service schedules ────────────────────────────────────────────
    def create_service_schedule(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/service-schedules", payload, headers)

    def get_service_schedule(self, schedule_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/service-schedules/{schedule_id}", headers=headers
        )

    def list_service_schedules(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/service-schedules", headers=headers, params=params
        )

    def suspend_service_schedule(
        self, schedule_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"/service-schedules/{schedule_id}/suspend", payload or {}, headers
        )

    # ─── Service visits ───────────────────────────────────────────────
    def create_service_visit(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/service-visits", payload, headers)

    def get_service_visit(self, visit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/service-visits/{visit_id}", headers=headers)

    def list_service_visits(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/service-visits", headers=headers, params=params)

    def dispatch_service_visit(
        self, visit_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"/service-visits/{visit_id}/dispatch", payload or {}, headers
        )

    def complete_service_visit(
        self, visit_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/service-visits/{visit_id}/complete", payload, headers
        )

    def mark_service_visit_missed(
        self, visit_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/service-visits/{visit_id}/mark-missed", payload, headers
        )

    def schedule_service_visit_rerun(
        self, visit_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/service-visits/{visit_id}/schedule-rerun", payload, headers
        )

    # ─── Waste manifests ──────────────────────────────────────────────
    def create_waste_manifest(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/waste-manifests", payload, headers)

    def get_waste_manifest(self, manifest_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/waste-manifests/{manifest_id}", headers=headers)

    def list_waste_manifests(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/waste-manifests", headers=headers, params=params)

    def seal_waste_manifest(
        self, manifest_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/waste-manifests/{manifest_id}/seal", payload, headers
        )

    def accept_waste_manifest(
        self, manifest_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"/waste-manifests/{manifest_id}/accept", payload or {}, headers
        )

    # ─── Charge events ────────────────────────────────────────────────
    def create_charge_event(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/charge-events", payload, headers)

    def get_charge_event(self, charge_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/charge-events/{charge_id}", headers=headers)

    def list_charge_events(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/charge-events", headers=headers, params=params)

    def dispute_charge_event(
        self, charge_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/charge-events/{charge_id}/dispute", payload, headers
        )

    def uphold_charge_event(
        self, charge_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"/charge-events/{charge_id}/uphold", payload or {}, headers
        )

    def waive_charge_event(
        self, charge_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"/charge-events/{charge_id}/waive", payload or {}, headers
        )


api_client = ApiClient()
