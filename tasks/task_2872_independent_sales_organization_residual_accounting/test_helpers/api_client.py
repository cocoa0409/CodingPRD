"""API client: one method per endpoint defined in the PRD."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed access to every endpoint of the ISO Residual Accounting API."""

    # ------------------------------------------------------------------ clock
    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_clock_raw(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --------------------------------------------------- processor programs
    def create_processor_program(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/processor-programs", payload, headers)

    def list_processor_programs(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/processor-programs", headers=headers, params=params)

    def get_processor_program(self, program_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/processor-programs/{program_id}", headers=headers)

    def update_processor_program(self, program_id: str, payload: Any, headers: Dict[str, str]):
        return self._request("PATCH", f"/processor-programs/{program_id}", payload, headers)

    def suspend_processor_program(self, program_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/processor-programs/{program_id}/suspend", {}, headers
        )

    def reinstate_processor_program(self, program_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/processor-programs/{program_id}/reinstate", {}, headers
        )

    # ------------------------------------------------------------------ agents
    def create_agent(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/agents", payload, headers)

    def list_agents(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/agents", headers=headers, params=params)

    def get_agent(self, agent_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/agents/{agent_id}", headers=headers)

    def update_agent(self, agent_id: str, payload: Any, headers: Dict[str, str]):
        return self._request("PATCH", f"/agents/{agent_id}", payload, headers)

    def get_agent_portfolio_summary(self, agent_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/agents/{agent_id}/portfolio-summary", headers=headers
        )

    def file_agent_notice(self, agent_id: str, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"/agents/{agent_id}/notice", payload, headers)

    def rescind_agent_notice(self, agent_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/agents/{agent_id}/rescind-notice", {}, headers)

    def depart_agent(self, agent_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/agents/{agent_id}/depart", {}, headers)

    def transfer_agent_portfolio(self, agent_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/agents/{agent_id}/transfer-portfolio", payload, headers
        )

    # ---------------------------------------------------------------- advances
    def create_agent_advance(self, agent_id: str, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"/agents/{agent_id}/advances", payload, headers)

    def list_agent_advances(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/agent-advances", headers=headers, params=params)

    def get_agent_advance(self, advance_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/agent-advances/{advance_id}", headers=headers)

    def restructure_agent_advance(self, advance_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/agent-advances/{advance_id}/restructure", payload, headers
        )

    # --------------------------------------------------------------- merchants
    def create_merchant(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/merchants", payload, headers)

    def list_merchants(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/merchants", headers=headers, params=params)

    def get_merchant(self, merchant_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/merchants/{merchant_id}", headers=headers)

    def update_merchant(self, merchant_id: str, payload: Any, headers: Dict[str, str]):
        return self._request("PATCH", f"/merchants/{merchant_id}", payload, headers)

    def activate_merchant(self, merchant_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/merchants/{merchant_id}/activate", {}, headers)

    def attrite_merchant(self, merchant_id: str, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"/merchants/{merchant_id}/attrite", payload, headers)

    def reactivate_merchant(self, merchant_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/merchants/{merchant_id}/reactivate", payload, headers
        )

    def reassign_merchant_agent(self, merchant_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/merchants/{merchant_id}/reassign-agent", payload, headers
        )

    # ------------------------------------------------------- chargeback events
    def create_chargeback_event(self, merchant_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/merchants/{merchant_id}/chargebacks", payload, headers
        )

    def list_chargeback_events(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/chargeback-events", headers=headers, params=params)

    def get_chargeback_event(self, chargeback_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/chargeback-events/{chargeback_id}", headers=headers)

    # --------------------------------------------------------- residual batches
    def create_residual_batch(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/residual-batches", payload, headers)

    def list_residual_batches(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/residual-batches", headers=headers, params=params)

    def get_residual_batch(self, batch_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/residual-batches/{batch_id}", headers=headers)

    def create_residual_line(self, batch_id: str, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"/residual-batches/{batch_id}/lines", payload, headers)

    def list_residual_lines(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/residual-lines", headers=headers, params=params)

    def get_residual_line(self, line_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/residual-lines/{line_id}", headers=headers)

    def normalize_residual_batch(self, batch_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/residual-batches/{batch_id}/normalize", {}, headers)

    def recall_residual_batch(self, batch_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/residual-batches/{batch_id}/recall", {}, headers)

    def post_residual_batch(self, batch_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/residual-batches/{batch_id}/post", {}, headers)

    def reverse_residual_batch(self, batch_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/residual-batches/{batch_id}/reverse", {}, headers)

    # --------------------------------------------------- derived ledger reads
    def list_merchant_profitability(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/merchant-profitability", headers=headers, params=params)

    def get_merchant_profitability(self, profitability_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/merchant-profitability/{profitability_id}", headers=headers
        )

    def list_residual_allocations(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/residual-allocations", headers=headers, params=params)

    def get_residual_allocation(self, allocation_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/residual-allocations/{allocation_id}", headers=headers
        )

    # -------------------------------------------------------- agent statements
    def list_agent_statements(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/agent-statements", headers=headers, params=params)

    def get_agent_statement(self, statement_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/agent-statements/{statement_id}", headers=headers)

    def issue_agent_statement(self, statement_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/agent-statements/{statement_id}/issue", {}, headers)

    def recall_agent_statement(self, statement_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/agent-statements/{statement_id}/recall", {}, headers)

    def finalize_agent_statement(self, statement_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/agent-statements/{statement_id}/finalize", {}, headers
        )

    def hold_agent_statement(self, statement_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/agent-statements/{statement_id}/hold", payload, headers
        )

    def release_agent_statement_hold(self, statement_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/agent-statements/{statement_id}/release-hold", {}, headers
        )

    def settle_agent_statement(self, statement_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/agent-statements/{statement_id}/settle", payload, headers
        )

    # --------------------------------------------------- statement adjustments
    def create_statement_adjustment(
        self, statement_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/agent-statements/{statement_id}/adjustments", payload, headers
        )

    def list_statement_adjustments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/statement-adjustments", headers=headers, params=params)

    def get_statement_adjustment(self, adjustment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/statement-adjustments/{adjustment_id}", headers=headers
        )

    def review_statement_adjustment(self, adjustment_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/statement-adjustments/{adjustment_id}/review", {}, headers
        )

    def request_info_statement_adjustment(
        self, adjustment_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/statement-adjustments/{adjustment_id}/request-info", payload, headers
        )

    def resubmit_statement_adjustment(
        self, adjustment_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/statement-adjustments/{adjustment_id}/resubmit", payload, headers
        )

    def approve_statement_adjustment(self, adjustment_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/statement-adjustments/{adjustment_id}/approve", {}, headers
        )

    def reject_statement_adjustment(
        self, adjustment_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/statement-adjustments/{adjustment_id}/reject", payload, headers
        )


api_client = ApiClient()
