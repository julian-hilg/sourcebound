/**
 * Rendered slides of a deck, large and numbered, each with its title; one can be selected.
 * Use it where a person looks at slides to talk about them ("slide 3 needs a shorter title").
 * Props only: the images come in as addresses.
 */
export interface SlideImage {
  src: string;
  title: string;
  alt?: string;
}

export function SlideGrid({ slides, selected, onSelect, width = 360 }: { slides: SlideImage[]; selected: number | null; onSelect: (n: number) => void; width?: number }) {
  return (
    <ol className="kit-slides" style={{ gridTemplateColumns: `repeat(auto-fill, minmax(${Math.min(width, 520)}px, 1fr))` }}>
      {slides.map((s, i) => (
        <li key={s.src} className="kit-slide" aria-selected={selected === i + 1}>
          <button type="button" className="kit-slide-button" onClick={() => onSelect(i + 1)} title={`Slide ${i + 1}: ${s.title}`}>
            <img src={s.src} alt={s.alt ?? s.title} loading="lazy" />
            <span className="kit-slide-caption">
              <span className="kit-slide-no">{i + 1}</span>
              <span>{s.title}</span>
            </span>
          </button>
        </li>
      ))}
    </ol>
  );
}
