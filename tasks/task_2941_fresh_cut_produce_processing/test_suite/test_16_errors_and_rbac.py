"""One refusal shape for every family, and the role lines that draw the refusals.

Five status families come back in the identical envelope, shipping reports the
run-level cause ahead of the case-level symptom, each role is held to its own
exclusive writes, one read is wide while its neighbour is narrow, and the
verifier of a corrective action may never be the operator who implemented it.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

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
    SANITATION_TECH_HEADERS,
    SHIPPING_CLERK_HEADERS,
    USER_QA_MANAGER_A,
    USER_QA_MANAGER_B,
    USER_QA_TECH_B,
    USER_QA_TECH_IMPLEMENTER,
    headers_with_empty_user_id,
    headers_with_undeclared_role,
    make_qa_manager_headers,
    make_qa_technician_headers,
)

# The five rejected writes, and the one product that survives them.
UNDECLARED_COMMODITY_CLASS = "PLASTIC"
DUPLICATE_PRODUCT_NAME = "Romaine Shred Duplicate"
ONE_PRODUCT = 1


def test_five_status_families_come_back_in_one_error_envelope(api):
    """401, 403, 400, 404 and 409 differ only in status and identifier.

    PRD: Header presence and non-emptiness first (`ERR_UNAUTHENTICATED`), then whether the declared role is a recognised role that is permitted on this operation (`ERR_UNAUTHORIZED`), then the narrower override-authority rule of §2.1 (`ERR_OVERRIDE_NOT_PERMITTED`).
    PRD: Any violation is `ERR_INVALID_REQUEST` (HTTP 400).
    PRD: Product codes are unique across the plant; registering a second product with an existing `code` is refused with `ERR_DUPLICATE_CODE` (HTTP 409).
    PRD: The `error_id` is a unique, machine-readable string that identifies the specific error.
    PRD: The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.

    Design: Corner/errors/corner_error_body_shape_is_uniform_across_status_families
    """
    fx.set_clock(api, c.CLOCK_MASTER_DATA)
    standing = fx.create_product(api)

    attempts = (
        (
            api.get_product(standing["id"], headers_with_empty_user_id()),
            ApiErrorId.UNAUTHENTICATED,
        ),
        (
            api.create_product(f.slaw_product_payload(), QA_MANAGER_HEADERS),
            ApiErrorId.UNAUTHORIZED,
        ),
        (
            api.create_product(
                f.slaw_product_payload(commodity_class=UNDECLARED_COMMODITY_CLASS),
                PLANT_ADMIN_HEADERS,
            ),
            ApiErrorId.INVALID_REQUEST,
        ),
        (
            api.get_product(c.UNKNOWN_ID, PLANT_ADMIN_HEADERS),
            ApiErrorId.PRODUCT_NOT_FOUND,
        ),
        (
            api.create_product(
                f.product_payload(name=DUPLICATE_PRODUCT_NAME), PLANT_ADMIN_HEADERS
            ),
            ApiErrorId.DUPLICATE_CODE,
        ),
    )
    for response, expected in attempts:
        validate_error(response, expected)
        body = a.assert_error_body_shape(response, expected.value)
        assert body["message"], "every family carries a human-readable message"

    # Not one of the five rejected calls left a product behind.
    products = a.assert_page(
        api.list_products(PLANT_ADMIN_HEADERS),
        expected_total=ONE_PRODUCT,
        expected_count=ONE_PRODUCT,
    )
    assert products[0]["code"] == c.PRODUCT_CODE
    assert products[0]["name"] == c.PRODUCT_NAME


# One case ships, and the counters that must not double-count it.
ONE_CASE = 1
AVAILABLE_AFTER_ONE_SHIPMENT = c.CLOSE_CASES_PRODUCED - 1


def test_the_held_run_is_reported_before_the_held_case(api):
    """The same case answers HOLD_NOT_RELEASED, then ships, then answers the other.

    PRD: Within shipping specifically, the run-level cause is reported before the case-level symptom: `ERR_HOLD_NOT_RELEASED` precedes `ERR_CASE_NOT_IN_INVENTORY`.
    PRD: This precedes the case's own state check deliberately, so that a held case reports the run-level cause rather than the case-level symptom.
    PRD: Second, the case's own `status` must be `IN_INVENTORY`; an already `SHIPPED` or `DESTROYED` case on a run whose disposition permits shipping is refused with `ERR_CASE_NOT_IN_INVENTORY` (HTTP 409).
    PRD: A successful shipment stamps `shipped_at` from the logical clock, decrements the run's `cases_available`, increments its `cases_shipped`, and increments the case's `version` by 1.

    Design: Corner/errors/corner_ship_reports_the_run_cause_before_the_case_symptom
    """
    world = fx.closed_world(api)
    first_case = fx.list_cases(api, world.run_id, {"limit": ONE_CASE})[0]
    assert first_case["status"] == c.CASE_ON_HOLD

    validate_error(
        api.ship_finished_case(first_case["id"], SHIPPING_CLERK_HEADERS),
        ApiErrorId.HOLD_NOT_RELEASED,
    )

    fx.clear_hold(
        api,
        world.hold_id,
        latest_apc_cfu_g=c.APC_BELOW_MICRO_THRESHOLD,
        resulted_by=USER_QA_TECH_B,
        released_by=USER_QA_MANAGER_A,
    )
    shipped = fx.ship_case(api, first_case["id"])
    assert shipped["status"] == c.CASE_SHIPPED
    a.assert_instant_equals(shipped["shipped_at"], c.CLOCK_CLOSE, "shipped_at")

    # Only now that the run-level gate passes can the case-level one be seen.
    validate_error(
        api.ship_finished_case(first_case["id"], SHIPPING_CLERK_HEADERS),
        ApiErrorId.CASE_NOT_IN_INVENTORY,
    )

    run = fx.read_run(api, world.run_id)
    a.assert_case_counters(
        run,
        available=AVAILABLE_AFTER_ONE_SHIPMENT,
        on_hold=0,
        shipped=ONE_CASE,
        destroyed=0,
    )


# The seven exclusive writes, each attempted by a role that is not on them.
ADMIN_ONLY_CODE = "PA-ONLY"
ADMIN_ONLY_NAME = "Admin Only"
SECOND_LOAD_RECEIVED_AT = "2026-08-02T05:50:00Z"
SECOND_LOAD_PULP_TEMP_C = 2.0
SECOND_LOAD_GROSS_LB = 5000.00
SECOND_LOAD_TARE_LB = 500.00
SECOND_GROWER_CODE = "GRW-999"
SECOND_RANCH_BLOCK = "B9"
LATE_WINDOW_START_AT = "2026-08-06T07:00:00Z"
LATE_WINDOW_END_AT = "2026-08-06T12:00:00Z"
NEVER_SET_CLOCK = "2026-08-02T07:00:00Z"


def test_each_role_is_refused_the_writes_another_role_owns(api):
    """Eight exclusive writes and one undeclared role, all refused before anything else.

    PRD: When both headers are present, `X-User-Role` must name one of the seven roles the plant recognises and that role must be listed for the operation being attempted; otherwise the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).
    PRD: The Authorized Roles column below is exhaustive: a syntactically valid request from a role not listed for that endpoint is refused with `ERR_UNAUTHORIZED`.
    PRD: Header presence and non-emptiness first (`ERR_UNAUTHENTICATED`), then whether the declared role is a recognised role that is permitted on this operation (`ERR_UNAUTHORIZED`), then the narrower override-authority rule of §2.1 (`ERR_OVERRIDE_NOT_PERMITTED`).
    PRD: An event in any other state is refused with `ERR_SANITATION_INVALID_STATE` (HTTP 409).

    Design: Corner/rbac/corner_every_role_is_refused_the_other_roles_exclusive_writes
    """
    world = fx.build_world(api, stop_after=fx.STOP_SANITATION_VALIDATED)
    before = fx.read_grower_lot(api, world.grower_lot_id)
    assert before["status"] == c.LOT_APPROVED
    assert world.sanitation_event["status"] == c.SANITATION_VALIDATED

    refusals = (
        api.create_product(
            f.product_payload(code=ADMIN_ONLY_CODE, name=ADMIN_ONLY_NAME),
            SHIPPING_CLERK_HEADERS,
        ),
        api.create_raw_receipt(
            f.raw_receipt_payload(
                world.grower_lot_id,
                received_at=SECOND_LOAD_RECEIVED_AT,
                pulp_temp_c=SECOND_LOAD_PULP_TEMP_C,
                gross_weight_lb=SECOND_LOAD_GROSS_LB,
                tare_weight_lb=SECOND_LOAD_TARE_LB,
            ),
            QA_TECHNICIAN_HEADERS,
        ),
        api.create_grower_lot(
            f.grower_lot_payload(
                grower_code=SECOND_GROWER_CODE, ranch_block=SECOND_RANCH_BLOCK
            ),
            RECEIVING_CLERK_HEADERS,
        ),
        api.approve_grower_lot(world.grower_lot_id, QA_TECHNICIAN_HEADERS),
        api.create_process_run(
            f.process_run_payload(
                world.line_id,
                world.product_id,
                world.spec_id,
                world.wash_system_id,
                planned_start_at=LATE_WINDOW_START_AT,
                planned_end_at=LATE_WINDOW_END_AT,
            ),
            SANITATION_TECH_HEADERS,
        ),
        # Already VALIDATED, so a state error would also apply - and does not.
        api.start_sanitation_event(
            world.sanitation_event_id, LINE_OPERATOR_HEADERS
        ),
        api.changeout_wash_system(world.wash_system_id, QA_TECHNICIAN_HEADERS),
        api.set_clock(f.clock_payload(NEVER_SET_CLOCK), QA_MANAGER_HEADERS),
        # A role string that names none of the seven, on a read four roles hold.
        api.get_grower_lot(world.grower_lot_id, headers_with_undeclared_role()),
    )
    for response in refusals:
        validate_error(response, ApiErrorId.UNAUTHORIZED)
        a.assert_error_body_shape(response, ApiErrorId.UNAUTHORIZED.value)

    after = fx.read_grower_lot(api, world.grower_lot_id, QA_MANAGER_HEADERS)
    assert after["status"] == c.LOT_APPROVED
    a.assert_version_is(after, before["version"], "grower lot")
    a.assert_empty_page(
        api.list_lot_raw_receipts(
            world.grower_lot_id,
            RECEIVING_CLERK_HEADERS,
            {"status": c.RECEIPT_PENDING_INSPECTION},
        )
    )


# The five roles on the run read, and the three on the recall view.
RUN_READERS = (
    PLANT_ADMIN_HEADERS,
    QA_MANAGER_HEADERS,
    QA_TECHNICIAN_HEADERS,
    LINE_OPERATOR_HEADERS,
    SHIPPING_CLERK_HEADERS,
)
RUN_NON_READERS = (RECEIVING_CLERK_HEADERS, SANITATION_TECH_HEADERS)
TRACEABILITY_READERS = (
    PLANT_ADMIN_HEADERS,
    QA_MANAGER_HEADERS,
    QA_TECHNICIAN_HEADERS,
)
TRACEABILITY_NON_READERS = (
    LINE_OPERATOR_HEADERS,
    SHIPPING_CLERK_HEADERS,
    RECEIVING_CLERK_HEADERS,
    SANITATION_TECH_HEADERS,
)


def test_the_run_read_is_wide_while_the_recall_view_is_narrow(api):
    """Five roles fetch the run; only three of them may open its recall view.

    PRD: The Authorized Roles column below is exhaustive: a syntactically valid request from a role not listed for that endpoint is refused with `ERR_UNAUTHORIZED`.
    PRD: | GET | `/process-runs/{id}` | Retrieve one processing run with both state dimensions, the frozen wash targets, the computed costs and the case counters. | `PlantAdmin`, `QAManager`, `QATechnician`, `LineOperator`, `ShippingClerk` |
    PRD: | GET | `/process-runs/{id}/traceability` | One-hop recall view: every grower lot and receipt that fed the run, the cases it produced, how many already shipped, and the rework ancestry. | `PlantAdmin`, `QAManager`, `QATechnician` |

    Design: Corner/rbac/corner_shared_reads_open_to_some_roles_and_closed_to_others
    """
    world = fx.closed_world(api)

    for headers in RUN_READERS:
        run = get_success_data(api.get_process_run(world.run_id, headers))
        assert run["id"] == world.run_id
        assert run["run_status"] == c.RUN_CLOSED
        assert run["disposition_status"] == c.DISPOSITION_HELD

    for headers in RUN_NON_READERS:
        validate_error(
            api.get_process_run(world.run_id, headers), ApiErrorId.UNAUTHORIZED
        )

    for headers in TRACEABILITY_READERS:
        trace = get_success_data(api.get_traceability(world.run_id, headers))
        assert trace["case_count"] == c.CLOSE_CASES_PRODUCED

    # The operator who packed the cases cannot open the recall graph.
    for headers in TRACEABILITY_NON_READERS:
        validate_error(
            api.get_traceability(world.run_id, headers), ApiErrorId.UNAUTHORIZED
        )


# The clean that fails on ATP, and the operator who then implements the fix.
ATP_ABOVE_LIMIT_RLU = 250
NO_REOPENS = 0
NO_OPEN_ACTIONS = 0


def test_the_implementer_cannot_verify_his_own_corrective_action(api):
    """The check reads the acting user, not the role the request declares.

    PRD: A `QATechnician` takes ownership, moving the action `OPEN → IN_PROGRESS` and stamping `implemented_by_user_id` from the acting `X-User-ID`.
    PRD: Verification is a `QAManager` decision carrying an `outcome`, and the verifying `X-User-ID` must differ from `implemented_by_user_id` on both branches or the request is refused with `ERR_SEGREGATION_OF_DUTIES`.
    PRD: All three refusals carry `ERR_SEGREGATION_OF_DUTIES` (HTTP 409), and all three are role-blind: holding `QAManager` does not exempt an operator who personally performed the work.
    PRD: An `outcome` of `PASS` moves the action `VERIFICATION_PENDING → VERIFIED`, stamps `verified_at` and `verified_by_user_id`, decrements the line's `open_corrective_action_count`, and recomputes the posture — which may move the line `FROZEN → RESTRICTED` or `FROZEN → OPEN` depending on what else is still open.
    PRD: Otherwise, if the latest sanitation event's `status` is anything other than `VALIDATED`, the posture is `RESTRICTED`.

    Design: Corner/rbac/corner_corrective_action_verifier_cannot_be_the_implementer
    """
    world = fx.build_world(api, stop_after=fx.STOP_RECEIPT_ACCEPTED)
    failed = fx.failed_sanitation(api, world.line_id, atp_rlu=ATP_ABOVE_LIMIT_RLU)
    assert failed["status"] == c.SANITATION_FAILED
    assert failed["failed_reason"] == c.FAILED_ATP_ABOVE_LIMIT

    action = fx.list_line_corrective_actions(api, world.line_id)[0]
    assert action["status"] == c.CA_OPEN
    assert action["source_type"] == c.SOURCE_SANITATION_FAILURE
    assert action["severity"] == c.SEVERITY_MAJOR
    assert action["source_ref_id"] == failed["id"]

    taken = get_success_data(
        api.start_corrective_action(
            action["id"], make_qa_technician_headers(USER_QA_TECH_IMPLEMENTER)
        )
    )
    assert taken["status"] == c.CA_IN_PROGRESS
    assert taken["implemented_by_user_id"] == USER_QA_TECH_IMPLEMENTER

    submitted = get_success_data(
        api.submit_corrective_action_verification(
            action["id"],
            f.corrective_action_submission_payload(),
            make_qa_technician_headers(USER_QA_TECH_IMPLEMENTER),
        )
    )
    assert submitted["status"] == c.CA_VERIFICATION_PENDING

    # The implementer wearing the manager's role is still the implementer.
    validate_error(
        api.verify_corrective_action(
            action["id"],
            f.outcome_payload(c.OUTCOME_PASS),
            make_qa_manager_headers(USER_QA_TECH_IMPLEMENTER),
        ),
        ApiErrorId.SEGREGATION_OF_DUTIES,
    )
    # A permitted user wearing the wrong role is refused two tiers earlier.
    validate_error(
        api.verify_corrective_action(
            action["id"],
            f.outcome_payload(c.OUTCOME_PASS),
            make_qa_technician_headers(USER_QA_MANAGER_B),
        ),
        ApiErrorId.UNAUTHORIZED,
    )

    verified = get_success_data(
        api.verify_corrective_action(
            action["id"],
            f.outcome_payload(c.OUTCOME_PASS),
            make_qa_manager_headers(USER_QA_MANAGER_B),
        )
    )
    assert verified["status"] == c.CA_VERIFIED
    assert verified["verified_by_user_id"] == USER_QA_MANAGER_B
    a.assert_instant_equals(
        verified["verified_at"], c.CLOCK_MASTER_DATA, "verified_at"
    )
    assert verified["reopen_count"] == NO_REOPENS

    # Clearing the action does not reopen the line: the clean itself failed.
    line = fx.read_line(api, world.line_id)
    assert line["open_corrective_action_count"] == NO_OPEN_ACTIONS
    assert line["posture"] == c.POSTURE_RESTRICTED
