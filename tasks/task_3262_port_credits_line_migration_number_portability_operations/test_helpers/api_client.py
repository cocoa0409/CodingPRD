"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/portability"


class ApiClient(GenericApiClient):
    # --- logical clock --------------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", payload, headers
        )

    # --- system config --------------------------------------------------------
    def get_system_config(self, headers):
        return self._request("GET", f"{PREFIX}/system-config", headers=headers)

    def run_ops(self, payload, headers):
        return self._request("POST", f"{PREFIX}/system-config/ops-run", payload, headers)

    # --- rejection code catalog ----------------------------------------------
    def create_rejection_code(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/rejection-code-catalog", payload, headers
        )

    # --- accounts -------------------------------------------------------------
    def create_account(self, payload, headers):
        return self._request("POST", f"{PREFIX}/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"{PREFIX}/accounts/{account_id}", headers=headers)

    # --- subscriber lines -----------------------------------------------------
    def create_subscriber_line(self, payload, headers):
        return self._request("POST", f"{PREFIX}/subscriber-lines", payload, headers)

    def get_subscriber_line(self, line_id, headers):
        return self._request(
            "GET", f"{PREFIX}/subscriber-lines/{line_id}", headers=headers
        )

    def list_account_subscriber_lines(self, account_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/accounts/{account_id}/subscriber-lines",
            headers=headers,
            params=params,
        )

    def activate_subscriber_line(self, line_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/subscriber-lines/{line_id}/activate", payload, headers
        )

    def cancel_subscriber_line(self, line_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/subscriber-lines/{line_id}/cancel", payload, headers
        )

    # --- port requests --------------------------------------------------------
    def create_port_request(self, payload, headers):
        return self._request("POST", f"{PREFIX}/port-requests", payload, headers)

    def get_port_request(self, request_id, headers):
        return self._request(
            "GET", f"{PREFIX}/port-requests/{request_id}", headers=headers
        )

    def list_line_port_requests(self, line_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/subscriber-lines/{line_id}/port-requests",
            headers=headers,
            params=params,
        )

    def submit_port_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/port-requests/{request_id}/submit", payload, headers
        )

    def record_port_rejection(self, request_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/port-requests/{request_id}/rejections", payload, headers
        )

    def resubmit_port_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/port-requests/{request_id}/resubmit", payload, headers
        )

    def accept_port_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/port-requests/{request_id}/accept", payload, headers
        )

    def cancel_port_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/port-requests/{request_id}/cancel", payload, headers
        )

    # --- migration requests ---------------------------------------------------
    def create_migration_request(self, payload, headers):
        return self._request("POST", f"{PREFIX}/migration-requests", payload, headers)

    def get_migration_request(self, migration_id, headers):
        return self._request(
            "GET", f"{PREFIX}/migration-requests/{migration_id}", headers=headers
        )

    def list_line_migration_requests(self, line_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/subscriber-lines/{line_id}/migration-requests",
            headers=headers,
            params=params,
        )

    def check_migration_eligibility(self, migration_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/migration-requests/{migration_id}/check-eligibility",
            payload,
            headers,
        )

    # --- device installment plans --------------------------------------------
    def create_device_plan(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/device-installment-plans", payload, headers
        )

    def get_device_plan(self, plan_id, headers):
        return self._request(
            "GET", f"{PREFIX}/device-installment-plans/{plan_id}", headers=headers
        )

    def list_line_device_plans(self, line_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/subscriber-lines/{line_id}/device-installment-plans",
            headers=headers,
            params=params,
        )

    # --- trade-in assessments -------------------------------------------------
    def create_trade_in_assessment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/trade-in-assessments", payload, headers)

    def list_trade_in_assessments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/trade-in-assessments", headers=headers, params=params
        )

    def list_plan_trade_in_assessments(self, plan_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/device-installment-plans/{plan_id}/trade-in-assessments",
            headers=headers,
            params=params,
        )

    def grade_trade_in_assessment(self, assessment_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/trade-in-assessments/{assessment_id}/grade",
            payload,
            headers,
        )

    # --- number reservations --------------------------------------------------
    def create_number_reservation(self, payload, headers):
        return self._request("POST", f"{PREFIX}/number-reservations", payload, headers)

    def list_account_number_reservations(self, account_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/accounts/{account_id}/number-reservations",
            headers=headers,
            params=params,
        )

    def commit_number_reservation(self, reservation_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/number-reservations/{reservation_id}/commit",
            payload,
            headers,
        )

    # --- line addition requests ----------------------------------------------
    def create_line_addition_request(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/line-addition-requests", payload, headers
        )

    def list_account_line_addition_requests(self, account_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/accounts/{account_id}/line-addition-requests",
            headers=headers,
            params=params,
        )

    def review_line_addition_request(self, request_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/line-addition-requests/{request_id}/review",
            payload,
            headers,
        )

    # --- port protection cases ------------------------------------------------
    def create_port_protection_case(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/port-protection-cases", payload, headers
        )

    def list_port_protection_cases(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/port-protection-cases", headers=headers, params=params
        )

    def resolve_port_protection_case(self, case_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/port-protection-cases/{case_id}/resolve",
            payload,
            headers,
        )

    # --- promo credit schedules ----------------------------------------------
    def create_promo_schedule(self, payload, headers):
        return self._request("POST", f"{PREFIX}/promo-credit-schedules", payload, headers)

    def get_promo_schedule(self, schedule_id, headers):
        return self._request(
            "GET", f"{PREFIX}/promo-credit-schedules/{schedule_id}", headers=headers
        )

    def activate_promo_schedule(self, schedule_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/promo-credit-schedules/{schedule_id}/activate",
            payload,
            headers,
        )

    def claw_back_promo_schedule(self, schedule_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/promo-credit-schedules/{schedule_id}/claw-back",
            payload,
            headers,
        )


api_client = ApiClient()