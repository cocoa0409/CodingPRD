"""Vendor qualification: the dual-variant derivation from status plus defect
count, the audit-overlap window, and the disqualification cascade into
procured component lots."""

from test_helpers import (
    ApiErrorId,
    APPLICANT,
    AUDITOR,
    NON_EXISTENT_UUID,
    SCM,
    assert_component_lot,
    create_adequate_program,
    create_component_lot,
    create_dca,
    create_qualification,
    create_vendor,
    qualification_payload,
    read_component_lot,
    read_qualification,
    read_vendor,
    test_result_payload,
    validate_error,
    validate_success,
)


def _conditionally_qualified(api, docket, name, defects):
    """A vendor whose qualification completed with the given defect count."""
    vendor = create_vendor(api, name=name)
    qual = create_qualification(api, vendor["id"], defects_found=defects)
    qual = validate_success(api.complete_audit(vendor["id"], qual["id"], AUDITOR))
    return vendor, qual


class TestQualificationVariant:
    """qualified_variant derives from status AND defects, never status alone."""

    def test_conditionally_qualified_with_three_defects_is_unqualified(self, api):
        """PRD §3.4: "The boundary is deliberate — exactly 3 defects on a
        conditionally qualified record yields `UNQUALIFIED`, not a generous
        reading of the status alone."

        Design: Difficulty/dual_variant_calc/qualification_variant_status_plus_defects
        """
        vendor, qual = _conditionally_qualified(api, "52-500", "Acme Nuclear", defects=3)
        assert qual["status"] == "CONDITIONALLY_QUALIFIED"
        assert qual["qualified_variant"] == "UNQUALIFIED"
        assert read_vendor(api, vendor["id"])["qualified"] is False

    def test_conditionally_qualified_with_two_defects_stays_conditional(self, api):
        """PRD §3.4: "The derived `qualified_variant` on each qualification
        pins this rule: the variant is `FULLY_QUALIFIED` when the status is
        `FULLY_QUALIFIED`; otherwise `CONDITIONALLY_QUALIFIED` when the status
        is `CONDITIONALLY_QUALIFIED` and defects are fewer than 3; otherwise
        `UNQUALIFIED`."

        Design: Difficulty/dual_variant_calc/qualification_variant_status_plus_defects
        """
        vendor, qual = _conditionally_qualified(api, "52-501", "Acme Two", defects=2)
        assert qual["status"] == "CONDITIONALLY_QUALIFIED"
        assert qual["qualified_variant"] == "CONDITIONALLY_QUALIFIED"
        # Conditional is never enough for the vendor's qualified flag.
        assert read_vendor(api, vendor["id"])["qualified"] is False


class TestAuditOverlap:
    """Audits of one vendor may not bunch up within fourteen days."""

    def test_nine_days_apart_rejected_fifteen_days_supersedes(self, api):
        """PRD §3.4: "the proposed `audit_date` must not fall within 14 days,
        in either direction, of any non-superseded qualification audit of the
        same vendor; an overlapping schedule is rejected with
        `ERR_AUDIT_OVERLAP` (HTTP 409)."
        PRD §3.4: "Opening a new cycle while the vendor already has an active
        qualification supersedes the old one — the prior `AUDIT_SCHEDULED`,
        `CONDITIONALLY_QUALIFIED`, or `FULLY_QUALIFIED` record transitions to
        terminal `SUPERSEDED`, and both vendor flags are recomputed."

        Design: Difficulty/resource_temporal_overlap/vendor_audit_overlap_plus_minus_14_days
        """
        vendor = create_vendor(api, name="Epsilon Pumps")
        first = create_qualification(
            api, vendor["id"], audit_date="2026-10-01T00:00:00Z", defects_found=0
        )
        # +9 days sits inside the 14-day window: rejected.
        overlap = api.create_qualification(
            vendor["id"],
            qualification_payload(audit_date="2026-10-10T00:00:00Z", defects_found=0),
            AUDITOR,
        )
        validate_error(overlap, ApiErrorId.ERR_AUDIT_OVERLAP, 409)
        # +15 days clears the window; the failed attempt did not supersede
        # anything, so the new cycle supersedes the first qualification.
        second = validate_success(
            api.create_qualification(
                vendor["id"],
                qualification_payload(audit_date="2026-10-16T00:00:00Z", defects_found=0),
                AUDITOR,
            ),
            201,
        )
        assert read_qualification(api, first["id"])["status"] == "SUPERSEDED"
        assert second["status"] == "AUDIT_SCHEDULED"

    def test_exactly_fourteen_days_apart_is_allowed(self, api):
        """PRD §3.4: "the proposed `audit_date` must not fall within 14 days,
        in either direction, of any non-superseded qualification audit of the
        same vendor; an overlapping schedule is rejected with
        `ERR_AUDIT_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/vendor_audit_overlap_plus_minus_14_days
        """
        vendor = create_vendor(api, name="Epsilon Spares")
        create_qualification(
            api, vendor["id"], audit_date="2026-10-01T00:00:00Z", defects_found=0
        )
        # Exactly 14 days later is outside "within 14 days": accepted, and it
        # supersedes the first cycle.
        second = validate_success(
            api.create_qualification(
                vendor["id"],
                qualification_payload(audit_date="2026-10-15T00:00:00Z", defects_found=0),
                AUDITOR,
            ),
            201,
        )
        assert second["status"] == "AUDIT_SCHEDULED"


class TestVendorDisqualifyCascade:
    """Disqualification flips the vendor's flag and rejects PROCURED lots."""

    def test_disqualify_rejects_procured_lots(self, api):
        """PRD §3.4: "Reaching `DISQUALIFIED` from a conditionally qualified
        vendor cascades: every component lot of that vendor still `PROCURED`
        transitions to `REJECTED`, each lot's `version` incrementing, and the
        vendor's `qualified` flag falls false if no other active qualification
        remains."

        Design: Difficulty/transitive_cascade/vendor_disqualify_rejects_lots_two_hop
        """
        dca = create_dca(api, docket_number="52-401")
        program = create_adequate_program(api, dca["id"])
        # A zero-defect audit completes straight to FULLY_QUALIFIED, opening
        # the procurement gate for the lot.
        vendor = create_vendor(api, name="Beta Castings")
        first = create_qualification(api, vendor["id"], defects_found=0)
        first = validate_success(api.complete_audit(vendor["id"], first["id"], AUDITOR))
        assert first["status"] == "FULLY_QUALIFIED"
        assert read_vendor(api, vendor["id"])["qualified"] is True
        lot = create_component_lot(api, vendor["id"], program["id"], quantity=4)
        assert lot["status"] == "PROCURED"

        # A second cycle (outside the 14-day overlap window) supersedes the
        # fully-qualified record and completes with a defect, landing
        # CONDITIONALLY_QUALIFIED — the state PRD §3.4 disqualifies from.
        second = create_qualification(
            api, vendor["id"], audit_date="2026-10-16T00:00:00Z", defects_found=1
        )
        assert read_qualification(api, first["id"])["status"] == "SUPERSEDED"
        second = validate_success(api.complete_audit(vendor["id"], second["id"], AUDITOR))
        assert second["status"] == "CONDITIONALLY_QUALIFIED"

        # Hop 0: the qualification is disqualified.
        disqualified = validate_success(
            api.disqualify_qualification(vendor["id"], second["id"], AUDITOR)
        )
        assert disqualified["status"] == "DISQUALIFIED"
        # Hop 1: the vendor flag falls.
        assert read_vendor(api, vendor["id"])["qualified"] is False
        # Hop 2: the PROCURED lot cascades to REJECTED.
        assert read_component_lot(api, lot["id"])["status"] == "REJECTED"

    def test_delivered_lot_survives_disqualification(self, api):
        """PRD §3.4: "Reaching `DISQUALIFIED` from a conditionally qualified
        vendor cascades: every component lot of that vendor still `PROCURED`
        transitions to `REJECTED`, each lot's `version` incrementing, and the
        vendor's `qualified` flag falls false if no other active qualification
        remains."
        PRD §3.4: "`RELEASED` and `REJECTED` are the terminal states; the only
        path to `REJECTED` is the system cascade from vendor disqualification
        or test-program failure described above."

        Design: Difficulty/transitive_cascade/vendor_disqualify_rejects_lots_two_hop
        """
        dca = create_dca(api, docket_number="52-402")
        program = create_adequate_program(api, dca["id"])
        vendor = create_vendor(api, name="Beta Forgings")
        first = create_qualification(api, vendor["id"], defects_found=0)
        first = validate_success(api.complete_audit(vendor["id"], first["id"], AUDITOR))
        assert first["status"] == "FULLY_QUALIFIED"
        lot = create_component_lot(api, vendor["id"], program["id"], quantity=2)
        # Delivery re-checks the vendor while it is still qualified.
        delivered = validate_success(api.deliver_component_lot(lot["id"], SCM))
        assert delivered["status"] == "DELIVERED"

        # A second, defect-bearing cycle reaches CONDITIONALLY_QUALIFIED and
        # is disqualified from there (the disqualify path PRD §3.4 names).
        second = create_qualification(
            api, vendor["id"], audit_date="2026-10-16T00:00:00Z", defects_found=1
        )
        second = validate_success(api.complete_audit(vendor["id"], second["id"], AUDITOR))
        assert second["status"] == "CONDITIONALLY_QUALIFIED"
        validate_success(api.disqualify_qualification(vendor["id"], second["id"], AUDITOR))
        # Only lots still PROCURED are cascaded; the DELIVERED lot is untouched.
        assert read_component_lot(api, lot["id"])["status"] == "DELIVERED"


class TestProcurementGate:
    """Lot creation requires a qualified vendor and an ADEQUATE program."""

    def test_gate_blocks_until_program_adequate(self, api):
        """PRD §3.4: "Creating a nuclear-grade lot requires both that the
        vendor's `qualified` flag is true and that the referenced test program
        is `ADEQUATE`; failure of either gate is rejected with
        `ERR_PROCUREMENT_GATE` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/lot_procurement_depends_on_program_and_vendor
        """
        dca = create_dca(api, docket_number="52-700")
        program = validate_success(
            api.create_test_program(
                dca["id"], {"program_code": "TP-1", "required_tests": 1}, APPLICANT
            ),
            201,
        )
        validate_success(api.start_test_program(program["id"], APPLICANT))
        vendor = create_vendor(api, name="Delta Steel")
        qual = create_qualification(api, vendor["id"], defects_found=0)
        validate_success(api.complete_audit(vendor["id"], qual["id"], AUDITOR))
        assert read_vendor(api, vendor["id"])["qualified"] is True

        # Vendor qualified but program still IN_PROGRESS: the gate rejects.
        blocked = api.create_component_lot(
            {
                "vendor_id": vendor["id"],
                "program_id": program["id"],
                "component_type": "module",
                "quantity": 1,
            },
            SCM,
        )
        validate_error(blocked, ApiErrorId.ERR_PROCUREMENT_GATE, 422)

        # The passing result drives the program ADEQUATE and the gate opens.
        validate_success(
            api.record_test_result(
                program["id"], test_result_payload(outcome="PASS", run_at="2026-09-20T00:00:00Z"), APPLICANT
            ),
            201,
        )
        lot = validate_success(
            api.create_component_lot(
                {
                    "vendor_id": vendor["id"],
                    "program_id": program["id"],
                    "component_type": "module",
                    "quantity": 1,
                },
                SCM,
            ),
            201,
        )
        assert_component_lot(lot)
        assert lot["status"] == "PROCURED"

    def test_gate_blocks_when_vendor_unqualified(self, api):
        """PRD §3.4: "Creating a nuclear-grade lot requires both that the
        vendor's `qualified` flag is true and that the referenced test program
        is `ADEQUATE`; failure of either gate is rejected with
        `ERR_PROCUREMENT_GATE` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/lot_procurement_depends_on_program_and_vendor
        """
        dca = create_dca(api, docket_number="52-703")
        program = create_adequate_program(api, dca["id"])
        # Freshly registered vendor: qualified is false.
        vendor = create_vendor(api, name="Delta Castings")
        blocked = api.create_component_lot(
            {
                "vendor_id": vendor["id"],
                "program_id": program["id"],
                "component_type": "module",
                "quantity": 1,
            },
            SCM,
        )
        validate_error(blocked, ApiErrorId.ERR_PROCUREMENT_GATE, 422)


class TestExistenceBeforeProcurementGate:
    """Unresolved foreign keys are reported before any domain gate."""

    def test_missing_program_yields_not_found_not_gate_error(self, api):
        """PRD §2.7: "The same 404 applies when a request-body foreign key
        reference — `dca_id`, `vendor_id`, `program_id`, `pipeline_id`,
        `utility_id`, `permit_id`, or a `sar_section_code` that names no
        section of the owning application — does not resolve to an existing
        row."
        PRD §2.7: "Only after those structural checks pass do the domain rules
        engage — segregation of duties on RAI acceptance, the procurement
        gate, audit-date overlap, the hearing windows, chronological test
        recording, section-code matching, capacity and escalation gates, the
        OCC version match, and uniqueness constraints."

        Design: Difficulty/priority_pair_validation_conflict/existence_vs_business_safety_on_lot_create
        """
        vendor = create_vendor(api, name="Gamma Forge")
        # Program id does not exist AND the vendor is unqualified: existence
        # is checked before the procurement gate, so the answer is 404.
        resp = api.create_component_lot(
            {
                "vendor_id": vendor["id"],
                "program_id": NON_EXISTENT_UUID,
                "component_type": "pipe",
                "quantity": 2,
            },
            SCM,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)

    def test_missing_vendor_also_yields_not_found(self, api):
        """PRD §2.7: "The same 404 applies when a request-body foreign key
        reference — `dca_id`, `vendor_id`, `program_id`, `pipeline_id`,
        `utility_id`, `permit_id`, or a `sar_section_code` that names no
        section of the owning application — does not resolve to an existing
        row."

        Design: Difficulty/priority_pair_validation_conflict/existence_vs_business_safety_on_lot_create
        """
        dca = create_dca(api, docket_number="52-704")
        program = create_adequate_program(api, dca["id"])
        resp = api.create_component_lot(
            {
                "vendor_id": NON_EXISTENT_UUID,
                "program_id": program["id"],
                "component_type": "pipe",
                "quantity": 2,
            },
            SCM,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)
