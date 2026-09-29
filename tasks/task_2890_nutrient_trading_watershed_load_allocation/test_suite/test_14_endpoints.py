"""Endpoint surface claims: the create-then-read-by-id shape of the Producer entity."""

from prd_bench_local_runner.testing import get_success_data, is_valid_uuid, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_common_fields, assert_instant_equals, assert_integer
from test_helpers.constants import CLOCK_BASE
from test_helpers.test_users import ADMIN, REGISTRY


def test_producers_are_written_by_either_authoring_role_and_read_back_unchanged(api):
    """Both authorised writers mint a producer and each row reads back at version 1.

    "A `ProgramAdministrator` or a `RegistryAdministrator` enrols a **Producer** by
    recording its `legal_name`, the `county_code` of its operation, and a
    `contact_email` used for verification scheduling."

    Design: Corner/endpoints/producer_create_and_read_round_trip_across_both_authoring_roles
    """
    fx.pin_clock(api)

    by_admin = validate_success(
        api.create_producer(
            f.producer_payload(
                legal_name="Bluegrass Farms LLC",
                county_code="OH-041",
                contact_email="ops@bluegrass.example",
            ),
            ADMIN,
        ),
        201,
    )
    by_registry = validate_success(
        api.create_producer(
            f.producer_payload(
                legal_name="Riverbend Acres LLC",
                county_code="OH-049",
                contact_email="ops@riverbend.example",
            ),
            REGISTRY,
        ),
        201,
    )

    assert by_admin["legal_name"] == "Bluegrass Farms LLC", by_admin
    assert by_admin["county_code"] == "OH-041", by_admin
    assert_common_fields(by_admin, expected_version=1)
    assert is_valid_uuid(by_registry["id"]), by_registry
    assert by_registry["id"] != by_admin["id"], (by_admin, by_registry)
    assert_integer(by_registry["version"], 1, "version")

    admin_row_read_by_registry = validate_success(api.get_producer(by_admin["id"], REGISTRY))

    assert admin_row_read_by_registry["id"] == by_admin["id"], admin_row_read_by_registry
    assert (
        admin_row_read_by_registry["contact_email"] == "ops@bluegrass.example"
    ), admin_row_read_by_registry
    assert_instant_equals(admin_row_read_by_registry["created_at"], CLOCK_BASE, "created_at")
    assert_integer(admin_row_read_by_registry["version"], 1, "version on re-read")

    registry_row_read_by_admin = get_success_data(api.get_producer(by_registry["id"], ADMIN))

    assert registry_row_read_by_admin["id"] == by_registry["id"], registry_row_read_by_admin
    assert (
        registry_row_read_by_admin["legal_name"] == "Riverbend Acres LLC"
    ), registry_row_read_by_admin
    assert registry_row_read_by_admin["county_code"] == "OH-049", registry_row_read_by_admin
    assert_integer(registry_row_read_by_admin["version"], 1, "version on re-read")
    assert registry_row_read_by_admin == by_registry, (registry_row_read_by_admin, by_registry)
