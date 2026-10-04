"""Households: dissolution guard, OCC-guarded linking, aggregate recompute,
and input-set filtering by member status."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    validate_error,
    validate_success,
)
from test_helpers import fixtures
from test_helpers.fixtures import (
    OFFICER_A,
    build_household,
    build_offering,
    make_member_headers,
    member_version,
)


class TestDissolutionGuard:
    def _member_with_household(self, api):
        _, member_id = fixtures.approve_direct_member(
            api, name="Guard Gail", dob="1983-03-03",
            start="2004-01-01", end="2010-01-01",
        )
        household = build_household(api, member_id, household_name="Gail House")
        return member_id, household

    def test_dissolve_with_linked_active_member_rejected(self, api):
        """PRD §3.10: "Dissolving a household requires that no member with
        status `ACTIVE` or `SUSPENDED` is currently linked, failing with
        `ERR_HOUSEHOLD_NOT_EMPTY` otherwise."

        Design: Corner/state_machines/household_dissolve_blocks_child_link
        """
        _, household = self._member_with_household(api)
        resp = api.dissolve_household(household["id"], OFFICER_A)
        validate_error(resp, ApiErrorId.ERR_HOUSEHOLD_NOT_EMPTY)
        current = validate_success(api.get_household(household["id"], OFFICER_A))
        assert current["status"] == "ACTIVE"

    def test_dissolve_succeeds_after_member_delinked(self, api):
        """PRD §3.10: "Dissolution moves the household to `DISSOLVED`, a
        terminal state, freezing `aggregate_product_count` at its last
        computed value." and "Delinking removes the member from their
        household by nulling `household_id`..."

        Design: Corner/state_machines/household_dissolve_blocks_child_link
        """
        member_id, household = self._member_with_household(api)
        validate_success(
            api.delink_household(member_id, make_member_headers(member_id))
        )
        dissolved = validate_success(
            api.dissolve_household(household["id"], OFFICER_A)
        )
        assert dissolved["status"] == "DISSOLVED"
        assert isinstance(dissolved["aggregate_product_count"], int)


class TestOccOnLinkHousehold:
    def _member_with_two_households(self, api):
        """Member auto-linked into H1 by creation; H2 also exists; the member
        is then delinked. Returns (member_id, h1, h2)."""
        _, member_id = fixtures.approve_direct_member(api, name="Occ Olga")
        h1 = build_household(api, member_id, household_name="Olga House")
        h2 = build_household(api, member_id, household_name="Other House")
        validate_success(
            api.delink_household(member_id, make_member_headers(member_id))
        )
        return member_id, h1, h2

    def test_stale_version_link_rejected(self, api):
        """PRD §2.8: "Linking a member into a household requires the request
        body to carry `expected_member_version`, the client-side copy of the
        member's current `version`... if the supplied value does not equal
        the member's current `version` on the server, the write is rejected
        with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/validations/stale_version_on_link_household_412
        """
        member_id, h1, h2 = self._member_with_two_households(api)
        version = member_version(api, member_id)
        # Successful interim link bumps the version, staling the capture.
        validate_success(api.link_household(
            member_id,
            {"household_id": h1["id"], "expected_member_version": version},
            make_member_headers(member_id),
        ))
        resp = api.link_household(
            member_id,
            {"household_id": h2["id"], "expected_member_version": version},
            make_member_headers(member_id),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

    def test_link_retry_with_fresh_version_bumps_once(self, api):
        """PRD §2.8: "Both guarded writes themselves increment the member's
        `version` by 1 on success." and "linking supersedes any prior
        linkage...".

        Design: Corner/validations/stale_version_on_link_household_412
        """
        member_id, h1, h2 = self._member_with_two_households(api)
        version = member_version(api, member_id)
        validate_success(api.link_household(
            member_id,
            {"household_id": h1["id"], "expected_member_version": version},
            make_member_headers(member_id),
        ))
        fresh = member_version(api, member_id)
        relinked = validate_success(api.link_household(
            member_id,
            {"household_id": h2["id"], "expected_member_version": fresh},
            make_member_headers(member_id),
        ))
        assert relinked["household_id"] == h2["id"]
        assert relinked["version"] == fresh + 1


class TestAggregateInputSet:
    def test_aggregate_counts_linked_active_and_suspended_only(self, api):
        """PRD §2.9: "Only members linked to the household whose status is
        `ACTIVE` or `SUSPENDED` contribute; `DECEASED` and `REVOKED` members
        are excluded from the sum." and "The recompute proceeds in a pinned
        order: first each contributing member's product availability matrix
        is recomputed, then the per-member available-facet counts are
        summed."

        Design: Corner/calculations/household_aggregate_includes_only_linked_active_suspended_members
        """
        _, sponsor_id = fixtures.approve_direct_member(
            api, name="Agg Adam", dob="1976-01-01",
            start="1996-01-01", end="2002-01-01",
        )
        # One BANKING offering open to both categories -> 6 facets each.
        # requires_active_status=False so the SUSPENDED child still
        # contributes after the sponsor's fraud revocation (PRD §3.7
        # suspended variant would otherwise force base availability off).
        build_offering(
            api, categories=["VETERAN_HONORABLE", "FAMILY_CHILD"],
            product_line="BANKING", product_code="SAV_ALL",
            product_name="Savings", requires_active_status=False,
        )
        household = build_household(api, sponsor_id,
                                    household_name="Agg House")
        # Child approval auto-links into the sponsor's household (PRD §3.3).
        _, child_id = fixtures.approve_family_member(
            api, sponsor_id, "CHILD", name="Agg Kid", dob="2002-01-01",
            doc_type="BIRTH_CERTIFICATE",
        )
        before = validate_success(
            api.get_household(household["id"], OFFICER_A)
        )
        assert before["aggregate_product_count"] == 12
        validate_success(api.record_eligibility_loss(
            sponsor_id, {"loss_type": "DOCUMENTATION_REVOKED"}, OFFICER_A,
        ))
        validate_success(api.record_eligibility_loss(
            sponsor_id,
            {"loss_type": "FRAUD_CONFIRMED", "loss_note": "confirmed"},
            OFFICER_A,
        ))
        after = validate_success(api.get_household(household["id"], OFFICER_A))
        # The revoked sponsor no longer contributes; the cascade-suspended
        # child still counts (SUSPENDED stays in the input set) at 6 facets.
        assert after["aggregate_product_count"] == 6
        child = validate_success(api.get_member(child_id, OFFICER_A))
        assert child["status"] == "SUSPENDED"


class TestHouseholdCreationReferences:
    def test_unknown_primary_member_rejected(self, api):
        """PRD §2.7: "foreign-key resolution producing
        `ERR_INVALID_REFERENCE`". PRD §3.10: "A household is created with a
        `household_name` display label and a `primary_member_id` naming the
        member whose lineage anchors it...".

        Design: Corner/entities/household_creation_requires_resolvable_primary_member
        """
        resp = api.create_household(
            {"household_name": "Ghost House",
             "primary_member_id": NON_EXISTENT_UUID},
            OFFICER_A,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REFERENCE)
