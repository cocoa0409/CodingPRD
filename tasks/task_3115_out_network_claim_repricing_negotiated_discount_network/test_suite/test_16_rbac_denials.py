"""Corner queue: RBAC peer-role separation."""
from test_helpers import (
    api_client, validate_error, get_success_data,
    create_payer, create_provider, create_claim_payload,
    setup_priced_claim, create_negotiation_case_payload,
    make_payer_admin_headers,
    TEST_USERS, ApiErrorId,
)

IDR = TEST_USERS["idr_entity_headers"]


def test_payer_admin_cannot_ingest_claims():
    """PRD §2.1: "When the role is recognized but not permitted for the target
    endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: "| POST | `/claims` | Ingest a claim from a payer feed | PayerRep |"

    Design: Corner/rbac/payer_admin_cannot_ingest_claims
    """
    payer = create_payer()
    provider = create_provider(npi="7000000001")
    res = api_client.create_claim(
        create_claim_payload(payer["id"], provider["id"],
                             external_claim_ref="R1"),
        make_payer_admin_headers(payer["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_idr_entity_cannot_negotiate():
    """PRD §2.1: "When the role is recognized but not permitted for the target
    endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: "| POST | `/negotiation-cases` | Open a negotiation on an
    out-of-network claim | PayerRep, ProviderRep |"

    Design: Corner/rbac/idr_entity_cannot_negotiate
    """
    env = setup_priced_claim(claim_overrides={"external_claim_ref": "R2"},
                             npi="7000000002")
    res = api_client.create_negotiation_case(
        create_negotiation_case_payload(env["claim"]["id"]), IDR)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE)
