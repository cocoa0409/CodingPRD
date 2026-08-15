"""Response envelope, resource creation defaults, and pagination (PRD §2)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_contestant,
    assert_rodeo,
    assert_rodeo_event,
    assert_vet_report,
    create_rodeo,
    create_rodeo_event_payload,
    create_rodeo_payload,
    create_vet_report_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    register_contestant,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["committee_admin_headers"]
OFFICE = TEST_USERS["entry_office_headers"]
VET = TEST_USERS["veterinarian_headers"]


def test_response_envelope_shape_on_success_and_error(api):
    """PRD §2.2: "All successful API responses (those with 2xx status codes)
    follow this standard envelope format in their JSON body:" and "All error
    API responses (4xx status codes) follow this standard envelope format:".
    PRD §2.7: "The first missing reference — path or body — produces the
    `ERR_NOT_FOUND` (HTTP 404) rejection."

    Design: Corner/endpoints/response_envelope_shape_on_success_and_error
    """
    created = validate_success(
        api.create_rodeo(
            create_rodeo_payload(name="Envelope Rodeo", city="Envelope"), ADMIN
        ),
        201,
    )
    assert_rodeo(created)

    fetched = validate_success(api.get_rodeo(created["id"], ADMIN), 200)
    assert fetched["id"] == created["id"]

    missing = api.get_rodeo(NON_EXISTENT_UUID, ADMIN)
    err = validate_error(missing, ApiErrorId.ERR_NOT_FOUND)
    assert isinstance(err["message"], str) and err["message"].strip()


def test_rodeo_create_defaults_and_system_fields(api):
    """PRD §3.1: "The rodeo opens in `DRAFT` posture with
    `unclaimed_purse_cents` at zero."
    PRD §2.5: every primary resource carries "`id` (string): a unique,
    server-minted identifier formatted as a UUID, with no type prefix" and
    "`created_at` (string): an ISO 8601 UTC timestamp with three fractional
    digits, set when the resource is created."

    Design: Corner/entities/rodeo_create_defaults_and_system_fields
    """
    resp = api.create_rodeo(
        create_rodeo_payload(
            name="Albuquerque Rodeo",
            city="Albuquerque",
            entries_close_at="2026-08-10T00:00:00Z",
        ),
        ADMIN,
    )
    assert resp.status_code == 201, f"expected 201, got {resp.status_code}"
    body = resp.json()
    assert body["response_type"] == "object"
    data = body["data"]
    assert_rodeo(data)
    assert data["posture"] == "DRAFT", f"new rodeo must open DRAFT: {data['posture']}"
    assert data["unclaimed_purse_cents"] == 0
    assert is_valid_uuid(data["id"])
    # Three fractional digits on created_at (PRD §2.5).
    assert is_iso8601_timestamp(data["created_at"])
    assert "." in data["created_at"] and len(
        data["created_at"].split(".")[1].rstrip("Z")
    ) == 3, f"created_at must carry three fractional digits: {data['created_at']}"


def test_rodeo_event_discipline_computed_from_code(api):
    """PRD §3.1: "the server derives `discipline` from it: `ROUGH_STOCK` for
    the three riding events (`BAREBACK`, `SADDLE_BRONC`, `BULL_RIDING`) and
    `TIMED` for the remaining four."

    Design: Corner/entities/rodeo_event_discipline_computed_from_code
    """
    rodeo = create_rodeo(name="Amarillo Rodeo", city="Amarillo")
    rough = validate_success(
        api.create_rodeo_event(
            create_rodeo_event_payload(rodeo["id"], event_code="BULL_RIDING"), ADMIN
        ),
        201,
    )
    timed = validate_success(
        api.create_rodeo_event(
            create_rodeo_event_payload(
                rodeo["id"], event_code="BARREL_RACING", go_rounds=2, payout_places=2
            ),
            ADMIN,
        ),
        201,
    )
    assert_rodeo_event(rough)
    assert_rodeo_event(timed)
    assert rough["discipline"] == "ROUGH_STOCK"
    assert timed["discipline"] == "TIMED"


def test_rodeo_event_invalid_event_code_rejected(api):
    """PRD §3.1: "The `event_code` is one of `BAREBACK`, `SADDLE_BRONC`,
    `BULL_RIDING`, `TIE_DOWN_ROPING`, `STEER_WRESTLING`, `TEAM_ROPING`, or
    `BARREL_RACING`" and "A value outside any of these shapes is rejected with
    `ERR_VALIDATION`."

    Design: Corner/entities/rodeo_event_invalid_event_code_rejected
    """
    rodeo = create_rodeo(name="Amarillo Rodeo", city="Amarillo")
    resp = api.create_rodeo_event(
        create_rodeo_event_payload(rodeo["id"], event_code="MUTTON_BUSTIN"), ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)

    data, meta = validate_paginated(
        api.list_rodeo_events(ADMIN, params={"rodeo_id": rodeo["id"]})
    )
    assert data == [], f"no event may be persisted after a 400, got {data}"
    assert meta["total_count"] == 0


def test_entry_get_nonexistent_returns_not_found(api):
    """PRD §2.7: "The first missing reference — path or body — produces the
    `ERR_NOT_FOUND` (HTTP 404) rejection."

    Design: Corner/entities/entry_get_nonexistent_returns_not_found
    """
    resp = api.get_entry(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    body = resp.json()
    assert body["response_type"] == "error"


def test_contestant_list_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned: it
    defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
    parameter says how many items to skip and defaults to 0." and "Paginated
    list responses carry `limit`, `offset`, `total_count`, and `has_more` in
    the `meta` object of the envelope."

    Design: Corner/entities/contestant_list_pagination_envelope
    """
    c1 = register_contestant("PRCA-201", "Rider One")
    c2 = register_contestant("PRCA-202", "Rider Two")

    page1, meta1 = validate_paginated(
        api.list_contestants(ADMIN, params={"limit": 1, "offset": 0})
    )
    assert len(page1) == 1
    assert meta1["total_count"] == 2
    assert meta1["has_more"] is True
    assert meta1["limit"] == 1
    assert meta1["offset"] == 0

    page2, meta2 = validate_paginated(
        api.list_contestants(ADMIN, params={"limit": 1, "offset": 1})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 2
    assert meta2["has_more"] is False

    seen = {page1[0]["id"], page2[0]["id"]}
    assert seen == {c1["id"], c2["id"]}, "both pages together must cover both contestants"
    for row in page1 + page2:
        assert_contestant(row)


def test_vet_report_immutable_common_fields_absent(api):
    """PRD §2.5: "Vet reports are the one exception. A vet report is immutable
    once filed: it carries `id` and `created_at` only, and both `updated_at`
    and `version` are absent from it."

    Design: Corner/entities/vet_report_immutable_common_fields_absent
    """
    contestant = register_contestant("PRCA-210", "Rider Ten")
    created = validate_success(
        api.create_vet_report(
            create_vet_report_payload(
                subject_type="CONTESTANT",
                contestant_id=contestant["id"],
                findings="Concussion protocol",
                disposition="INJURED_TURNOUT",
                veterinarian_name="Dr. Ellis",
            ),
            VET,
        ),
        201,
    )
    assert_vet_report(created)

    fetched = validate_success(api.get_vet_report(created["id"], VET), 200)
    assert_vet_report(fetched)


def test_contestant_version_increments_on_each_mutation(api):
    """PRD §2.5: "`version` (integer): a system-managed integer that increments
    by one on every mutation, including mutations caused by cascade side
    effects rather than a direct client call on that resource."
    PRD §3.2: "Either patch increments the contestant's `version`."

    Design: Corner/complexity_layers/contestant_version_increments_on_each_mutation
    """
    created = validate_success(
        api.create_contestant(
            {"card_number": "PRCA-498", "full_name": "Rider Ver"}, OFFICE
        ),
        201,
    )
    v1 = created["version"]
    assert isinstance(v1, int)
    created_stamp = created["created_at"]
    assert is_iso8601_timestamp(created_stamp)

    suspended = validate_success(
        api.patch_contestant(created["id"], {"status": "SUSPENDED"}, ADMIN), 200
    )
    assert suspended["version"] == v1 + 1, (
        f"SUSPENDED patch must increment version by exactly one: "
        f"{v1} -> {suspended['version']}"
    )
    assert suspended["created_at"] == created_stamp
    assert is_iso8601_timestamp(suspended["updated_at"])

    reinstated = validate_success(
        api.patch_contestant(created["id"], {"status": "GOOD_STANDING"}, ADMIN), 200
    )
    assert reinstated["version"] == v1 + 2, (
        f"reinstatement patch must increment version by exactly one again: "
        f"{v1 + 1} -> {reinstated['version']}"
    )
