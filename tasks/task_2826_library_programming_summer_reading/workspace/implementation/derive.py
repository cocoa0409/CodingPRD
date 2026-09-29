"""Derived fields and the per-entity JSON serializers.

Roll-ups that the PRD defines as sums or counts over children are computed on
read, which is what keeps the conservation invariants of section 2.8 true on
every read rather than merely after a settlement.
"""

import calc
import store
from core import fmt_date, fmt_instant


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def program_of(entity_program_id):
    return store.get("programs", entity_program_id)


def challenge_tiers(challenge_id):
    tiers = [t for t in store.DB["tiers"].values() if t["challenge_id"] == challenge_id]
    tiers.sort(key=lambda t: (t["tier_index"], t["_seq"]))
    return tiers


def participant_entries(participant_id):
    rows = [
        e
        for e in store.DB["entries"].values()
        if e["participant_id"] == participant_id
    ]
    rows.sort(key=store.order_key)
    return rows


def participant_awards(participant_id):
    rows = [
        a
        for a in store.DB["awards"].values()
        if a["participant_id"] == participant_id
    ]
    rows.sort(key=store.order_key)
    return rows


def challenge_awards(challenge_id):
    rows = []
    for award in store.DB["awards"].values():
        tier = store.get("tiers", award["tier_id"])
        if tier is not None and tier["challenge_id"] == challenge_id:
            rows.append(award)
    rows.sort(key=store.order_key)
    return rows


def tier_awards(tier_id):
    rows = [a for a in store.DB["awards"].values() if a["tier_id"] == tier_id]
    rows.sort(key=store.order_key)
    return rows


def program_contracts(program_id):
    rows = [
        c for c in store.DB["contracts"].values() if c["program_id"] == program_id
    ]
    rows.sort(key=store.order_key)
    return rows


def presenter_contracts(presenter_id):
    rows = [
        c for c in store.DB["contracts"].values() if c["presenter_id"] == presenter_id
    ]
    rows.sort(key=store.order_key)
    return rows


def program_reservations(program_id):
    rows = [
        r for r in store.DB["reservations"].values() if r["program_id"] == program_id
    ]
    rows.sort(key=store.order_key)
    return rows


def room_reservations(room_id):
    rows = [r for r in store.DB["reservations"].values() if r["room_id"] == room_id]
    rows.sort(key=store.order_key)
    return rows


# --------------------------------------------------------------------------
# inventory lot
# --------------------------------------------------------------------------

def lot_available(lot):
    value = (
        int(lot["quantity_procured"])
        - int(lot["quantity_reserved"])
        - int(lot["quantity_issued"])
    )
    return value if value > 0 else 0


def lot_status(lot):
    return "ACTIVE" if lot_available(lot) > 0 else "DEPLETED"


# --------------------------------------------------------------------------
# participant progress ledger
# --------------------------------------------------------------------------

def superseded_entry_ids(participant_id):
    """LOG entries that already carry a CORRECTION."""
    ids = set()
    for entry in participant_entries(participant_id):
        if entry["entry_type"] == "CORRECTION" and entry.get("corrected_entry_id"):
            ids.add(entry["corrected_entry_id"])
    return ids


def cumulative_units(participant_id):
    total = 0
    for entry in participant_entries(participant_id):
        if entry["entry_type"] == "LOG":
            total += int(entry.get("units") or 0)
        else:
            total += int(entry.get("units_delta") or 0)
    return total if total > 0 else 0


def eligible_tier_index(challenge_id, units):
    index = 0
    for tier in challenge_tiers(challenge_id):
        if tier["threshold_units"] <= units:
            index = max(index, tier["tier_index"])
    return index


def awarded_tier_index(participant_id):
    index = 0
    for award in participant_awards(participant_id):
        if award["status"] in ("RESERVED", "DEFERRED", "ISSUED"):
            tier = store.get("tiers", award["tier_id"])
            if tier is not None:
                index = max(index, tier["tier_index"])
    return index


def last_entry_on(participant_id):
    best = None
    for entry in participant_entries(participant_id):
        if entry["entry_type"] != "LOG":
            continue
        if best is None or entry["logged_on"] > best:
            best = entry["logged_on"]
    return best


def net_units_on_date(participant_id, logged_on):
    """Net LOG units for a single logged_on date, after corrections on it."""
    total = 0
    for entry in participant_entries(participant_id):
        if entry["logged_on"] != logged_on:
            continue
        if entry["entry_type"] == "LOG":
            total += int(entry.get("units") or 0)
        else:
            total += int(entry.get("units_delta") or 0)
    return total


# --------------------------------------------------------------------------
# challenge roll-ups
# --------------------------------------------------------------------------

def challenge_money(challenge):
    committed = 0
    spent = 0
    for award in challenge_awards(challenge["id"]):
        if award["status"] == "RESERVED":
            committed += int(award["award_total_cents"])
        elif award["status"] == "ISSUED":
            spent += int(award["award_total_cents"])
    budget = int(challenge["prize_budget_cents"])
    return {
        "prize_committed_cents": committed,
        "prize_spent_cents": spent,
        "prize_available_cents": budget - committed - spent,
    }


def prize_inventory_posture(challenge_id):
    tiers = challenge_tiers(challenge_id)
    for tier in tiers:
        drawable = False
        for lot in store.DB["lots"].values():
            if (
                lot["category"] == "PRIZE"
                and lot["sku"] == tier["prize_sku"]
                and lot_status(lot) == "ACTIVE"
            ):
                drawable = True
                break
        if not drawable:
            return "CONSTRAINED"
    return "AMPLE"


def challenge_participant_count(challenge_id):
    return len(
        [
            p
            for p in store.DB["participants"].values()
            if p["challenge_id"] == challenge_id
        ]
    )


def challenge_deferred_count(challenge_id):
    return len(
        [a for a in challenge_awards(challenge_id) if a["status"] == "DEFERRED"]
    )


# --------------------------------------------------------------------------
# program money
# --------------------------------------------------------------------------

def program_money(program):
    budget = int(program["materials_budget_cents"])
    committed = int(program["materials_committed_cents"])
    spent = int(program["materials_spent_cents"])
    available = budget - committed - spent
    total_budget = budget + int(program["presenter_fee_budget_cents"])
    encumbrance = (
        committed
        + spent
        + int(program["presenter_fee_committed_cents"])
        + int(program["presenter_fee_spent_cents"])
    )
    variance = total_budget - encumbrance
    return {
        "materials_available_cents": available,
        "budget_variance_cents": variance,
        "budget_posture": "OVER_BUDGET" if variance < 0 else "WITHIN_BUDGET",
    }


def program_posture(program):
    return program_money(program)["budget_posture"]


# --------------------------------------------------------------------------
# serializers
# --------------------------------------------------------------------------

def _common(entity):
    return {
        "id": entity["id"],
        "created_at": fmt_instant(entity["created_at"]),
        "updated_at": fmt_instant(entity["updated_at"]),
        "version": entity["version"],
    }


def branch_json(branch):
    out = _common(branch)
    out.update(
        {
            "name": branch["name"],
            "branch_code": branch["branch_code"],
            "overlapping_program_capacity": branch["overlapping_program_capacity"],
            "per_program_fee_cap_cents": branch["per_program_fee_cap_cents"],
            "programs_over_budget_count": branch["programs_over_budget_count"],
        }
    )
    return out


def room_json(room):
    out = _common(room)
    out.update(
        {
            "branch_id": room["branch_id"],
            "room_name": room["room_name"],
            "capacity_seats": room["capacity_seats"],
            "min_setup_minutes": room["min_setup_minutes"],
            "min_teardown_minutes": room["min_teardown_minutes"],
            "accessibility_features": list(room["accessibility_features"]),
            "status": room["status"],
        }
    )
    return out


def lot_json(lot):
    out = _common(lot)
    out.update(
        {
            "branch_id": lot["branch_id"],
            "category": lot["category"],
            "sku": lot["sku"],
            "description": lot["description"],
            "unit_cost_cents": lot["unit_cost_cents"],
            "quantity_procured": lot["quantity_procured"],
            "reuse_pool": lot["reuse_pool"],
            "quantity_reserved": lot["quantity_reserved"],
            "quantity_issued": lot["quantity_issued"],
            "quantity_available": lot_available(lot),
            "status": lot_status(lot),
        }
    )
    return out


def program_json(program):
    out = _common(program)
    out.update(
        {
            "branch_id": program["branch_id"],
            "challenge_id": program["challenge_id"],
            "title": program["title"],
            "age_group": program["age_group"],
            "serves_minors": program["serves_minors"],
            "delivery_mode": program["delivery_mode"],
            "partner_type": program["partner_type"],
            "partner_org_name": program["partner_org_name"],
            "partner_insurance_expires_on": fmt_date(
                program["partner_insurance_expires_on"]
            ),
            "registration_policy": program["registration_policy"],
            "start_utc": fmt_instant(program["start_utc"]),
            "end_utc": fmt_instant(program["end_utc"]),
            "attendance_target": program["attendance_target"],
            "attendance_cap": program["attendance_cap"],
            "accessibility_accommodations": list(
                program["accessibility_accommodations"]
            ),
            "supply_sku": program["supply_sku"],
            "supply_units_per_attendee": program["supply_units_per_attendee"],
            "materials_budget_cents": program["materials_budget_cents"],
            "presenter_fee_budget_cents": program["presenter_fee_budget_cents"],
            "operational_status": program["operational_status"],
            "compliance_status": program["compliance_status"],
            "registered_count": program["registered_count"],
            "registrant_references": list(program["registrant_references"]),
            "confirmed_room_capacity": program["confirmed_room_capacity"],
            "supply_draw_lines": [dict(line) for line in program["supply_draw_lines"]],
            "materials_committed_cents": program["materials_committed_cents"],
            "materials_spent_cents": program["materials_spent_cents"],
            "presenter_fee_committed_cents": program["presenter_fee_committed_cents"],
            "presenter_fee_spent_cents": program["presenter_fee_spent_cents"],
            "verified_registrant_attendance": program[
                "verified_registrant_attendance"
            ],
            "drop_in_headcount": program["drop_in_headcount"],
            "surveys_collected": program["surveys_collected"],
            "gross_attendance": program["gross_attendance"],
            "no_show_count": program["no_show_count"],
            "attendance_attainment_funder_pct": program[
                "attendance_attainment_funder_pct"
            ],
            "attendance_attainment_internal_pct": program[
                "attendance_attainment_internal_pct"
            ],
            "survey_response_rate_pct": program["survey_response_rate_pct"],
            "closure_reason": program["closure_reason"],
        }
    )
    out.update(program_money(program))
    return out


def reservation_json(reservation):
    out = _common(reservation)
    out.update(
        {
            "program_id": reservation["program_id"],
            "room_id": reservation["room_id"],
            "start_utc": fmt_instant(reservation["start_utc"]),
            "end_utc": fmt_instant(reservation["end_utc"]),
            "setup_minutes": reservation["setup_minutes"],
            "teardown_minutes": reservation["teardown_minutes"],
            "occupancy_start_utc": fmt_instant(reservation["occupancy_start_utc"]),
            "occupancy_end_utc": fmt_instant(reservation["occupancy_end_utc"]),
            "effective_capacity_seats": reservation["effective_capacity_seats"],
            "status": reservation["status"],
        }
    )
    return out


def presenter_json(presenter):
    out = _common(presenter)
    out.update(
        {
            "legal_name": presenter["legal_name"],
            "presenter_type": presenter["presenter_type"],
            "insurance_certificate_expires_on": fmt_date(
                presenter["insurance_certificate_expires_on"]
            ),
            "quoted_fee_cents": presenter["quoted_fee_cents"],
            "engagement_status": presenter["engagement_status"],
            "screening_tier": presenter["screening_tier"],
            "screening_decision": presenter["screening_decision"],
            "screening_decided_on": fmt_date(presenter["screening_decided_on"]),
            "screening_valid_until": fmt_date(presenter["screening_valid_until"]),
            "screening_status": calc.screening_status(presenter),
            "executed_contract_count": presenter["executed_contract_count"],
        }
    )
    return out


def contract_json(contract):
    out = _common(contract)
    out.update(
        {
            "presenter_id": contract["presenter_id"],
            "program_id": contract["program_id"],
            "round_trip_miles": contract["round_trip_miles"],
            "negotiation_round": contract["negotiation_round"],
            "offered_fee_cents": contract["offered_fee_cents"],
            "countered_fee_cents": contract["countered_fee_cents"],
            "agreed_fee_cents": contract["agreed_fee_cents"],
            "travel_fee_cents": contract["travel_fee_cents"],
            "escort_fee_cents": contract["escort_fee_cents"],
            "insurance_rider_fee_cents": contract["insurance_rider_fee_cents"],
            "weekend_premium_cents": contract["weekend_premium_cents"],
            "total_fee_cents": contract["total_fee_cents"],
            "kill_fee_cents": contract["kill_fee_cents"],
            "offered_by_user_id": contract["offered_by_user_id"],
            "executed_by_user_id": contract["executed_by_user_id"],
            "status": contract["status"],
        }
    )
    return out


def challenge_json(challenge):
    out = _common(challenge)
    out.update(
        {
            "name": challenge["name"],
            "logging_method": challenge["logging_method"],
            "unit_label": challenge["unit_label"],
            "start_on": fmt_date(challenge["start_on"]),
            "end_on": fmt_date(challenge["end_on"]),
            "correction_policy": challenge["correction_policy"],
            "prize_budget_cents": challenge["prize_budget_cents"],
            "prize_inventory_posture": prize_inventory_posture(challenge["id"]),
            "participant_count": challenge_participant_count(challenge["id"]),
            "deferred_award_count": challenge_deferred_count(challenge["id"]),
            "status": challenge["status"],
        }
    )
    out.update(challenge_money(challenge))
    return out


def tier_json(tier):
    awards = tier_awards(tier["id"])
    out = _common(tier)
    out.update(
        {
            "challenge_id": tier["challenge_id"],
            "tier_index": tier["tier_index"],
            "threshold_units": tier["threshold_units"],
            "prize_sku": tier["prize_sku"],
            "prize_units_per_participant": tier["prize_units_per_participant"],
            "award_count": len(
                [a for a in awards if a["status"] in ("RESERVED", "ISSUED")]
            ),
            "deferred_count": len([a for a in awards if a["status"] == "DEFERRED"]),
        }
    )
    return out


def participant_json(participant):
    units = cumulative_units(participant["id"])
    out = _common(participant)
    out.update(
        {
            "challenge_id": participant["challenge_id"],
            "home_branch_id": participant["home_branch_id"],
            "display_name": participant["display_name"],
            "age_band": participant["age_band"],
            "cumulative_units": units,
            "awarded_tier_index": awarded_tier_index(participant["id"]),
            "eligible_tier_index": eligible_tier_index(
                participant["challenge_id"], units
            ),
            "entry_count": len(participant_entries(participant["id"])),
            "last_entry_on": fmt_date(last_entry_on(participant["id"])),
        }
    )
    return out


def entry_json(entry):
    # An append-only ledger record: no updated_at and no version, ever.
    return {
        "id": entry["id"],
        "created_at": fmt_instant(entry["created_at"]),
        "participant_id": entry["participant_id"],
        "entry_type": entry["entry_type"],
        "units": entry["units"],
        "units_delta": entry["units_delta"],
        "logged_on": fmt_date(entry["logged_on"]),
        "source": entry["source"],
        "corrected_entry_id": entry["corrected_entry_id"],
        "note": entry["note"],
        "recorded_by_user_id": entry["recorded_by_user_id"],
    }


def award_json(award):
    out = _common(award)
    out.update(
        {
            "participant_id": award["participant_id"],
            "tier_id": award["tier_id"],
            "lot_id": award["lot_id"],
            "units": award["units"],
            "unit_cost_cents": award["unit_cost_cents"],
            "line_cost_cents": award["line_cost_cents"],
            "transfer_surcharge_cents": award["transfer_surcharge_cents"],
            "award_total_cents": award["award_total_cents"],
            "status": award["status"],
        }
    )
    return out


SERIALIZERS = {
    "branches": branch_json,
    "rooms": room_json,
    "programs": program_json,
    "reservations": reservation_json,
    "presenters": presenter_json,
    "contracts": contract_json,
    "challenges": challenge_json,
    "tiers": tier_json,
    "participants": participant_json,
    "entries": entry_json,
    "lots": lot_json,
    "awards": award_json,
}
