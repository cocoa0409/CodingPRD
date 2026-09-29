"""Role boundaries: what each of the six roles may and may not do.

Section 2.1 gives six roles with no session, no token exchange and no notion of
one caller holding two roles, and section 4 fixes the role list endpoint by
endpoint. The interesting cases are the ones where an over-broad implementation
would leak an override: the officer that drove a cycle up to communication, the
platform operator that owns the widest write grant, the analyst that worked a
dispute, and the donor whose read grant covers URLs it may never post to. Each
test pairs the refusal with the call that proves the refusal was the role gate
and not a version stamp, a state gate or an ownership check.
"""

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_FORBIDDEN_ROLE,
    ERR_INVALID_STATE,
    ERR_NOT_RESOURCE_OWNER,
)
from test_helpers.assertions import (
    assert_cents,
    assert_page_meta,
    assert_points,
    validate_error,
    validate_list,
    validate_success,
)
from test_helpers.constants import (
    ALUMNUS,
    ATHLETICS_ANNUAL,
    BASIS_DEATH,
    DECISION_DENY,
    DECISION_UPHOLD,
    DISPUTE_DENIED,
    DISPUTE_SUBMITTED,
    DISPUTE_UNDER_REVIEW,
    DISPUTE_UPHELD,
    DONOR_DECEASED,
    EVENT_DRAFT,
    INDIVIDUAL,
    NON_ALUMNUS,
    POLICY_REFUSE,
    RECALC_CERTIFIED,
    RECALC_COMMUNICATED,
    RECALC_COMPUTED,
    RECALC_DRAFT,
    ROLE_DISPUTE_ANALYST,
    ROLE_POLICY_COMMITTEE,
    TRANSFER_APPROVED,
    TRANSFER_REQUESTED,
)
from test_helpers.fixtures import (
    add_received_gift,
    certified_cycle,
    change_status,
    communicate_cycle,
    communicated_cycle,
    create_event,
    create_section_with_seats,
    file_dispute,
    open_cycle,
    read_cycle,
    read_dispute,
    read_donor,
    read_section,
    register_donor,
    request_transfer_ok,
    run_cycle,
)
from test_helpers.test_users import (
    ADMIN,
    ANALYST,
    ANALYST_USER_ID,
    CERTIFIER,
    CERTIFIER_USER_ID,
    OFFICER,
    OFFICER_USER_ID,
    POLICY,
    POLICY_USER_ID,
    headers_for,
    make_donor_headers,
)

GIFT_INSTANT = f.instant(2026, 3, 1)
DEATH_INSTANT = f.instant(2026, 3, 15)


def _a_communicated_cycle(client, cycle_year=2026):
    """DRAFT -> COMPUTED -> COMMUNICATED under officer-1, read back fresh."""
    cycle = communicated_cycle(client, cycle_year)
    return read_cycle(client, cycle["id"])


def _a_scored_donor(client, alumni_status=NON_ALUMNUS):
    """One donor with a single 1,000,000-cent RECEIVED 2026 athletics gift."""
    donor = register_donor(
        client, alumni_status=alumni_status, entity_type=INDIVIDUAL
    )
    add_received_gift(
        client,
        donor["id"],
        1000000,
        GIFT_INSTANT,
        designation=ATHLETICS_ANNUAL,
    )
    return donor


def _a_dispute_under_review(client):
    """A dispute the analyst has taken under review on a communicated cycle."""
    donor = _a_scored_donor(client)
    cycle = _a_communicated_cycle(client)
    dispute = file_dispute(client, donor["id"], cycle["id"], 4.00)
    reviewed = validate_success(client.review_dispute(dispute["id"], headers=ANALYST))
    return donor, cycle, reviewed


def _a_submitted_dispute(client):
    """A dispute nobody has reviewed yet, filed by the development office."""
    donor = _a_scored_donor(client)
    cycle = _a_communicated_cycle(client)
    dispute = file_dispute(client, donor["id"], cycle["id"], 2.00, headers=OFFICER)
    return donor, cycle, dispute


class TestOnlyThePointsCertifierMayCertifyACycle:
    """Certify is the certifier's alone, with no development-office override."""

    def test_the_officer_that_drove_the_cycle_cannot_freeze_it(self, client):
        """Neither the initiating officer nor the platform operator may certify.

        PRD 3.5: "Certification is the single most consequential act in the
        system, and it belongs to the `PointsCertifier` alone."

        PRD 4: "Freeze the cycle, assign ranks, and cascade staleness into
        published slots, events and relocation requests. Requires a certifier
        other than the initiator. | `PointsCertifier` |"

        PRD 2.1: "A `PlatformAdmin` may also perform every development-office
        write except the ones reserved to the certifier, the analyst and the
        committee."

        Design: Corner/rbac/development_officer_cannot_certify_the_cycle_it_ran_but_the_certifier_can
        """
        cycle = _a_communicated_cycle(client)
        payload = f.certify_payload(cycle["version"])

        validate_error(
            client.certify_recalculation(cycle["id"], payload, headers=OFFICER),
            ERR_FORBIDDEN_ROLE,
            403,
        )
        validate_error(
            client.certify_recalculation(cycle["id"], payload, headers=ADMIN),
            ERR_FORBIDDEN_ROLE,
            403,
        )

        after = read_cycle(client, cycle["id"])
        assert after["status"] == RECALC_COMMUNICATED
        assert after["version"] == cycle["version"]
        assert after["certified_by_user_id"] is None
        assert after["certified_at"] is None

    def test_the_certifier_freezes_it_with_the_very_same_version_stamp(self, client):
        """The same payload that was refused twice succeeds for the right role.

        PRD 2.1: "If both headers are present but the value of `X-User-Role` is
        not one of the roles listed for the endpoint being called, the request is
        rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        PRD 3.5: "Certification is the single most consequential act in the
        system, and it belongs to the `PointsCertifier` alone."

        Design: Corner/rbac/development_officer_cannot_certify_the_cycle_it_ran_but_the_certifier_can
        """
        cycle = _a_communicated_cycle(client)
        payload = f.certify_payload(cycle["version"])

        validate_error(
            client.certify_recalculation(cycle["id"], payload, headers=OFFICER),
            ERR_FORBIDDEN_ROLE,
            403,
        )
        certified = validate_success(
            client.certify_recalculation(cycle["id"], payload, headers=CERTIFIER)
        )
        assert certified["status"] == RECALC_CERTIFIED
        assert certified["certified_by_user_id"] == CERTIFIER_USER_ID


class TestThePointsCertifierHoldsNoComputeSideWrite:
    """Reads are shared with the certifier; the compute-side writes are not."""

    def test_the_certifier_cannot_run_the_cycle_it_will_later_freeze(self, client):
        """The run is refused, the same row reads back fine, the officer runs it.

        PRD 4: "Score every donor under both point variants and append the ledger
        generation. | `DevelopmentOfficer`, `PlatformAdmin` |"

        PRD 4: "Fetch one annual recalculation, including its version for the
        certify OCC check. | `DevelopmentOfficer`, `PointsCertifier`,
        `DisputeAnalyst`, `PolicyCommittee`, `PlatformAdmin` |"

        PRD 2.8: "`X-User-Role` is one of the roles listed for the endpoint — on
        every endpoint. Violation: `ERR_FORBIDDEN_ROLE` (403)."

        Design: Corner/rbac/points_certifier_cannot_run_or_communicate_a_recalculation
        """
        cycle = open_cycle(client, 2026)

        validate_error(
            client.run_recalculation(cycle["id"], {}, headers=CERTIFIER),
            ERR_FORBIDDEN_ROLE,
            403,
        )

        unchanged = read_cycle(client, cycle["id"], headers=CERTIFIER)
        assert unchanged["status"] == RECALC_DRAFT
        assert unchanged["version"] == cycle["version"]

        ran = run_cycle(client, cycle["id"])
        assert ran["status"] == RECALC_COMPUTED

    def test_the_certifier_cannot_open_the_dispute_window(self, client):
        """send-communications is a development-office write like the run.

        PRD 4: "Notify donors of their recalculated points and open the dispute
        window. | `DevelopmentOfficer`, `PlatformAdmin` |"

        PRD 2.1: "**`PointsCertifier`** — the independent certifier who freezes an
        annual cycle and who moves, or reverses, approved point transfers."

        Design: Corner/rbac/points_certifier_cannot_run_or_communicate_a_recalculation
        """
        cycle = open_cycle(client, 2026)
        run_cycle(client, cycle["id"])

        validate_error(
            client.send_communications(cycle["id"], headers=CERTIFIER),
            ERR_FORBIDDEN_ROLE,
            403,
        )
        assert read_cycle(client, cycle["id"])["status"] == RECALC_COMPUTED

        communicated = communicate_cycle(client, cycle["id"])
        assert communicated["status"] == RECALC_COMMUNICATED

    def test_the_certifier_cannot_open_a_cycle_and_leaves_the_year_free(self, client):
        """The refused create persisted nothing, so the officer still gets 2027.

        PRD 4: "Open the annual recalculation for a cycle_year in status DRAFT. |
        `DevelopmentOfficer`, `PlatformAdmin` |"

        PRD 3.3: "An annual cycle is opened by a development officer or platform
        operator with three values: `cycle_year`, the athletics cycle year being
        certified, which must be between 1900 and 2100 and must be unique across
        all recalculations; `cutoff_date`, the instant after which gifts are
        excluded from both variants; and `dispute_window_end`, the last instant at
        which a dispute may be filed against this cycle, which must be strictly
        later than `cutoff_date`."

        Design: Corner/rbac/points_certifier_cannot_run_or_communicate_a_recalculation
        """
        validate_error(
            client.create_recalculation(
                f.recalculation_payload(2027), headers=CERTIFIER
            ),
            ERR_FORBIDDEN_ROLE,
            403,
        )

        opened = open_cycle(client, 2027)
        assert opened["cycle_year"] == 2027
        assert opened["status"] == RECALC_DRAFT
        assert opened["initiated_by_user_id"] == OFFICER_USER_ID


class TestTheAnalystWorksDisputesButNeverDecidesThem:
    """The reviewer's role gate refuses the decision before the duty gate can."""

    def test_the_reviewing_analyst_is_stopped_at_the_role_gate(self, client):
        """The analyst who stamped reviewed_by_user_id may not decide the row.

        PRD 2.1: "**`DisputeAnalyst`** — the analyst who works donor point
        disputes: taking them under review and requesting supporting information.
        An analyst never decides a dispute."

        PRD 4: "Uphold or deny the dispute; upholding adjusts the donor's
        dispute_adjustment_points and certified_points. | `PolicyCommittee` |"

        PRD 2.8: "Segregation of duties: at certification `X-User-ID` differs from
        the recalculation's `initiated_by_user_id`, and at a dispute decision
        `X-User-ID` differs from the dispute's `reviewed_by_user_id`. This applies
        to exactly those two operations. Violation:
        `ERR_SEGREGATION_OF_DUTIES` (403)."

        Design: Corner/rbac/dispute_analyst_cannot_decide_the_dispute_it_reviewed
        """
        _, _, reviewed = _a_dispute_under_review(client)
        assert reviewed["status"] == DISPUTE_UNDER_REVIEW
        assert reviewed["reviewed_by_user_id"] == ANALYST_USER_ID

        validate_error(
            client.decide_dispute(
                reviewed["id"],
                f.dispute_decision_payload(DECISION_UPHOLD, granted_points_delta=4.00),
                headers=ANALYST,
            ),
            ERR_FORBIDDEN_ROLE,
            403,
        )
        assert read_dispute(client, reviewed["id"])["status"] == DISPUTE_UNDER_REVIEW

    def test_the_committee_decides_the_dispute_the_analyst_could_not(self, client):
        """The identical payload lands once it comes from the deciding role.

        PRD 3.4: "Deciding is reserved to the policy committee and carries a
        `decision` of `UPHOLD` or `DENY` plus an optional `granted_points_delta`,
        which is carried to 2 decimal places and, when present, must be at least
        zero."

        PRD 2.1: "**`PolicyCommittee`** — the committee that decides disputes and
        that grants or refuses the policy exceptions certain point transfers
        require."

        Design: Corner/rbac/dispute_analyst_cannot_decide_the_dispute_it_reviewed
        """
        _, _, reviewed = _a_dispute_under_review(client)
        payload = f.dispute_decision_payload(
            DECISION_UPHOLD, granted_points_delta=4.00
        )

        validate_error(
            client.decide_dispute(reviewed["id"], payload, headers=ANALYST),
            ERR_FORBIDDEN_ROLE,
            403,
        )
        decided = validate_success(
            client.decide_dispute(reviewed["id"], payload, headers=POLICY)
        )
        assert decided["status"] == DISPUTE_UPHELD
        assert_points(decided["granted_points_delta"], "4.00", "granted_points_delta")
        assert decided["decided_by_user_id"] == POLICY_USER_ID


class TestTheCommitteeCannotManufactureTheStateItDecidesOn:
    """The committee that decides may not perform the analyst's intake actions."""

    def test_the_committee_cannot_take_a_dispute_under_review(self, client):
        """Review belongs to the analyst, and the analyst then performs it.

        PRD 4: "Take the dispute under review; the first reviewer becomes the
        segregation-of-duties comparand at decide. | `DisputeAnalyst` |"

        PRD 3.4: "Taking it under review moves `SUBMITTED → UNDER_REVIEW`, and
        requires both that the dispute is in `SUBMITTED` and that the parent
        recalculation is in `COMMUNICATED`; on the **first** review only,
        `reviewed_by_user_id` is stamped with the analyst's `X-User-ID`, and the
        dispute's `version` advances by 1."

        Design: Corner/rbac/policy_committee_cannot_review_or_request_information
        """
        _, _, dispute = _a_submitted_dispute(client)

        validate_error(
            client.review_dispute(dispute["id"], headers=POLICY),
            ERR_FORBIDDEN_ROLE,
            403,
        )
        refused = read_dispute(client, dispute["id"])
        assert refused["status"] == DISPUTE_SUBMITTED
        assert refused["reviewed_by_user_id"] is None
        assert refused["version"] == dispute["version"]

        reviewed = validate_success(
            client.review_dispute(dispute["id"], headers=ANALYST)
        )
        assert reviewed["status"] == DISPUTE_UNDER_REVIEW
        assert reviewed["reviewed_by_user_id"] == ANALYST_USER_ID

    def test_the_committees_information_request_is_a_role_refusal_not_a_state_one(
        self, client
    ):
        """SUBMITTED is also illegal for request-info, yet step 2 answers first.

        PRD 4: "Ask the donor for supporting information, capped by
        INFO_REQUEST_ROUND_CAP. | `DisputeAnalyst` |"

        PRD 3.4: "If the analyst needs evidence, requesting information moves
        `UNDER_REVIEW → INFO_REQUESTED`, requires the dispute to be in
        `UNDER_REVIEW`, records the supplied `info_note` on the dispute, and
        advances its `version` by 1 — but only while `info_request_rounds` is
        strictly below the round cap of 2."

        PRD 2.8: "A test that expects a 409 where the request also happens to be
        forbidden will see the 403, because the auth checks sit above the state
        checks."

        Design: Corner/rbac/policy_committee_cannot_review_or_request_information
        """
        _, _, dispute = _a_submitted_dispute(client)

        validate_error(
            client.request_dispute_info(
                dispute["id"], f.request_info_payload(), headers=POLICY
            ),
            ERR_FORBIDDEN_ROLE,
            403,
        )
        untouched = read_dispute(client, dispute["id"])
        assert untouched["status"] == DISPUTE_SUBMITTED
        assert untouched["info_request_rounds"] == 0
        assert untouched["info_note"] is None


def _a_section_the_donor_may_read(client):
    """SEC-D, capacity 4, 200,000 cents per seat, a 10.00-point floor, one seat."""
    section, seats = create_section_with_seats(
        client,
        [("D", 1)],
        section_code="SEC-D",
        venue_code="STADIUM-D",
        seat_capacity=4,
        per_seat_requirement_cents=200000,
        required_points_per_seat=10.00,
    )
    return section, seats[0]


class TestTheDonorCannotWriteTheInventoryItIsAllowedToRead:
    """The read/write boundary runs straight through the section URL prefix."""

    def test_the_three_operator_writes_are_refused_and_change_nothing(self, client):
        """Create, seat-add and reprice are all closed to the donor.

        PRD 4: "Create a seating section with its capacity, per-seat donation
        requirement and points floor. | `PlatformAdmin` |"

        PRD 4: "Add a physical seat to the section, bounded by seat_capacity. |
        `PlatformAdmin` |"

        PRD 4: "Reset the section's market per-seat requirement for a cycle_year
        outside any renovation, appending to requirement_history so earlier
        occupants keep their grandfathered rate. | `PlatformAdmin` |"

        PRD 3.7: "A reprice supplies a new `per_seat_requirement_cents`, the
        `cycle_year` the new rate takes effect for, and `expected_section_version`;
        it replaces `per_seat_requirement_cents`, appends the new pairing to
        `requirement_history`, and advances the section's `version` by 1."

        Design: Corner/rbac/donor_cannot_touch_the_platform_admin_inventory_surface
        """
        section, _ = _a_section_the_donor_may_read(client)
        donor = register_donor(client)
        as_donor = make_donor_headers(donor["id"])

        validate_error(
            client.create_section(
                f.section_payload(
                    section_code="SEC-X",
                    venue_code="STADIUM-X",
                    seat_capacity=1,
                    per_seat_requirement_cents=100000,
                    required_points_per_seat=0.00,
                ),
                headers=as_donor,
            ),
            ERR_FORBIDDEN_ROLE,
            403,
        )
        validate_error(
            client.create_seat(section["id"], f.seat_payload("D", 2), headers=as_donor),
            ERR_FORBIDDEN_ROLE,
            403,
        )
        validate_error(
            client.reprice_section(
                section["id"],
                f.reprice_payload(1, 2026, section["version"]),
                headers=as_donor,
            ),
            ERR_FORBIDDEN_ROLE,
            403,
        )

        after = read_section(client, section["id"])
        assert_cents(
            after["per_seat_requirement_cents"], 200000, "per_seat_requirement_cents"
        )
        assert after["seat_row_count"] == 1
        assert len(after["requirement_history"]) == 1
        assert after["version"] == section["version"]

        rows, _meta = validate_list(client.list_sections(headers=ADMIN))
        assert [row["section_code"] for row in rows] == ["SEC-D"]

    def test_the_same_donor_may_list_the_seats_it_may_not_add_to(self, client):
        """The refusal is write-scoped: the identical path segment reads fine.

        PRD 4: "List the section's seats; the reverse-reachability channel for
        Seat.section_id. | `DevelopmentOfficer`, `PointsCertifier`,
        `PolicyCommittee`, `PlatformAdmin`, `Donor` |"

        PRD 2.1: "**`PlatformAdmin`** — the operator who owns venue inventory,
        section pricing and the renovation pipeline, and who suspends or
        reinstates donors."

        Design: Corner/rbac/donor_cannot_touch_the_platform_admin_inventory_surface
        """
        section, seat = _a_section_the_donor_may_read(client)
        donor = register_donor(client)
        as_donor = make_donor_headers(donor["id"])

        validate_error(
            client.create_seat(section["id"], f.seat_payload("D", 2), headers=as_donor),
            ERR_FORBIDDEN_ROLE,
            403,
        )

        rows, meta = validate_list(
            client.list_section_seats(section["id"], headers=as_donor)
        )
        assert_page_meta(meta, total_count=1)
        assert [row["id"] for row in rows] == [seat["id"]]


def _read_transfer(client, donor_id, transfer_id, headers=OFFICER):
    """A transfer is only readable through a donor's transfer sub-collection."""
    rows, _meta = validate_list(
        client.list_donor_point_transfers(
            donor_id, headers=headers, params={"limit": 100}
        )
    )
    matches = [row for row in rows if row["id"] == transfer_id]
    assert matches, "transfer {0} is not on donor {1}".format(transfer_id, donor_id)
    return matches[0]


def _an_admin_created_death_basis_transfer(client):
    """A REQUESTED 5.00-point DEATH transfer out of a 15.00-point dead donor."""
    source = _a_scored_donor(client)
    recipient = register_donor(
        client, alumni_status=NON_ALUMNUS, entity_type=INDIVIDUAL
    )
    change_status(client, source, DONOR_DECEASED, DEATH_INSTANT)
    cycle = open_cycle(client, 2026)
    run_cycle(client, cycle["id"])
    transfer = request_transfer_ok(
        client, source["id"], recipient["id"], BASIS_DEATH, 5.00, headers=ADMIN
    )
    return source, recipient, transfer


class TestThePlatformAdminHasNoOverrideOnTheTransferVerbs:
    """The operator may start a transfer and must then stand aside."""

    def test_the_admin_that_created_the_transfer_can_neither_approve_nor_refuse_it(
        self, client
    ):
        """Both downstream verbs belong to other roles, and nothing moves.

        PRD 4: "Request a point transfer between donors. The basis fixes the
        percentage cap; a basis whose factual precondition fails lands the transfer
        in EXCEPTION_PENDING. | `DevelopmentOfficer`, `PlatformAdmin` |"

        PRD 4: "Move the points, recompute both donors' certified_points, and
        cascade the eligibility and posture changes. | `PointsCertifier` |"

        PRD 4: "Grant the policy exception an EXCEPTION_PENDING transfer needs, or
        refuse the transfer outright. | `PolicyCommittee` |"

        PRD 3.6: "`transfer_pct_cap` is a fraction, carried to 2 decimal places
        and always greater than zero and at most 1: a `DEATH` basis permits the
        entire balance, 1.00; an `ENTITY_DISSOLUTION` basis likewise permits 1.00;
        a `DIVORCE` basis permits half, 0.50; and an `ENTITY_GIVING_REALIGNMENT`
        basis permits a quarter, 0.25."

        PRD 3.6: "When the precondition for the invoked basis holds,
        `exception_required` is false and the transfer is created in `REQUESTED`."

        Design: Corner/rbac/platform_admin_cannot_move_or_reverse_a_point_transfer_it_created
        """
        source, recipient, transfer = _an_admin_created_death_basis_transfer(client)
        assert transfer["status"] == TRANSFER_REQUESTED
        assert transfer["exception_required"] is False
        assert_points(transfer["transfer_pct_cap"], "1.00", "transfer_pct_cap")
        assert_points(
            transfer["max_transferable_points"], "15.00", "max_transferable_points"
        )

        validate_error(
            client.approve_point_transfer(transfer["id"], headers=ADMIN),
            ERR_FORBIDDEN_ROLE,
            403,
        )
        validate_error(
            client.transfer_policy_decision(
                transfer["id"],
                f.transfer_policy_decision_payload(POLICY_REFUSE),
                headers=ADMIN,
            ),
            ERR_FORBIDDEN_ROLE,
            403,
        )

        untouched = _read_transfer(client, source["id"], transfer["id"])
        assert untouched["status"] == TRANSFER_REQUESTED
        assert untouched["approved_by_user_id"] is None
        assert_points(
            read_donor(client, recipient["id"])["transferred_points_in"],
            "0.00",
            "recipient.transferred_points_in",
        )

    def test_the_certifier_moves_the_points_and_the_admin_cannot_unwind_them(
        self, client
    ):
        """Approval and reversal are both the certifier's, on either side of it.

        PRD 3.6: "Approval belongs to the `PointsCertifier` and moves `REQUESTED →
        APPROVED`."

        PRD 3.6: "On success it adds `points_amount` to the recipient's
        `transferred_points_in` and the same amount to the source's
        `transferred_points_out`, recomputes `certified_points` for both donors, and
        stamps `approved_by_user_id` with the certifier's `X-User-ID`."

        PRD 3.6: "Reversal is the compensating edge, also reserved to the
        `PointsCertifier`."

        PRD 4: "Compensating action: undo an approved transfer so the donor pair's
        certified-points total returns to its pre-transfer value. |
        `PointsCertifier` |"

        Design: Corner/rbac/platform_admin_cannot_move_or_reverse_a_point_transfer_it_created
        """
        source, recipient, transfer = _an_admin_created_death_basis_transfer(client)

        validate_error(
            client.approve_point_transfer(transfer["id"], headers=ADMIN),
            ERR_FORBIDDEN_ROLE,
            403,
        )
        approved = validate_success(
            client.approve_point_transfer(transfer["id"], headers=CERTIFIER)
        )
        assert approved["status"] == TRANSFER_APPROVED
        assert approved["approved_by_user_id"] == CERTIFIER_USER_ID
        assert_points(
            read_donor(client, source["id"])["certified_points"],
            "10.00",
            "source.certified_points",
        )
        assert_points(
            read_donor(client, recipient["id"])["certified_points"],
            "5.00",
            "recipient.certified_points",
        )

        validate_error(
            client.reverse_point_transfer(
                transfer["id"], f.reverse_transfer_payload(), headers=ADMIN
            ),
            ERR_FORBIDDEN_ROLE,
            403,
        )
        assert (
            _read_transfer(client, source["id"], transfer["id"])["status"]
            == TRANSFER_APPROVED
        )


def _one_section_and_one_donor(client):
    """SEC-A with a single seat, plus one donor: enough content to read."""
    section, _seats = create_section_with_seats(
        client,
        [("A", 1)],
        section_code="SEC-A",
        venue_code="STADIUM-A",
        seat_capacity=2,
        per_seat_requirement_cents=100000,
        required_points_per_seat=0.00,
    )
    donor = register_donor(client, alumni_status=ALUMNUS, entity_type=INDIVIDUAL)
    return section, donor


class TestTheAnalystReadSurfaceIsEnumeratedRatherThanUniversal:
    """Reads are not globally public: the analyst's grant is path by path."""

    def test_the_donor_and_dispute_reads_are_open_to_the_analyst(self, client):
        """The analyst may sweep donors, ledger entries and disputes.

        PRD 4: "List donors with filtering; the reverse-reachability channel for
        the self-referential household link. | `DevelopmentOfficer`,
        `PointsCertifier`, `DisputeAnalyst`, `PolicyCommittee`, `PlatformAdmin` |"

        PRD 4: "List immutable point-ledger entries; the reverse-reachability
        channel for both PointLedgerEntry FKs. | `DevelopmentOfficer`,
        `PointsCertifier`, `DisputeAnalyst`, `PolicyCommittee`, `PlatformAdmin`,
        `Donor` |"

        PRD 4: "List point disputes; the reverse-reachability channel for both
        PointDispute FKs. | `DevelopmentOfficer`, `DisputeAnalyst`,
        `PolicyCommittee`, `PlatformAdmin`, `Donor` |"

        Design: Corner/rbac/dispute_analyst_is_confined_to_the_donor_and_dispute_reading_surface
        """
        _section, _donor = _one_section_and_one_donor(client)

        _rows, donors_meta = validate_list(client.list_donors(headers=ANALYST))
        assert_page_meta(donors_meta, total_count=1)

        _rows, ledger_meta = validate_list(
            client.list_point_ledger_entries(headers=ANALYST)
        )
        assert_page_meta(ledger_meta, total_count=0)

        _rows, dispute_meta = validate_list(client.list_disputes(headers=ANALYST))
        assert_page_meta(dispute_meta, total_count=0)

    def test_the_venue_and_selection_reads_are_closed_to_the_analyst(self, client):
        """Four reads the other operator roles hold are refused to the analyst.

        PRD 4: "List sections; the reverse-reachability channel for
        Section.reseating_recalculation_id. | `DevelopmentOfficer`,
        `PointsCertifier`, `PolicyCommittee`, `PlatformAdmin`, `Donor` |"

        PRD 4: "Computed read: underwater ratio, posture and the recommended
        requirement for the section, per the section_pricing_sensitivity
        calculation. | `DevelopmentOfficer`, `PointsCertifier`, `PolicyCommittee`,
        `PlatformAdmin` |"

        PRD 4: "List seat assignments; the reverse-reachability channel for all
        three SeatAssignment FKs. | `DevelopmentOfficer`, `PointsCertifier`,
        `PolicyCommittee`, `PlatformAdmin`, `Donor` |"

        PRD 4: "List relocation and upgrade requests; the reverse-reachability
        channel for all five RelocationRequest FKs. | `DevelopmentOfficer`,
        `PointsCertifier`, `PolicyCommittee`, `PlatformAdmin`, `Donor` |"

        Design: Corner/rbac/dispute_analyst_is_confined_to_the_donor_and_dispute_reading_surface
        """
        section, _donor = _one_section_and_one_donor(client)

        validate_error(client.list_sections(headers=ANALYST), ERR_FORBIDDEN_ROLE, 403)
        validate_error(
            client.get_pricing_sensitivity(section["id"], headers=ANALYST),
            ERR_FORBIDDEN_ROLE,
            403,
        )
        validate_error(
            client.list_seat_assignments(headers=ANALYST), ERR_FORBIDDEN_ROLE, 403
        )
        validate_error(
            client.list_relocation_requests(headers=ANALYST), ERR_FORBIDDEN_ROLE, 403
        )

    def test_the_committee_reads_the_section_list_the_analyst_may_not(self, client):
        """The path is not globally closed — only closed to the analyst's role.

        PRD 2.1: "If both headers are present but the value of `X-User-Role` is
        not one of the roles listed for the endpoint being called, the request is
        rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        PRD 4: "List sections; the reverse-reachability channel for
        Section.reseating_recalculation_id. | `DevelopmentOfficer`,
        `PointsCertifier`, `PolicyCommittee`, `PlatformAdmin`, `Donor` |"

        Design: Corner/rbac/dispute_analyst_is_confined_to_the_donor_and_dispute_reading_surface
        """
        section, _donor = _one_section_and_one_donor(client)

        validate_error(client.list_sections(headers=ANALYST), ERR_FORBIDDEN_ROLE, 403)

        rows, meta = validate_list(client.list_sections(headers=POLICY))
        assert_page_meta(meta, total_count=1)
        assert [row["id"] for row in rows] == [section["id"]]


def _two_donors_a_certified_cycle_and_one_event(client):
    """The acting donor, a scored alumnus, a certified 2026 cycle and its event."""
    actor = register_donor(client, alumni_status=NON_ALUMNUS, entity_type=INDIVIDUAL)
    other = _a_scored_donor(client, alumni_status=ALUMNUS)
    cycle = certified_cycle(client, 2026)
    event = create_event(
        client,
        cycle["id"],
        f.instant(2026, 9, 1),
        f.instant(2026, 9, 2),
        1440,
    )
    return actor, other, cycle, event


class TestTheDonorReadGrantIsPathExact:
    """A donor's grant is enumerated path by path, not inherited by prefix."""

    def test_the_donor_list_is_closed_while_the_donor_singleton_is_open(self, client):
        """Donor is absent from the list's role column and present on the read.

        PRD 4: "List donors with filtering; the reverse-reachability channel for
        the self-referential household link. | `DevelopmentOfficer`,
        `PointsCertifier`, `DisputeAnalyst`, `PolicyCommittee`, `PlatformAdmin` |"

        PRD 4: "Fetch one donor, including every derived point component and
        rank_position. | `DevelopmentOfficer`, `PointsCertifier`, `DisputeAnalyst`,
        `PolicyCommittee`, `PlatformAdmin`, `Donor` |"

        Design: Corner/rbac/donor_may_read_another_donors_row_but_not_the_donor_list
        """
        actor, _other, _cycle, _event = _two_donors_a_certified_cycle_and_one_event(
            client
        )
        as_actor = make_donor_headers(actor["id"])

        validate_error(client.list_donors(headers=as_actor), ERR_FORBIDDEN_ROLE, 403)

        own = validate_success(client.get_donor(actor["id"], headers=as_actor))
        assert own["id"] == actor["id"]

    def test_a_donor_may_read_another_donors_row_and_gift_history(self, client):
        """Ownership binds five writes only, so cross-donor reads are permitted.

        PRD 2.8: "For a caller acting as `Donor`, `X-User-ID` equals the `donor_id`
        of the targeted dispute, selection slot, relocation request or seat
        assignment. This applies to exactly five operations: filing a point
        dispute, providing information on a dispute, picking a seat through a
        selection slot, forfeiting a selection slot, and creating a relocation
        request. Violation: `ERR_NOT_RESOURCE_OWNER` (403)."

        PRD 4: "List the donor's gifts; the reverse-reachability channel for
        Gift.donor_id. | `DevelopmentOfficer`, `PointsCertifier`, `DisputeAnalyst`,
        `PolicyCommittee`, `PlatformAdmin`, `Donor` |"

        Design: Corner/rbac/donor_may_read_another_donors_row_but_not_the_donor_list
        """
        actor, other, _cycle, _event = _two_donors_a_certified_cycle_and_one_event(
            client
        )
        as_actor = make_donor_headers(actor["id"])

        stranger = validate_success(client.get_donor(other["id"], headers=as_actor))
        assert stranger["id"] == other["id"]
        assert_points(stranger["certified_points"], "40.00", "other.certified_points")

        _rows, meta = validate_list(
            client.list_donor_gifts(other["id"], headers=as_actor)
        )
        assert_page_meta(meta, total_count=1)

    def test_the_cycle_itself_is_closed_while_its_events_are_open(self, client):
        """A nested child is readable although its parent singleton is not.

        PRD 4: "Fetch one annual recalculation, including its version for the
        certify OCC check. | `DevelopmentOfficer`, `PointsCertifier`,
        `DisputeAnalyst`, `PolicyCommittee`, `PlatformAdmin` |"

        PRD 4: "List the recalculation's selection events; the reverse-reachability
        channel for SelectionEvent.recalculation_id. | `DevelopmentOfficer`,
        `PointsCertifier`, `PolicyCommittee`, `PlatformAdmin`, `Donor` |"

        PRD 4: "Fetch one selection event, including its window, slot geometry and
        slot counters. | `DevelopmentOfficer`, `PointsCertifier`, `PolicyCommittee`,
        `PlatformAdmin`, `Donor` |"

        Design: Corner/rbac/donor_may_read_another_donors_row_but_not_the_donor_list
        """
        actor, _other, cycle, event = _two_donors_a_certified_cycle_and_one_event(
            client
        )
        as_actor = make_donor_headers(actor["id"])

        validate_error(
            client.get_recalculation(cycle["id"], headers=as_actor),
            ERR_FORBIDDEN_ROLE,
            403,
        )

        rows, meta = validate_list(
            client.list_recalculation_selection_events(cycle["id"], headers=as_actor)
        )
        assert_page_meta(meta, total_count=1)
        assert [row["id"] for row in rows] == [event["id"]]

        seen = validate_success(
            client.get_selection_event(event["id"], headers=as_actor)
        )
        assert seen["status"] == EVENT_DRAFT
        assert seen["scheduled_slot_count"] == 0


def _two_donors_and_a_communicated_cycle(client):
    """A scored donor to file for, a bystander donor, and an open dispute window."""
    subject = _a_scored_donor(client)
    bystander = register_donor(
        client, alumni_status=NON_ALUMNUS, entity_type=INDIVIDUAL
    )
    cycle = _a_communicated_cycle(client)
    return subject, bystander, cycle


class TestTheOwnershipCheckBindsTheDonorRoleAlone:
    """The same body succeeds for the office and fails for a stranger donor."""

    def test_the_office_files_for_a_donor_that_another_donor_may_not(self, client):
        """donor_id need not match X-User-ID unless the caller is a Donor.

        PRD 4: "File a dispute against a communicated recalculation; only the
        owning donor may file. | `Donor`, `DevelopmentOfficer` |"

        PRD 3.4: "A `Donor`-role filer may only supply their own `donor_id`."

        PRD 2.1: "Concretely, a `Donor` caller may only file a dispute whose
        `donor_id` is their own, only answer an information request on a dispute
        they own, only consume or forfeit a selection slot whose `donor_id` is their
        own, only file a relocation request whose `donor_id` is their own, and only
        act on a seat assignment whose `donor_id` is their own."

        PRD 2.1: "A mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        PRD 4: "Status codes follow one rule with no exceptions: an operation that
        brings a new resource into existence returns **201 Created**, and every
        other successful operation — including every read and every state transition
        on an existing resource — returns **200 OK**."

        Design: Corner/rbac/development_officer_may_file_a_dispute_for_a_donor_that_donor_could_not_file_for
        """
        subject, bystander, cycle = _two_donors_and_a_communicated_cycle(client)
        payload = f.dispute_payload(subject["id"], cycle["id"], 3.00)

        filed = validate_success(
            client.create_dispute(payload, headers=OFFICER), expected_status=201
        )
        assert filed["status"] == DISPUTE_SUBMITTED
        assert filed["donor_id"] == subject["id"]
        assert filed["version"] == 1

        validate_error(
            client.create_dispute(payload, headers=make_donor_headers(bystander["id"])),
            ERR_NOT_RESOURCE_OWNER,
            403,
        )

        _rows, meta = validate_list(client.list_disputes(headers=OFFICER))
        assert_page_meta(meta, total_count=1)

    def test_the_office_filed_dispute_is_a_real_row_that_blocks_certification(
        self, client
    ):
        """A merely SUBMITTED dispute stops the freeze, proving the row exists.

        PRD 3.5: "Moving a cycle `COMMUNICATED → CERTIFIED` requires four things at
        once: the recalculation is in `COMMUNICATED`; the supplied
        `expected_recalculation_version` equals the recalculation's current
        `version`; the certifier's `X-User-ID` differs from `initiated_by_user_id`;
        and no dispute on this recalculation remains in `SUBMITTED`, `UNDER_REVIEW`
        or `INFO_REQUESTED`."

        PRD 2.8: "The target resource's current state admits the requested
        transition — on every state-transition endpoint. Violation:
        `ERR_INVALID_STATE` (409)."

        Design: Corner/rbac/development_officer_may_file_a_dispute_for_a_donor_that_donor_could_not_file_for
        """
        subject, _bystander, cycle = _two_donors_and_a_communicated_cycle(client)
        filed = validate_success(
            client.create_dispute(
                f.dispute_payload(subject["id"], cycle["id"], 3.00), headers=OFFICER
            ),
            expected_status=201,
        )
        assert filed["status"] == DISPUTE_SUBMITTED

        validate_error(
            client.certify_recalculation(
                cycle["id"], f.certify_payload(cycle["version"]), headers=CERTIFIER
            ),
            ERR_INVALID_STATE,
            409,
        )
        assert read_cycle(client, cycle["id"])["status"] == RECALC_COMMUNICATED


def _a_dispute_reviewed_under_the_certifiers_own_user_id(client):
    """reviewed_by_user_id is certifier-1 while initiated_by_user_id is officer-1."""
    donor = _a_scored_donor(client)
    cycle = _a_communicated_cycle(client)
    dispute = file_dispute(client, donor["id"], cycle["id"], 2.00)
    reviewed = validate_success(
        client.review_dispute(
            dispute["id"],
            headers=headers_for(ROLE_DISPUTE_ANALYST, CERTIFIER_USER_ID),
        )
    )
    return donor, cycle, reviewed


class TestTheTwoSegregationAxesAreIndependentOfEachOther:
    """Each axis compares one field; touching the aggregate is not disqualifying."""

    def test_the_cycles_initiator_may_still_decide_a_dispute_against_it(self, client):
        """The decide axis reads reviewed_by_user_id and nothing else.

        PRD 2.1: "Two of those recorded identifiers exist purely to enforce
        **segregation of duties**, and both comparisons are made on `X-User-ID`
        values, so they bite even when the two actors hold different roles."

        PRD 2.1: "Certifying an annual recalculation requires that `X-User-ID`
        differ from the recalculation's `initiated_by_user_id`; deciding a dispute
        requires that `X-User-ID` differ from the dispute's `reviewed_by_user_id`."

        PRD 3.4: "Denying it, `UNDER_REVIEW → DENIED`, sets `granted_points_delta`
        to 0 and `decided_by_user_id` to the decider's `X-User-ID`, stamps
        `decided_at`, leaves the donor's `dispute_adjustment_points` unchanged, and
        advances only the dispute's `version` by 1."

        Design: Corner/rbac/the_two_segregation_axes_are_independent_of_each_other
        """
        donor, cycle, reviewed = _a_dispute_reviewed_under_the_certifiers_own_user_id(
            client
        )
        assert cycle["initiated_by_user_id"] == OFFICER_USER_ID
        assert reviewed["reviewed_by_user_id"] == CERTIFIER_USER_ID

        decided = validate_success(
            client.decide_dispute(
                reviewed["id"],
                f.dispute_decision_payload(DECISION_DENY),
                headers=headers_for(ROLE_POLICY_COMMITTEE, OFFICER_USER_ID),
            )
        )
        assert decided["status"] == DISPUTE_DENIED
        assert decided["decided_by_user_id"] == OFFICER_USER_ID
        assert_points(decided["granted_points_delta"], "0.00", "granted_points_delta")
        assert_points(
            read_donor(client, donor["id"])["certified_points"],
            "15.00",
            "donor.certified_points",
        )

    def test_the_disputes_reviewer_may_still_certify_the_cycle(self, client):
        """The certify axis reads initiated_by_user_id and nothing else.

        PRD 2.8: "Segregation of duties: at certification `X-User-ID` differs from
        the recalculation's `initiated_by_user_id`, and at a dispute decision
        `X-User-ID` differs from the dispute's `reviewed_by_user_id`. This applies
        to exactly those two operations. Violation:
        `ERR_SEGREGATION_OF_DUTIES` (403)."

        PRD 3.5: "On success the recalculation records `certified_by_user_id` from
        the certifier's `X-User-ID` and `certified_at` from the current logical
        clock instant, sets `certified_points_sum` to the sum of `certified_points`
        across every donor it processed, and advances its own `version` by 1."

        PRD 3.5: "`rank_position` is the 1-based index in that order."

        Design: Corner/rbac/the_two_segregation_axes_are_independent_of_each_other
        """
        donor, cycle, reviewed = _a_dispute_reviewed_under_the_certifiers_own_user_id(
            client
        )
        validate_success(
            client.decide_dispute(
                reviewed["id"],
                f.dispute_decision_payload(DECISION_DENY),
                headers=headers_for(ROLE_POLICY_COMMITTEE, OFFICER_USER_ID),
            )
        )

        current = read_cycle(client, cycle["id"])
        certified = validate_success(
            client.certify_recalculation(
                cycle["id"], f.certify_payload(current["version"]), headers=CERTIFIER
            )
        )
        assert certified["status"] == RECALC_CERTIFIED
        assert certified["certified_by_user_id"] == CERTIFIER_USER_ID
        assert_points(
            certified["certified_points_sum"], "15.00", "certified_points_sum"
        )
        assert read_donor(client, donor["id"])["rank_position"] == 1
