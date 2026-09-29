"""Endpoint contract and error-envelope behaviour of the Film Sales Presale API.

Every test drives only the declared endpoints, pins the logical clock as its first
call, and asserts pre-computed literals taken from the PRD narrative.
"""

from test_helpers import (
    CA_ASK_DE,
    CA_ESTIMATE_DE,
    CA_FLOOR_DE,
    CLOCK_DEFAULT,
    CONTRACT_MG,
    FILM_BUDGET,
    FILM_CAST_SCORE,
    FILM_GENRE,
    FILM_TITLE,
    HEAD_OF_SALES_CLOSER,
    HEAD_OF_SALES_VALUER,
    LIST_ALL,
    MILESTONE_SCHEDULE,
    NON_EXISTENT_UUID,
    NO_AUTH_HEADERS,
    accepted_contract,
    add_milestone_schedule,
    assert_account_counters,
    assert_created,
    assert_empty_collection,
    assert_film_counters,
    assert_instant,
    assert_list_response,
    assert_money,
    assert_object_response,
    assert_page_window,
    assert_single_resource_meta,
    assert_valuation_prices,
    buyer_meeting_payload,
    buyer_payload,
    completion_bond_payload,
    contract_payload,
    distribute_payload,
    executed_contract,
    executed_contract_environment,
    expense_payload,
    film_amendment_payload,
    film_payload,
    lapse_payload,
    make_account,
    make_buyer_headers,
    make_collection_agent_headers,
    make_comparables,
    make_delivery_manager_headers,
    make_film,
    make_fr_territory,
    make_head_of_sales_headers,
    make_lender_headers,
    make_market,
    make_platform_admin_headers,
    make_sales_agent_headers,
    make_territory,
    make_tiers,
    milestone_by_label,
    offered_contract,
    open_market,
    ordered_by,
    pin_clock,
    post_receipt,
    publish_payload,
    qc_pass_payload,
    read_buyer,
    read_film,
    read_milestones,
    read_valuation,
    receipt_payload,
    screening_slot_payload,
    slate_with_published_valuation,
    state_payload,
    submit_package,
    territory_payload,
    valuation_payload,
    validate_error,
)


# ==========================================================================
# Collection reads: ordering, paging and filter composition
# ==========================================================================
def test_film_slate_pages_newest_first_and_pages_do_not_overlap(api):
    """Three pictures registered on three successive days page newest first.

    PRD: "Several collections do nominate a domain ordering, and where they do it is authoritative: the film slate is returned newest first by `created_at` descending with `id` ascending as the tie-break; territories are ordered by `code` ascending; markets by `start_date` ascending then `created_at` ascending; screening slots and buyer meetings by `start_at` ascending then `created_at` ascending; a contract's payment milestones by `due_date` ascending then `created_at` ascending; a contract's deliverable packages by `revision_round` ascending then `created_at` ascending; an account's waterfall tiers by `tier_order` ascending; and an account's distribution runs by `run_index` ascending."

    PRD: "For list responses the `meta` object carries four pagination fields: `limit` and `offset` echoing the effective values used, `total_count` giving the number of rows matching the filter before the page window is applied, and `has_more` indicating whether any row remains beyond the current page."

    Design: Corner/endpoints/film_collection_read_orders_created_at_desc_and_pages_without_overlap
    """
    pin_clock(api, CLOCK_DEFAULT)
    oldest = make_film(api, title=FILM_TITLE, genre="ACTION")
    pin_clock(api, "2026-08-02T00:00:00Z")
    middle = make_film(api, title="Cold Harbour", genre="DRAMA")
    pin_clock(api, "2026-08-03T00:00:00Z")
    newest = make_film(api, title="Paper Kings", genre="COMEDY")

    headers = make_sales_agent_headers()
    first_rows, first_meta = assert_list_response(
        api.list_films(headers, {"limit": 2, "offset": 0}), expected_total=3, expected_rows=2
    )
    assert_page_window(first_meta, limit=2, offset=0, total_count=3, has_more=True)
    assert ordered_by(first_rows, "title") == ["Paper Kings", "Cold Harbour"]
    assert ordered_by(first_rows, "id") == [newest["id"], middle["id"]]

    second_rows, second_meta = assert_list_response(
        api.list_films(headers, {"limit": 2, "offset": 2}), expected_total=3, expected_rows=1
    )
    assert_page_window(second_meta, limit=2, offset=2, total_count=3, has_more=False)
    assert ordered_by(second_rows, "title") == [FILM_TITLE]
    assert second_rows[0]["id"] == oldest["id"]

    first_page_ids = set(ordered_by(first_rows, "id"))
    assert first_page_ids.isdisjoint(set(ordered_by(second_rows, "id"))), (
        "the two page windows must not share a row"
    )


def test_valuation_filters_compose_conjunctively(api):
    """Two valuations on one film-and-territory pair are separated by the filters.

    PRD: "For list responses the `meta` object carries four pagination fields: `limit` and `offset` echoing the effective values used, `total_count` giving the number of rows matching the filter before the page window is applied, and `has_more` indicating whether any row remains beyond the current page."

    PRD: "A new valuation's `status` is `DRAFT`, its `published_by_user_id` is null and its `published_at` is null."

    Design: Corner/endpoints/valuation_reverse_lookup_filters_compose_conjunctively
    """
    env = slate_with_published_valuation(api)
    film_id = env["film"]["id"]
    territory_id = env["territory"]["id"]
    published = env["valuation"]

    drafted = assert_created(
        api.create_valuation(
            valuation_payload(film_id, territory_id, "COMPARABLE_WEIGHTED"),
            make_sales_agent_headers(),
        )
    )
    assert drafted["status"] == "DRAFT"

    headers = make_sales_agent_headers()
    rows, _meta = assert_list_response(
        api.list_valuations(
            headers, {"film_id": film_id, "method": "COMPARABLE_WEIGHTED", **LIST_ALL}
        ),
        expected_total=1,
        expected_rows=1,
    )
    assert rows[0]["id"] == drafted["id"]
    assert rows[0]["status"] == "DRAFT"

    rows, _meta = assert_list_response(
        api.list_valuations(
            headers,
            {
                "film_id": film_id,
                "territory_id": territory_id,
                "status": "PUBLISHED",
                **LIST_ALL,
            },
        ),
        expected_total=1,
        expected_rows=1,
    )
    assert rows[0]["id"] == published["id"]

    assert_empty_collection(
        api.list_valuations(
            headers, {"status": "PUBLISHED", "method": "COMPARABLE_WEIGHTED", **LIST_ALL}
        )
    )

    assert_list_response(
        api.list_valuations(headers, {"film_id": film_id, **LIST_ALL}),
        expected_total=2,
        expected_rows=2,
    )


def test_contract_filters_read_each_status_axis_independently(api):
    """One contract answers a filter on each of its three status axes.

    PRD: "A contract may be `EXECUTED` and `REJECTED` and `PARTIALLY_PAID` all at once; no axis constrains another's enumerated values, and each advances on its own triggers."

    PRD: "Its `delivery_status` is one of `PENDING`, `SUBMITTED`, `ACCEPTED`, `REJECTED` or `CURED`."

    Design: Corner/endpoints/contract_reverse_lookup_filters_each_status_axis_independently
    """
    env = executed_contract_environment(api)
    contract_id = env["contract"]["id"]
    post_receipt(api, milestone_by_label(env, "ON_SIGNATURE"), "2026-08-05T00:00:00Z")

    headers = make_sales_agent_headers()
    probes = (
        {"film_id": env["film"]["id"], "negotiation_status": "EXECUTED"},
        {"buyer_id": env["buyer"]["id"], "delivery_status": "PENDING"},
        {"territory_id": env["territory"]["id"], "collection_status": "PARTIALLY_PAID"},
    )
    for params in probes:
        rows, _meta = assert_list_response(
            api.list_contracts(headers, {**params, **LIST_ALL}),
            expected_total=1,
            expected_rows=1,
        )
        assert rows[0]["id"] == contract_id, f"filter {params} returned the wrong row"

    assert_empty_collection(
        api.list_contracts(
            headers,
            {"negotiation_status": "EXECUTED", "collection_status": "UNPAID", **LIST_ALL},
        )
    )


def test_milestones_are_listed_by_due_date_not_insertion_order(api):
    """Four milestones inserted last-due-first come back in due-date order.

    PRD: "Several collections do nominate a domain ordering, and where they do it is authoritative: the film slate is returned newest first by `created_at` descending with `id` ascending as the tie-break; territories are ordered by `code` ascending; markets by `start_date` ascending then `created_at` ascending; screening slots and buyer meetings by `start_at` ascending then `created_at` ascending; a contract's payment milestones by `due_date` ascending then `created_at` ascending; a contract's deliverable packages by `revision_round` ascending then `created_at` ascending; an account's waterfall tiers by `tier_order` ascending; and an account's distribution runs by `run_index` ascending."

    PRD: "The supplied `pct_of_mg` is added to the contract's `milestone_pct_total`, which is maintained to four decimal places."

    Design: Corner/endpoints/child_reverse_lookups_order_by_their_domain_key_not_insertion_order
    """
    env = offered_contract(api)
    contract_id = env["contract"]["id"]
    add_milestone_schedule(api, contract_id, schedule=tuple(reversed(MILESTONE_SCHEDULE)))

    rows, meta = assert_list_response(
        api.list_milestones(contract_id, make_sales_agent_headers(), LIST_ALL),
        expected_total=4,
        expected_rows=4,
    )
    assert_page_window(meta, limit=100, offset=0, total_count=4, has_more=False)
    assert ordered_by(rows, "label") == [
        "ON_SIGNATURE",
        "ON_DELIVERY",
        "ON_RELEASE",
        "ON_TERM_END",
    ]
    assert_money(rows[0]["amount_usd"], 900000.00, "data[0].amount_usd")

    contract = assert_object_response(
        api.get_contract(contract_id, make_sales_agent_headers())
    )
    assert contract["milestone_pct_total"] == 1.0000


def test_nested_creation_binds_the_parent_from_the_path(api):
    """A buyer created under one territory ignores a rival territory in the body.

    PRD: "A buyer is a distributor licensing rights in exactly one territory, and a `PlatformAdmin` onboards it against that territory: the buyer's `territory_id` is taken from the creation path."

    PRD: "Clients never supply an `id`; supplying one has no effect."

    Design: Corner/endpoints/nested_creation_binds_the_parent_from_the_path_and_ignores_an_extra_field
    """
    pin_clock(api, CLOCK_DEFAULT)
    germany = make_territory(api)
    france = make_fr_territory(api)

    buyer = assert_created(
        api.create_buyer(
            germany["id"],
            buyer_payload(territory_id=france["id"]),
            make_platform_admin_headers(),
        )
    )
    assert buyer["territory_id"] == germany["id"], (
        "the parent territory must come from the creation path"
    )

    rows, _meta = assert_list_response(
        api.list_territory_buyers(germany["id"], make_sales_agent_headers(), LIST_ALL),
        expected_total=1,
        expected_rows=1,
    )
    assert rows[0]["id"] == buyer["id"]

    assert_empty_collection(
        api.list_territory_buyers(france["id"], make_sales_agent_headers(), LIST_ALL)
    )


def test_countersigning_returns_the_whole_mutated_contract(api):
    """The execute response is the contract itself, not an acknowledgement.

    PRD: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."

    PRD: "The contract's `unpaid_amount_usd` is computed as the sum of `amount_usd` across its `SCHEDULED` and `INVOICED` payment milestones, and `received_amount_usd` as the sum of `received_amount_usd` across its `RECEIVED` milestones."

    Design: Corner/endpoints/action_endpoints_return_the_whole_mutated_resource_not_a_bare_acknowledgement
    """
    env = accepted_contract(api)
    contract_id = env["contract"]["id"]

    action = assert_object_response(
        api.execute_contract(contract_id, make_head_of_sales_headers(HEAD_OF_SALES_CLOSER))
    )
    assert action["negotiation_status"] == "EXECUTED"
    assert action["delivery_status"] == "PENDING"
    assert action["collection_status"] == "UNPAID"
    assert action["executed_by_user_id"] == HEAD_OF_SALES_CLOSER
    assert_money(action["unpaid_amount_usd"], 2000000.00, "unpaid_amount_usd")

    fetched = assert_object_response(api.get_contract(contract_id, make_lender_headers()))
    assert fetched["negotiation_status"] == action["negotiation_status"]
    assert fetched["delivery_status"] == action["delivery_status"]
    assert fetched["collection_status"] == action["collection_status"]
    assert fetched["version"] == action["version"]
    assert_money(fetched["unpaid_amount_usd"], 2000000.00, "unpaid_amount_usd")


def test_distribution_runs_are_indexed_from_one(api):
    """Two runs against one account carry run_index 1 then 2, in that order.

    PRD: "The run produces an immutable `DistributionRun` record — one of the three resource types carrying only `id` and `created_at`, with no `updated_at` and no `version` — whose `run_index` is the account's `run_count` plus one at creation time, making run indices 1-based and monotonic per account, and whose `run_by_user_id` is recorded from `X-User-ID`."

    PRD: "The account's `total_distributed_usd` grows by `amount_allocated_usd`, its `balance_usd` is recomputed as `total_receipts_usd` less `total_distributed_usd` rounded to two decimal places, and its `run_count` increments by one."

    Design: Corner/endpoints/distribution_run_reverse_lookup_indexes_runs_from_one
    """
    env = executed_contract_environment(api)
    account_id = env["account"]["id"]
    post_receipt(api, milestone_by_label(env, "ON_SIGNATURE"), "2026-08-05T00:00:00Z")
    make_tiers(api, account_id, [(1, "PARTICIPATION", 1.00, None)])

    first = assert_created(
        api.distribute(
            account_id, distribute_payload(400000.00), make_collection_agent_headers()
        )
    )
    assert first["run_index"] == 1
    second = assert_created(
        api.distribute(
            account_id, distribute_payload(500000.00), make_collection_agent_headers()
        )
    )
    assert second["run_index"] == 2

    rows, _meta = assert_list_response(
        api.list_distribution_runs(account_id, make_lender_headers(), LIST_ALL),
        expected_total=2,
        expected_rows=2,
    )
    assert ordered_by(rows, "run_index") == [1, 2]
    assert_money(rows[0]["amount_in_usd"], 400000.00, "data[0].amount_in_usd")
    assert_money(rows[1]["amount_in_usd"], 500000.00, "data[1].amount_in_usd")

    account = assert_object_response(
        api.get_collection_account(account_id, make_collection_agent_headers())
    )
    assert_account_counters(
        account, receipts=900000.00, distributed=900000.00, balance=0.00, run_count=2
    )


def test_pagination_bounds_outside_their_range_are_malformed_requests(api):
    """limit 0, limit 101 and offset -1 are refused; a window past the end is not.

    PRD: "`limit` controls page size: it defaults to 10 when omitted, accepts a minimum of 1 and a maximum of 100."

    PRD: "A `limit` or `offset` outside these bounds is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/endpoints/pagination_limit_outside_its_declared_bounds_is_rejected_as_invalid_request
    """
    pin_clock(api, CLOCK_DEFAULT)
    make_film(api)

    headers = make_sales_agent_headers()
    for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
        validate_error(api.list_films(headers, params), "ERR_INVALID_REQUEST", 400)

    rows, meta = assert_list_response(
        api.list_films(headers, {"limit": 100, "offset": 5}),
        expected_total=1,
        expected_rows=0,
    )
    assert rows == []
    assert_page_window(meta, limit=100, offset=5, total_count=1, has_more=False)


def test_amendment_accepts_a_partial_body_and_leaves_unlisted_fields_alone(api):
    """A completion-status amendment touches nothing else; a cast-score change stales.

    PRD: "Production facts may be amended after registration, but only four of them: `completion_status`, `principal_cast_score`, `theatrical_release_date` and `estimated_delivery_date`."

    PRD: "One amendment carries a destructive side effect: if the submitted `principal_cast_score` differs from the stored value, every `PUBLISHED` territory valuation of the picture is moved to `STALE`, because the cast tier multiplier already baked into each published estimate is no longer defensible."

    Design: Corner/endpoints/patch_endpoint_accepts_a_partial_body_and_leaves_unlisted_fields_alone
    """
    env = slate_with_published_valuation(api)
    film_id = env["film"]["id"]
    valuation_id = env["valuation"]["id"]

    amended = assert_object_response(
        api.patch_film(
            film_id,
            film_amendment_payload(completion_status="IN_PRODUCTION"),
            make_platform_admin_headers(),
        )
    )
    assert amended["completion_status"] == "IN_PRODUCTION"
    assert amended["principal_cast_score"] == FILM_CAST_SCORE
    assert amended["title"] == FILM_TITLE
    assert amended["genre"] == FILM_GENRE
    assert_money(amended["production_budget_usd"], FILM_BUDGET, "production_budget_usd")
    assert read_valuation(api, valuation_id)["status"] == "PUBLISHED"
    assert_film_counters(read_film(api, film_id), published_count=1)

    version_before = amended["version"]
    restaged = assert_object_response(
        api.patch_film(
            film_id,
            film_amendment_payload(
                principal_cast_score=75, theatrical_release_date="2027-05-01T00:00:00Z"
            ),
            make_platform_admin_headers(),
        )
    )
    assert restaged["version"] == version_before + 1
    assert restaged["principal_cast_score"] == 75
    assert restaged["completion_status"] == "IN_PRODUCTION"
    assert_instant(
        restaged["theatrical_release_date"],
        "2027-05-01T00:00:00Z",
        "theatrical_release_date",
    )
    assert read_valuation(api, valuation_id)["status"] == "STALE"
    assert_film_counters(read_film(api, film_id), published_count=0)


def test_action_on_a_terminal_contract_is_refused_while_the_row_stays_readable(api):
    """A lapsed contract refuses acceptance yet still reads back in full.

    PRD: "This guard covers every state-driving operation in the system: the state endpoints on films, agency agreements, markets, screening slots, buyer meetings, banking facilities and collection accounts, plus countering, revising an offer, accepting, executing, lapsing, reverting, publishing, recording a quality-control verdict, posting a receipt, reversing a receipt, and posting a completion bond."

    PRD: "`REVERTED` and `LAPSED` are both terminal on the negotiation axis."

    Design: Corner/endpoints/conditional_action_on_a_terminal_row_is_refused_while_the_row_stays_readable
    """
    env = offered_contract(api)
    contract_id = env["contract"]["id"]
    buyer_headers = make_buyer_headers(env["buyer"]["id"])
    add_milestone_schedule(api, contract_id)

    lapsed = assert_object_response(
        api.lapse_contract(
            contract_id,
            lapse_payload(reason="BUYER_WITHDREW"),
            make_head_of_sales_headers(),
        )
    )
    assert lapsed["negotiation_status"] == "LAPSED"

    validate_error(
        api.accept_contract(contract_id, buyer_headers), "ERR_INVALID_STATE", 409
    )

    response = api.get_contract(contract_id, buyer_headers)
    contract = assert_object_response(response)
    assert_single_resource_meta(response)
    assert contract["negotiation_status"] == "LAPSED"
    assert_money(contract["minimum_guarantee_usd"], CONTRACT_MG, "minimum_guarantee_usd")

    assert_list_response(
        api.list_milestones(contract_id, make_sales_agent_headers(), LIST_ALL),
        expected_total=4,
        expected_rows=4,
    )


def test_every_remaining_reverse_lookup_answers_from_both_ends(api):
    """Market, slot, meeting, account and package collections each answer their filter.

    PRD: "The service computes `duration_minutes` as the whole minutes between the two instants, flooring any partial minute."

    PRD: "Its `revision_round` is 1 when no prior package exists for this contract, and otherwise one more than the `revision_round` of the contract's latest package, selected as the last row by `created_at` ascending."

    Design: Corner/endpoints/the_remaining_reverse_lookups_answer_from_both_ends_of_each_relationship
    """
    env = accepted_contract(api)
    film_id = env["film"]["id"]
    buyer_id = env["buyer"]["id"]

    market = make_market(
        api,
        name="EFM Berlin",
        city="Berlin",
        start_date="2027-02-11T00:00:00Z",
        end_date="2027-02-17T00:00:00Z",
        screening_room_count=3,
        meeting_table_count=4,
    )
    market = open_market(api, market["id"])
    slot = assert_created(
        api.create_screening_slot(
            screening_slot_payload(
                market["id"],
                film_id,
                1,
                "2027-02-11T09:00:00Z",
                "2027-02-11T11:00:00Z",
            ),
            make_sales_agent_headers(),
        )
    )
    meeting = assert_created(
        api.create_buyer_meeting(
            buyer_meeting_payload(
                market["id"],
                buyer_id,
                film_id,
                1,
                "2027-02-11T09:00:00Z",
                "2027-02-11T10:00:00Z",
            ),
            make_sales_agent_headers(),
        )
    )

    env = executed_contract(api, env)
    contract_id = env["contract"]["id"]
    make_account(api, film_id)
    pin_clock(api, "2027-06-14T00:00:00Z")
    package = submit_package(api, contract_id)

    agent_headers = make_sales_agent_headers()
    rows, _meta = assert_list_response(
        api.list_markets(agent_headers, {"status": "OPEN", **LIST_ALL}),
        expected_total=1,
        expected_rows=1,
    )
    assert rows[0]["name"] == "EFM Berlin"

    fetched_market = assert_object_response(api.get_market(market["id"], agent_headers))
    assert fetched_market["screening_room_count"] == 3
    assert fetched_market["meeting_table_count"] == 4

    rows, _meta = assert_list_response(
        api.list_screening_slots(
            agent_headers, {"market_id": market["id"], "room_number": 1, **LIST_ALL}
        ),
        expected_total=1,
        expected_rows=1,
    )
    assert rows[0]["id"] == slot["id"]
    assert rows[0]["status"] == "HELD"

    rows, _meta = assert_list_response(
        api.list_buyer_meetings(
            agent_headers, {"buyer_id": buyer_id, "status": "SCHEDULED", **LIST_ALL}
        ),
        expected_total=1,
        expected_rows=1,
    )
    assert rows[0]["id"] == meeting["id"]
    assert rows[0]["duration_minutes"] == 60

    rows, _meta = assert_list_response(
        api.list_collection_accounts(film_id, make_lender_headers(), LIST_ALL),
        expected_total=1,
        expected_rows=1,
    )
    assert rows[0]["status"] == "OPEN"

    rows, _meta = assert_list_response(
        api.list_deliverable_packages(
            contract_id, make_buyer_headers(buyer_id), LIST_ALL
        ),
        expected_total=1,
        expected_rows=1,
    )
    assert rows[0]["id"] == package["id"]
    assert rows[0]["revision_round"] == 1
    assert rows[0]["status"] == "SUBMITTED"


# ==========================================================================
# Error envelopes and existence codes
# ==========================================================================
def _assert_error_envelope(response, expected_error_id, expected_status):
    """The refusal carries the standard error envelope and nothing else."""
    data = validate_error(response, expected_error_id, expected_status)
    body = response.json()
    assert body["response_type"] == "error", (
        f"expected response_type error, got {body['response_type']!r}"
    )
    assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}, (
        f"error meta must carry exactly the two request fields, got {sorted(body['meta'])}"
    )
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {body['meta']['api_request_id']!r}"
    )
    assert "error_id" in data and "message" in data, f"error data is incomplete: {data}"
    return data


def test_unknown_ids_return_the_owning_entitys_own_not_found_code(api):
    """Nine unresolvable ids each report the code of the entity that owns the id.

    PRD: "A film referenced by path or by a body `film_id` must exist, else `ERR_FILM_NOT_FOUND`; then a territory referenced by path or by a body `territory_id`, else `ERR_TERRITORY_NOT_FOUND`; then a market referenced by path or by a body `market_id`, else `ERR_MARKET_NOT_FOUND`; then a buyer referenced by path or by a body `buyer_id`, else `ERR_BUYER_NOT_FOUND`; then a pre-sale contract referenced by path, else `ERR_CONTRACT_NOT_FOUND`; then a territory valuation, else `ERR_VALUATION_NOT_FOUND`; then a sales agency agreement, else `ERR_AGREEMENT_NOT_FOUND`; then a payment milestone, else `ERR_MILESTONE_NOT_FOUND`; then a deliverable package, else `ERR_PACKAGE_NOT_FOUND`; then a banking facility, else `ERR_FACILITY_NOT_FOUND`; then a collection account, else `ERR_ACCOUNT_NOT_FOUND`; and finally a screening slot or buyer meeting referenced by path, either of which when unresolvable yields `ERR_MARKET_ITEM_NOT_FOUND`."

    PRD: "All twelve of these carry HTTP 404."

    Design: Corner/errors/unknown_ids_return_the_owning_entitys_own_not_found_code
    """
    pin_clock(api, CLOCK_DEFAULT)
    agent_headers = make_sales_agent_headers()

    _assert_error_envelope(
        api.get_buyer(NON_EXISTENT_UUID, make_platform_admin_headers()),
        "ERR_BUYER_NOT_FOUND",
        404,
    )
    _assert_error_envelope(
        api.get_valuation(NON_EXISTENT_UUID, agent_headers),
        "ERR_VALUATION_NOT_FOUND",
        404,
    )
    _assert_error_envelope(
        api.log_expense(NON_EXISTENT_UUID, expense_payload(40000.00), agent_headers),
        "ERR_AGREEMENT_NOT_FOUND",
        404,
    )
    _assert_error_envelope(
        api.post_receipt(
            NON_EXISTENT_UUID,
            receipt_payload(900000.00, "2026-08-05T00:00:00Z"),
            make_collection_agent_headers(),
        ),
        "ERR_MILESTONE_NOT_FOUND",
        404,
    )
    _assert_error_envelope(
        api.post_qc_result(
            NON_EXISTENT_UUID, qc_pass_payload(), make_buyer_headers(NON_EXISTENT_UUID)
        ),
        "ERR_PACKAGE_NOT_FOUND",
        404,
    )
    _assert_error_envelope(
        api.post_completion_bond(
            NON_EXISTENT_UUID, completion_bond_payload(), make_lender_headers()
        ),
        "ERR_FACILITY_NOT_FOUND",
        404,
    )
    _assert_error_envelope(
        api.get_collection_account(NON_EXISTENT_UUID, make_collection_agent_headers()),
        "ERR_ACCOUNT_NOT_FOUND",
        404,
    )
    _assert_error_envelope(
        api.get_screening_slot(NON_EXISTENT_UUID, agent_headers),
        "ERR_MARKET_ITEM_NOT_FOUND",
        404,
    )
    _assert_error_envelope(
        api.get_buyer_meeting(NON_EXISTENT_UUID, agent_headers),
        "ERR_MARKET_ITEM_NOT_FOUND",
        404,
    )


def test_error_envelope_is_identical_at_every_status_class_of_one_write(api):
    """One amendment route refused four ways yields four identically shaped bodies.

    PRD: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."

    PRD: "Each amendment is available to `PlatformAdmin` alone, increments the picture's `version` by 1, and refreshes `updated_at`."

    Design: Corner/errors/error_envelope_shape_is_identical_at_every_status_class_when_a_write_is_rejected
    """
    pin_clock(api, CLOCK_DEFAULT)
    film = make_film(api)
    film_id = film["id"]
    amendment = film_amendment_payload(completion_status="IN_PRODUCTION")

    refusals = [
        _assert_error_envelope(
            api.patch_film(film_id, amendment, NO_AUTH_HEADERS),
            "ERR_UNAUTHENTICATED",
            401,
        ),
        _assert_error_envelope(
            api.patch_film(film_id, amendment, make_sales_agent_headers()),
            "ERR_UNAUTHORIZED",
            403,
        ),
        _assert_error_envelope(
            api.patch_film(NON_EXISTENT_UUID, amendment, make_platform_admin_headers()),
            "ERR_FILM_NOT_FOUND",
            404,
        ),
        _assert_error_envelope(
            api.patch_film(
                film_id,
                film_amendment_payload(completion_status="RELEASED"),
                make_platform_admin_headers(),
            ),
            "ERR_INVALID_REQUEST",
            400,
        ),
    ]
    for data in refusals:
        for leaked in ("title", "genre", "sales_status", "version", "completion_status"):
            assert leaked not in data, f"the error body leaked the film field {leaked}"

    unchanged = read_film(api, film_id)
    assert unchanged["principal_cast_score"] == FILM_CAST_SCORE
    assert unchanged["completion_status"] == "SCRIPT"
    assert unchanged["version"] == 1


def test_one_state_endpoint_returns_four_status_classes_by_error_class(api):
    """The market state route answers 403, 404, 400 and 409 from one path.

    PRD: "A market's lifecycle is linear: `PLANNED → OPEN → CLOSED`, both edges reserved to `PlatformAdmin`."

    PRD: "Whether the row's own current status permits the requested transition, including a repeated trigger on a row already in the destination state or already in a terminal state, else `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/errors/one_endpoint_returns_four_different_status_classes_by_error_class
    """
    pin_clock(api, CLOCK_DEFAULT)
    market = make_market(api)
    assert market["status"] == "PLANNED"
    opened = open_market(api, market["id"])
    assert opened["status"] == "OPEN"
    closed = assert_object_response(
        api.set_market_state(
            market["id"], state_payload("CLOSED"), make_platform_admin_headers()
        )
    )
    assert closed["status"] == "CLOSED"
    version_after_close = closed["version"]

    _assert_error_envelope(
        api.set_market_state(
            market["id"], state_payload("OPEN"), make_sales_agent_headers()
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    _assert_error_envelope(
        api.set_market_state(
            NON_EXISTENT_UUID, state_payload("OPEN"), make_platform_admin_headers()
        ),
        "ERR_MARKET_NOT_FOUND",
        404,
    )
    _assert_error_envelope(
        api.set_market_state(
            market["id"], state_payload("SOLD"), make_platform_admin_headers()
        ),
        "ERR_INVALID_REQUEST",
        400,
    )
    _assert_error_envelope(
        api.set_market_state(
            market["id"], state_payload("OPEN"), make_platform_admin_headers()
        ),
        "ERR_INVALID_STATE",
        409,
    )

    final = assert_object_response(api.get_market(market["id"], make_sales_agent_headers()))
    assert final["status"] == "CLOSED"
    assert final["version"] == version_after_close


def test_a_refused_write_leaves_no_row_and_advances_no_version(api):
    """A duplicate territory code and an out-of-range score both write nothing.

    PRD: "A `PlatformAdmin` creates each one with a `code` — a 2-to-3-letter uppercase identifier that must be unique across every territory in the system, with a duplicate rejected as `ERR_TERRITORY_CODE_TAKEN` — a human-readable `name`, a `region` grouping, a `market_tier` between 1 and 3 inclusive where 1 denotes a major territory, a `currency_code` naming the local settlement currency for information only, and a `base_value_index` between 0.10 and 2.00 inclusive."

    PRD: "Every required body field present, every enum value a member of its declared set, every number inside its declared range, and every end-or-close instant strictly after its start counterpart, else `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/errors/a_refused_write_leaves_no_row_and_advances_no_version
    """
    env = slate_with_published_valuation(api)
    film_id = env["film"]["id"]
    film_before = read_film(api, film_id)

    _assert_error_envelope(
        api.create_territory(territory_payload(), make_platform_admin_headers()),
        "ERR_TERRITORY_CODE_TAKEN",
        409,
    )
    _assert_error_envelope(
        api.patch_film(
            film_id,
            film_amendment_payload(principal_cast_score=-1),
            make_platform_admin_headers(),
        ),
        "ERR_INVALID_REQUEST",
        400,
    )

    assert_list_response(
        api.list_territories(make_sales_agent_headers(), LIST_ALL),
        expected_total=1,
        expected_rows=1,
    )

    film_after = read_film(api, film_id)
    assert film_after["version"] == film_before["version"]
    assert film_after["principal_cast_score"] == FILM_CAST_SCORE
    assert read_valuation(api, env["valuation"]["id"])["status"] == "PUBLISHED"
    assert_film_counters(film_after, published_count=1)
