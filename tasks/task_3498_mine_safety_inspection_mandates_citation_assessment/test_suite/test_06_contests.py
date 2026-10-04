"""Contests and commission adjudication (PRD §3.6, §2.5, §2.8): the 30-day
filing window, contestability state gate, OCC on the citation version, fiscal
decision payloads, and the citation's two independent state axes.

Clock note: all readings are >= the startup reading 2026-09-01T00:00:00Z
(PRD §2.4). A citation issued at 2026-09-01T10:00:00Z has its contest boundary
at exactly 2026-10-01T10:00:00Z (timely, inclusive); one second later lapses.
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    abate_citation_flow,
    create_contest_payload,
    decide_contest_flow,
    docket_contest_flow,
    file_contest_flow,
    get_assessment_for_citation,
    in_progress_inspection,
    issue_citation,
    make_inspector_headers,
    make_operator_rep_headers,
    refresh_citation,
    refresh_contest,
    extend_citation_flow,
    set_clock,
    setup_citation,
    setup_inspector,
    setup_registry,
    validate_created,
    validate_error,
    validate_paginated,
    verify_citation_flow,
)

_DM = TEST_USERS["district_manager_headers"]
_JUDGE = TEST_USERS["commission_judge_headers"]


def test_citation_dual_axes_contest_and_abatement_independent(api):
    """PRD §3.4: "The citation's abatement axis runs `OPEN` → `ABATED` →
    `VERIFIED`, independently of its contest axis."
    PRD §3.6: "`VACATED` moves the axis to `VACATED` and finalizes the
    assessment at zero cents; from `decided_at` onward the vacated citation is
    excluded both from pattern-of-violations windows and from the 730-day
    history counts of future citations."

    Design: Difficulty/non_linear_state_machine/citation_dual_axes_contest_and_abatement_independent
    """
    set_clock("2026-09-10T08:00:00Z")
    operator, mine, i1 = setup_registry(tonnage=1000)
    verifier = setup_inspector()
    inspection = in_progress_inspection(mine, i1, kind="SPOT")
    set_clock("2026-09-10T09:00:00Z")
    citation = issue_citation(inspection, mine, i1, repeat_violation=True)

    # Contest axis advances first.
    set_clock("2026-09-11T10:00:00Z")
    contest = file_contest_flow(citation, operator, grounds="gravity overstated")
    assert refresh_citation(citation["id"])["contest_status"] == "CONTESTED"

    # Abatement axis advances fully while the contest is pending.
    set_clock("2026-09-12T09:00:00Z")
    citation = abate_citation_flow(citation, operator)
    set_clock("2026-09-13T09:00:00Z")
    citation = verify_citation_flow(citation, verifier)

    set_clock("2026-09-14T09:00:00Z")
    docket_contest_flow(contest)

    set_clock("2026-09-15T09:00:00Z")
    decide_contest_flow(contest, "VACATED")

    after = refresh_citation(citation["id"])
    assert after["abatement_status"] == "VERIFIED", (
        "the abatement axis advanced fully while the contest was pending"
    )
    assert after["contest_status"] == "VACATED", (
        "the contest axis resolved independently of abatement"
    )
    assessment = get_assessment_for_citation(citation["id"])
    assert assessment["status"] == "FINAL"
    assert assessment["final_penalty_cents"] == 0, (
        "VACATED zeroes the penalty regardless of verified abatement"
    )


def test_contest_state_error_outranks_window_lapse(api):
    """PRD §2.5: "Every request is evaluated against an ordered cascade of
    validation tiers. When several checks would fail on the same request, the
    response reports the failure from the **earliest** tier; a request that
    fails an earlier tier never surfaces a later tier's error."
    PRD §3.6: "The citation's contest axis must stand at `UNCONTESTED` — a
    citation already `CONTESTED`, or one already `AFFIRMED`, `MODIFIED`, or
    `VACATED`, is not contestable again and answers
    `ERR_CITATION_NOT_CONTESTABLE`."
    PRD §3.6: "And the filing is timely only while `filed_at` falls on or
    before 30 days after the citation's `issued_at` — exactly 30 days after
    issuance is still timely, and a later filing is rejected with
    `ERR_CONTEST_WINDOW_LAPSED`."

    Design: Difficulty/priority_pair_validation_conflict/contest_state_error_outranks_window_lapse
    """
    set_clock("2026-09-01T08:00:00Z")
    operator, mine, i1 = setup_registry(tonnage=1000)
    inspection = in_progress_inspection(mine, i1, kind="SPOT")
    set_clock("2026-09-01T10:00:00Z")
    citation = issue_citation(inspection, mine, i1)

    set_clock("2026-09-05T10:00:00Z")
    file_contest_flow(citation, operator, grounds="first contest")
    assert refresh_citation(citation["id"])["contest_status"] == "CONTESTED"

    # Past the 30-day window (lapsed at 2026-10-01T10:00:00Z) AND already
    # contested. The OCC version is read fresh so only the state (tier 7) and
    # temporal (tier 11) checks can fail — the state check is earlier.
    set_clock("2026-10-03T10:00:00Z")
    fresh = refresh_citation(citation["id"])
    resp = api.create_contest(
        create_contest_payload(citation["id"], fresh["version"],
                               grounds="second contest, late"),
        make_operator_rep_headers(operator["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CITATION_NOT_CONTESTABLE)

    after = refresh_citation(citation["id"])
    assert after["contest_status"] == "CONTESTED"
    assert after["version"] == fresh["version"], (
        "a rejected filing mutates nothing"
    )


def test_contest_window_exact_thirty_days_boundary(api):
    """PRD §3.6: "And the filing is timely only while `filed_at` falls on or
    before 30 days after the citation's `issued_at` — exactly 30 days after
    issuance is still timely, and a later filing is rejected with
    `ERR_CONTEST_WINDOW_LAPSED`."

    Design: Difficulty/boundary_precision_check/contest_window_exact_thirty_days_boundary
    """
    set_clock("2026-09-01T08:00:00Z")
    operator, mine, i1 = setup_registry(tonnage=1000)
    inspection = in_progress_inspection(mine, i1, kind="SPOT")
    set_clock("2026-09-01T10:00:00Z")
    cit_a = issue_citation(inspection, mine, i1, standard_code="30 CFR 75.370")
    cit_b = issue_citation(inspection, mine, i1, standard_code="30 CFR 75.380")

    # filed exactly at issued_at + 30 days: the boundary is inclusive-timely.
    set_clock("2026-10-01T10:00:00Z")
    resp_a = api.create_contest(
        create_contest_payload(cit_a["id"], cit_a["version"],
                               grounds="filed exactly at the 30-day mark"),
        make_operator_rep_headers(operator["id"]),
    )
    contest_a = validate_created(resp_a)
    assert contest_a["filed_at"] == "2026-10-01T10:00:00Z"
    assert contest_a["status"] == "FILED"

    # One second past the boundary: lapsed.
    set_clock("2026-10-01T10:00:01Z")
    resp_b = api.create_contest(
        create_contest_payload(cit_b["id"], cit_b["version"],
                               grounds="one second past the window"),
        make_operator_rep_headers(operator["id"]),
    )
    validate_error(resp_b, ApiErrorId.ERR_CONTEST_WINDOW_LAPSED)
    assert refresh_citation(cit_b["id"])["contest_status"] == "UNCONTESTED"


def test_contest_decided_is_terminal(api):
    """PRD §3.6: "`DECIDED` and `WITHDRAWN` are the contest's terminal states."
    PRD §3.6: "`AFFIRMED` moves the citation's contest axis to `AFFIRMED` and
    finalizes the assessment at the final-variant pipeline amount, good-faith
    discount included when the citation was verified on time."

    Design: Corner/state_machines/contest_decided_is_terminal
    """
    set_clock("2026-09-10T09:00:00Z")
    bundle = setup_citation()
    contest = file_contest_flow(bundle["citation"], bundle["operator"])
    docket_contest_flow(contest)
    decided = decide_contest_flow(contest, "AFFIRMED")
    assert decided["status"] == "DECIDED" and decided["outcome"] == "AFFIRMED"

    resp = api.decide_contest(contest["id"], {"outcome": "VACATED"}, _JUDGE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = refresh_contest(contest["id"])
    assert after["status"] == "DECIDED" and after["outcome"] == "AFFIRMED"
    assert refresh_citation(bundle["citation"]["id"])["contest_status"] == "AFFIRMED"


def test_modified_decision_requires_modified_amount(api):
    """PRD §3.6: "The decision payload is validated fiscally:
    `modified_penalty_cents` is required and must be zero or greater exactly
    when the outcome is `MODIFIED`, and it must not be supplied for `AFFIRMED`
    or `VACATED`; any deviation is rejected with
    `ERR_CONTEST_DECISION_INVALID`."

    Design: Corner/validations/modified_decision_requires_modified_amount
    """
    set_clock("2026-09-10T09:00:00Z")
    bundle = setup_citation()
    cit2 = issue_citation(
        bundle["inspection"], bundle["mine"], bundle["inspector"],
        standard_code="30 CFR 75.380",
    )
    contest1 = docket_contest_flow(
        file_contest_flow(bundle["citation"], bundle["operator"])
    )
    contest2 = docket_contest_flow(file_contest_flow(cit2, bundle["operator"]))

    # MODIFIED without the adjudicated amount.
    resp1 = api.decide_contest(contest1["id"], {"outcome": "MODIFIED"}, _JUDGE)
    validate_error(resp1, ApiErrorId.ERR_CONTEST_DECISION_INVALID)

    # AFFIRMED carrying a modified amount.
    resp2 = api.decide_contest(
        contest2["id"], {"outcome": "AFFIRMED", "modified_penalty_cents": 5000}, _JUDGE
    )
    validate_error(resp2, ApiErrorId.ERR_CONTEST_DECISION_INVALID)

    assert refresh_contest(contest1["id"])["status"] == "DOCKETED"
    assert refresh_contest(contest2["id"])["status"] == "DOCKETED"


def test_inspector_cannot_decide_contest(api):
    """PRD §2.1: "`CommissionJudge` belongs to the independent review
    commission and only dockets and decides contests."
    PRD §2.1: "A request whose role is declared but not permitted on the target
    endpoint is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/inspector_cannot_decide_contest
    """
    set_clock("2026-09-10T09:00:00Z")
    bundle = setup_citation()
    contest = docket_contest_flow(
        file_contest_flow(bundle["citation"], bundle["operator"])
    )
    resp = api.decide_contest(
        contest["id"],
        {"outcome": "VACATED"},
        make_inspector_headers(bundle["inspector"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    assert refresh_contest(contest["id"])["status"] == "DOCKETED"


def test_occ_contest_file_stale_citation_version_rejected(api):
    """PRD §2.8: "Filing a contest requires the request to carry
    `expected_citation_version`, holding the `version` of the target Citation
    as the operator last observed it; since events such as an abatement
    extension mutate the citation, a mismatch with the citation's current
    `version` is likewise rejected with `ERR_STALE_VERSION` (HTTP 412),
    ensuring the contest references the exact instrument the operator intends
    to challenge."

    Design: Corner/complexity_layers/occ_contest_file_stale_citation_version_rejected
    """
    bundle = setup_citation()  # default clock reading; inside every window
    citation = bundle["citation"]
    stale_version = citation["version"]

    # The extension mutates the citation and advances its version.
    extended = extend_citation_flow(citation, bundle["operator"])
    assert extended["version"] != stale_version

    resp = api.create_contest(
        create_contest_payload(citation["id"], stale_version,
                               grounds="stale view of the citation"),
        make_operator_rep_headers(bundle["operator"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert refresh_citation(citation["id"])["contest_status"] == "UNCONTESTED"
    contests, meta = validate_paginated(
        api.list_contests(_DM, params={"citation_id": citation["id"]})
    )
    assert contests == [] and meta["total_count"] == 0
