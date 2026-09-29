"""Declared transitions, their initial states and the guards that precede them.

Each probe here drives one declared state dimension across one declared edge and
then reads back both the row that moved and the rows the move was supposed to
reach, so that a transition which fires without its side effects is as visible as
one that does not fire at all.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_cents,
    assert_instants_equal,
    assert_multiplier,
    assert_points_1dp,
    assert_rate,
    assert_score_2dp,
)
from test_helpers.constants import (
    ACTION_STATE_ISSUED,
    ACTION_TIER_SUSPENSION,
    ACTION_TIER_TERMINATION_REVIEW,
    ACTION_TYPE_COACHING,
    ACTION_TYPE_SUSPENSION,
    ACTION_TYPE_TERMINATION_RECOMMENDATION,
    BALLOT_DISPOSITION_PREVENTABLE,
    CLAIM_HANDLING_CLOSED,
    CLAIM_HANDLING_SETUP,
    CLAIMANT_TYPE_PROPERTY,
    CLOCK_EPOCH,
    DECISION_BASIS_NOT_APPLICABLE,
    DECISION_BASIS_WEIGHTED_CRITERIA,
    DEMAND_STATE_DEMANDED,
    DETERMINATION_PENDING,
    DETERMINATION_PREVENTABLE,
    DRIVER_STATUS_ACTIVE,
    DRIVER_STATUS_SUSPENDED_PENDING_ACTION,
    DRIVER_STATUS_TERMINATED,
    EMPLOYMENT_DECISION_CONTINUE,
    EMPLOYMENT_DECISION_PENDING,
    EMPLOYMENT_DECISION_SEPARATE,
    EVIDENCE_FORWARD_CAMERA,
    EVIDENCE_POSTURE_COMPLETE,
    EVIDENCE_POSTURE_COMPROMISED,
    EVIDENCE_POSTURE_PARTIAL,
    EVIDENCE_SCENE_PHOTO,
    EVIDENCE_TELEMATICS,
    OPERATOR_IDS,
    PRESERVATION_PRESERVED,
    PRESERVATION_PURGED_BEFORE_HOLD,
    PRESERVATION_RELEASED,
    PRESERVATION_REQUESTED,
    PREVENTABILITY_REPORTED,
    PREVENTABILITY_UNDER_REVIEW,
    REPORTING_STATUS_NOT_REQUIRED,
    REPORTING_STATUS_PENDING_FILING,
    RESERVE_BASIS_PROVISIONAL_REFRESH,
    RESERVE_STATUS_FINAL,
    RESERVE_STATUS_PROVISIONAL,
    REVIEW_STATE_DELIBERATION,
    REVIEW_STATE_DRAFT,
    RETRAINING_STATUS_NOT_REQUIRED,
    RETRAINING_STATUS_PENDING,
    RISK_TIER_STANDARD,
    ROUND_OUTCOME_OPEN,
    ROUTE_CLASS_LINEHAUL,
    ROUTE_CLASS_LOCAL,
    ROUTE_CLASS_REGIONAL,
    SEVERITY_CATASTROPHIC,
    SEVERITY_MINOR,
    SEVERITY_MODERATE,
    SEVERITY_SEVERE,
    STAFFING_POSTURE_CRITICAL,
    STAFFING_POSTURE_OK,
    SUBROGATION_RESOLUTION_DENIED,
    SUBROGATION_STATE_DRAFT,
    TOW_REASON_DISABLING_DAMAGE,
    TOW_REASON_NONE,
)
from test_helpers.fixtures import (
    CLAIMS_ADJUSTER,
    CLAIMS_MANAGER,
    COMMITTEE_ONE,
    DISPATCHER,
    SAFETY_ADMIN,
    SAFETY_MANAGER,
    build_case_in_deliberation,
    build_claim,
    build_crash,
    build_driver,
    build_review_case,
    build_statement,
    build_subrogation_demand,
    build_terminal,
    cast_quorum,
    decide_case,
    preserve_evidence,
    purge_evidence,
    request_evidence,
    set_clock,
)
from test_helpers.test_users import make_driver_headers


FOSTORIA_WINDOW = {
    "window_start_at": "2026-07-31T08:00:00Z",
    "window_end_at": "2026-07-31T10:00:00Z",
    "retention_deadline_at": "2026-10-31T00:00:00Z",
}
FOSTORIA_URI = "s3://evidence/2923fos/ecm-3201.json"
FOSTORIA_HASH = "9b9b8a8a7c7c6d6d5e5e4f4f3a3a2b2b"


def _minor_crash_with_one_unpreserved_snapshot(api: ApiClient) -> dict:
    """A MINOR crash whose only required kind is requested but not yet held."""
    terminal = build_terminal(
        api,
        name="Fostoria Terminal",
        terminal_code="FOS01",
        region_code="OH",
        annual_miles_millions=2.0,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-3201",
        full_name="Ulla Braithwaite",
        cdl_number="OH-CDL-3201",
        hire_date="2011-07-07",
    )
    crash = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-07-31T09:00:00Z",
        notified_at="2026-07-31T09:20:00Z",
        location_text="SR-12 at Countyline St",
        severity=SEVERITY_MINOR,
        route_class=ROUTE_CLASS_LOCAL,
        tow_away=False,
        tow_reason=TOW_REASON_NONE,
    )
    item = request_evidence(
        api,
        crash["id"],
        kind=EVIDENCE_TELEMATICS,
        source_device_id="ECM-3201",
        **FOSTORIA_WINDOW,
    )
    return {"terminal": terminal, "driver": driver, "crash": crash, "item": item}


class TestPreservingAnArtifactPlacesItUnderHold:
    """The second custody stage moves the item and re-derives the crash posture."""

    def test_the_item_moves_to_preserved_and_takes_its_stamps_from_the_clock(
        self, api: ApiClient
    ):
        """The URI and hash are recorded and preserved_at is the logical instant.

        PRD: "On success the item moves `REQUESTED → PRESERVED`, the URI and hash
        are recorded, `preserved_at` is stamped from the logical clock, the
        crash's evidence posture is re-derived, and the item's `version`
        increases by 1."

        Design: Corner/state_machines/evidence_preserve_moves_requested_to_preserved_and_completes_posture
        """
        context = _minor_crash_with_one_unpreserved_snapshot(api)
        item = context["item"]
        assert item["preservation_state"] == PRESERVATION_REQUESTED
        assert item["preserved_copy_uri"] is None
        assert item["preserved_at"] is None
        assert item["purge_reason"] is None

        response = api.preserve_evidence_item(
            item["id"],
            factories.preserve_payload(
                preserved_copy_uri=FOSTORIA_URI, evidence_hash=FOSTORIA_HASH
            ),
            DISPATCHER,
        )
        preserved = validate_success(response, 200)

        assert preserved["preservation_state"] == PRESERVATION_PRESERVED
        assert preserved["preserved_copy_uri"] == FOSTORIA_URI
        assert preserved["evidence_hash"] == FOSTORIA_HASH
        assert_instants_equal(preserved["preserved_at"], CLOCK_EPOCH, "preserved_at")
        assert preserved["purge_reason"] is None
        assert preserved["version"] == item["version"] + 1

    def test_the_posture_completes_without_the_crash_row_being_rewritten(
        self, api: ApiClient
    ):
        """One preserved bracketing snapshot satisfies a MINOR crash outright.

        PRD: "a `MINOR` crash requires a `TELEMATICS_SNAPSHOT` alone ... A
        required kind counts as satisfied only by an item that is currently in
        `PRESERVED` state *and* whose data window brackets the crash instant" and
        the posture "is recomputed from scratch on every read of the crash".

        Design: Corner/state_machines/evidence_preserve_moves_requested_to_preserved_and_completes_posture
        """
        context = _minor_crash_with_one_unpreserved_snapshot(api)
        before = validate_success(api.get_crash(context["crash"]["id"], SAFETY_MANAGER))
        assert before["evidence_posture"] == EVIDENCE_POSTURE_PARTIAL

        preserve_evidence(
            api,
            context["item"]["id"],
            preserved_copy_uri=FOSTORIA_URI,
            evidence_hash=FOSTORIA_HASH,
        )

        after = validate_success(api.get_crash(context["crash"]["id"], SAFETY_MANAGER))
        assert after["evidence_posture"] == EVIDENCE_POSTURE_COMPLETE
        assert after["version"] == before["version"]
        assert_instants_equal(after["updated_at"], before["updated_at"], "updated_at")


GREENVILLE_CRASH = dict(
    occurred_at="2026-07-31T14:00:00Z",
    notified_at="2026-07-31T14:30:00Z",
    location_text="US-127 at Beamsville Rd",
    severity=SEVERITY_MODERATE,
    route_class=ROUTE_CLASS_REGIONAL,
    tow_away=False,
    tow_reason=TOW_REASON_NONE,
    injury_transported_count=1,
    third_party_at_fault=True,
)


def _greenville_fleet(api: ApiClient) -> dict:
    """One terminal and one freshly hired driver, nothing else."""
    terminal = build_terminal(
        api,
        name="Greenville Terminal",
        terminal_code="GRE01",
        region_code="OH",
        annual_miles_millions=2.0,
    )
    driver = validate_success(
        api.create_driver(
            factories.driver_payload(
                terminal["id"],
                employee_code="D-3301",
                full_name="Vesna Kirilov",
                cdl_number="OH-CDL-3301",
                hire_date="2014-02-18",
            ),
            SAFETY_ADMIN,
        ),
        201,
    )
    return {"terminal": terminal, "driver": driver}


class TestEveryDimensionStartsInItsDeclaredInitialState:
    """Ten state dimensions, each observed on the call that mints its row."""

    def test_the_safety_side_dimensions_start_reported_requested_and_draft(
        self, api: ApiClient
    ):
        """Driver, crash, evidence item and review case each open where declared.

        PRD: "A new driver starts with `status` of `ACTIVE`, a
        `continued_employment_decision` of `PENDING` and a null `decision_note`."
        — "a new crash starts with `preventability_status` of `REPORTED`, an
        `evidence_posture` of `PARTIAL` and `appeals_exhausted` false." — "A
        requested item starts in `preservation_state` `REQUESTED`" — "Opening a
        case creates it in `DRAFT` with `determination` of `PENDING`,
        `decision_basis` of `NOT_APPLICABLE`, a null `committee_score`,
        `appeal_round` at 0, `next_vote_sequence` at 1"

        Design: Corner/state_machines/initial_states_of_every_entity_dimension_on_creation
        """
        context = _greenville_fleet(api)
        driver = context["driver"]
        assert driver["status"] == DRIVER_STATUS_ACTIVE
        assert driver["continued_employment_decision"] == EMPLOYMENT_DECISION_PENDING
        assert driver["decision_note"] is None

        crash = build_crash(
            api, driver["id"], context["terminal"]["id"], **GREENVILLE_CRASH
        )
        assert crash["preventability_status"] == PREVENTABILITY_REPORTED
        assert crash["reporting_status"] == REPORTING_STATUS_PENDING_FILING
        assert crash["dot_recordable"] is True
        assert crash["appeals_exhausted"] is False
        assert crash["evidence_posture"] == EVIDENCE_POSTURE_PARTIAL

        item = request_evidence(
            api,
            crash["id"],
            kind=EVIDENCE_TELEMATICS,
            source_device_id="ECM-3301",
            window_start_at="2026-07-31T13:00:00Z",
            window_end_at="2026-07-31T15:00:00Z",
            retention_deadline_at="2026-10-31T00:00:00Z",
        )
        assert item["preservation_state"] == PRESERVATION_REQUESTED

        case = build_review_case(
            api,
            crash["id"],
            committee_name="Greenville Safety Review Committee",
            statement_waiver_reason="driver hospitalised, statement waived by counsel",
        )
        assert case["status"] == REVIEW_STATE_DRAFT
        assert case["determination"] == DETERMINATION_PENDING
        assert case["decision_basis"] == DECISION_BASIS_NOT_APPLICABLE
        assert case["committee_score"] is None
        assert case["appeal_round"] == 0
        assert case["next_vote_sequence"] == 1
        assert case["active_vote_count"] == 0

        reread = validate_success(api.get_crash(crash["id"], SAFETY_MANAGER))
        assert reread["preventability_status"] == PREVENTABILITY_UNDER_REVIEW

    def test_the_claims_side_dimensions_start_setup_demanded_open_and_draft(
        self, api: ApiClient
    ):
        """The claim's two axes, the demand, the round and the recovery file.

        PRD: "A claim opens with `handling_status` of `SETUP` and `reserve_status`
        of `PROVISIONAL`" — "The demand is created in `DEMANDED` state" — a new
        round has an "`outcome` [of] `OPEN` ... with a null
        `claimant_counter_cents`, a null `gap_cents` and a null `countered_at`" —
        "The record starts in `DRAFT` with `recoverable_base_cents`,
        `max_recoverable_cents`, `recovered_amount_cents`, `resolution_note` and
        `resolved_at` all null"

        Design: Corner/state_machines/initial_states_of_every_entity_dimension_on_creation
        """
        context = _greenville_fleet(api)
        crash = build_crash(
            api, context["driver"]["id"], context["terminal"]["id"], **GREENVILLE_CRASH
        )

        claim = validate_success(
            api.create_claim(
                factories.claim_payload(crash["id"], claimant_notice_date="2026-08-01"),
                CLAIMS_ADJUSTER,
            ),
            201,
        )
        assert claim["handling_status"] == CLAIM_HANDLING_SETUP
        assert claim["reserve_status"] == RESERVE_STATUS_PROVISIONAL

        demand = validate_success(
            api.create_demand(
                claim["id"],
                factories.demand_payload(
                    claimant_name="Darke County Farm Bureau",
                    claimant_type=CLAIMANT_TYPE_PROPERTY,
                    demand_amount_cents=2_000_000,
                    represented_by_counsel=False,
                    demand_received_at=CLOCK_EPOCH,
                ),
                CLAIMS_ADJUSTER,
            ),
            201,
        )
        assert demand["status"] == DEMAND_STATE_DEMANDED

        round_row = validate_success(
            api.create_offer(demand["id"], factories.offer_payload(900_000), CLAIMS_ADJUSTER),
            201,
        )
        assert round_row["outcome"] == ROUND_OUTCOME_OPEN
        assert round_row["round_index"] == 1
        assert round_row["claimant_counter_cents"] is None
        assert round_row["gap_cents"] is None
        assert round_row["countered_at"] is None
        assert_cents(round_row["carrier_offer_cents"], 900_000, "carrier_offer_cents")

        recovery = validate_success(
            api.create_subrogation_demand(
                claim["id"],
                factories.subrogation_demand_payload(
                    third_party_name="Beamsville Grain LLC",
                    at_fault_percentage=40,
                    basis_note="third-party ran the stop sign",
                ),
                CLAIMS_MANAGER,
            ),
            201,
        )
        assert recovery["status"] == SUBROGATION_STATE_DRAFT
        assert recovery["recoverable_base_cents"] is None
        assert recovery["max_recoverable_cents"] is None
        assert recovery["recovered_amount_cents"] is None
        assert recovery["resolution_note"] is None
        assert recovery["resolved_at"] is None


HILLSBORO_OCCURRED_AT = "2026-07-31T18:00:00Z"
HILLSBORO_KEEP_URI = "s3://evidence/2923hil/ecm-3401.json"
HILLSBORO_KEEP_HASH = "1c1c2d2d3e3e4f4f5a5a6b6b7c7c8d8d"
HILLSBORO_EXPIRING_URI = "s3://evidence/2923hil/cam-3401.mp4"
HILLSBORO_EXPIRING_HASH = "2d2d3e3e4f4f5a5a6b6b7c7c8d8d9e9e"
EXPIRING_RETENTION_DEADLINE_AT = "2026-08-05T00:00:00Z"
ONE_SECOND_PAST_THE_DEADLINE = "2026-08-05T00:00:01Z"


def _crash_with_two_unpreserved_items(api: ApiClient) -> dict:
    """A MINOR crash carrying two requested items, one of them short-dated."""
    terminal = build_terminal(
        api,
        name="Hillsboro Terminal",
        terminal_code="HIL02",
        region_code="OH",
        annual_miles_millions=2.0,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-3401",
        full_name="Wren Alcott",
        cdl_number="OH-CDL-3401",
        hire_date="2019-04-01",
    )
    crash = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at=HILLSBORO_OCCURRED_AT,
        notified_at="2026-07-31T18:10:00Z",
        location_text="SR-73 at Careytown Rd",
        severity=SEVERITY_MINOR,
        route_class=ROUTE_CLASS_REGIONAL,
        tow_away=False,
        tow_reason=TOW_REASON_NONE,
    )
    keep = request_evidence(
        api,
        crash["id"],
        kind=EVIDENCE_TELEMATICS,
        source_device_id="ECM-3401",
        window_start_at="2026-07-31T17:00:00Z",
        window_end_at="2026-07-31T19:00:00Z",
        retention_deadline_at="2026-10-31T00:00:00Z",
    )
    expiring = request_evidence(
        api,
        crash["id"],
        kind=EVIDENCE_FORWARD_CAMERA,
        source_device_id="CAM-3401",
        window_start_at="2026-07-31T17:30:00Z",
        window_end_at="2026-07-31T18:30:00Z",
        retention_deadline_at=EXPIRING_RETENTION_DEADLINE_AT,
    )
    return {
        "terminal": terminal,
        "driver": driver,
        "crash": crash,
        "keep": keep,
        "expiring": expiring,
    }


class TestTheReviewPathPreconditionsAreEnforcedOneAtATime:
    """Each gate on the road to deliberation refuses for its own reason."""

    def test_an_unattested_statement_is_refused_and_leaves_the_gate_shut(
        self, api: ApiClient
    ):
        """The refused statement does not exist, so the case still lacks one.

        PRD: "Attestation is not optional in substance: a statement submitted
        with `attested` false is refused with `ERR_STATEMENT_NOT_ATTESTED`." —
        "unless a driver statement already exists for the crash, a
        `statement_waiver_reason` must be supplied ... and a request offering
        neither is refused with `ERR_DRIVER_STATEMENT_REQUIRED`."

        Design: Corner/state_machines/review_case_preconditions_gate_statement_evidence_and_retention
        """
        context = _crash_with_two_unpreserved_items(api)
        crash_id = context["crash"]["id"]

        validate_error(
            api.create_driver_statement(
                crash_id,
                factories.driver_statement_payload(
                    narrative="I would rather not swear to this yet.",
                    attested=False,
                    conditions_note=None,
                ),
                make_driver_headers(context["driver"]["id"]),
            ),
            ApiErrorId.STATEMENT_NOT_ATTESTED.value,
            409,
        )

        rows, meta = validate_paginated(api.list_driver_statements(crash_id, SAFETY_MANAGER))
        assert rows == []
        assert meta["total_count"] == 0

        validate_error(
            api.create_review_case(
                factories.review_case_payload(
                    crash_id, committee_name="Hillsboro Safety Review Committee"
                ),
                SAFETY_MANAGER,
            ),
            ApiErrorId.DRIVER_STATEMENT_REQUIRED.value,
            409,
        )

    def test_custody_gates_deliberation_until_one_item_is_actually_preserved(
        self, api: ApiClient
    ):
        """An attested statement opens the case; only a hold opens balloting.

        PRD: "Seating the committee and opening balloting moves the case
        `DRAFT → DELIBERATION`, and it is gated on custody: at least one evidence
        item on the case's crash must already be in `PRESERVED` state, or the
        request is refused with `ERR_NO_PRESERVED_EVIDENCE`."

        Design: Corner/state_machines/review_case_preconditions_gate_statement_evidence_and_retention
        """
        context = _crash_with_two_unpreserved_items(api)
        crash_id = context["crash"]["id"]

        statement = build_statement(
            api,
            crash_id,
            context["driver"]["id"],
            narrative="I clipped a bollard while backing into the dock.",
            conditions_note="wet pavement, dusk",
            attested=True,
        )
        assert statement["submitted_by_driver_id"] == context["driver"]["id"]
        assert_instants_equal(statement["submitted_at"], CLOCK_EPOCH, "submitted_at")

        case = validate_success(
            api.create_review_case(
                factories.review_case_payload(
                    crash_id, committee_name="Hillsboro Safety Review Committee"
                ),
                SAFETY_MANAGER,
            ),
            201,
        )
        assert case["statement_waiver_reason"] is None
        assert case["status"] == REVIEW_STATE_DRAFT

        validate_error(
            api.open_deliberation(case["id"], headers=SAFETY_MANAGER),
            ApiErrorId.NO_PRESERVED_EVIDENCE.value,
            409,
        )

        preserve_evidence(
            api,
            context["keep"]["id"],
            preserved_copy_uri=HILLSBORO_KEEP_URI,
            evidence_hash=HILLSBORO_KEEP_HASH,
        )
        opened = validate_success(api.open_deliberation(case["id"], headers=SAFETY_MANAGER))
        assert opened["status"] == REVIEW_STATE_DELIBERATION

    def test_preserving_one_second_past_the_retention_deadline_is_refused(
        self, api: ApiClient
    ):
        """The deadline is inclusive, so the second after it is already too late.

        PRD: "The retention deadline must not yet have passed — the current
        instant must be no later than `retention_deadline_at`, and preserving
        after that instant is refused with `ERR_RETENTION_DEADLINE_PASSED`."

        Design: Corner/state_machines/review_case_preconditions_gate_statement_evidence_and_retention
        """
        context = _crash_with_two_unpreserved_items(api)
        expiring_id = context["expiring"]["id"]
        set_clock(api, ONE_SECOND_PAST_THE_DEADLINE)

        validate_error(
            api.preserve_evidence_item(
                expiring_id,
                factories.preserve_payload(
                    preserved_copy_uri=HILLSBORO_EXPIRING_URI,
                    evidence_hash=HILLSBORO_EXPIRING_HASH,
                ),
                SAFETY_ADMIN,
            ),
            ApiErrorId.RETENTION_DEADLINE_PASSED.value,
            409,
        )

        unchanged = validate_success(api.get_evidence_item(expiring_id, SAFETY_ADMIN))
        assert unchanged["preservation_state"] == PRESERVATION_REQUESTED
        assert unchanged["preserved_at"] is None
        assert unchanged["preserved_copy_uri"] is None
        assert unchanged["version"] == context["expiring"]["version"]


IRONTON_WINDOW = {
    "window_start_at": "2026-07-28T09:00:00Z",
    "window_end_at": "2026-07-28T11:00:00Z",
    "retention_deadline_at": "2026-10-31T00:00:00Z",
}
IRONTON_COMMITTEE_SCORE = 3.00
IRONTON_SEVERE_POINTS = 8.0
IRONTON_CRASH_RATE = 0.500
SUSPENSION_START_AT = "2026-08-02T00:00:00Z"
SUSPENSION_END_AT = "2026-08-09T00:00:00Z"


def _decided_preventable_crash_at_a_two_driver_terminal(api: ApiClient) -> dict:
    """A spoliated SEVERE crash decided preventable, on a terminal of two."""
    terminal = build_terminal(
        api,
        name="Ironton Terminal",
        terminal_code="IRN02",
        region_code="OH",
        annual_miles_millions=2.0,
    )
    driver_a = build_driver(
        api,
        terminal["id"],
        employee_code="D-3501",
        full_name="Xavier Ondrusek",
        cdl_number="OH-CDL-3501",
        hire_date="2011-03-03",
    )
    build_driver(
        api,
        terminal["id"],
        employee_code="D-3502",
        full_name="Yusuf Halloran",
        cdl_number="OH-CDL-3502",
        hire_date="2011-03-03",
    )
    crash = build_crash(
        api,
        driver_a["id"],
        terminal["id"],
        occurred_at="2026-07-28T10:00:00Z",
        notified_at="2026-07-28T10:30:00Z",
        location_text="US-52 at Storms Creek",
        severity=SEVERITY_SEVERE,
        route_class=ROUTE_CLASS_LINEHAUL,
        tow_away=False,
        tow_reason=TOW_REASON_NONE,
    )
    photo = request_evidence(
        api,
        crash["id"],
        kind=EVIDENCE_SCENE_PHOTO,
        source_device_id="PHONE-3501",
        **IRONTON_WINDOW,
    )
    preserve_evidence(
        api,
        photo["id"],
        preserved_copy_uri="s3://evidence/2923irn/scene-3501.jpg",
        evidence_hash="3e3e4f4f5a5a6b6b7c7c8d8d9e9e0f0f",
    )
    snapshot = request_evidence(
        api,
        crash["id"],
        kind=EVIDENCE_TELEMATICS,
        source_device_id="ECM-3501",
        **IRONTON_WINDOW,
    )
    spoliated = purge_evidence(
        api,
        snapshot["id"],
        purge_reason="overwritten by the ECM ring buffer before the hold letter issued",
    )
    build_statement(
        api,
        crash["id"],
        driver_a["id"],
        narrative="The trailer jackknifed on the downgrade.",
        attested=True,
        conditions_note=None,
    )
    case = build_case_in_deliberation(
        api, crash["id"], committee_name="Ironton Safety Review Committee"
    )
    cast_quorum(
        api,
        case,
        vote=BALLOT_DISPOSITION_PREVENTABLE,
        scores=factories.uniform_criterion_scores(3),
    )
    decided = decide_case(api, case["id"])
    return {
        "terminal": terminal,
        "driver": driver_a,
        "crash": crash,
        "spoliated": spoliated,
        "review_case": decided,
    }


class TestIssuingASuspensionAppliesEveryDeclaredSideEffect:
    """The action row, the driver's status and the terminal's counters all move."""

    def test_the_action_opens_issued_and_the_driver_leaves_active(self, api: ApiClient):
        """The suspension is minted with retraining pending and no override.

        PRD: "An accepted action is created in `ISSUED` state with
        `issued_by_user_id` set from the acting operator and a null
        `completed_at`. Its `retraining_status` starts at `PENDING` when a
        `retraining_course_code` was supplied ... A suspension moves an `ACTIVE`
        driver `ACTIVE → SUSPENDED_PENDING_ACTION`"

        Design: Corner/state_machines/suspension_issue_side_effects_move_driver_terminal_counters_and_posture
        """
        context = _decided_preventable_crash_at_a_two_driver_terminal(api)
        assert context["spoliated"]["preservation_state"] == PRESERVATION_PURGED_BEFORE_HOLD
        assert context["review_case"]["determination"] == DETERMINATION_PREVENTABLE
        assert context["review_case"]["decision_basis"] == DECISION_BASIS_WEIGHTED_CRITERIA
        assert_score_2dp(
            context["review_case"]["committee_score"],
            IRONTON_COMMITTEE_SCORE,
            "committee_score",
        )

        before = validate_success(api.get_driver(context["driver"]["id"], SAFETY_MANAGER))
        assert_points_1dp(
            before["preventable_points"], IRONTON_SEVERE_POINTS, "preventable_points"
        )
        assert before["required_action_tier"] == ACTION_TIER_SUSPENSION
        assert before["status"] == DRIVER_STATUS_ACTIVE

        action = validate_success(
            api.create_disciplinary_action(
                factories.disciplinary_action_payload(
                    context["driver"]["id"],
                    context["crash"]["id"],
                    action_type=ACTION_TYPE_SUSPENSION,
                    action_note="seven-day out-of-service period",
                    suspension_start_at=SUSPENSION_START_AT,
                    suspension_end_at=SUSPENSION_END_AT,
                    retraining_course_code="DEFENSIVE-201",
                ),
                SAFETY_MANAGER,
            ),
            201,
        )

        assert action["status"] == ACTION_STATE_ISSUED
        assert action["retraining_status"] == RETRAINING_STATUS_PENDING
        assert action["override_flag"] is False
        assert action["issued_by_user_id"] == OPERATOR_IDS["safety_manager_decider"]
        assert action["completed_at"] is None

        after = validate_success(api.get_driver(context["driver"]["id"], SAFETY_MANAGER))
        assert after["status"] == DRIVER_STATUS_SUSPENDED_PENDING_ACTION
        assert after["version"] == before["version"] + 1

    def test_the_terminal_reaches_critical_posture_at_the_one_half_boundary(
        self, api: ApiClient
    ):
        """One suspended driver out of two sits exactly on the CRITICAL edge.

        PRD: "Because a suspended driver sits on both sides of the division, one
        suspended driver out of two non-terminated drivers is exactly one half
        and lands on `CRITICAL` at the boundary" — and the suspension "raises the
        terminal's `suspended_driver_count` by 1 on its next read while leaving
        `active_driver_count` untouched".

        Design: Corner/state_machines/suspension_issue_side_effects_move_driver_terminal_counters_and_posture
        """
        context = _decided_preventable_crash_at_a_two_driver_terminal(api)
        terminal_id = context["terminal"]["id"]
        before = validate_success(api.get_terminal(terminal_id, SAFETY_MANAGER))
        assert before["active_driver_count"] == 2
        assert before["suspended_driver_count"] == 0
        assert before["staffing_posture"] == STAFFING_POSTURE_OK

        validate_success(
            api.create_disciplinary_action(
                factories.disciplinary_action_payload(
                    context["driver"]["id"],
                    context["crash"]["id"],
                    action_type=ACTION_TYPE_SUSPENSION,
                    action_note="seven-day out-of-service period",
                    suspension_start_at=SUSPENSION_START_AT,
                    suspension_end_at=SUSPENSION_END_AT,
                    retraining_course_code="DEFENSIVE-201",
                ),
                SAFETY_MANAGER,
            ),
            201,
        )

        after = validate_success(api.get_terminal(terminal_id, SAFETY_MANAGER))
        assert after["active_driver_count"] == 2
        assert after["suspended_driver_count"] == 1
        assert after["staffing_posture"] == STAFFING_POSTURE_CRITICAL
        assert after["preventable_crash_count"] == 1
        assert_rate(
            after["crash_rate_per_million_miles"],
            IRONTON_CRASH_RATE,
            "crash_rate_per_million_miles",
        )
        assert after["risk_tier"] == RISK_TIER_STANDARD


MINOR_PROVISIONAL_RESERVE_CENTS = 500_000


def _two_crashes_with_a_closed_claim_and_a_draft_recovery(api: ApiClient) -> dict:
    """A non-recordable crash with a closed claim, and one with an open recovery."""
    terminal = build_terminal(
        api,
        name="Jackson Terminal",
        terminal_code="JAX02",
        region_code="OH",
        annual_miles_millions=2.0,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-3601",
        full_name="Zola Marchetti",
        cdl_number="OH-CDL-3601",
        hire_date="2015-05-15",
    )
    quiet_crash = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-07-30T08:00:00Z",
        notified_at="2026-07-30T08:05:00Z",
        location_text="Yard gate 2",
        severity=SEVERITY_MINOR,
        route_class=ROUTE_CLASS_LOCAL,
        tow_away=False,
        tow_reason=TOW_REASON_NONE,
    )
    recovery_crash = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-07-30T16:00:00Z",
        notified_at="2026-07-30T16:20:00Z",
        location_text="SR-32 at Sour Run Rd",
        severity=SEVERITY_MODERATE,
        route_class=ROUTE_CLASS_REGIONAL,
        tow_away=False,
        tow_reason=TOW_REASON_NONE,
        third_party_at_fault=True,
    )
    build_statement(
        api,
        quiet_crash["id"],
        driver["id"],
        narrative="I brushed the gate post at walking speed.",
        attested=True,
        conditions_note=None,
    )
    case = build_review_case(
        api, quiet_crash["id"], committee_name="Jackson Safety Review Committee"
    )
    quiet_claim = build_claim(api, quiet_crash["id"], claimant_notice_date="2026-07-31")
    closed_claim = validate_success(api.close_claim(quiet_claim["id"], headers=CLAIMS_MANAGER))
    recovery_claim = build_claim(
        api, recovery_crash["id"], claimant_notice_date="2026-07-31"
    )
    recovery = build_subrogation_demand(
        api,
        recovery_claim["id"],
        third_party_name="Sour Run Aggregates",
        at_fault_percentage=60,
        basis_note="third-party dump truck crossed the centre line",
    )
    return {
        "quiet_crash": quiet_crash,
        "review_case": case,
        "closed_claim": closed_claim,
        "recovery_claim": recovery_claim,
        "recovery": recovery,
    }


class TestUndeclaredTriggersAreRefusedWithTheOwningEntitysStateCode:
    """Four rows, four current states, four entity-scoped refusals."""

    def test_filing_a_crash_that_never_required_a_report_is_refused(
        self, api: ApiClient
    ):
        """NOT_REQUIRED is final for the filing dimension and nothing moves it.

        PRD: "It is legal only on a crash that is recordable and whose
        `reporting_status` is still `PENDING_FILING`; a non-recordable crash, or
        one already filed, is refused with `ERR_CRASH_STATE_INVALID`."

        Design: Corner/state_machines/invalid_triggers_from_each_state_return_entity_scoped_state_invalid
        """
        context = _two_crashes_with_a_closed_claim_and_a_draft_recovery(api)
        crash_id = context["quiet_crash"]["id"]
        assert context["quiet_crash"]["reporting_status"] == REPORTING_STATUS_NOT_REQUIRED

        validate_error(
            api.file_regulatory_report(
                crash_id,
                factories.regulatory_report_payload("FMCSA-2026-JAX02-0001"),
                SAFETY_MANAGER,
            ),
            ApiErrorId.CRASH_STATE_INVALID.value,
            409,
        )

        unchanged = validate_success(api.get_crash(crash_id, SAFETY_MANAGER))
        assert unchanged["reporting_status"] == REPORTING_STATUS_NOT_REQUIRED
        assert unchanged["filing_reference"] is None
        assert unchanged["filed_at"] is None

    def test_deciding_or_voting_on_a_draft_case_is_refused_before_any_other_check(
        self, api: ApiClient
    ):
        """The state gate runs ahead of both the quorum gate and the version gate.

        PRD: "The case must be in `DELIBERATION`, or the response is
        `ERR_REVIEW_CASE_STATE_INVALID`." — "A `CommitteeMember` casts a ballot
        against a case that is in `DELIBERATION`; voting on a case still in
        `DRAFT`, or on one already `DECIDED`, is `ERR_REVIEW_CASE_STATE_INVALID`."

        Design: Corner/state_machines/invalid_triggers_from_each_state_return_entity_scoped_state_invalid
        """
        context = _two_crashes_with_a_closed_claim_and_a_draft_recovery(api)
        case = context["review_case"]
        assert case["status"] == REVIEW_STATE_DRAFT

        validate_error(
            api.decide_review_case(case["id"], headers=SAFETY_MANAGER),
            ApiErrorId.REVIEW_CASE_STATE_INVALID.value,
            409,
        )

        validate_error(
            api.cast_vote(
                case["id"],
                factories.vote_payload(
                    case["version"],
                    vote=BALLOT_DISPOSITION_PREVENTABLE,
                    scores=factories.uniform_criterion_scores(2),
                ),
                COMMITTEE_ONE,
            ),
            ApiErrorId.REVIEW_CASE_STATE_INVALID.value,
            409,
        )

        still_draft = validate_success(api.get_review_case(case["id"], SAFETY_MANAGER))
        assert still_draft["status"] == REVIEW_STATE_DRAFT
        assert still_draft["version"] == case["version"]
        assert still_draft["next_vote_sequence"] == 1

    def test_revising_the_reserve_of_a_closed_claim_is_refused(self, api: ApiClient):
        """A closed file accepts no writes, whatever version is quoted.

        PRD: "Both set `closed_at` from the clock and both drive the reserve
        dimension to `FINAL` — from `REVISED` when the reserve was re-estimated at
        least once, or straight from `PROVISIONAL` when it never was. The whole
        residual `outstanding_reserve_cents` is moved into
        `reserve_released_cents`, so `outstanding_reserve_cents` becomes 0"

        Design: Corner/state_machines/invalid_triggers_from_each_state_return_entity_scoped_state_invalid
        """
        context = _two_crashes_with_a_closed_claim_and_a_draft_recovery(api)
        claim = context["closed_claim"]
        assert claim["handling_status"] == CLAIM_HANDLING_CLOSED
        assert claim["reserve_status"] == RESERVE_STATUS_FINAL
        assert_cents(claim["outstanding_reserve_cents"], 0, "outstanding_reserve_cents")
        assert_cents(
            claim["reserve_released_cents"],
            MINOR_PROVISIONAL_RESERVE_CENTS,
            "reserve_released_cents",
        )

        validate_error(
            api.revise_reserve(
                claim["id"],
                factories.reserve_revision_payload(
                    claim["version"], basis=RESERVE_BASIS_PROVISIONAL_REFRESH
                ),
                CLAIMS_ADJUSTER,
            ),
            ApiErrorId.CLAIM_STATE_INVALID.value,
            409,
        )

        unchanged = validate_success(api.get_claim(claim["id"], CLAIMS_ADJUSTER))
        assert unchanged["version"] == claim["version"]
        assert unchanged["revised_reserve_cents"] is None

    def test_a_draft_recovery_can_be_neither_resolved_nor_left_behind_at_closure(
        self, api: ApiClient
    ):
        """Resolution is illegal from DRAFT, and DRAFT also blocks the closure.

        PRD: "Resolution is legal only from `READY_TO_PURSUE`, so a `DRAFT` record
        or an already-resolved one answers
        `ERR_SUBROGATION_DEMAND_STATE_INVALID`." — "Every subrogation demand on
        the claim must have reached `RECOVERED`, `DENIED` or `WRITTEN_OFF`; any
        still in `DRAFT` or `READY_TO_PURSUE` blocks closure with
        `ERR_OPEN_SUBROGATION_REMAINS`."

        Design: Corner/state_machines/invalid_triggers_from_each_state_return_entity_scoped_state_invalid
        """
        context = _two_crashes_with_a_closed_claim_and_a_draft_recovery(api)
        recovery = context["recovery"]
        assert recovery["status"] == SUBROGATION_STATE_DRAFT

        validate_error(
            api.resolve_subrogation_demand(
                recovery["id"],
                factories.resolve_subrogation_payload(
                    resolution=SUBROGATION_RESOLUTION_DENIED,
                    resolution_note="third-party carrier denies liability",
                ),
                CLAIMS_MANAGER,
            ),
            ApiErrorId.SUBROGATION_DEMAND_STATE_INVALID.value,
            409,
        )

        validate_error(
            api.close_claim(context["recovery_claim"]["id"], headers=CLAIMS_MANAGER),
            ApiErrorId.OPEN_SUBROGATION_REMAINS.value,
            422,
        )

        claim = validate_success(
            api.get_claim(context["recovery_claim"]["id"], CLAIMS_ADJUSTER)
        )
        assert claim["handling_status"] == CLAIM_HANDLING_SETUP
        assert claim["closed_at"] is None


KENTON_WINDOW = {
    "window_start_at": "2026-07-27T21:00:00Z",
    "window_end_at": "2026-07-27T23:00:00Z",
    "retention_deadline_at": "2026-12-31T00:00:00Z",
}
KENTON_COMMITTEE_SCORE = 4.00
KENTON_CATASTROPHIC_POINTS = 12.0
SEPARATION_NOTE = "12.0 points on a single catastrophic loss"


def _driver_recommended_for_termination(api: ApiClient) -> dict:
    """A lone driver whose catastrophic preventable loss demands separation."""
    terminal = build_terminal(
        api,
        name="Kenton Terminal",
        terminal_code="KEN02",
        region_code="OH",
        annual_miles_millions=1.0,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-3701",
        full_name="Aurel Vasquez",
        cdl_number="OH-CDL-3701",
        hire_date="2008-08-08",
    )
    crash = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-07-27T22:00:00Z",
        notified_at="2026-07-27T22:30:00Z",
        location_text="I-75 MM 111",
        severity=SEVERITY_CATASTROPHIC,
        route_class=ROUTE_CLASS_LINEHAUL,
        tow_away=True,
        tow_reason=TOW_REASON_DISABLING_DAMAGE,
        injury_transported_count=2,
    )
    photo = request_evidence(
        api,
        crash["id"],
        kind=EVIDENCE_SCENE_PHOTO,
        source_device_id="PHONE-3701",
        **KENTON_WINDOW,
    )
    preserve_evidence(
        api,
        photo["id"],
        preserved_copy_uri="s3://evidence/2923ken/scene-3701.jpg",
        evidence_hash="4f4f5a5a6b6b7c7c8d8d9e9e0f0f1a1a",
    )
    snapshot = request_evidence(
        api,
        crash["id"],
        kind=EVIDENCE_TELEMATICS,
        source_device_id="ECM-3701",
        **KENTON_WINDOW,
    )
    purge_evidence(api, snapshot["id"], purge_reason="ECM module destroyed in the fire")
    build_statement(
        api,
        crash["id"],
        driver["id"],
        narrative="I lost the trailer on the ramp.",
        attested=True,
        conditions_note=None,
    )
    case = build_case_in_deliberation(
        api, crash["id"], committee_name="Kenton Safety Review Committee"
    )
    cast_quorum(
        api,
        case,
        vote=BALLOT_DISPOSITION_PREVENTABLE,
        scores=factories.uniform_criterion_scores(4),
    )
    decided = decide_case(api, case["id"])
    recommendation = validate_success(
        api.create_disciplinary_action(
            factories.disciplinary_action_payload(
                driver["id"],
                crash["id"],
                action_type=ACTION_TYPE_TERMINATION_RECOMMENDATION,
                action_note="recommend separation to the review board",
            ),
            SAFETY_MANAGER,
        ),
        201,
    )
    return {
        "terminal": terminal,
        "driver": driver,
        "crash": crash,
        "review_case": decided,
        "recommendation": recommendation,
    }


class TestTerminalStatesAbsorbEveryFurtherTrigger:
    """A separated driver and a recommendation-only action both stop moving."""

    def test_a_recommendation_that_never_required_retraining_cannot_complete_one(
        self, api: ApiClient
    ):
        """The action is ISSUED yet its retraining dimension was never pending.

        PRD: "Its `retraining_status` starts at `PENDING` when a
        `retraining_course_code` was supplied and at `NOT_REQUIRED` when none was
        — so coaching and termination recommendations carry `NOT_REQUIRED` from
        birth and can never be completed as retraining." — "The action must be in
        `ISSUED` state with a `retraining_status` of `PENDING`; an action that is
        already `COMPLETED` or has been `VOIDED` is refused with
        `ERR_DISCIPLINARY_ACTION_STATE_INVALID`, and so is one that never required
        retraining at all."

        Design: Corner/state_machines/terminated_driver_and_non_pending_action_reject_all_further_transitions
        """
        context = _driver_recommended_for_termination(api)
        action = context["recommendation"]
        assert_score_2dp(
            context["review_case"]["committee_score"],
            KENTON_COMMITTEE_SCORE,
            "committee_score",
        )
        assert context["review_case"]["determination"] == DETERMINATION_PREVENTABLE
        assert action["status"] == ACTION_STATE_ISSUED
        assert action["retraining_status"] == RETRAINING_STATUS_NOT_REQUIRED

        validate_error(
            api.complete_retraining(
                action["id"],
                factories.complete_retraining_payload(
                    completion_note="trying to close out the recommendation"
                ),
                SAFETY_ADMIN,
            ),
            ApiErrorId.DISCIPLINARY_ACTION_STATE_INVALID.value,
            409,
        )

        unchanged = validate_success(api.get_disciplinary_action(action["id"], SAFETY_MANAGER))
        assert unchanged["status"] == ACTION_STATE_ISSUED
        assert unchanged["completed_at"] is None
        assert unchanged["version"] == action["version"]

    def test_separation_is_absorbing_for_decisions_and_for_discipline_alike(
        self, api: ApiClient
    ):
        """After SEPARATE neither a reversal nor a fresh action is accepted.

        PRD: "A recorded `SEPARATE` sets `continued_employment_decision` to
        `SEPARATE`, records the `decision_note` and moves the driver to
        `TERMINATED`" — "A driver who is already `TERMINATED` accepts neither,
        yielding `ERR_DRIVER_STATE_INVALID`." — "A driver who has already been
        separated accepts no further action of any kind and yields
        `ERR_DRIVER_STATE_INVALID`."

        Design: Corner/state_machines/terminated_driver_and_non_pending_action_reject_all_further_transitions
        """
        context = _driver_recommended_for_termination(api)
        driver_id = context["driver"]["id"]
        before = validate_success(api.get_driver(driver_id, SAFETY_MANAGER))
        assert_points_1dp(
            before["preventable_points"], KENTON_CATASTROPHIC_POINTS, "preventable_points"
        )
        assert before["required_action_tier"] == ACTION_TIER_TERMINATION_REVIEW

        separated = validate_success(
            api.decide_employment(
                driver_id,
                factories.employment_decision_payload(
                    decision=EMPLOYMENT_DECISION_SEPARATE, decision_note=SEPARATION_NOTE
                ),
                SAFETY_MANAGER,
            )
        )
        assert separated["status"] == DRIVER_STATUS_TERMINATED
        assert separated["continued_employment_decision"] == EMPLOYMENT_DECISION_SEPARATE
        assert separated["decision_note"] == SEPARATION_NOTE

        validate_error(
            api.decide_employment(
                driver_id,
                factories.employment_decision_payload(
                    decision=EMPLOYMENT_DECISION_CONTINUE, decision_note="reversing course"
                ),
                SAFETY_MANAGER,
            ),
            ApiErrorId.DRIVER_STATE_INVALID.value,
            409,
        )
        validate_error(
            api.create_disciplinary_action(
                factories.disciplinary_action_payload(
                    driver_id,
                    context["crash"]["id"],
                    action_type=ACTION_TYPE_COACHING,
                    action_note="post-separation coaching",
                ),
                SAFETY_MANAGER,
            ),
            ApiErrorId.DRIVER_STATE_INVALID.value,
            409,
        )

        still_separated = validate_success(api.get_driver(driver_id, SAFETY_MANAGER))
        assert still_separated["continued_employment_decision"] == EMPLOYMENT_DECISION_SEPARATE
        assert still_separated["version"] == separated["version"]

    def test_the_emptied_terminal_reports_ok_rather_than_dividing_by_zero(
        self, api: ApiClient
    ):
        """Separation empties the headcounts but leaves the crash counter alone.

        PRD: "When `active_driver_count` is zero the posture is `OK` — there are
        no drivers to strain." — "Because both terminal headcounts are defined
        over non-terminated drivers, separation removes him from
        `active_driver_count` on the next read"

        Design: Corner/state_machines/terminated_driver_and_non_pending_action_reject_all_further_transitions
        """
        context = _driver_recommended_for_termination(api)
        validate_success(
            api.decide_employment(
                context["driver"]["id"],
                factories.employment_decision_payload(
                    decision=EMPLOYMENT_DECISION_SEPARATE, decision_note=SEPARATION_NOTE
                ),
                SAFETY_MANAGER,
            )
        )

        terminal = validate_success(api.get_terminal(context["terminal"]["id"], SAFETY_ADMIN))
        assert terminal["active_driver_count"] == 0
        assert terminal["suspended_driver_count"] == 0
        assert terminal["staffing_posture"] == STAFFING_POSTURE_OK
        assert terminal["preventable_crash_count"] == 1


LIMA_EVIDENCE = {
    "kind": EVIDENCE_TELEMATICS,
    "source_device_id": "ECM-3801",
    "window_start_at": "2026-07-31T10:00:00Z",
    "window_end_at": "2026-07-31T12:00:00Z",
    "retention_deadline_at": "2026-10-31T00:00:00Z",
}
LIMA_URI = "s3://evidence/2923lim/ecm-3801.json"
LIMA_HASH = "5a5a6b6b7c7c8d8d9e9e0f0f1a1a2b2b"
LIMA_REPLAY_URI = "s3://evidence/2923lim/ecm-3801-again.json"
LIMA_REPLAY_HASH = "6b6b7c7c8d8d9e9e0f0f1a1a2b2b3c3c"
LIMA_COMMITTEE = "Lima Safety Review Committee"
SHARED_EMPLOYEE_CODE = "D-3801"


def _one_of_everything_across_two_terminals(api: ApiClient) -> dict:
    """One crash carrying its single case, single claim and one preserved item."""
    set_clock(api, CLOCK_EPOCH)
    terminal_a = build_terminal(
        api,
        name="Lima Terminal",
        terminal_code="LIM02",
        region_code="OH",
        annual_miles_millions=2.0,
    )
    terminal_b = build_terminal(
        api,
        name="Marion Terminal",
        terminal_code="MAR02",
        region_code="OH",
        annual_miles_millions=2.0,
    )
    driver = build_driver(
        api,
        terminal_a["id"],
        employee_code=SHARED_EMPLOYEE_CODE,
        full_name="Bela Toranaga",
        cdl_number="OH-CDL-3801",
        hire_date="2016-06-16",
    )
    crash = build_crash(
        api,
        driver["id"],
        terminal_a["id"],
        occurred_at="2026-07-31T11:00:00Z",
        notified_at="2026-07-31T11:15:00Z",
        location_text="SR-309 at Cable Rd",
        severity=SEVERITY_MINOR,
        route_class=ROUTE_CLASS_LOCAL,
        tow_away=False,
        tow_reason=TOW_REASON_NONE,
    )
    requested = request_evidence(api, crash["id"], **LIMA_EVIDENCE)
    preserved = preserve_evidence(
        api, requested["id"], preserved_copy_uri=LIMA_URI, evidence_hash=LIMA_HASH
    )
    build_statement(
        api,
        crash["id"],
        driver["id"],
        narrative="Mirror strike in the turn lane.",
        conditions_note=None,
    )
    case = build_review_case(api, crash["id"], committee_name=LIMA_COMMITTEE)
    opened = validate_success(api.open_deliberation(case["id"], headers=SAFETY_MANAGER))
    claim = build_claim(api, crash["id"], claimant_notice_date="2026-07-31")
    return {
        "terminal_a": terminal_a,
        "terminal_b": terminal_b,
        "driver": driver,
        "crash": crash,
        "evidence": preserved,
        "review_case": opened,
        "claim": claim,
    }


class TestReplayingACreateIsRefusedRatherThanDuplicated:
    """The at-most-one children each report their own uniqueness code."""

    def test_the_second_case_and_the_second_claim_on_one_crash_are_both_refused(
        self, api: ApiClient
    ):
        """Each singleton child names itself, not the parent's state.

        PRD: "A crash may carry at most one review case for its whole life, so a
        second attempt is refused with `ERR_REVIEW_CASE_EXISTS` — and this is
        precisely the case where the referential rule wins over the state rule,
        because a crash that already has a case is no longer in its `REPORTED`
        state yet the duplicate is what the operator needs to be told." — "a
        crash carries at most one claim, so a second attempt is
        `ERR_CLAIM_EXISTS`"

        Design: Corner/state_machines/repeated_creates_and_transitions_are_refused_not_duplicated
        """
        context = _one_of_everything_across_two_terminals(api)
        crash_id = context["crash"]["id"]

        duplicate_case = api.create_review_case(
            factories.review_case_payload(
                crash_id, committee_name=f"{LIMA_COMMITTEE} (second attempt)"
            ),
            SAFETY_MANAGER,
        )
        duplicate_case_error = validate_error(
            duplicate_case, ApiErrorId.REVIEW_CASE_EXISTS.value, 409
        )
        assert (
            duplicate_case_error["error_id"] != ApiErrorId.CRASH_STATE_INVALID.value
        )

        validate_error(
            api.create_claim(
                factories.claim_payload(crash_id, claimant_notice_date="2026-08-01"),
                CLAIMS_ADJUSTER,
            ),
            ApiErrorId.CLAIM_EXISTS.value,
            409,
        )

        cases, case_meta = validate_paginated(
            api.list_review_cases(SAFETY_MANAGER, {"crash_id": crash_id})
        )
        assert case_meta["total_count"] == 1
        assert cases[0]["id"] == context["review_case"]["id"]
        claims, claim_meta = validate_paginated(
            api.list_claims(CLAIMS_ADJUSTER, {"crash_id": crash_id})
        )
        assert claim_meta["total_count"] == 1
        assert claims[0]["id"] == context["claim"]["id"]

    def test_the_terminal_code_is_fleet_wide_while_the_employee_code_is_per_terminal(
        self, api: ApiClient
    ):
        """The same literal collides at one scope and is legal at the other.

        PRD: "an operator-assigned `terminal_code` of three to ten uppercase
        alphanumeric characters that must be unique across the whole fleet ... A
        second terminal claiming a code that already exists is refused with
        `ERR_TERMINAL_CODE_DUPLICATE`." — "an `employee_code` that must be unique
        among the drivers of that same terminal, so the same payroll code may
        legitimately appear at two different terminals but never twice at one"

        Design: Corner/state_machines/repeated_creates_and_transitions_are_refused_not_duplicated
        """
        context = _one_of_everything_across_two_terminals(api)

        validate_error(
            api.create_terminal(
                factories.terminal_payload(
                    name="Lima Annex",
                    terminal_code="LIM02",
                    region_code="IN",
                    annual_miles_millions=1.0,
                ),
                SAFETY_ADMIN,
            ),
            ApiErrorId.TERMINAL_CODE_DUPLICATE.value,
            409,
        )
        validate_error(
            api.create_driver(
                factories.driver_payload(
                    context["terminal_a"]["id"],
                    employee_code=SHARED_EMPLOYEE_CODE,
                    full_name="Bela Toranaga (rehire)",
                    cdl_number="OH-CDL-3899",
                    hire_date="2026-01-05",
                ),
                SAFETY_ADMIN,
            ),
            ApiErrorId.EMPLOYEE_CODE_DUPLICATE.value,
            409,
        )

        elsewhere = validate_success(
            api.create_driver(
                factories.driver_payload(
                    context["terminal_b"]["id"],
                    employee_code=SHARED_EMPLOYEE_CODE,
                    full_name="Cato Rasmussen",
                    cdl_number="OH-CDL-3802",
                    hire_date="2016-06-16",
                ),
                SAFETY_ADMIN,
            ),
            201,
        )
        assert elsewhere["employee_code"] == SHARED_EMPLOYEE_CODE
        assert elsewhere["terminal_id"] == context["terminal_b"]["id"]
        assert elsewhere["status"] == DRIVER_STATUS_ACTIVE

        _, terminal_meta = validate_paginated(api.list_terminals(SAFETY_ADMIN))
        assert terminal_meta["total_count"] == 2

    def test_a_replayed_transition_overwrites_nothing_it_already_wrote(
        self, api: ApiClient
    ):
        """The second preserve and the second open both leave the row alone.

        PRD: "The item must currently be `REQUESTED`; an item that is already
        preserved, already spoliated or already released is refused with
        `ERR_EVIDENCE_ITEM_STATE_INVALID`." — "A case that is not in `DRAFT` —
        one where deliberation has already been opened, for instance — is refused
        with `ERR_REVIEW_CASE_STATE_INVALID`."

        Design: Corner/state_machines/repeated_creates_and_transitions_are_refused_not_duplicated
        """
        context = _one_of_everything_across_two_terminals(api)
        evidence_id = context["evidence"]["id"]
        case_id = context["review_case"]["id"]

        validate_error(
            api.preserve_evidence_item(
                evidence_id,
                factories.preserve_payload(
                    preserved_copy_uri=LIMA_REPLAY_URI, evidence_hash=LIMA_REPLAY_HASH
                ),
                DISPATCHER,
            ),
            ApiErrorId.EVIDENCE_ITEM_STATE_INVALID.value,
            409,
        )
        validate_error(
            api.open_deliberation(case_id, headers=SAFETY_MANAGER),
            ApiErrorId.REVIEW_CASE_STATE_INVALID.value,
            409,
        )

        item = validate_success(api.get_evidence_item(evidence_id, DISPATCHER))
        assert item["preservation_state"] == PRESERVATION_PRESERVED
        assert item["preserved_copy_uri"] == LIMA_URI
        assert item["evidence_hash"] == LIMA_HASH
        assert item["version"] == context["evidence"]["version"]

        case = validate_success(api.get_review_case(case_id, SAFETY_MANAGER))
        assert case["status"] == REVIEW_STATE_DELIBERATION
        assert case["version"] == context["review_case"]["version"]


NEWARK_WINDOW = {
    "window_start_at": "2026-07-30T18:00:00Z",
    "window_end_at": "2026-07-30T20:00:00Z",
    "retention_deadline_at": "2026-10-31T00:00:00Z",
}
SPOLIATION_REASON = "ECM ring buffer overwritten before the hold letter issued"
DISPOSAL_REASON = "retention schedule elapsed"
NEWARK_SCORE_BEFORE = 10
NEWARK_SCORE_AFTER = 30
NEWARK_MULTIPLIER_BEFORE = 1.00
NEWARK_MULTIPLIER_AFTER = 1.15
MODERATE_PROVISIONAL_RESERVE_CENTS = 2_500_000


def _claimed_crash_with_one_preserved_and_one_requested_item(api: ApiClient) -> dict:
    """A moderate crash whose camera is under hold and whose telematics is not."""
    set_clock(api, CLOCK_EPOCH)
    terminal = build_terminal(
        api,
        name="Newark Terminal",
        terminal_code="NWK02",
        region_code="OH",
        annual_miles_millions=2.0,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-3901",
        full_name="Dara Ionescu",
        cdl_number="OH-CDL-3901",
        hire_date="2013-03-13",
    )
    crash = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-07-30T19:00:00Z",
        notified_at="2026-07-30T19:10:00Z",
        location_text="SR-16 at Cherry Valley Rd",
        severity=SEVERITY_MODERATE,
        route_class=ROUTE_CLASS_REGIONAL,
        tow_away=False,
        tow_reason=TOW_REASON_NONE,
    )
    camera = request_evidence(
        api,
        crash["id"],
        kind=EVIDENCE_FORWARD_CAMERA,
        source_device_id="CAM-3901",
        **NEWARK_WINDOW,
    )
    preserved_camera = preserve_evidence(
        api,
        camera["id"],
        preserved_copy_uri="s3://evidence/2923nwk/cam-3901.mp4",
        evidence_hash="7c7c8d8d9e9e0f0f1a1a2b2b3c3c4d4d",
    )
    telematics = request_evidence(
        api,
        crash["id"],
        kind=EVIDENCE_TELEMATICS,
        source_device_id="ECM-3901",
        **NEWARK_WINDOW,
    )
    claim = build_claim(api, crash["id"], claimant_notice_date="2026-07-31")
    return {
        "terminal": terminal,
        "driver": driver,
        "crash": crash,
        "camera": preserved_camera,
        "telematics": telematics,
        "claim": claim,
    }


class TestThePurgeBranchIsChosenByTheItemsOwnStateAndByTheClaim:
    """One endpoint, two outcomes, and a conditional re-score behind one of them."""

    def test_purging_an_unsecured_item_spoliates_and_re_scores_the_sibling_claim(
        self, api: ApiClient
    ):
        """The requested branch is never blocked and it reaches the claim.

        PRD: "An item that is still merely `REQUESTED` when it is purged moves
        `REQUESTED → PURGED_BEFORE_HOLD`. This is spoliation ... The crash's
        `evidence_posture` becomes `COMPROMISED` — irreversibly ... and the
        crash's claim, if one exists, is re-scored so that its litigation risk
        rises by the difference between the compromised-evidence loading and the
        partial-evidence loading."

        Design: Corner/state_machines/conditional_cascade_spoliation_rescores_only_an_existing_claim
        """
        context = _claimed_crash_with_one_preserved_and_one_requested_item(api)
        before = context["claim"]
        assert before["litigation_risk_score"] == NEWARK_SCORE_BEFORE
        assert_multiplier(
            before["litigation_risk_multiplier"],
            NEWARK_MULTIPLIER_BEFORE,
            "litigation_risk_multiplier",
        )
        assert before["counsel_required"] is False
        opening_crash = validate_success(api.get_crash(context["crash"]["id"], SAFETY_MANAGER))
        assert opening_crash["evidence_posture"] == EVIDENCE_POSTURE_PARTIAL
        assert opening_crash["preventability_status"] == PREVENTABILITY_REPORTED

        spoliated = purge_evidence(
            api, context["telematics"]["id"], purge_reason=SPOLIATION_REASON
        )

        assert spoliated["preservation_state"] == PRESERVATION_PURGED_BEFORE_HOLD
        assert spoliated["purge_reason"] == SPOLIATION_REASON
        assert spoliated["version"] == context["telematics"]["version"] + 1

        crash = validate_success(api.get_crash(context["crash"]["id"], SAFETY_MANAGER))
        assert crash["evidence_posture"] == EVIDENCE_POSTURE_COMPROMISED

        after = validate_success(api.get_claim(context["claim"]["id"], CLAIMS_ADJUSTER))
        assert after["litigation_risk_score"] == NEWARK_SCORE_AFTER
        assert_multiplier(
            after["litigation_risk_multiplier"],
            NEWARK_MULTIPLIER_AFTER,
            "litigation_risk_multiplier",
        )
        assert after["counsel_required"] is False

    def test_the_frozen_reserve_is_not_retro_multiplied_by_the_new_posture(
        self, api: ApiClient
    ):
        """The derived multiplier moves while the stored reserve stands still.

        PRD: "Because the score is derived on read, preserving a missing evidence
        kind or granting an appeal moves the multiplier with no claim-side write
        at all — while the stored reserve stays exactly where it was, which is
        what makes multiplier-versus-reserve staleness visible to an adjuster."

        Design: Corner/state_machines/conditional_cascade_spoliation_rescores_only_an_existing_claim
        """
        context = _claimed_crash_with_one_preserved_and_one_requested_item(api)
        assert_cents(
            context["claim"]["provisional_reserve_cents"],
            MODERATE_PROVISIONAL_RESERVE_CENTS,
            "provisional_reserve_cents",
        )

        purge_evidence(api, context["telematics"]["id"], purge_reason=SPOLIATION_REASON)

        after = validate_success(api.get_claim(context["claim"]["id"], CLAIMS_ADJUSTER))
        assert_cents(
            after["provisional_reserve_cents"],
            MODERATE_PROVISIONAL_RESERVE_CENTS,
            "provisional_reserve_cents",
        )
        assert_cents(
            after["outstanding_reserve_cents"],
            MODERATE_PROVISIONAL_RESERVE_CENTS,
            "outstanding_reserve_cents",
        )
        assert after["revised_reserve_cents"] is None
        assert after["reserve_status"] == RESERVE_STATUS_PROVISIONAL

    def test_the_held_item_is_released_only_once_the_claim_is_closed(
        self, api: ApiClient
    ):
        """The identical call is refused, then permitted, on the same row.

        PRD: "Release is permitted only when the item's crash has no claim at
        all, or when that claim's `handling_status` is `CLOSED`; attempting it
        while a claim on the crash is still open is refused with
        `ERR_LITIGATION_HOLD_ACTIVE`, because the litigation hold outranks the
        retention schedule."

        Design: Corner/state_machines/conditional_cascade_spoliation_rescores_only_an_existing_claim
        """
        context = _claimed_crash_with_one_preserved_and_one_requested_item(api)
        purge_evidence(api, context["telematics"]["id"], purge_reason=SPOLIATION_REASON)
        camera_id = context["camera"]["id"]

        validate_error(
            api.purge_evidence_item(
                camera_id, factories.purge_payload(purge_reason=DISPOSAL_REASON), SAFETY_ADMIN
            ),
            ApiErrorId.LITIGATION_HOLD_ACTIVE.value,
            409,
        )
        held = validate_success(api.get_evidence_item(camera_id, SAFETY_ADMIN))
        assert held["preservation_state"] == PRESERVATION_PRESERVED
        assert held["purge_reason"] is None
        assert held["version"] == context["camera"]["version"]

        closed = validate_success(api.close_claim(context["claim"]["id"], headers=CLAIMS_MANAGER))
        assert closed["handling_status"] == CLAIM_HANDLING_CLOSED

        released = purge_evidence(api, camera_id, purge_reason=DISPOSAL_REASON)
        assert released["preservation_state"] == PRESERVATION_RELEASED
        assert released["purge_reason"] == DISPOSAL_REASON
        assert released["version"] == context["camera"]["version"] + 1

        crash = validate_success(api.get_crash(context["crash"]["id"], SAFETY_MANAGER))
        assert crash["evidence_posture"] == EVIDENCE_POSTURE_COMPROMISED
