"""
Who may invoke what, and the two places where identity matters more than role.

Authorisation is settled before any state or payload is examined, so an
unauthorised caller never learns whether its request would otherwise have
worked; and delivery settlement narrows further still, refusing the very
identity that graded the load even when its role is the right one.
"""

from test_helpers import fixtures as fx
from test_helpers import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_2dp, assert_3dp, assert_null
from test_helpers.test_users import (
    COMPLIANCE_OFFICER,
    GRAIN_ACCOUNTANT,
    GRAIN_ACCOUNTANT_AS_GRADER,
    GRAIN_BUYER,
    LOGISTICS_COORDINATOR,
    PLANT_MANAGER,
    PROCESS_OPERATOR,
    RISK_MANAGER,
    SCALE_OPERATOR,
)

_GRADE = {
    "moisture_pct": 15.00,
    "test_weight_lb_per_bu": 54.0,
    "foreign_material_pct": 3.00,
    "damaged_kernels_pct": 5.00,
    "aflatoxin_ppb": 3,
}

_OCTOBER_MARKS = {
    "marks_effective_month": "2026-10",
    "mark_corn_cents_per_bushel": 450.00,
    "mark_ethanol_cents_per_gallon": 178.00,
    "mark_natgas_cents_per_mmbtu": 320.00,
    "mark_soybean_meal_usd_per_ton": 330.00,
    "mark_sbo_cents_per_lb": 45.00,
}

_NOVEMBER_MARKS = {
    "marks_effective_month": "2026-11",
    "mark_corn_cents_per_bushel": 440.00,
    "mark_ethanol_cents_per_gallon": 176.50,
    "mark_natgas_cents_per_mmbtu": 315.00,
    "mark_soybean_meal_usd_per_ton": 335.00,
    "mark_sbo_cents_per_lb": 46.00,
}


def _plant_with_an_ungraded_load_and_a_draft_project(api):
    """
    One booked but ungraded load on a priced contract, and one draft carbon
    project — two rows whose next legitimate step belongs to a single role each.
    """
    plant = fx.commission_plant(api, coverage_floor_bushels=5000)
    fx.advance_clock(api, "2026-09-04T06:00:00Z")
    contract = fx.priced_contract(api, 458.0, supplier_name="Cedar Ridge Elevator")
    delivery = fx.book_delivery(api, contract["id"], ticket_number="TK-0001")
    project = fx.draft_project(
        api,
        project_code="CP-1",
        project_name="Combined heat and power retrofit",
        project_type="COMBINED_HEAT_POWER",
        claimed_reduction_g_per_mj=8.0,
        certification_tier="FULL",
    )
    return {"plant": plant, "delivery": delivery, "project": project}


class TestExclusiveWritesRefuseEveryOtherRole:
    """Four single-role endpoints, four unlisted callers, four 403s."""

    def test_each_exclusive_endpoint_refuses_the_role_that_does_not_hold_it(self, api):
        """Holding some rights on the plant is not holding these ones.

        PRD 2.1: "If the role is recognised but is not among the roles authorised
        for the endpoint being invoked (see the table in §4), the request fails
        with `ERR_UNAUTHORIZED`."
        PRD 4: "| POST | /ethanol-ops/corn-deliveries/{id}/grade | Record the
        grade factors and compute the bushels, discount schedule and net price |
        ScaleOperator |"
        PRD 4: "| POST | /ethanol-ops/hedge-positions | Open a futures position
        on corn, ethanol or natural gas | RiskManager |"

        Design: Corner/rbac/exclusive_operations_refuse_every_other_role
        """
        scenario = _plant_with_an_ungraded_load_and_a_draft_project(api)

        validate_error(
            api.grade_delivery(scenario["delivery"]["id"], _GRADE, GRAIN_BUYER),
            ApiErrorId.UNAUTHORIZED,
            403,
        )
        validate_error(
            api.create_hedge_position(
                {
                    "position_code": "HP-9",
                    "commodity": "ETHANOL",
                    "direction": "SHORT",
                    "contracts": 10,
                    "entry_price": 182.00,
                    "contract_month": "2026-10",
                },
                PROCESS_OPERATOR,
            ),
            ApiErrorId.UNAUTHORIZED,
            403,
        )
        validate_error(
            api.post_market_marks(
                scenario["plant"]["id"], dict(_OCTOBER_MARKS), LOGISTICS_COORDINATOR
            ),
            ApiErrorId.UNAUTHORIZED,
            403,
        )

    def test_the_refusal_precedes_the_state_check_and_records_nothing(self, api):
        """A ComplianceOfficer reviewing a draft is stopped at 403, never reaching the 409.

        PRD 2.9: "1. **Authentication and authorisation of the call itself** —
        `ERR_MISSING_AUTH_HEADERS`, then `ERR_INVALID_ROLE`, then
        `ERR_UNAUTHORIZED`."
        PRD 4: "| POST | /ethanol-ops/carbon-projects/{id}/review | Certify or
        return a submitted project, re-running the reduction waterfall on
        certification | PlantManager |"

        Design: Corner/rbac/exclusive_operations_refuse_every_other_role
        """
        scenario = _plant_with_an_ungraded_load_and_a_draft_project(api)

        response = api.review_carbon_project(
            scenario["project"]["id"],
            {"determination": "CERTIFY", "verified_reduction_g_per_mj": 8.0},
            COMPLIANCE_OFFICER,
        )
        validate_error(response, ApiErrorId.UNAUTHORIZED, 403)
        assert response.json()["data"]["error_id"] != ApiErrorId.INVALID_PROJECT_STATE, (
            "the authorisation failure must be reported before the state failure"
        )

        validate_error(
            api.grade_delivery(scenario["delivery"]["id"], _GRADE, GRAIN_BUYER),
            ApiErrorId.UNAUTHORIZED,
            403,
        )
        validate_error(
            api.create_hedge_position(
                {
                    "position_code": "HP-9",
                    "commodity": "ETHANOL",
                    "direction": "SHORT",
                    "contracts": 10,
                    "entry_price": 182.00,
                    "contract_month": "2026-10",
                },
                PROCESS_OPERATOR,
            ),
            ApiErrorId.UNAUTHORIZED,
            403,
        )
        validate_error(
            api.post_market_marks(
                scenario["plant"]["id"], dict(_OCTOBER_MARKS), LOGISTICS_COORDINATOR
            ),
            ApiErrorId.UNAUTHORIZED,
            403,
        )

        delivery = get_success_data(
            api.get_delivery(scenario["delivery"]["id"], SCALE_OPERATOR)
        )
        assert delivery["grading_status"] == "PENDING_GRADE", delivery["grading_status"]

        rows, meta = validate_paginated(api.list_hedge_positions(RISK_MANAGER))
        assert rows == [], rows
        assert meta["total_count"] == 0, meta["total_count"]

        plant = get_success_data(api.get_plant(scenario["plant"]["id"], PLANT_MANAGER))
        assert_null(plant["mark_corn_cents_per_bushel"], "mark_corn_cents_per_bushel")

        project = get_success_data(
            api.get_carbon_project(scenario["project"]["id"], COMPLIANCE_OFFICER)
        )
        assert project["verification_status"] == "DRAFT", project["verification_status"]


def _load_graded_by_the_scale_house(api):
    """TK-0001 graded at the scale house identity `scale-01` and awaiting settlement."""
    plant = fx.commission_plant(api, coverage_floor_bushels=5000)
    fx.advance_clock(api, "2026-09-04T06:00:00Z")
    contract = fx.priced_contract(api, 458.0, supplier_name="Cedar Ridge Elevator")
    delivery = fx.graded_load(
        api,
        contract["id"],
        delivery_overrides={"ticket_number": "TK-0001"},
        grade_overrides=dict(_GRADE),
    )
    return {"plant": plant, "contract": contract, "delivery": delivery}


class TestTheGraderMayNotSettleItsOwnLoad:
    """Settlement is keyed on the operator identifier, not on the role alone."""

    def test_the_grading_identity_is_refused_even_wearing_the_settling_role(self, api):
        """The stored grader identifier blocks settlement by that same person.

        PRD 2.1: "even though `GrainAccountant` is the authorised role for
        settlement, a settlement whose `X-User-ID` equals the delivery's stored
        `graded_by_user_id` is refused with `ERR_SEGREGATION_OF_DUTIES`."
        PRD 3.3: "The operator's `X-User-ID` is stored as `graded_by_user_id`."

        Design: Corner/rbac/the_grader_may_not_settle_its_own_load
        """
        scenario = _load_graded_by_the_scale_house(api)
        delivery = scenario["delivery"]

        assert delivery["graded_by_user_id"] == "scale-01", delivery["graded_by_user_id"]
        assert delivery["grading_status"] == "GRADED", delivery["grading_status"]

        validate_error(
            api.settle_delivery(delivery["id"], GRAIN_ACCOUNTANT_AS_GRADER),
            ApiErrorId.SEGREGATION_OF_DUTIES,
            403,
        )

        after = get_success_data(api.get_delivery(delivery["id"], SCALE_OPERATOR))
        assert after["grading_status"] == "GRADED", after["grading_status"]
        assert_null(after["settled_at"], "settled_at")
        assert_null(after["settled_by_user_id"], "settled_by_user_id")

        plant = get_success_data(api.get_plant(scenario["plant"]["id"], PLANT_MANAGER))
        assert_2dp(plant["corn_inventory_bushels"], 0.00, "corn_inventory_bushels")

    def test_the_identical_call_from_a_second_identity_settles_the_load(self, api):
        """Only the identifier differs, and that difference is what makes it legal.

        PRD 3.3: "the settling operator's `X-User-ID` must differ from the stored
        `graded_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`"
        PRD 3.3: "On success `grading_status` moves `GRADED → SETTLED`,
        `settlement_amount_cents` is computed, `settled_by_user_id` and
        `settled_at` are recorded, and the deepest cascade in the system fires."

        Design: Corner/rbac/the_grader_may_not_settle_its_own_load
        """
        scenario = _load_graded_by_the_scale_house(api)

        settled = validate_success(
            api.settle_delivery(scenario["delivery"]["id"], GRAIN_ACCOUNTANT), 200
        )

        assert settled["grading_status"] == "SETTLED", settled["grading_status"]
        assert settled["settled_by_user_id"] == "acct-01", settled["settled_by_user_id"]
        assert_2dp(settled["net_dry_bushels"], 940.00, "net_dry_bushels")
        assert settled["settlement_amount_cents"] == 413600, settled["settlement_amount_cents"]

        plant = get_success_data(api.get_plant(scenario["plant"]["id"], PLANT_MANAGER))
        assert_2dp(plant["corn_inventory_bushels"], 940.00, "corn_inventory_bushels")


class TestTheMarkPostingRightIsGenuinelyShared:
    """Two roles write the marks and a third reads the margin they drive."""

    def test_both_holders_of_the_right_post_and_the_second_post_replaces_the_first(self, api):
        """A RiskManager overwrites a PlantManager's marks wholesale on the same plant.

        PRD 4: "| POST | /ethanol-ops/plants/{id}/market-marks | Post the five
        market marks and re-price every open and partially closed hedge position |
        PlantManager, RiskManager |"
        PRD 3.1: "posting replaces the previous set wholesale rather than patching
        individual legs; the instant of the post is recorded in
        `marks_updated_at`."
        PRD 3.1: "The plant's own `version` increments as well."

        Design: Corner/rbac/shared_operations_work_for_every_holder_of_the_shared_right
        """
        plant = fx.commission_plant(api, coverage_floor_bushels=5000)
        assert plant["version"] == 1, plant["version"]
        fx.advance_clock(api, "2026-09-04T06:00:00Z")

        october = validate_success(
            api.post_market_marks(plant["id"], dict(_OCTOBER_MARKS), PLANT_MANAGER), 200
        )
        assert october["marks_effective_month"] == "2026-10", october["marks_effective_month"]
        assert_2dp(october["mark_ethanol_cents_per_gallon"], 178.00, "mark_ethanol_cents_per_gallon")

        november = validate_success(
            api.post_market_marks(plant["id"], dict(_NOVEMBER_MARKS), RISK_MANAGER), 200
        )
        assert november["marks_effective_month"] == "2026-11", november["marks_effective_month"]
        assert_2dp(november["mark_ethanol_cents_per_gallon"], 176.50, "mark_ethanol_cents_per_gallon")
        assert_2dp(november["mark_corn_cents_per_bushel"], 440.00, "mark_corn_cents_per_bushel")
        assert_2dp(november["mark_soybean_meal_usd_per_ton"], 335.00, "mark_soybean_meal_usd_per_ton")
        assert_2dp(november["mark_sbo_cents_per_lb"], 46.00, "mark_sbo_cents_per_lb")
        assert november["version"] == 3, november["version"]
        assert november["marks_updated_at"] is not None, "marks_updated_at must be recorded"

    def test_a_third_role_holding_only_the_read_right_reads_the_margin(self, api):
        """The GrainBuyer never writes the marks yet may read what they compute.

        PRD 4: "| GET | /ethanol-ops/plants/{id}/crush-margin | Compute the
        mark-to-market and realized crush margins side by side with their variant
        delta | PlantManager, RiskManager, GrainBuyer |"
        PRD 3.9: "Its distillers-grains leg takes `mark_soybean_meal_usd_per_ton`,
        applies an index of 0.92, scales by 17.0 pounds of distillers grains per
        bushel, divides by 2000 pounds per short ton and multiplies by 100 to
        reach cents."

        Design: Corner/rbac/shared_operations_work_for_every_holder_of_the_shared_right
        """
        plant = fx.commission_plant(api, coverage_floor_bushels=5000)
        fx.advance_clock(api, "2026-09-04T06:00:00Z")
        get_success_data(
            api.post_market_marks(plant["id"], dict(_OCTOBER_MARKS), PLANT_MANAGER)
        )
        get_success_data(
            api.post_market_marks(plant["id"], dict(_NOVEMBER_MARKS), RISK_MANAGER)
        )

        response = api.get_crush_margin(plant["id"], GRAIN_BUYER)
        assert response.status_code == 200, response.text
        margin = validate_success(response, 200)

        assert "mark_to_market" in margin, sorted(margin.keys())
        assert_3dp(margin["rolling_yield"], 2.850, "rolling_yield")
        assert_2dp(
            margin["mark_to_market"]["ddgs_cents_per_bushel"],
            261.97,
            "mark_to_market.ddgs_cents_per_bushel",
        )
        assert_2dp(
            margin["mark_to_market"]["corn_cost_cents_per_bushel"],
            440.00,
            "mark_to_market.corn_cost_cents_per_bushel",
        )
