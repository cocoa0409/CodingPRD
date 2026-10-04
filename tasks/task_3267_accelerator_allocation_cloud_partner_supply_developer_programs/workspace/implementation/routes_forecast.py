"""Demand forecasts: acknowledgement, commit, cancellation and revision."""

import calc
import constants as K
from auth import roles
from error import (
    CatalogError,
    ERR_FORECAST_DEADLINE_PASSED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NO_OPEN_EPOCH,
    ERR_PARTNER_NOT_FOUND,
    ERR_QUALIFICATION_NOT_MET,
    ERR_STALE_PARTNER_VERSION,
)
from envelope import created, ok, page
from rules import resolve, resource_or_404
from services import serialize
from store import DB
from util import by_created, optional, paginate, parse_utc, require, require_enum

GROUP = "forecast"


def _caller_partner(caller):
    partner = resolve("partners", caller.user_id)
    if partner is None:
        raise CatalogError(ERR_PARTNER_NOT_FOUND, "X-User-ID does not name a partner account.")
    return partner


def _create(caller):
    from flask import request
    body = request.raw_payload or {}
    partner = _caller_partner(caller)
    quantity = require(body, "requested_quantity_units", "int", positive=True)
    expected = body.get("expected_partner_version")
    if expected is None:
        raise CatalogError(ERR_INVALID_REQUEST, "'expected_partner_version' is required.")
    if int(expected) != int(partner.get("version", 1)):
        raise CatalogError(ERR_STALE_PARTNER_VERSION)
    product = resolve("products", require(body, "product_sku_id"))
    if product is None:
        raise CatalogError(ERR_INVALID_REQUEST, "'product_sku_id' does not resolve.")
    forecast = DB.mint({
        "partner_id": partner["id"],
        "product_sku_id": product["id"],
        "requested_quantity_units": quantity,
        "acknowledged_at": None,
        "horizon_band": None,
        "committed_quantity_units": 0,
        "cancellation_notice_days": None,
        "forfeit_rate": 0.0,
        "tracking_status": "DRAFT",
        "expected_partner_version": expected,
    })
    DB.forecasts[forecast["id"]] = forecast
    DB.bump(partner)
    return created(serialize(forecast))


def _list(caller):
    from flask import request
    rows = by_created(list(DB.forecasts.values()))
    for field in ("partner_id", "product_sku_id"):
        value = request.args.get(field)
        if value:
            rows = [row for row in rows if row.get(field) == value]
    window, meta = paginate([serialize(row) for row in rows], request.args)
    return page(window, meta)


def _read(caller, forecast_id):
    return ok(serialize(resource_or_404("forecasts", forecast_id, "demand forecast")))


def _acknowledge(caller, forecast_id):
    forecast = resource_or_404("forecasts", forecast_id, "demand forecast")
    if forecast.get("tracking_status") != "DRAFT":
        raise CatalogError(ERR_INVALID_STATE, "Only a DRAFT forecast may be acknowledged.")
    if int(forecast.get("requested_quantity_units", 0)) <= 0:
        raise CatalogError(ERR_INVALID_REQUEST, "requested_quantity_units must be positive.")
    partner = DB.partners.get(forecast.get("partner_id"))
    if partner is None:
        raise CatalogError(ERR_PARTNER_NOT_FOUND)
    if partner.get("qualification_status") != "QUALIFIED":
        raise CatalogError(ERR_QUALIFICATION_NOT_MET)

    forecast["acknowledged_at"] = DB.now_text()
    band, deadline = calc.forecast_commitment_deadline(forecast["acknowledged_at"])
    forecast["horizon_band"] = band
    forecast["tracking_status"] = "FORECAST_SUBMITTED"
    DB.touch(forecast)
    partner["eligibility_deadline_at"] = deadline
    DB.touch(partner)
    return ok(serialize(forecast))


def _commit(caller, forecast_id):
    from flask import request
    body = request.raw_payload or {}
    forecast = resource_or_404("forecasts", forecast_id, "demand forecast")
    if forecast.get("tracking_status") != "FORECAST_SUBMITTED":
        raise CatalogError(ERR_INVALID_STATE, "Only a FORECAST_SUBMITTED forecast may be committed.")
    if DB.open_epoch() is None:
        raise CatalogError(ERR_NO_OPEN_EPOCH)

    partner = DB.partners.get(forecast.get("partner_id"))
    if partner is None:
        raise CatalogError(ERR_PARTNER_NOT_FOUND)
    deadline = partner.get("eligibility_deadline_at")
    if deadline and DB.clock >= parse_utc(deadline):
        raise CatalogError(ERR_FORECAST_DEADLINE_PASSED)

    committed = require(body, "committed_quantity_units", "int")
    requested = int(forecast.get("requested_quantity_units", 0))
    if committed > requested:
        raise CatalogError(ERR_INVALID_REQUEST, "committed_quantity_units exceeds the requested ceiling.")

    # The overage reads the partner's committed volume BEFORE this commit.
    snapshot = int(partner.get("committed_volume_units", 0) or 0)
    rate = calc.forecast_forfeit_rate(forecast.get("horizon_band"), snapshot, requested)
    band = forecast.get("horizon_band") or "SHORT"

    forecast["committed_quantity_units"] = committed
    forecast["cancellation_notice_days"] = K.NOTICE_DAYS[band]
    forecast["forfeit_rate"] = rate
    forecast["tracking_status"] = "ACTIVE"
    DB.touch(forecast)

    partner["committed_volume_units"] = snapshot + committed
    partner["cancellation_forfeit_rate"] = rate
    DB.touch(partner)
    return ok(serialize(forecast))


def _cancel(caller, forecast_id):
    from flask import request
    body = request.raw_payload if isinstance(request.raw_payload, dict) else {}
    forecast = resource_or_404("forecasts", forecast_id, "demand forecast")
    if forecast.get("tracking_status") != "ACTIVE":
        raise CatalogError(ERR_INVALID_STATE, "Only an ACTIVE forecast may be cancelled.")
    for hold in DB.holds.values():
        if hold.get("forecast_id") != forecast["id"]:
            continue
        if hold.get("state") not in ("CANCELLED", "RECLAIMED", "EXPIRED"):
            raise CatalogError(ERR_INVALID_STATE, "Every referencing hold must be in a terminal state.")

    forecast["tracking_status"] = "CANCELLED"
    DB.touch(forecast)
    partner = DB.partners.get(forecast.get("partner_id"))
    if partner is not None:
        partner["committed_volume_units"] = max(
            0, int(partner.get("committed_volume_units", 0)) - int(forecast.get("committed_quantity_units", 0))
        )
        DB.touch(partner)

    actor = body.get("as_user_id")
    if actor:
        from routes_holds import _audit_as
        _audit_as(forecast.get("partner_id"), "FORECAST_CANCELLED", "DemandForecast", forecast["id"], actor, caller.role)
    else:
        from services import append_audit
        append_audit(forecast.get("partner_id"), "FORECAST_CANCELLED", "DemandForecast", forecast["id"], caller)
    return ok(serialize(forecast))


def _revise(caller, forecast_id):
    forecast = resource_or_404("forecasts", forecast_id, "demand forecast")
    if forecast.get("tracking_status") != "CANCELLED":
        raise CatalogError(ERR_INVALID_STATE, "Only a CANCELLED forecast may be revised.")
    partner = DB.partners.get(forecast.get("partner_id"))
    if partner is None:
        raise CatalogError(ERR_PARTNER_NOT_FOUND)
    if partner.get("qualification_status") != "QUALIFIED":
        raise CatalogError(ERR_QUALIFICATION_NOT_MET)

    forecast["acknowledged_at"] = DB.now_text()
    band, deadline = calc.forecast_commitment_deadline(forecast["acknowledged_at"])
    forecast["horizon_band"] = band
    forecast["tracking_status"] = "FORECAST_SUBMITTED"
    DB.touch(forecast)
    partner["eligibility_deadline_at"] = deadline
    DB.touch(partner)
    return ok(serialize(forecast))


ROUTES = [
    ("POST", "/accelerators/demand-forecasts", _create, ("PartnerOps",)),
    ("GET", "/accelerators/demand-forecasts", _list, ("PartnerOps",)),
    ("GET", "/accelerators/demand-forecasts/<forecast_id>", _read, ("PartnerOps",)),
    ("POST", "/accelerators/demand-forecasts/<forecast_id>/acknowledge", _acknowledge, ("PartnerProgramManager",)),
    ("POST", "/accelerators/demand-forecasts/<forecast_id>/commit", _commit, ("PartnerOps",)),
    ("POST", "/accelerators/demand-forecasts/<forecast_id>/cancel", _cancel, ("PartnerOps",)),
    ("POST", "/accelerators/demand-forecasts/<forecast_id>/revise", _revise, ("PartnerOps",)),
]


def register(app):
    for method, path, handler, allowed in ROUTES:
        endpoint = "%s_%s" % (GROUP, path.replace("/", "_").replace("<", "").replace(">", ""))
        app.add_url_rule(path, endpoint + method, roles(*allowed)(handler), methods=[method])