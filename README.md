# SRE Agent

An AI-powered Site Reliability Engineering assistant that connects directly to your infrastructure. Ask questions in natural language and receive answers backed by real-time data from Kubernetes, Prometheus, and Argo CD.

Built with [LangGraph](https://github.com/langchain-ai/langgraph), [Model Context Protocol](https://modelcontextprotocol.io/), persistent incident memory, and a Rich terminal UI.

## Features

- **Natural language diagnostics** — Describe infrastructure issues and receive actionable insights
- **28 integrated tools** across Kubernetes, Prometheus, and Argo CD
- **Persistent memory** — Automatically saves and recalls past incidents and failure patterns
- **Multi-model support** — Gemini, Claude, GPT-4, Ollama, Mistral, or any OpenAI-compatible provider
- **Hot-swap models** — Change LLM providers at runtime with `/model`
- **Streaming output** — Real-time response generation
- **Full CLI** — Slash commands for memory management, incident history, and exports

## Quick Start

### Prerequisites
- Python 3.10+
- Kubernetes cluster (local or remote)
- Prometheus and Argo CD deployed
- LLM API key (Gemini, OpenAI, Anthropic, or compatible)

### Installation

```bash
git clone https://github.com/ossama-ferjani/SRE-Agent.git
cd sre-agent
pip install -r requirements.txt
```

### Configuration

```bash
cp .env.example .env
# Edit .env with your API credentials and infrastructure URLs
```

Set one LLM provider:
```bash
# Example: Gemini (free tier available)
GOOGLE_API_KEY=YOUR_API_KEY

# Or OpenAI
OPENAI_API_KEY=sk-...

# Or any OpenAI-compatible service
OPENAI_COMPAT_API_KEY=sk-...
OPENAI_COMPAT_BASE_URL=https://api.provider.com/v1
```

And infrastructure endpoints:
```bash
PROMETHEUS_URL=http://localhost:9090
ARGOCD_URL=https://localhost:8080
ARGOCD_TOKEN=your-token
```

### Start MCP Servers

```bash
./tools/start_mcp_servers.sh
```

This starts Kubernetes, Prometheus, and Argo CD MCP servers on ports 3001-3003.

### Run the Agent

```bash
python -m cli.cli
# or
make run
```

## Usage Examples

```
"Are there any pods crashlooping in the cluster?"
"Check the payments service latency and error rates in Prometheus"
"Is anything out of sync in Argo CD?"
"What are the top recurring failure patterns from past incidents?"
```

The agent automatically determines which tools to use and reasoning path to take.

## Commands

| Command | Purpose |
|---------|---------|
| `/help` | Show all commands |
| `/servers` | MCP server status |
| `/model <name>` | Change LLM provider |
| `/memory` | View incident database |
| `/incidents [N]` | Recent incidents |
| `/patterns` | Failure patterns |
| `/search <query>` | Search incidents |
| `/export` | Export all data |
| `/reset` | Clear current session |

## Supported Models

Configure in `models/config.yaml` or via `--model` flag:

| Provider | Model | Env Variable |
|----------|-------|---|
| **Gemini** | `gemini/gemini-2.0-flash` | `GOOGLE_API_KEY` |
| **OpenAI** | `openai/gpt-4o` | `OPENAI_API_KEY` |
| **Claude** | `claude/claude-3-5-sonnet` | `ANTHROPIC_API_KEY` |
| **Ollama** | `ollama/llama3.1` | *(local)* |
| **OpenAI-compatible** | `openai-compat/<model>` | `OPENAI_COMPAT_*` |

---

## Available Tools

### Kubernetes (11 tools)
`list_namespaces`, `list_pods`, `get_pod_logs`, `describe_pod`, `list_deployments`, `scale_deployment`, `restart_deployment`, `list_services`, `get_events`, `get_node_status`, `delete_pod`

### Prometheus (9 tools)
`query`, `query_range`, `get_alerts`, `get_alert_rules`, `get_targets`, `get_metric_metadata`, `label_values`, `get_tsdb_status`, `get_runtime_info`

### Argo CD (8 tools)
`list_apps`, `get_app`, `sync_app`, `rollback_app`, `get_app_history`, `get_app_logs`, `list_projects`, `get_cluster_info`

---

The agent maintains incident history in SQLite at `~/.sre_agent/memory.db`:

- **Incidents** — automatically saved with symptoms, root causes, and resolutions
- **Patterns** — recurring failure modes derived from incident history
- **Context** — session-specific metadata

Recent incidents and top patterns are injected into every LLM request for context awareness.

## Project Structure

```
agent/              # LangGraph state machine and nodes
cli/                # Terminal UI and commands  
mcp_servers/        # MCP server loader and config
memory/             # Incident database layer
models/             # LLM provider registry
tools/              # Kubernetes, Prometheus, Argo CD servers
tests/              # Test suite
```

## Testing

```bash
make test           # Run all 40 tests
pytest tests/test_graph.py -v       # Agent logic
pytest tests/test_memory.py -v      # Incident storage
```

All tests run without live infrastructure — mocked connections.

## Troubleshooting

**MCP servers won't start?**
- Check ports 3001-3003 are available: `netstat -tlnp | grep 300[123]`
- Verify `.env` has correct infrastructure URLs

**Agent doesn't connect to Kubernetes?**
- Ensure kubeconfig is properly configured: `kubectl auth can-i get pods`
- Port-forward if using local cluster: `kubectl port-forward ...`

**Memory database issues?**
- Reset: `make reset-memory`
- Check location: `~/.sre_agent/memory.db`

## Contributing

Contributions are welcome. Open an issue or submit a pull request.

## License

[MIT](LICENSE)
