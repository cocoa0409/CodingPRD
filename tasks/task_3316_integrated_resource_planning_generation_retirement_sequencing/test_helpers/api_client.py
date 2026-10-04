"""API client: one method per endpoint defined in the PRD (§4 routing summary)."""
from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload: dict, headers: dict):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- ResourcePlan ---
    def create_plan(self, payload: dict, headers: dict):
        return self._request("POST", "/plans", payload, headers)

    def list_plans(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/plans", headers=headers, params=params)

    def get_plan(self, plan_id: str, headers: dict):
        return self._request("GET", f"/plans/{plan_id}", headers=headers)

    def open_comment(self, plan_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/plans/{plan_id}/open-comment", payload or {}, headers)

    def submit_for_review(self, plan_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/plans/{plan_id}/submit-for-review", payload or {}, headers)

    def commission_review(self, plan_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/plans/{plan_id}/commission-review", payload, headers)

    def reopen_plan(self, plan_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/plans/{plan_id}/reopen", payload or {}, headers)

    # --- LoadForecast ---
    def create_forecast(self, plan_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/plans/{plan_id}/forecasts", payload, headers)

    def list_forecasts(self, plan_id: str, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"/plans/{plan_id}/forecasts", headers=headers, params=params)

    def get_forecast(self, plan_id: str, forecast_id: str, headers: dict):
        return self._request("GET", f"/plans/{plan_id}/forecasts/{forecast_id}", headers=headers)

    def update_forecast(self, plan_id: str, forecast_id: str, payload: dict, headers: dict):
        return self._request("PUT", f"/plans/{plan_id}/forecasts/{forecast_id}", payload, headers)

    def list_forecasts_flat(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/forecasts", headers=headers, params=params)

    def get_forecast_flat(self, forecast_id: str, headers: dict):
        return self._request("GET", f"/forecasts/{forecast_id}", headers=headers)

    # --- Resource (fleet) ---
    def create_resource(self, payload: dict, headers: dict):
        return self._request("POST", "/resources", payload, headers)

    def list_resources(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/resources", headers=headers, params=params)

    def get_resource(self, resource_id: str, headers: dict):
        return self._request("GET", f"/resources/{resource_id}", headers=headers)

    def retire_resource(self, resource_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/resources/{resource_id}/retire", payload, headers)

    def cancel_retirement(self, resource_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/resources/{resource_id}/cancel-retirement", payload or {}, headers)

    def mothball_resource(self, resource_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/resources/{resource_id}/mothball", payload or {}, headers)

    def list_resource_analyses(self, resource_id: str, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"/resources/{resource_id}/retirement-analyses", headers=headers, params=params)

    # --- ResourcePortfolio / Position ---
    def create_portfolio(self, plan_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/plans/{plan_id}/portfolios", payload, headers)

    def list_portfolios(self, plan_id: str, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"/plans/{plan_id}/portfolios", headers=headers, params=params)

    def get_portfolio_under_plan(self, plan_id: str, portfolio_id: str, headers: dict):
        return self._request("GET", f"/plans/{plan_id}/portfolios/{portfolio_id}", headers=headers)

    def get_portfolio(self, portfolio_id: str, headers: dict):
        return self._request("GET", f"/portfolios/{portfolio_id}", headers=headers)

    def list_portfolios_flat(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/portfolios", headers=headers, params=params)

    def add_position(self, portfolio_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/portfolios/{portfolio_id}/positions", payload, headers)

    def list_positions(self, portfolio_id: str, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"/portfolios/{portfolio_id}/positions", headers=headers, params=params)

    def remove_position(self, portfolio_id: str, position_id: str, headers: dict):
        return self._request("DELETE", f"/portfolios/{portfolio_id}/positions/{position_id}", headers=headers)

    def get_position(self, position_id: str, headers: dict):
        return self._request("GET", f"/positions/{position_id}", headers=headers)

    def list_positions_flat(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/positions", headers=headers, params=params)

    # --- ReliabilitySnapshot ---
    def create_snapshot(self, portfolio_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/portfolios/{portfolio_id}/snapshots", payload, headers)

    def list_snapshots(self, portfolio_id: str, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"/portfolios/{portfolio_id}/snapshots", headers=headers, params=params)

    def get_snapshot(self, portfolio_id: str, snapshot_id: str, headers: dict):
        return self._request("GET", f"/portfolios/{portfolio_id}/snapshots/{snapshot_id}", headers=headers)

    def list_snapshots_flat(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/snapshots", headers=headers, params=params)

    def get_snapshot_flat(self, snapshot_id: str, headers: dict):
        return self._request("GET", f"/snapshots/{snapshot_id}", headers=headers)

    # --- ResourceCandidate ---
    def create_candidate(self, payload: dict, headers: dict):
        return self._request("POST", "/candidates", payload, headers)

    def list_candidates(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/candidates", headers=headers, params=params)

    def get_candidate(self, candidate_id: str, headers: dict):
        return self._request("GET", f"/candidates/{candidate_id}", headers=headers)

    def list_candidate_positions(self, candidate_id: str, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"/candidates/{candidate_id}/positions", headers=headers, params=params)

    def list_candidate_commitments(self, candidate_id: str, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"/candidates/{candidate_id}/procurement-commitments", headers=headers, params=params)

    # --- RetirementAnalysis ---
    def create_retirement_analysis(self, resource_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/resources/{resource_id}/retirement-analyses", payload, headers)

    def get_analysis(self, analysis_id: str, headers: dict):
        return self._request("GET", f"/retirement-analyses/{analysis_id}", headers=headers)

    def list_plan_analyses(self, plan_id: str, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"/plans/{plan_id}/retirement-analyses", headers=headers, params=params)

    def list_analyses_flat(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/retirement-analyses", headers=headers, params=params)

    def finalize_analysis(self, analysis_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/retirement-analyses/{analysis_id}/finalize", payload or {}, headers)

    def reopen_analysis(self, analysis_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/retirement-analyses/{analysis_id}/reopen", payload or {}, headers)

    # --- PublicComment ---
    def create_comment(self, plan_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/plans/{plan_id}/comments", payload, headers)

    def list_comments(self, plan_id: str, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"/plans/{plan_id}/comments", headers=headers, params=params)

    def list_comments_flat(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/comments", headers=headers, params=params)

    def get_comment_flat(self, comment_id: str, headers: dict):
        return self._request("GET", f"/comments/{comment_id}", headers=headers)

    def acknowledge_comment(self, plan_id: str, comment_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/plans/{plan_id}/comments/{comment_id}/acknowledge", payload or {}, headers)

    # --- Intervenor / Testimony ---
    def create_intervenor(self, payload: dict, headers: dict):
        return self._request("POST", "/intervenors", payload, headers)

    def list_intervenors(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/intervenors", headers=headers, params=params)

    def get_intervenor(self, intervenor_id: str, headers: dict):
        return self._request("GET", f"/intervenors/{intervenor_id}", headers=headers)

    def create_testimony(self, plan_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/plans/{plan_id}/testimonies", payload, headers)

    def list_testimonies(self, plan_id: str, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"/plans/{plan_id}/testimonies", headers=headers, params=params)

    def list_testimonies_flat(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/testimonies", headers=headers, params=params)

    def get_testimony(self, testimony_id: str, headers: dict):
        return self._request("GET", f"/testimonies/{testimony_id}", headers=headers)

    def withdraw_testimony(self, testimony_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/testimonies/{testimony_id}/withdraw", payload or {}, headers)

    def refile_testimony(self, testimony_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/testimonies/{testimony_id}/refile", payload or {}, headers)

    # --- SensitivityAnalysis ---
    def create_sensitivity(self, plan_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/plans/{plan_id}/sensitivities", payload, headers)

    def list_sensitivities(self, plan_id: str, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"/plans/{plan_id}/sensitivities", headers=headers, params=params)

    def list_sensitivities_flat(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/sensitivities", headers=headers, params=params)

    def get_sensitivity_flat(self, sensitivity_id: str, headers: dict):
        return self._request("GET", f"/sensitivities/{sensitivity_id}", headers=headers)

    # --- ProcurementCommitment / PlanCondition / DeviationReport ---
    def create_commitment(self, plan_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/plans/{plan_id}/procurement-commitments", payload, headers)

    def list_commitments(self, plan_id: str, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"/plans/{plan_id}/procurement-commitments", headers=headers, params=params)

    def list_commitments_flat(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/procurement-commitments", headers=headers, params=params)

    def get_commitment(self, commitment_id: str, headers: dict):
        return self._request("GET", f"/procurement-commitments/{commitment_id}", headers=headers)

    def award_commitment(self, commitment_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/procurement-commitments/{commitment_id}/award", payload or {}, headers)

    def cancel_commitment(self, commitment_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/procurement-commitments/{commitment_id}/cancel", payload or {}, headers)

    def list_conditions(self, plan_id: str, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"/plans/{plan_id}/conditions", headers=headers, params=params)

    def list_conditions_flat(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/conditions", headers=headers, params=params)

    def get_condition_flat(self, condition_id: str, headers: dict):
        return self._request("GET", f"/conditions/{condition_id}", headers=headers)

    def create_deviation_report(self, plan_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/plans/{plan_id}/deviation-reports", payload, headers)

    def list_deviation_reports(self, plan_id: str, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"/plans/{plan_id}/deviation-reports", headers=headers, params=params)

    def list_deviation_reports_flat(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/deviation-reports", headers=headers, params=params)

    def get_deviation_report_flat(self, report_id: str, headers: dict):
        return self._request("GET", f"/deviation-reports/{report_id}", headers=headers)


api_client = ApiClient()
