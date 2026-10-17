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
| **`tool_call_valid`** | Format Reliability | Boolean: The first LLM response in the run was valid, schema-correct JSON matching Schema A (`tool`) or Schema B (`final`) before any retry prompt. |
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

| Configuration | Status | $n$ | First-Try Validity | 95% Wilson CI | Task Success (Strict) | 95% Wilson CI | Task Success (Adjudicated) | 95% Wilson CI | Latency Note | Peak Ollama RSS |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `json_on_retry_on` | Completed | 45 | **100.0%** (45/45) | [92.1%, 100.0%] | **80.0%** (36/45) | [66.2%, 89.1%] | **82.2%** (37/45) | [68.7%, 90.7%] | 27.86s* *(pressured)* | 2,351.3 MB |
| `json_on_retry_off` | *not run* | 0 | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A |
| `json_off_retry_on` | *not run* | 0 | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A |
| `json_off_retry_off`| *not run* | 0 | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A |

*\*\*Note on Latency & Memory Conditions:* All latency and RAM numbers were measured at ~0.8 GB free RAM on an 8 GB host with the IDE open; memory-constrained. Note that 40.06s is the post-hoc variant (`REQUIRE_RETRIEVAL_BEFORE_ABSTAIN`), not the canonical configuration. The canonical configuration (27.86s) and post-hoc variant (40.06s) runs are not directly comparable because host memory load was not controlled between the runs. Regarding the 27.86s mean in the canonical run, it is hypothesized (not an empirical finding) that 6 premature 1-turn abstentions without tool calling reduced the average duration, while intermittent OS memory paging during multi-turn items introduced latency stalls. In the post-hoc run, warm-up cold start was 3.967s, mean latency per item was **40.06s** (median 43.09s, std 14.45s), and peak Ollama host RSS was **2,335.4 MB**.

*Reason for unrun configurations:* On an 8 GB laptop with ~0.4 GB available host memory during factorial planning, running the full 4-cell factorial across 3 repeats (540 total inference calls, estimated >6 hours of continuous CPU execution) would induce severe thermal throttling and system instability. `json_on_retry_on` was fully verified with $n=45$ real items. Because zero JSON format errors occurred when JSON mode was ON (first-try validity = 100%, 0 retries required across all 45 items), format errors did not occur with JSON mode enabled.

### 5.4 Experiment 3: Prompt Variant (Hardened vs Baseline)
- **Hardened (Default):** Includes Rules 8 and 9 explicitly forcing immediate invocation of `read_sql` and `search_documents`.
- **Baseline:** Omits Rules 8 and 9.

| Variant | Status | $n$ | First-Try Validity | Task Success (Strict) | Task Success (Adjudicated) | Citation Validity |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Hardened** (Rules 8 & 9) | Completed | 45 | **100.0%** (45/45) | **80.0%** (36/45) | **82.2%** (37/45) | **100.0%** (45/45) |
| **Baseline** (Rules 8 & 9 omitted) | *not run* | 0 | N/A | N/A | N/A | N/A |

*Note:* In `summary.csv`, the redundant duplicate row for `e3_prompt_hardened` has been removed to avoid double-counting the identical configuration from E2.

*Reason for unrun baseline:* Preserved machine health and prioritized full verification of the primary hardened configuration within the execution session.

---

### 5.5 Post-Hoc Architectural Variant: `REQUIRE_RETRIEVAL_BEFORE_ABSTAIN`
*(Clearly labeled POST-HOC architecture variant; reported separately from pre-registered configurations).*

To remedy the dominant failure mode observed in the pre-registered baseline (where the Document Assistant prematurely abstained on answerable questions without issuing a `search_documents` tool call), an architectural interceptor flag `REQUIRE_RETRIEVAL_BEFORE_ABSTAIN` (default `False`) was introduced into `backend/agent.py`. When enabled, if Document Assistant attempts to abstain on its first turn without executing a search, the harness forces one execution of `search_documents(query=...)` before accepting an abstention.

This feature was validated first against `tests/regression_prompts.json` in unit test `tests/test_require_retrieval_before_abstain.py` (passed), and then evaluated over the complete 45-item evaluation benchmark:

| Configuration | Status | $n$ | First-Try Validity | 95% Wilson CI | Task Success (Strict) | 95% Wilson CI | Task Success (Adjudicated) | 95% Wilson CI | Mean Latency | Peak Ollama RSS |
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

#### The 9 Failed Items Clarified
In the pre-registered canonical configuration (`e2_json_on_retry_on.jsonl`, $n=45$), exactly **9 items failed** under strict keyword scoring (36 succeeded, yielding $\frac{36}{45} = 80.0\%$). An earlier draft mentioned 7 failures due to a manual counting oversight; the exact count from the JSONL trace is 9. Every failed item ID and its empirical breakdown is presented below:

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

| Metric | Canonical Pre-Registered (E2) | Post-Hoc Architectural Variant |
| :--- | :--- | :--- |
| **Strict Task Success Rate** | **80.0%** (36/45) [66.2%, 89.1%] | **88.9%** (40/45) [76.5%, 95.2%] |
| **Adjudicated Task Success Rate** | **82.2%** (37/45) [68.7%, 90.7%] | **91.1%** (41/45) [79.3%, 96.5%] |

#### Taxonomy Breakdown Across All 5 Specified Causes:
- **`premature_abstention_without_tool_call`:** **6 items (66.7%)** — Model produced an abstention without searching documents.
- **`wrong_answer_after_retrieval`:** **3 items (33.3%)** — Includes 1 scorer false negative (`rag_q23`), 1 hallucinated decoy (`rag_q27`), and 1 agent argument retry failure (`agent_doc_03`).
- **`wrong_tool`:** **0 items (0.0%)** — Model never selected an inappropriate tool.
- **`invalid_json`:** **0 items (0.0%)** — With JSON mode enabled, schema adherence was 100%.
- **`timeout`:** **0 items (0.0%)** — No item exceeded the inference execution limit.

The categorized failure distribution is visualized in `eval/results/failure_analysis.png`.

---

## 6. System Resource Footprint & Latency Conditions (8 GB Hardware Budget)

### 6.1 Host Memory Pressure Context & Measured Free RAM
All latency and RAM numbers were **measured at ~0.8 GB free RAM on an 8 GB host with the IDE open; memory-constrained** (Windows 11, 7.69 GB usable RAM). Baseline operating system services and typical development processes consume approximately 6.7 GB to 7.1 GB of RAM on this machine, leaving between 0.62 GB and 0.85 GB free at benchmark invocation (requiring `--min-ram 0.1`).

#### Measured Free RAM and Latency Context:
- **Retrieval-Only Benchmarks (E1 & E1b):** Initial available RAM measured **~0.84 GB**. Mean retrieval latency across ChromaDB vector search was **2.34s – 2.37s** (std 0.01s – 0.14s). Peak Ollama generation RSS is recorded as **N/A** in `summary.csv` because no LLM generation process was invoked.
- **Canonical E2 Run (Oct 16):** Initial available RAM measured **~0.65 GB**. Warm-up cold start was **11.667s**, and overall mean latency was **27.86 seconds per item** (median **31.41s**, std **12.90s**).
- **Hypothesis on Canonical Latency (27.86 s):** It is hypothesized (not an empirical finding) that two confounding factors influenced the 27.86s figure:
  1. Six answerable items prematurely returned brief 1-turn abstentions without invoking retrieval tools, which lowered average duration compared to runs where all items executed multi-turn loops.
  2. Conversely, intermittent OS memory paging during multi-turn items under background host load may have introduced periodic latency stalls.
- **Post-Hoc Architectural Variant Run (`posthoc_retrieval_before_abstain`, Oct 17):** Note that **40.06 s is the post-hoc variant, not the canonical configuration**. Initial available RAM was measured at **~0.82 GB**. Warm-up cold start was **3.967s**. Mean latency per item was **40.06 seconds** (median **43.09s**, std **14.45s**, min **12.73s**, max **64.19s**), reflecting the additional second inference turn when premature abstentions were intercepted. Peak Ollama host RSS was **2,335.4 MB (~2.28 GB)**.
- **Comparability Warning:** The canonical (27.86 s) and post-hoc (40.06 s) runs are **not directly comparable** because host memory load was not controlled between the runs (background process activity, initial available RAM, and memory paging varied across test sessions).
- **Real Host Live Acceptance Verification (`scripts/live_check.py 1`):** Measured at start with **~0.85 GB** available RAM; peak Ollama process RAM was **2,232.04 MB** and peak backend process RAM was **167.11 MB**.

#### Detailed Per-Task Latency Breakdown (From Post-Hoc Variant Run, measured at ~0.8 GB free RAM on an 8 GB host with the IDE open; memory-constrained):
- **Pure Vector Search (`nomic-embed-text` on ChromaDB):** **2.34s – 2.37s**
- **Calculator Agent Tasks ($n = 5$):** Mean **16.44s** (median **16.08s**, min **12.73s**, max **19.36s**)
- **SQL Analytical Tasks ($n = 5$):** Mean **24.02s** (median **18.76s**, min **17.58s**, max **46.88s**)
- **Document Assistant Tasks ($n = 5$):** Mean **45.33s** (median **44.11s**, min **36.16s**, max **60.88s**)
- **RAG Policy Questions ($n = 30$):** Mean **45.79s** (median **45.94s**, min **22.34s**, max **64.19s**)

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

1. **Small Sample Size ($n = 45$):**
   The primary benchmark evaluation set contains 45 items (30 RAG questions and 15 agent tasks). While $n = 45$ is rigorous for an on-premise local LLM benchmark on constrained hardware (representing ~30 minutes of continuous CPU inference per run), 95% Wilson confidence intervals span roughly $\pm 8\%$ to $\pm 13\%$ (e.g., [66.2%, 89.1%] for an 80.0% rate). As demonstrated by the paired McNemar test on discordant pairs ($b + c = 8 < 10$, $p = 0.289$), observed point-estimate gains cannot be proven statistically significant at the $\alpha = 0.05$ level without expanding the item pool to $n \ge 100$.

2. **Synthetic Policy Documents:**
   The evaluation corpus comprises 3 core documents (1,500–2,500 chars) and 15 distractor documents crafted with explicit numerical and named institutional rules. Although designed to mimic real university statutes, synthetic documents feature well-structured typography, clear section headings, and explicit parameters. Real-world enterprise and institutional corpora typically feature unstructured layouts, multi-page scanned PDFs, OCR transcription errors, ambiguous footnotes, complex multi-column tables, and contradictory administrative amendments, which present greater vector retrieval noise.

3. **Single Repeat ($r = 1$):**
   Due to the 8 GB host memory budget and CPU inference execution duration (~40 seconds per item; >30 minutes per 45-item run), all benchmark configurations were evaluated across a single full repeat ($r = 1$). A low decoding temperature ($T = 0.2$) was enforced to maximize determinism. Nonetheless, run-to-run stochastic variance in tool generation order and sampling fluctuations across multiple seeds remain unmeasured.

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
