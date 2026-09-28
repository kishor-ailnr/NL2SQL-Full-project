"""
scripts/run_scenario_matrix.py
------------------------------
Runner that executes the 127-scenario matrix twice with query cache bypassed,
respects rate limits (clears rate limits between runs, paces requests),
and compiles a comprehensive PASS/FAIL/FLAKY breakdown report across all 14 categories.
"""

import sys
import time
from collections import defaultdict
from pathlib import Path

# Add project root to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from starlette.testclient import TestClient
from app.main import app
from tests.test_scenario_matrix import SCENARIOS, Scenario, classify_outcome, execute_scenario


import argparse


def run_full_matrix(target_category: str = None, num_runs: int = 2):
    scenarios_to_run = SCENARIOS
    if target_category:
        scenarios_to_run = [s for s in SCENARIOS if target_category.lower() in s.category.lower() or target_category.lower() in s.id.lower()]
    print(f"Starting execution of {len(scenarios_to_run)} scenarios ({num_runs} RUNS, CACHE BYPASSED)...")
    
    with TestClient(app) as client:
        # 1. Initialize sessions
        r_h = client.post("/api/connect-db", json={"db_type": "demo", "demo_name": "hospital"})
        hosp_sid = r_h.json()["session_id"]

        r_e = client.post("/api/connect-db", json={"db_type": "demo", "demo_name": "ecommerce"})
        ecom_sid = r_e.json()["session_id"]

        # Custom DB setup
        import tempfile, sqlite3
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            custom_path = f.name
        conn = sqlite3.connect(custom_path)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE inventory_items (
                id INTEGER PRIMARY KEY,
                item_name TEXT,
                category TEXT,
                quantity INTEGER,
                unit_price REAL,
                supplier TEXT
            );
        """)
        cur.executemany("""
            INSERT INTO inventory_items (id, item_name, category, quantity, unit_price, supplier)
            VALUES (?, ?, ?, ?, ?, ?);
        """, [
            (1, "Laptop", "Electronics", 5, 999.99, "TechCorp"),
            (2, "Mouse", "Electronics", 50, 19.99, "TechCorp"),
            (3, "Desk Chair", "Furniture", 8, 149.50, "OfficeSupply"),
            (4, "Notebook", "Stationery", 120, 2.50, "PaperCo"),
            (5, "Monitor", "Electronics", 0, 199.99, "TechCorp"),
        ])
        conn.commit()
        conn.close()

        sqlite_uri = f"sqlite:///{Path(custom_path).as_posix()}"
        r_c = client.post("/api/connect-db", json={"db_type": "sqlite", "connection_string": sqlite_uri})
        cust_sid = r_c.json()["session_id"]

        sessions = {
            "hospital": hosp_sid,
            "ecommerce": ecom_sid,
            "custom": cust_sid,
        }

        # Track results: scenario_id -> [run1_pass, run2_pass, run1_info, run2_info]
        scenario_results = {}

        for run_idx in range(1, num_runs + 1):
            print(f"\n==========================================", flush=True)
            print(f"=== RUN {run_idx} / {num_runs} (Cache Bypassed) ===", flush=True)
            print(f"==========================================", flush=True)
            
            for idx, sc in enumerate(scenarios_to_run, 1):
                sid = sessions.get(sc.db, hosp_sid)
                time.sleep(1.0)  # Pacing to stay within Gemini 15 RPM free tier quota
                t0 = time.time()
                try:
                    res = execute_scenario(client, sc, sid, bypass_cache=True)
                    actual_outcome = res["outcome"]
                    data = res["data"]
                    expected = sc.follow_up_expected_outcome if sc.follow_up else sc.expected_outcome

                    is_pass = (actual_outcome == expected)
                    failure_reasons = []

                    if not is_pass:
                        failure_reasons.append(f"Outcome mismatch: expected '{expected}', got '{actual_outcome}'")

                    sql = data.get("sql") or ""
                    if sc.sql_must_contain:
                        for s in sc.sql_must_contain:
                            if s.lower() not in sql.lower():
                                is_pass = False
                                failure_reasons.append(f"SQL missing '{s}'")

                    if sc.sql_must_not_contain:
                        for s in sc.sql_must_not_contain:
                            if s.lower() in sql.lower():
                                is_pass = False
                                failure_reasons.append(f"SQL has forbidden '{s}'")

                    if actual_outcome == "rows":
                        rows = data.get("result", [])
                        if sc.min_rows and len(rows) < sc.min_rows:
                            is_pass = False
                            failure_reasons.append(f"Row count {len(rows)} < min {sc.min_rows}")
                        if sc.max_rows is not None and len(rows) > sc.max_rows:
                            is_pass = False
                            failure_reasons.append(f"Row count {len(rows)} > max {sc.max_rows}")

                    dur = time.time() - t0
                    info = {
                        "pass": is_pass,
                        "outcome": actual_outcome,
                        "expected": expected,
                        "duration": dur,
                        "failures": failure_reasons,
                        "sql": sql,
                        "explanation": data.get("explanation"),
                    }
                    status_str = "PASS" if is_pass else f"FAIL ({', '.join(failure_reasons)})"
                    print(f"[{run_idx}][{idx:03d}/{len(scenarios_to_run):03d}] {sc.id} ({sc.category}): {status_str} ({dur:.2f}s)", flush=True)

                except Exception as exc:
                    dur = time.time() - t0
                    info = {
                        "pass": False,
                        "outcome": "error",
                        "expected": sc.expected_outcome,
                        "duration": dur,
                        "failures": [str(exc)],
                        "sql": "",
                        "explanation": "",
                    }
                    print(f"[{run_idx}][{idx:03d}/{len(scenarios_to_run):03d}] {sc.id} ({sc.category}): EXCEPTION {exc} ({dur:.2f}s)", flush=True)

                if sc.id not in scenario_results:
                    scenario_results[sc.id] = []
                scenario_results[sc.id].append(info)

                # Small throttle to stay well below rate limit
                time.sleep(0.3)

    # -----------------------------------------------------------------------
    # Summary Analysis
    # -----------------------------------------------------------------------
    categories = defaultdict(list)
    for sc in scenarios_to_run:
        categories[sc.category].append(sc)

    print("\n" + "="*80)
    print("SCENARIO MATRIX FINAL REPORT")
    print("="*80)

    category_stats = {}
    total_pass = 0
    total_fail = 0
    total_flaky = 0

    for cat_name, sc_list in categories.items():
        cat_pass = 0
        cat_fail = 0
        cat_flaky = 0

        for sc in sc_list:
            runs = scenario_results.get(sc.id, [])
            p1 = runs[0]["pass"] if len(runs) > 0 else False
            p2 = runs[1]["pass"] if len(runs) > 1 else p1

            if p1 and p2:
                cat_pass += 1
            elif not p1 and not p2:
                cat_fail += 1
                print(f"  FAIL: [{sc.id}] {sc.description}: {runs[0].get('failures')}")
            else:
                cat_flaky += 1
                print(f"  FLAKY: [{sc.id}] {sc.description}: Run 1 pass={p1}, Run 2 pass={p2}")

        total_pass += cat_pass
        total_fail += cat_fail
        total_flaky += cat_flaky

        rate = (cat_pass / len(sc_list)) * 100.0 if sc_list else 0.0
        category_stats[cat_name] = {
            "total": len(sc_list),
            "pass": cat_pass,
            "fail": cat_fail,
            "flaky": cat_flaky,
            "pass_rate": rate,
        }

    print("\nCATEGORY BREAKDOWN:")
    print(f"{'Category':<32} | {'Total':<6} | {'Pass':<6} | {'Fail':<6} | {'Flaky':<6} | {'Pass Rate':<10}")
    print("-" * 80)
    for cat_name, stats in category_stats.items():
        print(f"{cat_name:<32} | {stats['total']:<6} | {stats['pass']:<6} | {stats['fail']:<6} | {stats['flaky']:<6} | {stats['pass_rate']:.1f}%")
    print("-" * 80)
    overall_rate = (total_pass / len(scenarios_to_run)) * 100.0 if scenarios_to_run else 0.0
    print(f"{'TOTAL OVERALL':<32} | {len(scenarios_to_run):<6} | {total_pass:<6} | {total_fail:<6} | {total_flaky:<6} | {overall_rate:.1f}%")
    print("=" * 80)

    return total_pass, total_fail, total_flaky, category_stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--category", "-c", type=str, default=None, help="Filter scenarios by category substring or code (e.g. C1, C7)")
    parser.add_argument("--runs", "-r", type=int, default=2, help="Number of runs (default 2)")
    args = parser.parse_args()
    run_full_matrix(target_category=args.category, num_runs=args.runs)
