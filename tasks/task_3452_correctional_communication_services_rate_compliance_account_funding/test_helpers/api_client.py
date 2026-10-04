"""API client: one method per endpoint defined in the PRD (§4 table).

The base URL comes from the runner-provided API_BASE_URL environment
variable via GenericApiClient — no port is hardcoded here.

The logical-clock setter is mounted OUTSIDE the /comm-services prefix
(PRD §2.4); every other path carries the prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_ENDPOINT_PATH

_P = API_PREFIX  # "/comm-services"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (PlatformAdmin only; mounted at platform level)
    # ------------------------------------------------------------------
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", CLOCK_ENDPOINT_PATH, {"current_utc": current_utc}, headers
        )

    # ------------------------------------------------------------------
    # Facility
    # ------------------------------------------------------------------
    def create_facility(self, payload, headers):
        return self._request("POST", f"{_P}/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"{_P}/facilities/{facility_id}", headers=headers)

    def list_facilities(self, headers, params=None):
        return self._request("GET", f"{_P}/facilities", headers=headers, params=params)

    def activate_facility(self, facility_id, headers):
        return self._request(
            "POST", f"{_P}/facilities/{facility_id}/activate", {}, headers
        )

    def suspend_facility(self, facility_id, headers):
        return self._request(
            "POST", f"{_P}/facilities/{facility_id}/suspend", {}, headers
        )

    def run_dormancy_scan(self, facility_id, headers):
        return self._request(
            "POST", f"{_P}/facilities/{facility_id}/run-dormancy-scan", {}, headers
        )

    def get_video_availability(self, facility_id, date, headers):
        return self._request(
            "GET",
            f"{_P}/facilities/{facility_id}/video-availability",
            headers=headers,
            params={"date": date},
        )

    def get_regulatory_summary(self, facility_id, period_start, period_end, headers):
        return self._request(
            "GET",
            f"{_P}/facilities/{facility_id}/regulatory-summary",
            headers=headers,
            params={"period_start": period_start, "period_end": period_end},
        )

    # ------------------------------------------------------------------
    # RegulatoryCap
    # ------------------------------------------------------------------
    def create_regulatory_cap(self, payload, headers):
        return self._request("POST", f"{_P}/regulatory-caps", payload, headers)

    def get_regulatory_cap(self, cap_id, headers):
        return self._request(
            "GET", f"{_P}/regulatory-caps/{cap_id}", headers=headers
        )

    def list_regulatory_caps(self, headers, params=None):
        return self._request(
            "GET", f"{_P}/regulatory-caps", headers=headers, params=params
        )

    def amend_regulatory_cap(self, cap_id, payload, headers):
        return self._request("PUT", f"{_P}/regulatory-caps/{cap_id}", payload, headers)

    # ------------------------------------------------------------------
    # FacilityContract
    # ------------------------------------------------------------------
    def create_contract(self, payload, headers):
        return self._request("POST", f"{_P}/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"{_P}/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", f"{_P}/contracts", headers=headers, params=params)

    def activate_contract(self, contract_id, headers):
        return self._request(
            "POST", f"{_P}/contracts/{contract_id}/activate", {}, headers
        )

    def terminate_contract(self, contract_id, headers):
        return self._request(
            "POST", f"{_P}/contracts/{contract_id}/terminate", {}, headers
        )

    # ------------------------------------------------------------------
    # RateSchedule
    # ------------------------------------------------------------------
    def create_rate_schedule(self, contract_id, payload, headers):
        return self._request(
            "POST", f"{_P}/contracts/{contract_id}/rate-schedules", payload, headers
        )

    def get_rate_schedule(self, schedule_id, headers):
        return self._request(
            "GET", f"{_P}/rate-schedules/{schedule_id}", headers=headers
        )

    def list_rate_schedules(self, headers, params=None):
        return self._request(
            "GET", f"{_P}/rate-schedules", headers=headers, params=params
        )

    def activate_rate_schedule(self, schedule_id, expected_contract_version, headers):
        return self._request(
            "POST",
            f"{_P}/rate-schedules/{schedule_id}/activate",
            {"expected_contract_version": expected_contract_version},
            headers,
        )

    # ------------------------------------------------------------------
    # Inmate
    # ------------------------------------------------------------------
    def create_inmate(self, payload, headers):
        return self._request("POST", f"{_P}/inmates", payload, headers)

    def get_inmate(self, inmate_id, headers):
        return self._request("GET", f"{_P}/inmates/{inmate_id}", headers=headers)

    def list_inmates(self, headers, params=None):
        return self._request("GET", f"{_P}/inmates", headers=headers, params=params)

    def release_inmate(self, inmate_id, headers):
        return self._request("POST", f"{_P}/inmates/{inmate_id}/release", {}, headers)

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------
    def create_account(self, payload, headers):
        return self._request("POST", f"{_P}/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"{_P}/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", f"{_P}/accounts", headers=headers, params=params)

    def create_deposit(self, account_id, amount_cents, headers):
        return self._request(
            "POST",
            f"{_P}/accounts/{account_id}/deposits",
            {"amount_cents": amount_cents},
            headers,
        )

    def suspend_account(self, account_id, headers):
        return self._request(
            "POST", f"{_P}/accounts/{account_id}/suspend", {}, headers
        )

    def resume_account(self, account_id, headers):
        return self._request("POST", f"{_P}/accounts/{account_id}/resume", {}, headers)

    def close_account(self, account_id, headers):
        return self._request("POST", f"{_P}/accounts/{account_id}/close", {}, headers)

    def send_escheat_notice(self, account_id, headers):
        return self._request(
            "POST", f"{_P}/accounts/{account_id}/send-escheat-notice", {}, headers
        )

    def remit_escheat(self, account_id, headers):
        return self._request(
            "POST", f"{_P}/accounts/{account_id}/remit-escheat", {}, headers
        )

    def claim_unclaimed(self, account_id, headers):
        return self._request(
            "POST", f"{_P}/accounts/{account_id}/claim-unclaimed", {}, headers
        )

    def get_account_ledger(self, account_id, headers, params=None):
        return self._request(
            "GET", f"{_P}/accounts/{account_id}/ledger", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # RecipientNumber
    # ------------------------------------------------------------------
    def create_recipient_number(self, payload, headers):
        return self._request("POST", f"{_P}/recipient-numbers", payload, headers)

    def get_recipient_number(self, recipient_number_id, headers):
        return self._request(
            "GET", f"{_P}/recipient-numbers/{recipient_number_id}", headers=headers
        )

    def list_recipient_numbers(self, headers, params=None):
        return self._request(
            "GET", f"{_P}/recipient-numbers", headers=headers, params=params
        )

    def verify_recipient_number(
        self, recipient_number_id, verification_code, consent_to_recording, headers
    ):
        return self._request(
            "POST",
            f"{_P}/recipient-numbers/{recipient_number_id}/verify",
            {
                "verification_code": verification_code,
                "consent_to_recording": consent_to_recording,
            },
            headers,
        )

    def request_block(self, recipient_number_id, headers, reason=None):
        payload = {} if reason is None else {"reason": reason}
        return self._request(
            "POST",
            f"{_P}/recipient-numbers/{recipient_number_id}/request-block",
            payload,
            headers,
        )

    def privilege_decision(self, recipient_number_id, decision, headers, note=None):
        payload = {"decision": decision}
        if note is not None:
            payload["note"] = note
        return self._request(
            "POST",
            f"{_P}/recipient-numbers/{recipient_number_id}/privilege-decision",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # CallRecord
    # ------------------------------------------------------------------
    def create_call(self, payload, headers):
        return self._request("POST", f"{_P}/calls", payload, headers)

    def get_call(self, call_id, headers):
        return self._request("GET", f"{_P}/calls/{call_id}", headers=headers)

    def list_calls(self, headers, params=None):
        return self._request("GET", f"{_P}/calls", headers=headers, params=params)

    def end_call(self, call_id, duration_seconds, headers):
        return self._request(
            "POST",
            f"{_P}/calls/{call_id}/end",
            {"duration_seconds": duration_seconds},
            headers,
        )

    # ------------------------------------------------------------------
    # VideoSession
    # ------------------------------------------------------------------
    def create_video_session(self, payload, headers):
        return self._request("POST", f"{_P}/video-sessions", payload, headers)

    def get_video_session(self, session_id, headers):
        return self._request(
            "GET", f"{_P}/video-sessions/{session_id}", headers=headers
        )

    def list_video_sessions(self, headers, params=None):
        return self._request(
            "GET", f"{_P}/video-sessions", headers=headers, params=params
        )

    def confirm_video_session(self, session_id, headers):
        return self._request(
            "POST", f"{_P}/video-sessions/{session_id}/confirm", {}, headers
        )

    def cancel_video_session(self, session_id, headers):
        return self._request(
            "POST", f"{_P}/video-sessions/{session_id}/cancel", {}, headers
        )

    def close_out_video_session(self, session_id, outcome, headers):
        return self._request(
            "POST",
            f"{_P}/video-sessions/{session_id}/close-out",
            {"outcome": outcome},
            headers,
        )

    # ------------------------------------------------------------------
    # TabletMessage
    # ------------------------------------------------------------------
    def create_message(self, payload, headers):
        return self._request("POST", f"{_P}/messages", payload, headers)

    def get_message(self, message_id, headers):
        return self._request("GET", f"{_P}/messages/{message_id}", headers=headers)

    def list_messages(self, headers, params=None):
        return self._request("GET", f"{_P}/messages", headers=headers, params=params)

    def review_message(self, message_id, decision, headers, review_note=None):
        payload = {"decision": decision}
        if review_note is not None:
            payload["review_note"] = review_note
        return self._request(
            "POST", f"{_P}/messages/{message_id}/review", payload, headers
        )

    # ------------------------------------------------------------------
    # RefundRequest
    # ------------------------------------------------------------------
    def get_refund_request(self, refund_request_id, headers):
        return self._request(
            "GET", f"{_P}/refund-requests/{refund_request_id}", headers=headers
        )

    def list_refund_requests(self, headers, params=None):
        return self._request(
            "GET", f"{_P}/refund-requests", headers=headers, params=params
        )

    def decide_refund_request(
        self, refund_request_id, decision, headers, denial_reason=None
    ):
        payload = {"decision": decision}
        if denial_reason is not None:
            payload["denial_reason"] = denial_reason
        return self._request(
            "POST", f"{_P}/refund-requests/{refund_request_id}/decide", payload, headers
        )

    def mark_refund_paid(self, refund_request_id, headers):
        return self._request(
            "POST", f"{_P}/refund-requests/{refund_request_id}/mark-paid", {}, headers
        )

    # ------------------------------------------------------------------
    # Complaint
    # ------------------------------------------------------------------
    def create_complaint(self, payload, headers):
        return self._request("POST", f"{_P}/complaints", payload, headers)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"{_P}/complaints/{complaint_id}", headers=headers)

    def list_complaints(self, headers, params=None):
        return self._request("GET", f"{_P}/complaints", headers=headers, params=params)

    def start_complaint_review(self, complaint_id, headers):
        return self._request(
            "POST", f"{_P}/complaints/{complaint_id}/start-review", {}, headers
        )

    def resolve_complaint(self, complaint_id, resolution_note, headers):
        return self._request(
            "POST",
            f"{_P}/complaints/{complaint_id}/resolve",
            {"resolution_note": resolution_note},
            headers,
        )

    def escalate_complaint(self, complaint_id, headers):
        return self._request(
            "POST", f"{_P}/complaints/{complaint_id}/escalate", {}, headers
        )


api_client = ApiClient()

__all__ = ["ApiClient", "api_client"]
