"""Dual-variant calculations: the rollover date projection and the grade percentage.

Both calculations expose two variants over byte-identical stored inputs, so each
test pins the exact stored figure the PRD derives for one variant and shows the
other variant disagreeing.
"""
from prd_bench_local_runner.testing import get_success_data

from test_helpers import fixtures as fx
from test_helpers.test_users import make_instructor_headers


# ─── rollover due-date projection ─────────────────────────────────────────

SOURCE_ITEM = {
    "item_type": "ASSIGNMENT",
    "title": "Midterm Project",
    "due_at": "2026-03-03T00:00:00Z",
    "points_possible": 40.00,
    "storage_mb": 5.00,
}


def _target_items(api, shell_id, headers):
    return get_success_data(api.list_content_items(headers, params={"shell_id": shell_id}))


def test_anchor_proportional_projection_stretches_the_due_date(api, lms_admin_headers):
    """A rolled-over item keeps its fractional position in the target span.

    PRD §3.6: "The projected instant is the target term's `term_start_at` plus
    the ratio multiplied by the target span, rounded half up to a whole number of
    seconds." and: "With a source term running from 2026-01-12T00:00:00Z to
    2026-04-22T00:00:00Z (100 days), a target term running from
    2026-08-24T00:00:00Z to 2026-12-11T00:00:00Z (109 days), and a source item
    due at 2026-03-03T00:00:00Z — an offset of 50 days, a ratio of exactly 0.50 —
    `ANCHOR_PROPORTIONAL` projects 2026-10-17T12:00:00Z, while `FIXED_OFFSET`
    shifts by 224 days divided by 7, that is 32 whole weeks or 224 days, and
    projects 2026-10-13T00:00:00Z: four days and twelve hours apart from the same
    input."
    PRD §3.6 also fixes the copy's provenance: "Otherwise a copy is created in
    the target shell with `copy_state` `COPIED` and `source_item_id` set to the
    source item's identifier".

    Design: Difficulty/dual_variant_calc/rollover_due_date_projection_variant_divergence_on_content_item_calendar
    """
    setup = fx.rollover_pair_setup(api, source_items=[dict(SOURCE_ITEM)], target_count=1)
    source_item = setup["source_items"][0]

    job = fx.validated_rollover_job(
        api,
        setup["source_shell"]["id"],
        setup["target_shells"][0],
        setup["target_term"]["id"],
        strip_dates=False,
        strip_submissions=True,
        strip_grades=True,
        date_shift_mode="ANCHOR_PROPORTIONAL",
    )
    assert job["job_state"] == "VALIDATED"
    assert job["eligible_item_count"] == 1

    executed = fx.transition_rollover_job(api, job["id"], "EXECUTE")
    assert executed["job_state"] == "COMPLETED"
    assert executed["copied_item_count"] == 1
    assert executed["date_shifted_count"] == 1
    assert executed["date_stripped_count"] == 0

    copies = _target_items(api, setup["target_shells"][0]["id"], lms_admin_headers)
    assert len(copies) == 1
    copy = copies[0]
    assert copy["due_at"] == "2026-10-17T12:00:00Z"
    assert copy["copy_state"] == "COPIED"
    assert copy["source_item_id"] == source_item["id"]
    assert copy["date_stripped"] is False


def test_fixed_offset_projection_diverges_and_leaves_the_source_item_alone(
    api, lms_admin_headers
):
    """The same source item projects four days twelve hours earlier under FIXED_OFFSET.

    PRD §3.6: "Under **`FIXED_OFFSET`** the item keeps its day of the week
    instead. The gap between the two term starts is converted to a whole number
    of weeks by dividing by 604,800 seconds and rounding **down**; the item's
    `due_at` is shifted forward by exactly that many weeks; and the result is then
    clamped into the closed range from the target term's `term_start_at` to its
    `term_end_at`." and: "With a source term running from 2026-01-12T00:00:00Z to
    2026-04-22T00:00:00Z (100 days), a target term running from
    2026-08-24T00:00:00Z to 2026-12-11T00:00:00Z (109 days), and a source item
    due at 2026-03-03T00:00:00Z — an offset of 50 days, a ratio of exactly 0.50 —
    `ANCHOR_PROPORTIONAL` projects 2026-10-17T12:00:00Z, while `FIXED_OFFSET`
    shifts by 224 days divided by 7, that is 32 whole weeks or 224 days, and
    projects 2026-10-13T00:00:00Z: four days and twelve hours apart from the same
    input."
    A new item's own state is fixed by §3.6: "A new item opens with `copy_state`
    `SOURCE`, `date_stripped` false, `submission_count` 0, `has_submissions` false
    and `source_item_id` null — the last field is the copy-provenance
    self-reference, filled in only on rollover copies."

    Design: Difficulty/dual_variant_calc/rollover_due_date_projection_variant_divergence_on_content_item_calendar
    """
    setup = fx.rollover_pair_setup(api, source_items=[dict(SOURCE_ITEM)], target_count=2)
    source_item = setup["source_items"][0]
    shell_a, shell_b = setup["target_shells"]

    job_a = fx.validated_rollover_job(
        api, setup["source_shell"]["id"], shell_a, setup["target_term"]["id"],
        strip_dates=False, strip_submissions=True, strip_grades=True,
        date_shift_mode="ANCHOR_PROPORTIONAL",
    )
    job_b = fx.validated_rollover_job(
        api, setup["source_shell"]["id"], shell_b, setup["target_term"]["id"],
        strip_dates=False, strip_submissions=True, strip_grades=True,
        date_shift_mode="FIXED_OFFSET",
    )
    assert fx.transition_rollover_job(api, job_a["id"], "EXECUTE")["job_state"] == "COMPLETED"
    assert fx.transition_rollover_job(api, job_b["id"], "EXECUTE")["job_state"] == "COMPLETED"

    copy_a = _target_items(api, shell_a["id"], lms_admin_headers)[0]
    copy_b = _target_items(api, shell_b["id"], lms_admin_headers)[0]
    assert copy_a["due_at"] == "2026-10-17T12:00:00Z"
    assert copy_b["due_at"] == "2026-10-13T00:00:00Z"
    assert copy_a["due_at"] != copy_b["due_at"]

    # The source item is read, never rewritten, by either projection.
    still_source = fx.read_content_item(api, source_item["id"], lms_admin_headers)
    assert still_source["due_at"] == "2026-03-03T00:00:00Z"
    assert still_source["copy_state"] == "SOURCE"
    assert still_source["date_stripped"] is False
    assert still_source["source_item_id"] is None


# ─── grade percentage variants ────────────────────────────────────────────

def _gradebook_setup(api):
    """One published shell, two gradable items (60.00 + 20.00) and one graded student."""
    term = fx.create_term_in_state(api, "REGISTRATION_OPEN")
    owner = fx.create_faculty(api)
    instructor = make_instructor_headers(owner["id"])
    shell = fx.provision_shell(api, term["id"], owner["id"], base_seat_cap=10)
    fx.publish(api, shell["id"])
    student = fx.create_student(api)
    enrollment = fx.enrol(api, shell["id"], student["id"], "ACTIVE")
    item_a = fx.create_content_item(
        api, shell["id"], instructor, item_type="ASSIGNMENT", title="Essay",
        points_possible=60.00, storage_mb=0.00,
    )
    fx.create_content_item(
        api, shell["id"], instructor, item_type="QUIZ", title="Quiz 1",
        points_possible=20.00, storage_mb=0.00,
    )
    graded = fx.record_grade(api, enrollment["id"], item_a["id"], 50.00, instructor)
    fx.transition_term(api, term["id"], "IN_SESSION")
    fx.transition_term(api, term["id"], "FINALS")
    return {
        "term": term,
        "instructor": instructor,
        "shell": fx.read_shell(api, shell["id"]),
        "enrollment": enrollment,
        "graded": graded,
    }


def test_provisional_variant_divides_by_the_enrollments_graded_points(api):
    """50.00 over a graded_points_possible of 60.00 stores 83.33.

    PRD §3.8: "The **provisional** variant divides by the enrollment's own
    `graded_points_possible` — the work graded so far — which flatters an
    incomplete gradebook, and it writes `provisional_grade_pct`."
    PRD §3.8 also fixes the grade-record bookkeeping: "Each write re-derives the
    enrollment's `earned_points_total` as the sum of its grade records and its
    `graded_points_possible` as the sum of the `points_possible` of the items it
    now carries a record for, and re-derives that enrollment's
    `provisional_grade_pct`."
    And the staged passback: "The passback opens in `passback_state` `STAGED` with
    `term_id` copied from the shell, `variant_applied` `PROVISIONAL`,
    `staged_enrollment_count` set to the number of gradable rows described above,
    and every provisional percentage computed."

    Design: Difficulty/dual_variant_calc/final_grade_percentage_variant_divergence_on_enrollment_gradebook
    """
    setup = _gradebook_setup(api)
    graded = setup["graded"]
    assert graded["earned_points_total"] == 50.00
    assert graded["graded_points_possible"] == 60.00
    assert graded["provisional_grade_pct"] == 83.33
    assert setup["shell"]["total_points_possible"] == 80.00

    passback = fx.stage_passback(api, setup["shell"]["id"], setup["instructor"])
    assert passback["passback_state"] == "STAGED"
    assert passback["variant_applied"] == "PROVISIONAL"
    assert passback["staged_enrollment_count"] == 1
    assert passback["submitted_points_total"] == 0.00
    assert passback["accepted_points_total"] == 0.00
    assert passback["disputed_points_held"] == 0.00


def test_submitting_switches_the_denominator_to_the_shells_total_points(api):
    """SUBMIT recomputes the same 50.00 against 80.00 and stores 62.50 beside the 83.33.

    PRD §3.8: "The **final** variant divides by the shell's
    `total_points_possible` — every gradable point in the shell, graded or not —
    so missing work drags the figure down, and it writes `final_grade_pct`."
    PRD §3.8: "On identical stored grades the two disagree: an
    `earned_points_total` of 50.00 against a `graded_points_possible` of 60.00
    gives 83.33, while the same 50.00 against a shell `total_points_possible` of
    80.00 gives 62.50, and that 20.83-point gap is exactly what the registrar sees
    between the staged and the submitted figures."
    PRD §3.8: "Submitting flips `variant_applied` to `FINAL`, recomputes every
    staged enrollment's `final_grade_pct` under the final variant, sets
    `submitted_points_total` to the sum of the staged enrollments'
    `earned_points_total`, and sets `accepted_points_total` and
    `disputed_points_held` to 0.00."

    Design: Difficulty/dual_variant_calc/final_grade_percentage_variant_divergence_on_enrollment_gradebook
    """
    setup = _gradebook_setup(api)
    passback = fx.stage_passback(api, setup["shell"]["id"], setup["instructor"])
    assert passback["variant_applied"] == "PROVISIONAL"

    submitted = fx.transition_passback(
        api, passback["id"], "SUBMIT", setup["instructor"]
    )
    assert submitted["passback_state"] == "SUBMITTED"
    assert submitted["variant_applied"] == "FINAL"
    assert submitted["submitted_points_total"] == 50.00
    assert submitted["accepted_points_total"] == 0.00
    assert submitted["disputed_points_held"] == 0.00

    enrollment = fx.read_enrollment(api, setup["enrollment"]["id"])
    assert enrollment["final_grade_pct"] == 62.50
    # The provisional figure is retained, so the 20.83-point gap stays visible.
    assert enrollment["provisional_grade_pct"] == 83.33
    assert enrollment["earned_points_total"] == 50.00
    assert fx.read_shell(api, setup["shell"]["id"])["total_points_possible"] == 80.00
