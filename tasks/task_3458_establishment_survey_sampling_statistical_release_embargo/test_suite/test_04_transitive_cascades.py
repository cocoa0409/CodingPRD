"""Depth tests: transitive cascades.

A breach report runs grant -> outlet -> sibling grants -> release counters
(depth 3); a methodology activation runs notice -> FINAL cells -> factor
sets -> published-release disclosure (depth 2+), from a different trigger.
"""
from test_helpers import (
    TEST_USERS,
    api_client,
    apply_benchmark_run,
    approve_disclosure,
    close_collection,
    create_accredited_outlet,
    create_admin_cell_count,
    create_benchmark_run,
    create_factor_set,
    create_notice,
    create_release,
    create_stratum,
    finalize_factor_set,
    get_grant,
    get_release,
    get_single_cell,
    grant_for_outlet,
    list_grants,
    notice_action,
    open_embargo,
    publish_release,
    read_bulletin,
    report_breach,
    set_clock,
    setup_certified_cycle,
    setup_enrolled_panel,
    setup_program_with_frozen_frame,
    validate_paginated,
)

METHODOLOGIST = TEST_USERS["survey_methodologist_headers"]


def test_embargo_breach_cascade_depth3(api):
    """PRD §3.9: "A `ReleaseManager` who reports a breach on a grant in `ISSUED` or `ACCESSED` moves that grant to the terminal `BREACHED`, and the cascade runs three levels deep: the grant's owning outlet moves from `ACCREDITED` to `SUSPENDED`; every other grant of that outlet still in `ISSUED` or `ACCESSED` — across all releases — moves to `REVOKED`; and each affected release's `active_embargo_grant_count` is recomputed."
    PRD §3.9: "thereafter it always counts this release's grants in `ISSUED` or `ACCESSED`, recomputed whenever any of those grants changes status."

    Design: Difficulty/transitive_cascade/embargo_breach_cascade_depth3
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_program_with_frozen_frame(code="CES", sample_budget=3,
                                    annual_burden_budget_minutes=500)
    panel = setup_enrolled_panel("CES", count=3)
    en1, en2, en3 = panel["enrollments"]

    # September cycle certified and PUBLISHED; O1's grant G1 already ACCESSED.
    cyc_sep = setup_certified_cycle(
        "CES", "2026-09", panel["enrollments"],
        {en1["id"]: 9, en2["id"]: 11, en3["id"]: 8})
    outlet = create_accredited_outlet(name="Wire Service")
    rel1 = create_release(cyc_sep["id"], "2026-10-01T13:30:00Z")
    approve_disclosure(rel1["id"])
    open_embargo(rel1["id"])
    g1 = grant_for_outlet(rel1["id"], outlet["id"])
    read_bulletin(g1["id"], outlet["id"])  # ISSUED -> ACCESSED
    publish_release(rel1["id"])

    # October cycle certified; release R2 EMBARGO_OPEN with grant G2 ISSUED.
    cyc_oct = setup_certified_cycle(
        "CES", "2026-10", panel["enrollments"],
        {en1["id"]: 10, en2["id"]: 12, en3["id"]: 9})
    rel2 = create_release(cyc_oct["id"], "2026-10-26T13:30:00Z")
    approve_disclosure(rel2["id"])
    open_embargo(rel2["id"])
    g2 = grant_for_outlet(rel2["id"], outlet["id"])

    breached = report_breach(g2["id"])
    assert breached["grant_status"] == "BREACHED", "link 1: the reported grant"

    rows, _meta = validate_paginated(api_client.list_outlets(
        TEST_USERS["release_manager_headers"],
        params={"accreditation_status": "SUSPENDED"}))
    assert len(rows) == 1 and rows[0]["id"] == outlet["id"], (
        "link 2: breach cascade suspends the outlet")

    assert get_grant(g1["id"])["grant_status"] == "REVOKED", (
        "link 3: suspension revokes the outlet's other active grant on the "
        "published September release")
    assert get_release(rel1["id"])["active_embargo_grant_count"] == 0, (
        "link 4: published release's active grant counter recomputed 1 -> 0")
    assert get_release(rel2["id"])["active_embargo_grant_count"] == 0, (
        "breached grant no longer counts as active")


def test_methodology_activate_reconstruction_cascade(api):
    """PRD §3.8: "its `employment_estimate` is multiplied by `reconstruction_factor_ppm`, divided by 1,000,000, and rounded half up to a whole person; the cell moves to the terminal `RECONSTRUCTED` status and its `revision_no` increments by 1."
    PRD §3.8: "The cascade continues sideways: every in-scope `FINAL` seasonal factor set moves to `SUPERSEDED`, and for every affected cycle whose release is `PUBLISHED`, the release's `revision_notice_required` is set to true while an `APPROVED` disclosure reverts to `PENDING`."

    Design: Difficulty/transitive_cascade/methodology_activate_reconstruction_cascade
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_program_with_frozen_frame(
        code="CES", sample_budget=4,
        strata=[create_stratum("MANUFACTURING", "SMALL", 40)],
        annual_burden_budget_minutes=500)
    panel = setup_enrolled_panel("CES", count=4)
    s1 = create_factor_set("CES", year=2026, month_overrides={1: 0.95, 9: 1.05})

    # December cycle: 25x4 -> estimate 1000; certified and PUBLISHED.
    cyc = setup_certified_cycle(
        "CES", "2026-12", panel["enrollments"],
        {en["id"]: 25 for en in panel["enrollments"]})
    rel = create_release(cyc["id"], "2026-12-25T13:30:00Z")
    approve_disclosure(rel["id"])
    open_embargo(rel["id"])
    publish_release(rel["id"])

    # Benchmark realigns the cell to FINAL at 1045 and re-flags the release.
    run = create_benchmark_run("CES", "2026-12", [create_admin_cell_count(
        "MANUFACTURING", "SMALL", 1045)])
    apply_benchmark_run(run["id"])
    rel_mid = get_release(rel["id"])
    assert rel_mid["disclosure_status"] == "PENDING", (
        "benchmark cascade already reverted disclosure once")
    assert rel_mid["revision_notice_required"] is True
    approve_disclosure(rel["id"])  # re-approval after the benchmark

    # Factor set finalized (annual revision), then a methodology notice.
    finalize_factor_set(s1["id"], at="2027-01-02T00:00:00Z")
    notice = create_notice("CES", "NAICS 2027 conversion",
                           "2027-01-10T00:00:00Z",
                           reconstruction_factor_ppm=1100000)
    notice_action(notice["id"], "ANNOUNCE")
    set_clock("2027-01-10T00:00:00Z")

    activated = notice_action(notice["id"], "ACTIVATE")
    assert activated["notice_status"] == "EFFECTIVE"

    cell = get_single_cell(cyc["id"], "MANUFACTURING", "SMALL")
    assert cell["employment_estimate"] == 1150, (
        f"round_half_up(1045 x 1100000 / 1000000) = round_half_up(1149.5) = "
        f"1150, got {cell['employment_estimate']}")
    assert cell["estimate_status"] == "RECONSTRUCTED"
    assert cell["revision_no"] == 3, (
        "preliminary 1 -> benchmark 2 -> reconstruction 3")

    rows, _meta = validate_paginated(api_client.list_factor_sets(
        METHODOLOGIST, params={"program_code": "CES", "year": 2026}))
    assert len(rows) == 1 and rows[0]["set_status"] == "SUPERSEDED", (
        "reconstruction invalidates factors derived from pre-change data")

    rel_end = get_release(rel["id"])
    assert rel_end["disclosure_status"] == "PENDING"
    assert rel_end["revision_notice_required"] is True, (
        "ACTIVATE re-flagged the published release after re-approval")
