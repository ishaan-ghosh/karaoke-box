/* Inline SVG icon set for Karaoke Box (spec §6).
   Every glyph draws with currentColor and scales from a single `size`
   prop, so callers control color via CSS `color` and size via `size`.
   Decorative by default (aria-hidden); pass aria-label to expose one. */
import type { ReactNode, SVGProps } from 'react'

type IconProps = { size?: number } & SVGProps<SVGSVGElement>

function LineIcon({
  size = 24,
  viewBox = '0 0 24 24',
  children,
  ...props
}: IconProps & { viewBox?: string; children: ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox={viewBox}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      {children}
    </svg>
  )
}

function SolidIcon({
  size = 24,
  viewBox = '0 0 24 24',
  children,
  ...props
}: IconProps & { viewBox?: string; children: ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox={viewBox}
      fill="currentColor"
      aria-hidden="true"
      {...props}
    >
      {children}
    </svg>
  )
}

/* Brand mark — a neon waveform, drawn to sit inside a rounded square. */
export function WaveMark({ size = 24, ...props }: IconProps) {
  return (
    <LineIcon size={size} viewBox="0 0 32 32" strokeWidth={2.1} {...props}>
      <path d="M3 16h3l2-8 4 16 4-22 4 26 4-17 2 5h3" />
    </LineIcon>
  )
}

export function PlayIcon({ size = 24, ...props }: IconProps) {
  return (
    <SolidIcon size={size} {...props}>
      <path d="M8 5.14v13.72a1 1 0 0 0 1.52.86l11.14-6.86a1 1 0 0 0 0-1.72L9.52 4.28A1 1 0 0 0 8 5.14Z" />
    </SolidIcon>
  )
}

export function PauseIcon({ size = 24, ...props }: IconProps) {
  return (
    <SolidIcon size={size} {...props}>
      <rect x="6" y="5" width="4" height="14" rx="1" />
      <rect x="14" y="5" width="4" height="14" rx="1" />
    </SolidIcon>
  )
}

export function DownloadIcon({ size = 24, ...props }: IconProps) {
  return (
    <LineIcon size={size} {...props}>
      <path d="M12 4v11" />
      <path d="M8 11.5 12 15.5 16 11.5" />
      <path d="M5 19.5h14" />
    </LineIcon>
  )
}

export function UploadIcon({ size = 24, ...props }: IconProps) {
  return (
    <LineIcon size={size} {...props}>
      <path d="M12 15.5v-11" />
      <path d="M8 8.5 12 4.5 16 8.5" />
      <path d="M5 19.5h14" />
    </LineIcon>
  )
}

export function NoteIcon({ size = 24, ...props }: IconProps) {
  return (
    <SolidIcon size={size} {...props}>
      <path d="M20 4.5a1 1 0 0 0-1.24-.97l-8 2A1 1 0 0 0 10 6.5v8.06A3.5 3.5 0 1 0 12 17.5V9.28l6-1.5v4.78A3.5 3.5 0 1 0 20 16V4.5Z" />
    </SolidIcon>
  )
}

export function CheckIcon({ size = 24, ...props }: IconProps) {
  return (
    <LineIcon size={size} strokeWidth={2.2} {...props}>
      <path d="M5 12.5 10 17.5 19 6.5" />
    </LineIcon>
  )
}

export function AlertIcon({ size = 24, ...props }: IconProps) {
  return (
    <LineIcon size={size} strokeWidth={2} {...props}>
      <path d="M12 3.5 22 20.5H2L12 3.5Z" />
      <path d="M12 10v4.5" />
      <path d="M12 17.8h.01" />
    </LineIcon>
  )
}

export function HouseIcon({ size = 24, ...props }: IconProps) {
  return (
    <LineIcon size={size} {...props}>
      <path d="M4 11 12 4l8 7" />
      <path d="M6 10v9h12v-9" />
      <path d="M10 19v-5h4v5" />
    </LineIcon>
  )
}

export function ShieldIcon({ size = 24, ...props }: IconProps) {
  return (
    <LineIcon size={size} {...props}>
      <path d="M12 3.5 19 6v5.5c0 4.4-2.9 7.6-7 9-4.1-1.4-7-4.6-7-9V6l7-2.5Z" />
      <path d="M9 12l2.2 2.2L15.5 10" />
    </LineIcon>
  )
}
