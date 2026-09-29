"""Ranch registration, block planting geometry and block inventory listing."""
from test_helpers import (
    MISSING_UUID_A,
    ApiErrorId,
    assert_block,
    assert_money,
    assert_version,
    assert_vineyard,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx


class TestRanchRegistration:
    """PRD §3.1 — registering a client ranch and reading its live roll-ups."""

    def test_ranch_create_returns_the_registered_ranch_with_system_fields(self, api):
        """A freshly registered ranch reports a `block_count` of 0 and `managed_acres` of 0.00.

        Design: Corner/entities/vineyard_create_returns_object_envelope_with_system_fields
        """
        response = api.create_vineyard(f.vineyard_payload(), fx.VM)
        data = validate_success(response, 201)
        body = response.json()

        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])

        assert_vineyard(data)
        assert data["name"] == "Ridgecrest Ranch"
        assert data["owner_legal_name"] == "Ridgecrest Vineyards LLC"
        assert data["ava_region"] == "Paso Robles"
        assert data["client_contact_email"] == "ops@ridgecrest.example"
        assert data["block_count"] == 0
        assert_money(data["managed_acres"], 0.00, "managed_acres")
        assert_version(data, 1, "ranch")
        assert data["id"] is not None
        assert data["created_at"] is not None
        assert data["updated_at"] is not None

    def test_ranch_read_recomputes_block_count_and_managed_acres(self, api):
        """`block_count` is the number of blocks belonging to the ranch whose `farming_status` is either `ESTABLISHING` or `BEARING`, and `managed_acres` is the sum of `acres` over that same set, rounded to two decimal places.

        Design: Corner/entities/vineyard_get_returns_stored_representation_with_recomputed_aggregates
        """
        s = fx.setup_ranch_with_block(api)
        fx.create_block_b14(api, s.vineyard["id"])

        data = validate_success(api.get_vineyard(s.vineyard["id"], fx.VM))
        assert_vineyard(data)
        assert data["id"] == s.vineyard["id"]
        assert data["name"] == "Ridgecrest Ranch"
        assert data["block_count"] == 2
        assert_money(data["managed_acres"], 16.5, "managed_acres")


class TestBlockPlantingGeometry:
    """PRD §3.1 and §2.7 — vine density is derived once and truncated."""

    def test_block_vine_geometry_is_truncated_from_the_spacing_pair(self, api):
        """There are 43,560 square feet in an acre; dividing that by the product of the in-row and between-row spacings and discarding any fraction gives `vines_per_acre`. Vine geometry is the one place where rounding is replaced by truncation.

        Design: Corner/entities/block_vine_geometry_is_computed_and_floored_from_spacing
        """
        s = fx.setup_ranch(api)
        payload = f.block_payload_b16(s.vineyard["id"], rootstock="RIPARIA_GLOIRE")
        data = validate_success(api.create_block(payload, fx.VM), 201)

        assert_block(data)
        assert data["block_code"] == "B-16"
        assert data["variety"] == "SYRAH"
        assert data["clone"] == "FPS-07"
        assert data["rootstock"] == "RIPARIA_GLOIRE"
        assert data["trellis_system"] == "QUADRILATERAL_CORDON"
        assert data["planting_year"] == 2019
        assert data["vines_per_acre"] == 691
        assert data["vine_count"] == 2487
        assert data["farming_status"] == "ESTABLISHING"
        assert data["compliance_posture"] == "CLEAR"
        assert data["harvest_posture"] == "NOT_ESTIMATED"
        assert data["contract_id"] is None
        assert data["contracted_acres"] is None
        assert data["per_acre_fee_override"] is None
        assert_version(data, 1, "block")

    def test_block_geometry_applies_the_square_feet_per_acre_constant(self, api):
        """Multiplying `vines_per_acre` by the block's `acres` and again discarding any fraction gives `vine_count`. A new block opens with `farming_status` `ESTABLISHING`, `compliance_posture` `CLEAR` and `harvest_posture` `NOT_ESTIMATED`.

        Design: Corner/calculations/block_geometry_applies_sq_ft_per_acre_constant
        """
        s = fx.setup_ranch(api)
        payload = f.block_payload(
            s.vineyard["id"],
            block_code="B-30",
            variety="PINOT_NOIR",
            clone="FPS-23",
            rootstock="ROOTSTOCK_SO4",
            trellis_system="VSP",
            planting_year=2024,
            vine_spacing_ft=6.0,
            row_spacing_ft=10.0,
            acres=4.0,
        )
        data = validate_success(api.create_block(payload, fx.VM), 201)

        assert_block(data)
        assert data["vines_per_acre"] == 726
        assert data["vine_count"] == 2904
        assert data["farming_status"] == "ESTABLISHING"
        assert data["season_applied_inches"] == 0.000


class TestBlockCreateBodyShape:
    """PRD §2.6 rung 3 — body shape is checked before anything about the domain."""

    def test_block_create_without_a_variety_is_rejected(self, api):
        """Body shape (all write endpoints) — every required field present, every field of the declared JSON type, every enum value inside its declared set, every number inside its declared range, and no unknown fields, else `ERR_INVALID_REQUEST`.

        Design: Corner/entities/block_create_missing_variety_rejected
        """
        s = fx.setup_ranch(api)
        payload = f.block_payload(s.vineyard["id"], variety=f.OMIT)
        assert "variety" not in payload

        validate_error(api.create_block(payload, fx.VM), ApiErrorId.ERR_INVALID_REQUEST)

        ranch = validate_success(api.get_vineyard(s.vineyard["id"], fx.VM))
        assert ranch["block_count"] == 0
        assert_money(ranch["managed_acres"], 0.00, "managed_acres")

    def test_block_create_with_an_undeclared_variety_is_rejected(self, api):
        """Body shape (all write endpoints) — every required field present, every field of the declared JSON type, every enum value inside its declared set, every number inside its declared range, and no unknown fields, else `ERR_INVALID_REQUEST`.

        Design: Corner/entities/block_create_invalid_enum_variety_rejected
        """
        s = fx.setup_ranch(api)
        payload = f.block_payload(s.vineyard["id"], variety="MERLOT")

        validate_error(api.create_block(payload, fx.VM), ApiErrorId.ERR_INVALID_REQUEST)

        ranch = validate_success(api.get_vineyard(s.vineyard["id"], fx.VM))
        assert ranch["block_count"] == 0

    def test_block_create_carrying_server_owned_fields_is_rejected(self, api):
        """Body shape (all write endpoints) — every required field present, every field of the declared JSON type, every enum value inside its declared set, every number inside its declared range, and no unknown fields, else `ERR_INVALID_REQUEST`.

        Design: Corner/entities/block_create_extra_field_input_ignored
        """
        s = fx.setup_ranch(api)
        payload = f.block_payload(s.vineyard["id"], farming_status="BEARING", version=9)

        validate_error(api.create_block(payload, fx.VM), ApiErrorId.ERR_INVALID_REQUEST)

        ranch = validate_success(api.get_vineyard(s.vineyard["id"], fx.VM))
        assert ranch["block_count"] == 0


class TestBlockReadAndListing:
    """PRD §2.5 and §2.3 — path resolution and paginated narrowing."""

    def test_reading_an_unknown_block_id_reports_block_not_found(self, api):
        """A request against a block's scouting observations resolves the block segment first; if no such block exists the answer is `ERR_BLOCK_NOT_FOUND` (HTTP 404), and nothing further about the request is inspected.

        Design: Corner/entities/block_get_with_unknown_id_returns_block_not_found
        """
        response = api.get_block(MISSING_UUID_A, fx.VM)
        error = validate_error(response, ApiErrorId.ERR_BLOCK_NOT_FOUND)

        assert response.json()["response_type"] == "error"
        assert error["message"].strip() != ""

    def test_block_listing_narrows_by_ranch_and_reports_the_page_window(self, api):
        """Every list response carries `limit`, `offset`, `total_count` and `has_more` inside `meta`. `total_count` is the number of rows matching the filter before the page window is applied, and `has_more` is true exactly when rows remain beyond the current window.

        Design: Corner/entities/block_list_filters_by_vineyard_and_reports_pagination_fields
        """
        ranch_a = fx.create_vineyard(api)
        block_a = fx.create_block(api, ranch_a["id"])
        ranch_b = fx.create_vineyard(api, name="Salinas Bench",
                                     owner_legal_name="Salinas Bench Vines LLC")
        fx.create_block(api, ranch_b["id"], block_code="S-01")
        fx.create_block(api, ranch_b["id"], block_code="S-02")

        first_page, meta = validate_paginated(
            api.list_blocks(fx.VM, {"vineyard_id": ranch_b["id"], "limit": 1, "offset": 0})
        )
        assert len(first_page) == 1
        assert meta["total_count"] == 2
        assert meta["limit"] == 1
        assert meta["offset"] == 0
        assert meta["has_more"] is True
        assert all(row["block_code"] != "B-12" for row in first_page)

        past_end, past_meta = validate_paginated(
            api.list_blocks(fx.VM, {"vineyard_id": ranch_b["id"], "limit": 1, "offset": 2})
        )
        assert past_end == []
        assert past_meta["total_count"] == 2
        assert past_meta["offset"] == 2
        assert past_meta["has_more"] is False

        ranch_a_rows, _ = validate_paginated(
            api.list_blocks(fx.VM, {"vineyard_id": ranch_a["id"]})
        )
        assert len(ranch_a_rows) == 1
        assert ranch_a_rows[0]["id"] == block_a["id"]
        assert ranch_a_rows[0]["block_code"] == "B-12"

    def test_duplicate_block_code_is_refused_only_within_the_same_ranch(self, api):
        """The `block_code` must be unique within the owning ranch: a second block carrying a code another block on the same ranch already uses is refused with `ERR_DUPLICATE_BLOCK_CODE`.

        Design: Corner/validations/duplicate_block_code_within_vineyard_rejected
        """
        ranch_a = fx.create_vineyard(api)
        fx.create_block(api, ranch_a["id"])
        ranch_b = fx.create_vineyard(api, name="Salinas Bench",
                                     owner_legal_name="Salinas Bench Vines LLC")

        def clashing_payload(vineyard_id):
            return f.block_payload(
                vineyard_id,
                block_code="B-12",
                variety="ZINFANDEL",
                clone="FPS-06",
                rootstock="ROOTSTOCK_SO4",
                trellis_system="VSP",
                planting_year=2019,
                vine_spacing_ft=6.0,
                row_spacing_ft=10.0,
                acres=4.0,
            )

        validate_error(api.create_block(clashing_payload(ranch_a["id"]), fx.VM),
                       ApiErrorId.ERR_DUPLICATE_BLOCK_CODE)

        accepted = validate_success(
            api.create_block(clashing_payload(ranch_b["id"]), fx.VM), 201
        )
        assert accepted["vines_per_acre"] == 726
        assert accepted["vine_count"] == 2904

        ranch = validate_success(api.get_vineyard(ranch_a["id"], fx.VM))
        assert ranch["block_count"] == 1
        assert_money(ranch["managed_acres"], 12.5, "managed_acres")


class TestRetiredBlockIsClosedDownstream:
    """PRD §3.1 — a replant retires its predecessor, and `REMOVED` is terminal."""

    def test_work_order_create_on_a_retired_block_is_refused(self, api):
        """`REMOVED` is terminal — no operation ever brings a block back — and it closes the block to almost everything downstream: farming-plan drafting, submission and approval, work-order scheduling, irrigation scheduling and recording, spray recommendation and application, pest-observation filing, yield-estimate filing and harvest-load booking are all refused against a `REMOVED` block with `ERR_BLOCK_REMOVED`.

        Design: Corner/errors/work_order_create_on_removed_block_rejected
        """
        ranch = fx.create_vineyard(api)
        block = fx.create_block(api, ranch["id"])
        plan = fx.create_farming_plan(api, block["id"])
        plan = fx.submit_farming_plan(api, plan["id"])
        plan = fx.approve_farming_plan(api, plan["id"])
        crew = fx.create_crew(api)

        successor = validate_success(
            api.create_block(
                f.block_payload(
                    ranch["id"],
                    block_code="B-12R",
                    vine_spacing_ft=4.0,
                    row_spacing_ft=8.0,
                    acres=12.5,
                    replaces_block_id=block["id"],
                ),
                fx.VM,
            ),
            201,
        )
        assert successor["farming_status"] == "ESTABLISHING"
        assert successor["vines_per_acre"] == 1361
        assert successor["vine_count"] == 17012

        retired = fx.read_block(api, block["id"])
        assert retired["farming_status"] == "REMOVED"
        assert_version(retired, 3, "retired block")

        response = api.create_work_order(
            f.work_order_payload(
                block["id"], plan["id"], crew["id"],
                task_type="PRUNING",
                scheduled_start="2026-08-03T14:00:00Z",
                scheduled_end="2026-08-03T22:00:00Z",
                planned_vines=3000, planned_hours=8.0,
            ),
            fx.VM,
        )
        validate_error(response, ApiErrorId.ERR_BLOCK_REMOVED)

        ranch_now = validate_success(api.get_vineyard(ranch["id"], fx.VM))
        assert ranch_now["block_count"] == 1
        assert_money(ranch_now["managed_acres"], 12.5, "managed_acres")
        assert_money(fx.read_plan(api, plan["id"])["committed_cost"], 0.00,
                     "committed_cost")
