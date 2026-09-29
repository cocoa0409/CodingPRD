"""What a cooperative model score does to a rented list's expected response.

Four lists are modeled at 399, 400, 600 and 800 — the three band edges plus the
one value that falls below the lowest of them. The 399 case is the one that
separates a lift table from a quality bonus: a list the coops cannot model well
must respond *below* the season's own prospect base, not merely at it.
"""
from test_helpers import (
    BROKER,
    CLOCK_START,
    assert_prospect_list_rental,
    create_rental_payload,
    model_rental_payload,
    new_season,
    set_clock,
    validate_success,
)

LIST_TERMS = {
    "requested_gross_names": 10000,
    "cost_per_thousand_cents": 8500,
    "housefile_overlap_bps": 1000,
    "inter_list_overlap_bps": 0,
}

SCORES = {"L399": 399, "L400": 400, "L600": 600, "L800": 800}


def _four_lists_modeled_at_the_band_edges(api) -> dict:
    """One season on the default rate card holding four otherwise identical
    rentals, each modeled at a different cooperative score."""
    set_clock(CLOCK_START)
    season = new_season(season_code="FW26", fiscal_year=2026)

    modeled = {}
    for name, score in SCORES.items():
        rental = validate_success(
            api.create_rental(
                create_rental_payload(
                    season["id"], list_source_name=name, **LIST_TERMS
                ),
                BROKER,
            ),
            201,
        )
        modeled[name] = validate_success(
            api.model_rental(rental["id"], model_rental_payload(score), BROKER), 200
        )
    return modeled


class TestCooperativeModelLiftBands:
    def test_the_lowest_band_cuts_the_base_rate_while_the_others_lift_it(self, api):
        """PRD §3.2: "A score of 800 or above earns a lift of positive 4000 basis
        points; 600 or above earns positive 2000; 400 or above earns no lift at all;
        and anything below 400 earns a lift of *negative* 3000 basis points, so an
        unmodelled-quality list responds below the season base. The rental's
        `expected_response_rate_bps` is then the season's `prospect_base_response_bps`
        multiplied by the quantity ten thousand plus the lift, divided by ten
        thousand, with the result rounded half up to a whole basis point."

        Design: Corner/calculations/coop_model_score_bands_lift_and_cut_the_prospect_response_rate
        """
        modeled = _four_lists_modeled_at_the_band_edges(api)

        assert modeled["L399"]["expected_response_rate_bps"] == 77
        assert modeled["L400"]["expected_response_rate_bps"] == 110
        assert modeled["L600"]["expected_response_rate_bps"] == 132
        assert modeled["L800"]["expected_response_rate_bps"] == 154

        assert modeled["L399"]["expected_response_rate_bps"] < 110
        assert modeled["L400"]["coop_model_score"] == 400

    def test_modeling_records_the_score_without_pricing_a_single_name(self, api):
        """PRD §3.2: "**Ordering** moves the rental `MODELED → ORDERED` and takes no
        payload. It freezes the rental's per-name price: `unit_cost_cents_per_name`
        becomes `cost_per_thousand_cents` divided by one thousand, rounded half up to
        whole cents."

        Design: Corner/calculations/coop_model_score_bands_lift_and_cut_the_prospect_response_rate
        """
        modeled = _four_lists_modeled_at_the_band_edges(api)

        for name, score in SCORES.items():
            rental = modeled[name]
            assert_prospect_list_rental(rental)
            assert rental["status"] == "MODELED"
            assert rental["coop_model_score"] == score
            assert rental["unit_cost_cents_per_name"] == 0
            assert rental["gross_names"] == 0
            assert rental["net_names_delivered"] == 0
            assert rental["version"] == 2
