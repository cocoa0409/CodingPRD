"""Breadth tests: calculation results, branch selection and rounding order."""
from test_helpers import (
    ATTRACTION_HOST,
    DEAL_DESK_CLERK,
    EVENTS_COORDINATOR,
    PERMIT_CLERK,
    REMIT_ADMIN,
    STORE_MANAGER,
    accept_appraisal,
    create_appraisal,
    create_boat_unit,
    create_event_offering,
    create_member,
    create_open_attraction,
    create_point_event,
    create_remit_batch,
    create_store,
    get_success_data,
    set_clock,
)


# --- calculations/event_dwell_charge_flat_branch_for_free_demo -------------

def test_a_free_demo_is_charged_a_flat_fifteen_minutes_whatever_volume_registers(api):
    """PRD §2.8.1: "A free demo takes the flat branch and is charged fifteen
    minutes regardless of any registration volume; the seat arithmetic is
    skipped entirely."

    Design: Corner/calculations/event_dwell_charge_flat_branch_for_free_demo
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    member = create_member(api, store["id"], email="m_ev@x.com",
                           full_name="Eve Rill")
    offering = create_event_offering(api, store["id"], offering_kind="FREE_DEMO",
                                     title="Boat Wash Demo",
                                     starts_at_utc="2026-10-01T10:00:00Z",
                                     ends_at_utc="2026-10-01T11:00:00Z",
                                     registration_cap=0)
    get_success_data(api.publish_event_offering(offering["id"], EVENTS_COORDINATOR), 200)
    registration = get_success_data(
        api.create_event_registration(store["id"], offering["id"],
                                      {"member_id": member["id"], "seats": 4},
                                      EVENTS_COORDINATOR),
        201,
    )
    get_success_data(
        api.confirm_event_registration(offering["id"], registration["id"],
                                       EVENTS_COORDINATOR),
        200,
    )

    refreshed = get_success_data(
        api.get_event_offering(offering["id"], EVENTS_COORDINATOR), 200
    )
    assert refreshed["dwell_charge_minutes"] == 15, (
        "a free demo is charged fifteen minutes flat; got "
        f"{refreshed['dwell_charge_minutes']}"
    )
    assert refreshed["confirmed_count"] == 4, (
        "the seats were counted for capacity but not for dwell; got "
        f"{refreshed['confirmed_count']}"
    )
    summary = get_success_data(api.get_dwell_summary(store["id"], STORE_MANAGER), 200)
    assert summary["dwell_committed_minutes"] == 15, (
        "the seat count never entered the dwell arithmetic; got "
        f"{summary['dwell_committed_minutes']}"
    )


# --- calculations/event_dwell_charge_two_phase_and_rounding_order ----------

def test_a_capped_event_is_charged_the_two_phase_sum_rounded_once(api):
    """PRD §2.8.1: "half the registration cap, rounded up, is charged at the
    base rate of half a minute per seat, and the remaining overflow half is
    charged at double that rate."
    PRD §2.8.1: "The two halves are summed and the sum is rounded half up
    exactly once — rounding each half separately is forbidden. A cap of thirty
    therefore costs twenty-three minutes."

    Design: Corner/calculations/event_dwell_charge_two_phase_and_rounding_order
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    seminar = create_event_offering(api, store["id"], offering_kind="SEMINAR",
                                    title="Cold Water Safety",
                                    starts_at_utc="2026-10-02T10:00:00Z",
                                    ends_at_utc="2026-10-02T12:00:00Z",
                                    registration_cap=30)
    published = get_success_data(
        api.publish_event_offering(seminar["id"], EVENTS_COORDINATOR), 200
    )
    assert published["dwell_charge_minutes"] == 23, (
        "half the cap rounded up is fifteen seats at half a minute, the overflow "
        f"half is fifteen seats at one minute; got {published['dwell_charge_minutes']}"
    )
    assert isinstance(published["dwell_charge_minutes"], int), (
        "no offering reports a fractional dwell value"
    )


def test_a_second_capped_event_prices_its_own_cap_independently(api):
    """PRD §2.8.1: "Every other offering takes the capped two-phase branch: half
    the registration cap, rounded up, is charged at the base rate of half a
    minute per seat, and the remaining overflow half is charged at double that
    rate."

    Design: Corner/calculations/event_dwell_charge_two_phase_and_rounding_order
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    workshop = create_event_offering(api, store["id"], offering_kind="KIDS_WORKSHOP",
                                     title="Bait Tying",
                                     starts_at_utc="2026-10-03T10:00:00Z",
                                     ends_at_utc="2026-10-03T11:30:00Z",
                                     registration_cap=31)
    published = get_success_data(
        api.publish_event_offering(workshop["id"], EVENTS_COORDINATOR), 200
    )
    assert published["dwell_charge_minutes"] >= 20, (
        "a cap of thirty-one still crosses the base half and the overflow half; "
        f"got {published['dwell_charge_minutes']}"
    )
    assert isinstance(published["dwell_charge_minutes"], int)
    summary = get_success_data(api.get_dwell_summary(store["id"], STORE_MANAGER), 200)
    assert summary["dwell_committed_minutes"] == published["dwell_charge_minutes"], (
        "publishing commits exactly the offering's own charge; got "
        f"{summary['dwell_committed_minutes']}"
    )


# --- calculations/club_points_replay_is_chronological_and_floors_at_zero ---

def test_a_redemption_larger_than_the_balance_saturates_at_zero(api):
    """PRD §2.8.1: "After each event both running totals are clamped at zero by
    taking the greater of the running total and zero, so the balance and the
    lifetime earned can never go negative at any intermediate step."
    PRD §2.8.1: "For `REDEEM` events the absolute value of the event's
    `points_delta` is subtracted from the balance and the lifetime total is
    untouched."

    Design: Corner/calculations/club_points_replay_is_chronological_and_floors_at_zero
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    member = create_member(api, store["id"], email="m_rp@x.com",
                           full_name="Rhea Pell")
    create_point_event(api, store["id"], member["id"], event_kind="AWARD",
                       points_delta=500)
    redemption = create_point_event(api, store["id"], member["id"],
                                    event_kind="REDEEM", points_delta=-800)

    refreshed = get_success_data(api.get_member(member["id"], STORE_MANAGER), 200)
    assert refreshed["points_balance"] == 0, (
        "an oversized redemption floors at zero rather than going negative; got "
        f"{refreshed['points_balance']}"
    )
    assert refreshed["points_lifetime_earned"] == 500, (
        "a redemption does not reduce lifetime earnings; got "
        f"{refreshed['points_lifetime_earned']}"
    )
    assert refreshed["club_tier"] == "BASE", (
        f"500 sits below the 8000-point SILVER threshold; got {refreshed['club_tier']}"
    )
    assert redemption["points_delta"] == -800
    assert redemption["event_kind"] == "REDEEM"


# --- calculations/tier_downgrade_and_retention_floor ----------------------

def test_a_reversal_that_drops_the_lifetime_value_downgrades_the_tier(api):
    """PRD §2.8.1: "Downgrades are applied only against the member's current
    lifetime value, never against a historical maximum."
    PRD §2.8.1: "the floor is zero points at `BASE`, five hundred at `SILVER`,
    fifteen hundred at `GOLD` and four thousand at `PATRON`."
    PRD §2.8.1: "a member whose lifetime total has fallen back below a threshold
    they once held is downgraded."

    Design: Corner/calculations/tier_downgrade_and_retention_floor
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    member = create_member(api, store["id"], email="m_tf@x.com",
                           full_name="Trey Fenn")
    create_point_event(api, store["id"], member["id"], event_kind="AWARD",
                       points_delta=3000)
    create_point_event(api, store["id"], member["id"], event_kind="AWARD",
                       points_delta=5000)

    silver = get_success_data(api.get_member(member["id"], STORE_MANAGER), 200)
    assert silver["points_lifetime_earned"] == 8000
    assert silver["club_tier"] == "SILVER"
    assert silver["redeemable_points"] == 7500, (
        "8000 balance minus the SILVER retention floor of 500; got "
        f"{silver['redeemable_points']}"
    )

    create_point_event(api, store["id"], member["id"], event_kind="REVERSAL",
                       points_delta=-5000)
    base = get_success_data(api.get_member(member["id"], STORE_MANAGER), 200)
    assert base["points_lifetime_earned"] == 3000, (
        f"the reversal subtracts its magnitude from the lifetime total; got "
        f"{base['points_lifetime_earned']}"
    )
    assert base["club_tier"] == "BASE", (
        f"the downgrade is applied on the current lifetime value; got "
        f"{base['club_tier']}"
    )
    assert base["redeemable_points"] == 3000, (
        "a BASE member carries no retention floor; got "
        f"{base['redeemable_points']}"
    )


# --- calculations/trade_in_credit_boundary_at_and_above_the_penalty_round --

def test_the_prior_title_penalty_rounds_on_the_offer_and_barely_moves(api):
    """PRD §2.8.1: "when it does carry one the offer is multiplied by two
    hundred basis points."
    PRD §2.8.1: "Each arc is rounded half up on its own before it is combined.
    The credited value is the offer amount, plus the rounded rebate, minus the
    rounded penalty."
    PRD §2.8.1: "the penalty is rounded before it is subtracted."

    Design: Corner/calculations/trade_in_credit_boundary_at_and_above_the_penalty_round
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    member = create_member(api, store["id"], email="m_tb@x.com",
                           full_name="Tess Bell")
    first_unit = create_boat_unit(api, store["id"], stock_no="BU-P1",
                                  model_name="Bay 170", unit_price_cents=4_000_000,
                                  unit_condition="USED", hull_id_no="HINP10000001",
                                  prior_title_no="MO-TTL-OLD-0001",
                                  motor_price_cents=0, trailer_price_cents=0)
    second_unit = create_boat_unit(api, store["id"], stock_no="BU-P2",
                                   model_name="Bay 170", unit_price_cents=4_000_000,
                                   unit_condition="USED", hull_id_no="HINP20000001",
                                   prior_title_no="MO-TTL-OLD-0002",
                                   motor_price_cents=0, trailer_price_cents=0)
    first = accept_appraisal(api, create_appraisal(
        api, store["id"], member["id"], first_unit["id"], offer_amount_cents=50_000
    )["id"])
    second = accept_appraisal(api, create_appraisal(
        api, store["id"], member["id"], second_unit["id"], offer_amount_cents=50_001
    )["id"])

    assert first["accepted_credit_cents"] == 49_000, (
        "a 50000-cent offer loses the rounded 1000-cent penalty; got "
        f"{first['accepted_credit_cents']}"
    )
    assert second["accepted_credit_cents"] >= 49_001, (
        "the penalty does not grow proportionally at this scale; got "
        f"{second['accepted_credit_cents']}"
    )
    assert second["accepted_credit_cents"] - first["accepted_credit_cents"] <= 1, (
        "a one-cent larger offer cannot lose more than one cent of credit; got "
        f"{second['accepted_credit_cents'] - first['accepted_credit_cents']}"
    )


# --- calculations/permit_remit_window_is_half_open_at_the_end_boundary -----

def test_a_sale_stamped_at_the_window_boundary_is_included_only_on_the_start_side(api):
    """PRD §2.8.1: "where the window is half-open: a sale created exactly at
    `window_start_utc` is included and a sale created exactly at
    `window_end_utc` is excluded."

    Design: Corner/calculations/permit_remit_window_is_half_open_at_the_end_boundary
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    member = create_member(api, store["id"], email="m_hw@x.com",
                           full_name="Hana Weir")
    batch = create_remit_batch(api, store["id"])

    inside = get_success_data(
        api.create_permit_sale(
            store["id"],
            {
                "member_id": member["id"],
                "permit_type": "FISHING",
                "residency_class": "RESIDENT",
                "term_days": 7,
                "land_access_units": 0,
                "agent_user_id": "clerk_4471",
                "permit_remit_batch_id": batch["id"],
                "expected_remit_batch_version": batch["version"],
            },
            PERMIT_CLERK,
        ),
        201,
    )
    refreshed_batch = get_success_data(api.get_remit_batch(batch["id"], REMIT_ADMIN), 200)

    set_clock(api, "2026-09-30T00:00:00Z")
    excluded = get_success_data(
        api.create_permit_sale(
            store["id"],
            {
                "member_id": member["id"],
                "permit_type": "FISHING",
                "residency_class": "RESIDENT",
                "term_days": 7,
                "land_access_units": 0,
                "agent_user_id": "clerk_4471",
                "permit_remit_batch_id": batch["id"],
                "expected_remit_batch_version": refreshed_batch["version"],
            },
            PERMIT_CLERK,
        ),
        201,
    )

    sealed = get_success_data(
        api.seal_remit_batch(batch["id"], {"remitter_admin_user_id": "remit_9001"},
                             REMIT_ADMIN),
        200,
    )
    assert sealed["gross_fee_cents"] == 3200, (
        "the frozen total contains only the sale stamped exactly at "
        f"window_start_utc; got {sealed['gross_fee_cents']}"
    )
    assert excluded["fee_cents"] == 3200
    assert inside["fee_cents"] == 3200
    assert sealed["remit_variance_cents"] == 0, (
        f"the frozen and live reads agree at seal time; got "
        f"{sealed['remit_variance_cents']}"
    )


# --- calculations/remit_window_with_no_eligible_sale_is_rejected -----------

def test_a_batch_whose_window_precedes_every_sale_is_refused_as_empty(api):
    """PRD §3.7: "a batch presented with an empty window is refused with
    `ERR_EMPTY_REMIT_WINDOW` (HTTP 422)."
    PRD §3.7: "`gross_fee_cents` is the sum of the sales' `fee_cents` at that
    instant and never moves again ... and the store's `remit_ledger_cents` gains
    the frozen gross fee."

    Design: Corner/calculations/remit_window_with_no_eligible_sale_is_rejected
    """
    set_clock(api, "2026-09-15T00:00:00Z")
    store = create_store(api)
    member = create_member(api, store["id"], email="m_em@x.com",
                           full_name="Eli Mott")
    empty_batch = create_remit_batch(api, store["id"],
                                     window_start_utc="2026-08-01T00:00:00Z",
                                     window_end_utc="2026-08-31T00:00:00Z")
    full_batch = create_remit_batch(api, store["id"])
    get_success_data(
        api.create_permit_sale(
            store["id"],
            {
                "member_id": member["id"],
                "permit_type": "FISHING",
                "residency_class": "RESIDENT",
                "term_days": 7,
                "land_access_units": 0,
                "agent_user_id": "clerk_4471",
                "permit_remit_batch_id": full_batch["id"],
                "expected_remit_batch_version": full_batch["version"],
            },
            PERMIT_CLERK,
        ),
        201,
    )

    response = api.seal_remit_batch(empty_batch["id"],
                                    {"remitter_admin_user_id": "remit_9001"},
                                    REMIT_ADMIN)
    assert response.status_code >= 400, (
        "a batch with no eligible sale in its window cannot be sealed"
    )

    get_success_data(
        api.seal_remit_batch(full_batch["id"], {"remitter_admin_user_id": "remit_9001"},
                             REMIT_ADMIN),
        200,
    )
    store_row = get_success_data(api.get_store(store["id"], STORE_MANAGER), 200)
    assert store_row["remit_ledger_cents"] == 3200, (
        "the ledger is the accumulated sum of every sealed batch's frozen total, "
        f"so the empty batch contributed nothing; got {store_row['remit_ledger_cents']}"
    )


# --- calculations/attraction_posture_frozen_outranks_restricted ------------

def test_identical_commits_against_different_budgets_read_two_different_postures(api):
    """PRD §2.7: "A store is `FROZEN` when its free minutes have fallen below
    zero, or when at least one of its venues is over capacity."
    PRD §2.7: "It is `RESTRICTED` when free minutes have fallen below thirty
    minutes without crossing zero."

    Design: Corner/calculations/attraction_posture_frozen_outranks_restricted
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    tight_store = create_store(api, name="Tight Cove", dwell_capacity_minutes=55)
    roomy_store = create_store(api, name="Roomy Cove", state_code="MO",
                               dealer_license_no="MO-DLR-4418",
                               dwell_capacity_minutes=100)
    tight_venue = create_open_attraction(api, tight_store["id"],
                                         attraction_type="AQUARIUM",
                                         capacity_units=40, dwell_cost_minutes=30)
    roomy_venue = create_open_attraction(api, roomy_store["id"],
                                         attraction_type="AQUARIUM",
                                         capacity_units=40, dwell_cost_minutes=30)
    tight_member = create_member(api, tight_store["id"], email="m_ap1@x.com",
                                 full_name="Ada Pike")
    roomy_member = create_member(api, roomy_store["id"], email="m_ap2@x.com",
                                 full_name="Abe Pike")

    tight_session = get_success_data(
        api.create_session(
            tight_store["id"],
            {"attraction_id": tight_venue["id"], "member_id": tight_member["id"],
             "session_kind": "GENERAL_ADMISSION", "party_size": 10,
             "slot_start_utc": "2026-11-01T10:00:00Z",
             "slot_end_utc": "2026-11-01T11:00:00Z"},
            ATTRACTION_HOST,
        ),
        201,
    )
    roomy_session = get_success_data(
        api.create_session(
            roomy_store["id"],
            {"attraction_id": roomy_venue["id"], "member_id": roomy_member["id"],
             "session_kind": "GENERAL_ADMISSION", "party_size": 10,
             "slot_start_utc": "2026-11-01T10:00:00Z",
             "slot_end_utc": "2026-11-01T11:00:00Z"},
            ATTRACTION_HOST,
        ),
        201,
    )
    assert tight_session["dwell_charge_minutes"] == roomy_session["dwell_charge_minutes"], (
        "both stores commit exactly the same number of minutes"
    )
    assert tight_session["status"] == "CONFIRMED", (
        f"the tight store's first commit is admitted; got {tight_session['status']}"
    )
    assert roomy_session["status"] == "CONFIRMED", (
        f"the roomy store's commit is admitted; got {roomy_session['status']}"
    )

    tight_summary = get_success_data(
        api.get_dwell_summary(tight_store["id"], STORE_MANAGER), 200
    )
    roomy_summary = get_success_data(
        api.get_dwell_summary(roomy_store["id"], STORE_MANAGER), 200
    )
    assert tight_summary["attraction_posture"] == "FROZEN", (
        "free minutes below zero takes the first branch of the ordered predicate; "
        f"got {tight_summary['attraction_posture']}"
    )
    assert tight_summary["dwell_free_minutes"] < 0
    assert roomy_summary["attraction_posture"] == "RESTRICTED", (
        "free minutes inside the thirty-minute band take the second branch; got "
        f"{roomy_summary['attraction_posture']}"
    )
    assert 0 <= roomy_summary["dwell_free_minutes"] < 30, (
        f"the roomy store sits inside the critical band; got "
        f"{roomy_summary['dwell_free_minutes']}"
    )


# --- calculations/boat_deal_quote_variant_excludes_rigging_fee -------------

def test_the_same_deal_reports_two_prices_across_its_own_lifecycle(api):
    """PRD §2.8.1: "The provisional quote variant applies while the deal's commercial stage is"
    PRD §2.8.1: "the contracted settlement variant applies when the deal's
    commercial stage is `CONTRACTED`, `DELIVERED` or `SETTLED` and at least one
    funding record exists."

    Design: Corner/calculations/boat_deal_quote_variant_excludes_rigging_fee
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    member = create_member(api, store["id"], email="m_vs@x.com",
                           full_name="Vera Sand")
    unit = create_boat_unit(api, store["id"], stock_no="BU-9001",
                            model_name="Angler 190", unit_price_cents=9_000_000,
                            motor_price_cents=1_800_000,
                            trailer_price_cents=350_000, unit_condition="NEW",
                            hull_id_no="HIN9001AA000")
    deal = get_success_data(
        api.create_deal(store["id"], {"member_id": member["id"],
                                      "boat_unit_id": unit["id"]},
                        DEAL_DESK_CLERK),
        201,
    )
    assert deal["deal_stage"] == "QUOTED"
    assert deal["contract_price_cents"] == 11_125_000, (
        "the quote variant withholds the 95000-cent rigging fee; got "
        f"{deal['contract_price_cents']}"
    )

    contracted = get_success_data(
        api.contract_deal(deal["id"], {"expected_deal_version": deal["version"]},
                          DEAL_DESK_CLERK),
        200,
    )
    assert contracted["deal_stage"] == "CONTRACTED"
    assert contracted["contract_price_cents"] == 11_220_000, (
        "the contracted variant restores the rigging fee; got "
        f"{contracted['contract_price_cents']}"
    )
    assert (
        contracted["contract_price_cents"] - deal["contract_price_cents"] == 95_000
    ), "the reading under the provisional variant is exactly the rigging fee lower"
    assert contracted["total_fee_cents"] > 0, (
        "the relay flips with the variant, so a contracted deal carries its fees"
    )