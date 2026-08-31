"""Pricing the lot, sending it to the customer and winning the order."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_quote,
    assert_quote,
    complete_job,
    create_customer,
    create_mold,
    create_press,
    create_priced_submitted_quote,
    create_quote,
    make_customer_rep_headers,
    mold_version,
    post_report,
    price_quote,
    read_job,
    read_mold,
    read_quote,
    set_clock,
    setup_running_job,
    validate_error,
    validate_success,
)

PA = TEST_USERS["plant_admin_headers"]
SE = TEST_USERS["sales_engineer_headers"]
PE = TEST_USERS["process_engineer_headers"]


def _shop_with_two_tools():
    set_clock()
    customer = create_customer()
    press = create_press()
    shop_owned = create_mold(customer["id"], mold_code="M-SHOP", ownership="SHOP_OWNED")
    customer_owned = create_mold(
        customer["id"], mold_code="M-CUST", ownership="CUSTOMER_OWNED"
    )
    return customer, press, shop_owned, customer_owned


def test_a_shop_owned_tool_amortises_its_tooling_into_the_lot_price(api):
    """PRD §3.3: "**Tooling amortisation** is `tooling_cost_cents` divided by 50
    lots, rounded up, when the tool's `ownership` is `SHOP_OWNED`; when the tool is
    `CUSTOMER_OWNED` it is exactly zero, because the customer has already paid for
    the tool."
    PRD §3.3: "**Margin** is selected from `annual_volume` and stored on the quote
    as `margin_bp`: an annual volume below 50,000 parts takes 2,800 basis points, an
    annual volume from 50,000 up to but not including 250,000 parts takes 2,200
    basis points, and an annual volume of 250,000 parts or more takes 1,600 basis
    points."
    PRD §3.3: "Pricing a quote writes the lot figure to `quoted_lot_price_cents` and
    the per-piece figure to `quoted_piece_price_cents`. In this quoting pass the
    cycle time is the quote's own nominal `cycle_time_sec`, the yield is the shop's
    standard 9,700 basis points, and the machine is the one named by
    `rate_press_id`."

    Design: Difficulty/combinatorial_formula/quote_price_tiered_margin_ownership_branch_and_price_floor
    """
    customer, press, shop_owned, _ = _shop_with_two_tools()
    quote = create_quote(customer["id"], shop_owned["id"])

    data = validate_success(api.price_quote(quote["id"], {"press_id": press["id"]}, SE))

    assert_quote(data)
    assert data["quoted_lot_price_cents"] == 94828
    assert data["quoted_piece_price_cents"] == 95
    assert data["margin_bp"] == 2200
    assert data["rate_press_id"] == press["id"]
    assert data["status"] == "PRICED"


def test_a_customer_owned_tool_drops_the_tooling_component_entirely(api):
    """PRD §3.3: "**Tooling amortisation** is `tooling_cost_cents` divided by 50
    lots, rounded up, when the tool's `ownership` is `SHOP_OWNED`; when the tool is
    `CUSTOMER_OWNED` it is exactly zero, because the customer has already paid for
    the tool."
    PRD §3.3: "**Direct lot cost** is the sum of those four components — machine,
    resin, tooling and packaging — each of which was already rounded to whole cents
    in its own step. The rounding happens per component and only then are the
    components summed."

    Design: Difficulty/combinatorial_formula/quote_price_tiered_margin_ownership_branch_and_price_floor
    """
    customer, press, _, customer_owned = _shop_with_two_tools()
    quote = create_quote(customer["id"], customer_owned["id"])

    data = validate_success(api.price_quote(quote["id"], {"press_id": press["id"]}, SE))

    assert data["quoted_lot_price_cents"] == 33828
    assert data["quoted_piece_price_cents"] == 34
    assert data["margin_bp"] == 2200


def test_the_piece_price_clamps_to_the_twelve_cent_floor(api):
    """PRD §3.3: "**Piece price** is the larger of 12 cents and the lot price
    divided by 1,000 parts rounded **up**. This final per-piece step is the last
    rounding in the chain and it is a round-up, not a round-half-up."
    PRD §3.3: "**Margin** is selected from `annual_volume` and stored on the quote
    as `margin_bp`: an annual volume below 50,000 parts takes 2,800 basis points, an
    annual volume from 50,000 up to but not including 250,000 parts takes 2,200
    basis points, and an annual volume of 250,000 parts or more takes 1,600 basis
    points."

    Design: Difficulty/combinatorial_formula/quote_price_tiered_margin_ownership_branch_and_price_floor
    """
    customer, press, _, customer_owned = _shop_with_two_tools()
    quote = create_quote(
        customer["id"],
        customer_owned["id"],
        part_weight_grams=1,
        cycle_time_sec=1,
        resin_price_cents_per_kg=1,
        annual_volume=300000,
    )

    data = validate_success(api.price_quote(quote["id"], {"press_id": press["id"]}, SE))

    assert data["quoted_lot_price_cents"] == 2669
    assert data["quoted_piece_price_cents"] == 12, (
        "2669 / 1000 rounded up is 3 cents, so the 12-cent floor wins"
    )
    assert data["margin_bp"] == 1600


def test_the_quoted_estimate_prices_from_the_nominal_cycle_and_standard_yield(api):
    """PRD §3.3: "Pricing a quote writes the lot figure to `quoted_lot_price_cents`
    and the per-piece figure to `quoted_piece_price_cents`. In this quoting pass the
    cycle time is the quote's own nominal `cycle_time_sec`, the yield is the shop's
    standard 9,700 basis points, and the machine is the one named by
    `rate_press_id`."
    PRD §3.3: "**Margin** is selected from `annual_volume` and stored on the quote
    as `margin_bp`: an annual volume below 50,000 parts takes 2,800 basis points, an
    annual volume from 50,000 up to but not including 250,000 parts takes 2,200
    basis points, and an annual volume of 250,000 parts or more takes 1,600 basis
    points."

    Design: Difficulty/dual_variant_calc/quote_estimate_vs_as_run_actual_piece_price
    """
    shop = setup_running_job()
    post_report(
        shop["job"]["id"],
        shots=1000,
        short_shot_shots=25,
        good_parts=3800,
        scrap_parts=200,
        virgin_grams=36000,
        regrind_grams=4000,
        run_minutes=700,
    )
    complete_job(shop["job"]["id"])

    quote = read_quote(shop["quote"]["id"])
    assert quote["quoted_piece_price_cents"] == 95
    assert quote["quoted_lot_price_cents"] == 94828
    assert quote["margin_bp"] == 2200


def test_the_as_run_pass_reprices_from_the_observed_cycle_and_yield(api):
    """PRD §3.7: "When the job completes, the eleven pricing steps of §3.3 run a
    second time on the same quote, with three inputs swapped: the cycle time is the
    job's observed `actual_cycle_time_sec` rather than the quote's nominal
    `cycle_time_sec`, the yield is the job's observed `first_pass_yield_bp` rather
    than the standard 9,700 basis points, and the machine rate comes from the job's
    own `press_id` rather than from the quote's `rate_press_id`."
    PRD §3.7: "The per-piece result is stored as `as_run_piece_price_cents`, and
    `price_variance_cents` is that figure minus the quote's
    `quoted_piece_price_cents` — positive when the job cost more per piece to
    produce than it was sold for."
    PRD §3.6: "On completion the material axis moves `STAGED → CONSUMED`, freezing
    the lot binding for audit and closing the job to further reports;
    `actual_cycle_time_sec` and `first_pass_yield_bp` are computed; the as-run
    pricing pass of §3.7 fills `as_run_piece_price_cents` and `price_variance_cents`;
    and the job's duration is released from the press's
    `committed_minutes_scheduled` with the press's `version` incremented by 1."

    Design: Difficulty/dual_variant_calc/quote_estimate_vs_as_run_actual_piece_price
    """
    shop = setup_running_job()
    post_report(
        shop["job"]["id"],
        shots=1000,
        short_shot_shots=25,
        good_parts=3800,
        scrap_parts=200,
        virgin_grams=36000,
        regrind_grams=4000,
        run_minutes=700,
    )

    completed = validate_success(api.complete_job(shop["job"]["id"], PE))

    assert completed["actual_cycle_time_sec"] == 42
    assert completed["first_pass_yield_bp"] == 9500
    assert completed["as_run_piece_price_cents"] == 98
    assert completed["price_variance_cents"] == 3
    assert completed["run_status"] == "COMPLETED"
    assert completed["material_status"] == "CONSUMED"


def test_sending_an_unpriced_quote_is_refused(api):
    """PRD §3.3: "Sending the quote to the customer moves it `PRICED → SUBMITTED`
    and requires that `quoted_piece_price_cents` has been computed; nothing but the
    status, `updated_at` and `version` changes. Attempting to send a quote whose
    status is not `PRICED` is rejected with `ERR_QUOTE_NOT_PRICED`."

    Design: Corner/state_machines/quote_submit_from_draft_returns_quote_not_priced
    """
    set_clock()
    customer = create_customer()
    create_press()
    mold = create_mold(customer["id"])
    quote = create_quote(customer["id"], mold["id"])

    response = api.submit_quote(quote["id"], SE)

    assert response.status_code == 409, f"Expected 409, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_QUOTE_NOT_PRICED.value)
    assert read_quote(quote["id"])["status"] == "DRAFT"


def test_a_second_decision_on_an_accepted_quote_is_refused(api):
    """PRD §3.3: "Either answer requires the quote to be `SUBMITTED` — a decision on
    a quote in any other status is rejected with `ERR_INVALID_STATE` — and either
    answer stamps the acting `X-User-ID` onto the quote as `decided_by_user_id`."
    PRD §3.3: "`ACCEPTED`, `DECLINED` and `SUPERSEDED` are all terminal."

    Design: Corner/state_machines/quote_customer_decision_on_accepted_quote_returns_invalid_state
    """
    set_clock()
    customer = create_customer()
    press = create_press()
    mold = create_mold(customer["id"])
    quote = create_priced_submitted_quote(customer["id"], mold["id"], press["id"])
    accept_quote(quote["id"], customer["id"], mold["id"])
    version_after_acceptance = mold_version(mold["id"])

    response = api.quote_customer_decision(
        quote["id"],
        {
            "decision": "DECLINE",
            "expected_mold_version": version_after_acceptance,
            "reason": "changed our mind",
        },
        make_customer_rep_headers(customer["id"]),
    )

    assert response.status_code == 409, f"Expected 409, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)
    assert read_quote(quote["id"])["status"] == "ACCEPTED"
    mold_now = read_mold(mold["id"])
    assert mold_now["status"] == "SAMPLING"
    assert mold_now["version"] == version_after_acceptance, (
        "the refused decision must not bump the tool a second time"
    )


def test_accepting_one_quote_supersedes_its_siblings_on_the_same_tool(api):
    """PRD §3.3: "Acceptance is also exclusive: every *other* quote on the same tool
    whose status is `DRAFT`, `PRICED` or `SUBMITTED` is driven to `SUPERSEDED` — an
    unpriced draft is closed out alongside a submitted rival, with no further
    cascade of its own."
    PRD §3.3: "Acceptance moves the quote `SUBMITTED → ACCEPTED`, drives the tool
    `NEW → SAMPLING` (a no-op on the status when the tool is already `SAMPLING`,
    since a second program has been won on a tool already in sampling), and
    increments the tool's `version` by 1 in either case."

    Design: Corner/state_machines/quote_acceptance_supersedes_sibling_quotes_on_the_same_mold
    """
    set_clock()
    customer = create_customer()
    press = create_press()
    mold_one = create_mold(customer["id"], mold_code="M-1")
    mold_two = create_mold(customer["id"], mold_code="M-2")
    winner = create_priced_submitted_quote(customer["id"], mold_one["id"], press["id"])
    rival = create_priced_submitted_quote(customer["id"], mold_one["id"], press["id"])
    other_tool = create_quote(customer["id"], mold_two["id"])

    accepted = accept_quote(winner["id"], customer["id"], mold_one["id"])

    assert accepted["status"] == "ACCEPTED"
    assert accepted["decided_by_user_id"] == customer["id"]
    assert read_quote(rival["id"])["status"] == "SUPERSEDED"
    assert read_quote(other_tool["id"])["status"] == "DRAFT", (
        "a quote on a different tool is untouched"
    )
    assert read_mold(mold_one["id"])["status"] == "SAMPLING"
    assert read_mold(mold_two["id"])["status"] == "NEW"


def test_a_customer_on_credit_hold_cannot_accept_a_quote(api):
    """PRD §3.3: "additionally requires that the customer's `credit_hold` is false,
    otherwise `ERR_CUSTOMER_CREDIT_HOLD` (HTTP 402), and that the tool's lifecycle
    status is `NEW` or `SAMPLING`."
    PRD §3.1: "A customer on credit hold is not blocked from being quoted — the
    sales conversation continues — but is blocked at the two moments where money is
    committed, as §3.3 and §3.9 describe."

    Design: Corner/validations/customer_on_credit_hold_cannot_accept_a_quote
    """
    set_clock()
    customer = create_customer(name="Held Industries", code="HOLD", credit_hold=True)
    press = create_press()
    mold = create_mold(customer["id"])
    quote = create_priced_submitted_quote(customer["id"], mold["id"], press["id"])
    version_before = mold_version(mold["id"])

    response = api.quote_customer_decision(
        quote["id"],
        {"decision": "ACCEPT", "expected_mold_version": version_before},
        make_customer_rep_headers(customer["id"]),
    )

    assert response.status_code == 402, f"Expected 402, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_CUSTOMER_CREDIT_HOLD.value)
    quote_now = read_quote(quote["id"])
    assert quote_now["status"] == "SUBMITTED"
    assert quote_now.get("decided_by_user_id") is None
    mold_now = read_mold(mold["id"])
    assert mold_now["status"] == "NEW"
    assert mold_now["version"] == version_before


def test_pricing_a_quote_on_a_retired_tool_is_refused(api):
    """PRD §3.3: "Pricing is refused outright when the tool's lifecycle status is
    `TRANSFERRED` or `RETIRED`, and when the quote's `cavitation` exceeds the tool's
    `cavity_count`."
    PRD §3.1: "Once a tool is `RETIRED` or `TRANSFERRED`, operations targeting it
    are rejected with `ERR_MOLD_RETIRED` or `ERR_MOLD_TRANSFERRED` respectively."

    Design: Corner/errors/pricing_a_quote_on_a_retired_mold_returns_mold_retired
    """
    set_clock()
    customer = create_customer()
    press = create_press()
    mold = create_mold(customer["id"])
    quote = create_quote(customer["id"], mold["id"])
    validate_success(api.retire_mold(mold["id"], {"reason": "scrapped"}, PA))

    response = api.price_quote(quote["id"], {"press_id": press["id"]}, SE)

    assert response.status_code == 409, f"Expected 409, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_MOLD_RETIRED.value)
    quote_now = read_quote(quote["id"])
    assert quote_now["status"] == "DRAFT"
    assert quote_now.get("quoted_piece_price_cents") is None
    assert read_mold(mold["id"])["status"] == "RETIRED"
