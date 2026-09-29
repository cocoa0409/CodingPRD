"""Serialization. Derived fields are re-derived at read time so they can never
drift from the rows they summarise."""
import calc
import ledger
from store import public


def property_view(rec):
    return public(rec, {
        "outstanding_balance_cents": ledger.property_balance(rec["id"]),
        "unit_count": calc.unit_count(rec["id"]),
    })


def unit_view(rec):
    return public(rec)


def sku_view(rec):
    return public(rec)


def resident_view(rec):
    return public(rec)


def subscription_view(rec):
    return public(rec, {"next_ship_date": calc.next_ship_date(rec["id"])})


def shipment_view(rec):
    return public(rec)


def reading_view(rec):
    return public(rec)


def survey_view(rec):
    return public(rec)


def case_view(rec):
    return public(rec)


def claim_view(rec):
    return public(rec)


def entitlement_view(rec):
    return public(rec)


def ledger_view(rec):
    return public(rec)


def transfer_view(rec):
    return public(rec)
