# Worklog — task_3098_investment_research_ratings_managed_data_licensing

## Step 1: Create Task Directory — 2026-09-29T22:49:00.000Z

Pre-allocated task directory `./tasks/task_3098_investment_research_ratings_managed_data_licensing/` verified to exist with empty `workspace/` inside. Used as-is per instructions; no new index computed and no other task_* directory created.

## Step 2: Generate Scaffold — 2026-09-29T23:16:00.000Z

Generated the three scaffold artifacts for task_3098 (Investment Research Ratings & Managed Data Licensing) purely from the scenario + skill spec (no sibling tasks consulted):

- `SCAFFOLD.yaml` — §1.0–§1.7: 18 entities (FundCompany, Fund, Holding, Category, Methodology, MethodologyChange, Rating, RatingProposal, CommitteeVote, Licensee, LicenseAgreement, SeatEntitlement, LicenseAudit, DataDispute, IndexDefinition, IndexConstituent, ConflictFlag, ClientNotice), 14 state machines, 3 OCC concurrency rules, 6 calculations, 13 prioritized validations, 83 endpoints (incl. `/_clock/set_current_utc` with the mandated 2026-09-01T00:00:00Z default), 26 error codes, 5 roles (segregation-of-duties model; FundCompanyRep is `entity_backed:FundCompany` for the issuer-only dispute check).
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — all 9 rule_ids × 2 instances (18 total), with code-verified literals (e.g., provisional 5 stars vs final 4 stars on identical inputs; audit penalty 450000 vs 675000 across standard/repeat-offender variants; fee quote 8687500 via pinned 4-step discount-then-surcharge order).
- `SCAFFOLD_CORNER_DESIGN.yaml` — 37 instances across all 9 claim-extraction-guide sections, incl. excluded_because stubs where §1.8 already covers the corner.

Difficulty was pushed past typical expert level per instructions: depth-3 transitive cascades (audit close → licensee suspension → seat revocation → agreement counter), committee quorum/voting SoD state machine with review cycles, half-open abutting methodology windows vs (licensee, tier)-keyed agreement windows (two different interval-overlap semantics), cap-and-redistribute-with-discard index waterfall, restatement cascades with self-referential rating lineage, and dual boundary-precision checks (seat quota strict `<`, weights-sum exact 10000 with empty eligible-category set).

Lint verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (447 calls scanned, 59 design instances, zero name collisions, no forbidden race vocabulary.)

One fix applied during authoring: added five reverse-reachability GETs (`/research/proposals`, `/research/indices`, `/research/funds/{id}/constituents`, `/research/licensees/{id}/notices`, plus `restatement_of_id?` filter on `/research/ratings`) and extended validation priority 12 to cover `link-license`, both surfaced by `scaffold_lint.py` check (f) and chain replay.

## Step 3: Copy Shared Files — 2026-09-29T23:16:30.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-29T23:24:30.000Z

Generated `workspace/PRD.md` (358 lines) from the scaffold, per the prd-bench-doc-generator skill. The forbidden design index files were not opened or referenced.

**Document structure** (domain-derived, not template-copied):
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications: 2.1 RBAC with per-role identity prose (including the `entity_backed:FundCompany` rule for `FundCompanyRep`), 2.2 verbatim fixed response-structure block, 2.3 pagination (limit default 10, min 1, max 100, offset 0; `created_at` ascending), 2.4 validation priority ordering (all 13 priorities with their error IDs), 2.5 common resource properties (including the `updated_at`/`version` absence for Holding/CommitteeVote/ClientNotice), 2.6 nested retrieval, 2.7 conflict-of-interest governance, 2.8 OCC (all three `concurrency_rules` with `expected_agreement_version` / `expected_methodology_version` / `expected_dispute_version` → `ERR_STALE_VERSION` 412, framed purely as stale-version rejection), 2.9 integer cents/basis-point floor-division precision, 2.10 logical clock (default `2026-09-01T00:00:00Z`, no wall-clock fallback), 2.11 uniqueness constraints.
- §3 Business Logic in 10 subsections (fund companies/funds, holdings & category assignment, methodologies, change management & restatement, rating computation & publication, analyst committee, disputes & quality score, licensing & seats, audits & penalties, index construction) — all six calculations rendered as precise reconstruction-safe prose (6000/4000 blend, 7000/3000 category scoring, four-step fee pipeline with per-step floor, repeat-offender penalty with post-uplift 100000-cent floor, cap-and-redistribute waterfall with ticker tie-break and sub-10000 total by design, quality score decay), all state transitions with preconditions/side effects, all validation priority orderings stated explicitly.
- §4 endpoint table: 4 columns, 83 rows matching scaffold exactly. §5 error table: 2 columns, 26 rows.

**Hard contract results (mechanically verified):**
- Contract 1 (Field coverage): 100 required identifiers (entity fields + request-body + query params), 100 present, 0 missing — PASS
- Contract 2 (Rule coverage): all 13 validations with priorities, all 3 OCC rules (write-endpoint + expected_*_version + error_id + 412 all named), all state-machine transitions, all 6 calculations, all endpoint side effects, all 26 error IDs matchable in prose, enum/state/role coverage complete — PASS
- Contract 3 (§3 path purity): 494 backticked tokens scanned in §3, 0 path/method violations — PASS

## Step 5: Generate Unit Tests — 2026-09-29T23:43:00.000Z

Complete. All 73 tests generated and validated statically.

**Generated** in the task directory:

**test_helpers/** (9 files, ~2000 lines):
- `types.py` — 5 roles, 20 status/field enums, 20 entity TypedDicts; ledger-style entities (Holding, CommitteeVote, ClientNotice, IndexConstituent) correctly omit `updated_at`/`version`
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (63 methods)
- `api_errors.py` — all 26 error IDs with HTTP map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity shape assertions honoring the common-fields branch
- `factories.py`, `constants.py` (fee/penalty/quality/quorum constants), `test_users.py` (with mandatory `make_fund_company_rep_headers(company.id)` builder for the entity-backed role), `fixtures.py` (5 tiers: creation, company+fund+holdings, ratings lifecycle, OCC-threaded seat granting, licensed-index composites, dispute helpers)

**test_suite/** (5 files + conftest, 73 tests):
- `test_01_resources_and_envelope.py` (8 tests — creation defaults, retrieval, pagination, 404, required fields, holding immutability, error envelope)
- `test_02_ratings_and_committee.py` (19 tests — dual-variant stars, floor-division order, committee cycles, quorum, approval/supersede, publish guards, conflict-gate priority, SoD)
- `test_03_fund_company_and_disputes.py` (9 tests — suspension cascade, liquidation cascade, offboard lockdown, dispute counter conservation, issuer check, quality score)
- `test_04_licensing_audits_indices.py` (13 tests — fee quote tiers/bands, penalty variants, cascade to suspension/seats, seat quota boundary, seat invariant, agreement overlap, audit outcome, rebalance waterfall, index launch gating)
- `test_05_methodology_and_governance.py` (24 tests — window overlap/abutment, change branching, temporal gates, restatement cascade, snapshot integrity, category tie-break, OCC ×2, RBAC ×4, immediate consistency)

**Verification (all green):**
- 73/73 tests collected by pytest without errors
- Every test has exactly one `Design:` tag; all tags resolve to real instances; no stub instances translated
- All 18 difficulty instances have ≥2 tests; all 22 non-stub corner instances have ≥1 test
- Every PRD citation passes the 8-word verbatim grep check against PRD.md
- No "scaffold"/section references in generated code; no skip/xfail markers

**One derivation note:** `test_launch_requires_published_rating_under_index_methodology` asserts the constituent-admission refusal with `resp.status_code in (409, 422)` rather than a pinned error_id, because the PRD states the admission rule without naming its error code — the two-reader test fails for any specific `error_id`.

## Step 6: Generate Implementation — 2026-09-30T00:07:30.000Z

Implemented the complete Flask REST API for the task at `workspace/implementation/`:

**Files created:**
- `start.sh` — guarded pip install (no-op once Flask is importable), `exec python3 app.py`, foreground, `0.0.0.0:$PORT` (default 10000)
- `requirements.txt`, `app.py` (Flask app, error handlers mapping `ApiError` to the PRD §2.2 error envelope)
- `db.py` — empty in-memory store plus logical clock (defaults to `2026-09-01T00:00:00Z`, never wall-clock; `POST /_clock/set_current_utc` advances it)
- `errors.py` — all 26 error IDs with exact HTTP statuses from PRD §5
- `response.py` — exact envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields `limit`/`offset`/`total_count`/`has_more` with defaults 10/0, max 100)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (401/403), typed body validators (`ERR_VALIDATION` 400)
- `services.py` — calculations (quantitative star dual-variant with floor division, category assignment with 7000/3000 scoring and `category_code` ASC tie-break, fee quote with per-step floor, audit penalty with repeat-offender uplift before the 100000 floor, cap-and-redistribute index rebalance, quality score), cascades (company suspension, fund liquidation, restatement, penalty → licensee suspension/seat revocation), serializers (ledger rows carry only `id`+`created_at`)
- `routes_research.py`, `routes_licensing.py` — all 60+ endpoints with RBAC, left-to-right 404s, OCC on the three versioned endpoints (`ERR_STALE_VERSION` 412), state machines, validation priority ordering

**Result:** 73/73 tests pass under `prd-bench-local-run --isolation per-test-server` (~130s). Three bugs found and fixed during iteration: proposal REJECTED auto-transition must require ≥3 total votes (not fire at 2 rejections); publish must check `suppression_reason` before fund-active state (suppressed+suspended → `ERR_SUPPRESSED_RATING`); dispute quality-window timestamps must use logical-clock resolution time, and index launch with no linked agreement yields `ERR_INDEX_NOT_LICENSABLE` while a linked-but-wrong-tier agreement yields `ERR_LICENSE_TIER_INSUFFICIENT`. No entities are seeded at startup.

## Step 7: Run Tests and Iterate — 2026-09-30T00:14:00.000Z

All 8 rounds passed 73/73. Clean sweep on the first iteration — no failures to diagnose.

Summary:
- Iterations run: 1 (8-round parallel sweep, all rounds 73/73 passed).
- Tests deleted: none.
- Fixes applied to `test_helpers/`: none this iteration.
- Fixes applied to `implementation/`: none this iteration.

The task is stable: 73/73 tests pass in every one of 8 concurrent rounds under `--isolation per-test-server` (~138s wall time per round, all rounds concurrent). Prior work (recorded in the worklog) had already resolved three implementation bugs: REJECTED auto-transition requiring ≥3 total votes, publish checking `suppression_reason` before fund-active state, and dispute quality-window timestamps using logical-clock resolution time. No further action needed.

Orchestrator verification: all 8 `results.{1..8}.json` files confirmed `total: 73, passed: 73, failed: 0, errors: 0`.

## Step 8: Finalize PRD — 2026-09-30T00:14:30.000Z

SKIPPED. Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — the skip condition is met: `PRD.md` already determined every behavior the implementation exhibits. No `PRD_FINALIZED.md` produced.

## Step 9: Complete PRD — 2026-09-30T00:29:00.000Z

- **Source:** `PRD.md` (no `PRD_FINALIZED.md` existed; Step 8 skipped). **Output:** `workspace/PRD_COMPLETED.md`
- **Line counts:** PRD.md 358 lines / 50,406 chars → PRD_COMPLETED.md 358 lines / 51,410 chars (+1,004 chars, 10 modified paragraphs, no new sections).
- **Counts:** 9 ambiguity-pins, 1 mismatch-revision (plus 1 inert-tie-break clarification counted as an ambiguity pin).

### Changes

- §2.10 (Logical clock) — insert — ambiguity — pinned `/_clock/set_current_utc` response shape: object with single field `current_utc` (normalized UTC `Z`, 3 fractional digits) — implementation/routes_research.py:51, db.py:61-69.
- §3.1 (Fund company suspend/reinstate) — insert — ambiguity — pinned that `DISPUTE_HOLD` suppressions applied at suspend persist through reinstatement and clear only via §3.7 dispute resolution — implementation/routes_research.py:145-159.
- §3.2 (Holdings ingestion) — insert — ambiguity — pinned that the ingestion response is an array envelope of the created holdings rows — implementation/routes_research.py:302.
- §3.2 (Category assignment snapshot selection) — revise — ambiguity — replaced the inert "ties on that date broken by lexicographically smaller `security_ticker`" clause with the pinning that the once-per-date uniqueness rule makes the latest snapshot a single row set, so that tie-break never comes into play (impl takes all rows at `max(as_of_date)`) — implementation/services.py:182-187.
- §3.3 (Methodology creation) — revise — mismatch — `rating_ceilings` changed from "ascending" to "non-increasing" cutoffs (impl requires `ceilings[0] >= ceilings[1] >= ceilings[2] >= ceilings[3]`, rejects strictly-ascending input) — implementation/routes_research.py:524-525.
- §3.4 (Propose methodology change) — insert — ambiguity — pinned that proposing a change advances the methodology's `version` as a side effect (so a subsequent proposal must declare the advanced version) — implementation/routes_research.py:663-664.
- §3.8 (Fee preview) — insert — ambiguity — pinned that the fee-quote response body is an object with a single field `total_fee_cents` — implementation/routes_licensing.py:182.
- §3.8 (Grant seat) — insert — ambiguity — pinned that the per-agreement ACTIVE `workstation_user_id` uniqueness rule of §2.11 is enforced at grant time with `ERR_UNIQUENESS_VIOLATION` — implementation/routes_licensing.py:286-292.
- §3.8 (Grant seat) — revise — ambiguity — pinned that `entitled_data_scope` is set to the agreement's tier name at grant time — implementation/routes_licensing.py:307.
- §3.10 (Index launch) — insert — ambiguity — pinned that launching with no linked agreement at all is rejected with `ERR_INDEX_NOT_LICENSABLE` (not the tier error) — implementation/routes_licensing.py:574-575.
- §3.10 (On-demand rebalance) — insert — ambiguity — pinned that the on-demand rebalance returns the index's constituent rows in an array envelope — implementation/routes_licensing.py:627-629.

Note: each Edit call was executed twice by the harness during this session; the duplicated insertions that produced (lines 137, 151, 215) were detected via diff and deduplicated, so the final file contains each change exactly once.
