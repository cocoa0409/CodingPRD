"""Laboratory creation, uniqueness, envelope, and pagination tests."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_laboratory,
    create_laboratory,
    create_laboratory_payload,
    get_success_data,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

OFFICER = TEST_USERS["officer_headers"]


def test_laboratory_create_returns_declared_fields_and_applied_state(api):
    """PRD §3.1: "A new laboratory begins life in `APPLIED` accreditation status
    with an `active_discipline_count` of zero."
    PRD §2.5: "`version` (integer): a system-managed counter starting at
    creation that increments by one on every mutation to the resource,
    including mutations driven by cascades originating elsewhere."

    Design: Corner/entities/laboratory_create_returns_declared_fields_and_applied_state
    """
    payload = create_laboratory_payload(name="Apex Regional Lab",
                                        clia_number="45D1000001")
    resp = api.create_laboratory(payload, OFFICER)
    data = validate_success(resp, expected_status=201)
    assert_laboratory(data)
    assert data["accreditation_status"] == "APPLIED"
    assert data["active_discipline_count"] == 0
    assert data["version"] == 1
    assert data["name"] == "Apex Regional Lab"
    assert data["clia_number"] == "45D1000001"
    body = resp.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"]
    assert body["meta"]["api_request_timestamp"]


def test_laboratory_duplicate_clia_rejected(api):
    """PRD §3.1: "An `AccreditationOfficer` registers a laboratory by supplying
    its legal `name` and its CLIA certificate number `clia_number`, which must
    be unique across all laboratories in the system; a duplicate submission is
    rejected with `ERR_DUPLICATE_CLIA`."

    Design: Corner/entities/laboratory_duplicate_clia_rejected
    """
    create_laboratory(name="First Lab", clia_number="45D1000002")
    resp = api.create_laboratory(
        create_laboratory_payload(name="Second Lab", clia_number="45D1000002"),
        OFFICER)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CLIA.value, 409)


def test_laboratory_get_not_found_returns_404(api):
    """PRD §2.7: "The first identifier that does not correspond to an existing
    resource short-circuits the request with the corresponding not-found error"
    PRD §2.7: "(or the generic `ERR_NOT_FOUND`), each with HTTP 404."

    Design: Corner/entities/laboratory_get_not_found_returns_404
    """
    resp = api.get_laboratory(NON_EXISTENT_UUID, OFFICER)
    validate_error_is_one_of(resp, [
        ApiErrorId.ERR_LABORATORY_NOT_FOUND.value,
        ApiErrorId.ERR_NOT_FOUND.value,
    ])
    assert resp.status_code == 404


def test_system_fields_ignore_client_supplied_values(api):
    """PRD §3.1: "A new laboratory begins life in `APPLIED` accreditation status
    with an `active_discipline_count` of zero."
    PRD §2.5: "`id` (string): a unique server-generated identifier formatted as
    a UUID, with no type prefix."

    Design: Corner/entities/system_fields_ignore_client_supplied_values
    """
    payload = create_laboratory_payload(name="Sneaky Lab", clia_number="45D1000006")
    payload["accreditation_status"] = "ACCREDITED"
    payload["version"] = 99
    resp = api.create_laboratory(payload, OFFICER)
    data = validate_success(resp, expected_status=201)
    assert data["accreditation_status"] == "APPLIED"
    assert data["version"] == 1


def test_list_endpoints_paginate_with_defaults(api):
    """PRD §2.3: "`limit` specifies the maximum number of items to return; it
    defaults to 10, with a minimum of 1 and a maximum of 100. `offset`
    specifies how many items to skip and defaults to 0."
    PRD §2.3: "List responses include `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the response envelope."

    Design: Corner/endpoints/list_endpoints_paginate_with_defaults
    """
    create_laboratory(name="Page Lab One", clia_number="45D1000036")
    create_laboratory(name="Page Lab Two", clia_number="45D1000037")
    resp = api.list_laboratories(OFFICER, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
