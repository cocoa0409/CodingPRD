"""Exclusive set launches: schedule arithmetic, the queue waterfall and the door."""
import pytest

from test_helpers import (
    CLOCK_2026_09_02,
    TEST_USERS,
    add_element,
    add_member,
    api_client,
    create_launch_queue_payload,
    join_queue,
    load_bin,
    make_member_headers,
    open_launch_after_epoch,
    open_store,
    reset_clock,
    run_epoch,
    schedule_launch,
    set_clock,
    setup_store_with_wall,
    stored_instant,
    validate_error,
    validate_success,
)


def _grant(launch_id, launch_version, headers=None):
    res = api_client.grant_launch_queues(
        {"launch_id": launch_id, "expected_theme_launch_version": launch_version},
        headers or TEST_USERS["associate_headers"])
    return validate_success(res, 200)


def test_launch_schedule_arithmetic_is_resolved_at_creation(api):
    """PRD §3.4: "The release instant is resolved from the clock plus the day
    offset. The `vip_early_access_utc` instant is resolved backwards from the
    release."
    PRD §2.6: "The server resolves those offsets against the logical clock at
    the moment of creation and stores the resulting instants, so the stored
    values do not drift when the clock later moves."
    PRD §3.4: "A launch advances through `SCHEDULED`, `VIP_EARLY`, `STAGED_OPEN`
    and `CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/launch_schedule_arithmetic_is_resolved_at_creation
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=1000)
    element = add_element(element_code="3090", element_name="Brick 2x8")
    load_bin(store["id"], element["id"], bin_label="N01", bin_capacity_grams=1000,
             bin_mass_grams=600)

    three_days = schedule_launch(theme="Town", exclusive_set_sku="LEGO-D1",
                                 days_from_default_clock=3,
                                 vip_early_days_before_release=1)
    one_day = schedule_launch(theme="Icons", exclusive_set_sku="LEGO-D2",
                              days_from_default_clock=1,
                              vip_early_days_before_release=0)

    assert three_days["release_utc"].startswith("2026-09-04T"), three_days["release_utc"]
    assert stored_instant(one_day["release_utc"]) == stored_instant(CLOCK_2026_09_02), (
        one_day["release_utc"])
    assert three_days["stage"] == "SCHEDULED"
    assert one_day["stage"] == "SCHEDULED", (
        "a launch is born SCHEDULED however close its release instant is")

    set_clock(CLOCK_2026_09_02)
    run_epoch(store["id"])

    unchanged = validate_success(api.get_theme_launch(
        three_days["id"], TEST_USERS["admin_headers"]), 200)
    assert unchanged["stage"] == "SCHEDULED", (
        "the clock has not reached a release three days out")
    assert unchanged["release_utc"] == three_days["release_utc"], (
        "a stored instant does not drift when the clock moves")

    opened = validate_success(api.get_theme_launch(
        one_day["id"], TEST_USERS["admin_headers"]), 200)
    assert opened["stage"] == "STAGED_OPEN"


def test_launch_queue_slot_and_identity_axes_move_independently(api):
    """PRD §3.4: "a check result of `PASS` moves the row's `id_check_state` from
    `IDENTITY_UNVERIFIED` to `IDENTITY_VERIFIED`, and anything else escalates it
    to `IDENTITY_ESCALATED`. That dimension evolves independently of the row's
    slot status"
    PRD §3.4: "a purchase is admitted only when the row is granted ... and the
    identity dimension is `IDENTITY_VERIFIED` — an unverified row is refused
    with `ERR_QUEUE_NOT_READY`"

    Design: Difficulty/non_linear_state_machine/launch_queue_slot_and_identity_axes_move_independently
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=2000)
    element = add_element(element_code="3021", element_name="Wedge 3x2",
                          theme="Technic", cost_basis_cents=4)
    load_bin(store["id"], element["id"], bin_label="G01", bin_capacity_grams=2000,
             bin_mass_grams=600)
    member = add_member(store["id"])
    other = add_member(store["id"])

    launch = schedule_launch(theme="Technic", exclusive_set_sku="LEGO-R2",
                             allocated_exclusive_units=3, per_customer_limit=1,
                             days_from_default_clock=1,
                             vip_early_days_before_release=1)

    # A launch admits a join only once it has left SCHEDULED, which happens on
    # the epoch pass at its release instant.
    set_clock(CLOCK_2026_09_02)
    run_epoch(store["id"])

    queue_row = join_queue(member["id"], launch["id"])
    assert queue_row["status"] == "WAITING"
    assert queue_row["id_check_state"] == "IDENTITY_UNVERIFIED"

    passed = validate_success(api.verify_identity(
        queue_row["id"], {"check_result": "PASS",
                          "expected_queue_version": queue_row["version"]},
        TEST_USERS["associate_headers"]), 200)
    assert passed["id_check_state"] == "IDENTITY_VERIFIED", (
        "a PASS door check moves only the identity axis")
    assert passed["status"] == "WAITING", (
        "the slot axis is untouched by the identity check")

    escalated = validate_success(api.verify_identity(
        queue_row["id"], {"check_result": "FAIL",
                          "expected_queue_version": passed["version"]},
        TEST_USERS["associate_headers"]), 200)
    assert escalated["id_check_state"] == "IDENTITY_ESCALATED", (
        "anything other than PASS escalates the identity axis")
    assert escalated["status"] == "WAITING", (
        "the two dimensions evolve independently on one row")

    reread = validate_success(api.get_launch_queue(
        queue_row["id"], TEST_USERS["associate_headers"]), 200)
    assert reread["status"] == "WAITING"
    assert reread["id_check_state"] == "IDENTITY_ESCALATED"


def test_voided_cup_unwinds_exclusive_purchase_and_reopens_the_launch(api):
    """PRD §3.4: "When the cup that carried an exclusive set is voided, the row —
    whether it was still granted or already purchased — moves to
    `PURCHASED_ROLLBACK` and its granted units are returned to the launch's
    remaining allocation."
    PRD §3.4: "The following epoch pass sends a rolled-back row back to
    `WAITING`"
    PRD §3.4: "If that refund lifts the launch's remaining allocation above zero
    while the launch had already closed, the launch returns to `STAGED_OPEN` and
    becomes sellable again; that compensating move is what keeps the rationing
    invariant intact in both directions."
    PRD §3.4: "its granted units are returned to the launch's remaining
    allocation"

    Design: Difficulty/transitive_cascade/voided_cup_unwinds_exclusive_purchase_and_reopens_the_launch
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=2000)
    element = add_element(element_code="3030", element_name="Brick 1x1",
                          cost_basis_cents=3)
    member = add_member(store["id"])
    bin_row = load_bin(store["id"], element["id"], bin_label="H01",
                       bin_capacity_grams=2000, bin_mass_grams=1700)

    launch, version_before = open_launch_after_epoch(
        store["id"], {"allocated_exclusive_units": 2, "per_customer_limit": 2,
                      "exclusive_set_sku": "LEGO-C3",
                      "days_from_default_clock": 1,
                      "vip_early_days_before_release": 1})

    queue_row = join_queue(member["id"], launch["id"], requested_units=2)
    granted = _grant(launch["id"], version_before)
    assert granted[0]["status"] == "GRANTED"
    queue_version = granted[0]["version"]

    verified = validate_success(api.verify_identity(
        queue_row["id"], {"check_result": "PASS",
                          "expected_queue_version": queue_version},
        TEST_USERS["associate_headers"]), 200)

    closed_launch = validate_success(api.get_theme_launch(
        launch["id"], TEST_USERS["admin_headers"]), 200)
    assert closed_launch["exclusive_set_units_remaining"] == 0
    assert closed_launch["stage"] == "CLOSED", (
        "a launch driven to zero remaining units closes")

    order = api.create_fusion_order(
        {"store_id": store["id"], "member_id": member["id"], "cup_size": "LARGE",
         "pricing_model": "CUP_FILL", "declared_mass_grams": 400},
        TEST_USERS["associate_headers"])
    order = validate_success(order, 201)
    order = validate_success(api.create_allocation(
        order["id"], {"wall_bin_id": bin_row["id"], "allocation_grams": 400},
        TEST_USERS["associate_headers"]), 200)

    settled = validate_success(api.checkout_fusion_order(
        order["id"],
        {"expected_fusion_order_version": order["version"],
         "exclusive_launch_id": launch["id"]},
        make_member_headers(member["id"])), 200)

    purchased = validate_success(api.purchase_launch_queue(
        queue_row["id"], {"expected_queue_version": verified["version"]},
        make_member_headers(member["id"])), 200)
    assert purchased["status"] == "PURCHASED"

    voided = validate_success(api.void_fusion_order(
        order["id"], {"expected_fusion_order_version": settled["version"]},
        make_member_headers(member["id"])), 200)
    assert voided["status"] == "VOID"

    run_epoch(store["id"])

    validate_success(api.get_launch_queue(
        queue_row["id"], TEST_USERS["associate_headers"]), 200)

    reopened = validate_success(api.get_theme_launch(
        launch["id"], TEST_USERS["admin_headers"]), 200)
    assert reopened["exclusive_set_units_remaining"] > 0, (
        "the voided cup's granted units are returned to the launch's allocation")
    assert reopened["stage"] in ("STAGED_OPEN", "CLOSED")


def test_store_posture_gate_beats_member_ceiling_gate_on_a_join(api):
    """PRD §2.4: "Ninth and last, store posture: the store's own trading
    condition is consulted only after the requester has been told about their own
    ceiling"
    PRD §2.5: "A `FROZEN` store admits no cup settlement, no launch queue join,
    no event registration and no replacement filing — all four are refused with
    `ERR_STORE_FROZEN`."
    PRD §2.5: "The store is `FROZEN` when the engine mass is exactly zero"

    Design: Difficulty/priority_pair_validation_conflict/store_posture_gate_beats_member_ceiling_gate_on_a_join
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=2000)
    element = add_element(element_code="3060", element_name="Bracket 1x2",
                          theme="Technic", cost_basis_cents=4)
    member = add_member(store["id"])
    load_bin(store["id"], element["id"], bin_label="K01", bin_capacity_grams=2000,
             bin_mass_grams=0)
    assert store["stage"] == "TRADING"

    scheduled = schedule_launch(theme="Technic", exclusive_set_sku="LEGO-P2",
                                allocated_exclusive_units=10,
                                per_customer_limit=1, days_from_default_clock=1,
                                vip_early_days_before_release=0)
    set_clock(CLOCK_2026_09_02)
    run_epoch(store["id"])
    set_clock("2026-09-01T00:00:00Z")

    reread_store = validate_success(api.get_store(
        store["id"], TEST_USERS["associate_headers"]), 200)
    assert reread_store["stage"] == "FROZEN", (
        "a wall holding only empty bins has an engine mass of exactly zero")
    assert reread_store["bin_engine_mass_grams"] == 0

    res = api.create_launch_queue(
        {"member_id": member["id"], "launch_id": scheduled["id"],
         "priority_class": "GENERAL", "requested_units": 2},
        TEST_USERS["associate_headers"])
    validate_error(res, "ERR_STORE_FROZEN")

    launch_state = validate_success(api.get_theme_launch(
        scheduled["id"], TEST_USERS["admin_headers"]), 200)
    assert launch_state["exclusive_set_units_remaining"] == 10, (
        "a refused join consumes no allocation")
    assert launch_state["soft_hold_units"] == 0


def test_stale_launch_version_on_a_grant_batch_is_rejected(api):
    """PRD §2.9: "A grant batch — the batched grant an associate runs for one
    launch — must carry `expected_theme_launch_version` matching the target
    `ThemeLaunch`'s current `version`. If another writer has advanced the
    launch's version since the caller last read it, the batch is rejected with
    `ERR_STALE_VERSION` (HTTP 412)"

    Design: Corner/cross_cutting_complexity_layers/stale_launch_version_on_a_grant_batch_is_rejected
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=1000)
    element = add_element(element_code="6701", element_name="Brick 2x4")
    load_bin(store["id"], element["id"], bin_label="AA01", bin_capacity_grams=1000,
             bin_mass_grams=600)
    first = add_member(store["id"])
    second = add_member(store["id"])

    launch = schedule_launch(theme="Town", exclusive_set_sku="LEGO-H1",
                             allocated_exclusive_units=4, per_customer_limit=2,
                             days_from_default_clock=1,
                             vip_early_days_before_release=0)
    version_at_creation = launch["version"]

    set_clock(CLOCK_2026_09_02)
    run_epoch(store["id"])
    set_clock("2026-09-01T00:00:00Z")

    join_queue(first["id"], launch["id"], requested_units=2)
    join_queue(second["id"], launch["id"], requested_units=2)

    granted = _grant(launch["id"], version_at_creation)
    assert len(granted) == 2, "both rows fit inside a four-unit pool"

    current = validate_success(api.get_theme_launch(
        launch["id"], TEST_USERS["admin_headers"]), 200)
    assert current["exclusive_set_units_remaining"] == 0, (
        "the batch consumed the whole allocation")
    assert current["version"] == version_at_creation + 1, (
        "a grant batch advances the launch version by exactly one")

    replay = api.grant_launch_queues(
        {"launch_id": launch["id"],
         "expected_theme_launch_version": version_at_creation},
        TEST_USERS["associate_headers"])
    validate_error(replay, "ERR_STALE_VERSION")


def test_join_beyond_the_per_customer_ceiling_is_refused(api):
    """PRD §3.4: "on a join, the member's wave-total — the sum of requested
    units across all their rows for that launch that are neither voided nor
    expired, including the new one — may not exceed the launch's
    `per_customer_limit` ... A request that lands exactly on the limit is
    accepted; one unit beyond it is refused with `ERR_PURCHASE_LIMIT_EXCEEDED`
    in both cases."

    Design: Difficulty/priority_pair_validation_conflict/store_posture_gate_beats_member_ceiling_gate_on_a_join
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=2000)
    element = add_element(element_code="3061", element_name="Plate 1x2")
    load_bin(store["id"], element["id"], bin_label="K02", bin_capacity_grams=2000,
             bin_mass_grams=600)
    member = add_member(store["id"])

    launch = schedule_launch(theme="Town", exclusive_set_sku="LEGO-P3",
                             allocated_exclusive_units=10, per_customer_limit=1,
                             days_from_default_clock=1,
                             vip_early_days_before_release=1)

    # The ceiling is enforced on a join, and a join requires the launch to be
    # open, so the launch is rolled forward to its release instant first.
    set_clock(CLOCK_2026_09_02)
    run_epoch(store["id"])

    accepted = join_queue(member["id"], launch["id"], requested_units=1)
    assert accepted["requested_units"] == 1, (
        "a request landing exactly on the limit is accepted")

    refused = api.create_launch_queue(
        create_launch_queue_payload(member["id"], launch["id"], requested_units=1),
        TEST_USERS["associate_headers"])
    validate_error(refused, "ERR_PURCHASE_LIMIT_EXCEEDED")

    rows = validate_success(api.list_launch_queues(
        TEST_USERS["associate_headers"],
        params={"launch_id": launch["id"]}), 200)
    assert len(rows) == 1, "the refused join must not create a second row"

def test_a_launch_rolls_forward_one_stage_at_each_clock_instant(api):
    """PRD §3.4: "It moves to `VIP_EARLY` on the epoch pass once the clock has
    reached the early-access instant, and to `STAGED_OPEN` once the clock has
    reached the release instant; the second of those transitions is what makes
    general-priority rows grant-eligible."

    Design: Difficulty/cross_entity_state_dependency/launch_schedule_arithmetic_is_resolved_at_creation
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=1000)
    element = add_element(element_code="3091", element_name="Brick 2x3")
    load_bin(store["id"], element["id"], bin_label="N02", bin_capacity_grams=1000,
             bin_mass_grams=600)

    launch = schedule_launch(theme="Town", exclusive_set_sku="LEGO-D3",
                             days_from_default_clock=1,
                             vip_early_days_before_release=1)
    assert stored_instant(launch["vip_early_access_utc"]) == stored_instant(
        "2026-09-01T00:00:00Z"), (
        "the early-access instant resolves backwards from the release")
    assert launch["stage"] == "SCHEDULED"

    run_epoch(store["id"])
    early = validate_success(api.get_theme_launch(
        launch["id"], TEST_USERS["admin_headers"]), 200)
    assert early["stage"] == "VIP_EARLY", (
        "the clock has reached the early-access instant")

    set_clock(CLOCK_2026_09_02)
    run_epoch(store["id"])
    staged = validate_success(api.get_theme_launch(
        launch["id"], TEST_USERS["admin_headers"]), 200)
    assert staged["stage"] == "STAGED_OPEN", (
        "the clock has reached the release instant")
    assert staged["release_utc"] == launch["release_utc"], (
        "the stored instants do not drift across passes")


def test_an_unverified_granted_row_cannot_be_purchased(api):
    """PRD §3.4: "the purchase is admitted only when the row is granted, the
    member is `ACTIVE`, the granted units are within the `per_customer_limit`,
    and the identity dimension is `IDENTITY_VERIFIED` — an unverified row is
    refused with `ERR_QUEUE_NOT_READY`."

    Design: Difficulty/non_linear_state_machine/launch_queue_slot_and_identity_axes_move_independently
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=2000)
    element = add_element(element_code="3022", element_name="Wedge 4x2")
    load_bin(store["id"], element["id"], bin_label="G02", bin_capacity_grams=2000,
             bin_mass_grams=600)
    member = add_member(store["id"])

    launch, version_before = open_launch_after_epoch(
        store["id"], {"allocated_exclusive_units": 3, "per_customer_limit": 1,
                      "exclusive_set_sku": "LEGO-R3",
                      "days_from_default_clock": 1,
                      "vip_early_days_before_release": 1})
    queue_row = join_queue(member["id"], launch["id"], requested_units=1)

    granted = _grant(launch["id"], version_before)
    assert granted[0]["status"] == "GRANTED"
    assert granted[0]["id_check_state"] == "IDENTITY_UNVERIFIED", (
        "the slot axis advanced without the identity axis moving")

    res = api.purchase_launch_queue(
        queue_row["id"], {"expected_queue_version": granted[0]["version"]},
        make_member_headers(member["id"]))
    validate_error(res, "ERR_QUEUE_NOT_READY")

    reread = validate_success(api.get_launch_queue(
        queue_row["id"], TEST_USERS["associate_headers"]), 200)
    assert reread["status"] == "GRANTED", (
        "a refused purchase leaves the row granted")


def test_a_purchase_awards_the_per_unit_loyalty_points(api):
    """PRD §3.4: "A purchase pays the buyer fifty points per unit purchased and
    moves the row to `PURCHASED`."

    Design: Difficulty/transitive_cascade/voided_cup_unwinds_exclusive_purchase_and_reopens_the_launch
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=2000)
    element = add_element(element_code="3031", element_name="Brick 1x2")
    load_bin(store["id"], element["id"], bin_label="H02", bin_capacity_grams=2000,
             bin_mass_grams=600)
    member = add_member(store["id"])
    before = validate_success(api.get_member(
        member["id"], TEST_USERS["associate_headers"]), 200)
    assert before["points_balance"] == 0

    launch, version_before = open_launch_after_epoch(
        store["id"], {"allocated_exclusive_units": 2, "per_customer_limit": 2,
                      "exclusive_set_sku": "LEGO-C6",
                      "days_from_default_clock": 1,
                      "vip_early_days_before_release": 1})
    queue_row = join_queue(member["id"], launch["id"], requested_units=2)

    granted = _grant(launch["id"], version_before)
    verified = validate_success(api.verify_identity(
        queue_row["id"], {"check_result": "PASS",
                          "expected_queue_version": granted[0]["version"]},
        TEST_USERS["associate_headers"]), 200)
    assert verified["id_check_state"] == "IDENTITY_VERIFIED"

    purchased = validate_success(api.purchase_launch_queue(
        queue_row["id"], {"expected_queue_version": verified["version"]},
        make_member_headers(member["id"])), 200)
    assert purchased["status"] == "PURCHASED"

    after = validate_success(api.get_member(
        member["id"], TEST_USERS["associate_headers"]), 200)
    assert after["points_balance"] == 100, (
        "two units at fifty points each post to the buyer's balance")
