# a0-cognee — Cognee Knowledge Memory for Agent Zero

An Agent Zero community plugin that integrates [Cognee](https://www.cognee.ai/), an open-source AI memory platform combining vector search with graph databases, into Agent Zero's memory lifecycle.

## What It Does

**Cognee transforms raw conversation data into a connected knowledge graph.** This plugin automatically:

- **Retains** — Extracts key knowledge from conversations and stores it in Cognee
- **Recalls** — Enriches agent responses with semantic and graph-based search results
- **Contextualizes** — Injects relevant knowledge graph context into the system prompt

Unlike simple vector-only memory, Cognee links documents, entities, and concepts into a graph structure, enabling relationship-aware retrieval with 14+ search strategies.

## Architecture

```
Agent Zero                          Cognee Server (Docker)
├─ monologue_start                  ┌──────────────────────┐
│  └─ _20_cognee_init               │  REST API :8000      │
├─ system_prompt                    │  ├─ /api/add         │
│  └─ _30_cognee_context  ────────► │  ├─ /api/cognify     │
├─ message_loop_prompts_after       │  ├─ /api/search      │
│  └─ _51_cognee_recall   ────────► │  └─ /api/v1/datasets │
├─ monologue_end                    │                      │
│  └─ _52_cognee_retain   ────────► │  Triple Store:       │
└─                                  │  ├─ Relational (meta)│
                                    │  ├─ Vector (semantic)│
                                    │  └─ Graph (relations)│
                                    └──────────────────────┘
```

### Extension Lifecycle

| Hook | Extension | Priority | Purpose |
|------|-----------|----------|---------|
| `monologue_start` | `_20_cognee_init` | 20 | Initialize client state, verify configuration |
| `system_prompt` | `_30_cognee_context` | 30 | Query knowledge graph, inject context into system prompt |
| `message_loop_prompts_after` | `_51_cognee_recall` | 51 | Search Cognee with user message, inject results as extras |
| `monologue_end` | `_52_cognee_retain` | 52 | Extract knowledge via utility LLM, store in Cognee (background) |

## Prerequisites

- **Agent Zero** v0.9.x or later
- **Cognee Server** running and accessible (Docker recommended)

### Setting Up Cognee Server

```bash
# Quick start with Docker
echo 'LLM_API_KEY="your_openai_key"' > .env
docker run --env-file ./.env -p 8000:8000 --rm -it cognee/cognee:main

# Or with Docker Compose
git clone https://github.com/topoteretes/cognee.git
cd cognee && cp .env.template .env
# Edit .env with your LLM_API_KEY and other settings
docker-compose up -d
```

Verify it's running:
```bash
curl http://localhost:8000/api/health
# {"status": "healthy"}
```

## Installation

1. Clone this repository into your Agent Zero plugins directory:
   ```bash
   cd /path/to/agent-zero/usr/plugins/
   git clone https://github.com/neurocis/a0_cognee.git cognee
   ```

2. Enable the plugin in Agent Zero's **Settings → Plugins** panel.

3. Set your Cognee server URL in **Settings → Secrets**:
   ```
   COGNEE_BASE_URL = http://your-cognee-host:8000
   COGNEE_API_KEY = (optional, for authenticated instances)
   ```

4. The plugin will automatically install its dependencies (`aiohttp`) on first load.

## Configuration

All settings are configurable via the plugin's WebUI panel (**Settings → Plugins → Cognee Knowledge Memory**).

### Secrets (Settings → Secrets)

| Secret | Required | Description |
|--------|----------|-------------|
| `COGNEE_BASE_URL` | **Yes** | Cognee server URL (e.g., `http://localhost:8000`) |
| `COGNEE_API_KEY` | No | API key for authenticated Cognee instances |

### Plugin Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| Dataset Prefix | string | `a0` | Combined with project name for dataset isolation |
| Enable Retain | bool | `true` | Auto-extract and store conversation knowledge |
| Enable Recall | bool | `true` | Enrich responses with graph search results |
| Enable Context | bool | `true` | Inject knowledge context into system prompt |
| Auto-Cognify | bool | `true` | Build knowledge graph after each retain |
| Search Type | enum | `GRAPH_COMPLETION` | Cognee search strategy (see below) |
| Recall Max Tokens | int | `4096` | Max tokens from recall search results |
| Context Max Tokens | int | `500` | Max tokens for system prompt context |
| Cache TTL | int | `120` | Seconds to cache search results |
| Debug Logging | bool | `false` | Verbose logging for troubleshooting |

### Available Search Types

| Search Type | Description | LLM Generation |
|-------------|-------------|----------------|
| `GRAPH_COMPLETION` | Graph-aware Q&A via vector hints + graph traversal (default) | Yes |
| `RAG_COMPLETION` | Standard RAG — vector chunks → LLM | Yes |
| `GRAPH_COMPLETION_COT` | Chain-of-thought iterative graph reasoning | Yes |
| `GRAPH_SUMMARY_COMPLETION` | Graph context + summaries → LLM | Yes |
| `TRIPLET_COMPLETION` | Triplet vector search → LLM | Yes |
| `CHUNKS` | Raw text chunks by vector similarity | No |
| `SUMMARIES` | Chunk summaries by vector similarity | No |
| `FEELING_LUCKY` | LLM auto-selects best search type | Varies |

## How It Works

### Retain (Knowledge Extraction)

At the end of each agent monologue:
1. The conversation history is sent to a utility LLM with an extraction prompt
2. Key facts, relationships, and knowledge are extracted as structured data
3. The extracted knowledge is sent to Cognee via `POST /api/add`
4. If Auto-Cognify is enabled, `POST /api/cognify` builds the knowledge graph
5. All retention runs in a background thread to avoid blocking responses

### Recall (Search Enrichment)

During each message loop iteration:
1. The user's message is used as a search query
2. Cognee is queried with the configured search type
3. Results are formatted and injected into `loop_data.extras_persistent`
4. The agent sees these results as additional context when generating responses

### Context (System Prompt Injection)

When the system prompt is assembled:
1. Recent conversation history is used as a contextual query
2. Cognee returns relevant knowledge graph connections
3. Results are injected into the system prompt via the `cognee.context.md` template

## Dataset Isolation

Datasets are automatically scoped per project:
- Pattern: `{prefix}-{project_name}` (e.g., `a0-myproject`)
- Default dataset: `a0-default` when no project is active
- Change the prefix in plugin settings to create separate knowledge spaces

## Companion Skill

The plugin includes a companion `SKILL.md` that can be loaded via `skills_tool:load cognee` for on-demand CLI access to Cognee operations (search, add data, manage datasets, etc.).

## File Structure

```
cognee/
├── plugin.yaml                    # Plugin manifest
├── default_config.yaml            # Default settings
├── requirements.txt               # Dependencies (aiohttp)
├── hooks.py                       # install() + pre_update()
├── execute.py                     # Health check / setup verification
├── README.md                      # This file
├── SKILL.md                       # Companion skill for CLI access
├── helpers/
│   ├── __init__.py
│   └── cognee_helper.py           # Core REST API integration (~500 lines)
├── extensions/
│   └── python/
│       ├── monologue_start/
│       │   └── _20_cognee_init.py
│       ├── system_prompt/
│       │   └── _30_cognee_context.py
│       ├── message_loop_prompts_after/
│       │   └── _51_cognee_recall.py
│       └── monologue_end/
│           └── _52_cognee_retain.py
├── prompts/
│   ├── cognee.context.md           # Context injection template
│   ├── cognee.recall.md            # Recall injection template
│   └── cognee.retain_extract.sys.md # LLM extraction system prompt
└── webui/
    └── config.html                 # Settings panel (Alpine.js)
```

## Troubleshooting

### Plugin not working
1. Verify `COGNEE_BASE_URL` is set in Settings → Secrets
2. Check Cognee server is reachable: `curl $COGNEE_BASE_URL/api/health`
3. Enable Debug Logging in plugin settings to see detailed logs
4. Run the plugin health check from Settings → Plugins → Execute

### No memories being recalled
1. Ensure Retain and Recall are both enabled
2. Check that Auto-Cognify is enabled (data must be cognified before it's searchable)
3. Verify the dataset has data: check Cognee's `/api/v1/datasets` endpoint
4. Try a different Search Type (e.g., `RAG_COMPLETION` for simpler retrieval)

### High latency
1. Reduce Cache TTL to serve more from cache
2. Switch to a lighter search type (`CHUNKS` or `SUMMARIES`)
3. Reduce max token limits for recall and context
4. Disable Auto-Cognify and run cognification manually during quiet periods

## License

MIT

## Credits

- [Cognee](https://www.cognee.ai/) by Topoteretes — the underlying AI memory platform
- [Agent Zero](https://github.com/agent0ai/agent-zero) by Jan Tomášek — the agentic framework
- Plugin architecture inspired by [a0-hindsight](https://github.com/neurocis/a0-hindsight) and [a0-plugin-honcho](https://github.com/alogotron/a0-plugin-honcho)
- This plugin is part of the **neurocis method** for personal assistant memory, powering knowledge retention and semantic search for the Bibiotek agent (librarian)
