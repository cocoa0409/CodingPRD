"""One method per endpoint of the fleet planning and remarketing API.

Paths, HTTP verbs and query-filter names are transcribed from the endpoint
table in PRD section 4. Every method returns the raw response so callers can
assert on status codes.
"""

import re
from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/fleet"

_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})?$"
)


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO-8601 UTC instant to exactly three fractional digits.

    Sub-second width is a formatting difference, not a value difference, so
    comparisons of returned instants against expected literals go through
    this function on both sides.
    """
    if not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value.strip())
    if not match:
        return value
    seconds, fraction, _zone = match.groups()
    millis = (fraction or "")[:3].ljust(3, "0")
    return f"{seconds}.{millis}Z"


def _drop_none(params: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not params:
        return None
    trimmed = {k: v for k, v in params.items() if v is not None}
    return trimmed or None


class ApiClient(GenericApiClient):
    """Endpoint surface of the API under test."""

    # ----------------------------------------------------------------- clock
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{BASE}/_clock/set_current_utc", payload, headers)

    def get_clock(self, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{BASE}/_clock", headers=headers)

    # --------------------------------------------------------------- markets
    def create_market(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{BASE}/markets", payload, headers)

    def get_market(self, market_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{BASE}/markets/{market_id}", headers=headers)

    def list_markets(
        self,
        headers: Dict[str, str],
        region: Optional[str] = None,
        status: Optional[str] = None,
        code: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ) -> requests.Response:
        params = _drop_none(
            {
                "region": region,
                "status": status,
                "code": code,
                "limit": limit,
                "offset": offset,
            }
        )
        return self._request("GET", f"{BASE}/markets", params=params, headers=headers)

    def suspend_market(self, market_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{BASE}/markets/{market_id}/suspend", {}, headers)

    # ------------------------------------------------------- vehicle segments
    def create_vehicle_segment(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/vehicle-segments", payload, headers)

    def get_vehicle_segment(self, segment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{BASE}/vehicle-segments/{segment_id}", headers=headers)

    def list_vehicle_segments(
        self,
        headers: Dict[str, str],
        code: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ) -> requests.Response:
        params = _drop_none({"code": code, "limit": limit, "offset": offset})
        return self._request("GET", f"{BASE}/vehicle-segments", params=params, headers=headers)

    # -------------------------------------------------- manufacturer programs
    def create_manufacturer_program(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/manufacturer-programs", payload, headers)

    def get_manufacturer_program(
        self, program_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/manufacturer-programs/{program_id}", headers=headers
        )

    def list_manufacturer_programs(
        self,
        headers: Dict[str, str],
        program_type: Optional[str] = None,
        program_year: Optional[Any] = None,
        status: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ) -> requests.Response:
        params = _drop_none(
            {
                "program_type": program_type,
                "program_year": program_year,
                "status": status,
                "limit": limit,
                "offset": offset,
            }
        )
        return self._request(
            "GET", f"{BASE}/manufacturer-programs", params=params, headers=headers
        )

    def close_manufacturer_program(
        self, program_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/manufacturer-programs/{program_id}/close", {}, headers
        )

    # -------------------------------------------------- remarketing channels
    def create_remarketing_channel(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/remarketing-channels", payload, headers)

    def get_remarketing_channel(
        self, channel_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/remarketing-channels/{channel_id}", headers=headers
        )

    def list_remarketing_channels(
        self,
        headers: Dict[str, str],
        code: Optional[str] = None,
        status: Optional[str] = None,
        recondition_required: Optional[Any] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ) -> requests.Response:
        params = _drop_none(
            {
                "code": code,
                "status": status,
                "recondition_required": recondition_required,
                "limit": limit,
                "offset": offset,
            }
        )
        return self._request(
            "GET", f"{BASE}/remarketing-channels", params=params, headers=headers
        )

    def suspend_remarketing_channel(
        self, channel_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/remarketing-channels/{channel_id}/suspend", {}, headers
        )

    # ------------------------------------------------- depreciation policies
    def create_depreciation_policy(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/depreciation-policies", payload, headers)

    def get_depreciation_policy(
        self, policy_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/depreciation-policies/{policy_id}", headers=headers
        )

    def list_depreciation_policies(
        self,
        headers: Dict[str, str],
        segment_id: Optional[str] = None,
        supersedes_policy_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ) -> requests.Response:
        params = _drop_none(
            {
                "segment_id": segment_id,
                "supersedes_policy_id": supersedes_policy_id,
                "status": status,
                "limit": limit,
                "offset": offset,
            }
        )
        return self._request(
            "GET", f"{BASE}/depreciation-policies", params=params, headers=headers
        )

    def activate_depreciation_policy(
        self, policy_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/depreciation-policies/{policy_id}/activate", {}, headers
        )

    # ----------------------------------------------------------- fleet plans
    def create_fleet_plan(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/fleet-plans", payload, headers)

    def get_fleet_plan(self, plan_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{BASE}/fleet-plans/{plan_id}", headers=headers)

    def list_fleet_plans(
        self,
        headers: Dict[str, str],
        market_id: Optional[str] = None,
        season: Optional[str] = None,
        plan_year: Optional[Any] = None,
        status: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ) -> requests.Response:
        params = _drop_none(
            {
                "market_id": market_id,
                "season": season,
                "plan_year": plan_year,
                "status": status,
                "limit": limit,
                "offset": offset,
            }
        )
        return self._request("GET", f"{BASE}/fleet-plans", params=params, headers=headers)

    def lock_fleet_plan(self, plan_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{BASE}/fleet-plans/{plan_id}/lock", {}, headers)

    def create_purchase_allocation(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/fleet-plans/{plan_id}/allocations", payload, headers
        )

    def get_plan_performance(
        self, plan_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/fleet-plans/{plan_id}/performance", headers=headers
        )

    # --------------------------------------------------- purchase allocations
    def get_purchase_allocation(
        self, allocation_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/purchase-allocations/{allocation_id}", headers=headers
        )

    def list_purchase_allocations(
        self,
        headers: Dict[str, str],
        plan_id: Optional[str] = None,
        program_id: Optional[str] = None,
        segment_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ) -> requests.Response:
        params = _drop_none(
            {
                "plan_id": plan_id,
                "program_id": program_id,
                "segment_id": segment_id,
                "status": status,
                "limit": limit,
                "offset": offset,
            }
        )
        return self._request(
            "GET", f"{BASE}/purchase-allocations", params=params, headers=headers
        )

    def cancel_purchase_allocation(
        self, allocation_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/purchase-allocations/{allocation_id}/cancel", {}, headers
        )

    def create_vehicle(
        self, allocation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/purchase-allocations/{allocation_id}/vehicles", payload, headers
        )

    # -------------------------------------------------------------- vehicles
    def get_vehicle(self, vehicle_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{BASE}/vehicles/{vehicle_id}", headers=headers)

    def list_vehicles(
        self,
        headers: Dict[str, str],
        allocation_id: Optional[str] = None,
        segment_id: Optional[str] = None,
        program_id: Optional[str] = None,
        current_market_id: Optional[str] = None,
        fleet_status: Optional[str] = None,
        condition_status: Optional[str] = None,
        vin: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ) -> requests.Response:
        params = _drop_none(
            {
                "allocation_id": allocation_id,
                "segment_id": segment_id,
                "program_id": program_id,
                "current_market_id": current_market_id,
                "fleet_status": fleet_status,
                "condition_status": condition_status,
                "vin": vin,
                "limit": limit,
                "offset": offset,
            }
        )
        return self._request("GET", f"{BASE}/vehicles", params=params, headers=headers)

    def in_fleet_vehicle(self, vehicle_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{BASE}/vehicles/{vehicle_id}/in-fleet", {}, headers)

    def post_usage(
        self, vehicle_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/vehicles/{vehicle_id}/usage", payload, headers)

    def get_valuation(self, vehicle_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{BASE}/vehicles/{vehicle_id}/valuation", headers=headers)

    def get_channel_recommendation(
        self, vehicle_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/vehicles/{vehicle_id}/channel-recommendation", headers=headers
        )

    def list_vehicle_ledger_entries(
        self,
        vehicle_id: str,
        headers: Dict[str, str],
        entry_type: Optional[str] = None,
        source_entity_type: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ) -> requests.Response:
        params = _drop_none(
            {
                "entry_type": entry_type,
                "source_entity_type": source_entity_type,
                "limit": limit,
                "offset": offset,
            }
        )
        return self._request(
            "GET", f"{BASE}/vehicles/{vehicle_id}/ledger-entries", params=params, headers=headers
        )

    # --------------------------------------------------------- ledger entries
    def get_ledger_entry(
        self, ledger_entry_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/ledger-entries/{ledger_entry_id}", headers=headers
        )

    def list_ledger_entries(
        self,
        headers: Dict[str, str],
        vehicle_id: Optional[str] = None,
        entry_type: Optional[str] = None,
        source_entity_type: Optional[str] = None,
        source_entity_id: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ) -> requests.Response:
        params = _drop_none(
            {
                "vehicle_id": vehicle_id,
                "entry_type": entry_type,
                "source_entity_type": source_entity_type,
                "source_entity_id": source_entity_id,
                "limit": limit,
                "offset": offset,
            }
        )
        return self._request("GET", f"{BASE}/ledger-entries", params=params, headers=headers)

    # ------------------------------------------------------ in-fleeting tasks
    def create_in_fleeting_task(
        self, vehicle_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/vehicles/{vehicle_id}/in-fleeting-tasks", payload, headers
        )

    def get_in_fleeting_task(self, task_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{BASE}/in-fleeting-tasks/{task_id}", headers=headers)

    def list_in_fleeting_tasks(
        self,
        headers: Dict[str, str],
        vehicle_id: Optional[str] = None,
        market_id: Optional[str] = None,
        task_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ) -> requests.Response:
        params = _drop_none(
            {
                "vehicle_id": vehicle_id,
                "market_id": market_id,
                "task_type": task_type,
                "status": status,
                "limit": limit,
                "offset": offset,
            }
        )
        return self._request(
            "GET", f"{BASE}/in-fleeting-tasks", params=params, headers=headers
        )

    def complete_in_fleeting_task(
        self, task_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/in-fleeting-tasks/{task_id}/complete", {}, headers
        )

    def waive_in_fleeting_task(self, task_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{BASE}/in-fleeting-tasks/{task_id}/waive", {}, headers)

    # ------------------------------------------------- redistribution orders
    def create_redistribution_order(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/redistribution-orders", payload, headers)

    def get_redistribution_order(
        self, order_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/redistribution-orders/{order_id}", headers=headers
        )

    def list_redistribution_orders(
        self,
        headers: Dict[str, str],
        vehicle_id: Optional[str] = None,
        origin_market_id: Optional[str] = None,
        destination_market_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ) -> requests.Response:
        params = _drop_none(
            {
                "vehicle_id": vehicle_id,
                "origin_market_id": origin_market_id,
                "destination_market_id": destination_market_id,
                "status": status,
                "limit": limit,
                "offset": offset,
            }
        )
        return self._request(
            "GET", f"{BASE}/redistribution-orders", params=params, headers=headers
        )

    def propose_order(self, order_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/redistribution-orders/{order_id}/propose", {}, headers
        )

    def reject_order(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/redistribution-orders/{order_id}/reject", payload, headers
        )

    def authorize_order(self, order_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/redistribution-orders/{order_id}/authorize", {}, headers
        )

    def depart_order(self, order_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/redistribution-orders/{order_id}/depart", {}, headers
        )

    def receive_order(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/redistribution-orders/{order_id}/receive", payload, headers
        )

    def cancel_order(self, order_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/redistribution-orders/{order_id}/cancel", {}, headers
        )

    # ----------------------------------------------------------- damage events
    def create_damage_event(
        self, vehicle_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/vehicles/{vehicle_id}/damage-events", payload, headers
        )

    def get_damage_event(
        self, damage_event_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/damage-events/{damage_event_id}", headers=headers)

    def list_damage_events(
        self,
        headers: Dict[str, str],
        vehicle_id: Optional[str] = None,
        market_id: Optional[str] = None,
        damage_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ) -> requests.Response:
        params = _drop_none(
            {
                "vehicle_id": vehicle_id,
                "market_id": market_id,
                "damage_type": damage_type,
                "status": status,
                "limit": limit,
                "offset": offset,
            }
        )
        return self._request("GET", f"{BASE}/damage-events", params=params, headers=headers)

    def revise_damage_estimate(
        self, damage_event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/damage-events/{damage_event_id}/revise-estimate", payload, headers
        )

    def open_damage_recovery(
        self, damage_event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/damage-events/{damage_event_id}/open-recovery", payload, headers
        )

    def settle_damage_recovery(
        self, damage_event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/damage-events/{damage_event_id}/settle-recovery", payload, headers
        )

    def write_off_damage_event(
        self, damage_event_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/damage-events/{damage_event_id}/write-off", {}, headers
        )

    def declare_total_loss(
        self, damage_event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/damage-events/{damage_event_id}/declare-total-loss",
            payload,
            headers,
        )

    # ------------------------------------------------------------ consignments
    def create_consignment(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/consignments", payload, headers)

    def get_consignment(
        self, consignment_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/consignments/{consignment_id}", headers=headers)

    def list_consignments(
        self,
        headers: Dict[str, str],
        vehicle_id: Optional[str] = None,
        channel_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ) -> requests.Response:
        params = _drop_none(
            {
                "vehicle_id": vehicle_id,
                "channel_id": channel_id,
                "status": status,
                "limit": limit,
                "offset": offset,
            }
        )
        return self._request("GET", f"{BASE}/consignments", params=params, headers=headers)

    def authorize_recondition(
        self, consignment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/consignments/{consignment_id}/authorize-recondition",
            payload,
            headers,
        )

    def complete_recondition(
        self, consignment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/consignments/{consignment_id}/complete-recondition",
            payload,
            headers,
        )

    def list_consignment(
        self, consignment_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """Publish a DRAFT or RECONDITION_PENDING consignment to LISTED."""
        return self._request(
            "POST", f"{BASE}/consignments/{consignment_id}/list", {}, headers
        )

    def record_sale(
        self, consignment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/consignments/{consignment_id}/record-sale", payload, headers
        )

    def settle_consignment(
        self, consignment_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/consignments/{consignment_id}/settle", {}, headers
        )

    def withdraw_consignment(
        self, consignment_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/consignments/{consignment_id}/withdraw", {}, headers
        )
