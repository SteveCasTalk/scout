CREATE INDEX `idx_cases_owner_workspace` ON `test_cases` (`owner`,`workspace_id`);--> statement-breakpoint
CREATE INDEX `idx_runs_owner_workspace` ON `runs` (`owner`,`workspace_id`);