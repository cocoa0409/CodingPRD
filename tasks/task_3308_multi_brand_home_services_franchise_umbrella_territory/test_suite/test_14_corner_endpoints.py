"""Endpoint corner claims: synthesised work orders and the reopen window."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    activate_agreement,
    award_territory,
    conduct_audit,
    create_agreement,
    create_audit,
    create_brand,
    create_franchisee,
    create_lead,
    create_territory,
    franchisee_version,
    get_agreement,
    get_audit,
    offer_agreement,
    offer_territory,
    publish_audit,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["franchise_admin_headers"]


class TestLeadConvertSynthesisesWorkOrder:
    def test_converting_an_allocated_lead_spins_off_call_center_work(self, api):
        """PRD §3.6: "the allocation may be converted by a `FranchiseAdmin`,
        which moves the lead to `CONVERTED` and synthesizes a work order with a
        source of `CALL_CENTER_LEAD`, its performing agreement set to the lead's
        `allocated_agreement_id`, its `lead_id` bound to this lead, and a status
        of `CREATED`, feeding the flow of §3.4."

        Design: Corner/endpoints/lead_convert_synthesizes_a_call_center_work_order
        """
        set_clock("2026-09-01T00:00:00Z")
        franchisee = create_franchisee()
        brand = create_brand(
            brand_code="MSP", display_name="Mosaic Plumbing", trade="PLUMBING",
            royalty_rate=0.06, national_ad_fund_rate=0.01,
            min_certification_level="APPRENTICE", audit_cycle_months=12,
            cross_brand_fee_table={},
        )
        territory = create_territory(brand["id"], franchisee_id=franchisee["id"])
        agreement = create_agreement(franchisee["id"], brand["id"], territory["id"])
        offer_agreement(agreement["id"])
        offer_territory(territory["id"], franchisee["id"])
        award_territory(territory["id"])
        activate_agreement(agreement["id"])

        lead = create_lead(
            brand["id"], source="CALL_CENTER", household_income_band="BAND_2",
            estimated_value_cents=120000,
        )
        api.allocate_lead(
            lead["id"], franchisee_version(franchisee["id"]), ADMIN,
            allocated_agreement_id=agreement["id"],
        )

        resp = api.convert_lead(lead["id"], ADMIN)
        converted = validate_success(resp, 200)
        assert converted["status"] == "CONVERTED"

        rows, meta = validate_paginated(
            api.list_work_orders(ADMIN, {"lead_id": lead["id"]})
        )
        assert meta["total_count"] == 1, (
            f"converting the lead must synthesize exactly one work order, got "
            f"{meta['total_count']}"
        )
        synthesized = rows[0]
        assert synthesized["source"] == "CALL_CENTER_LEAD"
        assert synthesized["lead_id"] == lead["id"]
        assert synthesized["agreement_id"] == agreement["id"]
        assert synthesized["status"] == "CREATED"


class TestAuditReopenWindow:
    def _published_failing_audit(self):
        set_clock("2026-09-01T00:00:00Z")
        franchisee = create_franchisee()
        brand = create_brand(
            brand_code="MSP", display_name="Mosaic Plumbing", trade="PLUMBING",
            royalty_rate=0.06, national_ad_fund_rate=0.01,
            min_certification_level="APPRENTICE", audit_cycle_months=12,
            cross_brand_fee_table={},
        )
        territory = create_territory(brand["id"], franchisee_id=franchisee["id"])
        agreement = create_agreement(franchisee["id"], brand["id"], territory["id"])
        offer_agreement(agreement["id"])
        offer_territory(territory["id"], franchisee["id"])
        award_territory(territory["id"])
        activate_agreement(agreement["id"])
        audit = create_audit(
            agreement["id"], audit_kind="MYSTERY_SHOP", raw_score=80.0,
            findings_count=4, critical_findings_count=1,
            conducted_iso="2026-09-01T00:00:00Z",
        )
        conduct_audit(audit["id"])
        publish_audit(audit["id"], agreement["id"])
        return agreement, audit

    def test_reopening_inside_the_window_reverts_the_remediation(self, api):
        """PRD §3.8: "A `FranchiseAdmin` may reopen it, but only while the
        logical clock is strictly before the audit's `conducted_iso` advanced by
        24 hours".
        PRD §3.8: "Reopening returns the audit from `PUBLISHED` to `CONDUCTED`,
        resets its `remediation_status` to `NONE`, clears
        `remediation_opened_clock_iso` and `remediation_due_iso` back to null,
        and recomputes both the agreement's `open_remediation_count` and its
        `standards_status`."

        Design: Corner/endpoints/audit_reopen_is_closed_outside_its_twenty_four_hour_window
        """
        agreement, audit = self._published_failing_audit()
        assert get_audit(audit["id"])["remediation_status"] == "OPEN"

        set_clock("2026-09-01T12:00:00Z")
        resp = api.reopen_audit(audit["id"], ADMIN)
        reopened = validate_success(resp, 200)

        assert reopened["audit_status"] == "CONDUCTED"
        assert reopened["remediation_status"] == "NONE", (
            f"reopening reverts the remediation dimension, got "
            f"{reopened['remediation_status']}"
        )
        assert reopened["remediation_due_iso"] is None
        assert reopened["remediation_opened_clock_iso"] is None

        refreshed = get_agreement(agreement["id"])
        assert refreshed["open_remediation_count"] == 0
        assert refreshed["standards_status"] != "REMEDIATION_REQUIRED", (
            f"the posture must be recomputed away, got {refreshed['standards_status']}"
        )

    def test_reopening_at_exactly_twenty_four_hours_is_refused(self, api):
        """PRD §3.8: "reopening at or beyond that instant is refused with
        `ERR_REOPEN_WINDOW_CLOSED`."

        Design: Corner/endpoints/audit_reopen_is_closed_outside_its_twenty_four_hour_window
        """
        _, audit = self._published_failing_audit()

        set_clock("2026-09-02T00:00:00Z")
        resp = api.reopen_audit(audit["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_REOPEN_WINDOW_CLOSED)

        assert get_audit(audit["id"])["audit_status"] == "PUBLISHED", (
            "a refused reopen leaves the audit published"
        )