"""Design authoring, retrieval and design listing."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_design,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    DESIGN_OPS,
    create_design,
    create_licensor,
    get_design,
    set_clock,
)


def test_design_round_trips_team_only_artwork_and_null_approved_version(api):
    """PRD §3.1: "A newly authored design is written in
    `PENDING_LICENSOR_APPROVAL` with `approved_version` null and
    `rejection_reason` null; the `approved_version` property stays null for the
    whole of the design's unapproved life and is populated only at the moment of
    approval."
    PRD §3.1: "the player whose marks appear on it through `player_code` -
    which is supplied only when the artwork carries an individual player's marks
    and is null for team-only artwork"

    Design: Corner/entities/design_get_round_trips_player_code_and_null_approved_version
    """
    set_clock(api)
    licensor = create_licensor(api, name="NBL Marks B", royalty_rate_pct=0.1,
                               minimum_guarantee_cents=100000)

    created = validate_success(
        api.create_design(
            {
                "licensor_id": licensor["id"],
                "team_code": "ATL",
                "garment_sku": "TRACTOR",
                "design_name": "ATL Team Tractor",
            },
            DESIGN_OPS,
        ),
        expected_status=201,
    )

    read = get_design(api, created["id"])
    assert read["player_code"] is None
    assert read["approved_version"] is None
    assert read["rejection_reason"] is None
    assert read["approval_state"] == "PENDING_LICENSOR_APPROVAL"
    assert read["garment_sku"] == "TRACTOR"
    assert read["team_code"] == "ATL"
    assert read["licensor_id"] == licensor["id"]
    assert_design(read)


def test_design_read_wraps_the_resource_in_an_object_envelope(api):
    """PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/entities/design_get_round_trips_player_code_and_null_approved_version
    """
    set_clock(api)
    licensor = create_licensor(api, name="NBL Envelope")
    design = create_design(api, licensor, approve=False, garment_sku="CAP")

    resp = api.get_design(design["id"], DESIGN_OPS)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["response_type"] == "object"
    assert body["data"]["id"] == design["id"]


def test_design_list_is_scoped_by_licensor(api):
    """PRD §4: "GET | `/designs` | List designs, optionally scoped to one licensor
    or approval state | DesignOps, ProductionPlanner, AuditOnly"
    PRD §2.3: "Every list response reports `limit`, `offset`, `total_count` and
    `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/designs_list_filtered_by_licensor_and_state
    """
    set_clock(api)
    licensor_c = create_licensor(api, name="Licensor C", league_code="NBL")
    licensor_d = create_licensor(api, name="Licensor D", league_code="NBLM")
    design_c = create_design(api, licensor_c, approve=False, team_code="ATL",
                             garment_sku="CAP", design_name="C Cap")
    create_design(api, licensor_d, approve=False, team_code="BOS",
                  garment_sku="MINI", design_name="D Mini")

    resp = api.list_designs(DESIGN_OPS, params={"licensor_id": licensor_c["id"]})
    rows, meta = validate_paginated(resp)

    assert len(rows) == 1, f"expected exactly one scoped design, got {rows}"
    assert rows[0]["id"] == design_c["id"]
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field in meta, f"pagination field {field} missing from meta"


def test_design_read_of_unknown_id_returns_not_found(api):
    """PRD §2.10: "a path identifier that resolves to nothing yields
    `ERR_NOT_FOUND` (HTTP 404)"

    Design: Corner/entities/design_get_unknown_id_returns_not_found
    """
    set_clock(api)

    resp = api.get_design(NON_EXISTENT_UUID, DESIGN_OPS)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    body = resp.json()
    assert body["response_type"] == "error"
    assert "id" not in body["data"], "an error body carries no design object"


@pytest.mark.parametrize("sku", ["JERSEY", "TRACTOR", "DUFFEL", "CAP", "MINI", "PENNANT"])
def test_design_accepts_every_declared_garment_sku(api, sku):
    """PRD §3.1: "The `garment_sku` must be one of `JERSEY`, `TRACTOR`, `DUFFEL`,
    `CAP`, `MINI` or `PENNANT`."

    Design: Corner/entities/design_get_round_trips_player_code_and_null_approved_version
    """
    set_clock(api)
    licensor = create_licensor(api, name=f"NBL {sku}")

    created = validate_success(
        api.create_design(
            {
                "licensor_id": licensor["id"],
                "team_code": "ATL",
                "garment_sku": sku,
                "design_name": f"ATL {sku}",
            },
            DESIGN_OPS,
        ),
        expected_status=201,
    )
    assert created["garment_sku"] == sku
    assert created["approval_state"] == "PENDING_LICENSOR_APPROVAL"