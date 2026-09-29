"""Error catalog and the ApiError exception (PRD section 5 / scaffold 1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        entry = ERROR_CATALOG.get(error_id)
        if http_status is not None:
            self.http_status = http_status
        elif entry is not None:
            self.http_status = entry[0]
        else:
            self.http_status = 400
        if message is not None:
            self.message = message
        elif entry is not None:
            self.message = entry[1]
        else:
            self.message = error_id


ERROR_CATALOG = {
    # --- authentication / authorization ---
    "ERR_MISSING_AUTH_HEADER": (401, "X-User-Role and X-User-ID headers are required."),
    "ERR_INVALID_ROLE": (400, "X-User-Role is not a recognised role."),
    "ERR_UNAUTHORIZED": (403, "This role may not call this endpoint."),
    "ERR_FORBIDDEN_RESOURCE": (403, "An athlete may only act on their own deliverables."),
    "ERR_SEGREGATION_OF_DUTIES": (403, "The user who verified this deliverable may not initiate its payout."),
    # --- schema ---
    "ERR_INVALID_REQUEST": (400, "The request body is missing a required field or carries an invalid value."),
    # --- existence ---
    "ERR_COLLECTIVE_NOT_FOUND": (404, "Collective not found."),
    "ERR_MEMBERSHIP_TIER_NOT_FOUND": (404, "Membership tier not found."),
    "ERR_DONOR_MEMBER_NOT_FOUND": (404, "Donor member not found."),
    "ERR_COMMITMENT_NOT_FOUND": (404, "Commitment not found."),
    "ERR_CONTRIBUTION_NOT_FOUND": (404, "Contribution not found."),
    "ERR_ATHLETE_NOT_FOUND": (404, "Athlete not found."),
    "ERR_DEAL_CONTRACT_NOT_FOUND": (404, "Deal contract not found."),
    "ERR_DELIVERABLE_NOT_FOUND": (404, "Deliverable not found."),
    "ERR_PAYMENT_RELEASE_NOT_FOUND": (404, "Payment release not found."),
    "ERR_COMMUNICATION_LOG_NOT_FOUND": (404, "Communication log not found."),
    # --- referential / uniqueness ---
    "ERR_CROSS_COLLECTIVE_REFERENCE": (409, "All referenced entities must belong to the same collective."),
    "ERR_DELIVERABLE_CONTRACT_MISMATCH": (409, "The named deliverable does not belong to the named deal contract."),
    "ERR_COMMITMENT_DONOR_MISMATCH": (409, "The named commitment does not belong to the named donor member."),
    "ERR_DUPLICATE_IPEDS_CODE": (409, "institution_ipeds_code is already in use."),
    "ERR_DUPLICATE_TIER_CODE": (409, "tier_code is already in use in this collective."),
    "ERR_DUPLICATE_MEMBER_HANDLE": (409, "This donor email or athlete portal_user_id is already in use in this collective."),
    # --- state ---
    "ERR_TIER_NOT_DRAFT": (409, "The membership tier is not in DRAFT."),
    "ERR_TIER_NOT_OPEN": (409, "The membership tier is not OPEN."),
    "ERR_COMMITMENT_STATE_INVALID": (409, "The commitment is not in a state that permits this action."),
    "ERR_COMMITMENT_NOT_CHARGEABLE": (409, "A contribution may only be attributed to an ACTIVE or PAST_DUE commitment."),
    "ERR_CONTRIBUTION_STATE_INVALID": (409, "The contribution is not in a state that permits this action."),
    "ERR_ATHLETE_STATE_INVALID": (409, "That eligibility change is not permitted from the athlete's current status."),
    "ERR_CONTRACT_NOT_DRAFT": (409, "The deal contract is not in DRAFT."),
    "ERR_CONTRACT_NOT_ACTIVE": (409, "The deal contract is not ACTIVE."),
    "ERR_CONTRACT_TERMINAL": (409, "The deal contract is in a terminal lifecycle state."),
    "ERR_DISCLOSURE_STATE_INVALID": (409, "The disclosure is not in a state that permits this action."),
    "ERR_DISCLOSURE_NOT_SUBMITTED": (409, "The disclosure has not been submitted yet."),
    "ERR_DISCLOSURE_NOT_CLEARED": (409, "The disclosure has not been accepted by the institution."),
    "ERR_DELIVERABLE_STATE_INVALID": (409, "The deliverable is not in a state that permits this action."),
    "ERR_RELEASE_NOT_RELEASED": (409, "Only a RELEASED payment release can be reversed."),
    # --- concurrency ---
    "ERR_STALE_DONOR_VERSION": (412, "expected_donor_member_version does not match the stored donor member version."),
    "ERR_STALE_COLLECTIVE_VERSION": (412, "expected_collective_version does not match the stored collective version."),
    "ERR_STALE_CONTRACT_VERSION": (412, "expected_deal_contract_version does not match the stored deal contract version."),
    # --- business safety ---
    "ERR_COLLECTIVE_FUNDING_FROZEN": (409, "The collective's funding posture is FROZEN."),
    "ERR_COLLECTIVE_FUNDING_RESTRICTED": (409, "A roster-wide allocation requires an OPEN funding posture."),
    "ERR_ATHLETE_NOT_ENROLLED": (409, "The athlete is not ENROLLED."),
    "ERR_NO_ELIGIBLE_ATHLETES": (422, "No eligible athlete matches this allocation batch."),
    # --- business temporal ---
    "ERR_EXCLUSIVITY_WINDOW_CONFLICT": (409, "Another contract for this athlete already claims this exclusivity category over an overlapping window."),
    "ERR_DUE_OUTSIDE_CONTRACT_WINDOW": (422, "due_at must fall inside the contract's effective window."),
    "ERR_REVERSAL_ACROSS_TAX_YEARS": (422, "A release from a previous tax year cannot be reversed."),
    "ERR_BATCH_OVERLAP_CAPACITY_EXCEEDED": (409, "Too many roster allocation batches already overlap this window for this sport."),
    # --- business constraint ---
    "ERR_EVIDENCE_INSUFFICIENT": (422, "At least one documentation-of-services record is required before submission."),
    "ERR_CHARITY_HOURS_SHORTFALL": (422, "Documented charity hours are below the required amount."),
    "ERR_RESUBMISSION_LIMIT_REACHED": (422, "This deliverable has reached its submission limit."),
    "ERR_TIER_RANK_DUES_INVERSION": (422, "Tier dues must increase strictly with benefit_rank among OPEN tiers."),
    "ERR_STRUCTURE_CHANGE_LIMIT": (422, "This collective has already used its entity-structure changes."),
    "ERR_STRUCTURE_UNCHANGED": (422, "The submitted entity_structure matches the current one."),
    "ERR_DELIVERABLE_NOT_VERIFIED": (422, "A deliverable payout requires a VERIFIED or WAIVED deliverable."),
    "ERR_RELEASE_EXCEEDS_CONTRACT_VALUE": (422, "The release would push released_total_cents above the contract's total_value_cents."),
    "ERR_ROSTER_SHARE_BELOW_MINIMUM": (422, "The pool is too small to give every eligible athlete at least one cent."),
    "ERR_ATHLETE_ANNUAL_CAP_EXCEEDED": (422, "The athlete's committed contract value would exceed the annual cap."),
    "ERR_BILLING_INTERVAL_MISMATCH": (422, "billing_interval is inconsistent with the commitment kind."),
    "ERR_SOURCE_KIND_COMMITMENT_MISMATCH": (422, "commitment_id is inconsistent with source_kind."),
    # --- business fiscal ---
    "ERR_FUNDING_DESIGNATION_MISMATCH": (422, "No settled contribution carries the contract's funding designation."),
    "ERR_INSUFFICIENT_DESIGNATED_FUNDS": (422, "The designated pool does not hold enough unreleased settled funds."),
    "ERR_TAXPAYER_DOC_REQUIRED": (422, "A W8BEN is required before paying a nonresident alien athlete."),
    "ERR_RELEASE_EXCEEDS_PAYOUT_ELIGIBLE": (422, "requested_amount_cents exceeds the deliverable's payout_eligible_cents."),
}


def invalid(message=None):
    return ApiError("ERR_INVALID_REQUEST", message)
