"""HTTP client with one method per endpoint of the EPR reporting API (PRD 4).

Every method returns the raw response object so tests can assert on the status
code and on the error envelope. All paths are mounted under the `/epr` prefix.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

Headers = Optional[Dict[str, str]]
Payload = Optional[Dict[str, Any]]


class ApiClient(GenericApiClient):
    """Endpoint methods for the Packaging Extended Producer Responsibility API."""

    PREFIX = "/epr"

    # ------------------------------------------------------------------
    # Producers
    # ------------------------------------------------------------------
    def create_producer(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{self.PREFIX}/producers", payload, headers)

    def get_producer(self, producer_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{self.PREFIX}/producers/{producer_id}", None, headers
        )

    def list_producers(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", f"{self.PREFIX}/producers", params, headers)

    def determine_obligation(
        self, producer_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{self.PREFIX}/producers/{producer_id}/determine-obligation",
            payload if payload is not None else {},
            headers,
        )

    def restate_revenue(self, producer_id: str, payload: Payload, headers: Headers = None):
        return self._request(
            "POST",
            f"{self.PREFIX}/producers/{producer_id}/restate-revenue",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Stock keeping units
    # ------------------------------------------------------------------
    def create_sku(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{self.PREFIX}/skus", payload, headers)

    def get_sku(self, sku_id: str, headers: Headers = None):
        return self._request("GET", f"{self.PREFIX}/skus/{sku_id}", None, headers)

    def list_skus(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", f"{self.PREFIX}/skus", params, headers)

    def add_sku_component(self, sku_id: str, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"{self.PREFIX}/skus/{sku_id}/components", payload, headers
        )

    def activate_sku(self, sku_id: str, payload: Payload = None, headers: Headers = None):
        return self._request(
            "POST",
            f"{self.PREFIX}/skus/{sku_id}/activate",
            payload if payload is not None else {},
            headers,
        )

    def revise_packaging(self, sku_id: str, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"{self.PREFIX}/skus/{sku_id}/revise-packaging", payload, headers
        )

    def redesign_projection(self, sku_id: str, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"{self.PREFIX}/skus/{sku_id}/redesign-projection", payload, headers
        )

    # ------------------------------------------------------------------
    # State programs and reporting periods
    # ------------------------------------------------------------------
    def create_state_program(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{self.PREFIX}/state-programs", payload, headers)

    def get_state_program(self, state_program_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{self.PREFIX}/state-programs/{state_program_id}", None, headers
        )

    def list_state_programs(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", f"{self.PREFIX}/state-programs", params, headers)

    def create_reporting_period(
        self, state_program_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{self.PREFIX}/state-programs/{state_program_id}/reporting-periods",
            payload,
            headers,
        )

    def list_reporting_periods(
        self, state_program_id: str, headers: Headers = None, params: Payload = None
    ):
        return self._request(
            "GET",
            f"{self.PREFIX}/state-programs/{state_program_id}/reporting-periods",
            params,
            headers,
        )

    def get_reporting_period(self, reporting_period_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{self.PREFIX}/reporting-periods/{reporting_period_id}", None, headers
        )

    # ------------------------------------------------------------------
    # Producer responsibility organisations
    # ------------------------------------------------------------------
    def create_pro(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{self.PREFIX}/pros", payload, headers)

    def get_pro(self, pro_id: str, headers: Headers = None):
        return self._request("GET", f"{self.PREFIX}/pros/{pro_id}", None, headers)

    def list_pros(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", f"{self.PREFIX}/pros", params, headers)

    # ------------------------------------------------------------------
    # Fee schedules
    # ------------------------------------------------------------------
    def create_fee_schedule(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{self.PREFIX}/fee-schedules", payload, headers)

    def get_fee_schedule(self, fee_schedule_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{self.PREFIX}/fee-schedules/{fee_schedule_id}", None, headers
        )

    def list_fee_schedules(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", f"{self.PREFIX}/fee-schedules", params, headers)

    def publish_fee_schedule(
        self, fee_schedule_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{self.PREFIX}/fee-schedules/{fee_schedule_id}/publish",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Registrations
    # ------------------------------------------------------------------
    def create_registration(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{self.PREFIX}/registrations", payload, headers)

    def get_registration(self, registration_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{self.PREFIX}/registrations/{registration_id}", None, headers
        )

    def list_registrations(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", f"{self.PREFIX}/registrations", params, headers)

    def submit_registration(
        self, registration_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{self.PREFIX}/registrations/{registration_id}/submit",
            payload if payload is not None else {},
            headers,
        )

    def decide_registration(
        self, registration_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{self.PREFIX}/registrations/{registration_id}/decide",
            payload,
            headers,
        )

    def suspend_registration(
        self, registration_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{self.PREFIX}/registrations/{registration_id}/suspend",
            payload,
            headers,
        )

    def reinstate_registration(
        self, registration_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{self.PREFIX}/registrations/{registration_id}/reinstate",
            payload if payload is not None else {},
            headers,
        )

    def withdraw_registration(
        self, registration_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{self.PREFIX}/registrations/{registration_id}/withdraw",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Memberships
    # ------------------------------------------------------------------
    def create_membership(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{self.PREFIX}/memberships", payload, headers)

    def get_membership(self, membership_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{self.PREFIX}/memberships/{membership_id}", None, headers
        )

    def list_memberships(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", f"{self.PREFIX}/memberships", params, headers)

    def decide_membership(
        self, membership_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST", f"{self.PREFIX}/memberships/{membership_id}/decide", payload, headers
        )

    def record_fee_payment(
        self, membership_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{self.PREFIX}/memberships/{membership_id}/record-fee-payment",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Packaging reports and report lines
    # ------------------------------------------------------------------
    def create_report(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{self.PREFIX}/reports", payload, headers)

    def get_report(self, report_id: str, headers: Headers = None):
        return self._request("GET", f"{self.PREFIX}/reports/{report_id}", None, headers)

    def list_reports(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", f"{self.PREFIX}/reports", params, headers)

    def add_report_line(self, report_id: str, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"{self.PREFIX}/reports/{report_id}/lines", payload, headers
        )

    def get_report_line(self, report_line_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{self.PREFIX}/report-lines/{report_line_id}", None, headers
        )

    def list_report_lines(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", f"{self.PREFIX}/report-lines", params, headers)

    def delete_report_line(self, report_line_id: str, headers: Headers = None):
        return self._request(
            "DELETE", f"{self.PREFIX}/report-lines/{report_line_id}", None, headers
        )

    def submit_report(
        self, report_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{self.PREFIX}/reports/{report_id}/submit",
            payload if payload is not None else {},
            headers,
        )

    def assess_report(self, report_id: str, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"{self.PREFIX}/reports/{report_id}/assess", payload, headers
        )

    def get_fee_breakdown(self, report_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{self.PREFIX}/reports/{report_id}/fee-breakdown", None, headers
        )

    def resubmit_report(
        self, report_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{self.PREFIX}/reports/{report_id}/resubmit",
            payload if payload is not None else {},
            headers,
        )

    def close_report(self, report_id: str, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"{self.PREFIX}/reports/{report_id}/close", payload, headers
        )

    # ------------------------------------------------------------------
    # Verification engagements
    # ------------------------------------------------------------------
    def create_engagement(self, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"{self.PREFIX}/verification-engagements", payload, headers
        )

    def get_engagement(self, engagement_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{self.PREFIX}/verification-engagements/{engagement_id}", None, headers
        )

    def list_engagements(self, headers: Headers = None, params: Payload = None):
        return self._request(
            "GET", f"{self.PREFIX}/verification-engagements", params, headers
        )

    def start_engagement(
        self, engagement_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{self.PREFIX}/verification-engagements/{engagement_id}/start",
            payload if payload is not None else {},
            headers,
        )

    def issue_opinion(self, engagement_id: str, payload: Payload, headers: Headers = None):
        return self._request(
            "POST",
            f"{self.PREFIX}/verification-engagements/{engagement_id}/issue-opinion",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Invoices
    # ------------------------------------------------------------------
    def create_invoice(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{self.PREFIX}/invoices", payload, headers)

    def get_invoice(self, invoice_id: str, headers: Headers = None):
        return self._request("GET", f"{self.PREFIX}/invoices/{invoice_id}", None, headers)

    def list_invoices(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", f"{self.PREFIX}/invoices", params, headers)

    def void_invoice(self, invoice_id: str, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"{self.PREFIX}/invoices/{invoice_id}/void", payload, headers
        )

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, current_utc: str, headers: Headers = None):
        return self._request(
            "POST",
            f"{self.PREFIX}/_clock/set_current_utc",
            {"current_utc": current_utc},
            headers,
        )
