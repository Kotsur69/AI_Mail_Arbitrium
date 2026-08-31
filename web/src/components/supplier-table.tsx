/**
 * The per-supplier rollup -- the sheet anyone actually reads.
 *
 * It shows counts and no supplier-level verdict, exactly like the CSV. Whether
 * a later refusal overrides an earlier consent, or whether one consenting
 * mailbox speaks for a whole domain, is a business rule nobody has agreed yet;
 * inventing one here would put a number on the screen that the report does not
 * stand behind.
 *
 * Rows are ordered queue-first, so the domains needing a person come to the top.
 */

import { motion } from 'motion/react'
import { ChevronRight, TriangleAlert } from 'lucide-react'

import { STATUSES, type Supplier } from '@/lib/api'
import { STATUS_META, TONE_CLASS, formatCount, formatDateTime, share } from '@/lib/domain'
import { cn } from '@/lib/utils'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

const EASE = [0.16, 1, 0.3, 1] as const

// Beyond this many rows the staggered entrance stops being a cue and starts
// being a wait, so later rows appear together.
const STAGGER_LIMIT = 20

export function SupplierTable({
  suppliers,
  onSelect,
}: {
  suppliers: Supplier[]
  onSelect: (supplier: string) => void
}) {
  if (suppliers.length === 0) {
    return (
      <p className="px-4 py-10 text-center text-sm text-muted-foreground">
        Brak dostawcow do pokazania.
      </p>
    )
  }

  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className="min-w-56">Dostawca</TableHead>
            <TableHead className="w-20 text-right">Wiad.</TableHead>
            <TableHead className="min-w-40">Rozklad</TableHead>
            {STATUSES.map((status) => (
              <TableHead key={status} className="w-16 text-right">
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span className="cursor-help">{STATUS_META[status].label}</span>
                  </TooltipTrigger>
                  <TooltipContent>{STATUS_META[status].description}</TooltipContent>
                </Tooltip>
              </TableHead>
            ))}
            <TableHead className="w-28 text-right">Do weryf.</TableHead>
            <TableHead className="w-36 text-right">Ostatnia</TableHead>
            <TableHead className="w-8" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {suppliers.map((row, index) => (
            <motion.tr
              key={row.supplier}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{
                duration: 0.2,
                delay: Math.min(index, STAGGER_LIMIT) * 0.015,
                ease: EASE,
              }}
              onClick={() => onSelect(row.supplier)}
              tabIndex={0}
              role="button"
              aria-label={`Pokaz wiadomosci od ${row.supplier}`}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault()
                  onSelect(row.supplier)
                }
              }}
              className={cn(
                'group cursor-pointer border-b transition-colors',
                'hover:bg-muted/50 focus-visible:bg-muted/50 focus-visible:outline-none',
              )}
            >
              <TableCell className="font-medium">
                <span className="font-mono text-[13px]">{row.supplier}</span>
              </TableCell>
              <TableCell className="text-right font-mono">{formatCount(row.messages)}</TableCell>
              <TableCell>
                <MiniBar row={row} />
              </TableCell>
              {STATUSES.map((status) => (
                <TableCell
                  key={status}
                  className={cn(
                    'text-right font-mono',
                    row.statuses[status] > 0
                      ? TONE_CLASS[STATUS_META[status].tone].text
                      : 'text-muted-foreground/40',
                  )}
                >
                  {row.statuses[status] || '·'}
                </TableCell>
              ))}
              <TableCell className="text-right">
                {row.queued > 0 ? (
                  <span
                    className="inline-flex items-center gap-1 rounded bg-highlight/8 px-1.5 py-0.5
                               font-mono text-highlight ring-1 ring-inset ring-highlight/30"
                  >
                    <TriangleAlert className="size-3" aria-hidden />
                    {row.queued}
                  </span>
                ) : (
                  <span className="font-mono text-muted-foreground/40">·</span>
                )}
              </TableCell>
              <TableCell className="text-right text-xs text-muted-foreground">
                {formatDateTime(row.lastMessage)}
              </TableCell>
              <TableCell>
                <ChevronRight
                  className="size-4 text-muted-foreground/40 transition-transform duration-200
                             group-hover:translate-x-0.5 group-hover:text-foreground"
                  aria-hidden
                />
              </TableCell>
            </motion.tr>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

/** The supplier's replies as one proportional bar, so the eye sorts before the digits do. */
function MiniBar({ row }: { row: Supplier }) {
  return (
    <div className="flex h-1.5 w-full max-w-40 overflow-hidden rounded-full bg-muted">
      {STATUSES.map((status) => {
        const percent = share(row.statuses[status], row.messages)
        if (percent === 0) return null
        return (
          <div
            key={status}
            style={{ width: `${percent}%` }}
            className={cn('h-full', TONE_CLASS[STATUS_META[status].tone].bg)}
          />
        )
      })}
    </div>
  )
}
