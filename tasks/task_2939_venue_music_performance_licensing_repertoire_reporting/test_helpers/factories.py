"""
Request-body builders for the Venue Music Licensing API.

Two wire-format rules from PRD §2.6 and §2.5 govern every builder here, and
breaking either one turns a business assertion into a request-shape rejection:

* **Money, basis points, counts and capacities go on the wire as JSON
  integers.**  PRD §2.6 types every money field as "an integer number of
  cents", so ``4200000`` is correct and ``"4200000"`` is not.  Every default
  below is an ``int`` literal and every override is passed straight through, so
  a caller who passes an ``int`` gets an ``int`` in the JSON body.
* **Instants are full ISO-8601 instants.**  Every temporal field the PRD types
  as an instant — ``effective_from``, ``requested_term_start``,
  ``window_start`` / ``window_end``, ``period_start`` / ``period_end``,
  ``lookback_start`` / ``lookback_end``, ``performance_datetime`` and the
  clock's ``current_utc`` — is spelled ``YYYY-MM-DDTHH:MM:SSZ`` here, never as
  a bare calendar date.
"""

from typing import Any, Dict, List, Optional, Sequence

from .constants import (
    ASSESSMENT_KIND_INITIAL,
    CLOCK_START_INSTANT,
    DISPOSITION_ACCEPT_FOR_REVIEW,
    DISPOSITION_APPROVE,
    REPORT_DISPOSITION_ACCEPT,
    SHARE_ASCAP_BP,
    SHARE_BMI_BP,
    SHARE_GMR_BP,
    SHARE_SESAC_BP,
    USE_TYPE_LIVE,
    WINDOW_KIND_SEASONAL_EVENT_RIDER,
)

Payload = Dict[str, Any]


def _with(payload: Payload, overrides: Payload) -> Payload:
    """Apply keyword overrides, dropping any key explicitly set to ``None``.

    Passing ``field=None`` removes the field from the body entirely, which is
    how a test exercises an omitted optional field without hand-building a dict.
    """
    merged = dict(payload)
    for key, value in overrides.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


# ─── Societies and repertoire (PRD §3.1) ──────────────────────────────────


def society_payload(
    society_code: str, display_name: str, repertoire_share_bp: int, **overrides: Any
) -> Payload:
    """A performing-rights society filing."""
    return _with(
        {
            "society_code": society_code,
            "display_name": display_name,
            "repertoire_share_bp": int(repertoire_share_bp),
        },
        overrides,
    )


def _society_shorthand(
    society_code: str, display_name: str, repertoire_share_bp: int, overrides: Any
) -> Payload:
    """Build one society filing, letting a caller override the three defaults.

    The three named fields are pulled out of ``overrides`` rather than passed
    positionally, so a test that wants (say) the same ``society_code`` under a
    different ``display_name`` — which PRD §3.1's uniqueness rule is precisely
    about — can say so without colliding with the positional argument.
    """
    return society_payload(
        overrides.pop("society_code", society_code),
        overrides.pop("display_name", display_name),
        overrides.pop("repertoire_share_bp", repertoire_share_bp),
        **overrides,
    )


def bmi_payload(**overrides: Any) -> Payload:
    """BMI at its canonical 4600 bp repertoire share."""
    return _society_shorthand("BMI", "Broadcast Music Inc", SHARE_BMI_BP, overrides)


def ascap_payload(**overrides: Any) -> Payload:
    """ASCAP at its canonical 4400 bp repertoire share."""
    return _society_shorthand(
        "ASCAP", "American Society of Composers", SHARE_ASCAP_BP, overrides
    )


def sesac_payload(**overrides: Any) -> Payload:
    """SESAC at its canonical 500 bp repertoire share."""
    return _society_shorthand(
        "SESAC", "SESAC Performing Rights", SHARE_SESAC_BP, overrides
    )


def gmr_payload(**overrides: Any) -> Payload:
    """GMR at a 500 bp repertoire share."""
    return _society_shorthand("GMR", "Global Music Rights", SHARE_GMR_BP, overrides)


def repertoire_work_payload(
    society_id: str,
    title: str,
    writer_name: str,
    iswc: Optional[str] = None,
    **overrides: Any,
) -> Payload:
    """A registry row binding one work title and writer to one society."""
    payload: Payload = {
        "society_id": society_id,
        "title": title,
        "writer_name": writer_name,
    }
    if iswc is not None:
        payload["iswc"] = iswc
    return _with(payload, overrides)


# ─── Rate schedules (PRD §3.2) ────────────────────────────────────────────


def rate_schedule_payload(
    society_id: str,
    venue_category: str,
    effective_from: str = "2026-01-01T00:00:00Z",
    **overrides: Any,
) -> Payload:
    """A DRAFT rate schedule for one society and venue category.

    ``adjustment_bp``, ``min_annual_fee_cents``, ``max_annual_fee_cents`` and
    ``rate_court_order_ref`` are left out so the server applies its declared
    defaults; pass them as overrides to pin them explicitly.
    """
    return _with(
        {
            "society_id": society_id,
            "venue_category": venue_category,
            "effective_from": effective_from,
        },
        overrides,
    )


# ─── Venues (PRD §3.3) ────────────────────────────────────────────────────


def venue_payload(
    legal_name: str,
    venue_category: str,
    seating_capacity: int,
    standing_capacity: int,
    occupancy_limit: int,
    music_use_profile: str,
    weekly_live_performance_nights: int,
    annual_cover_revenue_cents: int,
    **overrides: Any,
) -> Payload:
    """A venue survey record.

    The eight positional fields are the ones the PRD requires on creation; the
    background-music survey fields (``gross_square_feet``, ``speaker_count``,
    ``max_speakers_per_room``, ``has_cover_charge``, ``retransmission_only``,
    ``uses_licensed_bgm_service``, ``bgm_service_provider``) are optional and
    are supplied as overrides only by the tests that analyse an exemption.
    """
    return _with(
        {
            "legal_name": legal_name,
            "venue_category": venue_category,
            "seating_capacity": int(seating_capacity),
            "standing_capacity": int(standing_capacity),
            "occupancy_limit": int(occupancy_limit),
            "music_use_profile": music_use_profile,
            "weekly_live_performance_nights": int(weekly_live_performance_nights),
            "annual_cover_revenue_cents": int(annual_cover_revenue_cents),
        },
        overrides,
    )


def bar_grill_venue_payload(legal_name: str = "Blue Note Grill", **overrides: Any) -> Payload:
    """A BAR_GRILL of occupancy 180, MIXED use, 4 live nights, 4200000 cents cover.

    Occupancy is the greater of seating 120 and standing 180, which lands this
    venue in the second occupancy tier; the resulting verified annual fee for a
    4600 bp society on a default schedule is 90017 cents.
    """
    return venue_payload(
        legal_name,
        "BAR_GRILL",
        120,
        180,
        200,
        "MIXED",
        4,
        4200000,
        **overrides,
    )


def concert_hall_venue_payload(
    legal_name: str = "Harbor Concert Hall", **overrides: Any
) -> Payload:
    """A CONCERT_HALL of occupancy 1200, LIVE_ONLY, 5 live nights, 62000000 cover.

    The top occupancy tier; the verified annual fee for a 4600 bp society on a
    default schedule is 1335461 cents.
    """
    return venue_payload(
        legal_name,
        "CONCERT_HALL",
        1200,
        0,
        1300,
        "LIVE_ONLY",
        5,
        62000000,
        **overrides,
    )


def mid_concert_hall_venue_payload(
    legal_name: str = "Harbourfront Concert Hall", **overrides: Any
) -> Payload:
    """A CONCERT_HALL of occupancy 800, LIVE_ONLY, 3 live nights, 10000000 cover.

    The fourth occupancy tier begins above 750, so this venue sits just inside
    it; the verified annual fee for a 4600 bp society is 463761 cents.
    """
    return venue_payload(
        legal_name,
        "CONCERT_HALL",
        800,
        0,
        900,
        "LIVE_ONLY",
        3,
        10000000,
        **overrides,
    )


def fitness_studio_venue_payload(
    legal_name: str = "Riverbend Fitness Studio", **overrides: Any
) -> Payload:
    """A FITNESS_STUDIO of occupancy 40, BACKGROUND_ONLY, no live nights, no cover.

    Every fee input is at its smallest, so the derived fee falls below the
    schedule's minimum annual fee and the clamp becomes observable.
    """
    return venue_payload(
        legal_name,
        "FITNESS_STUDIO",
        0,
        40,
        45,
        "BACKGROUND_ONLY",
        0,
        0,
        **overrides,
    )


def bgm_survey_fields(
    gross_square_feet: int = 1800,
    speaker_count: int = 6,
    max_speakers_per_room: int = 4,
    has_cover_charge: bool = False,
    retransmission_only: bool = True,
    **overrides: Any,
) -> Payload:
    """The background-music survey block, defaulted to satisfy every size test.

    These defaults sit inside both the floor-area limit and the two speaker
    limits and declare a retransmission-only, cover-charge-free operation, so a
    test that wants one clause of the exemption ladder to fail overrides exactly
    that one field.
    """
    return _with(
        {
            "gross_square_feet": int(gross_square_feet),
            "speaker_count": int(speaker_count),
            "max_speakers_per_room": int(max_speakers_per_room),
            "has_cover_charge": bool(has_cover_charge),
            "retransmission_only": bool(retransmission_only),
        },
        overrides,
    )


# ─── Licence applications (PRD §3.4) ──────────────────────────────────────


def application_payload(
    venue_id: str,
    society_id: str,
    requested_license_type: str,
    declared_seating: int,
    declared_standing: int,
    declared_cover_revenue_cents: int,
    declared_live_nights: int,
    declared_music_use_profile: str,
    requested_term_start: str,
    expected_venue_version: Optional[int] = None,
    **overrides: Any,
) -> Payload:
    """A licence application carrying the operator's self-declared inputs."""
    payload: Payload = {
        "venue_id": venue_id,
        "society_id": society_id,
        "requested_license_type": requested_license_type,
        "declared_seating": int(declared_seating),
        "declared_standing": int(declared_standing),
        "declared_cover_revenue_cents": int(declared_cover_revenue_cents),
        "declared_live_nights": int(declared_live_nights),
        "declared_music_use_profile": declared_music_use_profile,
        "requested_term_start": requested_term_start,
    }
    if expected_venue_version is not None:
        payload["expected_venue_version"] = int(expected_venue_version)
    return _with(payload, overrides)


def matching_application_payload(
    venue: Dict[str, Any],
    society_id: str,
    requested_term_start: str = "2026-09-01T00:00:00Z",
    requested_license_type: str = "BLANKET",
    **overrides: Any,
) -> Payload:
    """An application whose declarations mirror the venue's verified survey.

    Copying the venue row's own capacity and use figures is what makes the
    provisional fee and the verified fee agree, so any divergence a test then
    observes comes from the field it deliberately changed.
    """
    return application_payload(
        venue["id"],
        society_id,
        requested_license_type,
        venue["seating_capacity"],
        venue["standing_capacity"],
        venue["annual_cover_revenue_cents"],
        venue["weekly_live_performance_nights"],
        venue["music_use_profile"],
        requested_term_start,
        expected_venue_version=overrides.pop(
            "expected_venue_version", venue["version"]
        ),
        **overrides,
    )


def review_payload(
    disposition: str = DISPOSITION_ACCEPT_FOR_REVIEW,
    return_reason: Optional[str] = None,
    decline_reason: Optional[str] = None,
    **overrides: Any,
) -> Payload:
    """A review decision on an application."""
    payload: Payload = {"disposition": disposition}
    if return_reason is not None:
        payload["return_reason"] = return_reason
    if decline_reason is not None:
        payload["decline_reason"] = decline_reason
    return _with(payload, overrides)


def approve_payload(**overrides: Any) -> Payload:
    """The approving review disposition."""
    return review_payload(DISPOSITION_APPROVE, **overrides)


# ─── Licences, terms and riders (PRD §3.6, §3.7) ───────────────────────────


def suspend_payload(suspension_reason: str, **overrides: Any) -> Payload:
    """A suspension carrying its recorded reason."""
    return _with({"suspension_reason": suspension_reason}, overrides)


def terminate_payload(void_unpaid_assessments: bool = False, **overrides: Any) -> Payload:
    """A termination, optionally voiding the licence's unpaid assessments."""
    return _with(
        {"void_unpaid_assessments": bool(void_unpaid_assessments)}, overrides
    )


def renew_payload(
    requested_term_start: str,
    expected_license_version: Optional[int] = None,
    **overrides: Any,
) -> Payload:
    """A renewal request for a successor term."""
    payload: Payload = {"requested_term_start": requested_term_start}
    if expected_license_version is not None:
        payload["expected_license_version"] = int(expected_license_version)
    return _with(payload, overrides)


def coverage_window_payload(
    window_start: str,
    window_end: str,
    window_kind: str = WINDOW_KIND_SEASONAL_EVENT_RIDER,
    **overrides: Any,
) -> Payload:
    """A rider coverage window over a half-open interval inside the term."""
    return _with(
        {
            "window_kind": window_kind,
            "window_start": window_start,
            "window_end": window_end,
        },
        overrides,
    )


# ─── Performance reports and setlists (PRD §3.8) ───────────────────────────


def performance_report_payload(
    license_id: str,
    period_start: str = "2026-09-01T00:00:00Z",
    period_end: str = "2026-10-01T00:00:00Z",
    **overrides: Any,
) -> Payload:
    """A DRAFT performance report over one reporting period."""
    return _with(
        {
            "license_id": license_id,
            "period_start": period_start,
            "period_end": period_end,
        },
        overrides,
    )


def setlist_entry_payload(
    work_title: str,
    writer_name: str,
    society_affiliation: str,
    performance_datetime: str,
    duration_seconds: int,
    use_type: str = USE_TYPE_LIVE,
    **overrides: Any,
) -> Payload:
    """One performance of one work inside a report's period."""
    return _with(
        {
            "work_title": work_title,
            "writer_name": writer_name,
            "society_affiliation": society_affiliation,
            "performance_datetime": performance_datetime,
            "use_type": use_type,
            "duration_seconds": int(duration_seconds),
        },
        overrides,
    )


def report_review_payload(
    disposition: str = REPORT_DISPOSITION_ACCEPT,
    rejection_reason: Optional[str] = None,
    **overrides: Any,
) -> Payload:
    """A review decision on a submitted performance report."""
    payload: Payload = {"disposition": disposition}
    if rejection_reason is not None:
        payload["rejection_reason"] = rejection_reason
    return _with(payload, overrides)


# ─── Audit cases, settlement and payment (PRD §3.9) ────────────────────────


def audit_case_payload(
    venue_id: str,
    audit_trigger: str,
    lookback_start: str,
    lookback_end: str,
    society_ids: Sequence[str],
    **overrides: Any,
) -> Payload:
    """An audit case over a half-open lookback interval and a set of societies."""
    return _with(
        {
            "venue_id": venue_id,
            "audit_trigger": audit_trigger,
            "lookback_start": lookback_start,
            "lookback_end": lookback_end,
            "society_ids": list(society_ids),
        },
        overrides,
    )


def close_case_payload(closed_reason: str, **overrides: Any) -> Payload:
    """A no-action closure carrying its recorded reason."""
    return _with({"closed_reason": closed_reason}, overrides)


def settlement_offer_payload(
    offer_amount_cents: int,
    payment_plan_months: Optional[int] = None,
    **overrides: Any,
) -> Payload:
    """A settlement offer at or above the case's settlement floor."""
    payload: Payload = {"offer_amount_cents": int(offer_amount_cents)}
    if payment_plan_months is not None:
        payload["payment_plan_months"] = int(payment_plan_months)
    return _with(payload, overrides)


def payment_payload(amount_cents: int, **overrides: Any) -> Payload:
    """A payment against one issued assessment."""
    return _with({"amount_cents": int(amount_cents)}, overrides)


# ─── The logical clock (PRD §2.4) ─────────────────────────────────────────


def clock_payload(current_utc: str = CLOCK_START_INSTANT, **overrides: Any) -> Payload:
    """A replacement value for the server-held logical clock instant."""
    return _with({"current_utc": current_utc}, overrides)


# ─── Convenience: setlist families ────────────────────────────────────────


def setlist_family(entries: Sequence[Dict[str, Any]]) -> List[Payload]:
    """Turn a compact tuple-style description of a setlist into payloads.

    Each element must carry ``title``, ``writer``, ``affiliation``, ``when``,
    ``seconds`` and optionally ``use_type``; the result is ready to POST one
    element at a time.
    """
    built: List[Payload] = []
    for entry in entries:
        built.append(
            setlist_entry_payload(
                entry["title"],
                entry["writer"],
                entry["affiliation"],
                entry["when"],
                entry["seconds"],
                entry.get("use_type", USE_TYPE_LIVE),
            )
        )
    return built


INITIAL_ASSESSMENT_KIND = ASSESSMENT_KIND_INITIAL
