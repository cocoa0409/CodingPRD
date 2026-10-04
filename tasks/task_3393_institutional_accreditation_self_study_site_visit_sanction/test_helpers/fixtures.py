"""Composite setup helpers for the accreditation pipeline (PRD §3).

Every fixture builds preconditions from scratch via declared endpoints only
(the server restarts with an empty database before every test). All
entity-backed calls thread the owning entity's id into the role headers.
Setup calls fail fast with a "Setup failed" RuntimeError naming the step.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    CLOCK_DEFAULT_ISO,
    CRITERION_CODES,
    EVIDENCE_PLAN_STANDARD,
    INDICATOR_METRICS_HEALTHY,
    INDICATOR_METRICS_PANEL_BAND,
    PANEL_QUORUM,
    PANEL_SIZE,
    POST_VISIT_CLOCK_ISO,
    VISIT_END_ISO,
    VISIT_START_ISO,
)
from .factories import (
    adjudicate_payload,
    assurance_argument_payload,
    cast_vote_payload,
    change_request_payload,
    clock_payload,
    decide_payload,
    eligibility_application_payload,
    evidence_item_payload,
    federal_compliance_payload,
    file_report_payload,
    indicator_report_payload,
    indicator_submit_payload,
    institution_patch_payload,
    institution_payload,
    panel_payload,
    respond_payload,
    review_cycle_payload,
    reviewer_payload,
    sanction_transition_payload,
    schedule_visit_payload,
    team_assembly_payload,
    verify_payload,
)
from .test_users import TEST_USERS, make_liaison_headers, make_reviewer_headers

ADMIN = TEST_USERS["admin_headers"]
STAFF = TEST_USERS["staff_headers"]

PANELIST_NAMES = ["One", "Two", "Three", "Four", "Five", "Six", "Seven"]


def _ok(response, what: str) -> dict:
    if response.status_code >= 400:
        raise RuntimeError(
            f"Setup failed ({what}): HTTP {response.status_code} {response.text}"
        )
    return get_success_data(response)


def _list(path_fn, *args, params=None) -> list:
    data, _meta = validate_paginated(path_fn(*args, STAFF, params=params))
    return data


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------

def set_logical_clock(to_iso8601: str = CLOCK_DEFAULT_ISO) -> dict:
    return _ok(api_client.set_clock(clock_payload(to_iso8601), ADMIN), "set logical clock")


# ---------------------------------------------------------------------------
# Institutions & eligibility (PRD §3.1, §3.2)
# ---------------------------------------------------------------------------

def create_institution(**overrides) -> dict:
    return _ok(
        api_client.create_institution(institution_payload(**overrides), ADMIN),
        "create institution",
    )


def get_institution(institution_id: str) -> dict:
    return _ok(api_client.get_institution(institution_id, STAFF), "get institution")


def patch_institution(institution_id: str, **fields) -> dict:
    """Versioned profile update; re-reads the current version for OCC."""
    current = get_institution(institution_id)
    payload = institution_patch_payload(current["version"], **fields)
    return _ok(
        api_client.update_institution(institution_id, payload, STAFF),
        "patch institution",
    )


def create_eligibility_application(institution_id: str, pathway: str = "STANDARD", **overrides) -> dict:
    return _ok(
        api_client.create_eligibility_application(
            institution_id,
            eligibility_application_payload(pathway=pathway, **overrides),
            make_liaison_headers(institution_id),
        ),
        "create eligibility application",
    )


def file_eligibility_application(application_id: str, institution_id: str) -> dict:
    return _ok(
        api_client.file_eligibility_application(
            application_id, {}, make_liaison_headers(institution_id)
        ),
        "file eligibility application",
    )


def adjudicate_application(application_id: str, decision: str = "APPROVE", notes=None) -> dict:
    return _ok(
        api_client.adjudicate_eligibility_application(
            application_id, adjudicate_payload(decision, notes), STAFF
        ),
        f"adjudicate application ({decision})",
    )


def create_candidate_institution(pathway: str = "STANDARD", **inst_overrides) -> dict:
    """Institution -> DRAFT application -> FILED -> APPROVE -> CANDIDATE.

    Does NOT touch the logical clock; callers that depend on dates must call
    set_logical_clock() first.
    """
    institution = create_institution(**inst_overrides)
    institution_id = institution["id"]
    application = create_eligibility_application(institution_id, pathway=pathway)
    file_eligibility_application(application["id"], institution_id)
    application = adjudicate_application(application["id"], "APPROVE")
    return {
        "institution": get_institution(institution_id),
        "application": application,
    }


# ---------------------------------------------------------------------------
# Review cycle (PRD §3.3)
# ---------------------------------------------------------------------------

def create_review_cycle(institution_id: str, cycle_type: str = "INITIAL_ACCREDITATION") -> dict:
    return _ok(
        api_client.create_review_cycle(
            institution_id, review_cycle_payload(cycle_type), STAFF
        ),
        "create review cycle",
    )


def advance_cycle(cycle_id: str, what: str = "advance review cycle") -> dict:
    return _ok(api_client.advance_review_cycle(cycle_id, {}, STAFF), what)


def get_review_cycle(cycle_id: str) -> dict:
    return _ok(api_client.get_review_cycle(cycle_id, STAFF), "get review cycle")


def record_federal_compliance(cycle_id: str, components=None, cohort_default_rates=None) -> dict:
    return _ok(
        api_client.record_federal_compliance(
            cycle_id,
            federal_compliance_payload(components, cohort_default_rates),
            STAFF,
        ),
        "record federal compliance",
    )


# ---------------------------------------------------------------------------
# Assurance argument & evidence (PRD §3.4)
# ---------------------------------------------------------------------------

def create_assurance_argument(cycle_id: str, institution_id: str, **overrides) -> dict:
    return _ok(
        api_client.create_assurance_argument(
            cycle_id,
            assurance_argument_payload(**overrides),
            make_liaison_headers(institution_id),
        ),
        "create assurance argument",
    )


def add_evidence_item(argument_id: str, institution_id: str, criterion_code: str, ordinal: int, **overrides) -> dict:
    return _ok(
        api_client.create_evidence_item(
            argument_id,
            evidence_item_payload(criterion_code, ordinal, **overrides),
            make_liaison_headers(institution_id),
        ),
        f"add evidence {criterion_code}#{ordinal}",
    )


def add_evidence_set(argument_id: str, institution_id: str, plan=None) -> dict:
    """Attach `plan[criterion]` items per criterion. Returns {criterion: [items]}."""
    plan = plan or EVIDENCE_PLAN_STANDARD
    evidence = {}
    for code in CRITERION_CODES:
        evidence[code] = [
            add_evidence_item(argument_id, institution_id, code, i + 1)
            for i in range(plan.get(code, 0))
        ]
    return evidence


def submit_argument(argument_id: str, institution_id: str) -> dict:
    return _ok(
        api_client.submit_assurance_argument(
            argument_id, {}, make_liaison_headers(institution_id)
        ),
        "submit assurance argument",
    )


def request_argument_revision(argument_id: str) -> dict:
    return _ok(
        api_client.request_argument_revision(argument_id, {}, STAFF),
        "request argument revision",
    )


def lock_argument(argument_id: str) -> dict:
    return _ok(
        api_client.lock_assurance_argument(argument_id, {}, STAFF),
        "lock assurance argument",
    )


def get_assurance_argument(argument_id: str) -> dict:
    return _ok(api_client.get_assurance_argument(argument_id, STAFF), "get assurance argument")


def set_evidence_verified(item_id: str, reviewer_id: str, verified: bool = True) -> dict:
    return _ok(
        api_client.verify_evidence_item(
            item_id, verify_payload(verified), make_reviewer_headers(reviewer_id)
        ),
        f"verify evidence {item_id} -> {verified}",
    )


def verify_evidence_plan(evidence: dict, plan: dict, reviewer_id: str) -> None:
    """Verify the first plan[criterion] items of each criterion."""
    for code, count in plan.items():
        for item in evidence[code][:count]:
            set_evidence_verified(item["id"], reviewer_id, True)


# ---------------------------------------------------------------------------
# Reviewer registry & team assembly (PRD §3.5)
# ---------------------------------------------------------------------------

def create_reviewer(**overrides) -> dict:
    return _ok(
        api_client.create_reviewer(reviewer_payload(**overrides), STAFF),
        "create reviewer",
    )


def get_reviewer(reviewer_id: str) -> dict:
    return _ok(api_client.get_reviewer(reviewer_id, STAFF), "get reviewer")


def register_team_pool() -> dict:
    """The canonical four-reviewer pool: one chair-eligible + three members.

    Ranking is deterministic: Ada (chair bar met, quality 4.50) chairs;
    member seats rank by specialty coverage 4/3/2 (Ben, Cara, Dan).
    """
    chair = create_reviewer(
        full_name="Ada Chair",
        specialty_criteria=list(CRITERION_CODES),
        quality_rating=4.50,
        prior_chair_count=3,
    )
    member2 = create_reviewer(
        full_name="Ben Member",
        specialty_criteria=["CRIT_MISSION", "CRIT_INTEGRITY", "CRIT_TEACHING_QUALITY", "CRIT_RESOURCES_PLANNING"],
        quality_rating=4.00,
    )
    member3 = create_reviewer(
        full_name="Cara Member",
        specialty_criteria=["CRIT_MISSION", "CRIT_INTEGRITY", "CRIT_TEACHING_QUALITY"],
        quality_rating=3.50,
    )
    member4 = create_reviewer(
        full_name="Dan Member",
        specialty_criteria=["CRIT_MISSION", "CRIT_INTEGRITY"],
        quality_rating=3.00,
    )
    return {"chair": chair, "members": [member2, member3, member4]}


def assemble_review_team(cycle_id: str, visit_modality: str = "ON_SITE") -> dict:
    """Assemble with OCC: re-reads the cycle to present its current version."""
    cycle = get_review_cycle(cycle_id)
    return _ok(
        api_client.assemble_review_team(
            cycle_id,
            team_assembly_payload(cycle["version"], visit_modality),
            STAFF,
        ),
        "assemble review team",
    )


def list_team_assignments(team_id: str, reviewer_id: str = None) -> list:
    params = {"reviewer_id": reviewer_id} if reviewer_id else None
    return _list(api_client.list_team_assignments, team_id, params=params)


def get_assignment_for_reviewer(team_id: str, reviewer_id: str, status: str = "ACTIVE") -> dict:
    assignments = [
        a for a in list_team_assignments(team_id, reviewer_id) if a["status"] == status
    ]
    if not assignments:
        raise RuntimeError(
            f"Setup failed: no {status} assignment for reviewer {reviewer_id} on team {team_id}"
        )
    return assignments[0]


def respond_to_assignment(assignment_id: str, reviewer_id: str, response: str = "ACCEPT") -> dict:
    return _ok(
        api_client.respond_to_assignment(
            assignment_id, respond_payload(response), make_reviewer_headers(reviewer_id)
        ),
        f"respond to assignment ({response})",
    )


def accept_assignment(team_id: str, reviewer_id: str) -> dict:
    assignment = get_assignment_for_reviewer(team_id, reviewer_id)
    return respond_to_assignment(assignment["id"], reviewer_id, "ACCEPT")


def confirm_team(team_id: str) -> dict:
    return _ok(api_client.confirm_review_team(team_id, {}, STAFF), "confirm review team")


def get_review_team(team_id: str) -> dict:
    return _ok(api_client.get_review_team(team_id, STAFF), "get review team")


# ---------------------------------------------------------------------------
# Site visit (PRD §3.6)
# ---------------------------------------------------------------------------

def schedule_visit(team_id: str, chair_reviewer_id: str,
                   visit_start_at: str = VISIT_START_ISO,
                   visit_end_at: str = VISIT_END_ISO) -> dict:
    return _ok(
        api_client.schedule_visit(
            team_id,
            schedule_visit_payload(visit_start_at, visit_end_at),
            make_reviewer_headers(chair_reviewer_id),
        ),
        "schedule visit",
    )


def cancel_visit(team_id: str) -> dict:
    return _ok(api_client.cancel_visit(team_id, {}, STAFF), "cancel visit")


def file_team_report(team_id: str, chair_reviewer_id: str, ratings: dict = None,
                     report_recommendation: str = None, report_summary: str = None) -> dict:
    return _ok(
        api_client.file_team_report(
            team_id,
            file_report_payload(ratings, report_recommendation, report_summary),
            make_reviewer_headers(chair_reviewer_id),
        ),
        "file team report",
    )


# ---------------------------------------------------------------------------
# Decision panel & outcomes (PRD §3.7, §3.8)
# ---------------------------------------------------------------------------

def register_panelists(count: int = PANEL_SIZE) -> list:
    """Fresh, unaffiliated, conflict-free reviewers eligible for panel seating."""
    return [
        create_reviewer(
            full_name=f"Panelist {PANELIST_NAMES[i]}",
            specialty_criteria=["CRIT_MISSION"],
            quality_rating=3.00,
            prior_chair_count=0,
        )
        for i in range(count)
    ]


def convene_decision_panel(cycle_id: str, member_reviewer_ids: list = None) -> dict:
    ids = member_reviewer_ids or [r["id"] for r in register_panelists()]
    return _ok(
        api_client.convene_decision_panel(cycle_id, panel_payload(ids), STAFF),
        "convene decision panel",
    )


def cast_panel_vote(panel_id: str, reviewer_id: str, choice: str) -> dict:
    return _ok(
        api_client.cast_panel_vote(
            panel_id, cast_vote_payload(choice), make_reviewer_headers(reviewer_id)
        ),
        f"cast vote {choice}",
    )


def cast_panel_votes(panel_id: str, member_ids: list, choices) -> None:
    for reviewer_id, choice in zip(member_ids, choices):
        cast_panel_vote(panel_id, reviewer_id, choice)


def close_decision_panel(panel_id: str) -> dict:
    return _ok(api_client.close_decision_panel(panel_id, {}, STAFF), "close decision panel")


def list_cycle_outcomes(cycle_id: str) -> list:
    return _list(api_client.list_cycle_action_outcomes, cycle_id)


def list_institution_outcomes(institution_id: str) -> list:
    return _list(api_client.list_institution_action_outcomes, institution_id)


def advance_outcome(outcome_id: str, what: str = "advance action outcome") -> dict:
    return _ok(api_client.advance_action_outcome(outcome_id, {}, STAFF), what)


def apply_sanction_transition(outcome_id: str, action: str) -> dict:
    return _ok(
        api_client.sanction_transition(outcome_id, sanction_transition_payload(action), STAFF),
        f"sanction transition {action}",
    )


# ---------------------------------------------------------------------------
# Substantive change (PRD §3.9)
# ---------------------------------------------------------------------------

def create_change_request(institution_id: str, change_type: str = "NEW_LOCATION", **overrides) -> dict:
    return _ok(
        api_client.create_substantive_change_request(
            institution_id,
            change_request_payload(change_type, **overrides),
            make_liaison_headers(institution_id),
        ),
        f"create change request ({change_type})",
    )


def submit_change_request(change_id: str, institution_id: str) -> dict:
    return _ok(
        api_client.submit_substantive_change(
            change_id, {}, make_liaison_headers(institution_id)
        ),
        "submit change request",
    )


def decide_change_request(change_id: str, decision: str = "APPROVE", notes=None) -> dict:
    return _ok(
        api_client.decide_substantive_change(
            change_id, decide_payload(decision, notes), STAFF
        ),
        f"decide change request ({decision})",
    )


def list_change_requests(institution_id: str, status: str = None) -> list:
    params = {"status": status} if status else None
    return _list(api_client.list_substantive_change_requests, institution_id, params=params)


# ---------------------------------------------------------------------------
# Indicator monitoring (PRD §3.9)
# ---------------------------------------------------------------------------

def annual_period(year: int) -> tuple:
    return (f"{year}-01-01", f"{year}-12-31")


def create_indicator_report(institution_id: str, period_start: str, period_end: str) -> dict:
    return _ok(
        api_client.create_indicator_report(
            institution_id,
            indicator_report_payload(period_start, period_end),
            STAFF,
        ),
        "create indicator report",
    )


def submit_indicator_report(report_id: str, institution_id: str, metrics=None, **overrides) -> dict:
    return _ok(
        api_client.submit_indicator_report(
            report_id,
            indicator_submit_payload(metrics, **overrides),
            make_liaison_headers(institution_id),
        ),
        "submit indicator report",
    )


def evaluate_indicator_report(report_id: str) -> dict:
    return _ok(
        api_client.evaluate_indicator_report(report_id, {}, STAFF),
        "evaluate indicator report",
    )


def list_indicator_reports(institution_id: str) -> list:
    return _list(api_client.list_indicator_reports, institution_id)


def setup_panel_band_sanction(institution_id: str, year: int = 2026) -> dict:
    """Submit + evaluate a panel-band report: report FLAGGED_PANEL, cascade
    creates an EFFECTIVE NOTICE outcome and moves the institution to NOTICE."""
    start, end = annual_period(year)
    report = create_indicator_report(institution_id, start, end)
    report = submit_indicator_report(report["id"], institution_id, INDICATOR_METRICS_PANEL_BAND)
    report = evaluate_indicator_report(report["id"])
    outcomes = list_institution_outcomes(institution_id)
    cascade = [o for o in outcomes if o["origin"] == "INDICATOR_MONITOR"]
    if not cascade:
        raise RuntimeError("Setup failed: panel-band evaluation created no ActionOutcome")
    return {"report": report, "outcome": cascade[0]}


def submit_cleared_report(institution_id: str, year: int, metrics=None) -> dict:
    """Open, submit (healthy metrics) and evaluate a report into CLEARED."""
    start, end = annual_period(year)
    report = create_indicator_report(institution_id, start, end)
    report = submit_indicator_report(report["id"], institution_id, metrics or INDICATOR_METRICS_HEALTHY)
    return evaluate_indicator_report(report["id"])


# ---------------------------------------------------------------------------
# Composite pipelines (Tier 1–5)
# ---------------------------------------------------------------------------

def setup_cycle_materials_open(clock_iso: str = CLOCK_DEFAULT_ISO,
                               pathway: str = "STANDARD", **inst_overrides) -> dict:
    """Institution approved to CANDIDATE; INITIAL_ACCREDITATION cycle MATERIALS_OPEN."""
    if clock_iso:
        set_logical_clock(clock_iso)
    ctx = create_candidate_institution(pathway=pathway, **inst_overrides)
    institution_id = ctx["institution"]["id"]
    cycle = create_review_cycle(institution_id)
    cycle = advance_cycle(cycle["id"], "advance to MATERIALS_OPEN")
    ctx["cycle"] = cycle
    return ctx


def setup_argument_draft(evidence_plan=None, **kwargs) -> dict:
    """Adds a DRAFT assurance argument with the evidence plan attached."""
    ctx = setup_cycle_materials_open(**kwargs)
    institution_id = ctx["institution"]["id"]
    argument = create_assurance_argument(ctx["cycle"]["id"], institution_id)
    evidence = add_evidence_set(argument["id"], institution_id, evidence_plan)
    ctx["argument"] = argument
    ctx["evidence"] = evidence
    return ctx


def setup_submitted_argument(**kwargs) -> dict:
    """Argument SUBMITTED; cycle advanced to EVALUATION_ACTIVE."""
    ctx = setup_argument_draft(**kwargs)
    institution_id = ctx["institution"]["id"]
    argument = submit_argument(ctx["argument"]["id"], institution_id)
    cycle = advance_cycle(ctx["cycle"]["id"], "advance to EVALUATION_ACTIVE")
    ctx["argument"] = argument
    ctx["cycle"] = cycle
    return ctx


def setup_confirmed_team(visit_modality: str = "ON_SITE", **kwargs) -> dict:
    """Adds the canonical reviewer pool, an assembled team, all ACCEPTED,
    and a CONFIRMED team."""
    ctx = setup_submitted_argument(**kwargs)
    pool = register_team_pool()
    team = assemble_review_team(ctx["cycle"]["id"], visit_modality)
    for reviewer in [pool["chair"], *pool["members"]]:
        accept_assignment(team["id"], reviewer["id"])
    team = confirm_team(team["id"])
    ctx["reviewers"] = pool
    ctx["team"] = team
    return ctx


def setup_locked_argument(**kwargs) -> dict:
    """Confirmed team + argument REVIEW_LOCKED (cycle EVALUATION_ACTIVE)."""
    ctx = setup_confirmed_team(**kwargs)
    ctx["argument"] = lock_argument(ctx["argument"]["id"])
    return ctx


def setup_visit_scheduled(visit_start_at: str = VISIT_START_ISO,
                          visit_end_at: str = VISIT_END_ISO, **kwargs) -> dict:
    """Locked argument + visit window stored (team VISIT_SCHEDULED)."""
    ctx = setup_locked_argument(**kwargs)
    team = schedule_visit(
        ctx["team"]["id"], ctx["team"]["chair_reviewer_id"], visit_start_at, visit_end_at
    )
    ctx["team"] = team
    return ctx


def setup_report_filed(ratings: dict = None, report_recommendation: str = "GRANT",
                       clock_iso: str = POST_VISIT_CLOCK_ISO, **kwargs) -> dict:
    """Clock advanced past visit end; chair files the report (REPORT_FILED)."""
    ctx = setup_visit_scheduled(**kwargs)
    if clock_iso:
        set_logical_clock(clock_iso)
    team = file_team_report(
        ctx["team"]["id"], ctx["team"]["chair_reviewer_id"],
        ratings=ratings, report_recommendation=report_recommendation,
    )
    ctx["team"] = team
    return ctx


def setup_panel_review(record_compliance: bool = True, **kwargs) -> dict:
    """Report filed -> cycle VISIT_COMPLETE -> seven panelists + panel CONVENED
    -> federal compliance recorded (COMPLIANT by default) -> cycle PANEL_REVIEW."""
    ctx = setup_report_filed(**kwargs)
    cycle = advance_cycle(ctx["cycle"]["id"], "advance to VISIT_COMPLETE")
    panelists = register_panelists()
    panel = convene_decision_panel(cycle["id"], [p["id"] for p in panelists])
    if record_compliance:
        cycle = record_federal_compliance(cycle["id"])
    cycle = advance_cycle(cycle["id"], "advance to PANEL_REVIEW")
    ctx["cycle"] = cycle
    ctx["panel"] = panel
    ctx["panelists"] = panelists
    return ctx


def setup_decided_cycle(choices=None, **kwargs) -> dict:
    """Panel votes cast and closed: outcome DRAFTED, cycle DECIDED, team
    DISBANDED, argument ACCEPTED (when the prevailing action is not DENIAL)."""
    ctx = setup_panel_review(**kwargs)
    choices = list(choices) if choices else ["GRANT"] * PANEL_QUORUM
    member_ids = [p["id"] for p in ctx["panelists"]]
    cast_panel_votes(ctx["panel"]["id"], member_ids, choices)
    panel = close_decision_panel(ctx["panel"]["id"])
    outcomes = list_cycle_outcomes(ctx["cycle"]["id"])
    if not outcomes:
        raise RuntimeError("Setup failed: panel close created no ActionOutcome")
    ctx["panel"] = panel
    ctx["outcome"] = outcomes[0]
    ctx["cycle"] = get_review_cycle(ctx["cycle"]["id"])
    ctx["team"] = get_review_team(ctx["team"]["id"])
    ctx["argument"] = get_assurance_argument(ctx["argument"]["id"])
    return ctx


def setup_accredited_institution(**kwargs) -> dict:
    """Full initial-accreditation pipeline: outcome EFFECTIVE (institution
    ACCREDITED), cycle CLOSED. Clock sits at POST_VISIT_CLOCK_ISO."""
    ctx = setup_decided_cycle(**kwargs)
    advance_outcome(ctx["outcome"]["id"], "disclose outcome")
    outcome = advance_outcome(ctx["outcome"]["id"], "effectuate outcome")
    cycle = advance_cycle(ctx["cycle"]["id"], "close cycle")
    ctx["outcome"] = outcome
    ctx["cycle"] = cycle
    ctx["institution"] = get_institution(ctx["institution"]["id"])
    return ctx
