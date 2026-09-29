"""One method per endpoint of the CTE Program of Study & Federal Reporting API.

Every method returns the raw ``requests.Response`` so that a test can assert on
the HTTP status as well as the envelope. Query filters are passed through as a
plain mapping; callers build them with the helpers in ``factories``.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import (
    ADVISORY_COMMITTEES,
    CLOCK_SET,
    COMMITTEE_MEETINGS,
    COMMITTEE_MEMBERS,
    CREDENTIAL_ATTAINMENTS,
    CREDENTIALS,
    EDUCATORS,
    EXPENDITURES,
    GRANT_AWARDS,
    IMPROVEMENT_PLANS,
    PERFORMANCE_INDICATORS,
    PROGRAMS,
    SEQUENCE_COURSES,
    STUDENTS,
)
from .types import Headers, JsonDict


class CteApiClient(GenericApiClient):
    """Endpoint surface of the CTE API."""

    # ------------------------------------------------------------------
    # Escape hatches for shape probes that must bypass the typed helpers
    # ------------------------------------------------------------------
    def raw_get(
        self,
        path: str,
        headers: Optional[Headers] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", path, headers=headers, params=params)

    def raw_post(
        self,
        path: str,
        payload: Optional[JsonDict] = None,
        headers: Optional[Headers] = None,
    ) -> requests.Response:
        return self._request("POST", path, payload=payload, headers=headers)

    def raw_patch(
        self,
        path: str,
        payload: Optional[JsonDict] = None,
        headers: Optional[Headers] = None,
    ) -> requests.Response:
        return self._request("PATCH", path, payload=payload, headers=headers)

    # ------------------------------------------------------------------
    # Logical clock (PRD 2.5)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST", CLOCK_SET, payload={"to_iso8601": to_iso8601}, headers=headers
        )

    # ------------------------------------------------------------------
    # ProgramOfStudy (PRD 3.1, 3.2, 3.4)
    # ------------------------------------------------------------------
    def create_program(self, payload: JsonDict, headers: Headers) -> requests.Response:
        return self._request("POST", PROGRAMS, payload=payload, headers=headers)

    def list_programs(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", PROGRAMS, headers=headers, params=params)

    def get_program(self, program_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{PROGRAMS}/{program_id}", headers=headers)

    def patch_program(
        self, program_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "PATCH", f"{PROGRAMS}/{program_id}", payload=payload, headers=headers
        )

    def advance_clna(
        self, program_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PROGRAMS}/{program_id}/clna-advance",
            payload=payload,
            headers=headers,
        )

    def submit_program(
        self, program_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{PROGRAMS}/{program_id}/submit", payload=payload, headers=headers
        )

    def request_changes(
        self, program_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PROGRAMS}/{program_id}/request-changes",
            payload=payload,
            headers=headers,
        )

    def state_approve(
        self, program_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PROGRAMS}/{program_id}/state-approve",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # SequenceCourse (PRD 3.1)
    # ------------------------------------------------------------------
    def create_course(
        self, program_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PROGRAMS}/{program_id}/sequence-courses",
            payload=payload,
            headers=headers,
        )

    def list_program_courses(
        self,
        program_id: str,
        headers: Headers,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PROGRAMS}/{program_id}/sequence-courses",
            headers=headers,
            params=params,
        )

    def get_course(self, course_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{SEQUENCE_COURSES}/{course_id}", headers=headers)

    def patch_course(
        self, course_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "PATCH",
            f"{SEQUENCE_COURSES}/{course_id}",
            payload=payload,
            headers=headers,
        )

    def list_course_dependents(
        self, course_id: str, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{SEQUENCE_COURSES}/{course_id}/dependents",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Credential (PRD 3.1)
    # ------------------------------------------------------------------
    def create_credential(
        self, program_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PROGRAMS}/{program_id}/credentials",
            payload=payload,
            headers=headers,
        )

    def list_program_credentials(
        self, program_id: str, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PROGRAMS}/{program_id}/credentials",
            headers=headers,
            params=params,
        )

    def get_credential(self, credential_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{CREDENTIALS}/{credential_id}", headers=headers)

    # ------------------------------------------------------------------
    # Student, credit postings, exits and attainments (PRD 3.6)
    # ------------------------------------------------------------------
    def enroll_student(
        self, program_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PROGRAMS}/{program_id}/students",
            payload=payload,
            headers=headers,
        )

    def list_program_students(
        self, program_id: str, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PROGRAMS}/{program_id}/students", headers=headers, params=params
        )

    def get_student(self, student_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{STUDENTS}/{student_id}", headers=headers)

    def post_credit(
        self, student_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{STUDENTS}/{student_id}/credit-postings",
            payload=payload,
            headers=headers,
        )

    def exit_student(
        self, student_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{STUDENTS}/{student_id}/exit", payload=payload, headers=headers
        )

    def create_attainment(
        self, student_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{STUDENTS}/{student_id}/credential-attainments",
            payload=payload,
            headers=headers,
        )

    def list_attainments(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", CREDENTIAL_ATTAINMENTS, headers=headers, params=params
        )

    def get_attainment(self, attainment_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{CREDENTIAL_ATTAINMENTS}/{attainment_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # AdvisoryCommittee, members and meetings (PRD 3.3)
    # ------------------------------------------------------------------
    def charter_committee(
        self, program_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PROGRAMS}/{program_id}/advisory-committees",
            payload=payload,
            headers=headers,
        )

    def list_program_committees(
        self, program_id: str, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PROGRAMS}/{program_id}/advisory-committees",
            headers=headers,
            params=params,
        )

    def get_committee(self, committee_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{ADVISORY_COMMITTEES}/{committee_id}", headers=headers
        )

    def seat_member(
        self, committee_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{ADVISORY_COMMITTEES}/{committee_id}/members",
            payload=payload,
            headers=headers,
        )

    def list_committee_members(
        self,
        committee_id: str,
        headers: Headers,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{ADVISORY_COMMITTEES}/{committee_id}/members",
            headers=headers,
            params=params,
        )

    def get_member(self, member_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{COMMITTEE_MEMBERS}/{member_id}", headers=headers)

    def schedule_meeting(
        self, committee_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{ADVISORY_COMMITTEES}/{committee_id}/meetings",
            payload=payload,
            headers=headers,
        )

    def list_committee_meetings(
        self,
        committee_id: str,
        headers: Headers,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{ADVISORY_COMMITTEES}/{committee_id}/meetings",
            headers=headers,
            params=params,
        )

    def get_meeting(self, meeting_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{COMMITTEE_MEETINGS}/{meeting_id}", headers=headers
        )

    def file_minutes(
        self, meeting_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{COMMITTEE_MEETINGS}/{meeting_id}/minutes",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # GrantAward and Expenditure (PRD 3.7)
    # ------------------------------------------------------------------
    def create_grant(self, payload: JsonDict, headers: Headers) -> requests.Response:
        return self._request("POST", GRANT_AWARDS, payload=payload, headers=headers)

    def list_grants(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", GRANT_AWARDS, headers=headers, params=params)

    def get_grant(self, grant_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{GRANT_AWARDS}/{grant_id}", headers=headers)

    def request_expenditure(
        self, grant_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{GRANT_AWARDS}/{grant_id}/expenditures",
            payload=payload,
            headers=headers,
        )

    def list_grant_expenditures(
        self, grant_id: str, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{GRANT_AWARDS}/{grant_id}/expenditures",
            headers=headers,
            params=params,
        )

    def list_program_expenditures(
        self, program_id: str, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PROGRAMS}/{program_id}/expenditures",
            headers=headers,
            params=params,
        )

    def get_expenditure(
        self, expenditure_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"{EXPENDITURES}/{expenditure_id}", headers=headers
        )

    def certify_allowability(
        self, expenditure_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{EXPENDITURES}/{expenditure_id}/certify-allowability",
            payload=payload,
            headers=headers,
        )

    def obligate_expenditure(
        self, expenditure_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{EXPENDITURES}/{expenditure_id}/obligate",
            payload=payload,
            headers=headers,
        )

    def void_expenditure(
        self, expenditure_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{EXPENDITURES}/{expenditure_id}/void",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Educator (PRD 3.5)
    # ------------------------------------------------------------------
    def assign_educator(
        self, program_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PROGRAMS}/{program_id}/educators",
            payload=payload,
            headers=headers,
        )

    def list_program_educators(
        self, program_id: str, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PROGRAMS}/{program_id}/educators", headers=headers, params=params
        )

    def get_educator(self, educator_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{EDUCATORS}/{educator_id}", headers=headers)

    def verify_industry_hours(
        self, educator_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{EDUCATORS}/{educator_id}/verify-industry-hours",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # PerformanceIndicator (PRD 3.8)
    # ------------------------------------------------------------------
    def open_indicator(
        self, program_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PROGRAMS}/{program_id}/performance-indicators",
            payload=payload,
            headers=headers,
        )

    def list_program_indicators(
        self, program_id: str, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PROGRAMS}/{program_id}/performance-indicators",
            headers=headers,
            params=params,
        )

    def get_indicator(self, indicator_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{PERFORMANCE_INDICATORS}/{indicator_id}", headers=headers
        )

    def table_offer(
        self, indicator_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PERFORMANCE_INDICATORS}/{indicator_id}/negotiation-offers",
            payload=payload,
            headers=headers,
        )

    def accept_level(
        self, indicator_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PERFORMANCE_INDICATORS}/{indicator_id}/accept-level",
            payload=payload,
            headers=headers,
        )

    def close_reporting_year(
        self, indicator_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PERFORMANCE_INDICATORS}/{indicator_id}/close-reporting-year",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # ImprovementPlan (PRD 3.9)
    # ------------------------------------------------------------------
    def draft_plan(
        self, indicator_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PERFORMANCE_INDICATORS}/{indicator_id}/improvement-plans",
            payload=payload,
            headers=headers,
        )

    def list_plans(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", IMPROVEMENT_PLANS, headers=headers, params=params)

    def get_plan(self, plan_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{IMPROVEMENT_PLANS}/{plan_id}", headers=headers)

    def submit_plan(
        self, plan_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{IMPROVEMENT_PLANS}/{plan_id}/submit",
            payload=payload,
            headers=headers,
        )

    def return_plan(
        self, plan_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{IMPROVEMENT_PLANS}/{plan_id}/return",
            payload=payload,
            headers=headers,
        )

    def accept_plan(
        self, plan_id: str, payload: JsonDict, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{IMPROVEMENT_PLANS}/{plan_id}/accept",
            payload=payload,
            headers=headers,
        )
