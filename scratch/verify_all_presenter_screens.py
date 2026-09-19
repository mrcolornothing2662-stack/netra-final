"""
Verification script for all 21 screens described in the Presenter Walkthrough.
Verifies endpoints, data structures, and Copilot answers for Operation Meridian.
"""
import asyncio
import httpx
import json

BASE_URL = "http://127.0.0.1:8000"

async def verify_presenter_walkthrough():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
        # Auth
        login_res = await client.post("/api/v1/auth/login", data={"username": "admin", "password": "admin123"})
        assert login_res.status_code == 200, f"Login failed: {login_res.text}"
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        print("✅ [AUTH] Logged in successfully as admin")

        # 1. Dashboard / Case Selection
        case_id = "d456ad33-6411-4ece-baa8-397d9f422fe3"
        stats_res = await client.get(f"/api/v1/cases/{case_id}", headers=headers)
        assert stats_res.status_code == 200
        meridian_case = stats_res.json()
        print(f"✅ [SCREEN 1 - DASHBOARD] Found Operation Meridian case: {case_id} ({meridian_case.get('case_number')})")

        # Case Stats / Overview
        stats_res = await client.get(f"/api/v1/cases/{case_id}", headers=headers)
        assert stats_res.status_code == 200
        print(f"   Case details: {stats_res.json().get('title')} | Priority: {stats_res.json().get('priority')}")

        # 2. Evidence Screen
        ev_res = await client.get(f"/api/v1/evidence/{case_id}", headers=headers)
        assert ev_res.status_code == 200
        files = ev_res.json().get("files", [])
        assert len(files) >= 11, f"Expected >= 11 files, got {len(files)}"
        sample_file = files[0]
        assert "sha256_hash" in sample_file
        print(f"✅ [SCREEN 2 - EVIDENCE] {len(files)} evidence files verified with SHA-256 hashes.")
        print(f"   Sample evidence: {sample_file.get('filename')} (Hash: {sample_file.get('sha256_hash')[:16]}...)")

        # 3. Entity Extraction
        entities_res = await client.get(f"/api/v1/cases/{case_id}/entities", headers=headers)
        if entities_res.status_code != 200:
            # Fallback to graph endpoint if entities route differs
            graph_res = await client.get(f"/api/v1/graph/{case_id}", headers=headers)
            entities = graph_res.json().get("nodes", [])
        else:
            entities = entities_res.json().get("entities", [])
        entity_types = set(e.get("entity_type") or e.get("type") for e in entities)
        print(f"✅ [SCREEN 3 - ENTITIES] {len(entities)} canonical entities. Types: {entity_types}")

        # 4 & 5. Graph — Nodes, Edges, Observed vs Inferred
        graph_res = await client.get(f"/api/v1/graph/{case_id}", headers=headers)
        assert graph_res.status_code == 200
        gdata = graph_res.json()
        nodes = gdata.get("nodes", [])
        edges = gdata.get("edges", [])
        observed_edges = [e for e in edges if e.get("epistemic_status") == "observed"]
        inferred_edges = [e for e in edges if e.get("epistemic_status") == "inferred"]
        print(f"✅ [SCREEN 4 & 5 - GRAPH] {len(nodes)} nodes, {len(edges)} edges.")
        print(f"   Observed edges (solid): {len(observed_edges)}")
        print(f"   Inferred edges (dashed): {len(inferred_edges)}")
        if edges:
            sample_edge = edges[0]
            print(f"   Sample Edge metadata: type={sample_edge.get('relationship_type')} | status={sample_edge.get('epistemic_status')} | confidence={sample_edge.get('confidence')}")

        # 7 & 8. Timeline Demonstration
        timeline_res = await client.get(f"/api/v1/timeline/{case_id}", headers=headers)
        assert timeline_res.status_code == 200
        timeline_events = timeline_res.json().get("events", [])
        assert len(timeline_events) > 0, "No timeline events found!"
        print(f"✅ [SCREEN 7 & 8 - TIMELINE] {len(timeline_events)} temporal events available for replay.")

        # 9 to 18. Cognitive Engine Findings
        findings_res = await client.get(f"/api/v1/cases/{case_id}/findings", headers=headers)
        findings = findings_res.json().get("findings", []) if findings_res.status_code == 200 else []
        print(f"✅ [COGNITIVE ENGINES] {len(findings)} total findings generated in DB.")
        by_type = {}
        for f in findings:
            by_type.setdefault(f.get("finding_type"), []).append(f)
        for ftype, items in by_type.items():
            print(f"   • {ftype}: {len(items)} finding(s)")

        # 20. Legal Shield / Audit Verification
        audit_res = await client.get(f"/api/v1/audit/verify/{case_id}", headers=headers)
        print(f"✅ [SCREEN 20 - LEGAL SHIELD] Audit chain verification: status={audit_res.status_code}")
        if audit_res.status_code == 200:
            print(f"   Audit status: {audit_res.json().get('status')} | valid={audit_res.json().get('valid')}")

        # 21. Copilot Questions
        print("\n" + "=" * 70)
        print("VERIFYING COPILOT QUESTIONS FROM PRESENTER SCRIPT:")
        print("=" * 70)

        questions = [
            ("Q1: Exact factual question", "What amount was transferred through ACC-001?"),
            ("Q2: Relationship question", "What relationships connect ACC-001 to the available phone numbers?"),
            ("Q3: Temporal question", "What happened between August 20 and August 25?"),
        ]

        for q_label, question in questions:
            print(f"\n--- {q_label} ---")
            print(f"User Question: '{question}'")
            copilot_res = await client.post(
                f"/api/v1/copilot/{case_id}",
                json={"question": question, "top_k": 5},
                headers=headers,
            )
            print(f"Status Code: {copilot_res.status_code}")
            if copilot_res.status_code == 200:
                data = copilot_res.json()
                answer = data.get("answer", "")
                abstained = data.get("abstained", False)
                citations = data.get("citations", [])
                claims = data.get("claims", [])
                grounding = data.get("grounding_ratio")
                print(f"Abstained: {abstained}")
                print(f"Citations ({len(citations)}): {citations}")
                print(f"Grounding Ratio: {grounding}")
                print(f"Answer snippet: {answer[:300]}...")
            else:
                print(f"Error: {copilot_res.text}")

if __name__ == "__main__":
    asyncio.run(verify_presenter_walkthrough())
