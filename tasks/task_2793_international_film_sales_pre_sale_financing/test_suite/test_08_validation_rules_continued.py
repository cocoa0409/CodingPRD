"""Rejection-ladder precedence and validation-rule boundaries, part two.

The temporal boundaries, the uniqueness and referential gates, and the banking
safety checks of PRD section 3, each driven through the declared endpoints from an
empty database with the logical clock pinned by the first call of the test.
"""

from test_helpers import (
    AGREEMENT_EXPENSE_CAP,
    CA_ASK_DE,
    CA_ESTIMATE_DE,
    CA_FLOOR_DE,
    CONTRACT_HOLDBACK_RELEASE,
    CONTRACT_LICENSE_END,
    CONTRACT_MG,
    FACILITY_ADVANCE_BONDED,
    FACILITY_ADVANCE_UNBONDED,
    FACILITY_COLLATERAL,
    FILM_BUDGET,
    HEAD_OF_SALES_CLOSER,
    HEAD_OF_SALES_VALUER,
    LENDER_APPROVER,
    LENDER_DRAWER,
    LIST_ALL,
    accepted_contract,
    approve_facility,
    assert_account_counters,
    assert_buyer_exposure,
    assert_contract_axes,
    assert_created,
    assert_empty_collection,
    assert_facility_figures,
    assert_film_counters,
    assert_instant,
    assert_list_response,
    assert_money,
    assert_object_response,
    assert_tier,
    assert_valuation_prices,
    bond_facility,
    contract_payload,
    distribute_payload,
    engaged_slate,
    executed_contract,
    executed_contract_environment,
    expense_payload,
    facility_payload,
    film_amendment_payload,
    find_by,
    get_success_data,
    lapse_payload,
    make_account,
    make_buyer_headers,
    make_collection_agent_headers,
    make_delivery_manager_headers,
    make_facility,
    make_film,
    make_head_of_sales_headers,
    make_lender_headers,
    make_market,
    make_platform_admin_headers,
    make_sales_agent_headers,
    make_tiers,
    milestone_by_label,
    milestone_payload,
    open_market,
    package_payload,
    packaged_slate,
    pin_clock,
    post_receipt,
    post_receipts,
    publish_payload,
    read_account,
    read_agreement,
    read_buyer,
    read_contract,
    read_facility,
    read_film,
    read_milestones,
    read_tiers,
    read_valuation,
    record_qc_fail,
    reversal_payload,
    screening_slot_payload,
    slate_with_published_valuation,
    state_payload,
    submit_package,
    tier_payload,
    valuation_payload,
    validate_error,
    validate_success,
)


def test_reversing_a_receipt_after_the_cash_was_distributed_is_refused(api):
    """Once the waterfall has paid the cash away the receipt can no longer be undone.

    PRD: "Two conditions apply: the milestone's `status` must be `RECEIVED`, and the account's `balance_usd` must be at least the milestone's `received_amount_usd`."

    PRD: "The second condition exists because a reversal must not drive the balance negative — if the cash has already been distributed away through the waterfall, the reversal is rejected with `ERR_RECEIPT_ALREADY_DISTRIBUTED`."

    Design: Corner/validations/reverse_receipt_after_the_cash_was_distributed_is_rejected
    """
    env = executed_contract_environment(api)
    account_id = env["account"]["id"]
    milestone = milestone_by_label(env, "ON_SIGNATURE")
    post_receipt(api, milestone, "2026-08-05T00:00:00Z")
    make_tiers(api, account_id, [(1, "PARTICIPATION", 1.00, None)])
    get_success_data(
        api.distribute(
            account_id, distribute_payload(900000.00), make_collection_agent_headers()
        )
    )

    refused = api.reverse_receipt(
        milestone["id"],
        reversal_payload("wire posted against the wrong picture"),
        make_collection_agent_headers(),
    )
    validate_error(refused, "ERR_RECEIPT_ALREADY_DISTRIBUTED", 422)

    kept = milestone_by_label(read_milestones(api, env["contract"]["id"]), "ON_SIGNATURE")
    assert kept["status"] == "RECEIVED", (
        f"the refused reversal leaves the milestone RECEIVED, got {kept['status']}"
    )
    assert_money(kept["received_amount_usd"], 900000.00, "received_amount_usd")
    assert_money(kept["accrued_commission_usd"], 90000.00, "accrued_commission_usd")

    agreement = read_agreement(api, env["film"]["id"], env["agreement"]["id"])
    assert_money(agreement["gross_collected_usd"], 900000.00, "gross_collected_usd")
    assert_money(agreement["commission_earned_usd"], 90000.00, "commission_earned_usd")
    assert_account_counters(
        read_account(api, account_id),
        receipts=900000.00,
        distributed=900000.00,
        balance=0.00,
    )


def test_expenses_log_to_twice_the_cap_and_not_one_cent_further(api):
    """The tolerance is exactly twice the cap, and only the cap stays recoupable.

    PRD: "The posted `amount_usd` must be strictly greater than zero, and the running `expenses_incurred_usd` plus this amount must not exceed twice the `expense_cap_usd` — the tolerance factor is exactly 2.00, so an agency with a 500,000.00 cap may log up to 1,000,000.00 of expenses in total."

    PRD: "Anything beyond that, or a non-positive amount, is rejected with `ERR_EXPENSE_LOG_LIMIT`."

    PRD: "What they cannot do is *recoup* it — only the cap is ever recoverable through the waterfall, which is why logging an expense also resynchronises the `SALES_EXPENSES` waterfall tier's ceiling on every open collection account of the picture to the lesser of `expenses_incurred_usd` and `expense_cap_usd`, rounded to two decimal places."

    Design: Corner/validations/expenses_may_be_logged_to_twice_the_cap_and_not_one_cent_further
    """
    env = engaged_slate(api)
    agreement_id = env["agreement"]["id"]
    account = make_account(api, env["film"]["id"])
    tier = make_tiers(api, account["id"], [(1, "SALES_EXPENSES", 1.00, None)])[0]

    validate_success(
        api.log_expense(
            agreement_id,
            expense_payload(100000.00, "market booth and print advertising"),
            make_sales_agent_headers(),
        ),
        200,
    )
    validate_success(
        api.log_expense(
            agreement_id,
            expense_payload(50000.00, "trailer conform and key art"),
            make_head_of_sales_headers(),
        ),
        200,
    )

    refused = api.log_expense(
        agreement_id,
        expense_payload(0.01, "one cent past the tolerance"),
        make_sales_agent_headers(),
    )
    validate_error(refused, "ERR_EXPENSE_LOG_LIMIT", 422)

    agreement = read_agreement(api, env["film"]["id"], agreement_id)
    assert_money(agreement["expenses_incurred_usd"], 150000.00, "expenses_incurred_usd")
    assert_tier(
        find_by(read_tiers(api, account["id"]), id=tier["id"]), cap=AGREEMENT_EXPENSE_CAP
    )


def test_market_item_windows_must_sit_inside_the_market_dates(api):
    """A window starting before the market or ending after it is refused.

    PRD: "And the requested window must lie entirely inside the market window: `start_at` at or after the market's `start_date`, and `end_at` at or before the market's `end_date`, with failure yielding `ERR_OUTSIDE_MARKET_WINDOW`."

    Design: Corner/validations/market_item_windows_must_sit_inside_the_market_dates
    """
    env = packaged_slate(api)
    film_id = env["film"]["id"]
    market = make_market(
        api,
        name="EFM Berlin",
        city="Berlin",
        start_date="2027-02-11T00:00:00Z",
        end_date="2027-02-17T00:00:00Z",
        screening_room_count=3,
        meeting_table_count=4,
    )
    open_market(api, market["id"])

    early = api.create_screening_slot(
        screening_slot_payload(
            market["id"], film_id, 1, "2027-02-10T09:00:00Z", "2027-02-10T11:00:00Z", capacity=60
        ),
        make_sales_agent_headers(),
    )
    validate_error(early, "ERR_OUTSIDE_MARKET_WINDOW", 422)

    overrunning = api.create_screening_slot(
        screening_slot_payload(
            market["id"], film_id, 1, "2027-02-16T23:00:00Z", "2027-02-17T01:00:00Z", capacity=60
        ),
        make_sales_agent_headers(),
    )
    validate_error(overrunning, "ERR_OUTSIDE_MARKET_WINDOW", 422)

    hugging = assert_created(
        api.create_screening_slot(
            screening_slot_payload(
                market["id"],
                film_id,
                1,
                "2027-02-11T00:00:00Z",
                "2027-02-11T02:00:00Z",
                capacity=60,
            ),
            make_sales_agent_headers(),
        )
    )
    assert hugging["status"] == "HELD", f"a new slot is HELD, got {hugging['status']}"
    assert_list_response(
        api.list_screening_slots(make_sales_agent_headers(), LIST_ALL),
        expected_total=1,
        expected_rows=1,
    )


def test_holdback_gate_fails_one_second_early_and_passes_at_the_instant(api):
    """Delivery one second before the holdback release is refused; the instant itself passes.

    PRD: "The logical present instant must be at or after the contract's `holdback_release_date` — the exact instant of holdback release is deliverable, and anything earlier is rejected with `ERR_HOLDBACK_NOT_ELAPSED`."

    PRD: "`holdback_release_date` is computed as the picture's `theatrical_release_date` — as it stands at execution time, not as it stood when the offer was made — plus `holdback_days` whole days."

    Design: Corner/validations/holdback_gate_fails_one_second_early_and_passes_at_the_exact_instant
    """
    env = executed_contract(api)
    contract_id = env["contract"]["id"]
    assert_instant(
        env["contract"]["holdback_release_date"],
        CONTRACT_HOLDBACK_RELEASE,
        "holdback_release_date",
    )

    pin_clock(api, "2027-06-13T23:59:59Z")
    refused = api.create_deliverable_package(
        contract_id, package_payload(), make_delivery_manager_headers()
    )
    validate_error(refused, "ERR_HOLDBACK_NOT_ELAPSED", 422)
    assert_empty_collection(
        api.list_deliverable_packages(contract_id, make_delivery_manager_headers(), LIST_ALL)
    )
    assert_contract_axes(read_contract(api, contract_id), delivery="PENDING")

    pin_clock(api, CONTRACT_HOLDBACK_RELEASE)
    package = assert_created(
        api.create_deliverable_package(
            contract_id, package_payload(), make_delivery_manager_headers()
        )
    )
    assert package["revision_round"] == 1, (
        f"a first package is at revision_round 1, got {package['revision_round']}"
    )
    assert package["status"] == "SUBMITTED", (
        f"a new package is SUBMITTED, got {package['status']}"
    )
    assert_contract_axes(read_contract(api, contract_id), delivery="SUBMITTED")


def test_reversion_requires_the_licence_term_to_have_expired(api):
    """A fully paid contract reverts at the expiry instant and not one second earlier.

    PRD: "The logical present instant must be at or after the contract's `license_end_date` — the exact instant of expiry is reversible, and anything earlier is rejected with `ERR_LICENSE_TERM_NOT_EXPIRED`."

    PRD: "And the contract's `collection_status` must be `PAID`: the agency does not hand rights back to itself while the buyer still owes money."

    Design: Corner/validations/reversion_requires_the_licence_term_to_have_expired
    """
    env = executed_contract_environment(api)
    contract_id = env["contract"]["id"]
    assert_instant(
        env["contract"]["license_end_date"], CONTRACT_LICENSE_END, "license_end_date"
    )
    post_receipts(
        api,
        env,
        [
            ("ON_SIGNATURE", "2026-08-05T00:00:00Z"),
            ("ON_DELIVERY", "2027-06-20T00:00:00Z"),
            ("ON_RELEASE", "2027-07-20T00:00:00Z"),
            ("ON_TERM_END", "2028-07-01T00:00:00Z"),
        ],
    )
    assert_contract_axes(read_contract(api, contract_id), collection="PAID")

    pin_clock(api, "2028-07-31T23:59:59Z")
    refused = api.revert_contract(contract_id, make_head_of_sales_headers())
    validate_error(refused, "ERR_LICENSE_TERM_NOT_EXPIRED", 422)
    assert_contract_axes(read_contract(api, contract_id), negotiation="EXECUTED")

    pin_clock(api, CONTRACT_LICENSE_END)
    reverted = assert_object_response(
        api.revert_contract(contract_id, make_head_of_sales_headers())
    )
    assert_contract_axes(reverted, negotiation="REVERTED")
    assert_buyer_exposure(read_buyer(api, env["buyer"]["id"]), gross=0.00, net=0.00)
    assert_film_counters(read_film(api, env["film"]["id"]), committed=0.00, gap=FILM_BUDGET)


def test_resubmission_after_the_cure_deadline_is_rejected(api):
    """One second past the cure deadline is too late; the deadline instant still cures.

    PRD: "A `DeliveryManager` resubmits, which requires that the contract's latest package be in `REJECTED` status and that the logical present instant be at or before that package's `cure_deadline`; a resubmission arriving after the cure window has closed is rejected with `ERR_CURE_WINDOW_ELAPSED`."

    PRD: "**A failing verdict below the revision limit** sets `qc_result` to `FAIL`, writes the supplied `rejection_reason`, moves the package `SUBMITTED → REJECTED`, stamps its `cure_deadline` as 30 days after the package's `submitted_at`, and drives the contract's `delivery_status` to `REJECTED`."

    Design: Corner/validations/resubmission_after_the_cure_deadline_is_rejected
    """
    env = executed_contract(api)
    contract_id = env["contract"]["id"]
    pin_clock(api, CONTRACT_HOLDBACK_RELEASE)
    first = submit_package(api, contract_id)
    record_qc_fail(api, first["id"], env["buyer"]["id"])

    rejected = find_by(
        get_success_data(
            api.list_deliverable_packages(
                contract_id, make_delivery_manager_headers(), LIST_ALL
            )
        ),
        id=first["id"],
    )
    assert rejected["status"] == "REJECTED", (
        f"a failing verdict below the limit rejects the package, got {rejected['status']}"
    )
    assert_instant(rejected["cure_deadline"], "2027-07-14T00:00:00Z", "cure_deadline")

    pin_clock(api, "2027-07-14T00:00:01Z")
    refused = api.create_deliverable_package(
        contract_id, package_payload(), make_delivery_manager_headers()
    )
    validate_error(refused, "ERR_CURE_WINDOW_ELAPSED", 422)
    assert_list_response(
        api.list_deliverable_packages(contract_id, make_delivery_manager_headers(), LIST_ALL),
        expected_total=1,
        expected_rows=1,
    )

    pin_clock(api, "2027-07-14T00:00:00Z")
    second = assert_created(
        api.create_deliverable_package(
            contract_id, package_payload(), make_delivery_manager_headers()
        )
    )
    assert second["revision_round"] == 2, (
        f"a resubmission is one round higher, got {second['revision_round']}"
    )
    assert_contract_axes(read_contract(api, contract_id), delivery="SUBMITTED")


def test_tier_order_uniqueness_and_the_single_uncapped_tier_rule(api):
    """A repeated order and a second uncapped tier both report the same code.

    PRD: "Two uniqueness rules guard tier creation, both reporting `ERR_TIER_ORDER_TAKEN`: `tier_order` must be unique within the account, and an account may hold at most one uncapped tier, so a second tier submitted without a `cap_usd` is refused."

    PRD: "A tier created without a `cap_usd` is **uncapped**, and an uncapped tier is the sweep destination described below."

    Design: Corner/validations/tier_order_uniqueness_and_the_single_uncapped_tier_rule
    """
    env = executed_contract_environment(api)
    account_id = env["account"]["id"]
    fee = make_tiers(api, account_id, [(1, "COLLECTION_FEE", 0.05, 50000.00)])[0]

    order_taken = api.create_waterfall_tier(
        account_id, tier_payload(1, "PARTICIPATION", 1.00), make_collection_agent_headers()
    )
    validate_error(order_taken, "ERR_TIER_ORDER_TAKEN", 409)

    uncapped = assert_created(
        api.create_waterfall_tier(
            account_id, tier_payload(2, "PARTICIPATION", 1.00), make_collection_agent_headers()
        )
    )
    assert uncapped.get("cap_usd") is None, (
        f"a tier created without a cap is uncapped, got cap_usd {uncapped.get('cap_usd')!r}"
    )

    second_uncapped = api.create_waterfall_tier(
        account_id, tier_payload(3, "DEFERMENT", 1.00), make_collection_agent_headers()
    )
    validate_error(second_uncapped, "ERR_TIER_ORDER_TAKEN", 409)

    rows, _ = assert_list_response(
        api.list_waterfall_tiers(account_id, make_collection_agent_headers(), LIST_ALL),
        expected_total=2,
        expected_rows=2,
    )
    assert_tier(find_by(rows, id=fee["id"]), recouped=0.00, cap=50000.00, status="ACTIVE")
    assert_tier(find_by(rows, id=uncapped["id"]), recouped=0.00, status="ACTIVE")


def test_mg_below_the_published_floor_blocks_execution_until_it_matches(api):
    """A guarantee one step below the floor cannot be countersigned; the floor itself can.

    PRD: "And last, the floor: the contract's `minimum_guarantee_usd` must be at or above the `floor_price_usd` of that `PUBLISHED` valuation, else `ERR_MG_BELOW_FLOOR`; a minimum guarantee equal to the floor is acceptable, one a single cent below it is not."

    Design: Corner/validations/mg_below_the_published_floor_blocks_execution_until_it_matches_the_floor
    """
    env = slate_with_published_valuation(api)
    assert_valuation_prices(
        read_valuation(api, env["valuation"]["id"]), CA_ESTIMATE_DE, CA_ASK_DE, CA_FLOOR_DE
    )
    env = accepted_contract(api, env, minimum_guarantee_usd=1000000.00)
    first_id = env["contract"]["id"]

    refused = api.execute_contract(first_id, make_head_of_sales_headers(HEAD_OF_SALES_CLOSER))
    validate_error(refused, "ERR_MG_BELOW_FLOOR", 422)
    assert_contract_axes(read_contract(api, first_id), negotiation="ACCEPTED")

    assert_object_response(
        api.lapse_contract(
            first_id,
            lapse_payload("guarantee below the published floor"),
            make_head_of_sales_headers(),
        )
    )
    assert_buyer_exposure(read_buyer(api, env["buyer"]["id"]), gross=0.00)

    at_the_floor = assert_created(
        api.create_contract(
            contract_payload(
                env["film"]["id"],
                env["buyer"]["id"],
                env["territory"]["id"],
                read_buyer(api, env["buyer"]["id"])["version"],
                minimum_guarantee_usd=CA_FLOOR_DE,
            ),
            make_sales_agent_headers(),
        )
    )
    assert_money(at_the_floor["minimum_guarantee_usd"], CA_FLOOR_DE, "minimum_guarantee_usd")
    for label, pct, due_date in (
        ("ON_SIGNATURE", 0.50, "2026-09-01T00:00:00Z"),
        ("ON_DELIVERY", 0.50, "2027-06-15T00:00:00Z"),
    ):
        assert_created(
            api.create_milestone(
                at_the_floor["id"],
                milestone_payload(label, pct, due_date),
                make_sales_agent_headers(),
            )
        )
    get_success_data(
        api.accept_contract(at_the_floor["id"], make_buyer_headers(env["buyer"]["id"]))
    )
    executed = assert_object_response(
        api.execute_contract(
            at_the_floor["id"], make_head_of_sales_headers(HEAD_OF_SALES_CLOSER)
        )
    )
    assert_contract_axes(executed, negotiation="EXECUTED")
    assert_film_counters(
        read_film(api, env["film"]["id"]), committed=CA_FLOOR_DE, gap=22824000.00
    )


def test_staling_the_valuation_reopens_the_published_gate_at_execution(api):
    """A cast-score amendment stales the valuation and blocks the countersignature.

    PRD: "The second is a cast-score amendment: the `principal_cast_score` submitted in an amendment to the picture differs from the stored value, which invalidates every cast multiplier already baked into a published estimate."

    PRD: "Fourth, a valuation with `status` `PUBLISHED` must exist for that film-and-territory pair at all, else `ERR_NO_PUBLISHED_VALUATION`."

    Design: Corner/validations/staling_the_valuation_reopens_the_published_gate_at_execution
    """
    env = accepted_contract(api)
    contract_id = env["contract"]["id"]
    film_id = env["film"]["id"]

    get_success_data(
        api.patch_film(
            film_id, film_amendment_payload(principal_cast_score=75), make_platform_admin_headers()
        )
    )
    assert read_valuation(api, env["valuation"]["id"])["status"] == "STALE", (
        "a differing cast score stales the published valuation"
    )
    assert_film_counters(read_film(api, film_id), published_count=0)

    refused = api.execute_contract(
        contract_id, make_head_of_sales_headers(HEAD_OF_SALES_CLOSER)
    )
    validate_error(refused, "ERR_NO_PUBLISHED_VALUATION", 422)
    assert_contract_axes(read_contract(api, contract_id), negotiation="ACCEPTED")

    revalued = assert_created(
        api.create_valuation(
            valuation_payload(film_id, env["territory"]["id"], "CAST_ADJUSTED"),
            make_sales_agent_headers(),
        )
    )
    assert_valuation_prices(revalued, 1440000.00, 1800000.00, 1008000.00)
    published = assert_object_response(
        api.publish_valuation(
            revalued["id"],
            publish_payload(read_film(api, film_id)["version"]),
            make_head_of_sales_headers(HEAD_OF_SALES_VALUER),
        )
    )
    assert published["status"] == "PUBLISHED", (
        f"the fresh valuation publishes, got {published['status']}"
    )

    executed = assert_object_response(
        api.execute_contract(contract_id, make_head_of_sales_headers(HEAD_OF_SALES_CLOSER))
    )
    assert_contract_axes(executed, negotiation="EXECUTED")
    assert executed["executed_by_user_id"] == HEAD_OF_SALES_CLOSER, (
        f"expected executed_by_user_id {HEAD_OF_SALES_CLOSER}, "
        f"got {executed['executed_by_user_id']}"
    )
    assert_film_counters(read_film(api, film_id), committed=CONTRACT_MG, published_count=1)


def test_facility_approval_without_an_executed_contract_has_no_collateral(api):
    """With no executed contract behind it the facility has nothing to lend against.

    PRD: "`PROPOSED → APPROVED` is a `Lender` move requiring two things: at least one contract of the picture must be `EXECUTED` with a buyer whose `credit_rating` is `AAA`, `AA` or `A` and whose `status` is `ACTIVE`, and the facility's `eligible_collateral_usd` must be strictly greater than zero."

    PRD: "Failure on either count is `ERR_NO_ELIGIBLE_COLLATERAL`."

    Design: Corner/validations/facility_approval_without_an_executed_contract_has_no_eligible_collateral
    """
    pin_clock(api)
    film = make_film(api)
    facility = assert_created(
        api.create_banking_facility(film["id"], facility_payload(), make_lender_headers())
    )
    assert_facility_figures(facility, collateral=0.00, advance=0.00, status="PROPOSED")

    refused = api.set_facility_state(
        facility["id"], state_payload("APPROVED"), make_lender_headers(LENDER_APPROVER)
    )
    validate_error(refused, "ERR_NO_ELIGIBLE_COLLATERAL", 422)

    stored = read_facility(api, film["id"], facility["id"])
    assert_facility_figures(
        stored, collateral=0.00, advance=0.00, drawn=0.00, status="PROPOSED"
    )
    assert stored.get("approved_by_user_id") is None, (
        "a refused approval must not record an approving officer"
    )


def test_segregation_of_duties_outranks_the_completion_bond_gate_on_a_draw(api):
    """The approving officer is turned away before the missing bond is even considered.

    PRD: "**Ninth, business safety** — segregation of duties (`ERR_SEGREGATION_OF_DUTIES`, 403), then buyer blocking (`ERR_BUYER_BLOCKED`, 422), then the completion-bond requirement (`ERR_COMPLETION_BOND_REQUIRED`, 422)."

    PRD: "`X-User-ID` must differ from the facility's `approved_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES` — the officer who approved may not draw."

    Design: Corner/validations/segregation_of_duties_outranks_the_completion_bond_gate_on_a_draw
    """
    env = executed_contract(api)
    film_id = env["film"]["id"]
    facility = make_facility(api, film_id)
    approve_facility(api, facility["id"], as_user_id=LENDER_APPROVER)

    same_officer = api.set_facility_state(
        facility["id"], state_payload("DRAWN"), make_lender_headers(LENDER_APPROVER)
    )
    validate_error(same_officer, "ERR_SEGREGATION_OF_DUTIES", 403)

    unbonded = api.set_facility_state(
        facility["id"], state_payload("DRAWN"), make_lender_headers(LENDER_DRAWER)
    )
    validate_error(unbonded, "ERR_COMPLETION_BOND_REQUIRED", 422)

    still_approved = read_facility(api, film_id, facility["id"])
    assert_facility_figures(
        still_approved,
        collateral=FACILITY_COLLATERAL,
        advance=FACILITY_ADVANCE_UNBONDED,
        drawn=0.00,
        status="APPROVED",
    )

    bond_facility(api, facility["id"])
    bonded = read_facility(api, film_id, facility["id"])
    assert_facility_figures(
        bonded,
        collateral=FACILITY_COLLATERAL,
        advance=FACILITY_ADVANCE_BONDED,
        drawn=0.00,
        status="APPROVED",
    )

    drawn = assert_object_response(
        api.set_facility_state(
            facility["id"], state_payload("DRAWN"), make_lender_headers(LENDER_DRAWER)
        )
    )
    assert_facility_figures(
        drawn,
        drawn=FACILITY_ADVANCE_BONDED,
        outstanding=FACILITY_ADVANCE_BONDED,
        status="DRAWN",
    )


def test_a_fully_compliant_booking_passes_every_gate_in_the_ladder(api):
    """With every gate satisfied and a 30-minute turnaround the second booking is held.

    PRD: "Because both comparisons are strict, a gap of exactly 30 minutes between two screenings is accepted, a gap of 29 minutes is rejected, and back-to-back screenings with no gap at all are rejected."

    Design: Corner/validations/a_fully_compliant_slot_booking_passes_every_gate_in_the_ladder
    """
    env = slate_with_published_valuation(api)
    film_id = env["film"]["id"]
    market = make_market(
        api,
        name="EFM Berlin",
        city="Berlin",
        start_date="2027-02-11T00:00:00Z",
        end_date="2027-02-17T00:00:00Z",
        screening_room_count=3,
        meeting_table_count=4,
    )
    open_market(api, market["id"])

    first = assert_created(
        api.create_screening_slot(
            screening_slot_payload(
                market["id"],
                film_id,
                1,
                "2027-02-11T09:00:00Z",
                "2027-02-11T11:00:00Z",
                capacity=60,
            ),
            make_sales_agent_headers(),
        )
    )
    second = assert_created(
        api.create_screening_slot(
            screening_slot_payload(
                market["id"],
                film_id,
                1,
                "2027-02-11T11:30:00Z",
                "2027-02-11T13:00:00Z",
                slot_type="PRESS",
                capacity=40,
            ),
            make_head_of_sales_headers(),
        )
    )
    assert second["status"] == "HELD", f"a new slot is HELD, got {second['status']}"
    assert second["market_id"] == market["id"], "the slot echoes its market"
    assert second["film_id"] == film_id, "the slot echoes its film"
    assert second["slot_type"] == "PRESS", (
        f"expected slot_type PRESS, got {second['slot_type']}"
    )

    rows, _ = assert_list_response(
        api.list_screening_slots(make_sales_agent_headers(), LIST_ALL),
        expected_total=2,
        expected_rows=2,
    )
    assert rows[0]["id"] == first["id"], (
        "screening slots list by start_at ascending, so the earlier booking comes first"
    )
