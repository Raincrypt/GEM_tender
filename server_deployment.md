# GEM Tender Intelligence — Windows Server 2022 Deployment Guide

This guide describes how to deploy the GEM Tender Procurement system (FastAPI, Nginx, MongoDB, Redis/Memurai, and Ollama) on **Windows Server 2022 Standard**.

---

## 🗂️ Table of Contents
1. [Choose Your Path: Hyper-V VM vs. Native Windows Services](#choose-your-path-hyper-v-vm-vs-native-windows-services)
2. [Option A: Linux VM via Hyper-V (Recommended for CPU-only)](#option-a-linux-vm-via-hyper-v-recommended-for-cpu-only)
3. [Option B: Native Windows Services (Recommended for GPU)](#option-b-native-windows-services-recommended-for-gpu)
4. [Setting Up SSL on Windows (Win-ACME / Let's Encrypt)](#setting-up-ssl-on-windows-win-acme--lets-encrypt)
5. [Windows Firewall Configuration](#windows-firewall-configuration)

---

## Choose Your Path: Hyper-V VM vs. Native Windows Services

```
===================================================================================
   OPTION A: Hyper-V Linux VM                 OPTION B: Native Windows Services
===================================================================================
 [Internet] -> [Nginx (Linux Container)]     [Internet] -> [Nginx.exe (Windows Service)]
                    │                                             │
                    ▼                                             ▼
       [FastAPI (Linux Container)]                  [FastAPI (NSSM Windows Service)]
                    │                                             │
      ┌─────────────┴─────────────┐                 ┌─────────────┴─────────────┐
      ▼                           ▼                 ▼                           ▼
[MongoDB] [Redis] [Ollama] (Linux C.)        [MongoDB Service] [Memurai] [Ollama (Native)]
===================================================================================
```

---

## Option A: Linux VM via Hyper-V (Recommended for CPU-only)

If your server does not have an NVIDIA GPU, this is the easiest path because it runs the exact Linux Docker stack we have already built.

### Step 1 — Enable Hyper-V
Open PowerShell as Administrator and run:
```powershell
# Enable the Hyper-V role and management tools
Install-WindowsFeature -Name Hyper-V -IncludeManagementTools -Restart
```
*Note: Your server will reboot.*

### Step 2 — Create the Virtual Switch
1. Open **Hyper-V Manager** -> **Virtual Switch Manager** (right sidebar).
2. Choose **External** and click **Create Virtual Switch**.
3. Name it `ExternalSwitch`, select your active physical network adapter, check *Allow management operating system to share this network adapter*, and click **OK**.

### Step 3 — Create and Install the VM
1. Download the **Ubuntu Server 22.04 LTS ISO** file.
2. In Hyper-V Manager, click **New** -> **Virtual Machine**.
3. Configure:
   * **Generation**: Generation 2 (highly recommended).
   * **Startup Memory**: At least `8192 MB` (8GB). Uncheck *Use Dynamic Memory*.
   * **Configure Networking**: Connection = `ExternalSwitch`.
   * **Virtual Hard Disk**: Assign at least `50 GB`.
   * **Installation Options**: Install an operating system from a bootable image file -> Select the Ubuntu ISO.
4. **Important Gen 2 Secure Boot settings**:
   * Before booting, go to VM **Settings** -> **Security**.
   * Change Template to **Microsoft UEFI Certificate Authority** (required for Linux boot) or uncheck *Enable Secure Boot*.
5. Start the VM and follow the standard Ubuntu installation steps.

### Step 4 — Install Docker and Run the Stack
Log into your Ubuntu VM via SSH (e.g. `ssh username@vm-ip`) and run:
```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# Install Docker Compose
sudo apt-get install -y docker-compose-plugin

# Clone/copy the project files to the VM, configure your .env, then:
docker compose up -d
```

---

## Option B: Native Windows Services (Recommended for GPU)

If your server has an **NVIDIA GPU**, running natively allows Ollama to utilize CUDA with maximum performance and zero virtualization overhead.

### Step 1 — Install Native Services

#### 1. Ollama for Windows (Native)
* Download the Windows installer from [ollama.com/download/windows](https://ollama.com/download/windows).
* Run the installer. By default, it runs in your user tray.
* To ensure it runs on startup even if no user is logged in, you can configure it as a Windows service, or keep it in startup applications.
* Download your model from PowerShell:
  ```powershell
  ollama pull llama3.1:8b
  ```

#### 2. MongoDB Community Edition
* Download the MSI Installer from [mongodb.com/try/download/community](https://www.mongodb.com/try/download/community).
* Choose **Complete Install** and check **"Run service as Network Service user"** (default).
* Once installed, MongoDB will run automatically on Port `27017`.

#### 3. Redis / Memurai
* Because Redis is not officially supported on Windows, download **Memurai** (Developer/Standard Edition) from [memurai.com](https://www.memurai.com/) or download the community **MSOpenTech Redis MSI** from GitHub.
* Install as a Windows Service on Port `6379`.
* Set your Redis password in `C:\Program Files\Memurai\memurai.conf` or `redis.windows-service.conf`:
  ```conf
  requirepass GemRedis@2024Secure
  ```
* Restart the service:
  ```powershell
  Restart-Service -Name "Memurai" # or "Redis"
  ```

---

### Step 2 — Install Python and Dependencies

1. Download and install **Python 3.12** (Windows Installer) from python.org. Check **"Add python.exe to PATH"**.
2. Install **Tesseract OCR**:
   * Download the Windows binary from UB Mannheim GitHub.
   * Install to `C:\Program Files\Tesseract-OCR`.
   * Add `C:\Program Files\Tesseract-OCR` to your system Environment Variables `PATH`.
3. Install **Poppler**:
   * Download Poppler for Windows (e.g. from Github releases or packaged binary).
   * Extract to `C:\poppler`.
   * Add `C:\poppler\Library\bin` to your system `PATH`.
4. Install Python Dependencies:
   Open PowerShell in the project root (`f:\teneder evolution\tender`) and run:
   ```powershell
   # Create a clean virtual environment
   python -m venv .venv
   
   # Activate virtual environment
   .\.venv\Scripts\Activate.ps1
   
   # Install dependencies
   pip install --upgrade pip
   pip install -r backend/requirements.txt
   ```

---

### Step 3 — Register Services with NSSM

**NSSM (Non-Sucking Service Manager)** is a public domain tool that monitors Windows services and automatically restarts them if they fail.

1. Download NSSM from [nssm.cc](https://nssm.cc/download). Extract the `nssm.exe` (64-bit version) into `C:\Windows\System32\` or the project folder.
2. Register the **FastAPI Backend** Service:
   Run in PowerShell as Administrator:
   ```powershell
   nssm install GEM_Backend
   ```
   A GUI will pop up. Configure these fields:
   * **Application Path**: `F:\teneder evolution\tender\.venv\Scripts\uvicorn.exe`
   * **Startup directory**: `F:\teneder evolution\tender`
   * **Arguments**: `backend.main:app --host 0.0.0.0 --port 8000`
   * Go to **Environment** tab and add these variables (one per line):
     ```env
     OLLAMA_URL=http://localhost:11434/api/generate
     OLLAMA_MODEL=llama3.1:8b
     MONGO_URL=mongodb://gemadmin:GemMongo@2024Secure@localhost:27017/gem_tender?authSource=admin
     REDIS_URL=redis://:GemRedis@2024Secure@localhost:6379/0
     DATABASE_URL=sqlite:///F:/teneder%20evolution/tender/backend/data/gem.db
     JWT_SECRET_KEY=YOUR_SECURE_SECRET_MIN_32_CHARS
     ALLOWED_ORIGINS=http://localhost,http://localhost:80
     ENABLE_DOCS=false
     ```
   * Click **Install Service**.

3. Start the Backend Service:
   ```powershell
   Start-Service -Name "GEM_Backend"
   ```

---

### Step 4 — Configure Nginx for Windows

1. Download Nginx for Windows (Stable zip) from [nginx.org](https://nginx.org/en/download.html).
2. Extract Nginx to `C:\nginx`.
3. Configure `C:\nginx\conf\nginx.conf`. Modify the `http` block to proxy requests to your backend (FastAPI) and serve the frontend files:
   ```nginx
   server {
       listen 80;
       server_name localhost;

       # Frontend Static Files
       location / {
           root "F:/teneder evolution/tender/frontend";
           index dashboard.html;
           try_files $uri $uri/ =404;
       }

       # Backend API Proxy
       location /api/ {
           proxy_pass http://127.0.0.1:8000/;
           proxy_http_version 1.1;
           proxy_set_header Upgrade $http_upgrade;
           proxy_set_header Connection "upgrade";
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;

           # Disable buffering for SSE (Server-Sent Events)
           proxy_buffering off;
           proxy_cache off;
           chunked_transfer_encoding on;
       }
   }
   ```
4. Register **Nginx** as a Windows Service:
   ```powershell
   nssm install GEM_Nginx
   ```
   * **Application Path**: `C:\nginx\nginx.exe`
   * **Startup directory**: `C:\nginx`
   * Click **Install Service**.
5. Start Nginx Service:
   ```powershell
   Start-Service -Name "GEM_Nginx"
   ```

---

## Setting Up SSL on Windows (Win-ACME / Let's Encrypt)

If hosting on a public domain, you need HTTPS. On Windows Server, the easiest way is using **Win-ACME** (a free ACME client for Windows).

1. Download **win-acme** from [win-acme.com](https://www.win-acme.com/).
2. Run `wacs.exe` as Administrator.
3. Choose:
   * `M`: Create new certificate (full options)
   * `1`: Single binding of a host
   * Enter your domain: `yourdomain.com`
   * Choose path verification: `2` (serve files from a local folder) and point to `F:\teneder evolution\tender\frontend`.
   * For the task execution step, choose **Write PEM files to a folder** (e.g. `C:\nginx\certs\`).
4. Update your `nginx.conf` in `C:\nginx\conf\nginx.conf` to configure SSL:
   ```nginx
   server {
       listen 443 ssl http2;
       server_name yourdomain.com;

       ssl_certificate "C:/nginx/certs/yourdomain.com-chain.pem";
       ssl_certificate_key "C:/nginx/certs/yourdomain.com-key.pem";

       # Protocols and ciphers
       ssl_protocols TLSv1.2 TLSv1.3;
       ssl_ciphers HIGH:!aNULL:!MD5;

       # ... (rest of frontend and proxy configuration)
   }
   ```
5. Restart Nginx:
   ```powershell
   Restart-Service -Name "GEM_Nginx"
   ```

---

## Windows Firewall Configuration

Secure your Windows Server by opening only HTTP/HTTPS and SSH, while blocking database and Ollama ports from public access.

Run these PowerShell commands as Administrator:
```powershell
# 1. Allow HTTP (Port 80)
New-NetFirewallRule -DisplayName "GEM Tender HTTP" -Direction Inbound -LocalPort 80 -Protocol TCP -Action Allow

# 2. Allow HTTPS (Port 443)
New-NetFirewallRule -DisplayName "GEM Tender HTTPS" -Direction Inbound -LocalPort 443 -Protocol TCP -Action Allow

# 3. Block external access to MongoDB (Port 27017)
New-NetFirewallRule -DisplayName "Block MongoDB External" -Direction Inbound -LocalPort 27017 -Protocol TCP -Action Block

# 4. Block external access to Redis (Port 6379)
New-NetFirewallRule -DisplayName "Block Redis External" -Direction Inbound -LocalPort 6379 -Protocol TCP -Action Block

# 5. Block external access to Ollama (Port 11434)
New-NetFirewallRule -DisplayName "Block Ollama External" -Direction Inbound -LocalPort 11434 -Protocol TCP -Action Block
```
