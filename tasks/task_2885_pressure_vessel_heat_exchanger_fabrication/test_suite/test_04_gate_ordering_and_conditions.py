"""Boundary satisfaction, boundary violation, gate ordering, conditional derivation, cross-entity posture."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import api_errors, factories
from test_helpers.assertions import assert_number_equals
from test_helpers.constants import (
    CERT_STATUS_EXPIRED,
    COMPONENT_SHELL,
    FAB_STATUS_PLANNED,
    HEAT_STATUS_ACCEPTED,
    HEAT_STATUS_QUARANTINE,
    JOB_STATUS_DRAFT,
    JOINT_CATEGORY_C,
    JOINT_TYPE_FILLET,
    METHOD_MT,
    NDE_STATUS_NOT_PLANNED,
    PWHT_STATUS_NOT_REQUIRED,
    PWHT_STATUS_PENDING,
    REQUIRED_TEST_SIDES_HEAT_EXCHANGER,
    RT_EXTENT_FULL,
    SPEC_SA_516_70,
    VESSEL_TYPE_HEAT_EXCHANGER,
)


def test_a_heat_certified_at_exactly_the_published_minima_is_accepted(client, shop, admin_headers):
    """The spec-minimum comparison admits the boundary value itself.

    PRD §3.4: "An `ACCEPT` decision requires `mtr_received` to be true — accepting material whose mill test report has not arrived is refused with `ERR_TRACEABILITY_INCOMPLETE` — and requires both certified strengths to reach the minima for the heat's specification: at least 38 ksi yield and 70 ksi tensile for `SA-516-70`, at least 25 ksi yield and 70 ksi tensile for `SA-240-304L`, at least 36 ksi yield and 70 ksi tensile for `SA-105`, and at least 26 ksi yield and 47 ksi tensile for `SA-179`."

    Design: Corner/validations/validation_mtr_acceptance_at_exact_spec_minimum_is_admitted
    """
    inspector = shop.qc_inspector()
    heat = shop.heat(
        heat_number="H-5900",
        spec=SPEC_SA_516_70,
        yield_ksi=38.0,
        tensile_ksi=70.0,
        quantity_received_lb=2000.00,
    )

    response = client.review_heat(
        heat["id"], factories.mtr_review_payload("ACCEPT"), shop.acting_as(inspector)
    )

    accepted = validate_success(response, 200)
    assert accepted["status"] == HEAT_STATUS_ACCEPTED
    assert accepted["version"] == 2
    assert accepted["material_class"] == "FERRITIC"
    assert accepted["p_number"] == 1
    assert_number_equals(accepted["quantity_remaining_lb"], 2000.00, 2, "quantity_remaining_lb")

    listed, meta = validate_paginated(
        client.list_heats(
            admin_headers, params={"status": HEAT_STATUS_ACCEPTED, "limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in listed] == [heat["id"]]


def test_either_certified_strength_falling_short_refuses_the_acceptance(client, shop, admin_headers):
    """A shortfall in yield or in tensile is equally disqualifying and leaves quarantine intact.

    PRD §3.4: "Either strength falling short is refused with `ERR_MTR_BELOW_SPEC_MINIMUM`."

    Design: Corner/validations/validation_mtr_one_notch_below_spec_minimum_is_refused
    """
    inspector = shop.qc_inspector()
    low_yield = shop.heat(
        heat_number="H-5901", spec=SPEC_SA_516_70, yield_ksi=37.9, tensile_ksi=75.0
    )
    low_tensile = shop.heat(
        heat_number="H-5902", spec=SPEC_SA_516_70, yield_ksi=41.0, tensile_ksi=69.9
    )

    yield_response = client.review_heat(
        low_yield["id"], factories.mtr_review_payload("ACCEPT"), shop.acting_as(inspector)
    )
    tensile_response = client.review_heat(
        low_tensile["id"], factories.mtr_review_payload("ACCEPT"), shop.acting_as(inspector)
    )

    validate_error(yield_response, api_errors.ERR_MTR_BELOW_SPEC_MINIMUM, 409)
    validate_error(tensile_response, api_errors.ERR_MTR_BELOW_SPEC_MINIMUM, 409)
    for heat_id in (low_yield["id"], low_tensile["id"]):
        untouched = shop.read_heat(heat_id)
        assert untouched["status"] == HEAT_STATUS_QUARANTINE
        assert untouched["version"] == 1

    _, meta = validate_paginated(
        client.list_heats(
            admin_headers, params={"status": HEAT_STATUS_ACCEPTED, "limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 0


def test_an_unpermitted_caller_is_turned_away_before_the_body_is_judged(client, shop, admin_headers):
    """The role gate answers first, and the shape gate is still live for a permitted caller.

    PRD §2.8: "Checks run strictly in the ascending order below; the **first** violated check produces the response and no later check runs."

    PRD §2.8: "**Role permission.** The declared role appears in the endpoint's permitted-role list — otherwise `ERR_ROLE_NOT_PERMITTED` (403)."

    Design: Corner/validations/validation_priority_ordering_role_gate_outranks_shape_gate
    """
    inspector = shop.qc_inspector()
    engineer = shop.welding_engineer()
    invalid_body = factories.wps_payload(wps_number="WPS-102", process="TIG")

    unpermitted = client.create_wps(invalid_body, shop.acting_as(inspector))
    permitted = client.create_wps(invalid_body, shop.acting_as(engineer))

    validate_error(unpermitted, api_errors.ERR_ROLE_NOT_PERMITTED, 403)
    validate_error(permitted, api_errors.ERR_INVALID_REQUEST, 400)
    _, meta = validate_paginated(client.list_wps(admin_headers, params={"limit": 10, "offset": 0}))
    assert meta["total_count"] == 0


def test_the_heat_treatment_dimension_opens_only_when_the_procedure_demands_it(client, shop, admin_headers):
    """Two otherwise identical joints diverge on the flag carried by their procedures.

    PRD §3.6: "Its `pwht_status` opens at `PENDING` when the cited procedure has `pwht_required` true and at `NOT_REQUIRED` when it does not — the flag on the procedure, resolved once at planning time, is what decides whether the joint will ever need a furnace charge."

    Design: Corner/validations/validation_conditional_pwht_dimension_follows_the_wps_flag
    """
    job = shop.job(job_number="J-2885-C36", mawp_psi=350, inside_radius_in=30)
    shop.release_design(
        job,
        rt_extent_declared=RT_EXTENT_FULL,
        allowable_stress_psi=20000,
        corrosion_allowance_in=0.0625,
        thickness_nominal_in=0.7500,
    )
    heat = shop.accepted_heat(heat_number="H-6000", quantity_received_lb=2000.00)
    part = shop.issue_part(
        job["id"], heat["id"], part_mark="SH-01", component_type=COMPONENT_SHELL, issued_quantity_lb=1200.00
    )
    without_treatment = shop.qualified_wps(wps_number="WPS-100", pwht_required=False)
    with_treatment = shop.qualified_wps(wps_number="WPS-101", pwht_required=True)
    joint_shape = {
        "joint_category": JOINT_CATEGORY_C,
        "joint_type": JOINT_TYPE_FILLET,
        "thickness_in": 0.7500,
    }

    flag_off = shop.plan_joint(
        job["id"], without_treatment["id"], part["id"], weld_number="W-001", **joint_shape
    )
    flag_on = shop.plan_joint(
        job["id"], with_treatment["id"], part["id"], weld_number="W-002", **joint_shape
    )

    assert flag_off["pwht_status"] == PWHT_STATUS_NOT_REQUIRED
    assert flag_on["pwht_status"] == PWHT_STATUS_PENDING
    for joint in (flag_off, flag_on):
        assert joint["fab_status"] == FAB_STATUS_PLANNED
        assert joint["nde_status"] == NDE_STATUS_NOT_PLANNED
        assert joint["repair_generation"] == 0
        assert joint["required_volumetric_pct"] == 0
        assert joint["required_surface_method"] == METHOD_MT

    pending, meta = validate_paginated(
        client.list_welds(
            admin_headers,
            params={
                "job_id": job["id"],
                "pwht_status": PWHT_STATUS_PENDING,
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in pending] == [flag_on["id"]]
    assert_number_equals(
        shop.read_job(job["id"])["weld_completion_pct"], 0.00, 2, "weld_completion_pct"
    )


def test_the_expiry_gate_reads_the_certificate_named_by_the_request(client, shop, admin_headers):
    """The same body dies on a lapsed licence while a current licence keeps working.

    PRD §2.8: "**Certificate expiry.** The governing certificate has not passed `expires_on` relative to the logical clock — otherwise `ERR_CERTIFICATE_EXPIRED` (409)."

    Design: Corner/validations/validation_cross_entity_expired_certificate_blocks_new_job
    """
    short_dated = shop.certificate(
        cert_number="CA-U-8922", issued_on="2026-01-01", expires_on="2026-09-01"
    )
    long_dated = shop.certificate(
        cert_number="CA-U-8923", issued_on="2026-01-01", expires_on="2029-01-01"
    )
    before = shop.job(short_dated, job_number="J-2885-C37", mawp_psi=350, inside_radius_in=30)
    assert before["status"] == JOB_STATUS_DRAFT

    shop.set_clock("2026-09-02T00:00:00.000Z")
    refused = client.create_job(
        factories.vessel_job_payload(
            short_dated["id"], job_number="J-2885-C38", mawp_psi=350, inside_radius_in=30
        ),
        admin_headers,
    )
    admitted = client.create_job(
        factories.vessel_job_payload(
            long_dated["id"],
            job_number="J-2885-C39",
            vessel_type=VESSEL_TYPE_HEAT_EXCHANGER,
            mawp_psi=350,
            inside_radius_in=30,
        ),
        admin_headers,
    )

    lapsed = shop.read_certificate(short_dated["id"])
    assert lapsed["status"] == CERT_STATUS_EXPIRED
    assert lapsed["stamping_authorized"] is False
    validate_error(refused, api_errors.ERR_CERTIFICATE_EXPIRED, 409)

    later_job = validate_success(admitted, 201)
    assert later_job["status"] == JOB_STATUS_DRAFT
    assert later_job["required_test_sides"] == REQUIRED_TEST_SIDES_HEAT_EXCHANGER

    _, meta = validate_paginated(
        client.list_jobs(
            admin_headers,
            params={"certificate_id": short_dated["id"], "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 1
