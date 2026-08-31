/**
 * The dashboard: what the pipeline has concluded, and what still needs a person.
 *
 * All filter state lives here and is passed down, so the KPI cards, the
 * supplier rollup and the message list can never disagree about what is being
 * shown -- clicking a count, a domain or a tab all move the same three values.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { Database, Search, X } from 'lucide-react'

import {
  fetchMessages,
  fetchOverview,
  fetchSuppliers,
  type Message,
  type Overview,
  type Status,
  type Supplier,
} from '@/lib/api'
import { STATUS_META, formatCount } from '@/lib/domain'
import { cn } from '@/lib/utils'
import { AppHeader } from '@/components/app-header'
import {
  ActivityStrip,
  CardShell,
  KpiRow,
  ReviewReasons,
  StatusDistribution,
} from '@/components/kpi-row'
import { MessageTable } from '@/components/message-table'
import { SupplierTable } from '@/components/supplier-table'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { TooltipProvider } from '@/components/ui/tooltip'

// Long enough that typing a supplier name is one query rather than eleven,
// short enough that the table still feels like it is following along.
const SEARCH_DEBOUNCE_MS = 250

type Tab = 'dostawcy' | 'wiadomosci'

interface ActiveFilter {
  key: string
  label: string
  clear: () => void
}

export default function App() {
  const [mailbox, setMailbox] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('dostawcy')

  const [status, setStatus] = useState<Status | null>(null)
  const [reviewOnly, setReviewOnly] = useState(false)
  const [supplier, setSupplier] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [debounced, setDebounced] = useState('')

  const [overview, setOverview] = useState<Overview | null>(null)
  const [suppliers, setSuppliers] = useState<Supplier[]>([])
  const [messages, setMessages] = useState<Message[]>([])
  const [messageCount, setMessageCount] = useState(0)

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [reloadToken, setReloadToken] = useState(0)

  const refresh = useCallback(() => setReloadToken((token) => token + 1), [])

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(search), SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [search])

  // The overview and the rollup depend only on the mailbox, so changing a
  // status filter does not re-fetch either of them.
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    Promise.all([
      fetchOverview(mailbox, controller.signal),
      fetchSuppliers(mailbox, controller.signal),
    ])
      .then(([nextOverview, nextSuppliers]) => {
        setOverview(nextOverview)
        setSuppliers(nextSuppliers)
        setError(null)
      })
      .catch((cause: Error) => {
        if (cause.name !== 'AbortError') setError(cause.message)
      })
      .finally(() => setLoading(false))
    return () => controller.abort()
  }, [mailbox, reloadToken])

  useEffect(() => {
    const controller = new AbortController()
    fetchMessages({ mailbox, status, supplier, review: reviewOnly, q: debounced }, controller.signal)
      .then((page) => {
        setMessages(page.items)
        setMessageCount(page.total)
      })
      .catch((cause: Error) => {
        if (cause.name !== 'AbortError') setError(cause.message)
      })
    return () => controller.abort()
  }, [mailbox, status, supplier, reviewOnly, debounced, reloadToken])

  const selectStatus = useCallback((next: Status | null) => {
    setStatus(next)
    setReviewOnly(false)
    setTab('wiadomosci')
  }, [])

  const selectReview = useCallback(() => {
    setStatus(null)
    setReviewOnly(true)
    setTab('wiadomosci')
  }, [])

  const selectSupplier = useCallback((next: string) => {
    setSupplier(next)
    setTab('wiadomosci')
  }, [])

  const clearFilters = useCallback(() => {
    setStatus(null)
    setReviewOnly(false)
    setSupplier(null)
    setSearch('')
  }, [])

  const activeFilters = useMemo<ActiveFilter[]>(() => {
    const filters: ActiveFilter[] = []
    if (status) {
      filters.push({ key: 'status', label: STATUS_META[status].label, clear: () => setStatus(null) })
    }
    if (reviewOnly) {
      filters.push({ key: 'review', label: 'Do weryfikacji', clear: () => setReviewOnly(false) })
    }
    if (supplier) {
      filters.push({ key: 'supplier', label: supplier, clear: () => setSupplier(null) })
    }
    if (debounced) {
      filters.push({ key: 'q', label: `"${debounced}"`, clear: () => setSearch('') })
    }
    return filters
  }, [status, reviewOnly, supplier, debounced])

  if (loading && overview === null) {
    return <BootSkeleton />
  }

  if (overview && !overview.dbPresent) {
    return <EmptyState path={overview.dbPath} />
  }

  if (!overview) {
    return <ErrorState message={error ?? 'Nie udalo sie polaczyc z API.'} onRetry={refresh} />
  }

  return (
    <TooltipProvider delayDuration={200}>
      <div className="min-h-dvh">
        <AppHeader
          mailboxes={overview.mailboxes}
          mailbox={mailbox}
          campaign={overview.campaign}
          models={overview.models}
          lastClassifiedAt={overview.lastClassifiedAt}
          loading={loading}
          onMailboxChange={setMailbox}
          onRefresh={refresh}
        />

        <main className="mx-auto max-w-[1600px] space-y-3 p-4">
          {error && <ErrorBanner message={error} onRetry={refresh} />}

          <KpiRow
            totals={overview.totals}
            active={status}
            reviewOnly={reviewOnly}
            onSelectStatus={selectStatus}
            onSelectReview={selectReview}
          />

          <div className="grid gap-3 lg:grid-cols-[2fr_1fr]">
            <CardShell
              title="Aktywnosc dzienna"
              action={
                <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
                  <span className="size-2 rounded-full bg-highlight/75" aria-hidden />
                  do weryfikacji
                </span>
              }
            >
              <ActivityStrip timeline={overview.timeline} />
              <StatusDistribution totals={overview.totals} />
            </CardShell>

            <CardShell title="Kolejka weryfikacji">
              <ReviewReasons reasons={overview.reviewReasons} total={overview.totals.messages} />
            </CardShell>
          </div>

          <Tabs value={tab} onValueChange={(value) => setTab(value as Tab)}>
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <TabsList>
                <TabsTrigger value="dostawcy" className="cursor-pointer">
                  Dostawcy
                  <span className="ml-1.5 font-mono text-xs text-muted-foreground">
                    {formatCount(suppliers.length)}
                  </span>
                </TabsTrigger>
                <TabsTrigger value="wiadomosci" className="cursor-pointer">
                  Wiadomosci
                  <span className="ml-1.5 font-mono text-xs text-muted-foreground">
                    {formatCount(messageCount)}
                  </span>
                </TabsTrigger>
              </TabsList>

              <div className="relative ml-auto w-full sm:w-72">
                <Search
                  className="pointer-events-none absolute top-1/2 left-2.5 size-4
                             -translate-y-1/2 text-muted-foreground"
                  aria-hidden
                />
                <Input
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  onFocus={() => setTab('wiadomosci')}
                  placeholder="Szukaj w nadawcy, temacie, cytacie…"
                  aria-label="Szukaj w wiadomosciach"
                  className="pl-8"
                />
              </div>
            </div>

            <AnimatePresence initial={false}>
              {activeFilters.length > 0 && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  transition={{ duration: 0.18 }}
                  className="mb-2 flex flex-wrap items-center gap-1.5 overflow-hidden"
                >
                  <span className="text-xs text-muted-foreground">Filtry:</span>
                  {activeFilters.map((filter) => (
                    <button
                      key={filter.key}
                      type="button"
                      onClick={filter.clear}
                      className="inline-flex cursor-pointer items-center gap-1 rounded-md border
                                 bg-card px-2 py-0.5 text-xs transition-colors hover:bg-accent"
                    >
                      {filter.label}
                      <X className="size-3 text-muted-foreground" aria-hidden />
                    </button>
                  ))}
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={clearFilters}
                    className="h-6 cursor-pointer px-2 text-xs"
                  >
                    Wyczysc
                  </Button>
                </motion.div>
              )}
            </AnimatePresence>

            <Card className="overflow-hidden p-0">
              <TabsContent value="dostawcy" className="m-0">
                <SupplierTable suppliers={suppliers} onSelect={selectSupplier} />
              </TabsContent>
              <TabsContent value="wiadomosci" className="m-0">
                <MessageTable messages={messages} />
              </TabsContent>
            </Card>
          </Tabs>
        </main>
      </div>
    </TooltipProvider>
  )
}

function BootSkeleton() {
  return (
    <div className="mx-auto max-w-[1600px] space-y-3 p-4">
      <Skeleton className="h-12 w-full" />
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        {Array.from({ length: 6 }).map((_, index) => (
          <Skeleton key={index} className="h-[74px]" />
        ))}
      </div>
      <Skeleton className="h-40 w-full" />
      <Skeleton className="h-64 w-full" />
    </div>
  )
}

/**
 * No database yet. This is the expected first run, not a failure, so it says
 * what to type rather than what went wrong.
 */
function EmptyState({ path }: { path: string }) {
  return (
    <div className="grid min-h-dvh place-items-center p-6">
      <Card className="max-w-lg gap-4 p-6 text-center">
        <div className="mx-auto grid size-11 place-items-center rounded-lg bg-muted">
          <Database className="size-5 text-muted-foreground" aria-hidden />
        </div>
        <div className="space-y-1.5">
          <h1 className="text-lg font-semibold">Brak bazy werdyktow</h1>
          <p className="text-sm text-muted-foreground">
            Nie znaleziono pliku <code className="font-mono text-foreground">{path}</code>. Uruchom
            analize albo zaladuj dane przykladowe, zeby zobaczyc dashboard.
          </p>
        </div>
        <div className="space-y-2 text-left">
          <CommandHint
            label="Dane przykladowe"
            command=".venv/Scripts/python.exe scripts/seed_demo.py"
          />
          <CommandHint
            label="Prawdziwa analiza"
            command=".venv/Scripts/python.exe scripts/analyze_mailbox.py --all --db data/arbitrium.db"
          />
        </div>
      </Card>
    </div>
  )
}

function CommandHint({ label, command }: { label: string; command: string }) {
  return (
    <div>
      <p className="mb-1 text-xs font-medium text-muted-foreground">{label}</p>
      <pre className="overflow-x-auto rounded-md bg-muted px-3 py-2 font-mono text-xs">
        {command}
      </pre>
    </div>
  )
}

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="grid min-h-dvh place-items-center p-6">
      <Card className="max-w-md gap-3 p-6 text-center">
        <h1 className="text-lg font-semibold">Brak polaczenia z API</h1>
        <p className="text-sm text-muted-foreground">{message}</p>
        <p className="text-xs text-muted-foreground">
          Sprawdz, czy dziala <code className="font-mono">scripts/serve_dashboard.py</code>.
        </p>
        <Button onClick={onRetry} className="cursor-pointer">
          Sprobuj ponownie
        </Button>
      </Card>
    </div>
  )
}

function ErrorBanner({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div
      role="alert"
      className={cn(
        'flex items-center justify-between gap-3 rounded-lg border border-destructive/40',
        'bg-destructive/8 px-3 py-2 text-sm text-destructive',
      )}
    >
      <span>Nie udalo sie odswiezyc danych: {message}</span>
      <Button variant="ghost" size="sm" onClick={onRetry} className="cursor-pointer">
        Ponow
      </Button>
    </div>
  )
}
