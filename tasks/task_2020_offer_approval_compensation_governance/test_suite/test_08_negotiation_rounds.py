"""Negotiation rounds: limits, concession authority, round lifecycle."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_open_requisition, create_candidate_recruited, create_standard_peers,
    create_peer_snapshots, create_extended_offer, record_rejected_round,
    setup_exception_policy_rows, approve_chain, submit_offer_and_get_steps,
    create_draft_offer,
)

HM = TEST_USERS["hm_headers"]
REC = TEST_USERS["recruiter_headers"]
ADMIN = TEST_USERS["hr_admin_headers"]


def _extended_offer(api, base_cents=20000000, budget=50000000, headcount=1, peers=(19000000, 19500000, 20000000), title="Sr Eng"):
    req = create_open_requisition(HM, title=title, annual_budget_cents=budget, headcount_authorized=headcount)
    create_standard_peers(base_list=peers)
    cand = create_candidate_recruited(REC)
    offer = create_extended_offer(req, cand, REC, base_cents=base_cents)
    return req, cand, offer


def _offer_version(api, offer_id):
    return get_success_data(api.get_offer(offer_id, REC))["version"]


def _create_round(api, offer_id, proposed_base):
    return api.create_negotiation_round(
        offer_id, {"expected_offer_version": _offer_version(api, offer_id), "proposed_base_cents": proposed_base}, REC
    )


def _drive_to_three_rejected_rounds(api, offer_id, proposed=20500000):
    for _ in range(3):
        rnd = get_success_data(_create_round(api, offer_id, proposed))
        get_success_data(api.decide_negotiation_round(rnd["id"], {"outcome": "REJECTED"}, REC))


def test_negotiation_round_count_exhaustion_blocks_fourth(api):
    """PRD §3.7: "the offer's `round_count` — the number of rounds ever created
    for it, in any status — must be below three, else
    `ERR_NEGOTIATION_ROUND_LIMIT`".

    Design: Difficulty/boundary_precision_check/negotiation_round_count_exhaustion
    """
    req, cand, offer = _extended_offer(api)
    _drive_to_three_rejected_rounds(api, offer["id"], proposed=20400000)
    current = validate_success(api.get_offer(offer["id"], REC))
    assert current["round_count"] == 3
    # 4th round rejected even with an in-cap proposed base
    resp = api.create_negotiation_round(
        offer["id"],
        {"expected_offer_version": current["version"], "proposed_base_cents": 21000000},
        REC,
    )
    validate_error(resp, ApiErrorId.ERR_NEGOTIATION_ROUND_LIMIT)
    after = validate_success(api.get_offer(offer["id"], REC))
    assert after["status"] == "EXTENDED"


def test_negotiation_rounds_one_through_three_succeed(api):
    """PRD §3.7: "A recorded round takes `sequence` equal to `round_count` plus
    one, starts `PROPOSED`, moves the offer `EXTENDED → COUNTERED`, increments
    the offer's `version` by one, and appends `COUNTER_RECORDED`." Rounds 1-3
    are below the limit and must be recordable.

    Design: Difficulty/boundary_precision_check/negotiation_round_count_exhaustion
    """
    req, cand, offer = _extended_offer(api)
    for expected_seq in (1, 2, 3):
        rnd = validate_success(_create_round(api, offer["id"], 20400000), expected_status=201)
        assert rnd["sequence"] == expected_seq
        assert rnd["status"] == "PROPOSED"
        mid = validate_success(api.get_offer(offer["id"], REC))
        assert mid["status"] == "COUNTERED"
        validate_success(api.decide_negotiation_round(rnd["id"], {"outcome": "REJECTED"}, REC))
        back = validate_success(api.get_offer(offer["id"], REC))
        assert back["status"] == "EXTENDED"
        assert back["round_count"] == expected_seq


def test_round_limit_beats_proposed_base_hard_cap(api):
    """PRD §2.10: "Business constraints — negotiation round limit ..." is tier
    10 while "Fiscal gates, last: ... the base hard cap
    (`ERR_BASE_EXCEEDS_HARD_CAP`)" is tier 12; "a request that would fail
    several checks surfaces the error from the earliest tier it fails".

    Design: Difficulty/priority_pair_validation_conflict/round_limit_beats_proposed_base_hard_cap
    """
    req, cand, offer = _extended_offer(api)
    _drive_to_three_rejected_rounds(api, offer["id"])
    current = validate_success(api.get_offer(offer["id"], REC))
    assert current["round_count"] == 3
    # 27000000 > 21000000 * 1.25 = 26250000: also breaches the fiscal hard cap,
    # but the round-limit (tier 10) error must surface first.
    resp = api.create_negotiation_round(
        offer["id"],
        {"expected_offer_version": current["version"], "proposed_base_cents": 27000000},
        REC,
    )
    validate_error(resp, ApiErrorId.ERR_NEGOTIATION_ROUND_LIMIT)


def test_round_limit_rejection_creates_no_round_row(api):
    """PRD §3.7: "the offer's `round_count` — the number of rounds ever created
    for it, in any status — must be below three, else
    `ERR_NEGOTIATION_ROUND_LIMIT`" — a rejected creation adds no round row and
    leaves the offer EXTENDED.

    Design: Difficulty/priority_pair_validation_conflict/round_limit_beats_proposed_base_hard_cap
    """
    req, cand, offer = _extended_offer(api)
    _drive_to_three_rejected_rounds(api, offer["id"])
    current = validate_success(api.get_offer(offer["id"], REC))
    resp = api.create_negotiation_round(
        offer["id"],
        {"expected_offer_version": current["version"], "proposed_base_cents": 27000000},
        REC,
    )
    validate_error(resp, ApiErrorId.ERR_NEGOTIATION_ROUND_LIMIT)
    rounds = validate_success(api.list_negotiation_rounds(offer["id"], REC))
    assert len(rounds) == 3
    after = validate_success(api.get_offer(offer["id"], REC))
    assert after["status"] == "EXTENDED"
    assert after["round_count"] == 3


def test_concession_cap_boundary_inclusive_for_recruiter(api):
    """PRD §3.7: "Formally, the ceiling is the anchor plus the product of the
    anchor and the cap, that product rounded half up to whole cents before the
    addition, and a proposal exactly at the ceiling is permitted; anything above
    is rejected with `ERR_CONCESSION_EXCEEDS_AUTHORITY`."

    Design: Corner/calculations/concession_cap_boundary_inclusive
    """
    req, cand, offer = _extended_offer(api, budget=80000000, headcount=2,
                                       peers=(19000000, 20000000, 21500000))
    # anchor 20000000; Recruiter cap 5% -> ceiling 21000000 exactly
    rnd = get_success_data(_create_round(api, offer["id"], 21000000))
    decided = validate_success(api.decide_negotiation_round(rnd["id"], {"outcome": "ACCEPTED"}, REC))
    assert decided["status"] == "ACCEPTED"
    after = validate_success(api.get_offer(offer["id"], REC))
    assert after["base_cents"] == 21000000
    assert after["band"] == "IN_BAND"
    # recomputed chain [HiringManager] is a subset of the approved [HiringManager]
    assert after["status"] == "APPROVED"


def test_concession_one_cent_over_recruiter_cap_rejected_but_hm_succeeds(api):
    """PRD §3.7: "The proposed base may not exceed the anchor by more than the
    actor's cap: five percent for a `Recruiter`, ten percent for a
    `HiringManager`, one hundred percent for a `VPPeople`." and "anything above
    is rejected with `ERR_CONCESSION_EXCEEDS_AUTHORITY`."

    Design: Corner/calculations/concession_cap_boundary_inclusive
    """
    req, cand, offer = _extended_offer(api, budget=80000000, headcount=2,
                                       peers=(19000000, 20000000, 21500000))
    # 21000100 is one cent over the Recruiter 5% ceiling (21000000) but within HM's 10% (22000000)
    rnd = get_success_data(_create_round(api, offer["id"], 21000100))
    resp = api.decide_negotiation_round(rnd["id"], {"outcome": "ACCEPTED"}, REC)
    validate_error(resp, ApiErrorId.ERR_CONCESSION_EXCEEDS_AUTHORITY)
    round_after = [r for r in validate_success(api.list_negotiation_rounds(offer["id"], REC))
                   if r["id"] == rnd["id"]][0]
    assert round_after["status"] == "PROPOSED"
    offer_mid = validate_success(api.get_offer(offer["id"], REC))
    assert offer_mid["status"] == "COUNTERED"
    decided = validate_success(api.decide_negotiation_round(rnd["id"], {"outcome": "ACCEPTED"}, HM))
    assert decided["status"] == "ACCEPTED"
    after = validate_success(api.get_offer(offer["id"], REC))
    assert after["base_cents"] == 21000100
    assert after["band"] == "ABOVE_BAND"
    # new chain: policy-free [HiringManager] + band-severity escalation is policy-driven only;
    # with no policy rows and neutral flags the recomputed chain stays [HiringManager] — subset holds
    assert after["status"] == "APPROVED"


def test_round_decide_twice_returns_round_not_pending(api):
    """PRD §3.7: "deciding a round no longer `PROPOSED` fails with
    `ERR_ROUND_NOT_PENDING`."

    Design: Corner/validations/round_decide_twice_returns_round_not_pending
    """
    req, cand, offer = _extended_offer(api)
    rnd = get_success_data(_create_round(api, offer["id"], 20500000))
    validate_success(api.decide_negotiation_round(rnd["id"], {"outcome": "REJECTED"}, REC))
    resp = api.decide_negotiation_round(rnd["id"], {"outcome": "ACCEPTED"}, TEST_USERS["vp_headers"])
    validate_error(resp, ApiErrorId.ERR_ROUND_NOT_PENDING)
    after = validate_success(api.get_offer(offer["id"], REC))
    assert after["status"] == "EXTENDED"
    assert after["base_cents"] == 20000000


def test_accept_from_countered_withdraws_round(api):
    """PRD §3.6: "Acceptance is also possible from `COUNTERED`: the candidate
    takes the originally extended terms, the pending round is abandoned to
    `WITHDRAWN` with a `ROUND_WITHDRAWN` event, and the same `ACCEPTED` landing
    follows."

    Design: Corner/state_machines/accept_from_countered_withdraws_round
    """
    from test_helpers import make_candidate_headers, event_types
    req, cand, offer = _extended_offer(api)
    rnd = get_success_data(_create_round(api, offer["id"], 20500000))
    accepted = validate_success(api.accept_offer(offer["id"], make_candidate_headers(cand["id"])))
    assert accepted["status"] == "ACCEPTED"
    assert accepted["base_cents"] == 20000000
    rounds = validate_success(api.list_negotiation_rounds(offer["id"], REC))
    assert rounds[0]["status"] == "WITHDRAWN"
    types = event_types(validate_success(api.list_offer_events(offer["id"], REC)))
    assert "ROUND_WITHDRAWN" in types
    assert types.index("ROUND_WITHDRAWN") < types.index("ACCEPTED")
