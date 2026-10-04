"""Error identifiers, HTTP statuses and the ApiError exception."""

# error_id -> (http_status, default message)
ERROR_TABLE = {
    "ERR_MISSING_USER_CONTEXT": (400, "X-User-ID or X-User-Role header absent or naming an undeclared role."),
    "ERR_INSUFFICIENT_PERMISSIONS": (403, "The caller's role is not permitted for this endpoint."),
    "ERR_BROKER_RESOURCE_FORBIDDEN": (403, "A BrokerUser may act only on its own brokerage's resources."),
    "ERR_SEGREGATION_OF_DUTIES_VIOLATION": (403, "The QC reviewer of a loan must not be the loan's underwriter."),
    "ERR_BROKER_NOT_FOUND": (404, "broker_id does not resolve to a Broker."),
    "ERR_LICENSE_NOT_FOUND": (404, "license_id does not resolve to a BrokerLicense."),
    "ERR_REVIEW_NOT_FOUND": (404, "review_id does not resolve to a review."),
    "ERR_ELIGIBILITY_NOT_FOUND": (404, "eligibility_id does not resolve to a ProductEligibility."),
    "ERR_RATE_SHEET_NOT_FOUND": (404, "sheet_id does not resolve to a RateSheet."),
    "ERR_QUOTE_NOT_FOUND": (404, "quote_id does not resolve to a PricingQuote."),
    "ERR_LOAN_NOT_FOUND": (404, "loan_id does not resolve to a LoanSubmission."),
    "ERR_PLAN_NOT_FOUND": (404, "plan_id does not resolve to a CompensationPlan of this broker."),
    "ERR_ESCALATION_NOT_FOUND": (404, "escalation_id does not resolve to a TurnTimeEscalation."),
    "ERR_STALE_VERSION": (412, "The expected version no longer equals the parent's current version."),
    "ERR_BROKER_NOT_SUBMITTED": (409, "The broker is not SUBMITTED (or, on reinstatement, not SUSPENDED)."),
    "ERR_BROKER_NOT_SUSPENDABLE": (409, "Manual suspension requires an APPROVED broker."),
    "ERR_BROKER_NOT_APPROVED": (403, "The broker is not APPROVED."),
    "ERR_BROKER_EXCLUSIVITY_BLOCKED": (403, "The broker's exclusivity_status is BLOCKED."),
    "ERR_BROKER_EXCLUSIVITY_RESTRICTED": (403, "The broker is RESTRICTED for this operation's scope."),
    "ERR_EXCLUSIVITY_POLICY_BREACH": (403, "The disclosed competitor is listed on an ACTIVE exclusivity policy."),
    "ERR_BROKER_DEFECT_HOLD": (403, "The broker's open_defect_tier exceeds 2."),
    "ERR_BROKER_QUALITY_BELOW_REINSTATEMENT": (403, "rolling_quality_score is below 60.00."),
    "ERR_ACTIVE_LOANS_PRESENT": (409, "The broker still has active loans."),
    "ERR_FINANCIAL_REVIEW_PENDING": (409, "No PASSED financial review exists, or the review is unattested."),
    "ERR_NO_VALID_LICENSE": (409, "The broker has no unexpired license."),
    "ERR_DUPLICATE_NMLS_ID": (409, "A Broker already exists with the submitted nmls_id."),
    "ERR_PROPERTY_STATE_NOT_LICENSED": (422, "loan.property_state is absent from broker.licensed_states."),
    "ERR_PRODUCT_NOT_ELIGIBLE": (422, "No APPROVED ProductEligibility covers this submission."),
    "ERR_PRICING_QUOTE_SUPERSEDED": (409, "The referenced RateSheet is superseded or retired."),
    "ERR_COMPENSATION_PLAN_MISMATCH": (422, "The nominated compensation plan is not consistent with the election."),
    "ERR_COMPENSATION_ELECTION_IMMUTABLE": (409, "The compensation election can no longer change."),
    "ERR_COMPENSATION_ELECTION_PENDING": (409, "The compensation election is still UNDECIDED."),
    "ERR_LOAN_NOT_SUBMITTED": (409, "The loan is not SUBMITTED."),
    "ERR_LOAN_NOT_UNDERWRITING": (409, "The loan is not UNDERWRITING."),
    "ERR_LOAN_NOT_CONDITIONAL": (409, "The loan is not CONDITIONAL_APPROVAL."),
    "ERR_LOAN_NOT_CLEAR_TO_CLOSE": (409, "The loan is not CLEAR_TO_CLOSE."),
    "ERR_LOAN_NOT_WITHDRAWABLE": (409, "The loan is not withdrawable from its current status."),
    "ERR_LOAN_NOT_SUSPENDED": (409, "The loan is not SUSPENDED_REVIEW."),
    "ERR_DEFECT_REMEDIATION_OPEN": (409, "An OPEN defect finding blocks this operation."),
    "ERR_CLOSING_ESCALATION_OPEN": (409, "An OPEN TurnTimeEscalation blocks this operation."),
    "ERR_QC_REVIEW_EXISTS": (409, "A QualityControlReview already exists for this loan."),
    "ERR_REPURCHASE_NOT_REQUIRED": (409, "The review is not a repurchase-required critical defect."),
    "ERR_REPURCHASE_WINDOW_EXPIRED": (409, "The repurchase window has lapsed."),
    "ERR_LOAN_ALREADY_REPURCHASED": (409, "The loan already carries a repurchase."),
    "ERR_LAST_ACTIVE_COMPENSATION_PLAN": (409, "Deactivation would leave no ACTIVE compensation plan."),
    "ERR_SHEET_IN_USE": (409, "One or more PricingQuote rows reference this RateSheet."),
    "ERR_ESCALATION_ALREADY_RESOLVED": (409, "The escalation is already RESOLVED."),
    "ERR_REVIEW_ALREADY_DECIDED": (409, "The FinancialReview is not PENDING."),
    "ERR_ELIGIBILITY_ALREADY_DECIDED": (409, "The ProductEligibility is not PENDING."),
    "ERR_LICENSE_NOT_REVOCABLE": (409, "The license is not ACTIVE."),
    "ERR_NET_WORTH_BELOW_MINIMUM": (422, "net_worth_cents is below NET_WORTH_FLOOR_CENTS."),
    "ERR_DECISION_CONDITIONS_REQUIRED": (400, "decision_type is CONDITIONAL but conditions is missing or empty."),
    "ERR_INVALID_REQUEST": (400, "Malformed request body."),
}

# Every identifier the scaffold's error catalogue declares.
DECLARED_ERROR_IDS = sorted(ERROR_TABLE.keys())


class ApiError(Exception):
    """Carries an error_id, a human message and the matching HTTP status."""

    def __init__(self, error_id, message=None, http_status=None):
        if error_id not in ERROR_TABLE:
            raise KeyError("undeclared error_id: %s" % error_id)
        status, default_message = ERROR_TABLE[error_id]
        self.error_id = error_id
        self.message = message if message is not None else default_message
        self.http_status = http_status if http_status is not None else status
        super().__init__("%s: %s" % (self.error_id, self.message))


class ApplicationResult(Exception):
    """Internal control-flow marker: a status change to report as a 200 body."""

    def __init__(self, payload):
        self.payload = payload
        super().__init__("application result")