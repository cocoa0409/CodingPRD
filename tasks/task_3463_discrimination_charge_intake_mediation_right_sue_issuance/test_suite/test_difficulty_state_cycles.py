"""Difficulty queue: non-linear state machines — the Charge mediation cycle
and the ConciliationProcess offer/counter-offer cycle."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    conclude_mediation,
    create_employer,
    create_complainant,
    file_charge,
    make_director_headers,
    offer_mediation,
    read_charge,
    respond_to_mediation,
    setup_conciliation,
    table_offer,
    table_offer_payload,
    validate_error,
    validate_ok,
)
from test_helpers import api_client

_INTAKE = TEST_USERS["intake_officer_headers"]
_DIRECTOR = TEST_USERS["director_headers"]


def test_charge_mediation_investigation_cycle(api):
    """PRD section 3.4: "An `IntakeOfficer` offers mediation on a charge that is `DOCKETED` or `UNDER_INVESTIGATION`, provided every prior mediation case on the charge is in a terminal state and fewer than 2 mediation cases already exist — offering a third is rejected with `ERR_MEDIATION_ROUND_EXHAUSTED`, the hard cap being 2 rounds per charge."
    PRD section 3.4: "When the second `ACCEPTED` arrives — both responses now `ACCEPTED` — the mediation moves `OFFERED` → `ACTIVE` and the charge moves to `IN_MEDIATION`; on re-entry from `UNDER_INVESTIGATION`, the charge's investigation case, if it exists and is `GATHERING`, suspends to `SUSPENDED_MEDIATION`."
    PRD section 3.4: "On `IMPASSE` the case becomes `IMPASSE` with `concluded_at` stamped, scheduled sessions are cancelled, the charge returns to `UNDER_INVESTIGATION`, and the investigation resumes — an existing case moves `SUSPENDED_MEDIATION` → `GATHERING`, or, if somehow none exists, one is auto-created in `OPEN`."

    Design: Difficulty/non_linear_state_machine/charge_mediation_investigation_cycle
    """
    employer = create_employer(state_code="FL", employee_count_current=40,
                               legal_name="Cycle Co")
    complainant = create_complainant(full_name="Pat Six", email="p6@x.com")
    charge = file_charge(employer, complainant, basis_codes=["SEX"],
                         incident_date="2026-06-01", harm_description="harassment",
                         employee_count_at_incident=40)

    # Round 1: both parties accept -> IN_MEDIATION; IMPASSE -> UNDER_INVESTIGATION.
    mediation_1 = offer_mediation(charge)
    assert mediation_1["round_number"] == 1
    respond_to_mediation(charge, mediation_1, "complainant", "ACCEPTED")
    mediation_1 = respond_to_mediation(charge, mediation_1, "respondent", "ACCEPTED")
    assert mediation_1["status"] == "ACTIVE"
    assert read_charge(charge["id"])["case_status"] == "IN_MEDIATION"

    conclude_mediation(mediation_1, outcome="IMPASSE")
    after_first = read_charge(charge["id"])
    assert after_first["case_status"] == "UNDER_INVESTIGATION"
    case_id = after_first["investigation_case_id"]
    assert case_id  # auto-created by the impasse cascade

    # Round 2: re-offer from UNDER_INVESTIGATION and both accept again.
    mediation_2 = offer_mediation(after_first)
    assert mediation_2["round_number"] == 2
    respond_to_mediation(after_first, mediation_2, "respondent", "ACCEPTED")
    respond_to_mediation(after_first, mediation_2, "complainant", "ACCEPTED")
    assert read_charge(charge["id"])["case_status"] == "IN_MEDIATION"
    # The investigation never gathered evidence, so the conditional
    # GATHERING -> SUSPENDED_MEDIATION side effect does not fire: it stays OPEN.
    mid = validate_ok(api_client.get_investigation_case(case_id, _DIRECTOR))
    assert mid["status"] == "OPEN"

    conclude_mediation(mediation_2, outcome="IMPASSE")

    # The hard cap: a third mediation offer is rejected.
    third = api_client.offer_mediation(charge["id"], _INTAKE)
    validate_error(third, ApiErrorId.ERR_MEDIATION_ROUND_EXHAUSTED)

    final = read_charge(charge["id"])
    assert final["case_status"] == "UNDER_INVESTIGATION"
    # Exactly one InvestigationCase ever exists for the charge (1:1 pair).
    assert final["investigation_case_id"] == case_id
    end = validate_ok(api_client.get_investigation_case(case_id, _DIRECTOR))
    assert end["status"] == "OPEN"


def test_conciliation_offer_counteroffer_cycle(api):
    """PRD section 3.7: "The first offer moves the process `INITIATED` → `OFFER_TABLED`."
    PRD section 3.7: "From then on the sides must strictly alternate: a counter-offer by the side that did not table the current offer flips the process `OFFER_TABLED` → `COUNTERED`, and the next counter flips `COUNTERED` → `OFFER_TABLED` again — a two-state negotiation cycle."
    PRD section 3.7: "An offer tabled by the same side twice in a row is rejected with `ERR_OFFER_OUT_OF_TURN`."
    PRD section 3.7: "Each successful offer records the new `amount_cents` in `current_offer_cents`, sets or flips `last_offer_by` to the tabling side, increments `rounds_count` by 1, and increments the process `version` by 1."

    Design: Difficulty/non_linear_state_machine/conciliation_offer_counteroffer_cycle
    """
    base = setup_conciliation(
        cause_components={
            "back_pay_cents": 100_000, "front_pay_cents": 0,
            "compensatory_damages_cents": 0, "punitive_damages_cents": 0,
            "harm_start_date": "2026-06-01",
        },
        investigator_user_id="inv-004",
        director_user_id="dir-003",
    )
    charge = base["charge"]
    conciliation = base["conciliation"]

    offer_1 = table_offer(conciliation, 200_000, "COMMISSION", charge,
                          director_user_id="dir-003")
    assert offer_1["status"] == "OFFER_TABLED"
    assert offer_1["last_offer_by"] == "COMMISSION"

    offer_2 = table_offer(offer_1, 150_000, "RESPONDENT", charge)
    assert offer_2["status"] == "COUNTERED"
    assert offer_2["last_offer_by"] == "RESPONDENT"

    offer_3 = table_offer(offer_2, 175_000, "COMMISSION", charge,
                          director_user_id="dir-003")
    assert offer_3["status"] == "OFFER_TABLED"
    assert offer_3["rounds_count"] == 3
    assert offer_3["current_offer_cents"] == 175_000
    assert offer_3["last_offer_by"] == "COMMISSION"
    assert offer_3["version"] == conciliation["version"] + 3

    # Same side twice in a row: rejected even with the current OCC version.
    out_of_turn = api_client.table_offer(
        offer_3["id"],
        table_offer_payload(amount_cents=180_000,
                            expected_conciliation_version=offer_3["version"]),
        make_director_headers("dir-003"),
    )
    validate_error(out_of_turn, ApiErrorId.ERR_OFFER_OUT_OF_TURN)
