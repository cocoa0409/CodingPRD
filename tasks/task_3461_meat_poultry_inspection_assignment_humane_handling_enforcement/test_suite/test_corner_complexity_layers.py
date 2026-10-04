"""Breadth tests: complexity layers — optimistic-concurrency version
advancement, cascade compensation without drift, derived-field reconciliation,
and per-family cumulative rate thresholds."""

from test_helpers import (
    DISTRICT_MANAGER_HEADERS,
    fixtures as fx,
    validate_success,
)


def test_occ_version_increments_on_successful_enforcement_create(api):
    """PRD §3.4: "The proposal must carry `expected_establishment_version` per
    §2.8 — a mismatch is rejected with `ERR_STALE_ESTABLISHMENT_VERSION` (HTTP
    412) — and its creation increments the establishment's `version` by 1."
    PRD §2.6: "The `version` is an integer that starts at 1 when the resource
    is created and increments by 1 on every mutation of that resource —
    including mutations caused by system cascades, so a client watching a
    parent's `version` sees every derived change."

    Design: Corner/complexity_layers/occ_version_increments_on_successful_enforcement_create
    """
    est = fx.create_establishment(api, name="CL1 Plant", species_classes=["CATTLE"])
    inspector = fx.create_inspector(api, species_qualifications=["CATTLE"])
    fx.issue_nr(api, est["id"], inspector["id"], regulation_family="SANITATION",
                description="qualifying nr")
    v_pre = fx.get_establishment(api, est["id"])["version"]

    created = fx.create_enforcement_action(
        api, est["id"], action_type="WITHHOLD_MARKS", basis="NR_LINKAGE",
        regulation_family="SANITATION", expected_establishment_version=v_pre,
    )
    assert created["status"] == "PROPOSED"

    v_post = fx.get_establishment(api, est["id"])["version"]
    assert v_post == v_pre + 1, (
        f"the guarded write advances the parent version by exactly one ({v_pre} -> {v_post})"
    )


def test_suspension_then_lift_restores_held_labels_without_drift(api):
    """PRD §3.4: "Lifting a `SUSPENSION` moves the establishment's
    `inspection_status` from `SUSPENDED` back to `ACTIVE`, moves every label
    application in `HELD` back to `UNDER_REVIEW`, and leaves blocked shift
    windows `BLOCKED` — their windows lie in the past and are not resurrected."
    PRD §2.10: "`suspension_count` is the lifetime number of the
    establishment's enforcement actions of type `SUSPENSION` that have reached
    `IN_EFFECT`."

    Design: Corner/complexity_layers/suspension_then_lift_restores_held_labels_without_drift
    """
    base = fx.create_granted_establishment(api, species_classes=["CATTLE"], name="CL2 Plant")
    est_id = base["establishment"]["id"]
    label = fx.create_label_in_review(
        api, est_id, product_name="NoAbx Loin", label_claim="NO_ANTIBIOTICS",
        documentation_refs=["doc-n1", "doc-n2"],
    )
    pair = fx.create_inspector_pair(api, ["CATTLE"])

    cycle = fx.suspend_establishment_via_egregious_event(
        api, fx.get_establishment(api, est_id), pair["issuer"]["id"], pair["reviewer"]["id"],
    )
    held = {row["id"]: row["status"] for row in fx.list_label_applications(api, est_id)}
    assert held[label["id"]] == "HELD", "the suspension cascade reached the in-review label"

    fx.lift_enforcement(api, cycle["enforcement_action"]["id"])

    restored = {row["id"]: row["status"] for row in fx.list_label_applications(api, est_id)}
    assert restored[label["id"]] == "UNDER_REVIEW", "lift returns the label to its pre-hold status"
    est = fx.get_establishment(api, est_id)
    assert est["inspection_status"] == "ACTIVE"
    assert est["suspension_count"] == 1, "the lifetime count is not rewound by the lift"


def test_pathogen_category_derived_after_results(api):
    """PRD §3.6: "The pathogen is a `CAT_1` candidate when its positive rate is
    at most half the standard rate for that pathogen, a `CAT_2` candidate when
    its rate is at most the standard rate, and a `CAT_3` candidate when its
    rate exceeds the standard rate. The boundaries are pinned: a rate exactly
    equal to the standard rate is `CAT_2`, never `CAT_3`; a rate exactly equal
    to half the standard is `CAT_1`."
    PRD §3.6: "The establishment's `pathogen_category` is the worst category
    across the pathogens that have sufficient samples — `CAT_3` outranks
    `CAT_2`, which outranks `CAT_1`. If no pathogen has sufficient samples, the
    category is unchanged (null if the establishment has never been
    categorized)."

    Design: Corner/complexity_layers/pathogen_category_derived_after_results
    """
    base = fx.create_granted_establishment(api, species_classes=["POULTRY"], name="CL3 Plant")
    est_id = base["establishment"]["id"]
    inspector = fx.create_inspector(api, species_qualifications=["POULTRY"])

    before = fx.get_establishment(api, est_id)
    assert before["pathogen_category"] is None, "null before any categorization"

    # Ten SALMONELLA results, all NEGATIVE: rate 0.0 <= half-standard 0.05.
    fx.categorize_pathogen(api, est_id, inspector["id"], "SALMONELLA", positives=0, negatives=10)

    after = fx.get_establishment(api, est_id)
    assert after["pathogen_category"] == "CAT_1", (
        f"rate 0.0 <= 0.05 half-standard -> CAT_1, got {after['pathogen_category']!r}"
    )
    assert fx.list_enforcement_actions(api, est_id) == [], "CAT_1 creates no enforcement"


def test_rate_threshold_cumulative_not_instantaneous(api):
    """PRD §3.3: "At the moment a record enters `ESCALATED` — whether directly
    from `OPEN`, from `RESPONSE_SUBMITTED`, or through an appeal affirmance per
    §3.9 — the system counts the establishment's qualifying records in the same
    `regulation_family`: those with status `OPEN`, `RESPONSE_SUBMITTED`, or
    `ESCALATED` (records in `APPEALED` or `VACATED` never qualify), whose
    `issued_at` lies within the trailing 90 days of the logical clock inclusive
    of the boundary day, including the record that just escalated, now counted
    in its `ESCALATED` state. If that count reaches 3 — exactly at threshold
    fires — the system automatically creates an enforcement action against the
    establishment: `action_type` `SUSPENSION`, `basis` `NR_LINKAGE`,
    `regulation_family` set to the escalating record's family, `status`
    `PROPOSED`, and `auto_created` true."

    Design: Corner/complexity_layers/rate_threshold_cumulative_not_instantaneous
    """
    est = fx.create_establishment(api, name="CL4 Plant", species_classes=["CATTLE"])
    inspector = fx.create_inspector(api, species_qualifications=["CATTLE"])

    # One escalation in each of two DIFFERENT families: each family's counter
    # sits at 1, and they never sum.
    fx.issue_and_escalate_nrs(api, est["id"], inspector["id"], "SANITATION", 1)
    second = fx.issue_nr(api, est["id"], inspector["id"], regulation_family="HACCP",
                         description="haccp nr")
    escalated = fx.escalate_nr(api, second["id"], inspector["id"])
    assert escalated["status"] == "ESCALATED"

    assert fx.list_enforcement_actions(api, est["id"]) == [], (
        "per-family counters are 1 and 1; neither reaches the threshold of 3"
    )
    data = validate_success(api.get_establishment(est["id"], DISTRICT_MANAGER_HEADERS), 200)
    assert data["open_nr_count"] == 2
