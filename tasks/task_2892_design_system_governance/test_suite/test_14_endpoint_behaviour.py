"""
Routes read back exactly what their write produced.

Each scenario here drives one endpoint family end to end — declare, list,
re-pin; promote; resolve — and then reads the same fact through every other
route that is supposed to know about it, so a write that only half-lands is
visible somewhere.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_A11Y_CRITICAL_VIOLATIONS_OPEN,
    ERR_COMPONENT_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_audit_row,
    assert_conformance_score,
    assert_fields,
    assert_instant_equals,
    assert_page_meta,
    assert_versioned_row,
)
from test_helpers.constants import (
    AUDIT_METHOD_AUTOMATED,
    BRANDS,
    COMPAT_COMPATIBLE,
    COMPAT_INCOMPATIBLE,
    COVERAGE_NONE,
    DEFAULT_BRAND,
    DEFAULT_CLOCK,
    DEFAULT_MODE,
    DEFAULT_TOKEN_MODE,
    DEMOTION_REASON_NONE,
    DIRECTION_ALL,
    DIRECTION_CONSUMES,
    DIRECTION_PROVIDES,
    IMPL_PLANNED,
    MATURITY_BETA,
    MATURITY_EXPERIMENTAL,
    MODES,
    PLATFORM_WEB,
)
from test_helpers.factories import (
    dependency_payload,
    dependency_repin_payload,
    promote_payload,
    ship_payload,
)
from test_helpers.fixtures import (
    alias_token,
    file_audit,
    file_clean_evidence,
    governance_base,
    leaf_token,
    make_component,
    make_implementation,
    make_token_set,
    pin_clock,
    read_component,
    read_implementation,
    read_token_set,
    ship,
)
from test_helpers.test_users import (
    make_contributing_team_headers,
    make_design_system_lead_headers,
    make_engineering_reviewer_headers,
)

UNKNOWN_COMPONENT_UUID = "00000000-0000-4000-8000-0000000000aa"

BRAND_BASE, BRAND_A, BRAND_B = BRANDS
MODE_LIGHT, MODE_DARK = MODES
MODE_ANY = DEFAULT_TOKEN_MODE


def _one_edge_pinned_past_the_provider(api):
    """
    Two components owned by one team, joined by an edge pinned at major 2.

    The provider is still on its opening major version, so the pin is one
    version ahead of what the provider actually publishes.
    """
    base = governance_base(
        api, team_slug="design-guild", component_name="Badge", component_slug="badge"
    )
    provider = make_component(api, base["team_id"], name="Icon", slug="icon")
    base.update(
        {
            "consumer": base["component"],
            "consumer_id": base["component_id"],
            "provider": provider,
            "provider_id": provider["id"],
        }
    )
    return base


def test_the_three_dependency_routes_agree_on_one_edge(api):
    """Declaring, listing and re-pinning an edge all describe the same row.

    PRD: "At declaration the edge is `COMPATIBLE` when `pinned_provider_major` equals the provider's `current_major_version` and the provider's `lifecycle_state` is not `SUNSET`; it is `SUNSET_PROVIDER` when the provider is at `SUNSET`; and it is `INCOMPATIBLE` otherwise — which in practice means the consumer pinned a major version the provider has moved past."

    PRD: "The consumer component's `blocked_dependency_count` is then recomputed as the number of its outgoing edges whose `compatibility_state` is `INCOMPATIBLE` or `SUNSET_PROVIDER`, and the consumer component's `version` is incremented by 1."

    PRD: "Edges touching a component are listable from that component, with a `direction` filter accepting `ALL`, which is the default, `CONSUMES` for the edges where the path component is the consumer, and `PROVIDES` for the edges where it is the provider."

    PRD: "The operation returns 200 and increments both the edge's `version` and the consumer component's `version` by 1."

    The block is counted at declaration rather than lazily at ship time, and the
    re-pin gives it back through the edge's own route.

    Design: Corner/endpoints/dependency_edge_is_created_read_and_repinned_through_its_own_routes
    """
    scenario = _one_edge_pinned_past_the_provider(api)
    consumer_id = scenario["consumer_id"]
    provider_id = scenario["provider_id"]
    assert scenario["provider"]["current_major_version"] == 1
    assert scenario["consumer"]["version"] == 1

    edge = validate_success(
        api.create_dependency(
            consumer_id,
            dependency_payload(provider_id, pinned_provider_major=2),
            make_design_system_lead_headers(),
        ),
        201,
    )
    assert_versioned_row(edge, 1, "dependency edge")
    assert_fields(
        edge,
        {
            "consumer_component_id": consumer_id,
            "provider_component_id": provider_id,
            "pinned_provider_major": 2,
            "compatibility_state": COMPAT_INCOMPATIBLE,
        },
        "dependency edge",
    )
    assert_fields(
        read_component(api, consumer_id),
        {"blocked_dependency_count": 1, "version": 2},
        "consumer",
    )

    consumed, consumed_meta = validate_paginated(
        api.list_dependencies(
            consumer_id,
            make_contributing_team_headers(scenario["team_id"]),
            params={"direction": DIRECTION_CONSUMES, "limit": 100, "offset": 0},
        )
    )
    assert_page_meta(consumed_meta, total_count=1, has_more=False, limit=100, offset=0)
    assert consumed[0]["id"] == edge["id"]
    assert consumed[0]["pinned_provider_major"] == 2

    provided, provided_meta = validate_paginated(
        api.list_dependencies(
            provider_id,
            make_design_system_lead_headers(),
            params={"direction": DIRECTION_PROVIDES},
        )
    )
    assert_page_meta(provided_meta, total_count=1)
    assert [row["id"] for row in provided] == [edge["id"]]

    repinned = validate_success(
        api.update_dependency(
            edge["id"], dependency_repin_payload(1), make_design_system_lead_headers()
        ),
        200,
    )
    assert_fields(
        repinned,
        {
            "pinned_provider_major": 1,
            "compatibility_state": COMPAT_COMPATIBLE,
            "version": 2,
        },
        "re-pinned edge",
    )
    assert_fields(
        read_component(api, consumer_id),
        {"blocked_dependency_count": 0, "version": 3},
        "consumer",
    )
    _, all_meta = validate_paginated(
        api.list_dependencies(
            consumer_id,
            make_design_system_lead_headers(),
            params={"direction": DIRECTION_ALL},
        )
    )
    assert_page_meta(all_meta, total_count=1)


def test_beta_promotion_resets_the_baseline_and_clears_the_demotion_reason(api):
    """The promotion action writes four fields, not just the maturity level.

    PRD: "A successful promotion returns 200. It sets `maturity_level` to the requested destination, clears `maturity_demotion_reason` back to `NONE`, resets `conformance_baseline_at` to the logical clock, recomputes `governance_conformance_score` against that new window — dropping every audit older than the reset out of the sweep entirely, which typically raises the score in the same request — and increments the component's `version` by 1."

    PRD: "It also stamps `conformance_baseline_at` from the logical clock — this is the opening of the component's accessibility-evidence window, discussed in §3.4 — and sets `docs_last_reviewed_at` to the logical clock when the supplied `docs_state` is `PUBLISHED`, and to null otherwise."

    The component opens at version 1, the two filed audits and the ship each add
    one, and the promotion adds the fifth.

    Design: Corner/endpoints/beta_promotion_resets_the_conformance_baseline_and_clears_the_demotion_reason
    """
    base = governance_base(
        api, team_slug="design-guild", component_name="Badge", component_slug="badge"
    )
    created = base["component"]
    assert_fields(
        created,
        {"maturity_level": MATURITY_EXPERIMENTAL, "version": 1},
        "component",
    )
    assert_instant_equals(
        created["conformance_baseline_at"], DEFAULT_CLOCK, "conformance_baseline_at"
    )

    impl = make_implementation(
        api,
        base["component_id"],
        base["team_id"],
        platform=PLATFORM_WEB,
        package_name="@ds/badge-web",
        token_compliance_ratio=0.97,
    )
    file_clean_evidence(api, impl["id"], base["team_id"])
    ship(api, impl["id"], base["team_id"], token_compliance_ratio=0.97)

    before = read_component(api, base["component_id"])
    assert_conformance_score(before, 100.00, "governance_conformance_score")
    assert before["version"] == 4, (
        "the component's version counts its creation, the two filed audits and "
        f"the ship, got {before['version']}"
    )

    promoted = validate_success(
        api.promote_maturity(
            base["component_id"],
            promote_payload(MATURITY_BETA),
            make_design_system_lead_headers(),
        ),
        200,
    )
    assert_fields(
        promoted,
        {
            "maturity_level": MATURITY_BETA,
            "maturity_demotion_reason": DEMOTION_REASON_NONE,
            "version": 5,
        },
        "promoted component",
    )
    assert_conformance_score(promoted, 100.00, "governance_conformance_score")
    assert_instant_equals(
        promoted["conformance_baseline_at"], DEFAULT_CLOCK, "conformance_baseline_at"
    )


def _resolve(api, token_set_id, params=None):
    """Read the resolved view of a set, optionally at a brand-and-mode coordinate."""
    return validate_success(
        api.get_resolved_tokens(
            token_set_id, make_engineering_reviewer_headers(), params=params
        )
    )


def _sole_entry(resolved, label):
    """The one resolved entry a single-name set is expected to produce."""
    entries = resolved["resolved"]
    assert isinstance(entries, list) and len(entries) == 1, (
        f"{label}: expected exactly one resolved entry, got {entries!r}"
    )
    return entries[0]


def _entry_carries(entry, label, *expected):
    """Assert a resolved entry reports the values the precedence walk selected."""
    reported = {str(value) for value in entry.values()}
    for want in expected:
        assert want in reported, f"{label}: {entry!r} does not report {want!r}"


def _four_layers_of_one_name(api):
    """
    One token name backed by a row on each of the four precedence layers.

    The (BRAND_A, DARK) row is an alias onto the (BASE, ANY) leaf, so the layer
    the walk selects and the value it ends on are deliberately different facts.
    """
    pin_clock(api)
    token_set = make_token_set(
        api,
        name="Core",
        slug="core",
        default_brand=DEFAULT_BRAND,
        default_mode=DEFAULT_MODE,
    )
    set_id = token_set["id"]
    assert_fields(
        token_set,
        {"default_brand": DEFAULT_BRAND, "default_mode": DEFAULT_MODE, "version": 1},
        "token set",
    )

    def version():
        return read_token_set(api, set_id)["version"]

    base_any = leaf_token(
        api, set_id, "color.surface", "#FFFFFF", version(),
        brand=BRAND_BASE, mode=MODE_ANY,
    )
    base_dark = leaf_token(
        api, set_id, "color.surface", "#101010", version(),
        brand=BRAND_BASE, mode=MODE_DARK,
    )
    brand_a_any = leaf_token(
        api, set_id, "color.surface", "#FAF7F0", version(),
        brand=BRAND_A, mode=MODE_ANY,
    )
    brand_a_dark = alias_token(
        api, set_id, "color.surface", base_any["id"], version(),
        brand=BRAND_A, mode=MODE_DARK,
    )
    return {
        "token_set_id": set_id,
        "base_any": base_any,
        "base_dark": base_dark,
        "brand_a_any": brand_a_any,
        "brand_a_dark": brand_a_dark,
    }


def test_a_resolved_read_walks_all_four_precedence_layers(api):
    """One name resolves through a different layer at each read coordinate.

    PRD: "For each distinct name, the layer to use is the first present entry in this strictly ordered precedence list: the requested brand at the requested mode; then the requested brand at `ANY`; then `BASE` at the requested mode; then `BASE` at `ANY`."

    PRD: "Layer selection happens once, on the chosen token; alias targets are then resolved by explicit id and never re-enter layer selection, so a `BRAND_A` token aliasing a `BASE` token resolves to that `BASE` leaf's value regardless of the brand the read asked for."

    PRD: "The read accepts an optional `brand` and an optional `mode`; an omitted `brand` falls back to the set's `default_brand` and an omitted `mode` to its `default_mode`."

    PRD: "The response echoes `token_set_id`, the resolved `brand` and `mode`, the set's `max_alias_depth`, a `resolved_count` giving the number of names resolved, and the `resolved` array of resolved entries."

    Design: Corner/endpoints/resolved_tokens_read_walks_all_four_layers_of_the_precedence_list
    """
    scenario = _four_layers_of_one_name(api)
    set_id = scenario["token_set_id"]
    assert_fields(
        scenario["brand_a_dark"],
        {"alias_depth": 1, "resolved_value": "#FFFFFF"},
        "the aliasing row",
    )

    layer_one = _resolve(api, set_id, {"brand": BRAND_A, "mode": MODE_DARK})
    assert_fields(
        layer_one,
        {
            "token_set_id": set_id,
            "brand": BRAND_A,
            "mode": MODE_DARK,
            "resolved_count": 1,
            "max_alias_depth": 1,
        },
        "layer 1 read",
    )
    _entry_carries(
        _sole_entry(layer_one, "layer 1 read"),
        "layer 1 read",
        "color.surface",
        scenario["brand_a_dark"]["id"],
        "#FFFFFF",
    )

    layer_two = _resolve(api, set_id, {"brand": BRAND_A, "mode": MODE_LIGHT})
    assert layer_two["resolved_count"] == 1
    _entry_carries(
        _sole_entry(layer_two, "layer 2 read"),
        "layer 2 read",
        scenario["brand_a_any"]["id"],
        "#FAF7F0",
    )

    layer_three = _resolve(api, set_id, {"brand": BRAND_B, "mode": MODE_DARK})
    assert layer_three["resolved_count"] == 1
    _entry_carries(
        _sole_entry(layer_three, "layer 3 read"),
        "layer 3 read",
        scenario["base_dark"]["id"],
        "#101010",
    )

    layer_four = _resolve(api, set_id, {"brand": BRAND_B, "mode": MODE_LIGHT})
    assert layer_four["resolved_count"] == 1
    _entry_carries(
        _sole_entry(layer_four, "layer 4 read"),
        "layer 4 read",
        scenario["base_any"]["id"],
        "#FFFFFF",
    )

    defaulted = _resolve(api, set_id)
    assert_fields(
        defaulted,
        {"brand": DEFAULT_BRAND, "mode": DEFAULT_MODE, "resolved_count": 1},
        "defaulted read",
    )
    _entry_carries(
        _sole_entry(defaulted, "defaulted read"),
        "defaulted read",
        scenario["base_any"]["id"],
        "#FFFFFF",
    )


def test_ship_is_refused_when_the_newest_automated_audit_reopens_a_critical(api):
    """The ship gate reads the newest automated audit, not the best one.

    PRD: "The `AUTOMATED` `AA` accessibility audit with the greatest `audit_sequence` for this implementation must exist and must report `violations_critical` equal to 0; a missing audit or any open critical finding is `ERR_A11Y_CRITICAL_VIOLATIONS_OPEN`."

    PRD: "Add the two products. Subtract that sum from 100, then subtract a further 25.0 for each missing method."

    PRD: "When that set is empty, the component's `governance_conformance_score` is 0.00."

    A clean run at sequence 1 followed by a regressed one at sequence 2 leaves the
    implementation on 71.00 — a critical load of 10 weighted at 0.4 and a 25.0
    penalty for the absent manual method — and the ship is refused.

    Design: Corner/endpoints/ship_is_refused_when_the_newest_automated_audit_reopens_a_critical
    """
    base = governance_base(
        api, team_slug="design-guild", component_name="Badge", component_slug="badge"
    )
    impl = make_implementation(
        api,
        base["component_id"],
        base["team_id"],
        platform=PLATFORM_WEB,
        package_name="@ds/badge-web",
    )
    clean = file_audit(
        api, impl["id"], base["team_id"], method=AUDIT_METHOD_AUTOMATED
    )
    assert_audit_row(clean, 1, 0, 0, 0, AUDIT_METHOD_AUTOMATED)
    regressed = file_audit(
        api, impl["id"], base["team_id"], critical=1, method=AUDIT_METHOD_AUTOMATED
    )
    assert_audit_row(regressed, 2, 1, 0, 0, AUDIT_METHOD_AUTOMATED)

    validate_error(
        api.ship_implementation(
            impl["id"],
            ship_payload(package_version="1.0.0", token_compliance_ratio=0.90),
            make_contributing_team_headers(base["team_id"]),
        ),
        ERR_A11Y_CRITICAL_VIOLATIONS_OPEN,
        422,
    )

    after = read_implementation(api, impl["id"])
    assert_fields(
        after,
        {"status": IMPL_PLANNED, "shipped_at": None, "last_audit_sequence": 2},
        "implementation",
    )
    assert_conformance_score(after, 71.00)
    component = read_component(api, base["component_id"])
    assert component["coverage_state"] == COVERAGE_NONE
    assert component["shipped_platform_count"] == 0
    assert_conformance_score(component, 0.00, "governance_conformance_score")


def test_a_dependency_needs_both_of_its_endpoints_to_exist(api):
    """An unknown provider in the body refuses the edge and writes nothing.

    PRD: "`ERR_COMPONENT_NOT_FOUND` covers every component reference regardless of its role in the payload — a proposal's `target_component_id`, a dependency's `provider_component_id`, an exception grant's `substitute_for_component_id` and a deprecation plan's `replacement_component_id` all report the same code."

    PRD: "A `DesignSystemLead`, or a `ContributingTeam` that owns the consuming component, declares an edge from the component in the request path — which becomes the edge's `consumer_component_id` — to a `provider_component_id` supplied in the payload, at a `pinned_provider_major` that must be an integer of at least 1 and that records which major version of the provider's public API the consumer is built against."

    The same request against a real provider creates one row, and that row is
    reachable from both of its endpoints.

    Design: Corner/endpoints/dependency_link_requires_both_endpoints_of_the_edge_to_exist
    """
    scenario = _one_edge_pinned_past_the_provider(api)
    consumer_id = scenario["consumer_id"]

    validate_error(
        api.create_dependency(
            consumer_id,
            dependency_payload(UNKNOWN_COMPONENT_UUID, pinned_provider_major=1),
            make_design_system_lead_headers(),
        ),
        ERR_COMPONENT_NOT_FOUND,
        404,
    )
    assert_fields(
        read_component(api, consumer_id),
        {"version": 1, "blocked_dependency_count": 0},
        "consumer",
    )
    _, empty_meta = validate_paginated(
        api.list_dependencies(
            consumer_id,
            make_design_system_lead_headers(),
            params={"direction": DIRECTION_ALL},
        )
    )
    assert_page_meta(empty_meta, total_count=0, has_more=False)

    edge = validate_success(
        api.create_dependency(
            consumer_id,
            dependency_payload(scenario["provider_id"], pinned_provider_major=1),
            make_design_system_lead_headers(),
        ),
        201,
    )
    assert_fields(
        edge,
        {
            "compatibility_state": COMPAT_COMPATIBLE,
            "consumer_component_id": consumer_id,
            "provider_component_id": scenario["provider_id"],
        },
        "dependency edge",
    )
    provided, provided_meta = validate_paginated(
        api.list_dependencies(
            scenario["provider_id"],
            make_design_system_lead_headers(),
            params={"direction": DIRECTION_PROVIDES},
        )
    )
    assert_page_meta(provided_meta, total_count=1)
    assert [row["id"] for row in provided] == [edge["id"]]
