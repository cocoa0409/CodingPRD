"""
Figures that sit exactly on, or one representable step away from, a threshold.

Two of the boundaries here are inclusive score floors and one is a rounding
order: the tests are written so that an off-by-one-hundredth implementation
choice changes the observable outcome rather than merely the displayed digits.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ERR_A11Y_CONFORMANCE_INSUFFICIENT
from test_helpers.assertions import (
    assert_conformance_score,
    assert_debt_points,
    assert_decimal_places,
    assert_fields,
    assert_instant_equals,
)
from test_helpers.constants import (
    AUDIT_METHOD_AUTOMATED,
    AUDIT_METHOD_MANUAL,
    DEBT_STATE_CLEAR,
    DEFAULT_CLOCK,
    DEMOTION_REASON_NONE,
    EXCEPTION_RAW_TOKEN_USAGE,
    GRANT_APPROVED,
    IMPL_SHIPPED,
    MATURITY_BETA,
    MATURITY_EXPERIMENTAL,
    PLATFORM_IOS,
    PLATFORM_WEB,
)
from test_helpers.factories import promote_payload
from test_helpers.fixtures import (
    approve_grant,
    file_audit,
    file_clean_evidence,
    governance_base,
    make_implementation,
    promote,
    read_component,
    read_grant,
    read_implementation,
    read_team,
    request_grant,
    ship,
)
from test_helpers.test_users import make_design_system_lead_headers


def _component_sweeping_exactly_seventy(api):
    """
    A shipped component whose governance sweep lands exactly on the BETA floor.

    Each method carries one poor audit worth a defect load of 30 and one later
    clean audit. The engineer's latest-evidence view therefore reads 100.00 while
    the sweep, which keeps the worst audit per method, reads exactly 70.00.
    """
    base = governance_base(
        api,
        team_name="Controls Team",
        team_slug="controls-team",
        component_name="Switch",
        component_slug="switch",
    )
    impl = make_implementation(
        api,
        base["component_id"],
        base["team_id"],
        platform=PLATFORM_WEB,
        package_name="@ds/switch-web",
    )
    first = file_audit(
        api, impl["id"], base["team_id"], serious=7, moderate=2,
        method=AUDIT_METHOD_AUTOMATED,
    )
    assert first["defect_load"] == 30
    assert_conformance_score(
        read_implementation(api, impl["id"]), 63.00
    )
    second = file_audit(
        api, impl["id"], base["team_id"], serious=7, moderate=2,
        method=AUDIT_METHOD_MANUAL,
    )
    assert second["defect_load"] == 30
    assert_conformance_score(read_implementation(api, impl["id"]), 70.00)

    ship(api, impl["id"], base["team_id"])
    file_audit(api, impl["id"], base["team_id"], method=AUDIT_METHOD_AUTOMATED)
    file_audit(api, impl["id"], base["team_id"], method=AUDIT_METHOD_MANUAL)

    base.update({"implementation_id": impl["id"]})
    return base


def test_beta_promotion_is_admitted_when_the_sweep_lands_exactly_on_seventy(api):
    """The score floor is inclusive, so exactly 70.00 promotes.

    PRD: "a `governance_conformance_score` of at least 70.00, inclusive at the boundary, otherwise `ERR_A11Y_CONFORMANCE_INSUFFICIENT`"

    Design: Difficulty/boundary_precision_check/beta_promotion_at_exact_conformance_floor_seventy
    """
    scenario = _component_sweeping_exactly_seventy(api)

    before = read_component(api, scenario["component_id"])
    assert_conformance_score(before, 70.00, "governance_conformance_score")
    assert_conformance_score(
        read_implementation(api, scenario["implementation_id"]), 100.00
    )

    promoted = validate_success(
        api.promote_maturity(
            scenario["component_id"],
            promote_payload(MATURITY_BETA),
            make_design_system_lead_headers(),
        )
    )
    assert promoted["maturity_level"] == MATURITY_BETA


def test_the_promotion_at_the_floor_resets_the_baseline_and_clears_the_reason(api):
    """A successful promotion reopens the evidence window from the current instant.

    PRD: "It sets `maturity_level` to the requested destination, clears `maturity_demotion_reason` back to `NONE`, resets `conformance_baseline_at` to the logical clock, recomputes `governance_conformance_score` against that new window — dropping every audit older than the reset out of the sweep entirely, which typically raises the score in the same request — and increments the component's `version` by 1."

    Design: Difficulty/boundary_precision_check/beta_promotion_at_exact_conformance_floor_seventy
    """
    scenario = _component_sweeping_exactly_seventy(api)

    promoted = promote(api, scenario["component_id"], MATURITY_BETA)
    assert_fields(
        promoted,
        {
            "maturity_level": MATURITY_BETA,
            "maturity_demotion_reason": DEMOTION_REASON_NONE,
        },
        "component",
    )
    assert_instant_equals(
        promoted["conformance_baseline_at"], DEFAULT_CLOCK, "conformance_baseline_at"
    )
    assert_conformance_score(promoted, 70.00, "governance_conformance_score")


def _component_sweeping_just_below_seventy(api):
    """
    A shipped component whose sweep lands one representable step under the floor.

    An automated load of 2 and a manual load of 49 weight to 30.20, which is the
    smallest total that still leaves the score below 70.00.
    """
    base = governance_base(
        api,
        team_name="Inputs Team",
        team_slug="inputs-team",
        component_name="Chip",
        component_slug="chip",
    )
    impl = make_implementation(
        api,
        base["component_id"],
        base["team_id"],
        platform=PLATFORM_WEB,
        package_name="@ds/chip-web",
    )
    file_audit(
        api, impl["id"], base["team_id"], moderate=2, method=AUDIT_METHOD_AUTOMATED
    )
    file_audit(
        api, impl["id"], base["team_id"], serious=12, moderate=1,
        method=AUDIT_METHOD_MANUAL,
    )
    shipped = ship(api, impl["id"], base["team_id"])
    assert_conformance_score(shipped, 69.80)
    base.update({"implementation_id": impl["id"], "baseline_at": base["component"]["conformance_baseline_at"]})
    return base


def test_beta_promotion_is_refused_one_hundredth_class_below_the_floor(api):
    """69.80 is under the floor and the promotion is refused on the score.

    PRD: "Add the two products. Subtract that sum from 100, then subtract a further 25.0 for each missing method."

    An automated load of 2 contributes 0.80 and a manual load of 49 contributes
    29.40, which leaves 69.80 — short of the inclusive 70.00 floor.

    Design: Difficulty/boundary_precision_check/beta_promotion_one_hundredth_class_below_floor_rejected
    """
    scenario = _component_sweeping_just_below_seventy(api)

    component = read_component(api, scenario["component_id"])
    assert_conformance_score(component, 69.80, "governance_conformance_score")
    assert_decimal_places(
        component["governance_conformance_score"], 2, "governance_conformance_score"
    )

    validate_error(
        api.promote_maturity(
            scenario["component_id"],
            promote_payload(MATURITY_BETA),
            make_design_system_lead_headers(),
        ),
        ERR_A11Y_CONFORMANCE_INSUFFICIENT,
        422,
    )


def test_the_refused_promotion_leaves_the_maturity_and_the_baseline_alone(api):
    """Only a successful promotion moves the maturity dimension or the baseline.

    PRD: "When the maturity dimension is demoted from `STABLE` to `BETA` by a provider sunset, `conformance_baseline_at` is **not** reset; only a successful promotion moves the baseline."

    Design: Difficulty/boundary_precision_check/beta_promotion_one_hundredth_class_below_floor_rejected
    """
    scenario = _component_sweeping_just_below_seventy(api)

    validate_error(
        api.promote_maturity(
            scenario["component_id"],
            promote_payload(MATURITY_BETA),
            make_design_system_lead_headers(),
        ),
        ERR_A11Y_CONFORMANCE_INSUFFICIENT,
    )

    component = read_component(api, scenario["component_id"])
    assert_fields(
        component,
        {
            "maturity_level": MATURITY_EXPERIMENTAL,
            "maturity_demotion_reason": DEMOTION_REASON_NONE,
        },
        "component",
    )
    assert_instant_equals(
        component["conformance_baseline_at"], scenario["baseline_at"], "baseline"
    )
    assert_conformance_score(component, 69.80, "governance_conformance_score")
    implementation = read_implementation(api, scenario["implementation_id"])
    assert implementation["status"] == IMPL_SHIPPED
    assert_conformance_score(implementation, 69.80)


def _three_grants_priced_at_four_sixty_nine(api):
    """
    Three identical raw-token grants against a BETA component, each approved.

    Every grant prices at 5 base points times 1.25 for a single mobile platform
    times 0.75 for BETA maturity, which is 4.6875 before rounding.
    """
    base = governance_base(
        api,
        team_name="Rushed Team",
        team_slug="rushed-team",
        component_name="Card",
        component_slug="card",
        team_overrides={"debt_budget_points": 40.00},
    )
    impl = make_implementation(
        api,
        base["component_id"],
        base["team_id"],
        platform=PLATFORM_WEB,
        package_name="@ds/card-web",
    )
    file_clean_evidence(api, impl["id"], base["team_id"])
    ship(api, impl["id"], base["team_id"])
    promoted = promote(api, base["component_id"], MATURITY_BETA)
    assert promoted["maturity_level"] == MATURITY_BETA

    grants = []
    for _ in range(3):
        requested = request_grant(
            api,
            base["team_id"],
            base["component_id"],
            exception_kind=EXCEPTION_RAW_TOKEN_USAGE,
            platform_scope=PLATFORM_IOS,
        )
        grants.append(approve_grant(api, requested["id"]))
    base.update({"grants": grants})
    return base


def test_each_grant_rounds_its_own_product_to_four_sixty_nine(api):
    """Rounding happens once per grant, on the final product.

    PRD: "Rounding happens once, on the final product, and never on the intermediate multiplications."

    Five base points times 1.25 times 0.75 is 4.6875, which rounds half up to 4.69.

    Design: Difficulty/boundary_precision_check/exception_debt_round_then_sum_yields_14_07_not_14_06
    """
    scenario = _three_grants_priced_at_four_sixty_nine(api)

    for grant in scenario["grants"]:
        assert_fields(
            grant,
            {"state": GRANT_APPROVED, "pinned_maturity_level": MATURITY_BETA},
            "grant",
        )
        assert_debt_points(grant, 4.69)
        assert_decimal_places(grant["debt_points"], 2, "debt_points")
        assert_debt_points(read_grant(api, grant["id"]), 4.69)


def test_the_ledger_sums_the_rounded_points_to_fourteen_oh_seven(api):
    """The outstanding total is the sum of rounded points, not a rounded sum.

    PRD: "A team's `outstanding_debt_points` is the sum of `debt_points` across that team's grants in `APPROVED` or `EXPIRED`, rounded half up to two decimal places."

    Three grants of 4.69 total 14.07; summing the unrounded 4.6875 figures first
    would have produced 14.06 instead.

    Design: Difficulty/boundary_precision_check/exception_debt_round_then_sum_yields_14_07_not_14_06
    """
    scenario = _three_grants_priced_at_four_sixty_nine(api)

    team = read_team(api, scenario["team_id"])
    assert_debt_points(team, 14.07, "outstanding_debt_points")
    assert_debt_points(team, 14.07, "lifetime_debt_points")
    assert round(float(team["outstanding_debt_points"]), 2) != 14.06, (
        "the ledger must sum the per-grant rounded figures, not round the raw sum"
    )
    assert team["debt_state"] == DEBT_STATE_CLEAR
    assert read_component(api, scenario["component_id"])["one_off_exception_count"] == 3
