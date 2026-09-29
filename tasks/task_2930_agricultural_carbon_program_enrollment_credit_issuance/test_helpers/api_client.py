"""One method per endpoint of the agricultural carbon programme API.

Every method returns the raw HTTP response so a test may assert on the status
code as well as the body. Bodies are validated through the helpers in
``prd_bench_local_runner.testing`` which unwrap the ``data`` envelope, so tests
never index ``["data"]`` themselves.
"""

from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient

from .types import Headers, Json


class ApiClient(GenericApiClient):
    """Thin, total wrapper over the endpoint table."""

    # ---------------------------------------------------------------- clock
    def set_clock(self, payload: Json, headers: Optional[Headers] = None):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --------------------------------------------------------------- growers
    def create_grower(self, payload: Json, headers: Optional[Headers] = None):
        return self._request("POST", "/growers", payload, headers)

    def list_growers(self, params: Optional[Json] = None, headers: Optional[Headers] = None):
        return self._request("GET", "/growers", params, headers)

    def get_grower(self, grower_id: str, headers: Optional[Headers] = None):
        return self._request("GET", f"/growers/{grower_id}", None, headers)

    def get_grower_ledger_summary(self, grower_id: str, headers: Optional[Headers] = None):
        return self._request("GET", f"/growers/{grower_id}/ledger-summary", None, headers)

    def suspend_grower(self, grower_id: str, payload: Optional[Json] = None,
                       headers: Optional[Headers] = None):
        return self._request("POST", f"/growers/{grower_id}/suspend", payload, headers)

    def reinstate_grower(self, grower_id: str, payload: Optional[Json] = None,
                         headers: Optional[Headers] = None):
        return self._request("POST", f"/growers/{grower_id}/reinstate", payload, headers)

    # ---------------------------------------------------------------- fields
    def create_field(self, grower_id: str, payload: Json, headers: Optional[Headers] = None):
        return self._request("POST", f"/growers/{grower_id}/fields", payload, headers)

    def list_fields(self, params: Optional[Json] = None, headers: Optional[Headers] = None):
        return self._request("GET", "/fields", params, headers)

    def get_field(self, field_id: str, headers: Optional[Headers] = None):
        return self._request("GET", f"/fields/{field_id}", None, headers)

    def map_confirm_field(self, field_id: str, payload: Optional[Json] = None,
                          headers: Optional[Headers] = None):
        return self._request("POST", f"/fields/{field_id}/map-confirm", payload, headers)

    # ------------------------------------------------------ practice history
    def file_practice_history(self, field_id: str, payload: Json,
                              headers: Optional[Headers] = None):
        return self._request("POST", f"/fields/{field_id}/practice-history", payload, headers)

    def list_practice_history(self, params: Optional[Json] = None,
                              headers: Optional[Headers] = None):
        return self._request("GET", "/practice-history", params, headers)

    def get_practice_history(self, practice_history_id: str, headers: Optional[Headers] = None):
        return self._request("GET", f"/practice-history/{practice_history_id}", None, headers)

    # ---------------------------------------------------- practice standards
    def create_practice_standard(self, payload: Json, headers: Optional[Headers] = None):
        return self._request("POST", "/practice-standards", payload, headers)

    def list_practice_standards(self, params: Optional[Json] = None,
                                headers: Optional[Headers] = None):
        return self._request("GET", "/practice-standards", params, headers)

    def get_practice_standard(self, practice_standard_id: str, headers: Optional[Headers] = None):
        return self._request("GET", f"/practice-standards/{practice_standard_id}", None, headers)

    def retire_practice_standard(self, practice_standard_id: str, payload: Optional[Json] = None,
                                 headers: Optional[Headers] = None):
        return self._request(
            "POST", f"/practice-standards/{practice_standard_id}/retire", payload, headers
        )

    def revise_practice_standard(self, practice_standard_id: str, payload: Optional[Json] = None,
                                 headers: Optional[Headers] = None):
        return self._request(
            "POST", f"/practice-standards/{practice_standard_id}/revise", payload, headers
        )

    # ----------------------------------------------------------- enrollments
    def create_enrollment(self, payload: Json, headers: Optional[Headers] = None):
        return self._request("POST", "/enrollments", payload, headers)

    def list_enrollments(self, params: Optional[Json] = None, headers: Optional[Headers] = None):
        return self._request("GET", "/enrollments", params, headers)

    def get_enrollment(self, enrollment_id: str, headers: Optional[Headers] = None):
        return self._request("GET", f"/enrollments/{enrollment_id}", None, headers)

    def submit_enrollment(self, enrollment_id: str, payload: Optional[Json] = None,
                          headers: Optional[Headers] = None):
        return self._request("POST", f"/enrollments/{enrollment_id}/submit", payload, headers)

    def request_info_enrollment(self, enrollment_id: str, payload: Json,
                                headers: Optional[Headers] = None):
        return self._request("POST", f"/enrollments/{enrollment_id}/request-info", payload, headers)

    def resubmit_enrollment(self, enrollment_id: str, payload: Optional[Json] = None,
                            headers: Optional[Headers] = None):
        return self._request("POST", f"/enrollments/{enrollment_id}/resubmit", payload, headers)

    def screen_enrollment(self, enrollment_id: str, payload: Json,
                          headers: Optional[Headers] = None):
        return self._request("POST", f"/enrollments/{enrollment_id}/screen", payload, headers)

    def request_exit(self, enrollment_id: str, payload: Json, headers: Optional[Headers] = None):
        return self._request("POST", f"/enrollments/{enrollment_id}/request-exit", payload, headers)

    def decide_exit(self, enrollment_id: str, payload: Json, headers: Optional[Headers] = None):
        return self._request("POST", f"/enrollments/{enrollment_id}/decide-exit", payload, headers)

    def accrue_payment(self, enrollment_id: str, payload: Json,
                       headers: Optional[Headers] = None):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/accrue-payment", payload, headers
        )

    # ------------------------------------------------------------- baselines
    def propose_baseline(self, enrollment_id: str, payload: Json,
                         headers: Optional[Headers] = None):
        return self._request("POST", f"/enrollments/{enrollment_id}/baselines", payload, headers)

    def list_baselines(self, params: Optional[Json] = None, headers: Optional[Headers] = None):
        return self._request("GET", "/baselines", params, headers)

    def get_baseline(self, baseline_id: str, headers: Optional[Headers] = None):
        return self._request("GET", f"/baselines/{baseline_id}", None, headers)

    def approve_baseline(self, baseline_id: str, payload: Optional[Json] = None,
                         headers: Optional[Headers] = None):
        return self._request("POST", f"/baselines/{baseline_id}/approve", payload, headers)

    def reject_baseline(self, baseline_id: str, payload: Json, headers: Optional[Headers] = None):
        return self._request("POST", f"/baselines/{baseline_id}/reject", payload, headers)

    # ----------------------------------------------------------- data packets
    def file_data_packet(self, enrollment_id: str, payload: Json,
                         headers: Optional[Headers] = None):
        return self._request("POST", f"/enrollments/{enrollment_id}/data-packets", payload, headers)

    def list_data_packets(self, params: Optional[Json] = None, headers: Optional[Headers] = None):
        return self._request("GET", "/data-packets", params, headers)

    def get_data_packet(self, data_packet_id: str, headers: Optional[Headers] = None):
        return self._request("GET", f"/data-packets/{data_packet_id}", None, headers)

    def qc_data_packet(self, data_packet_id: str, payload: Optional[Json] = None,
                       headers: Optional[Headers] = None):
        return self._request("POST", f"/data-packets/{data_packet_id}/qc", payload, headers)

    def correct_data_packet(self, data_packet_id: str, payload: Json,
                            headers: Optional[Headers] = None):
        return self._request("POST", f"/data-packets/{data_packet_id}/correct", payload, headers)

    def reject_data_packet(self, data_packet_id: str, payload: Optional[Json] = None,
                           headers: Optional[Headers] = None):
        return self._request("POST", f"/data-packets/{data_packet_id}/reject", payload, headers)

    # ---------------------------------------------------- quantification runs
    def create_quantification_run(self, payload: Json, headers: Optional[Headers] = None):
        return self._request("POST", "/quantification-runs", payload, headers)

    def list_quantification_runs(self, params: Optional[Json] = None,
                                 headers: Optional[Headers] = None):
        return self._request("GET", "/quantification-runs", params, headers)

    def get_quantification_run(self, quantification_run_id: str,
                               headers: Optional[Headers] = None):
        return self._request("GET", f"/quantification-runs/{quantification_run_id}", None, headers)

    def submit_quantification_run(self, quantification_run_id: str, payload: Optional[Json] = None,
                                  headers: Optional[Headers] = None):
        return self._request(
            "POST", f"/quantification-runs/{quantification_run_id}/submit", payload, headers
        )

    def revise_quantification_run(self, quantification_run_id: str, payload: Optional[Json] = None,
                                  headers: Optional[Headers] = None):
        return self._request(
            "POST", f"/quantification-runs/{quantification_run_id}/revise", payload, headers
        )

    def issue_credits(self, quantification_run_id: str, payload: Optional[Json] = None,
                      headers: Optional[Headers] = None):
        return self._request(
            "POST", f"/quantification-runs/{quantification_run_id}/issue", payload, headers
        )

    # ------------------------------------------------------ verification body
    def create_verification_body(self, payload: Json, headers: Optional[Headers] = None):
        return self._request("POST", "/verification-bodies", payload, headers)

    def list_verification_bodies(self, params: Optional[Json] = None,
                                 headers: Optional[Headers] = None):
        return self._request("GET", "/verification-bodies", params, headers)

    def get_verification_body(self, verification_body_id: str,
                              headers: Optional[Headers] = None):
        return self._request("GET", f"/verification-bodies/{verification_body_id}", None, headers)

    def suspend_verification_body(self, verification_body_id: str, payload: Optional[Json] = None,
                                  headers: Optional[Headers] = None):
        return self._request(
            "POST", f"/verification-bodies/{verification_body_id}/suspend", payload, headers
        )

    def reinstate_verification_body(self, verification_body_id: str, payload: Optional[Json] = None,
                                    headers: Optional[Headers] = None):
        return self._request(
            "POST", f"/verification-bodies/{verification_body_id}/reinstate", payload, headers
        )

    # --------------------------------------------------------- verifications
    def create_verification(self, payload: Json, headers: Optional[Headers] = None):
        return self._request("POST", "/verifications", payload, headers)

    def list_verifications(self, params: Optional[Json] = None, headers: Optional[Headers] = None):
        return self._request("GET", "/verifications", params, headers)

    def get_verification(self, verification_id: str, headers: Optional[Headers] = None):
        return self._request("GET", f"/verifications/{verification_id}", None, headers)

    def start_visit(self, verification_id: str, payload: Optional[Json] = None,
                    headers: Optional[Headers] = None):
        return self._request("POST", f"/verifications/{verification_id}/start-visit", payload,
                             headers)

    def opine_verification(self, verification_id: str, payload: Json,
                           headers: Optional[Headers] = None):
        return self._request("POST", f"/verifications/{verification_id}/opine", payload, headers)

    def resample_verification(self, verification_id: str, payload: Optional[Json] = None,
                              headers: Optional[Headers] = None):
        return self._request("POST", f"/verifications/{verification_id}/resample", payload, headers)

    # --------------------------------------------------------- credit batches
    def list_credit_batches(self, params: Optional[Json] = None,
                            headers: Optional[Headers] = None):
        return self._request("GET", "/credit-batches", params, headers)

    def get_credit_batch(self, credit_batch_id: str, headers: Optional[Headers] = None):
        return self._request("GET", f"/credit-batches/{credit_batch_id}", None, headers)

    def list_batch_on_registry(self, credit_batch_id: str, payload: Json,
                               headers: Optional[Headers] = None):
        return self._request("POST", f"/credit-batches/{credit_batch_id}/list", payload, headers)

    def retire_batch(self, credit_batch_id: str, payload: Json,
                     headers: Optional[Headers] = None):
        return self._request("POST", f"/credit-batches/{credit_batch_id}/retire", payload, headers)

    def cancel_batch(self, credit_batch_id: str, payload: Json,
                     headers: Optional[Headers] = None):
        return self._request("POST", f"/credit-batches/{credit_batch_id}/cancel", payload, headers)

    # -------------------------------------------------------- buffer accounts
    def list_buffer_accounts(self, params: Optional[Json] = None,
                             headers: Optional[Headers] = None):
        return self._request("GET", "/buffer-accounts", params, headers)

    def get_buffer_account(self, buffer_account_id: str, headers: Optional[Headers] = None):
        return self._request("GET", f"/buffer-accounts/{buffer_account_id}", None, headers)

    # --------------------------------------------------------- reversal events
    def create_reversal_event(self, payload: Json, headers: Optional[Headers] = None):
        return self._request("POST", "/reversal-events", payload, headers)

    def list_reversal_events(self, params: Optional[Json] = None,
                             headers: Optional[Headers] = None):
        return self._request("GET", "/reversal-events", params, headers)

    def get_reversal_event(self, reversal_event_id: str, headers: Optional[Headers] = None):
        return self._request("GET", f"/reversal-events/{reversal_event_id}", None, headers)

    def assess_reversal(self, reversal_event_id: str, payload: Optional[Json] = None,
                        headers: Optional[Headers] = None):
        return self._request("POST", f"/reversal-events/{reversal_event_id}/assess", payload,
                             headers)

    def resolve_reversal(self, reversal_event_id: str, payload: Json,
                         headers: Optional[Headers] = None):
        return self._request("POST", f"/reversal-events/{reversal_event_id}/resolve", payload,
                             headers)

    # --------------------------------------------------------- grower payments
    def list_grower_payments(self, params: Optional[Json] = None,
                             headers: Optional[Headers] = None):
        return self._request("GET", "/grower-payments", params, headers)

    def get_grower_payment(self, grower_payment_id: str, headers: Optional[Headers] = None):
        return self._request("GET", f"/grower-payments/{grower_payment_id}", None, headers)

    def pay_grower_payment(self, grower_payment_id: str, payload: Optional[Json] = None,
                           headers: Optional[Headers] = None):
        return self._request("POST", f"/grower-payments/{grower_payment_id}/pay", payload, headers)
