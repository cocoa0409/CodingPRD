# Worklog — task_2792_parcel_dimensional_weight_accessorial_billing

## Step 1: Create task directory — 2026-09-04T22:11:27.632Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2792_parcel_dimensional_weight_accessorial_billing` and `.../workspace` (pre-assigned path from the orchestration request; no index auto-allocation performed).

## Step 2: Generate scaffold — 2026-09-05T00:03:31.301Z

All three scaffold artifacts are complete, parse under PyYAML, and the scaffold linter reports **VERDICT: clean lint** (913 calls across §1.8+§1.9 checked against §1.5, all §1.1 FKs reverse-reachable).

Files (all in `/home/ubuntu/github/CodingPRD/tasks/task_2792_parcel_dimensional_weight_accessorial_billing/`):

| file | lines | bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 2860 | 141049 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1742 | 121725 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4698 | 295264 |

**SCAFFOLD.yaml (§1.0–§1.7)** — scenario stored verbatim (including the leading directive line); no `scaffold_difficulty_design` / `scaffold_corner_design` keys. 13 entities, 10 state machines (Shipment carries two independent axes: measurement + movement), 11 calculations, 3 OCC rules, 55 validation rules (priority-ordered 1→55), 52 endpoints, 57 errors, 5 roles. Two carried-over defects fixed this session: the REFUSAL side-effect wording on `IN_TRANSIT→REFUSED`, and dead code in validation 35 / `ERR_CONTRACT_PERIOD_OVERLAP` (the `supersedes_contract_id` target is now explicitly exempt from the closed-interval overlap scan, so activating a successor is actually reachable).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)** — 9 §0.5 difficulty rules × 19 instances: dual-variant divergence, mode-dependent calculation (3 modes), parallel state axes, cycle termination, cascade depth, guarded/conditional cascade, priority-pair validation conflict, boundary precision, dependency chain, interval boundary semantics, compensation/invariant restoration.

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9)** — 75 instances over all nine claim-extraction sections, with every claim_type row in the guide covered: entities 12, state_machines 15, calculations 11, validations 12, endpoints 6, errors 10, rbac 3, cross_cutting_complexity_layers 5, consistency_model 1. 12 of them are `excluded_because` stubs that cite (and were verified against) real §1.8 instance names, so no §1.8 corner is re-tested. Every literal is derived from the §1.4 formulas — e.g. the 96-inch oversize threshold turning a 10950 line into 39950 via the 90 lb `OVERSIZE_FLOOR` basis and the 305 rate row; the tier row inclusive at 50000 (2750 discount) vs 49999 (nothing); the 8203 tier discount that makes the third full-line credit breach `ERR_CREDIT_EXCEEDS_INVOICE_NET` at exactly -8203.

One lint fix was needed: the `priority_ordering` instance originally used a literal `expected_shipment_version: "1"` against a nonexistent shipment; it now creates a real parcel in setup and passes its captured `${p_v}`, which also strengthened the assertion (priority 9 answers before the OCC guard at 19).

**Orchestrator post-step action:** the difficulty directive line ("Generate task harder than expert level!") had leaked into SCAFFOLD.yaml's `scenario:` key, from which it would reach PRD.md via the doc generator. Stripped that one line from SCAFFOLD.yaml; grep confirms no remaining occurrence anywhere in the task dir. Scaffold still parses.

## Step 3: Copy shared files — 2026-09-05T00:03:31.301Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T00:18:48.996Z

PRD generation complete and verified.

**Output:** `workspace/PRD.md` — **528 lines**, written in 10 incremental operations (1 `Write` + 9 heredoc/script appends) to stay clear of the 64k output cap. Line count was confirmed growing after each chunk (175 → 201 → 231 → 261 → 281 → 317 → 333 → 356 → 405 → 528).

**Termination check:** `tail -40` shows the document ending inside the completed §5 Error Code Catalogue table, final row `| ERR_CREDIT_EXCEEDS_INVOICE_NET | 422 |`. This is a genuine section boundary — the 57th of 57 error rows, no truncated sentence, no audit footer.

**Section list**
- 1. Introduction
- 2. Global Specifications & System-Wide Principles — 2.1 RBAC · 2.2 API Response Structure (verbatim fixed block) · 2.3 Pagination · 2.4 The Logical Clock · 2.5 Common Resource Properties and Record Versioning · 2.6 Money, Measurement Precision and Rounding · 2.7 Optimistic Concurrency Control · 2.8 Segregation of Duties on Money Movement · 2.9 Cascade Propagation and the Freeze Boundary · 2.10 Validation Order and Nested Path Resolution · 2.11 The Shipper Ledger and Its Invariants
- 3. Business Logic & Workflows — 3.1 Shipper Accounts and the Rate-Contract Governance Cycle · 3.2 The Service Catalogue and Surcharge Window Scheduling · 3.3 Package Induction and the Preliminary Weight Determination · 3.4 Scan Capture, Tolerance Verdicts and the Final Determination · 3.5 Movement Outcomes, Hand-Entered Accessorials and Waivers · 3.6 The Billing Sweep, Line Pricing and the Invoice Roll-Up · 3.7 Issuing, Settling and Voiding an Invoice · 3.8 Proposing and Applying Billing Adjustments · 3.9 Shipper Disputes, Evidence Review and Service-Guarantee Recovery
- 4. Endpoint Definitions (intro paragraph on 201-vs-200 semantics + 52-row, 4-column table)
- 5. Error Code Catalogue (57-row, 2-column table) ← last section

**Coverage: complete, no deliberate omissions.** 13/13 entities, 52/52 endpoints (table row count verified = 52), 57/57 errors (verified = 57), 55/55 validations, 11/11 calculations, 10/10 state machines with all 42 transitions, 3/3 concurrency rules, 28/28 endpoints carrying side effects.

**Hard Contract 1 — Field-Name Coverage: PASS.** entity fields missing 0/123 unique · endpoint request_body/input/query_params/path_params/output identifiers missing 0/67 · errors missing 0/57 · state names missing 0 · enum constraint values missing 0 · roles missing 0.

**Hard Contract 2 — Rule Coverage: PASS.** 55/55 validations rendered with their error ID, HTTP status and trigger condition; priority orderings stated in prose (a 9-tier global precedence list in §2.10 plus explicit per-endpoint orderings — adjustment proposal's five ordered checks, adjustment apply's three preconditions, guarantee-claim filing's seven guards, scan capture's OCC-before-ERR_MEASUREMENT_FINAL). All 55 applies_to scopes enumerated. 3/3 OCC rules (§2.7) with their 412 error IDs. 42/42 state transitions with guards and cascades. 11/11 calculations as business prose (no pseudocode). 28/28 endpoint side-effect sets. Sibling-branch symmetry given equal density: three → VOID invoice branches (numbered cascade hops 1–5 each), both settle source states, both EVIDENCE_REQUESTED entry branches, all three exception kind values, all seven measurement transitions, both dispute-credit variants, both resolve outcomes, both adjudicate outcomes. Field-level structured content (defaults, enums, nullability) carried into prose.

**Hard Contract 3 — §3 Path Purity: PASS.** 1085 backtick tokens scanned in §3; tokens starting with `/`: none; bare HTTP methods: none; method+path combinations: none; plain-prose HTTP verbs: none. All §3 operations are named in business language and cross-referenced to §4.

Two notes worth relaying:
1. Seven §4 endpoint descriptions in the scaffold contained scaffold-internal references (calculations.*, concurrency_rules.*). These were rewritten as PRD-internal cross-references (e.g. §2.7, §2.11) so no scaffold structure leaks to the implementer.
2. The withheld files (SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml) were never opened, grepped, or referenced.

**Orchestrator truncation check:** independently confirmed — 528 lines, `tail` ends at the final error-catalogue row, and `grep -c "harder than expert" PRD.md` = 0 (no difficulty-directive leak).

## Step 5: Generate unit tests — 2026-09-05T02:47:20.155Z

Stage 2 is complete. `test_19_disputed_codes_and_the_guarantee_channel.py` closed out the queue-B backlog, and the whole suite passes every gate.

## Output

`test_suite/` — 20 files (19 test modules + `conftest.py`), 10,173 lines, **114 test functions**.

| lines / tests | file |
|---|---|
| 75 / — | `conftest.py` |
| 399 / 6 | `test_01_dual_variant_weight_and_dispute_credit.py` |
| 340 / 6 | `test_02_line_pricing_and_invoice_rollup_formulas.py` |
| 399 / 6 | `test_03_measurement_recovery_and_review_cycles.py` |
| 472 / 6 | `test_04_cascades_from_a_rescan_and_a_claim.py` |
| 344 / 6 | `test_05_validation_precedence_conflicts.py` |
| 408 / 6 | `test_06_tolerance_and_lateness_boundaries.py` |
| 316 / 6 | `test_07_gates_that_live_on_another_entity.py` |
| 463 / 7 | `test_08_overlapping_windows_and_contract_periods.py` |
| 482 / 7 | `test_09_compensating_pairs_restore_the_ledger.py` |
| 444 / 5 | `test_10_born_defaults_and_server_minted_fields.py` |
| 635 / 6 | `test_11_reading_back_the_graph_the_writes_built.py` |
| 491 / 7 | `test_12_refused_writes_leave_no_trace.py` |
| 616 / 6 | `test_13_repeated_writes_and_reversed_periods.py` |
| 826 / 6 | `test_14_role_boundaries_and_shipper_scope.py` |
| 571 / 6 | `test_15_the_charges_a_parcel_earns_and_loses.py` |
| 849 / 6 | `test_16_cascades_and_the_shipper_ledger.py` |
| 545 / 5 | `test_17_the_thresholds_that_price_a_parcel.py` |
| 910 / 7 | `test_18_sweep_gates_tier_breaks_and_credit_ceilings.py` |
| 588 / 4 | `test_19_disputed_codes_and_the_guarantee_channel.py` |

`test_helpers/` — 9 files, 2,321 lines (`__init__` 38, `api_client` 394, `api_errors` 147, `assertions` 312, `constants` 157, `factories` 351, `fixtures` 732, `test_users` 106, `types` 84).

## Design-index coverage

- **Queue A (difficulty): 19 / 19 instances translated**, every one carrying at least 2 tests (verified programmatically — no instance below the floor, no instance untranslated).
- **Queue B (corner): 58 / 60 non-stub instances translated.** All 15 `excluded_because:` stubs were left alone; no tag points at a stub.
- **2 skipped under the PRD-first two-condition filter** (gaps left as gaps, no xfail/placeholder):
  - `entities/shipment_computed_pricing_fields_are_input_ignored` — the PRD never states how an induction body carrying server-computed pricing fields is treated, so "201 with the keys ignored" is not uniquely derived.
  - `entities/manual_accessorial_system_fields_are_input_ignored` — same gap for manual accessorial system fields.

## Gates

- All 114 tests carry exactly one `Design:` line; 114 tags for 114 tests, zero untagged, zero dual-tagged, zero malformed, zero pointing at a non-existent or stub instance.
- Citation audit across the suite: **citations=470 bad=0** (every `PRD §x.y: "…"` quote is a verbatim `workspace/PRD.md` substring resolving to the cited section).
- `python3 -m py_compile` clean on all 29 files; `python3 -m pyflakes` clean on all of `test_suite/`.
- No `skip`/`xfail` markers anywhere; the only "skipped" hits are prose about the guarantee sweep's `skipped_count`.
- Zero occurrences of "scaffold" or any scaffold section/priority reference in generated code.
- `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation/` — no stray `test_suite/` or `test_helpers/` was created there; nothing under `implementation/` was read or written; `worklog.md` untouched.

## Notes worth passing on

- One corner recipe (`a_single_unpriceable_parcel_rejects_the_whole_sweep`) had an unreachable setup: it wanted a contract with a single zone-2 weight row, but §3.1 requires each zone's rows to tile 1–9999 lb with no gaps, so that draft would be refused and `ERR_RATE_ROW_MISSING` unreachable by that route. Kept a fully tiled zone-2 table and rated the second parcel for **zone 5** — a zone the table never names — which preserves the instance's asserted outcome (preview 422, whole-sweep 422, nothing persisted) as a genuinely PRD-derived result. Explained inline in the test.
- `test_helpers/factories.evidence_payload` defaults `item_type="PHOTO"`, which is not in the PRD's evidence enum (`SCAN_IMAGE` / `DELIVERY_PHOTO` / `ADDRESS_PROOF` / `SCALE_CERT`). No test relies on that default (every evidence-filing test passes an explicit type), so Stage 1 was left untouched, but it is a latent trap for future edits.

## Step 6: Generate implementation — 2026-09-05T02:47:20.155Z

Implementation complete and verified.

## Files (`workspace/implementation/`)

| file | lines | role |
|---|---|---|
| `app.py` | 64 | `create_app()`, blueprint registration, `ApiError`/`HTTPException`/generic handlers, `app.run(PORT, threaded)` |
| `store.py` | 138 | in-memory `db` (13 dicts), logical clock, ISO/date helpers, `new_record`/`touch`/`sorted_records` |
| `errors.py` | 88 | 58 error ids → HTTP status map, `ApiError` |
| `response.py` | 104 | envelope `success`/`collection`/`error_body`, `pagination_params`, `paginate` |
| `auth.py` | 81 | `X-User-ID`/`X-User-Role`, `authorize(*roles)`, shipper-scope enforcement |
| `validators.py` | 249 | tiered field validation, rate/tier table + overrides validators |
| `calc.py` | 245 | Decimal geometry, dim weight, oversize floor, tolerance verdict, accessorial rate resolution |
| `domain.py` | 348 | lookups/404s, derived aggregates, contract selection, measurement application, auto-accessorial reassessment |
| `pricing.py` | 223 | line pricing, surcharge windows, tier selection, 7-step invoice roll-up, freeze guard, six-way reconciliation |
| `serializers.py` | 278 | 13 entity serializers with live-derived aggregates |
| `routes_admin.py` | 358 | shipper accounts, rate contracts, service levels, surcharge windows, `/_clock/set_current_utc` |
| `routes_shipments.py` | 366 | induction, scans, deliver/exceptions, accessorials, billing preview |
| `routes_billing.py` | 428 | sweep, invoice lifecycle, invoice lines, billing adjustments |
| `routes_claims.py` | 481 | disputes + evidence rounds, guarantee claims + audit sweep |
| `start.sh` | 10 | installs flask if absent, `exec python3 app.py` on `$PORT` |
| `requirements.txt` | 1 | `flask>=2.0` |

3462 lines total; all modules `py_compile` clean; `__pycache__` removed. Storage is in-memory dicts only, nothing seeded — a fresh process answers 404 for any id, so per-test-server isolation works.

## Endpoints
**52 implemented — exact 1:1 match with the 52 `path:` entries in SCAFFOLD.yaml** (verified by diffing the Flask url_map against the scaffold list).

## Smoke test
Three fresh boots on random high ports (34771, 26936, 24674), each killed by its own recorded port/PID (no pattern kill); zero tracebacks in any server log.

Run A (happy path): missing headers → 401 `ERR_MISSING_AUTH_HEADERS`; clock set; shipper/service level/contract draft+activate; induction → cube 3000, dim 22 lbs, basis `DIMENSIONAL`, RESIDENTIAL 590, guarantee deadline +72 h; in-tolerance scan; deliver; sweep → transportation 2090, gross 2680, tier 250 bps, discount 52, net 2628; issue → deadline +90 d; stale version → 412 `ERR_STALE_INVOICE_VERSION`; propose −500 then self-apply → 403 `ERR_SEGREGATION_OF_DUTIES`, second operator applies → invoice `ADJUSTED`, net 2128, ledger credit 500; ACCESSORIAL dispute (bad code → `ERR_DISPUTED_CODE_NOT_ASSESSED`, evidence round with wrong type → `accepted:false` + `ERR_EVIDENCE_REQUIRED`, correct type → UPHELD credit 590, charge waived, net 1538); settle; paginated list `has_more:true`; `ERR_INVALID_PAGINATION`, `ERR_UNKNOWN_ROLE`, `ERR_ROLE_NOT_PERMITTED`, cross-tenant 403, unknown route 404.

Run C (edge path): oversize 100×20×20 → cube 40000, dim 288, `oversize_flag`, three auto charges (RESIDENTIAL 590, DELIVERY_AREA 650, OVERSIZE override 13000), DEMAND window surcharge 300+700 oversize add = 1000; out-of-tolerance scan → 33.1 % / 10 lbs → `TOLERANCE_FLAGGED` and sweep rejected with `ERR_SCAN_TOLERANCE_UNRESOLVED`; MANUAL_REWEIGH → `VERIFIED`, further scan → `ERR_MEASUREMENT_FINAL`; late delivery → claim `late_by_seconds` 108000, candidate refund 27360 = line transportation base, duplicate → `ERR_DUPLICATE_CLAIM`, approve → `GUARANTEE_REFUND` adjustment, apply → claim `REFUNDED`; invoice roll-up 28360/14240/42600, 250 bps, discount 709 (exact), net 41891 → 14531 after refund; REFUSED exception → REFUSAL 1350 + RETURN_UNDELIVERABLE 1800; void → net 0, line voided, shipment back to `UNBILLED`, ledger zeroed.

One note from the impl generator: its first attempt at run C used the wrong request field names (`min_weight_lbs`/`rate_cents_per_lb`/`min_subtotal_cents`); the server correctly rejected them — PRD §3.2 specifies `min_lbs`/`max_lbs`/`cents_per_lb` and `min_transportation_subtotal_cents`, which is what the implementation accepts.

**Orchestrator post-step check:** `workspace/` contains only INSTRUCTION.md, PRD.md, implementation/ — no stray test_helpers/ or test_suite/ under workspace/. All `__pycache__` dirs removed before Step 7.

## Step 7: Run tests and iterate — 2026-09-05T03:10:00.000Z

All 8 parallel rounds pass, 114/114, twice in a row.

## Summary

**Iterations run: 3** (1 diagnostic sweep, 1 fix-verification sweep, 1 confirming sweep after helper edits). Every round of the final two sweeps: `114 passed / 114 total`, 0 failures, 0 errors, 0 skips — no flakiness across any of the 16 green rounds.

**Iteration 1 baseline:** 112/114 in all 8 rounds, with the *same two* tests failing in every round (deterministic, not load-induced).

### Tests deleted
None. Both failures traced to STEP 2 (test-vs-PRD consistency) — the asserted rules are verbatim in PRD and uniquely derivable; the *setups* were wrong.

### Fixes applied to `test_suite/`
- `test_08_overlapping_windows_and_contract_periods.py` → `test_a_cancelled_window_stops_excluding_the_dates_it_used_to_hold`: the test's own setup created SCHEDULED `PEAK-B` over `[2026-12-01, 2027-01-01)` and then probed with `PEAK-D` over `[2026-11-15, 2026-12-15)`. Those two genuinely intersect on `[12-01, 12-15)`, both `PEAK_SEASON` and both EXPRESS-scoped, so PRD §3.2 *requires* the `ERR_SURCHARGE_WINDOW_OVERLAP` the implementation returned. Narrowed `PEAK-D` to `[2026-11-15, 2026-12-01)` so it sits inside the cancelled window's former range and merely abuts `PEAK-B` (legal per "abutting windows do not collide"). The test's intent — a CANCELLED window stops excluding its dates — is preserved exactly, including the `len(scheduled) == 3` assertion.
- `test_14_role_boundaries_and_shipper_scope.py` → `test_02_eight_crossings_of_the_role_boundary_are_all_refused`: the "refused writes changed nothing" baseline (`delivered`) was snapshotted *before* the billing sweep, but PRD §3.6 states "Each swept shipment's `version` increments by 1", so the shipment legitimately went 2 → 3. Added a post-sweep `swept = refresh_shipment(...)` baseline, used it for `assert_version_unchanged`, and also fed `swept["version"]` (not the stale `delivered["version"]`) into the refused `MANUAL_REWEIGH` scan payload so the *only* possible refusal reason is the permission tier. No assertion was weakened.

### Fixes applied to `test_helpers/`
Found while auditing helper faithfulness (latent — not the cause of any current failure, but they would break against any PRD-faithful implementation that validates the enum, which this one does):
- `factories.py`, `evidence_payload`: default `item_type` `"PHOTO"` → `"DELIVERY_PHOTO"`. `"PHOTO"` is not one of PRD §3.9's four declared members (`SCAN_IMAGE`, `DELIVERY_PHOTO`, `ADDRESS_PROOF`, `SCALE_CERT`), so the default payload was a schema violation.
- `fixtures.py`, `dispute_under_review` and `dispute_at_round_cap`: default `required_item_type` `"PHOTO"` → `"DELIVERY_PHOTO"`, same reason.
- `constants.py`: `DISPUTE_CLAIM_TYPES` dropped the invented `"SERVICE_FAILURE"` member (PRD declares only `WEIGHT` and `ACCESSORIAL`); added the missing `EVIDENCE_ITEM_TYPES` list of the four PRD-declared evidence types.

### Fixes applied to `implementation/`
None. Neither failure was an implementation defect — the implementation was correct on both counts (the window-overlap refusal and the swept-shipment version bump are both PRD-mandated). No implementation check was removed or weakened; no endpoint, field, or seeded data was added.

**Orchestrator verification of sweep artifacts:** independently read all 8 `workspace/implementation/results.{1..8}.json` (each ~37 KB, all written at 03:05). Every round reports `passed=114 / total=114, failed=0, errors=0`. The clean sweep is real, not merely claimed.

## Step 8: Finalize PRD — 2026-09-05T03:16:33.446Z

Done. `PRD_FINALIZED.md` written with exactly one revised line.

## Counts
- `PRD.md`: 528 lines — `PRD_FINALIZED.md`: 528 lines. Line-count delta 0 (0.00%). One line revised (§3.9, line 370) = 0.19% of lines touched.

## Change
- **§3.9 (Evidence and review rounds)** — *revise* — the `required-evidence` request's `required_item_type` is now stated to be mandatory and constrained to the same four declared evidence types (`SCAN_IMAGE`, `DELIVERY_PHOTO`, `ADDRESS_PROOF`, `SCALE_CERT`); PRD previously only said the auditor names "the `required_item_type` it wants", leaving an implementer free to accept any string — `implementation/routes_claims.py:145` (`v.req_enum(body, "required_item_type", EVIDENCE_TYPES)`, enum tuple at `routes_claims.py:24`, `ERR_INVALID_REQUEST` via `validators.py:118-124`).

## Pre-edit search log

**Edit 1 (§3.9 `required_item_type`)**
- (a) Subject: the `required_item_type` field — every place it is written, read, cleared, validated, or serialized.
- (b) Impl paths enumerated (grepped `required_item_type`, `EVIDENCE_TYPES`, `item_type` across all of `implementation/`, then read each hit): `routes_claims.py:24` (enum tuple), `:52` claim-type enum (separate tuple, untouched), `:92` dispute birth sets it to `None` server-side, `:111` evidence `item_type` validated against the same tuple, `:119-120` acceptance comparison `required is None or item_type == required`, `:133` cleared to `None` on acceptance, `:145` the only client-supplied `required_item_type` (required + enum-validated), `:155` stored, `serializers.py:226` exposed on dispute reads (null or one of four), `validators.py:118-124` `req_enum` → `ERR_INVALID_REQUEST`. Confirmed `:145` is the *only* endpoint accepting this field, so no parallel endpoint is mis-described.
- (c) Wording adjustment: scoped the new clause to the type *named in this request* ("that named type") rather than to the field in general, so it cannot be read as contradicting the server-minted `null` at dispute birth (`:92`) or the clear-to-`null` on acceptance (`:133`). Phrased as "those same four declared evidence types" to reuse the list already declared one paragraph earlier instead of restating it (which would risk drift).

## Items checked and deliberately **not** patched

1. **Surcharge-window overlap** (`test_08` setup fix). PRD §3.2 ¶3 already pins it exactly as `routes_admin.py:272-281` implements it: half-open intersection test `start < other.end and other.start < end`, restricted to the same `kind` **and** the same `service_level_id` scope (exact equality, `null` scope matching only `null`), only against windows at `SCHEDULED` or `ACTIVE` (so a `CANCELLED` window is skipped), with abutting windows legal. No silence. Enumerated: `routes_admin.py:250-295` (create), the activate/cancel handlers, `pricing.py` candidate-window selection — all consistent with existing prose.
2. **Swept-shipment version bump** (`test_14` setup fix). PRD §3.6 already states "Each swept shipment's `version` increments by 1", and `routes_billing.py:122-125` does exactly one `touch(shipment)` per swept package. No silence. Also re-checked §2.7's `expected_shipment_version` prose against `routes_shipments.py` — already pinned.
3. **Evidence `item_type` enum** (`factories.py` / `constants.py` `"PHOTO"` → `"DELIVERY_PHOTO"`). PRD §3.9 already enumerates the four members inline for the submission field, and §2.10 tier 3 already makes a non-member `ERR_INVALID_REQUEST`. Pure fixture bug on the submission side.
4. **`DISPUTE_CLAIM_TYPES` dropping `"SERVICE_FAILURE"`.** PRD §3.9 ¶1 already declares `claim_type` as "either `WEIGHT` or `ACCESSORIAL`", matching `routes_claims.py:23`. `"SERVICE_FAILURE"` was invented by the helper; no PRD change warranted.

Consistent with the Step 7 report (zero `implementation/` fixes), the outcome is very nearly byte-identical — the single edit closes a real request-schema divergence rather than a fixture artifact.

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` shows exactly one changed line (370), matching the reported edit. Both files 528 lines.

## Step 9: Complete PRD — 2026-09-05T03:38:35.108Z

Run as **three sequential, module-partitioned passes** over one shared `workspace/PRD_COMPLETED.md` (pass 1 owned the `cp` from PRD_FINALIZED.md; passes 2 and 3 edited in place with surgical anchored Edits). Partition: pass 1 = app/store/errors/response/auth/validators/routes_admin; pass 2 = routes_shipments/calc/domain; pass 3 = routes_billing/routes_claims/pricing/serializers.

**Final counts:** `PRD_FINALIZED.md` 528 lines / 102,974 chars → `PRD_COMPLETED.md` 529 lines / 115,233 chars (+1 line, +12,259 chars; 85 changed lines by diff). Ambiguity-pins 33, mismatch-revisions 13 (46 edits total: 18 + 13 + 15).

### Pass 1 (global + admin) — 14 ambiguity-pins, 4 mismatch-revisions
- §2.1 — insert — ambiguity — whitespace-only header value counts as empty for `ERR_MISSING_AUTH_HEADERS` — auth.py:39
- §2.1 — insert — ambiguity — role matching is exact and case-sensitive — auth.py:42
- §2.1 — revise — mismatch — PRD limited the named-`shipper_id` rule to request bodies; impl enforces it on the `shipper_id` list filter as a pure comparison ahead of existence resolution, and narrows every shipper-referencing list to the caller's own account — auth.py:72-81, routes_shipments.py:131-137, routes_billing.py:142-149
- §2.1 — revise — mismatch — PRD's four-check order implied scoping precedes existence; impl resolves the path segment first, so a `ShipperUser` naming an unknown id gets the not-found error — routes_admin.py:71-72
- §2.2 — revise — ambiguity — `api_request_id` is `req_` plus exactly 20 uppercase-alnum characters — response.py:19-20
- §2.2 — insert — ambiguity — new bullet pinning pre-endpoint rejections (unrouted 404, bad method 405, unparseable/non-object body 400 `ERR_INVALID_REQUEST`) and that an absent body reads as `{}` — app.py:36-48, validators.py:20-29
- §2.3 — insert — ambiguity — `created_at` ties break by creation order (never id); `has_more` == offset + returned < total_count; list filters exact-equality, conjunctive, unvalidated (unknown value → empty page) — store.py:131-134, response.py:44, routes_admin.py:198-203
- §2.4 — insert — ambiguity — clock endpoint echoes `now_utc` as the single `data` field, re-rendered in canonical 3-digit ISO UTC; non-UTC offsets converted; clock may move backwards — routes_admin.py:352-358, store.py:56-81
- §2.10 — insert — ambiguity — tier 2 precedes tier 3, so an absent/null/non-string required reference field reports its own 404 rather than `ERR_INVALID_REQUEST` — domain.py:19-22, routes_admin.py:89
- §3.1 — insert — ambiguity — `name` required non-empty string, no length bound; `billing_email` unvalidated format; explicit null on an optional field == omission — routes_admin.py:36-37, validators.py:78-81
- §3.1 — insert — ambiguity — suspending an already-`SUSPENDED` account is itself `ERR_SHIPPER_SUSPENDED` (409) — routes_admin.py:59-61
- §3.1 — revise — mismatch — the 1–9999 zone tiling is NOT validated at draft time; only per-row integer types, `min_lbs <= max_lbs`, `cents_per_lb >= 0`, non-empty array; a gap surfaces later as `ERR_RATE_ROW_MISSING` — validators.py:186-211
- §3.1 — revise — mismatch — tier-table ascending order and threshold uniqueness are not validated; both integers must be >= 0; an empty table is accepted (no discount) — validators.py:214-235
- §3.1 — insert — ambiguity — override values must be integers >= 0; keys are not checked against the accessorial family (unknown keys inert) — validators.py:238-249
- §3.1 — insert — ambiguity — at draft time only the `supersedes_contract_id`'s existence is checked, not its owner or status — routes_admin.py:92-93
- §3.2 — insert — ambiguity — exact shape of the uppercase-snake-case service-level `code` (no lowercase, no leading/trailing or doubled underscore, digits allowed, no length bound) — routes_admin.py:24,216-217
- §3.2 — insert — ambiguity — a surcharge-window `code` carries no format constraint, unlike a service-level code — routes_admin.py:257
- §3.2 — insert — ambiguity — window overlap scope matching is literal `service_level_id` identity, so a null-scoped window never collides with a service-scoped one — routes_admin.py:273-274

Pass 1 also verified by script that `errors.py`'s `HTTP_STATUS` map is an exact 57-for-57 match with the §5 catalogue, and that every route/role/status in `routes_admin.py` matches the §4 table — no edits needed there.

### Pass 2 (shipments + calc + domain) — 7 ambiguity-pins, 6 mismatch-revisions
- §3.3 — insert — ambiguity — the five ledger aggregates are read-derived, so an induction does not refresh the account's `updated_at` or bump its `version` — routes_shipments.py:110-115, domain.py:192
- §3.3 — revise — mismatch — `reason` stays null only for measurement-derived automatic charges; exception-driven AUTO charges do carry one — routes_shipments.py:271
- §3.3 — insert — ambiguity — pinned the exact `assessed_basis` note forms and the condition priority that picks them (`residential_declared=true`, `delivery_area_class=DAS`, `longest_in=100>96` vs `length_plus_girth=140>130`, `weight_lbs=60>50` → `longest_in=60>48` → `non_conveyable=true`; integral weights rendered without `.0`) — calc.py:141-156, domain.py:261-273
- §3.3 — revise — mismatch — the shipment view exposes the two mirrored variance figures, NOT a `tolerance_status` field — serializers.py:80-118, routes_shipments.py:121
- §3.4 — insert — ambiguity — a `declared_cube_in3` of 0 yields `dim_variance_pct` 0.00 instead of a division error — calc.py:208-213
- §3.4 — insert — ambiguity — both variances are emitted as plain JSON numbers with trailing zeros dropped (5.00 → 5) — calc.py:92-98
- §3.4 — revise — mismatch — reversal reaches only the four measurement-derived codes; exception-raised `RETURN_UNDELIVERABLE` / `REFUSAL` / `ADDRESS_CORRECTION` charges are also AUTO but are never reversed by a later capture — domain.py:293-297
- §3.4 — revise — mismatch — a `WAIVED`/`REVERSED` charge is neither revived nor counted as coverage, so the next capture re-implying that code creates a brand-new `ASSESSED` charge — domain.py:282-291
- §3.5 — insert — ambiguity — exception `reason` must be non-empty when supplied and is copied onto every charge it creates; each charge's `assessed_basis` is `exception_kind=<kind>` — routes_shipments.py:258,268-281
- §3.5 — insert — mismatch — the freeze test inspects only the shipment's non-voided line, so a never-swept package and a package whose line was voided both pass freely — pricing.py:168-177 via routes_shipments.py:264
- §3.5 — insert — ambiguity — `amount_cents` must be an integer >= 0, an explicit 0 is honoured rather than falling back to the resolved rate, `assessed_basis` is `manual_entry=true`, and neither shipment nor account is versioned by a hand entry — routes_shipments.py:300-311
- §3.5 — revise — mismatch — "once the line's invoice has left `OPEN`" → the non-voided line's invoice being `ISSUED`, `ADJUSTED`, or `SETTLED` (a VOID invoice does not freeze) — pricing.py:165
- §3.5 — insert — ambiguity — a supplied waiver `reason` overwrites the charge's existing one, omission preserves it, and only the charge's `version` moves — routes_shipments.py:337-351
- §3.6 — insert — ambiguity — no state gate guards the billing preview: `IN_TRANSIT`, `TOLERANCE_FLAGGED`, and already-billed packages all price identically — routes_shipments.py:148-152

Pass 2 raised one cross-partition item to pass 3 (§2.9's `SETTLED` freeze imprecision).

### Pass 3 (billing + claims + pricing + serializers) — 12 ambiguity-pins, 3 mismatch-revisions
- §2.9 — revise — mismatch — the hand-trigger reject branch now names `ISSUED`/`ADJUSTED`/`SETTLED`, and the last bullet is scoped to scan triggers only, noting a `VOID` invoice lands in the "no line exists" branch because voiding flags every line `voided` — pricing.py:165,168-177,222
- §3.6 — insert — ambiguity — a non-string/empty `include_shipment_ids` member is `ERR_SHIPMENT_NOT_FOUND`, a non-array is `ERR_INVALID_REQUEST`, and member resolution precedes the period schema check — routes_billing.py:54-64
- §3.6 — insert — ambiguity — already-billed and tolerance gates are two separate full passes over the named list, so already-billed always wins — routes_billing.py:70-77
- §3.6 — insert — ambiguity — all candidates are priced before any record is written, so `ERR_RATE_ROW_MISSING` leaves no invoice/line/`billing_status` change — routes_billing.py:102-103
- §3.6 — insert — ambiguity — `line_count` counts every line including `voided` ones, so voiding never lowers it — serializers.py:162
- §3.7 — revise — mismatch — on void only `net_amount_cents` reads 0; frozen subtotals, `gross_charges_cents`, `tier_discount_*` and derived `adjustment_total_cents` keep their pre-void values, and the invoice's `version` moves exactly once — domain.py:162-167, serializers.py:163-169, routes_billing.py:205-221
- §3.8 — insert — ambiguity — `ERR_ADJUSTMENT_EXCEEDS_LINE` is a proposal-time gate only, never re-checked at release — routes_billing.py:378-381
- §3.8 — insert — ambiguity — a package already at `ADJUSTED` stays there but still bumps `version`; the shipment version bump is unconditional — routes_billing.py:345-350
- §3.8 — insert — ambiguity — a supplied reject `note` overwrites, an omitted one leaves the existing `note` intact — routes_billing.py:277-282
- §3.9 — insert — ambiguity — `disputed_codes` family membership is a schema-tier check, so an unknown code is `ERR_INVALID_REQUEST`, not `ERR_DISPUTED_CODE_NOT_ASSESSED` — routes_claims.py:54-55, validators.py:177-178
- §3.9 — insert — ambiguity — resolve check order is fixed: invoice-state → dispute-state → accepted-evidence — routes_claims.py:190-200
- §3.9 — insert — ambiguity — the uphold system adjustment also carries `applied_by_user_id` = `system` and a stamped `applied_at` — routes_claims.py:216-219
- §3.9 — insert — ambiguity — the referenced package also takes `BILLED → ADJUSTED` with a `version` bump — routes_claims.py:231-235
- §3.9 — revise — mismatch — removed the unreachable "0 when not late or suspended"; the candidate refund is always the line's `transportation_base_cents` — routes_claims.py:343-349
- §3.9 — insert — ambiguity — swept claims carry `filed_by_user_id` = literal `system` and null `claimed_reason` — routes_claims.py:409
- §3.9 — insert — ambiguity — approval also increments the invoice's `version`; the `DENIED` branch consults no invoice state — routes_claims.py:430-435,450

**Pass-3 verdict on the pass-2 hand-off:** confirmed real. `pricing.FROZEN_INVOICE_STATES` = `("ISSUED","ADJUSTED","SETTLED")` and `assert_not_frozen` raises `ERR_LINE_ALREADY_FROZEN` on all three, so §2.9's old wording was wrong for the three hand triggers. Fixed. Bonus finding: `VOID` is not in the freeze set, and `reconcile`'s `VOID` arm is effectively unreachable (voiding sets every line `voided`, so `live_line_for_shipment` returns `None`) — now stated inline. The bullet list remains six-way.

**Orchestrator verification:** `PRD_COMPLETED.md` is 529 lines and NOT byte-identical to `PRD_FINALIZED.md` (85 changed lines by diff) — the scan genuinely ran. It ends at a genuine section boundary (final §5 catalogue row `ERR_CREDIT_EXCEEDS_INVOICE_NET | 422`, 57 rows). Implementation module mtimes are unchanged since Step 6 generation (00:24–00:37, all predating the 03:05 clean sweep), confirming Step 9 was documentation-only and the verified 8×114/114 sweep still describes the shipped code.

## Pipeline complete — 2026-09-05T03:38:35.108Z

All nine steps finished. Final artifacts: SCAFFOLD.yaml (2859 lines, directive line stripped), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1742), SCAFFOLD_CORNER_DESIGN.yaml (4698), test_helpers/ (9 files / 2321 lines), test_suite/ (20 files / 10173 lines / 114 tests), workspace/PRD.md (528), workspace/PRD_FINALIZED.md (528), workspace/PRD_COMPLETED.md (529), workspace/implementation/ (16 files / 3462 lines, 52 endpoints) with results.{1..8}.json all at 114/114.
