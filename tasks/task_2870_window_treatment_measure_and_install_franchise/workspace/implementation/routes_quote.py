"""Quote assembly, presentation, revision and acceptance."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import calc
from core import (ROLE_DESIGNER, ROLE_FRANCHISEE, ROLE_FRANCHISOR, append_ledger, auth,
                  fail, free_lead_capacity, get_body, get_consultation, get_quote,
                  list_response, new_row, openings_of_quote, rederive_consultation,
                  rederive_quote_counts, rederive_territory, req_fk, req_int, req_str,
                  respond_object, require_designer_assignment, require_territory_active,
                  royalty_on, serialize, store, territory_of_consultation,
                  territory_of_lead, territory_of_quote, touch)

bp = Blueprint("quote", __name__)

CONSULTATION_OPEN_STATES = ("SCHEDULED", "COMPLETED")


def _designer_of_quote(quote):
    consultation = store.consultations.get(quote["consultation_id"])
    return consultation["designer_id"] if consultation else None


def _sync_lead_id(quote):
    consultation = store.consultations.get(quote["consultation_id"])
    if consultation is not None:
        quote["lead_id"] = consultation["lead_id"]


def flip_if_expired(quote):
    """Ladder stage 14: persist the flip, then reject the triggering request."""
    if (quote["status"] == "PRESENTED" and quote["expires_at"] is not None
            and store.clock >= quote["expires_at"]):
        quote["status"] = "EXPIRED"
        touch(quote)
        lead = store.leads.get(quote["lead_id"])
        if lead is not None and lead["status"] == "CONSULT_COMPLETE":
            territory = territory_of_lead(lead)
            lead["status"] = "LOST"
            touch(lead)
            free_lead_capacity(territory)
        fail("ERR_QUOTE_EXPIRED", "the quote expired at %s" % quote["expires_at"])


def _cordless_gate(quote):
    openings = openings_of_quote(quote["id"])
    lead = store.leads.get(quote["lead_id"])
    if calc.cordless_violated(openings, lead):
        fail("ERR_CORD_HAZARD_NOT_PERMITTED",
             "a child-occupied opening requires a cordless or motorized lift")


# --------------------------------------------------------------------------
@bp.route("/blinds/quotes", methods=["POST"])
def create_quote():
    actor = auth(ROLE_DESIGNER)
    body = get_body()
    consultation = req_fk(body, "consultation_id", get_consultation)
    if consultation is not None:
        require_designer_assignment(actor, consultation["designer_id"])
    consultation = get_consultation(req_str(body, "consultation_id", 1, None))
    expected_version = req_int(body, "expected_consultation_version")
    if expected_version != consultation["version"]:
        fail("ERR_STALE_CONSULTATION_VERSION",
             "consultation version is %s" % consultation["version"])
    require_territory_active(territory_of_consultation(consultation))
    if consultation["status"] not in CONSULTATION_OPEN_STATES:
        fail("ERR_CONSULTATION_CLOSED",
             "consultation status is %s" % consultation["status"])
    superseded = []
    for quote in store.quotes.values():
        if quote["consultation_id"] != consultation["id"]:
            continue
        if quote["status"] == "DRAFT":
            superseded.append(quote)
        elif (quote["status"] == "PRESENTED" and quote["expires_at"] is not None
                and store.clock < quote["expires_at"]):
            superseded.append(quote)
    released = set(q["id"] for q in superseded)
    sweep = []
    for opening in store.openings.values():
        if opening["consultation_id"] != consultation["id"]:
            continue
        if opening["measure_status"] == "CONFIGURED":
            sweep.append(opening)
        elif (opening["measure_status"] == "QUOTED"
                and opening.get("quote_id") in released):
            sweep.append(opening)
    if not sweep:
        fail("ERR_QUOTE_HAS_NO_OPENINGS",
             "the consultation carries no configured opening to attach")
    for quote in superseded:
        quote["status"] = "SUPERSEDED"
        quote["expires_at"] = None
        touch(quote)
        for opening in openings_of_quote(quote["id"]):
            opening["quote_id"] = None
            if opening["measure_status"] == "QUOTED":
                opening["measure_status"] = "CONFIGURED"
            touch(opening)
    row = new_row({
        "consultation_id": consultation["id"],
        "lead_id": consultation["lead_id"],
        "status": "DRAFT",
        "revision_count": 0,
        "opening_count": 0,
        "motorized_opening_count": 0,
        "subtotal_cents": 0,
        "install_fee_cents": 0,
        "pre_discount_total_cents": 0,
        "discount_pct": Decimal("0"),
        "discount_cents": 0,
        "total_cents": 0,
        "net_sales_cents": 0,
        "recognized_net_sales_cents": 0,
        "credited_net_sales_cents": 0,
        "presented_at": None,
        "expires_at": None,
        "accepted_at": None,
    })
    store.quotes[row["id"]] = row
    for opening in sweep:
        opening["quote_id"] = row["id"]
        opening["measure_status"] = "QUOTED"
        touch(opening)
    rederive_quote_counts(row)
    rederive_consultation(consultation)
    return respond_object(serialize(row), 201)


@bp.route("/blinds/quotes/<quote_id>", methods=["GET"])
def read_quote(quote_id):
    auth(ROLE_FRANCHISOR, ROLE_FRANCHISEE, ROLE_DESIGNER)
    return respond_object(serialize(get_quote(quote_id)), 200)


@bp.route("/blinds/quotes", methods=["GET"])
def list_quotes():
    auth(ROLE_FRANCHISOR, ROLE_FRANCHISEE, ROLE_DESIGNER)
    return list_response(store.quotes.values(), ("consultation_id", "status"))


@bp.route("/blinds/quotes/<quote_id>/present", methods=["POST"])
def present_quote(quote_id):
    actor = auth(ROLE_DESIGNER)
    quote = get_quote(quote_id)
    require_designer_assignment(actor, _designer_of_quote(quote))
    require_territory_active(territory_of_quote(quote))
    flip_if_expired(quote)
    if quote["status"] != "DRAFT":
        fail("ERR_QUOTE_NOT_DRAFT", "quote status is %s" % quote["status"])
    openings = openings_of_quote(quote["id"])
    if not openings:
        fail("ERR_QUOTE_HAS_NO_OPENINGS", "the quote carries no attached opening")
    _cordless_gate(quote)
    figures = calc.quote_waterfall(openings)
    quote.update(figures)
    quote["presented_at"] = store.clock
    quote["expires_at"] = store.clock + timedelta(days=calc.QUOTE_VALIDITY_DAYS)
    quote["status"] = "PRESENTED"
    _sync_lead_id(quote)
    touch(quote)
    return respond_object(serialize(quote), 200)


@bp.route("/blinds/quotes/<quote_id>/revise", methods=["POST"])
def revise_quote(quote_id):
    actor = auth(ROLE_DESIGNER)
    quote = get_quote(quote_id)
    require_designer_assignment(actor, _designer_of_quote(quote))
    flip_if_expired(quote)
    if quote["status"] != "PRESENTED":
        fail("ERR_QUOTE_NOT_PRESENTED", "quote status is %s" % quote["status"])
    if quote["revision_count"] >= calc.QUOTE_MAX_REVISIONS:
        fail("ERR_REVISION_LIMIT_REACHED", "the revision cap of two is reached")
    quote["status"] = "DRAFT"
    quote["revision_count"] += 1
    quote["expires_at"] = None
    quote["subtotal_cents"] = 0
    quote["install_fee_cents"] = 0
    quote["pre_discount_total_cents"] = 0
    quote["discount_cents"] = 0
    quote["total_cents"] = 0
    quote["net_sales_cents"] = 0
    quote["discount_pct"] = Decimal("0")
    rederive_quote_counts(quote)
    _sync_lead_id(quote)
    touch(quote)
    return respond_object(serialize(quote), 200)


@bp.route("/blinds/quotes/<quote_id>/accept", methods=["POST"])
def accept_quote(quote_id):
    actor = auth(ROLE_DESIGNER)
    quote = get_quote(quote_id)
    require_designer_assignment(actor, _designer_of_quote(quote))
    territory = territory_of_quote(quote)
    require_territory_active(territory)
    flip_if_expired(quote)
    if quote["status"] != "PRESENTED":
        fail("ERR_QUOTE_NOT_PRESENTED", "quote status is %s" % quote["status"])
    _cordless_gate(quote)
    recognized = quote["net_sales_cents"]
    quote["status"] = "ACCEPTED"
    quote["accepted_at"] = store.clock
    quote["recognized_net_sales_cents"] = recognized
    rederive_quote_counts(quote)
    _sync_lead_id(quote)
    touch(quote)
    if territory is not None:
        territory["net_sales_cents"] = territory["net_sales_cents"] + recognized
        append_ledger(territory, "NET_SALES_ROYALTY", royalty_on(territory, recognized),
                      recognized, "QUOTE", quote["id"], "quote_accepted")
        rederive_territory(territory)
    lead = store.leads.get(quote["lead_id"])
    if lead is not None and lead["status"] in ("CONSULT_COMPLETE", "ROUTED"):
        lead["status"] = "CONVERTED"
        touch(lead)
        free_lead_capacity(territory)
    return respond_object(serialize(quote), 200)
