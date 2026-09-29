"""The logical clock utility (PRD 2.5) and the compliance sweep (PRD 3.8)."""
from flask import Blueprint

import auth
import derive
import envelope
import errors
import ser
import store
import valid
from store import db, touch

bp = Blueprint("clock", __name__)

ALL_ROLES = auth.ALL_ROLES


@bp.route("/_clock/set_current_utc", methods=["POST"])
@auth.require(*ALL_ROLES)
def set_current_utc():
    data = valid.body()
    moment, _raw = valid.req_dt(data, "current_utc")
    db.set_clock(moment)
    return envelope.empty()


def _expire_certificates(provider_id):
    now = db.now()
    for row in store.order_rows(derive.certificates_of(provider_id)):
        if row["status"] not in ("ACTIVE", "ISSUED"):
            continue
        if now > row["not_after"]:
            row["status"] = "EXPIRED"
            touch(row)


def _overdue_tracebacks(provider_id):
    now = db.now()
    rows = [r for r in db.tracebacks.values()
            if r["provider_id"] == provider_id]
    for row in store.order_rows(rows):
        if row["state"] != "RECEIVED":
            continue
        if now > row["response_deadline_at"]:
            row["state"] = "OVERDUE"
            touch(row)


def _expire_notices(provider_id):
    now = db.now()
    rows = [r for r in db.notices.values() if r["provider_id"] == provider_id]
    for row in store.order_rows(rows):
        if row["state"] not in ("NOTIFIED", "UNDER_INVESTIGATION"):
            continue
        if not now > row["mitigation_deadline_at"]:
            continue
        row["state"] = "EXPIRED_UNMITIGATED"
        row["penalty_points_assessed"] = derive.NOTICE_EXPIRY_POINTS
        touch(row)
        customer = db.customers.get(row.get("customer_id"))
        if customer is not None and customer["origination_state"] == "ENABLED":
            derive._mark_suspended(customer, "NOTICE_EXPIRY", row["id"])
            touch(customer)
            derive.cascade_suspend_assignments(customer)


@bp.route("/rmd/compliance-sweeps", methods=["POST"])
@auth.require(auth.REGULATOR)
def compliance_sweep():
    data = valid.body()
    provider_id = valid.req_str(data, "provider_id")
    provider = db.providers.get(provider_id)
    if provider is None:
        errors.fail(errors.ERR_PROVIDER_NOT_FOUND,
                    "No provider with id %s" % provider_id)

    _expire_certificates(provider_id)
    _overdue_tracebacks(provider_id)
    _expire_notices(provider_id)

    provider["sweep_index"] = provider["sweep_index"] + 1
    derive.recompute_provider(provider, force=True)
    return envelope.ok(ser.provider(provider))
