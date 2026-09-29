"""API client: one method per endpoint defined in the PRD."""

from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

RYHS = "/ryhs"


class ApiClient(GenericApiClient):
    """Endpoint methods for the Runaway & Homeless Youth Services API."""

    # ─── Shelter programs ─────────────────────────────
    def create_shelter_program(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", f"{RYHS}/shelter-programs", payload, headers)

    def list_shelter_programs(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", f"{RYHS}/shelter-programs", headers=headers, params=params)

    def get_shelter_program(self, program_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{RYHS}/shelter-programs/{program_id}", headers=headers)

    def get_compliance_report(self, program_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{RYHS}/shelter-programs/{program_id}/compliance-report", headers=headers
        )

    def create_governance_proposal(self, program_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"{RYHS}/shelter-programs/{program_id}/governance-proposals", payload, headers
        )

    def list_governance_proposals(
        self, program_id: str, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"{RYHS}/shelter-programs/{program_id}/governance-proposals",
            headers=headers,
            params=params,
        )

    # ─── Youths and street outreach ───────────────────
    def create_youth(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", f"{RYHS}/youths", payload, headers)

    def list_youths(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", f"{RYHS}/youths", headers=headers, params=params)

    def get_youth(self, youth_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{RYHS}/youths/{youth_id}", headers=headers)

    def create_outreach_contact(self, youth_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"{RYHS}/youths/{youth_id}/outreach-contacts", payload, headers
        )

    def list_outreach_contacts(
        self, youth_id: str, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"{RYHS}/youths/{youth_id}/outreach-contacts", headers=headers, params=params
        )

    # ─── Safety screening ─────────────────────────────
    def create_safety_screening(self, youth_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"{RYHS}/youths/{youth_id}/safety-screenings", payload, headers
        )

    def list_safety_screenings(
        self, youth_id: str, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"{RYHS}/youths/{youth_id}/safety-screenings", headers=headers, params=params
        )

    def disposition_safety_screening(
        self, screening_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{RYHS}/safety-screenings/{screening_id}/disposition", payload, headers
        )

    # ─── Admissions ───────────────────────────────────
    def create_admission(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", f"{RYHS}/admissions", payload, headers)

    def list_admissions(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", f"{RYHS}/admissions", headers=headers, params=params)

    def get_admission(self, admission_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{RYHS}/admissions/{admission_id}", headers=headers)

    def extend_admission(self, admission_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"{RYHS}/admissions/{admission_id}/extend", payload, headers
        )

    def discharge_admission(self, admission_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"{RYHS}/admissions/{admission_id}/discharge", payload, headers
        )

    # ─── Guardian notifications ───────────────────────
    def list_guardian_notifications(
        self, admission_id: str, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"{RYHS}/admissions/{admission_id}/guardian-notifications",
            headers=headers,
            params=params,
        )

    def record_notification_attempt(
        self, notification_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{RYHS}/guardian-notifications/{notification_id}/attempt", payload, headers
        )

    def resolve_notification(self, notification_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"{RYHS}/guardian-notifications/{notification_id}/resolve", payload, headers
        )

    # ─── Reunification ────────────────────────────────
    def create_reunification_case(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", f"{RYHS}/reunification-cases", payload, headers)

    def get_reunification_case(self, case_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{RYHS}/reunification-cases/{case_id}", headers=headers)

    def list_youth_reunification_cases(
        self, youth_id: str, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"{RYHS}/youths/{youth_id}/reunification-cases", headers=headers, params=params
        )

    def create_mediation_session(self, case_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"{RYHS}/reunification-cases/{case_id}/mediation-sessions", payload, headers
        )

    def list_mediation_sessions(
        self, case_id: str, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"{RYHS}/reunification-cases/{case_id}/mediation-sessions",
            headers=headers,
            params=params,
        )

    def record_mediation_outcome(self, session_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"{RYHS}/mediation-sessions/{session_id}/record-outcome", payload, headers
        )

    def record_home_assessment(self, case_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"{RYHS}/reunification-cases/{case_id}/home-assessment", payload, headers
        )

    def decide_reunification_case(self, case_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"{RYHS}/reunification-cases/{case_id}/decision", payload, headers
        )

    def create_aftercare_contact(self, case_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"{RYHS}/reunification-cases/{case_id}/aftercare-contacts", payload, headers
        )

    # ─── Transitional living ──────────────────────────
    def create_tlp_placement(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", f"{RYHS}/tlp-placements", payload, headers)

    def list_tlp_placements(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", f"{RYHS}/tlp-placements", headers=headers, params=params)

    def get_tlp_placement(self, placement_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{RYHS}/tlp-placements/{placement_id}", headers=headers)

    def create_savings_entry(self, placement_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"{RYHS}/tlp-placements/{placement_id}/savings-entries", payload, headers
        )

    def list_savings_entries(
        self, placement_id: str, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"{RYHS}/tlp-placements/{placement_id}/savings-entries",
            headers=headers,
            params=params,
        )

    def create_life_skills_completion(
        self, placement_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{RYHS}/tlp-placements/{placement_id}/life-skills-completions", payload, headers
        )

    def list_life_skills_completions(
        self, placement_id: str, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"{RYHS}/tlp-placements/{placement_id}/life-skills-completions",
            headers=headers,
            params=params,
        )

    def run_compliance_review(self, placement_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{RYHS}/tlp-placements/{placement_id}/compliance-review", {}, headers
        )

    def exit_tlp_placement(self, placement_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"{RYHS}/tlp-placements/{placement_id}/exit", payload, headers
        )

    # ─── Education enrollment ─────────────────────────
    def create_education_enrollment(self, youth_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"{RYHS}/youths/{youth_id}/education-enrollments", payload, headers
        )

    def list_education_enrollments(
        self, youth_id: str, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"{RYHS}/youths/{youth_id}/education-enrollments",
            headers=headers,
            params=params,
        )

    def verify_education_records(self, enrollment_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{RYHS}/education-enrollments/{enrollment_id}/verify-records", {}, headers
        )

    # ─── Governance ───────────────────────────────────
    def get_governance_proposal(self, proposal_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{RYHS}/governance-proposals/{proposal_id}", headers=headers
        )

    def cast_governance_vote(self, proposal_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"{RYHS}/governance-proposals/{proposal_id}/votes", payload, headers
        )

    def list_proposal_votes(
        self, proposal_id: str, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"{RYHS}/governance-proposals/{proposal_id}/votes",
            headers=headers,
            params=params,
        )

    def list_youth_governance_votes(
        self, youth_id: str, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"{RYHS}/youths/{youth_id}/governance-votes", headers=headers, params=params
        )

    def retract_governance_vote(self, vote_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{RYHS}/governance-votes/{vote_id}/retract", {}, headers
        )

    def close_governance_vote(self, proposal_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{RYHS}/governance-proposals/{proposal_id}/close-vote", {}, headers
        )

    # ─── Test-driving operations ──────────────────────
    def set_clock(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_nightly_census(self, headers: Dict[str, str]):
        return self._request("POST", "/_ops/nightly-census", {}, headers)


api_client = ApiClient()
