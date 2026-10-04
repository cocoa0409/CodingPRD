"""Error catalog (scaffold 1.6 / PRD 5) + the ApiError carrier."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err(error_id, http_status, message):
    return ApiError(error_id, http_status, message)


# --- convenience constructors (band -> error id is fixed by the catalog) ---
def unauthenticated(msg="Authentication failed"):
    return err("ERR_UNAUTHENTICATED", 401, msg)


def unauthorized_role(msg="Role is not authorized for this operation"):
    return err("ERR_UNAUTHORIZED_ROLE", 403, msg)


def invalid_request(msg="Request is malformed"):
    return err("ERR_INVALID_REQUEST", 400, msg)


def not_found(msg="Resource not found"):
    return err("ERR_NOT_FOUND", 404, msg)


def cycle_not_open(msg="Election cycle is not OPEN"):
    return err("ERR_CYCLE_NOT_OPEN", 409, msg)


def invalid_state(msg="Entity is not in a state that allows this operation"):
    return err("ERR_INVALID_STATE", 409, msg)


def questionnaire_not_accepting(msg="Questionnaire is not accepting submissions"):
    return err("ERR_QUESTIONNAIRE_NOT_ACCEPTING_SUBMISSIONS", 409, msg)


def filing_not_verified(msg="The shell's filing is not VERIFIED"):
    return err("ERR_FILING_NOT_VERIFIED", 409, msg)


def questionnaire_not_pinned(msg="The contest's questionnaire is not PINNED"):
    return err("ERR_QUESTIONNAIRE_NOT_PINNED", 422, msg)


def stale_version(msg="Expected version does not match the current version"):
    return err("ERR_STALE_VERSION", 412, msg)


def volunteer_suspended(msg="Volunteer is SUSPENDED"):
    return err("ERR_VOLUNTEER_SUSPENDED", 403, msg)


def attestation_lapsed(msg="Volunteer attestation is LAPSED"):
    return err("ERR_ATTESTATION_LAPSED", 403, msg)


def advocacy_separation(msg="Volunteer holds an advocacy position"):
    return err("ERR_ADVOCACY_SEPARATION", 403, msg)


def moderator_not_qualified(msg="Referenced moderator lacks the MODERATOR capability"):
    return err("ERR_MODERATOR_NOT_QUALIFIED", 422, msg)


def sod_drafter_cannot_review(msg="The measure's drafter may not review it"):
    return err("ERR_SOD_DRAFTER_CANNOT_REVIEW", 403, msg)


def sod_moderator_own_question(msg="A moderator may not select their own authored question"):
    return err("ERR_SOD_MODERATOR_OWN_QUESTION", 403, msg)


def only_drafter_may_revise(msg="Only the measure's drafter may perform this action"):
    return err("ERR_ONLY_DRAFTER_MAY_REVISE", 403, msg)


def neutrality_review_outstanding(msg="A neutrality review is outstanding in the cycle"):
    return err("ERR_NEUTRALITY_REVIEW_OUTSTANDING", 422, msg)


def filing_deadline_passed(msg="The filing deadline has passed"):
    return err("ERR_FILING_DEADLINE_PASSED", 422, msg)


def filing_still_open(msg="The filing window is still open"):
    return err("ERR_FILING_STILL_OPEN", 422, msg)


def submission_window_closed(msg="The questionnaire submission window has closed"):
    return err("ERR_SUBMISSION_WINDOW_CLOSED", 422, msg)


def close_before_deadline(msg="The questionnaire cannot be closed before its deadline"):
    return err("ERR_CLOSE_BEFORE_DEADLINE", 422, msg)


def forum_time_overlap(msg="The forum overlaps another forum in the jurisdiction"):
    return err("ERR_FORUM_TIME_OVERLAP", 422, msg)


def moderator_buffer_violation(msg="The moderator's forums are not buffered by 24 hours"):
    return err("ERR_MODERATOR_BUFFER_VIOLATION", 422, msg)


def forum_not_concluded(msg="The forum has not concluded yet"):
    return err("ERR_FORUM_NOT_CONCLUDED", 422, msg)


def duplicate_fips(msg="fips_code is already used in this cycle"):
    return err("ERR_DUPLICATE_FIPS", 409, msg)


def duplicate_filing_reference(msg="filing_reference is already used in this contest"):
    return err("ERR_DUPLICATE_FILING_REFERENCE", 409, msg)


def duplicate_questionnaire(msg="The contest already has a questionnaire"):
    return err("ERR_DUPLICATE_QUESTIONNAIRE", 409, msg)


def duplicate_measure(msg="The contest already has a ballot measure"):
    return err("ERR_DUPLICATE_MEASURE", 409, msg)


def duplicate_review_this_round(msg="Reviewer already reviewed this measure in the current round"):
    return err("ERR_DUPLICATE_REVIEW_THIS_ROUND", 409, msg)


def contest_kind_mismatch(msg="The contest kind does not support this resource"):
    return err("ERR_CONTEST_KIND_MISMATCH", 422, msg)


def missing_pro_or_con(msg="At least one ACCEPTED PRO and one ACCEPTED CON argument are required"):
    return err("ERR_MISSING_PRO_OR_CON", 422, msg)


def forum_quorum_not_met(msg="Fewer than two eligible candidates"):
    return err("ERR_FORUM_QUORUM_NOT_MET", 422, msg)


def question_cap_reached(msg="The forum already has five selected questions"):
    return err("ERR_QUESTION_CAP_REACHED", 422, msg)


def language_unsupported(msg="The edition language is not supported by every jurisdiction"):
    return err("ERR_LANGUAGE_UNSUPPORTED", 422, msg)


def accessibility_grade_exceeded(msg="An approved measure exceeds the accessibility grade threshold"):
    return err("ERR_ACCESSIBILITY_GRADE_EXCEEDED", 422, msg)


def stale_snapshot(msg="A pinned contest or questionnaire version has advanced"):
    return err("ERR_STALE_SNAPSHOT", 422, msg)


def contests_not_locked(msg="Not every contest of the cycle is LOCKED"):
    return err("ERR_CONTESTS_NOT_LOCKED", 422, msg)


def unresolved_incidents_exist(msg="A policy incident remains REPORTED"):
    return err("ERR_UNRESOLVED_INCIDENTS_EXIST", 422, msg)


def no_distributed_edition(msg="No guide edition has been distributed"):
    return err("ERR_NO_DISTRIBUTED_EDITION", 422, msg)
