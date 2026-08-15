"""Evidence items and packets: review cycle, windows, singletons, OCC."""
from test_helpers import (
    ApiErrorId,
    assert_instant_equals,
    assign_active_investigator,
    attach_report,
    case_version,
    create_case,
    create_measure,
    create_packet,
    drive_to_investigation,
    evidence_packet_payload,
    finalize_packet,
    get_case,
    hearing_payload,
    make_cast,
    make_coordinator_headers,
    make_investigator_headers,
    make_party_headers,
    release_packet,
    review_evidence_item,
    review_response_payload,
    set_clock,
    submit_evidence,
    submit_response,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client


def _case_with_active_investigator(cast, categories=("SEXUAL_HARASSMENT",)):
    case = create_case(cast, categories=list(categories), received_via="EMAIL")
    drive_to_investigation(case["id"], cast["coord"]["id"], cast["comp"]["id"])
    assign_active_investigator(case["id"], cast["coord"]["id"], cast["inv"]["id"])
    return case


def _released_packet(case, cast):
    packet = create_packet(case["id"], cast["coord"]["id"], cast["inv"]["id"])
    attach_report(packet["id"], cast["inv"]["id"])
    return release_packet(packet["id"], cast["inv"]["id"])


class TestEvidenceReviewCycle:
    def test_evidence_excluded_reconsideration_cycle(self, api):
        """PRD 3.3: "The item machine is cyclic with no terminal states: an
        `EXCLUDED` item can be reconsidered through begin-review (`EXCLUDED →
        UNDER_REVIEW`), and an `ACCEPTED` item returns to `UNDER_REVIEW` by
        cascade when the packet that pinned it is superseded — one
        `EVIDENCE_REVIEW_STARTED` per pinned item."
        PRD 3.3: "An `ACCEPTED` ruling clears any prior `exclusion_reason`,
        appends `EVIDENCE_RULED`".

        Design: Corner/state_machines/evidence_excluded_reconsideration_cycle
        """
        cast = make_cast("comp", "resp", "coord", "inv")
        case = _case_with_active_investigator(cast, categories=("STALKING",))
        item = submit_evidence(
            case["id"], cast["resp"]["id"], "party",
            submitted_by_side="RESPONDENT", evidence_type="MESSAGE_RECORD",
            description="Chat log",
        )
        excluded = review_evidence_item(
            item["id"], cast["inv"]["id"], "EXCLUDED", exclusion_reason="not directly related"
        )
        assert excluded["status"] == "EXCLUDED"
        assert excluded["exclusion_reason"] == "not directly related"

        # Reconsideration: EXCLUDED -> UNDER_REVIEW -> ACCEPTED.
        accepted = review_evidence_item(item["id"], cast["inv"]["id"], "ACCEPTED")
        assert accepted["status"] == "ACCEPTED"
        assert accepted.get("exclusion_reason") is None, (
            "the ACCEPTED ruling clears the prior exclusion_reason"
        )


class TestReviewWindow:
    def test_packet_auto_closes_on_second_response(self, api):
        """PRD 2.8: "The packet closes its review at the *earlier* of two moments:
        the instant both parties' responses have been recorded, or a
        reconciliation observing the clock at or past `review_closes_at`."
        PRD 3.3: "the moment the second party's response lands, the packet
        auto-closes `RELEASED_FOR_REVIEW → REVIEW_CLOSED` with
        `PACKET_REVIEW_CLOSED`."

        Design: Corner/calculations/packet_auto_closes_on_second_response
        """
        cast = make_cast("comp", "resp", "coord", "inv")
        case = _case_with_active_investigator(cast)
        packet = _released_packet(case, cast)

        first = submit_response(packet["id"], "COMPLAINANT", cast["comp"]["id"], "first")
        assert first["status"] == "RELEASED_FOR_REVIEW", (
            "one response leaves the window open for the other party"
        )
        second = submit_response(packet["id"], "RESPONDENT", cast["resp"]["id"], "second")
        assert second["status"] == "REVIEW_CLOSED", (
            "the second response closes the window immediately, before the deadline"
        )
        assert first["complainant_responded_at"] is not None
        assert second["respondent_responded_at"] is not None

    def test_review_response_at_exact_close_instant_accepted(self, api):
        """PRD 2.8: "A review response submitted at a logical instant on or before
        `review_closes_at` is timely — the close instant itself is inclusive —
        and a response even one second later is rejected with
        `ERR_REVIEW_RESPONSE_LATE` (422)."
        PRD 2.8: "A released evidence packet gives both parties 10 days to
        respond: `review_closes_at` is exactly `released_at` plus 10 days."

        Design: Difficulty/boundary_precision_check/review_response_at_exact_close_instant
        """
        cast = make_cast("comp", "resp", "coord", "inv")
        case = _case_with_active_investigator(cast)
        packet = _released_packet(case, cast)
        # Released at the default clock 2026-08-01T00:00:00Z.
        assert_instant_equals(
            packet["review_closes_at"], "2026-08-11T00:00:00Z", "review_closes_at"
        )

        set_clock("2026-08-11T00:00:00Z")
        on_time = submit_response(packet["id"], "COMPLAINANT", cast["comp"]["id"], "at the wire")
        assert_instant_equals(
            on_time["complainant_responded_at"], "2026-08-11T00:00:00Z",
            "complainant_responded_at",
        )
        assert on_time["status"] == "RELEASED_FOR_REVIEW"

    def test_review_response_one_second_late_rejected(self, api):
        """PRD 2.8: "A review response submitted at a logical instant on or before
        `review_closes_at` is timely — the close instant itself is inclusive —
        and a response even one second later is rejected with
        `ERR_REVIEW_RESPONSE_LATE` (422)."

        Design: Difficulty/boundary_precision_check/review_response_at_exact_close_instant
        """
        cast = make_cast("comp", "resp", "coord", "inv")
        case = _case_with_active_investigator(cast)
        packet = _released_packet(case, cast)

        set_clock("2026-08-11T00:00:00Z")
        submit_response(packet["id"], "COMPLAINANT", cast["comp"]["id"], "at the wire")

        set_clock("2026-08-11T00:00:01Z")
        resp = api.submit_review_response(
            packet["id"],
            review_response_payload("RESPONDENT", response_text="one second late"),
            make_party_headers(cast["resp"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REVIEW_RESPONSE_LATE)

        # Auto-close fires only on the second VALID response or reconcile.
        after = validate_success(
            api.get_evidence_packet(packet["id"], make_coordinator_headers(cast["coord"]["id"]))
        )
        assert after["status"] == "RELEASED_FOR_REVIEW"


class TestFinalizeGateAndSingleton:
    def test_finalize_while_review_window_open_rejected(self, api):
        """PRD 3.3: "It requires the packet in `REVIEW_CLOSED` — finalizing while
        the window is still open with responses outstanding is premature and
        rejected with `ERR_REVIEW_WINDOW_OPEN` (422)".

        Design: Corner/validations/finalize_while_review_window_open_rejected
        """
        cast = make_cast("comp", "resp", "coord", "inv")
        case = _case_with_active_investigator(cast)
        packet = _released_packet(case, cast)
        submit_response(packet["id"], "COMPLAINANT", cast["comp"]["id"], "ok")

        resp = api.finalize_packet(packet["id"], make_investigator_headers(cast["inv"]["id"]))
        validate_error(resp, ApiErrorId.ERR_REVIEW_WINDOW_OPEN)

        coord_h = make_coordinator_headers(cast["coord"]["id"])
        after = validate_success(api.get_evidence_packet(packet["id"], coord_h))
        assert after["status"] == "RELEASED_FOR_REVIEW"
        case_after = get_case(case["id"], cast["coord"]["id"])
        assert case_after["status"] == "EVIDENCE_REVIEW"


class TestLivePacketSingleton:
    def test_second_live_packet_rejected_with_fresh_version(self, api):
        """PRD 3.3: "Only one packet per case may be live — in `DRAFT`,
        `RELEASED_FOR_REVIEW`, or `REVIEW_CLOSED` — at a time; creating while one
        is live is rejected with `ERR_ACTIVE_PACKET_EXISTS` (409)."

        Design: Corner/validations/second_live_packet_rejected_with_fresh_version
        """
        cast = make_cast("comp", "resp", "coord", "inv")
        case = _case_with_active_investigator(cast, categories=("STALKING",))
        create_packet(case["id"], cast["coord"]["id"], cast["inv"]["id"])

        # A fresh, correct expected_case_version proves the singleton constraint
        # — not staleness — rejects the second create.
        fresh = case_version(case["id"], cast["coord"]["id"])
        resp = api.create_evidence_packet(
            case["id"], evidence_packet_payload(fresh),
            make_investigator_headers(cast["inv"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ACTIVE_PACKET_EXISTS)


class TestReviewResponseGates:
    def test_review_response_binding_and_duplicate_gates(self, api):
        """PRD 3.3: "A second response from the same side on the same packet is
        `ERR_DUPLICATE_RESPONSE` (409), and a side that does not match the case's
        party binding is `ERR_PARTY_BINDING_MISMATCH` (422)."

        Design: Corner/validations/review_response_binding_and_duplicate_gates
        """
        cast = make_cast("comp", "resp", "coord", "inv")
        case = _case_with_active_investigator(cast)
        packet = _released_packet(case, cast)

        # A party cannot submit under the opposing side's name.
        cross = api.submit_review_response(
            packet["id"],
            review_response_payload("RESPONDENT", response_text="impersonation attempt"),
            make_party_headers(cast["comp"]["id"]),
        )
        validate_error(cross, ApiErrorId.ERR_PARTY_BINDING_MISMATCH)

        legitimate = submit_response(packet["id"], "COMPLAINANT", cast["comp"]["id"], "legitimate")
        assert legitimate["complainant_responded_at"] is not None

        duplicate = api.submit_review_response(
            packet["id"],
            review_response_payload("COMPLAINANT", response_text="second time"),
            make_party_headers(cast["comp"]["id"]),
        )
        validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_RESPONSE)


class TestPacketCreateOcc:
    def test_occ_packet_create_stale_version_rejected(self, api):
        """PRD 2.10: "Exactly three write endpoints take part in optimistic
        concurrency control, and each requires the non-optional request field
        `expected_case_version`, carrying the client's last observed `version` of
        the parent case. If that value does not equal the case's current
        `version` at write time — because another writer has advanced the case's
        version since the client last read it — the request is rejected with
        `ERR_STALE_CASE_VERSION` (HTTP 412), forcing the client to re-read the
        case before writing."
        PRD 2.10: "- **Creating an evidence packet** against a case legitimately
        supersedes a `FINALIZED` predecessor packet (§3.3); a second create based
        on a pre-supersede view of the case would otherwise double-supersede."

        Design: Corner/cross_cutting_complexity_layers/occ_packet_create_stale_version_rejected
        """
        cast = make_cast("comp", "resp", "coord", "inv")
        case = _case_with_active_investigator(cast, categories=("STALKING",))
        observed = case_version(case["id"], cast["coord"]["id"])
        # Intervening write advances the case version after the client's read.
        create_measure(
            case["id"], cast["coord"]["id"],
            measure_type="COUNSELING", party_side="COMPLAINANT",
            description="Intervening write",
        )

        stale = api.create_evidence_packet(
            case["id"], evidence_packet_payload(observed),
            make_investigator_headers(cast["inv"]["id"]),
        )
        validate_error(stale, ApiErrorId.ERR_STALE_CASE_VERSION)

        fresh = case_version(case["id"], cast["coord"]["id"])
        ok = api.create_evidence_packet(
            case["id"], evidence_packet_payload(fresh),
            make_investigator_headers(cast["inv"]["id"]),
        )
        packet = validate_success(ok, 201)
        assert packet["status"] == "DRAFT"


class TestHearingGatedOnPacket:
    def _case_with_review_closed_packet(self, cast):
        case = _case_with_active_investigator(cast)
        packet = create_packet(case["id"], cast["coord"]["id"], cast["inv"]["id"])
        attach_report(packet["id"], cast["inv"]["id"])
        packet = release_packet(packet["id"], cast["inv"]["id"])
        submit_response(packet["id"], "COMPLAINANT", cast["comp"]["id"], "ok")
        packet = submit_response(packet["id"], "RESPONDENT", cast["resp"]["id"], "ok")
        assert packet["status"] == "REVIEW_CLOSED"
        return case, packet

    def test_hearing_creation_rejected_until_packet_finalized(self, api):
        """PRD 3.4: "The case must be in `HEARING_PREPARATION` — a state only
        packet finalization produces, so a `FINALIZED` packet necessarily
        exists."
        PRD 2.11: "**State** — the target entity must be in a from-state from which
        the requested transition exists in its machine, with terminal states
        rejecting all further transitions (`ERR_INVALID_STATE_TRANSITION`, 409)".

        Design: Difficulty/cross_entity_state_dependency/hearing_creation_gated_on_packet_finalized
        """
        cast = make_cast("comp", "resp", "coord", "inv", "dm")
        case, packet = self._case_with_review_closed_packet(cast)
        coord_h = make_coordinator_headers(cast["coord"]["id"])

        # Case is EVIDENCE_REVIEW while the packet is REVIEW_CLOSED.
        assert get_case(case["id"], cast["coord"]["id"])["status"] == "EVIDENCE_REVIEW"
        rejected = api.schedule_hearing(
            case["id"], hearing_payload(cast["dm"]["id"]), coord_h
        )
        validate_error(rejected, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        finalize_packet(packet["id"], cast["inv"]["id"])
        accepted = api.schedule_hearing(
            case["id"], hearing_payload(cast["dm"]["id"]), coord_h
        )
        hearing = validate_success(accepted, 201)
        assert hearing["status"] == "SCHEDULED"

    def test_packet_finalize_is_the_enabling_transition(self, api):
        """PRD 3.3: "Finalization moves the packet `REVIEW_CLOSED → FINALIZED`,
        moves the case `EVIDENCE_REVIEW → HEARING_PREPARATION`, moves the case's
        `ACTIVE` investigator assignment to `COMPLETED`, appends
        `PACKET_FINALIZED`, and increments the case `version`."

        Design: Difficulty/cross_entity_state_dependency/hearing_creation_gated_on_packet_finalized
        """
        cast = make_cast("comp", "resp", "coord", "inv", "dm")
        case, packet = self._case_with_review_closed_packet(cast)
        coord_h = make_coordinator_headers(cast["coord"]["id"])

        finalized = finalize_packet(packet["id"], cast["inv"]["id"])
        assert finalized["status"] == "FINALIZED"
        case_after = get_case(case["id"], cast["coord"]["id"])
        assert case_after["status"] == "HEARING_PREPARATION"

        accepted = api.schedule_hearing(
            case["id"], hearing_payload(cast["dm"]["id"]), coord_h
        )
        hearing = validate_success(accepted, 201)
        assert hearing["status"] == "SCHEDULED"
