"""Queue A — non_linear_state_machine: cyclic machines. The disciplinary
rehearing loop (DECIDED -> APPEAL_PENDING -> REHEARING -> HEARING_SCHEDULED ->
DECIDED) and the certification lapse/reentry loop (ACTIVE -> LAPSED -> ACTIVE
with a fresh cycle).
"""
from datetime import datetime, timezone

from test_helpers import (
    advance_clock,
    appeal_case,
    create_candidate,
    create_reentry_application,
    decide_appeal,
    decide_case,
    decide_reentry,
    open_case,
    refresh_certification,
    refresh_case,
    schedule_hearing,
    setup_certified_candidate,
    walk_case_to_decided,
    walk_case_to_hearing_scheduled,
)


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def test_disciplinary_rehearing_cycle(api):
    """PRD §3.9: "`OVERTURNED` sends the case to `REHEARING`, clearing
    `sanction_type`, `findings`, `decided_at`, and `appeal_deadline` and
    incrementing `rehearing_count` (which starts at zero) by one."
    PRD §3.9: "The loop `DECIDED` → `APPEAL_PENDING` → `REHEARING` →
    `HEARING_SCHEDULED` → `DECIDED` is the due-process rehearing cycle, and
    since no sanction has been applied at any point on it, overturning requires
    no compensation."

    Design: Difficulty/non_linear_state_machine/disciplinary_rehearing_cycle
    """
    candidate = create_candidate()
    case = open_case(
        candidate["id"], violation_type="CRIMINAL_CONDUCT",
        description="Misdemeanor reported on renewal disclosure",
    )
    walk_case_to_decided(case["id"], candidate["id"], sanction_type="WARNING")
    appeal_case(case["id"], candidate["id"])

    overturned = decide_appeal(case["id"], "OVERTURNED", rationale="Evidence chain of custody broken")
    assert overturned["status"] == "REHEARING"
    assert overturned["rehearing_count"] == 1
    assert overturned["sanction_type"] is None, "decision fields are cleared on loop-back"
    assert overturned["findings"] is None
    assert overturned["decided_at"] is None

    schedule_hearing(case["id"])
    redecided = decide_case(case["id"], sanction_type="NONE",
                            findings="Not substantiated on rehearing")
    assert redecided["status"] == "DECIDED"
    assert redecided["sanction_type"] == "NONE"


def test_certification_lapse_reentry_cycle(api):
    """PRD §2.5: "Certifications `ACTIVE` whose `expires_on` is earlier than now
    become `LAPSED`."
    PRD §3.7: "Approval reinstates the certification to `ACTIVE` with a
    **fresh** cycle: `expires_on` becomes twenty-four calendar months from the
    reinstatement instant — deliberately not anniversary-preserving, unlike
    recertification — and `lapse_deadline` is recomputed to match."
    PRD §3.7: "a submission on or before the date twelve calendar months after
    expiry receives `TIER_CE_ONLY`".

    A certification issued 2026-09-04 lapses at the 2028-09-15 sweep, takes a
    TIER_CE_ONLY reentry, and its approval reactivates it with a fresh expiry
    anchored to the reinstatement instant (2030-09-15), not the old
    anniversary.

    Design: Difficulty/non_linear_state_machine/certification_lapse_reentry_cycle
    """
    ctx = setup_certified_candidate()
    sweep = advance_clock("2028-09-15T00:00:00Z")
    assert sweep["certifications_lapsed_count"] == 1
    assert refresh_certification(ctx["certification"]["id"])["status"] == "LAPSED"

    reentry = create_reentry_application(
        ctx["candidate"]["id"], ctx["certification"]["id"],
        ce_makeup_hours_claimed=40,
    )
    assert reentry["tier"] == "TIER_CE_ONLY", (
        f"lapse of 11 days is within 12 months, got {reentry['tier']}"
    )

    decide_reentry(reentry["id"], "APPROVED")
    cert = refresh_certification(ctx["certification"]["id"])
    assert cert["status"] == "ACTIVE", "reentry approval cycles LAPSED back to ACTIVE"
    assert _ts(cert["expires_on"]) == _ts("2030-09-15T00:00:00Z"), (
        f"fresh 24-month cycle from the 2028-09-15 reinstatement, got {cert['expires_on']}"
    )
    assert cert["renewed_count"] == 0, "reentry is not a renewal"
