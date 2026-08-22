"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------------
    # Plans
    # ------------------------------------------------------------------
    def create_plan(self, payload, headers):
        return self._request("POST", "/plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/plans/{plan_id}", headers=headers)

    def close_year(self, plan_id, headers):
        return self._request("POST", f"/plans/{plan_id}/close-year", {}, headers)

    def rollover_plan(self, plan_id, headers):
        return self._request("POST", f"/plans/{plan_id}/rollover", {}, headers)

    def freeze_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/plans/{plan_id}/freeze", payload, headers)

    def deposit_repurchase_funding(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/plans/{plan_id}/repurchase-funding", payload, headers
        )

    def run_repurchase_sweep(self, plan_id, headers):
        return self._request("POST", f"/plans/{plan_id}/repurchase-sweeps", {}, headers)

    def get_repurchase_forecast(self, plan_id, headers, params=None):
        return self._request(
            "GET", f"/plans/{plan_id}/repurchase-forecast", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Participants
    # ------------------------------------------------------------------
    def create_participant(self, payload, headers):
        return self._request("POST", "/participants", payload, headers)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/participants/{participant_id}", headers=headers)

    def list_participants(self, headers, params=None):
        return self._request("GET", "/participants", headers=headers, params=params)

    def update_participant(self, participant_id, payload, headers):
        return self._request(
            "PATCH", f"/participants/{participant_id}", payload, headers
        )

    def terminate_participant(self, participant_id, payload, headers):
        return self._request(
            "POST", f"/participants/{participant_id}/terminate", payload, headers
        )

    # ------------------------------------------------------------------
    # Valuations
    # ------------------------------------------------------------------
    def create_valuation(self, payload, headers):
        return self._request("POST", "/valuations", payload, headers)

    def get_valuation(self, valuation_id, headers):
        return self._request("GET", f"/valuations/{valuation_id}", headers=headers)

    def list_valuations(self, headers, params=None):
        return self._request("GET", "/valuations", headers=headers, params=params)

    def challenge_valuation(self, valuation_id, payload, headers):
        return self._request(
            "POST", f"/valuations/{valuation_id}/challenge", payload, headers
        )

    def resubmit_valuation(self, valuation_id, payload, headers):
        return self._request(
            "POST", f"/valuations/{valuation_id}/resubmit", payload, headers
        )

    def approve_valuation(self, valuation_id, headers):
        return self._request("POST", f"/valuations/{valuation_id}/approve", {}, headers)

    def reject_valuation(self, valuation_id, payload, headers):
        return self._request(
            "POST", f"/valuations/{valuation_id}/reject", payload, headers
        )

    # ------------------------------------------------------------------
    # Leveraged loans and servicing
    # ------------------------------------------------------------------
    def create_loan(self, payload, headers):
        return self._request("POST", "/esop-loans", payload, headers)

    def get_loan(self, loan_id, headers):
        return self._request("GET", f"/esop-loans/{loan_id}", headers=headers)

    def list_loans(self, headers, params=None):
        return self._request("GET", "/esop-loans", headers=headers, params=params)

    def create_loan_payment(self, payload, headers):
        return self._request("POST", "/loan-payments", payload, headers)

    def get_loan_payment(self, payment_id, headers):
        return self._request("GET", f"/loan-payments/{payment_id}", headers=headers)

    def list_loan_payments(self, headers, params=None):
        return self._request("GET", "/loan-payments", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Allocation runs and their cascade rows
    # ------------------------------------------------------------------
    def create_allocation_run(self, payload, headers):
        return self._request("POST", "/allocation-runs", payload, headers)

    def get_allocation_run(self, run_id, headers):
        return self._request("GET", f"/allocation-runs/{run_id}", headers=headers)

    def list_allocation_runs(self, headers, params=None):
        return self._request("GET", "/allocation-runs", headers=headers, params=params)

    def finalize_allocation_run(self, run_id, headers):
        return self._request("POST", f"/allocation-runs/{run_id}/finalize", {}, headers)

    def void_allocation_run(self, run_id, payload, headers):
        return self._request(
            "POST", f"/allocation-runs/{run_id}/void", payload, headers
        )

    def get_share_allocation(self, allocation_id, headers):
        return self._request(
            "GET", f"/share-allocations/{allocation_id}", headers=headers
        )

    def list_share_allocations(self, headers, params=None):
        return self._request("GET", "/share-allocations", headers=headers, params=params)

    def get_forfeiture_event(self, forfeiture_id, headers):
        return self._request(
            "GET", f"/forfeiture-events/{forfeiture_id}", headers=headers
        )

    def list_forfeiture_events(self, headers, params=None):
        return self._request("GET", "/forfeiture-events", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Distribution elections and installments
    # ------------------------------------------------------------------
    def create_distribution_election(self, payload, headers):
        return self._request("POST", "/distribution-elections", payload, headers)

    def get_distribution_election(self, election_id, headers):
        return self._request(
            "GET", f"/distribution-elections/{election_id}", headers=headers
        )

    def list_distribution_elections(self, headers, params=None):
        return self._request(
            "GET", "/distribution-elections", headers=headers, params=params
        )

    def commence_distribution_election(self, election_id, headers):
        return self._request(
            "POST", f"/distribution-elections/{election_id}/commence", {}, headers
        )

    def get_installment_payment(self, installment_id, headers):
        return self._request(
            "GET", f"/installment-payments/{installment_id}", headers=headers
        )

    def list_installment_payments(self, headers, params=None):
        return self._request(
            "GET", "/installment-payments", headers=headers, params=params
        )

    def pay_installment_payment(self, installment_id, headers):
        return self._request(
            "POST", f"/installment-payments/{installment_id}/pay", {}, headers
        )

    # ------------------------------------------------------------------
    # Put option exercises
    # ------------------------------------------------------------------
    def create_put_option_exercise(self, payload, headers):
        return self._request("POST", "/put-option-exercises", payload, headers)

    def get_put_option_exercise(self, exercise_id, headers):
        return self._request(
            "GET", f"/put-option-exercises/{exercise_id}", headers=headers
        )

    def list_put_option_exercises(self, headers, params=None):
        return self._request(
            "GET", "/put-option-exercises", headers=headers, params=params
        )

    def fund_put_option_exercise(self, exercise_id, headers):
        return self._request(
            "POST", f"/put-option-exercises/{exercise_id}/fund", {}, headers
        )

    def cancel_put_option_exercise(self, exercise_id, payload, headers):
        return self._request(
            "POST", f"/put-option-exercises/{exercise_id}/cancel", payload, headers
        )

    def settle_put_option_exercise(self, exercise_id, headers):
        return self._request(
            "POST", f"/put-option-exercises/{exercise_id}/settle", {}, headers
        )

    # ------------------------------------------------------------------
    # Participant statements
    # ------------------------------------------------------------------
    def get_participant_statement(self, statement_id, headers):
        return self._request(
            "GET", f"/participant-statements/{statement_id}", headers=headers
        )

    def list_participant_statements(self, headers, params=None):
        return self._request(
            "GET", "/participant-statements", headers=headers, params=params
        )

    def deliver_participant_statement(self, statement_id, payload, headers):
        return self._request(
            "POST", f"/participant-statements/{statement_id}/deliver", payload, headers
        )


api_client = ApiClient()
