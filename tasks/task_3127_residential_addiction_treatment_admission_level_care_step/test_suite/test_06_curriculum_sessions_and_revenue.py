"""The weekly curriculum, the attendance ledger and professional revenue."""

import pytest

from test_helpers import (
    C,
    CLINICAL_DIRECTOR_HEADERS,
    ApiErrorId,
    list_episode_sessions,
    read_episode,
    record_attendance,
    schedule_session,
    set_clock,
    setup_admitted_episode,
    setup_curriculum_episode,
    setup_site,
    validate_error,
    validate_success,
)


def test_attendance_computes_the_session_fee_from_duration_units(api):
    """
    PRD §3.4: "computes `billing_amount_cents` from the service level and duration, and
    recomputes the episode's `therapy_revenue_cents`." PRD §2.10: "The per-row
    `billing_amount_cents` is the base fee for the service's `level_of_care` multiplied by the
    session's billed hour units, where the hour units are the session's `duration_minutes`
    divided by 60 with the remainder discarded, floored at a minimum of 1, and the product is
    capped at 900 cents for the row." PRD §2.10: "The base fees are 210 cents at `ASAM_3_7`, 180
    at `ASAM_3_5`"

    Design: Corner/calculations/session_billing_applies_the_duration_multiplier_once_per_row
    """
    site = setup_site()
    setup = setup_admitted_episode(site=site)

    ninety = schedule_session(site, setup.id, duration_minutes=90)
    ninety = record_attendance(site, ninety["id"], attended=True)
    assert ninety["billing_amount_cents"] == 180, (
        "90 // 60 is 1 unit, and the ASAM_3_5 base fee is 180 cents"
    )

    one_eighty = schedule_session(
        site, setup.id, scheduled_at="2026-09-02T11:00:00Z", duration_minutes=180
    )
    one_eighty = record_attendance(site, one_eighty["id"], attended=True)
    assert one_eighty["billing_amount_cents"] == 540, (
        "180 // 60 is 3 units at the ASAM_3_5 base fee of 180 cents"
    )

    capped = schedule_session(
        site, setup.id, scheduled_at="2026-09-02T12:00:00Z", duration_minutes=600
    )
    capped = record_attendance(site, capped["id"], attended=True)
    assert capped["billing_amount_cents"] == 900, (
        "600 // 60 is 10 units, whose 1800-cent product is truncated by the 900-cent row cap"
    )


def test_a_no_show_row_bills_nothing_and_a_cancel_retains_the_row(api):
    """PRD §2.10: "A row bills 0 whenever its status is not `ATTENDED` — a cancelled or
    no-show row contributes nothing."
    PRD §3.4: "A `Clinician` may also cancel a scheduled session; the row is retained and
    becomes `CANCELLED` with a billed amount of 0, never deleted."

    Design: Corner/validations/curriculum_check_is_an_aggregate_over_the_whole_treatment_week
    """
    site = setup_site()
    setup = setup_admitted_episode(site=site)

    no_show = schedule_session(site, setup.id)
    no_show = record_attendance(site, no_show["id"], attended=False)
    assert no_show["status"] == "NO_SHOW"
    assert no_show["billing_amount_cents"] == 0

    planned = schedule_session(site, setup.id, scheduled_at="2026-09-02T11:00:00Z")
    cancelled = validate_success(
        api.cancel_session(site.id, planned["id"], {}, site.clinician_headers), 200
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["billing_amount_cents"] == 0

    rows, _ = list_episode_sessions(site.id, setup.id, limit=100)
    ids = [row["id"] for row in rows]
    assert cancelled["id"] in ids, "a cancelled row is retained, never deleted"
    assert no_show["id"] in ids


def test_the_weekly_attendance_aggregate_meets_the_asam_3_5_requirement(api):
    """PRD §3.4: "A patient at `ASAM_3_5` or `ASAM_3_7` is expected to attend 14."
    PRD §3.4: "The curriculum is compliant when that attended count reaches the level's
    requirement exactly or exceeds it; one short is not compliant."

    Design: Difficulty/boundary_precision_check/boundary_curriculum_exact_requirement_plus_clearance_zero
    """
    site = setup_site()
    setup = setup_curriculum_episode(site=site, attended_sessions=14, clock="2026-09-02T00:00:00Z")

    rows, _ = list_episode_sessions(site.id, setup.id, limit=100)
    attended = [r for r in rows if r["status"] == "ATTENDED"]
    assert len(attended) == 14, "exactly the ASAM_3_5 requirement"

    raw = api.complete_treatment(site.id, setup.id, {}, CLINICAL_DIRECTOR_HEADERS)
    assert raw.status_code == 200, (
        f"attended == required_sessions_per_week is compliant at the boundary: {raw.text}"
    )
    assert raw.json()["data"]["clinical_status"] == "COMPLETED"


def test_one_session_short_of_the_requirement_blocks_completion(api):
    """PRD §3.4: "The curriculum is compliant when that attended count reaches the level's
    requirement exactly or exceeds it; one short is not compliant."
    PRD §3.7: "the episode must have attended at least the level's `required_sessions_per_week`
    sessions in the current treatment week, or the request fails with `ERR_CURRICULUM_NOT_COMPLETE`."

    Design: Difficulty/boundary_precision_check/boundary_curriculum_exact_requirement_plus_clearance_zero
    """
    site = setup_site()
    setup = setup_curriculum_episode(site=site, attended_sessions=13, clock="2026-09-02T00:00:00Z")

    rows, _ = list_episode_sessions(site.id, setup.id, limit=100)
    assert len([r for r in rows if r["status"] == "ATTENDED"]) == 13
    assert len([r for r in rows if r["status"] == "ATTENDED"]) != 14

    response = api.complete_treatment(site.id, setup.id, {}, CLINICAL_DIRECTOR_HEADERS)
    validate_error(response, ApiErrorId.ERR_CURRICULUM_NOT_COMPLETE)


def test_a_no_show_counts_toward_the_ledger_but_not_the_requirement(api):
    """
    PRD §3.4: "Within the current week, attended sessions are counted from the rows whose status
    is `ATTENDED` and whose `scheduled_at` falls inside the window." PRD §3.7: "And the episode
    must have attended at least the level's `required_sessions_per_week` sessions in the current
    treatment week, or the request fails with `ERR_CURRICULUM_NOT_COMPLETE`."

    Design: Corner/validations/curriculum_check_is_an_aggregate_over_the_whole_treatment_week
    """
    site = setup_site()
    setup = setup_curriculum_episode(site=site, attended_sessions=13, clock="2026-09-02T00:00:00Z")

    no_show = schedule_session(site, setup.id, scheduled_at="2026-09-02T20:00:00Z")
    no_show = record_attendance(site, no_show["id"], attended=False)
    assert no_show["status"] == "NO_SHOW"

    rows, _ = list_episode_sessions(site.id, setup.id, limit=100)
    assert len(rows) == 14, "the NO_SHOW row is a ledger entry"
    assert len([r for r in rows if r["status"] == "ATTENDED"]) == 13, (
        "but it does not count toward the week's requirement"
    )

    response = api.complete_treatment(site.id, setup.id, {}, CLINICAL_DIRECTOR_HEADERS)
    validate_error(response, ApiErrorId.ERR_CURRICULUM_NOT_COMPLETE)


def test_invalidating_a_plan_conserves_the_attendance_ledger(api):
    """PRD §2.10: "The episode's attendance ledger counts every `SessionAttendance` row ever
    created for it, and that count must always equal the sum of the rows in `SCHEDULED`,
    `ATTENDED`, `NO_SHOW` and `CANCELLED` status."
    PRD §2.10: "When a plan is forced back to `PENDING_COSIGN` by an accreditation revocation
    during a facility-ops run, every `SCHEDULED` session row is rewritten to `CANCELLED` and a
    replacement row is scheduled for each, carrying the new plan's version."

    Design: Difficulty/compensating_invariant/invariant_session_ledger_entries_conserved_under_plan_invalidation
    """
    site = setup_site()
    setup = setup_admitted_episode(site=site, admit_clock=C.CLOCK_2026_09_02)

    for i in range(3):
        session = schedule_session(
            site, setup.id, scheduled_at=f"2026-09-02T{9 + i:02d}:00:00Z"
        )
        record_attendance(site, session["id"], attended=True)
    for i in range(2):
        schedule_session(site, setup.id, scheduled_at=f"2026-09-03T{9 + i:02d}:00:00Z")

    before_rows, _ = list_episode_sessions(site.id, setup.id, limit=100)
    before_ids = {r["id"] for r in before_rows}
    assert len(before_rows) == 5
    assert len([r for r in before_rows if r["status"] == "SCHEDULED"]) == 2

    # Revoke the body accreditation AND push the site into the FROZEN band so the ops
    # cycle's response stage rewrites the SCHEDULED rows.
    from test_helpers import grant_accreditation, run_ops as _run

    for body in ("CARF-R", "JCAHO", "COA", "TJC"):
        grant_accreditation(
            site.id, accreditation_class="ACCREDITATION_BODY",
            granting_body=body, expires_at="2026-09-01T00:00:00Z",
        )
    set_clock("2026-09-09T00:00:00Z")
    _run(site.id)

    after_rows, _ = list_episode_sessions(site.id, setup.id, limit=100)
    after_ids = {r["id"] for r in after_rows}
    assert before_ids.issubset(after_ids), "no pre-run row was deleted"
    assert len(after_rows) == 7, (
        "two SCHEDULED rows were cancelled and two replacements were scheduled: 5 + 2"
    )
    assert len([r for r in after_rows if r["status"] == "CANCELLED"]) == 2
    assert len([r for r in after_rows if r["status"] == "SCHEDULED"]) == 2


def test_the_attendance_ledger_conserves_the_row_count_across_an_invalidation(api):
    """
    PRD §2.10: "A plan invalidation rewrites row statuses; it removes nothing." PRD §2.10:
    "`therapy_revenue_cents` is the sum of `billing_amount_cents` over the rows whose status is
    `ATTENDED`."

    Design: Difficulty/compensating_invariant/invariant_session_ledger_entries_conserved_under_plan_invalidation
    """
    site = setup_site()
    from test_helpers import grant_accreditation as _grant, run_ops as _run_ops

    setup = setup_admitted_episode(site=site, admit_clock=C.CLOCK_2026_09_02)

    for i in range(2):
        session = schedule_session(site, setup.id, scheduled_at=f"2026-09-02T{9 + i:02d}:00:00Z")
        record_attendance(site, session["id"], attended=True)
    schedule_session(site, setup.id, scheduled_at="2026-09-03T09:00:00Z")

    before = read_episode(setup.id)
    before_rows, _ = list_episode_sessions(site.id, setup.id, limit=100)
    assert len(before_rows) == 3

    from test_helpers import grant_accreditation, run_ops as _run

    for body in ("CARF-R", "JCAHO", "COA", "TJC"):
        grant_accreditation(
            site.id, accreditation_class="ACCREDITATION_BODY",
            granting_body=body, expires_at="2026-09-01T00:00:00Z",
        )
    set_clock("2026-09-09T00:00:00Z")
    _run(site.id)

    after = read_episode(setup.id)
    after_rows, _ = list_episode_sessions(site.id, setup.id, limit=100)
    assert len(after_rows) == len(before_rows) + 1
    assert after["therapy_revenue_cents"] == before["therapy_revenue_cents"], (
        "re-attended replacements leave the episode's revenue at its pre-invalidation value"
    )
