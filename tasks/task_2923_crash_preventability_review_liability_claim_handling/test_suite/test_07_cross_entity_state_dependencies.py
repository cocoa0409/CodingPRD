"""Writes on one entity gated by the state of another, and repaired there."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_instants_equal, assert_points_1dp, assert_score_2dp
from test_helpers.constants import (
    ACTION_STATE_COMPLETED,
    ACTION_STATE_ISSUED,
    ACTION_TIER_SUSPENSION,
    ACTION_TYPE_SUSPENSION,
    BALLOT_DISPOSITION_NON_PREVENTABLE,
    BALLOT_DISPOSITION_PREVENTABLE,
    DECISION_BASIS_UNWEIGHTED_MAJORITY,
    DETERMINATION_PENDING,
    DETERMINATION_PREVENTABLE,
    DRIVER_STATUS_ACTIVE,
    DRIVER_STATUS_SUSPENDED_PENDING_ACTION,
    EMPLOYMENT_DECISION_CONTINUE,
    EMPLOYMENT_DECISION_PENDING,
    EVIDENCE_ELD_LOG,
    EVIDENCE_FORWARD_CAMERA,
    EVIDENCE_POSTURE_COMPLETE,
    EVIDENCE_POSTURE_PARTIAL,
    EVIDENCE_TELEMATICS,
    PREVENTABILITY_PREVENTABLE,
    RETRAINING_STATUS_COMPLETED,
    RETRAINING_STATUS_PENDING,
    REVIEW_STATE_DECIDED,
    REVIEW_STATE_DELIBERATION,
    ROUTE_CLASS_REGIONAL,
    SEVERITY_SEVERE,
    STAFFING_POSTURE_OK,
    TENURE_OVER_36_MONTHS,
    TOW_REASON_DISABLING_DAMAGE,
)
from test_helpers.fixtures import (
    COMMITTEE_ONE,
    COMMITTEE_THREE,
    COMMITTEE_TWO,
    SAFETY_ADMIN,
    SAFETY_MANAGER,
    build_crash,
    build_discipline,
    build_driver,
    build_preserved_evidence,
    build_review_case,
    build_statement,
    build_terminal,
    cast_ballot,
    cast_quorum,
    decide_case,
    open_deliberation,
    preserve_evidence,
    request_evidence,
    set_clock,
)

MARYSVILLE_WINDOW = {
    "window_start_at": "2026-07-30T13:00:00Z",
    "window_end_at": "2026-07-30T15:00:00Z",
    "retention_deadline_at": "2026-10-31T00:00:00Z",
}

DIVIDED_BALLOTS = (
    (
        COMMITTEE_ONE,
        BALLOT_DISPOSITION_PREVENTABLE,
        {
            "speed_and_spacing": 3,
            "hazard_recognition": 2,
            "vehicle_condition_precheck": 2,
            "regulatory_compliance": 3,
            "evasive_action": 3,
        },
        2.60,
    ),
    (
        COMMITTEE_TWO,
        BALLOT_DISPOSITION_PREVENTABLE,
        {
            "speed_and_spacing": 2,
            "hazard_recognition": 3,
            "vehicle_condition_precheck": 2,
            "regulatory_compliance": 3,
            "evasive_action": 2,
        },
        2.45,
    ),
    (
        COMMITTEE_THREE,
        BALLOT_DISPOSITION_NON_PREVENTABLE,
        {
            "speed_and_spacing": 4,
            "hazard_recognition": 2,
            "vehicle_condition_precheck": 3,
            "regulatory_compliance": 2,
            "evasive_action": 3,
        },
        2.85,
    ),
)

EXPECTED_DIVIDED_COMMITTEE_SCORE = 2.63
SEVERE_POINTS = 8.0


def _quorate_case_on_a_partial_record(api: ApiClient) -> dict:
    """Three live ballots, but only one of the three required kinds preserved."""
    terminal = build_terminal(
        api,
        name="Marysville Terminal",
        terminal_code="MAR01",
        region_code="OH",
        annual_miles_millions=4.0,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-1401",
        full_name="Cyril Okonkwo",
        cdl_number="OH-CDL-1401",
        hire_date="2015-06-01",
    )
    crash = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-07-30T14:00:00Z",
        notified_at="2026-07-30T14:12:00Z",
        location_text="US-33 at Industrial Pkwy",
        severity=SEVERITY_SEVERE,
        route_class=ROUTE_CLASS_REGIONAL,
        tow_away=True,
        tow_reason=TOW_REASON_DISABLING_DAMAGE,
        injury_transported_count=1,
        mechanical_factor=True,
    )
    requested = {}
    for kind, device in (
        (EVIDENCE_TELEMATICS, "ECM-7742"),
        (EVIDENCE_FORWARD_CAMERA, "CAM-7742"),
        (EVIDENCE_ELD_LOG, "ELD-7742"),
    ):
        requested[kind] = request_evidence(
            api, crash["id"], kind=kind, source_device_id=device, **MARYSVILLE_WINDOW
        )
    preserve_evidence(
        api,
        requested[EVIDENCE_TELEMATICS]["id"],
        preserved_copy_uri="s3://evidence/2923m/ecm-7742.json",
        evidence_hash="9f1c4d2ea77b40158c3e6b0a5d1f8e77",
    )
    build_statement(
        api,
        crash["id"],
        driver["id"],
        narrative=(
            "Traffic stopped abruptly on the ramp; I braked but could not stop in time."
        ),
        conditions_note="Light rain, dusk",
    )

    case = build_review_case(
        api, crash["id"], committee_name="Marysville Safety Review Committee"
    )
    current = open_deliberation(api, case["id"])
    for headers, vote, scores, _expected in DIVIDED_BALLOTS:
        current = cast_ballot(
            api, case["id"], current["version"], headers, vote=vote, scores=scores
        )
    return {
        "crash": crash,
        "driver": driver,
        "review_case": current,
        "evidence": requested,
    }


class TestDecidingDependsOnTheCrashRecord:
    """The case cannot leave DELIBERATION until another entity is repaired."""

    def test_the_case_is_blocked_by_the_crash_posture_and_not_by_its_own_tally(
        self, api: ApiClient
    ):
        """Quorum is satisfied, so only the other entity's posture can block.

        PRD: "The crash's `evidence_posture` must be `COMPLETE` or `COMPROMISED`,
        and a merely `PARTIAL` record is refused with
        `ERR_EVIDENCE_POSTURE_INSUFFICIENT`."

        Design: Difficulty/cross_entity_state_dependency/decide_blocked_by_crash_evidence_posture_partial
        """
        context = _quorate_case_on_a_partial_record(api)
        case_id = context["review_case"]["id"]
        crash = validate_success(api.get_crash(context["crash"]["id"], SAFETY_ADMIN))
        assert crash["evidence_posture"] == EVIDENCE_POSTURE_PARTIAL

        rows, meta = validate_paginated(api.list_votes(case_id, SAFETY_MANAGER))
        assert meta["total_count"] == 3
        assert all(row["superseded"] is False for row in rows)
        assert context["review_case"]["active_vote_count"] == 3

        body = validate_error(
            api.decide_review_case(case_id, headers=SAFETY_MANAGER),
            ApiErrorId.EVIDENCE_POSTURE_INSUFFICIENT.value,
        )
        assert body["error_id"] != ApiErrorId.QUORUM_NOT_MET.value

        blocked = validate_success(api.get_review_case(case_id, SAFETY_MANAGER))
        assert blocked["status"] == REVIEW_STATE_DELIBERATION
        assert blocked["determination"] == DETERMINATION_PENDING
        assert blocked["committee_score"] is None

    def test_preserving_the_two_missing_artifacts_unblocks_the_same_request(
        self, api: ApiClient
    ):
        """The dependency is repaired on a third entity, not on the case.

        PRD: "On a `COMPLETE` evidence record the basis is `UNWEIGHTED_MAJORITY`:
        the determination is `PREVENTABLE` when the count of live `PREVENTABLE`
        ballots strictly exceeds the count of live `NON_PREVENTABLE` ballots"

        Design: Difficulty/cross_entity_state_dependency/decide_blocked_by_crash_evidence_posture_partial
        """
        context = _quorate_case_on_a_partial_record(api)
        case_id = context["review_case"]["id"]
        validate_error(
            api.decide_review_case(case_id, headers=SAFETY_MANAGER),
            ApiErrorId.EVIDENCE_POSTURE_INSUFFICIENT.value,
        )

        preserve_evidence(
            api,
            context["evidence"][EVIDENCE_FORWARD_CAMERA]["id"],
            preserved_copy_uri="s3://evidence/2923m/cam-7742.mp4",
            evidence_hash="4b7a90ce15d34f6d8a2b1c0e7f39d551",
        )
        preserve_evidence(
            api,
            context["evidence"][EVIDENCE_ELD_LOG]["id"],
            preserved_copy_uri="s3://evidence/2923m/eld-7742.csv",
            evidence_hash="e2d81f60ba3c47a5911d7c48f6b0a933",
        )
        repaired = validate_success(api.get_crash(context["crash"]["id"], SAFETY_ADMIN))
        assert repaired["evidence_posture"] == EVIDENCE_POSTURE_COMPLETE

        decided = validate_success(api.decide_review_case(case_id, headers=SAFETY_MANAGER))
        assert decided["status"] == REVIEW_STATE_DECIDED
        assert decided["decision_basis"] == DECISION_BASIS_UNWEIGHTED_MAJORITY
        assert decided["determination"] == DETERMINATION_PREVENTABLE
        assert_score_2dp(
            decided["committee_score"],
            EXPECTED_DIVIDED_COMMITTEE_SCORE,
            "committee_score",
        )

    def test_each_ballot_keeps_the_score_it_was_cast_with(self, api: ApiClient):
        """The committee score is the mean of the already-rounded ballots.

        PRD: "a ballot's `weighted_member_score` and a case's `committee_score`
        to two decimal places"

        Design: Difficulty/cross_entity_state_dependency/decide_blocked_by_crash_evidence_posture_partial
        """
        context = _quorate_case_on_a_partial_record(api)
        rows, _ = validate_paginated(
            api.list_votes(context["review_case"]["id"], SAFETY_MANAGER)
        )
        by_member = {row["member_user_id"]: row for row in rows}
        for headers, vote, _scores, expected in DIVIDED_BALLOTS:
            row = by_member[headers["X-User-ID"]]
            assert row["vote"] == vote
            assert_score_2dp(
                row["weighted_member_score"],
                expected,
                f"{headers['X-User-ID']} weighted_member_score",
            )

    def test_the_repaired_decision_still_drives_the_driver_cascade(
        self, api: ApiClient
    ):
        """The unblocked determination is a full determination, not a partial one.

        PRD: "a `PREVENTABLE` outcome adds the crash's points while a
        `NON_PREVENTABLE` outcome contributes nothing at all"

        Design: Difficulty/cross_entity_state_dependency/decide_blocked_by_crash_evidence_posture_partial
        """
        context = _quorate_case_on_a_partial_record(api)
        for kind, uri, digest in (
            (
                EVIDENCE_FORWARD_CAMERA,
                "s3://evidence/2923m/cam-7742.mp4",
                "4b7a90ce15d34f6d8a2b1c0e7f39d551",
            ),
            (
                EVIDENCE_ELD_LOG,
                "s3://evidence/2923m/eld-7742.csv",
                "e2d81f60ba3c47a5911d7c48f6b0a933",
            ),
        ):
            preserve_evidence(
                api,
                context["evidence"][kind]["id"],
                preserved_copy_uri=uri,
                evidence_hash=digest,
            )
        validate_success(
            api.decide_review_case(context["review_case"]["id"], headers=SAFETY_MANAGER)
        )

        crash = validate_success(api.get_crash(context["crash"]["id"], SAFETY_ADMIN))
        assert crash["preventability_status"] == PREVENTABILITY_PREVENTABLE

        driver = validate_success(api.get_driver(context["driver"]["id"], SAFETY_ADMIN))
        assert_points_1dp(driver["preventable_points"], SEVERE_POINTS, "preventable_points")
        assert driver["required_action_tier"] == ACTION_TIER_SUSPENSION


NEWARK_WINDOW = {
    "window_start_at": "2026-07-30T08:00:00Z",
    "window_end_at": "2026-07-30T10:00:00Z",
    "retention_deadline_at": "2026-10-31T00:00:00Z",
}

SUSPENSION_START = "2026-08-02T00:00:00Z"
SUSPENSION_END = "2026-08-09T00:00:00Z"
JUST_AFTER_SUSPENSION = "2026-08-09T00:00:01Z"
UNANIMOUS_SCORE = 3.00


def _suspended_driver_with_pending_retraining(api: ApiClient) -> dict:
    """A suspension issued off a preventable severe crash, retraining pending."""
    terminal = build_terminal(
        api,
        name="Newark Terminal",
        terminal_code="NWK01",
        region_code="OH",
        annual_miles_millions=4.0,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-1501",
        full_name="Dinah Pryor",
        cdl_number="OH-CDL-1501",
        hire_date="2014-02-17",
    )
    crash = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-07-30T09:00:00Z",
        notified_at="2026-07-30T09:20:00Z",
        location_text="SR-16 at Cherry Valley Rd",
        severity=SEVERITY_SEVERE,
        route_class=ROUTE_CLASS_REGIONAL,
        tow_away=True,
        tow_reason=TOW_REASON_DISABLING_DAMAGE,
        injury_transported_count=1,
        mechanical_factor=True,
    )
    for kind, device in (
        (EVIDENCE_TELEMATICS, "ECM-8811"),
        (EVIDENCE_FORWARD_CAMERA, "CAM-8811"),
        (EVIDENCE_ELD_LOG, "ELD-8811"),
    ):
        build_preserved_evidence(
            api, crash["id"], kind=kind, source_device_id=device, **NEWARK_WINDOW
        )
    build_statement(
        api,
        crash["id"],
        driver["id"],
        narrative="I misjudged the closing speed of the vehicle ahead and struck it.",
        conditions_note=None,
    )

    case = build_review_case(
        api, crash["id"], committee_name="Newark Safety Review Committee"
    )
    opened = open_deliberation(api, case["id"])
    cast_quorum(
        api,
        opened,
        vote=BALLOT_DISPOSITION_PREVENTABLE,
        scores=factories.uniform_criterion_scores(3),
    )
    decided = decide_case(api, case["id"])
    action = build_discipline(
        api,
        driver["id"],
        crash["id"],
        action_type=ACTION_TYPE_SUSPENSION,
        action_note="Preventable rear-end collision with injury",
        suspension_start_at=SUSPENSION_START,
        suspension_end_at=SUSPENSION_END,
        retraining_course_code="DDC-8-2026",
    )
    return {
        "terminal": terminal,
        "driver": driver,
        "crash": crash,
        "review_case": decided,
        "action": action,
    }


class TestContinuedEmploymentDependsOnTheDisciplinaryAction:
    """The driver write is gated by a child row of a different entity."""

    def test_the_suspension_is_issued_with_retraining_pending_and_no_override(
        self, api: ApiClient
    ):
        """A single driver at the terminal cannot strain the staffing ratio.

        PRD: "An accepted action is created in `ISSUED` state with
        `issued_by_user_id` set from the acting operator and a null
        `completed_at`. Its `retraining_status` starts at `PENDING` when a
        `retraining_course_code` was supplied"

        Design: Difficulty/cross_entity_state_dependency/employment_continue_blocked_by_incomplete_retraining
        """
        context = _suspended_driver_with_pending_retraining(api)
        assert_score_2dp(
            context["review_case"]["committee_score"], UNANIMOUS_SCORE, "committee_score"
        )
        assert context["review_case"]["determination"] == DETERMINATION_PREVENTABLE

        action = context["action"]
        assert action["status"] == ACTION_STATE_ISSUED
        assert action["retraining_status"] == RETRAINING_STATUS_PENDING
        assert action["override_flag"] is False
        assert action["completed_at"] is None

        driver = validate_success(api.get_driver(context["driver"]["id"], SAFETY_ADMIN))
        assert driver["status"] == DRIVER_STATUS_SUSPENDED_PENDING_ACTION
        assert driver["tenure_band"] == TENURE_OVER_36_MONTHS

    def test_continuing_employment_is_refused_while_the_course_is_outstanding(
        self, api: ApiClient
    ):
        """Nothing on the driver row blocks the write; the action's status does.

        PRD: "A `CONTINUE` decision is refused while any disciplinary action of
        that driver is still `ISSUED` with `retraining_status` of `PENDING`, on
        the reasoning that a driver cannot be affirmed back into the seat while a
        mandated course is outstanding; the refusal is
        `ERR_RETRAINING_INCOMPLETE`."

        Design: Difficulty/cross_entity_state_dependency/employment_continue_blocked_by_incomplete_retraining
        """
        context = _suspended_driver_with_pending_retraining(api)
        driver_id = context["driver"]["id"]

        validate_error(
            api.decide_employment(
                driver_id,
                factories.employment_decision_payload(
                    decision=EMPLOYMENT_DECISION_CONTINUE,
                    decision_note="retaining after retraining",
                ),
                SAFETY_MANAGER,
            ),
            ApiErrorId.RETRAINING_INCOMPLETE.value,
        )

        unchanged = validate_success(api.get_driver(driver_id, SAFETY_ADMIN))
        assert unchanged["continued_employment_decision"] == EMPLOYMENT_DECISION_PENDING
        assert unchanged["status"] == DRIVER_STATUS_SUSPENDED_PENDING_ACTION

    def test_the_course_cannot_be_signed_off_before_the_period_has_elapsed(
        self, api: ApiClient
    ):
        """The repair itself is gated, so the block cannot be short-circuited.

        PRD: "When the action is a suspension there is an additional temporal
        condition: the out-of-service period must have elapsed, meaning the
        current logical instant must be strictly later than `suspension_end_at`.
        Reinstating a suspended driver early is not permitted and is refused with
        `ERR_SUSPENSION_NOT_ELAPSED`."

        Design: Difficulty/cross_entity_state_dependency/employment_continue_blocked_by_incomplete_retraining
        """
        context = _suspended_driver_with_pending_retraining(api)

        validate_error(
            api.complete_retraining(
                context["action"]["id"],
                factories.complete_retraining_payload(
                    completion_note="attempted early sign-off"
                ),
                SAFETY_ADMIN,
            ),
            ApiErrorId.SUSPENSION_NOT_ELAPSED.value,
        )

        still_issued = validate_success(
            api.get_disciplinary_action(context["action"]["id"], SAFETY_ADMIN)
        )
        assert still_issued["status"] == ACTION_STATE_ISSUED
        assert still_issued["retraining_status"] == RETRAINING_STATUS_PENDING

    def test_completing_the_action_returns_the_driver_and_licenses_the_decision(
        self, api: ApiClient
    ):
        """Repairing the other entity makes the identical request succeed.

        PRD: "On success the action moves `ISSUED → COMPLETED`, its
        `retraining_status` becomes `COMPLETED`, `completed_at` is stamped from
        the clock and its `version` increases by 1. The driver returns to
        `ACTIVE` — from `RETRAINING_REQUIRED` or from `SUSPENDED_PENDING_ACTION`
        alike — provided no other action of that driver is still `ISSUED` with
        retraining pending"

        Design: Difficulty/cross_entity_state_dependency/employment_continue_blocked_by_incomplete_retraining
        """
        context = _suspended_driver_with_pending_retraining(api)
        driver_id = context["driver"]["id"]
        validate_error(
            api.decide_employment(
                driver_id,
                factories.employment_decision_payload(
                    decision=EMPLOYMENT_DECISION_CONTINUE,
                    decision_note="retaining after retraining",
                ),
                SAFETY_MANAGER,
            ),
            ApiErrorId.RETRAINING_INCOMPLETE.value,
        )

        set_clock(api, JUST_AFTER_SUSPENSION)
        completed = validate_success(
            api.complete_retraining(
                context["action"]["id"],
                factories.complete_retraining_payload(
                    completion_note="DDC-8-2026 completed with a passing score"
                ),
                SAFETY_ADMIN,
            )
        )
        assert completed["status"] == ACTION_STATE_COMPLETED
        assert completed["retraining_status"] == RETRAINING_STATUS_COMPLETED
        assert_instants_equal(
            completed["completed_at"], JUST_AFTER_SUSPENSION, "completed_at"
        )
        assert completed["version"] == context["action"]["version"] + 1

        returned = validate_success(api.get_driver(driver_id, SAFETY_ADMIN))
        assert returned["status"] == DRIVER_STATUS_ACTIVE

        terminal = validate_success(api.get_terminal(context["terminal"]["id"], SAFETY_ADMIN))
        assert terminal["suspended_driver_count"] == 0
        assert terminal["active_driver_count"] == 1
        assert terminal["staffing_posture"] == STAFFING_POSTURE_OK

        continued = validate_success(
            api.decide_employment(
                driver_id,
                factories.employment_decision_payload(
                    decision=EMPLOYMENT_DECISION_CONTINUE,
                    decision_note="retaining after retraining",
                ),
                SAFETY_MANAGER,
            )
        )
        assert continued["continued_employment_decision"] == EMPLOYMENT_DECISION_CONTINUE
        assert continued["status"] == DRIVER_STATUS_ACTIVE
        assert_points_1dp(
            continued["preventable_points"], SEVERE_POINTS, "preventable_points"
        )
        assert continued["required_action_tier"] == ACTION_TIER_SUSPENSION
