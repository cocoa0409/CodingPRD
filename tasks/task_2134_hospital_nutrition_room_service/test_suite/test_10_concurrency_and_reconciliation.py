"""Cross-aggregate optimistic concurrency and derived-field reconciliation."""
import pytest
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_meal_order_payload,
    create_supplement_order_payload,
    diet_order_version,
    line,
    lock_and_open,
    new_dinner_period,
    place_tray,
    read_consult,
    read_diet_order,
    read_meal_order,
    read_meal_period,
    read_patient,
    setup_signed_consult,
    setup_tray_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

MANAGER = TEST_USERS["nutrition_manager_headers"]
CLERK = TEST_USERS["diet_clerk_headers"]
DIETITIAN = TEST_USERS["dietitian_headers"]


class TestOptimisticConcurrency:
    def test_stale_expected_diet_order_version_on_tray_creation_is_rejected(self, api):
        """PRD §2.6: "A request to create a meal order must carry
        `expected_diet_order_version`, holding the `version` the client last observed
        on the diet order named by `diet_order_id`. If it does not equal that diet
        order's current `version`, the creation is rejected with
        `ERR_STALE_DIET_ORDER_VERSION` (HTTP 412)."
        PRD §2.6: "Both are guarded by optimistic concurrency control, and in both
        cases the version field is a **required, non-optional** input — omitting it is a
        malformed request, not an implicit "no opinion"."

        Design: Corner/cross_cutting_layers/stale_expected_diet_order_version_on_tray_creation_returns_conflict
        """
        scenario = setup_tray_scenario(
            menu_keys=("SOU-BRO",),
            patient_overrides={"mrn": "MRN-BA01", "full_name": "Cid Reyes",
                               "age_years": 50},
            forecast_variant="CENSUS_BASED",
            open_for_service=True,
            place_order=False,
        )
        current_version = scenario["diet_order"]["version"]

        response = api.create_meal_order(
            create_meal_order_payload(
                scenario["patient"]["id"],
                scenario["period"]["id"],
                scenario["diet_order"]["id"],
                current_version - 1,
                [line(scenario["menu"]["SOU-BRO"]["id"], 1)],
            ),
            CLERK,
        )
        validate_error(response, ApiErrorId.ERR_STALE_DIET_ORDER_VERSION, 412)

        after = read_diet_order(scenario["diet_order"]["id"])
        assert after["version"] == current_version
        assert after["linked_meal_order_count"] == 0

        _, meta = validate_paginated(
            api.list_meal_orders(
                CLERK, params={"meal_period_id": scenario["period"]["id"]}
            )
        )
        assert meta["total_count"] == 0

    def test_stale_expected_consult_version_on_supplement_creation_is_rejected(self, api):
        """PRD §2.6: "A request to create a supplement order must carry
        `expected_consult_version`, holding the `version` the client last observed on
        the nutrition consult named by `consult_id`. If it does not equal that
        consult's current `version`, the creation is rejected with
        `ERR_STALE_CONSULT_VERSION` (HTTP 412)."
        PRD §2.6: "A consult's `version` advances every time a supplement order is
        attached to it — through `linked_supplement_order_count` — and also on
        assessment and on signature, so a stale value means the recommendation the
        client is acting on has since been revised."

        Design: Corner/cross_cutting_layers/stale_expected_consult_version_on_supplement_creation_returns_conflict
        """
        scenario = setup_signed_consult(
            patient_overrides={"mrn": "MRN-BB01", "full_name": "Dot Emeka",
                               "age_years": 74},
            assessment={"assessment_variant": "SCREENING", "weight_loss_pct": 8.0,
                        "intake_pct": 60.0, "bmi": 17.0},
        )
        signed_version = scenario["consult"]["version"]

        response = api.create_supplement_order(
            create_supplement_order_payload(
                scenario["consult"]["id"],
                scenario["menu"]["SUP-ORS"]["id"],
                signed_version - 1,
                2,
            ),
            DIETITIAN,
        )
        validate_error(response, ApiErrorId.ERR_STALE_CONSULT_VERSION, 412)

        after = read_consult(scenario["consult"]["id"])
        assert after["version"] == signed_version
        assert after["linked_supplement_order_count"] == 0
        assert read_patient(
            scenario["patient"]["id"]
        )["daily_supplement_cost_cents"] == 0


class TestDerivedFieldReconciliation:
    def test_every_accepted_tray_advances_the_linked_count_and_the_version(self, api):
        """PRD §3.6: "Creation also increments the pinned diet order's
        `linked_meal_order_count` by 1 and therefore that diet order's `version` by 1 —
        which is exactly why the next tray placed against the same prescription needs a
        freshly-read `expected_diet_order_version`."
        PRD §2.6: "This matters because a diet order's `version` moves for several
        reasons: every accepted meal order increments the order's
        `linked_meal_order_count` and therefore its `version`, and a cosign, a revision
        request or a discontinuation advances it too."
        PRD §3.6: "An accepted tray is stored with its fulfillment dimension at
        `PENDING_VALIDATION` and its quality-assurance dimension at `NOT_CHECKED`, with
        `placed_by_user_id` stamped from the acting `X-User-ID` and
        `pinned_diet_order_version` stamped with the diet order's `version` at the
        instant of pinning."

        Design: Corner/cross_cutting_layers/diet_order_version_and_linked_count_advance_on_every_accepted_tray
        """
        scenario = setup_tray_scenario(
            menu_keys=("SOU-BRO",),
            patient_overrides={"mrn": "MRN-BC01", "full_name": "Eve Rask",
                               "age_years": 55},
            forecast_variant="CENSUS_BASED",
            open_for_service=True,
        )
        version_at_cosign = scenario["diet_order"]["version"]
        dinner = new_dinner_period(scenario["ward"]["id"])

        version_after_first_tray = diet_order_version(scenario["diet_order"]["id"])
        assert version_after_first_tray == version_at_cosign + 1

        second_tray = place_tray(
            scenario["patient"]["id"],
            dinner["id"],
            scenario["diet_order"]["id"],
            [line(scenario["menu"]["SOU-BRO"]["id"], 1)],
            version_after_first_tray,
        )
        # (The PRD pins that creation stamps "the diet order's `version` at the
        # instant of pinning" but never says whether that instant precedes or
        # follows the creation's own linked-count version bump, so the concrete
        # value of pinned_diet_order_version is not asserted here.)

        after = read_diet_order(scenario["diet_order"]["id"])
        assert after["linked_meal_order_count"] == 2
        assert after["version"] == version_after_first_tray + 1

        _, meta = validate_paginated(
            api.list_meal_orders(
                CLERK, params={"diet_order_id": scenario["diet_order"]["id"]}
            )
        )
        assert meta["total_count"] == 2

    def test_menu_item_reprice_is_absorbed_into_line_cost_on_the_next_validate(self, api):
        """PRD §3.6: "A tray that survives all of that moves `PENDING_VALIDATION →
        VALIDATED`. Its `effective_texture_level` and `effective_liquid_level` are
        refreshed from the pinned order's envelope, its four nutrient totals are
        recomputed, every `line_cost_cents` and the tray's `food_cost_cents` are
        recomputed, and `revalidation_required` is cleared to false."
        PRD §3.2: "Menu items are published `ACTIVE` and the manager may later
        discontinue, reinstate or re-price one, moving `status` between `ACTIVE` and
        `DISCONTINUED` or revising `unit_cost_cents`, with the item's `version` bumping
        on each change."
        PRD §3.5: "`period_overhead_cents` is the subtotal multiplied by the tier's
        overhead rate — 18.0 percent in tier A, 15.0 percent in tier B, 12.0 percent in
        tier C — rounded half up to whole cents."

        Design: Corner/cross_cutting_layers/menu_item_reprice_is_absorbed_into_line_cost_on_the_next_validate
        """
        scenario = setup_tray_scenario(
            menu_keys=("SOU-BRO",),
            patient_overrides={"mrn": "MRN-BD01", "full_name": "Fen Larsen",
                               "age_years": 48},
            forecast_variant="CENSUS_BASED",
            open_for_service=True,
        )
        assert scenario["meal_order"]["food_cost_cents"] == 146

        repriced = validate_success(
            api.update_menu_item(
                scenario["menu"]["SOU-BRO"]["id"], {"unit_cost_cents": 200}, MANAGER
            ),
            200,
        )
        assert repriced["status"] == "ACTIVE"

        validated = validate_success(
            api.validate_meal_order(scenario["meal_order"]["id"], CLERK), 200
        )
        assert validated["food_cost_cents"] == 216
        assert validated["fulfillment_status"] == "VALIDATED"

        period = read_meal_period(scenario["period"]["id"])
        assert period["committed_food_cost_cents"] == 216
        assert period["period_overhead_cents"] == 39
        assert period["period_total_cost_cents"] == 255
