"""Rejection-ladder precedence and validation-rule boundaries, part one.

Every test in this module drives the declared endpoints only, starts from an
empty database, and pins the logical clock with its first call.  The rules under
test are the fixed system-wide rejection ladder of PRD section 2.7 and the
per-resource validation gates of PRD section 3.
"""

from test_helpers import (
    AGREEMENT_TERM_END,
    COLLECTION_AGENT_USER,
    CONTRACT_MG,
    HEAD_OF_SALES_CLOSER,
    HEAD_OF_SALES_VALUER,
    LIST_ALL,
    MILESTONE_SCHEDULE,
    NON_EXISTENT_UUID,
    NO_AUTH_HEADERS,
    TEST_USERS,
    add_milestone_schedule,
    assert_account_counters,
    assert_allocations,
    assert_buyer_exposure,
    assert_contract_axes,
    assert_created,
    assert_empty_collection,
    assert_film_counters,
    assert_list_response,
    assert_money,
    assert_object_response,
    assert_tier,
    buyer_amendment_payload,
    contract_payload,
    counter_payload,
    distribute_payload,
    engaged_slate,
    executed_contract_environment,
    film_amendment_payload,
    film_payload,
    find_by,
    get_success_data,
    make_buyer,
    make_buyer_headers,
    make_collection_agent_headers,
    make_film,
    make_head_of_sales_headers,
    make_market,
    make_platform_admin_headers,
    make_sales_agent_headers,
    make_tiers,
    milestone_by_label,
    milestone_payload,
    offered_contract,
    open_market,
    pin_clock,
    post_receipt,
    publish_payload,
    read_account,
    read_agreement,
    read_buyer,
    read_contract,
    read_film,
    read_milestones,
    read_tiers,
    read_valuation,
    receipt_payload,
    screening_slot_payload,
    state_payload,
    valuation_payload,
    valued_slate,
    validate_error,
)


def _pct_total(contract):
    """The contract's running milestone share total as a float."""
    return float(contract["milestone_pct_total"])


def test_absent_headers_outrank_role_path_and_shape_checks(api):
    """An unauthenticated amendment reports authentication, not the unknown film.

    PRD: "If either header is absent, or if `X-User-Role` does not spell one of the seven recognised roles exactly, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_headers_return_unauthenticated_before_every_other_check
    """
    pin_clock(api)

    refused = api.patch_film(
        NON_EXISTENT_UUID,
        film_amendment_payload(principal_cast_score=999),
        NO_AUTH_HEADERS,
    )
    validate_error(refused, "ERR_UNAUTHENTICATED", 401)

    assert_empty_collection(api.list_films(make_platform_admin_headers(), LIST_ALL))


def test_role_gate_outranks_body_validation_on_film_registration(api):
    """A forbidden role is reported before the half-filled body is inspected.

    PRD: "When both headers are well-formed but the named role is not among the roles authorised for the targeted operation (see the authorisation column of the endpoint table in §4), the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    PRD: "**Second, authorisation.** The acting role listed for the target endpoint, else `ERR_UNAUTHORIZED`."

    Design: Corner/validations/role_check_returns_unauthorized_before_body_validation
    """
    pin_clock(api)

    refused = api.create_film(
        film_payload(
            title=None,
            genre=None,
            principal_cast_score=None,
            estimated_delivery_date=None,
            theatrical_release_date=None,
        ),
        TEST_USERS["collection_agent_headers"],
    )
    validate_error(refused, "ERR_UNAUTHORIZED", 403)

    assert_empty_collection(api.list_films(make_platform_admin_headers(), LIST_ALL))


def test_unknown_contract_in_the_path_outranks_the_missing_body_fields(api):
    """The unresolvable path id is reported even though the body is incomplete.

    PRD: "A film referenced by path or by a body `film_id` must exist, else `ERR_FILM_NOT_FOUND`; then a territory referenced by path or by a body `territory_id`, else `ERR_TERRITORY_NOT_FOUND`; then a market referenced by path or by a body `market_id`, else `ERR_MARKET_NOT_FOUND`; then a buyer referenced by path or by a body `buyer_id`, else `ERR_BUYER_NOT_FOUND`; then a pre-sale contract referenced by path, else `ERR_CONTRACT_NOT_FOUND`; then a territory valuation, else `ERR_VALUATION_NOT_FOUND`; then a sales agency agreement, else `ERR_AGREEMENT_NOT_FOUND`; then a payment milestone, else `ERR_MILESTONE_NOT_FOUND`; then a deliverable package, else `ERR_PACKAGE_NOT_FOUND`; then a banking facility, else `ERR_FACILITY_NOT_FOUND`; then a collection account, else `ERR_ACCOUNT_NOT_FOUND`; and finally a screening slot or buyer meeting referenced by path, either of which when unresolvable yields `ERR_MARKET_ITEM_NOT_FOUND`."

    PRD: "This check sits *after* existence, so a request that both names a non-existent film and omits a required field reports the missing film."

    Design: Corner/validations/unknown_path_id_returns_contract_not_found_before_invalid_request
    """
    pin_clock(api)

    refused = api.create_milestone(
        NON_EXISTENT_UUID,
        milestone_payload("ON_SIGNATURE", None, None),
        make_sales_agent_headers(),
    )
    validate_error(refused, "ERR_CONTRACT_NOT_FOUND", 404)


def test_body_film_lookup_outranks_the_body_territory_lookup(api):
    """With both body foreign keys unresolvable the film is reported first.

    PRD: "A film referenced by path or by a body `film_id` must exist, else `ERR_FILM_NOT_FOUND`; then a territory referenced by path or by a body `territory_id`, else `ERR_TERRITORY_NOT_FOUND`; then a market referenced by path or by a body `market_id`, else `ERR_MARKET_NOT_FOUND`; then a buyer referenced by path or by a body `buyer_id`, else `ERR_BUYER_NOT_FOUND`; then a pre-sale contract referenced by path, else `ERR_CONTRACT_NOT_FOUND`; then a territory valuation, else `ERR_VALUATION_NOT_FOUND`; then a sales agency agreement, else `ERR_AGREEMENT_NOT_FOUND`; then a payment milestone, else `ERR_MILESTONE_NOT_FOUND`; then a deliverable package, else `ERR_PACKAGE_NOT_FOUND`; then a banking facility, else `ERR_FACILITY_NOT_FOUND`; then a collection account, else `ERR_ACCOUNT_NOT_FOUND`; and finally a screening slot or buyer meeting referenced by path, either of which when unresolvable yields `ERR_MARKET_ITEM_NOT_FOUND`."

    PRD: "All twelve of these carry HTTP 404."

    Design: Corner/validations/film_lookup_outranks_territory_lookup_when_both_body_ids_are_not_found
    """
    pin_clock(api)

    both_unknown = api.create_valuation(
        valuation_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID),
        make_sales_agent_headers(),
    )
    validate_error(both_unknown, "ERR_FILM_NOT_FOUND", 404)

    film = make_film(api)
    territory_unknown = api.create_valuation(
        valuation_payload(film["id"], NON_EXISTENT_UUID),
        make_sales_agent_headers(),
    )
    validate_error(territory_unknown, "ERR_TERRITORY_NOT_FOUND", 404)

    assert_empty_collection(api.list_valuations(make_sales_agent_headers(), LIST_ALL))


def test_invalid_request_outranks_the_buyer_ownership_check_on_a_counter(api):
    """A stranger's malformed counter reports shape first, ownership second.

    PRD: "**Fourth, request shape.** Every required body field present, every enum value a member of its declared set, every number inside its declared range, and every end-or-close instant strictly after its start counterpart, else `ERR_INVALID_REQUEST` (HTTP 400)."

    PRD: "The payload must carry a `counter_minimum_guarantee_usd`, and may optionally carry a `counter_license_term_months` and a `counter_holdback_days`."

    PRD: "This applies to exactly three operations — countering an offer, accepting an offer, and recording a quality-control verdict — and its failure code is `ERR_NOT_CONTRACT_BUYER` (HTTP 403)."

    Design: Corner/validations/body_validation_returns_invalid_request_before_the_buyer_scope_check
    """
    env = offered_contract(api)
    contract_id = env["contract"]["id"]
    stranger = TEST_USERS["buyer_headers_unowned"]

    malformed = api.counter_contract(contract_id, {}, stranger)
    validate_error(malformed, "ERR_INVALID_REQUEST", 400)

    well_formed = api.counter_contract(contract_id, counter_payload(1800000.00), stranger)
    validate_error(well_formed, "ERR_NOT_CONTRACT_BUYER", 403)

    stored = read_contract(api, contract_id)
    assert_contract_axes(stored, negotiation="OFFERED")
    assert stored["negotiation_round"] == 1, (
        f"the refused counter must not advance the round, got {stored['negotiation_round']}"
    )
    assert stored.get("counter_minimum_guarantee_usd") is None, (
        "the refused counter must not record a counter offer"
    )


def test_film_state_gate_outranks_the_market_open_gate_on_a_booking(api):
    """A booking naming a DEVELOPMENT picture and a PLANNED market reports the film.

    PRD: "**Eighth, the state of a *related* row**, in this order: the film's `sales_status` being in the window the operation needs, else `ERR_FILM_NOT_IN_MARKET` (409); then the referenced market being `OPEN`, else `ERR_MARKET_NOT_OPEN` (409); then the film's collection account existing and being `OPEN`, else `ERR_COLLECTION_ACCOUNT_NOT_OPEN` (409)."

    PRD: "The picture's `sales_status` must be either `PACKAGING` or `IN_MARKET` — a picture still in `DEVELOPMENT`, already `SOLD_OUT`, or `WRAPPED` cannot be screened — and failure yields `ERR_FILM_NOT_IN_MARKET`."

    Design: Corner/validations/film_state_gate_outranks_the_market_open_gate_on_slot_creation
    """
    env = engaged_slate(api)
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
    booking = screening_slot_payload(
        market["id"], film_id, 1, "2027-02-12T09:00:00Z", "2027-02-12T11:00:00Z", capacity=60
    )

    film_first = api.create_screening_slot(booking, make_sales_agent_headers())
    validate_error(film_first, "ERR_FILM_NOT_IN_MARKET", 409)

    get_success_data(
        api.set_film_state(film_id, state_payload("PACKAGING"), make_platform_admin_headers())
    )
    market_second = api.create_screening_slot(booking, make_sales_agent_headers())
    validate_error(market_second, "ERR_MARKET_NOT_OPEN", 409)

    assert_empty_collection(api.list_screening_slots(make_sales_agent_headers(), LIST_ALL))

    open_market(api, market["id"])
    slot = assert_created(api.create_screening_slot(booking, make_sales_agent_headers()))
    assert slot["status"] == "HELD", f"a new slot is HELD, got {slot['status']}"
    assert slot["room_number"] == 1, f"expected room 1, got {slot['room_number']}"


def test_publishing_at_the_exact_term_end_instant_is_out_of_force(api):
    """The term end instant itself is outside the term; one second earlier is inside.

    PRD: "An agreement is **in force** when its `status` is `EXECUTED` and the logical present instant is at or after `term_start_date` and strictly before `term_end_date`."

    PRD: "The picture's sales agency agreement must be in force, else `ERR_AGENCY_AGREEMENT_NOT_IN_FORCE`."

    Design: Corner/validations/publishing_at_the_exact_term_end_instant_is_out_of_force
    """
    env = valued_slate(api)
    film_id = env["film"]["id"]
    valuation_id = env["valuation"]["id"]
    second = assert_created(
        api.create_valuation(
            valuation_payload(film_id, env["territory"]["id"], "COMPARABLE_WEIGHTED"),
            make_sales_agent_headers(),
        )
    )
    film_version = read_film(api, film_id)["version"]

    pin_clock(api, AGREEMENT_TERM_END)
    refused = api.publish_valuation(
        valuation_id,
        publish_payload(film_version),
        make_head_of_sales_headers(HEAD_OF_SALES_VALUER),
    )
    validate_error(refused, "ERR_AGENCY_AGREEMENT_NOT_IN_FORCE", 422)
    assert read_valuation(api, valuation_id)["status"] == "DRAFT", (
        "the refused publication must leave the valuation in DRAFT"
    )
    assert_film_counters(read_film(api, film_id), published_count=0)

    pin_clock(api, "2028-07-31T23:59:59Z")
    published = assert_object_response(
        api.publish_valuation(
            valuation_id,
            publish_payload(film_version),
            make_head_of_sales_headers(HEAD_OF_SALES_VALUER),
        )
    )
    assert published["status"] == "PUBLISHED", (
        f"one second inside the term publishes, got {published['status']}"
    )
    assert read_agreement(api, film_id, env["agreement"]["id"])["status"] == "EXECUTED", (
        "the agreement's own status is untouched by the passage of the term"
    )
    assert read_valuation(api, second["id"])["status"] == "DRAFT", (
        "the untouched second valuation stays DRAFT"
    )
    assert_film_counters(read_film(api, film_id), published_count=1)


def test_blocking_the_buyer_stops_the_accept_it_previously_allowed(api):
    """A BLOCKED buyer cannot accept; restoring ACTIVE lets the same call through.

    PRD: "The buyer's trading `status` must be `ACTIVE` or `WATCHLIST`; a `BLOCKED` buyer is rejected with `ERR_BUYER_BLOCKED`."

    Design: Corner/validations/patching_the_buyer_to_blocked_stops_the_accept_it_already_allowed
    """
    env = offered_contract(api)
    contract_id = env["contract"]["id"]
    buyer_id = env["buyer"]["id"]

    get_success_data(
        api.patch_buyer(
            buyer_id, buyer_amendment_payload(status="BLOCKED"), make_platform_admin_headers()
        )
    )
    refused = api.accept_contract(contract_id, make_buyer_headers(buyer_id))
    validate_error(refused, "ERR_BUYER_BLOCKED", 422)
    assert_contract_axes(read_contract(api, contract_id), negotiation="OFFERED")
    assert_buyer_exposure(read_buyer(api, buyer_id), gross=CONTRACT_MG)

    get_success_data(
        api.patch_buyer(
            buyer_id, buyer_amendment_payload(status="ACTIVE"), make_platform_admin_headers()
        )
    )
    accepted = assert_object_response(
        api.accept_contract(contract_id, make_buyer_headers(buyer_id))
    )
    assert_contract_axes(accepted, negotiation="ACCEPTED")
    assert_buyer_exposure(read_buyer(api, buyer_id), gross=CONTRACT_MG)


def test_duplicate_territory_offer_blocks_a_rival_but_not_the_same_buyer(api):
    """A rival buyer is refused the territory; the incumbent supersedes its own offer.

    PRD: "The territory-exclusivity gate rejects with `ERR_DUPLICATE_TERRITORY_OFFER` when either of two conditions holds: some contract for the same film-and-territory pair already has `negotiation_status` `ACCEPTED` or `EXECUTED`, or some contract for that pair with `negotiation_status` `OFFERED` or `COUNTERED` belongs to a *different* buyer."

    PRD: "It also lapses any earlier contract for the same film, buyer and territory that was sitting in `OFFERED` or `COUNTERED` — the supersede cascade, which is why the buyer's version moves and why the stale-version guard on this operation exists."

    Design: Corner/validations/duplicate_territory_offer_blocks_a_rival_buyer_but_the_same_buyer_supersedes
    """
    env = offered_contract(api)
    film_id = env["film"]["id"]
    territory_id = env["territory"]["id"]
    incumbent_id = env["buyer"]["id"]
    rival = make_buyer(api, territory_id, company_name="Elbe Pictures")

    refused = api.create_contract(
        contract_payload(
            film_id,
            rival["id"],
            territory_id,
            read_buyer(api, rival["id"])["version"],
            minimum_guarantee_usd=1500000.00,
        ),
        make_sales_agent_headers(),
    )
    validate_error(refused, "ERR_DUPLICATE_TERRITORY_OFFER", 409)
    assert_buyer_exposure(read_buyer(api, rival["id"]), gross=0.00)

    superseding = assert_created(
        api.create_contract(
            contract_payload(
                film_id,
                incumbent_id,
                territory_id,
                read_buyer(api, incumbent_id)["version"],
                minimum_guarantee_usd=1000000.00,
            ),
            make_sales_agent_headers(),
        )
    )
    assert_contract_axes(superseding, negotiation="OFFERED")
    assert_money(
        superseding["minimum_guarantee_usd"], 1000000.00, "minimum_guarantee_usd"
    )
    assert_contract_axes(read_contract(api, env["contract"]["id"]), negotiation="LAPSED")
    assert_buyer_exposure(read_buyer(api, incumbent_id), gross=1000000.00)


def test_milestone_schedule_must_total_one_with_unique_labels(api):
    """Overshoot, duplicate labels and a partial schedule all report the same code.

    PRD: "Two rules govern the schedule, both reporting `ERR_MILESTONE_SCHEDULE_INVALID`."

    PRD: "While the schedule is being built, the contract's running `milestone_pct_total` plus the new `pct_of_mg` must not exceed 1.0000 — a partial schedule is perfectly acceptable mid-build — and no two milestones of the same contract may share the same `label`."

    PRD: "At countersigning time the rule tightens: the stored `milestone_pct_total` must equal exactly 1.0000, so a schedule that stops at 0.9000 blocks execution just as surely as one that would have overshot."

    Design: Corner/validations/milestone_schedule_must_sum_to_exactly_one_and_labels_must_be_unique
    """
    env = offered_contract(api)
    contract_id = env["contract"]["id"]
    add_milestone_schedule(api, contract_id, MILESTONE_SCHEDULE[:3])
    get_success_data(api.accept_contract(contract_id, make_buyer_headers(env["buyer"]["id"])))

    overshoot = api.create_milestone(
        contract_id,
        milestone_payload("ON_TERM_END", 0.30, "2028-08-01T00:00:00Z"),
        make_sales_agent_headers(),
    )
    validate_error(overshoot, "ERR_MILESTONE_SCHEDULE_INVALID", 422)
    assert abs(_pct_total(read_contract(api, contract_id)) - 0.7500) < 0.00005, (
        "the refused milestone must not move milestone_pct_total off 0.7500"
    )

    duplicate = api.create_milestone(
        contract_id,
        milestone_payload("ON_SIGNATURE", 0.25, "2028-08-01T00:00:00Z"),
        make_sales_agent_headers(),
    )
    validate_error(duplicate, "ERR_MILESTONE_SCHEDULE_INVALID", 422)

    partial = api.execute_contract(
        contract_id, make_head_of_sales_headers(HEAD_OF_SALES_CLOSER)
    )
    validate_error(partial, "ERR_MILESTONE_SCHEDULE_INVALID", 422)
    assert_contract_axes(read_contract(api, contract_id), negotiation="ACCEPTED")

    tail = assert_created(
        api.create_milestone(
            contract_id,
            milestone_payload("ON_TERM_END", 0.25, "2028-08-01T00:00:00Z"),
            make_sales_agent_headers(),
        )
    )
    assert_money(tail["amount_usd"], 500000.00, "amount_usd")
    completed = read_contract(api, contract_id)
    assert abs(_pct_total(completed) - 1.0000) < 0.00005, (
        f"expected milestone_pct_total 1.0000, got {completed['milestone_pct_total']}"
    )

    executed = assert_object_response(
        api.execute_contract(contract_id, make_head_of_sales_headers(HEAD_OF_SALES_CLOSER))
    )
    assert_contract_axes(executed, negotiation="EXECUTED")
    assert_money(executed["unpaid_amount_usd"], CONTRACT_MG, "unpaid_amount_usd")
    assert_list_response(
        api.list_milestones(contract_id, make_sales_agent_headers(), LIST_ALL),
        expected_total=4,
        expected_rows=4,
    )


def test_receipt_amount_must_match_the_milestone_to_the_cent(api):
    """One cent under and one cent over are both refused; the exact figure books.

    PRD: "And the posted `amount_usd` must equal the milestone's own `amount_usd` **exactly**: no partial payment, no overpayment, no rounding slack."

    PRD: "Any discrepancy is rejected with `ERR_RECEIPT_AMOUNT_MISMATCH`."

    Design: Corner/validations/receipt_amount_must_match_the_milestone_to_the_cent
    """
    env = executed_contract_environment(api)
    milestone = milestone_by_label(env, "ON_SIGNATURE")
    account_id = env["account"]["id"]
    assert_money(milestone["amount_usd"], 900000.00, "amount_usd")

    under = api.post_receipt(
        milestone["id"],
        receipt_payload(899999.99, "2026-08-05T00:00:00Z"),
        make_collection_agent_headers(),
    )
    validate_error(under, "ERR_RECEIPT_AMOUNT_MISMATCH", 422)

    over = api.post_receipt(
        milestone["id"],
        receipt_payload(900000.01, "2026-08-05T00:00:00Z"),
        make_collection_agent_headers(),
    )
    validate_error(over, "ERR_RECEIPT_AMOUNT_MISMATCH", 422)

    untouched = milestone_by_label(read_milestones(api, env["contract"]["id"]), "ON_SIGNATURE")
    assert untouched["status"] == "INVOICED", (
        f"a refused receipt leaves the milestone INVOICED, got {untouched['status']}"
    )
    assert_account_counters(read_account(api, account_id), receipts=0.00, balance=0.00)

    booked = assert_object_response(
        api.post_receipt(
            milestone["id"],
            receipt_payload(900000.00, "2026-08-05T00:00:00Z"),
            make_collection_agent_headers(COLLECTION_AGENT_USER),
        )
    )
    assert booked["status"] == "RECEIVED", (
        f"the exact amount books the milestone, got {booked['status']}"
    )
    assert_money(booked["received_amount_usd"], 900000.00, "received_amount_usd")
    assert booked["received_by_user_id"] == COLLECTION_AGENT_USER, (
        f"expected received_by_user_id {COLLECTION_AGENT_USER}, "
        f"got {booked['received_by_user_id']}"
    )


def test_distribution_cannot_exceed_the_balance_and_equality_passes(api):
    """One cent above the balance is refused; the balance itself distributes fully.

    PRD: "The account must be `OPEN`, and the offered amount must not exceed the account's `balance_usd`; landing exactly on the balance passes, and exceeding it is rejected with `ERR_INSUFFICIENT_ACCOUNT_BALANCE`."

    Design: Corner/validations/distribution_cannot_exceed_the_account_balance_and_equality_passes
    """
    env = executed_contract_environment(api)
    account_id = env["account"]["id"]
    post_receipt(api, milestone_by_label(env, "ON_SIGNATURE"), "2026-08-05T00:00:00Z")
    tier = make_tiers(api, account_id, [(1, "PARTICIPATION", 1.00, None)])[0]
    assert_account_counters(read_account(api, account_id), receipts=900000.00, balance=900000.00)

    refused = api.distribute(
        account_id, distribute_payload(900000.01), make_collection_agent_headers()
    )
    validate_error(refused, "ERR_INSUFFICIENT_ACCOUNT_BALANCE", 422)
    assert_empty_collection(
        api.list_distribution_runs(account_id, make_collection_agent_headers(), LIST_ALL)
    )

    run = assert_created(
        api.distribute(
            account_id, distribute_payload(900000.00), make_collection_agent_headers()
        )
    )
    assert run["run_index"] == 1, f"expected run_index 1, got {run['run_index']}"
    assert_money(run["amount_allocated_usd"], 900000.00, "amount_allocated_usd")
    assert_money(run["residual_usd"], 0.00, "residual_usd")
    assert_allocations(run, [900000.00], tier_count=1)
    assert_tier(find_by(read_tiers(api, account_id), id=tier["id"]), recouped=900000.00, status="ACTIVE")
    assert_account_counters(
        read_account(api, account_id),
        receipts=900000.00,
        distributed=900000.00,
        balance=0.00,
        run_count=1,
    )
