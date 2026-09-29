"""Endpoint client for the Consulting Bench Management API (PRD §4).

One method per declared endpoint row. Query parameters are passed as the
payload of GET calls, which GenericApiClient forwards as query params.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------------------------------------------------------- clock --
    def set_clock(self, current_utc: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_clock_raw(
        self, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_bench_run(self, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/bench-runs", {}, headers)

    # ------------------------------------------------------- practice groups --
    def create_practice_group(
        self, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/practice-groups", payload, headers)

    def list_practice_groups(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/practice-groups", params or {}, headers)

    def get_practice_group(
        self, group_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/practice-groups/{group_id}", None, headers)

    def patch_practice_group(
        self, group_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", f"/practice-groups/{group_id}", payload, headers)

    def list_child_groups(
        self, group_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/practice-groups/{group_id}/child-groups", params or {}, headers
        )

    # ---------------------------------------------------------------- skills --
    def create_skill(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/skills", payload, headers)

    def list_skills(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/skills", params or {}, headers)

    def get_skill(self, skill_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/skills/{skill_id}", None, headers)

    def patch_skill(
        self, skill_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", f"/skills/{skill_id}", payload, headers)

    # ----------------------------------------------------------- consultants --
    def create_consultant(
        self, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/consultants", payload, headers)

    def list_consultants(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/consultants", params or {}, headers)

    def get_consultant(
        self, consultant_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/consultants/{consultant_id}", None, headers)

    def patch_consultant(
        self, consultant_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "PATCH", f"/consultants/{consultant_id}", payload, headers
        )

    # ------------------------------------------------------ skill assertions --
    def create_skill_assertion(
        self, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/skill-assertions", payload, headers)

    def list_skill_assertions(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/skill-assertions", params or {}, headers)

    def get_skill_assertion(
        self, assertion_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/skill-assertions/{assertion_id}", None, headers)

    def patch_skill_assertion(
        self, assertion_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "PATCH", f"/skill-assertions/{assertion_id}", payload, headers
        )

    # ------------------------------------------------ demand opportunities --
    def create_demand(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/demand-opportunities", payload, headers)

    def list_demands(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/demand-opportunities", params or {}, headers)

    def get_demand(self, demand_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/demand-opportunities/{demand_id}", None, headers)

    def qualify_demand(
        self, demand_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/demand-opportunities/{demand_id}/qualify", {}, headers
        )

    def set_staffing_mode(
        self, demand_id: str, staffing_mode: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/demand-opportunities/{demand_id}/staffing-mode",
            {"staffing_mode": staffing_mode},
            headers,
        )

    def close_demand(
        self,
        demand_id: str,
        outcome: str,
        headers: Dict[str, str],
        note: Optional[str] = None,
    ) -> requests.Response:
        payload: Dict[str, Any] = {"outcome": outcome}
        if note is not None:
            payload["note"] = note
        return self._request(
            "POST", f"/demand-opportunities/{demand_id}/close", payload, headers
        )

    def auto_staff_demand(
        self, demand_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/demand-opportunities/{demand_id}/auto-staff", {}, headers
        )

    # ------------------------------------------------------------ assignments --
    def create_assignment(
        self, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/assignments", payload, headers)

    def list_assignments(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/assignments", params or {}, headers)

    def get_assignment(
        self, assignment_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/assignments/{assignment_id}", None, headers)

    def confirm_assignment(
        self, assignment_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/assignments/{assignment_id}/confirm", {}, headers
        )

    def release_assignment(
        self,
        assignment_id: str,
        headers: Dict[str, str],
        reason: Optional[str] = None,
    ) -> requests.Response:
        payload: Dict[str, Any] = {}
        if reason is not None:
            payload["reason"] = reason
        return self._request(
            "POST", f"/assignments/{assignment_id}/release", payload, headers
        )

    def cancel_assignment(
        self,
        assignment_id: str,
        headers: Dict[str, str],
        reason: Optional[str] = None,
    ) -> requests.Response:
        payload: Dict[str, Any] = {}
        if reason is not None:
            payload["reason"] = reason
        return self._request(
            "POST", f"/assignments/{assignment_id}/cancel", payload, headers
        )

    # ----------------------------------------------------------- bench spells --
    def list_bench_spells(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/bench-spells", params or {}, headers)

    def get_bench_spell(
        self, spell_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/bench-spells/{spell_id}", None, headers)

    def start_internal_project(
        self, spell_id: str, internal_project_code: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/bench-spells/{spell_id}/internal-project",
            {"internal_project_code": internal_project_code},
            headers,
        )

    def propose_separation(
        self,
        spell_id: str,
        headers: Dict[str, str],
        rationale: Optional[str] = None,
    ) -> requests.Response:
        payload: Dict[str, Any] = {}
        if rationale is not None:
            payload["rationale"] = rationale
        return self._request(
            "POST", f"/bench-spells/{spell_id}/separation-proposal", payload, headers
        )

    def decide_separation(
        self,
        spell_id: str,
        decision: str,
        headers: Dict[str, str],
        note: Optional[str] = None,
    ) -> requests.Response:
        payload: Dict[str, Any] = {"decision": decision}
        if note is not None:
            payload["note"] = note
        return self._request(
            "POST", f"/bench-spells/{spell_id}/separation-decision", payload, headers
        )

    # ----------------------------------------------------- reskilling programs --
    def create_reskilling_program(
        self, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/reskilling-programs", payload, headers)

    def list_reskilling_programs(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/reskilling-programs", params or {}, headers)

    def get_reskilling_program(
        self, program_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/reskilling-programs/{program_id}", None, headers)

    def enrol_in_program(
        self, program_id: str, consultant_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/reskilling-programs/{program_id}/enrollments",
            {"consultant_id": consultant_id},
            headers,
        )

    def complete_program(
        self, program_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/reskilling-programs/{program_id}/complete", {}, headers
        )

    # --------------------------------------------------- subcontractor firms --
    def create_firm(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/subcontractor-firms", payload, headers)

    def list_firms(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/subcontractor-firms", params or {}, headers)

    def get_firm(self, firm_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/subcontractor-firms/{firm_id}", None, headers)

    def patch_firm(
        self, firm_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "PATCH", f"/subcontractor-firms/{firm_id}", payload, headers
        )

    # ------------------------------------------------------ external placements --
    def create_placement(
        self, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/external-placements", payload, headers)

    def list_placements(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/external-placements", params or {}, headers)

    def get_placement(
        self, placement_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/external-placements/{placement_id}", None, headers)

    def approve_placement(
        self, placement_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/external-placements/{placement_id}/approve", {}, headers
        )

    def terminate_placement(
        self,
        placement_id: str,
        headers: Dict[str, str],
        reason: Optional[str] = None,
    ) -> requests.Response:
        payload: Dict[str, Any] = {}
        if reason is not None:
            payload["reason"] = reason
        return self._request(
            "POST", f"/external-placements/{placement_id}/terminate", payload, headers
        )

    # ------------------------------------------------------ discount approvals --
    def create_discount_approval(
        self, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/discount-approvals", payload, headers)

    def list_discount_approvals(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/discount-approvals", params or {}, headers)

    def get_discount_approval(
        self, approval_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/discount-approvals/{approval_id}", None, headers)

    def decide_discount_approval(
        self,
        approval_id: str,
        decision: str,
        headers: Dict[str, str],
        decision_note: Optional[str] = None,
    ) -> requests.Response:
        payload: Dict[str, Any] = {"decision": decision}
        if decision_note is not None:
            payload["decision_note"] = decision_note
        return self._request(
            "POST", f"/discount-approvals/{approval_id}/decide", payload, headers
        )

    def revise_discount_approval(
        self,
        approval_id: str,
        requested_rate_usd_per_hour: float,
        headers: Dict[str, str],
        decision_note: Optional[str] = None,
    ) -> requests.Response:
        payload: Dict[str, Any] = {
            "requested_rate_usd_per_hour": requested_rate_usd_per_hour
        }
        if decision_note is not None:
            payload["decision_note"] = decision_note
        return self._request(
            "POST", f"/discount-approvals/{approval_id}/revise", payload, headers
        )

    # ----------------------------------------------------- utilization periods --
    def create_utilization_period(
        self, consultant_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/consultants/{consultant_id}/utilization-periods", payload, headers
        )

    def list_utilization_periods(
        self,
        consultant_id: str,
        headers: Dict[str, str],
        params: Optional[Dict] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/consultants/{consultant_id}/utilization-periods",
            params or {},
            headers,
        )

    def get_utilization_period(
        self, consultant_id: str, period_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/consultants/{consultant_id}/utilization-periods/{period_id}",
            None,
            headers,
        )

    def close_utilization_period(
        self, consultant_id: str, period_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/consultants/{consultant_id}/utilization-periods/{period_id}/close",
            {},
            headers,
        )

    # ------------------------------------------------------- hiring forecasts --
    def create_hiring_forecast(
        self, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/hiring-forecasts", payload, headers)

    def list_hiring_forecasts(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/hiring-forecasts", params or {}, headers)

    def get_hiring_forecast(
        self, forecast_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/hiring-forecasts/{forecast_id}", None, headers)
