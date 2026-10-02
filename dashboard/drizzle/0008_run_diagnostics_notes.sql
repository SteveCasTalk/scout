ALTER TABLE `runs` ADD `device_info_json` text DEFAULT '{}' NOT NULL;
ALTER TABLE `runs` ADD `app_logs` text DEFAULT '' NOT NULL;
CREATE TABLE `review_notes` (
  `id` text PRIMARY KEY NOT NULL,
  `owner` text NOT NULL,
  `workspace_id` text NOT NULL,
  `target_type` text NOT NULL,
  `target_id` text NOT NULL,
  `body` text NOT NULL,
  `created` text NOT NULL,
  `updated` text NOT NULL
);
CREATE INDEX `idx_review_notes_owner_target` ON `review_notes` (`owner`,`target_type`,`target_id`);
