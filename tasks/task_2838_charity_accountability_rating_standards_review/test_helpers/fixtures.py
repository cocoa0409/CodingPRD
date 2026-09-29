"""Composite setup helpers.

Every test starts against an empty database, so each helper here builds its
preconditions from scratch through PRD-declared endpoints only. Monetary
figures are whole-cent JSON numbers; every timestamp is a full ISO 8601 UTC
instant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    adopt_methodology_payload,
    assign_panel_payload,
    create_appeal_payload,
    create_complaint_payload,
    create_correction_request_payload,
    create_filing_record_payload,
    create_governance_profile_payload,
    create_methodology_version_payload,
    create_organization_payload,
    create_public_comment_payload,
    create_rating_cycle_payload,
    decide_appeal_payload,
    decide_correction_payload,
    dimension_overrides_payload,
    dispose_public_comment_payload,
    publish_payload,
    resolve_complaint_payload,
    triage_complaint_payload,
    validate_filing_payload,
    waive_standard_payload,
)
from .test_users import (
    ADMIN_USER_ID,
    ANALYST_USER_ID,
    PANELIST_USER_IDS,
    REVIEWER_USER_ID,
    TEST_USERS,
    make_admin_headers,
    make_analyst_headers,
    make_organization_rep_headers,
    make_panelist_headers,
    make_public_headers,
    make_reviewer_headers,
)

ADMIN = TEST_USERS["admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]
PUBLIC = TEST_USERS["public_headers"]

# The instant the clock is parked at while a cycle is opened and scored.
CLOCK_AT_CYCLE = "2026-09-01T00:00:00Z"
# `effective_from` exactly 30 days after the untouched clock of 2026-08-01.
DEFAULT_EFFECTIVE_FROM = "2026-08-31T00:00:00Z"

# Three fiscal years of audited figures for the canonical rated charity.
FILING_FY2025 = {
    "total_expense_cents": 10000000,
    "program_expense_cents": 8000000,
    "fundraising_expense_cents": 1200000,
    "admin_expense_cents": 800000,
    "contributions_cents": 9000000,
    "total_revenue_cents": 11000000,
    "net_assets_cents": 6000000,
    "total_liabilities_cents": 2000000,
    "joint_cost_allocated_cents": 500000,
}
FILING_FY2024 = {
    "total_expense_cents": 6000000,
    "program_expense_cents": 4500000,
    "fundraising_expense_cents": 1000000,
    "admin_expense_cents": 500000,
    "contributions_cents": 5000000,
    "total_revenue_cents": 6500000,
    "net_assets_cents": 3000000,
    "total_liabilities_cents": 1000000,
}
FILING_FY2023 = {
    "total_expense_cents": 4000000,
    "program_expense_cents": 2800000,
    "fundraising_expense_cents": 900000,
    "admin_expense_cents": 300000,
    "contributions_cents": 3000000,
    "total_revenue_cents": 4200000,
    "net_assets_cents": 2000000,
    "total_liabilities_cents": 800000,
}
THREE_YEAR_FILINGS = [
    (2025, FILING_FY2025),
    (2024, FILING_FY2024),
    (2023, FILING_FY2023),
]

# A governance disclosure whose impact inputs are all empty, so the IMPACT
# dimension records a data_completeness_pct of exactly 0.00.
NO_IMPACT_GOVERNANCE = {
    "impact_report_on_file": False,
    "outcome_measures_count": 0,
    "third_party_evaluation_on_file": False,
}


# ── Atomic steps ─────────────────────────────────────────────────────────


def set_clock(to_iso8601, headers=None) -> dict:
    """Move the logical clock forward and return the resulting clock payload."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, headers or ADMIN)
    )


def run_transition_sweep(headers=None) -> dict:
    """Expire every ACTIVE grant whose grace_until lies before the clock."""
    return get_success_data(api_client.run_transition_sweep(headers or ADMIN))


def create_organization(**overrides) -> dict:
    """Register one rated charity."""
    return get_success_data(
        api_client.create_organization(create_organization_payload(**overrides), ADMIN)
    )


def read_organization(organization_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_organization(organization_id, headers or ANALYST)
    )


def organization_version(organization_id, headers=None) -> int:
    """Re-read the organization so a filing submission can satisfy §2.7."""
    return read_organization(organization_id, headers)["version"]


def create_draft_methodology(**overrides) -> dict:
    """Draft one methodology version; it lands in DRAFT."""
    return get_success_data(
        api_client.create_methodology_version(
            create_methodology_version_payload(**overrides), ADMIN
        )
    )


def open_comment(methodology_version_id, headers=None) -> dict:
    return get_success_data(
        api_client.open_comment(methodology_version_id, headers or ADMIN)
    )


def close_comment(methodology_version_id, headers=None) -> dict:
    return get_success_data(
        api_client.close_comment(methodology_version_id, headers or ADMIN)
    )


def file_public_comment(methodology_version_id, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_public_comment(
            create_public_comment_payload(methodology_version_id, **overrides),
            headers or PUBLIC,
        )
    )


def dispose_public_comment(public_comment_id, disposition="DECLINED", **overrides) -> dict:
    return get_success_data(
        api_client.dispose_public_comment(
            public_comment_id,
            dispose_public_comment_payload(disposition, **overrides),
            ADMIN,
        )
    )


def create_comment_closed_methodology(**overrides) -> dict:
    """Draft a version and walk it DRAFT -> COMMENT_OPEN -> COMMENT_CLOSED."""
    methodology = create_draft_methodology(**overrides)
    open_comment(methodology["id"])
    close_comment(methodology["id"])
    return get_success_data(
        api_client.get_methodology_version(methodology["id"], ADMIN)
    )


def adopt_methodology(methodology_version_id, effective_from, effective_until=None) -> dict:
    return get_success_data(
        api_client.adopt_methodology_version(
            methodology_version_id,
            adopt_methodology_payload(effective_from, effective_until),
            ADMIN,
        )
    )


def create_adopted_methodology(
    effective_from=DEFAULT_EFFECTIVE_FROM, effective_until=None, **overrides
) -> dict:
    """Draft, run a comment window and adopt one methodology version."""
    methodology = create_comment_closed_methodology(**overrides)
    return adopt_methodology(methodology["id"], effective_from, effective_until)


def submit_filing(
    organization_id,
    fiscal_year=2025,
    source_kind="AUDITED_STATEMENT",
    headers=None,
    expected_organization_version=None,
    **amounts,
) -> dict:
    """Submit one filing, re-reading the organization's version when needed."""
    version = expected_organization_version
    if version is None:
        version = organization_version(organization_id)
    payload = create_filing_record_payload(
        organization_id,
        version,
        fiscal_year=fiscal_year,
        source_kind=source_kind,
        **amounts,
    )
    return get_success_data(
        api_client.create_filing_record(payload, headers or ANALYST)
    )


def validate_filing(filing_record_id, decision="ACCEPT", headers=None, **extra) -> dict:
    return get_success_data(
        api_client.validate_filing_record(
            filing_record_id, validate_filing_payload(decision, **extra), headers or ANALYST
        )
    )


def submit_validated_filing(
    organization_id, fiscal_year=2025, source_kind="AUDITED_STATEMENT", **amounts
) -> dict:
    """Submit a filing and accept it, so a calculation may read it."""
    filing = submit_filing(
        organization_id, fiscal_year=fiscal_year, source_kind=source_kind, **amounts
    )
    return validate_filing(filing["id"])


def create_cycle(organization_id, methodology_version_id, headers=None, **overrides) -> dict:
    """Open one rating cycle, pinning the methodology version that scores it."""
    payload = create_rating_cycle_payload(
        organization_id, methodology_version_id, **overrides
    )
    analyst_headers = headers or make_analyst_headers(
        payload["assigned_analyst_user_id"]
    )
    return get_success_data(api_client.create_rating_cycle(payload, analyst_headers))


def read_cycle(rating_cycle_id, headers=None) -> dict:
    return get_success_data(api_client.get_rating_cycle(rating_cycle_id, headers or ANALYST))


def read_score_breakdown(rating_cycle_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_score_breakdown(rating_cycle_id, headers or ANALYST)
    )


def read_dimension_scores(rating_cycle_id, headers=None) -> list:
    return get_success_data(
        api_client.list_dimension_scores(rating_cycle_id, headers or ANALYST)
    )


def create_governance_profile(rating_cycle_id, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_governance_profile(
            create_governance_profile_payload(rating_cycle_id, **overrides),
            headers or ANALYST,
        )
    )


def evaluate_governance_profile(governance_profile_id, headers=None) -> dict:
    return get_success_data(
        api_client.evaluate_governance_profile(governance_profile_id, headers or ANALYST)
    )


def create_evaluated_governance_profile(rating_cycle_id, headers=None, **overrides) -> dict:
    """Record a disclosure and run the standards evaluation over it."""
    profile = create_governance_profile(rating_cycle_id, headers=headers, **overrides)
    evaluate_governance_profile(profile["id"], headers=headers)
    return get_success_data(
        api_client.get_governance_profile(profile["id"], headers or ANALYST)
    )


def read_standard_evaluations(governance_profile_id, headers=None) -> list:
    return get_success_data(
        api_client.list_standard_evaluations(governance_profile_id, headers or ANALYST)
    )


def waive_standard(standard_evaluation_id, **overrides) -> dict:
    return get_success_data(
        api_client.waive_standard_evaluation(
            standard_evaluation_id, waive_standard_payload(**overrides), ADMIN
        )
    )


def revoke_standard_waiver(standard_evaluation_id, **overrides) -> dict:
    from .factories import revoke_waiver_payload

    return get_success_data(
        api_client.revoke_standard_waiver(
            standard_evaluation_id, revoke_waiver_payload(**overrides), ADMIN
        )
    )


def score_cycle(rating_cycle_id, headers=None) -> dict:
    return get_success_data(
        api_client.score_rating_cycle(rating_cycle_id, headers or ANALYST)
    )


def open_org_review(rating_cycle_id, headers=None) -> dict:
    return get_success_data(
        api_client.open_org_review(rating_cycle_id, headers or ANALYST)
    )


def publish_cycle(rating_cycle_id, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.publish_rating_cycle(
            rating_cycle_id, publish_payload(**overrides), headers or REVIEWER
        )
    )


def withdraw_cycle(rating_cycle_id, headers=None, **overrides) -> dict:
    from .factories import withdraw_payload

    return get_success_data(
        api_client.withdraw_rating_cycle(
            rating_cycle_id, withdraw_payload(**overrides), headers or ADMIN
        )
    )


def override_dimensions(rating_cycle_id, overrides_list, expected_rating_cycle_version, **extra) -> dict:
    return get_success_data(
        api_client.create_dimension_overrides(
            rating_cycle_id,
            dimension_overrides_payload(
                overrides_list, expected_rating_cycle_version, **extra
            ),
            ANALYST,
        )
    )


# ── Composite scenarios ──────────────────────────────────────────────────


def setup_scored_cycle(
    org_overrides=None,
    methodology_overrides=None,
    cycle_overrides=None,
    governance_overrides=None,
    filings=None,
    effective_from=DEFAULT_EFFECTIVE_FROM,
    effective_until=None,
    clock_at_cycle=CLOCK_AT_CYCLE,
    evaluate=True,
    score=True,
    creator_headers=None,
) -> dict:
    """Adopted methodology, registered charity, validated filings, evaluated
    governance disclosure and — by default — a scored rating cycle.

    Returns a scenario dict whose keys name the entities the caller needs:
    `organization`, `methodology`, `cycle`, `governance_profile`,
    `standard_evaluations`, `filings`, `filing_by_year`, `dimension_scores`,
    plus pre-threaded headers for each acting role.

    `creator_headers` lets a caller open the cycle as a `RatingAnalyst` other
    than the one it assigns, which `POST /rating-cycles` permits because the
    assigned-analyst check of §2.8 does not guard cycle creation.
    """
    methodology = create_adopted_methodology(
        effective_from=effective_from,
        effective_until=effective_until,
        **(methodology_overrides or {}),
    )
    if clock_at_cycle:
        set_clock(clock_at_cycle)

    organization = create_organization(**(org_overrides or {}))
    org_rep_headers = make_organization_rep_headers(organization["id"])

    filing_rows = []
    for fiscal_year, amounts in filings if filings is not None else THREE_YEAR_FILINGS:
        filing_rows.append(
            submit_validated_filing(
                organization["id"], fiscal_year=fiscal_year, **amounts
            )
        )

    cycle_payload_overrides = dict(cycle_overrides or {})
    analyst_user_id = cycle_payload_overrides.get(
        "assigned_analyst_user_id", ANALYST_USER_ID
    )
    analyst_headers = make_analyst_headers(analyst_user_id)
    cycle = create_cycle(
        organization["id"],
        methodology["id"],
        headers=creator_headers or analyst_headers,
        **cycle_payload_overrides,
    )

    profile = None
    standard_evaluations = []
    if evaluate:
        profile = create_evaluated_governance_profile(
            cycle["id"], headers=analyst_headers, **(governance_overrides or {})
        )
        standard_evaluations = read_standard_evaluations(
            profile["id"], headers=analyst_headers
        )
    elif governance_overrides is not None:
        profile = create_governance_profile(
            cycle["id"], headers=analyst_headers, **governance_overrides
        )

    if score:
        cycle = score_cycle(cycle["id"], headers=analyst_headers)

    scenario = {
        "organization": organization,
        "methodology": methodology,
        "cycle": cycle,
        "governance_profile": profile,
        "standard_evaluations": standard_evaluations,
        "filings": filing_rows,
        "filing_by_year": {row["fiscal_year"]: row for row in filing_rows},
        "analyst_user_id": analyst_user_id,
        "analyst_headers": analyst_headers,
        "org_rep_headers": org_rep_headers,
        "reviewer_headers": REVIEWER,
        "admin_headers": ADMIN,
        "public_headers": PUBLIC,
        "dimension_scores": (
            read_dimension_scores(cycle["id"], headers=analyst_headers) if score else []
        ),
    }
    return scenario


def setup_cycle_in_org_review(**kwargs) -> dict:
    """A scored cycle whose organization review is open, arming the correction
    window 21 days out from the clock."""
    scenario = setup_scored_cycle(**kwargs)
    scenario["cycle"] = open_org_review(
        scenario["cycle"]["id"], headers=scenario["analyst_headers"]
    )
    return scenario


def setup_publishable_cycle(**kwargs) -> dict:
    """A cycle in organization review with the clock parked exactly on
    `correction_deadline_at`, the first instant publication is admissible."""
    scenario = setup_cycle_in_org_review(**kwargs)
    set_clock(scenario["cycle"]["correction_deadline_at"])
    return scenario


def setup_published_cycle(**kwargs) -> dict:
    """A published cycle plus the publication ledger row it appended."""
    scenario = setup_publishable_cycle(**kwargs)
    scenario["cycle"] = publish_cycle(scenario["cycle"]["id"])
    records = get_success_data(
        api_client.list_publication_records(
            ADMIN, params={"rating_cycle_id": scenario["cycle"]["id"]}
        )
    )
    scenario["publication_record"] = records[0] if records else None
    scenario["organization"] = read_organization(scenario["organization"]["id"])
    return scenario


def file_correction(rating_cycle_id, org_rep_headers, **overrides) -> dict:
    """The rated charity disputes one figure on a cycle in organization review."""
    return get_success_data(
        api_client.create_correction_request(
            create_correction_request_payload(rating_cycle_id, **overrides),
            org_rep_headers,
        )
    )


def claim_correction(correction_request_id, headers=None) -> dict:
    return get_success_data(
        api_client.claim_correction_request(correction_request_id, headers or ANALYST)
    )


def decide_correction(correction_request_id, decision="REJECT", headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.decide_correction_request(
            correction_request_id,
            decide_correction_payload(decision, **overrides),
            headers or ANALYST,
        )
    )


def setup_submitted_correction(correction_overrides=None, **kwargs) -> dict:
    """A cycle in CORRECTION_REQUESTED with one SUBMITTED correction."""
    scenario = setup_cycle_in_org_review(**kwargs)
    scenario["correction"] = file_correction(
        scenario["cycle"]["id"],
        scenario["org_rep_headers"],
        **(correction_overrides or {}),
    )
    scenario["cycle"] = read_cycle(scenario["cycle"]["id"])
    return scenario


def setup_claimed_correction(correction_overrides=None, **kwargs) -> dict:
    """A correction the cycle's own analyst has taken ownership of."""
    scenario = setup_submitted_correction(
        correction_overrides=correction_overrides, **kwargs
    )
    scenario["correction"] = claim_correction(
        scenario["correction"]["id"], headers=scenario["analyst_headers"]
    )
    return scenario


def setup_rejected_correction(correction_overrides=None, **kwargs) -> dict:
    """A rejected correction, which is what arms the appeal window."""
    scenario = setup_claimed_correction(
        correction_overrides=correction_overrides, **kwargs
    )
    scenario["correction"] = decide_correction(
        scenario["correction"]["id"], "REJECT", headers=scenario["analyst_headers"]
    )
    scenario["cycle"] = read_cycle(scenario["cycle"]["id"])
    return scenario


def setup_accepted_correction(correction_overrides=None, **kwargs) -> dict:
    """An accepted correction, which rewinds the cycle to DATA_COLLECTION."""
    scenario = setup_claimed_correction(
        correction_overrides=correction_overrides, **kwargs
    )
    scenario["correction"] = decide_correction(
        scenario["correction"]["id"], "ACCEPT", headers=scenario["analyst_headers"]
    )
    scenario["cycle"] = read_cycle(scenario["cycle"]["id"])
    return scenario


def file_appeal(rating_cycle_id, correction_request_id, org_rep_headers, **overrides) -> dict:
    return get_success_data(
        api_client.create_appeal(
            create_appeal_payload(rating_cycle_id, correction_request_id, **overrides),
            org_rep_headers,
        )
    )


def assign_panel(appeal_id, panel_member_user_ids=None, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.assign_appeal_panel(
            appeal_id,
            assign_panel_payload(panel_member_user_ids, **overrides),
            headers or ADMIN,
        )
    )


def decide_appeal(appeal_id, decision="DENY", panelist_user_id=None, **overrides) -> dict:
    headers = make_panelist_headers(panelist_user_id or PANELIST_USER_IDS[0])
    return get_success_data(
        api_client.decide_appeal(
            appeal_id, decide_appeal_payload(decision, **overrides), headers
        )
    )


def setup_filed_appeal(**kwargs) -> dict:
    """A rejected correction contested by an appeal in FILED."""
    scenario = setup_rejected_correction(**kwargs)
    scenario["appeal"] = file_appeal(
        scenario["cycle"]["id"],
        scenario["correction"]["id"],
        scenario["org_rep_headers"],
    )
    scenario["cycle"] = read_cycle(scenario["cycle"]["id"])
    return scenario


def setup_panel_assigned_appeal(panel_member_user_ids=None, **kwargs) -> dict:
    """An appeal with three distinct panelists seated on it."""
    scenario = setup_filed_appeal(**kwargs)
    scenario["appeal"] = assign_panel(
        scenario["appeal"]["id"], panel_member_user_ids
    )
    scenario["panel_member_user_ids"] = scenario["appeal"]["panel_member_user_ids"]
    return scenario


# ── Filing and governance profiles for specific arithmetic outcomes ───────

# Figures that earn every FINANCIAL_HEALTH point on all three ladders.
FILING_PERFECT = {
    "total_expense_cents": 10000000,
    "program_expense_cents": 9000000,
    "fundraising_expense_cents": 500000,
    "admin_expense_cents": 500000,
    "contributions_cents": 10000000,
    "total_revenue_cents": 11000000,
    "net_assets_cents": 12000000,
    "total_liabilities_cents": 1000000,
}
PERFECT_FILINGS = [
    (2025, FILING_PERFECT),
    (2024, FILING_PERFECT),
    (2023, FILING_PERFECT),
]

# A disclosure on which all eight standards are MET and every impact input is
# present, so all four dimensions normalise to 100.00.
PERFECT_GOVERNANCE = {
    "board_member_count": 9,
    "independent_board_member_count": 6,
    "conflict_of_interest_policy_on_file": True,
    "coi_policy_reviewed_at": "2026-03-01T00:00:00Z",
    "board_meetings_last_year": 4,
    "audit_committee_exists": True,
    "whistleblower_policy": True,
    "ceo_compensation_reviewed": True,
    "impact_report_on_file": True,
    "outcome_measures_count": 4,
    "third_party_evaluation_on_file": True,
}

# All eight standards MET, but only three published outcome measures.
ALL_STANDARDS_MET_GOVERNANCE = dict(PERFECT_GOVERNANCE, outcome_measures_count=3)


def with_amounts(base, **changes) -> dict:
    """Copy a filing amount set, replacing named figures."""
    amounts = dict(base)
    amounts.update(changes)
    return amounts


def three_years_of(amounts) -> list:
    """The same audited figures filed for the cycle year and the two before it."""
    return [(2025, amounts), (2024, amounts), (2023, amounts)]


# ── Publication walk ─────────────────────────────────────────────────────


def walk_cycle_to_published(rating_cycle_id, analyst_headers=None, reviewer_headers=None) -> dict:
    """Open organization review, advance the clock onto `correction_deadline_at`
    and publish the cycle."""
    cycle = open_org_review(rating_cycle_id, headers=analyst_headers or ANALYST)
    set_clock(cycle["correction_deadline_at"])
    return publish_cycle(rating_cycle_id, headers=reviewer_headers or REVIEWER)


def add_cycle_for_year(
    scenario,
    fiscal_year=2024,
    period_start="2024-01-01T00:00:00Z",
    period_end="2025-01-01T00:00:00Z",
    governance_overrides=None,
    score=True,
) -> dict:
    """Open a second, non-overlapping cycle on the same charity and methodology."""
    cycle = create_cycle(
        scenario["organization"]["id"],
        scenario["methodology"]["id"],
        headers=scenario["analyst_headers"],
        fiscal_year=fiscal_year,
        period_start=period_start,
        period_end=period_end,
        assigned_analyst_user_id=scenario["analyst_user_id"],
    )
    profile = create_evaluated_governance_profile(
        cycle["id"],
        headers=scenario["analyst_headers"],
        **(governance_overrides or {}),
    )
    if score:
        cycle = score_cycle(cycle["id"], headers=scenario["analyst_headers"])
    return {"cycle": cycle, "governance_profile": profile}


# ── Complaints ───────────────────────────────────────────────────────────


def file_complaint(organization_id, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_complaint(
            create_complaint_payload(organization_id, **overrides), headers or PUBLIC
        )
    )


def triage_complaint(complaint_id, disposition="INVESTIGATE", headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.triage_complaint(
            complaint_id,
            triage_complaint_payload(disposition, **overrides),
            headers or ANALYST,
        )
    )


def resolve_complaint(
    complaint_id, finding="SUBSTANTIATED", penalty_points=None, headers=None, **overrides
) -> dict:
    return get_success_data(
        api_client.resolve_complaint(
            complaint_id,
            resolve_complaint_payload(finding, penalty_points, **overrides),
            headers or ANALYST,
        )
    )


def reverse_complaint_finding(complaint_id, headers=None, **overrides) -> dict:
    from .factories import reverse_finding_payload

    return get_success_data(
        api_client.reverse_complaint_finding(
            complaint_id, reverse_finding_payload(**overrides), headers or ADMIN
        )
    )


def setup_investigating_complaint(organization_id, complainant_headers=None, **overrides) -> dict:
    """A complaint triaged for investigation, scored under the intake variant."""
    complaint = file_complaint(organization_id, headers=complainant_headers, **overrides)
    return triage_complaint(complaint["id"], "INVESTIGATE")


def setup_substantiated_complaint(
    organization_id, penalty_points=5, complainant_headers=None, **overrides
) -> dict:
    """A substantiated complaint that has already driven its penalty cascade."""
    complaint = setup_investigating_complaint(
        organization_id, complainant_headers=complainant_headers, **overrides
    )
    return resolve_complaint(complaint["id"], "SUBSTANTIATED", penalty_points)


# ── Adoption cascade, impact projection and transition grants ────────────

# Weights that shift almost all mass onto FINANCIAL_HEALTH.
M2_WEIGHTS = {
    "version_label": "M2",
    "weight_financial_health": 0.65,
    "weight_accountability": 0.10,
    "weight_transparency": 0.10,
    "weight_impact": 0.15,
}


def adopt_successor_methodology(
    superseded_methodology_id,
    effective_from="2027-01-30T00:00:00Z",
    effective_until=None,
    **overrides,
) -> dict:
    """Draft, comment and adopt a successor version that retires its predecessor."""
    payload_overrides = dict(M2_WEIGHTS)
    payload_overrides["supersedes_version_id"] = superseded_methodology_id
    payload_overrides.update(overrides)
    return create_adopted_methodology(
        effective_from=effective_from,
        effective_until=effective_until,
        **payload_overrides,
    )


def setup_transition_grant(**kwargs) -> dict:
    """A published charity whose rating a successor methodology would cut by at
    least 5.00 points, so adoption mints it a transition grant."""
    scenario = setup_published_cycle(**kwargs)
    scenario["successor_methodology"] = adopt_successor_methodology(
        scenario["methodology"]["id"]
    )
    grants = get_success_data(
        api_client.list_transition_grants(
            ADMIN, params={"organization_id": scenario["organization"]["id"]}
        )
    )
    scenario["transition_grants"] = grants
    scenario["transition_grant"] = grants[0] if grants else None
    scenario["organization"] = read_organization(scenario["organization"]["id"])
    scenario["methodology"] = get_success_data(
        api_client.get_methodology_version(scenario["methodology"]["id"], ADMIN)
    )
    return scenario


# ── Correction targets ───────────────────────────────────────────────────

# A dispute over the governance disclosure rather than a filing. The two
# conditional fields are set to None so the payload omits them entirely, which
# is what the PRD requires of a GOVERNANCE_DISCLOSURE target.
GOVERNANCE_CORRECTION = {
    "target_kind": "GOVERNANCE_DISCLOSURE",
    "target_field_name": "ceo_compensation_reviewed",
    "proposed_value": "true",
    "narrative": "The compensation committee reviewed chief-executive pay in March 2026",
    "target_fiscal_year": None,
    "target_source_kind": None,
}

# A dispute over the reserve figure on the audited FY2025 statement, cutting
# `net_assets_cents` from 6,000,000 to 2,000,000.
FILING_CORRECTION = {
    "target_kind": "FILING_FINANCIAL",
    "target_fiscal_year": 2025,
    "target_source_kind": "AUDITED_STATEMENT",
    "target_field_name": "net_assets_cents",
    "proposed_value": "2000000",
    "narrative": "The audited net assets figure double-counted a restricted pledge",
}


def read_filing(filing_record_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_filing_record(filing_record_id, headers or ANALYST)
    )


def read_organization_filings(organization_id, headers=None, **params) -> list:
    """The organization's filing reverse-read, in winning-selector order."""
    return get_success_data(
        api_client.list_organization_filing_records(
            organization_id, headers or ANALYST, params=params or None
        )
    )


def read_correction(correction_request_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_correction_request(correction_request_id, headers or ANALYST)
    )


def read_appeal(appeal_id, headers=None) -> dict:
    return get_success_data(api_client.get_appeal(appeal_id, headers or ANALYST))


def read_complaint(complaint_id, headers=None) -> dict:
    return get_success_data(api_client.get_complaint(complaint_id, headers or ANALYST))


def read_governance_profile(governance_profile_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_governance_profile(governance_profile_id, headers or ANALYST)
    )


def read_publication_records(headers=None, **params) -> list:
    return get_success_data(
        api_client.list_publication_records(headers or ADMIN, params=params or None)
    )


def setup_bare_organization(**overrides) -> dict:
    """One registered charity and nothing else — no methodology, no cycle.

    The logical clock is left at its untouched default.
    """
    organization = create_organization(**overrides)
    return {
        "organization": organization,
        "org_rep_headers": make_organization_rep_headers(organization["id"]),
        "admin_headers": ADMIN,
        "analyst_headers": ANALYST,
        "public_headers": PUBLIC,
    }
