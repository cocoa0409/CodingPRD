"""Water and fence tickets, the repair fork and the posture gate they drive."""

from test_helpers import (
    ApiErrorId,
    assign_infrastructure_ticket,
    complete_infrastructure_ticket,
    draft_settlement,
    infrastructure_ticket_payload,
    make_cattle_owner_headers,
    make_grazier_headers,
    open_infrastructure_ticket,
    read_contract,
    read_lot,
    read_pasture,
    read_ticket,
    set_logical_clock,
    setup_north_bench_active_contract,
    setup_north_bench_lot_on_feed,
    validate_error,
    validate_success,
    weigh_out_lot,
)


# ===========================================================================
# The repair fork: the same matrix share, opposite signs
# ===========================================================================

def test_the_two_repair_branches_flip_the_sign_of_the_owners_line(api):
    """PRD 3.7: "From it a raw owner amount follows: 0 when the responsible party is
    `GRAZIER`, the whole `repair_cost_cents` when it is `OWNER`, and half the repair
    cost — the cost multiplied by 50 percent and rounded half up to a whole cent — when
    it is `SHARED`."
    PRD 3.7: "The fork lands on the sign. On the grazier-repair branch, the grazier paid
    the vendor and bills the owner, so the ticket's `owner_share_cents` is the owner's
    matrix share as a positive charge. On the owner-repair branch, the owner already
    paid the vendor out of pocket, so the ticket's `owner_share_cents` is the *negative*
    of the grazier's matrix share — a credit the settlement pays back to the owner. On
    both branches `grazier_share_cents` is the grazier's matrix share, a positive
    number."

    Design: Difficulty/non_linear_state_machine/infrastructure_ticket_repair_branch_fork_flips_charge_sign
    """
    world = setup_north_bench_lot_on_feed()
    grazier_ticket = open_infrastructure_ticket(
        world.pasture_id, world.contract_id, make_grazier_headers(world.grazier_id),
        description="Stock tank float valve", reported_at="2026-09-10T08:00:00Z",
    )
    assign_infrastructure_ticket(grazier_ticket["id"], world.grazier_id, "GRAZIER")
    owner_ticket = open_infrastructure_ticket(
        world.pasture_id, world.contract_id, make_grazier_headers(world.grazier_id),
        description="Second tank overflow line", reported_at="2026-09-12T08:00:00Z",
    )
    assign_infrastructure_ticket(owner_ticket["id"], world.grazier_id, "OWNER")

    repaired_by_grazier = validate_success(
        api.complete_infrastructure_ticket(
            grazier_ticket["id"],
            {"repair_cost_cents": 180000, "cause": "WEAR",
             "completed_at": "2026-09-14T17:00:00Z"},
            make_grazier_headers(world.grazier_id),
        ),
        200,
    )
    repaired_by_owner = validate_success(
        api.complete_infrastructure_ticket(
            owner_ticket["id"],
            {"repair_cost_cents": 180000, "cause": "WEAR",
             "completed_at": "2026-09-16T17:00:00Z"},
            make_cattle_owner_headers(world.owner_id),
        ),
        200,
    )

    assert repaired_by_grazier["responsible_party"] == "SHARED"
    assert repaired_by_grazier["owner_share_cents"] == 90000
    assert repaired_by_grazier["grazier_share_cents"] == 90000
    assert repaired_by_grazier["status"] == "REPAIRED"

    assert repaired_by_owner["responsible_party"] == "SHARED"
    assert repaired_by_owner["owner_share_cents"] == -90000, (
        "The owner already paid the vendor, so their line is a credit"
    )
    assert repaired_by_owner["grazier_share_cents"] == 90000
    assert repaired_by_owner["status"] == "REPAIRED"


def test_the_two_signed_repair_lines_cancel_inside_the_settlement(api):
    """PRD 3.9: "Then `infrastructure_charge_cents` is the sum of the owner shares of
    every infrastructure ticket on this contract whose `status` is `REPAIRED` or
    `BILLED`, taken with their signs, so an owner-repair branch pulls the figure down
    and the total may legitimately be negative."
    PRD 3.9: "`subtotal_cents` is the base charge plus the treatment charge plus the
    infrastructure charge, less the death-loss credit."

    Design: Difficulty/non_linear_state_machine/infrastructure_ticket_repair_branch_fork_flips_charge_sign
    """
    world = setup_north_bench_lot_on_feed()
    grazier_ticket = open_infrastructure_ticket(
        world.pasture_id, world.contract_id, make_grazier_headers(world.grazier_id),
        description="Stock tank float valve", reported_at="2026-09-10T08:00:00Z",
    )
    assign_infrastructure_ticket(grazier_ticket["id"], world.grazier_id, "GRAZIER")
    owner_ticket = open_infrastructure_ticket(
        world.pasture_id, world.contract_id, make_grazier_headers(world.grazier_id),
        description="Second tank overflow line", reported_at="2026-09-12T08:00:00Z",
    )
    assign_infrastructure_ticket(owner_ticket["id"], world.grazier_id, "OWNER")
    complete_infrastructure_ticket(
        grazier_ticket["id"], make_grazier_headers(world.grazier_id),
        180000, "WEAR", "2026-09-14T17:00:00Z",
    )
    complete_infrastructure_ticket(
        owner_ticket["id"], make_cattle_owner_headers(world.owner_id),
        180000, "WEAR", "2026-09-16T17:00:00Z",
    )

    weigh_out_lot(world.lot_id, world.grazier_id)
    set_logical_clock("2026-11-12T00:00:00Z")
    settlement = draft_settlement(world.contract_id, world.lot_id, world.grazier_id)

    assert settlement["infrastructure_charge_cents"] == 0, (
        "A +90000 charge and a -90000 credit sum to nothing"
    )
    assert settlement["base_charge_cents"] == 1143760
    assert settlement["subtotal_cents"] == 1143760
    assert settlement["volume_rebate_cents"] == 11438
    assert settlement["total_due_cents"] == 1132322


# ===========================================================================
# A critical ticket restricts the pasture and holds its lots
# ===========================================================================

def test_a_critical_ticket_restricts_the_pasture_and_holds_its_scheduled_lot(api):
    """PRD 3.7: "Severity is not cosmetic: only a `CRITICAL` ticket counts toward the
    pasture's `open_critical_ticket_count`, and its arrival therefore recomputes that
    count and the pasture's `grazing_posture`, which becomes `RESTRICTED` while the
    ticket is live."
    PRD 2.10: "The posture leaving `OPEN` also reaches down into the lots: every lot on
    the pasture still sitting in `SCHEDULED` moves to `RECEIVING_HELD`, and when the
    posture later returns to `OPEN`, every `RECEIVING_HELD` lot moves back to
    `SCHEDULED`."

    Design: Difficulty/transitive_cascade/critical_ticket_restriction_cascade_ticket_to_pasture_to_lot
    """
    world = setup_north_bench_active_contract()
    lot = validate_success(
        api.create_lot(
            world.contract_id,
            {"scheduled_head_count": 150, "scheduled_delivery_date": "2026-08-10"},
            make_grazier_headers(world.grazier_id),
        ),
        201,
    )

    validate_success(
        api.create_infrastructure_ticket(
            infrastructure_ticket_payload(
                world.pasture_id, world.contract_id, severity="CRITICAL",
                description="Submersible pump burnt out, no water in the unit",
                reported_at="2026-08-09T06:00:00Z",
            ),
            make_grazier_headers(world.grazier_id),
        ),
        201,
    )

    pasture = read_pasture(world.pasture_id, world.grazier_id)
    assert pasture["open_critical_ticket_count"] == 1
    assert pasture["grazing_posture"] == "RESTRICTED"
    assert read_lot(lot["id"], world.grazier_id)["status"] == "RECEIVING_HELD"


def test_completing_the_critical_repair_reopens_the_pasture_and_releases_the_lot(api):
    """PRD 3.7: "Completing a repair also clears the pasture: `open_critical_ticket_count`
    and `grazing_posture` are recomputed, and if the posture returns to `OPEN`, every lot
    on the pasture sitting in `RECEIVING_HELD` moves back to `SCHEDULED`."
    PRD 3.7: "That raw amount is then capped by the contract's
    `infrastructure_owner_cap_cents`, taking whichever of the two is smaller, and the
    capped figure is the owner's matrix share; the grazier's matrix share is the repair
    cost less it."

    Design: Difficulty/transitive_cascade/critical_ticket_restriction_cascade_ticket_to_pasture_to_lot
    """
    world = setup_north_bench_active_contract()
    lot = validate_success(
        api.create_lot(
            world.contract_id,
            {"scheduled_head_count": 150, "scheduled_delivery_date": "2026-08-10"},
            make_grazier_headers(world.grazier_id),
        ),
        201,
    )
    ticket = open_infrastructure_ticket(
        world.pasture_id, world.contract_id, make_grazier_headers(world.grazier_id),
        severity="CRITICAL", description="Submersible pump burnt out",
        reported_at="2026-08-09T06:00:00Z",
    )
    assign_infrastructure_ticket(ticket["id"], world.grazier_id, "GRAZIER")

    repaired = complete_infrastructure_ticket(
        ticket["id"], make_grazier_headers(world.grazier_id),
        240000, "WEAR", "2026-08-09T18:00:00Z",
    )

    assert repaired["status"] == "REPAIRED"
    assert repaired["responsible_party"] == "SHARED"
    assert repaired["owner_share_cents"] == 100000, "Half of 240000 is capped at 100000"
    assert repaired["grazier_share_cents"] == 140000

    pasture = read_pasture(world.pasture_id, world.grazier_id)
    assert pasture["open_critical_ticket_count"] == 0
    assert pasture["grazing_posture"] == "OPEN"
    assert read_lot(lot["id"], world.grazier_id)["status"] == "SCHEDULED"


# ===========================================================================
# The posture gate over booking deliveries
# ===========================================================================

def test_booking_a_delivery_onto_a_restricted_pasture_is_refused(api):
    """PRD 3.4: "The booking is refused when the pasture underneath the contract is not
    posturally open, with `ERR_PASTURE_POSTURE_BLOCKED`."
    PRD 2.10: "Whenever the posture is anything other than `OPEN`, no delivery may be
    booked against a contract on that pasture and no lot may be received onto it; both
    attempts are rejected with `ERR_PASTURE_POSTURE_BLOCKED`."

    Design: Difficulty/cross_entity_state_dependency/lot_booking_gated_by_pasture_grazing_posture
    """
    world = setup_north_bench_active_contract()
    open_infrastructure_ticket(
        world.pasture_id, world.contract_id, make_grazier_headers(world.grazier_id),
        severity="CRITICAL", description="Pipeline blown at the divide",
        reported_at="2026-08-09T06:00:00Z",
    )

    resp = api.create_lot(
        world.contract_id,
        {"scheduled_head_count": 150, "scheduled_delivery_date": "2026-08-10"},
        make_grazier_headers(world.grazier_id),
    )
    validate_error(resp, ApiErrorId.ERR_PASTURE_POSTURE_BLOCKED.value, 409)

    pasture = read_pasture(world.pasture_id, world.grazier_id)
    assert pasture["grazing_posture"] == "RESTRICTED"
    assert pasture["open_critical_ticket_count"] == 1
    assert read_contract(world.contract_id, world.grazier_id)["lifecycle_status"] == "ACTIVE", (
        "The contract itself is in a perfectly valid state"
    )


def test_the_same_booking_succeeds_once_the_posture_returns_to_open(api):
    """PRD 2.10: "Whenever the posture is anything other than `OPEN`, no delivery may be
    booked against a contract on that pasture and no lot may be received onto it; both
    attempts are rejected with `ERR_PASTURE_POSTURE_BLOCKED`."
    PRD 2.10: "Otherwise, if `open_critical_ticket_count` is greater than 0, or
    `capacity_utilization_pct` is strictly greater than 100, the posture is `RESTRICTED`."

    Design: Difficulty/cross_entity_state_dependency/lot_booking_gated_by_pasture_grazing_posture
    """
    world = setup_north_bench_active_contract()
    ticket = open_infrastructure_ticket(
        world.pasture_id, world.contract_id, make_grazier_headers(world.grazier_id),
        severity="CRITICAL", description="Pipeline blown at the divide",
        reported_at="2026-08-09T06:00:00Z",
    )
    assign_infrastructure_ticket(ticket["id"], world.grazier_id, "GRAZIER")
    complete_infrastructure_ticket(
        ticket["id"], make_grazier_headers(world.grazier_id),
        50000, "STORM", "2026-08-09T18:00:00Z",
    )
    assert read_pasture(world.pasture_id, world.grazier_id)["grazing_posture"] == "OPEN"

    resp = api.create_lot(
        world.contract_id,
        {"scheduled_head_count": 150, "scheduled_delivery_date": "2026-08-10"},
        make_grazier_headers(world.grazier_id),
    )
    booked = validate_success(resp, 201)
    assert booked["status"] == "SCHEDULED"


# ===========================================================================
# Ticket lifecycle guards and the cause override
# ===========================================================================

def test_completing_a_ticket_that_was_never_assigned_is_refused(api):
    """PRD 3.7: "Completion is performed by whichever side was assigned: the grazier
    completes a ticket assigned to the grazier, and the cattle owner on the governing
    contract completes one assigned to the owner."
    PRD 3.7: "Assignment is declared only from `OPEN`; anything else is
    `ERR_TICKET_INVALID_STATE`."

    Design: Corner/state_machines/completing_an_unassigned_ticket_returns_ticket_invalid_state
    """
    world = setup_north_bench_lot_on_feed()
    ticket = open_infrastructure_ticket(
        world.pasture_id, world.contract_id, make_grazier_headers(world.grazier_id),
        asset_type="FENCE", severity="MAJOR",
        description="Three braces down on the west line",
        reported_at="2026-09-10T08:00:00Z",
    )

    resp = api.complete_infrastructure_ticket(
        ticket["id"],
        {"repair_cost_cents": 50000, "cause": "STORM",
         "completed_at": "2026-09-11T17:00:00Z"},
        make_grazier_headers(world.grazier_id),
    )
    validate_error(resp, ApiErrorId.ERR_TICKET_INVALID_STATE.value, 409)

    assert read_ticket(ticket["id"], world.grazier_id)["status"] == "OPEN"


def test_livestock_damage_overrides_the_matrix_and_the_owner_share_hits_the_cap(api):
    """PRD 3.7: "Then the determined `cause` may override the matrix outright —
    `LIVESTOCK_DAMAGE` makes the owner responsible whatever the matrix said, and
    `NEGLECT` makes the grazier responsible; a cause of `WEAR` or `STORM` leaves the
    matrix answer standing."
    PRD 3.7: "That raw amount is then capped by the contract's
    `infrastructure_owner_cap_cents`, taking whichever of the two is smaller, and the
    capped figure is the owner's matrix share; the grazier's matrix share is the repair
    cost less it."

    Design: Corner/calculations/livestock_damage_cause_overrides_the_matrix_and_hits_the_owner_cap
    """
    world = setup_north_bench_lot_on_feed(
        contract={"water_responsibility": "GRAZIER", "infrastructure_owner_cap_cents": 100000}
    )
    ticket = open_infrastructure_ticket(
        world.pasture_id, world.contract_id, make_grazier_headers(world.grazier_id),
        asset_type="WATER", severity="MAJOR",
        description="Tank rim caved in by cattle", reported_at="2026-09-12T08:00:00Z",
    )
    assign_infrastructure_ticket(ticket["id"], world.grazier_id, "GRAZIER")

    repaired = complete_infrastructure_ticket(
        ticket["id"], make_grazier_headers(world.grazier_id),
        180000, "LIVESTOCK_DAMAGE", "2026-09-14T17:00:00Z",
    )

    assert repaired["responsible_party"] == "OWNER", (
        "LIVESTOCK_DAMAGE beats a water matrix that said GRAZIER"
    )
    assert repaired["owner_share_cents"] == 100000, "180000 raw is clipped by the cap"
    assert repaired["grazier_share_cents"] == 80000
    assert repaired["status"] == "REPAIRED"


def test_reading_a_repaired_ticket_surfaces_its_computed_split(api):
    """PRD 3.7: "The allocation runs in three steps. First the matrix is consulted: a
    `WATER` failure looks at the contract's `water_responsibility` and a `FENCE` failure
    at its `fence_responsibility`."
    PRD 3.7: "From it a raw owner amount follows: 0 when the responsible party is
    `GRAZIER`, the whole `repair_cost_cents` when it is `OWNER`, and half the repair
    cost — the cost multiplied by 50 percent and rounded half up to a whole cent — when
    it is `SHARED`."

    Design: Corner/endpoints/get_infrastructure_ticket_by_id_returns_the_computed_split
    """
    world = setup_north_bench_lot_on_feed()
    ticket = open_infrastructure_ticket(
        world.pasture_id, world.contract_id, make_grazier_headers(world.grazier_id),
        asset_type="FENCE", severity="MAJOR",
        description="Storm laid down 40 rods of wire", reported_at="2026-09-10T08:00:00Z",
    )
    assign_infrastructure_ticket(ticket["id"], world.grazier_id, "GRAZIER")
    complete_infrastructure_ticket(
        ticket["id"], make_grazier_headers(world.grazier_id),
        50000, "STORM", "2026-09-12T17:00:00Z",
    )

    resp = api.get_infrastructure_ticket(
        ticket["id"], make_cattle_owner_headers(world.owner_id)
    )
    read_back = validate_success(resp, 200)

    assert read_back["responsible_party"] == "GRAZIER", (
        "fence_responsibility is GRAZIER and STORM adds no override"
    )
    assert read_back["owner_share_cents"] == 0
    assert read_back["grazier_share_cents"] == 50000
    assert read_back["status"] == "REPAIRED"
    assert read_back["cause"] == "STORM"
    assert read_pasture(world.pasture_id, world.grazier_id)["open_critical_ticket_count"] == 0
