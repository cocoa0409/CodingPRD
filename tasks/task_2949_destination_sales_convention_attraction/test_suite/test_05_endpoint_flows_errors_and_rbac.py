"""Endpoint round-trips, the error catalogue and role/ownership enforcement.

Three corner-design sections are translated in this one file, in this order:

  1. ``endpoints``  -- CRUD round trips, action endpoints, the ops checkpoint,
     the junction listing and the derived read snapshot.
  2. ``errors``     -- per-kind not-found codes, foreign-key/OCC precedence and
     the shape of the error envelope itself.
  3. ``rbac``       -- authentication defects, per-endpoint role lists,
     entity-backed ownership and segregation of duties.

Every test builds all of its own preconditions: the runner restarts the server
and wipes the database before each one, and the logical clock is pinned as the
first server call of every test.
"""
import pytest

from test_helpers import (
    INCENTIVE_APPROVER_USER_ID,
    NON_EXISTENT_UUID,
    SALES_MANAGER_USER_ID,
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_bid_package,
    assert_error_envelope_shape,
    assert_incentive_decision,
    assert_incentive_fund,
    assert_lodging_tax_receipt,
    assert_meeting_planner,
    assert_money_equals,
    assert_opportunity,
    assert_pagination_meta,
    assert_room_block_commitment,
    assert_space_hold,
    get_success_data,
    headers_with_blank_role,
    headers_with_blank_user_id,
    headers_with_undeclared_role,
    headers_without_role,
    headers_without_user_id,
    incentive_decision_payload,
    make_hotel_partner_headers,
    make_incentive_approver_headers,
    make_meeting_planner_headers,
    make_sales_manager_headers,
    pickup_record_payload,
    same_instant,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures

ADMIN = TEST_USERS["bureau_admin_headers"]
SALES = TEST_USERS["sales_manager_headers"]
SCHEDULER = TEST_USERS["center_scheduler_headers"]
APPROVER = TEST_USERS["incentive_approver_headers"]
SERVICES = TEST_USERS["services_manager_headers"]
ANALYST = TEST_USERS["board_analyst_headers"]


# =============================================================================
# Section `endpoints`
# =============================================================================

def test_incentive_fund_is_created_read_back_and_found_by_its_fiscal_year(
    bureau_admin_headers, incentive_approver_headers, board_analyst_headers
):
    """A new fund starts fully uncommitted and OPEN, reads back and filters by fiscal_year.

    PRD: "At creation `committed_amount`, `disbursed_amount` and
    `lodging_tax_receipts_total` are all `0.00`, `uncommitted_amount` equals
    `budget_amount`, and `posture` is `OPEN`." (PRD S3.1)
    PRD: "Fund listings may be filtered by `fiscal_year` and by `posture`" (PRD S3.1)

    Design: Corner/endpoints/incentive_fund_crud_round_trip_with_receipt_credits
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")

    created = validate_success(
        api_client.create_incentive_fund(
            {"fiscal_year": 2028, "budget_amount": 500_000.00}, bureau_admin_headers
        ),
        201,
    )
    assert_incentive_fund(created)
    assert created["posture"] == "OPEN"
    assert_money_equals(created["budget_amount"], 500_000.00, "budget_amount")
    assert_money_equals(created["uncommitted_amount"], 500_000.00, "uncommitted_amount")
    assert_money_equals(created["committed_amount"], 0.00, "committed_amount")
    assert_money_equals(created["disbursed_amount"], 0.00, "disbursed_amount")
    assert_money_equals(
        created["lodging_tax_receipts_total"], 0.00, "lodging_tax_receipts_total"
    )
    assert created["version"] == 1, "a freshly created row's version begins at 1"

    other = validate_success(
        api_client.create_incentive_fund(
            {"fiscal_year": 2029, "budget_amount": 250_000.00}, bureau_admin_headers
        ),
        201,
    )
    assert other["id"] != created["id"]

    read_back = validate_success(
        api_client.get_incentive_fund(created["id"], incentive_approver_headers)
    )
    assert read_back["id"] == created["id"]
    assert read_back["fiscal_year"] == 2028
    assert_money_equals(read_back["budget_amount"], 500_000.00, "budget_amount")

    listed, meta = validate_paginated(
        api_client.list_incentive_funds(board_analyst_headers, params={"fiscal_year": 2028})
    )
    assert meta["total_count"] == 1, "the FY2029 fund is excluded by the filter"
    assert [row["id"] for row in listed] == [created["id"]]


def test_lodging_tax_receipts_raise_the_budget_and_bump_the_fund_version(
    bureau_admin_headers, incentive_approver_headers, board_analyst_headers
):
    """Two receipt credits accumulate into the fund and each one bumps its version.

    PRD: "Posting a receipt raises both `lodging_tax_receipts_total` and
    `budget_amount` by the receipt `amount`, recomputes `uncommitted_amount` from
    the conservation identity, re-derives `posture`, and bumps the fund's
    `version` by one" (PRD S3.1)
    PRD: "`budget_amount` equals `uncommitted_amount` plus `committed_amount` plus
    `disbursed_amount`." (PRD S2.10)

    Design: Corner/endpoints/incentive_fund_crud_round_trip_with_receipt_credits
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    fund = fixtures.open_fund(fiscal_year=2028, budget_amount=500_000.00)
    other = fixtures.open_fund(fiscal_year=2029, budget_amount=250_000.00)

    first = validate_success(
        api_client.create_lodging_tax_receipt(
            fund["id"],
            {"amount": 12_000.50, "received_at": "2026-07-15T00:00:00Z"},
            bureau_admin_headers,
        ),
        201,
    )
    assert_lodging_tax_receipt(first)
    assert first["fund_id"] == fund["id"]
    assert_money_equals(first["amount"], 12_000.50, "receipt.amount")

    second = validate_success(
        api_client.create_lodging_tax_receipt(
            fund["id"],
            {"amount": 8_000.25, "received_at": "2026-08-01T00:00:00Z"},
            bureau_admin_headers,
        ),
        201,
    )

    after = validate_success(
        api_client.get_incentive_fund(fund["id"], incentive_approver_headers)
    )
    assert_incentive_fund(after)
    assert_money_equals(
        after["lodging_tax_receipts_total"], 20_000.75, "lodging_tax_receipts_total"
    )
    assert_money_equals(after["budget_amount"], 520_000.75, "budget_amount")
    assert_money_equals(after["uncommitted_amount"], 520_000.75, "uncommitted_amount")
    assert after["posture"] == "OPEN"
    assert after["version"] == 3, "each of the two receipt credits bumped the fund's version"

    page, meta = validate_paginated(
        api_client.list_lodging_tax_receipts(
            fund["id"], board_analyst_headers, params={"limit": 1, "offset": 1}
        )
    )
    assert_pagination_meta(meta, limit=1, offset=1, total_count=2, has_more=False)
    assert [row["id"] for row in page] == [second["id"]], (
        "list results are ordered by created_at ascending, so offset 1 is the second credit"
    )

    _, other_meta = validate_paginated(
        api_client.list_lodging_tax_receipts(other["id"], board_analyst_headers)
    )
    assert other_meta["total_count"] == 0, "receipts are scoped to the fund they credit"


def test_suspending_a_property_gates_the_invite_and_leaves_the_opportunity_version_intact(
    bureau_admin_headers, sales_manager_headers
):
    """A SUSPENDED property refuses the invite, and the refusal mutates nothing.

    PRD: "while a property is `SUSPENDED` it may neither be invited into a new
    block, nor answer an invitation, nor have an offer committed, each of those
    three attempts failing with `ERR_HOTEL_NOT_PARTICIPATING`." (PRD S3.1)
    PRD: "A cascade that does not fire leaves no trace: no counter moves, no
    version is bumped on the untouched row." (PRD S2.9)

    Design: Corner/endpoints/participation_action_is_the_only_hotel_mutator_and_gates_invites
    """
    scenario = fixtures.setup_lead()
    hotel = scenario["hotels"][0]
    assert hotel["participation_status"] == "PARTICIPATING", (
        "participation_status defaults to PARTICIPATING at registration"
    )
    base_version = hotel["version"]

    suspended = validate_success(
        api_client.set_hotel_participation(
            hotel["id"], {"participation_status": "SUSPENDED"}, bureau_admin_headers
        )
    )
    assert suspended["participation_status"] == "SUSPENDED"
    assert suspended["version"] == base_version + 1

    observed_version = fixtures.opportunity_version(scenario["opportunity_id"])
    invite_payload = {
        "opportunity_id": scenario["opportunity_id"],
        "hotel_id": hotel["id"],
        "rooms_peak_invited": 500,
        "expected_opportunity_version": observed_version,
    }
    refused = api_client.create_room_block_commitment(invite_payload, sales_manager_headers)
    validate_error(refused, ApiErrorId.ERR_HOTEL_NOT_PARTICIPATING.value, 409)

    reinstated = validate_success(
        api_client.set_hotel_participation(
            hotel["id"], {"participation_status": "PARTICIPATING"}, bureau_admin_headers
        )
    )
    assert reinstated["participation_status"] == "PARTICIPATING"
    assert reinstated["version"] == base_version + 2

    # The identical body, still quoting the version the client read before the
    # refusal, must now succeed: the rejected invite bumped nothing.
    accepted = validate_success(
        api_client.create_room_block_commitment(invite_payload, sales_manager_headers), 201
    )
    assert_room_block_commitment(accepted)
    assert accepted["status"] == "INVITED"
    assert accepted["rooms_peak_invited"] == 500

    hotel_after = fixtures.read_hotel(hotel["id"])
    assert hotel_after["committed_peak_rooms"] == 0, "an INVITED row commits no rooms"


def _expiry_run_world():
    """Five qualified leads, three halls, and four holds with staggered clocks."""
    fixtures.set_clock("2026-08-01T00:00:00Z")
    planner = fixtures.register_planner()
    halls = [
        fixtures.register_hall(name=name, exhibit_sqft=250_000,
                               capacity_persons=12_000, turnaround_hours=48)
        for name in ("Grand Hall A", "Grand Hall B", "Ballroom D")
    ]
    leads = []
    for index, peak in enumerate((900, 800, 700, 600, 500)):
        lead = fixtures.create_lead(
            planner["id"],
            event_name=f"Citywide Congress {index + 1}",
            arrival_date="2028-04-10",
            departure_date="2028-04-12",
            peak_rooms_requested=peak,
            total_room_nights_requested=900,
            attendance_estimate=4_000,
            exhibit_sqft_requested=100_000,
            rate_ceiling_amount=219.00,
        )
        leads.append(fixtures.qualify_lead(lead["id"]))

    # Grand Hall A: a FIRST hold with one SECOND queued behind it, both expiring
    # 90 days out (the SECOND copies the FIRST's expires_at).
    hold_1 = fixtures.place_hold(leads[0]["id"], halls[0]["id"])
    hold_2 = fixtures.place_hold(leads[1]["id"], halls[0]["id"])
    # Ballroom D: a lone FIRST hold with nothing waiting behind it.
    hold_5 = fixtures.place_hold(leads[4]["id"], halls[2]["id"])

    fixtures.set_clock("2026-09-20T00:00:00Z")
    hold_3 = fixtures.place_hold(leads[2]["id"], halls[1]["id"])
    hold_4 = fixtures.place_hold(leads[3]["id"], halls[1]["id"])
    challenged = fixtures.challenge_hold(hold_3["id"], hold_4["id"])
    return {
        "halls": halls,
        "leads": leads,
        "hold_1": hold_1,
        "hold_2": hold_2,
        "hold_3": hold_3,
        "hold_4": hold_4,
        "hold_5": hold_5,
        "challenged": challenged,
    }


def test_one_expiry_run_expires_two_holds_lapses_one_challenge_and_promotes_two(
    bureau_admin_headers, center_scheduler_headers
):
    """A single ops checkpoint reports expiries, lapsed challenges and promotions separately.

    PRD: "Every hold in status `HELD` whose `expires_at` is at or before the
    current logical clock moves to `EXPIRED` with `release_reason` `HOLD_EXPIRED`
    ... Every hold in status `CHALLENGED` whose `challenge_deadline` is strictly
    before the current logical clock moves to `RELEASED` with `release_reason`
    `CHALLENGE_LAPSED`" (PRD S3.4)
    PRD: "The checkpoint's own answer is a summary object rather than an entity:
    `expired_count` for holds that expired, `lapsed_challenge_count` for
    challenges that lapsed, `promoted_count` for holds promoted, and
    `promoted_space_hold_ids` listing the identifiers of the promoted holds." (PRD S3.4)

    Design: Corner/endpoints/one_expiry_run_expires_two_holds_lapses_a_challenge_and_promotes_two
    """
    world = _expiry_run_world()
    assert world["challenged"]["status"] == "CHALLENGED"
    assert same_instant(
        world["challenged"]["challenge_deadline"], "2026-10-04T00:00:00Z"
    ), "the challenge deadline is 14 days after the challenge was raised"

    fixtures.set_clock("2026-11-01T00:00:00Z")
    summary = get_success_data(api_client.run_space_hold_expiry(bureau_admin_headers))
    assert summary["expired_count"] == 2, (
        "the two 90-day FIRST holds on Grand Hall A and Ballroom D both lapsed"
    )
    assert summary["lapsed_challenge_count"] == 1, (
        "the CHALLENGED hold is counted only here, never also as an expiry"
    )
    assert summary["promoted_count"] == 2
    assert sorted(summary["promoted_space_hold_ids"]) == sorted(
        [world["hold_2"]["id"], world["hold_4"]["id"]]
    ), "exactly the two waiting SECOND holds were promoted"

    lapsed = fixtures.read_hold(world["hold_3"]["id"])
    assert lapsed["status"] == "RELEASED"
    assert lapsed["release_reason"] == "CHALLENGE_LAPSED"

    # The run processes by expires_at ascending, so hold_1 expires before hold_2
    # is examined; the promotion re-stamps hold_2 a fresh month from the clock.
    promoted_a = fixtures.read_hold(world["hold_2"]["id"])
    assert_space_hold(promoted_a)
    assert promoted_a["status"] == "HELD"
    assert promoted_a["hold_rank"] == "FIRST"
    assert same_instant(promoted_a["expires_at"], "2026-12-01T00:00:00Z"), (
        "a promoted hold gets 30 days from the current logical clock"
    )
    promoted_b = fixtures.read_hold(world["hold_4"]["id"])
    assert promoted_b["hold_rank"] == "FIRST"
    assert same_instant(promoted_b["expires_at"], "2026-12-01T00:00:00Z")

    _, expired_meta = validate_paginated(
        api_client.list_space_holds(center_scheduler_headers, params={"status": "EXPIRED"})
    )
    assert expired_meta["total_count"] == 2, "expiry lands in EXPIRED, not RELEASED"
    released, released_meta = validate_paginated(
        api_client.list_space_holds(center_scheduler_headers, params={"status": "RELEASED"})
    )
    assert released_meta["total_count"] == 1, "only the lapsed challenge is RELEASED"
    assert released[0]["id"] == world["hold_3"]["id"]

    ballroom = fixtures.read_hall(world["halls"][2]["id"])
    assert ballroom["confirmed_hold_count"] == 0, (
        "the lone hold on Ballroom D had no waiting SECOND, so nothing was promoted"
    )

    again = fixtures.run_expiry()
    assert again["expired_count"] == 0
    assert again["lapsed_challenge_count"] == 0
    assert again["promoted_count"] == 0
    assert again["promoted_space_hold_ids"] == []


def test_a_commitment_is_reachable_from_its_opportunity_and_from_its_hotel(
    sales_manager_headers, board_analyst_headers
):
    """The junction row answers to either parent filter, and the two filters compose.

    PRD: "Commitment listings are filterable by `opportunity_id`, by `hotel_id`
    and by `status`." (PRD S3.5)
    PRD: "Each invite bumps the opportunity's `version` by one" (PRD S3.5)

    Design: Corner/endpoints/commitment_is_a_junction_row_readable_from_both_of_its_parents
    """
    scenario = fixtures.setup_lead()
    hotel_a = scenario["hotels"][0]
    hotel_b = scenario["hotels"][1]

    second = fixtures.create_lead(
        scenario["planner_id"],
        event_name="CDA Summer Forum 2028",
        arrival_date="2028-06-05",
        departure_date="2028-06-07",
        peak_rooms_requested=400,
        total_room_nights_requested=700,
        attendance_estimate=3_000,
        exhibit_sqft_requested=50_000,
        rate_ceiling_amount=205.00,
    )
    second = fixtures.qualify_lead(second["id"])

    v1 = fixtures.opportunity_version(scenario["opportunity_id"])
    c_a1 = validate_success(
        api_client.create_room_block_commitment(
            {
                "opportunity_id": scenario["opportunity_id"],
                "hotel_id": hotel_a["id"],
                "rooms_peak_invited": 500,
                "expected_opportunity_version": v1,
            },
            sales_manager_headers,
        ),
        201,
    )
    v2 = fixtures.opportunity_version(scenario["opportunity_id"])
    assert v2 == v1 + 1
    c_b1 = validate_success(
        api_client.create_room_block_commitment(
            {
                "opportunity_id": scenario["opportunity_id"],
                "hotel_id": hotel_b["id"],
                "rooms_peak_invited": 400,
                "expected_opportunity_version": v2,
            },
            sales_manager_headers,
        ),
        201,
    )
    v3 = fixtures.opportunity_version(second["id"])
    c_a2 = validate_success(
        api_client.create_room_block_commitment(
            {
                "opportunity_id": second["id"],
                "hotel_id": hotel_a["id"],
                "rooms_peak_invited": 300,
                "expected_opportunity_version": v3,
            },
            sales_manager_headers,
        ),
        201,
    )
    assert len({c_a1["id"], c_b1["id"], c_a2["id"]}) == 3
    assert fixtures.opportunity_version(second["id"]) == v3 + 1, (
        "the third invite bumped only its own opportunity"
    )

    by_opportunity, opp_meta = validate_paginated(
        api_client.list_room_block_commitments(
            sales_manager_headers, params={"opportunity_id": scenario["opportunity_id"]}
        )
    )
    assert opp_meta["total_count"] == 2
    assert [row["id"] for row in by_opportunity] == [c_a1["id"], c_b1["id"]]

    by_hotel, hotel_meta = validate_paginated(
        api_client.list_room_block_commitments(
            board_analyst_headers, params={"hotel_id": hotel_a["id"]}
        )
    )
    assert hotel_meta["total_count"] == 2, (
        "one property serving two events keeps two independent junction rows"
    )
    assert [row["id"] for row in by_hotel] == [c_a1["id"], c_a2["id"]]

    composed, composed_meta = validate_paginated(
        api_client.list_room_block_commitments(
            sales_manager_headers,
            params={"opportunity_id": second["id"], "hotel_id": hotel_a["id"]},
        )
    )
    assert composed_meta["total_count"] == 1
    assert composed[0]["id"] == c_a2["id"]

    assert fixtures.read_hotel(hotel_a["id"])["committed_peak_rooms"] == 0, (
        "invitations are not commitments, not even in aggregate across two events"
    )


def test_one_opportunity_read_reconciles_the_whole_derived_snapshot_after_definite(
    sales_manager_headers, board_analyst_headers
):
    """A single read after acceptance shows coverage, cutoffs, frozen nights and zero attrition.

    PRD: "`committed_peak_rooms` on the opportunity is the sum of
    `rooms_peak_committed`; `block_coverage_pct` is that committed peak multiplied
    by 100 and divided by `peak_rooms_requested`, rounded half-up to two decimals;
    `citywide_cutoff_days_before_arrival` is the largest
    `cutoff_days_before_arrival` among the committed properties ... and
    `cutoff_alignment_spread_days` is the largest such value minus the smallest"
    (PRD S3.5)
    PRD: "the lead's `sales_stage` moves from `BIDDING` to `DEFINITE`, its
    `definite_at` is stamped from the logical clock, and its
    `definite_room_nights` is frozen at `committed_peak_rooms` multiplied by
    `event_nights`" (PRD S3.7)

    Design: Corner/endpoints/opportunity_read_reflects_the_whole_derived_snapshot_after_definite
    """
    scenario = fixtures.setup_definite_lead()
    bid = validate_success(
        api_client.get_bid_package(scenario["bid_id"], sales_manager_headers)
    )
    assert_bid_package(bid)
    assert bid["status"] == "ACCEPTED"

    opportunity = validate_success(
        api_client.get_opportunity(scenario["opportunity_id"], board_analyst_headers)
    )
    assert_opportunity(opportunity)
    assert opportunity["sales_stage"] == "DEFINITE"
    assert opportunity["hold_posture"] == "CONFIRMED"
    assert opportunity["committed_peak_rooms"] == 900, "500 + 300 + 100 committed peak rooms"
    assert_money_equals(opportunity["block_coverage_pct"], 90.00, "block_coverage_pct")
    assert opportunity["citywide_cutoff_days_before_arrival"] == 30
    assert opportunity["cutoff_alignment_spread_days"] == 0, (
        "all three properties cut off 30 days out, so largest minus smallest is 0"
    )
    assert opportunity["event_nights"] == 2
    assert opportunity["definite_room_nights"] == 1800, (
        "committed_peak_rooms 900 multiplied by event_nights 2"
    )
    assert same_instant(opportunity["definite_at"], "2027-03-01T00:00:00Z")
    assert_money_equals(
        opportunity["attrition_settlement_amount"], 0.00, "attrition_settlement_amount"
    )

    committed, committed_meta = validate_paginated(
        api_client.list_room_block_commitments(
            sales_manager_headers,
            params={"opportunity_id": scenario["opportunity_id"], "status": "COMMITTED"},
        )
    )
    assert committed_meta["total_count"] == 3
    assert committed[0]["cutoff_date"] == "2028-03-11", (
        "cutoff_date is arrival 2028-04-10 less 30 days"
    )

    planner = validate_success(
        api_client.get_meeting_planner(scenario["planner_id"], sales_manager_headers)
    )
    assert_meeting_planner(planner)
    assert planner["definite_count"] == 1, (
        "definite_count counts only this planner's own DEFINITE-or-SERVICED "
        "opportunities; the migrated legacy counters feed the scores, not this counter"
    )
    assert planner["lifetime_definite_room_nights"] == 7800, "legacy 6000 plus 1800"
    assert planner["tier"] == "TIER_B"
    assert planner["engagement_status"] == "ENGAGED", (
        "engagement_status flips to ENGAGED at first qualification and never flips back"
    )


def _revise_and_resubmit(scenario, response_due_at, amount=12_000.00):
    """One full negotiation round: revision request, re-request, re-approve, re-submit."""
    fixtures.answer_bid(scenario["bid_id"], scenario["planner_id"], "REVISION_REQUESTED")
    fixtures.ask_for_incentive(scenario["bid_id"], amount)
    fixtures.decide_incentive(
        scenario["bid_id"], scenario["fund_id"], "APPROVED", amount
    )
    fixtures.submit_bid(scenario["bid_id"], response_due_at)
    return fixtures.read_bid(scenario["bid_id"])


def test_a_revision_request_at_round_three_declines_the_bid_and_loses_the_lead(
    sales_manager_headers, center_scheduler_headers, incentive_approver_headers
):
    """At round 3 the same revision request terminates the ladder instead of looping.

    PRD: "When, however, a revision is requested while `round_number` already
    equals 3, the ladder terminates instead of looping: the package moves from
    `SUBMITTED` to `DECLINED` with `decline_reason` `REVISION_LIMIT_REACHED`, and
    the lead moves from `BIDDING` to `LOST` with `lost_reason`
    `REVISION_LIMIT_REACHED` plus the full lost cascade" (PRD S3.8)
    PRD: "Any live fund charge is decommitted: the fund's `committed_amount` falls
    by the package's `total_fund_charge_amount`, `uncommitted_amount` rises by the
    same amount, and `posture` is re-derived." (PRD S3.8)

    Design: Corner/endpoints/a_revision_request_at_round_three_declines_instead_of_reopening
    """
    scenario = fixtures.setup_bid_submitted()
    _revise_and_resubmit(scenario, "2027-05-01T00:00:00Z")
    third = _revise_and_resubmit(scenario, "2027-06-01T00:00:00Z")
    assert third["round_number"] == 3
    assert third["status"] == "SUBMITTED"

    # The clock stays inside the response window: the PRD imposes the
    # response_due_at gate on every verdict, terminal branch included.
    final = validate_success(
        api_client.planner_response(
            scenario["bid_id"],
            {"response": "REVISION_REQUESTED"},
            make_meeting_planner_headers(scenario["planner_id"]),
        )
    )
    assert final["status"] == "DECLINED"
    assert final["decline_reason"] == "REVISION_LIMIT_REACHED"
    assert final["round_number"] == 3, "the counter is not incremented past the maximum"

    opportunity = fixtures.read_opportunity(scenario["opportunity_id"])
    assert opportunity["sales_stage"] == "LOST"
    assert opportunity["lost_reason"] == "REVISION_LIMIT_REACHED"
    assert opportunity["hold_posture"] == "RELEASED"
    assert_money_equals(opportunity["block_coverage_pct"], 0.00, "block_coverage_pct")
    assert opportunity["committed_peak_rooms"] == 0

    hold = validate_success(
        api_client.get_space_hold(scenario["hold_id"], center_scheduler_headers)
    )
    assert hold["status"] == "RELEASED"
    assert hold["release_reason"] == "OPPORTUNITY_LOST"
    assert fixtures.read_hall(scenario["hall_id"])["confirmed_hold_count"] == 0

    fund = validate_success(
        api_client.get_incentive_fund(scenario["fund_id"], incentive_approver_headers)
    )
    assert_money_equals(fund["committed_amount"], 0.00, "committed_amount")
    assert_money_equals(fund["uncommitted_amount"], 500_000.00, "uncommitted_amount")
    assert_money_equals(fund["budget_amount"], 500_000.00, "budget_amount")
    assert fund["posture"] == "OPEN", "the third round's charge is decommitted by the loss"

    planner = fixtures.read_planner(scenario["planner_id"])
    assert planner["lost_count"] == 1
    assert planner["relationship_score_lifetime"] == 31, (
        "legacy 2 definites give 24 points, legacy 6000 room nights give 12, "
        "and the single loss subtracts 5"
    )


# =============================================================================
# Section `errors`
# =============================================================================

@pytest.mark.parametrize(
    "getter,expected_error_id",
    [
        ("get_hotel", ApiErrorId.ERR_HOTEL_NOT_FOUND),
        ("get_center_hall", ApiErrorId.ERR_HALL_NOT_FOUND),
        ("get_room_block_commitment", ApiErrorId.ERR_COMMITMENT_NOT_FOUND),
        ("get_incentive_fund", ApiErrorId.ERR_FUND_NOT_FOUND),
        ("get_servicing_order", ApiErrorId.ERR_SERVICING_ORDER_NOT_FOUND),
        ("get_board_report", ApiErrorId.ERR_BOARD_REPORT_NOT_FOUND),
    ],
    ids=["hotel", "hall", "commitment", "fund", "servicing_order", "board_report"],
)
def test_each_resource_kind_answers_an_unknown_id_with_its_own_not_found_code(
    bureau_admin_headers, getter, expected_error_id
):
    """Six resource families each answer an unknown path id with their own 404 code.

    PRD: "Each resource kind has its own dedicated not-found code, all carrying
    HTTP 404: `ERR_PLANNER_NOT_FOUND`, `ERR_HOTEL_NOT_FOUND`,
    `ERR_HALL_NOT_FOUND`, `ERR_OPPORTUNITY_NOT_FOUND`,
    `ERR_SPACE_HOLD_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`,
    `ERR_BID_PACKAGE_NOT_FOUND`, `ERR_FUND_NOT_FOUND`,
    `ERR_SERVICING_ORDER_NOT_FOUND` and `ERR_BOARD_REPORT_NOT_FOUND`." (PRD S2.7)

    Design: Corner/errors/every_remaining_resource_type_has_its_own_not_found_code
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    response = getattr(api_client, getter)(NON_EXISTENT_UUID, bureau_admin_headers)
    validate_error(response, expected_error_id.value, 404)


def test_an_unknown_hotel_in_the_body_beats_a_stale_opportunity_version(
    sales_manager_headers
):
    """The dangling body foreign key answers 404 even though the same body is also stale.

    PRD: "6. Every foreign key in the body resolving — the matching 404 code, on
    every creation that carries a foreign key. 7. `expected_opportunity_version`
    equal to the target opportunity's `version` — `ERR_STALE_OPPORTUNITY_VERSION`,
    412, on bid-package creation and room-block-commitment creation." (PRD S2.7)
    PRD: "the rule with the lowest position in the following ladder wins, and the
    request carries that rule's error code" (PRD S2.7)

    Design: Corner/errors/unknown_body_fks_resolve_before_the_stale_version_check
    """
    scenario = fixtures.setup_lead()
    hotel_a = scenario["hotels"][0]
    stale_version = fixtures.opportunity_version(scenario["opportunity_id"])

    # A second invite bumps the opportunity's version, making the token stale.
    fixtures.invite_hotel(
        scenario["opportunity_id"], scenario["hotels"][1]["id"], rooms_peak_invited=400
    )

    both_defects = api_client.create_room_block_commitment(
        {
            "opportunity_id": scenario["opportunity_id"],
            "hotel_id": NON_EXISTENT_UUID,
            "rooms_peak_invited": 500,
            "expected_opportunity_version": stale_version,
        },
        sales_manager_headers,
    )
    validate_error(both_defects, ApiErrorId.ERR_HOTEL_NOT_FOUND.value, 404)

    only_stale = api_client.create_room_block_commitment(
        {
            "opportunity_id": scenario["opportunity_id"],
            "hotel_id": hotel_a["id"],
            "rooms_peak_invited": 500,
            "expected_opportunity_version": stale_version,
        },
        sales_manager_headers,
    )
    validate_error(only_stale, ApiErrorId.ERR_STALE_OPPORTUNITY_VERSION.value, 412)

    _, meta = validate_paginated(
        api_client.list_room_block_commitments(
            sales_manager_headers, params={"opportunity_id": scenario["opportunity_id"]}
        )
    )
    assert meta["total_count"] == 1, "neither refused invite created a commitment row"


def test_an_unknown_fund_in_the_body_beats_a_stale_fund_version(incentive_approver_headers):
    """The decision's dangling fund_id answers 404 ahead of the stale fund version.

    PRD: "6. Every foreign key in the body resolving — the matching 404 code, on
    every creation that carries a foreign key. ... 8. `expected_fund_version`
    equal to the target fund's `version` — `ERR_STALE_FUND_VERSION`, 412, on
    incentive-decision creation." (PRD S2.7)
    PRD: "`fund_id` ... must all resolve to live rows, and a dangling reference
    returns the not-found code of the referenced kind." (PRD S2.7)

    Design: Corner/errors/unknown_body_fks_resolve_before_the_stale_version_check
    """
    scenario = fixtures.setup_bid_incentive_pending()
    stale_fund_version = fixtures.fund_version(scenario["fund_id"])
    # A receipt credit bumps the fund's version, so the captured token is stale.
    fixtures.post_receipt(scenario["fund_id"], 1_000.00, "2027-02-01T00:00:00Z")

    response = api_client.create_incentive_decision(
        scenario["bid_id"],
        incentive_decision_payload(
            NON_EXISTENT_UUID, "APPROVED", 12_000.00, stale_fund_version
        ),
        make_incentive_approver_headers(INCENTIVE_APPROVER_USER_ID),
    )
    validate_error(response, ApiErrorId.ERR_FUND_NOT_FOUND.value, 404)

    _, meta = validate_paginated(
        api_client.list_bid_incentive_decisions(
            scenario["bid_id"], incentive_approver_headers
        )
    )
    assert meta["total_count"] == 0, "the refused decision recorded no row"
    assert fixtures.read_bid(scenario["bid_id"])["status"] == "INCENTIVE_PENDING"


def test_a_rejected_create_returns_the_bare_error_envelope_and_stores_nothing(
    sales_manager_headers
):
    """A schema violation returns response_type error with exactly error_id and message.

    PRD: "Request-body schema conformance — `ERR_VALIDATION`, 400, on every
    endpoint. This covers ... `arrival_date` being strictly earlier than
    `departure_date`" (PRD S2.7)
    PRD: "The `meta` object for error responses contains only `api_request_id`
    and `api_request_timestamp`." / "The `message` provides a human-readable
    explanation of what went wrong." (PRD S2.2, whose error envelope shows
    `response_type` `error` with `data` holding only `error_id` and `message`)

    Design: Corner/errors/error_envelope_carries_only_error_id_and_message
    """
    scenario = fixtures.setup_inventory()

    response = api_client.create_opportunity(
        {
            "planner_id": scenario["planner_id"],
            "event_name": "Reversed Dates 2028",
            "arrival_date": "2028-04-12",
            "departure_date": "2028-04-10",
            "peak_rooms_requested": 500,
            "total_room_nights_requested": 900,
            "attendance_estimate": 4_000,
            "exhibit_sqft_requested": 100_000,
            "rate_ceiling_amount": 219.00,
        },
        sales_manager_headers,
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)
    assert_error_envelope_shape(response)
    body = response.json()
    assert isinstance(body["data"]["message"], str) and body["data"]["message"], (
        "the envelope carries a non-empty human-readable message"
    )

    _, meta = validate_paginated(api_client.list_opportunities(sales_manager_headers))
    assert meta["total_count"] == 0, "the rejected create left no row behind"


# =============================================================================
# Section `rbac`
# =============================================================================

@pytest.mark.parametrize(
    "defect",
    ["role_header_omitted", "role_header_blank", "role_header_undeclared",
     "user_id_header_omitted"],
)
def test_every_authentication_header_defect_returns_the_same_unauthenticated(defect):
    """A missing, blank or undeclared role header and a missing user id are all 401.

    PRD: "1. Both authentication headers present, non-empty, and `X-User-Role`
    naming a declared role — `ERR_UNAUTHENTICATED`, 401, on every endpoint."
    (PRD S2.7)
    PRD: "2. The acting role authorized for the called endpoint —
    `ERR_UNAUTHORIZED`, 403, on every endpoint." (PRD S2.7)

    Design: Corner/rbac/missing_blank_and_undeclared_role_headers_all_return_unauthenticated
    """
    scenario = fixtures.setup_lead()
    # "Blank" is the empty string, never whitespace.
    headers = {
        "role_header_omitted": lambda: headers_without_role(SALES_MANAGER_USER_ID),
        "role_header_blank": lambda: headers_with_blank_role(SALES_MANAGER_USER_ID),
        "role_header_undeclared": lambda: headers_with_undeclared_role(
            SALES_MANAGER_USER_ID
        ),
        "user_id_header_omitted": lambda: headers_without_user_id("SalesManager"),
    }[defect]()

    response = api_client.get_opportunity(scenario["opportunity_id"], headers)
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    assert_error_envelope_shape(response)


def test_a_blank_user_id_is_unauthenticated_rather_than_unauthorized():
    """An empty X-User-ID fails authentication even beside a legal role header.

    PRD: "1. Both authentication headers present, non-empty, and `X-User-Role`
    naming a declared role — `ERR_UNAUTHENTICATED`, 401, on every endpoint."
    (PRD S2.7)

    Design: Corner/rbac/missing_blank_and_undeclared_role_headers_all_return_unauthenticated
    """
    scenario = fixtures.setup_lead()
    response = api_client.get_opportunity(
        scenario["opportunity_id"], headers_with_blank_user_id("SalesManager")
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def _rbac_probe_world():
    """One world in which each of the eight probed writes has a rightful role."""
    scenario = fixtures.setup_bid_incentive_pending()

    # A fourth property, invited and OFFERED, so the commit probe is a request
    # that would succeed for its rightful SalesManager.
    riverside = fixtures.register_hotel(
        name="Riverside Court", committable_rooms=200, walk_distance_blocks=8
    )
    offered = fixtures.invite_hotel(
        scenario["opportunity_id"], riverside["id"], rooms_peak_invited=100
    )
    fixtures.offer_block(offered["id"], riverside["id"], 100, 199.00, 30)

    # A second lead still in LEAD stage, and a DRAFT board report.
    second = fixtures.create_lead(
        scenario["planner_id"],
        event_name="CDA Autumn Congress 2028",
        arrival_date="2028-09-10",
        departure_date="2028-09-12",
        peak_rooms_requested=400,
        total_room_nights_requested=700,
        attendance_estimate=3_000,
        exhibit_sqft_requested=50_000,
        rate_ceiling_amount=205.00,
    )
    report = fixtures.create_report("2027-01-01", "2027-06-30")

    scenario["riverside_id"] = riverside["id"]
    scenario["offered_commitment_id"] = offered["id"]
    scenario["opp2_id"] = second["id"]
    scenario["report_id"] = report["id"]
    scenario["fund_v"] = fixtures.fund_version(scenario["fund_id"])
    return scenario


def _probe_admin_qualifies(world):
    return api_client.qualify_opportunity(world["opp2_id"], ADMIN)


def _check_second_lead_untouched(world):
    assert fixtures.read_opportunity(world["opp2_id"])["sales_stage"] == "LEAD"


def _probe_sales_places_a_hold(world):
    # The second lead is still in LEAD stage, so this body also violates the
    # stage gate -- ladder position 2 guarantees that rule is never reached.
    return api_client.create_space_hold(
        {
            "opportunity_id": world["opp2_id"],
            "center_hall_id": world["hall_id"],
            "move_in_start": "2028-09-08T00:00:00Z",
            "move_out_end": "2028-09-13T00:00:00Z",
        },
        SALES,
    )


def _check_no_hold_for_the_second_lead(world):
    _, meta = validate_paginated(
        api_client.list_space_holds(SCHEDULER, params={"opportunity_id": world["opp2_id"]})
    )
    assert meta["total_count"] == 0


def _probe_hotel_commits_the_block(world):
    return api_client.commit_room_block_commitment(
        world["offered_commitment_id"], make_hotel_partner_headers(world["riverside_id"])
    )


def _check_offered_commitment_untouched(world):
    commitment = fixtures.read_commitment(world["offered_commitment_id"])
    assert commitment["status"] == "OFFERED"
    assert commitment["rooms_peak_committed"] == 0


def _probe_sales_decides_the_incentive(world):
    # Sales is also barred by segregation of duties at ladder position 15; the
    # role check at position 2 answers first.
    return api_client.create_incentive_decision(
        world["bid_id"],
        incentive_decision_payload(
            world["fund_id"], "APPROVED", 12_000.00, world["fund_v"]
        ),
        SALES,
    )


def _check_no_decision_and_fund_untouched(world):
    _, meta = validate_paginated(
        api_client.list_bid_incentive_decisions(world["bid_id"], APPROVER)
    )
    assert meta["total_count"] == 0
    assert fixtures.fund_version(world["fund_id"]) == world["fund_v"]


def _probe_analyst_opens_a_servicing_order(world):
    # The lead is not DEFINITE yet either; the role check answers first.
    return api_client.create_servicing_order(
        {
            "opportunity_id": world["opportunity_id"],
            "category": "HOUSING",
            "requested_units": 900,
            "window_start": "2028-04-08T00:00:00Z",
            "window_end": "2028-04-13T00:00:00Z",
        },
        ANALYST,
    )


def _check_no_servicing_order(world):
    _, meta = validate_paginated(
        api_client.list_opportunity_servicing_orders(world["opportunity_id"], SERVICES)
    )
    assert meta["total_count"] == 0


def _probe_services_publishes_the_report(world):
    return api_client.publish_board_report(world["report_id"], SERVICES)


def _check_report_still_draft(world):
    report = validate_success(api_client.get_board_report(world["report_id"], ANALYST))
    assert report["status"] == "DRAFT"


def _probe_approver_submits_the_bid(world):
    # The package is INCENTIVE_PENDING rather than APPROVED; the role check
    # at ladder position 2 answers before that state gate.
    return api_client.submit_bid_package(
        world["bid_id"], {"response_due_at": "2027-05-01T00:00:00Z"}, APPROVER
    )


def _check_bid_still_incentive_pending(world):
    bid = fixtures.read_bid(world["bid_id"])
    assert bid["status"] == "INCENTIVE_PENDING"
    assert bid["submitted_at"] is None


def _probe_planner_releases_the_hold(world):
    return api_client.release_space_hold(
        world["hold_id"], make_meeting_planner_headers(world["planner_id"])
    )


def _check_hold_still_held(world):
    hold = fixtures.read_hold(world["hold_id"])
    assert hold["status"] == "HELD"
    assert hold["release_reason"] is None


RBAC_PROBES = [
    ("bureau_admin_cannot_qualify", _probe_admin_qualifies, _check_second_lead_untouched),
    ("sales_manager_cannot_hold_space", _probe_sales_places_a_hold,
     _check_no_hold_for_the_second_lead),
    ("hotel_partner_cannot_commit", _probe_hotel_commits_the_block,
     _check_offered_commitment_untouched),
    ("sales_manager_cannot_decide", _probe_sales_decides_the_incentive,
     _check_no_decision_and_fund_untouched),
    ("board_analyst_cannot_open_servicing", _probe_analyst_opens_a_servicing_order,
     _check_no_servicing_order),
    ("services_manager_cannot_publish", _probe_services_publishes_the_report,
     _check_report_still_draft),
    ("incentive_approver_cannot_submit", _probe_approver_submits_the_bid,
     _check_bid_still_incentive_pending),
    ("meeting_planner_cannot_release", _probe_planner_releases_the_hold,
     _check_hold_still_held),
]


@pytest.mark.parametrize(
    "probe,checker",
    [(probe, checker) for (_, probe, checker) in RBAC_PROBES],
    ids=[name for (name, _, _) in RBAC_PROBES],
)
def test_each_exclusive_write_is_refused_to_a_role_that_does_not_hold_it(probe, checker):
    """Eight otherwise-valid writes are each refused to a role outside the endpoint's list.

    PRD: "2. The acting role authorized for the called endpoint —
    `ERR_UNAUTHORIZED`, 403, on every endpoint." (PRD S2.7)
    PRD: "Each endpoint in Section 4 lists the roles authorized to call it; a
    well-authenticated caller whose role is not on that list is rejected with
    `ERR_UNAUTHORIZED` and HTTP 403." (PRD S2.1)

    Design: Corner/rbac/each_roles_exclusive_write_is_refused_to_the_other_seven_roles
    """
    world = _rbac_probe_world()
    response = probe(world)
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    assert_error_envelope_shape(response)
    checker(world)


def test_a_hotel_partner_cannot_report_pickup_against_another_propertys_commitment():
    """The right role on the wrong property is ERR_NOT_RESOURCE_OWNER, yet may still read.

    PRD: "a hotel partner may answer, withdraw from, or report nightly pickup
    against a room block commitment only when that commitment's `hotel_id` equals
    the caller's `X-User-ID`." (PRD S2.1)
    PRD: "This ownership check guards exactly four operations: the hotel's offer on
    a commitment, the hotel's withdrawal from a commitment, the hotel's nightly
    pickup reporting on a commitment, and the planner's response to a submitted bid
    package. No other operation performs an ownership comparison." (PRD S2.1)

    Design: Corner/rbac/entity_backed_roles_cannot_act_for_a_property_or_planner_they_do_not_own
    """
    scenario = fixtures.setup_bid_submitted()
    owner = fixtures.register_hotel(
        name="Riverside Court", committable_rooms=200, walk_distance_blocks=8
    )
    commitment = fixtures.invite_hotel(
        scenario["opportunity_id"], owner["id"], rooms_peak_invited=100
    )
    fixtures.offer_block(commitment["id"], owner["id"], 100, 199.00, 30)
    stranger = scenario["hotels"][1]

    refused = api_client.create_pickup_record(
        commitment["id"],
        pickup_record_payload("2028-04-10", 100, 214.33),
        make_hotel_partner_headers(stranger["id"]),
    )
    validate_error(refused, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    # Reads are not owner-scoped: the same non-owning partner may still look.
    readable = validate_success(
        api_client.get_room_block_commitment(
            commitment["id"], make_hotel_partner_headers(stranger["id"])
        )
    )
    assert readable["status"] == "OFFERED"
    assert readable["hotel_id"] == owner["id"]

    _, meta = validate_paginated(
        api_client.list_pickup_records(
            commitment["id"], make_hotel_partner_headers(owner["id"])
        )
    )
    assert meta["total_count"] == 0, "the refused report recorded no pickup row"


def test_a_rival_planner_cannot_answer_a_bid_that_names_another_planner():
    """The wrong planner is refused, and the rightful planner can still accept.

    PRD: "a planner may answer a bid package only when the `planner_id` of the
    opportunity behind that bid package equals the caller's `X-User-ID`." (PRD S2.1)
    PRD: "Ownership violations return `ERR_NOT_RESOURCE_OWNER` with HTTP 403."
    (PRD S2.1)

    Design: Corner/rbac/entity_backed_roles_cannot_act_for_a_property_or_planner_they_do_not_own
    """
    scenario = fixtures.setup_bid_submitted()
    rival = fixtures.register_planner(
        org_name="Rival Society", contact_email="meetings@rival.org"
    )

    refused = api_client.planner_response(
        scenario["bid_id"],
        {"response": "ACCEPTED"},
        make_meeting_planner_headers(rival["id"]),
    )
    validate_error(refused, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
    assert fixtures.read_bid(scenario["bid_id"])["status"] == "SUBMITTED"

    accepted = validate_success(
        api_client.planner_response(
            scenario["bid_id"],
            {"response": "ACCEPTED"},
            make_meeting_planner_headers(scenario["planner_id"]),
        )
    )
    assert accepted["status"] == "ACCEPTED", (
        "the refusal was identity-based and left the bid answerable"
    )


def test_neither_the_preparer_nor_the_requester_may_decide_the_same_package(
    incentive_approver_headers
):
    """Both recorded sales identities are barred from deciding, and a third officer is not.

    PRD: "the decision records that approver's `X-User-ID` as
    `decided_by_user_id`, and that value must differ from **both** captured
    identifiers. If it equals either one, the decision is refused with
    `ERR_SEGREGATION_OF_DUTIES` and HTTP 403" (PRD S2.11)
    PRD: "Segregation of duties, described in Section 2.11, is checked before any
    money question is asked." (PRD S3.7)

    Design: Corner/rbac/neither_the_preparer_nor_the_requester_may_decide_the_same_package
    """
    scenario = fixtures.setup_block_assembled()
    preparer = make_sales_manager_headers("sales-11")
    requester = make_sales_manager_headers("sales-22")

    bid = fixtures.open_bid(scenario["opportunity_id"], headers=preparer)
    fixtures.attach_letters(bid["id"])
    fixtures.ask_for_incentive(bid["id"], 12_000.00, headers=requester)

    pending = fixtures.read_bid(bid["id"])
    assert pending["status"] == "INCENTIVE_PENDING"
    assert pending["prepared_by_user_id"] == "sales-11"
    assert pending["incentive_requested_by_user_id"] == "sales-22"
    assert_money_equals(
        pending["incentive_cap_amount"], 13_304.25, "incentive_cap_amount"
    )

    fund_v = fixtures.fund_version(scenario["fund_id"])
    payload = incentive_decision_payload(
        scenario["fund_id"], "APPROVED", 12_000.00, fund_v
    )

    as_preparer = api_client.create_incentive_decision(
        bid["id"], payload, make_incentive_approver_headers("sales-11")
    )
    validate_error(as_preparer, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    as_requester = api_client.create_incentive_decision(
        bid["id"], payload, make_incentive_approver_headers("sales-22")
    )
    validate_error(as_requester, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    # The same fund version token still works, so neither refusal touched the fund.
    decision = validate_success(
        api_client.create_incentive_decision(
            bid["id"], payload, make_incentive_approver_headers(INCENTIVE_APPROVER_USER_ID)
        ),
        201,
    )
    assert_incentive_decision(decision)
    assert decision["decided_by_user_id"] == INCENTIVE_APPROVER_USER_ID
    assert_money_equals(decision["total_charge_amount"], 12_600.00, "total_charge_amount")
    assert fixtures.read_bid(bid["id"])["status"] == "APPROVED"
