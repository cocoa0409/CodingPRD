import itertools
import uuid

from util import CLOCK, fmt_dt


class Store:
    def __init__(self):
        self.members = {}
        self.assessments = {}
        self.counselors = {}
        self.courses = {}
        self.enrollments = {}
        self.certifications = {}
        self.cycles = {}
        self.applications = {}
        self.awards = {}
        self.disbursements = {}
        self.client_files = {}
        self.file_reviews = {}
        self.exp_reports = {}
        self.audits = {}
        self.perf_reviews = {}
        self._seq = itertools.count(1)

    def new_entity(self, **fields):
        now = CLOCK.now()
        ent = {
            "id": str(uuid.uuid4()),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "_seq": next(self._seq),
        }
        ent.update(fields)
        return ent

    def touch(self, ent, bump=True):
        ent["updated_at"] = CLOCK.now()
        if bump:
            ent["version"] += 1


DB = Store()


def sort_entities(entities):
    return sorted(entities, key=lambda e: (e["created_at"], e["_seq"]))


def serialize(ent, fields):
    out = {}
    for f in fields:
        v = ent.get(f)
        if f in ("created_at", "updated_at", "chartered_at", "ce_window_end",
                 "certified_at", "lapse_deadline", "opened_on", "reviewed_at",
                 "corrective_plan_due", "delivery_start", "delivery_end",
                 "period_start", "period_end"):
            v = fmt_dt(v) if v is not None else None
        out[f] = v
    return out


COMMON = ["id", "created_at", "updated_at", "version"]

MEMBER_FIELDS = COMMON + [
    "legal_name", "ein", "state_code", "charter_status", "compliance_posture",
    "service_regions", "chartered_at", "revocation_reason",
    "open_finding_count", "failed_review_flag",
]

ASSESSMENT_FIELDS = COMMON + [
    "member_id", "governance_score", "finance_score", "program_capacity_score",
    "composite_score", "provisional_rating", "final_rating", "assessment_status",
    "assessor_id",
]

COUNSELOR_FIELDS = COMMON + [
    "member_id", "full_name", "email", "counselor_status",
    "ce_credits_accumulated", "ce_window_end",
]

COURSE_FIELDS = COMMON + [
    "course_code", "title", "program_area", "capacity", "ce_eligible",
    "ce_credits", "delivery_start", "delivery_end", "prerequisite_course_id",
    "course_status", "seats_taken",
]

ENROLLMENT_FIELDS = COMMON + [
    "course_id", "counselor_id", "enrollment_status", "score", "pass_threshold",
]

CERT_FIELDS = COMMON + [
    "counselor_id", "program_area", "certification_status", "certified_at",
    "lapse_deadline", "continuing_requirement_met",
]

CYCLE_FIELDS = COMMON + [
    "fiscal_year", "formula_pool_cents", "competitive_pool_cents",
    "cycle_status", "formula_committed_cents", "competitive_committed_cents",
]

APPLICATION_FIELDS = COMMON + [
    "cycle_id", "member_id", "program_area", "requested_formula_cents",
    "requested_competitive_cents", "pledged_match_cents", "application_status",
    "review_score", "reviewer_id",
]

AWARD_FIELDS = COMMON + [
    "application_id", "cycle_id", "member_id", "formula_component_cents",
    "competitive_component_cents", "required_match_cents", "verified_match_cents",
    "award_status", "disbursed_cents",
]

DISBURSEMENT_FIELDS = COMMON + [
    "award_id", "tranche_index", "amount_cents", "disbursement_status",
]

CLIENT_FILE_FIELDS = COMMON + [
    "member_id", "counselor_id", "program_area", "household_size",
    "opened_on", "file_status", "outcome_code", "counseling_hours",
]

FILE_REVIEW_FIELDS = COMMON + [
    "client_file_id", "reviewer_id", "review_status", "deficiency_codes",
    "reviewed_at",
]

EXP_REPORT_FIELDS = COMMON + [
    "award_id", "period_start", "period_end", "reported_spent_cents",
    "report_status", "cumulative_spent_cents",
]

AUDIT_FIELDS = COMMON + [
    "award_id", "auditor_id", "audit_status", "disallowance_cents",
    "parent_audit_id",
]

PERF_REVIEW_FIELDS = COMMON + [
    "member_id", "review_period", "households_served", "review_score",
    "review_status", "corrective_plan_due",
]
