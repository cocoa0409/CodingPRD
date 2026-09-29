"""Derived figures, the posting append path, and the cascade chain."""
from flask import g

import db
from money import D, ZERO, q2
from services import calc

ROOM_NIGHT_TYPES = ("ROOM", "ALLOWANCE")
OTHER_ROOM_TYPES = ("NO_SHOW", "LATE_CHECKOUT")
TAX_TYPES = ("OCCUPANCY_TAX", "TAX_TRUE_UP")
REVENUE_TYPES = set(ROOM_NIGHT_TYPES) | set(OTHER_ROOM_TYPES) | set(TAX_TYPES)
CONTROL_TYPES = ("LEDGER_TRANSFER", "DEPOSIT_APPLIED")
TAXABLE_TYPES = ("ROOM", "NO_SHOW", "ALLOWANCE")
CHARGE_ACCEPTING = ("OPEN", "ROOM_POSTING", "REOPENED")
POSTABLE_TYPES = ("MISC_CHARGE", "PAYMENT", "LEDGER_TRANSFER", "DEPOSIT_APPLIED")


def touch(row):
    """Mark a row mutated: updated_at moves and version increments once."""
    if row is None or row.get("_kind") == "JournalPosting":
        return
    seen = getattr(g, "_touched", None)
    if seen is None:
        seen = set()
        g._touched = seen
    key = (row.get("_kind"), row["id"])
    if key in seen:
        return
    seen.add(key)
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = db.now()


# --------------------------------------------------------------------------
# lookups over the posting book
# --------------------------------------------------------------------------

def postings():
    return db.all_of("postings")


def postings_of_folio(folio_id):
    return [p for p in postings() if p["folio_id"] == folio_id]


def postings_of_date(business_date_id):
    return [p for p in postings() if p["business_date_id"] == business_date_id]


def reversed_posting_ids():
    return set(
        p["reverses_posting_id"] for p in db.store.postings.values()
        if p.get("reverses_posting_id")
    )


def sum_amounts(rows, types=None):
    total = ZERO
    for row in rows:
        if types is None or row["charge_type"] in types:
            total = total + row["amount"]
    return q2(total)


# --------------------------------------------------------------------------
# folio
# --------------------------------------------------------------------------

def folio_figures(folio):
    charges = ZERO
    credits = ZERO
    for row in postings_of_folio(folio["id"]):
        if row["amount"] > 0:
            charges = charges + row["amount"]
        elif row["amount"] < 0:
            credits = credits + row["amount"]
    charges = q2(charges)
    credits = q2(credits)
    balance = q2(charges + credits)
    if folio["settlement_status"] == "TRANSFERRED_TO_CITY_LEDGER":
        status = "TRANSFERRED_TO_CITY_LEDGER"
    elif balance == ZERO:
        status = "SETTLED"
    elif credits != ZERO:
        status = "PARTIALLY_SETTLED"
    else:
        status = "UNSETTLED"
    return {
        "charges_total_amount": charges,
        "credits_total_amount": credits,
        "balance_amount": balance,
        "settlement_status": status,
    }


def folio_balance(folio):
    return folio_figures(folio)["balance_amount"]


def folio_hold(folio):
    """settlement_hold: a declined authorisation that is not yet resolved."""
    for auth in db.store.card_auths.values():
        if auth["folio_id"] != folio["id"]:
            continue
        if auth["status"] == "DECLINED" and auth["follow_up_status"] != "RESOLVED":
            return True
    return False


def rederive_folio(folio):
    """Re-derive a folio's money fields; that counts as a mutation."""
    figures = folio_figures(folio)
    folio["settlement_status"] = figures["settlement_status"]
    touch(folio)
    return figures


def folios_of_property(property_id):
    return [f for f in db.all_of("folios") if f["property_id"] == property_id]


# --------------------------------------------------------------------------
# card authorisations
# --------------------------------------------------------------------------

def auth_aging_days(auth):
    return calc.aging_days(auth["obtained_at"], db.now())


def lapse_authorization(auth, prop=None):
    """APPROVED lapses to EXPIRED once aging reaches the validity window."""
    if auth["status"] != "APPROVED":
        return auth
    if prop is None:
        folio = db.store.folios.get(auth["folio_id"])
        prop = db.store.properties.get(folio["property_id"]) if folio else None
    if prop is None:
        return auth
    if auth_aging_days(auth) >= int(prop["card_authorization_valid_days"]):
        auth["status"] = "EXPIRED"
        touch(auth)
    return auth


def auths_of_folio(folio_id):
    return [a for a in db.all_of("card_auths") if a["folio_id"] == folio_id]


def declined_unresolved_count(property_id):
    count = 0
    folio_ids = set(f["id"] for f in folios_of_property(property_id))
    for auth in db.store.card_auths.values():
        if auth["folio_id"] not in folio_ids:
            continue
        if auth["status"] == "DECLINED" and auth["follow_up_status"] != "RESOLVED":
            count += 1
    return count


# --------------------------------------------------------------------------
# ledger accounts
# --------------------------------------------------------------------------

def ledger_balance(account):
    total = D(account["opening_balance_amount"])
    for row in db.store.postings.values():
        if row["ledger_account_id"] == account["id"]:
            total = total + row["amount"]
    return q2(total)


# --------------------------------------------------------------------------
# business date
# --------------------------------------------------------------------------

def date_aggregates(date_row):
    prop = db.store.properties.get(date_row["property_id"])
    lines = postings_of_date(date_row["id"])
    room_night = sum_amounts(lines, ROOM_NIGHT_TYPES)
    other_room = sum_amounts(lines, OTHER_ROOM_TYPES)
    room_revenue = q2(room_night + other_room)
    tax_revenue = sum_amounts(lines, TAX_TYPES)
    allowance_credit = sum_amounts(lines, ("ALLOWANCE",))
    ledger_control = sum_amounts(lines, CONTROL_TYPES)

    outlet_revenue = ZERO
    closed_tickets = 0
    for ticket in db.store.tickets.values():
        if ticket["business_date_id"] != date_row["id"]:
            continue
        if ticket["status"] == "CLOSED":
            closed_tickets += 1
            outlet_revenue = outlet_revenue + D(ticket["total_amount"])
    outlet_revenue = q2(outlet_revenue)
    total_revenue = q2(room_revenue + tax_revenue + outlet_revenue)

    room_total = int(prop["room_count_total"]) if prop else 0
    rooms_available = room_total - int(date_row["out_of_order_room_count"])
    if rooms_available < 0:
        rooms_available = 0
    reversed_ids = reversed_posting_ids()
    occupied = set()
    for row in lines:
        if row["charge_type"] != "ROOM":
            continue
        if row["id"] in reversed_ids:
            continue
        if row["folio_id"]:
            occupied.add(row["folio_id"])
    rooms_occupied = len(occupied)

    variance_total = ZERO
    unresolved = 0
    for batch in db.store.batches.values():
        if batch["business_date_id"] != date_row["id"]:
            continue
        if batch["status"] in ("DECLARED", "VARIANCE_FLAGGED", "RECOUNT_REQUESTED"):
            unresolved += 1
        # PRD 3.5: only a VARIANCE_FLAGGED batch "contributes the absolute value of
        # its variance" to the day's total, and an ACCEPTED_WITH_VARIANCE batch
        # "continues contributing" it. A MATCHED batch does not, and a
        # RECOUNT_REQUESTED batch leaves the total.
        if (batch["status"] in ("VARIANCE_FLAGGED", "ACCEPTED_WITH_VARIANCE")
                and batch["variance_amount"] is not None):
            variance_total = variance_total + abs(D(batch["variance_amount"]))

    return {
        "rooms_available_count": rooms_available,
        "rooms_occupied_count": rooms_occupied,
        "room_night_revenue_amount": room_night,
        "other_room_revenue_amount": other_room,
        "room_revenue_amount": room_revenue,
        "tax_revenue_amount": tax_revenue,
        "outlet_revenue_amount": outlet_revenue,
        "closed_outlet_ticket_count": closed_tickets,
        "allowance_credit_amount": allowance_credit,
        "total_revenue_amount": total_revenue,
        "occupancy_pct": calc.occupancy_pct(rooms_occupied, rooms_available),
        "adr_amount": calc.adr(room_night, rooms_occupied),
        "revpar_amount": calc.revpar(room_night, rooms_available),
        "settlement_variance_total_amount": q2(variance_total),
        "unresolved_settlement_batch_count": unresolved,
        "ledger_control_amount": ledger_control,
        "declined_authorization_count": declined_unresolved_count(
            date_row["property_id"]
        ),
    }


def dates_of_period(period_id):
    return [d for d in db.all_of("business_dates")
            if d["accounting_period_id"] == period_id]


def period_subsystem_total(period):
    total = ZERO
    for date_row in dates_of_period(period["id"]):
        if date_row["status"] in ("CLOSED", "ARCHIVED"):
            total = total + date_aggregates(date_row)["total_revenue_amount"]
    return q2(total)


def reports_of_date(business_date_id):
    return [r for r in db.all_of("reports")
            if r["business_date_id"] == business_date_id]


def supersede_reports(date_row):
    """Any later change to a day's revenue aggregates invalidates its reports."""
    for report in reports_of_date(date_row["id"]):
        if report["status"] in ("DRAFT", "DISTRIBUTED"):
            report["status"] = "SUPERSEDED"
            touch(report)


# --------------------------------------------------------------------------
# the append path
# --------------------------------------------------------------------------

def append_posting(charge_type, amount, business_date, source_channel,
                   posted_by_user_id, folio=None, ledger_account_id=None,
                   night_index=None, reason_code=None, memo=None,
                   outlet_ticket_id=None, allowance_id=None,
                   reverses_posting_id=None):
    """Append one immutable journal line and run the cascade it triggers."""
    row = db.insert("postings", {
        "_kind": "JournalPosting",
        "folio_id": folio["id"] if folio else None,
        "ledger_account_id": ledger_account_id,
        "business_date_id": business_date["id"],
        "outlet_ticket_id": outlet_ticket_id,
        "allowance_id": allowance_id,
        "reverses_posting_id": reverses_posting_id,
        "charge_type": charge_type,
        "amount": q2(amount),
        "night_index": night_index,
        "source_channel": source_channel,
        "reason_code": reason_code,
        "posted_by_user_id": posted_by_user_id,
        "memo": memo,
    })
    if folio is not None:
        rederive_folio(folio)
    if ledger_account_id:
        touch(db.store.ledger_accounts.get(ledger_account_id))
    touch(business_date)
    if charge_type in REVENUE_TYPES:
        supersede_reports(business_date)
    return row
