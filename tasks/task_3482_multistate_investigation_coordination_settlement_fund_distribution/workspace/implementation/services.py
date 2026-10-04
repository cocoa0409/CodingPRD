"""Shared cross-route helpers: provisional allocation variant, per-settlement
child lookups, fund-status recomputation."""
import calc
import db


def active_participations_of(investigation_id):
    return [
        p
        for p in db.participations.values()
        if p["investigation_id"] == investigation_id and p["status"] == "ACTIVE"
    ]


def compute_provisional(settlement):
    """Provisional variant (PRD §2.7): lead-cost/distributable plus weight
    normalization over the investigation's ACTIVE participations at proposal
    time, reading live state-office registry values; remainder ties broken by
    participation invited_at ASC, never by id. Creates no allocation lines."""
    _lead_cost, distributable = calc.lead_cost_and_distributable(
        settlement["monetary_total_cents"], settlement["restitution_reserve_cents"]
    )
    entries = []
    for p in active_participations_of(settlement["investigation_id"]):
        office = db.offices.get(p["state_office_id"])
        if office is None:
            continue
        entries.append(
            {
                "key": office["state_code"],
                "raw": calc.raw_basis_value(settlement, office),
                "tie_dt": p["invited_at"],
                "tie_seq": p["_seq"],
            }
        )
    settlement["provisional_distributable_cents"] = distributable
    settlement["provisional_weight_bps_by_state"] = calc.normalize_weights(entries)


def settlement_lines(settlement_id):
    return [l for l in db.lines.values() if l["settlement_id"] == settlement_id]


def settlement_disbursements(settlement_id):
    line_ids = {l["id"] for l in settlement_lines(settlement_id)}
    return [d for d in db.disbursements.values() if d["allocation_line_id"] in line_ids]


def maybe_mark_fund_disbursed(settlement):
    """fund_status DISBURSING -> DISBURSED once every allocation line of the
    settlement has reached a terminal status (DISBURSED or REVERTED)."""
    if settlement["fund_status"] != "DISBURSING":
        return False
    lines = settlement_lines(settlement["id"])
    if lines and all(l["status"] in ("DISBURSED", "REVERTED") for l in lines):
        settlement["fund_status"] = "DISBURSED"
        return True
    return False


def live_settlement_of_investigation(investigation_id):
    inv = db.investigations.get(investigation_id)
    if inv is None or inv.get("active_settlement_id") is None:
        return None
    return db.settlements.get(inv["active_settlement_id"])
