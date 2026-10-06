CREATE TABLE `case_authoring_requests` (
	`owner` text NOT NULL,
	`workspace_id` text NOT NULL,
	`request_id` text NOT NULL,
	`payload_hash` text NOT NULL,
	`claim` text NOT NULL,
	`response_json` text NOT NULL,
	`created` text NOT NULL,
	PRIMARY KEY(`owner`, `workspace_id`, `request_id`)
);
--> statement-breakpoint
ALTER TABLE `test_cases` ADD `execution_json` text DEFAULT 'null' NOT NULL;