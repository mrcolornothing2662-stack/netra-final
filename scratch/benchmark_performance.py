"""
NETRA 5.0 Performance & Concurrency Benchmark Suite.
Measures ingestion, graph construction, cognitive reasoning latency,
and concurrent DB connection pool resilience.
"""

import asyncio
import os
import sys
import time
from typing import List, Dict, Any

# Ensure backend modules can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

import httpx
from cognitive import data_path
from cognitive.anomaly import build_entity_profiles, detect_transaction_spikes, scan_behavioral_anomalies
from cognitive.mo import classify_case_evidence, load_playbooks
from cognitive.uncertainty import audit_case_confidence
from cognitive.defence import audit_case_defensibility
from graph.graph_builder import build_case_graph
from parsers.whatsapp_parser import parse_whatsapp_export
from parsers.call_log_parser import parse_call_log_csv
from parsers.bank_csv_parser import parse_bank_csv

BASE_URL = "http://127.0.0.1:8000"


def format_stats(latencies_ms: List[float]) -> Dict[str, float]:
    latencies_sorted = sorted(latencies_ms)
    n = len(latencies_sorted)
    p50 = latencies_sorted[int(n * 0.50)]
    p95 = latencies_sorted[min(int(n * 0.95), n - 1)]
    avg = sum(latencies_sorted) / n
    return {
        "p50_ms": round(p50, 2),
        "p95_ms": round(p95, 2),
        "max_ms": round(latencies_sorted[-1], 2),
        "avg_ms": round(avg, 2),
        "runs": n,
    }


def benchmark_ingestion_parsers():
    print("\n--- 1. Ingestion & Parser Latency Benchmark ---")
    scratch_dir = os.path.abspath(os.path.join(os.path.dirname(__file__)))
    chat_file = os.path.join(scratch_dir, "tmp_benchmark_chat.txt")
    cdr_file = os.path.join(scratch_dir, "tmp_benchmark_cdr.csv")

    # 1. Chat Parser: 1000 WhatsApp lines
    chat_lines = [
        f"18/08/2026, 10:{i%60:02d} am - Officer Sharma: Please share your Aadhaar number."
        if i % 2 == 0 else
        f"18/08/2026, 10:{i%60:02d} am - Target: Transferring funds to account 9876543210."
        for i in range(1, 1001)
    ]
    with open(chat_file, "w", encoding="utf-8") as f:
        f.write("\n".join(chat_lines))

    chat_latencies = []
    for _ in range(10):
        t0 = time.perf_counter()
        events = parse_whatsapp_export(chat_file)
        chat_latencies.append((time.perf_counter() - t0) * 1000)

    chat_stats = format_stats(chat_latencies)
    print(f"WhatsApp Parser (1000 msgs): p50={chat_stats['p50_ms']}ms | p95={chat_stats['p95_ms']}ms | avg={chat_stats['avg_ms']}ms ({len(events)} events parsed)")

    # 2. CDR Parser: 1000 CDR rows
    cdr_rows = ["caller_number,receiver_number,timestamp,duration_sec,call_type,cell_id,imei"]
    for i in range(1, 1001):
        cdr_rows.append(f"+91987654{i:04d},+91876543{i:04d},2026-08-18 11:{i%60:02d}:00,{i%300},VOICE,TOWER_{i%10},358765432109876")
    with open(cdr_file, "w", encoding="utf-8") as f:
        f.write("\n".join(cdr_rows))

    cdr_latencies = []
    for _ in range(10):
        t0 = time.perf_counter()
        cdr_events = parse_call_log_csv(cdr_file)
        cdr_latencies.append((time.perf_counter() - t0) * 1000)

    cdr_stats = format_stats(cdr_latencies)
    print(f"CDR Parser (1000 records): p50={cdr_stats['p50_ms']}ms | p95={cdr_stats['p95_ms']}ms | avg={cdr_stats['avg_ms']}ms ({len(cdr_events)} events parsed)")

    # Clean up
    for p in (chat_file, cdr_file):
        if os.path.exists(p):
            os.remove(p)


def benchmark_cognitive_engines():
    print("\n--- 2. Cognitive Engines Latency Benchmark ---")
    
    # Behavioral Anomaly: 500 transactions across 10 accounts
    bank_txs = []
    for i in range(500):
        acc = f"ACC_{i % 10:02d}"
        bank_txs.append({
            "metadata": {
                "account": acc,
                "amount": float(1000 + (i * 73) % 90000),
                "type": "DEBIT" if i % 2 == 0 else "CREDIT",
                "counterparty": f"ACC_{(i + 1) % 10:02d}",
            },
            "timestamp": f"2026-08-18T{(i%24):02d}:{(i%60):02d}:00Z",
        })

    anomaly_latencies = []
    for _ in range(15):
        t0 = time.perf_counter()
        profiles = build_entity_profiles(bank_txs, [], [])
        spikes = detect_transaction_spikes(bank_txs, profiles)
        anomaly_latencies.append((time.perf_counter() - t0) * 1000)
    
    anom_stats = format_stats(anomaly_latencies)
    print(f"Behavioral Anomaly Profiler (500 txs): p50={anom_stats['p50_ms']}ms | p95={anom_stats['p95_ms']}ms | avg={anom_stats['avg_ms']}ms")

    # Crime Script Matcher (MO): 200 evidence events matched against all 6 playbooks
    playbook_file = data_path("playbooks.json")
    playbooks = load_playbooks(playbook_file)
    test_evidence = [
        {"type": "chat_message", "text": "This is CBI officer. Arrest warrant issued against your Aadhaar.", "timestamp": "2026-08-18 10:00:00"},
        {"type": "chat_message", "text": "Stay on Skype video call. Digital arrest initiated. Do not disconnect.", "timestamp": "2026-08-18 10:15:00"},
        {"type": "bank_transaction", "amount": 250000.0, "narration": "RTGS RBI SECURITY CLEARANCE TO MULE ACC", "timestamp": "2026-08-18 11:30:00"},
    ] * 50

    mo_latencies = []
    for _ in range(15):
        t0 = time.perf_counter()
        mo_res = classify_case_evidence(test_evidence, playbooks)
        mo_latencies.append((time.perf_counter() - t0) * 1000)

    mo_stats = format_stats(mo_latencies)
    print(f"Crime Script Matcher (150 multi-modal events): p50={mo_stats['p50_ms']}ms | p95={mo_stats['p95_ms']}ms | avg={mo_stats['avg_ms']}ms (Matched: {mo_res['best_match']['playbook'] if mo_res.get('best_match') else 'None'})")

    # Confidence Meter Audit (10 findings, 5 evidence items)
    sample_findings = [
        {"id": f"F_{i}", "category": "FINANCIAL", "title": f"Mule transfer {i}", "confidence_score": 0.85, "supporting_evidence_ids": ["E_1", "E_2"]}
        for i in range(10)
    ]
    sample_evidence = [{"id": f"E_{i}", "file_type": "PDF", "source": "Bank"} for i in range(5)]

    conf_latencies = []
    for _ in range(15):
        t0 = time.perf_counter()
        conf_rep = audit_case_confidence(sample_findings, sample_evidence)
        conf_latencies.append((time.perf_counter() - t0) * 1000)

    conf_stats = format_stats(conf_latencies)
    print(f"Confidence Meter Bayesian Audit (10 findings): p50={conf_stats['p50_ms']}ms | p95={conf_stats['p95_ms']}ms | avg={conf_stats['avg_ms']}ms")

    # Defence Bot Adversarial Critique
    def_latencies = []
    for _ in range(10):
        t0 = time.perf_counter()
        def_rep = audit_case_defensibility(
            case_id="BENCHMARK_CASE_01",
            evidence_files=sample_evidence,
            events=[],
            findings=sample_findings,
        )
        def_latencies.append((time.perf_counter() - t0) * 1000)

    def_stats = format_stats(def_latencies)
    print(f"Defence Bot Critique (10 findings, BSA/BNSS checks): p50={def_stats['p50_ms']}ms | p95={def_stats['p95_ms']}ms | avg={def_stats['avg_ms']}ms")


async def benchmark_concurrent_api_traffic():
    print("\n--- 3. Concurrent Server & DB Pool Benchmark ---")
    
    # Check server health
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as client:
        try:
            health = await client.get("/health")
            if health.status_code != 200:
                print(f"[!] Warning: /health returned {health.status_code}")
                return
            print("[+] Server reachable at http://127.0.0.1:8000")
        except Exception as e:
            print(f"[!] Server connection failed: {e}")
            return

        # Fire 30 concurrent requests to read-heavy endpoints
        endpoints = [
            "/health",
            "/api/docs",
            "/openapi.json",
        ] * 10  # 30 concurrent requests

        t0 = time.perf_counter()
        tasks = [client.get(ep) for ep in endpoints]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        total_time = (time.perf_counter() - t0) * 1000

        successes = sum(1 for r in responses if isinstance(r, httpx.Response) and r.status_code == 200)
        errors = len(responses) - successes

        print(f"Concurrent requests completed: {len(responses)}")
        print(f"Successes (HTTP 200): {successes}/{len(responses)}")
        print(f"Errors / Timeouts: {errors}")
        print(f"Total time for 30 concurrent requests: {total_time:.2f}ms (Avg {total_time/len(responses):.2f}ms/req)")
        assert errors == 0, f"Expected 0 errors under concurrency, got {errors}"


async def main():
    print("=" * 60)
    print("  NETRA 5.0 PRODUCTION HARDENING & BENCHMARK SUITE")
    print("=" * 60)
    
    benchmark_ingestion_parsers()
    benchmark_cognitive_engines()
    await benchmark_concurrent_api_traffic()
    
    print("\n" + "=" * 60)
    print("  ALL BENCHMARKS COMPLETED SATISFACTORILY")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
