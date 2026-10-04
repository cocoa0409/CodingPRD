"""Entity creation baseline: jurisdiction statute-field defaults and
round-trips, and client system-minted fields on the standard envelope."""
from test_helpers import (
    TEST_USERS,
    assert_client,
    assert_jurisdiction,
    create_client_payload,
    create_jurisdiction_payload,
    validate_created,
    validate_ok,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SPECIALIST = TEST_USERS["intake_specialist_headers"]


def test_jurisdiction_create_applies_defaults_and_roundtrips(api):
    """PRD section 2.8: "`actual_innocence_enhancement_pct` records the
    percentage enhancement applied to the tiered award when the case carries
    exculpatory evidence, defaulting to 0 (no enhancement) and bounded between
    0 and 100."
    PRD section 2.8: "`post_conviction_deadline_years` records the number of
    years after conviction within which a post-conviction petition must be
    filed (a null value means the jurisdiction imposes no statutory
    deadline); ... `compensation_cap_cents` records the statutory cap on the
    tiered portion of a compensation award, in cents (null means uncapped)".
    PRD section 2.5: "`version` (integer): starts at 1 at creation".

    Design: Corner/entities/jurisdiction_create_applies_defaults_and_roundtrips
    """
    created = validate_created(
        api.create_jurisdiction(
            create_jurisdiction_payload(
                state_code="AK",
                name="Alaska",
                has_post_conviction_dna_statute=False,
                clemency_available=False,
                compensation_statute_exists=False,
            ),
            ADMIN,
        )
    )
    assert_jurisdiction(created)
    assert created["version"] == 1
    # The three optional statute fields were omitted from the payload.
    assert created["post_conviction_deadline_years"] is None
    assert created["compensation_cap_cents"] is None
    assert created["actual_innocence_enhancement_pct"] == 0

    fetched = validate_ok(api.get_jurisdiction(created["id"], ADMIN))
    assert_jurisdiction(fetched)
    assert all(fetched[key] == value for key, value in created.items()), (
        "every stored field round-trips through GET unchanged"
    )
    assert fetched["state_code"] == "AK"
    assert fetched["has_post_conviction_dna_statute"] is False
    assert fetched["clemency_available"] is False
    assert fetched["compensation_statute_exists"] is False


def test_client_create_returns_system_minted_fields(api):
    """PRD section 4: "Operations that create a new resource return
    `201 Created`".
    PRD section 2.2: "The `api_request_id` is a server-generated unique
    identifier for the request that starts with `req_`."
    PRD section 2.5: "Every entity in the system — jurisdictions, clients,
    intake requests, cases, evidence items, records requests, testing
    authorizations, lab analyses, legal petitions, compensation claims,
    reentry providers, reentry referrals, and policy initiatives — carries a
    standard set of system-managed fields".
    PRD section 3.1: "An `IntakeSpecialist` registers each incarcerated
    requester as a `Client`, capturing the person's `full_name`,
    department-of-corrections `inmate_number`, and optionally the current
    `facility_name`."

    Design: Corner/entities/client_create_returns_system_minted_fields
    """
    resp = api.create_client(
        create_client_payload(full_name="Prim Okafor", inmate_number="XX-0001"),
        SPECIALIST,
    )
    envelope = resp.json()
    data = validate_created(resp)
    assert envelope["response_type"] == "object"
    assert envelope["meta"]["api_request_id"].startswith("req_")
    assert envelope["meta"]["api_request_timestamp"]

    assert_client(data)
    assert data["full_name"] == "Prim Okafor"
    assert data["inmate_number"] == "XX-0001"
    assert data["version"] == 1
    assert data["created_at"] == data["updated_at"]
    assert data.get("facility_name") is None, "optional field omitted"
