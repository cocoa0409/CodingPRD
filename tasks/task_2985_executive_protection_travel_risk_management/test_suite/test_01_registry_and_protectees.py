"""Registration defaults, stored-row reads, list envelopes and derived visibility."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx


def test_create_executive_returns_the_declared_defaults(api, dep):
    """Registering a protectee returns 201 with every derived field at its default.

    PRD §3.1: "Their `residential_survey_status` is `PENDING`, their `residential_component` is 0, their `public_exposure_score` is 0.00, and their `threat_level` is `LOW`."

    Design: Corner/entities/create_executive_returns_201_with_declared_defaults
    """
    response = api.create_executive(
        f.executive_payload(
            full_name="Eve Exec",
            tier=c.TIER_2,
            role_title="CFO",
            base_country_code=c.COUNTRY_US,
            annual_security_budget_cents=40_000_000,
        ),
        dep.mgr,
    )
    row = validate_success(response, 201)

    assert row["full_name"] == "Eve Exec"
    assert row["tier"] == c.TIER_2
    assert row["role_title"] == "CFO"
    assert row["base_country_code"] == c.COUNTRY_US
    assert row["consent_scope"] == c.CONSENT_NONE
    assert row["consent_expires_at"] is None
    assert row["residential_survey_status"] == c.SURVEY_PENDING
    a.assert_decimal_value(row["residential_component"], 0, "residential_component")
    a.assert_decimal_value(row["public_exposure_score"], 0.00, "public_exposure_score")
    assert row["threat_level"] == c.THREAT_LOW
    a.assert_cents(
        row["annual_security_budget_cents"], 40_000_000, "annual_security_budget_cents"
    )
    a.assert_budget_ledger(row, committed=0, spent=0, remaining=40_000_000)
    a.assert_cents(
        row["annual_disclosed_perquisite_cents"], 0, "annual_disclosed_perquisite_cents"
    )
    a.assert_cents(
        row["business_borne_security_cents"], 0, "business_borne_security_cents"
    )
    assert row["open_degraded_trip_count"] == 0
    a.assert_common_fields(row, expected_version=1)
    a.assert_single_resource_meta(response)


def test_get_vendor_returns_the_stored_row_unchanged(api, dep):
    """Reading a vendor echoes the registered figures and does not mutate the row.

    PRD §3.5: "A new vendor's `activation_status` is `AVAILABLE`, its `committed_engagement_hours` is 0 and its `suspension_reason` is null."

    Design: Corner/entities/get_vendor_returns_the_stored_row_unchanged
    """
    created = validate_success(
        api.create_vendor(
            f.vendor_payload(
                vendor_name="Guarda Atlantica",
                vendor_type=c.VENDOR_GROUND_SECURITY,
                country_code=c.COUNTRY_PT,
                max_concurrent_engagements=2,
                sla_response_minutes=45,
                hourly_rate_cents=10_000,
                retainer_cents=50_000,
            ),
            dep.dir,
        ),
        201,
    )
    assert created["activation_status"] == c.VENDOR_AVAILABLE
    a.assert_vendor_hours(created, 0)
    assert created["suspension_reason"] is None
    a.assert_common_fields(created, expected_version=1)

    read_response = api.get_vendor(created["id"], dep.analyst)
    row = validate_success(read_response)
    assert row["vendor_name"] == "Guarda Atlantica"
    assert row["vendor_type"] == c.VENDOR_GROUND_SECURITY
    assert row["country_code"] == c.COUNTRY_PT
    assert row["max_concurrent_engagements"] == 2
    assert row["sla_response_minutes"] == 45
    a.assert_cents(row["hourly_rate_cents"], 10_000, "hourly_rate_cents")
    a.assert_cents(row["retainer_cents"], 50_000, "retainer_cents")
    assert row["activation_status"] == c.VENDOR_AVAILABLE
    a.assert_vendor_hours(row, 0)
    assert row["version"] == 1, "a read is not a mutation, so version stays at 1"
    a.assert_single_resource_meta(read_response)


def test_list_trips_pages_with_total_count_and_has_more(api, dep):
    """A filtered trip list reports the pre-pagination total and whether more remain.

    PRD §2.3: "The `meta` object of a list response carries `limit` (the effective page size), `offset` (the effective skip count), `total_count` (the number of rows matching the filters before pagination) and `has_more` (true when rows remain beyond this page)."

    Design: Corner/entities/list_trips_returns_a_paginated_envelope_with_total_count_and_has_more
    """
    fx.publish_rating(api, dep)
    exec_a = fx.register_executive(api, dep, full_name="Eve Exec")
    exec_b = fx.register_executive(api, dep, full_name="Bob Board")
    ra_a = fx.draft_assessment(api, dep, exec_a["id"])
    ra_b = fx.draft_assessment(api, dep, exec_b["id"])
    for _ in range(3):
        fx.create_trip(api, dep, exec_a["id"], ra_a["id"])
    fx.create_trip(api, dep, exec_b["id"], ra_b["id"])

    first_page, meta = validate_paginated(
        api.list_trips(dep.mgr, executive_id=exec_a["id"], limit=2, offset=0)
    )
    assert len(first_page) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0

    second_page, second_meta = validate_paginated(
        api.list_trips(dep.mgr, executive_id=exec_a["id"], limit=2, offset=2)
    )
    assert len(second_page) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert all(row["executive_id"] == exec_a["id"] for row in first_page + second_page)


def test_create_trip_defaults_to_prorata_allocation(api, world):
    """A trip created without an allocation method carries PRORATA and empty derivations.

    PRD §3.4: "Two fields are optional: `insurance_policy_id`, which may be attached at creation or left null and attached later, and `cost_allocation_method`, which defaults to `PRORATA` and is otherwise `BUSINESS_ONLY` or `EXEC_PERQUISITE`."

    Design: Corner/entities/create_trip_without_cost_allocation_method_defaults_to_prorata
    """
    response = api.create_trip(
        f.trip_payload(world.exec_id, world.dep.mgr_id, world.ra_id),
        world.dep.mgr,
    )
    trip = validate_success(response, 201)

    assert trip["cost_allocation_method"] == c.ALLOCATION_PRORATA
    assert trip["insurance_policy_id"] is None
    a.assert_trip_states(trip, c.APPROVAL_DRAFT, c.READINESS_NOT_READY)
    assert trip["required_approval_level"] == c.LEVEL_MANAGER
    assert trip["max_leg_risk_band"] is None
    a.assert_cents(
        trip["provisional_security_cost_cents"], 0, "provisional_security_cost_cents"
    )
    a.assert_cents(
        trip["total_security_cost_cents"], 0, "total_security_cost_cents"
    )
    a.assert_cents(trip["perquisite_taxable_cents"], 0, "perquisite_taxable_cents")
    a.assert_cents(trip["business_borne_cents"], 0, "business_borne_cents")
    a.assert_decimal_value(
        trip["perquisite_rate_applied"], 0, "perquisite_rate_applied"
    )
    assert trip["check_in_interval_hours"] == 24
    assert trip["next_check_in_due_at"] is None
    assert trip["briefing_ack_at"] is None
    assert trip["denied_reason"] is None
    assert trip["closed_at"] is None
    assert trip["duress_active"] is False
    assert trip["missed_check_in_count"] == 0
    a.assert_common_fields(trip, expected_version=1)


def test_assignment_ignores_client_supplied_cost_and_hours(api):
    """The assignment's hours and cost are derived; payload figures are extra fields.

    PRD §3.5: "At creation, `planned_billable_hours` is frozen as the elapsed time from `starts_at` to `ends_at` measured in whole minutes, divided by 60 and rounded up to the next whole hour."

    Design: Corner/entities/assignment_computes_cost_and_hours_and_treats_client_supplied_values_as_extra_field
    """
    w = fx.trip_world(api, with_lead_agent=False, with_route_survey=False)
    dep = w.dep
    version = fx.leg_version(api, dep, w.leg_id)

    payload = f.detail_assignment_payload(
        w.leg_id,
        dep.lead_id,
        version,
        role_on_detail=c.DETAIL_DRIVER,
        starts_at="2026-09-10T08:00:00Z",
        ends_at="2026-09-10T14:00:00Z",
    )
    payload["cost_cents"] = 1
    payload["planned_billable_hours"] = 1
    assignment = validate_success(api.create_detail_assignment(payload, dep.mgr), 201)

    assert assignment["planned_billable_hours"] == 6
    a.assert_cents(assignment["cost_cents"], 45_900, "cost_cents")
    assert assignment["cost_basis"] == c.COST_BASIS_PROVISIONAL
    assert assignment["status"] == c.ASSIGNMENT_CONFIRMED
    assert assignment["role_on_detail"] == c.DETAIL_DRIVER

    staff = fx.read_staff(api, dep, dep.lead_id)
    a.assert_staff_hours(staff, committed=6, released=0)


def test_exposure_signal_and_check_in_carry_no_version(api):
    """Both append-only row types omit updated_at and version entirely.

    PRD §2.4: "A public-exposure signal — the `PublicExposureSignal` type — has no `updated_at` and no `version` field at all; the field is absent from its representation, not present-and-null, because a signal is observed once and never revised."

    Design: Corner/entities/exposure_signal_and_check_in_are_immutable_rows_without_a_version
    """
    w = fx.approved_trip_world(api)
    dep = w.dep

    first = validate_success(
        api.create_exposure_signal(
            w.exec_id,
            f.exposure_signal_payload(c.SIGNAL_MEDIA_MENTION, 3, "2026-07-15T00:00:00Z"),
            dep.analyst,
        ),
        201,
    )
    second = validate_success(
        api.create_exposure_signal(
            w.exec_id,
            f.exposure_signal_payload(c.SIGNAL_MEDIA_MENTION, 3, "2026-07-15T00:00:00Z"),
            dep.analyst,
        ),
        201,
    )
    assert first["id"] != second["id"], "two identical observations are two rows"
    for row in (first, second):
        a.assert_append_only_fields(row)

    signals, meta = validate_paginated(api.list_exposure_signals(w.exec_id, dep.analyst))
    assert meta["total_count"] == 2

    check_in = validate_success(
        api.create_check_in(
            w.trip_id, f.check_in_payload(kind=c.CHECK_IN_AD_HOC), w.exec_headers
        ),
        201,
    )
    a.assert_append_only_fields(check_in)


def test_leg_under_an_unknown_trip_is_a_trip_not_found(api, dep):
    """The trip path segment resolves before the leg payload is examined at all.

    PRD §2.6: "A request against any trip sub-resource whose trip does not exist yields `ERR_TRIP_NOT_FOUND` (HTTP 404), as does a body-level `trip_id` that resolves to nothing."

    Design: Corner/entities/create_leg_under_an_unknown_trip_returns_trip_not_found
    """
    fx.publish_rating(api, dep)
    response = api.create_trip_leg(
        c.MISSING_TRIP_ID, f.trip_leg_payload(), dep.mgr
    )
    validate_error(response, e.ERR_TRIP_NOT_FOUND, 404)
    a.assert_error_meta_shape(response)


def test_every_derived_field_is_visible_in_the_response_that_caused_it(api):
    """The write that derives a figure returns it; the next read agrees with it.

    PRD §2.10: "Submitting a trip for approval adds its provisional cost to the committed figure, and denying that trip subtracts exactly the same amount, restoring the ledger to its pre-submission value."

    Design: Corner/consistency_model/every_derived_field_is_visible_in_the_response_that_caused_it
    """
    w = fx.trip_world(api, with_lead_agent=False, with_route_survey=False)
    dep = w.dep
    version = fx.leg_version(api, dep, w.leg_id)

    assignment = validate_success(
        api.create_detail_assignment(
            f.detail_assignment_payload(
                w.leg_id,
                dep.lead_id,
                version,
                role_on_detail=c.DETAIL_LEAD_AGENT,
                starts_at=c.LEG_ARRIVE_AT,
                ends_at=c.LEG_DEPART_AT,
            ),
            dep.mgr,
        ),
        201,
    )
    assert assignment["planned_billable_hours"] == 10
    a.assert_cents(assignment["cost_cents"], 112_500, "cost_cents")
    assert assignment["cost_basis"] == c.COST_BASIS_PROVISIONAL

    fx.record_advance(api, dep, w.leg_id, c.ITEM_ROUTE_SURVEY)
    submitted = validate_success(api.submit_trip_for_approval(w.trip_id, dep.mgr))
    a.assert_cents(
        submitted["provisional_security_cost_cents"],
        112_500,
        "provisional_security_cost_cents",
    )
    a.assert_trip_states(submitted, c.APPROVAL_PENDING_REVIEW)

    executive = fx.read_executive(api, dep, w.exec_id)
    a.assert_budget_ledger(
        executive, committed=112_500, spent=0, remaining=99_887_500
    )

    leg = fx.read_leg(api, dep, w.leg_id)
    assert leg["leg_risk_band"] == c.BAND_LOW
    assert leg["required_advance_items"] == [c.ITEM_ROUTE_SURVEY]
