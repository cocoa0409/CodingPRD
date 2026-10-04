# Worklog — task_3377_syndicated_study_fielding_award_licensing_client_subscriptions

## Step 1: Create task directory — 2026-10-01T10:52:00.000Z

Pre-allocated task directory `./tasks/task_3377_syndicated_study_fielding_award_licensing_client_subscriptions/` verified to exist with `workspace/` inside (per command args; no new index computed, no other task_* directory created).

## Step 2: Generate scaffold — 2026-10-01T12:20:00.000Z

All three artifacts are complete and verified. Final state:

**Files written** (all parse as valid YAML, non-empty, verified on disk):
- `/home/ubuntu/github/CodingPRD/tasks/task_3377_syndicated_study_fielding_award_licensing_client_subscriptions/SCAFFOLD.yaml` (70 KB)
- `/home/ubuntu/github/CodingPRD/tasks/task_3377_syndicated_study_fielding_award_licensing_client_subscriptions/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (96 KB)
- `/home/ubuntu/github/CodingPRD/tasks/task_3377_syndicated_study_fielding_award_licensing_client_subscriptions/SCAFFOLD_CORNER_DESIGN.yaml` (146 KB)

**Counts**: 12 entities (Client, Brand, Study, MethodologyVersion, Factor, SampleFrame, Response, BrandResult, Award, License, UsageAudit, Subscription) · 40 endpoints (held at the impl-gen safety cap) · 33 error codes (all exercised) · 8 state machines · 12 calculations · 7 roles. **§1.8: 19 difficulty instances** (2 per rule, rule 6 has 3). **§1.9: 49 active corner instances + 9 `excluded_because` stubs**. Lint verdict, verbatim: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (863 calls scanned.)

**Design decisions worth flagging**:
- **Topology**: flat peer collections under `/research` (the skill's under-used flat pattern), with self-referential `Study.prior_study_id` for YoY chains and segregation-of-duties as the role model (award determination rejects the methodology pinner's `X-User-ID` → `ERR_SOD_CONFLICT`).
- **Dual variants**: provisional-vs-final index score (pre- vs post-dedupe-sweep input sets: 600 vs 800) on BrandResult; quote-vs-invoice license fee (400000 vs 340000) on License — different domains per Rule 1. Rounding-order fixture (412 vs naive 411) was machine-verified; all numeric asserts are precomputed literals.
- **Non-linear machines**: Study FIELDING⇄FIELDING_CLOSED reopen cycle gated on per-brand sample shortfall (only short brands' frames reopen); License ACTIVE⇄SUSPENDED driven by two distinct cascade rules (2×MINOR threshold vs 1×MAJOR).
- **Interval semantics deliberately opposed**: award licensing uses half-open `[activated_at, expires_at)` (adjacency allowed, expiry at exact `expires_at` allowed); subscriptions use closed `[starts_at, ends_at]` (adjacency conflicts).
- **Priority lattice**: three testable cross-category orderings — state(5)>temporal(7) at publish, safety(6)>constraint(8) at determine, OCC(4)>constraint(8) at pin.
- Two mid-authoring self-fixes: methodology create must allow DESIGN_LOCKED (else SUPERSEDED was unreachable — enum-closure catch), and PyYAML flow-context quirks (`foo?` optionals, `$.data[0]` captures, `errors[...]` grounds) needed quoting.

Orchestrator verification: all three files exist on disk and parse as valid YAML with correct top-level keys (SCAFFOLD.yaml → scenario/domain_name/api_prefix/...; DIFFICULTY → scaffold_difficulty_design; CORNER → scaffold_corner_design).

## Step 3: Copy shared files — 2026-10-01T12:21:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_3377_syndicated_study_fielding_award_licensing_client_subscriptions/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-10-01T12:35:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_3377_syndicated_study_fielding_award_licensing_client_subscriptions/workspace/PRD.md` — 284 lines, verified on disk.

**Sections:** §1 Introduction (2 paragraphs) · §2 Global Specifications (2.1 roles/identity, 2.2 verbatim envelope block, 2.3 pagination, 2.4 common properties incl. Factor's `common_fields: false` exception, 2.5 logical clock with the pinned `2026-09-01T00:00:00Z` start, 2.6 OCC at pin, 2.7 cents/0–1000/round-half-up discipline, 2.8 the 11-level validation priority order) · §3 Business Logic (9 subsections: study/methodology pinning, frames/ingest/quality gates, close-sweep-provisional/reopen cycle, index math/groups/ranks, awards+SoD+publish, licensing quote-vs-invoice, audits/suspension, clients/subscriptions/insights/YoY, press kit) · §4 endpoint table (40 rows, 4 columns) · §5 error catalogue (34 rows, 2 columns).

**Hard Contract Reports:**
- Contract 1 (Field-Name Coverage): 82 required identifiers (entity fields + request bodies + query params + response-payload keys like `computed_count`, `award_count`, `yoy_delta`, `current_utc`) — 82 present, 0 missing. PASS
- Contract 2 (Rule Coverage): 11 validation priorities expressed in order; 1 OCC rule (pin: `expected_study_version` + `ERR_STALE_VERSION`/412, no race framing); all Study/MethodologyVersion/SampleFrame/Response/License/UsageAudit/Subscription/Award transitions with preconditions and multi-hop side effects (3-hop close cascade, SCORED-reopen result invalidation, revoke auto-resolve, MINOR-audit threshold of 2); all 11 calculations in reconstructible prose incl. the 412-vs-411 rounding-order worked example and the CD(4,4)=83.156… constants; all applies_to scopes enumerated; rank-2-in-group-1-no-award sibling branch explicitly stated. PASS
- Contract 3 (§3 Path Purity): 493 backtick tokens scanned in §3, 0 paths, 0 bare HTTP methods, 0 method+path combos. PASS

**Ambiguities pinned down in prose:**
- Scaffold marks SampleFrame `terminal_states: []` with CLOSED reversible — written as "no manual reopen exists; only the shortfall cascade reopens."
- `significance_alpha` on Study vs `z_value` on MethodologyVersion — explicitly stated the study field is documentation-only and the pinned methodology's `z_value` is what enters the math.
- Response initial state is "ACCEPTED or REJECTED" — expressed as synchronous classification at ingest with REJECTED still a 201.
- `provisional_index` nullability — null exactly when the pre-sweep accepted set is empty; `final_index` null when `accepted_n` is 0.
- The checker initially mis-paired backticks across §2.2's fenced JSON blocks; re-ran with fences stripped — a tooling artifact, not a document defect.

## Step 5: Generate unit tests — 2026-10-01T13:12:00.000Z

Done. Summary of the generated suite for `task_3377_syndicated_study_fielding_award_licensing_client_subscriptions`:

**Stage 1 — `test_helpers/` (9 files):** `types.py` (all status enums + TypedDicts; `Factor` correctly omits `updated_at`/`version` per the append-only rule), `api_client.py` (40 methods covering every endpoint in the PRD §4 table), `api_errors.py` (all 33 error ids with HTTP statuses, registered via `set_error_http_status_map`), `assertions.py`, `factories.py` (canonical QUAL 6000bp/FEAT 4000bp methodology, z=1.96, sd=60), `constants.py` (clock default 2026-09-01, embargo 2026-10-15, all fee constants, MINOR suspension threshold 2, operator ids `u_ml_001`/`u_ao_001`), `test_users.py` (per-role builders incl. mandatory `make_client_user_headers(client_id)` for the entity-backed role), `fixtures.py` (composites: `setup_fielding_study` with per-brand/per-response specs and per-response clock control, `setup_scored_study`, `setup_awards_set_study`, `setup_published_study`, license/subscription helpers, brand-reuse for two-cycle YoY fixtures).

**Stage 2 — `test_suite/` (13 files: conftest + 12 test modules):** 87 tests total.

**Coverage:**
- Queue A (§1.8 difficulty): **19/19 instances translated, exactly 2 tests each (38 tests)**. 0 skipped.
- Queue B (§1.9 corner): **49/49 non-stub instances translated, 1 test each (49 tests)**. 0 skipped. All 9 `excluded_because:` stubs correctly left untranslated, and all 9 stub pointers verified to resolve to real §1.8 instance names.

**PRD-first adjudication notes:** every instance passed the two-condition filter (this PRD is unusually explicit — §2.8 fixes the global validation order, which legitimizes the three priority-pair instances). Two derivability accommodations were made rather than skips: timestamp assertions use prefix matching on the pinned logical instant (PRD pins the instant but §2.4's three-fractional-digit rendering makes exact string equality non-unique), and benchmarking `rankings` entry fields / diagnostics `factor_scores` entry key-names are not PRD-pinned, so those tests assert the pinned scalars (`yoy_delta`, `change_class`, `final_index`, `rank_position`, `significance_group`) plus a normalized factor-value map {QUAL:900, FEAT:800} rather than entry shapes.

**Verification:** `pytest test_suite/ --collect-only -q` → **87 tests collected, no errors**; `compileall` on both trees → True; AST audit → every test carries exactly one `Design: Difficulty/<rule>/<name>` or `Design: Corner/<section>/<name>` tag resolving to a real instance; no `skip`/`skipif`/`xfail` markers anywhere; 30 distinctive citation fragments grep verbatim against PRD.md.

Orchestrator spot-check: `pytest test_suite/ --collect-only -q` re-run by orchestrator → 87 tests collected in 0.22s, no errors. 9 files in test_helpers/, 13 in test_suite/.

## Step 6: Generate implementation — 2026-10-01T13:40:00.000Z

Full pipeline passes end-to-end. Implementation complete and verified.

**Files written** (all under `workspace/implementation/`):

- `start.sh` (executable, guarded flask install, `exec python3 app.py`, binds `0.0.0.0:$PORT` default 10000)
- `requirements.txt` (flask only)
- `app.py` — app factory, blueprint registration, envelope-shaped error handlers (404/405/500)
- `db.py` — empty in-memory store (no seeding) + logical clock starting at `2026-09-01T00:00:00Z`
- `timeutil.py` — ISO8601 parse/render (`iso` canonical for clock instants, `iso3` 3-fraction for created/updated), `add_months` with day clamping
- `errors.py` — all 33 error IDs with exact HTTP statuses
- `envelope.py` — `meta`/`response_type`/`data` envelope, pagination (`limit`/`offset`/`total_count`/`has_more`, defaults 10/0, clamped 1..100)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth, role gating
- `validation.py` — deferred 400 body validation (semantic checks priorities 3-10 run before `ERR_INVALID_REQUEST`)
- `records.py` — record factory (`version` starts 1, `touch` bumps), serializers for all 12 entity types (Factor omits `updated_at`/`version` per PRD 2.4)
- `services.py` — pinned index math (per-factor round-half-up THEN weighted sum, Decimal), duplicate sweep (submitted_at → PANEL-over-CUSTOMER_LIST → created_at), 3-hop fielding close, shortfall reopen, significance grouping (strict `>` critical diff, float) + epsilon-tie ranking, award determination, license quote/invoice fees (surcharge → 0.85 term → 1.25 violation → 220000 floor)
- Route modules: `routes_studies.py`, `routes_methodology.py`, `routes_frames.py`, `routes_responses.py`, `routes_scoring.py`, `routes_licenses.py`, `routes_registry.py`, `routes_subscriptions.py`, `routes_insights.py`

**Endpoints implemented: 40/40** from the scaffold endpoint table, including OCC pin (`expected_study_version` → `ERR_STALE_VERSION` 412), SoD at determine (`ERR_SOD_CONFLICT`), half-open license conflict intervals, closed-interval subscription overlap, minor-audit suspension threshold (2), and the test-driving clock endpoint.

**Verification**: all 20 files exist non-empty; `python3 -m compileall` passes; boot smoke test on a fresh process passed (401 unauthenticated envelope, empty paginated list, 201 study create with logical-clock timestamps); a full scripted pipeline passed — study → pin → frame → fielding → 3 ACCEPTED + 1 SPEEDER responses → close (provisional_index 600) → compute (rank 1/group 1) → SoD 403 for pinner → determine (1 award) → embargo 409 → clock advance → publish cascade → press kit → license quote 900000 / invoice 765000 with `expires_at` +24 months → subscription activate → diagnostics + benchmarking. All assertions green; only my own spawned PIDs were killed.

Orchestrator verification: 20 files on disk (incl. executable start.sh), `compileall` re-run by orchestrator → COMPILE_OK.

## Step 7: Run tests and iterate — 2026-10-01T13:55:00.000Z

Clean sweep: all 8 rounds at 87/87. All `results.${i}.json` files are in place as sweep evidence.

Summary:
- Iterations run: 2 (initial sweep + verification sweep after one fix).
- Tests deleted: none.
- Fixes applied to `test_helpers/`: none.
- Fixes applied to `test_suite/`: none.
- Fixes applied to `implementation/`: one —
  - `workspace/implementation/timeutil.py`, `new_id()`: changed `uuid.uuid4().hex` (32-char undashed) to `str(uuid.uuid4())` (canonical dashed form). PRD §2.4 requires every persisted resource's `id` to be "a server-minted UUID with no type prefix"; the canonical RFC 4122 rendering is hyphenated, and the shared runner helper `is_valid_uuid` accepts only that form. This single defect caused all 3 failures (`test_create_study_applies_defaults_and_initial_state`, `test_system_fields_input_ignored_on_brand_create`, `test_withdrawn_license_is_terminal`), each tripping "id must be a valid UUID" on freshly minted study/brand/license ids. Verified no other code depends on the undashed 32-char format (`new_id` is the sole mint point).
- All 8 final `results.${i}.json` files exist in `workspace/implementation/` with passed == total == 87; left in place as required sweep evidence.

Orchestrator verification: all 8 results.*.json parsed → 87/87 passed, 0 failed each; no implementation source file is newer than the sweep results (timeutil.py fix at 13:46:07 predates final sweep at 13:49:09–10), so the sweep evidence is valid and unshadowed.

## Step 8: Finalize PRD — 2026-10-01T14:05:00.000Z

Done. The diff is exactly one sentence revised inline; everything else is verbatim.

**Line counts / %-delta:** PRD.md 284 lines, PRD_FINALIZED.md 284 lines — 0% line-count delta; one sentence extended inline on line 85 (§2.4).

**Changes:**
- §2.4 — revise — pinned the wire rendering of a persisted resource's server-minted `id` to the canonical RFC 4122 hyphenated form (8-4-4-4-12 lowercase hex groups, e.g. `550e8400-e29b-41d4-a716-446655440000`), explicitly excluding the 32-character undashed hex rendering — `implementation/timeutil.py:52-53` (`new_id()` returns `str(uuid.uuid4())`; the Step 7 fix moved it off `uuid.uuid4().hex`).

This was the only edit: the step_7_diff contains exactly one implementation fix (the `new_id()` format change) and no test/test_helper changes, and that fix traces to a genuine PRD silence — §2.4 said "a server-minted UUID with no type prefix" without pinning dashed-canonical vs. undashed-hex, which the pre-fix implementation (`uuid.uuid4().hex`) demonstrably resolved the other way.

**Per-edit pre-edit search log:**
- (a) Subject: the rendering format of server-minted resource `id`s on the wire.
- (b) Impl paths enumerated and read/grepped:
  - `implementation/timeutil.py:52-53` — sole mint point, `str(uuid.uuid4())` (CPython guarantees lowercase dashed form).
  - `implementation/records.py:11-17` — `new_record()` assigns `id` via `new_id()` for every resource, Factor included.
  - `implementation/records.py:33-212` — all 12 `ser_*` serializers emit `id` verbatim from storage; wire form = minted form.
  - `implementation/db.py` + grep of `store.*.get(...)` across all `routes_*.py` and `services.py` — inbound identifier resolution is pure string-equality dict lookup; the server never UUID-parses or format-validates inbound ids.
  - Repo-wide grep for `uuid` in implementation/: only the `timeutil.py` import and the one mint call — no second mint point or alternate format.
  - Runner helper `prd_bench_local_runner.testing.is_valid_uuid` probed live: returns `True` for dashed canonical, `False` for undashed 32-char hex.
- (c) Wording adjustments made to keep all enumerated paths consistent: (1) scoped the clause to what the server *mints and renders* ("server-minted ... rendered in"), deliberately claiming nothing about inbound format validation, since the impl does none (an undashed inbound id simply 404s via existence lookup); (2) kept the sentence's original scope — the resource's own `id` field — so it does not mis-describe `api_request_id` (§2.2, `req_`-prefixed request metadata, not a persisted resource) or `pinned_by_user_id`/FK fields (client-supplied or verbatim echoes, not server-minted); (3) pinned "lowercase" because `str(uuid.uuid4())` is always lowercase, so the wording is an exact description of impl output rather than a loosened superset.

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` shows exactly the claimed single-sentence inline revision at line 85; both files 284 lines.

## Step 9: Complete PRD scan — 2026-10-01T14:25:00.000Z

All edits are applied and verified. Final summary:

**Source vs output:** `PRD_FINALIZED.md` 284 lines / 49,139 chars → `PRD_COMPLETED.md` 286 lines / 51,140 chars (+2 lines, +2,001 chars). 14 targeted edits; no sections added or removed.

**Counts:** 13 ambiguity-pins (inserts), 1 mismatch-revision.

### Changes (one bullet each)

- §2.2 Error format — insert — ambiguity — undefined-path/unsupported-method requests reported as `ERR_NOT_FOUND` (404) and unexpected failures as `ERR_INTERNAL` (500) in the standard envelope — `implementation/app.py:42-52`
- §5 Error catalogue — insert — ambiguity — added `ERR_INTERNAL | 500` row to keep the catalogue consistent with the §2.2 pin above — `implementation/app.py:52`
- §2.3 Pagination — insert — ambiguity — out-of-range `limit`/`offset` are clamped (limit to [1,100], offset to ≥0) and unparseable values fall back to defaults rather than being rejected; `created_at` ties broken by insertion order — `implementation/validation.py:96-107`, `implementation/envelope.py:50`
- §3.1 Pinning — insert — ambiguity — pinning a version no longer in `DRAFT` fails with `ERR_INVALID_STATE` — `implementation/routes_methodology.py:125-126`
- §3.2 Frame create — insert — ambiguity — frame creation against a study not in `DESIGN_LOCKED` fails with `ERR_INVALID_STATE` (PRD named no error id) — `implementation/routes_frames.py:30-31`
- §3.3 Duplicate sweep — insert — ambiguity — after `submitted_at`/PANEL-preference/`created_at` ties, remaining ties broken by ingestion order, earliest first — `implementation/services.py:114-117`
- §3.4 Eligible ordering — insert — ambiguity — brands registered at the same clock instant keep registration order in the eligible sort — `implementation/services.py:218-222`
- §3.4 Rank assignment — revise — **mismatch** — "two brands tied at the top are both rank 1 and the next brand is rank **3**" (was "rank 2", which contradicted both the PRD's own formula and the impl: `1 + count(final_index > mine + tie_epsilon)` yields 3 under competition ranking) — `implementation/services.py:241-244`
- §3.5 Award determination — insert — ambiguity — determination returns HTTP 201 (it creates the `Award` resources), reconciling §4's create-vs-transition status rule — `implementation/routes_scoring.py:61`
- §3.7 Audit filing — insert — ambiguity — filing an audit against a license not `ACTIVE`/`SUSPENDED` fails with `ERR_INVALID_STATE` — `implementation/routes_licenses.py:161-162`
- §3.8 List filters — insert — ambiguity — licenses additionally filterable by `award_id` and `status` (PRD only named `client_id`) — `implementation/routes_licenses.py:74`
- §3.8 Diagnostics — insert — ambiguity — `factor_scores` breakdown recomputed at read time over the brand's current `ACCEPTED` set with §3.4 per-factor rounding, entries pairing `factor_code` with integer `score`, ordered by factor `ordinal`, empty when no accepted responses — `implementation/routes_insights.py:48-54`
- §3.8 Benchmarking — insert — ambiguity — `rankings` entries carry `brand_id`/`final_index`/`rank_position`/`significance_group`/`accepted_n`, ordered by rank then `final_index` desc then brand `created_at`; benchmarking has **no** brand-result gate — missing brand/result/`final_index` only forces `yoy_comparable` false — `implementation/routes_insights.py:77-117`
- §3.9 Press kit — insert — ambiguity — `awards` array contains every award of the study regardless of status, ordered by `created_at` ascending — `implementation/routes_insights.py:134-137`
- §3.9 Catalogue — insert — ambiguity — `eligible` filter accepts `true`/`1` or `false`/`0` case-insensitively; any other value matches no rows — `implementation/routes_scoring.py:31-39`

### Dead-code audit

Every PRD-named check/helper was grepped for callsites and **all are invoked on the request path** — no dead PRD-required checks:

- SoD guard: `services.py:257` in `determine_awards`, called from `routes_scoring.py:60` ✓
- Suspension cascade: `suspend_license` called from manual suspend (`routes_licenses.py:129`) and audit escalation (`:205,:214`); `MINOR_SUSPENSION_THRESHOLD` used at `:213` ✓
- Interval-overlap checks: license half-open conflict inline at `routes_licenses.py:105-110`; subscription closed-interval overlap inline at `routes_subscriptions.py:90-99` ✓
- Significance grouping / rank assignment: inline in `compute_scoring` (`services.py:216-244`), called from the compute route ✓
- Duplicate sweep: `sweep_brand` called from `close_fielding` (`services.py:142`); `shortfall_brand_ids` from `reopen_fielding` (`services.py:176`) ✓
- Fee math: `fee_quote` (`routes_licenses.py:57`), `fee_invoice` (`:111`), `add_months` (`:113`) ✓
- Entitlement lookup: `find_active_subscription` called in both insights reads (`routes_insights.py:38,71`) ✓
- Open-audit gate on reinstate: `routes_licenses.py:116-121` ✓; revocation auto-resolve: `resolve_open_audits` at `:134` ✓

Minor non-finding: `Body.has()` (`validation.py:22`) is defined but never called — a generic accessor, not a PRD-named rule, so no action.

Orchestrator verification: `diff -q` confirms PRD_COMPLETED.md differs from PRD_FINALIZED.md (286/51140 vs 284/49139 — matches claimed counts exactly, no silent no-op). No implementation source file is newer than the Step 7 sweep results, so the 8×87/87 evidence remains valid. Dead-code spot checks confirmed independently: `MINOR_SUSPENSION_THRESHOLD` imported+used at routes_licenses.py:213, `find_active_subscription` called at routes_insights.py:38 and :71, `resolve_open_audits` present with callsite in routes_licenses.py.
