# Worklog — task_2938_presort_mail_service_provider_operations

## Step 1: Create task directory — 2026-09-05T19:01:15.102Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2938_presort_mail_service_provider_operations` and its `workspace/` subdirectory. Index 2938 was pre-assigned by the orchestrating command (no `./tasks/` scan performed — concurrent pipelines on this host make auto-allocation collide).

## Step 2: Generate scaffold — 2026-09-05T20:40:00.000Z

Subagent summary (verbatim):

All three scaffold artifacts for task 2938 are complete and lint-clean.

**Lint verdict (verbatim)**

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           .../SCAFFOLD.yaml
  Difficulty design:  .../SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      .../SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    56
  §1.1 entities declared:     13
  §1.8 instances scanned:     22
  §1.9 instances scanned:     48
  Calls scanned (§1.8+§1.9):  1020

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Deliverables** (all non-empty, YAML-parsed, single correct top-level key in each design file; `SCAFFOLD.yaml` contains neither design key)
- `SCAFFOLD.yaml` — 2623 lines / 136 KB
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2055 lines / 141 KB
- `SCAFFOLD_CORNER_DESIGN.yaml` — 2693 lines / 186 KB

**Counts**
- SCAFFOLD §1.1–§1.7: 13 entities, 9 state machines, 2 concurrency rules, 11 calculations, 46 validations, 56 endpoints, 54 error codes, 5 roles (`api_prefix: "/"`, consistency model immediate, logical clock default 2026-08-01T00:00:00Z).
- Difficulty index: 9 difficulty rules, 22 instances.
- Corner index: 9 sections, 75 instances = 48 with full `test_recipe` + 27 `excluded_because:` stubs. Per section: entities 11, state_machines 11, calculations 13, validations 9, endpoints 5, errors 13, rbac 5, cross_cutting_complexity_layers 7, consistency_model 1.
- Verified programmatically: no stub carries a `test_recipe`, every stub's cited `difficulty_instance` resolves to a real §1.8 instance name, every stub has a rationale, all 75 corner names are unique and disjoint from the 22 difficulty names, and every non-stub instance has `claim_type` + `grounds` + `distinguishing_aspect` + `test_recipe`.

**Two fixes made to reach clean lint**
1. `FK_REVERSE_UNREACHABLE` x12 — `scaffold_lint.py`'s sub-resource form matches the literal parent placeholder `{id}`, so descriptively-named parent placeholders (`/clients/{client_id}/permit-accounts`) were invisible to it even though every FK already had a sub-resource GET. Renamed all first-segment path placeholders to `{id}` across `SCAFFOLD.yaml` (206 occurrences, incl. state-machine triggers, `applies_to`, and role operation lists) and the 21 matching `grounds:` references in the two design files; the nested child placeholder in `DELETE /commingle-batches/{id}/members/{batch_member_id}` was deliberately left named to stay unambiguous.
2. Two call-level violations in the new rbac section: `GET /postage-statements/{id}/findings` was issued `as: PresortOperator` (not in that endpoint's roles) -> switched to `BureauAdmin` with the assert reworded; and the whitespace-header call used an undeclared `GET /clients` collection -> switched to `GET /clients/<bogus-uuid>` (auth at priority 1 still precedes existence).

**Flag for the orchestrator:** the meta-directive line `Generate task harder than expert level!` sits inside `SCAFFOLD.yaml`'s `scenario:` key at line 8. Standing project convention is to strip that single line after Step 2 so it does not leak into PRD.md.

### Orchestrator action taken after Step 2

Stripped the difficulty-directive line (and its trailing blank line) from `SCAFFOLD.yaml`'s `scenario:` block, leaving the scenario text itself verbatim. Re-verified: `grep -rn "harder than expert"` over the task dir now returns nothing, and `SCAFFOLD.yaml` still parses as YAML with 13 top-level keys. This prevents the difficulty directive from reaching the doc generator via the scaffold.

## Step 3: Copy shared files — 2026-09-05T20:41:00.253Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T20:53:00.000Z

Subagent summary (verbatim):

The PRD is complete and all three hard contracts pass.

## Deliverable

`workspace/PRD.md` — **462 lines**, ends cleanly on the final `ERR_INSUFFICIENT_POSTAGE_BALANCE` row of the §5 table.

## Section list (no numbering gaps)

- §1 Introduction (3 paragraphs)
- §2 Global Specifications & System-Wide Principles — 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim from `section-2.2-response-structure.md`) · 2.3 Pagination · 2.4 Resource Identity, Timestamps and Revision Counters · 2.5 The Logical Clock · 2.6 Addressing Nested Resources · 2.7 Money, Mills and Rounding Discipline · 2.8 Optimistic Concurrency · 2.9 Rejection Precedence: the Validation Ladder · 2.10 Segregation of Duties and the Conservation Invariants · 2.11 Cascade Integrity and the Documentation Chain
- §3 Business Logic & Workflows — 3.1 Onboarding Mailers and Funding Their Permits · 3.2 Tendering Mail and Clearing Address Hygiene · 3.3 The Entry-Point Network · 3.4 Commingling: Pooling Jobs to Earn a Deeper Tier · 3.5 Containerization, Documentation and Closing Sortation · 3.6 The Postage Statement: Filing, Verification and Correction · 3.7 Dock Appointments, Departure and Deposit · 3.8 Service-Level Tracking and Client Billing
- §4 Endpoint Definitions (4 columns, 56 rows)
- §5 Error Code Catalogue (2 columns, 54 rows)

## Coverage audit vs scaffold

| Category | Scaffold | Covered |
|---|---|---|
| Entities | 13 | 13 (all 95 `fields[].name` verbatim in backticks; `AddressHygieneRun`/`VerificationFinding` explicitly stated as `id`+`created_at` only) |
| State machines | 9 | 9 / all 43 transitions (from->to, every precondition paired with its error, every side effect) |
| Concurrency rules | 2 | 2 (write endpoint + `expected_permit_account_version` / `expected_batch_version` + `ERR_STALE_PERMIT_VERSION` 412 / `ERR_STALE_BATCH_VERSION` 412) |
| Calculations | 11 | 11, prose-only, all constants embedded (tier 500/3000/15000; discounts 800/1500/2200 bp; base rates 64/32/28c; 95-day move update; 95.00% floor; tray 150/1, pallet 250; class adders 0/1/2; zone weights 1/2/3/5; 500 bp major threshold, 2500/10000 bp surcharges; 2500c minimum fee, 0/500/1200 bp volume tiers; rework threshold 2) |
| Validations | 46 | 46, rendered as the explicit ascending ladder in §2.9 with every `applies_to` endpoint enumerated |
| Endpoints | 56 | 56 in §4; every `input`/`query_params` identifier (51) present in prose |
| Error codes | 54 | 54 in §5, and every one also referenced in §2/§3 narrative |
| Roles | 5 | 5, each named with its `identity:` translated (`ClientContact` entity-backed on `Client`; other four opaque) |

## Hard Contract reports

```
Field coverage check:
- entities[].fields: 95 required, 95 present, 0 missing
- endpoints[].input/request_body: 51 required, 51 present, 0 missing
- endpoints[].query_params (limit/offset/filters): included above, 0 missing
- state enumeration values: 42 required, 42 present, 0 missing
- enum-type field values: all present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 46 checked, 46 expressed in prose (explicit ordered ladder), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + occ_field + error_id + http_status), 0 missing
- state_machines[].transitions: 43 checked, 43 fully expressed, 0 missing
- calculations[]: 11 checked, 11 fully expressed incl. variants and pinned evaluation orders, 0 missing
- validations[] conditions: 46 checked, 46 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 56 endpoints checked, all side-effect sets expressed, 0 missing
- entities[].fields[] structured content: 95 checked, defaults/initial values/types reconstructible, 0 missing
- sibling-branch symmetry: 8 groups checked (verify 3-way fork; permit ACTIVE/HOLD->CLOSED; client & facility status pairs; job cancel from 2 states; statement VOID from DRAFT/SUBMITTED incl. supersede; shipment cancel from 2 states; standalone vs commingled rate variants; zone- vs piece-weighted indexes), 8 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 777
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Notes: the withheld `SCAFFOLD_DIFFICULTY_DESIGN.yaml` / `SCAFFOLD_CORNER_DESIGN.yaml` and all sibling task directories were never opened. No meta/difficulty language, pseudocode operators, or fuzzy hedging words appear in the PRD (verified by grep). One judgement call worth flagging: for `MailJob` creation the entity table gives `address_quality_pct`/`move_update_compliant` defaults of `null`, while the `POST /mail-jobs` `side_effects` say "initialised to 0" and "initialised to false" — I followed the endpoint's explicit initialisation, since that is what a creation-response assertion would check. Scratch was cleaned with `rm -rf .scratch/step4` only; `worklog.md` untouched.

### Orchestrator truncation check after Step 4

Verified per the known doc-generator truncation failure mode: `PRD.md` is 462 lines, `grep -n '^#'` shows 27 headings with no numbering gaps (§1 -> §2.1..§2.11 -> §3.1..§3.8 -> §4 -> §5), and `tail -12` ends on a complete markdown table row (`| ERR_INSUFFICIENT_POSTAGE_BALANCE | 402 |`) at the close of the final section — not mid-sentence. No regeneration needed. Also grepped for `harder than expert` / `scaffold` / `test_recipe` in PRD.md: no hits, so the difficulty directive and scaffold-only vocabulary did not leak.

## Step 6: Generate implementation — 2026-09-05T21:23:00.000Z

(Steps 5 and 6 were launched concurrently; Step 6 returned first. Logged here in step order.)

Subagent summary (verbatim):

Step 6 complete. The implementation is finished, verified, and no processes or scratch files are left behind.

## Deliverables

All under `workspace/implementation/` (3130 lines total, 21 files, `python3 -m py_compile` clean on all 19 modules):

| file | lines | role |
|---|---|---|
`app.py` | 82 | blueprint registration, global request lock, `ApiError`/`HTTPException`/`Exception` handlers, `app.run(host="0.0.0.0", port=$PORT)` |
`start.sh` | 8 | `exec python3 app.py` in the foreground, reads `$PORT` (default 10000), chmod +x |
`requirements.txt` | 1 | `Flask>=2.2` |
`errors.py` | 86 | all 56 `error_id` -> HTTP status + default messages |
`util.py` | 111 | ids, `req_`+20-char request ids, ms-truncating instant parse/format, `round_half_up_div`, `quantize` |
`store.py` | 81 | 13 in-process dict collections, monotonic `_seq`, logical clock default `2026-08-01T00:00:00Z` |
`envelope.py` | 109 | object/array/error envelopes, pagination reader, `listed()` |
`shape.py` | 197 | auth (rungs 1->2), body reader, unknown-field-first validator, field checkers |
`enums.py` | 68 | every enum domain |
`calc.py` | 200 | tiers, rate mills, postage, pro-rata pool, quality pct, container minima, zone/days, findings, service-level, invoice discount/fee |
`serialize.py` | 264 | one serializer per entity |
`domain.py` | 252 | lookups with per-entity 404 ids, ordered child collections, `derive_batch`, allocation writer, dock occupancy, invoice overlap |
`cascades.py` | 238 | sortation close, accept-clean, accept-with-adjustment, return-for-correction (incl. rework suspension), revise, void/supersede, deposit |
`routes_clients.py` | 241 | 8 endpoints |
`routes_permits.py` | 121 | 5 |
`routes_jobs.py` | 249 | 8 |
`routes_facilities.py` | 89 | 4 |
`routes_batches.py` | 258 | 11 |
`routes_statements.py` | 235 | 8 |
`routes_shipments.py` | 129 | 5 |
`routes_misc.py` | 111 | 7 (containers, SLRs, invoice payment, `_clock`) |

**Endpoints registered: 56 / 56** (enumerated from `app.url_map`; exact match to PRD §4, no extras).

**No seeding, no persistence:** storage is plain dicts on a module singleton; a fresh boot returns `total_count: 0` for every list and the clock reads its documented default. No file, SQLite, or `/tmp` artifact is created.

## Smoke tests (live HTTP)

Booted via `PORT=39381 bash start.sh` and later a clean re-boot on 39417. Verified full happy path: onboarding -> funding -> tender -> hygiene -> pooling -> containers -> sortation -> statement prepare/submit -> findings -> verify (all three outcomes) -> booking -> depart -> clock advance -> deposit -> delivery scan -> service-level -> invoice -> payment. Plus return->revise->re-sort->second-return->client suspension, member withdrawal re-derivation, void/supersede, dock aggregate capacity with touching windows, no-show sweep, container qualification boundaries (149/150/1), and the negative ladder (unknown field, bad enum, bad datetime, bool-as-int, malformed JSON, array body, pagination bounds, 401 whitespace header, 403 wrong role, per-entity 404s).

All four PRD worked examples reproduce exactly. Final confirming run: FIVE_DIGIT/FIRST_CLASS at a 2000bp facility -> `rate_mills 39936`, `batch_postage 1198080`; `ERR_PERMIT_HAS_RESERVED_FUNDS` on close-while-reserved; `ACCEPTED_CLEAN` with `adjustment 0` releasing reserved to 0; invoice `30000 pieces -> postage 1198080 + service_fee 7920 = total 1206000` with the 1200bp volume discount; `ERR_INVALID_STATEMENT_STATE` on re-verify; `ERR_INVALID_SHIPMENT_STATE` on deposit-before-depart.

Both smoke servers were killed by exact PID (1566192, 1592549 — verified as mine via `/proc/<pid>/cwd`); 73 unrelated `python3 app.py` processes on this host were left untouched. Ports 39381/39417 now have no listener.

## Interpretation decisions where the PRD was ambiguous

- **PRD over scaffold** on two conflicts: `address_quality_pct` starts at `0` (not 100) and `move_update_compliant` starts `false` on a job with no hygiene run.
- `created_at`/`updated_at` use real wall-clock; every domain instant (fee lapse, window checks, `deposited_at_utc`, `mailed_at_utc`) uses the logical clock. PRD §2.5 explicitly makes `api_request_timestamp` a real server timestamp.
- Every list endpoint is paginated with the §2.3 envelope; unknown **query** params are tolerated, unknown **body** fields are rejected first inside rung 3.
- Batch-state preconditions that the ladder does not number (submit requires `SORTED`, revise requires `REWORK`) raise `ERR_INVALID_BATCH_STATE` immediately after rung 13.
- Status-transition source mismatches reuse the entity's existing id (`ERR_CLIENT_SUSPENDED`, `ERR_PERMIT_ACCOUNT_NOT_ACTIVE`, `ERR_ENTRY_FACILITY_CLOSED`) since §5 defines no generic state error.
- Negative `move_update_age_days` -> `ERR_INVALID_PIECE_COUNT`, per §3.2's "Any of those bounds".
- Findings carry a private `_episode` (= `revision_index`) so cumulative severity and `adjustment_cents` reset per revision episode while history is retained; `_episode` is never serialized.
- ClientContact scoping (`ERR_CLIENT_SCOPE_VIOLATION`) is applied to exactly the nine rung-7 endpoints.
- Requests are serialized under one lock so no partial cascade is ever observable.

## Step 5: Generate unit tests — 2026-09-05T21:57:00.000Z

(Launched concurrently with Step 6; returned second. Logged here in step order.)

Subagent summary (verbatim):

Step 5 is complete. All 18 test modules and all 9 helper modules are written, compile, lint clean, and import cleanly.

## Deliverables (absolute paths)

`tasks/task_2938_presort_mail_service_provider_operations/`

**test_helpers/** — 3099 lines: `__init__.py` 1, `api_client.py` 344 (57 endpoint methods), `api_errors.py` 171, `assertions.py` 457, `constants.py` 316, `factories.py` 331, `fixtures.py` 1104 (24 world builders), `test_users.py` 146, `types.py` 229.

**test_suite/** — 9412 lines, `conftest.py` 18 plus 18 test modules: 01 dual_variant_calculations 299/9 tests, 02 combinatorial_formulas 412/11, 03 non_linear_state_machines 344/9, 04 transitive_cascades 339/11, 05 priority_pair_validation_conflicts 341/12, 06 boundary_precision_checks 400/11, 07 cross_entity_state_dependencies 389/10, 08 resource_temporal_overlap 305/8, 09 compensating_invariants 357/10, 10 entity_surfaces 1024/20, 11 lifecycle_transitions 1087/23, 12 derived_figures 661/14, 13 validation_gates 565/10, 14 endpoint_behaviours 555/11, 15 error_catalog 938/17, 16 access_control 636/11, 17 concurrency_and_pagination 532/9, 18 immediate_consistency 210/5.

**211 test functions.**

## Coverage — nothing skipped

Machine-audited: every test docstring ends with exactly **one** `Design:` line, and every tag resolves to a real instance in the right section.

- **Queue A (Difficulty): 22 of 22 live instances translated.**
- **Queue B (Corner): 48 of 48 live instances translated.** The index's other 27 corner instances carry `excluded_because: difficulty_instance: ...` (they are the index's own deliberate cross-references to queue A) and were correctly not re-emitted.

Also verified: every quoted PRD fragment is a literal substring of `workspace/PRD.md` (whitespace-normalised), and no docstring mentions the scaffold or a design-doc section.

## Two helper bugs found and fixed (relevant to Step 7)

1. **List-envelope shape.** `fixtures.list_container_records` did `get_success_data(...)["items"]` and `assertions.validate_unpaginated` expected `data` to be an object with `items` plus a nested `meta`. PRD §2.2 puts the **array in `data`** and the four pagination fields in the envelope `meta`, which is also what the runner's `validate_paginated` assumes. Unfixed, this would have blown up `build_deposited_world`/`build_scanned_world` with `TypeError: list indices must be integers` — i.e. a whole-file wipeout in test_01 masquerading as an implementation defect. Both are corrected; `validate_unpaginated` now checks `response_type == "array"` and the envelope meta.
2. **No 204 validator existed.** `validate_success` demands an envelope, so it cannot validate the 204/no-body member withdrawal; added `assert_no_content` to `assertions.py`.

## PRD-first adjudications (PRD won in every case)

- **An `OPEN` batch with members is already priced.** §3.4: "Every change of membership immediately re-derives the batch's price... While the batch is `OPEN`, this three-stage derivation writes each member's `share_basis_pct` and `allocated_postage_cents`." Two of my earlier assertions wrongly expected `NONE/0/0` on an OPEN batch that has members; corrected to the membership-derived figures (test_07: `THREE_DIGIT`/26384/79152; test_06: a lone 1200-piece pool at `BASIC`/28556 mills/34267 cents with share 100.0000). Only a batch at creation, with zero members, reads `NONE/0/0` (§3.4 line on batch opening) — test_11 asserts that case correctly. A misleading `fixtures.build_pooled_world` docstring saying an OPEN batch "carries no tier, no rate and no postage" was also corrected.
- **`MailJob.accepted_piece_count` at creation** — the index says null; §3.2 says "starts equal to `declared_piece_count`". Asserted the PRD value.
- **Sort trigger role** — a queue-A chain said `BureauAdmin`; `POST /commingle-batches/{id}/sort` is `PresortOperator`-only. Called as `PresortOperator`.
- **Whitespace-only auth headers** — `requests`/urllib3 raise `InvalidHeader` before a spaces-only value can leave the process, so those variants send `""`, which §2.1 covers explicitly ("absent, empty, or consists only of whitespace").
- **`$.data[0]` captures** resolved by id via `find_by_id`, since the PRD fixes no ordering for the members list.
- **Dropped one unsupported sub-assertion**: the index's claim that `created_at == updated_at` on a fresh row is nowhere in the PRD.
- **Arithmetic error in the index (worth flagging):** `dual_variant_calc/standalone_versus_commingled_rate_divergence` claims the pooled rate is "26384, not 26383 (which is what flooring twice yields)". Double-flooring actually reproduces 26384 exactly (floor(32000x8500/10000)=27200, floor(27200x9700/10000)=26384), so 26383 is unreachable and not PRD-derivable. The test therefore asserts the single-quotient floor plus a floor-not-round-up bound, and omits the unreachable counter-value.

## One deliberately isolated risk

`test_17` asserts that an undeclared **query** filter on the mail-job list returns 400 `ERR_INVALID_REQUEST`. Ladder rung 3 is phrased around the body, while §3.2 enumerates that endpoint's filters exhaustively. It is kept in its own single test so that if Step 7 judges the reading too aggressive, only that one test is affected.

Scratch (`.scratch/step5/`) deleted; the `.scratch` parent left in place. Nothing was written under `workspace/`, `worklog.md`, `PRD.md` and `SCAFFOLD*.yaml` were not touched, no server was started or killed, and no pytest was run.

### Orchestrator note

Verified `test_helpers/` and `test_suite/` are at the task root (not under `workspace/`) — the known misplacement failure mode did not occur. Step 6's impl generator ran fully concurrently and `test_suite/` did not exist on disk when it started, so its physical isolation from the test artifact held.

## Step 7: Run tests and iterate — 2026-09-05T22:57:00.000Z

Subagent summary (verbatim):

Clean sweep achieved. Storage stays in-memory only (no sqlite/file/tmp persistence), scratch removed, `worklog.md`, `PRD.md` and the SCAFFOLD files untouched.

## Summary

**Iterations run:** 2 (each a full 8-round parallel stability sweep under `setsid`).

Sweep 1 produced 6 failures, byte-identical in all 8 rounds — fully deterministic, no load-induced flakiness at all. All 6 traced to just two root causes.

**Tests deleted (1):**
- `test_17_concurrency_and_pagination.py::TestFilteredPaginationAcrossAMutation::test_an_undeclared_query_filter_is_rejected_rather_than_ignored` — **STEP 1b unique-derivability collapse (coverage silence on query-string scope).** This is the risk Step 5 flagged, adjudicated on PRD text. Every "unknown field" sentence in the PRD is explicitly scoped to the *body*: §2.4 "a **body** that includes one is rejected as an unknown field"; §2.8 "supplying one is an unknown field"; ladder rung 3 "the **body** parses, contains every field the endpoint requires, every field holds the declared type... Unknown fields are rejected." No PRD sentence states that an undeclared *query parameter* is rejected. §3.2's "The list accepts optional `client_id`, `permit_account_id`, `commingle_batch_id` and `status` filters" states what is accepted, not that anything else is refused; §2.3 only covers out-of-bounds `limit`/`offset` *values*, not unknown parameter *names*. Two PRD-faithful implementations exist — (A) rung 3 is scoped by its own clause to the body, so unknown query params are ignored (Step 6's choice); (B) "unknown fields" covers any client-supplied input, so they are rejected. Both readings are articulable, so the test goes.

**Fixes applied to `test_helpers/` (1 file, fixing 5 tests):**
- `fixtures.py` — `setup_cleared_job` returned the job snapshot from the *tender* call and never refreshed it after recording the hygiene run, so `world.job` held pre-hygiene values (`status` still `RECEIVED`, `accepted_piece_count` still equal to `declared_piece_count`). PRD §3.2 states the run's derived measures are "**mirrored onto the job**" and that "Recording a pass on a job in `RECEIVED` drives it `RECEIVED -> HYGIENE_CLEARED`", and the fixture's own docstring promises a job that "sits in `HYGIENE_CLEARED`". Added a `read_mail_job` primitive and a re-read at the end of the builder. This was one upstream fixture bug masquerading as 5 independent implementation defects across 3 modules (`assert 500 == 499`, `assert 1250 == 1200` x2, `RECEIVED != HYGIENE_CLEARED`). Verified no consumer depended on the stale snapshot — the only other reads of `.job[...]` are `["id"]` in test_11.

**Fixes applied to `test_suite/`:** none beyond the one deletion.

**Fixes applied to `implementation/`:** none. No implementation defect was found; the PRD-faithful implementation was correct on every one of the 6 failures, and I did not weaken any PRD-required check to accommodate a fixture.

**Final sweep evidence** (`results.1..8.json`): `231/231, 231/231, 231/231, 231/231, 231/231, 231/231, 231/231, 231/231` — 0 failed, 0 errors in every round.

### Orchestrator independent verification of Step 7

Re-read all eight `workspace/implementation/results.$i.json` myself rather than trusting the report: every round reads `passed=231 total=231 failed=0 errors=0`. Also confirmed the deleted test name no longer appears anywhere under `test_suite/` (grep returns nothing) and the suite now holds 210 test functions (211 minus the one deletion). Baseline sweep 1 was independently observed at 226/232 in all 8 rounds — identical counts across rounds, which corroborates the report's "deterministic, no load-induced flakiness" finding.

### Step 8 skip-condition adjudication

The skill skips Step 8 only when Step 7 had 0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes. Step 7 recorded 1 deletion and 1 `test_helpers/` fix, so the skip condition is NOT met and Step 8 runs. Note that 0 implementation fixes means a byte-identical `PRD_FINALIZED.md` would be a legitimate outcome here; the one substantive candidate is the query-parameter-scope silence the deletion exposed.

## Step 8: Finalize PRD — 2026-09-05T22:36:00.000Z

Subagent summary (verbatim):

Done. PRD_FINALIZED.md written with exactly one edit.

## Line counts
- `PRD.md`: 462 lines
- `PRD_FINALIZED.md`: 464 lines (+2 lines, +0.43%)
- File still ends at the real final boundary: the §5 error table's last row (`ERR_INSUFFICIENT_POSTAGE_BALANCE | 402`).
- `diff` shows one insertion only (after line 82, inside §2.3); no other bytes changed.

## Changes
- **§2.3 Pagination — insert — query-string scope pinned**: the unknown-field rejection is explicitly body-only; undeclared query parameters are ignored on every endpoint; declared parameters are still validated (`limit`/`offset` integer + bounds, enum filters reject undeclared members, identifier filters naming a nonexistent row match nothing rather than 404). — `implementation/envelope.py:65-102` (`read_pagination`, `_parse_int_param`, `enum_filter`, `str_filter`), plus `implementation/shape.py:96-99` for the body-scoped `Unknown field` rejection.

## Pre-edit search log (single edit)
- **(a) Subject**: scope of the "unknown input is rejected" rule — request body vs. URL query string — and, as a boundary guard, what validation *declared* query parameters do receive.
- **(b) Impl paths enumerated**: `grep -rn "request.args|args.get|enum_filter|str_filter|listed(|read_pagination"` over all of `implementation/`. Read `envelope.py` in full (`read_pagination`, `_parse_int_param`, `enum_filter`, `str_filter`, `page`, `listed`, `collection`); `shape.py` in full (`authenticate`, `raw_body`, `validate_body` — the only unknown-key rejection in the codebase, keyed off the parsed JSON body); `app.py` (no `before_request` query-string validation; only a store lock and error handlers). Enumerated every list callsite: the two filtered lists `routes_jobs.py:101-119` (`client_id`/`permit_account_id`/`commingle_batch_id` via `str_filter`, `status` via `enum_filter`) and `routes_batches.py:63-78` (`status`, `mail_class` via `enum_filter`, `entry_facility_id` via `str_filter`), and every unfiltered list that takes only `limit`/`offset`: `routes_clients.py:114,127,135`, `routes_jobs.py:201,215`, `routes_batches.py:142,221,251,258`, `routes_facilities.py:89`, `routes_permits.py:121`, `routes_statements.py:171`, `routes_misc.py:30`. Confirmed no whitelist of parameter names exists anywhere, and that non-list endpoints never touch `request.args` at all.
- **(c) Wording adjustments made**: (1) scoped the "ignored" claim to parameter *names*, not values, so it cannot be read as licensing an undeclared `status=BOGUS`, which `enum_filter` does reject; (2) added the explicit three-way enumeration ("a list that declares filters, a list that accepts only `limit`/`offset`, and any other endpoint alike") because the nested lists accept no filters and POST routes read no args — a narrower sentence would have implied filtered lists are special; (3) added "must be integers as well as within the bounds above" to stay consistent with `_parse_int_param`, which rejects non-numeric `limit`/`offset` before the bounds check; (4) added the "identifier filter naming a row that does not exist ... simply matches nothing" clause so a fresh implementer does not add a 404 to the `str_filter` paths, which do pure equality matching.

## Not patched (deliberate)
- The `test_helpers/fixtures.py` fix was a pure fixture bug (stale local job snapshot). I verified `implementation/routes_jobs.py:167-191` mirrors exactly the three derived measures §3.2 names (`accepted_piece_count` <- `net_piece_count`, `address_quality_pct`, `move_update_compliant`), increments `hygiene_run_count`, sets `HYGIENE_CLEARED`, and bumps `version`/`updated_at` via `touch`. §3.2 already determines all of this, so no edit.
- Step 7 applied zero implementation fixes, so no other PRD text needed pinning.

### Orchestrator verification of Step 8

Ran `diff PRD.md PRD_FINALIZED.md` myself: exactly one hunk, `82a83,84`, inserting the query-string-scope paragraph plus a blank line into §2.3 — no other bytes differ. `PRD_FINALIZED.md` is 464 lines and still ends on the §5 table's final row. Given Step 7 applied 0 implementation fixes, this near-identical result is the expected legitimate outcome rather than a sign Step 8 under-ran.

## Step 9: Complete PRD — 2026-09-05T23:35:00.000Z

Run as FOUR sequential module-partitioned passes over one shared `PRD_COMPLETED.md`, rather than a single subagent, because one agent scanning 19 implementation modules against a 464-line PRD reliably under-runs and can return a byte-identical file. Pass 1 owned the `cp` from `PRD_FINALIZED.md`; passes 2-4 were explicitly forbidden from re-copying or reverting earlier passes' edits. Partition: (1) app/shape/envelope/errors/util/store/enums/serialize; (2) calc/cascades/domain; (3) routes_clients/permits/jobs/facilities (25 endpoints); (4) routes_batches/statements/shipments/misc (31 endpoints).

### Pass 1 — core semantics (app, shape, envelope, errors, util, store, enums, serialize)

10 ambiguity-pins, 3 mismatch-revisions; 464 -> 465 lines, +3,809 chars; 13 hunks.

- §2.2 Success format — revise — ambiguity — `api_request_id` pinned as `req_` + exactly 20 uppercase-alnum chars, freshly generated on every response including errors — util.py:26-30, envelope.py:14-19
- §2.2 `data` bullet — revise — ambiguity — every declared field always present, no-value fields emitted as JSON `null` never omitted; no extra fields; the one 204 carries no body/envelope — serialize.py:1-24, envelope.py:26-31
- §2.2 Error format — insert — ambiguity — unmatched path / unsupported method / unparseable JSON -> `ERR_INVALID_REQUEST` 400; unexpected faults -> same envelope and error_id at 500 — app.py:63-73
- §2.3 ordering — revise — ambiguity — same-millisecond rows ordered by write sequence, so list order is exactly insertion order — store.py:41-44, 55-57
- §2.4 `created_at` — revise — mismatch — stamped from the server's real clock, not the logical clock — store.py:47-50, util.py:70-73
- §2.4 `updated_at` — revise — mismatch — refreshed from that same real clock — store.py:60-63
- §2.5 opening — revise — mismatch — "never read from the host's wall clock" narrowed to "no business rule reads it", listing `api_request_timestamp` and `created_at`/`updated_at` as real-clock values — util.py:70-73
- §2.5 client-supplied instants — revise — ambiguity — accepted spellings pinned (T or space separator, optional seconds, any/no fractional digits, any or no offset with naive read as UTC), normalized to UTC and truncated to ms; emitted form always canonical `...Z` with 3 digits — util.py:12-15, 32-58
- §2.7 rounding — revise — ambiguity — the five non-integer figures travel as JSON numbers at their scale, never strings; every other numeric field is a JSON integer — util.py:105-110, serialize.py:69/75/149
- §2.9 rung 3 — revise — ambiguity — unknown-field scan runs over the whole body before required/type checks; absent or empty body read as `{}`; non-object body rejected; explicit `null` = absent except the three genuinely nullable fields; booleans rejected for integer/number, numeric strings rejected — shape.py:98-127, 39-50
- §3.1 funding deposit — revise — mismatch — `reference` is validated but neither persisted nor exposed — serialize.py:45-58
- §3.3 entry facility — revise — ambiguity — `served_zip3_list` stored and returned in exactly the order supplied — serialize.py:107
- §4 preamble — revise — ambiguity — a trailing slash addresses the same endpoint — app.py:28

Reported fully covered already (no change needed): `enums.py` (all 19 enum domains match §3 member-for-member), `errors.py` (all 54 error-ids and statuses match the §5 table exactly, verified programmatically), and the entity **key sets** of all 13 serializers.

### Pass 2 — calculations, cascades, domain

8 ambiguity-pins, 1 mismatch-revision; 465 lines held, +3,168 chars; hunks 13 -> 21, pass 1 intact.

- §3.4 batch derivation — insert — ambiguity — member rows are version-incremented only when a run actually changes `allocated_postage_cents` or `share_basis_pct`; the member created by the pooling request returns at `version` 1 with its allocation already written — domain.py:172-191
- §3.4 withdrawal — insert — ambiguity — withdrawing the last member zeroes the counts and returns `achieved_tier` to `NONE`, but `rate_mills_per_piece` is still re-derived at the `NONE` tier and is therefore **not** 0 — domain.py:147-169, calc.py:42-59, 82-86
- §3.6 findings walk — insert x2 — ambiguity — the walk covers the current filing episode only, so cumulative severity restarts at zero after each revision, and `verification_error_count` is per-episode not lifetime — domain.py:126-132
- §3.6 branch one — insert — ambiguity — member/job/client writes are unconditional (version bumps even when the value is unchanged; a client owning two member jobs is incremented once per job) — cascades.py:56-64
- §3.6 branch two — insert x2 — ambiguity — the second allocation writes `allocated_adjustment_cents` only, leaving `share_basis_pct` as sortation wrote it, and version-increments only members whose adjustment share changes; the following job/client writes are unconditional — cascades.py:80-91, domain.py:172-191
- §3.6 branch three — **revise** — **mismatch** — PRD said `adjustment_cents` and `verified_postage_cents` are "left at 0"; impl *resets* `adjustment_cents` to 0, discarding the findings' surcharge total, and does **not** clear `verification_error_count` (only a revision does) — cascades.py:95-99, 150
- §3.6 branch three link 4 — insert — ambiguity — only an `ACTIVE` client is suspended; an already-`SUSPENDED` client is untouched, and one client is suspended once even if two of its jobs cross the threshold — cascades.py:131-139
- §3.8 service-level index — insert — ambiguity — an empty population reports `on_time_count` 0 as well as `record_count` 0 — calc.py:164-167

Already uniquely pinned: tier thresholds, single-floor rate, mills-to-cents once, floor-plus-remainder allocation with its tie-break, quality pct, container minima, zone/day tables, cumulative severity threshold, zone/piece weights, volume tiers, the ceiling-then-discount-then-floor service fee; sortation, void/supersede and deposit link ordering; all 11 per-entity 404 ids, every child-collection ordering, half-open dock occupancy over `SCHEDULED`/`IN_TRANSIT`, closed-interval invoice overlap over `ISSUED`/`PAID`.

### Pass 3 — client, permit, job, facility routes (25 endpoints)

13 ambiguity-pins, 1 mismatch-revision; 465 lines held, +5,105 chars; hunks 21 -> 31, passes 1-2 intact.

- §2.1 — insert — ambiguity — the nine rung-7 endpoints are the *complete* ownership-scoped set; every other ClientContact-authorized read carries no ownership comparison — routes_permits.py:49-54, routes_jobs.py:204-215
- §2.9 rung 3 — revise — ambiguity — rung 3 owns all per-field length/charset/range/precision bounds as `ERR_INVALID_REQUEST`, not rung 31 — shape.py:114-118, routes_clients.py:32-37
- §3.1 client status — revise — ambiguity — wrong-source-state yields `ERR_CLIENT_SUSPENDED` in **both** directions; `reason` defaults to null and is ignored on reinstatement; no idempotent path — routes_clients.py:92-102
- §3.1 permit status — insert x2 — ambiguity — wrong-source-state yields `ERR_PERMIT_ACCOUNT_NOT_ACTIVE` for all three targets and the optional `reason` is validated then discarded; the source-state check precedes the reserved-funds check, so re-closing a `CLOSED` account reports `ERR_PERMIT_ACCOUNT_NOT_ACTIVE`, never `ERR_PERMIT_HAS_RESERVED_FUNDS` — routes_permits.py:93-106
- §3.1 lists — revise — ambiguity — all three client-scoped lists are `created_at`-asc, filterless and paginated; the permit statement list returns every status incl. `DRAFT`/`VOID` — routes_clients.py:111-135, routes_permits.py:110-121
- §3.2 hygiene bounds — revise — **mismatch** — `cass_matched_count` and `ncoa_move_updated_count` may not be negative, `undeliverable_removed_count` must be >= 0; `ncoa_move_updated_count` feeds no derivation — routes_jobs.py:152-165
- §3.2 job cancel — revise — ambiguity — `reason` is the only field, any length incl. empty string; 200 with the job; nothing else written — routes_jobs.py:218-229
- §3.2 postage estimate — revise — ambiguity — echoes `mail_job_id` (five keys), gates on nothing but existence + scope, so it answers in every job status — routes_jobs.py:232-249
- §3.2 batch-memberships list — insert — ambiguity — `created_at`-asc, paginated, and empty (not 404) for an unpooled job — routes_jobs.py:204-215
- §3.3 facility status — insert — ambiguity — `status` is the only field (no `reason`); wrong-source-state yields `ERR_ENTRY_FACILITY_CLOSED` in both directions — routes_facilities.py:64-77
- §3.3 facility drop-shipment list — revise — ambiguity — `created_at`-asc, paginated, filterless, all statuses — routes_facilities.py:80-89
- §3.8 service-level index — revise — ambiguity — echoes `client_id` (five keys), single-object 200, never paginated — routes_clients.py:160-168
- §3.8 invoice issuance — revise — ambiguity — bumps the client's `version` unconditionally even at 0/0; write order is invoice -> jobs (`created_at` asc) -> client ledger; 201 — routes_clients.py:220-241

Cross-check reported clean: all 25 endpoints' §4 role lists match their `shape.authenticate(...)` tuples exactly, and scope checks exist at exactly the nine rung-7 sites.

### Pass 4 — batch, statement, shipment, misc routes (31 endpoints)

20 ambiguity-pins, 2 order/mismatch-revisions; 465 lines held, +5,991 chars; hunks 31 -> 47/48, passes 1-3 intact (27 hunks byte-identical, 4 extended by pure insertion).

- §2.9 rung 10 — insert — ambiguity — unnumbered own-state check on withdrawal: after the rung-12 batch check the member's job must be `POOLED`, else `ERR_INVALID_JOB_STATE` — routes_batches.py:158
- §2.9 rung 12 — insert — ambiguity — the two *unnumbered* batch-state preconditions (submit needs `SORTED`, revise needs `REWORK`) sit immediately after rung 13 and report `ERR_INVALID_BATCH_STATE`; rung 13 still wins — routes_statements.py:89, 232
- §2.5 — revise — ambiguity — the clock is an **absolute set, not an advance**; time may move backwards; `to_iso8601` required and sole field — routes_misc.py:95-96
- §3.4 open batch — insert — ambiguity — all three fields required; facility status not examined, so a pool may open against a `CLOSED` facility — routes_batches.py:28-38
- §3.4 pooling — insert — ambiguity — new member's `allocated_adjustment_cents` opens at 0; job written before batch re-derivation; response is the `BatchMember`, not the batch, at 201 — routes_batches.py:119-135
- §3.4 withdrawal — insert — ambiguity — job-state refusal checked after batch state and the belongs-to check; no body field accepted — routes_batches.py:150-159
- §3.4 nested lists — insert — ambiguity — the four batch sub-lists declare no filters, take only `limit`/`offset`, include every status — routes_batches.py:138-258
- §3.5 add container — insert — ambiguity — adding a container does **not** re-run the three-stage derivation; ledger and pricing untouched; 201 — routes_batches.py:194-214
- §3.5 close sortation — insert — ambiguity — batch `version` bumps exactly once regardless of cascade breadth; returns the batch at 200 — routes_batches.py:243-244
- §3.6 prepare — insert x2 — ambiguity — permit status and its client are **not** examined at preparation (`HOLD`/`CLOSED`/foreign client all accepted), status first bites at filing; preparation's own batch bump means a replayed identical request gets `ERR_STALE_BATCH_VERSION` — routes_statements.py:38-45, 70
- §3.6 findings — insert — ambiguity — finding returned at 201; the findings list is paginated and spans **all** episodes — routes_statements.py:164-173
- §3.6 verify — insert — ambiguity — the batch is version-incremented only in the returning branch; both accepting branches leave the batch row untouched — cascades.py:47-92
- §3.6 void — insert — ambiguity — `reason` is the sole field, verbatim, any length incl. empty — routes_statements.py:214
- §3.7 booking — insert — ambiguity — 201; nothing outside the new row is written, no batch/facility version movement — routes_shipments.py:57-70
- §3.7 deposit — **revise** — **mismatch (ordering)** — batch-state check precedes shipment-state check (rung 12 before 14); worked example added — routes_shipments.py:100-105
- §3.7 cancel shipment — insert — ambiguity — `reason` sole field/any length; 200; nothing else written; `deposited_at_utc` stays null — routes_shipments.py:118-129
- §3.7 clock sweep — insert — ambiguity — `no_show_shipment_ids` in `created_at` order, `[]` when none; exactly two keys at 200; sweep runs on backwards moves; `window_end_utc == clock` stays `SCHEDULED` — routes_misc.py:98-111
- §3.8 delivery scan — insert — ambiguity — both fields required; negative days is `ERR_INVALID_REQUEST` not a piece-count error; 200; any container/batch status accepted — routes_misc.py:45-62
- §3.8 payment — insert — ambiguity — `amount_cents` sole field with no bound of its own (0/negative => `ERR_PAYMENT_AMOUNT_MISMATCH`); 200; client ledger untouched — routes_misc.py:73-87
- §4 preamble — insert — ambiguity — enumerates the six write operations that declare **no** request field (sort, withdraw member, submit, revise, depart, deposit), so any supplied field is a rung-3 unknown field — routes_batches.py:148/227, routes_statements.py:83/226, routes_shipments.py:84/97

### Step 9 aggregate and orchestrator verification

- Totals across the four passes: **51 ambiguity-pins + 7 mismatch-revisions = 58 edits**, 48 diff hunks against `PRD_FINALIZED.md`.
- `PRD.md` 462 lines / 103,390 chars -> `PRD_FINALIZED.md` 464 / 104,081 -> `PRD_COMPLETED.md` 465 / 122,211 (+18,130 chars, +17.4% over PRD_FINALIZED). Line count barely moves because every pass was required to edit in-paragraph rather than add sections.
- Verified by the orchestrator: `PRD_COMPLETED.md` is NOT byte-identical to `PRD_FINALIZED.md` (the tell that the scan never ran), all 27 headings survive with no numbering gaps, the file still ends on the §5 table's final row `| ERR_INSUFFICIENT_POSTAGE_BALANCE | 402 |`, and grep finds no leak of the difficulty directive, scaffold vocabulary, `test_recipe`, or worklog references.
- Confirmed no implementation file is newer than `workspace/implementation/results.1.json`, so Step 9's documentation-only edits did not disturb the artifact the clean 231/231 x 8 sweep measured. Step 9 wrote only `PRD_COMPLETED.md`.
- Housekeeping: removed the transient `workspace/SWEEP_DONE` sentinel and the (interleaved, undiagnosable) `workspace/sweep.log`; kept `workspace/sweep.sh` as the reproducible re-verification harness and all eight `results.$i.json`. No stray worklog files and no `.scratch` leftovers remain.

**Pipeline complete.** All nine steps finished; `workspace/PRD_COMPLETED.md` is written.
