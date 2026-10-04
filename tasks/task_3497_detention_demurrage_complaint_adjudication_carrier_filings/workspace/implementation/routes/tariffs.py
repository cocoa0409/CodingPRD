"""TariffPublication: filing (OCC-guarded on the carrier), listing, publish
(PRD §3.2)."""
from datetime import timedelta

from flask import Blueprint

import store
from auth import require_roles, any_role
from clock import CLOCK
from envelope import ok_object, ok_list, paginate
from errors import (
    fail,
    ERR_CARRIER_NOT_FOUND,
    ERR_TARIFF_NOT_FOUND,
    ERR_FORBIDDEN_RESOURCE_ACCESS,
    ERR_CARRIER_NOT_ACTIVE,
    ERR_TARIFF_NOT_IN_DRAFT,
    ERR_PUBLISH_WINDOW_NOT_REACHED,
    ERR_EFFECTIVE_DATE_NOTICE_SHORT,
    ERR_STALE_VERSION,
)
from serialization import ser_tariff
from store import touch
from util import body, req_str, req_int, req_enum, req_dt
from constants import NOTICE_PERIOD_INCREASE_DAYS, NOTICE_PERIOD_OTHER_DAYS

bp = Blueprint("tariffs", __name__)

CHARGE_SCOPES = ("DETENTION", "DEMURRAGE", "GENERAL")
ACCRUAL_METHODS = ("CALENDAR", "WORKING_DAY")
CHANGE_TYPES = ("NEW", "INCREASE", "DECREASE")


@bp.post("/fmc/carriers/<carrierId>/tariff-publications")
def file_tariff(carrierId):
    uid, _role = require_roles("CarrierRep")
    carrier = store.carriers.get(carrierId)
    if carrier is None:
        fail(ERR_CARRIER_NOT_FOUND, "carrier organization not found: %s" % carrierId)
    if uid != carrierId:
        fail(ERR_FORBIDDEN_RESOURCE_ACCESS,
             "a CarrierRep may file tariffs only for its own organization")
    b = body()
    tariff_code = req_str(b, "tariff_code")
    charge_scope = req_enum(b, "charge_scope", CHARGE_SCOPES)
    free_time_days = req_int(b, "free_time_days", lo=0)
    per_diem_rate_cents = req_int(b, "per_diem_rate_cents", lo=1)
    accrual_method = req_enum(b, "accrual_method", ACCRUAL_METHODS)
    change_type = req_enum(b, "change_type", CHANGE_TYPES)
    effective_date = req_dt(b, "effective_date")
    expected_carrier_version = req_int(b, "expected_carrier_version")

    notice_period_days = (
        NOTICE_PERIOD_INCREASE_DAYS if change_type == "INCREASE"
        else NOTICE_PERIOD_OTHER_DAYS
    )
    now = CLOCK.now()
    if effective_date < now + timedelta(days=notice_period_days):
        fail(ERR_EFFECTIVE_DATE_NOTICE_SHORT,
             "effective_date is earlier than filed_at + notice_period_days")
    # OCC is deliberately the last check (rung 16).
    if expected_carrier_version != carrier["version"]:
        fail(ERR_STALE_VERSION,
             "expected_carrier_version does not match the carrier's current version")

    rec = store.base_record()
    rec.update(
        carrier_id=carrierId,
        tariff_code=tariff_code,
        charge_scope=charge_scope,
        free_time_days=free_time_days,
        per_diem_rate_cents=per_diem_rate_cents,
        accrual_method=accrual_method,
        change_type=change_type,
        notice_period_days=notice_period_days,
        effective_date=effective_date,
        filed_at=now,
        publication_status="DRAFT",
    )
    store.tariffs[rec["id"]] = rec
    touch(carrier)  # the OCC write advances the carrier's version
    return ok_object(ser_tariff(rec), 201)


@bp.get("/fmc/carriers/<carrierId>/tariff-publications")
def list_tariffs(carrierId):
    any_role()
    if carrierId not in store.carriers:
        fail(ERR_CARRIER_NOT_FOUND, "carrier organization not found: %s" % carrierId)
    recs = [t for t in store.tariffs.values() if t["carrier_id"] == carrierId]
    page, limit, offset, total = paginate(recs)
    return ok_list([ser_tariff(t) for t in page], limit, offset, total)


@bp.post("/fmc/tariff-publications/<tariffId>/publish")
def publish_tariff(tariffId):
    uid, _role = require_roles("CarrierRep")
    t = store.tariffs.get(tariffId)
    if t is None:
        fail(ERR_TARIFF_NOT_FOUND, "tariff publication not found: %s" % tariffId)
    if uid != t["carrier_id"]:
        fail(ERR_FORBIDDEN_RESOURCE_ACCESS,
             "a CarrierRep may publish only its own organization's tariffs")
    carrier = store.carriers.get(t["carrier_id"])
    if carrier is None:
        fail(ERR_CARRIER_NOT_FOUND, "carrier organization not found: %s" % t["carrier_id"])
    # Ladder order: carrier standing, then tariff state, then the window.
    if carrier["status"] != "ACTIVE":
        fail(ERR_CARRIER_NOT_ACTIVE, "carrier is not ACTIVE")
    if t["publication_status"] != "DRAFT":
        fail(ERR_TARIFF_NOT_IN_DRAFT, "publish requires the tariff to be DRAFT")
    if CLOCK.now() < t["effective_date"]:
        fail(ERR_PUBLISH_WINDOW_NOT_REACHED,
             "the tariff's effective_date has not been reached")
    t["publication_status"] = "PUBLISHED"
    touch(t)
    return ok_object(ser_tariff(t))
