\# System Architecture Plan \& Technical Strategy: Local LLM Mail Analyzer



\## Executive Overview

We are building a secure, internal email processing and analysis application. The tool will parse supplier responses from a designated Outlook mailbox, analyze email bodies and attachments using a \*\*100% local Open-Source LLM\*\*, and generate structured summary reports.



Privacy and data security are absolute priorities: no data can leave our local infrastructure.



\---



\## Technical Context \& Infrastructure Setup

\- \*\*Workstation Specs:\*\*

&#x20; - \*\*GPU:\*\* NVIDIA GeForce RTX 5070 Ti (16 GB VRAM)

&#x20; - \*\*RAM:\*\* 64 GB System RAM

&#x20; - \*\*CPU:\*\* High-performance desktop processor

\- \*\*Local LLM Engine:\*\* Ollama / LM Studio (vLLM or OpenAI-compatible local API endpoint).

\- \*\*Target Models:\*\* Qwen 2.5 (14B or 32B quantized Q4\_K\_M) or Llama 3.1 (8B/70B partially offloaded).

\- \*\*Environment:\*\* Windows workstation running a local web service accessible to the local network (LAN / IP: `192.168.x.x`).



\---



\## Pending Business \& Functional Requirements (Stakeholder Questionnaire)

\*Note: Answers to these questions are currently pending from business stakeholders. The architecture must remain modular to accommodate any option below.\*



1\. \*\*Mailbox Infrastructure:\*\*

&#x20;  - \*Question:\* Which mail server/protocol are we connecting to (Outlook desktop MAPI, Exchange, Graph API, or IMAP)?

&#x20;  - \*Answer:\* \[outlook]



2\. \*\*Mailbox Scope:\*\*

&#x20;  - \*Question:\* Should the tool monitor a single dedicated mailbox or support multiple mailboxes simultaneously?

&#x20;  - \*Answer:\* \[Może grupować po dostawcy]



3\. \*\*Aggregation Logic:\*\*

&#x20;  - \*Question:\* Should the report itemize every single email individually, or group/aggregate them (e.g., by supplier, thread, or subject)?

&#x20;  - \*Answer:\* \[Może grupować po dostawcy]



4\. \*\*Extraction Scope \& Schemas:\*\*

&#x20;  - \*Question:\* What specific data points must the LLM extract (e.g., binary status like Agreed/Declined, key dates, numerical summaries, or general text summaries)?

&#x20;  - \*Answer:\* \[Status: zgoda, brak zgody, inne (sa odpowiedzi opisowe). Podsumowanie liczbowe]



5\. \*\*Output Format:\*\*

&#x20;  - \*Question:\* What is the primary output file format (Excel `.xlsx`, CSV, PDF, or interactive web view)?

&#x20;  - \*Answer:\* \[najlepiej csv, będzie można edytować]



6\. \*\*Attachment Processing:\*\*

&#x20;  - \*Question:\* Does the system need to parse attachments (PDFs, Excel sheets, images/scans) alongside email bodies?

&#x20;  - \*Answer:\* \[Tak, bo mogą to być dokumenty z podpisem co jest równoznaczne z wyrażeniem zgody]



7\. \*\*Execution Trigger Mode:\*\*

&#x20;  - \*Question:\* Should analysis run on-demand (via user action) or on a automated cron schedule (e.g., daily summary sent at 07:00 AM)?

&#x20;  - \*Answer:\* \[na żądanie]



8\. \*\*Application Interface Preference:\*\*

&#x20;  - \*Question:\* Do stakeholders prefer a Web UI Dashboard (hosted locally at `192.168.x.x` where users manually select emails to analyze and export) or a fully automated headless background script sending emails via Outlook?

&#x20;  - \*Answer:\* \[Do rozważenia wysyłany raport o 7:00]



9\. \*\*Historical Time Horizon:\*\*

&#x20;  - \*Question:\* Are we processing incoming real-time emails moving forward, or do we need to process historical backlogs (e.g., past 2 weeks / 1 month)?

&#x20;  - \*Answer:\* \[Skrzynka została utworzona pod koniec lipca, trzeba całość przeanalizować]



10\. \*\*Error Handling \& Edge Cases:\*\*

&#x20;   - \*Question:\* How should off-topic emails, empty messages, or low-confidence LLM outputs be handled (e.g., flagged as "Needs Manual Review")?

&#x20;   - \*Answer:\* \[Flagować do weryfikacji ręcznej]



11\. \*\*User Access Control:\*\*

&#x20;   - \*Question:\* If the Web Dashboard option is chosen, will it be accessible to the entire department/team or restricted to specific users?

&#x20;   - \*Answer:\* \[Osoby mające obecnie dostęp + ja, do decyzji kierownictwa czy chcą mieć dostęp]



\## Proposed System Requirements \& Capabilities



\### Core Features

1\. \*\*Email Ingestion:\*\*

&#x20;  - Connect to Microsoft Outlook (via Graph API, EWS, IMAP, or local MAPI/pywin32).

&#x20;  - Fetch recent emails/threads, including metadata (sender, timestamp, subject, body, attachment links).

&#x20;  - In-memory processing preferred to avoid unneeded disk caching (except temporary extraction for attachments like PDF/Excel/docs).



2\. \*\*Dual-Mode Operation:\*\*

&#x20;  - \*\*Mode A: Web Dashboard (Interactive / Human-in-the-Loop)\*\*

&#x20;    - A local Web UI (`192.168.x.x`) displaying an email table with checkboxes.

&#x20;    - Users select specific supplier emails and trigger "Analyze Selected (LLM)".

&#x20;    - Real-time processing progress bar and inline table previews.

&#x20;    - One-click export button for generated summary reports (`.xlsx` / `.csv`).

&#x20;  - \*\*Mode B: Automated Cron / Scheduled Pipeline\*\*

&#x20;    - Runs in the background (e.g., every morning at 07:00 AM).

&#x20;    - Processes previous day's emails and automatically emails the generated report to designated recipients via Outlook.



3\. \*\*LLM Extraction Engine:\*\*

&#x20;  - Structured JSON output parsing (using Pydantic / Json Schema mode).

&#x20;  - Extracted fields per email:

&#x20;    - Supplier Name / Email Address

&#x20;    - Response Status (e.g., `Confirmed`, `Denied`, `Pending Info`, `Manual Review Needed`)

&#x20;    - Key Metrics \& Summary Details (custom group requirements)

&#x20;    - Flag for invalid/ambiguous content.



\---



\## Your Tasks as Architect



Please act as a Principal Software Architect and design the end-to-end repository structure, tech stack recommendation, and implementation roadmap for this system.



\### 1. Technology Recommendations

\- Recommend the best framework stack:

&#x20; - \*\*Backend:\*\* Python (FastAPI) vs Node.js vs Python-only solutions (Streamlit / Gradio).

&#x20; - \*\*Frontend:\*\* React / Next.js with `shadcn/ui` vs lightweight Python UI.

&#x20; - \*\*LLM Integration:\*\* LangChain, LlamaIndex, LiteLLM, or direct HTTP calls to local API (Ollama/LM Studio)?

&#x20; - \*\*Attachment Parsing:\*\* Best libraries for extracting text from PDF, DOCX, and XLSX files in Python.



\### 2. Proposed System Architecture \& Directory Structure

\- Outline the modular clean architecture (Data ingestion, LLM Service, API Layer, UI Component layer).

\- Provide a clean ASCII diagram of data flow from Outlook to Report generation.

\- Design a complete file/folder structure for the repository.



\### 3. Step-by-Step Implementation Roadmap

\- Phase 1: PoC (Outlook connection + LLM parsing).

\- Phase 2: Web Interface \& Table selection.

\- Phase 3: Export \& Automated Scheduled reporting.



\---



\## Clarification \& Questions

If any requirement is ambiguous or if you need more details about the environment, network configuration, or email protocol details before finalizing the vision, \*\*please ask me questions before writing code\*\*. 



Otherwise, lay out your complete architectural vision and initial setup plan.





