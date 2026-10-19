export function BrandMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 40 40" aria-hidden className={className} fill="none" stroke="currentColor" strokeWidth="2.4">
      <circle cx="20" cy="20" r="16" />
      <circle cx="20" cy="20" r="8" />
      <path d="M20 3 24 15 36 20 24 24 20 37 16 24 4 20 16 16Z" fill="currentColor" stroke="none" />
    </svg>
  );
}
