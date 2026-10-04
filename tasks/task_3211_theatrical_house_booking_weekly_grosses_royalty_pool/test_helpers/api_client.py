"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Companies ---
    def create_company(self, payload, headers):
        return self._request("POST", "/theatres/companies", payload, headers)

    def get_company(self, company_id, headers):
        return self._request("GET", f"/theatres/companies/{company_id}", headers=headers)

    def list_companies(self, headers, params=None):
        return self._request("GET", "/theatres/companies", headers=headers, params=params)

    # --- Theatres ---
    def create_theatre(self, payload, headers):
        return self._request("POST", "/theatres/houses", payload, headers)

    def get_theatre(self, theatre_id, headers):
        return self._request("GET", f"/theatres/houses/{theatre_id}", headers=headers)

    def list_theatres(self, headers, params=None):
        return self._request("GET", "/theatres/houses", headers=headers, params=params)

    def list_theatre_bookings(self, theatre_id, headers, params=None):
        return self._request("GET", f"/theatres/houses/{theatre_id}/bookings",
                             headers=headers, params=params)

    def list_theatre_capital_projects(self, theatre_id, headers, params=None):
        return self._request("GET", f"/theatres/houses/{theatre_id}/capital-projects",
                             headers=headers, params=params)

    # --- Productions ---
    def create_production(self, payload, headers):
        return self._request("POST", "/theatres/productions", payload, headers)

    def get_production(self, production_id, headers):
        return self._request("GET", f"/theatres/productions/{production_id}", headers=headers)

    def list_productions(self, headers, params=None):
        return self._request("GET", "/theatres/productions", headers=headers, params=params)

    def list_production_royalty_participants(self, production_id, headers, params=None):
        return self._request("GET", f"/theatres/productions/{production_id}/royalty-participants",
                             headers=headers, params=params)

    def list_production_discount_codes(self, production_id, headers, params=None):
        return self._request("GET", f"/theatres/productions/{production_id}/discount-codes",
                             headers=headers, params=params)

    # --- Bookings ---
    def create_booking(self, payload, headers):
        return self._request("POST", "/theatres/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/theatres/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/theatres/bookings", headers=headers, params=params)

    def approve_booking(self, booking_id, headers):
        return self._request("POST", f"/theatres/bookings/{booking_id}/approve", {}, headers)

    def decline_booking(self, booking_id, headers):
        return self._request("POST", f"/theatres/bookings/{booking_id}/decline", {}, headers)

    def withdraw_booking(self, booking_id, headers):
        return self._request("POST", f"/theatres/bookings/{booking_id}/withdraw", {}, headers)

    def close_booking(self, booking_id, headers):
        return self._request("POST", f"/theatres/bookings/{booking_id}/close", {}, headers)

    def execute_stop_notice(self, booking_id, headers):
        return self._request("POST", f"/theatres/bookings/{booking_id}/execute_stop_notice",
                             {}, headers)

    def list_booking_stop_notices(self, booking_id, headers, params=None):
        return self._request("GET", f"/theatres/bookings/{booking_id}/stop-notices",
                             headers=headers, params=params)

    def list_booking_weekly_gross_reports(self, booking_id, headers, params=None):
        return self._request("GET", f"/theatres/bookings/{booking_id}/weekly-gross-reports",
                             headers=headers, params=params)

    def list_booking_ticket_orders(self, booking_id, headers, params=None):
        return self._request("GET", f"/theatres/bookings/{booking_id}/ticket-orders",
                             headers=headers, params=params)

    def list_booking_crew_assignments(self, booking_id, headers, params=None):
        return self._request("GET", f"/theatres/bookings/{booking_id}/crew-assignments",
                             headers=headers, params=params)

    def list_booking_license_agreements(self, booking_id, headers, params=None):
        return self._request("GET", f"/theatres/bookings/{booking_id}/license-agreements",
                             headers=headers, params=params)

    # --- License agreements ---
    def create_license_agreement(self, booking_id, payload, headers):
        return self._request("POST", f"/theatres/bookings/{booking_id}/license-agreements",
                             payload, headers)

    def get_license_agreement(self, agreement_id, headers):
        return self._request("GET", f"/theatres/license-agreements/{agreement_id}",
                             headers=headers)

    def sign_license_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/theatres/license-agreements/{agreement_id}/sign",
                             payload, headers)

    # --- Royalty participants ---
    def create_royalty_participant(self, production_id, payload, headers):
        return self._request("POST",
                             f"/theatres/productions/{production_id}/royalty-participants",
                             payload, headers)

    def get_royalty_participant(self, participant_id, headers):
        return self._request("GET", f"/theatres/royalty-participants/{participant_id}",
                             headers=headers)

    # --- Discount codes ---
    def create_discount_code(self, production_id, payload, headers):
        return self._request("POST", f"/theatres/productions/{production_id}/discount-codes",
                             payload, headers)

    def get_discount_code(self, code_id, headers):
        return self._request("GET", f"/theatres/discount-codes/{code_id}", headers=headers)

    def deactivate_discount_code(self, code_id, headers):
        return self._request("POST", f"/theatres/discount-codes/{code_id}/deactivate",
                             {}, headers)

    # --- Ticket orders ---
    def create_ticket_order(self, booking_id, payload, headers):
        return self._request("POST", f"/theatres/bookings/{booking_id}/ticket-orders",
                             payload, headers)

    def get_ticket_order(self, order_id, headers):
        return self._request("GET", f"/theatres/ticket-orders/{order_id}", headers=headers)

    def list_ticket_orders(self, headers, params=None):
        return self._request("GET", "/theatres/ticket-orders", headers=headers, params=params)

    def refund_ticket_order(self, order_id, headers):
        return self._request("POST", f"/theatres/ticket-orders/{order_id}/refund", {}, headers)

    # --- Weekly gross reports ---
    def create_weekly_gross_report(self, booking_id, payload, headers):
        return self._request("POST", f"/theatres/bookings/{booking_id}/weekly-gross-reports",
                             payload, headers)

    def get_weekly_gross_report(self, report_id, headers):
        return self._request("GET", f"/theatres/weekly-gross-reports/{report_id}",
                             headers=headers)

    def submit_weekly_gross_report(self, report_id, headers):
        return self._request("POST", f"/theatres/weekly-gross-reports/{report_id}/submit",
                             {}, headers)

    def verify_weekly_gross_report(self, report_id, headers):
        return self._request("POST", f"/theatres/weekly-gross-reports/{report_id}/verify",
                             {}, headers)

    def reject_weekly_gross_report(self, report_id, headers):
        return self._request("POST", f"/theatres/weekly-gross-reports/{report_id}/reject",
                             {}, headers)

    def revise_weekly_gross_report(self, report_id, headers):
        return self._request("POST", f"/theatres/weekly-gross-reports/{report_id}/revise",
                             {}, headers)

    def get_report_settlement(self, report_id, headers):
        return self._request("GET", f"/theatres/weekly-gross-reports/{report_id}/settlement",
                             headers=headers)

    # --- Settlements ---
    def create_settlement(self, report_id, payload, headers):
        return self._request("POST", f"/theatres/weekly-gross-reports/{report_id}/settlements",
                             payload, headers)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/theatres/settlements/{settlement_id}", headers=headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/theatres/settlements", headers=headers, params=params)

    def finalize_settlement(self, settlement_id, headers):
        return self._request("POST", f"/theatres/settlements/{settlement_id}/finalize",
                             {}, headers)

    # --- Crew ---
    def create_crew_assignment(self, booking_id, payload, headers):
        return self._request("POST", f"/theatres/bookings/{booking_id}/crew-assignments",
                             payload, headers)

    # --- Capital projects ---
    def create_capital_project(self, theatre_id, payload, headers):
        return self._request("POST", f"/theatres/houses/{theatre_id}/capital-projects",
                             payload, headers)

    def get_capital_project(self, project_id, headers):
        return self._request("GET", f"/theatres/capital-projects/{project_id}", headers=headers)

    def complete_capital_project(self, project_id, headers):
        return self._request("POST", f"/theatres/capital-projects/{project_id}/complete",
                             {}, headers)

    def cancel_capital_project(self, project_id, headers):
        return self._request("POST", f"/theatres/capital-projects/{project_id}/cancel",
                             {}, headers)


api_client = ApiClient()
