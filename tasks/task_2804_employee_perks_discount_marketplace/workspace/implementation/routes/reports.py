"""Aggregated analytics with k-anonymity cohort suppression (PRD 2.10)."""
from flask import Blueprint

import auth
import calc
import clock
import db
import response
import support
import validate

bp = Blueprint("reports", __name__)


def _population(period_start, period_end, employer_id=None):
    """Verified redemptions whose verified_at lies in the half-open period."""
    rows = []
    for row in db.redemptions.values():
        if row["verification_status"] != "VERIFIED":
            continue
        if employer_id is not None and row["employer_id"] != employer_id:
            continue
        stamp = row["verified_at"]
        if stamp is None:
            continue
        if period_start <= stamp < period_end:
            rows.append(row)
    return rows


def _grouped(rows):
    groups = {}
    for row in rows:
        offer = db.offers.get(row["offer_id"])
        category = offer["category"] if offer is not None else None
        bucket = groups.setdefault(category, {
            "redemption_count": 0,
            "discount_amount_cents": 0,
            "memberships": set(),
            "employers": set(),
        })
        bucket["redemption_count"] += 1
        bucket["discount_amount_cents"] += int(row["discount_amount_cents"] or 0)
        bucket["memberships"].add(row["membership_id"])
        bucket["employers"].add(row["employer_id"])
    return groups


@bp.get("/perks/employers/<row_id>/engagement-report")
def engagement_report(row_id):
    principal = auth.require(auth.EMPLOYER_ADMIN, auth.PLATFORM_ADMIN)
    if principal.is_employer_admin and row_id != principal.user_id:
        auth.deny_scope()
    employer = support.fetch("employers", row_id)
    period_start = validate.query_instant("period_start")
    period_end = validate.query_instant("period_end")
    floor = employer["privacy_min_cohort_size"]
    if floor is None:
        floor = calc.DEFAULT_PRIVACY_MIN_COHORT_SIZE
    floor = int(floor)
    rows = _population(period_start, period_end, employer_id=employer["id"])
    groups = _grouped(rows)
    category_rows = []
    suppressed_count = 0
    for category in sorted(groups.keys(), key=lambda name: (name is None, name)):
        bucket = groups[category]
        cohort = len(bucket["memberships"])
        # The floor is inclusive: a row whose cohort equals it is NOT suppressed.
        if cohort < floor:
            suppressed_count += 1
            category_rows.append({
                "category": category,
                "suppressed": True,
                "redemption_count": None,
                "discount_amount_cents": None,
                "distinct_redeemer_count": None,
            })
        else:
            category_rows.append({
                "category": category,
                "suppressed": False,
                "redemption_count": bucket["redemption_count"],
                "discount_amount_cents": bucket["discount_amount_cents"],
                "distinct_redeemer_count": cohort,
            })
    # Totals span every redemption in the window, INCLUDING suppressed rows.
    total_discount = sum(int(r["discount_amount_cents"] or 0) for r in rows)
    total_redeemers = len({r["membership_id"] for r in rows})
    return response.ok({
        "employer_id": employer["id"],
        "period_start": clock.fmt(period_start),
        "period_end": clock.fmt(period_end),
        "privacy_min_cohort_size": floor,
        "category_rows": category_rows,
        "suppressed_category_count": suppressed_count,
        "total_redemption_count": len(rows),
        "total_discount_amount_cents": total_discount,
        "total_distinct_redeemer_count": total_redeemers,
    })


@bp.get("/perks/category-demand")
def category_demand():
    auth.require(auth.PARTNER_MANAGER, auth.MERCHANT)
    period_start = validate.query_instant("period_start")
    period_end = validate.query_instant("period_end")
    floor = calc.PARTNER_MIN_EMPLOYER_COHORT
    # The partner feed spans every verified redemption across all employers.
    rows = _population(period_start, period_end)
    groups = _grouped(rows)
    category_rows = []
    suppressed_count = 0
    for category in sorted(groups.keys(), key=lambda name: (name is None, name)):
        bucket = groups[category]
        cohort = len(bucket["employers"])
        if cohort < floor:
            suppressed_count += 1
            category_rows.append({
                "category": category,
                "suppressed": True,
                "redemption_count": None,
                "discount_amount_cents": None,
                "distinct_employer_count": None,
            })
        else:
            category_rows.append({
                "category": category,
                "suppressed": False,
                "redemption_count": bucket["redemption_count"],
                "discount_amount_cents": bucket["discount_amount_cents"],
                "distinct_employer_count": cohort,
            })
    return response.ok({
        "period_start": clock.fmt(period_start),
        "period_end": clock.fmt(period_end),
        "partner_min_employer_cohort": floor,
        "category_rows": category_rows,
        "suppressed_category_count": suppressed_count,
        "total_redemption_count": len(rows),
    })
