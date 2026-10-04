"""Formulation, jurisdiction, substance, and component basics (PRD §2.5, §3.1, §3.2)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_formulation,
    assert_formulation_component,
    component_payload,
    create_formulation,
    create_jurisdiction,
    create_substance,
    decide_clearance,
    discontinue_payload,
    formulation_payload,
    get_formulation,
    set_clock,
    submit_clearance,
    substance_payload,
    successor_payload,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = TEST_USERS["product_manager_headers"]
PA = TEST_USERS["platform_admin_headers"]
RM = TEST_USERS["regulatory_manager_headers"]


def test_formulation_create_returns_server_defaults(api):
    """PRD §3.2: "A root formulation is born in `DRAFT` status with
    `revision_number` 1, `successor_of_id` null, `active_clearance_count` 0, and
    all last-time-buy fields (`ltb_deadline`, `last_ship_date`,
    `ltb_pool_quantity`, `ltb_pool_remaining`) null."

    Design: Corner/entities/formulation_create_returns_server_defaults
    """
    set_clock()
    resp = api.create_formulation(formulation_payload(), PM)
    data = validate_success(resp, 201)
    assert_formulation(data)
    assert data["status"] == "DRAFT"
    assert data["revision_number"] == 1
    assert data["version"] == 1
    assert data["successor_of_id"] is None
    assert data["active_clearance_count"] == 0
    for field in ("ltb_deadline", "last_ship_date", "ltb_pool_quantity", "ltb_pool_remaining"):
        assert data[field] is None, f"{field} must be null on a root formulation"
    assert data.get("discontinued_at") is None


def test_jurisdiction_get_roundtrip_applies_sla_default(api):
    """PRD §3.1: "An optional `review_sla_days` (defaulting to 30 when omitted)
    records the advisory review turnaround; it is informational only and gates
    nothing."

    Design: Corner/entities/jurisdiction_get_roundtrip_applies_sla_default
    """
    set_clock()
    created = api.create_jurisdiction(
        {
            "code": "DE",
            "name": "Germany",
            "declaration_threshold_ppm": 1000,
            "full_disclosure_threshold_ppm": 10000,
        },
        PA,
    )
    jur = validate_success(created, 201)
    data = validate_success(api.get_jurisdiction(jur["id"], RM), 200)
    assert data["code"] == "DE"
    assert data["declaration_threshold_ppm"] == 1000
    assert data["full_disclosure_threshold_ppm"] == 10000
    assert data["review_sla_days"] == 30, "omitted review_sla_days must default to 30"


def test_formulation_components_list_reverse_reaches_both_parents(api):
    """PRD §4: "List formulation components; filterable by `formulation_id` and
    `substance_id`" PRD §2.3: "The `meta` object of a list response carries
    exactly the pagination fields `limit`, `offset`, `total_count`, and
    `has_more`, so a client can always tell how many records exist in total and
    whether further pages follow."

    Design: Corner/entities/formulation_components_list_reverse_reaches_both_parents
    """
    set_clock()
    s1 = create_substance(cas_number="50-00-0", name="Formaldehyde", restriction_class="RESTRICTED")
    s2 = create_substance(cas_number="64-17-5", name="Ethanol", restriction_class="REPORTABLE")
    f1 = create_formulation(product_code="F-100")
    f2 = create_formulation(product_code="F-200", name="Solvent adhesive", base_polymer_family="solvent")
    api.create_formulation_component(component_payload(f1["id"], s1["id"], 5000), PM)
    api.create_formulation_component(component_payload(f1["id"], s2["id"], 200), PM)
    api.create_formulation_component(component_payload(f2["id"], s1["id"], 300), PM)

    rows, meta = validate_paginated(
        api.list_formulation_components(PM, params={"formulation_id": f1["id"]})
    )
    assert meta["total_count"] == 2 and meta["has_more"] is False
    assert {(r["substance_id"], r["concentration_ppm"]) for r in rows} == {
        (s1["id"], 5000),
        (s2["id"], 200),
    }

    rows2, meta2 = validate_paginated(
        api.list_formulation_components(PM, params={"substance_id": s1["id"]})
    )
    assert meta2["total_count"] == 2
    assert {r["formulation_id"] for r in rows2} == {f1["id"], f2["id"]}


def test_component_create_missing_concentration_returns_invalid_request(api):
    """PRD §2.9: "Request shape — required fields present, enum values valid,
    concentrations and quantities positive, windows start strictly before they
    end, breakpoint and tier arrays correctly sorted and within size limits, and
    exactly-one-of partner pairs not both absent, else `ERR_INVALID_REQUEST`
    (400)." PRD §3.2: "each row naming a `formulation_id`, a `substance_id`,
    and a strictly positive `concentration_ppm`."

    Design: Corner/entities/component_create_missing_concentration_returns_invalid_request
    """
    set_clock()
    form = create_formulation()
    sub = create_substance()
    resp = api.create_formulation_component(
        {"formulation_id": form["id"], "substance_id": sub["id"]}, PM
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_formulation_component_row_is_immutable_without_version(api):
    """PRD §2.5: "it carries `id` and `created_at` only. Both `updated_at` and
    `version` are absent from FormulationComponent, and no endpoint updates or
    deletes one; its content is fixed at creation."

    Design: Corner/entities/formulation_component_row_is_immutable_without_version
    """
    set_clock()
    form = create_formulation()
    sub = create_substance()
    resp = api.create_formulation_component(component_payload(form["id"], sub["id"], 5000), PM)
    data = validate_success(resp, 201)
    assert_formulation_component(data)


def test_substance_create_rejects_unknown_restriction_class(api):
    """PRD §3.1: "A **substance** is registered with its unique `cas_number`, a
    display `name`, and a `restriction_class` of exactly one of `STANDARD`,
    `REPORTABLE`, `RESTRICTED`, or `PROHIBITED`." PRD §2.9: "Request shape —
    required fields present, enum values valid, concentrations and quantities
    positive, windows start strictly before they end, breakpoint and tier arrays
    correctly sorted and within size limits, and exactly-one-of partner pairs
    not both absent, else `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/substance_create_rejects_unknown_restriction_class
    """
    set_clock()
    resp = api.create_substance(
        substance_payload(cas_number="00-00-0", name="Mystery", restriction_class="BANNED"),
        PA,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_successor_creation_sets_self_reference_and_revision(api):
    """PRD §3.2: "The new row is a root-like `DRAFT` whose `revision_number` is
    the predecessor's `revision_number` plus one and whose `successor_of_id`
    points at the predecessor; the write also increments the predecessor's
    `version`."

    Design: Corner/entities/successor_creation_sets_self_reference_and_revision
    """
    set_clock()
    form = create_formulation()
    resp = api.create_successor(
        form["id"],
        successor_payload(
            product_code="F-100R",
            name="Reformulated acrylic foam",
            expected_formulation_version=form["version"],
        ),
        PM,
    )
    succ = validate_success(resp, 201)
    assert succ["successor_of_id"] == form["id"]
    assert succ["revision_number"] == 2
    assert succ["status"] == "DRAFT"
    predecessor = get_formulation(form["id"])
    assert predecessor["version"] == form["version"] + 1
    rows, meta = validate_paginated(
        api.list_formulations(PM, params={"successor_of_id": form["id"]})
    )
    assert meta["total_count"] == 1
    assert [r["id"] for r in rows] == [succ["id"]]


def test_discontinue_from_draft_rejected(api):
    """PRD §3.2: "Discontinuation is the product change notification and the
    opening of the last-time-buy window in a single action, performed by a
    `ProductManager` on an `ACTIVE` formulation with a payload of
    `last_time_buy_deadline`, `last_ship_date`, and `ltb_pool_quantity`."
    PRD §2.9: "State legality — the target entity is in a state from which the
    requested transition exists, and terminal states accept nothing further,
    else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/discontinue_from_draft_rejected
    """
    set_clock()
    form = create_formulation()
    resp = api.discontinue_formulation(form["id"], discontinue_payload(), PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = get_formulation(form["id"])
    assert after["status"] == "DRAFT"
    assert after["ltb_deadline"] is None
    assert after["ltb_pool_quantity"] is None


def test_active_clearance_count_reconciles_across_jurisdictions(api):
    """PRD §3.2: "A clearance granted `CLEARED` increments the formulation's
    `active_clearance_count`, and when that count rises from 0 to 1 the
    formulation itself bubbles up from `DRAFT` to `ACTIVE` — the moment the
    product becomes eligible for price agreements, application cases, and
    orders."

    Design: Corner/cross_cutting_layers/active_clearance_count_reconciles_across_jurisdictions
    """
    set_clock()
    jur_de = create_jurisdiction(code="DE", declaration_threshold_ppm=1000,
                                 full_disclosure_threshold_ppm=10000)
    jur_us = create_jurisdiction(code="US", name="United States",
                                 declaration_threshold_ppm=500,
                                 full_disclosure_threshold_ppm=5000)
    form = create_formulation()
    assert form["active_clearance_count"] == 0
    cl_de = submit_clearance(form["id"], jur_de["id"], "EXEMPT")
    assert get_formulation(form["id"])["active_clearance_count"] == 0
    decide_clearance(cl_de["id"], "CLEARED")
    after_de = get_formulation(form["id"])
    assert after_de["active_clearance_count"] == 1
    assert after_de["status"] == "ACTIVE"
    cl_us = submit_clearance(form["id"], jur_us["id"], "EXEMPT")
    decide_clearance(cl_us["id"], "CLEARED")
    after_us = get_formulation(form["id"])
    assert after_us["active_clearance_count"] == 2
