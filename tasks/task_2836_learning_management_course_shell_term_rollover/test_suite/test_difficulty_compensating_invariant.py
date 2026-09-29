"""Depth tests: three named conserved quantities and their compensating pairs.

Each test drives a forward operation that visibly moves a quantity between
holders, then either checks the conservation identity at the moment of maximum
displacement or drives the compensating operation and checks that every reading
returns to its pre-operation value rather than merely near it. The three
quantities are a term's active student headcount, the megabytes stored across a
rollover source-and-target pair, and a passback's three-bucket points ledger.
"""
import pytest

from test_helpers import (
    LMS_ADMIN_ALT_USER_ID,
    LMS_ADMIN_USER_ID,
    TEST_USERS,
    assert_passback_ledger,
    assert_term_seat_ledger,
    factories as fac,
    fixtures as fx,
    validate_paginated,
)

ADMIN = TEST_USERS["lms_admin_headers"]
ADMIN_ALT = TEST_USERS["lms_admin_alt_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


def _approved_merge_of_thirteen_students(api):
    """A parent of 8 and a child of 5 in one term carrying 13, ready to APPLY.

    One SIS batch adds every row, so the term's headcount is written by a single
    server-side pass. The request is opened and submitted by one LmsAdmin operator
    and approved by a different one.
    """
    term = fx.create_term_in_state(api, "IN_SESSION")
    owner = fx.create_faculty(api)
    parent = fx.provision_shell(
        api, term["id"], owner["id"], base_seat_cap=10, sis_section_code="CS500-01"
    )
    child = fx.provision_shell(
        api, term["id"], owner["id"], base_seat_cap=6, sis_section_code="CS500-02"
    )
    students = fx.create_students(api, 13)
    operations = [
        fac.sync_operation("ADD", parent["id"], person["id"]) for person in students[:8]
    ] + [
        fac.sync_operation("ADD", child["id"], person["id"]) for person in students[8:]
    ]
    batch = fx.apply_sync_batch(api, term["id"], operations)

    parent_before = fx.read_shell(api, parent["id"])
    child_before = fx.read_shell(api, child["id"])
    merge = fx.open_merge_request(
        api, parent_before, child["id"], headers=ADMIN,
        justification="cross-listed honours section",
    )
    fx.transition_merge_request(api, merge["id"], "SUBMIT", headers=ADMIN)
    approved = fx.transition_merge_request(
        api, merge["id"], "APPROVE", headers=ADMIN_ALT
    )
    return {
        "term": term,
        "term_before": fx.read_term(api, term["id"]),
        "batch": batch,
        "parent_before": parent_before,
        "child_before": child_before,
        "merge": merge,
        "approved": approved,
    }


def test_merge_apply_relocates_five_rows_and_conserves_the_term_headcount(api):
    """PRD §3.4: "The batch records `applied_add_count` and `applied_drop_count`,
    each drop's freed seat cascades waitlist promotions exactly as an individual
    drop does, `promoted_from_waitlist_count` records how many promotions fired
    across the whole batch, and the term's `sis_sync_epoch` advances by one."
    PRD §3.5: "Then every enrollment of the child shell whose `enrollment_state` is
    `ACTIVE` is relocated in `created_at` ascending order: its `shell_id` is
    repointed at the parent and its `merged_from_shell_id` is stamped with the
    child's identifier, and `moved_enrollment_count` records how many rows moved."
    PRD §3.5: "It first records `seat_ledger_before` as the term's
    `total_active_enrollments` read immediately before any mutation."
    PRD §3.5: "Finally `seat_ledger_after` records the term's
    `total_active_enrollments` after the relocation, and the seat ledger requires
    that it equal `seat_ledger_before` exactly — a merge moves students between
    shells and never changes how many of them the term is carrying. A parent
    holding 8 active students and a child holding 5, in a term carrying 13,
    therefore ends with the parent at 13, the child at 0 and the term still at 13."
    PRD §3.5: "The child shell itself moves `PROVISIONED` → `MERGED`, or
    `PUBLISHED` → `MERGED` if it was live, taking `merged_into_shell_id` to the
    parent's identifier, zeroing its `active_enrollment_count` and
    `waitlisted_enrollment_count`, setting its `seat_utilization_pct` to 0.00 and
    its `overflow_flag` to false, and — in the published case only — lowering the
    term's `published_shell_count` by one."
    PRD §3.5: "**No waitlist promotion is triggered on the parent by this
    transition**: an absorbing parent that ends up over its cap simply reports
    `overflow_flag` true rather than pulling its own queue forward."
    PRD §2.8: "**The term seat ledger.** A term's `total_active_enrollments`
    always equals the sum of `active_enrollment_count` across that term's shells
    whose `provisioning_state` is neither `REJECTED` nor `PURGED`."
    PRD §2.3: "Because the topology is flat, every collection that carries a
    foreign key also accepts that foreign key as an optional filter, which is how
    the reverse direction of each relationship is reachable. Filters compose:
    supplying two of them narrows to records matching both. Filter values are also
    the state fields themselves, so a caller can ask for one lifecycle stage at a
    time."

    Design: Difficulty/compensating_invariant/merge_apply_and_reverse_conserve_the_terms_active_student_headcount_at_thirteen
    """
    s = _approved_merge_of_thirteen_students(api)

    assert s["batch"]["applied_add_count"] == 13
    assert s["term_before"]["total_active_enrollments"] == 13
    assert s["parent_before"]["active_enrollment_count"] == 8
    assert s["child_before"]["active_enrollment_count"] == 5
    assert s["parent_before"]["seat_utilization_pct"] == pytest.approx(80.00, abs=0.005)
    assert s["merge"]["submitted_by_user_id"] == LMS_ADMIN_USER_ID
    assert s["approved"]["decided_by_user_id"] == LMS_ADMIN_ALT_USER_ID
    assert s["approved"]["merge_state"] == "APPROVED"

    applied = fx.transition_merge_request(
        api, s["merge"]["id"], "APPLY", headers=ADMIN_ALT
    )
    assert applied["merge_state"] == "APPLIED"
    assert applied["moved_enrollment_count"] == 5
    assert applied["seat_ledger_before"] == 13
    assert applied["seat_ledger_after"] == 13, (
        "the conservation identity is recorded on the merge row itself"
    )

    parent = fx.read_shell(api, s["parent_before"]["id"])
    child = fx.read_shell(api, s["child_before"]["id"])
    term = fx.read_term(api, s["term"]["id"])
    assert parent["active_enrollment_count"] == 13
    assert parent["absorbed_child_count"] == 1
    assert parent["seat_utilization_pct"] == pytest.approx(130.00, abs=0.005)
    assert parent["overflow_flag"] is True, (
        "an absorbing parent over its cap reports overflow instead of promoting"
    )
    assert child["provisioning_state"] == "MERGED"
    assert child["active_enrollment_count"] == 0
    assert child["waitlisted_enrollment_count"] == 0
    assert child["merged_into_shell_id"] == parent["id"]
    assert child["seat_utilization_pct"] == pytest.approx(0.00, abs=0.005)
    assert child["overflow_flag"] is False
    assert term["total_active_enrollments"] == 13, (
        "double-counting the relocated rows would read 18 here"
    )
    assert_term_seat_ledger(term, [parent, child])

    rows, meta = validate_paginated(
        api.list_enrollments(
            REGISTRAR, params={"merged_from_shell_id": s["child_before"]["id"]}
        )
    )
    assert meta["total_count"] == 5
    assert all(row["shell_id"] == parent["id"] for row in rows), (
        "every relocated row is repointed at the parent"
    )


def test_merge_reverse_returns_every_seat_reading_to_its_pre_apply_value(api):
    """PRD §3.5: "Every enrollment sitting on the parent whose
    `merged_from_shell_id` points at this child is sent home in `created_at`
    ascending order: its `shell_id` returns to the child and its
    `merged_from_shell_id` returns to null, with `reversed_enrollment_count`
    recording how many rows returned."
    PRD §3.5: "The child moves `MERGED` → `PROVISIONED`, its
    `merged_into_shell_id` returns to null and its seat observables are recomputed
    from the returned rows; the parent's `absorbed_child_count` falls by one and
    its own seat observables are recomputed too."
    PRD §3.5: "The term's `total_active_enrollments` is left at its pre-apply
    value, so the round trip through apply and reverse restores the parent to 8,
    the child to 5 and the term to 13 with zero drift."
    PRD §3.4: "Only in step five are the observables recomputed:
    `seat_utilization_pct` becomes `active_enrollment_count` divided by
    `base_seat_cap`, multiplied by 100, rounded half up to two decimal places, and
    `overflow_flag` becomes true exactly when `active_enrollment_count` is greater
    than `base_seat_cap`."
    PRD §2.8: "**The term seat ledger.** A term's `total_active_enrollments`
    always equals the sum of `active_enrollment_count` across that term's shells
    whose `provisioning_state` is neither `REJECTED` nor `PURGED`."
    PRD §2.3: "Because the topology is flat, every collection that carries a
    foreign key also accepts that foreign key as an optional filter, which is how
    the reverse direction of each relationship is reachable. Filters compose:
    supplying two of them narrows to records matching both. Filter values are also
    the state fields themselves, so a caller can ask for one lifecycle stage at a
    time."

    Design: Difficulty/compensating_invariant/merge_apply_and_reverse_conserve_the_terms_active_student_headcount_at_thirteen
    """
    s = _approved_merge_of_thirteen_students(api)
    applied = fx.transition_merge_request(
        api, s["merge"]["id"], "APPLY", headers=ADMIN_ALT
    )
    assert applied["moved_enrollment_count"] == 5

    reversed_row = fx.transition_merge_request(
        api, s["merge"]["id"], "REVERSE", headers=ADMIN_ALT
    )
    assert reversed_row["merge_state"] == "REVERSED"
    assert reversed_row["reversed_enrollment_count"] == 5, (
        "exactly the rows the apply moved come home, no more"
    )

    parent = fx.read_shell(api, s["parent_before"]["id"])
    child = fx.read_shell(api, s["child_before"]["id"])
    term = fx.read_term(api, s["term"]["id"])
    assert parent["active_enrollment_count"] == 8
    assert parent["seat_utilization_pct"] == pytest.approx(80.00, abs=0.005)
    assert parent["overflow_flag"] is False
    assert parent["absorbed_child_count"] == 0
    assert child["provisioning_state"] == "PROVISIONED"
    assert child["active_enrollment_count"] == 5
    assert child["merged_into_shell_id"] is None
    assert term["total_active_enrollments"] == 13, (
        "the term headcount never moved in either direction"
    )
    assert_term_seat_ledger(term, [parent, child])

    rows, meta = validate_paginated(
        api.list_enrollments(
            REGISTRAR, params={"merged_from_shell_id": s["child_before"]["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        "merged_from_shell_id is cleared on every returned row, leaving no trace "
        "of the relocation on the enrollments themselves"
    )
    assert rows == []


SP_TERM_START = "2026-01-12T00:00:00Z"
SP_TERM_END = "2026-05-08T00:00:00Z"
FA_TERM_START = "2026-08-24T00:00:00Z"
FA_TERM_END = "2026-12-11T00:00:00Z"

SOURCE_ITEM_SPECS = (
    ("Week 1 lecture capture", 250.00),
    ("Week 2 lecture capture", 200.00),
    ("Reading pack", 120.00),
)


def _validated_rollover_into_an_undersized_sandbox(api):
    """A CONCLUDED 570.00 MB source and an empty SANDBOX target, job VALIDATED.

    The target sandbox carries a 500.00-megabyte quota, so copying all three items
    is guaranteed to overshoot it. A second OFFICIAL shell in the autumn term
    gives that term a non-empty rollover denominator, and the logical clock is
    left at its startup instant so the sandbox is nowhere near expiry.
    """
    sp_term = fx.create_term(
        api, term_start_at=SP_TERM_START, term_end_at=SP_TERM_END
    )
    fa_term = fx.create_term(
        api, term_start_at=FA_TERM_START, term_end_at=FA_TERM_END
    )
    owner = fx.create_faculty(api)
    instructor = fx.make_instructor_headers(owner["id"])
    source = fx.provision_shell(
        api, sp_term["id"], owner["id"], base_seat_cap=30,
        sis_section_code="CS600-01",
    )
    items = [
        fx.create_content_item(
            api, source["id"], instructor, item_type="FILE", title=title,
            points_possible=0.00, storage_mb=storage_mb,
        )
        for title, storage_mb in SOURCE_ITEM_SPECS
    ]
    source_before = fx.read_shell(api, source["id"])
    concluded = fx.transition_shell(api, source["id"], "CONCLUDED")
    target = fx.provision_shell(
        api, fa_term["id"], owner["id"], shell_type="SANDBOX", base_seat_cap=1,
        sis_section_code="SBX-CS600",
    )
    fx.provision_shell(
        api, fa_term["id"], owner["id"], base_seat_cap=30,
        sis_section_code="CS600-01-FA",
    )
    job = fx.open_rollover_job(
        api, source["id"], target, fa_term["id"],
        strip_dates=True, strip_submissions=True, strip_grades=True,
    )
    return {
        "fa_term": fa_term,
        "owner": owner,
        "source": concluded,
        "source_before": source_before,
        "items": items,
        "target": target,
        "owner_before": fx.read_person(api, owner["id"]),
        "fa_term_before": fx.read_term(api, fa_term["id"]),
        "target_before": fx.read_shell(api, target["id"]),
        "job": job,
        "validated": fx.transition_rollover_job(api, job["id"], "VALIDATE"),
    }


def test_rollover_execute_takes_the_quota_branch_and_leaves_the_copies_in_place(api):
    """PRD §3.3: "On approval `effective_seat_cap` is set equal to
    `base_seat_cap`, `publish_readiness` is set to true, and `sandbox_expires_at`
    is set to sixty days after the term's `term_end_at` for a `SANDBOX` or `DEV`
    shell while remaining null for an `OFFICIAL` one."
    PRD §3.6: "A new item opens with `copy_state` `SOURCE`, `date_stripped` false,
    `submission_count` 0, `has_submissions` false and `source_item_id` null — the
    last field is the copy-provenance self-reference, filled in only on rollover
    copies."
    PRD §3.6: "The job opens in `job_state` `DRAFT` with every tally at zero."
    PRD §3.6: "Validation sets `eligible_item_count` to the number of the source
    shell's items whose `copy_state` is not `SKIPPED`, and copies nothing."
    PRD §3.6: "The job instead takes `COPYING` → `FAILED` when the copy pushed a
    `SANDBOX` or `DEV` target above that quota. On the failed branch
    `failure_reason` is recorded as "sandbox storage quota exceeded", **the copies
    are deliberately left in place** so the target shell is observable in its
    over-quota state, and the target term's `rollover_completion_pct` is not
    advanced."
    PRD §3.3: "For each shell, subtract a free allowance of 100.00 megabytes from
    its `storage_mb` and treat any negative result as zero; multiply the remainder
    by a rate of 0.0150 US dollars per megabyte; multiply again by the class
    multiplier, which is 1.00 for a `SANDBOX` shell and 0.50 for a `DEV` shell;
    then round that single shell's charge half up to two decimal places."

    Design: Difficulty/compensating_invariant/rollover_compensation_returns_the_source_target_pair_to_five_hundred_seventy_stored_megabytes
    """
    s = _validated_rollover_into_an_undersized_sandbox(api)

    assert s["items"][0]["copy_state"] == "SOURCE"
    assert s["source_before"]["storage_mb"] == pytest.approx(570.00, abs=0.005)
    assert s["source_before"]["content_item_count"] == 3
    assert s["source"]["provisioning_state"] == "CONCLUDED"
    assert s["target"]["sandbox_expires_at"].startswith("2027-02-09T00:00:00"), (
        "2026-12-11 plus sixty days, so the startup clock is well inside the "
        "sandbox's life and expiry cannot be what refuses anything here"
    )
    assert s["owner_before"]["sandbox_storage_charge_usd"] == pytest.approx(
        0.00, abs=0.005
    )
    assert s["target_before"]["storage_mb"] == pytest.approx(0.00, abs=0.005)
    assert s["target_before"]["content_item_count"] == 0
    assert s["fa_term_before"]["rollover_completion_pct"] == pytest.approx(
        0.00, abs=0.005
    )
    assert s["job"]["job_state"] == "DRAFT"
    assert s["validated"]["job_state"] == "VALIDATED"
    assert s["validated"]["eligible_item_count"] == 3

    failed = fx.transition_rollover_job(api, s["job"]["id"], "EXECUTE")
    assert failed["job_state"] == "FAILED", (
        "570.00 copied megabytes overshoot the sandbox quota, so the execute fork "
        "takes the quota branch rather than completing"
    )
    assert failed["failure_reason"] == "sandbox storage quota exceeded"
    assert failed["copied_item_count"] == 3

    target = fx.read_shell(api, s["target"]["id"])
    assert target["storage_mb"] == pytest.approx(570.00, abs=0.005), (
        "the over-quota state is observable rather than unwound inside the "
        "execute request"
    )
    assert target["content_item_count"] == 3
    owner = fx.read_person(api, s["owner"]["id"])
    assert owner["sandbox_storage_charge_usd"] == pytest.approx(7.05, abs=0.005), (
        "max(0.00, 570.00 - 100.00) * 0.0150 * 1.00 = 7.05"
    )
    fa_term = fx.read_term(api, s["fa_term"]["id"])
    assert fa_term["rollover_completion_pct"] == pytest.approx(0.00, abs=0.005), (
        "the failed branch must not advance the target term's completion"
    )


def test_rollover_compensation_returns_the_pair_to_five_hundred_seventy_megabytes(api):
    """PRD §3.6: "Every item of the target shell whose `copy_state` is `COPIED` and
    whose `source_item_id` points at an item of the source shell has its
    `copy_state` set to `SKIPPED` and its `storage_mb` set to 0.00; the target
    shell's `storage_mb` is reduced by `copied_storage_mb`, restoring its
    pre-execute value exactly, and its `content_item_count` and
    `total_points_possible` are re-derived."
    PRD §3.6: "The source shell's `storage_mb` is left untouched, so the megabytes
    stored across the source-and-target pair return to their pre-execute sum."
    PRD §3.6: "The job's `copied_item_count`, `date_stripped_count` and
    `date_shifted_count` are deliberately left as the audit record of what was
    undone."
    PRD §3.3: "Whenever a content item is added to or removed from such a shell,
    whenever such a shell's `storage_mb` changes because a rollover copied into it
    or a compensation unwound the copy, and whenever a shell is purged, the owner's
    `sandbox_storage_charge_usd` is recomputed from scratch."
    PRD §3.6: "Creating, editing or removing an item re-derives the owning shell's
    `storage_mb` (the sum of its items' `storage_mb`), its `content_item_count`
    (the number of its items whose `copy_state` is not `SKIPPED`) and its
    `total_points_possible` (the sum of `points_possible` over its `ASSIGNMENT` and
    `QUIZ` items whose `copy_state` is not `SKIPPED`), and re-derives the shell
    owner's `sandbox_storage_charge_usd` for `SANDBOX` and `DEV` shells."
    PRD §2.3: "Because the topology is flat, every collection that carries a
    foreign key also accepts that foreign key as an optional filter, which is how
    the reverse direction of each relationship is reachable. Filters compose:
    supplying two of them narrows to records matching both. Filter values are also
    the state fields themselves, so a caller can ask for one lifecycle stage at a
    time."

    Design: Difficulty/compensating_invariant/rollover_compensation_returns_the_source_target_pair_to_five_hundred_seventy_stored_megabytes
    """
    s = _validated_rollover_into_an_undersized_sandbox(api)
    failed = fx.transition_rollover_job(api, s["job"]["id"], "EXECUTE")
    assert failed["job_state"] == "FAILED"

    compensated = fx.transition_rollover_job(
        api, s["job"]["id"], "COMPENSATE",
        reason="sandbox over quota; unwind the copy",
    )
    assert compensated["job_state"] == "COMPENSATED"
    assert compensated["copied_item_count"] == 3, (
        "the audit tally of what was undone is deliberately left standing"
    )

    target = fx.read_shell(api, s["target"]["id"])
    assert target["storage_mb"] == pytest.approx(0.00, abs=0.005), (
        "the target is exactly back to its pre-execute reading, not merely close"
    )
    assert target["content_item_count"] == 0
    assert target["total_points_possible"] == pytest.approx(0.00, abs=0.005)

    source = fx.read_shell(api, s["source"]["id"])
    assert source["storage_mb"] == pytest.approx(570.00, abs=0.005), (
        "the pair's stored megabytes return from 1140.00 to 570.00"
    )
    assert source["content_item_count"] == 3
    item_a = fx.read_content_item(api, s["items"][0]["id"])
    assert item_a["copy_state"] == "SOURCE", (
        "compensation touches only the copies, never the originals"
    )
    assert item_a["storage_mb"] == pytest.approx(250.00, abs=0.005)

    owner = fx.read_person(api, s["owner"]["id"])
    assert owner["sandbox_storage_charge_usd"] == pytest.approx(0.00, abs=0.005), (
        "the derived money figure rides the undo back with no residue"
    )

    skipped, skipped_meta = validate_paginated(
        api.list_content_items(
            ADMIN, params={"shell_id": s["target"]["id"], "copy_state": "SKIPPED"}
        )
    )
    assert skipped_meta["total_count"] == 3, (
        "the copies survive as provenance rather than being deleted"
    )
    assert all(
        row["storage_mb"] == pytest.approx(0.00, abs=0.005) for row in skipped
    )
    provenance, provenance_meta = validate_paginated(
        api.list_content_items(ADMIN, params={"source_item_id": s["items"][0]["id"]})
    )
    assert provenance_meta["total_count"] == 1
    assert provenance[0]["shell_id"] == s["target"]["id"]
    assert provenance[0]["copy_state"] == "SKIPPED"


def _accepted_passback_of_two_hundred_fifty_points(api):
    """An ACCEPTED passback worth 250.00 points over two graded enrollments.

    One 200.00-point ASSIGNMENT is graded 160.00 for the first student and 90.00
    for the second, the instructor stages and submits, and a registrar accepts.
    """
    setup = fx.graded_shell_setup(api, points_possible=200.00, grades=(160.00, 90.00))
    instructor = setup["instructor_headers"]
    setup["staged"] = fx.stage_passback(api, setup["shell"]["id"], instructor)
    setup["submitted"] = fx.transition_passback(
        api, setup["staged"]["id"], "SUBMIT", instructor
    )
    setup["accepted"] = fx.registrar_decide_passback(
        api, setup["staged"]["id"], "ACCEPT"
    )
    setup["term_before"] = fx.read_term(api, setup["term"]["id"])
    return setup


def test_filing_a_dispute_escrows_the_held_points_without_moving_the_total(api):
    """PRD §3.8: "**Accepting** takes `SUBMITTED` → `ACCEPTED` and sets
    `accepted_points_total` equal to `submitted_points_total`, leaving
    `disputed_points_held` at 0.00."
    PRD §3.8: "The dispute opens in `dispute_state` `OPEN` with `held_points` set
    to the enrollment's current `earned_points_total`, the enrollment's own
    `disputed_points_held` set to the same amount, and `filed_by_user_id` recorded
    from the acting user."
    PRD §3.8: "The **first** dispute against an accepted passback drives that
    passback `ACCEPTED` → `DISPUTED`, raising its `open_dispute_count` by one,
    moving the held points from accepted into disputed, and raising the term's
    `open_amendment_count` by one; a subsequent dispute against an already-disputed
    passback simply raises `open_dispute_count` and repeats the bucket move."
    PRD §2.8: "**The passback points ledger.** Once a passback has been submitted
    at least once, its `accepted_points_total` plus its `disputed_points_held`
    always equals its `submitted_points_total`. Each bucket stores an
    already-rounded two-decimal value, so the identity is exact rather than
    approximate."

    Design: Difficulty/compensating_invariant/upheld_grade_dispute_releases_the_escrow_with_a_zero_drift_two_hundred_fifty_point_ledger
    """
    s = _accepted_passback_of_two_hundred_fifty_points(api)

    assert s["shell"]["provisioning_state"] == "PUBLISHED"
    assert s["term"]["lifecycle_state"] == "FINALS"
    e1 = fx.read_enrollment(api, s["enrollments"][0]["id"])
    e2_before = fx.read_enrollment(api, s["enrollments"][1]["id"])
    assert e1["earned_points_total"] == pytest.approx(160.00, abs=0.005)
    assert e1["graded_points_possible"] == pytest.approx(200.00, abs=0.005)
    assert e2_before["earned_points_total"] == pytest.approx(90.00, abs=0.005)

    assert s["staged"]["staged_enrollment_count"] == 2
    assert s["staged"]["variant_applied"] == "PROVISIONAL"
    assert s["staged"]["submitted_points_total"] == pytest.approx(0.00, abs=0.005)
    assert s["staged"]["accepted_points_total"] == pytest.approx(0.00, abs=0.005)
    assert s["staged"]["disputed_points_held"] == pytest.approx(0.00, abs=0.005)
    assert s["submitted"]["passback_state"] == "SUBMITTED"
    assert s["submitted"]["variant_applied"] == "FINAL"
    assert s["submitted"]["submitted_points_total"] == pytest.approx(250.00, abs=0.005)
    assert s["submitted"]["accepted_points_total"] == pytest.approx(0.00, abs=0.005)
    assert s["accepted"]["passback_state"] == "ACCEPTED"
    assert s["accepted"]["accepted_points_total"] == pytest.approx(250.00, abs=0.005)
    assert s["accepted"]["disputed_points_held"] == pytest.approx(0.00, abs=0.005)
    assert_passback_ledger(s["accepted"])
    assert s["term_before"]["open_amendment_count"] == 0

    dispute = fx.file_dispute(
        api, s["staged"]["id"], s["enrollments"][1]["id"], s["item"]["id"],
        140.00, s["students"][1]["id"],
    )
    assert dispute["dispute_state"] == "OPEN"
    assert dispute["held_points"] == pytest.approx(90.00, abs=0.005), (
        "the escrow is the enrollment's stored earned total, not the claimed 140.00"
    )

    disputed = fx.read_passback(api, s["staged"]["id"])
    assert disputed["passback_state"] == "DISPUTED"
    assert disputed["accepted_points_total"] == pytest.approx(160.00, abs=0.005)
    assert disputed["disputed_points_held"] == pytest.approx(90.00, abs=0.005)
    assert disputed["submitted_points_total"] == pytest.approx(250.00, abs=0.005), (
        "filing moves points between buckets and leaves the submitted total alone"
    )
    assert disputed["open_dispute_count"] == 1
    assert_passback_ledger(disputed)

    term = fx.read_term(api, s["term"]["id"])
    assert term["open_amendment_count"] == 1
    e2 = fx.read_enrollment(api, s["enrollments"][1]["id"])
    assert e2["disputed_points_held"] == pytest.approx(90.00, abs=0.005)
    assert e2["earned_points_total"] == pytest.approx(90.00, abs=0.005), (
        "the enrollment escrows its points without losing its grade"
    )


def test_upholding_the_dispute_releases_the_escrow_with_zero_drift(api):
    """PRD §3.8: "**Upholding** takes `OPEN` → `RESOLVED_UPHELD`, stamps
    `resolved_at` from the logical clock, leaves `adjusted_earned_points` null,
    leaves the enrollment's `earned_points_total` untouched while zeroing its
    `disputed_points_held`, and returns the held points from the passback's
    disputed bucket to its accepted bucket, restoring the accepted total to its
    pre-filing value with zero drift."
    PRD §3.8: "Filing followed by upholding is the compensating pair and must
    restore all three buckets to their pre-filing values with zero drift."
    PRD §3.8: "When the last open dispute resolves and **every** resolution in that
    round was upheld, the passback returns `DISPUTED` → `ACCEPTED` and the term's
    `open_amendment_count` falls by one — the round is ledger-neutral and costs the
    term nothing."
    PRD §2.5: "Timestamps the server stamps itself — `dropped_at`, `resolved_at`,
    `closed_at` — are taken from the logical clock at the moment of the transition."
    PRD §3.2: "`GRADING` → `CLOSED` first requires the term's
    `open_amendment_count` to be 0, meaning no passback of the term is sitting in
    `DISPUTED` or `AMENDED`; otherwise it is refused with
    `ERR_OPEN_DISPUTES_BLOCK_CLOSE`."

    Design: Difficulty/compensating_invariant/upheld_grade_dispute_releases_the_escrow_with_a_zero_drift_two_hundred_fifty_point_ledger
    """
    s = _accepted_passback_of_two_hundred_fifty_points(api)
    dispute = fx.file_dispute(
        api, s["staged"]["id"], s["enrollments"][1]["id"], s["item"]["id"],
        140.00, s["students"][1]["id"],
    )
    assert dispute["held_points"] == pytest.approx(90.00, abs=0.005)

    resolved = fx.resolve_dispute(
        api, dispute["id"], "UPHELD", s["instructor_headers"],
        note="regrade confirms the original mark",
    )
    assert resolved["dispute_state"] == "RESOLVED_UPHELD"
    assert resolved["adjusted_earned_points"] is None, (
        "upholding changes no grade, so no adjusted figure is recorded"
    )
    assert resolved["resolved_at"].startswith("2026-08-01T00:00:00"), (
        "the resolution instant comes from the logical clock, which has not been "
        "moved off its startup reading"
    )

    passback = fx.read_passback(api, s["staged"]["id"])
    assert passback["accepted_points_total"] == pytest.approx(250.00, abs=0.005), (
        "an implementation that added the held points to the submitted total on "
        "release would read 340.00 there instead"
    )
    assert passback["disputed_points_held"] == pytest.approx(0.00, abs=0.005)
    assert passback["submitted_points_total"] == pytest.approx(250.00, abs=0.005)
    assert_passback_ledger(passback)
    assert passback["passback_state"] == "ACCEPTED"
    assert passback["open_dispute_count"] == 0
    assert passback["amendment_round"] == 0, (
        "an all-upheld round is ledger-neutral and must not amend the passback"
    )

    e2 = fx.read_enrollment(api, s["enrollments"][1]["id"])
    assert e2["disputed_points_held"] == pytest.approx(0.00, abs=0.005)
    assert e2["earned_points_total"] == pytest.approx(90.00, abs=0.005)
    assert e2["final_grade_pct"] == pytest.approx(45.00, abs=0.005), (
        "90.00 over the shell's 200.00 total_points_possible, released without "
        "re-running the grade"
    )

    term = fx.read_term(api, s["term"]["id"])
    assert term["open_amendment_count"] == 0
    grading = fx.transition_term(api, s["term"]["id"], "GRADING")
    assert grading["lifecycle_state"] == "GRADING"
    closed = fx.transition_term(api, s["term"]["id"], "CLOSED")
    assert closed["lifecycle_state"] == "CLOSED", (
        "a residual amendment count would have refused this transition, so closing "
        "proves the parent counter really came back"
    )
