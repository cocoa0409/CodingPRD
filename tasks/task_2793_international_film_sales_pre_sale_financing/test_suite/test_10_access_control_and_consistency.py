"""Role grants, segregation of duties, concurrency guards and read-your-write
consistency of the Film Sales Presale API.

Every test drives only the declared endpoints, pins the logical clock as its first
call, and asserts pre-computed literals taken from the PRD narrative.
"""

from test_helpers import (
    AGREEMENT_EXPENSE_CAP,
    CA_ASK_DE,
    CA_ESTIMATE_DE,
    CA_FLOOR_DE,
    CLOCK_DEFAULT,
    CONTRACT_MG,
    FILM_BUDGET,
    HEAD_OF_SALES_CLOSER,
    HEAD_OF_SALES_VALUER,
    LENDER_APPROVER,
    LENDER_DRAWER,
    LIST_ALL,
    NON_EXISTENT_UUID,
    accepted_contract,
    account_payload,
    add_milestone_schedule,
    agreement_payload,
    approve_facility,
    assert_account_counters,
    assert_buyer_exposure,
    assert_contract_axes,
    assert_created,
    assert_film_counters,
    assert_instant,
    assert_list_response,
    assert_money,
    assert_object_response,
    assert_tier,
    assert_valuation_prices,
    bond_facility,
    buyer_amendment_payload,
    contract_payload,
    counter_payload,
    distribute_payload,
    draw_facility,
    executed_contract,
    executed_contract_environment,
    expense_payload,
    film_amendment_payload,
    find_by,
    make_account,
    make_buyer,
    make_buyer_headers,
    make_collection_agent_headers,
    make_delivery_manager_headers,
    make_facility,
    make_head_of_sales_headers,
    make_lender_headers,
    make_platform_admin_headers,
    make_sales_agent_headers,
    make_tiers,
    milestone_by_label,
    offered_contract,
    package_payload,
    pin_clock,
    post_receipt,
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
    receipt_payload,
    slate_with_published_valuation,
    valuation_payload,
    valued_slate,
    validate_error,
)


# ==========================================================================
# Role grants and the identity checks layered on top of them
# ==========================================================================
def test_platform_admin_owns_reference_data_but_no_deal_making_authority(api):
    """The admin is refused on execute, publish and receipt, yet may amend a buyer.

    PRD: "`PlatformAdmin` holds no deal-making authority: it cannot publish a valuation, execute a contract, post a receipt or draw a facility."

    PRD: "When both headers are well-formed but the named role is not among the roles authorised for the targeted operation (see the authorisation column of the endpoint table in §4), the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/platform_admin_cannot_publish_execute_or_post_receipts_despite_owning_reference_data
    """
    env = accepted_contract(api)
    contract_id = env["contract"]["id"]
    film_id = env["film"]["id"]
    valuation_id = env["valuation"]["id"]
    signature = milestone_by_label(read_milestones(api, contract_id), "ON_SIGNATURE")
    admin_headers = make_platform_admin_headers()

    validate_error(
        api.execute_contract(contract_id, admin_headers), "ERR_UNAUTHORIZED", 403
    )
    assert_contract_axes(read_contract(api, contract_id), negotiation="ACCEPTED")

    validate_error(
        api.publish_valuation(
            valuation_id, publish_payload(read_film(api, film_id)["version"]), admin_headers
        ),
        "ERR_UNAUTHORIZED",
        403,
    )

    validate_error(
        api.post_receipt(
            signature["id"], receipt_payload(900000.00, "2026-08-05T00:00:00Z"), admin_headers
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    refreshed = milestone_by_label(read_milestones(api, contract_id), "ON_SIGNATURE")
    assert refreshed["status"] == "SCHEDULED"

    amended = assert_object_response(
        api.patch_buyer(
            env["buyer"]["id"], buyer_amendment_payload(credit_rating="AA"), admin_headers
        )
    )
    assert amended["credit_rating"] == "AA"


def test_a_sales_agent_may_open_the_deal_but_not_approve_it(api):
    """The agent creates a valuation and an offer, and is refused on publish and execute.

    PRD: "Revising an offer and adding a payment milestone are the two operations that no role other than `SalesAgent` and `HeadOfSales` may perform."

    PRD: "This role drafts and executes the sales agency agreement, publishes territory valuations, countersigns accepted contracts, lapses contracts that will not close, and reverts rights once a licence term has run."

    Design: Corner/rbac/sales_agent_creates_the_valuation_and_the_offer_but_cannot_publish_or_execute
    """
    env = slate_with_published_valuation(api)
    film_id = env["film"]["id"]
    agent_headers = make_sales_agent_headers()

    second = assert_created(
        api.create_valuation(
            valuation_payload(film_id, env["territory"]["id"], "COMPARABLE_WEIGHTED"),
            agent_headers,
        )
    )
    assert second["status"] == "DRAFT"

    validate_error(
        api.publish_valuation(
            second["id"], publish_payload(read_film(api, film_id)["version"]), agent_headers
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    assert read_valuation(api, second["id"])["status"] == "DRAFT"

    env = offered_contract(api, env)
    assert env["contract"]["negotiation_status"] == "OFFERED"

    validate_error(
        api.execute_contract(env["contract"]["id"], agent_headers),
        "ERR_UNAUTHORIZED",
        403,
    )

    validate_error(
        api.create_agency_agreement(
            film_id,
            agreement_payload(commission_pct=0.15, expense_cap_usd=50000.00, term_months=12),
            agent_headers,
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    assert_list_response(
        api.list_agency_agreements(film_id, make_head_of_sales_headers(), LIST_ALL),
        expected_total=1,
        expected_rows=1,
    )


def test_a_rival_buyer_cannot_accept_someone_elses_offer(api):
    """Holding the Buyer role is not enough: the identity must match the contract.

    PRD: "Concretely, a `Buyer` may counter or accept only a contract whose `buyer_id` equals its own `X-User-ID`, and may record a quality-control verdict only on a deliverable package whose owning contract has that same `buyer_id`."

    PRD: "A violation is rejected with `ERR_NOT_CONTRACT_BUYER` (HTTP 403)."

    Design: Corner/rbac/buyer_scope_means_a_rival_buyer_cannot_accept_someone_elses_offer
    """
    env = offered_contract(api)
    contract_id = env["contract"]["id"]
    add_milestone_schedule(api, contract_id)
    rival = make_buyer(
        api,
        env["territory"]["id"],
        company_name="Alpen Kino",
        credit_rating="AA",
        exposure_limit_usd=5000000.00,
    )

    validate_error(
        api.accept_contract(contract_id, make_buyer_headers(rival["id"])),
        "ERR_NOT_CONTRACT_BUYER",
        403,
    )
    validate_error(
        api.counter_contract(
            contract_id, counter_payload(1500000.00), make_buyer_headers(NON_EXISTENT_UUID)
        ),
        "ERR_NOT_CONTRACT_BUYER",
        403,
    )
    assert read_contract(api, contract_id)["negotiation_round"] == 1

    accepted = assert_object_response(
        api.accept_contract(contract_id, make_buyer_headers(env["buyer"]["id"]))
    )
    assert accepted["negotiation_status"] == "ACCEPTED"
    assert_buyer_exposure(read_buyer(api, rival["id"]), gross=0.00)


def test_the_valuation_publisher_cannot_also_countersign_the_contract_it_priced(api):
    """Two HeadOfSales users, one refused on identity and one allowed.

    PRD: "Countersigning a pre-sale contract requires that `X-User-ID` differ from the `published_by_user_id` of the `PUBLISHED` territory valuation covering the contract's film-and-territory pair."

    PRD: "Both checks compare user identifiers only; the role check has already passed by the time they run."

    Design: Corner/rbac/the_valuation_publisher_cannot_also_execute_the_contract_it_priced
    """
    env = accepted_contract(api)
    contract_id = env["contract"]["id"]
    assert (
        read_valuation(api, env["valuation"]["id"])["published_by_user_id"]
        == HEAD_OF_SALES_VALUER
    )

    validate_error(
        api.execute_contract(contract_id, make_sales_agent_headers(HEAD_OF_SALES_VALUER)),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api.execute_contract(contract_id, make_head_of_sales_headers(HEAD_OF_SALES_VALUER)),
        "ERR_SEGREGATION_OF_DUTIES",
        403,
    )

    executed = assert_object_response(
        api.execute_contract(contract_id, make_head_of_sales_headers(HEAD_OF_SALES_CLOSER))
    )
    assert executed["executed_by_user_id"] == HEAD_OF_SALES_CLOSER
    assert executed["negotiation_status"] == "EXECUTED"


def test_operational_roles_cannot_reach_into_each_others_endpoint_families(api):
    """Four cross-family writes all stop at the role gate, before any domain gate.

    PRD: "When both headers are well-formed but the named role is not among the roles authorised for the targeted operation (see the authorisation column of the endpoint table in §4), the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    PRD: "A `DeliveryManager` assembles and submits the technical and legal materials a contract obliges the agency to deliver, and resubmits them after a rejection."

    Design: Corner/rbac/operational_roles_cannot_reach_into_each_others_endpoint_families
    """
    env = executed_contract_environment(api)
    contract_id = env["contract"]["id"]
    film_id = env["film"]["id"]
    signature = milestone_by_label(read_milestones(api, contract_id), "ON_SIGNATURE")

    validate_error(
        api.post_receipt(
            signature["id"],
            receipt_payload(900000.00, "2026-08-05T00:00:00Z"),
            make_delivery_manager_headers(),
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    untouched = milestone_by_label(read_milestones(api, contract_id), "ON_SIGNATURE")
    assert untouched["status"] == "INVOICED"
    assert_money(untouched["received_amount_usd"], 0.00, "received_amount_usd")

    validate_error(
        api.create_deliverable_package(
            contract_id, package_payload(), make_collection_agent_headers()
        ),
        "ERR_UNAUTHORIZED",
        403,
    )

    validate_error(
        api.create_contract(
            contract_payload(
                film_id,
                env["buyer"]["id"],
                env["territory"]["id"],
                read_buyer(api, env["buyer"]["id"])["version"],
                minimum_guarantee_usd=1500000.00,
                license_term_months=12,
                holdback_days=30,
            ),
            make_lender_headers(),
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    assert_list_response(
        api.list_contracts(make_sales_agent_headers(), LIST_ALL), expected_total=1
    )

    validate_error(
        api.create_collection_account(
            film_id,
            account_payload(bank_name="Second Trust", account_reference="CAM-DUP"),
            make_sales_agent_headers(),
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    assert_list_response(
        api.list_collection_accounts(film_id, make_lender_headers(), LIST_ALL),
        expected_total=1,
        expected_rows=1,
    )


def test_read_grants_differ_by_role_on_the_distribution_ledger(api):
    """The Lender reads the ledger, the SalesAgent and the Buyer cannot.

    PRD: "When both headers are well-formed but the named role is not among the roles authorised for the targeted operation (see the authorisation column of the endpoint table in §4), the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    PRD: "A `Lender` is the discounting bank. Lenders propose a banking facility against a picture's pre-sales, approve it, post the completion bond, draw it, and declare it in default."

    Design: Corner/rbac/read_grants_differ_by_role_and_a_sales_agent_cannot_read_distribution_runs
    """
    env = executed_contract_environment(api)
    account_id = env["account"]["id"]
    buyer_headers = make_buyer_headers(env["buyer"]["id"])
    signature = milestone_by_label(read_milestones(api, env["contract"]["id"]), "ON_SIGNATURE")
    post_receipt(api, signature, "2026-08-05T00:00:00Z")
    make_tiers(api, account_id, [(1, "PARTICIPATION", 1.00, None)])
    assert_created(
        api.distribute(
            account_id, distribute_payload(900000.00), make_collection_agent_headers()
        )
    )

    rows, _meta = assert_list_response(
        api.list_distribution_runs(account_id, make_lender_headers(), LIST_ALL),
        expected_total=1,
        expected_rows=1,
    )
    assert rows[0]["run_index"] == 1

    validate_error(
        api.list_distribution_runs(account_id, make_sales_agent_headers(), LIST_ALL),
        "ERR_UNAUTHORIZED",
        403,
    )

    contract = assert_object_response(api.get_contract(env["contract"]["id"], buyer_headers))
    assert contract["negotiation_status"] == "EXECUTED"

    validate_error(
        api.list_distribution_runs(account_id, buyer_headers, LIST_ALL),
        "ERR_UNAUTHORIZED",
        403,
    )


# ==========================================================================
# The four cross-cutting layers: concurrency, cross-aggregate resync, derived counters
# ==========================================================================
def test_publishing_against_a_stale_film_version_is_refused_then_retried(api):
    """An amendment between read and publish invalidates the client's film version.

    PRD: "If `expected_film_version` does not equal the film's current `version`, the publication is rejected with `ERR_STALE_FILM_VERSION` (HTTP 412)."

    PRD: "Both precede every state and business check that follows, so a stale-version request never reaches the domain rules at all."

    Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_on_publish_rejects_a_stale_film_version
    """
    env = valued_slate(api)
    film_id = env["film"]["id"]
    valuation_id = env["valuation"]["id"]
    film_v1 = read_film(api, film_id)["version"]

    amended = assert_object_response(
        api.patch_film(
            film_id,
            film_amendment_payload(completion_status="IN_PRODUCTION"),
            make_platform_admin_headers(),
        )
    )
    film_v2 = amended["version"]
    assert film_v2 == film_v1 + 1

    validate_error(
        api.publish_valuation(
            valuation_id,
            publish_payload(film_v1),
            make_head_of_sales_headers(HEAD_OF_SALES_VALUER),
        ),
        "ERR_STALE_FILM_VERSION",
        412,
    )
    assert read_valuation(api, valuation_id)["status"] == "DRAFT"
    assert_film_counters(read_film(api, film_id), published_count=0)

    published = assert_object_response(
        api.publish_valuation(
            valuation_id,
            publish_payload(film_v2),
            make_head_of_sales_headers(HEAD_OF_SALES_VALUER),
        )
    )
    assert published["status"] == "PUBLISHED"
    assert_valuation_prices(published, CA_ESTIMATE_DE, CA_ASK_DE, CA_FLOOR_DE)
    assert_film_counters(read_film(api, film_id), published_count=1)


def test_offering_against_a_stale_buyer_version_is_refused_then_retried(api):
    """A credit-limit rise between read and offer invalidates the buyer version.

    PRD: "If `expected_buyer_version` does not equal the buyer's current `version`, the create is rejected with `ERR_STALE_BUYER_VERSION` (HTTP 412)."

    PRD: "Creation increments the buyer's `version` by 1 and recomputes the buyer's gross pipeline exposure."

    Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_on_the_offer_rejects_a_stale_buyer_version
    """
    env = slate_with_published_valuation(api)
    buyer_id = env["buyer"]["id"]
    buyer_v1 = read_buyer(api, buyer_id)["version"]

    raised = assert_object_response(
        api.patch_buyer(
            buyer_id,
            buyer_amendment_payload(exposure_limit_usd=8000000.00),
            make_platform_admin_headers(),
        )
    )
    buyer_v2 = raised["version"]
    assert buyer_v2 == buyer_v1 + 1

    payload = contract_payload(
        env["film"]["id"], buyer_id, env["territory"]["id"], buyer_v1
    )
    validate_error(
        api.create_contract(payload, make_sales_agent_headers()),
        "ERR_STALE_BUYER_VERSION",
        412,
    )
    assert_list_response(
        api.list_contracts(make_sales_agent_headers(), LIST_ALL), expected_total=0
    )
    assert_buyer_exposure(read_buyer(api, buyer_id), gross=0.00)

    contract = assert_created(
        api.create_contract(
            contract_payload(env["film"]["id"], buyer_id, env["territory"]["id"], buyer_v2),
            make_sales_agent_headers(),
        )
    )
    assert contract["negotiation_status"] == "OFFERED"
    after = read_buyer(api, buyer_id)
    assert_buyer_exposure(after, gross=CONTRACT_MG)
    assert after["version"] == buyer_v2 + 1


def test_three_unrelated_writes_resync_three_waterfall_tier_caps(api):
    """An expense log, a facility draw and a receipt each rewrite a different tier ceiling.

    PRD: "What they cannot do is *recoup* it — only the cap is ever recoverable through the waterfall, which is why logging an expense also resynchronises the `SALES_EXPENSES` waterfall tier's ceiling on every open collection account of the picture to the lesser of `expenses_incurred_usd` and `expense_cap_usd`, rounded to two decimal places."

    PRD: "Drawing sets `drawn_amount_usd` to `advance_amount_usd`, sets `outstanding_debt_usd` to the same figure, sets the picture's `BANK_DEBT` tier's `cap_usd` to the drawn amount, and recomputes the picture's `financing_gap_usd`."

    PRD: "The `SALES_COMMISSION` tier's `cap_usd` is set to the agreement's new `commission_earned_usd`."

    Design: Corner/cross_cutting_complexity_layers/three_unrelated_writes_resync_three_waterfall_tier_caps_across_aggregates
    """
    env = executed_contract_environment(api)
    film_id = env["film"]["id"]
    account_id = env["account"]["id"]
    agreement_id = env["agreement"]["id"]
    make_tiers(
        api,
        account_id,
        [
            (1, "SALES_COMMISSION", 0.10, 1.00),
            (2, "SALES_EXPENSES", 1.00, 1.00),
            (3, "BANK_DEBT", 1.00, 1.00),
        ],
    )
    facility = make_facility(api, film_id, completion_bond_required=True)

    for amount, memo in ((40000.00, "market booth"), (50000.00, "key art and trailer")):
        api.log_expense(
            agreement_id, expense_payload(amount, memo=memo), make_sales_agent_headers()
        )

    approve_facility(api, facility["id"], LENDER_APPROVER)
    bond_facility(api, facility["id"])
    draw_facility(api, facility["id"], LENDER_DRAWER)

    signature = milestone_by_label(read_milestones(api, env["contract"]["id"]), "ON_SIGNATURE")
    post_receipt(api, signature, "2026-08-05T00:00:00Z")

    tiers = read_tiers(api, account_id)
    assert_tier(find_by(tiers, tier_type="SALES_COMMISSION"), cap=90000.00, recouped=0.00)
    assert_tier(
        find_by(tiers, tier_type="SALES_EXPENSES"),
        cap=AGREEMENT_EXPENSE_CAP,
        recouped=0.00,
    )
    assert_tier(
        find_by(tiers, tier_type="BANK_DEBT"),
        cap=1000000.00,
        recouped=0.00,
        status="ACTIVE",
    )

    agreement = read_agreement(api, film_id, agreement_id)
    assert_money(agreement["expenses_incurred_usd"], 90000.00, "expenses_incurred_usd")
    assert_money(agreement["expenses_recouped_usd"], 0.00, "expenses_recouped_usd")


def test_film_and_buyer_counters_reconcile_after_execution_and_first_receipt(api):
    """Every derived counter on five aggregates agrees after one countersignature and one receipt.

    PRD: "`financing_gap_usd` is the production budget less the committed minimum guarantees, rounded to two decimal places, and then floored at zero — a picture whose pre-sales exceed its budget reports a gap of exactly 0.00 rather than a negative figure."

    PRD: "There is no deferred recomputation and no eventual consistency anywhere in this system."

    Design: Corner/cross_cutting_complexity_layers/film_and_buyer_derived_counters_reconcile_after_execution_and_first_receipt
    """
    env = executed_contract_environment(api)
    contract_id = env["contract"]["id"]
    signature = milestone_by_label(read_milestones(api, contract_id), "ON_SIGNATURE")
    post_receipt(api, signature, "2026-08-05T00:00:00Z")

    film = read_film(api, env["film"]["id"])
    assert_film_counters(
        film,
        committed=CONTRACT_MG,
        collected=900000.00,
        gap=FILM_BUDGET - CONTRACT_MG,
        published_count=1,
        licensed_count=1,
        sales_status="SOLD_OUT",
    )

    contract = read_contract(api, contract_id)
    assert_contract_axes(contract, negotiation="EXECUTED", collection="PARTIALLY_PAID")
    assert_money(contract["unpaid_amount_usd"], 1100000.00, "unpaid_amount_usd")

    assert_buyer_exposure(
        read_buyer(api, env["buyer"]["id"]), gross=CONTRACT_MG, net=1100000.00
    )

    assert_account_counters(
        read_account(api, env["account"]["id"]),
        receipts=900000.00,
        distributed=0.00,
        balance=900000.00,
    )


# ==========================================================================
# The consistency model: immediate, synchronous and all-or-nothing
# ==========================================================================
def test_the_causing_response_already_carries_the_derived_values(api):
    """The receipt response itself shows the new status and the accrued commission.

    PRD: "Cascades are **immediate and synchronous**: by the time a response is returned, every derived counter the operation touches has already been rewritten, and a subsequent read observes the new figures."

    PRD: "Step three: the commission this receipt accrues is the posted `amount_usd` multiplied by that single rate, rounded half-up to two decimal places."

    Design: Corner/consistency_model/immediate_consistency_means_the_causing_response_already_carries_the_derived_values
    """
    env = executed_contract_environment(api)
    film_id = env["film"]["id"]
    agreement_id = env["agreement"]["id"]
    signature = milestone_by_label(read_milestones(api, env["contract"]["id"]), "ON_SIGNATURE")

    booked = assert_object_response(
        api.post_receipt(
            signature["id"],
            receipt_payload(900000.00, "2026-08-05T00:00:00Z"),
            make_collection_agent_headers(),
        )
    )
    assert booked["status"] == "RECEIVED"
    assert_money(booked["received_amount_usd"], 900000.00, "received_amount_usd")
    assert_money(booked["accrued_commission_usd"], 90000.00, "accrued_commission_usd")

    first_account = read_account(api, env["account"]["id"])
    second_account = read_account(api, env["account"]["id"])
    assert_account_counters(first_account, receipts=900000.00, balance=900000.00)
    assert_account_counters(second_account, receipts=900000.00, balance=900000.00)
    assert first_account["balance_usd"] == second_account["balance_usd"]

    first_agreement = read_agreement(api, film_id, agreement_id)
    second_agreement = read_agreement(api, film_id, agreement_id)
    for agreement in (first_agreement, second_agreement):
        assert_money(agreement["gross_collected_usd"], 900000.00, "gross_collected_usd")
        assert_money(agreement["commission_earned_usd"], 90000.00, "commission_earned_usd")
    assert (
        first_agreement["commission_earned_usd"] == second_agreement["commission_earned_usd"]
    )

    assert_film_counters(read_film(api, film_id), collected=900000.00)


def test_advancing_the_clock_alone_changes_no_row(api):
    """Moving the logical present past every due date rewrites nothing.

    PRD: "A `PlatformAdmin` moves it by supplying a `to_iso8601` instant to the clock-setting capability described in §4; from that point every comparison the domain makes against the present — whether a holdback has elapsed, whether a licence term has expired, whether a cure window is still open, whether an agency agreement's term window contains the present instant, and how many days of discount tenor a lender may claim — uses the new value."

    PRD: "And the contract's `collection_status` must be `PAID`: the agency does not hand rights back to itself while the buyer still owes money."

    Design: Corner/consistency_model/advancing_the_clock_alone_changes_no_row
    """
    env = executed_contract_environment(api)
    contract_id = env["contract"]["id"]
    before = read_milestones(api, contract_id)
    statuses_before = [row["status"] for row in before]
    film_before = read_film(api, env["film"]["id"])
    assert film_before["sales_status"] == "SOLD_OUT"

    pin_clock(api, "2028-08-02T00:00:00Z")

    after = read_milestones(api, contract_id)
    assert [row["status"] for row in after] == statuses_before
    assert after[0]["status"] == "INVOICED"
    assert after[3]["status"] == "SCHEDULED"
    for row in after:
        assert_money(row["received_amount_usd"], 0.00, "received_amount_usd")

    assert_contract_axes(
        read_contract(api, contract_id),
        negotiation="EXECUTED",
        delivery="PENDING",
        collection="UNPAID",
    )

    film_after = read_film(api, env["film"]["id"])
    assert film_after["sales_status"] == "SOLD_OUT"
    assert film_after["version"] == film_before["version"]


def test_one_request_commits_all_of_its_dependent_rows_or_none_of_them(api):
    """A refused second receipt leaves every row the first receipt wrote untouched.

    PRD: "The milestone's `status` must be `SCHEDULED` or `INVOICED` — a milestone already `RECEIVED` or already `WRITTEN_OFF` is rejected with `ERR_INVALID_STATE`."

    PRD: "A successful receipt sets the milestone's `status` to `RECEIVED`, writes `received_amount_usd` to the posted amount, writes `received_at` from the payload and `received_by_user_id` from `X-User-ID`."

    Design: Corner/consistency_model/one_request_commits_all_of_its_dependent_rows_or_none_of_them
    """
    env = executed_contract_environment(api)
    contract_id = env["contract"]["id"]
    account_id = env["account"]["id"]
    make_tiers(api, account_id, [(1, "SALES_COMMISSION", 1.00, 1.00)])
    signature = milestone_by_label(read_milestones(api, contract_id), "ON_SIGNATURE")
    post_receipt(api, signature, "2026-08-05T00:00:00Z")

    validate_error(
        api.post_receipt(
            signature["id"],
            receipt_payload(900000.00, "2026-08-06T00:00:00Z"),
            make_collection_agent_headers(),
        ),
        "ERR_INVALID_STATE",
        409,
    )

    assert_account_counters(
        read_account(api, account_id),
        receipts=900000.00,
        distributed=0.00,
        balance=900000.00,
    )
    assert_tier(
        find_by(read_tiers(api, account_id), tier_type="SALES_COMMISSION"), cap=90000.00
    )

    settled = milestone_by_label(read_milestones(api, contract_id), "ON_SIGNATURE")
    assert settled["status"] == "RECEIVED"
    assert_money(settled["received_amount_usd"], 900000.00, "received_amount_usd")
    assert_instant(settled["received_at"], "2026-08-05T00:00:00Z", "received_at")

    agreement = read_agreement(api, env["film"]["id"], env["agreement"]["id"])
    assert_money(agreement["commission_earned_usd"], 90000.00, "commission_earned_usd")
    assert_film_counters(read_film(api, env["film"]["id"]), collected=900000.00)
