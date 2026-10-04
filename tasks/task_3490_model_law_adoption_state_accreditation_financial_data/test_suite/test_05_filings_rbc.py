"""Financial filings and risk-based capital: dual-variant aggregation, pinned
rounding order, action-level bands, supervision cascade, supersession, and OCC."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_money_equals,
    assert_ratio_equals,
    assert_rbc_report,
    factories,
    fixtures,
    make_insurer_user_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

STAFF = TEST_USERS["association_staff_headers"]


class TestFilingsRbc:
    def test_rbc_covariance_vs_additive_divergence(self, api):
        """PRD §3.4: "The two ratio variants coexist deliberately. The covariance variant is official: it drives `action_level`, `latest_rbc_ratio`, and the supervision cascade. The additive variant divides by a larger capital requirement and therefore yields an equal or lower ratio; it is reported alongside as `ratio_additive` for conservative review and never drives classification — identical filing data can classify differently under the two, as with charges of 1000000, 800000, and 600000 cents against a surplus of 4000000 cents, where the covariance ratio of 2.8284 reads `NONE` but the additive ratio of 1.6667 reads `COMPANY_ACTION`."

        Design: Difficulty/dual_variant_calc/rbc_covariance_vs_additive_divergence
        """
        bundle = fixtures.setup_validated_filing(
            api, naic_code="90001",
            reported_surplus_cents=4000000,
            asset_risk_cents=1000000,
            underwriting_risk_cents=800000,
            other_risk_cents=600000,
        )
        report = bundle.report
        assert_rbc_report(report)
        assert_money_equals(report["tac_cents"], 4000000, "tac_cents")
        assert_money_equals(
            report["acl_additive_cents"], 2400000, "acl_additive_cents"
        )
        assert_money_equals(
            report["acl_covariance_cents"], 1414213.56, "acl_covariance_cents"
        )
        assert_ratio_equals(report["ratio_covariance"], 2.8284, "ratio_covariance")
        assert_ratio_equals(report["ratio_additive"], 1.6667, "ratio_additive")
        assert report["action_level"] == "NONE", (
            "the official covariance variant drives the classification"
        )
        assert bundle.insurer["latest_action_level"] == "NONE"
        assert bundle.insurer["status"] == "ACTIVE"

    def test_rbc_acl_rounding_order_pinned(self, api):
        """PRD §3.4: "the three integer-cent risk charges are squared and summed first, the square root of that sum is taken next, and only then is the result rounded half-up to two decimals to form `acl_covariance_cents`; dividing by the unrounded square root is a prohibited order — with charges of 1, 1, and 1 cents against a surplus of 3 cents, the pinned order yields a ratio of 1.7341 while the unpinned order yields 1.7321."
        PRD §2.5: "the risk-based capital aggregation rounds the capital requirement to two decimals before dividing by it, never the other way around (§3.4)."

        Design: Difficulty/combinatorial_formula/rbc_acl_rounding_order_pinned
        """
        bundle = fixtures.setup_validated_filing(
            api, naic_code="90011",
            reported_surplus_cents=3,
            asset_risk_cents=1,
            underwriting_risk_cents=1,
            other_risk_cents=1,
        )
        report = bundle.report
        assert_money_equals(
            report["acl_covariance_cents"], 1.73, "acl_covariance_cents"
        )
        assert_ratio_equals(report["ratio_covariance"], 1.7341, "ratio_covariance")
        assert_ratio_equals(report["ratio_additive"], 1.0, "ratio_additive")
        assert report["action_level"] == "COMPANY_ACTION"

    def test_rbc_ratio_two_hundred_percent_boundary(self, api):
        """PRD §3.4: "From `ratio_covariance`: at least 2.0000 maps to `NONE`; at least 1.5000 but below 2.0000 to `COMPANY_ACTION`"
        PRD §3.4: "Boundaries are inclusive at the lower edge of each band — exactly 2.0000 is `NONE`, while 1.9999 is `COMPANY_ACTION`."

        Design: Difficulty/boundary_precision_check/rbc_ratio_two_hundred_percent_boundary
        """
        state = fixtures.create_state(api, code="CA")
        ins_a = fixtures.create_insurer(api, "90040", state["code"])
        ins_b = fixtures.create_insurer(api, "90041", state["code"])
        fixtures.create_active_standard(api)
        fa = fixtures.create_filing(
            api, ins_a, reported_surplus_cents=4000000,
            asset_risk_cents=2000000, underwriting_risk_cents=0,
            other_risk_cents=0,
        )
        fixtures.submit_filing(api, fa)
        fixtures.validate_filing(api, fa["id"])
        fb = fixtures.create_filing(
            api, ins_b, reported_surplus_cents=3999800,
            asset_risk_cents=2000000, underwriting_risk_cents=0,
            other_risk_cents=0,
        )
        fixtures.submit_filing(api, fb)
        fixtures.validate_filing(api, fb["id"])
        ra = fixtures.list_rbc_reports(api, fa["id"])[0]
        rb = fixtures.list_rbc_reports(api, fb["id"])[0]
        assert_ratio_equals(ra["ratio_covariance"], 2.0, "filing A ratio")
        assert ra["action_level"] == "NONE", "2.0000 >= 2.0000 is NONE"
        assert_ratio_equals(rb["ratio_covariance"], 1.9999, "filing B ratio")
        assert rb["action_level"] == "COMPANY_ACTION", "1.9999 < 2.0000"

    def test_validate_rbc_supervision_escalation_cascade(self, api):
        """PRD §3.4: "The insurer's `latest_rbc_ratio` and `latest_action_level` are set from this report, and the insurer's `status` becomes `UNDER_SUPERVISION` when the action level is `AUTHORIZED_CONTROL` or `MANDATORY_CONTROL`, otherwise `ACTIVE`"
        PRD §3.4: "Hop 3 fires only when hop 2 moved the insurer into `UNDER_SUPERVISION`: every market conduct response that insurer has filed on a still-`OPEN` call has its `escalation_flag` set to true (§3.7)."
        PRD §3.7: "sets its `escalation_flag` — true when the responding insurer is `UNDER_SUPERVISION` at that moment and false otherwise"

        Design: Difficulty/transitive_cascade/validate_rbc_supervision_escalation_cascade
        """
        state = fixtures.create_state(api, code="CA")
        insurer = fixtures.create_insurer(api, "90030", state["code"])
        call = fixtures.create_call(
            api, state, call_code="MC-300", topic="underwriting"
        )
        response = fixtures.add_response(api, call["id"], insurer, 100000000, 0)
        assert response["escalation_flag"] is False, (
            "the insurer is ACTIVE at response creation"
        )
        fixtures.create_active_standard(api)
        filing = fixtures.create_filing(
            api, insurer, reported_surplus_cents=1600000,
            asset_risk_cents=1200000, underwriting_risk_cents=1200000,
            other_risk_cents=0,
        )
        fixtures.submit_filing(api, filing)
        fixtures.validate_filing(api, filing["id"])
        report = fixtures.list_rbc_reports(api, filing["id"])[0]
        assert_ratio_equals(report["ratio_covariance"], 0.9428, "ratio_covariance")
        assert report["action_level"] == "AUTHORIZED_CONTROL"
        insurer = fixtures.read_insurer(api, insurer["id"])
        assert insurer["status"] == "UNDER_SUPERVISION"
        responses = fixtures.list_responses(api, call["id"])
        assert len(responses) == 1
        assert responses[0]["escalation_flag"] is True, (
            "the supervision cascade escalates the open-call response"
        )

    def test_filing_supersede_surplus_sum_invariant(self, api):
        """PRD §3.4: "Creation also supersedes: any existing filing of the same (`insurer_id`, `period_year`, `period_quarter`) that is not already `SUPERSEDED` — whether `DRAFT`, `SUBMITTED`, `EDITS_FAILED`, or `VALIDATED` — becomes `SUPERSEDED`. A superseded `VALIDATED` filing keeps its RBC report for history, but the insurer's `latest_rbc_ratio` and `latest_action_level` are recomputed to null until a successor filing validates."

        Design: Difficulty/compensating_invariant/filing_supersede_surplus_sum_invariant
        """
        bundle = fixtures.setup_validated_filing(
            api, naic_code="90050",
            reported_surplus_cents=5000000,
            asset_risk_cents=100000,
            underwriting_risk_cents=50000,
            other_risk_cents=25000,
        )
        f1 = bundle.filing
        assert f1["status"] == "VALIDATED"
        f2 = fixtures.create_filing(
            api, bundle.insurer,
            reported_surplus_cents=6000000,
            asset_risk_cents=100000,
            underwriting_risk_cents=50000,
            other_risk_cents=25000,
        )
        assert f2["status"] == "DRAFT"
        f1_after = validate_success(api.get_filing(f1["id"], STAFF))
        assert f1_after["status"] == "SUPERSEDED", (
            "the new filing retires the prior VALIDATED filing of the period"
        )
        filings, _meta = validate_paginated(
            api.list_filings(f1["insurer_id"], STAFF, params={"period_year": 2026})
        )
        live = [f for f in filings if f["status"] != "SUPERSEDED"]
        assert len(live) == 1 and live[0]["id"] == f2["id"]
        assert sum(f["reported_surplus_cents"] for f in live) == 6000000, (
            "the live surplus for the period is the successor's, not the sum"
        )
        insurer = fixtures.read_insurer(api, f1["insurer_id"])
        assert insurer["latest_rbc_ratio"] is None
        assert insurer["latest_action_level"] is None

    def test_filing_state_errors(self, api):
        """PRD §3.4: "Submitting a filing requires it to be in `DRAFT` (`ERR_FILING_NOT_DRAFT`, 409)"
        PRD §3.4: "The filing must be `SUBMITTED` (`ERR_FILING_NOT_SUBMITTED`, 409)"

        Design: Corner/state_machines/filing_state_errors
        """
        state = fixtures.create_state(api, code="CA")
        insurer = fixtures.create_insurer(api, "90081", state["code"])
        fixtures.create_active_standard(api, code="VM-81", version_label="v1")
        filing = fixtures.create_filing(
            api, insurer, valuation_standard_code="VM-81", period_quarter="Q1",
            reported_surplus_cents=1000, asset_risk_cents=100,
            underwriting_risk_cents=50, other_risk_cents=25,
        )
        resp = api.validate_filing(filing["id"], STAFF)
        validate_error(resp, ApiErrorId.ERR_FILING_NOT_SUBMITTED)
        submitted = fixtures.submit_filing(api, filing)
        assert submitted["status"] == "SUBMITTED"
        resp = api.submit_filing(
            filing["id"], make_insurer_user_headers(insurer["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FILING_NOT_DRAFT)

    def test_insurer_supervision_reinstatement_loop(self, api):
        """PRD §3.4: "the insurer's `status` becomes `UNDER_SUPERVISION` when the action level is `AUTHORIZED_CONTROL` or `MANDATORY_CONTROL`, otherwise `ACTIVE` — the same classification reinstates a supervised insurer back to `ACTIVE` when a later filing lands in the three milder bands."

        Design: Corner/state_machines/insurer_supervision_reinstatement_loop
        """
        bundle = fixtures.setup_validated_filing(
            api, naic_code="90083", standard_code="VM-82",
            reported_surplus_cents=1600000,
            asset_risk_cents=1200000, underwriting_risk_cents=1200000,
            other_risk_cents=0,
        )
        assert bundle.report["action_level"] == "AUTHORIZED_CONTROL"
        assert bundle.insurer["status"] == "UNDER_SUPERVISION"
        followup = fixtures.create_filing(
            api, bundle.insurer, valuation_standard_code="VM-82",
            period_year=2027, reported_surplus_cents=6000000,
            asset_risk_cents=2000000, underwriting_risk_cents=0,
            other_risk_cents=0,
        )
        fixtures.submit_filing(api, followup)
        fixtures.validate_filing(api, followup["id"])
        report = fixtures.list_rbc_reports(api, followup["id"])[0]
        assert_ratio_equals(report["ratio_covariance"], 3.0, "ratio_covariance")
        assert report["action_level"] == "NONE"
        insurer = fixtures.read_insurer(api, bundle.insurer["id"])
        assert insurer["status"] == "ACTIVE", "the milder band reinstates the insurer"

    def test_rbc_regulatory_band_classification(self, api):
        """PRD §3.4: "at least 1.0000 but below 1.5000 to `REGULATORY_ACTION`"
        PRD §3.4: "the insurer's `status` becomes `UNDER_SUPERVISION` when the action level is `AUTHORIZED_CONTROL` or `MANDATORY_CONTROL`, otherwise `ACTIVE`"

        Design: Corner/calculations/rbc_regulatory_band_classification
        """
        bundle = fixtures.setup_validated_filing(
            api, naic_code="90084", standard_code="VM-83",
            reported_surplus_cents=2400000,
            asset_risk_cents=2000000, underwriting_risk_cents=0,
            other_risk_cents=0,
        )
        assert_ratio_equals(
            bundle.report["ratio_covariance"], 1.2, "ratio_covariance"
        )
        assert bundle.report["action_level"] == "REGULATORY_ACTION"
        assert bundle.insurer["status"] == "ACTIVE", (
            "REGULATORY_ACTION does not trigger supervision"
        )

    def test_occ_filing_stale_version_rejected(self, api):
        """PRD §2.6: "Creating a financial filing (`POST /naic/filings`) requires `expected_insurer_version`, carrying the client's last observed `version` of the target insurer. If the insurer's current `version` has advanced since that observation — for example because another filing was created or validated against the same insurer — the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_filing_stale_version_rejected
        """
        state = fixtures.create_state(api, code="CA")
        insurer = fixtures.create_insurer(api, "90092", state["code"])
        stale_version = insurer["version"]
        fixtures.create_active_standard(api, code="VM-87", version_label="v1")
        first = fixtures.create_filing(
            api, insurer, valuation_standard_code="VM-87",
            expected_insurer_version=stale_version,
            reported_surplus_cents=1000, asset_risk_cents=100,
            underwriting_risk_cents=0, other_risk_cents=0,
        )
        assert first["status"] == "DRAFT"
        # The first create advanced the insurer's version; the stale echo fails.
        resp = api.create_filing(
            factories.filing_payload(
                insurer["id"], stale_version, valuation_standard_code="VM-87",
                reported_surplus_cents=2000, asset_risk_cents=100,
                underwriting_risk_cents=0, other_risk_cents=0,
            ),
            make_insurer_user_headers(insurer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        filings, _meta = validate_paginated(
            api.list_filings(insurer["id"], STAFF, params={"period_year": 2026})
        )
        live = [f for f in filings if f["status"] != "SUPERSEDED"]
        assert len(live) == 1 and live[0]["id"] == first["id"]
