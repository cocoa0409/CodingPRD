"""Endpoint breadth: computed reads, nested collections and filtered listings."""

import pytest
from prd_bench_local_runner.testing import validate_paginated

from test_helpers import (
    assert_acre_feet,
    assert_cents,
    assert_compliance_summary_shape,
    assert_created_at_ascending,
    assert_ids_in_order,
    assert_instant,
    assert_penalty_preview_shape,
    assert_score,
    assert_sweep_result_shape,
    assert_total_count,
)
from test_helpers import factories as f
from test_helpers.constants import (
    CATEGORY_EROSION,
    CATEGORY_SEEPAGE,
    CATEGORY_STRUCTURAL,
    CLOCK_ORIGIN,
    DEFICIENCY_OPEN,
    DEFICIENCY_ORDERED,
    DELINQUENCY_CURRENT,
    DELINQUENCY_DELINQUENT,
    EAP_APPROVED,
    EAP_SUPERSEDED,
    ENTRY_CIVIL_PENALTY,
    EXERCISE_FUNCTIONAL,
    EXERCISE_TABLETOP,
    HAZARD_SIGNIFICANT,
    ORDER_ISSUED,
    ORDER_TYPE_NOTICE,
    REG_REGISTERED,
    SAFETY_UNRATED,
    SEVERITY_MINOR,
    SEVERITY_MODERATE,
    SEVERITY_SERIOUS,
    SOURCE_INSPECTION,
    SOURCE_SYSTEM_EXERCISE,
)
from test_helpers.test_users import make_owner_headers


# ---------------------------------------------------------------------------
# The compliance summary is a pure projection over five aggregates
# ---------------------------------------------------------------------------
@pytest.fixture()
def reconciled_dam(program, base):
    """A SIGNIFICANT dam with an approved plan, a clean drill and an unpaid penalty."""
    program.classify_significant(base.dam_id, base.engineer_a_id)
    plan = program.approved_plan(base.dam_id, base.owner_id, base.engineer_b_id)
    program.log_exercise(
        plan["id"],
        make_owner_headers(base.owner_id),
        exercise_type=EXERCISE_TABLETOP,
        conducted_at=CLOCK_ORIGIN,
        participant_count=4,
        notification_test_passed=True,
    )
    program.post_ledger_entry(
        base.owner_id,
        entry_type=ENTRY_CIVIL_PENALTY,
        amount_cents=30_000,
        memo="Unpaid civil penalty carried on the account.",
    )
    return plan


def test_the_summary_reports_the_classification_and_schedule_block(
    program, base, reconciled_dam
):
    """One read reconciles the hazard dial, the safety dial and the inspection clock.

    PRD 3.1: "It reconciles everything the program knows about the structure at the moment of the call, and returns exactly these keys: `dam_id`, `hazard_class`, `safety_status`, `regulatory_status`, `current_consequence_score`, `next_inspection_due_at`, `inspection_overdue`, `open_deficiency_count`, `escalated_deficiency_count` (the number of the dam's deficiencies currently in `ESCALATED`), `latest_eap_status`, `eap_expires_at` (the `expires_at` of the plan that `latest_eap_status` reports, null when the dam has no plan or the plan has no expiry), `eap_exercise_current` (the exercise-currency flag of the dam's `APPROVED` plan, false when there is no approved plan), `outstanding_penalty_cents` (the sum of `assessed_penalty_cents` across all of the dam's remediation orders, where orders that never defaulted contribute 0), `owner_delinquency_status`, `committed_drawdown_acre_ft` and `available_conservation_storage_acre_ft`."

    Design: Corner/endpoints/compliance_summary_reconciles_classification_plan_and_fiscal_state
    """
    assert reconciled_dam["status"] == EAP_APPROVED
    summary = program.summary(base.dam_id, make_owner_headers(base.owner_id))
    assert_compliance_summary_shape(summary)

    assert summary["dam_id"] == base.dam_id
    assert summary["hazard_class"] == HAZARD_SIGNIFICANT
    assert summary["safety_status"] == SAFETY_UNRATED
    assert summary["regulatory_status"] == REG_REGISTERED
    assert_score(summary["current_consequence_score"], 6.60)
    assert_instant(
        summary["next_inspection_due_at"],
        "2021-04-15T00:00:00Z",
        "next_inspection_due_at",
    )
    assert summary["inspection_overdue"] is True
    assert summary["open_deficiency_count"] == 0
    assert summary["escalated_deficiency_count"] == 0


def test_the_summary_reports_the_plan_fiscal_and_storage_block(
    program, base, reconciled_dam
):
    """Plan currency, the owner's ledger position and the reservoir split all appear.

    PRD 3.1: "It reconciles everything the program knows about the structure at the moment of the call, and returns exactly these keys: `dam_id`, `hazard_class`, `safety_status`, `regulatory_status`, `current_consequence_score`, `next_inspection_due_at`, `inspection_overdue`, `open_deficiency_count`, `escalated_deficiency_count` (the number of the dam's deficiencies currently in `ESCALATED`), `latest_eap_status`, `eap_expires_at` (the `expires_at` of the plan that `latest_eap_status` reports, null when the dam has no plan or the plan has no expiry), `eap_exercise_current` (the exercise-currency flag of the dam's `APPROVED` plan, false when there is no approved plan), `outstanding_penalty_cents` (the sum of `assessed_penalty_cents` across all of the dam's remediation orders, where orders that never defaulted contribute 0), `owner_delinquency_status`, `committed_drawdown_acre_ft` and `available_conservation_storage_acre_ft`."

    Design: Corner/endpoints/compliance_summary_reconciles_classification_plan_and_fiscal_state
    """
    summary = program.summary(base.dam_id)
    assert summary["latest_eap_status"] == EAP_APPROVED
    assert_instant(
        summary["eap_expires_at"], "2031-08-01T00:00:00Z", "eap_expires_at"
    )
    assert summary["eap_exercise_current"] is True

    # The 30,000-cent ledger penalty was never assessed by a defaulted order.
    assert_cents(summary["outstanding_penalty_cents"], 0, "outstanding_penalty_cents")
    assert summary["owner_delinquency_status"] == DELINQUENCY_DELINQUENT

    assert_acre_feet(
        summary["committed_drawdown_acre_ft"], 0.000, "committed_drawdown_acre_ft"
    )
    assert_acre_feet(
        summary["available_conservation_storage_acre_ft"],
        1500.000,
        "available_conservation_storage_acre_ft",
    )


def test_taking_the_snapshot_writes_nothing_to_the_dam(program, base, reconciled_dam):
    """The overdue flag is recomputed for the reader, not stored by the read.

    PRD 3.1: "Producing the snapshot recomputes the inspection schedule and the exercise-currency flag against the current clock, so a snapshot taken after the clock has advanced past a due date reports `inspection_overdue` as true even before any sweep has run."

    Design: Corner/endpoints/compliance_summary_reconciles_classification_plan_and_fiscal_state
    """
    before = program.get_dam(base.dam_id)
    assert before["inspection_overdue"] is True

    first = program.summary(base.dam_id)
    second = program.summary(base.dam_id)
    assert first["inspection_overdue"] is True
    assert second["inspection_overdue"] is True

    after = program.get_dam(base.dam_id)
    assert after["version"] == before["version"]
    assert after["open_deficiency_count"] == 0
    assert len(program.plans_for(base.dam_id)) == 1


# ---------------------------------------------------------------------------
# The penalty preview on a live order
# ---------------------------------------------------------------------------
@pytest.fixture()
def live_order(program, base):
    """A 30-day NOTICE_OF_DEFICIENCY order on a MODERATE seepage finding."""
    program.classify_significant(base.dam_id, base.engineer_a_id)
    visit = program.schedule_inspection(base.dam_id, base.engineer_a_id)
    program.set_clock("2026-08-05T13:00:00Z")
    program.submit_inspection(
        visit["id"],
        base.engineer_a_id,
        performed_at="2026-08-05T12:00:00Z",
        deficiencies=[
            f.deficiency_item(
                category=CATEGORY_SEEPAGE,
                severity=SEVERITY_MODERATE,
                description="Toe seepage carrying fines after the spring runoff.",
            )
        ],
    )
    deficiency = program.deficiencies_for(base.dam_id)[0]
    order = program.issue_order(
        deficiency["id"],
        order_type=ORDER_TYPE_NOTICE,
        requested_response_days=30,
    )
    return {"deficiency": deficiency, "order": order}


def test_the_state_may_grant_less_time_than_the_schedule_allows(live_order):
    """Thirty requested days beat the sixty-seven-day statutory allowance.

    PRD 3.4: "The result is the schedule's allowance, and `effective_response_days` is the smaller of `requested_response_days` and that allowance."

    Design: Corner/endpoints/penalty_preview_reports_zero_before_the_deadline_passes
    """
    order = live_order["order"]
    assert order["effective_response_days"] == 30
    assert_instant(
        order["compliance_deadline_at"],
        "2026-09-04T13:00:00Z",
        "compliance_deadline_at",
    )
    assert_cents(order["daily_penalty_rate_cents"], 6250, "daily_penalty_rate_cents")
    assert order["status"] == ORDER_ISSUED


def test_the_preview_returns_exactly_its_five_declared_keys(program, base, live_order):
    """The owner served may preview the exposure, and the payload is closed.

    PRD 3.4: "The preview applies **no cap and no abatement** and returns exactly `order_id`, `overdue_days`, `daily_penalty_rate_cents`, `provisional_penalty_cents` and `response_filed` (true exactly when `response_filed_at` is non-null)."

    Design: Corner/endpoints/penalty_preview_reports_zero_before_the_deadline_passes
    """
    preview = program.penalty_preview(
        live_order["order"]["id"], make_owner_headers(base.owner_id)
    )
    assert_penalty_preview_shape(preview)
    assert preview["order_id"] == live_order["order"]["id"]
    assert_cents(preview["daily_penalty_rate_cents"], 6250, "daily_penalty_rate_cents")
    assert preview["response_filed"] is False


def test_a_clock_inside_the_response_window_previews_nothing_owed(
    program, live_order
):
    """Nothing has been missed yet, so the accrual has not begun.

    PRD 3.4: "The number of overdue days is the count of whole days by which the current logical clock exceeds `compliance_deadline_at` — the elapsed interval rounded down to whole days, and 0 when the clock is at or before the deadline."

    Design: Corner/endpoints/penalty_preview_reports_zero_before_the_deadline_passes
    """
    order_id = live_order["order"]["id"]
    preview = program.penalty_preview(order_id)
    assert preview["overdue_days"] == 0
    assert_cents(preview["provisional_penalty_cents"], 0, "provisional_penalty_cents")

    # Previewing is a read: the order keeps its state and its zero assessment.
    stored = program.get_order(order_id)
    assert stored["status"] == ORDER_ISSUED
    assert_cents(stored["assessed_penalty_cents"], 0, "assessed_penalty_cents")
    assert stored["defaulted_at"] is None


# ---------------------------------------------------------------------------
# The deficiency listing under three orthogonal filters
# ---------------------------------------------------------------------------
@pytest.fixture()
def three_findings(program, base):
    """One submitted inspection reporting SERIOUS, MODERATE and MINOR findings."""
    program.classify_significant(base.dam_id, base.engineer_a_id)
    visit = program.schedule_inspection(base.dam_id, base.engineer_a_id)
    program.set_clock("2026-08-05T13:00:00Z")
    program.submit_inspection(
        visit["id"],
        base.engineer_a_id,
        performed_at="2026-08-05T12:00:00Z",
        deficiencies=[
            f.deficiency_item(
                category=CATEGORY_STRUCTURAL,
                severity=SEVERITY_SERIOUS,
                description="Spalling and exposed reinforcement on the training wall.",
            ),
            f.deficiency_item(
                category=CATEGORY_SEEPAGE,
                severity=SEVERITY_MODERATE,
                description="Damp patch on the downstream slope near the toe.",
            ),
            f.deficiency_item(
                category=CATEGORY_EROSION,
                severity=SEVERITY_MINOR,
                description="Rill erosion on the access ramp shoulder.",
            ),
        ],
    )
    rows = program.deficiencies_for(base.dam_id)
    return {"visit": visit, "rows": rows}


def test_the_status_and_source_filters_read_the_same_three_rows(
    api, program, base, three_findings
):
    """All three findings are open and inspection-born, and no drill row exists.

    PRD 3.4: "They can be listed filtered by `dam_id`, `inspection_id`, `status`, `severity`, `source` and `category`, and read individually."

    Design: Corner/endpoints/deficiency_listing_filters_by_status_severity_and_source
    """
    visit_id = three_findings["visit"]["id"]
    open_rows, open_meta = validate_paginated(
        api.list_deficiencies(
            base.engineer_a_headers,
            {"dam_id": base.dam_id, "status": DEFICIENCY_OPEN},
        )
    )
    assert_total_count(open_meta, 3)
    for row in open_rows:
        assert row["source"] == SOURCE_INSPECTION
        assert row["inspection_id"] == visit_id

    drill_rows, drill_meta = validate_paginated(
        api.list_deficiencies(
            program.admin,
            {"dam_id": base.dam_id, "source": SOURCE_SYSTEM_EXERCISE},
        )
    )
    assert drill_rows == []
    assert_total_count(drill_meta, 0)


def test_the_first_page_of_two_reports_more_rows_behind_it(
    api, program, base, three_findings
):
    """The window is two rows wide, and the count outside it is still reported.

    PRD 2.3: "List results are ordered by `created_at` ascending in every case — never by `id`, and never by any domain field, even where a domain ordering (such as ledger `sequence_no`) coincides with insertion order."

    Design: Corner/endpoints/deficiency_listing_filters_by_status_severity_and_source
    """
    rows = three_findings["rows"]
    page, meta = validate_paginated(
        api.list_deficiencies(
            program.admin, {"dam_id": base.dam_id, "limit": 2, "offset": 0}
        )
    )
    assert len(page) == 2
    assert_created_at_ascending(page)
    assert_ids_in_order(page, [rows[0]["id"], rows[1]["id"]])
    assert page[0]["severity"] == SEVERITY_SERIOUS
    assert page[1]["severity"] == SEVERITY_MODERATE
    assert meta["has_more"] is True
    assert_total_count(meta, 3)
    assert rows[2]["severity"] == SEVERITY_MINOR


def test_the_status_filter_follows_the_row_that_moves_to_ordered(
    api, program, base, three_findings
):
    """Issuing an order changes which page the finding appears on, not the open count.

    PRD 3.4: "Enforcement begins when program staff issue a **remediation order** against a deficiency that is `OPEN` or `ESCALATED`, moving it `OPEN → ORDERED`; the dam must not be `BREACHED`."

    Design: Corner/endpoints/deficiency_listing_filters_by_status_severity_and_source
    """
    serious_id = three_findings["rows"][0]["id"]
    program.issue_order(
        serious_id, order_type=ORDER_TYPE_NOTICE, requested_response_days=20
    )

    still_open, open_meta = validate_paginated(
        api.list_deficiencies(
            program.admin, {"dam_id": base.dam_id, "status": DEFICIENCY_OPEN}
        )
    )
    assert_total_count(open_meta, 2)
    assert serious_id not in [row["id"] for row in still_open]

    ordered, ordered_meta = validate_paginated(
        api.list_deficiencies(
            program.admin,
            {
                "dam_id": base.dam_id,
                "status": DEFICIENCY_ORDERED,
                "category": CATEGORY_STRUCTURAL,
            },
        )
    )
    assert_total_count(ordered_meta, 1)
    assert_ids_in_order(ordered, [serious_id])
    assert ordered[0]["order_count"] == 1

    # An ordered finding is still an open finding as far as the dam is concerned.
    assert program.get_dam(base.dam_id)["open_deficiency_count"] == 3


# ---------------------------------------------------------------------------
# Nested exercise listings stay attached to their own plan revision
# ---------------------------------------------------------------------------
@pytest.fixture()
def two_plan_revisions(program, base):
    """A superseded plan and its replacement, each carrying one accepted drill."""
    program.classify_significant(base.dam_id, base.engineer_a_id)
    r0 = program.approved_plan(base.dam_id, base.owner_id, base.engineer_b_id)
    program.log_exercise(
        r0["id"],
        make_owner_headers(base.owner_id),
        exercise_type=EXERCISE_TABLETOP,
        conducted_at="2026-07-01T00:00:00Z",
        participant_count=4,
        notification_test_passed=True,
    )
    r1 = program.approved_plan(
        base.dam_id,
        base.owner_id,
        base.engineer_b_id,
        version_label="2026 Rev B",
    )
    program.log_exercise(
        r1["id"],
        program.coordinator,
        exercise_type=EXERCISE_FUNCTIONAL,
        conducted_at="2026-07-20T00:00:00Z",
        participant_count=4,
        notification_test_passed=True,
    )
    return {"r0": r0, "r1": r1}


def test_each_nested_listing_returns_only_its_own_revisions_drill(
    api, program, base, two_plan_revisions
):
    """Superseding a plan leaves its exercise history exactly where it was logged.

    PRD 3.5: "Approval also supersedes the incumbent: any other plan on the same dam whose status is `APPROVED` moves `APPROVED → SUPERSEDED`, which is terminal, keeping its own `expires_at` for the audit record and keeping every exercise already logged against it attached to it."

    Design: Corner/endpoints/nested_exercise_listing_stays_scoped_to_its_own_plan_revision
    """
    old_rows, old_meta = validate_paginated(
        api.list_exercises(
            two_plan_revisions["r0"]["id"], make_owner_headers(base.owner_id)
        )
    )
    assert_total_count(old_meta, 1)
    assert old_rows[0]["exercise_type"] == EXERCISE_TABLETOP
    assert_instant(old_rows[0]["conducted_at"], "2026-07-01T00:00:00Z", "conducted_at")

    new_rows, new_meta = validate_paginated(
        api.list_exercises(two_plan_revisions["r1"]["id"], program.coordinator)
    )
    assert_total_count(new_meta, 1)
    assert new_rows[0]["exercise_type"] == EXERCISE_FUNCTIONAL
    assert_instant(new_rows[0]["conducted_at"], "2026-07-20T00:00:00Z", "conducted_at")


def test_the_superseded_revision_keeps_its_count_but_not_the_currency(
    program, base, two_plan_revisions
):
    """The replacement restarts the obligation while the old record stays intact.

    PRD 3.5: "Exercises attached to a `SUPERSEDED` or `EXPIRED` plan never count towards currency, however recent they are, which is why an approval that supersedes an incumbent plan starts the exercise obligation over."

    Design: Corner/endpoints/nested_exercise_listing_stays_scoped_to_its_own_plan_revision
    """
    old = program.get_plan(two_plan_revisions["r0"]["id"])
    assert old["status"] == EAP_SUPERSEDED
    assert old["accepted_exercise_count"] == 1

    new = program.get_plan(two_plan_revisions["r1"]["id"])
    assert new["status"] == EAP_APPROVED
    assert new["accepted_exercise_count"] == 1
    assert new["exercise_current"] is True

    superseded = program.plans_for(base.dam_id, status=EAP_SUPERSEDED)
    assert_ids_in_order(superseded, [two_plan_revisions["r0"]["id"]])
    assert program.get_dam(base.dam_id)["latest_eap_status"] == EAP_APPROVED


# ---------------------------------------------------------------------------
# The compliance sweep with nothing due
# ---------------------------------------------------------------------------
@pytest.fixture()
def quiet_program(program):
    """A single recently registered SIGNIFICANT dam and nothing else in flight."""
    setup = program.bootstrap(
        clock=None, dam={"registered_at": "2026-06-01T00:00:00Z"}
    )
    program.classify_significant(setup.dam_id, setup.engineer_a_id)
    return setup


def test_a_sweep_with_nothing_due_returns_every_counter_at_zero(
    program, quiet_program
):
    """The bulk enforcement run is a safe no-op on an empty input set.

    PRD 3.9: "A sweep on a program with nothing due is a legitimate no-op that returns zeros."

    Design: Corner/endpoints/compliance_sweep_on_a_quiet_program_reports_all_zero_counts
    """
    result = program.sweep()
    assert_sweep_result_shape(result)
    assert_instant(result["swept_at"], CLOCK_ORIGIN, "swept_at")

    assert result["defaulted_order_count"] == 0
    assert result["defaulted_order_ids"] == []
    assert result["escalated_deficiency_count"] == 0
    assert result["referred_order_count"] == 0
    assert result["expired_eap_count"] == 0
    assert_cents(result["penalty_cents_assessed"], 0, "penalty_cents_assessed")
    assert result["newly_delinquent_owner_count"] == 0
    assert result["dams_moved_under_enforcement"] == 0

    _rows, meta = program.ledger(quiet_program.owner_id)
    assert_total_count(meta, 0)
    assert (
        program.get_owner(quiet_program.owner_id)["delinquency_status"]
        == DELINQUENCY_CURRENT
    )


def test_the_sweep_recomputes_the_overdue_flag_without_disturbing_the_dam(
    program, quiet_program
):
    """A dam inspected on a 24-month clock from June 2026 is not yet due.

    PRD 3.9: "Fourth, the sweep recomputes `inspection_overdue` for every dam in the inventory against the current logical clock, on the schedule rule of §3.3."

    Design: Corner/endpoints/compliance_sweep_on_a_quiet_program_reports_all_zero_counts
    """
    before = program.get_dam(quiet_program.dam_id)
    assert_instant(
        before["next_inspection_due_at"],
        "2028-06-01T00:00:00Z",
        "next_inspection_due_at",
    )

    result = program.sweep()
    assert result["overdue_inspection_count"] == 0

    after = program.get_dam(quiet_program.dam_id)
    assert after["version"] == before["version"]
    assert after["regulatory_status"] == REG_REGISTERED
    assert after["safety_status"] == SAFETY_UNRATED
    assert after["inspection_overdue"] is False
