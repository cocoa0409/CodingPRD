"""Corner queue: state-machine claims — initial states, side-effecting
transitions on the brand/divestiture/case pipeline, and invalid or terminal
transitions on rationalization cases.
"""
from test_helpers import (
    TEST_USERS,
    USER_IDS,
    ApiErrorId,
    api_client,
    assert_brand,
    create_brand_payload,
    create_decide_payload,
    create_rationalization_case_payload,
    create_sign_spa_payload,
    get_item,
    get_tsa_for_divestiture,
    setup_divestiture_proposed,
    setup_divestiture_spa_signed,
    setup_executing_case,
    setup_listed_item,
    setup_scored_case,
    validate_created,
    validate_error,
    validate_ok,
    validate_paginated,
)

PM = TEST_USERS["portfolio_manager_headers"]
PM_PROPOSER = TEST_USERS["portfolio_manager_proposer_headers"]
PM_DECIDER = TEST_USERS["portfolio_manager_decider_headers"]
PM_DECIDER_2 = TEST_USERS["portfolio_manager_decider_2_headers"]


def test_brand_created_active_initial_state():
    """PRD §3.1: "A new brand starts life `ACTIVE`."
    PRD §2.5: "`version` (an integer that starts at 1 and increments by exactly
    1 on every mutation of that resource, including mutations performed as side
    effects of operations on other resources)".

    Design: Corner/state_machines/brand_created_active_initial_state
    """
    resp = api_client.create_brand(
        create_brand_payload(core_flag=False, private_label_share_pct=20,
                             annual_net_revenue_cents=800000000),
        PM,
    )
    brand = validate_created(resp)
    assert_brand(brand)
    assert brand["brand_status"] == "ACTIVE"
    assert brand["version"] == 1


def test_case_create_moves_item_to_cut_proposed():
    """PRD §3.2: "The server stamps the case with `proposer_user_id` taken from
    the caller's `X-User-ID` — this value anchors the segregation-of-duties
    rule at decision time — and the act of proposing moves the item from
    `LISTED` to `CUT_PROPOSED`, incrementing the item's `version`."
    PRD §3.2: "A new case starts in `SCORED` with `decider_user_id` null."

    Design: Corner/state_machines/case_create_moves_item_to_cut_proposed
    """
    _, _, item = setup_listed_item()
    assert item["version"] == 1
    resp = api_client.create_rationalization_case(
        create_rationalization_case_payload(item["id"]), PM_PROPOSER
    )
    case = validate_created(resp)
    assert case["case_status"] == "SCORED"
    assert case["proposer_user_id"] == USER_IDS["PROPOSER_1"]
    assert case["decider_user_id"] is None
    item_after = get_item(item["id"])
    assert item_after["item_status"] == "CUT_PROPOSED"
    assert item_after["version"] == 2, (
        f"the propose cascade increments Item.version once, got "
        f"{item_after['version']}"
    )


def test_sign_spa_creates_tsa_draft_and_brand_divesting():
    """PRD §3.5: "Signing moves the divestiture from `PROPOSED` to `SPA_SIGNED`,
    creates exactly one `TransitionServiceAgreement` in `DRAFT` bound to the
    divestiture — its `divestiture_id` pointing back, its `monthly_fee_cents`,
    `start_date`, and `end_date` taken from the signing payload, its
    `early_termination_penalty_cents` initialized to 0 and its `terminated_at`
    null — and moves the brand from `UNDER_REVIEW` to `DIVESTING`, incrementing
    both the divestiture's and the brand's `version`."

    Design: Corner/state_machines/sign_spa_creates_tsa_draft_and_brand_divesting
    """
    brand, divestiture = setup_divestiture_proposed()
    resp = api_client.sign_divestiture_spa(
        divestiture["id"],
        create_sign_spa_payload(
            tsa_monthly_fee_cents=75000,
            tsa_start_date="2026-09-15T00:00:00Z",
            tsa_end_date="2027-09-15T00:00:00Z",
        ),
        PM,
    )
    signed = validate_ok(resp)
    assert signed["divestiture_status"] == "SPA_SIGNED"
    tsa = get_tsa_for_divestiture(divestiture["id"])
    assert tsa["tsa_status"] == "DRAFT"
    assert tsa["monthly_fee_cents"] == 75000
    assert tsa["divestiture_id"] == divestiture["id"]
    brands, _ = validate_paginated(api_client.list_brands(PM))
    brand_after = {b["id"]: b for b in brands}[brand["id"]]
    assert brand_after["brand_status"] == "DIVESTING"


def test_close_activates_tsa_and_brand_divested():
    """PRD §3.5: "Closing moves the divestiture from `SPA_SIGNED` to `CLOSED`,
    flips the TSA from `DRAFT` to `ACTIVE`, and moves the brand from
    `DIVESTING` to `DIVESTED`, incrementing the `version` of all three
    records."

    Design: Corner/state_machines/close_activates_tsa_and_brand_divested
    """
    # TSA start 2026-09-01 equals the default clock; the close boundary is
    # inclusive, so no clock advance is needed.
    brand, divestiture, tsa = setup_divestiture_spa_signed(
        tsa_start_date="2026-09-01T00:00:00Z",
        tsa_end_date="2027-09-01T00:00:00Z",
    )
    resp = api_client.close_divestiture(divestiture["id"], PM)
    closed = validate_ok(resp)
    assert closed["divestiture_status"] == "CLOSED"
    tsa_after = get_tsa_for_divestiture(divestiture["id"])
    assert tsa_after["tsa_status"] == "ACTIVE"
    brands, _ = validate_paginated(api_client.list_brands(PM))
    brand_after = {b["id"]: b for b in brands}[brand["id"]]
    assert brand_after["brand_status"] == "DIVESTED"


def test_decide_on_executing_case_returns_invalid_state():
    """PRD §3.2: "The case must still be `SCORED` and — for an approval — the
    item must still be `CUT_PROPOSED`; otherwise the decide fails with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/decide_on_executing_case_returns_invalid_state
    """
    _, _, _, case = setup_executing_case()
    assert case["case_status"] == "EXECUTING", "Setup failed: case must be EXECUTING"
    resp = api_client.decide_rationalization_case(
        case["id"], create_decide_payload("REJECT"), PM_DECIDER
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = validate_ok(api_client.get_rationalization_case(case["id"], PM))
    assert after["case_status"] == "EXECUTING", "no flip-flop on a rejected decide"


def test_finalize_from_scored_case_returns_invalid_state():
    """PRD §3.2: "A `PortfolioManager` finalizes a case only when three
    conditions hold together: the case is `EXECUTING`, the item is still
    `SELL_THROUGH`, and the logical clock has reached the item's
    `sell_through_deadline` — the boundary is inclusive, so a finalize at
    exactly the deadline instant is allowed, and an earlier attempt is rejected
    with `ERR_SELL_THROUGH_OPEN` (HTTP 409)."

    Design: Corner/state_machines/finalize_from_scored_case_returns_invalid_state
    """
    _, _, item, case = setup_scored_case()
    assert case["case_status"] == "SCORED", "Setup failed: case must be SCORED"
    resp = api_client.finalize_rationalization_case(case["id"], PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_item(item["id"])["item_status"] == "CUT_PROPOSED", (
        "a rejected finalize must fire no side effects"
    )


def test_rejected_case_is_terminal_lockdown():
    """PRD §3.2: "A `REJECT` decision is a compensating revert: the case moves
    from `SCORED` to `REJECTED` and the item returns from `CUT_PROPOSED` to
    `LISTED`".
    PRD §3.2: "The case must still be `SCORED` ... otherwise the decide fails
    with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/rejected_case_is_terminal_lockdown
    """
    _, _, item, case = setup_scored_case()
    api_client.decide_rationalization_case(
        case["id"], create_decide_payload("REJECT"), PM_DECIDER
    )
    resp_decide = api_client.decide_rationalization_case(
        case["id"], create_decide_payload("APPROVE"), PM_DECIDER_2
    )
    validate_error(resp_decide, ApiErrorId.ERR_INVALID_STATE)
    resp_finalize = api_client.finalize_rationalization_case(case["id"], PM)
    validate_error(resp_finalize, ApiErrorId.ERR_INVALID_STATE)
    after = validate_ok(api_client.get_rationalization_case(case["id"], PM))
    assert after["case_status"] == "REJECTED"
    assert get_item(item["id"])["item_status"] == "LISTED"
