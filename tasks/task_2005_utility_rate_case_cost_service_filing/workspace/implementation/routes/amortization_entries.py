"""AmortizationEntry endpoints (PRD 3.6): strict in-order posting, LIFO reversal."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_INVALID_AMORT_ENTRY_STATE,
    ERR_INVALID_ASSET_STATE,
    ERR_AMORTIZATION_OUT_OF_ORDER,
    ERR_REVERSAL_NOT_LATEST,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, query_arg
from services.core import public, touch
from util import CLOCK
from validate import get_body, no_unknown_fields, require_path_resource

bp = Blueprint("amortization_entries", __name__)


@bp.get("/amortization-entries")
def list_amort_entries():
    filters = {
        "regulatory_asset_id": query_arg("regulatory_asset_id"),
        "rate_case_id": query_arg("rate_case_id"),
        "status": query_arg("status"),
    }
    # Pinned tie-break for cascade-minted rows: period_index ASC
    return list_response(
        "amortization_entries", filters,
        sort_key=lambda r: (r["created_at"], r["period_index"], r["_seq"]),
    )


@bp.get("/amortization-entries/<entry_id>")
def get_amort_entry(entry_id):
    return get_one("amortization_entries", entry_id)


def _asset_of(entry):
    return db["regulatory_assets"].get(entry["regulatory_asset_id"])


@bp.post("/amortization-entries/<entry_id>/post")
def post_entry(entry_id):
    body = get_body()
    no_unknown_fields(body, set())
    authorized(["UtilityFiler"])
    entry = require_path_resource("amortization_entries", entry_id)
    if entry["status"] != "PENDING":
        raise_error(ERR_INVALID_AMORT_ENTRY_STATE, "post requires PENDING")
    asset = _asset_of(entry)
    if asset is None or asset["status"] != "AMORTIZING":
        raise_error(ERR_INVALID_ASSET_STATE, "owning asset must be AMORTIZING")
    pending_min = min(
        (e["period_index"] for e in db["amortization_entries"].values()
         if e["regulatory_asset_id"] == asset["id"] and e["status"] == "PENDING"),
        default=None,
    )
    if pending_min is None or entry["period_index"] != pending_min:
        raise_error(ERR_AMORTIZATION_OUT_OF_ORDER,
                    "the earliest PENDING installment must post first")
    entry["status"] = "POSTED"
    entry["posted_at"] = CLOCK.now_iso()
    touch(entry)
    asset["amortized_to_date_cents"] += entry["amount_cents"]
    remaining = any(
        e["regulatory_asset_id"] == asset["id"] and e["status"] == "PENDING"
        for e in db["amortization_entries"].values()
    )
    if not remaining:
        asset["status"] = "FULLY_AMORTIZED"
    touch(asset)
    return success_object(public(entry))


@bp.post("/amortization-entries/<entry_id>/reverse")
def reverse_entry(entry_id):
    body = get_body()
    no_unknown_fields(body, set())
    authorized(["UtilityFiler"])
    entry = require_path_resource("amortization_entries", entry_id)
    if entry["status"] != "POSTED":
        raise_error(ERR_INVALID_AMORT_ENTRY_STATE, "reverse requires POSTED")
    asset = _asset_of(entry)
    if asset is None or asset["status"] not in ("AMORTIZING", "FULLY_AMORTIZED"):
        raise_error(ERR_INVALID_ASSET_STATE,
                    "owning asset must be AMORTIZING or FULLY_AMORTIZED")
    posted_max = max(
        (e["period_index"] for e in db["amortization_entries"].values()
         if e["regulatory_asset_id"] == asset["id"] and e["status"] == "POSTED"),
        default=None,
    )
    if posted_max is None or entry["period_index"] != posted_max:
        raise_error(ERR_REVERSAL_NOT_LATEST,
                    "only the latest POSTED installment may be reversed (LIFO)")
    was_full = asset["status"] == "FULLY_AMORTIZED"
    entry["status"] = "REVERSED"
    touch(entry)
    asset["amortized_to_date_cents"] -= entry["amount_cents"]
    if was_full:
        asset["status"] = "AMORTIZING"
    touch(asset)
    return success_object(public(entry))
