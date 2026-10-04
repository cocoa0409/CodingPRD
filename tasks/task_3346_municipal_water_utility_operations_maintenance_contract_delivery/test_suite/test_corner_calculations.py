"""Corner-queue tests for the pinned calculation results."""
import pytest

from test_helpers import (
    api_client,
    award_contract,
    create_standard,
    get_success_data,
    measurement_payload,
    read_contract,
    read_municipality_benchmark,
    register_municipality,
    setup_operating_contract,
    validate_success,
)


def test_measurement_at_the_exact_deviation_ratio_lands_in_the_major_band(api):
    """PRD §3.4: "A ratio of at least 0.50 yields a severity band of 1.00; at least 0.25 but below 0.50 yields 0.60; at least 0.10 but below 0.25 yields 0.30; below 0.10 yields 0.10."
    PRD §3.4: "As a worked illustration, a standard weighted 0.50 with a threshold of 10.0: a measured value of 12.5 gives a ratio of exactly 0.25, falling in the 0.60 band, for a weighted score of exactly 0.3000"
    PRD §3.4: "Assessment is the operator's act and requires the measurement to be in `RECORDED`; it recomputes `in_breach` from the owning standard's direction, sets `weighted_breach_score` by the breach severity rules below, and moves the row to `ASSESSED`."

    Design: Corner/calculations/breach_score_severity_band_at_exact_deviation_ratio
    """
    scenario = setup_operating_contract()
    measurement = validate_success(
        api_client.record_measurement(
            scenario.std["id"], measurement_payload(measured_value=12.5), scenario.con_h
        ),
        201,
    )

    assessed = validate_success(
        api_client.assess_measurement(measurement["id"], scenario.con_h)
    )

    assert assessed["in_breach"] is True, "12.5 exceeds an AT_MOST threshold of 10.0"
    assert assessed["weighted_breach_score"] == pytest.approx(0.3, abs=1e-9), (
        "a ratio of exactly 0.25 selects the 0.60 band, weighted by 0.50"
    )
    assert assessed["status"] == "ASSESSED"

    standard = get_success_data(api_client.get_standard(scenario.std["id"], scenario.con_h))
    assert standard["status"] == "ACTIVE", (
        "a weighted score below 0.60 does not drag the standard into BREACHED"
    )


def test_staffing_floor_adds_the_base_surcharge_band_before_rounding(api):
    """PRD §3.1: "The base value is one half multiplied by the count of active standards, plus one quarter multiplied by the sum of their `criticality_weight` values, the whole rounded half-up to two decimal places."
    PRD §3.1: "A surcharge is then added: 3.00 FTE when that base value is at least 6.00, 2.00 FTE when it is at least 3.50 but below 6.00, 1.00 FTE when it is at least 1.50 but below 3.50, and 0.00 FTE below 1.50."
    PRD §3.1: "The evaluation order is pinned: the base value is computed first, the surcharge band is selected from that base value alone, and only then is the surcharge added."

    Design: Corner/calculations/staffing_floor_base_fte_and_surcharge_band
    """
    municipality, municipality_headers = register_municipality()
    contract, contract_headers = award_contract(municipality, municipality_headers)

    standards = [
        create_standard(
            contract["id"],
            contract_headers,
            activate=False,
            code=f"STD-{index}",
            title=f"Standard {index}",
            metric_type="TREATMENT_EFFLUENT",
            criticality_weight=1.0,
            threshold_value=10.0,
            threshold_direction="AT_MOST",
            breach_penalty_cents=100000,
        )
        for index in range(1, 5)
    ]
    for standard in standards[:3]:
        validate_success(
            api_client.activate_standard(contract["id"], standard["id"], contract_headers)
        )

    # Three active standards at weight 1.0: base 2.25, band 1.00, floor 3.25.
    partial = read_contract(contract["id"], contract_headers)
    assert partial["staffing_floor_fte"] == pytest.approx(3.25, abs=0.01)

    fourth = validate_success(
        api_client.activate_standard(contract["id"], standards[3]["id"], contract_headers)
    )
    assert fourth["status"] == "ACTIVE"

    # Four active standards at weight 1.0: base 3.00, band 1.00, floor 4.00.
    complete = read_contract(contract["id"], contract_headers)
    assert complete["staffing_floor_fte"] == pytest.approx(4.0, abs=0.01), (
        "the surcharge band is selected from the base value of 3.00, giving a floor of 4.00"
    )


def test_benchmark_index_is_the_mean_cost_per_million_gallons_over_live_contracts(api):
    """PRD §3.8: "It is the mean cost per million gallons over the municipality's contracts that are in a live status — `OPERATING`, `UNDER_REVIEW` or `RENEWED` — rounded half-up to four decimal places, and it is exactly 0.0 when that set is empty."
    PRD §3.8: "The cost per million gallons for one contract is its `annual_fee_cents` divided by its annual million gallons, where the daily flow is the municipality's `population_served` multiplied by 0.00011 million gallons per capita and the annual figure is that daily flow multiplied by 365."

    Design: Corner/calculations/benchmark_index_forward_looking_mean_over_live_contracts
    """
    scenario = setup_operating_contract()
    assert scenario.con["status"] == "OPERATING"

    # 40000000 / (250000 * 0.00011 * 365) = 3985.0559...
    index = read_municipality_benchmark(scenario.mun["id"], scenario.mun_h)

    assert index == pytest.approx(3985.056, abs=0.001), (
        "the index averages the cost per million gallons of the live contracts"
    )
