"""Breadth probes over role denial: endpoint-level and transition-level
authorization."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    begin_campaign_testing,
    campaign_transition_payload,
    create_campaign,
    create_equipment_unit_payload,
    create_procurement_payload,
    create_test_laboratory,
    create_voting_system,
    get_campaign,
    make_lab_agent_headers,
    propose_modification,
    set_clock,
    setup_certified_jurisdiction,
    validate_error,
)

VENDOR = TEST_USERS["vendor_rep_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
PUBLIC = TEST_USERS["public_requester_headers"]
OFFICIAL_FALLBACK = TEST_USERS["election_official_headers"]


def test_vendor_cannot_certify_campaign(api):
    """PRD §3.2: "Certification is the `CertificationAuthority`'s act
    (`IN_TEST` → `CERTIFIED`)."
    PRD §2.1: "Authorization is enforced per endpoint and, on
    state-transition endpoints, per individual transition: the acting role
    must be the declared actor of the specific `to_state` being requested,
    not merely a role allowed on the endpoint as a whole."

    Design: Corner/rbac/vendor_cannot_certify_campaign
    """
    set_clock("2026-09-01T00:00:00Z")
    system = create_voting_system()
    lab = create_test_laboratory()
    campaign = create_campaign(system["id"], lab["id"])
    begin_campaign_testing(campaign["id"], lab["id"])

    resp = api.transition_certification_campaign(
        campaign["id"], campaign_transition_payload("CERTIFIED"), VENDOR
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    assert get_campaign(campaign["id"])["status"] == "IN_TEST"


def test_public_requester_cannot_create_procurement(api):
    """PRD §2.1: "`PublicRequester` is the unauthenticated-equivalent role
    for transparency reads; it has no write operations at all."
    PRD §2.1: "A request whose role is authenticated but not permitted on the
    target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/public_requester_cannot_create_procurement
    """
    base = setup_certified_jurisdiction()
    resp = api.create_procurement(
        create_procurement_payload(
            base["jurisdiction"]["id"], base["system"]["id"],
            base["certificate"]["id"], quantity=1, unit_price_cents=100,
        ),
        PUBLIC,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_auditor_cannot_create_equipment_unit(api):
    """PRD §2.1: "A request whose role is authenticated but not permitted on
    the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: "| POST | `/evote/equipment-units` | Register an equipment unit
    of a `FIELDED` system | ElectionOfficial |"

    Design: Corner/rbac/auditor_cannot_create_equipment_unit
    """
    base = setup_certified_jurisdiction()
    off1 = base["officials"][0]["id"]
    resp = api.create_equipment_unit(
        create_equipment_unit_payload(
            base["jurisdiction"]["id"], base["system"]["id"], off1,
            serial_number="SN-9001",
        ),
        AUDITOR,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_official_cannot_classify_modification(api):
    """PRD §3.9: "Classification is the `CertificationAuthority`'s decision".
    PRD §2.1: "Authorization is enforced per endpoint and, on
    state-transition endpoints, per individual transition: the acting role
    must be the declared actor of the specific `to_state` being requested,
    not merely a role allowed on the endpoint as a whole."

    Design: Corner/rbac/official_cannot_classify_modification
    """
    set_clock("2026-09-01T00:00:00Z")
    system = create_voting_system()
    mod = propose_modification(
        system["id"],
        description="EMS tweak",
        component_codes=["ELECTION_MANAGEMENT_UI"],
    )
    resp = api.transition_software_modification(
        mod["id"], {"to_state": "DE_MINIMIS_APPROVED"}, OFFICIAL_FALLBACK
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_lab_agent_cannot_certify_campaign(api):
    """PRD §3.2: "Certification is the `CertificationAuthority`'s act
    (`IN_TEST` → `CERTIFIED`)."
    PRD §2.1: "Authorization is enforced per endpoint and, on
    state-transition endpoints, per individual transition: the acting role
    must be the declared actor of the specific `to_state` being requested,
    not merely a role allowed on the endpoint as a whole."

    Design: Corner/rbac/lab_agent_cannot_certify_campaign
    """
    set_clock("2026-09-01T00:00:00Z")
    system = create_voting_system()
    lab = create_test_laboratory()
    campaign = create_campaign(system["id"], lab["id"])
    begin_campaign_testing(campaign["id"], lab["id"])

    resp = api.transition_certification_campaign(
        campaign["id"],
        campaign_transition_payload("CERTIFIED"),
        make_lab_agent_headers(lab["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    assert get_campaign(campaign["id"])["status"] == "IN_TEST"
