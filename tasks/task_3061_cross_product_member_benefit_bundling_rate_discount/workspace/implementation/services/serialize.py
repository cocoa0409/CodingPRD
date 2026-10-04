"""Resource serialisers exposing exactly the entity fields the PRD declares."""

from db import DB
from services import calc, recompute

COMMON = ("id", "created_at", "updated_at", "version")


def _pick(entity, names):
    return {name: entity.get(name) for name in names}


def member(member):
    data = _pick(member, COMMON)
    data.update(
        _pick(
            member,
            (
                "member_number",
                "full_name",
                "email",
                "member_status",
                "member_since_at",
                "product_adoption_count",
                "product_line_set",
                "member_tier",
                "qualifying_deposit_balance_cents",
                "benefit_entitlement_state",
                "rewards_points_balance",
                "churn_risk_score",
                "last_qualifying_deposit_at",
            ),
        )
    )
    return data


def holding(holding):
    data = _pick(holding, COMMON)
    data.update(
        _pick(
            holding,
            (
                "member_id",
                "product_line",
                "adoption_status",
                "adopted_at",
                "closed_at",
                "balance_cents",
                "deposit_rate_eligible",
                "cross_sell_eligible",
                "reunderwriting_permitted",
            ),
        )
    )
    return data


def loan(loan):
    data = _pick(loan, COMMON)
    data.update(
        _pick(
            loan,
            (
                "member_id",
                "holding_id",
                "loan_type",
                "principal_cents",
                "base_apr_bps",
                "autopay_status",
                "pricing_status",
                "discount_stack_bps",
                "effective_apr_bps",
                "last_priced_at",
            ),
        )
    )
    return data


def enrollment(enr):
    data = _pick(enr, COMMON)
    data.update(
        _pick(
            enr,
            (
                "member_id",
                "required_monthly_amount_cents",
                "status",
                "qualified_at",
                "last_deposit_at",
                "consecutive_qualifying_months",
                "requalification_due_at",
                "grace_deadline_at",
                "missed_cycle_count",
            ),
        )
    )
    return data


def entitlement(ent):
    data = _pick(ent, COMMON)
    data.update(
        _pick(
            ent,
            (
                "member_id",
                "source_holding_id",
                "benefit_code",
                "entitlement_status",
                "value_bps",
                "governing_rule_id",
                "granted_at",
                "stepped_down_at",
                "reconciliation_state",
                "override_requested_by",
                "override_approved_by",
            ),
        )
    )
    data["reconciliation_state"] = calc.reconciliation_state(ent)
    return data


def rule(rule):
    data = _pick(rule, COMMON)
    data.update(
        _pick(
            rule,
            (
                "rule_code",
                "discount_kind",
                "stacking_class",
                "discount_bps",
                "stacks_on_rule_id",
                "requires_direct_deposit",
                "min_member_tier",
                "effective_from",
                "effective_to",
                "status",
            ),
        )
    )
    return data


def application(app):
    data = _pick(app, COMMON)
    data.update(
        _pick(
            app,
            (
                "loan_account_id",
                "rule_id",
                "applied_bps",
                "application_state",
                "applied_at",
                "window_from",
                "window_to",
                "preempted_by_application_id",
            ),
        )
    )
    return data


def ledger(entry):
    data = _pick(entry, COMMON)
    data.update(
        _pick(
            entry,
            (
                "member_id",
                "loan_account_id",
                "entry_type",
                "points_delta",
                "principal_reduction_cents",
                "entry_status",
                "source_event_code",
                "reversed_by_entry_id",
            ),
        )
    )
    return data


def cycle(cycle):
    data = _pick(cycle, COMMON)
    data.update(
        _pick(
            cycle,
            (
                "member_id",
                "cycle_index",
                "opened_at",
                "due_at",
                "evaluated_at",
                "status",
                "qualifying_month_count",
                "qualifying_deposit_total_cents",
            ),
        )
    )
    return data


def notice(notice):
    data = _pick(notice, COMMON)
    data.update(
        _pick(
            notice,
            (
                "member_id",
                "notice_type",
                "status",
                "issued_at",
                "effective_at",
                "related_entitlement_id",
                "reason_code",
            ),
        )
    )
    return data


def session(session):
    data = _pick(session, COMMON)
    data.update(
        _pick(
            session,
            (
                "member_id",
                "coach_ref",
                "session_kind",
                "starts_at",
                "ends_at",
                "status",
                "capacity_total",
                "seats_reserved",
            ),
        )
    )
    return data


def check(check):
    data = _pick(check, COMMON)
    data.update(
        _pick(
            check,
            (
                "member_id",
                "target_product_line",
                "consent_recorded",
                "underwriting_reuse_permitted",
                "conditioning_blocked",
                "status",
                "decided_at",
                "decided_by",
            ),
        )
    )
    return data


def posting(posting):
    return dict(posting)


SERIALIZERS = {
    "members": member,
    "holdings": holding,
    "loan_accounts": loan,
    "enrollments": enrollment,
    "entitlements": entitlement,
    "rules": rule,
    "applications": application,
    "ledger": ledger,
    "cycles": cycle,
    "notices": notice,
    "sessions": session,
    "checks": check,
}


def render(entity):
    for collection, fn in SERIALIZERS.items():
        if entity.get("id") in getattr(DB, collection):
            return fn(entity)
    return dict(entity)