"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/program/_clock/set_current_utc", payload, headers)

    # --- contractors ---
    def create_contractor(self, payload, headers):
        return self._request("POST", "/program/contractors", payload, headers)

    def get_contractor(self, contractor_id, headers):
        return self._request("GET", f"/program/contractors/{contractor_id}", headers=headers)

    def patch_contractor_compliance(self, contractor_id, payload, headers):
        return self._request("PATCH", f"/program/contractors/{contractor_id}/compliance", payload, headers)

    def list_contractor_certifications(self, contractor_id, headers):
        return self._request("GET", f"/program/contractors/{contractor_id}/certifications", headers=headers)

    def list_contractor_complaints(self, contractor_id, headers):
        return self._request("GET", f"/program/contractors/{contractor_id}/complaints", headers=headers)

    # --- training ---
    def create_training_course(self, payload, headers):
        return self._request("POST", "/program/training-courses", payload, headers)

    def create_training_enrollment(self, payload, headers):
        return self._request("POST", "/program/training-enrollments", payload, headers)

    def get_training_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/program/training-enrollments/{enrollment_id}", headers=headers)

    def list_training_enrollments(self, headers, params=None):
        return self._request("GET", "/program/training-enrollments", headers=headers, params=params)

    def complete_training_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/program/training-enrollments/{enrollment_id}/complete", payload, headers)

    # --- certifications ---
    def create_certification(self, payload, headers):
        return self._request("POST", "/program/certifications", payload, headers)

    def get_certification(self, certification_id, headers):
        return self._request("GET", f"/program/certifications/{certification_id}", headers=headers)

    def verify_certification(self, certification_id, payload, headers):
        return self._request("POST", f"/program/certifications/{certification_id}/verify", payload, headers)

    def reinstate_certification(self, certification_id, headers):
        return self._request("POST", f"/program/certifications/{certification_id}/reinstate", {}, headers)

    def renew_certification(self, certification_id, payload, headers):
        return self._request("POST", f"/program/certifications/{certification_id}/renew", payload, headers)

    def list_certification_registrations(self, certification_id, headers):
        return self._request("GET", f"/program/certifications/{certification_id}/warranty-registrations", headers=headers)

    # --- catalog ---
    def create_component_catalog_item(self, payload, headers):
        return self._request("POST", "/program/component-catalog-items", payload, headers)

    # --- warranty registrations ---
    def create_warranty_registration(self, payload, headers):
        return self._request("POST", "/program/warranty-registrations", payload, headers)

    def get_warranty_registration(self, registration_id, headers):
        return self._request("GET", f"/program/warranty-registrations/{registration_id}", headers=headers)

    def activate_warranty_registration(self, registration_id, headers):
        return self._request("POST", f"/program/warranty-registrations/{registration_id}/activate", {}, headers)

    def list_registration_components(self, registration_id, headers):
        return self._request("GET", f"/program/warranty-registrations/{registration_id}/components", headers=headers)

    def list_registration_claims(self, registration_id, headers):
        return self._request("GET", f"/program/warranty-registrations/{registration_id}/claims", headers=headers)

    def create_registration_component(self, payload, headers):
        return self._request("POST", "/program/registration-components", payload, headers)

    # --- warranty claims ---
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/program/warranty-claims", payload, headers)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/program/warranty-claims/{claim_id}", headers=headers)

    def add_claim_evidence(self, claim_id, payload, headers):
        return self._request("POST", f"/program/warranty-claims/{claim_id}/evidence", payload, headers)

    def request_inspection(self, claim_id, headers):
        return self._request("POST", f"/program/warranty-claims/{claim_id}/request-inspection", {}, headers)

    def list_claim_inspection_orders(self, claim_id, headers):
        return self._request("GET", f"/program/warranty-claims/{claim_id}/inspection-orders", headers=headers)

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/program/warranty-claims/{claim_id}/adjudicate", payload, headers)

    def reopen_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/program/warranty-claims/{claim_id}/reopen", payload, headers)

    def list_remedy_allocations(self, claim_id, headers):
        return self._request("GET", f"/program/warranty-claims/{claim_id}/remedy-allocation", headers=headers)

    # --- inspection orders ---
    def schedule_inspection_order(self, order_id, payload, headers):
        return self._request("POST", f"/program/inspection-orders/{order_id}/schedule", payload, headers)

    def complete_inspection_order(self, order_id, payload, headers):
        return self._request("POST", f"/program/inspection-orders/{order_id}/complete", payload, headers)

    # --- complaints ---
    def create_complaint(self, payload, headers):
        return self._request("POST", "/program/complaints", payload, headers)

    def substantiate_complaint(self, complaint_id, headers):
        return self._request("POST", f"/program/complaints/{complaint_id}/substantiate", {}, headers)

    def dismiss_complaint(self, complaint_id, headers):
        return self._request("POST", f"/program/complaints/{complaint_id}/dismiss", {}, headers)

    # --- distributors / leads ---
    def create_distributor(self, payload, headers):
        return self._request("POST", "/program/distributors", payload, headers)

    def get_distributor(self, distributor_id, headers):
        return self._request("GET", f"/program/distributors/{distributor_id}", headers=headers)

    def create_lead_assignment(self, payload, headers):
        return self._request("POST", "/program/lead-assignments", payload, headers)

    def return_lead_assignment(self, lead_id, headers):
        return self._request("POST", f"/program/lead-assignments/{lead_id}/return", {}, headers)

    def list_lead_assignments(self, headers, params=None):
        return self._request("GET", "/program/lead-assignments", headers=headers, params=params)

    def get_lead_assignment(self, lead_id, headers):
        return self._request("GET", f"/program/lead-assignments/{lead_id}", headers=headers)


api_client = ApiClient()
