"""Entity -> wire dict. Common fields on every resource: id, created_at,
updated_at, version (PRD 2.4). System-managed created_at/updated_at serialize
with three fractional digits (PRD 2.4); clock-sourced and computed timestamps
serialize as the logical clock itself renders (PRD 2.5, 2.10).
Internal keys (leading underscore) are never exposed."""
from store import fmt_dt, fmt_clock_dt

_COMMON = ("id", "created_at", "updated_at", "version")


def _dump(row, fields):
    out = {}
    for f in fields + list(_COMMON):
        v = row.get(f)
        if f in ("created_at", "updated_at"):
            out[f] = fmt_dt(v)
        elif f.endswith("_at") or f == "eod_date":
            out[f] = fmt_clock_dt(v)
        else:
            out[f] = v
    return out


def series_out(r):
    return _dump(r, ["series_code", "title", "min_grade", "max_grade",
                     "quals_base_months", "quals_months_per_grade_step",
                     "allows_education_substitution", "education_substitution_cap_months",
                     "positive_education_required"])


def position_out(r):
    return _dump(r, ["series_id", "title", "org_code",
                     "factor_knowledge_level", "factor_supervision_level",
                     "factor_complexity_level", "factor_impact_level",
                     "total_points", "provisional_grade", "official_grade",
                     "sensitivity_level", "status"])


def announcement_out(r):
    return _dump(r, ["position_id", "announcement_number", "area_of_consideration",
                     "hiring_authority", "assessment_method", "open_at", "close_at",
                     "vacancies_count", "bq_cut", "wq_cut", "certificate_validity_days",
                     "remaining_vacancies", "status"])


def applicant_out(r):
    return _dump(r, ["full_name", "email", "is_us_citizen", "is_current_federal_employee",
                     "agency_code", "veteran_preference_claim",
                     "preference_verified", "preference_points"])


def document_out(r):
    return _dump(r, ["applicant_id", "doc_type", "verified", "verified_by", "verified_at"])


def application_out(r):
    return _dump(r, ["announcement_id", "applicant_id", "submitted_at",
                     "claimed_experience_months", "claimed_education_months",
                     "self_rating_knowledge", "self_rating_skill", "self_rating_ability",
                     "provisional_score", "provisional_category",
                     "required_experience_months", "creditable_experience_months",
                     "technical_score", "quality_category", "notified_at", "status"])


def assessment_out(r):
    return _dump(r, ["application_id", "sme_user_id",
                     "rating_knowledge", "rating_skill", "rating_ability",
                     "technical_score", "quality_category", "return_reason", "status"])


def certificate_out(r):
    return _dump(r, ["announcement_id", "issued_at", "expires_at", "extension_count", "status"])


def entry_out(r):
    return _dump(r, ["certificate_id", "application_id", "quality_category",
                     "preference_eligible", "preference_points", "augmented_score",
                     "rank_position", "status"])


def pass_over_out(r):
    return _dump(r, ["certificate_entry_id", "desired_entry_id", "reason_code",
                     "justification", "adjudicated_by", "adjudication_note", "status"])


def offer_out(r):
    return _dump(r, ["application_id", "certificate_entry_id", "tentative_offered_at",
                     "response_due_at", "responded_at", "suitability_reviewer_id",
                     "eod_date", "status"])


def suitability_out(r):
    return _dump(r, ["offer_id", "reviewer_id", "outcome", "notes", "recorded_at"])


def clearance_out(r):
    return _dump(r, ["offer_id", "adjudicator_id", "level_required", "outcome", "recorded_at"])


def appeal_out(r):
    return _dump(r, ["application_id", "grounds", "corrected_experience_months",
                     "filed_at", "deadline_at", "adjudication_note", "status"])


def appointment_out(r):
    return _dump(r, ["offer_id", "appointment_type", "eod_date"])
