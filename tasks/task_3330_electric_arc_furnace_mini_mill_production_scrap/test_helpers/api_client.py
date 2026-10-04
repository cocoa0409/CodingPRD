"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Mill ---
    def create_mill(self, payload, headers):
        return self._request("POST", "/mills", payload, headers)

    def list_mills(self, headers, params=None):
        return self._request("GET", "/mills", headers=headers, params=params)

    def get_mill(self, mill_id, headers):
        return self._request("GET", f"/mills/{mill_id}", headers=headers)

    # --- SurchargeIndex ---
    def publish_index(self, mill_id, payload, headers):
        return self._request("POST", f"/mills/{mill_id}/surcharge-indices", payload, headers)

    def list_indices(self, mill_id, headers, params=None):
        return self._request("GET", f"/mills/{mill_id}/surcharge-indices", headers=headers, params=params)

    def get_index(self, mill_id, index_id, headers):
        return self._request("GET", f"/mills/{mill_id}/surcharge-indices/by-id/{index_id}", headers=headers)

    # --- ProcurementContract ---
    def create_contract(self, mill_id, payload, headers):
        return self._request("POST", f"/mills/{mill_id}/procurement-contracts", payload, headers)

    def list_contracts(self, mill_id, headers, params=None):
        return self._request("GET", f"/mills/{mill_id}/procurement-contracts", headers=headers, params=params)

    def get_contract(self, mill_id, contract_id, headers):
        return self._request("GET", f"/mills/{mill_id}/procurement-contracts/{contract_id}", headers=headers)

    def close_contract(self, mill_id, contract_id, headers):
        return self._request("POST", f"/mills/{mill_id}/procurement-contracts/{contract_id}/close", {}, headers)

    def default_contract(self, mill_id, contract_id, headers):
        return self._request("POST", f"/mills/{mill_id}/procurement-contracts/{contract_id}/default", {}, headers)

    # --- ScrapLot ---
    def record_lot(self, mill_id, contract_id, payload, headers):
        return self._request("POST", f"/mills/{mill_id}/procurement-contracts/{contract_id}/scrap-lots", payload, headers)

    def list_lots_of_contract(self, mill_id, contract_id, headers, params=None):
        return self._request("GET", f"/mills/{mill_id}/procurement-contracts/{contract_id}/scrap-lots", headers=headers, params=params)

    def list_mill_lots(self, mill_id, headers, params=None):
        return self._request("GET", f"/mills/{mill_id}/scrap-lots", headers=headers, params=params)

    def get_lot(self, mill_id, lot_id, headers):
        return self._request("GET", f"/mills/{mill_id}/scrap-lots/by-id/{lot_id}", headers=headers)

    # --- Grade ---
    def create_grade(self, mill_id, payload, headers):
        return self._request("POST", f"/mills/{mill_id}/grades", payload, headers)

    def list_grades(self, mill_id, headers, params=None):
        return self._request("GET", f"/mills/{mill_id}/grades", headers=headers, params=params)

    def get_grade(self, mill_id, grade_id, headers):
        return self._request("GET", f"/mills/{mill_id}/grades/by-id/{grade_id}", headers=headers)

    # --- Heat ---
    def create_heat(self, mill_id, payload, headers):
        return self._request("POST", f"/mills/{mill_id}/heats", payload, headers)

    def list_heats(self, mill_id, headers, params=None):
        return self._request("GET", f"/mills/{mill_id}/heats", headers=headers, params=params)

    def get_heat(self, mill_id, heat_id, headers):
        return self._request("GET", f"/mills/{mill_id}/heats/{heat_id}", headers=headers)

    # --- HeatChargeLine ---
    def apply_charge(self, mill_id, heat_id, payload, headers):
        return self._request("POST", f"/mills/{mill_id}/heats/{heat_id}/charges", payload, headers)

    def list_charges(self, mill_id, heat_id, headers, params=None):
        return self._request("GET", f"/mills/{mill_id}/heats/{heat_id}/charges", headers=headers, params=params)

    # --- MeltdownSheet ---
    def create_sheet(self, mill_id, heat_id, payload, headers):
        return self._request("POST", f"/mills/{mill_id}/heats/{heat_id}/meltdown-sheets", payload, headers)

    def list_sheets(self, mill_id, heat_id, headers, params=None):
        return self._request("GET", f"/mills/{mill_id}/heats/{heat_id}/meltdown-sheets", headers=headers, params=params)

    def revise_sheet(self, mill_id, heat_id, sheet_id, payload, headers):
        return self._request("POST", f"/mills/{mill_id}/heats/{heat_id}/meltdown-sheets/{sheet_id}/revise", payload, headers)

    def confirm_sheet(self, mill_id, heat_id, sheet_id, headers):
        return self._request("POST", f"/mills/{mill_id}/heats/{heat_id}/meltdown-sheets/{sheet_id}/confirm", {}, headers)

    def reject_sheet(self, mill_id, heat_id, sheet_id, headers):
        return self._request("POST", f"/mills/{mill_id}/heats/{heat_id}/meltdown-sheets/{sheet_id}/reject", {}, headers)

    # --- Heat actions ---
    def tap_heat(self, mill_id, heat_id, headers):
        return self._request("POST", f"/mills/{mill_id}/heats/{heat_id}/tap", {}, headers)

    def cast_heat(self, mill_id, heat_id, headers):
        return self._request("POST", f"/mills/{mill_id}/heats/{heat_id}/cast", {}, headers)

    def abort_heat(self, mill_id, heat_id, headers):
        return self._request("POST", f"/mills/{mill_id}/heats/{heat_id}/abort", {}, headers)

    # --- EnergyInterval ---
    def record_interval(self, mill_id, heat_id, payload, headers):
        return self._request("POST", f"/mills/{mill_id}/heats/{heat_id}/energy-intervals", payload, headers)

    def list_intervals(self, mill_id, heat_id, headers, params=None):
        return self._request("GET", f"/mills/{mill_id}/heats/{heat_id}/energy-intervals", headers=headers, params=params)

    # --- MillTestReport ---
    def issue_mtr(self, mill_id, heat_id, payload, headers):
        return self._request("POST", f"/mills/{mill_id}/heats/{heat_id}/mill-test-reports", payload, headers)

    def list_mtrs(self, mill_id, heat_id, headers, params=None):
        return self._request("GET", f"/mills/{mill_id}/heats/{heat_id}/mill-test-reports", headers=headers, params=params)

    # --- Campaign ---
    def create_campaign(self, mill_id, payload, headers):
        return self._request("POST", f"/mills/{mill_id}/campaigns", payload, headers)

    def list_campaigns(self, mill_id, headers, params=None):
        return self._request("GET", f"/mills/{mill_id}/campaigns", headers=headers, params=params)

    def get_campaign(self, mill_id, campaign_id, headers):
        return self._request("GET", f"/mills/{mill_id}/campaigns/{campaign_id}", headers=headers)

    def add_campaign_line(self, mill_id, campaign_id, payload, headers):
        return self._request("POST", f"/mills/{mill_id}/campaigns/{campaign_id}/lines", payload, headers)

    def list_campaign_lines(self, mill_id, campaign_id, headers, params=None):
        return self._request("GET", f"/mills/{mill_id}/campaigns/{campaign_id}/lines", headers=headers, params=params)

    def commit_campaign(self, mill_id, campaign_id, payload, headers):
        return self._request("POST", f"/mills/{mill_id}/campaigns/{campaign_id}/commit", payload, headers)

    def close_campaign(self, mill_id, campaign_id, headers):
        return self._request("POST", f"/mills/{mill_id}/campaigns/{campaign_id}/close", {}, headers)

    def cancel_campaign(self, mill_id, campaign_id, headers):
        return self._request("POST", f"/mills/{mill_id}/campaigns/{campaign_id}/cancel", {}, headers)

    # --- CustomerAccount ---
    def create_account(self, mill_id, payload, headers):
        return self._request("POST", f"/mills/{mill_id}/customer-accounts", payload, headers)

    def list_accounts(self, mill_id, headers, params=None):
        return self._request("GET", f"/mills/{mill_id}/customer-accounts", headers=headers, params=params)

    def get_account(self, mill_id, account_id, headers):
        return self._request("GET", f"/mills/{mill_id}/customer-accounts/{account_id}", headers=headers)

    def patch_account(self, mill_id, account_id, payload, headers):
        return self._request("PATCH", f"/mills/{mill_id}/customer-accounts/{account_id}", payload, headers)

    # --- Order ---
    def create_order(self, mill_id, account_id, payload, headers):
        return self._request("POST", f"/mills/{mill_id}/customer-accounts/{account_id}/orders", payload, headers)

    def list_orders(self, mill_id, account_id, headers, params=None):
        return self._request("GET", f"/mills/{mill_id}/customer-accounts/{account_id}/orders", headers=headers, params=params)

    def get_order(self, mill_id, order_id, headers):
        return self._request("GET", f"/mills/{mill_id}/orders/{order_id}", headers=headers)

    def confirm_order(self, mill_id, account_id, order_id, payload, headers):
        return self._request("POST", f"/mills/{mill_id}/customer-accounts/{account_id}/orders/{order_id}/confirm", payload, headers)

    def invoice_order(self, mill_id, account_id, order_id, headers):
        return self._request("POST", f"/mills/{mill_id}/customer-accounts/{account_id}/orders/{order_id}/invoice", {}, headers)

    def cancel_order(self, mill_id, account_id, order_id, headers):
        return self._request("POST", f"/mills/{mill_id}/customer-accounts/{account_id}/orders/{order_id}/cancel", {}, headers)

    # --- Allocation ---
    def run_allocation(self, mill_id, headers):
        return self._request("POST", f"/mills/{mill_id}/allocation-runs", {}, headers)

    # --- InterruptibleWindow ---
    def create_window(self, mill_id, payload, headers):
        return self._request("POST", f"/mills/{mill_id}/interruptible-windows", payload, headers)

    def list_windows(self, mill_id, headers, params=None):
        return self._request("GET", f"/mills/{mill_id}/interruptible-windows", headers=headers, params=params)

    def get_window(self, mill_id, window_id, headers):
        return self._request("GET", f"/mills/{mill_id}/interruptible-windows/by-id/{window_id}", headers=headers)

    def honor_window(self, mill_id, window_id, headers):
        return self._request("POST", f"/mills/{mill_id}/interruptible-windows/{window_id}/honor", {}, headers)

    # --- EnergyEvent ---
    def declare_event(self, mill_id, payload, headers):
        return self._request("POST", f"/mills/{mill_id}/energy-events", payload, headers)

    def list_events(self, mill_id, headers, params=None):
        return self._request("GET", f"/mills/{mill_id}/energy-events", headers=headers, params=params)

    def get_event(self, mill_id, event_id, headers):
        return self._request("GET", f"/mills/{mill_id}/energy-events/by-id/{event_id}", headers=headers)

    def activate_event(self, mill_id, event_id, headers):
        return self._request("POST", f"/mills/{mill_id}/energy-events/{event_id}/activate", {}, headers)

    def release_event(self, mill_id, event_id, headers):
        return self._request("POST", f"/mills/{mill_id}/energy-events/{event_id}/release", {}, headers)

    # --- PowerInterruptionWaiver ---
    def grant_waiver(self, mill_id, payload, headers):
        return self._request("POST", f"/mills/{mill_id}/power-waivers", payload, headers)

    def list_waivers(self, mill_id, headers, params=None):
        return self._request("GET", f"/mills/{mill_id}/power-waivers", headers=headers, params=params)

    def get_waiver(self, mill_id, waiver_id, headers):
        return self._request("GET", f"/mills/{mill_id}/power-waivers/by-id/{waiver_id}", headers=headers)

    # --- DivisionScorecard ---
    def create_scorecard(self, mill_id, payload, headers):
        return self._request("POST", f"/mills/{mill_id}/division-scorecards", payload, headers)

    def list_scorecards(self, mill_id, headers, params=None):
        return self._request("GET", f"/mills/{mill_id}/division-scorecards", headers=headers, params=params)

    def get_scorecard(self, mill_id, scorecard_id, headers):
        return self._request("GET", f"/mills/{mill_id}/division-scorecards/{scorecard_id}", headers=headers)

    def close_scorecard(self, mill_id, scorecard_id, headers):
        return self._request("POST", f"/mills/{mill_id}/division-scorecards/{scorecard_id}/close", {}, headers)

    def distribute_scorecard(self, mill_id, scorecard_id, headers):
        return self._request("POST", f"/mills/{mill_id}/division-scorecards/{scorecard_id}/distribute", {}, headers)

    # --- Flat reads (org-wide) ---
    def flat_list_contracts(self, headers, params=None):
        return self._request("GET", "/mills/procurement-contracts", headers=headers, params=params)

    def flat_get_contract(self, contract_id, headers):
        return self._request("GET", f"/mills/procurement-contracts/{contract_id}", headers=headers)

    def flat_list_lots(self, headers, params=None):
        return self._request("GET", "/mills/scrap-lots", headers=headers, params=params)

    def flat_get_lot(self, lot_id, headers):
        return self._request("GET", f"/mills/scrap-lots/{lot_id}", headers=headers)

    def flat_list_grades(self, headers, params=None):
        return self._request("GET", "/mills/grades", headers=headers, params=params)

    def flat_get_grade(self, grade_id, headers):
        return self._request("GET", f"/mills/grades/{grade_id}", headers=headers)

    def flat_list_indices(self, headers, params=None):
        return self._request("GET", "/mills/surcharge-indices", headers=headers, params=params)

    def flat_get_index(self, index_id, headers):
        return self._request("GET", f"/mills/surcharge-indices/{index_id}", headers=headers)

    def flat_list_charges(self, headers, params=None):
        return self._request("GET", "/mills/charges", headers=headers, params=params)

    def flat_get_charge(self, line_id, headers):
        return self._request("GET", f"/mills/charges/{line_id}", headers=headers)

    def flat_list_sheets(self, headers, params=None):
        return self._request("GET", "/mills/meltdown-sheets", headers=headers, params=params)

    def flat_get_sheet(self, sheet_id, headers):
        return self._request("GET", f"/mills/meltdown-sheets/{sheet_id}", headers=headers)

    def flat_list_campaign_lines(self, headers, params=None):
        return self._request("GET", "/mills/campaign-lines", headers=headers, params=params)

    def flat_get_campaign_line(self, line_id, headers):
        return self._request("GET", f"/mills/campaign-lines/{line_id}", headers=headers)

    def flat_list_orders(self, headers, params=None):
        return self._request("GET", "/mills/orders", headers=headers, params=params)

    def flat_get_order(self, order_id, headers):
        return self._request("GET", f"/mills/orders/{order_id}", headers=headers)

    def flat_list_mtrs(self, headers, params=None):
        return self._request("GET", "/mills/mill-test-reports", headers=headers, params=params)

    def flat_get_mtr(self, mtr_id, headers):
        return self._request("GET", f"/mills/mill-test-reports/{mtr_id}", headers=headers)

    def flat_list_windows(self, headers, params=None):
        return self._request("GET", "/mills/interruptible-windows", headers=headers, params=params)

    def flat_get_window(self, window_id, headers):
        return self._request("GET", f"/mills/interruptible-windows/{window_id}", headers=headers)

    def flat_list_events(self, headers, params=None):
        return self._request("GET", "/mills/energy-events", headers=headers, params=params)

    def flat_get_event(self, event_id, headers):
        return self._request("GET", f"/mills/energy-events/{event_id}", headers=headers)

    def flat_list_waivers(self, headers, params=None):
        return self._request("GET", "/mills/power-waivers", headers=headers, params=params)

    def flat_get_waiver(self, waiver_id, headers):
        return self._request("GET", f"/mills/power-waivers/{waiver_id}", headers=headers)

    def flat_list_intervals(self, headers, params=None):
        return self._request("GET", "/mills/energy-intervals", headers=headers, params=params)

    def flat_get_interval(self, interval_id, headers):
        return self._request("GET", f"/mills/energy-intervals/{interval_id}", headers=headers)

    def flat_list_scorecards(self, headers, params=None):
        return self._request("GET", "/mills/division-scorecards", headers=headers, params=params)

    def flat_get_scorecard(self, scorecard_id, headers):
        return self._request("GET", f"/mills/division-scorecards/{scorecard_id}", headers=headers)

    def flat_list_heats(self, headers, params=None):
        return self._request("GET", "/mills/heats", headers=headers, params=params)

    def flat_get_heat(self, heat_id, headers):
        return self._request("GET", f"/mills/heats/{heat_id}", headers=headers)

    def flat_list_campaigns(self, headers, params=None):
        return self._request("GET", "/mills/campaigns", headers=headers, params=params)

    def flat_get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/mills/campaigns/{campaign_id}", headers=headers)

    def flat_list_accounts(self, headers, params=None):
        return self._request("GET", "/mills/customer-accounts", headers=headers, params=params)

    def flat_get_account(self, account_id, headers):
        return self._request("GET", f"/mills/customer-accounts/{account_id}", headers=headers)


api_client = ApiClient()
