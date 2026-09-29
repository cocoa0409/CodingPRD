"""Role permissions: exclusive writes, genuinely shared writes and partitioned reads."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_FORBIDDEN_ROLE
from test_helpers.assertions import assert_instant_equals, assert_load, assert_pagination_meta
from test_helpers.constants import UNKNOWN_UUIDS, UNKNOWN_UUID_C1
from test_helpers.test_users import (
    ADMIN,
    ANALYST,
    BASELINE_VERIFIER,
    PERMITTEE_1,
    PERMIT_WRITER,
    REGISTRY,
    make_permittee_headers,
    make_permit_writer_headers,
    make_producer_headers,
    make_verifier_headers,
)


def test_every_exclusive_operation_refuses_a_plausible_but_unauthorised_role(api):
    """The role gate fires before existence, so unknown ids still yield 403.

    "The acting role is permitted to perform this operation — `ERR_FORBIDDEN_ROLE`,
    403. ... This check runs before any existence check, so an unauthorised role
    receives 403 even when the referenced resource does not exist."

    Design: Corner/rbac/exclusive_operations_are_refused_to_every_other_role
    """
    watershed_id, permit_id, project_id, batch_id = UNKNOWN_UUIDS[:4]

    refusals = (
        api.create_watershed(
            f.watershed_payload(
                name="Scioto Headwaters",
                state_code="OH",
                watershed_code="SCR",
                pollutant="TOTAL_PHOSPHORUS",
                baseline_year=2020,
                baseline_load_lbs_yr=120000.00,
                eligible_zone_codes=["Z1"],
            ),
            ANALYST,
        ),
        api.create_tmdl_assessment(f.tmdl_assessment_payload(watershed_id), ADMIN),
        api.derive_limits(permit_id, ADMIN),
        api.create_verification_event(
            f.verification_event_payload(
                project_id,
                "BASELINE",
                "PASS",
                narrative="Registry staff attempting a field inspection.",
            ),
            REGISTRY,
        ),
        api.list_credit_batch(batch_id, ADMIN),
        api.file_annual_report(
            permit_id, f.annual_report_payload(25000.00, 2026), PERMIT_WRITER
        ),
        api.create_adaptive_review(
            watershed_id,
            f.adaptive_review_payload("AR-1", "2026-01-01", "2026-06-30"),
            ANALYST,
        ),
    )

    for response in refusals:
        validate_error(response, ERR_FORBIDDEN_ROLE, 403)
        assert response.status_code != 404, response.text


def test_shared_writes_accept_each_of_their_authorised_roles(api):
    """Reaches, samples, producers and the clock each accept more than one role.

    "**Reach** rows, which either a `ProgramAdministrator` or a `TmdlAnalyst` may
    create", "**MonitoringSample** rows, which a `TmdlAnalyst` or a
    `ProgramAdministrator` records", "A `ProgramAdministrator` or a
    `RegistryAdministrator` enrols a **Producer**"

    Design: Corner/rbac/shared_operations_succeed_for_each_of_their_authorised_roles
    """
    fx.pin_clock(api)
    watershed = fx.scr_watershed(api)

    r_a = validate_success(
        api.create_reach(
            f.reach_payload(
                watershed["id"],
                "R_A",
                trading_zone_code="Z2",
                reach_class="COMPLIANCE_POINT",
                delivery_factor=1.0000,
            ),
            ADMIN,
        ),
        201,
    )
    validate_success(
        api.create_reach(
            f.reach_payload(
                watershed["id"],
                "R_B",
                trading_zone_code="Z1",
                reach_class="HEADWATER",
                delivery_factor=0.8000,
                downstream_reach_id=r_a["id"],
            ),
            ANALYST,
        ),
        201,
    )
    _, meta = validate_paginated(api.list_reaches(ANALYST, {"watershed_id": watershed["id"]}))
    assert_pagination_meta(meta, 10, 0, 2, False)

    by_admin = validate_success(
        api.create_monitoring_sample(
            f.monitoring_sample_payload(r_a["id"], "2026-04-01T12:00:00Z", 0.0500, 1000.00), ADMIN
        ),
        201,
    )
    by_analyst = validate_success(
        api.create_monitoring_sample(
            f.monitoring_sample_payload(r_a["id"], "2026-04-02T12:00:00Z", 0.0250, 100.00), ANALYST
        ),
        201,
    )
    assert_load(by_admin["computed_load_lbs_yr"], 98422.25, "computed_load_lbs_yr")
    assert_load(by_analyst["computed_load_lbs_yr"], 4921.11, "computed_load_lbs_yr")

    producer_by_admin = validate_success(
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
    producer_by_registry = validate_success(
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
    assert producer_by_admin["id"] != producer_by_registry["id"], (
        producer_by_admin,
        producer_by_registry,
    )

    validate_success(
        api.set_clock("2026-06-16T00:00:00Z", make_producer_headers(producer_by_admin["id"]))
    )
    validate_success(api.set_clock("2026-06-17T00:00:00Z", make_verifier_headers("verifier-1")))
    validate_success(
        api.set_clock("2026-06-18T00:00:00Z", make_permittee_headers("user-permittee-1"))
    )
    validate_success(
        api.set_clock("2026-06-19T00:00:00Z", make_permit_writer_headers("permit-writer-1"))
    )

    after_the_last_clock_write = validate_success(
        api.create_reach(
            f.reach_payload(
                watershed["id"],
                "R_C",
                trading_zone_code="Z2",
                reach_class="MAINSTEM",
                delivery_factor=0.9000,
            ),
            ANALYST,
        ),
        201,
    )
    assert_instant_equals(
        after_the_last_clock_write["created_at"], "2026-06-19T00:00:00Z", "created_at"
    )


def test_read_scopes_are_partitioned_and_an_out_of_scope_read_is_forbidden(api):
    """A denied reader gets 403, never an empty page.

    The registry list endpoints are granted to "`ProgramAdministrator`,
    `RegistryAdministrator`, `PracticeVerifier`, `Producer`, `Permittee`" while the
    permit and project lists are granted to their own disjoint role sets.

    Design: Corner/rbac/read_scopes_are_partitioned_and_out_of_scope_reads_are_forbidden
    """
    producer_headers = make_producer_headers(UNKNOWN_UUID_C1)

    refusals = (
        api.list_credit_batches(ANALYST),
        api.list_credit_transactions(ANALYST),
        api.list_permits(producer_headers),
        api.list_credit_transactions(BASELINE_VERIFIER),
        api.list_practice_projects(PERMIT_WRITER),
        api.list_verification_events(PERMIT_WRITER),
    )

    for response in refusals:
        validate_error(response, ERR_FORBIDDEN_ROLE, 403)
        assert response.status_code != 200, response.text

    permitted = validate_paginated(api.list_credit_batches(REGISTRY))
    assert_pagination_meta(permitted[1], 10, 0, 0, False)
    permittee_view = validate_paginated(api.list_permits(PERMITTEE_1))
    assert_pagination_meta(permittee_view[1], 10, 0, 0, False)
