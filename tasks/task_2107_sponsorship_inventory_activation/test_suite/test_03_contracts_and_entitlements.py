"""Drafting deals: entitlement clauses, submission gates and the revision loop."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_entitlement,
    add_rate_card_line,
    assert_contract,
    assert_entitlement,
    create_contract,
    create_inventory_asset,
    create_property,
    create_rate_card,
    create_sponsor,
    publish_rate_card,
    read_contract,
    read_property,
    setup_contract_scenario,
    setup_exhausted_revision_contract,
    submit_contract,
    transition_property,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["property_admin_headers"]
SELLER = TEST_USERS["seller_headers"]
APPROVER = TEST_USERS["approver_headers"]


def test_entitlement_copies_asset_class_from_the_linked_asset(api):
    """PRD §3.4: "On creation the entitlement copies its `asset_class` from the
    linked asset — that copy, and not the rate card, is what later selects the
    priced line — takes its `contract_id` from the request path, and opens in
    `PENDING` with `unit_value_cents`, `gross_value_cents`, `delivered_units` and
    `makegood_credit_cents` all at 0 and `delivery_pct` at 0.00."

    Design: Corner/entities/entitlement_copies_asset_class_and_starts_pending
    """
    prop = create_property()
    signage_asset = create_inventory_asset(
        prop["id"], name="South Fascia Board", asset_class="SIGNAGE",
        capacity_units=3, changeover_buffer_minutes=0,
    )
    sponsor = create_sponsor()
    contract = create_contract(sponsor["id"], prop["id"])

    response = api.create_entitlement(
        contract["id"],
        {
            "inventory_asset_id": signage_asset["id"],
            "clause_ref": "7.4",
            "promised_units": 3,
        },
        SELLER,
    )
    entitlement = validate_success(response, 201)

    assert_entitlement(entitlement)
    assert entitlement["asset_class"] == "SIGNAGE", (
        "asset_class is copied from the linked asset, got "
        f"{entitlement['asset_class']}"
    )
    assert entitlement["contract_id"] == contract["id"]
    assert entitlement["status"] == "PENDING"
    assert entitlement["unit_value_cents"] == 0
    assert entitlement["gross_value_cents"] == 0
    assert entitlement["delivered_units"] == 0
    assert entitlement["makegood_credit_cents"] == 0
    assert entitlement["delivery_pct"] == 0.00


def test_contract_list_pages_and_filters_by_property(api):
    """PRD §2.3: "`limit` caps the number of records returned; when it is omitted
    it defaults to 10, and a supplied value must be at least 1 and at most 100."
    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and
    `has_more` inside the `meta` object of the envelope, where `total_count`
    reflects the number of records matching the filters before the page window is
    applied."
    PRD §3.4: "Contracts can be enumerated and narrowed by `sponsor_id`, by
    `property_id`, by the pinned `rate_card_id`, or by `status`."

    Design: Corner/entities/contracts_list_paginates_and_filters_by_property
    """
    prop = create_property()
    brands = [
        ("Zephyr Cola", "BEVERAGE", "ops@zephyr.example"),
        ("Nimbus Motors", "AUTOMOTIVE", "ops@nimbus.example"),
        ("Vega Telecom", "TELECOM", "ops@vega.example"),
    ]
    for name, category, email in brands:
        sponsor = create_sponsor(
            name=name, category=category, contact_email=email
        )
        create_contract(sponsor["id"], prop["id"])

    first_response = api.list_contracts(
        APPROVER, {"property_id": prop["id"], "limit": 2, "offset": 0}
    )
    first_page, first_meta = validate_paginated(first_response)
    assert first_response.json()["response_type"] == "array"
    assert len(first_page) == 2, f"expected 2 rows on page one, got {len(first_page)}"
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True

    second_response = api.list_contracts(
        APPROVER, {"property_id": prop["id"], "limit": 2, "offset": 2}
    )
    second_page, second_meta = validate_paginated(second_response)
    assert second_response.json()["response_type"] == "array"
    assert len(second_page) == 1, (
        f"expected 1 row on page two, got {len(second_page)}"
    )
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert first_page[0]["id"] != second_page[0]["id"]


def test_submit_and_countersign_preconditions_reject_in_declared_order(api):
    """PRD §3.5: "Three conditions gate the submission and are evaluated in this
    order. The owning property must be in `SELLING` or `IN_SEASON`; a property
    still in `PLANNING`, or already `CLOSED`, yields `ERR_PROPERTY_NOT_SELLING`.
    The contract must carry at least one entitlement, or the submission fails
    with `ERR_NO_ENTITLEMENTS`."
    PRD §3.5: "Then the published card must carry a priced line for every distinct
    `asset_class` appearing among the contract's entitlements; a missing line is
    `ERR_RATE_LINE_MISSING`."

    Design: Corner/validations/submit_and_countersign_preconditions_reject_in_priority_order
    """
    prop = create_property()
    signage_asset = create_inventory_asset(
        prop["id"], name="South Fascia Board", asset_class="SIGNAGE",
        capacity_units=3, changeover_buffer_minutes=0,
    )
    sponsor = create_sponsor()
    contract = create_contract(sponsor["id"], prop["id"])
    card = create_rate_card(prop["id"])
    add_rate_card_line(
        card["id"], asset_class="DIGITAL_BOARD", base_unit_price_cents=250_000
    )

    on_planning = api.submit_contract(contract["id"], SELLER)
    validate_error(on_planning, ApiErrorId.ERR_PROPERTY_NOT_SELLING.value)

    publish_rate_card(card["id"])
    transition_property(prop["id"], "SELLING")

    without_clauses = api.submit_contract(contract["id"], SELLER)
    validate_error(without_clauses, ApiErrorId.ERR_NO_ENTITLEMENTS.value)

    add_entitlement(
        contract["id"], signage_asset["id"], clause_ref="7.4", promised_units=3
    )
    submit_contract(contract["id"])

    expected_property_version = read_property(prop["id"])["version"]
    unpriced_class = api.countersign_contract(
        contract["id"],
        {"expected_property_version": expected_property_version},
        APPROVER,
    )
    validate_error(unpriced_class, ApiErrorId.ERR_RATE_LINE_MISSING.value)

    after = read_contract(contract["id"])
    assert after["status"] == "SUBMITTED"
    assert after["rate_card_id"] is None
    assert read_property(prop["id"])["committed_gross_value_cents"] == 0


def test_countersign_from_draft_and_close_from_countersigned_are_rejected(api):
    """PRD §3.5: "Any lifecycle action requested from a state that does not
    declare it — submitting an already-`SUBMITTED` contract, countersigning a
    `DRAFT` one, activating an `ACTIVE` one, closing a `COUNTERSIGNED` one,
    terminating a `CLOSED` one, or any action at all against a `CLOSED` or
    `TERMINATED` contract — is rejected with `ERR_INVALID_STATE` and fires no
    side effect."

    Design: Corner/state_machines/contract_countersign_from_draft_and_close_from_countersigned_rejected
    """
    scenario = setup_contract_scenario(
        stage="DRAFT", contract_overrides={"exclusivity_scope": "CATEGORY"}
    )
    contract_id = scenario["contract"]["id"]
    property_id = scenario["property"]["id"]

    on_draft = api.countersign_contract(
        contract_id,
        {"expected_property_version": read_property(property_id)["version"]},
        APPROVER,
    )
    validate_error(on_draft, ApiErrorId.ERR_INVALID_STATE.value)

    submit_contract(contract_id)
    countersigned = validate_success(
        api.countersign_contract(
            contract_id,
            {"expected_property_version": read_property(property_id)["version"]},
            APPROVER,
        )
    )
    assert_contract(countersigned)
    assert countersigned["status"] == "COUNTERSIGNED"

    early_close = api.close_contract(contract_id, APPROVER)
    validate_error(early_close, ApiErrorId.ERR_INVALID_STATE.value)

    after = read_contract(contract_id)
    assert after["status"] == "COUNTERSIGNED"
    assert after["makegood_credit_cents"] == 0


def test_fifth_submission_after_four_returns_is_refused(api):
    """PRD §3.5: "And the contract's `revision_round` must be at most 3; once it
    has reached 4 the revision loop is exhausted and the submission fails with
    `ERR_REVISION_LIMIT_REACHED`."
    PRD §3.5: "Three completed revision rounds are permitted; the fourth return
    leaves `revision_round` at 4, and any attempt to resubmit after that is
    refused."

    Design: Difficulty/non_linear_state_machine/contract_submit_return_revision_cycle_exhausts_at_four
    """
    scenario = setup_exhausted_revision_contract()
    contract = scenario["contract"]

    assert contract["revision_round"] == 4, (
        f"four returns leave revision_round at 4, got {contract['revision_round']}"
    )
    assert contract["status"] == "DRAFT"

    response = api.submit_contract(contract["id"], SELLER)
    validate_error(response, ApiErrorId.ERR_REVISION_LIMIT_REACHED.value)
    assert response.status_code == 409


def test_refused_fifth_submission_leaves_the_revision_row_untouched(api):
    """PRD §3.5: "A successful submission stamps `submitted_by_user_id` with the
    caller's `X-User-ID`."
    PRD §3.5: "The return raises `revision_round` by 1 and clears
    `submitted_by_user_id` back to null, so the next submission establishes a
    fresh submitter."
    PRD §3.5: "And the contract's `revision_round` must be at most 3; once it has
    reached 4 the revision loop is exhausted and the submission fails with
    `ERR_REVISION_LIMIT_REACHED`."

    Design: Difficulty/non_linear_state_machine/contract_submit_return_revision_cycle_exhausts_at_four
    """
    scenario = setup_exhausted_revision_contract()
    contract_id = scenario["contract"]["id"]

    assert scenario["contract"]["submitted_by_user_id"] is None, (
        "the return clears submitted_by_user_id back to null"
    )

    refused = api.submit_contract(contract_id, SELLER)
    validate_error(refused, ApiErrorId.ERR_REVISION_LIMIT_REACHED.value)

    after = read_contract(contract_id)
    assert after["status"] == "DRAFT"
    assert after["submitted_by_user_id"] is None
    assert after["revision_round"] == 4, (
        "the rejected submit must not raise revision_round, got "
        f"{after['revision_round']}"
    )
