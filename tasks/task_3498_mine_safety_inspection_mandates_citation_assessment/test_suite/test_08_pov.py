"""Pattern-of-violations program (PRD §3.7): the rolling 365-day window, the
SCREENING vs FINAL_DETERMINATION variant divergence, the >= 8 threshold, and
the POV_FINAL auto-order cascade (§3.5).

Clock note: all readings are >= the startup reading 2026-09-01T00:00:00Z
(PRD §2.4). The window-edge probe pins three citations at exactly
2026-09-10T00:00:00Z and one at +1s, then screens at 2027-09-10T00:00:00Z so
window_start lands exactly on the boundary instant (365 days, no leap day in
the span).
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_pov_screening,
    create_citation_payload,
    create_mine_payload,
    file_contest_flow,
    get_success_data,
    in_progress_inspection,
    issue_citation,
    issue_citations_for_pov,
    make_inspector_headers,
    refresh_mine,
    run_screening,
    set_clock,
    setup_citation,
    setup_inspector,
    setup_operator,
    setup_pov_final_mine,
    setup_registry,
    validate_created,
    validate_error,
    validate_paginated,
)

_ADMIN = TEST_USERS["admin_headers"]
_DM = TEST_USERS["district_manager_headers"]

_SS_MODERATE = {"significant_and_substantial": True, "negligence": "MODERATE"}


def test_pov_screening_includes_contested_final_excludes(api):
    """PRD §3.7: "Citations whose contest axis is `VACATED` never count; the
    `SCREENING` variant does, however, count citations under an unresolved
    contest (one still `FILED` or `DOCKETED`)."
    PRD §3.7: "it creates a `POVScreening` of `variant` `FINAL_DETERMINATION`
    over the same window mechanics but excluding citations under unresolved
    contest, so identical raw history can score lower than the screening that
    justified the notice. If that final-determination `weighted_score` falls
    short of 8 the notice is rejected with `ERR_POV_SCORE_INSUFFICIENT`."

    Design: Difficulty/dual_variant_calc/pov_screening_includes_contested_final_excludes
    """
    set_clock("2026-09-01T08:00:00Z")
    operator, mine, i1 = setup_registry(tonnage=1000)
    citations = issue_citations_for_pov(mine, i1, [_SS_MODERATE] * 4)

    # The fourth citation goes under unresolved contest (FILED).
    set_clock("2026-09-05T10:00:00Z")
    file_contest_flow(citations[3], operator, grounds="contesting the fourth citation")

    set_clock("2026-09-15T09:00:00Z")
    screening = run_screening(mine)
    assert_pov_screening(screening)
    assert screening["variant"] == "SCREENING"
    assert screening["ss_citation_count"] == 4
    assert screening["weighted_score"] == 8, "the FILED-contest citation still counts"
    assert screening["result"] == "POTENTIAL_POV"
    assert refresh_mine(mine["id"])["pov_status"] == "POTENTIAL_POV"

    # FINAL_DETERMINATION excludes the unresolved contested citation: 3 x 2 = 6.
    resp = api.issue_pov_notice(mine["id"], _DM)
    validate_error(resp, ApiErrorId.ERR_POV_SCORE_INSUFFICIENT)
    assert refresh_mine(mine["id"])["pov_status"] == "POTENTIAL_POV", (
        "no POV_FINAL escalation on a rejected notice"
    )


def test_pov_final_ss_citation_auto_ido_cascade(api):
    """PRD §3.5: "While a mine stands in `POV_FINAL` posture, every newly
    issued citation bearing the `significant_and_substantial` designation
    auto-creates an imminent-danger order at that mine, recording the
    citation's inspection as its `inspection_id` and the citing inspector as
    its `issued_by_inspector_id`, and the same halt-and-suspend cascade then
    fires."

    Design: Difficulty/transitive_cascade/pov_final_ss_citation_auto_ido_cascade
    """
    set_clock("2026-09-01T08:00:00Z")
    bundle = setup_pov_final_mine()  # 4 S&S citations -> screening -> notice
    mine, i1 = bundle["mine"], bundle["inspector"]
    assert mine["pov_status"] == "POV_FINAL"
    assert bundle["notice"]["variant"] == "FINAL_DETERMINATION"
    assert bundle["notice"]["result"] == "CONFIRMED_POV"

    set_clock("2026-09-16T08:00:00Z")
    inspection = in_progress_inspection(
        mine, i1, kind="SPOT",
        planned_start_at="2026-09-16T08:00:00Z",
        planned_end_at="2026-09-16T12:00:00Z",
    )
    set_clock("2026-09-16T09:00:00Z")
    resp = api.create_citation(
        create_citation_payload(
            inspection["id"], mine["id"],
            standard_code="30 CFR 75.500",
            negligence="HIGH", gravity_likelihood="REASONABLY_LIKELY",
            gravity_severity="SERIOUS", persons_affected=4,
            significant_and_substantial=True, repeat_violation=False,
        ),
        make_inspector_headers(i1["id"]),
    )
    citation = validate_created(resp)  # the cascade is post-commit, not a rejection
    assert citation["significant_and_substantial"] is True

    orders, meta = validate_paginated(
        api.list_imminent_danger_orders(_DM, params={"mine_id": mine["id"]})
    )
    assert len(orders) == 1 and meta["total_count"] == 1, (
        "exactly one auto-created order exists at the mine"
    )
    auto = orders[0]
    assert auto["inspection_id"] == inspection["id"]
    assert auto["issued_by_inspector_id"] == i1["id"]
    assert auto["status"] == "ISSUED"

    assert refresh_mine(mine["id"])["production_status"] == "HALTED"
    suspended = get_success_data(api.get_inspection(inspection["id"], _DM))
    assert suspended["status"] == "SUSPENDED", (
        "the inspection that produced the citation is suspended by its own cascade"
    )


def test_pov_score_exact_threshold_eight(api):
    """PRD §3.7: "The `weighted_score` adds 2 points per
    significant-and-substantial citation in the window, a further 1 point per
    citation in the window whose negligence is `HIGH` or `RECKLESS_DISREGARD`
    — so an S&S citation with `HIGH` negligence contributes 3 — and 5 points
    per imminent-danger order issued at the mine in the window, with orders
    counted regardless of their status."
    PRD §3.7: "When the `weighted_score` reaches at least 8 the screening's
    `result` is `POTENTIAL_POV`, otherwise `BELOW_THRESHOLD`; a mine in `NONE`
    posture escalates to `POTENTIAL_POV` on such a result, and a later
    screening that falls below 8 relaxes a `POTENTIAL_POV` mine back to `NONE`,
    each flip incrementing the mine's `version`."

    Design: Difficulty/boundary_precision_check/pov_score_exact_threshold_eight
    """
    set_clock("2026-09-01T08:00:00Z")
    operator = setup_operator(annual_tonnage_tons=1000)
    i1 = setup_inspector()
    mine_a = get_success_data(
        api.create_mine(
            create_mine_payload(
                operator["id"], mine_name="Threshold Mine A",
                mine_type="UNDERGROUND", activation_date="2026-09-01",
            ),
            _ADMIN,
        )
    )
    mine_b = get_success_data(
        api.create_mine(
            create_mine_payload(
                operator["id"], mine_name="Threshold Mine B",
                mine_type="UNDERGROUND", activation_date="2026-09-01",
            ),
            _ADMIN,
        )
    )

    # Mine A: 4 S&S citations -> 4 x 2 = 8 (inclusive boundary crosses).
    issue_citations_for_pov(mine_a, i1, [_SS_MODERATE] * 4, base_date="2026-09-01")
    # Mine B: 3 S&S + 1 HIGH-negligence non-S&S -> 3 x 2 + 1 = 7 (one short).
    issue_citations_for_pov(
        mine_b, i1, [_SS_MODERATE] * 3 + [{"negligence": "HIGH"}],
        base_date="2026-09-08",
    )

    set_clock("2026-09-15T09:00:00Z")
    screening_a = run_screening(mine_a)
    assert screening_a["weighted_score"] == 8
    assert screening_a["result"] == "POTENTIAL_POV"
    assert refresh_mine(mine_a["id"])["pov_status"] == "POTENTIAL_POV"

    screening_b = run_screening(mine_b)
    assert screening_b["weighted_score"] == 7
    assert screening_b["result"] == "BELOW_THRESHOLD"
    assert refresh_mine(mine_b["id"])["pov_status"] == "NONE"


def test_pov_window_excludes_citations_older_than_365_days(api):
    """PRD §3.7: "An `MSHAAdmin` runs a screening at a mine, creating a
    **POVScreening** whose `variant` is `SCREENING`, whose `screened_at` is the
    current clock, and whose `window_start` is exactly 365 days before
    `screened_at`; a citation counts when its `issued_at` is strictly after
    `window_start` and on or before `screened_at`."

    Design: Corner/calculations/pov_window_excludes_citations_older_than_365_days
    """
    set_clock("2026-09-05T08:00:00Z")
    _operator, mine, i1 = setup_registry(tonnage=1000)
    set_clock("2026-09-09T09:00:00Z")
    inspection = in_progress_inspection(
        mine, i1, kind="SPOT",
        planned_start_at="2026-09-09T08:00:00Z",
        planned_end_at="2026-09-10T17:00:00Z",
    )
    # Three S&S citations land exactly on what will be the window's open edge.
    set_clock("2026-09-10T00:00:00Z")
    for n in range(3):
        issue_citation(
            inspection, mine, i1,
            standard_code=f"30 CFR 75.40{n}",
            negligence="MODERATE", gravity_likelihood="UNLIKELY",
            gravity_severity="NO_INJURY", persons_affected=1,
            significant_and_substantial=True, repeat_violation=False,
        )
    # One citation lands one second inside the window.
    set_clock("2026-09-10T00:00:01Z")
    issue_citation(
        inspection, mine, i1,
        standard_code="30 CFR 75.403",
        negligence="MODERATE", gravity_likelihood="UNLIKELY",
        gravity_severity="NO_INJURY", persons_affected=1,
        significant_and_substantial=True, repeat_violation=False,
    )

    set_clock("2027-09-10T00:00:00Z")
    screening = run_screening(mine)
    assert_pov_screening(screening)
    assert screening["window_start"] == "2026-09-10T00:00:00Z"
    assert screening["ss_citation_count"] == 1, (
        "issued_at == window_start is strictly-outside; only the +1s citation counts"
    )
    assert screening["weighted_score"] == 2
    assert screening["result"] == "BELOW_THRESHOLD"
    assert refresh_mine(mine["id"])["pov_status"] == "NONE"


def test_err_pov_notice_requires_potential_status(api):
    """PRD §3.7: "Issuing a pattern-of-violations notice at a mine requires
    the mine to stand at `POTENTIAL_POV` — otherwise
    `ERR_POV_NOTICE_REQUIRES_POTENTIAL`"

    Design: Corner/errors/err_pov_notice_requires_potential_status
    """
    set_clock("2026-09-10T08:00:00Z")
    bundle = setup_citation()  # one non-S&S citation; mine posture NONE
    mine = bundle["mine"]

    resp = api.issue_pov_notice(mine["id"], _DM)
    validate_error(resp, ApiErrorId.ERR_POV_NOTICE_REQUIRES_POTENTIAL)

    assert refresh_mine(mine["id"])["pov_status"] == "NONE"
    screenings, meta = validate_paginated(
        api.list_pov_screenings(mine["id"], _DM)
    )
    assert screenings == [] and meta["total_count"] == 0, (
        "a rejected notice consults no score and creates no screening row"
    )
