"""API client: one method per endpoint of the prefabrication service (PRD §4)."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/prefab"


class ApiClient(GenericApiClient):
    # -- projects -----------------------------------------------------------
    def create_project(self, payload, headers):
        return self._request("POST", f"{PREFIX}/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"{PREFIX}/projects/{project_id}", headers=headers)

    def recompute_posture(self, project_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/projects/{project_id}/posture/recompute",
            payload or {}, headers=headers,
        )

    # -- model versions / takeoff ------------------------------------------
    def create_model_version(self, payload, headers):
        return self._request("POST", f"{PREFIX}/model-versions", payload, headers)

    def list_model_versions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/model-versions", headers=headers, params=params)

    def get_model_version(self, version_id, headers):
        return self._request("GET", f"{PREFIX}/model-versions/{version_id}", headers=headers)

    def coordinate_model_version(self, version_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/model-versions/{version_id}/coordinate",
            payload or {}, headers=headers,
        )

    def create_takeoff_line(self, payload, headers):
        return self._request("POST", f"{PREFIX}/takeoff-lines", payload, headers)

    def list_takeoff_lines(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/takeoff-lines", headers=headers, params=params)

    # -- racks / assemblies -------------------------------------------------
    def create_rack(self, payload, headers):
        return self._request("POST", f"{PREFIX}/racks", payload, headers)

    def list_racks(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/racks", headers=headers, params=params)

    # -- workers / rates ----------------------------------------------------
    def create_worker(self, payload, headers):
        return self._request("POST", f"{PREFIX}/workers", payload, headers)

    def create_trade_contract_rate(self, payload, headers):
        return self._request("POST", f"{PREFIX}/trade-contract-rates", payload, headers)

    # -- trade activities / crew days ---------------------------------------
    def create_trade_activity(self, payload, headers):
        return self._request("POST", f"{PREFIX}/trade-activities", payload, headers)

    def list_trade_activities(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/trade-activities", headers=headers, params=params)

    def set_trade_activity_status(self, activity_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/trade-activities/{activity_id}/status", payload, headers,
        )

    def create_crew_day(self, payload, headers):
        return self._request("POST", f"{PREFIX}/crew-days", payload, headers)

    def list_crew_days(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/crew-days", headers=headers, params=params)

    def acknowledge_crew_day(self, crew_day_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/crew-days/{crew_day_id}/acknowledge", payload, headers,
        )

    def list_compliance_ledger(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/compliance-ledger", headers=headers, params=params,
        )

    # -- work packages ------------------------------------------------------
    def create_prefab_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/prefab-orders", payload, headers)

    def list_prefab_orders(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/prefab-orders", headers=headers, params=params)

    def get_prefab_order(self, order_id, headers):
        return self._request("GET", f"{PREFIX}/prefab-orders/{order_id}", headers=headers)

    def release_prefab_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/prefab-orders/{order_id}/release", payload, headers,
        )

    def set_fabrication_status(self, order_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/prefab-orders/{order_id}/fabrication-status", payload, headers,
        )

    def ressue_prefab_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/prefab-orders/{order_id}/ressue", payload or {}, headers,
        )

    def cancel_prefab_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/prefab-orders/{order_id}/cancel", payload or {}, headers,
        )

    def set_delivery_status(self, order_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/prefab-orders/{order_id}/delivery-status", payload, headers,
        )

    # -- components ---------------------------------------------------------
    def create_prefab_component(self, payload, headers):
        return self._request("POST", f"{PREFIX}/prefab-components", payload, headers)

    def list_prefab_components(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/prefab-components", headers=headers, params=params)

    def get_prefab_component(self, component_id, headers):
        return self._request(
            "GET", f"{PREFIX}/prefab-components/{component_id}", headers=headers,
        )

    def fabricate_prefab_component(self, component_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/prefab-components/{component_id}/fabricate",
            payload or {}, headers,
        )

    def set_component_install_status(self, component_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/prefab-components/{component_id}/install-status", payload, headers,
        )

    # -- revisions / rework -------------------------------------------------
    def create_revision(self, payload, headers):
        return self._request("POST", f"{PREFIX}/revisions", payload, headers)

    def list_revisions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/revisions", headers=headers, params=params)

    def submit_revision(self, revision_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/revisions/{revision_id}/submit", payload or {}, headers,
        )

    def approve_revision(self, revision_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/revisions/{revision_id}/approve", payload, headers,
        )

    def set_rework_job_status(self, job_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/rework-jobs/{job_id}/status", payload, headers)

    def list_rework_jobs(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/rework-jobs", headers=headers, params=params)

    # -- procurement --------------------------------------------------------
    def create_material_release(self, payload, headers):
        return self._request("POST", f"{PREFIX}/material-releases", payload, headers)

    def list_material_releases(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/material-releases", headers=headers, params=params)

    def get_material_release(self, release_id, headers):
        return self._request(
            "GET", f"{PREFIX}/material-releases/{release_id}", headers=headers,
        )

    def declare_material_release(self, release_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/material-releases/{release_id}/declare", payload, headers,
        )

    # -- logical clock ------------------------------------------------------
    def set_current_utc(self, to_iso8601, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers,
        )


api_client = ApiClient()