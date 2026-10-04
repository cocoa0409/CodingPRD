"""Error catalogue: every error id declared in SCAFFOLD.yaml §1.6 / PRD.md §5."""

ERROR_STATUS = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_INSUFFICIENT_PERMISSIONS": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERRAL_NOT_FOUND": 404,
    "ERR_PROTOCOL_NOT_FOUND": 404,
    "ERR_ENROLLMENT_NOT_FOUND": 404,
    "ERR_HOUSING_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_HOUSING_FACILITY_NOT_FOUND": 404,
    "ERR_PLEDGE_NOT_FOUND": 404,
    "ERR_TRAVEL_NOT_FOUND": 404,
    "ERR_MILESTONE_NOT_FOUND": 404,
    "ERR_STUDY_NOT_FOUND": 404,
    "ERR_SURVIVORSHIP_ENROLLMENT_NOT_FOUND": 404,
    "ERR_CLINIC_NOT_FOUND": 404,
    "ERR_AGREEMENT_NOT_FOUND": 404,
    "ERR_SERVICE_NOT_FOUND": 404,
    "ERR_LEDGER_NOT_FOUND": 404,
    "ERR_FUND_NOT_FOUND": 404,
    "ERR_SIBLING_SERVICE_NOT_FOUND": 404,
    "ERR_HOLD_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_DUPLICATE_ENTITY": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_PROTOCOL_NOT_OPEN": 409,
    "ERR_PROTOCOL_NOT_IN_DRAFT": 409,
    "ERR_PROTOCOL_NOT_HELD": 409,
    "ERR_PROTOCOL_HELD": 409,
    "ERR_PROTOCOL_HOLD_ACTIVE": 409,
    "ERR_PROTOCOL_HAS_ENROLLED_PATIENTS": 409,
    "ERR_ARM_ASSENT_BLOCKED_BY_HOLD": 409,
    "ERR_HOLD_NOT_ACTIVE": 409,
    "ERR_HOLD_NOT_IRB_REVIEW": 409,
    "ERR_REFERRAL_NOT_SUBMITTED": 409,
    "ERR_REFERRAL_NOT_ACCEPTED": 409,
    "ERR_REFERRAL_NOT_DECLINED": 409,
    "ERR_DUPLICATE_PATIENT_ELIGIBILITY": 409,
    "ERR_AGE_OUTSIDE_PROTOCOL_RANGE": 422,
    "ERR_DISEASE_GROUP_MISMATCH": 422,
    "ERR_DISEASE_STAGE_MISMATCH": 422,
    "ERR_PROTOCOL_CAPACITY_EXCEEDED": 409,
    "ERR_PROTOCOL_BUDGET_EXCEEDS_COMMITMENT_SHARE": 402,
    "ERR_PROTOCOL_BUDGET_EXHAUSTED": 402,
    "ERR_NO_HOUSING_AVAILABLE": 409,
    "ERR_HOUSING_CAPACITY_EXCEEDED": 409,
    "ERR_HOUSING_IMMUNOSUPPRESSION_INCOMPATIBLE": 422,
    "ERR_HOUSING_FACILITY_UNAVAILABLE": 409,
    "ERR_STEP_DOWN_NOT_PERMITTED": 422,
    "ERR_INVALID_VACATE_REASON": 422,
    "ERR_HOUSING_OCCUPANCY_ACTIVE": 409,
    "ERR_NO_ACTIVE_HOUSING": 409,
    "ERR_OCCUPANCY_NOT_STARTED": 409,
    "ERR_HOUSING_ASSIGNMENT_NOT_SCHEDULED": 409,
    "ERR_HOUSING_ASSIGNMENT_NOT_ACTIVE": 409,
    "ERR_ENROLLMENT_NOT_PENDING_CONSENT": 409,
    "ERR_ENROLLMENT_NOT_ENROLLED": 409,
    "ERR_ENROLLMENT_NOT_ACTIVE_TREATMENT": 409,
    "ERR_ENROLLMENT_NOT_ON_HIATUS": 409,
    "ERR_ENROLLMENT_NOT_IN_SURVIVORSHIP": 409,
    "ERR_ENROLLMENT_ACTIVE": 409,
    "ERR_INVALID_CONSENT_SIGNER": 422,
    "ERR_BILLING_NOT_PERMITTED": 409,
    "ERR_ONE_TO_ONE_CARE_NOT_ELIGIBLE": 422,
    "ERR_ASSENT_NOT_OBTAINED": 409,
    "ERR_SUPPORT_BUDGET_EXCEEDED": 402,
    "ERR_PLEDGE_SETTLE_NOT_ACTIVE": 409,
    "ERR_PLEDGE_SETTLE_ENROLLMENT_ACTIVE": 409,
    "ERR_TRAVEL_NOT_REQUESTED": 409,
    "ERR_TRAVEL_NOT_CONFIRMED": 409,
    "ERR_TRAVEL_NOT_CANCELLABLE": 409,
    "ERR_TRAVELER_COUNT_RANGE": 422,
    "ERR_TRAVEL_ELIGIBILITY_NOT_CONFIRMED": 409,
    "ERR_TRAVEL_COVERAGE_EXPIRED": 409,
    "ERR_TRAVEL_LEG_OVERLAP": 409,
    "ERR_MILESTONE_NOT_DUE": 409,
    "ERR_PRIOR_MILESTONE_NOT_EXECUTED": 409,
    "ERR_MILESTONE_REQUIRES_MAIN_CAMPUS": 422,
    "ERR_NO_ACTIVE_AFFILIATION_AGREEMENT": 409,
    "ERR_AFFILIATE_NOT_ADJACENT": 422,
    "ERR_VISIT_WINDOW_TOO_DISTANT": 409,
    "ERR_MILESTONES_OUTSTANDING": 409,
    "ERR_NO_ACTIVE_SURVIVORSHIP_STUDY": 409,
    "ERR_SURVIVORSHIP_NOT_GRADUATED": 409,
    "ERR_SURVIVORSHIP_NOT_ON_STUDY": 409,
    "ERR_STUDY_NOT_ACTIVE": 409,
    "ERR_FOLLOW_UP_WINDOW_VIOLATION": 409,
    "ERR_SIBLING_SERVICE_NOT_ACTIVE": 409,
    "ERR_SIBLING_SESSION_LIMIT_REACHED": 409,
    "ERR_STALE_LEDGER_EPOCH": 409,
}

MESSAGES = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER":
        "X-User-ID or X-User-Role header missing or unresolvable.",
    "ERR_INSUFFICIENT_PERMISSIONS":
        "Acting role is not permitted for this operation.",
    "ERR_NOT_FOUND": "A resource id in the path or body does not exist.",
    "ERR_REFERRAL_NOT_FOUND": "Referral id does not exist.",
    "ERR_PROTOCOL_NOT_FOUND": "ClinicalProtocol id does not exist.",
    "ERR_ENROLLMENT_NOT_FOUND": "Enrollment id does not exist.",
    "ERR_HOUSING_ASSIGNMENT_NOT_FOUND": "HousingAssignment id does not exist.",
    "ERR_HOUSING_FACILITY_NOT_FOUND": "HousingFacility id does not exist.",
    "ERR_PLEDGE_NOT_FOUND": "FamilySupportPledge id does not exist.",
    "ERR_TRAVEL_NOT_FOUND": "TravelArrangement id does not exist.",
    "ERR_MILESTONE_NOT_FOUND": "ProtocolMilestone id does not exist.",
    "ERR_STUDY_NOT_FOUND": "SurvivorshipStudy id does not exist.",
    "ERR_SURVIVORSHIP_ENROLLMENT_NOT_FOUND": "SurvivorshipEnrollment id does not exist.",
    "ERR_CLINIC_NOT_FOUND": "AffiliateClinic id does not exist.",
    "ERR_AGREEMENT_NOT_FOUND": "AffiliationAgreement id does not exist.",
    "ERR_SERVICE_NOT_FOUND": "FamilySupportService id does not exist.",
    "ERR_LEDGER_NOT_FOUND": "FamilyServiceLedger id does not exist.",
    "ERR_FUND_NOT_FOUND": "ResearchFund id does not exist.",
    "ERR_SIBLING_SERVICE_NOT_FOUND": "SiblingSupportService id does not exist.",
    "ERR_HOLD_NOT_FOUND": "ProtocolHold id does not exist.",
    "ERR_INVALID_REQUEST":
        "Malformed body, missing required field, type mismatch, or an out-of-range integer.",
    "ERR_DUPLICATE_ENTITY": "A declared uniqueness constraint is violated.",
    "ERR_STALE_VERSION": "An expected_*_version OCC field does not match the parent's current version.",
    "ERR_INVALID_STATE": "The target resource is not in the state the operation requires.",
    "ERR_PROTOCOL_NOT_OPEN": "ClinicalProtocol is not OPEN.",
    "ERR_PROTOCOL_NOT_IN_DRAFT": "ClinicalProtocol is not in DRAFT.",
    "ERR_PROTOCOL_NOT_HELD": "ClinicalProtocol is not in HELD.",
    "ERR_PROTOCOL_HELD": "ClinicalProtocol is frozen by an active hold or review lock.",
    "ERR_PROTOCOL_HOLD_ACTIVE": "A ProtocolHold on this protocol is still ACTIVE.",
    "ERR_PROTOCOL_HAS_ENROLLED_PATIENTS": "ClinicalProtocol still carries enrolled patients.",
    "ERR_ARM_ASSENT_BLOCKED_BY_HOLD":
        "Assent confirmation and enrollment completion are blocked while the protocol carries a review lock.",
    "ERR_HOLD_NOT_ACTIVE": "ProtocolHold is not in ACTIVE status.",
    "ERR_HOLD_NOT_IRB_REVIEW": "ProtocolHold hold_reason is not IRB_REVIEW.",
    "ERR_REFERRAL_NOT_SUBMITTED": "Referral is not in SUBMITTED status.",
    "ERR_REFERRAL_NOT_ACCEPTED": "Referral is not in ACCEPTED status.",
    "ERR_REFERRAL_NOT_DECLINED": "Referral is not in DECLINED status.",
    "ERR_DUPLICATE_PATIENT_ELIGIBILITY":
        "Another referral sharing the protected eligibility_alias is already ACCEPTED or ARRIVED.",
    "ERR_AGE_OUTSIDE_PROTOCOL_RANGE":
        "computed_age_years lies outside the protocol's inclusive age band.",
    "ERR_DISEASE_GROUP_MISMATCH":
        "Referral disease_group does not equal the protocol's disease_group.",
    "ERR_DISEASE_STAGE_MISMATCH":
        "Referral disease_stage does not equal the protocol's required_stage.",
    "ERR_PROTOCOL_CAPACITY_EXCEEDED": "enrolled_count is not strictly below capacity.",
    "ERR_PROTOCOL_BUDGET_EXCEEDS_COMMITMENT_SHARE":
        "protocol_budget_cents exceeds the fund's commitment share of net fundraising.",
    "ERR_PROTOCOL_BUDGET_EXHAUSTED":
        "available_cents would not remain strictly positive after the reservation.",
    "ERR_NO_HOUSING_AVAILABLE": "The housing selector finds no facility for the required tier.",
    "ERR_HOUSING_CAPACITY_EXCEEDED":
        "Committed plus scheduled beds plus the facility buffer exceed total_beds at a window endpoint.",
    "ERR_HOUSING_IMMUNOSUPPRESSION_INCOMPATIBLE":
        "An immunosuppressed patient is targeted at a facility whose tier is not immunosuppression_capable.",
    "ERR_HOUSING_FACILITY_UNAVAILABLE": "HousingFacility is not in OPEN status.",
    "ERR_STEP_DOWN_NOT_PERMITTED":
        "Housing step-down attempted before immunosuppression has cleared.",
    "ERR_INVALID_VACATE_REASON":
        "vacated_reason is not one of TREATMENT_COMPLETE, TRANSFERRED_AFFILIATE or RELOCATED.",
    "ERR_HOUSING_OCCUPANCY_ACTIVE": "A housing assignment for this enrollment is still ACTIVE.",
    "ERR_NO_ACTIVE_HOUSING": "The enrollment has no ACTIVE housing assignment.",
    "ERR_OCCUPANCY_NOT_STARTED": "start_at is later than the logical clock.",
    "ERR_HOUSING_ASSIGNMENT_NOT_SCHEDULED": "HousingAssignment is not in SCHEDULED status.",
    "ERR_HOUSING_ASSIGNMENT_NOT_ACTIVE": "HousingAssignment is not in ACTIVE status.",
    "ERR_ENROLLMENT_NOT_PENDING_CONSENT": "Enrollment is not in PENDING_CONSENT status.",
    "ERR_ENROLLMENT_NOT_ENROLLED": "Enrollment is not in ENROLLED status.",
    "ERR_ENROLLMENT_NOT_ACTIVE_TREATMENT": "Enrollment is not in ACTIVE_TREATMENT status.",
    "ERR_ENROLLMENT_NOT_ON_HIATUS": "Enrollment is not in ON_HIATUS status.",
    "ERR_ENROLLMENT_NOT_IN_SURVIVORSHIP": "Enrollment is not in SURVIVORSHIP status.",
    "ERR_ENROLLMENT_ACTIVE":
        "The referral's enrollment is already active in treatment or survivorship.",
    "ERR_INVALID_CONSENT_SIGNER":
        "consent_signer does not match the signer required for the child's age.",
    "ERR_BILLING_NOT_PERMITTED":
        "A billable family amount was raised outside the single permitted excess-over-coverage line.",
    "ERR_ONE_TO_ONE_CARE_NOT_ELIGIBLE":
        "A traveling GUARDIAN coverage holder was not cleared for one-to-one care.",
    "ERR_ASSENT_NOT_OBTAINED": "Child assent is still PENDING at enrollment completion.",
    "ERR_SUPPORT_BUDGET_EXCEEDED":
        "The final family charge exceeds patient_support_budget_cents plus insurance_coverage_cents.",
    "ERR_PLEDGE_SETTLE_NOT_ACTIVE": "FamilySupportPledge is not in ACTIVE status.",
    "ERR_PLEDGE_SETTLE_ENROLLMENT_ACTIVE":
        "The pledge's enrollment is still in a live treatment state.",
    "ERR_TRAVEL_NOT_REQUESTED": "TravelArrangement is not in REQUESTED status.",
    "ERR_TRAVEL_NOT_CONFIRMED": "TravelArrangement is not in CONFIRMED status.",
    "ERR_TRAVEL_NOT_CANCELLABLE":
        "TravelArrangement is not in REQUESTED or CONFIRMED status.",
    "ERR_TRAVELER_COUNT_RANGE": "traveler_count is outside 2..6.",
    "ERR_TRAVEL_ELIGIBILITY_NOT_CONFIRMED":
        "The target enrollment's protocol is not OPEN, so travel eligibility cannot be stamped.",
    "ERR_TRAVEL_COVERAGE_EXPIRED":
        "More than 30 days have elapsed on the logical clock since eligibility_confirmed_at.",
    "ERR_TRAVEL_LEG_OVERLAP":
        "A confirmed or disbursed leg for the same enrollment and mode overlaps the proposed window.",
    "ERR_MILESTONE_NOT_DUE": "ProtocolMilestone is not in DUE status.",
    "ERR_PRIOR_MILESTONE_NOT_EXECUTED":
        "The immediately preceding milestone of this enrollment has not been executed.",
    "ERR_MILESTONE_REQUIRES_MAIN_CAMPUS":
        "requires_main_campus is true, so the milestone cannot be deferred.",
    "ERR_NO_ACTIVE_AFFILIATION_AGREEMENT":
        "No ACTIVE AffiliationAgreement covers this protocol at the requested affiliate.",
    "ERR_AFFILIATE_NOT_ADJACENT":
        "The affiliate's state is not within one state of the family's household_state_code.",
    "ERR_VISIT_WINDOW_TOO_DISTANT":
        "The milestone instant is more than 14 days after the logical clock.",
    "ERR_MILESTONES_OUTSTANDING":
        "The enrollment still carries a milestone in PENDING, DUE or MISSED status.",
    "ERR_NO_ACTIVE_SURVIVORSHIP_STUDY":
        "No ACTIVE survivorship study exists on the enrollment's protocol.",
    "ERR_SURVIVORSHIP_NOT_GRADUATED":
        "A survivorship enrollment on this patient has not graduated.",
    "ERR_SURVIVORSHIP_NOT_ON_STUDY": "SurvivorshipEnrollment is not in ON_STUDY status.",
    "ERR_STUDY_NOT_ACTIVE": "SurvivorshipStudy is not in ACTIVE status.",
    "ERR_FOLLOW_UP_WINDOW_VIOLATION":
        "A follow-up visit is logged out of interval order or before the previous visit.",
    "ERR_SIBLING_SERVICE_NOT_ACTIVE": "SiblingSupportService is not in ACTIVE status.",
    "ERR_SIBLING_SESSION_LIMIT_REACHED":
        "The sibling service window session limit has already been reached.",
    "ERR_STALE_LEDGER_EPOCH":
        "The supplied ledger_epoch does not match the ledger's current epoch.",
}


class ApiError(Exception):
    """Raised anywhere in the request path; rendered by the app error handler."""

    def __init__(self, error_id, message=None, http_status=None):
        self.error_id = error_id
        self.message = message or MESSAGES.get(error_id, error_id)
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        super().__init__(self.error_id)


class ValidationFailure(Exception):
    """A *screen* precondition failed: the referral is DECLINED, not refused."""

    def __init__(self, error_id, decline_reason):
        self.error_id = error_id
        self.decline_reason = decline_reason
        super().__init__(error_id)