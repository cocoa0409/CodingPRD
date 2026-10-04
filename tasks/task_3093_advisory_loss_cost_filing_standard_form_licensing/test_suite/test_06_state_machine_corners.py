"""State machine lifecycle corners: terminal lockdowns, preconditions, side
effects, and idempotency (PRD §3.1-§3.6)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_finding,
    begin_edit,
    create_circular_payload,
    create_filing_payload,
    create_submission_payload,
    dispose,
    make_activated_plan,
    make_class_plan,
    make_effective_filing,
    make_filed_filing,
    make_insurer,
    make_objected_filing,
    make_reviewed_filing,
    make_staged_revision,
    make_submission,
    set_clock,
    setup_insurer_with_active_plan,
    validate_error,
    validate_paginated,
    validate_success,
    make_insurer_headers,
    make_regulator_headers,
)

ADMIN = TEST_USERS["admin_headers"]
ACTUARY = TEST_USERS["actuary_headers"]


def test_filing_withdraw_from_effective_is_invalid_terminal_lockdown(api):
    """PRD §3.3: "Withdrawal is available from four states: a filing in
    `DRAFT`, `IN_ACTUARIAL_REVIEW`, or `REVIEWED` may be withdrawn
    unconditionally, and a filing in `FILED` may be withdrawn only while it
    has zero objection rows. Any withdrawal lands in `WITHDRAWN`, and
    withdrawing from any other state fails with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/filing_withdraw_from_effective_is_invalid_terminal_lockdown
    """
    filing, _dept = make_effective_filing(
        filing_overrides={"effective_date": "2026-11-01T00:00:00Z"},
    )
    resp = api.withdraw_filing(filing["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api.get_filing(filing["id"], ADMIN))
    assert after["filing_status"] == "EFFECTIVE"


def test_filing_submit_review_without_cells_rejected(api):
    """PRD §3.3: "With at least one cell in place, the administrator submits
    the filing to actuarial review, moving `filing_status` from `DRAFT` to
    `IN_ACTUARIAL_REVIEW` and recording the submitting administrator's
    identity on the filing as `last_submitted_by_admin_id`."
    PRD §2.7: "**From-state validity.** The target resource must be in a valid
    from-state for the requested transition; otherwise `ERR_INVALID_STATE`
    (HTTP 409)."

    Design: Corner/state_machines/filing_submit_review_without_cells_rejected
    """
    resp = api.create_filing(
        create_filing_payload(effective_date="2027-01-01T00:00:00Z"), ADMIN
    )
    filing = validate_success(resp, expected_status=201)
    resp2 = api.submit_filing_review(filing["id"], ADMIN)
    validate_error(resp2, ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api.get_filing(filing["id"], ADMIN))
    assert after["filing_status"] == "DRAFT"


def test_objection_on_filed_filing_executes_side_effects(api):
    """PRD §3.3: "A `RegulatorAnalyst` raises an objection against a `FILED`
    filing by supplying the `department_id`, an `objection_code` categorizing
    the objection, and the `objection_text` narrative; the created
    `RegulatoryObjection` is stamped with `raised_at` from the logical clock."
    PRD §3.3: "The first in-window objection moves the filing from `FILED` to
    `OBJECTED` and increments the filing's `version` by 1."
    PRD §2.4: "All time-gated behavior in the platform — objection windows,
    license coverage, scheduled class plan activation, variant go-live — is
    evaluated against a **logical clock**, never wall-clock time."

    Design: Corner/state_machines/objection_on_filed_filing_executes_side_effects
    """
    filing, dept = make_filed_filing(
        filing_overrides={"effective_date": "2026-11-01T00:00:00Z"},
    )
    set_clock("2026-09-10T00:00:00Z")
    version_at_file = filing["version"]
    resp = api.raise_objection(
        filing["id"],
        {"department_id": dept["id"], "objection_code": "R-10",
         "objection_text": "Data quality concerns"},
        make_regulator_headers(dept["id"]),
    )
    objection = validate_success(resp, expected_status=201)
    assert objection["filing_id"] == filing["id"]
    assert objection["department_id"] == dept["id"]
    assert objection["raised_at"].startswith("2026-09-10")
    after = validate_success(api.get_filing(filing["id"], ADMIN))
    assert after["filing_status"] == "OBJECTED"
    assert after["version"] == version_at_file + 1


def test_submission_dispose_twice_rejected_from_terminal(api):
    """PRD §3.2: "All three dispositions are only reachable from `EDITING`.
    There is also a fast path: disposing a submission still in `RECEIVED` with
    the optional payload flag `fast_reject` set to true covers batch-level
    structural edit failure and moves the submission directly from `RECEIVED`
    to `REJECTED`. Disposing from any other state is rejected with
    `ERR_INVALID_STATE`."
    PRD §3.1: "A new insurer begins life with `insurer_status` `ACTIVE` and a
    perfect statistical reporting quality: `quality_score_bps` starts at
    10000, expressed in basis points on a 0 to 10000 scale."

    Design: Corner/state_machines/submission_dispose_twice_rejected_from_terminal
    """
    insurer, plan = setup_insurer_with_active_plan()
    sub = make_submission(insurer["id"], plan["id"], record_count=5)
    begin_edit(sub["id"])
    disposed = dispose(sub["id"])
    assert disposed["submission_status"] == "ACCEPTED"
    resp = api.dispose_submission(sub["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api.get_submission(sub["id"], ADMIN))
    assert after["submission_status"] == "ACCEPTED"
    insurer_after = validate_success(api.get_insurer(insurer["id"], ADMIN))
    assert insurer_after["quality_score_bps"] == 10000


def test_suspended_insurer_cannot_create_submission(api):
    """PRD §3.1: "Suspending an insurer moves `insurer_status` from `ACTIVE`
    to `SUSPENDED`, increments the insurer's `version`, and has an immediate
    side effect: any attempt by that insurer to create a statistical
    submission is rejected with `ERR_INSURER_SUSPENDED` while the suspension
    stands."
    PRD §3.1: "Reinstatement returns a `SUSPENDED` insurer to `ACTIVE`."

    Design: Corner/state_machines/suspended_insurer_cannot_create_submission
    """
    insurer, plan = setup_insurer_with_active_plan()
    validate_success(api.suspend_insurer(insurer["id"], ADMIN))
    resp = api.create_submission(
        create_submission_payload(insurer["id"], plan["id"], record_count=5),
        make_insurer_headers(insurer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INSURER_SUSPENDED)
    validate_success(api.reinstate_insurer(insurer["id"], ADMIN))
    resp2 = api.create_submission(
        create_submission_payload(insurer["id"], plan["id"], record_count=5),
        make_insurer_headers(insurer["id"]),
    )
    assert resp2.status_code == 201
    rows, meta = validate_paginated(
        api.list_submissions(ADMIN, params={"insurer_id": insurer["id"]})
    )
    assert len(rows) == 1


def test_return_to_drafting_reverts_cleared_variants_compensation(api):
    """PRD §3.5: "Returning the form to drafting moves it from `IN_REVIEW`
    back to `DRAFTING` and reverts every `CLEARED` variant to `PENDING`,
    forcing re-clearance."

    Design: Corner/state_machines/return_to_drafting_reverts_cleared_variants_compensation
    """
    from test_helpers import make_form_with_variants
    form, variants = make_form_with_variants([
        {"state_code": "CW", "effective_from": "2026-10-01T00:00:00Z", "effective_to": None},
        {"state_code": "TX", "effective_from": "2026-10-01T00:00:00Z", "effective_to": None},
    ], form_overrides={"form_kind": "ENDORSEMENT"})
    api.submit_form_review(form["id"], ADMIN)
    api.clear_variant(variants[0]["id"], ACTUARY)
    resp = api.return_form_to_drafting(form["id"], ACTUARY)
    form_after = validate_success(resp)
    assert form_after["form_status"] == "DRAFTING"
    v_cw = validate_success(api.get_variant(variants[0]["id"], ADMIN))
    assert v_cw["review_status"] == "PENDING"
    assert v_cw["publication_status"] == "UNPUBLISHED"
    v_tx = validate_success(api.get_variant(variants[1]["id"], ADMIN))
    assert v_tx["review_status"] == "PENDING"


def test_class_plan_lock_requires_activated_revision_and_no_staged(api):
    """PRD §3.6: "Locking a class plan is terminal and requires the plan
    `OPEN`, a `current_revision_id` that is set, and zero revisions still in
    `STAGED` status; it moves `plan_status` from `OPEN` to `LOCKED`."
    PRD §3.6: "activating moves the revision's `revision_status` from `STAGED`
    to `ACTIVATED` and fires three cascades at once: the plan's previously
    `ACTIVATED` revision, if any, moves to `SUPERSEDED`; the plan's
    `current_revision_id` is set to the newly activated revision; and the
    plan's `version` increments by 1 (with `updated_at` refreshed)."

    Design: Corner/state_machines/class_plan_lock_requires_activated_revision_and_no_staged
    """
    plan, rev1 = make_activated_plan(activates_at="2026-08-01T00:00:00Z")
    rev2 = make_staged_revision(plan["id"], class_count=14, activates_at="2026-08-15T00:00:00Z")
    resp = api.lock_class_plan(plan["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    validate_success(api.activate_revision(rev2["id"], ADMIN))
    rev1_after = validate_success(api.get_revision(rev1["id"], ADMIN))
    assert rev1_after["revision_status"] == "SUPERSEDED"
    rev2_after = validate_success(api.get_revision(rev2["id"], ADMIN))
    assert rev2_after["revision_status"] == "ACTIVATED"
    resp2 = api.lock_class_plan(plan["id"], ADMIN)
    plan_after = validate_success(resp2)
    assert plan_after["plan_status"] == "LOCKED"
    assert plan_after["current_revision_id"] == rev2["id"]


def test_terminal_circular_superseded_accepts_no_further_publish(api):
    """PRD §3.5: "Publishing requires the `implementation_date` to lie
    strictly after the logical clock, and the supersede chain check requires
    any named predecessor to currently be `PUBLISHED` — otherwise
    `ERR_SUPERSEDE_CHAIN_BROKEN`. Publication is a cascade: the circular
    itself moves from `DRAFT` to `PUBLISHED`; every listed form that is
    `APPROVED` moves to `PUBLISHED`, which in turn schedules that form's
    `CLEARED` variants per the publication dimension above; and the superseded
    circular, if any, moves from `PUBLISHED` to `SUPERSEDED`."
    PRD §2.7: "**From-state validity.** The target resource must be in a valid
    from-state for the requested transition; otherwise `ERR_INVALID_STATE`
    (HTTP 409)."

    Design: Corner/state_machines/terminal_circular_superseded_accepts_no_further_publish
    """
    c1 = validate_success(api.create_circular(
        create_circular_payload(circular_number="CIR-2026-20",
                                subject="Original notice",
                                implementation_date="2026-11-01T00:00:00Z"),
        ADMIN,
    ), expected_status=201)
    validate_success(api.publish_circular(c1["id"], ADMIN))
    c2 = validate_success(api.create_circular(
        create_circular_payload(circular_number="CIR-2026-21",
                                subject="Replacement notice",
                                implementation_date="2026-12-01T00:00:00Z",
                                supersedes_circular_id=c1["id"]),
        ADMIN,
    ), expected_status=201)
    validate_success(api.publish_circular(c2["id"], ADMIN))
    c1_after = validate_success(api.get_circular(c1["id"], ADMIN))
    assert c1_after["circular_status"] == "SUPERSEDED"
    resp = api.publish_circular(c1["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
