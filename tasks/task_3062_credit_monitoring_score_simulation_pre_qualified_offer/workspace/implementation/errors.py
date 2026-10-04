"""Error catalogue and the ApiError exception used by every route."""

# error_id -> (http_status, default_message)
ERROR_CATALOG = {
    "ERR_INVALID_REQUEST": (400, "The request is malformed or missing required headers or fields."),
    "ERR_FORBIDDEN_FOR_ROLE": (403, "The caller's role is not permitted for this endpoint."),
    "ERR_CONSUMER_NOT_FOUND": (404, "A path-segment id did not resolve to an existing resource."),
    "ERR_INVALID_STATE_TRANSITION": (409, "The target resource is in a status from which the requested transition is not declared."),
    "ERR_PRIOR_BUREAU_SNAPSHOT_EXISTS": (409, "Monitoring consent cannot be granted after bureau data has landed."),
    "ERR_MONITORING_CONSENT_ALREADY_GRANTED": (409, "Monitoring consent has already been granted for this consumer."),
    "ERR_MONITORING_NOT_CONSENTED": (409, "A bureau pull requires monitoring consent."),
    "ERR_PULL_COOLDOWN_ACTIVE": (409, "A pull or replay was requested inside the 24-hour cooldown window."),
    "ERR_PULL_RESULT_EMPTY": (409, "The submitted pull-result census carried no entry."),
    "ERR_SNAPSHOT_MOVED": (409, "The pinned snapshot attached to the decision is no longer active."),
    "ERR_SHARED_CRITERION_NO_SNAPSHOT": (409, "A shared criterion was evaluated against a snapshot that no longer exists."),
    "ERR_STALE_VERSION": (412, "The supplied expected_consumer_version does not match the consumer's current version."),
    "ERR_SIMULATION_NEEDS_SNAPSHOT": (409, "A score simulation requires at least one successful bureau pull."),
    "ERR_QUALIFY_OVER_REPRESENTED": (409, "The consumer is over-represented for this product, so the decision may not be qualified."),
    "ERR_OFFER_PRESENTATION_CAP_EXCEEDED": (409, "The consumer's presentation cap for this product kind has been reached."),
    "ERR_PRESENTATION_INELIGIBLE": (409, "The presentation policy is not satisfied for the pinned snapshot and program."),
    "ERR_PRESENTATION_BLOCKED": (409, "Adverse-selection gating blocks presentation of this offer."),
    "ERR_CONSUMER_STATE_EXCLUDED": (409, "The consumer's state is outside the sponsor's served states."),
    "ERR_LENDER_SERVES_STATE_REQUIRED": (409, "The sponsor does not serve the consumer's state, so no decision may be created."),
    "ERR_COLLATERAL_ELIGIBILITY_CHANGED": (409, "A pinned targeting criterion no longer matches the consumer's current data."),
    "ERR_RENDER_COMPLETENESS_INCOMPLETE": (409, "Whole-render completeness does not hold for the pinned snapshot and program."),
    "ERR_CONSENT_NOT_PENDING": (409, "No pending consent record exists for this consumer and decision."),
    "ERR_CONSENT_ALREADY_CONSUMED": (409, "The one-time consent has already been consumed."),
    "ERR_CONSENT_DECISION_NOT_PREQUALIFIED": (409, "Consent may only be recorded for a pre-qualified decision."),
    "ERR_OFFER_EXPIRED": (409, "The decision's freshness window has passed, so the offer is unpresentable."),
    "ERR_OFFER_NOT_RENDERED": (409, "A referral may only be opened from a rendered offer."),
    "ERR_REFERRAL_NOT_FUNDED": (409, "The referral has never been funded."),
    "ERR_CLAWBACK_WINDOW_CLOSED": (409, "The reversal instant falls after the clawback window closed."),
    "ERR_REFERRAL_ALREADY_FUNDED": (409, "The referral is already in a terminal status."),
    "ERR_CLAWBACK_ALREADY_APPLIED": (409, "A clawback has already been posted for this referral."),
    "ERR_DUPLICATE_REFERRAL_REF": (409, "external_referral_ref is not unique across referrals."),
    "ERR_DISPUTE_CAP_EXCEEDED": (409, "More than three dispute referrals are held in SUBMITTED_OFFLINE at once."),
    "ERR_DISPUTE_SNAPSHOT_REQUIRED": (409, "A dispute referral requires an existing bureau snapshot."),
    "ERR_PROGRAM_NOT_DELIVERABLE": (409, "The logical clock is outside the program's go-live/expiry interval."),
    "ERR_PROGRAM_PAUSED": (409, "The sponsoring program is paused or expired."),
    "ERR_PROGRAM_CODE_DUPLICATE": (409, "program_code is not unique across lender programs."),
    "ERR_LENDER_NOT_ACTIVE": (409, "The sponsoring lender is not active."),
    "ERR_LENDER_NOT_COMPLIANT": (409, "The lender's compliance status is not APPROVED."),
    "ERR_LENDER_HAS_ACTIVE_PROGRAM": (409, "The lender still sponsors an active program."),
    "ERR_ITEM_HAS_ACTIVE_PROGRAM": (409, "An active program still references this catalog item."),
    "ERR_ITEM_NO_SCORE_TIER": (409, "No active score tier intersects this item's score band."),
    "ERR_TIER_CODE_DUPLICATE": (409, "tier_code is already held by an active score tier."),
    "ERR_TIER_BAND_OVERLAP": (409, "The tier band overlaps another active tier's band."),
    "ERR_FACET_SCORE_BELOW_MINIMUM": (409, "The facet score is below the content quality minimum."),
    "ERR_CONSUMER_HAS_OPEN_REFERRAL": (409, "The consumer still has a referral in SENT status."),
    "ERR_CONSUMER_HAS_OPEN_DECISION": (409, "The consumer still has an open decision."),
    "ERR_OPS_RUN_KEY_DUPLICATE": (409, "run_key is not unique across operations runs."),
    "ERR_CLOCK_NOT_MONOTONIC": (409, "The logical clock may not be set to an earlier instant."),
}


class ApiError(Exception):
    """Carries the catalogue error id, HTTP status and human message."""

    def __init__(self, error_id, message=None, http_status=None):
        self.error_id = error_id
        if http_status is None:
            http_status = ERROR_CATALOG.get(error_id, (500, ""))[0]
        self.http_status = http_status
        if message is None:
            message = ERROR_CATALOG.get(error_id, (500, ""))[1]
        self.message = message
        super().__init__(message)


def fail(error_id, message=None, http_status=None):
    raise ApiError(error_id, message, http_status)