"""API client: one method per endpoint in the PRD endpoint surface."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── test-driving capabilities ───────────────────────────────────────────
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_checkpoint(self, payload, headers):
        return self._request("POST", "/_ops/run-checkpoint", payload, headers)

    # ─── research funds ──────────────────────────────────────────────────────
    def create_fund(self, payload, headers):
        return self._request("POST", "/programs/research-funds", payload, headers)

    def list_funds(self, headers, params=None):
        return self._request("GET", "/programs/research-funds", headers=headers, params=params)

    def get_fund(self, fund_id, headers):
        return self._request("GET", f"/programs/research-funds/{fund_id}", headers=headers)

    def record_donation(self, fund_id, payload, headers):
        return self._request("POST", f"/programs/research-funds/{fund_id}/donations", payload, headers)

    def list_fund_services(self, fund_id, headers, params=None):
        return self._request("GET", f"/programs/research-funds/{fund_id}/services", headers=headers, params=params)

    # ─── clinical protocols ──────────────────────────────────────────────────
    def create_protocol(self, payload, headers):
        return self._request("POST", "/programs/clinical-protocols", payload, headers)

    def list_protocols(self, headers, params=None):
        return self._request("GET", "/programs/clinical-protocols", headers=headers, params=params)

    def get_protocol(self, protocol_id, headers):
        return self._request("GET", f"/programs/clinical-protocols/{protocol_id}", headers=headers)

    def open_protocol(self, protocol_id, headers, payload=None):
        return self._request("POST", f"/programs/clinical-protocols/{protocol_id}/open", payload or {}, headers)

    def close_protocol(self, protocol_id, payload, headers):
        return self._request("POST", f"/programs/clinical-protocols/{protocol_id}/close", payload, headers)

    def release_hold_via_protocol(self, protocol_id, headers, payload=None):
        return self._request("POST", f"/programs/clinical-protocols/{protocol_id}/release-hold", payload or {}, headers)

    def get_funding_posture(self, protocol_id, headers):
        return self._request("GET", f"/programs/clinical-protocols/{protocol_id}/funding-posture", headers=headers)

    def list_protocol_referrals(self, protocol_id, headers, params=None):
        return self._request("GET", f"/programs/clinical-protocols/{protocol_id}/referrals", headers=headers, params=params)

    def list_protocol_studies(self, protocol_id, headers, params=None):
        return self._request("GET", f"/programs/clinical-protocols/{protocol_id}/studies", headers=headers, params=params)

    def list_protocol_holds(self, protocol_id, headers, params=None):
        return self._request("GET", f"/programs/clinical-protocols/{protocol_id}/holds", headers=headers, params=params)

    def raise_hold(self, protocol_id, payload, headers):
        return self._request("POST", f"/programs/clinical-protocols/{protocol_id}/holds", payload, headers)

    def list_protocol_affiliations(self, protocol_id, headers, params=None):
        return self._request("GET", f"/programs/clinical-protocols/{protocol_id}/affiliations", headers=headers, params=params)

    def create_study(self, protocol_id, payload, headers):
        return self._request("POST", f"/programs/clinical-protocols/{protocol_id}/studies", payload, headers)

    # ─── protocol holds ──────────────────────────────────────────────────────
    def release_hold(self, hold_id, headers, payload=None):
        return self._request("POST", f"/programs/protocol-holds/{hold_id}/release", payload or {}, headers)

    def escalate_hold(self, hold_id, headers, payload=None):
        return self._request("POST", f"/programs/protocol-holds/{hold_id}/escalate", payload or {}, headers)

    def list_holds(self, headers, params=None):
        return self._request("GET", "/programs/protocol-holds", headers=headers, params=params)

    # ─── referrals ───────────────────────────────────────────────────────────
    def create_referral(self, payload, headers):
        return self._request("POST", "/programs/referrals", payload, headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/programs/referrals", headers=headers, params=params)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/programs/referrals/{referral_id}", headers=headers)

    def screen_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/programs/referrals/{referral_id}/screen", payload, headers)

    def arrive_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/programs/referrals/{referral_id}/arrive", payload, headers)

    def withdraw_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/programs/referrals/{referral_id}/withdraw", payload, headers)

    def list_referral_enrollments(self, referral_id, headers, params=None):
        return self._request("GET", f"/programs/referrals/{referral_id}/enrollments", headers=headers, params=params)

    def get_one_to_one_summary(self, referral_id, headers):
        return self._request("GET", f"/programs/referrals/{referral_id}/one-to-one-summary", headers=headers)

    def list_referral_reopens(self, referral_id, headers, params=None):
        return self._request("GET", f"/programs/referrals/{referral_id}/reopens", headers=headers, params=params)

    # ─── housing facilities ──────────────────────────────────────────────────
    def create_facility(self, payload, headers):
        return self._request("POST", "/programs/housing-facilities", payload, headers)

    def list_facilities(self, headers, params=None):
        return self._request("GET", "/programs/housing-facilities", headers=headers, params=params)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/programs/housing-facilities/{facility_id}", headers=headers)

    def list_facility_assignments(self, facility_id, headers, params=None):
        return self._request("GET", f"/programs/housing-facilities/{facility_id}/assignments", headers=headers, params=params)

    def suspend_facility(self, facility_id, payload, headers):
        return self._request("POST", f"/programs/housing-facilities/{facility_id}/suspend", payload, headers)

    def close_facility(self, facility_id, payload, headers):
        return self._request("POST", f"/programs/housing-facilities/{facility_id}/close", payload, headers)

    def reopen_facility(self, facility_id, headers, payload=None):
        return self._request("POST", f"/programs/housing-facilities/{facility_id}/reopen", payload or {}, headers)

    # ─── housing assignments ─────────────────────────────────────────────────
    def create_assignment(self, payload, headers):
        return self._request("POST", "/programs/housing-assignments", payload, headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/programs/housing-assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/programs/housing-assignments/{assignment_id}", headers=headers)

    def rebook_assignment(self, assignment_id, payload, headers):
        return self._request("PUT", f"/programs/housing-assignments/{assignment_id}", payload, headers)

    def activate_assignment(self, assignment_id, headers, payload=None):
        return self._request("POST", f"/programs/housing-assignments/{assignment_id}/activate", payload or {}, headers)

    def vacate_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/programs/housing-assignments/{assignment_id}/vacate", payload, headers)

    def cancel_assignment(self, assignment_id, headers, payload=None):
        return self._request("POST", f"/programs/housing-assignments/{assignment_id}/cancel", payload or {}, headers)

    # ─── enrollments ─────────────────────────────────────────────────────────
    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/programs/enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/programs/enrollments/{enrollment_id}", headers=headers)

    def sign_consent(self, enrollment_id, payload, headers):
        return self._request("POST", f"/programs/enrollments/{enrollment_id}/sign-consent", payload, headers)

    def record_arm_assent(self, enrollment_id, payload, headers):
        return self._request("POST", f"/programs/enrollments/{enrollment_id}/record-arm-assent", payload, headers)

    def start_treatment(self, enrollment_id, headers, payload=None):
        return self._request("POST", f"/programs/enrollments/{enrollment_id}/start-treatment", payload or {}, headers)

    def hiatus(self, enrollment_id, payload, headers):
        return self._request("POST", f"/programs/enrollments/{enrollment_id}/hiatus", payload, headers)

    def resume(self, enrollment_id, headers, payload=None):
        return self._request("POST", f"/programs/enrollments/{enrollment_id}/resume", payload or {}, headers)

    def complete_treatment(self, enrollment_id, headers, payload=None):
        return self._request("POST", f"/programs/enrollments/{enrollment_id}/complete-treatment", payload or {}, headers)

    def complete_follow_up(self, enrollment_id, headers, payload=None):
        return self._request("POST", f"/programs/enrollments/{enrollment_id}/complete-follow-up", payload or {}, headers)

    def list_enrollment_pledges(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/programs/enrollments/{enrollment_id}/pledges", headers=headers, params=params)

    def list_enrollment_assignments(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/programs/enrollments/{enrollment_id}/housing-assignments", headers=headers, params=params)

    def list_enrollment_travel(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/programs/enrollments/{enrollment_id}/travel-arrangements", headers=headers, params=params)

    def get_travel_summary(self, enrollment_id, headers):
        return self._request("GET", f"/programs/enrollments/{enrollment_id}/travel-summary", headers=headers)

    def list_enrollment_milestones(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/programs/enrollments/{enrollment_id}/milestones", headers=headers, params=params)

    def list_enrollment_survivorship(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/programs/enrollments/{enrollment_id}/survivorship-enrollments", headers=headers, params=params)

    def list_enrollment_sibling_services(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/programs/enrollments/{enrollment_id}/sibling-services", headers=headers, params=params)

    def create_sibling_service(self, enrollment_id, payload, headers):
        return self._request("POST", f"/programs/enrollments/{enrollment_id}/sibling-services", payload, headers)

    def create_milestone(self, enrollment_id, payload, headers):
        return self._request("POST", f"/programs/enrollments/{enrollment_id}/milestones", payload, headers)

    def request_travel(self, enrollment_id, payload, headers):
        return self._request("POST", f"/programs/enrollments/{enrollment_id}/travel-arrangements", payload, headers)

    # ─── family-support pledges ──────────────────────────────────────────────
    def create_pledge(self, payload, headers):
        return self._request("POST", "/programs/family-support-pledges", payload, headers)

    def list_pledges(self, headers, params=None):
        return self._request("GET", "/programs/family-support-pledges", headers=headers, params=params)

    def get_pledge(self, pledge_id, headers):
        return self._request("GET", f"/programs/family-support-pledges/{pledge_id}", headers=headers)

    def accrue_pledge(self, pledge_id, payload, headers):
        return self._request("POST", f"/programs/family-support-pledges/{pledge_id}/accrue", payload, headers)

    def settle_pledge(self, pledge_id, headers, payload=None):
        return self._request("POST", f"/programs/family-support-pledges/{pledge_id}/settle", payload or {}, headers)

    def void_pledge(self, pledge_id, headers, payload=None):
        return self._request("POST", f"/programs/family-support-pledges/{pledge_id}/void", payload or {}, headers)

    # ─── travel arrangements ─────────────────────────────────────────────────
    def list_travel(self, headers, params=None):
        return self._request("GET", "/programs/travel-arrangements", headers=headers, params=params)

    def get_travel(self, travel_id, headers):
        return self._request("GET", f"/programs/travel-arrangements/{travel_id}", headers=headers)

    def confirm_travel(self, travel_id, headers, payload=None):
        return self._request("POST", f"/programs/travel-arrangements/{travel_id}/confirm", payload or {}, headers)

    def disburse_travel(self, travel_id, headers, payload=None):
        return self._request("POST", f"/programs/travel-arrangements/{travel_id}/disburse", payload or {}, headers)

    def reverse_travel_disbursement(self, travel_id, payload, headers):
        return self._request("POST", f"/programs/travel-arrangements/{travel_id}/reverse-disbursement", payload, headers)

    def cancel_travel(self, travel_id, headers, payload=None):
        return self._request("POST", f"/programs/travel-arrangements/{travel_id}/cancel", payload or {}, headers)

    # ─── affiliate clinics and agreements ────────────────────────────────────
    def create_clinic(self, payload, headers):
        return self._request("POST", "/programs/affiliate-clinics", payload, headers)

    def list_clinics(self, headers, params=None):
        return self._request("GET", "/programs/affiliate-clinics", headers=headers, params=params)

    def get_clinic(self, clinic_id, headers):
        return self._request("GET", f"/programs/affiliate-clinics/{clinic_id}", headers=headers)

    def create_affiliation(self, clinic_id, payload, headers):
        return self._request("POST", f"/programs/affiliate-clinics/{clinic_id}/affiliations", payload, headers)

    def list_clinic_affiliations(self, clinic_id, headers, params=None):
        return self._request("GET", f"/programs/affiliate-clinics/{clinic_id}/affiliations", headers=headers, params=params)

    def list_affiliations(self, headers, params=None):
        return self._request("GET", "/programs/affiliations", headers=headers, params=params)

    def activate_affiliation(self, agreement_id, headers, payload=None):
        return self._request("POST", f"/programs/affiliations/{agreement_id}/activate", payload or {}, headers)

    def terminate_affiliation(self, agreement_id, payload, headers):
        return self._request("POST", f"/programs/affiliations/{agreement_id}/terminate", payload, headers)

    def suspend_affiliation(self, agreement_id, headers, payload=None):
        return self._request("POST", f"/programs/affiliations/{agreement_id}/suspend", payload or {}, headers)

    def list_clinic_milestones(self, clinic_id, headers, params=None):
        return self._request("GET", f"/programs/affiliate-clinics/{clinic_id}/milestones", headers=headers, params=params)

    def list_clinic_protocols(self, clinic_id, headers, params=None):
        return self._request("GET", f"/programs/affiliate-clinics/{clinic_id}/protocols", headers=headers, params=params)

    # ─── milestones ──────────────────────────────────────────────────────────
    def get_milestone(self, milestone_id, headers):
        return self._request("GET", f"/programs/milestones/{milestone_id}", headers=headers)

    def defer_milestone(self, milestone_id, payload, headers):
        return self._request("POST", f"/programs/protocol-milestones/{milestone_id}/defer-visit", payload, headers)

    def execute_milestone(self, milestone_id, headers, payload=None):
        return self._request("POST", f"/programs/protocol-milestones/{milestone_id}/execute", payload or {}, headers)

    def list_protocol_milestones(self, headers, params=None):
        return self._request("GET", "/programs/protocol-milestones", headers=headers, params=params)

    def list_milestones(self, headers, params=None):
        return self._request("GET", "/programs/milestones", headers=headers, params=params)

    # ─── survivorship ────────────────────────────────────────────────────────
    def list_studies(self, headers, params=None):
        return self._request("GET", "/programs/survivorship-studies", headers=headers, params=params)

    def create_survivorship_enrollment(self, study_id, payload, headers):
        return self._request("POST", f"/programs/survivorship-studies/{study_id}/enrollments", payload, headers)

    def list_study_enrollments(self, study_id, headers, params=None):
        return self._request("GET", f"/programs/survivorship-studies/{study_id}/enrollments", headers=headers, params=params)

    def get_survivorship_enrollment(self, survivorship_enrollment_id, headers):
        return self._request("GET", f"/programs/survivorship-enrollments/{survivorship_enrollment_id}", headers=headers)

    def log_follow_up(self, survivorship_enrollment_id, payload, headers):
        return self._request("POST", f"/programs/survivorship-enrollments/{survivorship_enrollment_id}/follow-ups", payload, headers)

    def withdraw_survivorship(self, survivorship_enrollment_id, headers, payload=None):
        return self._request("POST", f"/programs/survivorship-enrollments/{survivorship_enrollment_id}/withdraw", payload or {}, headers)

    def list_follow_ups(self, survivorship_enrollment_id, headers, params=None):
        return self._request("GET", f"/programs/survivorship-enrollments/{survivorship_enrollment_id}/follow-ups", headers=headers, params=params)

    def list_survivorship_enrollments(self, headers, params=None):
        return self._request("GET", "/programs/survivorship-enrollments", headers=headers, params=params)

    # ─── family-support services and ledgers ─────────────────────────────────
    def create_service(self, payload, headers):
        return self._request("POST", "/programs/family-support-services", payload, headers)

    def list_services(self, headers, params=None):
        return self._request("GET", "/programs/family-support-services", headers=headers, params=params)

    def get_service(self, service_id, headers):
        return self._request("GET", f"/programs/family-support-services/{service_id}", headers=headers)

    def accrue_allowance(self, service_id, payload, headers):
        return self._request("POST", f"/programs/family-support-services/{service_id}/allowances", payload, headers)

    def get_ledger(self, ledger_id, headers):
        return self._request("GET", f"/programs/family-service-ledgers/{ledger_id}", headers=headers)

    def freeze_ledger(self, ledger_id, headers, payload=None):
        return self._request("POST", f"/programs/family-service-ledgers/{ledger_id}/freeze", payload or {}, headers)

    def list_service_ledgers(self, service_id, headers, params=None):
        return self._request("GET", f"/programs/family-support-services/{service_id}/ledgers", headers=headers, params=params)

    # ─── sibling support ─────────────────────────────────────────────────────
    def list_sibling_services(self, headers, params=None):
        return self._request("GET", "/programs/sibling-support-services", headers=headers, params=params)

    def get_sibling_service(self, sibling_service_id, headers):
        return self._request("GET", f"/programs/sibling-support-services/{sibling_service_id}", headers=headers)

    def deliver_sibling_sessions(self, sibling_service_id, payload, headers):
        return self._request("POST", f"/programs/sibling-support-services/{sibling_service_id}/sessions", payload, headers)

    def cancel_sibling_service(self, sibling_service_id, headers, payload=None):
        return self._request("POST", f"/programs/sibling-support-services/{sibling_service_id}/cancel", payload or {}, headers)


api_client = ApiClient()