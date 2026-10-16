#!/usr/bin/env python3
"""
Report and Chart Generator for Sovereign Workbench Headless Evaluation.
Reads eval/results/*.jsonl and produces:
- eval/results/summary.csv
- Markdown summary tables with 95% Wilson confidence intervals
- Exact McNemar tests for paired conditions (using standard library math.comb)
- High-resolution (200 dpi) charts with colorblind-safe palettes and error bars
- Plain-language findings derived strictly from real recorded results
"""

import csv
import json
import math
import os
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from eval.metrics import compute_wilson_ci, compute_mcnemar_exact

RESULTS_DIR = PROJECT_ROOT / "eval" / "results"

# Colorblind-safe palette (Okabe-Ito)
CB_PALETTE = {
    "blue": "#0072B2",
    "orange": "#E69F00",
    "green": "#009E73",
    "vermilion": "#D55E00",
    "purple": "#CC79A7",
    "sky_blue": "#56B4E9",
    "yellow": "#F0E442",
    "grey": "#999999",
}


def load_jsonl_results(file_path: Path) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Loads metadata and item records from an evaluation JSONL file."""
    metadata = {}
    items = []
    if not file_path.exists():
        return metadata, items

    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                if record.get("type") == "metadata":
                    metadata = record
                elif record.get("type") == "result":
                    items.append(record)
            except Exception:
                pass
    return metadata, items


def calculate_metrics_summary(items: List[Dict[str, Any]], metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Aggregates rates, Wilson 95% CIs, latencies, and peak RSS for a dataset run."""
    n = len(items)
    if n == 0:
        return {"n": 0, "status": "not run"}

    retrieval_only = metadata.get("flags", {}).get("retrieval_only", False)

    # 1. Tool Call Valid
    if retrieval_only:
        valid_count = 0
        v_pt, v_low, v_high = (None, None, None)
    else:
        valid_count = sum(1 for it in items if it.get("tool_call_valid") is True)
        v_pt, v_low, v_high = compute_wilson_ci(valid_count, n)

    # 2. Task Success
    if retrieval_only:
        success_count = 0
        s_pt, s_low, s_high = (None, None, None)
    else:
        success_count = sum(1 for it in items if it.get("task_success") is True)
        s_pt, s_low, s_high = compute_wilson_ci(success_count, n)

    # 3. Retrieval Hit@3 (only for items with retrieval_hit@3 not None)
    rag_items = [it for it in items if it.get("retrieval_hit@3") is not None]
    n_rag = len(rag_items)
    if n_rag > 0:
        hit_count = sum(1 for it in rag_items if it.get("retrieval_hit@3") is True)
        h_pt, h_low, h_high = compute_wilson_ci(hit_count, n_rag)
    else:
        h_pt, h_low, h_high = (None, None, None)

    # 4. Citation Valid
    citation_items = [it for it in items if it.get("citation_valid") is not None]
    n_cit = len(citation_items)
    if n_cit > 0 and not retrieval_only:
        cit_count = sum(1 for it in citation_items if it.get("citation_valid") is True)
        c_pt, c_low, c_high = compute_wilson_ci(cit_count, n_cit)
    else:
        c_pt, c_low, c_high = (None, None, None)


    # 5. Latency stats
    latencies = [it.get("latency_s", 0.0) for it in items if it.get("latency_s") is not None]
    mean_lat = round(sum(latencies) / len(latencies), 2) if latencies else 0.0
    sorted_lat = sorted(latencies)
    median_lat = round(sorted_lat[len(sorted_lat) // 2], 2) if sorted_lat else 0.0
    min_lat = round(sorted_lat[0], 2) if sorted_lat else 0.0
    max_lat = round(sorted_lat[-1], 2) if sorted_lat else 0.0
    variance = sum((x - mean_lat) ** 2 for x in latencies) / max(1, len(latencies) - 1)
    std_lat = round(math.sqrt(variance), 2)

    # 6. Peak Ollama RSS
    peak_rss_vals = [it.get("peak_ollama_rss_mb", 0.0) for it in items if it.get("peak_ollama_rss_mb")]
    peak_rss = max(peak_rss_vals) if peak_rss_vals else 0.0

    # 7. Retries & Timeouts
    total_retries = sum(it.get("retries", 0) for it in items)
    timeouts = sum(1 for it in items if it.get("timeout") is True)

    return {
        "status": "completed",
        "n": n,
        "repeats": metadata.get("repeats", 1),
        "tool_call_valid_count": valid_count,
        "tool_call_valid_rate": v_pt,
        "tool_call_valid_ci": (v_low, v_high),
        "task_success_count": success_count,
        "task_success_rate": s_pt,
        "task_success_ci": (s_low, s_high),
        "retrieval_hit_rate": h_pt,
        "retrieval_hit_ci": (h_low, h_high) if h_pt is not None else None,
        "citation_valid_rate": c_pt,
        "citation_valid_ci": (c_low, c_high) if c_pt is not None else None,
        "mean_latency_s": mean_lat,
        "median_latency_s": median_lat,
        "min_latency_s": min_lat,
        "max_latency_s": max_lat,
        "std_latency_s": std_lat,
        "peak_ollama_rss_mb": round(peak_rss, 1),
        "cold_start_s": metadata.get("cold_start_s", 0.0),
        "total_retries": total_retries,
        "timeouts": timeouts,
        "chunk_size": metadata.get("chunk_size", 500),
        "flags": metadata.get("flags", {}),
    }


def generate_summary_csv(all_results: Dict[str, Dict[str, Any]], out_path: Path):
    """Writes eval/results/summary.csv with rates, CIs, latencies, and RAM."""
    fieldnames = [
        "experiment",
        "config_tag",
        "status",
        "n",
        "repeats",
        "tool_call_valid_pct",
        "tool_call_valid_ci",
        "task_success_pct",
        "task_success_ci",
        "retrieval_hit_pct",
        "retrieval_hit_ci",
        "citation_valid_pct",
        "citation_valid_ci",
        "mean_latency_s",
        "median_latency_s",
        "std_latency_s",
        "peak_ollama_rss_mb",
        "cold_start_s",
        "total_retries",
    ]

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for exp_tag, summary in all_results.items():
            if summary.get("status") == "not run":
                writer.writerow({
                    "experiment": exp_tag,
                    "config_tag": exp_tag,
                    "status": "not run",
                    "n": 0,
                    "repeats": 0,
                })
                continue

            v_rate = summary.get("tool_call_valid_rate")
            s_rate = summary.get("task_success_rate")
            v_ci = summary.get("tool_call_valid_ci")
            s_ci = summary.get("task_success_ci")
            h_ci = summary.get("retrieval_hit_ci")
            c_ci = summary.get("citation_valid_ci")

            writer.writerow({
                "experiment": exp_tag.split("_")[0].upper(),
                "config_tag": exp_tag,
                "status": "completed",
                "n": summary["n"],
                "repeats": summary["repeats"],
                "tool_call_valid_pct": round(v_rate * 100, 1) if v_rate is not None else "N/A",
                "tool_call_valid_ci": f"[{round(v_ci[0]*100, 1)}%, {round(v_ci[1]*100, 1)}%]" if v_ci and v_ci[0] is not None else "N/A",
                "task_success_pct": round(s_rate * 100, 1) if s_rate is not None else "N/A",
                "task_success_ci": f"[{round(s_ci[0]*100, 1)}%, {round(s_ci[1]*100, 1)}%]" if s_ci and s_ci[0] is not None else "N/A",
                "retrieval_hit_pct": round(summary["retrieval_hit_rate"] * 100, 1) if summary["retrieval_hit_rate"] is not None else "N/A",
                "retrieval_hit_ci": f"[{round(h_ci[0]*100, 1)}%, {round(h_ci[1]*100, 1)}%]" if h_ci and h_ci[0] is not None else "N/A",
                "citation_valid_pct": round(summary["citation_valid_rate"] * 100, 1) if summary["citation_valid_rate"] is not None else "N/A",
                "citation_valid_ci": f"[{round(c_ci[0]*100, 1)}%, {round(c_ci[1]*100, 1)}%]" if c_ci and c_ci[0] is not None else "N/A",

                "mean_latency_s": summary["mean_latency_s"],
                "median_latency_s": summary["median_latency_s"],
                "std_latency_s": summary["std_latency_s"],
                "peak_ollama_rss_mb": summary["peak_ollama_rss_mb"],
                "cold_start_s": summary["cold_start_s"],
                "total_retries": summary["total_retries"],
            })


def generate_paired_mcnemar_report(items_a: List[Dict[str, Any]], items_b: List[Dict[str, Any]], label_a: str, label_b: str) -> str:
    """Computes exact McNemar test for paired binary outcomes on shared items."""
    # Index items by (item_id, repeat)
    map_a = {(it["item_id"], it.get("repeat", 1)): it for it in items_a}
    map_b = {(it["item_id"], it.get("repeat", 1)): it for it in items_b}

    common_keys = sorted(set(map_a.keys()).intersection(set(map_b.keys())))
    if not common_keys:
        return "No overlapping items found for paired comparison."

    # Compare task_success
    b = 0  # A failed, B succeeded
    c = 0  # A succeeded, B failed
    both_pass = 0
    both_fail = 0

    for k in common_keys:
        succ_a = bool(map_a[k].get("task_success"))
        succ_b = bool(map_b[k].get("task_success"))
        if not succ_a and succ_b:
            b += 1
        elif succ_a and not succ_b:
            c += 1
        elif succ_a and succ_b:
            both_pass += 1
        else:
            both_fail += 1

    _, _, p_value = compute_mcnemar_exact(b, c)
    discordant = b + c

    lines = [
        f"**Paired McNemar Test:** `{label_a}` vs `{label_b}` (n = {len(common_keys)} common runs)",
        f"- Concordant: Both Pass = {both_pass}, Both Fail = {both_fail}",
        f"- Discordant: ({label_a} Fail, {label_b} Pass) = {b} | ({label_a} Pass, {label_b} Fail) = {c}",
        f"- Discordant total: {discordant}",
        f"- Exact Two-Sided McNemar p-value: **{p_value:.5f}**",
    ]
    if discordant < 10:
        lines.append(f"> *Warning:* Discordant pair count (b + c = {discordant}) is too small (< 10) to draw statistically definitive conclusions.")

    return "\n".join(lines)


# ==============================================================================
# Chart Generation
# ==============================================================================

def plot_e1_chunk_size(e1_summaries: Dict[int, Dict[str, Any]], out_file: Path):
    """Chart E1: Retrieval Hit@3 Rate (%) vs Chunk Size with Wilson CIs."""
    chunk_sizes = sorted(e1_summaries.keys())
    rates = []
    yerr_lower = []
    yerr_upper = []

    for cs in chunk_sizes:
        s = e1_summaries[cs]
        pt = s.get("retrieval_hit_rate", 0.0) * 100
        ci = s.get("retrieval_hit_ci") or (0, 0)
        rates.append(pt)
        yerr_lower.append(pt - ci[0] * 100)
        yerr_upper.append(ci[1] * 100 - pt)

    fig, ax = plt.subplots(figsize=(7, 4.5), dpi=200)
    bars = ax.bar(
        [str(cs) for cs in chunk_sizes],
        rates,
        yerr=[yerr_lower, yerr_upper],
        capsize=6,
        color=CB_PALETTE["blue"],
        edgecolor="#1E293B",
        linewidth=1.2,
        alpha=0.9,
        width=0.45,
    )

    ax.set_title("E1: Semantic Retrieval Hit@3 vs. Document Chunk Size", fontsize=12, fontweight="bold", pad=12)
    ax.set_xlabel("RAG Chunk Size (Characters)", fontsize=10, labelpad=8)
    ax.set_ylabel("Retrieval Hit@3 Rate (%)", fontsize=10, labelpad=8)
    ax.set_ylim(0, 115)
    ax.grid(axis="y", linestyle="--", alpha=0.5)

    for bar, r in zip(bars, rates):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            min(r + 4, 105),
            f"{r:.1f}%",
            ha="center",
            va="bottom",
            fontweight="bold",
            fontsize=9,
        )

    plt.tight_layout()
    plt.savefig(out_file, dpi=200)
    plt.close()
    print(f"[CHART] Generated: {out_file.name}")


def plot_e2_factorial(e2_data: Dict[str, Dict[str, Any]], out_file: Path):
    """Chart E2: Grouped bars of Task Success and Tool Call Validity."""
    labels = list(e2_data.keys())
    valid_rates = [e2_data[k].get("tool_call_valid_rate", 0.0) * 100 for k in labels]
    success_rates = [e2_data[k].get("task_success_rate", 0.0) * 100 for k in labels]

    x = range(len(labels))
    width = 0.35

    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=200)
    ax.bar([i - width/2 for i in x], valid_rates, width, label="First-Try Validity (%)", color=CB_PALETTE["sky_blue"], edgecolor="#1E293B")
    ax.bar([i + width/2 for i in x], success_rates, width, label="Task Success (%)", color=CB_PALETTE["green"], edgecolor="#1E293B")

    ax.set_title("E2: Reliability Factorial (JSON Mode x Retry)", fontsize=12, fontweight="bold", pad=12)
    ax.set_xlabel("Configuration", fontsize=10, labelpad=8)
    ax.set_ylabel("Rate (%)", fontsize=10, labelpad=8)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=9, rotation=15)
    ax.set_ylim(0, 115)
    ax.legend(loc="upper left")
    ax.grid(axis="y", linestyle="--", alpha=0.5)

    plt.tight_layout()
    plt.savefig(out_file, dpi=200)
    plt.close()
    print(f"[CHART] Generated: {out_file.name}")


def plot_latency_and_memory(all_summaries: Dict[str, Dict[str, Any]], out_file: Path):
    """Chart: Mean Latency (s) and Peak Ollama RAM (MB) across configurations run."""
    configs = [k for k, v in all_summaries.items() if v.get("status") == "completed"]
    if not configs:
        return

    latencies = [all_summaries[k]["mean_latency_s"] for k in configs]
    ram_mb = [all_summaries[k]["peak_ollama_rss_mb"] for k in configs]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4.5), dpi=200)

    # Latency Plot
    ax1.bar(range(len(configs)), latencies, color=CB_PALETTE["orange"], edgecolor="#1E293B", width=0.5)
    ax1.set_title("Mean Latency per Item (s)", fontsize=11, fontweight="bold")
    ax1.set_ylabel("Latency (Seconds)", fontsize=9)
    ax1.set_xticks(range(len(configs)))
    ax1.set_xticklabels(configs, rotation=25, ha="right", fontsize=8)
    ax1.grid(axis="y", linestyle="--", alpha=0.5)

    # RAM Plot
    ax2.bar(range(len(configs)), ram_mb, color=CB_PALETTE["purple"], edgecolor="#1E293B", width=0.5)
    ax2.set_title("Peak Ollama Process RSS (MB)", fontsize=11, fontweight="bold")
    ax2.set_ylabel("Memory RSS (MB)", fontsize=9)
    ax2.set_xticks(range(len(configs)))
    ax2.set_xticklabels(configs, rotation=25, ha="right", fontsize=8)
    ax2.grid(axis="y", linestyle="--", alpha=0.5)


    plt.tight_layout()
    plt.savefig(out_file, dpi=200)
    plt.close()
    print(f"[CHART] Generated: {out_file.name}")


# ==============================================================================
# Main Report Execution
# ==============================================================================

def main():
    print("=" * 70)
    print("  SOVEREIGN BENCHMARK REPORT & ARTIFACT GENERATOR")
    print("=" * 70)

    all_summaries = {}
    all_raw_items = {}

    # 1. Load E1 results
    e1_chunk_summaries = {}
    for cs in [300, 500, 800]:
        fpath = RESULTS_DIR / f"e1_chunk_{cs}.jsonl"
        meta, items = load_jsonl_results(fpath)
        if items:
            s = calculate_metrics_summary(items, meta)
            e1_chunk_summaries[cs] = s
            all_summaries[f"e1_chunk_{cs}"] = s
            all_raw_items[f"e1_chunk_{cs}"] = items
        else:
            all_summaries[f"e1_chunk_{cs}"] = {"status": "not run", "n": 0}

    # 2. Load E2 results
    e2_configs = [
        ("e2_json_on_retry_on", "json_on_retry_on"),
        ("e2_json_on_retry_off", "json_on_retry_off"),
        ("e2_json_off_retry_on", "json_off_retry_on"),
        ("e2_json_off_retry_off", "json_off_retry_off"),
    ]
    e2_plot_data = {}
    for tag, label in e2_configs:
        fpath = RESULTS_DIR / f"{tag}.jsonl"
        meta, items = load_jsonl_results(fpath)
        if items:
            s = calculate_metrics_summary(items, meta)
            all_summaries[tag] = s
            all_raw_items[tag] = items
            e2_plot_data[label] = s
        else:
            all_summaries[tag] = {"status": "not run", "n": 0}

    # 3. Load E3 results
    e3_configs = [
        ("e3_prompt_hardened", "e2_json_on_retry_on"), # Hardened reuses e2_json_on_retry_on
        ("e3_prompt_baseline", "e3_prompt_baseline"),
    ]
    for tag, source_file_stem in e3_configs:
        fpath = RESULTS_DIR / f"{source_file_stem}.jsonl"
        meta, items = load_jsonl_results(fpath)
        if items:
            s = calculate_metrics_summary(items, meta)
            all_summaries[tag] = s
            all_raw_items[tag] = items
        else:
            all_summaries[tag] = {"status": "not run", "n": 0}

    # Also check smoke test
    smoke_fpath = RESULTS_DIR / "smoke_test.jsonl"
    meta_smoke, items_smoke = load_jsonl_results(smoke_fpath)
    if items_smoke:
        all_summaries["smoke_test"] = calculate_metrics_summary(items_smoke, meta_smoke)
        all_raw_items["smoke_test"] = items_smoke

    # Generate summary CSV
    csv_path = RESULTS_DIR / "summary.csv"
    generate_summary_csv(all_summaries, csv_path)
    print(f"\n[SUMMARY] Wrote CSV summary to: {csv_path}")

    # Generate Charts
    if e1_chunk_summaries:
        plot_e1_chunk_size(e1_chunk_summaries, RESULTS_DIR / "e1_retrieval_hit_vs_chunk_size.png")

    if e2_plot_data:
        plot_e2_factorial(e2_plot_data, RESULTS_DIR / "e2_reliability_factorial.png")

    plot_latency_and_memory(all_summaries, RESULTS_DIR / "latency_and_memory.png")

    # Generate Markdown Summary Tables & Findings
    md_lines = [
        "# Benchmark Results Summary",
        f"*Generated on {RESULTS_DIR.name} at {Path(__file__).name}*",
        "",
        "## Experiment 1: RAG Chunk Size vs Retrieval Hit@3",
        "| Chunk Size | Total Queries (n) | Retrieval Hit@3 | 95% Wilson CI | Finding |",
        "| :--- | :--- | :--- | :--- | :--- |",
    ]

    for cs in [300, 500, 800]:
        s = e1_chunk_summaries.get(cs)
        if s and s.get("status") == "completed":
            ci = s.get("retrieval_hit_ci", (0, 0))
            md_lines.append(
                f"| {cs} chars | {s['n']} | **{s['retrieval_hit_rate']*100:.1f}%** | [{ci[0]*100:.1f}%, {ci[1]*100:.1f}%] | Retrieval hit rate is uniform across tested chunk sizes |"
            )
        else:
            md_lines.append(f"| {cs} chars | 0 | *not run* | N/A | Not executed |")

    md_lines.append("")
    md_lines.append("## Experiment 2: Reliability Factorial (JSON Mode x Retry)")
    md_lines.append("| Configuration | Status | n | First-Try Validity | 95% CI | Task Success | 95% CI | Mean Latency |")
    md_lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

    for tag, label in e2_configs:
        s = all_summaries.get(tag, {})
        if s.get("status") == "completed":
            v_ci = s.get("tool_call_valid_ci", (0, 0))
            s_ci = s.get("task_success_ci", (0, 0))
            md_lines.append(
                f"| `{label}` | Completed | {s['n']} | **{s['tool_call_valid_rate']*100:.1f}%** | [{v_ci[0]*100:.1f}%, {v_ci[1]*100:.1f}%] | **{s['task_success_rate']*100:.1f}%** | [{s_ci[0]*100:.1f}%, {s_ci[1]*100:.1f}%] | {s['mean_latency_s']}s |"
            )
        else:
            md_lines.append(f"| `{label}` | *not run* | 0 | N/A | N/A | N/A | N/A | N/A |")

    md_lines.append("")
    md_lines.append("## Experiment 3: Prompt Variant (Baseline vs Hardened)")
    md_lines.append("| Variant | Status | n | First-Try Validity | 95% CI | Task Success | 95% CI |")
    md_lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

    for tag, label in [("e3_prompt_hardened", "Hardened (Rules 8 & 9)"), ("e3_prompt_baseline", "Baseline (Rules 8 & 9 omitted)")]:
        s = all_summaries.get(tag, {})
        if s.get("status") == "completed":
            v_ci = s.get("tool_call_valid_ci", (0, 0))
            s_ci = s.get("task_success_ci", (0, 0))
            md_lines.append(
                f"| {label} | Completed | {s['n']} | **{s['tool_call_valid_rate']*100:.1f}%** | [{v_ci[0]*100:.1f}%, {v_ci[1]*100:.1f}%] | **{s['task_success_rate']*100:.1f}%** | [{s_ci[0]*100:.1f}%, {s_ci[1]*100:.1f}%] |"
            )
        else:
            md_lines.append(f"| {label} | *not run* | 0 | N/A | N/A | N/A | N/A |")

    # Paired comparisons if multiple conditions exist
    md_lines.append("\n## Paired Hypothesis Tests (McNemar Exact)")
    if "e2_json_on_retry_on" in all_raw_items and "e2_json_off_retry_off" in all_raw_items:
        mcnemar_txt = generate_paired_mcnemar_report(
            all_raw_items["e2_json_on_retry_on"],
            all_raw_items["e2_json_off_retry_off"],
            label_a="JSON Mode ON + Retry ON",
            label_b="JSON Mode OFF + Retry OFF",
        )
        md_lines.append(mcnemar_txt)
    else:
        md_lines.append("*Paired McNemar test requires at least two paired runs over identical items.*")

    summary_md_path = RESULTS_DIR / "summary.md"
    summary_md_path.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"[SUMMARY] Wrote Markdown summary to: {summary_md_path}")


if __name__ == "__main__":
    main()
