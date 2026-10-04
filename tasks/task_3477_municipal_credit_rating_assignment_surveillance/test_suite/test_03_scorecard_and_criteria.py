"""Analytical scorecard computation and criteria-version governance.

Covers the weighted score, the inclusive anchor table, the ENTERPRISE
weak-link cap variant, scorecard OCC, the factor-score and weight-sum
bounds, the active-criteria precondition, and criteria activation state
rules (PRD sections 2.6, 2.10, 3.2 and 3.6).
"""

from test_helpers import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    OFFICER_HEADERS,
    ApiErrorId,
    BB_SCORES,
    PERFECT_SCORES,
    WEAK_LINK_SCORES,
    assert_weighted_score,
    create_issuer,
    criteria_version_payload,
    get_engagement,
    make_issuer_headers,
    scorecard_payload,
    setup_active_criteria,
    setup_committee_ready_engagement,
    setup_engagement_in_analysis,
    submit_scorecard,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_scorecard_weighted_score_and_indicative_notch_server_computed(api):
    """PRD section 3.2: "a rounded score of at least 4.50 anchors at `AAA`;
    at least 4.00 anchors at `AA`; at least 3.50 anchors at `A`; at least 3.00
    anchors at `BBB`; at least 2.50 anchors at `BB`; at least 2.00 anchors at
    `B`; and anything below 2.00 anchors at `CCC`."
    PRD section 3.2: "For `GENERAL_OBLIGATION` and `REVENUE` engagements, the
    indicative rating the committee will see is simply the anchor:
    `indicative_notch` equals `anchor_notch` and `capped` is false."
    PRD section 3.2: "The server first finds the `ACTIVE` criteria version for
    the engagement's segment and pins its identity into the scorecard's
    `criteria_version_id`".

    Design: Corner/entities/scorecard_weighted_score_and_indicative_notch_server_computed
    """
    ctx = setup_committee_ready_engagement(api, scores=PERFECT_SCORES)
    scorecard = ctx["scorecard"]
    assert_weighted_score(scorecard, "5.0")
    assert scorecard["anchor_notch"] == "AAA"
    assert scorecard["capped"] is False
    assert scorecard["indicative_notch"] == "AAA"
    assert scorecard["criteria_version_id"] == ctx["criteria_version"]["id"]
    assert ctx["engagement"]["status"] == "COMMITTEE_READY"
    assert ctx["engagement"]["assigned_analyst_id"] == "analyst-1", (
        "the submitting analyst is recorded as the segregation-of-duties anchor"
    )


def test_scorecard_weak_link_cap_divergence(api):
    """PRD section 3.2: "For `GENERAL_OBLIGATION` and `REVENUE` engagements,
    the indicative rating the committee will see is simply the anchor:
    `indicative_notch` equals `anchor_notch` and `capped` is false."
    PRD section 3.2: "Enterprise credits carry a **weak-link cap**: when the
    engagement's `credit_type` is `ENTERPRISE` and the lowest of the six factor
    scores is exactly 1, the indicative rating becomes the worse of
    `anchor_notch` and `BB`, and `capped` is set true; when no factor scores a
    1, an enterprise scorecard behaves like the standard variant".

    Design: Difficulty/dual_variant_calc/scorecard_weak_link_cap_divergence
    """
    ctx_go = setup_committee_ready_engagement(api, scores=WEAK_LINK_SCORES)
    ctx_ent = setup_committee_ready_engagement(
        api,
        credit_type="ENTERPRISE",
        scores=WEAK_LINK_SCORES,
        criteria_overrides={
            "version_label": "ENT-2026.1",
            "w_economy": 0.10,
            "w_management": 0.25,
            "w_budgetary_performance": 0.20,
            "w_flexibility": 0.10,
            "w_liquidity": 0.15,
            "w_debt_profile": 0.20,
        },
    )
    sc_go = ctx_go["scorecard"]
    sc_ent = ctx_ent["scorecard"]

    # GO weights 0.20/0.20/0.20/0.15/0.10/0.15 over (5,5,5,5,5,1) -> 4.4000.
    assert_weighted_score(sc_go, "4.40")
    assert sc_go["anchor_notch"] == "AA"
    assert sc_go["capped"] is False
    assert sc_go["indicative_notch"] == "AA"

    # ENT weights 0.10/0.25/0.20/0.10/0.15/0.20 over (5,5,5,5,5,1) -> 4.2000;
    # the minimum factor score is exactly 1, so the weak-link cap fires.
    assert_weighted_score(sc_ent, "4.20")
    assert sc_ent["anchor_notch"] == "AA"
    assert sc_ent["capped"] is True
    assert sc_ent["indicative_notch"] == "BB", (
        "the same six scores diverge across the two calculation variants"
    )


def test_anchor_boundary_3_5000_inclusive_maps_A(api):
    """PRD section 3.2: "From the rounded `weighted_score`, the anchor table
    fixes `anchor_notch` using inclusive lower bounds: a rounded score of at
    least 4.50 anchors at `AAA`; ... at least 3.50 anchors at `A`; at least
    3.00 anchors at `BBB`".
    PRD section 3.2: "The comparison always runs against the four-decimal
    rounded value, never against the raw sum."

    Design: Difficulty/boundary_precision_check/anchor_boundary_3_5000_inclusive_maps_A
    """
    base = setup_engagement_in_analysis(api)
    setup_active_criteria(api)
    engagement = base["engagement"]

    # Default GO weights over (4,4,3,4,4,2) land exactly on 3.5000.
    first = submit_scorecard(api, engagement)
    assert_weighted_score(first, "3.5000")
    assert first["anchor_notch"] == "A", "the 3.50 threshold is inclusive"

    # Supersede with (4,4,3,4,3,2): 3.4000 falls below the boundary.
    second = submit_scorecard(api, engagement, scores={"score_liquidity": 3})
    assert_weighted_score(second, "3.4000")
    assert second["anchor_notch"] == "BBB"


def test_anchor_inclusive_boundaries_map_bbb_and_bb(api):
    """PRD section 3.2: "at least 3.00 anchors at `BBB`; at least 2.50 anchors
    at `BB`" — inclusive lower bounds applied to the four-decimal rounded
    `weighted_score`.

    Design: Corner/calculations/anchor_inclusive_boundaries_map_bbb_and_bb
    """
    base = setup_engagement_in_analysis(api)
    setup_active_criteria(api)
    engagement = base["engagement"]

    all_threes = {
        "score_economy": 3,
        "score_management": 3,
        "score_budgetary_performance": 3,
        "score_flexibility": 3,
        "score_liquidity": 3,
        "score_debt_profile": 3,
    }
    first = submit_scorecard(api, engagement, scores=all_threes)
    assert_weighted_score(first, "3.0")
    assert first["anchor_notch"] == "BBB", "exactly 3.0000 anchors at BBB"

    second = submit_scorecard(api, engagement, scores=BB_SCORES)
    assert_weighted_score(second, "2.85")
    assert second["anchor_notch"] == "BB"


def test_occ_stale_engagement_version_on_scorecard_rejected(api):
    """PRD section 2.6: "If the engagement's current `version` has moved past
    that value — because another scorecard landed, a document was accepted, or
    terms were accepted in between — the submission is rejected with
    `ERR_STALE_ENGAGEMENT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_engagement_version_on_scorecard_rejected
    """
    base = setup_engagement_in_analysis(api)
    setup_active_criteria(api)
    engagement = base["engagement"]
    observed_version = engagement["version"]

    first = api.submit_scorecard(
        engagement["id"],
        scorecard_payload(observed_version),
        headers=ANALYST_HEADERS,
    )
    validate_success(first, 200)

    replay = api.submit_scorecard(
        engagement["id"],
        scorecard_payload(observed_version, **PERFECT_SCORES),
        headers=ANALYST_HEADERS,
    )
    validate_error(replay, ApiErrorId.ERR_STALE_ENGAGEMENT_VERSION)

    data = validate_success(
        api.get_engagement_scorecard(engagement["id"], headers=ANALYST_HEADERS), 200
    )
    assert isinstance(data, list) and len(data) == 1, (
        "the scorecard read-back is an array of zero or one"
    )
    assert data[0]["indicative_notch"] == "A", (
        "the superseding all-5s submission never landed; the first scorecard stands"
    )


def test_factor_score_out_of_range_rejected(api):
    """PRD section 3.2: "six integer factor scores ... each an integer from 1
    to 5 inclusive, with anything outside that range rejected as
    `ERR_FACTOR_SCORE_OUT_OF_RANGE`."

    Design: Corner/validations/factor_score_out_of_range_rejected
    """
    base = setup_engagement_in_analysis(api)
    setup_active_criteria(api)
    engagement = base["engagement"]
    resp = api.submit_scorecard(
        engagement["id"],
        scorecard_payload(engagement["version"], score_economy=6),
        headers=ANALYST_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_FACTOR_SCORE_OUT_OF_RANGE)
    data = validate_success(
        api.get_engagement_scorecard(engagement["id"], headers=ANALYST_HEADERS), 200
    )
    assert data == [], "no scorecard is persisted by a rejected submission"


def test_scorecard_without_active_criteria_rejected(api):
    """PRD section 3.2: "Scoring also requires an `ACTIVE` criteria version
    for the engagement's `jurisdiction_code` and `credit_type`; when none
    exists the submission fails with `ERR_NO_ACTIVE_CRITERIA`."

    Design: Corner/errors/scorecard_without_active_criteria_rejected
    """
    issuer = create_issuer(api, legal_name="County of Example")
    base = setup_engagement_in_analysis(
        api, issuer=issuer, jurisdiction_code="US-NV"
    )
    setup_active_criteria(api)  # US-CA only; nothing covers US-NV
    engagement = base["engagement"]
    resp = api.submit_scorecard(
        engagement["id"],
        scorecard_payload(engagement["version"]),
        headers=ANALYST_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_CRITERIA)
    assert get_engagement(api, engagement["id"])["status"] == "ANALYSIS"


def test_weight_sum_not_one_rejected(api):
    """PRD section 3.6: "the six factor weights `w_economy`, `w_management`,
    `w_budgetary_performance`, `w_flexibility`, `w_liquidity`, and
    `w_debt_profile`, which must sum to exactly 1.000 — any other total is
    rejected with `ERR_WEIGHT_SUM_INVALID`."

    Design: Corner/validations/weight_sum_not_one_rejected
    """
    resp = api.create_criteria_version(
        criteria_version_payload(w_economy=0.19, version_label="GO-BAD"),
        headers=OFFICER_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_WEIGHT_SUM_INVALID)
    data, meta = validate_paginated(
        api.list_criteria_versions(
            headers=ADMIN_HEADERS, params={"jurisdiction_code": "US-CA"}
        )
    )
    assert data == [] and meta["total_count"] == 0, (
        "a rejected criteria version is not persisted even as DRAFT"
    )


def test_criteria_create_by_issuer_role_unauthorized(api):
    """PRD section 2.1: "Each endpoint admits a fixed set of roles; a caller
    whose role is not admitted is rejected with `ERR_UNAUTHORIZED_ROLE`
    (HTTP 403)."
    PRD section 3.6: "A `SurveillanceOfficer` drafts one with a
    `jurisdiction_code`, a `credit_type`, a human-readable `version_label`
    such as GO-2026.2, and the six factor weights".

    Design: Corner/validations/criteria_create_by_issuer_role_unauthorized
    """
    issuer = create_issuer(api)
    resp = api.create_criteria_version(
        criteria_version_payload(version_label="GO-2026.9"),
        headers=make_issuer_headers(issuer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_criteria_activate_twice_rejected(api):
    """PRD section 3.6: "Activation, again a `SurveillanceOfficer` act, moves
    a version `DRAFT` → `ACTIVE`, stamps `activated_at` from the clock, and
    increments the version's own `version`; activating anything not `DRAFT`
    fails with `ERR_CRITERIA_VERSION_STATE_INVALID`."

    Design: Corner/state_machines/criteria_activate_twice_rejected
    """
    criteria = setup_active_criteria(api)
    resp = api.activate_criteria_version(criteria["id"], headers=OFFICER_HEADERS)
    validate_error(resp, ApiErrorId.ERR_CRITERIA_VERSION_STATE_INVALID)
    current = validate_success(
        api.get_criteria_version(criteria["id"], headers=OFFICER_HEADERS), 200
    )
    assert current["status"] == "ACTIVE"
    items, meta = validate_paginated(
        api.list_review_items(
            headers=OFFICER_HEADERS, params={"criteria_version_id": criteria["id"]}
        )
    )
    assert items == [], "the rejected re-activation fans out no review items"
