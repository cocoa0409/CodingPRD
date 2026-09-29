"""Two opposite interval conventions guarding two different kinds of resource.

A representative is a single holder, so the double-booking test on badge windows
treats them as half-open and lets two cases sit back to back. A sterile
processing department is a bank of bays, so the occupation test is inclusive at
both ends and widens the tray set already holding a bay by half an hour on each
side before it counts collisions.
"""

from __future__ import annotations

from test_helpers import (
    AUTH_STATUS_APPROVED,
    AUTH_STATUS_REQUESTED,
    COMPLEXITY_SIMPLE,
    COMPLIANCE_ADMIN,
    ERR_REP_BADGE_WINDOW_CONFLICT,
    ERR_SPD_BAY_CAPACITY_EXCEEDED,
    LOANER_STATUS_EXPECTED,
    OR_COORDINATOR_2,
    READINESS_NOT_APPLICABLE,
    approved_product,
    assert_instant_equals,
    assert_instant_is_none,
    assert_integer_field,
    assert_total_count,
    assert_version_bumped,
    authorization_decision_payload,
    create_case,
    create_facility,
    create_vendor,
    credentialed_rep,
    decide_authorization,
    list_rows_and_meta,
    loaner_set_payload,
    make_vendor_admin_headers,
    read_authorization,
    read_case,
    read_loaner_set,
    read_vendor,
    read_vendor_rep,
    register_loaner_set,
    request_authorization,
    validate_error,
)


class TestBadgeWindowAdjacencyAndOverlap:
    """One representative, three cases: the touching pair boards, the straddling one does not."""

    @staticmethod
    def _setup(api):
        """Credential Ada Cole and approve her onto two back-to-back blocks at Ridgetop."""
        facility = create_facility(
            api,
            "RT-15",
            name="Ridgetop Surgical Hospital",
            spd_turnaround_hours=6,
            spd_bay_count=3,
        )
        vendor = create_vendor(
            api, "TEMPO", legal_name="Tempora Surgical Devices Inc"
        )
        rep = credentialed_rep(
            api,
            vendor["id"],
            "Ada Cole",
            issued_at_utc="2026-07-01T00:00:00Z",
            expires_at_utc="2027-07-01T00:00:00Z",
        )
        vendor_headers = make_vendor_admin_headers(vendor["id"])

        # Morning block 08:00-12:00 gives the badge window [07:00, 12:30).
        morning = create_case(
            api,
            facility["id"],
            "CASE-C3",
            "2026-09-22T08:00:00Z",
            "2026-09-22T12:00:00Z",
            procedure_name="Morning Block Support",
        )
        # Afternoon block 13:30-16:00 gives [12:30, 16:30), touching the morning window.
        afternoon = create_case(
            api,
            facility["id"],
            "CASE-C4",
            "2026-09-22T13:30:00Z",
            "2026-09-22T16:00:00Z",
            procedure_name="Afternoon Block Support",
        )
        # Add-on 13:00-15:00 gives [12:00, 15:30), thirty minutes inside the morning window.
        add_on = create_case(
            api,
            facility["id"],
            "CASE-C5",
            "2026-09-22T13:00:00Z",
            "2026-09-22T15:00:00Z",
            procedure_name="Overlapping Add-On Case",
        )

        requested_morning = request_authorization(
            api, morning["id"], rep["id"], headers=vendor_headers
        )
        approved_morning = decide_authorization(
            api, requested_morning["id"], "APPROVE"
        )
        requested_afternoon = request_authorization(
            api, afternoon["id"], rep["id"], headers=vendor_headers
        )
        approved_afternoon = decide_authorization(
            api, requested_afternoon["id"], "APPROVE"
        )
        requested_add_on = request_authorization(
            api, add_on["id"], rep["id"], headers=vendor_headers
        )
        return {
            "vendor": vendor,
            "rep": rep,
            "morning": morning,
            "afternoon": afternoon,
            "add_on": add_on,
            "approved_morning": approved_morning,
            "approved_afternoon": approved_afternoon,
            "requested_add_on": requested_add_on,
        }

    def test_adjacent_windows_touching_at_one_instant_are_both_approved(self, api):
        """Ada holds 07:00-12:30 and 12:30-16:30 at once, meeting at a single instant.

        "Adjacency is therefore legal — a window that ends at exactly the instant
        the next one begins does not conflict, and the approval is accepted." The
        windows themselves come from the site offsets: "`badge_window_start_utc`
        is the case's live `scheduled_start_utc` shifted earlier by the facility's
        `badge_lead_minutes` minutes, and `badge_window_end_utc` is the case's
        live `scheduled_end_utc` shifted later by the facility's
        `badge_grace_minutes` minutes."

        Design: Difficulty/resource_temporal_overlap/badge_window_overlap_rejected_while_adjacent_window_is_legal
        """
        state = self._setup(api)

        morning_authorization = read_authorization(
            api, state["approved_morning"]["id"]
        )
        assert morning_authorization["status"] == AUTH_STATUS_APPROVED
        assert_instant_equals(
            morning_authorization["badge_window_start_utc"],
            "2026-09-22T07:00:00Z",
            "badge_window_start_utc",
        )
        assert_instant_equals(
            morning_authorization["badge_window_end_utc"],
            "2026-09-22T12:30:00Z",
            "badge_window_end_utc",
        )

        afternoon_authorization = read_authorization(
            api, state["approved_afternoon"]["id"]
        )
        assert afternoon_authorization["status"] == AUTH_STATUS_APPROVED, (
            "the window that opens exactly when the morning window closes is bookable"
        )
        assert_instant_equals(
            afternoon_authorization["badge_window_start_utc"],
            "2026-09-22T12:30:00Z",
            "badge_window_start_utc",
        )
        assert_instant_equals(
            afternoon_authorization["badge_window_end_utc"],
            "2026-09-22T16:30:00Z",
            "badge_window_end_utc",
        )
        assert_integer_field(
            read_case(api, state["morning"]["id"]), "approved_rep_count", 1
        )
        assert_integer_field(
            read_case(api, state["afternoon"]["id"]), "approved_rep_count", 1
        )
        assert_integer_field(
            read_vendor_rep(api, state["rep"]["id"]), "open_authorization_count", 2
        )

    def test_thirty_minute_overlap_is_refused_and_moves_no_counter(self, api):
        """The add-on window straddles the morning window, so the approval is refused.

        "the representative has no other `APPROVED` authorization whose badge
        window overlaps the one this approval would create, else
        `ERR_REP_BADGE_WINDOW_CONFLICT` (409)", and windows "conflict when the
        first starts strictly before the second ends and the second starts
        strictly before the first ends".

        Design: Difficulty/resource_temporal_overlap/badge_window_overlap_rejected_while_adjacent_window_is_legal
        """
        state = self._setup(api)

        response = api.decide_authorization(
            state["requested_add_on"]["id"],
            authorization_decision_payload("APPROVE"),
            OR_COORDINATOR_2,
        )
        validate_error(response, ERR_REP_BADGE_WINDOW_CONFLICT)

        refused = read_authorization(api, state["requested_add_on"]["id"])
        assert refused["status"] == AUTH_STATUS_REQUESTED
        assert_instant_is_none(refused, "badge_window_start_utc")
        assert_instant_is_none(refused, "badge_window_end_utc")

        # Two approvals stand against the hard cap of six, so no quota gate is in play.
        assert_integer_field(
            read_vendor(api, state["vendor"]["id"]), "authorizations_used_epoch", 2
        )
        assert_integer_field(
            read_vendor_rep(api, state["rep"]["id"]), "open_authorization_count", 2
        )
        assert_integer_field(
            read_case(api, state["add_on"]["id"]), "approved_rep_count", 0
        )
        assert_integer_field(
            read_case(api, state["morning"]["id"]), "approved_rep_count", 1
        )
        assert_integer_field(
            read_case(api, state["afternoon"]["id"]), "approved_rep_count", 1
        )


class TestSterileProcessingBayBufferedCollision:
    """Summit Point runs one reprocessing bay, so the half-hour buffer decides admission."""

    @staticmethod
    def _setup(api):
        """Stage a four-tray SIMPLE set that holds the single bay from 04:00 to 10:00."""
        facility = create_facility(
            api,
            "SP-16",
            name="Summit Point Single Bay Center",
            spd_turnaround_hours=4,
            spd_bay_count=1,
        )
        vendor = create_vendor(
            api, "SPDX", legal_name="SPD Express Instruments Inc"
        )
        # A non-implant product, so no 24-hour implant floor distorts the lead time.
        _request, product = approved_product(
            api,
            vendor["id"],
            facility["id"],
            "PR-088",
            70000,
            is_implant=False,
            product_name="Power Reamer Tray Kit",
            manufacturer="SPD Express",
        )
        morning = create_case(
            api,
            facility["id"],
            "CASE-CA",
            "2026-09-20T10:00:00Z",
            "2026-09-20T12:00:00Z",
            procedure_name="Morning Reaming Case",
        )
        # Lead is 4 turnaround + 2 for SIMPLE + 0 tray surcharge = 6 hours.
        staged = register_loaner_set(
            api, vendor["id"], morning["id"], product["id"], 4, COMPLEXITY_SIMPLE
        )
        return facility, vendor, product, morning, staged

    def test_touching_occupation_is_refused_once_the_existing_set_is_buffered(self, api):
        """The afternoon set's occupation opens exactly where the morning set's closes, and is refused.

        "Each existing set's own occupation interval is widened by 30 minutes at
        each end to produce its buffered interval; the buffer is applied to the
        **existing** set only, never to the candidate. The candidate collides with
        an existing set when the existing set's buffered start is at or before the
        candidate's occupation end **and** the candidate's occupation start is at
        or before the existing set's buffered end — inclusive at both ends, so
        intervals that merely touch do collide."

        Design: Difficulty/resource_temporal_overlap/spd_bay_capacity_rejects_buffered_touching_occupation
        """
        facility, vendor, product, _morning, staged = self._setup(api)

        afternoon = create_case(
            api,
            facility["id"],
            "CASE-CB",
            "2026-09-20T16:00:00Z",
            "2026-09-20T18:00:00Z",
            procedure_name="Afternoon Reaming Case",
        )
        # Read the case immediately before the guarded write so the version echo matches.
        before = read_case(api, afternoon["id"])
        response = api.create_loaner_set(
            loaner_set_payload(
                afternoon["id"],
                product["id"],
                4,
                before["version"],
                COMPLEXITY_SIMPLE,
            ),
            make_vendor_admin_headers(vendor["id"]),
        )
        # The echoed version matched, so it is the counting exercise that refused
        # the write rather than the optimistic-concurrency rung.
        validate_error(response, ERR_SPD_BAY_CAPACITY_EXCEEDED)

        holder = read_loaner_set(api, staged["id"])
        assert_instant_equals(
            holder["required_delivery_deadline_utc"],
            "2026-09-20T04:00:00Z",
            "required_delivery_deadline_utc",
        )
        assert_instant_equals(
            holder["spd_occupation_start_utc"],
            "2026-09-20T04:00:00Z",
            "spd_occupation_start_utc",
        )
        assert_instant_equals(
            holder["spd_occupation_end_utc"],
            "2026-09-20T10:00:00Z",
            "spd_occupation_end_utc",
        )
        assert holder["status"] == LOANER_STATUS_EXPECTED, (
            "the morning set still holds the bay, which is why it still counts"
        )

        rows, meta = list_rows_and_meta(
            api.list_loaner_sets(
                COMPLIANCE_ADMIN, {"surgical_case_id": afternoon["id"]}
            )
        )
        assert_total_count(meta, 0)
        assert rows == [], "the refused registration wrote no tray set for the second case"

        after = read_case(api, afternoon["id"])
        assert_integer_field(after, "version", before["version"])
        assert after["implant_readiness_status"] == READINESS_NOT_APPLICABLE

    def test_occupation_opening_one_minute_past_the_buffer_is_admitted(self, api):
        """A case one minute later puts the candidate's occupation clear of the buffered interval.

        "If the number of colliding sets reaches the facility's `spd_bay_count`,
        the registration is refused with `ERR_SPD_BAY_CAPACITY_EXCEEDED`; a
        strictly smaller count admits the set." With the morning set buffered to
        end at 10:30, an occupation starting at 10:31 collides with nothing, so
        the count of colliding sets is zero against a bay count of one.

        Design: Difficulty/resource_temporal_overlap/spd_bay_capacity_rejects_buffered_touching_occupation
        """
        facility, vendor, product, _morning, staged = self._setup(api)

        evening = create_case(
            api,
            facility["id"],
            "CASE-CC",
            "2026-09-20T16:31:00Z",
            "2026-09-20T18:31:00Z",
            procedure_name="Evening Reaming Case",
        )
        before = read_case(api, evening["id"])
        admitted = register_loaner_set(
            api, vendor["id"], evening["id"], product["id"], 4, COMPLEXITY_SIMPLE
        )

        assert admitted["status"] == LOANER_STATUS_EXPECTED
        assert_instant_equals(
            admitted["required_delivery_deadline_utc"],
            "2026-09-20T10:31:00Z",
            "required_delivery_deadline_utc",
        )
        assert_instant_equals(
            admitted["spd_occupation_start_utc"],
            "2026-09-20T10:31:00Z",
            "spd_occupation_start_utc",
        )
        assert_instant_equals(
            admitted["spd_occupation_end_utc"],
            "2026-09-20T16:31:00Z",
            "spd_occupation_end_utc",
        )

        assert read_loaner_set(api, staged["id"])["status"] == LOANER_STATUS_EXPECTED
        assert_version_bumped(before, read_case(api, evening["id"]))
