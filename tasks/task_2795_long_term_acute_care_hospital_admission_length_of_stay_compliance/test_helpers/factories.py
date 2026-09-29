"""
Request payload builders.

Each function returns a valid body for one write endpoint, carrying every required field
and nothing else, and accepts keyword overrides so a test can change exactly the one
value it is probing:

    factories.referring_hospital_payload(hospital_type=HospitalType.CRITICAL_ACCESS)
    factories.discharge_payload(estimated_cost_cents=12000000)

Passing `None` for an optional field omits it from the body altogether, which is how a
test exercises a documented default rather than restating it.

Identifiers that the specification requires to be unique — a hospital `npi`, a patient
`mrn`, a physician `npi`, a `drg_code`, a `label`, a `period_label` — are drawn from
per-process counters, so two calls never collide by accident. Money is always emitted as a
JSON number; a cents figure quoted as a string is a different type and would be refused.
"""

import itertools
from typing import Any, Dict, Optional

from .constants import (
    CRITERIA_SET_A,
    DEFAULT_PROTOCOL_LABEL,
    DRG_207,
    PERIOD_FY2027,
)
from .types import (
    Discipline,
    DischargeDisposition,
    HospitalType,
    InterruptionDestination,
    Payer,
    QueryType,
    ReviewOutcome,
    SbtOutcome,
    Specialty,
    WeaningCloseOutcome,
)

Json = Dict[str, Any]

_npi_counter = itertools.count(1)
_mrn_counter = itertools.count(1)
_drg_counter = itertools.count(1)
_label_counter = itertools.count(1)


def next_npi() -> str:
    """A fresh ten-digit national provider identifier."""
    return "1{:09d}".format(next(_npi_counter))


def next_mrn() -> str:
    """A fresh medical record number, inside the 24-character limit."""
    return "MRN-{:06d}".format(next(_mrn_counter))


def next_drg_code() -> str:
    """A fresh three-digit DRG code."""
    return "{:03d}".format(300 + next(_drg_counter))


def _omit_none(payload: Json) -> Json:
    return {k: v for k, v in payload.items() if v is not None}


# ── Reference data ───────────────────────────────────
def referring_hospital_payload(**overrides: Any) -> Json:
    """A non-colocated acute-care referral source, whose threshold is therefore 25.00."""
    payload: Json = {
        "name": "Metro General",
        "npi": next_npi(),
        "hospital_type": HospitalType.ACUTE_CARE,
        "is_colocated": False,
    }
    payload.update(overrides)
    return _omit_none(payload)


def patient_payload(**overrides: Any) -> Json:
    payload: Json = {
        "mrn": next_mrn(),
        "full_name": "Ada Lovelace",
        "birth_date": "1948-06-15",
        "primary_payer": Payer.MEDICARE_FFS,
    }
    payload.update(overrides)
    return _omit_none(payload)


def physician_payload(**overrides: Any) -> Json:
    """A pulmonologist, which is the specialty a weaning-plan close requires."""
    payload: Json = {
        "npi": next_npi(),
        "full_name": "Dr Pulmo",
        "specialty": Specialty.PULMONOLOGY,
    }
    payload.update(overrides)
    return _omit_none(payload)


def credential_status_payload(credential_status: str) -> Json:
    return {"credential_status": credential_status}


def drg_rate_payload(**overrides: Any) -> Json:
    """The long-stay DRG whose full standard amount is 6,000,000 cents."""
    payload: Json = dict(DRG_207)
    payload.update(overrides)
    return _omit_none(payload)


def criteria_set_payload(**overrides: Any) -> Json:
    """The criteria set the suite screens against unless a test publishes its own."""
    payload: Json = dict(CRITERIA_SET_A)
    payload.update(overrides)
    return _omit_none(payload)


def period_payload(**overrides: Any) -> Json:
    """A cost reporting period bracketing both the clock epoch and the July backdates."""
    payload: Json = dict(PERIOD_FY2027)
    payload.update(overrides)
    return _omit_none(payload)


def next_label(prefix: str = "CS") -> str:
    """A fresh label inside the 40-character limit."""
    return "{}-{:04d}".format(prefix, next(_label_counter))


# ── Referrals ────────────────────────────────────────
PMV_CLINICALS: Json = {
    "vent_hours_at_referral": 240,
    "icu_days_at_referral": 5,
    "wound_stage": 1,
    "wound_count": 0,
    "prior_acute_discharge_at": "2026-06-30T12:00:00Z",
}

WOUND_CLINICALS: Json = {
    "vent_hours_at_referral": 10,
    "icu_days_at_referral": 1,
    "wound_stage": 3,
    "wound_count": 2,
    "prior_acute_discharge_at": "2026-06-30T12:00:00Z",
}

NEITHER_TRACK_CLINICALS: Json = {
    "vent_hours_at_referral": 10,
    "icu_days_at_referral": 1,
    "wound_stage": 1,
    "wound_count": 0,
    "prior_acute_discharge_at": "2026-06-30T12:00:00Z",
}


def referral_payload(
    patient_id: str,
    referring_hospital_id: str,
    drg_rate_id: str,
    expected_patient_version: int,
    clinicals: Optional[Json] = None,
    **overrides: Any
) -> Json:
    """A referral that screens onto the prolonged-mechanical-ventilation track by default.

    `expected_patient_version` is not optional on this endpoint, so it is a positional
    argument here rather than something a test can forget.
    """
    payload: Json = {
        "patient_id": patient_id,
        "referring_hospital_id": referring_hospital_id,
        "drg_rate_id": drg_rate_id,
        "expected_patient_version": expected_patient_version,
    }
    payload.update(dict(PMV_CLINICALS if clinicals is None else clinicals))
    payload.update(overrides)
    return _omit_none(payload)


def submit_info_payload(**fields: Any) -> Json:
    """The screening inputs supplied against a referral awaiting information."""
    return _omit_none(dict(fields))


def admit_payload(
    admitted_at: Optional[str] = None, override_reason: Optional[str] = None
) -> Json:
    """Admission takes only these two inputs, and both are optional."""
    return _omit_none({"admitted_at": admitted_at, "override_reason": override_reason})


# ── Clinical documentation ───────────────────────────
def idt_note_payload(
    discipline: str = Discipline.PHYSICIAN,
    note_text: str = "Interdisciplinary team reviewed the plan of care.",
    goals_documented: Optional[bool] = None,
) -> Json:
    return _omit_none(
        {
            "discipline": discipline,
            "note_text": note_text,
            "goals_documented": goals_documented,
        }
    )


def weaning_plan_payload(
    protocol_label: Optional[str] = None, vent_hours_total: Optional[float] = None
) -> Json:
    """Both inputs are optional: the label defaults and the hour total starts at zero."""
    return _omit_none(
        {"protocol_label": protocol_label, "vent_hours_total": vent_hours_total}
    )


def sbt_payload(
    outcome: str = SbtOutcome.TOLERATED,
    sbt_hours: float = 2,
    vent_hours_since_last: float = 4,
) -> Json:
    return {
        "outcome": outcome,
        "sbt_hours": sbt_hours,
        "vent_hours_since_last": vent_hours_since_last,
    }


def close_plan_payload(outcome: str = WeaningCloseOutcome.VENT_DEPENDENT) -> Json:
    return {"outcome": outcome}


# ── Interruptions, recombination and discharge ───────
def interrupt_payload(
    destination: str = InterruptionDestination.HOME, left_at: Optional[str] = None
) -> Json:
    return _omit_none({"destination": destination, "left_at": left_at})


def recombine_payload(interrupted_parent_stay_id: str) -> Json:
    return {"interrupted_parent_stay_id": interrupted_parent_stay_id}


def discharge_payload(
    discharge_disposition: str = DischargeDisposition.HOME,
    estimated_cost_cents: int = 1000000,
) -> Json:
    """Both inputs are required; the cost is a JSON number of whole cents."""
    return {
        "discharge_disposition": discharge_disposition,
        "estimated_cost_cents": estimated_cost_cents,
    }


# ── Pricing ──────────────────────────────────────────
def reprice_payload(
    expected_stay_version: int,
    recalculation_reason: str = "Coding review re-priced the stay.",
    override_drg_rate_id: Optional[str] = None,
) -> Json:
    return _omit_none(
        {
            "expected_stay_version": expected_stay_version,
            "recalculation_reason": recalculation_reason,
            "override_drg_rate_id": override_drg_rate_id,
        }
    )


def void_payload(void_reason: str = "AUDIT_CORRECTION") -> Json:
    return {"void_reason": void_reason}


# ── Denial risk ──────────────────────────────────────
def issue_query_payload(
    query_type: str = QueryType.IDT_PARTICIPATION,
    prompt_text: str = "Document the interdisciplinary participation for this stay.",
) -> Json:
    return {"query_type": query_type, "prompt_text": prompt_text}


def answer_query_payload(
    response_text: str = "Participation of all four disciplines is documented in the chart.",
) -> Json:
    return {"response_text": response_text}


def resolve_review_payload(
    outcome: str = ReviewOutcome.CLEARED,
    resolution_note: str = "Documentation reviewed and accepted.",
) -> Json:
    return {"outcome": outcome, "resolution_note": resolution_note}
