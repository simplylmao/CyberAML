# 🛡️ CyberAML Shield

> **AI-powered Anti-Money Laundering & Cybersecurity threat detection platform**  
> Real-time transaction risk scoring · Neo4j graph-based mule ring detection · Gemini AI analysis

---

## 🔍 What is CyberAML Shield?

CyberAML Shield is an enterprise-grade AML (Anti-Money Laundering) and cybersecurity convergence platform that scores financial transactions across **24 risk factors** in **8 signal domains**, detects coordinated money mule networks using a **Neo4j graph database**, and delivers board-level intelligence summaries via **Google Gemini AI**.

Built for compliance teams, financial intelligence units, and fraud analysts — it processes individual transactions or bulk CSV uploads of thousands of records in real-time.

---

## 🚨 Problem Statement

Financial institutions face a dual threat: **money laundering** and **cybercrime** increasingly converge in the same transactions. Traditional rule-based systems miss this convergence:

- A wire transfer to a sanctioned country via a crypto wallet looks like two separate alerts in legacy systems
- Money mule rings span hundreds of accounts — impossible to detect row-by-row
- Compliance teams drown in false positives, missing the real threats
- No single platform combines AML signals (PEP status, sanctions screening) with cyber signals (IP geolocation mismatch, device fingerprint anomalies)

**The result:** Financial crime goes undetected. Institutions face regulatory fines. Criminals move money freely.

---

## ✅ Our Solution

CyberAML Shield unifies **AML + cyber signals** into a single convergence score with:

- **24-factor risk engine** spanning 8 domains (CYBER, AML, DEMO, GEO, BEHAV, PROD, NETW, SCRN)
- **Convergence multipliers** (up to ×1.50) when multiple high-risk signals co-occur
- **Neo4j graph analytics** for detecting coordinated mule rings from real transaction data
- **Bulk CSV scanner** for processing entire day's transactions in seconds
- **Gemini AI** writing executive summaries fit for board/regulator reporting

---

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Streamlit Frontend                        │
│  Dashboard │ CAML Score │ Bulk Scanner │ Mule Radar │ Database  │
└────────────────────────┬────────────────────────────────────────┘
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
  ┌───────────────┐ ┌─────────┐ ┌─────────────┐
  │  Risk Scoring │ │ Gemini  │ │    Neo4j    │
  │    Engine     │ │   AI    │ │   AuraDB    │
  │  (24 factors) │ │  API    │ │ Graph Store │
  └───────┬───────┘ └─────────┘ └──────┬──────┘
          │                             │
          ▼                             ▼
  ┌───────────────┐             ┌─────────────┐
  │   SQLite DB   │             │   Cypher    │
  │  cyberaml.db  │             │Ring Queries │
  └───────────────┘             └─────────────┘
```

---

## ✨ Key Features

### 🔢 24-Factor CAML Risk Score
Scores every transaction 0–200 across 8 signal domains:

| Domain | Signals |
|--------|---------|
| **CYBER** | IP/billing country mismatch, login attempts, new device, device changes |
| **AML** | Source of funds, customer type, beneficial ownership layers |
| **DEMO** | Account age, customer country risk |
| **GEO** | Destination country, counterparty country |
| **BEHAV** | Velocity (txns today), behavior change %, structuring, round-number bias |
| **PROD** | Account type, payment channel |
| **NETW** | Linked flagged accounts |
| **SCRN** | Sanctions screening, adverse media, law enforcement match, PEP status |

**Convergence Multiplier:** When AML + Cyber signals co-occur, scores are multiplied (up to ×1.50) — reflecting the real-world elevation in risk.

### 📂 Bulk CSV Scanner (Enterprise Batch Processing)
- Upload any bank export or core banking dump — **no fixed template required**
- **100+ column name aliases** auto-detected (e.g. `amount`/`txn_amount`/`value`/`amt` all work)
- Processes up to **10,000 rows** with live progress bar
- Batch analytics dashboard: KPI cards, risk distribution, value at risk
- Gemini AI writes a **board-ready executive brief** from batch statistics
- Export flagged results (Critical + High) as CSV

### 🕸️ Mule Radar — Neo4j Live Graph Detection
- Pushes scored transactions into **Neo4j AuraDB** as a property graph
- **3 Cypher ring detection patterns:**
  - **Sanctioned Hub** — Multiple senders transacting to sanctioned countries (KP, IR, SY...)
  - **IP Geo Cluster** — Accounts sharing high-risk IP origin country
  - **PEP High-Value** — Politically Exposed Persons sending large transactions
- Detected rings rendered as **interactive D3.js network graphs**
- Gemini AI writes a detailed ring analysis on demand

### 🤖 Gemini AI Integration
- Per-transaction analysis: explains *why* a score is high in plain English
- Ring analysis: investigative narrative on detected mule networks
- Bulk executive summary: Chief AML Officer-style board brief

### 📊 Live Alert Feed & Dashboard
- Real-time transaction stream with risk badges
- Dashboard KPIs: total transactions, risk distribution, average score, value at risk
- Historical scoring from SQLite database

---

## 🛠️ Technologies Used

| Layer | Technology |
|-------|-----------|
| Frontend / App | Python · Streamlit |
| Risk Scoring Engine | Pure Python (custom 24-factor model) |
| Graph Database | Neo4j AuraDB (cloud) · Cypher query language |
| AI / LLM | Google Gemini 1.5 Flash API |
| Network Visualization | D3.js v7 (force-directed graphs) |
| Local Database | SQLite (via Python `sqlite3`) |
| Data Processing | Pandas |
| Deployment | Streamlit Community Cloud |

---

## 🚀 Setup Instructions

### Prerequisites
- Python 3.9+
- A Google Gemini API key ([get one free](https://makersuite.google.com/app/apikey))
- Neo4j AuraDB free instance ([sign up](https://neo4j.com/cloud/aura/))

### 1. Clone the repository
```bash
git clone https://github.com/YOUR_USERNAME/cyberaml-shield.git
cd cyberaml-shield
```

### 2. Install dependencies
```bash
pip install streamlit pandas neo4j google-generativeai
```

### 3. Configure credentials
Open `app.py` and update the following near the top of the file:

```python
# Gemini
GEMINI_API_KEY = "your_gemini_api_key_here"

# Neo4j
NEO4J_URI      = "neo4j+s://YOUR_INSTANCE.databases.neo4j.io"
NEO4J_USER     = "neo4j"
NEO4J_PASSWORD = "your_neo4j_password"
NEO4J_DATABASE = "neo4j"
```

### 4. Run the app
```bash
streamlit run app.py
```

The app opens at `http://localhost:8501`

### 5. First-time demo flow
1. Go to **Bulk CSV Scanner** → click **Download Sample CSV**
2. Upload the downloaded file → click **Scan All Rows**
3. After scan completes → click **Push All Results to Neo4j Graph**
4. Navigate to **Mule Radar → Live Graph (Neo4j)** tab
5. Click **Run Ring Detection** to see live patterns
6. Click **Generate Gemini Executive Summary** for a board-level brief

---

## 📁 Project Structure

```
cyberaml-shield/
├── app.py              # Main Streamlit application (all-in-one)
├── README.md           # This file
└── cyberaml.db         # SQLite database (auto-created on first run)
```

---

## 🌐 Live Demo

🔗 **[Live App on Streamlit Cloud](https://your-app.streamlit.app)** *(update with your URL)*

---

## 👥 Team

| Name | Role |
|------|------|
| *(Add your name)* | *(Add your role)* |

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.
