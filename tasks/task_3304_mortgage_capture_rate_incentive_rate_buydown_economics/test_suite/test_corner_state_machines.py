"""Corner coverage - initial states, terminal lockdowns, idempotency and lapse chains."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers import BANKER_HEADERS, CLOSING_HEADERS, COMPLIANCE_HEADERS, SALES_HEADERS


def test_a_newly_created_inventory_home_starts_available(api):
    """No reserve call is needed: creation alone lands the home in AVAILABLE.

    PRD §3.2: "A home site begins in `home_site_status` `AVAILABLE`."
    PRD §3.2: "Its physical progress is tracked by `construction_stage`".
    Design: Corner/state_machines/home_site_starts_available_on_creation
    """
    world = fixtures.seed_reference_data(api)
    site = fixtures.create_home_site(api, world["cm1"], construction_stage="FRAMING")

    assert site["home_site_status"] == "AVAILABLE", (
        f"creation alone reserves nothing, got {site['home_site_status']}"
    )
    assert site["construction_stage"] == "FRAMING", site["construction_stage"]


def test_a_suspended_community_refuses_any_further_posture_change(api):
    """SUSPENDED is declared terminal, so no later posture write is declared for it.

    PRD §3.1: "Suspension is the severe move and its trigger is a compliance failure".
    PRD §2.10: "Priority 4 requires that the target row be in a state that declares the
    requested transition in its state machine; failure yields `ERR_INVALID_STATE` at
    HTTP 409, and this check applies to every state-changing endpoint."
    Design: Corner/state_machines/community_suspended_is_terminal_and_refuses_further_posture_changes
    """
    world = fixtures.setup_contract_with_aba(
        api, construction_stage="DRYWALL", target_state="LOCKED", acknowledge_aba=False
    )
    fixtures.set_clock(api, "2026-09-05T00:00:00Z")
    suspended = fixtures.read_community(api, world["cm1"])
    assert suspended["program_status"] == "SUSPENDED", suspended["program_status"]

    refused = api.set_community_posture(world["cm1"], "ACTIVE", COMPLIANCE_HEADERS)
    validate_error(refused, "ERR_INVALID_STATE", 409)

    unchanged = fixtures.read_community(api, world["cm1"])
    assert unchanged["program_status"] == "SUSPENDED", (
        f"the platform's severe move is not reversible, got {unchanged['program_status']}"
    )


def test_a_second_close_on_the_same_contract_is_refused(api):
    """CLOSED is terminal, so the second close has no declared transition.

    PRD §3.4: "The contract's posture runs `PENDING`, `LOCKED`, `APPROVED`, then either
    `CLOSED` or `CANCELLED`, both of which are terminal."
    PRD §2.10: "Priority 4 requires that the target row be in a state that declares the
    requested transition in its state machine; failure yields `ERR_INVALID_STATE` at
    HTTP 409".
    Design: Corner/state_machines/contract_double_close_second_call_rejected
    """
    world = fixtures.seed_reference_data(api)
    site = fixtures.create_home_site(api, world["cm1"])
    contract = fixtures.create_contract(api, site["id"], world["b1"])
    world.update({"hs1": site["id"], "ct1": contract["id"]})

    application = fixtures.create_application(api, world["ct1"])
    application = get_success_data(api.qualify_loan_application(application["id"], BANKER_HEADERS))
    get_success_data(
        api.create_rate_lock(
            application["id"],
            f.rate_lock_payload(world["fc1"], lock_days=180,
                                expected_application_version=application["version"]),
            BANKER_HEADERS,
        )
    )
    fixtures.drive_lock(api, world)
    fixtures.drive_approve(api, world)
    fixtures.drive_close(api, world)

    refused = api.close_contract(world["ct1"], CLOSING_HEADERS)
    validate_error(refused, "ERR_INVALID_STATE", 409)

    after = fixtures.read_contract(api, world["ct1"])
    assert after["contract_status"] == "CLOSED", after["contract_status"]


def test_the_refused_second_close_draws_nothing_further_from_the_pool(api):
    """No second unit is drawn, so the commitment's ledger stops at the first close.

    PRD §3.6: "Each consumed lock increments its commitment's `units_drawn` by exactly
    one, and the commitment recomputes `units_available` as committed count minus drawn
    plus released".
    PRD §3.4: "No deposit settlement is created on a clean close, and the contract's
    `deposit_held_cents` remains equal to its `earnest_money_cents`".
    Design: Corner/state_machines/contract_double_close_second_call_rejected
    """
    world = fixtures.setup_contract_with_aba(
        api, construction_stage="FINISH", committed_units=5, target_state="CLOSED"
    )

    api.close_contract(world["ct1"], CLOSING_HEADERS)

    commitment = fixtures.read_commitment(api, world["fc1"])
    assert commitment["units_drawn"] == 1, (
        f"the rejected call drew nothing, got {commitment['units_drawn']}"
    )
    assert commitment["units_available"] == 4, (
        f"five purchased less the single consumed unit, got {commitment['units_available']}"
    )


def test_a_lapsed_cure_window_forces_the_steering_flag_down(api):
    """The undisposed disclosure drives the buyer's protection flag to false.

    PRD §2.8: "A `CURING` disclosure is a compliance failure: it forces the buyer's
    `steering_protection_flag` to false, and it drives the owning community into
    `SUSPENDED` posture".
    PRD §2.8: "The `steering_protection_flag` on a buyer is true exactly when every
    rate-buydown-bearing contract belonging to that buyer has an `ACKNOWLEDGED`
    affiliated-business arrangement disclosure."
    Design: Corner/state_machines/disclosure_cure_expiry_side_effect_chain_to_community_suspension
    """
    world = fixtures.setup_contract_with_aba(
        api, construction_stage="DRYWALL", target_state="LOCKED", acknowledge_aba=False
    )
    before = fixtures.read_buyer(api, world["b1"])
    assert before["steering_protection_flag"] is True, before["steering_protection_flag"]

    fixtures.set_clock(api, "2026-09-05T00:00:00Z")

    disclosed = fixtures.read_disclosure(api, world["d1"])
    assert disclosed["disclosure_status"] == "CURING", disclosed["disclosure_status"]

    after = fixtures.read_buyer(api, world["b1"])
    assert after["steering_protection_flag"] is False, (
        f"the lapse is what drops the protection flag, got {after['steering_protection_flag']}"
    )


def test_a_lapsed_disclosure_can_no_longer_be_acknowledged(api):
    """Acknowledgement is refused once the cure deadline has been passed.

    PRD §3.9: "An acknowledgement attempted once the form has already lapsed into
    `CURING` is refused with `ERR_ABA_DISCLOSURE_CURE_EXPIRED` at HTTP 409, because
    the statutory window has closed and the buyer's own acknowledgement can no longer
    cure it."
    PRD §2.8: "While the clock has not passed `cure_deadline_iso`, the disclosure may
    be acknowledged by its buyer and moves to `ACKNOWLEDGED`".
    Design: Corner/state_machines/disclosure_cure_expiry_side_effect_chain_to_community_suspension
    """
    world = fixtures.setup_contract_with_aba(
        api, construction_stage="DRYWALL", target_state="LOCKED", acknowledge_aba=False
    )
    fixtures.set_clock(api, "2026-09-05T00:00:00Z")

    refused = api.acknowledge_disclosure(
        world["d1"], fixtures.make_buyer_headers(world["b1"])
    )
    validate_error(refused, "ERR_ABA_DISCLOSURE_CURE_EXPIRED", 409)

    still = fixtures.read_disclosure(api, world["d1"])
    assert still["disclosure_status"] == "CURING", still["disclosure_status"]


def test_lock_expiry_returns_the_contract_and_reverts_its_acknowledged_disclosure(api):
    """One clock call moves three rows: lock, contract and disclosure.

    PRD §2.13: "a rate lock whose `lock_expires_iso` has passed moves from `ACTIVE` to
    `EXPIRED`".
    PRD §3.5: "the void cascades the contract from `LOCKED` back to `PENDING`: its
    acknowledged disclosures revert to `ISSUED`, the buyer drops from `QUALIFIED` to
    `CONTRACTED`".
    Design: Corner/state_machines/rate_lock_expiry_reverts_contract_and_disclosure_bubble_up
    """
    world = fixtures.setup_contract_with_aba(
        api, construction_stage="DRYWALL", target_state="LOCKED", lock_days=30
    )
    before = fixtures.read_disclosure(api, world["d1"])
    assert before["disclosure_status"] == "ACKNOWLEDGED", before["disclosure_status"]

    fixtures.set_clock(api, "2026-10-05T00:00:00Z")

    lock = fixtures.read_rate_lock(api, world["lk1"])
    assert lock["lock_status"] == "EXPIRED", lock["lock_status"]

    contract = fixtures.read_contract(api, world["ct1"])
    assert contract["contract_status"] == "PENDING", (
        f"the expiry pushes the contract back, got {contract['contract_status']}"
    )

    disclosure = fixtures.read_disclosure(api, world["d1"])
    assert disclosure["disclosure_status"] == "ISSUED", (
        f"the acknowledged form reverts when the lock lapses, got {disclosure['disclosure_status']}"
    )


def test_the_lock_lapse_also_drops_the_buyer_out_of_the_contracted_posture(api):
    """The buyer's aggregate posture falls from CONTRACTED to QUALIFIED with the contract.

    PRD §3.3: "`buyer_status` is a bubble-up aggregate over the buyer's contracts and
    applications, and each move is either a cascade from a child state change or one of
    the two documented operator actions."
    PRD §3.5: "the buyer drops from `QUALIFIED` to `CONTRACTED`".
    Design: Corner/state_machines/rate_lock_expiry_reverts_contract_and_disclosure_bubble_up
    """
    world = fixtures.setup_contract_with_aba(
        api, construction_stage="DRYWALL", target_state="LOCKED", lock_days=30
    )
    fixtures.set_clock(api, "2026-10-05T00:00:00Z")

    assert fixtures.read_rate_lock(api, world["lk1"])["lock_status"] == "EXPIRED"
    buyer = fixtures.read_buyer(api, world["b1"])
    assert buyer["buyer_status"] == "CONTRACTED", (
        f"the buyer comes back down with the contract, got {buyer['buyer_status']}"
    )