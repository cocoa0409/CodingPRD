"""Train window conflicts, changeover/turnaround gaps, molecule and market-scope gates."""
from test_helpers import (
    ApiErrorId,
    validate_success, validate_error,
    setup_master_data, setup_campaign,
    create_product_entity, create_train_entity, create_campaign_entity,
    create_campaign_payload,
)


def _dual_product_env(api, process_engineer_headers):
    """Site + MAB-001 product + FSN-002 product + dual-molecule train TR-9 + campaign A."""
    env = setup_master_data()
    product2 = create_product_entity(
        product_code="FSN-002", molecule_type="FUSION_PROTEIN", market_scope="BOTH",
        requires_cold_chain=True, min_storage_temp_c=2.0, max_storage_temp_c=8.0,
        shelf_life_hours=1440, changeover_hours=10, same_product_turnaround_hours=4,
        required_materials=[])
    train2 = create_train_entity(
        env["site"]["id"], train_code="TR-9", capacity_liters=1500,
        supported_molecule_types=["MONOCLONAL_ANTIBODY", "FUSION_PROTEIN"])
    campaign_a = create_campaign_entity(
        train2["id"], env["product"]["id"], demand_type="COMMERCIAL",
        planned_start_utc="2026-10-01T00:00:00Z", planned_end_utc="2026-10-10T00:00:00Z",
        upstream_hours=20, downstream_hours=30)
    return env, product2, train2, campaign_a


def test_changeover_gap_exactly_fourteen_hours_allowed(api, process_engineer_headers):
    """PRD §3.2: "No conflict exists when the candidate starts at or after the other campaign's end plus the gap, or when the candidate's end plus the gap falls at or before the other campaign's start; a gap of exactly the required hours is allowed."
    PRD §3.2: "otherwise the larger of the two products' `changeover_hours`."

    Design: Difficulty/boundary_precision_check/train_changeover_gap_exact_boundary
    """
    _env, product2, train2, _campaign_a = _dual_product_env(api, process_engineer_headers)
    payload = create_campaign_payload(
        product2["id"], demand_type="COMMERCIAL",
        planned_start_utc="2026-10-10T14:00:00Z", planned_end_utc="2026-10-12T00:00:00Z",
        upstream_hours=8, downstream_hours=24)
    data = validate_success(
        api.create_campaign(train2["id"], payload, process_engineer_headers),
        expected_status=201)
    assert data["status"] == "PROPOSED"


def test_changeover_gap_one_second_short_rejected(api, process_engineer_headers):
    """PRD §3.2: "Any overlap, or a shortfall of even one second, is a conflict rejected with `ERR_TRAIN_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/train_changeover_gap_exact_boundary
    """
    _env, product2, train2, _campaign_a = _dual_product_env(api, process_engineer_headers)
    payload = create_campaign_payload(
        product2["id"], demand_type="COMMERCIAL",
        planned_start_utc="2026-10-10T13:59:59Z", planned_end_utc="2026-10-11T00:00:00Z",
        upstream_hours=8, downstream_hours=24)
    resp = api.create_campaign(train2["id"], payload, process_engineer_headers)
    validate_error(resp, ApiErrorId.ERR_TRAIN_WINDOW_CONFLICT)


def test_same_product_exact_turnaround_allowed_and_overlap_rejected(api, process_engineer_headers):
    """PRD §3.2: "the required gap is the product's `same_product_turnaround_hours` when both campaigns make the same product"
    PRD §3.2: "No conflict exists when the candidate starts at or after the other campaign's end plus the gap, or when the candidate's end plus the gap falls at or before the other campaign's start; a gap of exactly the required hours is allowed. Any overlap, or a shortfall of even one second, is a conflict rejected with `ERR_TRAIN_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/train_window_buffered_adjacency_overlap_semantics
    """
    env = setup_campaign()  # campaign A occupies 2026-10-01T00:00Z .. 2026-10-20T00:00Z
    train_id, prod_id = env["train"]["id"], env["product"]["id"]
    exact = create_campaign_payload(
        prod_id, demand_type="COMMERCIAL",
        planned_start_utc="2026-10-20T06:00:00Z", planned_end_utc="2026-10-25T00:00:00Z",
        upstream_hours=8, downstream_hours=24)
    validate_success(api.create_campaign(train_id, exact, process_engineer_headers),
                     expected_status=201)
    overlap = create_campaign_payload(
        prod_id, demand_type="COMMERCIAL",
        planned_start_utc="2026-10-05T00:00:00Z", planned_end_utc="2026-10-12T00:00:00Z",
        upstream_hours=8, downstream_hours=24)
    validate_error(api.create_campaign(train_id, overlap, process_engineer_headers),
                   ApiErrorId.ERR_TRAIN_WINDOW_CONFLICT)


def test_same_product_five_hour_gap_rejected(api, process_engineer_headers):
    """PRD §3.2: "Any overlap, or a shortfall of even one second, is a conflict rejected with `ERR_TRAIN_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/train_window_buffered_adjacency_overlap_semantics
    """
    env = setup_campaign()
    short = create_campaign_payload(
        env["product"]["id"], demand_type="COMMERCIAL",
        planned_start_utc="2026-10-20T05:00:00Z", planned_end_utc="2026-10-25T00:00:00Z",
        upstream_hours=8, downstream_hours=24)
    resp = api.create_campaign(env["train"]["id"], short, process_engineer_headers)
    validate_error(resp, ApiErrorId.ERR_TRAIN_WINDOW_CONFLICT)


def test_campaign_on_incompatible_train_rejected(api, process_engineer_headers):
    """PRD §3.2: "Molecule compatibility rejects with `ERR_TRAIN_PRODUCT_INCOMPATIBLE` (HTTP 409) when the product's `molecule_type` is not among the train's `supported_molecule_types`."

    Design: Corner/validations/campaign_on_incompatible_train_rejected
    """
    env = setup_master_data()
    train_f = create_train_entity(env["site"]["id"], train_code="TR-F", capacity_liters=2000,
                                  supported_molecule_types=["FUSION_PROTEIN"])
    payload = create_campaign_payload(env["product"]["id"])
    resp = api.create_campaign(train_f["id"], payload, process_engineer_headers)
    validate_error(resp, ApiErrorId.ERR_TRAIN_PRODUCT_INCOMPATIBLE)


def test_clinical_campaign_on_commercial_only_product_rejected(api, process_engineer_headers):
    """PRD §3.2: "Market scope rejects with `ERR_MARKET_SCOPE_VIOLATION` (HTTP 422) when the `demand_type` is not permitted by the product's `market_scope` — `CLINICAL_ONLY` products admit only `CLINICAL` campaigns, `COMMERCIAL_ONLY` only `COMMERCIAL`, and `BOTH` admits either."

    Design: Corner/validations/clinical_campaign_on_commercial_only_product_rejected
    """
    env = setup_master_data()
    product_co = create_product_entity(product_code="MAB-CO", market_scope="COMMERCIAL_ONLY")
    payload = create_campaign_payload(product_co["id"], demand_type="CLINICAL")
    resp = api.create_campaign(env["train"]["id"], payload, process_engineer_headers)
    validate_error(resp, ApiErrorId.ERR_MARKET_SCOPE_VIOLATION)
