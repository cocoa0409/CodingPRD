"""Which rule speaks when several are broken at once: state before money,
safety before the calendar, and the four layers that answer before any
business rule is consulted."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_budget_ledger,
    assert_item_state,
    assert_money_cents,
    assert_shelf_slots,
    assert_status,
    assert_supplier_status,
    assert_two_decimal_value,
    assert_version_is,
)
from test_helpers.constants import (
    ARTWORK_APPROVED,
    DECISION_ACCEPT,
    DECISION_REINSTATE,
    HOLD_SUPPLIER_SUSPENDED,
    ITEM_PACKAGING_APPROVED,
    ITEM_SPEC_LOCKED,
    POSTURE_SUSPENDED,
    POSTURE_WATCH,
    RUN_HOLD,
    RUN_ONGOING,
    SPEC_DRAFT,
    SPEC_LOCKED,
    SPEC_SUPERSEDE_PENDING,
    SUPPLIER_CONDITIONAL,
    SUPPLIER_SUSPENDED,
)
from test_helpers.fixtures import (
    add_complaint,
    build_chain,
    open_change_request,
    qualify_supplier,
    read_artwork_round,
    read_budget_ledger,
    read_gap,
    read_item,
    read_run,
    read_specification,
    read_supplier,
    suspend_supplier,
)
from test_helpers.test_users import (
    DESIGNER_HEADERS,
    DIRECTOR_HEADERS,
    EMPTY_USER_ID_HEADERS,
    QUALITY_HEADERS,
    REGULATORY_HEADERS,
    SOURCING_HEADERS,
    UNKNOWN_ROLE_HEADERS,
)

UNKNOWN_PROGRAM_ID = "11111111-1111-4111-8111-111111111111"
UNKNOWN_ITEM_ID = "22222222-2222-4222-8222-222222222222"
UNKNOWN_COST_MODEL_ID = "33333333-3333-4333-8333-333333333333"
UNKNOWN_AUDIT_ID = "44444444-4444-4444-8444-444444444444"
UNKNOWN_SPECIFICATION_ID = "55555555-5555-4555-8555-555555555555"
UNKNOWN_STUDY_ID = "66666666-6666-4666-8666-666666666666"
UNKNOWN_ARTWORK_ROUND_ID = "77777777-7777-4777-8777-777777777777"
UNKNOWN_CLAIM_ID = "88888888-8888-4888-8888-888888888888"
UNKNOWN_RUN_ID = "99999999-9999-4999-8999-999999999999"
UNKNOWN_COMPLAINT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
UNKNOWN_CHANGE_REQUEST_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
UNKNOWN_PINNED_ARTWORK_ROUND_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"


def _tight_budget_locked_chain(api):
    """A locked specification on a program with only 33,020 cents left over."""
    return build_chain(api, upto=25, program={"dev_budget_cents": 300000})


def test_relocking_a_locked_specification_answers_state_not_budget(api):
    """Both rules are broken; the 409 on state silences the 422 on money.

    PRD 3.6: "The specification must be `DRAFT` — locking one that is `LOCKED`,
    `SUPERSEDE_PENDING` or `SUPERSEDED` is refused with
    `ERR_SPECIFICATION_NOT_DRAFT` (HTTP 409)."

    PRD 3.6: "And the money must be there: the program's `committed_budget_cents`
    plus the slotting fee this lock would compute must not exceed
    `dev_budget_cents`, or the lock is refused with `ERR_PROGRAM_BUDGET_EXCEEDED`
    (HTTP 422)."

    PRD 2.9: "Checks are evaluated in a strict order, and the **first** violated
    check determines the response; later violations are neither reported nor merged
    into the response, even when they are also true."

    Design: Difficulty/priority_pair_validation_conflict/spec_lock_state_beats_budget_fiscal
    """
    ctx = _tight_budget_locked_chain(api)
    before = read_budget_ledger(api, ctx["program_id"])
    assert_budget_ledger(
        before,
        dev_budget_cents=300000,
        committed_budget_cents=266980,
        available_budget_cents=33020,
    )

    response = api.lock_specification(ctx["specification_id"], DIRECTOR_HEADERS)
    validate_error(response, ApiErrorId.ERR_SPECIFICATION_NOT_DRAFT.value, 409)

    spec = read_specification(api, ctx["specification_id"])
    assert_status(spec, SPEC_LOCKED, "specification")
    assert_money_cents(spec["slotting_fee_cents"], 266980, "slotting_fee_cents")
    assert_version_is(spec, 2, "specification")
    assert_budget_ledger(
        read_budget_ledger(api, ctx["program_id"]),
        committed_budget_cents=266980,
        lifetime_committed_cents=266980,
        lifetime_released_cents=0,
    )
    item = read_item(api, ctx["item_id"])
    assert item["development_status"] == ITEM_SPEC_LOCKED
    assert item["spec_revision_count"] == 1, "the refused lock drafted nothing"


def test_a_supersede_pending_specification_also_answers_state_not_budget(api):
    """A second losing state — SUPERSEDE_PENDING — outranks the same fiscal gate.

    PRD 3.6: "The specification must be `DRAFT` — locking one that is `LOCKED`,
    `SUPERSEDE_PENDING` or `SUPERSEDED` is refused with
    `ERR_SPECIFICATION_NOT_DRAFT` (HTTP 409)."

    PRD 3.9: "because the pinned cost model changed, the item's specification
    standing at `LOCKED` whose `pinned_cost_model_id` is this cost model transitions
    `LOCKED → SUPERSEDE_PENDING`, with its `version` incremented"

    PRD 3.9: "**Hop five**: because at least one claim was rescinded, if the item
    whose specification pinned that round is `LAUNCHED`, the item transitions
    `LAUNCHED → RELAUNCH_PENDING`, with its `version` incremented."

    PRD 2.9: "the addressed resource's own transition state; item quality
    suspension; awarded-supplier qualification"

    Design: Difficulty/priority_pair_validation_conflict/spec_lock_state_beats_budget_fiscal
    """
    ctx = _tight_budget_locked_chain(api)
    request = open_change_request(
        api, ctx, factory=f.ingredient_substitution_payload
    )
    validate_success(
        api.decide_change_request(
            request["id"], f.decision_payload(DECISION_ACCEPT), DIRECTOR_HEADERS
        )
    )
    assert_status(
        read_specification(api, ctx["specification_id"]),
        SPEC_SUPERSEDE_PENDING,
        "specification",
    )

    response = api.lock_specification(ctx["specification_id"], DIRECTOR_HEADERS)
    validate_error(response, ApiErrorId.ERR_SPECIFICATION_NOT_DRAFT.value, 409)

    spec = read_specification(api, ctx["specification_id"])
    assert_status(spec, SPEC_SUPERSEDE_PENDING, "specification")
    assert_money_cents(spec["slotting_fee_cents"], 266980, "slotting_fee_cents")
    # Hop five is conditional on the item standing at LAUNCHED; this chain stops
    # at the lock, so the item stays SPEC_LOCKED and the cascade ends at hop four.
    assert read_item(api, ctx["item_id"])["development_status"] == ITEM_SPEC_LOCKED
    assert_budget_ledger(
        read_budget_ledger(api, ctx["program_id"]),
        dev_budget_cents=300000,
        committed_budget_cents=266980,
        lifetime_committed_cents=266980,
        available_budget_cents=33020,
    )


def _suspended_item_holding_its_line(api):
    """A WATCH item driven to SUSPENDED, its 06:00-18:00 run held on line CRK-1."""
    ctx = build_chain(api, upto=26)
    add_complaint(api, ctx["item_id"])
    suspend_supplier(api, ctx["supplier_id"])
    return ctx


def _collides_with_the_held_window(api, ctx):
    """20:00-02:00 sits inside the held run's buffer-expanded 04:00-20:00 window."""
    return api.create_production_run(
        f.production_run_payload(
            ctx["item_id"],
            ctx["specification_id"],
            ctx["plant_line_id"],
            run_type=RUN_ONGOING,
            window_start="2026-09-07T20:00:00Z",
            window_end="2026-09-08T02:00:00Z",
        ),
        SOURCING_HEADERS,
    )


def test_a_suspended_item_answers_safety_not_the_line_calendar(api):
    """The window really does collide, and the 422 on safety is still the answer.

    PRD 3.7: "The item's `quality_posture` must not be `SUSPENDED`, or the request
    is refused with `ERR_ITEM_QUALITY_SUSPENDED` (HTTP 422)."

    PRD 3.7: "A conflict is refused with `ERR_LINE_WINDOW_CONFLICT` (HTTP 409); a
    cancelled run's window, by contrast, is free and never conflicts."

    PRD 2.9: "Checks are evaluated in a strict order, and the **first** violated
    check determines the response; later violations are neither reported nor merged
    into the response, even when they are also true."

    Design: Difficulty/priority_pair_validation_conflict/run_schedule_safety_posture_beats_window_constraint
    """
    ctx = _suspended_item_holding_its_line(api)

    response = _collides_with_the_held_window(api, ctx)
    validate_error(response, ApiErrorId.ERR_ITEM_QUALITY_SUSPENDED.value, 422)

    item = read_item(api, ctx["item_id"])
    assert item["quality_posture"] == POSTURE_SUSPENDED
    assert_two_decimal_value(item["complaint_ppm_90d"], 100.00, "complaint_ppm_90d")
    run = read_run(api, ctx["run_id"])
    assert_status(run, RUN_HOLD, "production run")
    assert run["hold_reason"] == HOLD_SUPPLIER_SUSPENDED
    assert_supplier_status(read_supplier(api, ctx["supplier_id"]), SUPPLIER_SUSPENDED)
    assert_budget_ledger(
        read_budget_ledger(api, ctx["program_id"]), committed_budget_cents=666980
    )


def test_reinstating_the_supplier_uncovers_the_line_window_conflict(api):
    """Remove the winning rule and the losing one speaks: the same request, now 409.

    PRD 3.2: "Reinstatement, `SUSPENDED → CONDITIONAL`, re-stamps `qualified_at` and
    recomputes the `quality_posture` of every item still sitting at `SUSPENDED` from
    that item's complaint trend, landing each on `GREEN`, `WATCH` or `PROBATION`."

    PRD 3.7: "Run windows are closed intervals, so touching endpoints count as an
    intersection, and a held run still occupies its line."

    PRD 3.7: "A conflict is refused with `ERR_LINE_WINDOW_CONFLICT` (HTTP 409); a
    cancelled run's window, by contrast, is free and never conflicts."

    Design: Difficulty/priority_pair_validation_conflict/run_schedule_safety_posture_beats_window_constraint
    """
    ctx = _suspended_item_holding_its_line(api)
    reinstated = qualify_supplier(
        api,
        ctx["supplier_id"],
        decision=DECISION_REINSTATE,
        window_start="2026-08-10T08:00:00Z",
        window_end="2026-08-11T17:00:00Z",
    )["supplier"]
    assert_supplier_status(reinstated, SUPPLIER_CONDITIONAL)

    response = _collides_with_the_held_window(api, ctx)
    validate_error(response, ApiErrorId.ERR_LINE_WINDOW_CONFLICT.value, 409)

    item = read_item(api, ctx["item_id"])
    assert_item_state(item, ITEM_SPEC_LOCKED, POSTURE_WATCH)
    assert_two_decimal_value(item["complaint_ppm_90d"], 100.00, "complaint_ppm_90d")
    run = read_run(api, ctx["run_id"])
    assert_status(run, RUN_HOLD, "production run")
    assert run["hold_reason"] == HOLD_SUPPLIER_SUSPENDED, (
        "reinstatement touches postures, not runs"
    )
    assert_budget_ledger(
        read_budget_ledger(api, ctx["program_id"]), committed_budget_cents=666980
    )


def test_both_401s_answer_before_any_identifier_is_resolved(api):
    """An unknown role on a nonexistent program is still a 401, never a 404.

    PRD 2.1: "Every request — including reads and including the logical-clock
    endpoint — must carry two headers: `X-User-ID`, identifying the acting user, and
    `X-User-Role`, naming the role that user is acting in. If either header is absent
    or present but empty, the request fails with `ERR_MISSING_AUTH_HEADERS` (HTTP
    401). If `X-User-Role` carries any string other than the six role names
    enumerated below, the request fails with `ERR_UNKNOWN_ROLE` (HTTP 401)."

    PRD 2.9: "The order is: presence of the two auth headers; recognisability of the
    role; the role's authorisation for the endpoint; well-formedness of the request
    body and query string; existence of every path identifier"

    Design: Corner/errors/auth_layer_returns_401_pair_before_any_lookup
    """
    ctx = build_chain(api, upto=1)

    missing = api.get_program(ctx["program_id"], EMPTY_USER_ID_HEADERS)
    validate_error(missing, ApiErrorId.ERR_MISSING_AUTH_HEADERS.value, 401)

    unknown_role = api.get_program(UNKNOWN_PROGRAM_ID, UNKNOWN_ROLE_HEADERS)
    error = validate_error(unknown_role, ApiErrorId.ERR_UNKNOWN_ROLE.value, 401)
    assert error["error_id"] != ApiErrorId.ERR_PROGRAM_NOT_FOUND.value, (
        "the role is rejected before the program id is looked up"
    )

    program = validate_success(api.get_program(ctx["program_id"], DIRECTOR_HEADERS))
    assert_version_is(program, 1, "brand program")


def test_each_core_entity_reports_its_own_not_found_code(api):
    """Five reads against a populated database, five distinct 404 identifiers.

    PRD 2.9: "Path identifiers are resolved left to right, and the first
    unresolvable segment determines the 404 code."

    PRD 2.9: "`ERR_AUDIT_NOT_FOUND` for `plant_audit_id` or `basis_audit_id`,
    `ERR_ITEM_NOT_FOUND` for `item_id` or `replacement_item_id`,
    `ERR_COST_MODEL_NOT_FOUND` for `cost_model_id` or `pinned_cost_model_id`"

    Design: Corner/errors/unknown_path_ids_on_core_entities_return_their_own_404
    """
    ctx = build_chain(api, upto=24)

    validate_error(
        api.get_program(UNKNOWN_PROGRAM_ID, DIRECTOR_HEADERS),
        ApiErrorId.ERR_PROGRAM_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_item(UNKNOWN_ITEM_ID, SOURCING_HEADERS),
        ApiErrorId.ERR_ITEM_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_cost_model(UNKNOWN_COST_MODEL_ID, SOURCING_HEADERS),
        ApiErrorId.ERR_COST_MODEL_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_plant_audit(UNKNOWN_AUDIT_ID, QUALITY_HEADERS),
        ApiErrorId.ERR_AUDIT_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_specification(UNKNOWN_SPECIFICATION_ID, SOURCING_HEADERS),
        ApiErrorId.ERR_SPECIFICATION_NOT_FOUND.value,
        404,
    )

    assert read_item(api, ctx["item_id"])["development_status"] == (
        ITEM_PACKAGING_APPROVED
    )
    assert_status(
        read_specification(api, ctx["specification_id"]), SPEC_DRAFT, "specification"
    )


def test_each_downstream_entity_reports_its_own_not_found_code(api):
    """Six more identifiers, including three whose tables are entirely empty.

    PRD 2.9: "`ERR_STUDY_NOT_FOUND` for `study_id`, `ERR_ARTWORK_ROUND_NOT_FOUND`
    for `artwork_round_id` or `pinned_artwork_round_id`, `ERR_CLAIM_NOT_FOUND` for
    `label_claim_id`, `ERR_SPECIFICATION_NOT_FOUND` for `specification_id`,
    `ERR_RUN_NOT_FOUND` for `production_run_id`, `ERR_COMPLAINT_NOT_FOUND` for
    `complaint_id`, and `ERR_CHANGE_REQUEST_NOT_FOUND` for
    `cost_change_request_id`. All fourteen are HTTP 404."

    Design: Corner/errors/unknown_path_ids_on_downstream_entities_return_their_own_404
    """
    ctx = build_chain(api, upto=24)

    validate_error(
        api.get_study(UNKNOWN_STUDY_ID, QUALITY_HEADERS),
        ApiErrorId.ERR_STUDY_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_artwork_round(UNKNOWN_ARTWORK_ROUND_ID, DESIGNER_HEADERS),
        ApiErrorId.ERR_ARTWORK_ROUND_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_label_claim(UNKNOWN_CLAIM_ID, REGULATORY_HEADERS),
        ApiErrorId.ERR_CLAIM_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_production_run(UNKNOWN_RUN_ID, SOURCING_HEADERS),
        ApiErrorId.ERR_RUN_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_complaint(UNKNOWN_COMPLAINT_ID, QUALITY_HEADERS),
        ApiErrorId.ERR_COMPLAINT_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_change_request(UNKNOWN_CHANGE_REQUEST_ID, SOURCING_HEADERS),
        ApiErrorId.ERR_CHANGE_REQUEST_NOT_FOUND.value,
        404,
    )

    _runs, run_meta = validate_paginated(
        api.list_production_runs(SOURCING_HEADERS, params={"item_id": ctx["item_id"]})
    )
    assert run_meta["total_count"] == 0
    _complaints, complaint_meta = validate_paginated(
        api.list_complaints(QUALITY_HEADERS, params={"item_id": ctx["item_id"]})
    )
    assert complaint_meta["total_count"] == 0
    _requests, request_meta = validate_paginated(
        api.list_change_requests(SOURCING_HEADERS, params={"item_id": ctx["item_id"]})
    )
    assert request_meta["total_count"] == 0
    assert_status(
        read_artwork_round(api, ctx["artwork_round_id"]), ARTWORK_APPROVED, "round"
    )


def test_an_unknown_body_foreign_key_answers_404_before_the_version_check(api):
    """The pinned round does not exist; the stale-version check never gets a turn.

    PRD 2.9: "Foreign keys in a request body are resolved after path identifiers, in
    the order the receiving resource declares its fields."

    PRD 2.9: "existence of every path identifier; existence of every foreign key in
    the body; the supplier-scope restriction on `SupplierUser`; the claim self-review
    prohibition; the run self-approval prohibition; the two optimistic-concurrency
    version checks"

    PRD 2.7: "If `expected_item_version` does not equal the item's current
    `version`, the create is rejected with `ERR_STALE_ITEM_VERSION` (HTTP 412)."

    Design: Corner/errors/body_foreign_key_404_precedes_state_and_fiscal_checks
    """
    ctx = build_chain(api, upto=23)

    response = api.create_specification(
        f.specification_payload(
            ctx["item_id"],
            ctx["cost_model_id"],
            UNKNOWN_PINNED_ARTWORK_ROUND_ID,
            ctx["item_version"],
        ),
        SOURCING_HEADERS,
    )
    error = validate_error(
        response, ApiErrorId.ERR_ARTWORK_ROUND_NOT_FOUND.value, 404
    )
    assert error["error_id"] != ApiErrorId.ERR_STALE_ITEM_VERSION.value

    _specs, meta = validate_paginated(
        api.list_specifications(SOURCING_HEADERS, params={"item_id": ctx["item_id"]})
    )
    assert meta["total_count"] == 0, "a refused create persists no specification"
    assert read_item(api, ctx["item_id"])["spec_revision_count"] == 0
    assert_budget_ledger(
        read_budget_ledger(api, ctx["program_id"]),
        committed_budget_cents=0,
        lifetime_committed_cents=0,
    )


def test_four_different_shape_defects_all_answer_invalid_request(api):
    """An unknown field, a bad enum, an over-range limit and a non-ISO datetime.

    PRD 2.9: "Well-formedness, evaluated fourth, covers a single rejection code,
    `ERR_INVALID_REQUEST` (HTTP 422), for all of: an unknown field in the body or
    query string, a missing required field, a value of the wrong type, an enumerated
    value outside its declared set, a numeric value violating one of the constraints
    stated in the workflow narratives below, a datetime that is not ISO 8601 UTC, and
    a pagination `limit` or `offset` outside its permitted range."

    Design: Corner/errors/malformed_request_shapes_all_collapse_to_invalid_request
    """
    ctx = build_chain(api, upto=4)

    unknown_field = f.item_payload(ctx["gap_id"])
    unknown_field["retail_price_cents"] = 399
    validate_error(
        api.create_item(unknown_field, SOURCING_HEADERS),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )
    validate_error(
        api.create_item(
            f.item_payload(ctx["gap_id"], tier="SUPER_PREMIUM"), SOURCING_HEADERS
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )
    validate_error(
        api.list_items(
            SOURCING_HEADERS,
            params={"gap_id": ctx["gap_id"], "limit": 101, "offset": 0},
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )
    validate_error(
        api.create_supplier(
            f.supplier_payload(
                ctx["program_id"], gfsi_certificate_expiry="30/06/2027"
            ),
            SOURCING_HEADERS,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )

    _items, item_meta = validate_paginated(
        api.list_items(SOURCING_HEADERS, params={"gap_id": ctx["gap_id"]})
    )
    assert item_meta["total_count"] == 0, "no malformed create persisted an item"
    _suppliers, supplier_meta = validate_paginated(
        api.list_suppliers(SOURCING_HEADERS, params={"program_id": ctx["program_id"]})
    )
    assert supplier_meta["total_count"] == 0
    assert_shelf_slots(
        read_gap(api, ctx["gap_id"]),
        slots_consumed=0,
        slots_open=2,
        shelf_slots_quota=2,
    )
    assert_budget_ledger(
        read_budget_ledger(api, ctx["program_id"]), active_item_count=0
    )
