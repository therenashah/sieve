// Sieve's mark: a mesh/net inside a ring, echoing what the product actually does --
// filtering candidates through a set of criteria. Uses currentColor so it inherits
// whatever text color its container already has (white on the navbar/login hero).
export default function SieveLogo({ size = 16 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="9.5" stroke="currentColor" strokeWidth="1.5" />
      <g clipPath="url(#sieve-logo-clip)" stroke="currentColor" strokeWidth="1" strokeLinecap="round" opacity="0.9">
        <path d="M3 8.5H21M3 12H21M3 15.5H21" />
        <path d="M8.5 3V21M12 3V21M15.5 3V21" />
      </g>
      <defs>
        <clipPath id="sieve-logo-clip">
          <circle cx="12" cy="12" r="9.5" />
        </clipPath>
      </defs>
    </svg>
  );
}
