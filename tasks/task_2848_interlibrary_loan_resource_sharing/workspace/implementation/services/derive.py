"""Server-side derivations: patron counters/scores, partner balances, loan money."""
from db import base_row, db, now, touch
from services import calc

PATRON_COUNTER_KEYS = (
    "lost_count",
    "damaged_count",
    "late_return_count",
    "unclaimed_count",
    "unpaid_balance_cents",
    "pending_charge_cents",
    "open_request_count",
)
PATRON_ALL_KEYS = PATRON_COUNTER_KEYS + ("provisional_risk_score", "final_risk_score")


def patron_requests(patron_id):
    return [r for r in db.requests.values() if r.get("patron_id") == patron_id]


def patron_loans(patron_id):
    request_ids = set(r["id"] for r in patron_requests(patron_id))
    return [l for l in db.loans.values() if l.get("request_id") in request_ids]


def _patron_values(patron, keys):
    values = {}
    loans = None
    requests = None
    if keys & set(("lost_count", "damaged_count", "late_return_count",
                   "unpaid_balance_cents")):
        loans = patron_loans(patron["id"])
    if keys & set(("unclaimed_count", "pending_charge_cents", "open_request_count")):
        requests = patron_requests(patron["id"])
    if "lost_count" in keys:
        values["lost_count"] = (patron["historical_lost_count"] + sum(
            1 for l in loans if l["billing_status"] == "LOST_BILLED"))
    if "damaged_count" in keys:
        values["damaged_count"] = (patron["historical_damaged_count"] + sum(
            1 for l in loans if l["billing_status"] == "DAMAGE_BILLED"))
    if "late_return_count" in keys:
        values["late_return_count"] = (patron["historical_late_return_count"] + sum(
            1 for l in loans if (l["overdue_fine_cents"] or 0) > 0))
    if "unclaimed_count" in keys:
        values["unclaimed_count"] = (patron["historical_unclaimed_count"] + sum(
            1 for r in requests if r["status"] == "UNCLAIMED"))
    if "unpaid_balance_cents" in keys:
        values["unpaid_balance_cents"] = (patron["historical_unpaid_cents"] + sum(
            (l["outstanding_cents"] or 0) for l in loans
            if l["billing_status"] in ("FINE_ACCRUED", "DAMAGE_BILLED", "LOST_BILLED")))
    if "pending_charge_cents" in keys:
        values["pending_charge_cents"] = sum(
            (r["net_patron_charge_cents"] or 0) for r in requests
            if r["status"] not in ("CANCELLED", "UNFILLED"))
    if "open_request_count" in keys:
        values["open_request_count"] = sum(
            1 for r in requests if r["status"] not in calc.REQUEST_TERMINAL)
    return values


def standing_base(patron):
    return (calc.W_LOST * patron["lost_count"]
            + calc.W_DAMAGED * patron["damaged_count"]
            + calc.W_LATE * patron["late_return_count"]
            + calc.W_UNCLAIMED * patron["unclaimed_count"]
            + (patron["unpaid_balance_cents"] // calc.UNPAID_UNIT_CENTS))


def provisional_standing(patron):
    return calc.clamp_score(standing_base(patron))


def final_standing(patron):
    loans = patron_loans(patron["id"])
    instant = now()
    overdue_in_flight = sum(
        1 for l in loans
        if l["custody_status"] == "WITH_PATRON" and instant > l["due_at"])
    on_time_returns = sum(
        1 for l in loans
        if l["custody_status"] == "RETURNED_TO_LENDER"
        and (l["overdue_fine_cents"] or 0) == 0)
    return calc.clamp_score(standing_base(patron)
                            + calc.W_OVERDUE_IN_FLIGHT * overdue_in_flight
                            - calc.W_ON_TIME_RETURN * on_time_returns)


def recompute_patron(patron, keys, block=False, defer_touch=False):
    """Re-derive the named patron fields; bump the row only when a value moves."""
    keys = set(keys)
    changed = False
    values = _patron_values(patron, keys)
    for key in PATRON_COUNTER_KEYS:
        if key in values and patron[key] != values[key]:
            patron[key] = values[key]
            changed = True
    if "provisional_risk_score" in keys:
        score = provisional_standing(patron)
        if patron["provisional_risk_score"] != score:
            patron["provisional_risk_score"] = score
            changed = True
    if "final_risk_score" in keys:
        score = final_standing(patron)
        if patron["final_risk_score"] != score:
            patron["final_risk_score"] = score
            changed = True
        if block and score >= calc.STANDING_BLOCK_THRESHOLD \
                and patron["status"] == "ACTIVE":
            patron["status"] = "BLOCKED"
            changed = True
    if changed and not defer_touch:
        touch(patron)
    return changed


def recompute_patron_by_id(patron_id, keys, block=False):
    patron = db.patrons.get(patron_id)
    if patron is None:
        return False
    return recompute_patron(patron, keys, block=block)


def recompute_patron_for_request(req, keys, block=False):
    return recompute_patron_by_id(req.get("patron_id"), keys, block=block)


def partner_balance_values(partner_id):
    live = [r for r in db.requests.values()
            if r.get("committed_partner_id") == partner_id
            and r["status"] not in ("CANCELLED", "UNFILLED")]
    charges = [c for c in db.lending_charges.values()
               if c.get("partner_id") == partner_id]
    borrowed = len(live)
    lent = len(charges)
    return {
        "borrowed_from_count": borrowed,
        "lent_to_count": lent,
        "net_borrow_imbalance_items": borrowed - lent,
        "borrow_payable_cents": sum((r["committed_fee_cents"] or 0) for r in live),
        "lend_receivable_cents": sum((c["charge_cents"] or 0) for c in charges
                                     if c["status"] == "OPEN"),
    }


def recompute_partner(partner, defer_touch=False):
    if partner is None:
        return False
    values = partner_balance_values(partner["id"])
    changed = False
    for key, value in values.items():
        if partner[key] != value:
            partner[key] = value
            changed = True
    if changed and not defer_touch:
        touch(partner)
    return changed


def recompute_partner_by_id(partner_id):
    if not partner_id:
        return False
    return recompute_partner(db.partners.get(partner_id))


# --- loan money buckets ---------------------------------------------------

def recompute_loan_money(loan):
    loan["total_charge_cents"] = ((loan["overdue_fine_cents"] or 0)
                                  + (loan["damage_fee_cents"] or 0)
                                  + (loan["lost_replacement_cents"] or 0)
                                  + (loan["lender_processing_fee_cents"] or 0))
    loan["total_paid_cents"] = ((loan["paid_overdue_cents"] or 0)
                                + (loan["paid_damage_cents"] or 0)
                                + (loan["paid_lost_cents"] or 0)
                                + (loan["paid_processing_cents"] or 0))
    if loan["billing_status"] == "CHARGE_WAIVED":
        loan["outstanding_cents"] = 0
    else:
        loan["outstanding_cents"] = max(
            0, loan["total_charge_cents"] - loan["total_paid_cents"])
    return loan


# --- notifications --------------------------------------------------------

def notify(req, kind, subject):
    row = base_row()
    row.pop("updated_at", None)
    row.pop("version", None)
    row["request_id"] = req["id"]
    row["kind"] = kind
    row["channel"] = "EMAIL"
    row["subject"] = subject
    row["sent_at"] = now()
    db.notifications[row["id"]] = row
    return row
