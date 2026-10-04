"""Modification appeals, revisions, and retroactive adjustments.

Covers the PRD's appeals workflow (section 3.7) and revision cascades
(section 3.6).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_sheet_for_employer,
    create_unit_stat_report_payload,
    file_mod_appeal,
    get_employer,
    make_carrier_data_reporter_headers,
    make_employer_representative_headers,
    review_mod_appeal,
    set_clock,
    setup_employer_with_validated_report,
    setup_promulgated_sheet,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["bureau_admin_headers"]
ANALYST = TEST_USERS["bureau_analyst_headers"]

_BASE_CLAIMS = [
    {
        "claim_number": "C1",
        "claim_type": "INDEMNITY",
        "incurred_cents": 1600000,
        "paid_cents": 1600000,
        "claim_status": "CLOSED",
        "state_code": "TX",
    },
    {
        "claim_number": "C2",
        "claim_type": "INDEMNITY",
        "incurred_cents": 2400000,
        "paid_cents": 2400000,
        "claim_status": "CLOSED",
        "state_code": "TX",
    },
]

_CORRECTED_CLAIMS = [
    _BASE_CLAIMS[0],
    {
        "claim_number": "C2",
        "claim_type": "INDEMNITY",
        "incurred_cents": 1700000,
        "paid_cents": 1700000,
        "claim_status": "CLOSED",
        "state_code": "TX",
    },
]


def _appeal_under_review(api, sheet, employer, reason="dispute"):
    appeal = file_mod_appeal(sheet, employer, reason=reason)
    return review_mod_appeal(appeal["id"])


def _correction_cascade_to_revision_sheet(api, employer, carrier, policy, report):
    """Correct the locked report (C2 2,400,000 -> 1,700,000) and validate it.

    Per PRD section 3.6 the correction flips the consumed sheet to REVISED and
    spawns a new DRAFT revision sheet. Returns the new DRAFT sheet.
    """
    reporter = make_carrier_data_reporter_headers(carrier["id"])
    correction = validate_success(
        api.create_unit_stat_report(
            create_unit_stat_report_payload(
                policy_id=policy["id"],
                payroll_lines=[{"class_code": "3632", "payroll_dollars": 2000000}],
                claim_lines=_CORRECTED_CLAIMS,
                correction_of_report_id=report["id"],
            ),
            reporter,
        ),
        expected_status=201,
    )
    validate_success(api.validate_unit_stat_report(correction["id"], ANALYST))
    sheets, meta = validate_paginated(
        api.list_employer_experience_mod_sheets(employer["id"], ADMIN)
    )
    assert meta["total_count"] == 2, (
        f"Setup failed: expected 2 sheets after correction, got {meta['total_count']}"
    )
    drafts = [s for s in sheets if s["status"] == "DRAFT"]
    assert len(drafts) == 1, f"Setup failed: expected 1 DRAFT revision sheet, got {len(drafts)}"
    return correction, drafts[0]


def test_mod_sheet_cycles_promulgated_contested_revised_then_respawned(api):
    """PRD section 3.7: "Deciding `REVERSED` moves the appeal to `REVERSED`
    and moves the sheet from `CONTESTED` to `REVISED`, and the system spawns
    a new `ExperienceModSheet` in `DRAFT` with `revision_of_sheet_id` pointing
    at the reversed sheet and `revision_reason` set to `CLASS_CODE_CHANGE` or
    `CLAIM_VALUE_CHANGE` as the appeal determined."

    Design: Difficulty/non_linear_state_machine/mod_sheet_cycles_promulgated_contested_revised_promulgated
    """
    set_clock("2026-06-01T00:00:00Z")
    bureau, carrier, employer, class_code, table, policy, report, sheet = (
        setup_promulgated_sheet(payroll_dollars=2000000, claim_lines=_BASE_CLAIMS)
    )
    appeal = _appeal_under_review(api, sheet, employer, reason="Claim C2 reserved too high")
    decided = validate_success(
        api.decide_mod_appeal(
            appeal["id"],
            {"decision": "REVERSED", "decision_reason": "Carrier corrected C2 downward"},
            ANALYST,
        ),
        expected_status=200,
    )
    assert decided["status"] == "REVERSED"
    sheet_after = validate_success(api.get_experience_mod_sheet(sheet["id"], ADMIN))
    assert sheet_after["status"] == "REVISED", (
        f"Reversed appeal must move the sheet to REVISED, got {sheet_after['status']}"
    )

    sheets, meta = validate_paginated(
        api.list_employer_experience_mod_sheets(employer["id"], ADMIN)
    )
    assert meta["total_count"] == 2, (
        f"Reversal must spawn a second sheet, got total_count {meta['total_count']}"
    )
    spawned = [s for s in sheets if s["id"] != sheet["id"]]
    assert len(spawned) == 1
    assert spawned[0]["status"] == "DRAFT"
    assert spawned[0]["revision_of_sheet_id"] == sheet["id"]


def test_promulgate_respawned_revision_sheet_completes_cycle(api):
    """PRD section 3.7: "Deciding `REVERSED` moves the appeal to
    `REVERSED` and moves the sheet from `CONTESTED` to `REVISED`, and the
    system spawns a new `ExperienceModSheet` in `DRAFT` with
    `revision_of_sheet_id` pointing at the reversed sheet and
    `revision_reason` set to `CLASS_CODE_CHANGE` or `CLAIM_VALUE_CHANGE` as
    the appeal determined." PRD section 3.5: "Promulgation is the regulated
    act that makes a factor effective."

    Design: Difficulty/non_linear_state_machine/mod_sheet_cycles_promulgated_contested_revised_promulgated
    """
    set_clock("2026-06-01T00:00:00Z")
    bureau, carrier, employer, class_code, table, policy, report, sheet = (
        setup_promulgated_sheet(payroll_dollars=2000000, claim_lines=_BASE_CLAIMS)
    )
    appeal = _appeal_under_review(api, sheet, employer)
    validate_success(
        api.decide_mod_appeal(
            appeal["id"], {"decision": "REVERSED", "decision_reason": "x"}, ANALYST
        )
    )
    sheets, meta = validate_paginated(
        api.list_employer_experience_mod_sheets(employer["id"], ADMIN)
    )
    spawned = [s for s in sheets if s["id"] != sheet["id"]]
    assert len(spawned) == 1, "Setup failed: reversal must spawn exactly one sheet"
    assert spawned[0]["status"] == "DRAFT"

    # The revision loop closes: the spawned DRAFT sheet can itself promulgate.
    promulgated = validate_success(
        api.promulgate_experience_mod_sheet(spawned[0]["id"], ANALYST),
        expected_status=200,
    )
    assert promulgated["status"] == "PROMULGATED"
    assert promulgated["revision_of_sheet_id"] == sheet["id"]


def test_appeal_upheld_cascades_sheet_to_final(api):
    """PRD section 3.7: "Deciding `UPHELD` moves the appeal to `UPHELD`, stamps
    `decided_at`, and moves the sheet from `CONTESTED` to `FINAL` - the factor
    stands."

    Design: Corner/state_machines/appeal_upheld_cascades_sheet_to_final
    """
    set_clock("2026-06-01T00:00:00Z")
    bureau, carrier, employer, class_code, table, policy, report, sheet = (
        setup_promulgated_sheet(payroll_dollars=2000000, claim_lines=_BASE_CLAIMS)
    )
    appeal = _appeal_under_review(api, sheet, employer, reason="payroll dispute")
    decided = validate_success(
        api.decide_mod_appeal(
            appeal["id"],
            {"decision": "UPHELD", "decision_reason": "data verified"},
            ANALYST,
        ),
        expected_status=200,
    )
    assert decided["status"] == "UPHELD"
    sheet_after = validate_success(api.get_experience_mod_sheet(sheet["id"], ADMIN))
    assert sheet_after["status"] == "FINAL", (
        f"Upheld appeal must move the sheet to FINAL, got {sheet_after['status']}"
    )


def test_second_appeal_on_contested_sheet_returns_appeal_already_active(api):
    """PRD section 3.7: "no other active appeal may exist for the sheet, or
    the filing is rejected with `ERR_APPEAL_ALREADY_ACTIVE`"; PRD section 5:
    ERR_APPEAL_ALREADY_ACTIVE maps to HTTP 409.

    Design: Corner/validations/second_appeal_on_contested_sheet_returns_appeal_already_active
    """
    set_clock("2026-06-01T00:00:00Z")
    bureau, carrier, employer, class_code, table, policy, report, sheet = (
        setup_promulgated_sheet(payroll_dollars=2000000, claim_lines=_BASE_CLAIMS)
    )
    file_mod_appeal(sheet, employer, reason="first")
    contested = validate_success(api.get_experience_mod_sheet(sheet["id"], ADMIN))
    assert contested["status"] == "CONTESTED"

    resp = api.create_mod_appeal(
        {"mod_sheet_id": sheet["id"], "reason": "second"},
        make_employer_representative_headers(employer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_APPEAL_ALREADY_ACTIVE, expected_status=409)


def test_appeal_on_revised_sheet_yields_invalid_state_not_missing_reason(api):
    """PRD section 2.7: "Incoming requests are validated against a fixed
    precedence order, so that when several rules would fail at once, the same
    error surfaces every time." PRD section 3.7: "The sheet must be
    `PROMULGATED` — appealing a sheet in any other status fails with
    `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/appeal_on_revised_sheet_yields_invalid_state_not_missing_reason
    """
    set_clock("2026-06-01T00:00:00Z")
    bureau, carrier, employer, class_code, table, policy, report, sheet = (
        setup_promulgated_sheet(payroll_dollars=2000000, claim_lines=_BASE_CLAIMS)
    )
    appeal = _appeal_under_review(api, sheet, employer)
    validate_success(
        api.decide_mod_appeal(
            appeal["id"], {"decision": "REVERSED", "decision_reason": "x"}, ANALYST
        )
    )
    revised = validate_success(api.get_experience_mod_sheet(sheet["id"], ADMIN))
    assert revised["status"] == "REVISED"

    # Missing `reason` (a request-shape failure) on a non-PROMULGATED sheet:
    # the state check outranks the fiscal/request check.
    resp = api.create_mod_appeal(
        {"mod_sheet_id": sheet["id"]},
        make_employer_representative_headers(employer["id"]),
    )
    error = validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    assert error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST


def test_appeal_on_draft_sheet_yields_invalid_state(api):
    """PRD section 3.7: "The sheet must be `PROMULGATED` — appealing a
    sheet in any other status fails with `ERR_INVALID_STATE`"; PRD section 5:
    ERR_INVALID_STATE maps to HTTP 409.

    Design: Difficulty/priority_pair_validation_conflict/appeal_on_revised_sheet_yields_invalid_state_not_missing_reason
    """
    set_clock("2026-06-01T00:00:00Z")
    bureau, carrier, employer, class_code, table, policy, report = (
        setup_employer_with_validated_report(
            payroll_dollars=2000000, claim_lines=_BASE_CLAIMS
        )
    )
    sheet = create_sheet_for_employer(employer["id"])
    assert sheet["status"] == "DRAFT"
    # Well-formed appeal body against a DRAFT (not PROMULGATED) sheet.
    resp = api.create_mod_appeal(
        {"mod_sheet_id": sheet["id"], "reason": "too early"},
        make_employer_representative_headers(employer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_claim_correction_cascades_report_sheet_premium(api):
    """PRD section 3.6: "A `PROMULGATED` sheet moves to `REVISED` automatically
    in three circumstances: a correction report consuming a locked report is
    validated; a class code reassignment is confirmed; or a rating table
    revision is promulgated. In each case the system creates a new
    `ExperienceModSheet` in `DRAFT` whose `revision_of_sheet_id` points at the
    superseded sheet and whose `revision_reason` records the cause -
    `CLAIM_VALUE_CHANGE`, `CLASS_CODE_CHANGE`, or `RATE_REVISION`
    respectively."

    Design: Difficulty/transitive_cascade/claim_correction_cascades_report_sheet_premium
    """
    set_clock("2026-06-01T00:00:00Z")
    bureau, carrier, employer, class_code, table, policy, report, sheet = (
        setup_promulgated_sheet(payroll_dollars=2000000, claim_lines=_BASE_CLAIMS)
    )
    correction, draft2 = _correction_cascade_to_revision_sheet(
        api, employer, carrier, policy, report
    )

    old_report = validate_success(api.get_unit_stat_report(report["id"], ADMIN))
    assert old_report["status"] == "CORRECTED", (
        f"The corrected report must move to CORRECTED, got {old_report['status']}"
    )
    old_sheet = validate_success(api.get_experience_mod_sheet(sheet["id"], ADMIN))
    assert old_sheet["status"] == "REVISED", (
        f"The consumed sheet must move to REVISED, got {old_sheet['status']}"
    )
    assert draft2["revision_of_sheet_id"] == sheet["id"]
    assert draft2["revision_reason"] == "CLAIM_VALUE_CHANGE"
    assert draft2["actual_primary_cents"] + draft2["actual_excess_cents"] == 3300000, (
        "The revision sheet must recompute losses from the corrected report "
        f"(1,600,000 + 1,700,000 = 3,300,000), got primary "
        f"{draft2['actual_primary_cents']} + excess {draft2['actual_excess_cents']}"
    )
    # Per-claim split detail at exactly the split point is not uniquely
    # derivable from PRD prose, so only the conserved total is asserted here.


def test_claim_correction_moves_sheet_to_revised_with_claim_value_change(api):
    """PRD section 3.6: "A `PROMULGATED` sheet moves to `REVISED` automatically
    in three circumstances: a correction report consuming a locked report is
    validated; a class code reassignment is confirmed; or a rating table
    revision is promulgated. In each case the system creates a new
    `ExperienceModSheet` in `DRAFT` whose `revision_of_sheet_id` points at the
    superseded sheet and whose `revision_reason` records the cause -
    `CLAIM_VALUE_CHANGE`, `CLASS_CODE_CHANGE`, or `RATE_REVISION`
    respectively."

    Design: Difficulty/transitive_cascade/claim_correction_cascades_report_sheet_premium
    """
    set_clock("2026-06-01T00:00:00Z")
    bureau, carrier, employer, class_code, table, policy, report, sheet = (
        setup_promulgated_sheet(payroll_dollars=2000000, claim_lines=_BASE_CLAIMS)
    )
    correction, draft2 = _correction_cascade_to_revision_sheet(
        api, employer, carrier, policy, report
    )
    # The cascade is observable even before the revision sheet is promulgated.
    old_sheet = validate_success(api.get_experience_mod_sheet(sheet["id"], ADMIN))
    assert old_sheet["status"] == "REVISED"
    assert draft2["revision_of_sheet_id"] == sheet["id"]
    assert draft2["revision_reason"] == "CLAIM_VALUE_CHANGE"
    # The correction itself is a fresh report in SUBMITTED that validates clean.
    correction_now = validate_success(api.get_unit_stat_report(correction["id"], ADMIN))
    assert correction_now["status"] == "VALIDATED"
    assert correction_now["correction_of_report_id"] == report["id"]


def test_retroactive_adjustment_is_negative_credit_on_downward_revision(api):
    """PRD section 3.6: "the old billing is the manual premium multiplied by
    the prior sheet's `mod_factor`, rounded half up; the new billing is the
    manual premium multiplied by the new sheet's `mod_factor`, rounded half
    up; and the adjustment is the new billing minus the old. A negative
    adjustment is a credit due to the insured."

    Design: Corner/cross_cutting/retroactive_adjustment_is_negative_credit_on_downward_revision
    """
    set_clock("2026-06-01T00:00:00Z")
    bureau, carrier, employer, class_code, table, policy, report, sheet = (
        setup_promulgated_sheet(payroll_dollars=2000000, claim_lines=_BASE_CLAIMS)
    )
    _correction, draft2 = _correction_cascade_to_revision_sheet(
        api, employer, carrier, policy, report
    )
    assert draft2["revision_reason"] == "CLAIM_VALUE_CHANGE"

    promulgated2 = validate_success(
        api.promulgate_experience_mod_sheet(draft2["id"], ANALYST), expected_status=200
    )
    adjustment = promulgated2.get("retroactive_premium_adjustment_cents")
    assert adjustment is not None, (
        "A revision sheet must carry retroactive_premium_adjustment_cents"
    )
    # Manual premium is 2,000,000 * 250 / 100 = 5,000,000 cents; the downward
    # claim correction must produce a credit (new billing minus old < 0).
    assert isinstance(adjustment, int)
    assert adjustment < 0, (
        f"A downward revision must yield a negative adjustment (credit), got {adjustment}"
    )


def test_claim_level_loss_totals_conserved_across_correction(api):
    """PRD section 3.5: "For each claim line, the primary portion is the
    lesser of the claim's `incurred_cents` and the bureau's
    `split_point_cents`; the excess portion is the remainder. Summing the
    primary portions across all claims yields `actual_primary_cents`; summing
    the remainders yields `actual_excess_cents`." PRD section 3.3: "To correct
    a report that is `VALIDATED` or `LOCKED`, the carrier submits a fresh
    report whose `correction_of_report_id` names the report being corrected;
    referencing a report in any other status is rejected with
    `ERR_INVALID_STATE`."

    Design: Difficulty/compensating_invariant/claim_level_loss_totals_conserved_across_correction
    """
    set_clock("2026-06-01T00:00:00Z")
    bureau, carrier, employer, class_code, table, policy, report, sheet = (
        setup_promulgated_sheet(payroll_dollars=2000000, claim_lines=_BASE_CLAIMS)
    )
    correction, draft2 = _correction_cascade_to_revision_sheet(
        api, employer, carrier, policy, report
    )
    promulgated2 = validate_success(
        api.promulgate_experience_mod_sheet(draft2["id"], ANALYST), expected_status=200
    )
    # No loss cents leak between the corrected report and its replacement:
    # primary + excess on the revision sheet equals the corrected incurred total.
    total = promulgated2["actual_primary_cents"] + promulgated2["actual_excess_cents"]
    assert total == 3300000, (
        f"Expected primary + excess == 3,300,000 corrected incurred, got {total}"
    )

    old_report = validate_success(api.get_unit_stat_report(report["id"], ADMIN))
    assert old_report["status"] == "CORRECTED"
    new_report = validate_success(api.get_unit_stat_report(correction["id"], ADMIN))
    assert new_report["status"] == "LOCKED", (
        f"Promulgating the revision sheet must lock the correction, got "
        f"{new_report['status']}"
    )


def test_correction_report_receives_next_submission_number(api):
    """PRD section 3.3: "The new report enters in `SUBMITTED` with the next
    `submission_number`, and the referenced report moves to `CORRECTED`."

    Design: Difficulty/compensating_invariant/claim_level_loss_totals_conserved_across_correction
    """
    set_clock("2026-06-01T00:00:00Z")
    bureau, carrier, employer, class_code, table, policy, report, sheet = (
        setup_promulgated_sheet(payroll_dollars=2000000, claim_lines=_BASE_CLAIMS)
    )
    assert report["submission_number"] == 1
    correction, draft2 = _correction_cascade_to_revision_sheet(
        api, employer, carrier, policy, report
    )
    correction_now = validate_success(api.get_unit_stat_report(correction["id"], ADMIN))
    assert correction_now["submission_number"] == 2, (
        f"Correction must take the next submission number 2, got "
        f"{correction_now['submission_number']}"
    )
    old_report = validate_success(api.get_unit_stat_report(report["id"], ADMIN))
    assert old_report["status"] == "CORRECTED"

    # The revision sheet recomputes from the replacement report only: primary
    # plus excess equals the corrected incurred total with nothing duplicated.
    total = draft2["actual_primary_cents"] + draft2["actual_excess_cents"]
    assert total == 3300000, (
        f"Expected 3,300,000 from the corrected report alone, got {total}"
    )
