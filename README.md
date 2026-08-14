## License

Copyright © 2026 Manvendra Sang. All rights reserved.

This repository and all of its contents are proprietary software.

No permission is granted to use, copy, modify, reproduce, distribute,
publish, sublicense, sell, or incorporate any portion of this software
into another project without prior written permission from the copyright
holder.

This restriction applies to the current version and all historical
versions, commits, releases, branches, and other versions of the
repository.(all past commits and updates and future ones as well are included)

Viewing or accessing this repository does not grant a license or any
other right to use the software.

For licensing or commercial-use inquiries, contact the copyright holder.


# ShopWave Autonomous Support Resolution Agent

> Processes customer support tickets end-to-end using Claude + async Python.  
> Each ticket gets classified, resolved via multi-step tool chains, validated, and logged — automatically.

---

## Architecture

```
Ticket Ingestion → Classifier → Agent Loop → Tool Layer → Validator → Reply/Escalate
                                    ↑              ↓
                              AgentState       Audit Logger
```

| Layer | File | Responsibility |
|-------|------|----------------|
| Ingestion | `app/ingestion/loader.py` | Load + validate tickets from JSON |
| Classifier | `app/agents/classifier.py` | Claude triage: category, urgency, confidence |
| Resolver | `app/agents/resolver.py` | Agentic loop: tool selection + execution |
| Read Tools | `app/tools/read_tools.py` | get_customer, get_order, get_product, search_kb |
| Write Tools | `app/tools/write_tools.py` | check_eligibility, issue_refund, send_reply, escalate |
| Guardrails | `app/tools/write_tools.py` | Policy enforcement before every write |
| Audit Log | `app/logging/audit.py` | Full JSON audit trail per ticket |
| Dashboard | `dashboard/app.py` | FastAPI real-time log viewer |

---

## Environment Setup

**1. Get your Anthropic API key** from https://console.anthropic.com

**2. Create your `.env` file:**
```bash
cp .env.example .env
# Edit .env and paste your ANTHROPIC_API_KEY
```
