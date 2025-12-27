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
Content is automatically classified by age into four tiers (fully customizable):

| Tier | Age | Priority | Philosophy |
|------|-----|----------|------------|
| 🔥 **Hot** | 0-90 days | Highest | New releases - search aggressively |
| ☀️ **Warm** | 90-365 days | High | Recent content - search regularly |
| ❄️ **Cool** | 1-3 years | Medium | Older content - search weekly |
| 🧊 **Cold** | 3+ years | Low | Rare content - search monthly, never give up |

*Tier thresholds and search intervals are fully customizable in Settings.*

### ⚡ Pacing Presets
Choose how aggressive TFM should be based on your indexer limits (or create your own):

| Preset | API Calls/Day | Best For |
|--------|---------------|----------|
| 🐢 **Steady** | ~500 | Limited indexers, patient users |
| 🐇 **Fast** | ~2,000 | Most users |
| 🚀 **Faster** | ~5,000 | Premium indexers |
| ⚡ **Blazing** | 10,000+ | Unlimited indexers |

*Presets are starting points—all values can be fine-tuned in Settings.*

### 🔄 Smart Cooldowns
TFM remembers what it's searched and doesn't waste API calls on recently searched items.

### 🚨 Intelligent Escalation
When searching isn't working, TFM knows when to ask for help with manual interventions.

### 📊 Upgrade Searching
TFM also searches for **quality upgrades** (cutoff unmet) to improve your existing library.

### ⏰ Quiet Hours
Pause searching during specific hours to reduce load during maintenance windows.

### 🎨 Color Themes
TFM includes three built-in color themes to suit your preference:
- 🌙 **Dark** - Modern dark theme (default)
- ☀️ **Light** - Warm tan and brown tones
- 🪟 **Windows 98** - Classic retro styling with teal background and 3D beveled buttons

Click the theme button in the header to cycle through themes.

### 🔧 Queue Management
Automatically detects and handles stuck downloads with auto-resolution capabilities.

### 📥 SABnzbd Integration (Optional)
TFM can optionally connect to SABnzbd for enhanced queue monitoring. While Sonarr and Radarr handle most download management, SABnzbd integration allows TFM to:
- Monitor download progress directly
- Detect stuck or stalled downloads faster
- Provide more detailed queue status information

**Note:** SABnzbd is completely optional. TFM works perfectly with just Sonarr/Radarr, which already communicate with your download clients. The SABnzbd integration is for users who want additional visibility into their download queue.

### 🔢 Multi-Instance Support
TFM supports multiple instances of Sonarr, Radarr, and SABnzbd. This is perfect for users who run separate instances for different quality levels:
- **Sonarr** + **Sonarr 4K** (for standard and 4K TV libraries)
- **Radarr** + **Radarr 4K** (for standard and 4K movie libraries)
- **SABnzbd** instances for each

All instances are managed from a single TFM dashboard, with tier counts and search activity shown per-instance.

---

## 📸 Screenshots

### Dark Theme (Default)
*(Coming soon)*

### Light Theme
*(Coming soon)*

### Windows 98 Theme
*(Coming soon)*

### Setup Wizard
*(Coming soon)*

---

## 🚀 Installation

### Prerequisites
- Docker installed on your system
- Sonarr v3+ and/or Radarr v3+ running and accessible
- API keys for your Sonarr/Radarr instances
- (Optional) SABnzbd for enhanced queue monitoring

---

### 🐧 Linux (Ubuntu/Debian/etc.)

```bash
# Clone the repository
git clone https://github.com/egadgetboy/thefantasticmachinarr.git
cd thefantasticmachinarr

# Build the Docker image
docker build -t fantastic-machinarr:latest .

# Create config directory
mkdir -p /opt/tfm/config

# Run the container
docker run -d \
  --name fantastic-machinarr \
  --restart unless-stopped \
  -p 8080:8080 \
  -v /opt/tfm/config:/config \
  fantastic-machinarr:latest
```

Access the web UI at `http://your-server-ip:8080`

---

### 🪟 Windows (Docker Desktop)

1. Install [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/)
2. Open PowerShell or Command Prompt:

```powershell
# Clone the repository
git clone https://github.com/egadgetboy/thefantasticmachinarr.git
cd thefantasticmachinarr

# Build the Docker image
docker build -t fantastic-machinarr:latest .

# Run the container
docker run -d --name fantastic-machinarr --restart unless-stopped -p 8080:8080 -v tfm-config:/config fantastic-machinarr:latest
```

Access the web UI at `http://localhost:8080`

---

### 🍎 macOS (Docker Desktop)

1. Install [Docker Desktop for Mac](https://www.docker.com/products/docker-desktop/)
2. Open Terminal:

```bash
# Clone the repository
git clone https://github.com/egadgetboy/thefantasticmachinarr.git
cd thefantasticmachinarr

# Build the Docker image
docker build -t fantastic-machinarr:latest .

# Create config directory
mkdir -p ~/tfm/config

# Run the container
docker run -d \
  --name fantastic-machinarr \
  --restart unless-stopped \
  -p 8080:8080 \
  -v ~/tfm/config:/config \
  fantastic-machinarr:latest
```

Access the web UI at `http://localhost:8080`

---

### 📦 Unraid

1. Open Unraid terminal (or SSH)
2. Build the image:

```bash
cd /mnt/user/appdata
git clone https://github.com/egadgetboy/thefantasticmachinarr.git
cd thefantasticmachinarr
docker build -t fantastic-machinarr:latest .
```

3. In Unraid web UI, go to **Docker** → **Add Container**
4. Configure:
   - **Name:** fantastic-machinarr
   - **Repository:** fantastic-machinarr:latest
   - **Network Type:** Bridge
   - **Port:** 8080 → 8080
   - **Path:** /mnt/user/appdata/tfm/config → /config
5. Click **Apply**

Access the web UI at `http://your-unraid-ip:8080`

---

### 🗄️ OpenMediaVault (OMV)

1. Install Docker via OMV-Extras if not already installed
2. SSH into your OMV server:

```bash
# Clone the repository
cd /srv/dev-disk-by-label-*/appdata  # adjust path to your data drive
git clone https://github.com/egadgetboy/thefantasticmachinarr.git
cd thefantasticmachinarr

# Build the Docker image
docker build -t fantastic-machinarr:latest .

# Create config directory
mkdir -p /srv/dev-disk-by-label-*/appdata/tfm/config

# Run the container
docker run -d \
  --name fantastic-machinarr \
  --restart unless-stopped \
  -p 8080:8080 \
  -v /srv/dev-disk-by-label-*/appdata/tfm/config:/config \
  fantastic-machinarr:latest
```

Or use Portainer (if installed via OMV-Extras) to manage the container.

Access the web UI at `http://your-omv-ip:8080`

---

### 🐠 TrueNAS SCALE

1. SSH into TrueNAS or use Shell from web UI
2. Clone and build:

```bash
cd /mnt/pool/scripts  # adjust to your pool name
git clone https://github.com/egadgetboy/thefantasticmachinarr.git tfm
cd tfm
docker build -t fantastic-machinarr:latest .
```

3. In TrueNAS web UI, go to **Apps** → **Discover Apps** → **Custom App**
4. Configure:
   - **Application Name:** fantastic-machinarr
   - **Image Repository:** fantastic-machinarr
   - **Image Tag:** latest
   - **Port:** 8080 (container) → 8787 (node port, or your choice)
   - **Storage:** Add host path mount
     - Host Path: `/mnt/pool/scripts/tfm/config`
     - Mount Path: `/config`
5. Save and deploy

Access the web UI at `http://your-truenas-ip:8787`

**Updating on TrueNAS:**
```bash
cd /mnt/pool/scripts/tfm && git pull origin main && docker build --no-cache -t fantastic-machinarr:latest .
```
Then restart the app from TrueNAS UI.

---

### 🐳 Docker Compose

Create a `docker-compose.yml` file:

```yaml
version: '3.8'
services:
  fantastic-machinarr:
    build: .
    container_name: fantastic-machinarr
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - ./config:/config
```

Then run:
```bash
git clone https://github.com/egadgetboy/thefantasticmachinarr.git
cd thefantasticmachinarr
docker-compose up -d
```

---

## 🔧 First Run Setup

1. Open the web UI at `http://your-server:8080`
2. The Setup Wizard will guide you through:
   - Adding Sonarr/Radarr instances (URL + API key)
   - Adding SABnzbd (optional, for enhanced queue monitoring)
   - Choosing a pacing preset
   - Configuring tier thresholds (optional)
   - Setting up quiet hours (optional)
   - Configuring email notifications (optional)

---

## 📱 Dashboard

The web dashboard provides:

- **Scoreboard**: Finds today/total, API calls, next search countdown
- **Missing Content by Tier**: Visual breakdown of your library gaps
- **Search Activity**: Recent searches with status
- **Recent Finds**: Successfully grabbed content
- **Queue Issues**: Stuck downloads with auto-resolve
- **Manual Interventions**: Items needing your attention

---

## 🔄 Updating

```bash
cd /path/to/thefantasticmachinarr
git pull origin main
docker build --no-cache -t fantastic-machinarr:latest .
docker stop fantastic-machinarr
docker rm fantastic-machinarr
# Then recreate the container using your platform's method above
```

---

## 🛠️ API Endpoints

TFM provides a REST API for integration:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | Current status and statistics |
| `/api/dashboard` | GET | Dashboard data with tier counts |
| `/api/scoreboard` | GET | Quick scoreboard data |
| `/api/missing` | GET | Missing items by tier |
| `/api/searches` | GET | Recent search history |
| `/api/finds` | GET | Recent finds |
| `/api/queue` | GET | Queue status and stuck items |
| `/api/interventions` | GET | Items needing attention |
| `/api/search` | POST | Trigger manual search |
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
