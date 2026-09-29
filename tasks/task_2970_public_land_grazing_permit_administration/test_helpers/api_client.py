"""One method per endpoint of PRD 4. Resources are mounted at the service root."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed wrapper over the grazing permit administration API."""

    # --- Allotments and pastures -------------------------------------------
    def create_allotment(self, payload, headers):
        return self._request("POST", "/allotments", payload, headers)

    def list_allotments(self, headers, params=None):
        return self._request("GET", "/allotments", params, headers)

    def get_allotment(self, allotment_id, headers):
        return self._request("GET", f"/allotments/{allotment_id}", None, headers)

    def create_pasture(self, allotment_id, payload, headers):
        return self._request("POST", f"/allotments/{allotment_id}/pastures", payload, headers)

    def list_allotment_pastures(self, allotment_id, headers, params=None):
        return self._request("GET", f"/allotments/{allotment_id}/pastures", params, headers)

    def get_pasture(self, pasture_id, headers):
        return self._request("GET", f"/pastures/{pasture_id}", None, headers)

    def list_pastures(self, headers, params=None):
        return self._request("GET", "/pastures", params, headers)

    def list_allotment_closure_orders(self, allotment_id, headers, params=None):
        return self._request("GET", f"/allotments/{allotment_id}/closure-orders", params, headers)

    # --- Permittees and base property --------------------------------------
    def create_permittee(self, payload, headers):
        return self._request("POST", "/permittees", payload, headers)

    def get_permittee(self, permittee_id, headers):
        return self._request("GET", f"/permittees/{permittee_id}", None, headers)

    def create_base_property(self, permittee_id, payload, headers):
        return self._request("POST", f"/permittees/{permittee_id}/base-properties", payload, headers)

    def list_permittee_base_properties(self, permittee_id, headers, params=None):
        return self._request("GET", f"/permittees/{permittee_id}/base-properties", params, headers)

    def get_base_property(self, base_property_id, headers):
        return self._request("GET", f"/base-properties/{base_property_id}", None, headers)

    def list_base_properties(self, headers, params=None):
        return self._request("GET", "/base-properties", params, headers)

    # --- Grazing permits ----------------------------------------------------
    def create_permit(self, payload, headers):
        return self._request("POST", "/grazing-permits", payload, headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/grazing-permits", params, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/grazing-permits/{permit_id}", None, headers)

    def issue_permit(self, permit_id, headers, payload=None):
        return self._request("POST", f"/grazing-permits/{permit_id}/issue", payload or {}, headers)

    def renew_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/grazing-permits/{permit_id}/renew", payload, headers)

    def transfer_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/grazing-permits/{permit_id}/transfer", payload, headers)

    # --- Annual operating instructions and use records ----------------------
    def create_aoi(self, payload, headers):
        return self._request("POST", "/annual-operating-instructions", payload, headers)

    def list_aois(self, headers, params=None):
        return self._request("GET", "/annual-operating-instructions", params, headers)

    def get_aoi(self, aoi_id, headers):
        return self._request("GET", f"/annual-operating-instructions/{aoi_id}", None, headers)

    def create_use_record(self, aoi_id, payload, headers):
        return self._request(
            "POST", f"/annual-operating-instructions/{aoi_id}/use-records", payload, headers)

    def list_use_records(self, headers, params=None):
        return self._request("GET", "/pasture-use-records", params, headers)

    def get_use_record(self, use_record_id, headers):
        return self._request("GET", f"/pasture-use-records/{use_record_id}", None, headers)

    def issue_aoi(self, aoi_id, headers, payload=None):
        return self._request(
            "POST", f"/annual-operating-instructions/{aoi_id}/issue", payload or {}, headers)

    def approve_nonuse(self, aoi_id, payload, headers):
        return self._request(
            "POST", f"/annual-operating-instructions/{aoi_id}/non-use", payload, headers)

    def report_actual_use(self, use_record_id, payload, headers):
        return self._request(
            "POST", f"/pasture-use-records/{use_record_id}/report-actual-use", payload, headers)

    def accept_use_report(self, aoi_id, headers, payload=None):
        return self._request(
            "POST", f"/annual-operating-instructions/{aoi_id}/accept-use-report",
            payload or {}, headers)

    def void_aoi(self, aoi_id, payload, headers):
        return self._request(
            "POST", f"/annual-operating-instructions/{aoi_id}/void", payload, headers)

    # --- Grazing bills ------------------------------------------------------
    def list_bills(self, headers, params=None):
        return self._request("GET", "/grazing-bills", params, headers)

    def get_bill(self, bill_id, headers):
        return self._request("GET", f"/grazing-bills/{bill_id}", None, headers)

    def record_payment(self, bill_id, payload, headers):
        return self._request("POST", f"/grazing-bills/{bill_id}/payments", payload, headers)

    def void_bill(self, bill_id, payload, headers):
        return self._request("POST", f"/grazing-bills/{bill_id}/void", payload, headers)

    # --- Rangeland health assessments ---------------------------------------
    def create_assessment(self, payload, headers):
        return self._request("POST", "/rangeland-health-assessments", payload, headers)

    def list_assessments(self, headers, params=None):
        return self._request("GET", "/rangeland-health-assessments", params, headers)

    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/rangeland-health-assessments/{assessment_id}", None, headers)

    def submit_assessment(self, assessment_id, headers, payload=None):
        return self._request(
            "POST", f"/rangeland-health-assessments/{assessment_id}/submit", payload or {}, headers)

    def review_assessment(self, assessment_id, payload, headers):
        return self._request(
            "POST", f"/rangeland-health-assessments/{assessment_id}/review", payload, headers)

    # --- Permit decisions ---------------------------------------------------
    def create_decision(self, payload, headers):
        return self._request("POST", "/permit-decisions", payload, headers)

    def list_decisions(self, headers, params=None):
        return self._request("GET", "/permit-decisions", params, headers)

    def get_decision(self, decision_id, headers):
        return self._request("GET", f"/permit-decisions/{decision_id}", None, headers)

    def complete_environmental_review(self, decision_id, payload, headers):
        return self._request(
            "POST", f"/permit-decisions/{decision_id}/complete-environmental-review",
            payload, headers)

    def finalize_decision(self, decision_id, payload, headers):
        return self._request("POST", f"/permit-decisions/{decision_id}/finalize", payload, headers)

    def make_decision_effective(self, decision_id, headers, payload=None):
        return self._request(
            "POST", f"/permit-decisions/{decision_id}/make-effective", payload or {}, headers)

    # --- Appeal cases -------------------------------------------------------
    def file_appeal(self, decision_id, payload, headers):
        return self._request("POST", f"/permit-decisions/{decision_id}/appeals", payload, headers)

    def list_appeals(self, headers, params=None):
        return self._request("GET", "/appeal-cases", params, headers)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/appeal-cases/{appeal_id}", None, headers)

    def docket_appeal(self, appeal_id, headers, payload=None):
        return self._request("POST", f"/appeal-cases/{appeal_id}/docket", payload or {}, headers)

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/appeal-cases/{appeal_id}/decide", payload, headers)

    # --- Closure orders -----------------------------------------------------
    def create_closure_order(self, payload, headers):
        return self._request("POST", "/closure-orders", payload, headers)

    def get_closure_order(self, closure_order_id, headers):
        return self._request("GET", f"/closure-orders/{closure_order_id}", None, headers)

    def list_closure_orders(self, headers, params=None):
        return self._request("GET", "/closure-orders", params, headers)

    def lift_closure_order(self, closure_order_id, payload, headers):
        return self._request(
            "POST", f"/closure-orders/{closure_order_id}/lift", payload or {}, headers)

    # --- Trespass incidents -------------------------------------------------
    def create_trespass_incident(self, payload, headers):
        return self._request("POST", "/trespass-incidents", payload, headers)

    def list_trespass_incidents(self, headers, params=None):
        return self._request("GET", "/trespass-incidents", params, headers)

    def get_trespass_incident(self, incident_id, headers):
        return self._request("GET", f"/trespass-incidents/{incident_id}", None, headers)

    def bill_trespass_incident(self, incident_id, headers, payload=None):
        return self._request(
            "POST", f"/trespass-incidents/{incident_id}/bill", payload or {}, headers)

    # --- Range improvement projects -----------------------------------------
    def create_project(self, payload, headers):
        return self._request("POST", "/range-improvement-projects", payload, headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/range-improvement-projects", params, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/range-improvement-projects/{project_id}", None, headers)

    def approve_project(self, project_id, headers, payload=None):
        return self._request(
            "POST", f"/range-improvement-projects/{project_id}/approve", payload or {}, headers)

    def allocate_cost_share(self, project_id, headers, payload=None):
        return self._request(
            "POST", f"/range-improvement-projects/{project_id}/allocate-cost-share",
            payload or {}, headers)

    # --- Logical clock ------------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
