"""Carrying a valuation freeze from one home to the next.

Only a freeze-enabled grant has anything to move, the amount moved is the
smallest of three figures, and frozen value is conserved: whatever leaves the
source's portable balance reappears as a child grant's frozen value.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_DESTINATION_NOT_OWNED,
    ERR_FRAUD_HOLD_ACTIVE,
    ERR_GRANT_ALREADY_TERMINAL,
    ERR_PORTABLE_BALANCE_EXHAUSTED,
    ERR_STALE_GRANT_VERSION,
)
from test_helpers.assertions import (
    assert_bps,
    assert_grant,
    assert_money,
    assert_parcel_decomposition,
)
from test_helpers.test_users import ANALYST, CLERK, INVESTIGATOR, REVIEWER


def _ported_freeze_world(api):
    """A senior freeze on the old home and a paid-for new home, then the transfer.

    The whole frozen balance of 33600000 is asked for, and the destination's
    pre-transfer basis of 40000000 is larger, so the requested figure is what
    moves and the source balance is emptied.
    """
    world = fx.approved_freeze_world(api)
    world["child"] = validate_success(
        api.port_grant(
            world["grant_id"],
            f.port_request(
                world["destination"]["id"], 33600000, world["grant_version"]
            ),
            REVIEWER,
        ),
        expected_status=201,
    )
    return world


def test_a_full_transfer_mints_a_traceable_child_grant_on_the_destination(api):
    """PRD §3.6: "Its `ported_from_grant_id` points at the source grant, making the
    portability chain traceable; its `frozen_value_cents` is the allocated amount
    and its own `portable_balance_cents` is 0, so a ported freeze cannot be ported
    onward; its `benefit_status` is `ACTIVE`." The child "takes its
    `ownership_pct_bps_snapshot` from the `ownership_pct_bps` of the destination's
    verified primary-residence record, names the destination in its `parcel_id`".

    Design: Difficulty/transitive_cascade/full_port_cascade_reprices_source_and_destination_parcels_from_one_transfer
    """
    world = _ported_freeze_world(api)
    child = world["child"]

    assert child["ported_from_grant_id"] == world["grant_id"], (
        "the child must name the grant it came from, got "
        f"{child['ported_from_grant_id']}"
    )
    assert child["parcel_id"] == world["destination"]["id"], (
        f"the child belongs to the destination parcel, got {child['parcel_id']}"
    )
    assert_bps(child, "ownership_pct_bps_snapshot", 10000)
    assert_grant(
        child,
        benefit_status="ACTIVE",
        frozen_value_cents=33600000,
        portable_balance_cents=0,
    )

    rows, meta = validate_paginated(
        api.list_grants(REVIEWER, ported_from_grant_id=world["grant_id"])
    )
    assert meta["total_count"] == 1, (
        f"one transfer means one child grant, got {meta['total_count']}"
    )
    assert rows[0]["id"] == child["id"], f"unexpected portability chain: {rows}"


def test_a_full_transfer_retires_the_source_grant_and_reprices_both_parcels(api):
    """PRD §3.6: "When the reduction leaves the balance at exactly 0 the whole
    freeze has been moved, and the source grant's `benefit_status` becomes the
    terminal `TRANSFERRED`, removing it from its parcel's active set. ... Finally,
    the value decomposition re-runs for both parcels, the source losing a grant and
    the destination gaining one, and each parcel's `version` increments by 1."

    Design: Difficulty/transitive_cascade/full_port_cascade_reprices_source_and_destination_parcels_from_one_transfer
    """
    world = _ported_freeze_world(api)

    source = validate_success(api.get_grant(world["grant_id"], REVIEWER))
    assert_grant(
        source,
        benefit_status="TRANSFERRED",
        portable_balance_cents=0,
        frozen_value_cents=33600000,
    )

    origin = validate_success(api.get_parcel(world["parcel"]["id"], ANALYST))
    assert_parcel_decomposition(
        origin,
        assessed_value_cents=33600000,
        exempt_value_cents=0,
        taxable_value_cents=33600000,
        exemption_status="UNEXEMPTED",
    )

    # The destination's own basis of 40000000 gives way to the freeze it received.
    destination = validate_success(api.get_parcel(world["destination"]["id"], ANALYST))
    assert_money(destination, "assessed_value_cents", 33600000)
    assert destination["exemption_status"] == "PARTIALLY_EXEMPT", (
        "the received freeze is exempted in part, got "
        f"{destination['exemption_status']}"
    )

    assert (
        source["portable_balance_cents"] + world["child"]["frozen_value_cents"]
        == source["frozen_value_cents"]
    ), (
        "frozen value is moved, never created: "
        f"{source['portable_balance_cents']} + {world['child']['frozen_value_cents']} "
        f"!= {source['frozen_value_cents']}"
    )


def _fraud_hold_freeze_world(api):
    """A senior freeze held by a household that is under investigation elsewhere.

    The investigation names a second, agricultural grant of the same taxpayer, so
    the freeze itself is still active and only the taxpayer-wide hold stands
    between it and the transfer; the destination parcel has no ownership record of
    any kind.
    """
    fx.set_clock(api)
    senior = fx.create_program(api, f.senior_freeze_program())
    agricultural = fx.create_program(api, f.agricultural_use_program())
    residence = fx.create_parcel(api, f.parcel())
    farm = fx.create_parcel(api, f.farm_parcel())
    unowned = fx.create_parcel(api, f.destination_parcel())
    taxpayer = fx.create_taxpayer(
        api, f.taxpayer_account(full_name="SAMUEL SENIOR", ssn_last4="7788")
    )
    fx.add_ownership(api, residence["id"], taxpayer["id"])
    fx.add_ownership(
        api,
        farm["id"],
        taxpayer["id"],
        occupancy_type="AGRICULTURAL",
        deed_recorded_date="2020-01-01",
        occupancy_start_date="2020-01-01",
    )
    fx.inject_matching_residency(api, taxpayer["id"])

    freeze_application = fx.application_ready_for_approval(
        api, residence["id"], taxpayer["id"], senior["id"]
    )
    freeze_determined = validate_success(
        api.determine_application(
            freeze_application["id"],
            f.approve_determination(residence["version"]),
            REVIEWER,
        )
    )
    freeze_grant = validate_success(
        api.get_grant(freeze_determined["resulting_grant_id"], REVIEWER)
    )

    farm_application = fx.application_ready_for_approval(
        api,
        farm["id"],
        taxpayer["id"],
        agricultural["id"],
        claimed_occupancy_date="2020-01-01",
    )
    farm_determined = validate_success(
        api.determine_application(
            farm_application["id"], f.approve_determination(farm["version"]), REVIEWER
        )
    )
    case = fx.open_fraud_case(
        api,
        farm_determined["resulting_grant_id"],
        taxpayer["id"],
        improper_start_tax_year=2025,
        improper_end_tax_year=2025,
    )
    return {
        "taxpayer": taxpayer,
        "freeze_grant": freeze_grant,
        "farm_grant_id": farm_determined["resulting_grant_id"],
        "unowned_parcel": unowned,
        "case": case,
    }


def test_an_open_investigation_blocks_a_transfer_before_the_destination_is_examined(api):
    """PRD §2.10 orders "No fraud hold — `ERR_FRAUD_HOLD_ACTIVE`, on `POST
    /exemption-grants/{id}/port`" at position 11 and "The destination parcel of a
    transfer is owned and occupied by the grant's taxpayer —
    `ERR_DESTINATION_NOT_OWNED`" at position 12, and "the **first** failure decides
    the response; later checks are not evaluated at all."

    Design: Difficulty/priority_pair_validation_conflict/fraud_hold_beats_unowned_destination_on_freeze_port
    """
    world = _fraud_hold_freeze_world(api)

    response = api.port_grant(
        world["freeze_grant"]["id"],
        f.port_request(
            world["unowned_parcel"]["id"], 1000000, world["freeze_grant"]["version"]
        ),
        REVIEWER,
    )
    validate_error(response, ERR_FRAUD_HOLD_ACTIVE, expected_status=409)
    assert ERR_DESTINATION_NOT_OWNED not in response.text, (
        "the destination-ownership verdict must not be revealed while a hold "
        f"stands: {response.text}"
    )


def test_the_blocked_transfer_moves_no_value_and_leaves_the_hold_in_place(api):
    """PRD §3.6: "No fraud case naming the grant's taxpayer may have an open
    investigation, or the transfer is refused with `ERR_FRAUD_HOLD_ACTIVE`." PRD
    §3.8: "The addressed grant is immediately suspended with `suspension_reason`
    `FRAUD_INVESTIGATION` ... the taxpayer's account `status` becomes `FLAGGED`".

    Design: Difficulty/priority_pair_validation_conflict/fraud_hold_beats_unowned_destination_on_freeze_port
    """
    world = _fraud_hold_freeze_world(api)
    freeze_version = world["freeze_grant"]["version"]

    validate_error(
        api.port_grant(
            world["freeze_grant"]["id"],
            f.port_request(world["unowned_parcel"]["id"], 1000000, freeze_version),
            REVIEWER,
        ),
        ERR_FRAUD_HOLD_ACTIVE,
        expected_status=409,
    )

    freeze = validate_success(api.get_grant(world["freeze_grant"]["id"], REVIEWER))
    assert_grant(
        freeze, benefit_status="ACTIVE", portable_balance_cents=33600000
    )
    assert freeze["version"] == freeze_version, (
        f"the refused transfer must not touch the source grant, got {freeze['version']}"
    )

    investigated = validate_success(api.get_grant(world["farm_grant_id"], REVIEWER))
    assert_grant(
        investigated,
        benefit_status="SUSPENDED",
        suspension_reason="FRAUD_INVESTIGATION",
    )

    case = validate_success(api.get_fraud_case(world["case"]["id"], INVESTIGATOR))
    assert case["investigation_status"] == "OPEN", (
        f"the investigation is still open, got {case['investigation_status']}"
    )
    account = validate_success(api.get_taxpayer_account(world["taxpayer"]["id"], CLERK))
    assert account["status"] == "FLAGGED", (
        f"an open investigation flags the account, got {account['status']}"
    )

    rows, meta = validate_paginated(
        api.list_grants(REVIEWER, parcel_id=world["unowned_parcel"]["id"])
    )
    assert meta["total_count"] == 0, (
        f"no grant may have reached the destination, got {meta['total_count']}"
    )
    assert rows == [], f"unexpected grants on the destination parcel: {rows}"


def _two_partial_ports_world(api):
    """One freeze split across two later homes, a slice at a time.

    The household's primary residence moves twice, so the three occupancy
    intervals run end to end and the clock is advanced before each transfer to an
    instant the receiving interval covers.
    """
    world = fx.approved_freeze_world(
        api,
        clock="2026-02-01T00:00:00Z",
        destinations=[
            {"payload": f.destination_parcel(), "occupancy": ("2026-03-01", "2026-09-01")},
            {"payload": f.second_destination_parcel(), "occupancy": ("2026-09-01", None)},
        ],
    )
    first_destination, second_destination = world["destinations"]

    fx.set_clock(api, "2026-04-01T00:00:00Z")
    first_child = validate_success(
        api.port_grant(
            world["grant_id"],
            f.port_request(first_destination["id"], 1000000, world["grant_version"]),
            REVIEWER,
        ),
        expected_status=201,
    )
    after_first = validate_success(api.get_grant(world["grant_id"], REVIEWER))

    fx.set_clock(api, "2026-10-01T00:00:00Z")
    second_child = validate_success(
        api.port_grant(
            world["grant_id"],
            f.port_request(second_destination["id"], 2000000, after_first["version"]),
            REVIEWER,
        ),
        expected_status=201,
    )
    world["first_child"] = first_child
    world["second_child"] = second_child
    world["after_first"] = after_first
    world["after_second"] = validate_success(api.get_grant(world["grant_id"], REVIEWER))
    return world


def test_two_partial_transfers_conserve_the_frozen_value_of_the_source_grant(api):
    """PRD §3.6: "for any freeze-enabled grant, its remaining
    `portable_balance_cents` plus the sum of `frozen_value_cents` across every
    child grant that names it in `ported_from_grant_id` always equals its original
    `frozen_value_cents`. Frozen value is moved, never created." PRD §3.6 also
    fixes the source's fate: "A **partial** transfer — one whose allocation is
    smaller than the balance — leaves the source grant `ACTIVE` with a reduced
    `portable_balance_cents`".

    Design: Difficulty/compensating_invariant/portable_freeze_value_is_conserved_across_two_partial_ports
    """
    world = _two_partial_ports_world(api)
    after_first = world["after_first"]
    after_second = world["after_second"]

    assert_money(world["first_child"], "frozen_value_cents", 1000000)
    assert_grant(
        world["first_child"], benefit_status="ACTIVE", portable_balance_cents=0
    )
    assert_grant(
        after_first, benefit_status="ACTIVE", portable_balance_cents=32600000
    )
    assert (
        after_first["portable_balance_cents"]
        + world["first_child"]["frozen_value_cents"]
        == 33600000
    ), (
        "after one slice the frozen value must still add up: "
        f"{after_first['portable_balance_cents']} + "
        f"{world['first_child']['frozen_value_cents']}"
    )

    assert_money(world["second_child"], "frozen_value_cents", 2000000)
    assert_grant(
        world["second_child"], benefit_status="ACTIVE", portable_balance_cents=0
    )
    assert_grant(
        after_second,
        benefit_status="ACTIVE",
        portable_balance_cents=30600000,
        frozen_value_cents=33600000,
    )
    assert after_second["version"] == after_first["version"] + 1, (
        "each transfer increments the source version by exactly one, got "
        f"{after_second['version']} after {after_first['version']}"
    )
    assert (
        after_second["portable_balance_cents"]
        + world["first_child"]["frozen_value_cents"]
        + world["second_child"]["frozen_value_cents"]
        == after_second["frozen_value_cents"]
    ), "the conservation identity failed after the second slice"

    rows, meta = validate_paginated(
        api.list_grants(REVIEWER, ported_from_grant_id=world["grant_id"])
    )
    assert meta["total_count"] == 2, (
        f"two transfers mean two child grants, got {meta['total_count']}"
    )
    assert {row["id"] for row in rows} == {
        world["first_child"]["id"],
        world["second_child"]["id"],
    }, f"unexpected portability chain: {rows}"


def test_each_partial_transfer_reprices_only_the_parcels_it_touched(api):
    """PRD §2.7: "If such a grant exists, the assessed basis becomes the smaller of
    the value computed so far and that controlling grant's `frozen_value_cents`."
    PRD §3.6 adds that on a transfer "the value decomposition re-runs for both
    parcels, the source losing a grant and the destination gaining one".

    Design: Difficulty/compensating_invariant/portable_freeze_value_is_conserved_across_two_partial_ports
    """
    world = _two_partial_ports_world(api)
    first_destination, second_destination = world["destinations"]

    # The source grant never left the roll, so the old home keeps its own benefit.
    origin = validate_success(api.get_parcel(world["parcel"]["id"], ANALYST))
    assert_parcel_decomposition(
        origin,
        assessed_value_cents=33600000,
        exempt_value_cents=3360000,
        taxable_value_cents=30240000,
        exemption_status="PARTIALLY_EXEMPT",
    )

    # Each destination's own 40000000 basis gives way to the slice of freeze it
    # received, which is the cited cap-and-freeze rule under examination here.
    first = validate_success(api.get_parcel(first_destination["id"], ANALYST))
    assert_money(first, "assessed_value_cents", 1000000)
    assert first["exempt_value_cents"] + first["taxable_value_cents"] == 1000000, (
        "exempt plus taxable must equal the frozen basis, got "
        f"{first['exempt_value_cents']} + {first['taxable_value_cents']}"
    )

    second = validate_success(api.get_parcel(second_destination["id"], ANALYST))
    assert_money(second, "assessed_value_cents", 2000000)
    assert second["exempt_value_cents"] + second["taxable_value_cents"] == 2000000, (
        "exempt plus taxable must equal the frozen basis, got "
        f"{second['exempt_value_cents']} + {second['taxable_value_cents']}"
    )


def test_a_worthless_destination_exhausts_the_allocation_and_a_moved_freeze_cannot_move_again(api):
    """PRD §3.6: "The amount actually moved is the smallest of three figures: the
    `transfer_value_cents` requested, the source grant's remaining
    `portable_balance_cents`, and the destination parcel's `assessed_value_cents` ...
    If the resulting allocation is zero or less — the minimum meaningful allocation
    being one cent — the transfer is refused with `ERR_PORTABLE_BALANCE_EXHAUSTED`."
    PRD §3.6 adds: "The source grant must be `ACTIVE` ... one against a `TRANSFERRED`,
    `LAPSED` or `REVOKED` grant with `ERR_GRANT_ALREADY_TERMINAL`", and "When the
    reduction leaves the balance at exactly 0 the whole freeze has been moved, and the
    source grant's `benefit_status` becomes the terminal `TRANSFERRED`".

    Design: Corner/errors/port_allocation_and_source_state_guards_return_4xx
    """
    world = fx.approved_freeze_world(
        api,
        destinations=[
            {
                "payload": f.second_destination_parcel(
                    base_year_value_cents=0, market_value_cents=0
                ),
                "occupancy": ("2026-03-01", "2026-06-01"),
            },
            {"payload": f.destination_parcel(), "occupancy": ("2026-06-01", None)},
        ],
    )
    grant_id = world["grant_id"]
    source_version = world["grant_version"]
    worthless, real = world["destinations"]
    assert_money(world["grant"], "frozen_value_cents", 33600000)
    assert_money(world["grant"], "portable_balance_cents", 33600000)
    assert_money(world["grant"], "benefit_amount_cents", 3360000)

    # min(1000000, 33600000, 0) is zero, so there is nothing to move.
    validate_error(
        api.port_grant(
            grant_id,
            f.port_request(worthless["id"], 1000000, source_version),
            REVIEWER,
        ),
        ERR_PORTABLE_BALANCE_EXHAUSTED,
        expected_status=422,
    )

    intact = validate_success(api.get_grant(grant_id, REVIEWER))
    assert_grant(intact, benefit_status="ACTIVE")
    assert_money(intact, "portable_balance_cents", 33600000)
    assert intact["version"] == source_version, (
        "a refused transfer is not a mutation, so the source version must not move: "
        f"{source_version} became {intact['version']}"
    )
    assert_parcel_decomposition(
        validate_success(api.get_parcel(worthless["id"], ANALYST)),
        assessed_value_cents=0,
        exempt_value_cents=0,
        taxable_value_cents=0,
        exemption_status="UNEXEMPTED",
    )

    # The household moves on to the parcel that does carry a basis.
    fx.set_clock(api, "2026-07-01T00:00:00Z")
    child = validate_success(
        api.port_grant(
            grant_id, f.port_request(real["id"], 33600000, source_version), REVIEWER
        ),
        expected_status=201,
    )
    assert_money(child, "frozen_value_cents", 33600000)
    assert_money(child, "portable_balance_cents", 0)
    assert child["ported_from_grant_id"] == grant_id, (
        f"the child names its source, got {child['ported_from_grant_id']}"
    )

    emptied = validate_success(api.get_grant(grant_id, REVIEWER))
    assert_grant(emptied, benefit_status="TRANSFERRED")
    assert_money(emptied, "portable_balance_cents", 0)
    assert emptied["version"] == source_version + 1, (
        f"the transfer is one mutation on the source, got version {emptied['version']}"
    )
    assert_money(
        validate_success(api.get_parcel(real["id"], ANALYST)),
        "assessed_value_cents",
        33600000,
    )
    assert_parcel_decomposition(
        validate_success(api.get_parcel(world["parcel"]["id"], ANALYST)),
        assessed_value_cents=33600000,
        exempt_value_cents=0,
        taxable_value_cents=33600000,
        exemption_status="UNEXEMPTED",
    )

    # The source is terminal now, and the current version does not rescue it.
    response = api.port_grant(
        grant_id,
        f.port_request(real["id"], 1000000, emptied["version"]),
        REVIEWER,
    )
    validate_error(response, ERR_GRANT_ALREADY_TERMINAL, expected_status=409)
    assert ERR_STALE_GRANT_VERSION not in response.text, (
        "the supplied version is current, so no staleness may be reported: "
        f"{response.text}"
    )

    rows, meta = validate_paginated(
        api.list_grants(REVIEWER, ported_from_grant_id=grant_id)
    )
    assert meta["total_count"] == 1, (
        f"only one child was ever created from this freeze, got {meta['total_count']}"
    )
    assert rows[0]["id"] == child["id"], f"unexpected child grant: {rows[0]['id']}"


def test_the_second_transfer_must_re_read_the_balance_the_first_one_reduced(api):
    """PRD §2.9: "A portability transfer — `POST /exemption-grants/{id}/port` — must
    carry `expected_grant_version` equal to the current `version` of the source grant
    addressed in the path. If it does not, the request is rejected with
    `ERR_STALE_GRANT_VERSION` and HTTP 412. Partial ports are legitimate and each one
    reduces the source grant's remaining portable balance, so a transfer sized from a
    stale view of the grant would allocate frozen value that an earlier port already
    carved out. The check forces the second transfer to re-read the remaining balance
    first."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_grant_version_on_a_second_port_returns_conflict
    """
    world = fx.approved_freeze_world(api)
    grant_id = world["grant_id"]
    destination_id = world["destination"]["id"]
    stale_token = world["grant_version"]
    assert_money(world["grant"], "frozen_value_cents", 33600000)
    assert_money(world["grant"], "portable_balance_cents", 33600000)
    assert_money(
        validate_success(api.get_parcel(destination_id, ANALYST)),
        "assessed_value_cents",
        40000000,
    )

    # min(1000000, 33600000, 40000000) moves, and the destination's own basis
    # gives way to the freeze it now carries.
    first_child = validate_success(
        api.port_grant(
            grant_id,
            f.port_request(destination_id, 1000000, stale_token),
            REVIEWER,
        ),
        expected_status=201,
    )
    assert_money(first_child, "frozen_value_cents", 1000000)
    assert_money(
        validate_success(api.get_parcel(destination_id, ANALYST)),
        "assessed_value_cents",
        1000000,
    )

    # The identical body replayed on the pre-port view of the grant.
    validate_error(
        api.port_grant(
            grant_id,
            f.port_request(destination_id, 1000000, stale_token),
            REVIEWER,
        ),
        ERR_STALE_GRANT_VERSION,
        expected_status=412,
    )

    after_refusal = validate_success(api.get_grant(grant_id, REVIEWER))
    assert after_refusal["version"] == 2, (
        f"only the accepted transfer moved the source version, got {after_refusal['version']}"
    )
    assert_money(after_refusal, "portable_balance_cents", 32600000)
    _rows, refused_meta = validate_paginated(
        api.list_grants(REVIEWER, ported_from_grant_id=grant_id)
    )
    assert refused_meta["total_count"] == 1, (
        f"the refused transfer allocated nothing, got {refused_meta['total_count']}"
    )

    # Re-read first, and the very same transfer is honoured.
    second_child = validate_success(
        api.port_grant(
            grant_id,
            f.port_request(destination_id, 1000000, after_refusal["version"]),
            REVIEWER,
        ),
        expected_status=201,
    )
    assert_money(second_child, "frozen_value_cents", 1000000)
    assert second_child["id"] != first_child["id"], (
        "the re-issued transfer must mint a second child, not return the first"
    )

    source = validate_success(api.get_grant(grant_id, REVIEWER))
    assert source["version"] == 3, (
        f"two accepted transfers make three versions, got {source['version']}"
    )
    assert_grant(source, benefit_status="ACTIVE")
    assert_money(source, "portable_balance_cents", 31600000)
    assert (
        source["portable_balance_cents"]
        + first_child["frozen_value_cents"]
        + second_child["frozen_value_cents"]
        == 33600000
    ), (
        "frozen value is moved, never created: "
        f"{source['portable_balance_cents']} + {first_child['frozen_value_cents']} + "
        f"{second_child['frozen_value_cents']}"
    )

    final_destination = validate_success(api.get_parcel(destination_id, ANALYST))
    assert_money(final_destination, "assessed_value_cents", 1000000)
    assert final_destination["version"] == 3, (
        "creation and the two transfers are the destination's three mutations, got "
        f"version {final_destination['version']}"
    )
