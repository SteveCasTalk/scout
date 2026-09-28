ALTER TABLE `test_cases` ADD `assertion_text` text DEFAULT '' NOT NULL;--> statement-breakpoint
ALTER TABLE `runs` ADD `source` text DEFAULT 'Manual' NOT NULL;--> statement-breakpoint
ALTER TABLE `runs` ADD `trace_json` text DEFAULT '[]' NOT NULL;