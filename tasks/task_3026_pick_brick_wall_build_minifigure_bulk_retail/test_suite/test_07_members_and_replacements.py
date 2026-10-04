"""Members, loyalty points, replacement valuations and the conserving voids."""
import pytest

from test_helpers import (
    TEST_USERS,
    add_element,
    add_member,
    api_client,
    file_replacement,
    load_bin,
    make_member_headers,
    open_store,
    post_ledger,
    reset_clock,
    reinstate_member,
    setup_prospect_request,
    setup_store_with_wall,
    setup_surplus_element,
    suspend_member,
    validate_error,
    validate_success,
)


def test_member_cycles_between_active_and_suspended(api):
    """PRD §3.3: "A restricted member returns to `ACTIVE` on the final epoch
    pass when the no-show count has fallen below that threshold and the home
    store is not frozen — the restriction is a sanction with a defined exit, not
    a trap."
    PRD §3.3: "Reinstatement is an associate action that returns a suspended
    member to `ACTIVE`, resets their pass count to zero, and additionally
    requires that the member's home store hold at least a quarter of its declared
    wall capacity in live engine mass."

    Design: Difficulty/non_linear_state_machine/member_cycles_between_active_and_suspended
    """
    store, element, member, bin_row = setup_store_with_wall(
        store_overrides={"wall_bin_capacity_grams": 2000},
        bin_overrides={"bin_capacity_grams": 2000, "bin_mass_grams": 600})
    assert store["stage"] == "TRADING"
    assert member["stage"] == "ACTIVE"

    suspended_once = suspend_member(member["id"], "POLICY_REVIEW")
    assert suspended_once["stage"] == "SUSPENDED"

    reinstated = reinstate_member(member["id"])
    assert reinstated["stage"] == "ACTIVE", (
        "600 g clears the quarter-capacity reinstatement floor of a 2000 g wall")

    suspended_twice = suspend_member(member["id"], "SECOND_REVIEW")
    assert suspended_twice["stage"] == "SUSPENDED", (
        "the ACTIVE to SUSPENDED edge re-fires after reinstatement")

    final = reinstate_member(member["id"])
    assert final["stage"] == "ACTIVE"

    reread = validate_success(api.get_member(member["id"],
                                             TEST_USERS["associate_headers"]), 200)
    assert reread["stage"] == "ACTIVE"
    assert reread["passed_mb_reservations"] == 0, (
        "reinstatement resets the passed-reservation count")
    assert reread["version"] == 5, (
        "creation plus two suspensions and two reinstatements is five versions")


def test_replacement_ceiling_beats_sourcing_rule_on_one_filing(api):
    """PRD §3.7: "Every filing is measured against a personal ceiling before
    anything else about the element is considered, which is the deliberate
    inversion of the ordinary validation order described in §2.4."
    PRD §3.7: "When that count has already reached one, the filing is refused
    with `ERR_REPLACEMENT_LIMIT_REACHED` — landing exactly on the limit is a
    refusal, and being below it is an admission."
    PRD §2.4: "One endpoint deliberately inverts two rungs."

    Design: Difficulty/priority_pair_validation_conflict/replacement_ceiling_beats_sourcing_rule_on_one_filing
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=2000)
    sourced = add_element(element_code="3050", element_name="Brick 1x2",
                          cost_basis_cents=4)
    unsourced = add_element(element_code="3051", element_name="Brick 1x1 Round",
                            cost_basis_cents=3)
    member = add_member(store["id"])
    load_bin(store["id"], sourced["id"], bin_label="J01", bin_capacity_grams=2000,
             bin_mass_grams=600)
    load_bin(store["id"], unsourced["id"], bin_label="J02",
             bin_capacity_grams=2000, bin_mass_grams=0)
    # The surplus element must be retired before it can be named on a filing, and
    # a named-but-unregistered request is DENIED by the sourcing fork.
    retired = validate_success(api.retire_element(
        unsourced["id"], {"expected_element_version": unsourced["version"]},
        TEST_USERS["associate_headers"]), 200)
    assert retired["sourcing_mode"] == "SURPLUS"

    first = file_replacement(store["id"], member["id"], unsourced["id"],
                             member["version"])
    assert first["stage"] == "PROSPECT", (
        "a surplus-sourced element under the ceiling lands in PROSPECT")
    assert first["earned_points"] == 0, (
        "points are awarded on claim or completion, never on filing")

    refreshed = validate_success(api.get_member(member["id"],
                                                TEST_USERS["associate_headers"]), 200)

    # The second filing names a LIVE element that the sourcing fork would refuse,
    # yet the personal ceiling is consulted first: the caller hears about their
    # own ceiling rather than the sourcing story.
    second = api.create_replacement_request(
        {"store_id": store["id"], "member_id": member["id"],
         "element_id": sourced["id"], "quantity_missing": 1,
         "proof_of_purchase_supplied": False, "window_days": 30,
         "expected_member_version": refreshed["version"]},
        TEST_USERS["associate_headers"])
    validate_error(second, "ERR_REPLACEMENT_LIMIT_REACHED")


def test_replacement_claim_and_completion_award_different_points(api):
    """PRD §3.7: "A request that the member claims inside its window moves to
    `CLAIMED` and awards points derived from the element's wholesale cost basis:
    `quantity_missing` multiplied by the element's `cost_basis_cents`,
    multiplied by a valuation rate of ten percent, rounded half up to a whole
    number of points."
    PRD §3.7: "A request fulfilled by the store instead awards a flat good-will
    credit of twenty-five points per missing unit, with no reference to cost
    basis at all."

    Design: Difficulty/combinatorial_formula/replacement_claim_and_completion_award_different_points
    """
    store, element, member, request, _version = setup_prospect_request(
        quantity_missing=5, store_overrides={"wall_bin_capacity_grams": 2000},
        element_overrides={"element_code": "3010", "element_name": "Plate 1x2",
                           "cost_basis_cents": 6})
    assert request["stage"] == "PROSPECT"
    assert request["window_days"] == 30

    claimed = validate_success(api.claim_replacement_request(
        request["id"], make_member_headers(member["id"])), 200)
    assert claimed["stage"] == "CLAIMED"
    assert claimed["earned_points"] == 3, (
        "5 units at a 6-cent basis and a tenth valuation rate is 3 points")

    store2, element2, member2, request2, _v2 = setup_prospect_request(
        quantity_missing=5, store_overrides={"wall_bin_capacity_grams": 2000},
        element_overrides={"element_code": "3011", "element_name": "Plate 1x4",
                           "cost_basis_cents": 6})
    completed = validate_success(api.complete_replacement_request(
        request2["id"], TEST_USERS["associate_headers"]), 200)
    assert completed["stage"] == "COMPLETED"
    assert completed["earned_points"] == 125, (
        "the flat good-will credit is twenty-five points per missing unit")
    assert completed["earned_points"] > claimed["earned_points"], (
        "the completion credit is orders of magnitude larger than the claim valuation")


def test_the_completion_credit_is_not_adjusted_when_the_element_is_retired(api):
    """PRD §3.7: "The completion credit is not adjusted if the element is
    subsequently retired."

    Design: Difficulty/combinatorial_formula/replacement_claim_and_completion_award_different_points
    """
    store, element, member, request, _version = setup_prospect_request(
        quantity_missing=4, store_overrides={"wall_bin_capacity_grams": 2000},
        element_overrides={"element_code": "3012", "element_name": "Plate 1x6",
                           "cost_basis_cents": 9})

    completed = validate_success(api.complete_replacement_request(
        request["id"], TEST_USERS["associate_headers"]), 200)
    assert completed["earned_points"] == 100, (
        "four missing units pay twenty-five points each, whatever the basis")

    refreshed = validate_success(api.get_replacement_request(
        request["id"], TEST_USERS["associate_headers"]), 200)
    assert refreshed["earned_points"] == 100, (
        "the posted award is not recomputed on a later read")
    assert refreshed["stage"] == "COMPLETED"


def test_additive_points_ledger_conserves_the_member_balance(api):
    """PRD §3.3: "Points are recorded as a ledger, not as a counter. Each entry
    names the member, an `entry_kind` of `REDEMPTION`, `REPLACEMENT_GRANT` or
    `MANUAL_ADJUSTMENT`, a signed `points_delta` that must be non-zero, and an
    operator-facing `reason`. A negative delta is a redemption or a correction, a
    positive one an award."
    PRD §3.3: "The member's `points_balance` is the running sum of those signed
    movements plus whatever replacement-request awards have posted."

    Design: Difficulty/compensating_invariant/additive_points_ledger_conserves_the_member_balance
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=1000)
    element = add_element(element_code="3140", element_name="Trans Clear Plate",
                          cost_basis_cents=3)
    member = add_member(store["id"])
    other = add_member(store["id"])
    load_bin(store["id"], element["id"], bin_label="T01", bin_capacity_grams=1000,
             bin_mass_grams=600)

    post_ledger(member["id"], "MANUAL_ADJUSTMENT", 500, "Welcome bonus")
    after_bonus = validate_success(api.get_member(
        member["id"], TEST_USERS["admin_headers"]), 200)
    assert after_bonus["points_balance"] == 500

    post_ledger(member["id"], "REDEMPTION", -250, "In-store reward")
    after_redemption = validate_success(api.get_member(
        member["id"], TEST_USERS["admin_headers"]), 200)
    assert after_redemption["points_balance"] == 250, (
        "a negative delta is a redemption against the running balance")

    post_ledger(other["id"], "MANUAL_ADJUSTMENT", 250, "Replacement grant")
    after_grant = validate_success(api.get_member(
        other["id"], TEST_USERS["admin_headers"]), 200)
    assert after_grant["points_balance"] == 250

    assert after_redemption["points_balance"] + after_grant["points_balance"] == 500, (
        "a positive posting, a negative posting and a compensating grant move a "
        "closed total with nothing created or destroyed")


def test_void_then_recheckout_conserves_the_wall_engine_mass(api):
    """PRD §3.2: "Voiding a cup returns its mass to the wall. The member voids
    their own cup, supplying the expected version, and every draw recorded
    against that cup is reversed in full: each bin gains back exactly the grams
    it gave up, its status is recomputed from the restored fullness, and the
    store's engine mass and posture are re-derived."
    PRD §2.5: "Because posture is re-derived rather than latched, a voided cup
    that returns mass to the bins can lift a frozen store back through
    `RESTRICTED` and on to `TRADING` in consecutive recomputations."

    Design: Difficulty/compensating_invariant/void_then_checkout_again_conserves_the_wall_engine_mass
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=2000)
    element = add_element(element_code="3130", element_name="Technic Pin",
                          theme="Technic", cost_basis_cents=2)
    member = add_member(store["id"])
    bin_row = load_bin(store["id"], element["id"], bin_label="S01",
                       bin_capacity_grams=2000, bin_mass_grams=600)

    order = api.create_fusion_order(
        {"store_id": store["id"], "member_id": member["id"], "cup_size": "LARGE",
         "pricing_model": "CUP_FILL", "declared_mass_grams": 400},
        TEST_USERS["associate_headers"])
    order = validate_success(order, 201)
    order = validate_success(api.create_allocation(
        order["id"], {"wall_bin_id": bin_row["id"], "allocation_grams": 400},
        TEST_USERS["associate_headers"]), 200)

    drawn = validate_success(api.get_wall_bin(
        bin_row["id"], TEST_USERS["associate_headers"]), 200)
    assert drawn["bin_mass_grams"] == 200, (
        "the draw subtracts exactly the grams it took")

    settled = validate_success(api.checkout_fusion_order(
        order["id"], {"expected_fusion_order_version": order["version"]},
        make_member_headers(member["id"])), 200)

    voided = validate_success(api.void_fusion_order(
        order["id"], {"expected_fusion_order_version": settled["version"]},
        make_member_headers(member["id"])), 200)
    assert voided["status"] == "VOID"

    restored = validate_success(api.get_wall_bin(
        bin_row["id"], TEST_USERS["associate_headers"]), 200)
    assert restored["bin_mass_grams"] == 600, (
        "the reversal restores the opening mass exactly")

    store_after = validate_success(api.get_store(
        store["id"], TEST_USERS["associate_headers"]), 200)
    assert store_after["bin_engine_mass_grams"] == 600, (
        "the store's engine mass is back where it started, with zero drift")


def test_stale_member_version_on_a_replacement_filing_is_rejected(api):
    """PRD §2.9: "Filing a replacement request — a replacement filing made on a
    member's behalf — must carry `expected_member_version` matching the target
    `Member`'s current `version`. If another writer has advanced the member's
    version since the caller last read it, the filing is rejected with
    `ERR_MEMBER_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_member_version_on_a_replacement_filing_is_rejected
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=1000)
    element = setup_surplus_element(store["id"], {"element_code": "6901",
                                                  "element_name": "Brick 1x2",
                                                  "cost_basis_cents": 4})
    member = add_member(store["id"])
    version_at_creation = member["version"]

    first = file_replacement(store["id"], member["id"], element["id"],
                             version_at_creation)
    assert first["stage"] == "PROSPECT"

    replay = api.create_replacement_request(
        {"store_id": store["id"], "member_id": member["id"],
         "element_id": element["id"], "quantity_missing": 1,
         "proof_of_purchase_supplied": False, "window_days": 30,
         "expected_member_version": version_at_creation},
        TEST_USERS["associate_headers"])
    validate_error(replay, "ERR_MEMBER_STALE_VERSION")

    refreshed = validate_success(api.get_member(member["id"],
                                                TEST_USERS["associate_headers"]), 200)
    assert refreshed["version"] == version_at_creation + 1, (
        "the first filing advanced the member version exactly once")

    rows = validate_success(api.list_replacement_requests(
        TEST_USERS["associate_headers"], params={"member_id": member["id"]}), 200)
    assert len(rows) == 1, "the replayed filing must not create a second request"


def test_foreign_member_cannot_claim_another_members_prospect(api):
    """PRD §2.1: "When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the
    acting `Member` record itself. Ownership checks on any resource that
    references a `Member` — a cup, a build, a reservation, a queue row, a
    replacement request, a ledger line — compare that resource's foreign-key
    field to `X-User-ID`, and a member attempting to act on another member's row
    is refused with `ERR_FORBIDDEN`."

    Design: Corner/rbac/member_cannot_claim_another_members_replacement_request
    """
    store, element, owner, request, _version = setup_prospect_request(
        quantity_missing=1, store_overrides={"wall_bin_capacity_grams": 1000})
    intruder = add_member(store["id"])

    res = api.claim_replacement_request(request["id"],
                                        make_member_headers(intruder["id"]))
    validate_error(res, "ERR_FORBIDDEN")

    reread = validate_success(api.get_replacement_request(
        request["id"], TEST_USERS["associate_headers"]), 200)
    assert reread["stage"] == "PROSPECT", (
        "a foreign claim leaves the prospect untouched")
    assert reread["earned_points"] == 0

    intruder_state = validate_success(api.get_member(
        intruder["id"], TEST_USERS["associate_headers"]), 200)
    assert intruder_state["points_balance"] == 0, (
        "the refused claim posts no points to the intruder")


def test_owner_can_claim_their_own_prospect(api):
    """PRD §3.7: "Claiming is a member action on their own prospect and is
    admitted only while the clock is strictly before `window_expires_utc`, under
    an `ACTIVE` member."

    Design: Corner/rbac/member_cannot_claim_another_members_replacement_request
    """
    store, element, owner, request, _version = setup_prospect_request(
        quantity_missing=1, store_overrides={"wall_bin_capacity_grams": 1000})
    assert owner["stage"] == "ACTIVE"

    claimed = validate_success(api.claim_replacement_request(
        request["id"], make_member_headers(owner["id"])), 200)
    assert claimed["stage"] == "CLAIMED"

    owner_state = validate_success(api.get_member(
        owner["id"], TEST_USERS["associate_headers"]), 200)
    assert owner_state["points_balance"] == claimed["earned_points"], (
        "the award posts to the owning member's balance")


def test_frozen_store_blocks_a_replacement_filing(api):
    """PRD §2.5: "A `FROZEN` store admits no cup settlement, no launch queue
    join, no event registration and no replacement filing — all four are refused
    with `ERR_STORE_FROZEN`."
    PRD §2.5: "The store is `FROZEN` when the engine mass is exactly zero, or
    when at least three distinct members whose `home_store_id` is this store have
    `stage` of `SUSPENDED`"

    Design: Corner/errors/frozen_store_blocks_a_replacement_filing
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=1000)
    element = add_element(element_code="6001", element_name="Brick 2x2 Corner",
                          cost_basis_cents=5)
    member = add_member(store["id"])
    load_bin(store["id"], element["id"], bin_label="T01", bin_capacity_grams=1000,
             bin_mass_grams=0)
    retired = validate_success(api.retire_element(
        element["id"], {"expected_element_version": element["version"]},
        TEST_USERS["associate_headers"]), 200)
    assert retired["sourcing_mode"] == "SURPLUS"

    reread = validate_success(api.get_store(
        store["id"], TEST_USERS["associate_headers"]), 200)
    assert reread["stage"] == "FROZEN", (
        "a wall whose only bin is empty has an engine mass of exactly zero")

    res = api.create_replacement_request(
        {"store_id": store["id"], "member_id": member["id"],
         "element_id": element["id"], "quantity_missing": 1,
         "proof_of_purchase_supplied": False, "window_days": 30,
         "expected_member_version": member["version"]},
        TEST_USERS["associate_headers"])
    validate_error(res, "ERR_STORE_FROZEN")

    rows = validate_success(api.list_replacement_requests(
        TEST_USERS["associate_headers"], params={"store_id": store["id"]}), 200)
    assert rows == [], "a refused filing creates no request"

def test_replacement_claim_points_round_half_up_to_a_whole_point(api):
    """PRD §3.7: "A request that the member claims inside its window moves to
    `CLAIMED` and awards points derived from the element's wholesale cost basis:
    `quantity_missing` multiplied by the element's `cost_basis_cents`,
    multiplied by a valuation rate of ten percent, rounded half up to a whole
    number of points."
    PRD §3.7: "the `window_expires_utc` is that approval instant plus the
    requested number of days, evaluated against the logical clock."

    Design: Corner/calculations/replacement_claim_points_round_to_the_nearest_integer
    """
    store, element, member, request, _version = setup_prospect_request(
        quantity_missing=1, store_overrides={"wall_bin_capacity_grams": 1000},
        element_overrides={"element_code": "5101", "element_name": "Tile 1x1",
                           "cost_basis_cents": 5})
    assert request["stage"] == "PROSPECT", (
        "a surplus-sourced element under the ceiling lands in PROSPECT")
    assert request["earned_points"] == 0, (
        "a claim awards points only when it is made")
    assert request["window_expires_utc"].startswith("2026-10-01T"), (
        "the window runs thirty days forward from the approval instant")


def test_proof_of_purchase_never_raises_the_trailing_ceiling(api):
    """PRD §3.7: "Proof of purchase is never required, and supplying it changes
    nothing about how the request is treated: it does not improve the outcome,
    does not raise the trailing ceiling, and does not affect the points later
    awarded."

    Design: Difficulty/priority_pair_validation_conflict/replacement_ceiling_beats_sourcing_rule_on_one_filing
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=1000)
    element = setup_surplus_element(store["id"], {"element_code": "3052",
                                                  "element_name": "Brick 1x4"})
    member = add_member(store["id"])

    first = file_replacement(store["id"], member["id"], element["id"],
                             member["version"], quantity_missing=1,
                             proof_of_purchase_supplied=True)
    assert first["stage"] == "PROSPECT", (
        "a receipt does not change how the filing is treated")
    assert first["proof_of_purchase_supplied"] is True

    refreshed = validate_success(api.get_member(member["id"],
                                                TEST_USERS["associate_headers"]), 200)

    second = api.create_replacement_request(
        {"store_id": store["id"], "member_id": member["id"],
         "element_id": element["id"], "quantity_missing": 1,
         "proof_of_purchase_supplied": True, "window_days": 30,
         "expected_member_version": refreshed["version"]},
        TEST_USERS["associate_headers"])
    validate_error(second, "ERR_REPLACEMENT_LIMIT_REACHED")


def test_a_ledger_entry_must_move_a_non_zero_points_delta(api):
    """PRD §3.3: "Each entry names the member, an `entry_kind` of `REDEMPTION`,
    `REPLACEMENT_GRANT` or `MANUAL_ADJUSTMENT`, a signed `points_delta` that must
    be non-zero, and an operator-facing `reason`."
    PRD §3.3: "A negative delta is a redemption or a correction, a positive one an
    award."

    Design: Difficulty/compensating_invariant/additive_points_ledger_conserves_the_member_balance
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=1000)
    member = add_member(store["id"])

    res = api.create_ledger_entry(
        {"member_id": member["id"], "entry_kind": "MANUAL_ADJUSTMENT",
         "points_delta": 0, "reason": "No-op"},
        TEST_USERS["admin_headers"])
    if res.status_code < 400:
        raise AssertionError(
            "a zero points movement is inadmissible, but the posting was "
            f"accepted: HTTP {res.status_code} {res.text}")

    after = validate_success(api.get_member(
        member["id"], TEST_USERS["admin_headers"]), 200)
    assert after["points_balance"] == 0, "a refused posting moves no points"

    post_ledger(member["id"], "REPLACEMENT_GRANT", -100, "Correction posted")
    corrected = validate_success(api.get_member(
        member["id"], TEST_USERS["admin_headers"]), 200)
    assert corrected["points_balance"] == -100, (
        "a negative delta is a correction against the running balance")
