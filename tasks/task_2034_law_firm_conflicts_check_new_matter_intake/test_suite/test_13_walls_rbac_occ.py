"""Wall membership guards, RBAC denials (including segregation of duties),
optimistic concurrency control, roster-add supersede cascade, and immediate
read-after-write consistency."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_roster_party,
    api_client,
    consent_waiver,
    create_attorney,
    create_conflicts_partner,
    create_letter,
    create_engagement_letter_payload,
    create_matter,
    create_party,
    create_wall,
    get_success_data,
    issue_letter,
    list_hits_for_check,
    make_client_headers,
    make_conflicts_partner_headers,
    make_responsible_attorney_headers,
    run_conflict_check,
    send_waiver,
    setup_basic_matter,
    setup_matter_with_confirmed_hit,
    setup_matter_with_wall,
    setup_matter_with_waiver,
    transition_wall_payload,
    validate_error,
    validate_success,
)

INTAKE = TEST_USERS["intake_specialist_headers"]


class TestWallExclusionMembershipErrors:
    def test_exclude_already_excluded_attorney_rejected(self):
        """PRD §3.5: "While a wall is `ACTIVE`, its exclusion list can be
        amended in place: an `EXCLUDE` action carrying an `attorney_id` appends
        that attorney, failing with `ERR_ATTORNEY_ALREADY_EXCLUDED` if the
        attorney is already listed, and a `RELEASE` action removes the named
        attorney, failing with `ERR_ATTORNEY_NOT_EXCLUDED` if the attorney is
        not currently listed."

        Design: Corner/errors/c_wall_exclusion_membership_errors
        """
        party, atty_r, atty_a, partner, matter, wall = setup_matter_with_wall(
            "Membership Client Inc"
        )
        resp = api_client.transition_ethical_wall(
            wall["id"],
            transition_wall_payload("EXCLUDE", attorney_id=atty_a["id"]),
            make_conflicts_partner_headers(partner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ATTORNEY_ALREADY_EXCLUDED)

    def test_release_never_excluded_attorney_rejected(self):
        """PRD §3.5: "While a wall is `ACTIVE`, its exclusion list can be
        amended in place: an `EXCLUDE` action carrying an `attorney_id` appends
        that attorney, failing with `ERR_ATTORNEY_ALREADY_EXCLUDED` if the
        attorney is already listed, and a `RELEASE` action removes the named
        attorney, failing with `ERR_ATTORNEY_NOT_EXCLUDED` if the attorney is
        not currently listed."

        Design: Corner/errors/c_wall_exclusion_membership_errors
        """
        party, atty_r, atty_a, partner, matter, wall = setup_matter_with_wall(
            "Membership Client Inc"
        )
        atty_b = create_attorney(full_name="Bella Beta", bar_number="BAR004")
        resp = api_client.transition_ethical_wall(
            wall["id"],
            transition_wall_payload("RELEASE", attorney_id=atty_b["id"]),
            make_conflicts_partner_headers(partner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ATTORNEY_NOT_EXCLUDED)


class TestWallDoubleLiftRejected:
    def test_second_lift_fails_wall_invalid_state(self):
        """PRD §3.5: "A `LIFT` action — available from `ACTIVE` only — moves
        the wall to `LIFTED`, stamps `lifted_at` from the logical clock, and
        immediately restores read access to every formerly excluded attorney. A
        second lift, or any `EXCLUDE` or `RELEASE` attempted after a lift, is
        rejected with `ERR_WALL_INVALID_STATE`."

        Design: Corner/state_machines/c_wall_double_lift_rejected
        """
        party, atty_r, atty_a, partner, matter, wall = setup_matter_with_wall(
            "Wall State Client Inc"
        )
        cp = make_conflicts_partner_headers(partner["id"])
        lifted = validate_success(
            api_client.transition_ethical_wall(
                wall["id"], transition_wall_payload("LIFT"), cp
            ),
            200,
        )
        assert lifted["status"] == "LIFTED"

        resp = api_client.transition_ethical_wall(
            wall["id"], transition_wall_payload("LIFT"), cp
        )
        validate_error(resp, ApiErrorId.ERR_WALL_INVALID_STATE)


class TestHitReviewByNonResponsibleAttorney:
    def test_active_attorney_not_responsible_cannot_review(self):
        """PRD §3.4: "A hit may be reviewed by the matter's responsible
        attorney or by any `ConflictsPartner`; the reviewer submits a
        `decision` of `CONFIRMED` or `DISMISSED` with an optional `note`,
        stored verbatim as `review_note`. The hit must still be `PENDING` —
        reviewing a hit already `CONFIRMED`, `DISMISSED`, `WAIVED`, or `STALE`
        fails with `ERR_HIT_NOT_PENDING` — and a `ResponsibleAttorney` caller
        who is not the responsible attorney of the check's matter is rejected
        with `ERR_NOT_RESPONSIBLE_ATTORNEY`."

        Design: Corner/rbac/c_hit_review_by_non_responsible_attorney
        """
        p_x = create_party("Ownership X Inc")
        p_y = create_party("Ownership Y Corp")
        ra = create_attorney()
        other = create_attorney(full_name="Oscar Other", bar_number="BAR005")
        create_matter(p_x["id"], ra["id"], matter_title="M0")
        m1 = create_matter(p_y["id"], ra["id"], matter_title="M1")
        add_roster_party(m1["id"], p_x["id"], "ADVERSE")
        chk = run_conflict_check(m1["id"], "STRICT")
        hit = list_hits_for_check(chk["id"])[0]

        resp = api_client.review_conflict_hit(
            hit["id"],
            {"decision": "CONFIRMED"},
            make_responsible_attorney_headers(other["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_RESPONSIBLE_ATTORNEY)


class TestSodSelfApprovalRejected:
    def test_requester_cannot_approve_own_waiver_even_as_partner(self):
        """PRD §3.6: "An `APPROVE` action belongs to a `ConflictsPartner` and
        is bound by segregation of duties: the approver's `X-User-ID` must
        differ from the waiver's `requested_by_attorney_id`, or the request
        fails with `ERR_SOD_SELF_APPROVAL`."

        Design: Corner/rbac/c_sod_self_approval_rejected
        """
        p_x, p_y, ra, m1, hit, waiver = setup_matter_with_waiver(
            "Sod X Inc", "Sod Y Corp"
        )
        partner = create_conflicts_partner()
        send_waiver(waiver["id"], ra)
        consented = consent_waiver(waiver["id"], p_y, "doc-1")
        assert consented["status"] == "CONSENTED"

        # The requester attorney wearing the ConflictsPartner role hat.
        resp = api_client.transition_waiver_request(
            waiver["id"],
            {"action": "APPROVE"},
            make_conflicts_partner_headers(ra["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SOD_SELF_APPROVAL)

        # A different partner succeeds.
        approved = validate_success(
            api_client.transition_waiver_request(
                waiver["id"],
                {"action": "APPROVE"},
                make_conflicts_partner_headers(partner["id"]),
            ),
            200,
        )
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_attorney_id"] == partner["id"]


class TestClientCannotRunConflictCheckForbidden:
    def test_client_role_not_in_check_endpoint_roles(self):
        """PRD §2.1: "Each endpoint admits a fixed set of roles (§4), and
        transition-style endpoints further restrict individual actions within
        an endpoint to particular roles; a caller whose role is not admitted to
        the attempted operation is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §3.4: "Running a conflict check is available to an
        `IntakeSpecialist` or a `ResponsibleAttorney` while the matter is
        `INTAKE` or `OPEN`; on a terminal matter the attempt fails with
        `ERR_MATTER_TERMINAL`."

        Design: Corner/rbac/c_client_cannot_run_conflict_check_forbidden
        """
        party, atty, matter = setup_basic_matter("Curious Client Inc",
                                                 matter_title="M1")
        resp = api_client.create_conflict_check(
            matter["id"],
            {"search_variant": "STRICT"},
            make_client_headers(party["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestOccPatchStaleVersion412:
    def test_patch_with_current_version_succeeds_then_stale_replay_fails(self):
        """PRD §2.10: "Two write operations participate in optimistic
        concurrency control over the matter row: amending a matter's intake
        fields (`PATCH /intake/matters/{id}`) and creating an engagement letter
        for a matter (`POST /intake/matters/{id}/engagement-letters`). Each
        such request must carry `expected_matter_version`, a non-optional input
        field holding the matter `version` the caller last observed. If the
        matter's current `version` no longer equals that value, the request is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/c_occ_patch_stale_version_412
        """
        party, atty, matter = setup_basic_matter("Occ Client Inc")
        assert matter["version"] == 1

        amended = validate_success(
            api_client.patch_matter(
                matter["id"],
                {"matter_title": "M amended", "expected_matter_version": 1},
                INTAKE,
            ),
            200,
        )
        assert amended["matter_title"] == "M amended"
        assert amended["version"] == 2

        resp = api_client.patch_matter(
            matter["id"],
            {"matter_title": "M amended twice", "expected_matter_version": 1},
            INTAKE,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)


class TestOccLetterCreateStaleVersion412:
    def test_letter_create_with_superseded_matter_version_fails(self):
        """PRD §2.10: "Two write operations participate in optimistic
        concurrency control over the matter row: amending a matter's intake
        fields (`PATCH /intake/matters/{id}`) and creating an engagement letter
        for a matter (`POST /intake/matters/{id}/engagement-letters`). ...
        If the matter's current `version` no longer equals that value, the
        request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/c_occ_letter_create_stale_version_412
        """
        party, atty, matter = setup_basic_matter("Occ Letter Client Inc")
        assert matter["version"] == 1

        patched = validate_success(
            api_client.patch_matter(
                matter["id"],
                {"matter_title": "M v2", "expected_matter_version": 1},
                INTAKE,
            ),
            200,
        )
        assert patched["version"] == 2, "PATCH advanced the matter"

        resp = api_client.create_engagement_letter(
            matter["id"],
            create_engagement_letter_payload(1),
            make_responsible_attorney_headers(atty["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)


class TestPartyAddSupersedeCascadeEndToEnd:
    def test_roster_add_supersedes_check_stales_hit_and_unclears_matter(self):
        """PRD §3.3: "Because the roster feeds the conflict-search query set,
        every addition supersedes the matter's `COMPLETED` checks of `INTAKE`
        kind, moves any of their hits still `PENDING` to `STALE` with each
        staled hit's `version` incremented, recomputes `clearance_status`, and
        increments the matter's `version`."
        PRD §2.8: "`CLEARED` → `UNCHECKED` when a roster change supersedes all
        of the matter's intake checks so that no non-superseded checks remain".

        Design: Corner/complexity_layers/c_party_add_supersede_cascade_end_to_end
        """
        p_x = create_party("Cascade X Inc")
        p_y = create_party("Cascade Y Corp")
        p_z = create_party("Cascade Z Witness LLC")
        atty = create_attorney()
        create_matter(p_x["id"], atty["id"], matter_title="M0")
        m1 = create_matter(p_y["id"], atty["id"], matter_title="M1")
        add_roster_party(m1["id"], p_x["id"], "ADVERSE")
        chk = run_conflict_check(m1["id"], "STRICT")
        assert chk["hit_count"] == 1, (
            "pre-cascade the check completed with one PENDING hit"
        )
        hit = list_hits_for_check(chk["id"])[0]
        assert hit["review_status"] == "PENDING"

        # One roster add cascades three levels of observable state.
        add_roster_party(m1["id"], p_z["id"], "WITNESS")

        checks = get_success_data(
            api_client.list_matter_conflict_checks(m1["id"], INTAKE), 200
        )
        assert checks[0]["status"] == "SUPERSEDED", "hop 1"
        hit_after = get_success_data(
            api_client.get_conflict_hit(hit["id"], INTAKE), 200
        )
        assert hit_after["review_status"] == "STALE", (
            "hop 2: PENDING hits of a superseded check stale out"
        )
        m1_after = get_success_data(api_client.get_matter(m1["id"], INTAKE), 200)
        assert m1_after["clearance_status"] == "UNCHECKED", (
            "hop 3: precedence rule 5 — no non-superseded checks remain"
        )


class TestImmediateReadAfterWriteConsistency:
    def test_patch_response_and_immediate_get_agree(self):
        """PRD §2.4: "Consistency is immediate: every mutation and all of its
        cascaded effects are visible in the same request's response and in any
        re-read that follows it."
        PRD §3.3: "Amendments follow the same discipline. An `IntakeSpecialist`
        may amend `matter_title`, `practice_group`, or
        `responsible_attorney_id`, and every such request must carry the OCC
        token `expected_matter_version` described in §2.10."

        Design: Corner/consistency_model/c_immediate_read_after_write_consistency
        """
        party, atty, matter = setup_basic_matter("Consistent Client Inc",
                                                 matter_title="Before")
        assert matter["version"] == 1

        patched = validate_success(
            api_client.patch_matter(
                matter["id"],
                {"matter_title": "After", "expected_matter_version": 1},
                INTAKE,
            ),
            200,
        )
        assert patched["matter_title"] == "After"
        assert patched["version"] == 2, "response reflects the write"

        reread = get_success_data(api_client.get_matter(matter["id"], INTAKE), 200)
        assert reread["matter_title"] == "After"
        assert reread["version"] == 2, (
            "immediate re-read agrees with the mutation response"
        )
