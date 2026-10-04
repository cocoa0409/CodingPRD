"""Optimistic concurrency control, entity-specific 404s, and immediate read
consistency of writes (PRD §2.2, §2.4, §2.7, §2.9, §3.1, §3.2)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_version_incremented,
    create_active_licensee,
    create_product_line,
    advance_product_line,
    get_licensee,
    get_product_line,
    validate_error,
    validate_success,
)


class TestEntityNotFoundFamily:
    def test_entity_not_found_family_returns_specific_404s(self, api, platform_admin_headers):
        """PRD §2.9: "rejecting at the first unknown id with that entity's dedicated
        error: `ERR_FACTORY_NOT_FOUND`, `ERR_PRODUCT_LINE_NOT_FOUND`,
        `ERR_LICENSEE_NOT_FOUND`, `ERR_TERRITORY_NOT_FOUND`,
        `ERR_RETAIL_ACCOUNT_NOT_FOUND`, `ERR_DC_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`,
        `ERR_ORDER_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, or
        `ERR_PARTS_ORDER_NOT_FOUND` (all HTTP 404)."

        Design: Corner/errors/entity_not_found_family_returns_specific_404s
        """
        cases = [
            (api.get_factory, ApiErrorId.ERR_FACTORY_NOT_FOUND.value),
            (api.get_product_line, ApiErrorId.ERR_PRODUCT_LINE_NOT_FOUND.value),
            (api.get_licensee, ApiErrorId.ERR_LICENSEE_NOT_FOUND.value),
            (api.get_territory, ApiErrorId.ERR_TERRITORY_NOT_FOUND.value),
            (api.get_retail_account, ApiErrorId.ERR_RETAIL_ACCOUNT_NOT_FOUND.value),
            (api.get_distribution_center, ApiErrorId.ERR_DC_NOT_FOUND.value),
            (api.get_allocation_cycle, ApiErrorId.ERR_CYCLE_NOT_FOUND.value),
            (api.get_order, ApiErrorId.ERR_ORDER_NOT_FOUND.value),
            (api.get_delivery_appointment, ApiErrorId.ERR_APPOINTMENT_NOT_FOUND.value),
            (api.get_warranty_claim, ApiErrorId.ERR_CLAIM_NOT_FOUND.value),
            (api.get_parts_order, ApiErrorId.ERR_PARTS_ORDER_NOT_FOUND.value),
        ]
        for getter, expected_error in cases:
            resp = getter(NON_EXISTENT_UUID, platform_admin_headers)
            assert resp.status_code == 404, (
                f"{expected_error}: expected 404, got {resp.status_code}"
            )
            body = resp.json()
            assert body["response_type"] == "error"
            assert body["data"]["error_id"] == expected_error, (
                f"expected {expected_error}, got {body['data']['error_id']}"
            )


class TestProductLineOcc:
    def test_stale_product_line_version_returns_412(self, api, platform_admin_headers):
        """PRD §2.7: "Changing a product line's price point requires the request to
        carry `expected_product_line_version` equal to the product line's current
        `version`. If another writer has advanced the line's version since the client
        last read it, the update is rejected with `ERR_STALE_PRODUCT_LINE_VERSION`
        (HTTP 412)"
        PRD §3.1: "A successful price change increments the line's `version` and
        recomputes `clearance_price_cents`."

        Design: Corner/errors/stale_product_line_version_returns_412
        """
        line = create_product_line(price_point_cents=89900)
        line = advance_product_line(line["id"])  # CONCEPT -> ACTIVE
        observed = get_product_line(line["id"])
        v = observed["version"]

        updated = validate_success(
            api.update_product_line_price(
                line["id"],
                {"price_point_cents": 129900, "expected_product_line_version": v},
                platform_admin_headers,
            )
        )
        assert updated["price_point_cents"] == 129900
        # round_half_up(129900 * 0.75) == 97425, recomputed on the price change.
        assert updated["clearance_price_cents"] == 97425
        assert_version_incremented(updated["version"], v)
        assert updated["version"] == v + 1, "version increments by exactly 1 (PRD §2.4)"

        # Replaying against the now-stale observed version is rejected.
        replay = api.update_product_line_price(
            line["id"],
            {"price_point_cents": 59900, "expected_product_line_version": v},
            platform_admin_headers,
        )
        validate_error(replay, ApiErrorId.ERR_STALE_PRODUCT_LINE_VERSION.value)
        assert get_product_line(line["id"])["price_point_cents"] == 129900


class TestLicenseeOcc:
    def test_stale_licensee_version_returns_412(self, api, platform_admin_headers):
        """PRD §2.7: "Updating a licensee's commercial terms likewise requires
        `expected_licensee_version` matching the licensee's current `version`; a
        mismatch is rejected with `ERR_STALE_LICENSEE_VERSION` (HTTP 412)."

        Design: Corner/errors/stale_licensee_version_returns_412
        """
        licensee = create_active_licensee()
        observed = get_licensee(licensee["id"])
        v = observed["version"]

        updated = validate_success(
            api.update_licensee_terms(
                licensee["id"],
                {"expected_licensee_version": v, "royalty_rate": 0.05},
                platform_admin_headers,
            )
        )
        assert updated["royalty_rate"] == 0.05
        assert updated["version"] == v + 1

        replay = api.update_licensee_terms(
            licensee["id"],
            {"expected_licensee_version": v, "royalty_rate": 0.06},
            platform_admin_headers,
        )
        validate_error(replay, ApiErrorId.ERR_STALE_LICENSEE_VERSION.value)
        assert get_licensee(licensee["id"])["royalty_rate"] == 0.05

    def test_terms_update_response_reflects_new_values_immediately(self, api, platform_admin_headers):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data field."
        PRD §2.4: "`version` (integer): a system-managed integer that increments by
        exactly 1 on every successful mutating call against the resource."
        PRD §3.2: "Terms maintenance is an OCC-guarded write (§2.7): the request carries
        `expected_licensee_version` and any of `royalty_rate`,
        `merchandising_standard_version`, or `latest_audit_score`."

        Design: Corner/consistency_model/terms_update_response_reflects_new_values_immediately
        """
        licensee = create_active_licensee()
        observed = get_licensee(licensee["id"])
        v = observed["version"]
        updated = validate_success(
            api.update_licensee_terms(
                licensee["id"],
                {
                    "expected_licensee_version": v,
                    "royalty_rate": 0.05,
                    "merchandising_standard_version": "MS-2026.2",
                },
                platform_admin_headers,
            )
        )
        # The write response itself carries the new values — no follow-up read needed.
        assert updated["royalty_rate"] == 0.05
        assert updated["merchandising_standard_version"] == "MS-2026.2"
        assert updated["version"] == v + 1
        assert updated["updated_at"] is not None
