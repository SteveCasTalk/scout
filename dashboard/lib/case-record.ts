import { z } from 'zod';
import { caseInput, type TestCase } from './contracts';

export const caseSnapshotInput = caseInput.extend({ id: z.string().uuid(), revision: z.number().int().positive(), updated: z.string() });
export function decodeCase(row: Record<string, unknown>): TestCase {
    return caseSnapshotInput.parse({ ...row,
        sandbox: JSON.parse(String(row.sandbox_json || 'null')),
        checkpoints: JSON.parse(String(row.checkpoints_json || '[]')),
        starting_conditions: JSON.parse(String(row.starting_conditions_json || '{}')),
    });
}
export function retainRevision(db: D1Database, owner: string, c: TestCase) {
    return db.prepare('INSERT OR IGNORE INTO case_revisions (owner,workspace_id,case_id,revision,snapshot_json,created) SELECT ?,?,?,?,?,? FROM test_cases WHERE owner=? AND workspace_id=? AND id=? AND revision=?')
        .bind(owner,c.workspace_id,c.id,c.revision,JSON.stringify(c),c.updated,owner,c.workspace_id,c.id,c.revision);
}
