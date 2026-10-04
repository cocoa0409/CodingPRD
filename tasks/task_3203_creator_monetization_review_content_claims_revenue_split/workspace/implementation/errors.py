"""Error catalog and the ApiError exception type.

Every error id and HTTP status below is transcribed from SCAFFOLD.yaml
section 1.6 / PRD section 5.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


ERRORS = {
    # --- auth ---------------------------------------------------------------
    "ERR_UNAUTHENTICATED": (401, "X-User-Role header missing or not a declared role."),
    "ERR_FORBIDDEN_ROLE": (403, "The caller's role is not permitted for this operation, or an entity-backed caller is acting on a resource it does not own."),
    # --- existence ----------------------------------------------------------
    "ERR_CHANNEL_NOT_FOUND": (404, "No Channel exists with the supplied channel id."),
    "ERR_CONTENT_ITEM_NOT_FOUND": (404, "No ContentItem exists with the supplied item id for the named channel."),
    "ERR_CLAIM_NOT_FOUND": (404, "No Claim exists with the supplied claim id."),
    "ERR_REFERENCE_FILE_NOT_FOUND": (404, "No ReferenceFile exists with the supplied id."),
    "ERR_PAYOUT_BATCH_NOT_FOUND": (404, "No PayoutBatch exists with the supplied id for the channel."),
    "ERR_APPEAL_NOT_FOUND": (404, "No ClaimAppeal exists with the supplied id for the claim."),
    "ERR_MEMBERSHIP_NOT_FOUND": (404, "No ChannelMembership exists with the supplied id for the channel."),
    # --- state / concurrency ------------------------------------------------
    "ERR_INVALID_STATE": (409, "The target resource is not in a state that admits the requested operation."),
    "ERR_STALE_VERSION": (412, "The expected version supplied on an optimistic-concurrency-guarded write is not the parent's current version."),
    "ERR_CLAIM_ALREADY_DISPUTED": (409, "The claim is already in DISPUTED status."),
    "ERR_CLAIM_TERMINAL": (409, "The claim has reached TAKEN_DOWN and is terminal."),
    "ERR_DISPUTE_WINDOW_CLOSED": (409, "The claim's thirty-day dispute window has lapsed."),
    "ERR_APPEAL_LIMIT_REACHED": (409, "The appeal ladder allows at most two appeals per claim."),
    "ERR_APPEAL_ALREADY_PENDING": (409, "The claim already has a ClaimAppeal in status PENDING."),
    "ERR_APPEAL_LOCKOUT": (409, "A reinstated claim may be re-appealed only after the fourteen-day appeal lockout."),
    "ERR_CONTENT_ITEM_NOT_TAKEN_DOWN": (409, "The targeted claim is not in TAKEN_DOWN status."),
    # --- posture ------------------------------------------------------------
    "ERR_POSTURE_FROZEN": (409, "The channel's monetization posture is FROZEN."),
    "ERR_POSTURE_RESTRICTED": (409, "The channel's monetization posture is RESTRICTED."),
    # --- monetization -------------------------------------------------------
    "ERR_MONETIZATION_INELIGIBLE": (409, "The channel does not meet the watch-hour and subscriber eligibility thresholds."),
    "ERR_MONETIZATION_BLOCKED_BY_STRIKE": (409, "The channel carries an active policy strike and may not apply for monetization."),
    "ERR_CLASSIFICATION_BLOCKS_MONETIZATION": (409, "A reviewed content item carries ad_suitability NO_ADS."),
    # --- references / claims ------------------------------------------------
    "ERR_DUPLICATE_REFERENCE_FINGERPRINT": (409, "The reference fingerprint is already registered."),
    "ERR_INVALID_MATCH_CONFIDENCE": (400, "match_confidence must lie within the inclusive range 0.500 to 1.000."),
    "ERR_INVALID_CATEGORY_CODE": (400, "A supplied category code is outside the recognised vocabulary."),
    # --- fiscal -------------------------------------------------------------
    "ERR_BELOW_PAYMENT_THRESHOLD": (409, "The payout batch's adjusted net balance has not reached the channel payment threshold."),
    "ERR_NO_ELIGIBLE_MEMBERS": (409, "The channel has no ACTIVE membership to pay."),
    "ERR_UNSUPPORTED_STREAM_TYPE": (400, "The stream type is outside AD | MEMBERSHIP | SUPER_CHAT | SHOPPING."),
}


def raise_error(error_id, message=None):
    status, default_message = ERRORS[error_id]
    raise ApiError(error_id, status, message or default_message)