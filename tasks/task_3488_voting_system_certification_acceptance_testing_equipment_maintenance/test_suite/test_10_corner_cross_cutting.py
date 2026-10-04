"""Breadth probes over optimistic concurrency, version pinning, and
immediate read-after-write consistency."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_jurisdiction_ledger_invariant,
    create_election_definition,
    create_jurisdiction,
    create_procurement,
    create_software_modification_payload,
    create_voting_system,
    get_certificate,
    get_jurisdiction,
    get_procurement,
    get_voting_system,
    make_election_official_headers,
    put_layout_payload,
    set_clock,
    setup_certified_jurisdiction,
    setup_procurement,
    transition_certificate,
    validate_error,
    validate_success,
)

VENDOR = TEST_USERS["vendor_rep_headers"]


def test_occ_layout_write_stale_version_rejected(api):
    """PRD §2.6: "**Storing a ballot layout** against an election definition
    requires the request to carry `expected_election_definition_version`
    equal to the definition's current `version`. Each stored layout
    legitimately supersedes the prior content (`layout_revision` increments),
    so a writer holding a stale base version must re-read rather than
    silently overwrite another writer's layout. A mismatch is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_layout_write_stale_version_rejected
    """
    base = setup_procurement("ACCEPTED")
    off1 = base["officials"][0]["id"]
    definition = create_election_definition(
        base["jurisdiction"]["id"], base["procurement"]["id"],
        acting_official_id=off1,
    )
    ed_v = definition["version"]
    headers = make_election_official_headers(off1)

    resp = api.put_layout(definition["id"], put_layout_payload(ed_v), headers)
    first = validate_success(resp)
    assert first["layout_revision"] == 1
    assert first["version"] == ed_v + 1

    resp = api.put_layout(
        definition["id"],
        put_layout_payload(ed_v, ballot_layout={"contests": [{"code": "SEN", "choices": 2}]}),
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    resp = api.put_layout(
        definition["id"],
        put_layout_payload(ed_v + 1,
                           ballot_layout={"contests": [{"code": "SEN", "choices": 2}]}),
        headers,
    )
    third = validate_success(resp)
    assert third["layout_revision"] == 2


def test_occ_modification_create_stale_version_rejected(api):
    """PRD §2.6: "**Proposing a software modification** against a voting
    system requires `expected_voting_system_version` equal to the system's
    current `version`. Multiple modification proposals against the same
    system are individually legitimate, so a stale-baseline proposal is
    rejected purely on the version check rather than on any state
    precondition, with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.9: "A proposal enters `PROPOSED` with `submitted_at` stamped from
    the logical clock, `classification` null, and `lead_time_days` null;
    creating it increments the voting system's `version`."

    Design: Corner/cross_cutting_layers/occ_modification_create_stale_version_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    system = create_voting_system()
    sys_v = get_voting_system(system["id"])["version"]

    resp = api.create_software_modification(
        create_software_modification_payload(
            system["id"], sys_v,
            description="mod one", component_codes=["AUDIT_LOG_SERVICE"],
        ),
        VENDOR,
    )
    first = validate_success(resp, 201)
    assert first["status"] == "PROPOSED"

    resp = api.create_software_modification(
        create_software_modification_payload(
            system["id"], sys_v,
            description="mod two", component_codes=["SECURITY_MODULE"],
        ),
        VENDOR,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert get_voting_system(system["id"])["version"] == sys_v + 1, (
        "the first proposal bumped the system version, so the replay is stale"
    )


def test_version_pinning_records_placement_certificate_version(api):
    """PRD §3.4: "A placed procurement pins the certificate's `version` at
    that instant into `certificate_version_pinned`, which is never rewritten,
    starts with `cert_hold` false, enters `PLACED`, and encumbers its total
    against the jurisdiction ledger."

    Design: Corner/cross_cutting_layers/version_pinning_records_placement_certificate_version
    """
    base = setup_certified_jurisdiction()
    cert = base["certificate"]
    cert_version_at_placement = cert["version"]
    off1 = base["officials"][0]["id"]
    procurement = create_procurement(
        base["jurisdiction"]["id"], base["system"]["id"], cert["id"],
        acting_official_id=off1,
    )
    assert procurement["certificate_version_pinned"] == cert_version_at_placement

    transition_certificate(cert["id"], "SUSPENDED", reason="audit")
    transition_certificate(cert["id"], "ACTIVE")
    assert get_certificate(cert["id"])["version"] == cert_version_at_placement + 2
    assert get_procurement(procurement["id"])["certificate_version_pinned"] == (
        cert_version_at_placement
    ), "later certificate mutations never rewrite the placement-time pin"


def test_immediate_read_after_write_consistency(api):
    """PRD §3.1: "A `PlatformAdmin` creates a **jurisdiction** with a display
    `name`, a `state_code` of exactly two uppercase letters, and a
    non-negative `budget_total_cents`; at creation `available_cents` equals
    `budget_total_cents` while `encumbered_cents` and `spent_cents` start at
    zero, in line with the ledger invariant of §2.8."

    Design: Corner/consistency_model/immediate_read_after_write_consistency
    """
    set_clock("2026-09-01T00:00:00Z")
    created = create_jurisdiction(
        name="Consistent County", state_code="NV", budget_total_cents=777_000
    )
    data = get_jurisdiction(created["id"])
    assert data["name"] == "Consistent County"
    assert data["state_code"] == "NV"
    assert data["budget_total_cents"] == 777_000
    assert data["available_cents"] == 777_000
    assert data["encumbered_cents"] == 0
    assert data["spent_cents"] == 0
    assert_jurisdiction_ledger_invariant(data)
