"""Who may act: authentication before anything, then the role sets, ownership and duties.

Each refusal here is also shown to be the *first* refusal — the request that is
turned away is otherwise perfectly lawful, and the same call succeeds when the
right caller makes it.
"""

from test_helpers import (
    ADMIN,
    ANALYST_ONE,
    ANALYST_TWO,
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_error_payload_shape,
    assert_instant_equals,
    create_county,
    create_listing_payload,
    create_protest_payload,
    create_second_brokerage,
    decision_payload,
    escrow_deposit_payload,
    escrow_settlement_payload,
    make_broker_headers,
    make_buyer_headers,
    make_escrow_officer_headers,
    make_headers,
    make_regulator_analyst_headers,
    make_seller_headers,
    qualification_review_payload,
    read_agreement,
    read_application,
    read_buyer,
    read_county,
    read_license,
    read_listing,
    read_premises,
    set_clock,
    setup_scenario,
    validate_error,
    validate_paginated,
    validate_success,
    zoning_verification_payload,
)


def test_blank_and_unrecognised_headers_are_unauthenticated_before_any_other_check():
    """Empty headers, an empty user id and a seventh role name all answer 401 first.

    PRD: "A header that is absent, and equally a header whose value is the empty
    string, causes the request to be rejected with `ERR_UNAUTHENTICATED` (HTTP
    401). The same `ERR_UNAUTHENTICATED` rejection applies when `X-User-Role`
    carries a value that is not one of the six roles the platform recognises."

    PRD: "1. **Headers present.** Both `X-User-ID` and `X-User-Role` must be
    present and non-empty on every request — `ERR_UNAUTHENTICATED` (401)."

    PRD: "2. **Role recognised.** `X-User-Role` must be one of the six declared
    roles, on every request — `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/rbac/absent_or_unknown_role_header_is_unauthenticated_before_anything_else
    """
    county = create_county()

    both_blank = api_client.get_county(county["id"], make_headers("", ""))
    blank_error = validate_error(both_blank, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    assert_error_payload_shape(blank_error)

    no_user_id = api_client.get_county(county["id"], make_headers("", "PlatformAdmin"))
    validate_error(no_user_id, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    seventh_role = api_client.get_county(county["id"], make_headers("clerk-1", "CountyClerk"))
    unknown_error = validate_error(
        seventh_role, ApiErrorId.ERR_UNAUTHENTICATED.value, 401
    )
    assert unknown_error["error_id"] != ApiErrorId.ERR_ROLE_NOT_PERMITTED.value

    # Authentication is decided before the path identifier is ever resolved, so a
    # dangling id under an unrecognised role is still 401 and never 404.
    missing_row = api_client.get_county(NON_EXISTENT_UUID, make_headers("clerk-1", "CountyClerk"))
    dangling_error = validate_error(missing_row, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    assert dangling_error["error_id"] != ApiErrorId.ERR_COUNTY_NOT_FOUND.value

    # Nor is the body ever inspected: a well-formed write with blank headers is
    # refused for the headers, not accepted and not schema-checked.
    unauthenticated_write = api_client.create_county(
        {"county_code": "NAP", "name": "Napa", "state_code": "CA",
         "quota_licenses_total": 50},
        make_headers("", ""),
    )
    validate_error(unauthenticated_write, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    untouched = read_county(county["id"])
    assert untouched["version"] == county["version"]
    assert untouched["quota_licenses_counted"] == 0


def test_neither_the_buyer_nor_the_seller_may_work_the_listing_lifecycle():
    """Publication, withdrawal and listing creation are refused on the role, not the state.

    PRD: "3. **Role permitted.** The role must appear in the endpoint's authorised
    set, on every request — `ERR_ROLE_NOT_PERMITTED` (403)."

    PRD: "A `Broker` is the licensed intermediary: it lists licenses, drafts and
    executes agreements, files the agency disclosure, files and refiles transfer
    applications, answers protests, and may petition safekeeping."

    Design: Corner/rbac/buyer_and_seller_cannot_drive_the_brokers_listing_lifecycle
    """
    scenario = setup_scenario(stage="listing_draft")
    listing_id = scenario["listing_id"]
    assert scenario["listing"]["status"] == "DRAFT"

    buyer_activate = api_client.activate_listing(
        listing_id, make_buyer_headers(scenario["buyer_id"])
    )
    validate_error(buyer_activate, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    seller_withdraw = api_client.withdraw_listing(
        listing_id, make_seller_headers(scenario["seller_id"])
    )
    validate_error(seller_withdraw, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    buyer_create = api_client.create_listing(
        create_listing_payload(scenario["license_id"], scenario["brokerage_id"],
                              ask_price_cents=17000000),
        make_buyer_headers(scenario["buyer_id"]),
    )
    validate_error(buyer_create, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    _, meta = validate_paginated(
        api_client.list_listings(ADMIN, params={"license_id": scenario["license_id"]})
    )
    assert meta["total_count"] == 1

    published = validate_success(api_client.activate_listing(
        listing_id, make_broker_headers(scenario["brokerage_id"])
    ))
    assert published["status"] == "ACTIVE"
    assert published["version"] == 2


def test_the_broker_may_not_stand_in_for_the_licensing_authority():
    """Decision, protest intake, zoning verification and qualification review are all 403.

    PRD: "A `RegulatorAnalyst` runs buyer qualification reviews, records zoning
    verification outcomes, drives the application review lifecycle, records
    third-party protests, issues transfer decisions, and decides safekeeping
    filings."

    PRD: "3. **Role permitted.** The role must appear in the endpoint's authorised
    set, on every request — `ERR_ROLE_NOT_PERMITTED` (403)."

    Design: Corner/rbac/brokers_cannot_perform_the_regulators_exclusive_review_steps
    """
    scenario = setup_scenario(stage="application_posted")
    application_id = scenario["application_id"]
    posted = read_application(application_id)
    assert posted["status"] == "POSTED"

    broker_headers = make_broker_headers(scenario["brokerage_id"])

    broker_decision = api_client.decide_application(
        application_id, decision_payload("APPROVED"), broker_headers
    )
    validate_error(broker_decision, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    broker_protest = api_client.create_protest(
        create_protest_payload(application_id, protestant_name="Rival Bar",
                              grounds="PUBLIC_WELFARE"),
        broker_headers,
    )
    validate_error(broker_protest, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    broker_zoning = api_client.zoning_verification(
        scenario["premises_id"], zoning_verification_payload("DENIED"), broker_headers
    )
    validate_error(broker_zoning, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    buyer_review = api_client.qualification_review(
        scenario["buyer_id"],
        qualification_review_payload(scenario["premises_id"], "PRE_CHECK"),
        make_buyer_headers(scenario["buyer_id"]),
    )
    validate_error(buyer_review, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    officer_decision = api_client.decide_application(
        application_id, decision_payload("DENIED"), make_escrow_officer_headers()
    )
    validate_error(officer_decision, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    unchanged = read_application(application_id)
    assert unchanged["status"] == "POSTED"
    assert unchanged["decision"] is None
    assert unchanged["version"] == posted["version"]
    assert read_premises(scenario["premises_id"])["conditional_use_permit_status"] == "GRANTED"
    assert read_buyer(scenario["buyer_id"])["qualification_mode"] == "FINAL_REVIEW"

    _, meta = validate_paginated(
        api_client.list_protests(ADMIN, params={"application_id": application_id})
    )
    assert meta["total_count"] == 0


def test_settlement_belongs_to_the_escrow_officer_alone_while_the_deposit_is_shared():
    """Broker and Seller are refused on settlement; the Buyer's own deposit still lands.

    PRD: "When `X-User-Role` is `EscrowOfficer`, `X-User-ID` is an opaque
    escrow-holder identifier that the server does not persist on any record and
    does not compare to any entity's `id`. An `EscrowOfficer` is the sole operator
    of settlement and may also fund a deposit; it may never draft, execute or
    terminate an agreement."

    PRD: "A `Buyer` registers candidate premises, records the landlord's consent
    decision, funds the escrow, and acknowledges the agency disclosure as the
    buyer side."

    Design: Corner/rbac/only_the_escrow_officer_may_move_the_money
    """
    scenario = setup_scenario(stage="disclosure_acked")
    agreement_id = scenario["agreement_id"]
    assert scenario["agreement"]["required_deposit_cents"] == 2405001
    assert scenario["agreement"]["escrow_status"] == "AWAITING_DEPOSIT"

    broker_settlement = api_client.escrow_settlement(
        agreement_id, escrow_settlement_payload("REFUND"),
        make_broker_headers(scenario["brokerage_id"]),
    )
    validate_error(broker_settlement, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    funded = validate_success(api_client.escrow_deposit(
        agreement_id, escrow_deposit_payload(2405001),
        make_buyer_headers(scenario["buyer_id"]),
    ))
    assert funded["escrow_status"] == "HELD"
    assert funded["escrow_balance_cents"] == 2405001

    seller_settlement = api_client.escrow_settlement(
        agreement_id, escrow_settlement_payload("REFUND"),
        make_seller_headers(scenario["seller_id"]),
    )
    validate_error(seller_settlement, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    rows, meta = validate_paginated(
        api_client.list_escrow_ledger_entries(ADMIN, params={"agreement_id": agreement_id})
    )
    assert meta["total_count"] == 1
    assert rows[0]["entry_type"] == "DEPOSIT"
    assert rows[0]["amount_cents"] == 2405001
    assert read_agreement(agreement_id)["escrow_status"] == "HELD"


def test_a_second_registered_firm_passes_the_role_check_and_fails_on_ownership():
    """Gulf Brokers is a lawful Broker and still no party to Bay Brokers' agreement.

    PRD: "When `X-User-Role` is `Broker`, `X-User-ID` is the `id` of the acting
    `Brokerage`. Ownership checks compare it to the `brokerage_id` of the listing,
    purchase agreement, or — reached through the protested application and its
    agreement — protest being acted on."

    PRD: "7. **Ownership.** For entity-backed roles, the ownership comparison of
    section 2.1 — `ERR_NOT_RESOURCE_OWNER` (403). This check guards twelve
    operations: listing activation, listing withdrawal, agreement drafting,
    agreement execution, escrow deposit, agreement termination, disclosure filing,
    disclosure acknowledgement, transfer-application filing, application
    resubmission, protest response, and safekeeping filing."

    Design: Corner/rbac/a_foreign_brokerage_cannot_execute_another_firms_agreement
    """
    scenario = setup_scenario(stage="escrow_held")
    agreement_id = scenario["agreement_id"]
    foreign = create_second_brokerage()
    foreign_headers = make_broker_headers(foreign["id"])

    stolen_execution = api_client.execute_agreement(agreement_id, foreign_headers)
    validate_error(stolen_execution, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    # Ownership is consulted at step 7, so the foreign firm never reaches the open
    # offer count that would have refused even the owning firm's withdrawal.
    stolen_withdrawal = api_client.withdraw_listing(scenario["listing_id"], foreign_headers)
    withdrawal_error = validate_error(
        stolen_withdrawal, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403
    )
    assert withdrawal_error["error_id"] != ApiErrorId.ERR_LISTING_HAS_OPEN_OFFERS.value

    executed = validate_success(api_client.execute_agreement(
        agreement_id, make_broker_headers(scenario["brokerage_id"])
    ))
    assert executed["agreement_status"] == "EXECUTED"
    assert executed["brokerage_id"] == scenario["brokerage_id"]
    assert executed["brokerage_id"] != foreign["id"]
    assert read_listing(scenario["listing_id"])["status"] == "UNDER_CONTRACT"


def test_the_analyst_who_accepted_the_review_can_never_be_the_one_who_decides():
    """analyst-1 is refused on the decision at every instant; analyst-2 closes the transfer.

    PRD: "Segregation of duties is enforced at one specific point: the
    `RegulatorAnalyst` issuing a transfer decision must present an `X-User-ID`
    different from the value stored in that application's
    `accepted_by_analyst_id`. An analyst who tries to decide an application they
    themselves accepted for review is refused with `ERR_SEGREGATION_OF_DUTIES`
    (HTTP 403)."

    PRD: "8. **Segregation of duties.** On the transfer decision only —
    `ERR_SEGREGATION_OF_DUTIES` (403)."

    PRD: "26. **Posting period elapsed** — `ERR_POSTING_PERIOD_NOT_ELAPSED` (409),
    on the transfer decision."

    Design: Corner/rbac/the_accepting_analyst_may_never_decide_the_same_application
    """
    scenario = setup_scenario(stage="application_posted", analyst_id=ANALYST_ONE)
    application_id = scenario["application_id"]
    assert read_application(application_id)["accepted_by_analyst_id"] == ANALYST_ONE

    # Segregation is step 8 and the publication window is step 26, so the accepting
    # analyst is turned away on identity even while the posting is still running.
    too_early = api_client.decide_application(
        application_id, decision_payload("APPROVED"),
        make_regulator_analyst_headers(ANALYST_ONE),
    )
    early_error = validate_error(
        too_early, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403
    )
    assert early_error["error_id"] != ApiErrorId.ERR_POSTING_PERIOD_NOT_ELAPSED.value

    set_clock("2026-09-10T00:00:00Z")
    still_refused = api_client.decide_application(
        application_id, decision_payload("APPROVED"),
        make_regulator_analyst_headers(ANALYST_ONE),
    )
    validate_error(still_refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    assert read_application(application_id)["status"] == "POSTED"

    approved = validate_success(api_client.decide_application(
        application_id, decision_payload("APPROVED"),
        make_regulator_analyst_headers(ANALYST_TWO),
    ))
    assert approved["status"] == "APPROVED"
    assert approved["decision"] == "APPROVED"
    assert approved["accepted_by_analyst_id"] == ANALYST_ONE
    assert_instant_equals(approved["decided_at"], "2026-09-10T00:00:00Z", "decided_at")
    assert read_license(scenario["license_id"])["status"] == "TRANSFERRED"
    assert read_agreement(scenario["agreement_id"])["agreement_status"] == "CLOSED"
