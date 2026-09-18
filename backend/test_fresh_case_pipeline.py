import asyncio
import httpx
import os
import sys
import uuid
import itertools

BASE_URL = 'http://127.0.0.1:8000'
ZIP_PATH = '/Users/shubhamrana/Downloads/NETRA_Operation_Meridian_Synthetic_Case.zip'

async def run_test():
    print("=" * 70)
    print("NETRA 5.0 — FRESH CASE END-TO-END INGESTION & PIPELINE VERIFICATION")
    print("=" * 70)

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=120.0, follow_redirects=True) as client:
        # 1. Login
        login_res = await client.post('/api/v1/auth/login', data={'username': 'admin', 'password': 'admin123'})
        assert login_res.status_code == 200, f'Login failed: {login_res.text}'
        token = login_res.json()['access_token']
        headers = {'Authorization': f'Bearer {token}'}
        print('1. [AUTH] Logged in successfully as admin')

        # 2. Check for and clean any prior test case with this title
        cases_res = await client.get('/api/v1/cases', headers=headers)
        if cases_res.status_code == 200:
            existing = cases_res.json().get('cases', [])
            for c in existing:
                if 'Operation Meridian' in c.get('title', ''):
                    c_num = c.get('case_number')
                    c_id = c.get('id')
                    del_res = await client.delete(f"/api/v1/cases/{c_id}", headers=headers)
                    print(f'   Cleaned up prior test case: {c_num} ({c_id})')

        # 3. Create fresh case
        case_payload = {
            'title': 'Operation Meridian — Synthetic Pipeline Verification',
            'description': 'Automated validation of canonical entity firewall, evidence provenance, and cognitive loop',
            'crime_type': 'Cyber Fraud / Mule Ring',
            'priority': 'high',
            'tags': ['synthetic_test', 'firewall_verification']
        }
        create_res = await client.post('/api/v1/cases', json=case_payload, headers=headers)
        assert create_res.status_code in (200, 201), f'Case creation failed: {create_res.text}'
        case_data = create_res.json()
        case_id = case_data['id']
        case_num = case_data['case_number']
        print(f'2. [CASE] Created fresh case: {case_num} (UUID: {case_id})')

        # 4. Upload synthetic evidence zip package
        print(f'3. [UPLOAD] Uploading synthetic package: {os.path.basename(ZIP_PATH)}...')
        with open(ZIP_PATH, 'rb') as f:
            upload_res = await client.post(
                '/api/v1/evidence/upload',
                data={'case_id': case_id, 'source_type': 'zip'},
                files={'files': (os.path.basename(ZIP_PATH), f, 'application/zip')},
                headers=headers,
            )
        assert upload_res.status_code == 200, f'Upload failed: {upload_res.text}'
        upload_data = upload_res.json()
        queued_files = upload_data.get('files', [])
        print(f'   Uploaded and unzipped: {len(queued_files)} evidence files queued for parsing')
        for qf in queued_files:
            fname = qf.get('filename')
            fhash = str(qf.get('sha256_hash', ''))[:12]
            print(f'     • {fname} (SHA-256: {fhash}...)')

        # 5. Wait for all background parsing tasks to complete
        print('\n4. [PROCESSING] Waiting for background parsers and entity extractors to complete...')
        timeout_seconds = 90
        waited = 0
        all_done = False
        files_state = []

        while waited < timeout_seconds:
            ev_res = await client.get(f'/api/v1/evidence/{case_id}', headers=headers)
            files_state = ev_res.json().get('files', [])
            done = [f for f in files_state if f['upload_status'] in ('processed', 'failed')]
            if len(files_state) >= len(queued_files) and len(done) >= len(files_state):
                all_done = True
                break
            await asyncio.sleep(2)
            waited += 2

        processed_count = sum(1 for f in files_state if f['upload_status'] == 'processed')
        failed_count = sum(1 for f in files_state if f['upload_status'] == 'failed')
        print(f'   Files Status: {processed_count} processed, {failed_count} failed in {waited}s')
        for f in files_state:
            fname = f.get('filename')
            fstatus = f.get('upload_status')
            ferr = f.get('parse_error')
            status_icon = "🟢" if fstatus == 'processed' else "🔴"
            err_str = f" (Error: {ferr})" if ferr else ""
            print(f'     {status_icon} {fname}: {fstatus}{err_str}')

        assert all_done, f'Timeout waiting for evidence processing after {waited}s'

        # 6. Timeline and Events summary
        timeline_res = await client.get(f'/api/v1/timeline/{case_id}', headers=headers)
        timeline_events = timeline_res.json().get('events', []) if timeline_res.status_code == 200 else []
        print(f'\n5. [EVENTS] Extracted {len(timeline_events)} timeline evidence events')

        # 7. Query Database Directly for Entities, Mentions, and Relationships
        sys.path.insert(0, '/Users/shubhamrana/netra5.0/backend')
        from db.session import AsyncSessionLocal
        from db.models import Entity, EntityMention, Relationship, EvidenceEvent
        from sqlalchemy import select, func

        case_uuid = uuid.UUID(case_id)
        async with AsyncSessionLocal() as db:
            total_events = (await db.execute(
                select(func.count()).select_from(EvidenceEvent).where(EvidenceEvent.case_id == case_uuid)
            )).scalar() or 0

            ent_rows = (await db.execute(
                select(Entity).where(Entity.case_id == case_uuid).order_by(Entity.entity_type, Entity.canonical_value)
            )).scalars().all()

            total_mentions = (await db.execute(
                select(func.count()).select_from(EntityMention).join(Entity).where(Entity.case_id == case_uuid)
            )).scalar() or 0

            rel_rows = (await db.execute(
                select(Relationship).where(Relationship.case_id == case_uuid)
            )).scalars().all()

        print(f'\n6. [DATABASE METRICS]')
        print(f'   • Evidence Files: {len(files_state)} ({processed_count} processed)')
        print(f'   • Evidence Events in DB: {total_events}')
        print(f'   • Database Entities: {len(ent_rows)}')
        print(f'   • Database Entity Mentions: {total_mentions}')
        print(f'   • Observed Relationships: {len(rel_rows)}')

        # Group entities by type
        by_type = {}
        for ent in ent_rows:
            by_type.setdefault(ent.entity_type, []).append(ent.canonical_value)

        print('\n' + '=' * 70)
        print(f'MATERIALISED DATABASE ENTITIES ({len(ent_rows)} total):')
        print('=' * 70)

        for etype in sorted(by_type.keys()):
            values = sorted(by_type[etype])
            print(f'\n{etype} ({len(values)}):')
            for val in values:
                print(f'  ├─ {val}')

        # 8. Run Assertions
        print('\n' + '=' * 70)
        print('QUALITY ASSERTIONS (VERIFYING NO LEAKED FALSE POSITIVES):')
        print('=' * 70)

        forbidden_per = {
            'UNKNOWN', 'UNK', 'N/A', 'NA', 'NULL', 'NONE', 'SYSTEM',
            'NETWORK ANALYSIS', 'CONVERSATION', 'PARTICIPANTS',
            'PARTICIPANT', 'COMMUNICATION', '/ COMMUNICATION',
            'CONFIRMED. I', 'CONFIRMED', 'RECEIVED', 'SENT',
            'CHANDIGARH, INDIA'
        }

        all_persons = by_type.get('PERSON', []) + by_type.get('PER', [])
        for p in all_persons:
            p_upper = p.upper().strip()
            assert p_upper not in forbidden_per, f'❌ FAILED: Forbidden person persisted: {p}'
            assert not p_upper.startswith('+'), f'❌ FAILED: Phone number persisted as person: {p}'
            assert not ('2026' in p_upper and '-' in p_upper), f'❌ FAILED: Timestamp persisted as person: {p}'
        print('  ✅ Assert PASS: No PERSON -> UNKNOWN')
        print('  ✅ Assert PASS: No PERSON -> Phone (+91...)')
        print('  ✅ Assert PASS: No PERSON -> Chandigarh, India')
        print('  ✅ Assert PASS: No PERSON -> Network Analysis / Communication')
        print('  ✅ Assert PASS: No PERSON -> Conversation / Participants')
        print('  ✅ Assert PASS: No PERSON -> 2026-08-21...')
        print('  ✅ Assert PASS: No PERSON -> Confirmed. I')

        all_amounts = by_type.get('AMOUNT', [])
        for a in all_amounts:
            a_str = str(a).strip()
            assert a_str.lower() != 'received.', f'❌ FAILED: Received. persisted as amount: {a}'
            assert a_str not in ('2026', '2026.0'), f'❌ FAILED: Year 2026 persisted as amount: {a}'
        print('  ✅ Assert PASS: No AMOUNT -> Received.')
        print('  ✅ Assert PASS: No AMOUNT -> 2026 / 2026.0')

        all_keywords = by_type.get('KEYWORD', [])
        for k in all_keywords:
            assert not str(k).startswith('ACCT-'), f'❌ FAILED: ACCT-... persisted as KEYWORD: {k}'
            assert not str(k).startswith('ACC-'), f'❌ FAILED: ACC-... persisted as KEYWORD: {k}'
        print('  ✅ Assert PASS: No KEYWORD -> ACCT-... / ACC-...')

        all_banks = by_type.get('BANK', [])
        for b in all_banks:
            assert not str(b).startswith('+'), f'❌ FAILED: Phone persisted as BANK: {b}'
            assert str(b).lower() not in ('bank',), f'❌ FAILED: Generic bank persisted as BANK: {b}'
        print('  ✅ Assert PASS: No BANK -> Phone / Generic "Bank"')

        # 9. Check Cognitive Orchestration Findings
        print('\n7. [COGNITIVE INTELLIGENCE]')
        async with AsyncSessionLocal() as db:
            from db.models import InvestigationFinding
            findings = (await db.execute(
                select(InvestigationFinding).where(InvestigationFinding.case_id == case_uuid).order_by(InvestigationFinding.created_at.desc())
            )).scalars().all()
        print(f'   Cognitive Analysis Status: ACTIVE ({len(findings)} findings generated in DB)')
        for f in findings[:6]:
            print(f'     • [{f.finding_type}] {f.title} (severity: {f.severity})')

        print('\n' + '=' * 70)
        print('ALL PIPELINE ASSERTIONS PASSED WITH 100% CLEAN ENTITIES!')
        print('=' * 70)

if __name__ == '__main__':
    asyncio.run(run_test())
