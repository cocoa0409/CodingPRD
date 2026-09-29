"""Finalization, the plan window and the follow-up loop.

The deadline trio is derived in a pinned order - the appeal window from the
original scoring instant, the plan window from the current score anchored on the
rescore - and the follow-up must land between the owner's promise and the
agency's deadline.
"""

from test_helpers import (
    ApiErrorId,
    assert_cents,
    assert_created,
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
MAPLE_TWO_OCCUPIED = [
    {
        "unit_number": "101",
        "bedroom_count": 2,
        "occupancy_status": "OCCUPIED",
        "occupant_display_name": "Household 101",
    },
    {"unit_number": "102", "bedroom_count": 1, "occupancy_status": "OCCUPIED"},
]
FOUR_DEFINITIONS = ("LT_GAS", "SEV_WINDOW", "MOD_HANDRAIL", "LOW_TRASH")
CAP_DUE_AT = "2026-10-26T09:00:00.000Z"
FOLLOWUP_DUE_AT = "2026-11-25T09:00:00.000Z"
LATE_TARGET_AT = "2026-10-27T09:00:00.000Z"
EARLY_FOLLOW_UP_START = "2026-10-19T09:00:00.000Z"
EARLY_FOLLOW_UP_END = "2026-10-19T17:00:00.000Z"
PARENT_FINALIZE_ATTEMPT_AT = "2026-11-03T09:00:00.000Z"
RESCORED_CAP_DUE_AT = "2026-10-28T09:00:00.000Z"
RESCORED_FOLLOWUP_DUE_AT = "2026-11-07T09:00:00.000Z"
PRE_APPEAL_CAP_DUE_AT = "2026-10-11T09:00:00.000Z"
LT_CORRECTED_AT = "2026-09-10T12:00:00.000Z"
OVERSIZED_COST_CENTS = 900000
CEDAR_RESERVE_CENTS = 500000
REVISED_NARRATIVE = "Replace both egress windows and the frames"


def _cap_required(api):
    """Two severe rows, 84.0, finalized into the 45-day plan window."""
    return X.finalized_lifecycle(api, unit_specs=CEDAR_UNIT, deficiency_count=2)


def _submitted_plan(api):
    """A lawful 400000-cent plan sitting in SUBMITTED, never rejected."""
    bundle = _cap_required(api)
    bundle["plan"] = X.submitted_cap(
        api, bundle["inspection_id"], bundle["property_id"]
    )
    bundle["plan_id"] = bundle["plan"]["id"]
    return bundle


def _approved_plan(api):
    """The same plan carried to APPROVED, which advances the inspection."""
    return X.cap_approved_lifecycle(
        api, unit_specs=CEDAR_UNIT, deficiency_count=2
    )


def _follow_up_scheduled(api):
    """The follow-up created and linked, parent parked awaiting its close."""
    bundle = _approved_plan(api)
    bundle["follow_up"] = assert_created(
        api.schedule_follow_up(
            bundle["plan_id"], F.follow_up_payload(), X.INSPECTOR
        )
    )
    bundle["follow_up_id"] = bundle["follow_up"]["id"]
    return bundle


def _appeal_pending_on_a_scored_inspection(api):
    """A SUBMITTED appeal parks the inspection in APPEALED."""
    bundle = X.scored_lifecycle(api, unit_specs=CEDAR_UNIT, deficiency_count=2)
    bundle["appeal"] = X.filed_appeal(
        api,
        bundle["inspection_id"],
        bundle["property_id"],
        bundle["deficiency_ids"][0],
    )
    return bundle


def _rescored_by_a_granted_appeal(api):
    """78.3 at scoring, 82.3 after a void - a plan window tier apart."""
    bundle = X.adopted_standard(api, FOUR_DEFINITIONS)
    bundle.update(X.property_with_units(api, K.MAPLE_COURT, MAPLE_TWO_OCCUPIED))
    bundle.update(
        X.inspection_with_access(
            api,
            bundle["property_id"],
            bundle["standard_id"],
            access_results={bundle["unit_ids"]["102"]: "REFUSED"},
        )
    )
    recorded = X.record_deficiencies(
        api,
        bundle["inspection_id"],
        [
            {
                "defect_definition_id": bundle["definition_ids"]["SEV_WINDOW"],
                "unit_id": bundle["unit_ids"]["101"],
            },
            {
                "defect_definition_id": bundle["definition_ids"]["SEV_WINDOW"],
                "unit_id": bundle["unit_ids"]["101"],
            },
            {
                "defect_definition_id": bundle["definition_ids"]["MOD_HANDRAIL"],
                "inspectable_area": "INSIDE",
            },
            {
                "defect_definition_id": bundle["definition_ids"]["LOW_TRASH"],
                "inspectable_area": "OUTSIDE",
            },
            {
                "defect_definition_id": bundle["definition_ids"]["LT_GAS"],
                "unit_id": bundle["unit_ids"]["101"],
            },
        ],
    )
    bundle["deficiencies"] = recorded["deficiencies"]
    bundle["deficiency_ids"] = [row["id"] for row in recorded["deficiencies"]]
    assert_ok(
        api.record_correction(
            bundle["deficiency_ids"][4],
            F.correction_payload(
                corrected_at=LT_CORRECTED_AT, note="Connector replaced"
            ),
            bundle["owner_headers"],
        )
    )
    bundle["scored"] = X.scored_inspection(api, bundle["inspection_id"])
    bundle["appeal"] = X.filed_appeal(
        api,
        bundle["inspection_id"],
        bundle["property_id"],
        bundle["deficiency_ids"][1],
    )
    bundle["rescored"] = assert_ok(
        api.review_appeal(
            bundle["appeal"]["id"],
            F.appeal_review_payload("GRANTED", reviewer_note="Duplicate citation"),
            X.APPEALS,
        )
    )
    return bundle


class TestFinalizingUnderAPendingAppeal:
    """No deadline may be computed off a score still under challenge."""

    def test_finalization_is_refused_while_an_appeal_is_submitted(self, api):
        """The fork is never reached, so the deadline trio stays null.

        PRD: "the operation is refused while any appeal of the inspection remains
        in `SUBMITTED` or `RETURNED_FOR_INFO`, with `ERR_APPEAL_PENDING` (HTTP
        409)."

        Design: Corner/errors/finalizing_while_an_appeal_is_pending_is_rejected_as_appeal_pending
        """
        bundle = _appeal_pending_on_a_scored_inspection(api)
        assert_fields(bundle["appeal"], status="SUBMITTED")

        response = api.finalize_inspection(
            bundle["inspection_id"],
            F.finalize_payload(finalized_at=K.FINALIZED_AT),
            X.INSPECTOR,
        )

        assert_error(response, ApiErrorId.APPEAL_PENDING)
        unchanged = X.read_inspection(api, bundle["inspection_id"])
        assert_fields(unchanged, status="APPEALED", cap_required=False)
        assert_null(
            unchanged,
            "finalized_at",
            "cap_window_days",
            "cap_due_at",
            "followup_due_at",
        )
        assert_one_decimal(unchanged["final_score"], 84.0, "final_score")


class TestThePlanWindowUpperBound:
    """The owner's committed target must sit inside `cap_due_at`."""

    def test_a_target_after_the_plan_deadline_is_rejected(self, api):
        """One day past 2026-10-26T09:00 fails on the date, not the money.

        PRD: "`target_completion_at` must be no later than the inspection's
        `cap_due_at`, else `ERR_CAP_TARGET_AFTER_DEADLINE` (HTTP 422)."

        PRD: "a `final_score` of at least 90.00 gives `cap_window_days` 60, at
        least 80.00 gives 45, at least 60.00 gives 30, and anything below 60.00
        gives 15."

        Design: Corner/errors/plan_with_a_target_after_the_cap_deadline_is_rejected
        """
        bundle = _cap_required(api)
        finalized = bundle["inspection"]
        assert_integer(finalized["cap_window_days"], 45, "cap_window_days")
        assert_instant(finalized["cap_due_at"], CAP_DUE_AT, "cap_due_at")

        response = api.create_cap(
            F.cap_payload(
                bundle["inspection_id"], target_completion_at=LATE_TARGET_AT
            ),
            bundle["owner_headers"],
        )

        rejection = assert_error(response, ApiErrorId.CAP_TARGET_AFTER_DEADLINE)
        assert rejection["error_id"] != ApiErrorId.CAP_COST_EXCEEDS_RESERVE
        assert_cents(
            X.read_property(api, bundle["property_id"])["capital_reserve_cents"],
            CEDAR_RESERVE_CENTS,
            "capital_reserve_cents",
        )
        unchanged = X.read_inspection(api, bundle["inspection_id"])
        assert_fields(unchanged, status="CAP_REQUIRED")
        assert_integer(unchanged["version"], finalized["version"], "version")
        assert_total_count(
            api.list_caps(X.ADMIN, inspection_id=bundle["inspection_id"]), 0
        )


class TestTheFollowUpWindowLowerBound:
    """The follow-up window has a floor as well as a ceiling."""

    def test_a_follow_up_before_the_committed_target_is_rejected(self, api):
        """One day before the owner promised to be finished is too early.

        PRD: "The `scheduled_start` must be no earlier than the plan's
        `target_completion_at` and no later than the parent inspection's
        `followup_due_at`; a window that opens before the owner's own committed
        completion instant, or after the agency's follow-up deadline, is rejected
        with `ERR_FOLLOW_UP_TOO_EARLY` (HTTP 422)."

        Design: Corner/errors/follow_up_scheduled_before_the_plan_target_is_rejected_as_too_early
        """
        bundle = _approved_plan(api)
        assert_instant(
            bundle["inspection"]["followup_due_at"],
            FOLLOWUP_DUE_AT,
            "followup_due_at",
        )
        assert_instant(
            bundle["plan"]["target_completion_at"],
            K.CAP_TARGET_COMPLETION_AT,
            "target_completion_at",
        )

        response = api.schedule_follow_up(
            bundle["plan_id"],
            F.follow_up_payload(
                scheduled_start=EARLY_FOLLOW_UP_START,
                scheduled_end=EARLY_FOLLOW_UP_END,
            ),
            X.INSPECTOR,
        )

        assert_error(response, ApiErrorId.FOLLOW_UP_TOO_EARLY)
        unchanged = X.read_cap(api, bundle["plan_id"])
        assert_fields(unchanged, status="APPROVED")
        assert_null(unchanged, "follow_up_inspection_id")
        assert_integer(unchanged["version"], bundle["plan"]["version"], "version")
        assert_fields(
            X.read_inspection(api, bundle["inspection_id"]), status="CAP_APPROVED"
        )
        assert_total_count(
            api.list_inspections(
                X.INSPECTOR,
                property_id=bundle["property_id"],
                inspection_kind="FOLLOW_UP",
            ),
            0,
        )
        assert_integer(
            X.read_unit(api, bundle["unit_ids"]["101"])["prior_deficiency_count"],
            0,
            "prior_deficiency_count",
        )


class TestSchedulingTheFollowUp:
    """One call weaves a new inspection, the plan link and the parent."""

    def test_the_follow_up_inherits_the_parents_pinned_standard(self, api):
        """Three rows move together and the unit history is frozen at 2.

        PRD: "On success a fresh `Inspection` is created with `inspection_kind`
        `FOLLOW_UP`, `status` `SCHEDULED`, and the same `property_id` and
        `standard_id` as its parent - the follow-up inherits the parent's pinned
        standard rather than picking up whatever is currently `ADOPTED`."

        PRD: "Its identifier is written to the plan's `follow_up_inspection_id`,
        the plan moves `APPROVED -> FOLLOW_UP_SCHEDULED`, and the parent
        inspection moves `CAP_APPROVED -> FOLLOW_UP_SCHEDULED`. Every `Unit`
        carrying a non-`VOIDED` deficiency of the parent inspection recomputes its
        `prior_deficiency_count` at this point"

        Design: Corner/endpoints/schedule_follow_up_creates_the_linked_follow_up_inspection
        """
        bundle = _approved_plan(api)

        response = api.schedule_follow_up(
            bundle["plan_id"], F.follow_up_payload(), X.INSPECTOR
        )

        follow_up = assert_created(response)
        assert_fields(
            follow_up,
            inspection_kind="FOLLOW_UP",
            status="SCHEDULED",
            property_id=bundle["property_id"],
            standard_id=bundle["standard_id"],
            sample_size=0,
        )
        assert_instant(
            follow_up["scheduled_start"], K.FOLLOW_UP_START, "scheduled_start"
        )
        assert_instant(follow_up["scheduled_end"], K.FOLLOW_UP_END, "scheduled_end")
        assert_null(follow_up, "final_score")
        linked = X.read_cap(api, bundle["plan_id"])
        assert_fields(
            linked,
            status="FOLLOW_UP_SCHEDULED",
            follow_up_inspection_id=follow_up["id"],
        )
        assert_integer(linked["version"], bundle["plan"]["version"] + 1, "version")
        assert_fields(
            X.read_inspection(api, bundle["inspection_id"]),
            status="FOLLOW_UP_SCHEDULED",
        )
        assert_integer(
            X.read_unit(api, bundle["unit_ids"]["101"])["prior_deficiency_count"],
            2,
            "prior_deficiency_count",
        )


class TestClosingTheParentAheadOfItsFollowUp:
    """The parent cannot close before the visit that verifies it."""

    def test_finalizing_a_parent_with_an_open_follow_up_is_rejected(self, api):
        """The follow-up has never been sampled, started or scored.

        PRD: "An inspection sitting in `FOLLOW_UP_SCHEDULED` moves
        `FOLLOW_UP_SCHEDULED -> CLOSED` once the inspection named by its plan's
        `follow_up_inspection_id` has itself reached `CLOSED`; attempting it
        earlier is rejected with `ERR_FOLLOW_UP_NOT_CLOSED` (HTTP 409)."

        Design: Corner/errors/finalizing_a_parent_whose_follow_up_is_still_open_is_rejected
        """
        bundle = _follow_up_scheduled(api)
        parent = X.read_inspection(api, bundle["inspection_id"])
        assert_fields(
            X.read_inspection(api, bundle["follow_up_id"]), status="SCHEDULED"
        )

        response = api.finalize_inspection(
            bundle["inspection_id"],
            F.finalize_payload(finalized_at=PARENT_FINALIZE_ATTEMPT_AT),
            X.INSPECTOR,
        )

        assert_error(response, ApiErrorId.FOLLOW_UP_NOT_CLOSED)
        unchanged = X.read_inspection(api, bundle["inspection_id"])
        assert_fields(unchanged, status="FOLLOW_UP_SCHEDULED")
        assert_instant(unchanged["finalized_at"], K.FINALIZED_AT, "finalized_at")
        assert_integer(unchanged["version"], parent["version"], "version")
        assert_fields(
            X.read_cap(api, bundle["plan_id"]), status="FOLLOW_UP_SCHEDULED"
        )


class TestThePinnedDeadlineDerivationOrder:
    """The appeal window and the plan window read different instants.

    A granted appeal lifts the score across a tier boundary, so the plan window
    must be computed from the post-rescore figure while the appeal deadline stays
    where the first scoring put it.
    """

    def test_the_plan_window_reads_the_post_rescore_score(self, api):
        """82.3 buys the 45-day tier anchored on `rescored_at`, not 30 days.

        PRD: "At finalization the window tier reads the **current**
        `final_score`, meaning the post-rescore value when an appeal was granted
        and the original value otherwise"

        PRD: "The anchor instant is `rescored_at` when it is non-null and
        `scored_at` otherwise; `cap_due_at` is that anchor advanced by
        `cap_window_days` multiplied by 24 hours."

        Design: Difficulty/combinatorial_formula/cap_window_pinned_evaluation_order_appeal_moves_tier_but_not_deadline
        """
        bundle = _rescored_by_a_granted_appeal(api)
        assert_one_decimal(bundle["scored"]["final_score"], 78.3, "final_score")

        response = api.finalize_inspection(
            bundle["inspection_id"],
            F.finalize_payload(finalized_at=K.FINALIZED_AT),
            X.INSPECTOR,
        )

        finalized = assert_ok(response)
        assert_fields(finalized, status="CAP_REQUIRED", cap_required=True)
        assert_integer(finalized["cap_window_days"], 45, "cap_window_days")
        assert finalized["cap_window_days"] != 30
        assert_instant(finalized["cap_due_at"], RESCORED_CAP_DUE_AT, "cap_due_at")
        assert finalized["cap_due_at"] != PRE_APPEAL_CAP_DUE_AT
        assert_instant(
            finalized["followup_due_at"],
            RESCORED_FOLLOWUP_DUE_AT,
            "followup_due_at",
        )

    def test_the_appeal_deadline_stays_on_the_original_scoring_instant(self, api):
        """The void moved the score by 4.0 points and the deadline not at all.

        PRD: "The appeal deadline was derived at first scoring from `scored_at`
        alone and never reads any score (§3.7). Each granted appeal recomputes
        `final_score` and stamps `rescored_at`, leaving `appeal_deadline_at`
        untouched."

        Design: Difficulty/combinatorial_formula/cap_window_pinned_evaluation_order_appeal_moves_tier_but_not_deadline
        """
        bundle = _rescored_by_a_granted_appeal(api)
        assert_fields(
            X.read_deficiency(api, bundle["deficiency_ids"][1]), status="VOIDED"
        )

        response = api.finalize_inspection(
            bundle["inspection_id"],
            F.finalize_payload(finalized_at=K.FINALIZED_AT),
            X.INSPECTOR,
        )

        finalized = assert_ok(response)
        assert_instant(
            finalized["appeal_deadline_at"],
            K.APPEAL_DEADLINE_AT,
            "appeal_deadline_at",
        )
        assert_instant(
            finalized["rescored_at"], K.APPEAL_DECIDED_AT, "rescored_at"
        )
        assert_scores(finalized, 72.3, 82.3)
        assert_two_decimals(
            finalized["total_points_deducted"], 58.00, "total_points_deducted"
        )
        assert_two_decimals(
            X.read_deficiency(api, bundle["deficiency_ids"][1])["points_deducted"],
            0.00,
            "points_deducted",
        )


class TestPlanResubmissionGateOrder:
    """The state ladder is evaluated sixty priority steps before the money."""

    def test_a_resubmit_of_a_submitted_plan_reports_the_state_error(self, api):
        """900000 cents against a 500000 reserve is never even weighed.

        PRD: "the plan's `status` must be `REJECTED`; and the same two fiscal
        constraints re-apply, with `total_estimated_cost_cents` checked against
        the property's current `capital_reserve_cents` under
        `ERR_CAP_COST_EXCEEDS_RESERVE`"

        PRD: "the target row's `status`, `repair_status`, `verification_status`
        or `adoption_status` admits the requested transition, else the state
        error for that resource type: `ERR_STANDARD_ALREADY_ADOPTED`,
        `ERR_INSPECTION_INVALID_STATE`, `ERR_SELECTION_INVALID_STATE`"

        Design: Difficulty/priority_pair_validation_conflict/cap_resubmit_rejected_with_invalid_state_not_cost_exceeds_reserve
        """
        bundle = _submitted_plan(api)
        assert_fields(bundle["plan"], status="SUBMITTED", revision_count=0)

        response = api.resubmit_cap(
            bundle["plan_id"],
            F.cap_resubmit_payload(
                narrative=REVISED_NARRATIVE,
                total_estimated_cost_cents=OVERSIZED_COST_CENTS,
                milestone_count=4,
            ),
            bundle["owner_headers"],
        )

        rejection = assert_error(response, ApiErrorId.CAP_INVALID_STATE)
        assert rejection["error_id"] != ApiErrorId.CAP_COST_EXCEEDS_RESERVE
        unchanged = X.read_cap(api, bundle["plan_id"])
        assert_fields(
            unchanged, status="SUBMITTED", milestone_count=3, revision_count=0
        )
        assert_cents(
            unchanged["total_estimated_cost_cents"],
            K.CAP_COST_CENTS,
            "total_estimated_cost_cents",
        )
        assert_fields(unchanged, narrative=K.CAP_NARRATIVE)

    def test_the_refused_resubmit_leaves_the_plan_window_intact(self, api):
        """The inspection is still awaiting a compliant plan on the same terms.

        PRD: "On `REJECTED` the plan moves `SUBMITTED -> REJECTED`, stamps
        `decided_at`, stores the `reviewer_note`, and leaves the inspection
        sitting in `CAP_REQUIRED`; only the plan's `version` increments by 1."

        Design: Difficulty/priority_pair_validation_conflict/cap_resubmit_rejected_with_invalid_state_not_cost_exceeds_reserve
        """
        bundle = _submitted_plan(api)

        response = api.resubmit_cap(
            bundle["plan_id"],
            F.cap_resubmit_payload(
                total_estimated_cost_cents=OVERSIZED_COST_CENTS, milestone_count=4
            ),
            bundle["owner_headers"],
        )

        assert_error(response, ApiErrorId.CAP_INVALID_STATE)
        unchanged = X.read_inspection(api, bundle["inspection_id"])
        assert_fields(unchanged, status="CAP_REQUIRED")
        assert_one_decimal(unchanged["final_score"], 84.0, "final_score")
        assert_integer(unchanged["cap_window_days"], 45, "cap_window_days")
        assert_instant(unchanged["cap_due_at"], CAP_DUE_AT, "cap_due_at")
        assert_cents(
            X.read_property(api, bundle["property_id"])["capital_reserve_cents"],
            CEDAR_RESERVE_CENTS,
            "capital_reserve_cents",
        )


class TestPlanApprovalCrossesTwoEntities:
    """The review is admissible because of the inspection, and moves it."""

    def test_the_approval_stamps_the_plan(self, api):
        """The plan's own status alone cannot decide the call.

        PRD: "Both branches require the plan's `status` to be `SUBMITTED` and the
        owning inspection's `status` to be `CAP_REQUIRED`"

        PRD: "On `APPROVED` the plan moves `SUBMITTED -> APPROVED`, stamps
        `decided_at`, stores the `reviewer_note`, and drives the inspection
        `CAP_REQUIRED -> CAP_APPROVED`"

        Design: Difficulty/cross_entity_state_dependency/cap_approval_requires_and_advances_the_owning_inspection_state
        """
        bundle = _submitted_plan(api)
        assert_fields(
            X.read_inspection(api, bundle["inspection_id"]), status="CAP_REQUIRED"
        )

        response = api.review_cap(
            bundle["plan_id"], F.cap_review_payload("APPROVED"), X.REVIEWER
        )

        approved = assert_ok(response)
        assert_fields(approved, status="APPROVED", revision_count=0)
        assert_instant(approved["decided_at"], K.CAP_DECIDED_AT, "decided_at")
        assert_null(approved, "follow_up_inspection_id")
        assert_integer(approved["version"], bundle["plan"]["version"] + 1, "version")

    def test_the_approval_advances_the_owning_inspection(self, api):
        """Nothing in the request names the inspection it moves.

        PRD: "the `version` of the plan and of the inspection each increment by
        1."

        PRD: "On `APPROVED` the plan moves `SUBMITTED -> APPROVED`, stamps
        `decided_at`, stores the `reviewer_note`, and drives the inspection
        `CAP_REQUIRED -> CAP_APPROVED`"

        Design: Difficulty/cross_entity_state_dependency/cap_approval_requires_and_advances_the_owning_inspection_state
        """
        bundle = _submitted_plan(api)
        before = X.read_inspection(api, bundle["inspection_id"])

        response = api.review_cap(
            bundle["plan_id"], F.cap_review_payload("APPROVED"), X.REVIEWER
        )

        assert_ok(response)
        advanced = X.read_inspection(api, bundle["inspection_id"])
        assert_fields(advanced, status="CAP_APPROVED")
        assert_integer(advanced["version"], before["version"] + 1, "version")
        assert_instant(advanced["cap_due_at"], CAP_DUE_AT, "cap_due_at")
        assert_instant(advanced["finalized_at"], K.FINALIZED_AT, "finalized_at")
