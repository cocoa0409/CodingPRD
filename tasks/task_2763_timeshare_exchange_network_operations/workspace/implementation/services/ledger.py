"""The append-only two-balance ledger (PRD 2.7)."""

from store import db, touch


def _recompute_balances(member):
    power = 0
    cash = 0
    member_id = member["id"]
    for entry in db.ledger_entries.values():
        if entry["member_id"] == member_id:
            power += entry["power_delta"]
            cash += entry["cash_delta_cents"]
    member["trading_power_balance"] = power
    member["wallet_credit_cents"] = cash


def post(member, entry_type, related_entity_type, related_entity_id, description,
         power_delta=0, cash_delta_cents=0):
    """Write one ledger entry and reconcile the member's two balances."""
    entry = db.new_row({
        "member_id": member["id"],
        "entry_type": entry_type,
        "power_delta": power_delta,
        "cash_delta_cents": cash_delta_cents,
        "related_entity_type": related_entity_type,
        "related_entity_id": related_entity_id,
        "description": description,
    })
    db.ledger_entries[entry["id"]] = entry
    _recompute_balances(member)
    touch(member)
    return entry


def credit_power(member, entry_type, related_entity_type, related_entity_id, description, amount):
    """Credit trading power.  A zero amount still posts an entry."""
    return post(member, entry_type, related_entity_type, related_entity_id, description,
                power_delta=amount)


def debit_power_clamped(member, entry_type, related_entity_type, related_entity_id,
                        description, magnitude):
    """Debit trading power, clamped so the balance lands no lower than 0 (PRD 2.7)."""
    available = member["trading_power_balance"]
    applied = min(magnitude, available) if magnitude > 0 else 0
    return post(member, entry_type, related_entity_type, related_entity_id, description,
                power_delta=-applied)


def move_cash(member, entry_type, related_entity_type, related_entity_id, description, amount):
    return post(member, entry_type, related_entity_type, related_entity_id, description,
                cash_delta_cents=amount)
