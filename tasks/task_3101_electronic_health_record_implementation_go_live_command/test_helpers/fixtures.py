"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() from the framework (lenient validator) so setup failures
produce clear "setup failed" errors rather than confusing assertion failures.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS, CLOCK_STARTUP_DEFAULT
from .factories import (
    create_ehr_implementation_payload,
    create_facility_payload,
    create_department_payload,
    create_build_item_payload,
    create_staff_payload,
    create_training_assignment_payload,
    create_credentialed_trainer_payload,
    create_proficiency_exam_payload,
    create_test_scenario_payload,
    create_defect_payload,
    create_conversion_batch_payload,
    create_patient_order_payload,
    create_interface_channel_payload,
    create_interface_message_payload,
    create_cutover_task_payload,
    create_ticket_payload,
    create_staffing_shift_payload,
    create_optimization_item_payload,
)
from .test_users import TEST_USERS, make_credentialed_trainer_headers


# ---------------------------------------------------------------------------
# Convenient header aliases
# ---------------------------------------------------------------------------
DIRECTOR = TEST_USERS["implementation_director_headers"]
ANALYST = TEST_USERS["implementation_analyst_headers"]
BUILD_ANALYST = TEST_USERS["build_analyst_headers"]
TEST_LEAD = TEST_USERS["test_lead_headers"]
TRAINING = TEST_USERS["training_coordinator_headers"]
CONVERSION = TEST_USERS["conversion_analyst_headers"]
RECONCILER = TEST_USERS["order_reconciler_headers"]
REVENUE = TEST_USERS["revenue_cycle_analyst_headers"]
INTERFACE = TEST_USERS["interface_engineer_headers"]
CUTOVER = TEST_USERS["cutover_lead_headers"]
COMMAND_CENTER = TEST_USERS["command_center_lead_headers"]
TRIAGE = TEST_USERS["triage_commander_headers"]
OPTIMIZATION = TEST_USERS["optimization_lead_headers"]


# ===========================================================================
# Tier 0 — primitives
# ===========================================================================

def set_clock(to_iso8601: str = CLOCK_STARTUP_DEFAULT):
    """Move the logical clock. Every time-derived value follows this instant."""
    return get_success_data(
        api_client.set_current_utc({"to_iso8601": to_iso8601}, DIRECTOR)
    )


def create_program(**overrides) -> dict:
    return get_success_data(
        api_client.create_ehr_implementation(create_ehr_implementation_payload(**overrides), DIRECTOR)
    )


def get_program(prog_id: str, headers=None, params=None) -> dict:
    return get_success_data(
        api_client.get_ehr_implementation(prog_id, headers or DIRECTOR, params)
    )


def create_facility(prog_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_facility(prog_id, create_facility_payload(**overrides), DIRECTOR)
    )


def get_facility(fac_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_facility(fac_id, headers or ANALYST))


def create_department(fac_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_department(fac_id, create_department_payload(**overrides), BUILD_ANALYST)
    )


def get_department(dept_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_department(dept_id, headers or ANALYST))


def get_build_item(item_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_build_item(item_id, headers or ANALYST))


def get_interface_channel(channel_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_interface_channel(channel_id, headers or ANALYST))


def advance_epoch(prog_id: str) -> dict:
    return get_success_data(api_client.advance_epoch(prog_id, DIRECTOR))


def create_staff(prog_id: str, fac_id: str, dept_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_staff(
            prog_id, create_staff_payload(fac_id, dept_id, **overrides), TRAINING
        )
    )


def get_staff(staff_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_staff(staff_id, headers or TRAINING))


def create_ticket(fac_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_ticket(create_ticket_payload(fac_id, **overrides), COMMAND_CENTER)
    )


def create_shift(staff_id: str, fac_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_shift(
            create_staffing_shift_payload(staff_id, fac_id, **overrides), COMMAND_CENTER
        )
    )


def create_interface_channel(prog_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_interface_channel(
            prog_id, create_interface_channel_payload(**overrides), INTERFACE
        )
    )


def create_conversion_batch(fac_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_conversion_batch(
            fac_id, create_conversion_batch_payload(**overrides), CONVERSION
        )
    )


def create_patient_order(fac_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_patient_order(fac_id, create_patient_order_payload(**overrides), CONVERSION)
    )


def create_cutover_task(fac_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_cutover_task(fac_id, create_cutover_task_payload(**overrides), CUTOVER)
    )


# ===========================================================================
# Tier 1 — State progression
# ===========================================================================

def create_completed_build_item(dept_id: str, **overrides) -> dict:
    """Create a build item and walk it DRAFT -> IN_BUILD -> BUILD_COMPLETE."""
    item = get_success_data(
        api_client.create_build_item(dept_id, create_build_item_payload(**overrides), BUILD_ANALYST)
    )
    get_success_data(api_client.start_build_item(item["id"], BUILD_ANALYST))
    return get_success_data(api_client.complete_build_item(item["id"], BUILD_ANALYST))


def create_item_in_testing(dept_id: str, **overrides) -> dict:
    """Create a build item and walk it through to IN_TESTING."""
    item = create_completed_build_item(dept_id, **overrides)
    return get_success_data(api_client.start_testing(item["id"], TEST_LEAD))


def make_department_trainable(dept_id: str, application_code: str = "CLN",
                              **item_overrides) -> dict:
    """Give a department a completed build item, close its build, open training.

    Returns the department after begin-training, in TRAINING_IN_PROGRESS.
    """
    create_completed_build_item(
        dept_id, application_code=application_code, **item_overrides
    )
    get_success_data(api_client.complete_department_build(dept_id, BUILD_ANALYST))
    return get_success_data(api_client.begin_training(dept_id, TRAINING))


def setup_certified_trainer(prog_id: str, fac_id: str, dept_id: str,
                            application_code: str = "CLN",
                            certification_level: str = "STANDARD",
                            observation_hours: float = 8,
                            full_name: str = "Priya Raman"):
    """Register a staffer, start a trainer record and certify it.

    Returns (trainer_staff, certified_trainer_record).
    """
    staff = create_staff(prog_id, fac_id, dept_id, full_name=full_name)
    trainer = get_success_data(
        api_client.create_credentialed_trainer(
            staff["id"],
            create_credentialed_trainer_payload(
                staff["version"],
                application_code=application_code,
                certification_level=certification_level,
                observation_hours=observation_hours,
            ),
            TRAINING,
        )
    )
    certified = get_success_data(api_client.certify_trainer(trainer["id"], TRAINING))
    return staff, certified


def train_and_verify_staff(prog_id: str, fac_id: str, dept_id: str, trainer_id: str,
                           application_code: str = "CLN", curriculum_code: str = "CLN100",
                           required_hours: float = 40, hours: float = 40,
                           exam_score: float = 85, **staff_overrides) -> dict:
    """Register a staffer, complete a curriculum and pass a proctored exam.

    Returns the staff row, which is expected to read PROFICIENCY_VERIFIED.
    """
    staff = create_staff(prog_id, fac_id, dept_id, **staff_overrides)
    assignment = get_success_data(
        api_client.create_training_assignment(
            staff["id"],
            create_training_assignment_payload(
                curriculum_code=curriculum_code, application_code=application_code,
                required_hours=required_hours,
            ),
            TRAINING,
        )
    )
    get_success_data(api_client.log_hours(assignment["id"], {"hours": hours}, TRAINING))
    get_success_data(api_client.complete_assignment(assignment["id"], TRAINING))
    exam = get_success_data(
        api_client.schedule_exam(
            staff["id"],
            create_proficiency_exam_payload(trainer_id, application_code=application_code),
            TRAINING,
        )
    )
    get_success_data(
        api_client.record_exam_result(
            exam["id"], {"exam_score": exam_score}, make_credentialed_trainer_headers(trainer_id)
        )
    )
    return get_staff(staff["id"])


def verify_and_credential_staff(prog_id: str, fac_id: str, dept_id: str, trainer_id: str,
                                staff_type: str = "REGISTRATION", **kwargs) -> dict:
    """Train, verify and then issue the go-live credential.

    Defaults to a REGISTRATION staffer, which the credential precondition admits
    without a trainer record of its own.
    """
    staff = train_and_verify_staff(
        prog_id, fac_id, dept_id, trainer_id, staff_type=staff_type, **kwargs
    )
    return get_success_data(api_client.issue_credential(staff["id"], TRAINING))


# ===========================================================================
# Tier 2 — Entity hierarchy
# ===========================================================================

def setup_program():
    """Clock at its startup default plus one fresh program."""
    set_clock()
    return create_program()


def setup_program_and_facility(**fac_overrides):
    """Program + one registered facility. Returns (program, facility)."""
    prog = setup_program()
    fac = create_facility(prog["id"], **fac_overrides)
    return prog, fac


def setup_program_facility_department(**dept_overrides):
    """Program + facility + one department. Returns (program, facility, department)."""
    prog, fac = setup_program_and_facility()
    dept = create_department(fac["id"], **dept_overrides)
    return prog, fac, dept


def setup_configured_facility_with_department(**dept_overrides):
    """Program + facility configured for build + department. Returns (prog, fac, dept)."""
    prog, fac, dept = setup_program_facility_department(**dept_overrides)
    fac = get_success_data(api_client.configure_build(fac["id"], BUILD_ANALYST))
    return prog, fac, dept


# ===========================================================================
# Tier 3 — Full lifecycle shortcuts
# ===========================================================================

def setup_rejected_build_item_with_sev1_defect(defect_code: str = "LBL-9001",
                                               severity: str = "SEV1",
                                               **item_overrides) -> dict:
    """Drive one build item into BUILD_REJECTED with an open blocking defect.

    Program -> facility configured for build -> department BUILD_COMPLETE ->
    build item IN_TESTING -> scenario FAILED -> defect recorded. The department
    is left BUILD_REJECTED and the facility REMEDIATION_REQUIRED.
    """
    set_clock()
    prog = create_program()
    fac = create_facility(prog["id"])
    dept = create_department(fac["id"])
    item = get_success_data(
        api_client.create_build_item(dept["id"], create_build_item_payload(**item_overrides),
                                     BUILD_ANALYST)
    )
    scenario = get_success_data(
        api_client.create_test_scenario(item["id"], create_test_scenario_payload(), TEST_LEAD)
    )
    get_success_data(api_client.start_build_item(item["id"], BUILD_ANALYST))
    get_success_data(api_client.complete_build_item(item["id"], BUILD_ANALYST))
    get_success_data(api_client.start_testing(item["id"], TEST_LEAD))
    # PRD §3.3: "Closing the department's build requires that at least one of its
    # build items has reached BUILD_COMPLETE, IN_TESTING or
    # VALIDATION_COMPLETE". The close is issued while the item is IN_TESTING,
    # which is a state that declared precondition admits.
    get_success_data(api_client.complete_department_build(dept["id"], BUILD_ANALYST))
    get_success_data(api_client.configure_build(fac["id"], BUILD_ANALYST))
    get_success_data(
        api_client.execute_scenario(
            scenario["id"], {"outcome": "FAIL", "executed_epoch": 0}, TEST_LEAD
        )
    )
    defect = get_success_data(
        api_client.record_defect(
            scenario["id"],
            create_defect_payload(defect_code=defect_code, severity=severity),
            TEST_LEAD,
        )
    )
    return {
        "prog": prog,
        "fac": fac,
        "dept": dept,
        "item": item,
        "scenario": scenario,
        "defect": defect,
    }


def setup_failed_item_with_defect(severity: str = "SEV3", defect_code: str = "LBL-5001",
                                  **item_overrides) -> dict:
    """A build item in BUILD_REJECTED carrying one defect of the given severity."""
    return setup_rejected_build_item_with_sev1_defect(
        defect_code=defect_code, severity=severity, **item_overrides
    )


def setup_department_with_cleared_staff(application_code: str = "CLN",
                                        required_staff_count: int = 1,
                                        cleared_count: int = 1,
                                        exam_score: float = 90,
                                        department_code: str = "CLN",
                                        curriculum_code: str = "CLN100",
                                        required_hours: float = 40,
                                        close_gate: bool = False,
                                        configure_facility: bool = False) -> dict:
    """Build a facility whose departments are cleared to unlock facility validation.

    A companion department with a required_staff_count of 0 holds the certified
    proctor; its ratio is 100.00 and its gate is open without distorting the
    department under test. The department under test holds `cleared_count`
    proficiency-verified staffers out of `required_staff_count`.
    """
    set_clock()
    prog = create_program()
    fac = create_facility(prog["id"])
    trainer_dept = create_department(
        fac["id"], department_code=f"{department_code}-PROCTOR",
        application_scope=[application_code], required_staff_count=0,
    )
    trainer_staff, trainer = setup_certified_trainer(
        prog["id"], fac["id"], trainer_dept["id"], application_code=application_code,
        full_name="Priya Raman",
    )
    dept = create_department(
        fac["id"], department_code=department_code,
        application_scope=[application_code], required_staff_count=required_staff_count,
    )
    make_department_trainable(dept["id"], application_code=application_code)

    cleared = []
    for index in range(cleared_count):
        cleared.append(
            train_and_verify_staff(
                prog["id"], fac["id"], dept["id"], trainer["id"],
                application_code=application_code, curriculum_code=curriculum_code,
                required_hours=required_hours, exam_score=exam_score,
                full_name=f"Cleared {department_code} {index + 1}",
            )
        )

    if close_gate:
        get_success_data(api_client.close_proficiency_gate(dept["id"], TRAINING))
    if configure_facility:
        fac = get_success_data(api_client.configure_build(fac["id"], BUILD_ANALYST))

    return {
        "prog": prog,
        "fac": fac,
        "dept": get_department(dept["id"]),
        "trainer_dept": trainer_dept,
        "trainer_staff": trainer_staff,
        "trainer": trainer,
        "cleared": cleared,
    }


def setup_credentialed_staff(application_code: str = "CLN", **kwargs) -> dict:
    """A program, facility and department with one credentialed staffer.

    Defaults the staffer to REGISTRATION so the credential precondition is met
    without a trainer record of its own.
    """
    set_clock()
    prog = create_program()
    fac = create_facility(prog["id"])
    dept = create_department(
        fac["id"], department_code=application_code,
        application_scope=[application_code], required_staff_count=1,
    )
    make_department_trainable(dept["id"], application_code=application_code)
    trainer_staff, trainer = setup_certified_trainer(
        prog["id"], fac["id"], dept["id"], application_code=application_code
    )
    staff = verify_and_credential_staff(
        prog["id"], fac["id"], dept["id"], trainer["id"], application_code=application_code,
        **kwargs
    )
    return {
        "prog": prog,
        "fac": fac,
        "dept": dept,
        "trainer_staff": trainer_staff,
        "trainer": trainer,
        "staff": staff,
    }


def setup_interface_channel_in_validation(**channel_overrides) -> dict:
    """A program with one channel under message validation."""
    set_clock()
    prog = create_program()
    channel = create_interface_channel(prog["id"], **channel_overrides)
    get_success_data(api_client.begin_channel_build(channel["id"], INTERFACE))
    channel = get_success_data(api_client.begin_message_validation(channel["id"], INTERFACE))
    return {"prog": prog, "channel": channel}


def receive_and_validate_messages(channel_id: str, count: int,
                                  message_code: str = "DICOM_STOW", **payload_overrides) -> list:
    """Receive `count` messages and validate each one. Returns the message rows."""
    messages = []
    for _ in range(count):
        message = get_success_data(
            api_client.receive_message(
                channel_id,
                create_interface_message_payload(message_code=message_code, **payload_overrides),
                INTERFACE,
            )
        )
        messages.append(get_success_data(api_client.validate_message(message["id"], INTERFACE)))
    return messages


def setup_order_with_charge_submitted(fac_id: str, **order_overrides) -> dict:
    """An order reconciled, charged and submitted for claim."""
    order = create_patient_order(fac_id, **order_overrides)
    get_success_data(api_client.reconcile_order(order["id"], RECONCILER))
    get_success_data(api_client.post_charge(order["id"], REVENUE))
    get_success_data(api_client.submit_claim(order["id"], REVENUE))
    return get_success_data(api_client.get_patient_order(order["id"], ANALYST))


def setup_facility_with_cutover_plan(plan: list = None, **fac_overrides) -> dict:
    """A program, facility and a cutover plan built from a list of task payloads."""
    set_clock()
    prog = create_program()
    fac = create_facility(prog["id"], **fac_overrides)
    tasks = []
    for entry in (plan or []):
        tasks.append(create_cutover_task(fac["id"], **entry))
    return {"prog": prog, "fac": fac, "tasks": tasks}


# ===========================================================================
# Tier 4 — Accumulation / threshold targeting
# ===========================================================================

def setup_epoch_scoped_build_item(application_code: str = "LAB",
                                  scenario_class: str = "UNIT") -> dict:
    """A build item in IN_TESTING with one freshly defined scenario at epoch 0."""
    prog, fac, dept = setup_program_facility_department(
        department_code=application_code, application_scope=[application_code]
    )
    item = create_item_in_testing(dept["id"], application_code=application_code)
    scenario = get_success_data(
        api_client.create_test_scenario(
            item["id"], create_test_scenario_payload(scenario_class=scenario_class), TEST_LEAD
        )
    )
    return {"prog": prog, "fac": fac, "dept": dept, "item": item, "scenario": scenario}


def setup_program_at_epoch(epoch_index: int) -> dict:
    """A program advanced to a given epoch with one facility and department."""
    set_clock()
    prog = create_program()
    fac = create_facility(prog["id"])
    dept = create_department(fac["id"])
    for _ in range(epoch_index):
        prog = advance_epoch(prog["id"])
    return {"prog": prog, "fac": fac, "dept": dept}


# ===========================================================================
# Tier 5 — Finalization / terminal state
# ===========================================================================

def setup_reconciled_batches_for_facility(fac_id: str, count: int,
                                          payload_class: str = "ORDERS",
                                          source_count: int = 500) -> list:
    """Stage, validate, load and reconcile `count` zero-variance batches."""
    batches = []
    for _ in range(count):
        facility = get_facility(fac_id)
        batch = create_conversion_batch(
            fac_id, payload_class=payload_class, attempt_epoch=0,
            source_count=source_count, reconciled_count=source_count,
            expected_facility_version=facility["version"],
        )
        get_success_data(api_client.begin_batch_validation(batch["id"], CONVERSION))
        get_success_data(api_client.load_batch(batch["id"], CONVERSION))
        batches.append(get_success_data(api_client.reconcile_batch(batch["id"], CONVERSION)))
    return batches


def create_optimization_item(dept_id: str, prog_id: str, **overrides) -> dict:
    """Raise an optimization item using the program's current version."""
    program = get_program(prog_id)
    return get_success_data(
        api_client.create_optimization_item(
            create_optimization_item_payload(
                dept_id, program["version"], **overrides
            ),
            OPTIMIZATION,
        )
    )