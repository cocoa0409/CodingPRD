"""API client: one method per endpoint defined in the PRD (§4)."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock (PRD §2.5) --------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- markets --------------------------------------------------------
    def create_market(self, payload, headers):
        return self._request("POST", "/markets", payload, headers)

    def get_market(self, market_id, headers):
        return self._request("GET", f"/markets/{market_id}", headers=headers)

    def list_markets(self, headers, params=None):
        return self._request("GET", "/markets", headers=headers, params=params)

    def update_market(self, market_id, payload, headers):
        return self._request("PUT", f"/markets/{market_id}", payload, headers)

    def freeze_market(self, market_id, headers, payload=None):
        return self._request("POST", f"/markets/{market_id}/freeze", payload or {}, headers)

    def unfreeze_market(self, market_id, headers, payload=None):
        return self._request("POST", f"/markets/{market_id}/unfreeze", payload or {}, headers)

    def close_market(self, market_id, headers, payload=None):
        return self._request("POST", f"/markets/{market_id}/close", payload or {}, headers)

    def list_market_shortfalls(self, market_id, headers, params=None):
        return self._request(
            "GET", f"/markets/{market_id}/supply-shortfalls", headers=headers, params=params
        )

    # ---- drivers --------------------------------------------------------
    def create_driver(self, payload, headers):
        return self._request("POST", "/drivers", payload, headers)

    def get_driver(self, driver_id, headers):
        return self._request("GET", f"/drivers/{driver_id}", headers=headers)

    def list_drivers(self, headers, params=None):
        return self._request("GET", "/drivers", headers=headers, params=params)

    def record_rate_events(self, driver_id, payload, headers):
        return self._request("POST", f"/drivers/{driver_id}/rate-events", payload, headers)

    def deactivate_driver(self, driver_id, headers, payload=None):
        return self._request(
            "POST", f"/drivers/{driver_id}/deactivate", payload or {}, headers
        )

    def list_driver_enrollments(self, driver_id, headers, params=None):
        return self._request(
            "GET", f"/drivers/{driver_id}/enrollments", headers=headers, params=params
        )

    def list_driver_rides(self, driver_id, headers, params=None):
        return self._request(
            "GET", f"/drivers/{driver_id}/rides", headers=headers, params=params
        )

    def list_driver_settlements(self, driver_id, headers, params=None):
        return self._request(
            "GET", f"/drivers/{driver_id}/settlements", headers=headers, params=params
        )

    def list_driver_statements(self, driver_id, headers, params=None):
        return self._request(
            "GET", f"/drivers/{driver_id}/statements", headers=headers, params=params
        )

    # ---- incentive programs ---------------------------------------------
    def create_program(self, payload, headers):
        return self._request("POST", "/incentive-programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/incentive-programs/{program_id}", headers=headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/incentive-programs", headers=headers, params=params)

    def activate_program(self, program_id, headers, payload=None):
        return self._request(
            "POST", f"/incentive-programs/{program_id}/activate", payload or {}, headers
        )

    def pause_program(self, program_id, headers, payload=None):
        return self._request(
            "POST", f"/incentive-programs/{program_id}/pause", payload or {}, headers
        )

    def resume_program(self, program_id, headers, payload=None):
        return self._request(
            "POST", f"/incentive-programs/{program_id}/resume", payload or {}, headers
        )

    def retire_program(self, program_id, headers, payload=None):
        return self._request(
            "POST", f"/incentive-programs/{program_id}/retire", payload or {}, headers
        )

    def list_program_enrollments(self, program_id, headers, params=None):
        return self._request(
            "GET", f"/incentive-programs/{program_id}/enrollments", headers=headers, params=params
        )

    def list_program_forecasts(self, program_id, headers, params=None):
        return self._request(
            "GET", f"/incentive-programs/{program_id}/cost-forecasts", headers=headers, params=params
        )

    def create_forecast(self, program_id, payload, headers):
        return self._request(
            "POST", f"/incentive-programs/{program_id}/cost-forecasts", payload, headers
        )

    def approve_forecast(self, forecast_id, payload, headers):
        return self._request(
            "POST", f"/cost-forecasts/{forecast_id}/approve", payload, headers
        )

    def reject_forecast(self, forecast_id, headers, payload=None):
        return self._request(
            "POST", f"/cost-forecasts/{forecast_id}/reject", payload or {}, headers
        )

    # ---- enrollments -----------------------------------------------------
    def enroll_driver(self, program_id, payload, headers):
        return self._request(
            "POST", f"/incentive-programs/{program_id}/enrollments", payload, headers
        )

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def cancel_enrollment(self, enrollment_id, headers, payload=None):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/cancel", payload or {}, headers
        )

    # ---- rides ----------------------------------------------------------
    def create_ride(self, payload, headers):
        return self._request("POST", "/rides", payload, headers)

    def get_ride(self, ride_id, headers):
        return self._request("GET", f"/rides/{ride_id}", headers=headers)

    def list_rides(self, headers, params=None):
        return self._request("GET", "/rides", headers=headers, params=params)

    def accept_ride(self, ride_id, headers, payload=None):
        return self._request("POST", f"/rides/{ride_id}/accept", payload or {}, headers)

    def decline_ride(self, ride_id, headers, payload=None):
        return self._request("POST", f"/rides/{ride_id}/decline", payload or {}, headers)

    def complete_ride(self, ride_id, headers, payload=None):
        return self._request("POST", f"/rides/{ride_id}/complete", payload or {}, headers)

    def cancel_ride(self, ride_id, payload, headers):
        return self._request("POST", f"/rides/{ride_id}/cancel", payload, headers)

    def flag_ride_review(self, ride_id, headers, payload=None):
        return self._request("POST", f"/rides/{ride_id}/flag-review", payload or {}, headers)

    def clear_ride_review(self, ride_id, headers, payload=None):
        return self._request("POST", f"/rides/{ride_id}/clear-review", payload or {}, headers)

    def void_ride(self, ride_id, headers, payload=None):
        return self._request("POST", f"/rides/{ride_id}/void", payload or {}, headers)

    # ---- fraud flags -----------------------------------------------------
    def create_fraud_flag(self, payload, headers):
        return self._request("POST", "/fraud-flags", payload, headers)

    def get_fraud_flag(self, flag_id, headers):
        return self._request("GET", f"/fraud-flags/{flag_id}", headers=headers)

    def list_fraud_flags(self, headers, params=None):
        return self._request("GET", "/fraud-flags", headers=headers, params=params)

    def confirm_fraud_flag(self, flag_id, headers, payload=None):
        return self._request("POST", f"/fraud-flags/{flag_id}/confirm", payload or {}, headers)

    def dismiss_fraud_flag(self, flag_id, headers, payload=None):
        return self._request("POST", f"/fraud-flags/{flag_id}/dismiss", payload or {}, headers)

    # ---- settlements -----------------------------------------------------
    def compute_settlement(self, payload, headers):
        return self._request("POST", "/settlements/compute", payload, headers)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/settlements/{settlement_id}", headers=headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/settlements", headers=headers, params=params)

    def finalize_settlement(self, settlement_id, headers, payload=None):
        return self._request(
            "POST", f"/settlements/{settlement_id}/finalize", payload or {}, headers
        )

    def pay_settlement(self, settlement_id, headers, payload=None):
        return self._request("POST", f"/settlements/{settlement_id}/pay", payload or {}, headers)

    def reopen_settlement(self, settlement_id, headers, payload=None):
        return self._request(
            "POST", f"/settlements/{settlement_id}/reopen", payload or {}, headers
        )

    def void_settlement(self, settlement_id, headers, payload=None):
        return self._request(
            "POST", f"/settlements/{settlement_id}/void", payload or {}, headers
        )

    # ---- statements ------------------------------------------------------
    def compute_statement(self, payload, headers):
        return self._request("POST", "/statements/compute", payload, headers)

    def get_statement(self, statement_id, headers):
        return self._request("GET", f"/statements/{statement_id}", headers=headers)

    def list_statements(self, headers, params=None):
        return self._request("GET", "/statements", headers=headers, params=params)

    def publish_statement(self, statement_id, headers, payload=None):
        return self._request(
            "POST", f"/statements/{statement_id}/publish", payload or {}, headers
        )

    # ---- appeals ---------------------------------------------------------
    def create_appeal(self, payload, headers):
        return self._request("POST", "/appeals", payload, headers)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/appeals/{appeal_id}", headers=headers)

    def list_appeals(self, headers, params=None):
        return self._request("GET", "/appeals", headers=headers, params=params)

    def start_appeal_review(self, appeal_id, headers, payload=None):
        return self._request(
            "POST", f"/appeals/{appeal_id}/start-review", payload or {}, headers
        )

    def request_appeal_info(self, appeal_id, headers, payload=None):
        return self._request(
            "POST", f"/appeals/{appeal_id}/request-info", payload or {}, headers
        )

    def provide_appeal_info(self, appeal_id, headers, payload=None):
        return self._request(
            "POST", f"/appeals/{appeal_id}/provide-info", payload or {}, headers
        )

    def resolve_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/appeals/{appeal_id}/resolve", payload, headers)

    def escalate_appeal(self, appeal_id, headers, payload=None):
        return self._request(
            "POST", f"/appeals/{appeal_id}/escalate", payload or {}, headers
        )

    def withdraw_appeal(self, appeal_id, headers, payload=None):
        return self._request(
            "POST", f"/appeals/{appeal_id}/withdraw", payload or {}, headers
        )

    # ---- supply shortfalls ------------------------------------------------
    def create_supply_shortfall(self, payload, headers):
        return self._request("POST", "/supply-shortfalls", payload, headers)

    def get_supply_shortfall(self, shortfall_id, headers):
        return self._request("GET", f"/supply-shortfalls/{shortfall_id}", headers=headers)

    def address_supply_shortfall(self, shortfall_id, headers, payload=None):
        return self._request(
            "POST", f"/supply-shortfalls/{shortfall_id}/address", payload or {}, headers
        )


api_client = ApiClient()
