"""Contesting a published score: targeting, the frozen window, and rescoring.

The appeal window is frozen at first scoring and never re-derived, the contested
row must belong to the appealed inspection, and a granted technical-error appeal
rewrites both score variants and the property posture behind it.
"""

from test_helpers import (
    ApiErrorId,
    assert_error,
    assert_fields,
    assert_instant,
    assert_integer,
    assert_null,
    assert_ok,
    assert_one_decimal,
    assert_scores,
    assert_total_count,
    assert_two_decimals,
    constants as K,
    factories as F,
    fixtures as X,
)

CEDAR_UNIT = [
    {"unit_number": "101", "bedroom_count": 1, "occupancy_status": "OCCUPIED"}
]
HEAVY_DEFINITIONS = ("LT_GAS", "MOD_HEAVY")
LATE_FILED_AT = "2026-09-27T09:00:00.000Z"
SECOND_RETURN_AT = "2026-09-15T09:00:00.000Z"
THIRD_RETURN_AT = "2026-09-17T09:00:00.000Z"
FIRST_RESUBMIT_EVIDENCE = "Photograph set A with the marshal's order"
SECOND_RESUBMIT_EVIDENCE = "Photograph set B with timestamps"
THIRD_RESUBMIT_EVIDENCE = "Photograph set C"
OVER_GENEROUS_ADJUSTMENT = 20.0


def _two_severe_scored(api):
    """Two severe rows worth 16.00 each publish a final score of 84.0."""
    return X.scored_lifecycle(api, unit_specs=CEDAR_UNIT, deficiency_count=2)


def _one_severe_scored(api):
    """One severe row worth 16.00 publishes a final score of 92.0."""
    return X.scored_lifecycle(api, unit_specs=CEDAR_UNIT, deficiency_count=1)


def _submitted_technical_appeal(api):
    """A SUBMITTED technical-error appeal against an 84.0 inspection."""
    bundle = _two_severe_scored(api)
    bundle["appeal"] = X.filed_appeal(
        api,
        bundle["inspection_id"],
        bundle["property_id"],
        bundle["deficiency_ids"][0],
    )
    bundle["appeal_id"] = bundle["appeal"]["id"]
    return bundle


def _submitted_score_correction_appeal(api):
    """A SCORE_CORRECTION appeal asking 10.00 points back off a 16.00 row."""
    bundle = _one_severe_scored(api)
    bundle["appeal"] = X.filed_appeal(
        api,
        bundle["inspection_id"],
        bundle["property_id"],
        bundle["deficiency_ids"][0],
        "SCORE_CORRECTION",
    )
    bundle["appeal_id"] = bundle["appeal"]["id"]
    return bundle


def _three_heavy_rows_scored_fifty(api):
    """Three 40.00 rows zero the dwelling area, leaving a WATCH property."""
    bundle = X.scored_lifecycle(
        api,
        unit_specs=CEDAR_UNIT,
        definition_codes=HEAVY_DEFINITIONS,
        deficiency_code="MOD_HEAVY",
        deficiency_count=3,
    )
    bundle["appeal"] = X.filed_appeal(
        api,
        bundle["inspection_id"],
        bundle["property_id"],
        bundle["deficiency_ids"][2],
    )
    bundle["appeal_id"] = bundle["appeal"]["id"]
    return bundle


def _appeal_returned_three_times(api):
    """The bounded cycle run to exhaustion: two resubmits, three returns."""
    bundle = _one_severe_scored(api)
    appeal = X.returned_appeal(
        api,
        bundle["inspection_id"],
        bundle["property_id"],
        bundle["deficiency_ids"][0],
    )
    appeal_id = appeal["id"]
    history = [appeal]
    for evidence, returned_at in (
        (FIRST_RESUBMIT_EVIDENCE, SECOND_RETURN_AT),
        (SECOND_RESUBMIT_EVIDENCE, THIRD_RETURN_AT),
    ):
        history.append(
            assert_ok(
                api.resubmit_appeal(
                    appeal_id,
                    F.appeal_resubmit_payload(additional_evidence=evidence),
                    bundle["owner_headers"],
                )
            )
        )
        history.append(
            assert_ok(
                api.review_appeal(
                    appeal_id,
                    F.appeal_review_payload(
                        "RETURNED_FOR_INFO", decided_at=returned_at
                    ),
                    X.APPEALS,
                )
            )
        )
    bundle["appeal_id"] = appeal_id
    bundle["history"] = history
    return bundle


class TestResubmittingAPendingAppeal:
    """Resubmission is declared from `RETURNED_FOR_INFO` only."""

    def test_a_still_submitted_appeal_cannot_be_resubmitted(self, api):
        """The two-resubmission budget cannot be burned before a return.

        PRD: "The request carries `additional_evidence`, the appeal's `status`
        must be `RETURNED_FOR_INFO`, and `resubmission_count` must be strictly
        less than 2"

        PRD: "the target row's `status`, `repair_status`, `verification_status`
        or `adoption_status` admits the requested transition, else the state
        error for that resource type: `ERR_STANDARD_ALREADY_ADOPTED`,
        `ERR_INSPECTION_INVALID_STATE`, `ERR_SELECTION_INVALID_STATE`"

        Design: Corner/errors/resubmitting_a_still_pending_appeal_is_rejected_as_invalid_state
        """
        bundle = _submitted_technical_appeal(api)
        assert_fields(bundle["appeal"], status="SUBMITTED", resubmission_count=0)

        response = api.resubmit_appeal(
            bundle["appeal_id"],
            F.appeal_resubmit_payload(),
            bundle["owner_headers"],
        )

        assert_error(response, ApiErrorId.APPEAL_INVALID_STATE)
        unchanged = X.read_appeal(api, bundle["appeal_id"])
        assert_fields(unchanged, status="SUBMITTED", resubmission_count=0)
        assert_null(unchanged, "additional_evidence", "decided_at")
        assert_integer(
            unchanged["version"], bundle["appeal"]["version"], "version"
        )
        owning_inspection = X.read_inspection(api, bundle["inspection_id"])
        assert_fields(owning_inspection, status="APPEALED")
        assert_one_decimal(owning_inspection["final_score"], 84.0, "final_score")


class TestTheFrozenAppealWindow:
    """`appeal_deadline_at` is set once and bounds every later filing."""

    def test_a_filing_after_the_deadline_is_rejected(self, api):
        """One day past the fifteen-day window closes the door.

        PRD: "Separately, the `filed_at` instant must be no later than the
        inspection's frozen `appeal_deadline_at`; an instant strictly after it is
        rejected with `ERR_APPEAL_WINDOW_CLOSED` (HTTP 422)."

        PRD: "That deadline is **frozen at first scoring and is never
        re-derived**, no matter how many times the inspection is later rescored."

        Design: Corner/errors/appeal_filed_after_the_frozen_deadline_is_rejected_as_window_closed
        """
        bundle = _two_severe_scored(api)
        scored = bundle["inspection"]
        assert_instant(
            scored["appeal_deadline_at"], K.APPEAL_DEADLINE_AT, "appeal_deadline_at"
        )

        response = api.create_appeal(
            F.appeal_payload(
                bundle["inspection_id"],
                bundle["deficiency_ids"][0],
                filed_at=LATE_FILED_AT,
            ),
            bundle["owner_headers"],
        )

        assert_error(response, ApiErrorId.APPEAL_WINDOW_CLOSED)
        unchanged = X.read_inspection(api, bundle["inspection_id"])
        assert_fields(unchanged, status="SCORED")
        assert_integer(unchanged["version"], scored["version"], "version")
        assert_total_count(
            api.list_appeals(X.ADMIN, inspection_id=bundle["inspection_id"]), 0
        )


class TestAppealTargeting:
    """The contested row must reach the inspection being appealed."""

    def test_a_sweep_sourced_deficiency_cannot_be_contested(self, api):
        """An owner's own finding on the same unit has no `inspection_id`.

        PRD: "must name a `Deficiency` whose `inspection_id` equals the
        inspection being appealed, and that deficiency's `status` must be
        anything other than `VOIDED`"

        PRD: "Any violation of that composite condition - a missing contested
        deficiency, one drawn from a different inspection, one already voided, or
        a misplaced requested adjustment - is rejected with
        `ERR_DEFICIENCY_NOT_IN_INSPECTION` (HTTP 422)."

        Design: Corner/errors/appeal_citing_a_sweep_sourced_deficiency_is_rejected_as_not_in_inspection
        """
        bundle = _two_severe_scored(api)
        sweep = X.sweep_with_finding(
            api,
            bundle["property_id"],
            bundle["definition_ids"]["SEV_WINDOW"],
            bundle["unit_ids"]["101"],
        )
        sweep_row = X.read_deficiency(api, sweep["deficiency_id"])
        assert_fields(sweep_row, source="SELF_ASSESSMENT")
        assert_null(sweep_row, "inspection_id")

        response = api.create_appeal(
            F.appeal_payload(bundle["inspection_id"], sweep["deficiency_id"]),
            bundle["owner_headers"],
        )

        assert_error(response, ApiErrorId.DEFICIENCY_NOT_IN_INSPECTION)
        unchanged = X.read_inspection(api, bundle["inspection_id"])
        assert_fields(unchanged, status="SCORED")
        assert_integer(
            unchanged["version"], bundle["inspection"]["version"], "version"
        )
        assert_total_count(
            api.list_appeals(X.ADMIN, inspection_id=bundle["inspection_id"]), 0
        )


class TestGrantingAScoreCorrection:
    """The reviewer's figure is mandatory and bounded by the contested row."""

    def test_a_grant_without_a_granted_adjustment_is_rejected(self, api):
        """The owner's request is not the reviewer's number.

        PRD: "Granting a `SCORE_CORRECTION` appeal requires
        `granted_point_adjustment` to be present, else `ERR_ADJUSTMENT_REQUIRED`
        (HTTP 422)"

        PRD: "The reviewer's figure is what is applied; the owner's
        `requested_point_adjustment` is a request, not a binding amount."

        Design: Corner/errors/granting_a_score_correction_appeal_without_an_adjustment_is_rejected
        """
        bundle = _submitted_score_correction_appeal(api)

        response = api.review_appeal(
            bundle["appeal_id"],
            F.appeal_review_payload("GRANTED"),
            X.APPEALS,
        )

        assert_error(response, ApiErrorId.ADJUSTMENT_REQUIRED)
        unchanged = X.read_appeal(api, bundle["appeal_id"])
        assert_fields(unchanged, status="SUBMITTED")
        assert_integer(
            unchanged["version"], bundle["appeal"]["version"], "version"
        )
        assert_null(unchanged, "granted_point_adjustment", "decided_at")
        contested = X.read_deficiency(api, bundle["deficiency_ids"][0])
        assert_fields(contested, status="OPEN")
        assert_two_decimals(contested["points_deducted"], 16.00, "points_deducted")
        owning_inspection = X.read_inspection(api, bundle["inspection_id"])
        assert_fields(owning_inspection, status="APPEALED")
        assert_one_decimal(owning_inspection["final_score"], 92.0, "final_score")
        assert_null(owning_inspection, "rescored_at")

    def test_an_adjustment_larger_than_the_contested_points_is_rejected(self, api):
        """20.00 exceeds the row's own 16.00 and is refused, not clamped.

        PRD: "and to be strictly greater than `0.00` while being no greater than
        the contested deficiency's current `points_deducted`, else
        `ERR_ADJUSTMENT_EXCEEDS_POINTS` (HTTP 422)."

        Design: Corner/errors/granting_an_adjustment_larger_than_the_contested_points_is_rejected
        """
        bundle = _submitted_score_correction_appeal(api)

        response = api.review_appeal(
            bundle["appeal_id"],
            F.appeal_review_payload(
                "GRANTED", granted_point_adjustment=OVER_GENEROUS_ADJUSTMENT
            ),
            X.APPEALS,
        )

        assert_error(response, ApiErrorId.ADJUSTMENT_EXCEEDS_POINTS)
        unchanged = X.read_appeal(api, bundle["appeal_id"])
        assert_fields(unchanged, status="SUBMITTED")
        assert_integer(
            unchanged["version"], bundle["appeal"]["version"], "version"
        )
        assert_two_decimals(
            X.read_deficiency(api, bundle["deficiency_ids"][0])["points_deducted"],
            16.00,
            "points_deducted",
        )
        owning_inspection = X.read_inspection(api, bundle["inspection_id"])
        assert_one_decimal(owning_inspection["final_score"], 92.0, "final_score")
        assert_null(owning_inspection, "rescored_at")
        assert_one_decimal(
            X.read_property(api, bundle["property_id"])["last_final_score"],
            92.0,
            "last_final_score",
        )


class TestTheGrantedTechnicalAppealCascade:
    """One review travels appeal, deficiency, inspection and property.

    Nothing in the request names the inspection or the property, yet both are
    rewritten by the void the grant produces.
    """

    def test_the_void_rewrites_both_score_variants(self, api):
        """120.00 of dwelling points falls to 80.00 and 50.0 becomes 60.0.

        PRD: "On a `TECHNICAL_ERROR` grant, the contested deficiency's `status`
        becomes `VOIDED` and its `points_deducted` becomes `0.00`"

        PRD: "the inspection recomputes `unit_area_points`, `inside_area_points`,
        `outside_area_points`, `total_points_deducted` and `life_threatening_count`,
        recomputes `provisional_score` and `final_score` from the surviving
        deficiencies by the same two variants described above, sets `rescored_at`
        to the appeal's `decided_at`, and returns `APPEALED -> SCORED`"

        Design: Difficulty/transitive_cascade/cascade_b_granted_technical_appeal_void_rewrites_score_and_posture
        """
        bundle = _three_heavy_rows_scored_fifty(api)
        assert_scores(bundle["inspection"], 50.0, 50.0)

        response = api.review_appeal(
            bundle["appeal_id"],
            F.appeal_review_payload("GRANTED", reviewer_note="Duplicate citation"),
            X.APPEALS,
        )

        granted = assert_ok(response)
        assert_fields(granted, status="GRANTED")
        assert_instant(granted["decided_at"], K.APPEAL_DECIDED_AT, "decided_at")
        voided = X.read_deficiency(api, bundle["deficiency_ids"][2])
        assert_fields(voided, status="VOIDED")
        assert_two_decimals(voided["points_deducted"], 0.00, "points_deducted")
        assert_two_decimals(
            X.read_deficiency(api, bundle["deficiency_ids"][0])["points_deducted"],
            40.00,
            "points_deducted",
        )
        rescored = X.read_inspection(api, bundle["inspection_id"])
        assert_fields(rescored, status="SCORED")
        assert_two_decimals(rescored["unit_area_points"], 80.00, "unit_area_points")
        assert_two_decimals(
            rescored["total_points_deducted"], 80.00, "total_points_deducted"
        )
        assert_scores(rescored, 60.0, 60.0)
        assert_instant(rescored["rescored_at"], K.APPEAL_DECIDED_AT, "rescored_at")
        assert_instant(
            rescored["appeal_deadline_at"],
            K.APPEAL_DEADLINE_AT,
            "appeal_deadline_at",
        )

    def test_the_rewritten_score_lifts_the_property_off_watch(self, api):
        """The strict `< 60.00` floor means the new 60.0 is clean.

        PRD: "because `final_score` changed, the property's `last_final_score` is
        rewritten and its `readiness_posture` re-derived"

        PRD: "Otherwise, if `last_final_score` is not null and is below 60.00, the
        posture is `WATCH`. The comparison is made against the score as stored, at
        one decimal place."

        Design: Difficulty/transitive_cascade/cascade_b_granted_technical_appeal_void_rewrites_score_and_posture
        """
        bundle = _three_heavy_rows_scored_fifty(api)
        watched = X.read_property(api, bundle["property_id"])
        assert_fields(watched, readiness_posture="WATCH")
        assert_one_decimal(watched["last_final_score"], 50.0, "last_final_score")

        response = api.review_appeal(
            bundle["appeal_id"],
            F.appeal_review_payload("GRANTED", reviewer_note="Duplicate citation"),
            X.APPEALS,
        )

        assert_ok(response)
        lifted = X.read_property(api, bundle["property_id"])
        assert_one_decimal(lifted["last_final_score"], 60.0, "last_final_score")
        assert_fields(lifted, readiness_posture="READY")
        assert_integer(lifted["version"], watched["version"] + 1, "version")


class TestTheBoundedResubmissionCycle:
    """`SUBMITTED -> RETURNED_FOR_INFO -> SUBMITTED` runs at most twice."""

    def test_the_third_resubmission_is_refused(self, api):
        """The same `RETURNED_FOR_INFO` state that admitted two now refuses.

        PRD: "the appeal's `status` must be `RETURNED_FOR_INFO`, and
        `resubmission_count` must be strictly less than 2; a third attempt is
        rejected with `ERR_APPEAL_RESUBMIT_LIMIT` (HTTP 409), after which the
        appeal can only be granted or denied."

        Design: Difficulty/non_linear_state_machine/appeal_returned_for_info_cycle_third_resubmit_rejected
        """
        bundle = _appeal_returned_three_times(api)
        exhausted = X.read_appeal(api, bundle["appeal_id"])
        assert_fields(
            exhausted, status="RETURNED_FOR_INFO", resubmission_count=2
        )

        response = api.resubmit_appeal(
            bundle["appeal_id"],
            F.appeal_resubmit_payload(additional_evidence=THIRD_RESUBMIT_EVIDENCE),
            bundle["owner_headers"],
        )

        assert_error(response, ApiErrorId.APPEAL_RESUBMIT_LIMIT)
        unchanged = X.read_appeal(api, bundle["appeal_id"])
        assert_fields(
            unchanged,
            status="RETURNED_FOR_INFO",
            resubmission_count=2,
            additional_evidence=SECOND_RESUBMIT_EVIDENCE,
        )
        assert_instant(unchanged["decided_at"], THIRD_RETURN_AT, "decided_at")
        assert_integer(unchanged["version"], exhausted["version"], "version")

    def test_the_cycle_leaves_the_inspection_parked_in_appealed(self, api):
        """Two legal resubmits climb 0 to 1 to 2 and never touch the score.

        PRD: "A successful resubmission moves the appeal `RETURNED_FOR_INFO ->
        SUBMITTED`, stores `additional_evidence`, increments `resubmission_count`
        by 1, clears `decided_at` to null, and increments the appeal's `version`
        by 1."

        PRD: "A return for more information sets the appeal's `status` to
        `RETURNED_FOR_INFO`, stamps `decided_at` and stores the `reviewer_note`,
        and leaves the inspection in `APPEALED` precisely because a non-terminal
        appeal still exists."

        Design: Difficulty/non_linear_state_machine/appeal_returned_for_info_cycle_third_resubmit_rejected
        """
        bundle = _appeal_returned_three_times(api)
        first_return, first_resubmit, second_return, second_resubmit, third_return = (
            bundle["history"][0],
            bundle["history"][1],
            bundle["history"][2],
            bundle["history"][3],
            bundle["history"][4],
        )
        assert_fields(
            first_return, status="RETURNED_FOR_INFO", resubmission_count=0
        )
        assert_fields(first_resubmit, status="SUBMITTED", resubmission_count=1)
        assert_null(first_resubmit, "decided_at")
        assert_fields(
            second_return, status="RETURNED_FOR_INFO", resubmission_count=1
        )
        assert_fields(second_resubmit, status="SUBMITTED", resubmission_count=2)
        assert_null(second_resubmit, "decided_at")
        assert_fields(
            third_return, status="RETURNED_FOR_INFO", resubmission_count=2
        )

        response = api.resubmit_appeal(
            bundle["appeal_id"],
            F.appeal_resubmit_payload(additional_evidence=THIRD_RESUBMIT_EVIDENCE),
            bundle["owner_headers"],
        )

        assert_error(response, ApiErrorId.APPEAL_RESUBMIT_LIMIT)
        parked = X.read_inspection(api, bundle["inspection_id"])
        assert_fields(parked, status="APPEALED")
        assert_scores(parked, 92.0, 92.0)
