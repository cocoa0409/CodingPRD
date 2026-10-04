"""Error types and catalog."""


class ApiError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err_missing_context(msg="X-User-ID or X-User-Role header missing or malformed"):
    return ApiError("ERR_MISSING_CONTEXT", msg, 400)


def err_forbidden_role(msg="Role not permitted for this endpoint"):
    return ApiError("ERR_FORBIDDEN_ROLE", msg, 403)


def err_not_found(msg="Resource does not exist"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def err_invalid_input(msg="Missing required field, invalid enum, or range violation"):
    return ApiError("ERR_INVALID_INPUT", msg, 400)


def err_invalid_state(msg="Requested transition not valid from current state"):
    return ApiError("ERR_INVALID_STATE", msg, 409)


def err_sod(msg="Actor of this step must differ from actor of the prior step"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", msg, 409)


def err_reference_state(msg="Cross-entity state precondition failed"):
    return ApiError("ERR_REFERENCE_STATE", msg, 409)


def err_temporal(msg="Temporal rule violated"):
    return ApiError("ERR_TEMPORAL_CONFLICT", msg, 409)


def err_fiscal(msg="Fiscal rule violated"):
    return ApiError("ERR_FISCAL_BLOCK", msg, 422)


def err_stale_season(msg="Roster batch publish against a stale season version"):
    return ApiError("ERR_STALE_SEASON_VERSION", msg, 412)


def err_stale_program(msg="Payout finalize against a stale tournament program version"):
    return ApiError("ERR_STALE_PROGRAM_VERSION", msg, 412)


def err_exclusivity(msg="Activating agreement would overlap an ACTIVE/SUSPENDED exclusive agreement"):
    return ApiError("ERR_EXCLUSIVITY_CONFLICT", msg, 409)


def err_athlete_not_eligible(msg="Athlete lacks a GRANTED likeness grant required for this operation"):
    return ApiError("ERR_ATHLETE_NOT_ELIGIBLE", msg, 409)


def err_drop_window(msg="Content drop release attempted outside [scheduled_start_at, scheduled_end_at)"):
    return ApiError("ERR_DROP_WINDOW", msg, 409)


def err_censorship(msg="Drop content conflicts with a RELEASED regional edition's censorship flags"):
    return ApiError("ERR_CENSORSHIP_CONFLICT", msg, 409)


def err_empty_batch(msg="Roster batch validate/publish attempted with zero entries"):
    return ApiError("ERR_EMPTY_BATCH", msg, 409)


def err_rollback_not_head(msg="Rollback attempted on a batch that is not the most recently published batch"):
    return ApiError("ERR_ROLLBACK_NOT_HEAD", msg, 409)


def err_audit_window(msg="Audit opened after agreement.audit_window_days past statement finalization"):
    return ApiError("ERR_AUDIT_WINDOW_MISSED", msg, 409)


def err_audit_blocks_termination(msg="Agreement termination blocked by an OPEN or FINDINGS_FILED audit case"):
    return ApiError("ERR_AUDIT_BLOCKS_TERMINATION", msg, 409)


def err_wallet_frozen(msg="Debit attempted on a FROZEN wallet"):
    return ApiError("ERR_WALLET_FROZEN", msg, 409)


def err_insufficient_vc(msg="Wallet balance below debit amount"):
    return ApiError("ERR_INSUFFICIENT_VC", msg, 422)


def err_prize_shares(msg="Prize share_bps rows do not total 10000 at record-results"):
    return ApiError("ERR_PRIZE_SHARES_INVALID", msg, 422)


def err_unsanctioned(msg="finalize-payout on a program with league_sanctioned == false"):
    return ApiError("ERR_UNSANCTIONED_PAYOUT", msg, 422)


def err_grant_term(msg="Likeness grant term not contained in the agreement term"):
    return ApiError("ERR_GRANT_TERM_OUTSIDE_AGREEMENT", msg, 409)


def err_college_opt_in(msg="COLLEGE athlete grant requires college_opt_in == true"):
    return ApiError("ERR_COLLEGE_OPT_IN_REQUIRED", msg, 409)


def err_audio_uncovered(msg="Operation requires an ACTIVE audio license covering the asset"):
    return ApiError("ERR_AUDIO_UNCOVERED", msg, 409)
