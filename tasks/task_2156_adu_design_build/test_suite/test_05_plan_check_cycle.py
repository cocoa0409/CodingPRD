"""Filing a permit package and surviving plan check: the corrections loop and its cascade."""
from test_helpers import (
    ApiErrorId, validate_success, validate_error, validate_paginated,
    assert_permit_submittal, assert_correction_item, assert_availability,
    setup_feasibility_cleared_project, setup_under_plan_check_project,
    setup_permitted_project, setup_corrections_round,
    register_inspector, add_utility_connection, prepare_submittal, file_submittal,
    list_corrections, resolve_correction, read_project,
    setup_scheduled_phase, book_inspection, move_clock,
    DESIGN_LEAD, PLAN_CHECKER, PROJECT_MANAGER,
)

BLOCKING_ITEM = {"discipline": "STRUCTURAL", "severity": "BLOCKING",
                 "description": "Shear wall schedule missing on sheet S2"}
ADVISORY_ITEM = {"discipline": "PLANNING", "severity": "ADVISORY",
                 "description": "Label the trash enclosure on the site plan"}


def test_resubmitting_a_corrected_package_reopens_plan_check(api):
    """PRD §3.4: "Returning the corrected package to plan check moves the submittal
    `CORRECTIONS_REQUIRED → UNDER_PLAN_CHECK`, increases both `cycle_number` and
    `design_revision` by 1, clears `correction_deadline_date` back to null, and moves the
    project `DESIGN_REVISION → PERMITTING`."
    PRD §3.4: "This is the loop: a package can go around
    `UNDER_PLAN_CHECK → CORRECTIONS_REQUIRED → UNDER_PLAN_CHECK` once per correction round,
    with `design_revision` counting the rounds."

    Design: Difficulty/non_linear_state_machine/permit_submittal_correction_cycle
    """
    ctx = setup_corrections_round(api, [BLOCKING_ITEM, ADVISORY_ITEM])
    blocking = list_corrections(api, ctx["submittal"]["id"], {"severity": "BLOCKING"})[0]
    resolve_correction(api, blocking["id"])

    resubmitted = validate_success(
        api.resubmit_permit_submittal(ctx["submittal"]["id"], DESIGN_LEAD))

    assert_permit_submittal(resubmitted)
    assert resubmitted["status"] == "UNDER_PLAN_CHECK"
    assert resubmitted["cycle_number"] == 2, "the second plan-check round"
    assert resubmitted["design_revision"] == 2


def test_resubmission_clears_the_deadline_and_returns_the_project_to_permitting(api):
    """PRD §3.4: "A `DesignLead` clears individual corrections one at a time, moving a row
    `OPEN → RESOLVED` and stamping `resolved_on_date` from the logical clock."
    PRD §3.4: "Returning the corrected package to plan check moves the submittal
    `CORRECTIONS_REQUIRED → UNDER_PLAN_CHECK`, increases both `cycle_number` and
    `design_revision` by 1, clears `correction_deadline_date` back to null, and moves the
    project `DESIGN_REVISION → PERMITTING`."

    Design: Difficulty/non_linear_state_machine/permit_submittal_correction_cycle
    """
    ctx = setup_corrections_round(api, [BLOCKING_ITEM, ADVISORY_ITEM])
    assert ctx["project"]["status"] == "DESIGN_REVISION"
    blocking = list_corrections(api, ctx["submittal"]["id"], {"severity": "BLOCKING"})[0]

    resolved = resolve_correction(api, blocking["id"])
    assert_correction_item(resolved)
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolved_on_date"] == "2026-08-01", (
        "the logical clock reads 2026-08-01 until an operator moves it")

    resubmitted = validate_success(
        api.resubmit_permit_submittal(ctx["submittal"]["id"], DESIGN_LEAD))
    assert resubmitted["correction_deadline_date"] is None

    project = read_project(api, ctx["project"]["id"])
    assert project["status"] == "PERMITTING"


def test_corrections_letter_blocks_the_scheduled_phase_and_cancels_its_inspection(api):
    """PRD §2.9: "The **plan-check correction chain** has four links. A corrections letter on
    a submittal under plan check creates the correction rows; because the submittal entered
    its corrections state, the owning project moves from `PERMITTING` to `DESIGN_REVISION`;
    because the project left `PERMITTING`, every construction phase of that project that was
    `SCHEDULED` moves to `BLOCKED` and gives up its window; and because each of those phases
    entered `BLOCKED`, every inspection appointment on them that was still `SCHEDULED` or
    `PARTIAL` is `CANCELLED`, releasing the inspector's slot."
    PRD §3.4: "From there the four-link cascade of §2.9 runs in full: the project moves
    `PERMITTING → DESIGN_REVISION`; every construction phase of the project sitting in
    `SCHEDULED` moves to `BLOCKED` with both `window_start_date` and `window_end_date` cleared
    to null, processed oldest first; and every inspection appointment on each of those phases
    that was `SCHEDULED` or `PARTIAL` moves to `CANCELLED`, releasing the inspector's slot on
    its `slot_date`, again processed oldest first."

    Design: Difficulty/transitive_cascade/plan_check_corrections_chain
    """
    ctx = setup_permitted_project(api)
    inspector = register_inspector(api, ctx["jurisdiction"]["id"])
    phase = setup_scheduled_phase(api, ctx)
    appointment = book_inspection(api, phase["id"], inspector["id"])
    revision = prepare_submittal(api, ctx["project"]["id"], design_sheet_count=4)
    file_submittal(api, revision["id"])

    letter = validate_success(api.record_plan_check_result(
        revision["id"],
        {"outcome": "CORRECTIONS_REQUIRED",
         "correction_items": [{"discipline": "ENERGY", "severity": "BLOCKING",
                               "description": "Revised Title 24 report does not match the "
                                              "new window schedule"}]},
        PLAN_CHECKER))

    assert letter["status"] == "CORRECTIONS_REQUIRED"
    assert read_project(api, ctx["project"]["id"])["status"] == "DESIGN_REVISION"

    blocked = validate_success(api.get_construction_phase(phase["id"], PROJECT_MANAGER))
    assert blocked["status"] == "BLOCKED"
    assert blocked["window_start_date"] is None
    assert blocked["window_end_date"] is None

    cancelled = validate_success(api.get_inspection_appointment(appointment["id"], PROJECT_MANAGER))
    assert cancelled["status"] == "CANCELLED"


def test_corrections_letter_releases_the_slot_and_spares_the_approved_permit(api):
    """PRD §3.4: "The submittal moves `UNDER_PLAN_CHECK → CORRECTIONS_REQUIRED` and its
    `correction_deadline_date` is set to the logical clock date advanced by the jurisdiction's
    `correction_response_days`."
    PRD §3.8: "Anyone may also ask what an inspector's day looks like by naming a `slot_date`,
    and the answer reports that inspector's `inspector_id`, the `slot_date` asked about, their
    `daily_capacity`, a `booked_count` counting only appointments still in `SCHEDULED` or
    `PARTIAL`, and the `remaining_slots` left over."

    Design: Difficulty/transitive_cascade/plan_check_corrections_chain
    """
    ctx = setup_permitted_project(api)
    inspector = register_inspector(api, ctx["jurisdiction"]["id"])
    phase = setup_scheduled_phase(api, ctx)
    book_inspection(api, phase["id"], inspector["id"])
    revision = prepare_submittal(api, ctx["project"]["id"], design_sheet_count=4)
    file_submittal(api, revision["id"])

    letter = validate_success(api.record_plan_check_result(
        revision["id"],
        {"outcome": "CORRECTIONS_REQUIRED",
         "correction_items": [{"discipline": "ENERGY", "severity": "BLOCKING",
                               "description": "Revised Title 24 report does not match the "
                                              "new window schedule"}]},
        PLAN_CHECKER))

    assert letter["correction_deadline_date"] == "2026-09-15", (
        "2026-08-01 advanced by the jurisdiction's 45 correction_response_days")

    day = validate_success(
        api.get_inspector_availability(inspector["id"], "2026-09-03", PROJECT_MANAGER))
    assert_availability(day, inspector["id"], "2026-09-03", daily_capacity=4, booked_count=0)

    original = validate_success(api.get_permit_submittal(ctx["submittal"]["id"], PLAN_CHECKER))
    assert original["status"] == "APPROVED", "the earlier submittal is untouched by the cascade"


def test_corrections_letter_carrying_an_empty_array_is_rejected(api):
    """PRD §3.4: "The request supplies a `correction_items` array; if that key is omitted, or
    present but empty, the letter is rejected with `ERR_NO_CORRECTIONS_ON_RECORD` (HTTP 409) —
    a corrections letter carrying zero corrections is not a corrections letter."

    Design: Difficulty/boundary_precision_check/corrections_letter_with_empty_item_array
    """
    ctx = setup_under_plan_check_project(api)

    validate_error(
        api.record_plan_check_result(
            ctx["submittal"]["id"],
            {"outcome": "CORRECTIONS_REQUIRED", "correction_items": []}, PLAN_CHECKER),
        ApiErrorId.ERR_NO_CORRECTIONS_ON_RECORD)

    rows, meta = validate_paginated(
        api.list_correction_items(ctx["submittal"]["id"], DESIGN_LEAD))
    assert meta["total_count"] == 0, "no correction rows may be created by a rejected letter"


def test_rejected_corrections_letter_leaves_the_submittal_under_plan_check(api):
    """PRD §3.4: "Filing the package with the jurisdiction moves the submittal from `PREPARED`
    to `UNDER_PLAN_CHECK`, sets its `cycle_number` to 1, and stamps `submitted_on_date` with
    the logical clock date."
    PRD §3.4: "The request supplies a `correction_items` array; if that key is omitted, or
    present but empty, the letter is rejected with `ERR_NO_CORRECTIONS_ON_RECORD` (HTTP 409) —
    a corrections letter carrying zero corrections is not a corrections letter."

    Design: Difficulty/boundary_precision_check/corrections_letter_with_empty_item_array
    """
    ctx = setup_under_plan_check_project(api)

    validate_error(
        api.record_plan_check_result(
            ctx["submittal"]["id"],
            {"outcome": "CORRECTIONS_REQUIRED", "correction_items": []}, PLAN_CHECKER),
        ApiErrorId.ERR_NO_CORRECTIONS_ON_RECORD)

    submittal = validate_success(api.get_permit_submittal(ctx["submittal"]["id"], PLAN_CHECKER))
    assert submittal["status"] == "UNDER_PLAN_CHECK"
    assert submittal["cycle_number"] == 1
    assert submittal["correction_deadline_date"] is None
    assert read_project(api, ctx["project"]["id"])["status"] == "PERMITTING"


def test_plan_check_result_on_an_unfiled_submittal_is_rejected(api):
    """PRD §3.4: "The submittal must be in `PREPARED`, or the answer is
    `ERR_SUBMITTAL_STATE_INVALID`."
    PRD §3.4: "Plan check answers with one of two outcomes, recorded by a `PlanChecker` who
    supplies `outcome`. An `APPROVED` outcome closes the permit: the submittal moves
    `UNDER_PLAN_CHECK → APPROVED`, `approved_on_date` is stamped from the logical clock, the
    project moves `PERMITTING → PERMITTED`, and the submittal's `total_permit_fee_cents` is
    copied onto the project's own `total_permit_fee_cents` field."

    Design: Corner/state_machines/plan_check_result_on_prepared_submittal_returns_submittal_state_invalid
    """
    ctx = setup_feasibility_cleared_project(api)
    submittal = prepare_submittal(api, ctx["project"]["id"])

    validate_error(
        api.record_plan_check_result(submittal["id"], {"outcome": "APPROVED"}, PLAN_CHECKER),
        ApiErrorId.ERR_SUBMITTAL_STATE_INVALID)

    unchanged = validate_success(api.get_permit_submittal(submittal["id"], PLAN_CHECKER))
    assert unchanged["status"] == "PREPARED"
    assert unchanged["approved_on_date"] is None
    assert read_project(api, ctx["project"]["id"])["status"] == "FEASIBILITY_CLEARED"


def test_lapsed_correction_window_expires_the_submittal_and_then_locks_it(api):
    """PRD §3.4: "Two gates apply, in this order. First the deadline: if the logical clock
    date is later than `correction_deadline_date`, the submittal is first moved
    `CORRECTIONS_REQUIRED → EXPIRED` — a persisted transition that clears
    `correction_deadline_date` to null and raises the submittal's `version` — and the resubmit
    call is then rejected with `ERR_CORRECTION_WINDOW_EXPIRED` (HTTP 409)."
    PRD §3.4: "Expiry is evaluated lazily, at the moment a resubmit is attempted, and
    `EXPIRED` is terminal."

    Design: Corner/state_machines/lapsed_correction_window_expires_submittal_then_rejects_resubmit
    """
    ctx = setup_corrections_round(api, [{"discipline": "PLANNING", "severity": "BLOCKING",
                                         "description": "Show the required parking replacement"}])
    assert ctx["submittal"]["correction_deadline_date"] == "2026-09-15"
    resolve_correction(api, ctx["corrections"][0]["id"])
    move_clock(api, "2026-09-16T08:00:00Z")

    validate_error(api.resubmit_permit_submittal(ctx["submittal"]["id"], DESIGN_LEAD),
                   ApiErrorId.ERR_CORRECTION_WINDOW_EXPIRED)

    expired = validate_success(api.get_permit_submittal(ctx["submittal"]["id"], PLAN_CHECKER))
    assert expired["status"] == "EXPIRED"
    assert expired["correction_deadline_date"] is None
    assert expired["cycle_number"] == 1
    assert expired["design_revision"] == 1

    validate_error(api.resubmit_permit_submittal(ctx["submittal"]["id"], DESIGN_LEAD),
                   ApiErrorId.ERR_SUBMITTAL_STATE_INVALID)
    assert read_project(api, ctx["project"]["id"])["status"] == "DESIGN_REVISION"


def test_resolving_a_correction_twice_is_rejected(api):
    """PRD §3.4: "A row that is already `RESOLVED` is rejected with
    `ERR_CORRECTION_ITEM_STATE_INVALID` (HTTP 409), and a correction may only be cleared while
    its parent submittal is actually in `CORRECTIONS_REQUIRED` — otherwise the answer is
    `ERR_SUBMITTAL_STATE_INVALID`."
    PRD §2.4: "`version` is an integer that starts at 1 when the row is created and increases
    by exactly 1 on every mutation of that row, whether the mutation was requested directly or
    arrived as a cascade from somewhere else."

    Design: Corner/state_machines/resolve_correction_item_twice_returns_correction_item_state_invalid
    """
    ctx = setup_corrections_round(api, [{"discipline": "FIRE", "severity": "BLOCKING",
                                         "description": "Add smoke and CO alarm locations"}])
    correction = ctx["corrections"][0]
    resolved = resolve_correction(api, correction["id"])

    validate_error(api.resolve_correction_item(correction["id"], DESIGN_LEAD),
                   ApiErrorId.ERR_CORRECTION_ITEM_STATE_INVALID)

    rows, _ = validate_paginated(api.list_correction_items(ctx["submittal"]["id"], DESIGN_LEAD))
    still_resolved = rows[0]
    assert still_resolved["status"] == "RESOLVED"
    assert still_resolved["version"] == 2, "one mutation only: OPEN -> RESOLVED"
    assert still_resolved["resolved_on_date"] == resolved["resolved_on_date"]


def test_resubmit_with_an_open_blocking_correction_is_rejected(api):
    """PRD §3.4: "Second, if any correction on the submittal still has `severity` `BLOCKING`
    and `status` `OPEN`, the resubmit is rejected with `ERR_BLOCKING_CORRECTIONS_OPEN`. A
    submittal carrying only `ADVISORY` corrections passes this check with none of them
    resolved."
    PRD §3.4: "Correction listings under a submittal may be narrowed by `severity` and by
    `status`."

    Design: Corner/errors/resubmit_with_open_blocking_correction_rejected
    """
    ctx = setup_corrections_round(api, [
        {"discipline": "STRUCTURAL", "severity": "BLOCKING",
         "description": "Provide the foundation detail"},
        {"discipline": "PLANNING", "severity": "ADVISORY", "description": "Add a north arrow"},
    ])
    advisory = list_corrections(api, ctx["submittal"]["id"], {"severity": "ADVISORY"})[0]
    resolve_correction(api, advisory["id"])

    validate_error(api.resubmit_permit_submittal(ctx["submittal"]["id"], DESIGN_LEAD),
                   ApiErrorId.ERR_BLOCKING_CORRECTIONS_OPEN)

    submittal = validate_success(api.get_permit_submittal(ctx["submittal"]["id"], PLAN_CHECKER))
    assert submittal["status"] == "CORRECTIONS_REQUIRED"
    assert submittal["cycle_number"] == 1
    assert submittal["design_revision"] == 1

    open_rows, open_meta = validate_paginated(api.list_correction_items(
        ctx["submittal"]["id"], DESIGN_LEAD, {"status": "OPEN"}))
    assert open_meta["total_count"] == 1
    assert open_rows[0]["severity"] == "BLOCKING"


def test_filing_without_a_title24_report_is_rejected(api):
    """PRD §3.4: "And `title24_compliant` must be true, or the answer is `ERR_TITLE24_MISSING`
    (HTTP 409)."
    PRD §3.4: "Preparing a design package is a `DesignLead` action that names
    `design_sheet_count`, the number of sheets in the package, which must be at least 1, and
    `title24_compliant`, a flag asserting that the package includes a passing Title 24 energy
    compliance report."

    Design: Corner/validations/submit_without_title24_returns_title24_missing
    """
    ctx = setup_feasibility_cleared_project(api)
    submittal = prepare_submittal(api, ctx["project"]["id"], title24_compliant=False)

    validate_error(api.submit_permit_submittal(submittal["id"], DESIGN_LEAD),
                   ApiErrorId.ERR_TITLE24_MISSING)

    unchanged = validate_success(api.get_permit_submittal(submittal["id"], PLAN_CHECKER))
    assert unchanged["status"] == "PREPARED"
    assert unchanged["cycle_number"] == 0
    assert read_project(api, ctx["project"]["id"])["status"] == "FEASIBILITY_CLEARED"


def test_filing_with_a_pending_utility_decision_is_rejected(api):
    """PRD §3.4: "Every utility record of the project must have left `PENDING_DECISION`, or
    the answer is `ERR_UTILITY_DECISION_PENDING` (HTTP 409)."
    PRD §3.4: "Four conditions guard the filing, evaluated in this order."

    Design: Corner/validations/submit_with_pending_utility_decision_returns_utility_decision_pending
    """
    ctx = setup_feasibility_cleared_project(api)
    add_utility_connection(api, ctx["project"]["id"], "ELECTRIC")
    submittal = prepare_submittal(api, ctx["project"]["id"], title24_compliant=True)

    validate_error(api.submit_permit_submittal(submittal["id"], DESIGN_LEAD),
                   ApiErrorId.ERR_UTILITY_DECISION_PENDING)

    rows, _ = validate_paginated(api.list_utility_connections(ctx["project"]["id"], DESIGN_LEAD))
    assert rows[0]["status"] == "PENDING_DECISION"
    unchanged = validate_success(api.get_permit_submittal(submittal["id"], PLAN_CHECKER))
    assert unchanged["status"] == "PREPARED"
    assert unchanged["utility_component_cents"] == 0
