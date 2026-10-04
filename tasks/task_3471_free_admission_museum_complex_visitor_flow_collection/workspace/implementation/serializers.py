"""Entity serializers.

Each function emits exactly the fields the scaffold entity table declares
(plus the four common fields), with computed fields resolved at read time.
Internal bookkeeping fields (``_seq``, ``_creator_user_id``, parsed datetime
cache fields) are never serialized.
"""

import calc

_COMMON = ("id", "created_at", "updated_at", "version")


def _pick(entity, fields):
    out = {k: entity.get(k) for k in fields}
    for k in _COMMON:
        out[k] = entity[k]
    return out


def museum(m):
    out = _pick(
        m,
        (
            "museum_code",
            "display_name",
            "requires_timed_pass",
            "quarter_hour_pass_quota",
            "daily_pass_quota",
            "screening_rate_per_quarter_hour",
            "closed_dates",
        ),
    )
    out["closed_dates"] = list(m["closed_dates"])
    # Read-side diagnostic, FORWARD variant (PRD 3.1)
    out["screening_backlog_minutes"] = calc.screening_backlog_minutes(m)
    return out


def timed_entry_pass(p):
    return _pick(
        p,
        (
            "museum_id",
            "visitor_name",
            "holder_member_id",
            "visit_date",
            "entry_quarter_hour",
            "status",
            "admitted_slot",
            "created_by_user_id",
        ),
    )


def member(m):
    out = _pick(m, ("full_name", "email", "membership_term_months", "expires_on"))
    out["member_status"] = calc.member_status(m)
    return out


def special_exhibition(e):
    return _pick(
        e,
        (
            "museum_id",
            "revenue_fund_id",
            "title",
            "fee_cents",
            "daily_ticket_quota",
            "member_presale_opens_at",
            "public_sale_opens_at",
            "status",
        ),
    )


def exhibition_ticket(t):
    return _pick(
        t,
        (
            "exhibition_id",
            "member_id",
            "buyer_name",
            "visit_date",
            "price_paid_cents",
            "status",
        ),
    )


def education_program(p):
    return _pick(
        p,
        (
            "museum_id",
            "title",
            "gallery_code",
            "day_of_week",
            "start_minute",
            "end_minute",
            "student_capacity",
            "docent_ratio",
            "max_group_size",
            "required_docent_certification",
            "status",
        ),
    )


def docent(d):
    return _pick(d, ("full_name", "certification_level", "active"))


def docent_assignment(a):
    return _pick(a, ("program_id", "docent_id", "service_date", "status"))


def school_reservation(r):
    return _pick(
        r,
        (
            "museum_id",
            "program_id",
            "school_name",
            "headcount",
            "visit_date",
            "status",
            "created_by_user_id",
        ),
    )


def collection_object(o):
    return _pick(
        o,
        (
            "accession_number",
            "title",
            "declared_value_cents",
            "is_cultural_property",
            "status",
        ),
    )


def loan_agreement(l):
    return _pick(
        l,
        (
            "object_id",
            "borrower_institution",
            "loan_start_date",
            "loan_end_date",
            "declared_value_cents",
            "coverage_type",
            "courier_required",
            "status",
            "negotiated_round",
            "premium_cents",
        ),
    )


def condition_report(r):
    return _pick(
        r, ("loan_id", "report_kind", "condition_summary", "damage_noted", "status")
    )


def collection_review(r):
    return _pick(
        r,
        (
            "review_kind",
            "object_id",
            "fund_id",
            "proposed_object_title",
            "estimated_cost_cents",
            "disposal_method",
            "cultural_property_review_completed",
            "status",
            "submitted_by_user_id",
            "decided_by_user_id",
        ),
    )


def fund_account(f):
    out = _pick(f, ("fund_code", "fund_type", "appropriation_cents", "status"))
    out["receipts_cents"] = calc.fund_receipts(f["id"])
    out["settled_available_cents"] = calc.settled_available(f)
    out["committed_available_cents"] = calc.committed_available(f)
    return out


def expenditure(e):
    return _pick(
        e, ("fund_id", "review_id", "amount_cents", "activity_type", "memo", "status")
    )


def research_access_request(r):
    return _pick(
        r,
        (
            "object_id",
            "scholar_name",
            "research_topic",
            "visit_start_date",
            "visit_end_date",
            "status",
            "created_by_user_id",
        ),
    )
