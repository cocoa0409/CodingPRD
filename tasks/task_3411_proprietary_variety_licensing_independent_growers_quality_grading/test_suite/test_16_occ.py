"""Optimistic concurrency control: stale-version rejection on planting
creation (agreement guard) and on harvest-lot creation (planting guard)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_planting_payload, create_harvest_lot_payload,
    set_clock, create_plant_lot, get_agreement, get_planting,
    setup_active_agreement, setup_planting_confirmed,
    make_grower_principal_headers,
)

COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def test_occ_stale_agreement_version_rejected(api):
    """PRD section 2.7: "If the agreement's current `version` has advanced
    beyond the supplied value — for example because a decision or a prior
    planting creation moved it — the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the agreement
    before booking further plantings against it."

    Design: Corner/cross_cutting/occ_stale_agreement_version_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    variety, grower, agreement = setup_active_agreement()  # version 2
    lot = create_plant_lot(agreement, variety, quantity_plants=2000)
    resp = api.create_planting(
        create_planting_payload(agreement["id"], lot["id"],
                                agreement["version"] - 1, planned_plants=100),
        make_grower_principal_headers(grower["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    rows, meta = validate_paginated(api.list_plantings(
        COMPLIANCE, params={"agreement_id": agreement["id"]}))
    assert rows == [] and meta["total_count"] == 0
    assert get_agreement(agreement["id"])["version"] == agreement["version"]


def test_occ_correct_version_succeeds_then_stale_rejected(api):
    """PRD section 3.5: "it increments the agreement's `version` by 1, because
    the reservation changes the quota picture every other observer of the
    agreement sees."
    PRD section 2.7: "Planning a new planting requires the request to carry
    `expected_agreement_version`, holding the target agreement's `version` as
    the client last observed it."

    Design: Corner/cross_cutting/occ_correct_version_succeeds_then_stale_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    variety, grower, agreement = setup_active_agreement()  # version 2
    lot = create_plant_lot(agreement, variety, quantity_plants=2000)
    headers = make_grower_principal_headers(grower["id"])
    resp = api.create_planting(
        create_planting_payload(agreement["id"], lot["id"],
                                agreement["version"], planned_plants=100),
        headers)
    data = validate_success(resp, 201)
    assert data["status"] == "PLANNED"
    assert get_agreement(agreement["id"])["version"] == agreement["version"] + 1
    replay = api.create_planting(
        create_planting_payload(agreement["id"], lot["id"],
                                agreement["version"], planned_plants=100),
        headers)
    validate_error(replay, ApiErrorId.ERR_STALE_VERSION)
    rows, meta = validate_paginated(api.list_plantings(
        COMPLIANCE, params={"agreement_id": agreement["id"]}))
    assert len(rows) == 1 and meta["total_count"] == 1


def test_occ_stale_planting_version_rejected(api):
    """PRD section 2.7: "Recording a new harvest lot requires the request to
    carry `expected_planting_version`, holding the target planting's `version`
    as the client last observed it. If the planting's current `version` has
    advanced — for example after a confirmation or a prior harvest-lot
    recording moved it — the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting/occ_stale_planting_version_rejected
    """
    bundle = setup_planting_confirmed()  # planting version 2 after confirm
    planting = bundle["planting"]
    set_clock("2026-08-04T00:00:00Z")
    resp = api.create_harvest_lot(
        create_harvest_lot_payload(planting["id"], planting["version"] - 1,
                                   harvested_at="2026-08-03T06:00:00Z",
                                   gross_weight_kg=100),
        make_grower_principal_headers(bundle["grower"]["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    rows, meta = validate_paginated(api.list_harvest_lots(
        COMPLIANCE, params={"planting_id": planting["id"]}))
    assert rows == [] and meta["total_count"] == 0
    current = get_planting(planting["id"])
    assert current["status"] == "PLANTED", "no auto-HARVESTING fired"
