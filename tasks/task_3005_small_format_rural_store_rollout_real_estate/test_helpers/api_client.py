"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- rollout programs -----------------------------------------------
    def create_rollout(self, payload, headers):
        return self._request("POST", "/rollouts", payload, headers)

    def list_rollouts(self, headers, params=None):
        return self._request("GET", "/rollouts", headers=headers, params=params)

    def get_rollout(self, rollout_id, headers):
        return self._request("GET", f"/rollouts/{rollout_id}", headers=headers)

    def activate_rollout(self, rollout_id, headers):
        return self._request("POST", f"/rollouts/{rollout_id}/activate", {}, headers)

    def deactivate_rollout(self, rollout_id, headers):
        return self._request("POST", f"/rollouts/{rollout_id}/deactivate", {}, headers)

    def close_rollout(self, rollout_id, headers):
        return self._request("POST", f"/rollouts/{rollout_id}/close", {}, headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/rollouts/_clock-set", payload, headers)

    def update_rollout_settings(self, rollout_id, payload, headers):
        return self._request("PATCH", f"/rollouts/{rollout_id}/settings", payload, headers)

    def list_program_events(self, headers, params=None):
        return self._request("GET", "/rollouts/program-events", headers=headers, params=params)

    def get_program_event(self, event_id, headers):
        return self._request("GET", f"/rollouts/program-events/{event_id}", headers=headers)

    # ---- trade areas ------------------------------------------------------
    def create_trade_area(self, payload, headers):
        return self._request("POST", "/rollouts/trade-areas", payload, headers)

    def list_trade_areas(self, headers, params=None):
        return self._request("GET", "/rollouts/trade-areas", headers=headers, params=params)

    def get_trade_area(self, trade_area_id, headers):
        return self._request("GET", f"/rollouts/trade-areas/{trade_area_id}", headers=headers)

    def update_trade_area(self, payload, headers):
        return self._request("PATCH", "/rollouts/trade-area-updates", payload, headers)

    def screen_trade_area(self, trade_area_id, payload, headers):
        return self._request(
            "POST", f"/rollouts/trade-areas/{trade_area_id}/screen", payload, headers
        )

    # ---- stores ------------------------------------------------------------
    def create_store(self, payload, headers):
        return self._request("POST", "/rollouts/stores", payload, headers)

    def list_stores(self, headers, params=None):
        return self._request("GET", "/rollouts/stores", headers=headers, params=params)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/rollouts/stores/{store_id}", headers=headers)

    def update_store(self, store_id, payload, headers):
        return self._request("PATCH", f"/rollouts/stores/{store_id}", payload, headers)

    def select_format(self, store_id, payload, headers):
        return self._request(
            "POST", f"/rollouts/stores/{store_id}/select-format", payload, headers
        )

    def kill_store(self, store_id, payload, headers):
        return self._request("POST", f"/rollouts/stores/{store_id}/kill", payload, headers)

    def record_sales(self, store_id, payload, headers):
        return self._request(
            "POST", f"/rollouts/stores/{store_id}/record-sales", payload, headers
        )

    # ---- developers ---------------------------------------------------------
    def create_developer(self, payload, headers):
        return self._request("POST", "/rollouts/developers", payload, headers)

    def list_developers(self, headers, params=None):
        return self._request("GET", "/rollouts/developers", headers=headers, params=params)

    def get_developer(self, developer_id, headers):
        return self._request("GET", f"/rollouts/developers/{developer_id}", headers=headers)

    # ---- site control agreements ---------------------------------------------
    def create_site_agreement(self, payload, headers):
        return self._request("POST", "/rollouts/site-agreements", payload, headers)

    def list_site_agreements(self, headers, params=None):
        return self._request("GET", "/rollouts/site-agreements", headers=headers, params=params)

    def get_site_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/rollouts/site-agreements/{agreement_id}", headers=headers
        )

    def execute_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/rollouts/site-agreements/{agreement_id}/execute", payload, headers
        )

    def activate_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/rollouts/site-agreements/{agreement_id}/activate", payload, headers
        )

    def record_delivery(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/rollouts/site-agreements/{agreement_id}/deliveries", payload, headers
        )

    def terminate_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/rollouts/site-agreements/{agreement_id}/terminate", payload, headers
        )

    # ---- distribution centers -------------------------------------------------
    def create_distribution_center(self, payload, headers):
        return self._request("POST", "/rollouts/distribution-centers", payload, headers)

    def list_distribution_centers(self, headers, params=None):
        return self._request(
            "GET", "/rollouts/distribution-centers", headers=headers, params=params
        )

    def get_distribution_center(self, dc_id, headers):
        return self._request(
            "GET", f"/rollouts/distribution-centers/{dc_id}", headers=headers
        )

    # ---- DC assignments ----------------------------------------------------------
    def create_dc_assignment(self, payload, headers):
        return self._request("POST", "/rollouts/dc-assignments", payload, headers)

    def list_dc_assignments(self, headers, params=None):
        return self._request("GET", "/rollouts/dc-assignments", headers=headers, params=params)

    def get_dc_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/rollouts/dc-assignments/{assignment_id}", headers=headers
        )

    # ---- route plans -----------------------------------------------------------------
    def create_route_plan(self, payload, headers):
        return self._request("POST", "/rollouts/route-plans", payload, headers)

    def list_route_plans(self, headers, params=None):
        return self._request("GET", "/rollouts/route-plans", headers=headers, params=params)

    def get_route_plan(self, route_plan_id, headers):
        return self._request("GET", f"/rollouts/route-plans/{route_plan_id}", headers=headers)

    # ---- opening plans -----------------------------------------------------------------
    def create_opening_plan(self, payload, headers):
        return self._request("POST", "/rollouts/opening-plans", payload, headers)

    def list_opening_plans(self, headers, params=None):
        return self._request("GET", "/rollouts/opening-plans", headers=headers, params=params)

    def get_opening_plan(self, opening_plan_id, headers):
        return self._request(
            "GET", f"/rollouts/opening-plans/{opening_plan_id}", headers=headers
        )

    def lock_opening_plan(self, opening_plan_id, payload, headers):
        return self._request(
            "POST", f"/rollouts/opening-plans/{opening_plan_id}/lock", payload, headers
        )

    def unlock_opening_plan(self, opening_plan_id, payload, headers):
        return self._request(
            "POST", f"/rollouts/opening-plans/{opening_plan_id}/unlock", payload, headers
        )

    def execute_opening_plan(self, opening_plan_id, payload, headers):
        return self._request(
            "POST", f"/rollouts/opening-plans/{opening_plan_id}/execute", payload, headers
        )

    # ---- cannibalization studies ------------------------------------------------------
    def create_cannibalization_study(self, payload, headers):
        return self._request("POST", "/rollouts/cannibalization-studies", payload, headers)

    def list_cannibalization_studies(self, headers, params=None):
        return self._request(
            "GET", "/rollouts/cannibalization-studies", headers=headers, params=params
        )

    def get_cannibalization_study(self, study_id, headers, params=None):
        return self._request(
            "GET", f"/rollouts/cannibalization-studies/{study_id}", headers=headers, params=params
        )

    def finalize_cannibalization_study(self, study_id, payload, headers):
        return self._request(
            "POST",
            f"/rollouts/cannibalization-studies/{study_id}/finalize",
            payload,
            headers,
        )

    # ---- capital projects --------------------------------------------------------------
    def create_capital_project(self, payload, headers):
        return self._request("POST", "/rollouts/capital-projects", payload, headers)

    def list_capital_projects(self, headers, params=None):
        return self._request(
            "GET", "/rollouts/capital-projects", headers=headers, params=params
        )

    def get_capital_project(self, project_id, headers):
        return self._request(
            "GET", f"/rollouts/capital-projects/{project_id}", headers=headers
        )

    def submit_capital_project(self, project_id, payload, headers):
        return self._request(
            "POST", f"/rollouts/capital-projects/{project_id}/submit", payload, headers
        )

    def decide_capital_project(self, project_id, payload, headers):
        return self._request(
            "POST", f"/rollouts/capital-projects/{project_id}/decide", payload, headers
        )

    def cancel_capital_project(self, project_id, payload, headers):
        return self._request(
            "POST", f"/rollouts/capital-projects/{project_id}/cancel", payload, headers
        )


api_client = ApiClient()
