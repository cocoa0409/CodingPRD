"""Cascade and allocation services shared by the route modules.

The four named cascades of PRD 2.10 live here so that the weather closure, the
suspension cascade, the award cascade and the correction cascade all move stock
and money through exactly one implementation.
"""

import calc
import derive
import revision
import store


# --------------------------------------------------------------------------
# branch budget posture roll-up (adjusted ONLY on a flip)
# --------------------------------------------------------------------------

class PostureGuard(object):
    """Records each watched program's posture, then adjusts branch counters."""

    def __init__(self):
        self.before = {}

    def watch(self, program):
        if program["id"] not in self.before:
            self.before[program["id"]] = derive.program_posture(program)
        return program

    def settle(self):
        for program_id, before in self.before.items():
            program = store.get("programs", program_id)
            if program is None:
                continue
            after = derive.program_posture(program)
            if after == before:
                continue
            branch = store.get("branches", program["branch_id"])
            if branch is None:
                continue
            if before == "WITHIN_BUDGET" and after == "OVER_BUDGET":
                branch["programs_over_budget_count"] += 1
            elif before == "OVER_BUDGET" and after == "WITHIN_BUDGET":
                branch["programs_over_budget_count"] -= 1
                if branch["programs_over_budget_count"] < 0:
                    branch["programs_over_budget_count"] = 0
        self.before = {}


# --------------------------------------------------------------------------
# inventory movements
# --------------------------------------------------------------------------

def reserve_units(lot, units):
    lot["quantity_reserved"] += int(units)


def unreserve_units(lot, units):
    lot["quantity_reserved"] -= int(units)
    if lot["quantity_reserved"] < 0:
        lot["quantity_reserved"] = 0


def issue_reserved_units(lot, units):
    lot["quantity_reserved"] -= int(units)
    if lot["quantity_reserved"] < 0:
        lot["quantity_reserved"] = 0
    lot["quantity_issued"] += int(units)


def candidate_lots(category, sku, home_branch_id, minimum_units=1):
    """Two-bucket allocation order: own branch first, then reuse-pool lots."""
    own = []
    shared = []
    for lot in store.DB["lots"].values():
        if lot["category"] != category or lot["sku"] != sku:
            continue
        if derive.lot_status(lot) != "ACTIVE":
            continue
        if derive.lot_available(lot) < minimum_units:
            continue
        if lot["branch_id"] == home_branch_id:
            own.append(lot)
        elif lot["reuse_pool"]:
            shared.append(lot)
    own.sort(key=store.order_key)
    shared.sort(key=store.order_key)
    return own + shared


# --------------------------------------------------------------------------
# the supply draw (program confirmation)
# --------------------------------------------------------------------------

def supply_draw_plan(program):
    """Returns (lines, subtotal) or None when stock cannot cover the draw."""
    needed = int(program["attendance_target"]) * int(
        program["supply_units_per_attendee"]
    )
    lines = []
    subtotal = 0
    if needed <= 0:
        return lines, subtotal
    for lot in candidate_lots("SUPPLY", program["supply_sku"], program["branch_id"]):
        if needed <= 0:
            break
        available = derive.lot_available(lot)
        units = min(needed, available)
        if units <= 0:
            continue
        base = units * int(lot["unit_cost_cents"])
        surcharge = calc.cross_branch_surcharge_cents(
            base, lot["branch_id"], program["branch_id"]
        )
        line_total = base + surcharge
        lines.append(
            {
                "lot_id": lot["id"],
                "units": units,
                "unit_cost_cents": int(lot["unit_cost_cents"]),
                "surcharge_cents": surcharge,
                "line_total_cents": line_total,
            }
        )
        subtotal += line_total
        needed -= units
    if needed > 0:
        return None
    return lines, subtotal


def apply_supply_draw(program, lines):
    for line in lines:
        lot = store.get("lots", line["lot_id"])
        if lot is not None:
            reserve_units(lot, line["units"])
    program["supply_draw_lines"] = [dict(line) for line in lines]


def return_supply_draw(program):
    """Give drawn units back; a DEPLETED lot reactivates on its own accord."""
    for line in program["supply_draw_lines"]:
        lot = store.get("lots", line["lot_id"])
        if lot is not None:
            unreserve_units(lot, line["units"])
    program["supply_draw_lines"] = []
    program["materials_committed_cents"] = 0


def issue_supply_draw(program):
    for line in program["supply_draw_lines"]:
        lot = store.get("lots", line["lot_id"])
        if lot is not None:
            issue_reserved_units(lot, line["units"])


# --------------------------------------------------------------------------
# reservations
# --------------------------------------------------------------------------

def release_reservations(program):
    for reservation in derive.program_reservations(program["id"]):
        if reservation["status"] in ("HELD", "CONFIRMED"):
            reservation["status"] = "RELEASED"
            revision.mark(reservation)
    program["confirmed_room_capacity"] = 0


def revert_confirmed_reservation(program):
    for reservation in derive.program_reservations(program["id"]):
        if reservation["status"] == "CONFIRMED":
            reservation["status"] = "HELD"
            revision.mark(reservation)
    program["confirmed_room_capacity"] = 0


# --------------------------------------------------------------------------
# tier awards: pricing, granting, promotion and revocation
# --------------------------------------------------------------------------

def price_award_against_lot(units, lot, home_branch_id):
    line_cost = units * int(lot["unit_cost_cents"])
    surcharge = calc.cross_branch_surcharge_cents(
        line_cost, lot["branch_id"], home_branch_id
    )
    return {
        "lot_id": lot["id"],
        "units": units,
        "unit_cost_cents": int(lot["unit_cost_cents"]),
        "line_cost_cents": line_cost,
        "transfer_surcharge_cents": surcharge,
        "award_total_cents": line_cost + surcharge,
        "status": "RESERVED",
    }


def deferred_award_fields(units):
    return {
        "lot_id": None,
        "units": units,
        "unit_cost_cents": 0,
        "line_cost_cents": 0,
        "transfer_surcharge_cents": 0,
        "award_total_cents": 0,
        "status": "DEFERRED",
    }


def grant_award(participant, tier):
    """Create one TierAward for a newly reached tier (RESERVED or DEFERRED)."""
    units = int(tier["prize_units_per_participant"])
    lots = candidate_lots(
        "PRIZE", tier["prize_sku"], participant["home_branch_id"], units
    )
    if lots:
        fields = price_award_against_lot(units, lots[0], participant["home_branch_id"])
        lot = lots[0]
    else:
        fields = deferred_award_fields(units)
        lot = None
    fields["participant_id"] = participant["id"]
    fields["tier_id"] = tier["id"]
    award = store.new_entity("awards", fields)
    if lot is not None:
        reserve_units(lot, units)
    return award


def grant_awards_for_progress(participant):
    """CASCADE-C link 2: one award per tier in (awarded, eligible]."""
    units = derive.cumulative_units(participant["id"])
    eligible = derive.eligible_tier_index(participant["challenge_id"], units)
    awarded = derive.awarded_tier_index(participant["id"])
    if eligible <= awarded:
        return []
    by_index = dict(
        (tier["tier_index"], tier)
        for tier in derive.challenge_tiers(participant["challenge_id"])
    )
    created = []
    for index in range(awarded + 1, eligible + 1):
        tier = by_index.get(index)
        if tier is None:
            continue
        created.append(grant_award(participant, tier))
    return created


def promote_deferred_awards(lot):
    """Freed or freshly procured units serve the longest-waiting reader first."""
    if lot is None or lot["category"] != "PRIZE":
        return
    deferred = [
        award
        for award in store.DB["awards"].values()
        if award["status"] == "DEFERRED"
    ]
    deferred.sort(key=store.order_key)
    for award in deferred:
        tier = store.get("tiers", award["tier_id"])
        participant = store.get("participants", award["participant_id"])
        if tier is None or participant is None:
            continue
        if tier["prize_sku"] != lot["sku"]:
            continue
        units = int(tier["prize_units_per_participant"])
        # The triggering lot must itself be able to fill the award, and the
        # participant must be allowed to draw from it.
        if derive.lot_status(lot) != "ACTIVE" or derive.lot_available(lot) < units:
            continue
        if (
            lot["branch_id"] != participant["home_branch_id"]
            and not lot["reuse_pool"]
        ):
            continue
        # Promotion is a fresh pricing against the full candidate order.
        lots = candidate_lots(
            "PRIZE", tier["prize_sku"], participant["home_branch_id"], units
        )
        if not lots:
            continue
        chosen = lots[0]
        award.update(
            price_award_against_lot(units, chosen, participant["home_branch_id"])
        )
        reserve_units(chosen, units)
        revision.mark(award)


def revoke_awards_below(participant, units):
    """CASCADE-D links 2 and 3 under the LEDGER_TRUTH policy."""
    freed_lots = []
    for award in derive.participant_awards(participant["id"]):
        if award["status"] not in ("RESERVED", "DEFERRED"):
            continue
        tier = store.get("tiers", award["tier_id"])
        if tier is None or tier["threshold_units"] <= units:
            continue
        if award["status"] == "RESERVED":
            lot = store.get("lots", award["lot_id"])
            if lot is not None:
                unreserve_units(lot, award["units"])
                if lot not in freed_lots:
                    freed_lots.append(lot)
        award["status"] = "REVOKED"
        revision.mark(award)
    for lot in freed_lots:
        promote_deferred_awards(lot)


# --------------------------------------------------------------------------
# contract cancellation (CASCADE-A and the library cancellation)
# --------------------------------------------------------------------------

WEATHER_CANCELLABLE = ("OFFERED", "COUNTERED", "EXECUTED")
LIBRARY_CANCELLABLE = ("DRAFT", "OFFERED", "COUNTERED", "EXECUTED")


def cancel_program_contracts(program, cause):
    """Replaces presenter_fee_committed_cents with the summed kill liability."""
    if cause == "WEATHER":
        cancellable = WEATHER_CANCELLABLE
        new_status = "CANCELLED_WEATHER"
    else:
        cancellable = LIBRARY_CANCELLABLE
        new_status = "CANCELLED_LIBRARY"
    total = 0
    for contract in derive.program_contracts(program["id"]):
        if contract["status"] not in cancellable:
            continue
        if cause == "WEATHER":
            fee = calc.weather_kill_fee_cents(contract["total_fee_cents"], program)
        else:
            fee = calc.library_kill_fee_cents(contract["total_fee_cents"], program)
        contract["kill_fee_cents"] = fee
        contract["status"] = new_status
        revision.mark(contract)
        total += fee
    program["presenter_fee_committed_cents"] = total


# --------------------------------------------------------------------------
# the suspension cascade (CASCADE-B)
# --------------------------------------------------------------------------

def suspend_presenter_cascade(presenter):
    presenter["engagement_status"] = "SUSPENDED"
    guard = PostureGuard()
    for contract in derive.presenter_contracts(presenter["id"]):
        if contract["status"] not in ("OFFERED", "COUNTERED", "EXECUTED"):
            continue
        program = store.get("programs", contract["program_id"])
        was_executed = contract["status"] == "EXECUTED"
        contract["status"] = "BLOCKED"
        revision.mark(contract)
        if program is None:
            continue
        guard.watch(program)
        if was_executed:
            program["presenter_fee_committed_cents"] -= int(
                contract["total_fee_cents"]
            )
        program["compliance_status"] = "BLOCKED"
        if program["operational_status"] == "CONFIRMED":
            program["operational_status"] = "SCHEDULED"
            return_supply_draw(program)
            revert_confirmed_reservation(program)
        revision.mark(program)
    guard.settle()


def restore_presenter_cascade(presenter):
    """CLEARED_WITH_CONDITIONS: blocked contracts return to OFFERED at 0 fee."""
    if presenter["executed_contract_count"] > 0:
        presenter["engagement_status"] = "ACTIVE"
    else:
        presenter["engagement_status"] = "PROSPECT"
    for contract in derive.presenter_contracts(presenter["id"]):
        if contract["status"] != "BLOCKED":
            continue
        contract["status"] = "OFFERED"
        contract["total_fee_cents"] = 0
        revision.mark(contract)
        program = store.get("programs", contract["program_id"])
        if program is None:
            continue
        program["compliance_status"] = "PENDING_SCREENING"
        revision.mark(program)
