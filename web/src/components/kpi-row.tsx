/**
 * The block above the tables: how the campaign stands, in one glance.
 *
 * The cards are buttons. A number on a dashboard that cannot be opened is a
 * number a reviewer has to go and re-find by hand, so every count here filters
 * the table below it.
 *
 * Motion is limited to entrance, and to bars growing from nothing to their
 * share. Nothing loops, nothing moves once the data has settled.
 */

import type { ReactNode } from 'react'
import { motion } from 'motion/react'
import { Inbox, TriangleAlert } from 'lucide-react'

import { STATUSES, type Status, type TimelinePoint, type Totals } from '@/lib/api'
import { STATUS_META, TONE_CLASS, formatCount, formatDay, reasonMeta, share } from '@/lib/domain'
import { cn } from '@/lib/utils'
import { Card } from '@/components/ui/card'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

// One rhythm for the whole page: a short ease-out, staggered just enough that
// the row reads left to right rather than flashing in all at once.
const EASE = [0.16, 1, 0.3, 1] as const
const RISE = {
  hidden: { opacity: 0, y: 8 },
  shown: { opacity: 1, y: 0 },
}

interface KpiRowProps {
  totals: Totals
  active: Status | null
  reviewOnly: boolean
  onSelectStatus: (status: Status | null) => void
  onSelectReview: () => void
}

export function KpiRow({ totals, active, reviewOnly, onSelectStatus, onSelectReview }: KpiRowProps) {
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
      <KpiCard
        index={0}
        label="Wiadomosci"
        value={totals.messages}
        icon={<Inbox className="size-4" aria-hidden />}
        selected={active === null && !reviewOnly}
        onClick={() => onSelectStatus(null)}
        hint="Wszystkie sklasyfikowane wiadomosci."
      />

      {STATUSES.map((status, index) => {
        const meta = STATUS_META[status]
        const Icon = meta.icon
        return (
          <KpiCard
            key={status}
            index={index + 1}
            label={meta.label}
            value={totals[status]}
            percent={share(totals[status], totals.messages)}
            tone={TONE_CLASS[meta.tone].text}
            icon={<Icon className="size-4" aria-hidden />}
            selected={active === status && !reviewOnly}
            onClick={() => onSelectStatus(status)}
            hint={meta.description}
          />
        )
      })}

      <KpiCard
        index={5}
        label="Do weryfikacji"
        value={totals.review}
        percent={share(totals.review, totals.messages)}
        tone="text-highlight"
        icon={<TriangleAlert className="size-4" aria-hidden />}
        selected={reviewOnly}
        onClick={onSelectReview}
        hint="Wiadomosci, ktore pipeline oznaczyl do recznego sprawdzenia."
      />
    </div>
  )
}

interface KpiCardProps {
  index: number
  label: string
  value: number
  percent?: number
  tone?: string
  icon: ReactNode
  selected: boolean
  onClick: () => void
  hint: string
}

function KpiCard({
  index,
  label,
  value,
  percent,
  tone,
  icon,
  selected,
  onClick,
  hint,
}: KpiCardProps) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <motion.button
          type="button"
          variants={RISE}
          initial="hidden"
          animate="shown"
          transition={{ duration: 0.25, delay: index * 0.04, ease: EASE }}
          onClick={onClick}
          aria-pressed={selected}
          className={cn(
            'group cursor-pointer rounded-lg border bg-card p-3 text-left',
            'transition-colors duration-200 hover:border-primary/40 hover:bg-accent/40',
            'focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none',
            selected && 'border-primary/60 bg-accent/60',
          )}
        >
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <span className={cn('shrink-0', tone)}>{icon}</span>
            <span className="truncate">{label}</span>
          </div>
          <div className="mt-1.5 flex items-baseline gap-1.5">
            <span className={cn('font-mono text-2xl leading-none font-semibold', tone)}>
              {formatCount(value)}
            </span>
            {percent !== undefined && (
              <span className="text-xs text-muted-foreground">{percent.toFixed(0)}%</span>
            )}
          </div>
        </motion.button>
      </TooltipTrigger>
      <TooltipContent className="max-w-64">{hint}</TooltipContent>
    </Tooltip>
  )
}

/** One bar, four segments: the whole campaign's shape without a chart library. */
export function StatusDistribution({ totals }: { totals: Totals }) {
  if (totals.messages === 0) return null

  return (
    <div className="space-y-2">
      <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-muted">
        {STATUSES.map((status) => {
          const meta = STATUS_META[status]
          const percent = share(totals[status], totals.messages)
          if (percent === 0) return null
          return (
            <Tooltip key={status}>
              <TooltipTrigger asChild>
                <motion.div
                  initial={{ width: 0 }}
                  animate={{ width: `${percent}%` }}
                  transition={{ duration: 0.5, ease: EASE }}
                  className={cn('h-full cursor-help', TONE_CLASS[meta.tone].bg)}
                />
              </TooltipTrigger>
              <TooltipContent>
                {meta.label}: {formatCount(totals[status])} ({percent.toFixed(1)}%)
              </TooltipContent>
            </Tooltip>
          )
        })}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        {STATUSES.map((status) => {
          const meta = STATUS_META[status]
          return (
            <span key={status} className="inline-flex items-center gap-1.5">
              <span className={cn('size-2 rounded-full', TONE_CLASS[meta.tone].bg)} aria-hidden />
              {meta.label}
              <span className="font-mono text-foreground">{formatCount(totals[status])}</span>
            </span>
          )
        })}
      </div>
    </div>
  )
}

/**
 * Mail per day since the campaign opened, with the queued share stacked on top.
 *
 * Deliberately unlabelled on the x axis: at one bar per day the dates would be
 * unreadable, and the exact day is one hover away.
 */
export function ActivityStrip({ timeline }: { timeline: TimelinePoint[] }) {
  if (timeline.length === 0) {
    return <p className="text-xs text-muted-foreground">Brak wiadomosci z data odbioru.</p>
  }

  const peak = Math.max(...timeline.map((point) => point.messages), 1)

  return (
    <div className="flex h-28 items-end gap-[3px]" role="img" aria-label="Wiadomosci dziennie">
      {timeline.map((point, index) => {
        // A silent day gets a hairline on the baseline, not a stub bar: it has
        // to be visibly nothing, or the chart reads as one message that day.
        const height = point.messages === 0 ? 2 : Math.max(share(point.messages, peak), 8)
        return (
          <Tooltip key={point.day}>
            <TooltipTrigger asChild>
              <motion.div
                initial={{ scaleY: 0 }}
                animate={{ scaleY: 1 }}
                transition={{ duration: 0.3, delay: index * 0.012, ease: EASE }}
                style={{ height: point.messages === 0 ? `${height}px` : `${height}%` }}
                className={cn(
                  'flex min-w-[4px] flex-1 origin-bottom cursor-help flex-col justify-end',
                  'overflow-hidden rounded-[2px] transition-colors',
                  point.messages === 0
                    ? 'bg-border hover:bg-muted-foreground/40'
                    : 'bg-primary/30 hover:bg-primary/50',
                )}
              >
                {point.review > 0 && (
                  <div
                    style={{ height: `${share(point.review, point.messages)}%` }}
                    className="w-full bg-highlight/75"
                  />
                )}
              </motion.div>
            </TooltipTrigger>
            <TooltipContent>
              <span className="font-medium">{formatDay(point.day)}</span>
              {point.messages === 0
                ? ' — brak wiadomosci'
                : ` — ${point.messages} wiad.${point.review > 0 ? `, ${point.review} do weryfikacji` : ''}`}
            </TooltipContent>
          </Tooltip>
        )
      })}
    </div>
  )
}

/** Why the queue is as big as it is, ordered by how much each rule contributes. */
export function ReviewReasons({
  reasons,
  total,
}: {
  reasons: Record<string, number>
  total: number
}) {
  const entries = Object.entries(reasons)
  if (entries.length === 0) {
    return <p className="text-xs text-muted-foreground">Nic nie czeka na weryfikacje.</p>
  }

  return (
    <ul className="space-y-2">
      {entries.map(([reason, count], index) => {
        const meta = reasonMeta(reason)
        const Icon = meta.icon
        return (
          <li key={reason} className="space-y-1">
            <div className="flex items-center gap-2 text-xs">
              <Icon className="size-3.5 shrink-0 text-highlight" aria-hidden />
              <span className="flex-1 truncate">{meta.label}</span>
              <span className="font-mono text-muted-foreground">{formatCount(count)}</span>
            </div>
            <div className="h-1 w-full overflow-hidden rounded-full bg-muted">
              <motion.div
                initial={{ width: 0 }}
                animate={{ width: `${share(count, total)}%` }}
                transition={{ duration: 0.45, delay: 0.05 + index * 0.05, ease: EASE }}
                className="h-full rounded-full bg-highlight/70"
              />
            </div>
          </li>
        )
      })}
    </ul>
  )
}

export function CardShell({
  title,
  action,
  children,
  className,
}: {
  title: string
  action?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <Card className={cn('gap-3 p-4', className)}>
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">{title}</h2>
        {action}
      </div>
      {children}
    </Card>
  )
}
