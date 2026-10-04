"""Domain types: entity TypedDicts, status enums and the role enum.

All eleven primary resources carry the same four system-managed properties
(id, created_at, updated_at, version); none of them is immutable after creation,
so every TypedDict below lists all four.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class ClubType(str, Enum):
    COMMUNITY = "COMMUNITY"
    CORPORATE = "CORPORATE"
    CAMPUS = "CAMPUS"
    ADVANCED = "ADVANCED"


class CharterStatus(str, Enum):
    ORGANIZING = "ORGANIZING"
    CHARTERED = "CHARTERED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class GoodStanding(str, Enum):
    GOOD = "GOOD"
    PROBATION = "PROBATION"
    NOT_IN_GOOD_STANDING = "NOT_IN_GOOD_STANDING"


class CoachingStatus(str, Enum):
    NONE = "NONE"
    FLAGGED = "FLAGGED"
    ASSIGNED = "ASSIGNED"
    COACHED = "COACHED"


class DcpTier(str, Enum):
    PRESIDENT_DISTINGUISHED = "PRESIDENT_DISTINGUISHED"
    SELECT_DISTINGUISHED = "SELECT_DISTINGUISHED"
    DISTINGUISHED = "DISTINGUISHED"
    NONE = "NONE"


class MembershipStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"


class DuesStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    VOID = "VOID"


class Office(str, Enum):
    NONE = "NONE"
    PRESIDENT = "PRESIDENT"
    VP_EDUCATION = "VP_EDUCATION"
    VP_MEMBERSHIP = "VP_MEMBERSHIP"
    VP_PUBLIC_RELATIONS = "VP_PUBLIC_RELATIONS"
    SECRETARY = "SECRETARY"
    TREASURER = "TREASURER"
    SERGEANT_AT_ARMS = "SERGEANT_AT_ARMS"


class PathCode(str, Enum):
    DYNAMIC_LEADERSHIP = "DYNAMIC_LEADERSHIP"
    ENGAGING_HUMOR = "ENGAGING_HUMOR"
    PERSUASIVE_INFLUENCE = "PERSUASIVE_INFLUENCE"
    PRESENTATION_MASTERY = "PRESENTATION_MASTERY"
    TEAM_COLLABORATION = "TEAM_COLLABORATION"
    VISIONARY_COMMUNICATION = "VISIONARY_COMMUNICATION"


class PathLevel(str, Enum):
    LEVEL_1 = "LEVEL_1"
    LEVEL_2 = "LEVEL_2"
    LEVEL_3 = "LEVEL_3"
    LEVEL_4 = "LEVEL_4"
    LEVEL_5 = "LEVEL_5"
    COMPLETED = "COMPLETED"


class PathStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ProjectKind(str, Enum):
    SPEECH = "SPEECH"
    EVALUATION = "EVALUATION"
    LEADERSHIP = "LEADERSHIP"


class CompletionStatus(str, Enum):
    LOGGED = "LOGGED"
    EVALUATED = "EVALUATED"
    APPROVED = "APPROVED"
    RETURNED = "RETURNED"


class MeetingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    CANCELLED = "CANCELLED"


class RoleCode(str, Enum):
    TOASTMASTER = "TOASTMASTER"
    TABLE_TOPICS_MASTER = "TABLE_TOPICS_MASTER"
    SPEAKER = "SPEAKER"
    EVALUATOR = "EVALUATOR"
    TIMER = "TIMER"
    AH_COUNTER = "AH_COUNTER"
    GRAMMARIAN = "GRAMMARIAN"
    GENERAL_EVALUATOR = "GENERAL_EVALUATOR"


class RoleClass(str, Enum):
    SPEECH = "SPEECH"
    FUNCTIONARY = "FUNCTIONARY"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    RELEASED = "RELEASED"


class TermStatus(str, Enum):
    NOMINATED = "NOMINATED"
    ELECTED = "ELECTED"
    TRAINED = "TRAINED"
    COMPLETED = "COMPLETED"
    VACATED = "VACATED"


class ContestLevel(str, Enum):
    CLUB = "CLUB"
    AREA = "AREA"
    DIVISION = "DIVISION"
    DISTRICT = "DISTRICT"


class ContestType(str, Enum):
    INTERNATIONAL_SPEECH = "INTERNATIONAL_SPEECH"
    TALL_TALES = "TALL_TALES"
    EVALUATION = "EVALUATION"
    HUMOROUS = "HUMOROUS"


class ContestStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class EntryStatus(str, Enum):
    ENTERED = "ENTERED"
    JUDGED = "JUDGED"
    ADVANCED = "ADVANCED"
    ELIMINATED = "ELIMINATED"
    DISQUALIFIED = "DISQUALIFIED"


class VisitKind(str, Enum):
    AREA_DIRECTOR = "AREA_DIRECTOR"
    DIVISION_DIRECTOR = "DIVISION_DIRECTOR"
    CLUB_COACH = "CLUB_COACH"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"


class UserRole(str, Enum):
    WORLD_HEADQUARTERS = "WorldHeadquarters"
    CLUB_OFFICER = "ClubOfficer"
    MEMBER = "Member"
    DISTRICT_DIRECTOR = "DistrictDirector"


class Club(TypedDict, total=False):
    id: str
    club_name: str
    club_type: str
    corporate_sponsor_name: Optional[str]
    district_number: str
    division_code: str
    area_code: str
    venue_name: str
    club_dues_cents: int
    sponsor_club_id: Optional[str]
    organizing_meeting_at: Optional[str]
    organizing_meeting_attendees: int
    charter_status: str
    charter_date: Optional[str]
    good_standing: str
    good_standing_score: int
    cycle_open_standing: str
    dues_cycle_index: int
    cycle_opened_at: str
    cycle_closed_at: Optional[str]
    paid_member_count: int
    total_member_count: int
    new_member_count_this_cycle: int
    officer_trained_count: int
    meetings_held_this_cycle: int
    approved_level_completions_this_cycle: int
    contest_participation_count: int
    dcp_recognition_points: int
    dcp_tier: str
    coaching_status: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    home_area_code: Optional[str]
    member_since: str
    total_speeches_delivered: int
    highest_level_completed: int
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict, total=False):
    id: str
    member_id: str
    club_id: str
    status: str
    dues_status: str
    join_date: str
    first_time_member: bool
    dues_paid_through_cycle: int
    consecutive_cycles_paid: int
    quoted_total_cents: Optional[int]
    officer_role: str
    speeches_delivered_this_cycle: int
    roles_completed_this_cycle: int
    created_at: str
    updated_at: str
    version: int


class EducationPath(TypedDict, total=False):
    id: str
    membership_id: str
    path_code: str
    level: str
    status: str
    approved_speeches_at_level: int
    approved_projects_at_level: int
    level_started_at: str
    last_advanced_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProjectCompletion(TypedDict, total=False):
    id: str
    path_id: str
    member_id: str
    club_id: str
    project_code: str
    project_kind: str
    level: int
    speech_minutes: int
    delivered_at: str
    evaluator_member_id: Optional[str]
    evaluation_summary: Optional[str]
    status: str
    return_reason: Optional[str]
    counts_for_level_advancement: bool
    created_at: str
    updated_at: str
    version: int


class MeetingEvent(TypedDict, total=False):
    id: str
    club_id: str
    scheduled_at: str
    duration_minutes: int
    venue_name: str
    theme: Optional[str]
    status: str
    attendance_count: Optional[int]
    quorum_met: bool
    filled_role_slots: int
    required_role_slots: int
    held_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RoleAssignment(TypedDict, total=False):
    id: str
    meeting_id: str
    member_id: str
    role_code: str
    role_class: str
    status: str
    credit_awarded: bool
    released_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OfficerTerm(TypedDict, total=False):
    id: str
    club_id: str
    member_id: str
    office: str
    term_index: int
    status: str
    nominated_at: str
    elected_at: Optional[str]
    training_due_at: Optional[str]
    trained_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Contest(TypedDict, total=False):
    id: str
    club_id: Optional[str]
    contest_level: str
    contest_type: str
    district_number: str
    division_code: str
    area_code: Optional[str]
    scheduled_at: str
    status: str
    entry_count: int
    judged_entry_count: int
    winner_entry_id: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ContestEntry(TypedDict, total=False):
    id: str
    contest_id: str
    member_id: str
    club_id: str
    speech_title: str
    status: str
    ballot_count: int
    judge_score_total: int
    placement: Optional[int]
    created_at: str
    updated_at: str
    version: int


class AreaVisit(TypedDict, total=False):
    id: str
    club_id: str
    director_member_id: str
    visit_kind: str
    scheduled_at: str
    status: str
    completed_at: Optional[str]
    findings: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BulkEnrollmentResult(TypedDict, total=False):
    created_count: int
    failed_count: int
    memberships: List[Membership]
