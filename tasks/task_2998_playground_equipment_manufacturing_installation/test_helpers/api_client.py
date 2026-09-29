"""API client: one method per endpoint defined in the PRD.

Every path is mounted under the /playground prefix exactly as the PRD writes it.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/playground"


class ApiClient(GenericApiClient):
    # ---------------------------------------------------------------- clock
    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{PREFIX}/_clock/set_current_utc",
            {"current_utc": current_utc},
            headers,
        )

    def set_clock_raw(self, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", payload, headers
        )

    # ------------------------------------------------------------ standards
    def create_standard(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/standards", payload, headers)

    def list_standards(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/standards", headers=headers, params=params
        )

    def get_standard(self, standard_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/standards/{standard_id}", headers=headers
        )

    def activate_standard(self, standard_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/standards/{standard_id}/activate", {}, headers
        )

    def supersede_standard(
        self, standard_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/standards/{standard_id}/supersede", payload, headers
        )

    # ------------------------------------------------------ component models
    def create_component_model(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/component-models", payload, headers)

    def list_component_models(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/component-models", headers=headers, params=params
        )

    def get_component_model(self, model_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/component-models/{model_id}", headers=headers
        )

    def certify_component_model(self, model_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/component-models/{model_id}/certify", {}, headers
        )

    def set_component_model_lifecycle(
        self, model_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/component-models/{model_id}/lifecycle",
            payload,
            headers,
        )

    # ------------------------------------------------------------- projects
    def create_project(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/projects", payload, headers)

    def list_projects(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/projects", headers=headers, params=params
        )

    def get_project(self, project_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/projects/{project_id}", headers=headers)

    def start_consultation(self, project_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/projects/{project_id}/start-consultation", {}, headers
        )

    def create_play_area(
        self, project_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/projects/{project_id}/play-areas", payload, headers
        )

    def list_play_areas(
        self, project_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/projects/{project_id}/play-areas",
            headers=headers,
            params=params,
        )

    def issue_rendering(self, project_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/projects/{project_id}/renderings", payload, headers
        )

    def list_project_renderings(
        self, project_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/projects/{project_id}/renderings",
            headers=headers,
            params=params,
        )

    def certify_compliance(self, project_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/projects/{project_id}/certify-compliance", {}, headers
        )

    def cancel_project(self, project_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/projects/{project_id}/cancel", {}, headers
        )

    def create_pledge(self, project_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/projects/{project_id}/pledges", payload, headers
        )

    def list_project_pledges(
        self, project_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/projects/{project_id}/pledges",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------ play areas
    def get_play_area(self, area_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/play-areas/{area_id}", headers=headers)

    def create_placement(self, area_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/play-areas/{area_id}/placements", payload, headers
        )

    def list_area_placements(
        self, area_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/play-areas/{area_id}/placements",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------ placements
    def list_placements(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/placements", headers=headers, params=params
        )

    def get_placement(self, placement_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/placements/{placement_id}", headers=headers
        )

    def validate_placement(self, placement_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/placements/{placement_id}/validate", {}, headers
        )

    def retrofit_placement(
        self, placement_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/placements/{placement_id}/retrofit", payload, headers
        )

    def delete_placement(self, placement_id: str, headers: Dict[str, str]):
        return self._request(
            "DELETE", f"{PREFIX}/placements/{placement_id}", headers=headers
        )

    # ------------------------------------------------------------ renderings
    def list_renderings(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/renderings", headers=headers, params=params
        )

    def get_rendering(self, rendering_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/renderings/{rendering_id}", headers=headers
        )

    def record_community_votes(
        self, rendering_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/renderings/{rendering_id}/community-votes",
            payload,
            headers,
        )

    def close_review(self, rendering_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/renderings/{rendering_id}/close-review", {}, headers
        )

    # ---------------------------------------------------------------- quotes
    def create_quote(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/quotes", payload, headers)

    def list_quotes(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/quotes", headers=headers, params=params)

    def get_quote(self, quote_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/quotes/{quote_id}", headers=headers)

    def accept_quote(self, quote_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/quotes/{quote_id}/accept", {}, headers
        )

    # --------------------------------------------------------------- pledges
    def get_pledge(self, pledge_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/pledges/{pledge_id}", headers=headers)

    def collect_pledge(self, pledge_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/pledges/{pledge_id}/collect", {}, headers
        )

    def refund_pledge(self, pledge_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/pledges/{pledge_id}/refund", {}, headers
        )

    # ---------------------------------------------------------------- orders
    def create_order(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/orders", payload, headers)

    def list_orders(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/orders", headers=headers, params=params)

    def get_order(self, order_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/orders/{order_id}", headers=headers)

    def start_production(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/orders/{order_id}/start-production", {}, headers
        )

    def advance_kitting(self, order_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/orders/{order_id}/kitting", payload, headers
        )

    def advance_bagging(self, order_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/orders/{order_id}/hardware-bagging", payload, headers
        )

    def ship_order(self, order_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/orders/{order_id}/ship", {}, headers)

    # ------------------------------------------------------------ installers
    def create_installer(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/installers", payload, headers)

    def list_installers(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/installers", headers=headers, params=params
        )

    def get_installer(self, installer_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/installers/{installer_id}", headers=headers
        )

    def set_installer_status(
        self, installer_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/installers/{installer_id}/status", payload, headers
        )

    # ------------------------------------------------------ installation jobs
    def create_installation_job(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/installation-jobs", payload, headers)

    def list_installation_jobs(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/installation-jobs", headers=headers, params=params
        )

    def get_installation_job(self, job_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/installation-jobs/{job_id}", headers=headers
        )

    def reschedule_job(self, job_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/installation-jobs/{job_id}/reschedule", payload, headers
        )

    def start_job(self, job_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/installation-jobs/{job_id}/start", {}, headers
        )

    def complete_job(self, job_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/installation-jobs/{job_id}/complete", {}, headers
        )

    def rework_job(self, job_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/installation-jobs/{job_id}/rework", payload, headers
        )

    def cancel_job(self, job_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/installation-jobs/{job_id}/cancel", {}, headers
        )

    def file_inspection(self, job_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/installation-jobs/{job_id}/inspections", payload, headers
        )

    def list_job_inspections(
        self, job_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/installation-jobs/{job_id}/inspections",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------- warranty claims
    def create_warranty_claim(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/warranty-claims", payload, headers)

    def list_warranty_claims(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/warranty-claims", headers=headers, params=params
        )

    def get_warranty_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/warranty-claims/{claim_id}", headers=headers
        )

    def decide_warranty_claim(
        self, claim_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/warranty-claims/{claim_id}/decide", payload, headers
        )

    # -------------------------------------------------------------- raw hook
    def raw_get(self, path: str, headers: Dict[str, str], params: Optional[Dict] = None):
        """Escape hatch for path-shape tests (unknown ids, nested resolution)."""
        return self._request("GET", f"{PREFIX}{path}", headers=headers, params=params)

    def raw_post(self, path: str, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}{path}", payload, headers)


api_client = ApiClient()
