CREATE TABLE `matrix_batches` (
	`id` text PRIMARY KEY NOT NULL,
	`owner` text NOT NULL,
	`workspace_id` text NOT NULL,
	`matrix_id` text NOT NULL,
	`matrix_revision` integer NOT NULL,
	`matrix_name` text NOT NULL,
	`case_id` text NOT NULL,
	`entries_json` text NOT NULL,
	`settings_json` text NOT NULL,
	`request_signature` text NOT NULL,
	`summary_json` text NOT NULL,
	`created` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `idx_matrix_batches_owner_case` ON `matrix_batches` (`owner`,`workspace_id`,`case_id`);--> statement-breakpoint
CREATE TABLE `scenario_matrices` (
	`id` text PRIMARY KEY NOT NULL,
	`owner` text NOT NULL,
	`workspace_id` text NOT NULL,
	`case_id` text NOT NULL,
	`name` text NOT NULL,
	`revision` integer NOT NULL,
	`definition_json` text NOT NULL,
	`updated` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `idx_matrices_owner_case` ON `scenario_matrices` (`owner`,`workspace_id`,`case_id`);--> statement-breakpoint
ALTER TABLE `runs` ADD `matrix_batch_id` text;--> statement-breakpoint
ALTER TABLE `runs` ADD `matrix_variant_id` text;--> statement-breakpoint
CREATE UNIQUE INDEX `idx_runs_matrix_variant` ON `runs` (`owner`,`workspace_id`,`matrix_batch_id`,`matrix_variant_id`);