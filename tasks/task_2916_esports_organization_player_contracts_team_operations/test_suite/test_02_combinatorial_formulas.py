"""Formulas whose result depends on the order their steps are pinned to.

The weekly cap nests a minimum inside a conditional reserve, the prize waterfall
floors every row before handing one row the remainder, and the transfer
settlement keys the agent's tier on a figure produced two steps earlier.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    fixtures,
    make_coaching_staff_headers,
    make_finance_officer_headers,
    make_general_manager_headers,
    make_guardian_representative_headers,
    make_scout_headers,
    validate_error,
    validate_success,
)


def _minor_enrolled_full_time():
    """A 16-year-old with a 1080-minute guardian cap, full-time schooling and 5 h streaming."""
    return fixtures.setup_signed_minor(
        player_overrides={"education_enrollment_status": "ENROLLED_FULL_TIME"},
        guardian_weekly_cap_minutes=1080,
        with_team_house=True,
    )


def _book(ctx, starts_at, ends_at, block_type="INDIVIDUAL"):
    return api_client.create_practice_block(
        {
            "organization_id": ctx["org"]["id"],
            "team_house_id": ctx["house"]["id"],
            "block_type": block_type,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "participant_player_ids": [ctx["player"]["id"]],
        },
        make_coaching_staff_headers(),
    )


def test_education_reserve_decides_the_refusal_and_the_exact_cap_is_admitted():
    """At cap 480 a 181-minute booking is refused for schooling and 180 minutes fits.

    PRD: "For a minor it is the smaller of the league's `minor_max_weekly_minutes` and the
    player's `guardian_weekly_cap_minutes`, treating a null guardian cap as if it equalled the
    league ceiling, and then, only when the minor's `education_enrollment_status` is exactly
    `ENROLLED_FULL_TIME`, reduced by the league's `education_reserved_minutes`."
    PRD: "The education reservation gets its own, narrower error: when the booking fails the cap
    *with* the reservation applied but the identical request would have passed had
    `education_reserved_minutes` been zero, the reservation was decisive and the refusal is
    `ERR_EDUCATION_HOURS_RESERVED` (HTTP 422) instead; when the request would have failed even
    with no reservation at all, the plain `ERR_WEEKLY_HOUR_CAP_EXCEEDED` is reported."
    PRD: "The comparison is strictly greater-than, so committed minutes exactly equal to the cap
    are admitted and only one minute more is a violation."

    Design: Difficulty/combinatorial_formula/weekly_hour_cap_nested_min_with_minor_and_education_branches
    """
    ctx = _minor_enrolled_full_time()

    refused = _book(ctx, "2026-08-10T10:00:00Z", "2026-08-10T13:01:00Z")
    validate_error(refused, ApiErrorId.ERR_EDUCATION_HOURS_RESERVED.value, 422)

    admitted = validate_success(
        _book(ctx, "2026-08-10T10:00:00Z", "2026-08-10T13:00:00Z"), 201
    )
    assert admitted["duration_minutes"] == 180
    assert admitted["block_status"] == "SCHEDULED"


def test_minor_status_is_derived_from_the_birth_date_and_the_clock():
    """The nested cap only applies because the derivation calls this player a minor.

    PRD: "`age_years` is the number of whole years between the player's `birth_date` and the
    current instant, counting an anniversary falling exactly on the current date as reached — so a
    player whose eighteenth birthday is today has `age_years` of 18."
    PRD: "`is_minor` is true exactly when `age_years` is strictly less than the governing league's
    `minor_age_threshold_years`, which is 18 by default; the league used for that comparison is
    the league of the organization named in `current_organization_id` when the player has one, and
    otherwise the league of the organization named in the request being evaluated."

    Design: Difficulty/combinatorial_formula/weekly_hour_cap_nested_min_with_minor_and_education_branches
    """
    ctx = _minor_enrolled_full_time()

    player = validate_success(
        api_client.get_player(ctx["player"]["id"], make_scout_headers())
    )
    assert player["is_minor"] is True
    assert player["age_years"] == 16
    assert player["guardian_consent_status"] == "GRANTED"


def test_dropping_full_time_enrolment_lifts_the_reserve_for_later_bookings():
    """Only the enrolment input changes, and the same arithmetic now admits 300 minutes.

    PRD: "A part-time enrolment reserves nothing."
    PRD: "Amendments are forward-looking only: later weekly-cap arithmetic uses the new enrolment
    status and the new guardian ceiling, while blocks already on the calendar are not
    re-validated."
    PRD: "Their **streaming minutes** are added on top: for a minor who owns a contract in
    `ACTIVE` or `SUSPENDED`, the contract's `streaming_hours_per_week` multiplied by 60; for a
    player who is not a minor, or for one who owns no such contract, zero."

    Design: Difficulty/combinatorial_formula/weekly_hour_cap_nested_min_with_minor_and_education_branches
    """
    ctx = _minor_enrolled_full_time()
    validate_success(_book(ctx, "2026-08-10T10:00:00Z", "2026-08-10T13:00:00Z"), 201)

    validate_success(
        api_client.update_player(
            ctx["player"]["id"],
            {"education_enrollment_status": "NOT_ENROLLED"},
            make_guardian_representative_headers(ctx["player"]["id"]),
        )
    )

    admitted = validate_success(
        _book(ctx, "2026-08-11T10:00:00Z", "2026-08-11T15:00:00Z"), 201
    )
    assert admitted["duration_minutes"] == 300
    assert admitted["block_status"] == "SCHEDULED"


def _three_contracts_and_a_draft_distribution():
    """Weights 4000 / 4500 / 4200, one non-resident row and one minor row."""
    ctx = fixtures.setup_league_and_org()
    ctx["player_one"] = fixtures.create_player()
    ctx["player_two"] = fixtures.create_player(
        full_name="Marek Rus", birth_date="2000-03-02", region_code="CZ"
    )
    minor = fixtures.create_minor_player()
    ctx["player_three"] = fixtures.grant_guardian_consent(minor["id"])

    fixtures.set_clock("2026-08-04T00:00:00Z")
    offer_one = fixtures.create_offer(ctx["org"]["id"], ctx["player_one"]["id"])
    offer_two = fixtures.create_offer(
        ctx["org"]["id"],
        ctx["player_two"]["id"],
        base_salary_cents=10000000,
        prize_split_player_pct_bp=4500,
        streaming_hours_per_week=12,
        tax_residency_code="KR",
    )
    offer_three = fixtures.create_offer(
        ctx["org"]["id"],
        ctx["player_three"]["id"],
        base_salary_cents=4000000,
        prize_split_player_pct_bp=4200,
        streaming_hours_per_week=5,
    )
    fixtures.set_clock("2026-08-05T00:00:00Z")
    ctx["contract_one"] = fixtures.accept_offer(offer_one["id"], ctx["player_one"]["id"])
    ctx["contract_two"] = fixtures.accept_offer(offer_two["id"], ctx["player_two"]["id"])
    ctx["contract_three"] = fixtures.accept_offer(offer_three["id"], ctx["player_three"]["id"])

    fixtures.set_clock("2026-08-21T00:00:00Z")
    ctx["distribution"] = fixtures.create_distribution(ctx["org"]["id"], ctx["league"]["id"])
    return ctx


def test_prize_waterfall_totals_follow_the_six_pinned_steps():
    """Levy, house cut and player pool each consume the output of the step above.

    PRD: "Step one takes the association's cut: `association_levy_cents` is `gross_prize_cents`
    multiplied by the league's `player_association_levy_bp`, divided by 10000 and rounded half up;
    what remains after subtracting it is the distributable amount."
    PRD: "Step two takes the house's cut: `org_share_cents` is that distributable amount
    multiplied by the organization's `org_prize_share_bp`, divided by 10000 and rounded half up;
    what remains after subtracting it is the player pool."
    PRD: "Step six freezes the totals: `allocated_cents` is the sum of `gross_share_cents` across
    the rows and therefore equals the player pool exactly, `withholding_total_cents` and
    `escrow_total_cents` are the sums of the corresponding per-row deductions, and
    `unallocated_cents` is `gross_prize_cents` less `association_levy_cents` less
    `org_share_cents` less `allocated_cents`."

    Design: Difficulty/combinatorial_formula/prize_allocation_floor_per_row_then_remainder_rounding_order
    """
    ctx = _three_contracts_and_a_draft_distribution()

    calculated = validate_success(
        api_client.calculate_prize_distribution(
            ctx["distribution"]["id"], make_finance_officer_headers()
        )
    )
    assert calculated["association_levy_cents"] == 250000
    assert calculated["org_share_cents"] == 3412500
    assert calculated["allocated_cents"] == 6337500
    assert calculated["unallocated_cents"] == 0
    assert calculated["withholding_total_cents"] == 1287461
    assert calculated["escrow_total_cents"] == 209587
    assert calculated["distribution_status"] == "CALCULATED"


def test_every_row_is_floored_and_one_row_takes_the_whole_remainder():
    """Deductions are taken from each row's own post-remainder gross share.

    PRD: "Each row's floor share is the player pool multiplied by that row's weight, divided by
    the weight total, with the fraction discarded."
    PRD: "The remainder is the player pool less the sum of all those floor shares, and the entire
    remainder is handed to exactly one row: the eligible contract with the largest floor share,
    with ties broken by the earlier `created_at` of the contract."
    PRD: "Step five computes each row's deductions from that row's **own final**
    `gross_share_cents`, never from the pre-remainder floor value."
    PRD: "A row's `withholding_rate_bp` is 1500 when the contract's `tax_residency_code` equals
    the paying organization's `tax_jurisdiction_code` and 3000 when it does not; `withholding_cents`
    is `gross_share_cents` multiplied by that rate, divided by 10000 and rounded half up."

    Design: Difficulty/combinatorial_formula/prize_allocation_floor_per_row_then_remainder_rounding_order
    """
    ctx = _three_contracts_and_a_draft_distribution()
    validate_success(
        api_client.calculate_prize_distribution(
            ctx["distribution"]["id"], make_finance_officer_headers()
        )
    )

    rows = validate_success(
        api_client.list_prize_allocations(
            ctx["distribution"]["id"], make_finance_officer_headers()
        )
    )
    by_contract = {row["contract_id"]: row for row in rows}

    resident = by_contract[ctx["contract_one"]["id"]]
    assert resident["weight_bp"] == 4000
    assert resident["gross_share_cents"] == 1996062
    assert resident["withholding_rate_bp"] == 1500
    assert resident["withholding_cents"] == 299409
    assert resident["escrow_holdback_cents"] == 0
    assert resident["net_cents"] == 1696653

    remainder_row = by_contract[ctx["contract_two"]["id"]]
    assert remainder_row["weight_bp"] == 4500
    assert remainder_row["gross_share_cents"] == 2245572
    assert remainder_row["withholding_rate_bp"] == 3000
    assert remainder_row["withholding_cents"] == 673672
    assert remainder_row["net_cents"] == 1571900

    minor_row = by_contract[ctx["contract_three"]["id"]]
    assert minor_row["weight_bp"] == 4200
    assert minor_row["gross_share_cents"] == 2095866
    assert minor_row["withholding_cents"] == 314380
    assert minor_row["escrow_holdback_cents"] == 209587
    assert minor_row["net_cents"] == 1571899


def _approved_transfer_out(fee_cents=8000000):
    """A second organization, two signed players and an APPROVED transfer of the second."""
    ctx = fixtures.setup_two_signed_players()
    ctx["destination"] = fixtures.create_organization(
        ctx["league"]["id"], name="Northline Nova", tax_jurisdiction_code="KR", org_prize_share_bp=3000
    )
    fixtures.set_clock("2026-08-20T00:00:00Z")
    ctx["move"] = fixtures.setup_approved_move(
        ctx["org"]["id"],
        ctx["player_two"]["id"],
        "TRANSFER_OUT",
        ctx["contract_two"]["id"],
        transfer_to_organization_id=ctx["destination"]["id"],
        gross_transfer_fee_cents=fee_cents,
        effective_at="2026-08-20T00:00:00Z",
    )
    return ctx


def test_transfer_settlement_keys_the_commission_tier_on_the_gross_settlement():
    """The tier is selected from the fee less the buyout credit, not from the raw fee.

    PRD: "Step three computes the `buyout_credit_cents` owed to the departing player as that
    monthly rate multiplied by the remaining whole months, multiplied by the contract's
    `buyout_multiplier_bp`, divided by 10000 and rounded half up."
    PRD: "Step five selects the agent's `commission_tier_bp` **from that gross settlement, before
    any commission is deducted**: 500 basis points when the gross settlement is strictly below
    5,000,000 cents, and 300 basis points at or above that breakpoint — the larger the deal, the
    thinner the agent's percentage."
    PRD: "Step six sets `net_to_org_cents` to the gross settlement less the agent's commission,
    and if that figure is negative the whole execution is refused with `ERR_NEGATIVE_SETTLEMENT`
    (HTTP 422) and nothing is written."
    PRD: "Step seven takes the cap relief from the contract's frozen charge:
    `released_cap_cents` is set to the contract's `provisional_cap_charge_cents`, which is what
    makes a later reversal exact."

    Design: Difficulty/combinatorial_formula/transfer_settlement_pinned_evaluation_order_with_gross_keyed_tier
    """
    ctx = _approved_transfer_out()

    executed = validate_success(
        api_client.execute_roster_move(
            ctx["move"]["id"], make_general_manager_headers(ctx["org"]["id"])
        )
    )
    assert executed["buyout_credit_cents"] == 4999998
    assert executed["commission_tier_bp"] == 500
    assert executed["agent_commission_cents"] == 150000
    assert executed["net_to_org_cents"] == 2850002
    assert executed["released_cap_cents"] == 9863014


def test_transfer_execution_moves_the_move_and_terminates_the_named_contract():
    """The settlement is written by the same request that ends the employment.

    PRD: "Step two derives the monthly rate from the base salary alone and never from any cap
    charge: `base_salary_cents` divided by 12 and rounded half up."
    PRD: "Execution of a `RELEASE` or a `TRANSFER_OUT` moves `move_status` `APPROVED` →
    `EXECUTED` and fires a **four-link cascade**."
    PRD: "First, the named contract's `contract_status` becomes `TERMINATED`, whether it was
    `ACTIVE` or `SUSPENDED` beforehand."

    Design: Difficulty/combinatorial_formula/transfer_settlement_pinned_evaluation_order_with_gross_keyed_tier
    """
    ctx = _approved_transfer_out()
    gm_headers = make_general_manager_headers(ctx["org"]["id"])

    executed = validate_success(api_client.execute_roster_move(ctx["move"]["id"], gm_headers))
    assert executed["move_status"] == "EXECUTED"

    terminated = validate_success(
        api_client.get_contract(ctx["contract_two"]["id"], gm_headers)
    )
    assert terminated["contract_status"] == "TERMINATED"

    untouched = validate_success(api_client.get_contract(ctx["contract_one"]["id"], gm_headers))
    assert untouched["contract_status"] == "ACTIVE"
