"""Difficulty queue — non-linear state machines (PRD §3.4, §3.9).

The alternatives-analysis review-revise cycle, and the enforcement case's
two independent dimensions (case_status loops through DEFAULTED while
resolution_track stays put).
"""
import pytest

from test_helpers import (
    AaStatus,
    AaVerdict,
    ApiErrorId,
    CaseStatus,
    ResolutionTrack,
    assert_iso_instants_equal,
    create_aa,
    get_case,
    grant_extension,
    iso_add_days,
    patch_aa,
    review_aa,
    set_clock,
    setup_application_in_alternatives_review,
    setup_case_restoration_pending,
    validate_error,
    verify_restoration,
)


def test_alternatives_analysis_revision_cycle(api):
    """PRD §3.4: "Requesting revision moves the analysis `SUBMITTED` to
    `REVISION_REQUESTED` and may carry `revision_notes`".
    PRD §3.4: "The applicant revises a `REVISION_REQUESTED` analysis by
    editing any of `avoidance_demonstrated`, `avoidance_narrative`,
    `minimization_steps`, `ledpa_conclusion`, or
    `offsite_alternatives_considered`; the edit returns the analysis to
    `SUBMITTED` and increments `revision_count` by 1."
    PRD §3.4: "A successful accept moves the analysis `SUBMITTED` to
    `ACCEPTED`, also terminal."

    The cycle SUBMITTED -> REVISION_REQUESTED -> SUBMITTED -> ACCEPTED runs
    on one analysis; revision_count increments only on the PATCH-driven
    return edge.

    Design: Difficulty/non_linear_state_machine/alternatives_analysis_revision_cycle
    """
    ctx = setup_application_in_alternatives_review()
    applicant = ctx["applicant"]

    aa = create_aa(
        ctx["app"], applicant,
        avoidance_narrative="Initial narrative",
        minimization_steps=["Only one step"],
        ledpa_conclusion="UNDETERMINED",
        offsite_alternatives_considered=1,
    )
    assert aa["status"] == AaStatus.SUBMITTED.value
    assert aa["revision_count"] == 0

    aa = review_aa(aa, AaVerdict.REQUEST_REVISION.value,
                   revision_notes="LEDPA conclusion unsupported")
    assert aa["status"] == AaStatus.REVISION_REQUESTED.value

    aa = patch_aa(
        aa, applicant,
        minimization_steps=["Relocated outfall", "Reduced footprint by 40 percent"],
        ledpa_conclusion="PROPOSED_IS_LEDPA",
    )
    assert aa["status"] == AaStatus.SUBMITTED.value, "the PATCH is the return edge"
    assert aa["revision_count"] == 1, (
        f"revision_count increments only on the return edge: got {aa['revision_count']}"
    )

    aa = review_aa(aa, AaVerdict.ACCEPT.value)
    assert aa["status"] == AaStatus.ACCEPTED.value, (
        "the revised analysis now satisfies the LEDPA gate (avoidance true, "
        "2 minimization steps, PROPOSED_IS_LEDPA)"
    )


def test_enforcement_case_parallel_dimensions_with_defaulted_loop(
    api, officer_confirmer_headers
):
    """PRD §3.9: "Should the clock pass a restoration deadline while the case
    still pends, the case transitions `RESOLUTION_PENDING` to `DEFAULTED`; a
    `DistrictEngineer` may then grant a one-time extension, returning the
    case to `RESOLUTION_PENDING` with `restoration_deadline` reset to the
    current clock plus 60 days and `extension_used` set true".
    PRD §3.9: "timely restoration earns the good-faith offset: the case
    closes and `penalty_final_dollars` is fixed at half of the accrued
    penalty, rounded half-up to two decimal places."
    PRD §3.9: "Every other out-of-state case operation is
    `ERR_CASE_INVALID_STATE`."

    case_status loops RESOLUTION_PENDING -> DEFAULTED -> RESOLUTION_PENDING
    -> CLOSED while resolution_track stays RESTORATION throughout. Penalty:
    2.0 acres * 250.0/day * 136 days (2026-09-01 to 2027-01-15) = 68000.00,
    halved at closure to 34000.00.

    Design: Difficulty/non_linear_state_machine/enforcement_case_parallel_dimensions_with_defaulted_loop
    """
    applicant, site, case = setup_case_restoration_pending(2.0)
    assert case["resolution_track"] == ResolutionTrack.RESTORATION.value
    # Confirmed at the 2026-09-01 startup clock; deadline = +90 days.
    assert_iso_instants_equal(
        case["restoration_deadline"], "2026-11-30T00:00:00Z",
        label="restoration_deadline = confirmed_date + 90 days",
    )

    # Clock past the deadline: RESOLUTION_PENDING -> DEFAULTED (§2.5 step 5).
    set_clock(iso_add_days(case["restoration_deadline"], 1))
    case = get_case(case)
    assert case["case_status"] == CaseStatus.DEFAULTED.value
    assert case["resolution_track"] == ResolutionTrack.RESTORATION.value, (
        "the resolution dimension never moves while case_status loops"
    )

    # verify-restoration is defined only from RESOLUTION_PENDING.
    resp = api.verify_restoration(case["id"], officer_confirmer_headers)
    validate_error(resp, ApiErrorId.ERR_CASE_INVALID_STATE)

    case = grant_extension(case)
    assert case["case_status"] == CaseStatus.RESOLUTION_PENDING.value
    assert case["extension_used"] is True
    assert_iso_instants_equal(
        case["restoration_deadline"], "2027-01-30T00:00:00Z",
        label="extended deadline = extension clock 2026-12-01 + 60 days",
    )

    # Inside the extended window; verify closes with the good-faith offset.
    set_clock("2027-01-15T00:00:00Z")
    case = verify_restoration(case)
    assert case["case_status"] == CaseStatus.CLOSED.value
    assert case["penalty_final_dollars"] == pytest.approx(34000.00, abs=0.005), (
        "136 days * 2.0 acres * 250.0 = 68000.00 accrued, halved at closure: "
        f"expected 34000.00, got {case['penalty_final_dollars']}"
    )
    assert case["resolution_track"] == ResolutionTrack.RESTORATION.value
