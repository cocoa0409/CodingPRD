"""Lookups, cascades and shared domain services."""

import calc
import serializers
import store
from errors import fail


# ---------------------------------------------------------------------------
# path / foreign-key resolution
# ---------------------------------------------------------------------------
def get_branch(branch_id):
    rec = store.branches.get(branch_id)
    if rec is None:
        fail("ERR_BRANCH_NOT_FOUND", "Branch %s does not exist" % branch_id)
    return rec


def get_trailer_type(type_id):
    rec = store.trailer_types.get(type_id)
    if rec is None:
        fail("ERR_TRAILER_TYPE_NOT_FOUND", "Trailer type %s does not exist" % type_id)
    return rec


def get_trailer(trailer_id):
    rec = store.trailers.get(trailer_id)
    if rec is None:
        fail("ERR_TRAILER_NOT_FOUND", "Trailer %s does not exist" % trailer_id)
    return rec


def get_customer(customer_id):
    rec = store.customers.get(customer_id)
    if rec is None:
        fail("ERR_CUSTOMER_NOT_FOUND", "Customer %s does not exist" % customer_id)
    return rec


def get_certificate(certificate_id):
    rec = store.certificates.get(certificate_id)
    if rec is None:
        fail("ERR_INSURANCE_CERTIFICATE_NOT_FOUND", "Certificate %s does not exist" % certificate_id)
    return rec


def get_rate_card(card_id):
    rec = store.rate_cards.get(card_id)
    if rec is None:
        fail("ERR_RATE_CARD_NOT_FOUND", "Rate card %s does not exist" % card_id)
    return rec


def get_agreement(agreement_id):
    rec = store.agreements.get(agreement_id)
    if rec is None:
        fail("ERR_AGREEMENT_NOT_FOUND", "Agreement %s does not exist" % agreement_id)
    return rec


def get_agreement_unit(unit_id):
    rec = store.agreement_units.get(unit_id)
    if rec is None:
        fail("ERR_AGREEMENT_UNIT_NOT_FOUND", "Agreement unit %s does not exist" % unit_id)
    return rec


def get_assessment(assessment_id):
    rec = store.damage_assessments.get(assessment_id)
    if rec is None:
        fail("ERR_DAMAGE_ASSESSMENT_NOT_FOUND", "Damage assessment %s does not exist" % assessment_id)
    return rec


def get_chargeback(chargeback_id):
    rec = store.chargebacks.get(chargeback_id)
    if rec is None:
        fail("ERR_CHARGEBACK_NOT_FOUND", "Chargeback %s does not exist" % chargeback_id)
    return rec


def get_relocation(order_id):
    rec = store.relocation_orders.get(order_id)
    if rec is None:
        fail("ERR_RELOCATION_ORDER_NOT_FOUND", "Relocation order %s does not exist" % order_id)
    return rec


def get_maintenance_event(event_id):
    rec = store.maintenance_events.get(event_id)
    if rec is None:
        fail("ERR_MAINTENANCE_EVENT_NOT_FOUND", "Maintenance event %s does not exist" % event_id)
    return rec


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def active_rate_card(branch_id, trailer_type_id, product):
    matches = [c for c in store.rate_cards.values()
               if c["branch_id"] == branch_id
               and c["trailer_type_id"] == trailer_type_id
               and c["product"] == product
               and c["status"] == "ACTIVE"]
    if not matches:
        return None
    return store.sorted_rows(matches)[-1]


def units_of_agreement(agreement_id):
    return store.sorted_rows([u for u in store.agreement_units.values()
                              if u["agreement_id"] == agreement_id])


def units_on_trailer(trailer_id):
    return store.sorted_rows([u for u in store.agreement_units.values()
                              if u["trailer_id"] == trailer_id])


def trailer_has_live_booking(trailer_id, exclude_unit_id=None):
    for u in store.agreement_units.values():
        if u["trailer_id"] != trailer_id:
            continue
        if exclude_unit_id is not None and u["id"] == exclude_unit_id:
            continue
        if u["status"] in ("ALLOCATED", "OUT"):
            return True
    return False


def trailer_window_conflict(trailer_id, start, end):
    for u in store.agreement_units.values():
        if u["trailer_id"] != trailer_id or u["status"] not in ("ALLOCATED", "OUT"):
            continue
        u_start = store.parse_date(u["planned_start_date"])
        u_end = store.parse_date(u["planned_end_date"])
        if u_start is None or u_end is None:
            continue
        if calc.half_open_overlap(u_start, u_end, start, end):
            return True
    return False


# ---------------------------------------------------------------------------
# cascades
# ---------------------------------------------------------------------------
def release_trailer_if_idle(trailer):
    """After a unit left ALLOCATED without checkout, hand the trailer back."""
    if trailer_has_live_booking(trailer["id"]):
        return
    if trailer["availability_status"] == "ALLOCATED":
        trailer["availability_status"] = "AVAILABLE"
        store.touch(trailer)


def revert_agreement_if_short(agreement):
    if agreement["status"] == "RESERVED" and \
            serializers.allocated_unit_count(agreement["id"]) < agreement["unit_count"]:
        agreement["status"] = "PENDING_ALLOCATION"
        store.touch(agreement)


def swap_out_allocated_units(trailer):
    """Trailer left SERVICEABLE: swap out every ALLOCATED line standing on it."""
    for unit in units_on_trailer(trailer["id"]):
        if unit["status"] != "ALLOCATED":
            continue
        unit["status"] = "SWAPPED_OUT"
        store.touch(unit)
        release_trailer_if_idle(trailer)
        agreement = store.agreements.get(unit["agreement_id"])
        if agreement is not None:
            revert_agreement_if_short(agreement)


def cancel_open_relocations(trailer):
    """Trailer went OOS_DAMAGE: cancel every REQUESTED or APPROVED move on it."""
    for order in store.sorted_rows([o for o in store.relocation_orders.values()
                                    if o["trailer_id"] == trailer["id"]]):
        if order["status"] not in ("REQUESTED", "APPROVED"):
            continue
        order["status"] = "CANCELLED"
        order["cancel_reason"] = "TRAILER_OUT_OF_SERVICE"
        store.touch(order)


def apply_service_status_cascades(trailer, previous_status=None):
    """Run the cascades a trailer leaving SERVICEABLE triggers.

    Idempotent: swapping out only touches ALLOCATED lines and cancelling only
    touches REQUESTED/APPROVED orders, so re-running changes nothing.
    """
    current = calc.trailer_service_status(trailer)
    if current == "OOS_DAMAGE":
        cancel_open_relocations(trailer)
        swap_out_allocated_units(trailer)
    elif current == "OOS_DOT_EXPIRED":
        swap_out_allocated_units(trailer)
    return current


# ---------------------------------------------------------------------------
# reservation
# ---------------------------------------------------------------------------
def reserve_agreement(agreement, card):
    """Pin the rate card and the forward quote the first time RESERVED is reached."""
    branch = store.branches.get(agreement["branch_id"])
    if agreement.get("rate_card_id") is None:
        agreement["rate_card_id"] = card["id"]
        agreement["quoted_total_cents"] = calc.quoted_total_cents(agreement, card, branch)
    agreement["status"] = "RESERVED"


def eligible_trailers(agreement):
    start = store.parse_date(agreement["start_date"])
    end = store.parse_date(agreement["end_date"])
    out = []
    for t in store.trailers.values():
        if t["current_branch_id"] != agreement["branch_id"]:
            continue
        if t["trailer_type_id"] != agreement["trailer_type_id"]:
            continue
        if t["availability_status"] != "AVAILABLE":
            continue
        if calc.trailer_service_status(t) != "SERVICEABLE":
            continue
        expires = store.parse_date(t.get("dot_expires_on"))
        if expires is None or not (expires > end):
            continue
        if trailer_window_conflict(t["id"], start, end):
            continue
        out.append(t)
    return out


def rank_trailers(rows):
    def key(t):
        expires = store.parse_date(t.get("dot_expires_on"))
        return (t.get("hub_miles", 0),
                -expires.toordinal() if expires else 0,
                t["created_at"],
                t["_seq"])
    return sorted(rows, key=key)


def candidate_pool(agreement, branch):
    ranked = rank_trailers(eligible_trailers(agreement))
    if agreement["product"] == "SHORT_TERM_RENTAL" and agreement_intersects_peak(agreement, branch):
        pct = calc.dec(branch.get("lease_reserve_pct") or 0)
        reserved = calc.ceil_dec(calc.dec(len(ranked)) * pct)
        return ranked[reserved:]
    return ranked


def agreement_intersects_peak(agreement, branch):
    start = store.parse_date(agreement["start_date"])
    end = store.parse_date(agreement["end_date"])
    peak_start = store.parse_date(branch.get("peak_season_start_date"))
    peak_end = store.parse_date(branch.get("peak_season_end_date"))
    if None in (start, end, peak_start, peak_end):
        return False
    # half-open [start, end) against the closed [peak_start, peak_end]
    return start <= peak_end and peak_start < end
