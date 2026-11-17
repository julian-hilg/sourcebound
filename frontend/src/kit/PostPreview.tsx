import { useState, type ReactNode } from "react";

/**
 * How a post will look in a feed: author line, text cut after a few lines with "…more",
 * images or document pages as a carousel. It approximates a professional network's feed card;
 * it is a preview for judging length and the first lines, not a pixel copy of any network.
 * Use wherever text and images are prepared here and published elsewhere.
 */

export interface PreviewImage {
  src: string;
  alt: string;
}

interface Props {
  author: string;
  headline?: string;
  /** Shown under the headline, e.g. "Scheduled for 2026-11-20 08:30" or "Draft". */
  meta?: string;
  text: string;
  /** Lines of text visible before "…more" (the feed shows about three). */
  visibleLines?: number;
  images?: PreviewImage[];
  /** For a carousel of document pages: the title shown under the pages. */
  documentTitle?: string;
  /** Characters used and allowed; over the limit is marked. */
  characters?: number;
  limit?: number;
  footer?: ReactNode;
  width?: number;
}

const initials = (name: string) =>
  name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]!.toUpperCase())
    .join("") || "?";

export function PostPreview({ author, headline, meta, text, visibleLines = 3, images = [], documentTitle, characters, limit, footer, width = 520 }: Props) {
  const [open, setOpen] = useState(false);
  const [page, setPage] = useState(0);
  const at = Math.min(page, Math.max(0, images.length - 1));
  const over = characters !== undefined && limit !== undefined && characters > limit;
  return (
    <article className="kit-post" style={{ maxWidth: width }} aria-label="Post preview">
      <header>
        <span className="kit-post-avatar" aria-hidden>
          {initials(author)}
        </span>
        <span className="kit-post-who">
          <strong>{author || "Author"}</strong>
          {headline && <span className="wb-dim">{headline}</span>}
          {meta && <span className="wb-dim">{meta}</span>}
        </span>
      </header>
      <div className="kit-post-text" data-open={open || undefined} style={open ? undefined : { WebkitLineClamp: visibleLines }}>
        {text || <span className="wb-dim">No text yet.</span>}
      </div>
      {text && (
        <button className="kit-post-more" onClick={() => setOpen(!open)}>
          {open ? "show less" : "…more"}
        </button>
      )}
      {images.length > 0 && (
        <figure className="kit-post-media">
          <img src={images[at]!.src} alt={images[at]!.alt} />
          {images.length > 1 && (
            <figcaption>
              <button className="wb-button" disabled={at === 0} onClick={() => setPage(at - 1)} aria-label="Previous page">
                ‹
              </button>
              <span className="wb-num">
                {documentTitle ? `${documentTitle} · ` : ""}
                {at + 1} / {images.length}
              </span>
              <button className="wb-button" disabled={at === images.length - 1} onClick={() => setPage(at + 1)} aria-label="Next page">
                ›
              </button>
            </figcaption>
          )}
        </figure>
      )}
      <footer>
        {characters !== undefined && (
          <span className={over ? "wb-warn" : "wb-dim"}>
            {characters.toLocaleString("en-US")}
            {limit !== undefined ? ` of ${limit.toLocaleString("en-US")}` : ""} characters{over ? ": too long" : ""}
          </span>
        )}
        {footer}
      </footer>
    </article>
  );
}
