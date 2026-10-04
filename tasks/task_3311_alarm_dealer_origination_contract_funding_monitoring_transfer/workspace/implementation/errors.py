"""Error catalogue (§1.6) and the ApiError exception.

Every error_id/status pair below is read from the scaffold's errors table and the
PRD §5 catalogue. Field names for the error body come from response_envelope.error.
"""


# error_id -> (http_status, default_message)
ERRORS = {
    "ERR_UNAUTHENTICATED": (401, "Missing or invalid authentication headers."),
    "ERR_UNAUTHORIZED": (403, "The acting role is not permitted for this operation."),
    "ERR_ENTITY_NOT_FOUND": (404, "The referenced entity does not exist."),
    "ERR_FK_INTEGRITY_VIOLATION": (400, "A body foreign key does not resolve to a row."),
    "ERR_MONITORING_ACCOUNT_NOT_FOUND": (404, "No monitoring account is available for this package."),
    "ERR_INVALID_STATE": (409, "The target resource is not in a state from which this transition is declared."),
    "ERR_PACKAGE_NOT_APPROVED": (409, "The package may be funded only from APPROVED."),
    "ERR_CONTRACT_NOT_PENDING": (409, "The contract may be funded only from PENDING_VALIDATION."),
    "ERR_RESCISSION_WINDOW_CLOSED": (409, "The rescission request is outside its window or no longer pending."),
    "ERR_ALARM_ALREADY_VERIFIED": (409, "The alarm event is not PENDING."),
    "ERR_DISPATCH_NOT_REQUESTED": (409, "The dispatch action is not declared from the current state."),
    "ERR_FUNDING_WINDOW_EXPIRED": (409, "The funding window has expired."),
    "ERR_ALARM_OUTSIDE_VERIFIED_WINDOW": (422, "The instant lies outside the permitted window."),
    "ERR_SERVICE_WINDOW_OVERLAP": (422, "The scheduled window collides with an existing slot."),
    "ERR_RESIDENCE_OUTSIDE_SERVICE_RADIUS": (422, "The residence lies outside the relocation service radius."),
    "ERR_SEGREGATION_OF_DUTIES_REQUIRED": (403, "The approving operator must differ from the requestor."),
    "ERR_MASS_CANCEL_BLOCKED": (422, "The mass-cancel guard has tripped for this account."),
    "ERR_FALSE_ALARM_WATCH_ACTIVE": (422, "An open SERVICE_REQUIRED action blocks this operation."),
    "ERR_PACKAGE_REFERENCE_DUPLICATE": (409, "The package reference is already used by this dealer."),
    "ERR_SWEEP_MONTH_DUPLICATE": (409, "An attrition sweep already exists for this month."),
    "ERR_NATURAL_KEY_DUPLICATE": (409, "The natural key already exists."),
    "ERR_NO_FUNDABLE_CONTRACT": (422, "No child contract is fundable."),
    "ERR_PACKAGE_DECLINED": (409, "The whole-package posture declined this child."),
    "ERR_ASSUMED_CONTRACT_MUST_HAVE_SURVIVING_CONTRACT": (422, "The outgoing subscriber would be left with no surviving contract."),
    "ERR_ALARM_NOT_FOR_ACCOUNT": (422, "The alarm event does not belong to the named monitoring account."),
    "ERR_CREDIT_SCORE_BELOW_FLOOR": (422, "The credit score is below the contract quality floor."),
    "ERR_TERM_BELOW_FLOOR": (422, "The contract term is below the contract quality floor."),
    "ERR_EQUIPMENT_CONFIG_NOT_PERMITTED": (422, "The equipment configuration is not permitted for this channel."),
    "ERR_MONITORING_NOT_PROVISIONED": (422, "No monitoring account is PROVISIONED and no waiver exempts the contract."),
    "ERR_DEALER_STANDING_SUSPENDED": (422, "The dealer standing is SUSPENDED."),
    "ERR_DEALER_PACKAGE_SUSPENDED": (422, "The dealer standing is SUSPENDED; packages may not be created or submitted."),
    "ERR_DEALER_CHARGEBACK_RATE_EXCEEDED": (422, "The dealer chargeback rate exceeds the cap."),
    "ERR_HOLDBACK_RATE_EXCEEDS_CEILING": (422, "The holdback rate exceeds the maximum permitted rate."),
    "ERR_CHARGEBACK_WINDOW_CLOSED": (409, "The chargeback is outside its window or the contract is exempt."),
    "ERR_DISCLOSURE_AMOUNT_MISMATCH": (409, "The disclosure amounts no longer match the contract."),
    "ERR_STALE_VERSION": (412, "The expected version does not match the current version."),
    "ERR_INVALID_REQUEST": (400, "The request body is missing a required field or a value is out of range."),
}


class ApiError(Exception):
    """Carries the error_id, message and HTTP status used to build the error envelope."""

    def __init__(self, error_id, message=None, http_status=None):
        if error_id not in ERRORS:
            raise ValueError("unknown error_id: %s" % error_id)
        default_status, default_message = ERRORS[error_id]
        self.error_id = error_id
        self.message = message if message is not None else default_message
        self.http_status = http_status if http_status is not None else default_status
        super().__init__("%s: %s" % (self.error_id, self.message))