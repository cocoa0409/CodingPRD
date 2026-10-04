"""Education evaluation: credit floor, single-open rule, deficiency loop
(PRD §3.2)."""
from test_helpers import (
    ALTERNATIVE_PATH_MIN_CREDITS, ApiErrorId, assert_candidate,
    assert_education_evaluation, create_candidate_payload,
    create_education_evaluation_payload, create_jurisdiction_payload,
    make_candidate_headers, validate_error, validate_paginated,
    validate_success,
)


def _candidate_with_jurisdiction(api, anonymous_headers, ncarb_admin_headers,
                                 email_marker="c1"):
    validate_success(api.create_jurisdiction(
        create_jurisdiction_payload(code="J1"), ncarb_admin_headers,
    ), expected_status=201)
    return validate_success(api.create_candidate(
        create_candidate_payload(
            email=f"{email_marker}@example.com", home_jurisdiction_code="J1",
        ),
        anonymous_headers,
    ), expected_status=201)


class TestAlternativePathCreditFloor:
    def test_evaluation_alternative_path_credit_boundary(self, api, anonymous_headers, ncarb_admin_headers):
        """PRD §3.2: "an `ALTERNATIVE_PATH` evaluation must declare at least
        64 semester credit hours, and a lower figure is rejected with
        `ERR_ALTERNATIVE_CREDITS_INSUFFICIENT` (HTTP 422)."
        PRD §3.2: "A new evaluation lands in `SUBMITTED` status with
        `review_count` at 0 and `deficiency_notes` null."

        Design: Corner/entities/evaluation_alternative_path_credit_boundary
        """
        validate_success(api.create_jurisdiction(
            create_jurisdiction_payload(code="J1"), ncarb_admin_headers,
        ), expected_status=201)
        cand_64 = validate_success(api.create_candidate(
            create_candidate_payload(
                email="c64@example.com", home_jurisdiction_code="J1",
            ), anonymous_headers,
        ), expected_status=201)
        cand_63 = validate_success(api.create_candidate(
            create_candidate_payload(
                email="c63@example.com", home_jurisdiction_code="J1",
            ), anonymous_headers,
        ), expected_status=201)

        # One below the floor: rejected.
        validate_error(
            api.create_education_evaluation(
                cand_63["id"],
                create_education_evaluation_payload(
                    path_type="ALTERNATIVE_PATH",
                    institution_name="Night College",
                    semester_credit_hours=ALTERNATIVE_PATH_MIN_CREDITS - 1,
                ),
                make_candidate_headers(cand_63["id"]),
            ),
            ApiErrorId.ERR_ALTERNATIVE_CREDITS_INSUFFICIENT,
        )
        # Exactly the floor: boundary inclusive, accepted.
        data = validate_success(api.create_education_evaluation(
            cand_64["id"],
            create_education_evaluation_payload(
                path_type="ALTERNATIVE_PATH",
                institution_name="Night College",
                semester_credit_hours=ALTERNATIVE_PATH_MIN_CREDITS,
            ),
            make_candidate_headers(cand_64["id"]),
        ), expected_status=201)
        assert_education_evaluation(data)
        assert data["status"] == "SUBMITTED"
        assert data["review_count"] == 0
        assert data["deficiency_notes"] is None

    def test_evaluation_second_open_evaluation_rejected(self, api, anonymous_headers, ncarb_admin_headers):
        """PRD §3.2: "Only one evaluation per candidate may be open at a time:
        submitting a second while an earlier one is still `SUBMITTED` fails
        with `ERR_EVALUATION_ALREADY_OPEN`."

        Design: Corner/entities/evaluation_second_open_evaluation_rejected
        """
        cand = _candidate_with_jurisdiction(api, anonymous_headers, ncarb_admin_headers)
        ch = make_candidate_headers(cand["id"])
        validate_success(api.create_education_evaluation(
            cand["id"], create_education_evaluation_payload(), ch,
        ), expected_status=201)
        validate_error(
            api.create_education_evaluation(
                cand["id"],
                create_education_evaluation_payload(
                    path_type="ALTERNATIVE_PATH",
                    institution_name="Night College",
                    semester_credit_hours=ALTERNATIVE_PATH_MIN_CREDITS,
                ),
                ch,
            ),
            ApiErrorId.ERR_EVALUATION_ALREADY_OPEN,
        )
        rows, meta = validate_paginated(
            api.list_education_evaluations(cand["id"], ch)
        )
        assert len(rows) == 1, f"expected exactly 1 evaluation, got {len(rows)}"


class TestDeficiencyCycle:
    def _deficient_evaluation(self, api, anonymous_headers, ncarb_admin_headers):
        cand = _candidate_with_jurisdiction(api, anonymous_headers, ncarb_admin_headers)
        ch = make_candidate_headers(cand["id"])
        evaluation = validate_success(api.create_education_evaluation(
            cand["id"],
            create_education_evaluation_payload(
                path_type="ALTERNATIVE_PATH",
                institution_name="Night College",
                semester_credit_hours=ALTERNATIVE_PATH_MIN_CREDITS,
            ),
            ch,
        ), expected_status=201)
        deficient = validate_success(api.review_education_evaluation(
            evaluation["id"],
            {"decision": "DEFICIENT",
             "deficiency_notes": "missing structures coursework"},
            ncarb_admin_headers,
        ))
        assert deficient["status"] == "DEFICIENT"
        assert deficient["review_count"] == 1
        assert deficient["deficiency_notes"] == "missing structures coursework"
        return cand, ch, evaluation

    def test_deficiency_loop_resubmit_clears_notes_and_replaces_fields(self, api, anonymous_headers, ncarb_admin_headers):
        """PRD §3.2: "The owning candidate — and only that candidate — may
        resubmit the evaluation, which returns it to `SUBMITTED`, clears
        `deficiency_notes` back to null, and replaces any of `path_type`,
        `institution_name`, or `semester_credit_hours` for which the
        resubmission supplies new values."

        Design: Difficulty/non_linear_state_machine/education_evaluation_deficiency_cycle
        """
        cand, ch, evaluation = self._deficient_evaluation(
            api, anonymous_headers, ncarb_admin_headers,
        )
        data = validate_success(api.resubmit_education_evaluation(
            evaluation["id"], {"semester_credit_hours": 72}, ch,
        ))
        assert data["status"] == "SUBMITTED", "DEFICIENT -> SUBMITTED loop"
        assert data["deficiency_notes"] is None, "notes cleared at resubmit"
        assert data["semester_credit_hours"] == 72, "resubmission replaced the field"
        assert data["review_count"] == 1, "review count unchanged by resubmit"

    def test_deficiency_loop_completes_to_satisfied(self, api, anonymous_headers, ncarb_admin_headers):
        """PRD §3.2: "A `SATISFIED` decision moves the evaluation to
        `SATISFIED` — its terminal state — increments `review_count` by one,
        flips the owning candidate's `education_status` from `NONE` to
        `SATISFIED`, and triggers a recompute of `certificate_eligible`."

        Design: Difficulty/non_linear_state_machine/education_evaluation_deficiency_cycle
        """
        cand, ch, evaluation = self._deficient_evaluation(
            api, anonymous_headers, ncarb_admin_headers,
        )
        validate_success(api.resubmit_education_evaluation(
            evaluation["id"], {"semester_credit_hours": 72}, ch,
        ))
        data = validate_success(api.review_education_evaluation(
            evaluation["id"], {"decision": "SATISFIED"}, ncarb_admin_headers,
        ))
        assert data["status"] == "SATISFIED", (
            "SUBMITTED -> DEFICIENT -> SUBMITTED -> SATISFIED full loop"
        )
        assert data["review_count"] == 2
        assert data["deficiency_notes"] is None
        assert data["semester_credit_hours"] == 72
        candidate = validate_success(
            api.get_candidate(cand["id"], ncarb_admin_headers)
        )
        assert_candidate(candidate)
        assert candidate["education_status"] == "SATISFIED"
