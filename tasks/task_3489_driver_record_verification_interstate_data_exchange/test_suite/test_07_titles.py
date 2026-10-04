"""Vehicle titling and the brand-washing defense: defaults, the TITLE_NETWORK
gate, the brand union, and the completion cascade."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_created,
    assert_error,
    assert_title_transfer,
    assert_vehicle_title,
    certify_participation,
    complete_title_transfer,
    create_jurisdiction,
    create_title_transfer,
    create_vehicle_title,
    enroll_participation,
    list_jurisdiction_titles,
    list_title_transfers,
    make_jurisdiction_registrar_headers,
    read_jurisdiction,
    setup_certified_jurisdiction,
    setup_title_world,
    title_transfer_payload,
    vehicle_title_payload,
)


def test_vehicle_title_brands_default_empty(api):
    """PRD §3.7: "A registrar titles a vehicle in its own jurisdiction by supplying a
    seventeen-character `vin` and, optionally, a `brands` set drawn from `SALVAGE`,
    `FLOOD`, `REBUILT`, and `JUNK`, defaulting to empty when omitted."
    PRD §3.7: "The title is created `ACTIVE` with `holding_jurisdiction_id` set to the
    caller's jurisdiction and `washing_alert` false."

    Design: Corner/entities/vehicle_title_brands_default_empty
    """
    ctx = setup_certified_jurisdiction(
        api, code="AA", systems=("POINTER_NETWORK", "TITLE_NETWORK")
    )
    resp = api.create_vehicle_title(
        vehicle_title_payload("1FTFW1ET5DFC10312"),  # brands omitted entirely
        make_jurisdiction_registrar_headers(ctx["jurisdiction_id"]),
    )
    title = assert_created(resp)
    assert_vehicle_title(title)
    assert title["brands"] == [], "the brand set defaults to empty"
    assert title["status"] == "ACTIVE"
    assert title["washing_alert"] is False


def test_vehicle_title_creation_blocked_without_title_network(api):
    """PRD §3.7: "The titling jurisdiction must be `ACTIVE` with a `CERTIFIED`
    `TITLE_NETWORK` participation."
    PRD §2.6: "then a participation-certification failure as
    `ERR_PARTICIPATION_NOT_CERTIFIED`" (HTTP 409).

    Design: Difficulty/cross_entity_state_dependency/vehicle_title_creation_blocked_without_title_network
    """
    # ACTIVE jurisdiction certified for POINTER_NETWORK only — the membership gate
    # passes, the TITLE_NETWORK certification gate fails.
    ctx = setup_certified_jurisdiction(api, code="BB", systems=("POINTER_NETWORK",))
    resp = api.create_vehicle_title(
        vehicle_title_payload("5YJSA1E26HF1B0001", []),
        make_jurisdiction_registrar_headers(ctx["jurisdiction_id"]),
    )
    assert_error(resp, ApiErrorId.ERR_PARTICIPATION_NOT_CERTIFIED)

    # Granting the TITLE_NETWORK participation flips the identical request to success.
    title_participation = enroll_participation(api, ctx["jurisdiction_id"], "TITLE_NETWORK")
    certify_participation(api, title_participation["id"], score=94)
    resp = api.create_vehicle_title(
        vehicle_title_payload("5YJSA1E26HF1B0001", []),
        make_jurisdiction_registrar_headers(ctx["jurisdiction_id"]),
    )
    title = assert_created(resp)
    assert title["status"] == "ACTIVE"
    assert read_jurisdiction(api, ctx["jurisdiction_id"])["membership_status"] == "ACTIVE"


def test_title_transfer_empty_brand_set_boundary(api):
    """PRD §3.7: "The empty boundary passes cleanly: when the source brands and the
    disclosure are both empty, verification succeeds and the carried set is empty."
    PRD §3.7: "Otherwise the `carried_brands` are computed as the union of the source
    brands and the disclosed brands, sorted alphabetically for determinism, and the
    transfer is created in `VERIFIED` status."

    Design: Difficulty/boundary_precision_check/title_transfer_empty_brand_set_boundary
    """
    world = setup_title_world(api, from_code="AA", to_code="BB", source_brands=[])
    transfer = create_title_transfer(
        api, world["title_id"], world["to_ctx"]["jurisdiction_id"], []
    )
    assert_title_transfer(transfer)
    assert transfer["status"] == "VERIFIED"
    assert transfer["carried_brands"] == []
    rows, _ = list_jurisdiction_titles(api, world["from_ctx"]["jurisdiction_id"])
    assert rows[0]["washing_alert"] is False, "no washing attempt was recorded"


def test_title_transfer_complete_moves_title_and_carries_brands(api):
    """PRD §3.7: "On completion the source title goes `ACTIVE` → `EXPORTED`; a new title
    springs up in the receiving jurisdiction carrying the same VIN, `brands` equal to
    the `carried_brands`, status `ACTIVE`, and a fresh `washing_alert` of false; and the
    transfer's `new_title_id` — null until now — is set as the transfer moves `VERIFIED`
    → `COMPLETED`, its terminal state."
    PRD §3.7: "the `carried_brands` are computed as the union of the source brands and
    the disclosed brands, sorted alphabetically for determinism".

    Design: Corner/state_machines/title_transfer_complete_moves_title_and_carries_brands
    """
    world = setup_title_world(
        api, from_code="AA", to_code="BB", source_brands=["SALVAGE"]
    )
    transfer = create_title_transfer(
        api, world["title_id"], world["to_ctx"]["jurisdiction_id"], ["FLOOD", "SALVAGE"]
    )
    assert transfer["carried_brands"] == ["FLOOD", "SALVAGE"], (
        "sorted alphabetical union of source and disclosed brands"
    )

    completed = complete_title_transfer(
        api, transfer["id"], world["to_ctx"]["jurisdiction_id"]
    )
    assert_title_transfer(completed)
    assert completed["status"] == "COMPLETED"
    assert completed["new_title_id"] is not None

    source_rows, _ = list_jurisdiction_titles(api, world["from_ctx"]["jurisdiction_id"])
    assert source_rows[0]["status"] == "EXPORTED"
    new_rows, _ = list_jurisdiction_titles(api, world["to_ctx"]["jurisdiction_id"])
    assert new_rows[0]["id"] == completed["new_title_id"]
    assert new_rows[0]["brands"] == ["FLOOD", "SALVAGE"]
    assert new_rows[0]["washing_alert"] is False


def test_brand_washing_rejected_and_flagged(api):
    """PRD §3.7: "If the disclosed set is not a superset of the source title's brands —
    that is, any brand on the source title is missing from the disclosure — the request
    is rejected with `ERR_BRAND_DISCLOSURE_MISMATCH`, the source title's `washing_alert`
    is set to true as a permanent marker (once set, it is never cleared), and no
    transfer is persisted."

    Design: Corner/errors/brand_washing_rejected_and_flagged
    """
    world = setup_title_world(
        api,
        from_code="AA",
        to_code="BB",
        vin="9BWDE5202J0011223",
        source_brands=["SALVAGE", "FLOOD"],
    )
    resp = api.create_title_transfer(
        title_transfer_payload(world["title_id"], ["SALVAGE"]),
        make_jurisdiction_registrar_headers(world["to_ctx"]["jurisdiction_id"]),
    )
    assert_error(resp, ApiErrorId.ERR_BRAND_DISCLOSURE_MISMATCH)

    rows, _ = list_jurisdiction_titles(api, world["from_ctx"]["jurisdiction_id"])
    assert rows[0]["washing_alert"] is True, "the washing attempt latches on the source title"
    assert rows[0]["status"] == "ACTIVE", "the title itself is otherwise unaffected"
    transfers, meta = list_title_transfers(
        api, params={"vehicle_title_id": world["title_id"]}
    )
    assert meta["total_count"] == 0 and transfers == [], "no transfer was persisted"


def test_vin_duplicate_active_title_rejected(api):
    """PRD §3.7: "At most one `ACTIVE` title exists per VIN across the exchange: a
    duplicate is rejected with `ERR_VIN_ALREADY_TITLED`."

    Design: Corner/errors/vin_duplicate_active_title_rejected
    """
    ctx = setup_certified_jurisdiction(
        api, code="AA", systems=("POINTER_NETWORK", "TITLE_NETWORK")
    )
    create_vehicle_title(api, ctx["jurisdiction_id"], "1FTFW1ET5DFC10312")
    resp = api.create_vehicle_title(
        vehicle_title_payload("1FTFW1ET5DFC10312", ["REBUILT"]),
        make_jurisdiction_registrar_headers(ctx["jurisdiction_id"]),
    )
    assert_error(resp, ApiErrorId.ERR_VIN_ALREADY_TITLED)


def test_same_jurisdiction_title_transfer_rejected(api):
    """PRD §3.7: "The receiving jurisdiction must differ from the source title's holding
    jurisdiction — a same-jurisdiction request is `ERR_SAME_JURISDICTION_TRANSFER`".

    Design: Corner/errors/same_jurisdiction_title_transfer_rejected
    """
    ctx = setup_certified_jurisdiction(
        api, code="AA", systems=("POINTER_NETWORK", "TITLE_NETWORK")
    )
    title = create_vehicle_title(
        api, ctx["jurisdiction_id"], "2C3CDXBG8NH100200", ["REBUILT"]
    )
    resp = api.create_title_transfer(
        title_transfer_payload(title["id"], ["REBUILT"]),
        make_jurisdiction_registrar_headers(ctx["jurisdiction_id"]),
    )
    assert_error(resp, ApiErrorId.ERR_SAME_JURISDICTION_TRANSFER)


def test_title_transfer_unknown_vehicle_title_not_found(api):
    """PRD §2.6: "Path identifiers and body foreign keys must reference existing
    resources, validated left to right; the first missing reference yields the
    corresponding not-found error" — here `ERR_TITLE_NOT_FOUND` (HTTP 404).

    Design: Corner/errors/title_transfer_unknown_vehicle_title_not_found
    """
    jurisdiction = create_jurisdiction(api, code="BB", name="State B", fee_tier="TIER_2")
    resp = api.create_title_transfer(
        title_transfer_payload(NON_EXISTENT_UUID, []),
        make_jurisdiction_registrar_headers(jurisdiction["id"]),
    )
    assert_error(resp, ApiErrorId.ERR_TITLE_NOT_FOUND)


def test_complete_unknown_title_transfer_not_found(api):
    """PRD §2.6: "Path identifiers and body foreign keys must reference existing
    resources, validated left to right; the first missing reference yields the
    corresponding not-found error" — here `ERR_TITLE_TRANSFER_NOT_FOUND` (HTTP 404).

    Design: Corner/errors/complete_unknown_title_transfer_not_found
    """
    jurisdiction = create_jurisdiction(api, code="BB", name="State B", fee_tier="TIER_2")
    resp = api.complete_title_transfer(
        NON_EXISTENT_UUID,
        make_jurisdiction_registrar_headers(jurisdiction["id"]),
    )
    assert_error(resp, ApiErrorId.ERR_TITLE_TRANSFER_NOT_FOUND)
