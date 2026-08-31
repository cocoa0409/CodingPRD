"""API client: one method per endpoint the PRD declares.

Every route is mounted under the `/compliance` prefix; collections are flat
peers under that prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/compliance"


class ApiClient(GenericApiClient):
    # ─── Business units ───────────────────────────────────────────────────

    def create_business_unit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/business-units", payload, headers)

    def get_business_unit(self, unit_id, headers):
        return self._request(
            "GET", f"{PREFIX}/business-units/{unit_id}", headers=headers)

    def list_business_units(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/business-units", headers=headers, params=params)

    def create_exposure_adjustment(self, unit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/business-units/{unit_id}/exposure-adjustments",
            payload, headers)

    # ─── Employees ────────────────────────────────────────────────────────

    def create_employee(self, payload, headers):
        return self._request("POST", f"{PREFIX}/employees", payload, headers)

    def get_employee(self, employee_id, headers):
        return self._request(
            "GET", f"{PREFIX}/employees/{employee_id}", headers=headers)

    def list_employees(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/employees", headers=headers, params=params)

    def grant_clearance(self, employee_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/employees/{employee_id}/clearance-grants",
            payload if payload is not None else {}, headers)

    def revoke_clearance(self, employee_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/employees/{employee_id}/clearance-revocations",
            payload, headers)

    # ─── Training curricula ───────────────────────────────────────────────

    def create_curriculum(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/training-curricula", payload, headers)

    def get_curriculum(self, curriculum_id, headers):
        return self._request(
            "GET", f"{PREFIX}/training-curricula/{curriculum_id}", headers=headers)

    # ─── Training assignments ─────────────────────────────────────────────

    def create_training_assignment(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/training-assignments", payload, headers)

    def get_training_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/training-assignments/{assignment_id}", headers=headers)

    def list_training_assignments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/training-assignments", headers=headers, params=params)

    def start_training(self, assignment_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/training-assignments/{assignment_id}/start",
            payload if payload is not None else {}, headers)

    def complete_training(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/training-assignments/{assignment_id}/completion",
            payload, headers)

    def waive_training(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/training-assignments/{assignment_id}/waiver",
            payload, headers)

    # ─── Trade associations ───────────────────────────────────────────────

    def create_association(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/trade-associations", payload, headers)

    def get_association(self, association_id, headers):
        return self._request(
            "GET", f"{PREFIX}/trade-associations/{association_id}", headers=headers)

    def decide_association(self, association_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/trade-associations/{association_id}/approval",
            payload, headers)

    # ─── Participations ───────────────────────────────────────────────────

    def create_participation(self, payload, headers):
        return self._request("POST", f"{PREFIX}/participations", payload, headers)

    def get_participation(self, participation_id, headers):
        return self._request(
            "GET", f"{PREFIX}/participations/{participation_id}", headers=headers)

    def list_participations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/participations", headers=headers, params=params)

    def submit_participation(self, participation_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/participations/{participation_id}/submission",
            payload if payload is not None else {}, headers)

    def decide_legal_clearance(self, participation_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/participations/{participation_id}/legal-clearance",
            payload, headers)

    def record_business_justification(self, participation_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/participations/{participation_id}/business-justification",
            payload, headers)

    def reinstate_participation(self, participation_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/participations/{participation_id}/reinstatement",
            payload if payload is not None else {}, headers)

    def terminate_participation(self, participation_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/participations/{participation_id}/termination",
            payload, headers)

    # ─── Association meetings ─────────────────────────────────────────────

    def create_meeting(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/association-meetings", payload, headers)

    def get_meeting(self, meeting_id, headers):
        return self._request(
            "GET", f"{PREFIX}/association-meetings/{meeting_id}", headers=headers)

    def list_meetings(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/association-meetings", headers=headers, params=params)

    # ─── Meeting attendances ──────────────────────────────────────────────

    def create_attendance(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/meeting-attendances", payload, headers)

    def get_attendance(self, attendance_id, headers):
        return self._request(
            "GET", f"{PREFIX}/meeting-attendances/{attendance_id}", headers=headers)

    def list_attendances(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/meeting-attendances", headers=headers, params=params)

    def cancel_attendance(self, attendance_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/meeting-attendances/{attendance_id}/cancellation",
            payload, headers)

    def confirm_attendance(self, attendance_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/meeting-attendances/{attendance_id}/attendance-confirmation",
            payload if payload is not None else {}, headers)

    def submit_minutes(self, attendance_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/meeting-attendances/{attendance_id}/minutes",
            payload, headers)

    def review_minutes(self, attendance_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/meeting-attendances/{attendance_id}/minutes-review",
            payload, headers)

    def close_remediation(self, attendance_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/meeting-attendances/{attendance_id}/remediation-closure",
            payload, headers)

    # ─── Competitor contacts ──────────────────────────────────────────────

    def create_contact(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/competitor-contacts", payload, headers)

    def get_contact(self, contact_id, headers):
        return self._request(
            "GET", f"{PREFIX}/competitor-contacts/{contact_id}", headers=headers)

    def list_contacts(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/competitor-contacts", headers=headers, params=params)

    def open_contact_review(self, contact_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/competitor-contacts/{contact_id}/review-opening",
            payload if payload is not None else {}, headers)

    def order_contact_remediation(self, contact_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/competitor-contacts/{contact_id}/remediation-order",
            payload, headers)

    def respond_contact_remediation(self, contact_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/competitor-contacts/{contact_id}/remediation-response",
            payload, headers)

    def clear_contact(self, contact_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/competitor-contacts/{contact_id}/clearance",
            payload, headers)

    def escalate_contact(self, contact_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/competitor-contacts/{contact_id}/escalation",
            payload, headers)

    # ─── Transactions ─────────────────────────────────────────────────────

    def create_transaction(self, payload, headers):
        return self._request("POST", f"{PREFIX}/transactions", payload, headers)

    def get_transaction(self, transaction_id, headers):
        return self._request(
            "GET", f"{PREFIX}/transactions/{transaction_id}", headers=headers)

    def list_transactions(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/transactions", headers=headers, params=params)

    def file_transaction(self, transaction_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/transactions/{transaction_id}/filing",
            payload if payload is not None else {}, headers)

    def clear_transaction(self, transaction_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/transactions/{transaction_id}/clearance",
            payload if payload is not None else {}, headers)

    # ─── HSR analyses ─────────────────────────────────────────────────────

    def create_hsr_analysis(self, payload, headers):
        return self._request("POST", f"{PREFIX}/hsr-analyses", payload, headers)

    def get_hsr_analysis(self, analysis_id, headers):
        return self._request(
            "GET", f"{PREFIX}/hsr-analyses/{analysis_id}", headers=headers)

    def list_hsr_analyses(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/hsr-analyses", headers=headers, params=params)

    # ─── Sites and readiness drills ───────────────────────────────────────

    def create_site(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sites", payload, headers)

    def get_site(self, site_id, headers):
        return self._request("GET", f"{PREFIX}/sites/{site_id}", headers=headers)

    def create_drill(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/readiness-drills", payload, headers)

    def get_drill(self, drill_id, headers):
        return self._request(
            "GET", f"{PREFIX}/readiness-drills/{drill_id}", headers=headers)

    def list_drills(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/readiness-drills", headers=headers, params=params)

    def start_drill(self, drill_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/readiness-drills/{drill_id}/start",
            payload if payload is not None else {}, headers)

    def complete_drill(self, drill_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/readiness-drills/{drill_id}/completion",
            payload, headers)

    def abort_drill(self, drill_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/readiness-drills/{drill_id}/abort", payload, headers)

    # ─── Document audits ──────────────────────────────────────────────────

    def create_document_audit(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/document-audits", payload, headers)

    def get_document_audit(self, audit_id, headers):
        return self._request(
            "GET", f"{PREFIX}/document-audits/{audit_id}", headers=headers)

    def list_document_audits(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/document-audits", headers=headers, params=params)

    def record_audit_findings(self, audit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/document-audits/{audit_id}/findings", payload, headers)

    # ─── Leniency applications ────────────────────────────────────────────

    def create_leniency_application(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/leniency-applications", payload, headers)

    def get_leniency_application(self, application_id, headers):
        return self._request(
            "GET", f"{PREFIX}/leniency-applications/{application_id}",
            headers=headers)

    def list_leniency_applications(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/leniency-applications", headers=headers, params=params)

    def request_marker(self, application_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/leniency-applications/{application_id}/marker-request",
            payload if payload is not None else {}, headers)

    def decide_marker(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/leniency-applications/{application_id}/marker-decisions",
            payload, headers)

    def submit_disclosure(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/leniency-applications/{application_id}/disclosure-submission",
            payload, headers)

    def decide_disclosure(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/leniency-applications/{application_id}/disclosure-decision",
            payload, headers)

    def withdraw_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/leniency-applications/{application_id}/withdrawal",
            payload, headers)

    # ─── Risk assessments ─────────────────────────────────────────────────

    def create_risk_assessment(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/risk-assessments", payload, headers)

    def get_risk_assessment(self, assessment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/risk-assessments/{assessment_id}", headers=headers)

    def list_risk_assessments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/risk-assessments", headers=headers, params=params)

    # ─── Logical clock ────────────────────────────────────────────────────

    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
