"""Corner queue: endpoint-behavior claims (amend happy path, settle cascade,
response envelope, vacatur rules)."""
from test_helpers import (
    TEST_USERS,
    UNKNOWN_UUID,
    ApiErrorId,
    amend_charge_payload,
    conclude_mediation,
    create_complainant_payload,
    make_charging_party_headers,
    read_charge,
    schedule_session,
    set_clock,
    setup_docketed_charge,
    setup_in_mediation,
    setup_settled_via_conciliation,
    setup_settled_via_mediation,
    vacate_settlement_payload,
    validate_created,
    validate_error,
    validate_ok,
    validate_paginated,
)
from test_helpers import api_client

_INTAKE = TEST_USERS["intake_officer_headers"]
_DIRECTOR = TEST_USERS["director_headers"]
_MEDIATOR = TEST_USERS["mediator_headers"]


def test_amend_happy_path_bumps_version(api):
    """PRD section 3.3: "The amendment payload must carry `expected_charge_version` per the OCC rule of §2.7, plus any of `basis_codes`, `incident_date`, or `harm_description` to change."
    PRD section 3.3: "A successful amendment increments the charge's `version` by 1."

    Design: Corner/endpoints/amend_happy_path_bumps_version
    """
    base = setup_docketed_charge(basis_codes=["RACE"], incident_date="2026-06-01")
    charge = base["charge"]

    amended = validate_ok(
        api_client.amend_charge(
            charge["id"],
            amend_charge_payload(
                expected_charge_version=charge["version"],
                harm_description="fired; supervisor quoted bias",
            ),
            make_charging_party_headers(charge["complainant_id"]),
        )
    )
    # Exactly one increment; the untouched fields and the state are preserved.
    assert amended["version"] == charge["version"] + 1
    assert amended["case_status"] == "DOCKETED"
    assert amended["harm_description"] == "fired; supervisor quoted bias"
    assert amended["basis_codes"] == ["RACE"]
    assert amended["employee_count_at_incident"] == 40


def test_conclude_settled_cancels_scheduled_sessions(api):
    """PRD section 3.4: "On settlement the mediation case becomes `SETTLED` with `concluded_at` stamped from the clock, the charge records `settled_amount_cents` equal to the agreed amount with `settled_via` set to `MEDIATION` and `settled_at` stamped from the clock, every `SCHEDULED` session is `CANCELLED`, and the charge moves `IN_MEDIATION` → `CLOSED_SETTLED`."

    Design: Corner/endpoints/conclude_settled_cancels_scheduled_sessions
    """
    base = setup_in_mediation(basis_codes=["RACE"], incident_date="2026-06-01")
    charge = base["charge"]
    mediation = base["mediation_case"]
    schedule_session(mediation, "med-012",
                     scheduled_start="2026-10-01T10:00:00Z",
                     scheduled_end="2026-10-01T11:00:00Z")

    settled = conclude_mediation(mediation, outcome="SETTLED",
                                 settlement_amount_cents=900_000,
                                 mediator_user_id="med-012")
    assert settled["status"] == "SETTLED"

    # The clock never passed the session's end, so it reads CANCELLED by the
    # conclude cascade, not HELD by the lazy transition.
    sessions, _meta = validate_paginated(
        api_client.list_mediation_sessions(mediation["id"], _MEDIATOR)
    )
    assert sessions[0]["status"] == "CANCELLED"

    closed = read_charge(charge["id"])
    assert closed["case_status"] == "CLOSED_SETTLED"
    assert closed["settled_amount_cents"] == 900_000
    assert closed["settled_via"] == "MEDIATION"


def test_response_envelope_shape_on_success_and_error(api):
    """PRD section 2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."
    PRD section 2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."
    PRD section 2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
    PRD section 2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."

    Design: Corner/endpoints/response_envelope_shape_on_success_and_error
    """
    created = api_client.create_complainant(
        create_complainant_payload(full_name="Finn Three", email="f3@x.com"),
        _INTAKE,
    )
    data = validate_created(created)
    body = created.json()
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert body["meta"]["api_request_timestamp"]
    assert body["response_type"] == "object"
    assert body["data"]["id"] == data["id"]

    missing = api_client.get_charge(UNKNOWN_UUID, _DIRECTOR)
    validate_error(missing, ApiErrorId.ERR_CHARGE_NOT_FOUND)
    error_body = missing.json()
    assert error_body["response_type"] == "error"
    assert error_body["data"]["error_id"] == "ERR_CHARGE_NOT_FOUND"
    assert isinstance(error_body["data"]["message"], str)
    assert error_body["data"]["message"]


def test_vacate_after_window_rejected(api):
    """PRD section 3.8: "Within 10 days of `settled_at` — the logical clock must be on or before `settled_at` plus 10 days; a later attempt is rejected with `ERR_VACATE_WINDOW_EXPIRED` — a `Director` may vacate, supplying a `reason`."

    Design: Corner/endpoints/vacate_after_window_rejected
    """
    base = setup_settled_via_mediation(settlement_amount_cents=500_000)
    charge = base["charge"]
    assert charge["settled_at"][:10] == "2026-09-01"

    # 2026-09-12 is 11 days after settlement: outside the inclusive window.
    set_clock("2026-09-12T00:00:00Z")
    expired = api_client.vacate_settlement(
        charge["id"], vacate_settlement_payload(reason="too late"), _DIRECTOR
    )
    validate_error(expired, ApiErrorId.ERR_VACATE_WINDOW_EXPIRED)

    unchanged = read_charge(charge["id"])
    assert unchanged["case_status"] == "CLOSED_SETTLED"
    assert unchanged["settled_amount_cents"] == 500_000


def test_vacate_conciliation_settlement_rejected(api):
    """PRD section 3.8: "Vacatur is available only when the charge is `CLOSED_SETTLED` with `settled_via` equal to `MEDIATION`; conciliation settlements are final and a vacate attempt against one is rejected with `ERR_INVALID_STATE`."

    Design: Corner/endpoints/vacate_conciliation_settlement_rejected
    """
    base = setup_settled_via_conciliation(
        offer_amount_cents=120_000,
        cause_components={
            "back_pay_cents": 100_000, "front_pay_cents": 0,
            "compensatory_damages_cents": 0, "punitive_damages_cents": 0,
            "harm_start_date": "2026-06-01",
        },
    )
    charge = base["charge"]
    assert base["conciliation"]["status"] == "SETTLED"
    assert charge["case_status"] == "CLOSED_SETTLED"
    assert charge["settled_via"] == "CONCILIATION"

    # Even inside the 10-day window, a conciliation settlement is final.
    rejected = api_client.vacate_settlement(
        charge["id"], vacate_settlement_payload(reason="regret"), _DIRECTOR
    )
    validate_error(rejected, ApiErrorId.ERR_INVALID_STATE)

    unchanged = read_charge(charge["id"])
    assert unchanged["case_status"] == "CLOSED_SETTLED"
    assert unchanged["settled_amount_cents"] == 120_000
