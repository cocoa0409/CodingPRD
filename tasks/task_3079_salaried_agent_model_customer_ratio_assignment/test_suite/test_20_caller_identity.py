"""Corner tests — caller identity checks (queue B)."""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    validate_error,
    ApiErrorId,
    PLATFORM_ADMIN,
    anonymous_headers,
    create_region,
    set_clock,
)


@pytest.fixture(autouse=True)
def _clock():
    set_clock()


def test_a_request_without_a_role_header_is_refused_as_unauthenticated():
    """PRD §2.1: "A request that omits either header, or presents a role outside this set, is refused with `ERR_UNAUTHENTICATED` (HTTP 401); this is the only authentication check and it runs ahead of everything else, on every endpoint except the region-creation and single-region-read operations named in §4."

    Design: Corner/validations/request_without_a_role_header_returns_unauthenticated
    """
    region = create_region()

    resp = api_client.create_agent({"region_id": region["id"]}, anonymous_headers())
    assert resp.status_code == 401, resp.text
    data = validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
    assert data["error_id"] == "ERR_UNAUTHENTICATED", data
    assert data["error_id"] != "ERR_INVALID_REQUEST", data


def test_an_unauthenticated_write_persists_no_agent():
    """PRD §2.1: "Header authentication comes first, so a request with no usable identity never reaches an entitlement check."

    Design: Corner/validations/request_without_a_role_header_returns_unauthenticated
    """
    region = create_region()
    api_client.create_agent({"region_id": region["id"]}, anonymous_headers())

    listed = get_success_data(api_client.list_agents(
        PLATFORM_ADMIN, params={"region_id": region["id"]},
    ))
    rows = listed if isinstance(listed, list) else listed.get("data", [])
    assert rows == [], rows