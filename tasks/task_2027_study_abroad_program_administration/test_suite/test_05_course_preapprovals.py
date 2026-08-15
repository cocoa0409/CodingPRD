"""Course pre-approval creation, review, revision, supersede, and OCC (PRD §2.9, §3.3)."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_approved_preapproval,
    create_pending_preapproval,
    get_application_version,
    make_student_headers,
    review_preapproval,
    setup_open_program_with_application,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
    COORD_A_HEADERS,
    FACULTY_HEADERS,
)


class TestPerCourseRounding:
    def test_rounding_per_course_then_sum_three_credits(self, api):
        """PRD §3.3: "Every new record is born `PENDING` and immediately carries a computed
        `home_credits_est`: the `host_credits` multiplied by the governing agreement's
        `credit_conversion_factor`, with the product rounded to the nearest half credit, ties
        rounding away from zero."
        PRD §2.6: "Each course's converted home-credit value is rounded individually to the
        nearest half credit (a step of 0.5), using round half up with ties away from zero,
        **before** any summation takes place; the resulting per-course values are then summed
        exactly. Summing raw unrounded values and rounding the total produces different
        numbers and is not the contract."

        Design: Difficulty/combinatorial_formula/credit_rounding_per_course_then_sum
        """
        program, student, application = setup_open_program_with_application(
            student_overrides={"full_name": "Round Student", "email": "round@uni.edu"},
        )
        cpa1 = create_pending_preapproval(application, student, "HIST310", 3)
        # host 3 * factor 0.75 = 2.25 -> round half up to nearest 0.5 -> 2.5
        assert cpa1["home_credits_est"] == pytest.approx(2.5, abs=1e-9), (
            f"HIST310 home_credits_est must be 2.5, got {cpa1['home_credits_est']}"
        )

    def test_rounding_per_course_then_sum_five_credits(self, api):
        """PRD §3.3: "the `host_credits` multiplied by the governing agreement's
        `credit_conversion_factor`, with the product rounded to the nearest half credit, ties
        rounding away from zero."

        Design: Difficulty/combinatorial_formula/credit_rounding_per_course_then_sum
        """
        program, student, application = setup_open_program_with_application()
        cpa2 = create_pending_preapproval(application, student, "ART220", 5)
        # host 5 * factor 0.75 = 3.75 -> round half up to nearest 0.5 -> 4.0
        assert cpa2["home_credits_est"] == pytest.approx(4.0, abs=1e-9), (
            f"ART220 home_credits_est must be 4.0, got {cpa2['home_credits_est']}"
        )


class TestRevisionLoop:
    def test_course_preapproval_revision_loop(self, api):
        """PRD §3.3: "A student whose plan comes back `NEEDS_REVISION` revises it — supplying
        a new `host_credits` and optionally a new `course_title` — which loops the record back
        to `PENDING` and recomputes `home_credits_est` under the same per-course rounding."

        Design: Difficulty/non_linear_state_machine/course_preapproval_revision_loop
        """
        program, student, application = setup_open_program_with_application(
            student_overrides={"full_name": "Revise Student", "email": "revise@uni.edu"},
        )
        cpa = create_pending_preapproval(application, student, "HIST310", 4)
        # host 4 * 0.75 = 3.0
        assert cpa["home_credits_est"] == pytest.approx(3.0, abs=1e-9)

        mid = review_preapproval(
            cpa["id"], "NEEDS_REVISION", review_notes="syllabus missing",
        )
        assert mid["status"] == "NEEDS_REVISION"

        revised = validate_success(
            api.revise_course_preapproval(
                cpa["id"], {"host_credits": 5}, make_student_headers(student["id"]),
            )
        )
        assert revised["status"] == "PENDING", (
            f"Revise must loop back to PENDING, got {revised['status']}"
        )
        # host 5 * 0.75 = 3.75 -> 4.0
        assert revised["home_credits_est"] == pytest.approx(4.0, abs=1e-9), (
            f"Revise must recompute home_credits_est from the new host_credits, got {revised['home_credits_est']}"
        )

    def test_course_preapproval_review_stamps_reviewer(self, api):
        """PRD §3.3: "All three decisions stamp `reviewed_by` with the reviewer's `X-User-ID`
        and store the payload's `review_notes` (which may be omitted or null)."

        Design: Difficulty/non_linear_state_machine/course_preapproval_revision_loop
        """
        program, student, application = setup_open_program_with_application()
        cpa = create_pending_preapproval(application, student, "HIST310", 4)
        reviewed = review_preapproval(
            cpa["id"], "NEEDS_REVISION", review_notes="syllabus missing",
        )
        assert reviewed["reviewed_by"] == "fac-1"
        assert reviewed["review_notes"] == "syllabus missing"


class TestSupersede:
    def test_cpa_supersede_side_effect(self, api):
        """PRD §3.3: "At most one record per `(application_id, course_code)` pair may be
        live: if an existing record with the same `course_code` for the same application is
        in `PENDING` or `APPROVED`, the new create supersedes it, moving the older record to
        `SUPERSEDED` whether it was `PENDING` or `APPROVED`."

        Design: Corner/state_machines/cpa_supersede_side_effect
        """
        program, student, application = setup_open_program_with_application(
            student_overrides={"full_name": "Supersede Student", "email": "sup@uni.edu"},
        )
        cpa1 = create_approved_preapproval(application, student, "HIST310", 3)

        version = get_application_version(application["id"])
        cpa2 = validate_success(
            api.create_course_preapproval(
                application["id"],
                {
                    "course_code": "HIST310",
                    "course_title": "Modern French History (retake)",
                    "host_credits": 4,
                    "expected_application_version": version,
                },
                make_student_headers(student["id"]),
            ),
            expected_status=201,
        )
        assert cpa2["status"] == "PENDING"
        assert cpa2["home_credits_est"] == pytest.approx(3.0, abs=1e-9)

        resp = api.list_course_preapprovals(application["id"], COORD_A_HEADERS)
        data, meta = validate_paginated(resp)
        assert len(data) == 2, (
            f"Exactly 2 pre-approval rows exist for the application, got {len(data)}"
        )
        by_id = {row["id"]: row for row in data}
        assert by_id[cpa1["id"]]["status"] == "SUPERSEDED", (
            "The older same-course record must move to SUPERSEDED"
        )
        assert by_id[cpa2["id"]]["status"] == "PENDING"


class TestOptimisticConcurrency:
    def test_occ_stale_version_rejected(self, api):
        """PRD §2.9: "That request must carry `expected_application_version`, a non-optional
        field holding the parent application's `version` as last observed by the client. If
        the application's current `version` does not match — because another writer has
        advanced it in the meantime, for instance by creating a pre-approval that superseded
        a prior record for the same course — the create is rejected with `ERR_STALE_VERSION`
        (HTTP 412), preventing the client from acting on a stale view of the application."

        Design: Corner/cross_cutting_layers/occ_stale_version_rejected_and_fresh_accepted
        """
        program, student, application = setup_open_program_with_application(
            student_overrides={"full_name": "Occ Student", "email": "occ@uni.edu"},
        )
        stale_version = application["version"]

        # CPA1 succeeds and advances the application version.
        cpa1 = validate_success(
            api.create_course_preapproval(
                application["id"],
                {
                    "course_code": "HIST310",
                    "course_title": "Modern French History",
                    "host_credits": 3,
                    "expected_application_version": stale_version,
                },
                make_student_headers(student["id"]),
            ),
            expected_status=201,
        )

        # CPA2 replaying the same stale version is rejected.
        resp_stale = api.create_course_preapproval(
            application["id"],
            {
                "course_code": "ART220",
                "course_title": "Studio Art",
                "host_credits": 5,
                "expected_application_version": stale_version,
            },
            make_student_headers(student["id"]),
        )
        validate_error(resp_stale, ApiErrorId.ERR_STALE_VERSION)

    def test_occ_fresh_version_accepted(self, api):
        """PRD §2.9: "That request must carry `expected_application_version`, a non-optional
        field holding the parent application's `version` as last observed by the client. If
        the application's current `version` does not match ... the create is rejected with
        `ERR_STALE_VERSION` (HTTP 412) ..."

        Design: Corner/cross_cutting_layers/occ_stale_version_rejected_and_fresh_accepted
        """
        program, student, application = setup_open_program_with_application()
        stale_version = application["version"]
        create_pending_preapproval(application, student, "HIST310", 3)

        fresh_version = get_application_version(application["id"])
        assert fresh_version == stale_version + 1, (
            "Creating a pre-approval must advance the parent application's version"
        )
        cpa2 = validate_success(
            api.create_course_preapproval(
                application["id"],
                {
                    "course_code": "ART220",
                    "course_title": "Studio Art",
                    "host_credits": 5,
                    "expected_application_version": fresh_version,
                },
                make_student_headers(student["id"]),
            ),
            expected_status=201,
        )
        assert cpa2["status"] == "PENDING"
