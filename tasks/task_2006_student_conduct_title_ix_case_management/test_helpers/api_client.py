"""API client: one method per endpoint defined in the PRD endpoint table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- PartyProfile (directory) ----
    def create_party_profile(self, payload, headers):
        return self._request("POST", "/api/party-profiles", payload, headers)

    def list_party_profiles(self, headers, params=None):
        return self._request("GET", "/api/party-profiles", headers=headers, params=params)

    def get_party_profile(self, profile_id, headers):
        return self._request("GET", f"/api/party-profiles/{profile_id}", headers=headers)

    # ---- Case ----
    def create_case(self, payload, headers):
        return self._request("POST", "/api/cases", payload, headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/api/cases", headers=headers, params=params)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/api/cases/{case_id}", headers=headers)

    def begin_jurisdiction_review(self, case_id, headers):
        return self._request("POST", f"/api/cases/{case_id}/begin-jurisdiction-review", headers=headers)

    def confirm_jurisdiction(self, case_id, headers):
        return self._request("POST", f"/api/cases/{case_id}/confirm-jurisdiction", headers=headers)

    def dismiss_case(self, case_id, payload, headers):
        return self._request("POST", f"/api/cases/{case_id}/dismiss", payload, headers)

    def file_formal_complaint(self, case_id, headers):
        return self._request("POST", f"/api/cases/{case_id}/file-formal-complaint", headers=headers)

    def finalize_closure(self, case_id, headers):
        return self._request("POST", f"/api/cases/{case_id}/finalize-closure", headers=headers)

    def resume_case(self, case_id, headers):
        return self._request("POST", f"/api/cases/{case_id}/resume", headers=headers)

    def reconcile_case(self, case_id, headers):
        return self._request("POST", f"/api/cases/{case_id}/reconcile", headers=headers)

    # ---- SupportiveMeasure ----
    def create_supportive_measure(self, case_id, payload, headers):
        return self._request("POST", f"/api/cases/{case_id}/supportive-measures", payload, headers)

    def list_supportive_measures(self, case_id, headers, params=None):
        return self._request("GET", f"/api/cases/{case_id}/supportive-measures", headers=headers, params=params)

    def get_supportive_measure(self, measure_id, headers):
        return self._request("GET", f"/api/supportive-measures/{measure_id}", headers=headers)

    def terminate_supportive_measure(self, measure_id, headers):
        return self._request("POST", f"/api/supportive-measures/{measure_id}/terminate", headers=headers)

    # ---- NoContactDirective ----
    def create_no_contact_directive(self, case_id, payload, headers):
        return self._request("POST", f"/api/cases/{case_id}/no-contact-directives", payload, headers)

    def list_case_directives(self, case_id, headers, params=None):
        return self._request("GET", f"/api/cases/{case_id}/no-contact-directives", headers=headers, params=params)

    def get_no_contact_directive(self, directive_id, headers):
        return self._request("GET", f"/api/no-contact-directives/{directive_id}", headers=headers)

    def list_no_contact_directives(self, headers, params=None):
        return self._request("GET", "/api/no-contact-directives", headers=headers, params=params)

    def lift_no_contact_directive(self, directive_id, headers):
        return self._request("POST", f"/api/no-contact-directives/{directive_id}/lift", headers=headers)

    # ---- DirectiveViolation ----
    def report_violation(self, directive_id, payload, headers):
        return self._request("POST", f"/api/no-contact-directives/{directive_id}/violations", payload, headers)

    def list_violations(self, directive_id, headers, params=None):
        return self._request("GET", f"/api/no-contact-directives/{directive_id}/violations", headers=headers, params=params)

    def get_violation(self, violation_id, headers):
        return self._request("GET", f"/api/directive-violations/{violation_id}", headers=headers)

    def substantiate_violation(self, violation_id, headers):
        return self._request("POST", f"/api/directive-violations/{violation_id}/substantiate", headers=headers)

    def mark_violation_unsubstantiated(self, violation_id, headers):
        return self._request("POST", f"/api/directive-violations/{violation_id}/mark-unsubstantiated", headers=headers)

    # ---- InvestigatorAssignment ----
    def propose_investigator(self, case_id, payload, headers):
        return self._request("POST", f"/api/cases/{case_id}/investigator-assignments", payload, headers)

    def list_case_assignments(self, case_id, headers, params=None):
        return self._request("GET", f"/api/cases/{case_id}/investigator-assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/api/investigator-assignments/{assignment_id}", headers=headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/api/investigator-assignments", headers=headers, params=params)

    def accept_assignment(self, assignment_id, headers):
        return self._request("POST", f"/api/investigator-assignments/{assignment_id}/accept", headers=headers)

    def decline_assignment(self, assignment_id, headers):
        return self._request("POST", f"/api/investigator-assignments/{assignment_id}/decline", headers=headers)

    def recuse_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/api/investigator-assignments/{assignment_id}/recuse", payload, headers)

    # ---- EvidenceItem ----
    def submit_evidence_item(self, case_id, payload, headers):
        return self._request("POST", f"/api/cases/{case_id}/evidence-items", payload, headers)

    def list_evidence_items(self, case_id, headers, params=None):
        return self._request("GET", f"/api/cases/{case_id}/evidence-items", headers=headers, params=params)

    def get_evidence_item(self, item_id, headers):
        return self._request("GET", f"/api/evidence-items/{item_id}", headers=headers)

    def begin_evidence_review(self, item_id, headers):
        return self._request("POST", f"/api/evidence-items/{item_id}/begin-review", headers=headers)

    def rule_evidence_relevance(self, item_id, payload, headers):
        return self._request("POST", f"/api/evidence-items/{item_id}/rule-relevance", payload, headers)

    # ---- EvidencePacket ----
    def create_evidence_packet(self, case_id, payload, headers):
        return self._request("POST", f"/api/cases/{case_id}/evidence-packets", payload, headers)

    def list_evidence_packets(self, case_id, headers, params=None):
        return self._request("GET", f"/api/cases/{case_id}/evidence-packets", headers=headers, params=params)

    def get_evidence_packet(self, packet_id, headers):
        return self._request("GET", f"/api/evidence-packets/{packet_id}", headers=headers)

    def attach_packet_report(self, packet_id, payload, headers):
        return self._request("POST", f"/api/evidence-packets/{packet_id}/attach-report", payload, headers)

    def release_packet(self, packet_id, headers):
        return self._request("POST", f"/api/evidence-packets/{packet_id}/release", headers=headers)

    def submit_review_response(self, packet_id, payload, headers):
        return self._request("POST", f"/api/evidence-packets/{packet_id}/review-responses", payload, headers)

    def finalize_packet(self, packet_id, headers):
        return self._request("POST", f"/api/evidence-packets/{packet_id}/finalize", headers=headers)

    def withdraw_packet(self, packet_id, headers):
        return self._request("POST", f"/api/evidence-packets/{packet_id}/withdraw", headers=headers)

    # ---- Notice ----
    def create_notice(self, case_id, payload, headers):
        return self._request("POST", f"/api/cases/{case_id}/notices", payload, headers)

    def list_case_notices(self, case_id, headers, params=None):
        return self._request("GET", f"/api/cases/{case_id}/notices", headers=headers, params=params)

    def get_notice(self, notice_id, headers):
        return self._request("GET", f"/api/notices/{notice_id}", headers=headers)

    # ---- AdvisorAppointment ----
    def appoint_advisor(self, case_id, payload, headers):
        return self._request("POST", f"/api/cases/{case_id}/advisor-appointments", payload, headers)

    def appoint_university_advisor(self, case_id, payload, headers):
        return self._request("POST", f"/api/cases/{case_id}/advisor-appointments/appoint-university", payload, headers)

    def list_case_advisor_appointments(self, case_id, headers, params=None):
        return self._request("GET", f"/api/cases/{case_id}/advisor-appointments", headers=headers, params=params)

    def get_advisor_appointment(self, appointment_id, headers):
        return self._request("GET", f"/api/advisor-appointments/{appointment_id}", headers=headers)

    def list_advisor_appointments(self, headers, params=None):
        return self._request("GET", "/api/advisor-appointments", headers=headers, params=params)

    def withdraw_advisor_appointment(self, appointment_id, headers):
        return self._request("POST", f"/api/advisor-appointments/{appointment_id}/withdraw", headers=headers)

    # ---- Hearing ----
    def schedule_hearing(self, case_id, payload, headers):
        return self._request("POST", f"/api/cases/{case_id}/hearings", payload, headers)

    def list_case_hearings(self, case_id, headers, params=None):
        return self._request("GET", f"/api/cases/{case_id}/hearings", headers=headers, params=params)

    def get_hearing(self, hearing_id, headers):
        return self._request("GET", f"/api/hearings/{hearing_id}", headers=headers)

    def list_hearings(self, headers, params=None):
        return self._request("GET", "/api/hearings", headers=headers, params=params)

    def convene_hearing(self, hearing_id, headers):
        return self._request("POST", f"/api/hearings/{hearing_id}/convene", headers=headers)

    def adjourn_hearing(self, hearing_id, payload, headers):
        return self._request("POST", f"/api/hearings/{hearing_id}/adjourn", payload, headers)

    def reconvene_hearing(self, hearing_id, headers):
        return self._request("POST", f"/api/hearings/{hearing_id}/reconvene", headers=headers)

    def cancel_hearing(self, hearing_id, headers):
        return self._request("POST", f"/api/hearings/{hearing_id}/cancel", headers=headers)

    def close_cross_exam(self, hearing_id, headers):
        return self._request("POST", f"/api/hearings/{hearing_id}/close-cross-exam", headers=headers)

    # ---- CrossExamQuestion ----
    def ask_cross_exam_question(self, hearing_id, payload, headers):
        return self._request("POST", f"/api/hearings/{hearing_id}/cross-exam-questions", payload, headers)

    def list_cross_exam_questions(self, hearing_id, headers, params=None):
        return self._request("GET", f"/api/hearings/{hearing_id}/cross-exam-questions", headers=headers, params=params)

    def get_cross_exam_question(self, question_id, headers):
        return self._request("GET", f"/api/cross-exam-questions/{question_id}", headers=headers)

    def list_all_cross_exam_questions(self, headers, params=None):
        return self._request("GET", "/api/cross-exam-questions", headers=headers, params=params)

    def rule_cross_exam_question(self, question_id, payload, headers):
        return self._request("POST", f"/api/cross-exam-questions/{question_id}/rule", payload, headers)

    # ---- Determination ----
    def create_determination(self, case_id, payload, headers):
        return self._request("POST", f"/api/cases/{case_id}/determinations", payload, headers)

    def issue_determination(self, determination_id, payload, headers):
        return self._request("POST", f"/api/determinations/{determination_id}/issue", payload, headers)

    def get_determination(self, determination_id, headers):
        return self._request("GET", f"/api/determinations/{determination_id}", headers=headers)

    def list_case_determinations(self, case_id, headers, params=None):
        return self._request("GET", f"/api/cases/{case_id}/determinations", headers=headers, params=params)

    def list_determinations(self, headers, params=None):
        return self._request("GET", "/api/determinations", headers=headers, params=params)

    # ---- Sanction ----
    def list_determination_sanctions(self, determination_id, headers, params=None):
        return self._request("GET", f"/api/determinations/{determination_id}/sanctions", headers=headers, params=params)

    def get_sanction(self, sanction_id, headers):
        return self._request("GET", f"/api/sanctions/{sanction_id}", headers=headers)

    def mark_sanction_complete(self, sanction_id, headers):
        return self._request("POST", f"/api/sanctions/{sanction_id}/mark-complete", headers=headers)

    # ---- Appeal ----
    def file_appeal(self, case_id, payload, headers):
        return self._request("POST", f"/api/cases/{case_id}/appeals", payload, headers)

    def list_case_appeals(self, case_id, headers, params=None):
        return self._request("GET", f"/api/cases/{case_id}/appeals", headers=headers, params=params)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/api/appeals/{appeal_id}", headers=headers)

    def list_appeals(self, headers, params=None):
        return self._request("GET", "/api/appeals", headers=headers, params=params)

    def begin_appeal_review(self, appeal_id, payload, headers):
        return self._request("POST", f"/api/appeals/{appeal_id}/begin-review", payload, headers)

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/api/appeals/{appeal_id}/decide", payload, headers)

    # ---- InformalResolution ----
    def propose_informal_resolution(self, case_id, payload, headers):
        return self._request("POST", f"/api/cases/{case_id}/informal-resolutions", payload, headers)

    def list_case_informal_resolutions(self, case_id, headers, params=None):
        return self._request("GET", f"/api/cases/{case_id}/informal-resolutions", headers=headers, params=params)

    def get_informal_resolution(self, resolution_id, headers):
        return self._request("GET", f"/api/informal-resolutions/{resolution_id}", headers=headers)

    def list_informal_resolutions(self, headers, params=None):
        return self._request("GET", "/api/informal-resolutions", headers=headers, params=params)

    def consent_informal_resolution(self, resolution_id, payload, headers):
        return self._request("POST", f"/api/informal-resolutions/{resolution_id}/consent", payload, headers)

    def withdraw_informal_resolution(self, resolution_id, headers):
        return self._request("POST", f"/api/informal-resolutions/{resolution_id}/withdraw", headers=headers)

    def resolve_informal_resolution(self, resolution_id, payload, headers):
        return self._request("POST", f"/api/informal-resolutions/{resolution_id}/resolve", payload, headers)

    # ---- AnnualStatistic ----
    def get_annual_statistics(self, year, headers):
        return self._request("GET", f"/api/annual-statistics/{year}", headers=headers)

    def publish_annual_statistics(self, year, headers):
        return self._request("POST", f"/api/annual-statistics/{year}/publish", headers=headers)

    def amend_annual_statistics(self, year, headers):
        return self._request("POST", f"/api/annual-statistics/{year}/amend", headers=headers)

    # ---- CaseEvent (audit trail) ----
    def list_case_events(self, case_id, headers, params=None):
        return self._request("GET", f"/api/cases/{case_id}/events", headers=headers, params=params)

    # ---- System / test-driving ----
    def set_logical_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    def run_retention_purge(self, headers):
        return self._request("POST", "/api/records/purge-run", headers=headers)


api_client = ApiClient()
