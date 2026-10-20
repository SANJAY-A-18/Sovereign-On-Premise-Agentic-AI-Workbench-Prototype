import sqlite3
import glob
import json
import os
from pathlib import Path

print("=================================================================")
print("INVESTIGATION: 'unexpected keyword argument' IN EVAL & TRACES")
print("=================================================================")

# 1. Search in eval/results/*.jsonl
jsonl_files = sorted(glob.glob("eval/results/*.jsonl"))
print(f"\n1. Scan of eval/results/*.jsonl ({len(jsonl_files)} files):")
eval_matches = {}
for jf in jsonl_files:
    fname = os.path.basename(jf)
    count = 0
    items = []
    with open(jf, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            if "unexpected keyword argument" in line:
                count += 1
                try:
                    obj = json.loads(line)
                    item_id = obj.get("item_id", f"line_{line_num}")
                except Exception:
                    item_id = f"line_{line_num}"
                items.append(item_id)
    if count > 0:
        eval_matches[fname] = items
        print(f"   {fname}: {count} occurrences (items: {items})")
    else:
        print(f"   {fname}: 0 occurrences")

if not eval_matches:
    print("   SUMMARY FOR EVAL RESULTS: Zero (0) occurrences across all benchmark JSONL runs.")

# 2. Search in SQLite Databases
dbs = ["data/sovereign.db", "data_backup/sovereign.db", "eval/.workdir/sovereign.db"]
print("\n2. Scan of SQLite Database Step Traces:")
for db_path in dbs:
    p = Path(db_path)
    if not p.exists():
        print(f"   {db_path}: [File Not Found]")
        continue
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(DISTINCT run_id), COUNT(*) FROM steps WHERE output_data LIKE '%unexpected keyword argument%'")
        run_count, step_count = cur.fetchone()
        print(f"   {db_path}: {step_count} step occurrences across {run_count} distinct runs.")

        # Also get list of runs and questions
        cur.execute("""
            SELECT s.run_id, r.question, s.step_number, s.input_data, s.output_data
            FROM steps s JOIN runs r ON s.run_id = r.id
            WHERE s.output_data LIKE '%unexpected keyword argument%'
            ORDER BY s.run_id, s.step_number
        """)
        rows = cur.fetchall()
        for r in rows:
            print(f"      Run #{r[0]} | Step #{r[2]} | Question: '{r[1][:50]}...'")
            print(f"         Tool Input: {r[3]}")
            print(f"         Tool Error: {r[4]}")
    except Exception as e:
        print(f"   {db_path}: Error querying DB: {e}")

print("=================================================================")
