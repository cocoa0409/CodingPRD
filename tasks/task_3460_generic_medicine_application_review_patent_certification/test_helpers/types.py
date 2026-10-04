"""Domain types: entity TypedDicts, status enums, role enum (PRD sections 2-3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    APPLICANT_SPONSOR = "ApplicantSponsor"
    INNOVATOR_SPONSOR = "InnovatorSponsor"
    REGULATORY_REVIEWER = "RegulatoryReviewer"
    FACILITY_INSPECTOR = "FacilityInspector"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    RECEIVED = "RECEIVED"
    TENTATIVE_APPROVAL = "TENTATIVE_APPROVAL"
    APPROVED = "APPROVED"
    REFUSED_APPROVAL = "REFUSED_APPROVAL"
    LAPSED = "LAPSED"
    WITHDRAWN = "WITHDRAWN"


class PatentStatus(str, Enum):
    LISTED = "LISTED"
    EXPIRED = "EXPIRED"


class CertificationType(str, Enum):
    PARAGRAPH_II_EXPIRED = "PARAGRAPH_II_EXPIRED"
    PARAGRAPH_III_DEFER = "PARAGRAPH_III_DEFER"
    PARAGRAPH_IV_CHALLENGE = "PARAGRAPH_IV_CHALLENGE"


class CertificationStatus(str, Enum):
    CERTIFIED = "CERTIFIED"
    AMENDED_TO_P3 = "AMENDED_TO_P3"


class NoticeStatus(str, Enum):
    NOTICE_SENT = "NOTICE_SENT"
    SUIT_FILED = "SUIT_FILED"
    NO_SUIT_FILED = "NO_SUIT_FILED"
    STAY_EXPIRED = "STAY_EXPIRED"
    DECIDED_VALID = "DECIDED_VALID"
    DECIDED_INVALID = "DECIDED_INVALID"


class CycleStatus(str, Enum):
    OPEN = "OPEN"
    CRL_ISSUED = "CRL_ISSUED"
    AMENDMENT_RECEIVED = "AMENDMENT_RECEIVED"
    CLOSED = "CLOSED"
    LAPSED = "LAPSED"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    WAIVED = "WAIVED"
    CANCELLED = "CANCELLED"


class AwardStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    AWARDED = "AWARDED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    FORFEITED = "FORFEITED"


# All entities carry the four common system properties (PRD section 2.5).
ApplicantCompany = TypedDict("ApplicantCompany", {
    "id": str, "legal_name": str, "contact_email": str, "headquarters_country": str,
    "created_at": str, "updated_at": str, "version": int})
ReferenceProduct = TypedDict("ReferenceProduct", {
    "id": str, "brand_name": str, "active_ingredient": str, "strength": str,
    "dosage_form": str, "rld_approval_date": str, "is_new_chemical_entity": bool,
    "indication_codes": List[str], "patent_owner_user_id": str,
    "created_at": str, "updated_at": str, "version": int})
ListedPatent = TypedDict("ListedPatent", {
    "id": str, "reference_product_id": str, "patent_number": str, "patent_type": str,
    "use_code": Optional[str], "expiry_date": str, "status": str,
    "created_at": str, "updated_at": str, "version": int})
ProtectedIndication = TypedDict("ProtectedIndication", {
    "id": str, "reference_product_id": str, "indication_code": str,
    "effective_from": str, "protected_until": str, "status": str,
    "created_at": str, "updated_at": str, "version": int})
GenericApplication = TypedDict("GenericApplication", {
    "id": str, "applicant_id": str, "reference_product_id": str, "review_priority": str,
    "labeling_mode": str, "carved_indication_codes": List[str], "status": str,
    "received_date": Optional[str], "current_cycle_number": int,
    "tentative_approval_date": Optional[str], "approval_date": Optional[str],
    "first_marketing_date": Optional[str], "patent_blocked_until": Optional[str],
    "exclusivity_blocked": bool, "open_deficiency_count": int,
    "open_supplement_count": int, "created_at": str, "updated_at": str, "version": int})
BioequivalenceStudy = TypedDict("BioequivalenceStudy", {
    "id": str, "application_id": str, "study_type": str, "analyte": str,
    "auc_ratio_pct": float, "auc_ci_low_pct": float, "auc_ci_high_pct": float,
    "cmax_ratio_pct": float, "cmax_ci_low_pct": float, "cmax_ci_high_pct": float,
    "is_adequate": bool, "status": str,
    "created_at": str, "updated_at": str, "version": int})
PatentCertification = TypedDict("PatentCertification", {
    "id": str, "application_id": str, "patent_id": str, "certification_type": str,
    "status": str, "filed_date": str, "amended_date": Optional[str],
    "created_at": str, "updated_at": str, "version": int})
PatentChallengeNotice = TypedDict("PatentChallengeNotice", {
    "id": str, "certification_id": str, "notice_date": str, "is_timely": bool,
    "suit_deadline": str, "suit_filed_date": Optional[str], "stay_until": Optional[str],
    "court_outcome": str, "court_decision_date": Optional[str], "status": str,
    "created_at": str, "updated_at": str, "version": int})
ReviewCycle = TypedDict("ReviewCycle", {
    "id": str, "application_id": str, "cycle_number": int, "status": str,
    "opened_date": str, "base_review_months": int, "major_amendment_extensions_count": int,
    "goal_date": str, "deficiency_issued_date": Optional[str],
    "deficiency_response_due_date": Optional[str],
    "deficiency_response_received_date": Optional[str],
    "deficiency_summary": Optional[str], "closed_reason": Optional[str],
    "created_at": str, "updated_at": str, "version": int})
Amendment = TypedDict("Amendment", {
    "id": str, "application_id": str, "classification": str, "contains_new_be_data": bool,
    "notes": Optional[str], "submitted_date": str,
    "created_at": str, "updated_at": str, "version": int})
ManufacturingFacility = TypedDict("ManufacturingFacility", {
    "id": str, "applicant_id": str, "facility_name": str, "fei_number": str,
    "country_code": str, "is_foreign": bool,
    "created_at": str, "updated_at": str, "version": int})
FacilityInspection = TypedDict("FacilityInspection", {
    "id": str, "facility_id": str, "application_id": str, "inspection_type": str,
    "scheduled_start_date": str, "scheduled_end_date": str, "status": str,
    "outcome_date": Optional[str], "created_at": str, "updated_at": str, "version": int})
Supplement = TypedDict("Supplement", {
    "id": str, "application_id": str, "change_type": str, "pathway": str,
    "description": Optional[str], "review_status": str, "effectivity": str,
    "submitted_date": str, "effective_date": Optional[str], "decision_date": Optional[str],
    "created_at": str, "updated_at": str, "version": int})
ExclusivityAward = TypedDict("ExclusivityAward", {
    "id": str, "application_id": str, "reference_product_id": str, "status": str,
    "awarded_date": Optional[str], "approval_date": Optional[str],
    "marketing_deadline": Optional[str], "first_marketing_date": Optional[str],
    "exclusivity_end_date": Optional[str], "forfeiture_reason": Optional[str],
    "created_at": str, "updated_at": str, "version": int})
