# 🛡️ CyberAML Shield

> **AI-powered Anti-Money Laundering & Cybersecurity Threat Detection Platform**

Real-time transaction risk scoring · Graph-based mule network detection · Gemini AI analysis

---

## 🔍 What is CyberAML Shield?

**CyberAML Shield** is an AML and cybersecurity convergence platform designed to identify suspicious financial transactions by combining traditional Anti-Money Laundering indicators with cybersecurity and behavioral signals.

The platform evaluates transactions across **24 risk factors and 8 signal domains**, producing a **CAML risk score from 0–200**.

It also provides:

* Individual transaction risk scoring
* Bulk CSV transaction scanning
* Behavioral and cybersecurity analysis
* Graph-based relationship visualization
* Potential mule-network identification
* SQLite transaction history
* Gemini-powered investigation summaries
* Executive-level AML intelligence reports

The project was developed by **Aditya**, a student at **VIT Chennai**, as a **hackathon project**.

---

## 🚨 Problem Statement

Financial crime increasingly combines traditional money-laundering techniques with cyber-enabled attacks.

Traditional rule-based monitoring systems often analyze transactions independently. This can make it difficult to identify situations where several seemingly unrelated indicators occur together.

For example:

* A new device performs multiple high-value transfers.
* The account suddenly changes its transaction behavior.
* Funds are sent through a higher-risk payment channel.
* Multiple accounts appear connected through common destinations.
* A customer has sanctions, PEP, or adverse-media indicators.

Individually, these signals may produce weak alerts.

Together, they can indicate a much more significant financial-crime threat.

CyberAML Shield addresses this problem by combining these signals into a unified risk model.

---

## ✅ Solution

CyberAML Shield combines AML, cybersecurity, behavioral, geographic and network indicators into a single **CAML risk score**.

The system provides:

### 1. 24-Factor Risk Engine

Transactions are evaluated across eight signal domains:

| Domain    | Example Signals                                             |
| --------- | ----------------------------------------------------------- |
| **CYBER** | IP mismatch, login attempts, new device, device changes     |
| **AML**   | Source of funds, customer type, ownership complexity        |
| **DEMO**  | Account age, customer-country risk                          |
| **GEO**   | Destination and counterparty risk                           |
| **BEHAV** | Velocity, behavioral change, structuring, round-number bias |
| **PROD**  | Account type, payment channel                               |
| **NETW**  | Linked flagged accounts                                     |
| **SCRN**  | Sanctions, adverse media, law enforcement, PEP              |

---

## 🎯 CAML Risk Score

The scoring engine produces a score from:

**0 → 200**

Risk levels are:

|   Score | Level       |
| ------: | ----------- |
|    0–39 | 🟢 LOW      |
|   40–69 | 🟡 MEDIUM   |
|   70–99 | 🟠 HIGH     |
| 100–200 | 🔴 CRITICAL |

---

## 🔀 Convergence Scoring

One of the central ideas behind CyberAML Shield is that AML and cybersecurity signals should not always be treated independently.

When multiple high-risk domains appear together, the system applies a convergence multiplier.

Current multipliers include:

* **1.00×** — normal
* **1.20×** — multiple active risk domains
* **1.35×** — significant cross-domain activity
* **1.50×** — strong AML + cybersecurity convergence

This allows combinations of otherwise moderate indicators to produce an appropriately elevated risk score.

---

## 📂 Bulk CSV Scanner

The Bulk Scanner allows an analyst to upload transaction data and score hundreds or thousands of records.

Features include:

* CSV upload
* Automatic column alias recognition
* Row-by-row risk scoring
* Live progress bar
* Risk distribution
* Value-at-risk calculation
* High/Critical transaction filtering
* CSV export
* Gemini executive summary

The application recognizes multiple common column names, such as:

```text
amount
txn_amount
transaction_amount
value
amt
```

and maps them into the internal scoring model.

---

## 🕸️ Mule Radar

CyberAML Shield includes a graph-style network visualization showing relationships between:

```text
Customer
   │
   ├──── Transaction
   │
   └──── Destination Country
```

The visualization can help analysts identify:

* Customers with unusually high transaction counts
* Customers connected to multiple destinations
* High-risk customers
* Repeated relationships
* Potential coordinated activity

The visualization uses **D3.js** and does not require an external Neo4j server.

---

## 🤖 Gemini AI

Google Gemini can provide natural-language analysis on top of the deterministic risk engine.

Gemini can generate:

### Transaction Analysis

Explains why a transaction received a particular risk score.

### Mule Network Analysis

Provides investigative context around suspicious customer relationships.

### Executive Summary

Produces a concise AML intelligence brief covering:

* Overall risk
* Major indicators
* Potential laundering behavior
* Cybersecurity convergence
* Recommended investigation actions

The application continues to work without Gemini. The deterministic risk engine does not depend on an external AI service.

---

## 📊 Dashboard

The dashboard provides an overview of:

* Total transactions
* Critical alerts
* High-risk transactions
* Average CAML score
* Value at risk
* Risk distribution
* Recent alerts

---

## 🗄️ Local Database

CyberAML Shield uses SQLite to retain transaction scoring history.

Database file:

```text
cyberaml.db
```

The database is automatically created when the application starts.

The database stores:

* Transaction ID
* Customer ID
* Amount
* Destination country
* Risk score
* Risk level
* Timestamp

---

## 🏗️ Architecture

```text
┌──────────────────────────────────────────────────────────┐
│                  Streamlit Frontend                      │
│                                                          │
│ Dashboard │ CAML Score │ Bulk Scanner │ Mule Radar      │
│                         │                │                │
└─────────────────────────┼────────────────┼────────────────┘
                          │                │
              ┌───────────▼───────┐   ┌──▼──────────────┐
              │  Risk Engine      │   │ Graph Engine    │
              │                   │   │                │
              │ 24 Risk Factors   │   │ D3.js Network  │
              │ 8 Signal Domains  │   │ Visualization   │
              └───────────┬───────┘   └────────────────┘
                          │
                ┌─────────▼─────────┐
                │    SQLite DB      │
                │ Transaction       │
                │ History           │
                └─────────┬─────────┘
                          │
                ┌─────────▼─────────┐
                │    Gemini AI      │
                │ Investigation &   │
                │ Executive Reports │
                └───────────────────┘
```

---

## 🛠️ Technologies

| Layer           | Technology                |
| --------------- | ------------------------- |
| Frontend        | Python + Streamlit        |
| Risk Engine     | Python                    |
| Data Processing | Pandas + NumPy            |
| Database        | SQLite                    |
| Visualization   | D3.js                     |
| AI              | Google Gemini             |
| Deployment      | Streamlit Community Cloud |

---

## 🚀 Running Locally

### Requirements

* Python 3.9+
* pip
* Optional Google Gemini API key

### Clone the repository

```bash
git clone https://github.com/simplylmao/cyberaml-shield.git
cd cyberaml-shield
```

### Install dependencies

```bash
pip install -r requirements.txt
```

### Run

```bash
streamlit run app.py
```

The application will normally be available at:

```text
http://localhost:8501
```

---

## 🤖 Configure Gemini

Gemini is optional.

For local development, create:

```text
.streamlit/secrets.toml
```

and add:

```toml
GEMINI_API_KEY = "your-api-key"
```

Do **not** commit the real API key to GitHub.

The `.gitignore` already excludes:

```text
.streamlit/secrets.toml
```

---

## ☁️ Streamlit Community Cloud

1. Push the project to GitHub.
2. Open Streamlit Community Cloud.
3. Create a new application.
4. Select:

```text
simplylmao/cyberaml-shield
```

5. Set the main file to:

```text
app.py
```

6. Add the following secret:

```toml
GEMINI_API_KEY = "your-api-key"
```

7. Deploy.

The application can run without Gemini, but adding the API key enables AI-generated investigation and executive summaries.

---

## 🧪 Demo Workflow

For a quick demonstration:

### Step 1

Open:

```text
Bulk Scanner
```

### Step 2

Click:

```text
Download Sample CSV
```

### Step 3

Upload the downloaded CSV.

### Step 4

Click:

```text
Scan All Rows
```

### Step 5

Review:

* Risk distribution
* Critical alerts
* High-risk transactions
* Value at risk

### Step 6

Open:

```text
Mule Radar
```

to view the relationship graph.

### Step 7

If Gemini is configured, generate:

```text
Executive Summary
```

---

## 📁 Project Structure

```text
cyberaml-shield/
│
├── app.py
├── requirements.txt
├── README.md
├── .gitignore
│
├── .streamlit/
│   └── secrets.toml.example
│
└── data/
    └── sample_transactions.csv
```

The SQLite database is automatically generated and should not be committed to GitHub.

---

## 🔐 Security Notes

CyberAML Shield is a hackathon/educational prototype.

Do not upload real customer financial data to an unsecured deployment.

Never commit:

* API keys
* passwords
* production database files
* customer information
* financial institution credentials

Use Streamlit Secrets for deployment credentials.

---

## 🎓 Project Information

**Project:** CyberAML Shield
**Developer:** Aditya
**College:** VIT Chennai
**Team:** Solo
**Event:** Hackathon

---

## 📄 License

MIT License.

Copyright © 2026 Aditya.
