"""Projection layer: dual-variant market estimation, rounding precision,
signed restatement deltas, methodology restatement OCC, and cell schema."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_cell,
    create_methodology,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import DAM, PA


def _divergence_cell():
    """Cell whose two projection variants diverge on identical inputs:
    WEIGHTED 250 * 400/100 = 1000, DENSITY 250 * (10000000/2000000) * 1.0 = 1250."""
    methodology = create_methodology(name="M1", default_variant="PROJECTION_WEIGHTED")
    cell = create_cell(
        methodology["id"],
        geography_code="CA-SOUTH",
        specialty="CARDIOLOGY",
        period_code="2026-08",
        sample_units=250,
        market_outlets=400,
        sampled_outlets=100,
        market_population=10000000,
        sampled_population=2000000,
        specialty_uptake_index=1.0,
        supplier_ids=[],
    )
    return methodology, cell


class TestProjectionVariantDivergence:
    def test_weighted_variant_scales_by_outlet_coverage(self, api):
        """PRD §3.5: "Under `PROJECTION_WEIGHTED`, the estimate is the sample units scaled by outlet
        coverage: `sample_units` multiplied by `market_outlets` divided by `sampled_outlets`,
        rounded half-up to integer units."

        Design: Difficulty/dual_variant_calc/projection_weighted_vs_density_divergence
        """
        _methodology, cell = _divergence_cell()
        data = validate_success(
            api.recompute_cell(cell["id"], {"projection_variant": "PROJECTION_WEIGHTED"}, PA)
        )
        assert data["estimate_units"] == 1000, (
            f"250 * 400/100 must be 1000, got {data['estimate_units']}"
        )
        assert data["status"] == "CURRENT"

    def test_density_variant_diverges_and_records_signed_delta(self, api):
        """PRD §3.5: "Under `PROJECTION_DENSITY`, the estimate scales by population density and
        specialty uptake instead: `sample_units` multiplied by the quotient of `market_population`
        over `sampled_population`, that product multiplied by `specialty_uptake_index`, rounded
        half-up to integer units."
        PRD §3.5: "The fresh value is written to `estimate_units`, and `restatement_delta_units`
        records the signed difference between the new estimate and the previous one — null on
        the very first recompute, when no previous estimate exists."

        Design: Difficulty/dual_variant_calc/projection_weighted_vs_density_divergence
        """
        _methodology, cell = _divergence_cell()
        weighted = validate_success(
            api.recompute_cell(cell["id"], {"projection_variant": "PROJECTION_WEIGHTED"}, PA)
        )
        density = validate_success(
            api.recompute_cell(cell["id"], {"projection_variant": "PROJECTION_DENSITY"}, PA)
        )
        assert density["estimate_units"] == 1250, (
            f"250 * (10000000/2000000) * 1.0 must be 1250, got {density['estimate_units']}"
        )
        assert weighted["estimate_units"] != density["estimate_units"], (
            "the two variants must diverge on identical inputs"
        )
        assert density["restatement_delta_units"] == 250, (
            f"delta must be 1250 - 1000 = 250, got {density['restatement_delta_units']}"
        )
        fetched = validate_success(api.get_cell(cell["id"], PA))
        assert fetched["status"] == "CURRENT"


class TestProjectionRounding:
    def test_estimate_rounds_half_up(self, api):
        """PRD §3.5: "Under `PROJECTION_WEIGHTED`, the estimate is the sample units scaled by outlet
        coverage: `sample_units` multiplied by `market_outlets` divided by `sampled_outlets`,
        rounded half-up to integer units."

        Design: Corner/calculations/projection_round_half_up_precision
        """
        methodology = create_methodology(name="M-PRC")
        cell = create_cell(
            methodology["id"],
            geography_code="G-P",
            sample_units=251,
            market_outlets=350,
            sampled_outlets=100,
        )
        data = validate_success(
            api.recompute_cell(cell["id"], {"projection_variant": "PROJECTION_WEIGHTED"}, PA)
        )
        assert data["estimate_units"] == 879, (
            f"round-half-up of 878.5 must be 879, got {data['estimate_units']}"
        )


class TestRestatementDelta:
    def test_first_recompute_has_null_delta(self, api):
        """PRD §3.5: "The fresh value is written to `estimate_units`, and `restatement_delta_units`
        records the signed difference between the new estimate and the previous one — null on
        the very first recompute, when no previous estimate exists."

        Design: Corner/calculations/restatement_delta_signed_after_coverage_loss
        """
        from test_helpers import setup_validated_batch

        supplier, agreement, _batch = setup_validated_batch(
            batch_overrides={"period_code": "2026-08", "record_count": 100}
        )
        methodology = create_methodology(name="M-DELTA")
        cell = create_cell(
            methodology["id"],
            geography_code="CA-SOUTH",
            specialty="CARDIOLOGY",
            period_code="2026-08",
            sample_units=250,
            market_outlets=400,
            sampled_outlets=100,
            market_population=10000000,
            sampled_population=2000000,
            specialty_uptake_index=1.0,
            supplier_ids=[supplier["id"]],
        )
        first = validate_success(
            api.recompute_cell(cell["id"], {"projection_variant": "PROJECTION_WEIGHTED"}, PA)
        )
        assert first["estimate_units"] == 1000
        assert first["restatement_delta_units"] is None, (
            "the very first recompute has no previous estimate, so delta must be null"
        )

    def test_signed_delta_after_coverage_loss(self, api):
        """PRD §3.5: "The fresh value is written to `estimate_units`, and `restatement_delta_units`
        records the signed difference between the new estimate and the previous one — null on
        the very first recompute, when no previous estimate exists."
        PRD §3.5: "The request names a `projection_variant` — which overrides the methodology's
        `default_variant` for this recompute — and may optionally supply a corrected
        `sampled_outlets`."

        Design: Corner/calculations/restatement_delta_signed_after_coverage_loss
        """
        from test_helpers import setup_validated_batch

        supplier, agreement, _batch = setup_validated_batch(
            batch_overrides={"period_code": "2026-08", "record_count": 100}
        )
        methodology = create_methodology(name="M-DELTA")
        cell = create_cell(
            methodology["id"],
            geography_code="CA-SOUTH",
            specialty="CARDIOLOGY",
            period_code="2026-08",
            sample_units=250,
            market_outlets=400,
            sampled_outlets=100,
            market_population=10000000,
            sampled_population=2000000,
            specialty_uptake_index=1.0,
            supplier_ids=[supplier["id"]],
        )
        first = validate_success(
            api.recompute_cell(cell["id"], {"projection_variant": "PROJECTION_WEIGHTED"}, PA)
        )
        assert first["estimate_units"] == 1000
        get_success_data(api.suspend_agreement(agreement["id"], DAM))
        suspended = validate_success(api.get_cell(cell["id"], PA))
        assert suspended["status"] == "PENDING_RESTATEMENT"
        second = validate_success(
            api.recompute_cell(
                cell["id"],
                {"projection_variant": "PROJECTION_WEIGHTED", "sampled_outlets": 50},
                PA,
            )
        )
        assert second["estimate_units"] == 2000, (
            f"250 * 400/50 must be 2000, got {second['estimate_units']}"
        )
        assert second["restatement_delta_units"] == 1000, (
            f"signed delta 2000 - 1000 must be 1000, got {second['restatement_delta_units']}"
        )
        assert second["status"] == "CURRENT"


class TestMethodologyRestateOCC:
    def test_matching_expected_version_restate_succeeds(self, api):
        """PRD §2.5: "Restating a projection methodology requires the request to carry
        `expected_methodology_version` equal to the methodology's current `version`; if the
        methodology's version has advanced since the client last observed it — because a prior
        restate already bumped the version and marked cells pending restatement — the request
        is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/errors/stale_version_restate_methodology_returns_412
        """
        methodology = create_methodology(name="M-OCC")
        restated = validate_success(
            api.restate_methodology(
                methodology["id"],
                {"expected_methodology_version": methodology["version"]},
                PA,
            )
        )
        assert restated["version"] == methodology["version"] + 1

    def test_stale_expected_version_restate_rejected_412(self, api):
        """PRD §2.5: "Restating a projection methodology requires the request to carry
        `expected_methodology_version` equal to the methodology's current `version`; if the
        methodology's version has advanced since the client last observed it — because a prior
        restate already bumped the version and marked cells pending restatement — the request
        is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/errors/stale_version_restate_methodology_returns_412
        """
        methodology = create_methodology(name="M-OCC")
        stale_version = methodology["version"]
        validate_success(
            api.restate_methodology(
                methodology["id"],
                {"expected_methodology_version": stale_version},
                PA,
            )
        )
        resp = api.restate_methodology(
            methodology["id"],
            {"expected_methodology_version": stale_version},
            PA,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        fetched = validate_success(api.get_methodology(methodology["id"], PA))
        assert fetched["version"] == stale_version + 1, (
            "the rejected stale restate must not advance the version"
        )


class TestRecomputeSchemaGuards:
    def test_zero_sampled_outlets_rejected_and_estimate_untouched(self, api):
        """PRD §3.5: "Creating one — a `PlatformAdmin` act — requires the `methodology_id`, a
        `geography_code` such as `CA-SOUTH`, a `specialty` from the same four-value enumeration
        as prescribers, a `period_code` in `YYYY-MM` form, and six measurement inputs:
        `sample_units` (observed units in the sample, zero or more), `market_outlets` and
        `sampled_outlets` (each at least 1), `market_population` and `sampled_population`
        (each at least 1), and a strictly positive `specialty_uptake_index`."

        Design: Corner/validations/recompute_zero_sampled_outlets_invalid_request
        """
        methodology = create_methodology(name="M-Z")
        cell = create_cell(methodology["id"], geography_code="GZ")
        resp = api.recompute_cell(
            cell["id"],
            {"projection_variant": "PROJECTION_WEIGHTED", "sampled_outlets": 0},
            PA,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        fetched = validate_success(api.get_cell(cell["id"], PA))
        assert fetched["estimate_units"] is None
