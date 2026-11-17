import { z } from "zod";
import type { DatabaseDriver, DatabaseSpec } from "./api";

/**
 * A database connection, field by field: the same rules as `databases.check` in the service, which
 * stays the authority (it checks again before anything is written). One schema for the form and for
 * the `connection.save` command. There is no password field: a password never enters a record.
 */
export const DRIVERS: Record<DatabaseDriver, { title: string; port?: number; auth?: ("sql" | "windows" | "none")[]; file?: boolean }> = {
  mssql: { title: "SQL Server", port: 1433, auth: ["sql", "windows"] },
  postgresql: { title: "PostgreSQL", port: 5432, auth: ["sql", "none"] },
  mysql: { title: "MySQL / MariaDB", port: 3306, auth: ["sql", "none"] },
  sqlite: { title: "SQLite file", file: true },
  duckdb: { title: "DuckDB file", file: true },
};
export const AUTH_LABEL = { sql: "User and password", windows: "Windows login (integrated)", none: "No login" } as const;
const HOST = /^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$/;
const ENV = /^[A-Za-z_][A-Za-z0-9_]*$/;

export const databaseSpec = z
  .object({
    driver: z.enum(["mssql", "postgresql", "mysql", "sqlite", "duckdb"]).describe("mssql, postgresql, mysql, sqlite or duckdb"),
    server: z.string().trim().max(253).optional().describe("Host name (client-server drivers)"),
    port: z.number("Enter a port number.").int().min(1, "A number from 1 to 65535.").max(65535, "A number from 1 to 65535.").optional(),
    database: z.string().trim().max(128).optional().describe("Database name (client-server drivers)"),
    auth: z.enum(["sql", "windows", "none"]).optional().describe("sql: user and password; windows: SQL Server only; none"),
    user: z.string().trim().max(128).optional(),
    password_env: z.string().trim().max(80).optional().describe("NAME of the environment variable with the password, for pipelines and jobs; never the password"),
    encrypt: z.boolean().optional(),
    trust_server_certificate: z.boolean().optional(),
    ssl_mode: z.enum(["disable", "prefer", "require", "verify-full"]).optional(),
    timeout: z.number("Enter a number of seconds.").int().min(1, "Seconds, from 1 to 120.").max(120, "Seconds, from 1 to 120.").optional(),
    path: z.string().trim().max(1000).optional().describe("The database file (sqlite, duckdb)"),
  })
  .superRefine((s, ctx) => {
    const d = DRIVERS[s.driver];
    const need = (path: string, message: string) => ctx.addIssue({ code: "custom", path: [path], message });
    if (d.file) {
      if (!s.path) need("path", "The database file.");
      return;
    }
    if (!s.server) need("server", "The server's host name.");
    else if (!HOST.test(s.server)) need("server", "A host name or address. An instance is reached through its port.");
    if (!s.database) need("database", "The database name.");
    const auth = s.auth ?? d.auth![0]!;
    if (!d.auth!.includes(auth)) need("auth", `For ${d.title}: ${d.auth!.map((a) => AUTH_LABEL[a]).join(" or ")}.`);
    if (auth === "sql" && !s.user) need("user", "A login with a password needs the user name.");
    if (s.password_env && !ENV.test(s.password_env)) need("password_env", "The NAME of an environment variable (letters, digits, _), never the password.");
  });

/** What the person types, as typed: numbers stay text until checked. */
export type Draft = { id: string; name: string } & Record<Exclude<keyof DatabaseSpec, "driver">, string | boolean> & { driver: DatabaseDriver };

export function blankDraft(driver: DatabaseDriver = "mssql"): Draft {
  const d = DRIVERS[driver];
  return {
    id: "", name: "", driver, server: "", port: d.port ? String(d.port) : "", database: "", auth: d.auth?.[0] ?? "none", user: "", password_env: "",
    encrypt: true, trust_server_certificate: false, ssl_mode: "prefer", timeout: "15", path: "",
  };
}

export function toDraft(id: string, name: string, spec: DatabaseSpec): Draft {
  const blank = blankDraft(spec.driver);
  const filled = Object.fromEntries(Object.entries(spec).map(([k, v]) => [k, typeof v === "number" ? String(v) : (v ?? "")]));
  return { ...blank, ...filled, id, name } as Draft;
}

/** The draft as a spec for its driver (fields of other drivers dropped), or one message per field. */
export function checkDraft(draft: Draft, isNew: boolean): { ok: true; spec: DatabaseSpec } | { ok: false; errors: Record<string, string> } {
  const errors: Record<string, string> = {};
  if (isNew && !/^[a-z][a-z0-9_]*$/.test(draft.id)) errors.id = "Lowercase letters, digits and _, starting with a letter (e.g. warehouse).";
  if (!draft.name.trim()) errors.name = "Give the connection a name.";
  const d = DRIVERS[draft.driver];
  const num = (v: string | boolean) => (String(v).trim() === "" ? undefined : Number(v));
  const candidate: Record<string, unknown> = { driver: draft.driver, timeout: num(draft.timeout) };
  if (d.file) candidate.path = draft.path;
  else {
    Object.assign(candidate, { server: draft.server, port: num(draft.port), database: draft.database, auth: draft.auth });
    if (draft.auth === "sql") Object.assign(candidate, { user: draft.user, password_env: draft.password_env || undefined });
    if (draft.driver === "mssql") Object.assign(candidate, { encrypt: Boolean(draft.encrypt), trust_server_certificate: Boolean(draft.trust_server_certificate) });
    if (draft.driver === "postgresql") candidate.ssl_mode = draft.ssl_mode;
  }
  const result = databaseSpec.safeParse(candidate);
  if (!result.success) for (const issue of result.error.issues) errors[String(issue.path[0])] ??= issue.message;
  if (Object.keys(errors).length || !result.success) return { ok: false, errors };
  return { ok: true, spec: result.data as DatabaseSpec };
}
