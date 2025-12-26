# 🎬 The Fantastic Machinarr (TFM)

**Intelligent media library automation for Sonarr and Radarr**

TFM is a companion tool that helps Sonarr and Radarr find content they can't find on their own. It uses tier-based prioritization, automatic queue resolution, and smart API rate limiting.

## ✨ Features

- **🔥 Tier-Based Searching** - Hot/Warm/Cool/Cold priorities with configurable intervals
- **🔧 Auto Queue Resolution** - Automatically resolves stuck downloads
- **🖐️ Manual Intervention** - UI for handling issues that need human decisions
- **📊 API Rate Limiting** - Configurable daily limits to prevent indexer bans
- **📧 Email Notifications** - Batched finds and instant alerts
- **🎯 Multi-Instance Support** - Multiple Sonarr/Radarr/SABnzbd instances

## 📦 Installation

### TrueNAS Scale (Custom App YAML)

1. **Download and extract TFM:**
```bash
cd /mnt/hddpool/scripts
mkdir fantastic_machinarr && cd fantastic_machinarr
wget https://github.com/egadgetboy/thefantasticmachinarr/releases/latest/download/fantastic_machinarr.zip
unzip fantastic_machinarr.zip
mkdir -p config
```

2. **Build the Docker image:**
```bash
docker build -t fantastic-machinarr:latest .
```

3. **Create Custom App in TrueNAS:**
   - Go to Apps → Discover Apps → Custom App
   - Use this YAML:

```yaml
version: "3.8"
services:
  fantastic-machinarr:
    image: fantastic-machinarr:latest
    container_name: fantastic-machinarr
    restart: unless-stopped
    ports:
      - "8787:8080"
    volumes:
      - /mnt/hddpool/scripts/fantastic_machinarr/config:/config
    environment:
      - TZ=America/Chicago
```

4. **Access at:** `http://your-truenas-ip:8787`

---

### Docker (Generic)

```bash
# Clone or download
git clone https://github.com/egadgetboy/thefantasticmachinarr.git
cd thefantasticmachinarr

# Build
docker build -t fantastic-machinarr:latest .

# Run
docker run -d \
  --name fantastic-machinarr \
  --restart unless-stopped \
  -p 8787:8080 \
  -v $(pwd)/config:/config \
  -e TZ=America/Chicago \
  fantastic-machinarr:latest
```

---

### Docker Compose

```yaml
version: '3.8'
services:
  fantastic-machinarr:
    build: .
    container_name: fantastic-machinarr
    restart: unless-stopped
    ports:
      - "8787:8080"
    volumes:
      - ./config:/config
    environment:
      - TZ=America/Chicago
```

```bash
docker-compose up -d
```

---

### Unraid

1. **Using Community Apps (recommended):**
   - Search for "Fantastic Machinarr" in Community Apps
   - Install and configure

2. **Manual Docker:**
   - Go to Docker → Add Container
   - Repository: `ghcr.io/egadgetboy/fantastic-machinarr:latest`
   - Port: `8787` → `8080`
   - Path: `/mnt/user/appdata/fantastic-machinarr` → `/config`

---

### Linux (Bare Metal / systemd)

```bash
# Clone
git clone https://github.com/egadgetboy/thefantasticmachinarr.git
cd thefantasticmachinarr

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create config directory
sudo mkdir -p /etc/fantastic-machinarr
sudo chown $USER:$USER /etc/fantastic-machinarr

# Test run
python -m fantastic_machinarr --config /etc/fantastic-machinarr/config.json --port 8787
```

**Create systemd service:**

```bash
sudo tee /etc/systemd/system/fantastic-machinarr.service << 'EOF'
[Unit]
Description=The Fantastic Machinarr
After=network.target

[Service]
Type=simple
User=YOUR_USER
WorkingDirectory=/path/to/thefantasticmachinarr
ExecStart=/path/to/thefantasticmachinarr/venv/bin/python -m fantastic_machinarr --config /etc/fantastic-machinarr/config.json --port 8787
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable fantastic-machinarr
sudo systemctl start fantastic-machinarr
```

---

### Windows

1. **Install Python 3.11+** from https://python.org

2. **Download and extract TFM:**
   - Download from GitHub releases
   - Extract to `C:\FantasticMachinarr`

3. **Open PowerShell as Administrator:**
```powershell
cd C:\FantasticMachinarr
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

4. **Create config directory:**
```powershell
mkdir C:\ProgramData\FantasticMachinarr
```

5. **Run:**
```powershell
python -m fantastic_machinarr --config C:\ProgramData\FantasticMachinarr\config.json --port 8787
```

6. **Create Windows Service (optional):**
   - Use NSSM: https://nssm.cc/
   - `nssm install FantasticMachinarr`
   - Path: `C:\FantasticMachinarr\venv\Scripts\python.exe`
   - Arguments: `-m fantastic_machinarr --config C:\ProgramData\FantasticMachinarr\config.json`

---

### OpenMediaVault (OMV)

1. **Install Docker via OMV-Extras**

2. **Create folder structure:**
```bash
mkdir -p /srv/dev-disk-by-uuid-XXX/docker/fantastic-machinarr/config
```

3. **Using Portainer or Docker CLI:**
```bash
docker run -d \
  --name fantastic-machinarr \
  --restart unless-stopped \
  -p 8787:8080 \
  -v /srv/dev-disk-by-uuid-XXX/docker/fantastic-machinarr/config:/config \
  -e TZ=Europe/London \
  fantastic-machinarr:latest
```

---

## ⚙️ Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `TZ` | Timezone | `UTC` |
| `SONARR_URL` | Sonarr URL | - |
| `SONARR_API_KEY` | Sonarr API key | - |
| `RADARR_URL` | Radarr URL | - |
| `RADARR_API_KEY` | Radarr API key | - |
| `SABNZBD_URL` | SABnzbd URL | - |
| `SABNZBD_API_KEY` | SABnzbd API key | - |

### Tier System

| Tier | Age | Search Frequency | Description |
|------|-----|------------------|-------------|
| 🔥 Hot | 0-7 days | Every hour | New releases, highest priority |
| ☀️ Warm | 8-30 days | Every 6 hours | Recent content |
| ❄️ Cool | 31-90 days | Daily | Older content |
| 🧊 Cold | 90+ days | Weekly | Archive content |

### Auto-Resolution Options

TFM can automatically resolve these stuck queue issues:

- ✅ No files found / eligible for import
- ✅ File is a sample only
- ✅ Unknown series/movie
- ✅ Unexpected episode
- ✅ Invalid season/episode
- ✅ No audio tracks detected
- ✅ Import failed
- ✅ Download failed
- ⚠️ Path not valid (manual fix recommended)
- ⚠️ Not an upgrade (careful - may lose quality)

---

## 🔌 API

TFM exposes a REST API:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | System status |
| `/api/dashboard` | GET | Dashboard data |
| `/api/missing` | GET | Missing items by tier |
| `/api/queue` | GET | Stuck queue items |
| `/api/interventions` | GET | Manual interventions |
| `/api/search` | POST | Trigger search |
| `/api/resolve` | POST | Resolve stuck item |
| `/api/finds` | GET | Recent finds |
| `/api/logs` | GET | Application logs |

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Open a Pull Request

---

## 📄 License

MIT License - see LICENSE file

---

## 🙏 Acknowledgments

- Sonarr/Radarr teams for the excellent APIs
- The *arr community for inspiration
