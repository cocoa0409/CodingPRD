"""Property records and the site-visit repair pacing (PRD 3.1).

Properties are recorded against the household that owns them.  Creation
requires the owning ``homeowner_id``, a street ``address``, a ``kind`` of either
``DEPARTING`` or ``NEW``, the ``appraised_value_cents`` and a ``condition_grade``
of ``A``, ``B``, ``C`` or ``D``.  Several fields are optional and carry defaults
an implementer must honour rather than treat as absent: ``mortgage_payoff_cents``
defaults to 0 (correct for a home owned free and clear), ``purchase_price_cents``
defaults to 0 and is meaningful only for a ``NEW`` home, ``appraisal_date``
defaults to the very start of the logical clock, and ``repair_progress_bps``
defaults to 300.

The initial record also seeds two fields the client never supplies: every
property begins ``UNLISTED`` in its ``listing_status`` and ``NOT_STARTED`` in its
``repair_status``, with a ``site_visit_count`` of zero and a
``program_inventory_flag`` of false that only ever turns true when the program
itself acquires the home.

Repairs are paced by physical inspection rather than paperwork: each recorded
site visit raises ``site_visit_count`` by one, and ``repair_status`` flips to
``COMPLETE`` at the moment the visit count, multiplied by one hundred, is at
least the property's ``repair_progress_bps`` requirement.  A property left at its
default requirement of 300 therefore completes on its third recorded visit.
"""

from constants import (
    CONDITION_GRADES,
    DEFAULT_APPRAISAL_DATE,
    DEFAULT_MORTGAGE_PAYOFF_CENTS,
    DEFAULT_PURCHASE_PRICE_CENTS,
    DEFAULT_REPAIR_PROGRESS_BPS,
    DEFAULT_SITE_VISIT_COUNT,
    PROPERTY_KINDS,
    REPAIR_VISIT_SCALE,
)
from services import create, touch
from services.lookup import get_homeowner, get_property
from timeutil import parse_iso
from validation import body_of, get_datetime, get_enum, get_int, get_str


def create_property(payload):
    data = body_of(payload)

    homeowner_id = get_str(data, "homeowner_id", required=True)
    homeowner = get_homeowner(homeowner_id)

    address = get_str(data, "address", required=True)
    kind = get_enum(data, "kind", PROPERTY_KINDS, required=True)
    appraised_value_cents = get_int(data, "appraised_value_cents", required=True, minimum=0)
    condition_grade = get_enum(data, "condition_grade", CONDITION_GRADES, required=True)

    mortgage_payoff_cents = get_int(
        data, "mortgage_payoff_cents", required=False, default=DEFAULT_MORTGAGE_PAYOFF_CENTS, minimum=0
    )
    purchase_price_cents = get_int(
        data, "purchase_price_cents", required=False, default=DEFAULT_PURCHASE_PRICE_CENTS, minimum=0
    )
    appraisal_date = get_datetime(
        data, "appraisal_date", required=False, default=parse_iso(DEFAULT_APPRAISAL_DATE)
    )
    repair_progress_bps = get_int(
        data, "repair_progress_bps", required=False, default=DEFAULT_REPAIR_PROGRESS_BPS, minimum=0
    )

    from timeutil import format_iso

    record = {
        "homeowner_id": homeowner["id"],
        "address": address,
        "kind": kind,
        "appraised_value_cents": appraised_value_cents,
        "mortgage_payoff_cents": mortgage_payoff_cents,
        "appraisal_date": format_iso(appraisal_date),
        "purchase_price_cents": purchase_price_cents,
        "condition_grade": condition_grade,
        "listing_status": "UNLISTED",
        "repair_status": "NOT_STARTED",
        "site_visit_count": DEFAULT_SITE_VISIT_COUNT,
        "repair_progress_bps": repair_progress_bps,
        "program_inventory_flag": False,
    }
    create("properties", record)
    return record


def record_site_visit(property_id):
    """Record a coordinator site visit and re-evaluate repair completion."""
    record = get_property(property_id)
    record["site_visit_count"] = int(record.get("site_visit_count") or 0) + 1
    required_visits = int(record.get("repair_progress_bps") or 0)
    if record["site_visit_count"] * REPAIR_VISIT_SCALE >= required_visits:
        record["repair_status"] = "COMPLETE"
    touch(record)
    return record


def set_listing_status(record, value):
    record["listing_status"] = value
    touch(record)
    return record


def set_repair_status(record, value):
    record["repair_status"] = value
    touch(record)
    return record


def repair_ceiling_cents(record):
    """The property's repair ceiling.

    PRD 3.4 states the cumulative approved amount across every repair advance
    for the property may not exceed "that property's repair ceiling", and the
    scaffold's ``repair_progress_bps`` is the property's declared repair
    requirement.  That field is expressed as a required-visit count scaled by
    one hundred, so the ceiling is read on the same scale: the completion
    requirement in cents.
    """
    return int(record.get("repair_progress_bps") or 0)