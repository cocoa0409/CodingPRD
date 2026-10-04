"""Fee calculations: roster pricing, the engagement milestone, and invoices.

Sources: SCAFFOLD.yaml §1.3 `roster_fee_payability_weighted`,
`attributed_savings_severity_bucket`, `engagement_milestone_trigger`,
`invoice_milestone_time_allocation`, `retention_credit_compensation`; PRD §3.2,
§3.7, §3.8.
"""

from db import STORE
from errors import ApiError
from services import common
from utils import ANCHOR, cents, d, parse_iso

WEEKS_PER_MONTH = 4
# ---------------------------------------------------------------------------
# Client account
# ---------------------------------------------------------------------------
def client_of(ident):
    return STORE.need("ClientAccount", ident, "ClientAccount")


def enrollments_of_client(client_id):
    return [e for e in STORE.all("Enrollment") if member_client_id(e) == client_id]


def member_client_id(enrollment):
    member = STORE.get("Member", enrollment.get("member_id"))
    return member["client_account_id"] if member else None


def invoices_of_client(client_id):
    return [i for i in STORE.all("FeeInvoice")
            if i["client_account_id"] == client_id]


def billing_period_bounds(period):
    """(inclusive week_index of the period's first day, exclusive upper week)."""
    try:
        year, month = period.split("-")
        year, month = int(year), int(month)
        if not 1 <= month <= 12:
            raise ValueError
    except (AttributeError, ValueError):
        raise ApiError(
            "ERR_INVALID_REFERENCE", "billing_period must match YYYY-MM."
        )
    first = ANCHOR.replace(year=year, month=month, day=1)
    if month == 12:
        later = first.replace(year=year + 1, month=1)
    else:
        later = first.replace(month=month + 1)
    from utils import week_of

    start_week = week_of(first)
    next_month_start_week = week_of(later)
    return start_week, next_month_start_week, first


# ---------------------------------------------------------------------------
# roster_fee_payability_weighted
# ---------------------------------------------------------------------------
def acute_base():
    for track in STORE.all("ProgramTrack"):
        if track["track_code"] == "ACUTE":
            return int(track["base_fee_per_member_cents"])
    return 0


def roster_fee_variants(eligibility_file):
    members = [m for m in STORE.all("Member")
               if m["eligibility_file_id"] == eligibility_file["id"]]
    members = [m for m in members if m.get("musculo_condition_code") is not None]
    base = acute_base()
    if eligibility_file["roster_format"] == "LEGACY":
        # NESTED ROUNDING, PINNED: the floor is applied per member, BEFORE the
        # weighted sum.  Summing first and flooring once diverges whenever a
        # member's base is not an exact multiple of four.
        base = int(d(base) * d("0.75"))  # floor of a non-negative Decimal
    weighted = d(0)
    for member in members:
        weight = d("1.00") if member["member_status"] == "ELIGIBLE" else d("0.50")
        weighted += d(base) * d(100) * weight
    eligible_count = sum(
        1 for m in members if m["member_status"] == "ELIGIBLE"
    )
    client = STORE.get("ClientAccount", eligibility_file["client_account_id"])
    expected = d((client or {}).get("expected_monthly_engagement_rate") or "0.60")

    if eligible_count == 0:
        chronological = 0
    else:
        chronological = cents(weighted / d(eligible_count))

    row_count = len(members)
    denominator = d(row_count) * expected
    if denominator == 0:
        provisional = 0
    else:
        provisional = cents(weighted / denominator)

    return {
        "member_row_count": row_count,
        "eligible_member_count": eligible_count,
        "ineligible_member_count": row_count - eligible_count,
        "screened_member_count": row_count,
        "total_monthly_fee_cents": chronological,
        "provisional_total_monthly_fee_cents": provisional,
        "fee_variance_cents": chronological - provisional,
    }


# ---------------------------------------------------------------------------
# engagement_milestone_trigger (inclusive boundary)
# ---------------------------------------------------------------------------
def adhered_group(client_id, strict=False):
    rows = []
    for enrollment in enrollments_of_client(client_id):
        if enrollment["enrollment_status"] != "ACTIVE":
            continue
        if (enrollment.get("weeks_active") or 0) < 1:
            continue
        track = common.track_of(enrollment)
        if track is None:
            continue
        rate = d(enrollment["adherence_rate"])
        threshold = d(track["min_adherence_rate"])
        if (rate > threshold) if strict else (rate >= threshold):
            rows.append(enrollment)
    return rows


def milestone_summary(client_id, strict=False):
    group = adhered_group(client_id, strict=strict)
    total = d(0)
    for enrollment in group:
        track = common.track_of(enrollment)
        total += (
            d(track["base_fee_per_member_cents"])
            * d(enrollment["weeks_active"])
            / d(WEEKS_PER_MONTH)
        )
    return {
        "milestone_member_count": len(group),
        "milestone_engagement_component_cents": cents(total),
    }


# ---------------------------------------------------------------------------
# invoice_milestone_time_allocation
# ---------------------------------------------------------------------------
def months_active(enrollment):
    current_week = common.weeks_active(enrollment) + enrollment["enrolled_week"]
    return (current_week - enrollment["enrolled_week"]) // WEEKS_PER_MONTH


def elapsed_weeks(enrollment):
    from utils import week_of

    return week_of(STORE.clock) - enrollment["enrolled_week"]


def pinned_share(enrollment):
    track = common.track_of(enrollment)
    if track is None:
        return 0
    return cents(
        d(track["base_fee_per_member_cents"]) * d(months_active(enrollment))
    )


def trailing_delta(enrollment):
    track = common.track_of(enrollment)
    if track is None:
        return 0
    leftover = elapsed_weeks(enrollment) - WEEKS_PER_MONTH * months_active(enrollment)
    return cents(
        d(track["base_fee_per_member_cents"]) * d(leftover) / d(WEEKS_PER_MONTH)
    )


def membership_delta(enrollment):
    track = common.track_of(enrollment)
    if track is None:
        return 0
    return cents(
        d(track["base_fee_per_member_cents"])
        * d(enrollment["weeks_active"])
        / d(WEEKS_PER_MONTH)
    )


def enrollment_inclusion_set(client_id, period):
    """Enrollments whose enrolled_week falls in the period's four-week month.

    The period runs from the week of its first day through the week of the
    same day one month later, half-open on the upper end.  The week-based
    span is pinned at four weeks so that the window matches the four-week
    month the member-week arithmetic uses throughout the invoice.
    """
    start_week, _, _ = billing_period_bounds(period)
    out = []
    for enrollment in enrollments_of_client(client_id):
        week = enrollment.get("enrolled_week")
        if week is None:
            continue
        if start_week <= week < start_week + WEEKS_PER_MONTH:
            out.append(enrollment)
    out.sort(key=lambda e: (e["enrolled_week"], e["created_at"], e["id"]))
    return out



def savings_share(client_id, period, statuses, rate=None, billing_time=False):
    """Fee from attributed downstream savings in the period.

    The default reading sums the version-pinned `attributed_savings_cents`
    already persisted on each measurement.  The billing-time re-evaluation
    variant substitutes each line's superseded instance in place of its
    current one and recomputes the window's engagement rate as of the invoice
    creation instant, so the two readings diverge on the same window whenever
    a line has been superseded (SCAFFOLD 1.3, PRD 3.6).
    """
    if rate is None:
        client = client_of(client_id)
        rate = d(client["savings_share_rate"])
    total = d(0)
    start_week, _, _ = billing_period_bounds(period)
    end_week = start_week + WEEKS_PER_MONTH
    for enrollment in enrollments_of_client(client_id):
        if billing_time:
            # One substituted instance per superseded family, over the whole
            # enrollment, then restricted to the measurements in the period.
            from collections import defaultdict

            buckets = defaultdict(list)
            for line in common.claim_lines_of(enrollment["id"]):
                buckets[
                    (line["claim_service_week"], line["claim_source"])
                ].append(line)
            substituted = []
            for family in buckets.values():
                family.sort(key=lambda c: c["line_instance_version"])
                older = [
                    c for c in family
                    if c["claim_superseded"] or c["claim_withdrawn"]
                ]
                substituted.append(older[0] if older else family[-1])
        for row in common.measurements_of(enrollment["id"], statuses=statuses):
            week = row["measurement_week"]
            if not (start_week <= week < end_week):
                continue
            if billing_time:
                scoped = [
                    line for line in substituted
                    if row["window_start_week"] <= line["claim_service_week"]
                    <= row["window_end_week"]
                ]
                total += d(common.attributed_savings(
                    enrollment,
                    row,
                    rate=enrollment["adherence_rate"],
                    lines=scoped,
                ))
            else:
                total += d(row.get("attributed_savings_cents") or 0)
    return cents(total * d(rate))


def late_fee_component(client_id, period, invoice_created_at):
    """Fees from reconciliations that lapsed strictly after invoice creation."""
    start_week, _, _ = billing_period_bounds(period)
    end_week = start_week + WEEKS_PER_MONTH
    created = parse_iso(invoice_created_at)
    total = 0
    for enrollment in enrollments_of_client(client_id):
        if enrollment["enrollment_status"] != "COMPLETED":
            continue
        week = enrollment.get("completed_week")
        if week is None or not (start_week <= week < end_week):
            continue
        if created is not None and parse_iso(enrollment["updated_at"]) <= created:
            continue
        total += membership_delta(enrollment)
    return total


def recomputed_component(client_id, period, previous_group_ids):
    """Full recompute of the pinned component over the current tables."""
    inclusion = enrollment_inclusion_set(client_id, period)
    total = d(0)
    for enrollment in inclusion:
        total += d(pinned_share(enrollment)) + d(trailing_delta(enrollment))

    current_group = {e["id"] for e in adhered_group(client_id)}
    previous = set(previous_group_ids or set())
    for enrollment in enrollments_of_client(client_id):
        delta = membership_delta(enrollment)
        if enrollment["id"] in current_group and enrollment["id"] not in previous:
            total += d(delta)
        elif enrollment["id"] not in current_group and enrollment["id"] in previous:
            total -= d(delta)
    return cents(total)


def build_invoice_components(invoice):
    """(re)compute every component of an invoice from current state."""
    client_id = invoice["client_account_id"]
    period = invoice["billing_period"]
    client = client_of(client_id)
    inclusion = enrollment_inclusion_set(client_id, period)

    summary = milestone_summary(client_id)
    invoice["milestone_member_count"] = summary["milestone_member_count"]
    invoice["milestone_engagement_component_cents"] = summary[
        "milestone_engagement_component_cents"
    ]

    invoice["additional_fee_component_cents"] = late_fee_component(
        client_id, period, invoice["created_at"]
    )

    provisional_engagement = d(0)
    for enrollment in inclusion:
        provisional_engagement += d(pinned_share(enrollment))

    savings = (
        savings_share(
            client_id, period, ("RECORDED", "FINALIZED"),
            client["savings_share_rate"], billing_time=True,
        )
        if invoice["invoice_status"] == "FINALIZED"
        else savings_share(client_id, period, ("RECORDED",),
                           client["savings_share_rate"])
    )
    invoice["savings_share_component_cents"] = savings
    invoice["provisional_amount_cents"] = cents(
        provisional_engagement + d(savings)
    )

    recomputed = recomputed_component(
        client_id, period, invoice.get("_milestone_group")
    )
    invoice["recalculated_component_cents"] = recomputed
    invoice["final_amount_cents"] = cents(
        d(recomputed)
        + d(savings_share(
            client_id, period, ("RECORDED", "FINALIZED"),
            client["savings_share_rate"], billing_time=True,
        ))
    )
    invoice["net_delta_cents"] = (
        invoice["final_amount_cents"] - invoice["provisional_amount_cents"]
    )
    return invoice


def refresh_draft_invoices(client_id):
    """Re-quote every DRAFT invoice of a client after a reconciliation."""
    for invoice in invoices_of_client(client_id):
        if invoice["invoice_status"] == "DRAFT":
            build_invoice_components(invoice)


# ---------------------------------------------------------------------------
# retention credit / membership roll
# ---------------------------------------------------------------------------
def retention_credit(client_id):
    client_of(client_id)
    drafts = [i for i in invoices_of_client(client_id)
              if i["invoice_status"] == "DRAFT"]
    summary = milestone_summary(client_id)
    return {
        "draft_invoice_count": len(drafts),
        "retained_credit_amount_cents": sum(
            int(i.get("provisional_amount_cents") or 0) for i in drafts
        ),
        "proposal_member_count": summary["milestone_member_count"],
        "proposal_amount_cents": summary["milestone_engagement_component_cents"],
    }


def membership_roll(client_id, as_of_week_index):
    """Member-week entitlement as of a requested week (read-only view).

    The roll reports one population (the enrollments that have cleared their
    first active week) at one member-week scale, alongside the figure that
    figure will carry once that week's month is priced -- so
    proposed/entitled member counts agree and the amounts are the forward and
    chronological readings of the same member-weeks.
    """
    client_of(client_id)
    group = []
    for enrollment in enrollments_of_client(client_id):
        if enrollment["enrollment_status"] != "ACTIVE":
            continue
        week = enrollment.get("enrolled_week")
        if week is None or week > as_of_week_index:
            continue
        weeks = as_of_week_index - week
        if weeks < 1:
            continue
        track = common.track_of(enrollment)
        if track is None:
            continue
        if d(enrollment["adherence_rate"]) < d(track["min_adherence_rate"]):
            continue
        group.append((enrollment, weeks))

    total = d(0)
    for enrollment, weeks in group:
        track = common.track_of(enrollment)
        unit = d(track["base_fee_per_member_cents"])
        total += unit * d(weeks) / d(WEEKS_PER_MONTH)

    return {
        "proposed_member_count": len(group),
        "proposed_amount_cents": cents(total),
        "entitled_member_count": len(group),
        "entitled_amount_cents": cents(total),
    }


def engagement_report(client_id):
    client = client_of(client_id)
    enrollments = []
    summary = milestone_summary(client_id)
    for enrollment in enrollments_of_client(client_id):
        track = common.track_of(enrollment)
        member = common.member_of(enrollment)
        enrollments.append({
            "enrollment_id": enrollment["id"],
            "member_id": enrollment["member_id"],
            "member_status": member["member_status"] if member else None,
            "enrollment_status": enrollment["enrollment_status"],
            "track_code": track["track_code"] if track else None,
            "enrolled_week": enrollment.get("enrolled_week"),
            "weeks_active": enrollment.get("weeks_active"),
            "adherence_rate": enrollment.get("adherence_rate"),
            "projected_engagement_milestone": enrollment.get(
                "projected_engagement_milestone"
            ),
            "milestone_weeks": (
                enrollment.get("weeks_active")
                if enrollment.get("projected_engagement_milestone") == 1 else 0
            ),
        })
    return {
        "client_account_id": client["id"],
        "billing_model": client["billing_model"],
        "expected_monthly_engagement_rate": client[
            "expected_monthly_engagement_rate"
        ],
        "enrollments": enrollments,
        "milestone_member_count": summary["milestone_member_count"],
        "milestone_engagement_component_cents": summary[
            "milestone_engagement_component_cents"
        ],
    }