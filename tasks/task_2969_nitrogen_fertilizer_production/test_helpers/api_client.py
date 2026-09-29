"""One method per endpoint of the Nitrogen Fertilizer Production API.

Every path is mounted under ``/nitrogen-ops`` (PRD section 4) and every path
parameter is named ``{id}``. Methods return the raw response so tests can
assert status codes as well as bodies.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX


def _params(**kwargs) -> Dict[str, Any]:
    """Drop unset query-string parameters so defaults stay server-side."""
    return {k: v for k, v in kwargs.items() if v is not None}


def _body(**kwargs) -> Dict[str, Any]:
    """Drop unset body fields so optional inputs stay genuinely absent.

    A field explicitly supplied as ``None`` is preserved, because sending an
    explicit JSON null is a different request from omitting the field.
    """
    return {k: v for k, v in kwargs.items() if v is not _UNSET}


class _Unset:
    def __repr__(self):  # pragma: no cover - debugging aid only
        return "<unset>"


_UNSET = _Unset()


class ApiClient(GenericApiClient):
    """Endpoint surface of the nitrogen operations service."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers,
        )

    # ------------------------------------------------------------------
    # Plant
    # ------------------------------------------------------------------
    def create_plant(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{API_PREFIX}/plants", payload, headers)

    def get_plant(self, plant_id: str, headers=None):
        return self._request("GET", f"{API_PREFIX}/plants/{plant_id}", None, headers)

    def list_plants(self, headers=None, limit=None, offset=None):
        return self._request(
            "GET", f"{API_PREFIX}/plants", _params(limit=limit, offset=offset), headers
        )

    def post_gas_index(self, plant_id: str, spot_gas_index_usd_per_mmbtu, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/plants/{plant_id}/gas-index",
            {"spot_gas_index_usd_per_mmbtu": spot_gas_index_usd_per_mmbtu},
            headers,
        )

    def post_permit_status(self, plant_id: str, permit_status: str, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/plants/{plant_id}/permit-status",
            {"permit_status": permit_status},
            headers,
        )

    def post_psm_program_status(self, plant_id: str, psm_program_status: str, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/plants/{plant_id}/psm-program-status",
            {"psm_program_status": psm_program_status},
            headers,
        )

    # ------------------------------------------------------------------
    # ReformerTrain
    # ------------------------------------------------------------------
    def create_reformer_train(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{API_PREFIX}/reformer-trains", payload, headers)

    def get_reformer_train(self, train_id: str, headers=None):
        return self._request(
            "GET", f"{API_PREFIX}/reformer-trains/{train_id}", None, headers
        )

    def list_reformer_trains(
        self, headers=None, plant_id=None, status=None, limit=None, offset=None
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/reformer-trains",
            _params(plant_id=plant_id, status=status, limit=limit, offset=offset),
            headers,
        )

    # ------------------------------------------------------------------
    # CatalystCharge
    # ------------------------------------------------------------------
    def create_catalyst_charge(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{API_PREFIX}/catalyst-charges", payload, headers)

    def get_catalyst_charge(self, charge_id: str, headers=None):
        return self._request(
            "GET", f"{API_PREFIX}/catalyst-charges/{charge_id}", None, headers
        )

    def list_catalyst_charges(
        self, headers=None, train_id=None, status=None, limit=None, offset=None
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/catalyst-charges",
            _params(train_id=train_id, status=status, limit=limit, offset=offset),
            headers,
        )

    def patch_catalyst_charge(self, charge_id: str, poisoning_index, headers=None):
        return self._request(
            "PATCH",
            f"{API_PREFIX}/catalyst-charges/{charge_id}",
            {"poisoning_index": poisoning_index},
            headers,
        )

    def regenerate_catalyst_charge(self, charge_id: str, headers=None):
        return self._request(
            "POST", f"{API_PREFIX}/catalyst-charges/{charge_id}/regenerate", {}, headers
        )

    # ------------------------------------------------------------------
    # GasHedgeLot
    # ------------------------------------------------------------------
    def create_gas_hedge_lot(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{API_PREFIX}/gas-hedge-lots", payload, headers)

    def get_gas_hedge_lot(self, lot_id: str, headers=None):
        return self._request(
            "GET", f"{API_PREFIX}/gas-hedge-lots/{lot_id}", None, headers
        )

    def list_gas_hedge_lots(
        self,
        headers=None,
        plant_id=None,
        status=None,
        delivery_month=None,
        limit=None,
        offset=None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/gas-hedge-lots",
            _params(
                plant_id=plant_id,
                status=status,
                delivery_month=delivery_month,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    # ------------------------------------------------------------------
    # ProductLine
    # ------------------------------------------------------------------
    def create_product_line(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{API_PREFIX}/product-lines", payload, headers)

    def get_product_line(self, line_id: str, headers=None):
        return self._request(
            "GET", f"{API_PREFIX}/product-lines/{line_id}", None, headers
        )

    def list_product_lines(self, headers=None, plant_id=None, limit=None, offset=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/product-lines",
            _params(plant_id=plant_id, limit=limit, offset=offset),
            headers,
        )

    # ------------------------------------------------------------------
    # ProductionRun
    # ------------------------------------------------------------------
    def create_production_run(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{API_PREFIX}/production-runs", payload, headers)

    def get_production_run(self, run_id: str, headers=None):
        return self._request(
            "GET", f"{API_PREFIX}/production-runs/{run_id}", None, headers
        )

    def list_production_runs(
        self,
        headers=None,
        train_id=None,
        catalyst_charge_id=None,
        status=None,
        limit=None,
        offset=None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/production-runs",
            _params(
                train_id=train_id,
                catalyst_charge_id=catalyst_charge_id,
                status=status,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def approve_production_run(self, run_id: str, headers=None):
        return self._request(
            "POST", f"{API_PREFIX}/production-runs/{run_id}/approve", {}, headers
        )

    def start_production_run(self, run_id: str, headers=None):
        return self._request(
            "POST", f"{API_PREFIX}/production-runs/{run_id}/start", {}, headers
        )

    def complete_production_run(
        self, run_id: str, actual_ammonia_tons, actual_operating_hours, headers=None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/production-runs/{run_id}/complete",
            {
                "actual_ammonia_tons": actual_ammonia_tons,
                "actual_operating_hours": actual_operating_hours,
            },
            headers,
        )

    def abort_production_run(self, run_id: str, abort_reason: str, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/production-runs/{run_id}/abort",
            {"abort_reason": abort_reason},
            headers,
        )

    def reopen_production_run(self, run_id: str, reopen_reason: str, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/production-runs/{run_id}/reopen",
            {"reopen_reason": reopen_reason},
            headers,
        )

    # ------------------------------------------------------------------
    # ProductionOrder
    # ------------------------------------------------------------------
    def create_production_order(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{API_PREFIX}/production-orders", payload, headers)

    def get_production_order(self, order_id: str, headers=None):
        return self._request(
            "GET", f"{API_PREFIX}/production-orders/{order_id}", None, headers
        )

    def list_production_orders(
        self,
        headers=None,
        run_id=None,
        product_line_id=None,
        destination_asset_id=None,
        allocation_status=None,
        security_status=None,
        limit=None,
        offset=None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/production-orders",
            _params(
                run_id=run_id,
                product_line_id=product_line_id,
                destination_asset_id=destination_asset_id,
                allocation_status=allocation_status,
                security_status=security_status,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def reserve_production_order(
        self, order_id: str, reserve_tons, expected_run_version, headers=None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/production-orders/{order_id}/reserve",
            {
                "reserve_tons": reserve_tons,
                "expected_run_version": expected_run_version,
            },
            headers,
        )

    def release_production_order(self, order_id: str, release_reason: str, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/production-orders/{order_id}/release",
            {"release_reason": release_reason},
            headers,
        )

    def security_check_production_order(self, order_id: str, decision: str, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/production-orders/{order_id}/security-check",
            {"decision": decision},
            headers,
        )

    def produce_production_order(self, order_id: str, produced_tons, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/production-orders/{order_id}/produce",
            {"produced_tons": produced_tons},
            headers,
        )

    # ------------------------------------------------------------------
    # StorageAsset
    # ------------------------------------------------------------------
    def create_storage_asset(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{API_PREFIX}/storage-assets", payload, headers)

    def get_storage_asset(self, asset_id: str, headers=None):
        return self._request(
            "GET", f"{API_PREFIX}/storage-assets/{asset_id}", None, headers
        )

    def list_storage_assets(
        self,
        headers=None,
        plant_id=None,
        asset_kind=None,
        product_code=None,
        limit=None,
        offset=None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/storage-assets",
            _params(
                plant_id=plant_id,
                asset_kind=asset_kind,
                product_code=product_code,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def set_opening_balance(self, asset_id: str, opening_balance_tons, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/storage-assets/{asset_id}/opening-balance",
            {"opening_balance_tons": opening_balance_tons},
            headers,
        )

    # ------------------------------------------------------------------
    # Shipment
    # ------------------------------------------------------------------
    def create_shipment(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{API_PREFIX}/shipments", payload, headers)

    def get_shipment(self, shipment_id: str, headers=None):
        return self._request(
            "GET", f"{API_PREFIX}/shipments/{shipment_id}", None, headers
        )

    def list_shipments(
        self,
        headers=None,
        origin_asset_id=None,
        dest_asset_id=None,
        production_order_id=None,
        status=None,
        mode=None,
        limit=None,
        offset=None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/shipments",
            _params(
                origin_asset_id=origin_asset_id,
                dest_asset_id=dest_asset_id,
                production_order_id=production_order_id,
                status=status,
                mode=mode,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def book_shipment(self, shipment_id: str, expected_origin_asset_version, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/shipments/{shipment_id}/book",
            {"expected_origin_asset_version": expected_origin_asset_version},
            headers,
        )

    def depart_shipment(self, shipment_id: str, headers=None):
        return self._request(
            "POST", f"{API_PREFIX}/shipments/{shipment_id}/depart", {}, headers
        )

    def deliver_shipment(self, shipment_id: str, received_tons, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/shipments/{shipment_id}/deliver",
            {"received_tons": received_tons},
            headers,
        )

    def cancel_shipment(self, shipment_id: str, cancel_reason: str, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/shipments/{shipment_id}/cancel",
            {"cancel_reason": cancel_reason},
            headers,
        )

    # ------------------------------------------------------------------
    # PriceQuote
    # ------------------------------------------------------------------
    def create_price_quote(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{API_PREFIX}/price-quotes", payload, headers)

    def get_price_quote(self, quote_id: str, headers=None):
        return self._request(
            "GET", f"{API_PREFIX}/price-quotes/{quote_id}", None, headers
        )

    def list_price_quotes(
        self,
        headers=None,
        plant_id=None,
        product_line_id=None,
        status=None,
        limit=None,
        offset=None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/price-quotes",
            _params(
                plant_id=plant_id,
                product_line_id=product_line_id,
                status=status,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def issue_price_quote(self, quote_id: str, headers=None):
        return self._request(
            "POST", f"{API_PREFIX}/price-quotes/{quote_id}/issue", {}, headers
        )

    def withdraw_price_quote(self, quote_id: str, withdraw_reason: str, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/price-quotes/{quote_id}/withdraw",
            {"withdraw_reason": withdraw_reason},
            headers,
        )

    def revise_price_quote(self, quote_id: str, payload: Optional[Dict[str, Any]] = None,
                           headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/price-quotes/{quote_id}/revise",
            payload if payload is not None else {},
            headers,
        )

    def expire_due_price_quotes(self, headers=None):
        return self._request("POST", f"{API_PREFIX}/price-quotes/expire-due", {}, headers)

    # ------------------------------------------------------------------
    # Turnaround
    # ------------------------------------------------------------------
    def create_turnaround(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{API_PREFIX}/turnarounds", payload, headers)

    def get_turnaround(self, turnaround_id: str, headers=None):
        return self._request(
            "GET", f"{API_PREFIX}/turnarounds/{turnaround_id}", None, headers
        )

    def list_turnarounds(
        self,
        headers=None,
        plant_id=None,
        train_id=None,
        status=None,
        scope=None,
        limit=None,
        offset=None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/turnarounds",
            _params(
                plant_id=plant_id,
                train_id=train_id,
                status=status,
                scope=scope,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def submit_turnaround(self, turnaround_id: str, headers=None):
        return self._request(
            "POST", f"{API_PREFIX}/turnarounds/{turnaround_id}/submit", {}, headers
        )

    def psm_review_turnaround(
        self, turnaround_id: str, decision: str, findings_count, headers=None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/turnarounds/{turnaround_id}/psm-review",
            {"decision": decision, "findings_count": findings_count},
            headers,
        )

    def approve_turnaround(self, turnaround_id: str, headers=None):
        return self._request(
            "POST", f"{API_PREFIX}/turnarounds/{turnaround_id}/approve", {}, headers
        )

    def reject_turnaround(self, turnaround_id: str, rejection_reason: str, headers=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/turnarounds/{turnaround_id}/reject",
            {"rejection_reason": rejection_reason},
            headers,
        )

    def revise_turnaround(self, turnaround_id: str, headers=None):
        return self._request(
            "POST", f"{API_PREFIX}/turnarounds/{turnaround_id}/revise", {}, headers
        )

    def start_turnaround(self, turnaround_id: str, headers=None):
        return self._request(
            "POST", f"{API_PREFIX}/turnarounds/{turnaround_id}/start", {}, headers
        )

    def complete_turnaround(
        self, turnaround_id: str, payload: Optional[Dict[str, Any]] = None, headers=None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/turnarounds/{turnaround_id}/complete",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # TurnaroundTask
    # ------------------------------------------------------------------
    def create_turnaround_task(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{API_PREFIX}/turnaround-tasks", payload, headers)

    def get_turnaround_task(self, task_id: str, headers=None):
        return self._request(
            "GET", f"{API_PREFIX}/turnaround-tasks/{task_id}", None, headers
        )

    def list_turnaround_tasks(
        self,
        headers=None,
        turnaround_id=None,
        predecessor_task_id=None,
        status=None,
        limit=None,
        offset=None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/turnaround-tasks",
            _params(
                turnaround_id=turnaround_id,
                predecessor_task_id=predecessor_task_id,
                status=status,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def complete_turnaround_task(self, task_id: str, headers=None):
        return self._request(
            "POST", f"{API_PREFIX}/turnaround-tasks/{task_id}/complete", {}, headers
        )

    # ------------------------------------------------------------------
    # EmissionsReading
    # ------------------------------------------------------------------
    def create_emissions_reading(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"{API_PREFIX}/emissions-readings", payload, headers)

    def get_emissions_reading(self, reading_id: str, headers=None):
        return self._request(
            "GET", f"{API_PREFIX}/emissions-readings/{reading_id}", None, headers
        )

    def list_emissions_readings(
        self, headers=None, plant_id=None, pollutant=None, limit=None, offset=None
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/emissions-readings",
            _params(plant_id=plant_id, pollutant=pollutant, limit=limit, offset=offset),
            headers,
        )

    # ------------------------------------------------------------------
    # Raw helpers for negative path tests
    # ------------------------------------------------------------------
    def raw_get(self, path: str, headers=None, params=None):
        """GET an absolute API path, for family-404 and header sweeps."""
        return self._request("GET", path, None, headers, params=params)

    def raw_post(self, path: str, payload=None, headers=None):
        """POST an absolute API path, for header and role sweeps."""
        return self._request("POST", path, payload if payload is not None else {}, headers)
