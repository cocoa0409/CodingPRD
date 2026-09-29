"""Pytest fixtures and composite scenario builders.

Every test starts against an empty database, so each scenario is rebuilt from
the API alone. The builders below walk the PRD's own workflow order: register
an authority and a brand, bring twenty units into `OPERATING` so the brand
becomes a covered establishment, certify a recipe for a menu item, publish a
disclosure packet, then draft, list and publish a menu board.

Setup calls use `get_success_data`, which raises a clear "Setup step failed"
message naming the error identifier when a precondition is not met.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import get_success_data

from . import api_errors  # noqa: F401  (registers the error/status mapping)
from . import factories as f
from .api_client import ApiClient
from .constants import (
    BOARD_PRIMARY_MENU_BOARD,
    CHANNEL_IN_STORE_BINDER,
    CHANNEL_WEBSITE,
    CLOCK_EPOCH_COMPACT,
    DECISION_CERTIFY,
    DECISION_REJECT,
    EXTRA_REQUIREMENT_NONE,
    ITEM_CLASS_STANDARD,
    METHOD_DATABASE,
    PREEMPTION_VARIANCE_ALLOWED,
    STATEMENT_FEDERAL_DEFAULT,
    TIER_FEDERAL_ALIGNED,
    UNIT_OPERATING,
    VARIABLE_NONE,
    VARIANCE_DECISION_GRANTED,
    VARIANCE_DECISION_OPEN_REVIEW,
)
from .test_users import (
    PLATFORM_ADMIN,
    ANALYST_CERTIFIER,
    ANALYST_SUBMITTER,
    make_brand_officer_headers,
    make_publisher_headers,
    make_regulator_headers,
)


# ---------------------------------------------------------------------------
# Scenario containers
# ---------------------------------------------------------------------------
@dataclass
class Env:
    """An authority, a brand and that brand's first unit, with their headers."""

    api: ApiClient
    jurisdiction: Dict[str, Any]
    brand: Dict[str, Any]
    establishment: Dict[str, Any]

    @property
    def admin(self) -> Dict[str, str]:
        return PLATFORM_ADMIN

    @property
    def officer(self) -> Dict[str, str]:
        return make_brand_officer_headers(self.brand["id"])

    @property
    def publisher(self) -> Dict[str, str]:
        return make_publisher_headers(self.establishment["id"])

    @property
    def regulator(self) -> Dict[str, str]:
        return make_regulator_headers(self.jurisdiction["id"])

    @property
    def submitter(self) -> Dict[str, str]:
        return ANALYST_SUBMITTER

    @property
    def certifier(self) -> Dict[str, str]:
        return ANALYST_CERTIFIER

    @property
    def brand_id(self) -> str:
        return self.brand["id"]

    @property
    def jurisdiction_id(self) -> str:
        return self.jurisdiction["id"]

    @property
    def establishment_id(self) -> str:
        return self.establishment["id"]

    # --- readbacks ------------------------------------------------------
    def read_brand(self) -> Dict[str, Any]:
        return get_success_data(self.api.get_brand(self.brand_id, self.officer))

    def read_jurisdiction(self) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_jurisdiction(self.jurisdiction_id, self.officer)
        )

    def read_establishment(self, establishment_id: Optional[str] = None) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_establishment(
                establishment_id or self.establishment_id, self.officer
            )
        )

    def read_item(self, menu_item_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_menu_item(menu_item_id, self.officer))

    def read_recipe(self, recipe_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_recipe(recipe_id, self.officer))

    def read_analysis(self, analysis_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_nutrition_analysis(analysis_id, self.officer)
        )

    def read_packet(self, packet_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_disclosure_packet(packet_id, self.officer)
        )

    def read_board(self, board_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_menu_board(board_id, self.officer))

    def read_listing(self, board_id: str, listing_id: str) -> Dict[str, Any]:
        rows = get_success_data(
            self.api.list_menu_board_listings(board_id, self.officer)
        )
        for row in rows:
            if row["id"] == listing_id:
                return row
        raise AssertionError(f"listing {listing_id} not found on board {board_id}")

    def read_variance(self, variance_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_variance_request(variance_id, self.officer)
        )

    def read_action(self, action_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_enforcement_action(action_id, self.officer)
        )

    def read_summary(self) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_brand_compliance_summary(self.brand_id, self.officer)
        )

    @property
    def brand_version(self) -> int:
        return self.read_brand()["version"]


@dataclass
class ItemBundle:
    """A menu item together with its recipe chain."""

    item: Dict[str, Any]
    recipes: List[Dict[str, Any]] = field(default_factory=list)
    analyses: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def item_id(self) -> str:
        return self.item["id"]

    @property
    def recipe(self) -> Dict[str, Any]:
        return self.recipes[-1]

    @property
    def analysis(self) -> Dict[str, Any]:
        return self.analyses[-1]


@dataclass
class BoardBundle:
    board: Dict[str, Any]
    listings: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def board_id(self) -> str:
        return self.board["id"]

    @property
    def listing(self) -> Dict[str, Any]:
        return self.listings[-1]


# ---------------------------------------------------------------------------
# Primitive builders
# ---------------------------------------------------------------------------
def set_clock(api: ApiClient, to_iso8601: str = CLOCK_EPOCH_COMPACT) -> Dict[str, Any]:
    """Move the logical clock of PRD 2.4 and run its sweep."""
    return get_success_data(
        api.set_clock(f.clock_payload(to_iso8601=to_iso8601), PLATFORM_ADMIN)
    )


def make_jurisdiction(
    api: ApiClient,
    code: str = "CA-VAR",
    name: str = "California",
    preemption_mode: str = PREEMPTION_VARIANCE_ALLOWED,
    extra_requirement: str = EXTRA_REQUIREMENT_NONE,
    enforcement_tier: str = TIER_FEDERAL_ALIGNED,
    **extra: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_jurisdiction(
            f.jurisdiction_payload(
                code=code,
                name=name,
                preemption_mode=preemption_mode,
                extra_requirement=extra_requirement,
                enforcement_tier=enforcement_tier,
                **extra,
            ),
            PLATFORM_ADMIN,
        )
    )


def make_brand(
    api: ApiClient,
    legal_name: str = "Golden Grill Holdings LLC",
    doing_business_as: Any = "Golden Grill",
) -> Dict[str, Any]:
    return get_success_data(
        api.create_brand(
            f.brand_payload(
                legal_name=legal_name, doing_business_as=doing_business_as
            ),
            PLATFORM_ADMIN,
        )
    )


def make_establishment(
    api: ApiClient,
    brand_id: str,
    jurisdiction_id: str,
    unit_label: str,
    unit_status: str = UNIT_OPERATING,
    operates_under_brand_name: bool = True,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_establishment(
            f.establishment_payload(
                brand_id=brand_id,
                jurisdiction_id=jurisdiction_id,
                unit_label=unit_label,
                unit_status=unit_status,
                operates_under_brand_name=operates_under_brand_name,
            ),
            headers or PLATFORM_ADMIN,
        )
    )


def register_unit_batch(
    api: ApiClient,
    brand_id: str,
    jurisdiction_id: str,
    unit_count: int,
    unit_status: str = UNIT_OPERATING,
    operates_under_brand_name: bool = True,
    unit_label_prefix: Any = "CA-B",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_establishment_batch(
            brand_id,
            f.establishment_batch_payload(
                jurisdiction_id=jurisdiction_id,
                unit_count=unit_count,
                unit_status=unit_status,
                operates_under_brand_name=operates_under_brand_name,
                unit_label_prefix=unit_label_prefix,
            ),
            headers or PLATFORM_ADMIN,
        )
    )


def seed_registry(
    api: ApiClient,
    code: str = "CA-VAR",
    name: str = "California",
    preemption_mode: str = PREEMPTION_VARIANCE_ALLOWED,
    extra_requirement: str = EXTRA_REQUIREMENT_NONE,
    enforcement_tier: str = TIER_FEDERAL_ALIGNED,
    unit_count: int = 20,
    unit_label: str = "CA-0001",
    unit_label_prefix: str = "CA-B",
    unit_status: str = UNIT_OPERATING,
    clock: Optional[str] = CLOCK_EPOCH_COMPACT,
    **jurisdiction_extra: Any,
) -> Env:
    """An authority, a brand and `unit_count` units, the first one named.

    Twenty `OPERATING` units is the estate depth at which PRD 3.1's unit
    branch is satisfied, so the default leaves the brand one non-exempt item
    away from `COVERED`.
    """
    if clock is not None:
        set_clock(api, clock)
    jurisdiction = make_jurisdiction(
        api,
        code=code,
        name=name,
        preemption_mode=preemption_mode,
        extra_requirement=extra_requirement,
        enforcement_tier=enforcement_tier,
        **jurisdiction_extra,
    )
    brand = make_brand(api)
    establishment = make_establishment(
        api,
        brand_id=brand["id"],
        jurisdiction_id=jurisdiction["id"],
        unit_label=unit_label,
        unit_status=unit_status,
    )
    if unit_count > 1:
        register_unit_batch(
            api,
            brand_id=brand["id"],
            jurisdiction_id=jurisdiction["id"],
            unit_count=unit_count - 1,
            unit_status=unit_status,
            unit_label_prefix=unit_label_prefix,
        )
    return Env(
        api=api,
        jurisdiction=jurisdiction,
        brand=brand,
        establishment=establishment,
    )


# ---------------------------------------------------------------------------
# Menu and recipe builders
# ---------------------------------------------------------------------------
def make_menu_item(
    env: Env,
    name: str = "Grill Sandwich",
    item_class: str = ITEM_CLASS_STANDARD,
    variable_type: str = VARIABLE_NONE,
    first_offered_on: str = "2026-01-05",
) -> Dict[str, Any]:
    return get_success_data(
        env.api.create_menu_item(
            f.menu_item_payload(
                brand_id=env.brand_id,
                name=name,
                item_class=item_class,
                variable_type=variable_type,
                first_offered_on=first_offered_on,
            ),
            env.officer,
        )
    )


def open_recipe_version(
    env: Env,
    menu_item_id: str,
    change_note: str = "Initial specification",
    expected_menu_item_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Open a DRAFT recipe, reading the item's current version as the guard."""
    if expected_menu_item_version is None:
        expected_menu_item_version = env.read_item(menu_item_id)["version"]
    return get_success_data(
        env.api.create_recipe(
            menu_item_id,
            f.recipe_payload(
                expected_menu_item_version=expected_menu_item_version,
                change_note=change_note,
            ),
            env.submitter,
        )
    )


def add_components(
    env: Env, recipe_id: str, components: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    return [
        get_success_data(
            env.api.add_recipe_component(recipe_id, component, env.submitter)
        )
        for component in components
    ]


def submit_recipe(
    env: Env, recipe_id: str, method: str = METHOD_DATABASE
) -> Dict[str, Any]:
    return get_success_data(
        env.api.submit_for_analysis(
            recipe_id, f.submit_for_analysis_payload(method=method), env.submitter
        )
    )


def certify_analysis(
    env: Env, analysis_id: str, decision_note: str = "Database values verified"
) -> Dict[str, Any]:
    """Certify as the second analyst; PRD 3.4 forbids the submitter here."""
    return get_success_data(
        env.api.decide_analysis(
            analysis_id,
            f.analysis_decision_payload(
                decision=DECISION_CERTIFY, decision_note=decision_note
            ),
            env.certifier,
        )
    )


def reject_analysis(
    env: Env,
    analysis_id: str,
    decision_note: str = "Portion weights need rechecking",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        env.api.decide_analysis(
            analysis_id,
            f.analysis_decision_payload(
                decision=DECISION_REJECT, decision_note=decision_note
            ),
            headers or env.certifier,
        )
    )


def certify_recipe_version(
    env: Env,
    menu_item_id: str,
    components: List[Dict[str, Any]],
    change_note: str = "Initial specification",
    method: str = METHOD_DATABASE,
    decision_note: str = "Database values verified",
) -> Dict[str, Any]:
    """Open a recipe version, populate it, submit it and certify it."""
    recipe = open_recipe_version(env, menu_item_id, change_note=change_note)
    add_components(env, recipe["id"], components)
    analysis = submit_recipe(env, recipe["id"], method=method)
    certify_analysis(env, analysis["id"], decision_note=decision_note)
    return {
        "recipe": env.read_recipe(recipe["id"]),
        "analysis": env.read_analysis(analysis["id"]),
    }


def sandwich_components(mayonnaise_grams: Any = 20) -> List[Dict[str, Any]]:
    """The three-component sandwich that declares 530 Cal at 20 g of mayonnaise."""
    return [
        f.chicken_breast_component(),
        f.brioche_bun_component(),
        f.herb_mayonnaise_component(grams=mayonnaise_grams),
    ]


def certified_sandwich(
    env: Env,
    name: str = "Grill Sandwich",
    mayonnaise_grams: Any = 20,
    first_offered_on: str = "2026-01-05",
) -> ItemBundle:
    """A STANDARD item certified at 530 Cal / 550 mg sodium."""
    item = make_menu_item(env, name=name, first_offered_on=first_offered_on)
    result = certify_recipe_version(
        env, item["id"], sandwich_components(mayonnaise_grams=mayonnaise_grams)
    )
    return ItemBundle(
        item=env.read_item(item["id"]),
        recipes=[result["recipe"]],
        analyses=[result["analysis"]],
    )


# ---------------------------------------------------------------------------
# Disclosure packet builders
# ---------------------------------------------------------------------------
def draft_packet(
    env: Env,
    cross_contact_statement: Any = "",
    written_info_channels: Optional[List[str]] = None,
    expected_brand_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Draft an allergen disclosure packet, reading the brand version guard."""
    if expected_brand_version is None:
        expected_brand_version = env.brand_version
    return get_success_data(
        env.api.create_disclosure_packet(
            env.brand_id,
            f.disclosure_packet_payload(
                expected_brand_version=expected_brand_version,
                cross_contact_statement=cross_contact_statement,
                written_info_channels=written_info_channels
                or [CHANNEL_IN_STORE_BINDER, CHANNEL_WEBSITE],
            ),
            env.officer,
        )
    )


def publish_packet(env: Env, packet_id: str) -> Dict[str, Any]:
    return get_success_data(
        env.api.publish_disclosure_packet(packet_id, env.officer)
    )


def draft_and_publish_packet(
    env: Env,
    cross_contact_statement: Any = "",
    written_info_channels: Optional[List[str]] = None,
) -> Dict[str, Any]:
    packet = draft_packet(
        env,
        cross_contact_statement=cross_contact_statement,
        written_info_channels=written_info_channels,
    )
    publish_packet(env, packet["id"])
    return env.read_packet(packet["id"])


# ---------------------------------------------------------------------------
# Menu board builders
# ---------------------------------------------------------------------------
def create_board(
    env: Env,
    board_type: str = BOARD_PRIMARY_MENU_BOARD,
    succinct_statement_variant: str = STATEMENT_FEDERAL_DEFAULT,
    establishment_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> BoardBundle:
    target = establishment_id or env.establishment_id
    board = get_success_data(
        env.api.create_menu_board(
            f.menu_board_payload(
                establishment_id=target,
                board_type=board_type,
                succinct_statement_variant=succinct_statement_variant,
            ),
            headers or make_publisher_headers(target),
        )
    )
    return BoardBundle(board=board)


def add_listing(
    env: Env,
    board_id: str,
    menu_item_id: str,
    sodium_warning_icon: Any = False,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        env.api.create_listing(
            board_id,
            f.listing_payload(
                menu_item_id=menu_item_id, sodium_warning_icon=sodium_warning_icon
            ),
            headers or env.publisher,
        )
    )


def publish_board(
    env: Env,
    board_id: str,
    effective_from: str = CLOCK_EPOCH_COMPACT,
    effective_to: Any = f.OMIT,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        env.api.publish_menu_board(
            board_id,
            f.board_publish_payload(
                effective_from=effective_from, effective_to=effective_to
            ),
            headers or env.publisher,
        )
    )


def listed_board(
    env: Env,
    menu_item_id: str,
    board_type: str = BOARD_PRIMARY_MENU_BOARD,
    succinct_statement_variant: str = STATEMENT_FEDERAL_DEFAULT,
    sodium_warning_icon: Any = False,
) -> BoardBundle:
    """A DRAFT board carrying one listing for `menu_item_id`."""
    bundle = create_board(
        env,
        board_type=board_type,
        succinct_statement_variant=succinct_statement_variant,
    )
    bundle.listings.append(
        add_listing(
            env, bundle.board_id, menu_item_id,
            sodium_warning_icon=sodium_warning_icon,
        )
    )
    bundle.board = env.read_board(bundle.board_id)
    return bundle


def published_board(
    env: Env,
    menu_item_id: str,
    board_type: str = BOARD_PRIMARY_MENU_BOARD,
    succinct_statement_variant: str = STATEMENT_FEDERAL_DEFAULT,
    effective_from: str = CLOCK_EPOCH_COMPACT,
    effective_to: Any = f.OMIT,
    sodium_warning_icon: Any = False,
) -> BoardBundle:
    bundle = listed_board(
        env,
        menu_item_id,
        board_type=board_type,
        succinct_statement_variant=succinct_statement_variant,
        sodium_warning_icon=sodium_warning_icon,
    )
    publish_board(
        env, bundle.board_id, effective_from=effective_from, effective_to=effective_to
    )
    bundle.board = env.read_board(bundle.board_id)
    bundle.listings = [
        env.read_listing(bundle.board_id, line["id"]) for line in bundle.listings
    ]
    return bundle


# ---------------------------------------------------------------------------
# Enforcement builders
# ---------------------------------------------------------------------------
def open_citation(
    env: Env,
    citation_code: str,
    establishment_id: Optional[str] = None,
    inspection_note: Any = "Board shows no calorie declarations",
) -> Dict[str, Any]:
    return get_success_data(
        env.api.create_enforcement_action(
            f.enforcement_action_payload(
                establishment_id=establishment_id or env.establishment_id,
                citation_code=citation_code,
                inspection_note=inspection_note,
            ),
            env.regulator,
        )
    )


def file_response(
    env: Env, action_id: str, response_type: str,
    response_note: Any = "Response filed by the brand",
) -> Dict[str, Any]:
    return get_success_data(
        env.api.create_enforcement_response(
            action_id,
            f.enforcement_response_payload(
                response_type=response_type, response_note=response_note
            ),
            env.officer,
        )
    )


def regulator_action(
    env: Env, action_id: str, action_type: str, penalty_basis: Any = f.OMIT,
    action_note: Any = "Regulator action recorded",
) -> Dict[str, Any]:
    return get_success_data(
        env.api.create_regulator_action(
            action_id,
            f.regulator_action_payload(
                action_type=action_type,
                penalty_basis=penalty_basis,
                action_note=action_note,
            ),
            env.regulator,
        )
    )


# ---------------------------------------------------------------------------
# Variance builders
# ---------------------------------------------------------------------------
def file_variance(
    env: Env,
    requirement_code: str,
    requested_start_date: str = "2026-09-01",
    requested_end_date: str = "2026-09-30",
    justification: str = "Statewide wording change lands later; interim relief asked",
) -> Dict[str, Any]:
    return get_success_data(
        env.api.create_variance_request(
            f.variance_request_payload(
                brand_id=env.brand_id,
                jurisdiction_id=env.jurisdiction_id,
                requirement_code=requirement_code,
                justification=justification,
                requested_start_date=requested_start_date,
                requested_end_date=requested_end_date,
            ),
            env.officer,
        )
    )


def decide_variance(
    env: Env,
    variance_id: str,
    decision: str,
    effective_start_date: Any = f.OMIT,
    effective_end_date: Any = f.OMIT,
    decision_note: Any = "Docketed for review",
) -> Dict[str, Any]:
    return get_success_data(
        env.api.decide_variance_request(
            variance_id,
            f.variance_decision_payload(
                decision=decision,
                decision_note=decision_note,
                effective_start_date=effective_start_date,
                effective_end_date=effective_end_date,
            ),
            env.regulator,
        )
    )


def grant_variance(
    env: Env,
    requirement_code: str,
    requested_start_date: str = "2026-09-01",
    requested_end_date: str = "2026-09-30",
    effective_start_date: Any = f.OMIT,
    effective_end_date: Any = f.OMIT,
) -> Dict[str, Any]:
    """File a variance, open review, then grant it (PRD 3.8's only grant path)."""
    variance = file_variance(
        env,
        requirement_code,
        requested_start_date=requested_start_date,
        requested_end_date=requested_end_date,
    )
    decide_variance(env, variance["id"], VARIANCE_DECISION_OPEN_REVIEW)
    decide_variance(
        env,
        variance["id"],
        VARIANCE_DECISION_GRANTED,
        effective_start_date=effective_start_date,
        effective_end_date=effective_end_date,
    )
    return env.read_variance(variance["id"])


# ---------------------------------------------------------------------------
# Composite scenario
# ---------------------------------------------------------------------------
@dataclass
class PublishedScenario:
    """A covered brand with a certified item, a published packet and a board."""

    env: Env
    item: ItemBundle
    packet: Dict[str, Any]
    board: BoardBundle

    @property
    def api(self) -> ApiClient:
        return self.env.api

    @property
    def item_id(self) -> str:
        return self.item.item_id

    @property
    def board_id(self) -> str:
        return self.board.board_id

    @property
    def packet_id(self) -> str:
        return self.packet["id"]


def build_published_scenario(
    api: ApiClient,
    code: str = "CA-VAR",
    name: str = "California",
    mayonnaise_grams: Any = 20,
    effective_from: str = CLOCK_EPOCH_COMPACT,
    effective_to: Any = f.OMIT,
    **jurisdiction_extra: Any,
) -> PublishedScenario:
    """Walk the whole PRD workflow up to a published board.

    Registry, twenty operating units, one certified STANDARD item, a published
    disclosure packet and a published primary menu board listing that item.
    """
    env = seed_registry(api, code=code, name=name, **jurisdiction_extra)
    item = certified_sandwich(env, mayonnaise_grams=mayonnaise_grams)
    packet = draft_and_publish_packet(env)
    board = published_board(
        env, item.item_id, effective_from=effective_from, effective_to=effective_to
    )
    return PublishedScenario(
        env=env,
        item=ItemBundle(
            item=env.read_item(item.item_id),
            recipes=item.recipes,
            analyses=item.analyses,
        ),
        packet=packet,
        board=board,
    )


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def api() -> ApiClient:
    """A client pointed at the freshly started server for this test."""
    return ApiClient()


@pytest.fixture
def registry(api: ApiClient) -> Env:
    """An authority, a brand and twenty `OPERATING` units, clock at the epoch."""
    return seed_registry(api)


@pytest.fixture
def covered_brand(api: ApiClient) -> Env:
    """A registry whose brand is `COVERED`: twenty units and one standard item."""
    env = seed_registry(api)
    make_menu_item(env)
    return env


@pytest.fixture
def certified_brand(api: ApiClient) -> ItemBundle:
    """A covered brand whose only standard item is certified at 530 Cal.

    The bundle's `item` row is re-read after certification, and the owning
    `Env` is reachable through the module-level builders that produced it.
    """
    env = seed_registry(api)
    bundle = certified_sandwich(env)
    bundle.item = env.read_item(bundle.item_id)
    return bundle


@pytest.fixture
def published_scenario(api: ApiClient) -> PublishedScenario:
    """The full chain: covered brand, certified item, published packet and board."""
    return build_published_scenario(api)
