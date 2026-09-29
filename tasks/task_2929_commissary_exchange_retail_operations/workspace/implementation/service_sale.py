"""Sale rollup, the vendor allowance variants and the shared eligibility gate."""

import calculations as calc
import constants as C
import derive
from db import db
from errors import ApiError


def active_assortments():
    return list(db.assortments.values())


def governing_for(store_id, product_id, reference_instant):
    return calc.governing_assortment(
        active_assortments(), store_id, product_id, reference_instant
    )


def governing_by_line(sale, lines):
    """Both allowance variants resolve the governing allocation at the visit's
    business_date; only the window-test instant differs between them."""
    mapping = {}
    for line in lines:
        mapping[line["id"]] = governing_for(
            sale["store_id"], line["product_id"], sale["business_date"]
        )
    return mapping


def rollup(sale):
    store = db.stores[sale["store_id"]]
    lines = derive.lines_of_sale(sale["id"])
    sale.update(calc.sale_surcharge_rollup(store, lines))
    return lines


def refresh_provisional_allowance(sale, lines):
    mapping = governing_by_line(sale, lines)
    total, per_line = calc.vendor_promotional_allowance(lines, mapping, sale["business_date"])
    for line in lines:
        line["line_allowance_cents"] = per_line[line["id"]]
    sale["provisional_allowance_cents"] = total
    return total


def settled_allowance(sale, lines, tender_instant):
    mapping = governing_by_line(sale, lines)
    total, _per_line = calc.vendor_promotional_allowance(lines, mapping, tender_instant)
    return total


# --------------------------------------------------------------------------
# eligibility gate (PRD 3.2 / 3.5 / 3.8)
# --------------------------------------------------------------------------


def require_card_valid(patron):
    if patron["card_status"] != "VALID":
        raise ApiError("ERR_PATRON_CARD_NOT_VALID")


def require_sponsor_card_valid(patron):
    if patron["id_card_class"] != "DEPENDENT":
        return
    sponsor = db.patrons.get(patron["sponsor_patron_id"])
    if sponsor is None or sponsor["card_status"] != "VALID":
        raise ApiError("ERR_SPONSOR_CARD_NOT_VALID")


def require_channel_and_region(patron, store):
    if store["channel"] not in C.CHANNEL_ELIGIBILITY[patron["id_card_class"]]:
        raise ApiError("ERR_PATRON_NOT_ELIGIBLE_FOR_CHANNEL")
    if store["region"] not in C.REGION_ELIGIBILITY[patron["id_card_class"]]:
        raise ApiError("ERR_PATRON_NOT_ELIGIBLE_IN_REGION")


def delegation_covers(delegation, instant):
    """Half-open coverage: valid_from <= instant < valid_to."""
    return delegation["valid_from"] <= instant < delegation["valid_to"]
