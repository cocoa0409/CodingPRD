"""Teacher onboarding: screening, sample review and the reviewer revision loop."""
from test_helpers import (
    ApiErrorId,
    create_application,
    get_success_data,
    make_platform_admin_headers,
    make_teacher_applicant_headers,
    onboard_active_teacher,
    review_sample,
    setup_application_at_sample_pending,
    submit_sample,
    validate_error,
)


def test_rejected_sample_returns_application_to_sample_pending(api):
    """PRD §3.1: "A rejected sample may be resubmitted as a revision, which returns
    the application from `SAMPLE_REJECTED` to `SAMPLE_PENDING`, releases the reviewer
    binding and clears `decision`; this loop is available only while `revision_count`
    is below 3, and the resubmitted sample must again be at least 5 minutes long."
    PRD §3.1: "The same stage with `verdict` as `FAIL` moves the application to
    `SAMPLE_REJECTED` instead: the reviewer is bound the same way, `decision` becomes
    `REJECT`, `decision_reason_code` becomes `SAMPLE_QUALITY`, and `revision_count` is
    incremented."

    Design: Difficulty/non_linear_state_machine/application_sample_revision_cycle
    """
    application = setup_application_at_sample_pending()
    assert application["status"] == "SAMPLE_PENDING"
    assert application["revision_count"] == 0

    rejected = review_sample(application["id"], "FAIL", reason_code="SAMPLE_QUALITY")
    assert rejected["status"] == "SAMPLE_REJECTED", "a FAIL sample verdict lands in SAMPLE_REJECTED"
    assert rejected["decision"] == "REJECT"
    assert rejected["decision_reason_code"] == "SAMPLE_QUALITY"
    assert rejected["revision_count"] == 1, "the rejection increments the revision counter"

    reopened = submit_sample(
        application["id"],
        sample_url="https://samples.example.com/ada-v2.mp4",
        sample_minutes=12,
    )
    assert reopened["status"] == "SAMPLE_PENDING", (
        "the same application re-entered SAMPLE_PENDING, so the machine traversed a cycle"
    )
    assert reopened["revision_count"] == 1, "the revision counter survives the resubmission"
    assert reopened["reviewed_by_user_id"] is None, "the reviewer binding is released on resubmission"
    assert reopened["decision"] is None, "the decision is cleared on resubmission"

    fresh = get_success_data(
        api.get_teacher_application(application["id"], make_teacher_applicant_headers())
    )
    assert fresh["status"] == "SAMPLE_PENDING"


def test_revision_cycle_repeats_while_the_budget_lasts(api):
    """PRD §3.1: "A rejected sample may be resubmitted as a revision, which returns
    the application from `SAMPLE_REJECTED` to `SAMPLE_PENDING`, releases the reviewer
    binding and clears `decision`; this loop is available only while `revision_count`
    is below 3, and the resubmitted sample must again be at least 5 minutes long."

    Design: Difficulty/non_linear_state_machine/application_sample_revision_cycle
    """
    application = setup_application_at_sample_pending()

    first_rejection = review_sample(application["id"], "FAIL", reason_code="SAMPLE_QUALITY")
    assert first_rejection["revision_count"] == 1
    first_reopen = submit_sample(application["id"], sample_minutes=11)
    assert first_reopen["status"] == "SAMPLE_PENDING"

    second_rejection = review_sample(application["id"], "FAIL", reason_code="SAMPLE_QUALITY")
    assert second_rejection["status"] == "SAMPLE_REJECTED"
    assert second_rejection["revision_count"] == 2, (
        "the second rejection accumulates onto the same counter rather than resetting it"
    )
    second_reopen = submit_sample(application["id"], sample_minutes=13)
    assert second_reopen["status"] == "SAMPLE_PENDING"
    assert second_reopen["revision_count"] == 2
    assert second_reopen["reviewed_by_user_id"] is None

    fresh = get_success_data(
        api.get_teacher_application(application["id"], make_teacher_applicant_headers())
    )
    assert fresh["status"] == "SAMPLE_PENDING"
    assert fresh["decision"] is None


def test_teaching_sample_below_minimum_minutes_rejected(api):
    """PRD §2.6: "A teaching sample's duration is at least 5 whole minutes. Any failure
    here is `ERR_SAMPLE_TOO_SHORT` (HTTP 400), and it applies to application creation,
    application submission and teaching-sample submission."

    Design: Corner/validations/teaching_sample_below_minimum_minutes_rejected
    """
    response = api.create_teacher_application(
        {
            "applicant_user_id": "u_short",
            "applicant_email": "short@example.com",
            "display_name": "Short Sample",
            "teaching_sample_url": "https://samples.example.com/short.mp4",
            "teaching_sample_minutes": 2,
        },
        make_teacher_applicant_headers("u_short"),
    )
    error = validate_error(response, ApiErrorId.ERR_SAMPLE_TOO_SHORT)
    assert error["error_id"] == "ERR_SAMPLE_TOO_SHORT"


def test_activating_an_already_active_teacher_returns_invalid_state(api):
    """PRD §3.2: "A `PlatformAdmin` activates the account, moving it from
    `PENDING_SETUP` to `ACTIVE`; the activation is gated on `payout_tax_document_status`
    being `ON_FILE`, so a teacher with an outstanding tax-document problem cannot be
    brought online."
    PRD §2.6: "The target resource is in a state from which the requested transition is
    declared. Any failure here is `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/errors/activating_an_already_active_teacher_returns_invalid_state
    """
    teacher = onboard_active_teacher()
    assert teacher["status"] == "ACTIVE"

    response = api.activate_teacher(teacher["id"], make_platform_admin_headers())
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)

    fresh = get_success_data(api.get_teacher(teacher["id"], make_platform_admin_headers()))
    assert fresh["status"] == "ACTIVE"


def test_reinstating_a_never_suspended_teacher_returns_invalid_state(api):
    """PRD §3.2: "Reinstatement returns a `SUSPENDED` teacher to `ACTIVE` and requires
    two conditions beyond the state itself: the tax-document status must be `ON_FILE`,
    and `peak_actionable_risk_score` must be strictly below 40."
    PRD §2.6: "The target resource is in a state from which the requested transition is
    declared. Any failure here is `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/errors/reinstate_without_suspension_returns_invalid_state
    """
    teacher = onboard_active_teacher()
    assert teacher["suspension_trigger"] is None

    response = api.reinstate_teacher(teacher["id"], make_platform_admin_headers())
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)

    fresh = get_success_data(api.get_teacher(teacher["id"], make_platform_admin_headers()))
    assert fresh["status"] == "ACTIVE"
    assert fresh["suspension_trigger"] is None
