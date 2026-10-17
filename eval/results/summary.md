# Benchmark Results Summary
*Generated on results at report.py*

## Experiment 1: RAG Chunk Size vs Document Retrieval Hit@3 (3 Core Docs)
| Chunk Size | Total Queries (n) | Document Hit@3 | 95% Wilson CI | Finding |
| :--- | :--- | :--- | :--- | :--- |
| 300 chars | 30 | **100.0%** | [88.6%, 100.0%] | Uniform 100% document-level hit on 3 core synthetic documents |
| 500 chars | 30 | **100.0%** | [88.6%, 100.0%] | Uniform 100% document-level hit on 3 core synthetic documents |
| 800 chars | 30 | **100.0%** | [88.6%, 100.0%] | Uniform 100% document-level hit on 3 core synthetic documents |

## Experiment 1b: Distractor Corpus & Chunk-Level Retrieval Accuracy (18 Documents)
| Chunk Size | Corpus Docs | Answerable Queries | Chunk Hit@1 | 95% Wilson CI | Chunk Hit@3 | 95% Wilson CI | MRR | Finding |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 300 chars | 18 | 24 | **75.0%** | [55.1%, 88.0%] | **87.5%** | [69.0%, 95.7%] | **0.8056** | Multi-sentence clauses split across boundaries; CIs overlap at n=24 |
| 500 chars | 18 | 24 | **75.0%** | [55.1%, 88.0%] | **91.7%** | [74.2%, 97.7%] | **0.8333** | Multi-sentence clauses split across boundaries; CIs overlap at n=24 |
| 800 chars | 18 | 24 | **83.3%** | [64.1%, 93.3%] | **95.8%** | [79.8%, 99.3%] | **0.8889** | Highest point estimate; 95% CIs overlap across sizes at n=24 (no superiority claim) |

## Experiment 2: Reliability Factorial (JSON Mode x Retry)
| Configuration | Status | n | First-Try Validity | 95% CI | Task Success | 95% CI | Mean Latency |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `json_on_retry_on` | Completed | 45 | **100.0%** | [92.1%, 100.0%] | **80.0%** | [66.2%, 89.1%] | 27.86s* |
| `json_on_retry_off` | *not run* | 0 | N/A | N/A | N/A | N/A | N/A |
| `json_off_retry_on` | *not run* | 0 | N/A | N/A | N/A | N/A | N/A |
| `json_off_retry_off` | *not run* | 0 | N/A | N/A | N/A | N/A | N/A |

*Note on Latency & Memory Conditions:* All latency and RAM numbers were measured at ~0.8 GB free RAM on an 8 GB host with the IDE open; memory-constrained. Note that 40.06s is the post-hoc variant (`REQUIRE_RETRIEVAL_BEFORE_ABSTAIN`), not the canonical configuration. The canonical configuration (27.86s) and post-hoc variant runs are not directly comparable because host memory load was not controlled. Regarding the canonical 27.86s mean, it is hypothesized (not an empirical finding) that 6 premature 1-turn abstentions without tool calling lowered the average duration, while intermittent OS memory paging during multi-turn items introduced latency stalls. In the post-hoc run, warm-up cold start was 3.967s, mean latency was 40.06s (median 43.09s, std 14.45s), and peak Ollama host RSS was 2,335.4 MB.

## Experiment 3: Prompt Variant (Baseline vs Hardened)
| Variant | Status | n | First-Try Validity | 95% CI | Task Success | 95% CI |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Hardened (Rules 8 & 9) | Completed | 45 | **100.0%** | [92.1%, 100.0%] | **80.0%** | [66.2%, 89.1%] |
| Baseline (Rules 8 & 9 omitted) | *not run* | 0 | N/A | N/A | N/A | N/A |

## Post-Hoc Architectural Variant: REQUIRE_RETRIEVAL_BEFORE_ABSTAIN
*Evaluated as a post-hoc intervention forcing one retrieval before accepting Document Assistant abstentions.*
| Configuration | Status | n | First-Try Validity | 95% CI | Task Success (Strict) | 95% CI | Task Success (Adjudicated) | 95% CI | Mean Latency | Peak Ollama RSS |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `POST-HOC: require_retrieval_before_abstain` | Completed | 45 | **100.0%** | [92.1%, 100.0%] | **88.9%** | [76.5%, 95.2%] | **91.1%** | [79.3%, 96.5%] | 40.06s* | 2335.4 MB |

### Post-Hoc Regressions and Validation Scope
- **Regressions (b=6 gained, c=2 lost):**
  1. `rag_q03`: In the canonical run, the recorded 'pass' was a scorer false positive (the answer contained the name 'Radhakrishnan' while stating the documents did not specify the officer). In post-hoc, the model reached the same negative conclusion without naming the officer, failing the keyword match.
  2. `rag_q21`: In post-hoc, the model relied on generic university priors ('Medical Absence Form', 'Academic Office') instead of conditioning strictly on retrieved text mentioning Form MED-401 and Clause 2.1.
- **Validation Scope:** Validation of this post-hoc intervention was strictly a unit test (`tests/test_require_retrieval_before_abstain.py`) plus the 45-item evaluation benchmark, not a broad multi-domain regression run.

### Paired McNemar Test: Pre-registered Canonical vs Post-Hoc Variant
**Paired McNemar Test:** `Pre-registered Canonical (json_on_retry_on)` vs `Post-Hoc (require_retrieval_before_abstain)` (n = 45 common runs)
- Concordant: Both Pass = 34, Both Fail = 3
- Discordant: (Pre-registered Canonical (json_on_retry_on) Fail, Post-Hoc (require_retrieval_before_abstain) Pass) = 6 | (Pre-registered Canonical (json_on_retry_on) Pass, Post-Hoc (require_retrieval_before_abstain) Fail) = 2
- Discordant total: 8
- Exact Two-Sided McNemar p-value: **0.28906**
> *Note on Sample Size:* Discordant pair count (b + c = 8) is too small (< 10) to draw statistically definitive conclusions.

## Failure Analysis Breakdown (Canonical Pre-registered Run)
Total failed items: **9 / 45**
- **Strict Task Success Rate:** **80.0%** (36/45) [66.2%, 89.1%]
- **Adjudicated Task Success Rate:** **82.2%** (37/45) [68.7%, 90.7%] *(Crediting `rag_q23` scorer false negative)*

### Scorer False Negative Report: `rag_q23`
- **Question:** *Can undergraduate students take out rare manuscripts from Wing C, and what special badge is needed for on-site inspection?*
- **Expected Keywords:** `['cannot', 'CLRC-SEC-9']` (match: all)
- **Model Answer:** *"Undergraduate students are not allowed to take out rare manuscripts from Wing C. A special badge named CLRC-SEC-9 is needed for on-site inspection of these rare manuscripts."*
- **Adjudication:** The model's answer is factually and semantically correct. It failed the automated keyword matcher solely because the phrasing 'are not allowed to' did not match the literal substring 'cannot'.

| Item ID | Suite | Question | Expected Keyword / Ground Truth | Model Answer | Failure Cause |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `rag_q08` | rag | How many hours of supervised library study remediation are m... | `['18', 'hours']` | The provided documents do not contain this information.... | **Premature Abstention Without Tool Call** |
| `rag_q13` | rag | What is the minimum passing percentage required specifically... | `['42', 'percent']` | The provided documents do not contain this information.... | **Premature Abstention Without Tool Call** |
| `rag_q14` | rag | What is the registration fee per theoretical credit for sitt... | `['1,150', '1150']` | I do not know.... | **Premature Abstention Without Tool Call** |
| `rag_q19` | rag | What is the daily overdue fine rate per volume starting from... | `['40']` | The provided documents do not contain this information.... | **Premature Abstention Without Tool Call** |
| `rag_q20` | rag | What is the daily session cap in minutes for users on Cyber ... | `['90', 'minutes']` | The provided documents do not contain this information.... | **Premature Abstention Without Tool Call** |
| `rag_q22` | rag | A student arrived late for their exam. At what point is hall... | `['20', '45']` | The provided documents do not contain this information.... | **Premature Abstention Without Tool Call** |
| `rag_q23` | rag | Can undergraduate students take out rare manuscripts from Wi... | `['cannot', 'CLRC-SEC-9']` | Undergraduate students are not allowed to take out rare manuscripts fr... | **Scorer False Negative (Wrong Answer After Retrieval)** |
| `rag_q27` | rag | What is the passing score percentage required for foreign la... | `['do not know', 'not mentioned', 'no information', 'does not contain', 'cannot find', 'not provided']` | According to the regulations provided in the documents, the passing sc... | **Wrong Answer After Retrieval** |
| `agent_doc_03` | agent | Under the library charter, what is the infraction penalty fe... | `['3,200', '3200']` | The provided documents do not contain this information.... | **Wrong Answer After Retrieval** |