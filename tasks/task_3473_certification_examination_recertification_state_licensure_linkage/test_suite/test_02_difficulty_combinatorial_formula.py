"""Queue A — combinatorial_formula: pinned evaluation/rounding orders that a
naive reading would get wrong (per-line fee rounding vs round-once;
window-vs-expiry circularity broken by the creation-time snapshot; nested
min/max spill order across CE components).
"""
from datetime import datetime, timezone

from test_helpers import (
    decide_license,
    decide_recert,
    refresh_certification,
    setup_certified_candidate,
    setup_license_context_nremt,
    setup_recert_draft_with_entries,
    setup_submitted_recert,
    submit_recert,
)


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def test_licensure_fee_per_line_rounding_beats_sum_rounding(api):
    """PRD §3.8: "the applicable lines are always the `base_license_fee_cents`,
    plus the `national_verification_surcharge_cents` on the national path or the
    `state_exam_fee_cents` on the state-exam path; `assessed_fee_cents` is their
    sum."
    PRD §3.8: "The `registry_share_cents` is computed line by line — each
    applicable line multiplied by `registry_share_bps_snapshot`, divided by ten
    thousand, and rounded half up to a whole cent — and then summed from those
    per-line amounts."
    PRD §3.8: "The rounding order is pinned: round each line first, then sum;
    summing first and rounding once is not the contract and diverges on
    half-cent lines."

    Two 9990-cent lines at 1500 bps: round_half_up(1498.5) = 1499 per line,
    summed to 2998; the sum-first variant would yield 2997 and is wrong.

    Design: Difficulty/combinatorial_formula/licensure_fee_per_line_rounding_beats_sum_rounding
    """
    ctx = setup_license_context_nremt()
    granted = decide_license(ctx["license_application"]["id"], "GRANTED")
    assert granted["status"] == "GRANTED"
    assert granted["assessed_fee_cents"] == 19980, (
        f"9990 base + 9990 surcharge == 19980, got {granted['assessed_fee_cents']}"
    )
    assert granted["registry_share_cents"] == 2998, (
        f"per-line round_half_up(9990*0.15)=1499 twice sums to 2998, "
        f"got {granted['registry_share_cents']}"
    )


def test_recert_extension_anniversary_preserving(api):
    """PRD §3.6: "Approval extends the certification **anniversary-style**: the
    new `expires_on` is twenty-four calendar months after the pinned
    `cert_expires_on_at_creation`, never measured from the approval date, so
    approving early in the window loses no certified time; `lapse_deadline` is
    recomputed forty-eight calendar months beyond the new expiry,
    `renewed_count` increments by one, and the certification's `version`
    increments — all without any status transition, since the certification
    simply stays `ACTIVE`."

    Approval at 2027-10-15 against an expiry pinned at 2028-09-04 extends to
    2030-09-04 (the anniversary), not to 2029-10-15 (approval date + 24
    months).

    Design: Difficulty/combinatorial_formula/recert_extension_anniversary_preserving
    """
    ctx = setup_submitted_recert()
    assert ctx["recert_application"]["status"] == "SUBMITTED"

    decide_recert(ctx["recert_application"]["id"], "APPROVED")
    cert = refresh_certification(ctx["certification"]["id"])
    assert _ts(cert["expires_on"]) == _ts("2030-09-04T00:00:00Z"), (
        f"anniversary-preserving extension pins expiry to 2030-09-04, "
        f"got {cert['expires_on']}"
    )
    assert _ts(cert["lapse_deadline"]) == _ts("2034-09-04T00:00:00Z"), (
        "lapse_deadline recomputes forty-eight calendar months beyond the new expiry"
    )
    assert cert["renewed_count"] == 1
    assert cert["status"] == "ACTIVE", "renewal mutates expiry without a status transition"


def test_ce_waterfall_spill_rescues_individual_component(api):
    """PRD §3.6: "Spillover is then evaluated in pinned order — national first,
    then local, then individual: the national spill is the amount by which
    claimed national hours exceed `ce_national_min_hours` (zero when they do
    not), and the local spill is the amount by which claimed local hours exceed
    `ce_local_min_hours`."
    PRD §3.6: "The stored results are `national_credited_hours`, the lesser of
    claimed national hours and the national minimum; `local_credited_hours`,
    the lesser of claimed local hours and the local minimum;
    `individual_credited_hours`, the lesser of claimed individual hours plus
    both spills and `ce_individual_min_hours`; and `total_credited_hours`, the
    sum of the three credited figures."

    NATIONAL 30 claimed caps at the 20 minimum and spills 10 into INDIVIDUAL,
    rescuing a portfolio with zero INDIVIDUAL-tagged hours.

    Design: Difficulty/combinatorial_formula/ce_waterfall_spill_rescues_individual_component
    """
    spill_entries = [
        dict(component="NATIONAL", hours=15, delivery_method="IN_PERSON",
             course_code="N1", course_date="2027-10-01", provider_name="AlphaCE"),
        dict(component="NATIONAL", hours=15, delivery_method="IN_PERSON",
             course_code="N2", course_date="2027-10-02", provider_name="BetaCE"),
        dict(component="LOCAL", hours=10, delivery_method="IN_PERSON",
             course_code="L1", course_date="2027-10-03", provider_name="GammaCE"),
    ]
    ctx = setup_recert_draft_with_entries(
        setup_certified_candidate(), model="NCCP", entry_specs=spill_entries,
    )
    submitted = submit_recert(ctx["recert_application"]["id"], ctx["candidate"]["id"])
    assert submitted["national_credited_hours"] == 20, (
        f"30 claimed national hours cap at the 20 minimum, got {submitted['national_credited_hours']}"
    )
    assert submitted["local_credited_hours"] == 10
    assert submitted["individual_credited_hours"] == 10, (
        f"pure spill: 0 tagged + spill_N 10, got {submitted['individual_credited_hours']}"
    )
    assert submitted["total_credited_hours"] == 40
    assert submitted["status"] == "SUBMITTED"
