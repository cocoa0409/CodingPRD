"""Corner queue — entity creation defaults, schema rejection, and nested
existence checks."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_contract,
    assert_study,
    create_contract_payload,
    create_design_plan_payload,
    create_participant_payload,
    create_study_payload,
    setup_contract,
    setup_contract_with_study,
    validate_error,
    validate_success,
)

AO = TEST_USERS["agency_officer_headers"]
PI = TEST_USERS["principal_investigator_headers"]
SD = TEST_USERS["study_director_headers"]


def test_contract_creation_applies_defaults(api):
    """PRD §3.1: "A new contract starts `ACTIVE` with `disbursed_cents` and
    `forfeited_cents` both zero and `remaining_cents` equal to the full award."
    PRD §3.1: "optionally a `deliverable_report_count` naming how many `FINAL`
    reports the agency requires — the count defaults to 1 and must be at
    least 1."

    Design: Corner/entities/contract_creation_applies_defaults
    """
    contract = validate_success(
        api.create_contract(
            create_contract_payload(
                agency_code="ACF-OPRE", title="Coaching Evaluation",
                award_amount_cents=90000000,
            ),
            AO,
        ),
        201,
    )
    assert_contract(contract)
    assert contract["status"] == "ACTIVE"
    assert contract["disbursed_cents"] == 0
    assert contract["forfeited_cents"] == 0
    assert contract["remaining_cents"] == 90000000
    assert contract["deliverable_report_count"] == 1, "default applied"
    assert contract["version"] == 1

    fetched = validate_success(api.get_contract(contract["id"], AO), 200)
    assert fetched["id"] == contract["id"]
    assert fetched["remaining_cents"] == 90000000


def test_study_creation_initial_computed_fields(api):
    """PRD §3.2: "The study is born in `DESIGN` status with
    `committed_projected_n`, `pipeline_projected_n`, `enrolled_total`, and
    `quarantined_record_count` all zero and `sample_adequacy` set to
    `UNASSESSED`."

    Design: Corner/entities/study_creation_initial_computed_fields
    """
    ctx = setup_contract()
    study = validate_success(
        api.create_study(
            ctx["id"],
            create_study_payload(
                title="Coaching Impact Study",
                research_question="Does coaching raise employment?",
            ),
            PI,
        ),
        201,
    )
    assert_study(study)
    assert study["status"] == "DESIGN"
    assert study["committed_projected_n"] == 0
    assert study["pipeline_projected_n"] == 0
    assert study["enrolled_total"] == 0
    assert study["quarantined_record_count"] == 0
    assert study["sample_adequacy"] == "UNASSESSED"


def test_contract_create_missing_required_returns_invalid_request(api):
    """PRD §2.8: "Required fields must be present, undeclared fields are
    rejected, types must be valid, enum values must be in range, and a window
    end must be after its start where applicable (`ERR_INVALID_REQUEST`, HTTP
    400)."
    PRD §3.1: "the total `award_amount_cents` as an integer number of cents
    that must be greater than zero."

    Design: Corner/entities/contract_create_missing_required_returns_invalid_request
    """
    resp = api.create_contract(
        {"agency_code": "ACF-OPRE", "title": "Coaching Evaluation"}, AO
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_design_plan_create_invalid_enum_rejected(api):
    """PRD §2.8: "Required fields must be present, undeclared fields are
    rejected, types must be valid, enum values must be in range, and a window
    end must be after its start where applicable (`ERR_INVALID_REQUEST`, HTTP
    400)."
    PRD §3.2: "supplying the `design_type` (one of `RCT`, `QED_MATCHING`,
    `QED_RDD`, or `QED_DID`; any of the three `QED_*` values selects the
    quasi-experimental variant)."

    Design: Corner/entities/design_plan_create_invalid_enum_rejected
    """
    ctx = setup_contract_with_study()
    study = ctx["study"]
    resp = api.create_design_plan(
        study["id"],
        create_design_plan_payload(
            expected_study_version=study["version"], design_type="QED_XTREME"
        ),
        PI,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_get_unknown_study_returns_not_found(api):
    """PRD §2.7: "The request is rejected immediately with `ERR_NOT_FOUND`
    (HTTP 404) at the first identifier that does not exist or does not belong
    to the enclosing parent; the system does not proceed to evaluate later
    identifiers or any business rule once an earlier path segment has failed."

    Design: Corner/entities/get_unknown_study_returns_not_found
    """
    resp = api.get_study(NON_EXISTENT_UUID, PI)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_contract_create_computed_field_input_ignored(api):
    """PRD §2.8: "Required fields must be present, undeclared fields are
    rejected, types must be valid, enum values must be in range, and a window
    end must be after its start where applicable (`ERR_INVALID_REQUEST`, HTTP
    400)." (`disbursed_cents` is server-computed, never an accepted input.)

    Design: Corner/entities/contract_create_computed_field_input_ignored
    """
    resp = api.create_contract(
        {
            "agency_code": "ACF-OPRE",
            "title": "T",
            "award_amount_cents": 1000,
            "disbursed_cents": 5,
        },
        AO,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_participant_create_under_unknown_site_returns_not_found(api):
    """PRD §2.7: "The request is rejected immediately with `ERR_NOT_FOUND`
    (HTTP 404) at the first identifier that does not exist or does not belong
    to the enclosing parent; the system does not proceed to evaluate later
    identifiers or any business rule once an earlier path segment has failed."

    Design: Corner/entities/participant_create_under_unknown_site_returns_not_found
    """
    resp = api.create_participant(
        NON_EXISTENT_UUID, create_participant_payload(external_ref="P001"), SD
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
