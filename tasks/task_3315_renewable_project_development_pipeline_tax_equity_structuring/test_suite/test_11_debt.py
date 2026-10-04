"""Debt facilities: the draw commitment cap and the cascade-only conversion
state."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_debt_facility_payload,
    create_project,
    get_success_data,
    validate_error,
    validate_success,
)


def test_draw_exceeds_commitment(
    api, developer_admin_headers, lender_agent_headers
):
    """PRD §3.8: "Each draw requires a `draw_amount_usd` that is present and
    greater than zero, and the draw must keep the running total within
    commitment — the existing `drawn_usd` plus the new `draw_amount_usd` must
    not exceed `commitment_usd`, failing with `ERR_DRAW_EXCEEDS_COMMITMENT`
    (HTTP 422) otherwise. Each accepted draw adds its amount into `drawn_usd`."

    Design: Corner/errors/draw_exceeds_commitment
    """
    project = create_project(name="Draw Farm", target_capacity_mw=110)
    facility = validate_success(
        api.create_debt_facility(
            project["id"],
            create_debt_facility_payload(commitment_usd=10000000,
                                         interest_rate_pct=5.0,
                                         projected_cfads_usd=800000),
            lender_agent_headers,
        ),
        expected_status=201,
    )
    drawn = get_success_data(
        api.transition_debt_facility(
            facility["id"],
            {"to": "CONSTRUCTION_DRAWING", "draw_amount_usd": 6000000},
            lender_agent_headers,
        )
    )
    assert drawn["drawn_usd"] == pytest.approx(6000000.00, abs=0.001)
    resp = api.transition_debt_facility(
        facility["id"],
        {"to": "CONSTRUCTION_DRAWING", "draw_amount_usd": 5000000},
        lender_agent_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DRAW_EXCEEDS_COMMITMENT)
    current = get_success_data(
        api.get_debt_facility(facility["id"], lender_agent_headers)
    )
    assert current["drawn_usd"] == pytest.approx(6000000.00, abs=0.001)


def test_dscr_exactly_at_minimum_converts(
    api, developer_admin_headers, lender_agent_headers
):
    """PRD §3.6: "A debt facility sitting in `CONSTRUCTION_DRAWING`
    auto-transitions to `CONVERSION_PENDING`." (system cascade at COD)
    PRD §3.8: "Conversion to term repayment is gated on debt service coverage
    and on sizing." — the conversion step is the
    `CONVERSION_PENDING` -> `TERM_REPAYMENT` transition.

    Design: Corner/calculations/dscr_exactly_at_minimum_converts
    """
    projects = []
    facilities = []
    for name, cap in (("DSCR Farm X", 100), ("DSCR Farm Y", 100)):
        projects.append(create_project(name=name, target_capacity_mw=cap))
    facilities.append(validate_success(
        api.create_debt_facility(
            projects[0]["id"],
            create_debt_facility_payload(commitment_usd=10000000,
                                         interest_rate_pct=5.0,
                                         projected_cfads_usd=520000.00),
            lender_agent_headers,
        ),
        expected_status=201,
    ))
    facilities.append(validate_success(
        api.create_debt_facility(
            projects[1]["id"],
            create_debt_facility_payload(commitment_usd=10000000,
                                         interest_rate_pct=5.0,
                                         projected_cfads_usd=519999.99),
            lender_agent_headers,
        ),
        expected_status=201,
    ))
    for f in facilities:
        get_success_data(
            api.transition_debt_facility(
                f["id"],
                {"to": "CONSTRUCTION_DRAWING", "draw_amount_usd": 8000000},
                lender_agent_headers,
            )
        )
    # CONVERSION_PENDING is cascade-only at COD: the direct transition is
    # refused regardless of DSCR arithmetic.
    for f in facilities:
        resp = api.transition_debt_facility(
            f["id"], {"to": "CONVERSION_PENDING"}, lender_agent_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    # Neither facility left CONSTRUCTION_DRAWING; a TERM_REPAYMENT attempt is
    # equally a from-state violation.
    for f in facilities:
        resp = api.transition_debt_facility(
            f["id"], {"to": "TERM_REPAYMENT"}, lender_agent_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        current = get_success_data(
            api.get_debt_facility(f["id"], lender_agent_headers)
        )
        assert current["status"] == "CONSTRUCTION_DRAWING"
