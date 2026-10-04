"""Combined multi-brand negotiations with a single retailer buyer."""

from flask import Blueprint, request

import clock
import storage
from calculations import (new_record, bump, negotiation_totals,
                          negotiation_expiry_for)
from envelope import success, paginate, sorted_by_created
from errors import fail
from rbac import guard, synchronized, ALL_ROLES
from serializers import negotiation_out
from validation import body_json, f_str, f_int, f_enum, f_dt, f_list, _MISSING, _invalid

bp = Blueprint("negotiations", __name__, url_prefix="/portfolio")

ACTIVE_NEGOTIATION_STATES = ("TERMS_PROPOSED", "ACCEPTED")


def _validate_brand_terms(body):
    """Step 4 shape/range checks on the brand_terms array."""
    terms = f_list(body, "brand_terms")
    cleaned = []
    for idx, entry in enumerate(terms):
        if not isinstance(entry, dict):
            _invalid(f"brand_terms[{idx}]", "must be an object")
        brand_id = entry.get("brand_id", _MISSING)
        if brand_id is _MISSING or not isinstance(brand_id, str):
            _invalid(f"brand_terms[{idx}].brand_id", "must be a string")
        baseline = entry.get("baseline_facings", _MISSING)
        if baseline is _MISSING or isinstance(baseline, bool) or not isinstance(baseline, int) or baseline < 0:
            _invalid(f"brand_terms[{idx}].baseline_facings", "must be an integer >= 0")
        proposed = entry.get("proposed_facings", _MISSING)
        if proposed is _MISSING or isinstance(proposed, bool) or not isinstance(proposed, int) or proposed < 0:
            _invalid(f"brand_terms[{idx}].proposed_facings", "must be an integer >= 0")
        cleaned.append({
            "brand_id": brand_id,
            "baseline_facings": baseline,
            "proposed_facings": proposed,
        })
    return cleaned


@bp.post("/combined-negotiations")
@synchronized
def create_negotiation():
    guard(["PortfolioManager"])
    body = body_json(required=True)
    retailer_id = f_str(body, "retailer_id")
    period_code = f_str(body, "period_code")
    brand_terms = _validate_brand_terms(body)
    effective_from = f_dt(body, "effective_from")
    effective_to = f_dt(body, "effective_to")
    # step 4 (PRD §3.6): window coherence is a body well-formedness failure
    if not effective_from < effective_to:
        fail("ERR_INVALID_REQUEST",
             "effective_from must be strictly before effective_to")
    # step 6: body FKs resolve (retailer, then each brand in brand_terms)
    retailer = storage.retailers.get(retailer_id)
    if retailer is None:
        fail("ERR_NOT_FOUND", f"retailer {retailer_id} not found")
    brands = []
    for t in brand_terms:
        b = storage.brands.get(t["brand_id"])
        if b is None:
            fail("ERR_NOT_FOUND", f"brand {t['brand_id']} not found")
        brands.append(b)
    # step 11: at most one TERMS_PROPOSED negotiation per (retailer, period)
    for n in storage.negotiations.values():
        if (n["retailer_id"] == retailer_id and n["period_code"] == period_code
                and n["negotiation_status"] == "TERMS_PROPOSED"):
            fail("ERR_NEGOTIATION_ALREADY_OPEN",
                 "retailer already has a TERMS_PROPOSED negotiation for this period_code")
    # step 13: composition — 2..5 entries, distinct brand ids, all ACTIVE
    if len(brand_terms) < 2 or len(brand_terms) > 5:
        fail("ERR_NOT_COMBINED", "brand_terms must hold between 2 and 5 entries")
    ids = [t["brand_id"] for t in brand_terms]
    if len(set(ids)) != len(ids):
        fail("ERR_NOT_COMBINED", "brand_terms brand ids must be distinct")
    for b in brands:
        if b["brand_status"] != "ACTIVE":
            fail("ERR_BRAND_NOT_NEGOTIABLE",
                 f"brand {b['id']} is not ACTIVE (channel-conflict guard)")
    # step 17: closed-interval window overlap with the same retailer's
    # TERMS_PROPOSED/ACCEPTED negotiations (shared boundary day IS overlap)
    for n in storage.negotiations.values():
        if (n["retailer_id"] == retailer_id
                and n["negotiation_status"] in ACTIVE_NEGOTIATION_STATES
                and effective_from <= n["effective_to"]
                and effective_to >= n["effective_from"]):
            fail("ERR_NEGOTIATION_WINDOW_OVERLAP",
                 "effective window overlaps another open/accepted negotiation "
                 "of the same retailer")
    total_base, total_prop, reduction = negotiation_totals(brand_terms)
    rec = new_record()
    rec.update({
        "retailer_id": retailer_id,
        "period_code": period_code,
        "brand_terms": brand_terms,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "total_baseline_facings": total_base,
        "total_proposed_facings": total_prop,
        "shelf_reduction_pct": reduction,
        "negotiation_status": "TERMS_PROPOSED",
        "expires_at": negotiation_expiry_for(rec["created_at"]),
    })
    storage.negotiations[rec["id"]] = rec
    return success(negotiation_out(rec), status=201)


@bp.get("/combined-negotiations")
@synchronized
def list_negotiations():
    guard(ALL_ROLES)
    records = list(storage.negotiations.values())
    for param in ("retailer_id", "negotiation_status"):
        value = request.args.get(param)
        if value is not None:
            records = [n for n in records if n[param] == value]
    page, meta = paginate(sorted_by_created(records))
    return success([negotiation_out(n) for n in page], response_type="array",
                   pagination=meta)


@bp.get("/combined-negotiations/<nid>")
@synchronized
def get_negotiation(nid):
    guard(ALL_ROLES)
    n = storage.negotiations.get(nid)
    if n is None:
        fail("ERR_NOT_FOUND", f"combined negotiation {nid} not found")
    return success(negotiation_out(n))


@bp.post("/combined-negotiations/<nid>/respond")
@synchronized
def respond_negotiation(nid):
    user_id = guard(["RetailerBuyer"])
    body = body_json(required=True)
    response = f_enum(body, "response", ("ACCEPT", "REJECT"))
    # step 5: path id resolves
    n = storage.negotiations.get(nid)
    if n is None:
        fail("ERR_NOT_FOUND", f"combined negotiation {nid} not found")
    # step 7: respond requires TERMS_PROPOSED
    if n["negotiation_status"] != "TERMS_PROPOSED":
        fail("ERR_INVALID_STATE", "respond requires negotiation TERMS_PROPOSED")
    # step 9: the single buyer — X-User-ID must equal retailer_id
    if user_id != n["retailer_id"]:
        fail("ERR_OWNERSHIP_MISMATCH",
             "respondent's X-User-ID must equal the negotiation's retailer_id")
    # step 18: TTL — a clock strictly later than expires_at auto-expires the
    # negotiation (version still increments) and the call fails.
    if clock.now() > n["expires_at"]:
        n["negotiation_status"] = "EXPIRED"
        bump(n)
        fail("ERR_NEGOTIATION_EXPIRED",
             "logical clock is strictly later than expires_at")
    n["negotiation_status"] = "ACCEPTED" if response == "ACCEPT" else "REJECTED"
    bump(n)
    return success(negotiation_out(n))
