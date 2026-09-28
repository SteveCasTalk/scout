CREATE TABLE `test_cases` (
	`id` text PRIMARY KEY NOT NULL,
	`owner` text NOT NULL,
	`title` text NOT NULL,
	`platform` text NOT NULL,
	`suite` text NOT NULL,
	`goal` text NOT NULL,
	`preconditions` text NOT NULL,
	`steps` text NOT NULL,
	`expected` text NOT NULL,
	`revision` integer NOT NULL,
	`updated` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `idx_cases_owner` ON `test_cases` (`owner`);--> statement-breakpoint
CREATE TABLE `evidence` (
	`id` text PRIMARY KEY NOT NULL,
	`owner` text NOT NULL,
	`run_id` text NOT NULL,
	`name` text NOT NULL,
	`mime` text NOT NULL,
	`size` integer NOT NULL,
	`object_key` text NOT NULL,
	`created` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `idx_evidence_owner_run` ON `evidence` (`owner`,`run_id`);--> statement-breakpoint
CREATE TABLE `runs` (
	`id` text PRIMARY KEY NOT NULL,
	`owner` text NOT NULL,
	`case_id` text NOT NULL,
	`snapshot` text NOT NULL,
	`status` text NOT NULL,
	`build` text NOT NULL,
	`device` text NOT NULL,
	`notes` text NOT NULL,
	`created` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `idx_runs_owner` ON `runs` (`owner`);