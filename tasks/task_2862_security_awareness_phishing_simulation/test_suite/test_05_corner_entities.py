"""Entity-surface claims: creation, retrieval, listing, defaults and immutability.

Every test in this module translates exactly one non-stub instance of the
`entities` section of the §1.9 breadth index.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    COMPLIANCE_COMPLIANT,
    DELIVERY_CLICKED,
    EMPLOYMENT_ACTIVE,
    MODULE_DRAFT,
    POSTURE_NONE,
    TENURE_EARLY,
    TENURE_NEW_HIRE,
    TENURE_VETERAN,
    TIER_1,
    UNKNOWN_EMPLOYEE_UUID,
    UNKNOWN_MODULE_UUID,
)
from test_helpers.assertions import (
    assert_append_only_shape,
    assert_delivery,
    assert_employee_axes,
    assert_instant_equals,
    assert_instant_is_none,
    assert_ledgers,
    assert_no_prefix_uuid,
    assert_risk_scores,
    assert_utc_millisecond_format,
    assert_version_is,
    assert_versioned_shape,
    ids_of,
)
from test_helpers.factories import employee_payload, incident_payload, module_payload
from test_helpers.fixtures import (
    create_module,
    delivered_simulation,
    read_employee,
    register_employee,
    reset_clock,
    set_clock,
)
from test_helpers.test_users import ADMIN, ANALYST


def test_employee_creation_returns_every_declared_field(api):
    """The 201 body carries the three axes, both ledgers and both risk variants.

    PRD §3.1: "A newly registered employee starts with `employment_status` of
    `ACTIVE`, `compliance_state` of `COMPLIANT`, `access_posture` of `NONE`,
    `active_suspension_count` of 0, `repeat_clicker_tier` of 0,
    `consecutive_clean_simulations` of 0, `reserved_simulation_slots` of 0, and
    both `risk_score_provisional` and `risk_score_settled` at 0.00."

    Design: Corner/entities/employee_creation_returns_201_with_every_declared_field
    """
    reset_clock(api)
    created = validate_success(
        api.create_employee(
            employee_payload(
                email="ada.new@corp.example", full_name="Ada New",
                department="ENGINEERING", role_code="ENGINEER",
                hire_date="2020-04-01",
            ),
            ADMIN,
        ),
        expected_status=201,
    )

    assert created["email"] == "ada.new@corp.example"
    assert created["full_name"] == "Ada New"
    assert created["department"] == "ENGINEERING"
    assert created["role_code"] == "ENGINEER"
    assert created["hire_date"] == "2020-04-01"
    assert_employee_axes(created, employment_status=EMPLOYMENT_ACTIVE,
                         compliance_state=COMPLIANCE_COMPLIANT,
                         access_posture=POSTURE_NONE)
    assert created["repeat_clicker_tier"] == 0
    assert created["consecutive_clean_simulations"] == 0
    assert_ledgers(created, reserved_simulation_slots=0, active_suspension_count=0)
    assert_risk_scores(created, provisional=0.00, settled=0.00)
    assert_versioned_shape(created, "employee")
    assert_version_is(created, 1, "employee")
    assert_no_prefix_uuid(created["id"], "employee.id")
    assert_utc_millisecond_format(created["created_at"], "created_at")


def test_employee_retrieval_echoes_the_stored_row_without_bumping_version(api):
    """The read surfaces the derived tenure band and leaves `version` alone.

    PRD §3.1: "Reading a single employee surfaces both risk-score variants and all
    three axes, and refreshes `tenure_band`, `repeat_clicker_tier`,
    `consecutive_clean_simulations`, `risk_score_provisional` and
    `risk_score_settled` without bumping `version`."

    Design: Corner/entities/employee_retrieval_returns_the_stored_row
    """
    reset_clock(api)
    created = register_employee(
        api, email="rea.read@corp.example", full_name="Rea Read",
        department="HR", role_code="IC", hire_date="2026-07-25",
    )

    fetched = validate_success(api.get_employee(created["id"], ADMIN))
    assert fetched["id"] == created["id"]
    assert fetched["tenure_band"] == TENURE_NEW_HIRE
    assert fetched["version"] == created["version"]
    assert fetched["full_name"] == "Rea Read"
    assert fetched["department"] == "HR"


def test_employee_listing_filters_by_manager_id(api):
    """The manager filter is the reverse-lookup channel for the self-reference.

    PRD §3.1: "Listing employees is the reverse-lookup channel for the
    self-referential manager link and accepts filters on `manager_id`,
    `department`, `compliance_state`, `access_posture` and `employment_status`,
    alongside `limit` and `offset`."

    Design: Corner/entities/employee_listing_filters_by_manager_id
    """
    reset_clock(api)
    manager = register_employee(
        api, full_name="Lila Lead", department="SALES",
        role_code="MANAGER", hire_date="2014-01-01",
    )
    first = register_employee(
        api, full_name="Rep One", department="SALES", role_code="IC",
        hire_date="2019-01-01", manager_id=manager["id"],
    )
    second = register_employee(
        api, full_name="Rep Two", department="SALES", role_code="IC",
        hire_date="2019-02-01", manager_id=manager["id"],
    )
    unrelated = register_employee(
        api, full_name="Otto Other", department="IT", role_code="IT_ADMIN",
        hire_date="2019-03-01",
    )

    rows = validate_success(api.list_employees({"manager_id": manager["id"]}, ADMIN))
    returned = ids_of(rows)
    assert sorted(returned) == sorted([first["id"], second["id"]])
    assert manager["id"] not in returned
    assert unrelated["id"] not in returned
    for row in rows:
        assert row["manager_id"] == manager["id"]


def test_employee_get_unknown_id_returns_the_employee_flavoured_404(api):
    """An unregistered but well-formed id is a family-specific 404.

    PRD §2.8: "Each resource family has its own not-found identifier:
    `ERR_EMPLOYEE_NOT_FOUND`, `ERR_MODULE_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
    `ERR_CAMPAIGN_NOT_FOUND`, `ERR_TEMPLATE_NOT_FOUND` and
    `ERR_DELIVERY_NOT_FOUND` cover employees, training modules, curriculum
    assignments, campaigns, phishing templates and simulation deliveries
    respectively, all at HTTP 404."

    Design: Corner/entities/employee_get_unknown_id_returns_404_employee_not_found
    """
    reset_clock(api)
    existing = register_employee(
        api, full_name="Ona Only", department="IT",
        role_code="IT_ADMIN", hire_date="2018-01-01",
    )

    validate_error(
        api.get_employee(UNKNOWN_EMPLOYEE_UUID, ADMIN),
        ApiErrorId.EMPLOYEE_NOT_FOUND.value,
        expected_status=404,
    )

    still_there = validate_success(api.get_employee(existing["id"], ADMIN))
    assert still_there["id"] == existing["id"]


def test_create_employee_without_department_is_a_request_shape_failure(api):
    """A missing required input fails the well-formedness check before any write.

    PRD §3.1: "Registering someone into the awareness program requires a work
    `email`, a `full_name`, an organizational `department`, a job `role_code`, and
    a calendar `hire_date`"

    PRD §2.8: "Request well-formedness (`ERR_INVALID_REQUEST`): required body
    fields present, enum members recognised"

    Design: Corner/entities/create_employee_missing_required_department_returns_400_invalid_request
    """
    reset_clock(api)

    validate_error(
        api.create_employee(
            {"email": "nod@corp.example", "full_name": "No Dept",
             "role_code": "IC", "hire_date": "2019-01-01"},
            ADMIN,
        ),
        ApiErrorId.INVALID_REQUEST.value,
        expected_status=400,
    )

    assert validate_success(api.list_employees({}, ADMIN)) == []


def test_training_module_materialises_every_declared_default(api):
    """Only the three required inputs still produce all five optional defaults.

    PRD §3.2: "`passing_score_pct` defaults to 80 and is the inclusive minimum
    score that turns a submitted attempt into a completion. `reminder_offsets_days`
    defaults to the ordered list 7, 3, 1 and −2, and each entry positions one
    reminder relative to the effective deadline, so the negative entry is a
    reminder that fires two days *after* the deadline has passed.
    `escalate_after_reminders` defaults to 3 and is recorded on the module as
    informational cadence guidance for program owners"

    Design: Corner/entities/training_module_defaults_applied_when_optional_inputs_omitted
    """
    reset_clock(api)
    created = validate_success(
        api.create_module(
            module_payload(code="DEFAULTS-1", title="Defaults Probe",
                           module_type="ANNUAL"),
            ADMIN,
        ),
        expected_status=201,
    )

    fetched = validate_success(api.get_module(created["id"], ADMIN))
    assert fetched["passing_score_pct"] == 80
    assert fetched["reminder_offsets_days"] == [7, 3, 1, -2]
    assert fetched["escalate_after_reminders"] == 3
    assert fetched["max_extension_days"] == 10
    assert fetched["applies_to_role_codes"] == []
    assert fetched["criticality"] == "STANDARD"
    assert fetched["status"] == MODULE_DRAFT
    assert_instant_is_none(fetched["published_at"], "published_at")
    assert_instant_is_none(fetched["retired_at"], "retired_at")


def test_tenure_band_is_computed_from_hire_date_not_from_the_payload(api):
    """A client-supplied band is ignored; the clock and hire_date decide.

    PRD §3.1: "Fewer than 90 such days makes the `tenure_band` `NEW_HIRE`; from 90
    up to but not including 365 days it is `EARLY`; from 365 up to but not
    including 1,095 days — that is, up to but not including the third anniversary
    — it is `ESTABLISHED`; and 1,095 days or more makes it `VETERAN`."

    Design: Corner/entities/employee_tenure_band_computed_from_hire_date_client_input_ignored
    """
    reset_clock(api)
    ramping = validate_success(
        api.create_employee(
            employee_payload(
                email="ramp@corp.example", full_name="Ray Ramp",
                department="ENGINEERING", role_code="ENGINEER",
                hire_date="2026-05-01", tenure_band=TENURE_VETERAN,
            ),
            ADMIN,
        ),
        expected_status=201,
    )
    assert ramping["tenure_band"] == TENURE_EARLY, "92 days of tenure is the middle band"
    assert ramping["hire_date"] == "2026-05-01"

    fresh = register_employee(
        api, full_name="Nina New", department="HR", role_code="IC",
        hire_date="2026-07-25",
    )
    assert fresh["tenure_band"] == TENURE_NEW_HIRE

    veteran = register_employee(
        api, full_name="Vera Vet", department="IT", role_code="IT_ADMIN",
        hire_date="2018-01-01",
    )
    assert veteran["tenure_band"] == TENURE_VETERAN


def test_incident_system_fields_are_server_minted_and_phish_flag_is_derived(api):
    """A client-supplied id and phish_related are both ignored.

    PRD §2.4: "Every persisted resource carries a server-minted `id` formatted as
    a UUID with no type prefix, and a `created_at` timestamp recorded as an ISO
    8601 UTC instant with three fractional digits."

    PRD §3.10: "The computed `phish_related` flag is true exactly when the
    `incident_type` is `CREDENTIAL_PHISH` or `BEC`; malware-delivery and data-loss
    incidents are excluded from the correlation series entirely."

    Design: Corner/entities/incident_record_system_fields_generated_by_server_input_ignored
    """
    reset_clock(api)
    created = validate_success(
        api.create_incident(
            incident_payload(
                incident_type="CREDENTIAL_PHISH", severity="HIGH",
                department="FINANCE", occurred_at="2026-07-30T12:00:00Z",
                summary="Finance clerk entered credentials on a lookalike portal.",
                id="11111111-1111-4111-8111-111111111111", phish_related=False,
            ),
            ANALYST,
        ),
        expected_status=201,
    )

    assert created["id"] != "11111111-1111-4111-8111-111111111111"
    assert_no_prefix_uuid(created["id"], "incident.id")
    assert created["phish_related"] is True
    assert_instant_equals(created["created_at"], "2026-08-01T00:00:00Z", "created_at")
    assert_instant_equals(created["occurred_at"], "2026-07-30T12:00:00Z", "occurred_at")
    assert created["severity"] == "HIGH"
    assert created["department"] == "FINANCE"


def test_incident_severity_outside_the_enum_is_rejected(api):
    """An unrecognised enum member is a 400, never a silently coerced value.

    PRD §3.10: "A `SecurityAnalyst` records real security incidents, supplying an
    `incident_type` from `CREDENTIAL_PHISH`, `BEC`, `MALWARE_DELIVERY` and
    `DATA_LOSS`, a `severity` from `LOW`, `MEDIUM`, `HIGH` and `CRITICAL`"

    Design: Corner/entities/create_incident_invalid_severity_enum_rejected
    """
    reset_clock(api)

    validate_error(
        api.create_incident(
            incident_payload(
                incident_type="BEC", severity="SEVERE", department="SALES",
                occurred_at="2026-07-30T12:00:00Z",
                summary="Invalid severity probe.",
            ),
            ANALYST,
        ),
        ApiErrorId.INVALID_REQUEST.value,
        expected_status=400,
    )
    assert validate_success(api.list_incidents({}, ANALYST)) == []

    accepted = validate_success(
        api.create_incident(
            incident_payload(
                incident_type="BEC", severity="CRITICAL", department="SALES",
                occurred_at="2026-07-30T12:00:00Z",
                summary="Invalid severity probe.",
            ),
            ANALYST,
        ),
        expected_status=201,
    )
    assert accepted["severity"] == "CRITICAL"
    assert accepted["phish_related"] is True


def test_incident_records_carry_no_version_and_no_updated_at(api):
    """The audit trail is append-only, so the common-field block is the short one.

    PRD §2.4: "Three record types are deliberately append-only and therefore carry
    neither `updated_at` nor `version`: `InteractionEvent`, `IncidentRecord`, and
    `CommunicationWindow`. Each of these exposes only `id` and `created_at` among
    the common properties, and none of them has an update endpoint."

    Design: Corner/entities/incident_record_immutability_no_version_field
    """
    reset_clock(api)
    created = validate_success(
        api.create_incident(
            incident_payload(
                incident_type="MALWARE_DELIVERY", severity="MEDIUM",
                department="IT", occurred_at="2026-07-28T08:00:00Z",
                summary="Macro-enabled attachment blocked at the gateway.",
            ),
            ANALYST,
        ),
        expected_status=201,
    )

    fetched = validate_success(api.get_incident(created["id"], ANALYST))
    assert_append_only_shape(fetched, "incident")
    assert fetched["phish_related"] is False


def test_interaction_events_are_append_only_with_a_one_based_sequence(api):
    """Two appends produce two immutable rows numbered 1 and 2 in that order.

    PRD §3.9: "The resulting `InteractionEvent` records a `delivery_id` pointing at
    the delivery it belongs to, a `sequence_index` assigned as one more than the
    number of events already on that delivery so that the first event is index 1"

    Design: Corner/entities/interaction_event_immutability_append_only_sequence
    """
    reset_clock(api)
    employee = register_employee(
        api, full_name="Eli Event", department="IT",
        role_code="IT_ADMIN", hire_date="2017-05-05",
    )
    ctx = delivered_simulation(
        api, employee=employee, difficulty_tier=TIER_1,
        scheduled_send_at="2026-08-02T09:00:00Z", name="IT Event Wave",
    )
    delivery = ctx["delivery"]

    set_clock(api, "2026-08-02T09:10:00Z")
    opened = validate_success(
        api.append_interaction(
            delivery["id"],
            {"event_type": "OPEN", "occurred_at": "2026-08-02T09:05:00Z",
             "source": "MAIL_GATEWAY"},
            ADMIN,
        ),
        expected_status=201,
    )
    clicked = validate_success(
        api.append_interaction(
            delivery["id"],
            {"event_type": "CLICK", "occurred_at": "2026-08-02T09:10:00Z",
             "source": "LANDING_PAGE"},
            ADMIN,
        ),
        expected_status=201,
    )
    assert opened["sequence_index"] == 1
    assert clicked["sequence_index"] == 2
    assert_append_only_shape(opened, "interaction event")
    assert_append_only_shape(clicked, "interaction event")

    rows = validate_success(api.list_interaction_events(delivery["id"], {}, ANALYST))
    assert len(rows) == 2
    assert [row["sequence_index"] for row in rows] == [1, 2]
    assert rows[0]["event_type"] == "OPEN"
    assert rows[1]["event_type"] == "CLICK"

    after = validate_success(api.get_delivery(delivery["id"], ADMIN))
    assert_delivery(after, state=DELIVERY_CLICKED)
    assert_instant_equals(after["first_click_at"], "2026-08-02T09:10:00Z",
                          "first_click_at")


def test_assignment_rejects_an_unknown_employee_reference(api):
    """A body foreign key resolves with the employee family's own 404.

    PRD §2.8: "Foreign keys supplied in a request body are resolved with the same
    family-specific identifiers: an unknown `employee_id`, `manager_id` or
    `root_cause_employee_id` yields `ERR_EMPLOYEE_NOT_FOUND`, an unknown
    `module_id` yields `ERR_MODULE_NOT_FOUND`, and an unknown `template_id` yields
    `ERR_TEMPLATE_NOT_FOUND`."

    Design: Corner/entities/assignment_foreign_key_employee_must_exist_returns_404
    """
    reset_clock(api)
    employee = register_employee(
        api, full_name="Fay Kay", department="HR", role_code="IC",
        hire_date="2019-01-01",
    )
    module = create_module(api, code="FK-ANNUAL", title="FK Probe Module",
                           module_type="ANNUAL")
    validate_success(api.publish_module(module["id"], ADMIN))

    validate_error(
        api.create_assignment(
            {"employee_id": UNKNOWN_EMPLOYEE_UUID, "module_id": module["id"],
             "assignment_reason": "ANNUAL",
             "expected_employee_version": employee["version"]},
            ADMIN,
        ),
        ApiErrorId.EMPLOYEE_NOT_FOUND.value,
        expected_status=404,
    )
    assert validate_success(api.list_assignments({}, ADMIN)) == []
    assert read_employee(api, employee["id"])["version"] == employee["version"]

    created = validate_success(
        api.create_assignment(
            {"employee_id": employee["id"], "module_id": module["id"],
             "assignment_reason": "ANNUAL",
             "expected_employee_version": employee["version"]},
            ADMIN,
        ),
        expected_status=201,
    )
    assert created["employee_id"] == employee["id"]


def test_assignment_rejects_an_unknown_module_reference_with_its_own_code(api):
    """The second foreign key on the same write reports the module-flavoured 404.

    PRD §2.8: "an unknown `module_id` yields `ERR_MODULE_NOT_FOUND`"

    Design: Corner/entities/assignment_foreign_key_module_must_exist_returns_404
    """
    reset_clock(api)
    employee = register_employee(
        api, full_name="Moe Kay", department="HR", role_code="IC",
        hire_date="2019-02-02",
    )

    error = validate_error(
        api.create_assignment(
            {"employee_id": employee["id"], "module_id": UNKNOWN_MODULE_UUID,
             "assignment_reason": "ANNUAL",
             "expected_employee_version": employee["version"]},
            ADMIN,
        ),
        ApiErrorId.MODULE_NOT_FOUND.value,
        expected_status=404,
    )
    assert error["error_id"] != ApiErrorId.EMPLOYEE_NOT_FOUND.value
    assert read_employee(api, employee["id"])["version"] == employee["version"]
    assert validate_success(api.list_assignments({}, ADMIN)) == []
