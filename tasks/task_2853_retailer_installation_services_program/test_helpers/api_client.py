"""One method per endpoint of the Retailer Installation Services API.

Every method returns the raw ``requests.Response`` so tests can assert status
codes and pass the response straight into the framework validators. Nothing here
unwraps the response envelope.

Outgoing payloads pass through :func:`canonicalise_instants`, which rewrites every
ISO 8601 UTC instant to exactly three fractional digits, because the API accepts
"an ISO 8601 UTC string with exactly three fractional digits" and nothing else.
Doing it here means no individual test has to think about sub-second width.
"""

import re
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import GenericApiClient

_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?Z$"
)


def iso3(instant: str) -> str:
    """Return ``instant`` with exactly three fractional digits.

    ``2026-08-01T00:00:00Z`` and ``2026-08-01T00:00:00.000000Z`` both become
    ``2026-08-01T00:00:00.000Z``. A string that is not an ISO 8601 UTC instant is
    returned untouched.
    """
    if not isinstance(instant, str):
        return instant
    match = _INSTANT_RE.match(instant)
    if not match:
        return instant
    date_part, time_part, frac = match.groups()
    frac = (frac or "")[:3].ljust(3, "0")
    return f"{date_part}T{time_part}.{frac}Z"


def canonicalise_instants(value: Any) -> Any:
    """Recursively canonicalise every ISO 8601 UTC instant inside ``value``."""
    if isinstance(value, str):
        return iso3(value)
    if isinstance(value, dict):
        return {k: canonicalise_instants(v) for k, v in value.items()}
    if isinstance(value, list):
        return [canonicalise_instants(v) for v in value]
    return value


class ApiClient(GenericApiClient):
    """Domain client: one method per endpoint declared by the PRD."""

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------
    def _send(self, method, path, payload=None, headers=None, params=None):
        return self._request(
            method,
            path,
            payload=canonicalise_instants(payload),
            headers=headers,
            params=canonicalise_instants(params),
        )

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._send(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def get_clock(self, headers: Dict[str, str]):
        return self._send("GET", "/_clock", None, headers)

    # ------------------------------------------------------------------
    # Service categories
    # ------------------------------------------------------------------
    def create_service_category(self, payload: Dict[str, Any], headers):
        return self._send("POST", "/service-categories", payload, headers)

    def list_service_categories(self, headers, params: Optional[Dict] = None):
        return self._send("GET", "/service-categories", None, headers, params)

    def get_service_category(self, category_id: str, headers):
        return self._send("GET", f"/service-categories/{category_id}", None, headers)

    def patch_service_category(self, category_id: str, payload: Dict[str, Any], headers):
        return self._send(
            "PATCH", f"/service-categories/{category_id}", payload, headers
        )

    # ------------------------------------------------------------------
    # Jurisdictions
    # ------------------------------------------------------------------
    def create_jurisdiction(self, payload: Dict[str, Any], headers):
        return self._send("POST", "/jurisdictions", payload, headers)

    def list_jurisdictions(self, headers, params: Optional[Dict] = None):
        return self._send("GET", "/jurisdictions", None, headers, params)

    def get_jurisdiction(self, jurisdiction_id: str, headers):
        return self._send("GET", f"/jurisdictions/{jurisdiction_id}", None, headers)

    def patch_jurisdiction(self, jurisdiction_id: str, payload: Dict[str, Any], headers):
        return self._send("PATCH", f"/jurisdictions/{jurisdiction_id}", payload, headers)

    # ------------------------------------------------------------------
    # Installers and their credentials
    # ------------------------------------------------------------------
    def create_installer(self, payload: Dict[str, Any], headers):
        return self._send("POST", "/installers", payload, headers)

    def list_installers(self, headers, params: Optional[Dict] = None):
        return self._send("GET", "/installers", None, headers, params)

    def get_installer(self, installer_id: str, headers):
        return self._send("GET", f"/installers/{installer_id}", None, headers)

    def patch_installer(self, installer_id: str, payload: Dict[str, Any], headers):
        return self._send("PATCH", f"/installers/{installer_id}", payload, headers)

    def create_credential(self, installer_id: str, payload: Dict[str, Any], headers):
        return self._send(
            "POST", f"/installers/{installer_id}/credentials", payload, headers
        )

    def list_installer_credentials(self, installer_id: str, headers,
                                   params: Optional[Dict] = None):
        return self._send(
            "GET", f"/installers/{installer_id}/credentials", None, headers, params
        )

    def list_credentials(self, headers, params: Optional[Dict] = None):
        return self._send("GET", "/installer-credentials", None, headers, params)

    def get_credential(self, credential_id: str, headers):
        return self._send(
            "GET", f"/installer-credentials/{credential_id}", None, headers
        )

    def verify_credential(self, credential_id: str, payload: Dict[str, Any], headers):
        return self._send(
            "POST", f"/installer-credentials/{credential_id}/verify", payload, headers
        )

    def record_background_check(self, installer_id: str, payload: Dict[str, Any],
                                headers):
        return self._send(
            "POST", f"/installers/{installer_id}/background-check", payload, headers
        )

    def activate_installer(self, installer_id: str, headers, payload=None):
        return self._send(
            "POST", f"/installers/{installer_id}/activate", payload or {}, headers
        )

    def remove_installer(self, installer_id: str, payload: Dict[str, Any], headers):
        return self._send(
            "POST", f"/installers/{installer_id}/remove", payload, headers
        )

    # ------------------------------------------------------------------
    # Scorecard
    # ------------------------------------------------------------------
    def create_scorecard_event(self, installer_id: str, payload: Dict[str, Any],
                               headers):
        return self._send(
            "POST", f"/installers/{installer_id}/scorecard-events", payload, headers
        )

    def list_installer_scorecard_events(self, installer_id: str, headers,
                                        params: Optional[Dict] = None):
        return self._send(
            "GET", f"/installers/{installer_id}/scorecard-events", None, headers, params
        )

    def get_scorecard(self, installer_id: str, headers):
        return self._send(
            "GET", f"/installers/{installer_id}/scorecard", None, headers
        )

    def list_project_scorecard_events(self, project_id: str, headers,
                                      params: Optional[Dict] = None):
        return self._send(
            "GET", f"/projects/{project_id}/scorecard-events", None, headers, params
        )

    # ------------------------------------------------------------------
    # Customers
    # ------------------------------------------------------------------
    def create_customer(self, payload: Dict[str, Any], headers):
        return self._send("POST", "/customers", payload, headers)

    def list_customers(self, headers, params: Optional[Dict] = None):
        return self._send("GET", "/customers", None, headers, params)

    def get_customer(self, customer_id: str, headers):
        return self._send("GET", f"/customers/{customer_id}", None, headers)

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------
    def create_project(self, payload: Dict[str, Any], headers):
        return self._send("POST", "/projects", payload, headers)

    def list_projects(self, headers, params: Optional[Dict] = None):
        return self._send("GET", "/projects", None, headers, params)

    def get_project(self, project_id: str, headers):
        return self._send("GET", f"/projects/{project_id}", None, headers)

    def get_settlement_preview(self, project_id: str, headers):
        return self._send(
            "GET", f"/projects/{project_id}/settlement-preview", None, headers
        )

    def pay_deposit(self, project_id: str, payload: Dict[str, Any], headers):
        return self._send("POST", f"/projects/{project_id}/deposit", payload, headers)

    def pay_balance(self, project_id: str, payload: Dict[str, Any], headers):
        return self._send(
            "POST", f"/projects/{project_id}/pay-balance", payload, headers
        )

    def cancel_project(self, project_id: str, payload: Dict[str, Any], headers):
        return self._send("POST", f"/projects/{project_id}/cancel", payload, headers)

    def reinstate_project(self, project_id: str, payload: Dict[str, Any], headers):
        return self._send("POST", f"/projects/{project_id}/reinstate", payload, headers)

    def record_quality_inspection(self, project_id: str, payload: Dict[str, Any],
                                  headers):
        return self._send(
            "POST", f"/projects/{project_id}/quality-inspection", payload, headers
        )

    def close_project(self, project_id: str, headers, payload=None):
        return self._send(
            "POST", f"/projects/{project_id}/close", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Permits and inspections
    # ------------------------------------------------------------------
    def apply_permit(self, project_id: str, payload: Dict[str, Any], headers):
        return self._send(
            "POST", f"/projects/{project_id}/permit/apply", payload, headers
        )

    def issue_permit(self, project_id: str, payload: Dict[str, Any], headers):
        return self._send(
            "POST", f"/projects/{project_id}/permit/issue", payload, headers
        )

    def reserve_inspection_slot(self, project_id: str, payload: Dict[str, Any],
                                headers):
        return self._send(
            "POST", f"/projects/{project_id}/inspection-slot", payload, headers
        )

    def record_inspection_result(self, project_id: str, payload: Dict[str, Any],
                                 headers):
        return self._send(
            "POST", f"/projects/{project_id}/inspection-result", payload, headers
        )

    # ------------------------------------------------------------------
    # Measurements
    # ------------------------------------------------------------------
    def create_measurement(self, project_id: str, payload: Dict[str, Any], headers):
        return self._send(
            "POST", f"/projects/{project_id}/measurements", payload, headers
        )

    def list_project_measurements(self, project_id: str, headers,
                                  params: Optional[Dict] = None):
        return self._send(
            "GET", f"/projects/{project_id}/measurements", None, headers, params
        )

    def list_measurements(self, headers, params: Optional[Dict] = None):
        return self._send("GET", "/measurements", None, headers, params)

    def get_measurement(self, measurement_id: str, headers):
        return self._send("GET", f"/measurements/{measurement_id}", None, headers)

    def complete_measurement(self, measurement_id: str, payload: Dict[str, Any],
                             headers):
        return self._send(
            "POST", f"/measurements/{measurement_id}/complete", payload, headers
        )

    # ------------------------------------------------------------------
    # Change orders
    # ------------------------------------------------------------------
    def create_change_order(self, payload: Dict[str, Any], headers):
        return self._send("POST", "/change-orders", payload, headers)

    def list_project_change_orders(self, project_id: str, headers,
                                   params: Optional[Dict] = None):
        return self._send(
            "GET", f"/projects/{project_id}/change-orders", None, headers, params
        )

    def list_change_orders(self, headers, params: Optional[Dict] = None):
        return self._send("GET", "/change-orders", None, headers, params)

    def get_change_order(self, change_order_id: str, headers):
        return self._send("GET", f"/change-orders/{change_order_id}", None, headers)

    def submit_change_order(self, change_order_id: str, headers, payload=None):
        return self._send(
            "POST", f"/change-orders/{change_order_id}/submit", payload or {}, headers
        )

    def decide_change_order(self, change_order_id: str, payload: Dict[str, Any],
                            headers):
        return self._send(
            "POST", f"/change-orders/{change_order_id}/decide", payload, headers
        )

    # ------------------------------------------------------------------
    # Material deliveries
    # ------------------------------------------------------------------
    def create_material_delivery(self, project_id: str, payload: Dict[str, Any],
                                 headers):
        return self._send(
            "POST", f"/projects/{project_id}/material-deliveries", payload, headers
        )

    def list_project_material_deliveries(self, project_id: str, headers,
                                         params: Optional[Dict] = None):
        return self._send(
            "GET", f"/projects/{project_id}/material-deliveries", None, headers, params
        )

    def list_material_deliveries(self, headers, params: Optional[Dict] = None):
        return self._send("GET", "/material-deliveries", None, headers, params)

    def get_material_delivery(self, delivery_id: str, headers):
        return self._send("GET", f"/material-deliveries/{delivery_id}", None, headers)

    def update_delivery_status(self, delivery_id: str, payload: Dict[str, Any],
                               headers):
        return self._send(
            "POST", f"/material-deliveries/{delivery_id}/status", payload, headers
        )

    # ------------------------------------------------------------------
    # Installer assignments
    # ------------------------------------------------------------------
    def create_assignment(self, payload: Dict[str, Any], headers):
        return self._send("POST", "/installer-assignments", payload, headers)

    def list_assignments(self, headers, params: Optional[Dict] = None):
        return self._send("GET", "/installer-assignments", None, headers, params)

    def get_assignment(self, assignment_id: str, headers):
        return self._send(
            "GET", f"/installer-assignments/{assignment_id}", None, headers
        )

    def confirm_assignment(self, assignment_id: str, headers, payload=None):
        return self._send(
            "POST",
            f"/installer-assignments/{assignment_id}/confirm",
            payload or {},
            headers,
        )

    def start_assignment(self, assignment_id: str, headers, payload=None):
        return self._send(
            "POST",
            f"/installer-assignments/{assignment_id}/start",
            payload or {},
            headers,
        )

    def complete_assignment(self, assignment_id: str, payload: Dict[str, Any], headers):
        return self._send(
            "POST", f"/installer-assignments/{assignment_id}/complete", payload, headers
        )

    def release_assignment(self, assignment_id: str, payload: Dict[str, Any], headers):
        return self._send(
            "POST", f"/installer-assignments/{assignment_id}/release", payload, headers
        )

    # ------------------------------------------------------------------
    # Punch list
    # ------------------------------------------------------------------
    def list_project_punch_list_items(self, project_id: str, headers,
                                      params: Optional[Dict] = None):
        return self._send(
            "GET", f"/projects/{project_id}/punch-list-items", None, headers, params
        )

    def list_punch_list_items(self, headers, params: Optional[Dict] = None):
        return self._send("GET", "/punch-list-items", None, headers, params)

    def get_punch_list_item(self, item_id: str, headers):
        return self._send("GET", f"/punch-list-items/{item_id}", None, headers)

    def resolve_punch_item(self, item_id: str, payload: Dict[str, Any], headers):
        return self._send(
            "POST", f"/punch-list-items/{item_id}/resolve", payload, headers
        )

    def verify_punch_item(self, item_id: str, headers, payload=None):
        return self._send(
            "POST", f"/punch-list-items/{item_id}/verify", payload or {}, headers
        )

    def escalate_punch_item(self, item_id: str, payload: Dict[str, Any], headers):
        return self._send(
            "POST", f"/punch-list-items/{item_id}/escalate", payload, headers
        )

    # ------------------------------------------------------------------
    # Warranty claims
    # ------------------------------------------------------------------
    def create_warranty_claim(self, payload: Dict[str, Any], headers):
        return self._send("POST", "/warranty-claims", payload, headers)

    def list_warranty_claims(self, headers, params: Optional[Dict] = None):
        return self._send("GET", "/warranty-claims", None, headers, params)

    def get_warranty_claim(self, claim_id: str, headers):
        return self._send("GET", f"/warranty-claims/{claim_id}", None, headers)

    def triage_warranty_claim(self, claim_id: str, payload: Dict[str, Any], headers):
        return self._send(
            "POST", f"/warranty-claims/{claim_id}/triage", payload, headers
        )
