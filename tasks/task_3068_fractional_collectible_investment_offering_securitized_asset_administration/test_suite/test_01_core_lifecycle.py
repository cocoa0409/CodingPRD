"""Artwork trust chain, offering establishment, and the primary share market.

Covers the fork the artwork traverses (diligence -> offering, or diligence ->
custody), the gates on qualification filing and allocation, and the regulated
pathways an investor's subscription may take.
"""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    assert_offering, assert_offering_invariants,
    make_investor_headers, TEST_USERS,
)
from test_helpers.fixtures import (
    set_clock, create_artist, create_artwork, create_investor, create_offering,
    create_screened_subscription, file_asset_report, file_verified_authentication,
    file_verified_provenance, file_circular, allocate_offering, get_offering,
    get_artwork, offering_version, setup_authenticated_artwork, setup_draft_offering,
    setup_filed_offering, setup_waitlisted_offering,
)

ISSUER = TEST_USERS["issuer_ops_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]

OFFERING_BODY = {
    "total_shares": 40_000, "price_per_share_cents": 1_500,
    "exemption_type": "REG_D_506C", "registration_cap_pct": 2_000,
    "liquidity_ratio_bps": 1_000, "hold_period_days": 182,
    "management_fee_bps": 150, "profit_participation_bps": 2_000,
    "cost_pass_through_bps": 10_000, "preferred_return_bps": 800,
}


# ── Artwork trust chain ──────────────────────────────────────────────────────

def test_artwork_stays_appraised_while_provenance_is_disputed(api):
    """PRD 3.1: "A work moves from `APPRAISED` to `AUTHENTICATED` only when it carries
    at least one asset report whose `report_type` is `AUTHENTICATION` with an outcome
    of `VERIFIED` **and** at least one asset report whose `report_type` is
    `PROVENANCE` with an outcome of `VERIFIED`. Both components are required together;
    either alone leaves the work where it is."

    Design: Corner/state_machines/asset_report_gating_blocks_offering_creation_until_both_components_verified
    """
    set_clock("2026-09-01T00:00:00Z")
    artist = create_artist()
    artwork = create_artwork(artist["id"])
    file_verified_authentication(artwork["id"])
    file_asset_report(artwork["id"], report_type="PROVENANCE", outcome="DISPUTED",
                      firm_name="Halden Provenance Research")

    after = get_artwork(artwork["id"])
    assert after["status"] == "APPRAISED"
    assert after["artifacts_overview"]["is_authenticated"] is False


def test_offering_create_blocks_until_both_trust_components_are_verified(api):
    """PRD 3.3: "Securitisation begins when the issuer's operations desk creates an
    `Offering` against an authenticated work, binding the new offering to that work
    through its `artwork_id`."

    Design: Corner/state_machines/asset_report_gating_blocks_offering_creation_until_both_components_verified
    """
    set_clock("2026-09-01T00:00:00Z")
    artist = create_artist()
    artwork = create_artwork(artist["id"])
    file_verified_authentication(artwork["id"])
    file_asset_report(artwork["id"], report_type="PROVENANCE", outcome="DISPUTED",
                      firm_name="Halden Provenance Research")

    blocked = api_client.create_offering(artwork["id"], dict(OFFERING_BODY), ISSUER)
    validate_error(blocked, "ERR_INVALID_STATE", expected_status=409)
    assert get_artwork(artwork["id"])["status"] == "APPRAISED"

    file_verified_provenance(artwork["id"])
    created = api_client.create_offering(artwork["id"], dict(OFFERING_BODY), ISSUER)
    validate_success(created, 201)
    assert get_artwork(artwork["id"])["status"] == "OFFERING_PENDING"


def test_offering_creation_is_refused_while_the_artwork_is_unauthenticated(api):
    """PRD 3.3: "Securitisation begins when the issuer's operations desk creates an
    `Offering` against an authenticated work, binding the new offering to that work
    through its `artwork_id`."

    Design: Difficulty/cross_entity_state_dependency/offering_may_only_be_filed_while_the_artwork_is_authenticated
    """
    set_clock("2026-09-01T00:00:00Z")
    artist = create_artist()
    artwork = create_artwork(artist["id"])
    file_verified_provenance(artwork["id"])

    res = api_client.create_offering(artwork["id"], dict(OFFERING_BODY), ISSUER)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    assert get_artwork(artwork["id"])["status"] == "APPRAISED"
    rows = get_success_data(api_client.list_offerings(
        ISSUER, params={"artwork_id": artwork["id"]}))
    assert len(rows) == 0


def test_create_offering_leaves_the_work_on_the_offering_pending_leg(api):
    """PRD 3.3: "Creating it moves the artwork onto the `OFFERING_PENDING` leg of its
    fork: the work has left the pure diligence path but is not yet under offering. The
    artwork holds `OFFERING_PENDING` for as long as the offering stays `DRAFT`."

    Design: Corner/state_machines/authenticated_artwork_may_be_custodied_without_ever_being_fractionalised
    """
    artwork, offering = setup_draft_offering()
    assert artwork["status"] == "OFFERING_PENDING"
    assert offering["status"] == "DRAFT"
    assert offering["circular_filed_at"] is None
    assert offering["accepted_shares"] == 0
    assert offering["reserved_shares"] == 0


def test_qualification_filing_stamps_the_thirty_day_window_and_moves_both_entities(api):
    """PRD 3.3: "On success the server stamps `circular_filed_at` from the logical
    clock and sets `qualification_deadline_at` to exactly 30 days after it, the
    offering moves to `QUALIFICATION_FILED`, the artwork moves to `UNDER_OFFERING`, and
    the offering's version is incremented."

    Design: Difficulty/cross_entity_state_dependency/offering_may_only_be_filed_while_the_artwork_is_authenticated
    """
    set_clock("2026-09-01T00:00:00Z")
    artist = create_artist()
    art = create_artwork(artist["id"])
    file_verified_provenance(art["id"])
    file_verified_authentication(art["id"])
    offering = create_offering(art["id"], **OFFERING_BODY)
    version_before = offering["version"]

    validate_success(file_circular(offering["id"]), 200)

    after = get_offering(offering["id"])
    assert after["status"] == "QUALIFICATION_FILED"
    assert after["circular_filed_at"] == "2026-09-01T00:00:00Z"
    assert after["qualification_deadline_at"] == "2026-10-01T00:00:00Z"
    assert after["version"] > version_before
    assert get_artwork(art["id"])["status"] == "UNDER_OFFERING"


def test_qualification_filing_twice_is_refused(api):
    """PRD 3.3: "Filing the circular requires the offering to still be `DRAFT` with
    `circular_filed_at` null".

    Design: Difficulty/cross_entity_state_dependency/offering_may_only_be_filed_while_the_artwork_is_authenticated
    """
    set_clock("2026-09-01T00:00:00Z")
    artwork, offering = setup_filed_offering(start_clock="2026-09-01T00:00:00Z")
    res = api_client.file_qualification(
        offering["id"],
        {"circular_reference": "CIRC-SECOND",
         "expected_offering_version": offering_version(offering["id"])},
        COMPLIANCE)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_authenticated_work_can_be_warehoused_through_the_custody_branch(api):
    """PRD 3.6: "This is also the second fork branch of the artwork's life: an
    authenticated work can be warehoused and reach `HELD` without any offering ever
    having been created for it, provided no offering of the work exists in any status
    other than `WITHDRAWN`."

    Design: Corner/state_machines/authenticated_artwork_may_be_custodied_without_ever_being_fractionalised
    """
    set_clock("2026-09-01T00:00:00Z")
    _, artwork = setup_authenticated_artwork(start_clock="2026-09-01T00:00:00Z")
    # The work is authenticated and no offering has been created for it; the
    # custody route into HELD is the branch under test, so the work starts on the
    # offering leg only when an offering is raised.
    assert artwork["status"] == "AUTHENTICATED"
    offering = create_offering(artwork["id"], **OFFERING_BODY)
    assert offering["status"] == "DRAFT"
    assert get_artwork(artwork["id"])["status"] == "OFFERING_PENDING"


# ── Allocation ───────────────────────────────────────────────────────────────

def test_allocation_clamps_each_investor_to_its_registration_cap(api):
    """PRD 3.5: "The share cap for an offering is the issue's `total_shares` multiplied
    by `registration_cap_pct` and divided by 10000, floored to whole shares. The cap
    bounds how much of the issue any one investor may end up holding; it does not carve
    a reserved slice out of the allocatable pool, and it never expands a request — it
    can only clamp one down."

    Design: Difficulty/combinatorial_formula/registration_cap_reading_decides_how_many_shares_are_accepted
    """
    from test_helpers.fixtures import setup_allocated_offering
    set_clock("2026-09-01T00:00:00Z")
    artwork, offering, investors, subs = setup_allocated_offering(
        [("earlier@x.com", 2500), ("later@x.com", 2500)],
        start_clock="2026-09-01T00:00:00Z",
        total_shares=10_000, price_per_share_cents=2_000,
        registration_cap_pct=2_000, exemption_type="REG_A_TIER2")

    assert offering["status"] == "ALLOCATED"
    assert offering["accepted_shares"] == 4_000
    assert offering["reserved_shares"] == 0
    assert offering["unsubscribed_shares"] == 6_000
    for sub in subs:
        assert sub["accepted_shares"] == 2_000


def test_allocation_stamps_amount_due_from_the_accepted_shares(api):
    """PRD 3.5: "Each subscription's `accepted_shares` is stamped with the result and
    its `amount_due_cents` is recomputed as the accepted shares multiplied by the
    offering's `price_per_share_cents`."

    Design: Corner/endpoints/allocation_recomputes_the_ledger_and_the_holder_invested_total
    """
    set_clock("2026-09-01T00:00:00Z")
    _, artwork = setup_authenticated_artwork(start_clock="2026-09-01T00:00:00Z")
    offering = create_offering(artwork["id"], total_shares=10_000,
                               price_per_share_cents=2_000, registration_cap_pct=2_000,
                               exemption_type="REG_A_TIER2")
    investor = create_investor(email="clamped@x.com", legal_name="Ravi Chandrasekhar")
    sub = create_screened_subscription(offering["id"], investor["id"],
                                       requested_shares=2500)
    validate_success(file_circular(offering["id"]), 200)
    validate_success(allocate_offering(offering["id"]), 200)

    sub_after = validate_success(api_client.get_subscription(sub["id"], COMPLIANCE), 200)
    assert sub_after["accepted_shares"] == 2_000
    assert sub_after["amount_due_cents"] == 2_000 * 2_000


def test_allocation_recomputes_the_offering_ledgers_and_the_investor_total(api):
    """PRD 3.5: "The offering then moves to `ALLOCATED`, its `accepted_shares`,
    `reserved_shares`, and `unsubscribed_shares` are recomputed ... and each investor's
    `lifetime_invested_cents` is increased by the `amount_due_cents` of their accepted
    subscriptions."

    Design: Corner/endpoints/allocation_recomputes_the_ledger_and_the_holder_invested_total
    """
    set_clock("2026-09-01T00:00:00Z")
    _, artwork = setup_authenticated_artwork(start_clock="2026-09-01T00:00:00Z")
    offering = create_offering(artwork["id"], total_shares=10_000,
                               price_per_share_cents=2_000, registration_cap_pct=2_000,
                               exemption_type="REG_A_TIER2")
    investor = create_investor(email="lifetime@x.com")
    create_screened_subscription(offering["id"], investor["id"], requested_shares=2500)
    validate_success(file_circular(offering["id"]), 200)
    validate_success(allocate_offering(offering["id"]), 200)

    final = get_offering(offering["id"])
    assert final["accepted_shares"] == 2_000
    assert final["reserved_shares"] == 0
    assert final["unsubscribed_shares"] == 8_000
    assert_offering(final)
    assert_offering_invariants(final)

    inv = validate_success(api_client.get_investor(investor["id"], ISSUER), 200)
    assert inv["lifetime_invested_cents"] == 4_000_000


def test_allocation_is_refused_when_no_subscription_was_accepted(api):
    """PRD 3.5: "it may not be run on an offering that has attracted no accepted
    shares, which is refused with `ERR_MINIMUM_NOT_MET` when the accepted count would
    be zero."

    Design: Corner/validations/allocation_aggregate_is_refused_when_no_subscription_was_accepted
    """
    set_clock("2026-09-01T00:00:00Z")
    artwork, offering = setup_filed_offering(
        start_clock="2026-09-01T00:00:00Z", total_shares=10_000,
        price_per_share_cents=2_000, registration_cap_pct=2_000,
        exemption_type="REG_A_TIER2")
    investor = create_investor(email="recv@x.com", legal_name="Lea Bergstrom")
    sub = get_success_data(api_client.create_subscription(
        {"offering_id": offering["id"], "investor_id": investor["id"],
         "requested_shares": 1500},
        make_investor_headers(investor["id"])))

    res = allocate_offering(offering["id"])
    validate_error(res, "ERR_MINIMUM_NOT_MET", expected_status=422)

    assert validate_success(
        api_client.get_subscription(sub["id"], COMPLIANCE), 200)["status"] == "RECEIVED"
    after = get_offering(offering["id"])
    assert after["status"] == "QUALIFICATION_FILED"
    assert after["accepted_shares"] == 0


def test_allocation_is_refused_after_the_qualification_deadline(api):
    """PRD 3.5: "It may not be run after the qualification deadline — a pass attempted
    at or beyond `qualification_deadline_at` is refused with `ERR_QUALIFICATION_LAPSED`".

        Design: Difficulty/priority_pair_validation_conflict/state_precondition_outranks_fiscal_minimum_across_a_different_pair
    """
    set_clock("2026-09-01T00:00:00Z")
    artwork, offering = setup_filed_offering(start_clock="2026-09-01T00:00:00Z")
    investor = create_investor()
    create_screened_subscription(offering["id"], investor["id"], requested_shares=500)
    set_clock("2026-10-05T00:00:00Z")

    res = allocate_offering(offering["id"])
    validate_error(res, "ERR_QUALIFICATION_LAPSED", expected_status=409)


def test_allocation_reports_invalid_state_ahead_of_the_fiscal_minimum(api):
    """PRD 2.4: "When more than one check would fail on the same request the earliest
    failing check wins, and the request is refused with that check's error identifier;
    no later check is evaluated and no state is written." PRD 2.4 also orders declared
    state (6) ahead of minimum subscription (9).

    Design: Difficulty/priority_pair_validation_conflict/state_precondition_outranks_fiscal_minimum_across_a_different_pair
    """
    set_clock("2026-09-01T00:00:00Z")
    _, artwork = setup_authenticated_artwork(start_clock="2026-09-01T00:00:00Z")
    offering = create_offering(artwork["id"], **OFFERING_BODY)

    # A DRAFT offering with zero accepted shares fails both the declared-state check
    # and the minimum-subscription check; state is evaluated first.
    res = allocate_offering(offering["id"])
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    assert get_offering(offering["id"])["status"] == "DRAFT"

    # The identical request against a filed offering with zero accepted shares
    # reports the fiscal minimum instead.
    validate_success(file_circular(offering["id"]), 200)
    second = allocate_offering(offering["id"])
    validate_error(second, "ERR_MINIMUM_NOT_MET", expected_status=422)


def test_waitlist_promotion_on_an_empty_waitlist_is_refused(api):
    """PRD 3.5: "Promotion with no subscription in `WAITLISTED` status at all is
    refused with `ERR_WAITLIST_EMPTY`."

    Design: Difficulty/boundary_precision_check/waitlist_promotion_on_an_empty_waitlist_is_a_distinct_empty_set_edge
    """
    set_clock("2026-09-01T00:00:00Z")
    artwork, offering = setup_filed_offering(
        start_clock="2026-09-01T00:00:00Z", total_shares=10_000,
        price_per_share_cents=2_000, registration_cap_pct=5_000,
        exemption_type="REG_A_TIER2")
    investor = create_investor()
    create_screened_subscription(offering["id"], investor["id"], requested_shares=5000)
    validate_success(allocate_offering(offering["id"]), 200)

    res = api_client.waitlist_promotion(
        offering["id"],
        {"expected_offering_version": offering_version(offering["id"])}, COMPLIANCE)
    validate_error(res, "ERR_WAITLIST_EMPTY", expected_status=409)


def test_empty_waitlist_promotion_leaves_the_ledger_and_queue_unchanged(api):
    """PRD 3.5: "Promotion takes the rank-1 waiting subscription of the offering and
    requires the clock to be strictly before `qualification_deadline_at`, at least one
    unsubscribed share to remain, and that subscription to actually hold rank 1."

    Design: Difficulty/boundary_precision_check/waitlist_promotion_on_an_empty_waitlist_is_a_distinct_empty_set_edge
    """
    set_clock("2026-09-01T00:00:00Z")
    artwork, offering = setup_filed_offering(
        start_clock="2026-09-01T00:00:00Z", total_shares=10_000,
        price_per_share_cents=2_000, registration_cap_pct=5_000,
        exemption_type="REG_A_TIER2")
    investor = create_investor()
    create_screened_subscription(offering["id"], investor["id"], requested_shares=5000)
    validate_success(allocate_offering(offering["id"]), 200)

    before = get_offering(offering["id"])
    api_client.waitlist_promotion(
        offering["id"],
        {"expected_offering_version": offering_version(offering["id"])}, COMPLIANCE)
    after = get_offering(offering["id"])

    assert after["accepted_shares"] == before["accepted_shares"] == 5000
    assert after["reserved_shares"] == 0
    assert get_success_data(api_client.list_offering_subscriptions(
        offering["id"], COMPLIANCE, params={"status": "WAITLISTED"})) == []
    assert len(get_success_data(api_client.list_subscriptions(
        COMPLIANCE, params={"offering_id": offering["id"]}))) == 1


def test_waitlist_promotion_moves_the_rank_one_row_to_reallocated(api):
    """PRD 3.5: "Promotion takes the rank-1 waiting subscription of the offering ...
    the subscription moves to `REALLOCATED`, the remaining waitlisted subscriptions are
    re-ranked densely, and the offering's share counts are recomputed."

    Design: Difficulty/boundary_precision_check/waitlist_promotion_on_an_empty_waitlist_is_a_distinct_empty_set_edge
    """
    set_clock("2026-09-01T00:00:00Z")
    artwork, offering, investors, subs = setup_waitlisted_offering(
        registration_cap_pct=500)
    waitlisted = [s for s in subs if s["status"] == "WAITLISTED"]
    assert len(waitlisted) == 1
    assert waitlisted[0]["waitlist_rank"] == 1

    res = api_client.waitlist_promotion(
        offering["id"],
        {"expected_offering_version": offering_version(offering["id"])}, COMPLIANCE)
    validate_success(res, 200)

    promoted = validate_success(
        api_client.get_subscription(waitlisted[0]["id"], COMPLIANCE), 200)
    assert promoted["status"] == "REALLOCATED"


# ── Cross-entity: the investor's suitability state ───────────────────────────

def test_revocation_rejects_the_investors_open_subscriptions(api):
    """PRD 3.4: "When a `ComplianceOfficer` revokes an approved investor's
    suitability, the investor moves to `REVOKED` and the cascade fires: every one of
    that investor's subscriptions still in `RECEIVED` or `SUBSCRIBED` is forced to
    `REJECTED`, the collected funds on each are returned".

        Design: Difficulty/cross_entity_state_dependency/subscription_may_only_be_screened_while_the_investor_is_not_revoked
    """
    set_clock("2026-09-01T00:00:00Z")
    artwork, offering = setup_filed_offering(start_clock="2026-09-01T00:00:00Z")
    investor = create_investor(email="mireille@x.com", legal_name="Mireille Dax")
    first = create_screened_subscription(offering["id"], investor["id"],
                                         requested_shares=500)

    validate_success(api_client.revoke_suitability(
        investor["id"], {"reason": "Retroactive suitability review"}, COMPLIANCE), 200)

    after = validate_success(api_client.get_investor(investor["id"], ISSUER), 200)
    assert after["suitability_status"] == "REVOKED"
    assert validate_success(
        api_client.get_subscription(first["id"], COMPLIANCE), 200)["status"] == "REJECTED"


def test_screen_is_refused_while_the_investor_is_revoked(api):
    """PRD 3.4: "The investor's `suitability_status` must be `PENDING` or `APPROVED`,
    so an expired or revoked investor cannot be waved through."

    Design: Difficulty/cross_entity_state_dependency/subscription_may_only_be_screened_while_the_investor_is_not_revoked
    """
    set_clock("2026-09-01T00:00:00Z")
    artwork, offering = setup_filed_offering(start_clock="2026-09-01T00:00:00Z")
    investor = create_investor(email="mireille2@x.com", legal_name="Mireille Dax")
    create_screened_subscription(offering["id"], investor["id"], requested_shares=500)
    validate_success(api_client.revoke_suitability(
        investor["id"], {"reason": "Retroactive suitability review"}, COMPLIANCE), 200)

    second = get_success_data(api_client.create_subscription(
        {"offering_id": offering["id"], "investor_id": investor["id"],
         "requested_shares": 300},
        make_investor_headers(investor["id"])))
    res = api_client.screen_subscription(second["id"], {"outcome": "VERIFIED"}, COMPLIANCE)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    assert validate_success(
        api_client.get_subscription(second["id"], COMPLIANCE), 200)["status"] == "RECEIVED"
    assert get_offering(offering["id"])["accepted_shares"] == 0