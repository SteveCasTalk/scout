import { sqliteTable, text, integer, index } from 'drizzle-orm/sqlite-core';
export const cases = sqliteTable('test_cases', {
    id: text('id').primaryKey(), owner: text('owner').notNull(), project: text('project').notNull().default('General'), appId: text('app_id').notNull().default(''), title: text('title').notNull(), platform: text('platform').notNull(), suite: text('suite').notNull(), goal: text('goal').notNull(), preconditions: text('preconditions').notNull(), steps: text('steps').notNull(), expected: text('expected').notNull(), assertionText: text('assertion_text').notNull().default(''), revision: integer('revision').notNull(), updated: text('updated').notNull(),
}, t => [index('idx_cases_owner').on(t.owner)]);
export const runs = sqliteTable('runs', {
    id: text('id').primaryKey(), owner: text('owner').notNull(), caseId: text('case_id').notNull(), externalRunId: text('external_run_id'), snapshot: text('snapshot').notNull(), status: text('status').notNull(), build: text('build').notNull(), device: text('device').notNull(), notes: text('notes').notNull(), source: text('source').notNull().default('Manual'), traceJson: text('trace_json').notNull().default('[]'), created: text('created').notNull(),
}, t => [index('idx_runs_owner').on(t.owner), index('idx_runs_external_owner').on(t.owner, t.externalRunId)]);
export const evidence = sqliteTable('evidence', {
    id: text('id').primaryKey(), owner: text('owner').notNull(), runId: text('run_id').notNull(), name: text('name').notNull(), mime: text('mime').notNull(), size: integer('size').notNull(), objectKey: text('object_key').notNull(), created: text('created').notNull(),
}, t => [index('idx_evidence_owner_run').on(t.owner, t.runId)]);
