/* Reusable 5-bar CSS equalizer motif (spec §2.5).
   Bars dance via staggered `eq-bounce` keyframes defined in base.css;
   `prefers-reduced-motion` freezes them there too. Purely decorative.

   size  — 'sm' (history row) · 'md' (transport) · 'lg' (ProgressCard)
   tone  — 'gold' (default VU meters) · 'neon' (active accent)          */

type EqProps = {
  size?: 'sm' | 'md' | 'lg'
  tone?: 'gold' | 'neon'
  className?: string
}

export function Eq({ size = 'md', tone = 'gold', className }: EqProps) {
  const classes = [
    'eq',
    `eq--${size}`,
    tone === 'neon' ? 'eq--neon' : '',
    className ?? '',
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <span className={classes} aria-hidden="true">
      <span />
      <span />
      <span />
      <span />
      <span />
    </span>
  )
}
