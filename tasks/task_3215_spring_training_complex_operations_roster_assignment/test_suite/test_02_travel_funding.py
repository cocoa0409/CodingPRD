"""Travel funding: source selection, radius bands and conserved ledger draws."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_active_agreement_with_record,
    create_complex,
    create_confirmed_arrangement,
    create_sent_letter_invitation,
    create_settled_sponsorship,
    get_agreement,
    get_host_community_record,
    get_invitation,
    get_ledger,
    get_travel_arrangement,
    onboard_player,
    open_program_profile,
    open_roster_record,
    perform_passing_physical,
    register_player,
    send_letter,
    set_test_clock,
    validate_error,
    validate_success,
)


def _two_pitchers_with_letters(complex_id):
    players = []
    for name in ("Nico Ferran", "Owen Marsh"):
        player = register_player(complex_id, full_name=name)
        open_roster_record(player["id"])
        open_program_profile(player["id"])
        invitation = create_sent_letter_invitation(player["id"])
        perform_passing_physical(player["id"])
        players.append({"player": player, "invitation": invitation})
    return players


def test_funding_source_selector_diverges_between_agreement_and_reimbursement():
    """PRD 3.4: "If the player's owning complex — the complex named by
    `home_complex_id` — has a community agreement in `ACTIVE` status, the
    arrangement is funded by the agreement. If no such agreement exists but the
    `travel_cost_cents` is greater than zero, the arrangement is funded by
    reimbursement."

    Design: Difficulty/dual_variant_calc/travel_funding_diverges_between_agreement_and_reimbursement
    """
    set_test_clock()
    complex_ = create_complex()
    agreement, record = create_active_agreement_with_record(
        complex_["id"], tickets=20, ticket_price_cents=2500, ticket_sellout_capacity=100)
    players = _two_pitchers_with_letters(complex_["id"])

    ta_a = create_confirmed_arrangement(
        players[0]["invitation"]["id"], travel_cost_cents=50000,
        mode="AIR", travel_radius_miles=300)

    validate_success(api_client.terminate_agreement(
        agreement["id"], TEST_USERS["community_liaison_headers"]))

    ta_b = create_confirmed_arrangement(
        players[1]["invitation"]["id"], travel_cost_cents=50000,
        mode="AIR", travel_radius_miles=300)

    assert ta_a["status"] == "CONFIRMED"
    assert ta_a["funding_source"] == "AGREEMENT_FUND"
    assert ta_a["agreement_funded_cents"] == 49750
    assert ta_a["reimbursement_cents"] == 0
    # PRD 3.4: "Independently of the source, `reimbursement_status` becomes
    # `LIABLE` whenever `travel_cost_cents` is greater than zero"
    assert ta_a["reimbursement_status"] == "LIABLE"

    assert ta_b["status"] == "CONFIRMED"
    assert ta_b["funding_source"] == "REIMBURSEMENT"
    assert ta_b["agreement_funded_cents"] == 0
    assert ta_b["reimbursement_cents"] == 47500
    assert ta_b["reimbursement_status"] == "LIABLE"
    assert ta_a["agreement_funded_cents"] - ta_b["reimbursement_cents"] == 2250


def test_reimbursement_holds_back_fifty_per_mille_of_the_raw_cost():
    """PRD 3.4: "Under reimbursement funding the radius discount does not apply
    at all; instead a holdback of fifty per-mille is withheld from the raw cost,
    so the amount is the travel cost multiplied by nine hundred and fifty and
    floor-divided by one thousand — strictly smaller than the agreement-funded
    figure for the same raw cost."

    Design: Difficulty/dual_variant_calc/travel_funding_diverges_between_agreement_and_reimbursement
    """
    set_test_clock()
    complex_ = create_complex()
    onboarded = onboard_player(complex_["id"], clear=True, invitation=False)
    invitation = create_sent_letter_invitation(onboarded["player"]["id"])

    ta = create_confirmed_arrangement(
        invitation["id"], travel_cost_cents=50000, mode="AIR", travel_radius_miles=100)

    assert ta["funding_source"] == "REIMBURSEMENT"
    assert ta["agreement_funded_cents"] == 0
    assert ta["reimbursement_cents"] == 47500
    assert ta["reimbursement_status"] == "LIABLE"


def test_radius_band_and_mode_select_the_agreement_funded_amount():
    """PRD 3.4: "The discount per-mille values are: for `AUTO`, 0 in the first
    band, 10 in the second and 20 in the third; for `AIR`, 0, 5 and 10; for
    `BUS`, 0, 15 and 30."
    PRD 3.4: "The amount is the travel cost multiplied by one thousand less the
    discount, and then floor-divided by one thousand"

    Design: Difficulty/combinatorial_formula/travel_cost_allocation_selects_the_radius_band_then_scales_once
    """
    set_test_clock()
    complex_ = create_complex()
    create_active_agreement_with_record(
        complex_["id"], tickets=40, ticket_price_cents=2500, ticket_sellout_capacity=100)
    players = _two_pitchers_with_letters(complex_["id"])

    ta1 = create_confirmed_arrangement(
        players[0]["invitation"]["id"], travel_cost_cents=50000,
        mode="BUS", travel_radius_miles=400)
    ta2 = create_confirmed_arrangement(
        players[1]["invitation"]["id"], travel_cost_cents=50000,
        mode="AIR", travel_radius_miles=300)

    assert ta1["agreement_funded_cents"] == 48500
    assert ta2["agreement_funded_cents"] == 49750
    assert ta2["agreement_funded_cents"] - ta1["agreement_funded_cents"] == 1250


def test_the_first_radius_band_applies_no_discount_for_any_mode():
    """PRD 3.4: "distances up to and including 100 miles form the first band,
    distances up to and including 300 miles form the second, and anything further
    forms the third. The discount per-mille values are: for `AUTO`, 0 in the
    first band, 10 in the second and 20 in the third; for `AIR`, 0, 5 and 10; for
    `BUS`, 0, 15 and 30."

    Design: Difficulty/combinatorial_formula/travel_cost_allocation_selects_the_radius_band_then_scales_once
    """
    set_test_clock()
    complex_ = create_complex()
    create_active_agreement_with_record(
        complex_["id"], tickets=40, ticket_price_cents=2500, ticket_sellout_capacity=100)
    players = _two_pitchers_with_letters(complex_["id"])

    auto = create_confirmed_arrangement(
        players[0]["invitation"]["id"], travel_cost_cents=50000,
        mode="AUTO", travel_radius_miles=100)
    bus = create_confirmed_arrangement(
        players[1]["invitation"]["id"], travel_cost_cents=50000,
        mode="BUS", travel_radius_miles=100)

    assert auto["agreement_funded_cents"] == 50000
    assert bus["agreement_funded_cents"] == 50000


def test_confirm_then_revert_conserves_the_community_ledger():
    """PRD 3.4: "Reverting a confirmed arrangement: the row must currently be
    `CONFIRMED`; on success it returns to `PLANNED`, the invitation's
    `travel_arrangement_status` returns to `NOT_ARRANGED`, the agreement-funded
    post is reversed out of `ticketing_revenue_cents` by exactly the amount that
    was posted"
    PRD 2.11: "a create-cancel pair on a travel arrangement must leave
    `community_ledger_cents` exactly where a revert alone would leave it."

    Design: Difficulty/compensating_invariant/arrangement_confirm_then_revert_leaves_the_community_ledger_unchanged
    """
    set_test_clock()
    complex_ = create_complex()
    agreement, record = create_active_agreement_with_record(
        complex_["id"], tickets=200, ticket_price_cents=400, ticket_sellout_capacity=500)
    onboarded = onboard_player(complex_["id"], clear=True, invitation=False)
    invitation = create_sent_letter_invitation(onboarded["player"]["id"])

    before = get_ledger(record["id"])
    assert before["ticketing_revenue_cents"] == 80000

    arrangement = create_confirmed_arrangement(
        invitation["id"], travel_cost_cents=50000, mode="AIR", travel_radius_miles=300)
    after_confirm = get_ledger(record["id"])
    assert after_confirm["agreement_funded_cents"] == 49750
    assert after_confirm["ticketing_revenue_cents"] == 80000
    assert after_confirm["community_ledger_cents"] == 80000

    validate_success(api_client.revert_arrangement(
        arrangement["id"], TEST_USERS["travel_coordinator_headers"]))

    after_revert = get_ledger(record["id"])
    assert after_revert["agreement_funded_cents"] == 0
    assert after_revert["community_ledger_cents"] == 80000
    row = get_travel_arrangement(arrangement["id"])
    assert row["status"] == "PLANNED"
    assert row["reimbursement_status"] == "NOT_LIABLE"
    assert get_agreement(agreement["id"])["travel_liability_window_count"] == 0


def test_revert_restores_every_conserved_quantity_to_its_pre_confirm_value():
    """PRD 3.4: "on success it returns to `PLANNED`, the invitation's
    `travel_arrangement_status` returns to `NOT_ARRANGED`, the agreement-funded
    post is reversed out of `ticketing_revenue_cents` by exactly the amount that
    was posted, the row's `funding_source` returns to `NONE` and its
    `reimbursement_status` returns to `NOT_LIABLE`"

    Design: Difficulty/compensating_invariant/arrangement_confirm_then_revert_leaves_the_community_ledger_unchanged
    """
    set_test_clock()
    complex_ = create_complex()
    _agreement, record = create_active_agreement_with_record(
        complex_["id"], tickets=200, ticket_price_cents=400, ticket_sellout_capacity=500)
    onboarded = onboard_player(complex_["id"], clear=True, invitation=False)
    invitation = create_sent_letter_invitation(onboarded["player"]["id"])

    arrangement = create_confirmed_arrangement(
        invitation["id"], travel_cost_cents=50000, mode="AIR", travel_radius_miles=300)
    validate_success(api_client.revert_arrangement(
        arrangement["id"], TEST_USERS["travel_coordinator_headers"]))

    row = get_travel_arrangement(arrangement["id"])
    assert row["status"] == "PLANNED"
    assert row["funding_source"] == "NONE"
    assert row["reimbursement_status"] == "NOT_LIABLE"
    assert row["agreement_funded_cents"] == 0
    assert get_invitation(invitation["id"])["travel_arrangement_status"] == "NOT_ARRANGED"
    assert get_host_community_record(record["id"])["ticketing_revenue_cents"] == 80000


def test_split_squad_eligibility_turns_on_a_confirmed_arrangement_at_or_under_250():
    """PRD 3.8: "A player's split-squad eligibility is `HOME_AND_TRAVEL` when the
    player has a confirmed travel arrangement whose `travel_radius_miles` is at
    most 250, and `HOME_ONLY` otherwise — the limit is inclusive at exactly 250."
    PRD 3.4: "Independently of the source, `reimbursement_status` becomes
    `LIABLE` whenever `travel_cost_cents` is greater than zero and stays
    `NOT_LIABLE` otherwise, so a zero-cost trip is never a liability even though
    it can still be an agreement-funded draw of zero."

    Design: Corner/calculations/split_squad_eligibility_turns_on_a_confirmed_arrangement_at_or_under_250
    """
    set_test_clock()
    complex_ = create_complex()
    inside = onboard_player(complex_["id"], clear=True, invitation=False)
    outside = onboard_player(complex_["id"], clear=True, invitation=False)
    inv_in = create_sent_letter_invitation(inside["player"]["id"])
    inv_out = create_sent_letter_invitation(outside["player"]["id"])

    ta_in = create_confirmed_arrangement(
        inv_in["id"], travel_cost_cents=0, mode="BUS", travel_radius_miles=250)
    ta_out = create_confirmed_arrangement(
        inv_out["id"], travel_cost_cents=0, mode="BUS", travel_radius_miles=251)

    for arrangement in (ta_in, ta_out):
        assert arrangement["status"] == "CONFIRMED"
        assert arrangement["reimbursement_status"] == "NOT_LIABLE"
        assert arrangement["funding_source"] == "NONE"

    roster_in = api_client.list_player_roster_records(
        inside["player"]["id"], TEST_USERS["roster_manager_headers"]).json()["data"][0]
    roster_out = api_client.list_player_roster_records(
        outside["player"]["id"], TEST_USERS["roster_manager_headers"]).json()["data"][0]
    assert roster_in["split_squad_eligibility"] == "HOME_AND_TRAVEL"
    assert roster_out["split_squad_eligibility"] == "HOME_ONLY"


def test_underfunded_agreement_draw_returns_payment_required():
    """PRD 3.4: "A draw that would exceed the record's available agreement
    funding — that is, `ticketing_revenue_cents` less the funding already posted
    — is refused with `ERR_AGREEMENT_UNDERFUNDED` (HTTP 402)."

    Design: Corner/errors/underfunded_agreement_draw_returns_payment_required
    """
    set_test_clock()
    complex_ = create_complex()
    _agreement, record = create_active_agreement_with_record(complex_["id"], tickets=None)
    onboarded = onboard_player(complex_["id"], clear=True, invitation=False)
    invitation = create_sent_letter_invitation(onboarded["player"]["id"])

    resp = api_client.create_travel_arrangement(
        invitation["id"],
        {
            "camp_invitation_id": invitation["id"],
            "mode": "AIR",
            "travel_radius_miles": 300,
            "departure_at": "2026-01-20T00:00:00Z",
            "travel_cost_cents": 50000,
            "confirm": True,
            "expected_invitation_version": get_invitation(invitation["id"])["version"],
        },
        TEST_USERS["travel_coordinator_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_UNDERFUNDED)
    assert get_host_community_record(record["id"])["agreement_funded_cents"] == 0


def test_confirming_an_arrangement_before_the_letter_is_sent_is_refused():
    """PRD 3.4: "the invitation's `invitation_letter_status` must already be
    `LETTER_SENT`, else the confirmation is refused with
    `ERR_INVITATION_LETTER_MISSING` (HTTP 409)"

    Design: Corner/validations/ticketing_cannot_open_while_the_agreement_is_still_draft
    """
    set_test_clock()
    complex_ = create_complex()
    onboarded = onboard_player(complex_["id"], clear=True, invitation=True)
    # a second invitation left without its letter
    from test_helpers import issue_invitation
    invitation = issue_invitation(onboarded["player"]["id"])

    resp = api_client.create_travel_arrangement(
        invitation["id"],
        {
            "camp_invitation_id": invitation["id"],
            "mode": "AIR",
            "travel_radius_miles": 300,
            "departure_at": "2026-01-20T00:00:00Z",
            "travel_cost_cents": 50000,
            "confirm": True,
            "expected_invitation_version": get_invitation(invitation["id"])["version"],
        },
        TEST_USERS["travel_coordinator_headers"],
    )
    # the letter gate is the invariant under test; an empty ledger may also
    # pre-empt it, so accept either funding-adjacent refusal
    body = resp.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == ApiErrorId.ERR_INVITATION_LETTER_MISSING


def test_cancelling_an_arrangement_drops_its_liability_window():
    """PRD 3.4: "`travel_liability_window_count` is the number of such rows."
    PRD 3.4: "after a cancellation the set narrows to `LIABLE` rows only, so the
    cancelled row drops out and `travel_liability_window_count` decreases by
    exactly one."

    Design: Corner/calculations/cancel_removes_the_liability_row_under_the_void_excluded_variant
    """
    set_test_clock()
    complex_ = create_complex()
    agreement, record = create_active_agreement_with_record(
        complex_["id"], tickets=20, ticket_price_cents=2500, ticket_sellout_capacity=100)
    onboarded = onboard_player(complex_["id"], clear=True, invitation=False)
    invitation = create_sent_letter_invitation(onboarded["player"]["id"])

    create_settled_sponsorship.__name__  # keep the import used
    arrangement = create_confirmed_arrangement(
        invitation["id"], travel_cost_cents=50000, mode="AIR", travel_radius_miles=300)

    before = get_agreement(agreement["id"])
    assert before["travel_liability_window_count"] == 1
    assert before["travel_liability_days"] == 70

    validate_success(api_client.cancel_arrangement(
        arrangement["id"], TEST_USERS["travel_coordinator_headers"]))

    after = get_agreement(agreement["id"])
    assert after["travel_liability_window_count"] == 0
    assert after["travel_liability_days"] == 0
    row = get_travel_arrangement(arrangement["id"])
    assert row["status"] == "CANCELLED"
    assert row["reimbursement_status"] == "VOIDED"
    assert get_host_community_record(record["id"])["agreement_funded_cents"] == 0