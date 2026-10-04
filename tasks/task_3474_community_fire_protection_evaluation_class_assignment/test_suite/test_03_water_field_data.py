"""Water-domain field data: hydrant registration, list filters, input rules."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_hydrant,
    advance_cycle_to,
    create_community_bundle,
    create_cycle,
    get_success_data,
    make_water_utility_manager_headers,
    set_hydrant_status,
    submit_flow_test,
    validate_error,
    validate_success,
)

ANALYST = TEST_USERS["field_analyst_headers"]


def _system_in_data_collection(api, name):
    bundle = create_community_bundle(api, name=name)
    cycle = create_cycle(api, bundle["community"]["id"])
    advance_cycle_to(api, cycle["id"], "DATA_COLLECTION")
    return bundle


def test_hydrant_create_computed_field_input_ignored(api):
    """PRD §3.4: "a new hydrant is `ACTIVE` with `max_flow_gpm` and
    `last_certified_test_date` both null until a certified flow test fills
    them." A client-supplied max_flow_gpm is not part of the registered
    input and leaves the computed field null.

    Design: Corner/entities/hydrant_create_computed_field_input_ignored
    """
    bundle = _system_in_data_collection(api, "Hydra")
    system = bundle["system"]
    resp = api.create_hydrant(
        {"system_id": system["id"], "location_descriptor": "5th & Main", "max_flow_gpm": 999},
        make_water_utility_manager_headers(system["id"]),
    )
    hydrant = validate_success(resp, 201)
    assert hydrant["max_flow_gpm"] is None, "client-supplied computed field must be ignored"
    assert hydrant["status"] == "ACTIVE"


def test_hydrants_list_filter_by_status(api):
    """PRD §4: "List endpoints accept optional filters drawn from the
    resource's own fields — … hydrants by `system_id` and `status`; flow
    tests by `system_id`, `hydrant_id`, `status`, and `supersedes_test_id`".

    Design: Corner/entities/hydrants_list_filter_by_status
    """
    bundle = _system_in_data_collection(api, "Filterton")
    system = bundle["system"]
    h1 = add_hydrant(api, system["id"], "H1")
    h2 = add_hydrant(api, system["id"], "H2")
    set_hydrant_status(api, system["id"], h2["id"], "OUT_OF_SERVICE")
    rows = get_success_data(
        api.list_hydrants(
            make_water_utility_manager_headers(system["id"]),
            params={"system_id": system["id"], "status": "OUT_OF_SERVICE"},
        )
    )
    assert len(rows) == 1
    assert rows[0]["id"] == h2["id"]
    assert rows[0]["id"] != h1["id"]


def test_flow_tests_list_filter_by_hydrant(api):
    """PRD §4: "List endpoints accept optional filters drawn from the
    resource's own fields — … flow tests by `system_id`, `hydrant_id`,
    `status`, and `supersedes_test_id`".

    Design: Corner/entities/flow_tests_list_filter_by_hydrant
    """
    bundle = _system_in_data_collection(api, "Filter Falls")
    system = bundle["system"]
    h1 = add_hydrant(api, system["id"], "H1")
    h2 = add_hydrant(api, system["id"], "H2")
    t1 = submit_flow_test(api, system["id"], h1["id"], measured_flow_gpm=1000)
    submit_flow_test(api, system["id"], h2["id"], measured_flow_gpm=900)
    rows = get_success_data(api.list_flow_tests(ANALYST, params={"hydrant_id": h1["id"]}))
    assert len(rows) == 1
    assert rows[0]["id"] == t1["id"]


def test_flow_test_psi_ordering_returns_invalid_request(api):
    """PRD §3.4: "the `residual_psi` (at least 10 and strictly below the
    static reading), and the `measured_flow_gpm` (positive); pressure
    readings that violate these bounds are rejected with
    `ERR_INVALID_REQUEST`."

    Design: Corner/validations/flow_test_psi_ordering_returns_invalid_request
    """
    bundle = _system_in_data_collection(api, "Psi City")
    system = bundle["system"]
    hydrant = add_hydrant(api, system["id"], "H1")
    resp = api.create_flow_test(
        {
            "system_id": system["id"], "hydrant_id": hydrant["id"],
            "test_date": "2026-08-15", "static_psi": 70, "residual_psi": 80,
            "measured_flow_gpm": 1000,
        },
        make_water_utility_manager_headers(system["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_test_date_in_future_returns_error(api):
    """PRD §3.4: "the `test_date` (which must not fall after the logical
    clock date, else `ERR_TEST_DATE_IN_FUTURE` with HTTP 422)" — the default
    clock reads 2026-09-01, so 2027-01-15 is in the future.

    Design: Corner/validations/test_date_in_future_returns_error
    """
    bundle = _system_in_data_collection(api, "Future Test")
    system = bundle["system"]
    hydrant = add_hydrant(api, system["id"], "H1")
    resp = api.create_flow_test(
        {
            "system_id": system["id"], "hydrant_id": hydrant["id"],
            "test_date": "2027-01-15", "static_psi": 80, "residual_psi": 60,
            "measured_flow_gpm": 1000,
        },
        make_water_utility_manager_headers(system["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_TEST_DATE_IN_FUTURE)
