"""The contracts that every endpoint shares.

Pagination, path-parameter resolution and body-shape validation are declared once
and apply everywhere, so they are pinned down here on the two endpoints where they
are cheapest to observe: the route listing and the segment create.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    fixtures as fx,
    ids_of,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    create_segment_payload,
    drop,
)

_HARBOR_LOOP = {
    "name": "Harbor Loop",
    "topology_objective": "RING_CLOSURE",
    "target_in_service_date": "2027-03-01",
    "budget_authorized_cents": 250000000,
}
_DOCK_STREET = {
    "sequence_index": 1,
    "street_name": "Dock Street",
    "municipality_code": "MUN-014",
    "length_feet": 400,
    "terrain_class": "URBAN_PAVED",
    "planned_work_start_on": "2026-09-15",
    "planned_work_end_on": "2026-09-20",
}


def test_the_route_listing_reports_its_window_and_its_filtered_population(
    api, engineer_headers, admin_headers
):
    """Three stored routes, read two at a time, then narrowed to one objective.

    PRD: "Pagination is reported back to the caller through four fields inside the
    `meta` object: `limit` and `offset` echo the effective values actually applied,
    `total_count` reports how many records matched the filters before the page window
    was applied, and `has_more` is true exactly when records remain beyond the
    current window."

    Design: Corner/entities/route_listing_paginates_with_total_count_and_has_more
    """
    fx.set_clock("2026-08-10T00:00:00Z")
    alpha = fx.create_route(headers=engineer_headers, **dict(_HARBOR_LOOP, name="Alpha Ring"))
    bravo = fx.create_route(
        headers=engineer_headers,
        **dict(_HARBOR_LOOP, name="Bravo Spur", topology_objective="SPUR"),
    )
    charlie = fx.create_route(headers=engineer_headers, **dict(_HARBOR_LOOP, name="Charlie Ring"))

    first_page, first_meta = validate_paginated(
        api.list_routes(headers=admin_headers, params={"limit": 2, "offset": 0})
    )
    assert ids_of(first_page) == [alpha["id"], bravo["id"]]
    assert first_meta["total_count"] == 3
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["has_more"] is True

    last_page, last_meta = validate_paginated(
        api.list_routes(headers=admin_headers, params={"limit": 2, "offset": 2})
    )
    assert ids_of(last_page) == [charlie["id"]]
    assert last_meta["total_count"] == 3
    assert last_meta["offset"] == 2
    assert last_meta["has_more"] is False

    spurs, spur_meta = validate_paginated(
        api.list_routes(headers=admin_headers, params={"topology_objective": "SPUR"})
    )
    assert ids_of(spurs) == [bravo["id"]]
    assert spur_meta["total_count"] == 1
    assert spur_meta["has_more"] is False

    everything, all_meta = validate_paginated(api.list_routes(headers=admin_headers))
    assert len(everything) == 3
    assert all_meta["limit"] == 10
    assert all_meta["offset"] == 0
    assert all_meta["total_count"] == 3
    assert all_meta["has_more"] is False


def test_a_well_formed_id_that_names_no_route_is_a_not_found_and_not_an_empty_page(
    api, engineer_headers
):
    """The collection is non-empty, so a 404 here is about the addressed row alone.

    PRD: "**Path-parameter existence**, resolved left to right. Applies to every
    operation carrying a path parameter. → the matching not-found identifier (404)"

    Design: Corner/entities/route_get_with_unknown_id_returns_route_not_found
    """
    fx.set_clock("2026-08-10T00:00:00Z")
    stored = fx.create_route(headers=engineer_headers, **_HARBOR_LOOP)

    missing = api.get_route(NON_EXISTENT_UUID, headers=engineer_headers)
    validate_error(missing, "ERR_ROUTE_NOT_FOUND", 404)
    body = missing.json()["data"]
    assert body["error_id"] == "ERR_ROUTE_NOT_FOUND"
    assert isinstance(body["message"], str) and body["message"] != ""

    rows, meta = validate_paginated(api.list_routes(headers=engineer_headers))
    assert ids_of(rows) == [stored["id"]]
    assert meta["total_count"] == 1


def test_every_required_segment_input_is_required_one_at_a_time(api, engineer_headers):
    """Eight omissions, eight identical shape faults, and no segment ever appears.

    PRD: "Each `RouteSegment` is created with a `route_id` naming its route, a
    `sequence_index` of at least 1 giving its position along the route, a
    `street_name` and a `municipality_code` identifying the right-of-way, a
    `length_feet` of at least 1, a `terrain_class`, and the pair of planned
    construction dates `planned_work_start_on` and `planned_work_end_on`, the latter
    falling on or after the former."

    Design: Corner/entities/segment_create_missing_terrain_class_returns_invalid_request
    """
    fx.set_clock("2026-08-10T00:00:00Z")
    route = fx.create_route(headers=engineer_headers, **_HARBOR_LOOP)

    required = (
        "route_id",
        "sequence_index",
        "street_name",
        "municipality_code",
        "length_feet",
        "terrain_class",
        "planned_work_start_on",
        "planned_work_end_on",
    )
    for field_name in required:
        incomplete = drop(create_segment_payload(route["id"], **_DOCK_STREET), field_name)
        refused = api.create_segment(incomplete, headers=engineer_headers)
        validate_error(refused, "ERR_INVALID_REQUEST", 400)

    rows, meta = validate_paginated(
        api.list_route_segments(route["id"], headers=engineer_headers)
    )
    assert rows == []
    assert meta["total_count"] == 0

    unchanged = fx.read_route(route["id"])
    assert unchanged["segment_count"] == 0
    assert unchanged["design_total_length_feet"] == 0
    assert unchanged["version"] == route["version"]


def test_a_foreign_enum_reversed_dates_and_a_zero_page_are_all_shape_faults(
    api, engineer_headers
):
    """Three unrelated malformations on two endpoints answer with the same identifier.

    PRD: "**Body shape** — every required field present; no unknown field; every
    enum value inside its declared set; every integer inside its declared
    constraint; dates parseable as `YYYY-MM-DD`; instants parseable as ISO 8601 UTC;
    and every ordering constraint between a pair of body fields satisfied, namely
    `planned_work_end_on` on or after `planned_work_start_on`, `work_window_end_on`
    on or after `work_window_start_on`, `ends_on` on or after `starts_on`,
    `express_fiber_count` strictly less than `fiber_count_allocated`, and
    `station_feet` no greater than the addressed segment's `length_feet`."

    Design: Corner/entities/segment_create_with_out_of_set_enum_or_reversed_dates_returns_invalid_request
    """
    fx.set_clock("2026-08-10T00:00:00Z")
    route = fx.create_route(headers=engineer_headers, **_HARBOR_LOOP)

    foreign_enum = api.create_segment(
        create_segment_payload(route["id"], **dict(_DOCK_STREET, terrain_class="SWAMP_CROSSING")),
        headers=engineer_headers,
    )
    validate_error(foreign_enum, "ERR_INVALID_REQUEST", 400)

    reversed_dates = api.create_segment(
        create_segment_payload(
            route["id"],
            **dict(
                _DOCK_STREET,
                planned_work_start_on="2026-09-20",
                planned_work_end_on="2026-09-15",
            ),
        ),
        headers=engineer_headers,
    )
    validate_error(reversed_dates, "ERR_INVALID_REQUEST", 400)

    empty_page = api.list_routes(headers=engineer_headers, params={"limit": 0})
    validate_error(empty_page, "ERR_INVALID_REQUEST", 400)

    rows, meta = validate_paginated(
        api.list_route_segments(route["id"], headers=engineer_headers)
    )
    assert rows == []
    assert meta["total_count"] == 0

    accepted = validate_success(
        api.create_segment(
            create_segment_payload(route["id"], **_DOCK_STREET), headers=engineer_headers
        ),
        201,
    )
    assert accepted["terrain_class"] == "URBAN_PAVED"
    assert accepted["planned_work_end_on"] == "2026-09-20"


def test_each_resource_family_answers_a_missing_id_with_its_own_not_found(
    api, engineer_headers
):
    """One absent identifier aimed at six families yields six distinct error ids.

    PRD: "The 404-bearing identifiers are `ERR_ROUTE_NOT_FOUND`,
    `ERR_SEGMENT_NOT_FOUND`, `ERR_WALKOUT_NOT_FOUND`,
    `ERR_POLE_APPLICATION_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`,
    `ERR_DESIGN_NOT_FOUND`, `ERR_SPLICE_POINT_NOT_FOUND` and
    `ERR_AS_BUILT_NOT_FOUND`."

    Design: Corner/errors/every_remaining_not_found_error_id_is_triggerable
    """
    fx.set_clock("2026-08-10T00:00:00Z")

    probes = (
        (api.get_walkout(NON_EXISTENT_UUID, headers=engineer_headers), "ERR_WALKOUT_NOT_FOUND"),
        (
            api.get_pole_attachment_application(NON_EXISTENT_UUID, headers=engineer_headers),
            "ERR_POLE_APPLICATION_NOT_FOUND",
        ),
        (
            api.get_permit_application(NON_EXISTENT_UUID, headers=engineer_headers),
            "ERR_PERMIT_NOT_FOUND",
        ),
        (
            api.get_design_package(NON_EXISTENT_UUID, headers=engineer_headers),
            "ERR_DESIGN_NOT_FOUND",
        ),
        (
            api.void_splice_point(NON_EXISTENT_UUID, headers=engineer_headers),
            "ERR_SPLICE_POINT_NOT_FOUND",
        ),
        (
            api.get_as_built_record(NON_EXISTENT_UUID, headers=engineer_headers),
            "ERR_AS_BUILT_NOT_FOUND",
        ),
    )
    for response, expected_error_id in probes:
        validate_error(response, expected_error_id, 404)
        envelope = response.json()
        assert isinstance(envelope["data"]["message"], str)
        assert envelope["data"]["message"] != ""
        assert "api_request_id" in envelope["meta"]
        assert "api_request_timestamp" in envelope["meta"]

    unknown_segment = api.get_segment(NON_EXISTENT_UUID, headers=engineer_headers)
    validate_error(unknown_segment, "ERR_SEGMENT_NOT_FOUND", 404)

    unknown_route = api.get_route(NON_EXISTENT_UUID, headers=engineer_headers)
    validate_error(unknown_route, "ERR_ROUTE_NOT_FOUND", 404)
