"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ---- brands ----
    def create_brand(self, payload, headers):
        return self._request("POST", "/brands", payload, headers)

    # ---- license agreements ----
    def create_license_agreement(self, payload, headers):
        return self._request("POST", "/license-agreements", payload, headers)

    def get_license_agreement(self, agreement_id, headers):
        return self._request("GET", f"/license-agreements/{agreement_id}",
                             headers=headers)

    def list_license_agreements(self, headers, params=None):
        return self._request("GET", "/license-agreements", headers=headers,
                             params=params)

    def transition_license_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/license-agreements/{agreement_id}/transition",
                             payload, headers)

    def amend_license_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/license-agreements/{agreement_id}/amend",
                             payload, headers)

    # ---- quality audits ----
    def create_quality_audit(self, agreement_id, payload, headers):
        return self._request("POST", f"/license-agreements/{agreement_id}/quality-audits",
                             payload, headers)

    def list_quality_audits(self, agreement_id, headers, params=None):
        return self._request("GET", f"/license-agreements/{agreement_id}/quality-audits",
                             headers=headers, params=params)

    # ---- pod varieties ----
    def create_pod_variety(self, payload, headers):
        return self._request("POST", "/pod-varieties", payload, headers)

    def get_pod_variety(self, variety_id, headers):
        return self._request("GET", f"/pod-varieties/{variety_id}", headers=headers)

    def list_pod_varieties(self, headers, params=None):
        return self._request("GET", "/pod-varieties", headers=headers, params=params)

    def transition_pod_variety(self, variety_id, payload, headers):
        return self._request("POST", f"/pod-varieties/{variety_id}/transition",
                             payload, headers)

    # ---- brewer models ----
    def create_brewer_model(self, payload, headers):
        return self._request("POST", "/brewer-models", payload, headers)

    # ---- facilities / filling lines ----
    def create_facility(self, payload, headers):
        return self._request("POST", "/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/facilities/{facility_id}", headers=headers)

    def create_filling_line(self, facility_id, payload, headers):
        return self._request("POST", f"/facilities/{facility_id}/filling-lines",
                             payload, headers)

    def list_filling_lines(self, facility_id, headers, params=None):
        return self._request("GET", f"/facilities/{facility_id}/filling-lines",
                             headers=headers, params=params)

    # ---- production runs ----
    def create_production_run(self, payload, headers):
        return self._request("POST", "/production-runs", payload, headers)

    def get_production_run(self, run_id, headers):
        return self._request("GET", f"/production-runs/{run_id}", headers=headers)

    def list_production_runs(self, headers, params=None):
        return self._request("GET", "/production-runs", headers=headers, params=params)

    def transition_production_run(self, run_id, payload, headers):
        return self._request("POST", f"/production-runs/{run_id}/transition",
                             payload, headers)

    # ---- households ----
    def create_household(self, payload, headers):
        return self._request("POST", "/households", payload, headers)

    def get_household(self, household_id, headers):
        return self._request("GET", f"/households/{household_id}", headers=headers)

    # ---- brewers ----
    def create_brewer(self, household_id, payload, headers):
        return self._request("POST", f"/households/{household_id}/brewers",
                             payload, headers)

    def get_brewer(self, brewer_id, headers):
        return self._request("GET", f"/brewers/{brewer_id}", headers=headers)

    def list_brewers(self, headers, params=None):
        return self._request("GET", "/brewers", headers=headers, params=params)

    def record_brews(self, brewer_id, payload, headers):
        return self._request("POST", f"/brewers/{brewer_id}/record-brews",
                             payload, headers)

    # ---- consumption records ----
    def create_consumption_record(self, household_id, payload, headers):
        return self._request("POST", f"/households/{household_id}/consumption-records",
                             payload, headers)

    def list_consumption_records(self, household_id, headers, params=None):
        return self._request("GET", f"/households/{household_id}/consumption-records",
                             headers=headers, params=params)

    # ---- service events ----
    def create_service_event(self, brewer_id, payload, headers):
        return self._request("POST", f"/brewers/{brewer_id}/service-events",
                             payload, headers)

    def list_service_events(self, brewer_id, headers, params=None):
        return self._request("GET", f"/brewers/{brewer_id}/service-events",
                             headers=headers, params=params)

    def resolve_service_event(self, event_id, payload, headers):
        return self._request("POST", f"/service-events/{event_id}/resolve",
                             payload, headers)

    # ---- retail accounts / assortment plans ----
    def create_retail_account(self, payload, headers):
        return self._request("POST", "/retail-accounts", payload, headers)

    def get_retail_account(self, account_id, headers):
        return self._request("GET", f"/retail-accounts/{account_id}", headers=headers)

    def create_assortment_plan(self, account_id, payload, headers):
        return self._request("POST", f"/retail-accounts/{account_id}/assortment-plans",
                             payload, headers)

    def list_assortment_plans(self, account_id, headers, params=None):
        return self._request("GET", f"/retail-accounts/{account_id}/assortment-plans",
                             headers=headers, params=params)

    def transition_assortment_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/assortment-plans/{plan_id}/transition",
                             payload, headers)

    # ---- royalty statements ----
    def create_royalty_statement(self, agreement_id, payload, headers):
        return self._request("POST", f"/license-agreements/{agreement_id}/royalty-statements",
                             payload, headers)

    def list_royalty_statements(self, agreement_id, headers, params=None):
        return self._request("GET", f"/license-agreements/{agreement_id}/royalty-statements",
                             headers=headers, params=params)

    def transition_royalty_statement(self, statement_id, payload, headers):
        return self._request("POST", f"/royalty-statements/{statement_id}/transition",
                             payload, headers)


api_client = ApiClient()
