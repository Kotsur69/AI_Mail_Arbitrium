/**
 * The shape of what the FastAPI process serves, and the only place that fetches it.
 *
 * Every response is normalised here rather than in components, because the API
 * answers a missing database with a short payload (`dbPresent: false` and
 * nothing else) and no table should have to know that.
 */

export type Status = 'zgoda' | 'brak_zgody' | 'inne' | 'nie_dotyczy'

export const STATUSES: readonly Status[] = ['zgoda', 'brak_zgody', 'inne', 'nie_dotyczy']

export interface Totals {
  messages: number
  zgoda: number
  brak_zgody: number
  inne: number
  nie_dotyczy: number
  review: number
  with_attachments: number
  attachments_read: number
  attachments_total: number
}

export interface TimelinePoint {
  day: string
  messages: number
  review: number
}

export interface Campaign {
  configured: boolean
  subject: string
  description: string
  model: string | null
}

export interface Overview {
  dbPresent: boolean
  dbPath: string
  campaign: Campaign
  totals: Totals
  reviewReasons: Record<string, number>
  timeline: TimelinePoint[]
  mailboxes: string[]
  models: string[]
  lastClassifiedAt: string | null
  generatedAt: string | null
}

export interface Supplier {
  supplier: string
  messages: number
  statuses: Record<Status, number>
  queued: number
  lastMessage: string | null
}

export interface Message {
  id: string
  mailbox: string
  supplier: string
  sender: string
  subject: string
  receivedAt: string | null
  status: Status
  reviewReasons: string[]
  evidence: string
  rationale: string
  attachmentsTotal: number
  attachmentsRead: number
  attachmentStatus: Status | null
  model: string
  classifiedAt: string
}

export interface MessagePage {
  total: number
  items: Message[]
}

export interface MessageFilters {
  mailbox?: string | null
  status?: Status | null
  supplier?: string | null
  review?: boolean
  q?: string
}

const EMPTY_TOTALS: Totals = {
  messages: 0,
  zgoda: 0,
  brak_zgody: 0,
  inne: 0,
  nie_dotyczy: 0,
  review: 0,
  with_attachments: 0,
  attachments_read: 0,
  attachments_total: 0,
}

/** Drop empty values so `?status=` never reaches the API as a filter on "". */
function query(params: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === '' || value === false) continue
    search.set(key, String(value))
  }
  const rendered = search.toString()
  return rendered ? `?${rendered}` : ''
}

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`/api${path}`, { signal })
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`)
  }
  return (await response.json()) as T
}

export async function fetchOverview(
  mailbox: string | null,
  signal?: AbortSignal,
): Promise<Overview> {
  const raw = await get<Partial<Overview>>(`/overview${query({ mailbox })}`, signal)
  return {
    dbPresent: raw.dbPresent ?? false,
    dbPath: raw.dbPath ?? '',
    campaign: raw.campaign ?? { configured: false, subject: '', description: '', model: null },
    totals: raw.totals ?? EMPTY_TOTALS,
    reviewReasons: raw.reviewReasons ?? {},
    timeline: raw.timeline ?? [],
    mailboxes: raw.mailboxes ?? [],
    models: raw.models ?? [],
    lastClassifiedAt: raw.lastClassifiedAt ?? null,
    generatedAt: raw.generatedAt ?? null,
  }
}

export async function fetchSuppliers(
  mailbox: string | null,
  signal?: AbortSignal,
): Promise<Supplier[]> {
  const raw = await get<{ items?: Supplier[] }>(`/suppliers${query({ mailbox })}`, signal)
  return raw.items ?? []
}

export async function fetchMessages(
  filters: MessageFilters,
  signal?: AbortSignal,
): Promise<MessagePage> {
  const raw = await get<Partial<MessagePage>>(`/messages${query({ ...filters })}`, signal)
  return { total: raw.total ?? 0, items: raw.items ?? [] }
}
