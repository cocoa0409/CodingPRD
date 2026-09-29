"""The derived cost read-out, the authentication gate, role authority and duties."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import test_users as U
from test_helpers.api_errors import (
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
)
from test_helpers.fixtures import Plant

# A DesignReviewer's role header worn by the engineer who authored the design.
AUTHOR_AS_REVIEWER = U.make_headers(U.USER_DESIGN_ENGINEER, C.ROLE_DESIGN_REVIEWER)
# A TestEngineer's role header worn by the technician who wound the stator.
WINDER_AS_TESTER = U.make_headers(U.USER_BUILD_TECHNICIAN, C.ROLE_TEST_ENGINEER)
# A QualityCertifier's role header worn by the engineer who recorded the test.
RECORDER_AS_CERTIFIER = U.make_headers(U.USER_TEST_ENGINEER, C.ROLE_QUALITY_CERTIFIER)


def test_the_cost_read_out_reproduces_eleven_fields_and_the_stored_actual_cost(api):
    """Twelve units and one rejected stator: 149600 per unit through to 195976.

    PRD 3.5: "A derived cost read-out is available for a single work order,
    returning `work_order_id`, `unit_count`, `per_unit_direct_cost_cents`,
    `direct_cost_cents`, `overhead_band`, `overhead_cents`, `standard_cost_cents`,
    `actual_cost_cents`, `cost_variance_cents`, `rework_reject_count` and
    `unit_standard_cost_cents`."

    Design: Corner/endpoints/cost_summary_read_out_matches_the_stored_work_order_cost_roll_up
    """
    design_payload = F.motor_design_payload()
    plant = Plant(api)
    plant.add_distributor()
    plant.add_oven()
    plant.released_design(design_payload)
    plant.add_order()
    plant.confirm_order()
    work_order = plant.add_work_order(unit_count=12)
    rejected = plant.add_stator()
    plant.disposition_stator(
        "REJECTED", stator=rejected, disposition_notes="Slot liner nicked while winding."
    )

    response = api.get_work_order_cost_summary(
        work_order["id"], U.PRODUCTION_PLANNER
    )

    summary = A.assert_ok(response)
    assert response.json()["response_type"] == "object"
    assert response.json()["meta"]["api_request_id"]
    assert response.json()["meta"]["api_request_timestamp"]
    A.assert_cost_summary_figures(
        summary, design_payload, 12, 1, work_order_id=work_order["id"]
    )
    assert summary["unit_count"] == 12
    assert summary["per_unit_direct_cost_cents"] == 149600
    assert summary["direct_cost_cents"] == 1795200
    assert summary["overhead_band"] == "COMPLEX"
    assert summary["overhead_cents"] == 556512
    assert summary["standard_cost_cents"] == 2351712
    assert summary["actual_cost_cents"] == 2414212
    assert summary["cost_variance_cents"] == 62500
    assert summary["rework_reject_count"] == 1
    assert summary["unit_standard_cost_cents"] == 195976
    stored = plant.get_work_order()
    assert stored["actual_cost_cents"] == summary["actual_cost_cents"]
    assert stored["actual_cost_cents"] == 2414212
    assert stored["standard_cost_cents"] == summary["standard_cost_cents"]
    assert stored["cost_variance_cents"] == summary["cost_variance_cents"]
    assert stored["overhead_band"] == summary["overhead_band"]
    assert stored["rework_reject_count"] == 1
    A.assert_cost_rollup(stored, design_payload, 12, 1)


def test_blank_headers_and_an_undeclared_role_all_fail_authentication(api):
    """Three malformed identities answer 401; the well-formed pair returns the row.

    PRD 2.1: "If either header is absent, empty, or if `X-User-Role` does not name
    one of the roles defined below, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing occurs."

    Design: Corner/errors/unauthenticated_calls_are_rejected_for_blank_and_undeclared_headers
    """
    design = validate_success(
        api.create_motor_design(F.motor_design_payload(), U.DESIGN_ENGINEER), 201
    )
    assert design["status"] == "DRAFT"

    blank_role = api.get_motor_design(design["id"], U.EMPTY_ROLE)
    blank_user_id = api.get_motor_design(design["id"], U.EMPTY_USER_ID)
    undeclared_role = api.get_motor_design(design["id"], U.UNDECLARED_ROLE)
    absent_role = api.get_motor_design(design["id"], U.MISSING_ROLE)
    absent_user_id = api.get_motor_design(design["id"], U.MISSING_USER_ID)

    assert U.EMPTY_ROLE["X-User-Role"] == ""
    assert U.EMPTY_USER_ID["X-User-ID"] == ""
    assert U.UNDECLARED_ROLE["X-User-Role"] not in C.ALL_ROLES
    validate_error(blank_role, ERR_UNAUTHENTICATED, 401)
    validate_error(blank_user_id, ERR_UNAUTHENTICATED, 401)
    validate_error(undeclared_role, ERR_UNAUTHENTICATED, 401)
    assert undeclared_role.status_code != 403
    validate_error(absent_role, ERR_UNAUTHENTICATED, 401)
    validate_error(absent_user_id, ERR_UNAUTHENTICATED, 401)
    authenticated = validate_success(
        api.get_motor_design(design["id"], U.DESIGN_ENGINEER), 200
    )
    assert authenticated["status"] == "DRAFT"
    assert authenticated["id"] == design["id"]


def test_nine_endpoints_refuse_the_roles_they_do_not_list(api):
    """Every exclusive operation refuses the other roles, yet a shared read is allowed.

    PRD 2.1: "When the headers are well-formed but the named role is not authorised
    for the target operation, the rejection is `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/every_role_is_denied_the_exclusive_operations_of_the_other_roles
    """
    plant = Plant(api)
    plant.add_distributor()
    cell = plant.add_cell()
    released = plant.released_design()
    under_review = plant.add_design(F.premium_motor_design_payload())
    under_review = plant.submit_design(design=under_review)
    plant.add_order()
    plant.confirm_order()
    work_order = plant.add_work_order()
    draft_order = plant.add_order()
    assert released["status"] == "RELEASED"
    assert under_review["status"] == "IN_REVIEW"
    assert draft_order["status"] == "DRAFT"

    reviewer_authors = api.create_motor_design(
        F.economy_motor_design_payload(), U.DESIGN_REVIEWER
    )
    engineer_approves = api.record_review_decision(
        under_review["id"],
        F.review_decision_payload("APPROVE"),
        U.DESIGN_ENGINEER_OTHER,
    )
    distributor_confirms = api.confirm_customer_order(
        draft_order["id"], F.confirm_order_payload(), plant.distributor_headers
    )
    technician_opens_work_order = api.create_work_order(
        F.work_order_payload(
            draft_order["id"], released["id"], released["version"], unit_count=4
        ),
        U.BUILD_TECHNICIAN,
    )
    tester_winds = api.create_stator_build(
        F.stator_build_payload(work_order["id"]), U.TEST_ENGINEER
    )
    technician_schedules = api.create_performance_test(
        F.performance_test_payload(work_order["id"], cell["id"], 999),
        U.BUILD_TECHNICIAN,
    )
    compliance_certifies = api.create_nameplate(
        F.nameplate_payload(work_order["id"], NON_EXISTENT_UUID), U.COMPLIANCE_OFFICER
    )
    planner_registers_distributor = api.create_distributor(
        F.distributor_payload(name="Westwind Motoren", tier="SILVER"),
        U.PRODUCTION_PLANNER,
    )
    technician_reads_costs = api.get_work_order_cost_summary(
        work_order["id"], U.BUILD_TECHNICIAN
    )
    technician_reads_work_order = api.get_work_order(
        work_order["id"], U.BUILD_TECHNICIAN
    )

    validate_error(reviewer_authors, ERR_UNAUTHORIZED, 403)
    _designs, design_meta = validate_paginated(api.list_motor_designs(U.PLANT_ADMIN))
    assert design_meta["total_count"] == 2
    validate_error(engineer_approves, ERR_UNAUTHORIZED, 403)
    still_in_review = plant.get_design(under_review)
    assert still_in_review["status"] == "IN_REVIEW"
    assert still_in_review["review_round"] == 0
    validate_error(distributor_confirms, ERR_UNAUTHORIZED, 403)
    assert plant.get_order(draft_order)["status"] == "DRAFT"
    validate_error(technician_opens_work_order, ERR_UNAUTHORIZED, 403)
    _work_orders, work_order_meta = validate_paginated(
        api.list_work_orders(U.PLANT_ADMIN)
    )
    assert work_order_meta["total_count"] == 1
    validate_error(tester_winds, ERR_UNAUTHORIZED, 403)
    _stators, stator_meta = validate_paginated(api.list_stator_builds(U.PLANT_ADMIN))
    assert stator_meta["total_count"] == 0
    validate_error(technician_schedules, ERR_UNAUTHORIZED, 403)
    validate_error(compliance_certifies, ERR_UNAUTHORIZED, 403)
    _tests, test_meta = validate_paginated(api.list_performance_tests(U.PLANT_ADMIN))
    assert test_meta["total_count"] == 0
    _nameplates, nameplate_meta = validate_paginated(api.list_nameplates(U.PLANT_ADMIN))
    assert nameplate_meta["total_count"] == 0
    validate_error(planner_registers_distributor, ERR_UNAUTHORIZED, 403)
    _distributors, distributor_meta = validate_paginated(
        api.list_distributors(U.PLANT_ADMIN)
    )
    assert distributor_meta["total_count"] == 1
    validate_error(technician_reads_costs, ERR_UNAUTHORIZED, 403)
    shared_read = validate_success(technician_reads_work_order, 200)
    assert shared_read["build_status"] == "RELEASED"
    assert shared_read["id"] == work_order["id"]
    assert shared_read["certification_status"] == "PENDING"


def test_the_three_separations_of_duty_compare_ids_not_roles(api):
    """Author, winder and recording engineer are each refused, then a colleague succeeds.

    PRD 2.9: "The `DesignReviewer` who records a decision on a design under review
    must not be the `DesignEngineer` who authored it — the acting `X-User-ID` must
    differ from the design's `created_by_user_id`."

    PRD 2.9: "The `TestEngineer` who applies a surge test to an impregnated stator
    must not be the `BuildTechnician` who wound it — the acting `X-User-ID` must
    differ from that stator's `winder_user_id`."

    PRD 2.9: "The `QualityCertifier` who issues a nameplate must not be the
    `TestEngineer` who recorded the performance test the nameplate cites — the acting
    `X-User-ID` must differ from that test's `test_engineer_user_id`."

    Design: Corner/rbac/segregation_of_duties_blocks_the_author_the_winder_and_the_recording_engineer
    """
    plant = Plant(api)
    plant.add_distributor()
    plant.add_oven()
    plant.add_cell()
    standard = plant.add_standard()
    design = plant.add_design()
    design = plant.submit_design()
    assert design["created_by_user_id"] == U.USER_DESIGN_ENGINEER
    assert design["status"] == "IN_REVIEW"

    author_approves = api.record_review_decision(
        design["id"], F.review_decision_payload("APPROVE"), AUTHOR_AS_REVIEWER
    )

    validate_error(author_approves, ERR_SEGREGATION_OF_DUTIES, 403)
    assert AUTHOR_AS_REVIEWER["X-User-Role"] == C.ROLE_DESIGN_REVIEWER
    unchanged = plant.get_design()
    assert unchanged["status"] == "IN_REVIEW"
    assert unchanged["review_round"] == 0
    released = plant.decide_design("APPROVE")
    assert released["status"] == "RELEASED"
    assert released["review_round"] == 1
    assert released["released_by_user_id"] == U.USER_DESIGN_REVIEWER

    plant.add_order()
    plant.confirm_order()
    work_order = plant.add_work_order()
    stator = plant.add_stator()
    assert stator["winder_user_id"] == U.USER_BUILD_TECHNICIAN
    stator = plant.impregnate_stator()
    assert stator["status"] == "IMPREGNATED"

    winder_surge_tests = api.surge_test_stator_build(
        stator["id"], F.surge_test_payload(2.40), WINDER_AS_TESTER
    )

    validate_error(winder_surge_tests, ERR_SEGREGATION_OF_DUTIES, 403)
    assert WINDER_AS_TESTER["X-User-Role"] == C.ROLE_TEST_ENGINEER
    still_impregnated = plant.get_stator()
    assert still_impregnated["status"] == "IMPREGNATED"
    assert still_impregnated["surge_test_kv"] is None
    assert still_impregnated["surge_test_result"] is None
    surged = plant.surge_test_stator()
    assert surged["status"] == "SURGE_TESTED"
    assert surged["surge_test_result"] == "PASS"
    assert surged["surge_tester_user_id"] == U.USER_TEST_ENGINEER
    A.assert_rounded_to(
        surged["insulation_margin_kv"], 0.33, 2, "insulation_margin_kv"
    )

    plant.disposition_stator("ACCEPTED")
    plant.add_rotor()
    plant.form_cage()
    plant.machine_rotor()
    plant.balance_rotor("ACCEPTED")
    plant.add_assembly()
    plant.schedule_test()
    completed = plant.record_test()
    assert completed["status"] == "COMPLETED"
    assert completed["test_engineer_user_id"] == U.USER_TEST_ENGINEER
    A.assert_rounded_to(
        completed["measured_efficiency_pct"], 93.42, 2, "measured_efficiency_pct"
    )

    recorder_certifies = api.create_nameplate(
        F.nameplate_payload(work_order["id"], completed["id"], "EU"),
        RECORDER_AS_CERTIFIER,
    )

    validate_error(recorder_certifies, ERR_SEGREGATION_OF_DUTIES, 403)
    assert RECORDER_AS_CERTIFIER["X-User-Role"] == C.ROLE_QUALITY_CERTIFIER
    _nameplates, nameplate_meta = validate_paginated(api.list_nameplates(U.PLANT_ADMIN))
    assert nameplate_meta["total_count"] == 0
    assert plant.get_work_order()["certification_status"] == "PENDING"
    nameplate = plant.issue_nameplate()
    assert nameplate["status"] == "ISSUED"
    assert nameplate["certifier_user_id"] == U.USER_QUALITY_CERTIFIER
    assert nameplate["standard_id"] == standard["id"]
    A.assert_rounded_to(
        nameplate["stamped_efficiency_pct"], 93.42, 2, "stamped_efficiency_pct"
    )
    A.assert_rounded_to(
        nameplate["minimum_efficiency_pct_applied"],
        89.60,
        2,
        "minimum_efficiency_pct_applied",
    )
    assert plant.get_work_order()["certification_status"] == "CERTIFIED"
