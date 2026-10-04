"""API client: one method per endpoint defined in the PRD (§4).

All POST helpers auto-attach a fresh Idempotency-Key header per call unless the
caller supplies one via ``idem_key`` (PRD §2.9); idempotency replay tests pass
an explicit key, and missing-key tests pass ``idem_key=False`` to suppress it.
"""
import uuid

from prd_bench_local_runner.testing import GenericApiClient


def _with_idem(headers, idem_key=None):
    h = dict(headers or {})
    if idem_key is False:
        h.pop("Idempotency-Key", None)
        return h
    h["Idempotency-Key"] = idem_key if idem_key is not None else str(uuid.uuid4())
    return h


class ApiClient(GenericApiClient):
    # ---- logical clock --------------------------------------------------
    def set_clock(self, current_utc, headers, idem_key=None):
        return self._request(
            "POST",
            "/construction/_clock/set_current_utc",
            {"current_utc": current_utc},
            _with_idem(headers, idem_key),
        )

    # ---- jurisdictions --------------------------------------------------
    def create_jurisdiction(self, payload, headers, idem_key=None):
        return self._request(
            "POST", "/construction/jurisdictions", payload, _with_idem(headers, idem_key)
        )

    def list_jurisdiction_sites(self, jurisdiction_id, headers, params=None):
        return self._request(
            "GET",
            f"/construction/jurisdictions/{jurisdiction_id}/sites",
            headers=headers,
            params=params,
        )

    # ---- community deployments -----------------------------------------
    def create_community_deployment(self, payload, headers, idem_key=None):
        return self._request(
            "POST",
            "/construction/community-deployments",
            payload,
            _with_idem(headers, idem_key),
        )

    def get_community_deployment(self, deployment_id, headers):
        return self._request(
            "GET", f"/construction/community-deployments/{deployment_id}", headers=headers
        )

    def activate_community_deployment(self, deployment_id, headers, idem_key=None):
        return self._request(
            "POST",
            f"/construction/community-deployments/{deployment_id}/activate",
            {},
            _with_idem(headers, idem_key),
        )

    def set_learning_variant(self, deployment_id, payload, headers, idem_key=None):
        return self._request(
            "POST",
            f"/construction/community-deployments/{deployment_id}/set-learning-variant",
            payload,
            _with_idem(headers, idem_key),
        )

    # ---- sites ----------------------------------------------------------
    def create_site(self, payload, headers, idem_key=None):
        return self._request(
            "POST", "/construction/sites", payload, _with_idem(headers, idem_key)
        )

    def get_site(self, site_id, headers):
        return self._request("GET", f"/construction/sites/{site_id}", headers=headers)

    def site_action(self, site_id, payload, headers, idem_key=None):
        return self._request(
            "POST",
            f"/construction/sites/{site_id}/action",
            payload,
            _with_idem(headers, idem_key),
        )

    # ---- structural plans / revisions -----------------------------------
    def create_structural_plan(self, payload, headers, idem_key=None):
        return self._request(
            "POST", "/construction/structural-plans", payload, _with_idem(headers, idem_key)
        )

    def list_plan_revisions(self, plan_id, headers, params=None):
        return self._request(
            "GET",
            f"/construction/structural-plans/{plan_id}/revisions",
            headers=headers,
            params=params,
        )

    def create_plan_revision(self, plan_id, payload, headers, idem_key=None):
        return self._request(
            "POST",
            f"/construction/structural-plans/{plan_id}/revisions",
            payload,
            _with_idem(headers, idem_key),
        )

    def plan_revision_action(self, plan_id, revision_id, payload, headers, idem_key=None):
        return self._request(
            "POST",
            f"/construction/structural-plans/{plan_id}/revisions/{revision_id}/action",
            payload,
            _with_idem(headers, idem_key),
        )

    # ---- permit applications --------------------------------------------
    def create_permit_application(self, site_id, payload, headers, idem_key=None):
        return self._request(
            "POST",
            f"/construction/sites/{site_id}/permit-applications",
            payload,
            _with_idem(headers, idem_key),
        )

    def list_permit_applications(self, site_id, headers, params=None):
        return self._request(
            "GET",
            f"/construction/sites/{site_id}/permit-applications",
            headers=headers,
            params=params,
        )

    def get_permit_application(self, site_id, application_id, headers):
        return self._request(
            "GET",
            f"/construction/sites/{site_id}/permit-applications/{application_id}",
            headers=headers,
        )

    def permit_application_action(self, site_id, application_id, payload, headers, idem_key=None):
        return self._request(
            "POST",
            f"/construction/sites/{site_id}/permit-applications/{application_id}/action",
            payload,
            _with_idem(headers, idem_key),
        )

    # ---- printer setups ---------------------------------------------------
    def create_printer_setup(self, site_id, payload, headers, idem_key=None):
        return self._request(
            "POST",
            f"/construction/sites/{site_id}/printer-setups",
            payload,
            _with_idem(headers, idem_key),
        )

    def list_printer_setups(self, site_id, headers, params=None):
        return self._request(
            "GET",
            f"/construction/sites/{site_id}/printer-setups",
            headers=headers,
            params=params,
        )

    def advance_printer_setup(self, site_id, setup_id, payload, headers, idem_key=None):
        return self._request(
            "POST",
            f"/construction/sites/{site_id}/printer-setups/{setup_id}/advance",
            payload,
            _with_idem(headers, idem_key),
        )

    # ---- material batches -------------------------------------------------
    def create_material_batch(self, site_id, payload, headers, idem_key=None):
        return self._request(
            "POST",
            f"/construction/sites/{site_id}/material-batches",
            payload,
            _with_idem(headers, idem_key),
        )

    def list_material_batches(self, site_id, headers, params=None):
        return self._request(
            "GET",
            f"/construction/sites/{site_id}/material-batches",
            headers=headers,
            params=params,
        )

    def qualify_material_batch(self, site_id, batch_id, headers, idem_key=None):
        return self._request(
            "POST",
            f"/construction/sites/{site_id}/material-batches/{batch_id}/qualify",
            {},
            _with_idem(headers, idem_key),
        )

    # ---- weather observations ---------------------------------------------
    def post_weather_observation(self, site_id, payload, headers, idem_key=None):
        return self._request(
            "POST",
            f"/construction/sites/{site_id}/weather-observations",
            payload,
            _with_idem(headers, idem_key),
        )

    def list_weather_observations(self, site_id, headers, params=None):
        return self._request(
            "GET",
            f"/construction/sites/{site_id}/weather-observations",
            headers=headers,
            params=params,
        )

    # ---- print jobs ---------------------------------------------------------
    def create_print_job(self, site_id, payload, headers, idem_key=None):
        return self._request(
            "POST",
            f"/construction/sites/{site_id}/print-jobs",
            payload,
            _with_idem(headers, idem_key),
        )

    def list_print_jobs(self, site_id, headers, params=None):
        return self._request(
            "GET",
            f"/construction/sites/{site_id}/print-jobs",
            headers=headers,
            params=params,
        )

    def transition_print_job(self, site_id, job_id, payload, headers, idem_key=None):
        return self._request(
            "POST",
            f"/construction/sites/{site_id}/print-jobs/{job_id}/transition",
            payload,
            _with_idem(headers, idem_key),
        )

    # ---- layer inspections --------------------------------------------------
    def create_layer_inspection(self, site_id, job_id, payload, headers, idem_key=None):
        return self._request(
            "POST",
            f"/construction/sites/{site_id}/print-jobs/{job_id}/layer-inspections",
            payload,
            _with_idem(headers, idem_key),
        )

    def list_layer_inspections(self, site_id, job_id, headers, params=None):
        return self._request(
            "GET",
            f"/construction/sites/{site_id}/print-jobs/{job_id}/layer-inspections",
            headers=headers,
            params=params,
        )

    def disposition_layer_inspection(
        self, site_id, job_id, inspection_id, payload, headers, idem_key=None
    ):
        return self._request(
            "POST",
            f"/construction/sites/{site_id}/print-jobs/{job_id}/layer-inspections/{inspection_id}/disposition",
            payload,
            _with_idem(headers, idem_key),
        )

    # ---- conventional trade tasks -------------------------------------------
    def create_trade_task(self, site_id, payload, headers, idem_key=None):
        return self._request(
            "POST",
            f"/construction/sites/{site_id}/trade-tasks",
            payload,
            _with_idem(headers, idem_key),
        )

    def list_trade_tasks(self, site_id, headers, params=None):
        return self._request(
            "GET",
            f"/construction/sites/{site_id}/trade-tasks",
            headers=headers,
            params=params,
        )

    def transition_trade_task(self, site_id, task_id, payload, headers, idem_key=None):
        return self._request(
            "POST",
            f"/construction/sites/{site_id}/trade-tasks/{task_id}/transition",
            payload,
            _with_idem(headers, idem_key),
        )


api_client = ApiClient()
