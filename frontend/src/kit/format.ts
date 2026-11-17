/** Formatting helpers for the kit. Pure functions; a locale is always passed in, never read from the environment. */

/** "1.4 GB" from a byte count. */
export function bytes(n: number | null | undefined, locale = "en-US"): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return "–";
  const units = ["B", "kB", "MB", "GB", "TB"];
  let i = 0;
  let v = n;
  while (v >= 1000 && i < units.length - 1) {
    v /= 1000;
    i++;
  }
  return `${v.toLocaleString(locale, { maximumFractionDigits: v < 10 && i > 0 ? 1 : 0 })} ${units[i]}`;
}

/** A number for a table cell: grouped thousands, at most `digits` decimals. Non-numbers come back as text. */
export function number(v: unknown, locale = "en-US", digits = 4): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return v === null || v === undefined ? "" : String(v);
  return v.toLocaleString(locale, { maximumFractionDigits: digits });
}

/** RFC 4180: quote a field when it has a comma, quote or line break. */
export function toCsv(headers: string[], rows: unknown[][]): string {
  const cell = (v: unknown) => {
    const text = v === null || v === undefined ? "" : String(v);
    return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  return [headers, ...rows].map((row) => row.map(cell).join(",")).join("\r\n") + "\r\n";
}

/** Put text on the clipboard; resolves to whether it worked. */
export async function copy(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}
