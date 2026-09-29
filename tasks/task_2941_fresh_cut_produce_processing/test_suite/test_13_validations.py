"""The authentication tier, the override rule, and identifier resolution order.

Every test here drives one request into several rules at once and pins which
rule the server is required to report: the empty-string header that outranks
both a bad path id and a malformed body, the override-authority refusal that
outranks the payload check, the declared order the four planning foreign keys
resolve in, and the lifecycle-state gates that outrank the food-safety gates
behind them.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    LINE_OPERATOR_HEADERS,
    PLANT_ADMIN_HEADERS,
    QA_MANAGER_HEADERS,
    QA_TECHNICIAN_HEADERS,
    RECEIVING_CLERK_HEADERS,
    USER_SANITATION_TECH_A,
    headers_with_empty_role,
    headers_with_empty_user_id,
    headers_without_role,
    headers_without_user_id,
    make_qa_technician_headers,
    make_sanitation_tech_headers,
)

HTTP_CREATED = 201

# A body that is malformed twice over, for the calls that never reach it.
MALFORMED_PRODUCT_CODE = "X"
UNDECLARED_COMMODITY_CLASS = "BOGUS"

# A disposition decision the contract does not declare.
UNDECLARED_DECISION = "MAYBE"
CHILLED_ON_ARRIVAL = "Chilled on arrival"

# The window a second run would occupy, two days clear of the standing run.
LATER_START_AT = "2026-08-05T07:00:00Z"
LATER_END_AT = "2026-08-05T12:00:00Z"

# The second FOODSERVICE revision, which supersedes the first.
SECOND_REVISION_CAP_DAYS = 13
SECOND_REVISION_MIN_REMAINING_DAYS = 9
FIRST_SPEC_REVISION = 1
SECOND_SPEC_REVISION = 2
SPECS_PER_PRODUCT = 2
ACTIVE_SPECS_PER_PRODUCT = 1

# The second product's own two revisions, for the mismatch probe.
OTHER_SPEC_CAP_DAYS = 12
OTHER_SPEC_MIN_REMAINING_DAYS = 8
OTHER_SPEC_CASE_NET_WEIGHT_LB = 15.0

# One cent of a pound more trim than the load weighs.
ONE_CENT_OVER_NET_LB = 40000.01
TOTAL_LOSS_TRIM_LB = 40000.00
NO_POUNDS_LB = 0.00

# A clean submitted one component short of the line's requirement.
SHORT_COMPONENT_COUNT = c.LINE_REQUIRED_COMPONENTS - 1
CLEAN_ATP_RLU = 100

# The pounds a closed run is offered and must refuse.
LATE_DRAW_LB = 100.00


def test_an_empty_header_outranks_both_a_bad_path_id_and_a_bad_body(api):
    """An empty string is an absent header, and priority 1 precedes every lookup.

    PRD: If either header is absent, or is present but sent as an empty string, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401); an empty string is treated as an absent header, not as a valid identifier.
    PRD: **Authentication.** Header presence and non-emptiness first (`ERR_UNAUTHENTICATED`), then whether the declared role is a recognised role that is permitted on this operation (`ERR_UNAUTHORIZED`), then the narrower override-authority rule of §2.1 (`ERR_OVERRIDE_NOT_PERMITTED`).
    PRD: Identifiers embedded in the URL are resolved left to right, and always before any body field is resolved.

    Design: Corner/validations/corner_missing_or_blank_auth_headers_are_unauthenticated
    """
    world = fx.build_world(api, stop_after=fx.STOP_MASTER_DATA)

    # Absent and empty are the same refusal, on both headers.
    for headers in (
        headers_without_role(),
        headers_without_user_id(),
        headers_with_empty_role(),
        headers_with_empty_user_id(c.ROLE_QA_MANAGER),
    ):
        validate_error(
            api.get_product(world.product_id, headers),
            ApiErrorId.UNAUTHENTICATED,
        )

    # The authentication tier runs before the path id is resolved at all.
    validate_error(
        api.get_product(c.UNKNOWN_ID, headers_with_empty_role()),
        ApiErrorId.UNAUTHENTICATED,
    )

    # And before the body is examined, even with an undeclared enum member in it.
    validate_error(
        api.create_product(
            f.product_payload(
                code=MALFORMED_PRODUCT_CODE,
                name=MALFORMED_PRODUCT_CODE,
                commodity_class=UNDECLARED_COMMODITY_CLASS,
            ),
            headers_with_empty_role(),
        ),
        ApiErrorId.UNAUTHENTICATED,
    )

    # None of the four refusals registered a product.
    a.assert_page(api.list_products(PLANT_ADMIN_HEADERS), expected_total=1)


def test_the_override_field_is_refused_before_the_body_is_read(api):
    """A technician sending an override and a bad decision sees the override refusal.

    PRD: The `override_justification` field on a receipt disposition may only be supplied by an operator whose `X-User-Role` is `QAManager`.
    PRD: Any other role that sends a non-null `override_justification` is refused with `ERR_OVERRIDE_NOT_PERMITTED` (HTTP 403), and this refusal happens before the rest of the payload is examined — so a `QATechnician` who sends both an override justification and a malformed body sees the override refusal, not a request-shape error.
    PRD: Any violation is `ERR_INVALID_REQUEST` (HTTP 400).

    Design: Corner/validations/corner_override_permission_is_checked_before_the_payload
    """
    world = fx.build_world(api, stop_after=fx.STOP_RECEIPT_PENDING)
    assert world.receipt["status"] == c.RECEIPT_PENDING_INSPECTION
    assert world.receipt["temp_grade"] == c.TEMP_IN_SPEC

    overreaching = f.disposition_payload(
        UNDECLARED_DECISION,
        trim_loss_lb=c.RECEIPT_TRIM_LOSS_LB,
        override_justification=CHILLED_ON_ARRIVAL,
    )
    validate_error(
        api.disposition_raw_receipt(world.receipt_id, overreaching, QA_TECHNICIAN_HEADERS),
        ApiErrorId.OVERRIDE_NOT_PERMITTED,
    )

    # The identical body from the permitted role reaches the payload check.
    validate_error(
        api.disposition_raw_receipt(world.receipt_id, overreaching, QA_MANAGER_HEADERS),
        ApiErrorId.INVALID_REQUEST,
    )

    # Both refusals left the load dispositionable.
    assert fx.read_receipt(api, world.receipt_id)["status"] == c.RECEIPT_PENDING_INSPECTION

    accepted = fx.disposition_receipt(
        api,
        world.receipt_id,
        c.DECISION_ACCEPT,
        trim_loss_lb=c.RECEIPT_TRIM_LOSS_LB,
        override_justification=CHILLED_ON_ARRIVAL,
        headers=QA_MANAGER_HEADERS,
    )
    assert accepted["status"] == c.RECEIPT_ACCEPTED
    assert accepted["accepted_lb"] == c.RECEIPT_ACCEPTED_LB
    assert accepted["remaining_lb"] == c.RECEIPT_ACCEPTED_LB


def _planning_payload(world, **overrides):
    """A planning body for a window two days clear of the standing run."""
    return f.process_run_payload(
        overrides.pop("line_id", world.line_id),
        overrides.pop("product_id", world.product_id),
        overrides.pop("customer_spec_id", world.spec_id),
        overrides.pop("wash_system_id", world.wash_system_id),
        planned_start_at=LATER_START_AT,
        planned_end_at=LATER_END_AT,
        **overrides,
    )


def test_the_line_wins_when_every_planning_foreign_key_is_wrong(api):
    """Body keys resolve in the declared order, and a path id outranks all of them.

    PRD: Foreign keys in the body are resolved after the path and in the order the operation declares its inputs.
    PRD: Planning a run resolves, in this exact order, `line_id` (`ERR_LINE_NOT_FOUND`), `product_id` (`ERR_PRODUCT_NOT_FOUND`), `customer_spec_id` (`ERR_CUSTOMER_SPEC_NOT_FOUND`), `wash_system_id` (`ERR_WASH_SYSTEM_NOT_FOUND`) and then, only when it is present and non-null, `rework_source_run_id` (`ERR_PROCESS_RUN_NOT_FOUND`).
    PRD: Recording a load resolves `grower_lot_id` (`ERR_GROWER_LOT_NOT_FOUND`).

    Design: Corner/validations/corner_path_ids_resolve_before_body_ids_in_declared_order
    """
    world = fx.build_world(api, stop_after=fx.STOP_RUN_PLANNED)

    all_wrong = _planning_payload(
        world,
        line_id=c.UNKNOWN_ID,
        product_id=c.UNKNOWN_ID,
        customer_spec_id=c.UNKNOWN_ID,
        wash_system_id=c.UNKNOWN_ID,
    )
    validate_error(
        api.create_process_run(all_wrong, LINE_OPERATOR_HEADERS),
        ApiErrorId.LINE_NOT_FOUND,
    )

    one_at_a_time = (
        ({"product_id": c.UNKNOWN_ID}, ApiErrorId.PRODUCT_NOT_FOUND),
        ({"customer_spec_id": c.UNKNOWN_ID}, ApiErrorId.CUSTOMER_SPEC_NOT_FOUND),
        ({"wash_system_id": c.UNKNOWN_ID}, ApiErrorId.WASH_SYSTEM_NOT_FOUND),
        ({"rework_source_run_id": c.UNKNOWN_ID}, ApiErrorId.PROCESS_RUN_NOT_FOUND),
    )
    for override, expected_error in one_at_a_time:
        validate_error(
            api.create_process_run(
                _planning_payload(world, **override), LINE_OPERATOR_HEADERS
            ),
            expected_error,
        )

    # The path id is resolved before the body's own foreign key.
    validate_error(
        api.create_lot_consumption(
            c.UNKNOWN_ID,
            f.lot_consumption_payload(c.UNKNOWN_ID, world.run_version, LATE_DRAW_LB),
            LINE_OPERATOR_HEADERS,
        ),
        ApiErrorId.PROCESS_RUN_NOT_FOUND,
    )

    # A create endpoint with no path id at all still resolves its body key.
    validate_error(
        api.create_raw_receipt(
            f.raw_receipt_payload(c.UNKNOWN_ID), RECEIVING_CLERK_HEADERS
        ),
        ApiErrorId.GROWER_LOT_NOT_FOUND,
    )

    # Nothing was planned: the standing run is still the only one.
    a.assert_page(api.list_process_runs(LINE_OPERATOR_HEADERS), expected_total=1)


def test_a_superseded_revision_cannot_be_packed_to_and_a_foreign_one_loses_first(api):
    """Publishing revision 2 retires revision 1, and the mismatch rule runs first.

    PRD: The server computes `spec_revision` as 1 plus the number of specification rows that already existed for the same `product_id` and `channel`, sets the new row's `status` to `ACTIVE` with `superseded_at` left null, and moves the previously `ACTIVE` row for that same `product_id` and `channel` to `SUPERSEDED`, stamping its `superseded_at` with the logical clock.
    PRD: The server maintains `active_spec_count` on the product, starting at 0, as the number of that product's specification revisions whose `status` is `ACTIVE`.
    PRD: The named specification must belong to the named product: its `product_id` must equal the run's `product_id`, or the request is refused with `ERR_SPEC_PRODUCT_MISMATCH` (HTTP 422).
    PRD: The named specification's `status` must be `ACTIVE`; a `SUPERSEDED` revision cannot be packed to, and naming one is refused with `ERR_SPEC_NOT_ACTIVE` (HTTP 422).

    Design: Corner/validations/corner_spec_must_belong_to_the_product_and_still_be_active
    """
    world = fx.build_world(api, stop_after=fx.STOP_SANITATION_VALIDATED)
    assert world.spec["spec_revision"] == FIRST_SPEC_REVISION
    assert world.spec["status"] == c.SPEC_ACTIVE

    product = validate_success(api.get_product(world.product_id, PLANT_ADMIN_HEADERS))
    current = fx.create_customer_spec(
        api,
        world.product_id,
        product["version"],
        max_shelf_life_days_offered=SECOND_REVISION_CAP_DAYS,
        min_remaining_shelf_life_days_at_ship=SECOND_REVISION_MIN_REMAINING_DAYS,
    )
    assert current["spec_revision"] == SECOND_SPEC_REVISION
    assert current["status"] == c.SPEC_ACTIVE
    assert current["superseded_at"] is None

    rows = a.assert_page(
        api.list_customer_specs(
            world.product_id, QA_MANAGER_HEADERS, {"limit": c.DEFAULT_LIMIT, "offset": 0}
        ),
        expected_total=SPECS_PER_PRODUCT,
    )
    by_id = {row["id"]: row for row in rows}
    retired = by_id[world.spec_id]
    assert retired["status"] == c.SPEC_SUPERSEDED
    a.assert_instant(retired["superseded_at"], "superseded_at")
    assert by_id[current["id"]]["status"] == c.SPEC_ACTIVE

    reread = validate_success(api.get_product(world.product_id, PLANT_ADMIN_HEADERS))
    assert reread["active_spec_count"] == ACTIVE_SPECS_PER_PRODUCT

    # A second product with its own two revisions, so its first is also retired.
    other = validate_success(
        api.create_product(f.slaw_product_payload(), PLANT_ADMIN_HEADERS), HTTP_CREATED
    )
    foreign_overrides = {
        "max_shelf_life_days_offered": OTHER_SPEC_CAP_DAYS,
        "min_remaining_shelf_life_days_at_ship": OTHER_SPEC_MIN_REMAINING_DAYS,
        "atmosphere_required": c.ATMOSPHERE_AIR,
        "case_net_weight_lb": OTHER_SPEC_CASE_NET_WEIGHT_LB,
        "code_date_format": c.CODE_DATE_CALENDAR,
    }
    foreign_retired = fx.create_customer_spec(
        api, other["id"], other["version"], **foreign_overrides
    )
    other_reread = validate_success(api.get_product(other["id"], PLANT_ADMIN_HEADERS))
    fx.create_customer_spec(
        api, other["id"], other_reread["version"], **foreign_overrides
    )

    validate_error(
        api.create_process_run(
            _planning_payload(world, customer_spec_id=world.spec_id),
            LINE_OPERATOR_HEADERS,
        ),
        ApiErrorId.SPEC_NOT_ACTIVE,
    )
    # The foreign revision is both superseded and someone else's; the owner check wins.
    validate_error(
        api.create_process_run(
            _planning_payload(world, customer_spec_id=foreign_retired["id"]),
            LINE_OPERATOR_HEADERS,
        ),
        ApiErrorId.SPEC_PRODUCT_MISMATCH,
    )

    planned = fx.plan_run(
        api,
        world.line_id,
        world.product_id,
        current["id"],
        world.wash_system_id,
        planned_start_at=LATER_START_AT,
        planned_end_at=LATER_END_AT,
    )
    assert planned["run_status"] == c.RUN_SETUP
    assert planned["customer_spec_id"] == current["id"]


def test_trim_loss_equal_to_the_net_weight_accepts_a_load_worth_no_pounds(api):
    """One cent over the net weight is refused; exactly the net weight is accepted.

    PRD: `trim_loss_lb` must be zero or greater and must not exceed the load's `net_weight_lb`, or the acceptance is refused with `ERR_TRIM_LOSS_EXCEEDS_NET` (HTTP 422).
    PRD: The server sets `accepted_lb` to the net weight less the declared trim loss, rounded half-up to two decimal places, sets `remaining_lb` to that same figure — the load's full drawable balance — and stamps `dispositioned_by_user_id` with the acting `X-User-ID`.

    Design: Corner/validations/corner_trim_loss_at_exactly_net_weight_is_accepted
    """
    world = fx.build_world(api, stop_after=fx.STOP_RECEIPT_PENDING)
    assert world.receipt["net_weight_lb"] == c.RECEIPT_NET_WEIGHT_LB
    assert world.receipt["trim_loss_lb"] is None
    assert world.receipt["accepted_lb"] is None
    assert world.receipt["remaining_lb"] is None

    validate_error(
        api.disposition_raw_receipt(
            world.receipt_id,
            f.disposition_payload(c.DECISION_ACCEPT, trim_loss_lb=ONE_CENT_OVER_NET_LB),
            QA_TECHNICIAN_HEADERS,
        ),
        ApiErrorId.TRIM_LOSS_EXCEEDS_NET,
    )
    assert fx.read_receipt(api, world.receipt_id)["status"] == c.RECEIPT_PENDING_INSPECTION

    total_loss = fx.disposition_receipt(
        api, world.receipt_id, c.DECISION_ACCEPT, trim_loss_lb=TOTAL_LOSS_TRIM_LB
    )
    assert total_loss["status"] == c.RECEIPT_ACCEPTED
    assert total_loss["trim_loss_lb"] == TOTAL_LOSS_TRIM_LB
    assert total_loss["accepted_lb"] == NO_POUNDS_LB
    assert total_loss["remaining_lb"] == NO_POUNDS_LB
    a.assert_pounds(total_loss["accepted_lb"], "accepted_lb")
    a.assert_pounds(total_loss["remaining_lb"], "remaining_lb")


def test_the_clean_state_gate_is_reported_before_its_component_count(api):
    """A short submit against a SCHEDULED event names the state, not the count.

    PRD: Submitting the completed clean moves the event `IN_PROGRESS → AWAITING_VALIDATION` and carries three measurements:
    PRD: **Lifecycle state preconditions.** Whether the target resource is in a state from which the requested action is legal, yielding `ERR_GROWER_LOT_INVALID_STATE`, `ERR_RECEIPT_NOT_PENDING`, `ERR_RUN_NOT_IN_SETUP`, `ERR_RUN_NOT_RUNNING`, `ERR_CONSUMPTION_ALREADY_VOIDED`, `ERR_SANITATION_INVALID_STATE`, `ERR_SWAB_INVALID_RESULT_TRANSITION`, `ERR_CORRECTIVE_ACTION_INVALID_STATE`, `ERR_HOLD_INVALID_STATE`, `ERR_HOLD_NOT_RELEASED` or `ERR_CASE_NOT_IN_INVENTORY` as appropriate.
    PRD: The submission is refused with `ERR_DISASSEMBLY_INCOMPLETE` (HTTP 422) unless `disassembled_component_count` is at least the line's `required_disassembly_component_count`; a count exactly equal to the requirement passes.
    PRD: All three refusals carry `ERR_SEGREGATION_OF_DUTIES` (HTTP 409), and all three are role-blind: holding `QAManager` does not exempt an operator who personally performed the work.

    Design: Corner/validations/corner_sanitation_state_gate_precedes_the_disassembly_count
    """
    world = fx.build_world(api, stop_after=fx.STOP_MASTER_DATA)
    assert world.line["required_disassembly_component_count"] == c.LINE_REQUIRED_COMPONENTS
    assert world.line["max_atp_rlu"] == c.LINE_MAX_ATP_RLU

    event = fx.schedule_sanitation(
        api,
        world.line_id,
        shift=c.SHIFT_FIRST,
        scheduled_for=c.SANITATION_SCHEDULED_FOR,
    )
    assert event["status"] == c.SANITATION_SCHEDULED

    short_submission = f.sanitation_submission_payload(
        disassembled_component_count=SHORT_COMPONENT_COUNT, atp_rlu=CLEAN_ATP_RLU
    )
    validate_error(
        api.submit_sanitation_event(
            event["id"],
            short_submission,
            make_sanitation_tech_headers(USER_SANITATION_TECH_A),
        ),
        ApiErrorId.SANITATION_INVALID_STATE,
    )
    validate_error(
        api.validate_sanitation_event(
            event["id"], f.outcome_payload(c.OUTCOME_PASS), QA_TECHNICIAN_HEADERS
        ),
        ApiErrorId.SANITATION_INVALID_STATE,
    )

    started = fx.start_sanitation(api, event["id"], USER_SANITATION_TECH_A)
    assert started["status"] == c.SANITATION_IN_PROGRESS
    assert started["performed_by_user_id"] == USER_SANITATION_TECH_A

    validate_error(
        api.submit_sanitation_event(
            event["id"],
            short_submission,
            make_sanitation_tech_headers(USER_SANITATION_TECH_A),
        ),
        ApiErrorId.DISASSEMBLY_INCOMPLETE,
    )

    submitted = fx.submit_sanitation(
        api,
        event["id"],
        USER_SANITATION_TECH_A,
        disassembled_component_count=c.LINE_REQUIRED_COMPONENTS,
        atp_rlu=CLEAN_ATP_RLU,
    )
    assert submitted["status"] == c.SANITATION_AWAITING_VALIDATION
    assert submitted["disassembled_component_count"] == c.LINE_REQUIRED_COMPONENTS

    # The identity check reads X-User-ID, so the technician's own role is irrelevant.
    validate_error(
        api.validate_sanitation_event(
            event["id"],
            f.outcome_payload(c.OUTCOME_PASS),
            make_qa_technician_headers(USER_SANITATION_TECH_A),
        ),
        ApiErrorId.SEGREGATION_OF_DUTIES,
    )
    assert (
        fx.read_line(api, world.line_id)["posture"] == c.POSTURE_RESTRICTED
    ), "the clean is still unvalidated, so the line stays shut"


def test_a_closed_run_refuses_a_start_a_second_close_and_a_late_draw(api):
    """Three lifecycle writes, two distinct state errors, and nothing written.

    PRD: The run must be in `SETUP`; any other `run_status` is refused with `ERR_RUN_NOT_IN_SETUP` (HTTP 409).
    PRD: The close moves the production dimension `RUNNING → CLOSED`; a run in any other `run_status` is refused with `ERR_RUN_NOT_RUNNING`.
    PRD: Consumption is permitted while the run's `run_status` is `SETUP` or `RUNNING`; a `CLOSED` or `CANCELLED` run is refused with `ERR_RUN_NOT_RUNNING` (HTTP 409).

    Design: Corner/validations/corner_closed_run_refuses_start_close_and_consumption
    """
    world = fx.closed_world(api)
    closed = fx.read_run(api, world.run_id)
    assert closed["run_status"] == c.RUN_CLOSED
    assert closed["cases_produced"] == c.CLOSE_CASES_PRODUCED
    version_before = closed["version"]

    validate_error(
        api.start_process_run(world.run_id, LINE_OPERATOR_HEADERS),
        ApiErrorId.RUN_NOT_IN_SETUP,
    )
    validate_error(
        api.close_process_run(world.run_id, f.close_payload(), LINE_OPERATOR_HEADERS),
        ApiErrorId.RUN_NOT_RUNNING,
    )
    # The supplied version is current, so it is the state gate that refuses the draw.
    validate_error(
        api.create_lot_consumption(
            world.run_id,
            f.lot_consumption_payload(world.receipt_id, version_before, LATE_DRAW_LB),
            LINE_OPERATOR_HEADERS,
        ),
        ApiErrorId.RUN_NOT_RUNNING,
    )

    after = fx.read_run(api, world.run_id)
    a.assert_version_is(after, version_before, "process run")
    assert after["cases_produced"] == c.CLOSE_CASES_PRODUCED
    assert after["run_status"] == c.RUN_CLOSED
    a.assert_page(
        api.list_run_lot_consumptions(world.run_id, LINE_OPERATOR_HEADERS),
        expected_total=1,
    )
