"""Ledgers that must read identically after a forward move and its compensating reverse."""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories
from test_helpers.assertions import assert_number_equals
from test_helpers.constants import (
    COMPONENT_TYPE_HEAD,
    COMPONENT_TYPE_SHELL,
    DESIGN_CODE_DIV1,
    DISPOSITION_CLOSED,
    DISPOSITION_OPEN,
    DISPOSITION_REPAIR,
    FAB_STATUS_WELDED,
    HEAT_STATUS_ACCEPTED,
    HEAT_STATUS_DEPLETED,
    JOB_STATUS_FABRICATION,
    JOB_STATUS_NDE_HOLD,
    JOINT_CATEGORY_B,
    JOINT_TYPE_BUTT,
    NCR_SOURCE_NDE_REJECT,
    NDE_STATUS_ACCEPTED,
    PART_STATUS_ISSUED,
    PART_STATUS_SCRAPPED,
    RT_EXTENT_FULL,
    RT_EXTENT_NONE,
    SEVERITY_MAJOR,
    SPEC_SA_516_70,
    VESSEL_TYPE_PRESSURE_VESSEL,
)

LAMINATION = "LAMINATION FOUND AT LAYOUT"


def _job_beside_a_two_thousand_pound_heat(shop):
    job = shop.job(
        job_number="J-2885-17",
        customer_name="Northline Energy",
        vessel_type=VESSEL_TYPE_PRESSURE_VESSEL,
        design_code=DESIGN_CODE_DIV1,
        mawp_psi=350,
        design_temp_f=650,
        mdmt_f=-20,
        inside_radius_in=30.0,
        stress_ratio=1.00,
    )
    shop.release_design(
        job,
        rt_extent_declared=RT_EXTENT_NONE,
        allowable_stress_psi=20000,
        corrosion_allowance_in=0.0625,
        thickness_nominal_in=1.0000,
    )
    heat = shop.accepted_heat(
        heat_number="H-4471", spec=SPEC_SA_516_70, quantity_received_lb=2000.00
    )
    return job, heat, shop.welding_engineer()


def _issue(client, shop, job, heat, engineer, part_mark, pounds):
    return client.issue_part(
        job["id"],
        factories.part_payload(
            heat["id"],
            part_mark=part_mark,
            component_type=COMPONENT_TYPE_SHELL,
            issued_quantity_lb=pounds,
        ),
        shop.acting_as(engineer),
    )


def _assert_ledger(heat, issued, remaining, status):
    assert_number_equals(heat["quantity_issued_lb"], issued, 2, "quantity_issued_lb")
    assert_number_equals(heat["quantity_remaining_lb"], remaining, 2, "quantity_remaining_lb")
    assert heat["status"] == status
    assert_number_equals(
        heat["quantity_received_lb"],
        heat["quantity_remaining_lb"] + heat["quantity_issued_lb"],
        2,
        "quantity_received_lb",
    )


def test_scrapping_an_issued_piece_restores_the_pounds_and_reverses_the_depletion(client, shop):
    """The forward pair of issues exhausts the heat and the scrap puts the mass back without netting it against the issued total.

    PRD §3.4: "`quantity_issued_lb` is the sum of `issued_quantity_lb` across all parts referencing this heat whose `status` is still `ISSUED`; scrapped pieces are excluded from that sum."

    PRD §3.4: "The invariant that the received pounds always equal the remaining pounds plus the issued pounds therefore holds after every one of the three triggers."

    PRD §3.4: "When an issue brings `quantity_remaining_lb` to exactly 0.00 the heat moves `ACCEPTED → DEPLETED`; any positive remainder, however small, keeps it `ACCEPTED`."

    PRD §3.4: "On scrap the piece moves `ISSUED → SCRAPPED`, its `scrap_reason` is stored, the heat's `quantity_issued_lb` and `quantity_remaining_lb` are re-derived so the mass invariant holds again, and a heat that was `DEPLETED` moves `DEPLETED → ACCEPTED` as soon as its remaining pounds rise above 0.00 — the same restoration the cancellation cascade performs."

    Design: Difficulty/compensating_invariant/compensating_invariant_heat_mass_conserved_across_issue_scrap_reissue
    """
    job, heat, engineer = _job_beside_a_two_thousand_pound_heat(shop)

    first = validate_success(_issue(client, shop, job, heat, engineer, "SH-01", 1200.00), 201)
    _assert_ledger(shop.read_heat(heat["id"]), 1200.00, 800.00, HEAT_STATUS_ACCEPTED)

    second = validate_success(_issue(client, shop, job, heat, engineer, "SH-02", 800.00), 201)
    exhausted = shop.read_heat(heat["id"])
    _assert_ledger(exhausted, 2000.00, 0.00, HEAT_STATUS_DEPLETED)

    scrapped = validate_success(
        client.scrap_part(
            second["id"], factories.scrap_payload(scrap_reason=LAMINATION), shop.acting_as(engineer)
        ),
        200,
    )
    assert scrapped["status"] == PART_STATUS_SCRAPPED
    assert scrapped["scrap_reason"] == LAMINATION

    restored = shop.read_heat(heat["id"])
    _assert_ledger(restored, 1200.00, 800.00, HEAT_STATUS_ACCEPTED)
    assert restored["version"] > exhausted["version"]

    untouched = validate_success(client.get_part(first["id"], shop.admin), 200)
    assert untouched["status"] == PART_STATUS_ISSUED
    assert untouched["scrap_reason"] is None
    assert_number_equals(untouched["issued_quantity_lb"], 1200.00, 2, "issued_quantity_lb")


def test_re_issuing_the_same_pounds_lands_on_the_identical_ledger_with_no_drift(client, shop):
    """The round trip issue, scrap and re-issue returns every figure to the value it held at exhaustion.

    PRD §3.4: "The **mass ledger** on each heat is maintained by aggregation rather than by decrement, and it is re-derived on every part issue, every part scrap, and the job-cancellation cascade."

    PRD §3.4: "`quantity_remaining_lb` is `quantity_received_lb` minus that issued total, rounded half up to two decimal places."

    PRD §3.4: "Parts are listed with filters on `job_id`, `heat_id`, `component_type` and `status`."

    PRD §2.4: "`version` is an integer that starts at 1 when the record is created and increments by exactly 1 on every mutation of that record, whether the mutation was requested directly by a client or applied by the server as a cascade from somewhere else."

    Design: Difficulty/compensating_invariant/compensating_invariant_heat_mass_conserved_across_issue_scrap_reissue
    """
    job, heat, engineer = _job_beside_a_two_thousand_pound_heat(shop)

    validate_success(_issue(client, shop, job, heat, engineer, "SH-01", 1200.00), 201)
    second = validate_success(_issue(client, shop, job, heat, engineer, "SH-02", 800.00), 201)
    at_depletion = shop.read_heat(heat["id"])
    _assert_ledger(at_depletion, 2000.00, 0.00, HEAT_STATUS_DEPLETED)

    validate_success(
        client.scrap_part(
            second["id"], factories.scrap_payload(scrap_reason=LAMINATION), shop.acting_as(engineer)
        ),
        200,
    )
    after_scrap = shop.read_heat(heat["id"])
    _assert_ledger(after_scrap, 1200.00, 800.00, HEAT_STATUS_ACCEPTED)

    validate_success(_issue(client, shop, job, heat, engineer, "SH-03", 800.00), 201)
    after_reissue = shop.read_heat(heat["id"])
    _assert_ledger(after_reissue, 2000.00, 0.00, HEAT_STATUS_DEPLETED)
    assert after_reissue["quantity_issued_lb"] == at_depletion["quantity_issued_lb"]
    assert after_reissue["quantity_remaining_lb"] == at_depletion["quantity_remaining_lb"]
    assert after_reissue["version"] > after_scrap["version"]

    rows, meta = validate_paginated(
        client.list_parts(shop.admin, params={"job_id": job["id"], "status": PART_STATUS_ISSUED})
    )
    assert meta["total_count"] == 2
    assert sorted(row["part_mark"] for row in rows) == ["SH-01", "SH-03"]
    assert_number_equals(
        sum(row["issued_quantity_lb"] for row in rows), 2000.00, 2, "issued_quantity_lb"
    )

    _, scrapped_meta = validate_paginated(
        client.list_parts(shop.admin, params={"job_id": job["id"], "status": PART_STATUS_SCRAPPED})
    )
    assert scrapped_meta["total_count"] == 1


def _rejected_category_b_seam(shop):
    """One Category B seam welded, radiographed and interpreted REJECT, leaving the job on hold."""
    certificate = shop.certificate(
        cert_number="CA-U-8801",
        scope_codes=["U"],
        issued_on="2026-01-01",
        expires_on="2029-01-01",
    )
    job = shop.job(
        certificate,
        job_number="J-2885-18",
        customer_name="Northline Energy",
        vessel_type=VESSEL_TYPE_PRESSURE_VESSEL,
        design_code=DESIGN_CODE_DIV1,
        mawp_psi=350,
        design_temp_f=650,
        mdmt_f=-20,
        inside_radius_in=30.0,
        stress_ratio=1.00,
    )
    shop.release_design(
        job,
        rt_extent_declared=RT_EXTENT_FULL,
        allowable_stress_psi=20000,
        corrosion_allowance_in=0.0625,
        thickness_nominal_in=1.0000,
    )
    heat = shop.accepted_heat(
        heat_number="H-4471", spec=SPEC_SA_516_70, quantity_received_lb=2000.00
    )
    shell_part = shop.issue_part(
        job["id"],
        heat["id"],
        part_mark="SH-01",
        component_type=COMPONENT_TYPE_SHELL,
        issued_quantity_lb=1200.00,
    )
    head_part = shop.issue_part(
        job["id"],
        heat["id"],
        part_mark="HD-01",
        component_type=COMPONENT_TYPE_HEAD,
        issued_quantity_lb=600.00,
    )
    procedure = shop.qualified_wps(wps_number="WPS-1", pwht_required=False, preheat_min_f=50)
    qualification = shop.welder_qualification(
        procedure["id"], welder_stamp="W12", welder_name="Rosa Vela", qualified_on="2026-06-01"
    )
    seam = shop.plan_joint(
        job["id"],
        procedure["id"],
        shell_part["id"],
        weld_number="W-001",
        joint_category=JOINT_CATEGORY_B,
        joint_type=JOINT_TYPE_BUTT,
        thickness_in=1.5000,
        part_b_id=head_part["id"],
    )
    shop.release_weld_map(job["id"])
    shop.complete_joint(seam["id"], qualification["id"], welded_at="2026-07-30T09:00:00.000Z")
    exams = shop.run_nde_plan(job["id"])
    shop.reject_exam(
        exams[0]["id"], examined_coverage_pct=100.00, indications_count=2, exam_date="2026-08-01"
    )
    report = shop.nonconformances_of(job["id"])[0]
    return job, seam, exams[0], report, procedure, qualification


def test_the_open_count_stays_at_one_while_the_disposition_moves_and_the_repair_is_built(
    client, shop
):
    """Three writes later the joint population has doubled and the count of open reports has not moved.

    PRD §3.2: "`nonconformance_open_count` counts the job's nonconformance reports whose `disposition` is `OPEN`, `REPAIR` or `USE_AS_IS`; reaching 0 is what releases an examination hold."

    PRD §3.7: "Three of the four dispositions count as **open**: `OPEN`, `REPAIR` and `USE_AS_IS` all keep the report inside the job's `nonconformance_open_count`. Only `CLOSED` leaves it."

    PRD §3.7: "The `ncr_number` is minted by the system as the literal `NCR-`, then the parent job's `job_number`, then a hyphen, then a per-job sequence number equal to the count of reports already existing for that job plus one, zero-padded to three digits."

    PRD §3.7: "`severity` is derived, not supplied: it is `MAJOR` when `source` is `PRESSURE_TEST_FAIL`, or when the failed joint's `joint_category` is `A` or `B`, and `MINOR` in every other case — a rejected nozzle attachment is minor, a rejected main seam is not."

    PRD §3.7: "The new joint's `repair_of_weld_id` is set to the report's `weld_id`, its `repair_generation` is the parent joint's `repair_generation` plus 1, and its `joint_category`, `joint_type`, `thickness_in`, `part_a_id` and `part_b_id` are copied from the parent."

    PRD §3.6: "The denominator counts all of the job's joints, repair joints included, which is why raising a repair pushes the percentage down before it pulls it up."

    Design: Difficulty/compensating_invariant/compensating_invariant_open_nonconformance_count_conserved_through_repair_cycle
    """
    job, seam, exam, report, procedure, qualification = _rejected_category_b_seam(shop)

    assert report["ncr_number"] == "NCR-J-2885-18-001"
    assert report["source"] == NCR_SOURCE_NDE_REJECT
    assert report["severity"] == SEVERITY_MAJOR
    assert report["disposition"] == DISPOSITION_OPEN
    assert report["weld_id"] == seam["id"]
    assert report["closed_at"] is None

    held = shop.read_job(job["id"])
    assert held["status"] == JOB_STATUS_NDE_HOLD
    assert held["nonconformance_open_count"] == 1
    assert_number_equals(held["weld_completion_pct"], 0.00, 2, "weld_completion_pct")

    dispositioned = shop.disposition(report["id"], disposition=DISPOSITION_REPAIR)
    assert dispositioned["disposition"] == DISPOSITION_REPAIR
    assert dispositioned["closed_at"] is None
    after_disposition = shop.read_job(job["id"])
    assert after_disposition["nonconformance_open_count"] == 1
    assert after_disposition["status"] == JOB_STATUS_NDE_HOLD

    repair = validate_success(
        client.create_repair_weld(
            report["id"],
            factories.repair_weld_payload(procedure["id"], weld_number="W-001R1"),
            shop.acting_as(shop.welding_engineer()),
        ),
        201,
    )
    assert repair["repair_of_weld_id"] == seam["id"]
    assert repair["repair_generation"] == 1
    assert repair["required_volumetric_pct"] == 100
    assert repair["joint_category"] == JOINT_CATEGORY_B
    assert repair["joint_type"] == JOINT_TYPE_BUTT
    assert_number_equals(repair["thickness_in"], 1.5000, 4, "thickness_in")
    assert repair["part_a_id"] == seam["part_a_id"]
    assert repair["part_b_id"] == seam["part_b_id"]

    after_repair_planned = shop.read_job(job["id"])
    assert after_repair_planned["nonconformance_open_count"] == 1
    assert after_repair_planned["status"] == JOB_STATUS_NDE_HOLD
    assert_number_equals(
        after_repair_planned["weld_completion_pct"], 0.00, 2, "weld_completion_pct"
    )

    shop.complete_joint(repair["id"], qualification["id"], welded_at="2026-08-01T08:00:00.000Z")
    after_repair_welded = shop.read_job(job["id"])
    assert after_repair_welded["nonconformance_open_count"] == 1
    assert after_repair_welded["status"] == JOB_STATUS_NDE_HOLD

    _, weld_meta = validate_paginated(
        client.list_welds(shop.admin, params={"job_id": job["id"]})
    )
    assert weld_meta["total_count"] == 2
    assert exam["id"] is not None


def test_only_the_close_returns_the_count_to_zero_and_the_rejection_stays_on_the_record(
    client, shop
):
    """The accepted repair satisfies the parent joint and fills the percentage, but the hold lifts on the close alone.

    PRD §3.6: "A rejected joint is **never re-planned in place**. Its `nde_status` moves `REJECTED → ACCEPTED` only as a consequence of repair: when a repair joint whose `repair_of_weld_id` points at it reaches `fab_status` `WELDED` with `nde_status` `ACCEPTED`, the parent joint's examination status is satisfied through its replacement. Re-invoking plan selection does not pick up a `REJECTED` joint."

    PRD §3.6: "The numerator counts the job's joints whose `fab_status` is `WELDED` **and** whose `nde_status` is `ACCEPTED` **and** whose `pwht_status` is either `NOT_REQUIRED` or `COMPLETE`; a joint failing any one of the three is not counted."

    PRD §3.7: "`REPAIR → CLOSED` requires that a repair joint exist whose `repair_of_weld_id` equals the report's `weld_id`, whose `fab_status` is `WELDED` and whose `nde_status` is `ACCEPTED` — the repair must be made and passed, not merely planned."

    PRD §3.7: "Either requested path stamps `closed_at` with the current logical UTC instant, decreases the job's `nonconformance_open_count` by 1, and moves the job `NDE_HOLD → FABRICATION` once that count reaches 0."

    PRD §3.6: "The examination record itself moves `PENDING → ACCEPT` on the first branch and `PENDING → REJECT` on the second, and both `ACCEPT` and `REJECT` are terminal for it — an interpretation once recorded is never revised."

    Design: Difficulty/compensating_invariant/compensating_invariant_open_nonconformance_count_conserved_through_repair_cycle
    """
    job, seam, exam, report, procedure, qualification = _rejected_category_b_seam(shop)
    shop.disposition(report["id"], disposition=DISPOSITION_REPAIR)
    repair = shop.repair_joint(report["id"], procedure["id"], weld_number="W-001R1")
    shop.complete_joint(repair["id"], qualification["id"], welded_at="2026-08-01T08:00:00.000Z")

    repair_exams = shop.run_nde_plan(job["id"])
    assert len(repair_exams) == 1
    assert repair_exams[0]["weld_id"] == repair["id"]
    shop.accept_exam(
        repair_exams[0]["id"],
        examined_coverage_pct=100.00,
        indications_count=0,
        exam_date="2026-08-01",
    )

    satisfied = shop.read_joint(seam["id"])
    assert satisfied["nde_status"] == NDE_STATUS_ACCEPTED
    assert satisfied["fab_status"] == FAB_STATUS_WELDED
    assert shop.read_joint(repair["id"])["nde_status"] == NDE_STATUS_ACCEPTED

    before_close = shop.read_job(job["id"])
    assert before_close["nonconformance_open_count"] == 1
    assert before_close["status"] == JOB_STATUS_NDE_HOLD
    assert_number_equals(before_close["weld_completion_pct"], 100.00, 2, "weld_completion_pct")

    closed = shop.close_nonconformance(report["id"])
    assert closed["disposition"] == DISPOSITION_CLOSED
    assert closed["closed_at"] is not None

    after_close = shop.read_job(job["id"])
    assert after_close["nonconformance_open_count"] == 0
    assert after_close["status"] == JOB_STATUS_FABRICATION
    assert_number_equals(after_close["weld_completion_pct"], 100.00, 2, "weld_completion_pct")

    preserved = validate_success(client.get_exam(exam["id"], shop.admin), 200)
    assert preserved["result"] == "REJECT"
    assert preserved["indications_count"] == 2
    assert shop.read_joint(repair["id"])["repair_of_weld_id"] == seam["id"]

    rows, ncr_meta = validate_paginated(
        client.list_nonconformances(shop.admin, params={"job_id": job["id"]})
    )
    assert ncr_meta["total_count"] == 1
    assert rows[0]["id"] == report["id"]
    assert rows[0]["disposition"] == DISPOSITION_CLOSED
