"""Composite setup helpers.

Every fixture rebuilds its preconditions from scratch against an empty
database (the harness restarts the server before each test) using only
PRD-declared endpoints. The dominant anchor chain mirrors the shared setup
used across the design index: clock 2026-09-01 -> VOCC carrier -> shipper ->
tariff (free 2 days, 5000 cents/day, CALENDAR, NEW, effective 2026-09-02) ->
clock 2026-09-03 -> publish -> clock 2026-09-10 -> one 10000-cent invoice
(availability 2026-09-04, return 2026-09-08, last accrual 2026-09-08).
"""
from test_helpers.api_client import api_client
from test_helpers.constants import CLOCK_START_ISO
from test_helpers.factories import (
    create_bond_payload,
    create_carrier_payload,
    create_complaint_payload,
    create_congestion_report_payload,
    create_dispute_payload,
    create_draw_payload,
    create_invoice_payload,
    create_oti_license_payload,
    create_proceeding_payload,
    create_service_contract_payload,
    create_shipper_payload,
    create_tariff_payload,
)
from test_helpers.test_users import (
    TEST_USERS,
    make_alj_headers,
    make_carrier_rep_headers,
    make_counsel_headers,
    make_ombuds_officer_headers,
    make_shipper_rep_headers,
)

ADMIN = TEST_USERS["admin_headers"]
DOCKET = TEST_USERS["docket_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]
COUNSEL = TEST_USERS["counsel_headers"]


def _ok(resp, what):
    body = resp.json()
    assert 200 <= resp.status_code < 300, (
        f"Setup failed for {what}: HTTP {resp.status_code}: {body}"
    )
    return body["data"]


# ---------------------------------------------------------------------------
# Atomic helpers
# ---------------------------------------------------------------------------

def set_logical_clock(iso=CLOCK_START_ISO):
    """Move the server-side logical clock (PRD §2.4)."""
    return _ok(api_client.set_clock(iso, ADMIN), f"set clock {iso}")


def make_carrier(org_type="VOCC", org_name="Corner Carriers"):
    return _ok(api_client.create_carrier(
        create_carrier_payload(org_name=org_name, org_type=org_type), ADMIN),
        "carrier")


def make_shipper(company_name="Corner Shippers", contact_email="billing@corner.example"):
    return _ok(api_client.create_shipper(
        create_shipper_payload(company_name=company_name, contact_email=contact_email),
        ADMIN), "shipper")


def get_carrier_version(carrier_id):
    return _ok(api_client.get_carrier(carrier_id, DOCKET), "carrier read")["version"]


def file_tariff(carrier_id, expected_carrier_version=None, **overrides):
    """File a tariff as the owning CarrierRep. When expected_carrier_version
    is omitted the carrier is re-observed first (PRD §2.9 re-read discipline)."""
    if expected_carrier_version is None:
        expected_carrier_version = get_carrier_version(carrier_id)
    return _ok(api_client.create_tariff(
        carrier_id,
        create_tariff_payload(expected_carrier_version, **overrides),
        make_carrier_rep_headers(carrier_id)), "tariff filing")


def publish_tariff(carrier_id, tariff_id):
    return _ok(api_client.publish_tariff(tariff_id, make_carrier_rep_headers(carrier_id)),
               "tariff publish")


def file_service_contract(carrier_id, shipper_id, **overrides):
    return _ok(api_client.create_service_contract(
        carrier_id, create_service_contract_payload(shipper_id, **overrides),
        make_carrier_rep_headers(carrier_id)), "service contract filing")


def issue_invoice(carrier_id, shipper_id, tariff_id=None, service_contract_id=None,
                  **overrides):
    return _ok(api_client.create_invoice(
        carrier_id,
        create_invoice_payload(tariff_id=tariff_id, service_contract_id=service_contract_id,
                               billed_party_shipper_id=shipper_id, **overrides),
        make_carrier_rep_headers(carrier_id)), "invoice issuance")


def open_dispute(invoice_id, shipper_id, **overrides):
    return _ok(api_client.create_dispute(
        invoice_id, create_dispute_payload(**overrides),
        make_shipper_rep_headers(shipper_id)), "dispute filing")


def mark_paid(invoice_id, shipper_id):
    return _ok(api_client.mark_invoice_paid(
        invoice_id, make_shipper_rep_headers(shipper_id)), "mark-paid")


def respond_dispute(dispute_id, carrier_id, payload):
    return _ok(api_client.respond_to_dispute(
        dispute_id, payload, make_carrier_rep_headers(carrier_id)), "dispute response")


def file_complaint(shipper_id, respondent_carrier_id, subject_invoice_ids, **overrides):
    return _ok(api_client.create_complaint(
        create_complaint_payload(respondent_carrier_id, subject_invoice_ids, **overrides),
        make_shipper_rep_headers(shipper_id)), "complaint filing")


def open_proceeding(carrier_id, basis="TARIFF_VIOLATION", counsel_id="ec-1"):
    return _ok(api_client.create_proceeding(
        create_proceeding_payload(carrier_id, basis=basis),
        make_counsel_headers(counsel_id)), "proceeding opening")


def determine_proceeding(proceeding_id, determination, judge_id="alj-1", **extra):
    payload = {"determination": determination}
    payload.update(extra)
    return _ok(api_client.determine_proceeding(
        proceeding_id, payload, make_alj_headers(judge_id)), "determination")


# ---------------------------------------------------------------------------
# Tier 1/2: standard billing anchor chain
# ---------------------------------------------------------------------------

def setup_carrier_shipper(org_type="VOCC", carrier_name="Corner Carriers"):
    """Clock at the 2026-09-01 startup reading + one carrier + one shipper."""
    set_logical_clock(CLOCK_START_ISO)
    carrier = make_carrier(org_type=org_type, org_name=carrier_name)
    shipper = make_shipper()
    return {"carrier": carrier, "shipper": shipper}


def setup_published_tariff(tariff_overrides=None, carrier_name="Corner Carriers",
                           org_type="VOCC", with_shipper=True):
    """Carrier (+ shipper) with a tariff filed 2026-09-01 and published after
    the clock moves to 2026-09-03 (effective_date 2026-09-02 reached)."""
    env = setup_carrier_shipper(org_type=org_type, carrier_name=carrier_name)
    carrier = env["carrier"]
    tariff = file_tariff(carrier["id"], **(tariff_overrides or {}))
    set_logical_clock("2026-09-03T00:00:00Z")
    tariff = publish_tariff(carrier["id"], tariff["id"])
    env["tariff"] = tariff
    return env


def setup_standard_billing(tariff_overrides=None, invoice_overrides=None,
                           carrier_name="Corner Carriers"):
    """Published-tariff carrier + shipper + one ISSUED 10000-cent invoice.

    Invoice: availability 2026-09-04, return 2026-09-08, last accrual
    2026-09-08, issued at clock 2026-09-10 -> free_time_end 2026-09-06,
    billable_days 2, amount 10000 under the default 5000 cents/day tariff.
    """
    env = setup_published_tariff(tariff_overrides=tariff_overrides,
                                 carrier_name=carrier_name)
    set_logical_clock("2026-09-10T00:00:00Z")
    invoice = issue_invoice(env["carrier"]["id"], env["shipper"]["id"],
                            tariff_id=env["tariff"]["id"], **(invoice_overrides or {}))
    env["invoice"] = invoice
    return env


def setup_standard_complaint(mark_paid_first=False, invoice_overrides=None,
                             claimed=50_000, carrier_name="Corner Carriers"):
    """Standard billing + one DOCKETED complaint over the standard invoice."""
    env = setup_standard_billing(invoice_overrides=invoice_overrides,
                                 carrier_name=carrier_name)
    if mark_paid_first:
        env["invoice"] = mark_paid(env["invoice"]["id"], env["shipper"]["id"])
    complaint = file_complaint(env["shipper"]["id"], env["carrier"]["id"],
                               [env["invoice"]["id"]],
                               reparations_claimed_cents=claimed)
    env["complaint"] = complaint
    return env


# ---------------------------------------------------------------------------
# Tier 3: complaint lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_complaint_in_ombuds(officer_id="om-1", **kwargs):
    env = setup_standard_complaint(**kwargs)
    complaint = _ok(api_client.refer_ombuds(
        env["complaint"]["id"], {"ombuds_officer_id": officer_id}, DOCKET),
        "ombuds referral")
    env["complaint"] = complaint
    env["officer_id"] = officer_id
    return env


def setup_adjudication_open(judge_id="alj-1", **kwargs):
    env = setup_standard_complaint(**kwargs)
    complaint = _ok(api_client.open_adjudication(
        env["complaint"]["id"], make_alj_headers(judge_id)), "open adjudication")
    env["complaint"] = complaint
    env["judge_id"] = judge_id
    return env


def setup_decided_complaint(decide_clock=None, judge_id="alj-1", **kwargs):
    """Complaint carried through decision by its presiding judge."""
    env = setup_adjudication_open(judge_id=judge_id, **kwargs)
    if decide_clock:
        set_logical_clock(decide_clock)
    complaint = _ok(api_client.decide_complaint(
        env["complaint"]["id"], make_alj_headers(judge_id)), "decision")
    env["complaint"] = complaint
    return env


def setup_appealed_complaint(appeal_by="carrier", **kwargs):
    env = setup_decided_complaint(**kwargs)
    if appeal_by == "carrier":
        headers = make_carrier_rep_headers(env["carrier"]["id"])
    else:
        headers = make_shipper_rep_headers(env["shipper"]["id"])
    complaint = _ok(api_client.appeal_complaint(env["complaint"]["id"], headers),
                    "appeal")
    env["complaint"] = complaint
    return env


# ---------------------------------------------------------------------------
# Tier 3: OTI license / bond ledger shortcuts
# ---------------------------------------------------------------------------

def setup_nvocc_license(bond_coverages=(7_500_000,), carrier_name="Ledger Lines"):
    """NVOCC carrier with a license; each listed bond is appended in order.

    Returns env with carrier, license (post-append state, so its version is
    the current one), and license_id.
    """
    set_logical_clock(CLOCK_START_ISO)
    carrier = make_carrier(org_type="NVOCC", org_name=carrier_name)
    license_ = _ok(api_client.create_oti_license(
        carrier["id"], create_oti_license_payload(license_type="NVOCC"),
        make_carrier_rep_headers(carrier["id"])), "license application")
    for i, coverage in enumerate(bond_coverages):
        license_ = _ok(api_client.append_surety_bond(
            license_["id"],
            create_bond_payload(bond_ref=f"B{i + 1}", coverage_cents=coverage),
            make_carrier_rep_headers(carrier["id"])), "bond append")
    return {"carrier": carrier, "license": license_, "license_id": license_["id"]}


def get_license_state(carrier_id, license_id):
    rows, _meta = _list(api_client.list_oti_licenses(carrier_id, DOCKET))
    for row in rows:
        if row["id"] == license_id:
            return row
    raise AssertionError(f"license {license_id} not found on carrier {carrier_id}")


def _list(resp):
    body = resp.json()
    assert resp.status_code == 200, f"Setup list failed: HTTP {resp.status_code}: {body}"
    return body["data"], body["meta"]


def post_draw(license_id, carrier_id, bond_ref, amount_cents,
              expected_license_version, reason="claim", counsel_id="ec-1"):
    return _ok(api_client.post_bond_draw(
        license_id,
        create_draw_payload(bond_ref, amount_cents, expected_license_version,
                            reason=reason),
        make_counsel_headers(counsel_id)), "bond draw")


# ---------------------------------------------------------------------------
# Tier 5: enforcement-driven suspension
# ---------------------------------------------------------------------------

def setup_suspended_carrier_with_pending_dispute(violation_count=5,
                                                 basis="UNREASONABLE_PRACTICE",
                                                 carrier_name="Cascade Carriers"):
    """Standard billing + one PENDING dispute, then a determination whose
    score deduction leaves the carrier below the 600 suspension threshold
    (PRD §2.10 cascade fires in full)."""
    env = setup_standard_billing(carrier_name=carrier_name)
    dispute = open_dispute(env["invoice"]["id"], env["shipper"]["id"],
                           dispute_reason="CHARGE_EXCEEDS_PUBLISHED")
    env["dispute"] = dispute
    proceeding = open_proceeding(env["carrier"]["id"], basis=basis)
    env["proceeding"] = determine_proceeding(
        proceeding["id"], "VIOLATION_FOUND", violation_count=violation_count)
    return env
