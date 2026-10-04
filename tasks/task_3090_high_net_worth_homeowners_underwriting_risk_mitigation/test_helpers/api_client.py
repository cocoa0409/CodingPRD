"""API client: one method per endpoint declared in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Thin endpoint wrapper over the HNW homeowners underwriting API."""

    # ─── Reference configuration ──────────────────────────────────────────
    def set_clock(self, current_utc, headers):
        return self._request("POST", "/hnw/_clock/set_current_utc",
                             {"current_utc": current_utc}, headers)

    def create_risk_zone(self, payload, headers):
        return self._request("POST", "/hnw/risk-zones", payload, headers)

    def list_risk_zones(self, headers, params=None):
        return self._request("GET", "/hnw/risk-zones", headers=headers, params=params)

    def get_risk_zone(self, zone_id, headers):
        return self._request("GET", f"/hnw/risk-zones/{zone_id}", headers=headers)

    def check_concentration(self, zone_id, headers):
        return self._request("POST", f"/hnw/risk-zones/{zone_id}/check_concentration",
                             headers=headers)

    def set_zone_event(self, zone_id, state_event, headers):
        return self._request("POST", f"/hnw/risk-zones/{zone_id}/set-event",
                             {"state_event": state_event}, headers)

    def create_agency(self, payload, headers):
        return self._request("POST", "/hnw/agencies", payload, headers)

    def list_agencies(self, headers, params=None):
        return self._request("GET", "/hnw/agencies", headers=headers, params=params)

    def get_agency(self, agency_id, headers):
        return self._request("GET", f"/hnw/agencies/{agency_id}", headers=headers)

    def set_agency_active(self, agency_id, active, headers):
        return self._request("POST", f"/hnw/agencies/{agency_id}/set-active",
                             {"active": active}, headers)

    # ─── Properties ───────────────────────────────────────────────────────
    def create_property(self, payload, headers):
        return self._request("POST", "/hnw/properties", payload, headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/hnw/properties", headers=headers, params=params)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/hnw/properties/{property_id}", headers=headers)

    def posture_eval(self, property_id, expected_property_version, headers):
        return self._request("POST", f"/hnw/properties/{property_id}/posture-eval",
                             {"expected_property_version": expected_property_version},
                             headers)

    def reopen_property(self, property_id, headers):
        return self._request("POST", f"/hnw/properties/{property_id}/reopen",
                             headers=headers)

    # ─── Appraisals ───────────────────────────────────────────────────────
    def create_appraisal(self, property_id, payload, headers):
        return self._request("POST", f"/hnw/properties/{property_id}/appraisals",
                             payload, headers)

    def list_appraisals(self, property_id, headers, params=None):
        return self._request("GET", f"/hnw/properties/{property_id}/appraisals",
                             headers=headers, params=params)

    def get_appraisal(self, appraisal_id, headers):
        return self._request("GET", f"/hnw/appraisals/{appraisal_id}", headers=headers)

    def review_appraisal(self, appraisal_id, headers):
        return self._request("POST", f"/hnw/appraisals/{appraisal_id}/review",
                             headers=headers)

    def approve_appraisal(self, appraisal_id, headers):
        return self._request("POST", f"/hnw/appraisals/{appraisal_id}/approve",
                             headers=headers)

    def provision_appraisal(self, appraisal_id, headers):
        return self._request("POST", f"/hnw/appraisals/{appraisal_id}/provision",
                             headers=headers)

    def reject_appraisal(self, appraisal_id, reason, headers):
        return self._request("POST", f"/hnw/appraisals/{appraisal_id}/reject",
                             {"reason": reason}, headers)

    def supersede_appraisal(self, appraisal_id, headers):
        return self._request("POST", f"/hnw/appraisals/{appraisal_id}/supersede",
                             headers=headers)

    def withdraw_appraisal(self, appraisal_id, headers):
        return self._request("POST", f"/hnw/appraisals/{appraisal_id}/withdraw",
                             headers=headers)

    def reappraise(self, property_id, appraisal_id, headers):
        return self._request("POST", f"/hnw/properties/{property_id}/valuation/reappraise",
                             {"appraisal_id": appraisal_id}, headers)

    # ─── Appraisal documents ──────────────────────────────────────────────
    def create_appraisal_document(self, property_id, payload, headers):
        return self._request("POST", f"/hnw/properties/{property_id}/appraisal-documents",
                             payload, headers)

    def list_appraisal_documents(self, property_id, headers, params=None):
        return self._request("GET", f"/hnw/properties/{property_id}/appraisal-documents",
                             headers=headers, params=params)

    def get_appraisal_document(self, doc_id, headers):
        return self._request("GET", f"/hnw/appraisal-documents/{doc_id}", headers=headers)

    def list_document_scheduled_items(self, doc_id, headers, params=None):
        return self._request("GET", f"/hnw/appraisal-documents/{doc_id}/scheduled-items",
                             headers=headers, params=params)

    # ─── Scheduled personal property ──────────────────────────────────────
    def create_scheduled_item(self, property_id, payload, headers):
        return self._request("POST", f"/hnw/properties/{property_id}/scheduled-items",
                             payload, headers)

    def list_scheduled_items(self, property_id, headers, params=None):
        return self._request("GET", f"/hnw/properties/{property_id}/scheduled-items",
                             headers=headers, params=params)

    def approve_scheduled_item(self, item_id, headers):
        return self._request("POST", f"/hnw/scheduled-items/{item_id}/approve",
                             headers=headers)

    def reject_scheduled_item(self, item_id, reason, headers):
        return self._request("POST", f"/hnw/scheduled-items/{item_id}/reject",
                             {"reason": reason}, headers)

    def refresh_scheduled_item_appraisal(self, item_id, appraisal_doc_id, headers):
        return self._request("POST", f"/hnw/scheduled-items/{item_id}/refresh-appraisal",
                             {"appraisal_doc_id": appraisal_doc_id}, headers)

    def detach_scheduled_item(self, item_id, claim_id, headers):
        return self._request("POST", f"/hnw/scheduled-items/{item_id}/detach",
                             {"claim_id": claim_id}, headers)

    # ─── Mitigation requirements ──────────────────────────────────────────
    def create_mitigation_requirement(self, property_id, payload, headers):
        return self._request("POST", f"/hnw/properties/{property_id}/mitigation-requirements",
                             payload, headers)

    def list_mitigation_requirements(self, property_id, headers, params=None):
        return self._request("GET", f"/hnw/properties/{property_id}/mitigation-requirements",
                             headers=headers, params=params)

    def verify_mitigation_requirement(self, requirement_id, verified_band, headers,
                                      verification_count=None):
        payload = {"verified_band": verified_band}
        if verification_count is not None:
            payload["verification_count"] = verification_count
        return self._request("POST", f"/hnw/mitigation-requirements/{requirement_id}/verify",
                             payload, headers)

    def waive_mitigation_requirement(self, requirement_id, reason, headers):
        return self._request("POST", f"/hnw/mitigation-requirements/{requirement_id}/waive",
                             {"reason": reason}, headers)

    def reopen_mitigation_requirement(self, requirement_id, due_on, headers):
        return self._request("POST", f"/hnw/mitigation-requirements/{requirement_id}/reopen",
                             {"due_on": due_on}, headers)

    # ─── Risk consultations ───────────────────────────────────────────────
    def create_risk_consultation(self, property_id, payload, headers):
        return self._request("POST", f"/hnw/properties/{property_id}/risk-consultations",
                             payload, headers)

    def list_risk_consultations(self, property_id, headers, params=None):
        return self._request("GET", f"/hnw/properties/{property_id}/risk-consultations",
                             headers=headers, params=params)

    def complete_risk_consultation(self, consultation_id, headers):
        return self._request("POST", f"/hnw/risk-consultations/{consultation_id}/complete",
                             headers=headers)

    def cancel_risk_consultation(self, consultation_id, headers):
        return self._request("POST", f"/hnw/risk-consultations/{consultation_id}/cancel",
                             headers=headers)

    def revisit_risk_consultation(self, consultation_id, scheduled_for, headers):
        return self._request("POST", f"/hnw/risk-consultations/{consultation_id}/revisit",
                             {"scheduled_for": scheduled_for}, headers)

    def issue_consultation_report(self, consultation_id, payload, headers):
        return self._request("POST", f"/hnw/risk-consultations/{consultation_id}/report",
                             payload, headers)

    # ─── Wildfire defense dispatch ────────────────────────────────────────
    def request_dispatch(self, property_id, headers):
        return self._request("POST", f"/hnw/wildfire-events/properties/{property_id}/dispatch-request",
                             headers=headers)

    def poll_vendors(self, risk_zone_id, headers):
        return self._request("POST", "/hnw/wildfire-events/vendors/poll",
                             {"risk_zone_id": risk_zone_id}, headers)

    def dispatch_ack(self, property_id, risk_zone_id, vendor_ref, headers):
        return self._request("POST", f"/hnw/wildfire-events/properties/{property_id}/dispatch-ack",
                             {"risk_zone_id": risk_zone_id, "vendor_ref": vendor_ref},
                             headers)

    def advance_dispatch(self, dispatch_id, headers):
        return self._request("POST", f"/hnw/wildfire-events/dispatches/{dispatch_id}/advance",
                             headers=headers)

    def list_property_dispatches(self, property_id, headers, params=None):
        return self._request("GET", f"/hnw/properties/{property_id}/wildfire-dispatches",
                             headers=headers, params=params)

    def list_zone_dispatches(self, zone_id, headers, params=None):
        return self._request("GET", f"/hnw/risk-zones/{zone_id}/wildfire-dispatches",
                             headers=headers, params=params)

    # ─── Enrollments ──────────────────────────────────────────────────────
    def create_enrollment(self, property_id, payload, headers):
        return self._request("POST", f"/hnw/properties/{property_id}/enrollments",
                             payload, headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/hnw/enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/hnw/enrollments/{enrollment_id}", headers=headers)

    def underwriting_summary(self, enrollment_id, headers, view=None):
        params = {"view": view} if view is not None else None
        return self._request("GET", f"/hnw/enrollments/{enrollment_id}/underwriting-summary",
                             headers=headers, params=params)

    def create_endorsement(self, enrollment_id, payload, headers):
        return self._request("POST", f"/hnw/enrollments/{enrollment_id}/endorsements",
                             payload, headers)

    def submit_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/hnw/enrollments/{enrollment_id}/submit",
                             headers=headers)

    def refer_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/hnw/enrollments/{enrollment_id}/refer",
                             headers=headers)

    def approve_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/hnw/enrollments/{enrollment_id}/approve",
                             headers=headers)

    def return_enrollment_to_draft(self, enrollment_id, headers):
        return self._request("POST", f"/hnw/enrollments/{enrollment_id}/return-to-draft",
                             headers=headers)

    def recall_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/hnw/enrollments/{enrollment_id}/recall",
                             headers=headers)

    def attach_enrollment(self, enrollment_id, expected_property_version, headers):
        return self._request("POST", f"/hnw/enrollments/{enrollment_id}/attach",
                             {"expected_property_version": expected_property_version},
                             headers)

    def withdraw_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/hnw/enrollments/{enrollment_id}/withdraw",
                             headers=headers)

    def decline_enrollment(self, enrollment_id, reason, headers):
        return self._request("POST", f"/hnw/enrollments/{enrollment_id}/decline",
                             {"reason": reason}, headers)

    # ─── Claims ───────────────────────────────────────────────────────────
    def create_claim(self, enrollment_id, payload, headers):
        return self._request("POST", f"/hnw/enrollments/{enrollment_id}/claims",
                             payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/hnw/claims", headers=headers, params=params)

    def list_enrollment_claims(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/hnw/enrollments/{enrollment_id}/claims",
                             headers=headers, params=params)

    def list_property_claims(self, property_id, headers, params=None):
        return self._request("GET", f"/hnw/properties/{property_id}/claims",
                             headers=headers, params=params)

    def review_claim(self, claim_id, headers):
        return self._request("POST", f"/hnw/claims/{claim_id}/review", headers=headers)

    def approve_claim(self, claim_id, headers):
        return self._request("POST", f"/hnw/claims/{claim_id}/approve", headers=headers)

    def settle_claim(self, claim_id, headers):
        return self._request("POST", f"/hnw/claims/{claim_id}/settle", headers=headers)

    def pay_claim(self, claim_id, headers):
        return self._request("POST", f"/hnw/claims/{claim_id}/pay", headers=headers)

    def deny_claim(self, claim_id, reason, headers):
        return self._request("POST", f"/hnw/claims/{claim_id}/deny",
                             {"reason": reason}, headers)

    # ─── Non-renewal notices ──────────────────────────────────────────────
    def create_non_renewal_notice(self, enrollment_id, payload, headers):
        return self._request("POST", f"/hnw/enrollments/{enrollment_id}/non-renewal-notices",
                             payload, headers)

    def list_enrollment_notices(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/hnw/enrollments/{enrollment_id}/non-renewal-notices",
                             headers=headers, params=params)

    def list_property_notices(self, property_id, headers, params=None):
        return self._request("GET", f"/hnw/properties/{property_id}/non-renewal-notices",
                             headers=headers, params=params)

    def list_zone_notices(self, zone_id, headers, params=None):
        return self._request("GET", f"/hnw/risk-zones/{zone_id}/non-renewal-notices",
                             headers=headers, params=params)

    def issue_non_renewal_notice(self, notice_id, headers):
        return self._request("POST", f"/hnw/non-renewal-notices/{notice_id}/issue",
                             headers=headers)

    def rescind_non_renewal_notice(self, notice_id, headers):
        return self._request("POST", f"/hnw/non-renewal-notices/{notice_id}/rescind",
                             headers=headers)

    # ─── Managed-risk letters ─────────────────────────────────────────────
    def list_property_managed_risk_events(self, property_id, headers, params=None):
        return self._request("GET", f"/hnw/properties/{property_id}/managed-risk-events",
                             headers=headers, params=params)

    def list_managed_risk_events(self, headers, params=None):
        return self._request("GET", "/hnw/managed-risk-events", headers=headers, params=params)


api_client = ApiClient()