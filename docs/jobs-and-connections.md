# Jobs, SQL and MCP servers

## Jobs: tables that stay current

A source without an API becomes a table that stays current, a pseudo-API:

1. A **pipeline** (`pipelines/<name>/pipeline.py`, with fixture tests) fetches through
   `sourcebound.fetch.Fetcher`, parses, validates against a contract and upserts into a lake
   table. Design for few requests: one page, many rows.
2. A **job** runs the pipeline on a schedule.
3. Projects and apps read the table like any other (`lake.read`, SQL), with snapshots, so a
   result still records which version it used.

```sh
sb job add ecb_fx --run "pipelines/ecb_fx/pipeline.py" --every 1d --table market.ecb_fx_daily --source ecb_data_portal
sb job list                 # schedule, last run, what is due
sb job run ecb_fx           # now
sb job run --due            # everything that is due; this is what the scheduler calls
sb job log
sb job schedule             # the line for cron, launchd or Task Scheduler
```

- Sourcebound runs no background service. The system's scheduler calls `sb job run --due`
  every few minutes; jobs that are not due are skipped.
- A job is a file in `<registry>/jobs/<id>.yaml` (`run`, `every`, `enabled`, `table`,
  `source`, `timeout_minutes`). The person adds and edits jobs; an agent proposes them.
- The fetcher's rules hold unchanged: the interval per host, robots.txt, no retries after a
  refusal. When a host is stopped the pipeline fails, the job records the failure, and it
  stays failed until the person has looked and run `sb unblock`.
- `every` is how often the job may run, not how often a host is asked: keep it no shorter than
  the source changes.

## Read-only SQL

```sh
sb sql lake "SELECT currency, max(date) FROM market.ecb_fx_daily GROUP BY 1"
sb sql warehouse "SELECT TOP 20 * FROM dbo.Orders"       # a registered database source
```

One statement that reads (SELECT, WITH, SHOW, DESCRIBE, EXPLAIN); anything else is refused
before it reaches the database. This is a look at the data: nothing is archived, no lineage
is recorded. To build a table from a database, use `sourcebound.sources.query` in a pipeline,
which archives the extract and the query text.

A database source is a register entry with a `database:` block: SQL Server, PostgreSQL,
MySQL / MariaDB, or a SQLite or DuckDB file. Make one in the web view (Connections panel,
"New database connection…": a form like the Werkbank starter's, with Test connection) or here:

```sh
sb datasource add warehouse --name "Order warehouse" --driver mssql --server sql-01 --database Orders --auth windows
sb datasource add shop --name "Shop" --driver postgresql --server db-01 --database shop --auth sql --user reader --password-env SHOP_PW
sb datasource add local --name "Local copy" --driver duckdb --path D:/data/warehouse.duckdb
sb datasource set warehouse --trust-server-certificate     # change a field
sb datasource test warehouse                               # connects and prints the server's version
sb datasource rm warehouse                                 # only while nothing was read from it
uv sync --extra sql                                        # SQL Server, PostgreSQL, MySQL (connectorx)
```

The password is never in a file. It is typed once per session in the web view and held in the
memory of `sb ui`, or read from the environment variable `password_env` names (for pipelines
and jobs); `sb datasource test` asks for it in a terminal. An older entry with
`connection_env:` (a whole URI in an environment variable) keeps working.

The guard is a second line of defence, not the first: give the account behind the URI read
permissions only.

## MCP servers

Agents reach some systems through MCP servers. The register keeps them in one place; a
project links the ones it needs.

```sh
sb mcp add warehouse --command "npx -y @acme/warehouse-mcp --read-only" --env WAREHOUSE_TOKEN
sb mcp add docs --url https://mcp.example.org/mcp
sb mcp list                 # with whether each environment variable is set
sb mcp link [NAME ...]      # writes .mcp.json of the current project; Claude Code asks before first use
sb mcp rm NAME
```

- The register holds names of environment variables, never values; `.mcp.json` refers to them
  as `${NAME}`.
- An MCP server of a data provider is also documentation: archive its tool list with
  `sb datasource docs ID tools.json`.
- MCP is for agents to look things up. Data that a result rests on still goes through a
  pipeline into the lake.
