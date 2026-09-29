"""Payload factories — one per write endpoint, request-input fields only.

Money is always sent as an integer number of cents, dates as ISO YYYY-MM-DD
calendar dates, and instants as full ISO 8601 UTC instants. Optional fields are
left out of the defaults so that a caller can observe the documented defaults.
"""
from typing import Any, Dict


def _merge(defaults: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(defaults)
    payload.update(overrides)
    return {k: v for k, v in payload.items() if v is not _OMIT}


class _Omit:
    def __repr__(self):  # pragma: no cover - debugging aid
        return "<omit>"


_OMIT = _Omit()
OMIT = _OMIT


def create_member_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "legal_name": "Acme Industrial Corp",
            "membership_tier": "FULL",
            "home_jurisdiction_code": "FEDERAL",
            "home_district_code": "CA-12",
            "annual_dues_cents": 400_000,
            "dues_year": 2026,
            "restricted_class_size": 25,
        },
        overrides,
    )


def create_committee_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "name": "Federal Tax Policy Committee",
            "jurisdiction_scope": "FEDERAL",
            "quorum_threshold_pct": 60.00,
            "consensus_threshold_pct": 66.67,
        },
        overrides,
    )


def create_seat_payload(member_id: str, **overrides) -> Dict[str, Any]:
    return _merge({"member_id": member_id}, overrides)


def create_policy_position_payload(committee_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "committee_id": committee_id,
            "title": "Support the Manufacturing Tax Credit",
            "jurisdiction_code": "FEDERAL",
            "summary": "The association supports extending the manufacturing tax credit.",
        },
        overrides,
    )


def open_ballot_payload(**overrides) -> Dict[str, Any]:
    return _merge({}, overrides)


def cast_vote_payload(ballot: str = "SUPPORT", **overrides) -> Dict[str, Any]:
    return _merge({"ballot": ballot}, overrides)


def create_registration_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "jurisdiction_code": "FEDERAL",
            "registrant_name": "National Metals Association",
            "coverage_start_date": "2026-01-01",
            "coverage_end_date": "2026-12-31",
        },
        overrides,
    )


def create_activity_payload(
    registration_id: str, position_id: str, **overrides
) -> Dict[str, Any]:
    return _merge(
        {
            "registration_id": registration_id,
            "position_id": position_id,
            "activity_kind": "DIRECT_LOBBYING",
            "activity_date": "2026-07-15",
            "hours": 1.000,
            "expenditure_cents": 100_000,
        },
        overrides,
    )


def void_payload(void_reason: str = "Recorded in error", **overrides) -> Dict[str, Any]:
    return _merge({"void_reason": void_reason}, overrides)


def create_report_payload(
    registration_id: str, expected_registration_version: int, **overrides
) -> Dict[str, Any]:
    return _merge(
        {
            "registration_id": registration_id,
            "period_code": "2026Q3",
            "basis": "METHOD_A",
            "expected_registration_version": expected_registration_version,
        },
        overrides,
    )


def create_campaign_payload(position_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "position_id": position_id,
            "name": "Manufacturing Credit Mobilisation",
            "target_jurisdiction_code": "FEDERAL",
        },
        overrides,
    )


def dispatch_alert_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "target_district_code": "CA-12",
            "target_chamber": "US_HOUSE",
            "message_subject": "Call your representative today",
            "unit_cost_cents": 30_000,
        },
        overrides,
    )


def create_prior_approval_payload(member_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "member_id": member_id,
            "calendar_year": 2026,
            "solicitable_class_size": 5,
            "effective_date": "2026-01-01",
            "expires_at_date": "2026-12-31",
        },
        overrides,
    )


def grant_prior_approval_payload(**overrides) -> Dict[str, Any]:
    return _merge({"authorized_by_name": "Dana Reyes, General Counsel"}, overrides)


def create_candidate_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "name": "Jordan Ellis",
            "office": "US_HOUSE",
            "jurisdiction_code": "FEDERAL",
            "district_code": "CA-12",
            "election_cycle": "2026-GENERAL",
            "incumbency": "INCUMBENT",
            "voting_alignment_pct": 90.00,
            "committee_relevance_score": 80,
        },
        overrides,
    )


def create_fund_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "name": "NMA Political Action Fund",
            "fund_year": 2026,
            "jurisdiction_code": "FEDERAL",
            "min_reserve_cents": 100_000,
        },
        overrides,
    )


def create_receipt_payload(member_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "member_id": member_id,
            "amount_cents": 600_000,
            "received_date": "2026-08-01",
        },
        overrides,
    )


def filing_cycle_payload(**overrides) -> Dict[str, Any]:
    return _merge({"period_code": "2026Q1", "filed_on_date": "2026-04-15"}, overrides)


def create_contribution_payload(
    fund_id: str, candidate_id: str, **overrides
) -> Dict[str, Any]:
    return _merge(
        {
            "fund_id": fund_id,
            "candidate_id": candidate_id,
            "amount_cents": 100_000,
        },
        overrides,
    )
