"""Account registration, reads, ledger and billing surfaces."""
import re
from decimal import Decimal

from flask import Blueprint, g, request

from db import db, find
from auth import authorize
from errors import err
from response import success, paged, sort_by_created
from serializers import account as ser_account, ledger as ser_ledger
from services import engine
from routes.common import body, required, opt_enum, req_str
from response import pagination
from util import now, r6, r2, out_num, parse_iso, new_id


bp = Blueprint("accounts", __name__)

LOCATOR_RE = re.compile(r"^[a-z0-9]{2}[0-9]{4}$")


@bp.route("/v1/accounts", methods=["POST"])
def create_account():
    authorize(g.role, ["PlatformOperator"])
    data = body()
    org_name = req_str(data, "org_name")
    locator = req_str(data, "account_locator")
    cloud = required(data, "cloud_provider")
    region = required(data, "region")
    if not isinstance(cloud, str) or not isinstance(region, str):
        raise err("ERR_INVALID_REQUEST", "cloud_provider and region must be strings.")
    if cloud not in engine.CLOUDS or region not in engine.REGIONS:
        raise err("ERR_INVALID_REQUEST", "Unknown cloud_provider or region.")
    if not LOCATOR_RE.match(locator):
        raise err("ERR_INVALID_REQUEST", "account_locator must match ^[a-z0-9]{2}[0-9]{4}$.")
    scope = opt_enum(data, "monitor_scope", ("ACCOUNT_ONLY", "INCLUDE_CONSUMERS"),
                     "ACCOUNT_ONLY")
    for existing in db.accounts:
        if existing["account_locator"] == locator:
            raise err("ERR_DUPLICATE_RESOURCE", "account_locator must be globally unique.")
    ts = now()
    record = {
        "id": new_id(),
        "org_name": org_name,
        "account_locator": locator,
        "region": region,
        "region_factor": engine.REGION_FACTOR[region],
        "cloud_provider": cloud,
        "monitor_scope": scope,
        "posted_consumption_credits_reconciled": r6(0),
        "posted_storage_dollars_reconciled": r2(0),
        "account_state": "OPEN",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.accounts.append(record)
    return success(ser_account(record), 201)


@bp.route("/v1/accounts", methods=["GET"])
def list_accounts():
    authorize(g.role, ["PlatformOperator"])
    items = sort_by_created(db.accounts)
    region = request.args.get("region")
    cloud = request.args.get("cloud_provider")
    if region:
        items = [a for a in items if a["region"] == region]
    if cloud:
        items = [a for a in items if a["cloud_provider"] == cloud]
    limit, offset = pagination()
    return paged([ser_account(a) for a in items], limit, offset)


@bp.route("/v1/accounts/<account_id>", methods=["GET"])
def get_account(account_id):
    authorize(g.role, ["PlatformOperator", "FinanceController", "ShareAdmin", "DataEngineer"])
    record = find(db.accounts, account_id)
    if record is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "Account not found.")
    return success(ser_account(record))


@bp.route("/v1/accounts/<account_id>/ledger-entries", methods=["GET"])
def list_ledger(account_id):
    authorize(g.role, ["FinanceController", "PlatformOperator", "DataEngineer"])
    record = find(db.accounts, account_id)
    if record is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "Account not found.")
    rows = [r for r in db.ledger if r["account_id"] == account_id]
    bucket = request.args.get("bucket")
    source_entity = request.args.get("source_entity")
    if bucket:
        rows = [r for r in rows if r["bucket"] == bucket]
    if source_entity:
        rows = [r for r in rows if r["source_entity"] == source_entity]
    rows = sorted(rows, key=lambda r: (r["posted_at"], r["id"]))
    limit, offset = pagination()
    return paged([ser_ledger(r) for r in rows], limit, offset)


@bp.route("/v1/accounts/<account_id>/billing-summary", methods=["GET"])
def billing_summary(account_id):
    authorize(g.role, ["FinanceController", "PlatformOperator", "ShareAdmin"])
    record = find(db.accounts, account_id)
    if record is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "Account not found.")
    raw = request.args.get("as_of")
    instant = None
    if raw not in (None, ""):
        try:
            instant = parse_iso(raw, "as_of")
        except ValueError:
            raise err("ERR_INVALID_REQUEST", "as_of must be an ISO 8601 timestamp.")
    if instant is None:
        credits = engine.ledger_sum_credits(account_id)
        storage = engine.ledger_sum_storage_dollars(account_id)
        dollars = engine.ledger_sum_dollars(account_id)
        bucket_totals = engine.ledger_bucket_totals(account_id)
    else:
        credits = r6(sum((r["amount_credits"] for r in engine.ledger_rows(account_id, engine.CREDIT_BUCKETS)
                          if r["posted_at"] <= instant), Decimal("0")))
        storage = r2(sum((r["amount_usd"] for r in engine.ledger_rows(account_id, engine.STORAGE_BUCKETS)
                          if r["posted_at"] <= instant), Decimal("0")))
        dollars = r2(sum((r["amount_usd"] for r in engine.ledger_rows(account_id, engine.DOLLAR_BUCKETS)
                          if r["posted_at"] <= instant), Decimal("0")))
        bucket_totals = {}
        for bucket_name in engine.ALL_BUCKETS:
            sel = [r for r in db.ledger
                   if r["account_id"] == account_id and r["bucket"] == bucket_name
                   and r["posted_at"] <= instant]
            bucket_totals[bucket_name] = {
                "amount_credits": out_num(r6(sum((r["amount_credits"] for r in sel), Decimal("0")))),
                "amount_usd": out_num(r2(sum((r["amount_usd"] for r in sel), Decimal("0")))),
            }
    payload = {
        "posted_consumption_credits_reconciled": out_num(credits),
        "posted_storage_dollars_reconciled": out_num(storage),
        "account_dollars_balance": out_num(dollars),
        "bucket_totals": bucket_totals,
    }
    return success(payload)
