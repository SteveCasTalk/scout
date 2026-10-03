import { sqliteTable, text, integer, index, uniqueIndex, primaryKey } from 'drizzle-orm/sqlite-core';
export const workspaces = sqliteTable('workspaces', {
    id: text('id').primaryKey(), owner: text('owner').notNull(), name: text('name').notNull(), created: text('created').notNull(),
}, t => [index('idx_workspaces_owner').on(t.owner)]);
export const cases = sqliteTable('test_cases', {
    id: text('id').primaryKey(), owner: text('owner').notNull(), workspaceId: text('workspace_id').notNull().default(''), project: text('project').notNull().default('General'), ticketKey: text('ticket_key').notNull().default(''), sandboxJson: text('sandbox_json').notNull().default('null'), comparisonKey: text('comparison_key').notNull().default(''), appId: text('app_id').notNull().default(''), title: text('title').notNull(), platform: text('platform').notNull(), suite: text('suite').notNull(), goal: text('goal').notNull(), preconditions: text('preconditions').notNull(), steps: text('steps').notNull(), expected: text('expected').notNull(), checkpointsJson: text('checkpoints_json').notNull().default('[]'), startingConditionsJson: text('starting_conditions_json').notNull().default('{}'), assertionText: text('assertion_text').notNull().default(''), revision: integer('revision').notNull(), updated: text('updated').notNull(),
}, t => [index('idx_cases_owner').on(t.owner), index('idx_cases_owner_workspace').on(t.owner, t.workspaceId)]);
export const runs = sqliteTable('runs', {
    id: text('id').primaryKey(), owner: text('owner').notNull(), workspaceId: text('workspace_id').notNull().default(''), caseId: text('case_id').notNull(), externalRunId: text('external_run_id'), matrixBatchId: text('matrix_batch_id'), matrixVariantId: text('matrix_variant_id'), snapshot: text('snapshot').notNull(), status: text('status').notNull(), build: text('build').notNull(), device: text('device').notNull(), deviceInfoJson: text('device_info_json').notNull().default('{}'), appLogs: text('app_logs').notNull().default(''), notes: text('notes').notNull(), source: text('source').notNull().default('Manual'), traceJson: text('trace_json').notNull().default('[]'), created: text('created').notNull(),
}, t => [index('idx_runs_owner').on(t.owner), index('idx_runs_external_owner').on(t.owner, t.externalRunId), index('idx_runs_owner_workspace').on(t.owner, t.workspaceId), uniqueIndex('idx_runs_matrix_variant').on(t.owner,t.workspaceId,t.matrixBatchId,t.matrixVariantId)]);
export const caseRevisions = sqliteTable('case_revisions', {
    owner: text('owner').notNull(), workspaceId: text('workspace_id').notNull(), caseId: text('case_id').notNull(), revision: integer('revision').notNull(), snapshotJson: text('snapshot_json').notNull(), created: text('created').notNull(),
}, t => [primaryKey({columns:[t.owner,t.caseId,t.revision]}), index('idx_case_revisions_owner_workspace').on(t.owner,t.workspaceId,t.caseId)]);
export const evidence = sqliteTable('evidence', {
    id: text('id').primaryKey(), owner: text('owner').notNull(), runId: text('run_id').notNull(), name: text('name').notNull(), mime: text('mime').notNull(), size: integer('size').notNull(), objectKey: text('object_key').notNull(), created: text('created').notNull(),
}, t => [index('idx_evidence_owner_run').on(t.owner, t.runId)]);

export const reviewNotes = sqliteTable('review_notes', {
    id: text('id').primaryKey(), owner: text('owner').notNull(), workspaceId: text('workspace_id').notNull(), targetType: text('target_type').notNull(), targetId: text('target_id').notNull(), body: text('body').notNull(), created: text('created').notNull(), updated: text('updated').notNull(),
}, t => [index('idx_review_notes_owner_target').on(t.owner, t.targetType, t.targetId)]);

export const checkpointReviews = sqliteTable('checkpoint_reviews', {
    id: text('id').primaryKey(), owner: text('owner').notNull(), workspaceId: text('workspace_id').notNull(), runId: text('run_id').notNull(), checkpointId: text('checkpoint_id').notNull(), originalVerdict: text('original_verdict').notNull(), decision: text('decision').notNull(), explanation: text('explanation').notNull(), created: text('created').notNull(),
}, t => [index('idx_checkpoint_reviews_owner_run').on(t.owner, t.runId)]);

export const platformComparisons = sqliteTable('platform_comparisons', {
    id: text('id').primaryKey(), owner: text('owner').notNull(), workspaceId: text('workspace_id').notNull(), androidRunId: text('android_run_id').notNull(), iosRunId: text('ios_run_id').notNull(), reportJson: text('report_json').notNull(), created: text('created').notNull(),
}, t => [index('idx_comparisons_owner_workspace').on(t.owner, t.workspaceId)]);
export const comparisonReviews = sqliteTable('comparison_reviews', {
    id: text('id').primaryKey(), owner: text('owner').notNull(), comparisonId: text('comparison_id').notNull(), checkpointId: text('checkpoint_id').notNull(), conclusion: text('conclusion').notNull(), explanation: text('explanation').notNull(), created: text('created').notNull(),
}, t => [index('idx_comparison_reviews_owner').on(t.owner, t.comparisonId)]);

export const scenarioMatrices = sqliteTable('scenario_matrices', {
    id: text('id').primaryKey(), owner: text('owner').notNull(), workspaceId: text('workspace_id').notNull(), caseId: text('case_id').notNull(), name: text('name').notNull(), revision: integer('revision').notNull(), definitionJson: text('definition_json').notNull(), updated: text('updated').notNull(),
}, t => [index('idx_matrices_owner_case').on(t.owner,t.workspaceId,t.caseId)]);
export const matrixBatches = sqliteTable('matrix_batches', {
    id: text('id').primaryKey(), owner: text('owner').notNull(), workspaceId: text('workspace_id').notNull(), matrixId: text('matrix_id').notNull(), matrixRevision: integer('matrix_revision').notNull(), matrixName: text('matrix_name').notNull(), caseId: text('case_id').notNull(), entriesJson: text('entries_json').notNull(), settingsJson: text('settings_json').notNull(), requestSignature: text('request_signature').notNull(), summaryJson: text('summary_json').notNull(), created: text('created').notNull(),
}, t => [index('idx_matrix_batches_owner_case').on(t.owner,t.workspaceId,t.caseId)]);
