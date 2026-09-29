"""Validation corners: which refusal wins, and where a bound actually bites.

The service specifies a 27-step check order, so most of these tests build a
request that breaks two rules at once and pin which of the two is reported.
The rest pin an inclusive bound, a strict inequality or a conjunction of
clauses that a partial implementation would collapse into one.
"""

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_DISPUTE_NOT_FOUND,
    ERR_DISPUTE_WINDOW_CLOSED,
    ERR_EVENT_SLOTS_STALE,
    ERR_FORBIDDEN_ROLE,
    ERR_HOUSEHOLD_LINK_INVALID,
    ERR_INVALID_REQUEST,
    ERR_NOT_RESOURCE_OWNER,
    ERR_RECALCULATION_NOT_CERTIFIED,
    ERR_RELOCATION_TARGET_INVALID,
    ERR_SEAT_POINTS_SHORTFALL,
    ERR_SECTION_CAPACITY_EXCEEDED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_SLOT_WINDOW_OVERFLOW,
    ERR_TRANSFER_POLICY_EXCEPTION_REQUIRED,
    ERR_UNAUTHENTICATED,
)
from test_helpers.assertions import (
    assert_cents,
    assert_donor_points,
    assert_instant,
    assert_page_meta,
    assert_points,
    assert_ratio,
    assert_seat_inventory,
    assert_three_fractional_digits,
    get_success_data,
    validate_error,
    validate_list,
    validate_success,
)
from test_helpers.constants import (
    BASIS_DEATH,
    DECISION_UPHOLD,
    DISPUTE_SUBMITTED,
    DISPUTE_UNDER_REVIEW,
    DISPUTE_UPHELD,
    ELIGIBLE,
    EVENT_DRAFT,
    EVENT_SLOTS_PUBLISHED,
    EVENT_SLOTS_STALE,
    INDIVIDUAL,
    JOINT_HOUSEHOLD,
    LIMIT_MAX,
    NON_ALUMNUS,
    OFFSET_MIN,
    POLICY_GRANT,
    PRICING_MARKET,
    RECALC_CERTIFIED,
    RECALC_COMMUNICATED,
    RELEASE_DONOR_RELEASE,
    RELOCATION_AWAITING_SELECTION,
    RELOCATION_GRANTED,
    ROLE_DISPUTE_ANALYST,
    ROLE_DONOR,
    ROLE_PLATFORM_ADMIN,
    OCCUPANCY_HELD,
    OCCUPANCY_RELEASED,
    SEAT_AVAILABLE,
    SLOT_FORFEITED,
    SLOT_SCHEDULED,
    SLOT_STALE,
    TRANSFER_APPROVED,
    TRANSFER_EXCEPTION_PENDING,
    TRANSFER_REQUESTED,
)
from test_helpers.fixtures import (
    add_received_gift,
    certified_cycle,
    communicate_cycle,
    confirm_assignment,
    create_event,
    create_section,
    create_section_with_seats,
    file_relocation_request,
    open_cycle,
    pick_seat,
    pick_seat_ok,
    publish_and_open,
    publish_slots,
    read_assignment,
    read_cycle,
    read_donor,
    read_dispute,
    read_event,
    read_relocation_request,
    read_seat,
    read_section,
    read_slot,
    register_donor,
    request_transfer,
    run_cycle,
    set_clock,
    slot_for_donor,
)
from test_helpers.test_users import (
    ADMIN,
    ANALYST,
    CERTIFIER,
    CERTIFIER_2,
    CERTIFIER_2_USER_ID,
    CERTIFIER_USER_ID,
    OFFICER,
    POLICY,
    POLICY_2,
    POLICY_2_USER_ID,
    POLICY_USER_ID,
    headers_for,
    make_donor_headers,
)

# Probe identifiers that are well-formed UUIDs but resolve to nothing.
MISSING_DISPUTE_ID = "00000000-0000-4000-8000-00000000d15e"
MISSING_SECTION_ID = "00000000-0000-4000-8000-00000000cec7"


class TestPathExistenceOutranksTheBodyContract:
    """Step 5 runs before step 6, so an unknown id hides a missing field."""

    def test_an_unknown_dispute_id_beats_a_missing_required_field(self, client):
        """An empty body against a nonexistent dispute is a 404, not a 400.

        PRD 2.8: "Checks run strictly in the sequence below; the **first** rule
        that a request violates determines the response, and no later rule is
        evaluated."

        PRD 2.8: "Every path identifier resolves, checked left to right — on
        every endpoint that has path parameters."

        Design: Corner/validations/unknown_path_id_outranks_a_missing_required_body_field
        """
        refused = client.request_dispute_info(MISSING_DISPUTE_ID, {}, headers=ANALYST)
        validate_error(refused, ERR_DISPUTE_NOT_FOUND, 404)


class TestRoleRejectionOutranksPathExistence:
    """Step 2 runs before step 5, so a forbidden caller learns nothing."""

    def test_a_forbidden_role_is_not_told_the_section_is_missing(self, client):
        """The officer is refused on the endpoint before the id is resolved.

        PRD 2.8: "`X-User-Role` is one of the roles listed for the endpoint — on
        every endpoint."

        PRD 2.8: "A test that expects a 409 where the request also happens to be
        forbidden will see the 403, because the auth checks sit above the state
        checks."

        Design: Corner/validations/role_rejection_outranks_path_existence_for_an_unknown_section
        """
        refused = client.create_seat(
            MISSING_SECTION_ID, f.seat_payload("Z", 1), headers=OFFICER
        )
        validate_error(refused, ERR_FORBIDDEN_ROLE, 403)


class TestAuthenticationOutranksAuthorization:
    """Step 1 rejects an empty header value before any role list is consulted."""

    def test_an_empty_user_id_is_reported_as_unauthenticated(self, client):
        """The Donor role is not listed on the donor list, yet the answer is 401.

        PRD 2.1: "If either header is absent, or present but empty, the request
        is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else
        about the request is examined."

        PRD 2.8: "Both `X-User-ID` and `X-User-Role` are present and non-empty —
        on every endpoint."

        Design: Corner/validations/an_empty_user_id_header_outranks_both_role_and_existence
        """
        refused = client.list_donors(headers=headers_for(ROLE_DONOR, ""))
        validate_error(refused, ERR_UNAUTHENTICATED, 401)


class TestPaginationBoundsAreEnforcedAtBothEnds:
    """limit runs 1 through 100 inclusive and offset may not go negative."""

    def test_one_hundred_is_accepted_and_one_hundred_and_one_is_not(self, client):
        """The upper bound is inclusive, so only 101 crosses it.

        PRD 2.8: "The body parses; required fields are present; enum values are
        recognised; numeric and string constraints hold; `limit` is within 1
        through 100 and `offset` is at least 0 — on every endpoint."

        Design: Corner/validations/pagination_bounds_are_enforced_at_both_ends_of_the_declared_range
        """
        register_donor(client, alumni_status=NON_ALUMNUS)

        rows, meta = validate_list(
            client.list_donors(headers=OFFICER, params={"limit": LIMIT_MAX})
        )
        assert_page_meta(
            meta, total_count=1, limit=LIMIT_MAX, offset=OFFSET_MIN, has_more=False
        )
        assert len(rows) == 1

        validate_error(
            client.list_donors(headers=OFFICER, params={"limit": LIMIT_MAX + 1}),
            ERR_INVALID_REQUEST,
            400,
        )

    def test_a_zero_limit_and_a_negative_offset_are_both_rejected(self, client):
        """Neither bound is silently clamped to its default.

        PRD 2.3: "A `limit` outside the range 1 through 100 inclusive, or a
        negative `offset`, is a malformed request and is rejected with
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/validations/pagination_bounds_are_enforced_at_both_ends_of_the_declared_range
        """
        register_donor(client, alumni_status=NON_ALUMNUS)

        validate_error(
            client.list_donors(headers=OFFICER, params={"limit": 0}),
            ERR_INVALID_REQUEST,
            400,
        )
        validate_error(
            client.list_donors(headers=OFFICER, params={"offset": -1}),
            ERR_INVALID_REQUEST,
            400,
        )


def _cycle_initiated_under_the_certifier_id(client):
    """A cycle whose initiator id is a certifier id, opened by an admin role."""
    set_clock(client, f.instant(2026, 4, 1))
    donor = register_donor(client, alumni_status=NON_ALUMNUS)
    add_received_gift(client, donor["id"], 1000000, f.instant(2026, 3, 1))
    cycle = open_cycle(
        client, 2026, headers=headers_for(ROLE_PLATFORM_ADMIN, CERTIFIER_USER_ID)
    )
    run_cycle(client, cycle["id"])
    communicate_cycle(client, cycle["id"])
    return donor, read_cycle(client, cycle["id"])


class TestCertificationSegregationKeysOnTheUserId:
    """The comparand is the header value, not the role that supplied it."""

    def test_the_initiator_id_blocks_the_same_user_from_certifying(self, client):
        """certifier-1 opened the cycle under an admin role and is now locked out.

        PRD 3.4: "The new recalculation starts in `DRAFT` with
        `donors_processed_count`, `communication_sent_count` and
        `certified_points_sum` at zero, `certified_by_user_id` and `certified_at`
        null, and `initiated_by_user_id` set to the caller's `X-User-ID` — the
        value that will later be compared against the certifier's identity."

        PRD 2.1: "Certifying an annual recalculation requires that `X-User-ID`
        differ from the recalculation's `initiated_by_user_id`; deciding a
        dispute requires that `X-User-ID` differ from the dispute's
        `reviewed_by_user_id`."

        Design: Corner/validations/certifying_a_cycle_you_initiated_yourself_returns_segregation_of_duties
        """
        donor, cycle = _cycle_initiated_under_the_certifier_id(client)
        assert cycle["initiated_by_user_id"] == CERTIFIER_USER_ID
        assert cycle["status"] == RECALC_COMMUNICATED

        refused = client.certify_recalculation(
            cycle["id"], f.certify_payload(cycle["version"]), headers=CERTIFIER
        )
        validate_error(refused, ERR_SEGREGATION_OF_DUTIES, 403)

        after = read_cycle(client, cycle["id"])
        assert after["status"] == RECALC_COMMUNICATED
        assert after["version"] == cycle["version"]
        assert after["certified_by_user_id"] is None
        assert read_donor(client, donor["id"])["rank_position"] is None

    def test_a_different_certifier_id_succeeds_on_the_same_version(self, client):
        """The refusal wrote nothing, so the very same version stamp still fits.

        PRD 2.8: "Segregation of duties: at certification `X-User-ID` differs
        from the recalculation's `initiated_by_user_id`, and at a dispute
        decision `X-User-ID` differs from the dispute's `reviewed_by_user_id`."

        PRD 3.5: "On success the recalculation records `certified_by_user_id`
        from the certifier's `X-User-ID` and `certified_at` from the current
        logical clock instant, sets `certified_points_sum` to the sum of
        `certified_points` across every donor it processed, and advances its own
        `version` by 1."

        Design: Corner/validations/certifying_a_cycle_you_initiated_yourself_returns_segregation_of_duties
        """
        donor, cycle = _cycle_initiated_under_the_certifier_id(client)
        validate_error(
            client.certify_recalculation(
                cycle["id"], f.certify_payload(cycle["version"]), headers=CERTIFIER
            ),
            ERR_SEGREGATION_OF_DUTIES,
            403,
        )

        certified = validate_success(
            client.certify_recalculation(
                cycle["id"], f.certify_payload(cycle["version"]), headers=CERTIFIER_2
            )
        )
        assert certified["status"] == RECALC_CERTIFIED
        assert certified["certified_by_user_id"] == CERTIFIER_2_USER_ID
        assert_instant(
            certified["certified_at"], f.instant(2026, 4, 1), "certified_at"
        )
        assert_points(
            certified["certified_points_sum"], "15.00", "certified_points_sum"
        )
        assert read_donor(client, donor["id"])["rank_position"] == 1


def _dispute_reviewed_under_the_policy_id(client):
    """A dispute whose first reviewer signed in with a policy-committee id."""
    set_clock(client, f.instant(2026, 4, 1))
    donor = register_donor(client, alumni_status=NON_ALUMNUS)
    add_received_gift(client, donor["id"], 1000000, f.instant(2026, 3, 1))
    cycle = open_cycle(client, 2026, dispute_window_end=f.instant(2026, 9, 30))
    run_cycle(client, cycle["id"])
    communicate_cycle(client, cycle["id"])

    dispute = get_success_data(
        client.create_dispute(
            f.dispute_payload(donor["id"], cycle["id"], 5.00),
            headers=make_donor_headers(donor["id"]),
        )
    )
    validate_success(
        client.review_dispute(
            dispute["id"], headers=headers_for(ROLE_DISPUTE_ANALYST, POLICY_USER_ID)
        )
    )
    return donor, cycle, read_dispute(client, dispute["id"])


class TestDisputeDecisionSegregationKeysOnTheReviewerId:
    """The second comparand of the same rule, on a different pair of roles."""

    def test_the_first_reviewers_id_blocks_that_user_from_deciding(self, client):
        """policy-1 reviewed as an analyst and may not decide as the committee.

        PRD 3.4: "That first reviewer's identity is the comparand the eventual
        decision is measured against, which is why it is stamped once and never
        overwritten."

        PRD 3.4: "Both outcomes require that the dispute is in `UNDER_REVIEW`,
        that the current logical clock instant is before the parent
        recalculation's `dispute_window_end`, and that the decider's `X-User-ID`
        differs from `reviewed_by_user_id`."

        Design: Corner/validations/deciding_a_dispute_you_reviewed_yourself_returns_segregation_of_duties
        """
        donor, _cycle, dispute = _dispute_reviewed_under_the_policy_id(client)
        assert dispute["reviewed_by_user_id"] == POLICY_USER_ID
        assert dispute["status"] == DISPUTE_UNDER_REVIEW

        refused = client.decide_dispute(
            dispute["id"],
            f.dispute_decision_payload(DECISION_UPHOLD, granted_points_delta=5.00),
            headers=POLICY,
        )
        validate_error(refused, ERR_SEGREGATION_OF_DUTIES, 403)

        after = read_dispute(client, dispute["id"])
        assert after["status"] == DISPUTE_UNDER_REVIEW
        assert after["decided_by_user_id"] is None
        assert after["granted_points_delta"] is None
        assert_donor_points(
            read_donor(client, donor["id"]),
            dispute_adjustment_points="0.00",
            certified_points="15.00",
            label="donor",
        )

    def test_a_second_committee_id_may_decide_the_same_dispute(self, client):
        """policy-2 upholds it, and the adjustment lands in the same request.

        PRD 3.4: "Upholding it, `UNDER_REVIEW → UPHELD`, sets
        `granted_points_delta` from the payload and `decided_by_user_id` to the
        decider's `X-User-ID`, stamps `decided_at` with the current logical clock
        instant, adds `granted_points_delta` to the donor's
        `dispute_adjustment_points`, recomputes the donor's `certified_points`,
        and advances both the dispute's `version` and the donor's `version` by
        1."

        Design: Corner/validations/deciding_a_dispute_you_reviewed_yourself_returns_segregation_of_duties
        """
        donor, _cycle, dispute = _dispute_reviewed_under_the_policy_id(client)
        validate_error(
            client.decide_dispute(
                dispute["id"],
                f.dispute_decision_payload(DECISION_UPHOLD, granted_points_delta=5.00),
                headers=POLICY,
            ),
            ERR_SEGREGATION_OF_DUTIES,
            403,
        )

        decided = validate_success(
            client.decide_dispute(
                dispute["id"],
                f.dispute_decision_payload(DECISION_UPHOLD, granted_points_delta=5.00),
                headers=POLICY_2,
            )
        )
        assert decided["status"] == DISPUTE_UPHELD
        assert decided["decided_by_user_id"] == POLICY_2_USER_ID
        assert_points(
            decided["granted_points_delta"], "5.00", "granted_points_delta"
        )
        assert_donor_points(
            read_donor(client, donor["id"]),
            dispute_adjustment_points="5.00",
            certified_points="20.00",
            label="donor",
        )


def _two_joint_households_and_an_individual(client):
    """The three donors the two failing clauses and the passing one need."""
    set_clock(client, f.instant(2026, 4, 1))
    first = register_donor(
        client, alumni_status=NON_ALUMNUS, entity_type=JOINT_HOUSEHOLD
    )
    second = register_donor(
        client, alumni_status=NON_ALUMNUS, entity_type=JOINT_HOUSEHOLD
    )
    single = register_donor(client, alumni_status=NON_ALUMNUS, entity_type=INDIVIDUAL)
    return first, second, single


class TestTheHouseholdLinkIsAConjunctionOfThreeClauses:
    """Each failing clause is a 409 on the same code, and the writes never happen."""

    def test_a_partner_who_is_not_a_joint_household_is_refused(self, client):
        """The entity_type clause fails while every other clause holds.

        PRD 3.1: "A link is admitted only when the partner is a different donor
        from the one being linked, when both donors carry `entity_type`
        `JOINT_HOUSEHOLD`, and when neither donor is already linked to some third
        donor; otherwise the response is `ERR_HOUSEHOLD_LINK_INVALID`."

        Design: Corner/validations/household_link_rejects_a_non_joint_partner_and_a_self_link
        """
        first, _second, single = _two_joint_households_and_an_individual(client)

        refused = client.link_household(
            first["id"],
            f.household_link_payload(single["id"], first["version"]),
            headers=OFFICER,
        )
        validate_error(refused, ERR_HOUSEHOLD_LINK_INVALID, 409)

        after = read_donor(client, first["id"])
        assert after["version"] == first["version"]
        assert after["household_partner_donor_id"] is None

    def test_a_self_link_is_a_link_invalid_rather_than_a_bad_request(self, client):
        """The different-donor clause is a step 22 refusal, not a step 6 one.

        PRD 2.8: "A household link names a donor other than the acting one, both
        donors have `entity_type` `JOINT_HOUSEHOLD`, and neither is already
        linked to some third donor."

        Design: Corner/validations/household_link_rejects_a_non_joint_partner_and_a_self_link
        """
        first, _second, _single = _two_joint_households_and_an_individual(client)

        refused = client.link_household(
            first["id"],
            f.household_link_payload(first["id"], first["version"]),
            headers=OFFICER,
        )
        validate_error(refused, ERR_HOUSEHOLD_LINK_INVALID, 409)

        after = read_donor(client, first["id"])
        assert after["version"] == first["version"]
        assert after["household_partner_donor_id"] is None

    def test_the_valid_link_still_fits_the_untouched_version_and_binds_both_rows(
        self, client
    ):
        """Two refusals later, the original version stamp is still the current one.

        PRD 3.1: "The link operation names the counterpart as
        `partner_donor_id` and echoes `expected_donor_version`; when it succeeds,
        `household_partner_donor_id` is written reciprocally on *both* rows and
        *both* donors have their `version` advanced by 1."

        Design: Corner/validations/household_link_rejects_a_non_joint_partner_and_a_self_link
        """
        first, second, single = _two_joint_households_and_an_individual(client)
        for partner_id in (single["id"], first["id"]):
            validate_error(
                client.link_household(
                    first["id"],
                    f.household_link_payload(partner_id, first["version"]),
                    headers=OFFICER,
                ),
                ERR_HOUSEHOLD_LINK_INVALID,
                409,
            )

        linked = validate_success(
            client.link_household(
                first["id"],
                f.household_link_payload(second["id"], first["version"]),
                headers=OFFICER,
            )
        )
        assert linked["household_partner_donor_id"] == second["id"]
        assert linked["version"] == first["version"] + 1

        partner = read_donor(client, second["id"])
        assert partner["household_partner_donor_id"] == first["id"]
        assert partner["version"] == second["version"] + 1
        assert read_donor(client, single["id"])["household_partner_donor_id"] is None


class TestSeatCapacityIsCheckedBeforeTheRowIsInserted:
    """Every individual payload is valid; only the collective count breaches."""

    def test_the_seat_that_would_exceed_capacity_is_refused(self, client):
        """One seat fits a capacity of 1 and the next one does not.

        PRD 3.7: "Seats may only be added while the section's `status` is `OPEN`
        — a section that is `UNDER_RENOVATION` or `CLOSED` rejects the addition
        with `ERR_SECTION_UNDER_RENOVATION` — and only while `seat_row_count`
        would remain within `seat_capacity`; the seat that would push it past
        capacity is refused with `ERR_SECTION_CAPACITY_EXCEEDED`."

        Design: Corner/validations/seat_creation_beyond_the_section_capacity_returns_capacity_exceeded
        """
        set_clock(client, f.instant(2026, 4, 1))
        section = create_section(client, seat_capacity=1)

        seat = validate_success(
            client.create_seat(section["id"], f.seat_payload("C", 1), headers=ADMIN),
            201,
        )
        assert seat["seat_status"] == SEAT_AVAILABLE
        assert seat["section_id"] == section["id"]

        refused = client.create_seat(
            section["id"], f.seat_payload("C", 2), headers=ADMIN
        )
        validate_error(refused, ERR_SECTION_CAPACITY_EXCEEDED, 409)

    def test_the_refused_seat_leaves_no_trace_on_the_section(self, client):
        """Counters, version and the seat collection all stop at one.

        PRD 3.7: "A new seat starts in `seat_status` `AVAILABLE`, increments the
        section's `seat_row_count` and `seats_available`, and advances the
        section's `version` by 1."

        Design: Corner/validations/seat_creation_beyond_the_section_capacity_returns_capacity_exceeded
        """
        set_clock(client, f.instant(2026, 4, 1))
        section = create_section(client, seat_capacity=1)
        validate_success(
            client.create_seat(section["id"], f.seat_payload("C", 1), headers=ADMIN),
            201,
        )
        validate_error(
            client.create_seat(section["id"], f.seat_payload("C", 2), headers=ADMIN),
            ERR_SECTION_CAPACITY_EXCEEDED,
            409,
        )

        after = read_section(client, section["id"])
        assert_seat_inventory(
            after,
            seats_available=1,
            seats_committed_count=0,
            decommissioned_seat_count=0,
            seat_row_count=1,
            label="SEC-C",
        )
        assert after["version"] == section["version"] + 1

        _rows, meta = validate_list(
            client.list_section_seats(section["id"], headers=ADMIN)
        )
        assert_page_meta(meta, total_count=1)


def _two_certified_donors(client):
    """A pool of exactly two, so every publication schedules two slots."""
    set_clock(client, f.instant(2026, 4, 1))
    bigger = register_donor(client, alumni_status=NON_ALUMNUS)
    add_received_gift(client, bigger["id"], 2000000, f.instant(2026, 3, 1))
    smaller = register_donor(client, alumni_status=NON_ALUMNUS)
    add_received_gift(client, smaller["id"], 1000000, f.instant(2026, 3, 1))
    cycle = certified_cycle(client, 2026)
    return bigger, smaller, cycle


class TestSlotOverflowIsAStrictExceedOnTheLastSlot:
    """Reaching window_end is fine; passing it publishes nothing at all."""

    def test_two_forty_minute_slots_overflow_a_sixty_minute_window(self, client):
        """Eighty minutes of schedule do not fit an hour, so nothing is written.

        PRD 3.8: "If the last slot's `slot_end` would fall strictly after
        `window_end`, nothing at all is published and the request is rejected with
        `ERR_SLOT_WINDOW_OVERFLOW` — the schedule is all-or-nothing."

        Design: Corner/validations/publishing_slots_that_do_not_fit_the_window_returns_slot_window_overflow
        """
        _bigger, _smaller, cycle = _two_certified_donors(client)
        event = create_event(
            client,
            cycle["id"],
            f.instant(2026, 9, 1),
            f.instant(2026, 9, 1, 1),
            40,
        )

        refused = client.publish_slots(event["id"], headers=OFFICER)
        validate_error(refused, ERR_SLOT_WINDOW_OVERFLOW, 422)

        after = read_event(client, event["id"])
        assert after["status"] == EVENT_DRAFT
        assert after["published_slot_count"] == 0
        assert after["scheduled_slot_count"] == 0

        _rows, meta = validate_list(
            client.list_selection_slots(
                headers=OFFICER, params={"selection_event_id": event["id"]}
            )
        )
        assert_page_meta(meta, total_count=0)

    def test_a_last_slot_that_ends_exactly_at_window_end_is_accepted(self, client):
        """Two thirty-minute slots tile the hour and the second one closes it.

        PRD 3.8: "Taking the ranked pool in order with a zero-based counter, each
        donor's `slot_index` is their position in that order; their `slot_start`
        is `window_start` advanced by the counter multiplied by the sum of
        `slot_minutes` and `slot_buffer_minutes`, expressed in minutes; and their
        `slot_end` is their `slot_start` advanced by `slot_minutes`."

        PRD 2.8: "The last computed slot's `slot_end` does not fall after the
        event's `window_end`."

        Design: Corner/validations/publishing_slots_that_do_not_fit_the_window_returns_slot_window_overflow
        """
        _bigger, _smaller, cycle = _two_certified_donors(client)
        event = create_event(
            client,
            cycle["id"],
            f.instant(2026, 9, 2),
            f.instant(2026, 9, 2, 1),
            30,
        )

        published = validate_success(client.publish_slots(event["id"], headers=OFFICER))
        assert published["status"] == EVENT_SLOTS_PUBLISHED
        assert published["published_slot_count"] == 2
        assert published["scheduled_slot_count"] == 2

        rows, meta = validate_list(
            client.list_selection_slots(
                headers=OFFICER, params={"selection_event_id": event["id"]}
            )
        )
        assert_page_meta(meta, total_count=2)
        assert [row["slot_index"] for row in rows] == [0, 1]
        assert_instant(rows[0]["slot_start"], f.instant(2026, 9, 2), "slot 0 start")
        assert_instant(
            rows[0]["slot_end"], f.instant(2026, 9, 2, 0, 30), "slot 0 end"
        )
        assert_instant(
            rows[1]["slot_start"], f.instant(2026, 9, 2, 0, 30), "slot 1 start"
        )
        assert_instant(rows[1]["slot_end"], f.instant(2026, 9, 2, 1), "slot 1 end")


def _read_transfer(client, donor_id, transfer_id):
    """Transfers are readable only through a donor's transfer collection."""
    rows, _meta = validate_list(
        client.list_donor_point_transfers(donor_id, headers=OFFICER)
    )
    matches = [row for row in rows if row["id"] == transfer_id]
    assert len(matches) == 1, "transfer {0} not found on donor {1}".format(
        transfer_id, donor_id
    )
    return matches[0]


def _death_basis_transfer_from_a_living_donor(client):
    """A DEATH-basis transfer that forks to EXCEPTION_PENDING on creation."""
    set_clock(client, f.instant(2026, 4, 1))
    source = register_donor(client, alumni_status=NON_ALUMNUS)
    add_received_gift(client, source["id"], 5000000, f.instant(2026, 3, 1))
    recipient = register_donor(client, alumni_status=NON_ALUMNUS)
    cycle = open_cycle(client, 2026)
    run_cycle(client, cycle["id"])

    transfer = validate_success(
        request_transfer(client, source["id"], recipient["id"], BASIS_DEATH, 10.00),
        201,
    )
    return source, recipient, transfer


class TestApprovingAnExceptionPendingTransferReportsTheCarveOut:
    """Step 9 hands this exact pair to step 13 for a more specific answer."""

    def test_the_fork_is_reported_as_a_missing_exception_not_a_bad_state(
        self, client
    ):
        """The basis precondition failed, so the answer names the exception.

        PRD 3.6: "When it does not hold, `exception_required` is true and the
        transfer is created directly in `EXCEPTION_PENDING` — the entry state of
        a brand-new transfer therefore depends on the source donor's own status
        and type, not on anything the requester supplies."

        PRD 3.6: "Attempting approval while the transfer is still in
        `EXCEPTION_PENDING` is not reported as an ordinary state error; it is
        reported specifically as `ERR_TRANSFER_POLICY_EXCEPTION_REQUIRED`, so that
        the caller learns *what* is missing rather than merely that the state is
        wrong."

        Design: Corner/validations/approving_an_exception_pending_transfer_reports_the_policy_carve_out_not_invalid_state
        """
        source, recipient, transfer = _death_basis_transfer_from_a_living_donor(client)
        assert transfer["status"] == TRANSFER_EXCEPTION_PENDING
        assert transfer["exception_required"] is True
        assert_points(transfer["transfer_pct_cap"], "1.00", "transfer_pct_cap")
        assert_points(
            transfer["max_transferable_points"], "67.50", "max_transferable_points"
        )

        refused = client.approve_point_transfer(transfer["id"], headers=CERTIFIER)
        validate_error(refused, ERR_TRANSFER_POLICY_EXCEPTION_REQUIRED, 422)

        after = _read_transfer(client, source["id"], transfer["id"])
        assert after["status"] == TRANSFER_EXCEPTION_PENDING
        assert_donor_points(
            read_donor(client, source["id"]),
            certified_points="67.50",
            label="source",
        )
        assert_donor_points(
            read_donor(client, recipient["id"]),
            transferred_points_in="0.00",
            label="recipient",
        )

    def test_the_policy_grant_unlocks_the_approval_without_moving_points(
        self, client
    ):
        """GRANT walks the transfer back to REQUESTED and nothing else.

        PRD 3.6: "Granting the exception moves `EXCEPTION_PENDING → REQUESTED`,
        requires the transfer to be in `EXCEPTION_PENDING`, stamps
        `exception_granted_by_user_id` with the committee member's `X-User-ID`,
        records the note as `decision_note`, and advances the transfer's
        `version` by 1."

        Design: Corner/validations/approving_an_exception_pending_transfer_reports_the_policy_carve_out_not_invalid_state
        """
        source, _recipient, transfer = _death_basis_transfer_from_a_living_donor(client)
        validate_error(
            client.approve_point_transfer(transfer["id"], headers=CERTIFIER),
            ERR_TRANSFER_POLICY_EXCEPTION_REQUIRED,
            422,
        )

        granted = validate_success(
            client.transfer_policy_decision(
                transfer["id"],
                f.transfer_policy_decision_payload(POLICY_GRANT),
                headers=POLICY,
            )
        )
        assert granted["status"] == TRANSFER_REQUESTED
        assert granted["exception_granted_by_user_id"] == POLICY_USER_ID
        assert_donor_points(
            read_donor(client, source["id"]),
            certified_points="67.50",
            transferred_points_out="0.00",
            label="source",
        )

    def test_the_identical_approval_then_succeeds_and_moves_the_points(self, client):
        """The same call that was refused now nets both donors' balances.

        PRD 3.6: "On success it adds `points_amount` to the recipient's
        `transferred_points_in` and the same amount to the source's
        `transferred_points_out`, recomputes `certified_points` for both donors,
        and stamps `approved_by_user_id` with the certifier's `X-User-ID`."

        Design: Corner/validations/approving_an_exception_pending_transfer_reports_the_policy_carve_out_not_invalid_state
        """
        source, recipient, transfer = _death_basis_transfer_from_a_living_donor(client)
        validate_error(
            client.approve_point_transfer(transfer["id"], headers=CERTIFIER),
            ERR_TRANSFER_POLICY_EXCEPTION_REQUIRED,
            422,
        )
        validate_success(
            client.transfer_policy_decision(
                transfer["id"],
                f.transfer_policy_decision_payload(POLICY_GRANT),
                headers=POLICY,
            )
        )

        approved = validate_success(
            client.approve_point_transfer(transfer["id"], headers=CERTIFIER)
        )
        assert approved["status"] == TRANSFER_APPROVED
        assert approved["approved_by_user_id"] == CERTIFIER_USER_ID
        assert_donor_points(
            read_donor(client, source["id"]),
            transferred_points_out="10.00",
            certified_points="57.50",
            label="source",
        )
        assert_donor_points(
            read_donor(client, recipient["id"]),
            transferred_points_in="10.00",
            certified_points="10.00",
            label="recipient",
        )


def _a_seated_donor_awaiting_a_relocation(client):
    """A donor seated in SEC-S with an open request to move to SEC-T."""
    set_clock(client, f.instant(2026, 4, 1))
    origin, origin_seats = create_section_with_seats(
        client,
        [("S", 1), ("S", 2)],
        section_code="SEC-S",
        venue_code="STADIUM-S",
        seat_capacity=2,
        per_seat_requirement_cents=100000,
        required_points_per_seat=0.00,
    )
    target, target_seats = create_section_with_seats(
        client,
        [("T", 1)],
        section_code="SEC-T",
        venue_code="STADIUM-T",
        seat_capacity=1,
        per_seat_requirement_cents=100000,
        required_points_per_seat=0.00,
    )
    donor = register_donor(client, alumni_status=NON_ALUMNUS)
    add_received_gift(client, donor["id"], 1000000, f.instant(2026, 3, 1))
    cycle = certified_cycle(client, 2026)
    event = publish_and_open(
        client, cycle["id"], f.instant(2026, 9, 1), f.instant(2026, 9, 5), 2880
    )

    set_clock(client, f.instant(2026, 9, 1, 12))
    slot = slot_for_donor(client, event["id"], donor["id"])
    held = pick_seat_ok(client, slot["id"], origin_seats[0]["id"], donor["id"])
    assignment = confirm_assignment(client, held["id"])
    request = get_success_data(
        file_relocation_request(
            client, donor["id"], assignment["id"], target["id"], event["id"]
        ),
    )
    assert request["status"] == RELOCATION_AWAITING_SELECTION
    return {
        "donor": donor,
        "origin": origin,
        "origin_seats": origin_seats,
        "target": target,
        "target_seats": target_seats,
        "assignment": assignment,
        "request": request,
    }


def _grant_naming(client, request_id, **extra):
    return client.decide_relocation_request(
        request_id, f.relocation_decision_payload(POLICY_GRANT, **extra), headers=OFFICER
    )


class TestARelocationTargetMustSitInTheTargetSection:
    """Priority 23 reads a third entity's section_id, and it reads it first."""

    def test_an_available_seat_in_the_origin_section_is_target_invalid(self, client):
        """S/2 is free, so the refusal cannot be about availability.

        PRD 3.9: "Granting moves `AWAITING_SELECTION → GRANTED` and requires the
        request to be in `AWAITING_SELECTION`, `target_seat_id` to name a seat in
        `seat_status` `AVAILABLE` that belongs to `target_section_id`, and the
        target section's `required_points_per_seat` to be at most the donor's
        `certified_points`."

        PRD 2.8: "A granted relocation supplies `target_seat_id`, and that seat
        belongs to `target_section_id`. This applies to a relocation decision.
        Violation: `ERR_RELOCATION_TARGET_INVALID` (422)."

        Design: Corner/validations/granting_a_relocation_onto_a_seat_outside_the_target_section_returns_target_invalid
        """
        state = _a_seated_donor_awaiting_a_relocation(client)
        stray = state["origin_seats"][1]
        assert read_seat(client, stray["id"])["seat_status"] == SEAT_AVAILABLE

        refused = _grant_naming(
            client, state["request"]["id"], target_seat_id=stray["id"]
        )
        validate_error(refused, ERR_RELOCATION_TARGET_INVALID, 422)

    def test_an_omitted_target_seat_is_target_invalid_not_malformed(self, client):
        """The field is optional in the contract, so its absence is a rule break.

        PRD 3.9: "A missing `target_seat_id`, or one naming a seat outside
        `target_section_id`, is refused with `ERR_RELOCATION_TARGET_INVALID`; a
        seat that is already `ASSIGNED` or `DECOMMISSIONED` with
        `ERR_SEAT_NOT_AVAILABLE`; a target section not in `status` `OPEN` with
        `ERR_SECTION_UNDER_RENOVATION`; and a points shortfall with
        `ERR_SEAT_POINTS_SHORTFALL`."

        Design: Corner/validations/granting_a_relocation_onto_a_seat_outside_the_target_section_returns_target_invalid
        """
        state = _a_seated_donor_awaiting_a_relocation(client)
        validate_error(
            _grant_naming(
                client,
                state["request"]["id"],
                target_seat_id=state["origin_seats"][1]["id"],
            ),
            ERR_RELOCATION_TARGET_INVALID,
            422,
        )

        validate_error(
            _grant_naming(client, state["request"]["id"]),
            ERR_RELOCATION_TARGET_INVALID,
            422,
        )

        still_open = read_relocation_request(client, state["request"]["id"])
        assert still_open["status"] == RELOCATION_AWAITING_SELECTION
        assert still_open["granted_seat_assignment_id"] is None
        assert read_donor(client, state["donor"]["id"])["pending_request_count"] == 1

    def test_the_seat_inside_the_target_section_is_granted(self, client):
        """T/1 clears clause two, and the swap runs on the same request.

        PRD 3.9: "On success a new seat assignment is created on the target seat
        with `pricing_mode` `MARKET` — a relocation always pays the market rate,
        never a grandfathered one — and with `selection_slot_id` left null
        because no slot was consumed; `granted_seat_assignment_id` is pointed at
        the new row; the assignment named by `current_seat_assignment_id` is
        released with `release_reason` `DONOR_RELEASE`; the donor's
        `pending_request_count` decrements; and the request's `version` advances
        by 1."

        PRD 3.9: "Under `MARKET` pricing, `requirement_cents` is simply the
        section's current `per_seat_requirement_cents`, with no escalator and no
        ceiling."

        Design: Corner/validations/granting_a_relocation_onto_a_seat_outside_the_target_section_returns_target_invalid
        """
        state = _a_seated_donor_awaiting_a_relocation(client)
        validate_error(
            _grant_naming(client, state["request"]["id"]),
            ERR_RELOCATION_TARGET_INVALID,
            422,
        )

        granted = validate_success(
            _grant_naming(
                client,
                state["request"]["id"],
                target_seat_id=state["target_seats"][0]["id"],
            )
        )
        assert granted["status"] == RELOCATION_GRANTED
        assert granted["granted_seat_assignment_id"] is not None

        minted = read_assignment(client, granted["granted_seat_assignment_id"])
        assert minted["seat_id"] == state["target_seats"][0]["id"]
        assert minted["pricing_mode"] == PRICING_MARKET
        assert minted["occupancy_status"] == OCCUPANCY_HELD
        assert_cents(minted["requirement_cents"], 100000, "requirement_cents")

        vacated = read_assignment(client, state["assignment"]["id"])
        assert vacated["occupancy_status"] == OCCUPANCY_RELEASED
        assert vacated["release_reason"] == RELEASE_DONOR_RELEASE
        assert (
            read_seat(client, state["origin_seats"][0]["id"])["seat_status"]
            == SEAT_AVAILABLE
        )
        assert (
            read_seat(client, state["origin_seats"][1]["id"])["seat_status"]
            == SEAT_AVAILABLE
        )
        assert read_donor(client, state["donor"]["id"])["pending_request_count"] == 0


def _a_section_with_a_fifty_point_floor(client):
    """SEC-P asks 50.00 points a seat; one donor clears it and one does not."""
    set_clock(client, f.instant(2026, 4, 1))
    section, seats = create_section_with_seats(
        client,
        [("P", 1), ("P", 2)],
        section_code="SEC-P",
        venue_code="STADIUM-P",
        seat_capacity=2,
        per_seat_requirement_cents=100000,
        required_points_per_seat=50.00,
    )
    rich = register_donor(client, alumni_status=NON_ALUMNUS)
    add_received_gift(client, rich["id"], 5000000, f.instant(2026, 3, 1))
    thin = register_donor(client, alumni_status=NON_ALUMNUS)
    add_received_gift(client, thin["id"], 1000000, f.instant(2026, 3, 1))
    cycle = certified_cycle(client, 2026)
    event = publish_and_open(
        client, cycle["id"], f.instant(2026, 9, 1), f.instant(2026, 9, 5), 2880
    )
    return section, seats, rich, thin, event


class TestTheSectionsPointsFloorIsCheckedOnTheSeatItself:
    """A valid in-window slot is not a licence to take any seat."""

    def test_the_donor_above_the_floor_freezes_the_floor_onto_the_row(self, client):
        """67.50 clears 50.00, and the row records both figures.

        PRD 3.9: "Two snapshots are frozen onto the row at creation and never
        move afterwards: `required_points` copies the section's
        `required_points_per_seat`, and `points_at_pick` copies the donor's
        `certified_points` as they stood at the moment of the pick."

        Design: Corner/validations/picking_below_the_sections_points_floor_returns_seat_points_shortfall
        """
        _section, seats, rich, _thin, event = _a_section_with_a_fifty_point_floor(client)
        set_clock(client, f.instant(2026, 9, 1, 12))

        slot = slot_for_donor(client, event["id"], rich["id"])
        assignment = pick_seat_ok(client, slot["id"], seats[0]["id"], rich["id"])

        assert_cents(assignment["requirement_cents"], 100000, "requirement_cents")
        assert_cents(assignment["total_due_cents"], 100000, "total_due_cents")
        assert_points(assignment["required_points"], "50.00", "required_points")
        assert assignment["eligibility_status"] == ELIGIBLE
        assert_points(assignment["points_at_pick"], "67.50", "points_at_pick")

    def test_the_donor_below_the_floor_is_refused_with_the_slot_intact(self, client):
        """15.00 is short of 50.00, so the pick is a 422 and the turn survives.

        PRD 3.9: "And if the donor's `certified_points` is below the section's
        `required_points_per_seat`, the pick is refused with
        `ERR_SEAT_POINTS_SHORTFALL`."

        PRD 2.8: "The donor's `certified_points` is at least the target section's
        `required_points_per_seat`. This applies to a seat pick and to a
        relocation decision. Violation: `ERR_SEAT_POINTS_SHORTFALL` (422)."

        Design: Corner/validations/picking_below_the_sections_points_floor_returns_seat_points_shortfall
        """
        section, seats, rich, thin, event = _a_section_with_a_fifty_point_floor(client)
        set_clock(client, f.instant(2026, 9, 1, 12))
        pick_seat_ok(
            client,
            slot_for_donor(client, event["id"], rich["id"])["id"],
            seats[0]["id"],
            rich["id"],
        )

        set_clock(client, f.instant(2026, 9, 3, 12))
        thin_slot = slot_for_donor(client, event["id"], thin["id"])
        spare = read_seat(client, seats[1]["id"])
        refused = pick_seat(client, thin_slot["id"], spare["id"], thin["id"])
        validate_error(refused, ERR_SEAT_POINTS_SHORTFALL, 422)

        after_seat = read_seat(client, spare["id"])
        assert after_seat["seat_status"] == SEAT_AVAILABLE
        assert after_seat["version"] == spare["version"]
        assert read_slot(client, thin_slot["id"])["slot_status"] == SLOT_SCHEDULED
        assert read_event(client, event["id"])["scheduled_slot_count"] == 1
        assert_seat_inventory(
            read_section(client, section["id"]),
            seats_available=1,
            seats_committed_count=1,
            decommissioned_seat_count=0,
            assigned_seat_count=1,
            seat_row_count=2,
            label="SEC-P",
        )


DISPUTE_WINDOW_END = "2026-09-30T00:00:00.000Z"


def _a_communicated_cycle_with_a_published_window(client):
    """One donor at 15.00 on a COMMUNICATED cycle closing at the instant above."""
    set_clock(client, f.instant(2026, 4, 1))
    donor = register_donor(client, alumni_status=NON_ALUMNUS)
    add_received_gift(client, donor["id"], 1000000, f.instant(2026, 3, 1))
    cycle = open_cycle(client, 2026, dispute_window_end=DISPUTE_WINDOW_END)
    run_cycle(client, cycle["id"])
    cycle = communicate_cycle(client, cycle["id"])
    assert cycle["status"] == RECALC_COMMUNICATED
    return donor, cycle


class TestTheDisputeWindowClosesStrictlyBeforeItsEnd:
    """The bound is exclusive, so the last millisecond still admits a filing."""

    def test_filing_at_the_window_end_exactly_is_refused(self, client):
        """At the closing instant the window is already shut.

        PRD 3.5: "Filing is admitted only while the current logical clock instant
        is strictly before the parent recalculation's `dispute_window_end`; at or
        after that instant the filing is rejected with
        `ERR_DISPUTE_WINDOW_CLOSED`."

        PRD 2.8: "The current logical clock instant is strictly earlier than the
        parent recalculation's `dispute_window_end`. This applies to filing a
        dispute and to deciding a dispute. Violation: `ERR_DISPUTE_WINDOW_CLOSED`
        (422)."

        Design: Corner/validations/filing_a_dispute_exactly_at_the_window_end_is_closed_but_one_millisecond_earlier_is_open
        """
        donor, cycle = _a_communicated_cycle_with_a_published_window(client)
        set_clock(client, DISPUTE_WINDOW_END)

        refused = client.create_dispute(
            f.dispute_payload(donor["id"], cycle["id"], 5.00),
            headers=make_donor_headers(donor["id"]),
        )
        validate_error(refused, ERR_DISPUTE_WINDOW_CLOSED, 422)

        _rows, meta = validate_list(
            client.list_disputes(
                headers=OFFICER, params={"recalculation_id": cycle["id"]}
            )
        )
        assert_page_meta(meta, total_count=0)

    def test_filing_one_millisecond_earlier_is_accepted(self, client):
        """The same body one tick earlier lands in SUBMITTED.

        PRD 3.5: "The new dispute lands in `SUBMITTED` with `info_request_rounds`
        at 0, `reviewed_by_user_id`, `decided_by_user_id`,
        `granted_points_delta` and `decided_at` all null."

        Design: Corner/validations/filing_a_dispute_exactly_at_the_window_end_is_closed_but_one_millisecond_earlier_is_open
        """
        donor, cycle = _a_communicated_cycle_with_a_published_window(client)
        last_tick = f.instant(2026, 9, 29, 23, 59, 59, 999)
        set_clock(client, last_tick)

        filed = validate_success(
            client.create_dispute(
                f.dispute_payload(donor["id"], cycle["id"], 5.00),
                headers=make_donor_headers(donor["id"]),
            ),
            201,
        )
        assert filed["status"] == DISPUTE_SUBMITTED
        assert filed["info_request_rounds"] == 0
        assert_points(filed["claimed_points_delta"], "5.00", "claimed_points_delta")
        assert filed["granted_points_delta"] is None
        assert_three_fractional_digits(filed["created_at"], "dispute.created_at")
        assert_instant(filed["created_at"], last_tick, "dispute.created_at")

        assert read_cycle(client, cycle["id"])["status"] == RECALC_COMMUNICATED


class TestRetentionAnalysisIsGatedOnCertificationNotOnItsInputs:
    """Every figure it needs already exists; the gate is still a hard 409."""

    def test_the_communicated_cycle_refuses_the_read(self, client):
        """The inputs are all present and the read is still refused.

        PRD 3.5: "Once a cycle is certified, the office can read a retention
        picture off it. This computed read requires the recalculation to be in
        `CERTIFIED` and is rejected with `ERR_RECALCULATION_NOT_CERTIFIED`
        otherwise."

        PRD 2.8: "The recalculation the operation depends on is in `CERTIFIED`.
        This applies to publishing slots for a selection event, starting a
        section's reseating, and reading a recalculation's retention analysis.
        Violation: `ERR_RECALCULATION_NOT_CERTIFIED` (409)."

        Design: Corner/validations/retention_analysis_on_a_communicated_cycle_is_refused_until_it_is_certified
        """
        donor, cycle = _a_communicated_cycle_with_a_published_window(client)
        assert_donor_points(
            read_donor(client, donor["id"]),
            certified_points="15.00",
            consecutive_giving_years=1,
            label="donor",
        )
        assert cycle["donors_processed_count"] == 1

        refused = client.get_retention_analysis(cycle["id"], headers=OFFICER)
        validate_error(refused, ERR_RECALCULATION_NOT_CERTIFIED, 409)

    def test_certifying_opens_the_same_read(self, client):
        """The one-donor picture: a single newcomer and a zero retention rate.

        PRD 3.5: "The response returns `cycle_year`, `donors_processed_count`,
        `retained_donor_count`, `new_donor_count`, `lapsed_risk_donor_count`,
        `retention_rate`, `average_certified_points` and `certified_points_sum`
        inline as a single object rather than as a stored resource."

        Design: Corner/validations/retention_analysis_on_a_communicated_cycle_is_refused_until_it_is_certified
        """
        _donor, cycle = _a_communicated_cycle_with_a_published_window(client)
        validate_error(
            client.get_retention_analysis(cycle["id"], headers=OFFICER),
            ERR_RECALCULATION_NOT_CERTIFIED,
            409,
        )

        certified = validate_success(
            client.certify_recalculation(
                cycle["id"], f.certify_payload(cycle["version"]), headers=CERTIFIER
            )
        )
        assert certified["status"] == RECALC_CERTIFIED

        analysis = validate_success(
            client.get_retention_analysis(cycle["id"], headers=OFFICER)
        )
        assert analysis["cycle_year"] == 2026
        assert analysis["donors_processed_count"] == 1
        assert analysis["retained_donor_count"] == 0
        assert analysis["new_donor_count"] == 1
        assert analysis["lapsed_risk_donor_count"] == 0
        assert_ratio(analysis["retention_rate"], "0.0000", "retention_rate")
        assert_points(
            analysis["average_certified_points"], "15.00", "average_certified_points"
        )
        assert_points(analysis["certified_points_sum"], "15.00", "certified_points_sum")


def _two_donors_with_published_slots(client):
    """Two SCHEDULED slots on one published, not yet opened, event."""
    set_clock(client, f.instant(2026, 4, 1))
    first = register_donor(client, alumni_status=NON_ALUMNUS)
    add_received_gift(client, first["id"], 2000000, f.instant(2026, 3, 1))
    second = register_donor(client, alumni_status=NON_ALUMNUS)
    add_received_gift(client, second["id"], 1000000, f.instant(2026, 3, 1))
    cycle = certified_cycle(client, 2026)
    event = create_event(
        client, cycle["id"], f.instant(2026, 9, 1), f.instant(2026, 9, 5), 2880
    )
    published = publish_slots(client, event["id"])
    assert published["published_slot_count"] == 2
    assert published["scheduled_slot_count"] == 2

    return {
        "first": first,
        "second": second,
        "event": published,
        "first_slot": slot_for_donor(client, event["id"], first["id"]),
        "second_slot": slot_for_donor(client, event["id"], second["id"]),
    }


def _forfeit(client, slot_id, headers, reason):
    return client.forfeit_slot(slot_id, f.forfeit_payload(reason=reason), headers=headers)


class TestForfeitingAPeersSlotIsAnOwnershipFailure:
    """The Donor role is on the endpoint, so the refusal names ownership."""

    def test_the_peer_donor_is_refused_as_a_non_owner(self, client):
        """Priority 3 compares X-User-ID with the slot's own donor_id.

        PRD 2.8: "For a caller acting as `Donor`, `X-User-ID` equals the
        `donor_id` of the targeted dispute, selection slot, relocation request or
        seat assignment. This applies to exactly five operations: filing a point
        dispute, providing information on a dispute, picking a seat through a
        selection slot, forfeiting a selection slot, and creating a relocation
        request. Violation: `ERR_NOT_RESOURCE_OWNER` (403)."

        Design: Corner/validations/a_donor_forfeiting_another_donors_slot_returns_not_resource_owner
        """
        state = _two_donors_with_published_slots(client)

        refused = _forfeit(
            client,
            state["first_slot"]["id"],
            make_donor_headers(state["second"]["id"]),
            "Peer donor attempting to release a slot that is not theirs",
        )
        validate_error(refused, ERR_NOT_RESOURCE_OWNER, 403)

        assert read_slot(client, state["first_slot"]["id"])["slot_status"] == (
            SLOT_SCHEDULED
        )
        assert read_event(client, state["event"]["id"])["scheduled_slot_count"] == 2

    def test_the_same_donor_may_forfeit_their_own_slot(self, client):
        """The identical call on their own slot is admitted.

        PRD 3.8: "Forfeiting moves the slot `SCHEDULED → FORFEITED`, requires the
        slot to be in `SCHEDULED` and — for a `Donor`-role caller — the caller's
        `X-User-ID` to equal the slot's `donor_id`, decrements the event's
        `scheduled_slot_count`, and advances the slot's `version` by 1."

        Design: Corner/validations/a_donor_forfeiting_another_donors_slot_returns_not_resource_owner
        """
        state = _two_donors_with_published_slots(client)
        validate_error(
            _forfeit(
                client,
                state["first_slot"]["id"],
                make_donor_headers(state["second"]["id"]),
                "Peer donor attempting to release a slot that is not theirs",
            ),
            ERR_NOT_RESOURCE_OWNER,
            403,
        )

        own = validate_success(
            _forfeit(
                client,
                state["second_slot"]["id"],
                make_donor_headers(state["second"]["id"]),
                "Own slot released voluntarily",
            )
        )
        assert own["slot_status"] == SLOT_FORFEITED
        assert own["version"] == state["second_slot"]["version"] + 1
        assert read_event(client, state["event"]["id"])["scheduled_slot_count"] == 1

    def test_the_development_officer_is_not_bound_by_the_ownership_clause(
        self, client
    ):
        """Priority 3 constrains only a Donor-role caller, so the office may act.

        PRD 3.1: "When `X-User-Role` is `DevelopmentOfficer`, `PointsCertifier`,
        `DisputeAnalyst`, `PolicyCommittee` or `PlatformAdmin`, `X-User-ID` is an
        opaque operator identifier that is not tied to any persisted entity: the
        server records it where a workflow demands an audit trail — as
        `initiated_by_user_id` and `certified_by_user_id` on a recalculation, as
        `reviewed_by_user_id` and `decided_by_user_id` on a dispute, and as
        `exception_granted_by_user_id` and `approved_by_user_id` on a point
        transfer — but never compares it to any entity's `id`."

        Design: Corner/validations/a_donor_forfeiting_another_donors_slot_returns_not_resource_owner
        """
        state = _two_donors_with_published_slots(client)
        validate_success(
            _forfeit(
                client,
                state["second_slot"]["id"],
                make_donor_headers(state["second"]["id"]),
                "Own slot released voluntarily",
            )
        )

        by_office = validate_success(
            _forfeit(
                client,
                state["first_slot"]["id"],
                OFFICER,
                "Released by the development office at the donor's request",
            )
        )
        assert by_office["slot_status"] == SLOT_FORFEITED

        after = read_event(client, state["event"]["id"])
        assert after["scheduled_slot_count"] == 0
        assert after["status"] == EVENT_SLOTS_PUBLISHED
        assert after["published_slot_count"] == 2


def _a_slot_left_stale_by_a_later_certification(client):
    """X holds an OPEN event's slot 0; a 2027 cycle then inverts the ranking."""
    set_clock(client, f.instant(2026, 4, 1))
    _section, seats = create_section_with_seats(
        client,
        [("K", 1), ("K", 2)],
        section_code="SEC-K",
        venue_code="STADIUM-K",
        seat_capacity=2,
        per_seat_requirement_cents=100000,
        required_points_per_seat=0.00,
    )
    leader = register_donor(client, alumni_status=NON_ALUMNUS)
    add_received_gift(client, leader["id"], 2000000, f.instant(2026, 3, 1))
    riser = register_donor(client, alumni_status=NON_ALUMNUS)
    add_received_gift(client, riser["id"], 1000000, f.instant(2026, 3, 1))

    first_cycle = certified_cycle(client, 2026)
    event = publish_and_open(
        client, first_cycle["id"], f.instant(2026, 9, 1), f.instant(2026, 9, 5), 2880
    )
    slot = slot_for_donor(client, event["id"], leader["id"])
    assert slot["slot_index"] == 0
    assert slot["rank_at_publish"] == 1

    add_received_gift(client, riser["id"], 5000000, f.instant(2027, 3, 1))
    certified_cycle(
        client,
        2027,
        cutoff_date=f.end_of_day(2027, 6, 30),
        dispute_window_end=f.end_of_day(2027, 9, 30),
    )

    set_clock(client, f.instant(2026, 9, 1, 12))
    return leader, riser, seats, event, slot


class TestPickingAStaleSlotNamesTheStalenessNotTheState:
    """Priority 9 hands this exact pair to priority 12 for a better answer."""

    def test_the_later_certification_inverts_the_pair_and_stales_the_event(
        self, client
    ):
        """The setup the carve-out needs: a STALE slot under a SLOTS_STALE event.

        PRD 3.5: "Every selection slot still in `SCHEDULED` whose
        `rank_at_publish` no longer equals its donor's freshly assigned
        `rank_position` moves `SCHEDULED → STALE`, and each such slot decrements
        its event's `scheduled_slot_count` and has its own `version` advanced by
        1."

        Design: Corner/validations/picking_a_stale_slot_reports_event_slots_stale_not_invalid_state
        """
        leader, riser, _seats, event, slot = _a_slot_left_stale_by_a_later_certification(
            client
        )

        assert_donor_points(
            read_donor(client, riser["id"]),
            certified_points="87.50",
            rank_position=1,
            label="riser",
        )
        assert_donor_points(
            read_donor(client, leader["id"]),
            certified_points="25.00",
            rank_position=2,
            label="leader",
        )

        stale_slot = read_slot(client, slot["id"])
        assert stale_slot["slot_status"] == SLOT_STALE
        assert stale_slot["rank_at_publish"] == 1

        stale_event = read_event(client, event["id"])
        assert stale_event["status"] == EVENT_SLOTS_STALE
        assert stale_event["scheduled_slot_count"] == 0

    def test_the_pick_reports_the_stale_event_rather_than_an_invalid_state(
        self, client
    ):
        """A STALE slot is no listed transition, and the answer still names step 12.

        PRD 2.8: "Two situations are carved out of this rule and reported by a
        later, more specific check instead: approving a transfer that is still in
        `EXCEPTION_PENDING` is reported at step 13 as
        `ERR_TRANSFER_POLICY_EXCEPTION_REQUIRED`, and picking through a slot in
        `STALE` whose event has fallen to `SLOTS_STALE` is reported at step 12 as
        `ERR_EVENT_SLOTS_STALE`."

        PRD 2.8: "A pick against a stale event reports `ERR_EVENT_SLOTS_STALE`,
        and a relocation request against an event in any other status reports
        `ERR_EVENT_NOT_OPEN_FOR_REQUESTS`; both carry HTTP 409."

        Design: Corner/validations/picking_a_stale_slot_reports_event_slots_stale_not_invalid_state
        """
        leader, _riser, seats, _event, slot = _a_slot_left_stale_by_a_later_certification(
            client
        )
        target = read_seat(client, seats[0]["id"])

        refused = pick_seat(client, slot["id"], target["id"], leader["id"])
        validate_error(refused, ERR_EVENT_SLOTS_STALE, 409)

        after_seat = read_seat(client, target["id"])
        assert after_seat["seat_status"] == SEAT_AVAILABLE
        assert after_seat["version"] == target["version"]
        assert read_slot(client, slot["id"])["slot_status"] == SLOT_STALE

        _rows, meta = validate_list(
            client.list_seat_assignments(
                headers=OFFICER, params={"donor_id": leader["id"]}
            )
        )
        assert_page_meta(meta, total_count=0)
