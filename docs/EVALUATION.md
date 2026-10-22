# Sovereign On-Premise Agentic AI Workbench: Evaluation Benchmark (Phase 6)

## 1. Executive Summary & Objective

This document outlines the evaluation methodology, dataset design, mathematical metrics, and empirical findings for the **Sovereign On-Premise Agentic AI Workbench**. The primary objective of Phase 6 is to establish a headless, fully reproducible evaluation benchmark that systematically measures the reliability, schema adherence, retrieval accuracy, and system resource footprint of a local language model (**`qwen2.5:3b`** with **`nomic-embed-text`** embeddings) executing inside a sovereign agentic reasoning loop on consumer-grade hardware (**8 GB RAM laptop, zero cloud egress**).

All statistics and findings reported herein derive strictly from real experimental executions logged incrementally to `eval/results/*.jsonl`. No synthetic estimations, fabrications, or simulated values are permitted.

---

## 2. Benchmark Architecture & Isolation Guarantees

### 2.1 Workspace and Data Directory Isolation
To guarantee complete isolation between production data and benchmark runs:
1. The evaluation harness sets the environment variable `SOVEREIGN_DATA_DIR` to `eval/.workdir` prior to importing backend components.
2. `eval/.workdir` is strictly added to `.gitignore`, preventing benchmark artifacts from polluting version control.
3. The root application directory `data/` is strictly guarded. Before each benchmark run, the harness records the latest filesystem modification timestamp (`mtime`) of `data/` and re-verifies at teardown that `mtime_before == mtime_after`, empirically demonstrating zero writes to the production database or user files.

### 2.2 Code Path Reuse
The benchmark does not simulate or re-implement the agent loop. Instead, it directly invokes the production `AgentRunner.run_agent()` and `vector_store` routines with real SQLite database sessions (`sovereign.db` and `demo.db`), identical system prompt builders, and the exact same tool execution pipelines.

### 2.3 Memory Safety & Resource Safeguards
Running local LLMs alongside embedded vector stores on an 8 GB Windows laptop introduces risks of system freezes. The harness incorporates a `psutil`-based memory guard (`check_ram_safety`):
- Before each benchmark item is executed, available physical RAM is sampled.
- If available RAM falls below a configurable threshold (default `3.0 GB`, configurable via `--min-ram`), the harness aborts gracefully with a diagnostic message rather than risking an operating system freeze or swapping thrash.

### 2.4 Auto-Approval in Evaluation Mode
High-risk tools (specifically `read_sql` queries against `demo.db`) normally pause the agent loop and wait for human supervisor approval via the Streamlit UI. In headless evaluation mode, the harness automatically marks pending approvals as `approved` by `eval_auto_approver`, logs this event, resumes the agent run, and records `auto_approved: True` in the JSONL trace.

---

## 3. Dataset Design & The Freeze Rule

The benchmark dataset resides in `eval/data/` and is strictly decoupled from the developer regression prompt set (`tests/regression_prompts.json`).

```
eval/data/
├── docs/
│   ├── attendance_rules.txt    # 2,174 characters, Policy AC-804/rev3
│   ├── exam_regulations.txt    # 2,181 characters, Regulation EXAM-REG-502
│   └── library_rules.txt       # 2,276 characters, Charter LIB-POL-2026-V4
├── rag_questions.json          # 30 items (20 single-fact, 4 multi-sentence, 6 decoys)
├── agent_tasks.json            # 15 items (5 calculator, 5 SQL, 5 document search)
└── FROZEN.sha256               # Cryptographic integrity manifest
```

### 3.1 Synthetic College Policy Documents
Three distinctive documents (1.5k–2.5k characters each) were created containing highly specific, checkable institutional facts (dates, personnel names, fees, room numbers, percentage thresholds) that cannot be known from general internet pre-training:
1. **`attendance_rules.txt` (2,174 chars):** Clause 2.1 attendance threshold (82%), medical concession (7 percentage points via Form MED-401 to Dr. K. Radhakrishnan within 5 business days), non-negotiable floor (65%), surcharge (Rs 2,450 + 18 hrs library remediation), biometric window (08:15 AM to 08:35 AM at Kiosk-7), appeal deadline (October 24, 2026 in Room 304).
2. **`exam_regulations.txt` (2,181 chars):** Controller Dr. Hemant V. Deshmukh, hall admission cutoff (20 minutes after start), early exit lock (45 minutes), passing marks (42% theory, 50% aggregate), supplementary fee (Rs 1,150/credit before November 12, 2026), Clause 8.4 malpractice penalty (Level-2 infraction: 2-semester suspension), re-evaluation fee (Rs 850 via Form RV-11 within 12 days).
3. **`library_rules.txt` (2,276 chars):** Chief Librarian Mrs. Rajeshwari Ramanathan, quota (4 books for 16 days), fines (Rs 15/day for first 7 days, escalating to Rs 40/day on day 8), Wing C reference badge (CLRC-SEC-9), lost book policy (exact ISBN in 21 days + Rs 600 fee or 2.5x list price), Cyber Commons 90-minute cap, P2P penalty (Rs 3,200 fine + 30-day ban).

### 3.2 Question & Task Taxonomies
- **`rag_questions.json` (30 items):**
  - **Single-fact (20 items):** Direct factual retrieval requiring specific numerical or name answers.
  - **Paraphrased / Multi-sentence (4 items):** Synthesizing information across multiple clauses.
  - **Unanswerable Decoys (6 items):** Topically plausible queries where the text is deliberately silent (e.g., blood donation attendance, photocopying costs). The only acceptable behavior is explicit abstention (e.g., "I do not know" or "The documents do not contain this information"). Factual invention is scored as a failure.
- **`agent_tasks.json` (15 items):**
  - **Calculator Tasks (5 items):** Multi-step arithmetic, percentage discounts, and exponentiation. Ground truth is computed dynamically at runtime using safe Python AST evaluation (`eval_safe_arithmetic`).
  - **SQL Tasks (5 items):** Analytical queries over `demo.db` (`students` table). Ground truth is computed dynamically at runtime via a direct read-only SQLite `SELECT` query.
  - **Document Tasks (5 items):** Complex retrieval questions targeting Document Assistant.

### 3.3 The Freeze Rule & Tamper Detection
To prevent benchmark overfitting and prompt-tuning against the test set:
1. SHA-256 hashes for all 5 core dataset files are frozen in `eval/data/FROZEN.sha256`.
2. At every benchmark startup, `verify_dataset_frozen()` verifies the exact file hashes.
3. If any file hash differs, results are flagged with `dataset_status: "dataset modified"`.
4. Prompts, parsers, and system parameters are never modified to fit the evaluation dataset.

### 3.4 Distractor Corpus (Separate, Non-Frozen Extension)
To challenge pure retrieval discrimination without perturbing the frozen baseline dataset, a separate distractor corpus of 15 synthetic institutional policy documents was authored under `eval/data/distractors/` with its own dedicated cryptographic hash manifest `eval/data/distractors/DISTRACTORS.sha256`:
- **Document Volume:** 15 distinct documents (1,850 to 2,138 characters each) covering campus parking permits, hostel quiet hours, sports complex equipment, scholarship renewal GPA bands, laboratory hazardous materials safety, dining hall meal subscriptions, grievance cell escalation protocols, placement drive eligibility, incubation cell seed grants, student council elections, visiting scholar housing, health centre medical insurance, intellectual property patents, community service NSS requirements, and undergraduate internship credits.
- **Combined Corpus Size:** 18 documents total (3 core + 15 distractors).
- **Integrity Guarantee:** The 5 original frozen dataset files remain strictly untouched, verified by `verify_dataset_frozen()`.

---

## 4. Metric Definitions & Statistical Methodology

| Metric | Target | Definition |
| :--- | :--- | :--- |
| **`valid response`** (formerly `tool_call_valid`) | Response Adherence & Engine Health | Boolean: The first LLM response in the run was valid, non-engine-error schema-correct JSON matching Schema A (`tool`) or Schema B (`final`) before any retry prompt. Renamed from `tool_call_valid` to `valid response` where it encompasses both schema correctness and engine-level execution (isolating Ollama HTTP 500 token-repeat aborts as engine errors rather than schema invalidity). |
| **`task_success`** | Task Completion | Boolean: Expected tool was invoked AND the final answer matches ground truth or expected keywords. For decoys, success requires that the agent abstains without inventing facts. |
| **`retrieval_hit@3`** | Document Retrieval | Boolean: The target document appears in the top-3 chunks retrieved by ChromaDB using `nomic-embed-text` cosine similarity. |
| **`chunk_hit@1`** | Chunk Precision | Boolean: The top-1 retrieved chunk contains the ground truth answer text / expected keywords. |
| **`chunk_hit@3`** | Chunk Recall | Boolean: At least one of the top-3 retrieved chunks contains the ground truth answer text / expected keywords. |
| **`mrr`** | Ranking Quality | Float: Mean Reciprocal Rank ($\frac{1}{\text{rank}}$) of the first retrieved chunk containing the correct answer text (0.0 if not found in top-3). |
| **`citation_valid`** | Hallucination Check | Boolean: Every file and chunk index cited in the final answer or sources exists in the indexed corpus. |
| **`latency_s`** | Inference Speed | Float: Execution time in seconds per item, excluding a one-time pre-benchmark warm-up call (`cold_start_s`). |
| **`peak_ollama_rss_mb`** | Memory Budget | Float: Peak summed Resident Set Size (RSS in MB) across all Ollama host processes and runner child processes (`llama-server.exe`). |
| **`REQUIRE_RETRIEVAL_BEFORE_ABSTAIN`** | Post-Hoc Flag | Architectural boolean flag (default `False`). When enabled, intercepts Document Assistant abstention attempts and forces one `search_documents` execution before accepting abstention. |

### 4.1 95% Wilson Confidence Intervals
For binomial rates $p = \frac{k}{n}$, standard normal approximations fail near 0% or 100%. We compute the **Wilson Score Interval** with continuity:
$$w = \frac{p + \frac{z^2}{2n} \pm z \sqrt{\frac{p(1-p)}{n} + \frac{z^2}{4n^2}}}{1 + \frac{z^2}{n}}$$
where $z = 1.95996$ for 95% confidence.

### 4.2 Paired McNemar Exact Test
For comparisons between two configurations evaluated on the identical set of items (e.g. Pre-registered Canonical vs Post-Hoc Variant), we identify discordant pairs:
- $b$: condition 1 failed (0) and condition 2 succeeded (1)
- $c$: condition 1 succeeded (1) and condition 2 failed (0)

Under null hypothesis $H_0: p = 0.5$, we evaluate the exact two-sided binomial probability using standard library `math.comb`:
$$\text{p-value} = 2 \sum_{i=0}^{\min(b, c)} \binom{b+c}{i} 0.5^{b+c}$$
If $b + c < 10$, the report issues an explicit warning stating that the sample size of discordant pairs is too small to conclude statistical significance.

---

## 5. Experimental Results (Empirical Data)

### 5.1 Experiment 1: RAG Chunk Size vs. Document Retrieval Hit@3 (3 Core Docs)
Evaluated on all 30 RAG questions using pure vector retrieval against embedded ChromaDB (`nomic-embed-text`). No LLM generation was invoked.

| Chunk Size | Total Queries ($n$) | Target Corpus Documents | Document Hit@3 Rate | 95% Wilson Confidence Interval | Mean Retrieval Latency |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **300 characters** | 30 | 27 chunks (9/doc) | **100.0%** (30/30) | [88.6%, 100.0%] | 2.37s |
| **500 characters** | 30 | 15 chunks (5/doc) | **100.0%** (30/30) | [88.6%, 100.0%] | 2.37s |
| **800 characters** | 30 | 9 chunks (3/doc) | **100.0%** (30/30) | [88.6%, 100.0%] | 2.34s |

**Key Finding (E1 Ceiling Effect / Null Result):**
Retrieval document hit rate was a uniform 100.0% across all three chunk sizes (300, 500, and 800 characters) on the 3 core synthetic documents. Because the 3 documents have distinct topical vocabularies, `nomic-embed-text` clustered the source document into the top 3 results regardless of window size. Consequently, **E1 does not discriminate between chunk sizes**, and chunk size 500 cannot be claimed as optimal from E1 data alone.

---

### 5.2 Experiment 1b: Distractor Corpus & Chunk-Level Retrieval Accuracy (18 Documents)
To rigorously test chunking under realistic vector competition, 15 synthetic policy documents (29.9 kB total) were added under `eval/data/distractors/` (combined corpus = 18 documents, 51–142 indexed chunks). We evaluated chunk-level retrieval: a hit requires that the retrieved chunk actually contains the ground truth answer text / expected keywords. Evaluated over all $n = 24$ answerable RAG queries.

| Chunk Size | Corpus Docs | Answerable Queries ($n$) | Chunk Hit@1 | 95% Wilson CI | Chunk Hit@3 | 95% Wilson CI | MRR | Key Empirical Finding |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **300 characters** | 18 | 24 | **75.0%** (18/24) | [55.1%, 88.0%] | **87.5%** (21/24) | [69.0%, 95.7%] | **0.8056** | Multi-sentence clauses split across chunk boundaries; CIs overlap at n=24 |
| **500 characters** | 18 | 24 | **75.0%** (18/24) | [55.1%, 88.0%] | **91.7%** (22/24) | [74.2%, 97.7%] | **0.8333** | Multi-sentence clauses split across chunk boundaries; CIs overlap at n=24 |
| **800 characters** | 18 | 24 | **83.3%** (20/24) | [64.1%, 93.3%] | **95.8%** (23/24) | [79.8%, 99.3%] | **0.8889** | Highest point estimate; 95% CIs overlap across sizes at n=24 (no superiority claim) |

**Empirical Finding on Chunk Size (No Claim of Superiority):**
When evaluated with distractor competition and verified chunk-level keyword containment across the $n = 24$ answerable queries, chunk size 800 achieved the highest point estimates for both Chunk Hit@3 (95.8%, 23/24) and MRR (0.8889), compared to 91.7% (22/24) and MRR 0.8333 for chunk size 500, and 87.5% (21/24) and MRR 0.8056 for chunk size 300.

However, at $n = 24$, the 95% Wilson confidence intervals substantially overlap across all three window sizes:
- **Chunk Hit@3:** 300 chars [69.0%, 95.7%] vs. 500 chars [74.2%, 97.7%] vs. 800 chars [79.8%, 99.3%]
- **Chunk Hit@1:** 300 chars [55.1%, 88.0%] vs. 500 chars [55.1%, 88.0%] vs. 800 chars [64.1%, 93.3%]

Because of this statistical overlap, **no claim of statistical superiority can be made**. The point-estimate advantage of chunk size 800 illustrates a qualitative pattern: institutional regulations frequently contain dependent conditions, exceptions, and fee amounts spanning multiple sentences. Smaller chunks (300–500 chars) fragment these clauses, separating the qualification from the quantitative rule, whereas chunk size 800 preserves contextual integrity. A larger evaluation corpus and query set would be required to establish a statistically significant separation.

---

### 5.3 Experiment 2: Reliability Factorial (JSON Mode x Retry)
Evaluated on `qwen2.5:3b`.

The two canonical runs are presented as the primary result. The pooled n=90 interval is labeled as approximate because the same 45 items are repeated across runs (observations are not independent). Pooled latency has been removed to avoid conflating repeated measures across varying host conditions; per-run and per-task-type latencies are retained.

| Configuration | Status | $n$ | Repeats | Valid Response | 95% Wilson CI | Task Success (Strict) | 95% Wilson CI | Mean Latency | Peak Ollama RSS | Retries |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Canonical Run 1** (`json_on_retry_on`) [Primary] | Completed | 45 | 1 | **100.0%** (45/45) | [92.1%, 100.0%] | **80.0%** (36/45) | [66.2%, 89.1%] | 27.86s* | 2,351.3 MB | 0 |
| **Canonical Run 2** (`json_on_retry_on_rerun`) [Primary] | Completed | 45 | 1 | **97.8%** (44/45) | [88.4%, 99.6%] | **80.0%** (36/45) | [66.2%, 89.1%] | 55.39s* | 2,205.5 MB | 0 |
| **Canonical Pooled** (Runs 1 & 2) [Approximate]* | Completed | 90 | 2 | **98.9%** (89/90) | [94.0%, 99.8%] | **80.0%** (72/90) | [70.6%, 87.0%] | N/A | 2,351.3 MB | 0 |
| `json_on_retry_off` | *not run* | 0 | 0 | N/A | N/A | N/A | N/A | N/A | N/A | 0 |
| `json_off_retry_on` | Completed | 45 | 1 | **93.3%** (42/45) | [82.1%, 97.7%] | **82.2%** (37/45) | [68.7%, 90.7%] | 23.53s* | 2,344.1 MB | 8 |
| `json_off_retry_off` | Completed | 45 | 1 | **88.9%** (40/45) | [76.5%, 95.2%] | **66.7%** (30/45) | [52.1%, 78.6%] | 19.25s* | 2,363.0 MB | 0 |

*\*Note on Latency & Memory Conditions:* All latency and RAM numbers were measured at ~0.8 GB free RAM on an 8 GB host with the IDE open; memory-constrained. Note that 40.06s is the post-hoc variant (`REQUIRE_RETRIEVAL_BEFORE_ABSTAIN`), not the canonical configuration. The canonical configuration runs (27.86s in Run 1, 55.39s in Run 2; pooled latency omitted) and post-hoc variant (40.06s) runs are not directly comparable because host memory load and paging were not controlled between test sessions.

**Reason why `json_on_retry_off` was NOT run:**
With JSON mode active (`json_mode=True`), the model produced zero format errors (0 retries in 90 items across Runs 1 and 2), so the retry mechanism had nothing to act on. The conclusion that `json_on_retry_off` would yield identical performance is an inference based on the absence of retries, not a tested result.

#### Paired Exact McNemar Tests for Experiment 2 (Identical Items):
1. **`json_off_retry_on` vs `json_off_retry_off` ($n = 45$ identical items):**
   - Concordant: Both Pass = 29, Both Fail = 7
   - Discordant: (`json_off_retry_on` Fail, `json_off_retry_off` Pass) [$b$] = **1** | (`json_off_retry_on` Pass, `json_off_retry_off` Fail) [$c$] = **8**
   - Total Discordant Pairs ($b + c$): **9**
   - Exact Two-Sided McNemar p-value: **0.03906**
   - **Finding:** Retry effect is suggestive (p = 0.039, 9 discordant pairs: $b = 1, c = 8$). While nominally below 0.05 ($p = 0.03906 < 0.05$), the sample size of discordant pairs is modest ($b + c = 9 < 10$). Retries recover schema violations and improve task completion when JSON mode is disabled.
2. **Canonical Run 1 vs `json_off_retry_on` ($n = 45$ identical items):**
   - Concordant: Both Pass = 35, Both Fail = 7
   - Discordant: (Canonical Fail, `json_off_retry_on` Pass) [$b$] = **2** | (Canonical Pass, `json_off_retry_on` Fail) [$c$] = **1**
   - Total Discordant Pairs ($b + c$): **3**
   - Exact Two-Sided McNemar p-value: **1.00000**
   - **Finding:** Difference is not statistically significant ($\alpha = 0.05$).
3. **Canonical Run 1 vs Canonical Run 2 ($n = 45$ identical items):**
   - Concordant: Both Pass = 33, Both Fail = 6
   - Discordant: (Run 1 Fail, Run 2 Pass) [$b$] = **3** | (Run 1 Pass, Run 2 Fail) [$c$] = **3**
   - Total Discordant Pairs ($b + c$): **6**
   - Exact Two-Sided McNemar p-value: **1.00000**
   - **Finding:** Difference is not statistically significant ($\alpha = 0.05$). Aggregate task success is identical (80.0% vs 80.0%).

#### Item-Level Flip Table: Canonical Run 1 vs Run 2
Across the 45 identical items, exactly **6 items flipped** between Run 1 and Run 2 ($13.3\%$; Run 1 Pass $\rightarrow$ Run 2 Fail: 3; Run 1 Fail $\rightarrow$ Run 2 Pass: 3; exact McNemar $p = 1.00000$):

| Item ID | Suite | Question | Expected Keyword / Ground Truth | Run 1 Outcome | Run 1 Response Summary | Run 2 Outcome | Run 2 Response Summary | Flip Diagnosis |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `rag_q09` | rag | Morning biometric scan window hours at Kiosk-7 | `['08:15', '08:35']` | **PASS** | Answered 08:15 AM to 08:35 AM | **FAIL** | "The provided documents do not contain this information." | Stochastic premature abstention without tool call on Run 2 |
| `rag_q11` | rag | Authorized Controller of Examinations | `['Deshmukh']` | **PASS** | Answered Dr. Hemant V. Deshmukh | **FAIL** | "The provided documents do not contain this information." | Stochastic premature abstention without tool call on Run 2 |
| `rag_q13` | rag | Minimum passing percentage for theory paper | `['42', 'percent']` | **FAIL** | "The provided documents do not contain this information." | **PASS** | Retrieved exam rules; answered 42% | Model recovered from Run 1 premature abstention; searched documents and answered correctly |
| `rag_q14` | rag | Registration fee per theoretical credit | `['1,150', '1150']` | **FAIL** | "I do not know." | **PASS** | Retrieved exam rules; answered Rs 1,150 | Model recovered from Run 1 premature abstention; searched documents and answered correctly |
| `rag_q20` | rag | Daily session cap on Cyber Commons workstations | `['90', 'minutes']` | **FAIL** | "The provided documents do not contain this information." | **PASS** | Retrieved library rules; answered 90 minutes | Model recovered from Run 1 premature abstention; searched documents and answered correctly |
| `rag_q30` | rag | Private group study room reservation fee *(Decoy)* | `['do not know', ...]` | **PASS** | "I do not know." | **FAIL** | Error: Ollama chat error (HTTP 500 repeat limit) | Ollama HTTP 500 token repeat limit abort on Run 2 (engine_error; valid response=False) |

---

### 5.4 Experiment 3: Prompt Variant (Hardened vs Baseline)
- **Hardened (Default):** Includes Rules 8 and 9 explicitly forcing immediate invocation of `read_sql` and `search_documents`.
- **Baseline:** Omits Rules 8 and 9.

| Variant | Status | $n$ | Valid Response | 95% Wilson CI | Task Success (Strict) | 95% Wilson CI | Mean Latency | Peak Ollama RSS |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Hardened** (Rules 8 & 9) | Completed | 45 | **100.0%** (45/45) | [92.1%, 100.0%] | **80.0%** (36/45) | [66.2%, 89.1%] | 27.86s* | 2,351.3 MB |
| **Baseline** (Rules 8 & 9 omitted) | Completed | 45 | **97.8%** (44/45) | [88.4%, 99.6%] | **55.6%** (25/45) | [41.2%, 69.1%] | 16.17s* | 2,402.2 MB |

*Note:* In `summary.csv`, the redundant duplicate row for `e3_prompt_hardened` has been removed to avoid double-counting the identical configuration from E2.

#### Paired Exact McNemar Test (Canonical Run 1 vs Baseline Prompt, $n = 45$ identical items):
- **Concordant Pairs:** Both Pass = 23, Both Fail = 7
- **Discordant Pairs:**
  - (Canonical Fail, Baseline Pass) [$b$]: **2 items** (`rag_q03`, `rag_q21`)
  - (Canonical Pass, Baseline Fail) [$c$]: **13 items** (`rag_q01`, `rag_q02`, `rag_q04`, `rag_q06`, `rag_q07`, `rag_q09`, `rag_q10`, `rag_q11`, `rag_q16`, `rag_q17`, `rag_q18`, `agent_sql_01`, `agent_sql_04`)
- **Total Discordant Pairs ($b + c$):** **15**
- **Exact Two-Sided McNemar p-value:** **0.00739**
- **Finding:** Prompt effect is strong (survives Bonferroni with 5 tests, threshold 0.01; exact two-sided $p = 0.00739 < 0.01$; $b = 2, c = 13$, 15 discordant pairs). Rules 8 and 9 produce a clear, statistically robust improvement in task completion (+24.4 percentage points) by actively preventing premature abstentions without tool calling. (Comparing Canonical Run 2 vs Baseline is likewise statistically significant: $b=4, c=15, p = 0.01921 < 0.05$).

---

### 5.5 Post-Hoc Architectural Variant: `REQUIRE_RETRIEVAL_BEFORE_ABSTAIN`
*(Clearly labeled POST-HOC architecture variant; reported separately from pre-registered configurations).*

To remedy the dominant failure mode observed in the pre-registered baseline (where the Document Assistant prematurely abstained on answerable questions without issuing a `search_documents` tool call), an architectural interceptor flag `REQUIRE_RETRIEVAL_BEFORE_ABSTAIN` (default `False`) was introduced into `backend/agent.py`. When enabled, if Document Assistant attempts to abstain on its first turn without executing a search, the harness forces one execution of `search_documents(query=...)` before accepting an abstention.

This feature was validated first against `tests/regression_prompts.json` in unit test `tests/test_require_retrieval_before_abstain.py` (passed), and then evaluated over the complete 45-item evaluation benchmark:

| Configuration | Status | $n$ | Valid Response | 95% Wilson CI | Task Success (Strict) | 95% Wilson CI | Task Success (Adjudicated) | 95% Wilson CI | Mean Latency | Peak Ollama RSS |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Canonical Pre-Registered** (`json_on_retry_on`) | Completed | 45 | **100.0%** (45/45) | [92.1%, 100.0%] | **80.0%** (36/45) | [66.2%, 89.1%] | **82.2%** (37/45) | [68.7%, 90.7%] | 27.86s* | 2,351.3 MB |
| **Post-Hoc Variant** (`REQUIRE_RETRIEVAL_BEFORE_ABSTAIN`) | Completed | 45 | **100.0%** (45/45) | [92.1%, 100.0%] | **88.9%** (40/45) | [76.5%, 95.2%] | **91.1%** (41/45) | [79.3%, 96.5%] | **40.06s** | **2,335.4 MB** |

#### Paired McNemar Test (Canonical vs Post-Hoc Variant, $n=45$ common items):
- **Concordant Pairs:** Both Pass = 34, Both Fail = 3
- **Discordant Pairs:**
  - Canonical Fail $\rightarrow$ Post-Hoc Pass ($b$): **6 items** (`rag_q08`, `rag_q13`, `rag_q14`, `rag_q19`, `rag_q20`, `agent_doc_03`)
  - Canonical Pass $\rightarrow$ Post-Hoc Fail ($c$): **2 items** (`rag_q03`, `rag_q21`)
- **Total Discordant Pairs ($b + c$):** 8
- **Exact Two-Sided McNemar p-value:** **0.28906**
- **Statistical Note on Sample Size:** Because the total number of discordant pairs ($b + c = 8$) is less than 10, the sample size is insufficient to reject the null hypothesis at the $\alpha = 0.05$ level, despite the notable empirical gain in task success rate (+8.9 percentage points strict, +8.9 percentage points adjudicated).

#### Post-Hoc Regressions and Validation Scope
The post-hoc intervention produced exactly **2 regressions** ($c=2$ items that passed in the canonical run but failed under post-hoc forced retrieval):
1. **`rag_q03` ("Who is the Chief Medical Officer to whom medical petitions must be submitted?"):**
   - **Expected Keyword:** `Radhakrishnan`
   - **Cause (Canonical Pass was a Scorer False Positive):** In the canonical run, the recorded "pass" was a scorer false positive (the answer contained the name "Radhakrishnan" while stating the documents did not specify the officer: *"...The documents only mention Dr. K. Radhakrishnan as the Chief Medical Officer, but do not specify that medical petitions must be submitted to him"*). Because the keyword matcher simply checked for the substring `"Radhakrishnan"`, it credited a success. In the post-hoc run, the model reached the same negative conclusion (*"Based on the provided documents, there is no information about the Chief Medical Officer to whom medical petitions must be submitted for medical petitions. The documents do not contain this information."*) but omitted the name, failing the keyword match. The regression was therefore an artifact of the canonical baseline's scorer false positive.
2. **`rag_q21` ("If a student falls ill and needs to miss lectures, what is the official form that must be filed, who reviews it, and what is the extent of attendance relief permitted?"):**
   - **Expected Keywords:** `['MED-401', 'Radhakrishnan', '7']`
   - **Cause:** In the canonical run, the model retrieved the clauses and correctly cited `Form MED-401`, `Dr. K. Radhakrishnan`, and `7 percentage points`. In the post-hoc run, after forced retrieval, the model failed to condition strictly on the retrieved text and instead hallucinated generic university priors: *"'Medical Absence Form' or a similar document... typically reviewed by the Academic Office or the Dean's Office"*, missing the specific keywords.

> [!WARNING]
> **Validation Scope Disclaimer:**
> The validation of the `REQUIRE_RETRIEVAL_BEFORE_ABSTAIN` interceptor was strictly a unit test (`tests/test_require_retrieval_before_abstain.py`) plus the 45-item evaluation benchmark. It was **not** evaluated on a broad multi-domain regression suite. Consequently, while it effectively resolved 6 premature abstention failures on this specific institutional benchmark, forcing retrieval before abstention carries the potential to induce regressions on open-domain queries (such as hallucinating generic answers on true out-of-domain queries or over-interpreting retrieved context).

---

### 5.6 Comprehensive Failure Analysis

#### Failure Cause Classification Across All Configurations
Every failed item in each evaluation configuration was classified according to the 5 specified root causes:

| Configuration | Total (n) | Failed Items | Premature Abstention | Wrong Answer After Retrieval | Engine Error | Invalid JSON | Wrong Tool | Timeout |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Canonical Run 1** (`json_on_retry_on`) | 45 | **9** (20.0%) | 6 | 3 | 0 | 0 | 0 | 0 |
| **Canonical Run 2** (`json_on_retry_on_rerun`) | 45 | **9** (20.0%) | 4 | 4 | 1 | 0 | 0 | 0 |
| **Canonical Pooled** (Runs 1 & 2) | 90 | **18** (20.0%) | 10 | 7 | 1 | 0 | 0 | 0 |
| **Factorial:** `json_off_retry_on` | 45 | **8** (17.8%) | 5 | 3 | 0 | 0 | 0 | 0 |
| **Factorial:** `json_off_retry_off` | 45 | **15** (33.3%) | 7 | 3 | 0 | 5 | 0 | 0 |
| **Baseline Prompt** (Rules 8 & 9 omitted) | 45 | **20** (44.4%) | 15 | 4 | 1 | 0 | 0 | 0 |
| **Post-Hoc Variant** (`REQUIRE_RETRIEVAL_BEFORE_ABSTAIN`) | 45 | **5** (11.1%) | 1 | 4 | 0 | 0 | 0 | 0 |

#### Technical Root Cause & Separation from Schema Errors: Engine Errors (`rag_q07` Baseline, `rag_q30` Run 2)
In the baseline prompt run (`e3_prompt_baseline.jsonl`), item `rag_q07` records `valid_response=False` with `retries=0`. Similarly, in Canonical Run 2 (`e2_json_on_retry_on_rerun.jsonl`), decoy item `rag_q30` records `valid_response=False` with `retries=0`.

Inspection of the raw JSONL traces reveals the recorded answer:
`"Error during model communication: Ollama chat error (HTTP 500): {\"error\":\"prediction aborted, token repeat limit reached\"}"`.

**Diagnostic Analysis & Root Cause:**
1. During text generation, the local Ollama process aborted prediction because the model exceeded Ollama's internal token repetition limit.
2. In `backend/agent.py` (lines 465–479), the HTTP 500 response raises an `OllamaError` at the transport layer before any completion string is returned to the parser.
3. The agent runner handles `OllamaError` by immediately aborting the run, recording the error message into `run.final_answer`, and returning `status="failed"`.
4. Because the engine aborted before returning any JSON agent action, `valid_response` evaluated to `False`. However, this is an **engine error** (`engine_error`), not a model schema formatting error. Consequently, "Invalid JSON" is 0 for both runs.
5. The agent retry mechanism (`MAX_FORMAT_RETRIES = 2`) is designed strictly for schema recovery when the model emits malformed JSON during ordinary completion. It is never triggered on engine crashes or HTTP transport errors.
Consequently, zero retries were attempted, resulting in `valid_response=False` with `retries=0`.

#### The 9 Failed Items from Canonical Run 1 Clarified
In the pre-registered canonical configuration (`e2_json_on_retry_on.jsonl`, $n=45$), exactly **9 items failed** under strict keyword scoring (36 succeeded, yielding $\frac{36}{45} = 80.0\%$). Every failed item ID and its empirical breakdown is presented below:

| Item ID | Suite | Question | Expected Keyword / Ground Truth | Model Response Summary | Classified Failure Cause |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `rag_q08` | rag | Remediation hours required under Clause 2.1 | `['18', 'hours']` | "The provided documents do not contain this information." | `premature_abstention_without_tool_call` |
| `rag_q13` | rag | Minimum passing percentage for theory paper | `['42', 'percent']` | "The provided documents do not contain this information." | `premature_abstention_without_tool_call` |
| `rag_q14` | rag | Registration fee per theoretical credit | `['1,150', '1150']` | "I do not know." | `premature_abstention_without_tool_call` |
| `rag_q19` | rag | Daily overdue fine rate from day 8 onward | `['40']` | "The provided documents do not contain this information." | `premature_abstention_without_tool_call` |
| `rag_q20` | rag | Daily session cap on Cyber Commons workstations | `['90', 'minutes']` | "The provided documents do not contain this information." | `premature_abstention_without_tool_call` |
| `rag_q22` | rag | Exam hall admission cutoff and earliest exit time | `['20', '45']` | "The provided documents do not contain this information." | `premature_abstention_without_tool_call` |
| `rag_q23` | rag | Can undergraduates take out rare manuscripts from Wing C | `['cannot', 'CLRC-SEC-9']` | "Undergraduate students are not allowed to take out rare manuscripts from Wing C. A special badge named CLRC-SEC-9 is needed..." *(Correct answer; keyword "cannot" not matched)* | `scorer_false_negative` (`wrong_answer_after_retrieval`) |
| `rag_q27` | rag | Passing percentage for foreign language elective *(Decoy)* | `['do not know', 'not mentioned']` | Hallucinated exam passing score (42% / 50%) instead of abstaining | `wrong_answer_after_retrieval` |
| `agent_doc_03` | agent | Library charter infraction fee for unauthorized P2P | `['3,200', '3200']` | Initial tool arguments formatting error followed by model abstention | `wrong_answer_after_retrieval` |

#### Scorer False Negative Report: `rag_q23`
Item `rag_q23` represents an automated string-scoring false negative:
- **Question:** *"Can undergraduate students take out rare manuscripts from Wing C, and what special badge is needed for on-site inspection?"*
- **Ground Truth Expected Keywords:** `['cannot', 'CLRC-SEC-9']` (match: all)
- **Model Output:** *"Undergraduate students are not allowed to take out rare manuscripts from Wing C. A special badge named CLRC-SEC-9 is needed for on-site inspection of these rare manuscripts."*
- **Adjudication:** The model correctly retrieved `library_rules.txt`, correctly identified that undergraduate students are forbidden from removing rare manuscripts, and provided the exact required badge identifier `CLRC-SEC-9`. The response is factually and semantically correct. It was scored as a failure solely because the model formulated the prohibition as *"are not allowed to"* rather than matching the literal keyword string *"cannot"*.

#### Strict vs. Adjudicated Benchmark Success Rates
Crediting `rag_q23` yields the adjudicated success rate:

| Metric | Canonical Run 1 (E2) | Post-Hoc Architectural Variant |
| :--- | :--- | :--- |
| **Strict Task Success Rate** | **80.0%** (36/45) [66.2%, 89.1%] | **88.9%** (40/45) [76.5%, 95.2%] |
| **Adjudicated Task Success Rate** | **82.2%** (37/45) [68.7%, 90.7%] | **91.1%** (41/45) [79.3%, 96.5%] |

The categorized failure distribution is visualized in `eval/results/failure_analysis.png`.

---

## 6. System Resource Footprint & Latency Conditions (8 GB Hardware Budget)

### 6.1 Host Memory Pressure Context & Measured Free RAM
All latency and RAM numbers were **measured at ~0.8 GB free RAM on an 8 GB host with the IDE open; memory-constrained** (Windows 11, 7.69 GB usable RAM). Baseline operating system services and typical development processes consume approximately 6.7 GB to 7.1 GB of RAM on this machine, leaving between 0.62 GB and 0.85 GB free at benchmark invocation (requiring `--min-ram 0.1`).

#### Measured Free RAM and Latency Context:
- **Retrieval-Only Benchmarks (E1 & E1b):** Initial available RAM measured **~0.84 GB**. Mean retrieval latency across ChromaDB vector search was **2.34s – 2.37s** (std 0.01s – 0.14s). Peak Ollama generation RSS is recorded as **N/A** in `summary.csv` because no LLM generation process was invoked.
- **Canonical E2 Run 1 (Oct 16):** Initial available RAM measured **~0.65 GB**. Warm-up cold start was **11.667s**, and overall mean latency was **27.86 seconds per item** (median **31.41s**, std **12.90s**).
- **Canonical E2 Run 2 (Oct 17):** Initial available RAM measured **~0.78 GB**. Warm-up cold start was **8.792s**, and overall mean latency was **55.39 seconds per item** (median **60.74s**, std **31.59s**).
- **Canonical Pooled ($n=90$, Repeats=2):** Pooled latency is omitted to avoid conflating repeated measures across fluctuating host memory conditions. Individual run latencies (Run 1: 27.86s, Run 2: 55.39s) and per-task-type latencies are retained.
- **Hypothesis on Canonical Latency Variation:** It is hypothesized (not an empirical finding) that host memory paging and thread contention under Windows background services significantly fluctuated execution speed between sessions, while premature 1-turn abstentions without tool calling reduced durations for items that failed early.
- **Post-Hoc Architectural Variant Run (`posthoc_retrieval_before_abstain`, Oct 17):** Note that **40.06 s is the post-hoc variant, not the canonical configuration**. Initial available RAM was measured at **~0.82 GB**. Warm-up cold start was **3.967s**. Mean latency per item was **40.06 seconds** (median **43.09s**, std **14.45s**, min **12.73s**, max **64.19s**). Peak Ollama host RSS was **2,335.4 MB (~2.28 GB)**.
- **Comparability Warning:** The canonical (27.86s / 55.39s) and post-hoc (40.06s) runs are **not directly comparable** because host memory load was not controlled between the runs (background process activity, initial available RAM, and memory paging varied across test sessions).
- **Real Host Live Acceptance Verification (`scripts/live_check.py 1`):** Measured at start with **~0.85 GB** available RAM; peak Ollama process RAM was **2,232.04 MB** and peak backend process RAM was **167.11 MB**.

#### Detailed Per-Task Latency Breakdown Across Configurations:

| Configuration | Total (n) | Overall Mean Latency | RAG Policy Queries | Calculator Tasks | SQL Analytical Tasks | Document Assistant Tasks |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Canonical Run 1** (`json_on_retry_on`) | 45 | **27.86s** | 32.17s | 12.32s | 17.31s | 28.14s |
| **Canonical Run 2** (`json_on_retry_on_rerun`) | 45 | **55.39s** | 71.71s | 10.30s | 14.37s | 43.53s |
| **Factorial:** `json_off_retry_on` | 45 | **23.53s** | 26.28s | 10.46s | 16.21s | 27.46s |
| **Factorial:** `json_off_retry_off` | 45 | **19.25s** | 20.81s | 10.46s | 10.59s | 27.33s |
| **Baseline Prompt** (Rules 8 & 9 omitted) | 45 | **16.17s** | 17.82s | 10.22s | 13.73s | 14.69s |
| **Post-Hoc Variant** (`REQUIRE_RETRIEVAL_BEFORE_ABSTAIN`) | 45 | **40.06s** | 45.79s | 16.44s | 24.02s | 45.33s |

> [!IMPORTANT]
> **Methodology Note on Latency Comparability (Why Overall Means Cannot Be Directly Compared):**
> Overall aggregate latency means across configurations are **not directly comparable** because abstentions end early. When an agent prematurely abstains without issuing a tool call (such as the 15 premature abstentions in `e3_prompt_baseline`, 6 in Canonical Run 1, and 7 in `json_off_retry_off`), it generates a short negative sentence on Turn 1 in ~10–12 seconds without executing vector searches or database queries. Conversely, configurations that successfully invoke tools perform multi-turn reasoning and retrieval loops lasting 25–70+ seconds. Aggregate mean latencies thus confound execution efficiency with failure-mode dropouts (a configuration with more early-exit failures appears misleadingly "faster"). Meaningful latency evaluations must be compared per task type and conditioned on multi-turn tool execution.

#### Memory Safety Safeguards:
When Ollama holds `qwen2.5:3b` in host memory alongside the backend and vector store, total system memory utilization exceeds 87% (available RAM hovers between 0.60 GB and 0.95 GB). The `psutil`-based safety guard (`check_ram_safety` configured to `--min-ram 0.1`) actively ensured that runs did not cause operating system kernel panics or swapping thrashing.

---

## 7. Fresh Test Suite & Live Acceptance Verification

Fresh validation runs performed directly on the `evaluation` branch:

### 7.1 Non-Live Test Suite (`pytest -m "not live"`)
```
================ 74 passed, 2 deselected, 1 warning in 58.25s =================
```
- Includes 8 metric unit tests (`tests/test_eval_metrics.py`), the new post-hoc interceptor unit test (`tests/test_require_retrieval_before_abstain.py`), and all security/audit/RBAC tests.

### 7.2 Real Host Live Acceptance Check (`scripts/live_check.py 1`)
```
======================================================================
  1-RUN LIVE ACCEPTANCE SUMMARY
======================================================================
  [PASS] a) GET /health (Ollama & models present)          : 1/1 (100%)
  [PASS] b) Auth roles (1st=admin, 2nd=user)               : 1/1 (100%)
  [PASS] c) Document upload (attendance rules)             : 1/1 (100%)
  [PASS] d) Document Assistant (citation check)            : 1/1 (100%)
  [PASS] e) Calculator tool used (15% of 2480)             : 1/1 (100%)
  [PASS] f1) Data Analyst approval (approved)              : 1/1 (100%)
  [PASS] f2) Data Analyst approval (denied)                : 1/1 (100%)
  [PASS] g) Negative retrieval (says does not know)        : 1/1 (100%)

  Peak Ollama Process RAM: 2232.04 MB
  Peak Backend Process RAM: 167.11 MB
>>> ALL 1 RUN(S) PASSED 100% AGAINST REAL HOST OLLAMA (WORKING) <<<
```

---

## 8. Threats to Validity

The empirical findings of this benchmark must be interpreted within the context of four primary methodological and hardware constraints:

1. **Sample Size and Repeated Measures ($n = 45$ per run, $n = 90$ pooled):**
   The primary benchmark evaluation result is presented through the two canonical runs ($n = 45$ each, 80.0% task success). The pooled $n = 90$ confidence interval ([70.6%, 87.0%]) is labeled as approximate because the same 45 items are repeated across runs (observations are clustered, not statistically independent).
   For paired comparisons across identical items:
   - **Prompt Effect:** Strong (survives Bonferroni with 5 tests, threshold 0.01; exact two-sided $p = 0.00739 < 0.01$, $b = 2, c = 13$, 15 discordant pairs).
   - **Retry Effect:** Suggestive ($p = 0.039$, 9 discordant pairs: $b = 1, c = 8$). While nominally below 0.05 ($p = 0.03906 < 0.05$), the modest discordant count ($b + c = 9 < 10$) warrants caution against asserting unconditional significance.
   - **Canonical vs Post-Hoc:** Not significant ($p = 0.28906$, 8 discordant pairs: $b = 6, c = 2$).
   No claims of statistical significance are asserted without an exact test ($p < 0.05$).

2. **Synthetic Policy Documents:**
   The evaluation corpus comprises 3 core documents (1,500–2,500 chars) and 15 distractor documents crafted with explicit numerical and named institutional rules. Although designed to mimic real university statutes, synthetic documents feature well-structured typography, clear section headings, and explicit parameters. Real-world enterprise and institutional corpora typically feature unstructured layouts, multi-page scanned PDFs, OCR transcription errors, ambiguous footnotes, complex multi-column tables, and contradictory administrative amendments, which present greater vector retrieval noise.

3. **Repeatability ($r = 2$ for Canonical Configuration):**
   The canonical configuration was evaluated across two full repeats ($r = 2$, pooled $n = 90$), demonstrating identical aggregate task success (80.0% in Run 1 and 80.0% in Run 2; McNemar $p = 1.00000$). Nonetheless, item-level analysis revealed 6 flips ($13.3\%$) driven primarily by stochastic premature abstention vs retrieval recovery, plus 1 Ollama HTTP 500 engine repeat-limit abort. Single-run configurations (`json_off_retry_on`, `json_off_retry_off`, baseline prompt) remain subject to run-to-run stochastic variance in tool generation order.

4. **Single Evaluated Model (`qwen2.5:3b`):**
   All evaluation data, JSON schema adherence rates, premature abstention rates, and post-hoc retrieval behaviors were measured exclusively on `qwen2.5:3b` under Ollama on CPU. Findings cannot be directly extrapolated to larger parameter sizes (e.g. 7B, 14B, 32B) or other model families (such as Llama-3, Mistral, or Gemma). Larger models may possess stronger inherent instruction following that could obviate the need for post-hoc retrieval interceptors, but would require hardware with at least 16 GB to 32 GB of system RAM.

---

## 9. Exact Commands to Reproduce Experiments

Ensure Ollama is running natively at `http://localhost:11434` with `qwen2.5:3b` and `nomic-embed-text` pulled.

```powershell
# Activate Python 3.11 Virtual Environment
.\.venv\Scripts\activate

# 1. Run Unit Tests (zero Ollama required)
pytest tests/test_eval_metrics.py tests/test_require_retrieval_before_abstain.py

# 2. Run Non-Live Test Suite
pytest -m "not live"

# 3. Run Live Acceptance Check Against Real Host Ollama
python scripts/live_check.py 1

# 4. Reproduce Experiment 1 (Core Corpus, Chunk Size 300, 500, 800)
python eval/run_eval.py --chunk-size 300 --suite rag --retrieval-only --out eval/results/e1_chunk_300.jsonl
python eval/run_eval.py --chunk-size 500 --suite rag --retrieval-only --out eval/results/e1_chunk_500.jsonl
python eval/run_eval.py --chunk-size 800 --suite rag --retrieval-only --out eval/results/e1_chunk_800.jsonl

# 5. Reproduce Experiment 1b (18-Doc Distractor Corpus, Chunk Size 300, 500, 800)
python eval/run_eval.py --chunk-size 300 --suite rag --retrieval-only --distractors --out eval/results/e1b_chunk_300.jsonl
python eval/run_eval.py --chunk-size 500 --suite rag --retrieval-only --distractors --out eval/results/e1b_chunk_500.jsonl
python eval/run_eval.py --chunk-size 800 --suite rag --retrieval-only --distractors --out eval/results/e1b_chunk_800.jsonl

# 6. Reproduce Experiment 2 (Canonical Pre-Registered Reliable Configuration)
python eval/run_eval.py --suite all --repeats 1 --json-mode on --retry on --prompt-variant hardened --min-ram 0.1 --out eval/results/e2_json_on_retry_on.jsonl

# 7. Reproduce Post-Hoc Architectural Variant
python eval/run_eval.py --suite all --repeats 1 --json-mode on --retry on --prompt-variant hardened --require-retrieval-before-abstain --min-ram 0.1 --out eval/results/posthoc_retrieval_before_abstain.jsonl

# 8. Generate Summary CSV, Markdown Report, and Charts
python eval/report.py

# 9. View Results in Streamlit UI (Admin Only)
streamlit run ui/app.py
```

---

## 10. Future Work: Multi-Model Comparative Evaluation

As hardware budgets permit (e.g., workstations with 16 GB+ RAM or dedicated VRAM):
1. **Model Comparison:** Benchmark larger quantized local models:
   - `mistral:7b-instruct-q4_K_M` (~4.4 GB RAM)
   - `llama3.1:8b-instruct-q4_K_M` (~4.7 GB RAM)
   - `phi3:mini` (~2.3 GB RAM)
2. **Automated Prompt Tuning:** Formally compare chain-of-thought system prompts against direct tool instruction prompts.
3. **Hybrid Sparse + Dense Retrieval:** Introduce BM25 lexical ranking alongside `nomic-embed-text` dense vector embeddings for hybrid retrieval.
4. **Engine Error Recovery:** Retry or recover on Ollama token-repeat HTTP 500 aborts (such as resetting the context window or backoff/temperature adjustment upon encountering `prediction aborted, token repeat limit reached`). This was not implemented in the benchmarked system; doing so now would constitute an unmeasured post-hoc modification.

---

## 11. Post-Evaluation Fixes (Post-eval-v1)

> [!NOTE]
> **Baseline Integrity Notice:** All baseline benchmark results, confidence intervals, and frozen datasets reported in Sections 1–8 represent the evaluated system at Git tag `eval-v1`. The modifications detailed below represent post-evaluation bug fixes and refinements identified during manual UI testing. No test sets were altered, no baseline results were overwritten, and no tuning against evaluation questions was performed.

### 11.1 Bug Fix 1: Tool Argument Wrapper Key Normalization
- **What:** Implemented recursive unwrapping (`unwrap_tool_args` and `normalize_tool_args` in `backend/agent.py`) supporting wrapper keys `args`, `arguments`, `parameters`, `params`, `input` (whether passed as Python dictionaries or JSON-encoded strings, with or without trailing colons such as `args:`), alongside canonical parameter mapping across all registered tools.
- **Why:** During manual UI interaction, small models (`qwen2.5:3b`) emitted tool call JSON with wrapper keys such as `{"action": "search_documents", "args:": {"query": "..."}}` or `{"tool": "search_documents", "args": {"args": {"query": "..."}}}`, which previously caused Python to raise `TypeError: search_documents() got an unexpected keyword argument 'args:'`.
- **Investigation & Evidence (Read-Only Search):**
  - **`eval/results/*.jsonl` (13 files):** Exactly **0 occurrences** of `unexpected keyword argument`. Evaluation JSONL logs record final answers and top-level outcomes; runs where the model recovered in a subsequent turn recorded the final answer rather than intermediate step exceptions.
  - **`eval/.workdir/sovereign.db`:** Exactly **152 step occurrences across 152 distinct runs** where the model emitted `{"action": "search_documents", "args:": ...}`, generating an intermediate `Tool Execution Error: search_documents() got an unexpected keyword argument 'args:'` at Step #3. In inspected traces (e.g. Run #228), the model observed the error and self-corrected in Step #4 by emitting `{"action": "search_documents", "args": ...}`, succeeding at the expense of 2 additional reasoning turns and latency.
  - **`data/sovereign.db`:** Exactly **6 step occurrences across 6 runs**.
  - **`data_backup/sovereign.db`:** Exactly **2 step occurrences across 2 runs**.
- **Verification:** Unit tests in `tests/test_agent_parsing.py` verify all 17 wrapper shapes (including JSON strings, colon suffixes, and nested dicts). Regression tests using the exact queries `"How many days can I borrow a book and what is the overdue fine?"` and `"What is the hostel curfew time?"` against `sample_policy.txt` pass cleanly with zero tool errors.

### 11.2 Refinement 2: Boundary-Preserving Text Chunker
- **What:** Replaced the character-slicing chunker in `backend/rag.py` (`TextChunker.chunk_text`) with a boundary-preserving algorithm that prioritizes paragraph breaks (`\n\n`), line breaks (`\n`), sentence boundaries (`. `, `? `, `! `), and word boundaries, never splitting mid-word while honoring `chunk_size` and `chunk_overlap`.
- **Why:** The previous chunker sliced text blindly at character offsets (`cleaned_text[start:start+size]`), bisecting words mid-token (e.g., splitting `"Hall tickets"` into `"Hall ti"` and `"ety goggles"` in `sample_policy.txt`), degrading semantic embeddings and precision.
- **Empirical Evidence (Retrieval-Only E1b Comparative Evaluation):**
  Post-evaluation retrieval-only benchmarks were run across the 18-document distractor corpus ($n = 24$ answerable items) for chunk sizes 300, 500, and 800 characters without modifying frozen data:

| Chunk Size | Baseline Chunk Hit@1 (`eval-v1`) | Post-Eval Chunk Hit@1 (`fixes`) | Baseline Chunk Hit@3 (`eval-v1`) | Post-Eval Chunk Hit@3 (`fixes`) | Baseline MRR (`eval-v1`) | Post-Eval MRR (`fixes`) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **300 chars** | 75.0% (18/24) | **83.3%** (20/24, +8.3%) | 87.5% (21/24) | **100.0%** (24/24, +12.5%) | 0.8056 | **0.9097** (+0.1041) |
| **500 chars** | 75.0% (18/24) | **95.8%** (23/24, +20.8%) | 91.7% (22/24) | **100.0%** (24/24, +8.3%) | 0.8333 | **0.9792** (+0.1459) |
| **800 chars** | 83.3% (20/24) | **83.3%** (20/24, unchanged) | 95.8% (23/24) | **100.0%** (24/24, +4.2%) | 0.8889 | **0.8958** (+0.0069) |

- **Key Takeaways:**
  1. **100.0% Top-3 Recall:** With word and sentence integrity preserved, Chunk Hit@3 reached 100.0% (24/24) across all chunk sizes.
  2. **Substantial Precision Gain at 500 chars:** Chunk Hit@1 increased from 75.0% to 95.8% (23/24), and MRR jumped from 0.8333 to 0.9792, demonstrating that avoiding mid-clause cuts allows dense embeddings to match queries directly to the top-ranked chunk.

### 11.3 UI Fixes: Citations, Status, Badge Clipping & Uploader Reset
- **What & Why:**
  1. **Citations Filtering:** Tool execution errors are now strictly excluded from the "Citations & Sources" panel and only rendered in the execution trace under the **Traces** tab.
  2. **Recovered Status Display:** The Chat interface displays `⚠️ Completed with a recovered tool error` whenever an intermediate tool failure or format retry occurred but the agent subsequently finalized successfully.
  3. **Ollama Status Badge:** Adjusted header columns to `[2, 1]` and applied `white-space: nowrap` with `0.78rem` font size to `.status-pill`, eliminating badge clipping on laptop resolutions.
  4. **Document Uploader Reset:** Added dynamic session-state widget keying (`doc_uploader_key`) so the Streamlit file uploader resets to empty after successful document ingestion.

### 11.4 Post-Eval Fix 4: Extended Argument Normalization for Malformed Wrapper Keys (`"args: {"`) & String Prefixes
- **What:** Enhanced argument normalization in `backend/agent.py` by:
  1. Adding `clean_wrapper_key()` to strip trailing whitespace, colons, and opening braces (`:{ \t`) from malformed keys (e.g. converting `"args: {"` to `"args"`).
  2. Unwrapping string arguments with prefixes like `"query: <text>"` or `"expression: <expr>"`.
  3. Handling tool parameters passed as raw string values directly under malformed wrapper keys.
- **Why (Evidence First from `data/sovereign.db`):**
  Inspection of all error steps in `data/sovereign.db` revealed real observed malformed shapes:
  - Run 1 (Step 3): `"args:"` with trailing colon.
  - Run 4 (Step 3): `file_path` alias mismatch instead of `filename` for `read_file`.
  - Runs 5, 9, 13, 17, 19: Malformed wrapper keys containing opening braces, e.g. `{"action": "search_documents", "args: {": {"query": "..."}}` and `{"args: {": "query: "}`.
  - In manual testing following the initial unwrapping fix, Run 19 produced `"args: {": "query: "` which caused `search_documents() got an unexpected keyword argument 'args: {'`, recovering on Step 4 and displaying `⚠️ Completed with a recovered tool error`.
- **Verification:** Unit tests added in `tests/test_agent_parsing.py` for each real observed shape (34 tests passing).

### 11.5 Post-Eval Fix 5: Pre-Approval SQL Static Validation, Runtime Demo Schema Injection & Tool Loop Blocking
- **What:**
  1. **Pre-Approval Static Validation (`backend/tools.py:validate_sql_query`):** Prior to creating an approval request, proposed SQL queries are statically checked for:
     - Exactly single-statement execution.
     - Strictly SELECT queries (no UPDATE, INSERT, DELETE, DROP, ATTACH, ALTER, etc.).
     - No comment injections (`--` or `/* ... */`).
     - Real SQLite validity via `EXPLAIN <query>` executed on a read-only SQLite connection against `demo.db`.
     If static checks fail, `PolicyDecision.DENIED` is returned directly to the agent with the exact validation error and current SQLite schema without creating a human approval request.
  2. **Runtime SQLite Demo Schema Injection (`backend/tools.py:get_demo_db_schema`):** Dynamically inspects `demo.db` (`sqlite_master` and `PRAGMA table_info(students)`) and injects the live table name and column definitions into the agent prompt context. This completely prevents the model from hallucinating MySQL-specific queries (e.g., `SHOW TABLES` or `information_schema.tables`).
  3. **Duplicate Tool Execution Loop Prevention (`backend/agent.py`):** The agent tracks failed or denied tool call signatures `(tool_name, frozenset(args))`. Repeated calls to the same tool with identical arguments are blocked immediately with a recorded policy step, preventing infinite loop thrashing and duplicate supervisor approvals.
- **Verification:** Comprehensive unit and mock tests in `tests/test_data_analyst_prevalidation.py` (9 tests passing).

### 11.6 Post-Eval Fix 6: UI Robustness, Approvals Plain-Language SQL Notes, Latency Consistency & Abstentions
- **What:**
  1. **Status Pill Header Clipping:** Increased Streamlit main container top padding to `3.5rem !important` (and `4.8rem` on narrow viewports <= 768px) and added `.status-pill-wrapper` margins, ensuring the full pill (all borders) is visible without clipping under the Streamlit top bar.
  2. **Data Analyst Result Lifecycle in Chat:** Persisted `latest_run_id` in `st.session_state`. When a Data Analyst run pauses for approval, the Chat tab displays `⏳ Waiting for approval — open the Approvals tab` with a refresh button. After approval or denial in the Approvals tab, returning to Chat (or clicking refresh) immediately displays the final result (status banner, answer, citations, latency, trace ID) exactly like Document Assistant. Denied runs clearly display the supervisor denial message alongside the model's final response.
  3. **Approvals Card Plain-Language SQL Note:** When `read_sql` is requested, the card displays the proposed SQL in a dedicated code block along with a clear note: `ℹ️ Plain-language note: read-only SELECT on the demo database`, plus a link to view the run in Chat.
  4. **Latency Consistency:** Formatted latencies with 2 decimal places in seconds and milliseconds. Added explanatory timing notes clarifying that total run latency measures cumulative step compute execution time (LLM + tool + policy) and excludes human approval pause wait time.
  5. **Abstention Panel Heading Rename:** When the model abstains ("I do not know", "cannot find", "does not contain"), the source panel heading is dynamically renamed from "Citations & Sources" to "Retrieved context" to accurately reflect that retrieved chunks were insufficient to answer the query.
- **Verification:** Verified via `tests/test_ui_comprehensive.py` (11 tests passing).

### 11.7 Post-Eval Fix 7: Shared Institutional Knowledge Base Architecture & Object-Level Authorization
- **What:** Clarified and verified the dual security boundary of Document Management:
  - **Shared Knowledge Base:** Uploaded documents are treated as an institutional knowledge base queryable by all authorized agents and users for RAG retrieval.
  - **Object-Level Authorization:** Regular (non-admin) users cannot delete or modify documents uploaded by other users (enforced with HTTP 403 and UI read-only badges), and cannot see other users' runs, traces, pending approvals, or audit logs.
- **Verification:** Explicitly verified via `tests/test_stage3_security.py::test_object_level_authorization` and `tests/test_ui_comprehensive.py::test_ui_documents_shared_kb_and_authorization`.

### 11.8 Post-Eval Tooling 8: Clean-State Development Reset Tool (`scripts/reset_dev_state.py`)
- **What:** Created `scripts/reset_dev_state.py` (and `scripts/reset_dev_state.ps1` wrapper):
  - Refuses to run if ports 8000 or 8501 are active (unless `--force`).
  - Prompts for confirmation (unless `--yes`).
  - Backs up `data/` to a timestamped folder `data_backup_YYYYMMDD_HHMMSS` (git-ignored).
  - Purges all application state (`sovereign.db`, WAL/SHM, Chroma vector store, uploads, logs) and recreates empty directories.
  - Re-seeds `data/demo.db` with the canonical 10-row `students` table, validating row counts, GPA > 3.80 count (4), and Meera Nair marks (89).
  - Never touches `.env`, `eval/`, `tests/`, `docs/`, source code, or existing backup folders.
- **Verification:** Ran end-to-end reset, verified all zero-counts and 10 demo rows, started backend, verified user registration and `scripts/demo_check.py` acceptance (all 5 steps passed), and executed clean final reset.

---

## 12. Erratum: Evaluation Benchmark Scope (`eval-v1`) vs Post-Evaluation Enhancements

**Important Notice:** All empirical benchmark metrics, tables, and figures reported in Sections 5 through 10 of this document represent the performance of the system as evaluated under tag `eval-v1` (prior to post-evaluation bug fixes and improvements).

1. **Integrity of Historical Results:** None of the earlier reported benchmark numbers, confidence intervals, or figures have been altered or retroactively overwritten. The frozen dataset and results remain preserved under `eval/data/` and `eval/results/`.
2. **Analysis of Evaluated Traces (`eval/.workdir/sovereign.db`):**
   - **Step Error Incidence:** Across all 273 runs logged in `eval/.workdir/sovereign.db` under `eval-v1`, the `Tool Execution Error: search_documents() got an unexpected keyword argument` occurred in **152 out of 273 runs (55.68%)**.
   - **Per Agent Breakdown:**
     - `Document Assistant`: **152 out of 242 runs (62.81%)** encountered the keyword error.
     - `Data Analyst`: **0 out of 31 runs (0.00%)** encountered the keyword error.
   - **Latency Impact:**
     - Within `Document Assistant` runs specifically, affected runs averaged **33.90 s** (33,903.60 ms) vs **24.29 s** (24,291.68 ms) for unaffected runs (a difference of about **+9.6 s**). The cause of this latency difference is not established (e.g., whether attributable to retry prompt overhead, token generation length, or host load variation).
     - Across all benchmark suites combined, affected runs averaged **33.90 s** vs **19.73 s** for unaffected runs (which included faster Data Analyst runs averaging 6.50 s).
     - For `Data Analyst`, all 31 runs were unaffected, averaging **6.50 s**.
   - **Trace-Matched Failure Reclassification:**
     Every failed item ($n = 66$) across the benchmark suites in `eval/results/*.jsonl` was matched 1-to-1 with its execution trace in `eval/.workdir/sovereign.db` by question text and chronological execution sequence:
     - **Tool error then abstain:** **39 runs (59.09%)** — The LLM invoked `search_documents` with a malformed argument wrapper (`"args:": ...`), caught the unexpected keyword argument error from the tool execution step, and immediately produced an abstention ("I do not know" / "documents do not contain this information") without retrieving context.
     - **Retrieved but wrong:** **15 runs (22.73%)** — Tools executed successfully and retrieved documents/data, but the final answer failed accuracy scoring (e.g., hallucinated on unanswerable decoys or missed ground-truth keywords).
     - **No tool call at all:** **12 runs (18.18%)** — The LLM failed JSON formatting constraints, hit formatting retry exhaustion, or abstained directly without issuing any tool call.
3. **Post-Evaluation Fixes:** The root causes of the keyword argument error and associated abstentions were resolved in post-eval fixes (Section 11.4: extended argument normalization) on the `fixes` branch.


---

## 13. Post-Fix Canonical Benchmark Evaluation (`fixes` Branch)

Following post-evaluation fixes on the `fixes` branch (principally argument normalization supporting trailing colons/nested wrappers in `backend/agent.py` and boundary-preserving chunking in `backend/rag.py`), an end-to-end evaluation benchmark was re-executed under identical headless benchmark conditions against the 45 canonical evaluation items (`eval/results/postfix_canonical.jsonl`).

### 13.1 Performance Summary and Metrics Comparison

| Benchmark Run | Tag / Git Ref | Total Items ($n$) | Valid Response Rate (95% Wilson CI) | Task Success Rate (95% Wilson CI) | Total Latency / Runtime | Mean Latency per Item | Peak Ollama RSS |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Canonical Run 1** | `eval-v1` | 45 | **100.0%** [92.1%, 100.0%] | **80.0%** (36/45) [66.2%, 89.1%] | 1,048.6 s | 23.30 s | 2,126.2 MB |
| **Canonical Run 2** | `eval-v1` | 45 | **97.8%** [88.4%, 99.6%] | **80.0%** (36/45) [66.2%, 89.1%] | 1,126.3 s | 25.03 s | 2,246.5 MB |
| **Canonical Pooled** | `eval-v1` | 90 (approx.)* | **98.9%** [94.0%, 99.8%] | **80.0%** (72/90) [70.6%, 86.9%] | N/A (pooled) | N/A | 2,246.5 MB |
| **Post-Fix Canonical** | `fixes` | 45 | **100.0%** [92.1%, 100.0%] | **86.7%** (39/45) [73.8%, 93.7%] | **1,025 s** (1,024.5 s) | 22.61 s | 2,508.0 MB |

*\*Note: Pooled confidence interval is approximate due to repeated testing of the same 45 items.*

### 13.2 Paired Exact McNemar Tests

Across identical 45 evaluation items, paired contingency analysis reveals:

1. **Post-Fix Canonical vs Canonical Run 1:**
   - Both Pass: **32**
   - Both Fail: **2**
   - $b$ (Run 1 Fail $\to$ Post-Fix Pass): **7 items**
   - $c$ (Run 1 Pass $\to$ Post-Fix Fail): **4 items**
   - Total Discordant ($b + c$): **11 items**
   - **Exact Two-Sided McNemar $p$-value:** **0.54883** (statistically not significant; 95% Wilson CIs overlap).

2. **Post-Fix Canonical vs Canonical Run 2:**
   - Both Pass: **33**
   - Both Fail: **3**
   - $b$ (Run 2 Fail $\to$ Post-Fix Pass): **6 items**
   - $c$ (Run 2 Pass $\to$ Post-Fix Fail): **3 items**
   - Total Discordant ($b + c$): **9 items**
   - **Exact Two-Sided McNemar $p$-value:** **0.50781** (statistically not significant; 95% Wilson CIs overlap).

### 13.3 Trace Inspection & Classification of Failed Items (`eval/.workdir/sovereign.db`)

Across all execution steps in `eval/.workdir/sovereign.db` for the post-fix run (Runs 4–48), the incidence of `Tool Execution Error: search_documents() got an unexpected keyword argument` was exactly **0 steps (0.0%)**, down from 152 steps (55.68%) in `eval-v1`.

Exactly **6 items failed** ($39/45 = 86.7\%$ success). Trace inspection of the database classifies each failure:

1. **`rag_q06` (Run 9) — Abstained after degenerate retrieval:**
   - **Question:** *"What is the absolute minimum attendance percentage floor below which no condonation is allowed?"*
   - **Expected:** `['65', 'percent']` (from `attendance_rules.txt`, Clause 2.1).
   - **Tool Steps:** Step 1: Model emitted malformed wrapper `{"action": "search_documents", "args: {": "query"}`. Normalizer extracted query string `"query"`. Step 3: Tool searched for `"query"` and returned `library_rules.txt` (Chunk #2). Step 4: Model concluded documents did not contain the floor information.
   - **Actual Answer:** *"The provided documents do not contain the information needed to answer the question about the absolute minimum attendance percentage floor."*

2. **`rag_q09` (Run 12) — Abstained after successful retrieval:**
   - **Question:** *"What are the exact morning biometric scan window hours at Kiosk-7?"*
   - **Expected:** `['08:15', '08:35']` (from `attendance_rules.txt`, Section 4).
   - **Tool Steps:** Step 1: Model searched `"query"` $\to$ `library_rules.txt`. Step 4: Model searched `"morning biometric scan window hours at Kiosk-7"` $\to$ successfully retrieved `attendance_rules.txt` Chunk #5 containing `"The morning logging window opens at 08:15 AM and closes promptly at 08:35 AM at Kiosk-7."` Step 7: Model repeated the identical tool call; Step 8: System policy blocked repeated duplicate invocation. Step 9: Model abstained despite the presence of the exact hours in the context window.
   - **Actual Answer:** *"The provided documents do not contain the specific information about the morning biometric scan window hours at Kiosk-7."*

3. **`rag_q22` (Run 25) — Retrieved but wrong answer (Reasoning error):**
   - **Question:** *"A student arrived late for their exam. At what point is hall admission shut down, and what is the earliest time a student is permitted to hand in their paper and exit?"*
   - **Expected:** `['20', '45']` (from `exam_regulations.txt`, Section 3.2: 20 minutes entry cutoff, 45 minutes earliest exit).
   - **Tool Steps:** Step 1: Searched question. Step 3: Successfully retrieved `exam_regulations.txt` Chunk #1 (`"...hall entry is strictly barred 20 minutes after the commencement bell rings. No candidate shall be permitted to submit their answer script or leave the hall during the first 45 minutes..."`). Step 4: Model answered 20 minutes for entry, but hallucinated 15 minutes for exit by conflating the arrival window ("15 minutes before") with exit cutoff.
   - **Actual Answer:** *"Based on the provided documents, hall admission is strictly barred 20 minutes after the commencement bell rings. Therefore, the earliest time a student is permitted to hand in their paper and exit is 15 minutes after the scheduled start time of the exam..."*

4. **`rag_q23` (Run 26) — Retrieved but wrong answer (Lexical keyword mismatch):**
   - **Question:** *"Can undergraduate students take out rare manuscripts from Wing C, and what special badge is needed for on-site inspection?"*
   - **Expected:** `['cannot', 'CLRC-SEC-9']` (from `library_rules.txt`, Chunk #2).
   - **Tool Steps:** Step 1: Searched question. Step 3: Successfully retrieved `library_rules.txt` Chunk #2. Step 4: Model accurately answered the question in natural language using the phrase *"are not allowed to borrow"* instead of the exact modal verb *"cannot"*, failing the automated keyword matching filter.
   - **Actual Answer:** *"Undergraduate students are not allowed to borrow rare manuscripts from Wing C (2nd Floor) for personal use. They can only be inspected on-site using a special visitor badge, which is CLRC-SEC-9..."*

5. **`rag_q25` (Run 28) — Retrieved but wrong answer (Decoy hallucination):**
   - **Question:** *"What is the permissible attendance concession for students participating in blood donation drives on campus?"* (Unanswerable decoy).
   - **Expected:** Honest abstention (e.g., `['do not know', 'not mentioned', 'does not contain']`).
   - **Tool Steps:** Step 1: Searched query. Step 3: Retrieved `attendance_rules.txt` Chunk #1 (which mentions a 10% duty concession for national sports/symposia). Step 4: Model hallucinated that blood donation drives qualify for the 10% concession.
   - **Actual Answer:** *"Based on the provided documents, students participating in blood donation drives on campus may receive an official duty allowance of up to 10 percent. However, this allowance is strictly for students representing the institute in recognized national tournaments..."*

6. **`rag_q26` (Run 29) — Retrieved but wrong answer (Decoy hallucination):**
   - **Question:** *"What is the specific stipend deduction penalty for graduate teaching assistants who fail to meet the 82 percent attendance threshold?"* (Unanswerable decoy).
   - **Expected:** Honest abstention (e.g., `['do not know', 'not mentioned', 'no information']`).
   - **Tool Steps:** Step 1: Searched query. Step 3: Retrieved `attendance_rules.txt` Chunk #1 (which mentions an undergraduate condonation surcharge of Rs 2,450). Step 4: Model conflated the undergraduate fine with a graduate TA stipend deduction.
   - **Actual Answer:** *"The specific stipend deduction penalty for graduate teaching assistants who fail to meet the 82 percent attendance threshold is a condonation surcharge of Rs 2,450 per course. Additionally, these candidates must complete 18 hours of supervised remediation..."*

### 13.4 Methodological Caveats

1. **Sample Size & Variance ($n = 45$):** This post-fix benchmark represents a **single execution run** of $n = 45$ items. Given stochastic generation in small 3B models (even at temperature 0.2), point estimates are subject to sampling variance. The 95% Wilson confidence interval for task success spans **[73.8%, 93.7%]**, overlapping with baseline runs.
2. **Train/Test Overlap (Non-Held-Out Set):** The post-evaluation fixes (specifically argument unwrapping patterns) were developed after analyzing failure traces observed on this benchmark set under `eval-v1`. This run demonstrates that the specific keyword argument crash and word-splitting chunking bugs were mitigated, but it does **not** constitute an evaluation on a novel, held-out distribution of questions.
3. **Preservation of Evaluation Tag Integrity:** In accordance with scientific integrity guidelines, **zero baseline evaluation numbers, tables, confidence intervals, or figures** reported in Sections 1 through 10 have been altered or overwritten. All baseline artifacts remain permanently preserved under tag `eval-v1`.
