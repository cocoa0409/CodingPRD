"""
Request payload factories for the Building Trades Hiring Hall Dispatch API.

Each builder returns the payload the PRD declares for that operation, with
sensible valid defaults, and merges caller overrides last. Derived builders
merge their own specialisation into the override mapping rather than passing a
keyword twice, so a caller may override any field of any builder.

Money and hours are always JSON numbers (§2.9) and every instant is a full ISO
8601 UTC value with three fractional digits (§2.4).
"""

from typing import Any, Dict, List, Optional

from .constants import (
    CLAIM_OUT_OF_ORDER_DISPATCH,
    CLASSIFICATION_APPRENTICE,
    CLASSIFICATION_JOURNEYWORKER,
    DECISION_DENIED,
    GROUP_1,
    GROUP_2,
    GROUP_3,
    GROUP_4,
    LAYOFF_LACK_OF_WORK,
    LOCAL_KIND_HOME,
    LOCAL_KIND_SISTER,
    ORDERING_FIRST_REGISTERED,
    ORDERING_SENIORITY,
    REFERRAL_KIND_LIST_ORDER,
    REFERRAL_KIND_NAMED_CALL,
    REFERRAL_KIND_SPECIAL_SKILL,
    REMEDY_NONE,
    REMOVAL_VOLUNTARY,
    SIGNATORY,
    SKILL_WELDING_6G,
    SLOT_APPRENTICE,
    SLOT_JOURNEYWORKER,
    STANDING_GOOD,
)

# The instant the fixtures park the logical hall clock at before doing anything.
# Chosen so that every window opened in setup is comfortably inside its bounds.
DEFAULT_TEST_CLOCK = "2026-09-01T00:00:00.000Z"
DEFAULT_AGREEMENT_EXPIRY = "2027-06-30T00:00:00.000Z"
DEFAULT_POLICY_EFFECTIVE_FROM = "2026-01-01T00:00:00.000Z"
DEFAULT_REPORT_AT = "2026-09-25T07:00:00.000Z"


# ─── Logical clock (§2.5) ─────────────────────────────────────────────────────


def clock_payload(current_utc: str = DEFAULT_TEST_CLOCK, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"current_utc": current_utc}
    payload.update(overrides)
    return payload


# ─── Locals (§3.1) ────────────────────────────────────────────────────────────


def local_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "local_number": 512,
        "name": "Local 512 (home)",
        "kind": LOCAL_KIND_HOME,
        "reciprocity_factor_bp": 0,
    }
    payload.update(overrides)
    return payload


def home_local_payload(**overrides) -> Dict[str, Any]:
    return local_payload(**{"kind": LOCAL_KIND_HOME, **overrides})


def sister_local_payload(**overrides) -> Dict[str, Any]:
    """A sister local whose reciprocity factor credits half the traveler's hours."""
    return local_payload(
        **{
            "local_number": 46,
            "name": "Local 46 (sister)",
            "kind": LOCAL_KIND_SISTER,
            "reciprocity_factor_bp": 5000,
            **overrides,
        }
    )


# ─── Out-of-work list groups (§3.2) ───────────────────────────────────────────


def out_of_work_list_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "group_code": GROUP_1,
        "priority_rank": 1,
        "ordering_policy": ORDERING_SENIORITY,
        "requires_local_hours": 4000,
        "accepts_travelers": False,
    }
    payload.update(overrides)
    return payload


def group_one_payload(**overrides) -> Dict[str, Any]:
    """Rank 1, seniority ordered, a 4,000-hour floor and no travelers."""
    return out_of_work_list_payload(
        **{
            "group_code": GROUP_1,
            "priority_rank": 1,
            "ordering_policy": ORDERING_SENIORITY,
            "requires_local_hours": 4000,
            "accepts_travelers": False,
            **overrides,
        }
    )


def group_two_payload(**overrides) -> Dict[str, Any]:
    return out_of_work_list_payload(
        **{
            "group_code": GROUP_2,
            "priority_rank": 2,
            "ordering_policy": ORDERING_SENIORITY,
            "requires_local_hours": 2000,
            "accepts_travelers": False,
            **overrides,
        }
    )


def group_three_payload(**overrides) -> Dict[str, Any]:
    return out_of_work_list_payload(
        **{
            "group_code": GROUP_3,
            "priority_rank": 3,
            "ordering_policy": ORDERING_FIRST_REGISTERED,
            "requires_local_hours": 0,
            "accepts_travelers": False,
            **overrides,
        }
    )


def group_four_payload(**overrides) -> Dict[str, Any]:
    """Rank 4, the traveler-admitting group with no hours floor."""
    return out_of_work_list_payload(
        **{
            "group_code": GROUP_4,
            "priority_rank": 4,
            "ordering_policy": ORDERING_SENIORITY,
            "requires_local_hours": 0,
            "accepts_travelers": True,
            **overrides,
        }
    )


# ─── Ratio policies (§3.6) ────────────────────────────────────────────────────


def ratio_policy_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "policy_code": "STD-2026",
        "first_apprentice_at_jw_count": 1,
        "then_every_n_jw": 4,
        "effective_from": DEFAULT_POLICY_EFFECTIVE_FROM,
    }
    payload.update(overrides)
    return payload


# ─── Members and endorsements (§3.1) ──────────────────────────────────────────


def member_payload(home_local_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": "Ana Cortes",
        "home_local_id": home_local_id,
        "classification": CLASSIFICATION_JOURNEYWORKER,
        "local_hours_in_trade": 9000,
    }
    payload.update(overrides)
    return payload


def journeyworker_payload(home_local_id: str, **overrides) -> Dict[str, Any]:
    return member_payload(
        home_local_id,
        **{"classification": CLASSIFICATION_JOURNEYWORKER, **overrides},
    )


def apprentice_payload(home_local_id: str, **overrides) -> Dict[str, Any]:
    """An apprentice must declare `apprentice_period`; a journeyworker must not."""
    return member_payload(
        home_local_id,
        **{
            "full_name": "Dee Kwan",
            "classification": CLASSIFICATION_APPRENTICE,
            "apprentice_period": 2,
            "local_hours_in_trade": 500,
            **overrides,
        },
    )


def standing_payload(standing: str = STANDING_GOOD, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"standing": standing}
    payload.update(overrides)
    return payload


def skill_endorsement_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "skill_code": SKILL_WELDING_6G,
        "certified_until": "2027-01-01T00:00:00.000Z",
        "verified": True,
    }
    payload.update(overrides)
    return payload


# ─── Registrations (§3.3, §3.4) ───────────────────────────────────────────────


def reciprocity_credit(sister_local_id: str, raw_hours: int) -> Dict[str, Any]:
    """One entry of the `reciprocity_credits` array; `raw_hours` is a JSON number."""
    return {"sister_local_id": sister_local_id, "raw_hours": raw_hours}


def registration_payload(member_id: str, list_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"member_id": member_id, "list_id": list_id}
    payload.update(overrides)
    return payload


def traveler_registration_payload(
    member_id: str, list_id: str, credits: List[Dict[str, Any]], **overrides
) -> Dict[str, Any]:
    return registration_payload(
        member_id, list_id, **{"reciprocity_credits": credits, **overrides}
    )


def preserving_registration_payload(
    member_id: str, list_id: str, predecessor_registration_id: str, **overrides
) -> Dict[str, Any]:
    return registration_payload(
        member_id,
        list_id,
        **{
            "predecessor_registration_id": predecessor_registration_id,
            "claim_position_preservation": True,
            **overrides,
        },
    )


def removal_payload(reason: str = REMOVAL_VOLUNTARY, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload


# ─── Contractors (§3.5) ───────────────────────────────────────────────────────


def contractor_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": "Northline Mechanical",
        "agreement_expires_at": DEFAULT_AGREEMENT_EXPIRY,
        "signatory_status": SIGNATORY,
    }
    payload.update(overrides)
    return payload


def signatory_status_payload(signatory_status: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"signatory_status": signatory_status}
    payload.update(overrides)
    return payload


# ─── Job requests (§3.5) ──────────────────────────────────────────────────────


def job_request_payload(contractor_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "contractor_id": contractor_id,
        "job_site": "Feedwater Skid",
        "journeyworkers_requested": 1,
        "apprentices_requested": 0,
        "expected_duration_days": 20,
        "report_at": DEFAULT_REPORT_AT,
        "hourly_rate_cents": 5000,
    }
    payload.update(overrides)
    return payload


def long_call_payload(contractor_id: str, **overrides) -> Dict[str, Any]:
    """`expected_duration_days` above the 5-day ceiling makes this a long call."""
    return job_request_payload(
        contractor_id, **{"expected_duration_days": 20, **overrides}
    )


def short_call_payload(contractor_id: str, **overrides) -> Dict[str, Any]:
    """`expected_duration_days` of 5 or fewer makes this a short call."""
    return job_request_payload(
        contractor_id,
        **{"job_site": "Turbine Deck Patch", "expected_duration_days": 5, **overrides},
    )


def cancel_payload(reason: str = "Owner pulled the scope.", **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload


# ─── Referrals (§3.6, §3.7) ───────────────────────────────────────────────────


def referral_payload(expected_job_request_version: int, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "slot_kind": SLOT_JOURNEYWORKER,
        "referral_kind": REFERRAL_KIND_LIST_ORDER,
        "expected_job_request_version": expected_job_request_version,
    }
    payload.update(overrides)
    return payload


def list_order_referral_payload(
    expected_job_request_version: int, **overrides
) -> Dict[str, Any]:
    return referral_payload(
        expected_job_request_version,
        **{"referral_kind": REFERRAL_KIND_LIST_ORDER, **overrides},
    )


def named_call_referral_payload(
    expected_job_request_version: int, member_id: str, **overrides
) -> Dict[str, Any]:
    return referral_payload(
        expected_job_request_version,
        **{
            "referral_kind": REFERRAL_KIND_NAMED_CALL,
            "member_id": member_id,
            **overrides,
        },
    )


def special_skill_referral_payload(
    expected_job_request_version: int, **overrides
) -> Dict[str, Any]:
    return referral_payload(
        expected_job_request_version,
        **{"referral_kind": REFERRAL_KIND_SPECIAL_SKILL, **overrides},
    )


def apprentice_referral_payload(
    expected_job_request_version: int, **overrides
) -> Dict[str, Any]:
    return referral_payload(
        expected_job_request_version, **{"slot_kind": SLOT_APPRENTICE, **overrides}
    )


def refusal_payload(good_cause: Optional[str] = None, **overrides) -> Dict[str, Any]:
    """
    Omitting `refusal_good_cause_code` leaves it null and makes the refusal a
    bare turn-down, which is what charges a strike.
    """
    payload: Dict[str, Any] = {}
    if good_cause is not None:
        payload["refusal_good_cause_code"] = good_cause
    payload.update(overrides)
    return payload


def withdraw_payload(reason: str = "Dispatcher error at the counter.", **overrides
                     ) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload


# ─── Dispatches (§3.8) ────────────────────────────────────────────────────────


def layoff_payload(hours_worked: int = 40, layoff_reason: str = LAYOFF_LACK_OF_WORK,
                    **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "hours_worked": hours_worked,
        "layoff_reason": layoff_reason,
    }
    payload.update(overrides)
    return payload


def recall_payload(report_at: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"report_at": report_at}
    payload.update(overrides)
    return payload


# ─── Grievances (§3.9) ────────────────────────────────────────────────────────


def grievance_payload(referral_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "referral_id": referral_id,
        "claim_type": CLAIM_OUT_OF_ORDER_DISPATCH,
        "narrative": "The dispatcher reached past me on the rank-one list.",
    }
    payload.update(overrides)
    return payload


def adjudication_payload(decision: str = DECISION_DENIED, remedy: str = REMEDY_NONE,
                          **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision, "remedy": remedy}
    payload.update(overrides)
    return payload
