"""Identity resolution: name changes, mergers and dissolutions."""
from test_helpers import (
    ApiErrorId,
    create_grant,
    create_org,
    finalize_identity_case,
    get_org,
    list_grants,
    make_admin_headers,
    open_identity_case,
    set_clock,
    validate_error,
    validate_success,
)


def test_identity_case_finalize_withdraw_leaves_the_organization_graph_untouched(api):
    """PRD §3.8: "Withdrawal is the quiet branch: a `WITHDRAW` decision moves the
    case from `OPEN` to `WITHDRAWN`, mutates no organization at all, and increments
    only the case's own `version` by 1."

    Design: Corner/endpoints/identity_case_finalize_withdraw_leaves_the_organization_graph_untouched
    """
    set_clock()
    subject = create_org("Willow Creek Collective", "900100200", state_code="IL")
    survivor = create_org("Prairie Food Bank", "900100201", state_code="IL")
    case = open_identity_case(subject["id"], "MERGE", surviving_org_id=survivor["id"],
                              resolution_note="Proposed merger.")

    resp = api.finalize_identity_case(
        case["id"], {"resolution_decision": "WITHDRAW"}, make_admin_headers())
    withdrawn = validate_success(resp, 200)
    assert withdrawn["status"] == "WITHDRAWN"

    after_subject = get_org(subject["id"])
    assert after_subject["profile_status"] == "DRAFT"
    assert after_subject.get("successor_organization_id") is None
    assert get_org(survivor["id"])["distinct_funder_count"] == 0

    for org_id in (subject["id"], survivor["id"]):
        assert get_org(org_id).get("successor_organization_id") != survivor["id"]


def test_merge_case_whose_successor_chain_loops_returns_merge_cycle_detected(api):
    """PRD §3.8: "A `MERGE` must also not create a cycle: following the
    `successor_organization_id` chain outward from the surviving organization must
    never arrive back at the subject organization, and a chain that does is refused
    with `ERR_MERGE_CYCLE_DETECTED` (HTTP 409)."

    Design: Corner/errors/merge_case_whose_successor_chain_loops_returns_merge_cycle_detected
    """
    set_clock()
    absorbed = create_org("Willow Creek Collective", "900100200", state_code="IL")
    survivor = create_org("Prairie Food Bank", "900100201", state_code="IL")

    first_case = open_identity_case(absorbed["id"], "MERGE",
                                    surviving_org_id=survivor["id"],
                                    resolution_note="First merger.")
    finalize_identity_case(first_case["id"])
    assert get_org(absorbed["id"])["successor_organization_id"] == survivor["id"]

    reverse_case = open_identity_case(survivor["id"], "MERGE",
                                      surviving_org_id=absorbed["id"],
                                      resolution_note="Reverse merger attempt.")
    resp = api.finalize_identity_case(
        reverse_case["id"], {"resolution_decision": "FINALIZE"}, make_admin_headers())
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}: {resp.text}"
    validate_error(resp, ApiErrorId.ERR_MERGE_CYCLE_DETECTED.value)

    cases = api.list_identity_cases(survivor["id"], make_admin_headers())
    rows = validate_success(cases, 200)
    assert any(c["id"] == reverse_case["id"] and c["status"] == "OPEN" for c in rows), (
        "the refused finalization must leave the case OPEN"
    )

    assert get_org(survivor["id"])["profile_status"] == "DRAFT"
    assert get_org(survivor["id"]).get("successor_organization_id") is None
    assert get_org(absorbed["id"])["successor_organization_id"] == survivor["id"]


# DELETED (PRD-silence / non-unique-derivability): the corner instance
# `dissolution_case_carrying_a_surviving_organization_returns_identity_case_invalid`
# required POST /nonprofits/identity-cases to accept a DISSOLUTION case that names
# a surviving organization, so that the refusal could be asserted on the
# OPEN->FINALIZED transition. PRD §3.8 states the same field-combination rule in
# the case-creation paragraph — "A `DISSOLUTION` requires `surviving_organization_id`
# to be null. ... Any combination that violates these rules is refused with
# `ERR_IDENTITY_CASE_INVALID` (HTTP 409)." — so a faithful PRD-only implementation
# may refuse the create instead, which makes the test's setup unbuildable. The
# refusal's timing is not pinned by the PRD; the scaffold-only rule was the
# transition precondition on state_machines.IdentityResolutionCase.OPEN_to_FINALIZED.


# ---------------------------------------------------------------------------
# Merge finalization cascade (difficulty instance)
# ---------------------------------------------------------------------------

def _merge_setup():
    """Northgate Pantry holds two RECORDED grants and merges into Southgate Services."""
    absorbed = create_org("Northgate Pantry", "111222333", state_code="MN")
    survivor = create_org("Southgate Services", "444555666", state_code="MN")
    funder = create_org("Harborlight Fund", "777888999", state_code="MN")
    create_grant(absorbed["id"], survivor["id"], funder_name_raw="Southgate Services",
                 recipient_name_raw="Northgate Pantry", recipient_ein="111222333",
                 amount_cents=5000000, fiscal_year=2025)
    create_grant(absorbed["id"], funder["id"], funder_name_raw="Harborlight Fund",
                 recipient_name_raw="Northgate Pantry", recipient_ein="111222333",
                 amount_cents=2500000, fiscal_year=2025)
    case = open_identity_case(absorbed["id"], "MERGE",
                              surviving_org_id=survivor["id"],
                              resolution_note="Northgate Pantry merged into Southgate Services.")
    return absorbed, survivor, funder, case


def test_merge_finalization_reassigns_grants_and_recomputes_funder_count(api):
    """PRD §3.8: "The number of re-pointed grant rows is recorded on the case as
    `reassigned_grant_count`, and the surviving organization's `distinct_funder_count`
    is recomputed because its set of recorded grants has changed."
    PRD §3.8: "The subject organization's `profile_status` moves to `MERGED` and its
    `successor_organization_id` is set to the case's `surviving_organization_id`."

    Design: Difficulty/transitive_cascade/merge_finalization_cascades_three_hops_to_surviving_funder_count
    """
    set_clock()
    absorbed, survivor, funder, case = _merge_setup()

    finalized = validate_success(api.finalize_identity_case(
        case["id"], {"resolution_decision": "FINALIZE"}, make_admin_headers()), 200)
    assert finalized["status"] == "FINALIZED"
    assert finalized["reassigned_grant_count"] == 2

    absorbed_after = get_org(absorbed["id"])
    assert absorbed_after["profile_status"] == "MERGED"
    assert absorbed_after["successor_organization_id"] == survivor["id"]
    assert absorbed_after["distinct_funder_count"] == 0

    survivor_after = get_org(survivor["id"])
    assert survivor_after["distinct_funder_count"] == 2, (
        "both re-pointed grants now hang off the surviving organization"
    )


def test_merge_finalization_moves_the_whole_grant_history_to_the_survivor(api):
    """PRD §3.8: "Every `Grant` whose `recipient_organization_id` is the absorbed
    organization is re-pointed to the surviving organization, and every `Grant`
    whose `funder_organization_id` is the absorbed organization is re-pointed as
    well — the absorbed organization's grant history, both incoming and outgoing,
    moves wholesale."

    Design: Difficulty/transitive_cascade/merge_finalization_cascades_three_hops_to_surviving_funder_count
    """
    set_clock()
    absorbed, survivor, funder, case = _merge_setup()
    finalize_identity_case(case["id"])

    survivor_grants = list_grants(survivor["id"])
    assert len(survivor_grants) == 2
    assert all(g["recipient_organization_id"] == survivor["id"] for g in survivor_grants)

    absorbed_grants = list_grants(absorbed["id"])
    assert absorbed_grants == [], "no grant still points at the absorbed organization"
