"""Request-payload builders.

Money is always emitted as a JSON integer number of cents (PRD §2.5), instants
always as full ISO 8601 UTC instants with three fractional digits (PRD §2.4),
and the two calendar-date families always as plain YYYY-MM-DD strings.
"""

from datetime import date, timedelta
from typing import Dict, List, Optional

from .constants import DEFAULT_CURE_DAYS


# ------------------------------------------------------------------- time help
def utc_instant(day: str, hour: int = 0, minute: int = 0, second: int = 0,
                millisecond: int = 0) -> str:
    """Build an ISO 8601 UTC instant with exactly three fractional digits."""
    return f"{day}T{hour:02d}:{minute:02d}:{second:02d}.{millisecond:03d}Z"


def date_plus_days(day: str, days: int) -> str:
    return (date.fromisoformat(day) + timedelta(days=days)).isoformat()


def instant_plus_days(day: str, days: int, hour: int = 0) -> str:
    return utc_instant(date_plus_days(day, days), hour)


def review_window(day: str, start_hour: int, end_hour: int) -> Dict[str, str]:
    """A half-open reviewer window on one calendar day (PRD §3.5)."""
    return {
        "review_window_start_at": utc_instant(day, start_hour),
        "review_window_end_at": utc_instant(day, end_hour),
    }


# ------------------------------------------------------------------- registry
def studio_payload(legal_name: str = "Northlight Studio",
                   contact_email: str = "dev@northlight.example",
                   country_code: Optional[str] = "SE") -> Dict:
    payload = {"legal_name": legal_name, "contact_email": contact_email}
    if country_code is not None:
        payload["country_code"] = country_code
    return payload


def publisher_payload(legal_name: str = "Vantage Publishing",
                      contact_email: str = "ops@vantage.example",
                      country_code: Optional[str] = "US") -> Dict:
    payload = {"legal_name": legal_name, "contact_email": contact_email}
    if country_code is not None:
        payload["country_code"] = country_code
    return payload


def publisher_user_payload(publisher_id: str, display_name: str, function: str) -> Dict:
    return {
        "publisher_id": publisher_id,
        "display_name": display_name,
        "function": function,
    }


# ------------------------------------------------------------------ agreement
def agreement_payload(studio_id: str, publisher_id: str, title: str,
                      advance_total_cents: int, royalty_rate_bps: int = 2500,
                      ship_date_original: str = "2027-03-31",
                      recoupable_cost_cap_bps: Optional[int] = None,
                      platform_fee_bps: Optional[int] = None,
                      live_ops_quarterly_funding_cents: Optional[int] = None) -> Dict:
    payload = {
        "studio_id": studio_id,
        "publisher_id": publisher_id,
        "title": title,
        "advance_total_cents": int(advance_total_cents),
        "royalty_rate_bps": int(royalty_rate_bps),
        "ship_date_original": ship_date_original,
    }
    if recoupable_cost_cap_bps is not None:
        payload["recoupable_cost_cap_bps"] = int(recoupable_cost_cap_bps)
    if platform_fee_bps is not None:
        payload["platform_fee_bps"] = int(platform_fee_bps)
    if live_ops_quarterly_funding_cents is not None:
        payload["live_ops_quarterly_funding_cents"] = int(live_ops_quarterly_funding_cents)
    return payload


def milestone_payload(agreement_id: str, sequence_index: int, title: str,
                      gate_profile: str, funded_amount_cents: int,
                      contractor_budget_cents: int,
                      acceptance_criteria: Optional[List[str]] = None,
                      depends_on_milestone_id: Optional[str] = None) -> Dict:
    payload = {
        "agreement_id": agreement_id,
        "sequence_index": int(sequence_index),
        "title": title,
        "gate_profile": gate_profile,
        "funded_amount_cents": int(funded_amount_cents),
        "contractor_budget_cents": int(contractor_budget_cents),
        "acceptance_criteria": list(
            acceptance_criteria
            if acceptance_criteria is not None
            else ["Core loop playable", "Two biomes complete", "Save and load"]
        ),
    }
    if depends_on_milestone_id is not None:
        payload["depends_on_milestone_id"] = depends_on_milestone_id
    return payload


# ---------------------------------------------------------------------- builds
def build_payload(milestone_id: str, build_number: int,
                  feature_completeness_pct: float,
                  crash_free_sessions_pct: float,
                  content_completeness_pct: float,
                  known_blocker_count: int,
                  addressed_condition_indexes: Optional[List[int]] = None,
                  release_notes: Optional[str] = None) -> Dict:
    payload = {
        "milestone_id": milestone_id,
        "build_number": int(build_number),
        "feature_completeness_pct": float(feature_completeness_pct),
        "crash_free_sessions_pct": float(crash_free_sessions_pct),
        "content_completeness_pct": float(content_completeness_pct),
        "known_blocker_count": int(known_blocker_count),
    }
    if addressed_condition_indexes is not None:
        payload["addressed_condition_indexes"] = list(addressed_condition_indexes)
    if release_notes is not None:
        payload["release_notes"] = release_notes
    return payload


def build_payload_from_metrics(milestone_id: str, build_number: int, metrics: Dict,
                              addressed_condition_indexes: Optional[List[int]] = None) -> Dict:
    return build_payload(
        milestone_id,
        build_number,
        metrics["feature_completeness_pct"],
        metrics["crash_free_sessions_pct"],
        metrics["content_completeness_pct"],
        metrics["known_blocker_count"],
        addressed_condition_indexes,
    )


# --------------------------------------------------------------------- reviews
def review_payload(build_id: str, verdict: str, window_start: str, window_end: str,
                   conditions: Optional[List[int]] = None,
                   cure_days: Optional[int] = None,
                   notes: Optional[str] = None) -> Dict:
    payload = {
        "build_id": build_id,
        "verdict": verdict,
        "review_window_start_at": window_start,
        "review_window_end_at": window_end,
    }
    if conditions is not None:
        payload["conditions"] = list(conditions)
    if cure_days is not None:
        payload["cure_days"] = int(cure_days)
    if notes is not None:
        payload["notes"] = notes
    return payload


def accepted_review_payload(build_id: str, day: str = "2026-08-01",
                            start_hour: int = 9, end_hour: int = 13) -> Dict:
    return review_payload(
        build_id, "ACCEPTED",
        utc_instant(day, start_hour), utc_instant(day, end_hour),
    )


def conditional_review_payload(build_id: str, conditions: List[int],
                               cure_days: int = DEFAULT_CURE_DAYS,
                               day: str = "2026-08-01",
                               start_hour: int = 9, end_hour: int = 13) -> Dict:
    return review_payload(
        build_id, "CONDITIONAL",
        utc_instant(day, start_hour), utc_instant(day, end_hour),
        conditions=conditions, cure_days=cure_days,
    )


def rejected_review_payload(build_id: str, day: str = "2026-08-01",
                            start_hour: int = 9, end_hour: int = 12) -> Dict:
    return review_payload(
        build_id, "REJECTED",
        utc_instant(day, start_hour), utc_instant(day, end_hour),
    )


# --------------------------------------------------------------- change orders
def change_order_payload(agreement_id: str, target_milestone_id: str, order_type: str,
                         expected_agreement_version: int, rationale: str,
                         requested_amount_cents: Optional[int] = None,
                         ship_date_delta_days: Optional[int] = None,
                         content_threshold_relief_pct: Optional[float] = None) -> Dict:
    payload = {
        "agreement_id": agreement_id,
        "target_milestone_id": target_milestone_id,
        "order_type": order_type,
        "rationale": rationale,
        "expected_agreement_version": int(expected_agreement_version),
    }
    if requested_amount_cents is not None:
        payload["requested_amount_cents"] = int(requested_amount_cents)
    if ship_date_delta_days is not None:
        payload["ship_date_delta_days"] = int(ship_date_delta_days)
    if content_threshold_relief_pct is not None:
        payload["content_threshold_relief_pct"] = float(content_threshold_relief_pct)
    return payload


def approve_payload(decision_note: Optional[str] = None) -> Dict:
    payload = {"decision": "APPROVE"}
    if decision_note is not None:
        payload["decision_note"] = decision_note
    return payload


def decline_payload(decision_note: Optional[str] = None) -> Dict:
    payload = {"decision": "DECLINE"}
    if decision_note is not None:
        payload["decision_note"] = decision_note
    return payload


# ----------------------------------------------------------------- outsourcing
def engagement_payload(milestone_id: str, vendor_code: str, committed_cents: int,
                       start_date: str, end_date: str,
                       scope_summary: str = "Outsourced production work") -> Dict:
    return {
        "milestone_id": milestone_id,
        "vendor_code": vendor_code,
        "scope_summary": scope_summary,
        "committed_cents": int(committed_cents),
        "start_date": start_date,
        "end_date": end_date,
    }


def invoice_payload(engagement_id: str, invoice_number: str, amount_cents: int,
                    period_end_date: str, description: Optional[str] = None) -> Dict:
    payload = {
        "engagement_id": engagement_id,
        "invoice_number": invoice_number,
        "amount_cents": int(amount_cents),
        "period_end_date": period_end_date,
    }
    if description is not None:
        payload["description"] = description
    return payload


def approve_invoice_payload() -> Dict:
    return {"decision": "APPROVE"}


def reject_invoice_payload(rejection_reason: Optional[str] = None) -> Dict:
    payload = {"decision": "REJECT"}
    if rejection_reason is not None:
        payload["rejection_reason"] = rejection_reason
    return payload


# --------------------------------------------------------------------- revenue
def revenue_line(platform_code: str, gross_cents: int, returns_cents: int = 0) -> Dict:
    return {
        "platform_code": platform_code,
        "gross_cents": int(gross_cents),
        "returns_cents": int(returns_cents),
    }


def royalty_statement_payload(agreement_id: str, period_label: str,
                              expected_agreement_version: int,
                              revenue_lines: Optional[List[Dict]] = None,
                              recoupable_cost_cents: Optional[int] = None) -> Dict:
    payload = {
        "agreement_id": agreement_id,
        "period_label": period_label,
        "revenue_lines": list(revenue_lines if revenue_lines is not None else []),
        "expected_agreement_version": int(expected_agreement_version),
    }
    if recoupable_cost_cents is not None:
        payload["recoupable_cost_cents"] = int(recoupable_cost_cents)
    return payload


def live_ops_draw_payload(amount_cents: int, memo: Optional[str] = None) -> Dict:
    payload = {"amount_cents": int(amount_cents)}
    if memo is not None:
        payload["memo"] = memo
    return payload
