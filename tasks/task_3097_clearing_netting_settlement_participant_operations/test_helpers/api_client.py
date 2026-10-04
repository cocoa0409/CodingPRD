"""API client: one method per endpoint defined in the PRD §4 table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ─── logical clock ─────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/clearing/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ─── participants ──────────────────────────────────
    def create_participant(self, payload, headers):
        return self._request("POST", "/clearing/participants", payload, headers)

    def list_participants(self, headers, params=None):
        return self._request("GET", "/clearing/participants", headers=headers, params=params)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/clearing/participants/{participant_id}", headers=headers)

    def update_participant(self, participant_id, payload, headers):
        return self._request("PUT", f"/clearing/participants/{participant_id}", payload, headers)

    def financial_review(self, participant_id, payload, headers):
        return self._request("POST", f"/clearing/participants/{participant_id}/financial-review",
                             payload, headers)

    def activate_participant(self, participant_id, headers):
        return self._request("POST", f"/clearing/participants/{participant_id}/activate",
                             {}, headers)

    def suspend_participant(self, participant_id, headers):
        return self._request("POST", f"/clearing/participants/{participant_id}/suspend",
                             {}, headers)

    def reinstate_participant(self, participant_id, headers):
        return self._request("POST", f"/clearing/participants/{participant_id}/reinstate",
                             {}, headers)

    # ─── deposits ──────────────────────────────────────
    def list_participant_deposits(self, participant_id, headers):
        return self._request("GET", f"/clearing/participants/{participant_id}/deposits",
                             headers=headers)

    def list_deposits(self, headers, params=None):
        return self._request("GET", "/clearing/deposits", headers=headers, params=params)

    def get_deposit(self, deposit_id, headers):
        return self._request("GET", f"/clearing/deposits/{deposit_id}", headers=headers)

    def post_deposit_transaction(self, deposit_id, payload, headers):
        return self._request("POST", f"/clearing/deposits/{deposit_id}/postings",
                             payload, headers)

    def list_deposit_postings(self, deposit_id, headers, params=None):
        return self._request("GET", f"/clearing/deposits/{deposit_id}/postings",
                             headers=headers, params=params)

    def list_participant_deposit_postings(self, participant_id, headers, params=None):
        return self._request("GET", f"/clearing/participants/{participant_id}/deposit-postings",
                             headers=headers, params=params)

    def allocate_fund_cost(self, security_id, payload, headers):
        return self._request("POST", f"/clearing/securities/{security_id}/allocate-fund-cost",
                             payload, headers)

    # ─── securities ────────────────────────────────────
    def create_security(self, payload, headers):
        return self._request("POST", "/clearing/securities", payload, headers)

    def list_securities(self, headers, params=None):
        return self._request("GET", "/clearing/securities", headers=headers, params=params)

    def get_security(self, security_id, headers):
        return self._request("GET", f"/clearing/securities/{security_id}", headers=headers)

    def update_security(self, security_id, payload, headers):
        return self._request("PUT", f"/clearing/securities/{security_id}", payload, headers)

    # ─── custody ───────────────────────────────────────
    def create_custody_account(self, participant_id, payload, headers):
        return self._request("POST", f"/clearing/participants/{participant_id}/custody-accounts",
                             payload, headers)

    def list_custody_accounts(self, participant_id, headers):
        return self._request("GET", f"/clearing/participants/{participant_id}/custody-accounts",
                             headers=headers)

    # ─── settlement windows ────────────────────────────
    def create_settlement_window(self, payload, headers):
        return self._request("POST", "/clearing/settlement-windows", payload, headers)

    def list_settlement_windows(self, headers, params=None):
        return self._request("GET", "/clearing/settlement-windows", headers=headers, params=params)

    def get_settlement_window(self, window_id, headers):
        return self._request("GET", f"/clearing/settlement-windows/{window_id}", headers=headers)

    def update_settlement_window(self, window_id, payload, headers):
        return self._request("PUT", f"/clearing/settlement-windows/{window_id}", payload, headers)

    def net_window(self, window_id, payload, headers):
        return self._request("POST", f"/clearing/settlement-windows/{window_id}/net",
                             payload, headers)

    def run_cycle(self, window_id, payload, headers):
        return self._request("POST", f"/clearing/settlement-windows/{window_id}/run-cycle",
                             payload, headers)

    def settle_window(self, window_id, headers):
        return self._request("POST", f"/clearing/settlement-windows/{window_id}/settle",
                             {}, headers)

    def close_cycle(self, window_id, headers):
        return self._request("POST", f"/clearing/settlement-windows/{window_id}/close-cycle",
                             {}, headers)

    def affirm_window(self, window_id, headers):
        return self._request("POST", f"/clearing/settlement-windows/{window_id}/affirm",
                             {}, headers)

    # ─── trades ────────────────────────────────────────
    def create_trade_submission(self, payload, headers):
        return self._request("POST", "/clearing/trade-submissions", payload, headers)

    def list_trade_submissions(self, headers, params=None):
        return self._request("GET", "/clearing/trade-submissions", headers=headers, params=params)

    def get_trade_submission(self, trade_id, headers):
        return self._request("GET", f"/clearing/trade-submissions/{trade_id}", headers=headers)

    def lock_in_trade(self, trade_id, headers):
        return self._request("POST", f"/clearing/trade-submissions/{trade_id}/lock-in", {}, headers)

    def dispute_trade(self, trade_id, headers):
        return self._request("POST", f"/clearing/trade-submissions/{trade_id}/dispute", {}, headers)

    def resolve_dispute(self, trade_id, headers):
        return self._request("POST", f"/clearing/trade-submissions/{trade_id}/resolve-dispute",
                             {}, headers)

    def unmatch_trade(self, trade_id, headers):
        return self._request("POST", f"/clearing/trade-submissions/{trade_id}/unmatch", {}, headers)

    def cancel_trade(self, trade_id, headers):
        return self._request("POST", f"/clearing/trade-submissions/{trade_id}/cancel", {}, headers)

    # ─── net positions ─────────────────────────────────
    def list_net_positions(self, headers, params=None):
        return self._request("GET", "/clearing/net-positions", headers=headers, params=params)

    def get_net_position(self, net_position_id, headers):
        return self._request("GET", f"/clearing/net-positions/{net_position_id}", headers=headers)

    def list_participant_net_positions(self, participant_id, headers):
        return self._request("GET", f"/clearing/participants/{participant_id}/net-positions",
                             headers=headers)

    def fund_net_position(self, net_position_id, payload, headers):
        return self._request("POST", f"/clearing/net-positions/{net_position_id}/fund",
                             payload, headers)

    # ─── corporate actions ─────────────────────────────
    def create_corporate_action(self, payload, headers):
        return self._request("POST", "/clearing/corporate-actions", payload, headers)

    def list_corporate_actions(self, headers, params=None):
        return self._request("GET", "/clearing/corporate-actions", headers=headers, params=params)

    def list_security_corporate_actions(self, security_id, headers):
        return self._request("GET", f"/clearing/securities/{security_id}/corporate-actions",
                             headers=headers)

    def apply_corporate_action(self, action_id, headers):
        return self._request("POST", f"/clearing/corporate-actions/{action_id}/apply", {}, headers)

    def reverse_corporate_action(self, action_id, headers):
        return self._request("POST", f"/clearing/corporate-actions/{action_id}/reverse", {}, headers)

    # ─── clearing funds ────────────────────────────────
    def create_clearing_fund(self, payload, headers):
        return self._request("POST", "/clearing/clearing-funds", payload, headers)

    def list_clearing_funds(self, headers, params=None):
        return self._request("GET", "/clearing/clearing-funds", headers=headers, params=params)

    def list_security_clearing_funds(self, security_id, headers):
        return self._request("GET", f"/clearing/securities/{security_id}/clearing-funds",
                             headers=headers)

    def recompute_clearing_fund(self, fund_id, payload, headers):
        return self._request("POST", f"/clearing/clearing-funds/{fund_id}/recompute",
                             payload, headers)

    def get_clearing_fund(self, fund_id, headers):
        return self._request("GET", f"/clearing/clearing-funds/{fund_id}", headers=headers)

    def list_fund_components(self, fund_id, headers, params=None):
        return self._request("GET", f"/clearing/clearing-funds/{fund_id}/components",
                             headers=headers, params=params)

    def list_fund_components_all(self, headers, params=None):
        return self._request("GET", "/clearing/fund-components", headers=headers, params=params)

    def get_fund_component(self, component_id, headers):
        return self._request("GET", f"/clearing/fund-components/{component_id}", headers=headers)

    def list_component_loss_allocations(self, component_id, headers, params=None):
        return self._request("GET", f"/clearing/fund-components/{component_id}/loss-allocations",
                             headers=headers, params=params)

    def list_participant_fund_components(self, participant_id, headers):
        return self._request("GET", f"/clearing/participants/{participant_id}/fund-components",
                             headers=headers)

    # ─── default proceedings ───────────────────────────
    def create_default_proceeding(self, payload, headers):
        return self._request("POST", "/clearing/default-proceedings", payload, headers)

    def list_default_proceedings(self, headers, params=None):
        return self._request("GET", "/clearing/default-proceedings", headers=headers, params=params)

    def update_default_proceeding(self, proceeding_id, payload, headers):
        return self._request("PUT", f"/clearing/default-proceedings/{proceeding_id}",
                             payload, headers)

    def list_participant_default_proceedings(self, participant_id, headers):
        return self._request("GET", f"/clearing/participants/{participant_id}/default-proceedings",
                             headers=headers)

    def get_default_proceeding(self, proceeding_id, headers):
        return self._request("GET", f"/clearing/default-proceedings/{proceeding_id}", headers=headers)

    def place_bid(self, proceeding_id, payload, headers):
        return self._request("POST", f"/clearing/default-proceedings/{proceeding_id}/bids",
                             payload, headers)

    def liquidate_proceeding(self, proceeding_id, headers):
        return self._request("POST", f"/clearing/default-proceedings/{proceeding_id}/liquidate",
                             {}, headers)

    def allocate_loss(self, proceeding_id, headers):
        return self._request("POST", f"/clearing/default-proceedings/{proceeding_id}/allocate-loss",
                             {}, headers)

    def list_proceeding_loss_allocations(self, proceeding_id, headers, params=None):
        return self._request("GET", f"/clearing/default-proceedings/{proceeding_id}/loss-allocations",
                             headers=headers, params=params)

    def list_loss_allocations(self, headers, params=None):
        return self._request("GET", "/clearing/loss-allocations", headers=headers, params=params)


api_client = ApiClient()