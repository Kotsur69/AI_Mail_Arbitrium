# mail_analyzer

Classifies supplier replies in an Outlook mailbox with a **local** LLM, and tells you
which ones a human still has to read.

A buyer sends the same request to a few hundred suppliers. The replies come back as
free-form Polish prose, sometimes with the decision hidden in a signed attachment.
This reads that mailbox and produces a per-supplier answer: **zgoda** (agreed),
**brak zgody** (refused), or a queue of messages that need a person.

Nothing leaves the machine. The model runs in [LM Studio](https://lmstudio.ai) on the
same workstation, mail is read over Outlook COM in read-only mode, and there is no
outbound network call in the pipeline.

## Status

Phase 1 (proof of concept) is done and measured against a real mailbox:

| | |
|---|---|
| Throughput | ~6.2 s per message on `qwen3-30b-a3b-2507`, RTX 5070 Ti / 64 GB |
| Outlook object model guard | does not fire — body, attachments and sender read without prompts |
| Tests | 71 passing |

Not built yet: attachment parsing, persistence, web UI, CSV export, scheduling.

## How it works

```
Outlook (COM, read-only)
        │  RawMessage: message-id, sender, subject, body, attachment names
        ▼
normalize.py ── strips quoted history and confidentiality footers
        ▼
classify.py ── one message → one verdict, JSON-Schema constrained decoding
        ▼
review.py ── deterministic rules decide what a human must check
        ▼
per-supplier rollup  →  report
```

Three decisions carry most of the design:

**The model classifies one message and nothing else.** Every count, rollup and status
precedence is computed in Python. The model is never asked to aggregate.

**Output is a contract, not a suggestion.** `response_format` pins the reply to
`MessageVerdict`'s JSON Schema, so a malformed answer is impossible rather than
handled.

**Confidence is not probabilistic.** Three ways of getting an uncertainty signal out
of this stack were tested and all three failed: self-reported `confidence` came back
~0.95 on everything including deliberately ambiguous mail; majority vote over three
samples at temperature 0.7 was unanimous on all ten test messages at triple the cost;
LM Studio returns `logprobs: null`. So `review.py` uses rules over the verdict itself
— is the status decisive, is the quoted evidence actually present in the source, is it
long enough to justify the call, does it conflict with the attachment. Cheap,
auditable, and it explains itself to the reviewer.

## Layout

```
src/mail_analyzer/
  verdict.py            the LLM contract + the grounding check
  classify.py           the local model call
  normalize.py          quoted-history and disclaimer stripping
  review.py             what a human has to look at, and why
  config.py             mailboxes as configuration, validated on load
  ingestion/
    base.py             RawMessage, dedupe key, MailSource protocol
    outlook_mapi.py     read-only Outlook COM adapter
scripts/
  probe_outlook.py      recon: stores, folders, guard behaviour (structure only)
  analyze_mailbox.py    Phase 1 CLI: read a mailbox, classify, print a table
  phase0_smoke.py       constrained decoding + grounding on hand-written cases
  phase0_confidence.py  the confidence experiment that failed
  fetch_models.sh       pull GGUF weights from Hugging Face
tests/
```

`ingestion/base.py` defines `MailSource`, so Outlook is one adapter rather than an
assumption baked through the pipeline. Messages are deduped on
`PR_INTERNET_MESSAGE_ID`; Outlook's `EntryID` is deliberately unused, because it gets
rewritten when an item moves between folders and the same message would look new.

## Setup

Requires Windows with **classic** Outlook (`OUTLOOK.EXE`). New Outlook (`olk.exe`)
exposes no COM object model and cannot be used.

```bash
python -m venv .venv
./.venv/Scripts/python.exe -m pip install openai pydantic pytest pywin32
bash scripts/fetch_models.sh          # GGUF weights into LM Studio's model tree
```

Then load the model in LM Studio and start its server on `localhost:1234`.

## Mailboxes

Mailboxes are configuration, not command-line archaeology. Let Outlook write the
file for you:

```bash
./.venv/Scripts/python.exe scripts/analyze_mailbox.py --init-config
```

That produces `config/mailboxes.toml` listing every store the Outlook profile can
see, with archives and public folder trees switched off. Adding a mailbox later
means adding three lines:

```toml
[[mailbox]]
name = "dostawcy"                # what you type on the command line
store = "zgody@firma.pl"         # matched loosely: address, display name, or a fragment
folder = "Skrzynka odbiorcza"    # omit entirely to use the store's inbox
since = 2026-07-25               # ignore anything received before this day
```

Two things there are deliberate. `store` is matched case-insensitively and by
fragment, because a mailbox shows up in Outlook as an address, as a display name,
or as either with a suffix, and which one a person types should not decide whether
the run works. `folder` is optional, because Outlook names its folders in the
display language — omit it and the store's own inbox is used, whatever it is
called.

## Usage

```bash
# What can Outlook see? Prints structure and counts only, never content.
./.venv/Scripts/python.exe scripts/analyze_mailbox.py --list-stores

# One configured mailbox, or every enabled one.
./.venv/Scripts/python.exe scripts/analyze_mailbox.py --mailbox dostawcy
./.venv/Scripts/python.exe scripts/analyze_mailbox.py --all --limit 20

# A mailbox that is not in the config file at all.
./.venv/Scripts/python.exe scripts/analyze_mailbox.py --store "you@example.com" --limit 15
```

`--folder`, `--since` and `--limit` override the file for one run, so narrowing a
run never means editing configuration.

Subjects, senders and bodies are **redacted by default** — the CLI prints sender
domains and hashed subject tags. Real content requires `--show-content`, and that flag
exists so mail is only ever displayed when a person is the one reading it.

```bash
./.venv/Scripts/python.exe -m pytest
```

## Known limitation

The classifier is asked whether a message expresses agreement, without ever being
shown *what* is being agreed to. In that framing "Potwierdzam odbiór" ("confirming
receipt") is indistinguishable from consent, and it produces false positives on
mailboxes that contain no request at all. The fix is to pass the campaign's own
subject into the prompt and have the model judge relevance against it — which is only
testable against a real supplier mailbox.

## Privacy

- The model is local. No mail, no attachment and no fragment of either is sent anywhere.
- Outlook access is read-only: nothing is written, moved, deleted, sent, or marked as read.
- CLI output is redacted unless content is explicitly requested.
- Exports, databases and model weights are gitignored.
