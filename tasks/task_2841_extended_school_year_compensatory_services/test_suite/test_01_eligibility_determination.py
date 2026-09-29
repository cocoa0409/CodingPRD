"""Regression/recoupment analysis, the objection loop, and finalization."""

import pytest

from test_helpers import (
    ApiErrorId,
    factories,
    fixtures,
    make_case_manager_headers,
    make_parent_guardian_headers,
    make_sped_director_headers,
    validate_error,
    validate_success,
)

CM = make_case_manager_headers()
CM_ALT = make_case_manager_headers("cm-002")
DIR = make_sped_director_headers()
DIR_ALT = make_sped_director_headers("dir-002")

SHARED_PROBES = [
    factories.skill_probe("READING_FLUENCY", 80, 60, 20, 4),
    factories.skill_probe("MATH_COMPUTATION", 100, 74, 22, 4),
]


def _draft_determination(api, student_id, variant, probes):
    payload = factories.determination_payload(
        student_id, skill_probes=probes, analysis_variant=variant
    )
    return validate_success(api.create_determination(payload, CM), 201)


class TestVariantDivergence:
    """Identical probe evidence under the two analysis variants."""

    def test_probe_based_variant_qualifies_two_domains_on_observed_recoupment(self, api):
        """PRD §3.2: "Under `PROBE_BASED` — the district collected genuine post-break probe data — each probe's recoupment day count *is* its `recoupment_days_observed`, taken as observed. A probe **qualifies** when its regression percentage is at least twenty-five point zero **and** its recoupment day count is at least twenty days; both comparisons are inclusive."

        PRD §3.2: "Whichever variant ran, `max_recoupment_days` records the largest recoupment day count the variant considered — the largest observed figure under `PROBE_BASED`, the largest projected figure under `TEAM_JUDGMENT` — as a whole number of days, and `criteria_met_count` records how many probe domains satisfied **both** tests under that variant."

        PRD §3.2: "Otherwise, if `criteria_met_count` is at least two, the recommendation is `ELIGIBLE`."

        Design: Difficulty/dual_variant_calc/eligibility_variant_divergence_probe_based_vs_team_judgment
        """
        fixtures.set_clock(api)
        student = fixtures.register_student(api)
        determination = _draft_determination(
            api, student["id"], "PROBE_BASED", SHARED_PROBES
        )

        analysed = validate_success(
            api.analyze_determination(determination["id"], {}, CM)
        )

        assert float(analysed["max_regression_pct"]) == 26.0
        assert analysed["max_recoupment_days"] == 22
        assert analysed["criteria_met_count"] == 2
        assert analysed["data_sufficiency"] == "SUFFICIENT"
        assert analysed["eligibility_recommendation"] == "ELIGIBLE"
        assert analysed["status"] == "PARENT_REVIEW"

    def test_team_judgment_variant_qualifies_one_domain_on_projected_recoupment(self, api):
        """PRD §3.2: "Under `TEAM_JUDGMENT` — no post-break data exists and the IEP team projects recoupment from the magnitude of the regression — each probe's observed `recoupment_days_observed` is discarded entirely, and its recoupment day count is instead **projected** as the probe's regression percentage divided by one point two percentage points per day, rounded **up** to the next whole day. A probe qualifies when its regression percentage is strictly greater than twenty-five point zero **and** its projected recoupment day count is strictly greater than twenty days; both comparisons are exclusive."

        PRD §3.2: "Failing all three, the recommendation is `INELIGIBLE`."

        Design: Difficulty/dual_variant_calc/eligibility_variant_divergence_probe_based_vs_team_judgment
        """
        fixtures.set_clock(api)
        student = fixtures.register_student(api)
        determination = _draft_determination(
            api, student["id"], "TEAM_JUDGMENT", SHARED_PROBES
        )

        analysed = validate_success(
            api.analyze_determination(determination["id"], {}, CM)
        )

        assert float(analysed["max_regression_pct"]) == 26.0
        assert analysed["max_recoupment_days"] == 22
        assert analysed["criteria_met_count"] == 1
        assert analysed["data_sufficiency"] == "SUFFICIENT"
        assert analysed["eligibility_recommendation"] == "INELIGIBLE"
        assert analysed["status"] == "PARENT_REVIEW"


class TestRecoupmentBoundary:
    """The observed-recoupment threshold read across successive objection rounds."""

    def _boundary_probes(self, second_recoupment_days):
        return [
            factories.skill_probe("READING_FLUENCY", 80, 60, 20, 4),
            factories.skill_probe("MATH_COMPUTATION", 80, 60, second_recoupment_days, 4),
        ]

    def test_recoupment_one_day_below_the_threshold_qualifies_only_one_domain(self, api):
        """PRD §3.2: "Under `PROBE_BASED` — the district collected genuine post-break probe data — each probe's recoupment day count *is* its `recoupment_days_observed`, taken as observed. A probe **qualifies** when its regression percentage is at least twenty-five point zero **and** its recoupment day count is at least twenty days; both comparisons are inclusive."

        PRD §3.2: "Failing all three, the recommendation is `INELIGIBLE`."

        Design: Difficulty/boundary_precision_check/recoupment_days_threshold_boundary_across_objection_rounds
        """
        fixtures.set_clock(api)
        student = fixtures.register_student(api)
        determination = _draft_determination(
            api, student["id"], "PROBE_BASED", self._boundary_probes(19)
        )

        analysed = validate_success(
            api.analyze_determination(determination["id"], {}, CM)
        )

        assert analysed["status"] == "PARENT_REVIEW"
        assert float(analysed["max_regression_pct"]) == 25.0
        assert analysed["max_recoupment_days"] == 20
        assert analysed["criteria_met_count"] == 1
        assert analysed["data_sufficiency"] == "SUFFICIENT"
        assert analysed["eligibility_recommendation"] == "INELIGIBLE"

        student_row = fixtures.refresh_student(api, student["id"])
        assert student_row["esy_eligibility_status"] == "NOT_DETERMINED"

    @pytest.mark.parametrize(
        "recoupment_days,expected_max_recoupment",
        [(20, 20), (21, 21)],
    )
    def test_recoupment_at_and_above_the_threshold_qualifies_both_domains(
        self, api, recoupment_days, expected_max_recoupment
    ):
        """PRD §3.2: "Under `PROBE_BASED` — the district collected genuine post-break probe data — each probe's recoupment day count *is* its `recoupment_days_observed`, taken as observed. A probe **qualifies** when its regression percentage is at least twenty-five point zero **and** its recoupment day count is at least twenty days; both comparisons are inclusive."

        PRD §3.2: "`OBJECT` sends the determination back with `PARENT_REVIEW → DRAFT`, increases `objection_round_count` by one, and **clears `analyzed_by_user_id` to null**, so that the next analysis run re-establishes authorship from scratch; the team may then re-analyse, optionally after amending `skill_probes`, and push the determination to `PARENT_REVIEW` again."

        PRD §3.2: "Otherwise, if `criteria_met_count` is at least two, the recommendation is `ELIGIBLE`."

        Design: Difficulty/boundary_precision_check/recoupment_days_threshold_boundary_across_objection_rounds
        """
        fixtures.set_clock(api)
        student = fixtures.register_student(api)
        parent = make_parent_guardian_headers(student["id"])
        determination = _draft_determination(
            api, student["id"], "PROBE_BASED", self._boundary_probes(19)
        )

        validate_success(api.analyze_determination(determination["id"], {}, CM))
        objected = validate_success(
            api.determination_parent_response(
                determination["id"],
                {"response": "OBJECT", "parent_comment": "Recoupment was misrecorded"},
                parent,
            )
        )
        assert objected["status"] == "DRAFT"
        assert objected["objection_round_count"] == 1
        assert objected["analyzed_by_user_id"] is None

        reanalysed = validate_success(
            api.analyze_determination(
                determination["id"],
                {"skill_probes": self._boundary_probes(recoupment_days)},
                CM,
            )
        )

        assert float(reanalysed["max_regression_pct"]) == 25.0
        assert reanalysed["max_recoupment_days"] == expected_max_recoupment
        assert reanalysed["criteria_met_count"] == 2
        assert reanalysed["eligibility_recommendation"] == "ELIGIBLE"
        assert reanalysed["status"] == "PARENT_REVIEW"

        student_row = fixtures.refresh_student(api, student["id"])
        assert student_row["esy_eligibility_status"] == "NOT_DETERMINED"


class TestObjectionCycle:
    """PARENT_REVIEW back to DRAFT and forward again through the same endpoint."""

    OBJECTION_PROBES = [
        factories.skill_probe("READING_FLUENCY", 80, 60, 20, 4),
        factories.skill_probe("EXPRESSIVE_LANGUAGE", 80, 60, 19, 4),
    ]
    AMENDED_PROBES = [
        factories.skill_probe("READING_FLUENCY", 80, 60, 20, 4),
        factories.skill_probe("EXPRESSIVE_LANGUAGE", 80, 60, 20, 4),
    ]

    def test_objection_returns_the_determination_to_draft_and_clears_the_analyst(self, api):
        """PRD §3.2: "`OBJECT` sends the determination back with `PARENT_REVIEW → DRAFT`, increases `objection_round_count` by one, and **clears `analyzed_by_user_id` to null**, so that the next analysis run re-establishes authorship from scratch; the team may then re-analyse, optionally after amending `skill_probes`, and push the determination to `PARENT_REVIEW` again."

        PRD §3.2: "Analysis also writes `analyzed_by_user_id` with the calling `CaseManager`'s `X-User-ID`, and increments the determination's `version`."

        Design: Difficulty/non_linear_state_machine/determination_objection_cycle_returns_to_draft_and_reanalyzes
        """
        fixtures.set_clock(api)
        student = fixtures.register_student(api)
        parent = make_parent_guardian_headers(student["id"])
        determination = _draft_determination(
            api, student["id"], "PROBE_BASED", self.OBJECTION_PROBES
        )

        first = validate_success(api.analyze_determination(determination["id"], {}, CM))
        assert first["criteria_met_count"] == 1
        assert first["eligibility_recommendation"] == "INELIGIBLE"
        assert first["max_recoupment_days"] == 20
        assert first["analyzed_by_user_id"] == "cm-001"

        objected = validate_success(
            api.determination_parent_response(
                determination["id"],
                {
                    "response": "OBJECT",
                    "parent_comment": "Summer probe for expressive language was cut short.",
                },
                parent,
            )
        )
        assert objected["status"] == "DRAFT"
        assert objected["objection_round_count"] == 1
        assert objected["analyzed_by_user_id"] is None

        second = validate_success(
            api.analyze_determination(
                determination["id"], {"skill_probes": self.AMENDED_PROBES}, CM_ALT
            )
        )
        assert second["status"] == "PARENT_REVIEW"
        assert second["criteria_met_count"] == 2
        assert second["eligibility_recommendation"] == "ELIGIBLE"
        assert second["analyzed_by_user_id"] == "cm-002"
        assert float(second["max_regression_pct"]) == 25.0
        assert second["max_recoupment_days"] == 20

    def test_reentered_cycle_completes_through_agreement_and_finalization(self, api):
        """PRD §3.2: "`AGREE` advances `PARENT_REVIEW → PARENT_AGREED`."

        PRD §3.2: "On success the director's identifier is stored as `finalized_by_user_id`, and the cross-entity write that the rest of the system waits for happens: the determination's `eligibility_recommendation` is copied onto the student's `esy_eligibility_status`, the student's `version` increases by one and its `updated_at` is refreshed, and the determination's own `version` increases by one as well."

        Design: Difficulty/non_linear_state_machine/determination_objection_cycle_returns_to_draft_and_reanalyzes
        """
        fixtures.set_clock(api)
        student = fixtures.register_student(api)
        parent = make_parent_guardian_headers(student["id"])
        determination = _draft_determination(
            api, student["id"], "PROBE_BASED", self.OBJECTION_PROBES
        )

        validate_success(api.analyze_determination(determination["id"], {}, CM))
        validate_success(
            api.determination_parent_response(
                determination["id"], {"response": "OBJECT"}, parent
            )
        )
        validate_success(
            api.analyze_determination(
                determination["id"], {"skill_probes": self.AMENDED_PROBES}, CM_ALT
            )
        )

        agreed = validate_success(
            api.determination_parent_response(
                determination["id"], {"response": "AGREE"}, parent
            )
        )
        assert agreed["status"] == "PARENT_AGREED"
        assert agreed["objection_round_count"] == 1

        finalized = validate_success(
            api.finalize_determination(determination["id"], {}, DIR)
        )
        assert finalized["status"] == "FINALIZED"
        assert finalized["finalized_by_user_id"] == "dir-001"

        student_row = fixtures.refresh_student(api, student["id"])
        assert student_row["esy_eligibility_status"] == "ELIGIBLE"
        assert student_row["version"] == student["version"] + 1


def test_regression_percentage_rounds_half_up_to_one_decimal_place(api):
    """PRD §3.2: "For each probe in array order, the regression percentage is the probe's `pre_break_mastery_pct` less its `post_break_mastery_pct`, multiplied by one hundred, divided by its `pre_break_mastery_pct`, and rounded half up to one decimal place; a probe whose `post_break_mastery_pct` is greater than or equal to its `pre_break_mastery_pct` yields zero point zero."

    PRD §3.2: "`max_regression_pct` is the largest of those per-probe percentages, likewise carried to one decimal place."

    Design: Corner/calculations/regression_pct_rounds_half_up_to_one_decimal
    """
    fixtures.set_clock(api)
    student = fixtures.register_student(api)
    probes = [
        factories.skill_probe("READING_FLUENCY", 80, 55, 21, 4),
        factories.skill_probe("MATH_COMPUTATION", 90, 64, 21, 4),
    ]
    determination = _draft_determination(api, student["id"], "PROBE_BASED", probes)

    analysed = validate_success(api.analyze_determination(determination["id"], {}, CM))

    assert float(analysed["max_regression_pct"]) == 31.3
    assert analysed["max_recoupment_days"] == 21
    assert analysed["criteria_met_count"] == 2
    assert analysed["data_sufficiency"] == "SUFFICIENT"
    assert analysed["eligibility_recommendation"] == "ELIGIBLE"
    assert analysed["status"] == "PARENT_REVIEW"

    student_row = fixtures.refresh_student(api, student["id"])
    assert student_row["esy_eligibility_status"] == "NOT_DETERMINED"


def test_analyze_requires_at_least_two_probe_domains(api):
    """PRD §3.2: "Two preconditions guard the run: the determination must currently be in `DRAFT`, and it must carry at least two probe entries — fewer than two probe domains is rejected with `ERR_INSUFFICIENT_PROBE_DATA`."

    PRD §3.2: "The request may optionally supply a replacement `skill_probes` array, which is precisely how the team responds after a parent objection."

    Design: Corner/errors/analyze_with_a_single_probe_domain_rejected
    """
    fixtures.set_clock(api)
    student = fixtures.register_student(api)
    determination = _draft_determination(
        api,
        student["id"],
        "PROBE_BASED",
        [factories.skill_probe("READING_FLUENCY", 80, 60, 20, 4)],
    )

    rejected = api.analyze_determination(determination["id"], {}, CM)
    validate_error(rejected, ApiErrorId.INSUFFICIENT_PROBE_DATA.value, 422)
    assert fixtures.refresh_determination(api, determination["id"])["status"] == "DRAFT"

    accepted = validate_success(
        api.analyze_determination(
            determination["id"], {"skill_probes": SHARED_PROBES}, CM
        )
    )
    assert float(accepted["max_regression_pct"]) == 26.0
    assert accepted["max_recoupment_days"] == 22
    assert accepted["criteria_met_count"] == 2
    assert accepted["data_sufficiency"] == "SUFFICIENT"
    assert accepted["eligibility_recommendation"] == "ELIGIBLE"
    assert accepted["status"] == "PARENT_REVIEW"
    assert accepted["analyzed_by_user_id"] == "cm-001"


def test_second_finalize_on_a_finalized_determination_is_a_state_error(api):
    """PRD §2.7: "The target resource is in a state from which the requested transition exists, including the cross-entity state guards — otherwise `ERR_INVALID_STATE`."

    PRD §3.2: "Finalization is a `SpedDirector` act and completes `PARENT_AGREED → FINALIZED`, which is terminal. It requires the determination to be in `PARENT_AGREED`, and it requires the acting `X-User-ID` to differ from `analyzed_by_user_id`; a director trying to rubber-stamp their own analysis is refused with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/state_machines/second_finalize_on_a_finalized_determination_rejected
    """
    fixtures.set_clock(api)
    student = fixtures.register_student(api)
    parent = make_parent_guardian_headers(student["id"])
    determination = _draft_determination(
        api, student["id"], "PROBE_BASED", SHARED_PROBES
    )
    validate_success(api.analyze_determination(determination["id"], {}, CM))
    validate_success(
        api.determination_parent_response(
            determination["id"], {"response": "AGREE"}, parent
        )
    )
    finalized = validate_success(
        api.finalize_determination(determination["id"], {}, DIR)
    )

    rejected = api.finalize_determination(determination["id"], {}, DIR_ALT)
    validate_error(rejected, ApiErrorId.INVALID_STATE.value, 409)

    after = fixtures.refresh_determination(api, determination["id"])
    assert after["status"] == "FINALIZED"
    assert after["finalized_by_user_id"] == "dir-001"
    assert after["version"] == finalized["version"]
    assert (
        fixtures.refresh_student(api, student["id"])["esy_eligibility_status"]
        == "ELIGIBLE"
    )


def test_guardian_of_another_student_cannot_read_or_answer_a_determination(api):
    """PRD §2.1: "The guardian ownership check guards exactly six operations: reading one student, listing that student's eligibility determinations, reading one eligibility determination, submitting a parent response to a determination, reading one compensatory award, and submitting a parent response to an award. In all six, a `ParentGuardian` whose `X-User-ID` does not equal the addressed record's `student_id` (or, for the student read, the addressed `Student`'s own `id`) is rejected with `ERR_NOT_STUDENT_GUARDIAN` (HTTP 403)."

    PRD §3.2: "The parent now responds, and only a `ParentGuardian` whose `X-User-ID` matches the determination's `student_id` may do so — anyone else draws `ERR_NOT_STUDENT_GUARDIAN`."

    Design: Corner/rbac/parent_guardian_cannot_respond_for_another_students_determination
    """
    fixtures.set_clock(api)
    student_one = fixtures.register_student(api)
    student_two = fixtures.register_student(
        api,
        student_number="S-2841-002",
        first_name="Ben",
        last_name="Okafor",
        primary_disability="SPECIFIC_LEARNING_DISABILITY",
        transportation_required=False,
    )
    determination = _draft_determination(
        api, student_one["id"], "PROBE_BASED", SHARED_PROBES
    )
    validate_success(api.analyze_determination(determination["id"], {}, CM))

    stranger = make_parent_guardian_headers(student_two["id"])
    validate_error(
        api.determination_parent_response(
            determination["id"], {"response": "AGREE"}, stranger
        ),
        ApiErrorId.NOT_STUDENT_GUARDIAN.value,
        403,
    )
    validate_error(
        api.get_determination(determination["id"], stranger),
        ApiErrorId.NOT_STUDENT_GUARDIAN.value,
        403,
    )
    assert (
        fixtures.refresh_determination(api, determination["id"])["status"]
        == "PARENT_REVIEW"
    )

    owner = make_parent_guardian_headers(student_one["id"])
    agreed = validate_success(
        api.determination_parent_response(
            determination["id"], {"response": "AGREE"}, owner
        )
    )
    assert agreed["status"] == "PARENT_AGREED"
    assert (
        fixtures.refresh_student(api, student_one["id"])["esy_eligibility_status"]
        == "NOT_DETERMINED"
    )


def test_director_cannot_finalize_the_analysis_they_authored(api):
    """PRD §2.1: "The `SpedDirector` who finalizes an eligibility determination must not be the user recorded in `analyzed_by_user_id`, and the `SpedDirector` who resolves a compensatory dispute must not be the user recorded in `authored_by_user_id`. Either collision is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    PRD §2.7: "The approving user differs from the user who produced the artifact — otherwise `ERR_SEGREGATION_OF_DUTIES`. Applies to determination finalization and to award dispute resolution."

    Design: Corner/rbac/finalizing_ones_own_analysis_rejected_as_segregation_of_duties
    """
    fixtures.set_clock(api)
    student = fixtures.register_student(api)
    parent = make_parent_guardian_headers(student["id"])
    determination = _draft_determination(
        api, student["id"], "PROBE_BASED", SHARED_PROBES
    )
    analyst = make_case_manager_headers("dir-001")
    validate_success(api.analyze_determination(determination["id"], {}, analyst))
    validate_success(
        api.determination_parent_response(
            determination["id"], {"response": "AGREE"}, parent
        )
    )

    validate_error(
        api.finalize_determination(determination["id"], {}, DIR),
        ApiErrorId.SEGREGATION_OF_DUTIES.value,
        403,
    )
    blocked = fixtures.refresh_determination(api, determination["id"])
    assert blocked["status"] == "PARENT_AGREED"
    assert blocked["finalized_by_user_id"] is None
    assert (
        fixtures.refresh_student(api, student["id"])["esy_eligibility_status"]
        == "NOT_DETERMINED"
    )

    finalized = validate_success(
        api.finalize_determination(determination["id"], {}, DIR_ALT)
    )
    assert finalized["status"] == "FINALIZED"
    assert finalized["analyzed_by_user_id"] == "dir-001"
    assert finalized["finalized_by_user_id"] == "dir-002"
    assert (
        fixtures.refresh_student(api, student["id"])["esy_eligibility_status"]
        == "ELIGIBLE"
    )
