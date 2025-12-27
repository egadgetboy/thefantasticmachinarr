# TFM Development Environment

This folder contains the development and testing environment for The Fantastic Machinarr.

## Quick Start

```bash
# Clone the repo
git clone https://github.com/egadgetboy/thefantasticmachinarr.git tfm-test
cd tfm-test

# Run tests with mock servers
python dev/tests/test_runner.py
```

---

## Test Container Setup

### Docker Compose YAML

Add this to your `docker-compose.yml`:

```yaml
services:
  tfm-test:
    container_name: tfm-test
    build:
      context: /mnt/hddpool/scripts/tfm-test
      dockerfile: Dockerfile
    image: tfm-test:latest
    ports:
      - "8081:8080"
    volumes:
      - /mnt/hddpool/scripts/tfm-test/config:/config
    environment:
      - TZ=America/Chicago
    user: "1000:1000"
    restart: unless-stopped
```

### Setup Commands

```bash
# Create directory and clone
mkdir -p /mnt/hddpool/scripts/tfm-test/config
cd /mnt/hddpool/scripts/tfm-test
git clone https://github.com/egadgetboy/thefantasticmachinarr.git .

# Build and start
docker compose up -d tfm-test
```

### Access

- **Test UI**: http://your-server:8081
- **Live UI**: http://your-server:8080 (unchanged)

---

## Container Reference

| Container | Purpose | Port | Config Path |
|-----------|---------|------|-------------|
| `fantastic-machinarr` | **LIVE** - Real Sonarr/Radarr | 8080 | `/mnt/hddpool/scripts/tfm/config` |
| `tfm-test` | **TEST** - Development/Testing | 8081 | `/mnt/hddpool/scripts/tfm-test/config` |

---

## Mock Servers

The mock servers (`dev/tests/mock_servers.py`) provide fictional content for testing without touching real data.

### Running Mock Servers Standalone

```bash
cd /path/to/tfm-test
python dev/tests/mock_servers.py
```

This starts:
- Mock Sonarr on port 18989
- Mock Radarr on port 17878  
- Mock SABnzbd on port 18080

### Fictional Test Data

#### Movies (11 total)

| Title | Year | Tier | Has File |
|-------|------|------|----------|
| Quantum Paradox | 2025 | 🔥 Hot | No |
| The Last Algorithm | 2025 | 🔥 Hot | No |
| Nebula Rising | 2025 | 🔥 Hot | Yes |
| Chrome Hearts | 2025 | 🔥 Hot | No |
| Synthetic Dreams | 2024 | 🌡️ Warm | No |
| The Copper Key | 2024 | 🌡️ Warm | Yes |
| Midnight Protocol | 2024 | 🌡️ Warm | No |
| Binary Sunset | 2023 | ❄️ Cool | No |
| The Glass Fortress | 2022 | ❄️ Cool | Yes |
| Echo Chamber | 2020 | 🧊 Cold | No |
| The Forgotten Code | 2018 | 🧊 Cold | No |

#### TV Series (4 total)

| Title | Year | Seasons | Episodes |
|-------|------|---------|----------|
| Starfall Academy | 2025 | 1 | 10 |
| The Digital Frontier | 2024 | 2 | 20 |
| Quantum Detectives | 2023 | 1 | 10 |
| Neon Nights | 2020 | 3 | 30 |

#### Mock Queue Items

- Active downloads with progress indicators
- Stuck items (no files found, not an upgrade)
- Various warning states for testing queue resolution

---

## Running Tests

### Quick Test

```bash
cd /path/to/tfm-test
python dev/tests/test_runner.py
```

### Expected Output

```
============================================================
🎬 THE FANTASTIC MACHINARR - TEST SUITE
============================================================

Using fictional test data - no real content involved.

🚀 Starting Mock Servers...
✅ Mock Sonarr running on http://127.0.0.1:18989
✅ Mock Radarr running on http://127.0.0.1:17878
✅ Mock SABnzbd running on http://127.0.0.1:18080

📡 Testing Mock Servers...
  ✅ Sonarr: OK
  ✅ Radarr: OK
  ✅ SABnzbd: OK

📊 Testing Mock Data...
  ✅ Sonarr Series: 4 series
  ✅ Sonarr Missing: ~20 episodes
  ✅ Radarr Movies: 11 movies
  ✅ Radarr Missing: 8 movies
  ✅ Sonarr Queue: 2 items
  ✅ SABnzbd Queue: 2 items

🎯 Testing Tier Classification...
  ✅ 10 days old → hot
  ✅ 100 days old → warm
  ✅ 500 days old → cool
  ✅ 1500 days old → cold

============================================================
📊 TEST RESULTS
============================================================
  ✅ PASS - mock_servers
  ✅ PASS - mock_data
  ✅ PASS - tier_classification
  ✅ PASS - tfm_startup

  Total: 4/4 passed

🎉 ALL TESTS PASSED!
```

---

## Development Workflow

### 1. Make Changes

Edit files in the tfm-test directory.

### 2. Test Locally

```bash
python dev/tests/test_runner.py
```

### 3. Test in Container

```bash
# Rebuild and restart test container
cd /mnt/hddpool/scripts/tfm-test
git pull origin main
docker build --no-cache -t tfm-test:latest .
docker restart tfm-test
```

### 4. Deploy to Production

Once tested, the same code is pushed to the main branch (without the dev folder) for the live container:

```bash
# Update live container
cd /mnt/hddpool/scripts/tfm
git pull origin main
docker build --no-cache -t fantastic-machinarr:latest .
docker restart fantastic-machinarr
```

---

## File Structure

```
dev/
├── README.md              # This file
└── tests/
    ├── __init__.py
    ├── mock_servers.py    # Fictional Sonarr/Radarr/SABnzbd servers
    ├── test_runner.py     # Automated test suite
    └── test_full_system.py # Full system integration tests
```

---

## Port Reference

| Service | Live Port | Mock Port |
|---------|-----------|-----------|
| TFM Web UI | 8080 | 8081 |
| Sonarr | 8989 | 18989 |
| Radarr | 7878 | 17878 |
| SABnzbd | 8080 | 18080 |

Mock ports are intentionally different to avoid conflicts with real services.

---

## Troubleshooting

### Tests fail to start mock servers

Check if ports are in use:
```bash
netstat -tlnp | grep -E "18989|17878|18080"
```

### Container won't build

```bash
# Clean rebuild
docker build --no-cache -t tfm-test:latest .
```

### Check container logs

```bash
docker logs tfm-test
```
