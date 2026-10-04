"""Party designations and group seats: creation, reverse-lookup listing,
uniqueness scopes, group-state gating, and seating conservation under
expulsion (PRD §3.3, §3.4).
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    assert_party_designation,
    create_accident_case_payload,
    create_designation,
    create_group,
    create_org,
    create_party_designation_payload,
    create_seat,
    create_seat_payload,
    expel_designation,
    find_seat,
    get_designation,
    get_group,
    record_conduct_violation,
    set_clock,
    setup_adopted_case,
    setup_group_completed,
    setup_launched_investigation,
    setup_on_scene,
    validate_error,
    validate_paginated,
    validate_success,
)

DUTY_OFFICER = TEST_USERS["duty_officer_headers"]
PARTY_COORDINATOR = TEST_USERS["party_coordinator_headers"]


class TestDesignationCreationAndListing:
    def test_designation_creation_starts_active_and_round_trips(self, api):
        """PRD §3.3: "the coordinator submits a payload containing the
        `investigation_id` and the `organization_id`, and the server records an
        `ACTIVE` designation stamped with `designated_at` from the logical
        clock."

        Design: Corner/entities/designation_creation_starts_active_and_round_trips
        """
        ctx = setup_launched_investigation()
        org = create_org(legal_name="Blue Ridge Transit Authority", org_type="OPERATOR")

        resp = api.create_party_designation(
            create_party_designation_payload(ctx["investigation"]["id"], org["id"]),
            PARTY_COORDINATOR,
        )
        designation = validate_success(resp, expected_status=201)
        assert_party_designation(designation)
        assert designation["status"] == "ACTIVE"
        # Stamped from the logical clock, which the chain pinned at the
        # initial 2026-09-01T00:00:00Z (prefix-compared: the exact fractional
        # rendering of a logical-clock stamp is not pinned by the PRD).
        assert designation["designated_at"].startswith("2026-09-01T00:00:00")

        reread = get_designation(designation["id"])
        assert reread["investigation_id"] == ctx["investigation"]["id"]
        assert reread["organization_id"] == org["id"]
        assert reread["version"] == 1
        assert reread["group_seats"] == []

    def test_designation_list_paginates_and_filters(self, api):
        """PRD §2.3: "`limit` specifies the maximum number of items to return:
        it defaults to 10 when omitted, accepts a minimum of 1 and a maximum of
        100. `offset` specifies how many items to skip: it defaults to 0 and
        may never be negative." PRD §2.3: "party designations by
        `investigation_id`, `organization_id`, and `status`". PRD §2.3: "The
        `meta` object of a list response carries the four pagination fields
        `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/designation_list_paginates_and_filters
        """
        ctx = setup_on_scene()
        inv_id = ctx["investigation"]["id"]
        org_b = create_org(legal_name="Piedmont Airframe Works", org_type="MANUFACTURER")
        create_designation(inv_id, org_b["id"])
        org_c = create_org(legal_name="Allied Signalmens Union", org_type="UNION")
        create_designation(inv_id, org_c["id"])

        rows, meta = validate_paginated(
            api.list_party_designations(
                DUTY_OFFICER, params={"investigation_id": inv_id, "limit": 2, "offset": 0}
            )
        )
        assert len(rows) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2 and meta["offset"] == 0

        rows, meta = validate_paginated(
            api.list_party_designations(
                DUTY_OFFICER, params={"investigation_id": inv_id, "limit": 2, "offset": 2}
            )
        )
        assert len(rows) == 1
        assert meta["total_count"] == 3
        assert meta["has_more"] is False

        rows, _ = validate_paginated(
            api.list_party_designations(
                DUTY_OFFICER, params={"investigation_id": inv_id, "status": "ACTIVE"}
            )
        )
        assert len(rows) == 3

        rows, _ = validate_paginated(
            api.list_party_designations(
                DUTY_OFFICER, params={"organization_id": org_b["id"]}
            )
        )
        assert len(rows) == 1
        assert rows[0]["organization_id"] == org_b["id"]

    def test_body_foreign_keys_checked_in_declared_input_order(self, api):
        """PRD §2.6: "Only after every path identifier resolves are foreign
        keys in the request body validated, in the endpoint's declared input
        order." PRD §3.3 declares the designation payload as "`investigation_id`
        and the `organization_id`."

        Design: Corner/validations/body_foreign_keys_checked_in_declared_input_order
        """
        ctx = setup_launched_investigation()
        inv_id = ctx["investigation"]["id"]

        resp = api.create_party_designation(
            create_party_designation_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID),
            PARTY_COORDINATOR,
        )
        validate_error(resp, ApiErrorId.ERR_INVESTIGATION_NOT_FOUND)

        resp = api.create_party_designation(
            create_party_designation_payload(inv_id, NON_EXISTENT_UUID),
            PARTY_COORDINATOR,
        )
        validate_error(resp, ApiErrorId.ERR_PARTY_ORGANIZATION_NOT_FOUND)

        rows, _ = validate_paginated(
            api.list_party_designations(DUTY_OFFICER, params={"investigation_id": inv_id})
        )
        assert rows == []

    def test_duplicate_seat_designation_and_report_number_conflicts(self, api):
        """PRD §3.1: "a duplicate submission is rejected with
        `ERR_DUPLICATE_REPORT_NUMBER`". PRD §3.3: "while an `ACTIVE`
        designation already exists for the same investigation and organization,
        a second designation for that pair is rejected with
        `ERR_DUPLICATE_DESIGNATION`." PRD §3.3: "A designation may hold only
        one `SEATED` seat on a given group; a repeat is rejected with
        `ERR_DUPLICATE_SEAT`."

        Design: Corner/validations/duplicate_seat_designation_and_report_number_conflicts
        """
        ctx = setup_on_scene()
        inv_id = ctx["investigation"]["id"]

        resp = api.create_accident_case(
            create_accident_case_payload(report_number=ctx["case"]["report_number"]),
            DUTY_OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_REPORT_NUMBER)

        resp = api.create_party_designation(
            create_party_designation_payload(inv_id, ctx["org"]["id"]),
            PARTY_COORDINATOR,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_DESIGNATION)

        resp = api.create_seat(
            ctx["designation"]["id"],
            create_seat_payload(ctx["group"]["id"]),
            TEST_USERS["iic_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SEAT)

        rows, _ = validate_paginated(
            api.list_party_designations(DUTY_OFFICER, params={"investigation_id": inv_id})
        )
        assert len(rows) == 1


class TestSeatGroupStateGate:
    def test_seat_creation_rejected_on_complete_group(self, api):
        """PRD §3.3: "the designation must be `ACTIVE`
        (`ERR_DESIGNATION_NOT_ACTIVE`) and the group `ACTIVE`
        (`ERR_GROUP_NOT_ACTIVE`)."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_seat_gated_by_group_status
        """
        ctx = setup_group_completed()
        group = ctx["group"]
        assert group["status"] == "COMPLETE"
        assert group["seated_count"] == 1

        org2 = create_org(legal_name="Allied Signalmens Union", org_type="UNION")
        designation2 = create_designation(ctx["investigation"]["id"], org2["id"])
        assert designation2["status"] == "ACTIVE"

        resp = api.create_seat(
            designation2["id"],
            create_seat_payload(group["id"]),
            TEST_USERS["iic_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_GROUP_NOT_ACTIVE)

        # The designation itself is valid; only the group state blocks.
        assert get_designation(designation2["id"])["status"] == "ACTIVE"
        after = get_group(group["id"])
        assert after["status"] == "COMPLETE"
        assert after["seated_count"] == 1

    def test_seat_creation_rejected_on_disbanded_group(self, api):
        """PRD §3.3: "the group `ACTIVE` (`ERR_GROUP_NOT_ACTIVE`)" — a group
        reaches `DISBANDED` only through the adoption cascade (PRD §3.8: "every
        group still `ACTIVE` or `COMPLETE` is `DISBANDED`"), and any non-ACTIVE
        group rejects seating.

        Design: Difficulty/cross_entity_state_dependency/cross_entity_seat_gated_by_group_status
        """
        ctx = setup_adopted_case()
        group = ctx["group"]
        assert group["status"] == "DISBANDED"

        org2 = create_org(legal_name="Seaboard Railcar Manufacturing", org_type="MANUFACTURER")
        designation2 = create_designation(ctx["investigation"]["id"], org2["id"])
        resp = api.create_seat(
            designation2["id"],
            create_seat_payload(group["id"]),
            TEST_USERS["iic_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_GROUP_NOT_ACTIVE)


class TestSeatingConservationUnderExpulsion:
    def test_seat_then_expel_conserves_group_seated_count(self, api):
        """PRD §3.3: "A group's `seated_count` is the count of seats
        referencing that group, across every designation of the same
        investigation, whose status is `SEATED`; it is recomputed on every seat
        creation, suspension, or removal." PRD §3.4: "Every embedded seat in
        `SEATED` or `SUSPENDED` status becomes `REMOVED`, and each referenced
        group's `seated_count` is recomputed."

        Design: Difficulty/compensating_invariant/compensating_invariant_seat_then_expel_conserves_seating
        """
        ctx = setup_on_scene()
        group = ctx["group"]
        assert group["seated_count"] == 1  # the first party's seat

        org_d = create_org(legal_name="Piedmont Airframe Works", org_type="MANUFACTURER")
        designation_d = create_designation(ctx["investigation"]["id"], org_d["id"])
        designation_d = create_seat(designation_d["id"], group["id"])
        seat_d = find_seat(designation_d, group_id=group["id"])
        assert get_group(group["id"])["seated_count"] == 2

        record_conduct_violation(
            designation_d["id"],
            seat_d["seat_id"],
            violation_kind="PREMATURE_PUBLIC_STATEMENT",
            detail="Manufacturer issued a press release attributing cause before the factual docket opened.",
        )
        expelled = expel_designation(
            designation_d["id"], reason="Premature public statement."
        )
        assert expelled["status"] == "EXPELLED"
        assert find_seat(expelled, seat_id=seat_d["seat_id"])["status"] == "REMOVED"

        # The seat+expel pair leaves the conserved quantity unchanged.
        group_after = get_group(group["id"])
        assert group_after["seated_count"] == 1
        # An ACTIVE group does not revert; only COMPLETE groups do (PRD §3.4).
        assert group_after["status"] == "ACTIVE"
        # The unrelated party's seat is untouched.
        designation_e = get_designation(ctx["designation"]["id"])
        assert find_seat(designation_e, group_id=group["id"])["status"] == "SEATED"

    def test_expulsion_conserves_seating_per_group(self, api):
        """PRD §3.3: "A group's `seated_count` is the count of seats
        referencing that group, across every designation of the same
        investigation, whose status is `SEATED`" — the conserved quantity is
        scoped per group, so removing a seat from one group leaves a sibling
        group's count untouched.

        Design: Difficulty/compensating_invariant/compensating_invariant_seat_then_expel_conserves_seating
        """
        ctx = setup_on_scene()
        group1 = ctx["group"]
        group2 = create_group(
            ctx["investigation"]["id"], specialty="STRUCTURES", chairman_user_id="gc-2"
        )

        org_d = create_org(legal_name="Piedmont Airframe Works", org_type="MANUFACTURER")
        designation_d = create_designation(ctx["investigation"]["id"], org_d["id"])
        designation_d = create_seat(designation_d["id"], group2["id"])
        seat_d = find_seat(designation_d, group_id=group2["id"])
        assert get_group(group1["id"])["seated_count"] == 1
        assert get_group(group2["id"])["seated_count"] == 1

        record_conduct_violation(
            designation_d["id"],
            seat_d["seat_id"],
            violation_kind="PREMATURE_PUBLIC_STATEMENT",
            detail="Press release before the docket opened.",
        )
        expel_designation(designation_d["id"], reason="Premature public statement.")

        assert get_group(group2["id"])["seated_count"] == 0
        assert get_group(group2["id"])["status"] == "ACTIVE"
        assert get_group(group1["id"])["seated_count"] == 1
