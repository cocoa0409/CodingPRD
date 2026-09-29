"""Pledge gates, the member tier price and the committed-spend ledger."""

from test_helpers import (
    assert_commitment,
    assert_member_standing_consistent,
    commitment_payload,
    create_draft_trial,
    create_member,
    create_negotiation,
    create_product,
    create_vendor,
    endorse_trial,
    make_librarian_headers,
    pledge,
    read_commitment,
    read_member,
    read_subscription,
    setup_catalog,
    setup_members,
    setup_multi_member_subscription,
    sign,
    submit_round,
    validate_error,
    validate_paginated,
    validate_success,
    vendor_accepts,
    withdraw,
)


def test_second_pledge_on_the_same_product_is_rejected(api, admin):
    """A member library may hold only one live pledge per package.

    PRD: "A member may hold only one live pledge per package, so if a commitment
    row already exists on the same product and member pair with `status` of
    `PLEDGED` or `CONFIRMED`, the request is refused with
    `ERR_DUPLICATE_COMMITMENT` (409) — rows already `WITHDRAWN` or `RELEASED` do
    not block a fresh pledge."

    Design: Corner/validations/second_pledge_on_the_same_product_is_rejected
    """
    scenario = setup_catalog()
    product_id = scenario["product"]["id"]
    member_id = scenario["member"]["id"]
    first = pledge(product_id, member_id)
    assert first["projected_price_cents"] == 4500000

    response = api.create_commitment(product_id, commitment_payload(member_id),
                                     make_librarian_headers(member_id))
    validate_error(response, "ERR_DUPLICATE_COMMITMENT", 409)

    _, meta = validate_paginated(api.list_commitments(admin, {"product_id": product_id}))
    assert meta["total_count"] == 1, "the refused pledge created no second row"

    stored = read_commitment(first["id"])
    assert stored["projected_price_cents"] == 4500000, "the first price is untouched"
    assert stored["participant_count_at_pricing"] == 1, (
        "the refused pledge did not inflate the participant count"
    )


def test_withdrawing_an_already_withdrawn_commitment_is_rejected(api):
    """Withdrawal is not repeatable, so the ledger cannot be decremented twice.

    PRD: "Rows already `WITHDRAWN` or `RELEASED` cannot be withdrawn again."

    Design: Corner/errors/withdrawing_an_already_withdrawn_commitment_is_rejected
    """
    scenario = setup_catalog()
    member_id = scenario["member"]["id"]
    commitment = pledge(scenario["product"]["id"], member_id)
    withdraw(commitment["id"], member_id)

    response = api.withdraw_commitment(commitment["id"], make_librarian_headers(member_id))
    validate_error(response, "ERR_COMMITMENT_INVALID_STATE", 409)

    assert read_commitment(commitment["id"])["status"] == "WITHDRAWN"
    member = read_member(member_id)
    assert member["annual_committed_cents"] == 0, "no second decrement occurred"
    assert member["standing"] == "IN_GOOD_STANDING"
    assert_member_standing_consistent(member)


def test_pledge_above_the_budget_ceiling_is_rejected(api, admin):
    """The fiscal gate alone refuses a projection the ceiling cannot hold.

    PRD: "And a pledge must fit the budget: the member's current
    `annual_committed_cents` plus the projected price of the new pledge must be
    less than or equal to `budget_ceiling_cents`, otherwise
    `ERR_BUDGET_CEILING_EXCEEDED` (409)."

    Design: Corner/errors/pledge_above_the_budget_ceiling_is_rejected
    """
    scenario = setup_catalog(member_overrides={"budget_ceiling_cents": 4000000})
    member_id = scenario["member"]["id"]

    response = api.create_commitment(scenario["product"]["id"],
                                     commitment_payload(member_id),
                                     make_librarian_headers(member_id))
    validate_error(response, "ERR_BUDGET_CEILING_EXCEEDED", 409)

    member = read_member(member_id)
    assert member["standing"] == "IN_GOOD_STANDING", "the state gate was never violated"
    assert member["annual_committed_cents"] == 0
    _, meta = validate_paginated(api.list_commitments(admin, {"member_id": member_id}))
    assert meta["total_count"] == 0, "the refused pledge stored nothing"


def test_pledge_participant_count_excludes_withdrawn_commitments(api):
    """Only live rows count towards the band, and earlier rows are never re-priced.

    PRD: "Its participant count is the number of commitment rows on the product
    whose `status` is `PLEDGED` or `CONFIRMED`, **including the row being
    created**."

    PRD: "A pledge that is still `PLEDGED` simply moves `PLEDGED → WITHDRAWN` with
    no financial consequence, since it never entered the ledger."

    Design: Corner/calculations/pledge_participant_count_excludes_withdrawn_commitments
    """
    vendor = create_vendor()
    product = create_product(vendor["id"])
    alpha, bravo, charlie, delta = setup_members([
        {"name": "Alpha College"}, {"name": "Bravo University"},
        {"name": "Charlie Institute"}, {"name": "Delta Academy"},
    ])
    commitment_alpha = pledge(product["id"], alpha["id"])
    commitment_bravo = pledge(product["id"], bravo["id"])
    commitment_charlie = pledge(product["id"], charlie["id"])
    assert commitment_charlie["projected_price_cents"] == 4050000
    withdraw(commitment_charlie["id"], charlie["id"])

    response = api.create_commitment(product["id"], commitment_payload(delta["id"]),
                                     make_librarian_headers(delta["id"]))
    data = validate_success(response, expected_status=201)

    assert_commitment(data)
    assert data["participant_count_at_pricing"] == 3, (
        "Alpha, Bravo and Delta itself are live; Charlie's withdrawn row is not"
    )
    assert float(data["applied_discount_pct"]) == 10
    assert data["projected_price_cents"] == 4050000

    assert read_commitment(commitment_charlie["id"])["status"] == "WITHDRAWN"
    first = read_commitment(commitment_alpha["id"])
    assert first["projected_price_cents"] == 4500000, "an earlier row is never re-priced"
    assert first["participant_count_at_pricing"] == 1
    assert read_commitment(commitment_bravo["id"])["projected_price_cents"] == 4500000


def test_member_price_rounds_half_up_to_the_nearest_cent(api):
    """A gross of 449,999.55 cents rounds up to a whole cent rather than truncating.

    PRD: "Round the gross amount half up to whole cents, take the smaller of that
    rounded gross and the rounded ceiling, and then take the larger of the result
    and the consortium's floor of 150,000 cents (fifteen hundred dollars)."

    PRD: "Compute the gross amount: the product's `base_list_price_cents`,
    multiplied by the size factor, multiplied by the classification factor,
    multiplied by one minus the selected band's `discount_pct` divided by 100."

    Design: Corner/calculations/member_price_rounds_half_up_to_the_nearest_cent
    """
    vendor = create_vendor()
    product = create_product(vendor["id"], base_list_price_cents=999999,
                             tier_bands=[{"min_participants": 1, "discount_pct": 0}])
    member = create_member(name="Alpha College", fte_count=4000,
                           carnegie_class="BACCALAUREATE", budget_ceiling_cents=9000000)

    response = api.create_commitment(product["id"], commitment_payload(member["id"]),
                                     make_librarian_headers(member["id"]))
    data = validate_success(response, expected_status=201)

    assert_commitment(data)
    assert data["projected_price_cents"] == 450000, (
        "999,999 x 0.60 x 0.75 is 449,999.55, which rounds half up to 450,000"
    )
    assert isinstance(data["projected_price_cents"], int)
    assert float(data["applied_discount_pct"]) == 0
    assert data["participant_count_at_pricing"] == 1
    assert data["status"] == "PLEDGED"
    assert read_member(member["id"])["annual_committed_cents"] == 0, (
        "a pledge never enters the ledger"
    )

def _two_clamped_pledges():
    """Two members, two packages, one pledge each — one clamped down, one up.

    Metro University is large enough that its gross exceeds the fairness ceiling
    of the expensive package; Tiny Seminary is small enough that its gross falls
    under the consortium floor on the cheap package.  Separate packages keep both
    participant counts at 1, so the discount band is the same in both cases.
    """
    vendor = create_vendor()
    expensive = create_product(vendor["id"], name="Atlas Humanities Collection",
                               base_list_price_cents=10000000)
    cheap = create_product(vendor["id"], name="Atlas Pastoral Studies",
                           base_list_price_cents=200000,
                           tier_bands=[{"min_participants": 1, "discount_pct": 0}])
    metro = create_member(name="Metro University", fte_count=15000,
                          carnegie_class="BACCALAUREATE", budget_ceiling_cents=9000000)
    tiny = create_member(name="Tiny Seminary", fte_count=3000,
                         carnegie_class="BACCALAUREATE", budget_ceiling_cents=500000)
    return {
        "expensive": expensive,
        "cheap": cheap,
        "metro": metro,
        "tiny": tiny,
        "metro_commitment": pledge(expensive["id"], metro["id"]),
        "tiny_commitment": pledge(cheap["id"], tiny["id"]),
    }


def test_the_larger_member_is_clamped_down_to_the_fairness_ceiling(api):
    """A gross of 6,375,000 is cut to the package's sixty-percent ceiling.

    PRD: "Compute the fairness ceiling: the product's `base_list_price_cents`
    multiplied by 60 and divided by 100 — that is, no single member ever pays
    more than sixty percent of the whole package's list price — rounded half up
    to whole cents."

    PRD: "Determine the size factor from the member's `fte_count`: a population
    below 5,000 gives a factor of 0.60; a population of 5,000 or more but below
    20,000 gives 0.85; a population of 20,000 or more gives 1.15."

    Design: Difficulty/combinatorial_formula/member_price_nested_clamp_selects_ceiling_for_one_member_and_floor_for_another
    """
    scenario = _two_clamped_pledges()
    stored = read_commitment(scenario["metro_commitment"]["id"])

    assert_commitment(stored)
    assert stored["projected_price_cents"] == 6000000, (
        "10,000,000 x 0.85 x 0.75 is 6,375,000, above the 6,000,000 ceiling, so "
        "the smaller of the two is taken"
    )
    assert stored["projected_price_cents"] != 6375000, "the unclamped gross is not stored"
    assert float(stored["applied_discount_pct"]) == 0, "a lone participant earns no discount"
    assert stored["participant_count_at_pricing"] == 1
    assert stored["status"] == "PLEDGED"
    assert read_member(scenario["metro"]["id"])["annual_committed_cents"] == 0, (
        "a pledge never enters the ledger"
    )


def test_the_smaller_member_is_clamped_up_to_the_consortium_floor(api):
    """A gross of 90,000 is raised to the 150,000-cent floor by the outer clamp.

    PRD: "Round the gross amount half up to whole cents, take the smaller of that
    rounded gross and the rounded ceiling, and then take the larger of the result
    and the consortium's floor of 150,000 cents (fifteen hundred dollars)."

    PRD: "Both roundings happen **before** the clamping; the clamp is never
    applied to an unrounded figure and no rounding is applied after it."

    Design: Difficulty/combinatorial_formula/member_price_nested_clamp_selects_ceiling_for_one_member_and_floor_for_another
    """
    scenario = _two_clamped_pledges()
    stored = read_commitment(scenario["tiny_commitment"]["id"])

    assert_commitment(stored)
    assert stored["projected_price_cents"] == 150000, (
        "200,000 x 0.60 x 0.75 is 90,000; the inner ceiling of 120,000 does not "
        "bind, and the outer floor of 150,000 does"
    )
    assert stored["projected_price_cents"] != 90000, "the gross is below the floor"
    assert stored["projected_price_cents"] != 120000, (
        "the ceiling is the smaller of the pair, so it never becomes the answer here"
    )
    assert float(stored["applied_discount_pct"]) == 0
    assert stored["participant_count_at_pricing"] == 1

    other = read_commitment(scenario["metro_commitment"]["id"])
    assert other["projected_price_cents"] == 6000000, (
        "the same formula picked the opposite clamp for the other member"
    )
    assert read_member(scenario["tiny"]["id"])["annual_committed_cents"] == 0


def _over_committed_xavier():
    """A member whose settled price overshoots the projection that cleared its ceiling.

    Xavier's ceiling of 4,100,000 admits the 4,050,000 projection it is quoted as
    the third pledger.  Its two co-pledgers then withdraw, so the signature
    settles Xavier alone at 4,500,000 and the ledger overshoots the ceiling.
    """
    vendor = create_vendor()
    first = create_product(vendor["id"], name="Atlas Humanities Collection")
    second = create_product(vendor["id"], name="Atlas Social Sciences")
    xavier = create_member(name="Xavier College", budget_ceiling_cents=4100000)
    yankee = create_member(name="Yankee University")
    zulu = create_member(name="Zulu Institute")

    trial = create_draft_trial(first["id"], xavier["id"])
    endorse_trial(trial["id"], xavier["id"])
    negotiation = create_negotiation(first["id"], trial["id"])
    submit_round(negotiation["id"])
    vendor_accepts(negotiation["id"], vendor["id"], 9000000)

    yankee_commitment = pledge(first["id"], yankee["id"])
    zulu_commitment = pledge(first["id"], zulu["id"])
    xavier_commitment = pledge(first["id"], xavier["id"])
    assert xavier_commitment["projected_price_cents"] == 4050000, (
        "the third pledger is quoted the ten-percent band, inside its ceiling"
    )
    withdraw(yankee_commitment["id"], yankee["id"])
    withdraw(zulu_commitment["id"], zulu["id"])

    return {
        "vendor": vendor,
        "first": first,
        "second": second,
        "xavier": xavier,
        "commitment": xavier_commitment,
        "subscription": sign(negotiation["id"]),
    }


def test_over_committed_member_pledging_reports_standing_not_the_budget(api, admin):
    """Two gates fail at once and the earlier standing gate decides the answer.

    PRD: "The system evaluates in the following strict priority order, and
    returns on the first failure:"

    PRD: "The acting member's `standing` is `IN_GOOD_STANDING` — otherwise
    `ERR_MEMBER_OVER_COMMITTED` (409). Applies to exactly three operations:
    pledging participation in a product, setting up a trial on a product, and
    opening a `DRAFT` trial."

    PRD: "The consequence worth internalising is that structural failures always
    mask business failures, and that within the business band the ordering above
    is authoritative."

    Design: Difficulty/priority_pair_validation_conflict/pledge_by_over_committed_member_reports_standing_before_budget_ceiling
    """
    scenario = _over_committed_xavier()
    xavier_id = scenario["xavier"]["id"]

    response = api.create_commitment(scenario["second"]["id"],
                                     commitment_payload(xavier_id),
                                     make_librarian_headers(xavier_id))
    error = validate_error(response, "ERR_MEMBER_OVER_COMMITTED", 409)
    assert error["error_id"] != "ERR_BUDGET_CEILING_EXCEEDED", (
        "standing sits at priority 9 and the budget ceiling at priority 32"
    )

    member = read_member(xavier_id)
    assert member["standing"] == "OVER_COMMITTED"
    assert member["annual_committed_cents"] == 4500000, (
        "the signature settled Xavier alone, above the 4,100,000 ceiling"
    )
    assert_member_standing_consistent(member)

    _, meta = validate_paginated(
        api.list_commitments(admin, {"product_id": scenario["second"]["id"]})
    )
    assert meta["total_count"] == 0, "the refused pledge stored no row on the second package"


def test_restoring_standing_lets_the_budget_gate_decide_the_same_pledge(api, admin):
    """Once standing is repaired the identical request reports the fiscal code.

    PRD: "A member is `IN_GOOD_STANDING` while `annual_committed_cents` is less
    than or equal to `budget_ceiling_cents`, and becomes `OVER_COMMITTED` the
    moment `annual_committed_cents` exceeds `budget_ceiling_cents`."

    PRD: "And a pledge must fit the budget: the member's current
    `annual_committed_cents` plus the projected price of the new pledge must be
    less than or equal to `budget_ceiling_cents`, otherwise
    `ERR_BUDGET_CEILING_EXCEEDED` (409)."

    Design: Difficulty/priority_pair_validation_conflict/pledge_by_over_committed_member_reports_standing_before_budget_ceiling
    """
    scenario = _over_committed_xavier()
    xavier_id = scenario["xavier"]["id"]
    payload = commitment_payload(xavier_id)
    headers = make_librarian_headers(xavier_id)

    validate_error(api.create_commitment(scenario["second"]["id"], payload, headers),
                   "ERR_MEMBER_OVER_COMMITTED", 409)

    withdraw(scenario["commitment"]["id"], xavier_id)
    member = read_member(xavier_id)
    assert member["annual_committed_cents"] == 0
    assert member["standing"] == "IN_GOOD_STANDING", "the compensating action repaired standing"

    response = api.create_commitment(scenario["second"]["id"], payload, headers)
    validate_error(response, "ERR_BUDGET_CEILING_EXCEEDED", 409)

    _, meta = validate_paginated(
        api.list_commitments(admin, {"product_id": scenario["second"]["id"]})
    )
    assert meta["total_count"] == 0, "a 4,500,000 projection still does not fit 4,100,000"
    assert read_member(xavier_id)["standing"] == "IN_GOOD_STANDING", (
        "the fiscal refusal does not change standing"
    )


def test_withdrawing_a_confirmed_pledge_reverses_the_exact_settled_amount(api):
    """The withdrawal decrements by precisely the settled price and clears it.

    PRD: "That withdrawal is the exact compensating action of the confirmation:
    it decreases the owning member's `annual_committed_cents` by precisely the
    `tier_price_cents` the confirmation added, re-derives `standing` — restoring
    `IN_GOOD_STANDING` if the ledger now sits at or below `budget_ceiling_cents`
    — and then clears `tier_price_cents` back to null."

    Design: Difficulty/compensating_invariant/withdrawing_a_confirmed_pledge_restores_the_member_ledger_identity
    """
    scenario = setup_multi_member_subscription([
        {"name": "Alpha College"}, {"name": "Bravo University"},
        {"name": "Charlie Institute"},
    ])
    charlie = scenario["members"][2]
    charlie_commitment = scenario["commitments"][2]
    assert read_commitment(charlie_commitment["id"])["tier_price_cents"] == 4050000
    assert read_member(charlie["id"])["annual_committed_cents"] == 4050000

    response = api.withdraw_commitment(charlie_commitment["id"],
                                       make_librarian_headers(charlie["id"]))
    data = validate_success(response)

    assert_commitment(data)
    assert data["status"] == "WITHDRAWN"
    assert data["tier_price_cents"] is None, "the settled price is cleared back to null"
    assert data["projected_price_cents"] == 4050000, (
        "the projection is a historical fact and is not cleared"
    )

    member = read_member(charlie["id"])
    assert member["annual_committed_cents"] == 0, "the decrement is exactly 4,050,000"
    assert member["standing"] == "IN_GOOD_STANDING"
    assert_member_standing_consistent(member)


def test_the_ledger_identity_survives_the_withdrawal_across_all_members(api, admin):
    """Committed spend equals the sum of confirmed settled prices before and after.

    PRD: "A commitment that has already been `CONFIRMED` moves `CONFIRMED →
    WITHDRAWN` only while its subscription's `contract_status` is
    `PENDING_ACTIVATION` or `ACTIVE`; on any other contract state the request is
    `ERR_COMMITMENT_INVALID_STATE` (409)."

    PRD: "The **settled** variant runs when a signature confirms the pledges, and
    again on renewal execution, restructure execution and restructure reversal;
    its result is stamped as `tier_price_cents`."

    Design: Difficulty/compensating_invariant/withdrawing_a_confirmed_pledge_restores_the_member_ledger_identity
    """
    scenario = setup_multi_member_subscription([
        {"name": "Alpha College"}, {"name": "Bravo University"},
        {"name": "Charlie Institute"},
    ])
    alpha, bravo, charlie = scenario["members"]
    subscription_id = scenario["subscription"]["id"]
    assert read_subscription(subscription_id)["contract_status"] == "PENDING_ACTIVATION"

    ledger_before = sum(read_member(m["id"])["annual_committed_cents"]
                        for m in (alpha, bravo, charlie))
    assert ledger_before == 12150000, "three members settled at 4,050,000 each"

    withdraw(scenario["commitments"][2]["id"], charlie["id"])

    ledger_after = sum(read_member(m["id"])["annual_committed_cents"]
                       for m in (alpha, bravo, charlie))
    rows, meta = validate_paginated(
        api.list_commitments(admin, {"subscription_id": subscription_id,
                                     "status": "CONFIRMED"})
    )
    assert meta["total_count"] == 2, "only Alpha and Bravo remain confirmed"
    assert sum(row["tier_price_cents"] for row in rows) == 8100000
    assert ledger_after == 8100000, "both sides of the identity moved together"

    for survivor in (alpha, bravo):
        assert read_member(survivor["id"])["annual_committed_cents"] == 4050000, (
            "a co-participant is not re-priced by somebody else's withdrawal"
        )
    assert read_subscription(subscription_id)["negotiated_price_cents"] == 9000000, (
        "the consortium's own price is untouched by a member leaving"
    )
