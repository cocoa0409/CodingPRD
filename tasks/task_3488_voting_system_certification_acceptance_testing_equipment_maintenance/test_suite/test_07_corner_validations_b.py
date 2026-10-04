"""Breadth probes over the validation pipeline: lead times, recertification
gates, paper compatibility, deficiency arithmetic, acceptance gates, custody
gates, entity-backed ownership, certificate expiry, and body-FK existence
(second half)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    apply_modification,
    begin_campaign_testing,
    campaign_transition_payload,
    certify_la_test,
    classify_modification_de_minimis,
    classify_modification_recertification,
    create_campaign,
    create_campaign_payload,
    create_custody_transfer_payload,
    create_election_definition,
    create_equipment_unit,
    create_jurisdiction,
    create_la_test,
    create_official,
    create_post_election_audit_payload,
    create_procurement_payload,
    create_test_laboratory,
    create_voting_system,
    create_work_order_payload,
    election_definition_transition_payload,
    file_deficiencies,
    file_findings,
    get_campaign,
    get_certificate,
    get_election_definition,
    get_equipment_unit,
    get_procurement,
    get_voting_system,
    make_election_official_headers,
    make_lab_agent_headers,
    open_audit,
    propose_modification,
    put_layout_payload,
    record_acceptance_test,
    set_clock,
    setup_certified_jurisdiction,
    setup_certified_system,
    setup_election_definition,
    setup_procurement,
    store_layout,
    transition_audit,
    transition_certificate,
    transition_election_definition,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
AUTHORITY = TEST_USERS["certification_authority_headers"]
VENDOR = TEST_USERS["vendor_rep_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_lead_time_not_elapsed_blocks_apply(api):
    """PRD §3.9: "the transition stamps `classified_at` and computes
    `lead_time_days` from pre-classification state in a fixed order: start
    from a base of 30 days; if `component_codes` touches
    `TABULATION_FIRMWARE` or `BALLOT_LAYOUT_ENGINE`, add 60 days; if the
    system has a certificate with `scope` `FEDERAL` in `ACTIVE` or
    `SUSPENDED` status — evaluated strictly before any suspension the
    classification itself is about to cause — add 45 days."
    PRD §3.9: "the current logical instant must be at least `classified_at`
    plus `lead_time_days` days (`ERR_LEAD_TIME_NOT_ELAPSED`)."
    PRD §3.9: "Going effective writes `new_baseline_version` onto the voting
    system's `software_baseline_version` (bumping the system's `version`)".

    Design: Corner/validations/lead_time_not_elapsed_blocks_apply
    """
    base = setup_certified_system()  # STATE certificate -> no federal add
    mod = propose_modification(
        base["system"]["id"],
        description="audit log rotation tuning",
        component_codes=["AUDIT_LOG_SERVICE"],
    )
    mod = classify_modification_de_minimis(mod["id"])
    assert mod["lead_time_days"] == 30, "base only: no scope-touching code, no FEDERAL cert"

    set_clock("2026-09-11T00:00:00Z")
    resp = api.transition_software_modification(
        mod["id"],
        {"to_state": "EFFECTIVE", "new_baseline_version": "1.0.1"},
        VENDOR,
    )
    validate_error(resp, ApiErrorId.ERR_LEAD_TIME_NOT_ELAPSED)

    set_clock("2026-10-01T00:00:00Z")
    applied = apply_modification(mod["id"], "1.0.1")
    assert applied["status"] == "EFFECTIVE", "day 30 of 30 satisfies the gate"
    assert get_voting_system(base["system"]["id"])["software_baseline_version"] == "1.0.1"


def test_recert_apply_requires_newer_certified_campaign(api):
    """PRD §3.9: "The recertification path demands more: a certification
    campaign for the same system must have reached `CERTIFIED` with a
    `completed_at` later than the modification's `submitted_at`
    (`ERR_RECERTIFICATION_CAMPAIGN_REQUIRED`)."

    Design: Corner/validations/recert_apply_requires_newer_certified_campaign
    """
    base = setup_certified_system()  # campaign certified at 2026-09-01
    mod = propose_modification(
        base["system"]["id"],
        description="firmware 2.0",
        component_codes=["TABULATION_FIRMWARE"],
    )
    mod = classify_modification_recertification(mod["id"])
    assert mod["lead_time_days"] == 90, "30 base + 60 scope-touching; STATE cert adds nothing"

    set_clock("2026-12-01T00:00:00Z")  # past the 90-day lead
    resp = api.transition_software_modification(
        mod["id"],
        {"to_state": "EFFECTIVE", "new_baseline_version": "2.0.0"},
        VENDOR,
    )
    validate_error(resp, ApiErrorId.ERR_RECERTIFICATION_CAMPAIGN_REQUIRED)
    assert get_certificate(base["certificate"]["id"])["status"] == "SUSPENDED", (
        "no compensation fires on a rejected apply"
    )


def test_escalation_requires_critical_finding(api):
    """PRD §3.10: "`CLOSED_CONFIRMED` carries no further precondition.
    `CLOSED_ESCALATED` requires at least one critical finding
    (`critical_findings` of 0 is rejected with
    `ERR_ESCALATION_REQUIRES_CRITICAL`)".

    Design: Corner/validations/escalation_requires_critical_finding
    """
    base = setup_election_definition("CANVASSING")
    audit = open_audit(base["definition"]["id"], audit_type="COMPLIANCE")
    file_findings(audit["id"], 0, 2, 1)

    resp = api.transition_post_election_audit(
        audit["id"], {"to_state": "CLOSED_ESCALATED"}, AUDITOR
    )
    validate_error(resp, ApiErrorId.ERR_ESCALATION_REQUIRES_CRITICAL)

    closed = transition_audit(audit["id"], "CLOSED_CONFIRMED")
    assert closed["status"] == "CLOSED_CONFIRMED", "the same findings close fine as confirmed"


def test_paper_outside_scanner_range_rejected(api):
    """PRD §3.5: "Paper stock is checked against the scanner's physical
    envelope — weight within 80 to 120 gsm and thickness within 60 to 250
    microns — and an `OPTICAL_SCANNER` system accepts only `UNCOATED` paper;
    `COATED` paper on such a system, or any out-of-range dimension, is
    `ERR_PAPER_INCOMPATIBLE`."
    PRD §3.5: "Each successful store supersedes the prior layout and
    increments `layout_revision` by 1".

    Design: Corner/validations/paper_outside_scanner_range_rejected
    """
    base = setup_procurement("ACCEPTED")  # OPTICAL_SCANNER system
    off1 = base["officials"][0]["id"]
    definition = create_election_definition(
        base["jurisdiction"]["id"], base["procurement"]["id"],
        acting_official_id=off1,
    )
    ed_v = definition["version"]

    resp = api.put_layout(
        definition["id"],
        put_layout_payload(ed_v, paper_thickness_microns=300),
        make_election_official_headers(off1),
    )
    validate_error(resp, ApiErrorId.ERR_PAPER_INCOMPATIBLE)

    resp = api.put_layout(
        definition["id"],
        put_layout_payload(ed_v, paper_coating="COATED"),
        make_election_official_headers(off1),
    )
    validate_error(resp, ApiErrorId.ERR_PAPER_INCOMPATIBLE)

    stored = store_layout(definition["id"], off1)
    assert stored["layout_revision"] == 1, "failed writes bumped nothing"


def test_deficiency_resolution_must_be_exact(api):
    """PRD §3.2: "Each count must be non-negative and their total at least 1,
    otherwise `ERR_DEFICIENCY_COUNTS_INVALID`."
    PRD §3.2: "resolution is all-or-nothing: each resolved count must exactly
    equal the campaign's current open count, otherwise
    `ERR_DEFICIENCY_COUNTS_INVALID`."

    Design: Corner/validations/deficiency_resolution_must_be_exact
    """
    set_clock("2026-09-01T00:00:00Z")
    system = create_voting_system()
    lab = create_test_laboratory()
    campaign = create_campaign(system["id"], lab["id"])
    begin_campaign_testing(campaign["id"], lab["id"])

    resp = api.transition_certification_campaign(
        campaign["id"],
        campaign_transition_payload(
            "DEFICIENCIES_FILED", critical_count=0, major_count=0, minor_count=0
        ),
        make_lab_agent_headers(lab["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DEFICIENCY_COUNTS_INVALID)

    file_deficiencies(campaign["id"], lab["id"], 0, 1, 2)
    resp = api.transition_certification_campaign(
        campaign["id"],
        campaign_transition_payload(
            "SUBMITTED", resolved_critical=0, resolved_major=1, resolved_minor=1
        ),
        VENDOR,
    )
    validate_error(resp, ApiErrorId.ERR_DEFICIENCY_COUNTS_INVALID)

    data = get_campaign(campaign["id"])
    assert data["status"] == "DEFICIENCIES_FILED"
    assert data["open_critical_count"] == 0
    assert data["open_major_count"] == 1
    assert data["open_minor_count"] == 2


def test_accept_gate_requires_complete_passing_tests(api):
    """PRD §3.4: "The accept decision (`ACCEPTANCE_TESTING` → `ACCEPTED`)
    demands all of the following: ... at least one `HARDWARE_DIAGNOSTIC` test
    and at least one `BALLOT_SCAN_CALIBRATION` test exist for the procurement
    (`ERR_ACCEPTANCE_TESTS_INCOMPLETE`); and no acceptance test of the
    procurement has `result` `FAIL` (`ERR_ACCEPTANCE_TEST_FAILURES_PRESENT`)."

    Design: Corner/validations/accept_gate_requires_complete_passing_tests
    """
    base = setup_procurement("ACCEPTANCE_TESTING")
    off1 = base["officials"][0]["id"]
    proc_id = base["procurement"]["id"]
    record_acceptance_test(proc_id, off1, test_type="HARDWARE_DIAGNOSTIC")

    resp = api.transition_procurement(
        proc_id, {"to_state": "ACCEPTED"}, make_election_official_headers(off1)
    )
    validate_error(resp, ApiErrorId.ERR_ACCEPTANCE_TESTS_INCOMPLETE)

    failing = record_acceptance_test(
        proc_id, off1,
        test_type="BALLOT_SCAN_CALIBRATION",
        critical_defects=0, major_defects=2, minor_defects=3,
    )
    assert failing["result"] == "FAIL", "index 29 > 20"
    resp = api.transition_procurement(
        proc_id, {"to_state": "ACCEPTED"}, make_election_official_headers(off1)
    )
    validate_error(resp, ApiErrorId.ERR_ACCEPTANCE_TEST_FAILURES_PRESENT)
    assert get_procurement(proc_id)["status"] == "ACCEPTANCE_TESTING"


def test_program_requires_stored_layout(api):
    """PRD §3.5: "Programming (`DRAFT` → `PROGRAMMED`) requires a complete
    definition: `ballot_layout` stored and `paper_weight_gsm`,
    `paper_thickness_microns`, and `paper_coating` all non-null, otherwise
    `ERR_LAYOUT_REQUIRED`."

    Design: Corner/validations/program_requires_stored_layout
    """
    base = setup_procurement("ACCEPTED")
    off1 = base["officials"][0]["id"]
    definition = create_election_definition(
        base["jurisdiction"]["id"], base["procurement"]["id"],
        acting_official_id=off1,
    )
    resp = api.transition_election_definition(
        definition["id"],
        election_definition_transition_payload("PROGRAMMED"),
        make_election_official_headers(off1),
    )
    validate_error(resp, ApiErrorId.ERR_LAYOUT_REQUIRED)
    assert get_election_definition(definition["id"])["status"] == "DRAFT"


def test_la_passed_requires_certified_pass_test(api):
    """PRD §3.5: "Marking logic-and-accuracy passed (`PROGRAMMED` →
    `LA_PASSED`) requires at least one logic-and-accuracy test of this
    definition in `CERTIFIED` status with `result` `PASS`
    (`ERR_LA_TEST_NOT_CERTIFIED`; §3.6)."

    Design: Corner/validations/la_passed_requires_certified_pass_test
    """
    base = setup_election_definition("PROGRAMMED")
    off1 = base["officials"][0]["id"]
    off2 = base["officials"][1]["id"]
    ed_id = base["definition"]["id"]
    la_test = create_la_test(ed_id, off1)
    assert la_test["result"] == "PASS" and la_test["status"] == "CONDUCTED"

    resp = api.transition_election_definition(
        ed_id,
        election_definition_transition_payload("LA_PASSED"),
        make_election_official_headers(off1),
    )
    validate_error(resp, ApiErrorId.ERR_LA_TEST_NOT_CERTIFIED)

    certify_la_test(la_test["id"], off2)
    passed = transition_election_definition(ed_id, "LA_PASSED", off1)
    assert passed["status"] == "LA_PASSED"


def test_audit_open_blocks_close(api):
    """PRD §3.5: "Closing (`CANVASSING` → `CLOSED`) requires every
    post-election audit of the definition to be terminal — `CLOSED_CONFIRMED`
    or `CLOSED_ESCALATED` — otherwise `ERR_AUDIT_OPEN` (§3.10)."

    Design: Corner/validations/audit_open_blocks_close
    """
    base = setup_election_definition("CANVASSING")
    off1 = base["officials"][0]["id"]
    ed_id = base["definition"]["id"]
    audit = open_audit(ed_id, audit_type="RISK_LIMITING")

    resp = api.transition_election_definition(
        ed_id,
        election_definition_transition_payload("CLOSED"),
        make_election_official_headers(off1),
    )
    validate_error(resp, ApiErrorId.ERR_AUDIT_OPEN)

    file_findings(audit["id"], 0, 0, 0)
    transition_audit(audit["id"], "CLOSED_CONFIRMED")
    closed = transition_election_definition(ed_id, "CLOSED", off1)
    assert closed["status"] == "CLOSED"


def test_custody_transfer_gates(api):
    """PRD §3.7: "While a unit is `QUARANTINED`, custody transfers,
    deploy/store transitions, and work-order creation are all rejected with
    `ERR_UNIT_QUARANTINED`."
    PRD §3.7: "the payload's `to_official_id` must differ from
    `from_official_id` (`ERR_SELF_TRANSFER`)".
    PRD §3.7: "The acting official's `X-User-ID` is recorded as
    `from_official_id` and must equal the unit's `current_custodian_id`
    (`ERR_FORBIDDEN_OWNERSHIP`)".

    Design: Corner/validations/custody_transfer_gates
    """
    base = setup_certified_jurisdiction()
    off1 = base["officials"][0]["id"]
    off2 = base["officials"][1]["id"]
    jur_id = base["jurisdiction"]["id"]
    sys_id = base["system"]["id"]
    unit_a = create_equipment_unit(jur_id, sys_id, off1, serial_number="SN-3001")
    unit_b = create_equipment_unit(jur_id, sys_id, off1, serial_number="SN-3002")
    resp = api.transition_equipment_unit(
        unit_b["id"], {"to_state": "QUARANTINED"}, AUTHORITY
    )
    validate_success(resp)

    resp = api.create_custody_transfer(
        unit_b["id"],
        create_custody_transfer_payload(off2, seal_number="SEAL-Q1"),
        make_election_official_headers(off1),
    )
    validate_error(resp, ApiErrorId.ERR_UNIT_QUARANTINED)

    resp = api.create_custody_transfer(
        unit_a["id"],
        create_custody_transfer_payload(off1, seal_number="SEAL-S1"),
        make_election_official_headers(off1),
    )
    validate_error(resp, ApiErrorId.ERR_SELF_TRANSFER)

    resp = api.create_custody_transfer(
        unit_a["id"],
        create_custody_transfer_payload(off1, seal_number="SEAL-S2"),
        make_election_official_headers(off2),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)


def test_entity_backed_ownership_enforced(api):
    """PRD §2.1: "When `X-User-Role` is `LabAgent`, `X-User-ID` is the `id`
    of the acting TestLaboratory; ownership checks on any resource that
    references a TestLaboratory (a certification campaign's `lab_id`) compare
    that field to `X-User-ID`, and a mismatch is rejected with
    `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."
    PRD §2.1: "When `X-User-Role` is `ElectionOfficial`, `X-User-ID` is the
    `id` of the acting ElectionOfficial; ownership checks compare the
    official's `jurisdiction_id` against the jurisdiction that owns the
    target resource (procurement, election definition, equipment unit, or the
    jurisdiction of a work order's unit), and custody-transfer creation
    compares `X-User-ID` against the unit's `current_custodian_id`.
    Mismatches are rejected with `ERR_FORBIDDEN_OWNERSHIP`."

    Design: Corner/validations/entity_backed_ownership_enforced
    """
    base = setup_certified_jurisdiction()
    off1 = base["officials"][0]["id"]
    jur_a = base["jurisdiction"]
    lab_a = base["lab"]
    lab_b = create_test_laboratory(lab_name="Beta Lab")
    jur_b = create_jurisdiction(name="Other County", state_code="NV",
                                budget_total_cents=9_000_000)
    off_b = create_official(jur_b["id"], full_name="Cara Otr")
    # The original campaign is CERTIFIED (terminal), so a second opens cleanly.
    campaign2 = create_campaign(
        base["system"]["id"], lab_a["id"], guidelines_baseline="VVSG_1_1"
    )

    resp = api.transition_certification_campaign(
        campaign2["id"],
        campaign_transition_payload("IN_TEST"),
        make_lab_agent_headers(lab_b["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)

    resp = api.create_procurement(
        create_procurement_payload(
            jur_a["id"], base["system"]["id"], base["certificate"]["id"],
            quantity=1, unit_price_cents=1000,
        ),
        make_election_official_headers(off_b["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)


def test_certificate_expiry_sweep_and_reinstate_block(api):
    """PRD §3.3: "A `CertificationAuthority` may suspend an `ACTIVE`
    certificate (optionally recording a `reason`) and later reinstate it
    (`SUSPENDED` → `ACTIVE`), provided the certificate has not yet reached
    `expires_at` — reinstating at or past expiry is rejected with
    `ERR_CERTIFICATE_EXPIRED`."
    PRD §3.3: "when any certificate read — single or list — observes the
    logical clock at or past `expires_at`, an `ACTIVE` or `SUSPENDED`
    certificate flips to `EXPIRED` and its `version` increments as part of
    that read."

    Design: Corner/validations/certificate_expiry_sweep_and_reinstate_block
    """
    base = setup_certified_system()
    cert_id = base["certificate"]["id"]
    transition_certificate(cert_id, "SUSPENDED", reason="review")

    set_clock("2028-09-01T00:00:00Z")  # past expires_at (2028-08-31)
    resp = api.transition_certificate(cert_id, {"to_state": "ACTIVE"}, AUTHORITY)
    validate_error(resp, ApiErrorId.ERR_CERTIFICATE_EXPIRED)
    assert get_certificate(cert_id)["status"] == "EXPIRED", (
        "the following read applies the lazy sweep and locks the row"
    )


def test_body_fk_existence_errors(api):
    """PRD §2.7: "5. **Body-referenced resources exist** — each foreign key
    in a request body resolves: `voting_system_id` (`ERR_SYSTEM_NOT_FOUND`),
    `lab_id` (`ERR_LAB_NOT_FOUND`), `certificate_id`
    (`ERR_CERTIFICATE_NOT_FOUND`), `jurisdiction_id`
    (`ERR_JURISDICTION_NOT_FOUND`), `to_official_id` or
    `initial_custodian_id` (`ERR_OFFICIAL_NOT_FOUND`), `procurement_id`
    (`ERR_PROCUREMENT_NOT_FOUND`), `election_definition_id`
    (`ERR_ELECTION_DEFINITION_NOT_FOUND`), `equipment_unit_id`
    (`ERR_UNIT_NOT_FOUND`) — all 404."

    Design: Corner/validations/body_fk_existence_errors
    """
    base = setup_procurement("ACCEPTED")
    off1 = base["officials"][0]["id"]
    jur_id = base["jurisdiction"]["id"]
    sys_id = base["system"]["id"]
    cert_id = base["certificate"]["id"]
    unit = create_equipment_unit(jur_id, sys_id, off1, serial_number="SN-1001")
    bogus = NON_EXISTENT_UUID
    off1_headers = make_election_official_headers(off1)

    resp = api.create_procurement(
        create_procurement_payload(jur_id, sys_id, bogus, quantity=1,
                                   unit_price_cents=100),
        off1_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CERTIFICATE_NOT_FOUND)

    resp = api.create_procurement(
        create_procurement_payload(jur_id, bogus, cert_id, quantity=1,
                                   unit_price_cents=100),
        off1_headers,
    )
    validate_error(resp, ApiErrorId.ERR_SYSTEM_NOT_FOUND)

    resp = api.create_certification_campaign(
        create_campaign_payload(sys_id, bogus, state_code=None), VENDOR
    )
    validate_error(resp, ApiErrorId.ERR_LAB_NOT_FOUND)

    resp = api.create_election_definition(
        {
            "jurisdiction_id": jur_id,
            "procurement_id": bogus,
            "name": "Ghost",
            "election_date": "2026-11-03",
            "precinct_count": 1,
        },
        off1_headers,
    )
    validate_error(resp, ApiErrorId.ERR_PROCUREMENT_NOT_FOUND)

    resp = api.create_work_order(
        create_work_order_payload(bogus, work_type="REPAIR"), off1_headers
    )
    validate_error(resp, ApiErrorId.ERR_UNIT_NOT_FOUND)

    resp = api.create_post_election_audit(
        create_post_election_audit_payload(bogus, audit_type="COMPLIANCE"), AUDITOR
    )
    validate_error(resp, ApiErrorId.ERR_ELECTION_DEFINITION_NOT_FOUND)

    resp = api.create_custody_transfer(
        unit["id"],
        create_custody_transfer_payload(bogus, seal_number="SEAL-FK"),
        off1_headers,
    )
    validate_error(resp, ApiErrorId.ERR_OFFICIAL_NOT_FOUND)

    resp = api.create_procurement(
        create_procurement_payload(bogus, sys_id, cert_id, quantity=1,
                                   unit_price_cents=100),
        off1_headers,
    )
    validate_error(resp, ApiErrorId.ERR_JURISDICTION_NOT_FOUND)
