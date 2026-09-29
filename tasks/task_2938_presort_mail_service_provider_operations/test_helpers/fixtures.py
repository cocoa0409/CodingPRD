"""Composite world builders for the presort bureau API.

The harness restarts the server before every single test, so each test opens
against an empty database and has to build whatever history it needs. Almost
every interesting behaviour in this domain sits several steps downstream of an
empty database — a postage statement cannot exist until two clients, two permit
accounts, an entry facility, two hygiene-cleared mail jobs, a commingle batch
with two members and two containers, and a completed sort all exist first.

Rather than repeating that ramp, the builders here expose the canonical world at
each stage it becomes interesting, each one extending the previous:

    pooled -> sorted -> submitted -> accepted+departed -> deposited -> scanned

plus a handful of small single-purpose worlds for behaviours that need a
different shape entirely (a closed facility, a permit account on hold, a
first-class job, a facility with four empty batches).

Every builder uses the lenient success reader, because a builder's job is to get
history on disk, not to assert on it; the tests do the asserting.

Canonical arithmetic of the two-client world, so that the literals in the tests
can be checked against the setup without re-deriving them:

    MARKETING_MAIL base rate  = 32 cents per piece
    SCF-021 drop_ship_discount_bp = 300
    job A: 1250 declared, 50 undeliverable -> 1200 accepted, quality 98.80
    job B: 1850 declared, 50 undeliverable -> 1800 accepted, quality 98.92
    pooled volume 3000 -> THREE_DIGIT tier (discount 1500 bp)
    rate  = floor(32 * 1000 * 8500 * 9700 / 100000000) = 26384 mills
    batch = round_half_up(3000 * 26384 / 1000)         = 79152 cents
    pro rata of 79152 over 1200 and 1800:
        floors 31660 and 47491, one remainder cent to the larger contributor
        -> A 31660, B 47492
    standalone, with the drop-ship discount forced to zero and BASIC at 800 bp:
        rate 29440 mills; A 35328 cents, B 52992 cents; 88320 together
"""

from typing import Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as f
from test_helpers.api_client import ApiClient
from test_helpers.constants import FIXTURE_CLOCK_UTC
from test_helpers.test_users import (
    ACCEPTANCE_CLERK,
    BUREAU_ADMIN,
    POSTAGE_MANAGER,
    PRESORT_OPERATOR,
)

# ─── Canonical figures of the two-client world ────────────────────────────

JOB_A_DECLARED = 1250
JOB_A_ACCEPTED = 1200
JOB_A_QUALITY_PCT = 98.80
JOB_B_DECLARED = 1850
JOB_B_ACCEPTED = 1800
JOB_B_QUALITY_PCT = 98.92

POOLED_PIECES = 3000
POOLED_TIER = "THREE_DIGIT"
POOLED_RATE_MILLS = 26384
POOLED_POSTAGE_CENTS = 79152
MEMBER_A_POSTAGE_CENTS = 31660
MEMBER_B_POSTAGE_CENTS = 47492
MEMBER_A_SHARE_PCT = 40.0000
MEMBER_B_SHARE_PCT = 60.0000

STANDALONE_TIER = "BASIC"
STANDALONE_RATE_MILLS = 29440
STANDALONE_A_CENTS = 35328
STANDALONE_B_CENTS = 52992

HOUSE_FUNDING_CENTS = 200000
EXACT_FUNDING_CENTS = POOLED_POSTAGE_CENTS

CONTAINER_1_PIECES = 1000
CONTAINER_2_PIECES = 2000
CONTAINER_1_ZIP3 = "021"
CONTAINER_2_ZIP3 = "941"

FACILITY_CODE = "SCF-021"
FACILITY_DISCOUNT_BP = 300
FACILITY_DOCK_CAPACITY = 12


class World(dict):
    """A bag of ids and captured versions with attribute access."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:  # pragma: no cover - developer error only
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


# ─── Primitive steps ──────────────────────────────────────────────────────


def set_clock(api: ApiClient, to_iso8601: str) -> Dict:
    return get_success_data(api.set_clock(to_iso8601, BUREAU_ADMIN))


def create_client(api: ApiClient, payload: Dict) -> Dict:
    return get_success_data(api.create_client(payload, BUREAU_ADMIN))


def create_permit_account(api: ApiClient, payload: Dict) -> Dict:
    return get_success_data(api.create_permit_account(payload, POSTAGE_MANAGER))


def fund_permit_account(
    api: ApiClient, permit_account_id: str, amount_cents: int, reference: str
) -> Dict:
    current = get_success_data(api.get_permit_account(permit_account_id, POSTAGE_MANAGER))
    return get_success_data(
        api.fund_permit_account(
            permit_account_id,
            f.funding_payload(amount_cents, current["version"], reference),
            POSTAGE_MANAGER,
        )
    )


def create_entry_facility(api: ApiClient, payload: Dict) -> Dict:
    return get_success_data(api.create_entry_facility(payload, BUREAU_ADMIN))


def create_mail_job(api: ApiClient, payload: Dict) -> Dict:
    return get_success_data(api.create_mail_job(payload, PRESORT_OPERATOR))


def create_hygiene_run(api: ApiClient, mail_job_id: str, payload: Dict) -> Dict:
    return get_success_data(
        api.create_hygiene_run(mail_job_id, payload, PRESORT_OPERATOR)
    )


def read_mail_job(api: ApiClient, mail_job_id: str) -> Dict:
    """Re-read a job so a builder can hand back its current state rather than
    the snapshot the creation call returned."""
    return get_success_data(api.get_mail_job(mail_job_id, PRESORT_OPERATOR))


def create_batch(api: ApiClient, payload: Dict) -> Dict:
    return get_success_data(api.create_commingle_batch(payload, PRESORT_OPERATOR))


def add_member(api: ApiClient, batch_id: str, mail_job_id: str) -> Dict:
    return get_success_data(
        api.add_batch_member(batch_id, f.batch_member_payload(mail_job_id), PRESORT_OPERATOR)
    )


def add_container(api: ApiClient, batch_id: str, payload: Dict) -> Dict:
    return get_success_data(api.add_sort_container(batch_id, payload, PRESORT_OPERATOR))


def sort_batch(api: ApiClient, batch_id: str) -> Dict:
    return get_success_data(api.sort_batch(batch_id, PRESORT_OPERATOR))


def batch_version(api: ApiClient, batch_id: str) -> int:
    return get_success_data(api.get_commingle_batch(batch_id, PRESORT_OPERATOR))["version"]


def create_statement(
    api: ApiClient, batch_id: str, permit_account_id: str, expected_batch_version: int
) -> Dict:
    return get_success_data(
        api.create_postage_statement(
            f.postage_statement_payload(
                batch_id, permit_account_id, expected_batch_version
            ),
            POSTAGE_MANAGER,
        )
    )


def submit_statement(api: ApiClient, statement_id: str) -> Dict:
    return get_success_data(api.submit_postage_statement(statement_id, POSTAGE_MANAGER))


def add_finding(api: ApiClient, statement_id: str, payload: Dict) -> Dict:
    return get_success_data(api.create_finding(statement_id, payload, ACCEPTANCE_CLERK))


def verify_statement(api: ApiClient, statement_id: str, outcome: str) -> Dict:
    return get_success_data(
        api.verify_postage_statement(statement_id, f.verify_payload(outcome), ACCEPTANCE_CLERK)
    )


def revise_statement(api: ApiClient, statement_id: str) -> Dict:
    return get_success_data(api.revise_postage_statement(statement_id, POSTAGE_MANAGER))


def create_drop_shipment(api: ApiClient, payload: Dict) -> Dict:
    return get_success_data(api.create_drop_shipment(payload, PRESORT_OPERATOR))


def depart_drop_shipment(api: ApiClient, drop_shipment_id: str) -> Dict:
    return get_success_data(api.depart_drop_shipment(drop_shipment_id, PRESORT_OPERATOR))


def deposit_drop_shipment(api: ApiClient, drop_shipment_id: str) -> Dict:
    return get_success_data(api.deposit_drop_shipment(drop_shipment_id, ACCEPTANCE_CLERK))


def list_container_records(api: ApiClient, sort_container_id: str) -> List[Dict]:
    rows = get_success_data(
        api.list_container_service_level_records(sort_container_id, ACCEPTANCE_CLERK)
    )
    assert isinstance(rows, list), f"a list response carries an array in data, got {rows!r}"
    return rows


def record_delivery_scan(
    api: ApiClient, service_level_record_id: str, days: int, scanned_at_utc: str
) -> Dict:
    return get_success_data(
        api.record_delivery_scan(
            service_level_record_id,
            f.delivery_scan_payload(days, scanned_at_utc),
            ACCEPTANCE_CLERK,
        )
    )


def _remember(world: World, name: str, resource: Dict) -> Dict:
    """Keep both the resource and its id under readable names."""
    world[name] = resource
    world[f"{name}_id"] = resource["id"]
    return resource


# ─── The canonical two-client world, stage by stage ────────────────────────


def build_pooled_world(api: ApiClient) -> World:
    """Two clients, two permit accounts, one SCF entry facility, two
    hygiene-cleared mail jobs pooled into one commingle batch, and two sort
    containers staged against it. The batch has not been sorted, so it is still
    OPEN: membership has priced it provisionally at the pooled tier, rate and
    postage, but none of those figures is frozen yet.
    """
    world = World()
    set_clock(api, FIXTURE_CLOCK_UTC)

    _remember(world, "acme", create_client(api, f.ACME_CLIENT))
    _remember(world, "bore", create_client(api, f.BORE_CLIENT))

    _remember(
        world,
        "permit_a",
        create_permit_account(
            api,
            f.permit_account_payload(
                world.acme_id, permit_number="PI-100100", payment_method="PERMIT_IMPRINT"
            ),
        ),
    )
    _remember(
        world,
        "permit_b",
        create_permit_account(
            api,
            f.permit_account_payload(
                world.bore_id, permit_number="PI-200200", payment_method="METER"
            ),
        ),
    )

    _remember(world, "facility", create_entry_facility(api, f.entry_facility_payload()))

    _remember(
        world,
        "job_a",
        create_mail_job(
            api,
            f.mail_job_payload(
                world.acme_id,
                world.permit_a_id,
                declared_piece_count=JOB_A_DECLARED,
                declared_weight_oz_per_piece=1.2,
            ),
        ),
    )
    _remember(
        world,
        "hygiene_a",
        create_hygiene_run(
            api,
            world.job_a_id,
            f.hygiene_run_payload(
                submitted_piece_count=1250,
                cass_matched_count=1235,
                ncoa_move_updated_count=40,
                undeliverable_removed_count=50,
                move_update_age_days=30,
            ),
        ),
    )

    _remember(
        world,
        "job_b",
        create_mail_job(
            api,
            f.mail_job_payload(
                world.bore_id,
                world.permit_b_id,
                declared_piece_count=JOB_B_DECLARED,
                declared_weight_oz_per_piece=1.1,
            ),
        ),
    )
    _remember(
        world,
        "hygiene_b",
        create_hygiene_run(
            api,
            world.job_b_id,
            f.hygiene_run_payload(
                submitted_piece_count=1850,
                cass_matched_count=1830,
                ncoa_move_updated_count=55,
                undeliverable_removed_count=50,
                move_update_age_days=20,
            ),
        ),
    )

    _remember(
        world,
        "batch",
        create_batch(api, f.commingle_batch_payload(world.facility_id)),
    )
    _remember(world, "member_a", add_member(api, world.batch_id, world.job_a_id))
    _remember(world, "member_b", add_member(api, world.batch_id, world.job_b_id))

    _remember(
        world,
        "container_1",
        add_container(
            api,
            world.batch_id,
            f.sort_container_payload(
                container_type="TRAY",
                destination_zip3=CONTAINER_1_ZIP3,
                sort_level="FIVE_DIGIT",
                piece_count=CONTAINER_1_PIECES,
            ),
        ),
    )
    _remember(
        world,
        "container_2",
        add_container(
            api,
            world.batch_id,
            f.sort_container_payload(
                container_type="TRAY",
                destination_zip3=CONTAINER_2_ZIP3,
                sort_level="THREE_DIGIT",
                piece_count=CONTAINER_2_PIECES,
            ),
        ),
    )
    return world


def build_member_a_only_world(api: ApiClient) -> World:
    """The canonical world stopped one step earlier: both jobs exist and are
    hygiene-cleared, but only job A has been pooled, and no containers have been
    staged. The batch therefore holds exactly one member and 1200 pieces.
    """
    world = World()
    set_clock(api, FIXTURE_CLOCK_UTC)

    _remember(world, "acme", create_client(api, f.ACME_CLIENT))
    _remember(world, "bore", create_client(api, f.BORE_CLIENT))
    _remember(
        world,
        "permit_a",
        create_permit_account(
            api, f.permit_account_payload(world.acme_id, permit_number="PI-100100")
        ),
    )
    _remember(
        world,
        "permit_b",
        create_permit_account(
            api,
            f.permit_account_payload(
                world.bore_id, permit_number="PI-200200", payment_method="METER"
            ),
        ),
    )
    _remember(world, "facility", create_entry_facility(api, f.entry_facility_payload()))
    _remember(
        world,
        "job_a",
        create_mail_job(
            api,
            f.mail_job_payload(
                world.acme_id,
                world.permit_a_id,
                declared_piece_count=JOB_A_DECLARED,
                declared_weight_oz_per_piece=1.2,
            ),
        ),
    )
    create_hygiene_run(
        api,
        world.job_a_id,
        f.hygiene_run_payload(1250, 1235, 40, 50, 30),
    )
    _remember(
        world,
        "job_b",
        create_mail_job(
            api,
            f.mail_job_payload(
                world.bore_id,
                world.permit_b_id,
                declared_piece_count=JOB_B_DECLARED,
                declared_weight_oz_per_piece=1.1,
            ),
        ),
    )
    create_hygiene_run(
        api,
        world.job_b_id,
        f.hygiene_run_payload(1850, 1830, 55, 50, 20),
    )
    _remember(world, "batch", create_batch(api, f.commingle_batch_payload(world.facility_id)))
    _remember(world, "member_a", add_member(api, world.batch_id, world.job_a_id))
    return world


def build_sorted_world(api: ApiClient) -> World:
    """The canonical world with the sort completed: the batch is SORTED at the
    THREE_DIGIT tier, priced at 26384 mills and 79152 cents, its two members
    hold their pro rata allocations, and both containers carry placards. The
    batch version observed straight after the sort is kept as ``batch_v1``.
    """
    world = build_pooled_world(api)
    sort_batch(api, world.batch_id)
    world.batch_v1 = batch_version(api, world.batch_id)
    return world


def add_house_account(api: ApiClient, world: World) -> World:
    """The bureau's own house client and permit account.

    A commingled statement is filed against one permit account for the whole
    pooled volume, and that account has to belong to somebody. Using a third,
    bureau-owned client keeps the two mailing clients' own accounts untouched, so
    a test can watch the funds move on the paying account without wondering
    whether a mailer's own balance was also debited.
    """
    _remember(world, "house", create_client(api, f.HOUSE_CLIENT))
    _remember(
        world,
        "permit_house",
        create_permit_account(
            api,
            f.permit_account_payload(
                world.house_id, permit_number="PI-900900", payment_method="PERMIT_IMPRINT"
            ),
        ),
    )
    return world


def build_open_funded_world(api: ApiClient) -> World:
    """The pooled world plus a funded house permit account, with the batch left
    unsorted. The batch version observed while it is still OPEN is kept as
    ``batch_v_open`` so a statement filing can quote a version that is correct
    and still be refused for the batch's state.
    """
    world = build_pooled_world(api)
    add_house_account(api, world)
    fund_permit_account(api, world.permit_house_id, HOUSE_FUNDING_CENTS, "WIRE-8811")
    world.batch_v_open = batch_version(api, world.batch_id)
    return world


def build_submitted_world(
    api: ApiClient,
    funding_cents: int = HOUSE_FUNDING_CENTS,
    reference: str = "WIRE-8811",
) -> World:
    """The sorted world with a postage statement filed against the funded house
    permit account and submitted, so 79152 cents sit reserved awaiting
    verification. Passing ``funding_cents`` equal to the declared postage puts
    the account on the exact equality boundary of the sufficient-funds test.
    """
    world = build_sorted_world(api)
    add_house_account(api, world)
    world.funded_cents = funding_cents
    fund_permit_account(api, world.permit_house_id, funding_cents, reference)
    _remember(
        world,
        "statement",
        create_statement(api, world.batch_id, world.permit_house_id, world.batch_v1),
    )
    submit_statement(api, world.statement_id)
    return world


def build_accepted_world(api: ApiClient) -> World:
    """The submitted world with the statement verified as ACCEPT, so the
    reserved postage has been captured and the batch is DOCUMENTED."""
    world = build_submitted_world(api)
    verify_statement(api, world.statement_id, "ACCEPT")
    return world


SHIPMENT_WINDOW_START = f.instant(2026, 8, 12, 8, 0, 0)
SHIPMENT_WINDOW_END = f.instant(2026, 8, 12, 16, 0, 0)
DEPOSIT_CLOCK_UTC = f.instant(2026, 8, 12, 14, 0, 0)
SCAN_CLOCK_ON_TIME = f.instant(2026, 8, 14, 10, 0, 0)
SCAN_CLOCK_LATE = f.instant(2026, 8, 21, 10, 0, 0)


def build_departed_world(api: ApiClient) -> World:
    """The accepted world with a two-pallet appointment booked for the
    half-open window 08:00 to 16:00 on 12 August, the clock advanced into that
    window at 14:00, and the shipment departed. Everything is now in place for a
    deposit except the deposit itself.
    """
    world = build_accepted_world(api)
    _remember(
        world,
        "shipment",
        create_drop_shipment(
            api,
            f.drop_shipment_payload(
                world.batch_id,
                world.facility_id,
                SHIPMENT_WINDOW_START,
                SHIPMENT_WINDOW_END,
                pallet_count=2,
            ),
        ),
    )
    set_clock(api, DEPOSIT_CLOCK_UTC)
    depart_drop_shipment(api, world.shipment_id)
    return world


def build_deposited_world(api: ApiClient) -> World:
    """The departed world with the deposit recorded at 14:00 on 12 August: the
    batch is CLOSED, both containers are DEPOSITED, both jobs are MAILED, and one
    service-level record now exists per container. Those two records are looked up
    straight away and kept as ``slr_1`` and ``slr_2``, so a caller never has to
    walk back from the containers itself.
    """
    world = build_departed_world(api)
    deposit_drop_shipment(api, world.shipment_id)
    records_1 = list_container_records(api, world.container_1_id)
    records_2 = list_container_records(api, world.container_2_id)
    world.slr_1 = records_1[0]
    world.slr_1_id = records_1[0]["id"]
    world.slr_2 = records_2[0]
    world.slr_2_id = records_2[0]["id"]
    return world


def build_scanned_world(api: ApiClient) -> World:
    """The deposited world with a delivery scan on each service-level record:
    the 021 tray delivered in 2 days against a 4-day commitment, and the 941 tray
    in 9 days against a 7-day commitment. One record is on time and one is not,
    which is what makes the two weighted indices differ.
    """
    world = build_deposited_world(api)
    record_delivery_scan(api, world.slr_1_id, 2, SCAN_CLOCK_ON_TIME)
    record_delivery_scan(api, world.slr_2_id, 9, SCAN_CLOCK_LATE)
    return world


def build_second_cycle_submitted_world(api: ApiClient) -> World:
    """The submitted world driven once around the rework loop and back to
    SUBMITTED: one container-qualification finding covering 90 pieces, a RETURN
    verdict, a revision, a fresh sort and a fresh submission. Both mailing jobs
    now carry a rework count of 1 and the statement sits at revision index 1, so
    a second RETURN drives each job to its second rework.
    """
    world = build_submitted_world(api)
    add_finding(
        api,
        world.statement_id,
        f.finding_payload(finding_type="CONTAINER_NOT_QUALIFIED", affected_piece_count=90),
    )
    verify_statement(api, world.statement_id, "RETURN")
    revise_statement(api, world.statement_id)
    sort_batch(api, world.batch_id)
    submit_statement(api, world.statement_id)
    return world


# ─── Single-purpose worlds ────────────────────────────────────────────────


def build_first_class_world(api: ApiClient) -> World:
    """One client with a FIRST_CLASS job whose only hygiene run used
    move-update data 120 days old, and an open MARKETING_MAIL batch to try to
    pool it into. The job is doubly ineligible — stale move update and the wrong
    mail class — which is what makes it useful for ordering the two refusals.
    """
    world = World()
    set_clock(api, FIXTURE_CLOCK_UTC)
    _remember(
        world,
        "cargo",
        create_client(
            api,
            f.client_payload(
                name="Cargo Mail Co",
                client_code="CARGO",
                service_fee_rate_per_thousand_cents=1500,
            ),
        ),
    )
    _remember(
        world,
        "permit_c",
        create_permit_account(
            api, f.permit_account_payload(world.cargo_id, permit_number="PI-300300")
        ),
    )
    _remember(world, "facility", create_entry_facility(api, f.entry_facility_payload()))
    _remember(
        world,
        "job_c",
        create_mail_job(
            api,
            f.mail_job_payload(
                world.cargo_id,
                world.permit_c_id,
                mail_class="FIRST_CLASS",
                processing_category="LETTERS",
                declared_piece_count=1000,
                declared_weight_oz_per_piece=0.9,
            ),
        ),
    )
    _remember(
        world,
        "hygiene_c",
        create_hygiene_run(
            api,
            world.job_c_id,
            f.hygiene_run_payload(
                submitted_piece_count=1000,
                cass_matched_count=990,
                ncoa_move_updated_count=25,
                undeliverable_removed_count=40,
                move_update_age_days=120,
            ),
        ),
    )
    _remember(
        world, "batch", create_batch(api, f.commingle_batch_payload(world.facility_id))
    )
    return world


def build_closed_facility_world(api: ApiClient) -> World:
    """A DDU facility whose dock holds only 4 pallets, two empty batches, an
    appointment that already fills the dock over 10:00 to 14:00 on 12 August, and
    the facility then closed. A second booking is refusable on two independent
    grounds at once.
    """
    world = World()
    set_clock(api, FIXTURE_CLOCK_UTC)
    _remember(
        world,
        "facility",
        create_entry_facility(
            api,
            f.entry_facility_payload(
                facility_code="DDU-021",
                facility_type="DDU",
                zip3="021",
                dock_capacity_pallets_per_slot=4,
                drop_ship_discount_bp=500,
                served_zip3_list=["021"],
            ),
        ),
    )
    _remember(
        world, "batch_1", create_batch(api, f.commingle_batch_payload(world.facility_id))
    )
    _remember(
        world, "batch_2", create_batch(api, f.commingle_batch_payload(world.facility_id))
    )
    _remember(
        world,
        "shipment_1",
        create_drop_shipment(
            api,
            f.drop_shipment_payload(
                world.batch_1_id,
                world.facility_id,
                f.instant(2026, 8, 12, 10, 0, 0),
                f.instant(2026, 8, 12, 14, 0, 0),
                pallet_count=4,
            ),
        ),
    )
    get_success_data(
        api.set_entry_facility_status(
            world.facility_id, f.facility_status_payload("CLOSED"), BUREAU_ADMIN
        )
    )
    return world


def build_two_untouched_jobs_world(api: ApiClient) -> World:
    """One client with two identical 1000-piece jobs and no hygiene run on
    either, so a hygiene run can be posted to each with a single field differing
    between them.
    """
    world = World()
    set_clock(api, FIXTURE_CLOCK_UTC)
    _remember(
        world,
        "pivot",
        create_client(
            api,
            f.client_payload(
                name="Pivot Print",
                client_code="PIVOT",
                service_fee_rate_per_thousand_cents=1100,
            ),
        ),
    )
    _remember(
        world,
        "permit_p",
        create_permit_account(
            api, f.permit_account_payload(world.pivot_id, permit_number="PI-400400")
        ),
    )
    for name in ("job_p", "job_q"):
        _remember(
            world,
            name,
            create_mail_job(
                api,
                f.mail_job_payload(
                    world.pivot_id,
                    world.permit_p_id,
                    declared_piece_count=1000,
                    declared_weight_oz_per_piece=1.0,
                ),
            ),
        )
    return world


def build_empty_batch_world(api: ApiClient) -> World:
    """One SCF facility and one empty open batch, ready to have containers
    staged against it one at a time."""
    world = World()
    set_clock(api, FIXTURE_CLOCK_UTC)
    _remember(world, "facility", create_entry_facility(api, f.entry_facility_payload()))
    _remember(
        world, "batch", create_batch(api, f.commingle_batch_payload(world.facility_id))
    )
    return world


def build_single_member_no_container_world(api: ApiClient) -> World:
    """One client's single 1200-piece job pooled into an open batch that has no
    containers at all, so a sort has members to price but nothing to sort."""
    world = World()
    set_clock(api, FIXTURE_CLOCK_UTC)
    _remember(
        world,
        "solo",
        create_client(
            api,
            f.client_payload(
                name="Solo Mailworks",
                client_code="SOLO",
                service_fee_rate_per_thousand_cents=1300,
            ),
        ),
    )
    _remember(
        world,
        "permit_s",
        create_permit_account(
            api, f.permit_account_payload(world.solo_id, permit_number="PI-500500")
        ),
    )
    _remember(world, "facility", create_entry_facility(api, f.entry_facility_payload()))
    _remember(
        world,
        "job_s",
        create_mail_job(
            api,
            f.mail_job_payload(
                world.solo_id,
                world.permit_s_id,
                declared_piece_count=1250,
                declared_weight_oz_per_piece=1.2,
            ),
        ),
    )
    create_hygiene_run(api, world.job_s_id, f.hygiene_run_payload(1250, 1235, 40, 50, 30))
    _remember(
        world, "batch", create_batch(api, f.commingle_batch_payload(world.facility_id))
    )
    _remember(world, "member_s", add_member(api, world.batch_id, world.job_s_id))
    return world


def build_permit_on_hold_world(api: ApiClient) -> World:
    """One client whose job cleared hygiene while its permit account was still
    ACTIVE, with the account then placed on hold. The job is pool-ready in every
    respect except the state of the account that would pay for it.
    """
    world = World()
    set_clock(api, FIXTURE_CLOCK_UTC)
    _remember(
        world,
        "gate",
        create_client(
            api,
            f.client_payload(
                name="Gatehouse Mail",
                client_code="GATE",
                service_fee_rate_per_thousand_cents=1000,
            ),
        ),
    )
    _remember(
        world,
        "permit_g",
        create_permit_account(
            api, f.permit_account_payload(world.gate_id, permit_number="PI-600600")
        ),
    )
    _remember(world, "facility", create_entry_facility(api, f.entry_facility_payload()))
    _remember(
        world,
        "job_g",
        create_mail_job(
            api,
            f.mail_job_payload(
                world.gate_id,
                world.permit_g_id,
                declared_piece_count=1250,
                declared_weight_oz_per_piece=1.2,
            ),
        ),
    )
    create_hygiene_run(api, world.job_g_id, f.hygiene_run_payload(1250, 1235, 40, 50, 30))
    _remember(
        world, "batch", create_batch(api, f.commingle_batch_payload(world.facility_id))
    )
    get_success_data(
        api.set_permit_account_status(
            world.permit_g_id,
            f.permit_status_payload("HOLD", reason="annual fee review"),
            POSTAGE_MANAGER,
        )
    )
    return world


def build_dock_world(api: ApiClient, batch_count: int = 4) -> World:
    """An NDC facility whose dock holds 12 pallets per slot, plus several empty
    batches — one per appointment, because a batch may hold only one live
    appointment at a time. Batches are exposed as ``batch_1`` through
    ``batch_<n>``.
    """
    world = World()
    set_clock(api, FIXTURE_CLOCK_UTC)
    _remember(
        world,
        "facility",
        create_entry_facility(
            api,
            f.entry_facility_payload(
                facility_code="NDC-060",
                facility_type="NDC",
                zip3="060",
                dock_capacity_pallets_per_slot=12,
                drop_ship_discount_bp=200,
                served_zip3_list=["060", "061"],
            ),
        ),
    )
    for index in range(1, batch_count + 1):
        _remember(
            world,
            f"batch_{index}",
            create_batch(api, f.commingle_batch_payload(world.facility_id)),
        )
    return world

# ─── Composable setup helpers for one-off shapes ───────────────────────────
#
# Many behaviours need only a thin slice of history — one client, one permit
# account, sometimes one cleared job — with literals that differ from the
# canonical world. Building those from the primitives above takes half a dozen
# lines every time, so the three helpers below collapse the ramp while leaving
# every literal in the caller's hands.


def setup_client_with_permit(
    api: ApiClient,
    name: str,
    client_code: str,
    service_fee_rate_per_thousand_cents: int = 1000,
    permit_number: str = "PI-100100",
    payment_method: str = "METER",
    commingle_opt_in: Optional[bool] = None,
    billing_terms: Optional[str] = None,
    annual_fee_paid_through_utc: str = f.FEE_PAID_THROUGH_2027,
) -> Dict:
    """One ACTIVE client with one ACTIVE permit account of its own.

    Returns a ``World`` holding ``client``/``client_id`` and
    ``permit``/``permit_id`` so the caller can go straight on to a mail job.
    """
    world = World()
    _remember(
        world,
        "client",
        create_client(
            api,
            f.client_payload(
                name=name,
                client_code=client_code,
                service_fee_rate_per_thousand_cents=service_fee_rate_per_thousand_cents,
                billing_terms=billing_terms,
                commingle_opt_in=commingle_opt_in,
            ),
        ),
    )
    _remember(
        world,
        "permit",
        create_permit_account(
            api,
            f.permit_account_payload(
                world.client_id,
                permit_number=permit_number,
                payment_method=payment_method,
                annual_fee_paid_through_utc=annual_fee_paid_through_utc,
            ),
        ),
    )
    return world


def setup_facility(api: ApiClient, **overrides) -> Dict:
    """One entry facility, defaulting to the canonical SCF-021 with a 300
    basis-point entry discount, a 12-pallet dock and 021/022 served."""
    return create_entry_facility(api, f.entry_facility_payload(**overrides))


def setup_cleared_job(
    api: ApiClient,
    client_id: str,
    permit_account_id: str,
    mail_class: str = "MARKETING_MAIL",
    processing_category: str = "LETTERS",
    declared_piece_count: int = 1000,
    declared_weight_oz_per_piece: float = 1.0,
    submitted_piece_count: Optional[int] = None,
    cass_matched_count: Optional[int] = None,
    ncoa_move_updated_count: int = 30,
    undeliverable_removed_count: int = 0,
    move_update_age_days: int = 10,
) -> Dict:
    """One tendered mail job with a single hygiene pass already recorded, so the
    job sits in ``HYGIENE_CLEARED`` and is ready to be pooled.

    The hygiene pass defaults to submitting the whole declared volume with every
    piece CASS-matched and nothing suppressed, which keeps the job's
    ``accepted_piece_count`` equal to its declared count and its
    ``address_quality_pct`` at 100.00. Returns a ``World`` with ``job``/``job_id``
    and ``run``/``run_id``.
    """
    submitted = (
        declared_piece_count if submitted_piece_count is None else submitted_piece_count
    )
    matched = submitted if cass_matched_count is None else cass_matched_count
    world = World()
    _remember(
        world,
        "job",
        create_mail_job(
            api,
            f.mail_job_payload(
                client_id,
                permit_account_id,
                mail_class=mail_class,
                processing_category=processing_category,
                declared_piece_count=declared_piece_count,
                declared_weight_oz_per_piece=declared_weight_oz_per_piece,
            ),
        ),
    )
    _remember(
        world,
        "run",
        create_hygiene_run(
            api,
            world.job_id,
            f.hygiene_run_payload(
                submitted_piece_count=submitted,
                cass_matched_count=matched,
                ncoa_move_updated_count=ncoa_move_updated_count,
                undeliverable_removed_count=undeliverable_removed_count,
                move_update_age_days=move_update_age_days,
            ),
        ),
    )
    # The hygiene pass mirrors its three derived measures onto the job and moves
    # it RECEIVED -> HYGIENE_CLEARED, so the snapshot the tender returned is
    # already stale. Re-read it, because this builder's whole promise is to hand
    # back a job that "sits in HYGIENE_CLEARED" with its post-hygiene counters.
    _remember(world, "job", read_mail_job(api, world.job_id))
    return world


def build_unpooled_world(api: ApiClient) -> World:
    """The canonical two-client world one step earlier than ``build_pooled_world``:
    both clients, both permit accounts, the SCF-021 entry facility, both
    hygiene-cleared jobs and the OPEN batch all exist, but nothing has been pooled
    into the batch and no container has been staged against it. The batch is
    therefore still at tier ``NONE`` with zero members, which is what lets a test
    watch each pooling re-price the pool from scratch.
    """
    world = World()
    set_clock(api, FIXTURE_CLOCK_UTC)

    _remember(world, "acme", create_client(api, f.ACME_CLIENT))
    _remember(world, "bore", create_client(api, f.BORE_CLIENT))
    _remember(
        world,
        "permit_a",
        create_permit_account(
            api,
            f.permit_account_payload(
                world.acme_id, permit_number="PI-100100", payment_method="PERMIT_IMPRINT"
            ),
        ),
    )
    _remember(
        world,
        "permit_b",
        create_permit_account(
            api,
            f.permit_account_payload(
                world.bore_id, permit_number="PI-200200", payment_method="METER"
            ),
        ),
    )
    _remember(world, "facility", create_entry_facility(api, f.entry_facility_payload()))

    _remember(
        world,
        "job_a",
        create_mail_job(
            api,
            f.mail_job_payload(
                world.acme_id,
                world.permit_a_id,
                declared_piece_count=JOB_A_DECLARED,
                declared_weight_oz_per_piece=1.2,
            ),
        ),
    )
    _remember(
        world,
        "hygiene_a",
        create_hygiene_run(api, world.job_a_id, f.hygiene_run_payload(1250, 1235, 40, 50, 30)),
    )
    _remember(
        world,
        "job_b",
        create_mail_job(
            api,
            f.mail_job_payload(
                world.bore_id,
                world.permit_b_id,
                declared_piece_count=JOB_B_DECLARED,
                declared_weight_oz_per_piece=1.1,
            ),
        ),
    )
    _remember(
        world,
        "hygiene_b",
        create_hygiene_run(api, world.job_b_id, f.hygiene_run_payload(1850, 1830, 55, 50, 20)),
    )
    _remember(
        world, "batch", create_batch(api, f.commingle_batch_payload(world.facility_id))
    )
    return world
