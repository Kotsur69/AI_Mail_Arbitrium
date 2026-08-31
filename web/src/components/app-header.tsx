/**
 * The bar that says what you are looking at, and lets you change it.
 *
 * It carries the four facts a reviewer needs before trusting a single row: the
 * mailbox, the model that judged it, when the last verdict was written, and the
 * request the suppliers were actually sent. That last one matters most -- the
 * same reply means different things depending on what was asked, and a reviewer
 * who cannot see the question cannot check the answer.
 */

import { useCallback, useEffect, useState } from 'react'
import { Database, Mail, Moon, RefreshCw, Sun } from 'lucide-react'

import type { Campaign } from '@/lib/api'
import { formatDateTime } from '@/lib/domain'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

const THEME_KEY = 'arbitrium-theme'

type Theme = 'light' | 'dark'

function preferredTheme(): Theme {
  const stored = localStorage.getItem(THEME_KEY)
  if (stored === 'light' || stored === 'dark') return stored
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function useTheme() {
  const [theme, setTheme] = useState<Theme>(preferredTheme)

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark')
    localStorage.setItem(THEME_KEY, theme)
  }, [theme])

  const toggle = useCallback(() => {
    setTheme((current) => (current === 'dark' ? 'light' : 'dark'))
  }, [])

  return { theme, toggle }
}

interface AppHeaderProps {
  mailboxes: string[]
  mailbox: string | null
  campaign: Campaign
  models: string[]
  lastClassifiedAt: string | null
  loading: boolean
  onMailboxChange: (mailbox: string | null) => void
  onRefresh: () => void
}

export function AppHeader({
  mailboxes,
  mailbox,
  campaign,
  models,
  lastClassifiedAt,
  loading,
  onMailboxChange,
  onRefresh,
}: AppHeaderProps) {
  const { theme, toggle } = useTheme()

  return (
    <header className="sticky top-0 z-20 border-b bg-background/85 backdrop-blur">
      <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
        <div className="flex items-center gap-2">
          <span
            className="grid size-8 place-items-center rounded-md bg-primary
                       text-primary-foreground"
          >
            <Mail className="size-4" aria-hidden />
          </span>
          <div className="leading-tight">
            <h1 className="text-sm font-semibold">Arbitrium</h1>
            <p className="text-xs text-muted-foreground">Analiza zgod dostawcow</p>
          </div>
        </div>

        {mailboxes.length > 1 && (
          <>
            <Separator orientation="vertical" className="hidden h-8 sm:block" />
            <div className="flex items-center gap-1">
              <MailboxChip
                label="Wszystkie"
                active={mailbox === null}
                onClick={() => onMailboxChange(null)}
              />
              {mailboxes.map((name) => (
                <MailboxChip
                  key={name}
                  label={name}
                  active={mailbox === name}
                  onClick={() => onMailboxChange(name)}
                />
              ))}
            </div>
          </>
        )}

        <div className="ml-auto flex items-center gap-3">
          {campaign.subject && (
            <Tooltip>
              <TooltipTrigger asChild>
                <span
                  className="hidden max-w-72 cursor-help truncate text-xs
                             text-muted-foreground lg:block"
                >
                  Prosba: <span className="text-foreground">{campaign.subject}</span>
                </span>
              </TooltipTrigger>
              <TooltipContent className="max-w-80">
                <p className="font-medium">{campaign.subject}</p>
                {campaign.description && <p className="mt-1">{campaign.description}</p>}
              </TooltipContent>
            </Tooltip>
          )}

          {models.length > 0 && (
            <Tooltip>
              <TooltipTrigger asChild>
                <span
                  className="hidden cursor-help items-center gap-1.5 font-mono text-xs
                             text-muted-foreground md:inline-flex"
                >
                  <Database className="size-3.5" aria-hidden />
                  {models.length === 1 ? models[0] : `${models.length} modele`}
                </span>
              </TooltipTrigger>
              <TooltipContent>
                <p>Werdykty w tej bazie wydaly:</p>
                <ul className="mt-1 font-mono">
                  {models.map((name) => (
                    <li key={name}>{name}</li>
                  ))}
                </ul>
                <p className="mt-1">Ostatni werdykt: {formatDateTime(lastClassifiedAt)}</p>
              </TooltipContent>
            </Tooltip>
          )}

          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                onClick={onRefresh}
                disabled={loading}
                aria-label="Odswiez dane"
                className="cursor-pointer"
              >
                <RefreshCw className={cn('size-4', loading && 'animate-spin')} aria-hidden />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Odswiez -- backfill dopisuje werdykty na biezaco.</TooltipContent>
          </Tooltip>

          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                onClick={toggle}
                aria-label={theme === 'dark' ? 'Wlacz jasny motyw' : 'Wlacz ciemny motyw'}
                className="cursor-pointer"
              >
                {theme === 'dark' ? (
                  <Sun className="size-4" aria-hidden />
                ) : (
                  <Moon className="size-4" aria-hidden />
                )}
              </Button>
            </TooltipTrigger>
            <TooltipContent>{theme === 'dark' ? 'Jasny motyw' : 'Ciemny motyw'}</TooltipContent>
          </Tooltip>
        </div>
      </div>
    </header>
  )
}

function MailboxChip({
  label,
  active,
  onClick,
}: {
  label: string
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        'cursor-pointer rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
        'focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none',
        active
          ? 'bg-primary text-primary-foreground'
          : 'text-muted-foreground hover:bg-accent hover:text-foreground',
      )}
    >
      {label}
    </button>
  )
}
