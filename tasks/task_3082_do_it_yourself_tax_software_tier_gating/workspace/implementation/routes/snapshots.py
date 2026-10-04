"""PriorYearReturnSnapshot endpoints: register, list, fetch, import."""
from flask import Blueprint

from core import (
    ApiError,
    CARRYFORWARD_ITEM_TYPES,
    check_ownership,
    db,
    endpoint,
    expected_version,
    f_int,
    f_str,
    body,
    bad_request,
    dump,
    new_row,
    paginate,
    respond_object,
    sort_created,
    touch,
)
import svc

bp = Blueprint("snapshots", __name__)


def _validate_carryforward(items):
    if not isinstance(items, list):
        bad_request("Field 'carryforward_items' must be an array.")
    cleaned = []
    for entry in items:
        if not isinstance(entry, dict):
            bad_request("Each carryforward item must be an object.")
        item_type = entry.get("item_type")
        if item_type not in CARRYFORWARD_ITEM_TYPES:
            bad_request("carryforward item_type must be one of %s." % ", ".join(CARRYFORWARD_ITEM_TYPES))
        asset_tag = entry.get("asset_tag")
        if not isinstance(asset_tag, str) or not asset_tag.strip():
            bad_request("carryforward asset_tag must be a non-empty string.")
        amount = entry.get("remaining_amount_cents")
        if isinstance(amount, bool) or not isinstance(amount, int):
            bad_request("carryforward remaining_amount_cents must be an integer.")
        cleaned.append(
            {
                "item_type": item_type,
                "asset_tag": asset_tag,
                "remaining_amount_cents": amount,
            }
        )
    return cleaned


@bp.post("/tax/accounts/<account_id>/prior-year-snapshots")
@endpoint("Taxpayer")
def create_snapshot(account_id):
    acct = svc.get_account(account_id)
    check_ownership(acct)
    payload = body()
    tax_year = f_int(payload, "tax_year")
    items = _validate_carryforward(payload.get("carryforward_items", []))
    # Supersede any existing AVAILABLE or IMPORTED snapshot for the same pair.
    for snap in db.snapshots.values():
        if (
            snap["account_id"] == acct["id"]
            and snap["tax_year"] == tax_year
            and snap["import_status"] in ("AVAILABLE", "IMPORTED")
        ):
            snap["import_status"] = "SUPERSEDED"
            touch(snap)
    snap = new_row(
        "snapshot",
        account_id=acct["id"],
        tax_year=tax_year,
        carryforward_items=items,
        import_status="AVAILABLE",
    )
    db.snapshots[snap["id"]] = snap
    return respond_object(dump(snap), status=201)


@bp.get("/tax/accounts/<account_id>/prior-year-snapshots")
@endpoint("Taxpayer")
def list_snapshots(account_id):
    acct = svc.get_account(account_id)
    check_ownership(acct)
    rows = [s for s in db.snapshots.values() if s["account_id"] == acct["id"]]
    return paginate(rows)


@bp.get("/tax/accounts/<account_id>/prior-year-snapshots/<snapshot_id>")
@endpoint("Taxpayer")
def get_snapshot(account_id, snapshot_id):
    acct = svc.get_account(account_id)
    check_ownership(acct)
    snap = svc.get_snapshot_on_account(acct, snapshot_id)
    return respond_object(dump(snap))


@bp.post("/tax/accounts/<account_id>/prior-year-snapshots/<snapshot_id>/import")
@endpoint("Taxpayer")
def import_snapshot(account_id, snapshot_id):
    acct = svc.get_account(account_id)
    check_ownership(acct)
    snap = svc.get_snapshot_on_account(acct, snapshot_id)
    payload = body()
    return_id = f_str(payload, "return_id")
    ret = db.returns.get(return_id)
    if ret is None or ret["account_id"] != acct["id"]:
        raise ApiError("ERR_RETURN_NOT_FOUND", "return_id does not exist.")
    svc.require_account_active(acct)
    svc.require_return_editable(ret)
    expected_version(payload, ret)
    if snap["import_status"] == "SUPERSEDED":
        raise ApiError("ERR_SNAPSHOT_SUPERSEDED", "Snapshot has been superseded.")
    if snap["import_status"] == "IMPORTED":
        raise ApiError("ERR_INVALID_STATE", "Snapshot has already been imported.")
    if snap["tax_year"] >= ret["tax_year"]:
        raise ApiError("ERR_SNAPSHOT_YEAR_INVALID", "snapshot.tax_year >= return.tax_year on import.")
    svc.import_snapshot(snap, ret, acct)
    return respond_object(dump(ret))
