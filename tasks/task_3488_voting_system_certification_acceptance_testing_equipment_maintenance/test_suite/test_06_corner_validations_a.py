"""Breadth probes over the validation pipeline: authentication, schema
ordering, segregation of duties, uniqueness, aggregate gates, lifecycle
gates, and fiscal/temporal boundaries (first half)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    begin_campaign_testing,
    budget_adjustment_payload,
    certify_campaign,
    certify_la_test,
    create_campaign,
    create_campaign_payload,
    create_custody_transfer_payload,
    create_election_definition,
    create_equipment_unit,
    create_equipment_unit_payload,
    create_jurisdiction,
    create_la_test,
    create_official,
    create_official_payload,
    create_post_election_audit_payload,
    create_procurement_payload,
    create_test_laboratory,
    create_test_laboratory_payload,
    create_voting_system,
    election_definition_transition_payload,
    get_election_definition,
    get_equipment_unit,
    make_election_official_headers,
    open_audit,
    record_acceptance_test,
    set_clock,
    set_official_status,
    setup_certified_jurisdiction,
    setup_certified_system,
    setup_election_definition,
    setup_procurement,
    store_layout,
    transition_election_definition,
    transfer_custody,
    validate_error,
    validate_success,
    withdraw_campaign,
)

ADMIN = TEST_USERS["platform_admin_headers"]
AUTHORITY = TEST_USERS["certification_authority_headers"]
VENDOR = TEST_USERS["vendor_rep_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_missing_auth_headers_returns_401_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or presenting an
    `X-User-Role` value that is not one of the declared roles, is rejected
    with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`." and "The `error_id` is a
    unique, machine-readable string that identifies the specific error."

    Design: Corner/validations/missing_auth_headers_returns_401_unauthenticated
    """
    set_clock("2026-09-01T00:00:00Z")
    system = create_voting_system()
    resp = api.get_voting_system(system["id"], {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
    body = resp.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_UNAUTHENTICATED"
    assert body["data"]["message"]
    assert body["meta"]["api_request_id"]


def test_schema_validation_precedes_body_fk_existence(api):
    """PRD §2.7: "When several checks could fail on the same request, the
    failure with the lowest priority number wins — the earlier rejection
    masks the later ones."
    PRD §2.7: "4. **Body well-formedness** — required fields present, no
    undeclared fields, enum values in range, types correct, integer bounds
    respected (`quantity` at least 1, ...)"

    Design: Corner/validations/schema_validation_precedes_body_fk_existence
    """
    base = setup_certified_jurisdiction()
    off1 = base["officials"][0]["id"]
    resp = api.create_procurement(
        create_procurement_payload(
            base["jurisdiction"]["id"],
            base["system"]["id"],
            NON_EXISTENT_UUID,
            quantity=0,
            unit_price_cents=5,
        ),
        make_election_official_headers(off1),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert resp.json()["data"]["error_id"] != "ERR_CERTIFICATE_NOT_FOUND", (
        "schema (priority 4) masks body-FK existence (priority 5)"
    )


def test_sod_conductor_cannot_certify_or_challenge_own_test(api):
    """PRD §3.6: "`CONDUCTED` → `CERTIFIED` must be performed by an official
    of the jurisdiction whose `X-User-ID` differs from `conducted_by`
    (`ERR_SEGREGATION_OF_DUTIES`); success stamps `certified_by` with the
    certifying official. Challenging (`CONDUCTED` → `CHALLENGED`) is likewise
    forbidden to the conductor on the manual path; the same transition also
    arrives by the recertification cascade of §3.9, which does not evaluate
    segregation of duties."

    Design: Corner/validations/sod_conductor_cannot_certify_or_challenge_own_test
    """
    base = setup_election_definition("PROGRAMMED")
    off1 = base["officials"][0]["id"]
    off2 = base["officials"][1]["id"]
    la_test = create_la_test(base["definition"]["id"], off1)

    resp = api.transition_la_test(
        la_test["id"], {"to_state": "CERTIFIED"}, make_election_official_headers(off1)
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    resp = api.transition_la_test(
        la_test["id"], {"to_state": "CHALLENGED"}, make_election_official_headers(off1)
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    certified = certify_la_test(la_test["id"], off2)
    assert certified["status"] == "CERTIFIED"
    assert certified["certified_by"] == off2


def test_transfer_to_ineligible_official_rejected(api):
    """PRD §3.7: "the payload's `to_official_id` must differ from
    `from_official_id` (`ERR_SELF_TRANSFER`), must resolve
    (`ERR_OFFICIAL_NOT_FOUND`), must be `ACTIVE` (`ERR_OFFICIAL_INACTIVE`),
    and must belong to the unit's jurisdiction
    (`ERR_OFFICIAL_JURISDICTION_MISMATCH`)."

    Design: Corner/validations/transfer_to_ineligible_official_rejected
    """
    base = setup_certified_jurisdiction()
    off1 = base["officials"][0]["id"]
    off2 = base["officials"][1]["id"]
    set_official_status(off2, "INACTIVE")
    jur_b = create_jurisdiction(name="Other County", state_code="CA",
                                budget_total_cents=5_000_000)
    off3 = create_official(jur_b["id"], full_name="Cara Otr")
    unit = create_equipment_unit(
        base["jurisdiction"]["id"], base["system"]["id"], off1, serial_number="SN-1001"
    )

    resp = api.create_custody_transfer(
        unit["id"],
        create_custody_transfer_payload(off2, seal_number="SEAL-X1"),
        make_election_official_headers(off1),
    )
    validate_error(resp, ApiErrorId.ERR_OFFICIAL_INACTIVE)
    resp = api.create_custody_transfer(
        unit["id"],
        create_custody_transfer_payload(off3["id"], seal_number="SEAL-X2"),
        make_election_official_headers(off1),
    )
    validate_error(resp, ApiErrorId.ERR_OFFICIAL_JURISDICTION_MISMATCH)
    assert get_equipment_unit(unit["id"])["current_custodian_id"] == off1


def test_uniqueness_constraints_enforced(api):
    """PRD §2.7: "13. **Uniqueness** — `lab_code` globally
    (`ERR_DUPLICATE_LAB_CODE`), `serial_number` globally
    (`ERR_DUPLICATE_SERIAL`), `badge_no` within a jurisdiction
    (`ERR_DUPLICATE_BADGE`), `seal_number` across a unit's transfer history
    (`ERR_SEAL_NUMBER_REUSED`) — all 409."

    Design: Corner/validations/uniqueness_constraints_enforced
    """
    base = setup_certified_jurisdiction()
    off1 = base["officials"][0]["id"]
    jur_id = base["jurisdiction"]["id"]
    create_equipment_unit(jur_id, base["system"]["id"], off1, serial_number="SN-1001")

    resp = api.create_equipment_unit(
        create_equipment_unit_payload(
            jur_id, base["system"]["id"], off1, serial_number="SN-1001"
        ),
        make_election_official_headers(off1),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SERIAL)

    resp = api.create_official(
        jur_id,
        create_official_payload(
            full_name="Dup Badge", badge_no=base["officials"][0]["badge_no"]
        ),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_BADGE)

    resp = api.create_test_laboratory(
        create_test_laboratory_payload(
            lab_code=base["lab"]["lab_code"],
            lab_name="Duplicate Lab",
            accreditation_scope="FEDERAL",
        ),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_LAB_CODE)


def test_seal_number_reuse_rejected(api):
    """PRD §3.7: "The `seal_number` must not appear in any prior transfer of
    this unit (`ERR_SEAL_NUMBER_REUSED`)."

    Design: Corner/validations/seal_number_reuse_rejected
    """
    base = setup_certified_jurisdiction()
    off1 = base["officials"][0]["id"]
    off2 = base["officials"][1]["id"]
    unit = create_equipment_unit(
        base["jurisdiction"]["id"], base["system"]["id"], off1, serial_number="SN-1001"
    )
    transfer_custody(unit["id"], off1, off2, seal_number="SEAL-R1", seal_intact=True)

    resp = api.create_custody_transfer(
        unit["id"],
        create_custody_transfer_payload(off1, seal_number="SEAL-R1"),
        make_election_official_headers(off2),
    )
    validate_error(resp, ApiErrorId.ERR_SEAL_NUMBER_REUSED)
    assert get_equipment_unit(unit["id"])["current_custodian_id"] == off2, (
        "the rejected transfer moved nothing"
    )


def test_campaign_already_active_rejected(api):
    """PRD §3.2: "no other campaign for the same system may be in
    `SUBMITTED`, `IN_TEST`, or `DEFICIENCIES_FILED`
    (`ERR_CAMPAIGN_ALREADY_ACTIVE`)."

    Design: Corner/validations/campaign_already_active_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    system = create_voting_system()
    lab = create_test_laboratory()
    campaign = create_campaign(system["id"], lab["id"])

    resp = api.create_certification_campaign(
        create_campaign_payload(system["id"], lab["id"],
                                guidelines_baseline="VVSG_1_1"),
        VENDOR,
    )
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_ALREADY_ACTIVE)

    withdraw_campaign(campaign["id"])
    resp = api.create_certification_campaign(
        create_campaign_payload(system["id"], lab["id"],
                                guidelines_baseline="VVSG_1_1"),
        VENDOR,
    )
    second = validate_success(resp, 201)
    assert second["status"] == "SUBMITTED", (
        "WITHDRAWN is terminal, so it no longer blocks a fresh campaign"
    )


def test_audit_already_active_rejected(api):
    """PRD §3.10: "The definition must be `CANVASSING`, and at most one audit
    per definition may be non-terminal — in `INITIATED` or `FINDINGS_FILED`
    (`ERR_AUDIT_ALREADY_ACTIVE`)."

    Design: Corner/validations/audit_already_active_rejected
    """
    base = setup_election_definition("CANVASSING")
    ed_id = base["definition"]["id"]
    open_audit(ed_id, audit_type="COMPLIANCE")

    resp = api.create_post_election_audit(
        create_post_election_audit_payload(ed_id, audit_type="FULL_RECOUNT"),
        AUDITOR,
    )
    validate_error(resp, ApiErrorId.ERR_AUDIT_ALREADY_ACTIVE)


def test_lab_eligibility_gates(api):
    """PRD §3.2: "the laboratory must be `ACCREDITED` (`ERR_LAB_SUSPENDED`);
    the laboratory's `accreditation_scope` must cover the campaign's scope —
    a state campaign requires a `STATE` or `DUAL` laboratory, a federal-only
    campaign requires `FEDERAL` or `DUAL` (`ERR_LAB_SCOPE_MISMATCH`)".

    Design: Corner/validations/lab_eligibility_gates
    """
    set_clock("2026-09-01T00:00:00Z")
    system = create_voting_system()
    lab_federal = create_test_laboratory(
        lab_name="Federal Only Lab", accreditation_scope="FEDERAL",
        max_concurrent_campaigns=2,
    )
    lab_suspended = create_test_laboratory(lab_name="Suspendable Lab")
    resp = api.transition_test_laboratory(
        lab_suspended["id"], {"to_state": "SUSPENDED"}, AUTHORITY
    )
    validate_success(resp)

    resp = api.create_certification_campaign(
        create_campaign_payload(system["id"], lab_federal["id"], state_code="CA"),
        VENDOR,
    )
    validate_error(resp, ApiErrorId.ERR_LAB_SCOPE_MISMATCH)

    resp = api.create_certification_campaign(
        create_campaign_payload(system["id"], lab_suspended["id"], state_code=None),
        VENDOR,
    )
    validate_error(resp, ApiErrorId.ERR_LAB_SUSPENDED)


def test_system_lifecycle_gates(api):
    """PRD §3.7: "Registration requires the voting system to be `FIELDED`
    (`ERR_SYSTEM_NOT_FIELDED`)".
    PRD §3.2: "the system must not be `RETIRED` (`ERR_SYSTEM_RETIRED`)".
    PRD §3.1: "A direct `REGISTERED` to `RETIRED` transition is not offered
    at all."

    Design: Corner/validations/system_lifecycle_gates
    """
    set_clock("2026-09-01T00:00:00Z")
    system_a = create_voting_system()  # stays REGISTERED
    lab = create_test_laboratory()
    system_b = create_voting_system(
        vendor_name="Vendor B", model_name="BMD-9",
        software_baseline_version="3.0.0", hardware_class="BALLOT_MARKING_DEVICE",
    )
    campaign_b = create_campaign(system_b["id"], lab["id"], state_code=None)
    begin_campaign_testing(campaign_b["id"], lab["id"])
    certify_campaign(campaign_b["id"])  # system B becomes FIELDED
    jurisdiction = create_jurisdiction()
    official = create_official(jurisdiction["id"])

    resp = api.create_equipment_unit(
        create_equipment_unit_payload(
            jurisdiction["id"], system_a["id"], official["id"],
            serial_number="SN-2001",
        ),
        make_election_official_headers(official["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SYSTEM_NOT_FIELDED)

    resp = api.transition_voting_system(system_b["id"], {"to_state": "RETIRED"}, ADMIN)
    validate_success(resp)
    resp = api.create_certification_campaign(
        create_campaign_payload(system_b["id"], lab["id"], state_code=None), VENDOR
    )
    validate_error(resp, ApiErrorId.ERR_SYSTEM_RETIRED)

    resp = api.transition_voting_system(system_a["id"], {"to_state": "RETIRED"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_certificate_system_mismatch_rejected(api):
    """PRD §3.4: "Placement evaluates its guards in pipeline order: the body
    references resolve first (`ERR_JURISDICTION_NOT_FOUND`,
    `ERR_SYSTEM_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`); then the
    certificate must belong to the named system
    (`ERR_CERTIFICATE_SYSTEM_MISMATCH`)".

    Design: Corner/validations/certificate_system_mismatch_rejected
    """
    base = setup_certified_system(state_code="CA")
    cert_a = base["certificate"]
    lab = base["lab"]
    system_b = create_voting_system(
        vendor_name="Vendor B", model_name="CT-1",
        software_baseline_version="1.2.0", hardware_class="CENTRAL_TABULATOR",
    )
    campaign_b = create_campaign(system_b["id"], lab["id"], state_code=None)
    begin_campaign_testing(campaign_b["id"], lab["id"])
    certify_campaign(campaign_b["id"])
    jurisdiction = create_jurisdiction(state_code="CA")
    official = create_official(jurisdiction["id"])

    resp = api.create_procurement(
        create_procurement_payload(
            jurisdiction["id"], system_b["id"], cert_a["id"],
            quantity=1, unit_price_cents=1000,
        ),
        make_election_official_headers(official["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CERTIFICATE_SYSTEM_MISMATCH)


def test_budget_fiscal_gates(api):
    """PRD §3.4: "and finally the fiscal check of §2.8 — the computed
    `total_price_cents` (the `quantity` multiplied by the `unit_price_cents`)
    must not exceed the jurisdiction's `available_cents`
    (`ERR_BUDGET_EXCEEDED`)."
    PRD §2.8: "A `PlatformAdmin` budget adjustment carries a signed
    `delta_cents` and a `reason`, adds `delta_cents` to both
    `budget_total_cents` and `available_cents`, and is rejected whenever the
    adjustment would drive `available_cents` below zero."

    Design: Corner/validations/budget_fiscal_gates
    """
    base = setup_certified_system()
    jurisdiction = create_jurisdiction(
        name="Poor County", state_code="CA", budget_total_cents=1_000_000
    )
    official = create_official(jurisdiction["id"])

    resp = api.create_procurement(
        create_procurement_payload(
            jurisdiction["id"], base["system"]["id"], base["certificate"]["id"],
            quantity=10, unit_price_cents=2_500_000,
        ),
        make_election_official_headers(official["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED)

    resp = api.create_budget_adjustment(
        jurisdiction["id"], budget_adjustment_payload(-2_000_000, "clawback"), ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_BUDGET_ADJUSTMENT_INVALID)

    resp = api.create_budget_adjustment(
        jurisdiction["id"], budget_adjustment_payload(500_000, "grant"), ADMIN
    )
    data = validate_success(resp, 201)
    assert data["budget_total_cents"] == 1_500_000
    assert data["available_cents"] == 1_500_000


def test_election_calendar_temporal_gates(api):
    """PRD §3.5: "the `election_date` must be at least 30 days after the
    current logical date at creation (`ERR_ELECTION_DATE_INVALID`)."
    PRD §3.5: "the `election_date` must be at least 14 days after the current
    logical date (`ERR_ELECTION_FREEZE_WINDOW`)."
    PRD §3.5: "Canvassing (`LOCKED` → `CANVASSING`) opens only once the
    current logical date has reached the `election_date`
    (`ERR_ELECTION_NOT_HELD`)."

    Design: Corner/validations/election_calendar_temporal_gates
    """
    base = setup_procurement("ACCEPTED")
    off1 = base["officials"][0]["id"]
    off2 = base["officials"][1]["id"]
    jur_id = base["jurisdiction"]["id"]
    proc_id = base["procurement"]["id"]
    # ED1 carried to LOCKED at the 2026-09-01 boot clock (63 days out).
    ed1 = create_election_definition(jur_id, proc_id, acting_official_id=off1)
    store_layout(ed1["id"], off1)
    transition_election_definition(ed1["id"], "PROGRAMMED", off1)
    la1 = create_la_test(ed1["id"], off1)
    certify_la_test(la1["id"], off2)
    transition_election_definition(ed1["id"], "LA_PASSED", off1)
    transition_election_definition(ed1["id"], "LOCKED", off1)
    # ED2 carried to LA_PASSED.
    ed2 = create_election_definition(jur_id, proc_id, acting_official_id=off1,
                                     name="2026 General B", precinct_count=2)
    store_layout(ed2["id"], off1)
    transition_election_definition(ed2["id"], "PROGRAMMED", off1)
    la2 = create_la_test(
        ed2["id"], off1,
        expected_tallies={"GOV": 5000}, scanned_tallies={"GOV": 5000},
    )
    certify_la_test(la2["id"], off2)
    transition_election_definition(ed2["id"], "LA_PASSED", off1)

    set_clock("2026-10-24T00:00:00Z")

    resp = api.create_election_definition(
        {
            "jurisdiction_id": jur_id,
            "procurement_id": proc_id,
            "name": "Snap Election",
            "election_date": "2026-11-10",
            "precinct_count": 1,
        },
        make_election_official_headers(off1),
    )
    validate_error(resp, ApiErrorId.ERR_ELECTION_DATE_INVALID)

    resp = api.transition_election_definition(
        ed1["id"], election_definition_transition_payload("CANVASSING"),
        make_election_official_headers(off1),
    )
    validate_error(resp, ApiErrorId.ERR_ELECTION_NOT_HELD)

    resp = api.transition_election_definition(
        ed2["id"], election_definition_transition_payload("LOCKED"),
        make_election_official_headers(off1),
    )
    validate_error(resp, ApiErrorId.ERR_ELECTION_FREEZE_WINDOW)

    assert get_election_definition(ed1["id"])["status"] == "LOCKED", (
        "the same lock succeeded outside the freeze window"
    )
