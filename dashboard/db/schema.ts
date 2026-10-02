import { sqliteTable, text, integer, index } from 'drizzle-orm/sqlite-core';
export const workspaces = sqliteTable('workspaces', {
    id: text('id').primaryKey(), owner: text('owner').notNull(), name: text('name').notNull(), created: text('created').notNull(),
}, t => [index('idx_workspaces_owner').on(t.owner)]);
export const cases = sqliteTable('test_cases', {
    id: text('id').primaryKey(), owner: text('owner').notNull(), workspaceId: text('workspace_id').notNull().default(''), project: text('project').notNull().default('General'), ticketKey: text('ticket_key').notNull().default(''), appId: text('app_id').notNull().default(''), title: text('title').notNull(), platform: text('platform').notNull(), suite: text('suite').notNull(), goal: text('goal').notNull(), preconditions: text('preconditions').notNull(), steps: text('steps').notNull(), expected: text('expected').notNull(), checkpointsJson: text('checkpoints_json').notNull().default('[]'), startingConditionsJson: text('starting_conditions_json').notNull().default('{}'), assertionText: text('assertion_text').notNull().default(''), revision: integer('revision').notNull(), updated: text('updated').notNull(),
}, t => [index('idx_cases_owner').on(t.owner), index('idx_cases_owner_workspace').on(t.owner, t.workspaceId)]);
export const runs = sqliteTable('runs', {
    id: text('id').primaryKey(), owner: text('owner').notNull(), workspaceId: text('workspace_id').notNull().default(''), caseId: text('case_id').notNull(), externalRunId: text('external_run_id'), snapshot: text('snapshot').notNull(), status: text('status').notNull(), build: text('build').notNull(), device: text('device').notNull(), deviceInfoJson: text('device_info_json').notNull().default('{}'), appLogs: text('app_logs').notNull().default(''), notes: text('notes').notNull(), source: text('source').notNull().default('Manual'), traceJson: text('trace_json').notNull().default('[]'), created: text('created').notNull(),
}, t => [index('idx_runs_owner').on(t.owner), index('idx_runs_external_owner').on(t.owner, t.externalRunId), index('idx_runs_owner_workspace').on(t.owner, t.workspaceId)]);
export const evidence = sqliteTable('evidence', {
    id: text('id').primaryKey(), owner: text('owner').notNull(), runId: text('run_id').notNull(), name: text('name').notNull(), mime: text('mime').notNull(), size: integer('size').notNull(), objectKey: text('object_key').notNull(), created: text('created').notNull(),
}, t => [index('idx_evidence_owner_run').on(t.owner, t.runId)]);

export const reviewNotes = sqliteTable('review_notes', {
    id: text('id').primaryKey(), owner: text('owner').notNull(), workspaceId: text('workspace_id').notNull(), targetType: text('target_type').notNull(), targetId: text('target_id').notNull(), body: text('body').notNull(), created: text('created').notNull(), updated: text('updated').notNull(),
}, t => [index('idx_review_notes_owner_target').on(t.owner, t.targetType, t.targetId)]);

export const checkpointReviews = sqliteTable('checkpoint_reviews', {
    id: text('id').primaryKey(), owner: text('owner').notNull(), workspaceId: text('workspace_id').notNull(), runId: text('run_id').notNull(), checkpointId: text('checkpoint_id').notNull(), originalVerdict: text('original_verdict').notNull(), decision: text('decision').notNull(), explanation: text('explanation').notNull(), created: text('created').notNull(),
}, t => [index('idx_checkpoint_reviews_owner_run').on(t.owner, t.runId)]);
