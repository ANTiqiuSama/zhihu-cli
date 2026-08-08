<div align="center">

# 🧢 zhihu-cli

**Official Open Platform search plus full web tooling in one terminal.**

```
official search · browse · download · publish · analyze — all from one command.
```

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

</div>

---

**zhihu-cli** is a hybrid terminal client for Zhihu. It securely installs and
invokes Zhihu's official Open Platform CLI for supported search, hot-list,
Zhida, and personal-context APIs, while retaining the community web backend for
full-text downloads, publishing, interaction, analytics, and multi-account use.

> This repository is a **community project** and is not affiliated with Zhihu
> Inc. The `official` provider executes an unmodified binary downloaded from
> Zhihu's official CDN; all web automation commands remain unofficial.

---

## 🚀 Quick Start

> **Requirement:** Python 3.12 or newer. Check your version with `python --version` before installing.

```bash
# Clone and install
git clone https://github.com/ANTiqiuSama/zhihu-cli.git
cd zhihu-cli
python -m pip install .

# Install the official Open Platform provider (verified HTTPS + size + SHA-256)
zhihu-cli official install
zhihu-cli official version
zhihu-cli official upgrade --check  # explicit remote update check

# Install Zhihu's verified official Skill for future Codex sessions
zhihu-cli official skill install
zhihu-cli official skill path

# Optional extras
python -m pip install ".[nlp]"          # word clouds, clustering
python -m pip install ".[creator]"      # income charts, trends
python -m pip install ".[classifier]"   # ML-powered content classification
```

### 1. Configure the official provider

Create an Access Secret in the
[Zhihu Open Platform profile](https://developer.zhihu.com/profile), then enter
it locally without placing it in chat or shell history:

```powershell
$zhihuSecret = Read-Host "Zhihu Access Secret" -MaskInput
$zhihuSecret | zhihu-cli official auth set --secret-stdin
Remove-Variable zhihuSecret
```

Run an official search:

```bash
zhihu-cli official capabilities --pretty
zhihu-cli official search zhihu --query "科研自动化" --count 5 --pretty
zhihu-cli official search global --query "research automation workflow" --count 10 --pretty
zhihu-cli official hot --limit 10 --pretty
```

The official provider returns titles, summaries, metadata, and original links;
it does not promise complete answer or article bodies.

### 2. Authenticate the web backend when needed

```bash
zhihu-cli login --qrcode --browser auto  # follows the configured/default browser (Edge on Windows when selected)
zhihu-cli login --qrcode --browser edge  # explicitly align QR login and verification with Microsoft Edge
zhihu-cli login --cookie "…" --browser edge  # keep imported credentials aligned with Edge
zhihu-cli auth paste          # paste a full cURL from browser DevTools
```

If Zhihu returns risk-control error `40352`, the CLI opens the verification
page and explains the next step. Run QR login in a user-visible interactive
terminal: non-interactive execution stops before opening the page, and one
login session never opens more than one human-verification challenge. Browser
verification cookies do not automatically move into a separate CLI session,
so `zhihu-cli auth paste` is the most reliable fallback: deliberately copy an
authenticated request as cURL from browser DevTools after verification and
paste it into the CLI.

Use web authentication only for capabilities the official provider does not
offer, such as complete content downloads, comments, publishing, interaction,
and multiple profiles. Stop when Zhihu presents human verification; this
project does not automate CAPTCHA bypass.

### 3. Verify

```bash
zhihu-cli status              # short status command
zhihu-cli whoami              # online account verification
zhihu-cli auth status         # full grouped command remains available
```

The official and web credentials are independent. `official auth status`
checks an Open Platform Access Secret; the existing `auth status` checks cached
web headers and profiles.

### 4. Enable Codex routing

```powershell
zhihu-cli official skill install
zhihu-cli official skill path
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  "$env:USERPROFILE\.codex\skills\zhihu\scripts\run.ps1" status
```

The installer downloads the official Skill from Zhihu's CDN, verifies the
release-manifest size and SHA-256, validates the package identity, and installs
it under the user-level Codex skills directory. On Windows it adds a UTF-8 BOM
to the packaged PowerShell scripts so Windows PowerShell 5.1 can parse their
Chinese text without changing command or authentication behavior. Start a new
Codex turn after installation so skill discovery refreshes.

Codex should route search, hot lists, Zhida, personal content, followees, and
favorites through the official `zhihu` Skill. Complete public-answer body reads
remain a separate community-web operation and must not treat a search summary
as complete text. Credentials remain in the official OS keychain and are never
copied into the repository or Skill files.

---

## Official CLI diff

This project does not fork or modify Zhihu's official binary. It adds a secure
provider bridge and keeps the broader community client alongside it.

| Capability | Zhihu official CLI 0.2.0 | This hybrid CLI 0.3.1 |
|---|---|---|
| Zhihu search | Official API, 1–10 summarized results | Same official command via `official search zhihu`; legacy typed web search also retained |
| Global search | Official API, 1–20 results, realtime/static/all indexes | Same via `official search global` |
| Hot list | Official API, 1–30 entries | Same via `official hot`; legacy web hot list retained |
| Zhida | Three official models; JSON/SSE/text | Same via `official answer` |
| Personal context | Own contents, followees, favorites | Same via `official me ...` |
| Complete answer/article body | Not provided; summaries only | Community `answer --api`, `browse`, and `download` paths, subject to web access controls |
| Questions and comments | No full thread reader | Browse question/answer/comment threads |
| Publishing and social actions | Not provided | Publish/edit, vote, thank, follow, collect, and comment |
| Chat, notifications, drafts | Not provided | Retained community commands |
| Creator/NLP analysis | Not provided | Retained analysis and extension tools |
| Multi-account web profiles | Not provided | Retained profile switching |
| Authentication | Open Platform Access Secret in OS keychain | Official credentials stay in the official keychain; web Cookie/cURL profiles remain separate |
| Installation | Official Skill installs a closed binary | `official install` verifies the binary; `official skill install` verifies and installs the official Codex Skill without vendoring either artifact |
| Platforms in current official manifest | Windows AMD64; macOS AMD64/ARM64 | Official provider on those platforms; community Python commands retain their existing portability |
| License/source | Official binary is not vendored here | Community wrapper code remains MIT; official artifacts stay external |

Provider selection is explicit. Failure of an official API call never silently
falls back to scraping or a private web API. Use `zhihu-cli official ...` for
official calls and the existing top-level commands for web operations.

---

## ✨ What You Can Do

### 📖 Read & Browse

Browse Zhihu's feeds, hot lists, questions, articles, pins, and comments — all rendered in your terminal with a Rich-powered pager. Explore the real-time trending list with excerpts, scroll through your personalized recommend feed, or dive into a question and its full answer thread without clicking a single link.

For automation that needs explicit completeness and access-control evidence, use the safe answer-detail API mode:

```bash
zhihu-cli answer "https://www.zhihu.com/question/123/answer/456" --api --json
zhihu-cli answer "https://www.zhihu.com/question/123/answer/456?utm_source=x" --api --json --metadata-only
```

API mode canonicalizes the URL, stops before networking when no profile is active, sends at most one request, disables automatic captcha retries, and succeeds only for HTTP 200 JSON containing the matching answer ID and non-empty content. `--allow-anonymous` permits one explicit compatibility probe; it does not bypass login, captcha, or risk control.

### 💾 Download for Offline

Save any Zhihu content (articles, answers, questions, pins, videos) as clean Markdown with YAML frontmatter. Download individual pieces or batch-process from a manifest. Everything lands in `~/.zhihu-cli/downloads/`, organized by type, ready for your note-taking system or offline reading.

### 🔍 Search

Use `official search zhihu` as the stable default for discovery and patrols.
The legacy `search question|article|user|topic` commands remain available when
their richer type-specific web results are explicitly required.

### ✍️ Publish & Edit

Write answers and articles in Markdown, publish them to Zhihu with one command. Need to update? Modify existing answers and articles from your local files. Markdown-to-HTML conversion happens automatically via Zhihu's own rendering pipeline.

### 💬 Interact

Vote, thank, follow, block, and comment — full social interaction without the browser. Manage collections: create, populate, and organize them. Send and receive direct messages, and stream real-time notifications and chat via MQTT.

### 🕸️ Scrape & Export

Batch-export your creations, activity history, answers, and articles as structured JSON. Use the universal converter to merge and normalize across formats for your own data pipeline.

### 📊 Analyze

**Creator analytics** — pull your Zhihu income data and visualize it: monthly summaries, trend charts (with EMA), advanced indicators (Bollinger Bands, MACD), derivative analysis (velocity/acceleration/jerk), weekday breakdowns, and per-content daily metrics. Charts are saved as PNGs.

**NLP tools** — run word frequency analysis, generate word clouds, and perform K-means clustering on your downloaded content. All operate across your full Markdown library.

### 🔐 Multi-Account

Save multiple profiles from different accounts, switch between them with a single command. Each profile keeps its own auth credentials and cookies.

---

## 🏗️ Architecture

```
src/zhihu_cli/
├── main.py                  # Click CLI — command group hub
├── output.py                # styled terminal output (Rich)
├── official.py              # official manifest verification + binary resolver
├── commands/official.py     # secure passthrough to the official CLI
├── content/
│   ├── handlers/            # one file per Zhihu domain
│   └── utils/               # HTML↔Markdown, ZSE v4 signing
├── creator_tools/           # income analytics + plotting
├── nlp_tools/               # word count, wordcloud, clustering
└── extensions/              # plugin system (auto-discovered)
```

| Layer | What It Does |
|---|---|
| **✅ Official** | Open Platform CLI installed from Zhihu's CDN with host, size, SHA-256, archive, and version checks |
| **🔐 Auth** | Browser Cookie + User-Agent headers from cURL paste or QR code login, cached per-profile |
| **✍️ Signing** | Every Zhihu request gets auto-signed with `x-zse-93` / `x-zse-96` headers via ZSE v4 cipher |
| **🌐 Requests** | `curl_cffi` impersonates Chrome's TLS fingerprint to avoid detection |
| **📄 Extraction** | Prefers direct API calls; falls back to HTML page scraping with `js-initialData` parsing |
| **📝 Markdown** | HTML → LaTeX preprocessing → recursive traversal → clean Markdown. Reverse for publishing |
| **🔌 Extensions** | Drop a plugin in `extensions/` with `register_cli(group)` — auto-discovered at startup |

---

## 🧪 Extras

### Optional Dependencies

```bash
pip install -e ".[nlp]"          # jieba, matplotlib, wordcloud, scikit-learn...
pip install -e ".[creator]"      # matplotlib, numpy, pandas, seaborn...
pip install -e ".[classifier]"   # torch, transformers, scikit-learn...
```

### Shell Completions

```bash
eval "$(python autocomp.py)"
```

---

## 🤝 Contributing

PRs welcome! The codebase is structured for extensibility:

- **New command?** Add a file to `commands/` with a `register_<name>(group)` function, import it in `main.py`.
- **New handler?** Add a file to `content/handlers/` — follow the existing patterns.
- **New extension?** Create `extensions/<name>/` with an `__init__.py` exposing `register_cli(group)`.

Run the formatter before submitting:

```bash
pre-commit run --all-files
ruff check .
ruff format .
```

---

## 📜 License and official artifacts

The community source code in this repository is MIT licensed. Zhihu's official
CLI binary and official Skills are not included in this repository and remain
subject to Zhihu's own terms. `zhihu-cli official install` downloads the binary
directly from `developer-cdn.zhihu.com` after explicit user invocation.

---

<div align="center">

*Made with ❤️ and way too many terminal sessions.*

[Report a bug](https://github.com/ANTiqiuSama/zhihu-cli/issues) · Star ⭐ this repo!

</div>
