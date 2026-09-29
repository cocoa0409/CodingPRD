"""API client: one method per endpoint defined in the PRD."""

import re

import requests
from prd_bench_local_runner.testing import GenericApiClient

# ``requests`` refuses to transmit a header value that begins with whitespace, so
# the PRD 2.1 clause "A request whose ``X-User-ID`` header is absent, empty, or
# consists only of whitespace is rejected with ``ERR_UNAUTHENTICATED``" cannot be
# exercised through the ordinary send path at all. Any header carrying such a
# value is therefore applied after the request has been prepared, which skips
# ``PreparedRequest.prepare_headers`` validation and puts the bytes on the wire
# exactly as the PRD describes them.
_LEADING_WHITESPACE = re.compile(r"^\s")


class ApiClient(GenericApiClient):
    """Typed access to the 63 endpoints of the Equity Award Administration API."""

    def _request(self, method, path, payload=None, headers=None, params=None):
        headers = headers or {}
        unsendable = {
            key: value
            for key, value in headers.items()
            if isinstance(value, str) and value != "" and _LEADING_WHITESPACE.match(value)
        }
        if not unsendable:
            return super()._request(method, path, payload, headers, params)

        sendable = {k: v for k, v in headers.items() if k not in unsendable}
        kwargs = {"headers": sendable}
        if method.upper() in ("GET", "DELETE"):
            kwargs["params"] = payload or params
        else:
            kwargs["json"] = payload
            if params:
                kwargs["params"] = params
        prepared = self.session.prepare_request(
            requests.Request(method, f"{self.base_url}{path}", **kwargs)
        )
        for key, value in unsendable.items():
            prepared.headers[key] = value
        return self.session.send(prepared)

    # ---------------------------------------------------------------- clock
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_clock_raw(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---------------------------------------------------------- equity plans
    def create_equity_plan(self, payload, headers):
        return self._request("POST", "/equity-plans", payload, headers)

    def list_equity_plans(self, headers, params=None):
        return self._request("GET", "/equity-plans", headers=headers, params=params)

    def get_equity_plan(self, plan_id, headers):
        return self._request("GET", f"/equity-plans/{plan_id}", headers=headers)

    def set_equity_plan_status(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/equity-plans/{plan_id}/status", payload, headers
        )

    def adjust_share_reserve(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/equity-plans/{plan_id}/share-reserve-adjustments", payload, headers
        )

    def run_annual_rollover(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/equity-plans/{plan_id}/annual-rollover", payload, headers
        )

    def get_burn_rate_summary(self, plan_id, headers):
        return self._request(
            "GET", f"/equity-plans/{plan_id}/burn-rate-summary", headers=headers
        )

    # --------------------------------------------------- approval authorities
    def create_approval_authority(self, payload, headers):
        return self._request("POST", "/approval-authorities", payload, headers)

    def get_approval_authority(self, authority_id, headers):
        return self._request(
            "GET", f"/approval-authorities/{authority_id}", headers=headers
        )

    def list_plan_approval_authorities(self, plan_id, headers, params=None):
        return self._request(
            "GET", f"/equity-plans/{plan_id}/approval-authorities",
            headers=headers, params=params,
        )

    def revoke_approval_authority(self, authority_id, payload, headers):
        return self._request(
            "POST", f"/approval-authorities/{authority_id}/revoke", payload, headers
        )

    # ----------------------------------------------------------- participants
    def create_participant(self, payload, headers):
        return self._request("POST", "/participants", payload, headers)

    def list_participants(self, headers, params=None):
        return self._request("GET", "/participants", headers=headers, params=params)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/participants/{participant_id}", headers=headers)

    def set_insider_status(self, participant_id, payload, headers):
        return self._request(
            "POST", f"/participants/{participant_id}/insider-status", payload, headers
        )

    def terminate_participant(self, participant_id, payload, headers):
        return self._request(
            "POST", f"/participants/{participant_id}/terminate", payload, headers
        )

    # ---------------------------------------------------- mobility assignments
    def create_mobility_assignment(self, payload, headers):
        return self._request("POST", "/mobility-assignments", payload, headers)

    def get_mobility_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/mobility-assignments/{assignment_id}", headers=headers
        )

    def list_participant_mobility_assignments(self, participant_id, headers, params=None):
        return self._request(
            "GET", f"/participants/{participant_id}/mobility-assignments",
            headers=headers, params=params,
        )

    # ----------------------------------------------------------------- grants
    def create_grant(self, payload, headers):
        return self._request("POST", "/grants", payload, headers)

    def list_grants(self, headers, params=None):
        return self._request("GET", "/grants", headers=headers, params=params)

    def get_grant(self, grant_id, headers):
        return self._request("GET", f"/grants/{grant_id}", headers=headers)

    def create_vesting_tranche(self, grant_id, payload, headers):
        return self._request(
            "POST", f"/grants/{grant_id}/vesting-tranches", payload, headers
        )

    def list_vesting_tranches(self, headers, params=None):
        return self._request("GET", "/vesting-tranches", headers=headers, params=params)

    def get_vesting_tranche(self, tranche_id, headers):
        return self._request("GET", f"/vesting-tranches/{tranche_id}", headers=headers)

    def submit_grant(self, grant_id, headers, payload=None):
        return self._request(
            "POST", f"/grants/{grant_id}/submit", payload if payload is not None else {}, headers
        )

    def request_grant_changes(self, grant_id, payload, headers):
        return self._request(
            "POST", f"/grants/{grant_id}/request-changes", payload, headers
        )

    def revise_grant(self, grant_id, payload, headers):
        return self._request("POST", f"/grants/{grant_id}/revise", payload, headers)

    def approve_grant(self, grant_id, payload, headers):
        return self._request("POST", f"/grants/{grant_id}/approve", payload, headers)

    def issue_grant(self, grant_id, headers, payload=None):
        return self._request(
            "POST", f"/grants/{grant_id}/issue", payload if payload is not None else {}, headers
        )

    def cancel_grant(self, grant_id, payload, headers):
        return self._request("POST", f"/grants/{grant_id}/cancel", payload, headers)

    # ------------------------------------------------------ performance cycles
    def create_performance_cycle(self, payload, headers):
        return self._request("POST", "/performance-cycles", payload, headers)

    def get_performance_cycle(self, cycle_id, headers):
        return self._request("GET", f"/performance-cycles/{cycle_id}", headers=headers)

    def list_plan_performance_cycles(self, plan_id, headers, params=None):
        return self._request(
            "GET", f"/equity-plans/{plan_id}/performance-cycles",
            headers=headers, params=params,
        )

    def certify_performance_cycle(self, cycle_id, payload, headers):
        return self._request(
            "POST", f"/performance-cycles/{cycle_id}/certify", payload, headers
        )

    # ----------------------------------------------- vesting and settlements
    def vest_tranche(self, tranche_id, payload, headers):
        return self._request(
            "POST", f"/vesting-tranches/{tranche_id}/vest", payload, headers
        )

    def list_vesting_events(self, headers, params=None):
        return self._request("GET", "/vesting-events", headers=headers, params=params)

    def get_vesting_event(self, event_id, headers):
        return self._request("GET", f"/vesting-events/{event_id}", headers=headers)

    def allocate_taxes(self, event_id, headers, payload=None):
        return self._request(
            "POST", f"/vesting-events/{event_id}/allocate-taxes",
            payload if payload is not None else {}, headers,
        )

    def settle_vesting_event(self, event_id, headers, payload=None):
        return self._request(
            "POST", f"/vesting-events/{event_id}/settle",
            payload if payload is not None else {}, headers,
        )

    def reverse_vesting_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"/vesting-events/{event_id}/reverse", payload, headers
        )

    def list_event_tax_allocations(self, event_id, headers, params=None):
        return self._request(
            "GET", f"/vesting-events/{event_id}/tax-allocations",
            headers=headers, params=params,
        )

    def get_tax_allocation(self, allocation_id, headers):
        return self._request("GET", f"/tax-allocations/{allocation_id}", headers=headers)

    # -------------------------------------------------------- trading windows
    def create_trading_window(self, payload, headers):
        return self._request("POST", "/trading-windows", payload, headers)

    def get_trading_window(self, window_id, headers):
        return self._request("GET", f"/trading-windows/{window_id}", headers=headers)

    def list_plan_trading_windows(self, plan_id, headers, params=None):
        return self._request(
            "GET", f"/equity-plans/{plan_id}/trading-windows",
            headers=headers, params=params,
        )

    def set_trading_window_status(self, window_id, payload, headers):
        return self._request(
            "POST", f"/trading-windows/{window_id}/status", payload, headers
        )

    # -------------------------------------------------- preclearance requests
    def create_preclearance_request(self, payload, headers):
        return self._request("POST", "/preclearance-requests", payload, headers)

    def list_preclearance_requests(self, headers, params=None):
        return self._request(
            "GET", "/preclearance-requests", headers=headers, params=params
        )

    def get_preclearance_request(self, request_id, headers):
        return self._request(
            "GET", f"/preclearance-requests/{request_id}", headers=headers
        )

    def decide_preclearance_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/preclearance-requests/{request_id}/decide", payload, headers
        )

    def resubmit_preclearance_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/preclearance-requests/{request_id}/resubmit", payload, headers
        )

    def execute_preclearance_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/preclearance-requests/{request_id}/execute", payload, headers
        )

    # ------------------------------------------------------------ trading plans
    def create_trading_plan(self, payload, headers):
        return self._request("POST", "/trading-plans", payload, headers)

    def list_trading_plans(self, headers, params=None):
        return self._request("GET", "/trading-plans", headers=headers, params=params)

    def get_trading_plan(self, trading_plan_id, headers):
        return self._request("GET", f"/trading-plans/{trading_plan_id}", headers=headers)

    def activate_trading_plan(self, trading_plan_id, headers, payload=None):
        return self._request(
            "POST", f"/trading-plans/{trading_plan_id}/activate",
            payload if payload is not None else {}, headers,
        )

    def modify_trading_plan(self, trading_plan_id, payload, headers):
        return self._request(
            "POST", f"/trading-plans/{trading_plan_id}/modify", payload, headers
        )

    def terminate_trading_plan(self, trading_plan_id, payload, headers):
        return self._request(
            "POST", f"/trading-plans/{trading_plan_id}/terminate", payload, headers
        )

    # ------------------------------------------------------ Section 16 reports
    def get_transaction_report(self, report_id, headers):
        return self._request("GET", f"/transaction-reports/{report_id}", headers=headers)

    def list_participant_transaction_reports(self, participant_id, headers, params=None):
        return self._request(
            "GET", f"/participants/{participant_id}/transaction-reports",
            headers=headers, params=params,
        )

    def file_transaction_report(self, report_id, headers, payload=None):
        return self._request(
            "POST", f"/transaction-reports/{report_id}/file",
            payload if payload is not None else {}, headers,
        )


api_client = ApiClient()
