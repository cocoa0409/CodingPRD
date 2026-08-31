"""API client: one method per endpoint defined in the PRD (section 4)."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- Customers ----------------
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def set_credit_status(self, customer_id, payload, headers):
        return self._request(
            "POST", f"/customers/{customer_id}/credit-status", payload, headers
        )

    # ---------------- Sites ----------------
    def create_site(self, payload, headers):
        return self._request("POST", "/sites", payload, headers)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/sites/{site_id}", headers=headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", "/sites", headers=headers, params=params)

    # ---------------- Cranes ----------------
    def create_crane(self, payload, headers):
        return self._request("POST", "/cranes", payload, headers)

    def get_crane(self, crane_id, headers):
        return self._request("GET", f"/cranes/{crane_id}", headers=headers)

    def list_cranes(self, headers, params=None):
        return self._request("GET", "/cranes", headers=headers, params=params)

    def crane_out_of_service(self, crane_id, payload, headers):
        return self._request(
            "POST", f"/cranes/{crane_id}/out-of-service", payload, headers
        )

    def crane_return_to_service(self, crane_id, payload, headers):
        return self._request(
            "POST", f"/cranes/{crane_id}/return-to-service", payload, headers
        )

    # ---------------- Load chart ----------------
    def create_load_chart_entry(self, payload, headers):
        return self._request("POST", "/load-chart-entries", payload, headers)

    def list_crane_load_chart_entries(self, crane_id, headers, params=None):
        return self._request(
            "GET", f"/cranes/{crane_id}/load-chart-entries", headers=headers, params=params
        )

    # ---------------- Personnel ----------------
    def create_personnel(self, payload, headers):
        return self._request("POST", "/personnel", payload, headers)

    def get_personnel(self, personnel_id, headers):
        return self._request("GET", f"/personnel/{personnel_id}", headers=headers)

    def list_personnel(self, headers, params=None):
        return self._request("GET", "/personnel", headers=headers, params=params)

    def recertify_personnel(self, personnel_id, payload, headers):
        return self._request(
            "POST", f"/personnel/{personnel_id}/certifications", payload, headers
        )

    # ---------------- Rigging gear ----------------
    def create_rigging_gear(self, payload, headers):
        return self._request("POST", "/rigging-gear", payload, headers)

    def get_rigging_gear(self, gear_id, headers):
        return self._request("GET", f"/rigging-gear/{gear_id}", headers=headers)

    def list_rigging_gear(self, headers, params=None):
        return self._request("GET", "/rigging-gear", headers=headers, params=params)

    def retire_rigging_gear(self, gear_id, payload, headers):
        return self._request("POST", f"/rigging-gear/{gear_id}/retire", payload, headers)

    def create_gear_inspection(self, payload, headers):
        return self._request("POST", "/gear-inspections", payload, headers)

    def list_gear_inspections(self, gear_id, headers, params=None):
        return self._request(
            "GET", f"/rigging-gear/{gear_id}/inspections", headers=headers, params=params
        )

    # ---------------- Lift plans ----------------
    def create_lift_plan(self, payload, headers):
        return self._request("POST", "/lift-plans", payload, headers)

    def get_lift_plan(self, plan_id, headers):
        return self._request("GET", f"/lift-plans/{plan_id}", headers=headers)

    def list_lift_plans(self, headers, params=None):
        return self._request("GET", "/lift-plans", headers=headers, params=params)

    def site_survey(self, plan_id, payload, headers):
        return self._request("POST", f"/lift-plans/{plan_id}/site-survey", payload, headers)

    def configure_lift_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/lift-plans/{plan_id}/configure", payload, headers)

    def approve_lift_plan(self, plan_id, headers, payload=None):
        return self._request("POST", f"/lift-plans/{plan_id}/approve", payload or {}, headers)

    def release_lift_plan(self, plan_id, headers, payload=None):
        return self._request("POST", f"/lift-plans/{plan_id}/release", payload or {}, headers)

    def cancel_lift_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/lift-plans/{plan_id}/cancel", payload, headers)

    def set_field_status(self, plan_id, payload, headers):
        return self._request("POST", f"/lift-plans/{plan_id}/field-status", payload, headers)

    # ---------------- Gear assignments ----------------
    def create_gear_assignment(self, payload, headers):
        return self._request("POST", "/gear-assignments", payload, headers)

    def get_gear_assignment(self, assignment_id, headers):
        return self._request("GET", f"/gear-assignments/{assignment_id}", headers=headers)

    def list_gear_assignments(self, headers, params=None):
        return self._request("GET", "/gear-assignments", headers=headers, params=params)

    def release_gear_assignment(self, assignment_id, headers, payload=None):
        return self._request(
            "POST", f"/gear-assignments/{assignment_id}/release", payload or {}, headers
        )

    # ---------------- Engineering reviews ----------------
    def create_engineering_review(self, payload, headers):
        return self._request("POST", "/engineering-reviews", payload, headers)

    def get_engineering_review(self, review_id, headers):
        return self._request("GET", f"/engineering-reviews/{review_id}", headers=headers)

    def list_engineering_reviews(self, headers, params=None):
        return self._request("GET", "/engineering-reviews", headers=headers, params=params)

    def decide_engineering_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"/engineering-reviews/{review_id}/decision", payload, headers
        )

    def resubmit_engineering_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"/engineering-reviews/{review_id}/resubmit", payload, headers
        )

    # ---------------- Permits ----------------
    def create_permit(self, payload, headers):
        return self._request("POST", "/permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/permits/{permit_id}", headers=headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/permits", headers=headers, params=params)

    def submit_permit(self, permit_id, headers, payload=None):
        return self._request("POST", f"/permits/{permit_id}/submit", payload or {}, headers)

    def record_permit_decision(self, permit_id, payload, headers):
        return self._request(
            "POST", f"/permits/{permit_id}/record-decision", payload, headers
        )

    # ---------------- Standby events ----------------
    def create_standby_event(self, payload, headers):
        return self._request("POST", "/standby-events", payload, headers)

    def get_standby_event(self, event_id, headers):
        return self._request("GET", f"/standby-events/{event_id}", headers=headers)

    def list_standby_events(self, headers, params=None):
        return self._request("GET", "/standby-events", headers=headers, params=params)

    def close_standby_event(self, event_id, payload, headers):
        return self._request("POST", f"/standby-events/{event_id}/close", payload, headers)

    # ---------------- Invoices ----------------
    def create_invoice(self, payload, headers):
        return self._request("POST", "/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def issue_invoice(self, invoice_id, headers, payload=None):
        return self._request("POST", f"/invoices/{invoice_id}/issue", payload or {}, headers)

    def void_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", payload, headers)

    def dispute_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/dispute", payload, headers)

    def pay_invoice(self, invoice_id, headers, payload=None):
        return self._request("POST", f"/invoices/{invoice_id}/pay", payload or {}, headers)

    # ---------------- Logical clock ----------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---------------- Raw helpers ----------------
    def raw_get(self, path, headers, params=None):
        return self._request("GET", path, headers=headers, params=params)

    def raw_post(self, path, payload, headers):
        return self._request("POST", path, payload, headers)


api_client = ApiClient()
