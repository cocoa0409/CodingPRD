"""Depth probes over the PRD's pinned arithmetic: dual-variant calculations,
branching formulas, pinned evaluation order, and exact boundaries."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    begin_campaign_testing,
    classify_modification_recertification,
    compute_conformity_final_bp,
    compute_conformity_screen_bp,
    compute_print_estimate,
    create_campaign,
    create_election_definition,
    create_equipment_unit,
    create_la_test,
    create_test_laboratory,
    create_unit_with_battery_cycles,
    create_voting_system,
    create_work_order,
    deploy_unit,
    equipment_unit_transition_payload,
    file_deficiencies,
    get_certificate,
    get_equipment_unit,
    make_election_official_headers,
    propose_modification,
    record_acceptance_test,
    record_usage,
    resubmit_campaign,
    set_clock,
    setup_certified_jurisdiction,
    setup_certified_system,
    setup_election_definition,
    setup_procurement,
    start_work_order,
    transfer_custody,
    validate_error,
    validate_success,
)


def test_campaign_conformity_screen_vs_final_diverge(api):
    """PRD §3.2: "The screening variant, stored as `conformity_screen_bp`,
    starts from 10000 and subtracts 1200 per open critical deficiency, 300
    per open major, 75 per open minor, and 250 per completed resubmission."
    PRD §3.2: "The final-audit variant, stored as `conformity_final_bp`,
    starts from 10000 and subtracts 1500 per open critical deficiency, 250
    per open major, 50 per open minor, 400 per completed resubmission, and an
    aging term of 10 basis points per full week elapsed since
    `last_submitted_at` — the elapsed whole days between the current logical
    instant and `last_submitted_at`, divided by 7 and rounded down,
    multiplied by 10."

    Design: Difficulty/dual_variant_calc/campaign_conformity_screen_vs_final_diverge
    """
    set_clock("2026-09-01T00:00:00Z")
    system = create_voting_system()
    lab = create_test_laboratory()
    campaign = create_campaign(system["id"], lab["id"], state_code="CA")
    begin_campaign_testing(campaign["id"], lab["id"])
    file_deficiencies(campaign["id"], lab["id"], 0, 0, 1)
    resubmit_campaign(campaign["id"], 0, 0, 1)
    set_clock("2026-09-15T00:00:00Z")
    begin_campaign_testing(campaign["id"], lab["id"])
    file_deficiencies(campaign["id"], lab["id"], 1, 2, 3)

    resp = api.get_certification_campaign(
        campaign["id"], TEST_USERS["certification_authority_headers"]
    )
    data = validate_success(resp)
    expected_screen = compute_conformity_screen_bp(1, 2, 3, 1)
    expected_final = compute_conformity_final_bp(
        1, 2, 3, 1, "2026-09-01T00:00:00Z", "2026-09-15T00:00:00Z"
    )
    assert expected_screen == 7725 and expected_final == 7430
    assert data["conformity_screen_bp"] == 7725, (
        f"LAB_SCREEN variant must be 7725, got {data['conformity_screen_bp']}"
    )
    assert data["conformity_final_bp"] == 7430, (
        f"FINAL_AUDIT variant must be 7430, got {data['conformity_final_bp']}"
    )
    assert data["conformity_screen_bp"] != data["conformity_final_bp"]
    assert data["status"] == "DEFICIENCIES_FILED"
    assert data["resubmission_count"] == 1


def test_fleet_readiness_optimistic_exceeds_conservative(api):
    """PRD §3.5: "The optimistic tally counts a unit ready if it is
    `IN_SERVICE` or `IN_STORAGE`, or if it is `IN_MAINTENANCE` with an open
    work order (`SCHEDULED` or `IN_PROGRESS`) whose `scheduled_end` is on or
    before the end of election day — the planner's projection, which ignores
    battery, custody, and storage-excursion state."
    PRD §3.5: "The conservative tally counts a unit ready if and only if it
    is `IN_SERVICE`, its custody is `SECURED`, its `battery_cycles` are below
    500, and its `storage_excursion_count` is zero — certification-grade
    readiness."

    Design: Difficulty/dual_variant_calc/fleet_readiness_optimistic_exceeds_conservative
    """
    base = setup_procurement("ACCEPTED")
    off1 = base["officials"][0]["id"]
    off2 = base["officials"][1]["id"]
    jur_id = base["jurisdiction"]["id"]
    sys_id = base["system"]["id"]
    definition = create_election_definition(
        jur_id, base["procurement"]["id"], acting_official_id=off1
    )
    # U1: deployed, clean (100 cycles, no excursions, SECURED).
    u1 = create_equipment_unit(jur_id, sys_id, off1, serial_number="SN-U1")
    deploy_unit(u1["id"], off1)
    record_usage(u1["id"], off1, 100)
    # U2: deployed but custody UNSEALED via a broken-seal transfer.
    u2 = create_equipment_unit(jur_id, sys_id, off1, serial_number="SN-U2")
    deploy_unit(u2["id"], off1)
    transfer_custody(u2["id"], off1, off2, seal_number="SEAL-U2-1", seal_intact=False)
    # U3: in maintenance with a work order finishing before election day.
    u3 = create_equipment_unit(jur_id, sys_id, off1, serial_number="SN-U3")
    wo3 = create_work_order(
        u3["id"],
        off1,
        work_type="BATTERY_REPLACEMENT",
        scheduled_start="2026-10-01T00:00:00Z",
        scheduled_end="2026-10-05T00:00:00Z",
    )
    start_work_order(wo3["id"], off1)
    # U4: never deployed, stays IN_STORAGE.
    create_equipment_unit(jur_id, sys_id, off1, serial_number="SN-U4")

    resp = api.get_readiness(definition["id"], make_election_official_headers(off1))
    readiness = validate_success(resp)
    assert readiness["unit_count"] == 4
    assert readiness["optimistic_ready_count"] == 4, (
        "U1 in service, U2 in service, U3 in maintenance with a work order "
        "ending 2026-10-05 <= election 2026-11-03, U4 in storage"
    )
    assert readiness["conservative_ready_count"] == 1, (
        "only U1 is IN_SERVICE + SECURED + sub-500 cycles + zero excursions"
    )
    assert readiness["optimistic_ready_count"] != readiness["conservative_ready_count"]


def test_acceptance_index_weights_branch_by_test_type(api):
    """PRD §3.4: "The platform computes a `deficiency_index` as the smaller
    of 100 and a weighted sum of the counts, with the weight triple selected
    by `test_type`: `HARDWARE_DIAGNOSTIC` weighs critical, major, and minor
    defects at 25, 8, and 2; `BALLOT_SCAN_CALIBRATION` at 30, 10, and 3;
    `LOGIC_VERIFICATION` at 40, 12, and 4."
    PRD §3.4: "The computed `result` is `PASS` if and only if
    `critical_defects` is zero **and** the `deficiency_index` is at most 20;
    otherwise it is `FAIL`."

    Design: Difficulty/combinatorial_formula/acceptance_index_weights_branch_by_test_type
    """
    base = setup_procurement("ACCEPTANCE_TESTING")
    off1 = base["officials"][0]["id"]
    proc_id = base["procurement"]["id"]

    cal = record_acceptance_test(
        proc_id, off1,
        test_type="BALLOT_SCAN_CALIBRATION",
        critical_defects=0, major_defects=2, minor_defects=3,
    )
    assert cal["deficiency_index"] == 29, "30*0 + 10*2 + 3*3 = 29"
    assert cal["result"] == "FAIL", "29 > 20"

    log = record_acceptance_test(
        proc_id, off1,
        test_type="LOGIC_VERIFICATION",
        critical_defects=0, major_defects=1, minor_defects=1,
    )
    assert log["deficiency_index"] == 16, "40*0 + 12*1 + 4*1 = 16"
    assert log["result"] == "PASS", "0 critical and 16 <= 20"

    hw = record_acceptance_test(
        proc_id, off1,
        test_type="HARDWARE_DIAGNOSTIC",
        critical_defects=0, major_defects=5, minor_defects=40,
    )
    assert hw["deficiency_index"] == 100, "min(100, 25*0 + 8*5 + 2*40 = 120) clamps to 100"
    assert hw["result"] == "FAIL", "clamped 100 > 20"


def test_print_estimate_per_precinct_ceil_then_aggregate_tier(api):
    """PRD §3.5: "First, the per-precinct ream count `reams_per_precinct` is
    `ballots_per_precinct` divided by 500 sheets per ream, rounded up — the
    ceiling is applied per precinct, before any aggregation."
    PRD §3.5: "Third, the tier price is selected on the aggregate
    `total_reams`: 100 reams or fewer prices at 4200 cents per ream, 101
    through 500 reams at 3900 cents per ream, and more than 500 reams at 3500
    cents per ream."

    Design: Difficulty/combinatorial_formula/print_estimate_per_precinct_ceil_then_aggregate_tier
    """
    base = setup_procurement("ACCEPTED")
    off1 = base["officials"][0]["id"]
    jur_id = base["jurisdiction"]["id"]
    proc_id = base["procurement"]["id"]
    ed3 = create_election_definition(jur_id, proc_id, acting_official_id=off1,
                                     name="2026 General", precinct_count=3)
    ed50 = create_election_definition(jur_id, proc_id, acting_official_id=off1,
                                      name="2026 Primary", precinct_count=50)
    ed51 = create_election_definition(jur_id, proc_id, acting_official_id=off1,
                                      name="2027 Special", precinct_count=51)

    resp = api.get_print_estimate(
        ed3["id"], TEST_USERS["auditor_headers"], params={"ballots_per_precinct": 501}
    )
    est3 = validate_success(resp)
    assert est3 == compute_print_estimate(501, 3)
    assert est3["reams_per_precinct"] == 2, "ceil(501/500) applied per precinct"
    assert est3["total_reams"] == 6
    assert est3["tier_price_cents"] == 4200
    assert est3["total_cost_cents"] == 25200

    resp = api.get_print_estimate(
        ed50["id"], TEST_USERS["auditor_headers"], params={"ballots_per_precinct": 600}
    )
    est50 = validate_success(resp)
    assert est50 == compute_print_estimate(600, 50)
    assert est50["total_reams"] == 100
    assert est50["tier_price_cents"] == 4200
    assert est50["total_cost_cents"] == 420000

    resp = api.get_print_estimate(
        ed51["id"], TEST_USERS["auditor_headers"], params={"ballots_per_precinct": 600}
    )
    est51 = validate_success(resp)
    assert est51 == compute_print_estimate(600, 51)
    assert est51["total_reams"] == 102
    assert est51["tier_price_cents"] == 3900, "tier selected on the AGGREGATE ream count"
    assert est51["total_cost_cents"] == 397800
    assert est51["total_cost_cents"] < est50["total_cost_cents"], (
        "crossing the 100-ream aggregate boundary lowers the total"
    )


def test_modification_lead_time_computed_before_suspension_cascade(api):
    """PRD §3.9: "the transition stamps `classified_at` and computes
    `lead_time_days` from pre-classification state in a fixed order: start
    from a base of 30 days; if `component_codes` touches
    `TABULATION_FIRMWARE` or `BALLOT_LAYOUT_ENGINE`, add 60 days; if the
    system has a certificate with `scope` `FEDERAL` in `ACTIVE` or
    `SUSPENDED` status — evaluated strictly before any suspension the
    classification itself is about to cause — add 45 days."

    Design: Difficulty/combinatorial_formula/modification_lead_time_computed_before_suspension_cascade
    """
    base = setup_certified_system(state_code=None)  # FEDERAL-scope certificate
    sys_id = base["system"]["id"]
    cert_id = base["certificate"]["id"]
    assert base["certificate"]["scope"] == "FEDERAL"

    mod = propose_modification(
        sys_id,
        description="Tabulation firmware 2.4.2 hotfix",
        component_codes=["TABULATION_FIRMWARE"],
    )
    mod = classify_modification_recertification(mod["id"])
    assert mod["lead_time_days"] == 135, (
        "30 base + 60 scope-touching + 45 federal certificate, evaluated "
        "against the PRE-classification ACTIVE certificate"
    )
    assert mod["classification"] == "RECERTIFICATION_REQUIRED"
    assert mod["status"] == "RECERTIFICATION_PENDING"
    cert = get_certificate(cert_id)
    assert cert["status"] == "SUSPENDED", (
        "the cascade fires only after the lead-time evaluation pinned 135"
    )


def test_la_discrepancy_exactly_at_50bp_passes_one_unit_above_fails(api):
    """PRD §3.6: "The computed `result` is `PASS` if and only if 10000 times
    `total_discrepancy` is less than or equal to 50 times `total_expected`;
    an exact boundary passes, one unit above fails, and the rounded
    `discrepancy_bp` never decides the outcome."

    Design: Difficulty/boundary_precision_check/la_discrepancy_exactly_at_50bp_passes_one_unit_above_fails
    """
    base = setup_election_definition("PROGRAMMED")
    off1 = base["officials"][0]["id"]
    ed_id = base["definition"]["id"]
    expected = {"PRES": 12000, "SEN": 8000}

    test_a = create_la_test(
        ed_id, off1,
        expected_tallies=expected,
        scanned_tallies={"PRES": 12100, "SEN": 8000},
    )
    assert test_a["total_discrepancy"] == 100
    assert test_a["result"] == "PASS", "100*10000 == 50*20000 exactly: boundary is inclusive"
    assert test_a["discrepancy_bp"] == 50

    test_b = create_la_test(
        ed_id, off1,
        expected_tallies=expected,
        scanned_tallies={"PRES": 12101, "SEN": 8000},
    )
    assert test_b["total_discrepancy"] == 101
    assert test_b["result"] == "FAIL", "101*10000 > 50*20000"
    assert test_b["discrepancy_bp"] == 50, (
        "floored display value identical to test A; the verdict uses exact integer math"
    )


def test_battery_deploy_at_500_blocked_499_allowed(api):
    """PRD §3.7: "Deploying (`IN_STORAGE` → `IN_SERVICE`) requires a
    jurisdiction official, `custody_status` `SECURED` (`ERR_UNIT_UNSEALED`),
    `battery_cycles` strictly below 500 — exactly 500 is rejected
    (`ERR_BATTERY_CYCLE_LIMIT`) — and a voting system that is not `RETIRED`
    (`ERR_SYSTEM_RETIRED`); custody is unchanged by deployment."

    Design: Difficulty/boundary_precision_check/battery_deploy_at_500_blocked_499_allowed
    """
    base = setup_certified_jurisdiction()
    off1 = base["officials"][0]["id"]
    jur_id = base["jurisdiction"]["id"]
    sys_id = base["system"]["id"]
    u499 = create_unit_with_battery_cycles(jur_id, sys_id, off1, 499,
                                           serial_number="SN-499")
    u500 = create_unit_with_battery_cycles(jur_id, sys_id, off1, 500,
                                           serial_number="SN-500")

    resp = api.transition_equipment_unit(
        u499["id"],
        equipment_unit_transition_payload("IN_SERVICE"),
        make_election_official_headers(off1),
    )
    deployed = validate_success(resp)
    assert deployed["operational_status"] == "IN_SERVICE", "499 < 500 deploys"

    resp = api.transition_equipment_unit(
        u500["id"],
        equipment_unit_transition_payload("IN_SERVICE"),
        make_election_official_headers(off1),
    )
    validate_error(resp, ApiErrorId.ERR_BATTERY_CYCLE_LIMIT)
    unit = get_equipment_unit(u500["id"])
    assert unit["operational_status"] == "IN_STORAGE", "exactly 500 is rejected"
