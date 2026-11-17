import { useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import { number } from "./format";

/**
 * A grid for query results and table previews: thousands of rows, only those in view exist in
 * the page. Sticky header, numbers flush right, click a header to sort, a row menu through
 * `onRowMenu`. Rows are arrays in column order, as a database hands them over.
 *
 * Use it for data whose columns are not known when the panel is written. For a short list
 * with hand-picked columns, a plain `wb-table` reads better.
 */

export interface GridColumn {
  key: string;
  label?: string;
  /** The source's type name, shown as a tooltip; names containing INT, FLOAT, DOUBLE, DECIMAL are numeric. */
  type?: string;
  numeric?: boolean;
  width?: number;
}

export interface GridCell {
  row: unknown[];
  rowIndex: number;
  column: GridColumn;
  value: unknown;
}

interface Props {
  columns: GridColumn[];
  rows: unknown[][];
  rowHeight?: number;
  locale?: string;
  nullText?: string;
  label?: string;
  /** Called on right-click or the Menu key on a cell; open a context menu from it. */
  onRowMenu?: (event: MouseEvent, cell: GridCell) => void;
  /** The index (in `rows`) of the row to mark, and what a click on a row does. */
  selected?: number | null;
  onSelect?: (rowIndex: number) => void;
  empty?: string;
}

const NUMERIC = /INT|FLOAT|DOUBLE|DECIMAL|NUMERIC|REAL|BIGINT/i;
const OVERSCAN = 8;

const isNumeric = (c: GridColumn, rows: unknown[][], i: number) => c.numeric ?? (c.type ? NUMERIC.test(c.type) : rows.slice(0, 30).every((r) => r[i] === null || typeof r[i] === "number"));

export function DataGrid({ columns, rows, rowHeight = 22, locale = "en-US", nullText = "NULL", label = "Rows", onRowMenu, selected, onSelect, empty = "No rows." }: Props) {
  const viewport = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [height, setHeight] = useState(400);
  const [sort, setSort] = useState<{ index: number; descending: boolean } | null>(null);

  useEffect(() => {
    const el = viewport.current;
    if (!el) return;
    const observer = new ResizeObserver(() => setHeight(el.clientHeight));
    observer.observe(el);
    setHeight(el.clientHeight);
    return () => observer.disconnect();
  }, []);
  // A new result starts at the top, unsorted.
  const signature = columns.map((c) => c.key).join("\u0000");
  useEffect(() => {
    setSort(null);
    viewport.current?.scrollTo({ top: 0 });
  }, [signature, rows]);

  const numeric = useMemo(() => columns.map((c, i) => isNumeric(c, rows, i)), [columns, rows]);
  const show = (v: unknown, i: number) => (v === null || v === undefined ? null : numeric[i] ? number(v, locale) : typeof v === "boolean" ? String(v) : String(v));
  const widths = useMemo(
    () =>
      columns.map((c, i) => {
        if (c.width) return c.width;
        let chars = (c.label ?? c.key).length + 2;
        for (const r of rows.slice(0, 60)) chars = Math.max(chars, (show(r[i], i) ?? nullText).length);
        return Math.round(Math.min(420, Math.max(60, chars * 8.3 + 22)));
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [columns, rows, locale],
  );
  const total = widths.reduce((s, w) => s + w, 0);
  const order = useMemo(() => {
    const index = rows.map((_r, i) => i);
    if (!sort) return index;
    const { index: col, descending } = sort;
    return index.sort((a, b) => {
      const x = rows[a]![col];
      const y = rows[b]![col];
      const cmp = x === y ? 0 : x === null || x === undefined ? 1 : y === null || y === undefined ? -1 : typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y));
      return descending ? -cmp : cmp;
    });
  }, [rows, sort]);

  const first = Math.max(0, Math.floor(scrollTop / rowHeight) - OVERSCAN);
  const last = Math.min(order.length, Math.ceil((scrollTop + height) / rowHeight) + OVERSCAN);
  return (
    <div className="kit-grid" ref={viewport} onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)} role="table" aria-rowcount={rows.length + 1} aria-label={label}>
      <div className="kit-grid-head" role="row" style={{ width: total, height: rowHeight + 2 }}>
        {columns.map((c, i) => (
          <button
            key={c.key + i}
            role="columnheader"
            className="kit-grid-cell"
            data-numeric={numeric[i] || undefined}
            style={{ width: widths[i] }}
            title={c.type ? `${c.key}: ${c.type}` : c.key}
            aria-sort={sort?.index === i ? (sort.descending ? "descending" : "ascending") : undefined}
            onClick={() => (setSort(sort?.index === i ? (sort.descending ? null : { index: i, descending: true }) : { index: i, descending: false }), viewport.current?.scrollTo({ top: 0 }))}
          >
            {c.label ?? c.key}
            {sort?.index === i ? (sort.descending ? " ▾" : " ▴") : ""}
          </button>
        ))}
      </div>
      <div style={{ height: order.length * rowHeight, width: total, position: "relative" }}>
        {order.slice(first, last).map((rowIndex, n) => {
          const row = rows[rowIndex]!;
          return (
            <div
              key={rowIndex}
              role="row"
              aria-rowindex={first + n + 2}
              aria-selected={selected === rowIndex || undefined}
              className="kit-grid-row"
              style={{ top: (first + n) * rowHeight, height: rowHeight }}
              onClick={onSelect ? () => onSelect(rowIndex) : undefined}
            >
              {columns.map((c, i) => {
                const text = show(row[i], i);
                return (
                  <span
                    key={i}
                    role="cell"
                    className="kit-grid-cell"
                    data-numeric={numeric[i] || undefined}
                    data-null={text === null || undefined}
                    style={{ width: widths[i] }}
                    title={text !== null && text.length > 40 ? text : undefined}
                    onContextMenu={onRowMenu ? (e) => onRowMenu(e, { row, rowIndex, column: c, value: row[i] }) : undefined}
                  >
                    {text ?? nullText}
                  </span>
                );
              })}
            </div>
          );
        })}
      </div>
      {rows.length === 0 && <p className="kit-grid-empty">{empty}</p>}
    </div>
  );
}
