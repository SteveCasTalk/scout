CREATE TABLE `case_revisions` (
	`owner` text NOT NULL,
	`workspace_id` text NOT NULL,
	`case_id` text NOT NULL,
	`revision` integer NOT NULL,
	`snapshot_json` text NOT NULL,
	`created` text NOT NULL,
	PRIMARY KEY(`owner`, `case_id`, `revision`)
);
--> statement-breakpoint
CREATE INDEX `idx_case_revisions_owner_workspace` ON `case_revisions` (`owner`,`workspace_id`,`case_id`);