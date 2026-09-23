import React from 'react';
import type { Case } from '../../../data/types';
import { CaseNotesSection } from '../../../components/notes/CaseNotesSection';
import { CommandCenter } from '../CommandCenter';

export function Overview({ caseData }: { caseData: Case }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      {/* Investigation Command Center — Primary Workspace */}
      <CommandCenter caseId={caseData.id} />

      {/* Case-specific Investigator Notes & Sticky Wall */}
      <CaseNotesSection caseId={caseData.id} />
    </div>
  );
}
