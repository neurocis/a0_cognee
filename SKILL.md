# Cognee Knowledge Memory — Companion Skill

## Description
On-demand access to Cognee's knowledge graph operations from Agent Zero.
Use this skill when you need direct control over Cognee beyond the automatic plugin lifecycle.

## Trigger Phrases
- "search cognee", "query cognee", "cognee search"
- "add to cognee", "store in cognee", "cognee remember"
- "cognify", "build knowledge graph"
- "cognee datasets", "list datasets"
- "cognee status", "cognee health"
- "export cognee", "delete cognee dataset"

## Prerequisites
- Cognee server running and accessible
- `COGNEE_BASE_URL` set in Settings → Secrets
- Plugin `a0-cognee` installed and enabled

## Operations

### 1. Search — Query the Knowledge Graph

Search Cognee with various strategies.

**Parameters:**
- `query` (required): Search query text
- `search_type` (optional): One of `GRAPH_COMPLETION`, `RAG_COMPLETION`, `GRAPH_COMPLETION_COT`, `GRAPH_SUMMARY_COMPLETION`, `TRIPLET_COMPLETION`, `CHUNKS`, `SUMMARIES`, `FEELING_LUCKY`
- `dataset_name` (optional): Target dataset (defaults to project dataset)

**Code:**
```python
import asyncio
import sys
sys.path.insert(0, "/a0")

from helpers.cognee_helper import search, format_search_results

async def run():
    # Create a minimal agent proxy for config access
    from python.helpers.proxy import Proxy
    agent = Proxy.get_agent()

    result = await search(
        agent,
        query="YOUR_QUERY_HERE",
        search_type="GRAPH_COMPLETION",  # or another type
    )
    formatted = format_search_results(result)
    print(formatted if formatted else f"Result: {result}")

asyncio.run(run())
```

**Returns:** Formatted search results from Cognee's knowledge graph.

**Use Cases:**
- Find related knowledge across conversations
- Query specific facts or relationships
- Explore entity connections in the graph

---

### 2. Add Data — Store Content in Cognee

Add text content for later cognification.

**Parameters:**
- `content` (required): Text content to store
- `dataset_name` (optional): Target dataset

**Code:**
```python
import asyncio, sys
sys.path.insert(0, "/a0")
from helpers.cognee_helper import add_data

async def run():
    from python.helpers.proxy import Proxy
    agent = Proxy.get_agent()

    result = await add_data(
        agent,
        content="Your content to store here.",
        dataset_name=None,  # uses project default
    )
    print(f"Result: {result}")

asyncio.run(run())
```

**Returns:** API response confirming data was added.

**Use Cases:**
- Manually ingest documents or notes
- Store research findings for later retrieval
- Add project documentation to the knowledge graph

---

### 3. Cognify — Build Knowledge Graph

Trigger cognification to process ingested data into a knowledge graph.

**Parameters:**
- `dataset_name` (optional): Dataset to cognify

**Code:**
```python
import asyncio, sys
sys.path.insert(0, "/a0")
from helpers.cognee_helper import cognify

async def run():
    from python.helpers.proxy import Proxy
    agent = Proxy.get_agent()

    result = await cognify(agent, dataset_name=None)
    print(f"Cognify result: {result}")

asyncio.run(run())
```

**Returns:** Cognification status.

**Use Cases:**
- Manually trigger graph building after batch data ingestion
- Re-cognify after adding new data when auto-cognify is disabled

---

### 4. List Datasets — View Available Datasets

**Code:**
```python
import asyncio, sys
sys.path.insert(0, "/a0")
from helpers.cognee_helper import get_datasets

async def run():
    from python.helpers.proxy import Proxy
    agent = Proxy.get_agent()

    result = await get_datasets(agent)
    print(f"Datasets: {result}")

asyncio.run(run())
```

**Returns:** List of all datasets with metadata.

---

### 5. Health Check — Verify Cognee Server

**Code:**
```python
import asyncio, sys
sys.path.insert(0, "/a0")
from helpers.cognee_helper import health_check

async def run():
    from python.helpers.proxy import Proxy
    agent = Proxy.get_agent()

    result = await health_check(agent)
    print(f"Health: {result}")

asyncio.run(run())
```

**Returns:** Server health status.

---

### 6. Delete Dataset — Remove a Dataset

**Parameters:**
- `dataset_id` (required): UUID of the dataset to delete

**Code:**
```python
import asyncio, sys
sys.path.insert(0, "/a0")
from helpers.cognee_helper import delete_dataset

async def run():
    from python.helpers.proxy import Proxy
    agent = Proxy.get_agent()

    result = await delete_dataset(agent, dataset_id="DATASET_UUID_HERE")
    print(f"Delete result: {result}")

asyncio.run(run())
```

**Returns:** Deletion confirmation.

**⚠️ Warning:** This permanently removes the dataset and its knowledge graph.

---

### 7. Retain and Cognify — Store + Build in One Step

Convenience operation: add data and immediately cognify.

**Parameters:**
- `content` (required): Text content to store
- `dataset_name` (optional): Target dataset

**Code:**
```python
import asyncio, sys
sys.path.insert(0, "/a0")
from helpers.cognee_helper import retain_and_cognify

async def run():
    from python.helpers.proxy import Proxy
    agent = Proxy.get_agent()

    result = await retain_and_cognify(
        agent,
        content="Key facts and knowledge to retain.",
    )
    print(f"Result: {result}")

asyncio.run(run())
```

**Returns:** Combined add + cognify results.

---

### 8. Prune Data — Clear All Data

**Code:**
```python
import asyncio, sys
sys.path.insert(0, "/a0")
from helpers.cognee_helper import prune_data

async def run():
    from python.helpers.proxy import Proxy
    agent = Proxy.get_agent()

    result = await prune_data(agent)
    print(f"Prune result: {result}")

asyncio.run(run())
```

**⚠️ Warning:** This deletes ALL datasets. Use with extreme caution.

---

## Search Types Reference

| Type | Description | LLM? |
|------|-------------|------|
| `GRAPH_COMPLETION` | Graph-aware Q&A (default) | Yes |
| `RAG_COMPLETION` | Standard RAG retrieval | Yes |
| `GRAPH_COMPLETION_COT` | Chain-of-thought graph reasoning | Yes |
| `GRAPH_SUMMARY_COMPLETION` | Graph + summaries | Yes |
| `TRIPLET_COMPLETION` | Triplet vector search | Yes |
| `CHUNKS` | Raw text chunks | No |
| `SUMMARIES` | Chunk summaries | No |
| `FEELING_LUCKY` | Auto-selects best strategy | Varies |

## Configuration

- **Server URL**: Set `COGNEE_BASE_URL` in Settings → Secrets
- **API Key**: Set `COGNEE_API_KEY` in Settings → Secrets (optional)
- **Plugin settings**: Configure via Settings → Plugins → Cognee Knowledge Memory
- **Dataset isolation**: Datasets are scoped per project as `{prefix}-{project_name}`

## Best Practices

1. **Search before adding** — Check if knowledge already exists to avoid duplicates
2. **Use appropriate search types** — `GRAPH_COMPLETION` for complex queries, `CHUNKS` for raw retrieval
3. **Batch additions** — Add multiple related items, then cognify once for efficiency
4. **Monitor datasets** — List datasets periodically to track knowledge growth
5. **Use project isolation** — Different projects get separate datasets automatically
