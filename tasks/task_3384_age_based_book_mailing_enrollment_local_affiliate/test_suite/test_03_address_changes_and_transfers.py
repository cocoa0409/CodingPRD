"""Address changes, transfers, and the hold cycle (PRD §3.4, §2.9)."""
import pytest

from test_helpers import (
    ApiErrorId,
    AddressChangeStatus,
    DEFAULT_CHILD_SPECS,
    EnrollmentStatus,
    TEST_USERS,
    UnenrollReason,
    api_client,
    approve_agreement,
    create_address_change,
    create_address_change_payload,
    decide_address_change,
    get_affiliate,
    get_child,
    get_child_wave_item,
    make_affiliate_coordinator_headers,
    mark_item_returned,
    register_child,
    register_children,
    set_logical_clock,
    setup_manifested_wave,
    setup_operative_affiliate,
    setup_second_affiliate,
    validate_error,
    validate_paginated,
    validate_success,
)

_ADMIN = TEST_USERS["platform_admin_headers"]

IN_AREA_ADDRESS = {
    "line1": "9 Maple Ave", "city": "Nashville", "region": "TN",
    "postal_code": "37210", "country": "US",
}
MEMPHIS_ADDRESS = {
    "line1": "7 Beale St", "city": "Memphis", "region": "TN",
    "postal_code": "37103", "country": "US",
}


class TestAddressChangeReject:
    def test_address_change_reject_leaves_child_untouched(self, api):
        """PRD §3.4: "Rejection is the quiet branch: the change becomes
        `REJECTED` and the child is untouched — status, address, and
        `consecutive_returns` all unchanged."
        PRD §3.4: "`decided_by` records who acted."

        Design: Corner/endpoints/address_change_reject_leaves_child_untouched
        """
        base = setup_operative_affiliate()
        affiliate = base["affiliate"]
        child = register_children(affiliate["id"], DEFAULT_CHILD_SPECS[:1])[0]
        change = create_address_change(
            child["id"],
            affiliate["id"],
            {
                "line1": "1 Reject Rd", "city": "Nashville", "region": "TN",
                "postal_code": "37209", "country": "US",
            },
        )
        decided = decide_address_change(change["id"], affiliate["id"], "REJECT")
        assert decided["status"] == AddressChangeStatus.REJECTED.value
        assert decided["decided_by"] == affiliate["id"]
        assert decided["resulting_child_id"] is None
        after = get_child(child["id"])
        assert after["mailing_address"]["line1"] == "1 Oak St"
        assert after["enrollment_status"] == EnrollmentStatus.ACTIVE.value
        assert after["consecutive_returns"] == 0
        assert get_affiliate(affiliate["id"])["enrolled_count"] == 1


class TestAddressChangeTerminalChild:
    def test_address_change_create_on_graduated_child_rejected(self, api):
        """PRD §3.4: "Submission requires the child to be non-terminal —
        `ACTIVE` or `UNDELIVERABLE_HOLD` — else `ERR_INVALID_STATE`".
        PRD §3.3: "When the sweep finds the current logical month has moved
        beyond a child's `expected_final_mailing_month`, the child becomes
        `GRADUATED` and the affiliate's `enrolled_count` is recomputed."

        Design: Corner/state_machines/address_change_create_on_graduated_child_rejected
        """
        base = setup_operative_affiliate()
        affiliate = base["affiliate"]
        kid = register_child(
            affiliate["id"],
            full_name="Old Kid",
            family_name="Kid",
            birth_date="2021-10-15T00:00:00Z",
            mailing_address={
                "line1": "3 Vine St", "city": "Nashville", "region": "TN",
                "postal_code": "37211", "country": "US",
            },
        )
        sweep = set_logical_clock("2026-10-01T00:00:00Z")
        assert kid["id"] in sweep["graduated_child_ids"]
        assert get_child(kid["id"])["enrollment_status"] == (
            EnrollmentStatus.GRADUATED.value
        )
        resp = api.create_address_change(
            kid["id"],
            create_address_change_payload(
                {
                    "line1": "9 Nowhere", "city": "Nashville", "region": "TN",
                    "postal_code": "37201", "country": "US",
                }
            ),
            make_affiliate_coordinator_headers(affiliate["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestUndeliverableHoldCycle:
    def test_hold_clears_on_approved_in_area_address_change(self, api):
        """PRD §3.4: "The first consecutive return slides the child from
        `ACTIVE` into `UNDELIVERABLE_HOLD`".
        PRD §3.4: "If `new_postal_prefix` falls inside the child's current
        affiliate coverage, the change is `APPLIED_IN_AREA`: the child's
        `mailing_address` is replaced with `new_address`, `postal_prefix` is
        recomputed, and the address revalidation returns the child to `ACTIVE`
        with `consecutive_returns` reset to zero — this is the way a held
        child clears its hold."

        Design: Difficulty/non_linear_state_machine/child_undeliverable_hold_cycle
        """
        ctx = setup_manifested_wave()
        affiliate, child = ctx["affiliate"], ctx["children"][0]
        item = get_child_wave_item(ctx["wave"]["id"], child["id"])
        mark_item_returned(item["id"])
        held = get_child(child["id"])
        assert held["enrollment_status"] == EnrollmentStatus.UNDELIVERABLE_HOLD.value
        assert held["consecutive_returns"] == 1
        change = create_address_change(child["id"], affiliate["id"], IN_AREA_ADDRESS)
        decided = decide_address_change(change["id"], affiliate["id"], "APPROVE")
        assert decided["status"] == AddressChangeStatus.APPLIED_IN_AREA.value
        after = get_child(child["id"])
        assert after["enrollment_status"] == EnrollmentStatus.ACTIVE.value
        assert after["consecutive_returns"] == 0
        assert after["mailing_address"]["line1"] == "9 Maple Ave"
        assert after["postal_prefix"] == "372"

    def test_hold_cycle_keeps_enrolled_count_and_records_decider(self, api):
        """PRD §2.9: "An affiliate's `enrolled_count` is the count of its
        children whose `enrollment_status` is `ACTIVE` or
        `UNDELIVERABLE_HOLD`; children who are `GRADUATED`, `UNENROLLED`, or
        `TRANSFERRED_OUT` never count."
        PRD §3.4: "`decided_by` records who acted."

        Design: Difficulty/non_linear_state_machine/child_undeliverable_hold_cycle
        """
        ctx = setup_manifested_wave()
        affiliate, child = ctx["affiliate"], ctx["children"][0]
        assert get_affiliate(affiliate["id"])["enrolled_count"] == 3
        item = get_child_wave_item(ctx["wave"]["id"], child["id"])
        mark_item_returned(item["id"])
        assert get_affiliate(affiliate["id"])["enrolled_count"] == 3, (
            "a held child still counts toward enrollment"
        )
        change = create_address_change(child["id"], affiliate["id"], IN_AREA_ADDRESS)
        decided = decide_address_change(change["id"], affiliate["id"], "APPROVE")
        assert decided["decided_by"] == affiliate["id"], (
            "the deciding coordinator's X-User-ID is the affiliate id"
        )
        assert get_affiliate(affiliate["id"])["enrolled_count"] == 3, (
            "an in-area approval never changes the count"
        )


class TestTransferCascade:
    def test_address_transfer_cascades_new_enrollment_and_recounts(self, api):
        """PRD §3.4: "the change is `APPLIED_TRANSFER`: the source child
        becomes `TRANSFERRED_OUT`, and a brand-new child enrollment is
        auto-created on the target affiliate carrying the same `full_name`,
        `family_name`, and `birth_date`, the new `mailing_address`, a
        `registered_month` of the current logical month,
        `transfer_source_child_id` pointing back at the source child, `ACTIVE`
        status, and a fresh zero `consecutive_returns`; the address change's
        `resulting_child_id` records the new enrollment".

        Design: Difficulty/transitive_cascade/address_transfer_cascades_new_enrollment_and_recounts
        """
        base = setup_operative_affiliate()
        program, affiliate_a = base["program"], base["affiliate"]
        second = setup_second_affiliate(
            program, ["371"], name="Memphis Shelby Books",
            contact_email="coord@msb.org",
        )
        affiliate_b = second["affiliate"]
        children = register_children(affiliate_a["id"])
        source = children[0]
        change = create_address_change(
            source["id"], affiliate_a["id"], MEMPHIS_ADDRESS
        )
        decided = decide_address_change(change["id"], affiliate_a["id"], "APPROVE")
        assert decided["status"] == AddressChangeStatus.APPLIED_TRANSFER.value
        new_child_id = decided["resulting_child_id"]
        assert new_child_id, "APPLIED_TRANSFER must record the new enrollment"
        assert get_child(source["id"])["enrollment_status"] == (
            EnrollmentStatus.TRANSFERRED_OUT.value
        )
        new_child = get_child(new_child_id)
        assert new_child["affiliate_id"] == affiliate_b["id"]
        assert new_child["enrollment_status"] == EnrollmentStatus.ACTIVE.value
        assert new_child["transfer_source_child_id"] == source["id"]
        assert new_child["birth_date"].startswith("2026-05-10"), (
            "the new enrollment carries the source child's birth date"
        )
        assert new_child["registered_month"] == "2026-09"
        assert new_child["consecutive_returns"] == 0
        assert new_child["full_name"] == source["full_name"]
        assert new_child["family_name"] == source["family_name"]

    def test_address_transfer_recounts_both_affiliates(self, api):
        """PRD §3.4: "the source affiliate's `enrolled_count` drops by one and
        the target's rises by one, so global enrollment is conserved."

        Design: Difficulty/transitive_cascade/address_transfer_cascades_new_enrollment_and_recounts
        """
        base = setup_operative_affiliate()
        program, affiliate_a = base["program"], base["affiliate"]
        second = setup_second_affiliate(
            program, ["371"], name="Memphis Shelby Books",
            contact_email="coord@msb.org",
        )
        affiliate_b = second["affiliate"]
        children = register_children(affiliate_a["id"])
        source = children[0]
        assert get_affiliate(affiliate_a["id"])["enrolled_count"] == 3
        assert get_affiliate(affiliate_b["id"])["enrolled_count"] == 0
        change = create_address_change(
            source["id"], affiliate_a["id"], MEMPHIS_ADDRESS
        )
        decide_address_change(change["id"], affiliate_a["id"], "APPROVE")
        assert get_affiliate(affiliate_a["id"])["enrolled_count"] == 2
        assert get_affiliate(affiliate_b["id"])["enrolled_count"] == 1


class TestTransferBranchDependency:
    def test_transfer_branch_unenrolls_when_target_not_operative(self, api):
        """PRD §3.4: "The target is chosen by a selector over every affiliate
        whose `postal_prefixes` contain `new_postal_prefix` and that is
        operative in the current logical month".
        PRD §3.4: "If that selector finds nobody, the third branch applies:
        `APPLIED_UNENROLLED` moves the child to `UNENROLLED` with
        `unenroll_reason` set to `MOVED_OUT_OF_AREA`, `resulting_child_id`
        stays null, and the affiliate count is recomputed."

        Design: Difficulty/cross_entity_state_dependency/transfer_branch_depends_on_target_agreement_state
        """
        base = setup_operative_affiliate()
        program, affiliate_a = base["program"], base["affiliate"]
        setup_second_affiliate(
            program, ["371"], approve=False, name="Memphis Shelby Books",
            contact_email="coord@msb.org",
        )
        child = register_children(affiliate_a["id"], DEFAULT_CHILD_SPECS[:2])[0]
        change = create_address_change(
            child["id"], affiliate_a["id"], MEMPHIS_ADDRESS
        )
        decided = decide_address_change(change["id"], affiliate_a["id"], "APPROVE")
        assert decided["status"] == AddressChangeStatus.APPLIED_UNENROLLED.value, (
            "the covering affiliate is not operative (agreement still "
            "PENDING_APPROVAL), so the selector finds nobody"
        )
        assert decided["resulting_child_id"] is None
        after = get_child(child["id"])
        assert after["enrollment_status"] == EnrollmentStatus.UNENROLLED.value
        assert after["unenroll_reason"] == UnenrollReason.MOVED_OUT_OF_AREA.value

    def test_transfer_branch_transfers_once_target_agreement_active(self, api):
        """PRD §3.4: "If the new prefix is not covered by the current affiliate
        but is covered by a different operative affiliate, the change is
        `APPLIED_TRANSFER`".
        PRD §3.2: "On approval the agreement becomes `ACTIVE` ... and the
        affiliate's `operative` flag is recomputed — flipping true once the
        current logical month is fully covered."

        Design: Difficulty/cross_entity_state_dependency/transfer_branch_depends_on_target_agreement_state
        """
        base = setup_operative_affiliate()
        program, affiliate_a = base["program"], base["affiliate"]
        second = setup_second_affiliate(
            program, ["371"], approve=False, name="Memphis Shelby Books",
            contact_email="coord@msb.org",
        )
        affiliate_b = second["affiliate"]
        children = register_children(affiliate_a["id"], DEFAULT_CHILD_SPECS[:2])
        approve_agreement(second["agreement"]["id"], program["id"])
        change = create_address_change(
            children[1]["id"],
            affiliate_a["id"],
            {
                "line1": "8 Beale St", "city": "Memphis", "region": "TN",
                "postal_code": "37105", "country": "US",
            },
        )
        decided = decide_address_change(change["id"], affiliate_a["id"], "APPROVE")
        assert decided["status"] == AddressChangeStatus.APPLIED_TRANSFER.value
        assert decided["resulting_child_id"], "transfer creates a new enrollment"
        assert get_child(children[1]["id"])["enrollment_status"] == (
            EnrollmentStatus.TRANSFERRED_OUT.value
        )
        assert get_affiliate(affiliate_b["id"])["enrolled_count"] == 1


class TestTransferConservation:
    def test_transfer_conserves_global_enrollment_count(self, api):
        """PRD §3.4: "the source affiliate's `enrolled_count` drops by one and
        the target's rises by one, so global enrollment is conserved."

        Design: Difficulty/compensating_invariant/transfer_conserves_global_enrollment_count
        """
        base = setup_operative_affiliate()
        program, affiliate_a = base["program"], base["affiliate"]
        second = setup_second_affiliate(
            program, ["371"], name="Memphis Shelby Books",
            contact_email="coord@msb.org",
        )
        affiliate_b = second["affiliate"]
        children = register_children(affiliate_a["id"])
        register_child(
            affiliate_b["id"],
            full_name="Jo Knapp",
            family_name="Knapp",
            birth_date="2026-03-01T00:00:00Z",
            mailing_address={
                "line1": "11 Front St", "city": "Memphis", "region": "TN",
                "postal_code": "37101", "country": "US",
            },
        )
        before_a = get_affiliate(affiliate_a["id"])["enrolled_count"]
        before_b = get_affiliate(affiliate_b["id"])["enrolled_count"]
        assert (before_a, before_b) == (3, 1)
        change = create_address_change(
            children[0]["id"], affiliate_a["id"], MEMPHIS_ADDRESS
        )
        decide_address_change(change["id"], affiliate_a["id"], "APPROVE")
        after_a = get_affiliate(affiliate_a["id"])["enrolled_count"]
        after_b = get_affiliate(affiliate_b["id"])["enrolled_count"]
        assert (after_a, after_b) == (2, 2)
        assert after_a + after_b == before_a + before_b, (
            "global non-terminal enrollment is conserved across the transfer"
        )

    def test_transfer_leaves_no_double_counted_child(self, api):
        """PRD §2.9: "An affiliate's `enrolled_count` is the count of its
        children whose `enrollment_status` is `ACTIVE` or
        `UNDELIVERABLE_HOLD`; children who are `GRADUATED`, `UNENROLLED`, or
        `TRANSFERRED_OUT` never count."
        PRD §3.3: "Children can be listed with `affiliate_id`,
        `enrollment_status`, and `transfer_source_child_id` filters".

        Design: Difficulty/compensating_invariant/transfer_conserves_global_enrollment_count
        """
        base = setup_operative_affiliate()
        program, affiliate_a = base["program"], base["affiliate"]
        second = setup_second_affiliate(
            program, ["371"], name="Memphis Shelby Books",
            contact_email="coord@msb.org",
        )
        affiliate_b = second["affiliate"]
        children = register_children(affiliate_a["id"])
        own = register_child(
            affiliate_b["id"],
            full_name="Jo Knapp",
            family_name="Knapp",
            birth_date="2026-03-01T00:00:00Z",
            mailing_address={
                "line1": "11 Front St", "city": "Memphis", "region": "TN",
                "postal_code": "37101", "country": "US",
            },
        )
        change = create_address_change(
            children[0]["id"], affiliate_a["id"], MEMPHIS_ADDRESS
        )
        decided = decide_address_change(change["id"], affiliate_a["id"], "APPROVE")
        rows, meta = validate_paginated(
            api.list_children(
                _ADMIN, params={"enrollment_status": "ACTIVE", "limit": 100}
            )
        )
        assert meta["total_count"] == 4
        active_ids = {row["id"] for row in rows}
        assert active_ids == {
            children[1]["id"],
            children[2]["id"],
            own["id"],
            decided["resulting_child_id"],
        }, "the transferred-out child is gone and the new enrollment appears exactly once"
        assert get_child(children[0]["id"])["enrollment_status"] == (
            EnrollmentStatus.TRANSFERRED_OUT.value
        )
