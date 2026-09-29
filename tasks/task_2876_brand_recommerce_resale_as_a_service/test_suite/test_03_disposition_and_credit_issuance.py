"""Disposition: the four-link acceptance cascade and the disjoint rejection."""

from test_helpers import (
    ADMIN,
    CREDIT_POLICY_CORE,
    GRADE_POLICY_FOOTWEAR_A,
    GRADE_POLICY_FOOTWEAR_B,
    GRADE_POLICY_FOOTWEAR_SALVAGE,
    api_client,
    assert_credit_grant,
    assert_credit_ledger_entry,
    assert_instant,
    assert_null,
    assert_pagination_meta,
    assert_resale_unit,
    authenticate_trade_in,
    create_credit_policy,
    create_customer,
    create_grade_policy,
    create_store_location,
    create_trade_in,
    disposition_trade_in,
    fetch_customer,
    grant_ledger_entries,
    grant_of_trade_in,
    place_order,
    receive_trade_in,
    setup_credit_source_grant,
    setup_estate,
    setup_listed_unit,
    unit_of_trade_in,
    validate_paginated,
)


def _authenticated_footwear_trade_in(assessed_grade="A", item_mass_grams=900):
    """Ava's mail-in FOOTWEAR trade-in graded GENUINE and ready for disposition."""
    create_grade_policy(GRADE_POLICY_FOOTWEAR_A)
    create_grade_policy(GRADE_POLICY_FOOTWEAR_B)
    create_credit_policy(CREDIT_POLICY_CORE)
    create_store_location()
    customer = create_customer(email="ava@example.com", full_name="Ava Reyes",
                              loyalty_tier="PLUS")
    assert customer["version"] == 1
    assert customer["credit_balance_minor"] == 0
    assert customer["diverted_grams_total"] == 0
    trade_in = create_trade_in(
        customer,
        channel="MAIL_IN",
        product_category="FOOTWEAR",
        declared_grade="A",
        msrp_minor=120000,
        item_mass_grams=item_mass_grams,
    )
    receive_trade_in(trade_in["id"])
    authenticate_trade_in(trade_in["id"], "GENUINE", assessed_grade)
    return customer, trade_in


def test_acceptance_cascades_from_trade_in_to_grant_to_ledger_to_balance():
    """Each link is caused by the previous link, not by the request.

    PRD §3.4: "The **first link** moves the trade-in to `ACCEPTED`, writes
    `accepted_at` from the logical clock, overwrites `appraised_credit_minor`
    with the *final* appraisal, and bumps the trade-in's version."
    PRD §3.4: "The **second link**, caused by the first, creates one
    brand-currency grant."
    PRD §3.4: "computes `expires_at` as `issued_at` plus the pinned policy's
    `expiry_days` whole days, and enters `status` `ISSUED`."
    PRD §3.4: "The **third link**, caused by the second, appends the grant's
    opening ledger entry: `credit_grant_id` pointing at the new grant,
    `resale_order_id` null because no order is involved, `entry_type` `ISSUE`,
    `amount_minor` the full issued amount as a positive number,
    `balance_after_minor` equal to that same issued amount, and `occurred_at`
    from the logical clock."
    PRD §3.4: "The **fourth link**, caused by the third, recomputes the
    participant's `credit_balance_minor` as the sum of `remaining_minor` over
    that customer's grants whose `status` is `ISSUED` or `PARTIALLY_REDEEMED`,
    and increments the customer's version."

    Design: Difficulty/transitive_cascade/acceptance_cascades_trade_in_to_grant_to_ledger_to_customer_balance
    """
    customer, trade_in = _authenticated_footwear_trade_in(assessed_grade="A")

    accepted = disposition_trade_in(trade_in["id"], "ACCEPT", "OWNED_INVENTORY")

    # Link 1: base 120000 * 3500bp = 42000, mail-in 4200, PLUS loyalty 2100.
    assert accepted["status"] == "ACCEPTED"
    assert_instant(accepted["accepted_at"], "2026-08-01T00:00:00Z", "accepted_at")
    assert accepted["appraised_credit_minor"] == 48300
    assert accepted["version"] > trade_in["version"]

    # Link 2, caused by link 1.
    grant = grant_of_trade_in(trade_in["id"])
    assert_credit_grant(grant)
    assert grant["customer_id"] == customer["id"]
    assert grant["trade_in_id"] == trade_in["id"]
    assert grant["issued_amount_minor"] == 48300
    assert grant["remaining_minor"] == 48300
    assert grant["status"] == "ISSUED"
    assert_instant(grant["issued_at"], accepted["accepted_at"], "issued_at")
    # 2026-08-01 plus the pinned policy's 180 whole days.
    assert_instant(grant["expires_at"], "2027-01-28T00:00:00Z", "expires_at")

    # Link 3, caused by link 2.
    entries = grant_ledger_entries(grant["id"])
    assert len(entries) == 1
    opening = entries[0]
    assert_credit_ledger_entry(opening)
    assert opening["credit_grant_id"] == grant["id"]
    assert opening["entry_type"] == "ISSUE"
    assert opening["amount_minor"] == 48300
    assert opening["balance_after_minor"] == 48300
    assert_null(opening["resale_order_id"], "resale_order_id")
    assert_instant(opening["occurred_at"], "2026-08-01T00:00:00Z", "occurred_at")

    # Link 4, caused by link 3: recomputed from the grants, not from the body.
    after = fetch_customer(customer["id"])
    assert after["credit_balance_minor"] == 48300
    assert after["version"] == 2


def test_acceptance_mints_the_unit_branch_in_parallel_with_the_credit_chain():
    """The unit branch runs off link 1 and prices nothing.

    PRD §3.4: "Running in parallel off the first link, a **resale unit** is
    created."
    PRD §3.4: "It records `trade_in_id`, copies `product_category` straight
    across, copies `condition_grade` from the trade-in's `assessed_grade` — not
    from the declared grade — copies `reference_msrp_minor` from `msrp_minor`
    and `mass_grams` from `item_mass_grams`, giving the unit its own
    denormalized pricing input and its own conserved mass."
    PRD §3.4: "The unit begins in lifecycle state `INTAKE`, accounting state
    `UNCAPITALIZED`, with `capitalized_cost_minor` at 0, `list_price_minor` and
    `current_price_minor` and `listed_at` and `listed_channel_id` and
    `replacement_for_unit_id` all null, `markdown_step_count` at 0 and
    `aged_days` at 0."
    PRD §3.4: "Creating the unit in turn causes the participant's
    `diverted_grams_total` to be recomputed."
    PRD §3.4: "Its `ownership_treatment` comes from the request's optional
    `ownership_treatment` field and is `OWNED_INVENTORY` when that field is
    omitted; the only other value is `CONSIGNED`."

    Design: Difficulty/transitive_cascade/acceptance_cascades_trade_in_to_grant_to_ledger_to_customer_balance
    """
    # Declared A but assessed B, so the unit's grade can only have come from the
    # grader's verdict and the final appraisal can only have used the B tier.
    customer, trade_in = _authenticated_footwear_trade_in(assessed_grade="B")

    # ownership_treatment omitted entirely, so the default must be applied.
    accepted = disposition_trade_in(trade_in["id"], "ACCEPT", ownership_treatment=None)

    # Priced at B: base 120000 * 2400bp = 28800, mail-in 2880, loyalty 1440.
    assert accepted["appraised_credit_minor"] == 33120

    unit = unit_of_trade_in(trade_in["id"])
    assert_resale_unit(unit)
    assert unit["trade_in_id"] == trade_in["id"]
    assert unit["product_category"] == "FOOTWEAR"
    assert unit["condition_grade"] == "B"
    assert unit["reference_msrp_minor"] == 120000
    assert unit["mass_grams"] == 900
    assert unit["ownership_treatment"] == "OWNED_INVENTORY"
    assert unit["lifecycle_state"] == "INTAKE"
    assert unit["accounting_state"] == "UNCAPITALIZED"
    assert unit["capitalized_cost_minor"] == 0
    assert_null(unit["list_price_minor"], "list_price_minor")
    assert_null(unit["current_price_minor"], "current_price_minor")
    assert_null(unit["listed_at"], "listed_at")
    assert_null(unit["listed_channel_id"], "listed_channel_id")
    assert_null(unit["replacement_for_unit_id"], "replacement_for_unit_id")
    assert unit["markdown_step_count"] == 0
    assert unit["aged_days"] == 0

    # The mass landed in the diverted bucket, and the credit chain still ran.
    after = fetch_customer(customer["id"])
    assert after["diverted_grams_total"] == 900
    assert after["credit_balance_minor"] == 33120


def test_the_rejection_branch_shares_no_side_effect_with_acceptance():
    """Two identical twins fork, and the rejected one writes nothing outward.

    PRD §3.4: "The two branches have deliberately **disjoint** side-effect sets,
    and neither leaks into the other."
    PRD §3.4: "**Rejecting** is the disjoint branch. The trade-in moves to
    `REJECTED`, `reject_reason` is written from the request body,
    `appraised_credit_minor` is zeroed out — the provisional quote is explicitly
    withdrawn rather than left standing — and the version is bumped."
    PRD §3.4: "Nothing else happens at all: no brand-currency grant is created,
    no ledger entry is appended, no resale unit is created, and the
    participant's `credit_balance_minor`, `diverted_grams_total` and `version`
    are all left exactly as they were."

    Design: Corner/state_machines/reject_disposition_side_effect_set_is_disjoint_from_accept
    """
    create_grade_policy(GRADE_POLICY_FOOTWEAR_A)
    create_credit_policy(CREDIT_POLICY_CORE)
    create_store_location()
    customer = create_customer(email="ava@example.com", full_name="Ava Reyes",
                              loyalty_tier="PLUS")

    twins = []
    for _ in range(2):
        twin = create_trade_in(
            customer,
            channel="MAIL_IN",
            product_category="FOOTWEAR",
            declared_grade="A",
            msrp_minor=120000,
            item_mass_grams=900,
        )
        receive_trade_in(twin["id"])
        authenticate_trade_in(twin["id"], "GENUINE", "A")
        twins.append(twin)
    accepted_twin, rejected_twin = twins

    accepted = disposition_trade_in(accepted_twin["id"], "ACCEPT", "OWNED_INVENTORY")
    assert accepted["appraised_credit_minor"] == 48300
    before = fetch_customer(customer["id"])
    assert before["credit_balance_minor"] == 48300
    assert before["diverted_grams_total"] == 900

    rejected = disposition_trade_in(
        rejected_twin["id"],
        decision="REJECT",
        ownership_treatment=None,
        reject_reason="authenticity documentation missing",
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["appraised_credit_minor"] == 0
    assert rejected["reject_reason"] == "authenticity documentation missing"
    assert_null(rejected["accepted_at"], "accepted_at")
    assert rejected["version"] > rejected_twin["version"]

    _, grant_meta = validate_paginated(
        api_client.list_credit_grants(ADMIN, {"trade_in_id": rejected_twin["id"]})
    )
    assert_pagination_meta(grant_meta, 0)
    _, unit_meta = validate_paginated(
        api_client.list_resale_units(ADMIN, {"trade_in_id": rejected_twin["id"]})
    )
    assert_pagination_meta(unit_meta, 0)

    after = fetch_customer(customer["id"])
    assert after["credit_balance_minor"] == before["credit_balance_minor"]
    assert after["diverted_grams_total"] == before["diverted_grams_total"]
    assert after["version"] == before["version"]


def test_a_salvage_grade_acceptance_still_issues_credit_but_diverts_no_mass():
    """The unit is born salvaged, so it never enters the diverted bucket.

    PRD §3.4: "There is one twist on the parallel branch. When the
    `assessed_grade` is `SALVAGE`, the unit that was just created is moved,
    **inside the very same request**, to lifecycle state `SALVAGED` and
    accounting state `EXPENSED`."
    PRD §3.4: "It therefore never spends a moment in the diverted bucket, and
    the participant's `diverted_grams_total` does not rise by that item's mass
    even though the trade-in was accepted and the credit was issued."
    PRD §3.2: "The provisional variant contributes **no loyalty bonus at all**,
    even for a `PLUS` customer — that term is reserved for issuance."
    PRD §3.4: "the loyalty bonus is likewise computed against that same base,
    rounded down, independently of the channel bonus."

    Design: Corner/state_machines/salvage_grade_acceptance_moves_both_unit_dimensions_in_one_request
    """
    create_grade_policy(GRADE_POLICY_FOOTWEAR_SALVAGE)
    create_credit_policy(CREDIT_POLICY_CORE)
    create_store_location()
    customer = create_customer(email="ava@example.com", full_name="Ava Reyes",
                              loyalty_tier="PLUS")
    trade_in = create_trade_in(
        customer,
        channel="MAIL_IN",
        product_category="FOOTWEAR",
        declared_grade="SALVAGE",
        msrp_minor=120000,
        item_mass_grams=1400,
    )
    # Base floor(120000 * 500 / 10000) = 6000 plus a mail-in bonus of 600.
    assert trade_in["appraised_credit_minor"] == 6600

    receive_trade_in(trade_in["id"])
    authenticate_trade_in(trade_in["id"], "GENUINE", "SALVAGE")
    accepted = disposition_trade_in(trade_in["id"], "ACCEPT", "OWNED_INVENTORY")

    # Issuance adds the PLUS term floor(6000 * 500 / 10000) = 300.
    assert accepted["status"] == "ACCEPTED"
    assert accepted["appraised_credit_minor"] == 6900

    grant = grant_of_trade_in(trade_in["id"])
    assert grant["issued_amount_minor"] == 6900
    assert grant["status"] == "ISSUED"

    unit = unit_of_trade_in(trade_in["id"])
    assert unit["lifecycle_state"] == "SALVAGED"
    assert unit["accounting_state"] == "EXPENSED"
    assert unit["capitalized_cost_minor"] == 0
    assert unit["condition_grade"] == "SALVAGE"
    assert unit["mass_grams"] == 1400

    after = fetch_customer(customer["id"])
    assert after["credit_balance_minor"] == 6900
    assert after["diverted_grams_total"] == 0


def test_the_issue_ledger_row_survives_unchanged_when_a_redeem_row_is_appended():
    """Ledger rows are append-only and carry no version at all.

    PRD §2.6: "A **brand-currency ledger entry** and a **refurbishment task
    line** carry only `id` and `created_at`."
    PRD §2.6: "Neither has an `updated_at` field and neither has a `version`
    field — those two fields are absent from their representations entirely,
    because neither row is ever mutated, voided or deleted after it is written."
    PRD §3.7: "Every touched grant receives exactly one ledger entry with
    `entry_type` `REDEEM`, a negative `amount_minor` equal to the amount drawn
    from it, a `balance_after_minor` equal to that grant's `remaining_minor`
    after the draw, `occurred_at` from the logical clock, and `resale_order_id`
    set to the order that caused it."
    PRD §3.7: "The ledger entries an order produced are separately listable by
    the same three roles with an optional `entry_type` filter, `limit` and
    `offset` — a `Customer` seeing only their own, per §2.10."

    Design: Corner/entities/credit_ledger_entry_rows_are_append_only_with_no_version
    """
    estate = setup_estate()
    # Ben's mail-in acceptance mints the brand currency: base 50000 * 2000bp =
    # 10000, mail-in 1000, PLUS loyalty 500.
    buyer_side = setup_credit_source_grant(estate, loyalty_tier="PLUS")
    buyer = buyer_side["customer"]
    grant = buyer_side["grant"]
    assert grant["issued_amount_minor"] == 11500

    opening = grant_ledger_entries(grant["id"])
    assert len(opening) == 1
    issue_row = opening[0]
    assert_credit_ledger_entry(issue_row)
    assert issue_row["entry_type"] == "ISSUE"
    assert issue_row["amount_minor"] == 11500
    assert issue_row["balance_after_minor"] == 11500

    # Ava's in-store item becomes the unit on sale at 50000 * 3900bp = 19500.
    seller_side = setup_listed_unit(
        estate, email="ava@example.com", full_name="Ava Reyes", loyalty_tier="PLUS"
    )
    assert seller_side["unit"]["list_price_minor"] == 19500

    # Gross 19500 → fee 1755 at 900bp → total 21255 → cap floor(21255/2) = 10627.
    order = place_order(buyer, seller_side["channel"], seller_side["unit"], 10627)
    assert order["credit_applied_minor"] == 10627

    after = grant_ledger_entries(grant["id"])
    assert len(after) == 2
    reread_issue, redeem_row = after

    # The ISSUE row was appended to, never rewritten.
    assert reread_issue["id"] == issue_row["id"]
    assert reread_issue["entry_type"] == issue_row["entry_type"]
    assert reread_issue["amount_minor"] == issue_row["amount_minor"]
    assert reread_issue["balance_after_minor"] == issue_row["balance_after_minor"]
    assert_instant(reread_issue["occurred_at"], issue_row["occurred_at"], "occurred_at")

    assert_credit_ledger_entry(redeem_row)
    assert redeem_row["entry_type"] == "REDEEM"
    assert redeem_row["amount_minor"] == -10627
    assert redeem_row["balance_after_minor"] == 873
    assert redeem_row["resale_order_id"] == order["id"]

    # Neither row carries the optimistic-concurrency trio.
    for row in after:
        assert "version" not in row
        assert "updated_at" not in row

    filtered, filtered_meta = validate_paginated(
        api_client.list_credit_grant_ledger_entries(
            grant["id"], ADMIN, {"entry_type": "REDEEM"}
        )
    )
    assert_pagination_meta(filtered_meta, 1)
    assert filtered[0]["entry_type"] == "REDEEM"
    assert filtered[0]["id"] == redeem_row["id"]
