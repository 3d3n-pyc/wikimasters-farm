# wikimasters-farm

Multi-account farming bot for [WikiMasters](https://www.wiki-masters.com).

Automates daily routines across secondary accounts and transfers progress to a main account:
- Opening daily booster packs (with automatic Cloudflare Turnstile handling)
- Claiming completed achievements for WikiBidous (WB)
- Bulk-discarding duplicate cards (Common, Uncommon, duplicate Rares) into WikiBidous
- Proposing daily trades to the main account with missing cards and WB
- Safely accepting incoming trades on the main account while verifying counterparties

## Requirements

- Python 3.10+
- Firefox dependencies (for Camoufox headless browser)

## Installation

```bash
git clone https://github.com/your-username/wikimasters-farm.git
cd wikimasters-farm

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Download Camoufox browser binaries
camoufox fetch
```

## Configuration

Create `accounts.json` at the root of the project:

```json
[
  {
    "email": "main@example.com",
    "password": "your_password",
    "is_target": true
  },
  {
    "email": "bot1@example.com",
    "password": "your_password",
    "is_target": false
  },
  {
    "email": "bot2@example.com",
    "password": "your_password",
    "is_target": false
  }
]
```

- Exactly one account must have `"is_target": true` (the main account receiving cards/WB).
- All other accounts are farm bots.

## Usage

Run the full pipeline:

```bash
python run.py
```

### CLI Options

| Flag | Description |
|---|---|
| `--limit N`, `-l N` | Run only on the first N farm accounts |
| `--accounts a@b.com ...`, `-a ...` | Filter run to specific account emails |
| `--concurrency N`, `-c N` | Number of accounts processed concurrently (default: 3) |
| `--skip-packs` | Skip opening booster packs |
| `--skip-trades` | Skip proposing and accepting trades |
| `--accept-only` | Only accept pending trades on the main account |
| `--sync-target` | Refresh the main account collection cache |
| `--force-trade` | Bypass daily trade limits and force proposals |
| `--debug` | Enable verbose debug logging |

### Examples

```bash
# Test run on 2 bots
python run.py --limit 2

# Fast run without opening packs (discard + trade only)
python run.py --skip-packs

# Accept incoming trades on main
python run.py --accept-only
```

## How It Works

1. **Target Setup**: Initializes the main account session, auto-accepts pending friend requests, opens packs, and refreshes the local card cache.
2. **Concurrent Farming**:
   - Each bot connects via fast HTTP requests using cached Supabase JWT sessions.
   - If Cloudflare Turnstile anti-bot verification is triggered, Camoufox is launched headlessly to solve it.
   - Booster packs are opened with rate-limit backoff.
   - Unlocked achievements are claimed for WB.
   - Excess/duplicate cards are discarded into WB.
   - A trade offer is constructed prioritizing missing cards for the target, attaching WB and a token Common card to respect game trade rules.
3. **Trade Harvesting**: The main account reviews incoming trades, checks that the initiator is an authorized farm account, verifies safety constraints, and accepts them.
