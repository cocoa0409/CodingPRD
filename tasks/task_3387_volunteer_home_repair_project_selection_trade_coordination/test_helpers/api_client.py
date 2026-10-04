"""API client: one method per endpoint defined in the PRD (§4).

Every method returns the raw requests.Response; callers assert status codes
through the framework validators. PATCH-style transition endpoints take the
full payload dict so the caller controls exactly which fields are sent.
"""

from prd_bench_local_runner.testing import GenericApiClient

REBUILD = "/rebuild"
CLOCK = "/_clock"


class ApiClient(GenericApiClient):
    # ---- FundingCycle -------------------------------------------------
    def create_funding_cycle(self, payload, headers):
        return self._request("POST", f"{REBUILD}/funding-cycles", payload, headers)

    def get_funding_cycle(self, cycle_id, headers):
        return self._request(
            "GET", f"{REBUILD}/funding-cycles/{cycle_id}", headers=headers
        )

    def patch_funding_cycle(self, cycle_id, payload, headers):
        return self._request(
            "PATCH", f"{REBUILD}/funding-cycles/{cycle_id}", payload, headers
        )

    # ---- SelectionRun ---------------------------------------------------
    def create_selection_run(self, cycle_id, payload, headers):
        return self._request(
            "POST",
            f"{REBUILD}/funding-cycles/{cycle_id}/selection-runs",
            payload,
            headers,
        )

    def list_selection_runs(self, headers, params=None):
        return self._request(
            "GET", f"{REBUILD}/selection-runs", headers=headers, params=params
        )

    def get_selection_run(self, run_id, headers):
        return self._request(
            "GET", f"{REBUILD}/selection-runs/{run_id}", headers=headers
        )

    def apply_selection_run(self, run_id, headers):
        return self._request(
            "POST", f"{REBUILD}/selection-runs/{run_id}/apply", {}, headers
        )

    # ---- Sponsor / SponsorshipCommitment --------------------------------
    def create_sponsor(self, payload, headers):
        return self._request("POST", f"{REBUILD}/sponsors", payload, headers)

    def get_sponsor(self, sponsor_id, headers):
        return self._request("GET", f"{REBUILD}/sponsors/{sponsor_id}", headers=headers)

    def create_commitment(self, payload, headers):
        return self._request("POST", f"{REBUILD}/commitments", payload, headers)

    def list_commitments(self, headers, params=None):
        return self._request(
            "GET", f"{REBUILD}/commitments", headers=headers, params=params
        )

    def get_commitment(self, commitment_id, headers):
        return self._request(
            "GET", f"{REBUILD}/commitments/{commitment_id}", headers=headers
        )

    def patch_commitment(self, commitment_id, payload, headers):
        return self._request(
            "PATCH", f"{REBUILD}/commitments/{commitment_id}", payload, headers
        )

    # ---- HomeownerApplication -------------------------------------------
    def create_application(self, payload, headers):
        return self._request("POST", f"{REBUILD}/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request(
            "GET", f"{REBUILD}/applications", headers=headers, params=params
        )

    def get_application(self, application_id, headers):
        return self._request(
            "GET", f"{REBUILD}/applications/{application_id}", headers=headers
        )

    def patch_application(self, application_id, payload, headers):
        return self._request(
            "PATCH", f"{REBUILD}/applications/{application_id}", payload, headers
        )

    # ---- HomeAssessment / ScopeItem -------------------------------------
    def create_assessment(self, payload, headers):
        return self._request("POST", f"{REBUILD}/assessments", payload, headers)

    def list_assessments(self, headers, params=None):
        return self._request(
            "GET", f"{REBUILD}/assessments", headers=headers, params=params
        )

    def get_assessment(self, assessment_id, headers):
        return self._request(
            "GET", f"{REBUILD}/assessments/{assessment_id}", headers=headers
        )

    def complete_assessment(self, assessment_id, payload, headers):
        return self._request(
            "POST",
            f"{REBUILD}/assessments/{assessment_id}/complete",
            payload,
            headers,
        )

    def patch_assessment(self, assessment_id, payload, headers):
        return self._request(
            "PATCH", f"{REBUILD}/assessments/{assessment_id}", payload, headers
        )

    def list_scope_items(self, headers, params=None):
        return self._request(
            "GET", f"{REBUILD}/scope-items", headers=headers, params=params
        )

    def get_scope_item(self, scope_item_id, headers):
        return self._request(
            "GET", f"{REBUILD}/scope-items/{scope_item_id}", headers=headers
        )

    # ---- Project ----------------------------------------------------------
    def list_projects(self, headers, params=None):
        return self._request("GET", f"{REBUILD}/projects", headers=headers, params=params)

    def get_project(self, project_id, headers):
        return self._request("GET", f"{REBUILD}/projects/{project_id}", headers=headers)

    def patch_project(self, project_id, payload, headers):
        return self._request(
            "PATCH", f"{REBUILD}/projects/{project_id}", payload, headers
        )

    def create_scope_amendment(self, project_id, payload, headers):
        return self._request(
            "POST", f"{REBUILD}/projects/{project_id}/scope-amendments", payload, headers
        )

    # ---- RebuildEvent -----------------------------------------------------
    def create_event(self, payload, headers):
        return self._request("POST", f"{REBUILD}/events", payload, headers)

    def list_events(self, headers, params=None):
        return self._request("GET", f"{REBUILD}/events", headers=headers, params=params)

    def get_event(self, event_id, headers):
        return self._request("GET", f"{REBUILD}/events/{event_id}", headers=headers)

    def patch_event(self, event_id, payload, headers):
        return self._request("PATCH", f"{REBUILD}/events/{event_id}", payload, headers)

    # ---- Volunteer --------------------------------------------------------
    def create_volunteer(self, payload, headers):
        return self._request("POST", f"{REBUILD}/volunteers", payload, headers)

    def get_volunteer(self, volunteer_id, headers):
        return self._request(
            "GET", f"{REBUILD}/volunteers/{volunteer_id}", headers=headers
        )

    def patch_volunteer(self, volunteer_id, payload, headers):
        return self._request(
            "PATCH", f"{REBUILD}/volunteers/{volunteer_id}", payload, headers
        )

    # ---- EventEnrollment --------------------------------------------------
    def create_enrollment(self, payload, headers):
        return self._request("POST", f"{REBUILD}/enrollments", payload, headers)

    def list_enrollments(self, headers, params=None):
        return self._request(
            "GET", f"{REBUILD}/enrollments", headers=headers, params=params
        )

    def get_enrollment(self, enrollment_id, headers):
        return self._request(
            "GET", f"{REBUILD}/enrollments/{enrollment_id}", headers=headers
        )

    def patch_enrollment(self, enrollment_id, payload, headers):
        return self._request(
            "PATCH", f"{REBUILD}/enrollments/{enrollment_id}", payload, headers
        )

    # ---- TradeContractor --------------------------------------------------
    def create_trade_contractor(self, payload, headers):
        return self._request("POST", f"{REBUILD}/trade-contractors", payload, headers)

    def get_trade_contractor(self, contractor_id, headers):
        return self._request(
            "GET", f"{REBUILD}/trade-contractors/{contractor_id}", headers=headers
        )

    def patch_trade_contractor(self, contractor_id, payload, headers):
        return self._request(
            "PATCH", f"{REBUILD}/trade-contractors/{contractor_id}", payload, headers
        )

    # ---- TradeWorkOrder ---------------------------------------------------
    def create_trade_work_order(self, payload, headers):
        return self._request("POST", f"{REBUILD}/trade-work-orders", payload, headers)

    def list_trade_work_orders(self, headers, params=None):
        return self._request(
            "GET", f"{REBUILD}/trade-work-orders", headers=headers, params=params
        )

    def get_trade_work_order(self, work_order_id, headers):
        return self._request(
            "GET", f"{REBUILD}/trade-work-orders/{work_order_id}", headers=headers
        )

    def schedule_trade_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST",
            f"{REBUILD}/trade-work-orders/{work_order_id}/schedule",
            payload,
            headers,
        )

    def inspect_trade_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST",
            f"{REBUILD}/trade-work-orders/{work_order_id}/inspect",
            payload,
            headers,
        )

    def patch_trade_work_order(self, work_order_id, payload, headers):
        return self._request(
            "PATCH", f"{REBUILD}/trade-work-orders/{work_order_id}", payload, headers
        )

    # ---- MaterialOrder ----------------------------------------------------
    def create_material_order(self, payload, headers):
        return self._request("POST", f"{REBUILD}/material-orders", payload, headers)

    def list_material_orders(self, headers, params=None):
        return self._request(
            "GET", f"{REBUILD}/material-orders", headers=headers, params=params
        )

    def get_material_order(self, order_id, headers):
        return self._request(
            "GET", f"{REBUILD}/material-orders/{order_id}", headers=headers
        )

    def patch_material_order(self, order_id, payload, headers):
        return self._request(
            "PATCH", f"{REBUILD}/material-orders/{order_id}", payload, headers
        )

    # ---- WarrantyClaim ----------------------------------------------------
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", f"{REBUILD}/warranty-claims", payload, headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request(
            "GET", f"{REBUILD}/warranty-claims", headers=headers, params=params
        )

    def get_warranty_claim(self, claim_id, headers):
        return self._request(
            "GET", f"{REBUILD}/warranty-claims/{claim_id}", headers=headers
        )

    def patch_warranty_claim(self, claim_id, payload, headers):
        return self._request(
            "PATCH", f"{REBUILD}/warranty-claims/{claim_id}", payload, headers
        )

    # ---- Logical clock (test-driving) -------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", f"{CLOCK}/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
