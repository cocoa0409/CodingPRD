"""Grant reporting: the reportable set, the pinned rounding order, cost share
and served-area outcomes (PRD 3.9)."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import db
import domain
import util
from db import store, touch
from services import households as household_service
from services import installations as installation_service


def reportable_set(grant_id, period_start_date, period_end_date):
    """PRD 3.9: INSTALLED or VERIFIED rows of the grant whose installed_at date
    falls inside the inclusive reporting period, ordered installed_at then
    created_at ascending."""
    rows = []
    for installation in store.installations.values():
        if installation["status"] not in domain.REPORTABLE_STATUSES:
            continue
        if installation["installed_at"] is None:
            continue
        lot = store.device_lots.get(installation["device_lot_id"])
        if lot is None or lot["funding_grant_id"] != grant_id:
            continue
        installed_date = installation["installed_at"].astimezone(timezone.utc).date()
        if installed_date < period_start_date or installed_date > period_end_date:
            continue
        rows.append(installation)
    rows.sort(key=lambda r: (r["installed_at"], r["created_at"], r["_seq"]))
    return rows


def household_of_installation(installation):
    visit = store.visits.get(installation["visit_id"])
    if visit is None:
        return None
    return store.households.get(visit["household_id"])


def recompute_money(report):
    """Per-device reimbursement with per-installation rounding first, then the
    five pinned cost-share steps (PRD 3.9)."""
    grant = store.grants.get(report["grant_id"])
    rows = reportable_set(
        report["grant_id"], report["period_start_date"], report["period_end_date"]
    )
    household_ids = []
    zone_ids = []
    total = 0
    for installation in rows:
        total += installation_service.reimbursable_for(
            grant, installation["device_type"], installation["reserved_cost_cents"]
        )
        household = household_of_installation(installation)
        if household is not None:
            if household["id"] not in household_ids:
                household_ids.append(household["id"])
            if household["zone_id"] not in zone_ids:
                zone_ids.append(household["zone_id"])
    report["installation_count"] = len(rows)
    report["household_count"] = len(household_ids)
    report["served_zone_count"] = len(zone_ids)
    report["reimbursable_total_cents"] = total

    direct = total
    indirect = util.round_cents(
        util.to_decimal(direct) * util.to_decimal(grant["indirect_rate_pct"]) / Decimal(100)
    )
    total_project = direct + indirect
    match_required = util.round_cents(
        util.to_decimal(total_project) * util.to_decimal(grant["match_pct"]) / Decimal(100)
    )
    report["indirect_cents"] = indirect
    report["total_project_cents"] = total_project
    report["partner_match_required_cents"] = match_required
    report["grant_share_cents"] = total_project - match_required
    return zone_ids


def zone_outcome(zone):
    """The before-and-after window pair anchored on service_start_date (PRD 3.9)."""
    result = {
        "baseline_fire_count": None,
        "post_fire_count": None,
        "baseline_fire_rate_per_1000": None,
        "post_fire_rate_per_1000": None,
        "rate_delta_pct": None,
        "baseline_injuries": None,
        "post_injuries": None,
        "injury_delta": None,
    }
    if zone["service_start_date"] is None:
        return result
    service_date = zone["service_start_date"]
    anchor = datetime(
        service_date.year, service_date.month, service_date.day, tzinfo=timezone.utc
    )
    window = timedelta(days=domain.OUTCOME_WINDOW_DAYS)
    baseline_start = anchor - window
    post_end = min(util.clock.now(), anchor + window)

    baseline_count = 0
    post_count = 0
    baseline_injuries = 0
    post_injuries = 0
    for incident in store.fire_incidents.values():
        if incident["zone_id"] != zone["id"]:
            continue
        occurred = incident["occurred_at"]
        if baseline_start <= occurred < anchor:
            baseline_count += 1
            baseline_injuries += incident["injuries"]
        elif anchor <= occurred < post_end:
            post_count += 1
            post_injuries += incident["injuries"]

    occupied = util.to_decimal(zone["occupied_units"])
    baseline_rate = util.round_half_up(
        util.to_decimal(baseline_count) * Decimal(1000) / occupied, 2
    )
    post_rate = util.round_half_up(
        util.to_decimal(post_count) * Decimal(1000) / occupied, 2
    )
    if baseline_rate == Decimal("0.00"):
        rate_delta = None
    else:
        rate_delta = util.round_half_up(
            Decimal(100) * (post_rate - baseline_rate) / baseline_rate, 2
        )
    result.update(
        {
            "baseline_fire_count": baseline_count,
            "post_fire_count": post_count,
            "baseline_fire_rate_per_1000": baseline_rate,
            "post_fire_rate_per_1000": post_rate,
            "rate_delta_pct": rate_delta,
            "baseline_injuries": baseline_injuries,
            "post_injuries": post_injuries,
            "injury_delta": post_injuries - baseline_injuries,
        }
    )
    return result


def outcome_summary(zone):
    """The zone-level computed summary of PRD 3.9."""
    figures = zone_outcome(zone)
    eligible, rate = household_service.retention_figures(
        [h for h in store.households.values() if h["zone_id"] == zone["id"]]
    )
    return {
        "zone_id": zone["id"],
        "service_start_date": util.fmt_date(zone["service_start_date"]),
        "baseline_fire_count": figures["baseline_fire_count"],
        "post_fire_count": figures["post_fire_count"],
        "baseline_fire_rate_per_1000": figures["baseline_fire_rate_per_1000"],
        "post_fire_rate_per_1000": figures["post_fire_rate_per_1000"],
        "rate_delta_pct": figures["rate_delta_pct"],
        "baseline_injuries": figures["baseline_injuries"],
        "post_injuries": figures["post_injuries"],
        "injury_delta": figures["injury_delta"],
        "served_household_count": zone["served_household_count"],
        "retention_eligible_count": eligible,
        "retention_rate_pct": rate,
    }


def recompute_outcomes(report, zone_ids):
    """Unit-weighted rollup over the served zones; zones whose
    service_start_date is null are excluded on both sides (PRD 3.9)."""
    baseline_numerator = Decimal(0)
    post_numerator = Decimal(0)
    denominator = Decimal(0)
    injury_delta = 0
    contributing = 0
    for zone_id in zone_ids:
        zone = store.zones.get(zone_id)
        if zone is None or zone["service_start_date"] is None:
            continue
        figures = zone_outcome(zone)
        units = util.to_decimal(zone["occupied_units"])
        baseline_numerator += util.to_decimal(figures["baseline_fire_rate_per_1000"]) * units
        post_numerator += util.to_decimal(figures["post_fire_rate_per_1000"]) * units
        denominator += units
        injury_delta += figures["injury_delta"]
        contributing += 1
    if contributing == 0 or denominator == 0:
        report["baseline_fire_rate_per_1000"] = None
        report["post_fire_rate_per_1000"] = None
        report["injury_delta"] = None
    else:
        report["baseline_fire_rate_per_1000"] = util.round_half_up(
            baseline_numerator / denominator, 2
        )
        report["post_fire_rate_per_1000"] = util.round_half_up(
            post_numerator / denominator, 2
        )
        report["injury_delta"] = injury_delta

    scoped = []
    for zone_id in zone_ids:
        scoped.extend(
            [h for h in store.households.values() if h["zone_id"] == zone_id]
        )
    eligible, rate = household_service.retention_figures(scoped)
    report["retention_rate_pct"] = rate


def recompute_all(report):
    zone_ids = recompute_money(report)
    recompute_outcomes(report, zone_ids)


def recompute_draft_reports(grant, installed_at):
    """Hop four of the commit cascade: every DRAFT report of the grant whose
    period covers the installation's install date re-runs the money arithmetic."""
    if installed_at is None:
        return
    installed_date = installed_at.astimezone(timezone.utc).date()
    reports = [
        r
        for r in store.grant_reports.values()
        if r["grant_id"] == grant["id"] and r["status"] == "DRAFT"
    ]
    for report in db.by_created_at(reports):
        if (
            report["period_start_date"] <= installed_date
            and installed_date <= report["period_end_date"]
        ):
            recompute_money(report)
            touch(report)
