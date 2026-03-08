# SRE Agent

An AI-powered Site Reliability Engineering assistant that connects directly to your live infrastructure. Ask questions in plain English and get answers backed by real data from Kubernetes, Prometheus, and Argo CD — no dashboards, no context switching.

Built on [LangGraph](https://github.com/langchain-ai/langgraph) with [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) servers, a persistent SQLite incident memory, and a Rich terminal UI.

---

## Features

- **Natural language ops** — describe a problem, get a diagnosis with concrete fix commands
- **28 live tools** across Kubernetes (11), Prometheus (9), and Argo CD (8)
- **Persistent memory** — every resolved incident and failure pattern is saved to SQLite; injected into the agent's context automatically
- **Multi-model** — Gemini, Claude, GPT-4o, Ollama, Mistral, or any OpenAI-compatible API
- **Hot-swap models** at runtime with `/model`
- **Streaming output** — responses appear word-by-word as the LLM generates them
- **Full REPL** with slash commands for memory, server status, incident history, export

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        CLI  (cli/cli.py)                         │
│  Rich REPL · slash commands · streaming output · /help · /memory │
└────────────────────────┬─────────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────────────┐
│                    LangGraph Agent Graph                          │
│                                                                  │
│  inject_memory ──► reason (LLM) ──► tools (ToolNode / MCP)      │
│                         │                      │                 │
│                         └──► process_memory ◄──┘                 │
│                                commands                          │
│                                    │                             │
│                             save_conversation                    │
│                           (AsyncSqliteSaver)                     │
└──────────────────────────────────────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────────────────────────┐
│                   MCP Servers  (tools/*)                       │
│                                                                │
│  k8s_mcp.py        :3001   Kubernetes Python client           │
│  prometheus_mcp.py :3002   Prometheus HTTP API                │
│  argocd_mcp.py     :3003   Argo CD REST API                   │
└──────────────────┬─────────────────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────────────┐
│              Real Infrastructure                             │
│   Kubernetes cluster  ·  Prometheus  ·  Argo CD             │
└──────────────────────────────────────────────────────────────┘
```

**Data flow:**
1. User types a question in the REPL
2. `inject_memory` prepends recent incidents and patterns to the system prompt
3. `reason` calls the LLM (bound with all 28 MCP tools)
4. The LLM calls tools as needed; `ToolNode` executes them and loops back
5. Final response is parsed for `memory_save` / `memory_search` blocks
6. Conversation is checkpointed; response is streamed to the terminal

---

## Quick Start

### Prerequisites

- Python 3.10+
- A running Kubernetes cluster (local kind/minikube or remote)
- Prometheus and Argo CD deployed in the cluster
- An API key for at least one supported LLM provider

### 1. Clone and install

```bash
git clone https://github.com/your-org/sre-agent.git
cd sre-agent
pip3 install -r requirements.txt
```

### 2. Configure secrets

```bash
cp .env.example .env
# Edit .env — set your API key and infrastructure URLs
```

Minimum required fields (pick one LLM provider):

```bash
# Gemini (free tier available)
GOOGLE_API_KEY=AIza...

# Or OpenAI
OPENAI_API_KEY=sk-...

# Or any OpenAI-compatible API (Together, Groq, KodeKloud, etc.)
OPENAI_COMPAT_API_KEY=sk-...
OPENAI_COMPAT_BASE_URL=https://api.your-provider.com/v1

# Infrastructure
PROMETHEUS_URL=http://localhost:9090
ARGOCD_URL=https://localhost:8080
ARGOCD_TOKEN=your-token
```

### 3. Set your active model

Edit `models/config.yaml`:

```yaml
active:
  provider: "gemini"
  model: "gemini-2.0-flash"
```

See [Supported Models](#supported-models) for all options.

### 4. Start the MCP servers

The MCP servers are lightweight Python processes. Start all three with one command:

```bash
./tools/start_mcp_servers.sh
```

This starts:
- `k8s_mcp.py` on `:3001` — talks to your kubeconfig cluster
- `prometheus_mcp.py` on `:3002` — talks to `$PROMETHEUS_URL`
- `argocd_mcp.py` on `:3003` — talks to `$ARGOCD_URL` with `$ARGOCD_TOKEN`

Logs go to `/tmp/mcp-k8s.log`, `/tmp/mcp-prometheus.log`, `/tmp/mcp-argocd.log`.

To stop: `./tools/start_mcp_servers.sh stop`

### 5. Port-forward if using a local cluster

```bash
# Prometheus
kubectl port-forward svc/prometheus-operated -n monitoring 9090:9090 &

# Argo CD
kubectl port-forward svc/argocd-server -n argocd 8080:443 &
```

Or use `make port-forward` (adjust the service names for your install).

### 6. Run the agent

```bash
make run
# or
python3 -m cli.cli
```

On startup you'll see a checklist confirming model, memory, and MCP connections:

```
╔══════════════════════════════════════════════════════════╗
║              SRE Agent  •  Powered by LangGraph          ║
╚══════════════════════════════════════════════════════════╝

  ✅  Model:  openai-compat/google/gemini-3-pro-preview  (source: models/config.yaml)
  ✅  Memory: /home/you/.sre_agent/memory.db  (3 incidents · 2 patterns)
  ✅  MCP kubernetes: connected (11 tools)
  ✅  MCP prometheus: connected (9 tools)
  ✅  MCP argo: connected (8 tools)
  ✅  Thread: default

  Type /help for commands. Ctrl+C to exit.
```

---

## Usage Examples

```
You: Are there any pods crashlooping in the cluster?

You: The payments service is slow — check Prometheus for error rate and p99 latency

You: Check if Argo CD has any apps out of sync and tell me what changed

You: Something is broken in the broken-app namespace — investigate and tell me the root cause

You: What are the top 3 recurring failure patterns from past incidents?
```

The agent uses tools automatically — no need to name them. It will call `list_pods`, `get_pod_logs`, `query`, `get_alerts`, `get_app` etc. as needed and reason over the results.

---

## CLI Commands

| Command | Description |
|---|---|
| `/help` | Show all slash commands |
| `/servers` | MCP server status and tool counts |
| `/model <name>` | Hot-swap model (e.g. `/model openai/gpt-4o`) |
| `/memory` | Memory DB summary panel |
| `/incidents [N]` | Table of recent N incidents (default 10) |
| `/patterns` | Top recurring failure patterns by frequency |
| `/search <query>` | Full-text search across all incidents |
| `/save` | Interactively save a new incident |
| `/thread <name>` | Switch to a named conversation thread |
| `/reset` | Clear current thread (memory kept) |
| `/export` | Export all incidents to `incidents_export.json` |
| `/quit` | Exit |

---

## Supported Models

Set `active.provider` and `active.model` in `models/config.yaml`, or pass `--model` / set `MODEL=` env var.

| Provider | Example Model String | Env Var | Install |
|---|---|---|---|
| Gemini | `gemini/gemini-2.0-flash` | `GOOGLE_API_KEY` | included |
| Gemini | `gemini/gemini-1.5-pro` | `GOOGLE_API_KEY` | included |
| OpenAI | `openai/gpt-4o` | `OPENAI_API_KEY` | `langchain-openai` |
| OpenAI | `openai/gpt-4o-mini` | `OPENAI_API_KEY` | `langchain-openai` |
| Claude | `claude/claude-opus-4-5` | `ANTHROPIC_API_KEY` | `langchain-anthropic` |
| Claude | `claude/claude-3-5-sonnet` | `ANTHROPIC_API_KEY` | `langchain-anthropic` |
| Ollama | `ollama/llama3.1` | *(none)* | `langchain-ollama` |
| Mistral | `mistral/mistral-large-latest` | `MISTRAL_API_KEY` | `langchain-mistralai` |
| OpenAI-compat | `openai-compat/<model>` | `OPENAI_COMPAT_API_KEY` + `OPENAI_COMPAT_BASE_URL` | included |

**OpenAI-compatible** covers any API that speaks the OpenAI chat completions protocol: Together AI, Groq, Fireworks, Anyscale, KodeKloud, local vLLM, etc.

```yaml
# models/config.yaml
active:
  provider: "openai-compat"
  model: "meta-llama/Llama-3-70b-chat-hf"
```

```bash
# .env
OPENAI_COMPAT_API_KEY=sk-...
OPENAI_COMPAT_BASE_URL=https://api.together.xyz/v1
```

---

## MCP Tool Reference

### Kubernetes (port 3001)

| Tool | Description |
|---|---|
| `list_namespaces` | All namespaces |
| `list_pods` | Pods in a namespace with status/restarts |
| `get_pod_logs` | Container logs (tail N lines) |
| `describe_pod` | Full pod spec + events |
| `list_deployments` | Deployments with replica counts |
| `scale_deployment` | Scale replicas |
| `restart_deployment` | Rolling restart |
| `list_services` | Services and selectors |
| `get_events` | Namespace events (warnings first) |
| `get_node_status` | Node capacity and conditions |
| `delete_pod` | Force-delete a pod |

### Prometheus (port 3002)

| Tool | Description |
|---|---|
| `query` | Instant PromQL query |
| `query_range` | Range query with step |
| `get_alerts` | Currently firing alerts |
| `get_alert_rules` | All configured alert rules |
| `get_targets` | Scrape targets and health |
| `get_metric_metadata` | Metric help and type |
| `label_values` | Values for a label |
| `get_tsdb_status` | TSDB cardinality info |
| `get_runtime_info` | Prometheus runtime info |

### Argo CD (port 3003)

| Tool | Description |
|---|---|
| `list_apps` | All Argo CD applications |
| `get_app` | App sync + health details |
| `sync_app` | Trigger a sync |
| `rollback_app` | Roll back to a previous revision |
| `get_app_history` | Deployment history |
| `get_app_logs` | App container logs |
| `list_projects` | Argo CD projects |
| `get_cluster_info` | Registered clusters |

---

## How Memory Works

The agent maintains a SQLite database at `~/.sre_agent/memory.db` with three tables:

- **`incidents`** — title, severity, service, namespace, symptoms, root cause, resolution, tags, resolved flag
- **`patterns`** — auto-derived failure patterns with frequency counts, updated whenever a root cause is saved
- **`context`** — key/value store for session state

On every turn, the 5 most recent incidents and top 5 patterns are injected into the system prompt so the agent recognises recurring failures.

**The agent saves incidents automatically** when it discovers a root cause, by outputting a `memory_save` block:

````
```memory_save
{
  "title": "payments-api OOMKilled",
  "severity": "critical",
  "service": "payments-api",
  "namespace": "production",
  "symptoms": "pod restarting every 5 minutes",
  "root_cause": "unbounded in-memory cache",
  "resolution": "set cache max size 512MB and redeployed"
}
```
````

You can also save manually with `/save` or search with `/search <query>`.

**Conversation checkpoints** are stored at `~/.sre_agent/checkpoints.db` via `AsyncSqliteSaver`, giving the agent session continuity across restarts.

---

## Project Structure

```
sre-agent/
├── agent/
│   ├── graph.py        # LangGraph StateGraph, build_graph(), run_graph(), stream_graph()
│   ├── nodes.py        # inject_memory, reason, process_memory_commands, save_conversation
│   ├── prompt.py       # System prompt template
│   └── state.py        # AgentState TypedDict
│
├── cli/
│   └── cli.py          # Rich REPL, slash commands, streaming output
│
├── mcp_servers/
│   ├── servers.py      # MultiServerMCPClient loader (load_mcp_tools_async/sync)
│   ├── config.yaml     # MCP server endpoints
│   └── docker-compose.yml  # sqld (networked SQLite, optional)
│
├── memory/
│   ├── db.py           # SQLite connection (local file or sqld Docker)
│   ├── store.py        # save_incident, search_incidents, get_recent_incidents, etc.
│   └── schema.sql      # incidents, patterns, context, FTS5 virtual table
│
├── models/
│   ├── registry.py     # get_model() — resolves provider string to LangChain model
│   └── config.yaml     # Active provider and model selection
│
├── tools/
│   ├── k8s_mcp.py          # Kubernetes MCP server (FastMCP, port 3001)
│   ├── prometheus_mcp.py   # Prometheus MCP server (FastMCP, port 3002)
│   ├── argocd_mcp.py       # Argo CD MCP server (FastMCP, port 3003)
│   └── start_mcp_servers.sh  # Start/stop all three MCP servers
│
├── tests/              # pytest suite (40 tests)
├── config.yaml         # Agent behaviour settings
├── .env.example        # Environment variable template
├── Makefile            # Common tasks
└── requirements.txt    # Python dependencies
```

---

## Makefile Reference

```bash
make install        # pip3 install -r requirements.txt
make run            # Start the agent REPL
make mcp-start      # Start all 3 Python MCP servers
make mcp-stop       # Stop all MCP servers
make mcp-logs       # Tail MCP server logs
make port-forward   # kubectl port-forward Prometheus + Argo CD
make test           # Run full test suite
make clean          # Remove __pycache__, .pytest_cache, .ruff_cache
make reset-memory   # Wipe ~/.sre_agent/{memory,checkpoints}.db
make switch-model   # Print instructions for switching models
```

---

## Adding a New MCP Server

1. Write a FastMCP server in `tools/my_tool_mcp.py`:

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("my-tool")

@mcp.tool()
def do_something(param: str) -> str:
    """Description the LLM will see."""
    return "result"

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=3004)
```

2. Register it in `mcp_servers/config.yaml`:

```yaml
servers:
  my-tool:
    url: "${MY_TOOL_URL:-http://localhost:3004/mcp}"
    description: "My Tool — brief description of what tools it exposes"
    transport: "streamable_http"
```

3. Add the URL to `.env`:

```bash
MY_TOOL_URL=http://localhost:3004/mcp
```

4. Start your server and restart the agent — it will discover the tools automatically.

---

## Generating an Argo CD API Token

```bash
# Patch admin account to allow API key creation
kubectl patch configmap argocd-cm -n argocd \
  --type merge \
  -p '{"data": {"accounts.admin": "apiKey, login"}}'

# Generate token (valid 30 days)
argocd account generate-token \
  --account admin \
  --expires-in 720h \
  --server localhost:8080 \
  --insecure
```

Copy the token into `.env` as `ARGOCD_TOKEN`.

---

## Running Tests

```bash
# Full suite
make test

# Individual suites
pytest tests/test_graph.py -v       # Agent graph (mocked LLM)
pytest tests/test_memory.py -v      # SQLite memory store
pytest tests/test_registry.py -v    # Model provider registry
pytest tests/test_mcp.py -v         # MCP server config loading
```

All 40 tests run without any live infrastructure — LLM calls and MCP connections are mocked.

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GOOGLE_API_KEY` | For Gemini | — | Google AI Studio API key |
| `ANTHROPIC_API_KEY` | For Claude | — | Anthropic Console API key |
| `OPENAI_API_KEY` | For OpenAI | — | OpenAI API key |
| `MISTRAL_API_KEY` | For Mistral | — | Mistral AI key |
| `OPENAI_COMPAT_API_KEY` | For compat | — | API key for OpenAI-compatible provider |
| `OPENAI_COMPAT_BASE_URL` | For compat | — | Base URL, e.g. `https://api.together.xyz/v1` |
| `MODEL` | No | from `models/config.yaml` | Override active model at runtime |
| `MCP_KUBERNETES_URL` | No | `http://localhost:3001/mcp` | Kubernetes MCP endpoint |
| `MCP_PROMETHEUS_URL` | No | `http://localhost:3002/mcp` | Prometheus MCP endpoint |
| `MCP_ARGO_URL` | No | `http://localhost:3003/mcp` | Argo CD MCP endpoint |
| `PROMETHEUS_URL` | No | `http://localhost:9090` | Prometheus base URL |
| `ARGOCD_URL` | No | `https://localhost:8080` | Argo CD server URL |
| `ARGOCD_TOKEN` | For Argo CD | — | Argo CD API token |
| `SQLITE_URL` | No | — | sqld container URL for networked SQLite |

---

## License

[MIT](LICENSE)
