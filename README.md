# 🎬 The Fantastic Machinarr

**Intelligent automation for Sonarr & Radarr that finds your missing content without hammering your indexers.**

TFM is a smart companion app that works alongside your existing Sonarr and Radarr installations. It intelligently searches for missing episodes and movies, manages API limits, handles stuck downloads, and keeps you informed—all without requiring constant attention.

---

## Why TFM?

Sonarr and Radarr are great at *grabbing* content when it appears, but they're not great at *finding* content that's been missing for a while. Their built-in search features either:
- Do nothing (waiting for RSS)
- Search everything at once (hammering your indexers)
- Require manual intervention for each item

**TFM solves this** by intelligently prioritizing what to search, when to search, and when to ask for help.

---

## ✨ Key Features

### 🔥 Tier-Based Prioritization
Content is automatically classified by age into four tiers:

| Tier | Age | Priority | Philosophy |
|------|-----|----------|------------|
| 🔥 **Hot** | 0-7 days | Highest | New releases - search aggressively |
| ☀️ **Warm** | 7-30 days | High | Recent content - search regularly |
| ❄️ **Cool** | 30-180 days | Medium | Older content - search weekly |
| 🧊 **Cold** | 180+ days | Low | Rare content - search monthly, never give up |

### ⚡ Pacing Presets
Choose how aggressive TFM should be based on your indexer limits:

| Preset | API Calls/Day | Best For |
|--------|---------------|----------|
| 🐢 **Steady** | ~500 | Limited indexers, patient users |
| 🐇 **Fast** | ~2,000 | Most users |
| 🚀 **Faster** | ~5,000 | Premium indexers |
| ⚡ **Blazing** | 10,000+ | Unlimited indexers |

Each preset automatically adjusts:
- Search cooldowns per tier
- Maximum attempts before escalation
- When to notify you vs. keep trying

### 🔄 Smart Cooldowns
TFM remembers what it's searched and doesn't waste API calls:

- **Hot items**: Retry quickly (every 10-60 min based on pacing)
- **Cold items**: Retry slowly (weekly/monthly)
- **Already searched**: Skip until cooldown expires
- **Never gives up**: Cool/Cold items keep trying forever, just less often

### 🚨 Intelligent Escalation
When searching isn't working, TFM knows when to ask for help:

**Urgent Interventions** (Hot/Warm items):
- "Searched 24 times over 24 hours without finding"
- Suggests: Dismiss or Reset & Try Again

**Long-Missing Notifications** (Cool/Cold items):
- Milestone alerts at 1, 3, 6, 12, 18, 24 months
- Suggests: Keep Waiting, Search Again, or check elsewhere (YouTube, etc.)

### 📊 Upgrade Searching
TFM doesn't just find missing content—it also searches for **quality upgrades** (cutoff unmet) to improve your existing library.

### ⏰ Quiet Hours
Pause searching during specific hours (e.g., 2 AM - 6 AM) to reduce load during maintenance windows or peak usage times.

### 🔧 Queue Management
Automatically detects and handles stuck downloads:
- Identifies common issues (no files found, sample only, not an upgrade)
- Auto-resolves when possible (blocklist and retry)
- Escalates to manual intervention when needed
- Shows countdown timer until auto-resolution

---

## 📱 Dashboard

The web dashboard gives you complete visibility:

### Scoreboard
- **Finds Today / Total**: Track your success
- **API Calls**: Monitor usage vs. daily limit
- **Status**: Current state (searching, sleeping, idle)

### Activity Bar
Real-time status showing what TFM is doing right now.

### Data Tables with Pagination
All activity panels support:
- 10 items per page
- Up to 500 items in history
- Prev/Next navigation

| Panel | Shows |
|-------|-------|
| **Recent Searches** | Time, Type (missing/upgrade), Source, Title, Tier, Status |
| **Recent Finds** | Time, How Found, Source, Title, Details |
| **Queue Issues** | Stuck duration, Issue type, Auto-resolve countdown |
| **Manual Intervention** | Urgent vs. long-missing, Tier, Search count, Actions |

---

## 🚀 Getting Started

### Prerequisites
- Sonarr v3+ and/or Radarr v3+
- Docker (recommended) or Python 3.9+
- API keys for your Sonarr/Radarr instances

### Docker Installation

```bash
# Clone the repository
git clone https://github.com/egadgetboy/thefantasticmachinarr.git
cd thefantasticmachinarr

# Build the image
docker build -t fantastic-machinarr:latest .

# Run the container
docker run -d \
  --name fantastic-machinarr \
  -p 8080:8080 \
  -v /path/to/config:/config \
  fantastic-machinarr:latest
```

### TrueNAS SCALE
1. Build the image using the command above
2. Create a new container in the TrueNAS UI
3. Map port 8080 and the config volume
4. Start the container

### First Run
1. Open `http://your-server:8080` in your browser
2. The Setup Wizard will guide you through:
   - Adding Sonarr/Radarr instances
   - Choosing a pacing preset
   - Configuring tier thresholds
   - Setting up quiet hours (optional)
   - Configuring email notifications (optional)

---

## ⚙️ Configuration

### Pacing Presets Explained

**🐢 Steady (≤500 API/day)**
- Hot: 1hr cooldown, 24 attempts → 24hr to intervention
- Warm: 6hr cooldown, 8 attempts → 48hr to intervention
- Cool: Weekly, then monthly
- Cold: Monthly, then quarterly

**🐇 Fast (≤2,000 API/day)**
- Hot: 30min cooldown, 16 attempts → 8hr to intervention
- Warm: 3hr cooldown, 8 attempts → 24hr to intervention
- Cool: Every 3 days, then bi-weekly
- Cold: Bi-weekly, then monthly

**🚀 Faster (≤5,000 API/day)**
- Hot: 15min cooldown, 16 attempts → 4hr to intervention
- Warm: 1hr cooldown, 8 attempts → 8hr to intervention
- Cool: Daily, then weekly
- Cold: Weekly, then bi-weekly

**⚡ Blazing (>5,000 API/day)**
- Hot: 10min cooldown, 12 attempts → 2hr to intervention
- Warm: 30min cooldown, 8 attempts → 4hr to intervention
- Cool: Every 6 hours, then every 3 days
- Cold: Every 3 days, then weekly

### Tier Configuration
Customize age thresholds in the wizard or settings:
- Hot: 0-7 days (default)
- Warm: 7-30 days (default)
- Cool: 30-180 days (default)
- Cold: 180+ days (default)

### Search Distribution
Control what percentage of each search cycle goes to each tier:
- Hot: 40% (default)
- Warm: 30% (default)
- Cool: 20% (default)
- Cold: 10% (default)

---

## 🔍 How It Works

### Search Cycle
1. **Gather**: Fetch all missing episodes/movies and cutoff unmet (upgrades)
2. **Classify**: Assign each item to a tier based on age
3. **Filter**: Remove items still in cooldown
4. **Select**: Pick items based on tier distribution percentages
5. **Randomize**: Shuffle within each tier (if enabled)
6. **Search**: Trigger searches via Sonarr/Radarr API
7. **Record**: Track what was searched and when

### Queue Monitoring
1. **Scan**: Check download queues every few minutes
2. **Detect**: Identify stuck items (warnings, errors, stalled)
3. **Track**: Record when items first got stuck
4. **Wait**: Allow configured time for auto-resolution
5. **Resolve**: Auto-fix if possible, or escalate to manual intervention

### Find Detection
1. **Monitor**: Watch for items transitioning from "missing" to "downloaded"
2. **Record**: Log the find with timestamp and resolution type
3. **Count**: Update daily and total find counters

---

## 📧 Notifications (Coming Soon)

Email notifications for:
- Urgent interventions (Hot/Warm search failures)
- Long-missing milestones (1, 3, 6, 12+ months)
- Daily/weekly digest of finds
- Queue issues requiring attention

---

## 🛠️ API Endpoints

TFM provides a REST API for integration:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | Current status and statistics |
| `/api/missing` | GET | Missing items by tier |
| `/api/searches` | GET | Recent search history |
| `/api/finds` | GET | Recent finds |
| `/api/queue` | GET | Queue status and stuck items |
| `/api/interventions` | GET | Items needing attention |
| `/api/search` | POST | Trigger manual search |
| `/api/storage` | GET | Storage space info |
| `/api/config` | GET/POST | Configuration management |

---

## 🤝 Contributing

Contributions are welcome! Please feel free to submit issues and pull requests.

---

## 📜 License

MIT License - see LICENSE file for details.

---

## 🙏 Acknowledgments

- The Sonarr and Radarr teams for their excellent software
- The *arr community for inspiration and feedback

---

**Made with ❤️ for media enthusiasts who want their libraries complete.**
