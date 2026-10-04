"""Program configuration: checklist weight sums, one ACTIVE checklist per
program, cycle/checklist matching, cycle calendar overlap semantics, and the
clock-derived cycle posture (PRD §3.1, §2.4).
"""

import pytest

from test_helpers import (
    ApiErrorId,
    PLATFORM_ADMIN,
    award_cycle_payload,
    checklist_version_payload,
    create_checklist,
    create_cycle,
    create_draft_submission,
    create_government,
    create_standard,
    activate_standard,
    make_government_contact_headers,
    refresh_cycle,
    set_logical_clock,
    submit_submission,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_cycle_checklist_program_mismatch_rejected(api):
    """PRD §3.1: "The referenced checklist must be `ACTIVE` and must belong to
    the same `program_type` as the cycle; a mismatch on either count is
    rejected with `ERR_CYCLE_CHECKLIST_MISMATCH`."

    Design: Corner/validations/cycle_checklist_program_mismatch_rejected
    """
    set_logical_clock(api)
    checklist = create_checklist(api, program_type="BUDGET_PRESENTATION")

    resp = api.create_award_cycle(
        award_cycle_payload(checklist["id"], program_type="FINANCIAL_REPORTING"),
        headers=PLATFORM_ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_CYCLE_CHECKLIST_MISMATCH)

    rows, meta = validate_paginated(api.list_award_cycles(headers=PLATFORM_ADMIN))
    assert meta["total_count"] == 0 and rows == [], (
        "no cycle may be created by the rejected call"
    )


def test_checklist_weight_sum_invalid_rejected(api):
    """PRD §3.1: "The weights across the list must sum to exactly 1.000; any
    other total is rejected with `ERR_WEIGHT_SUM_INVALID`."

    Design: Corner/validations/checklist_weight_sum_invalid_rejected
    """
    set_logical_clock(api)

    resp = api.create_checklist_version(
        checklist_version_payload(
            program_type="FINANCIAL_REPORTING",
            version_label="bad",
            criteria=[
                {"criterion_code": "C1", "weight": 0.5},
                {"criterion_code": "C2", "weight": 0.4},
            ],
        ),
        headers=PLATFORM_ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_WEIGHT_SUM_INVALID)

    rows, meta = validate_paginated(api.list_checklist_versions(headers=PLATFORM_ADMIN))
    assert meta["total_count"] == 0 and rows == [], (
        "no checklist row may exist after the rejected create"
    )


def test_duplicate_active_checklist_rejected(api):
    """PRD §3.1: "A new checklist begins life `ACTIVE`, and the association
    keeps exactly one active checklist per program: creating one while another
    `ACTIVE` checklist exists for the same `program_type` is rejected with
    `ERR_CHECKLIST_ALREADY_ACTIVE`."
    PRD §2.8: "its `status` moves from `ACTIVE` to `SUPERSEDED` exclusively as
    a cascade of an activated standard of the same `program_type` (§3.7), and
    at most one checklist may be `ACTIVE` per program at any time."

    Design: Corner/validations/duplicate_active_checklist_rejected
    """
    set_logical_clock(api)
    checklist_v1 = create_checklist(api, program_type="FINANCIAL_REPORTING")

    # A second ACTIVE checklist for the same program is rejected.
    rejected = api.create_checklist_version(
        checklist_version_payload(
            program_type="FINANCIAL_REPORTING",
            version_label="2026.2",
            pass_score=86.00,
            criteria=[{"criterion_code": "C1", "weight": 1.0}],
        ),
        headers=PLATFORM_ADMIN,
    )
    validate_error(rejected, ApiErrorId.ERR_CHECKLIST_ALREADY_ACTIVE)

    # Supersede v1 through standards activation, then the replacement is lawful.
    standard = create_standard(api, effective_date="2026-09-10T00:00:00Z")
    activated = validate_success(
        api.activate_standards_reference(standard["id"], headers=PLATFORM_ADMIN)
    )
    assert activated["status"] == "EFFECTIVE"

    replacement = validate_success(
        api.create_checklist_version(
            checklist_version_payload(
                program_type="FINANCIAL_REPORTING",
                version_label="2026.2",
                pass_score=86.00,
                criteria=[{"criterion_code": "C1", "weight": 1.0}],
            ),
            headers=PLATFORM_ADMIN,
        ),
        201,
    )
    assert replacement["status"] == "ACTIVE"

    rows, _ = validate_paginated(
        api.list_checklist_versions(
            headers=PLATFORM_ADMIN, params={"program_type": "FINANCIAL_REPORTING"}
        )
    )
    by_id = {row["id"]: row["status"] for row in rows}
    assert by_id[checklist_v1["id"]] == "SUPERSEDED"
    assert by_id[replacement["id"]] == "ACTIVE"


def test_cycle_windows_half_open_adjacency_allowed(api):
    """PRD §3.1: "The submission window is half-open — it begins inclusively at
    `submission_opens_at` and ends exclusively at `submission_deadline_at` —
    and windows of the same program may not overlap, though back-to-back
    cycles whose boundary instants merely touch are permitted."
    PRD §3.1: "An overlapping window is rejected with
    `ERR_CYCLE_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/cycle_windows_half_open_adjacency_allowed
    """
    set_logical_clock(api)
    checklist = create_checklist(api, program_type="FINANCIAL_REPORTING")
    create_cycle(api, checklist["id"])  # [2026-09-01, 2026-10-15)

    # Adjacent at the exact deadline instant: allowed under half-open semantics.
    adjacent = validate_success(
        api.create_award_cycle(
            award_cycle_payload(
                checklist["id"],
                fiscal_year=2027,
                submission_opens_at="2026-10-15T00:00:00Z",
                submission_deadline_at="2026-11-30T00:00:00Z",
                review_close_at="2027-01-15T00:00:00Z",
            ),
            headers=PLATFORM_ADMIN,
        ),
        201,
    )
    assert adjacent["submission_opens_at"].startswith("2026-10-15T00:00:00")

    # Opening one day earlier intersects [2026-09-01, 2026-10-15): rejected.
    overlapping = api.create_award_cycle(
        award_cycle_payload(
            checklist["id"],
            fiscal_year=2028,
            submission_opens_at="2026-10-14T00:00:00Z",
            submission_deadline_at="2026-12-31T00:00:00Z",
            review_close_at="2027-02-15T00:00:00Z",
        ),
        headers=PLATFORM_ADMIN,
    )
    validate_error(overlapping, ApiErrorId.ERR_CYCLE_WINDOW_OVERLAP)

    # The overlap rule is per program: a BUDGET_PRESENTATION cycle over the
    # same dates is unaffected.
    budget_checklist = create_checklist(api, program_type="BUDGET_PRESENTATION")
    budget_cycle = validate_success(
        api.create_award_cycle(
            award_cycle_payload(budget_checklist["id"], program_type="BUDGET_PRESENTATION"),
            headers=PLATFORM_ADMIN,
        ),
        201,
    )
    assert budget_cycle["program_type"] == "BUDGET_PRESENTATION"


def test_cycle_posture_scheduled_before_window_opens(api):
    """PRD §2.4: "An award cycle's `posture` is recomputed on every read of the
    cycle and on every posture-gated write, from the cycle's three instants:
    before `submission_opens_at` the posture is `SCHEDULED`; at or after
    `submission_opens_at` and before `submission_deadline_at` it is `OPEN`; at
    or after `submission_deadline_at` and before `review_close_at` it is
    `IN_REVIEW`; and at or after `review_close_at` it is `PAST_REVIEW`."
    PRD §3.4: "The cycle's `posture` must be `OPEN`, meaning the logical clock
    is at or after `submission_opens_at` and before `submission_deadline_at`;
    submitting at any other posture is rejected with
    `ERR_SUBMISSION_WINDOW_CLOSED`."

    Design: Corner/calculations/cycle_posture_scheduled_before_window_opens
    """
    set_logical_clock(api, "2026-08-15T00:00:00Z")
    checklist = create_checklist(api)
    cycle = create_cycle(api, checklist["id"])  # window [2026-09-01, 2026-10-15)
    government = create_government(api)
    submission = create_draft_submission(api, government["id"], cycle["id"])

    early = refresh_cycle(api, cycle["id"])
    assert early["posture"] == "SCHEDULED"

    too_early = api.submit_report_submission(
        submission["id"],
        headers=make_government_contact_headers(government["id"]),
    )
    validate_error(too_early, ApiErrorId.ERR_SUBMISSION_WINDOW_CLOSED)

    # At exactly the opens instant the lower bound is inclusive: posture OPEN.
    set_logical_clock(api, "2026-09-01T00:00:00Z")
    opened = refresh_cycle(api, cycle["id"])
    assert opened["posture"] == "OPEN"

    submitted = submit_submission(api, submission["id"], government["id"])
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submitted_at"].startswith("2026-09-01T00:00:00")
