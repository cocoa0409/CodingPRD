"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/aftermarket"


class ApiClient(GenericApiClient):
    # ─── Logical clock ──────────────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ─── Part ───────────────────────────────────────────────────────────────
    def create_part(self, payload, headers):
        return self._request("POST", f"{PREFIX}/parts", payload, headers)

    def get_part(self, part_id, headers):
        return self._request("GET", f"{PREFIX}/parts/{part_id}", headers=headers)

    def list_parts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/parts", headers=headers, params=params)

    def patch_part(self, part_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/parts/{part_id}", payload, headers)

    def classify_part(self, part_id, headers):
        return self._request("POST", f"{PREFIX}/parts/{part_id}/classify", {}, headers)

    def phase_out_part(self, part_id, headers):
        return self._request("POST", f"{PREFIX}/parts/{part_id}/phase-out", {}, headers)

    def reinstate_part(self, part_id, headers):
        return self._request("POST", f"{PREFIX}/parts/{part_id}/reinstate", {}, headers)

    def supersede_part(self, part_id, successor_part_id, headers):
        return self._request("POST", f"{PREFIX}/parts/{part_id}/supersede",
                             {"successor_part_id": successor_part_id}, headers)

    def obsolete_part(self, part_id, headers):
        return self._request("POST", f"{PREFIX}/parts/{part_id}/obsolete", {}, headers)

    def list_ledger_entries(self, part_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/parts/{part_id}/ledger-entries",
                             headers=headers, params=params)

    def get_price_quote(self, part_id, qty, headers):
        return self._request("GET", f"{PREFIX}/parts/{part_id}/price-quote",
                             headers=headers, params={"qty": qty})

    # ─── EquipmentModel ─────────────────────────────────────────────────────
    def create_equipment_model(self, payload, headers):
        return self._request("POST", f"{PREFIX}/equipment-models", payload, headers)

    def get_equipment_model(self, model_id, headers):
        return self._request("GET", f"{PREFIX}/equipment-models/{model_id}",
                             headers=headers)

    # ─── InstalledUnit ──────────────────────────────────────────────────────
    def create_installed_unit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/installed-units", payload, headers)

    def get_installed_unit(self, unit_id, headers):
        return self._request("GET", f"{PREFIX}/installed-units/{unit_id}",
                             headers=headers)

    def list_installed_units(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/installed-units",
                             headers=headers, params=params)

    def decommission_installed_unit(self, unit_id, headers):
        return self._request("POST", f"{PREFIX}/installed-units/{unit_id}/decommission",
                             {}, headers)

    # ─── PartApplicability ──────────────────────────────────────────────────
    def create_part_applicability(self, payload, headers):
        return self._request("POST", f"{PREFIX}/part-applicabilities", payload, headers)

    def get_part_applicability(self, applicability_id, headers):
        return self._request("GET", f"{PREFIX}/part-applicabilities/{applicability_id}",
                             headers=headers)

    def list_part_applicabilities(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/part-applicabilities",
                             headers=headers, params=params)

    def withdraw_part_applicability(self, applicability_id, headers):
        return self._request(
            "POST", f"{PREFIX}/part-applicabilities/{applicability_id}/withdraw",
            {}, headers)

    # ─── Dealer ─────────────────────────────────────────────────────────────
    def create_dealer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/dealers", payload, headers)

    def get_dealer(self, dealer_id, headers):
        return self._request("GET", f"{PREFIX}/dealers/{dealer_id}", headers=headers)

    def adjust_dealer_balance(self, dealer_id, amount_cents, reason, headers):
        return self._request("POST", f"{PREFIX}/dealers/{dealer_id}/balance-adjustments",
                             {"amount_cents": amount_cents, "reason": reason}, headers)

    def suspend_dealer(self, dealer_id, headers):
        return self._request("POST", f"{PREFIX}/dealers/{dealer_id}/suspend", {}, headers)

    # ─── ServiceWorkOrder ───────────────────────────────────────────────────
    def create_work_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/work-orders", payload, headers)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"{PREFIX}/work-orders/{work_order_id}",
                             headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/work-orders", headers=headers,
                             params=params)

    def create_part_line(self, work_order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/work-orders/{work_order_id}/part-lines",
                             payload, headers)

    def close_work_order(self, work_order_id, headers):
        return self._request("POST", f"{PREFIX}/work-orders/{work_order_id}/close",
                             {}, headers)

    # ─── WorkOrderPartLine ──────────────────────────────────────────────────
    def get_part_line(self, line_id, headers):
        return self._request("GET", f"{PREFIX}/work-order-part-lines/{line_id}",
                             headers=headers)

    def list_part_lines(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/work-order-part-lines",
                             headers=headers, params=params)

    def consume_part_line(self, line_id, qty_consumed, headers):
        return self._request("POST",
                             f"{PREFIX}/work-order-part-lines/{line_id}/consume",
                             {"qty_consumed": qty_consumed}, headers)

    def cancel_part_line(self, line_id, headers):
        return self._request("POST",
                             f"{PREFIX}/work-order-part-lines/{line_id}/cancel",
                             {}, headers)

    # ─── DemandForecast ─────────────────────────────────────────────────────
    def create_forecast(self, part_id, payload, headers):
        return self._request("POST", f"{PREFIX}/parts/{part_id}/forecasts",
                             payload, headers)

    def list_forecasts(self, part_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/parts/{part_id}/forecasts",
                             headers=headers, params=params)

    # ─── LastTimeBuyCampaign ────────────────────────────────────────────────
    def create_campaign(self, payload, headers):
        return self._request("POST", f"{PREFIX}/last-time-buy-campaigns",
                             payload, headers)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"{PREFIX}/last-time-buy-campaigns/{campaign_id}",
                             headers=headers)

    def list_campaigns(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/last-time-buy-campaigns",
                             headers=headers, params=params)

    def submit_campaign(self, campaign_id, headers):
        return self._request(
            "POST", f"{PREFIX}/last-time-buy-campaigns/{campaign_id}/submit", {}, headers)

    def approve_campaign(self, campaign_id, approved_qty, headers):
        return self._request(
            "POST", f"{PREFIX}/last-time-buy-campaigns/{campaign_id}/approve",
            {"approved_qty": approved_qty}, headers)

    def reject_campaign(self, campaign_id, rejection_reason, headers):
        return self._request(
            "POST", f"{PREFIX}/last-time-buy-campaigns/{campaign_id}/reject",
            {"rejection_reason": rejection_reason}, headers)

    def revise_campaign(self, campaign_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/last-time-buy-campaigns/{campaign_id}/revise",
            payload, headers)

    def allocate_campaign(self, campaign_id, headers):
        return self._request(
            "POST", f"{PREFIX}/last-time-buy-campaigns/{campaign_id}/allocate",
            {}, headers)

    def close_campaign(self, campaign_id, headers):
        return self._request(
            "POST", f"{PREFIX}/last-time-buy-campaigns/{campaign_id}/close", {}, headers)

    # ─── AllocationRequest ──────────────────────────────────────────────────
    def create_allocation_request(self, payload, headers):
        return self._request("POST", f"{PREFIX}/allocation-requests", payload, headers)

    def get_allocation_request(self, request_id, headers):
        return self._request("GET", f"{PREFIX}/allocation-requests/{request_id}",
                             headers=headers)

    def list_allocation_requests(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/allocation-requests",
                             headers=headers, params=params)

    def withdraw_allocation_request(self, request_id, headers):
        return self._request("POST",
                             f"{PREFIX}/allocation-requests/{request_id}/withdraw",
                             {}, headers)

    # ─── AftermarketPriceRule ───────────────────────────────────────────────
    def create_price_rule(self, payload, headers):
        return self._request("POST", f"{PREFIX}/price-rules", payload, headers)

    def list_price_rules(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/price-rules", headers=headers,
                             params=params)

    # ─── ReplenishmentOrder ─────────────────────────────────────────────────
    def create_replenishment_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/replenishment-orders", payload, headers)

    def get_replenishment_order(self, order_id, headers):
        return self._request("GET", f"{PREFIX}/replenishment-orders/{order_id}",
                             headers=headers)

    def list_replenishment_orders(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/replenishment-orders",
                             headers=headers, params=params)

    def approve_replenishment_order(self, order_id, headers):
        return self._request("POST",
                             f"{PREFIX}/replenishment-orders/{order_id}/approve",
                             {}, headers)

    def reject_replenishment_order(self, order_id, headers, rejection_reason=None):
        payload = {} if rejection_reason is None else {"rejection_reason": rejection_reason}
        return self._request("POST",
                             f"{PREFIX}/replenishment-orders/{order_id}/reject",
                             payload, headers)

    def ship_replenishment_order(self, order_id, headers):
        return self._request("POST", f"{PREFIX}/replenishment-orders/{order_id}/ship",
                             {}, headers)

    def receive_replenishment_order(self, order_id, headers):
        return self._request("POST", f"{PREFIX}/replenishment-orders/{order_id}/receive",
                             {}, headers)

    # ─── ReturnAuthorization ────────────────────────────────────────────────
    def create_return_authorization(self, payload, headers):
        return self._request("POST", f"{PREFIX}/return-authorizations", payload, headers)

    def get_return_authorization(self, return_id, headers):
        return self._request("GET", f"{PREFIX}/return-authorizations/{return_id}",
                             headers=headers)

    def list_return_authorizations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/return-authorizations",
                             headers=headers, params=params)

    def approve_return_authorization(self, return_id, headers):
        return self._request("POST",
                             f"{PREFIX}/return-authorizations/{return_id}/approve",
                             {}, headers)

    def reject_return_authorization(self, return_id, headers, rejection_reason=None):
        payload = {} if rejection_reason is None else {"rejection_reason": rejection_reason}
        return self._request("POST",
                             f"{PREFIX}/return-authorizations/{return_id}/reject",
                             payload, headers)

    def receive_return_authorization(self, return_id, headers):
        return self._request("POST",
                             f"{PREFIX}/return-authorizations/{return_id}/receive",
                             {}, headers)

    def inspect_return_authorization(self, return_id, disposition, headers):
        return self._request("POST",
                             f"{PREFIX}/return-authorizations/{return_id}/inspect",
                             {"disposition": disposition}, headers)

    # ─── Raw escape hatch for header-omission tests ─────────────────────────
    def raw_post(self, path, payload, headers):
        return self._request("POST", path, payload, headers)


api_client = ApiClient()
