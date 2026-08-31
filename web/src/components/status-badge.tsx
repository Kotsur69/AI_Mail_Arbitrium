/**
 * The two badges the whole dashboard is built out of: a verdict, and a reason
 * a verdict is waiting for a person.
 *
 * Both pair an icon with a word. Neither relies on its colour to be read.
 */

import type { Status } from '@/lib/api'
import { STATUS_META, TONE_CLASS, reasonMeta } from '@/lib/domain'
import { cn } from '@/lib/utils'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

export function StatusBadge({ status, className }: { status: Status; className?: string }) {
  const meta = STATUS_META[status]
  const tone = TONE_CLASS[meta.tone]
  const Icon = meta.icon

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          className={cn(
            'inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium',
            'bg-current/8 ring-1 ring-inset transition-colors',
            tone.text,
            tone.ring,
            className,
          )}
        >
          <Icon className="size-3.5 shrink-0" aria-hidden />
          <span className="text-foreground/90">{meta.label}</span>
        </span>
      </TooltipTrigger>
      <TooltipContent className="max-w-64">{meta.description}</TooltipContent>
    </Tooltip>
  )
}

export function ReasonBadge({ reason }: { reason: string }) {
  const meta = reasonMeta(reason)
  const Icon = meta.icon

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          className={cn(
            'inline-flex cursor-help items-center gap-1 rounded px-1.5 py-0.5',
            'text-[11px] font-medium text-highlight ring-1 ring-inset ring-highlight/30',
            'bg-highlight/8 transition-colors hover:bg-highlight/15',
          )}
        >
          <Icon className="size-3 shrink-0" aria-hidden />
          {meta.label}
        </span>
      </TooltipTrigger>
      <TooltipContent className="max-w-64">{meta.hint}</TooltipContent>
    </Tooltip>
  )
}
