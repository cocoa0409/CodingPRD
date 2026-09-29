"""
Endpoint client for the Ethanol Plant Operations API (PRD section 4).

One method per row of the endpoint table, all mounted beneath `/ethanol-ops`.
Every method returns the raw `requests.Response` so tests can assert status
codes as well as bodies.

Instant handling
----------------
The PRD writes instants as ISO 8601 UTC and stamps stored `created_at` values
with exactly three fractional digits, while request literals are usually
written without a fractional part.  `canonical_instant()` reduces any of those
spellings to a single second-resolution form so that comparing
`2026-09-04T06:00:00Z` with `2026-09-04T06:00:00.000Z` never fails, which
matches the PRD's own statement that instants are compared at second
resolution in UTC.
"""

import re
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX

_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:?\d{2})?$"
)


def canonical_instant(value: Any) -> Any:
    """
    Reduce an ISO 8601 UTC instant to `YYYY-MM-DDTHH:MM:SSZ`.

    Sub-second digits are discarded and a missing zone is treated as UTC.
    Anything that is not an instant-shaped string is returned untouched so the
    helper can be applied blindly to a field that may be null.
    """
    if not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value.strip())
    if not match:
        return value
    year, month, day, hour, minute, second = match.groups()[:6]
    return f"{year}-{month}-{day}T{hour}:{minute}:{second}Z"


def instants_equal(left: Any, right: Any) -> bool:
    """Precision-insensitive equality between two instants."""
    return canonical_instant(left) == canonical_instant(right)


class EthanolOpsApiClient(GenericApiClient):
    """Typed access to every endpoint of the Ethanol Plant Operations API."""

    # ─── Logical clock ─────────────────────────────────
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

    # ─── Plant ─────────────────────────────────────────
    def create_plant(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/plants", payload, headers)

    def get_plant(self, plant_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{API_PREFIX}/plants/{plant_id}", None, headers)

    def post_market_marks(self, plant_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/plants/{plant_id}/market-marks", payload, headers
        )

    def get_crush_margin(self, plant_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/plants/{plant_id}/crush-margin", None, headers
        )

    # ─── Corn purchase contracts ───────────────────────
    def create_contract(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/corn-contracts", payload, headers)

    def get_contract(self, contract_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/corn-contracts/{contract_id}", None, headers
        )

    def list_contracts(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/corn-contracts", params or {}, headers
        )

    def price_contract(self, contract_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/corn-contracts/{contract_id}/price", payload, headers
        )

    def roll_contract(self, contract_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/corn-contracts/{contract_id}/roll", payload, headers
        )

    def list_contract_deliveries(
        self, contract_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/corn-contracts/{contract_id}/deliveries",
            params or {},
            headers,
        )

    def create_delivery(self, contract_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{API_PREFIX}/corn-contracts/{contract_id}/deliveries",
            payload,
            headers,
        )

    # ─── Inbound deliveries ────────────────────────────
    def get_delivery(self, delivery_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/corn-deliveries/{delivery_id}", None, headers
        )

    def grade_delivery(self, delivery_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{API_PREFIX}/corn-deliveries/{delivery_id}/grade",
            payload,
            headers,
        )

    def settle_delivery(self, delivery_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/corn-deliveries/{delivery_id}/settle", {}, headers
        )

    # ─── Fermentation batches ──────────────────────────
    def create_batch(self, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/fermentation-batches", payload, headers
        )

    def get_batch(self, batch_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/fermentation-batches/{batch_id}", None, headers
        )

    def create_health_reading(
        self, batch_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/fermentation-batches/{batch_id}/health-readings",
            payload,
            headers,
        )

    def list_health_readings(
        self, batch_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/fermentation-batches/{batch_id}/health-readings",
            params or {},
            headers,
        )

    def intervene_batch(self, batch_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{API_PREFIX}/fermentation-batches/{batch_id}/intervene",
            payload,
            headers,
        )

    def distill_batch(self, batch_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/fermentation-batches/{batch_id}/distill", {}, headers
        )

    def complete_batch(self, batch_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/fermentation-batches/{batch_id}/complete", {}, headers
        )

    def dump_batch(self, batch_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{API_PREFIX}/fermentation-batches/{batch_id}/dump",
            payload,
            headers,
        )

    # ─── Product tanks ─────────────────────────────────
    def create_tank(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/product-tanks", payload, headers)

    def get_tank(self, tank_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/product-tanks/{tank_id}", None, headers
        )

    def list_tank_batches(
        self, tank_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/product-tanks/{tank_id}/batches",
            params or {},
            headers,
        )

    def list_tank_blends(
        self, tank_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/product-tanks/{tank_id}/denaturant-blends",
            params or {},
            headers,
        )

    def hold_tank(self, tank_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/product-tanks/{tank_id}/hold", payload, headers
        )

    def release_tank(self, tank_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/product-tanks/{tank_id}/release", {}, headers
        )

    # ─── Denaturant blends ─────────────────────────────
    def create_blend(self, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/denaturant-blends", payload, headers
        )

    def get_blend(self, blend_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/denaturant-blends/{blend_id}", None, headers
        )

    def execute_blend(self, blend_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/denaturant-blends/{blend_id}/execute", {}, headers
        )

    # ─── Loading tracks ────────────────────────────────
    def create_track(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/loading-tracks", payload, headers)

    def get_track(self, track_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/loading-tracks/{track_id}", None, headers
        )

    # ─── Unit train shipments ──────────────────────────
    def create_shipment(self, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/unit-train-shipments", payload, headers
        )

    def get_shipment(self, shipment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/unit-train-shipments/{shipment_id}", None, headers
        )

    def list_shipments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/unit-train-shipments", params or {}, headers
        )

    def load_shipment(self, shipment_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{API_PREFIX}/unit-train-shipments/{shipment_id}/load",
            {},
            headers,
        )

    def issue_bill_of_lading(
        self, shipment_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/unit-train-shipments/{shipment_id}/bill-of-lading",
            payload,
            headers,
        )

    def invoice_shipment(self, shipment_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{API_PREFIX}/unit-train-shipments/{shipment_id}/invoice",
            {},
            headers,
        )

    def cancel_shipment(self, shipment_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{API_PREFIX}/unit-train-shipments/{shipment_id}/cancel",
            payload,
            headers,
        )

    # ─── Co-product sales ──────────────────────────────
    def create_sale(self, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/co-product-sales", payload, headers
        )

    def get_sale(self, sale_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/co-product-sales/{sale_id}", None, headers
        )

    def list_sales(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/co-product-sales", params or {}, headers
        )

    def respond_to_sale(self, sale_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/co-product-sales/{sale_id}/respond", payload, headers
        )

    def ship_sale(self, sale_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/co-product-sales/{sale_id}/ship", {}, headers
        )

    # ─── Renewable credit batches ──────────────────────
    def get_rin_batch(self, rin_batch_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/rin-batches/{rin_batch_id}", None, headers
        )

    def list_rin_batches(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{API_PREFIX}/rin-batches", params or {}, headers)

    def retire_rin_batch(
        self, rin_batch_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/rin-batches/{rin_batch_id}/retire", payload, headers
        )

    # ─── Carbon projects ───────────────────────────────
    def create_carbon_project(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/carbon-projects", payload, headers)

    def get_carbon_project(self, project_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/carbon-projects/{project_id}", None, headers
        )

    def list_carbon_projects(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/carbon-projects", params or {}, headers
        )

    def submit_carbon_project(
        self, project_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/carbon-projects/{project_id}/submit",
            payload,
            headers,
        )

    def review_carbon_project(
        self, project_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/carbon-projects/{project_id}/review",
            payload,
            headers,
        )

    # ─── Hedge positions ───────────────────────────────
    def create_hedge_position(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/hedge-positions", payload, headers)

    def get_hedge_position(self, position_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/hedge-positions/{position_id}", None, headers
        )

    def list_hedge_positions(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/hedge-positions", params or {}, headers
        )

    def close_hedge_position(
        self, position_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/hedge-positions/{position_id}/close",
            payload,
            headers,
        )

    # ─── Permit conditions ─────────────────────────────
    def create_permit_condition(self, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/permit-conditions", payload, headers
        )

    def get_permit_condition(self, condition_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/permit-conditions/{condition_id}", None, headers
        )

    def list_permit_conditions(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/permit-conditions", params or {}, headers
        )

    def create_permit_reading(
        self, condition_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/permit-conditions/{condition_id}/readings",
            payload,
            headers,
        )

    def list_permit_readings(
        self, condition_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/permit-conditions/{condition_id}/readings",
            params or {},
            headers,
        )

    def resolve_deviation(
        self, condition_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/permit-conditions/{condition_id}/resolve-deviation",
            payload,
            headers,
        )
