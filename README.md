# HappyCowler MCP

An MCP (Model Context Protocol) server that lets you ask your AI assistant about vegan and vegetarian restaurants anywhere in the world, powered by [HappyCow.net](https://happycow.net/).

**Example prompts once connected:**
- *"What are the top 10 most popular fully vegan restaurants in Lima, Peru?"*
- *"Find vegetarian-friendly restaurants in Bangkok with the highest ratings."*
- *"List all vegan restaurants in Berlin, Germany."*

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Setup with Claude Desktop](#setup-with-claude-desktop)
- [Setup with Claude CLI (claude-code)](#setup-with-claude-cli-claude-code)
- [How It Works](#how-it-works)
- [Tool Reference](#tool-reference)
- [Disclaimer](#disclaimer)

---

## Prerequisites

- Python 3.8 or later
- [Claude Desktop](https://claude.ai/download) **or** the [Claude CLI (`claude`)](https://docs.anthropic.com/en/docs/claude-code)
- Git (to clone this repo)

---

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/tw3kirk/happycowler-mcp.git
cd happycowler-mcp

# 2. Install Python dependencies
pip install beautifulsoup4 "mcp>=1.0"

# 3. Install the incapsula library manually (required for HappyCow access)
pip install requests six bs4
# Then copy the incapsula package into your site-packages:
pip download incapsula-cracker-py3 -d /tmp/incap && \
  tar xzf /tmp/incap/incapsula-cracker-py3-*.tar.gz -C /tmp/incap && \
  cp -r /tmp/incap/incapsula-cracker-py3-*/incapsula \
        $(python -c "import site; print(site.getsitepackages()[0])")
```

> **Tip:** Note the absolute path to your `server.py` — you'll need it in the config steps below.
>
> ```bash
> pwd   # e.g. /Users/yourname/happycowler-mcp
> ```

---

## Setup with Claude Desktop

Claude Desktop reads MCP server configuration from a JSON file.

### 1. Find the config file

| OS | Path |
|----|------|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

### 2. Add the server

Open the config file (create it if it doesn't exist) and add the `happycowler` entry inside `"mcpServers"`:

```json
{
  "mcpServers": {
    "happycowler": {
      "command": "python",
      "args": ["/absolute/path/to/happycowler-mcp/server.py"]
    }
  }
}
```

Replace `/absolute/path/to/happycowler-mcp/server.py` with the real path on your machine.

**If you have other MCP servers already configured**, just add the `"happycowler"` block alongside them:

```json
{
  "mcpServers": {
    "some-other-server": { "...": "..." },
    "happycowler": {
      "command": "python",
      "args": ["/absolute/path/to/happycowler-mcp/server.py"]
    }
  }
}
```

### 3. Restart Claude Desktop

Quit and reopen Claude Desktop. You should see a hammer icon (🔨) in the chat input bar, indicating MCP tools are available.

### 4. Test it

Type a message like:

> *"What vegan restaurants are there in Worms, Germany?"*

Claude will call the `search_restaurants` tool automatically and present the results.

---

## Setup with Claude CLI (claude-code)

The Claude CLI supports MCP servers via the `claude mcp` command.

### Add the server

```bash
claude mcp add happycowler python /absolute/path/to/happycowler-mcp/server.py
```

Verify it was added:

```bash
claude mcp list
```

You should see `happycowler` in the list.

### Use it in a session

Start a Claude session and ask:

```bash
claude
```

Then type:

> *"Find the top-rated fully vegan restaurants in Tokyo, Japan."*

### Scope options

By default `claude mcp add` adds the server to your **user-level** config (available in all projects). To limit it to the current project only:

```bash
claude mcp add --scope project happycowler python /absolute/path/to/happycowler-mcp/server.py
```

### Remove the server

```bash
claude mcp remove happycowler
```

---

## How It Works

1. You ask Claude a natural language question about vegan/vegetarian restaurants.
2. Claude constructs the correct HappyCow city URL (e.g. `https://www.happycow.net/south-america/peru/lima/`) and calls the `search_restaurants` tool.
3. The tool crawls the HappyCow listing page and returns structured JSON — name, type, rating, address, phone, hours, cuisine, and description for each restaurant.
4. Claude presents the results in whatever format you asked for.

### HappyCow URL pattern

The tool accepts any HappyCow city listing URL. The format is:

```
https://www.happycow.net/{region}/{country}/{city}/
```

Common regions: `europe`, `north-america`, `south-america`, `asia`, `africa`, `oceania`, `middle-east`

| City | URL |
|------|-----|
| Lima, Peru | `https://www.happycow.net/south-america/peru/lima/` |
| Tokyo, Japan | `https://www.happycow.net/asia/japan/tokyo/` |
| Berlin, Germany | `https://www.happycow.net/europe/germany/berlin/` |
| New York, USA | `https://www.happycow.net/north-america/usa/new-york/` |
| London, UK | `https://www.happycow.net/europe/england/london/` |
| Sydney, Australia | `https://www.happycow.net/oceania/australia/sydney/` |

---

## Tool Reference

### `search_restaurants`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `city_url` | string | *(required)* | Full HappyCow city listing URL |
| `type_filter` | string | `"all"` | `"all"` · `"vegan"` · `"vegetarian"` · `"veg-friendly"` |
| `max_results` | integer | `50` | Maximum number of restaurants to return |

**Returns:** JSON array. Each item contains:

```json
{
  "name":        "Loving Hut",
  "type":        "Vegan",
  "rating":      "4.5",
  "address":     "123 Main St, Lima, Peru",
  "phone":       "+51 1 234 5678",
  "hours":       "Mon-Sun 11am-9pm",
  "cuisine":     "Cuisine: Asian",
  "description": "International vegan chain with a varied menu."
}
```

---

## Disclaimer

Crawling HappyCow may be against their Terms of Service. Use responsibly and consider supporting HappyCow directly at [happycow.net](https://happycow.net/).
