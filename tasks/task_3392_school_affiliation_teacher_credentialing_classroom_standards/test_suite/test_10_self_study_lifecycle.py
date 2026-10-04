"""Self-study lifecycle: the DRAFT -> SUBMITTED -> RETURNED_FOR_REVISION ->
SUBMITTED -> ACCEPTED loop, the terminal lockdown of ACCEPTED with the school
catalog pin, and the one-in-flight constraint.
"""

from test_helpers import (
    ApiErrorId,
    create_accepted_self_study,
    create_active_catalog,
    create_self_study,
    create_self_study_payload,
    create_school,
    make_school_admin_headers,
    read_self_study,
    read_school,
    reset_clock,
    review_self_study,
    school_version,
    submit_self_study,
    validate_error,
)


def test_self_study_revision_cycle_resubmits(api):
    """PRD section 3.6: "A `RETURNED_FOR_REVISION` outcome reopens the cycle,
    and resubmission re-evaluates against the current state." PRD section 3.6:
    "A study in `DRAFT` — or one returned for revision — is submitted by its
    `SchoolAdmin`; the `narrative` must be non-empty (`ERR_VALIDATION`,
    HTTP 400), and submission records `submitted_at` and lands the study in
    `SUBMITTED`."

    Design: Difficulty/non_linear_state_machine/self_study_revision_cycle
    """
    reset_clock()
    create_active_catalog()
    school = create_school(name="S School", display_name="S Schoolhouse")
    study = create_self_study(school["id"], narrative="Cycle test narrative")

    submit_self_study(study["id"], school["id"])
    returned = review_self_study(
        study["id"], "RETURNED_FOR_REVISION", notes="Strengthen the materials section"
    )
    assert returned["status"] == "RETURNED_FOR_REVISION"

    resubmitted = submit_self_study(study["id"], school["id"])
    assert resubmitted["status"] == "SUBMITTED", "the revision loop closes"
    assert resubmitted["submitted_at"] is not None

    accepted = review_self_study(study["id"], "ACCEPTED")
    assert accepted["status"] == "ACCEPTED"


def test_self_study_accepted_is_terminal_and_pins_catalog(api):
    """PRD section 3.6: "An `ACCEPTED` outcome is terminal and momentous: the
    school adopts the study's pinned edition as its own `pinned_catalog_id`,
    which drives classroom-audit scoring from then on, and the school's
    `version` increments." PRD section 3.6: "only a `SUBMITTED` study is
    actionable (`ERR_INVALID_STATE`, HTTP 409 otherwise)".

    Design: Difficulty/non_linear_state_machine/self_study_revision_cycle
    """
    reset_clock()
    catalog = create_active_catalog()
    school = create_school(name="S School", display_name="S Schoolhouse")
    study = create_self_study(school["id"], narrative="Cycle test narrative")
    submit_self_study(study["id"], school["id"])
    review_self_study(study["id"], "RETURNED_FOR_REVISION")
    submit_self_study(study["id"], school["id"])
    review_self_study(study["id"], "ACCEPTED")

    assert read_school(school["id"])["pinned_catalog_id"] == catalog["id"]

    rejected = api.submit_self_study(
        study["id"], headers=make_school_admin_headers(school["id"])
    )
    validate_error(rejected, ApiErrorId.ERR_INVALID_STATE)
    assert read_self_study(study["id"])["status"] == "ACCEPTED"


def test_second_in_flight_self_study_rejected(api):
    """PRD section 3.6: "A school may hold only one in-flight self-study at a
    time — one in `DRAFT`, `SUBMITTED` or `RETURNED_FOR_REVISION` — and a
    second attempt fails with `ERR_IN_FLIGHT_SELF_STUDY_EXISTS` (HTTP 409)."

    Design: Corner/validations/second_in_flight_self_study_rejected
    """
    reset_clock()
    create_active_catalog()
    school = create_school(name="IF School", display_name="IF Schoolhouse")
    first = create_self_study(school["id"], narrative="first")
    assert first["status"] == "DRAFT"

    fresh_version = school_version(school["id"])
    rejected = api.create_self_study(
        create_self_study_payload(school["id"], fresh_version, narrative="second"),
        headers=make_school_admin_headers(school["id"]),
    )
    validate_error(rejected, ApiErrorId.ERR_IN_FLIGHT_SELF_STUDY_EXISTS)
