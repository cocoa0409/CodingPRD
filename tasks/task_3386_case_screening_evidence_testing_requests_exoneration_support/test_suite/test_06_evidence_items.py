"""Evidence item registration: server-computed remaining sample, the posture
re-derivation on first arrival, and the independence of the two state
dimensions carried on one evidence item."""
from test_helpers import (
    advance_evidence_item,
    assert_evidence_item,
    create_evidence_item,
    create_testing_authorization,
    create_testing_authorization_payload,
    get_case,
    get_evidence_item,
    setup_accepted_case,
    setup_case_in_investigation,
    sign_agreement,
    TEST_USERS,
    validate_created,
)

ATTORNEY = TEST_USERS["staff_attorney_headers"]


def test_evidence_item_create_computes_remaining_and_posture(api):
    """PRD section 3.3: "The new item's `location_status` starts at
    `IDENTIFIED`, its `remaining_sample_ng` starts equal to
    `initial_sample_ng`, and its arrival re-derives the owning case's
    `evidence_posture` — a case with no prior items moves from `NO_EVIDENCE`
    to `SEEKING`."

    Design: Corner/entities/evidence_item_create_computes_remaining_and_posture
    """
    ctx = setup_accepted_case(
        jurisdiction_overrides={"state_code": "UT", "name": "Utah"}
    )
    assert ctx["case"]["evidence_posture"] == "NO_EVIDENCE"

    resp = api.create_evidence_item(
        {
            "case_id": ctx["case"]["id"],
            "description": "Envelope with hair",
            "evidence_type": "OTHER",
            "custodian_type": "COURT_CLERK",
            "initial_sample_ng": 9,
        },
        TEST_USERS["evidence_analyst_headers"],
    )
    item = validate_created(resp)
    assert_evidence_item(item)
    assert item["remaining_sample_ng"] == 9, "remaining starts equal to initial"
    assert item["location_status"] == "IDENTIFIED"
    assert item["testing_status"] == "UNTESTED"

    assert get_case(ctx["case"]["id"])["evidence_posture"] == "SEEKING"


def test_location_moves_leave_testing_dimension_untouched(api):
    """PRD section 3.3: "An evidence item carries two independent state
    dimensions on one row."
    PRD section 3.3: "A transition on one dimension never writes the other."
    PRD section 3.3: "The location dimension walks `IDENTIFIED` → `SEARCHING`
    when the analyst starts the search; `SEARCHING` → `LOCATED` when material
    is found".

    Design: Difficulty/non_linear_state_machine/evidence_location_and_testing_dims_evolve_independently
    """
    ctx = setup_case_in_investigation(
        jurisdiction_overrides={"state_code": "WA", "name": "Washington"}
    )
    item = create_evidence_item(
        ctx["case"]["id"],
        description="Fingerprint card",
        evidence_type="FINGERPRINT_CARD",
        custodian_type="COURT_CLERK",
        initial_sample_ng=20,
    )
    assert item["location_status"] == "IDENTIFIED"
    assert item["testing_status"] == "UNTESTED"

    advance_evidence_item(item["id"], "START_SEARCH")
    mid = get_evidence_item(item["id"])
    assert mid["location_status"] == "SEARCHING"
    assert mid["testing_status"] == "UNTESTED", "location move must not write testing_status"

    advance_evidence_item(item["id"], "MARK_LOCATED")
    advance_evidence_item(item["id"], "CONFIRM_CUSTODY")
    end = get_evidence_item(item["id"])
    assert end["location_status"] == "CUSTODY_CONFIRMED"
    assert end["testing_status"] == "UNTESTED"


def test_testing_move_leaves_location_dimension_untouched(api):
    """PRD section 3.4: "Either path to effectiveness — a signature reaching
    `SIGNED` or a ruling reaching `GRANTED` — re-derives the linked evidence
    item's `testing_status`, which becomes `TESTING_AUTHORIZED` when no
    laboratory activity exists on the item yet (§3.5)."
    PRD section 3.3: "A transition on one dimension never writes the other."

    Design: Difficulty/non_linear_state_machine/evidence_location_and_testing_dims_evolve_independently
    """
    ctx = setup_case_in_investigation(
        jurisdiction_overrides={"state_code": "WA", "name": "Washington"}
    )
    item = create_evidence_item(
        ctx["case"]["id"],
        description="Fingerprint card",
        evidence_type="FINGERPRINT_CARD",
        custodian_type="COURT_CLERK",
        initial_sample_ng=20,
    )
    advance_evidence_item(item["id"], "START_SEARCH")
    advance_evidence_item(item["id"], "MARK_LOCATED")
    advance_evidence_item(item["id"], "CONFIRM_CUSTODY")

    authorization = create_testing_authorization(
        ctx["case"]["id"], item["id"], "AGREEMENT", terms="Print re-lift"
    )
    sign_agreement(authorization["id"])

    after = get_evidence_item(item["id"])
    assert after["testing_status"] == "TESTING_AUTHORIZED"
    assert after["location_status"] == "CUSTODY_CONFIRMED", (
        "the authorization cascade writes the testing dimension only"
    )
