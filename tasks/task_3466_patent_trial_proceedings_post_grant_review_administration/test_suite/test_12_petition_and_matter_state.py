"""Petition and litigation-matter state machine corners (PRD §3.2, §3.4)."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    DEFAULT_CLOCK_ISO,
    PANEL,
    accord,
    api_client,
    assert_litigation_matter,
    assert_petition,
    assert_same_instant,
    create_litigation_matter,
    decide_institution,
    file_petition,
    get_litigation_matter,
    get_petition,
    new_world,
    patch_litigation_matter,
    per_ground_scores,
    set_clock,
    setup_instituted_proceeding,
    validate_error,
    validate_paginated,
)


def test_accord_filing_date_stamps_accorded_date_from_logical_clock():
    """PRD §3.4: "A successful accordance moves the petition from `FILED` to
    `NOTICE_ACCORDED`, stamps `accorded_date` from the logical clock —
    opening the institution window — and refreshes the provisional
    `fintiv_score` against the decision-relevant matters."

    Design: Corner/state_machines/accord_filing_date_stamps_accorded_date_from_logical_clock
    """
    world = new_world(petitioner_name="PF Corp", owner_name="OF Corp")
    petition = file_petition(world["petitioner"]["id"], world["patent"]["id"],
                             challenged_claims=[1])
    assert petition["status"] == "FILED"
    assert_same_instant(petition["filing_date"], DEFAULT_CLOCK_ISO, "filing_date")
    data = accord(petition["id"])
    assert_petition(data)
    assert data["status"] == "NOTICE_ACCORDED"
    assert_same_instant(data["accorded_date"], DEFAULT_CLOCK_ISO, "accorded_date")


def test_accord_on_already_accorded_petition_rejected():
    """PRD §3.4: "Accordance is allowed only while the petition is `FILED`;
    against any other status it fails with `ERR_PETITION_WRONG_STATE`."

    Design: Corner/state_machines/accord_on_already_accorded_petition_rejected
    """
    world = new_world(petitioner_name="PG Corp", owner_name="OG Corp")
    petition = file_petition(world["petitioner"]["id"], world["patent"]["id"],
                             challenged_claims=[1])
    accord(petition["id"])
    resp = api_client.accord_filing_date(petition["id"], PANEL)
    validate_error(resp, ApiErrorId.ERR_PETITION_WRONG_STATE, 409)


def test_decide_institution_before_accord_rejected():
    """PRD §3.4: "The petition must be in `NOTICE_ACCORDED`
    (`ERR_PETITION_WRONG_STATE` otherwise)".

    Design: Corner/state_machines/decide_institution_before_accord_rejected
    """
    world = new_world(petitioner_name="PH Corp", owner_name="OH Corp")
    petition = file_petition(world["petitioner"]["id"], world["patent"]["id"],
                             challenged_claims=[1])
    resp = api_client.decide_institution(
        petition["id"],
        {"per_ground_scores": per_ground_scores((1, 80)),
         "lead_judge_user_id": "judge-tess"},
        PANEL,
    )
    validate_error(resp, ApiErrorId.ERR_PETITION_WRONG_STATE, 409)
    assert get_petition(petition["id"])["status"] == "FILED"
    # No Proceeding was created for the rejected decision.
    _, meta = validate_paginated(api_client.list_proceedings(PANEL, params={}))
    assert meta["total_count"] == 0


def test_litigation_matter_terminal_states_lock_further_patches():
    """PRD §3.2: "`SETTLED`, `TRIAL_COMPLETED`, and `DISMISSED` are terminal;
    patching a matter that has reached any of them is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/litigation_matter_terminal_states_lock_further_patches
    """
    world = new_world(petitioner_name="PI Corp", owner_name="OI Corp")
    matter = create_litigation_matter(
        world["patent"]["id"], world["petitioner"]["id"],
        "2026-01-01T00:00:00Z", court_name="N.D. Cal.",
        docket_number="3:25-cv-00999",
    )
    settled = patch_litigation_matter(
        matter["id"],
        {"status": "SETTLED",
         "expected_litigation_matter_version": matter["version"]},
    )
    resp = api_client.patch_litigation_matter(
        matter["id"],
        {"status": "STAYED",
         "expected_litigation_matter_version": settled["version"]},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    assert get_litigation_matter(matter["id"])["status"] == "SETTLED"


def test_denied_petition_is_terminal():
    """PRD §3.4: "A denial leaves the petition `DENIED` and terminal." and
    "The petition must be in `NOTICE_ACCORDED` (`ERR_PETITION_WRONG_STATE`
    otherwise)".

    Design: Corner/state_machines/denied_petition_is_terminal
    """
    world = new_world(petitioner_name="PJ Corp", owner_name="OJ Corp")
    petition = file_petition(world["petitioner"]["id"], world["patent"]["id"],
                             challenged_claims=[1])
    accord(petition["id"])
    decision = decide_institution(
        petition["id"], per_ground_scores((1, 10)), "judge-ulric"
    )
    assert decision["outcome"] == "DENIED_MERITS"
    # A higher second score cannot reopen the terminal petition.
    resp = api_client.decide_institution(
        petition["id"],
        {"per_ground_scores": per_ground_scores((1, 95)),
         "lead_judge_user_id": "judge-ulric"},
        PANEL,
    )
    validate_error(resp, ApiErrorId.ERR_PETITION_WRONG_STATE, 409)
    # Nor can a fresh accord.
    resp2 = api_client.accord_filing_date(petition["id"], PANEL)
    validate_error(resp2, ApiErrorId.ERR_PETITION_WRONG_STATE, 409)


def test_litigation_matter_active_stayed_active_cycle_preserves_fields():
    """PRD §3.2: "from `STAYED`, it may return to `ACTIVE` — the stay is
    lifted and `stay_reason` returns to null" and "The `stay_reason` field
    records provenance whenever the matter stands in `STAYED`: `MANUAL_STAY`
    when the administrator stayed it directly, `INSTITUTION_STAY` when the
    institution cascade stayed it, and `PATENT_CANCELLED` when the
    full-cancellation cascade stayed it; the field is null in every
    non-`STAYED` status."

    Design: Corner/state_machines/litigation_matter_active_stayed_active_cycle_preserves_fields
    """
    world = new_world(petitioner_name="PM Corp", owner_name="OM Corp")
    matter = create_litigation_matter(
        world["patent"]["id"], world["petitioner"]["id"],
        "2026-02-01T00:00:00Z", trial_date="2027-05-01T00:00:00Z",
        court_name="S.D.N.Y.", docket_number="1:25-cv-01100",
    )
    stayed = patch_litigation_matter(
        matter["id"],
        {"status": "STAYED",
         "expected_litigation_matter_version": matter["version"]},
    )
    assert_litigation_matter(stayed)
    assert stayed["status"] == "STAYED"
    assert stayed["stay_reason"] == "MANUAL_STAY"
    assert stayed["version"] == matter["version"] + 1
    lifted = patch_litigation_matter(
        matter["id"],
        {"status": "ACTIVE",
         "expected_litigation_matter_version": stayed["version"]},
    )
    assert lifted["status"] == "ACTIVE"
    assert lifted["stay_reason"] is None
    assert_same_instant(lifted["trial_date"], "2027-05-01T00:00:00Z", "trial_date")
