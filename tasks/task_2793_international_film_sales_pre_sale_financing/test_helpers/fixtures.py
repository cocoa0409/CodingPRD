"""Composite state builders.

Every builder drives only the declared endpoints, in the order the PRD's own
narrative requires, and uses the lenient `get_success_data` so that a setup
failure reports as a setup error rather than as a domain assertion failure.

The builders are layered:

* `pin_clock` and the single-row helpers are the primitives;
* `slate_with_published_valuation` walks the whole engagement chain up to a
  picture that is `IN_MARKET` with one `PUBLISHED` territory valuation;
* `executed_contract_environment` continues to a countersigned contract with its
  four-line milestone schedule and an open collection account;
* the accumulation helpers post receipts, build waterfall tiers, and bond, approve
  and draw a banking facility.
"""

from prd_bench_local_runner.testing import get_success_data

from .constants import (
    AGREEMENT_TERM_START,
    CLOCK_DEFAULT,
    COMP_FEES_DE,
    CONTRACT_MG,
    MILESTONE_SCHEDULE,
    TERRITORY_FR_CODE,
    TERRITORY_FR_INDEX,
)
from .factories import (
    account_payload,
    agreement_payload,
    buyer_payload,
    clock_payload,
    comparable_payload,
    completion_bond_payload,
    contract_payload,
    facility_payload,
    film_payload,
    market_payload,
    milestone_payload,
    publish_payload,
    receipt_payload,
    state_payload,
    territory_payload,
    tier_payload,
    valuation_payload,
)
from .test_users import (
    COLLECTION_AGENT_USER,
    HEAD_OF_SALES_CLOSER,
    HEAD_OF_SALES_USER,
    HEAD_OF_SALES_VALUER,
    LENDER_APPROVER,
    LENDER_DRAWER,
    LENDER_USER,
    make_buyer_headers,
    make_collection_agent_headers,
    make_head_of_sales_headers,
    make_lender_headers,
    make_platform_admin_headers,
    make_sales_agent_headers,
)

# Three verified in-genre comparables whose release years all sit inside the
# seven-year lookback from the default clock reading.
COMP_YEARS_DE = (2022, 2023, 2024)


# --------------------------------------------------------------------------
# Tier 1 - primitives
# --------------------------------------------------------------------------
def pin_clock(api, instant=CLOCK_DEFAULT):
    """Move the logical clock, which only a PlatformAdmin may do."""
    return get_success_data(
        api.set_clock(clock_payload(instant), make_platform_admin_headers())
    )


def make_film(api, **overrides):
    return get_success_data(
        api.create_film(film_payload(**overrides), make_platform_admin_headers())
    )


def make_territory(api, **overrides):
    return get_success_data(
        api.create_territory(territory_payload(**overrides), make_platform_admin_headers())
    )


def make_fr_territory(api, **overrides):
    return make_territory(
        api,
        code=TERRITORY_FR_CODE,
        name="France",
        currency_code="EUR",
        base_value_index=TERRITORY_FR_INDEX,
        **overrides,
    )


def make_comparables(api, territory_id, fees=COMP_FEES_DE, years=COMP_YEARS_DE, **overrides):
    """Record one verified comparable per fee, each inside the lookback window."""
    rows = []
    for index, fee in enumerate(fees):
        year = years[index % len(years)]
        rows.append(
            get_success_data(
                api.create_comparable_title(
                    territory_id,
                    comparable_payload(
                        fee, year, name=f"Comparable {index + 1}", **overrides
                    ),
                    make_platform_admin_headers(),
                )
            )
        )
    return rows


def make_buyer(api, territory_id, **overrides):
    return get_success_data(
        api.create_buyer(
            territory_id, buyer_payload(**overrides), make_platform_admin_headers()
        )
    )


def make_agreement(api, film_id, **overrides):
    return get_success_data(
        api.create_agency_agreement(
            film_id, agreement_payload(**overrides), make_head_of_sales_headers()
        )
    )


def execute_agreement(api, agreement_id, as_user_id=HEAD_OF_SALES_USER):
    return get_success_data(
        api.set_agency_agreement_state(
            agreement_id,
            state_payload("EXECUTED"),
            make_head_of_sales_headers(as_user_id),
        )
    )


def make_market(api, **overrides):
    return get_success_data(
        api.create_market(market_payload(**overrides), make_platform_admin_headers())
    )


def open_market(api, market_id):
    return get_success_data(
        api.set_market_state(market_id, state_payload("OPEN"), make_platform_admin_headers())
    )


def make_account(api, film_id, **overrides):
    return get_success_data(
        api.create_collection_account(
            film_id, account_payload(**overrides), make_collection_agent_headers()
        )
    )


def read_film(api, film_id):
    return get_success_data(api.get_film(film_id, make_platform_admin_headers()))


def read_buyer(api, buyer_id):
    return get_success_data(api.get_buyer(buyer_id, make_platform_admin_headers()))


def read_contract(api, contract_id):
    return get_success_data(api.get_contract(contract_id, make_sales_agent_headers()))


def read_account(api, account_id):
    return get_success_data(
        api.get_collection_account(account_id, make_collection_agent_headers())
    )


def read_valuation(api, valuation_id):
    return get_success_data(api.get_valuation(valuation_id, make_sales_agent_headers()))


def read_agreement(api, film_id, agreement_id):
    rows = get_success_data(
        api.list_agency_agreements(film_id, make_head_of_sales_headers())
    )
    for row in rows:
        if row["id"] == agreement_id:
            return row
    raise AssertionError(f"Setup step failed: agreement {agreement_id} not listed")


def read_milestones(api, contract_id):
    return get_success_data(
        api.list_milestones(contract_id, make_sales_agent_headers(), {"limit": 100})
    )


def read_tiers(api, account_id):
    return get_success_data(
        api.list_waterfall_tiers(account_id, make_collection_agent_headers(), {"limit": 100})
    )


def read_facilities(api, film_id):
    return get_success_data(
        api.list_banking_facilities(film_id, make_lender_headers(), {"limit": 100})
    )


def read_facility(api, film_id, facility_id):
    for row in read_facilities(api, film_id):
        if row["id"] == facility_id:
            return row
    raise AssertionError(f"Setup step failed: facility {facility_id} not listed")


# --------------------------------------------------------------------------
# Tier 2 - the engagement chain
# --------------------------------------------------------------------------
def engaged_slate(api, clock=CLOCK_DEFAULT, film_overrides=None, agreement_overrides=None):
    """A registered picture with an EXECUTED agency agreement, still DEVELOPMENT."""
    pin_clock(api, clock)
    film = make_film(api, **(film_overrides or {}))
    agreement = make_agreement(api, film["id"], **(agreement_overrides or {}))
    agreement = execute_agreement(api, agreement["id"])
    return {"film": film, "agreement": agreement}


def packaged_slate(api, **kwargs):
    """The picture advanced DEVELOPMENT -> PACKAGING, which needs the executed
    agreement."""
    env = engaged_slate(api, **kwargs)
    env["film"] = get_success_data(
        api.set_film_state(
            env["film"]["id"], state_payload("PACKAGING"), make_platform_admin_headers()
        )
    )
    return env


def valued_slate(
    api,
    method="CAST_ADJUSTED",
    clock=CLOCK_DEFAULT,
    film_overrides=None,
    agreement_overrides=None,
    territory_overrides=None,
    buyer_overrides=None,
    comp_fees=COMP_FEES_DE,
    comp_years=COMP_YEARS_DE,
):
    """A PACKAGING picture, a territory with three verified comparables, a buyer,
    and a DRAFT valuation on that film-and-territory pair."""
    env = packaged_slate(
        api,
        clock=clock,
        film_overrides=film_overrides,
        agreement_overrides=agreement_overrides,
    )
    territory = make_territory(api, **(territory_overrides or {}))
    comparables = make_comparables(api, territory["id"], comp_fees, comp_years)
    buyer = make_buyer(api, territory["id"], **(buyer_overrides or {}))
    valuation = get_success_data(
        api.create_valuation(
            valuation_payload(env["film"]["id"], territory["id"], method),
            make_sales_agent_headers(),
        )
    )
    env.update(
        {
            "territory": territory,
            "comparables": comparables,
            "buyer": buyer,
            "valuation": valuation,
        }
    )
    return env


def slate_with_published_valuation(api, valuer=HEAD_OF_SALES_VALUER, **kwargs):
    """The valuation published and the picture moved PACKAGING -> IN_MARKET.

    The film version is read immediately before publication so that the
    publication carries the matching `expected_film_version`.
    """
    env = valued_slate(api, **kwargs)
    film_version = read_film(api, env["film"]["id"])["version"]
    env["film_version_at_publish"] = film_version
    env["valuation"] = get_success_data(
        api.publish_valuation(
            env["valuation"]["id"],
            publish_payload(film_version),
            make_head_of_sales_headers(valuer),
        )
    )
    env["film"] = get_success_data(
        api.set_film_state(
            env["film"]["id"], state_payload("IN_MARKET"), make_head_of_sales_headers()
        )
    )
    return env


# --------------------------------------------------------------------------
# Tier 3 - the negotiation chain
# --------------------------------------------------------------------------
def offered_contract(api, env=None, minimum_guarantee_usd=CONTRACT_MG, **kwargs):
    """An OFFERED contract on the canonical slate."""
    if env is None:
        env = slate_with_published_valuation(api, **kwargs)
    buyer_version = read_buyer(api, env["buyer"]["id"])["version"]
    env["buyer_version_at_offer"] = buyer_version
    env["contract"] = get_success_data(
        api.create_contract(
            contract_payload(
                env["film"]["id"],
                env["buyer"]["id"],
                env["territory"]["id"],
                buyer_version,
                minimum_guarantee_usd=minimum_guarantee_usd,
            ),
            make_sales_agent_headers(),
        )
    )
    return env


def add_milestone_schedule(api, contract_id, schedule=MILESTONE_SCHEDULE):
    """Add the four-line schedule whose pct_of_mg shares sum to exactly 1.0000."""
    rows = []
    for label, pct, due_date, _amount in schedule:
        rows.append(
            get_success_data(
                api.create_milestone(
                    contract_id,
                    milestone_payload(label, pct, due_date),
                    make_sales_agent_headers(),
                )
            )
        )
    return rows


def accepted_contract(api, env=None, with_milestones=True, **kwargs):
    """The offer accepted by the contract's own buyer, with the schedule complete."""
    if env is None or "contract" not in env:
        env = offered_contract(api, env, **kwargs)
    if with_milestones:
        env["milestones"] = add_milestone_schedule(api, env["contract"]["id"])
    env["contract"] = get_success_data(
        api.accept_contract(env["contract"]["id"], make_buyer_headers(env["buyer"]["id"]))
    )
    return env


def executed_contract(api, env=None, closer=HEAD_OF_SALES_CLOSER, **kwargs):
    """The contract countersigned by a HeadOfSales who is not the publisher."""
    if env is None or env.get("contract", {}).get("negotiation_status") != "ACCEPTED":
        env = accepted_contract(api, env, **kwargs)
    env["contract"] = get_success_data(
        api.execute_contract(env["contract"]["id"], make_head_of_sales_headers(closer))
    )
    env["milestones"] = read_milestones(api, env["contract"]["id"])
    return env


def executed_contract_environment(api, env=None, **kwargs):
    """The canonical environment: an EXECUTED contract, its four milestones, and an
    OPEN collection account on the picture."""
    env = executed_contract(api, env, **kwargs)
    env["account"] = make_account(api, env["film"]["id"])
    env["milestones"] = read_milestones(api, env["contract"]["id"])
    return env


def milestone_by_label(env_or_rows, label):
    rows = env_or_rows["milestones"] if isinstance(env_or_rows, dict) else env_or_rows
    for row in rows:
        if row["label"] == label:
            return row
    raise AssertionError(f"Setup step failed: no milestone labelled {label}")


# --------------------------------------------------------------------------
# Tier 4 - accumulation and threshold targeting
# --------------------------------------------------------------------------
def post_receipt(api, milestone, received_at, as_user_id=COLLECTION_AGENT_USER):
    """Book a receipt for exactly the milestone's own amount."""
    return get_success_data(
        api.post_receipt(
            milestone["id"],
            receipt_payload(milestone["amount_usd"], received_at),
            make_collection_agent_headers(as_user_id),
        )
    )


def post_receipts(api, env, labels_and_dates):
    """Post a sequence of receipts in the order given; the commission band each one
    lands in depends on that arrival order."""
    posted = []
    for label, received_at in labels_and_dates:
        milestone = milestone_by_label(read_milestones(api, env["contract"]["id"]), label)
        posted.append(post_receipt(api, milestone, received_at))
    env["receipts"] = posted
    return posted


def make_tiers(api, account_id, specs):
    """Create waterfall tiers from (tier_order, tier_type, pct_of_available, cap) tuples."""
    rows = []
    for tier_order, tier_type, pct, cap in specs:
        rows.append(
            get_success_data(
                api.create_waterfall_tier(
                    account_id,
                    tier_payload(tier_order, tier_type, pct, cap),
                    make_collection_agent_headers(),
                )
            )
        )
    return rows


def make_facility(api, film_id, **overrides):
    return get_success_data(
        api.create_banking_facility(
            film_id, facility_payload(**overrides), make_lender_headers()
        )
    )


def bond_facility(api, facility_id, **overrides):
    return get_success_data(
        api.post_completion_bond(
            facility_id, completion_bond_payload(**overrides), make_lender_headers()
        )
    )


def approve_facility(api, facility_id, as_user_id=LENDER_APPROVER):
    return get_success_data(
        api.set_facility_state(
            facility_id, state_payload("APPROVED"), make_lender_headers(as_user_id)
        )
    )


def draw_facility(api, facility_id, as_user_id=LENDER_DRAWER):
    """Drawing requires an identity different from the approving officer's."""
    return get_success_data(
        api.set_facility_state(
            facility_id, state_payload("DRAWN"), make_lender_headers(as_user_id)
        )
    )


def drawn_facility(api, env, **overrides):
    """A bonded, approved and drawn facility against the canonical contract."""
    facility = make_facility(api, env["film"]["id"], **overrides)
    bond_facility(api, facility["id"])
    approve_facility(api, facility["id"])
    env["facility"] = draw_facility(api, facility["id"])
    return env["facility"]


# --------------------------------------------------------------------------
# Tier 5 - delivery and finalisation
# --------------------------------------------------------------------------
def submit_package(api, contract_id, technical=14, legal=6):
    from .factories import package_payload
    from .test_users import make_delivery_manager_headers

    return get_success_data(
        api.create_deliverable_package(
            contract_id,
            package_payload(technical, legal),
            make_delivery_manager_headers(),
        )
    )


def record_qc_fail(api, package_id, buyer_id, rejection_reason="QC_FAIL"):
    from .factories import qc_fail_payload

    return get_success_data(
        api.post_qc_result(
            package_id, qc_fail_payload(rejection_reason), make_buyer_headers(buyer_id)
        )
    )


def record_qc_pass(api, package_id, buyer_id):
    from .factories import qc_pass_payload

    return get_success_data(
        api.post_qc_result(package_id, qc_pass_payload(), make_buyer_headers(buyer_id))
    )


def open_market_with_buyers(api, env=None, **kwargs):
    """An OPEN market plus two buyers in the same territory, for the occupancy rules."""
    if env is None:
        env = slate_with_published_valuation(api, **kwargs)
    market = make_market(api)
    env["market"] = open_market(api, market["id"])
    env["buyer_alt"] = make_buyer(
        api, env["territory"]["id"], company_name="Nordic Media"
    )
    return env


AGREEMENT_START = AGREEMENT_TERM_START
