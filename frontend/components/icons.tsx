// Plain-stroke icons drawn with `currentColor` so they stay monotone (match the
// button's text color and only tint on hover via CSS) instead of rendering as
// colorful platform emoji.
export function TrashIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path
        d="M2.5 4h11M6 4V2.5h4V4M5 4v9.5A1 1 0 0 0 6 14.5h4a1 1 0 0 0 1-1V4M6.5 7v4.5M9.5 7v4.5"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
