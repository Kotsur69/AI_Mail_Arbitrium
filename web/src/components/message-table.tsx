/**
 * Every classified message, newest first, each one openable down to its quote.
 *
 * The quote is the point of this view. A status without the sentence it rests
 * on is an assertion; with the sentence, a reviewer can agree or overrule in a
 * second or two, which is the whole economics of the review queue.
 *
 * Rows collapse by default because a table of expanded quotes is unscannable,
 * and a reviewer has to find the row before reading it.
 */

import { useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { ChevronDown, Paperclip, Quote as QuoteIcon } from 'lucide-react'

import type { Message } from '@/lib/api'
import { formatDateTime } from '@/lib/domain'
import { cn } from '@/lib/utils'
import { ReasonBadge, StatusBadge } from '@/components/status-badge'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

const EASE = [0.16, 1, 0.3, 1] as const
const STAGGER_LIMIT = 20

export function MessageTable({ messages }: { messages: Message[] }) {
  const [open, setOpen] = useState<string | null>(null)

  if (messages.length === 0) {
    return (
      <p className="px-4 py-10 text-center text-sm text-muted-foreground">
        Zadna wiadomosc nie pasuje do wybranych filtrow.
      </p>
    )
  }

  return (
    <ul className="divide-y">
      {messages.map((message, index) => (
        <MessageRow
          key={message.id}
          message={message}
          index={index}
          open={open === message.id}
          onToggle={() => setOpen(open === message.id ? null : message.id)}
        />
      ))}
    </ul>
  )
}

interface RowProps {
  message: Message
  index: number
  open: boolean
  onToggle: () => void
}

function MessageRow({ message, index, open, onToggle }: RowProps) {
  const queued = message.reviewReasons.length > 0

  return (
    <motion.li
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.2, delay: Math.min(index, STAGGER_LIMIT) * 0.015, ease: EASE }}
      className={cn('transition-colors', open && 'bg-muted/30')}
    >
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full cursor-pointer items-center gap-3 px-4 py-2.5 text-left
                   transition-colors hover:bg-muted/50 focus-visible:ring-[3px]
                   focus-visible:ring-ring focus-visible:outline-none"
      >
        {/* A queued row carries a warm rail down its left edge -- visible before
            any badge is read, and gone the moment the queue empties. */}
        <span
          className={cn(
            'h-8 w-0.5 shrink-0 rounded-full transition-colors',
            queued ? 'bg-highlight' : 'bg-transparent',
          )}
          aria-hidden
        />

        <span className="w-32 shrink-0">
          <StatusBadge status={message.status} />
        </span>

        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium">
            {message.subject || '(bez tematu)'}
          </span>
          <span className="block truncate font-mono text-xs text-muted-foreground">
            {message.sender}
          </span>
        </span>

        {message.attachmentsTotal > 0 && (
          <Tooltip>
            <TooltipTrigger asChild>
              <span
                className="hidden shrink-0 items-center gap-1 font-mono text-xs
                           text-muted-foreground sm:inline-flex"
              >
                <Paperclip className="size-3.5" aria-hidden />
                {message.attachmentsRead}/{message.attachmentsTotal}
              </span>
            </TooltipTrigger>
            <TooltipContent>
              Odczytano {message.attachmentsRead} z {message.attachmentsTotal} zalacznikow.
            </TooltipContent>
          </Tooltip>
        )}

        {queued && (
          <span className="hidden shrink-0 gap-1 lg:flex">
            {message.reviewReasons.map((reason) => (
              <ReasonBadge key={reason} reason={reason} />
            ))}
          </span>
        )}

        <span className="hidden w-36 shrink-0 text-right text-xs text-muted-foreground md:block">
          {formatDateTime(message.receivedAt)}
        </span>

        <ChevronDown
          className={cn(
            'size-4 shrink-0 text-muted-foreground transition-transform duration-200',
            open && 'rotate-180',
          )}
          aria-hidden
        />
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            key="detail"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            // Exit is quicker than enter: closing should feel like a dismissal,
            // not like waiting for the row to finish folding away.
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.22, ease: EASE }}
            className="overflow-hidden"
          >
            <Detail message={message} />
          </motion.div>
        )}
      </AnimatePresence>
    </motion.li>
  )
}

function Detail({ message }: { message: Message }) {
  return (
    <div className="grid gap-4 px-4 pt-1 pb-4 pl-9 md:grid-cols-[1fr_260px]">
      <div className="space-y-3">
        <div>
          <p className="mb-1 text-xs font-medium text-muted-foreground">Cytat z wiadomosci</p>
          {/* A plain quotation rule, in the border colour. The coloured accents
              on this row are the verdict and the review flag; a third one here
              would only compete with them. */}
          {message.evidence ? (
            <blockquote
              className="flex gap-2 rounded-md border-l-2 border-border bg-muted/50
                         px-3 py-2 text-sm"
            >
              <QuoteIcon className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" aria-hidden />
              <span className="italic">{message.evidence}</span>
            </blockquote>
          ) : (
            <p className="text-sm text-muted-foreground italic">Model nie podal cytatu.</p>
          )}
        </div>

        <div>
          <p className="mb-1 text-xs font-medium text-muted-foreground">Uzasadnienie</p>
          <p className="text-sm">{message.rationale || '—'}</p>
        </div>

        {message.reviewReasons.length > 0 && (
          <div>
            <p className="mb-1.5 text-xs font-medium text-muted-foreground">
              Dlaczego czeka na czlowieka
            </p>
            <div className="flex flex-wrap gap-1.5">
              {message.reviewReasons.map((reason) => (
                <ReasonBadge key={reason} reason={reason} />
              ))}
            </div>
          </div>
        )}
      </div>

      <dl className="space-y-1.5 text-xs">
        <Field label="Dostawca" value={message.supplier} mono />
        <Field label="Skrzynka" value={message.mailbox} />
        <Field label="Odebrano" value={formatDateTime(message.receivedAt)} />
        <Field label="Sklasyfikowano" value={formatDateTime(message.classifiedAt)} />
        <Field label="Model" value={message.model} mono />
        {message.attachmentStatus && (
          <div className="flex items-baseline justify-between gap-2 pt-0.5">
            <dt className="text-muted-foreground">Status zalacznika</dt>
            <dd>
              <StatusBadge status={message.attachmentStatus} />
            </dd>
          </div>
        )}
      </dl>
    </div>
  )
}

function Field({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <dt className="shrink-0 text-muted-foreground">{label}</dt>
      <dd className={cn('truncate text-right', mono && 'font-mono')}>{value}</dd>
    </div>
  )
}
