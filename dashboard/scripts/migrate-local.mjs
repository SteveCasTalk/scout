// Applies pending drizzle/*.sql migrations to the local development D1 database.
//
// Applied migrations are recorded in a `_scout_migrations` table inside the same
// database, so the script is safe to rerun. Databases created before this script
// existed have no record: pass `--baseline <migration>` once to mark everything
// up to and including that file as already applied.
//
//   npm run db:migrate
//   npm run db:migrate -- --status
//   npm run db:migrate -- --baseline 0015_eminent_prodigy
import { spawnSync } from "node:child_process";
import { existsSync, readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = fileURLToPath(new URL("../", import.meta.url));
const migrationsDir = path.join(projectRoot, "drizzle");
const wranglerConfig = "dist/server/wrangler.json";
const ledger = "_scout_migrations";

function usage(message) {
  if (message) console.error(`error: ${message}\n`);
  console.error("usage: node scripts/migrate-local.mjs [--status] [--baseline <migration>] [--persist-to <dir>]");
  process.exit(message ? 2 : 0);
}

const options = { status: false, baseline: null, persistTo: ".wrangler/state" };
const argv = process.argv.slice(2);
for (let index = 0; index < argv.length; index += 1) {
  const arg = argv[index];
  if (arg === "--status") options.status = true;
  else if (arg === "--baseline") options.baseline = argv[++index] ?? usage("--baseline needs a migration name");
  else if (arg === "--persist-to") options.persistTo = argv[++index] ?? usage("--persist-to needs a directory");
  else if (arg === "--help" || arg === "-h") usage();
  else usage(`unknown argument ${arg}`);
}

if (!existsSync(path.join(projectRoot, wranglerConfig))) {
  console.error(`error: ${wranglerConfig} is missing. Run \`npm run build\` first.`);
  process.exit(1);
}

function wrangler(args) {
  const result = spawnSync(
    process.execPath,
    [
      "--import", "./scripts/sites-env.mjs",
      "./node_modules/wrangler/bin/wrangler.js",
      "d1", "execute", "DB", "--local",
      "--config", wranglerConfig,
      "--persist-to", options.persistTo,
      ...args,
    ],
    { cwd: projectRoot, encoding: "utf8" },
  );
  if (result.status !== 0) {
    throw new Error(`wrangler failed (${args.join(" ")}):\n${result.stderr || result.stdout}`);
  }
  return result.stdout;
}

function query(sql) {
  const output = wrangler(["--json", "--command", sql]);
  return JSON.parse(output.slice(output.indexOf("[")))[0].results;
}

const sqlString = (value) => `'${value.replaceAll("'", "''")}'`;
const record = (name) =>
  wrangler(["--command", `INSERT INTO ${ledger} (name, applied_at) VALUES (${sqlString(name)}, ${sqlString(new Date().toISOString())})`]);

const migrations = readdirSync(migrationsDir)
  .filter((file) => /^\d{4}_.+\.sql$/.test(file))
  .sort()
  .map((file) => file.replace(/\.sql$/, ""));

wrangler(["--command", `CREATE TABLE IF NOT EXISTS ${ledger} (name TEXT PRIMARY KEY NOT NULL, applied_at TEXT NOT NULL)`]);
const applied = new Set(query(`SELECT name FROM ${ledger}`).map((row) => row.name));
const hasSchema = query("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'test_cases'").length > 0;

if (options.baseline) {
  const baseline = options.baseline.replace(/\.sql$/, "");
  const end = migrations.indexOf(baseline);
  if (end === -1) usage(`unknown migration ${baseline}; expected one of drizzle/*.sql`);
  for (const name of migrations.slice(0, end + 1)) {
    if (!applied.has(name)) {
      record(name);
      applied.add(name);
      console.log(`marked  ${name}`);
    }
  }
}

const pending = migrations.filter((name) => !applied.has(name));

if (options.status) {
  for (const name of migrations) console.log(`${applied.has(name) ? "applied" : "pending"}  ${name}`);
  process.exit(0);
}

if (applied.size === 0 && hasSchema) {
  console.error(
    "error: this database already has dashboard tables but no migration record.\n" +
      "It was migrated by hand before this script existed. Mark the migrations it already has, then rerun:\n\n" +
      `  npm run db:migrate -- --baseline ${migrations.at(-1)}\n\n` +
      "Use an earlier name if the database is behind; the dashboard README lists what each migration adds.",
  );
  process.exit(1);
}

if (pending.length === 0) {
  console.log(`Local database is up to date (${migrations.length} migrations).`);
  process.exit(0);
}

for (const name of pending) {
  console.log(`apply   ${name}`);
  wrangler(["--file", path.join("drizzle", `${name}.sql`)]);
  record(name);
}
console.log(`Applied ${pending.length} migration(s).`);
