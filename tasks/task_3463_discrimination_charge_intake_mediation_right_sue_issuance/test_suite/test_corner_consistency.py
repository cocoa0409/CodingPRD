"""Corner queue: consistency-model claims — computed results are visible in
the very response that produces them."""
from test_helpers import (
    add_days,
    assert_charge,
    create_charge_payload,
    create_deferral_agency,
    create_employer,
    create_complainant,
    validate_created,
)
from test_helpers import api_client
from test_helpers import TEST_USERS

_INTAKE = TEST_USERS["intake_officer_headers"]


def test_screening_visible_in_creation_response(api):
    """PRD section 3.2: "Creation synchronously runs jurisdictional screening; intake never rejects a charge for being late or too small — it records the outcome."
    PRD section 3.2: "The newly created charge lands in `DOCKETED` (timely, Commission-retained), `DELEGATED_TO_FEPA` (FEPA-exclusive), `DISMISSED_UNTIMELY`, or `DISMISSED_NO_JURISDICTION`, and is returned with a 201."
    PRD section 2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."

    Design: Corner/consistency_model/screening_visible_in_creation_response
    """
    create_deferral_agency(
        state_code="CA", filing_deadline_days=300,
        work_sharing_policy="DUAL_FILE_DEFAULT", covers_age=True,
        agency_name="CA FEPA",
    )
    employer = create_employer(state_code="CA", employee_count_current=40,
                               legal_name="Imm Co")
    complainant = create_complainant(full_name="Gale Eleven", email="g11@x.com")

    # The 201 response body itself carries every computed screening field —
    # no second read is needed to observe them.
    created = api_client.create_charge(
        create_charge_payload(
            complainant_id=complainant["id"], employer_id=employer["id"],
            basis_codes=["RACE"], incident_date="2026-03-04",
            harm_description="fired", employee_count_at_incident=40,
        ),
        _INTAKE,
    )
    charge = validate_created(created)
    assert_charge(charge)
    assert charge["case_status"] == "DOCKETED"
    assert charge["jurisdiction_outcome"] == "TIMELY_CONFIRMED"
    assert charge["filing_deadline_date"][:10] == add_days("2026-03-04", 300) == "2026-12-29"
    assert charge["investigation_owner"] == "EEOC"
    assert charge["dual_filed"] is True
