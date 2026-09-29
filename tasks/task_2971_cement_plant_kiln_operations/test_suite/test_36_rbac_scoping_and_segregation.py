"""Breadth coverage of the three authorisation mechanisms that are not a plain role check: the
external customer's per-row scope, the two two-person controls that compare user ids rather than
roles, and the shared endpoints whose pairs of owners are all different — plus the universal read
privilege and the one payload field only an administrator may send.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_amount, assert_int
from test_helpers.constants import (
    ROLE_ENVIRONMENTAL_OFFICER,
    ROLE_QUALITY_MANAGER,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    ENG1_ID,
    ENGINEER_HEADERS,
    ENV_HEADERS,
    EO1_ID,
    LAB1_ID,
    LAB_HEADERS,
    LOGISTICS_HEADERS,
    OPERATOR_HEADERS,
    QM1_ID,
    QUALITY_HEADERS,
    make_customer_headers,
    make_headers,
)

UNAUTHORIZED = ApiErrorId.ERR_UNAUTHORIZED.value
SCOPE_VIOLATION = ApiErrorId.ERR_CUSTOMER_SCOPE_VIOLATION.value
SEGREGATION = ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value


# ---------------------------------------------------------------------------
# rbac: the Customer's authority is per row, and it differs between reads
# ---------------------------------------------------------------------------
def test_a_customer_reads_only_its_own_rows_and_writes_nothing(api):
    """One buyer owns a certificate and an appointment; a second buyer owns nothing. The same scope
    rule then answers in two different shapes: the bystander's single reads are refused outright
    while its list read succeeds and simply comes back empty. The two write and read attempts that
    close the test show the other half of the rule — off the two collections the role is not on the
    endpoint at all, so the answer is the plain role error rather than the scope error.

    PRD: "The `Customer` role may write nothing at all. It may read exactly two collections, and
    only its own rows within them: mill certificates and loadout orders. On the two list reads, the
    result set is silently filtered to rows whose `customer_id` equals the caller's `X-User-ID` — an
    out-of-scope row is absent from the page rather than an error. On the two single-row reads, a
    request for a row belonging to another customer is refused with `ERR_CUSTOMER_SCOPE_VIOLATION`
    (HTTP 403)."

    Design: Corner/rbac/customer_role_cannot_write_and_cannot_read_another_customers_rows
    """
    fx.reset_clock(api)
    env = fx.certificate_chain(api)
    owner_id = env["customer"]["id"]
    bystander = fx.create_customer(
        api,
        name="Bystander Buyer",
        contract_priority=50,
        contract_monthly_tonnes=500.00,
    )
    owner_headers = make_customer_headers(owner_id)
    bystander_headers = make_customer_headers(bystander["id"])

    own_certificate = validate_success(
        api.get_mill_certificate(env["certificate"]["id"], owner_headers)
    )
    assert own_certificate["customer_id"] == owner_id

    validate_error(
        api.get_mill_certificate(env["certificate"]["id"], bystander_headers),
        SCOPE_VIOLATION,
        403,
    )
    validate_error(
        api.get_loadout_order(env["order"]["id"], bystander_headers),
        SCOPE_VIOLATION,
        403,
    )

    empty, empty_meta = validate_paginated(
        api.list_loadout_orders(bystander_headers, params={"limit": 50, "offset": 0})
    )
    assert empty == [], "an out-of-scope row is absent from the page rather than an error"
    assert empty_meta["total_count"] == 0

    mine, mine_meta = validate_paginated(
        api.list_loadout_orders(owner_headers, params={"limit": 50, "offset": 0})
    )
    assert mine_meta["total_count"] == 1
    assert [row["id"] for row in mine] == [env["order"]["id"]]

    validate_error(
        api.create_loadout_order(
            f.loadout_order_payload(
                owner_id,
                env["cement_silo"]["id"],
                env["certificate"]["id"],
                env["certificate"]["version"],
                window_start="2026-08-07T06:00:00Z",
                window_end="2026-08-07T08:00:00Z",
                tonnes=10.00,
            ),
            owner_headers,
        ),
        UNAUTHORIZED,
        403,
    )
    validate_error(api.get_plant(env["plant_id"], owner_headers), UNAUTHORIZED, 403)


# ---------------------------------------------------------------------------
# rbac: the design two-person control compares user ids, not roles
# ---------------------------------------------------------------------------
def test_the_author_of_a_design_cannot_review_it_in_a_managers_role(api):
    """The engineer who wrote and submitted the recipe comes back wearing the quality manager's
    role. The endpoint admits that role, so the refusal is the two-person-control error and not the
    role error. PRD 2.8 puts this control on three decisions only — "design approval, burn-test
    adjudication and certificate issue" — so approval is the manager's verb it bites on. A
    genuinely different user then approves, and only that accepted call moves the version.

    PRD: "The approver's `X-User-ID` must differ from the design's `created_by_user_id`; an engineer
    who approves their own recipe is refused with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/design_author_cannot_approve_its_own_design
    """
    fx.reset_clock(api)
    env = fx.plant_environment(api)

    design = fx.create_draft_design(api, env["plant_id"], env["materials"], code="D5")
    assert design["created_by_user_id"] == ENG1_ID
    submitted = validate_success(api.submit_design(design["id"], ENGINEER_HEADERS))
    assert submitted["status"] == "SUBMITTED"

    author_as_manager = make_headers(ENG1_ID, ROLE_QUALITY_MANAGER)
    validate_error(
        api.approve_design(design["id"], author_as_manager), SEGREGATION, 403
    )

    stalled = validate_success(api.get_design(design["id"], ENGINEER_HEADERS))
    assert stalled["status"] == "SUBMITTED"
    assert stalled["approved_by_user_id"] is None
    assert stalled["created_by_user_id"] == ENG1_ID
    assert stalled["version"] == submitted["version"]

    approved = validate_success(api.approve_design(design["id"], QUALITY_HEADERS))
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == QM1_ID
    assert approved["created_by_user_id"] == ENG1_ID
    assert approved["version"] == submitted["version"] + 1


# ---------------------------------------------------------------------------
# rbac: the trial-burn control bars the recorder, not the requester
# ---------------------------------------------------------------------------
def test_the_technician_who_recorded_a_stack_test_cannot_sign_it_off(api):
    """The officer requests the trial burn, the technician measures it, and then the technician
    wearing the officer's role is refused — twice, once for each decision, because the control is on
    the act of adjudicating and not on its outcome. The officer who requested the test is then
    allowed to adjudicate it, which is the whole point: the bar compares the adjudicator against the
    recorder alone.

    PRD: "In both branches the adjudicating `X-User-ID` must differ from `result_recorded_by_user_id`,
    so a technician may not sign off on their own stack test; a violation is refused with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/burn_test_recorder_cannot_adjudicate_its_own_result
    """
    fx.reset_clock(api)
    env = fx.plant_environment(api)

    burn = validate_success(
        api.create_burn_test(
            f.burn_test_payload(env["plant_id"], env["fuels"]["tdf"]["id"], 10.00, 30),
            ENV_HEADERS,
        ),
        201,
    )
    validate_success(api.start_burn_test(burn["id"], LAB_HEADERS))
    recorded = validate_success(
        api.record_burn_test_result(
            burn["id"], f.burn_result_payload(0.10, 0.18, True), LAB_HEADERS
        )
    )
    assert recorded["status"] == "RESULT_RECORDED"
    assert recorded["result_recorded_by_user_id"] == LAB1_ID

    recorder_as_officer = make_headers(LAB1_ID, ROLE_ENVIRONMENTAL_OFFICER)
    validate_error(
        api.adjudicate_burn_test(
            burn["id"], f.adjudication_payload("AUTHORIZED", 10.00), recorder_as_officer
        ),
        SEGREGATION,
        403,
    )
    validate_error(
        api.adjudicate_burn_test(
            burn["id"],
            f.adjudication_payload("REJECTED", None, "chlorine too high"),
            recorder_as_officer,
        ),
        SEGREGATION,
        403,
    )

    stalled = validate_success(api.get_burn_test(burn["id"], LAB_HEADERS))
    assert stalled["status"] == "RESULT_RECORDED"
    assert stalled["valid_from"] is None
    assert stalled["valid_until"] is None
    assert stalled["version"] == recorded["version"]

    authorized = validate_success(
        api.adjudicate_burn_test(
            burn["id"], f.adjudication_payload("AUTHORIZED", 10.00), ENV_HEADERS
        )
    )
    assert authorized["status"] == "AUTHORIZED"
    assert authorized["result_recorded_by_user_id"] == LAB1_ID
    assert authorized["adjudicated_by_user_id"] == EO1_ID
    assert_amount(
        authorized["authorized_max_tsr_pct"], 10.00, "authorized_max_tsr_pct"
    )


# ---------------------------------------------------------------------------
# rbac: the shared endpoints pair different roles on every one
# ---------------------------------------------------------------------------
def test_each_shared_endpoint_admits_its_own_pair_and_nobody_else(api):
    """Four endpoints, four different pairs of owners, and the negatives are the point: the engineer
    that shares raw materials and outages with the administrator is refused on fuels, the technician
    that may read everything else in the API is refused the distribution plan, and the quality
    manager is refused an outage that two other roles may plan. Nothing the refusals attempted
    survives — the fuel catalogue and the outage list both come back at their pre-attempt sizes.

    PRD: "It shares raw-material registration with `ProcessEngineer`, fuel registration with
    `EnvironmentalOfficer`, customer creation and customer amendment with `LogisticsPlanner`, plain
    outage planning with `ProcessEngineer`, and distribution planning with `LogisticsPlanner`."

    Design: Corner/rbac/shared_operations_admit_both_owners_and_refuse_everyone_else_unauthorized
    """
    fx.reset_clock(api)
    env = fx.plant_environment(api)
    kiln_id = env["kiln"]["id"]

    shared_material = validate_success(
        api.create_raw_material(f.limestone_payload("LS-2"), ADMIN_HEADERS), 201
    )
    assert shared_material["code"] == "LS-2"
    validate_error(
        api.create_raw_material(f.limestone_payload("LS-3"), LAB_HEADERS),
        UNAUTHORIZED,
        403,
    )
    validate_error(
        api.create_fuel(f.coal_payload("COAL-2"), ENGINEER_HEADERS), UNAUTHORIZED, 403
    )
    validate_error(
        api.create_burn_test(
            f.burn_test_payload(env["plant_id"], env["fuels"]["rdf"]["id"]),
            OPERATOR_HEADERS,
        ),
        UNAUTHORIZED,
        403,
    )

    by_admin = validate_success(
        api.create_outage(
            f.outage_payload(
                kiln_id, "2026-10-05T00:00:00Z", "2026-10-06T00:00:00Z", "MECHANICAL"
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    assert by_admin["status"] == "PLANNED"
    by_engineer = validate_success(
        api.create_outage(
            f.outage_payload(
                kiln_id, "2026-10-08T00:00:00Z", "2026-10-09T00:00:00Z", "COMBINED"
            ),
            ENGINEER_HEADERS,
        ),
        201,
    )
    assert by_engineer["status"] == "PLANNED"
    validate_error(
        api.create_outage(
            f.outage_payload(
                kiln_id, "2026-10-11T00:00:00Z", "2026-10-12T00:00:00Z", "COMBINED"
            ),
            QUALITY_HEADERS,
        ),
        UNAUTHORIZED,
        403,
    )

    validate_error(
        api.get_distribution_plan(env["plant_id"], LAB_HEADERS, params={"as_of_month": 8}),
        UNAUTHORIZED,
        403,
    )

    _outages, outage_meta = validate_paginated(
        api.list_outages(OPERATOR_HEADERS, params={"kiln_id": kiln_id})
    )
    assert outage_meta["total_count"] == 2, "the refused outage left no row"
    _fuels, fuel_meta = validate_paginated(api.list_fuels(OPERATOR_HEADERS))
    assert fuel_meta["total_count"] == 4, "the engineer's fuel was never registered"
    _materials, material_meta = validate_paginated(api.list_raw_materials(LAB_HEADERS))
    assert material_meta["total_count"] == 4


# ---------------------------------------------------------------------------
# rbac: reads are universal across the seven internal roles
# ---------------------------------------------------------------------------
def test_seven_roles_read_seven_resources_none_of_which_they_may_write(api):
    """Each of the seven internal roles is handed exactly one read it could never perform as a
    write: the operator reads the recipe it may not author, the technician the silo it may not
    block, the planner the run it may not fire, and so on. The payloads are whole rather than
    redacted — the operator sees the design's computed modules and the planner sees the run's
    clinker and emissions — and after all seven reads not one version has moved.

    PRD: "The first seven are the plant's internal roles and every one of them may perform every
    read (GET) operation in the API; write authority is partitioned among them as §4 records."

    Design: Corner/rbac/every_get_is_open_to_all_seven_internal_roles
    """
    fx.reset_clock(api)
    env = fx.released_clinker_environment(api)

    design = validate_success(api.get_design(env["design"]["id"], OPERATOR_HEADERS))
    assert_amount(design["as_designed_lsf"], 96.98, "as_designed_lsf")
    assert design["status"] == "APPROVED"

    silo = validate_success(api.get_silo(env["clinker_silo"]["id"], LAB_HEADERS))
    assert silo["status"] == "OPEN"

    run = validate_success(api.get_kiln_run(env["run"]["id"], LOGISTICS_HEADERS))
    assert_amount(run["clinker_tonnes"], 583.78, "clinker_tonnes")
    assert_amount(run["nox_emitted_kg"], 216.00, "nox_emitted_kg")

    pile = validate_success(api.get_pile(env["pile"]["id"], ENV_HEADERS))
    assert pile["status"] == "CONSUMED"

    plant = validate_success(api.get_plant(env["plant_id"], QUALITY_HEADERS))
    assert plant["id"] == env["plant_id"]

    _kilns, kiln_meta = validate_paginated(
        api.list_kilns(ENGINEER_HEADERS, params={"plant_id": env["plant_id"], "limit": 50, "offset": 0})
    )
    assert kiln_meta["total_count"] == 1

    tests, test_meta = validate_paginated(
        api.list_lab_tests(ADMIN_HEADERS, params={"kiln_run_id": env["run"]["id"]})
    )
    assert test_meta["total_count"] == 1
    assert tests[0]["test_type"] == "FREE_LIME"

    assert validate_success(api.get_design(env["design"]["id"], QUALITY_HEADERS))[
        "version"
    ] == design["version"]
    assert validate_success(api.get_silo(env["clinker_silo"]["id"], ADMIN_HEADERS))[
        "version"
    ] == silo["version"]
    assert validate_success(api.get_kiln_run(env["run"]["id"], OPERATOR_HEADERS))[
        "version"
    ] == run["version"]
    assert validate_success(api.get_pile(env["pile"]["id"], ENGINEER_HEADERS))[
        "version"
    ] == pile["version"]


# ---------------------------------------------------------------------------
# rbac: the peak-season override is a payload privilege, not an endpoint one
# ---------------------------------------------------------------------------
def test_the_peak_season_override_is_a_payload_privilege_of_the_administrator(api):
    """August is a peak month, so the same window is refused three ways before it is allowed: the
    engineer sending the override is refused on the flag rather than on the endpoint — a 422 and not
    a 403, because the engineer may plan outages — and the administrator omitting it is refused
    identically, since both legs of the rule must hold at once. The October window then shows the
    gate only bites on peak months, and neither refusal left a row.

    PRD: "Because an outage in peak season costs the plant sales it cannot recover, a window
    intersecting any peak month is permitted only when `peak_season_override` is true **and** the
    caller is a `PlantAdmin`; that flag defaults to false, and a peak-season window without a
    `PlantAdmin` override is refused with `ERR_PEAK_SEASON_OUTAGE`."

    Design: Corner/rbac/only_a_plant_admin_can_set_the_peak_season_override
    """
    fx.reset_clock(api)
    env = fx.plant_environment(api)
    kiln_id = env["kiln"]["id"]
    peak_window = ("2026-08-15T00:00:00Z", "2026-08-17T00:00:00Z")

    validate_error(
        api.create_outage(
            f.outage_payload(
                kiln_id, peak_window[0], peak_window[1], "REFRACTORY",
                peak_season_override=True,
            ),
            ENGINEER_HEADERS,
        ),
        ApiErrorId.ERR_PEAK_SEASON_OUTAGE.value,
        422,
    )
    validate_error(
        api.create_outage(
            f.outage_payload(kiln_id, peak_window[0], peak_window[1], "REFRACTORY"),
            ADMIN_HEADERS,
        ),
        ApiErrorId.ERR_PEAK_SEASON_OUTAGE.value,
        422,
    )

    allowed = validate_success(
        api.create_outage(
            f.outage_payload(
                kiln_id, peak_window[0], peak_window[1], "REFRACTORY",
                peak_season_override=True,
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    assert allowed["demand_season_class"] == "PEAK"
    assert allowed["peak_season_override"] is True
    assert allowed["status"] == "PLANNED"

    shoulder = validate_success(
        api.create_outage(
            f.outage_payload(
                kiln_id, "2026-10-20T00:00:00Z", "2026-10-22T00:00:00Z", "COMBINED"
            ),
            ENGINEER_HEADERS,
        ),
        201,
    )
    assert shoulder["demand_season_class"] == "SHOULDER"
    assert shoulder["peak_season_override"] is False

    _outages, meta = validate_paginated(
        api.list_outages(OPERATOR_HEADERS, params={"kiln_id": kiln_id})
    )
    assert_int(meta["total_count"], 2, "total_count")
