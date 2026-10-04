"""Request-payload factories — one per write endpoint, input fields only.

Each builder produces a valid payload and lets a test override whatever the case
under test needs to vary; pass ``DROP`` as an override value to omit a key
entirely (for missing-required-field cases). All default datetimes sit at or
after the logical clock's start instant so setups are always reachable.
"""

from .constants import (
    ACTIVATOR_ACTUARY_USER_ID,
    AUTHOR_ACTUARY_USER_ID,
    DEFAULT_ENACTED_ON,
    DEFAULT_EXPOSURE_END,
    DEFAULT_EXPOSURE_START,
    DEFAULT_LICENSE_EFFECTIVE_FROM,
    DEFAULT_LICENSE_VALID_UNTIL,
    DEFAULT_REVIEW_PERIOD_END,
    DEFAULT_REVIEW_PERIOD_START,
    MIN_CALL_COST_CENTS,
    REVIEW_LEAD_USER_ID,
)
from .types import JsonObject


class _Drop(object):
    """Sentinel meaning "omit this key entirely"."""

    def __repr__(self):
        return "<omit>"


DROP = _Drop()


def _merge(base: JsonObject, overrides: JsonObject) -> JsonObject:
    """Overlay overrides onto a base payload; an override of DROP removes the key."""
    payload = dict(base)
    for key, value in overrides.items():
        if value is DROP:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


# --------------------------------------------------------------- logical clock
def clock_payload(to_iso8601: str, **overrides) -> JsonObject:
    """Body for the clock-advance endpoint."""
    return _merge({"to_iso8601": to_iso8601}, overrides)


# ------------------------------------------------------------------ model acts
def model_act_payload(
    model_code: str = "MDL-100",
    version_label: str = "v1",
    **overrides,
) -> JsonObject:
    """A DRAFTING-bound model law; is_core defaults to false per the contract."""
    return _merge(
        {
            "model_code": model_code,
            "version_label": version_label,
            "title": "Model Act " + model_code,
            "act_type": "MODEL_LAW",
            "committee_name": "Standing Committee",
            "is_core": False,
        },
        overrides,
    )


def exposure_draft_payload(
    model_act_id,
    comment_window_start: str = DEFAULT_EXPOSURE_START,
    comment_window_end: str = DEFAULT_EXPOSURE_END,
    **overrides,
) -> JsonObject:
    """A 30-day half-open comment window anchored at the clock start."""
    return _merge(
        {
            "model_act_id": model_act_id,
            "comment_window_start": comment_window_start,
            "comment_window_end": comment_window_end,
        },
        overrides,
    )


def ballot_payload(state_code: str, vote: str = "YEA", **overrides) -> JsonObject:
    return _merge({"state_code": state_code, "vote": vote}, overrides)


# ----------------------------------------------------------------------- states
def state_payload(code: str = "CA", name: str = None, **overrides) -> JsonObject:
    return _merge(
        {"code": code, "name": name if name is not None else "State of " + code},
        overrides,
    )


# -------------------------------------------------------------------- adoptions
def adoption_payload(
    model_act_id,
    state_code: str,
    expected_state_version: int,
    **overrides,
) -> JsonObject:
    """An adoption record carrying its optimistic-concurrency field."""
    return _merge(
        {
            "model_act_id": model_act_id,
            "state_code": state_code,
            "adopted_citation": "Ins. Code " + str(state_code) + " 100",
            "enacted_on": DEFAULT_ENACTED_ON,
            "expected_state_version": expected_state_version,
        },
        overrides,
    )


def certify_payload(variation_class: str = "SUBSTANTIALLY_SIMILAR", **overrides) -> JsonObject:
    return _merge({"variation_class": variation_class}, overrides)


# ---------------------------------------------------------------------- reviews
def review_payload(
    state_id,
    period_start: str = DEFAULT_REVIEW_PERIOD_START,
    period_end: str = DEFAULT_REVIEW_PERIOD_END,
    team_lead_id: str = REVIEW_LEAD_USER_ID,
    self_assessment_compliant: int = 0,
    self_assessment_total: int = 1,
    **overrides,
) -> JsonObject:
    """A MANUAL accreditation review in SCHEDULED-bound shape."""
    return _merge(
        {
            "state_id": state_id,
            "period_start": period_start,
            "period_end": period_end,
            "team_lead_id": team_lead_id,
            "self_assessment_compliant": self_assessment_compliant,
            "self_assessment_total": self_assessment_total,
        },
        overrides,
    )


def findings_payload(
    findings_compliant: int = 18,
    findings_total: int = 20,
    **overrides,
) -> JsonObject:
    """On-site findings; the default 18/20 scores 90.0 (a PASS picture)."""
    return _merge(
        {"findings_compliant": findings_compliant, "findings_total": findings_total},
        overrides,
    )


# --------------------------------------------------------------------- insurers
def insurer_payload(
    naic_code: str = "90001",
    domicile_state_code: str = "CA",
    name: str = None,
    **overrides,
) -> JsonObject:
    base = {
        "naic_code": naic_code,
        "domicile_state_code": domicile_state_code,
    }
    if name is not DROP:
        base["name"] = name if name is not None else "Insurer " + str(naic_code)
    return _merge(base, overrides)


def filing_payload(
    insurer_id,
    expected_insurer_version: int,
    valuation_standard_code: str = "VM-20",
    period_year: int = 2026,
    period_quarter: str = "ANNUAL",
    reported_surplus_cents: int = 4000000,
    asset_risk_cents: int = 1000000,
    underwriting_risk_cents: int = 800000,
    other_risk_cents: int = 600000,
    **overrides,
) -> JsonObject:
    """A DRAFT-bound filing carrying its optimistic-concurrency field."""
    return _merge(
        {
            "insurer_id": insurer_id,
            "period_year": period_year,
            "period_quarter": period_quarter,
            "valuation_standard_code": valuation_standard_code,
            "reported_surplus_cents": reported_surplus_cents,
            "asset_risk_cents": asset_risk_cents,
            "underwriting_risk_cents": underwriting_risk_cents,
            "other_risk_cents": other_risk_cents,
            "expected_insurer_version": expected_insurer_version,
        },
        overrides,
    )


# -------------------------------------------------------------------- producers
def producer_payload(
    npn: str = "P-1",
    full_name: str = None,
    home_state_code: str = "CA",
    **overrides,
) -> JsonObject:
    return _merge(
        {
            "npn": npn,
            "full_name": full_name if full_name is not None else "Producer " + str(npn),
            "home_state_code": home_state_code,
        },
        overrides,
    )


def license_payload(
    producer_id,
    state_code: str = "CA",
    license_class: str = "LIFE",
    effective_from: str = DEFAULT_LICENSE_EFFECTIVE_FROM,
    valid_until: str = DEFAULT_LICENSE_VALID_UNTIL,
    **overrides,
) -> JsonObject:
    """An APPLIED-bound license over a one-year closed window."""
    return _merge(
        {
            "producer_id": producer_id,
            "state_code": state_code,
            "license_class": license_class,
            "effective_from": effective_from,
            "valid_until": valid_until,
        },
        overrides,
    )


# --------------------------------------------------------- market conduct calls
def call_payload(
    call_code: str = "MC-100",
    topic: str = "claims handling",
    total_cost_cents: int = MIN_CALL_COST_CENTS,
    **overrides,
) -> JsonObject:
    """An OPEN-bound data call at exactly the 100000-cent cost floor."""
    return _merge(
        {"call_code": call_code, "topic": topic, "total_cost_cents": total_cost_cents},
        overrides,
    )


def response_payload(
    direct_premium_cents: int = 100000000,
    complaint_count: int = 0,
    **overrides,
) -> JsonObject:
    return _merge(
        {
            "direct_premium_cents": direct_premium_cents,
            "complaint_count": complaint_count,
        },
        overrides,
    )


# ---------------------------------------------------------- valuation standards
def valuation_standard_payload(
    code: str = "VM-20",
    version_label: str = "v2026.1",
    guidance_text: str = "Actuarial guidance",
    **overrides,
) -> JsonObject:
    """A DRAFT-bound standard version. Author/activator ids live in test_users
    (AUTHOR_ACTUARY_USER_ID drafts; ACTIVATOR_ACTUARY_USER_ID activates)."""
    return _merge(
        {"code": code, "version_label": version_label, "guidance_text": guidance_text},
        overrides,
    )


__all__ = [
    "DROP",
    "AUTHOR_ACTUARY_USER_ID",
    "ACTIVATOR_ACTUARY_USER_ID",
    "clock_payload",
    "model_act_payload",
    "exposure_draft_payload",
    "ballot_payload",
    "state_payload",
    "adoption_payload",
    "certify_payload",
    "review_payload",
    "findings_payload",
    "insurer_payload",
    "filing_payload",
    "producer_payload",
    "license_payload",
    "call_payload",
    "response_payload",
    "valuation_standard_payload",
]
