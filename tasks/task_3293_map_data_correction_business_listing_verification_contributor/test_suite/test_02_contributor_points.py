"""Contributor points, levels, and rounding-order tests."""
from test_helpers import (
    TEST_USERS,
    api_client,
    create_contributor_grant_payload,
    make_contributor,
    make_region,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _grant(api, contributor_id, source_id, base_points, note, multiplier=None):
    payload = create_contributor_grant_payload(
        contributor_id=contributor_id, source_id=source_id,
        base_points=base_points, note=note,
    )
    if multiplier is not None:
        payload["quality_multiplier"] = multiplier
    resp = api.create_contributor_grant(payload, ADMIN)
    return validate_success(resp, expected_status=201)


def test_points_award_per_contribution_rounding(api):
    """PRD §2.7: "Point awards are whole integers, with per-contribution
    rounding applied before any summation — the rule that rounds each grant's
    `points` first and only then totals them is pinned, and the alternative
    order (sum raw products, round once at the end) is expressly forbidden
    because the two orders disagree on half-point products."
    PRD §3.1: "Level thresholds are pinned: below 50 points the contributor is
    `NEWCOMER`; at least 50 but below 250, `REGULAR`; at least 250 but below
    1000, `TRUSTED`; at least 1000 but below 5000, `EXPERT`; and at 5000 or
    more, `MASTER`."

    Design: Difficulty/combinatorial_formula/points_award_mode_b_per_contribution_rounding
    """
    region = make_region(name="R4")
    contributor = make_contributor(region["id"], display_name="C5", email="c5@x.com")
    _grant(api, contributor["id"], "g-half-1", 1, "half grant 1", multiplier=0.5)
    _grant(api, contributor["id"], "g-half-2", 1, "half grant 2", multiplier=0.5)

    resp = api.get_contributor(contributor["id"], ADMIN)
    data = validate_success(resp)
    assert data["total_points"] == 2, (
        f"per-contribution rounding pins round(1*0.5)=1 twice -> total 2, "
        f"got {data['total_points']}"
    )
    assert data["lifetime_points"] == 2
    assert data["level"] == "NEWCOMER", f"2 < 50 must be NEWCOMER, got {data['level']}"


def test_points_award_half_points_sum_not_rounded_once(api):
    """PRD §2.7: "Point awards are whole integers, with per-contribution
    rounding applied before any summation — the rule that rounds each grant's
    `points` first and only then totals them is pinned, and the alternative
    order (sum raw products, round once at the end) is expressly forbidden
    because the two orders disagree on half-point products."
    PRD §3.1: "The grant's awarded `points` equal the product of `base_points`
    and `quality_multiplier` rounded half-up to a whole integer — computed per
    grant, before any summation."

    Design: Difficulty/combinatorial_formula/points_award_mode_b_per_contribution_rounding
    """
    region = make_region(name="R4b")
    contributor = make_contributor(region["id"], display_name="C5b", email="c5b@x.com")
    g1 = _grant(api, contributor["id"], "h1", 1, "half 1", multiplier=0.5)
    g2 = _grant(api, contributor["id"], "h2", 3, "half 2", multiplier=0.5)
    assert g1["points"] == 1, f"round_half_up(0.5) == 1, got {g1['points']}"
    assert g2["points"] == 2, f"round_half_up(1.5) == 2, got {g2['points']}"

    resp = api.get_contributor(contributor["id"], ADMIN)
    data = validate_success(resp)
    # Pinned order: 1 + 2 = 3. Forbidden sum-then-round would give
    # round_half_up(0.5 + 1.5) = 2.
    assert data["total_points"] == 3, (
        f"per-contribution rounding yields 1+2=3, got {data['total_points']}"
    )
    assert data["lifetime_points"] == 3


def test_contributor_level_exactly_250_is_trusted(api):
    """PRD §3.1: "Level thresholds are pinned: below 50 points the contributor
    is `NEWCOMER`; at least 50 but below 250, `REGULAR`; at least 250 but
    below 1000, `TRUSTED`; at least 1000 but below 5000, `EXPERT`; and at 5000
    or more, `MASTER`."

    Design: Difficulty/boundary_precision_check/contributor_level_exactly_250_is_trusted_empty_resolve_noop
    """
    region = make_region(name="R12")
    contributor = make_contributor(region["id"], display_name="C14", email="c14@x.com")
    _grant(api, contributor["id"], "seed-249", 249, "seed 249")

    resp = api.get_contributor(contributor["id"], ADMIN)
    at_249 = validate_success(resp)
    assert at_249["total_points"] == 249
    assert at_249["level"] == "REGULAR", (
        f"249 points must be REGULAR, got {at_249['level']}"
    )

    _grant(api, contributor["id"], "plus-1", 1, "cross to 250")
    resp = api.get_contributor(contributor["id"], ADMIN)
    at_250 = validate_success(resp)
    assert at_250["total_points"] == 250
    assert at_250["level"] == "TRUSTED", (
        f"exactly 250 points must be TRUSTED, got {at_250['level']}"
    )


def test_contributor_level_boundary_249_regular(api):
    """PRD §3.1: "Level thresholds are pinned: below 50 points the contributor
    is `NEWCOMER`; at least 50 but below 250, `REGULAR`; at least 250 but
    below 1000, `TRUSTED`; at least 1000 but below 5000, `EXPERT`; and at 5000
    or more, `MASTER`."

    Design: Difficulty/boundary_precision_check/contributor_level_exactly_250_is_trusted_empty_resolve_noop
    """
    region = make_region(name="R12b")
    contributor = make_contributor(region["id"], display_name="C14b",
                                   email="c14b@x.com", seed_points=249)
    assert contributor["total_points"] == 249
    assert contributor["level"] == "REGULAR", (
        f"249 is strictly below 250 -> REGULAR, got {contributor['level']}"
    )
