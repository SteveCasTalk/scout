ALTER TABLE `test_cases` ADD `project` text DEFAULT 'General' NOT NULL;--> statement-breakpoint
ALTER TABLE `runs` ADD `external_run_id` text;--> statement-breakpoint
CREATE INDEX `idx_runs_external_owner` ON `runs` (`owner`,`external_run_id`);