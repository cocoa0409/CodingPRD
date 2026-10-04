"""Corner breadth index (entities): coating-system creation echoes, defaults,
required-field and enum closure, the profile-band constraint, not-found
lookup, and the list pagination envelope.

Note on ``version``: the PRD pins ``version`` as an integer that increments
by one on every modification (§2.4) but does not state its initial value, so
these tests assert the field's presence and positivity rather than a literal
starting number.
"""
from test_helpers import (
    PLATFORM_ADMIN_HEADERS,
    TECHNICAL_SERVICE_ENGINEER_HEADERS,
    ApiClient,
    ApiErrorId,
    assert_coating_system,
    assert_envelope_meta,
    assert_list_page,
    coating_system_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_coating_system_creation_happy_path_echoes_inputs(api: ApiClient):
    """PRD §3.1: "A newly registered system begins life `ACTIVE` with
    `spec_revision` set to 1."
    PRD §3.1: "Two fields carry defaults: `is_competitor_system` defaults to
    false and is set true only when the record describes a competing,
    non-house system named in a substitution request".

    Design: Corner/entities/coating_system_creation_happy_path_echoes_inputs
    """
    payload = coating_system_payload(
        system_code="SW-ECHO-01",
        coat_count=3,
        total_dft_min_mils=9.0,
        total_dft_max_mils=15.0,
        base_voc_gpl=250,
        thinner_voc_gpl=420,
        max_thinner_pct=0.10,
    )
    system = validate_success(
        api.create_coating_system(payload, TECHNICAL_SERVICE_ENGINEER_HEADERS),
        expected_status=201,
    )

    assert_coating_system(system)
    assert system["status"] == "ACTIVE"
    assert system["spec_revision"] == 1
    assert system["system_code"] == "SW-ECHO-01"
    assert system["coat_count"] == 3
    assert system["base_voc_gpl"] == 250
    assert system["max_thinner_pct"] == 0.10
    assert system["is_competitor_system"] is False


def test_coating_system_creation_defaults_applied(api: ApiClient):
    """PRD §3.1: "Two fields carry defaults: `is_competitor_system` defaults
    to false and is set true only when the record describes a competing,
    non-house system named in a substitution request; and `max_thinner_pct`,
    the maximum permitted thinner addition as a fraction of mixed volume,
    defaults to 0 and may range from 0 up to 0.25."

    Design: Corner/entities/coating_system_creation_defaults_applied
    """
    payload = coating_system_payload(system_code="SW-DFLT-01", surface_prep_standard="SSPC_SP6_COMMERCIAL")
    payload.pop("is_competitor_system", None)
    del payload["max_thinner_pct"]

    system = validate_success(
        api.create_coating_system(payload, TECHNICAL_SERVICE_ENGINEER_HEADERS),
        expected_status=201,
    )
    assert system["is_competitor_system"] is False
    assert system["max_thinner_pct"] == 0


def test_coating_system_creation_missing_required_field_rejected(api: ApiClient):
    """PRD §2.8: "a request body that is missing a required field, supplies a
    value of the wrong type, names an enumeration value outside the defined
    set, or violates an array cardinality rule — fewer than three spot
    film-thickness readings, zero adhesion readings, or a non-positive tested
    area — is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/coating_system_creation_missing_required_field_rejected
    """
    payload = coating_system_payload(system_code="SW-MISS-01")
    del payload["total_dft_min_mils"]

    response = api.create_coating_system(payload, TECHNICAL_SERVICE_ENGINEER_HEADERS)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    rows, meta = validate_paginated(api.list_coating_systems(PLATFORM_ADMIN_HEADERS))
    assert meta["total_count"] == 0 and rows == [], "no row may be persisted"


def test_coating_system_creation_invalid_enum_rejected(api: ApiClient):
    """PRD §2.8: "a request body that is missing a required field, supplies a
    value of the wrong type, names an enumeration value outside the defined
    set, or violates an array cardinality rule — fewer than three spot
    film-thickness readings, zero adhesion readings, or a non-positive tested
    area — is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.1: "the required `surface_prep_standard` — one of
    `SSPC_SP10_NEAR_WHITE`, `SSPC_SP6_COMMERCIAL`, `SSPC_SP11_POWER_TOOL`, or
    `SSPC_SP1_SOLVENT`".

    Design: Corner/entities/coating_system_creation_invalid_enum_rejected
    """
    payload = coating_system_payload(
        system_code="SW-ENUM-01", surface_prep_standard="SSPC_SP7_BRUSH_OFF"
    )
    response = api.create_coating_system(payload, TECHNICAL_SERVICE_ENGINEER_HEADERS)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_coating_system_profile_max_below_min_rejected(api: ApiClient):
    """PRD §3.1: "the acceptable anchor-profile band `min_surface_profile_mils`
    through `max_surface_profile_mils` (the maximum must be at least the
    minimum)" and "A request that violates any of these shapes — an inverted
    profile band, a coat count outside 1 through 4, a thinner ceiling above
    one quarter of mixed volume — is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/coating_system_profile_max_below_min_rejected
    """
    payload = coating_system_payload(
        system_code="SW-PROF-01", min_surface_profile_mils=4.0, max_surface_profile_mils=2.0
    )
    response = api.create_coating_system(payload, TECHNICAL_SERVICE_ENGINEER_HEADERS)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_coating_system_not_found_on_get(api: ApiClient):
    """PRD §2.8: "the server validates the identifiers' existence
    sequentially, left to right, and rejects the request immediately with the
    not-found error corresponding to the first identifier that does not
    resolve to an existing resource". The not-found catalog includes
    `ERR_COATING_SYSTEM_NOT_FOUND` (HTTP 404).

    Design: Corner/entities/coating_system_not_found_on_get
    """
    response = api.get_coating_system(
        "00000000-0000-4000-8000-0000000000ff", PLATFORM_ADMIN_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_COATING_SYSTEM_NOT_FOUND, expected_status=404)


def test_coating_system_list_pagination_envelope(api: ApiClient):
    """PRD §2.3: "The `limit` parameter sets the maximum number of items
    returned: it defaults to 10 when omitted, and any supplied value must be
    at least 1 and at most 100. The `offset` parameter sets the number of
    items skipped before the page begins and defaults to 0."
    PRD §2.3: "The `meta` object of a list response carries four pagination
    fields: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/coating_system_list_pagination_envelope
    """
    for index in range(1, 4):
        validate_success(
            api.create_coating_system(
                coating_system_payload(system_code=f"SW-PAGE-{index}"),
                TECHNICAL_SERVICE_ENGINEER_HEADERS,
            ),
            expected_status=201,
        )

    first_page = api.list_coating_systems(PLATFORM_ADMIN_HEADERS, params={"limit": 2, "offset": 0})
    body = first_page.json()
    assert_envelope_meta(body)
    rows, meta = validate_paginated(first_page)
    assert body["response_type"] == "array"
    assert len(rows) == 2
    assert_list_page(meta, limit=2, offset=0, total=3, has_more=True)

    last_page = api.list_coating_systems(PLATFORM_ADMIN_HEADERS, params={"limit": 2, "offset": 2})
    rows, meta = validate_paginated(last_page)
    assert len(rows) == 1
    assert_list_page(meta, limit=2, offset=2, total=3, has_more=False)
