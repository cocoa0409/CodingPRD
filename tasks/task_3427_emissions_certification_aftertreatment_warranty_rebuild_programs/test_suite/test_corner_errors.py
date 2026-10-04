"""Corner coverage — errors (PRD §3.4 unit registration family-state gate).

The runner restarts the server before every test, so each test builds its own
environment from an empty database through PRD-declared endpoints only.
"""
from test_helpers import (
    ApiErrorId,
    create_engine_unit_payload,
    setup_family_certified,
    setup_fleet,
    validate_error,
)


def test_unit_create_requires_family_in_production(api, admin_headers):
    """PRD §3.4: "Two gates guard registration: the family must be in `IN_PRODUCTION` (`ERR_FAMILY_NOT_IN_PRODUCTION`, HTTP 409), and the `in_service_date` must not lie in the future — a date strictly after the logical clock is rejected with `ERR_IN_SERVICE_DATE_IN_FUTURE` (HTTP 422), while a date exactly equal to the clock is accepted."

    Registering a unit against a family that is merely CERTIFIED (never
    entered production) fails 409 ERR_FAMILY_NOT_IN_PRODUCTION.

    Design: Corner/errors/unit_create_requires_family_in_production
    """
    env = setup_family_certified()
    assert env["family"]["certification_status"] == "CERTIFIED"
    fleet = setup_fleet()

    refused = api.create_engine_unit(
        create_engine_unit_payload(
            engine_family_id=env["family"]["id"],
            fleet_id=fleet["id"],
            serial_number="UN-E1",
        ),
        admin_headers,
    )
    validate_error(refused, ApiErrorId.ERR_FAMILY_NOT_IN_PRODUCTION)
