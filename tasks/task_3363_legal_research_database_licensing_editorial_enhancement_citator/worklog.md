# Worklog — task_3363_legal_research_database_licensing_editorial_enhancement_citator

## Step 1: Create task directory — 2026-10-01T09:07:00.000Z

Task directory pre-allocated by the caller: `./tasks/task_3363_legal_research_database_licensing_editorial_enhancement_citator/` with `workspace/` inside. Verified existence; no new directory created (index computation skipped per instructions).

## Step 2: Generate Scaffold — 2026-10-01T10:13:27.262Z

Recovery note: the Step 2 subagent was interrupted mid-flight (session ended before its summary was recorded), but per the lost-report-≠-lost-artifact rule the on-disk artifacts were verified complete rather than re-generated: all three YAML files parse fully with `yaml.safe_load`, correct top-level structure (SCAFFOLD.yaml has neither forbidden design key; DIFFICULTY and CORNER each have exactly their single required top-level key), and file tails show proper YAML endings. Artifact contents: SCAFFOLD.yaml 1378 lines — 12 entities, 7 state machines, 6 calculations, 38 validations, 39 endpoints, 38 errors, 9 roles, complexity_profile primary_archetype=compliance_audit, secondary=event_sourcing, layers=[cascading_side_effects, dual_variant_calculation, optimistic_concurrency, rate_threshold_triggers], role_model=segregation_of_duties, consistency_model=immediate. SCAFFOLD_DIFFICULTY_DESIGN.yaml 769 lines — 9 rules × 2 instances = 18 instances (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant). SCAFFOLD_CORNER_DESIGN.yaml 1484 lines — 9 sections, 58 instances. Total test-source instances: 76. Endpoint count 39 (≤40, inside the impl-gen safety envelope).

## Step 3: Copy shared files — 2026-10-01T10:13:49.475Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (53 lines).

## Step 4: Generate PRD — 2026-10-01T10:31:51.433Z

PRD generation complete. All three hard contracts verified mechanically.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3363_legal_research_database_licensing_editorial_enhancement_citator/workspace/PRD.md` — 304 lines, ends cleanly at §5 with the `ERR_STALE_VERSION` table row.

**Section list:**
- §1 Introduction (2 paragraphs)
- §2 Global Specifications: 2.1 RBAC (9 roles, identity prose for entity-backed `FirmAdmin`/`Researcher` vs 7 opaque roles), 2.2 API Response Structure (byte-identical to the canonical verbatim block — verified), 2.3 Pagination, 2.4 Logical Clock & Lazy Overdue Materialization, 2.5 Common Resource Properties (incl. the UsageEvent/RoyaltyStatement `common_fields: false` exception), 2.6 Citator Treatment Scoring (full 6×4 weight matrix + 80/40 thresholds + both derivation variants), 2.7 Monetary Precision, 2.8 OCC (both rules), 2.9 Validation Cascade & Error Priority (full 38-priority ordering in prose), 2.10 Identifier Resolution & Reverse Reachability, 2.11 Interval Semantics
- §3 Business Logic: 3.1 Ingestion & Publish, 3.2 Citator Override, 3.3 Headnote Workflow, 3.4 Plans/Accounts/Subscriptions, 3.5 Seats & Metered Usage, 3.6 Invoicing & Cost Recovery, 3.7 Licensing & Royalties, 3.8 Removal Orders
- §4 Endpoint Definitions (4-column table, all 39 endpoints)
- §5 Error Code Catalogue (2-column table, all 38 errors)

**Hard-contract reports:**
- Contract 1 (Field-Name Coverage): 108/108 entity + endpoint input/query field names present in backticks, 0 missing — PASS (two passes; first pass caught `email`/`full_name`, repaired in §3.5, re-ran clean). All enum values and state names also verified present.
- Contract 2 (Rule Coverage): priority cascade expressed in §2.9; both OCC rules named with `expected_document_version`/`expected_subscription_version` + `ERR_STALE_VERSION`/412; all 27 state transitions with preconditions and cascades; all 6 calculations as reconstructible prose including the pinned per-component rounding (638+268=906 vs 905), cost-recovery waterfall (2624/1968/1312 → 2625/1969/1312), and royalty contrast (135 vs 148 cents); all `applies_to` scopes enumerated; sibling branches (FLAT_RATE/TRANSACTIONAL, PER_VIEW/REVENUE_SHARE, SEAL/REMOVE, APPROVE/REJECT) rendered with equal density — PASS. Note: `NET_TERMS_DAYS` has no value in the scaffold, so the PRD names it symbolically without inventing a number.
- Contract 3 (§3 Path Purity): 207 backtick tokens scanned in §3, 0 paths, 0 bare HTTP methods — PASS.

No pseudocode operators or fuzzy hedging anywhere outside code fences (scanned). The difficulty-design files were not touched.

Orchestrator verification: PRD.md on disk is 304 lines, clean head/tail, §1–§5 headings all present. ORCHESTRATOR FLAG for Step 6→7 hand-off: `NET_TERMS_DAYS` is an unpinned symbolic constant (PRD line 193 names it without a value) — grep the literals used by test_suite/test_helpers vs implementation/ before the first sweep to catch drift early.

## Step 5: Generate Unit Tests — 2026-10-01T11:11:57.253Z

All verification passes are green. Final summary:

## Files written

**`test_helpers/`** (under `/home/ubuntu/github/CodingPRD/tasks/task_3363_legal_research_database_licensing_editorial_enhancement_citator/test_helpers/`):
- `types.py` (364 lines) — 12 entity TypedDicts (UsageEvent/RoyaltyStatement correctly carry only `id` + `created_at`, no `version`/`updated_at`), 24 enums
- `constants.py` (57) — citator weight matrix, `SIGNAL_RED_MIN=80`, `SIGNAL_YELLOW_MIN=40`, bulk defaults 100/500, `DEFAULT_CLOCK_ISO`, and `NET_TERMS_DAYS = 30` (the design-pinned literal: issued 2026-09-10 → due 2026-10-10; PRD §3.6 names it only symbolically, defined here as a named constant per the hand-off-audit rule)
- `api_errors.py` (90) — all 38 error IDs with HTTP statuses, registered via `set_error_http_status_map`
- `api_client.py` (137) — 37 endpoint methods on `ApiClient(GenericApiClient)`
- `test_users.py` (51) — shared opaque-role headers + `make_firm_admin_headers` / `make_researcher_headers` / `make_attorney_editor_headers` (entity-backed identity threading)
- `assertions.py` (162), `factories.py` (163), `fixtures.py` (315) — composite setups: `setup_subscribed_user`, `setup_issued_invoice`, `create_citing_document`, `seal_document`, `advance_clock_days_past` (due_at-relative stepping), etc.
- `__init__.py` (162) — barrel export

**`test_suite/`**: `conftest.py` (50) + 10 test modules — `test_01_api_foundation.py` (161), `test_02_documents.py` (185), `test_03_citator.py` (242), `test_04_headnotes.py` (283), `test_05_removal_orders.py` (334), `test_06_subscriptions.py` (224), `test_07_seats.py` (238), `test_08_usage_events.py` (241), `test_09_invoicing.py` (370), `test_10_royalties.py` (213). Total 4,042 lines.

## Collection
`python3 -m pytest test_suite/ --collect-only -q` → **90 tests collected, 0 errors** (also pyflakes-clean, no skip/xfail markers, no scaffold references).

## Instances skipped (1)
- `Corner/validations/seat_double_assign_rejected` — the design pins `ERR_SEAT_ALREADY_HELD` (409), but PRD §2.9/§3.5 run the duplicate-email shape check first ("a duplicate is a shape violation rejected with `ERR_INVALID_REQUEST` (HTTP 400). Beyond shape, the gauntlet runs…"), so the asserted outcome contradicts the PRD's own cascade order; skipped per the PRD-first filter rather than weakened. The 3 `excluded_because:` stubs were not translated (their difficulty cross-references all resolve).

## Design-tag audit
90 tests: **0 untagged, 0 dual-tagged, 0 unresolved tags, 0 tags pointing at stubs**; every docstring ends with exactly one `Design:` line. All 18 difficulty instances carry ≥2 tests (36 tests); all 54 translated corner instances carry ≥1 (54 tests). All 120 PRD citations survive verbatim grep of `PRD.md`.

Key robustness choices: overdue/void tests read `due_at` back from the issued invoice and step the logical clock relative to it (valid for any net-terms value); the period-closed test keeps the clock at the issuance instant so the `ERR_INVOICE_PERIOD_CLOSED` gate — not the subscription-suspension gate — is what fires regardless of `NET_TERMS_DAYS`; all create endpoints assert explicit 201, transitions/reads 200.

Orchestrator verification: re-ran `pytest --collect-only` myself — 90 tests, 0 errors confirmed; grep shows exactly 90 `Design: ` tags (one per test), 0 skip/xfail, `NET_TERMS_DAYS = 30` at test_helpers/constants.py:36.

## Step 6: Generate Implementation — 2026-10-01T11:47:00.000Z

All 38 catalog errors have raise sites (empty diff). Implementation complete and verified.

## Summary

**Files written** (all under `workspace/implementation/`, 2,142 lines total):

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | Guarded pip install + `exec python3 app.py`, `$PORT`/0.0.0.0 |
| `requirements.txt` | 1 | flask>=3.0 |
| `app.py` | 61 | Flask entry, blueprint registration, ApiError/HTTP error handlers |
| `constants.py` | 83 | All pinned constants + enum domains |
| `db.py` | 86 | In-memory store, logical clock, id/timestamp/version helpers |
| `errors.py` | 59 | ApiError + full 38-error catalog with HTTP statuses |
| `middleware.py` | 47 | Lazy OVERDUE sweep + X-User-ID/X-User-Role auth + role decorator |
| `response.py` | 87 | `meta`/`response_type`/`data` envelope, pagination (limit/offset/total_count/has_more) |
| `serializers.py` | 66 | Per-entity serializers; computed `seats_used` |
| `util.py` | 130 | Shape validators (fields, enums, strict ISO dates, OCC ints) |
| `services/citator.py` | 57 | Citation normalization + weighted scoring (80/40 thresholds) |
| `services/billing.py` | 138 | Overdue materialization, auto-resume, invoice totals, cost-recovery waterfall |
| `services/compliance.py` | 57 | Removal-order apply/reverse cascades |
| `routes/clock.py` | 19 | Logical clock setter |
| `routes/documents.py` | 229 | Documents CRUD + publish cascade + citator override + citing-references |
| `routes/headnotes.py` | 123 | Headnote workflow with segregation of duties |
| `routes/commercial.py` | 345 | Plans, accounts, subscriptions, change-plan, status, seats, users |
| `routes/usage.py` | 141 | Usage-event gauntlet (scope, bulk-rate, matter-code) |
| `routes/billing.py` | 126 | Invoice generate/list/get/transition |
| `routes/licensing.py` | 172 | License agreements + royalty statements |
| `routes/removal.py` | 150 | Removal orders + transitions |

**Pinned constants** (PRD-symbolic values): `NET_TERMS_DAYS = 30` (constants.py:14); `DEFAULT_BULK_HOURLY_LIMIT = 100`, `DEFAULT_BULK_DAILY_LIMIT = 500` (constants.py:19-20, from scaffold defaults); `SIGNAL_RED_MIN = 80`, `SIGNAL_YELLOW_MIN = 40` and the full 6x4 `CITATOR_WEIGHTS` matrix (constants.py:23-39); `CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"` (constants.py:9). Entity `version` starts at 1 (db.py `stamp_new`).

**Coverage**: 39/39 endpoints implemented; all 38 error IDs from the catalog are raised with their pinned HTTP statuses (verified via catalog-vs-raisesite diff, empty). Validation cascade follows PRD §2.9 order exactly (auth → roles → ownership → shape → existence in pinned order → state gates → business-safety → constraints → referential → fiscal seat-capacity last). No seeded data; storage is in-memory dicts only.

**Boot smoke test**: port 18777 — no-header request returned 401 `ERR_UNAUTHENTICATED` in the correct envelope; authenticated list returned 200 empty array with pagination meta. Flow checks all passed: citation normalization ("123 F.3d  456" → "123 F3D 456"), publish cascade with citator recompute (100/RED), the PRD's worked invoice example (total 5906 = 5000 + per-component-rounded 638+268; allocation 3282/1968/656), lazy OVERDUE + suspension + auto-resume on PAID, SEAL/REMOVE cascades with reversal restoring scores (and headnotes staying retracted per spec), REMOVED read → `ERR_DOCUMENT_REMOVED`, OCC 412 on stale version, headnote author/segregation gates, PER_VIEW royalty (3×45=135), half-open exclusive-window adjacency. Fresh reboot on 18778 confirmed empty store + clock default. All smoke servers killed by exact PID (43292/43294, 73755/73757); ports verified closed; no other pipeline processes touched. Test suite was not run and test files were never read.

Orchestrator hand-off audit (run independently): all 22 impl files present on disk; constants grep shows NO drift — impl `NET_TERMS_DAYS=30`/`CLOCK_DEFAULT_ISO=2026-09-01T00:00:00Z`/`SIGNAL_RED_MIN=80`/`SIGNAL_YELLOW_MIN=40`/bulk 100/500 all match test_helpers/constants.py exactly; error catalog diff empty in all three directions (impl 38 = tests 38 = PRD 38); 39 Flask route decorators counted across routes/; smoke-test ports 18777/18778 both closed.

## Step 7: Run Tests and Iterate — 2026-10-01T11:56:05.710Z

Clean 8-round parallel sweep achieved: all 8 rounds pass 90/90.

## Summary

**Iterations run:** 2 (initial sweep → one fix → final clean sweep).

**Root cause (all 6 failures, one defect):** Every entity serializer emitted `id` as `uuid.uuid4().hex` — 32 hex chars with no hyphens. The shared assertion library `is_valid_uuid` (and PRD §2.5's "server-minted UUID") requires the canonical hyphenated `8-4-4-4-12` form. Six tests across documents, headnotes, usage events, invoicing, and royalties all tripped on the same `"{Entity}.id must be a server-minted UUID"` assertion, deterministically in all 8 rounds.

**Tests deleted:** none. STEP 1 passed for all failures — PRD §2.5 verbatim: "`id` — a server-minted UUID with no type prefix, unique across the system." The canonical hyphenated string is the uniquely derivable reading ("with no type prefix" anticipates prefixes like `doc_`, not dash-stripping), so the tests were faithful and the implementation was at fault (STEP 3).

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:**
- `workspace/implementation/db.py` — `new_id()`: changed `uuid.uuid4().hex` to `str(uuid.uuid4())` so every entity id is the canonical hyphenated UUID PRD §2.5 requires. Verified no other code assumed the 32-hex form (grep for hex/regex/route-converter patterns came back empty), and smoke-tested a document create returning `id: "8e801d6e-ea29-495f-9e6a-41491545e6aa"`.

**Deliverables confirmed:** `results.1.json` … `results.8.json` from the final clean sweep (all `passed=90, failed=0`) are left in place under `workspace/implementation/`.

Orchestrator verification: all 8 results.*.json present on disk, each `passed=90 failed=0 total=90`; db.py:52 confirmed `return str(uuid.uuid4())`. Step 7 had 1 implementation/ fix and 0 deletions / 0 test-side fixes → Step 8 is NOT skipped.

## Step 8: Finalize PRD — 2026-10-01T12:02:35.690Z

The diff is exactly one revised line; both files are 304 lines. Task complete.

## Summary

**Outcome chosen: EDITED** (not byte-identical). One line revised.

**Verification behind the outcome.** PRD §2.5's wording — "`id` — a server-minted UUID with no type prefix, unique across the system" — does not unambiguously pin the hyphenated form. Direct empirical evidence: the Step 6 implementer read exactly this PRD and emitted `uuid.uuid4().hex` (32 hex chars, no hyphens), which Python's own docs describe as a UUID representation. "With no type prefix" forbids *added* prefixes (e.g. `doc_…`); it does not reach the serialization-shape question, since `.hex` adds no prefix — it is an alternate standard rendering of the same UUID value. Per the task instruction ("if the wording is at all ambiguous about the serialized string shape, add a minimal clarifying clause"), I added one clause. I also empirically confirmed the shared runner's `is_valid_uuid` accepts `8e801d6e-ea29-495f-9e6a-41491545e6aa` and rejects `8e801d6eea29495f9e6a41491545e6aa`.

**Line counts / delta:** PRD.md 304 lines, PRD_FINALIZED.md 304 lines (0% line-count delta; 1 of 304 lines revised in place, ~0.33% of lines, +120 chars).

**Change log:**
- §2.5 (Common Resource Properties) — revise — the `id` bullet now reads "a server-minted UUID rendered in its canonical hyphenated string form (five hexadecimal groups of 8-4-4-4-12 characters, as produced by a standard UUID library's string conversion), with no type prefix, unique across the system" — `workspace/implementation/db.py:50-52` (`new_id()` returning `str(uuid.uuid4())`).

**Pre-edit search log (mandatory, one edit):**
- (a) Subject: the serialized string shape of the system-managed resource `id` property.
- (b) Impl paths enumerated and read/grepped: (1) `db.py:50-52` sole minting site `new_id()` → `str(uuid.uuid4())`; (2) `db.py:65-80` `stamp_new()`/`stamp_ledger()` the only two attachers of `id`, covering all 13 entity types; (3) `serializers.py:6-66` all 13 serializers pass `id` through verbatim via `_public()`; (4) `routes/*.py` untyped Flask string converters, ids consumed as opaque dict keys with no format validation; (5) repo-wide greps `uuid|new_id|\.hex` hit only `db.py`; no second minting site, no consumer assuming any id format; (6) `response.py:18-20` `api_request_id` minted independently (`req_` + 20 alphanumerics), governed by §2.2 not §2.5; (7) foreign-key fields all copy `new_id()` values; `author_editor_id`/`user_id` copy opaque `X-User-ID` per §2.1 outside §2.5 scope.
- (c) Wording adjustment: the clause describes only the *output* rendering; mandates no specific case beyond standard string conversion; constrains nothing about request ids, foreign keys, or input handling; keeps pre-existing "no type prefix" and "unique across the system" clauses verbatim.

No files under `implementation/`, `test_suite/`, or `test_helpers/` were touched.

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` shows exactly the one reported line (§2.5 id bullet); both files 304 lines; find-newer check shows ZERO source files under implementation/, test_suite/, test_helpers/ modified after the clean-sweep results — sweep evidence intact.

## Step 9: Complete PRD — 2026-10-01T12:20:45.483Z

The diff confirms exactly the 18 intended edits at the expected lines. Task complete.

## Summary

**Source vs output:** `PRD_FINALIZED.md` 304 lines / 54,118 bytes → `PRD_COMPLETED.md` 304 lines / 56,563 bytes (char delta +2,423; all edits in-paragraph, no lines added or removed).

**Counts:** 17 ambiguity-pins, 1 mismatch-revision.

**Changes (one per bullet):**
- §2.1 — insert — ambiguity — FirmAdmin account-ownership comparison applies only where an endpoint performs an ownership check (seat management); list/read endpoints do no account scoping — implementation/routes/commercial.py:268
- §2.2 — insert — ambiguity — `api_request_timestamp` is read from the logical clock, never wall-clock — implementation/response.py:26, implementation/db.py:60-62
- §2.3 — insert — ambiguity — out-of-range/non-integer `limit` and negative `offset` are `ERR_INVALID_REQUEST`; `created_at` ties break by insertion order; `has_more` = offset + page size < total_count — implementation/response.py:58-87
- §2.4 — insert — ambiguity — clock setter accepts any well-formed ISO 8601 instant, no monotonicity constraint — implementation/routes/clock.py:15-19, implementation/util.py:112-125
- §2.5 — insert — ambiguity — `version` starts at 1; `updated_at` equals `created_at` at creation — implementation/db.py:65-72
- §2.9 — insert — ambiguity — ownership rules evaluate against the already-resolved target, so an unresolvable path identifier's not-found error preempts the ownership check — implementation/routes/commercial.py:262-269, implementation/routes/headnotes.py:87-91
- §2.9 — revise — mismatch — REMOVED-document screening scoped to reads (single-doc read + citing-reference lookup); writes (publish, citator override, headnote creation, order docketing) resolve REMOVED docs normally and obey only their own state gates — implementation/routes/documents.py:96-97,110-111 vs 146-178,216; implementation/routes/headnotes.py:44-45; implementation/routes/removal.py:32-33
- §2.10 — insert — ambiguity — enum-valued filters outside their domain are `ERR_INVALID_REQUEST`; identifier-valued filters are unresolved and just yield an empty page — implementation/util.py:50-57
- §3.1 — insert — ambiguity — omitting `direction` on citing-references returns the union of both directions — implementation/routes/documents.py:113-127
- §3.1 — insert — ambiguity — `references` list may be empty; duplicate entries each create their own CitingReference row — implementation/routes/documents.py:137-144,188-199
- §3.4 — insert — ambiguity — omitted numeric plan fields default to 0 except `monthly_fee_cents` (null when omitted on TRANSACTIONAL); wrong-model fields stored but never consulted; `volume_discount_pct` is a fraction (0.15 = 15%) — implementation/routes/commercial.py:66-84, implementation/services/billing.py:75
- §3.4 — insert — ambiguity — change-plan is not gated on subscription status; only the version guard applies — implementation/routes/commercial.py:199-212
- §3.4 — insert — ambiguity — cancellation also clears `suspension_reason` to null — implementation/routes/commercial.py:238-239
- §3.5 — insert — ambiguity — both seat actions answer 200 with the updated subscription object — implementation/routes/commercial.py:304,318
- §3.5 — insert — ambiguity — trailing-hour window is `(now − 60 min, now]`: lower bound exclusive, upper inclusive — implementation/routes/usage.py:73-81
- §3.6 — insert — ambiguity — invoice generation is not gated on subscription status — implementation/routes/billing.py:32-42
- §3.6 — insert — ambiguity — `NET_TERMS_DAYS` pinned to 30 — implementation/constants.py:14, implementation/routes/billing.py:108
- §3.6 — insert — ambiguity — cost_recovery_allocation rows are emitted ordered by `matter_code` ascending — implementation/services/billing.py:126,135-138

**Dead-code findings:**
- implementation/routes/commercial.py:284-290 — the `ERR_SEAT_ALREADY_HELD` (409) check inside seat ASSIGN is unreachable. The account-wide email-uniqueness shape check at commercial.py:278-280 rejects every duplicate email with `ERR_INVALID_REQUEST` (400) first, so no request can ever reach the already-held branch. It implements PRD §3.5's "the account must not already hold an `ACTIVE`-seated user under that same email (`ERR_SEAT_ALREADY_HELD`)" and its §2.9 cascade position; as shipped, every duplicate-email assignment yields 400, never 409. Report-only; code untouched.

**Missing-behavior findings:** none — every other PRD rule has a live implementation path (the shadowed 409 above is the only PRD-pinned response that cannot actually occur, and it is reported under dead code).

Orchestrator verification: PRD_COMPLETED.md on disk is 304 lines / 56,563 bytes; diff vs PRD_FINALIZED.md shows 38 changed lines consistent with 18 in-paragraph edits; spot greps confirm §2.3 (ERR_INVALID_REQUEST for bad limit/offset, creation-(insertion)-order tie-break, has_more definition), §3.5 trailing-hour window `(now − 60 minutes, now]`, §3.6 NET_TERMS_DAYS=30 pin. find-newer check post-Step-9: ZERO source files under implementation/, test_suite/, test_helpers/ modified after the clean sweep; all 8 results.*.json still in place. Note: the dead-code finding is consistent with Step 5's skipped instance `Corner/validations/seat_double_assign_rejected` (skipped for exactly this 400-preempts-409 cascade reason), and PRD §2.9 pins the cascade order, so a faithful reader's 409 check would be equally unreachable — behavioral equivalence preserved.
