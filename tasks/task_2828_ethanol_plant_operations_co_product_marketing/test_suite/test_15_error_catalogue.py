"""
The error catalogue read one code at a time.

Thirteen resources each own a not-found code, the two authentication failures
answer 401 rather than 403, and every wrong-state action reports the state error
of the resource it was aimed at rather than a shared generic conflict.
"""

from test_helpers import fixtures as fx
from test_helpers import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_2dp,
    assert_3dp,
    assert_error_envelope_shape,
    assert_null,
    ids_of,
)
from test_helpers.test_users import (
    COMPLIANCE_OFFICER,
    LOGISTICS_COORDINATOR,
    NO_HEADERS,
    PLANT_MANAGER,
    PROCESS_OPERATOR,
    ROLE_ONLY_HEADERS,
    headers_with_unknown_role,
)

_FOREIGN = "dead0000-0000-4000-8000-0000000000"


def _foreign_reads(api):
    """
    One GET per resource collection, each on a foreign UUID, paired with the
    not-found code that collection owns.  A `PlantManager` may read all
    thirteen, so authorisation never pre-empts the existence check.
    """
    return [
        ("plant", api.get_plant(f"{_FOREIGN}01", PLANT_MANAGER), ApiErrorId.PLANT_NOT_FOUND),
        ("contract", api.get_contract(f"{_FOREIGN}02", PLANT_MANAGER), ApiErrorId.CONTRACT_NOT_FOUND),
        ("delivery", api.get_delivery(f"{_FOREIGN}03", PLANT_MANAGER), ApiErrorId.DELIVERY_NOT_FOUND),
        ("batch", api.get_batch(f"{_FOREIGN}04", PLANT_MANAGER), ApiErrorId.BATCH_NOT_FOUND),
        ("tank", api.get_tank(f"{_FOREIGN}05", PLANT_MANAGER), ApiErrorId.TANK_NOT_FOUND),
        ("blend", api.get_blend(f"{_FOREIGN}06", PLANT_MANAGER), ApiErrorId.BLEND_NOT_FOUND),
        ("track", api.get_track(f"{_FOREIGN}07", PLANT_MANAGER), ApiErrorId.TRACK_NOT_FOUND),
        ("shipment", api.get_shipment(f"{_FOREIGN}08", PLANT_MANAGER), ApiErrorId.SHIPMENT_NOT_FOUND),
        ("sale", api.get_sale(f"{_FOREIGN}09", PLANT_MANAGER), ApiErrorId.SALE_NOT_FOUND),
        ("rin_batch", api.get_rin_batch(f"{_FOREIGN}0a", PLANT_MANAGER), ApiErrorId.RIN_BATCH_NOT_FOUND),
        ("carbon_project", api.get_carbon_project(f"{_FOREIGN}0b", PLANT_MANAGER), ApiErrorId.CARBON_PROJECT_NOT_FOUND),
        ("hedge_position", api.get_hedge_position(f"{_FOREIGN}0c", PLANT_MANAGER), ApiErrorId.HEDGE_POSITION_NOT_FOUND),
        ("permit_condition", api.get_permit_condition(f"{_FOREIGN}0d", PLANT_MANAGER), ApiErrorId.PERMIT_CONDITION_NOT_FOUND),
    ]


class TestEveryCollectionOwnsItsNotFoundCode:
    """Thirteen collections, thirteen codes, one shared foreign identifier shape."""

    def test_each_foreign_read_reports_the_code_of_the_collection_it_was_aimed_at(self, api):
        """No collection borrows another's code and none falls back on a generic 404.

        PRD 2.5: "Each entity has its own not-found code, and they are checked in
        a fixed order: plant (`ERR_PLANT_NOT_FOUND`), corn purchase contract
        (`ERR_CONTRACT_NOT_FOUND`), corn delivery (`ERR_DELIVERY_NOT_FOUND`),
        fermentation batch (`ERR_BATCH_NOT_FOUND`), product tank
        (`ERR_TANK_NOT_FOUND`), denaturant blend (`ERR_BLEND_NOT_FOUND`), loading
        track (`ERR_TRACK_NOT_FOUND`), unit train shipment
        (`ERR_SHIPMENT_NOT_FOUND`), co-product sale (`ERR_SALE_NOT_FOUND`), RIN
        batch (`ERR_RIN_BATCH_NOT_FOUND`), carbon project
        (`ERR_CARBON_PROJECT_NOT_FOUND`), hedge position
        (`ERR_HEDGE_POSITION_NOT_FOUND`) and permit condition
        (`ERR_PERMIT_CONDITION_NOT_FOUND`)."

        Design: Corner/errors/every_resource_has_its_own_not_found_code
        """
        reads = _foreign_reads(api)
        assert len(reads) == 13, len(reads)

        observed = {}
        for label, response, expected in reads:
            body = response.json()
            observed[label] = body.get("data", {}).get("error_id")
            assert observed[label] == expected, (
                f"{label}: expected {expected}, got {observed[label]}"
            )

        assert len(set(observed.values())) == 13, observed

    def test_every_foreign_read_answers_404_in_the_error_envelope(self, api):
        """A missing row is a 404 carrying the standard error envelope, never a 422.

        PRD 5: "| `ERR_PLANT_NOT_FOUND` | 404 |"
        PRD 2.2: "All error API responses (4xx status codes) follow this standard
        envelope format:"

        Design: Corner/errors/every_resource_has_its_own_not_found_code
        """
        for label, response, expected in _foreign_reads(api):
            assert response.status_code == 404, (
                f"{label}: expected HTTP 404, got {response.status_code}"
            )
            body = response.json()
            assert body["response_type"] == "error", f"{label}: {body['response_type']}"
            assert_error_envelope_shape(body)
            assert body["data"]["error_id"] == expected, f"{label}: {body['data']}"
            assert body["data"]["error_id"] != ApiErrorId.VALIDATION, label


class TestBothAuthenticationFailuresAnswer401:
    """Absent credentials and an unrecognised role are authentication, not authorisation."""

    def test_absent_headers_and_an_absent_user_id_are_both_missing_auth_headers(self, api):
        """The user identifier is as mandatory as the role, and its absence reads the same.

        PRD 2.1: "Every request to every endpoint must carry two headers:
        `X-User-ID`, identifying the human or service account making the call,
        and `X-User-Role`, naming the operating role that call is being made
        under. If either header is absent or empty, the request fails with
        `ERR_MISSING_AUTH_HEADERS`."

        Design: Corner/errors/missing_auth_headers_and_unknown_role_are_rejected_at_401
        """
        plant = fx.commission_plant(api)

        validate_error(
            api.get_plant(plant["id"], NO_HEADERS),
            ApiErrorId.MISSING_AUTH_HEADERS,
            401,
        )
        validate_error(
            api.get_plant(plant["id"], ROLE_ONLY_HEADERS),
            ApiErrorId.MISSING_AUTH_HEADERS,
            401,
        )

    def test_an_unrecognised_role_is_401_and_a_recognised_one_reads_the_plant(self, api):
        """An unknown role fails authentication at 401 rather than authorisation at 403.

        PRD 2.1: "If `X-User-Role` carries a string that is not one of the eight
        roles below, the request fails with `ERR_INVALID_ROLE`."
        PRD 5: "| `ERR_INVALID_ROLE` | 401 |"

        Design: Corner/errors/missing_auth_headers_and_unknown_role_are_rejected_at_401
        """
        plant = fx.commission_plant(api)

        response = api.get_plant(plant["id"], headers_with_unknown_role("EthanolTsar"))
        validate_error(response, ApiErrorId.INVALID_ROLE, 401)
        assert response.status_code != 403, "an unknown role is not ERR_UNAUTHORIZED 403"

        read = validate_success(api.get_plant(plant["id"], PLANT_MANAGER), 200)
        assert read["id"] == plant["id"], read["id"]


def _in_service_tank(api):
    """T-301 commissioned and never held, so it is `IN_SERVICE` with no hold."""
    fx.commission_plant(api)
    fx.advance_clock(api, "2026-09-04T06:00:00Z")
    return fx.commission_tank(
        api, "T-301", "DENATURED_E100", 1000000.00, opening_gallons=400000.00
    )


def _loaded_but_undocumented_train(api):
    """
    SH-1 loaded with ten railcars, so the loading dimension is `LOADED` while the
    billing dimension is still `PENDING_BOL`.
    """
    fx.commission_plant(api)
    fx.advance_clock(api, "2026-09-04T06:00:00Z")
    tank = fx.commission_tank(
        api, "T-301", "DENATURED_E100", 1000000.00, opening_gallons=400000.00
    )
    track = fx.commission_track(api)
    shipment = fx.loaded_shipment(
        api,
        track["id"],
        tank["id"],
        track["version"],
        railcar_count=10,
        gallons_per_railcar=2659.00,
        window_start="2026-09-04T06:00:00Z",
        window_end="2026-09-04T12:00:00Z",
        price_cents_per_gallon=181.50,
    )
    return {"tank": tank, "track": track, "shipment": shipment}


def _draft_project(api):
    """CP-1 registered and left at `DRAFT`, never submitted for verification."""
    fx.commission_plant(api)
    fx.advance_clock(api, "2026-09-04T06:00:00Z")
    return fx.draft_project(
        api,
        project_code="CP-1",
        project_type="COMBINED_HEAT_POWER",
        claimed_reduction_g_per_mj=8.0,
    )


class TestWrongStateActionsReportTheirOwnResourceStateError:
    """Each refusal names the resource whose state blocked it."""

    def test_releasing_a_tank_that_was_never_held_is_an_invalid_tank_state(self, api):
        """Release is for a held tank, so a serving tank refuses it and keeps serving.

        PRD 3.5: "Releasing a hold requires the tank to be `ON_HOLD` or
        `OUT_OF_SERVICE` — releasing a tank already `IN_SERVICE` is refused with
        `ERR_INVALID_TANK_STATE` — and takes no body."

        Design: Corner/errors/wrong_state_actions_return_the_resource_specific_state_error
        """
        tank = _in_service_tank(api)
        assert tank["service_status"] == "IN_SERVICE", tank["service_status"]

        validate_error(
            api.release_tank(tank["id"], PROCESS_OPERATOR),
            ApiErrorId.INVALID_TANK_STATE,
            409,
        )

        after = get_success_data(api.get_tank(tank["id"], PROCESS_OPERATOR))
        assert after["service_status"] == "IN_SERVICE", after["service_status"]
        assert_null(after["hold_reason"], "hold_reason")
        assert after["version"] == 1, after["version"]

    def test_invoicing_before_the_bill_of_lading_is_an_invalid_billing_state(self, api):
        """The refusal names the billing dimension, not the already-invoiced lock.

        PRD 3.6: "Invoicing moves the billing dimension `BOL_ISSUED → INVOICED`
        and takes no body; any other billing state is refused with
        `ERR_INVALID_SHIPMENT_BILLING_STATE`."

        Design: Corner/errors/wrong_state_actions_return_the_resource_specific_state_error
        """
        scenario = _loaded_but_undocumented_train(api)
        shipment = scenario["shipment"]
        assert shipment["loading_status"] == "LOADED", shipment["loading_status"]
        assert shipment["billing_status"] == "PENDING_BOL", shipment["billing_status"]

        response = api.invoice_shipment(shipment["id"], LOGISTICS_COORDINATOR)
        validate_error(response, ApiErrorId.INVALID_SHIPMENT_BILLING_STATE, 409)
        assert response.json()["data"]["error_id"] != ApiErrorId.SHIPMENT_ALREADY_INVOICED

        after = get_success_data(api.get_shipment(shipment["id"], LOGISTICS_COORDINATOR))
        assert after["billing_status"] == "PENDING_BOL", after["billing_status"]
        assert after["loading_status"] == "LOADED", after["loading_status"]
        assert_null(after["invoice_amount_cents"], "invoice_amount_cents")
        assert_2dp(after["loaded_gallons"], 26590.00, "loaded_gallons")

    def test_reviewing_a_draft_project_is_an_invalid_project_state(self, api):
        """A determination may only be made on a submitted project, so a draft refuses it.

        PRD 3.8: "The project must be `SUBMITTED`, otherwise
        `ERR_INVALID_PROJECT_STATE`."

        Design: Corner/errors/wrong_state_actions_return_the_resource_specific_state_error
        """
        project = _draft_project(api)
        assert project["verification_status"] == "DRAFT", project["verification_status"]

        validate_error(
            api.review_carbon_project(
                project["id"],
                {"determination": "CERTIFY", "verified_reduction_g_per_mj": 8.0},
                PLANT_MANAGER,
            ),
            ApiErrorId.INVALID_PROJECT_STATE,
            409,
        )

        after = get_success_data(api.get_carbon_project(project["id"], COMPLIANCE_OFFICER))
        assert after["verification_status"] == "DRAFT", after["verification_status"]
        assert_null(after["verified_reduction_g_per_mj"], "verified_reduction_g_per_mj")


def _credits_minted_but_never_separated(api):
    """
    FB-1 grinds 940.00 bushels at the 54.0 pound basis with one clean reading, so
    the yield freezes at the 2.850 base and completion mints a single credit
    batch that no bill of lading has yet separated.
    """
    plant = fx.commission_plant(api)
    fx.advance_clock(api, "2026-09-05T00:00:00Z")
    tank = fx.commission_tank(
        api, "T-101", "ETHANOL_200_PROOF", 1000000.00, opening_gallons=0.00
    )
    contract = fx.priced_contract(api, 458.0)
    fx.settled_load(api, contract["id"])
    batch = fx.completed_batch(
        api,
        tank["id"],
        batch_code="FB-1",
        corn_bushels_charged=940.00,
        charge_test_weight_lb_per_bu=54.0,
    )
    rows, _ = validate_paginated(
        api.list_rin_batches(COMPLIANCE_OFFICER, {"fermentation_batch_id": batch["id"]})
    )
    return {"plant": plant, "batch": batch, "rin_rows": rows}


class TestRetiringUnseparatedCreditsIsRefused:
    """Retirement is reachable only from SEPARATED, so a freshly minted credit refuses it."""

    def test_completion_mints_one_generated_credit_batch_over_the_grossed_up_gallons(self, api):
        """The tradeable count is the floor of the denaturant-grossed eligible gallons.

        PRD 3.4: "`ethanol_gallons_produced` is `corn_bushels_charged` multiplied
        by `effective_yield_gal_per_bushel`, rounded half up to two decimals"
        PRD 3.8: "`rin_eligible_gallons` is the batch's
        `ethanol_gallons_produced` multiplied by a denaturant gross-up of 1.02 and
        by a D6 equivalence value of 1.0, rounded half up to two decimals. The
        tradeable count, `rin_count`, is then the **floor** of that
        eligible-gallons figure and never a rounding"

        Design: Corner/errors/retirement_of_a_generated_but_unseparated_rin_batch_rejected
        """
        scenario = _credits_minted_but_never_separated(api)
        batch = scenario["batch"]

        assert_2dp(batch["fermentation_health_index"], 100.00, "fermentation_health_index")
        assert_3dp(batch["effective_yield_gal_per_bushel"], 2.850, "effective_yield_gal_per_bushel")
        assert_2dp(batch["ethanol_gallons_produced"], 2679.00, "ethanol_gallons_produced")
        assert_3dp(batch["ddgs_tons_produced"], 7.990, "ddgs_tons_produced")
        assert_2dp(batch["corn_oil_lbs_produced"], 564.00, "corn_oil_lbs_produced")

        assert len(scenario["rin_rows"]) == 1, scenario["rin_rows"]
        credit = scenario["rin_rows"][0]
        assert credit["status"] == "GENERATED", credit["status"]
        assert credit["d_code"] == 6, credit["d_code"]
        assert credit["rin_year"] == 2026, credit["rin_year"]
        assert credit["fermentation_batch_id"] == batch["id"], credit["fermentation_batch_id"]
        assert_2dp(credit["rin_eligible_gallons"], 2732.58, "rin_eligible_gallons")
        assert credit["rin_count"] == 2732, credit["rin_count"]

    def test_retiring_a_generated_credit_batch_is_an_invalid_rin_state(self, api):
        """The state check fires first, so the absent invoice is never even reached.

        PRD 3.8: "The batch must be at `SEPARATED`, otherwise
        `ERR_INVALID_RIN_STATE`, and the shipment that separated it must have
        reached `billing_status` `INVOICED`, otherwise
        `ERR_SHIPMENT_NOT_INVOICED`"
        PRD 3.8: "`rin_generated_count` sums `rin_count` across `GENERATED`,
        `SEPARATED` and `RETIRED` batches; `rin_separated_count` sums across
        `SEPARATED` and `RETIRED`; and `rin_retired_count` sums across `RETIRED`
        alone."

        Design: Corner/errors/retirement_of_a_generated_but_unseparated_rin_batch_rejected
        """
        scenario = _credits_minted_but_never_separated(api)
        credit = scenario["rin_rows"][0]

        response = api.retire_rin_batch(
            credit["id"], {"retirement_reference": "EMTS-2026-0001"}, COMPLIANCE_OFFICER
        )
        validate_error(response, ApiErrorId.INVALID_RIN_STATE, 409)
        assert response.json()["data"]["error_id"] != ApiErrorId.SHIPMENT_NOT_INVOICED

        after = get_success_data(api.get_rin_batch(credit["id"], COMPLIANCE_OFFICER))
        assert after["status"] == "GENERATED", after["status"]
        assert_null(after["retired_at"], "retired_at")
        assert_null(after["separated_shipment_id"], "separated_shipment_id")

        plant = get_success_data(api.get_plant(scenario["plant"]["id"], PLANT_MANAGER))
        assert plant["rin_generated_count"] == 2732, plant["rin_generated_count"]
        assert plant["rin_separated_count"] == 0, plant["rin_separated_count"]
        assert plant["rin_retired_count"] == 0, plant["rin_retired_count"]


def _stack_resting_on_a_draft_foundation(api):
    """CP-2 registered against CP-1 while CP-1 is still an unsubmitted draft."""
    fx.commission_plant(api)
    fx.advance_clock(api, "2026-09-04T06:00:00Z")
    foundation = fx.draft_project(
        api,
        project_code="CP-1",
        project_type="CARBON_CAPTURE",
        claimed_reduction_g_per_mj=8.0,
    )
    stacked = fx.draft_project(
        api,
        project_code="CP-2",
        project_type="COMBINED_HEAT_POWER",
        claimed_reduction_g_per_mj=2.5,
        predecessor_project_id=foundation["id"],
    )
    return {"foundation": foundation, "stacked": stacked}


class TestAStackedClaimWaitsForItsFoundation:
    """Registration accepts the stack; submission is where the foundation is checked."""

    def test_registration_stamps_the_predecessor_and_the_filter_finds_the_stacked_row(self, api):
        """A draft predecessor is a legal reference, so the stacked project registers.

        PRD 2.5: "a `predecessor_project_id` in a create body or a filter yields
        `ERR_CARBON_PROJECT_NOT_FOUND`"
        PRD 3.8: "A project opens at `verification_status` `DRAFT` with
        `revision_count` at 0."

        Design: Corner/errors/submission_with_an_uncertified_predecessor_rejected
        """
        scenario = _stack_resting_on_a_draft_foundation(api)
        stacked = scenario["stacked"]

        assert stacked["predecessor_project_id"] == scenario["foundation"]["id"], (
            stacked["predecessor_project_id"]
        )
        assert stacked["verification_status"] == "DRAFT", stacked["verification_status"]
        assert stacked["revision_count"] == 0, stacked["revision_count"]
        assert_null(stacked["submitted_at"], "submitted_at")

        rows, _ = validate_paginated(
            api.list_carbon_projects(
                COMPLIANCE_OFFICER,
                {"predecessor_project_id": scenario["foundation"]["id"]},
            )
        )
        assert ids_of(rows) == [stacked["id"]], ids_of(rows)

    def test_submitting_over_an_uncertified_predecessor_is_refused(self, api):
        """The audit cannot begin until the claim it rests on has been certified.

        PRD 3.8: "Where a `predecessor_project_id` is set, that predecessor must
        itself have reached `CERTIFIED`, otherwise
        `ERR_PREDECESSOR_NOT_CERTIFIED` — a stacked claim cannot be audited
        before the foundation it rests on has been."

        Design: Corner/errors/submission_with_an_uncertified_predecessor_rejected
        """
        scenario = _stack_resting_on_a_draft_foundation(api)

        validate_error(
            api.submit_carbon_project(
                scenario["stacked"]["id"],
                {"verification_body": "Verra Assurance"},
                COMPLIANCE_OFFICER,
            ),
            ApiErrorId.PREDECESSOR_NOT_CERTIFIED,
            422,
        )

        after = get_success_data(
            api.get_carbon_project(scenario["stacked"]["id"], COMPLIANCE_OFFICER)
        )
        assert after["verification_status"] == "DRAFT", after["verification_status"]
        assert_null(after["verification_body"], "verification_body")
        assert_null(after["submitted_at"], "submitted_at")

        foundation = get_success_data(
            api.get_carbon_project(scenario["foundation"]["id"], COMPLIANCE_OFFICER)
        )
        assert foundation["verification_status"] == "DRAFT", foundation["verification_status"]


class TestTheCrushMarginNeedsAllFiveMarks:
    """A fresh plant carries no marks, so the margin cannot be computed at all."""

    def test_the_margin_read_is_refused_while_the_marks_are_null(self, api):
        """Every mark starts null, and the read is refused rather than reported as zero.

        PRD 3.1: "All five are null on a fresh plant, and posting replaces the
        previous set wholesale rather than patching individual legs"
        PRD 3.9: "Reading the margin requires that the marks be readable: all
        five of `mark_corn_cents_per_bushel`, `mark_ethanol_cents_per_gallon`,
        `mark_natgas_cents_per_mmbtu`, `mark_soybean_meal_usd_per_ton` and
        `mark_sbo_cents_per_lb` must have been posted, otherwise the read is
        refused with `ERR_MARKS_NOT_POSTED`."

        Design: Corner/errors/crush_margin_read_before_any_marks_are_posted_rejected
        """
        plant = fx.commission_plant(api)

        assert_null(plant["mark_corn_cents_per_bushel"], "mark_corn_cents_per_bushel")
        assert_null(plant["mark_ethanol_cents_per_gallon"], "mark_ethanol_cents_per_gallon")
        assert_null(plant["mark_natgas_cents_per_mmbtu"], "mark_natgas_cents_per_mmbtu")
        assert_null(plant["mark_soybean_meal_usd_per_ton"], "mark_soybean_meal_usd_per_ton")
        assert_null(plant["mark_sbo_cents_per_lb"], "mark_sbo_cents_per_lb")
        assert_null(plant["marks_updated_at"], "marks_updated_at")

        validate_error(
            api.get_crush_margin(plant["id"], PLANT_MANAGER),
            ApiErrorId.MARKS_NOT_POSTED,
            422,
        )

    def test_posting_the_marks_makes_the_same_read_succeed(self, api):
        """With the marks on file the forward view computes and the backward view zeroes.

        PRD 3.9: "The `MARK_TO_MARKET` variant values everything at posted marks
        and is always returned, being the only view available before any batch has
        completed or any shipment has been invoiced."
        PRD 3.9: "Where the bushels ground are 0, or any required mark has never
        been posted, every `REALIZED` leg is reported as 0.00."

        Design: Corner/errors/crush_margin_read_before_any_marks_are_posted_rejected
        """
        plant = fx.commission_plant(api)
        fx.advance_clock(api, "2026-09-04T06:00:00Z")
        fx.post_marks(api, plant["id"], PLANT_MANAGER)

        margin = validate_success(api.get_crush_margin(plant["id"], PLANT_MANAGER), 200)

        assert_3dp(margin["rolling_yield"], 2.850, "rolling_yield")
        mtm = margin["mark_to_market"]
        assert_2dp(mtm["ethanol_cents_per_bushel"], 507.30, "mark_to_market.ethanol_cents_per_bushel")
        assert_2dp(mtm["ddgs_cents_per_bushel"], 258.06, "mark_to_market.ddgs_cents_per_bushel")
        assert_2dp(mtm["corn_oil_cents_per_bushel"], 22.46, "mark_to_market.corn_oil_cents_per_bushel")
        assert_2dp(mtm["gross_cents_per_bushel"], 787.82, "mark_to_market.gross_cents_per_bushel")
        assert_2dp(mtm["corn_cost_cents_per_bushel"], 440.00, "mark_to_market.corn_cost_cents_per_bushel")
        assert_2dp(mtm["net_cents_per_bushel"], 294.06, "mark_to_market.net_cents_per_bushel")

        realized = margin["realized"]
        assert_2dp(realized["ethanol_cents_per_bushel"], 0.00, "realized.ethanol_cents_per_bushel")
        assert_2dp(realized["coproduct_cents_per_bushel"], 0.00, "realized.coproduct_cents_per_bushel")
        assert_2dp(realized["corn_cost_cents_per_bushel"], 0.00, "realized.corn_cost_cents_per_bushel")
        assert_2dp(realized["net_cents_per_bushel"], 0.00, "realized.net_cents_per_bushel")
        assert_2dp(margin["variant_delta_cents_per_bushel"], -294.06, "variant_delta_cents_per_bushel")


def _blend_aimed_at_a_full_tank(api):
    """
    BL-1 is on specification at 2565.00 neat plus 60.00 denaturant, but T-302 is a
    2000.00 gallon day tank, so its headroom is smaller than the 2625.00 gallons
    the blend would land.
    """
    fx.commission_plant(api)
    fx.advance_clock(api, "2026-09-04T06:00:00Z")
    neat = fx.commission_tank(
        api, "T-101", "ETHANOL_200_PROOF", 1000000.00, opening_gallons=500000.00
    )
    denaturant = fx.commission_tank(
        api, "T-201", "DENATURANT", 1000000.00, opening_gallons=500000.00
    )
    destination = fx.commission_tank(
        api, "T-302", "DENATURED_E100", 2000.00, opening_gallons=0.00
    )
    blend = fx.schedule_blend(
        api, neat["id"], denaturant["id"], destination["id"], destination["version"]
    )
    return {
        "neat": neat,
        "denaturant": denaturant,
        "destination": destination,
        "blend": blend,
    }


class TestABlendMayNotOverfillItsDestination:
    """Scheduling reserves nothing, so the headroom is only checked at execution."""

    def test_the_blend_schedules_against_a_tank_with_too_little_headroom(self, api):
        """A scheduled blend moves nothing, so the small destination accepts the plan.

        PRD 3.5: "`available_gallons` is `capacity_gallons` less
        `current_gallons`, floored at 0.00, and both figures carry two decimals."
        PRD 3.5: "Only terminal, effective movements count — a scheduled blend
        moves nothing"

        Design: Corner/errors/blend_execution_into_a_tank_without_room_rejected
        """
        scenario = _blend_aimed_at_a_full_tank(api)
        blend = scenario["blend"]

        assert blend["status"] == "SCHEDULED", blend["status"]
        assert_null(blend["output_gallons"], "output_gallons")
        assert_null(blend["executed_at"], "executed_at")

        destination = get_success_data(
            api.get_tank(scenario["destination"]["id"], PROCESS_OPERATOR)
        )
        assert_2dp(destination["capacity_gallons"], 2000.00, "capacity_gallons")
        assert_2dp(destination["current_gallons"], 0.00, "current_gallons")
        assert_2dp(destination["available_gallons"], 2000.00, "available_gallons")

    def test_executing_it_is_refused_for_capacity_and_moves_no_liquid(self, api):
        """The on-spec blend clears the specification check and then fails on headroom.

        PRD 3.5: "and the destination's `available_gallons` must be at least the
        combined output, otherwise `ERR_INSUFFICIENT_TANK_CAPACITY`."

        Design: Corner/errors/blend_execution_into_a_tank_without_room_rejected
        """
        scenario = _blend_aimed_at_a_full_tank(api)

        validate_error(
            api.execute_blend(scenario["blend"]["id"], PROCESS_OPERATOR),
            ApiErrorId.INSUFFICIENT_TANK_CAPACITY,
            422,
        )

        blend = get_success_data(api.get_blend(scenario["blend"]["id"], PROCESS_OPERATOR))
        assert blend["status"] == "SCHEDULED", blend["status"]
        assert_null(blend["output_gallons"], "output_gallons")
        assert_null(blend["executed_at"], "executed_at")

        neat = get_success_data(api.get_tank(scenario["neat"]["id"], PROCESS_OPERATOR))
        denaturant = get_success_data(
            api.get_tank(scenario["denaturant"]["id"], PROCESS_OPERATOR)
        )
        destination = get_success_data(
            api.get_tank(scenario["destination"]["id"], PROCESS_OPERATOR)
        )
        assert_2dp(neat["current_gallons"], 500000.00, "neat current_gallons")
        assert_2dp(denaturant["current_gallons"], 500000.00, "denaturant current_gallons")
        assert_2dp(destination["current_gallons"], 0.00, "destination current_gallons")
