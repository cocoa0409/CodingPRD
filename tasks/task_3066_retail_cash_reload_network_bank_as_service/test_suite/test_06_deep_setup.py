"""Deep-setup and OCC-adjacent scenarios (PRD §2.7, §3.5, §3.7)."""
import pytest

from test_helpers import (
    api_client, ApiErrorId, validate_error, get_success_data, set_clock,
    setup_network, get_account, get_program, get_load, get_agreement, get_location,
    get_brand_partner, get_dispute, get_sponsor, get_batch, get_alert,
    create_and_fund_load, create_brand, activate_brand, create_agreement,
    create_location, create_account, raise_alert, review_alert, confirm_alert,
    create_dispute, dispute_retailer_response, dispute_program_review,
    dispute_return_to_retailer, move_program_posture, oversight_review,
    setup_settled_load, create_settlement_batch, open_settlement_batch,
    setup_requested_float_window, create_float_window,
    suspend_brands, setup_frozen_program,
    make_bank_sponsor_headers, make_program_manager_headers,
    make_retailer_clerk_headers, OFFICER, ANALYST, ADMIN, SETTLEMENT,
)


def test_oversight_review_advances_the_due_date_and_counts_a_completion():
    """PRD §3.5: "Recording a review increments the sponsor's
    `oversight_reviews_completed`, stamps the program's `last_posture_review_at`
    with the current clock, pushes `oversight_review_due_at` forward by 90 days".

    Design: Corner/endpoints/oversight_review_advances_due_date_and_counts
    """
    net = setup_network(clock="2026-09-01T12:00:00Z")
    resp = oversight_review(net["program"]["id"], net["bank"]["id"])
    program = get_success_data(resp)
    assert program["last_posture_review_at"] == "2026-09-01T12:00:00Z"
    assert program["oversight_review_due_at"] == "2026-11-30T12:00:00Z"
    assert program["is_oversight_overdue"] is False
    assert get_sponsor(net["bank"]["id"])["oversight_reviews_completed"] == 1


def test_oversight_review_on_time_is_not_overdue():
    """PRD §3.5: "a review performed exactly at the deadline is not late".
    PRD §3.5: "The review computes an `overdue_days` figure ... counting only
    complete days and reporting zero when the review is on time or early".

    Design: Corner/endpoints/oversight_review_advances_due_date_and_counts
    """
    net = setup_network(clock="2026-12-15T00:00:00Z")
    program = get_program(net["program"]["id"])
    assert program["is_oversight_overdue"] is False
    reviewed = get_success_data(oversight_review(net["program"]["id"], net["bank"]["id"]))
    assert reviewed["is_oversight_overdue"] is False


def test_posture_transition_requires_the_sponsoring_bank():
    """PRD §3.5: "Every posture move is performed by the program's own
    `BankSponsor` — or by a `PlatformAdmin`".
    PRD §2.1: "a posture move or oversight review is refused unless the target
    program's `sponsor_bank_id` equals `X-User-ID`."

    Design: Corner/endpoints/program_state_transition_requires_sponsor_and_bumps_version
    """
    net = setup_network(activate_brand_flag=True)
    create_and_fund_load(net["location"], net["account"], net["agreement"],
                         principal_cents=12000)
    alert = raise_alert(net["program"], net["account"], "VELOCITY")
    review_alert(alert["id"])
    confirm_alert(alert["id"])
    resp = move_program_posture(net["program"]["id"], "RESTRICTED", net["bank"]["id"])
    moved = get_success_data(resp)
    assert moved["compliance_posture"] == "RESTRICTED"
    assert get_agreement(net["agreement"]["id"])["agreement_status"] == "SUSPENDED"
    assert get_location(net["location"]["id"])["location_status"] == "RESTRICTED"


def test_posture_transition_increments_the_program_version():
    """PRD §3.5: "Each successful move sets `compliance_posture`, stamps
    `last_posture_review_at` with the current clock instant, and advances the
    program's `version` by one."

    Design: Corner/endpoints/program_state_transition_requires_sponsor_and_bumps_version
    """
    net = setup_network(activate_brand_flag=True)
    create_and_fund_load(net["location"], net["account"], net["agreement"],
                         principal_cents=12000)
    alert = raise_alert(net["program"], net["account"], "VELOCITY")
    review_alert(alert["id"])
    confirm_alert(alert["id"])
    before = get_program(net["program"]["id"])
    moved = get_success_data(move_program_posture(net["program"]["id"], "RESTRICTED",
                                                  net["bank"]["id"]))
    assert moved["version"] == before["version"] + 1


def test_posture_move_below_the_restricted_floor_is_blocked():
    """PRD §3.5: "a move to `RESTRICTED` requires a score of at least 4.00 and at
    most 59.99 ... A move that does not meet its band is refused with
    `ERR_PROGRAM_POSTURE_TRANSITION_BLOCKED` (HTTP 409)."

    Design: Corner/endpoints/program_state_transition_requires_sponsor_and_bumps_version
    """
    net = setup_network()
    assert get_program(net["program"]["id"])["posture_score"] == pytest.approx(0.00, abs=0.01)
    resp = move_program_posture(net["program"]["id"], "RESTRICTED", net["bank"]["id"])
    validate_error(resp, ApiErrorId.ERR_PROGRAM_POSTURE_TRANSITION_BLOCKED, 409)
    assert get_program(net["program"]["id"])["compliance_posture"] == "OPEN"


def test_posture_move_to_frozen_below_sixty_is_blocked():
    """PRD §3.5: "a move to `FROZEN` requires a score of at least 60.00 ... A move
    that does not meet its band is refused with
    `ERR_PROGRAM_POSTURE_TRANSITION_BLOCKED` (HTTP 409)."

    Design: Corner/endpoints/program_state_transition_requires_sponsor_and_bumps_version
    """
    net = setup_network()
    suspend_brands(net, 5)
    program = get_program(net["program"]["id"])
    assert program["posture_score"] < 60.00
    resp = move_program_posture(net["program"]["id"], "FROZEN", net["bank"]["id"])
    validate_error(resp, ApiErrorId.ERR_PROGRAM_POSTURE_TRANSITION_BLOCKED, 409)


def test_posture_move_to_frozen_advances_at_or_above_sixty():
    """PRD §3.5: "a move to `FROZEN` requires a score of at least 60.00".
    PRD §3.5: "The `posture_score` then compounds rather than accumulating: with
    `n` breaches and a decay factor λ, the score is one hundred multiplied by one
    minus the quantity one minus λ raised to the power `n`."

    Design: Corner/endpoints/program_state_transition_requires_sponsor_and_bumps_version
    """
    net = setup_network(clock="2027-01-01T00:00:00Z")
    # Six COMPLIANCE suspensions yield 100*(1-0.9^6) = 46.86; an overdue review
    # raises λ to 0.20, so six breaches yield 100*(1-0.8^6) = 73.79 >= 60.00.
    suspend_brands(net, 6)
    program = get_program(net["program"]["id"])
    assert program["is_oversight_overdue"] is True
    assert program["posture_score"] >= 60.00
    moved = get_success_data(move_program_posture(net["program"]["id"], "FROZEN",
                                                  net["bank"]["id"]))
    assert moved["compliance_posture"] == "FROZEN"


def test_frozen_program_closes_the_stores_and_cascades_to_loads():
    """PRD §3.5: "Hop 1 suspends every brand whose status is `ACTIVE` or
    `SUSPENDED`, always with a `suspension_source` of `POSTURE`, and closes every
    store under the program's agreements whose status is `OPEN` or `RESTRICTED`."

    Design: Difficulty/cross_entity_state_dependency/brand_activation_requires_open_program
    """
    net = setup_network(clock="2027-01-01T00:00:00Z")
    load = create_and_fund_load(net["location"], net["account"], net["agreement"],
                                principal_cents=12000)
    suspend_brands(net, 6)
    get_success_data(move_program_posture(net["program"]["id"], "FROZEN",
                                          net["bank"]["id"]))
    assert get_location(net["location"]["id"])["location_status"] == "CLOSED"
    assert get_load(load["id"])["load_status"] == "REVERSED"
    assert get_load(load["id"])["reversal_reason"] == "AML_CONFIRMED"
    assert get_account(net["account"]["id"])["compliance_hold_status"] == "FROZEN"


def test_program_frozen_refuses_a_load_creation_against_its_agreement():
    """PRD §2.4: "A write that creates or mutates a child of a program whose
    `compliance_posture` is `FROZEN` is refused with `ERR_PROGRAM_FROZEN` (HTTP 409)
    — this guard covers ... load creation, alert filing, dispute filing".

    Design: Difficulty/cross_entity_state_dependency/brand_activation_requires_open_program
    """
    net = setup_network(clock="2027-01-01T00:00:00Z")
    suspend_brands(net, 6)
    get_success_data(move_program_posture(net["program"]["id"], "FROZEN",
                                          net["bank"]["id"]))
    resp = api_client.create_load(
        {"reload_location_id": net["location"]["id"],
         "card_account_id": net["account"]["id"],
         "principal_cents": 3000,
         "expected_card_account_version": get_account(net["account"]["id"])["version"]},
        make_retailer_clerk_headers(net["agreement"]["id"]))
    validate_error(resp, ApiErrorId.ERR_PROGRAM_FROZEN, 409)


# ---------------------------------------------------------------------------
# Optimistic concurrency
# ---------------------------------------------------------------------------

def test_stale_program_version_refuses_brand_onboarding():
    """PRD §2.7: "Onboarding a `BrandPartner` requires `expected_program_version`,
    carrying the client's last observed `version` of the sponsoring `Program`. A
    mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), because an oversight
    review or a posture transition legitimately changes the program a partner is
    being onboarded against."

    Design: Corner/errors/stale_program_version_refuses_brand_onboarding
    """
    net = setup_network(clock="2026-09-01T12:00:00Z")
    stale_version = get_program(net["program"]["id"])["version"]
    get_success_data(oversight_review(net["program"]["id"], net["bank"]["id"]))
    resp = api_client.create_brand_partner(
        {"program_id": net["program"]["id"], "brand_name": "Late Brand",
         "services_scope": ["LEDGERING"], "ledgering_enabled": True,
         "expected_program_version": stale_version},
        OFFICER)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)


def test_fresh_program_version_permits_brand_onboarding():
    """PRD §2.7: "The remaining version-bearing writes are the load reversal and
    the load re-instatement described in §3.4 ... No other operation accepts a
    client-supplied version field."

    Design: Corner/errors/stale_program_version_refuses_brand_onboarding
    """
    net = setup_network(clock="2026-09-01T12:00:00Z")
    get_success_data(oversight_review(net["program"]["id"], net["bank"]["id"]))
    fresh = get_program(net["program"]["id"])["version"]
    created = get_success_data(api_client.create_brand_partner(
        {"program_id": net["program"]["id"], "brand_name": "Fresh Brand",
         "services_scope": ["LEDGERING"], "ledgering_enabled": True,
         "expected_program_version": fresh},
        OFFICER))
    assert created["brand_name"] == "Fresh Brand"
    assert created["partner_status"] == "PENDING_ONBOARDING"


def test_stale_card_account_version_refuses_load_creation():
    """PRD §2.7: "Creating a `LoadTransaction` requires
    `expected_card_account_version`, carrying the client's last observed `version`
    of the target `CardAccount`. A mismatch with the account's current `version`
    is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/errors/stale_program_version_refuses_brand_onboarding
    """
    net = setup_network()
    stale_version = get_account(net["account"]["id"])["version"]
    create_and_fund_load(net["location"], net["account"], net["agreement"],
                         principal_cents=3000)
    resp = api_client.create_load(
        {"reload_location_id": net["location"]["id"],
         "card_account_id": net["account"]["id"],
         "principal_cents": 3000,
         "expected_card_account_version": stale_version},
        make_retailer_clerk_headers(net["agreement"]["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)


# ---------------------------------------------------------------------------
# Dispute response window
# ---------------------------------------------------------------------------

def test_expired_response_window_blocks_a_late_retailer_response():
    """PRD §3.7: "A `REG_E` case gives the retailer 24 hours ... the deadline is
    the current clock instant plus that many hours ... A response arriving after it
    is refused with `ERR_DISPUTE_RESPONSE_WINDOW_CLOSED` (HTTP 409)."

    Design: Corner/errors/expired_response_window_blocks_late_retailer_response
    """
    net = setup_network(clock="2026-09-01T00:00:00Z")
    load = create_and_fund_load(net["location"], net["account"], net["agreement"],
                                principal_cents=3500)
    dispute = create_dispute(net["program"], load, net["account"],
                             claimed_amount_cents=1500)
    assert dispute["retailer_response_due_at"] == "2026-09-02T00:00:00Z"
    set_clock("2026-09-02T01:00:00Z")
    resp = dispute_retailer_response(dispute["id"], net["agreement"]["id"],
                                     position="late evidence packet")
    validate_error(resp, ApiErrorId.ERR_DISPUTE_RESPONSE_WINDOW_CLOSED, 409)
    case = get_dispute(dispute["id"])
    assert case["case_status"] == "OPEN"
    assert case["response_round"] == 0


def test_response_exactly_at_the_deadline_is_accepted():
    """PRD §3.7: "the comparison is inclusive, so a retailer response arriving
    exactly at the deadline is in time."

    Design: Corner/errors/expired_response_window_blocks_late_retailer_response
    """
    net = setup_network(clock="2026-09-01T00:00:00Z")
    load = create_and_fund_load(net["location"], net["account"], net["agreement"],
                                principal_cents=3500)
    dispute = create_dispute(net["program"], load, net["account"],
                             claimed_amount_cents=1500)
    set_clock("2026-09-02T00:00:00Z")
    accepted = get_success_data(dispute_retailer_response(
        dispute["id"], net["agreement"]["id"], position="in time"))
    assert accepted["case_status"] == "RETAILER_RESPONSE"
    assert accepted["response_round"] == 1


def test_voluntary_dispute_window_is_forty_eight_hours():
    """PRD §3.7: "A `REG_E` case gives the retailer 24 hours, a `VOLUNTARY` case
    48 hours, and a `CORPORATE` case 72 hours".

    Design: Corner/errors/expired_response_window_blocks_late_retailer_response
    """
    net = setup_network(clock="2026-09-01T00:00:00Z",
                        account_overrides={"cardholder_agreement_type": "VOLUNTARY"})
    load = create_and_fund_load(net["location"], net["account"], net["agreement"],
                                principal_cents=3500)
    dispute = create_dispute(net["program"], load, net["account"],
                             claimed_amount_cents=1500)
    assert dispute["retailer_response_due_at"] == "2026-09-03T00:00:00Z"