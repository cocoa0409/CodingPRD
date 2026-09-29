"""Refusals: the shape they take, the family they name, and who provokes them.

Every rejection in this service answers three questions at once - what envelope
came back, which entity family owns the identifier, and which of several
competing rules was allowed to speak first. These tests drive heterogeneous
refusals through one plant and read the answers: a uniform error body across six
different failure kinds, an entity-specific code for each of the fourteen
single-resource reads and each of the eleven state families, and a role gate that
runs ahead of both the version pin and the state check.
"""

import pytest

from types import SimpleNamespace

from test_helpers import (
    adhesion_inspection_payload,
    approve_payload,
    approx2,
    approx4,
    assert_error_envelope,
    certification_approver_headers,
    certification_payload,
    CLOCK_AFTER_ALL_WINDOWS,
    compliance_engineer_headers,
    component_lot_payload,
    data_of,
    ERR_COMPONENT_LOT_NOT_FOUND,
    ERR_DUPLICATE_CODE,
    ERR_EFFICIENCY_TEST_NOT_FOUND,
    ERR_FORBIDDEN_ROLE,
    ERR_FURNACE_NOT_FOUND,
    ERR_GLASS_LINING_BATCH_NOT_FOUND,
    ERR_HEATER_UNIT_NOT_FOUND,
    ERR_INVALID_BATCH_STATE,
    ERR_INVALID_CAMPAIGN_STATE,
    ERR_INVALID_CERTIFICATION_STATE,
    ERR_INVALID_CLAIM_STATE,
    ERR_INVALID_COMPONENT_LOT_STATE,
    ERR_INVALID_MODEL_STATE,
    ERR_INVALID_NOTICE_STATE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_SUPPLIER_STATE,
    ERR_INVALID_TANK_LOT_STATE,
    ERR_INVALID_TEST_STATE,
    ERR_INVALID_UNIT_STATE,
    ERR_LINING_INSPECTION_NOT_FOUND,
    ERR_PRODUCT_MODEL_NOT_FOUND,
    ERR_RATING_CERTIFICATION_NOT_FOUND,
    ERR_RECALL_CAMPAIGN_NOT_FOUND,
    ERR_RECALL_NOTICE_NOT_FOUND,
    ERR_SOD_APPROVER_IS_SUBMITTER,
    ERR_STALE_PARENT_VERSION,
    ERR_SUPPLIER_NOT_FOUND,
    ERR_SUPPLIER_SCOPE_VIOLATION,
    ERR_SUPPLIER_SCORE_BELOW_FLOOR,
    ERR_TANK_LOT_NOT_FOUND,
    ERR_TEST_CELL_NOT_FOUND,
    ERR_WARRANTY_CLAIM_NOT_FOUND,
    furnace_payload,
    heater_unit_payload,
    make_supplier_rep_headers,
    NON_EXISTENT_UUID,
    plant_admin_headers,
    plant_operator_headers,
    product_model_payload,
    qualify_payload,
    quality_inspector_headers,
    reason_payload,
    recall_campaign_payload,
    supplier_quality_headers,
    tank_lot_payload,
    USER_APPROVER,
    USER_ENGINEER,
    validate_error,
    validate_paginated,
    validate_success,
    warranty_analyst_headers,
    warranty_claim_payload,
    fixtures as x,
)

#: The one serial the plant's first unit is labelled with.
FIRST_SERIAL = "GX50-T-202608-00001"
#: A pin that is stale by several accepted writes on any lot the plant builds.
LONG_STALE_PIN = 1


def _a_released_model_and_an_unqualifiable_supplier(api):
    """One catalogue model already in channel, plus a supplier that cannot score.

    The version captured here is the one the model carried before the channel
    release incremented it, so a certification pinned to it is stale by one write.
    """
    model = x.make_model(api)
    stale_version = x.model_version(api, model["id"])
    data_of(api.release_model_to_channel(model["id"], compliance_engineer_headers()))
    weak = x.make_pending_supplier(
        api,
        name="Fringe Valves",
        component_category="ANODE",
        audit_score=60,
        defect_ppm=4000,
        open_capa_count=3,
    )
    return SimpleNamespace(
        model_id=model["id"], stale_version=stale_version, supplier_id=weak["id"]
    )


def _six_refusals_of_six_different_kinds(api, ground):
    """Provoke one rejection at each of six admission stages, in order."""
    return [
        (
            ERR_SUPPLIER_NOT_FOUND,
            404,
            api.get_supplier(NON_EXISTENT_UUID, supplier_quality_headers()),
        ),
        (
            ERR_INVALID_REQUEST,
            400,
            api.create_product_model(
                {
                    key: value
                    for key, value in product_model_payload().items()
                    if key != "model_code"
                },
                compliance_engineer_headers(),
            ),
        ),
        (
            ERR_INVALID_REQUEST,
            400,
            api.create_product_model(
                product_model_payload(
                    model_code="SX40-E",
                    fuel_type="STEAM",
                    nominal_capacity_gallons=40,
                ),
                compliance_engineer_headers(),
            ),
        ),
        (
            ERR_DUPLICATE_CODE,
            409,
            api.create_product_model(
                product_model_payload(
                    fuel_type="ELECTRIC",
                    nominal_capacity_gallons=40,
                    channel="RETAIL",
                    insulation_r_value=18,
                ),
                compliance_engineer_headers(),
            ),
        ),
        (
            ERR_STALE_PARENT_VERSION,
            412,
            api.create_certification(
                certification_payload(ground.model_id, ground.stale_version),
                compliance_engineer_headers(),
            ),
        ),
        (
            ERR_SUPPLIER_SCORE_BELOW_FLOOR,
            422,
            api.qualify_supplier(
                ground.supplier_id,
                qualify_payload(audit_score=60, defect_ppm=4000, open_capa_count=3),
                supplier_quality_headers(),
            ),
        ),
    ]


class TestErrorEnvelopeUniformity:
    """Six unrelated failure kinds, one envelope."""

    def test_01_every_refusal_returns_the_same_two_field_meta(self, api):
        """A 404, two 400s, a 409, a 412 and a 422 are indistinguishable in shape.

        PRD: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        Design: Corner/errors/error_envelope_shape_is_uniform_whenever_a_call_is_rejected
        """
        ground = _a_released_model_and_an_unqualifiable_supplier(api)

        refusals = _six_refusals_of_six_different_kinds(api, ground)

        assert len(refusals) == 6
        for error_id, _status, response in refusals:
            assert_error_envelope(response, error_id)

    def test_02_each_refusal_names_its_own_identifier_and_status(self, api):
        """The identifier moves with the rule that fired, not with the endpoint.

        PRD: "The `error_id` is a unique, machine-readable string that identifies
        the specific error."

        Design: Corner/errors/error_envelope_shape_is_uniform_whenever_a_call_is_rejected
        """
        ground = _a_released_model_and_an_unqualifiable_supplier(api)

        refusals = _six_refusals_of_six_different_kinds(api, ground)

        seen = []
        for error_id, status, response in refusals:
            validate_error(response, error_id, expected_status=status)
            seen.append(error_id)
        assert seen == [
            ERR_SUPPLIER_NOT_FOUND,
            ERR_INVALID_REQUEST,
            ERR_INVALID_REQUEST,
            ERR_DUPLICATE_CODE,
            ERR_STALE_PARENT_VERSION,
            ERR_SUPPLIER_SCORE_BELOW_FLOOR,
        ]

    def test_03_no_refused_write_left_a_row_or_a_score_behind(self, api):
        """Two refused model creates and a refused scoring persisted nothing.

        PRD: "A newly registered supplier begins at `qualification_status`
        `PENDING` with no `qualification_score`, no `qualified_until` and no
        `disqualification_reason_code`."

        Design: Corner/errors/error_envelope_shape_is_uniform_whenever_a_call_is_rejected
        """
        ground = _a_released_model_and_an_unqualifiable_supplier(api)
        _six_refusals_of_six_different_kinds(api, ground)

        listing = api.list_product_models(
            compliance_engineer_headers(), {"limit": 100, "offset": 0}
        )
        rows, _meta = validate_paginated(listing)
        supplier = validate_success(
            api.get_supplier(ground.supplier_id, supplier_quality_headers())
        )

        assert listing.json()["response_type"] == "array"
        assert len(rows) == 1
        assert rows[0]["id"] == ground.model_id
        assert supplier["qualification_status"] == "PENDING"
        assert supplier["qualification_score"] is None


def _a_plant_with_a_claim_and_two_campaigns(api):
    """One shipped unit carrying an open claim, one draft campaign, one announced.

    The announced campaign is scoped to the single serial the plant produced, so
    its fan-out leaves exactly one notice sitting in `PENDING`.
    """
    plant = x.make_full_plant(api)
    unit_id = x.ship_unit(api, plant)
    claim = data_of(
        api.create_warranty_claim(
            warranty_claim_payload(unit_id), warranty_analyst_headers()
        )
    )
    draft = data_of(
        api.create_recall_campaign(
            recall_campaign_payload(plant.model_id, campaign_code="RC-A"),
            warranty_analyst_headers(),
        )
    )
    announced = x.make_announced_campaign(
        api, plant.model_id, FIRST_SERIAL, FIRST_SERIAL, campaign_code="RC-B"
    )
    notices = x.campaign_notices(api, announced["id"])
    return SimpleNamespace(
        plant=plant,
        unit_id=unit_id,
        claim_id=claim["id"],
        draft_campaign_id=draft["id"],
        announced_campaign_id=announced["id"],
        notice_id=notices[0]["id"],
    )


def _eleven_refusals_across_eleven_state_families(api, ground):
    """One refused transition per state-machine family, all on settled rows."""
    plant = ground.plant
    return [
        (
            ERR_INVALID_SUPPLIER_STATE,
            api.qualify_supplier(
                plant.gas_supplier_id, qualify_payload(), supplier_quality_headers()
            ),
        ),
        (
            ERR_INVALID_COMPONENT_LOT_STATE,
            api.release_component_lot(plant.gas_lot_id, quality_inspector_headers()),
        ),
        (
            ERR_INVALID_BATCH_STATE,
            api.fire_lining_batch(plant.batch_id, plant_operator_headers()),
        ),
        (
            ERR_INVALID_TANK_LOT_STATE,
            api.weld_tank_lot(plant.tank_lot_id, plant_operator_headers()),
        ),
        (
            ERR_INVALID_MODEL_STATE,
            api.release_model_to_channel(plant.model_id, compliance_engineer_headers()),
        ),
        (
            ERR_INVALID_TEST_STATE,
            api.record_test_result(
                plant.uef_test_ids[0],
                {"measured_value": 0.59},
                quality_inspector_headers(),
            ),
        ),
        (
            ERR_INVALID_CERTIFICATION_STATE,
            api.submit_certification(plant.cert_id, compliance_engineer_headers()),
        ),
        (
            ERR_INVALID_UNIT_STATE,
            api.assemble_unit(ground.unit_id, plant_operator_headers()),
        ),
        (
            ERR_INVALID_CLAIM_STATE,
            api.pay_claim(ground.claim_id, warranty_analyst_headers()),
        ),
        (
            ERR_INVALID_CAMPAIGN_STATE,
            api.announce_campaign(
                ground.draft_campaign_id, warranty_analyst_headers()
            ),
        ),
        (
            ERR_INVALID_NOTICE_STATE,
            api.remedy_notice(ground.notice_id, warranty_analyst_headers()),
        ),
    ]


def _versions(api, ground):
    """The current `version` of every row the eleven refusals aim at."""
    plant = ground.plant
    return {
        "supplier": validate_success(
            api.get_supplier(plant.gas_supplier_id, supplier_quality_headers())
        )["version"],
        "component_lot": validate_success(
            api.get_component_lot(plant.gas_lot_id, quality_inspector_headers())
        )["version"],
        "batch": validate_success(
            api.get_lining_batch(plant.batch_id, plant_operator_headers())
        )["version"],
        "tank_lot": validate_success(
            api.get_tank_lot(plant.tank_lot_id, plant_operator_headers())
        )["version"],
        "model": validate_success(
            api.get_product_model(plant.model_id, compliance_engineer_headers())
        )["version"],
        "test": validate_success(
            api.get_efficiency_test(
                plant.uef_test_ids[0], compliance_engineer_headers()
            )
        )["version"],
        "certification": validate_success(
            api.get_certification(plant.cert_id, certification_approver_headers())
        )["version"],
        "unit": validate_success(
            api.get_heater_unit(ground.unit_id, plant_operator_headers())
        )["version"],
        "claim": validate_success(
            api.get_warranty_claim(ground.claim_id, warranty_analyst_headers())
        )["version"],
        "campaign": validate_success(
            api.get_recall_campaign(
                ground.draft_campaign_id, warranty_analyst_headers()
            )
        )["version"],
        "notice": validate_success(
            api.get_recall_notice(ground.notice_id, warranty_analyst_headers())
        )["version"],
    }


class TestInvalidStateFamilyPerEntity:
    """Eleven settled rows, eleven refusals, eleven different identifiers."""

    def test_04_the_supply_chain_families_each_name_themselves(self, api):
        """Supplier, component lot, lining batch and tank lot all differ.

        PRD: "Each entity family has its own code: `ERR_INVALID_SUPPLIER_STATE`,
        `ERR_INVALID_COMPONENT_LOT_STATE`, `ERR_INVALID_BATCH_STATE`,
        `ERR_INVALID_TANK_LOT_STATE`, `ERR_INVALID_MODEL_STATE`,
        `ERR_INVALID_TEST_STATE`, `ERR_INVALID_CERTIFICATION_STATE`,
        `ERR_INVALID_UNIT_STATE`, `ERR_INVALID_CLAIM_STATE`,
        `ERR_INVALID_CAMPAIGN_STATE` and `ERR_INVALID_NOTICE_STATE`, all HTTP 409."

        Design: Corner/errors/invalid_state_error_family_is_entity_specific
        """
        ground = _a_plant_with_a_claim_and_two_campaigns(api)

        refusals = _eleven_refusals_across_eleven_state_families(api, ground)[:4]

        for error_id, response in refusals:
            validate_error(response, error_id, expected_status=409)

    def test_05_re_releasing_a_released_model_names_the_model_family(self, api):
        """The channel dimension is already past `DRAFT`, so the move is undeclared.

        PRD: "Channel release is a `ComplianceEngineer` action that moves a model
        `DRAFT → RELEASED`; a model whose `release_status` is anything other than
        `DRAFT` reports `ERR_INVALID_MODEL_STATE`."

        Design: Corner/errors/invalid_state_error_family_is_entity_specific
        """
        ground = _a_plant_with_a_claim_and_two_campaigns(api)

        response = api.release_model_to_channel(
            ground.plant.model_id, compliance_engineer_headers()
        )

        validate_error(response, ERR_INVALID_MODEL_STATE, expected_status=409)
        model = validate_success(
            api.get_product_model(ground.plant.model_id, compliance_engineer_headers())
        )
        assert model["release_status"] == "RELEASED"

    def test_06_submitting_an_approved_certificate_names_the_certification_family(
        self, api
    ):
        """Submission is admissible only from `DRAFT` or `REJECTED`.

        PRD: "Submission is the compliance engineer's assertion that the test
        programme is complete, and it is accepted from either `DRAFT` or
        `REJECTED` — the `SUBMITTED → REJECTED → SUBMITTED` revision loop."

        Design: Corner/errors/invalid_state_error_family_is_entity_specific
        """
        ground = _a_plant_with_a_claim_and_two_campaigns(api)

        response = api.submit_certification(
            ground.plant.cert_id, compliance_engineer_headers()
        )

        validate_error(response, ERR_INVALID_CERTIFICATION_STATE, expected_status=409)
        cert = validate_success(
            api.get_certification(
                ground.plant.cert_id, certification_approver_headers()
            )
        )
        assert cert["status"] == "APPROVED"

    def test_07_a_second_reading_on_a_passed_test_names_the_test_family(self, api):
        """The stored reading is not overwritten by the refused second result.

        PRD: "The call is refused with `ERR_INVALID_TEST_STATE` unless the test is
        still `SCHEDULED`, and with `ERR_TEST_WINDOW_NOT_ELAPSED` unless the
        logical clock has reached the test's own `window_end`; the clock exactly at
        `window_end` is sufficient."

        Design: Corner/errors/invalid_state_error_family_is_entity_specific
        """
        ground = _a_plant_with_a_claim_and_two_campaigns(api)

        response = api.record_test_result(
            ground.plant.uef_test_ids[0],
            {"measured_value": 0.59},
            quality_inspector_headers(),
        )

        validate_error(response, ERR_INVALID_TEST_STATE, expected_status=409)
        test = validate_success(
            api.get_efficiency_test(
                ground.plant.uef_test_ids[0], compliance_engineer_headers()
            )
        )
        assert test["status"] == "PASSED"
        assert test["measured_value"] == approx4(0.5850)

    def test_08_assembling_a_shipped_unit_names_the_unit_family(self, api):
        """A unit that has left the dock cannot be assembled again.

        PRD: "Each entity family has its own code: `ERR_INVALID_SUPPLIER_STATE`,
        `ERR_INVALID_COMPONENT_LOT_STATE`, `ERR_INVALID_BATCH_STATE`,
        `ERR_INVALID_TANK_LOT_STATE`, `ERR_INVALID_MODEL_STATE`,
        `ERR_INVALID_TEST_STATE`, `ERR_INVALID_CERTIFICATION_STATE`,
        `ERR_INVALID_UNIT_STATE`, `ERR_INVALID_CLAIM_STATE`,
        `ERR_INVALID_CAMPAIGN_STATE` and `ERR_INVALID_NOTICE_STATE`, all HTTP 409."

        Design: Corner/errors/invalid_state_error_family_is_entity_specific
        """
        ground = _a_plant_with_a_claim_and_two_campaigns(api)

        response = api.assemble_unit(ground.unit_id, plant_operator_headers())

        validate_error(response, ERR_INVALID_UNIT_STATE, expected_status=409)
        unit = validate_success(
            api.get_heater_unit(ground.unit_id, plant_operator_headers())
        )
        assert unit["build_status"] == "SHIPPED"

    def test_09_paying_an_open_claim_names_the_claim_family(self, api):
        """Payment demands `VALIDATED`, and validation has not happened yet.

        PRD: "Attempting to validate a claim that is not `OPEN`, to pay one that is
        not `VALIDATED`, or to reverse one that is not `PAID`, all report
        `ERR_INVALID_CLAIM_STATE`."

        Design: Corner/errors/invalid_state_error_family_is_entity_specific
        """
        ground = _a_plant_with_a_claim_and_two_campaigns(api)

        response = api.pay_claim(ground.claim_id, warranty_analyst_headers())

        validate_error(response, ERR_INVALID_CLAIM_STATE, expected_status=409)
        claim = validate_success(
            api.get_warranty_claim(ground.claim_id, warranty_analyst_headers())
        )
        assert claim["status"] == "OPEN"
        assert claim["paid_at"] is None

    def test_10_announcing_a_draft_campaign_names_the_campaign_family(self, api):
        """An unscoped campaign cannot fan out, and writes no notice.

        PRD: "A `WarrantyAnalyst` announces a campaign in `status` `SCOPED`, and
        the campaign's `estimated_remedy_cost_cents` must be less than or equal to
        its `budget_cents`; an estimate exactly equal to the budget is allowed, and
        one cent over is refused with `ERR_RECALL_BUDGET_EXCEEDED`, leaving the
        campaign `SCOPED` so it can be re-scoped to a narrower range or reopened
        with more budget."

        Design: Corner/errors/invalid_state_error_family_is_entity_specific
        """
        ground = _a_plant_with_a_claim_and_two_campaigns(api)

        response = api.announce_campaign(
            ground.draft_campaign_id, warranty_analyst_headers()
        )

        validate_error(response, ERR_INVALID_CAMPAIGN_STATE, expected_status=409)
        campaign = validate_success(
            api.get_recall_campaign(
                ground.draft_campaign_id, warranty_analyst_headers()
            )
        )
        assert campaign["status"] == "DRAFT"
        assert x.campaign_notices(api, ground.draft_campaign_id) == []

    def test_11_remedying_a_pending_notice_names_the_notice_family(self, api):
        """A remedy cannot skip the notification step.

        PRD: "The same role records the remedy on a notice in `status` `NOTIFIED`,
        moving it `NOTIFIED → REMEDIED` and recording `remedied_at`; a remedy
        cannot skip notification, and attempting it on a `PENDING` notice reports
        `ERR_INVALID_NOTICE_STATE`."

        Design: Corner/errors/invalid_state_error_family_is_entity_specific
        """
        ground = _a_plant_with_a_claim_and_two_campaigns(api)

        response = api.remedy_notice(ground.notice_id, warranty_analyst_headers())

        validate_error(response, ERR_INVALID_NOTICE_STATE, expected_status=409)
        notice = validate_success(
            api.get_recall_notice(ground.notice_id, warranty_analyst_headers())
        )
        assert notice["status"] == "PENDING"
        assert notice["remedied_at"] is None

    def test_12_no_version_moved_during_the_eleven_refusals(self, api):
        """Eleven rejected writes leave eleven untouched rows.

        PRD: "Thirteen of the fourteen resource types are mutable and additionally
        carry `updated_at` — an ISO 8601 UTC timestamp with three fractional
        digits, refreshed on every accepted mutation of that row — and `version`,
        an integer that starts at 1 when the row is created and increments by
        exactly 1 on every accepted mutation."

        Design: Corner/errors/invalid_state_error_family_is_entity_specific
        """
        ground = _a_plant_with_a_claim_and_two_campaigns(api)
        before = _versions(api, ground)

        refusals = _eleven_refusals_across_eleven_state_families(api, ground)

        assert len(refusals) == 11
        for error_id, response in refusals:
            validate_error(response, error_id, expected_status=409)
        assert _versions(api, ground) == before


#: One single-resource read per resource type, with a role that is on that route.
NOT_FOUND_READS = [
    ("get_supplier", ERR_SUPPLIER_NOT_FOUND, supplier_quality_headers),
    ("get_component_lot", ERR_COMPONENT_LOT_NOT_FOUND, quality_inspector_headers),
    ("get_furnace", ERR_FURNACE_NOT_FOUND, plant_admin_headers),
    ("get_lining_batch", ERR_GLASS_LINING_BATCH_NOT_FOUND, plant_operator_headers),
    ("get_tank_lot", ERR_TANK_LOT_NOT_FOUND, plant_operator_headers),
    (
        "get_lining_inspection",
        ERR_LINING_INSPECTION_NOT_FOUND,
        quality_inspector_headers,
    ),
    ("get_product_model", ERR_PRODUCT_MODEL_NOT_FOUND, compliance_engineer_headers),
    ("get_test_cell", ERR_TEST_CELL_NOT_FOUND, plant_admin_headers),
    ("get_efficiency_test", ERR_EFFICIENCY_TEST_NOT_FOUND, compliance_engineer_headers),
    (
        "get_certification",
        ERR_RATING_CERTIFICATION_NOT_FOUND,
        certification_approver_headers,
    ),
    ("get_heater_unit", ERR_HEATER_UNIT_NOT_FOUND, plant_operator_headers),
    ("get_warranty_claim", ERR_WARRANTY_CLAIM_NOT_FOUND, warranty_analyst_headers),
    ("get_recall_campaign", ERR_RECALL_CAMPAIGN_NOT_FOUND, warranty_analyst_headers),
    ("get_recall_notice", ERR_RECALL_NOTICE_NOT_FOUND, warranty_analyst_headers),
]


class TestNotFoundFamilyPerEntity:
    """Fourteen resource types, fourteen distinct 404 identifiers."""

    @pytest.mark.parametrize(
        "reader, expected_error_id, headers",
        NOT_FOUND_READS,
        ids=[error_id for _reader, error_id, _headers in NOT_FOUND_READS],
    )
    def test_13_an_unknown_path_id_names_its_own_entity(
        self, api, reader, expected_error_id, headers
    ):
        """Path resolution reports the type of the row it could not find.

        PRD: "A missing row yields that entity's own not-found code:
        `ERR_SUPPLIER_NOT_FOUND`, `ERR_COMPONENT_LOT_NOT_FOUND`,
        `ERR_FURNACE_NOT_FOUND`, `ERR_GLASS_LINING_BATCH_NOT_FOUND`,
        `ERR_TANK_LOT_NOT_FOUND`, `ERR_LINING_INSPECTION_NOT_FOUND`,
        `ERR_PRODUCT_MODEL_NOT_FOUND`, `ERR_TEST_CELL_NOT_FOUND`,
        `ERR_EFFICIENCY_TEST_NOT_FOUND`, `ERR_RATING_CERTIFICATION_NOT_FOUND`,
        `ERR_HEATER_UNIT_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND`,
        `ERR_RECALL_CAMPAIGN_NOT_FOUND` or `ERR_RECALL_NOTICE_NOT_FOUND`, each HTTP
        404."

        Design: Corner/errors/not_found_error_family_is_entity_specific
        """
        response = getattr(api, reader)(NON_EXISTENT_UUID, headers())

        validate_error(response, expected_error_id, expected_status=404)
        assert response.json()["response_type"] == "error"


class TestExclusiveOperationsRefusedToOtherRoles:
    """Eleven writes, each reserved to one role, each attempted by another."""

    def test_14_the_clock_moves_for_nobody_but_the_plant_administrator(self, api):
        """A production operator's clock move is refused and the instant holds.

        PRD: "A `PlantAdmin` moves the clock by supplying a `current_utc` instant,
        and any role other than `SupplierRep` may read the clock, which returns the
        same `current_utc` field."

        Design: Corner/rbac/exclusive_operations_are_forbidden_to_every_other_role
        """
        x.make_full_plant(api)

        response = api.set_clock("2026-08-06T00:00:00Z", plant_operator_headers())

        validate_error(response, ERR_FORBIDDEN_ROLE, expected_status=403)
        clock = validate_success(api.read_clock(plant_admin_headers()))
        assert clock["current_utc"].startswith("2026-08-05T06:00:00")

    def test_15_every_exclusive_write_is_closed_to_the_wrong_role(self, api):
        """Eight reserved writes, eight callers who do not own them.

        PRD: "Authorisation — the caller's role is listed on this endpoint
        (`ERR_FORBIDDEN_ROLE`, 403), on every endpoint."

        Design: Corner/rbac/exclusive_operations_are_forbidden_to_every_other_role
        """
        plant = x.make_full_plant(api)

        refusals = [
            api.create_furnace(
                furnace_payload(furnace_code="FURN-B", max_firing_temp_c=880),
                plant_operator_headers(),
            ),
            api.create_tank_lot(
                tank_lot_payload(plant.model_id, lot_code="TL-002", planned_quantity=60),
                quality_inspector_headers(),
            ),
            api.create_product_model(
                product_model_payload(
                    model_code="EX40-E",
                    fuel_type="ELECTRIC",
                    nominal_capacity_gallons=40,
                    channel="RETAIL",
                    insulation_r_value=18,
                ),
                plant_admin_headers(),
            ),
            api.create_heater_unit(
                heater_unit_payload(
                    plant.tank_lot_id, plant.valve_lot_id, plant.gas_lot_id
                ),
                quality_inspector_headers(),
            ),
            api.create_recall_campaign(
                recall_campaign_payload(plant.model_id, campaign_code="RC-X"),
                plant_admin_headers(),
            ),
            api.revoke_certification(
                plant.cert_id,
                reason_payload(reason_code="TEST_DATA_INVALID"),
                compliance_engineer_headers(),
            ),
            api.lift_model_restriction(plant.model_id, compliance_engineer_headers()),
            api.release_component_lot(plant.gas_lot_id, supplier_quality_headers()),
        ]

        assert len(refusals) == 8
        for response in refusals:
            validate_error(response, ERR_FORBIDDEN_ROLE, expected_status=403)
        cert = validate_success(
            api.get_certification(plant.cert_id, certification_approver_headers())
        )
        assert cert["status"] == "APPROVED"

    def test_16_the_role_gate_speaks_before_the_pin_and_before_the_state(self, api):
        """Two calls that would also fail later rules still report the role.

        PRD: "When a request violates more than one rule, exactly one error is
        returned, and which one is fully determined: the rules are evaluated in a
        fixed order and the **first** violated rule wins."

        Design: Corner/rbac/exclusive_operations_are_forbidden_to_every_other_role
        """
        plant = x.make_full_plant(api)

        stale_and_wrong_role = api.create_lining_inspection(
            adhesion_inspection_payload(plant.tank_lot_id, LONG_STALE_PIN),
            plant_operator_headers(),
        )
        settled_and_wrong_role = api.unblock_component_lot(
            plant.gas_lot_id, quality_inspector_headers()
        )

        validate_error(stale_and_wrong_role, ERR_FORBIDDEN_ROLE, expected_status=403)
        validate_error(settled_and_wrong_role, ERR_FORBIDDEN_ROLE, expected_status=403)

    def test_17_the_one_shared_write_is_open_to_both_of_its_roles(self, api):
        """Booking incoming material is accepted from either quality role.

        PRD: "Incoming material is booked as a component lot, an action open to
        both the `SupplierQualityManager` and the `QualityInspector`."

        Design: Corner/rbac/exclusive_operations_are_forbidden_to_every_other_role
        """
        plant = x.make_full_plant(api)

        by_inspector = api.create_component_lot(
            component_lot_payload(
                plant.gas_supplier_id, part_number="GV-990", quantity=10
            ),
            quality_inspector_headers(),
        )
        by_manager = api.create_component_lot(
            component_lot_payload(
                plant.gas_supplier_id, part_number="GV-991", quantity=10
            ),
            supplier_quality_headers(),
        )

        first = validate_success(by_inspector, expected_status=201)
        second = validate_success(by_manager, expected_status=201)
        assert first["status"] == "QUARANTINED"
        assert second["status"] == "QUARANTINED"
        lot = validate_success(
            api.get_component_lot(plant.gas_lot_id, quality_inspector_headers())
        )
        model = validate_success(
            api.get_product_model(plant.model_id, compliance_engineer_headers())
        )
        assert lot["status"] == "RELEASED"
        assert model["release_status"] == "RELEASED"


class TestSupplierRepReadScope:
    """The one entity-backed role: three endpoints, and only its own rows on them."""

    def test_18_single_reads_stop_at_the_acting_supplier_row(self, api):
        """Its own supplier and its own lot are readable; the neighbour's are not.

        PRD: "A `SupplierRep` may read its own supplier record and no other, and
        may read a component lot only when that lot's `supplier_id` equals
        `X-User-ID`; the component-lot list is likewise narrowed to its own lots."

        Design: Corner/rbac/supplier_rep_reads_outside_its_own_scope_are_forbidden
        """
        supply = x.make_supply_base(api)
        rep = make_supplier_rep_headers(supply.gas_supplier_id)

        own_supplier = validate_success(api.get_supplier(supply.gas_supplier_id, rep))
        other_supplier = api.get_supplier(supply.valve_supplier_id, rep)
        own_lot = validate_success(api.get_component_lot(supply.gas_lot_id, rep))
        other_lot = api.get_component_lot(supply.valve_lot_id, rep)

        assert own_supplier["name"] == "Meridian Controls"
        assert own_lot["part_number"] == "GV-880"
        validate_error(
            other_supplier, ERR_SUPPLIER_SCOPE_VIOLATION, expected_status=403
        )
        validate_error(other_lot, ERR_SUPPLIER_SCOPE_VIOLATION, expected_status=403)

    def test_19_the_lot_list_is_narrowed_and_a_foreign_filter_is_refused(self, api):
        """Asking for someone else's lots is a scope breach, not an empty page.

        PRD: "Any read that reaches outside that scope is rejected with
        `ERR_SUPPLIER_SCOPE_VIOLATION` (HTTP 403)."

        Design: Corner/rbac/supplier_rep_reads_outside_its_own_scope_are_forbidden
        """
        supply = x.make_supply_base(api)
        rep = make_supplier_rep_headers(supply.gas_supplier_id)

        unfiltered = api.list_component_lots(rep, {"limit": 100, "offset": 0})
        foreign_filter = api.list_component_lots(
            rep, {"supplier_id": supply.valve_supplier_id, "limit": 100, "offset": 0}
        )

        rows, _meta = validate_paginated(unfiltered)
        assert unfiltered.json()["response_type"] == "array"
        assert [row["id"] for row in rows] == [supply.gas_lot_id]
        validate_error(
            foreign_filter, ERR_SUPPLIER_SCOPE_VIOLATION, expected_status=403
        )

    def test_20_endpoints_off_the_three_are_refused_on_the_role_itself(self, api):
        """The collection read, the tank-lot list and any write are all closed.

        PRD: "Read-only, and authorised on exactly three endpoints: the
        single-supplier read, the single-component-lot read, and the component-lot
        list."

        Design: Corner/rbac/supplier_rep_reads_outside_its_own_scope_are_forbidden
        """
        supply = x.make_supply_base(api)
        rep = make_supplier_rep_headers(supply.gas_supplier_id)

        supplier_collection = api.list_suppliers(rep, {"limit": 100, "offset": 0})
        tank_lot_list = api.list_tank_lots(rep, {"limit": 100, "offset": 0})
        attempted_write = api.create_component_lot(
            component_lot_payload(
                supply.gas_supplier_id, part_number="GV-992", quantity=10
            ),
            rep,
        )

        validate_error(supplier_collection, ERR_FORBIDDEN_ROLE, expected_status=403)
        validate_error(tank_lot_list, ERR_FORBIDDEN_ROLE, expected_status=403)
        validate_error(attempted_write, ERR_FORBIDDEN_ROLE, expected_status=403)
        rows, _meta = validate_paginated(
            api.list_component_lots(
                supplier_quality_headers(), {"limit": 100, "offset": 0}
            )
        )
        assert len(rows) == 2

    def test_21_an_identity_that_matches_no_supplier_row_owns_nothing(self, api):
        """Ownership is compared against a real row, so an unknown caller is out.

        PRD: "When `X-User-Role` is `SupplierRep`, `X-User-ID` is the `id` of the
        acting `Supplier` row; ownership checks compare the resource's supplier
        reference to `X-User-ID`."

        Design: Corner/rbac/supplier_rep_reads_outside_its_own_scope_are_forbidden
        """
        supply = x.make_supply_base(api)

        response = api.get_supplier(
            supply.gas_supplier_id, make_supplier_rep_headers(NON_EXISTENT_UUID)
        )

        validate_error(response, ERR_SUPPLIER_SCOPE_VIOLATION, expected_status=403)


def _two_open_certifications_one_submitted(api):
    """A submitted certificate and a newer draft sibling on the same model.

    The submitted one is opened and submitted first, so the later creation cannot
    supersede it - only a certificate still sitting at DRAFT or REJECTED is
    superseded - which leaves the draft opened second the live DRAFT of the pair.
    """
    model_id = x.make_model(api)["id"]
    cell_id = x.make_test_cell(api)["id"]
    x.make_passing_test_suite(api, model_id, cell_id)
    submitted = x.make_submitted_certification(api, model_id)
    draft = data_of(
        api.create_certification(
            certification_payload(model_id, x.model_version(api, model_id)),
            compliance_engineer_headers(),
        )
    )
    return SimpleNamespace(
        model_id=model_id, submitted_id=submitted["id"], draft_id=draft["id"]
    )


class TestSegregationOfDutiesPerUser:
    """The approver gate reads the user id, not the role, and guards both verdicts."""

    def test_22_the_submitter_may_not_approve_even_wearing_the_approver_role(
        self, api
    ):
        """`eng-1` holding the approver role is still the submitter.

        PRD: "Adjudication belongs exclusively to a `CertificationApprover`, and
        both outcomes require the caller's `X-User-ID` to differ from
        `submitted_by_user_id`, failing with `ERR_SOD_APPROVER_IS_SUBMITTER`."

        Design: Corner/rbac/segregation_of_duties_is_per_user_not_per_role_on_both_verdicts
        """
        ground = _two_open_certifications_one_submitted(api)

        response = api.approve_certification(
            ground.submitted_id,
            approve_payload(),
            certification_approver_headers(USER_ENGINEER),
        )

        validate_error(response, ERR_SOD_APPROVER_IS_SUBMITTER, expected_status=403)
        cert = validate_success(
            api.get_certification(ground.submitted_id, certification_approver_headers())
        )
        assert cert["status"] == "SUBMITTED"
        assert cert["submitted_by_user_id"] == "eng-1"

    def test_23_the_submitter_may_not_reject_its_own_submission_either(self, api):
        """The negative verdict carries the same separation requirement.

        PRD: "Adjudication belongs exclusively to a `CertificationApprover`, and
        both outcomes require the caller's `X-User-ID` to differ from
        `submitted_by_user_id`, failing with `ERR_SOD_APPROVER_IS_SUBMITTER`."

        Design: Corner/rbac/segregation_of_duties_is_per_user_not_per_role_on_both_verdicts
        """
        ground = _two_open_certifications_one_submitted(api)

        response = api.reject_certification(
            ground.submitted_id,
            reason_payload(reason_code="MISSING_TEST_DATA"),
            certification_approver_headers(USER_ENGINEER),
        )

        validate_error(response, ERR_SOD_APPROVER_IS_SUBMITTER, expected_status=403)
        cert = validate_success(
            api.get_certification(ground.submitted_id, certification_approver_headers())
        )
        assert cert["status"] == "SUBMITTED"
        assert cert["reason_code"] is None

    def test_24_the_state_check_outranks_the_separation_check(self, api):
        """The same conflicted caller on a draft hears about the state instead.

        PRD: "Approving a certificate that is not `SUBMITTED` — a `DRAFT`, for
        instance — and revoking one that is `SUPERSEDED` both report
        `ERR_INVALID_CERTIFICATION_STATE`."

        Design: Corner/rbac/segregation_of_duties_is_per_user_not_per_role_on_both_verdicts
        """
        ground = _two_open_certifications_one_submitted(api)

        response = api.approve_certification(
            ground.draft_id,
            approve_payload(),
            certification_approver_headers(USER_ENGINEER),
        )

        validate_error(response, ERR_INVALID_CERTIFICATION_STATE, expected_status=409)
        draft = validate_success(
            api.get_certification(ground.draft_id, certification_approver_headers())
        )
        assert draft["status"] == "DRAFT"
        assert draft["submitted_by_user_id"] is None

    def test_25_an_independent_approver_publishes_the_rating(self, api):
        """A different user in the same role is admissible, and the model publishes.

        PRD: "Approval also stores `approved_by_user_id` and stamps
        `label_serial_prefix` on the certificate equal to the model's `model_code`,
        then publishes onto the model itself: the model's `certification_status`
        moves to `CERTIFIED` from whichever of `UNCERTIFIED`, `TEST_PENDING` or
        `SUSPENDED` it occupied, and `certified_uef`, `certified_fhr`,
        `certified_recovery` and `label_serial_prefix` are copied onto the model's
        `uef_rated`, `fhr_rated`, `recovery_rate_rated` and `label_serial_prefix`
        respectively."

        Design: Corner/rbac/segregation_of_duties_is_per_user_not_per_role_on_both_verdicts
        """
        ground = _two_open_certifications_one_submitted(api)

        approved = validate_success(
            api.approve_certification(
                ground.submitted_id,
                approve_payload(),
                certification_approver_headers(USER_APPROVER),
            )
        )

        assert approved["status"] == "APPROVED"
        assert approved["submitted_by_user_id"] == "eng-1"
        assert approved["approved_by_user_id"] == "appr-1"
        model = validate_success(
            api.get_product_model(ground.model_id, compliance_engineer_headers())
        )
        assert model["certification_status"] == "CERTIFIED"
        assert model["uef_rated"] == approx2(0.59)


def _the_nine_shared_reads(api, plant):
    """One shared read per opaque-identity role, plus the supplier-scoped one."""
    return [
        api.list_furnaces(plant_admin_headers(), {"limit": 100, "offset": 0}),
        api.get_tank_lot(plant.tank_lot_id, plant_operator_headers()),
        api.list_lot_lining_inspections(
            plant.tank_lot_id, quality_inspector_headers(), {"limit": 100, "offset": 0}
        ),
        api.get_product_model(plant.model_id, compliance_engineer_headers()),
        api.get_certification(plant.cert_id, certification_approver_headers()),
        api.list_component_lots(
            supplier_quality_headers(),
            {"supplier_id": plant.gas_supplier_id, "limit": 100, "offset": 0},
        ),
        api.get_warranty_analysis(
            plant.model_id, warranty_analyst_headers(), {"production_period": "2026-08"}
        ),
        api.get_supplier(
            plant.gas_supplier_id, make_supplier_rep_headers(plant.gas_supplier_id)
        ),
        api.read_clock(supplier_quality_headers()),
    ]


class TestSharedReadsOpenToEveryRole:
    """Whatever a role may not write, it may still read what it is listed on."""

    def test_26_all_nine_shared_reads_are_admitted(self, api):
        """Nine callers, nine roles, nine successful reads and no role refusal.

        PRD: "The role check applies to every endpoint without exception — the
        clock read, for instance, is open to all seven opaque-identity roles but
        closed to `SupplierRep`."

        Design: Corner/rbac/every_declared_role_can_perform_its_shared_reads
        """
        plant = x.make_full_plant(api)

        reads = _the_nine_shared_reads(api, plant)

        assert len(reads) == 9
        for response in reads:
            assert response.status_code == 200
            body = response.json()
            assert body["response_type"] != "error"

    def test_27_the_production_reads_carry_the_plant_s_own_rows(self, api):
        """The furnace, the released lot and its two inspection records.

        PRD: "Shares every read endpoint except the supplier-scoped reads."

        Design: Corner/rbac/every_declared_role_can_perform_its_shared_reads
        """
        plant = x.make_full_plant(api)

        furnaces = api.list_furnaces(plant_admin_headers(), {"limit": 100, "offset": 0})
        lot = validate_success(
            api.get_tank_lot(plant.tank_lot_id, plant_operator_headers())
        )
        inspections, _meta = validate_paginated(
            api.list_lot_lining_inspections(
                plant.tank_lot_id,
                quality_inspector_headers(),
                {"limit": 100, "offset": 0},
            )
        )

        furnace_rows, _furnace_meta = validate_paginated(furnaces)
        assert furnaces.json()["response_type"] == "array"
        assert len(furnace_rows) == 1
        assert furnace_rows[0]["id"] == plant.furnace_id
        assert lot["status"] == "RELEASED"
        assert len(inspections) == 2

    def test_28_the_certificate_and_the_supplier_filtered_lots_read_back(self, api):
        """The approver sees its own verdict; the manager sees one supplier's lots.

        PRD: "Shares the catalogue, test and certification read endpoints."

        Design: Corner/rbac/every_declared_role_can_perform_its_shared_reads
        """
        plant = x.make_full_plant(api)

        cert = validate_success(
            api.get_certification(plant.cert_id, certification_approver_headers())
        )
        lots, _meta = validate_paginated(
            api.list_component_lots(
                supplier_quality_headers(),
                {"supplier_id": plant.gas_supplier_id, "limit": 100, "offset": 0},
            )
        )

        assert cert["status"] == "APPROVED"
        assert cert["certified_uef"] == approx2(0.59)
        assert [row["id"] for row in lots] == [plant.gas_lot_id]

    def test_29_the_computed_report_and_the_clock_are_shared_too(self, api):
        """An empty cohort still answers, and the clock reads for a supplier manager.

        PRD: "Shares the warranty-analysis and recall-completion computed reads
        plus the catalogue, unit, claim, certification and recall read endpoints."

        Design: Corner/rbac/every_declared_role_can_perform_its_shared_reads
        """
        plant = x.make_full_plant(api)

        analysis = validate_success(
            api.get_warranty_analysis(
                plant.model_id,
                warranty_analyst_headers(),
                {"production_period": "2026-08"},
            )
        )
        clock = validate_success(api.read_clock(supplier_quality_headers()))

        assert analysis["shipped_unit_count"] == 0
        assert clock["current_utc"].startswith(CLOCK_AFTER_ALL_WINDOWS[:-1])

    def test_30_the_supplier_representative_reads_its_own_score(self, api):
        """The external role's one useful read returns the published weighting.

        PRD: "The three components are then combined with weights of 0.40 for the
        audit component, 0.35 for the parts-per-million component and 0.25 for the
        corrective-action component, and the weighted sum is rounded half up to two
        decimal places to become `qualification_score`."

        Design: Corner/rbac/every_declared_role_can_perform_its_shared_reads
        """
        plant = x.make_full_plant(api)

        own = validate_success(
            api.get_supplier(
                plant.gas_supplier_id, make_supplier_rep_headers(plant.gas_supplier_id)
            )
        )

        assert own["qualification_score"] == approx2(91.40)
        assert own["qualification_status"] == "QUALIFIED"
