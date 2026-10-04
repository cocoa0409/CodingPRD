"""Collections and dye-lot batches (PRD §3.1, §3.2): creation defaults and
system fields, field round-trip, enum validation, initial batch state,
release idempotence, sunset lockdown, and per-collection dye-lot uniqueness.
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_batch,
    assert_collection,
    create_batch_payload,
    create_collection_payload,
    create_pcf_report_payload,
    get_collection_version,
    is_valid_uuid,
    set_clock,
    setup_collection_with_batch,
    sunset_collection,
    validate_created,
    validate_error,
    validate_success,
)


def test_collection_create_applies_defaults_and_system_fields(api, admin_headers):
    """PRD §3.1: "The optional `claim_intent` field, defaulting to `NONE` and
    alternatively `CARBON_NEUTRAL` or `CARBON_NEGATIVE`, declares the program's
    ambition for the collection and selects which take-back credit variant
    applies to returns declared under it (§3.5)."
    PRD §3.1: "A new collection is `ACTIVE` with `version` 1."
    PRD §2.5: "The API never consults wall-clock time."

    Design: Corner/entities/collection_create_applies_defaults_and_system_fields
    """
    set_clock()
    resp = api.create_collection(
        {
            "name": "Cirrus",
            "pattern_code": "CIR",
            "backing_type": "STANDARD",
            "lifecycle_boundary": "CRADLE_TO_GRAVE",
        },
        admin_headers,
    )
    data = validate_created(resp)
    assert_collection(data)
    assert data["claim_intent"] == "NONE", "claim_intent default must be NONE"
    assert data["status"] == "ACTIVE"
    assert data["version"] == 1
    assert is_valid_uuid(data["id"]), "id must be a server-minted UUID"
    # Stamped from the logical clock pinned at 2026-09-01T00:00:00Z (PRD §2.5);
    # the instant is pinned, the fractional formatting follows PRD §2.4.
    assert data["created_at"].startswith("2026-09-01T00:00:00")
    assert data["updated_at"] == data["created_at"]


def test_collection_get_round_trips_all_fields(api, admin_headers, manager_headers):
    """PRD §3.1: "A `PlatformAdmin` registers a collection with a display
    `name`, a `pattern_code` shared by all of the collection's dye lots, a
    `backing_type` of either `STANDARD` or `ADHESIVE_FREE_CAPABLE`, and a
    `lifecycle_boundary` of either `CRADLE_TO_GATE` or `CRADLE_TO_GRAVE`."

    Design: Corner/entities/collection_get_round_trips_all_fields
    """
    set_clock()
    resp = api.create_collection(
        {
            "name": "Looplet",
            "pattern_code": "LOP",
            "backing_type": "ADHESIVE_FREE_CAPABLE",
            "lifecycle_boundary": "CRADLE_TO_GRAVE",
            "claim_intent": "CARBON_NEGATIVE",
        },
        admin_headers,
    )
    created = validate_created(resp)
    data = validate_success(api.get_collection(created["id"], manager_headers))
    assert_collection(data)
    assert data["name"] == "Looplet"
    assert data["pattern_code"] == "LOP"
    assert data["backing_type"] == "ADHESIVE_FREE_CAPABLE"
    assert data["lifecycle_boundary"] == "CRADLE_TO_GRAVE"
    assert data["claim_intent"] == "CARBON_NEGATIVE"
    assert data["status"] == "ACTIVE"
    assert data["version"] == 1


def test_collection_create_with_invalid_backing_type_returns_invalid_request(
    api, admin_headers
):
    """PRD §2.8 (rule 11): "and general request shape — required fields
    present, enum members known, `vintage_year` at least 2020,
    `target_reduction_pct` strictly between 0 and 1, quantities positive
    (`ERR_INVALID_REQUEST`, 400)."

    Design: Corner/entities/collection_create_with_invalid_backing_type_returns_invalid_request
    """
    set_clock()
    payload = create_collection_payload(
        name="Bad", pattern_code="BAD", backing_type="MAGNETIC",
        lifecycle_boundary="CRADLE_TO_GATE",
    )
    resp = api.create_collection(payload, admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_batch_created_quarantine_with_full_availability_and_empty_mix(
    api, admin_headers
):
    """PRD §3.2: "A new batch enters `QUARANTINE` with its `available_m2`
    initialized to the full `produced_m2`, an empty `feedstock_mix`, and the
    batch's `collection_id` taken from the creation path."
    PRD §3.2: "While the mix is empty the total mass is zero and
    `recycled_content_pct` is undefined (null)."
    PRD §3.2: "The batch's `allocated_mass_kg` is the plain sum of all
    mix-entry quantities and is the number the release gate checks."

    Design: Corner/entities/batch_created_quarantine_with_full_availability_and_empty_mix
    """
    set_clock()
    col = validate_created(
        api.create_collection(create_collection_payload(), admin_headers)
    )
    resp = api.create_batch(col["id"], create_batch_payload(), admin_headers)
    batch = validate_created(resp)
    assert_batch(batch)
    assert batch["status"] == "QUARANTINE"
    assert batch["available_m2"] == 100
    assert batch["feedstock_mix"] == []
    assert batch["allocated_mass_kg"] == 0
    assert batch["recycled_content_pct"] is None


def test_batch_release_from_released_returns_409(api, admin_headers):
    """PRD §2.8 (rule 5): "The target resource is in a state from which the
    requested transition exists; otherwise `ERR_INVALID_STATE` (HTTP 409)."
    PRD §3.2: "A successful release moves the batch from `QUARANTINE` to
    `RELEASED` and re-validates both computed fields one final time."

    Design: Corner/state_machines/batch_release_from_released_returns_409
    """
    set_clock()
    built = setup_collection_with_batch()
    batch = built["batch"]
    assert batch["status"] == "RELEASED"
    resp = api.release_batch(batch["id"], admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    data = validate_success(api.get_batch(batch["id"], admin_headers))
    assert data["status"] == "RELEASED"
    # Canonical 100 m2 mix: 200 kg fishing-net @0.50 + 200 kg virgin @2.10,
    # intensity 1.2 -> recycled 50.00, embodied 6.400 (PRD §3.2 formulas).
    assert data["recycled_content_pct"] == 50.00
    assert data["embodied_carbon_kg_per_m2"] == 6.400


def test_sunset_is_terminal_and_blocks_new_children(
    api, admin_headers, manager_headers
):
    """PRD §3.1: "Sunset is a gate on new work, not a retraction of history:
    creating a dye-lot batch under a `SUNSET` collection, creating a footprint
    report against one, or submitting a report belonging to one are all
    rejected with `ERR_COLLECTION_SUNSET` (HTTP 409), while reports, claims,
    and packages already published remain exactly as they were."
    PRD §2.8 (rule 5): "The target resource is in a state from which the
    requested transition exists; otherwise `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/sunset_is_terminal_and_blocks_new_children
    """
    set_clock()
    col = validate_created(
        api.create_collection(create_collection_payload(), admin_headers)
    )
    sunset_collection(col["id"])
    # SUNSET is terminal: a second sunset has no transition.
    validate_error(
        api.sunset_collection(col["id"], admin_headers), ApiErrorId.ERR_INVALID_STATE
    )
    # New batch under a SUNSET collection is gated.
    validate_error(
        api.create_batch(
            col["id"],
            create_batch_payload(dye_lot_code="DL-X"),
            admin_headers,
        ),
        ApiErrorId.ERR_COLLECTION_SUNSET,
    )
    # New report against a SUNSET collection is gated; the optimistic-concurrency
    # version is re-read fresh so the state guard is what fires (PRD §2.8).
    payload = create_pcf_report_payload(col["id"], get_collection_version(col["id"]))
    validate_error(
        api.create_pcf_report(payload, manager_headers),
        ApiErrorId.ERR_COLLECTION_SUNSET,
    )
    # Sunset is not deletion: reads keep working and show the terminal state.
    data = validate_success(api.get_collection(col["id"], admin_headers))
    assert data["status"] == "SUNSET"


def test_dye_lot_conflict_scoped_per_collection(api, admin_headers):
    """PRD §3.2: "The `dye_lot_code` must be unique within its collection; a
    duplicate is rejected with `ERR_DYE_LOT_CONFLICT` (HTTP 409)."

    Design: Corner/validations/dye_lot_conflict_scoped_per_collection
    """
    set_clock()
    col_a = validate_created(
        api.create_collection(create_collection_payload(), admin_headers)
    )
    col_b = validate_created(
        api.create_collection(
            create_collection_payload(
                name="Gravia", pattern_code="GRV", lifecycle_boundary="CRADLE_TO_GRAVE"
            ),
            admin_headers,
        )
    )
    validate_created(
        api.create_batch(col_a["id"], create_batch_payload(), admin_headers)
    )
    # Same code inside the same collection is rejected...
    validate_error(
        api.create_batch(
            col_a["id"],
            create_batch_payload(production_date="2026-09-06T00:00:00Z"),
            admin_headers,
        ),
        ApiErrorId.ERR_DYE_LOT_CONFLICT,
    )
    # ...while the same code under a different collection is accepted.
    resp = api.create_batch(
        col_b["id"],
        create_batch_payload(production_date="2026-09-06T00:00:00Z"),
        admin_headers,
    )
    batch = validate_created(resp)
    assert batch["dye_lot_code"] == "DL-100"
