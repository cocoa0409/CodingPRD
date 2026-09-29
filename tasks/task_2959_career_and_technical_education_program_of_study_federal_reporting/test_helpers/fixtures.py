"""Composite scenario builders.

Most behaviour in this domain only becomes reachable after a long authoring
sequence: a program of study needs a complete course sequence, an approved
credential list, an eligible instructor, an active advisory committee with
documented stakeholder minutes and a certified needs assessment before it can be
submitted, and a passing endorsement vote before the state can approve it. The
builder below performs that sequence once, with named stop points, so that each
test spends its own lines on the rule it is actually about.

Every setup call goes through ``get_success_data``, so a broken precondition
surfaces as a setup failure naming the endpoint rather than as a confusing
assertion deep inside a test.
"""

from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from . import test_users as users
from .api_client import CteApiClient
from .constants import (
    AGENDA_CLNA_STAKEHOLDER,
    AGENDA_POS_ENDORSEMENT,
    CLNA_CERTIFIED,
    CLNA_DATA_COLLECTION,
    CLNA_GAP_ANALYSIS,
    CLNA_STAKEHOLDER_CONSULTATION,
    COURSE_ACTIVE,
    DECISION_CERTIFY,
    ROUTE_INDUSTRY_EXPERIENCE,
    SECTOR_EMPLOYER,
    SECTOR_POSTSECONDARY,
    SOURCE_EMPLOYER_LETTER,
    TIER_NATIONAL,
    VERIFICATION_VERIFIED,
)
from .types import CommitteeScenario, GrantScenario, JsonDict, ProgramScenario, UserIdentity

# Named stop points of the authoring sequence.
STOP_DRAFT = "DRAFT"
STOP_CLNA_CERTIFIED = "CLNA_CERTIFIED"
STOP_SUBMITTED = "SUBMITTED"
STOP_COMMITTEE_REVIEW = "COMMITTEE_REVIEW"
STOP_STATE_APPROVED = "STATE_APPROVED"

_STOP_ORDER = [
    STOP_DRAFT,
    STOP_CLNA_CERTIFIED,
    STOP_SUBMITTED,
    STOP_COMMITTEE_REVIEW,
    STOP_STATE_APPROVED,
]

# Default roster of the advisory committee the builder charters.
DEFAULT_MEMBERS = (
    ("Rosa Vega", SECTOR_EMPLOYER, "EMP-1", True),
    ("Ken Ade", SECTOR_EMPLOYER, "EMP-2", False),
    ("Iris Lund", SECTOR_POSTSECONDARY, "PSE-1", False),
)

DEFAULT_TERM_START = "2026-01-01"
DEFAULT_TERM_END = "2027-12-31"
CLNA_MEETING_INSTANTS = ("2026-08-04T14:00:00.000Z", "2026-08-05T14:00:00.000Z")
ENDORSEMENT_MEETING_INSTANT = "2026-08-10T15:00:00.000Z"
NARRATIVE_URL = "https://district.example/narrative.pdf"


class Builder:
    """Scenario builder bound to one API client."""

    def __init__(self, client: CteApiClient):
        self.client = client

    # ------------------------------------------------------------------
    # Primitives
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601: str, actor: UserIdentity = users.DIRECTOR) -> JsonDict:
        return get_success_data(
            self.client.set_clock(to_iso8601, users.headers(actor))
        )

    def program_version(
        self, program_id: str, actor: UserIdentity = users.DIRECTOR
    ) -> int:
        program = get_success_data(
            self.client.get_program(program_id, users.headers(actor))
        )
        return program["version"]

    def grant_version(
        self, grant_id: str, actor: UserIdentity = users.FISCAL_OFFICER
    ) -> int:
        grant = get_success_data(self.client.get_grant(grant_id, users.headers(actor)))
        return grant["version"]

    # ------------------------------------------------------------------
    # ProgramOfStudy pieces
    # ------------------------------------------------------------------
    def create_program(
        self,
        cip_code: str,
        director: UserIdentity = users.DIRECTOR,
        **kwargs: Any,
    ) -> JsonDict:
        return get_success_data(
            self.client.create_program(
                f.program_payload(cip_code, **kwargs), users.headers(director)
            )
        )

    def add_course(
        self, program_id: str, payload: JsonDict, director: UserIdentity = users.DIRECTOR
    ) -> JsonDict:
        return get_success_data(
            self.client.create_course(program_id, payload, users.headers(director))
        )

    def add_credential(
        self,
        program_id: str,
        code: str,
        tier: str = TIER_NATIONAL,
        director: UserIdentity = users.DIRECTOR,
        **kwargs: Any,
    ) -> JsonDict:
        return get_success_data(
            self.client.create_credential(
                program_id,
                f.credential_payload(code, tier=tier, **kwargs),
                users.headers(director),
            )
        )

    def add_educator(
        self,
        program_id: str,
        full_name: str = "Dana Reyes",
        certification_route: str = ROUTE_INDUSTRY_EXPERIENCE,
        claimed_industry_hours: int = 4200,
        credential_expires_on: str = "2029-06-30",
        director: UserIdentity = users.DIRECTOR,
    ) -> JsonDict:
        return get_success_data(
            self.client.assign_educator(
                program_id,
                f.educator_payload(
                    full_name,
                    certification_route,
                    claimed_industry_hours,
                    credential_expires_on,
                ),
                users.headers(director),
            )
        )

    def verify_hours(
        self,
        educator_id: str,
        verified_hours: int,
        verification_source: str = SOURCE_EMPLOYER_LETTER,
        reviewer: UserIdentity = users.REVIEWER,
    ) -> JsonDict:
        return get_success_data(
            self.client.verify_industry_hours(
                educator_id,
                f.verification_payload(verified_hours, verification_source),
                users.headers(reviewer),
            )
        )

    # ------------------------------------------------------------------
    # Advisory committee pieces
    # ------------------------------------------------------------------
    def charter_committee(
        self,
        program_id: str,
        expected_version: Optional[int] = None,
        director: UserIdentity = users.DIRECTOR,
        **kwargs: Any,
    ) -> JsonDict:
        version = (
            expected_version
            if expected_version is not None
            else self.program_version(program_id, director)
        )
        return get_success_data(
            self.client.charter_committee(
                program_id,
                f.committee_payload(version, **kwargs),
                users.headers(director),
            )
        )

    def seat_member(
        self,
        committee_id: str,
        full_name: str,
        sector: str,
        seat_code: str,
        term_start_on: str = DEFAULT_TERM_START,
        term_end_on: str = DEFAULT_TERM_END,
        is_chair: Any = f.UNSET,
        director: UserIdentity = users.DIRECTOR,
    ) -> JsonDict:
        return get_success_data(
            self.client.seat_member(
                committee_id,
                f.member_payload(
                    full_name,
                    sector,
                    seat_code,
                    term_start_on=term_start_on,
                    term_end_on=term_end_on,
                    is_chair=is_chair,
                ),
                users.headers(director),
            )
        )

    def seat_roster(
        self,
        committee_id: str,
        roster: Sequence[Any] = DEFAULT_MEMBERS,
        term_start_on: str = DEFAULT_TERM_START,
        term_end_on: str = DEFAULT_TERM_END,
        director: UserIdentity = users.DIRECTOR,
    ) -> CommitteeScenario:
        member_ids: List[str] = []
        chair_id = ""
        for full_name, sector, seat_code, is_chair in roster:
            member = self.seat_member(
                committee_id,
                full_name,
                sector,
                seat_code,
                term_start_on=term_start_on,
                term_end_on=term_end_on,
                is_chair=True if is_chair else f.UNSET,
                director=director,
            )
            member_ids.append(member["id"])
            if is_chair:
                chair_id = member["id"]
        return CommitteeScenario(
            committee_id=committee_id,
            chair_member_id=chair_id,
            member_ids=member_ids,
            chair=users.chair_identity(chair_id) if chair_id else None,
        )

    def schedule_meeting(
        self,
        committee_id: str,
        chair_member_id: str,
        agenda_kind: str,
        scheduled_for: str,
    ) -> JsonDict:
        return get_success_data(
            self.client.schedule_meeting(
                committee_id,
                f.meeting_payload(agenda_kind, scheduled_for),
                users.chair_headers(chair_member_id),
            )
        )

    def file_minutes(
        self,
        meeting_id: str,
        chair_member_id: str,
        held_at: str,
        attendee_member_ids: Sequence[str],
        vote_yes: int,
        vote_no: int,
        minutes_url: str = "https://district.example/minutes.pdf",
        amendment_reason: Any = f.UNSET,
    ) -> JsonDict:
        return get_success_data(
            self.client.file_minutes(
                meeting_id,
                f.minutes_payload(
                    held_at,
                    attendee_member_ids,
                    vote_yes,
                    vote_no,
                    minutes_url=minutes_url,
                    amendment_reason=amendment_reason,
                ),
                users.chair_headers(chair_member_id),
            )
        )

    def quorate_meeting(
        self,
        committee: CommitteeScenario,
        agenda_kind: str,
        scheduled_for: str,
        vote_yes: Optional[int] = None,
        vote_no: int = 0,
        minutes_url: str = "https://district.example/minutes.pdf",
    ) -> JsonDict:
        """Schedule a meeting and file passing minutes with the full roster."""
        meeting = self.schedule_meeting(
            committee.committee_id, committee.chair_member_id, agenda_kind, scheduled_for
        )
        yes = len(committee.member_ids) if vote_yes is None else vote_yes
        self.file_minutes(
            meeting["id"],
            committee.chair_member_id,
            scheduled_for,
            committee.member_ids,
            yes,
            vote_no,
            minutes_url=minutes_url,
        )
        return meeting

    # ------------------------------------------------------------------
    # Needs assessment and approval
    # ------------------------------------------------------------------
    def advance_clna(
        self,
        program_id: str,
        to_phase: str,
        actor: UserIdentity = users.DIRECTOR,
        evidence_url: Any = f.UNSET,
    ) -> JsonDict:
        return get_success_data(
            self.client.advance_clna(
                program_id,
                f.clna_advance_payload(to_phase, evidence_url=evidence_url),
                users.headers(actor),
            )
        )

    def certify_clna(
        self,
        program_id: str,
        director: UserIdentity = users.DIRECTOR,
        certifier: UserIdentity = users.REVIEWER,
    ) -> JsonDict:
        """Walk the four declared phases, certifying under a second operator."""
        self.advance_clna(program_id, CLNA_DATA_COLLECTION, director)
        self.advance_clna(program_id, CLNA_STAKEHOLDER_CONSULTATION, director)
        self.advance_clna(program_id, CLNA_GAP_ANALYSIS, director)
        return self.advance_clna(program_id, CLNA_CERTIFIED, certifier)

    def submit(
        self,
        program_id: str,
        director: UserIdentity = users.DIRECTOR,
        narrative_url: str = NARRATIVE_URL,
    ) -> JsonDict:
        return get_success_data(
            self.client.submit_program(
                program_id, f.submit_payload(narrative_url), users.headers(director)
            )
        )

    def request_changes(
        self,
        program_id: str,
        finding_codes: Sequence[str],
        reviewer: UserIdentity = users.REVIEWER,
        note: Any = f.UNSET,
    ) -> JsonDict:
        return get_success_data(
            self.client.request_changes(
                program_id,
                f.request_changes_payload(finding_codes, note=note),
                users.headers(reviewer),
            )
        )

    def state_approve(
        self, program_id: str, reviewer: UserIdentity = users.REVIEWER, **kwargs: Any
    ) -> JsonDict:
        return get_success_data(
            self.client.state_approve(
                program_id, f.state_approve_payload(**kwargs), users.headers(reviewer)
            )
        )

    # ------------------------------------------------------------------
    # The full authoring sequence
    # ------------------------------------------------------------------
    def program(
        self,
        cip_code: str,
        stop_at: str = STOP_STATE_APPROVED,
        director: UserIdentity = users.DIRECTOR,
        reviewer: UserIdentity = users.REVIEWER,
        title: str = "Program Of Study",
        cluster: Optional[str] = None,
        labor_market_data_asof: str = "2026-03-01",
        secondary_code: str = "SEC-1",
        secondary_credit_hours: float = 4.0,
        postsecondary_code: str = "PSE-9",
        postsecondary_credit_hours: float = 3.0,
        articulated_credit_hours: float = 3.0,
        articulation_verified: bool = True,
        credential_code: str = "CRED-1",
        credential_tier: str = TIER_NATIONAL,
        educator_route: str = ROUTE_INDUSTRY_EXPERIENCE,
        claimed_industry_hours: int = 4200,
        verified_industry_hours: int = 4200,
        credential_expires_on: str = "2029-06-30",
        quorum_min_members: int = 3,
        employer_seat_min: int = 2,
        roster: Sequence[Any] = DEFAULT_MEMBERS,
        term_start_on: str = DEFAULT_TERM_START,
        term_end_on: str = DEFAULT_TERM_END,
        narrative_url: str = NARRATIVE_URL,
    ) -> ProgramScenario:
        """Author a program of study up to the named stop point."""
        assert stop_at in _STOP_ORDER, f"Unknown stop point {stop_at!r}"
        target = _STOP_ORDER.index(stop_at)

        kwargs: Dict[str, Any] = {
            "title": title,
            "labor_market_data_asof": labor_market_data_asof,
        }
        if cluster is not None:
            kwargs["cluster"] = cluster
        program = self.create_program(cip_code, director, **kwargs)
        program_id = program["id"]

        scenario = ProgramScenario(
            program_id=program_id,
            cip_code=cip_code,
            version=program["version"],
            director=director,
            reviewer=reviewer,
            registrar=users.REGISTRAR,
            fiscal_officer=users.FISCAL_OFFICER,
        )
        if target == 0:
            return scenario

        secondary = self.add_course(
            program_id,
            f.secondary_course(secondary_code, 1, secondary_credit_hours, status=COURSE_ACTIVE),
            director,
        )
        postsecondary = self.add_course(
            program_id,
            f.postsecondary_course(
                postsecondary_code,
                2,
                postsecondary_credit_hours,
                articulated_credit_hours,
                articulation_verified,
                status=COURSE_ACTIVE,
                prerequisite_course_id=secondary["id"],
            ),
            director,
        )
        credential = self.add_credential(
            program_id, credential_code, tier=credential_tier, director=director
        )
        educator = self.add_educator(
            program_id,
            certification_route=educator_route,
            claimed_industry_hours=claimed_industry_hours,
            credential_expires_on=credential_expires_on,
            director=director,
        )
        if verified_industry_hours > 0:
            self.verify_hours(educator["id"], verified_industry_hours, reviewer=reviewer)

        committee_row = self.charter_committee(
            program_id,
            director=director,
            quorum_min_members=quorum_min_members,
            employer_seat_min=employer_seat_min,
        )
        committee = self.seat_roster(
            committee_row["id"],
            roster,
            term_start_on=term_start_on,
            term_end_on=term_end_on,
            director=director,
        )

        clna_meeting_ids = []
        for instant in CLNA_MEETING_INSTANTS:
            meeting = self.quorate_meeting(
                committee, AGENDA_CLNA_STAKEHOLDER, instant
            )
            clna_meeting_ids.append(meeting["id"])

        self.certify_clna(program_id, director=director, certifier=reviewer)

        scenario.secondary_course_id = secondary["id"]
        scenario.postsecondary_course_id = postsecondary["id"]
        scenario.credential_id = credential["id"]
        scenario.educator_id = educator["id"]
        scenario.committee = committee
        scenario.clna_meeting_ids = clna_meeting_ids
        scenario.version = self.program_version(program_id, director)
        if target == 1:
            return scenario

        self.submit(program_id, director, narrative_url)
        scenario.version = self.program_version(program_id, director)
        if target == 2:
            return scenario

        endorsement = self.quorate_meeting(
            committee, AGENDA_POS_ENDORSEMENT, ENDORSEMENT_MEETING_INSTANT
        )
        scenario.endorsement_meeting_id = endorsement["id"]
        scenario.version = self.program_version(program_id, director)
        if target == 3:
            return scenario

        self.state_approve(program_id, reviewer)
        scenario.version = self.program_version(program_id, director)
        return scenario

    # ------------------------------------------------------------------
    # GrantAward and Expenditure
    # ------------------------------------------------------------------
    def grant(
        self,
        fiscal_year: int = 2027,
        allocation_cents: int = 5000000,
        obligation_window_start: str = "2026-07-01",
        obligation_window_end: str = "2027-06-30",
        officer: UserIdentity = users.FISCAL_OFFICER,
    ) -> GrantScenario:
        row = get_success_data(
            self.client.create_grant(
                f.grant_payload(
                    fiscal_year,
                    allocation_cents,
                    obligation_window_start,
                    obligation_window_end,
                ),
                users.headers(officer),
            )
        )
        return GrantScenario(
            grant_id=row["id"],
            fiscal_year=fiscal_year,
            allocation_cents=allocation_cents,
            version=row["version"],
            fiscal_officer=officer,
        )

    def expenditure(
        self,
        grant_id: str,
        program_id: str,
        category: str,
        unit_cost_cents: int,
        quantity: int = 1,
        service_period_start: str = "2026-09-01",
        service_period_end: str = "2026-09-30",
        asset_tag: Any = f.UNSET,
        description: str = "Charge against the federal award",
        director: UserIdentity = users.DIRECTOR,
        expected_version: Optional[int] = None,
    ) -> JsonDict:
        """Request a charge, re-reading the award's version unless one is given.

        Every accepted request advances the award's ``version``, so a fixture that
        files several charges must observe the award again between them.
        """
        version = (
            expected_version
            if expected_version is not None
            else self.grant_version(grant_id)
        )
        return get_success_data(
            self.client.request_expenditure(
                grant_id,
                f.expenditure_payload(
                    program_id,
                    category,
                    unit_cost_cents,
                    quantity,
                    version,
                    service_period_start=service_period_start,
                    service_period_end=service_period_end,
                    description=description,
                    asset_tag=asset_tag,
                ),
                users.headers(director),
            )
        )

    def certify(
        self,
        expenditure_id: str,
        decision: str = DECISION_CERTIFY,
        finding_code: Any = f.UNSET,
        officer: UserIdentity = users.FISCAL_OFFICER,
    ) -> JsonDict:
        return get_success_data(
            self.client.certify_allowability(
                expenditure_id,
                f.certification_payload(decision, finding_code=finding_code),
                users.headers(officer),
            )
        )

    def certified_expenditure(
        self,
        grant_id: str,
        program_id: str,
        category: str,
        unit_cost_cents: int,
        quantity: int = 1,
        officer: UserIdentity = users.FISCAL_OFFICER,
        **kwargs: Any,
    ) -> JsonDict:
        row = self.expenditure(
            grant_id, program_id, category, unit_cost_cents, quantity, **kwargs
        )
        return self.certify(row["id"], officer=officer)

    # ------------------------------------------------------------------
    # Students, credits and attainments
    # ------------------------------------------------------------------
    def enroll(
        self,
        program_id: str,
        state_student_id: str,
        cohort_year: int = 2026,
        registrar: UserIdentity = users.REGISTRAR,
        special_population_codes: Any = f.UNSET,
    ) -> JsonDict:
        return get_success_data(
            self.client.enroll_student(
                program_id,
                f.student_payload(
                    state_student_id,
                    cohort_year,
                    special_population_codes=special_population_codes,
                ),
                users.headers(registrar),
            )
        )

    def post_credit(
        self,
        student_id: str,
        course_id: str,
        credit_delta: float,
        posted_on: str = "2026-07-15",
        registrar: UserIdentity = users.REGISTRAR,
    ) -> JsonDict:
        return get_success_data(
            self.client.post_credit(
                student_id,
                f.credit_posting_payload(course_id, credit_delta, posted_on),
                users.headers(registrar),
            )
        )

    def attain(
        self,
        student_id: str,
        credential_id: str,
        attained_on: str = "2026-07-20",
        verification_status: str = VERIFICATION_VERIFIED,
        exam_score: Any = 88.50,
        actor: UserIdentity = users.REGISTRAR,
    ) -> JsonDict:
        return get_success_data(
            self.client.create_attainment(
                student_id,
                f.attainment_payload(
                    credential_id, attained_on, verification_status, exam_score=exam_score
                ),
                users.headers(actor),
            )
        )

    def cohort(
        self,
        scenario: ProgramScenario,
        size: int,
        verified_count: int = 0,
        credit_delta: float = 2.0,
        cohort_year: int = 2026,
        first_student_number: int = 100000001,
        posted_on: str = "2026-07-15",
        attained_on: str = "2026-07-20",
    ) -> List[JsonDict]:
        """Enroll ``size`` students, credit them, and verify the first few.

        Each student receives ``credit_delta`` credit hours in the program's
        secondary course, which is what carries them over the concentrator
        threshold of PRD 3.6 and into the indicator denominator of PRD 3.8.
        """
        students: List[JsonDict] = []
        for index in range(size):
            student = self.enroll(
                scenario.program_id,
                str(first_student_number + index),
                cohort_year=cohort_year,
                registrar=scenario.registrar or users.REGISTRAR,
            )
            if credit_delta:
                student = self.post_credit(
                    student["id"],
                    scenario.secondary_course_id or "",
                    credit_delta,
                    posted_on=posted_on,
                )
            if index < verified_count:
                self.attain(
                    student["id"],
                    scenario.credential_id or "",
                    attained_on=attained_on,
                    verification_status=VERIFICATION_VERIFIED,
                )
            students.append(student)
        return students

    # ------------------------------------------------------------------
    # Performance indicators and improvement plans
    # ------------------------------------------------------------------
    def indicator(
        self,
        program_id: str,
        indicator_code: str,
        reporting_year: int = 2027,
        baseline_pct: float = 90.0,
        cohort_year: int = 2026,
        reviewer: UserIdentity = users.REVIEWER,
    ) -> JsonDict:
        return get_success_data(
            self.client.open_indicator(
                program_id,
                f.indicator_payload(
                    indicator_code, reporting_year, baseline_pct, cohort_year
                ),
                users.headers(reviewer),
            )
        )

    def offer(
        self,
        indicator_id: str,
        offered_level_pct: float,
        actor: UserIdentity = users.REVIEWER,
        rationale: Any = f.UNSET,
    ) -> JsonDict:
        return get_success_data(
            self.client.table_offer(
                indicator_id,
                f.offer_payload(offered_level_pct, rationale=rationale),
                users.headers(actor),
            )
        )

    def agreed_indicator(
        self,
        program_id: str,
        indicator_code: str,
        offered_level_pct: float,
        reporting_year: int = 2027,
        baseline_pct: float = 90.0,
        cohort_year: int = 2026,
        reviewer: UserIdentity = users.REVIEWER,
        director: UserIdentity = users.DIRECTOR,
    ) -> JsonDict:
        """Open an indicator, let the state offer, and have the district accept."""
        row = self.indicator(
            program_id,
            indicator_code,
            reporting_year=reporting_year,
            baseline_pct=baseline_pct,
            cohort_year=cohort_year,
            reviewer=reviewer,
        )
        self.offer(row["id"], offered_level_pct, actor=reviewer)
        return get_success_data(
            self.client.accept_level(
                row["id"], f.accept_level_payload(), users.headers(director)
            )
        )

    def close_year(
        self,
        indicator_id: str,
        closed_on: str,
        reviewer: UserIdentity = users.REVIEWER,
    ) -> JsonDict:
        return get_success_data(
            self.client.close_reporting_year(
                indicator_id, f.close_year_payload(closed_on), users.headers(reviewer)
            )
        )

    def draft_plan(
        self,
        indicator_id: str,
        milestones: Optional[Sequence[JsonDict]] = None,
        funding_expenditure_id: Any = f.UNSET,
        director: UserIdentity = users.DIRECTOR,
    ) -> JsonDict:
        return get_success_data(
            self.client.draft_plan(
                indicator_id,
                f.plan_payload(
                    milestones if milestones is not None else f.three_milestones(),
                    funding_expenditure_id=funding_expenditure_id,
                ),
                users.headers(director),
            )
        )

    def submit_plan(
        self,
        plan_id: str,
        director: UserIdentity = users.DIRECTOR,
        submission_note: Any = f.UNSET,
    ) -> JsonDict:
        return get_success_data(
            self.client.submit_plan(
                plan_id,
                f.plan_submit_payload(submission_note=submission_note),
                users.headers(director),
            )
        )

    def return_plan(
        self, plan_id: str, return_reason: str, reviewer: UserIdentity = users.REVIEWER
    ) -> JsonDict:
        return get_success_data(
            self.client.return_plan(
                plan_id, f.plan_return_payload(return_reason), users.headers(reviewer)
            )
        )

    def accept_plan(
        self, plan_id: str, reviewer: UserIdentity = users.REVIEWER, **kwargs: Any
    ) -> JsonDict:
        return get_success_data(
            self.client.accept_plan(
                plan_id, f.plan_accept_payload(**kwargs), users.headers(reviewer)
            )
        )

    def miss_twice(
        self,
        indicator_id: str,
        first_closed_on: str = "2027-06-30",
        second_closed_on: str = "2027-07-01",
        reviewer: UserIdentity = users.REVIEWER,
    ) -> JsonDict:
        """Close two reporting years short of target, firing the sanction chain.

        The second miss carries ``consecutive_miss_count`` to the tolerance of 2,
        which is what escalates the indicator and suspends the program (PRD 3.8).
        """
        self.close_year(indicator_id, first_closed_on, reviewer=reviewer)
        return self.close_year(indicator_id, second_closed_on, reviewer=reviewer)
