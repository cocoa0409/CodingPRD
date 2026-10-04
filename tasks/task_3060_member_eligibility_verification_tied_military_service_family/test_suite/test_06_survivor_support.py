"""Survivor support: continuance waterfall variants, input-set filtering,
grant cascades, and household membership conservation."""
from test_helpers import (
    ApiErrorId,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures
from test_helpers.fixtures import (
    BENEFITS,
    OFFICER_A,
    build_household,
    build_offering,
    make_member_headers,
    member_version,
    open_entitlement,
)


class TestContinuanceVariants:
    def test_spouse_beneficiary_gets_spouse_share_and_window(self, api):
        """PRD §3.9: "For a beneficiary whose `claimed_relationship` is
        `SPOUSE` or `WIDOW_WIDOWER`, the member share rate is 0.20 over 3
        months..." and "The covered amount is multiplied by the share rate,
        floored to whole cents, and then multiplied by the month count to
        produce `continuance_amount_cents`; `continuance_months` records the
        month count."

        Design: Difficulty/dual_variant_calc/survivor_continuance_spouse_vs_child_share
        """
        bundle = fixtures.setup_member_spouse_survivor_case(
            api, sponsor_name="Sam Service", spouse_name="Wendy Spouse",
            exposure_cents=420000,
        )
        open_entitlement(
            api, bundle["sponsor_id"], bundle["offering"]["id"],
            exposure_cents=420000,
        )
        granted = validate_success(
            api.grant_survivor_case(bundle["survivor_case"]["id"], BENEFITS)
        )
        # (420000 - 50000) * 0.20 = 74000; 74000 * 3 = 222000
        assert granted["continuance_amount_cents"] == 222000
        assert granted["continuance_months"] == 3

    def test_child_beneficiary_gets_child_window(self, api):
        """PRD §3.9: "for `CHILD`, `STEPCHILD`, or any other relationship —
        the lineal-descendant variant — the rate is 0.30 over 2 months, so
        identical exposure inputs yield a different amount over a shorter
        window."

        Design: Difficulty/dual_variant_calc/survivor_continuance_spouse_vs_child_share
        """
        fixtures.ensure_clock(api)
        _, sponsor_id = fixtures.approve_direct_member(api, name="Sam Parent")
        _, child_id = fixtures.approve_family_member(
            api, sponsor_id, "CHILD", name="Junior", dob="2005-01-01",
            doc_type="BIRTH_CERTIFICATE",
        )
        offering = build_offering(
            api, categories=["VETERAN_HONORABLE", "FAMILY_CHILD"],
            product_line="INSURANCE",
        )
        open_entitlement(api, sponsor_id, offering["id"],
                         exposure_cents=420000)
        validate_success(api.mark_deceased(
            sponsor_id, {"beneficiary_member_id": child_id}, BENEFITS,
        ))
        cases = validate_success(
            api.list_member_survivor_cases(sponsor_id, BENEFITS)
        )
        granted = validate_success(
            api.grant_survivor_case(cases[0]["id"], BENEFITS)
        )
        # (420000 - 50000) * 0.30 = 111000; 111000 * 2 = 222000
        assert granted["continuance_amount_cents"] == 222000
        assert granted["continuance_months"] == 2


class TestContinuanceInputSet:
    def test_closed_entitlement_excluded_from_exposure(self, api):
        """PRD §3.9: "The exposure base is the sum of `exposure_cents` over
        the deceased member's entitlements in `OPEN` or `GRANDFATHERED`
        status — `CLOSED` entitlements are excluded."

        Design: Corner/calculations/survivor_continuance_input_set_excludes_closed
        """
        bundle = fixtures.setup_member_spouse_survivor_case(
            api, sponsor_name="Set Sid", spouse_name="Set Sue",
            exposure_cents=420000,
        )
        sponsor_id = bundle["sponsor_id"]
        # One OPEN entitlement at 420000 counts; a second voluntarily CLOSED
        # entitlement at 900000 must not contribute to the exposure base.
        open_entitlement(
            api, sponsor_id, bundle["offering"]["id"], exposure_cents=420000,
        )
        second = open_entitlement(
            api, sponsor_id, bundle["offering"]["id"], exposure_cents=900000
        )
        validate_success(
            api.close_entitlement(
                sponsor_id, second["id"], make_member_headers(sponsor_id)
            )
        )
        # Death processing happened inside the bundle helper before these
        # entitlements existed; the survivor case is already OPEN.
        granted = validate_success(
            api.grant_survivor_case(bundle["survivor_case"]["id"], BENEFITS)
        )
        assert granted["continuance_amount_cents"] == 222000


class TestGrantRowAndCascade:
    def _deceased_with_household(self, api):
        """Deceased sponsor in his own household; spouse beneficiary; one
        GRANDFATHERED entitlement (via suspension + reinstatement) whose
        offering also permits the spouse's category."""
        fixtures.ensure_clock(api)
        case_d, sponsor_id = fixtures.approve_direct_member(
            api, name="Hal Harbor", dob="1975-03-03",
            start="1995-01-01", end="2015-01-01",
        )
        _, spouse_id = fixtures.approve_family_member(
            api, sponsor_id, "SPOUSE", name="Ivy Harbor", dob="1977-08-08",
            doc_type="MARRIAGE_CERTIFICATE",
        )
        offering = build_offering(
            api, categories=["VETERAN_HONORABLE", "FAMILY_SPOUSE"],
            product_line="INSURANCE", product_code="HOME_INS",
            product_name="Homeowners",
        )
        entitlement = open_entitlement(
            api, sponsor_id, offering["id"], exposure_cents=420000
        )
        household = build_household(api, sponsor_id,
                                    household_name="Harbor House")
        # Grandfather the book, then reinstate so death processing is legal.
        validate_success(api.record_eligibility_loss(
            sponsor_id, {"loss_type": "DOCUMENTATION_REVOKED"}, OFFICER_A,
        ))
        from test_helpers.fixtures import add_evidence
        add_evidence(api, case_d["id"], content_hash="restore-harbor")
        validate_success(api.reinstate_member(sponsor_id, OFFICER_A))
        validate_success(api.mark_deceased(
            sponsor_id, {"beneficiary_member_id": spouse_id}, BENEFITS,
        ))
        cases = validate_success(
            api.list_member_survivor_cases(sponsor_id, BENEFITS)
        )
        return {
            "sponsor_id": sponsor_id, "spouse_id": spouse_id,
            "entitlement": entitlement, "household": household,
            "survivor_case": cases[0],
        }

    def test_grant_rekeys_grandfathered_entitlement_to_beneficiary(self, api):
        """PRD §3.9: "Every `GRANDFATHERED` entitlement of the deceased
        member whose offering permits the beneficiary's category is re-keyed
        to the `beneficiary_member_id` in an ownership transfer; the
        remaining entitlements close with `closure_reason` `MEMBER_LOSS`."

        Design: Difficulty/transitive_cascade/survivor_grant_entitlement_transfer_household_rekey_cascade
        """
        parts = self._deceased_with_household(api)
        granted = validate_success(
            api.grant_survivor_case(parts["survivor_case"]["id"], BENEFITS)
        )
        assert granted["status"] == "GRANTED"
        ent = validate_success(
            api.get_entitlement(parts["entitlement"]["id"], OFFICER_A)
        )
        assert ent["member_id"] == parts["spouse_id"]

    def test_grant_moves_beneficiary_into_deceased_household(self, api):
        """PRD §3.9: "The beneficiary's `household_id` is set to the deceased
        member's household when one is set, recorded on the case as
        `transfer_household_id`, and both the old and new household
        aggregates are recomputed."

        Design: Difficulty/transitive_cascade/survivor_grant_entitlement_transfer_household_rekey_cascade
        """
        parts = self._deceased_with_household(api)
        granted = validate_success(
            api.grant_survivor_case(parts["survivor_case"]["id"], BENEFITS)
        )
        assert granted["continuance_amount_cents"] == 222000
        assert granted["transfer_household_id"] == parts["household"]["id"]
        spouse = validate_success(api.get_member(parts["spouse_id"], OFFICER_A))
        assert spouse["household_id"] == parts["household"]["id"]


class TestGrantSideEffectsOnEmptyEstate:
    def test_grant_with_no_entitlements_yields_zero_continuance(self, api):
        """PRD §3.9: "A deductible of 50000 cents is absorbed first, and only
        the overflow above it flows into the benefit: the covered amount is
        the exposure minus the deductible, floored at zero." and "The
        beneficiary's `household_id` is set to the deceased member's
        household when one is set, recorded on the case as
        `transfer_household_id`..."

        Design: Corner/state_machines/survivor_grant_side_effects_all_applied
        """
        bundle = fixtures.setup_member_spouse_survivor_case(
            api, sponsor_name="Side Sid", spouse_name="Side Sue",
        )
        household = build_household(api, bundle["sponsor_id"],
                                    household_name="Sid House")
        # Re-create the survivor state: the survivor case opened at death
        # references the household at grant time, so grant reads it now.
        granted = validate_success(
            api.grant_survivor_case(bundle["survivor_case"]["id"], BENEFITS)
        )
        assert granted["status"] == "GRANTED"
        assert granted["continuance_amount_cents"] == 0
        assert granted["continuance_months"] == 3
        assert granted["transfer_household_id"] == household["id"]


class TestHouseholdMembershipConservation:
    def _grant_and_capture(self, api):
        """Deceased sponsor in H_D; spouse in her own H_B; grant moves the
        spouse into H_D. Returns the ids and the pre-grant aggregate of H_B.
        """
        fixtures.ensure_clock(api)
        _, sponsor_id = fixtures.approve_direct_member(
            api, name="Ted Trail", dob="1970-01-01",
            start="1990-01-01", end="2010-01-01",
        )
        _, spouse_id = fixtures.approve_family_member(
            api, sponsor_id, "SPOUSE", name="Uma Trail", dob="1972-02-02",
            doc_type="MARRIAGE_CERTIFICATE",
        )
        h_d = build_household(api, sponsor_id, household_name="Trail Home")
        h_b = build_household(api, spouse_id, household_name="Uma Place")
        pre_grant_hb = validate_success(
            api.get_household(h_b["id"], OFFICER_A)
        )["aggregate_product_count"]
        validate_success(api.mark_deceased(
            sponsor_id, {"beneficiary_member_id": spouse_id}, BENEFITS,
        ))
        cases = validate_success(
            api.list_member_survivor_cases(sponsor_id, BENEFITS)
        )
        return {
            "sponsor_id": sponsor_id, "spouse_id": spouse_id,
            "h_d": h_d, "h_b": h_b, "survivor_case": cases[0],
            "pre_grant_hb": pre_grant_hb,
        }

    def _household_member_count(self, api, household_id):
        members, _meta = validate_paginated(
            api.list_members(OFFICER_A, params={"household_id": household_id,
                                                "limit": 100})
        )
        return len(members)

    def test_membership_conserved_through_grant(self, api):
        """PRD §3.9: "The beneficiary's `household_id` is set to the deceased
        member's household when one is set..." and PRD §3.10: "the primary
        member ... is auto-linked at creation". The grant moves exactly one
        membership between the two households; the total across both is
        unchanged.

        Design: Difficulty/compensating_invariant/household_membership_conserved_across_survivor_transfer
        """
        parts = self._grant_and_capture(api)
        before = (
            self._household_member_count(api, parts["h_d"]["id"])
            + self._household_member_count(api, parts["h_b"]["id"])
        )
        assert before == 2
        validate_success(
            api.grant_survivor_case(parts["survivor_case"]["id"], BENEFITS)
        )
        spouse = validate_success(api.get_member(parts["spouse_id"], OFFICER_A))
        assert spouse["household_id"] == parts["h_d"]["id"]
        after = (
            self._household_member_count(api, parts["h_d"]["id"])
            + self._household_member_count(api, parts["h_b"]["id"])
        )
        assert after == 2

    def test_round_trip_restores_original_household_without_drift(self, api):
        """PRD §3.10: "Delinking removes the member from their household by
        nulling `household_id` and recomputes the abandoned household's
        aggregate." and "Linking a member into a household is a deliberate
        write carrying the `household_id` and the OCC field
        `expected_member_version` per §2.8; linking supersedes any prior
        linkage..."

        Design: Difficulty/compensating_invariant/household_membership_conserved_across_survivor_transfer
        """
        parts = self._grant_and_capture(api)
        validate_success(
            api.grant_survivor_case(parts["survivor_case"]["id"], BENEFITS)
        )
        spouse_headers = make_member_headers(parts["spouse_id"])
        validate_success(
            api.delink_household(parts["spouse_id"], spouse_headers)
        )
        version = member_version(api, parts["spouse_id"])
        validate_success(api.link_household(
            parts["spouse_id"],
            {"household_id": parts["h_b"]["id"],
             "expected_member_version": version},
            spouse_headers,
        ))
        spouse = validate_success(api.get_member(parts["spouse_id"], OFFICER_A))
        assert spouse["household_id"] == parts["h_b"]["id"]
        total = (
            self._household_member_count(api, parts["h_d"]["id"])
            + self._household_member_count(api, parts["h_b"]["id"])
        )
        assert total == 2
        h_b = validate_success(api.get_household(parts["h_b"]["id"], OFFICER_A))
        assert h_b["aggregate_product_count"] == parts["pre_grant_hb"]
