"""API client: one method per endpoint defined in the PRD (§4).

All endpoints are mounted under /api/v1; the framework client prepends the
base URL, so methods pass paths including the /api/v1 prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def _request(self, method, path, payload=None, headers=None, params=None):
        # per-test-server isolation restarts the server before every test;
        # forcing Connection: close prevents the session-scoped client from
        # reusing a stale keep-alive connection to the previous server
        # process (RemoteDisconnected flakes on the first request of a test).
        hdrs = dict(headers or {})
        hdrs.setdefault("Connection", "close")
        return super()._request(method, path, payload, hdrs, params)

    # --- Logical clock ---
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/api/v1/_clock/set_current_utc",
            {"current_utc": current_utc}, headers,
        )

    # --- Conversion projects ---
    def create_project(self, payload, headers):
        return self._request("POST", "/api/v1/conversions", payload, headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/api/v1/conversions", headers=headers, params=params)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/api/v1/conversions/{project_id}", headers=headers)

    def advance_project(self, project_id, headers):
        return self._request("POST", f"/api/v1/conversions/{project_id}/advance", headers=headers)

    def plan_cutover(self, project_id, payload, headers):
        return self._request(
            "POST", f"/api/v1/conversions/{project_id}/plan-cutover", payload, headers
        )

    def go_live(self, project_id, headers):
        return self._request("POST", f"/api/v1/conversions/{project_id}/go-live", headers=headers)

    def close_project(self, project_id, headers):
        return self._request("POST", f"/api/v1/conversions/{project_id}/close", headers=headers)

    # --- Product types ---
    def create_product_type(self, payload, headers):
        return self._request("POST", "/api/v1/product-types", payload, headers)

    def list_product_types(self, headers, params=None):
        return self._request("GET", "/api/v1/product-types", headers=headers, params=params)

    def get_product_type(self, ptid, headers):
        return self._request("GET", f"/api/v1/product-types/{ptid}", headers=headers)

    def activate_product_type(self, ptid, headers):
        return self._request("POST", f"/api/v1/product-types/{ptid}/activate", headers=headers)

    def deactivate_product_type(self, ptid, headers):
        return self._request("POST", f"/api/v1/product-types/{ptid}/deactivate", headers=headers)

    def retire_product_type(self, ptid, headers):
        return self._request("POST", f"/api/v1/product-types/{ptid}/retire", headers=headers)

    def list_accounts_of_product(self, ptid, headers, params=None):
        return self._request(
            "GET", f"/api/v1/product-types/{ptid}/accounts", headers=headers, params=params
        )

    # --- GL accounts ---
    def create_gl_account(self, payload, headers):
        return self._request("POST", "/api/v1/gl-accounts", payload, headers)

    def list_gl_accounts(self, headers, params=None):
        return self._request("GET", "/api/v1/gl-accounts", headers=headers, params=params)

    def get_gl_account(self, gid, headers):
        return self._request("GET", f"/api/v1/gl-accounts/{gid}", headers=headers)

    def list_accounts_of_gl(self, gid, headers, params=None):
        return self._request(
            "GET", f"/api/v1/gl-accounts/{gid}/accounts", headers=headers, params=params
        )

    # --- Accounts ---
    def create_account(self, payload, headers):
        return self._request("POST", "/api/v1/accounts", payload, headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/api/v1/accounts", headers=headers, params=params)

    def get_account(self, aid, headers):
        return self._request("GET", f"/api/v1/accounts/{aid}", headers=headers)

    def map_account(self, aid, payload, headers):
        return self._request("POST", f"/api/v1/accounts/{aid}/map", payload, headers)

    def flag_exception(self, aid, payload, headers):
        return self._request("POST", f"/api/v1/accounts/{aid}/flag-exception", payload, headers)

    def clear_exception(self, aid, payload, headers):
        return self._request("POST", f"/api/v1/accounts/{aid}/clear-exception", payload, headers)

    def list_comms_of_account(self, aid, headers, params=None):
        return self._request(
            "GET", f"/api/v1/accounts/{aid}/customer-comms", headers=headers, params=params
        )

    # --- Mock runs ---
    def create_mock_run(self, payload, headers):
        return self._request("POST", "/api/v1/mock-runs", payload, headers)

    def list_mock_runs(self, headers, params=None):
        return self._request("GET", "/api/v1/mock-runs", headers=headers, params=params)

    def get_mock_run(self, rid, headers):
        return self._request("GET", f"/api/v1/mock-runs/{rid}", headers=headers)

    def finalize_mock_run(self, rid, headers):
        return self._request("POST", f"/api/v1/mock-runs/{rid}/finalize", headers=headers)

    # --- Ancillary systems ---
    def create_ancillary_system(self, payload, headers):
        return self._request("POST", "/api/v1/ancillary-systems", payload, headers)

    def list_ancillary_systems(self, headers, params=None):
        return self._request("GET", "/api/v1/ancillary-systems", headers=headers, params=params)

    def get_ancillary_system(self, sid, headers):
        return self._request("GET", f"/api/v1/ancillary-systems/{sid}", headers=headers)

    def start_integration(self, sid, headers):
        return self._request(
            "POST", f"/api/v1/ancillary-systems/{sid}/start-integration", headers=headers
        )

    def verify_integration(self, sid, headers):
        return self._request("POST", f"/api/v1/ancillary-systems/{sid}/verify", headers=headers)

    def fail_integration(self, sid, headers):
        return self._request("POST", f"/api/v1/ancillary-systems/{sid}/fail", headers=headers)

    def retest_integration(self, sid, headers):
        return self._request("POST", f"/api/v1/ancillary-systems/{sid}/retest", headers=headers)

    def list_defects_of_system(self, sid, headers, params=None):
        return self._request(
            "GET", f"/api/v1/ancillary-systems/{sid}/defects", headers=headers, params=params
        )

    # --- Training sessions / staff / enrollments ---
    def create_training_session(self, payload, headers):
        return self._request("POST", "/api/v1/training-sessions", payload, headers)

    def list_training_sessions(self, headers, params=None):
        return self._request("GET", "/api/v1/training-sessions", headers=headers, params=params)

    def get_training_session(self, tsid, headers):
        return self._request("GET", f"/api/v1/training-sessions/{tsid}", headers=headers)

    def start_training_session(self, tsid, headers):
        return self._request("POST", f"/api/v1/training-sessions/{tsid}/start", headers=headers)

    def complete_training_session(self, tsid, headers):
        return self._request("POST", f"/api/v1/training-sessions/{tsid}/complete", headers=headers)

    def cancel_training_session(self, tsid, headers):
        return self._request("POST", f"/api/v1/training-sessions/{tsid}/cancel", headers=headers)

    def create_staff(self, payload, headers):
        return self._request("POST", "/api/v1/staff", payload, headers)

    def list_staff(self, headers, params=None):
        return self._request("GET", "/api/v1/staff", headers=headers, params=params)

    def get_staff(self, smid, headers):
        return self._request("GET", f"/api/v1/staff/{smid}", headers=headers)

    def list_enrollments_of_staff(self, smid, headers, params=None):
        return self._request(
            "GET", f"/api/v1/staff/{smid}/enrollments", headers=headers, params=params
        )

    def create_enrollment(self, payload, headers):
        return self._request("POST", "/api/v1/enrollments", payload, headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/api/v1/enrollments", headers=headers, params=params)

    def attend_enrollment(self, eid, headers):
        return self._request("POST", f"/api/v1/enrollments/{eid}/attend", headers=headers)

    def no_show_enrollment(self, eid, headers):
        return self._request("POST", f"/api/v1/enrollments/{eid}/no-show", headers=headers)

    def cancel_enrollment(self, eid, headers):
        return self._request("POST", f"/api/v1/enrollments/{eid}/cancel", headers=headers)

    # --- Customer communications ---
    def create_comm(self, payload, headers):
        return self._request("POST", "/api/v1/customer-comms", payload, headers)

    def list_comms(self, headers, params=None):
        return self._request("GET", "/api/v1/customer-comms", headers=headers, params=params)

    def get_comm(self, cid, headers):
        return self._request("GET", f"/api/v1/customer-comms/{cid}", headers=headers)

    def schedule_comm(self, cid, payload, headers):
        return self._request("POST", f"/api/v1/customer-comms/{cid}/schedule", payload, headers)

    def send_comm(self, cid, headers):
        return self._request("POST", f"/api/v1/customer-comms/{cid}/send", headers=headers)

    def deliver_comm(self, cid, headers):
        return self._request("POST", f"/api/v1/customer-comms/{cid}/deliver", headers=headers)

    def fail_comm(self, cid, headers):
        return self._request("POST", f"/api/v1/customer-comms/{cid}/fail", headers=headers)

    def resend_comm(self, cid, headers):
        return self._request("POST", f"/api/v1/customer-comms/{cid}/resend", headers=headers)

    def cancel_comm(self, cid, headers):
        return self._request("POST", f"/api/v1/customer-comms/{cid}/cancel", headers=headers)

    # --- Defects ---
    def create_defect(self, payload, headers):
        return self._request("POST", "/api/v1/defects", payload, headers)

    def list_defects(self, headers, params=None):
        return self._request("GET", "/api/v1/defects", headers=headers, params=params)

    def get_defect(self, did, headers):
        return self._request("GET", f"/api/v1/defects/{did}", headers=headers)

    def triage_defect(self, did, headers):
        return self._request("POST", f"/api/v1/defects/{did}/triage", headers=headers)

    def start_fix_defect(self, did, headers):
        return self._request("POST", f"/api/v1/defects/{did}/start-fix", headers=headers)

    def reject_fix_defect(self, did, headers):
        return self._request("POST", f"/api/v1/defects/{did}/reject-fix", headers=headers)

    def resolve_defect(self, did, headers):
        return self._request("POST", f"/api/v1/defects/{did}/resolve", headers=headers)

    def reopen_defect(self, did, headers):
        return self._request("POST", f"/api/v1/defects/{did}/reopen", headers=headers)

    def close_defect(self, did, headers):
        return self._request("POST", f"/api/v1/defects/{did}/close", headers=headers)

    # --- Service credit claims ---
    def create_service_credit(self, payload, headers):
        return self._request("POST", "/api/v1/service-credits", payload, headers)

    def list_service_credits(self, headers, params=None):
        return self._request("GET", "/api/v1/service-credits", headers=headers, params=params)

    def get_service_credit(self, scid, headers):
        return self._request("GET", f"/api/v1/service-credits/{scid}", headers=headers)

    def approve_service_credit(self, scid, headers):
        return self._request("POST", f"/api/v1/service-credits/{scid}/approve", headers=headers)

    def pay_service_credit(self, scid, headers):
        return self._request("POST", f"/api/v1/service-credits/{scid}/pay", headers=headers)

    def dispute_service_credit(self, scid, payload, headers):
        return self._request(
            "POST", f"/api/v1/service-credits/{scid}/dispute", payload, headers
        )

    def reopen_service_credit(self, scid, headers):
        return self._request("POST", f"/api/v1/service-credits/{scid}/reopen", headers=headers)

    def reject_service_credit(self, scid, headers):
        return self._request("POST", f"/api/v1/service-credits/{scid}/reject", headers=headers)

    # --- Cutover plans / tasks ---
    def list_plans(self, headers, params=None):
        return self._request("GET", "/api/v1/plans", headers=headers, params=params)

    def get_plan(self, pid, headers):
        return self._request("GET", f"/api/v1/plans/{pid}", headers=headers)

    def create_task(self, payload, headers):
        return self._request("POST", "/api/v1/tasks", payload, headers)

    def list_tasks(self, headers, params=None):
        return self._request("GET", "/api/v1/tasks", headers=headers, params=params)

    def get_task(self, tid, headers):
        return self._request("GET", f"/api/v1/tasks/{tid}", headers=headers)

    def schedule_plan(self, pid, headers):
        return self._request("POST", f"/api/v1/plans/{pid}/schedule", headers=headers)

    def declare_go(self, pid, headers):
        return self._request("POST", f"/api/v1/plans/{pid}/go", headers=headers)

    def rollback_plan(self, pid, headers):
        return self._request("POST", f"/api/v1/plans/{pid}/rollback", headers=headers)

    def start_task(self, tid, headers):
        return self._request("POST", f"/api/v1/tasks/{tid}/start", headers=headers)

    def complete_task(self, tid, headers):
        return self._request("POST", f"/api/v1/tasks/{tid}/complete", headers=headers)

    def fail_task(self, tid, headers):
        return self._request("POST", f"/api/v1/tasks/{tid}/fail", headers=headers)

    def list_task_dependents(self, tid, headers, params=None):
        return self._request(
            "GET", f"/api/v1/tasks/{tid}/dependents", headers=headers, params=params
        )


api_client = ApiClient()
