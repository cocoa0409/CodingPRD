"""The COD cascade: combinatorial ITC rate and the availability boundary."""
import pytest

from test_helpers import (
    ApiErrorId,
    build_cod_project,
    certify_four_prerequisite_milestones,
    get_success_data,
    transition_project,
    validate_error,
)


def test_itc_rate_combinatorial_adders_mode_a(
    api, developer_admin_headers, tax_counsel_headers
):
    """PRD §3.5: "The rate starts at a 30.00 percent base. A 10.00 percent
    domestic content adder applies when the project's
    `domestic_content_certified` flag is true and at least one supply agreement
    of the project has its own `domestic_content_certified` true while in
    `EXECUTED`, `AMENDMENT_PENDING`, `DELIVERING`, or `FULFILLED` status. A
    further 10.00 percent energy community adder applies when the project's
    `energy_community_eligible` flag is true. The resulting rate is stored as
    `credit_rate_pct`. ... The `qualified_credit_usd` is the rate divided by
    100 and multiplied by that basis, rounded half-up to 2 decimal places, and
    the project's `total_itc_credits_usd` is set to the same figure."
    PRD §3.6: "A tax credit qualification sitting in `CONTINUITY_MAINTAINED` or
    `CURED` auto-transitions to `QUALIFIED`, recomputing `credit_rate_pct` and
    `qualified_credit_usd` per the credit computation of §3.5 and updating the
    project's `total_itc_credits_usd`."

    Design: Difficulty/combinatorial_formula/itc_rate_combinatorial_adders_mode_a
    """
    result = build_cod_project(
        "Adder Farm", "CL-A", 200,
        project_overrides={"energy_community_eligible": True,
                           "domestic_content_certified": True},
        order_overrides={"order_amount_usd": 10000000,
                         "safe_harbor_method": "FIVE_PERCENT_COST",
                         "eligible_cost_basis_usd": 10000000,
                         "deposit_usd": 500000.00,
                         "supplier_domestic_content": True},
    )
    tcq = result["tcq"]
    project = result["project"]
    # All three branches engaged: 30.00 + 10.00 + 10.00 = 50.00%.
    assert tcq["status"] == "QUALIFIED"
    assert tcq["credit_rate_pct"] == pytest.approx(50.00, abs=0.001)
    assert tcq["qualified_credit_usd"] == pytest.approx(5000000.00, abs=0.001)
    assert project["total_itc_credits_usd"] == pytest.approx(5000000.00, abs=0.001)
    assert project["status"] == "COMMERCIAL_OPERATION"


def test_itc_rate_base_only_when_no_adders(
    api, developer_admin_headers, tax_counsel_headers
):
    """PRD §3.5: "The rate starts at a 30.00 percent base. A 10.00 percent
    domestic content adder applies when the project's
    `domestic_content_certified` flag is true and at least one supply agreement
    of the project has its own `domestic_content_certified` true while in
    `EXECUTED`, `AMENDMENT_PENDING`, `DELIVERING`, or `FULFILLED` status. A
    further 10.00 percent energy community adder applies when the project's
    `energy_community_eligible` flag is true."

    Design: Difficulty/combinatorial_formula/itc_rate_combinatorial_adders_mode_a
    """
    result = build_cod_project(
        "Base Rate Farm", "CL-BASE", 120,
        order_overrides={"order_amount_usd": 10000000,
                         "safe_harbor_method": "FIVE_PERCENT_COST",
                         "eligible_cost_basis_usd": 10000000,
                         "deposit_usd": 500000.00},
    )
    tcq = result["tcq"]
    # Neither flag set: base rate only, 30% of the 10,000,000.00 basis.
    assert tcq["credit_rate_pct"] == pytest.approx(30.00, abs=0.001)
    assert tcq["qualified_credit_usd"] == pytest.approx(3000000.00, abs=0.001)
    assert result["project"]["total_itc_credits_usd"] == pytest.approx(3000000.00, abs=0.001)


def test_availability_exactly_at_guarantee_zero_ld(
    api, developer_admin_headers
):
    """PRD §3.6: "When the shortfall is zero or negative — including a measured
    availability exactly equal to the guarantee — the `availability_ld_usd` is
    0.00. Otherwise the damages are the shortfall multiplied by 25,000 dollars
    per percentage point, rounded half-up to 2 decimal places, capped at
    500,000.00 dollars."
    PRD §3.6: "Abandonment is available from any status other than
    `OPERATIONAL` (an attempt from `OPERATIONAL` fails with
    `ERR_INVALID_STATE`)".

    Design: Difficulty/boundary_precision_check/availability_exactly_at_guarantee_zero_ld
    """
    result = build_cod_project("Avail Farm X", "CL-AX", 120)
    pid = result["project"]["id"]
    done = transition_project(pid, "OPERATIONAL", measured_availability_pct=97.00)
    assert done["status"] == "OPERATIONAL"
    assert done["availability_ld_usd"] == pytest.approx(0.00, abs=0.001)
    # OPERATIONAL is terminal for further OPERATIONAL transitions.
    resp = api.transition_project(
        pid, {"to": "OPERATIONAL", "measured_availability_pct": 96.99},
        developer_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_availability_one_hundredth_below_guarantee(
    api, developer_admin_headers
):
    """PRD §3.6: "Otherwise the damages are the shortfall multiplied by 25,000
    dollars per percentage point, rounded half-up to 2 decimal places, capped
    at 500,000.00 dollars."

    Design: Difficulty/boundary_precision_check/availability_exactly_at_guarantee_zero_ld
    """
    result = build_cod_project("Avail Farm Y", "CL-AY", 120)
    pid = result["project"]["id"]
    # Guarantee 97.0 (default), measured 96.99: shortfall 0.01 -> LD 250.00.
    done = transition_project(pid, "OPERATIONAL", measured_availability_pct=96.99)
    assert done["status"] == "OPERATIONAL"
    assert done["availability_ld_usd"] == pytest.approx(250.00, abs=0.001)


def test_availability_ld_capped(
    api, developer_admin_headers
):
    """PRD §3.6: "Otherwise the damages are the shortfall multiplied by 25,000
    dollars per percentage point, rounded half-up to 2 decimal places, capped
    at 500,000.00 dollars."

    Design: Difficulty/boundary_precision_check/availability_exactly_at_guarantee_zero_ld
    """
    result = build_cod_project("Avail Farm Z", "CL-AZ", 120)
    pid = result["project"]["id"]
    # Shortfall 97.0 - 60.0 = 37.0 -> 925,000 raw, capped at 500,000.00.
    done = transition_project(pid, "OPERATIONAL", measured_availability_pct=60.0)
    assert done["availability_ld_usd"] == pytest.approx(500000.00, abs=0.001)
