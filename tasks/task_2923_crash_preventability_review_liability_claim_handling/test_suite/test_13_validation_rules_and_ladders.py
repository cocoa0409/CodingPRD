"""Validation rules read from both sides: the violation and the exact satisfaction.

Where a bound is inclusive the legal edge is exercised as well as the illegal one,
so an implementation that turns `<=` into `<` is caught by the passing half of the
pair rather than only by the failing half.
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
    assert_points_1dp,
    assert_score_2dp,
    shift_instant,
)
from test_helpers.constants import (
    ABSENT_UUIDS,
    ACTION_TIER_NONE,
    ACTION_TIER_SUSPENSION,
    ACTION_TYPE_COACHING,
    ACTION_TYPE_RETRAINING,
    ACTION_TYPE_SUSPENSION,
    APPEAL_CODE_CRITERIA_MISAPPLICATION,
    APPEAL_CODE_NEW_EVIDENCE,
    APPEAL_CODE_PROCEDURAL,
    BALLOT_DISPOSITION_ABSTAIN,
    BALLOT_DISPOSITION_NON_PREVENTABLE,
    BALLOT_DISPOSITION_PREVENTABLE,
    CLAIM_HANDLING_NEGOTIATION,
    CLAIM_HANDLING_SETTLEMENT_COMPLETE,
    CLAIMANT_TYPE_PROPERTY,
    CLOCK_EPOCH,
    DEMAND_STATE_COUNTER_OUTSTANDING,
    DEMAND_STATE_DEMANDED,
    DEMAND_STATE_OFFER_OUTSTANDING,
    DECISION_BASIS_WEIGHTED_CRITERIA,
    DEMAND_STATE_SETTLED,
    DETERMINATION_NON_PREVENTABLE,
    DETERMINATION_PENDING,
    DETERMINATION_PREVENTABLE,
    DRIVER_STATUS_ACTIVE,
    EMPLOYMENT_DECISION_PENDING,
    EMPLOYMENT_DECISION_SEPARATE,
    EVIDENCE_ELD_LOG,
    EVIDENCE_FORWARD_CAMERA,
    EVIDENCE_POSTURE_COMPLETE,
    EVIDENCE_POSTURE_COMPROMISED,
    EVIDENCE_SCENE_PHOTO,
    EVIDENCE_TELEMATICS,
    LAYER_KIND_SIR,
    PRESERVATION_REQUESTED,
    PREVENTABILITY_REPORTED,
    PREVENTABILITY_UNDER_REVIEW,
    RESERVE_BASIS_DEMAND_BASED,
    RESERVE_STATUS_PROVISIONAL,
    RESERVE_STATUS_REVISED,
    REVIEW_STATE_DECIDED,
    REVIEW_STATE_DELIBERATION,
    REVIEW_STATE_DRAFT,
    ROUND_OUTCOME_ACCEPTED,
    ROUND_OUTCOME_COUNTERED,
    ROUND_OUTCOME_OPEN,
    ROLE_DISPATCHER,
    ROUND_OUTCOME_SUPERSEDED,
    ROUTE_CLASS_LINEHAUL,
    ROUTE_CLASS_LOCAL,
    ROUTE_CLASS_REGIONAL,
    SEVERITY_MINOR,
    SEVERITY_MODERATE,
    SEVERITY_SEVERE,
    SUBROGATION_RESOLUTION_DENIED,
    SUBROGATION_RESOLUTION_RECOVERED,
    SUBROGATION_STATE_DRAFT,
    TOW_REASON_NONE,
)
from test_helpers.fixtures import (
    APPEALS_MANAGER,
    AUDITOR,
    CLAIMS_ADJUSTER,
    CLAIMS_MANAGER,
    COMMITTEE_ONE,
    DISPATCHER,
    SAFETY_MANAGER,
    build_claim,
    build_crash,
    build_demand,
    build_driver,
    build_case_in_deliberation,
    build_policy_layer,
    build_review_case,
    build_statement,
    build_subrogation_demand,
    build_terminal,
    cast_quorum,
    decide_case,
    grant_appeal,
    make_counter,
    make_offer,
    preserve_evidence,
    purge_evidence,
    request_evidence,
    rescind,
    revise_reserve,
    set_clock,
    settle,
)
from test_helpers.test_users import make_missing_user_id_headers

YELLOW_SPRINGS_DEMAND_A_CENTS = 2_000_000
YELLOW_SPRINGS_DEMAND_B_CENTS = 300_000
FIRST_OFFER_CENTS = 500_000
FIRST_COUNTER_CENTS = 1_800_000
FIRST_GAP_CENTS = 1_300_000
SECOND_OFFER_CENTS = 900_000
RAISED_COUNTER_CENTS = 1_900_000
OVER_DEMAND_OFFER_CENTS = 2_500_000
SECOND_GAP_CENTS = 900_000
YELLOW_SPRINGS_ALAE_CENTS = 160_000
YELLOW_SPRINGS_TOTAL_CENTS = 2_160_000
YELLOW_SPRINGS_REFERENCE = "SET-2026-YSP02-0001"


def _claim_with_two_property_demands(api: ApiClient) -> dict:
    """A 2,500,000 reserve, a single deep retention layer and two open demands.

    Both demands are property-damage files, so the bodily-injury counsel gate is
    out of the picture and only the two monotonicity rules bound the ledger.
    """
    terminal = build_terminal(
        api,
        name="Yellow Springs Terminal",
        terminal_code="YSP02",
        region_code="OH",
        annual_miles_millions=3.0,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-4901",
        full_name="Sanne Ogundipe",
        cdl_number="OH-CDL-4901",
        hire_date="2014-03-03",
    )
    crash = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-07-30T09:00:00Z",
        notified_at="2026-07-30T09:20:00Z",
        location_text="US-68 at Corry St",
        severity=SEVERITY_MODERATE,
        route_class=ROUTE_CLASS_REGIONAL,
        tow_away=False,
        tow_reason=TOW_REASON_NONE,
        injury_transported_count=0,
        fatality_count=0,
        hazmat_release=False,
        mechanical_factor=False,
        third_party_at_fault=False,
    )
    build_policy_layer(
        api,
        program_year=2026,
        layer_index=1,
        layer_type=LAYER_KIND_SIR,
        attachment_point_cents=0,
        limit_cents=10_000_000,
        insurer_name="Self-insured retention",
    )
    claim = build_claim(api, crash["id"], claimant_notice_date="2026-07-31")
    demand_a = build_demand(
        api,
        claim["id"],
        claimant_name="Corry Street Bakery",
        claimant_type=CLAIMANT_TYPE_PROPERTY,
        demand_amount_cents=YELLOW_SPRINGS_DEMAND_A_CENTS,
        represented_by_counsel=False,
        demand_received_at="2026-07-31T10:00:00Z",
    )
    demand_b = build_demand(
        api,
        claim["id"],
        claimant_name="Glen Helen Fence Trust",
        claimant_type=CLAIMANT_TYPE_PROPERTY,
        demand_amount_cents=YELLOW_SPRINGS_DEMAND_B_CENTS,
        represented_by_counsel=False,
        demand_received_at="2026-07-31T10:30:00Z",
    )
    return {
        "crash": crash,
        "claim": claim,
        "demand_a": demand_a,
        "demand_b": demand_b,
    }


class TestTheNegotiationLadderSqueezesTheGapFromBothSides:
    """The carrier may only climb, the claimant may only descend, and both may stand still once."""

    def test_the_two_carrier_side_clauses_report_distinct_error_ids(self, api: ApiClient):
        """A repeated offer and an over-the-demand offer fail differently.

        PRD: "`carrier_offer_cents` may never exceed the demand's
        `demand_amount_cents`, since the carrier cannot offer more than was asked;
        a violation is `ERR_OFFER_EXCEEDS_DEMAND`. And when a round already
        stands, the new `carrier_offer_cents` must strictly exceed the standing
        round's `carrier_offer_cents` — the carrier may not lower its position and
        may not repeat it — with a violation reported as
        `ERR_OFFER_NOT_MONOTONIC`."

        Design: Corner/validations/negotiation_ladder_refuses_regressive_offers_and_rising_counters
        """
        context = _claim_with_two_property_demands(api)
        demand_id = context["demand_a"]["id"]
        assert context["demand_a"]["status"] == DEMAND_STATE_DEMANDED

        first = make_offer(api, demand_id, FIRST_OFFER_CENTS)
        assert first["round_index"] == 1
        assert first["outcome"] == ROUND_OUTCOME_OPEN
        assert first["claimant_counter_cents"] is None
        assert first["gap_cents"] is None
        assert_instants_equal(first["offered_at"], CLOCK_EPOCH, "offered_at")

        countered = make_counter(api, demand_id, FIRST_COUNTER_CENTS)
        assert countered["outcome"] == ROUND_OUTCOME_COUNTERED
        assert_cents(countered["gap_cents"], FIRST_GAP_CENTS, "gap_cents")
        assert FIRST_GAP_CENTS == FIRST_COUNTER_CENTS - FIRST_OFFER_CENTS

        validate_error(
            api.create_offer(
                demand_id, factories.offer_payload(FIRST_OFFER_CENTS), CLAIMS_ADJUSTER
            ),
            ApiErrorId.OFFER_NOT_MONOTONIC.value,
            422,
        )
        validate_error(
            api.create_offer(
                demand_id,
                factories.offer_payload(OVER_DEMAND_OFFER_CENTS),
                CLAIMS_ADJUSTER,
            ),
            ApiErrorId.OFFER_EXCEEDS_DEMAND.value,
            422,
        )

        unchanged = validate_success(api.get_demand(demand_id, CLAIMS_ADJUSTER))
        assert unchanged["status"] == DEMAND_STATE_COUNTER_OUTSTANDING
        assert unchanged["round_count"] == 1

    def test_a_fresh_offer_supersedes_the_standing_round_and_resets_the_claimant(
        self, api: ApiClient
    ):
        """A raised counter and a flat counter both fail on the one error id.

        PRD: "The counter must strictly exceed the standing round's
        `carrier_offer_cents` ... and, when an earlier round carried a counter, the
        new counter may not exceed that previous `claimant_counter_cents`, because
        claimant positions may not increase. Either violation is
        `ERR_COUNTER_NOT_MONOTONIC`."

        Design: Corner/validations/negotiation_ladder_refuses_regressive_offers_and_rising_counters
        """
        context = _claim_with_two_property_demands(api)
        demand_id = context["demand_a"]["id"]
        first = make_offer(api, demand_id, FIRST_OFFER_CENTS)
        make_counter(api, demand_id, FIRST_COUNTER_CENTS)

        second = make_offer(api, demand_id, SECOND_OFFER_CENTS)
        assert second["round_index"] == 2
        assert second["outcome"] == ROUND_OUTCOME_OPEN

        rounds, _ = validate_paginated(api.list_negotiation_rounds(demand_id, CLAIMS_ADJUSTER))
        by_index = {row["round_index"]: row for row in rounds}
        assert by_index[1]["id"] == first["id"]
        assert by_index[1]["outcome"] == ROUND_OUTCOME_SUPERSEDED
        assert by_index[2]["outcome"] == ROUND_OUTCOME_OPEN

        validate_error(
            api.create_counter(
                demand_id,
                factories.counter_payload(RAISED_COUNTER_CENTS),
                CLAIMS_ADJUSTER,
            ),
            ApiErrorId.COUNTER_NOT_MONOTONIC.value,
            422,
        )
        validate_error(
            api.create_counter(
                demand_id,
                factories.counter_payload(SECOND_OFFER_CENTS),
                CLAIMS_ADJUSTER,
            ),
            ApiErrorId.COUNTER_NOT_MONOTONIC.value,
            422,
        )

        held = validate_success(api.get_demand(demand_id, CLAIMS_ADJUSTER))
        assert held["status"] == DEMAND_STATE_OFFER_OUTSTANDING
        assert held["round_count"] == 2

    def test_standing_still_is_legal_on_both_sides_of_the_table(self, api: ApiClient):
        """A repeated counter and an offer equal to the demand both go through.

        PRD: "the new counter may not exceed that previous
        `claimant_counter_cents`". And: "`carrier_offer_cents` may never exceed the
        demand's `demand_amount_cents`".

        Design: Corner/validations/negotiation_ladder_refuses_regressive_offers_and_rising_counters
        """
        context = _claim_with_two_property_demands(api)
        demand_id = context["demand_a"]["id"]
        make_offer(api, demand_id, FIRST_OFFER_CENTS)
        make_counter(api, demand_id, FIRST_COUNTER_CENTS)
        make_offer(api, demand_id, SECOND_OFFER_CENTS)

        repeated = make_counter(api, demand_id, FIRST_COUNTER_CENTS)
        assert repeated["round_index"] == 2
        assert_cents(
            repeated["claimant_counter_cents"], FIRST_COUNTER_CENTS, "claimant_counter_cents"
        )
        assert_cents(repeated["gap_cents"], SECOND_GAP_CENTS, "gap_cents")
        assert SECOND_GAP_CENTS == FIRST_COUNTER_CENTS - SECOND_OFFER_CENTS

        at_the_demand = make_offer(api, demand_id, YELLOW_SPRINGS_DEMAND_A_CENTS)
        assert at_the_demand["round_index"] == 3

        settled = settle(api, demand_id, settlement_reference=YELLOW_SPRINGS_REFERENCE)
        assert settled["status"] == DEMAND_STATE_SETTLED
        assert_cents(
            settled["settled_amount_cents"],
            YELLOW_SPRINGS_DEMAND_A_CENTS,
            "settled_amount_cents",
        )
        assert_cents(settled["alae_cents"], YELLOW_SPRINGS_ALAE_CENTS, "alae_cents")
        assert_cents(
            settled["settlement_total_cents"],
            YELLOW_SPRINGS_TOTAL_CENTS,
            "settlement_total_cents",
        )
        assert settled["round_count"] == 3
        assert YELLOW_SPRINGS_ALAE_CENTS == int(YELLOW_SPRINGS_DEMAND_A_CENTS * 8 / 100)

        rounds, meta = validate_paginated(
            api.list_negotiation_rounds(demand_id, CLAIMS_MANAGER)
        )
        assert meta["total_count"] == 3
        assert [row["round_index"] for row in rounds] == [1, 2, 3]
        assert rounds[2]["outcome"] == ROUND_OUTCOME_ACCEPTED

    def test_the_untouched_sibling_demand_blocks_closure_of_the_claim(
        self, api: ApiClient
    ):
        """One settled demand is not enough while a sibling is still DEMANDED.

        PRD: "Every demand on the claim must have reached `SETTLED` or
        `CLOSED_PAID`; any demand still in `DEMANDED`, `OFFER_OUTSTANDING` or
        `COUNTER_OUTSTANDING` blocks closure with `ERR_OPEN_DEMANDS_REMAIN`."

        Design: Corner/validations/negotiation_ladder_refuses_regressive_offers_and_rising_counters
        """
        context = _claim_with_two_property_demands(api)
        demand_id = context["demand_a"]["id"]
        make_offer(api, demand_id, YELLOW_SPRINGS_DEMAND_A_CENTS)
        settle(api, demand_id, settlement_reference=YELLOW_SPRINGS_REFERENCE)

        validate_error(
            api.close_claim(context["claim"]["id"], headers=CLAIMS_MANAGER),
            ApiErrorId.OPEN_DEMANDS_REMAIN.value,
            422,
        )

        claim = validate_success(api.get_claim(context["claim"]["id"], CLAIMS_MANAGER))
        assert claim["handling_status"] == CLAIM_HANDLING_NEGOTIATION
        assert claim["closed_at"] is None

        sibling = validate_success(api.get_demand(context["demand_b"]["id"], CLAIMS_ADJUSTER))
        assert sibling["status"] == DEMAND_STATE_DEMANDED


ZANESVILLE_CRASH_AT = CLOCK_EPOCH
MIN_AT_FAULT_PERCENTAGE = 1
MAX_AT_FAULT_PERCENTAGE = 100
MAX_LEGAL_LIMIT = 100
MIN_LEGAL_LIMIT = 1
MIN_LEGAL_OFFSET = 0
ZANESVILLE_WAIVER = "driver hospitalised and unable to give a statement"


def _terminal_and_driver_only(api: ApiClient) -> dict:
    """A fleet with no crash yet, so the crash can be filed at the clock instant."""
    terminal = build_terminal(
        api,
        name="Zanesville East Terminal",
        terminal_code="ZAN03",
        region_code="OH",
        annual_miles_millions=1.0,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-5001",
        full_name="Tomasz Ekwueme",
        cdl_number="OH-CDL-5001",
        hire_date="2016-08-01",
    )
    return {"terminal": terminal, "driver": driver}


def _crash_at_the_current_instant(api: ApiClient, context: dict) -> dict:
    return build_crash(
        api,
        context["driver"]["id"],
        context["terminal"]["id"],
        occurred_at=ZANESVILLE_CRASH_AT,
        notified_at=ZANESVILLE_CRASH_AT,
        location_text="I-70 MM 154 westbound",
        severity=SEVERITY_MODERATE,
        route_class=ROUTE_CLASS_LINEHAUL,
        tow_away=False,
        tow_reason=TOW_REASON_NONE,
        injury_transported_count=0,
        fatality_count=0,
        hazmat_release=False,
        mechanical_factor=False,
        third_party_at_fault=True,
    )


class TestEveryBoundIsInclusiveOnItsLegalSide:
    """The exact edge of each range is accepted rather than rejected."""

    def test_a_crash_filed_at_the_current_instant_is_accepted(self, api: ApiClient):
        """A bound of "not after" leaves the instant itself legal.

        PRD: "Three temporal facts are checked before anything is created:
        `occurred_at` must not be after the current instant, `notified_at` must not
        be after the current instant, and `notified_at` must not precede
        `occurred_at`. Any of those three failing is `ERR_FUTURE_TIMESTAMP`."

        Design: Corner/validations/boundary_inputs_that_exactly_satisfy_their_bounds_are_accepted
        """
        context = _terminal_and_driver_only(api)

        crash = _crash_at_the_current_instant(api, context)

        assert_instants_equal(crash["occurred_at"], ZANESVILLE_CRASH_AT, "occurred_at")
        assert_instants_equal(crash["notified_at"], CLOCK_EPOCH, "notified_at")
        assert crash["preventability_status"] == PREVENTABILITY_REPORTED

    def test_a_waiver_reason_satisfies_the_statement_precondition_on_its_own(
        self, api: ApiClient
    ):
        """The case opens with no statement on file at all.

        PRD: "unless a driver statement already exists for the crash, a
        `statement_waiver_reason` must be supplied to explain why the committee will
        proceed without one, and a request offering neither is refused with
        `ERR_DRIVER_STATEMENT_REQUIRED`."

        Design: Corner/validations/boundary_inputs_that_exactly_satisfy_their_bounds_are_accepted
        """
        context = _terminal_and_driver_only(api)
        crash = _crash_at_the_current_instant(api, context)

        case = build_review_case(
            api,
            crash["id"],
            committee_name="Zanesville Safety Review Committee",
            statement_waiver_reason=ZANESVILLE_WAIVER,
        )

        assert case["status"] == REVIEW_STATE_DRAFT
        assert case["statement_waiver_reason"] == ZANESVILLE_WAIVER

        statements, meta = validate_paginated(
            api.list_driver_statements(crash["id"], SAFETY_MANAGER)
        )
        assert meta["total_count"] == 0
        assert statements == []

    def test_both_ends_of_the_at_fault_range_are_accepted(self, api: ApiClient):
        """One percent and one hundred percent are both inside the range.

        PRD: "the `at_fault_percentage` attributed to that party, which must be an
        integer from 1 through 100 inclusive"

        Design: Corner/validations/boundary_inputs_that_exactly_satisfy_their_bounds_are_accepted
        """
        context = _terminal_and_driver_only(api)
        crash = _crash_at_the_current_instant(api, context)
        claim = build_claim(api, crash["id"], claimant_notice_date="2026-08-01")

        low = build_subrogation_demand(
            api,
            claim["id"],
            third_party_name="Muskingum Grading LLC",
            at_fault_percentage=MIN_AT_FAULT_PERCENTAGE,
            basis_note="minimal shared fault for the debris",
        )
        high = build_subrogation_demand(
            api,
            claim["id"],
            third_party_name="Licking County Haulage",
            at_fault_percentage=MAX_AT_FAULT_PERCENTAGE,
            basis_note="entirely the other unit's failure to yield",
        )

        assert low["at_fault_percentage"] == MIN_AT_FAULT_PERCENTAGE
        assert low["status"] == SUBROGATION_STATE_DRAFT
        assert high["at_fault_percentage"] == MAX_AT_FAULT_PERCENTAGE
        assert high["status"] == SUBROGATION_STATE_DRAFT

        rows, meta = validate_paginated(
            api.list_claim_subrogation_demands(
                claim["id"],
                AUDITOR,
                {"status": SUBROGATION_STATE_DRAFT, "limit": MAX_LEGAL_LIMIT, "offset": MIN_LEGAL_OFFSET},
            )
        )
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert {row["id"] for row in rows} == {low["id"], high["id"]}

    def test_the_extreme_legal_page_windows_are_both_honoured(self, api: ApiClient):
        """A limit of 100 with an offset of 0, and a limit of 1, are all in range.

        PRD: "`limit` controls page size: it defaults to 10, may not be smaller
        than 1, and may not be larger than 100. `offset` controls the starting
        position: it defaults to 0 and may not be negative."

        Design: Corner/validations/boundary_inputs_that_exactly_satisfy_their_bounds_are_accepted
        """
        context = _terminal_and_driver_only(api)
        crash = _crash_at_the_current_instant(api, context)

        widest, wide_meta = validate_paginated(
            api.list_crashes(
                AUDITOR,
                {
                    "driver_id": context["driver"]["id"],
                    "limit": MAX_LEGAL_LIMIT,
                    "offset": MIN_LEGAL_OFFSET,
                },
            )
        )
        assert wide_meta["limit"] == MAX_LEGAL_LIMIT
        assert wide_meta["offset"] == MIN_LEGAL_OFFSET
        assert wide_meta["total_count"] == 1
        assert wide_meta["has_more"] is False
        assert [row["id"] for row in widest] == [crash["id"]]

        narrowest, narrow_meta = validate_paginated(
            api.list_crashes(AUDITOR, {"limit": MIN_LEGAL_LIMIT})
        )
        assert narrow_meta["limit"] == MIN_LEGAL_LIMIT
        assert narrow_meta["offset"] == MIN_LEGAL_OFFSET
        assert narrow_meta["total_count"] == 1
        assert narrow_meta["has_more"] is False
        assert len(narrowest) == 1


ABSENT_CRASH_ID = ABSENT_UUIDS[30]
ABSENT_DRIVER_ID = ABSENT_UUIDS[31]
ABSENT_CRASH_ID_FOR_DISCIPLINE = ABSENT_UUIDS[32]
UNDECLARED_ACTION_TYPE = "WARNING"
ADA_EVIDENCE_WINDOW = {
    "window_start_at": "2026-07-31T02:00:00Z",
    "window_end_at": "2026-07-31T04:00:00Z",
    "retention_deadline_at": "2026-12-31T00:00:00Z",
}


def _one_valid_crash_on_one_valid_driver(api: ApiClient) -> dict:
    """A wholly valid fleet, so only the ids named in each request are absent."""
    terminal = build_terminal(
        api,
        name="Ada West Terminal",
        terminal_code="ADA02",
        region_code="OH",
        annual_miles_millions=2.0,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-5101",
        full_name="Ursula Mbeki",
        cdl_number="OH-CDL-5101",
        hire_date="2017-05-05",
    )
    crash = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-07-31T03:00:00Z",
        notified_at="2026-07-31T03:30:00Z",
        location_text="SR-235 at Main St",
        severity=SEVERITY_MINOR,
        route_class=ROUTE_CLASS_LOCAL,
        tow_away=False,
        tow_reason=TOW_REASON_NONE,
        injury_transported_count=0,
        fatality_count=0,
        hazmat_release=False,
        mechanical_factor=False,
        third_party_at_fault=False,
    )
    return {"terminal": terminal, "driver": driver, "crash": crash}


def _evidence_body(**overrides) -> dict:
    return factories.evidence_payload(
        kind=EVIDENCE_TELEMATICS,
        source_device_id="ECM-X",
        **ADA_EVIDENCE_WINDOW,
        **overrides,
    )


class TestTheLadderIsWalkedOneBandAtATime:
    """Peeling the violations off a single request one by one moves the reported id down the ladder."""

    def test_authentication_outranks_the_body_shape_and_the_absent_path_id(
        self, api: ApiClient
    ):
        """A missing identity header masks every later band.

        PRD: "Requests are validated in one strict ascending order, and the
        **first** rule that is violated determines the entire response. ...
        **Authentication.** Both headers present and non-empty, with `X-User-Role`
        naming one of the eight declared roles — otherwise `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/error_ladder_reports_the_lowest_priority_rule_that_is_violated
        """
        _one_valid_crash_on_one_valid_driver(api)

        validate_error(
            api.create_evidence_item(
                ABSENT_CRASH_ID,
                _evidence_body(camera_channel=3),
                make_missing_user_id_headers(ROLE_DISPATCHER),
            ),
            ApiErrorId.UNAUTHENTICATED.value,
            401,
        )

    def test_the_unknown_field_outranks_the_absent_path_id(self, api: ApiClient):
        """With a real actor, band 4 still speaks before band 6.

        PRD: "**Request shape.** The body parses as JSON, contains no unknown
        fields, contains every required input, and every present value matches its
        declared type, enum domain and range constraint — including the pagination
        bounds on list reads. Any violation is `ERR_INVALID_REQUEST`."

        Design: Corner/validations/error_ladder_reports_the_lowest_priority_rule_that_is_violated
        """
        _one_valid_crash_on_one_valid_driver(api)

        validate_error(
            api.create_evidence_item(
                ABSENT_CRASH_ID, _evidence_body(camera_channel=3), DISPATCHER
            ),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

        validate_error(
            api.create_evidence_item(ABSENT_CRASH_ID, _evidence_body(), DISPATCHER),
            ApiErrorId.CRASH_NOT_FOUND.value,
            404,
        )

    def test_the_bad_enum_outranks_two_absent_body_references(self, api: ApiClient):
        """Band 4 covers the enum domain, so neither absent parent is reached.

        PRD: "every present value matches its declared type, enum domain and range
        constraint". And: "The `action_type` is one of `COACHING`, `RETRAINING`,
        `SUSPENSION` or `TERMINATION_RECOMMENDATION`".

        Design: Corner/validations/error_ladder_reports_the_lowest_priority_rule_that_is_violated
        """
        _one_valid_crash_on_one_valid_driver(api)

        validate_error(
            api.create_disciplinary_action(
                factories.disciplinary_action_payload(
                    ABSENT_DRIVER_ID,
                    ABSENT_CRASH_ID_FOR_DISCIPLINE,
                    action_type=UNDECLARED_ACTION_TYPE,
                    action_note="bad enum plus two absent parents",
                ),
                SAFETY_MANAGER,
            ),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

    def test_body_references_resolve_in_the_declaration_order_of_the_owning_entity(
        self, api: ApiClient
    ):
        """The driver is named first in the entity, so the driver reports first.

        PRD: "**Body reference existence.** Every foreign key supplied in the
        request body resolves to an existing row, checked in the declaration order
        of the owning entity's fields — otherwise the entity-specific not-found code
        at HTTP 404."

        Design: Corner/validations/error_ladder_reports_the_lowest_priority_rule_that_is_violated
        """
        context = _one_valid_crash_on_one_valid_driver(api)

        validate_error(
            api.create_disciplinary_action(
                factories.disciplinary_action_payload(
                    ABSENT_DRIVER_ID,
                    ABSENT_CRASH_ID_FOR_DISCIPLINE,
                    action_type=ACTION_TYPE_COACHING,
                    action_note="two absent parents",
                ),
                SAFETY_MANAGER,
            ),
            ApiErrorId.DRIVER_NOT_FOUND.value,
            404,
        )

        validate_error(
            api.create_disciplinary_action(
                factories.disciplinary_action_payload(
                    context["driver"]["id"],
                    ABSENT_CRASH_ID_FOR_DISCIPLINE,
                    action_type=ACTION_TYPE_COACHING,
                    action_note="only the crash is absent",
                ),
                SAFETY_MANAGER,
            ),
            ApiErrorId.CRASH_NOT_FOUND.value,
            404,
        )


BUCYRUS_A_WINDOW = {
    "window_start_at": "2026-07-27T10:00:00Z",
    "window_end_at": "2026-07-27T12:00:00Z",
    "retention_deadline_at": "2027-06-30T00:00:00Z",
}
BUCYRUS_ELD_WINDOW = {
    "window_start_at": "2026-07-27T00:00:00Z",
    "window_end_at": "2026-07-28T00:00:00Z",
    "retention_deadline_at": "2027-06-30T00:00:00Z",
}
BUCYRUS_B_WINDOW = {
    "window_start_at": "2026-07-28T13:00:00Z",
    "window_end_at": "2026-07-28T15:00:00Z",
    "retention_deadline_at": "2027-06-30T00:00:00Z",
}
BUCYRUS_SEVERE_POINTS = 8.0
BUCYRUS_CLEARED_POINTS = 0.0
BUCYRUS_COMMITTEE_SCORE = 3.00
BUCYRUS_AT_FAULT_PERCENTAGE = 40


def _two_drivers_one_preventable_crash_and_one_reported_crash(api: ApiClient) -> dict:
    """Driver A carries a decided preventable SEVERE crash; Driver B a bare MODERATE one.

    Crash A also keeps an ELD log that was requested and never preserved, and
    Crash B keeps a preserved scene photo that belongs to the wrong crash for any
    appeal on Crash A.
    """
    terminal = build_terminal(
        api,
        name="Bucyrus Terminal",
        terminal_code="BUC02",
        region_code="OH",
        annual_miles_millions=4.0,
    )
    driver_a = build_driver(
        api,
        terminal["id"],
        employee_code="D-5201",
        full_name="Viktor Amankwah",
        cdl_number="OH-CDL-5201",
        hire_date="2012-06-06",
    )
    driver_b = build_driver(
        api,
        terminal["id"],
        employee_code="D-5202",
        full_name="Wanda Iliescu",
        cdl_number="OH-CDL-5202",
        hire_date="2012-07-07",
    )
    crash_a = build_crash(
        api,
        driver_a["id"],
        terminal["id"],
        occurred_at="2026-07-27T11:00:00Z",
        notified_at="2026-07-27T11:20:00Z",
        location_text="US-30 at SR-4",
        severity=SEVERITY_SEVERE,
        route_class=ROUTE_CLASS_LINEHAUL,
        tow_away=False,
        tow_reason=TOW_REASON_NONE,
        injury_transported_count=0,
        fatality_count=0,
        hazmat_release=False,
        mechanical_factor=False,
        third_party_at_fault=False,
    )
    photo_a = request_evidence(
        api,
        crash_a["id"],
        kind=EVIDENCE_SCENE_PHOTO,
        source_device_id="PHONE-5201",
        **BUCYRUS_A_WINDOW,
    )
    preserve_evidence(
        api,
        photo_a["id"],
        preserved_copy_uri="s3://evidence/2923buc/scene-5201.jpg",
        evidence_hash="4d4d5e5e6f6f7a7a8b8b9c9c0d0d1e1e",
    )
    telematics_a = request_evidence(
        api,
        crash_a["id"],
        kind=EVIDENCE_TELEMATICS,
        source_device_id="ECM-5201",
        **BUCYRUS_A_WINDOW,
    )
    purge_evidence(api, telematics_a["id"], purge_reason="buffer overwritten before the hold")
    eld_a = request_evidence(
        api,
        crash_a["id"],
        kind=EVIDENCE_ELD_LOG,
        source_device_id="ELD-5201",
        **BUCYRUS_ELD_WINDOW,
    )
    build_statement(
        api,
        crash_a["id"],
        driver_a["id"],
        narrative="Traffic stopped short of the light.",
        attested=True,
    )
    case_a = build_case_in_deliberation(
        api, crash_a["id"], committee_name="Bucyrus Safety Review Committee"
    )
    cast_quorum(
        api,
        case_a,
        vote=BALLOT_DISPOSITION_PREVENTABLE,
        scores=factories.uniform_criterion_scores(3),
    )
    decided_a = decide_case(api, case_a["id"])

    crash_b = build_crash(
        api,
        driver_b["id"],
        terminal["id"],
        occurred_at="2026-07-28T14:00:00Z",
        notified_at="2026-07-28T14:10:00Z",
        location_text="SR-98 at the fairgrounds",
        severity=SEVERITY_MODERATE,
        route_class=ROUTE_CLASS_REGIONAL,
        tow_away=False,
        tow_reason=TOW_REASON_NONE,
        injury_transported_count=0,
        fatality_count=0,
        hazmat_release=False,
        mechanical_factor=False,
        third_party_at_fault=False,
    )
    photo_b = request_evidence(
        api,
        crash_b["id"],
        kind=EVIDENCE_SCENE_PHOTO,
        source_device_id="PHONE-5202",
        **BUCYRUS_B_WINDOW,
    )
    preserve_evidence(
        api,
        photo_b["id"],
        preserved_copy_uri="s3://evidence/2923buc/scene-5202.jpg",
        evidence_hash="5e5e6f6f7a7a8b8b9c9c0d0d1e1e2f2f",
    )
    claim_b = build_claim(api, crash_b["id"], claimant_notice_date="2026-07-31")

    return {
        "terminal": terminal,
        "driver_a": driver_a,
        "driver_b": driver_b,
        "crash_a": crash_a,
        "crash_b": crash_b,
        "photo_a": photo_a,
        "eld_a": eld_a,
        "photo_b": photo_b,
        "review_case_a": decided_a,
        "claim_b": claim_b,
    }


class TestGatesThatReadStateLivingOnADifferentRow:
    """Each refusal is caused by a field on a row the request never names as its target."""

    def test_the_crashs_preventability_and_the_driver_crash_pairing_gate_discipline(
        self, api: ApiClient
    ):
        """Neither defect is on the disciplinary action being created.

        PRD: "The supplied `driver_id` must be the very driver recorded on that
        crash, and a mismatch is `ERR_DRIVER_CRASH_MISMATCH`. The crash's
        `preventability_status` must be `PREVENTABLE`, and discipline arising from a
        crash that is still under review, was found non-preventable, or was never
        reviewed at all is refused with `ERR_CRASH_NOT_PREVENTABLE`."

        Design: Corner/validations/cross_entity_gates_read_the_crash_the_driver_and_the_evidence
        """
        context = _two_drivers_one_preventable_crash_and_one_reported_crash(api)
        assert context["review_case_a"]["determination"] == DETERMINATION_PREVENTABLE
        assert context["review_case_a"]["decision_basis"] == DECISION_BASIS_WEIGHTED_CRITERIA
        assert_score_2dp(
            context["review_case_a"]["committee_score"],
            BUCYRUS_COMMITTEE_SCORE,
            "committee_score",
        )
        assert context["eld_a"]["preservation_state"] == PRESERVATION_REQUESTED

        crash_a = validate_success(api.get_crash(context["crash_a"]["id"], SAFETY_MANAGER))
        assert crash_a["evidence_posture"] == EVIDENCE_POSTURE_COMPROMISED

        validate_error(
            api.create_disciplinary_action(
                factories.disciplinary_action_payload(
                    context["driver_b"]["id"],
                    context["crash_b"]["id"],
                    action_type=ACTION_TYPE_COACHING,
                    action_note="crash was never determined preventable",
                ),
                SAFETY_MANAGER,
            ),
            ApiErrorId.CRASH_NOT_PREVENTABLE.value,
            409,
        )
        validate_error(
            api.create_disciplinary_action(
                factories.disciplinary_action_payload(
                    context["driver_b"]["id"],
                    context["crash_a"]["id"],
                    action_type=ACTION_TYPE_COACHING,
                    action_note="wrong driver for this crash",
                ),
                SAFETY_MANAGER,
            ),
            ApiErrorId.DRIVER_CRASH_MISMATCH.value,
            409,
        )

        rows, meta = validate_paginated(
            api.list_disciplinary_actions(
                SAFETY_MANAGER, {"driver_id": context["driver_b"]["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert rows == []

    def test_the_drivers_computed_tier_gates_the_action_weight_and_the_separation(
        self, api: ApiClient
    ):
        """The gate is a derived field on the driver, not an input to either request.

        PRD: "the chosen action's rank must be at least as high as the driver's
        required tier's rank — where none is below coaching. A manager who offers
        coaching to a driver whose points already demand suspension is refused with
        `ERR_ACTION_TIER_INSUFFICIENT`". And: "A `SEPARATE` decision is refused
        unless the driver's `required_action_tier` currently reads
        `TERMINATION_REVIEW` ... and the refusal is
        `ERR_SEPARATION_NOT_SUPPORTED`."

        Design: Corner/validations/cross_entity_gates_read_the_crash_the_driver_and_the_evidence
        """
        context = _two_drivers_one_preventable_crash_and_one_reported_crash(api)
        driver_id = context["driver_a"]["id"]
        earned = validate_success(api.get_driver(driver_id, SAFETY_MANAGER))
        assert_points_1dp(
            earned["preventable_points"], BUCYRUS_SEVERE_POINTS, "preventable_points"
        )
        assert earned["required_action_tier"] == ACTION_TIER_SUSPENSION

        validate_error(
            api.create_disciplinary_action(
                factories.disciplinary_action_payload(
                    driver_id,
                    context["crash_a"]["id"],
                    action_type=ACTION_TYPE_COACHING,
                    action_note="too light for an 8.0-point driver",
                ),
                SAFETY_MANAGER,
            ),
            ApiErrorId.ACTION_TIER_INSUFFICIENT.value,
            422,
        )
        validate_error(
            api.decide_employment(
                driver_id,
                factories.employment_decision_payload(
                    decision=EMPLOYMENT_DECISION_SEPARATE,
                    decision_note="attempting separation at the SUSPENSION tier",
                ),
                SAFETY_MANAGER,
            ),
            ApiErrorId.SEPARATION_NOT_SUPPORTED.value,
            409,
        )

        unmoved = validate_success(api.get_driver(driver_id, SAFETY_MANAGER))
        assert unmoved["status"] == DRIVER_STATUS_ACTIVE
        assert unmoved["continued_employment_decision"] == EMPLOYMENT_DECISION_PENDING
        assert unmoved["version"] == earned["version"]

    def test_the_third_party_flag_two_hops_away_gates_the_recovery_file(
        self, api: ApiClient
    ):
        """The flag sits on the crash, and the request names only the claim.

        PRD: "It is permitted only when the underlying crash's
        `third_party_at_fault` is true; a crash that alleges no third-party fault
        answers `ERR_NO_THIRD_PARTY_AT_FAULT`."

        Design: Corner/validations/cross_entity_gates_read_the_crash_the_driver_and_the_evidence
        """
        context = _two_drivers_one_preventable_crash_and_one_reported_crash(api)
        assert context["crash_b"]["third_party_at_fault"] is False

        validate_error(
            api.create_subrogation_demand(
                context["claim_b"]["id"],
                factories.subrogation_demand_payload(
                    third_party_name="Crawford County Fair Board",
                    at_fault_percentage=BUCYRUS_AT_FAULT_PERCENTAGE,
                    basis_note="no third party was ever at fault here",
                ),
                CLAIMS_ADJUSTER,
            ),
            ApiErrorId.NO_THIRD_PARTY_AT_FAULT.value,
            409,
        )

        rows, meta = validate_paginated(
            api.list_claim_subrogation_demands(context["claim_b"]["id"], CLAIMS_ADJUSTER)
        )
        assert meta["total_count"] == 0
        assert rows == []

    def test_a_cited_appeal_artifact_must_be_this_crashs_and_currently_preserved(
        self, api: ApiClient
    ):
        """Both halves of the citation rule are checked, and the same id reports each.

        PRD: "a `NEW_EVIDENCE` appeal must cite `appeal_evidence_item_id`; that item
        must resolve or the response is `ERR_EVIDENCE_ITEM_NOT_FOUND`, and it must
        belong to the case's own crash and be in `PRESERVED` state or the response
        is `ERR_APPEAL_EVIDENCE_INVALID`."

        Design: Corner/validations/cross_entity_gates_read_the_crash_the_driver_and_the_evidence
        """
        context = _two_drivers_one_preventable_crash_and_one_reported_crash(api)
        case_id = context["review_case_a"]["id"]

        validate_error(
            api.appeal_review_case(
                case_id,
                factories.appeal_payload(
                    appeal_grounds="dash footage from the other crash shows the light cycle",
                    appeal_grounds_code=APPEAL_CODE_NEW_EVIDENCE,
                    appeal_evidence_item_id=context["photo_b"]["id"],
                ),
                APPEALS_MANAGER,
            ),
            ApiErrorId.APPEAL_EVIDENCE_INVALID.value,
            409,
        )
        validate_error(
            api.appeal_review_case(
                case_id,
                factories.appeal_payload(
                    appeal_grounds="the ELD log will show the hours were legal",
                    appeal_grounds_code=APPEAL_CODE_NEW_EVIDENCE,
                    appeal_evidence_item_id=context["eld_a"]["id"],
                ),
                APPEALS_MANAGER,
            ),
            ApiErrorId.APPEAL_EVIDENCE_INVALID.value,
            409,
        )

        granted = grant_appeal(
            api,
            case_id,
            appeal_grounds="the preserved scene photo shows the queue was already stopped",
            appeal_grounds_code=APPEAL_CODE_NEW_EVIDENCE,
            appeal_evidence_item_id=context["photo_a"]["id"],
        )
        assert granted["status"] == REVIEW_STATE_DELIBERATION
        assert granted["appeal_round"] == 1
        assert granted["determination"] == DETERMINATION_PENDING
        assert granted["appeal_evidence_item_id"] == context["photo_a"]["id"]

        cleared = validate_success(api.get_driver(context["driver_a"]["id"], SAFETY_MANAGER))
        assert_points_1dp(
            cleared["preventable_points"], BUCYRUS_CLEARED_POINTS, "preventable_points"
        )
        assert cleared["required_action_tier"] == ACTION_TIER_NONE
        assert cleared["status"] == DRIVER_STATUS_ACTIVE


CELINA_DEMAND_P_CENTS = 500_000
CELINA_DEMAND_Q_CENTS = 400_000
CELINA_ALAE_P_CENTS = 40_000
CELINA_ALAE_Q_CENTS = 32_000
CELINA_TOTAL_P_CENTS = 540_000
CELINA_TOTAL_Q_CENTS = 432_000
CELINA_PROVISIONAL_RESERVE_CENTS = 2_500_000
CELINA_OUTSTANDING_BOTH_SETTLED_CENTS = 1_528_000
CELINA_OUTSTANDING_AFTER_RESCISSION_CENTS = 2_068_000
CELINA_REFERENCE_P = "SET-2026-CEL02-0001"
CELINA_REFERENCE_Q = "SET-2026-CEL02-0002"
RESCISSION_DEADLINE = "2026-08-08T00:00:00Z"
ONE_SECOND_PAST_RESCISSION_DEADLINE = "2026-08-08T00:00:01Z"
APPEAL_DEADLINE = "2026-08-15T00:00:00Z"
ONE_SECOND_PAST_APPEAL_DEADLINE = "2026-08-15T00:00:01Z"
CELINA_UNANIMOUS_LOW_SCORE = 1.00


def _celina_fleet(api: ApiClient) -> dict:
    """One terminal, one long-tenured driver and a single-layer 2026 tower."""
    terminal = build_terminal(
        api,
        name="Celina Terminal",
        terminal_code="CEL02",
        region_code="OH",
        annual_miles_millions=6.0,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-5301",
        full_name="Xiulan Berthold",
        cdl_number="OH-CDL-5301",
        hire_date="2013-09-09",
    )
    build_policy_layer(
        api,
        program_year=2026,
        layer_index=1,
        layer_type=LAYER_KIND_SIR,
        attachment_point_cents=0,
        limit_cents=10_000_000,
        insurer_name="Self-insured retention",
    )
    return {"terminal": terminal, "driver": driver}


def _two_demands_settled_at_the_clock_epoch(api: ApiClient) -> dict:
    """Two property demands on one claim, each settled at its own full amount.

    Both settlements land at the epoch, so both rescission windows shut at the
    same instant and the pair can be probed from either side of it.
    """
    fleet = _celina_fleet(api)
    crash = build_crash(
        api,
        fleet["driver"]["id"],
        fleet["terminal"]["id"],
        occurred_at="2026-07-26T08:00:00Z",
        notified_at="2026-07-26T08:20:00Z",
        location_text="SR-29 at Havemann Rd",
        severity=SEVERITY_MODERATE,
        route_class=ROUTE_CLASS_REGIONAL,
        tow_away=False,
        tow_reason=TOW_REASON_NONE,
        injury_transported_count=0,
        fatality_count=0,
        hazmat_release=False,
        mechanical_factor=False,
        third_party_at_fault=False,
    )
    claim = build_claim(api, crash["id"], claimant_notice_date="2026-07-28")
    demand_p = build_demand(
        api,
        claim["id"],
        claimant_name="Havemann Road Orchard",
        claimant_type=CLAIMANT_TYPE_PROPERTY,
        demand_amount_cents=CELINA_DEMAND_P_CENTS,
        represented_by_counsel=False,
        demand_received_at="2026-07-29T09:00:00Z",
    )
    demand_q = build_demand(
        api,
        claim["id"],
        claimant_name="Mercer County Signs",
        claimant_type=CLAIMANT_TYPE_PROPERTY,
        demand_amount_cents=CELINA_DEMAND_Q_CENTS,
        represented_by_counsel=False,
        demand_received_at="2026-07-29T09:30:00Z",
    )
    round_p = make_offer(api, demand_p["id"], CELINA_DEMAND_P_CENTS)
    make_offer(api, demand_q["id"], CELINA_DEMAND_Q_CENTS)
    settled_p = settle(api, demand_p["id"], settlement_reference=CELINA_REFERENCE_P)
    settled_q = settle(api, demand_q["id"], settlement_reference=CELINA_REFERENCE_Q)
    return {
        "crash": crash,
        "claim": claim,
        "demand_p": demand_p,
        "demand_q": demand_q,
        "round_p": round_p,
        "settled_p": settled_p,
        "settled_q": settled_q,
    }


def _two_cases_decided_non_preventable(api: ApiClient) -> dict:
    """Two moderate crashes decided against the criteria rule on all-one ballots.

    Each crash keeps a purged telematics snapshot, so the posture is COMPROMISED
    and the decision runs on WEIGHTED_CRITERIA; five ones renormalise to exactly
    1.00, which is below the 2.50 threshold, so neither determination leaves any
    discipline outstanding to interfere with the appeal windows.
    """
    fleet = _celina_fleet(api)
    cases = []
    for suffix, occurred_at, notified_at, location, narrative in (
        (
            "A",
            "2026-07-26T12:00:00Z",
            "2026-07-26T12:20:00Z",
            "US-127 at Wabash Rd",
            "The pickup pulled out of the field lane.",
        ),
        (
            "B",
            "2026-07-26T16:00:00Z",
            "2026-07-26T16:20:00Z",
            "SR-703 at the lake spillway",
            "Wet leaves on the spillway apron.",
        ),
    ):
        crash = build_crash(
            api,
            fleet["driver"]["id"],
            fleet["terminal"]["id"],
            occurred_at=occurred_at,
            notified_at=notified_at,
            location_text=location,
            severity=SEVERITY_MODERATE,
            route_class=ROUTE_CLASS_REGIONAL,
            tow_away=False,
            tow_reason=TOW_REASON_NONE,
            injury_transported_count=0,
            fatality_count=0,
            hazmat_release=False,
            mechanical_factor=False,
            third_party_at_fault=False,
        )
        window = {
            "window_start_at": shift_instant(occurred_at, hours=-1),
            "window_end_at": shift_instant(occurred_at, hours=1),
            "retention_deadline_at": "2027-06-30T00:00:00Z",
        }
        photo = request_evidence(
            api,
            crash["id"],
            kind=EVIDENCE_SCENE_PHOTO,
            source_device_id=f"PHONE-5301-{suffix}",
            **window,
        )
        preserve_evidence(
            api,
            photo["id"],
            preserved_copy_uri=f"s3://evidence/2923cel/scene-5301{suffix.lower()}.jpg",
            evidence_hash="6f6f7a7a8b8b9c9c0d0d1e1e2f2f3a3a",
        )
        snapshot = request_evidence(
            api,
            crash["id"],
            kind=EVIDENCE_TELEMATICS,
            source_device_id=f"ECM-5301-{suffix}",
            **window,
        )
        purge_evidence(api, snapshot["id"], purge_reason="download window missed")
        build_statement(
            api, crash["id"], fleet["driver"]["id"], narrative=narrative, attested=True
        )
        case = build_case_in_deliberation(
            api, crash["id"], committee_name="Celina Safety Review Committee"
        )
        cast_quorum(
            api,
            case,
            vote=BALLOT_DISPOSITION_NON_PREVENTABLE,
            scores=factories.uniform_criterion_scores(1),
        )
        cases.append(decide_case(api, case["id"]))
    return {"case_a": cases[0], "case_b": cases[1]}


class TestBothCompensatingWindowsAreClosedIntervals:
    """Each window is probed at its exact deadline and one second past it."""

    def test_a_rescission_at_exactly_one_hundred_sixty_eight_hours_still_lands(
        self, api: ApiClient
    ):
        """The seven-day bound is `<=`, so the deadline instant itself is legal.

        PRD: "only while the current logical instant is no later than the demand's
        `settled_at` plus 168 hours — seven days; the boundary is inclusive, so a
        rescission at exactly 168 hours after `settled_at` is allowed and one
        instant later is `ERR_RESCISSION_WINDOW_CLOSED`."

        Design: Corner/validations/temporal_windows_are_inclusive_at_the_deadline_and_shut_one_second_later
        """
        context = _two_demands_settled_at_the_clock_epoch(api)
        assert_instants_equal(context["settled_p"]["settled_at"], CLOCK_EPOCH, "settled_at P")
        assert_instants_equal(context["settled_q"]["settled_at"], CLOCK_EPOCH, "settled_at Q")
        assert context["settled_p"]["rescission_count"] == 0
        assert_cents(
            context["settled_p"]["settlement_total_cents"],
            CELINA_TOTAL_P_CENTS,
            "settlement_total_cents P",
        )
        assert_cents(
            context["settled_q"]["settlement_total_cents"],
            CELINA_TOTAL_Q_CENTS,
            "settlement_total_cents Q",
        )

        set_clock(api, RESCISSION_DEADLINE)
        rescinded = rescind(
            api,
            context["demand_p"]["id"],
            rescission_reason="claimant's release was never signed",
        )

        assert rescinded["status"] == DEMAND_STATE_OFFER_OUTSTANDING
        assert rescinded["rescission_count"] == 1
        assert rescinded["settled_at"] is None
        assert rescinded["settled_amount_cents"] is None
        assert rescinded["alae_cents"] is None
        assert rescinded["settlement_total_cents"] is None
        assert rescinded["settlement_reference"] is None

        rounds, _ = validate_paginated(
            api.list_negotiation_rounds(context["demand_p"]["id"], CLAIMS_MANAGER)
        )
        standing = [row for row in rounds if row["id"] == context["round_p"]["id"]]
        assert len(standing) == 1
        assert standing[0]["outcome"] == ROUND_OUTCOME_OPEN

    def test_the_rescission_returns_the_money_without_moving_the_exposure(
        self, api: ApiClient
    ):
        """The claim ledger is restored to exactly its pre-settlement figures.

        PRD: "the rescinded indemnity and expense are returned from
        `indemnity_paid_cents` and `alae_paid_cents` to
        `outstanding_reserve_cents`, leaving `claim_exposure_cents` unchanged ...
        the claim moves `SETTLEMENT_COMPLETE → NEGOTIATION`"

        Design: Corner/validations/temporal_windows_are_inclusive_at_the_deadline_and_shut_one_second_later
        """
        context = _two_demands_settled_at_the_clock_epoch(api)
        before = validate_success(api.get_claim(context["claim"]["id"], CLAIMS_MANAGER))
        assert before["handling_status"] == CLAIM_HANDLING_SETTLEMENT_COMPLETE
        assert_cents(
            before["provisional_reserve_cents"],
            CELINA_PROVISIONAL_RESERVE_CENTS,
            "provisional_reserve_cents",
        )
        assert_cents(
            before["outstanding_reserve_cents"],
            CELINA_OUTSTANDING_BOTH_SETTLED_CENTS,
            "outstanding_reserve_cents",
        )

        set_clock(api, RESCISSION_DEADLINE)
        rescind(
            api,
            context["demand_p"]["id"],
            rescission_reason="claimant's release was never signed",
        )

        after = validate_success(api.get_claim(context["claim"]["id"], CLAIMS_MANAGER))
        assert after["handling_status"] == CLAIM_HANDLING_NEGOTIATION
        assert_cents(
            after["indemnity_paid_cents"], CELINA_DEMAND_Q_CENTS, "indemnity_paid_cents"
        )
        assert_cents(after["alae_paid_cents"], CELINA_ALAE_Q_CENTS, "alae_paid_cents")
        assert_cents(
            after["outstanding_reserve_cents"],
            CELINA_OUTSTANDING_AFTER_RESCISSION_CENTS,
            "outstanding_reserve_cents",
        )
        assert_cents(
            after["claim_exposure_cents"],
            CELINA_PROVISIONAL_RESERVE_CENTS,
            "claim_exposure_cents",
        )
        assert_cents(after["sir_eroded_cents"], CELINA_TOTAL_Q_CENTS, "sir_eroded_cents")
        assert len(after["layer_allocations"]) == 1
        assert_cents(
            after["layer_allocations"][0]["allocated_cents"],
            CELINA_TOTAL_Q_CENTS,
            "allocated_cents",
        )

    def test_a_rescission_one_second_past_the_deadline_is_refused(self, api: ApiClient):
        """The same request one second later leaves the settlement untouched.

        PRD: "a rescission at exactly 168 hours after `settled_at` is allowed and
        one instant later is `ERR_RESCISSION_WINDOW_CLOSED`."

        Design: Corner/validations/temporal_windows_are_inclusive_at_the_deadline_and_shut_one_second_later
        """
        context = _two_demands_settled_at_the_clock_epoch(api)
        set_clock(api, ONE_SECOND_PAST_RESCISSION_DEADLINE)

        validate_error(
            api.rescind_settlement(
                context["demand_q"]["id"],
                factories.rescind_payload(rescission_reason="one second too late"),
                CLAIMS_MANAGER,
            ),
            ApiErrorId.RESCISSION_WINDOW_CLOSED.value,
            409,
        )

        unmoved = validate_success(api.get_demand(context["demand_q"]["id"], CLAIMS_MANAGER))
        assert unmoved["status"] == DEMAND_STATE_SETTLED
        assert unmoved["rescission_count"] == 0
        assert_instants_equal(unmoved["settled_at"], CLOCK_EPOCH, "settled_at")
        assert unmoved["settlement_reference"] == CELINA_REFERENCE_Q
        assert unmoved["version"] == context["settled_q"]["version"]

    def test_an_appeal_at_exactly_fourteen_days_still_reopens_the_case(
        self, api: ApiClient
    ):
        """A bound of "no later than 14 days" leaves that day's instant legal.

        PRD: "The appeal must be filed no later than 14 days after `decided_at`,
        and one filed after that window is `ERR_APPEAL_WINDOW_CLOSED`."

        Design: Corner/validations/temporal_windows_are_inclusive_at_the_deadline_and_shut_one_second_later
        """
        context = _two_cases_decided_non_preventable(api)
        case_a = context["case_a"]
        assert_instants_equal(case_a["decided_at"], CLOCK_EPOCH, "decided_at")
        assert case_a["determination"] == DETERMINATION_NON_PREVENTABLE
        assert context["case_b"]["determination"] == DETERMINATION_NON_PREVENTABLE
        assert case_a["decision_basis"] == DECISION_BASIS_WEIGHTED_CRITERIA
        assert_score_2dp(
            case_a["committee_score"], CELINA_UNANIMOUS_LOW_SCORE, "committee_score"
        )

        set_clock(api, APPEAL_DEADLINE)
        appealed = grant_appeal(
            api,
            case_a["id"],
            appeal_grounds="the committee applied the wrong following-distance criterion",
            appeal_grounds_code=APPEAL_CODE_CRITERIA_MISAPPLICATION,
        )

        assert appealed["status"] == REVIEW_STATE_DELIBERATION
        assert appealed["appeal_round"] == 1
        assert appealed["determination"] == DETERMINATION_PENDING

    def test_an_appeal_one_second_past_the_deadline_is_closed_not_exhausted(
        self, api: ApiClient
    ):
        """The refusal names the window, not the untouched appeal allowance.

        PRD: "The crash's `appeals_exhausted` must be false and the case's
        `appeal_round` must still be below the maximum of 1 ... The appeal must be
        filed no later than 14 days after `decided_at`, and one filed after that
        window is `ERR_APPEAL_WINDOW_CLOSED`."

        Design: Corner/validations/temporal_windows_are_inclusive_at_the_deadline_and_shut_one_second_later
        """
        context = _two_cases_decided_non_preventable(api)
        case_b = context["case_b"]
        set_clock(api, ONE_SECOND_PAST_APPEAL_DEADLINE)

        validate_error(
            api.appeal_review_case(
                case_b["id"],
                factories.appeal_payload(
                    appeal_grounds="the same criterion argument, filed one second late",
                    appeal_grounds_code=APPEAL_CODE_CRITERIA_MISAPPLICATION,
                ),
                APPEALS_MANAGER,
            ),
            ApiErrorId.APPEAL_WINDOW_CLOSED.value,
            409,
        )

        unmoved = validate_success(api.get_review_case(case_b["id"], AUDITOR))
        assert unmoved["status"] == REVIEW_STATE_DECIDED
        assert unmoved["appeal_round"] == 0
        assert unmoved["determination"] == DETERMINATION_NON_PREVENTABLE
        assert unmoved["version"] == case_b["version"]


DEFIANCE_PROVISIONAL_RESERVE_CENTS = 2_500_000
DEFIANCE_DEMAND_A_CENTS = 1_500_000
DEFIANCE_DEMAND_B_CENTS = 1_200_000
DEFIANCE_OFFER_A_CENTS = 1_500_000
DEFIANCE_OFFER_B_CENTS = 1_000_000
DEFIANCE_TOTAL_A_CENTS = 1_620_000
DEFIANCE_TOTAL_B_CENTS = 1_080_000
DEFIANCE_OUTSTANDING_AFTER_A_CENTS = 880_000
DEFIANCE_REVISED_RESERVE_CENTS = 2_820_000
DEFIANCE_OUTSTANDING_AFTER_REVISION_CENTS = 1_200_000
DEFIANCE_INDEMNITY_PAID_CENTS = 2_500_000
DEFIANCE_ALAE_PAID_CENTS = 200_000
DEFIANCE_OUTSTANDING_FINAL_CENTS = 120_000
DEFIANCE_INCURRED_FINAL_CENTS = 2_820_000
DEFIANCE_SIR_ERODED_CENTS = 2_700_000
DEFIANCE_SIR_LIMIT_CENTS = 10_000_000
DEFIANCE_REFERENCE_A = "SET-2026-DEF02-0001"
DEFIANCE_REFERENCE_B_REFUSED = "SET-2026-DEF02-0002"
DEFIANCE_REFERENCE_B = "SET-2026-DEF02-0003"


def _claim_with_two_offered_demands(api: ApiClient) -> dict:
    """A 2,500,000 provisional reserve facing two demands that each fit alone.

    The single 10,000,000 retention layer is far larger than anything settled
    here, so the coverage guard that outranks the reserve guard never binds.
    """
    terminal = build_terminal(
        api,
        name="Defiance Terminal",
        terminal_code="DEF02",
        region_code="OH",
        annual_miles_millions=3.0,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-5401",
        full_name="Yusuf Kirchner",
        cdl_number="OH-CDL-5401",
        hire_date="2015-10-10",
    )
    build_policy_layer(
        api,
        program_year=2026,
        layer_index=1,
        layer_type=LAYER_KIND_SIR,
        attachment_point_cents=0,
        limit_cents=DEFIANCE_SIR_LIMIT_CENTS,
        insurer_name="Self-insured retention",
    )
    crash = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-07-29T18:00:00Z",
        notified_at="2026-07-29T18:15:00Z",
        location_text="US-24 at Clinton St",
        severity=SEVERITY_MODERATE,
        route_class=ROUTE_CLASS_LINEHAUL,
        tow_away=False,
        tow_reason=TOW_REASON_NONE,
        injury_transported_count=0,
        fatality_count=0,
        hazmat_release=False,
        mechanical_factor=False,
        third_party_at_fault=False,
    )
    claim = build_claim(api, crash["id"], claimant_notice_date="2026-07-30")
    demand_a = build_demand(
        api,
        claim["id"],
        claimant_name="Clinton Street Motors",
        claimant_type=CLAIMANT_TYPE_PROPERTY,
        demand_amount_cents=DEFIANCE_DEMAND_A_CENTS,
        represented_by_counsel=False,
        demand_received_at="2026-07-30T10:00:00Z",
    )
    make_offer(api, demand_a["id"], DEFIANCE_OFFER_A_CENTS)
    demand_b = build_demand(
        api,
        claim["id"],
        claimant_name="Maumee Valley Freight",
        claimant_type=CLAIMANT_TYPE_PROPERTY,
        demand_amount_cents=DEFIANCE_DEMAND_B_CENTS,
        represented_by_counsel=False,
        demand_received_at="2026-07-30T10:30:00Z",
    )
    make_offer(api, demand_b["id"], DEFIANCE_OFFER_B_CENTS)
    return {"crash": crash, "claim": claim, "demand_a": demand_a, "demand_b": demand_b}


class TestTheReserveGuardReadsWhatIsLeftNotWhatWasSetUp:
    """Two settlements that each fit the original reserve do not both fit the file."""

    def test_the_second_settlement_is_refused_on_the_remaining_reserve(
        self, api: ApiClient
    ):
        """1,080,000 is far below 2,500,000 yet above the 880,000 still unspent.

        PRD: "the claim's `outstanding_reserve_cents` must be greater than or equal
        to `settlement_total_cents`, because money must be reserved before it is
        paid, and a shortfall is `ERR_RESERVE_INSUFFICIENT`."

        Design: Corner/validations/cumulative_settlements_outrun_a_reserve_that_each_one_fits_inside
        """
        context = _claim_with_two_offered_demands(api)
        assert_cents(
            context["claim"]["provisional_reserve_cents"],
            DEFIANCE_PROVISIONAL_RESERVE_CENTS,
            "provisional_reserve_cents",
        )

        settled_a = settle(
            api, context["demand_a"]["id"], settlement_reference=DEFIANCE_REFERENCE_A
        )
        assert_cents(
            settled_a["settlement_total_cents"],
            DEFIANCE_TOTAL_A_CENTS,
            "settlement_total_cents A",
        )

        midway = validate_success(api.get_claim(context["claim"]["id"], CLAIMS_ADJUSTER))
        assert_cents(
            midway["outstanding_reserve_cents"],
            DEFIANCE_OUTSTANDING_AFTER_A_CENTS,
            "outstanding_reserve_cents",
        )
        assert_cents(
            midway["total_incurred_cents"],
            DEFIANCE_PROVISIONAL_RESERVE_CENTS,
            "total_incurred_cents",
        )
        assert midway["reserve_status"] == RESERVE_STATUS_PROVISIONAL

        validate_error(
            api.settle_demand(
                context["demand_b"]["id"],
                factories.settle_payload(
                    settlement_reference=DEFIANCE_REFERENCE_B_REFUSED
                ),
                CLAIMS_MANAGER,
            ),
            ApiErrorId.RESERVE_INSUFFICIENT.value,
            422,
        )
        assert DEFIANCE_TOTAL_B_CENTS < DEFIANCE_PROVISIONAL_RESERVE_CENTS
        assert DEFIANCE_TOTAL_B_CENTS > DEFIANCE_OUTSTANDING_AFTER_A_CENTS

        refused = validate_success(api.get_demand(context["demand_b"]["id"], CLAIMS_ADJUSTER))
        assert refused["status"] == DEMAND_STATE_OFFER_OUTSTANDING
        assert refused["settlement_total_cents"] is None
        assert refused["settled_at"] is None

        after = validate_success(api.get_claim(context["claim"]["id"], CLAIMS_ADJUSTER))
        assert_cents(
            after["indemnity_paid_cents"], DEFIANCE_OFFER_A_CENTS, "indemnity_paid_cents"
        )
        assert_cents(
            after["outstanding_reserve_cents"],
            DEFIANCE_OUTSTANDING_AFTER_A_CENTS,
            "outstanding_reserve_cents",
        )
        assert after["version"] == midway["version"]

    def test_only_a_demand_weighted_revision_makes_room_for_the_second(
        self, api: ApiClient
    ):
        """The revision weights the settled total against the still-open demand.

        PRD: "Under `DEMAND_BASED` the gross figure is the sum over the claim's
        demands of, for each demand, its `settlement_total_cents` when the demand
        is `SETTLED` or `CLOSED_PAID` and its `demand_amount_cents` otherwise"

        Design: Corner/validations/cumulative_settlements_outrun_a_reserve_that_each_one_fits_inside
        """
        context = _claim_with_two_offered_demands(api)
        settle(api, context["demand_a"]["id"], settlement_reference=DEFIANCE_REFERENCE_A)
        observed = validate_success(api.get_claim(context["claim"]["id"], CLAIMS_ADJUSTER))

        revised = revise_reserve(
            api,
            context["claim"]["id"],
            observed["version"],
            basis=RESERVE_BASIS_DEMAND_BASED,
            revision_note="weight the settled total against the open demand",
        )

        assert revised["reserve_status"] == RESERVE_STATUS_REVISED
        assert_cents(
            revised["revised_reserve_cents"],
            DEFIANCE_REVISED_RESERVE_CENTS,
            "revised_reserve_cents",
        )
        assert (
            DEFIANCE_TOTAL_A_CENTS + DEFIANCE_DEMAND_B_CENTS
            == DEFIANCE_REVISED_RESERVE_CENTS
        )
        assert_cents(
            revised["outstanding_reserve_cents"],
            DEFIANCE_OUTSTANDING_AFTER_REVISION_CENTS,
            "outstanding_reserve_cents",
        )
        assert_cents(
            revised["provisional_reserve_cents"],
            DEFIANCE_PROVISIONAL_RESERVE_CENTS,
            "provisional_reserve_cents",
        )

    def test_the_identical_settlement_lands_once_the_reserve_covers_it(
        self, api: ApiClient
    ):
        """Nothing about the settlement changed except the room left for it.

        PRD: "The claim moves the indemnity into `indemnity_paid_cents` and the
        expense into `alae_paid_cents`, reduces `outstanding_reserve_cents` by
        exactly `settlement_total_cents`"

        Design: Corner/validations/cumulative_settlements_outrun_a_reserve_that_each_one_fits_inside
        """
        context = _claim_with_two_offered_demands(api)
        settle(api, context["demand_a"]["id"], settlement_reference=DEFIANCE_REFERENCE_A)
        observed = validate_success(api.get_claim(context["claim"]["id"], CLAIMS_ADJUSTER))
        revise_reserve(
            api,
            context["claim"]["id"],
            observed["version"],
            basis=RESERVE_BASIS_DEMAND_BASED,
            revision_note="weight the settled total against the open demand",
        )

        settled_b = settle(
            api, context["demand_b"]["id"], settlement_reference=DEFIANCE_REFERENCE_B
        )
        assert settled_b["status"] == DEMAND_STATE_SETTLED
        assert_cents(
            settled_b["settlement_total_cents"],
            DEFIANCE_TOTAL_B_CENTS,
            "settlement_total_cents B",
        )

        final = validate_success(api.get_claim(context["claim"]["id"], CLAIMS_ADJUSTER))
        assert final["handling_status"] == CLAIM_HANDLING_SETTLEMENT_COMPLETE
        assert_cents(
            final["indemnity_paid_cents"],
            DEFIANCE_INDEMNITY_PAID_CENTS,
            "indemnity_paid_cents",
        )
        assert_cents(final["alae_paid_cents"], DEFIANCE_ALAE_PAID_CENTS, "alae_paid_cents")
        assert_cents(
            final["outstanding_reserve_cents"],
            DEFIANCE_OUTSTANDING_FINAL_CENTS,
            "outstanding_reserve_cents",
        )
        assert_cents(
            final["total_incurred_cents"],
            DEFIANCE_INCURRED_FINAL_CENTS,
            "total_incurred_cents",
        )
        assert_cents(final["sir_eroded_cents"], DEFIANCE_SIR_ERODED_CENTS, "sir_eroded_cents")
        assert final["sir_eroded_cents"] < DEFIANCE_SIR_LIMIT_CENTS
        assert_cents(final["insured_paid_cents"], 0, "insured_paid_cents")


ELYRIA_AT_FAULT_PERCENTAGE = 60
ELYRIA_RECOVERED_CENTS = 100_000
ELYRIA_COURSE_CODE = "CENTRE-101"
ELYRIA_SUSPENSION_START = "2026-08-03T00:00:00Z"
ELYRIA_SUSPENSION_END = "2026-08-05T00:00:00Z"
FOUR_OF_THE_FIVE_CRITERIA = {
    "speed_and_spacing": 2,
    "hazard_recognition": 2,
    "regulatory_compliance": 2,
    "evasive_action": 2,
}


def _deliberating_case_and_draft_recovery(api: ApiClient) -> dict:
    """A crash still under review, its open ballot box and a DRAFT recovery file.

    Every discriminated request below would also fail a later band — discipline on
    a crash that is not preventable, resolution of a recovery still in DRAFT, an
    appeal against a case that is not DECIDED — so the reported error proves which
    band ran first.
    """
    terminal = build_terminal(
        api,
        name="Elyria South Terminal",
        terminal_code="ELY02",
        region_code="OH",
        annual_miles_millions=5.0,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-5501",
        full_name="Zofia Nakamura",
        cdl_number="OH-CDL-5501",
        hire_date="2014-11-11",
    )
    crash = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-07-30T20:00:00Z",
        notified_at="2026-07-30T20:15:00Z",
        location_text="SR-57 at Chestnut Ridge",
        severity=SEVERITY_MODERATE,
        route_class=ROUTE_CLASS_REGIONAL,
        tow_away=False,
        tow_reason=TOW_REASON_NONE,
        injury_transported_count=0,
        fatality_count=0,
        hazmat_release=False,
        mechanical_factor=False,
        third_party_at_fault=True,
    )
    snapshot = request_evidence(
        api,
        crash["id"],
        kind=EVIDENCE_TELEMATICS,
        source_device_id="ECM-5501",
        window_start_at="2026-07-30T19:00:00Z",
        window_end_at="2026-07-30T21:00:00Z",
        retention_deadline_at="2027-06-30T00:00:00Z",
    )
    preserve_evidence(
        api,
        snapshot["id"],
        preserved_copy_uri="s3://evidence/2923ely/ecm-5501.json",
        evidence_hash="8b8b9c9c0d0d1e1e2f2f3a3a4b4b5c5c",
    )
    camera = request_evidence(
        api,
        crash["id"],
        kind=EVIDENCE_FORWARD_CAMERA,
        source_device_id="CAM-5501",
        window_start_at="2026-07-30T19:30:00Z",
        window_end_at="2026-07-30T20:30:00Z",
        retention_deadline_at="2027-06-30T00:00:00Z",
    )
    preserve_evidence(
        api,
        camera["id"],
        preserved_copy_uri="s3://evidence/2923ely/cam-5501.mp4",
        evidence_hash="9c9c0d0d1e1e2f2f3a3a4b4b5c5c6d6d",
    )
    build_statement(
        api,
        crash["id"],
        driver["id"],
        narrative="The van crossed the centre line.",
        attested=True,
    )
    case = build_case_in_deliberation(
        api, crash["id"], committee_name="Elyria Safety Review Committee"
    )
    # Opening the case moved the crash out of REPORTED, so the intake snapshot is
    # already stale; re-read it so the crash handed back really is under review.
    crash = validate_success(api.get_crash(crash["id"], SAFETY_MANAGER))
    claim = build_claim(api, crash["id"], claimant_notice_date="2026-07-31")
    subrogation = build_subrogation_demand(
        api,
        claim["id"],
        third_party_name="Ridge Line Plumbing",
        at_fault_percentage=ELYRIA_AT_FAULT_PERCENTAGE,
        basis_note="their van crossed the centre line",
    )
    return {
        "driver": driver,
        "crash": crash,
        "camera": camera,
        "review_case": case,
        "claim": claim,
        "subrogation": subrogation,
    }


class TestFieldsThatAreRequiredInOneBranchAndForbiddenInTheOther:
    """Each discriminator is driven both ways, and the shape band always reports first."""

    def test_criterion_scores_are_required_on_a_substantive_ballot_and_banned_on_an_abstention(
        self, api: ApiClient
    ):
        """A four-key map is not the required shape, and is never zero-filled.

        PRD: "when the vote is not an abstention — a `criterion_scores` object with
        exactly five keys, each an integer from 0 through 4 inclusive ... An
        abstention must omit `criterion_scores` entirely; supplying scores with an
        abstention, or omitting them on a substantive vote, is
        `ERR_INVALID_REQUEST`."

        Design: Corner/validations/conditional_field_shape_flips_with_its_discriminator
        """
        context = _deliberating_case_and_draft_recovery(api)
        case_id = context["review_case"]["id"]
        version = context["review_case"]["version"]

        validate_error(
            api.cast_vote(
                case_id,
                factories.vote_payload(
                    version,
                    vote=BALLOT_DISPOSITION_ABSTAIN,
                    scores=factories.uniform_criterion_scores(2),
                ),
                COMMITTEE_ONE,
            ),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )
        validate_error(
            api.cast_vote(
                case_id,
                factories.vote_payload(version, vote=BALLOT_DISPOSITION_PREVENTABLE),
                COMMITTEE_ONE,
            ),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )
        validate_error(
            api.cast_vote(
                case_id,
                factories.vote_payload(
                    version,
                    vote=BALLOT_DISPOSITION_PREVENTABLE,
                    scores=FOUR_OF_THE_FIVE_CRITERIA,
                ),
                COMMITTEE_ONE,
            ),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

        accepted = validate_success(
            api.cast_vote(
                case_id,
                factories.vote_payload(
                    version,
                    vote=BALLOT_DISPOSITION_ABSTAIN,
                    comment="I sat on the prior appeal panel",
                ),
                COMMITTEE_ONE,
            ),
            201,
        )
        assert accepted["active_vote_count"] == 0
        assert accepted["abstain_count"] == 1
        assert accepted["committee_score"] is None
        assert accepted["version"] == version + 1

        rows, meta = validate_paginated(api.list_votes(case_id, AUDITOR))
        assert meta["total_count"] == 1
        assert len(rows) == 1
        assert rows[0]["vote"] == BALLOT_DISPOSITION_ABSTAIN
        assert rows[0]["weighted_member_score"] is None

    def test_the_suspension_window_and_the_course_code_follow_the_action_type(
        self, api: ApiClient
    ):
        """Four rejections, none of which is the preventability gate they also fail.

        PRD: "`suspension_start_at` and `suspension_end_at`, the inclusive bounds of
        the out-of-service period, are required when and only when the action is a
        suspension, must be absent otherwise ... `retraining_course_code`, naming
        the course the driver must complete, is required when and only when the
        action is a retraining or a suspension, and must be absent for a coaching
        or a termination recommendation."

        Design: Corner/validations/conditional_field_shape_flips_with_its_discriminator
        """
        context = _deliberating_case_and_draft_recovery(api)
        driver_id = context["driver"]["id"]
        crash_id = context["crash"]["id"]
        assert context["crash"]["preventability_status"] == PREVENTABILITY_UNDER_REVIEW

        for payload in (
            factories.disciplinary_action_payload(
                driver_id,
                crash_id,
                action_type=ACTION_TYPE_SUSPENSION,
                action_note="no window supplied",
                retraining_course_code=ELYRIA_COURSE_CODE,
            ),
            factories.disciplinary_action_payload(
                driver_id,
                crash_id,
                action_type=ACTION_TYPE_RETRAINING,
                action_note="window supplied on a retraining",
                suspension_start_at=ELYRIA_SUSPENSION_START,
                suspension_end_at=ELYRIA_SUSPENSION_END,
                retraining_course_code=ELYRIA_COURSE_CODE,
            ),
            factories.disciplinary_action_payload(
                driver_id,
                crash_id,
                action_type=ACTION_TYPE_COACHING,
                action_note="course code on a coaching",
                retraining_course_code=ELYRIA_COURSE_CODE,
            ),
            factories.disciplinary_action_payload(
                driver_id,
                crash_id,
                action_type=ACTION_TYPE_RETRAINING,
                action_note="no course code",
            ),
        ):
            validate_error(
                api.create_disciplinary_action(payload, SAFETY_MANAGER),
                ApiErrorId.INVALID_REQUEST.value,
                400,
            )

        rows, meta = validate_paginated(
            api.list_disciplinary_actions(SAFETY_MANAGER, {"driver_id": driver_id})
        )
        assert meta["total_count"] == 0
        assert rows == []

    def test_the_recovered_amount_follows_the_resolution_and_outranks_the_state_gate(
        self, api: ApiClient
    ):
        """A DRAFT recovery could not be resolved either way, yet shape reports first.

        PRD: "That amount is required when the `resolution` is `RECOVERED` and must
        be absent for the other two resolutions; supplying it with `DENIED` or
        `WRITTEN_OFF`, or omitting it with `RECOVERED`, is `ERR_INVALID_REQUEST`."

        Design: Corner/validations/conditional_field_shape_flips_with_its_discriminator
        """
        context = _deliberating_case_and_draft_recovery(api)
        subrogation_id = context["subrogation"]["id"]
        assert context["subrogation"]["status"] == SUBROGATION_STATE_DRAFT

        validate_error(
            api.resolve_subrogation_demand(
                subrogation_id,
                factories.resolve_subrogation_payload(
                    resolution=SUBROGATION_RESOLUTION_RECOVERED,
                    resolution_note="recovered but no amount given",
                ),
                CLAIMS_MANAGER,
            ),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )
        validate_error(
            api.resolve_subrogation_demand(
                subrogation_id,
                factories.resolve_subrogation_payload(
                    resolution=SUBROGATION_RESOLUTION_DENIED,
                    recovered_amount_cents=ELYRIA_RECOVERED_CENTS,
                    resolution_note="denied yet an amount was given",
                ),
                CLAIMS_MANAGER,
            ),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

        unmoved = validate_success(
            api.get_subrogation_demand(subrogation_id, CLAIMS_MANAGER)
        )
        assert unmoved["status"] == SUBROGATION_STATE_DRAFT
        assert unmoved["recovered_amount_cents"] is None
        assert unmoved["resolved_at"] is None
        assert unmoved["version"] == context["subrogation"]["version"]

    def test_the_appeal_citation_follows_the_grounds_code_not_the_case_state(
        self, api: ApiClient
    ):
        """Both directions of the citation rule outrank the DELIBERATION state gate.

        PRD: "a `NEW_EVIDENCE` appeal must cite `appeal_evidence_item_id` ... A
        `PROCEDURAL` or `CRITERIA_MISAPPLICATION` appeal must omit the citation
        altogether."

        Design: Corner/validations/conditional_field_shape_flips_with_its_discriminator
        """
        context = _deliberating_case_and_draft_recovery(api)
        case_id = context["review_case"]["id"]
        assert context["review_case"]["status"] == REVIEW_STATE_DELIBERATION

        crash = validate_success(api.get_crash(context["crash"]["id"], SAFETY_MANAGER))
        assert crash["evidence_posture"] == EVIDENCE_POSTURE_COMPLETE

        validate_error(
            api.appeal_review_case(
                case_id,
                factories.appeal_payload(
                    appeal_grounds="procedural, with an evidence pointer that has no business here",
                    appeal_grounds_code=APPEAL_CODE_PROCEDURAL,
                    appeal_evidence_item_id=context["camera"]["id"],
                ),
                APPEALS_MANAGER,
            ),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )
        validate_error(
            api.appeal_review_case(
                case_id,
                factories.appeal_payload(
                    appeal_grounds="new evidence, but no item cited",
                    appeal_grounds_code=APPEAL_CODE_NEW_EVIDENCE,
                ),
                APPEALS_MANAGER,
            ),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

        unmoved = validate_success(api.get_review_case(case_id, AUDITOR))
        assert unmoved["status"] == REVIEW_STATE_DELIBERATION
        assert unmoved["appeal_round"] == 0
        assert unmoved["appeal_grounds"] is None
        assert unmoved["version"] == context["review_case"]["version"]


FOSTORIA_TOWER_CAPACITY_CENTS = 900_000
FOSTORIA_PROVISIONAL_RESERVE_CENTS = 500_000
FOSTORIA_DEMAND_A_CENTS = 900_000
FOSTORIA_DEMAND_B_CENTS = 600_000
FOSTORIA_TOTAL_A_CENTS = 972_000
FOSTORIA_TOTAL_B_CENTS = 648_000
FOSTORIA_ALAE_B_CENTS = 48_000
FOSTORIA_REVISED_RESERVE_CENTS = 1_500_000
FOSTORIA_OUTSTANDING_AFTER_B_CENTS = 852_000
FOSTORIA_REMAINING_CAPACITY_CENTS = 252_000


def _thin_tower_and_two_offered_demands(api: ApiClient) -> dict:
    """A 900,000 programme facing a 972,000 settlement and a 500,000 reserve."""
    terminal = build_terminal(
        api,
        name="Fostoria Terminal",
        terminal_code="FOS02",
        region_code="OH",
        annual_miles_millions=2.0,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-5601",
        full_name="Aiko Ravnborg",
        cdl_number="OH-CDL-5601",
        hire_date="2016-12-12",
    )
    crash = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-07-31T05:00:00Z",
        notified_at="2026-07-31T05:10:00Z",
        location_text="SR-12 at the elevator",
        severity=SEVERITY_MINOR,
        route_class=ROUTE_CLASS_LOCAL,
        tow_away=False,
        tow_reason=TOW_REASON_NONE,
        injury_transported_count=0,
        fatality_count=0,
        hazmat_release=False,
        mechanical_factor=False,
        third_party_at_fault=False,
    )
    layer = build_policy_layer(
        api,
        program_year=2026,
        layer_index=1,
        layer_type=LAYER_KIND_SIR,
        attachment_point_cents=0,
        limit_cents=FOSTORIA_TOWER_CAPACITY_CENTS,
        insurer_name="Self-insured retention",
    )
    claim = build_claim(api, crash["id"], claimant_notice_date="2026-07-31")
    demand_a = build_demand(
        api,
        claim["id"],
        claimant_name="Elevator Road Grain",
        claimant_type=CLAIMANT_TYPE_PROPERTY,
        demand_amount_cents=FOSTORIA_DEMAND_A_CENTS,
        represented_by_counsel=False,
        demand_received_at="2026-07-31T07:00:00Z",
    )
    make_offer(api, demand_a["id"], FOSTORIA_DEMAND_A_CENTS)
    demand_b = build_demand(
        api,
        claim["id"],
        claimant_name="Seneca County Signs",
        claimant_type=CLAIMANT_TYPE_PROPERTY,
        demand_amount_cents=FOSTORIA_DEMAND_B_CENTS,
        represented_by_counsel=False,
        demand_received_at="2026-07-31T07:30:00Z",
    )
    make_offer(api, demand_b["id"], FOSTORIA_DEMAND_B_CENTS)
    return {
        "crash": crash,
        "layer": layer,
        "claim": claim,
        "demand_a": demand_a,
        "demand_b": demand_b,
    }


class TestCoverageIsProvenBeforeTheReserveIsCounted:
    """The order of the two money guards is visible in which error comes back."""

    def test_a_settlement_that_breaks_both_guards_reports_the_coverage_failure(
        self, api: ApiClient
    ):
        """972,000 exceeds the 900,000 tower and the 500,000 reserve alike.

        PRD: "Only after coverage is proven does the reserve-sufficiency guard run
        ... A file that is both uncovered and underreserved reports the coverage
        failure, never the reserve failure."

        Design: Corner/validations/coverage_check_runs_before_the_reserve_check_on_every_settle
        """
        context = _thin_tower_and_two_offered_demands(api)
        assert_cents(
            context["claim"]["provisional_reserve_cents"],
            FOSTORIA_PROVISIONAL_RESERVE_CENTS,
            "provisional_reserve_cents",
        )
        assert FOSTORIA_TOTAL_A_CENTS > FOSTORIA_TOWER_CAPACITY_CENTS
        assert FOSTORIA_TOTAL_A_CENTS > FOSTORIA_PROVISIONAL_RESERVE_CENTS
        before = validate_success(api.get_claim(context["claim"]["id"], CLAIMS_ADJUSTER))

        validate_error(
            api.settle_demand(
                context["demand_a"]["id"],
                factories.settle_payload(settlement_reference="SET-2026-FOS02-0001"),
                CLAIMS_MANAGER,
            ),
            ApiErrorId.COVERAGE_EXHAUSTED.value,
            422,
        )

        untouched = validate_success(api.get_claim(context["claim"]["id"], CLAIMS_ADJUSTER))
        assert untouched["layer_allocations"] == []
        assert_cents(untouched["sir_eroded_cents"], 0, "sir_eroded_cents")
        assert_cents(
            untouched["outstanding_reserve_cents"],
            FOSTORIA_PROVISIONAL_RESERVE_CENTS,
            "outstanding_reserve_cents",
        )
        assert untouched["version"] == before["version"]

    def test_the_reserve_guard_is_reachable_once_the_tower_is_wide_enough(
        self, api: ApiClient
    ):
        """648,000 clears the untouched tower, so the second guard finally speaks.

        PRD: "then the tower must have enough remaining capacity for the whole
        `settlement_total_cents`, or the request fails with
        `ERR_COVERAGE_EXHAUSTED`. Only after coverage is proven does the
        reserve-sufficiency guard run"

        Design: Corner/validations/coverage_check_runs_before_the_reserve_check_on_every_settle
        """
        context = _thin_tower_and_two_offered_demands(api)
        assert FOSTORIA_TOTAL_B_CENTS < FOSTORIA_TOWER_CAPACITY_CENTS
        assert FOSTORIA_TOTAL_B_CENTS > FOSTORIA_PROVISIONAL_RESERVE_CENTS

        validate_error(
            api.settle_demand(
                context["demand_b"]["id"],
                factories.settle_payload(settlement_reference="SET-2026-FOS02-0002"),
                CLAIMS_MANAGER,
            ),
            ApiErrorId.RESERVE_INSUFFICIENT.value,
            422,
        )

        observed = validate_success(api.get_claim(context["claim"]["id"], CLAIMS_ADJUSTER))
        revised = revise_reserve(
            api,
            context["claim"]["id"],
            observed["version"],
            basis=RESERVE_BASIS_DEMAND_BASED,
            revision_note="weight both open demands",
        )
        assert_cents(
            revised["revised_reserve_cents"],
            FOSTORIA_REVISED_RESERVE_CENTS,
            "revised_reserve_cents",
        )
        assert_cents(
            revised["outstanding_reserve_cents"],
            FOSTORIA_REVISED_RESERVE_CENTS,
            "outstanding_reserve_cents",
        )

        settled_b = settle(
            api, context["demand_b"]["id"], settlement_reference="SET-2026-FOS02-0003"
        )
        assert settled_b["status"] == DEMAND_STATE_SETTLED
        assert_cents(settled_b["alae_cents"], FOSTORIA_ALAE_B_CENTS, "alae_cents")
        assert_cents(
            settled_b["settlement_total_cents"],
            FOSTORIA_TOTAL_B_CENTS,
            "settlement_total_cents",
        )

    def test_the_capacity_this_claim_already_spent_still_counts_against_it(
        self, api: ApiClient
    ):
        """The retention already eroded shrinks the capacity the next settle sees.

        Demand A overruns the surviving capacity and the standing reserve alike,
        so the file is both uncovered and underreserved and the coverage failure
        is the one that must be reported.

        PRD: "the amount already consumed on this claim is the sum of
        `allocated_cents` in the claim's `layer_allocations` entries whose
        `policy_layer_id` is that layer; the layer's remaining capacity is its
        `limit_cents` less that amount ... If anything is still unallocated after
        the last layer, the entire settlement is refused with
        `ERR_COVERAGE_EXHAUSTED`" and "A file that is both uncovered and
        underreserved reports the coverage failure, never the reserve failure."

        Design: Corner/validations/coverage_check_runs_before_the_reserve_check_on_every_settle
        """
        context = _thin_tower_and_two_offered_demands(api)
        observed = validate_success(api.get_claim(context["claim"]["id"], CLAIMS_ADJUSTER))
        revise_reserve(
            api,
            context["claim"]["id"],
            observed["version"],
            basis=RESERVE_BASIS_DEMAND_BASED,
            revision_note="weight both open demands",
        )
        settle(api, context["demand_b"]["id"], settlement_reference="SET-2026-FOS02-0003")

        assert (
            FOSTORIA_TOWER_CAPACITY_CENTS - FOSTORIA_TOTAL_B_CENTS
            == FOSTORIA_REMAINING_CAPACITY_CENTS
        )
        assert FOSTORIA_TOTAL_A_CENTS > FOSTORIA_REMAINING_CAPACITY_CENTS
        assert FOSTORIA_TOTAL_A_CENTS > FOSTORIA_OUTSTANDING_AFTER_B_CENTS

        validate_error(
            api.settle_demand(
                context["demand_a"]["id"],
                factories.settle_payload(settlement_reference="SET-2026-FOS02-0004"),
                CLAIMS_MANAGER,
            ),
            ApiErrorId.COVERAGE_EXHAUSTED.value,
            422,
        )

        final = validate_success(api.get_claim(context["claim"]["id"], CLAIMS_ADJUSTER))
        assert final["handling_status"] == CLAIM_HANDLING_NEGOTIATION
        assert_cents(
            final["indemnity_paid_cents"], FOSTORIA_DEMAND_B_CENTS, "indemnity_paid_cents"
        )
        assert_cents(final["alae_paid_cents"], FOSTORIA_ALAE_B_CENTS, "alae_paid_cents")
        assert_cents(
            final["outstanding_reserve_cents"],
            FOSTORIA_OUTSTANDING_AFTER_B_CENTS,
            "outstanding_reserve_cents",
        )
        assert_cents(final["sir_eroded_cents"], FOSTORIA_TOTAL_B_CENTS, "sir_eroded_cents")
        assert len(final["layer_allocations"]) == 1
        assert final["layer_allocations"][0]["policy_layer_id"] == context["layer"]["id"]
        assert_cents(
            final["layer_allocations"][0]["allocated_cents"],
            FOSTORIA_TOTAL_B_CENTS,
            "allocated_cents",
        )
        assert validate_success(api.get_demand(context["demand_a"]["id"], CLAIMS_ADJUSTER))[
            "status"
        ] == DEMAND_STATE_OFFER_OUTSTANDING
