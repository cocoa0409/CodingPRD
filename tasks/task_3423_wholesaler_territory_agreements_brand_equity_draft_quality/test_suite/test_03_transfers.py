"""Transfer applications: qualification, ROFR windows, decisions, sweeps,
and the consummation cascade."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_instant_equals,
    create_transfer_payload,
    get_assignment,
    get_success_data,
    make_agreement,
    make_event,
    make_territory,
    make_transfer,
    make_wholesaler,
    qualification_review,
    request_allocation,
    setup_awarded_territory,
    setup_locked_event_single_requester,
    setup_qualified_transfer,
    validate_error,
    validate_paginated,
    validate_success,
    make_wholesaler_headers,
)

ADMIN = TEST_USERS["admin_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


class TestQualificationThreshold:
    def test_successor_qualification_threshold_70_inclusive(self, api):
        """PRD §3.3: "A score of at least 70.00 qualifies the buyer, and the
        threshold is inclusive, so exactly 70.00 qualifies"
        PRD §3.3: "A score below 70.00 moves the application `SUBMITTED` →
        `REJECTED`, a terminal state, with the computed score still stored."

        Design: Corner/calculations/successor_qualification_threshold_70_inclusive
        """
        env70 = setup_qualified_transfer(rofr=False, buyer_scores=70)
        env69 = setup_qualified_transfer(rofr=False, buyer_scores=69)

        t70 = env70["transfer"]
        assert t70["qualification_score"] == pytest.approx(70.00, abs=1e-9)
        assert t70["status"] == "QUALIFIED"
        assert t70["rofr_deadline"] is None

        t69 = env69["transfer"]
        assert t69["qualification_score"] == pytest.approx(69.00, abs=1e-9)
        assert t69["status"] == "REJECTED"
        assert t69["rofr_deadline"] is None


class TestTerminalLockdown:
    def test_decision_on_rejected_transfer_returns_409(self, api):
        """PRD §3.3: "A score below 70.00 moves the application `SUBMITTED` →
        `REJECTED`, a terminal state, with the computed score still stored."
        PRD §2.10: "the target resource sits in a state from which the
        requested transition exists, terminal-state lockdown included"

        Design: Corner/state_machines/decision_on_rejected_transfer_returns_409
        """
        env = setup_qualified_transfer(rofr=False, buyer_scores=50)
        transfer = env["transfer"]
        assert transfer["status"] == "REJECTED"
        assert transfer["qualification_score"] == pytest.approx(50.00, abs=1e-9)

        resp = api.transfer_decision(transfer["id"], {"decision": "APPROVE"},
                                     COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestPendingUniqueness:
    def test_second_pending_transfer_rejected(self, api, admin_headers):
        """PRD §3.3: "only one application per agreement may be in flight: when
        another application for the same agreement sits in `SUBMITTED`,
        `QUALIFIED`, `ROFR_OPEN`, `ROFR_EXERCISED`, `ROFR_WAIVED`,
        `ROFR_LAPSED`, or `APPROVED`, the new one is rejected with
        `ERR_TRANSFER_ALREADY_PENDING`."

        Design: Corner/validations/second_pending_transfer_rejected
        """
        territory, seller, agreement = setup_awarded_territory(
            territory_name="Pending Territory",
            wholesaler_overrides={"financial_capacity_score": 70,
                                  "warehouse_capacity_score": 70,
                                  "market_coverage_score": 70})
        buyer_a = make_wholesaler(legal_name="Pending Buyer A",
                                  financial_capacity_score=80,
                                  warehouse_capacity_score=80,
                                  market_coverage_score=80)
        buyer_b = make_wholesaler(legal_name="Pending Buyer B",
                                  financial_capacity_score=81,
                                  warehouse_capacity_score=81,
                                  market_coverage_score=81)
        first = make_transfer(agreement["id"], seller["id"], buyer_a["id"])
        assert first["status"] == "SUBMITTED"

        resp = api.create_transfer(
            create_transfer_payload(agreement["id"], buyer_b["id"],
                                    purchase_price_cents=1_100_000),
            make_wholesaler_headers(seller["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TRANSFER_ALREADY_PENDING)

        listed, _meta = _list_transfers(api, agreement["id"], admin_headers)
        assert len(listed) == 1


class TestRofrWindowGate:
    def test_decision_during_open_rofr_window_rejected(self, api, admin_headers):
        """PRD §3.4: "One state is explicitly out of bounds: deciding while the
        ROFR window is still unresolved — the application sits in `ROFR_OPEN` —
        is never permitted, and the attempt is rejected with
        `ERR_ROFR_WINDOW_OPEN`."

        Design: Corner/validations/decision_during_open_rofr_window_rejected
        """
        env = setup_qualified_transfer(rofr=True, buyer_scores=80)
        transfer = env["transfer"]
        assert transfer["status"] == "ROFR_OPEN"

        resp = api.transfer_decision(transfer["id"], {"decision": "APPROVE"},
                                     COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_ROFR_WINDOW_OPEN)

        listed, _meta = _list_transfers(api, env["agreement"]["id"], admin_headers)
        assert listed[0]["status"] == "ROFR_OPEN"


class TestClockSweeps:
    def test_rofr_window_lapses_via_clock_sweep(self, api, admin_headers):
        """PRD §2.5: "Right-of-first-refusal windows whose deadline has passed
        lapse: a transfer application sitting in `ROFR_OPEN` whose
        `rofr_deadline` is strictly before the new clock moves to
        `ROFR_LAPSED`."
        PRD §3.4: "`successor_wholesaler_id` becomes the agreement's ROFR
        holder when the application arrived via `ROFR_EXERCISED`, and the
        `buyer_wholesaler_id` when it arrived from `QUALIFIED`, `ROFR_WAIVED`,
        or `ROFR_LAPSED`; the `consummation_deadline` is set to the logical
        clock plus 60 days."

        Design: Corner/state_machines/rofr_window_lapses_via_clock_sweep
        """
        env = setup_qualified_transfer(rofr=True, buyer_scores=80)
        transfer = env["transfer"]
        assert_instant_equals(transfer["rofr_deadline"], "2026-10-01T00:00:00Z",
                              label="rofr_deadline")

        sweep = validate_success(
            api.set_clock({"to_iso8601": "2026-10-02T00:00:00Z"}, ADMIN), 200
        )
        assert sweep["rofr_lapsed_count"] == 1

        listed, _meta = _list_transfers(api, env["agreement"]["id"], admin_headers)
        assert listed[0]["status"] == "ROFR_LAPSED"

        decided = validate_success(
            api.transfer_decision(transfer["id"], {"decision": "APPROVE"},
                                  COMPLIANCE)
        )
        assert decided["status"] == "APPROVED"
        assert decided["successor_wholesaler_id"] == env["buyer"]["id"], (
            "the lapsed ROFR confers nothing — the buyer stays successor"
        )
        assert_instant_equals(decided["consummation_deadline"],
                              "2026-12-01T00:00:00Z",
                              label="consummation_deadline")

    def test_approved_transfer_expires_via_clock_sweep(self, api, admin_headers):
        """PRD §2.5: "Approved transfers whose consummation window has run out
        expire: an application in `APPROVED` whose `consummation_deadline` is
        strictly before the new clock moves to `EXPIRED`."
        PRD §3.4: "If the clock passes the consummation deadline first, the
        sweep expires the application — `APPROVED` → `EXPIRED` — and
        consummation is no longer possible; a late attempt fails the state tier
        with `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/approved_transfer_expires_via_clock_sweep
        """
        env = setup_qualified_transfer(rofr=False, buyer_scores=80)
        transfer = env["transfer"]
        approved = validate_success(
            api.transfer_decision(transfer["id"], {"decision": "APPROVE"},
                                  COMPLIANCE)
        )
        assert_instant_equals(approved["consummation_deadline"],
                              "2026-10-31T00:00:00Z",
                              label="consummation_deadline")

        sweep = validate_success(
            api.set_clock({"to_iso8601": "2026-11-01T00:00:00Z"}, ADMIN), 200
        )
        assert sweep["consummation_expired_count"] == 1

        resp = api.consummate_transfer(transfer["id"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        territory_id = env["agreement"]["territory_id"]
        terr = validate_success(api.get_territory(territory_id, admin_headers))
        assert terr["incumbent_wholesaler_id"] == env["seller"]["id"], (
            "the expired transfer changed nothing"
        )
        agreement = validate_success(
            api.get_agreement(env["agreement"]["id"], admin_headers)
        )
        assert agreement["status"] == "ACTIVE"


@pytest.fixture
def rofr_branches(api):
    """Two transfers with ROFR holders: branch E exercised, branch W waived,
    both approved and consummated at the startup clock."""
    out = {}
    for key, tname in (("e", "Branch E Territory"), ("w", "Branch W Territory")):
        territory = make_territory(name=tname)
        seller = make_wholesaler(legal_name=f"Seller {key.upper()}",
                                 financial_capacity_score=60,
                                 warehouse_capacity_score=60,
                                 market_coverage_score=60)
        holder = make_wholesaler(legal_name=f"Holder {key.upper()}", tier="GOLD",
                                 financial_capacity_score=85,
                                 warehouse_capacity_score=85,
                                 market_coverage_score=85)
        buyer = make_wholesaler(legal_name=f"Buyer {key.upper()}", tier="BRONZE",
                                financial_capacity_score=80,
                                warehouse_capacity_score=80,
                                market_coverage_score=80)
        agreement = make_agreement(territory["id"], seller["id"],
                                   rofr_holder_wholesaler_id=holder["id"])
        transfer = make_transfer(agreement["id"], seller["id"], buyer["id"],
                                 purchase_price_cents=5_000_000)
        reviewed = qualification_review(transfer["id"])
        out[key] = {"territory": territory, "seller": seller, "holder": holder,
                    "buyer": buyer, "agreement": agreement, "transfer": reviewed}

    api.rofr_response(out["e"]["transfer"]["id"], {"decision": "EXERCISE"},
                      make_wholesaler_headers(out["e"]["holder"]["id"]))
    api.rofr_response(out["w"]["transfer"]["id"], {"decision": "WAIVE"},
                      make_wholesaler_headers(out["w"]["holder"]["id"]))
    for key in ("e", "w"):
        decided = api.transfer_decision(out[key]["transfer"]["id"],
                                        {"decision": "APPROVE"}, COMPLIANCE)
        if decided.status_code != 200:
            raise AssertionError(f"Setup failed at decision: {decided.text[:300]}")
        out[key]["approved"] = get_success_data(decided)
        consummated = api.consummate_transfer(out[key]["transfer"]["id"], ADMIN)
        if consummated.status_code != 200:
            raise AssertionError(
                f"Setup failed at consummate: {consummated.text[:300]}"
            )
        out[key]["consummated"] = get_success_data(consummated)
    return out


class TestRofrBranchDivergence:
    def test_rofr_exercised_branch_installs_holder_as_successor(
        self, api, rofr_branches
    ):
        """PRD §3.4: "`successor_wholesaler_id` becomes the agreement's ROFR
        holder when the application arrived via `ROFR_EXERCISED`, and the
        `buyer_wholesaler_id` when it arrived from `QUALIFIED`, `ROFR_WAIVED`,
        or `ROFR_LAPSED`; the `consummation_deadline` is set to the logical
        clock plus 60 days."
        PRD §3.4: "The territory of that agreement stays `AWARDED`, but its
        `incumbent_wholesaler_id` is swapped to the `successor_wholesaler_id`."

        Design: Difficulty/non_linear_state_machine/transfer_rofr_branch_divergence
        """
        branch = rofr_branches["e"]
        transfer = branch["transfer"]
        assert transfer["qualification_score"] == pytest.approx(80.00, abs=1e-9)
        assert_instant_equals(transfer["rofr_deadline"], "2026-10-01T00:00:00Z",
                              label="rofr_deadline")

        consummated = branch["consummated"]
        assert consummated["status"] == "CONSUMMATED"
        assert consummated["successor_wholesaler_id"] == branch["holder"]["id"], (
            "exercise overrides the buyer"
        )
        assert_instant_equals(consummated["consummation_deadline"],
                              "2026-10-31T00:00:00Z",
                              label="consummation_deadline")

        terr = validate_success(api.get_territory(branch["territory"]["id"], ADMIN))
        assert terr["incumbent_wholesaler_id"] == branch["holder"]["id"]
        assert terr["status"] == "AWARDED"

        old = validate_success(api.get_agreement(branch["agreement"]["id"], ADMIN))
        assert old["status"] == "TERMINATED"

        holder_agreements, _ = _list_w_agreements(api, branch["holder"]["id"])
        assert len(holder_agreements) == 1
        succ = holder_agreements[0]
        assert succ["status"] == "ACTIVE"
        assert succ["version"] == 1
        assert succ["rofr_holder_wholesaler_id"] is None
        assert succ["territory_id"] == branch["territory"]["id"]
        assert succ["brand_scope"] == branch["agreement"]["brand_scope"]

    def test_rofr_waived_branch_preserves_buyer_as_successor(
        self, api, rofr_branches
    ):
        """PRD §3.4: "`successor_wholesaler_id` becomes the agreement's ROFR
        holder when the application arrived via `ROFR_EXERCISED`, and the
        `buyer_wholesaler_id` when it arrived from `QUALIFIED`, `ROFR_WAIVED`,
        or `ROFR_LAPSED`; the `consummation_deadline` is set to the logical
        clock plus 60 days."
        PRD §3.4: "The referenced agreement moves `ACTIVE` → `TERMINATED`."

        Design: Difficulty/non_linear_state_machine/transfer_rofr_branch_divergence
        """
        branch = rofr_branches["w"]
        consummated = branch["consummated"]
        assert consummated["status"] == "CONSUMMATED"
        assert consummated["successor_wholesaler_id"] == branch["buyer"]["id"], (
            "waiver preserves the buyer"
        )

        terr = validate_success(api.get_territory(branch["territory"]["id"], ADMIN))
        assert terr["incumbent_wholesaler_id"] == branch["buyer"]["id"]

        old = validate_success(api.get_agreement(branch["agreement"]["id"], ADMIN))
        assert old["status"] == "TERMINATED"

        buyer_agreements, _ = _list_w_agreements(api, branch["buyer"]["id"])
        assert len(buyer_agreements) == 1
        succ = buyer_agreements[0]
        assert succ["status"] == "ACTIVE"
        assert succ["version"] == 1
        assert succ["rofr_holder_wholesaler_id"] is None

        buyer = validate_success(api.get_wholesaler(branch["buyer"]["id"], ADMIN))
        assert buyer["status"] == "APPOINTED", (
            "first ACTIVE agreement promotes the successor APPLICANT -> APPOINTED"
        )


@pytest.fixture
def consummated_seller_cascade(api):
    """Seller with one BUD-LTD agreement and a PENDING allocation assignment;
    transfer qualified + approved, then consummated."""
    territory, seller, agreement = setup_awarded_territory(
        territory_name="Sale Territory",
        wholesaler_overrides={"tier": "BRONZE", "financial_capacity_score": 60,
                              "warehouse_capacity_score": 60,
                              "market_coverage_score": 60},
        agreement_overrides={"brand_scope": ["BUD-LTD"]},
    )
    buyer = make_wholesaler(legal_name="Buying Distributing",
                            financial_capacity_score=80,
                            warehouse_capacity_score=80,
                            market_coverage_score=80)
    event = make_event(brand_code="BUD-LTD", total_qty_cases=100)
    resp = request_allocation(event["id"], seller["id"], 300)
    if resp.status_code != 201:
        raise AssertionError(f"Setup failed at request: {resp.text[:300]}")
    locked = api.lock_event(event["id"], ADMIN)
    if locked.status_code != 200:
        raise AssertionError(f"Setup failed at lock: {locked.text[:300]}")
    event = get_success_data(locked)

    transfer = make_transfer(agreement["id"], seller["id"], buyer["id"],
                             purchase_price_cents=7_500_000)
    qualification_review(transfer["id"])
    decided = api.transfer_decision(transfer["id"], {"decision": "APPROVE"},
                                    COMPLIANCE)
    if decided.status_code != 200:
        raise AssertionError(f"Setup failed at decision: {decided.text[:300]}")
    consummated = api.consummate_transfer(transfer["id"], ADMIN)
    if consummated.status_code != 200:
        raise AssertionError(f"Setup failed at consummate: {consummated.text[:300]}")
    return {
        "territory": territory, "seller": seller, "buyer": buyer,
        "agreement": agreement, "event": event,
        "transfer": get_success_data(consummated),
    }


class TestConsummationCascadeTerminatesSeller:
    def test_consummation_terminates_agreement_and_seller(
        self, api, consummated_seller_cascade
    ):
        """PRD §3.4: "The referenced agreement moves `ACTIVE` → `TERMINATED`."
        PRD §3.4: "The seller is re-evaluated: when it now holds zero remaining
        `ACTIVE` agreements, it moves `APPOINTED` → `TERMINATED`, and every
        `PENDING` allocation assignment naming the seller is released —
        `pending_qty` decreases and `released_qty` increases by each released
        assignment's `assigned_qty` (§3.5)."

        Design: Difficulty/transitive_cascade/consummation_cascade_terminates_seller
        """
        env = consummated_seller_cascade
        assert env["transfer"]["status"] == "CONSUMMATED"
        assert env["transfer"]["successor_wholesaler_id"] == env["buyer"]["id"]

        agreement = validate_success(api.get_agreement(env["agreement"]["id"], ADMIN))
        assert agreement["status"] == "TERMINATED"

        seller = validate_success(api.get_wholesaler(env["seller"]["id"], ADMIN))
        assert seller["status"] == "TERMINATED"

        event = validate_success(api.get_allocation_event(env["event"]["id"], ADMIN))
        assignment = get_assignment(event, env["seller"]["id"])
        assert assignment["status"] == "RELEASED"
        assert event["released_qty"] == 40
        assert event["pending_qty"] == 0
        assert event["unassigned_remainder"] == 60

    def test_consummation_installs_successor_agreement(
        self, api, consummated_seller_cascade
    ):
        """PRD §3.4: "A brand-new agreement is created for the territory and
        the successor, copying the old agreement's `brand_scope`,
        `weighting_profile`, all three performance targets, all three declared
        metrics, and `term_years`; it carries no ROFR holder
        (`rofr_holder_wholesaler_id` null) and is born `ACTIVE` at `version`
        1."
        PRD §3.4: "When this new agreement is the successor's first `ACTIVE`
        agreement, the successor moves `APPLICANT` → `APPOINTED`."

        Design: Difficulty/transitive_cascade/consummation_cascade_terminates_seller
        """
        env = consummated_seller_cascade
        terr = validate_success(api.get_territory(env["territory"]["id"], ADMIN))
        assert terr["incumbent_wholesaler_id"] == env["buyer"]["id"]
        assert terr["status"] == "AWARDED"

        succ_agreements, _ = _list_w_agreements(api, env["buyer"]["id"])
        assert len(succ_agreements) == 1
        succ = succ_agreements[0]
        assert succ["wholesaler_id"] == env["buyer"]["id"]
        assert succ["territory_id"] == env["territory"]["id"]
        assert succ["status"] == "ACTIVE"
        assert succ["version"] == 1
        assert succ["rofr_holder_wholesaler_id"] is None
        assert succ["brand_scope"] == ["BUD-LTD"]

        buyer = validate_success(api.get_wholesaler(env["buyer"]["id"], ADMIN))
        assert buyer["status"] == "APPOINTED"


@pytest.fixture
def safety_vs_pending(api):
    """Seller with a pending clean transfer; a retail-tainted second buyer."""
    territory, seller, agreement = setup_awarded_territory(
        territory_name="Safety Territory",
        wholesaler_overrides={"financial_capacity_score": 70,
                              "warehouse_capacity_score": 70,
                              "market_coverage_score": 70})
    clean_buyer = make_wholesaler(legal_name="Clean Buyer", tier="BRONZE",
                                  financial_capacity_score=80,
                                  warehouse_capacity_score=80,
                                  market_coverage_score=80)
    tainted_buyer = make_wholesaler(legal_name="Retail-Tainted Buyer",
                                    tier="BRONZE", holds_retail_interest=True,
                                    financial_capacity_score=90,
                                    warehouse_capacity_score=90,
                                    market_coverage_score=90)
    first = make_transfer(agreement["id"], seller["id"], clean_buyer["id"],
                          purchase_price_cents=3_000_000)
    return {"territory": territory, "seller": seller, "agreement": agreement,
            "clean_buyer": clean_buyer, "tainted_buyer": tainted_buyer,
            "first": first}


class TestSafetyBeatsPending:
    def test_transfer_create_safety_beats_pending_constraint(
        self, api, safety_vs_pending, admin_headers
    ):
        """PRD §2.10: "Likewise, a transfer application that names a
        retail-interest buyer for an agreement already carrying a pending
        transfer reports `ERR_THREE_TIER_PROHIBITION`, because the three-tier
        tier is evaluated before the uniqueness tier."

        Design: Difficulty/priority_pair_validation_conflict/transfer_create_safety_beats_pending_constraint
        """
        env = safety_vs_pending
        assert env["first"]["status"] == "SUBMITTED"

        resp = api.create_transfer(
            create_transfer_payload(env["agreement"]["id"],
                                    env["tainted_buyer"]["id"],
                                    purchase_price_cents=3_500_000),
            make_wholesaler_headers(env["seller"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_THREE_TIER_PROHIBITION)

        listed, _meta = _list_transfers(api, env["agreement"]["id"], admin_headers)
        assert len(listed) == 1, "the rejected transfer left no residue"
        assert listed[0]["status"] == "SUBMITTED"

    def test_transfer_create_retail_interest_buyer_rejected_in_isolation(
        self, api, safety_vs_pending
    ):
        """PRD §2.8: "A wholesaler holding any retail-tier ownership interest
        may not acquire a distributorship. Naming a buyer whose
        `holds_retail_interest` flag is true on a transfer application is
        rejected with `ERR_THREE_TIER_PROHIBITION` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/transfer_create_safety_beats_pending_constraint
        """
        # A fresh agreement with no pending transfer: the safety tier alone.
        territory, seller, agreement = setup_awarded_territory(
            territory_name="Isolation Territory",
            wholesaler_overrides={"financial_capacity_score": 70,
                                  "warehouse_capacity_score": 70,
                                  "market_coverage_score": 70})
        tainted = make_wholesaler(legal_name="Tainted Solo Buyer",
                                  holds_retail_interest=True,
                                  financial_capacity_score=90,
                                  warehouse_capacity_score=90,
                                  market_coverage_score=90)
        resp = api.create_transfer(
            create_transfer_payload(agreement["id"], tainted["id"]),
            make_wholesaler_headers(seller["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_THREE_TIER_PROHIBITION)


# --- local listing helpers ------------------------------------------------------

def _list_transfers(api, agreement_id, headers):
    return validate_paginated(api.list_agreement_transfers(agreement_id, headers))


def _list_w_agreements(api, wholesaler_id):
    return validate_paginated(api.list_wholesaler_agreements(wholesaler_id, ADMIN))
