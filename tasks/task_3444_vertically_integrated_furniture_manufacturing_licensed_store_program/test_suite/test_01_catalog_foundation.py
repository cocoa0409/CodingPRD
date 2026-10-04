"""Catalog foundation: creation envelopes, computed clearance price, defaults,
and request-shape validation (PRD §2.2, §2.4, §2.8, §3.1, §3.2, §3.6)."""
from test_helpers import (
    ApiErrorId,
    assert_distribution_center,
    assert_factory,
    assert_licensee,
    assert_product_line,
    create_distribution_center_payload,
    create_factory_payload,
    create_licensee_payload,
    create_product_line_payload,
    validate_error,
    validate_success,
)


class TestFactoryCreation:
    def test_factory_create_applies_defaults_and_envelope(self, api, platform_admin_headers):
        """PRD §3.1: "New factories start `ACTIVE`."
        PRD §4: "endpoints that create a new resource respond with HTTP 201"
        PRD §2.2: "The `response_type` is either "object" for a single resource or
        "array" for a list of resources."
        PRD §2.4: "Every resource in this API — factories, product lines, licensees,
        territories, retail accounts, distribution centers, allocation cycles, supply
        orders, delivery appointments, warranty claims, and parts orders — carries the
        same four system-managed properties, with no exceptions"

        Design: Corner/entities/factory_create_applies_defaults_and_envelope
        """
        resp = api.create_factory(
            create_factory_payload(
                code="FAC-D1",
                region="DOMESTIC",
                component_lines=["FOAM", "FRAMES", "UPHOLSTERY"],
                weekly_capacity_units=100,
            ),
            platform_admin_headers,
        )
        assert resp.status_code == 201, f"expected 201, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body["response_type"] == "object"
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert isinstance(body["meta"].get("api_request_timestamp"), str)
        factory = body["data"]
        assert_factory(factory)
        assert factory["status"] == "ACTIVE", (
            f"new factory must start ACTIVE, got {factory['status']}"
        )

    def test_factory_create_missing_required_capacity_returns_400(self, api, platform_admin_headers):
        """PRD §3.1: "A `PlatformAdmin` registers each factory with a unique `code`,
        a `region` of `DOMESTIC` or `OVERSEAS`, a non-empty `component_lines` array
        whose members are drawn from `FOAM`, `FRAMES`, and `UPHOLSTERY` ..., and a
        `weekly_capacity_units` integer greater than zero."
        PRD §2.8: "Required fields present, types valid, enum values in range ... —
        any such defect is `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/entities/factory_create_missing_required_capacity_returns_400
        """
        resp = api.create_factory(
            {"code": "FAC-X1", "region": "DOMESTIC", "component_lines": ["FOAM"]},
            platform_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


class TestProductLineCreation:
    def test_product_line_create_computes_clearance_price(self, api, platform_admin_headers):
        """PRD §3.1: "Every line's `lifecycle` field starts at `CONCEPT`."
        PRD §3.1: "Its `clearance_price_cents` is computed as the price point times
        the clearance keep `CLEARANCE_MARKDOWN_KEEP` of 0.75, rounded half-up to cents
        — the clearance markdown keeps 75 percent of the price point — and it is
        recomputed on every price change."

        Design: Corner/entities/product_line_create_computes_clearance_price
        """
        resp = api.create_product_line(
            create_product_line_payload(
                name="Alder Sofa Collection",
                category="UPHOLSTERY",
                price_point_cents=89900,
                style_code="ALD-SOFA-01",
            ),
            platform_admin_headers,
        )
        line = validate_success(resp, 201)
        assert_product_line(line)
        assert line["lifecycle"] == "CONCEPT"
        # round_half_up(89900 * 0.75) == 67425, computed already at create.
        assert line["clearance_price_cents"] == 67425, (
            f"expected clearance_price_cents 67425, got {line['clearance_price_cents']}"
        )

    def test_price_point_off_ladder_rejected(self, api, platform_admin_headers):
        """PRD §3.1: "a `price_point_cents` that must be a member of the fixed price
        ladder `PRICE_LADDER_CENTS`, whose five rungs are exactly 39900, 59900, 89900,
        129900, and 189900 cents. Any other price point is rejected with
        `ERR_PRICE_POINT_NOT_ON_LADDER`."

        Design: Corner/entities/price_point_off_ladder_rejected
        """
        resp = api.create_product_line(
            create_product_line_payload(
                name="Off Ladder Line",
                category="BEDDING",
                price_point_cents=99999,
                style_code="OFF-01",
            ),
            platform_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PRICE_POINT_NOT_ON_LADDER.value)


class TestLicenseeCreation:
    def test_licensee_create_applies_defaults_and_initial_state(self, api, platform_admin_headers):
        """PRD §3.2: "`royalty_rate`, the fraction owed on delivered licensee order
        totals, defaults to 0.04; `merchandising_standard_version`, the pinned
        merchandising standards revision, defaults to "MS-2026.1"; and
        `latest_audit_score`, the most recent merchandising standards audit on a
        0-to-100 scale, defaults to 80."
        PRD §3.2: "A new licensee's `status` is `APPLICANT`; its computed ledger fields
        `royalty_accrued_cents` and `chargeback_cents` start at 0, with
        `net_royalty_cents` derived as accrued minus chargebacks; and `last_cycle_score`
        and `seasoned_score` remain null until the first cycle close scores the licensee."

        Design: Corner/entities/licensee_create_applies_defaults_and_initial_state
        """
        resp = api.create_licensee(
            create_licensee_payload(business_name="Summit Home Furnishings"),
            platform_admin_headers,
        )
        licensee = validate_success(resp, 201)
        assert_licensee(licensee)
        assert licensee["status"] == "APPLICANT"
        assert licensee["royalty_rate"] == 0.04
        assert licensee["merchandising_standard_version"] == "MS-2026.1"
        assert licensee["latest_audit_score"] == 80
        assert licensee["last_cycle_score"] is None
        assert licensee["seasoned_score"] is None
        assert licensee["royalty_accrued_cents"] == 0
        assert licensee["chargeback_cents"] == 0
        assert licensee["net_royalty_cents"] == 0


class TestDistributionCenterCreation:
    def test_dc_create_default_crew_units_six(self, api, platform_admin_headers):
        """PRD §3.6: "A `PlatformAdmin` registers each DC with a unique `code`, the
        `supports_home_delivery` flag, a `region_codes` array naming the regions the DC
        covers for freight and home delivery, and `daily_crew_units` — its concurrent
        home-delivery crew capacity — which defaults to 6 and must lie between 1 and 20
        inclusive."

        Design: Corner/entities/dc_create_default_crew_units_six
        """
        resp = api.create_distribution_center(
            create_distribution_center_payload(
                code="DC-KENT",
                supports_home_delivery=True,
                region_codes=["T-SEA"],
            ),
            platform_admin_headers,
        )
        dc = validate_success(resp, 201)
        assert_distribution_center(dc)
        assert dc["daily_crew_units"] == 6, (
            f"omitted daily_crew_units must default to 6, got {dc['daily_crew_units']}"
        )
