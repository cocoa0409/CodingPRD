"""Breadth tests for the `entities` section of the corner design index.

Covers the create-side entity contracts: the declared defaults a freshly
registered `Patient` and `Drug` are born with, the system-owned `InfusionChair`
status, the server-derived `TherapyEpisode` routing and floor fields, and the
payload-shape rejections that guard `Visit` and `ScreeningRecord` intake.

Design sections covered: Corner/entities.
"""
from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import assertions, factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import CLOCK_DEFAULT, instant


# ---------------------------------------------------------------------------
# Patient creation defaults
# ---------------------------------------------------------------------------
def test_patient_creation_returns_envelope_and_all_declared_defaults(
    api, registry_admin_headers
):
    """A freshly registered patient carries every derived field at its floor.

    PRD §3.1: "A patient is born with every derived field at its floor:
    `tb_screen_status` is `MISSING`, `hbv_screen_status` is `INCOMPLETE`,
    `target_status` is `UNASSESSED`, `latest_activity_score` and
    `latest_activity_category` are both null, `administered_dose_total` is 0,
    `active_episode_count` is 0 and `version` is 1."

    Design: Corner/entities/patient_creation_returns_envelope_and_all_declared_defaults
    """
    fixtures.set_clock(CLOCK_DEFAULT, registry_admin_headers)

    payload = factories.create_patient_payload(
        mrn="RH0001",
        full_name="Pat One",
        date_of_birth="1975-04-12",
        diagnosis_code="RA_SEROPOSITIVE",
        registry_consent=True,
    )
    response = api.create_patient(payload, registry_admin_headers)
    data = validate_success(response, 201)

    body = response.json()
    assert body["response_type"] == "object", "a single resource reports response_type object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert body["meta"]["api_request_timestamp"]

    assertions.assert_patient(data)
    assert data["mrn"] == "RH0001"
    assert data["full_name"] == "Pat One"
    assert data["date_of_birth"] == "1975-04-12"
    assert data["diagnosis_code"] == "RA_SEROPOSITIVE"
    assert data["registry_consent"] is True

    assert data["tb_screen_status"] == "MISSING"
    assert data["hbv_screen_status"] == "INCOMPLETE"
    assert data["target_status"] == "UNASSESSED"
    assert data["latest_activity_score"] is None
    assert data["latest_activity_category"] is None
    assert data["administered_dose_total"] == 0
    assert data["active_episode_count"] == 0
    assert data["version"] == 1

    assertions.assert_three_fraction_digit_instant(data["created_at"], "created_at")
    assertions.assert_instant_equals(data["created_at"], CLOCK_DEFAULT, "created_at")


# ---------------------------------------------------------------------------
# Drug optional-flag defaults
# ---------------------------------------------------------------------------
def test_drug_screening_flags_default_to_true_when_omitted(api, registry_admin_headers):
    """Omitting both screening booleans demands the screens rather than waiving them.

    PRD §3.1: "Two optional booleans, `tb_screen_required` and
    `hbv_screen_required`, both default to **true** when omitted — the safe
    default is to demand the screen."

    Design: Corner/entities/drug_optional_flags_take_declared_defaults_when_omitted
    """
    fixtures.set_clock(CLOCK_DEFAULT, registry_admin_headers)

    payload = factories.infliximab_payload()
    assert "tb_screen_required" not in payload
    assert "hbv_screen_required" not in payload

    data = validate_success(api.create_drug(payload, registry_admin_headers), 201)

    assertions.assert_drug(data)
    assert data["tb_screen_required"] is True
    assert data["hbv_screen_required"] is True


def test_drug_biosimilar_and_step_therapy_default_when_omitted(api, registry_admin_headers):
    """The informational flag and the step-therapy array take their declared floors.

    PRD §3.1: "The optional flag `is_biosimilar` defaults to false and is
    purely informational, feeding only the registry's biosimilar-uptake
    metric."

    Design: Corner/entities/drug_optional_flags_take_declared_defaults_when_omitted
    """
    fixtures.set_clock(CLOCK_DEFAULT, registry_admin_headers)

    payload = factories.infliximab_payload()
    assert "is_biosimilar" not in payload
    assert "step_therapy_required_classes" not in payload

    data = validate_success(api.create_drug(payload, registry_admin_headers), 201)

    assert data["is_biosimilar"] is False
    assert data["step_therapy_required_classes"] == []


# ---------------------------------------------------------------------------
# Infusion chair status is system owned
# ---------------------------------------------------------------------------
def test_new_infusion_chair_is_open_with_version_one(api, registry_admin_headers):
    """`status` is never a create input: a brand-new chair opens by itself.

    PRD §3.1: "A new chair's `status` is `OPEN`."

    Design: Corner/entities/infusion_chair_status_is_system_owned_and_defaults_to_open
    """
    fixtures.set_clock(CLOCK_DEFAULT, registry_admin_headers)

    payload = factories.create_infusion_chair_payload(
        label="AIC-1", site_type="AMBULATORY_INFUSION_CENTER", turnover_buffer_minutes=30
    )
    assert "status" not in payload, "status is absent from the chair's input schema"

    data = validate_success(api.create_infusion_chair(payload, registry_admin_headers), 201)

    assertions.assert_infusion_chair(data)
    assert data["status"] == "OPEN"
    assert data["version"] == 1
    assert data["id"]
    assertions.assert_instant_equals(data["created_at"], CLOCK_DEFAULT, "created_at")


def test_chair_status_changes_only_through_patch_and_bumps_version(api, registry_admin_headers):
    """The one mutable chair field moves by PATCH, and the move costs a revision.

    PRD §3.1: "That status is mutable, and it is the only field of a chair that
    is: a `RegistryAdmin` may set it to `CLOSED` or back to `OPEN`, which
    increments the chair's `version` by one."

    Design: Corner/entities/infusion_chair_status_is_system_owned_and_defaults_to_open
    """
    fixtures.set_clock(CLOCK_DEFAULT, registry_admin_headers)

    created = validate_success(
        api.create_infusion_chair(
            factories.create_infusion_chair_payload(label="AIC-1"), registry_admin_headers
        ),
        201,
    )
    chair_version = created["version"]

    closed = validate_success(
        api.update_infusion_chair(
            created["id"], factories.update_infusion_chair_payload("CLOSED"), registry_admin_headers
        ),
        200,
    )
    assert closed["status"] == "CLOSED"
    assert closed["version"] == chair_version + 1

    reopened = validate_success(
        api.update_infusion_chair(
            created["id"], factories.update_infusion_chair_payload("OPEN"), registry_admin_headers
        ),
        200,
    )
    assert reopened["status"] == "OPEN"
    assert reopened["version"] == chair_version + 2


# ---------------------------------------------------------------------------
# Therapy episode: every routing and floor field is server-derived
# ---------------------------------------------------------------------------
def test_episode_routing_fields_are_derived_not_accepted_as_input(api, practice):
    """An IV product on a medical-enabled PREFER_AMBULATORY plan routes itself.

    PRD §3.4: "Episode creation sets `routing_frozen` to true, and from that
    moment `benefit_channel` and `site_of_care` are pinned for the episode's
    whole lifetime; no later operation recomputes them, and activation does not
    disturb the flag."

    Design: Corner/entities/therapy_episode_computed_fields_are_derived_not_accepted_as_input
    """
    fixtures.set_clock(CLOCK_DEFAULT, practice.admin_headers)

    assert practice.drug["route"] == "IV"
    assert practice.plan["medical_benefit_enabled"] is True
    assert practice.plan["site_of_care_policy"] == "PREFER_AMBULATORY"

    payload = factories.create_therapy_episode_payload(
        practice.patient_id,
        practice.drug_id,
        practice.plan_id,
        practice.patient_version,
        therapy_start_at=CLOCK_DEFAULT,
    )
    # The input schema admits nothing but these five fields plus the optional
    # prior_episode_id, so every routing field below is the server's own work.
    assert set(payload) == {
        "patient_id",
        "drug_id",
        "payer_plan_id",
        "therapy_start_at",
        "expected_patient_version",
    }

    data = validate_success(api.create_therapy_episode(payload, practice.rheum_headers), 201)

    assertions.assert_therapy_episode(data)
    assert data["benefit_channel"] == "MEDICAL"
    assert data["site_of_care"] == "AMBULATORY_INFUSION_CENTER"
    assert data["routing_frozen"] is True
    assert data["self_injection_training_status"] == "NOT_REQUIRED"
    assert data["self_injection_training_attempts"] == 0


def test_episode_state_and_counter_floors_are_derived_not_accepted_as_input(api, practice):
    """Line of therapy, both state axes, the counters and monitoring all settle themselves.

    PRD §3.4: "A new episode's other fields settle as follows. `therapy_state`
    is `PLANNED` and `funding_state` is `UNFUNDED`."

    Design: Corner/entities/therapy_episode_computed_fields_are_derived_not_accepted_as_input
    """
    fixtures.set_clock(CLOCK_DEFAULT, practice.admin_headers)

    payload = factories.create_therapy_episode_payload(
        practice.patient_id,
        practice.drug_id,
        practice.plan_id,
        practice.patient_version,
        therapy_start_at=CLOCK_DEFAULT,
    )
    data = validate_success(api.create_therapy_episode(payload, practice.rheum_headers), 201)

    assert data["line_of_therapy"] == 1
    assert data["prior_episode_id"] is None
    assert data["therapy_state"] == "PLANNED"
    assert data["funding_state"] == "UNFUNDED"
    assert data["hold_count"] == 0
    assert data["doses_administered"] == 0
    # No matching CMP panel is on file yet, so the brand-new episode is overdue.
    assert data["monitoring_status"] == "OVERDUE"


# ---------------------------------------------------------------------------
# Visit intake: required-field shape violation
# ---------------------------------------------------------------------------
def test_visit_missing_required_visit_datetime_returns_invalid_request(api, practice):
    """Both references resolve, but the missing instant is still a shape violation.

    PRD §3.2: "A visit is booked by a `RegistryAdmin` or by a
    `Rheumatologist`, and its payload names `patient_id`, `clinician_id`,
    `visit_datetime` as an ISO 8601 UTC instant with three fractional digits,
    and `visit_type`, which is `NEW`, `FOLLOW_UP` or `URGENT`."

    Design: Corner/entities/visit_missing_required_visit_datetime_returns_invalid_request
    """
    fixtures.set_clock(CLOCK_DEFAULT, practice.admin_headers)

    payload = factories.create_visit_payload(
        practice.patient_id, practice.rheumatologist_id, visit_type="FOLLOW_UP"
    )
    payload.pop("visit_datetime")

    validate_error(
        api.create_visit(payload, practice.rheum_headers),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )

    rows, meta = assertions.validate_list(
        api.list_visits(practice.admin_headers, params={"patient_id": practice.patient_id})
    )
    assert meta["total_count"] == 0, "the rejected booking must persist no Visit row"
    assert rows == []


# ---------------------------------------------------------------------------
# Screening record intake: enum and ordering shape violations
# ---------------------------------------------------------------------------
def test_screening_record_invalid_enum_screen_type_rejected(api, practice):
    """A screen type outside the declared six-member set is a payload violation.

    PRD §2.10: "`ERR_INVALID_REQUEST` — payload shape. Every required field
    present, every value of its declared JSON type, every enum value drawn from
    its declared member set, every number inside its declared range and decimal
    width, every timestamp parseable as an ISO 8601 UTC instant, `limit` within
    1 to 100 inclusive, `offset` not negative, and — for a screening record —
    `collected_at` no later than `resulted_at`."

    Design: Corner/entities/screening_record_invalid_enum_screen_type_rejected
    """
    fixtures.set_clock(CLOCK_DEFAULT, practice.admin_headers)

    payload = factories.create_screening_record_payload(
        practice.patient_id,
        "QUANTIFERON_GOLD",
        "NEGATIVE",
        collected_at=instant(2026, 7, 20),
        resulted_at=instant(2026, 7, 21),
    )
    validate_error(
        api.create_screening_record(payload, practice.nurse_headers),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )

    rows, meta = assertions.validate_list(
        api.list_patient_screening_records(practice.patient_id, practice.nurse_headers)
    )
    assert meta["total_count"] == 0
    assert rows == []
    assert (
        validate_success(api.get_patient(practice.patient_id, practice.admin_headers))[
            "tb_screen_status"
        ]
        == "MISSING"
    )


def test_screening_record_collected_after_resulted_rejected(api, practice):
    """A specimen cannot be drawn after its own result was released.

    PRD §3.3: "A mismatched pairing, like a `TB_IGRA` row claiming `COMPLETED`,
    is a payload violation and is refused with `ERR_INVALID_REQUEST` (HTTP
    422), as is a record whose `collected_at` is later than its `resulted_at`."

    Design: Corner/entities/screening_record_invalid_enum_screen_type_rejected
    """
    fixtures.set_clock(CLOCK_DEFAULT, practice.admin_headers)

    payload = factories.create_screening_record_payload(
        practice.patient_id,
        "TB_IGRA",
        "NEGATIVE",
        collected_at=instant(2026, 7, 22),
        resulted_at=instant(2026, 7, 21),
    )
    validate_error(
        api.create_screening_record(payload, practice.nurse_headers),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )

    _rows, meta = assertions.validate_list(
        api.list_patient_screening_records(practice.patient_id, practice.nurse_headers)
    )
    assert meta["total_count"] == 0
    assert (
        validate_success(api.get_patient(practice.patient_id, practice.admin_headers))[
            "tb_screen_status"
        ]
        == "MISSING"
    )


# ---------------------------------------------------------------------------
# Screening record immutability
# ---------------------------------------------------------------------------
def test_screening_record_carries_no_version_field(api, practice):
    """The append-only clinical document exposes only `id` and `created_at`.

    PRD §2.4: "`ScreeningRecord` and `MonitoringLab` carry only `id` and
    `created_at`: both `updated_at` and `version` are absent from them
    entirely."

    Design: Corner/entities/screening_record_is_immutable_and_carries_no_version_field
    """
    fixtures.set_clock(CLOCK_DEFAULT, practice.admin_headers)

    payload = factories.create_screening_record_payload(
        practice.patient_id,
        "TB_IGRA",
        "POSITIVE",
        collected_at=instant(2026, 7, 1),
        resulted_at=instant(2026, 7, 2),
    )
    created = validate_success(api.create_screening_record(payload, practice.nurse_headers), 201)

    assertions.assert_screening_record(created)
    assert "version" not in created
    assert "updated_at" not in created

    rows, _meta = assertions.validate_list(
        api.list_patient_screening_records(practice.patient_id, practice.nurse_headers)
    )
    assert len(rows) == 1
    for row in rows:
        assert "version" not in row, "no ScreeningRecord in the response carries a version field"
        assert "updated_at" not in row


def test_screening_correction_appends_a_record_and_leaves_history_intact(api, practice):
    """A later record supersedes the derivation without editing the earlier row.

    PRD §2.4: "There is no endpoint that updates or deletes either one; a
    mistaken screening or lab result is corrected by filing a further record,
    not by editing history."

    Design: Corner/entities/screening_record_is_immutable_and_carries_no_version_field
    """
    fixtures.set_clock(CLOCK_DEFAULT, practice.admin_headers)

    positive = validate_success(
        api.create_screening_record(
            factories.create_screening_record_payload(
                practice.patient_id,
                "TB_IGRA",
                "POSITIVE",
                collected_at=instant(2026, 7, 1),
                resulted_at=instant(2026, 7, 2),
            ),
            practice.nurse_headers,
        ),
        201,
    )
    before = validate_success(api.get_patient(practice.patient_id, practice.admin_headers))
    assert before["tb_screen_status"] == "POSITIVE_UNTREATED"

    validate_success(
        api.create_screening_record(
            factories.create_screening_record_payload(
                practice.patient_id,
                "TB_LTBI_TREATMENT_COMPLETE",
                "COMPLETED",
                collected_at=instant(2026, 7, 20),
                resulted_at=instant(2026, 7, 21),
            ),
            practice.nurse_headers,
        ),
        201,
    )
    after = validate_success(api.get_patient(practice.patient_id, practice.admin_headers))
    assert after["tb_screen_status"] == "CLEARED_AFTER_TREATMENT"

    # The original row is untouched by the correction.
    igra_rows, igra_meta = assertions.validate_list(
        api.list_patient_screening_records(
            practice.patient_id, practice.nurse_headers, params={"screen_type": "TB_IGRA"}
        )
    )
    assert igra_meta["total_count"] == 1, "the treatment record is a different screen_type"
    assert igra_rows[0]["id"] == positive["id"]
    assert igra_rows[0]["result"] == "POSITIVE"
    assertions.assert_instant_equals(
        igra_rows[0]["resulted_at"], instant(2026, 7, 2), "resulted_at"
    )
    assert "version" not in igra_rows[0]
