"""Part and customer registration corners: defaults, schema walls, uniqueness."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_part,
    create_customer_payload,
    create_part_payload,
    make_part,
    validate_error,
    validate_success,
)

PLANNER = TEST_USERS["supply_planner_headers"]
CHANNEL = TEST_USERS["channel_manager_headers"]


class TestPartRegistration:
    def test_part_create_applies_defaults_and_system_fields(self, api):
        """PRD §3.1: "A newly registered part starts with `lifecycle_status` `ACTIVE`,
        `on_hand_units` 0, `reserved_units` 0, and a computed `posture`."
        PRD §3.1: "Three optional planner inputs carry defaults: `automotive_grade`, a
        boolean marking the part as qualified for automotive applications, defaults to
        false; `demand_rate_units_per_week`, the planner-maintained trailing demand rate
        in units per week, defaults to 0; and `buffer_multiple`, the deliberate inventory
        buffer multiple applied to demand under the supply-control policy of §2.10,
        defaults to 1.5."
        PRD §3.1: "When the trailing target is zero, posture is `NORMAL`."

        Design: Corner/entities/part_create_applies_defaults_and_system_fields
        """
        payload = create_part_payload(
            part_number="OPA177FP",
            description="Precision op amp",
            package_family="PDIP",
            process_technology="ANALOG_BIPOLAR",
        )
        part = validate_success(api.create_part(payload, PLANNER), 201)
        assert_part(part)
        assert part["lifecycle_status"] == "ACTIVE"
        assert part["demand_rate_units_per_week"] == 0
        assert part["buffer_multiple"] == 1.5
        assert part["automotive_grade"] is False
        assert part["on_hand_units"] == 0
        assert part["reserved_units"] == 0
        assert part["posture"] == "NORMAL"

    def test_part_create_missing_part_number_returns_invalid_request(self, api):
        """PRD §2.8: "Required fields are present, unknown fields are rejected
        (including client-supplied computed or system fields such as `on_hand_units`),
        types are valid, enum members are valid, `quantity` and `total_units` are at
        least 1, a `tiers` array is well-formed (ascending `min_qty` with the first
        tier's `min_qty` exactly 1), and a `part_number` is unique."
        PRD §2.8: "every other schema failure is `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/part_create_missing_part_number_returns_invalid_request
        """
        payload = {
            "description": "No number",
            "package_family": "SOIC",
            "process_technology": "CMOS_180NM",
        }
        validate_error(api.create_part(payload, PLANNER), ApiErrorId.ERR_INVALID_REQUEST)

    def test_part_create_computed_field_input_rejected(self, api):
        """PRD §2.8: "Required fields are present, unknown fields are rejected
        (including client-supplied computed or system fields such as `on_hand_units`),
        types are valid, enum members are valid, `quantity` and `total_units` are at
        least 1, a `tiers` array is well-formed (ascending `min_qty` with the first
        tier's `min_qty` exactly 1), and a `part_number` is unique."

        Design: Corner/entities/part_create_computed_field_input_rejected
        """
        payload = create_part_payload(
            part_number="OPA177GQ",
            description="Sneaky stock",
            package_family="PDIP",
            process_technology="ANALOG_BIPOLAR",
        )
        payload["on_hand_units"] = 9999
        validate_error(api.create_part(payload, PLANNER), ApiErrorId.ERR_INVALID_REQUEST)

    def test_customer_create_invalid_tier_enum_rejected(self, api):
        """PRD §2.8: "Required fields are present, unknown fields are rejected
        (including client-supplied computed or system fields such as `on_hand_units`),
        types are valid, enum members are valid, `quantity` and `total_units` are at
        least 1, a `tiers` array is well-formed (ascending `min_qty` with the first
        tier's `min_qty` exactly 1), and a `part_number` is unique."
        PRD §3.2: "a `tier` of `STRATEGIC`, `KEY`, `STANDARD`, or `SMALL`".

        Design: Corner/entities/customer_create_invalid_tier_enum_rejected
        """
        payload = create_customer_payload(
            name="Enum Testers",
            tier="VIP",
            channel="DIRECT_FIELD",
            credit_limit_cents=1000,
        )
        validate_error(api.create_customer(payload, CHANNEL), ApiErrorId.ERR_INVALID_REQUEST)

    def test_duplicate_part_number_rejected(self, api):
        """PRD §3.1: "registering a `part_number` that already exists is rejected with
        `ERR_DUPLICATE_PART_NUMBER`, HTTP 409".

        Design: Corner/validations/duplicate_part_number_rejected
        """
        first = make_part(
            part_number="LM358N", description="Original", package_family="PDIP"
        )
        res = api.create_part(
            create_part_payload(
                part_number="LM358N",
                description="Duplicate",
                package_family="SOIC",
                process_technology="CMOS_180NM",
            ),
            PLANNER,
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_PART_NUMBER)
        intact = validate_success(api.get_part(first["id"], PLANNER), 200)
        assert intact["package_family"] == "PDIP"
        assert intact["description"] == "Original"
