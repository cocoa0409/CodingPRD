"""Metal price index immutability and can-format creation/tooling rules
(PRD §2.5, §2.7, §3.3)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    set_clock, create_plant, create_customer, create_format, create_format_payload,
    publish_index_payload, api_client, manager, admin,
)


class TestMetalPriceIndex:
    def test_metal_price_index_is_immutable_common_fields_false(self, api):
        """PRD §2.5: "The one exception is the metal price index. A published
        index row is immutable after creation and therefore carries only `id`
        and `created_at`; both `updated_at` and `version` are absent from it."

        Design: Corner/entities/metal_price_index_is_immutable_common_fields_false
        """
        set_clock()
        resp = api.publish_index(publish_index_payload("2026-08", 128.0), admin())
        data = validate_success(resp, 201)
        assert data["period"] == "2026-08"
        assert data["index_cents_per_lb"] == 128.0
        assert "id" in data and "created_at" in data
        assert "version" not in data, "immutable index row carries no version"
        assert "updated_at" not in data, "immutable index row carries no updated_at"


class TestFormatCreation:
    def test_format_create_response_carries_computed_state_immediately(self, api):
        """PRD §3.3: "A proposed format starts in `PROPOSED` with
        `delivered_units` at 0 and `unamortized_exposure_cents` at 0."

        Design: Corner/consistency_model/format_create_response_carries_computed_state_immediately
        """
        set_clock()
        plant = create_plant()
        customer = create_customer()
        resp = api.create_format(plant["id"], create_format_payload(customer["id"]),
                                 manager())
        data = validate_success(resp, 201)
        assert data["status"] == "PROPOSED"
        assert data["delivered_units"] == 0
        assert data["unamortized_exposure_cents"] == 0

    def test_format_create_with_out_of_enum_shape_returns_validation(self, api):
        """PRD §3.3: "a `shape` of `STANDARD`, `SLEEK`, `SLIM`, or `STUBBY`".
        PRD §2.7 gate 3: "required fields present, types valid, enum membership
        respected ... Violations are rejected with `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/entities/format_create_with_out_of_enum_shape_returns_validation
        """
        set_clock()
        plant = create_plant()
        customer = create_customer()
        payload = create_format_payload(customer["id"], size_code="99OZ",
                                        shape="MEGA")
        resp = api.create_format(plant["id"], payload, manager())
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        data, _meta = validate_paginated(
            api.list_formats(manager(), params={"plant_id": plant["id"]}))
        assert len(data) == 0, "invalid-enum format must not be persisted"


class TestSpecialtyToolingTerms:
    def test_specialty_format_tool_requires_tooling_terms_then_succeeds(self, api):
        """PRD §3.3: "When the format is specialty, tooling is rejected with
        `ERR_TOOLING_TERMS_REQUIRED` unless `tooling_investment_cents` and
        `min_volume_commitment_units` are both strictly positive; upon tooling,
        a format with a positive volume commitment initializes its
        `unamortized_exposure_cents` to the full `tooling_investment_cents`."

        Design: Corner/state_machines/specialty_format_tool_requires_tooling_terms_then_succeeds
        """
        set_clock()
        plant = create_plant()
        customer = create_customer()
        f_bad = create_format(plant["id"], customer["id"],
                              size_code="8OZ-SLEEK", shape="SLEEK",
                              is_specialty=True, metal_lbs_per_1000_units=22.0,
                              tooling_investment_cents=0,
                              min_volume_commitment_units=0)
        f_ok = create_format(plant["id"], customer["id"],
                             size_code="250ML-SLIM", shape="SLIM",
                             is_specialty=True, metal_lbs_per_1000_units=18.0,
                             tooling_investment_cents=100000,
                             min_volume_commitment_units=1000000)
        resp_bad = api.tool_format(f_bad["id"], manager())
        validate_error(resp_bad, ApiErrorId.ERR_TOOLING_TERMS_REQUIRED)
        still = validate_success(api.get_format(f_bad["id"], manager()))
        assert still["status"] == "PROPOSED"
        tooled = validate_success(api.tool_format(f_ok["id"], manager()))
        assert tooled["status"] == "TOOLED"
        assert tooled["unamortized_exposure_cents"] == 100000
