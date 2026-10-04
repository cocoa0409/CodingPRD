"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock ---
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/survey/_clock/set_current_utc",
            {"current_utc": current_utc}, headers,
        )

    # --- Regions ---
    def create_region(self, payload, headers):
        return self._request("POST", "/survey/regions", payload, headers)

    def get_region(self, region_id, headers):
        return self._request("GET", f"/survey/regions/{region_id}", headers=headers)

    # --- Dealers ---
    def create_dealer(self, payload, headers):
        return self._request("POST", "/survey/dealers", payload, headers)

    def get_dealer(self, dealer_id, headers):
        return self._request("GET", f"/survey/dealers/{dealer_id}", headers=headers)

    def list_dealers(self, headers, params=None):
        return self._request("GET", "/survey/dealers", headers=headers, params=params)

    def get_dealer_score_history(self, dealer_id, headers):
        return self._request(
            "GET", f"/survey/dealers/{dealer_id}/score-history", headers=headers
        )

    # --- Departments ---
    def create_department(self, payload, headers):
        return self._request("POST", "/survey/departments", payload, headers)

    def get_department(self, department_id, headers):
        return self._request(
            "GET", f"/survey/departments/{department_id}", headers=headers
        )

    def list_dealer_departments(self, dealer_id, headers, params=None):
        return self._request(
            "GET", f"/survey/dealers/{dealer_id}/departments",
            headers=headers, params=params,
        )

    # --- Advisors ---
    def create_advisor(self, payload, headers):
        return self._request("POST", "/survey/advisors", payload, headers)

    def get_advisor(self, advisor_id, headers):
        return self._request("GET", f"/survey/advisors/{advisor_id}", headers=headers)

    def list_department_advisors(self, department_id, headers, params=None):
        return self._request(
            "GET", f"/survey/departments/{department_id}/advisors",
            headers=headers, params=params,
        )

    # --- Customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/survey/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request(
            "GET", f"/survey/customers/{customer_id}", headers=headers
        )

    # --- Question sets ---
    def create_question_set(self, payload, headers):
        return self._request("POST", "/survey/question-sets", payload, headers)

    def get_question_set(self, question_set_id, headers):
        return self._request(
            "GET", f"/survey/question-sets/{question_set_id}", headers=headers
        )

    def activate_question_set(self, question_set_id, headers):
        return self._request(
            "POST", f"/survey/question-sets/{question_set_id}/activate",
            {}, headers,
        )

    def retire_question_set(self, question_set_id, headers):
        return self._request(
            "POST", f"/survey/question-sets/{question_set_id}/retire",
            {}, headers,
        )

    # --- Waves ---
    def create_wave(self, payload, headers):
        return self._request("POST", "/survey/waves", payload, headers)

    def get_wave(self, wave_id, headers):
        return self._request("GET", f"/survey/waves/{wave_id}", headers=headers)

    def list_waves(self, headers, params=None):
        return self._request("GET", "/survey/waves", headers=headers, params=params)

    def open_wave(self, wave_id, headers):
        return self._request("POST", f"/survey/waves/{wave_id}/open", {}, headers)

    def close_wave(self, wave_id, headers):
        return self._request("POST", f"/survey/waves/{wave_id}/close", {}, headers)

    def finalize_wave(self, wave_id, headers):
        return self._request(
            "POST", f"/survey/waves/{wave_id}/finalize", {}, headers
        )

    def get_wave_benchmark(self, wave_id, dealer_id, headers):
        return self._request(
            "GET", f"/survey/waves/{wave_id}/benchmarks/{dealer_id}",
            headers=headers,
        )

    def list_wave_invitations(self, wave_id, headers, params=None):
        return self._request(
            "GET", f"/survey/waves/{wave_id}/invitations",
            headers=headers, params=params,
        )

    # --- Transactions ---
    def create_transaction(self, payload, headers):
        return self._request("POST", "/survey/transactions", payload, headers)

    def get_transaction(self, transaction_id, headers):
        return self._request(
            "GET", f"/survey/transactions/{transaction_id}", headers=headers
        )

    def list_transactions(self, headers, params=None):
        return self._request(
            "GET", "/survey/transactions", headers=headers, params=params
        )

    def list_dealer_transactions(self, dealer_id, headers, params=None):
        return self._request(
            "GET", f"/survey/dealers/{dealer_id}/transactions",
            headers=headers, params=params,
        )

    # --- Invitations ---
    def get_invitation(self, invitation_id, headers):
        return self._request(
            "GET", f"/survey/invitations/{invitation_id}", headers=headers
        )

    def list_invitations(self, headers, params=None):
        return self._request(
            "GET", "/survey/invitations", headers=headers, params=params
        )

    def send_invitation(self, invitation_id, headers):
        return self._request(
            "POST", f"/survey/invitations/{invitation_id}/send", {}, headers
        )

    def submit_response(self, invitation_id, payload, headers):
        return self._request(
            "POST", f"/survey/invitations/{invitation_id}/responses",
            payload, headers,
        )

    def opt_out_invitation(self, invitation_id, headers):
        return self._request(
            "POST", f"/survey/invitations/{invitation_id}/opt-out", {}, headers
        )

    def suppress_invitation(self, invitation_id, headers):
        return self._request(
            "POST", f"/survey/invitations/{invitation_id}/suppress", {}, headers
        )

    # --- Responses ---
    def get_response(self, response_id, headers):
        return self._request(
            "GET", f"/survey/responses/{response_id}", headers=headers
        )

    def list_responses(self, headers, params=None):
        return self._request(
            "GET", "/survey/responses", headers=headers, params=params
        )

    def list_invitation_responses(self, invitation_id, headers):
        return self._request(
            "GET", f"/survey/invitations/{invitation_id}/responses",
            headers=headers,
        )

    # --- Appeals ---
    def create_appeal(self, payload, headers):
        return self._request("POST", "/survey/appeals", payload, headers)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/survey/appeals/{appeal_id}", headers=headers)

    def list_appeals(self, headers, params=None):
        return self._request("GET", "/survey/appeals", headers=headers, params=params)

    def list_dealer_appeals(self, dealer_id, headers, params=None):
        return self._request(
            "GET", f"/survey/dealers/{dealer_id}/appeals",
            headers=headers, params=params,
        )

    def assign_appeal(self, appeal_id, headers):
        return self._request(
            "POST", f"/survey/appeals/{appeal_id}/assign", {}, headers
        )

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request(
            "POST", f"/survey/appeals/{appeal_id}/decide", payload, headers
        )

    # --- Manipulation flags ---
    def create_flag(self, payload, headers):
        return self._request("POST", "/survey/flags", payload, headers)

    def get_flag(self, flag_id, headers):
        return self._request("GET", f"/survey/flags/{flag_id}", headers=headers)

    def list_flags(self, headers, params=None):
        return self._request("GET", "/survey/flags", headers=headers, params=params)

    def list_dealer_flags(self, dealer_id, headers, params=None):
        return self._request(
            "GET", f"/survey/dealers/{dealer_id}/flags",
            headers=headers, params=params,
        )

    def resolve_flag(self, flag_id, payload, headers):
        return self._request(
            "POST", f"/survey/flags/{flag_id}/resolve", payload, headers
        )

    # --- Incentive statements ---
    def create_statement(self, payload, headers):
        return self._request("POST", "/survey/statements", payload, headers)

    def get_statement(self, statement_id, headers):
        return self._request(
            "GET", f"/survey/statements/{statement_id}", headers=headers
        )

    def list_statements(self, headers, params=None):
        return self._request(
            "GET", "/survey/statements", headers=headers, params=params
        )

    def list_dealer_statements(self, dealer_id, headers, params=None):
        return self._request(
            "GET", f"/survey/dealers/{dealer_id}/statements",
            headers=headers, params=params,
        )

    def pay_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/survey/statements/{statement_id}/pay", {}, headers
        )

    # --- Action plans ---
    def create_action_plan(self, payload, headers):
        return self._request("POST", "/survey/action-plans", payload, headers)

    def get_action_plan(self, plan_id, headers):
        return self._request(
            "GET", f"/survey/action-plans/{plan_id}", headers=headers
        )

    def list_action_plans(self, headers, params=None):
        return self._request(
            "GET", "/survey/action-plans", headers=headers, params=params
        )

    def list_dealer_action_plans(self, dealer_id, headers, params=None):
        return self._request(
            "GET", f"/survey/dealers/{dealer_id}/action-plans",
            headers=headers, params=params,
        )

    def submit_action_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/survey/action-plans/{plan_id}/submit", {}, headers
        )

    def review_action_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/survey/action-plans/{plan_id}/review", payload, headers
        )

    def revise_action_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/survey/action-plans/{plan_id}/revise", {}, headers
        )

    def start_action_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/survey/action-plans/{plan_id}/start", {}, headers
        )

    def complete_action_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/survey/action-plans/{plan_id}/complete", {}, headers
        )


api_client = ApiClient()
