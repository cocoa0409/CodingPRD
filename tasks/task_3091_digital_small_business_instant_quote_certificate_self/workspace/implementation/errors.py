"""Error type and error id constants (from the scaffold error catalog)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def unauthenticated(msg="Missing or invalid X-User-ID or X-User-Role headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def forbidden_role(msg="Role not permitted for this endpoint"):
    return ApiError("ERR_FORBIDDEN_ROLE", 403, msg)


def not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def invalid_state(msg="Resource state forbids the operation"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def stale_quote_version(msg="expected_quote_version mismatch"):
    return ApiError("ERR_STALE_QUOTE_VERSION", 412, msg)


def stale_policy_version(msg="expected_policy_version mismatch"):
    return ApiError("ERR_STALE_POLICY_VERSION", 412, msg)


def quote_expired(msg="Quote has expired"):
    return ApiError("ERR_QUOTE_EXPIRED", 409, msg)


def quote_basis_stale(msg="premium_basis_hash changed since issuance"):
    return ApiError("ERR_QUOTE_BASIS_STALE", 409, msg)


def class_ambiguous(msg="Ambiguous class-of-business determination"):
    return ApiError("ERR_CLASS_AMBIGUOUS", 422, msg)


def class_declined(msg="No admitted class for the description"):
    return ApiError("ERR_CLASS_DECLINED", 422, msg)


def appetite_window_invalid(msg="effective_from must be strictly before effective_to"):
    return ApiError("ERR_APPETITE_WINDOW_INVALID", 422, msg)


def line_not_eligible(msg="Lines not eligible for the class"):
    return ApiError("ERR_LINE_NOT_ELIGIBLE", 422, msg)


def last_line_removal(msg="Removal would leave zero in-force lines"):
    return ApiError("ERR_LAST_LINE_REMOVAL", 422, msg)


def line_overlap(msg="Added and removed lines overlap or line already in force"):
    return ApiError("ERR_LINE_OVERLAP", 422, msg)


def endorsement_window(msg="effective_at outside the endorsement window"):
    return ApiError("ERR_ENDORSEMENT_WINDOW", 422, msg)


def exposure_negative(msg="exposure_units must be >= 0"):
    return ApiError("ERR_EXPOSURE_NEGATIVE", 422, msg)


def uw_answers_incomplete(msg="Required underwriting answers missing"):
    return ApiError("ERR_UW_ANSWERS_INCOMPLETE", 422, msg)


def claim_window(msg="loss_occurred_at outside coverage or intake window"):
    return ApiError("ERR_CLAIM_WINDOW", 422, msg)


def claim_amount_floor(msg="claim_amount_cents must be >= 100"):
    return ApiError("ERR_CLAIM_AMOUNT_FLOOR", 422, msg)


def evidence_size(msg="file_size_bytes outside [1024, 10485760]"):
    return ApiError("ERR_EVIDENCE_SIZE", 422, msg)


def evidence_future(msg="exif_taken_at after claim intake instant"):
    return ApiError("ERR_EVIDENCE_FUTURE", 422, msg)


def segregation_of_duties(msg="FinanceOfficer cannot pay a claim they reviewed"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", 422, msg)


def not_review_owner(msg="Only the adjuster_owner may decide the claim"):
    return ApiError("ERR_NOT_REVIEW_OWNER", 409, msg)


def open_claims_block(msg="Open claims block this operation"):
    return ApiError("ERR_OPEN_CLAIMS_BLOCK", 409, msg)


def renewal_window(msg="Renewal outside [renewal_window_start, term_end)"):
    return ApiError("ERR_RENEWAL_WINDOW", 422, msg)


def renewal_notice_issued(msg="Non-renewal notice already issued"):
    return ApiError("ERR_RENEWAL_NOTICE_ISSUED", 409, msg)


def appetite_inactive(msg="Class is off-appetite"):
    return ApiError("ERR_APPETITE_INACTIVE", 409, msg)


def nonrenewal_statute(msg="days_before_term_end below statutory minimum"):
    return ApiError("ERR_NONRENEWAL_STATUTE", 422, msg)


def nonrenewal_duplicate(msg="Policy already has a non-renewal notice"):
    return ApiError("ERR_NONRENEWAL_DUPLICATE", 409, msg)


def cert_endorsement_invalid(msg="Endorsement is not an EFFECTIVE ADDITIONAL_INSURED on this policy"):
    return ApiError("ERR_CERT_ENDORSEMENT_INVALID", 422, msg)


def channel_mismatch(msg="Channel/partner mismatch"):
    return ApiError("ERR_CHANNEL_MISMATCH", 422, msg)


def validation(msg="Malformed request body"):
    return ApiError("ERR_VALIDATION", 400, msg)


def reject_unknown_keys(body, allowed):
    """PRD §2.7: a malformed request body — wrong types, unknown fields — is
    rejected with ERR_VALIDATION (HTTP 400)."""
    extra = set(body.keys()) - set(allowed)
    if extra:
        raise validation(f"Unknown field(s): {sorted(extra)}")
