"""Contract repricing, price-basis determination, and window overlap."""
from test_helpers import (
    ApiErrorId,
    adjudicate,
    advance_episode_days,
    drive_episode_to_post_op,
    drive_episode_to_sor_pending,
    get_episode,
    get_success_data,
    make_active_contract,
    make_contract,
    make_employer,
    make_patient,
    make_template,
    open_episode,
    setup_episode_in_post_op,
    setup_program,
    submit_claim,
    validate_error,
    validate_success,
)

ADMIN = {"X-User-ID": "test-program-admin-1", "X-User-Role": "ProgramAdmin"}
COORD = {"X-User-ID": "test-care-coordinator-1", "X-User-Role": "CareCoordinator"}
REVIEWER = {"X-User-ID": "test-physician-reviewer-1", "X-User-Role": "PhysicianReviewer"}

NEW_COMPONENTS = {
    "facility": 2600000, "professional": 300000, "implant": 200000, "anesthesia": 100000,
}


def _reprice(contract_id: str, version: int, price: int, components: dict) -> dict:
    from test_helpers import api_client
    return validate_success(
        api_client.reprice_contract(
            contract_id,
            {"expected_contract_version": version,
             "new_bundle_price_cents": price,
             "new_rate_components": components},
            ADMIN,
        )
    )


def test_bundle_case_payable_locked_vs_repriced_basis(api):
    """PRD §3.7: "the payable is the episode's `applied_bundle_price_cents`
    plus the outlier payable. Because the applied basis comes from the
    approval-time price determination, a `LOCKED` episode pays against the
    original price snapshot while a `REPRICED` episode pays against the latest
    amendment, and changing the basis changes the payable for the same billed
    amount."
    PRD §3.4: "if the gap between the episode's `screen_seq` at approval and
    the latest amendment's `effective_from_seq` is at least 30 days — a gap of
    exactly 30 qualifies — the episode is `REPRICED` onto the latest
    amendment's price and components"

    Design: Difficulty/dual_variant_calc/bundle_case_payable_locked_vs_repriced_basis
    """
    prog = setup_program()
    contract = prog["contract"]
    patient_a = make_patient(prog["employer"])
    patient_b = make_patient(prog["employer"])
    ep_a = drive_episode_to_sor_pending(open_episode(patient_a, contract))
    ep_b = drive_episode_to_sor_pending(open_episode(patient_b, contract))

    refreshed = get_success_data(api.get_contract(contract["id"], ADMIN))
    _reprice(contract["id"], refreshed["version"], 3200000, NEW_COMPONENTS)

    # Episode A approves on the very next day after the amendment (PRD §3.4:
    # the approval stamps the post-increment screen_seq), so its gap is 1 —
    # far under 30 — and it locks the original price schedule.
    validate_success(
        api.record_review(
            ep_a["id"],
            {"conclusion": "SURGERY_INDICATED",
             "expected_episode_version": ep_a["version"]},
            REVIEWER,
        ),
        expected_status=201,
    )
    ep_a = get_episode(ep_a["id"])
    assert ep_a["status"] == "APPROVED"
    assert ep_a["price_rule"] == "LOCKED"
    assert ep_a["applied_bundle_price_cents"] == 3000000

    # Episode B burns 30 day-counter advances (PRD §3.4: the SOR_REVIEW loop
    # "may later resolve identically", and §3.1 lists every day-counter advance
    # among the events that increment screen_seq), so its approval stamps a
    # post-increment gap well past 30 and it re-prices onto the amendment.
    advance_episode_days(ep_b["id"], 30)
    ep_b = get_episode(ep_b["id"])
    validate_success(
        api.record_review(
            ep_b["id"],
            {"conclusion": "SURGERY_INDICATED",
             "expected_episode_version": ep_b["version"]},
            REVIEWER,
        ),
        expected_status=201,
    )
    ep_b = get_episode(ep_b["id"])
    assert ep_b["status"] == "APPROVED"
    assert ep_b["price_rule"] == "REPRICED"
    assert ep_b["applied_bundle_price_cents"] == 3200000

    # Identical BUNDLE_CASE bills adjudicate to different payables because the
    # two episodes sit on different price bases. Schedule strictly into the
    # future relative to each episode's own day counter (PRD §3.5).
    ep_a = drive_episode_to_post_op(ep_a, requested_day_seq=ep_a["screen_seq"] + 1)
    ep_b = drive_episode_to_post_op(ep_b, requested_day_seq=ep_b["screen_seq"] + 1)
    claim_a = submit_claim(ep_a, "BUNDLE_CASE", ep_a["surgery_done_seq"], 4000000)
    claim_b = submit_claim(ep_b, "BUNDLE_CASE", ep_b["surgery_done_seq"], 4000000)
    adj_a = adjudicate(claim_a["id"])
    adj_b = adjudicate(claim_b["id"])
    assert adj_a["status"] == "APPROVED"
    assert adj_a["adjudicated_payable_cents"] == 3000000
    assert adj_b["status"] == "APPROVED"
    assert adj_b["adjudicated_payable_cents"] == 3200000
    assert adj_a["adjudicated_payable_cents"] != adj_b["adjudicated_payable_cents"]


def test_reprice_notice_gap_of_exactly_thirty_days_qualifies(api):
    """PRD §3.4: "if the gap between the episode's `screen_seq` at approval and
    the latest amendment's `effective_from_seq` is at least 30 days — a gap of
    exactly 30 qualifies — the episode is `REPRICED` onto the latest
    amendment's price and components; if the gap is under 30 days, the episode
    stays `LOCKED` onto the price schedule in force before that latest
    amendment"

    Design: Difficulty/dual_variant_calc/bundle_case_payable_locked_vs_repriced_basis
    """
    prog = setup_program()
    contract = prog["contract"]

    # Both episodes reach SOR_PENDING with screen_seq 2 (document + the
    # auto-transition step, per PRD §3.4); the amendment's effective_from_seq
    # is 1. With the approval's own post-increment stamp (PRD §3.4), the gap
    # at approval is (2 + days burned + 1) - 1 = days burned + 2.
    patient_a = make_patient(prog["employer"])
    patient_b = make_patient(prog["employer"])
    ep_a = drive_episode_to_sor_pending(open_episode(patient_a, contract))
    ep_b = drive_episode_to_sor_pending(open_episode(patient_b, contract))

    refreshed = get_success_data(api.get_contract(contract["id"], ADMIN))
    _reprice(contract["id"], refreshed["version"], 3200000, NEW_COMPONENTS)

    # Episode A burns 28 day-counter advances: the approval transition
    # increments screen_seq once more and stamps the post-increment value
    # (PRD §3.4), so its approval gap is exactly 30 — the boundary qualifies
    # as REPRICED ("a gap of exactly 30 qualifies").
    advance_episode_days(ep_a["id"], 28)
    ep_a = get_episode(ep_a["id"])
    validate_success(
        api.record_review(
            ep_a["id"],
            {"conclusion": "SURGERY_INDICATED",
             "expected_episode_version": ep_a["version"]},
            REVIEWER,
        ),
        expected_status=201,
    )
    ep_a = get_episode(ep_a["id"])
    assert ep_a["status"] == "APPROVED"
    assert ep_a["price_rule"] == "REPRICED", "a gap of exactly 30 qualifies"
    assert ep_a["applied_bundle_price_cents"] == 3200000

    # Episode B burns 27 advances (post-increment approval gap 29 < 30): it
    # stays LOCKED on the price schedule in force before the amendment — the
    # contract's original price when exactly one amendment exists (PRD §3.4).
    advance_episode_days(ep_b["id"], 27)
    ep_b = get_episode(ep_b["id"])
    validate_success(
        api.record_review(
            ep_b["id"],
            {"conclusion": "SURGERY_INDICATED",
             "expected_episode_version": ep_b["version"]},
            REVIEWER,
        ),
        expected_status=201,
    )
    ep_b = get_episode(ep_b["id"])
    assert ep_b["status"] == "APPROVED"
    assert ep_b["price_rule"] == "LOCKED"
    assert ep_b["applied_bundle_price_cents"] == 3000000


def test_contract_reprice_self_loop_renews_amendment_history(api):
    """PRD §3.2: "An accepted amendment appends an entry recording the new
    price, the new components, and the `effective_from_seq` at which it took
    effect to the contract's `change_history`, increments `reprice_count` by
    one, updates `bundle_price_cents` and `rate_components` to the new values,
    and bumps the contract's `version`. The contract's `status` stays `ACTIVE`
    through repricing."

    Design: Difficulty/non_linear_state_machine/contract_reprice_self_loop_renews_amendment_history
    """
    employer = make_employer({"ORTHO_JOINT": 2500000})
    template = make_template()
    contract = make_active_contract(employer, template)

    v = contract["version"]
    round1 = _reprice(contract["id"], v, 3200000, NEW_COMPONENTS)
    assert round1["reprice_count"] == 1
    assert round1["bundle_price_cents"] == 3200000
    assert round1["status"] == "ACTIVE"
    assert round1["version"] == v + 1

    components2 = dict(NEW_COMPONENTS, facility=2800000)
    round2 = _reprice(contract["id"], round1["version"], 3400000, components2)
    assert round2["status"] == "ACTIVE", "repricing never leaves ACTIVE"
    assert round2["reprice_count"] == 2
    assert round2["bundle_price_cents"] == 3400000
    assert round2["version"] == v + 2, "each accepted amendment bumps the version"

    history = round2["change_history"]
    assert len(history) == 2, (
        "each accepted amendment appends one change_history entry"
    )


def test_reprice_with_component_sum_mismatch_rejected(api):
    """PRD §3.2: "The amendment carries `expected_contract_version` (per §2.6),
    a `new_bundle_price_cents` greater than zero, and `new_rate_components`
    whose values must again sum exactly to the new price with the implant
    component inside the template cap — the same `ERR_COMPONENT_SUM_MISMATCH`
    and `ERR_IMPLANT_CAP_EXCEEDED` guards as creation."

    Design: Difficulty/non_linear_state_machine/contract_reprice_self_loop_renews_amendment_history
    """
    employer = make_employer({"ORTHO_JOINT": 2500000})
    template = make_template()
    contract = make_active_contract(employer, template)

    resp = api.reprice_contract(
        contract["id"],
        {"expected_contract_version": contract["version"],
         "new_bundle_price_cents": 3200000,
         "new_rate_components": {
             "facility": 2500000,  # 100000 short of the new price
             "professional": 300000,
             "implant": 200000,
             "anesthesia": 100000,
         }},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_COMPONENT_SUM_MISMATCH)

    after = get_success_data(api.get_contract(contract["id"], ADMIN))
    assert after["reprice_count"] == 0
    assert after["change_history"] == []
    assert after["bundle_price_cents"] == 3000000


def test_occ_reprice_stale_contract_version(api):
    """PRD §2.6: "A reprice amendment against a contract must likewise carry
    `expected_contract_version` equal to the contract's current `version`.
    When the contract's version has advanced since the client last read it —
    for example because a prior accepted amendment already changed the price
    schedule — the amendment is rejected with `ERR_STALE_VERSION` (HTTP 412)"

    Design: Corner/cross_cutting_complexity_layers/occ_reprice_stale_contract_version
    """
    employer = make_employer({"ORTHO_JOINT": 2500000})
    template = make_template()
    contract = make_active_contract(employer, template)
    v = contract["version"]

    round1 = _reprice(contract["id"], v, 3200000, NEW_COMPONENTS)

    stale = api.reprice_contract(
        contract["id"],
        {"expected_contract_version": v,  # stale: the first reprice advanced it
         "new_bundle_price_cents": 3400000,
         "new_rate_components": dict(NEW_COMPONENTS, facility=2800000)},
        ADMIN,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    fresh = _reprice(
        contract["id"], round1["version"], 3400000,
        dict(NEW_COMPONENTS, facility=2800000),
    )
    assert fresh["bundle_price_cents"] == 3400000
    assert fresh["reprice_count"] == 2


def test_contract_activation_window_overlap_half_open(api):
    """PRD §3.2: "no other `ACTIVE` contract exists for the same employer and
    the same template procedure family whose half-open coverage window
    overlaps this one. Windows that merely share an endpoint — one ending
    exactly when the other begins — do not overlap and both may activate. A
    genuine overlap is rejected with `ERR_CONTRACT_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/contract_activation_window_overlap_half_open
    """
    employer = make_employer({"ORTHO_JOINT": 2500000})
    template = make_template()
    c1 = make_active_contract(
        employer, template,
        effective_from="2026-09-01T00:00:00Z",
        effective_to="2026-12-01T00:00:00Z",
    )
    c2 = make_contract(
        employer, template,
        effective_from="2026-11-01T00:00:00Z",
        effective_to="2027-03-01T00:00:00Z",
        bundle_price_cents=3100000,
    )
    c3 = make_contract(
        employer, template,
        effective_from="2026-12-01T00:00:00Z",
        effective_to="2027-06-01T00:00:00Z",
        bundle_price_cents=3200000,
    )

    resp = api.activate_contract(c2["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_WINDOW_OVERLAP)
    assert get_success_data(api.get_contract(c2["id"], ADMIN))["status"] == "DRAFT"

    adjacent = validate_success(api.activate_contract(c3["id"], ADMIN))
    assert adjacent["status"] == "ACTIVE", (
        "windows sharing only an endpoint do not overlap"
    )
    assert get_success_data(api.get_contract(c1["id"], ADMIN))["status"] == "ACTIVE"


def test_window_overlap_gate_scoped_to_same_family(api):
    """PRD §3.2: "no other `ACTIVE` contract exists for the same employer and
    the same template procedure family whose half-open coverage window
    overlaps this one."
    An overlapping window for a different procedure family is out of scope for
    the gate, so activation succeeds.

    Design: Difficulty/resource_temporal_overlap/contract_activation_window_overlap_half_open
    """
    employer = make_employer({"ORTHO_JOINT": 2500000, "BARIATRIC": 4000000})
    ortho = make_template()
    bariatric = make_template(procedure_family="BARIATRIC", label="Sleeve")
    c1 = make_active_contract(
        employer, ortho,
        effective_from="2026-09-01T00:00:00Z",
        effective_to="2026-12-01T00:00:00Z",
    )
    assert c1["status"] == "ACTIVE"

    c2 = make_contract(
        employer, bariatric,
        effective_from="2026-09-01T00:00:00Z",
        effective_to="2026-12-01T00:00:00Z",
        bundle_price_cents=3100000,
    )
    activated = validate_success(api.activate_contract(c2["id"], ADMIN))
    assert activated["status"] == "ACTIVE", (
        "a different procedure family is outside the overlap gate"
    )
