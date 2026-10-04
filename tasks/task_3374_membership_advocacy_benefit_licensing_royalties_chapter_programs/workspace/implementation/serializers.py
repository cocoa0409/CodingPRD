"""Resource serializers. Derived fields are recomputed from the logical clock
on every read (PRD §2.4); stored fields are copied through."""

from datetime import date

import services


def _base(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def household_view(h):
    out = _base(h)
    out["state_code"] = h["state_code"]
    out["auto_renew_enabled"] = h["auto_renew_enabled"]
    out["status"] = services.household_status(h["id"])
    out["primary_member_id"] = h["primary_member_id"]
    out["secondary_member_id"] = h["secondary_member_id"]
    out["lifetime_collected_cents"] = h["lifetime_collected_cents"]
    out["lifetime_refunded_cents"] = h["lifetime_refunded_cents"]
    return out


def member_view(m):
    out = _base(m)
    out["household_id"] = m["household_id"]
    out["full_name"] = m["full_name"]
    out["date_of_birth"] = m["date_of_birth"]
    out["role_in_household"] = m["role_in_household"]
    out["benefit_marketing_opt_out"] = m["benefit_marketing_opt_out"]
    out["age_years"] = services.compute_age_years(date.fromisoformat(m["date_of_birth"]))
    out["in_good_standing"] = services.member_in_good_standing(m)
    return out


def term_view(t):
    out = _base(t)
    for key in (
        "household_id", "term_years", "is_renewal", "start_date", "end_date",
        "purchased_at", "paid_cents", "refunded_cents", "cancel_reason",
        "cancelled_at", "status",
    ):
        out[key] = t[key]
    return out


def provider_view(p):
    out = _base(p)
    out["legal_name"] = p["legal_name"]
    out["status"] = p["status"]
    out["royalty_balance_cents"] = p["royalty_balance_cents"]
    out["escalations_trailing_12mo"] = services.provider_trailing_count(p["id"])
    return out


def agreement_view(a):
    out = _base(a)
    for key in (
        "provider_id", "product_category", "effective_from", "effective_to",
        "status", "probation_count", "recognized_royalty_cents",
        "provisional_outstanding_cents",
    ):
        out[key] = a[key]
    out["escalations_trailing_12mo"] = services.agreement_trailing_count(a["id"])
    out["royalty_exposure_cents"] = a["recognized_royalty_cents"] + a["provisional_outstanding_cents"]
    return out


def statement_view(s):
    out = _base(s)
    for key in (
        "license_agreement_id", "period_year", "period_quarter",
        "reported_sales_cents", "audited_sales_cents",
        "provisional_royalty_cents", "final_royalty_cents", "delta_cents",
        "status",
    ):
        out[key] = s[key]
    return out


def complaint_view(c):
    out = _base(c)
    for key in (
        "member_id", "license_agreement_id", "category", "severity",
        "description", "status", "filed_at", "escalated_at", "resolution_code",
    ):
        out[key] = c[key]
    return out


def entity_view(e):
    out = _base(e)
    for key in ("kind", "display_name", "balance_cents"):
        out[key] = e[key]
    return out


def transfer_view(t):
    out = _base(t)
    for key in (
        "from_entity_id", "to_entity_id", "amount_cents", "purpose",
        "requested_by_user_id", "decided_by_user_id", "status",
        "from_balance_after_cents", "to_balance_after_cents", "executed_at",
    ):
        out[key] = t[key]
    return out


def publication_view(p):
    out = _base(p)
    for key in ("title", "publication_date", "min_cpm_cents", "max_cpm_cents"):
        out[key] = p[key]
    out["circulation_count"] = services.circulation_count(p["publication_date"])
    return out


def booking_view(b):
    out = _base(b)
    for key in (
        "publication_id", "advertiser_name", "category", "agreed_cpm_cents",
        "estimated_cost_cents", "status",
    ):
        out[key] = b[key]
    return out


def chapter_view(c):
    out = _base(c)
    for key in ("name", "state_code", "city"):
        out[key] = c[key]
    return out


def session_view(s):
    out = _base(s)
    for key in (
        "chapter_id", "course_kind", "instructor_name", "start_time",
        "end_time", "capacity", "enrolled_member_ids",
    ):
        out[key] = s[key]
    out["enrolled_count"] = len(s["enrolled_member_ids"])
    out["status"] = services.session_status(s)
    return out


def campaign_view(c):
    out = _base(c)
    for key in (
        "title", "level", "state_code", "issue_area", "start_date",
        "end_date", "sponsor_entity_id",
    ):
        out[key] = c[key]
    out["computed_status"] = services.campaign_status(c)
    return out


def mobilization_view(m):
    out = _base(m)
    for key in ("campaign_id", "channel", "audience_spec", "audience_count"):
        out[key] = m[key]
    return out
