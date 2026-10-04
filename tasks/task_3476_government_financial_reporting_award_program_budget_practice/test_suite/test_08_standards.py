"""Standards coordination: clock-gated activation and the two-link
supersession cascade into checklists and pinned draft submissions
(PRD §3.7, §2.8).
"""

from test_helpers import (
    ApiErrorId,
    PLATFORM_ADMIN,
    activate_standard,
    create_checklist,
    create_cycle,
    create_draft_submission,
    create_government,
    create_standard,
    refresh_submission,
    set_logical_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_standards_activation_depth2_cascade(api):
    """PRD §3.7: "Activation moves the standard to `EFFECTIVE` and fires a
    three-link cascade: every other `EFFECTIVE` standard sharing the same
    `topic_code` is superseded to `SUPERSEDED`; the `ACTIVE` checklist version
    of the standard's `program_type` is superseded to `SUPERSEDED`; and every
    report submission still in `DRAFT` that pinned that checklist has its
    `pinned_checklist_stale` set to true, which bars it from submitting until
    a fresh cycle and checklist apply."
    PRD §2.8: "Pins do not float: if a pinned checklist is later superseded,
    drafts that pinned it are marked stale rather than silently re-pointed"

    Design: Difficulty/transitive_cascade/standards_activation_depth2_cascade
    """
    set_logical_clock(api, "2026-09-15T00:00:00Z")
    checklist = create_checklist(api)
    cycle = create_cycle(api, checklist["id"])
    government = create_government(api)
    submission = create_draft_submission(api, government["id"], cycle["id"])
    standard = create_standard(api, effective_date="2026-09-10T00:00:00Z")

    activated = activate_standard(api, standard["id"])
    assert activated["status"] == "EFFECTIVE"

    # Link 1: the program's ACTIVE checklist is superseded by the cascade.
    rows, meta = validate_paginated(
        api.list_checklist_versions(
            headers=PLATFORM_ADMIN, params={"program_type": "FINANCIAL_REPORTING"}
        )
    )
    by_id = {row["id"]: row["status"] for row in rows}
    assert by_id[checklist["id"]] == "SUPERSEDED"

    # Link 2: the DRAFT pinned to that checklist is flagged stale — the pin
    # itself is retained, only staleness flips.
    flagged = refresh_submission(api, submission["id"])
    assert flagged["pinned_checklist_stale"] is True
    assert flagged["status"] == "DRAFT"
    assert flagged["pinned_checklist_version_id"] == checklist["id"]


def test_standard_activate_before_effective_returns_not_yet_effective(api):
    """PRD §3.7: "Activation is a clock-gated, state-gated act. The logical
    clock must be at or after the standard's `effective_date`, else the
    activation is rejected with `ERR_STANDARD_NOT_YET_EFFECTIVE`, and the
    standard must still be `ISSUED` — an attempt to activate one that has
    already left that state is rejected with `ERR_STANDARD_STATE_INVALID`."

    Design: Corner/state_machines/standard_activate_before_effective_returns_not_yet_effective
    """
    set_logical_clock(api, "2026-09-15T00:00:00Z")
    checklist = create_checklist(api)
    standard = create_standard(api, effective_date="2026-10-01T00:00:00Z")

    early = api.activate_standards_reference(standard["id"], headers=PLATFORM_ADMIN)
    validate_error(early, ApiErrorId.ERR_STANDARD_NOT_YET_EFFECTIVE)

    # At exactly the effective date the >= boundary fires.  This activation
    # succeeding also proves the rejected attempt left the standard ISSUED —
    # anything else would have failed with ERR_STANDARD_STATE_INVALID.
    set_logical_clock(api, "2026-10-01T00:00:00Z")
    activated = activate_standard(api, standard["id"])
    assert activated["status"] == "EFFECTIVE"

    rows, _ = validate_paginated(
        api.list_checklist_versions(
            headers=PLATFORM_ADMIN, params={"program_type": "FINANCIAL_REPORTING"}
        )
    )
    by_id = {row["id"]: row["status"] for row in rows}
    assert by_id[checklist["id"]] == "SUPERSEDED", (
        "the cascade fires on the boundary activation"
    )
