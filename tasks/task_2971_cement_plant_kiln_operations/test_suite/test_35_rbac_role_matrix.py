"""Breadth coverage of the write matrix: for each internal role, the operations it owns succeed
and every other role is refused with 403 on the very same request. Read access is never the
question here — the roles refused a write are, in several of these tests, the heaviest readers of
the row they may not touch.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_amount
from test_helpers.test_users import (
    ADMIN_HEADERS,
    ENGINEER_HEADERS,
    ENV_HEADERS,
    INTERNAL_ROLE_HEADERS,
    LAB_HEADERS,
    LOGISTICS_HEADERS,
    OPERATOR_HEADERS,
    QUALITY_HEADERS,
)

UNAUTHORIZED = ApiErrorId.ERR_UNAUTHORIZED.value


def _refused(response):
    return validate_error(response, UNAUTHORIZED, 403)


# ---------------------------------------------------------------------------
# rbac: the PlantAdmin owns master data and the physical assets
# ---------------------------------------------------------------------------
def test_master_data_and_a_silos_status_belong_to_the_plant_admin_alone(api):
    """The administrator blocks the clinker silo, and then the two roles that read silos all day
    — the engineer who plans batches out of them and the planner who ships out of them — are both
    refused the same PATCH. Read access is not write access: every internal role can still fetch
    the row it may not change, and none of the four refused writes leaves a plant, kiln or silo
    behind.

    PRD: "`PlantAdmin` owns plant master data and physical assets — it alone registers plants,
    kilns and silos, changes a silo's status, approves a kiln outage, and creates an outage whose
    window carries a peak-season override."

    Design: Corner/rbac/plant_admin_master_data_is_exclusive_and_other_roles_are_forbidden
    """
    fx.reset_clock(api)
    env = fx.plant_environment(api)
    silo_id = env["clinker_silo"]["id"]
    version_before = env["clinker_silo"]["version"]

    blocked = validate_success(
        api.patch_silo(
            silo_id,
            {"status": "BLOCKED", "block_reason": "SILO_INSPECTION"},
            ADMIN_HEADERS,
        )
    )
    assert blocked["status"] == "BLOCKED"
    assert blocked["block_reason"] == "SILO_INSPECTION"

    _refused(api.create_plant(f.plant_payload(name="Rogue Plant"), ENGINEER_HEADERS))
    _refused(api.create_kiln(f.kiln_payload(env["plant_id"], code="K9"), OPERATOR_HEADERS))
    _refused(
        api.create_silo(
            f.clinker_silo_payload(env["plant_id"], code="SC9"), QUALITY_HEADERS
        )
    )
    _refused(api.patch_silo(silo_id, {"status": "OPEN"}, ENGINEER_HEADERS))
    _refused(api.patch_silo(silo_id, {"status": "OPEN"}, LOGISTICS_HEADERS))

    still_blocked = validate_success(api.get_silo(silo_id, ADMIN_HEADERS))
    assert still_blocked["status"] == "BLOCKED"
    assert still_blocked["version"] == version_before + 1, (
        "only the administrator's own PATCH may move the version"
    )

    for role, headers in INTERNAL_ROLE_HEADERS.items():
        readable = validate_success(api.get_silo(silo_id, headers))
        assert readable["id"] == silo_id, f"{role} must be able to read the silo"

    _rows, meta = validate_paginated(
        api.list_silos(LOGISTICS_HEADERS, params={"plant_id": env["plant_id"]})
    )
    assert meta["total_count"] == 2, "the refused silo create wrote nothing"
    _plants, plant_meta = validate_paginated(api.list_plants(OPERATOR_HEADERS))
    assert plant_meta["total_count"] == 1
    _kilns, kiln_meta = validate_paginated(
        api.list_kilns(OPERATOR_HEADERS, params={"plant_id": env["plant_id"]})
    )
    assert kiln_meta["total_count"] == 1


# ---------------------------------------------------------------------------
# rbac: the ProcessEngineer authors, the QualityManager approves
# ---------------------------------------------------------------------------
def test_design_authoring_and_pile_blending_belong_to_the_process_engineer(api):
    """The engineer walks its whole half of the design lifecycle — author, amend, submit, and seal
    the bed — while the operator's create, the quality manager's amendment, the planner's addition
    and the environmental officer's pile are all refused. The last call is the point of the split:
    the quality manager that could not touch the recipe's fields is nevertheless the only role
    that can approve it.

    PRD: "`ProcessEngineer` authors raw mix designs, amends and submits them, creates blended
    piles and appends additions to them, seals piles, creates cement batches, and starts and
    completes outages; it shares kiln-run scheduling with `KilnOperator`."

    Design: Corner/rbac/process_engineer_design_and_pile_writes_are_forbidden_to_other_roles
    """
    fx.reset_clock(api)
    env = fx.plant_environment(api)
    approved = fx.create_approved_design(api, env["plant_id"], env["materials"])
    pile = fx.create_open_pile(api, env["plant_id"], approved["id"])
    fx.add_reference_additions(api, pile["id"], env["materials"])

    authored = fx.create_draft_design(api, env["plant_id"], env["materials"], code="D3")
    assert authored["status"] == "DRAFT"
    amended = validate_success(
        api.patch_design(authored["id"], {"target_lsf": 96.50}, ENGINEER_HEADERS)
    )
    assert_amount(amended["target_lsf"], 96.50, "target_lsf")
    submitted = validate_success(api.submit_design(authored["id"], ENGINEER_HEADERS))
    assert submitted["status"] == "SUBMITTED"
    sealed = validate_success(api.seal_pile(pile["id"], ENGINEER_HEADERS))
    assert sealed["status"] == "SEALED"

    _refused(
        api.create_design(
            f.design_payload(
                env["plant_id"],
                fx.reference_components(env["materials"]),
                code="D9",
            ),
            OPERATOR_HEADERS,
        )
    )
    _refused(
        api.patch_design(authored["id"], {"target_lsf": 90.00}, QUALITY_HEADERS)
    )
    _refused(
        api.add_pile_addition(
            pile["id"],
            f.addition_payload(env["materials"]["iron_ore"]["id"], 10.00, 5.0),
            LOGISTICS_HEADERS,
        )
    )
    _refused(
        api.create_pile(
            f.pile_payload(
                env["plant_id"], approved["id"], approved["version"], pile_code="PZ"
            ),
            ENV_HEADERS,
        )
    )

    unmoved = validate_success(api.get_design(authored["id"], QUALITY_HEADERS))
    assert unmoved["status"] == "SUBMITTED"
    assert_amount(unmoved["target_lsf"], 96.50, "target_lsf")

    bed = validate_success(api.get_pile(pile["id"], LOGISTICS_HEADERS))
    assert bed["status"] == "SEALED"
    assert len(bed["additions"]) == 2
    assert_amount(bed["dry_tonnes"], 1000.00, "dry_tonnes")

    approval = validate_success(api.approve_design(authored["id"], QUALITY_HEADERS))
    assert approval["status"] == "APPROVED"


# ---------------------------------------------------------------------------
# rbac: the KilnOperator fires, and the quality dimension is not its business
# ---------------------------------------------------------------------------
def test_firing_a_kiln_belongs_to_the_operator_and_releasing_clinker_does_not(api):
    """Scheduling is shared, so the engineer's run is created alongside the operator's; every
    action after that is the operator's alone, and the engineer's light on a run that is already
    burning is refused on the role rather than on the state. The telling refusal is the last one
    before the abort: the operator that fired the kiln may not release the clinker it made,
    because the run's quality dimension answers to a different role entirely.

    PRD: "`KilnOperator` fires kilns — lighting a run, charging fuel, completing and aborting a
    run — and drives the finish mill by starting and finishing grinding."

    Design: Corner/rbac/kiln_operator_firing_actions_are_forbidden_to_other_roles
    """
    fx.reset_clock(api)
    env = fx.plant_environment(api)
    design = fx.create_approved_design(api, env["plant_id"], env["materials"])
    first_bed = fx.create_sealed_pile(
        api, env["plant_id"], design["id"], env["materials"], pile_code="PA"
    )
    second_bed = fx.create_sealed_pile(
        api, env["plant_id"], design["id"], env["materials"], pile_code="PB"
    )

    shared = validate_success(
        api.create_kiln_run(
            f.kiln_run_payload(
                env["kiln"]["id"],
                second_bed["id"],
                env["clinker_silo"]["id"],
                window_start="2026-08-02T00:00:00Z",
                window_end="2026-08-02T12:00:00Z",
            ),
            ENGINEER_HEADERS,
        ),
        201,
    )
    assert shared["process_state"] == "SCHEDULED"

    run = validate_success(
        api.create_kiln_run(
            f.kiln_run_payload(
                env["kiln"]["id"], first_bed["id"], env["clinker_silo"]["id"]
            ),
            OPERATOR_HEADERS,
        ),
        201,
    )
    run_id = run["id"]
    validate_success(api.light_kiln_run(run_id, OPERATOR_HEADERS))
    validate_success(
        api.charge_fuel(
            run_id, f.fuel_charge_payload(env["fuels"]["gas"]["id"], 45.00), OPERATOR_HEADERS
        )
    )
    topped_up = validate_success(
        api.charge_fuel(
            run_id, f.fuel_charge_payload(env["fuels"]["coal"]["id"], 5.00), OPERATOR_HEADERS
        )
    )
    assert_amount(topped_up["gross_energy_gj"], 2295.00, "gross_energy_gj")

    _refused(api.light_kiln_run(run_id, ENGINEER_HEADERS))
    _refused(
        api.charge_fuel(
            run_id, f.fuel_charge_payload(env["fuels"]["coal"]["id"], 5.00), QUALITY_HEADERS
        )
    )
    _refused(api.complete_kiln_run(run_id, LOGISTICS_HEADERS))
    _refused(api.abort_kiln_run(run_id, {"abort_reason": "curiosity"}, LAB_HEADERS))
    _refused(api.release_clinker(run_id, OPERATOR_HEADERS))

    intact = validate_success(api.get_kiln_run(run_id, LAB_HEADERS))
    assert intact["process_state"] == "BURNING"
    assert intact["quality_state"] == "PENDING_LAB"
    assert_amount(intact["gross_energy_gj"], 2295.00, "gross_energy_gj")

    aborted = validate_success(
        api.abort_kiln_run(
            run_id, {"abort_reason": "REFRACTORY_ALARM"}, OPERATOR_HEADERS
        )
    )
    assert aborted["process_state"] == "ABORTED"


# ---------------------------------------------------------------------------
# rbac: the LabTechnician measures, and the burn-test lifecycle is split
# ---------------------------------------------------------------------------
def test_measurements_belong_to_the_lab_technician_across_two_lifecycles(api):
    """The technician's Blaine reading is accepted and closes the fineness branch, while the
    quality manager's strength reading on the same batch is refused and leaves that branch
    pending. The trial burn is split three ways in the same test: its creation is shared with the
    environmental officer, but only the technician may start it and record its result — and the
    officer that created the row is refused the measurement.

    PRD: "`LabTechnician` records every measurement: laboratory tests, and the start and result of
    a trial burn; it shares burn-test creation with `EnvironmentalOfficer`."

    Design: Corner/rbac/lab_technician_measurement_writes_are_forbidden_to_other_roles
    """
    fx.reset_clock(api)
    env = fx.released_clinker_environment(api)
    batch = fx.create_ground_batch(
        api, env["plant_id"], env["clinker_silo"]["id"], env["cement_silo"]["id"]
    )

    fineness = validate_success(
        api.create_lab_test(
            f.lab_test_payload("BLAINE", 400, cement_batch_id=batch["id"]), LAB_HEADERS
        ),
        201,
    )
    assert fineness["in_spec"] is True
    _refused(
        api.create_lab_test(
            f.lab_test_payload(
                "COMPRESSIVE_STRENGTH_28D", 30.0, cement_batch_id=batch["id"]
            ),
            QUALITY_HEADERS,
        )
    )

    half_tested = validate_success(api.get_cement_batch(batch["id"], ENGINEER_HEADERS))
    assert half_tested["fineness_branch_state"] == "PASSED"
    assert half_tested["strength_branch_state"] == "PENDING"
    assert half_tested["status"] == "GROUND"

    shared_create = validate_success(
        api.create_burn_test(
            f.burn_test_payload(env["plant_id"], env["fuels"]["rdf"]["id"]), ENV_HEADERS
        ),
        201,
    )
    assert shared_create["status"] == "REQUESTED"
    burn_test_id = shared_create["id"]

    _refused(api.start_burn_test(burn_test_id, ENGINEER_HEADERS))
    started = validate_success(api.start_burn_test(burn_test_id, LAB_HEADERS))
    assert started["status"] == "IN_PROGRESS"

    _refused(
        api.record_burn_test_result(burn_test_id, f.burn_result_payload(), ENV_HEADERS)
    )
    recorded = validate_success(
        api.record_burn_test_result(burn_test_id, f.burn_result_payload(), LAB_HEADERS)
    )
    assert recorded["status"] == "RESULT_RECORDED"
    assert recorded["version"] == shared_create["version"] + 2, (
        "only the two accepted transitions moved the row"
    )


# ---------------------------------------------------------------------------
# rbac: the QualityManager signs for quality — approvals and certificates
# ---------------------------------------------------------------------------
def test_certificates_and_design_approval_belong_to_the_quality_manager(api):
    """The certificate's three writes are walked in order — draft, issue, revoke — and each one is
    first refused to a different role: the administrator that owns the silos cannot draft, the
    engineer that made the cement cannot issue, and the planner that will ship it cannot revoke.
    The same role then closes the design loop by approving a recipe the administrator was refused.

    PRD: "`QualityManager` requests revisions of and approves raw mix designs, releases clinker,
    and creates, issues and revokes mill certificates."

    Design: Corner/rbac/quality_manager_approval_and_certificate_writes_are_forbidden_to_other_roles
    """
    fx.reset_clock(api)
    env = fx.qualified_cement_environment(api)
    customer = fx.create_customer(api)
    batch_id = env["batch"]["id"]

    _refused(
        api.create_mill_certificate(
            f.mill_certificate_payload(batch_id, customer["id"], 100.00), ADMIN_HEADERS
        )
    )
    draft = validate_success(
        api.create_mill_certificate(
            f.mill_certificate_payload(batch_id, customer["id"], 100.00), QUALITY_HEADERS
        ),
        201,
    )
    assert draft["status"] == "DRAFT"
    certificate_id = draft["id"]

    _refused(api.issue_mill_certificate(certificate_id, ENGINEER_HEADERS))
    issued = validate_success(api.issue_mill_certificate(certificate_id, QUALITY_HEADERS))
    assert issued["status"] == "ISSUED"
    assert issued["revoked_at"] is None

    certified = validate_success(api.get_cement_batch(batch_id, ENGINEER_HEADERS))
    assert certified["status"] == "CERTIFIED"
    assert_amount(
        certified["certified_tonnes_allocated"], 100.00, "certified_tonnes_allocated"
    )

    _refused(
        api.revoke_mill_certificate(
            certificate_id, {"revoke_reason": "unauthorised attempt"}, LOGISTICS_HEADERS
        )
    )
    intact = validate_success(api.get_mill_certificate(certificate_id, LOGISTICS_HEADERS))
    assert intact["status"] == "ISSUED"
    assert intact["revoked_at"] is None

    revoked = validate_success(
        api.revoke_mill_certificate(
            certificate_id, {"revoke_reason": "STRENGTH_RETEST_FAILED"}, QUALITY_HEADERS
        )
    )
    assert revoked["status"] == "REVOKED"
    assert revoked["revoked_at"] is not None

    design = fx.create_draft_design(api, env["plant_id"], env["materials"], code="D4")
    validate_success(api.submit_design(design["id"], ENGINEER_HEADERS))
    _refused(api.approve_design(design["id"], ADMIN_HEADERS))
    approved = validate_success(api.approve_design(design["id"], QUALITY_HEADERS))
    assert approved["status"] == "APPROVED"


# ---------------------------------------------------------------------------
# rbac: the air permit is the EnvironmentalOfficer's, and adjudication is sole
# ---------------------------------------------------------------------------
def test_only_the_environmental_officer_adjudicates_a_trial_burn(api):
    """Fuel registration is shared and the administrator's tyre-derived fuel lands, while the
    engineer's is refused. Adjudication is not shared with anyone: the technician who performed
    the stack test and the quality manager who signs for everything else in the plant are both
    refused with the role error rather than a two-person-control error, and the burn test does not
    move until the officer decides.

    PRD: "`EnvironmentalOfficer` owns the air permit: it registers fuels and is the only role that
    may adjudicate a trial burn."

    Design: Corner/rbac/environmental_officer_adjudication_is_forbidden_to_other_roles
    """
    fx.reset_clock(api)
    env = fx.plant_environment(api)

    shared_fuel = validate_success(api.create_fuel(f.tdf_payload("TDF-9"), ADMIN_HEADERS), 201)
    assert shared_fuel["code"] == "TDF-9"
    _refused(api.create_fuel(f.rdf_payload("RDF-9"), ENGINEER_HEADERS))

    burn = validate_success(
        api.create_burn_test(
            f.burn_test_payload(env["plant_id"], env["fuels"]["tdf"]["id"]), LAB_HEADERS
        ),
        201,
    )
    validate_success(api.start_burn_test(burn["id"], LAB_HEADERS))
    recorded = validate_success(
        api.record_burn_test_result(burn["id"], f.burn_result_payload(), LAB_HEADERS)
    )
    assert recorded["status"] == "RESULT_RECORDED"

    _refused(
        api.adjudicate_burn_test(
            burn["id"], f.adjudication_payload("AUTHORIZED", 10.00), LAB_HEADERS
        )
    )
    _refused(
        api.adjudicate_burn_test(
            burn["id"], f.adjudication_payload("AUTHORIZED", 10.00), QUALITY_HEADERS
        )
    )
    unmoved = validate_success(api.get_burn_test(burn["id"], OPERATOR_HEADERS))
    assert unmoved["status"] == "RESULT_RECORDED"
    assert unmoved["version"] == recorded["version"], "a refusal never moves the row"

    authorized = validate_success(
        api.adjudicate_burn_test(
            burn["id"], f.adjudication_payload("AUTHORIZED", 10.00), ENV_HEADERS
        )
    )
    assert authorized["status"] == "AUTHORIZED"
    assert_amount(
        authorized["authorized_max_tsr_pct"], 10.00, "authorized_max_tsr_pct"
    )

    _rows, meta = validate_paginated(api.list_fuels(ENV_HEADERS))
    assert meta["total_count"] == 5, "the engineer's fuel was never registered"


# ---------------------------------------------------------------------------
# rbac: the terminal is the LogisticsPlanner's, front to back
# ---------------------------------------------------------------------------
def test_the_terminal_and_its_customers_belong_to_the_logistics_planner(api):
    """All four loadout writes are attempted by four different foreign roles against one reserved
    appointment, and all four are refused: the order stays reserved, unstarted, with its 120.00
    tonnes still promised in the silo. The planner then voids it — releasing exactly those tonnes —
    and administers a customer the kiln operator may not create.

    PRD: "`LogisticsPlanner` runs the terminal: loadout order creation, start of loading,
    completion and voiding, plus customer administration and distribution planning."

    Design: Corner/rbac/logistics_planner_loadout_writes_are_forbidden_to_other_roles
    """
    fx.reset_clock(api)
    env = fx.certificate_chain(api)
    order_id = env["order"]["id"]
    assert env["order"]["status"] == "RESERVED"

    _refused(
        api.create_loadout_order(
            f.loadout_order_payload(
                env["customer"]["id"],
                env["cement_silo"]["id"],
                env["certificate"]["id"],
                env["certificate"]["version"],
                tonnes=50.00,
            ),
            ADMIN_HEADERS,
        )
    )
    _refused(api.start_loading(order_id, QUALITY_HEADERS))
    _refused(
        api.complete_loadout_order(order_id, {"loaded_tonnes": 120.00}, ENGINEER_HEADERS)
    )
    _refused(
        api.void_loadout_order(
            order_id, {"void_reason": "unauthorised attempt"}, OPERATOR_HEADERS
        )
    )

    intact = validate_success(api.get_loadout_order(order_id, ADMIN_HEADERS))
    assert intact["status"] == "RESERVED"
    assert intact["loading_started_at"] is None

    promised = validate_success(
        api.get_silo(env["cement_silo"]["id"], LOGISTICS_HEADERS)
    )
    assert_amount(promised["reserved_tonnes"], 120.00, "reserved_tonnes")

    voided = validate_success(
        api.void_loadout_order(
            order_id, {"void_reason": "CUSTOMER_CANCELLED"}, LOGISTICS_HEADERS
        )
    )
    assert voided["status"] == "VOIDED"
    freed = validate_success(api.get_silo(env["cement_silo"]["id"], LOGISTICS_HEADERS))
    assert_amount(freed["reserved_tonnes"], 0.00, "reserved_tonnes")

    _refused(
        api.create_customer(f.customer_payload(name="Rogue Ready-Mix"), OPERATOR_HEADERS)
    )
    buyer = validate_success(
        api.create_customer(
            f.customer_payload(name="Northern Blocks"), LOGISTICS_HEADERS
        ),
        201,
    )
    amended = validate_success(
        api.patch_customer(
            buyer["id"], {"contract_monthly_tonnes": 5000.00}, LOGISTICS_HEADERS
        )
    )
    assert_amount(
        amended["contract_monthly_tonnes"], 5000.00, "contract_monthly_tonnes"
    )
    _customers, customer_meta = validate_paginated(api.list_customers(OPERATOR_HEADERS))
    assert customer_meta["total_count"] == 2, "the operator's customer was never created"
