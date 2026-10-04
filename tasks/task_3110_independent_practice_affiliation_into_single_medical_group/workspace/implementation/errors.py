"""Error types and the error catalog."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# --- helpers producing catalog errors ---
def err_auth(msg="Missing or malformed X-User-ID / X-User-Role header"):
    return ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", msg, 400)


def err_perms(msg="Role not permitted on this endpoint"):
    return ApiError("ERR_INSUFFICIENT_PERMISSIONS", msg, 403)


def err_ownership(msg="PracticeExecutive X-User-ID does not match target practice_id"):
    return ApiError("ERR_PRACTICE_OWNERSHIP_MISMATCH", msg, 403)


def err_sod(msg="Finalizer X-User-ID matches a covered batch's settled_by_user_id"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", msg, 403)


def err_not_found(resource, msg=None):
    return ApiError(f"ERR_{resource}_NOT_FOUND", msg or f"{resource} not found", 404)


def err_invalid(msg="Invalid request"):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


def err_stale(msg="expected version does not match current version"):
    return ApiError("ERR_STALE_VERSION", msg, 412)


def err_transition(msg="State machine has no transition from current state"):
    return ApiError("ERR_INVALID_TRANSITION", msg, 409)


def err_group_not_operating(msg="Group is not OPERATING"):
    return ApiError("ERR_GROUP_NOT_OPERATING", msg, 409)


def err_practice_not_affiliated(msg="Practice is not AFFILIATED/DEPARTING"):
    return ApiError("ERR_PRACTICE_NOT_AFFILIATED", msg, 409)


def err_contract_not_active(msg="Contract is not ACTIVE"):
    return ApiError("ERR_CONTRACT_NOT_ACTIVE", msg, 409)


def err_pool_not_scoring(msg="Pool is not SCORING"):
    return ApiError("ERR_POOL_NOT_SCORING", msg, 409)


def err_allocation_not_payable(msg="Allocation is not PAYABLE"):
    return ApiError("ERR_ALLOCATION_NOT_PAYABLE", msg, 409)


def err_no_wave(msg="No IN_CUTOVER wave in the practice's market"):
    return ApiError("ERR_NO_WAVE_IN_CUTOVER", msg, 409)


def err_no_ratification(msg="No PASSED ratification vote on the contract"):
    return ApiError("ERR_NO_PASSED_RATIFICATION_VOTE", msg, 422)


def err_no_voters(msg="Zero eligible voters in the market"):
    return ApiError("ERR_NO_ELIGIBLE_VOTERS", msg, 422)


def err_dup_vote(msg="Provider already cast a ballot on this vote"):
    return ApiError("ERR_DUPLICATE_VOTE", msg, 409)


def err_cutover(msg="Cutover window violation"):
    return ApiError("ERR_INVALID_CUTOVER_WINDOW", msg, 422)


def err_expedited(msg="EXPEDITED request span exceeds 45 days"):
    return ApiError("ERR_EXPEDITED_WINDOW_EXCEEDED", msg, 422)


def err_wave_overlap(msg="Wave cutover window overlaps another wave in the market"):
    return ApiError("ERR_WAVE_WINDOW_OVERLAP", msg, 409)


def err_enroll_overlap(msg="Enrollment window overlaps another enrollment"):
    return ApiError("ERR_ENROLLMENT_WINDOW_OVERLAP", msg, 409)


def err_market_capacity(msg="Market at capacity"):
    return ApiError("ERR_MARKET_AT_CAPACITY", msg, 409)


def err_dup_batch(msg="Batch already exists for (practice, contract, period)"):
    return ApiError("ERR_DUPLICATE_BATCH", msg, 409)


def err_dup_statement(msg="Statement already exists for (practice, period)"):
    return ApiError("ERR_DUPLICATE_STATEMENT", msg, 409)


def err_no_effective(msg="No EFFECTIVE enrollment links practice to contract"):
    return ApiError("ERR_NO_EFFECTIVE_ENROLLMENT", msg, 422)


def err_unsettled(msg="A POSTED batch exists in the practice's period"):
    return ApiError("ERR_UNSETTLED_BATCHES_EXIST", msg, 422)


def err_uplift(msg="Average fee-schedule uplift below 0.08 or no PROPOSED rates"):
    return ApiError("ERR_FEE_SCHEDULE_UPLIFT_INSUFFICIENT", msg, 422)


def err_non_compete(msg="non_compete_accepted must be true"):
    return ApiError("ERR_NON_COMPETE_ACK_REQUIRED", msg, 422)


def err_exit_not_reached(msg="Clock date is before earliest_exit_date"):
    return ApiError("ERR_EXIT_DATE_NOT_REACHED", msg, 422)


def err_no_eligible(msg="No ENTERED allocation meets the quality threshold"):
    return ApiError("ERR_NO_ELIGIBLE_ALLOCATIONS", msg, 422)
