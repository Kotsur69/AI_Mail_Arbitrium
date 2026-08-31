/**
 * What the pipeline's vocabulary is called in the interface.
 *
 * The stored values stay exactly as `review.py` and `verdict.py` write them --
 * the dashboard translates for display and never for storage, so a reviewer
 * comparing the screen against the CSV is reading the same rows.
 *
 * Every status carries an icon as well as a colour. That is not decoration:
 * consent and refusal are green and red, and colour alone would be the only
 * thing separating them for a red-green colourblind reviewer.
 */

import {
  CircleCheck,
  CircleHelp,
  CircleMinus,
  CircleX,
  FileWarning,
  Quote,
  ScanText,
  TriangleAlert,
  type LucideIcon,
} from 'lucide-react'

import type { Status } from '@/lib/api'

export interface StatusMeta {
  label: string
  icon: LucideIcon
  /** Tailwind colour token, defined in index.css. */
  tone: 'consent' | 'refusal' | 'other' | 'unrelated'
  description: string
}

export const STATUS_META: Record<Status, StatusMeta> = {
  zgoda: {
    label: 'Zgoda',
    icon: CircleCheck,
    tone: 'consent',
    description: 'Dostawca wyraznie wyrazil zgode.',
  },
  brak_zgody: {
    label: 'Brak zgody',
    icon: CircleX,
    tone: 'refusal',
    description: 'Dostawca wyraznie odmowil.',
  },
  inne: {
    label: 'Inne',
    icon: CircleHelp,
    tone: 'other',
    description: 'Odpowiedz na temat, ale nierozstrzygajaca: warunkowa, wymijajaca, kontrpytanie.',
  },
  nie_dotyczy: {
    label: 'Nie dotyczy',
    icon: CircleMinus,
    tone: 'unrelated',
    description: 'Wiadomosc nie jest odpowiedzia na prosbe.',
  },
}

export interface ReasonMeta {
  label: string
  icon: LucideIcon
  hint: string
}

/**
 * Why a message is waiting for a person. The hints are the reasoning from
 * `review.py` in one sentence, because a badge saying `evidence_not_grounded`
 * tells a reviewer nothing about what to go and check.
 */
export const REASON_META: Record<string, ReasonMeta> = {
  ambiguous_status: {
    label: 'Niejednoznaczne',
    icon: CircleHelp,
    hint: 'Odpowiedz nie rozstrzyga -- trzeba ja przeczytac.',
  },
  off_topic: {
    label: 'Nie na temat',
    icon: CircleMinus,
    hint: 'Nie jest odpowiedzia na prosbe. Zwykle mozna odrzucic hurtem.',
  },
  no_evidence: {
    label: 'Brak cytatu',
    icon: Quote,
    hint: 'Model nie wskazal fragmentu uzasadniajacego decyzje.',
  },
  evidence_not_grounded: {
    label: 'Cytat spoza tresci',
    icon: TriangleAlert,
    hint: 'Cytatu nie ma doslownie w wiadomosci -- model mogl go wymyslic.',
  },
  evidence_too_short: {
    label: 'Cytat za krotki',
    icon: Quote,
    hint: 'Zbyt krotki fragment, by uzasadnial rozstrzygniecie.',
  },
  body_attachment_conflict: {
    label: 'Konflikt z zalacznikiem',
    icon: FileWarning,
    hint: 'Tresc wiadomosci mowi co innego niz zalacznik.',
  },
  vision_transcript: {
    label: 'Odczyt ze skanu',
    icon: ScanText,
    hint: 'Cytat pochodzi z transkrypcji skanu -- zerknij na oryginal.',
  },
}

export function reasonMeta(reason: string): ReasonMeta {
  return (
    REASON_META[reason] ?? {
      label: reason,
      icon: TriangleAlert,
      hint: 'Powod zapisany przez pipeline, nieznany temu widokowi.',
    }
  )
}

/** Tailwind classes per tone, spelled out so the compiler can see them. */
export const TONE_CLASS: Record<StatusMeta['tone'], { text: string; bg: string; ring: string }> = {
  consent: { text: 'text-consent', bg: 'bg-consent', ring: 'ring-consent/30' },
  refusal: { text: 'text-refusal', bg: 'bg-refusal', ring: 'ring-refusal/30' },
  other: { text: 'text-other', bg: 'bg-other', ring: 'ring-other/30' },
  unrelated: { text: 'text-unrelated', bg: 'bg-unrelated', ring: 'ring-unrelated/30' },
}

const DATE_TIME = new Intl.DateTimeFormat('pl-PL', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
})

const DATE_ONLY = new Intl.DateTimeFormat('pl-PL', {
  day: '2-digit',
  month: '2-digit',
})

const NUMBER = new Intl.NumberFormat('pl-PL')

export function formatDateTime(iso: string | null): string {
  if (!iso) return '—'
  const moment = new Date(iso)
  return Number.isNaN(moment.getTime()) ? '—' : DATE_TIME.format(moment)
}

export function formatDay(iso: string): string {
  const moment = new Date(iso)
  return Number.isNaN(moment.getTime()) ? iso : DATE_ONLY.format(moment)
}

export function formatCount(value: number): string {
  return NUMBER.format(value)
}

/** A share of the total, or 0 when there is no total to be a share of. */
export function share(value: number, total: number): number {
  return total > 0 ? (value / total) * 100 : 0
}
