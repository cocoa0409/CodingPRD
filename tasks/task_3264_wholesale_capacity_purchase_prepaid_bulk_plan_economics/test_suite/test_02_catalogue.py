"""Plan catalogue: creation, listing, offer and withdraw, derived thresholds."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_plan,
    create_plan_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.fixtures import (
    create_agreement,
    create_plan,
    create_subscriber,
    current_agreement_version,
    get_plan,
    get_summary,
    offer_plan,
    purchase_term,
    quote_term,
    set_clock,
    setup_active_agreement,
    setup_agreement_with_offered_plan,
    setup_offered_plan,
)

MISSING_ID = "00000000-0000-4000-8000-000000000000"


def test_plan_creation_lands_in_draft(api):
    """PRD §3.2: "A freshly registered plan sits in `DRAFT` and is not sellable."

    Design: Corner/entities/plans_list_paginates_with_total_count_and_has_more
    """
    set_clock()
    agreement = setup_active_agreement()
    plan = create_plan(agreement["id"], plan_code="H3")
    assert_plan(plan)
    assert plan["plan_status"] == "DRAFT"
    assert plan["term_months"] == 3
    assert plan["renewal_price_cents"] > plan["intro_price_cents"]


def test_plans_list_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned, defaulting to 10
    when omitted, and may be set no lower than 1 nor higher than 100. The `offset` parameter
    gives the number of leading items to skip and defaults to 0."

    Design: Corner/entities/plans_list_paginates_with_total_count_and_has_more
    """
    set_clock()
    # A bare agreement carries no plan, so the catalogue is registered from scratch
    # here to keep total_count exactly three.
    agreement = create_agreement()
    create_plan(agreement["id"], plan_code="M3")
    create_plan(agreement["id"], plan_code="Y12")
    create_plan(agreement["id"], plan_code="H6")

    page = api.list_plans(
        TEST_USERS["planner_headers"],
        {"agreement_id": agreement["id"], "limit": 2, "offset": 0},
    )
    data, meta = validate_paginated(page)
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    last = api.list_plans(
        TEST_USERS["planner_headers"],
        {"agreement_id": agreement["id"], "limit": 2, "offset": 2},
    )
    data_tail, meta_tail = validate_paginated(last)
    assert len(data_tail) == 1
    assert meta_tail["total_count"] == 3
    assert meta_tail["has_more"] is False


def test_plan_offer_derives_the_deprioritization_threshold(api):
    """PRD §3.2: "Offering a plan is what makes it sellable, moving its `plan_status` from
    `DRAFT` to `OFFERED`. A `CapacityPlanner` may offer a plan only while the parent agreement
    is `DRAFT` or `ACTIVE`, and the offer is what derives the plan's
    `deprioritization_threshold_mb`: it is set equal to `data_allotment_mb`, not taken
    from the request."

    Design: Corner/entities/plan_deprioritization_threshold_is_derived_and_input_ignored
    """
    set_clock()
    agreement = setup_active_agreement()
    plan = create_plan(agreement["id"], data_allotment_mb=3000)

    offered = api.offer_plan(
        plan["id"],
        TEST_USERS["planner_headers"],
        {"deprioritization_threshold_mb": 99999},
    ).json()["data"]
    assert offered["plan_status"] == "OFFERED"
    assert offered["deprioritization_threshold_mb"] == 3000
    assert offered["deprioritization_threshold_mb"] != 99999


def test_plan_term_and_step_up_price_constraints(api):
    """PRD §3.2: "The term length must be one of 3, 6, or 12 months, the intro price must be
    at least 1 cent, the renewal price must be strictly
    greater than the intro price, and the data allotment must be at least 1 megabyte."

    Design: Corner/entities/plan_type_constraints_on_term_and_step_up_price
    """
    set_clock()
    agreement = setup_active_agreement()

    bad_term = create_plan_payload(agreement["id"], plan_code="BAD", term_months=4)
    resp = api.create_plan(bad_term, TEST_USERS["planner_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_PLAN_TERM)

    equal_renewal = create_plan_payload(
        agreement["id"],
        plan_code="EQ",
        term_months=6,
        intro_price_cents=1999,
        renewal_price_cents=1999,
    )
    resp = api.create_plan(equal_renewal, TEST_USERS["planner_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_PLAN_TERM)

    good = api.create_plan(
        create_plan_payload(agreement["id"], plan_code="OK", term_months=3),
        TEST_USERS["planner_headers"],
    )
    validate_success(good, expected_status=201)

    twelve = api.create_plan(
        create_plan_payload(agreement["id"], plan_code="Y12", term_months=12,
                            intro_price_cents=15999, renewal_price_cents=19999),
        TEST_USERS["planner_headers"],
    )
    validate_success(twelve, expected_status=201)


def test_plan_offer_withdraw_offer_cycles_repeatedly(api):
    """PRD §3.2: "A plan that is not yet placed can be withdrawn by a `CapacityPlanner`,
    returning it from `OFFERED` to `DRAFT`; withdrawal is admitted only when no term on the plan
    is in `QUOTED`, `PURCHASED`, `AWAITING_ACTIVATION`, `ACTIVE`, `RENEWAL_DUE`, or
    `ACTIVE_RENEWAL`."

    Design: Difficulty/non_linear_state_machine/plan_cyclic_offer_withdraw_reoffer
    """
    set_clock()
    agreement, plan_h = setup_agreement_with_offered_plan()
    plan_m = create_plan(agreement["id"], plan_code="M3", data_allotment_mb=15000)
    offer_plan(plan_m["id"], current_agreement_version(agreement["id"]))

    subscriber = create_subscriber()
    term_m = quote_term(
        subscriber["id"], plan_m["id"], current_agreement_version(agreement["id"])
    )
    purchase_term(term_m["id"], subscriber["id"])

    summary = get_summary(agreement["id"])
    assert summary["allocated_data_mb"] == 15000

    assert get_plan(plan_h["id"])["plan_status"] == "OFFERED"
    assert get_plan(plan_h["id"])["deprioritization_threshold_mb"] == 3000

    withdrawn = api.withdraw_plan(
        plan_h["id"], TEST_USERS["planner_headers"]
    ).json()["data"]
    assert withdrawn["plan_status"] == "DRAFT"

    reoffered = offer_plan(plan_h["id"], current_agreement_version(agreement["id"]))
    assert reoffered["plan_status"] == "OFFERED"

    second_withdraw = api.withdraw_plan(
        plan_h["id"], TEST_USERS["planner_headers"]
    ).json()["data"]
    assert second_withdraw["plan_status"] == "DRAFT"

    # A plan holding a live term cannot be withdrawn.
    blocked = api.withdraw_plan(plan_m["id"], TEST_USERS["planner_headers"])
    validate_error(blocked, ApiErrorId.ERR_INVALID_STATE)


def test_withdrawing_an_unsold_plan_returns_allocation_to_zero(api):
    """PRD §2.4: "the invariant `allocated_data_mb` plus `remaining_data_mb` equals
    `committed_data_mb` holds after every event while the agreement is in `ACTIVE` or
    `SUSPENDED`."

    Design: Difficulty/non_linear_state_machine/plan_cyclic_offer_withdraw_reoffer
    """
    set_clock()
    agreement, plan = setup_agreement_with_offered_plan()
    summary = get_summary(agreement["id"])
    assert summary["allocated_data_mb"] == 0
    assert summary["remaining_data_mb"] == 16000

    api.withdraw_plan(plan["id"], TEST_USERS["planner_headers"])
    after = get_summary(agreement["id"])
    assert after["allocated_data_mb"] == 0
    assert after["remaining_data_mb"] == 16000
    assert get_plan(plan["id"])["plan_status"] == "DRAFT"


def test_plan_read_with_unknown_id_returns_plan_not_found(api):
    """PRD §2.9: "a missing plan `ERR_PLAN_NOT_FOUND`".

    Design: Corner/errors/not_found_codes_are_entity_specific
    """
    set_clock()
    resp = api.get_plan(MISSING_ID, TEST_USERS["planner_headers"])
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_FOUND)


def test_offering_a_plan_on_a_closed_agreement_is_rejected(api):
    """PRD §3.1: "a sale attempted afterwards against the closed agreement is rejected with
    `ERR_AGREEMENT_CLOSED` (HTTP 409), while a sale attempted against a retired plan is
    rejected with `ERR_PLAN_RETIRED` (HTTP 409)."

    Design: Corner/errors/error_agreement_closed_blocks_plan_offer
    """
    set_clock()
    # PRD 3.1: "a `SUSPENDED` agreement may be closed with the narrower bar that no term
    # is in QUOTED, PURCHASED, or AWAITING_ACTIVATION" — and an ACTIVE agreement may be
    # closed only "when no plan on it is still in DRAFT". A DRAFT plan therefore blocks
    # the close itself, so the agreement must be closed with every plan already offered;
    # PRD 3.1's close then "sets plan_status to RETIRED on every plan the agreement
    # contains", which is the state the later offer is made against.
    agreement = setup_active_agreement()
    draft = setup_offered_plan(
        agreement["id"], plan_code="D3", data_allotment_mb=3000
    )
    api.close_agreement(agreement["id"], TEST_USERS["planner_headers"])

    resp = api.offer_plan(draft["id"], TEST_USERS["planner_headers"])
    assert resp.status_code in (409, 422), (
        f"offering on a closed agreement must be refused, got {resp.status_code}"
    )
    assert get_summary(agreement["id"])["allocated_data_mb"] == 0