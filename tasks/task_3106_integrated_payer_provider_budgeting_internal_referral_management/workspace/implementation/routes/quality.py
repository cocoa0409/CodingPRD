"""QualityMetric endpoints (PRD 3.10)."""

from flask import Blueprint

from calculations import (
    component_score,
    mean_wait_days,
    region_quality_composite_score,
    weighted_component_score,
)
from constants import ROLE_QUALITY_REVIEW_BOARD
from db import STORE
from domain import (
    get_quality_metric,
    get_region,
    new_record,
    raise_alert,
    recompute_provider_panel,
    recompute_region_aggregates,
    require_body_reference,
    run_posture_ladder,
    store_row,
    touch,
)
from errors import (
    ERR_DUPLICATE_QUALITY_METRIC,
    ERR_INVALID_STATE,
    ERR_METRIC_NOT_FINALIZABLE,
    raise_error,
)
from projections import period_of
from rounding import dec, round_half_up_int
from routes._common import (
    QUALITY_READERS,
    arg,
    filter_rows,
    list_response,
    payload,
    principal,
    require_field,
    single_response,
)

bp = Blueprint("quality", __name__)


def _logged_internal_referral_pct(region_id, period):
    """PRD 3.10 / the internal_referral_rate rule:

        logged_internal_referral_pct = round_half_up(referred_inside_count /
                                                     total_authorized_count)

    Only referrals in {AUTHORIZED, SCHEDULED, COMPLETED} are counted; denied
    referrals are excluded from the denominator entirely. The ratio is rounded
    half-up to a whole number, so a ratio of exactly one half reads as 1.
    """
    authorized = 0
    referred_inside = 0
    for referral in STORE.referrals.values():
        if referral.get("status") not in ("AUTHORIZED", "SCHEDULED", "COMPLETED"):
            continue
        member = STORE.members.get(referral.get("member_id"))
        if member is None or member.get("region_id") != region_id:
            continue
        authorized += 1
        if referral.get("referral_type") == "INTERNAL":
            referred_inside += 1
    _ = period
    if authorized == 0:
        return 1.0
    return float(round_half_up_int(
        dec(referred_inside) / dec(authorized)))


def _measured_value(metric):
    region_id = metric["region_id"]
    code = metric.get("metric_code")
    period = metric.get("period")
    if code == "ACCESS_WAIT_DAYS":
        department_ids = {d["id"] for d in STORE.departments.values()
                          if d.get("region_id") == region_id}
        rows = [a for a in STORE.appointments.values()
                if a.get("department_id") in department_ids
                and a.get("fulfillment_status") != "CANCELLED"
                and (period is None or period_of(a.get("start_utc")) == period)]
        return mean_wait_days(rows)
    if code == "QUALITY_COMPOSITE":
        # PRD 2.2/PATCH /_outcome-targets: the test-driving capability writes a
        # metric's measured value directly. Because the board controls the
        # composite's measurement (an external survey / chart-audit number),
        # finalization preserves that supplied reading rather than replacing it
        # with a derived aggregate.
        supplied = metric.get("measured_value")
        if supplied not in (None, 0):
            return supplied
        return region_quality_composite_score(
            [m for m in STORE.quality_metrics.values()
             if m.get("region_id") == region_id and m["id"] != metric["id"]])
    if code == "PANEL_AVAILABILITY":
        active = [p for p in STORE.providers.values()
                  if p.get("region_id") == region_id
                  and p.get("status") == "ACTIVE"]
        return len(active)
    if code == "MEMBER_SATISFACTION":
        members = [m for m in STORE.members.values()
                   if m.get("region_id") == region_id
                   and m.get("status") in ("ACTIVE", "TRANSFER_PENDING")]
        return len(members)
    return int(metric.get("measured_value") or 0)


@bp.post("/regions/<region_id>/quality-metrics")
def create_quality_metric(region_id):
    principal((ROLE_QUALITY_REVIEW_BOARD,))
    get_region(region_id)
    body = payload()
    metric_code = require_field(body, "metric_code")
    period = require_field(body, "period")
    provider_id = require_field(body, "accountable_provider_id")
    require_body_reference("providers", provider_id)

    for existing in STORE.quality_metrics.values():
        if (existing.get("region_id") == region_id
                and existing.get("metric_code") == metric_code
                and existing.get("period") == period):
            raise_error(ERR_DUPLICATE_QUALITY_METRIC)

    row = new_record(
        region_id=region_id,
        metric_code=metric_code,
        period=period,
        target_value=require_field(body, "target_value"),
        measured_value=0,
        weighted_component_score=0,
        accountable_provider_id=provider_id,
        status="MEASURING",
    )
    store_row("quality_metrics", row)
    return single_response("quality_metrics", row, 201)


@bp.get("/regions/<region_id>/quality-metrics")
def list_region_quality_metrics(region_id):
    principal(QUALITY_READERS)
    get_region(region_id)
    rows = [m for m in STORE.quality_metrics.values()
            if m.get("region_id") == region_id]
    rows = filter_rows(rows, metric_code=arg("metric_code"),
                       period=arg("period"), status=arg("status"))
    return list_response("quality_metrics", rows)


@bp.get("/quality-metrics")
def list_quality_metrics():
    principal(QUALITY_READERS)
    rows = list(STORE.quality_metrics.values())
    rows = filter_rows(
        rows,
        region_id=arg("region_id"),
        accountable_provider_id=arg("accountable_provider_id"),
        metric_code=arg("metric_code"),
        status=arg("status"),
    )
    return list_response("quality_metrics", rows)


@bp.get("/quality-metrics/<metric_id>")
def get_one_quality_metric(metric_id):
    principal(QUALITY_READERS)
    return single_response("quality_metrics", get_quality_metric(metric_id))


@bp.post("/quality-metrics/<metric_id>/finalize")
def finalize_quality_metric(metric_id):
    principal((ROLE_QUALITY_REVIEW_BOARD,))
    metric = get_quality_metric(metric_id)
    if metric.get("status") not in ("MEASURING", "REOPENED"):
        raise_error(ERR_METRIC_NOT_FINALIZABLE)

    region_id = metric["region_id"]
    pct = _logged_internal_referral_pct(region_id, metric.get("period"))
    if pct != 1.0:
        raise_error(ERR_METRIC_NOT_FINALIZABLE,
                    "Finalization requires fully logged internal-referral activity.")

    measured = _measured_value(metric)
    metric["measured_value"] = measured
    metric["weighted_component_score"] = weighted_component_score(
        metric.get("metric_code"), measured, metric.get("target_value", 0))
    metric["status"] = "FINALIZED"
    touch(metric)

    provider_touched = None
    if metric.get("metric_code") == "QUALITY_COMPOSITE":
        provider = STORE.providers.get(metric.get("accountable_provider_id"))
        if provider is not None:
            provider["quality_score"] = measured
            recompute_provider_panel(provider)
            touch(provider)
            provider_touched = provider

    recompute_region_aggregates(region_id, bump_version=True)

    raise_alert(region_id, "QUALITY_GAP", "WARNING", "QualityMetric", metric_id)
    recompute_region_aggregates(region_id, bump_version=False)
    run_posture_ladder(region_id)

    if measured < _dec(metric.get("target_value", 0)):
        metric["status"] = "REMEDIATION"
        touch(metric)
        provider = STORE.providers.get(metric.get("accountable_provider_id"))
        if provider is not None and provider.get("status") == "ACTIVE":
            provider["status"] = "PANEL_CLOSED"
            touch(provider)

    _ = (provider_touched, component_score)
    return single_response("quality_metrics", metric)


def _dec(value):
    from rounding import dec
    return dec(value)


@bp.post("/quality-metrics/<metric_id>/reopen")
def reopen_quality_metric(metric_id):
    principal((ROLE_QUALITY_REVIEW_BOARD,))
    metric = get_quality_metric(metric_id)
    if metric.get("status") != "REMEDIATION":
        raise_error(ERR_INVALID_STATE)
    metric["status"] = "REOPENED"
    touch(metric)
    return single_response("quality_metrics", metric)