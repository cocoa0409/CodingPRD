"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock ---------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- branches ----------------------------------------------------------
    def create_branch(self, payload, headers):
        return self._request("POST", "/branches", payload, headers)

    def get_branch(self, branch_id, headers):
        return self._request("GET", f"/branches/{branch_id}", headers=headers)

    def list_branch_center_managers(self, branch_id, headers, params=None):
        return self._request(
            "GET", f"/branches/{branch_id}/center-managers", headers=headers, params=params
        )

    def list_branch_expansion_plans(self, branch_id, headers, params=None):
        return self._request(
            "GET", f"/branches/{branch_id}/expansion-plans", headers=headers, params=params
        )

    def submit_expansion_plan(self, branch_id, payload, headers):
        return self._request(
            "POST", f"/branches/{branch_id}/expansion-plans", payload, headers
        )

    def decide_expansion_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/expansion-plans/{plan_id}/decide", payload, headers
        )

    # ---- center managers -----------------------------------------------------
    def create_center_manager(self, payload, headers):
        return self._request("POST", "/center-managers", payload, headers)

    def get_center_manager(self, manager_id, headers):
        return self._request("GET", f"/center-managers/{manager_id}", headers=headers)

    def list_manager_training_sessions(self, manager_id, headers, params=None):
        return self._request(
            "GET", f"/center-managers/{manager_id}/training-sessions",
            headers=headers, params=params,
        )

    # ---- centers -------------------------------------------------------------
    def create_center(self, payload, headers):
        return self._request("POST", "/centers", payload, headers)

    def list_centers(self, headers, params=None):
        return self._request("GET", "/centers", headers=headers, params=params)

    def get_center(self, center_id, headers):
        return self._request("GET", f"/centers/{center_id}", headers=headers)

    def reassign_center(self, center_id, payload, headers):
        return self._request("PATCH", f"/centers/{center_id}", payload, headers)

    def list_center_peer_groups(self, center_id, headers, params=None):
        return self._request(
            "GET", f"/centers/{center_id}/peer-groups", headers=headers, params=params
        )

    # ---- peer groups -----------------------------------------------------------
    def create_peer_group(self, payload, headers):
        return self._request("POST", "/peer-groups", payload, headers)

    def list_peer_groups(self, headers, params=None):
        return self._request("GET", "/peer-groups", headers=headers, params=params)

    def get_peer_group(self, group_id, headers):
        return self._request("GET", f"/peer-groups/{group_id}", headers=headers)

    def list_group_members(self, group_id, headers, params=None):
        return self._request(
            "GET", f"/peer-groups/{group_id}/members", headers=headers, params=params
        )

    def add_group_member(self, group_id, payload, headers):
        return self._request(
            "POST", f"/peer-groups/{group_id}/members", payload, headers
        )

    def dissolve_peer_group(self, group_id, headers):
        return self._request(
            "POST", f"/peer-groups/{group_id}/dissolve", {}, headers
        )

    def list_group_training_sessions(self, group_id, headers, params=None):
        return self._request(
            "GET", f"/peer-groups/{group_id}/training-sessions",
            headers=headers, params=params,
        )

    def create_loan_application(self, group_id, payload, headers):
        return self._request(
            "POST", f"/peer-groups/{group_id}/loan-applications", payload, headers
        )

    # ---- members ------------------------------------------------------------------
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def list_member_votes(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/members/{member_id}/votes", headers=headers, params=params
        )

    def list_member_attendance(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/members/{member_id}/attendance", headers=headers, params=params
        )

    def get_member_savings_account(self, member_id, headers):
        return self._request(
            "GET", f"/members/{member_id}/savings-account", headers=headers
        )

    def withdraw_savings(self, member_id, payload, headers):
        return self._request(
            "POST", f"/members/{member_id}/savings/withdrawals", payload, headers
        )

    def unfreeze_savings(self, member_id, headers):
        return self._request(
            "POST", f"/members/{member_id}/savings/unfreeze", {}, headers
        )

    def close_savings(self, member_id, headers):
        return self._request(
            "POST", f"/members/{member_id}/savings/close", {}, headers
        )

    def list_member_bureau_reports(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/members/{member_id}/bureau-reports", headers=headers, params=params
        )

    # ---- training sessions ------------------------------------------------------------
    def create_training_session(self, payload, headers):
        return self._request("POST", "/group-training-sessions", payload, headers)

    def list_training_sessions(self, headers, params=None):
        return self._request(
            "GET", "/group-training-sessions", headers=headers, params=params
        )

    def complete_training_session(self, session_id, headers):
        return self._request(
            "POST", f"/group-training-sessions/{session_id}/complete", {}, headers
        )

    def cancel_training_session(self, session_id, headers):
        return self._request(
            "POST", f"/group-training-sessions/{session_id}/cancel", {}, headers
        )

    # ---- loan applications ---------------------------------------------------------------
    def list_loan_applications(self, headers, params=None):
        return self._request("GET", "/loan-applications", headers=headers, params=params)

    def get_loan_application(self, application_id, headers):
        return self._request(
            "GET", f"/loan-applications/{application_id}", headers=headers
        )

    def submit_loan_application(self, application_id, headers):
        return self._request(
            "POST", f"/loan-applications/{application_id}/submit", {}, headers
        )

    def cast_vote(self, application_id, payload, headers):
        return self._request(
            "POST", f"/loan-applications/{application_id}/votes", payload, headers
        )

    def list_application_votes(self, application_id, headers, params=None):
        return self._request(
            "GET", f"/loan-applications/{application_id}/votes",
            headers=headers, params=params,
        )

    def get_application_loan(self, application_id, headers):
        return self._request(
            "GET", f"/loan-applications/{application_id}/loan", headers=headers
        )

    def disburse_loan_application(self, application_id, headers):
        return self._request(
            "POST", f"/loan-applications/{application_id}/disburse", {}, headers
        )

    # ---- loans -------------------------------------------------------------------------
    def list_loans(self, headers, params=None):
        return self._request("GET", "/loans", headers=headers, params=params)

    def get_loan(self, loan_id, headers):
        return self._request("GET", f"/loans/{loan_id}", headers=headers)

    def create_restructure(self, loan_id, payload, headers):
        return self._request(
            "POST", f"/loans/{loan_id}/restructures", payload, headers
        )

    def list_loan_restructures(self, loan_id, headers, params=None):
        return self._request(
            "GET", f"/loans/{loan_id}/restructures", headers=headers, params=params
        )

    def list_loan_bureau_reports(self, loan_id, headers, params=None):
        return self._request(
            "GET", f"/loans/{loan_id}/bureau-reports", headers=headers, params=params
        )

    # ---- center meetings -----------------------------------------------------------------
    def create_center_meeting(self, payload, headers):
        return self._request("POST", "/center-meetings", payload, headers)

    def list_center_meetings(self, headers, params=None):
        return self._request("GET", "/center-meetings", headers=headers, params=params)

    def get_center_meeting(self, meeting_id, headers):
        return self._request("GET", f"/center-meetings/{meeting_id}", headers=headers)

    def open_meeting(self, meeting_id, headers):
        return self._request(
            "POST", f"/center-meetings/{meeting_id}/open", {}, headers
        )

    def cancel_meeting(self, meeting_id, headers):
        return self._request(
            "POST", f"/center-meetings/{meeting_id}/cancel", {}, headers
        )

    def record_attendance(self, meeting_id, payload, headers):
        return self._request(
            "POST", f"/center-meetings/{meeting_id}/attendance", payload, headers
        )

    def list_meeting_attendance(self, meeting_id, headers, params=None):
        return self._request(
            "GET", f"/center-meetings/{meeting_id}/attendance",
            headers=headers, params=params,
        )

    def post_collection(self, meeting_id, payload, headers):
        return self._request(
            "POST", f"/center-meetings/{meeting_id}/collections", payload, headers
        )

    def close_meeting(self, meeting_id, headers):
        return self._request(
            "POST", f"/center-meetings/{meeting_id}/close", {}, headers
        )

    def reconcile_meeting(self, meeting_id, payload, headers):
        return self._request(
            "POST", f"/center-meetings/{meeting_id}/reconcile", payload, headers
        )

    # ---- repayment transactions ------------------------------------------------------------
    def list_repayment_transactions(self, headers, params=None):
        return self._request(
            "GET", "/repayment-transactions", headers=headers, params=params
        )

    def get_repayment_transaction(self, transaction_id, headers):
        return self._request(
            "GET", f"/repayment-transactions/{transaction_id}", headers=headers
        )

    def void_repayment_transaction(self, transaction_id, headers):
        return self._request(
            "POST", f"/repayment-transactions/{transaction_id}/void", {}, headers
        )


api_client = ApiClient()
