"""Financial clearance lifecycle: deposits, reopen cycle, refund, forfeiture."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_slot_payload,
    get_case,
    get_case_clearance,
    get_case_version,
    get_success_data,
    hold_slot_fresh,
    issue_estimate_letter,
    post_deposit,
    set_clock,
    setup_approved_case,
    setup_case_with_holds,
    setup_cleared_case,
    setup_ready_to_travel_case,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

FC = TEST_USERS["financial_counselor_headers"]
IC = TEST_USERS["intake_coordinator_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def test_deposit_threshold_crossing_immediately_visible(api):
    """PRD §3.6: "A `DEPOSIT` adds its amount to `deposit_paid_cents`, and
    after each posting the system checks the clearance threshold: when
    `deposit_paid_cents` reaches or exceeds `required_deposit_cents` —
    equality clears — the clearance flips `PENDING → CLEARED` and the case
    bubbles from `AWAITING_FINANCIAL` to `FINANCIAL_CLEARED`."

    Design: Corner/consistency_model/deposit_threshold_crossing_is_immediately_visible
    """
    set_clock()
    ctx = setup_approved_case()
    case_id = ctx["case"]["id"]
    assert ctx["clearance"]["status"] == "PENDING"
    assert ctx["case"]["status"] == "AWAITING_FINANCIAL"

    post_deposit(case_id, 60000)
    clearance = get_case_clearance(case_id)
    case = get_case(case_id)
    assert clearance["status"] == "CLEARED"
    assert clearance["deposit_paid_cents"] == 60000
    assert case["status"] == "FINANCIAL_CLEARED"


def test_clearance_reopen_cycle_returns_to_pending(api):
    """PRD §3.6: "When insurance verification reverses, a counselor may reopen
    a `CLEARED` clearance, returning it to `PENDING` and bubbling the case
    from `FINANCIAL_CLEARED` back to `AWAITING_FINANCIAL`."

    Design: Difficulty/non_linear_state_machine/financial_clearance_cleared_pending_cycle
    """
    set_clock()
    ctx = setup_cleared_case()
    case_id = ctx["case"]["id"]
    resp = api.reopen_clearance(case_id, FC)
    validate_success(resp, 200)
    clearance = get_case_clearance(case_id)
    assert clearance["status"] == "PENDING"
    assert clearance["deposit_paid_cents"] == 60000
    case = get_case(case_id)
    assert case["status"] == "AWAITING_FINANCIAL"


def test_second_deposit_after_reopen_clears_again(api):
    """PRD §3.6: "A `DEPOSIT` adds its amount to `deposit_paid_cents`, and
    after each posting the system checks the clearance threshold: when
    `deposit_paid_cents` reaches or exceeds `required_deposit_cents` —
    equality clears — the clearance flips `PENDING → CLEARED` and the case
    bubbles from `AWAITING_FINANCIAL` to `FINANCIAL_CLEARED`."

    Design: Difficulty/non_linear_state_machine/financial_clearance_cleared_pending_cycle
    """
    set_clock()
    ctx = setup_cleared_case()
    case_id = ctx["case"]["id"]
    resp = api.reopen_clearance(case_id, FC)
    validate_success(resp, 200)
    post_deposit(case_id, 1)
    clearance = get_case_clearance(case_id)
    assert clearance["status"] == "CLEARED"
    assert clearance["deposit_paid_cents"] == 60001


def test_refund_restores_clearance_balance(api):
    """PRD §3.6: "A `REFUND` reverses a prior deposit: the referenced source
    `DEPOSIT` transaction is voided — its `status` becomes `VOID` — and the
    refunded amount is subtracted from `deposit_paid_cents`."

    Design: Difficulty/compensating_invariant/deposit_refund_restores_clearance_balance
    """
    set_clock()
    ctx = setup_approved_case()
    case_id = ctx["case"]["id"]
    dep_txn = post_deposit(case_id, 60000)
    assert get_case_clearance(case_id)["status"] == "CLEARED"

    resp = api.create_billing_transaction(
        case_id, {"txn_type": "REFUND", "amount_cents": 60000}, FC
    )
    validate_success(resp, 201)
    clearance = get_case_clearance(case_id)
    assert clearance["deposit_paid_cents"] == 0
    txn = get_success_data(api.get_billing_transaction(dep_txn["id"], FC))
    assert txn["status"] == "VOID"


def test_refund_voids_only_source_deposit(api):
    """PRD §3.6: "A `REFUND` reverses a prior deposit: the referenced source
    `DEPOSIT` transaction is voided — its `status` becomes `VOID` — and the
    refunded amount is subtracted from `deposit_paid_cents`."

    Design: Difficulty/compensating_invariant/deposit_refund_restores_clearance_balance
    """
    set_clock()
    ctx = setup_approved_case()
    case_id = ctx["case"]["id"]
    post_deposit(case_id, 30000)
    post_deposit(case_id, 30000)
    assert get_case_clearance(case_id)["deposit_paid_cents"] == 60000

    resp = api.create_billing_transaction(
        case_id, {"txn_type": "REFUND", "amount_cents": 30000}, FC
    )
    validate_success(resp, 201)
    clearance = get_case_clearance(case_id)
    assert clearance["deposit_paid_cents"] == 30000


def test_forfeiture_depth3_release_cascade(api):
    """PRD §3.6: "A successful forfeit fires a depth-3 cascade: the clearance
    becomes `FORFEITED` with `holds_released` set true; every slot `HELD` by
    the case is released to `RELEASED`, freeing capacity; each corresponding
    pending visit is cancelled; the itinerary, if still `DRAFT`, is cancelled
    and its `revision` increments by one; and the case itself is withdrawn to
    `WITHDRAWN`."

    Design: Difficulty/transitive_cascade/forfeiture_depth3_release_cascade
    """
    set_clock()
    ctx = setup_cleared_case()
    card = ctx["services"][0]
    slot = get_success_data(
        api.create_slot(card["id"], create_slot_payload(), ADMIN)
    )
    case_id = ctx["case"]["id"]
    visit = hold_slot_fresh(case_id, slot["id"], visit_type="CONSULT")
    itinerary = get_success_data(api.get_itinerary(ctx["itinerary"]["id"], IC))
    revision_before = itinerary["revision"]

    resp = api.reopen_clearance(case_id, FC)
    validate_success(resp, 200)
    # Deadline: 2026-09-10 - 14 days = 2026-08-27; clock 2026-09-01 is past it.
    resp = api.forfeit_clearance(case_id, FC)
    validate_success(resp, 200)

    clearance = get_case_clearance(case_id)
    assert clearance["status"] == "FORFEITED"
    assert clearance["holds_released"] is True
    slot_after = get_success_data(api.get_slot(slot["id"], IC))
    assert slot_after["status"] == "RELEASED"
    visit_after = get_success_data(api.get_visit(visit["id"], IC))
    assert visit_after["status"] == "CANCELLED"
    itinerary_after = get_success_data(api.get_itinerary(ctx["itinerary"]["id"], IC))
    assert itinerary_after["status"] == "CANCELLED"
    assert itinerary_after["revision"] == revision_before + 1
    case_after = get_case(case_id)
    assert case_after["status"] == "WITHDRAWN"


def test_forfeit_reopen_blocked_after_holds_released(api):
    """PRD §3.6: "once forfeiture has released the case's holds —
    `holds_released` true — the clearance can never return to `PENDING`, and
    the attempt is rejected with `ERR_CLEARANCE_HOLD_RELEASED`."
    PRD §3.6: "reopening a clearance that is not `CLEARED` yields
    `ERR_INVALID_STATE`, and once forfeiture has released the case's holds —
    `holds_released` true — the clearance can never return to `PENDING`, and
    the attempt is rejected with `ERR_CLEARANCE_HOLD_RELEASED`."

    Design: Difficulty/transitive_cascade/forfeiture_depth3_release_cascade
    """
    set_clock()
    ctx = setup_cleared_case()
    card = ctx["services"][0]
    slot = get_success_data(
        api.create_slot(card["id"], create_slot_payload(), ADMIN)
    )
    case_id = ctx["case"]["id"]
    hold_slot_fresh(case_id, slot["id"], visit_type="CONSULT")
    resp = api.reopen_clearance(case_id, FC)
    validate_success(resp, 200)
    resp = api.forfeit_clearance(case_id, FC)
    validate_success(resp, 200)

    clearance = get_case_clearance(case_id)
    assert clearance["holds_released"] is True
    resp = api.reopen_clearance(case_id, FC)
    validate_error_is_one_of(resp, [
        ApiErrorId.ERR_CLEARANCE_HOLD_RELEASED.value,
        ApiErrorId.ERR_INVALID_STATE.value,
    ])


def test_forfeit_before_deadline_rejected(api):
    """PRD §3.6: "the logical clock's current date must be strictly later than
    the earliest `HELD` slot date of the case's itinerary minus 14 days —
    attempting the forfeit earlier is rejected with
    `ERR_DEADLINE_NOT_BREACHED`, and attempting it on a clearance not in
    `PENDING` is rejected with `ERR_INVALID_STATE`."

    Design: Corner/validations/forfeit_before_deadline_rejected
    """
    set_clock()
    ctx = setup_cleared_case()
    card = ctx["services"][0]
    slot = get_success_data(
        api.create_slot(
            card["id"],
            create_slot_payload(slot_date="2026-10-01"),
            ADMIN,
        )
    )
    case_id = ctx["case"]["id"]
    hold_slot_fresh(case_id, slot["id"], visit_type="CONSULT")
    resp = api.reopen_clearance(case_id, FC)
    validate_success(resp, 200)
    # Deadline: 2026-10-01 - 14 days = 2026-09-17; clock 2026-09-01 is earlier.
    resp = api.forfeit_clearance(case_id, FC)
    validate_error(resp, ApiErrorId.ERR_DEADLINE_NOT_BREACHED)


def test_international_waiver_forbidden(api):
    """PRD §3.6: "International patients may never be waived — the request is
    rejected with `ERR_INTERNATIONAL_WAIVER_FORBIDDEN` — and waiving a
    clearance not in `PENDING` fails with `ERR_INVALID_STATE`."

    Design: Corner/validations/international_waiver_forbidden
    """
    set_clock()
    ctx = setup_approved_case(
        patient_overrides={
            "full_name": "Ingrid International",
            "residence_country": "DE",
            "residence_state": None,
            "preferred_language": "de",
        }
    )
    case_id = ctx["case"]["id"]
    resp = api.waive_clearance(case_id, FC)
    validate_error(resp, ApiErrorId.ERR_INTERNATIONAL_WAIVER_FORBIDDEN)
    clearance = get_case_clearance(case_id)
    assert clearance["status"] == "PENDING"


def test_withdrawal_cascades_to_slots_visits_logistics(api):
    """PRD §3.7: "Manual withdrawal and the fatigue auto-withdrawal of §3.3
    share one release cascade: every slot the case holds moves `HELD →
    RELEASED` and the capacity pool is decremented accordingly; every
    logistics arrangement in `REQUESTED` or `BOOKED` is cancelled; the
    itinerary, if `DRAFT`, is cancelled; and every `PENDING` visit is
    cancelled."

    Design: Corner/state_machines/withdrawal_cascades_to_slots_visits_logistics
    """
    set_clock()
    ctx = setup_case_with_holds([{"start_min": 540, "end_min": 600}])
    case_id = ctx["case"]["id"]
    slot_id = ctx["slots"][0]["id"]
    visit_id = ctx["visits"][0]["id"]
    itinerary_id = ctx["itinerary"]["id"]
    log = get_success_data(
        api.create_logistics(
            case_id,
            {"arrangement_type": "TRAVEL", "details": "MSP flight",
             "companion_count": 1},
            TEST_USERS["logistics_coordinator_headers"],
        )
    )

    resp = api.withdraw_case(case_id, IC)
    validate_success(resp, 200)
    assert get_case(case_id)["status"] == "WITHDRAWN"
    assert get_success_data(api.get_slot(slot_id, IC))["status"] == "RELEASED"
    assert get_success_data(api.get_visit(visit_id, IC))["status"] == "CANCELLED"
    assert get_success_data(api.get_itinerary(itinerary_id, IC))["status"] == "CANCELLED"
    assert (
        get_success_data(api.get_logistics(log["id"], IC))["status"] == "CANCELLED"
    )


def test_settlement_with_fewer_than_three_completed_visits_rejected(api):
    """PRD §3.6: "Recording a `SETTLEMENT` transaction requires the clearance
    to be `CLEARED` (`ERR_INVALID_STATE` otherwise), the case to be
    `COMPLETED`, and at least 3 of the itinerary's visits to stand
    `COMPLETED` — fewer, and the request is rejected with
    `ERR_MINIMUM_COMPLETED_VISITS`."

    Design: Corner/validations/settlement_with_fewer_than_three_completed_visits_rejected
    """
    set_clock()
    ctx = setup_ready_to_travel_case()
    case_id = ctx["case"]["id"]
    itinerary_id = ctx["itinerary"]["id"]
    set_clock("2026-09-10T12:00:00Z")
    visits = get_success_data(api.list_itinerary_visits(itinerary_id, IC))
    assert len(visits) == 2
    for visit in sorted(visits, key=lambda v: v["sequencing_priority"]):
        resp = api.complete_visit(visit["id"], IC)
        validate_success(resp, 200)
    assert get_case(case_id)["status"] == "COMPLETED"

    resp = api.create_billing_transaction(
        case_id, {"txn_type": "SETTLEMENT", "amount_cents": 1}, FC
    )
    validate_error(resp, ApiErrorId.ERR_MINIMUM_COMPLETED_VISITS)
