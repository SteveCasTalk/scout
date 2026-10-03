CREATE TABLE `comparison_reviews` (
	`id` text PRIMARY KEY NOT NULL,
	`owner` text NOT NULL,
	`comparison_id` text NOT NULL,
	`checkpoint_id` text NOT NULL,
	`conclusion` text NOT NULL,
	`explanation` text NOT NULL,
	`created` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `idx_comparison_reviews_owner` ON `comparison_reviews` (`owner`,`comparison_id`);--> statement-breakpoint
CREATE TABLE `platform_comparisons` (
	`id` text PRIMARY KEY NOT NULL,
	`owner` text NOT NULL,
	`workspace_id` text NOT NULL,
	`android_run_id` text NOT NULL,
	`ios_run_id` text NOT NULL,
	`report_json` text NOT NULL,
	`created` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `idx_comparisons_owner_workspace` ON `platform_comparisons` (`owner`,`workspace_id`);--> statement-breakpoint
ALTER TABLE `test_cases` ADD `comparison_key` text DEFAULT '' NOT NULL;