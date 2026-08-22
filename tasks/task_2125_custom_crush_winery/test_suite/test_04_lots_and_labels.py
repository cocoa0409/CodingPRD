"""Lot creation, derived composition, federal label eligibility and provenance."""
import pytest

from test_helpers import (
    ApiErrorId,
    activate_contract,
    assert_lot,
    create_lot_payload,
    new_accepted_intake,
    new_contract,
    new_lot,
    setup_active_contract,
    setup_executed_blend_trial,
    validate_error,
    validate_paginated,
    validate_success,
)

FIVE_TON = {"gross_weight_lbs": 14000, "tare_weight_lbs": 4000}


def test_new_lot_opens_on_both_axes_with_derived_composition(
    api, cellar_supervisor_headers, facility_admin_headers
):
    """PRD 3.4: "A newly created lot carries `origin` `INTAKE`,
    `production_status` `JUICE`, `bond_status` `IN_BOND`, `loss_gallons` 0,
    `cases_bottled` 0, `aging_days` 0, and null values for `current_vessel_id`,
    `parent_lot_id`, `alcohol_pct` and `aging_start_at`."
    PRD 3.4: "Its `source_intake_ids` records, in order, the intakes it was
    built from, and its `component_manifest` is an empty array because it is not
    a blend. Each named intake moves `ACCEPTED` to `ASSIGNED` and takes the new
    lot's identifier as its own `lot_id`, and the owning client's
    `bond_gallons_in_bond` is recomputed."

    Design: Corner/state_machines/corner_lot_initial_state_is_juice_and_in_bond
    """
    scenario = setup_active_contract()
    contract_id = scenario["contract"]["id"]
    intake = new_accepted_intake(contract_id, "DT-1001")

    data = validate_success(
        api.create_lot(
            create_lot_payload(contract_id, [intake["id"]]), cellar_supervisor_headers
        ),
        201,
    )

    assert_lot(data)
    assert data["production_status"] == "JUICE"
    assert data["bond_status"] == "IN_BOND"
    assert data["origin"] == "INTAKE"
    assert data["aging_start_at"] is None
    assert data["aging_days"] == 0
    assert data["cases_bottled"] == 0
    assert data["loss_gallons"] == pytest.approx(0, abs=0.01)
    assert data["volume_gallons"] == pytest.approx(3135.00, abs=0.01)
    assert data["brix_at_crush"] == pytest.approx(23.50, abs=0.01)
    assert data["source_intake_ids"] == [intake["id"]]
    assert data["component_manifest"] == []

    stored_intake = validate_success(
        api.get_harvest_intake(intake["id"], facility_admin_headers)
    )
    assert stored_intake["status"] == "ASSIGNED"
    assert stored_intake["lot_id"] == data["id"]

    client = validate_success(
        api.get_client(scenario["client"]["id"], facility_admin_headers)
    )
    assert client["bond_gallons_in_bond"] == pytest.approx(3135.00, abs=0.01)


def test_brix_at_crush_is_volume_weighted_and_dominance_follows_gallons(
    api, cellar_supervisor_headers
):
    """PRD 3.4: "Its `brix_at_crush` is the volume-weighted average sugar of
    that fruit: total each intake's `estimated_gallons` multiplied by its
    `brix`, divide by the total `estimated_gallons`, and round half up to two
    decimal places."
    PRD 3.4: "The dominant `varietal` is the varietal value with the greatest
    total `estimated_gallons` among the contributing intakes; where two
    varietals tie on gallons, the winner is the one whose earliest contributing
    intake has the smaller `created_at`, never the one with the smaller
    identifier."

    Design: Corner/calculations/corner_lot_composition_volume_weighted_brix_and_dominant_varietal
    """
    scenario = setup_active_contract()
    contract_id = scenario["contract"]["id"]
    cabernet = new_accepted_intake(
        contract_id, "DT-A1", brix=26.00, ph=3.65,
        varietal="CABERNET_SAUVIGNON", appellation="OAKVILLE", block_code="B12",
        **FIVE_TON,
    )
    merlot = new_accepted_intake(
        contract_id, "DT-A2", brix=22.50, ph=3.50,
        varietal="MERLOT", appellation="RUTHERFORD", block_code="R04", **FIVE_TON,
    )
    assert cabernet["estimated_gallons"] == pytest.approx(787.50, abs=0.01)
    assert merlot["estimated_gallons"] == pytest.approx(825.00, abs=0.01)

    data = validate_success(
        api.create_lot(
            create_lot_payload(
                contract_id, [cabernet["id"], merlot["id"]], lot_code="MIX-26-01"
            ),
            cellar_supervisor_headers,
        ),
        201,
    )

    assert data["volume_gallons"] == pytest.approx(1612.50, abs=0.01)
    assert data["brix_at_crush"] == pytest.approx(24.21, abs=0.01), (
        f"the volume-weighted average is 24.21, not the arithmetic mean 24.25; "
        f"got {data['brix_at_crush']}"
    )
    assert data["varietal"] == "MERLOT", "825.00 gallons beats 787.50"
    assert data["appellation"] == "RUTHERFORD"
    assert data["varietal_label"] == "RED_BLEND", "a 51.16 percent share is below 75.00"
    assert data["appellation_label"] == "CALIFORNIA"
    assert data["source_intake_ids"] == [cabernet["id"], merlot["id"]]


def test_varietal_label_survives_at_exactly_seventy_five_percent(
    api, cellar_supervisor_headers
):
    """PRD 3.4: "The dominant varietal's share is 100 multiplied by its gallons
    and divided by the lot's `volume_gallons`, rounded half up to two decimal
    places; when that share is at least 75.00 percent the lot's
    `varietal_label` is that varietal's name, and otherwise it is the literal
    string `RED_BLEND`."

    Design: Corner/calculations/corner_lot_varietal_label_at_and_below_the_75_percent_line
    """
    scenario = setup_active_contract()
    contract_id = scenario["contract"]["id"]
    # 15.0 t CABERNET = 2475.00 gallons, 5.0 t MERLOT = 825.00 gallons → 75.00 %
    cab_at = new_accepted_intake(contract_id, "DT-B1", gross_weight_lbs=34000,
                                 tare_weight_lbs=4000)
    mer_at = new_accepted_intake(contract_id, "DT-B2", varietal="MERLOT",
                                 block_code="B07", brix=23.50, ph=3.55, **FIVE_TON)
    # 14.0 t CABERNET = 2310.00 gallons, 6.0 t MERLOT = 990.00 gallons → 70.00 %
    cab_below = new_accepted_intake(contract_id, "DT-B3", gross_weight_lbs=32000,
                                    tare_weight_lbs=4000, block_code="B13")
    mer_below = new_accepted_intake(contract_id, "DT-B4", varietal="MERLOT",
                                    block_code="B08", brix=23.50, ph=3.55,
                                    gross_weight_lbs=16000, tare_weight_lbs=4000)

    at_line = new_lot(
        contract_id, [cab_at["id"], mer_at["id"]], lot_code="AT75-26-01"
    )
    below_line = new_lot(
        contract_id, [cab_below["id"], mer_below["id"]], lot_code="AT70-26-01"
    )

    assert at_line["volume_gallons"] == pytest.approx(3300.00, abs=0.01)
    assert at_line["varietal_label"] == "CABERNET_SAUVIGNON", (
        "a share landing exactly on 75.00 percent satisfies the threshold"
    )
    assert below_line["volume_gallons"] == pytest.approx(3300.00, abs=0.01)
    assert below_line["varietal_label"] == "RED_BLEND", "70.00 percent is below the line"
    assert at_line["appellation_label"] == "OAKVILLE"
    assert below_line["appellation_label"] == "OAKVILLE"


def test_appellation_label_falls_back_to_california_below_eighty_five_percent(
    api, cellar_supervisor_headers
):
    """PRD 3.4: "The dominant appellation's share is computed the same way; when
    it is at least 85.00 percent the `appellation_label` is that appellation's
    name, and otherwise it is the literal string `CALIFORNIA`."

    Design: Corner/calculations/corner_lot_appellation_label_falls_back_to_california_below_85
    """
    scenario = setup_active_contract()
    contract_id = scenario["contract"]["id"]
    # 16.0 t OAKVILLE = 2640.00 gallons, 4.0 t RUTHERFORD = 660.00 gallons → 80.00 %
    oakville = new_accepted_intake(contract_id, "DT-C1", gross_weight_lbs=36000,
                                   tare_weight_lbs=4000)
    rutherford = new_accepted_intake(contract_id, "DT-C2", appellation="RUTHERFORD",
                                     block_code="R04", brix=23.50, ph=3.60,
                                     gross_weight_lbs=12000, tare_weight_lbs=4000)

    data = new_lot(
        contract_id, [oakville["id"], rutherford["id"]], lot_code="AVA80-26-01"
    )

    assert data["volume_gallons"] == pytest.approx(3300.00, abs=0.01)
    assert data["varietal_label"] == "CABERNET_SAUVIGNON", (
        "the lot is 100.00 percent CABERNET_SAUVIGNON by volume"
    )
    assert data["appellation"] == "OAKVILLE"
    assert data["appellation_label"] == "CALIFORNIA", (
        "80.00 percent is below the 85.00 percent AVA line"
    )


def test_lot_may_not_be_built_from_another_contracts_fruit(
    api, cellar_supervisor_headers, facility_admin_headers
):
    """PRD 3.4: "Every named intake must also belong to the same contract as the
    new lot, or the request is refused with `ERR_CROSS_CONTRACT_REFERENCE`."

    Design: Corner/validations/corner_cross_contract_intake_reference_rejected
    """
    scenario = setup_active_contract()
    contract_a = scenario["contract"]["id"]
    contract_b = new_contract(scenario["client"]["id"], harvest_year=2027)
    activate_contract(contract_b["id"])
    intake_b = new_accepted_intake(contract_b["id"], "DT-S1", **FIVE_TON)

    response = api.create_lot(
        create_lot_payload(contract_a, [intake_b["id"]], lot_code="XC-26-01"),
        cellar_supervisor_headers,
    )
    validate_error(response, ApiErrorId.ERR_CROSS_CONTRACT_REFERENCE.value, 422)

    stored = validate_success(api.get_harvest_intake(intake_b["id"], facility_admin_headers))
    assert stored["status"] == "ACCEPTED"
    assert stored["lot_id"] is None

    rows, meta = validate_paginated(
        api.list_lots(facility_admin_headers, params={"contract_id": contract_a})
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_lot_creation_side_effects_are_visible_on_the_very_next_read(
    api, cellar_supervisor_headers, facility_admin_headers
):
    """PRD 3.4: "The lot's `volume_gallons` is the total `estimated_gallons` of
    the named intakes, rounded half up to two decimal places."
    PRD 3.1: "`bond_gallons_in_bond` is the total `volume_gallons` across that
    client's lots whose `bond_status` is `IN_BOND`, carried to two decimal
    places and recomputed on every mutation of a lot's volume or bond status."

    Design: Corner/consistency_model/corner_immediate_visibility_of_lot_creation_side_effects
    """
    scenario = setup_active_contract()
    contract_id = scenario["contract"]["id"]
    intake = new_accepted_intake(contract_id, "DT-AM1")

    created = validate_success(
        api.create_lot(
            create_lot_payload(contract_id, [intake["id"]]), cellar_supervisor_headers
        ),
        201,
    )
    assert created["volume_gallons"] == pytest.approx(3135.00, abs=0.01), (
        "the creation response itself already carries the computed volume"
    )

    stored_intake = validate_success(
        api.get_harvest_intake(intake["id"], cellar_supervisor_headers)
    )
    assert stored_intake["status"] == "ASSIGNED"
    assert stored_intake["lot_id"] == created["id"]

    client = validate_success(
        api.get_client(scenario["client"]["id"], facility_admin_headers)
    )
    assert client["bond_gallons_in_bond"] == pytest.approx(3135.00, abs=0.01)


def test_traceability_read_exposes_the_manifest_and_transitive_ancestors(
    api, compliance_officer_headers
):
    """PRD 3.4: "The traceability view of a lot answers with the lot's own
    `lot_id`, its `origin`, the `source_intake_ids` it was built from, its
    `component_manifest`, the `ancestor_lot_ids` reachable transitively through
    blend lineage, and a `total_source_gallons` figure."
    PRD 3.4: "For a `BLEND`-origin lot, `total_source_gallons` is the total of
    the component volumes recorded in its `component_manifest`, and
    `ancestor_lot_ids` lists every source lot named in that manifest and then,
    transitively, every lot named in those lots' own manifests."

    Design: Corner/endpoints/corner_lot_traceability_computed_read_returns_ancestors
    """
    scenario = setup_executed_blend_trial(draw_a=750.00, draw_b=250.00)
    blend_lot_id = scenario["blend_lot"]["id"]

    data = validate_success(
        api.get_lot_traceability(blend_lot_id, compliance_officer_headers)
    )

    assert data["origin"] == "BLEND"
    assert data["total_source_gallons"] == pytest.approx(1000.00, abs=0.01)
    assert data["source_intake_ids"] == [], "a blend lot is not built from fruit"

    manifest = {entry["source_lot_id"]: entry for entry in data["component_manifest"]}
    assert len(manifest) == 2, f"expected two component entries, got {manifest}"
    assert manifest[scenario["lot_a"]["id"]]["volume_gallons"] == pytest.approx(
        750.00, abs=0.01
    )
    assert manifest[scenario["lot_a"]["id"]]["pct_of_blend"] == pytest.approx(
        75.00, abs=0.01
    )
    assert manifest[scenario["lot_b"]["id"]]["volume_gallons"] == pytest.approx(
        250.00, abs=0.01
    )
    assert manifest[scenario["lot_b"]["id"]]["pct_of_blend"] == pytest.approx(
        25.00, abs=0.01
    )

    assert scenario["lot_a"]["id"] in data["ancestor_lot_ids"]
    assert scenario["lot_b"]["id"] in data["ancestor_lot_ids"]

    source_view = validate_success(
        api.get_lot_traceability(scenario["lot_a"]["id"], compliance_officer_headers)
    )
    assert source_view["source_intake_ids"] == [scenario["intake_a"]["id"]]

    rows, meta = validate_paginated(
        api.list_lots(compliance_officer_headers, params={"parent_lot_id": blend_lot_id})
    )
    assert rows == [], "neither source lot was fully drawn, so neither carries a parent"
    assert meta["total_count"] == 0


# ── The empty-collection edge on lot creation ───────────────────────


def test_lot_creation_with_an_empty_intake_array_finds_no_eligible_fruit(
    api, cellar_supervisor_headers
):
    """PRD 3.4: "That array must not be empty and every intake it names must
    stand in `ACCEPTED`; an empty array or an intake in any other status is
    refused with `ERR_NO_ELIGIBLE_INTAKES`."

    Design: Difficulty/boundary_precision_check/lot_creation_rejects_empty_intake_ids_collection
    """
    scenario = setup_active_contract(clock="2026-09-15T00:00:00Z")

    response = api.create_lot(
        create_lot_payload(scenario["contract"]["id"], [], lot_code="EMPTY-26-01"),
        cellar_supervisor_headers,
    )

    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_INTAKES.value, 422)


def test_rejected_empty_lot_creation_mints_nothing_and_moves_no_version(
    api, cellar_supervisor_headers, facility_admin_headers
):
    """PRD 3.4: "That array must not be empty and every intake it names must
    stand in `ACCEPTED`; an empty array or an intake in any other status is
    refused with `ERR_NO_ELIGIBLE_INTAKES`."
    PRD 3.1: "Every one of these six transitions increments the contract's
    `version` by 1."

    Design: Difficulty/boundary_precision_check/lot_creation_rejects_empty_intake_ids_collection
    """
    scenario = setup_active_contract(clock="2026-09-15T00:00:00Z")
    contract_id = scenario["contract"]["id"]

    api.create_lot(
        create_lot_payload(contract_id, [], lot_code="EMPTY-26-01"),
        cellar_supervisor_headers,
    )

    rows, meta = validate_paginated(
        api.list_lots(cellar_supervisor_headers, params={"contract_id": contract_id})
    )
    assert rows == [], "no zero-gallon lot may be minted"
    assert meta["total_count"] == 0
    assert meta["has_more"] is False

    contract = validate_success(api.get_contract(contract_id, facility_admin_headers))
    assert contract["version"] == 3, (
        f"create, SUBMIT and ACTIVATE leave version 3; the rejected call must "
        f"perform no mutation, got {contract['version']}"
    )
