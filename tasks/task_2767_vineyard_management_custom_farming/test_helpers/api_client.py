"""API client: one method per endpoint defined in the PRD (§4)."""
from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Canonicalise an ISO 8601 UTC instant so sub-second width never matters.

    PRD §2.4 stamps timestamps "in ISO 8601 UTC with three fractional digits"
    while PRD §3.6 expresses derived clearance instants "to whole seconds", so
    a whole-second instant and the same instant with a ``.000`` fraction denote
    the same moment. Comparisons in the test suite go through this function
    rather than comparing raw strings.
    """
    if value is None:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1]
    if "+" in text[10:]:
        text = text[: 10 + text[10:].index("+")]
    if "." in text:
        base, frac = text.split(".", 1)
        frac = "".join(ch for ch in frac if ch.isdigit()).rstrip("0")
    else:
        base, frac = text, ""
    return f"{base}.{frac}Z" if frac else f"{base}Z"


class ApiClient(GenericApiClient):
    """Endpoint methods for the Vineyard Management & Custom Farming API."""

    # ─── Logical clock ────────────────────────────────
    def set_clock(self, current_utc: str, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ─── Ranches ──────────────────────────────────────
    def create_vineyard(self, payload, headers):
        return self._request("POST", "/vineyards", payload, headers)

    def get_vineyard(self, vineyard_id, headers):
        return self._request("GET", f"/vineyards/{vineyard_id}", headers=headers)

    # ─── Blocks ───────────────────────────────────────
    def create_block(self, payload, headers):
        return self._request("POST", "/blocks", payload, headers)

    def get_block(self, block_id, headers):
        return self._request("GET", f"/blocks/{block_id}", headers=headers)

    def list_blocks(self, headers, params=None):
        return self._request("GET", "/blocks", headers=headers, params=params)

    # ─── Pest observations ────────────────────────────
    def create_pest_observation(self, block_id, payload, headers):
        return self._request(
            "POST", f"/blocks/{block_id}/pest-observations", payload, headers
        )

    def list_pest_observations(self, block_id, headers, params=None):
        return self._request(
            "GET", f"/blocks/{block_id}/pest-observations", headers=headers, params=params
        )

    # ─── Yield estimates ──────────────────────────────
    def create_yield_estimate(self, block_id, payload, headers):
        return self._request(
            "POST", f"/blocks/{block_id}/yield-estimates", payload, headers
        )

    def list_yield_estimates(self, block_id, headers, params=None):
        return self._request(
            "GET", f"/blocks/{block_id}/yield-estimates", headers=headers, params=params
        )

    # ─── Custom-farming agreements ────────────────────
    def create_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    def enroll_block(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/contracts/{contract_id}/enroll-block", payload, headers
        )

    def activate_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/contracts/{contract_id}/activate", payload, headers
        )

    def settle_period(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/contracts/{contract_id}/settle-period", payload, headers
        )

    # ─── Farming plans ────────────────────────────────
    def create_farming_plan(self, payload, headers):
        return self._request("POST", "/farming-plans", payload, headers)

    def get_farming_plan(self, plan_id, headers):
        return self._request("GET", f"/farming-plans/{plan_id}", headers=headers)

    def list_farming_plans(self, headers, params=None):
        return self._request("GET", "/farming-plans", headers=headers, params=params)

    def submit_farming_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/farming-plans/{plan_id}/submit", payload or {}, headers
        )

    def return_farming_plan_for_revision(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/farming-plans/{plan_id}/return-for-revision", payload, headers
        )

    def approve_farming_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/farming-plans/{plan_id}/approve", payload or {}, headers
        )

    # ─── Labor crews ──────────────────────────────────
    def create_crew(self, payload, headers):
        return self._request("POST", "/crews", payload, headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/crews/{crew_id}", headers=headers)

    # ─── Work orders ──────────────────────────────────
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}", headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def start_work_order(self, work_order_id, headers, payload=None):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/start", payload or {}, headers
        )

    def complete_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/complete", payload, headers
        )

    def cancel_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/cancel", payload, headers
        )

    def advance_payroll(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/payroll", payload, headers
        )

    # ─── Irrigation events ────────────────────────────
    def create_irrigation_event(self, payload, headers):
        return self._request("POST", "/irrigation-events", payload, headers)

    def get_irrigation_event(self, event_id, headers):
        return self._request("GET", f"/irrigation-events/{event_id}", headers=headers)

    def list_irrigation_events(self, headers, params=None):
        return self._request("GET", "/irrigation-events", headers=headers, params=params)

    def record_irrigation_applied(self, event_id, payload, headers):
        return self._request(
            "POST", f"/irrigation-events/{event_id}/record-applied", payload, headers
        )

    # ─── Spray records ────────────────────────────────
    def create_spray_record(self, payload, headers):
        return self._request("POST", "/spray-records", payload, headers)

    def get_spray_record(self, spray_id, headers):
        return self._request("GET", f"/spray-records/{spray_id}", headers=headers)

    def list_spray_records(self, headers, params=None):
        return self._request("GET", "/spray-records", headers=headers, params=params)

    def apply_spray_record(self, spray_id, payload, headers):
        return self._request(
            "POST", f"/spray-records/{spray_id}/apply", payload, headers
        )

    def verify_spray_record(self, spray_id, headers, payload=None):
        return self._request(
            "POST", f"/spray-records/{spray_id}/verify", payload or {}, headers
        )

    # ─── Winery delivery windows ──────────────────────
    def create_delivery_window(self, payload, headers):
        return self._request("POST", "/delivery-windows", payload, headers)

    def get_delivery_window(self, window_id, headers):
        return self._request("GET", f"/delivery-windows/{window_id}", headers=headers)

    # ─── Harvest loads ────────────────────────────────
    def create_harvest_load(self, payload, headers):
        return self._request("POST", "/harvest-loads", payload, headers)

    def get_harvest_load(self, load_id, headers):
        return self._request("GET", f"/harvest-loads/{load_id}", headers=headers)

    def list_harvest_loads(self, headers, params=None):
        return self._request("GET", "/harvest-loads", headers=headers, params=params)

    def dispatch_harvest_load(self, load_id, payload, headers):
        return self._request(
            "POST", f"/harvest-loads/{load_id}/dispatch", payload, headers
        )

    def receive_harvest_load(self, load_id, payload, headers):
        return self._request(
            "POST", f"/harvest-loads/{load_id}/receive", payload, headers
        )

    def reject_harvest_load(self, load_id, payload, headers):
        return self._request(
            "POST", f"/harvest-loads/{load_id}/reject", payload, headers
        )


api_client = ApiClient()
