"""Inter-club usage settlement: the pinned waterfall, its tier floor and its reversal.

Every figure below comes from the four-step waterfall — hold, net, tier, rebate — run
over guest usage batches swept for one period and one club pair.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_settlement_ledger_conserved,
    charge_and_pay,
    create_club,
    create_franchisee,
    create_member,
    create_published_plan_template,
    create_territory,
    create_usage_settlement,
    read_club,
    read_guest_usage_event,
    read_usage_settlement,
    record_guest_usage,
    open_club,
    post_usage_settlement,
    reverse_usage_settlement,
    set_clock_date,
    setup_guest_usage_scenario,
    sign_agreement,
)

BRAND = TEST_USERS["brand_administrator_headers"]


def _eighty_four_visits_at_the_standard_guest_fee() -> dict:
    """Two batches — 50 and 34 visits — at a 1250-cent host club, swept into one
    settlement for August."""
    scenario = setup_guest_usage_scenario(
        period_visits=[("2026-08", 50), ("2026-08", 34)],
        legal_name="Twin Peaks Fitness LLC",
        contact_email="ops@twinpeaksfit.example",
        home_club_name="Home Club",
        host_club_name="Host Club",
        host_center_lat=34.5,
        host_center_lng=-118.0,
    )
    charge_and_pay(
        scenario["agreement"]["id"],
        scenario["agreement"]["effective_monthly_dues_cents"],
        occurred_on="2026-08-01",
        due_on="2026-09-05",
        paid_on="2026-08-02",
    )
    scenario["settlement"] = create_usage_settlement(
        "2026-08", scenario["home_club"]["id"], scenario["host_club"]["id"]
    )
    return scenario


def _two_settlements_around_the_tier_floor() -> dict:
    """A 647-cent host fee turns 84 visits into a net of exactly 50000 cents and 83
    visits into 49405, one on each side of the first rebate tier."""
    franchisee = create_franchisee(
        legal_name="Summit Ridge Fitness LLC", contact_email="ops@summitridgefit.example"
    )
    home_territory = create_territory(
        franchisee["id"], center_lat=34.0, center_lng=-118.0, protected_radius_km=5.0
    )
    host_territory = create_territory(
        franchisee["id"], center_lat=34.1, center_lng=-118.1, protected_radius_km=5.0
    )
    home_club = open_club(
        create_club(
            home_territory["id"],
            franchisee["id"],
            name="Summit Home",
            guest_fee_cents=1250,
        )["id"],
        franchisee["id"],
    )
    host_club = open_club(
        create_club(
            host_territory["id"],
            franchisee["id"],
            name="Summit Host X",
            guest_fee_cents=647,
        )["id"],
        franchisee["id"],
    )
    plan_template = create_published_plan_template()
    member = create_member(
        home_club["id"],
        full_name="Noor Bhattacharya",
        email="noor.bhattacharya@example.com",
    )
    set_clock_date("2026-07-01")
    agreement = sign_agreement(
        member["id"],
        home_club["id"],
        plan_template["id"],
        signed_on="2026-07-01",
        multi_club_access=True,
    )
    batch_84 = record_guest_usage(agreement["id"], host_club["id"], "2026-07", 84)
    set_clock_date("2026-08-01")
    batch_83 = record_guest_usage(agreement["id"], host_club["id"], "2026-08", 83)
    return {
        "home_club": home_club,
        "host_club": host_club,
        "batch_84": batch_84,
        "batch_83": batch_83,
        "settlement_84": create_usage_settlement(
            "2026-07", home_club["id"], host_club["id"]
        ),
        "settlement_83": create_usage_settlement(
            "2026-08", home_club["id"], host_club["id"]
        ),
    }


def test_settlement_sweep_counts_every_unsettled_batch_for_the_pair():
    """Two batches of 50 and 34 visits at 1250 cents each sweep into one settlement of
    84 visits and 105000 cents gross.

    PRD 3.7: "`event_count` is the number of swept rows and `visit_count` is the sum of
    their visit counts."

    Design: Difficulty/combinatorial_formula/settlement_rebate_tier_keyed_only_on_net_before_rebate
    """
    scenario = _eighty_four_visits_at_the_standard_guest_fee()
    settlement = scenario["settlement"]

    assert scenario["agreement"]["effective_monthly_dues_cents"] == 4432
    assert scenario["guest_usage_events"][0]["usage_fee_cents"] == 62500
    assert scenario["guest_usage_events"][1]["usage_fee_cents"] == 42500
    assert settlement["event_count"] == 2
    assert settlement["visit_count"] == 84
    assert settlement["gross_fee_cents"] == 105000


def test_rebate_tier_is_keyed_on_the_net_before_rebate_and_nothing_else():
    """The 105000 gross would reach the six percent tier, but the tier reads the 96600
    net instead and pays three percent, leaving 93702 payable rather than 90804.

    PRD 3.7: "Step three, tier selection, which is keyed on `net_before_rebate_cents` and
    on nothing else — never on `gross_fee_cents` and never on the final payable:
    `rebate_pct` is 0.00 when `net_before_rebate_cents` is below 50000 cents, 0.03 when it
    is at least 50000 but below 100000 cents, and 0.06 when it is at or above 100000
    cents."

    Design: Difficulty/combinatorial_formula/settlement_rebate_tier_keyed_only_on_net_before_rebate
    """
    settlement = _eighty_four_visits_at_the_standard_guest_fee()["settlement"]

    assert settlement["admin_hold_cents"] == 8400
    assert settlement["net_before_rebate_cents"] == 96600
    assert settlement["rebate_pct"] == 0.03
    assert settlement["volume_rebate_cents"] == 2898
    assert settlement["net_payable_cents"] == 93702
    assert settlement["net_payable_cents"] != 90804


def test_creating_a_settlement_moves_no_money_between_the_club_ledgers():
    """Creation only stamps the swept batches and computes the payable; both ledgers stay
    at zero until the settlement is posted.

    PRD 3.7: "Creation stamps the new settlement's identifier into the `settlement_id` of
    every swept batch and leaves the settlement `OPEN`, with `posted_on` and `reversed_on`
    null."

    Design: Difficulty/combinatorial_formula/settlement_rebate_tier_keyed_only_on_net_before_rebate
    """
    scenario = _eighty_four_visits_at_the_standard_guest_fee()

    assert scenario["settlement"]["status"] == "OPEN"
    assert scenario["settlement"]["posted_on"] is None
    assert scenario["settlement"]["reversed_on"] is None
    home = read_club(scenario["home_club"]["id"])
    host = read_club(scenario["host_club"]["id"])
    assert home["settlement_ledger_cents"] == 0
    assert host["settlement_ledger_cents"] == 0


def test_net_before_rebate_of_exactly_the_tier_floor_earns_the_three_percent_rebate():
    """84 visits at 647 cents give 54348 gross and a rounded hold of 4348, landing the net
    on exactly 50000 — not below the floor, so the three percent tier applies.

    PRD 3.7: "Step one, the brand's administration hold: `admin_hold_cents` is
    `gross_fee_cents` multiplied by 0.08 — eight percent — rounded half up to whole cents."

    Design: Difficulty/boundary_precision_check/usage_settlement_rebate_tier_at_the_exact_fifty_thousand_cent_floor
    """
    settlement = _two_settlements_around_the_tier_floor()["settlement_84"]

    assert settlement["event_count"] == 1
    assert settlement["visit_count"] == 84
    assert settlement["gross_fee_cents"] == 54348
    assert settlement["admin_hold_cents"] == 4348
    assert settlement["net_before_rebate_cents"] == 50000
    assert settlement["rebate_pct"] == 0.03
    assert settlement["volume_rebate_cents"] == 1500
    assert settlement["net_payable_cents"] == 48500
    assert settlement["status"] == "OPEN"


def test_one_visit_fewer_falls_under_the_tier_floor_and_earns_no_rebate():
    """83 visits give 53701 gross, a 4296 hold and a 49405 net — 595 cents under the
    floor — so the rebate is zero and the whole net stays payable.

    PRD 3.7: "Step four, and only now: `volume_rebate_cents` is `net_before_rebate_cents`
    multiplied by `rebate_pct`, rounded half up to whole cents."

    Design: Difficulty/boundary_precision_check/usage_settlement_rebate_tier_at_the_exact_fifty_thousand_cent_floor
    """
    settlement = _two_settlements_around_the_tier_floor()["settlement_83"]

    assert settlement["event_count"] == 1
    assert settlement["visit_count"] == 83
    assert settlement["gross_fee_cents"] == 53701
    assert settlement["admin_hold_cents"] == 4296
    assert settlement["net_before_rebate_cents"] == 49405
    assert settlement["rebate_pct"] == 0.0
    assert settlement["volume_rebate_cents"] == 0
    assert settlement["net_payable_cents"] == 49405


def test_guest_fee_is_snapshotted_from_the_host_club_at_recording_time():
    """Each batch keeps the 647-cent fee it was recorded against, which is what makes the
    two gross figures 54348 and 53701.

    PRD 3.7: "`guest_fee_cents_at_visit` captures the host club's `guest_fee_cents` as it
    stands at that instant."

    Design: Difficulty/boundary_precision_check/usage_settlement_rebate_tier_at_the_exact_fifty_thousand_cent_floor
    """
    setup = _two_settlements_around_the_tier_floor()

    assert setup["batch_84"]["guest_fee_cents_at_visit"] == 647
    assert setup["batch_84"]["usage_fee_cents"] == 54348
    assert setup["batch_83"]["guest_fee_cents_at_visit"] == 647
    assert setup["batch_83"]["usage_fee_cents"] == 53701


def test_posting_debits_the_home_club_and_credits_the_host_by_the_same_amount():
    """93702 cents leave the paying club and arrive at the hosting club in one request, so
    the network-wide ledger still sums to zero.

    PRD 3.7: "The home club's `settlement_ledger_cents` decreases by `net_payable_cents`
    and the host club's increases by the same amount, `status` advances `OPEN → POSTED`,
    `posted_on` records the logical clock date, and the settlement's `version` plus both
    clubs' `version` values each increment by 1."

    Design: Difficulty/compensating_invariant/settlement_post_then_reverse_conserves_the_zero_sum_inter_club_ledger
    """
    scenario = _eighty_four_visits_at_the_standard_guest_fee()
    posted = post_usage_settlement(scenario["settlement"]["id"])

    assert posted["status"] == "POSTED"
    assert posted["net_payable_cents"] == 93702
    home = read_club(scenario["home_club"]["id"])
    host = read_club(scenario["host_club"]["id"])
    assert home["settlement_ledger_cents"] == -93702
    assert host["settlement_ledger_cents"] == 93702
    assert_settlement_ledger_conserved([home, host])


def test_reversal_returns_both_ledgers_and_every_sweep_flag_to_its_pre_post_value():
    """The compensating action undoes both legs exactly and releases the swept batches,
    while the settlement keeps the payable it was posted at.

    PRD 3.7: "Both club ledgers and the sweep flags return to exactly their pre-posting
    values with zero drift."

    Design: Difficulty/compensating_invariant/settlement_post_then_reverse_conserves_the_zero_sum_inter_club_ledger
    """
    scenario = _eighty_four_visits_at_the_standard_guest_fee()
    post_usage_settlement(scenario["settlement"]["id"])
    reversed_settlement = reverse_usage_settlement(scenario["settlement"]["id"])

    assert reversed_settlement["status"] == "REVERSED"
    assert reversed_settlement["net_payable_cents"] == 93702
    home = read_club(scenario["home_club"]["id"])
    host = read_club(scenario["host_club"]["id"])
    assert home["settlement_ledger_cents"] == 0
    assert host["settlement_ledger_cents"] == 0
    assert_settlement_ledger_conserved([home, host])
    for event in scenario["guest_usage_events"]:
        assert read_guest_usage_event(event["id"])["settlement_id"] is None


def test_released_batches_can_be_swept_into_a_fresh_settlement_for_the_same_triple():
    """Because reversal cleared the flags, the same two batches settle again at exactly
    the same figures under a new settlement identifier.

    PRD 3.7: "Reversing anything that is not `POSTED` is refused with
    `ERR_INVALID_SETTLEMENT_STATE`, and `REVERSED` is terminal — a reversed settlement is
    never re-posted, though the released batches may be swept into a fresh one."

    Design: Difficulty/compensating_invariant/settlement_post_then_reverse_conserves_the_zero_sum_inter_club_ledger
    """
    scenario = _eighty_four_visits_at_the_standard_guest_fee()
    post_usage_settlement(scenario["settlement"]["id"])
    reverse_usage_settlement(scenario["settlement"]["id"])

    resettlement = validate_success(
        api_client.create_usage_settlement(
            {
                "period_month": "2026-08",
                "home_club_id": scenario["home_club"]["id"],
                "host_club_id": scenario["host_club"]["id"],
            },
            BRAND,
        ),
        expected_status=201,
    )

    assert resettlement["id"] != scenario["settlement"]["id"]
    assert resettlement["status"] == "OPEN"
    assert resettlement["event_count"] == 2
    assert resettlement["visit_count"] == 84
    assert resettlement["net_payable_cents"] == 93702
    for event in scenario["guest_usage_events"]:
        assert read_guest_usage_event(event["id"])["settlement_id"] == resettlement["id"]
    assert read_usage_settlement(scenario["settlement"]["id"])["status"] == "REVERSED"
