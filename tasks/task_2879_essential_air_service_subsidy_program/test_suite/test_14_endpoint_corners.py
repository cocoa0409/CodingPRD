"""Endpoint corners: the ranking preview, superseding preference filings,
preference membership and aircraft retirement.

The harness restarts the API against an empty database before every test, so
each test builds all of its own preconditions through declared endpoints.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_append_only_row,
    assert_money,
    assert_ratio,
)
from test_helpers.constants import (
    CARRIER_ACTIVE,
    CARRIER_SUSPENDED,
    DEFAULT_CLOCK,
    EVAL_NOT_SELECTED,
    EVAL_SELECTED,
    EVAL_UNDER_EVALUATION,
    PROPOSAL_DRAFT,
    PROPOSAL_SUBMIT,
    PROPOSAL_SUBMITTED,
    SERVICE_LEVEL_ENHANCED,
    SOLICITATION_AWARDED,
    SOLICITATION_CLOSED,
    STANDING_REINSTATE,
    STANDING_SUSPEND,
)
from test_helpers.test_users import ADMIN, OFFICER


UNKNOWN_PROPOSAL_ID = "00000000-0000-4000-8000-000000000005"

TWO_CANDIDATE_SECOND = {
    "service_level": SERVICE_LEVEL_ENHANCED,
    "weekly_round_trips": 13,
    "annual_subsidy_request_usd": 1700000.00,
}


def _two_candidates(api: ApiClient):
    """A CLOSED solicitation with candidate A at 12 round trips / 1,600,000.00
    and candidate B at 13 round trips / 1,700,000.00."""
    return fx.build_two_candidate_solicitation(
        api,
        clock=DEFAULT_CLOCK,
        second_overrides=dict(TWO_CANDIDATE_SECOND),
        close=True,
    )


def _proposal(api: ApiClient, proposal_id: str):
    return validate_success(api.get_proposal(proposal_id, ADMIN))


# ─── endpoints / ranking_preview_scores_the_live_candidate_set ────────

def test_ranking_preview_scores_both_live_candidates_without_persisting(api: ApiClient):
    """The preview ranks the two live candidates and writes nothing at all.

    "The read-only ranking preview scores the solicitation's current candidate set and answers with `candidate_count`, the `top_proposal_id` and its `top_composite_score`, the full `ranked_proposal_ids` list in ranked order, and the `excluded_proposal_ids` that the candidate filter rejected."

    Design: Corner/endpoints/ranking_preview_scores_the_live_candidate_set
    """
    built = _two_candidates(api)
    solicitation_id = built["solicitation"]["id"]
    proposal_a = _proposal(api, built["proposal_a"]["id"])
    proposal_b = _proposal(api, built["proposal_b"]["id"])

    # The per-passenger prices the subsidy component is computed from.
    assert proposal_a["projected_annual_passengers"] == 8892
    assert_money(
        proposal_a["subsidy_per_passenger_usd"], 179.94, "subsidy_per_passenger_usd A"
    )
    assert proposal_b["projected_annual_passengers"] == 9633
    assert_money(
        proposal_b["subsidy_per_passenger_usd"], 176.48, "subsidy_per_passenger_usd B"
    )

    preview = validate_success(api.get_ranking(solicitation_id, OFFICER))
    assert preview["candidate_count"] == 2
    assert preview["ranked_proposal_ids"] == [proposal_b["id"], proposal_a["id"]]
    assert preview["excluded_proposal_ids"] == []
    assert preview["top_proposal_id"] == proposal_b["id"]
    assert_ratio(preview["top_composite_score"], 60.0000, "top_composite_score")

    # Nothing moved: no score written, no state changed.
    assert _proposal(api, proposal_a["id"])["composite_score"] is None
    assert _proposal(api, proposal_b["id"])["composite_score"] is None
    solicitation = validate_success(api.get_solicitation(solicitation_id, ADMIN))
    assert solicitation["status"] == SOLICITATION_CLOSED
    assert solicitation["selected_proposal_id"] is None
    assert solicitation["candidate_count_at_award"] is None


def test_suspending_a_carrier_moves_its_proposal_into_the_excluded_set(api: ApiClient):
    """Suspending a bidder re-runs the filter and re-normalises the survivor.

    "A carrier that has been suspended or debarred since it bid takes its proposals out of contention."

    Design: Corner/endpoints/ranking_preview_scores_the_live_candidate_set
    """
    built = _two_candidates(api)
    reference = built["ref"]
    solicitation_id = built["solicitation"]["id"]
    proposal_a_id = built["proposal_a"]["id"]
    proposal_b_id = built["proposal_b"]["id"]

    first = validate_success(api.get_ranking(solicitation_id, OFFICER))
    assert first["candidate_count"] == 2

    suspended = validate_success(
        api.carrier_standing_action(
            reference.second_carrier_id,
            f.carrier_standing_payload(STANDING_SUSPEND, note="maintenance findings"),
            ADMIN,
        )
    )
    assert suspended["status"] == CARRIER_SUSPENDED

    second = validate_success(api.get_ranking(solicitation_id, OFFICER))
    assert second["candidate_count"] == 1
    assert second["ranked_proposal_ids"] == [proposal_a_id]
    assert second["excluded_proposal_ids"] == [proposal_b_id]
    assert second["top_proposal_id"] == proposal_a_id
    # A is now its own cheapest per-passenger bid, so it scores the full
    # 0.35 * 100.0000 + 0.25 * 100.0000 with no preference points.
    assert_ratio(second["top_composite_score"], 60.0000, "top_composite_score")

    # The excluded proposal was untouched: only its carrier's standing changed.
    excluded = _proposal(api, proposal_b_id)
    assert excluded["submission_state"] == PROPOSAL_SUBMITTED
    assert excluded["evaluation_state"] == EVAL_UNDER_EVALUATION
    assert excluded["composite_score"] is None


def test_selection_order_persists_every_candidates_composite_score(api: ApiClient):
    """The order writes the losing score too and books the winner's agreement.

    "Every candidate's `composite_score` is written to its row, so the scores of the losers remain auditable."

    Design: Corner/endpoints/ranking_preview_scores_the_live_candidate_set
    """
    built = _two_candidates(api)
    reference = built["ref"]
    solicitation_id = built["solicitation"]["id"]
    proposal_a_id = built["proposal_a"]["id"]
    proposal_b_id = built["proposal_b"]["id"]

    validate_success(
        api.carrier_standing_action(
            reference.second_carrier_id,
            f.carrier_standing_payload(STANDING_SUSPEND, note="maintenance findings"),
            ADMIN,
        )
    )
    reinstated = validate_success(
        api.carrier_standing_action(
            reference.second_carrier_id,
            f.carrier_standing_payload(STANDING_REINSTATE, note="findings closed"),
            ADMIN,
        )
    )
    assert reinstated["status"] == CARRIER_ACTIVE

    agreement = validate_success(
        api.create_selection_order(
            solicitation_id,
            f.selection_order_payload(order_note="lowest subsidy per passenger wins"),
            OFFICER,
        ),
        201,
    )

    winner = _proposal(api, proposal_b_id)
    loser = _proposal(api, proposal_a_id)
    assert_ratio(winner["composite_score"], 60.0000, "winner composite_score")
    assert_ratio(loser["composite_score"], 59.3270, "loser composite_score")
    assert winner["evaluation_state"] == EVAL_SELECTED
    assert loser["evaluation_state"] == EVAL_NOT_SELECTED

    assert agreement["carrier_id"] == reference.second_carrier_id
    assert agreement["proposal_id"] == proposal_b_id
    assert agreement["min_weekly_round_trips"] == 13
    assert agreement["min_monthly_seats"] == 2140


# ─── endpoints / superseding_preference_filing_replaces_the_ranking_input

def test_first_preference_filing_becomes_the_ranking_input(api: ApiClient):
    """An accepted filing stamps its rows and drives the composite ranking.

    "An accepted filing increments the solicitation's `preference_filing_count` by 1, creates one preference row per ranking entry stamped with a `filing_sequence` equal to that new count, records `filed_by_user_id` as the acting `X-User-ID` — which is the community's own `id` — and increments the solicitation's `version` by 1."

    Design: Corner/endpoints/superseding_preference_filing_replaces_the_ranking_input
    """
    built = _two_candidates(api)
    reference = built["ref"]
    solicitation_id = built["solicitation"]["id"]
    proposal_a_id = built["proposal_a"]["id"]
    proposal_b_id = built["proposal_b"]["id"]
    community_headers = reference.community_headers

    before = validate_success(api.get_solicitation(solicitation_id, community_headers))
    filed = validate_success(
        api.file_preferences(
            solicitation_id,
            f.preference_filing_payload(
                before["version"],
                f.ranking_entries(proposal_a_id, proposal_b_id),
                rationale="incumbent crew base preferred",
            ),
            community_headers,
        ),
        201,
    )
    assert filed["preference_filing_count"] == 1
    assert filed["version"] == before["version"] + 1

    rows, meta = validate_paginated(
        api.list_solicitation_preferences(solicitation_id, ADMIN)
    )
    assert meta["total_count"] == 2
    assert [row["proposal_id"] for row in rows] == [proposal_a_id, proposal_b_id]
    assert [row["rank"] for row in rows] == [1, 2]
    for row in rows:
        assert row["filing_sequence"] == 1
        assert row["rationale"] == "incumbent crew base preferred"
        assert row["filed_by_user_id"] == reference.community_id
        assert_append_only_row(row)

    ranking = validate_success(api.get_ranking(solicitation_id, OFFICER))
    assert ranking["top_proposal_id"] == proposal_a_id
    assert_ratio(ranking["top_composite_score"], 99.3270, "top_composite_score")
    assert ranking["ranked_proposal_ids"] == [proposal_a_id, proposal_b_id]


def test_second_preference_filing_supersedes_the_first_and_flips_the_award(api: ApiClient):
    """Re-filing in the reverse order changes the winner the order books.

    "A community that changes its mind simply files again; the previous ranking contributes nothing from that moment on."

    Design: Corner/endpoints/superseding_preference_filing_replaces_the_ranking_input
    """
    built = _two_candidates(api)
    reference = built["ref"]
    solicitation_id = built["solicitation"]["id"]
    proposal_a_id = built["proposal_a"]["id"]
    proposal_b_id = built["proposal_b"]["id"]
    community_headers = reference.community_headers

    first_version = validate_success(
        api.get_solicitation(solicitation_id, community_headers)
    )["version"]
    validate_success(
        api.file_preferences(
            solicitation_id,
            f.preference_filing_payload(
                first_version,
                f.ranking_entries(proposal_a_id, proposal_b_id),
                rationale="incumbent crew base preferred",
            ),
            community_headers,
        ),
        201,
    )

    second_version = validate_success(
        api.get_solicitation(solicitation_id, community_headers)
    )["version"]
    assert second_version == first_version + 1

    refiled = validate_success(
        api.file_preferences(
            solicitation_id,
            f.preference_filing_payload(
                second_version,
                f.ranking_entries(proposal_b_id, proposal_a_id),
                rationale="city council reversed its vote",
            ),
            community_headers,
        ),
        201,
    )
    assert refiled["preference_filing_count"] == 2
    assert refiled["version"] == first_version + 2

    ranking = validate_success(api.get_ranking(solicitation_id, OFFICER))
    assert ranking["top_proposal_id"] == proposal_b_id
    assert_ratio(ranking["top_composite_score"], 100.0000, "top_composite_score")
    assert ranking["ranked_proposal_ids"] == [proposal_b_id, proposal_a_id]

    agreement = validate_success(
        api.create_selection_order(
            solicitation_id,
            f.selection_order_payload(order_note="awarded on the second filing"),
            OFFICER,
        ),
        201,
    )
    assert agreement["proposal_id"] == proposal_b_id
    assert_ratio(
        _proposal(api, proposal_b_id)["composite_score"], 100.0000, "winner composite"
    )
    assert_ratio(
        _proposal(api, proposal_a_id)["composite_score"], 79.3270, "loser composite"
    )


def test_both_preference_generations_remain_readable_after_a_superseding_filing(api: ApiClient):
    """The superseded rows stay stored and are still listed and filterable.

    "Earlier filings remain stored and remain readable, but the selection ranking consults **only** the rows whose `filing_sequence` equals the solicitation's current `preference_filing_count`."

    Design: Corner/endpoints/superseding_preference_filing_replaces_the_ranking_input
    """
    built = _two_candidates(api)
    reference = built["ref"]
    solicitation_id = built["solicitation"]["id"]
    proposal_a_id = built["proposal_a"]["id"]
    proposal_b_id = built["proposal_b"]["id"]
    community_headers = reference.community_headers

    first_version = validate_success(
        api.get_solicitation(solicitation_id, community_headers)
    )["version"]
    validate_success(
        api.file_preferences(
            solicitation_id,
            f.preference_filing_payload(
                first_version,
                f.ranking_entries(proposal_a_id, proposal_b_id),
                rationale="incumbent crew base preferred",
            ),
            community_headers,
        ),
        201,
    )
    validate_success(
        api.file_preferences(
            solicitation_id,
            f.preference_filing_payload(
                first_version + 1,
                f.ranking_entries(proposal_b_id, proposal_a_id),
                rationale="city council reversed its vote",
            ),
            community_headers,
        ),
        201,
    )

    rows, meta = validate_paginated(
        api.list_solicitation_preferences(solicitation_id, ADMIN)
    )
    assert meta["total_count"] == 4
    assert [(row["filing_sequence"], row["rank"]) for row in rows] == [
        (1, 1), (1, 2), (2, 1), (2, 2)
    ]
    assert [row["proposal_id"] for row in rows] == [
        proposal_a_id, proposal_b_id, proposal_b_id, proposal_a_id
    ]

    superseded, superseded_meta = validate_paginated(
        api.list_solicitation_preferences(
            solicitation_id, ADMIN, {"filing_sequence": 1}
        )
    )
    assert superseded_meta["total_count"] == 2
    assert [row["proposal_id"] for row in superseded] == [proposal_a_id, proposal_b_id]
    for row in superseded:
        assert row["rationale"] == "incumbent crew base preferred"

    current, current_meta = validate_paginated(
        api.list_solicitation_preferences(
            solicitation_id, ADMIN, {"filing_sequence": 2}
        )
    )
    assert current_meta["total_count"] == 2
    assert [row["proposal_id"] for row in current] == [proposal_b_id, proposal_a_id]
    for row in current:
        assert row["rationale"] == "city council reversed its vote"

    ranked_a, ranked_a_meta = validate_paginated(
        api.list_proposal_preferences(proposal_a_id, ADMIN)
    )
    assert ranked_a_meta["total_count"] == 2
    assert [(row["filing_sequence"], row["rank"]) for row in ranked_a] == [(1, 1), (2, 2)]


# ─── endpoints / preference_rankings_must_name_this_solicitations_submitted_proposals

def _two_solicitations(api: ApiClient):
    """Two eligible communities, each with an OPEN solicitation.

    Solicitation 1 holds one SUBMITTED and one DRAFT proposal; solicitation 2
    holds one SUBMITTED proposal from the same carrier.
    """
    reference = fx.make_reference_data(
        api, clock=DEFAULT_CLOCK, with_second_carrier=False
    )
    second_community = fx.register_second_community(api, enplanements_prior_year=5100)
    first = fx.open_solicitation(api, reference.community_id)
    second = fx.open_solicitation(api, second_community["id"])
    submitted_here = fx.submitted_proposal(
        api, first["id"], reference.carrier_id, reference.aircraft_type_id
    )
    draft_here = fx.draft_proposal(
        api,
        first["id"],
        reference.carrier_id,
        reference.aircraft_type_id,
        service_level=SERVICE_LEVEL_ENHANCED,
        weekly_round_trips=14,
        annual_subsidy_request_usd=1800000.00,
    )
    submitted_there = fx.submitted_proposal(
        api,
        second["id"],
        reference.carrier_id,
        reference.aircraft_type_id,
        annual_subsidy_request_usd=1550000.00,
    )
    return {
        "ref": reference,
        "second_community": second_community,
        "first": validate_success(api.get_solicitation(first["id"], ADMIN)),
        "second": validate_success(api.get_solicitation(second["id"], ADMIN)),
        "submitted_here": submitted_here,
        "draft_here": draft_here,
        "submitted_there": submitted_there,
    }


def test_preference_filing_must_name_a_submitted_proposal_of_this_solicitation(api: ApiClient):
    """A foreign proposal and a draft proposal are both refused as non-members.

    "A filing that names a proposal belonging to some other solicitation, or one whose `submission_state` is not `SUBMITTED`, is refused with `ERR_PROPOSAL_NOT_IN_SOLICITATION`; a `proposal_id` that resolves to no stored proposal at all is refused with `ERR_PROPOSAL_NOT_FOUND`."

    Design: Corner/endpoints/preference_rankings_must_name_this_solicitations_submitted_proposals
    """
    built = _two_solicitations(api)
    solicitation = built["first"]
    headers = built["ref"].community_headers

    foreign = api.file_preferences(
        solicitation["id"],
        f.preference_filing_payload(
            solicitation["version"],
            f.ranking_entries(built["submitted_there"]["id"]),
            rationale="names the other solicitations proposal",
        ),
        headers,
    )
    validate_error(foreign, E.ERR_PROPOSAL_NOT_IN_SOLICITATION, 409)

    with_draft = api.file_preferences(
        solicitation["id"],
        f.preference_filing_payload(
            solicitation["version"],
            f.ranking_entries(
                built["submitted_here"]["id"], built["draft_here"]["id"]
            ),
            rationale="includes a draft proposal",
        ),
        headers,
    )
    validate_error(with_draft, E.ERR_PROPOSAL_NOT_IN_SOLICITATION, 409)

    unchanged = validate_success(api.get_solicitation(solicitation["id"], ADMIN))
    assert unchanged["preference_filing_count"] == 0
    assert unchanged["version"] == solicitation["version"]
    _, meta = validate_paginated(
        api.list_solicitation_preferences(solicitation["id"], ADMIN)
    )
    assert meta["total_count"] == 0


def test_preference_filing_naming_an_unknown_proposal_is_a_not_found(api: ApiClient):
    """An unresolvable proposal id fails existence before membership.

    "Existence — every identifier referenced in the path or the body resolves to a stored row, checked left to right: the path identifier first, then body foreign keys in this declaration order — `community_id`, `carrier_id`, `aircraft_type_id`, `solicitation_id`, `proposal_id`, `agreement_id`, `service_period_id`."

    Design: Corner/endpoints/preference_rankings_must_name_this_solicitations_submitted_proposals
    """
    built = _two_solicitations(api)
    solicitation = built["first"]

    response = api.file_preferences(
        solicitation["id"],
        f.preference_filing_payload(
            solicitation["version"],
            f.ranking_entries(UNKNOWN_PROPOSAL_ID),
            rationale="names a proposal that does not exist",
        ),
        built["ref"].community_headers,
    )
    validate_error(response, E.ERR_PROPOSAL_NOT_FOUND, 404)

    unchanged = validate_success(api.get_solicitation(solicitation["id"], ADMIN))
    assert unchanged["preference_filing_count"] == 0
    assert unchanged["version"] == solicitation["version"]


def test_accepted_preference_filing_does_not_leak_across_solicitations(api: ApiClient):
    """The accepted filing writes one row and leaves the other round untouched.

    "It ranks exactly those proposals of the addressed solicitation whose `submission_state` is `SUBMITTED`, each of them once and only once, and the `rank` values it assigns must form the whole contiguous run of integers from 1 through the number of such proposals, with 1 meaning most preferred."

    Design: Corner/endpoints/preference_rankings_must_name_this_solicitations_submitted_proposals
    """
    built = _two_solicitations(api)
    solicitation = built["first"]
    submitted_here_id = built["submitted_here"]["id"]

    filed = validate_success(
        api.file_preferences(
            solicitation["id"],
            f.preference_filing_payload(
                solicitation["version"],
                f.ranking_entries(submitted_here_id),
                rationale="the one submitted proposal of this solicitation",
            ),
            built["ref"].community_headers,
        ),
        201,
    )
    assert filed["preference_filing_count"] == 1

    rows, meta = validate_paginated(
        api.list_solicitation_preferences(solicitation["id"], ADMIN)
    )
    assert meta["total_count"] == 1
    assert rows[0]["proposal_id"] == submitted_here_id

    ranked, ranked_meta = validate_paginated(
        api.list_proposal_preferences(submitted_here_id, ADMIN)
    )
    assert ranked_meta["total_count"] == 1
    assert ranked[0]["rank"] == 1
    assert ranked[0]["filing_sequence"] == 1

    _, foreign_meta = validate_paginated(
        api.list_proposal_preferences(built["submitted_there"]["id"], ADMIN)
    )
    assert foreign_meta["total_count"] == 0
    other_round = validate_success(api.get_solicitation(built["second"]["id"], ADMIN))
    assert other_round["preference_filing_count"] == 0


# ─── endpoints / aircraft_retirement_blocks_new_submissions_only ──────

def _retirement_setup(api: ApiClient):
    """An OPEN solicitation with one SUBMITTED and one DRAFT proposal on the
    same aircraft type, plus a second type that stays in service."""
    reference = fx.make_reference_data(
        api, clock=DEFAULT_CLOCK, with_second_carrier=False
    )
    other_type = validate_success(
        api.create_aircraft_type(f.jet_aircraft_type_payload(), ADMIN), 201
    )
    solicitation = fx.open_solicitation(api, reference.community_id)
    early = fx.submitted_proposal(
        api, solicitation["id"], reference.carrier_id, reference.aircraft_type_id
    )
    late = fx.draft_proposal(
        api,
        solicitation["id"],
        reference.carrier_id,
        reference.aircraft_type_id,
        service_level=SERVICE_LEVEL_ENHANCED,
        weekly_round_trips=13,
        annual_subsidy_request_usd=1700000.00,
    )
    return {
        "ref": reference,
        "other_type": other_type,
        "solicitation": solicitation,
        "early": early,
        "late": late,
    }


def test_retiring_an_aircraft_type_blocks_only_new_submissions(api: ApiClient):
    """Retirement stops the draft submission and leaves the earlier one alone.

    "The named aircraft type must not have been retired, or the refusal is `ERR_AIRCRAFT_TYPE_RETIRED`."

    Design: Corner/endpoints/aircraft_retirement_blocks_new_submissions_only
    """
    built = _retirement_setup(api)
    reference = built["ref"]
    retired_type_id = reference.aircraft_type_id

    retired = validate_success(
        api.retire_aircraft_type(
            retired_type_id,
            f.retire_payload(note="type withdrawn from the program fleet"),
            ADMIN,
        )
    )
    assert retired["is_retired"] is True
    still_flying = validate_success(
        api.get_aircraft_type(built["other_type"]["id"], ADMIN)
    )
    assert still_flying["is_retired"] is False

    # Retirement is a flag, not a deletion.
    readable = validate_success(api.get_aircraft_type(retired_type_id, ADMIN))
    assert readable["code"] == "B190"
    assert readable["seats"] == 19

    refused = api.proposal_action(
        built["late"]["id"],
        f.proposal_action_payload(PROPOSAL_SUBMIT),
        reference.carrier_headers,
    )
    validate_error(refused, E.ERR_AIRCRAFT_TYPE_RETIRED, 422)

    assert _proposal(api, built["late"]["id"])["submission_state"] == PROPOSAL_DRAFT
    assert _proposal(api, built["early"]["id"])["submission_state"] == PROPOSAL_SUBMITTED


def test_award_proceeds_on_a_proposal_submitted_before_retirement(api: ApiClient):
    """A proposal submitted before the retirement still wins the award.

    "When a type leaves the program's approved list, an administrator retires it — optionally recording a `note` — which sets `is_retired` to true and bars the type from backing any further proposal submission."

    Design: Corner/endpoints/aircraft_retirement_blocks_new_submissions_only
    """
    built = _retirement_setup(api)
    reference = built["ref"]
    retired_type_id = reference.aircraft_type_id
    solicitation_id = built["solicitation"]["id"]

    validate_success(
        api.retire_aircraft_type(
            retired_type_id,
            f.retire_payload(note="type withdrawn from the program fleet"),
            ADMIN,
        )
    )
    fx.close_solicitation(api, solicitation_id)

    agreement = validate_success(
        api.create_selection_order(
            solicitation_id,
            f.selection_order_payload(
                order_note="award on the pre-retirement submission"
            ),
            OFFICER,
        ),
        201,
    )
    assert agreement["proposal_id"] == built["early"]["id"]

    awarded = validate_success(api.get_solicitation(solicitation_id, ADMIN))
    assert awarded["status"] == SOLICITATION_AWARDED
    assert awarded["candidate_count_at_award"] == 1

    # The agreement still reaches the retired type through its source proposal.
    source = _proposal(api, agreement["proposal_id"])
    assert source["aircraft_type_id"] == retired_type_id
    assert validate_success(api.get_aircraft_type(retired_type_id, ADMIN))["is_retired"] is True
