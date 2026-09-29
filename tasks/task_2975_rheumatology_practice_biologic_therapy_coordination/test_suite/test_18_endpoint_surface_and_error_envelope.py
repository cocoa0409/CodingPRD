"""Endpoint surface breadth and the shape of the error envelope.

Every test in this module translates exactly one instance of the
`endpoints` or `errors` section of the breadth-test design index:

  * the deferred reauthorization sweep's count vector and its idempotence
    (PRD §2.11, §3.5),
  * therapy-episode list filters composing with `limit` and `offset`
    (PRD §2.3, §2.5),
  * the two cross-entity links one dose booking writes, and their reverse
    reachability through the appointment list (PRD §3.7),
  * the seven path-scoped 404 codes of the rejection ladder (PRD §2.10),
  * the invariance of the error envelope across five status classes
    (PRD §2.2).
"""
import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import assertions, factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import instant
from test_helpers.fixtures import ADMIN
from test_helpers.test_users import make_patient_headers, make_rheumatologist_headers


# ---------------------------------------------------------------------------
# endpoints / reauthorization_calendar_sweep_reports_its_counts_and_is_idempotent
# ---------------------------------------------------------------------------
def test_reauthorization_sweep_reports_its_counts_and_then_reports_zeroes(api):
    """The first sweep past `valid_through` expires the authorization and lapses
    the episode's funding, reporting 1 / 1 / 0; the second reports all zeroes.

    PRD §2.11: "They are applied by an explicit sweep that a `RegistryAdmin`
    invokes, which compares the current logical clock against the stored
    deadlines and reports what it changed as three counters:
    `authorizations_expired`, `episodes_lapsed` and
    `enrollments_reauth_pending`."
    PRD §2.11: "The sweep is idempotent — running it twice against the same
    clock reports zeroes on the second run — and it is the only mechanism by
    which an authorization expires or an enrollment becomes due for renewal."
    PRD §3.5: "When the reauthorization sweep of §2.11 observes that the
    logical clock has passed an approved authorization's `valid_through`, that
    authorization moves `APPROVED → EXPIRED`, the episode's `funding_state`
    moves `AUTHORIZED → LAPSED`, and both revision counters increment by one;
    the sweep counts that pair in `authorizations_expired` and
    `episodes_lapsed`."

    Design: Corner/endpoints/reauthorization_calendar_sweep_reports_its_counts_and_is_idempotent
    """
    fixtures.set_clock(instant(2026, 8, 1))
    scenario = fixtures.active_episode(
        requested_units=6,
        determination_overrides={
            "approved_units": 6,
            "valid_from": instant(2026, 8, 1),
            "valid_through": instant(2026, 8, 31),
        },
    )

    # No AssistanceEnrollment exists, so the enrollment leg has nothing to do.
    fixtures.set_clock(instant(2027, 1, 1))

    first = validate_success(api.run_reauthorization_calendar(ADMIN), 200)
    assert first["authorizations_expired"] == 1, first
    assert first["episodes_lapsed"] == 1, first
    assert first["enrollments_reauth_pending"] == 0, first

    second = validate_success(api.run_reauthorization_calendar(ADMIN), 200)
    assert second["authorizations_expired"] == 0, second
    assert second["episodes_lapsed"] == 0, second
    assert second["enrollments_reauth_pending"] == 0, second

    authorization = get_success_data(api.get_authorization(scenario.authorization_id, ADMIN))
    assert authorization["status"] == "EXPIRED"
    assertions.assert_unit_ledger(authorization, reserved=0, consumed=0, remaining=6)

    episode = get_success_data(api.get_therapy_episode(scenario.episode_id, ADMIN))
    assert episode["funding_state"] == "LAPSED"
    assert episode["therapy_state"] == "ACTIVE"

    patient = get_success_data(api.get_patient(scenario.patient_id, ADMIN))
    assert patient["active_episode_count"] == 1, "the sweep touches funding only"


# ---------------------------------------------------------------------------
# endpoints / episode_list_filters_compose_with_limit_and_offset
# ---------------------------------------------------------------------------
def test_episode_list_filters_compose_with_limit_and_offset(api):
    """`therapy_state` and `patient_id` narrow the population before the page
    window is applied, so `total_count` reports the filtered row count.

    PRD §2.3: "Four pagination fields appear in the `meta` object of every list
    response: `limit` and `offset` echo the effective values applied to the
    query, `total_count` reports how many rows match the filters before the page
    window is applied, and `has_more` is true when rows remain beyond the
    current page."
    PRD §2.5: "Every one of those filters is optional and combines with `limit`
    and `offset`."

    Design: Corner/endpoints/episode_list_filters_compose_with_limit_and_offset
    """
    fixtures.set_clock(instant(2026, 8, 1))
    scenario = fixtures.bootstrap_reference()
    fixtures.register_patient(scenario, mrn="RH0001", full_name="Pat One")
    patient_two = get_success_data(
        api.create_patient(
            factories.create_patient_payload(
                mrn="RH0002",
                full_name="Pat Two",
                date_of_birth="1980-09-30",
                diagnosis_code="PSA",
            ),
            ADMIN,
        ),
        201,
    )

    # Patient one: one episode discontinued straight out of PLANNED, then a
    # second PLANNED episode. The discontinued one predates the second, so it
    # was never touched by the supersede cascade.
    episode_a = fixtures.open_planned_episode(scenario)
    get_success_data(
        api.discontinue_therapy_episode(
            episode_a["id"],
            factories.discontinue_episode_payload("INADEQUATE_RESPONSE"),
            scenario.rheum_headers,
        )
    )
    episode_b = fixtures.open_planned_episode(scenario, therapy_start_at=instant(2026, 8, 2))

    # Patient two: one PLANNED episode.
    episode_c = get_success_data(
        api.create_therapy_episode(
            factories.create_therapy_episode_payload(
                patient_two["id"],
                scenario.drug_id,
                scenario.plan_id,
                patient_two["version"],
                therapy_start_at=instant(2026, 8, 2),
            ),
            scenario.rheum_headers,
        ),
        201,
    )

    rows, meta = assertions.validate_list(
        api.list_therapy_episodes(ADMIN, params={"therapy_state": "PLANNED"})
    )
    assertions.assert_pagination_meta(meta, limit=10, offset=0, total_count=2, has_more=False)
    assert {row["id"] for row in rows} == {episode_b["id"], episode_c["id"]}

    rows, meta = assertions.validate_list(
        api.list_therapy_episodes(
            ADMIN, params={"therapy_state": "PLANNED", "limit": 1, "offset": 1}
        )
    )
    assert len(rows) == 1
    assertions.assert_pagination_meta(meta, limit=1, offset=1, total_count=2, has_more=False)

    rows, meta = assertions.validate_list(
        api.list_therapy_episodes(
            ADMIN, params={"therapy_state": "PLANNED", "limit": 1, "offset": 2}
        )
    )
    assert rows == []
    assertions.assert_pagination_meta(meta, limit=1, offset=2, total_count=2, has_more=False)

    rows, meta = assertions.validate_list(
        api.list_therapy_episodes(ADMIN, params={"patient_id": scenario.patient_id})
    )
    assert meta["total_count"] == 2
    by_id = {row["id"]: row for row in rows}
    assert episode_a["id"] in by_id
    assert by_id[episode_a["id"]]["therapy_state"] == "DISCONTINUED"

    rows, meta = assertions.validate_list(
        api.list_therapy_episodes(
            ADMIN,
            params={"patient_id": scenario.patient_id, "therapy_state": "DISCONTINUED"},
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == episode_a["id"]
    assert rows[0]["discontinuation_reason"] == "INADEQUATE_RESPONSE"


# ---------------------------------------------------------------------------
# endpoints /
# scheduling_a_dose_links_the_appointment_to_both_its_authorization_and_its_enrollment
# ---------------------------------------------------------------------------
def test_scheduling_a_dose_links_its_authorization_and_its_enrollment(api):
    """One booking reserves a unit on the authorization and caps the assistance
    at the grant's remaining benefit; both links are reverse-reachable.

    PRD §3.7: "**Fifth**, the gross assistance is capped at the enrollment's
    `benefit_remaining_cents`, and `assistance_applied_cents` becomes the
    smaller of the two."
    PRD §3.7: "**Sixth**, the books are settled: `patient_out_of_pocket_cents`
    is the gross share less `assistance_applied_cents`, `reserved_enrollment_id`
    records the chosen enrollment, that amount is added to the enrollment's
    `benefit_reserved_cents` and subtracted from its `benefit_remaining_cents`,
    and if `benefit_remaining_cents` thereby reaches exactly zero the enrollment
    moves `ACTIVE → EXHAUSTED` and its `version` increments by one."
    PRD §3.7: "An appointment read exposes its per-dose money —
    `dose_cost_share_cents`, `assistance_applied_cents` and
    `patient_out_of_pocket_cents` — alongside its schedule and status, and the
    appointment list is the reverse channel to `episode_id`, `chair_id`,
    `reserved_authorization_id` and `reserved_enrollment_id`."

    Design: Corner/endpoints/scheduling_a_dose_links_the_appointment_to_both_its_authorization_and_its_enrollment
    """
    fixtures.set_clock(instant(2026, 8, 1))
    scenario = fixtures.active_episode(
        requested_units=6,
        determination_overrides={
            "approved_units": 6,
            "valid_from": instant(2026, 8, 1),
            "valid_through": instant(2027, 1, 28),
        },
    )
    enrollment = fixtures.active_enrollment(
        scenario,
        program_type="FOUNDATION_GRANT",
        annual_benefit_cents=50_000,
        coverage_start=instant(2026, 8, 1),
    )
    assert enrollment["status"] == "ACTIVE"
    assertions.assert_instant_equals(
        enrollment["coverage_end"], instant(2027, 1, 28), "coverage_end"
    )
    assertions.assert_instant_equals(
        enrollment["reauth_due_at"], instant(2026, 12, 29), "reauth_due_at"
    )

    appointment = fixtures.schedule_appointment(scenario, instant(2026, 8, 3, 9, 0, 0))
    assertions.assert_infusion_appointment(appointment)

    assert appointment["reserved_authorization_id"] == scenario.authorization_id
    assert appointment["reserved_enrollment_id"] == enrollment["id"]
    assert appointment["dose_sequence"] == 1
    assert appointment["dose_cost_share_cents"] == 138_759
    assert appointment["assistance_applied_cents"] == 50_000
    assert appointment["patient_out_of_pocket_cents"] == 88_759

    authorization = get_success_data(api.get_authorization(scenario.authorization_id, ADMIN))
    assertions.assert_unit_ledger(authorization, reserved=1, consumed=0, remaining=5)

    refreshed = get_success_data(api.get_assistance_enrollment(enrollment["id"], ADMIN))
    assertions.assert_money_ledger(refreshed, used=0, reserved=50_000, remaining=0)
    assert refreshed["status"] == "EXHAUSTED"

    for filter_params in (
        {"reserved_authorization_id": scenario.authorization_id},
        {"reserved_enrollment_id": enrollment["id"]},
    ):
        rows, meta = assertions.validate_list(
            api.list_infusion_appointments(scenario.nurse_headers, params=filter_params)
        )
        assert meta["total_count"] == 1, filter_params
        assert rows[0]["id"] == appointment["id"], filter_params


# ---------------------------------------------------------------------------
# errors / every_path_scoped_lookup_returns_its_own_not_found_code
# ---------------------------------------------------------------------------
PATH_SCOPED_NOT_FOUND_CASES = [
    pytest.param(
        "GET", f"/patients/{NON_EXISTENT_UUID}", None,
        ApiErrorId.ERR_PATIENT_NOT_FOUND.value, id="patient",
    ),
    pytest.param(
        "GET", f"/visits/{NON_EXISTENT_UUID}", None,
        ApiErrorId.ERR_VISIT_NOT_FOUND.value, id="visit",
    ),
    pytest.param(
        "GET", f"/therapy-episodes/{NON_EXISTENT_UUID}", None,
        ApiErrorId.ERR_EPISODE_NOT_FOUND.value, id="episode",
    ),
    pytest.param(
        "GET", f"/authorizations/{NON_EXISTENT_UUID}", None,
        ApiErrorId.ERR_AUTHORIZATION_NOT_FOUND.value, id="authorization",
    ),
    pytest.param(
        "GET", f"/infusion-appointments/{NON_EXISTENT_UUID}", None,
        ApiErrorId.ERR_APPOINTMENT_NOT_FOUND.value, id="appointment",
    ),
    pytest.param(
        "GET", f"/assistance-enrollments/{NON_EXISTENT_UUID}", None,
        ApiErrorId.ERR_ENROLLMENT_NOT_FOUND.value, id="enrollment",
    ),
    pytest.param(
        "PATCH", f"/infusion-chairs/{NON_EXISTENT_UUID}", {"status": "CLOSED"},
        ApiErrorId.ERR_CHAIR_NOT_FOUND.value, id="chair",
    ),
]


@pytest.mark.parametrize(
    "method,path,payload,expected_error_id", PATH_SCOPED_NOT_FOUND_CASES
)
def test_every_path_scoped_lookup_returns_its_own_not_found_code(
    api, method, path, payload, expected_error_id
):
    """The same all-zero UUID yields a different 404 code on each path, keyed to
    the entity the `{id}` segment names.

    PRD §2.10: "`ERR_PATIENT_NOT_FOUND` — the patient `id` in the path does not
    resolve. Applies to the single-patient read, the patient screening-record
    list and the quality report."
    PRD §2.10: "`ERR_VISIT_NOT_FOUND` — the visit `id` in the path does not
    resolve. Applies to the single-visit read, check-in and scoring."
    PRD §2.10: "`ERR_EPISODE_NOT_FOUND` — the therapy-episode `id` in the path
    does not resolve. Applies to every episode-scoped endpoint."
    PRD §2.10: "`ERR_AUTHORIZATION_NOT_FOUND` — the authorization `id` in the
    path does not resolve. Applies to every authorization-scoped endpoint."
    PRD §2.10: "`ERR_APPOINTMENT_NOT_FOUND` — the appointment `id` in the path
    does not resolve. Applies to every appointment-scoped endpoint."
    PRD §2.10: "`ERR_ENROLLMENT_NOT_FOUND` — the enrollment `id` in the path
    does not resolve. Applies to every enrollment-scoped endpoint."
    PRD §2.10: "`ERR_CHAIR_NOT_FOUND` — the chair `id` in the path does not
    resolve. Applies to the chair status update."

    Design: Corner/errors/every_path_scoped_lookup_returns_its_own_not_found_code
    """
    fixtures.set_clock(instant(2026, 8, 1))
    seeded = get_success_data(
        api.create_patient(factories.create_patient_payload(mrn="RH0001"), ADMIN), 201
    )

    response = api.raw(method, path, payload, ADMIN)
    validate_error(response, expected_error_id, 404)

    # The seeded row is untouched by the miss.
    validate_success(api.get_patient(seeded["id"], ADMIN), 200)


# ---------------------------------------------------------------------------
# errors / the_error_envelope_is_identical_across_every_status_class
# ---------------------------------------------------------------------------
def _assert_error_envelope(response, expected_error_id, expected_status):
    """A 4xx body is `response_type` "error", a two-key `data` and a two-key
    `meta`; no partial entity ever leaks into `data`."""
    error_data = validate_error(response, expected_error_id, expected_status)
    body = response.json()

    assert body["response_type"] == "error"
    assert set(error_data.keys()) == {"error_id", "message"}, (
        f"error data must hold exactly error_id and message, got {sorted(error_data)}"
    )
    assert error_data["message"].strip(), "message must be a non-empty explanation"

    meta = body["meta"]
    assert set(meta.keys()) == {"api_request_id", "api_request_timestamp"}, (
        f"error meta must hold only api_request_id and api_request_timestamp, "
        f"got {sorted(meta)}"
    )
    assert isinstance(meta["api_request_id"], str) and meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {meta['api_request_id']!r}"
    )
    assert isinstance(meta["api_request_timestamp"], str) and meta["api_request_timestamp"]


def test_the_error_envelope_is_identical_across_every_status_class(api):
    """A 403, a 404, a 409, a 412 and a 422 all carry the same envelope: only
    the status code and the `error_id` vary.

    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."

    Design: Corner/errors/the_error_envelope_is_identical_across_every_status_class
    """
    fixtures.set_clock(instant(2026, 8, 1))
    clinician = fixtures.create_clinician(None, npi="1234567893", full_name="Ada Rheum")
    drug = fixtures.create_drug(None)
    plan = fixtures.create_plan(None)
    patient = get_success_data(
        api.create_patient(
            factories.create_patient_payload(mrn="RH0001", full_name="Pat One"), ADMIN
        ),
        201,
    )
    rheum_headers = make_rheumatologist_headers(clinician["id"])

    # 403 — the Patient role holds no write privilege anywhere in the API.
    _assert_error_envelope(
        api.create_drug(
            factories.create_drug_payload(
                name="Golimumab",
                route="SC",
                formulary_tier=3,
                acquisition_cost_cents=200_000,
                admin_time_minutes=0,
                monitoring_panel_type="CBC",
                monitoring_panel_interval_days=180,
            ),
            make_patient_headers(patient["id"]),
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
        403,
    )

    # 404 — an unresolvable path segment.
    _assert_error_envelope(
        api.get_patient(NON_EXISTENT_UUID, ADMIN),
        ApiErrorId.ERR_PATIENT_NOT_FOUND.value,
        404,
    )

    # 409 — a natural key colliding within its own collection.
    _assert_error_envelope(
        api.create_patient(
            factories.create_patient_payload(mrn="RH0001", full_name="Clone One"), ADMIN
        ),
        ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value,
        409,
    )

    # 412 — an expected_patient_version that does not equal the current one.
    _assert_error_envelope(
        api.create_therapy_episode(
            factories.create_therapy_episode_payload(
                patient["id"],
                drug["id"],
                plan["id"],
                patient["version"] + 1,
                therapy_start_at=instant(2026, 8, 1),
            ),
            rheum_headers,
        ),
        ApiErrorId.ERR_STALE_PATIENT_VERSION.value,
        412,
    )

    # 422 — a timestamp that does not parse as an ISO 8601 UTC instant.
    _assert_error_envelope(
        api.create_therapy_episode(
            factories.create_therapy_episode_payload(
                patient["id"],
                drug["id"],
                plan["id"],
                patient["version"],
                therapy_start_at="yesterday",
            ),
            rheum_headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )

    # No rejected body mutated the row.
    unchanged = get_success_data(api.get_patient(patient["id"], ADMIN))
    assert unchanged["version"] == patient["version"]
    assert unchanged["full_name"] == "Pat One"
