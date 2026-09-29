"""Two interval resources with deliberately different separation semantics."""

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
    ACTION_STATE_ISSUED,
    ACTION_TIER_SUSPENSION,
    ACTION_TYPE_SUSPENSION,
    BALLOT_DISPOSITION_PREVENTABLE,
    DETERMINATION_PREVENTABLE,
    DRIVER_STATUS_SUSPENDED_PENDING_ACTION,
    EVIDENCE_ELD_LOG,
    EVIDENCE_FORWARD_CAMERA,
    EVIDENCE_POSTURE_PARTIAL,
    EVIDENCE_SCENE_PHOTO,
    EVIDENCE_TELEMATICS,
    PRESERVATION_REQUESTED,
    RETRAINING_STATUS_PENDING,
    ROUTE_CLASS_LINEHAUL,
    ROUTE_CLASS_LOCAL,
    SEVERITY_MODERATE,
    SEVERITY_SEVERE,
    STAFFING_POSTURE_CRITICAL,
    STAFFING_POSTURE_OK,
    TOW_REASON_DISABLING_DAMAGE,
    TOW_REASON_NONE,
)
from test_helpers.fixtures import (
    DISPATCHER,
    SAFETY_ADMIN,
    SAFETY_MANAGER,
    build_crash,
    build_discipline,
    build_driver,
    build_preserved_evidence,
    build_review_case,
    build_statement,
    build_terminal,
    cast_quorum,
    decide_case,
    open_deliberation,
    request_evidence,
)

RETENTION_DEADLINE = "2026-10-31T00:00:00Z"
BASE_WINDOW = ("2026-07-30T13:00:00Z", "2026-07-30T15:00:00Z")
WINDOW_STARTING_AT_THE_BASE_END = ("2026-07-30T15:00:00Z", "2026-07-30T17:00:00Z")
WINDOW_ENDING_AT_THE_BASE_START = ("2026-07-30T11:00:00Z", "2026-07-30T13:00:00Z")
WINDOW_OVERLAPPING_BY_ONE_SECOND = ("2026-07-30T14:59:59Z", "2026-07-30T16:00:00Z")
PHOTO_WINDOW = ("2026-07-30T14:20:00Z", "2026-07-30T14:40:00Z")


def _crash_with_one_telematics_window(api: ApiClient) -> dict:
    """A crash carrying a single REQUESTED telematics capture window."""
    terminal = build_terminal(
        api,
        name="Orrville Terminal",
        terminal_code="ORR01",
        region_code="OH",
        annual_miles_millions=4.0,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-1601",
        full_name="Elias Trueblood",
        cdl_number="OH-CDL-1601",
        hire_date="2011-09-19",
    )
    crash = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-07-30T14:00:00Z",
        notified_at="2026-07-30T14:10:00Z",
        location_text="SR-57 at Smith Rd",
        severity=SEVERITY_MODERATE,
        route_class=ROUTE_CLASS_LOCAL,
        tow_away=False,
        tow_reason=TOW_REASON_NONE,
    )
    base = request_evidence(
        api,
        crash["id"],
        kind=EVIDENCE_TELEMATICS,
        source_device_id="ECM-9001",
        window_start_at=BASE_WINDOW[0],
        window_end_at=BASE_WINDOW[1],
        retention_deadline_at=RETENTION_DEADLINE,
    )
    return {"crash": crash, "base": base}


def _telematics_window(api: ApiClient, crash_id: str, window: tuple):
    return api.create_evidence_item(
        crash_id,
        factories.evidence_payload(
            kind=EVIDENCE_TELEMATICS,
            source_device_id="ECM-9001",
            window_start_at=window[0],
            window_end_at=window[1],
            retention_deadline_at=RETENTION_DEADLINE,
        ),
        DISPATCHER,
    )


class TestEvidenceCaptureWindows:
    """Pure half-open intervals: adjacency is legal, intersection is not."""

    def test_a_window_that_merely_touches_the_existing_one_is_accepted(
        self, api: ApiClient
    ):
        """Both adjacency directions are accepted with no buffer at all.

        PRD: "Overlap is judged on half-open intervals that include their start
        instant and exclude their end instant, so two windows that merely touch at
        an instant, one ending exactly where the next begins, are accepted as
        adjacent rather than rejected as overlapping."

        Design: Difficulty/resource_temporal_overlap/evidence_window_touching_allowed_overlap_rejected
        """
        context = _crash_with_one_telematics_window(api)
        assert context["base"]["preservation_state"] == PRESERVATION_REQUESTED

        after = validate_success(
            _telematics_window(
                api, context["crash"]["id"], WINDOW_STARTING_AT_THE_BASE_END
            ),
            201,
        )
        assert_instants_equal(
            after["window_start_at"], WINDOW_STARTING_AT_THE_BASE_END[0], "window_start_at"
        )

        before = validate_success(
            _telematics_window(
                api, context["crash"]["id"], WINDOW_ENDING_AT_THE_BASE_START
            ),
            201,
        )
        assert_instants_equal(
            before["window_end_at"], WINDOW_ENDING_AT_THE_BASE_START[1], "window_end_at"
        )
        assert len({context["base"]["id"], after["id"], before["id"]}) == 3

    def test_a_one_second_intersection_is_refused_and_creates_no_row(
        self, api: ApiClient
    ):
        """A genuine intersection of one second is the whole difference.

        PRD: "for the three kinds that participate in the required-evidence sets
        — `TELEMATICS_SNAPSHOT`, `FORWARD_CAMERA` and `ELD_LOG` — the requested
        window may not overlap the window of an existing, not-yet-purged item of
        the same kind on the same crash."

        Design: Difficulty/resource_temporal_overlap/evidence_window_touching_allowed_overlap_rejected
        """
        context = _crash_with_one_telematics_window(api)
        validate_success(
            _telematics_window(api, context["crash"]["id"], WINDOW_STARTING_AT_THE_BASE_END),
            201,
        )

        validate_error(
            _telematics_window(
                api, context["crash"]["id"], WINDOW_OVERLAPPING_BY_ONE_SECOND
            ),
            ApiErrorId.EVIDENCE_WINDOW_CONFLICT.value,
        )

        rows, meta = validate_paginated(
            api.list_crash_evidence_items(
                context["crash"]["id"], SAFETY_ADMIN, {"kind": EVIDENCE_TELEMATICS}
            )
        )
        assert meta["total_count"] == 2
        starts = sorted(row["window_start_at"] for row in rows)
        assert_instants_equal(starts[0], BASE_WINDOW[0], "first window_start_at")
        assert_instants_equal(
            starts[1], WINDOW_STARTING_AT_THE_BASE_END[0], "second window_start_at"
        )

    def test_the_conflict_rule_is_scoped_to_one_kind_on_one_crash(
        self, api: ApiClient
    ):
        """The same window is legal for another kind, and photos are exempt.

        PRD: "`DRIVER_FACING_CAMERA` and `SCENE_PHOTO` items are not subject to
        the duplication test."

        Design: Difficulty/resource_temporal_overlap/evidence_window_touching_allowed_overlap_rejected
        """
        context = _crash_with_one_telematics_window(api)
        crash_id = context["crash"]["id"]

        camera = validate_success(
            api.create_evidence_item(
                crash_id,
                factories.evidence_payload(
                    kind=EVIDENCE_FORWARD_CAMERA,
                    source_device_id="CAM-9001",
                    window_start_at=BASE_WINDOW[0],
                    window_end_at=BASE_WINDOW[1],
                    retention_deadline_at=RETENTION_DEADLINE,
                ),
                DISPATCHER,
            ),
            201,
        )
        photos = []
        for device in ("PHONE-114", "PHONE-115"):
            photos.append(
                validate_success(
                    api.create_evidence_item(
                        crash_id,
                        factories.evidence_payload(
                            kind=EVIDENCE_SCENE_PHOTO,
                            source_device_id=device,
                            window_start_at=PHOTO_WINDOW[0],
                            window_end_at=PHOTO_WINDOW[1],
                            retention_deadline_at=RETENTION_DEADLINE,
                        ),
                        DISPATCHER,
                    ),
                    201,
                )
            )
        assert photos[0]["id"] != photos[1]["id"]
        assert camera["kind"] == EVIDENCE_FORWARD_CAMERA

        _rows, meta = validate_paginated(
            api.list_crash_evidence_items(crash_id, SAFETY_ADMIN)
        )
        assert meta["total_count"] == 4

        crash = validate_success(api.get_crash(crash_id, SAFETY_ADMIN))
        assert crash["evidence_posture"] == EVIDENCE_POSTURE_PARTIAL


PORTSMOUTH_WINDOW = {
    "window_start_at": "2026-07-30T05:00:00Z",
    "window_end_at": "2026-07-30T07:00:00Z",
    "retention_deadline_at": RETENTION_DEADLINE,
}

FIRST_SUSPENSION = ("2026-08-02T00:00:00Z", "2026-08-09T00:00:00Z")
TOUCHING_SUSPENSION = ("2026-08-09T00:00:00Z", "2026-08-16T00:00:00Z")
ONE_SECOND_SHORT_SUSPENSION = ("2026-08-09T23:59:59Z", "2026-08-16T23:59:59Z")
EXACTLY_ONE_BUFFER_LATER = ("2026-08-10T00:00:00Z", "2026-08-17T00:00:00Z")

OVERRIDE_REASON = "single-driver terminal, covered by an agency driver"
UNANIMOUS_FOUR_SCORE = 4.00
SEVERE_POINTS = 8.0


def _driver_serving_one_suspension(api: ApiClient) -> dict:
    """A single-driver terminal whose only driver is already out of service."""
    terminal = build_terminal(
        api,
        name="Portsmouth Terminal",
        terminal_code="POR01",
        region_code="OH",
        annual_miles_millions=4.0,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-1701",
        full_name="Fiona Delacroix",
        cdl_number="OH-CDL-1701",
        hire_date="2011-09-19",
    )
    crash = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-07-30T06:00:00Z",
        notified_at="2026-07-30T06:25:00Z",
        location_text="US-23 at Lucasville",
        severity=SEVERITY_SEVERE,
        route_class=ROUTE_CLASS_LINEHAUL,
        tow_away=True,
        tow_reason=TOW_REASON_DISABLING_DAMAGE,
        injury_transported_count=1,
        mechanical_factor=True,
    )
    for kind, device in (
        (EVIDENCE_TELEMATICS, "ECM-9301"),
        (EVIDENCE_FORWARD_CAMERA, "CAM-9301"),
        (EVIDENCE_ELD_LOG, "ELD-9301"),
    ):
        build_preserved_evidence(
            api, crash["id"], kind=kind, source_device_id=device, **PORTSMOUTH_WINDOW
        )
    build_statement(
        api,
        crash["id"],
        driver["id"],
        narrative="I drifted onto the shoulder and over-corrected into the guardrail.",
        conditions_note=None,
    )
    case = build_review_case(
        api, crash["id"], committee_name="Portsmouth Safety Review Committee"
    )
    opened = open_deliberation(api, case["id"])
    cast_quorum(
        api,
        opened,
        vote=BALLOT_DISPOSITION_PREVENTABLE,
        scores=factories.uniform_criterion_scores(4),
    )
    decided = decide_case(api, case["id"])
    first = build_discipline(
        api,
        driver["id"],
        crash["id"],
        action_type=ACTION_TYPE_SUSPENSION,
        action_note="First out-of-service period",
        suspension_start_at=FIRST_SUSPENSION[0],
        suspension_end_at=FIRST_SUSPENSION[1],
        retraining_course_code="DDC-9-2026",
    )
    return {
        "terminal": terminal,
        "driver": driver,
        "crash": crash,
        "review_case": decided,
        "first_action": first,
    }


def _second_suspension(api: ApiClient, context: dict, window: tuple, note: str):
    return api.create_disciplinary_action(
        factories.disciplinary_action_payload(
            context["driver"]["id"],
            context["crash"]["id"],
            action_type=ACTION_TYPE_SUSPENSION,
            action_note=note,
            suspension_start_at=window[0],
            suspension_end_at=window[1],
            retraining_course_code="DDC-9-2026",
            override_reason=OVERRIDE_REASON,
        ),
        SAFETY_MANAGER,
    )


class TestSuspensionOutOfServiceWindows:
    """The same half-open comparison, but each interval is widened by 24 hours."""

    def test_the_first_suspension_needed_no_override_and_turns_the_posture(
        self, api: ApiClient
    ):
        """One suspended driver of one active driver is exactly the ratio bound.

        PRD: "Because a suspended driver sits on both sides of the division, one
        suspended driver out of two non-terminated drivers is exactly one half and
        lands on `CRITICAL` at the boundary"

        Design: Difficulty/resource_temporal_overlap/suspension_window_buffer_rejects_adjacent
        """
        context = _driver_serving_one_suspension(api)
        assert_score_2dp(
            context["review_case"]["committee_score"],
            UNANIMOUS_FOUR_SCORE,
            "committee_score",
        )
        assert context["review_case"]["determination"] == DETERMINATION_PREVENTABLE
        assert context["first_action"]["override_flag"] is False

        driver = validate_success(api.get_driver(context["driver"]["id"], SAFETY_ADMIN))
        assert_points_1dp(driver["preventable_points"], SEVERE_POINTS, "preventable_points")
        assert driver["required_action_tier"] == ACTION_TIER_SUSPENSION

        terminal = validate_success(api.get_terminal(context["terminal"]["id"], SAFETY_ADMIN))
        assert terminal["suspended_driver_count"] == 1
        assert terminal["active_driver_count"] == 1
        assert terminal["staffing_posture"] == STAFFING_POSTURE_CRITICAL
        assert terminal["staffing_posture"] != STAFFING_POSTURE_OK

    def test_a_back_to_back_window_is_refused_because_of_the_separation(
        self, api: ApiClient
    ):
        """Touching is enough for evidence windows but not for a driver.

        PRD: "The windows are compared as half-open intervals including their
        start and excluding their end, and each existing interval is then widened
        by a mandatory separation of 24 hours on either side before the
        comparison; a new window that overlaps an existing one, or that falls
        inside that one-day separation, is refused with
        `ERR_SUSPENSION_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/suspension_window_buffer_rejects_adjacent
        """
        context = _driver_serving_one_suspension(api)

        body = validate_error(
            _second_suspension(
                api, context, TOUCHING_SUSPENSION, "Second period, back to back"
            ),
            ApiErrorId.SUSPENSION_WINDOW_CONFLICT.value,
        )
        assert body["error_id"] != ApiErrorId.STAFFING_OVERRIDE_REQUIRED.value

    def test_one_second_short_of_the_separation_is_still_refused(self, api: ApiClient):
        """The buffer is measured to the second, like every other boundary here.

        PRD: "each existing interval is then widened by a mandatory separation of
        24 hours on either side before the comparison; a new window that overlaps
        an existing one, or that falls inside that one-day separation, is refused
        with `ERR_SUSPENSION_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/suspension_window_buffer_rejects_adjacent
        """
        context = _driver_serving_one_suspension(api)

        body = validate_error(
            _second_suspension(
                api,
                context,
                ONE_SECOND_SHORT_SUSPENSION,
                "Second period, one second short of the buffer",
            ),
            ApiErrorId.SUSPENSION_WINDOW_CONFLICT.value,
        )
        assert body["error_id"] != ApiErrorId.STAFFING_OVERRIDE_REQUIRED.value

        rows, meta = validate_paginated(
            api.list_disciplinary_actions(
                SAFETY_ADMIN, {"driver_id": context["driver"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == context["first_action"]["id"]

    def test_a_start_exactly_one_buffer_after_the_previous_end_is_accepted(
        self, api: ApiClient
    ):
        """The separation is satisfied at exactly 24 hours, and the driver holds.

        PRD: "Because consecutive out-of-service periods may legitimately stack on
        the same driver, a driver already sitting in `SUSPENDED_PENDING_ACTION`
        may receive an additional suspension, and that second window is checked
        against the first."

        Design: Difficulty/resource_temporal_overlap/suspension_window_buffer_rejects_adjacent
        """
        context = _driver_serving_one_suspension(api)

        second = validate_success(
            _second_suspension(
                api,
                context,
                EXACTLY_ONE_BUFFER_LATER,
                "Second period, exactly one buffer later",
            ),
            201,
        )
        assert second["status"] == ACTION_STATE_ISSUED
        assert second["override_flag"] is True
        assert second["retraining_status"] == RETRAINING_STATUS_PENDING
        assert_instants_equal(
            second["suspension_start_at"], EXACTLY_ONE_BUFFER_LATER[0], "suspension_start_at"
        )

        driver = validate_success(api.get_driver(context["driver"]["id"], SAFETY_ADMIN))
        assert driver["status"] == DRIVER_STATUS_SUSPENDED_PENDING_ACTION

        terminal = validate_success(api.get_terminal(context["terminal"]["id"], SAFETY_ADMIN))
        assert terminal["suspended_driver_count"] == 1
        assert terminal["active_driver_count"] == 1
        assert terminal["staffing_posture"] == STAFFING_POSTURE_CRITICAL

        rows, meta = validate_paginated(
            api.list_disciplinary_actions(
                SAFETY_ADMIN, {"driver_id": context["driver"]["id"]}
            )
        )
        assert meta["total_count"] == 2
        assert all(row["status"] == ACTION_STATE_ISSUED for row in rows)
        assert all(row["retraining_status"] == RETRAINING_STATUS_PENDING for row in rows)
