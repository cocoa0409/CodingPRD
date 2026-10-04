"""Recognition and pledges: the pinned base-then-bonus award scoring, the
conferral recompute of the employer's tier, the vetting gates, the nominator
qualification rule, and the statement lapse/renewal cycle."""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    assert_award_score_invariants,
    assert_instant,
    assert_recognition_award,
    award_payload,
    create_certified_ombudsman,
    create_employer,
    create_signed_statement,
    create_statement,
    make_ombudsman_headers,
    nominate_award,
    read_employer,
    resolve_case_for_employer,
    set_clock,
    setup_employer_with_resolved_cases,
    sign_statement,
    transition_award,
    validate_error,
    validate_success,
)


def _setup_employer_with_two_resolved(api: ApiClient) -> dict:
    """Employer with a signed statement and exactly two RESOLVED_INFORMAL cases."""
    set_clock(api)
    employer = create_employer(api, legal_name="Meridian Grocers Co-op", sector="RETAIL", size_tier="LARGE")
    ombudsman = create_certified_ombudsman(api)
    create_signed_statement(api, employer["id"])
    setup_employer_with_resolved_cases(api, employer, ombudsman, 2)
    return {"employer": employer, "ombudsman": ombudsman}


def test_award_score_base_tier_then_bonus_snapshot(api: ApiClient):
    """PRD §3.9: "Then the snapshot computes: `score_base` awards 10 points per resolved case, adds 15 when a signed statement exists, and subtracts 10 per open case; `tier_qualified` is read from `score_base` alone — at least 60 qualifies `GOLD`, at least 40 qualifies `SILVER`, at least 20 qualifies `BRONZE` — and a base below 20 fails vetting outright; `score_bonus` adds 30 keyed to a `GOLD` qualification, 15 to `SILVER`, 5 to `BRONZE`; and `score_final` is the base plus the bonus."

    Design: Difficulty/combinatorial_formula/award_score_base_tier_then_bonus
    """
    world = _setup_employer_with_two_resolved(api)
    employer = read_employer(api, world["employer"]["id"])
    assert employer["resolved_case_count"] == 2 and employer["open_case_count"] == 0

    award = nominate_award(api, world["employer"]["id"], tier="BRONZE",
                           rationale="Two clean informal resolutions and a signed statement.")
    vetted = transition_award(api, award["id"], "VETTED")
    assert_award_score_invariants(vetted)
    assert vetted["score_base"] == 35, "2 resolved * 10 + 15 signed - 0 open * 10"
    assert vetted["tier_qualified"] == "BRONZE", "35 clears the BRONZE floor but not the SILVER gate"
    assert vetted["score_bonus"] == 5
    assert vetted["score_final"] == 40


def test_award_tier_not_recomputed_from_final_score(api: ApiClient, coordinator_headers: dict):
    """PRD §3.9: "The qualified tier is never recomputed from the final score: a base of 35 qualifies `BRONZE`, the 5-point bonus lifts the final to 40, and the tier stays `BRONZE` even though 40 reaches the `SILVER` gate."
    PRD §3.9: "Conferral, `VETTED → CONFERRED`, then recomputes the employer's `recognition_tier` as the highest tier among its `CONFERRED` awards, or `NONE` when it has none."

    Design: Difficulty/combinatorial_formula/award_score_base_tier_then_bonus
    """
    world = _setup_employer_with_two_resolved(api)
    award = nominate_award(api, world["employer"]["id"], tier="BRONZE",
                           rationale="Two clean informal resolutions and a signed statement.")
    transition_award(api, award["id"], "VETTED")
    conferred = transition_award(api, award["id"], "CONFERRED")
    assert conferred["status"] == "CONFERRED"
    assert conferred["tier_qualified"] == "BRONZE"
    assert conferred["score_final"] == 40

    employer = read_employer(api, world["employer"]["id"])
    assert employer["recognition_tier"] == "BRONZE", \
        "the conferred tier is the base-keyed BRONZE, not the SILVER the final score would reach"


def test_statement_lapses_and_renews_with_fresh_expiry(api: ApiClient, coordinator_headers: dict):
    """PRD §2.4: "A signed statement flips from `SIGNED` to `LAPSED` only when the clock is strictly later than `expires_on`."
    PRD §3.9: "A signed statement lapses lazily into `LAPSED` once the clock is strictly past `expires_on`, and a lapsed statement may be renewed — `LAPSED → SIGNED` — which re-stamps `signed_on` and recomputes `expires_on` afresh."

    Design: Corner/state_machines/statement_lapses_and_renews_with_fresh_expiry
    """
    set_clock(api)
    employer = create_employer(api)
    statement = create_signed_statement(api, employer["id"])
    assert_instant(statement["expires_on"], "2028-09-01T00:00:00Z", "expires_on")

    set_clock(api, "2028-09-01T00:00:00Z")
    at_expiry = validate_success(api.list_employer_statements(employer["id"], coordinator_headers))
    assert at_expiry[0]["status"] == "SIGNED", "at the exact expires_on instant the statement is still SIGNED"

    set_clock(api, "2028-09-02T00:00:00Z")
    past_expiry = validate_success(api.list_employer_statements(employer["id"], coordinator_headers))
    assert past_expiry[0]["status"] == "LAPSED", "one day past expiry the lazy lapse applies"

    renewed = sign_statement(api, statement["id"], employer["id"])
    assert renewed["status"] == "SIGNED"
    assert_instant(renewed["signed_on"], "2028-09-02T00:00:00Z", "renewed signed_on")
    assert_instant(renewed["expires_on"], "2030-09-02T00:00:00Z", "renewed expires_on")


def test_award_confer_recomputes_employer_recognition_tier(api: ApiClient, coordinator_headers: dict):
    """PRD §3.9: "Conferral, `VETTED → CONFERRED`, then recomputes the employer's `recognition_tier` as the highest tier among its `CONFERRED` awards, or `NONE` when it has none."
    PRD §3.9: "Then the snapshot computes: `score_base` awards 10 points per resolved case, adds 15 when a signed statement exists, and subtracts 10 per open case"

    Design: Corner/state_machines/award_confer_recomputes_employer_recognition_tier
    """
    set_clock(api)
    employer = create_employer(api)
    ombudsman = create_certified_ombudsman(api)
    resolve_case_for_employer(api, employer, ombudsman)
    create_signed_statement(api, employer["id"])
    assert read_employer(api, employer["id"])["recognition_tier"] == "NONE"

    award = nominate_award(api, employer["id"], tier="BRONZE", rationale="Clean informal resolution.")
    vetted = transition_award(api, award["id"], "VETTED")
    assert_award_score_invariants(vetted)
    assert vetted["score_base"] == 25, "1 resolved * 10 + 15 signed - 0 open"
    assert vetted["tier_qualified"] == "BRONZE"
    assert vetted["score_bonus"] == 5
    assert vetted["score_final"] == 30

    conferred = transition_award(api, award["id"], "CONFERRED")
    assert conferred["status"] == "CONFERRED"
    assert read_employer(api, employer["id"])["recognition_tier"] == "BRONZE"


def test_award_vet_without_signed_statement_returns_eligibility_unmet(api: ApiClient, coordinator_headers: dict):
    """PRD §3.9: "The employer must hold at least one statement in `SIGNED` status — lazy lapse applied first — and its `resolved_case_count` must clear the nominated tier's gate: at least 1 for `BRONZE`, 3 for `SILVER`, 5 for `GOLD`."
    PRD §3.9: "Failing the statement requirement, the resolved-case gate, or the base-score floor all surface as `ERR_AWARD_ELIGIBILITY_UNMET`."

    Design: Corner/validations/award_vet_without_signed_statement_returns_eligibility_unmet
    """
    set_clock(api)
    employer = create_employer(api)
    ombudsman = create_certified_ombudsman(api)
    resolve_case_for_employer(api, employer, ombudsman)
    create_statement(api, employer["id"])  # PLEDGED, never signed

    award = nominate_award(api, employer["id"], tier="BRONZE",
                           rationale="Nominated without a signed statement.")
    response = api.transition_award(award["id"], {"to_status": "VETTED"}, coordinator_headers)
    validate_error(response, ApiErrorId.ERR_AWARD_ELIGIBILITY_UNMET)
    assert response.status_code == 409

    awards = validate_success(api.list_employer_awards(employer["id"], coordinator_headers))
    assert len(awards) == 1
    assert awards[0]["status"] == "NOMINATED"
    assert awards[0]["score_base"] is None


def test_unqualified_ombudsman_nominator_rejected(api: ApiClient):
    """PRD §3.9: "An ombudsman nominator must have earned standing with that employer: at least one case assigned to that ombudsman and closed `RESOLVED_INFORMAL` for this employer, failing with `ERR_NOMINATION_NOT_QUALIFIED` otherwise."
    PRD §3.9: "Recognition awards begin with a nomination by an ombudsman or coordinator, carrying the `employer_id`, the nominated `tier` of `BRONZE`, `SILVER`, or `GOLD`, and a `rationale`; the server stamps `nominated_by_id` and `nominated_by_role` from the nominator's headers."

    Design: Corner/rbac/unqualified_ombudsman_nominator_rejected
    """
    set_clock(api)
    employer = create_employer(api)
    ombudsman = create_certified_ombudsman(api)
    resolve_case_for_employer(api, employer, ombudsman)
    other = create_certified_ombudsman(api, full_name="O Two", email="o2@example.com")

    rejected = api.create_award(
        award_payload(employer["id"], tier="BRONZE", rationale="O2 nominates without qualification."),
        make_ombudsman_headers(other["id"]),
    )
    validate_error(rejected, ApiErrorId.ERR_NOMINATION_NOT_QUALIFIED)
    assert rejected.status_code == 409

    accepted = api.create_award(
        award_payload(employer["id"], tier="BRONZE", rationale="O1 nominates after resolving a case."),
        make_ombudsman_headers(ombudsman["id"]),
    )
    award = validate_success(accepted, 201)
    assert_recognition_award(award)
    assert award["status"] == "NOMINATED"
    assert award["nominated_by_id"] == ombudsman["id"]
    assert award["nominated_by_role"] == "Ombudsman"
