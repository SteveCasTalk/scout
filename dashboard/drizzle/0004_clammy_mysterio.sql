CREATE TABLE `workspaces` (
	`id` text PRIMARY KEY NOT NULL,
	`owner` text NOT NULL,
	`name` text NOT NULL,
	`created` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `idx_workspaces_owner` ON `workspaces` (`owner`);--> statement-breakpoint
ALTER TABLE `test_cases` ADD `workspace_id` text DEFAULT '' NOT NULL;--> statement-breakpoint
ALTER TABLE `runs` ADD `workspace_id` text DEFAULT '' NOT NULL;
--> statement-breakpoint
INSERT INTO `workspaces` (`id`, `owner`, `name`, `created`)
SELECT lower(hex(randomblob(16))), `owner`, `name`, MIN(`created`)
FROM (
  SELECT `owner`, COALESCE(NULLIF(trim(`project`), ''), 'General') AS `name`, `updated` AS `created` FROM `test_cases`
  UNION ALL
  SELECT `owner`, COALESCE(NULLIF(trim(json_extract(`snapshot`, '$.project')), ''), 'General') AS `name`, `created` FROM `runs`
)
GROUP BY `owner`, `name`;
--> statement-breakpoint
UPDATE `test_cases` SET `workspace_id` = (
  SELECT `workspaces`.`id` FROM `workspaces`
  WHERE `workspaces`.`owner` = `test_cases`.`owner`
    AND `workspaces`.`name` = COALESCE(NULLIF(trim(`test_cases`.`project`), ''), 'General')
  LIMIT 1
);
--> statement-breakpoint
UPDATE `runs` SET `workspace_id` = (
  SELECT COALESCE(
    (SELECT `test_cases`.`workspace_id` FROM `test_cases` WHERE `test_cases`.`id` = `runs`.`case_id` AND `test_cases`.`owner` = `runs`.`owner` LIMIT 1),
    (SELECT `workspaces`.`id` FROM `workspaces` WHERE `workspaces`.`owner` = `runs`.`owner` AND `workspaces`.`name` = COALESCE(NULLIF(trim(json_extract(`runs`.`snapshot`, '$.project')), ''), 'General') LIMIT 1)
  )
);
--> statement-breakpoint
