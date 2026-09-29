"""Cross-cutting breadth: stale views, the hub counter and reconciled counters."""

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    assert_acre_feet,
    assert_cfs,
    assert_instant,
    assert_total_count,
)
from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    ASSESSMENT_DRAFT,
    CATEGORY_EAP_EXERCISE,
    CATEGORY_OPERATIONAL,
    CATEGORY_STRUCTURAL,
    DEFICIENCY_CLOSED_VERIFIED,
    DEFICIENCY_OPEN,
    DEFICIENCY_ORDERED,
    DEFICIENCY_REMEDIATION_SUBMITTED,
    DRAWDOWN_COORDINATED,
    DRAWDOWN_REQUESTED,
    EAP_DRAFT,
    EAP_SUBMITTED,
    EXERCISE_DEFICIENT,
    EXERCISE_TABLETOP,
    HAZARD_SIGNIFICANT,
    HAZARD_UNCLASSIFIED,
    ORDER_SATISFIED,
    ORDER_TYPE_NOTICE,
    REASON_NOTIFICATION_TEST_FAILED,
    REG_REGISTERED,
    SAFETY_POOR,
    SEVERITY_MINOR,
    SEVERITY_MODERATE,
    SEVERITY_SERIOUS,
    SOURCE_INSPECTION,
    SOURCE_SYSTEM_EXERCISE,
    VERIFY_SATISFIED,
)


# ---------------------------------------------------------------------------
# A plan drafted against the pre-certification dam
# ---------------------------------------------------------------------------
@pytest.fixture()
def reclassified_dam(program, base):
    """The dam's version as the owner last saw it, before certification moved it."""
    stale_version = program.dam_version(base.dam_id)
    program.classify_significant(base.dam_id, base.engineer_a_id)
    return {"stale_version": stale_version}


def test_a_plan_quoting_the_pre_certification_version_is_refused(
    api, program, base, reclassified_dam
):
    """The owner's last observed dam version no longer matches, so the draft is refused.

    PRD 2.5: "**Dam stale-view rejection** — plan drafting must quote the dam version the client last observed; otherwise `ERR_STALE_DAM_VERSION` (412)."

    Design: Corner/cross_cutting_complexity_layers/plan_creation_rejected_against_a_stale_dam_version
    """
    validate_error(
        api.create_eap(
            f.eap_payload(base.dam_id, reclassified_dam["stale_version"]),
            base.owner_headers,
        ),
        ApiErrorId.ERR_STALE_DAM_VERSION,
        412,
    )

    fresh_version = program.dam_version(base.dam_id)
    assert fresh_version > reclassified_dam["stale_version"]
    assert program.get_dam(base.dam_id)["hazard_class"] == HAZARD_SIGNIFICANT


def test_the_refused_draft_leaves_no_plan_behind(api, program, base, reclassified_dam):
    """Nothing is stored for a rejected draft, so the dam still reports no plan.

    PRD 3.5: "A stale dam version is rejected with `ERR_STALE_DAM_VERSION`, an owner drafting against someone else's dam gets `ERR_NOT_RESOURCE_OWNER`, and a `BREACHED` dam refuses the draft with `ERR_DAM_NOT_OPERABLE`."

    Design: Corner/cross_cutting_complexity_layers/plan_creation_rejected_against_a_stale_dam_version
    """
    validate_error(
        api.create_eap(
            f.eap_payload(base.dam_id, reclassified_dam["stale_version"]),
            base.owner_headers,
        ),
        ApiErrorId.ERR_STALE_DAM_VERSION,
        412,
    )

    _rows, meta = validate_paginated(
        api.list_eaps(program.admin, {"dam_id": base.dam_id})
    )
    assert_total_count(meta, 0)


def test_refiling_at_the_fresh_version_lands_the_draft(
    api, program, base, reclassified_dam
):
    """Reading the dam again and quoting that version is all the owner needs.

    PRD 3.5: "The new plan lands in `DRAFT` with `review_findings`, `approved_at`, `expires_at` and `last_accepted_exercise_at` all null, `accepted_exercise_count` at 0 and `exercise_current` false; the dam's `latest_eap_status` becomes `DRAFT` and the dam's `version` increments by 1."

    Design: Corner/cross_cutting_complexity_layers/plan_creation_rejected_against_a_stale_dam_version
    """
    validate_error(
        api.create_eap(
            f.eap_payload(base.dam_id, reclassified_dam["stale_version"]),
            base.owner_headers,
        ),
        ApiErrorId.ERR_STALE_DAM_VERSION,
        412,
    )

    fresh_version = program.dam_version(base.dam_id)
    plan = validate_success(
        api.create_eap(
            f.eap_payload(base.dam_id, fresh_version), base.owner_headers
        ),
        201,
    )
    assert plan["status"] == EAP_DRAFT
    assert plan["approved_at"] is None
    assert plan["expires_at"] is None
    assert plan["accepted_exercise_count"] == 0
    assert plan["exercise_current"] is False

    dam = program.get_dam(base.dam_id)
    assert dam["latest_eap_status"] == EAP_DRAFT
    assert dam["version"] == fresh_version + 1


# ---------------------------------------------------------------------------
# Two dams competing for one channel, coordinated one at a time
# ---------------------------------------------------------------------------
@pytest.fixture()
def two_orders_one_reach(program, base):
    """Two SIGNIFICANT dams on the same reach, each with a REQUESTED 200-cfs order."""
    program.classify_significant(base.dam_id, base.engineer_a_id)
    second = program.create_dam(
        base.owner_id, base.reach_id, name="Basalt Ridge Dam", nid_code="ST00181"
    )
    program.classify_significant(second["id"], base.engineer_a_id)

    event_a = program.declare_event(base.dam_id)
    event_b = program.declare_event(second["id"])
    order_a = program.request_drawdown(
        base.dam_id, event_a["id"], requested_release_cfs=200
    )
    order_b = program.request_drawdown(
        second["id"], event_b["id"], requested_release_cfs=200
    )
    return {
        "dam_b": second,
        "order_a": order_a,
        "order_b": order_b,
        "stale_version": program.reach_version(base.reach_id),
    }


def test_the_first_coordination_commits_the_channel_and_moves_the_reach(
    api, program, base, two_orders_one_reach
):
    """One coordination takes 200 cfs of the channel and advances the reach version.

    PRD 3.7: "On success the order moves `REQUESTED → COORDINATED`, `coordinated_at` is stamped with the clock, and both shared quantities are committed in the same request: the reach's `committed_release_cfs` rises by the order's requested rate and its `active_drawdown_count` by one, incrementing the reach's `version` by 1; and the dam's `committed_drawdown_acre_ft` rises by the order's planned volume with `available_conservation_storage_acre_ft` recomputed, incrementing the dam's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/second_coordination_rejected_against_a_stale_reach_version
    """
    stale = two_orders_one_reach["stale_version"]
    coordinated = validate_success(
        api.coordinate_drawdown(
            two_orders_one_reach["order_a"]["id"],
            f.coordinate_payload(stale),
            program.admin,
        )
    )
    assert coordinated["status"] == DRAWDOWN_COORDINATED

    reach = program.get_reach(base.reach_id)
    assert_cfs(reach["committed_release_cfs"], 200, "committed_release_cfs")
    assert reach["active_drawdown_count"] == 1
    assert reach["version"] == stale + 1

    dam = program.get_dam(base.dam_id)
    assert_acre_feet(
        dam["committed_drawdown_acre_ft"], 99.174, "committed_drawdown_acre_ft"
    )


def test_the_second_coordination_at_the_same_version_is_refused(
    api, program, base, two_orders_one_reach
):
    """A thousand cfs of channel is still free, and the stale version is refused anyway.

    PRD 2.5: "This outranks the capacity and storage checks, so a stale reach version is reported even when the reach is simultaneously over capacity."

    Design: Corner/cross_cutting_complexity_layers/second_coordination_rejected_against_a_stale_reach_version
    """
    stale = two_orders_one_reach["stale_version"]
    program.coordinate_drawdown(
        two_orders_one_reach["order_a"]["id"], expected_reach_version=stale
    )

    validate_error(
        api.coordinate_drawdown(
            two_orders_one_reach["order_b"]["id"],
            f.coordinate_payload(stale),
            program.admin,
        ),
        ApiErrorId.ERR_STALE_REACH_VERSION,
        412,
    )

    assert (
        program.get_drawdown(two_orders_one_reach["order_b"]["id"])["status"]
        == DRAWDOWN_REQUESTED
    )
    reach = program.get_reach(base.reach_id)
    assert_cfs(reach["committed_release_cfs"], 200, "committed_release_cfs")
    assert reach["version"] > stale


def test_the_retry_at_the_refreshed_version_takes_the_rest(
    api, program, base, two_orders_one_reach
):
    """Re-reading the reach and quoting its version lets the second release commit.

    PRD 3.7: "The reach's own `committed_release_cfs` obeys the same discipline as the sum of `requested_release_cfs` over its `COORDINATED` and `ACTIVE` orders."

    Design: Corner/cross_cutting_complexity_layers/second_coordination_rejected_against_a_stale_reach_version
    """
    stale = two_orders_one_reach["stale_version"]
    program.coordinate_drawdown(
        two_orders_one_reach["order_a"]["id"], expected_reach_version=stale
    )
    validate_error(
        api.coordinate_drawdown(
            two_orders_one_reach["order_b"]["id"],
            f.coordinate_payload(stale),
            program.admin,
        ),
        ApiErrorId.ERR_STALE_REACH_VERSION,
        412,
    )

    fresh = program.reach_version(base.reach_id)
    second = validate_success(
        api.coordinate_drawdown(
            two_orders_one_reach["order_b"]["id"],
            f.coordinate_payload(fresh),
            program.admin,
        )
    )
    assert second["status"] == DRAWDOWN_COORDINATED

    reach = program.get_reach(base.reach_id)
    assert_cfs(reach["committed_release_cfs"], 400, "committed_release_cfs")
    assert reach["active_drawdown_count"] == 2


# ---------------------------------------------------------------------------
# The hub counter moves once per write and never on a read
# ---------------------------------------------------------------------------
def test_three_reads_of_the_dam_leave_its_version_where_it_was(api, program, base):
    """A plain read, a computed snapshot and a filtered listing all cost nothing.

    PRD 2.9: "The dam record carries a large number of derived fields, and the program's correctness rests on them being reconciled inside the same request that changes their inputs — never lazily, never on a later read."

    Design: Corner/cross_cutting_complexity_layers/dam_version_advances_exactly_once_per_mutating_write_and_never_on_reads
    """
    first = validate_success(api.get_dam(base.dam_id, program.admin))
    assert first["version"] == 1

    validate_success(api.get_compliance_summary(base.dam_id, program.admin))
    rows, _meta = validate_paginated(
        api.list_dams(program.admin, {"hazard_class": HAZARD_UNCLASSIFIED})
    )
    assert [row["id"] for row in rows] == [base.dam_id]

    assert program.dam_version(base.dam_id) == first["version"]


def test_filing_a_draft_is_free_while_certifying_costs_exactly_one(api, program, base):
    """The draft leaves the dam alone; the certification that reclassifies it does not.

    PRD 3.2: "The dam's `version` increments by 1 across the whole certification, and its safety rating is left exactly as it was — reclassification is a consequence judgement, not a condition judgement."

    Design: Corner/cross_cutting_complexity_layers/dam_version_advances_exactly_once_per_mutating_write_and_never_on_reads
    """
    before = program.dam_version(base.dam_id)
    assessment = program.create_assessment(
        f.assessment_a1(base.dam_id), base.engineer_a_id
    )
    assert assessment["status"] == ASSESSMENT_DRAFT

    unmoved = program.get_dam(base.dam_id)
    assert unmoved["version"] == before
    assert unmoved["hazard_class"] == HAZARD_UNCLASSIFIED

    program.certify_assessment(assessment["id"], base.engineer_a_id)
    after = program.get_dam(base.dam_id)
    assert after["version"] == before + 1
    assert after["hazard_class"] == HAZARD_SIGNIFICANT


def test_each_plan_write_advances_the_busiest_counter_once(api, program, base):
    """Four writes across three resources move the dam's version to exactly four.

    PRD 2.4: "Because a dam is the hub of this domain, its `version` is the busiest counter in the system: it advances when a certification reclassifies it, when an inspection acceptance rates it, when a plan write refreshes its plan status, when a deficiency opens or closes, when enforcement or intervention moves its regulatory posture, and when a drawdown commits or releases storage."

    Design: Corner/cross_cutting_complexity_layers/dam_version_advances_exactly_once_per_mutating_write_and_never_on_reads
    """
    program.classify_significant(base.dam_id, base.engineer_a_id)
    after_certify = program.dam_version(base.dam_id)
    assert after_certify == 2

    plan = program.draft_plan(base.dam_id, base.owner_id, after_certify)
    assert program.dam_version(base.dam_id) == after_certify + 1

    submitted = validate_success(
        api.submit_eap(plan["id"], None, base.owner_headers)
    )
    assert submitted["status"] == EAP_SUBMITTED

    final = program.get_dam(base.dam_id)
    assert final["version"] == after_certify + 2
    assert final["version"] == 4
    assert final["latest_eap_status"] == EAP_SUBMITTED


# ---------------------------------------------------------------------------
# One counter absorbing findings from two different sources
# ---------------------------------------------------------------------------
@pytest.fixture()
def planned_dam(program, base):
    """A SIGNIFICANT dam with an APPROVED plan and a scheduled visit, clock at the visit."""
    program.classify_significant(base.dam_id, base.engineer_a_id)
    plan = program.approved_plan(base.dam_id, base.owner_id, base.engineer_b_id)
    visit = program.schedule_inspection(base.dam_id, base.engineer_a_id)
    program.set_clock("2026-08-05T13:00:00Z")
    return {"plan": plan, "visit": visit}


@pytest.fixture()
def two_findings(program, base, planned_dam):
    """The inspection submitted with one SERIOUS and one MINOR finding."""
    return program.submit_inspection(
        planned_dam["visit"]["id"],
        base.engineer_a_id,
        performed_at="2026-08-05T12:00:00Z",
        condition_rating=SAFETY_POOR,
        narrative="Two findings.",
        deficiencies=[
            f.deficiency_item(
                category=CATEGORY_STRUCTURAL,
                severity=SEVERITY_SERIOUS,
                description="Crest cracking.",
            ),
            f.deficiency_item(
                category=CATEGORY_OPERATIONAL,
                severity=SEVERITY_MINOR,
                description="Piezometer unreadable.",
            ),
        ],
    )


@pytest.fixture()
def failed_exercise(program, base, planned_dam, two_findings):
    """A tabletop exercise whose notification test failed, logged by the owner."""
    return program.log_exercise(
        planned_dam["plan"]["id"],
        base.owner_headers,
        exercise_type=EXERCISE_TABLETOP,
        conducted_at="2026-08-04T00:00:00Z",
        participant_count=4,
        notification_test_passed=False,
    )


@pytest.fixture()
def ordered_finding(program, base, failed_exercise):
    """A notice of deficiency issued against the SERIOUS inspection finding."""
    serious = program.deficiencies_for(base.dam_id, severity=SEVERITY_SERIOUS)[0]
    order = program.issue_order(
        serious["id"], order_type=ORDER_TYPE_NOTICE, requested_response_days=30
    )
    return {"deficiency": serious, "order": order}


def test_the_submitted_findings_raise_the_counter_to_two(
    api, program, base, planned_dam, two_findings
):
    """Both rows are inspection-born and the dam's counter matches their number.

    PRD 3.3: "The inspection's `deficiency_count` is set to the length of the submitted array, the dam's `open_deficiency_count` rises by the number of rows created, and the dam's `version` increments by 1 when that count changes."

    Design: Corner/cross_cutting_complexity_layers/open_deficiency_count_reconciles_across_inspection_and_system_sources
    """
    assert two_findings["deficiency_count"] == 2
    assert program.get_dam(base.dam_id)["open_deficiency_count"] == 2

    rows = program.deficiencies_for(base.dam_id)
    assert len(rows) == 2
    for row in rows:
        assert row["source"] == SOURCE_INSPECTION
        assert row["inspection_id"] == planned_dam["visit"]["id"]
        assert row["status"] == DEFICIENCY_OPEN


def test_the_failed_exercise_adds_a_system_born_third_row(
    api, program, base, failed_exercise
):
    """A deficient exercise opens its own row and the same counter absorbs it.

    PRD 3.5: "A deficient exercise additionally opens a deficiency with `source` of `SYSTEM_EXERCISE`, `category` of `EAP_EXERCISE`, `severity` of `MODERATE` and `status` of `OPEN`, incrementing the dam's `open_deficiency_count`."

    Design: Corner/cross_cutting_complexity_layers/open_deficiency_count_reconciles_across_inspection_and_system_sources
    """
    assert failed_exercise["outcome"] == EXERCISE_DEFICIENT
    assert failed_exercise["deficiency_reason"] == REASON_NOTIFICATION_TEST_FAILED

    system_rows = program.deficiencies_for(base.dam_id, source=SOURCE_SYSTEM_EXERCISE)
    assert len(system_rows) == 1
    system_row = system_rows[0]
    assert system_row["category"] == CATEGORY_EAP_EXERCISE
    assert system_row["severity"] == SEVERITY_MODERATE
    assert system_row["status"] == DEFICIENCY_OPEN
    assert system_row["inspection_id"] is None

    assert program.get_dam(base.dam_id)["open_deficiency_count"] == 3


def test_the_intermediate_enforcement_states_stay_inside_the_counter(
    api, program, base, ordered_finding
):
    """Ordering and answering a finding never lowers the count of open work.

    PRD 2.9: "A dam's `open_deficiency_count` is the number of its deficiencies whose status is `OPEN`, `ORDERED`, `REMEDIATION_SUBMITTED` or `ESCALATED`."

    Design: Corner/cross_cutting_complexity_layers/open_deficiency_count_reconciles_across_inspection_and_system_sources
    """
    deficiency_id = ordered_finding["deficiency"]["id"]
    assert program.get_dam(base.dam_id)["open_deficiency_count"] == 3
    summary = program.summary(base.dam_id)
    assert summary["open_deficiency_count"] == 3
    assert summary["escalated_deficiency_count"] == 0
    assert (
        validate_success(api.get_deficiency(deficiency_id, program.admin))["status"]
        == DEFICIENCY_ORDERED
    )

    program.file_order_response(
        ordered_finding["order"]["id"],
        base.owner_id,
        corrective_action_summary="Crest joints routed and sealed.",
        completed_at="2026-08-05T09:00:00Z",
    )
    assert program.get_dam(base.dam_id)["open_deficiency_count"] == 3
    assert (
        validate_success(api.get_deficiency(deficiency_id, program.admin))["status"]
        == DEFICIENCY_REMEDIATION_SUBMITTED
    )


def test_only_the_satisfied_verification_takes_the_counter_down(
    api, program, base, ordered_finding
):
    """Closing one finding drops the count to two, and a live query agrees.

    PRD 3.4: "On `SATISFIED` the order moves `RESPONSE_FILED → SATISFIED`, which is terminal, the deficiency moves `REMEDIATION_SUBMITTED → CLOSED_VERIFIED` with `closed_at` stamped at the clock, the dam's `open_deficiency_count` falls by one and the dam's `version` increments."

    Design: Corner/cross_cutting_complexity_layers/open_deficiency_count_reconciles_across_inspection_and_system_sources
    """
    order_id = ordered_finding["order"]["id"]
    program.file_order_response(
        order_id,
        base.owner_id,
        corrective_action_summary="Crest joints routed and sealed.",
        completed_at="2026-08-05T09:00:00Z",
    )
    verified = program.verify_order(
        order_id,
        base.engineer_b_id,
        outcome=VERIFY_SATISFIED,
        notes="Repair confirmed in the field.",
    )
    assert verified["status"] == ORDER_SATISFIED

    closed = validate_success(
        api.get_deficiency(ordered_finding["deficiency"]["id"], program.admin)
    )
    assert closed["status"] == DEFICIENCY_CLOSED_VERIFIED
    assert_instant(closed["closed_at"], "2026-08-05T13:00:00Z", "closed_at")

    assert program.get_dam(base.dam_id)["open_deficiency_count"] == 2
    summary = program.summary(base.dam_id)
    assert summary["open_deficiency_count"] == 2
    assert summary["regulatory_status"] == REG_REGISTERED

    _rows, meta = validate_paginated(
        api.list_deficiencies(
            program.admin, {"dam_id": base.dam_id, "status": DEFICIENCY_OPEN}
        )
    )
    assert_total_count(meta, 2)
