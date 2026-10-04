"""Appraisal documents and scheduled personal property (PRD §3.2)."""

import calc
import db
import reqs
from clock import add_months, first_of_next_month, fmt_dt, months_between, parse_dt
from errors import err
from middleware import authorize
from response import array, ok, paginate
from serialize import render, render_list
from services import core

from flask import Blueprint

bp = Blueprint("scheduled", __name__)

ITEM_CLASSES = ("JEWELRY", "FINE_ART", "COLLECTION", "WINE", "DWELLING")
ITEM_TYPES = ("JEWELRY", "FINE_ART", "COLLECTION", "WINE")
DOC_READERS = ("Underwriter", "AgencyProducer", "ClaimsAdjuster", "PlatformAdmin",
               "ComplianceReporter", "RiskConsultant")
SCHEDULED_READERS = ("Underwriter", "AgencyProducer", "ClaimsAdjuster", "PlatformAdmin",
                     "ComplianceReporter", "RiskConsultant")

SCHEDULED_VALUE_CAP_PCT = 0.60


def common_fields():
    now = fmt_dt(db.now())
    return {"id": db.new_id(), "created_at": now, "updated_at": now, "version": 1}


def _doc_fields(property_id, doc):
    now = db.now()
    months = months_between(doc["appraisal_date"], now)
    doc["currency_months"] = months
    doc["currency_status"] = calc.currency_status(months)
    doc["expires_on"] = fmt_dt(first_of_next_month(add_months(doc["appraisal_date"], 24)))


def _recompute_docs(property_id):
    for doc in db.APPRAISAL_DOCUMENTS.values():
        if doc["property_id"] == property_id:
            _doc_fields(property_id, doc)


# --------------------------------------------------------------------------
# appraisal documents
# --------------------------------------------------------------------------
@bp.route("/hnw/properties/<property_id>/appraisal-documents", methods=["POST"])
def create_document(property_id):
    authorize(("Underwriter",))
    prop = core.get(db.PROPERTIES, property_id, "Property")
    data = reqs.body()
    record = {
        "id": db.new_id(),
        "created_at": fmt_dt(db.now()),
        "property_id": prop["id"],
        "item_class": reqs.enum(data, "item_class", ITEM_CLASSES),
        "appraiser_name": reqs.string(data, "appraiser_name", required=True),
        "appraisal_date": parse_dt(reqs.require(data, "appraisal_date")),
        "appraised_value_cents": reqs.integer(data, "appraised_value_cents", required=True,
                                              minimum=0, strict_min=True),
    }
    if record["appraisal_date"] is None:
        raise err("ERR_INVALID_REQUEST", "appraisal_date must be an ISO 8601 instant.")
    _doc_fields(property_id, record)
    db.APPRAISAL_DOCUMENTS[record["id"]] = record
    return ok(render(record), status=201)


@bp.route("/hnw/properties/<property_id>/appraisal-documents", methods=["GET"])
def list_documents(property_id):
    authorize(DOC_READERS)
    core.get(db.PROPERTIES, property_id, "Property")
    limit, offset = reqs.pagination()
    rows = [d for d in db.APPRAISAL_DOCUMENTS.values() if d["property_id"] == property_id]
    item_class = reqs.query("item_class")
    currency = reqs.query("currency_status")
    if item_class:
        rows = [d for d in rows if d["item_class"] == item_class]
    if currency:
        rows = [d for d in rows if d["currency_status"] == currency]
    rows = reqs.sorted_by_created(rows)
    page, meta = paginate(rows, limit, offset)
    return array(render_list(page), meta)


@bp.route("/hnw/appraisal-documents/<doc_id>", methods=["GET"])
def read_document(doc_id):
    authorize(DOC_READERS)
    doc = core.get(db.APPRAISAL_DOCUMENTS, doc_id, "AppraisalDocument")
    return ok(render(doc))


@bp.route("/hnw/appraisal-documents/<doc_id>/scheduled-items", methods=["GET"])
def list_document_items(doc_id):
    authorize(DOC_READERS)
    core.get(db.APPRAISAL_DOCUMENTS, doc_id, "AppraisalDocument")
    limit, offset = reqs.pagination()
    rows = [s for s in db.SCHEDULED_ITEMS.values() if s["appraisal_doc_id"] == doc_id]
    status = reqs.query("status")
    if status:
        rows = [s for s in rows if s["status"] == status]
    rows = reqs.sorted_by_created(rows)
    page, meta = paginate(rows, limit, offset)
    return array(render_list(page), meta)


# --------------------------------------------------------------------------
# scheduled items
# --------------------------------------------------------------------------
@bp.route("/hnw/properties/<property_id>/scheduled-items", methods=["POST"])
def create_item(property_id):
    authorize(("AgencyProducer", "Underwriter"))
    prop = core.get(db.PROPERTIES, property_id, "Property")
    data = reqs.body()
    doc_id = reqs.string(data, "appraisal_doc_id", required=True)
    core.get(db.APPRAISAL_DOCUMENTS, doc_id, "AppraisalDocument")
    record = common_fields()
    record.update({
        "property_id": prop["id"],
        "item_type": reqs.enum(data, "item_type", ITEM_TYPES),
        "declared_value_cents": reqs.integer(data, "declared_value_cents", required=True,
                                             minimum=0, strict_min=True),
        "appraisal_doc_id": doc_id,
        "appraisal_currency_months": 0,
        "status": "PENDING",
        "attached_value_cents": 0,
    })
    db.SCHEDULED_ITEMS[record["id"]] = record
    _refresh_item(record)
    return ok(render(record), status=201)


@bp.route("/hnw/properties/<property_id>/scheduled-items", methods=["GET"])
def list_items(property_id):
    authorize(SCHEDULED_READERS)
    core.get(db.PROPERTIES, property_id, "Property")
    limit, offset = reqs.pagination()
    rows = [s for s in db.SCHEDULED_ITEMS.values() if s["property_id"] == property_id]
    status = reqs.query("status")
    item_type = reqs.query("item_type")
    if status:
        rows = [s for s in rows if s["status"] == status]
    if item_type:
        rows = [s for s in rows if s["item_type"] == item_type]
    rows = reqs.sorted_by_created(rows)
    page, meta = paginate(rows, limit, offset)
    return array(render_list(page), meta)


def resolve_for_property(property_id):
    """Collapse a property's duplicate items to one row per item_type.

    The row holding the greatest declared_value_cents survives; any duplicate is
    retired and stops contributing to both property aggregates.
    """
    by_type = {}
    for item in db.SCHEDULED_ITEMS.values():
        if item["property_id"] != property_id:
            continue
        current = by_type.get(item["item_type"])
        if current is None or item["declared_value_cents"] > current["declared_value_cents"]:
            by_type[item["item_type"]] = item
    for item in db.SCHEDULED_ITEMS.values():
        if item["property_id"] != property_id:
            continue
        if by_type.get(item["item_type"]) is not item and item["status"] == "PENDING":
            item["status"] = "REJECTED"
            core.touch(item)
            _refresh_item(item)


def _refresh_item(item):
    doc = db.APPRAISAL_DOCUMENTS.get(item["appraisal_doc_id"])
    item["appraisal_currency_months"] = (
        months_between(doc["appraisal_date"], db.now()) if doc else 0)
    item["attached_value_cents"] = (
        item["declared_value_cents"] if item["status"] in ("APPROVED", "ATTACHED") else 0)


@bp.route("/hnw/scheduled-items/<item_id>/approve", methods=["POST"])
def approve_item(item_id):
    authorize(("Underwriter",))
    item = core.get(db.SCHEDULED_ITEMS, item_id, "ScheduledItem")
    if item["status"] not in ("PENDING", "APPROVED"):
        raise err("ERR_INVALID_STATE",
                  "Only a PENDING scheduled item may be approved.")
    doc = db.APPRAISAL_DOCUMENTS.get(item["appraisal_doc_id"])
    if doc is None:
        raise err("ERR_APPRAISAL_DOC_MISMATCH",
                  "The substantiating AppraisalDocument does not exist.")
    # Priority 17: referential match (property + item class).
    if doc["property_id"] != item["property_id"] or doc["item_class"] != item["item_type"]:
        raise err("ERR_APPRAISAL_DOC_MISMATCH",
                  "The substantiating document belongs to another property or classes differ.")
    if doc["appraisal_date"] is None:
        raise err("ERR_APPRAISAL_DOC_MISMATCH", "The document carries no appraisal_date.")
    _doc_fields(item["property_id"], doc)
    # Priority 18: currency / value sufficiency.
    if doc["currency_status"] not in ("CURRENT", "AGING"):
        raise err("ERR_APPRAISAL_CURRENCY_EXPIRED",
                  "The substantiating document is EXPIRED.")
    if doc["appraised_value_cents"] < item["declared_value_cents"]:
        raise err("ERR_APPRAISAL_CURRENCY_EXPIRED",
                  "The document's appraised value is below the item's declared value.")
    _require_scheduled_cap(item)
    item["status"] = "APPROVED"
    core.touch(item)
    _refresh_item(item)
    core.recompute_property(item["property_id"])
    return ok(render(item))


def _require_scheduled_cap(item):
    """Priority 12: aggregate scheduled value must not exceed 60 percent.

    PRD 3.2: the sum of declared_value_cents across the property's items
    already in APPROVED or ATTACHED, counted together with the item under
    approval, must not exceed 60 percent of the property's
    total_insured_value_cents.  The comparison is made exactly at the cent
    (integer arithmetic, never a float), so an aggregate of 120000000 against
    a cap of 120000000 passes while 120000001 breaches.
    """
    property_id = item["property_id"]
    prop = db.PROPERTIES[property_id]
    aggregate = item["declared_value_cents"]
    for other in db.SCHEDULED_ITEMS.values():
        if other["property_id"] != property_id or other["id"] == item["id"]:
            continue
        if other["status"] in ("APPROVED", "ATTACHED"):
            aggregate += other["declared_value_cents"]
    # The cap is compared strictly: the aggregate must not exceed 60 percent of
    # the property's total insured value, evaluated at the cent.
    if aggregate * 100 > 60 * prop["total_insured_value_cents"]:
        raise err("ERR_SCHEDULED_VALUE_CAP",
                  "The aggregate scheduled value exceeds 60 percent of total insured value.")


@bp.route("/hnw/scheduled-items/<item_id>/reject", methods=["POST"])
def reject_item(item_id):
    authorize(("Underwriter",))
    item = core.get(db.SCHEDULED_ITEMS, item_id, "ScheduledItem")
    reqs.body()
    status = item["status"]
    if status == "PENDING":
        pass
    elif status == "APPROVED":
        _refresh_item(item)
        if item["appraisal_currency_months"] < 24:
            raise err("ERR_INVALID_STATE",
                      "An approved item may only be thrown back once it has reached 24 months.")
        item["status"] = "REJECTED"
        core.touch(item)
        _refresh_item(item)
        core.recompute_property(item["property_id"])
    else:
        raise err("ERR_INVALID_STATE",
                  "The scheduled item is not in a state from which this transition is declared.")
    core.recompute_property(item["property_id"])
    return ok(render(item))


@bp.route("/hnw/scheduled-items/<item_id>/refresh-appraisal", methods=["POST"])
def refresh_item(item_id):
    authorize(("AgencyProducer",))
    item = core.get(db.SCHEDULED_ITEMS, item_id, "ScheduledItem")
    if item["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE",
                  "Only an APPROVED item may be refreshed against a newer document.")
    _refresh_item(item)
    if item["appraisal_currency_months"] < 24:
        raise err("ERR_INVALID_STATE",
                  "The item has not yet reached 24 months of appraisal currency.")
    data = reqs.body()
    doc_id = reqs.string(data, "appraisal_doc_id", required=True)
    doc = core.get(db.APPRAISAL_DOCUMENTS, doc_id, "AppraisalDocument")
    if doc["property_id"] != item["property_id"] or doc["item_class"] != item["item_type"]:
        raise err("ERR_APPRAISAL_DOC_MISMATCH",
                  "The replacement document does not substantiate this item.")
    _doc_fields(item["property_id"], doc)
    if doc["currency_status"] not in ("CURRENT", "AGING"):
        raise err("ERR_APPRAISAL_CURRENCY_EXPIRED",
                  "The replacement document is not current or aging.")
    if doc["appraised_value_cents"] < item["declared_value_cents"]:
        raise err("ERR_APPRAISAL_CURRENCY_EXPIRED",
                  "The replacement document's value is below the item's declared value.")
    item["appraisal_doc_id"] = doc_id
    item["status"] = "PENDING"
    item["attached_value_cents"] = 0
    core.touch(item)
    _refresh_item(item)
    core.recompute_property(item["property_id"])
    return ok(render(item))


@bp.route("/hnw/scheduled-items/<item_id>/detach", methods=["POST"])
def detach_item(item_id):
    authorize(("Underwriter",))
    item = core.get(db.SCHEDULED_ITEMS, item_id, "ScheduledItem")
    if item["status"] != "ATTACHED":
        raise err("ERR_INVALID_STATE", "Only an ATTACHED item may be detached.")
    data = reqs.body()
    claim_id = data.get("claim_id")
    if claim_id is not None:
        claim = core.get(db.CLAIMS, claim_id, "Claim")
        if claim["status"] not in ("SETTLED", "PAID", "REJECTED"):
            raise err("ERR_INVALID_STATE",
                      "The claim that triggered the detach has not yet closed.")
    item["status"] = "APPROVED"
    core.touch(item)
    _refresh_item(item)
    item["attached_value_cents"] = item["declared_value_cents"]
    core.recompute_property(item["property_id"])
    return ok(render(item))