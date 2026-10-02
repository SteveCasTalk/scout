CREATE TABLE `checkpoint_reviews` (
  `id` text PRIMARY KEY NOT NULL,
  `owner` text NOT NULL,
  `workspace_id` text NOT NULL,
  `run_id` text NOT NULL,
  `checkpoint_id` text NOT NULL,
  `original_verdict` text NOT NULL,
  `decision` text NOT NULL,
  `explanation` text NOT NULL,
  `created` text NOT NULL
);
CREATE INDEX `idx_checkpoint_reviews_owner_run` ON `checkpoint_reviews` (`owner`,`run_id`);
