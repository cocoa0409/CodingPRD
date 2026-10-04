"""Party conduct: strike accumulation, seat suspension, and the expulsion
cascade (PRD §3.4).

The second strike (inclusive threshold) auto-suspends a seat; expulsion
requires a qualifying PREMATURE_PUBLIC_STATEMENT entry and cascades through
seats, groups, and the investigation's completeness figure.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    conduct_violation_payload,
    expel_designation,
    expel_party_designation_payload,
    find_report,
    find_seat,
    get_designation,
    get_group,
    get_investigation,
    record_conduct_violation,
    setup_docket_released,
    setup_on_scene,
    validate_error,
)

MD_PROPOSER = TEST_USERS["md_proposer_headers"]


class TestStrikeAccumulation:
    def test_strike_threshold_suspends_seat_and_reconciles_seated_count(self, api):
        """PRD §3.4: "A violation can only be recorded against a `SEATED` seat
        (`ERR_SEAT_NOT_SEATED`)." PRD §3.4: "The seat's `strike_count` is
        simply the length of that log. When the count reaches two — the
        threshold is inclusive — a `SEATED` seat automatically becomes
        `SUSPENDED`, and the referenced group's `seated_count` is recomputed."

        Design: Corner/calculations/strike_threshold_suspends_seat_and_reconciles_seated_count
        """
        ctx = setup_on_scene()
        designation_id = ctx["designation"]["id"]
        seat_id = ctx["seat_id"]
        group_id = ctx["group"]["id"]

        after_one = record_conduct_violation(
            designation_id,
            seat_id,
            violation_kind="UNAUTHORIZED_ANALYSIS_DISCLOSURE",
            detail="Shared draft analysis with a non-party affiliate.",
        )
        seat = find_seat(after_one, seat_id=seat_id)
        assert seat["strike_count"] == 1
        assert seat["status"] == "SEATED"
        assert get_group(group_id)["seated_count"] == 1

        after_two = record_conduct_violation(
            designation_id,
            seat_id,
            violation_kind="EX_PARTE_CONTACT",
            detail="Undisclosed contact with a board member.",
        )
        seat = find_seat(after_two, seat_id=seat_id)
        assert seat["strike_count"] == 2
        assert seat["status"] == "SUSPENDED", "the >= 2 threshold is inclusive"
        assert get_group(group_id)["seated_count"] == 0

        # A third strike cannot land: the seat is no longer SEATED.
        resp = api.record_conduct_violation(
            designation_id,
            seat_id,
            conduct_violation_payload("EX_PARTE_CONTACT", "Second undisclosed contact."),
            TEST_USERS["iic_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_SEAT_NOT_SEATED)


class TestExpulsionGate:
    def test_expel_without_qualifying_violation_returns_constraint_error(self, api):
        """PRD §3.4: "It requires cause: at least one
        `PREMATURE_PUBLIC_STATEMENT` entry must exist somewhere across the
        conduct logs of the designation's seats, and without one the expulsion
        is rejected with `ERR_EXPULSION_WITHOUT_QUALIFYING_VIOLATION`."

        Design: Corner/validations/expel_without_qualifying_violation_returns_constraint_error
        """
        ctx = setup_on_scene()
        record_conduct_violation(
            ctx["designation"]["id"],
            ctx["seat_id"],
            violation_kind="EX_PARTE_CONTACT",
            detail="Undisclosed contact with a board member.",
        )

        resp = api.expel_party_designation(
            ctx["designation"]["id"],
            expel_party_designation_payload(reason="General misconduct."),
            MD_PROPOSER,
        )
        validate_error(resp, ApiErrorId.ERR_EXPULSION_WITHOUT_QUALIFYING_VIOLATION)

        designation = get_designation(ctx["designation"]["id"])
        assert designation["status"] == "ACTIVE"
        seat = find_seat(designation, seat_id=ctx["seat_id"])
        assert seat["status"] == "SEATED"
        assert seat["strike_count"] == 1

    def test_double_expel_returns_designation_not_active(self, api):
        """PRD §3.4: "Expulsion is the severe remedy, exercised by a
        `ManagingDirector` against an `ACTIVE` designation
        (`ERR_DESIGNATION_NOT_ACTIVE` otherwise)."

        Design: Corner/errors/double_expel_returns_designation_not_active
        """
        ctx = setup_on_scene()
        record_conduct_violation(
            ctx["designation"]["id"],
            ctx["seat_id"],
            violation_kind="PREMATURE_PUBLIC_STATEMENT",
            detail="Briefed reporters before the docket opened.",
        )
        expelled = expel_designation(
            ctx["designation"]["id"], reason="Premature public statement."
        )
        assert expelled["status"] == "EXPELLED"

        resp = api.expel_party_designation(
            ctx["designation"]["id"],
            expel_party_designation_payload(reason="Expel again."),
            MD_PROPOSER,
        )
        validate_error(resp, ApiErrorId.ERR_DESIGNATION_NOT_ACTIVE)

        designation = get_designation(ctx["designation"]["id"])
        assert designation["status"] == "EXPELLED"
        assert find_seat(designation, seat_id=ctx["seat_id"])["status"] == "REMOVED"


class TestExpulsionCascade:
    def test_expulsion_empties_complete_group_and_recomputes_docket(self, api):
        """PRD §3.4: "Every embedded seat in `SEATED` or `SUSPENDED` status
        becomes `REMOVED`, and each referenced group's `seated_count` is
        recomputed. Any group left with zero seated parties by those removals
        reverts from `COMPLETE` back to `ACTIVE` if it had already completed.
        Finally the investigation's `docket_completeness_pct` is recomputed,
        and the investigation's own `version` and `updated_at` are bumped — an
        expulsion is never a purely local event." PRD §3.4: "The payload's
        optional `reason` text is recorded as the designation's
        `expulsion_reason`, the designation becomes `EXPELLED`, and its
        `version` increments."

        Design: Difficulty/transitive_cascade/transitive_cascade_expulsion_empties_complete_group
        """
        ctx = setup_docket_released()
        designation_id = ctx["designation"]["id"]
        group_id = ctx["group"]["id"]
        inv_id = ctx["investigation"]["id"]
        assert ctx["investigation"]["docket_completeness_pct"] == 100
        assert ctx["group"]["status"] == "COMPLETE"

        record_conduct_violation(
            designation_id,
            ctx["seat_id"],
            violation_kind="PREMATURE_PUBLIC_STATEMENT",
            detail="Party counsel briefed reporters on the factual record before the board meeting.",
        )
        expelled = expel_designation(
            designation_id, reason="Premature public statement on investigation findings."
        )

        # Link 1: the designation itself.
        assert expelled["status"] == "EXPELLED"
        assert (
            expelled["expulsion_reason"]
            == "Premature public statement on investigation findings."
        )
        # Link 2: its seat is removed.
        assert find_seat(expelled, seat_id=ctx["seat_id"])["status"] == "REMOVED"
        # Link 3: the emptied COMPLETE group reverts to ACTIVE.
        group = get_group(group_id)
        assert group["status"] == "ACTIVE"
        assert group["seated_count"] == 0
        # Link 4: the completeness figure recomputes on the investigation.
        investigation = get_investigation(inv_id)
        assert investigation["docket_completeness_pct"] == 0
        # An opened public docket is not re-sealed by expulsion.
        assert investigation["docket_status"] == "OPEN"

    def test_expulsion_cascade_bumps_versions_and_preserves_docketed_report(self, api):
        """PRD §3.4: "the investigation's own `version` and `updated_at` are
        bumped — an expulsion is never a purely local event." PRD §3.4: "Each
        accepted entry appends to the seat's append-only `conduct_log` —
        recorded with its `violation_kind`, `detail`, and a `recorded_at` stamp
        from the logical clock — and the designation's `version` increments."
        PRD §3.5: "A successful release moves every `VERIFIED` report across
        the investigation's groups to `DOCKETED`" — and nothing in the
        expulsion cascade withdraws a docketed report.

        Design: Difficulty/transitive_cascade/transitive_cascade_expulsion_empties_complete_group
        """
        ctx = setup_docket_released()
        designation_id = ctx["designation"]["id"]
        inv_id = ctx["investigation"]["id"]
        inv_version_before = ctx["investigation"]["version"]
        dsg_version_before = get_designation(designation_id)["version"]

        violated = record_conduct_violation(
            designation_id,
            ctx["seat_id"],
            violation_kind="PREMATURE_PUBLIC_STATEMENT",
            detail="Briefed reporters before the docket opened.",
        )
        assert violated["version"] == dsg_version_before + 1

        expelled = expel_designation(designation_id, reason="Premature public statement.")
        assert expelled["version"] == dsg_version_before + 2

        investigation = get_investigation(inv_id)
        assert investigation["version"] == inv_version_before + 1

        # The public factual record is never withdrawn by an expulsion.
        group = get_group(ctx["group"]["id"])
        assert find_report(group, report_id=ctx["report_id"])["status"] == "DOCKETED"
