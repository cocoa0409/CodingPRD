"""Supplier capacity commitments, orders, cancellation, commit cascade (PRD §3.2, §3.3)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    make_supplier_manager_headers,
    api_client,
    create_commitment_payload, place_order_payload,
    create_program, create_supplier, get_program,
    create_workforce_plan, hire,
    create_rate_case_in_state,
    setup_confirmed_commitment, setup_ordered_commitment, place_order,
    assert_commitment, assert_commitment_quantity_invariant,
)


def _setup_two_ordered_commitments(program_id):
    """Two suppliers, each CONFIRMED at rate 8 with a 10-unit order at assumed rate 8."""
    supplier_eng, commitment_eng = setup_confirmed_commitment(
        program_id, component_code="ENG", committed_rate=8
    )
    commitment_eng = place_order(
        commitment_eng["id"], supplier_eng["id"], quantity=10, assumed_rate_per_month=8
    )
    supplier_lg, commitment_lg = setup_confirmed_commitment(
        program_id, component_code="LG", committed_rate=8
    )
    commitment_lg = place_order(
        commitment_lg["id"], supplier_lg["id"], quantity=10, assumed_rate_per_month=8
    )
    return (supplier_eng, commitment_eng), (supplier_lg, commitment_lg)


def test_rate_commit_flips_atrisk_reprices_reserve_and_autoshelves(api, admin_headers, planner_headers):
    """PRD §3.2: "Second, commitments re-rate: every commitment of the program in `ORDERED`
    whose `assumed_rate_at_order` exceeds the newly committed rate flips to `AT_RISK`, and
    every commitment in `AT_RISK` whose `assumed_rate_at_order` is less than or equal to the
    new rate recovers to `ORDERED`."
    PRD §3.3: "Every `AT_RISK` commitment contributes a projected penalty of thirty percent
    of its `active_ordered_quantity` times `unit_price_cents`, rounded half-up per
    commitment before any summation; every `CANCELLED` commitment contributes its recorded
    `cancellation_penalty_cents`; `CONFIRMED` and `ORDERED` commitments contribute nothing."
    PRD §3.2: "Fourth, the program's `posture` is recomputed — and if it lands on
    `DISTRESSED`, every other case of the same program still sitting in `GATED_REVIEW` is
    auto-shelved to `SHELVED`."
    PRD §2.9: "It is `DISTRESSED` when any of the following holds: the `readiness_index`
    is below 60.0; any `CRITICAL` quality escape on a program aircraft is in `OPEN`,
    `ROOT_CAUSE`, or `DISPOSITIONED`; the `open_escape_count` is 3 or more; or any
    commitment of the program is `AT_RISK`."

    Design: Difficulty/transitive_cascade/rate_commit_atrisk_reserve_posture_autoshelve_chain
    """
    program = create_program(required_component_codes=2)
    (supplier_eng, _), (supplier_lg, _) = _setup_two_ordered_commitments(program["id"])
    plan = create_workforce_plan(program["id"], skill_code="AVIONICS", required_headcount=10)
    hire(plan["id"], 10)

    case_a = create_rate_case_in_state(program["id"], "GATED_REVIEW", proposed_rate=4)
    assert case_a["gating_verdict"] == "PASS"
    case_b = create_rate_case_in_state(program["id"], "GATED_REVIEW", proposed_rate=6)
    assert case_b["gating_verdict"] == "PASS"

    case_a = validate_success(api_client.commit_rate_case(case_a["id"], planner_headers))
    assert case_a["status"] == "COMMITTED"

    program = get_program(program["id"])
    assert program["current_rate_per_month"] == 4
    eng, _ = validate_paginated(
        api_client.list_supplier_commitments(supplier_eng["id"], admin_headers)
    )
    assert eng[0]["status"] == "AT_RISK", "assumed rate 8 exceeds committed rate 4"
    lg, _ = validate_paginated(
        api_client.list_supplier_commitments(supplier_lg["id"], admin_headers)
    )
    assert lg[0]["status"] == "AT_RISK"
    assert program["cancellation_reserve_cents"] == 6000000, (
        "2 x round(0.30 x 10 x 1000000)"
    )
    assert program["posture"] == "DISTRESSED"

    shelved, meta = validate_paginated(
        api_client.list_rate_cases(program["id"], planner_headers, params={"status": "SHELVED"})
    )
    assert meta["total_count"] == 1
    assert shelved[0]["id"] == case_b["id"], (
        "the other GATED_REVIEW case was auto-shelved by the DISTRESSED posture"
    )


def test_rate_commit_recovers_atrisk_commitments_when_rate_rises(api, admin_headers, planner_headers):
    """PRD §3.2: "every commitment in `AT_RISK` whose `assumed_rate_at_order` is less than
    or equal to the new rate recovers to `ORDERED`."
    PRD §3.3: "`CONFIRMED` and `ORDERED` commitments contribute nothing."
    PRD §2.9: "Otherwise it is `STABLE` when the `readiness_index` is at least 85.0 and the
    `open_escape_count` is zero."

    Design: Difficulty/transitive_cascade/rate_commit_atrisk_reserve_posture_autoshelve_chain
    """
    program = create_program(required_component_codes=2)
    (supplier_eng, _), (supplier_lg, _) = _setup_two_ordered_commitments(program["id"])
    plan = create_workforce_plan(program["id"], skill_code="AVIONICS", required_headcount=10)
    hire(plan["id"], 10)

    case_a = create_rate_case_in_state(program["id"], "GATED_REVIEW", proposed_rate=4)
    validate_success(api_client.commit_rate_case(case_a["id"], planner_headers))
    assert get_program(program["id"])["posture"] == "DISTRESSED"

    case_c = create_rate_case_in_state(program["id"], "GATED_REVIEW", proposed_rate=8)
    assert case_c["gating_verdict"] == "PASS"
    case_c = validate_success(api_client.commit_rate_case(case_c["id"], planner_headers))
    assert case_c["status"] == "COMMITTED"

    program = get_program(program["id"])
    assert program["current_rate_per_month"] == 8
    eng, _ = validate_paginated(
        api_client.list_supplier_commitments(supplier_eng["id"], admin_headers)
    )
    assert eng[0]["status"] == "ORDERED", "assumed rate 8 is <= the newly committed 8"
    lg, _ = validate_paginated(
        api_client.list_supplier_commitments(supplier_lg["id"], admin_headers)
    )
    assert lg[0]["status"] == "ORDERED"
    assert program["cancellation_reserve_cents"] == 0
    assert program["posture"] == "STABLE"


def test_place_order_then_cancel_conserves_ordered_quantity(api):
    """PRD §3.3: "Ordering (`CONFIRMED` → `ORDERED`, and repeatable from `ORDERED` or
    `AT_RISK` as a top-up) takes a `quantity`, an `assumed_rate_per_month`, and a
    `required_by_month`; each call adds `quantity` into `ordered_quantity`, overwrites
    `assumed_rate_at_order` with the payload's rate assumption, and lands the commitment in
    `ORDERED`."
    PRD §3.3: "A fresh commitment shows `ordered_quantity` and `cancelled_quantity` at zero,
    so `active_ordered_quantity` — ordered minus cancelled — starts at zero as well"
    PRD §3.3: "Cancelling adds the quantity into `cancelled_quantity`, records a
    `cancellation_penalty_cents` of thirty percent of the cancelled quantity times
    `unit_price_cents`, rounded half-up to integer cents, and recomputes the program's
    reserve."

    Design: Difficulty/compensating_invariant/place_order_then_cancel_conserves_ordered_quantity
    """
    program = create_program()
    supplier, commitment = setup_confirmed_commitment(program["id"])
    sm_headers = make_supplier_manager_headers(supplier["id"])

    commitment = place_order(commitment["id"], supplier["id"], quantity=10,
                             assumed_rate_per_month=8)
    assert commitment["ordered_quantity"] == 10
    assert commitment["active_ordered_quantity"] == 10
    assert commitment["cancelled_quantity"] == 0

    commitment = place_order(commitment["id"], supplier["id"], quantity=5,
                             assumed_rate_per_month=8)
    assert commitment["ordered_quantity"] == 15
    assert commitment["active_ordered_quantity"] == 15
    assert commitment["cancelled_quantity"] == 0

    commitment = validate_success(
        api_client.cancel_commitment(commitment["id"], sm_headers, {"cancel_quantity": 15})
    )
    assert commitment["status"] == "CANCELLED"
    assert commitment["ordered_quantity"] == 15
    assert commitment["active_ordered_quantity"] == 0
    assert commitment["cancelled_quantity"] == 15
    assert commitment["cancellation_penalty_cents"] == 4500000, "0.30 x 15 x 1000000"
    assert_commitment_quantity_invariant(commitment)


def test_cancel_with_omitted_quantity_defaults_to_full_active(api):
    """PRD §3.3: "The `cancel_quantity` may be omitted, in which case it defaults to the
    full `active_ordered_quantity`; when provided it must equal `active_ordered_quantity`
    exactly, else `ERR_CANCEL_QUANTITY_INVALID` (422) — partial cancellations do not exist."
    PRD §3.3: "Cancelling adds the quantity into `cancelled_quantity`, records a
    `cancellation_penalty_cents` of thirty percent of the cancelled quantity times
    `unit_price_cents`, rounded half-up to integer cents, and recomputes the program's
    reserve."

    Design: Difficulty/compensating_invariant/place_order_then_cancel_conserves_ordered_quantity
    """
    program = create_program()
    supplier, commitment = setup_ordered_commitment(program["id"], quantity=10,
                                                    assumed_rate_per_month=8)
    sm_headers = make_supplier_manager_headers(supplier["id"])
    commitment = validate_success(api_client.cancel_commitment(commitment["id"], sm_headers))
    assert commitment["status"] == "CANCELLED"
    assert commitment["ordered_quantity"] == 10
    assert commitment["active_ordered_quantity"] == 0
    assert commitment["cancelled_quantity"] == 10, "omitted cancel_quantity took the full active quantity"
    assert commitment["cancellation_penalty_cents"] == 3000000, "0.30 x 10 x 1000000"
    assert_commitment_quantity_invariant(commitment)


def test_place_order_lead_time_violation_beats_quantity_cap(api):
    """PRD §2.8: "Where several rungs could fire on a single request, the lower-numbered
    rung's error is the one returned."
    PRD §3.3: "Temporally, `required_by_month` must be at least `lead_time_months` calendar
    months beyond the current logical month — a tighter window is rejected
    `ERR_LEAD_TIME_VIOLATION` (422)."
    PRD §3.3: "Fiscally, `quantity` must be at least one and no more than
    `committed_rate_per_month` multiplied by `lead_time_months` — anything outside that band
    is `ERR_ORDER_EXCEEDS_COMMITMENT` (422)."
    PRD §2.4: "At startup the clock reads exactly `2026-09-01T00:00:00Z`, and it holds that
    reading until a `ProgramAdmin` moves it."

    Design: Difficulty/priority_pair_validation_conflict/place_order_lead_time_beats_quantity_cap
    """
    program = create_program()
    supplier, commitment = setup_confirmed_commitment(program["id"])
    # current logical month 2026-09 + lead 4 -> earliest legal 2027-01; 2026-10 violates it
    # AND quantity 999 violates the 8 x 4 == 32 cap: the temporal rung wins.
    resp = api_client.place_order(
        commitment["id"],
        place_order_payload(quantity=999, assumed_rate_per_month=8,
                            required_by_month="2026-10"),
        make_supplier_manager_headers(supplier["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_LEAD_TIME_VIOLATION)


def test_place_order_lead_time_beats_quantity_cap_second_pair(api):
    """PRD §2.8: "Where several rungs could fire on a single request, the lower-numbered
    rung's error is the one returned."
    PRD §3.3: "Temporally, `required_by_month` must be at least `lead_time_months` calendar
    months beyond the current logical month — a tighter window is rejected
    `ERR_LEAD_TIME_VIOLATION` (422)."
    PRD §3.3: "Fiscally, `quantity` must be at least one and no more than
    `committed_rate_per_month` multiplied by `lead_time_months` — anything outside that band
    is `ERR_ORDER_EXCEEDS_COMMITMENT` (422)."

    Design: Difficulty/priority_pair_validation_conflict/place_order_lead_time_beats_quantity_cap
    """
    program = create_program()
    supplier, commitment = setup_confirmed_commitment(program["id"])
    # 2026-11 is only two months beyond 2026-09 (< lead 4); quantity 100 also exceeds 32.
    resp = api_client.place_order(
        commitment["id"],
        place_order_payload(quantity=100, assumed_rate_per_month=8,
                            required_by_month="2026-11"),
        make_supplier_manager_headers(supplier["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_LEAD_TIME_VIOLATION)


def test_commitment_confirm_twice_rejected(api):
    """PRD §3.3: "Confirmation moves the commitment `DRAFT` → `CONFIRMED`."
    PRD §2.8: "the requested transition must exist from the resource's current state,
    including terminal-state lockdown and the delivery-pipeline stage gates
    (`ERR_INVALID_TRANSITION`, 409)".

    Design: Corner/state_machines/commitment_confirm_twice_rejected
    """
    program = create_program()
    supplier = create_supplier()
    sm_headers = make_supplier_manager_headers(supplier["id"])
    commitment = validate_success(
        api_client.create_capacity_commitment(
            supplier["id"], create_commitment_payload(program["id"]), sm_headers
        ),
        201,
    )
    assert commitment["status"] == "DRAFT"
    commitment = validate_success(api_client.confirm_commitment(commitment["id"], sm_headers))
    assert commitment["status"] == "CONFIRMED"
    resp = api_client.confirm_commitment(commitment["id"], sm_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)


def test_cancel_partial_quantity_rejected(api):
    """PRD §3.3: "The `cancel_quantity` may be omitted, in which case it defaults to the
    full `active_ordered_quantity`; when provided it must equal `active_ordered_quantity`
    exactly, else `ERR_CANCEL_QUANTITY_INVALID` (422) — partial cancellations do not exist."

    Design: Corner/validations/cancel_partial_quantity_rejected
    """
    program = create_program()
    supplier, commitment = setup_ordered_commitment(program["id"], quantity=10,
                                                    assumed_rate_per_month=8)
    resp = api_client.cancel_commitment(
        commitment["id"],
        make_supplier_manager_headers(supplier["id"]),
        {"cancel_quantity": 3},
    )
    validate_error(resp, ApiErrorId.ERR_CANCEL_QUANTITY_INVALID)


def test_place_order_quantity_over_cap_rejected(api):
    """PRD §3.3: "Fiscally, `quantity` must be at least one and no more than
    `committed_rate_per_month` multiplied by `lead_time_months` — anything outside that band
    is `ERR_ORDER_EXCEEDS_COMMITMENT` (422)."
    PRD §2.4: "At startup the clock reads exactly `2026-09-01T00:00:00Z`, and it holds that
    reading until a `ProgramAdmin` moves it."

    Design: Corner/validations/place_order_quantity_over_cap_rejected
    """
    program = create_program()
    supplier, commitment = setup_confirmed_commitment(program["id"])
    # required_by_month 2027-01 is exactly lead_time_months (4) beyond 2026-09: legal;
    # quantity 33 exceeds the 8 x 4 == 32 cap.
    resp = api_client.place_order(
        commitment["id"],
        place_order_payload(quantity=33, assumed_rate_per_month=8,
                            required_by_month="2027-01"),
        make_supplier_manager_headers(supplier["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ORDER_EXCEEDS_COMMITMENT)


def test_place_order_lead_time_exactly_met_allowed(api):
    """PRD §3.3: "Temporally, `required_by_month` must be at least `lead_time_months`
    calendar months beyond the current logical month — a tighter window is rejected
    `ERR_LEAD_TIME_VIOLATION` (422)."
    PRD §3.3: "Fiscally, `quantity` must be at least one and no more than
    `committed_rate_per_month` multiplied by `lead_time_months` — anything outside that band
    is `ERR_ORDER_EXCEEDS_COMMITMENT` (422)."
    PRD §2.4: "At startup the clock reads exactly `2026-09-01T00:00:00Z`, and it holds that
    reading until a `ProgramAdmin` moves it."

    Design: Corner/validations/place_order_lead_time_exactly_met_allowed
    """
    program = create_program()
    supplier, commitment = setup_confirmed_commitment(program["id"])
    # 2026-09 + 4 calendar months == 2027-01 exactly (inclusive); quantity 32 == 8 x 4.
    commitment = validate_success(
        api_client.place_order(
            commitment["id"],
            place_order_payload(quantity=32, assumed_rate_per_month=8,
                                required_by_month="2027-01"),
            make_supplier_manager_headers(supplier["id"]),
        )
    )
    assert commitment["status"] == "ORDERED"
    assert commitment["ordered_quantity"] == 32
    assert commitment["assumed_rate_at_order"] == 8


def test_supplier_manager_ownership_mismatch_rejected(api, admin_headers):
    """PRD §2.1: "When `X-User-Role` is `SupplierManager`, `X-User-ID` is the `id` of the
    acting Supplier: on supplier-scoped writes — every commitment create, confirm, order,
    and cancel — the server compares the commitment's `supplier_id` against `X-User-ID`,
    and a mismatch is rejected with `ERR_UNAUTHORIZED_ROLE`."

    Design: Corner/rbac/supplier_manager_ownership_mismatch_rejected
    """
    program = create_program()
    supplier_one = create_supplier(supplier_code="S1", name="Engines Co", region="NA")
    supplier_two = create_supplier(supplier_code="S2", name="Landing Co", region="EU")
    resp = api_client.create_capacity_commitment(
        supplier_one["id"],
        create_commitment_payload(program["id"]),
        make_supplier_manager_headers(supplier_two["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
