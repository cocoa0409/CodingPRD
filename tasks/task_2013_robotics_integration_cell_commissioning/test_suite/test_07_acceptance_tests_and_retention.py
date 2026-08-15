"""Acceptance tests and the retention release schedule: zero-defect PASS vs
one-defect CONDITIONAL_PASS boundary, pinned waterfall rounding, retention
ledger conservation, retention overrelease guard, guarantee-window violation
(PRD §3.6, §2.8, §2.6)."""
from test_helpers import (
    ApiErrorId,
    assert_acceptance_test,
    create_acceptance_test_payload,
    create_org,
    create_project,
    create_site,
    create_user,
    get_project,
    make_finance_admin_headers,
    make_project_engineer_headers,
    make_site_supervisor_headers,
    retention_ledger_entry_payload,
    setup_full_project,
    setup_project_in_fat,
    setup_project_in_guarantee,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_training_zero_defect_fat_pass_vs_one_defect_conditional(api):
    """PRD §3.6: "A clean run — `measured_cycle_time_s` not exceeding
    `contracted_cycle_time_s`, `measured_oee_pct` at least
    `guaranteed_oee_pct`, and `defects_observed` exactly zero — earns `PASS`."
    PRD §3.6: "A `CONDITIONAL_PASS` halves the milestone release for that
    test, rounded half-up to a whole cent". PRD §3.6: "The record opens with
    `verdict` `PENDING`, its `attempt` number is one higher than the count of
    prior attempts in the same phase".

    Design: Difficulty/boundary_precision_check/training_zero_defect_fat_pass_vs_one_defect_conditional
    """
    ctx = setup_project_in_fat(project_overrides={"project_code": "P-BP2"})
    proj = ctx["project"]
    sup = ctx["users"]["SITE_SUPERVISOR"]
    sup_hdrs = make_site_supervisor_headers(sup["id"])

    # Contract 1,000,000 at 1000 bps -> total retention 100,000; FAT milestone
    # is 30% of total = 30,000; CONDITIONAL_PASS halves it -> 15,000.
    fat1 = validate_success(
        api.create_acceptance_test(
            proj["id"],
            create_acceptance_test_payload(
                "FAT",
                measured_cycle_time_s=9.0,
                measured_oee_pct=85.0,
                defects_observed=1,
            ),
            sup_hdrs,
        ),
        201,
    )
    recorded1 = validate_success(api.record_acceptance_test(fat1["id"], sup_hdrs))
    assert_acceptance_test(recorded1)
    assert recorded1["verdict"] == "CONDITIONAL_PASS"
    assert recorded1["retention_released_cents"] == 15000

    fat2 = validate_success(
        api.create_acceptance_test(
            proj["id"],
            create_acceptance_test_payload(
                "FAT",
                measured_cycle_time_s=9.0,
                measured_oee_pct=85.0,
                defects_observed=0,
            ),
            sup_hdrs,
        ),
        201,
    )
    recorded2 = validate_success(api.record_acceptance_test(fat2["id"], sup_hdrs))
    assert recorded2["verdict"] == "PASS"
    assert recorded2["retention_released_cents"] == 30000
    assert recorded2["attempt"] == 2


def test_retention_waterfall_pinned_rounding_order(api):
    """PRD §3.6: "thirty percent of the total, rounded half-up to a whole
    cent, is earmarked for the factory-acceptance milestone; forty percent,
    rounded half-up the same way, for the site-acceptance milestone; and the
    guarantee bucket receives whatever remains after those two earmarks,
    absorbing any rounding difference. The evaluation order is fixed — total
    first, then factory, then site, then the guarantee as residual." PRD §3.1:
    "the system multiplies `contract_value_cents` by the owning org's
    `retention_rate_bps`, divides by ten thousand, rounds half-up to a whole
    cent, seeds `retention_balance_cents` with the result, and posts the
    opening `WITHHOLD` ledger entry".

    Design: Difficulty/combinatorial_formula/retention_waterfall_pinned_rounding_order
    """
    # 999,999 cents * 333 bps / 10000 = 33,299.9667 -> round_half_up = 33,300.
    org = create_org(legal_name="OddRates", retention_rate_bps=333)
    eng = create_user(org["id"], "Eng One", "PROJECT_ENGINEER")
    site = create_site(org["id"], eng["id"], site_name="Plant D")
    proj = create_project(
        site["id"],
        eng["id"],
        project_code="P-333",
        contracted_cycle_time_s=10.0,
        contract_value_cents=999999,
        guaranteed_oee_pct=80.0,
    )
    assert proj["retention_balance_cents"] == 33300

    resp = api.list_retention_ledger_entries(proj["id"], make_finance_admin_headers())
    entries, _meta = validate_paginated(resp)
    withholds = [e for e in entries if e["entry_type"] == "WITHHOLD"]
    assert len(withholds) == 1
    assert withholds[0]["amount_cents"] == 33300


def test_retention_ledger_conservation_across_milestones(api):
    """PRD §2.8: "Conservation is absolute: no posting may drive
    `retention_balance_cents` below zero, and any posting that would is
    rejected with `ERR_RETENTION_OVERRELEASE` (HTTP 422). This rule binds both
    hand-posted adjustments and the automatic postings made when a guarantee
    closes."

    Design: Difficulty/compensating_invariant/retention_ledger_conservation_across_milestones
    """
    org = create_org(retention_rate_bps=1000)
    eng = create_user(org["id"], "Eng One", "PROJECT_ENGINEER")
    site = create_site(org["id"], eng["id"], site_name="Plant Q")
    proj = create_project(
        site["id"],
        eng["id"],
        project_code="P-CI1",
        contracted_cycle_time_s=10.0,
        contract_value_cents=1_000_000,
        guaranteed_oee_pct=80.0,
    )
    assert proj["retention_balance_cents"] == 100000
    fa = make_finance_admin_headers()

    # Paired ADJUST -5000 then +5000 leaves balance unchanged.
    validate_success(
        api.post_retention_ledger_entry(
            proj["id"],
            retention_ledger_entry_payload(proj["version"], "ADJUST", -5000),
            fa,
        ),
        201,
    )
    v1 = get_project(proj["id"], fa)["version"]
    validate_success(
        api.post_retention_ledger_entry(
            proj["id"], retention_ledger_entry_payload(v1, "ADJUST", 5000), fa
        ),
        201,
    )

    final_proj = get_project(proj["id"], fa)
    assert final_proj["retention_balance_cents"] == 100000

    resp = api.list_retention_ledger_entries(proj["id"], fa)
    entries, _ = validate_paginated(resp)
    assert len(entries) == 3
    kinds = [(e["entry_type"], e["amount_cents"]) for e in entries]
    assert ("WITHHOLD", 100000) in kinds
    assert ("ADJUST", -5000) in kinds
    assert ("ADJUST", 5000) in kinds

    # An ADJUST that would drive the balance below zero is rejected.
    resp = api.post_retention_ledger_entry(
        proj["id"],
        retention_ledger_entry_payload(
            final_proj["version"], "ADJUST", -100001
        ),
        fa,
    )
    validate_error(resp, ApiErrorId.ERR_RETENTION_OVERRELEASE)


def test_retention_overrelease_guard(api):
    """PRD §2.8: "no posting may drive `retention_balance_cents` below zero,
    and any posting that would is rejected with `ERR_RETENTION_OVERRELEASE`
    (HTTP 422)."

    Design: Corner/errors/retention_overrelease_guard
    """
    org = create_org(retention_rate_bps=1000)
    eng = create_user(org["id"], "Eng One", "PROJECT_ENGINEER")
    site = create_site(org["id"], eng["id"], site_name="S21")
    proj = create_project(
        site["id"],
        eng["id"],
        project_code="P-OVER",
        contracted_cycle_time_s=10.0,
        contract_value_cents=1_000_000,
        guaranteed_oee_pct=80.0,
    )
    assert proj["retention_balance_cents"] == 100000

    resp = api.post_retention_ledger_entry(
        proj["id"],
        retention_ledger_entry_payload(proj["version"], "ADJUST", -100001),
        make_finance_admin_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_RETENTION_OVERRELEASE)

    after = get_project(proj["id"], make_finance_admin_headers())
    assert after["retention_balance_cents"] == 100000


def test_guarantee_close_before_window_end_rejected(api):
    """PRD §3.9: "Closing before the window ends is rejected with
    `ERR_GUARANTEE_WINDOW_VIOLATION`."

    Design: Corner/validations/guarantee_close_before_window_end_rejected
    """
    ctx = setup_project_in_guarantee(project_overrides={"project_code": "P-GW"})
    proj = ctx["project"]
    svc = ctx["users"]["SERVICE_MANAGER"]

    from test_helpers import (
        get_throughput_guarantee_for_project,
        make_service_manager_headers,
    )

    guar = get_throughput_guarantee_for_project(
        proj["id"], make_service_manager_headers(svc["id"])
    )
    # Logical clock has been moved to 2026-08-11 during training completion;
    # the guarantee window opened at SAT->TRAINING (logical clock then) and
    # ends guarantee_window_days (default 90) later, so the window is still
    # open and close must be rejected.
    resp = api.close_throughput_guarantee(
        guar["id"],
        {"outcome": "MET", "observed_cycle_time_s": 9.0, "observed_uptime_pct": 90.0},
        make_service_manager_headers(svc["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_GUARANTEE_WINDOW_VIOLATION)


def test_throughput_shortfall_max_of_two_metrics(api):
    """PRD §3.9: "the cycle shortfall is the excess of observed over
    contracted cycle time expressed as a percentage of the contracted time,
    floored at zero; the uptime shortfall is the amount by which observed
    uptime falls below the guaranteed OEE, in percentage points, likewise
    floored at zero; `shortfall_pct` is the larger of the two, rounded half-up
    to two decimal places. The penalty posted is a `PENALTY` ledger entry for
    the smaller of the outstanding `retention_balance_cents` and the
    `contract_value_cents` multiplied by the shortfall percentage divided by
    one hundred, rounded half-up to a whole cent — sized to zero the balance".

    Design: Corner/calculations/throughput_shortfall_max_of_two_metrics
    """
    ctx = setup_project_in_guarantee(project_overrides={"project_code": "P-SHORT"})
    proj = ctx["project"]
    svc = ctx["users"]["SERVICE_MANAGER"]

    from test_helpers import (
        get_throughput_guarantee_for_project,
        make_service_manager_headers,
    )

    guar = get_throughput_guarantee_for_project(
        proj["id"], make_service_manager_headers(svc["id"])
    )
    assert guar["guarantee_status"] == "MEASURING"

    # Move logical clock past window end (default 90 days from SAT advance).
    validate_success(api.set_clock("2027-08-01T00:00:00Z", make_finance_admin_headers()))

    # Cycle shortfall = (11.0-10.0)/10.0*100 = 10.00; uptime shortfall =
    # 80.0-70.0 = 10.00 -> shortfall_pct = 10.00.
    closed = validate_success(
        api.close_throughput_guarantee(
            guar["id"],
            {
                "outcome": "MISSED",
                "observed_cycle_time_s": 11.0,
                "observed_uptime_pct": 70.0,
            },
            make_service_manager_headers(svc["id"]),
        )
    )
    assert closed["guarantee_status"] == "MISSED"
    assert closed["shortfall_pct"] == 10.0

    # Balance was 30,000 after FAT 30,000 + SAT 40,000 releases from 100,000.
    # Penalty = min(30,000, round_half_up(1,000,000*10.00/100)) = min(30,000,
    # 100,000) = 30,000, posted as a PENALTY and zeroing the balance.
    fa = make_finance_admin_headers()
    resp = api.list_retention_ledger_entries(proj["id"], fa)
    entries, _ = validate_paginated(resp)
    penalties = [e for e in entries if e["entry_type"] == "PENALTY"]
    assert len(penalties) == 1
    assert penalties[0]["amount_cents"] == -30000

    after = get_project(proj["id"], fa)
    assert after["retention_balance_cents"] == 0
