"""State-machine cycles, cash conservation, and the remaining edge cases.

Covers the genuine cycles the machines contain (the offering's return to
`ALLOCATED` after a below-reserve execution, and the subscription withdrawal
that must leave the offering's cash ledger exactly where it was), the ordering
of the eligibility screen's refusals, and a few corners of the resource surface.
"""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    make_investor_headers, make_issuer_ops_headers,
    assert_artwork, assert_offering, assert_offering_invariants,
    TEST_USERS, NON_EXISTENT_UUID,
)
from test_helpers.fixtures import (
    set_clock, create_artist, create_artwork, create_investor, create_offering,
    create_screened_subscription, create_holding_decision_payload,
    file_appraisal, file_verified_authentication, file_verified_provenance,
    file_circular, allocate_offering, collect_funds, open_platform_account,
    get_artwork, get_offering, get_platform_account, offering_version, artwork_version,
    approve_decision, execute_sale, setup_held_offering,
    setup_authenticated_artwork, setup_filed_offering,
)

ISSUER = TEST_USERS["issuer_ops_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]

PROPOSER = "ops-desk-11"
APPROVER = "ops-desk-12"


# ── The offering's ALLOCATED -> SALE_PENDING -> ALLOCATED cycle ──────────────

def _sale_ready_offering(proposed_gross_cents=90_000_000):
    """A HELD, insured offering whose clock has run out, with an approved SELL
    decision, so the offering is at SALE_PENDING."""
    set_clock("2026-08-01T00:00:00Z")
    artist = create_artist()
    artwork = create_artwork(artist["id"], acquisition_cost_cents=60_000_000,
                             reserve_price_cents=100_000_000)
    file_verified_provenance(artwork["id"])
    file_verified_authentication(artwork["id"])
    validate_success(file_appraisal(artwork["id"], 90_000_000), 201)
    offering = create_offering(artwork["id"], total_shares=40_000,
                               price_per_share_cents=1_500, registration_cap_pct=5_000,
                               liquidity_ratio_bps=1_000, hold_period_days=176)
    investor = create_investor()
    create_screened_subscription(offering["id"], investor["id"], requested_shares=20000)
    validate_success(file_circular(offering["id"]), 200)
    validate_success(allocate_offering(offering["id"]), 200)

    from test_helpers.fixtures import create_custody_record, receive_custody
    custody = create_custody_record(offering["id"])
    set_clock("2027-01-05T00:00:00Z")
    validate_success(receive_custody(custody["id"], offering["id"]), 200)

    set_clock("2027-06-30T00:00:00Z")
    decision = validate_success(api_client.create_holding_decision(
        offering["id"],
        create_holding_decision_payload(decision_type="SELL",
                                        proposed_gross_cents=proposed_gross_cents),
        make_issuer_ops_headers(PROPOSER)), 201)
    validate_success(
        api_client.approve_decision(
            decision["id"],
            {"expected_offering_version": offering_version(offering["id"])},
            make_issuer_ops_headers(APPROVER)), 200)
    return (get_artwork(artwork["id"]), get_offering(offering["id"]),
            validate_success(api_client.get_holding_decision(decision["id"], ISSUER), 200))


def test_a_below_reserve_execution_cycles_the_offering_back_to_allocated(api):
    """PRD 3.8: "Proceeds strictly below the reserve are declined: the decision moves to
    terminal `FAILED`, the offering reverts to `ALLOCATED`, the artwork reverts to
    `HELD`, and no distribution is created — the pair of entities rolls back together
    and the offering is available to be sold another day."

    Design: Difficulty/non_linear_state_machine/offering_cycles_allocated_held_sale_pending_and_back
    """
    artwork, offering, decision = _sale_ready_offering()
    assert offering["status"] == "SALE_PENDING"

    res = execute_sale(decision["id"], offering["id"], 99_000_000)
    failed = validate_success(res, 200)
    assert failed["status"] == "FAILED"

    assert get_offering(offering["id"])["status"] == "ALLOCATED"
    assert get_artwork(artwork["id"])["status"] == "HELD"
    assert get_success_data(api_client.list_distributions(offering["id"], ISSUER)) == []


def test_the_cycle_back_to_allocated_does_not_restart_the_holding_clock(api):
    """PRD 3.8: "the offering reverts to `ALLOCATED`, the artwork reverts to `HELD`" —
    the offer clock it already had is retained across the cycle.

    Design: Difficulty/non_linear_state_machine/offering_cycles_allocated_held_sale_pending_and_back
    """
    artwork, offering, decision = _sale_ready_offering()
    clock_before = get_offering(offering["id"])

    execute_sale(decision["id"], offering["id"], 99_000_000)

    after = get_offering(offering["id"])
    assert after["status"] == "ALLOCATED"
    assert after["holding_clock_started_at"] == clock_before["holding_clock_started_at"]
    assert after["holding_period_end_at"] == clock_before["holding_period_end_at"]
    assert after["holding_period_end_at"] == "2027-06-30T00:00:00Z"


# ── Cash conservation across the withdrawal ──────────────────────────────────

def _filed_offering_with_collected_funds(amounts):
    """A filed offering whose rescission window is still open, with one screened
    and funded subscription per amount. Returns (offering, subscriptions, account)."""
    set_clock("2026-09-01T00:00:00Z")
    account = open_platform_account()
    artist = create_artist()
    artwork = create_artwork(artist["id"], acquisition_cost_cents=60_000_000,
                             reserve_price_cents=100_000_000)
    file_verified_provenance(artwork["id"])
    file_verified_authentication(artwork["id"])
    offering = create_offering(artwork["id"], total_shares=40_000,
                               price_per_share_cents=1_500, registration_cap_pct=2_000,
                               liquidity_ratio_bps=1_000, hold_period_days=182)
    subs = []
    for i, amount in enumerate(amounts):
        investor = create_investor(email=f"sub{i}@x.com", legal_name=f"Subscriber {i}")
        sub = create_screened_subscription(offering["id"], investor["id"],
                                           requested_shares=amount // 1_500)
        collect_funds(sub["id"], amount)
        sub["investor_id"] = investor["id"]
        subs.append(sub)
    validate_success(file_circular(offering["id"]), 200)
    return get_offering(offering["id"]), subs, account


def test_rescinding_a_subscribed_position_refunds_the_collected_funds(api):
    """PRD 3.5: "An investor may rescind a subscribed position inside the rescission
    window: the acting investor must be the subscription's own `investor_id`, the
    offering must be in `DRAFT` or `QUALIFICATION_FILED`, and the current clock instant
    must be no later than `circular_filed_at` plus three days. Rescission moves the
    subscription to terminal `WITHDRAWN`, sets `refunded_cents` to
    `collected_subscription_cents`, and recomputes the offering's `accepted_shares` and
    `cash_ledger_cents`."

    Design: Difficulty/compensating_invariant/subscription_withdrawal_restores_the_offering_cash_ledger_exactly
    """
    offering, subs, account = _filed_offering_with_collected_funds([30_000_000, 15_000_000])
    assert get_offering(offering["id"])["cash_ledger_cents"] == 45_000_000

    set_clock("2026-09-02T00:00:00Z")
    validate_success(api_client.withdraw_subscription(
        subs[0]["id"], {}, make_investor_headers(subs[0]["investor_id"])), 200)

    first = validate_success(api_client.get_subscription(subs[0]["id"], COMPLIANCE), 200)
    assert first["status"] == "WITHDRAWN"
    assert first["refunded_cents"] == 30_000_000


def test_the_offering_cash_ledger_falls_by_exactly_the_refunded_amount(api):
    """PRD 3.5: "Rescission moves the subscription to terminal `WITHDRAWN`, sets
    `refunded_cents` to `collected_subscription_cents`, and recomputes the offering's
    `accepted_shares` and `cash_ledger_cents`."

    Design: Difficulty/compensating_invariant/subscription_withdrawal_restores_the_offering_cash_ledger_exactly
    """
    offering, subs, account = _filed_offering_with_collected_funds([30_000_000, 15_000_000])
    set_clock("2026-09-02T00:00:00Z")
    validate_success(api_client.withdraw_subscription(
        subs[0]["id"], {}, make_investor_headers(subs[0]["investor_id"])), 200)

    after = get_offering(offering["id"])
    assert after["cash_ledger_cents"] == 15_000_000
    assert_offering(after)
    assert_offering_invariants(after)

    # The segregated total still equals the balance: the conserved quantity is
    # unchanged by the collect/withdraw pair.
    held = validate_success(api_client.get_platform_account(account["id"], ADMIN), 200)
    assert held["balance_cents"] == 15_000_000
    assert held["investor_funds_held_cents"] == 15_000_000

    collected = sum(s["collected_subscription_cents"] for s in (
        validate_success(api_client.get_subscription(subs[0]["id"], COMPLIANCE), 200),
        validate_success(api_client.get_subscription(subs[1]["id"], COMPLIANCE), 200)))
    refunded = sum(s["refunded_cents"] for s in (
        validate_success(api_client.get_subscription(subs[0]["id"], COMPLIANCE), 200),
        validate_success(api_client.get_subscription(subs[1]["id"], COMPLIANCE), 200)))
    assert collected - refunded == 15_000_000


# ── The eligibility screen's internal order ──────────────────────────────────

def test_a_japanese_resident_subscription_is_refused_as_ineligible(api):
    """PRD 2.8: "The jurisdiction override is evaluated first, then whether the investor
    has reached the age of 18 at the current clock instant as measured from
    `birth_date`, then the residence rule: a `residency_country_code` other than `US` is
    refused outright."

    Design: Difficulty/priority_pair_validation_conflict/investor_ineligibility_outranks_jurisdiction_redirect
    """
    set_clock("2026-09-01T00:00:00Z")
    artwork, offering = setup_filed_offering(start_clock="2026-09-01T00:00:00Z")
    investor = create_investor(email="tokyo@x.com", legal_name="Haruko Sen",
                               citizenship_country_code="JP",
                               residency_country_code="JP", birth_date="1965-05-05")

    res = api_client.create_subscription(
        {"offering_id": offering["id"], "investor_id": investor["id"],
         "requested_shares": 100},
        make_investor_headers(investor["id"]))
    validate_error(res, "ERR_INVESTOR_INELIGIBLE", expected_status=400)

    assert get_success_data(api_client.list_subscriptions(
        ISSUER, params={"offering_id": offering["id"]})) == []
    assert validate_success(
        api_client.get_investor(investor["id"], ISSUER), 200)["suitability_status"] == "PENDING"


def test_a_us_citizen_lawfully_resident_abroad_is_still_refused_as_ineligible(api):
    """PRD 2.8: "A failed eligibility screen is reported as `ERR_INVESTOR_INELIGIBLE`
    (HTTP 400), covering non-US residency and an investor under 18 at the current clock
    instant."

    Design: Difficulty/priority_pair_validation_conflict/investor_ineligibility_outranks_jurisdiction_redirect
    """
    set_clock("2026-09-01T00:00:00Z")
    artwork, offering = setup_filed_offering(start_clock="2026-09-01T00:00:00Z")
    investor = create_investor(email="abroad@x.com", legal_name="Helene Marchetti",
                               citizenship_country_code="US",
                               residency_country_code="FR", birth_date="1968-03-09")

    res = api_client.create_subscription(
        {"offering_id": offering["id"], "investor_id": investor["id"],
         "requested_shares": 100},
        make_investor_headers(investor["id"]))
    validate_error(res, "ERR_INVESTOR_INELIGIBLE", expected_status=400)

    assert get_offering(offering["id"])["accepted_shares"] == 0


def test_an_underage_non_us_resident_is_refused_as_ineligible(api):
    """PRD 2.8: "A failed eligibility screen is reported as `ERR_INVESTOR_INELIGIBLE`
    (HTTP 400), covering non-US residency and an investor under 18 at the current clock
    instant."

    The jurisdiction override fires only for a US citizen who is also a US resident, so
    an underage caller whose residency is outside the US does not trip it; the age test,
    evaluated after the override, refuses it with `ERR_INVESTOR_INELIGIBLE`.

    Design: Corner/validations/an_underage_investor_is_refused_before_the_jurisdiction_redirect
    """
    set_clock("2026-09-01T00:00:00Z")
    artwork, offering = setup_filed_offering(start_clock="2026-09-01T00:00:00Z")
    minor = create_investor(email="minor-abroad@x.com", legal_name="Casey Whitlock",
                            citizenship_country_code="CA", residency_country_code="CA",
                            birth_date="2009-01-01",
                            annual_income_cents=0, net_worth_cents=5_000_000)

    set_clock("2026-09-10T00:00:00Z")
    res = api_client.create_subscription(
        {"offering_id": offering["id"], "investor_id": minor["id"],
         "requested_shares": 100},
        make_investor_headers(minor["id"]))
    validate_error(res, "ERR_INVESTOR_INELIGIBLE", expected_status=400)

    assert get_success_data(api_client.list_subscriptions(
        ISSUER, params={"investor_id": minor["id"]})) == []


# ── The registration cap is a bound, not a reservation ───────────────────────

def test_a_subscription_clamped_to_zero_becomes_waitlisted(api):
    """PRD 3.5: "for each one the remaining room is the share cap less the investor's
    running accepted total, floored at zero, the accepted amount is the smaller of the
    subscription's `requested_shares` and that room, and the accepted amount is added to
    the running total. ... A subscription that comes out of the clamp with at least one
    share becomes `SUBSCRIBED`; one clamped all the way to zero becomes `WAITLISTED`."

    Design: Difficulty/combinatorial_formula/registration_cap_reading_decides_how_many_shares_are_accepted
    """
    set_clock("2026-09-01T00:00:00Z")
    artwork, offering = setup_filed_offering(
        start_clock="2026-09-01T00:00:00Z", total_shares=10_000,
        price_per_share_cents=2_000, registration_cap_pct=2_000,
        exemption_type="REG_A_TIER2")
    investor = create_investor(email="over@x.com", legal_name="Over Subscriber")
    other = create_investor(email="other@x.com", legal_name="Other Subscriber")
    first = create_screened_subscription(offering["id"], investor["id"],
                                         requested_shares=3000)
    second = create_screened_subscription(offering["id"], investor["id"],
                                          requested_shares=3000)
    create_screened_subscription(offering["id"], other["id"], requested_shares=3000)
    validate_success(allocate_offering(offering["id"]), 200)

    assert validate_success(
        api_client.get_subscription(first["id"], COMPLIANCE), 200)["accepted_shares"] == 2000
    clamped = validate_success(api_client.get_subscription(second["id"], COMPLIANCE), 200)
    assert clamped["accepted_shares"] == 0
    assert clamped["status"] == "WAITLISTED"
    assert clamped["waitlist_rank"] == 1


# ── The artwork's fork is legible from its status alone ──────────────────────

def test_abandoning_a_filed_offering_returns_the_artwork_to_authenticated(api):
    """PRD 3.3: "It moves the offering to terminal `OFFERING_ABANDONED` and returns the
    artwork to `AUTHENTICATED` — back to the fork point — rather than to `HELD`. That
    direction matters: a work can reach `HELD` by two distinct routes, and there is no
    edge back from `HELD` to `OFFERING_PENDING`."

    Design: Corner/state_machines/artwork_cannot_leave_offering_pending_through_the_held_branch
    """
    set_clock("2026-09-01T00:00:00Z")
    artwork, offering = setup_filed_offering(start_clock="2026-09-01T00:00:00Z")

    abandoned = validate_success(api_client.abandon_offering(
        offering["id"],
        {"reason": "Reserve price renegotiation",
         "expected_offering_version": offering_version(offering["id"])}, COMPLIANCE), 200)
    assert abandoned["status"] == "OFFERING_ABANDONED"
    assert get_artwork(artwork["id"])["status"] == "AUTHENTICATED"


def test_a_fresh_offering_after_abandonment_reuses_the_fork_node(api):
    """PRD 3.3: "the only route back into `OFFERING_PENDING` runs through
    `AUTHENTICATED`."

    Design: Corner/state_machines/artwork_cannot_leave_offering_pending_through_the_held_branch
    """
    set_clock("2026-09-01T00:00:00Z")
    artwork, offering = setup_filed_offering(start_clock="2026-09-01T00:00:00Z")
    validate_success(api_client.abandon_offering(
        offering["id"],
        {"reason": "Reserve price renegotiation",
         "expected_offering_version": offering_version(offering["id"])}, COMPLIANCE), 200)

    second = create_offering(artwork["id"], total_shares=40_000,
                             price_per_share_cents=1_500, registration_cap_pct=2_000,
                             liquidity_ratio_bps=1_000, hold_period_days=182)
    assert get_artwork(artwork["id"])["status"] == "OFFERING_PENDING"

    rows = get_success_data(api_client.list_offerings(
        ISSUER, params={"artwork_id": artwork["id"]}))
    assert len(rows) == 2
    statuses = {row["id"]: row["status"] for row in rows}
    assert statuses[offering["id"]] == "OFFERING_ABANDONED"
    assert statuses[second["id"]] == "DRAFT"


# ── The appraisal's parent lookup and stale version ──────────────────────────

def test_an_appraisal_against_an_unknown_work_is_not_found(api):
    """PRD 2.5: "the server confirms the existence of the leftmost identifier first and
    refuses the request with `ERR_NOT_FOUND` for the first identifier that does not
    resolve, before attempting any lookup further right and before evaluating any
    business rule."

    Design: Corner/entities/artwork_appraisals_require_a_valid_parent_and_read_back_under_it
    """
    set_clock("2026-09-01T00:00:00Z")
    res = api_client.create_appraisal(
        NON_EXISTENT_UUID,
        {"appraised_value_cents": 20_000_000,
         "appraiser_firm": "Ashgrove Fine Art Appraisals",
         "appraisal_method": "MARKET_INDEX",
         "expected_artwork_version": 1},
        ISSUER)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_an_appraisal_reads_back_through_its_artwork_scoped_list(api):
    """PRD 3.2: "The server stamps `filed_at` and, on every filing, recomputes the
    selection dimension across the whole sibling set: the new row becomes the selected
    appraisal — its `is_selected` set true".

    Design: Corner/entities/artwork_appraisals_require_a_valid_parent_and_read_back_under_it
    """
    set_clock("2026-09-01T00:00:00Z")
    _, artwork = setup_authenticated_artwork(start_clock="2026-09-01T00:00:00Z")
    appraisal = validate_success(file_appraisal(artwork["id"], 20_000_000,
                                                appraisal_method="MARKET_INDEX"), 201)

    assert appraisal["artwork_id"] == artwork["id"]
    assert appraisal["is_selected"] is True
    rows = get_success_data(api_client.list_appraisals(artwork["id"], ISSUER))
    assert len(rows) == 1


def test_a_stale_artwork_version_refuses_a_new_appraisal_filing(api):
    """PRD 2.6: "Filing an appraisal requires `expected_artwork_version`, matched
    against the target `Artwork`'s current `version`. Every prior appraisal filing,
    custody transition, and asset-report component re-evaluates the artwork's
    `artifacts_overview` and therefore advances its version."

    Design: Corner/cross_cutting_complexity_layers/a_stale_artwork_version_refuses_a_new_appraisal_filing
    """
    set_clock("2026-09-01T00:00:00Z")
    _, artwork = setup_authenticated_artwork(start_clock="2026-09-01T00:00:00Z")
    stale_version = artwork_version(artwork["id"])

    # A first filing advances the artwork's version.
    validate_success(file_appraisal(artwork["id"], 20_000_000), 201)

    res = api_client.create_appraisal(
        artwork["id"],
        {"appraised_value_cents": 21_000_000,
         "appraiser_firm": "Ashgrove Fine Art Appraisals",
         "appraisal_method": "MARKET_INDEX",
         "expected_artwork_version": stale_version},
        ISSUER)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)

    assert len(get_success_data(api_client.list_appraisals(artwork["id"], ISSUER))) == 1
    assert get_artwork(artwork["id"])["last_appraised_value_cents"] == 20_000_000


def test_retrying_an_appraisal_with_the_fresh_version_succeeds(api):
    """PRD 2.6: "the field holds the parent entity's `version` as the client last
    observed it, and if that value no longer equals the parent's stored `version` the
    request is refused with `ERR_STALE_VERSION` and HTTP 412, and nothing is written."

    Design: Corner/cross_cutting_complexity_layers/a_stale_artwork_version_refuses_a_new_appraisal_filing
    """
    set_clock("2026-09-01T00:00:00Z")
    _, artwork = setup_authenticated_artwork(start_clock="2026-09-01T00:00:00Z")
    validate_success(file_appraisal(artwork["id"], 20_000_000), 201)

    set_clock("2026-12-14T00:00:00Z")
    validate_success(file_appraisal(artwork["id"], 21_000_000), 201)
    assert get_artwork(artwork["id"])["last_appraised_value_cents"] == 21_000_000