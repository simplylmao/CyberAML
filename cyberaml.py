import streamlit as st
import pandas as pd
import numpy as np
import random
import json
import sqlite3
import io
import csv
from datetime import datetime, timedelta
from pathlib import Path

# ── Database setup ─────────────────────────────────────────────────────────────
DB_PATH = Path("cyberaml.db")

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                txn_id TEXT, sender_name TEXT, source TEXT, timestamp TEXT,
                amount REAL, account_age INTEGER, billing_country TEXT, ip_country TEXT,
                txn_hour INTEGER, attempts INTEGER, txns_today INTEGER,
                new_device INTEGER, device_changes INTEGER,
                customer_type TEXT, industry TEXT, source_of_funds TEXT, pep_status TEXT,
                customer_country TEXT, destination_country TEXT, behavior_change_pct INTEGER,
                account_type TEXT, payment_channel TEXT, ownership_layers INTEGER,
                linked_flagged INTEGER, counterparty_country TEXT, sanctions_hit TEXT,
                adverse_media TEXT, law_enforcement TEXT,
                final_score INTEGER, risk_level TEXT, risk_class TEXT,
                base_score INTEGER, multiplier REAL, multiplier_reason TEXT
            )
        """)
        conn.commit()

def save_transaction(txn, source="mock"):
    p = txn["params"]; r = txn["result"]
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO transactions
            (txn_id, sender_name, source, timestamp, amount, account_age,
             billing_country, ip_country, txn_hour, attempts, txns_today,
             new_device, device_changes, customer_type, industry, source_of_funds, pep_status,
             customer_country, destination_country, behavior_change_pct, account_type, payment_channel,
             ownership_layers, linked_flagged, counterparty_country, sanctions_hit, adverse_media, law_enforcement,
             final_score, risk_level, risk_class, base_score, multiplier, multiplier_reason)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            txn["txn_id"], txn["name"], source, txn["time"],
            p.get("amount",0), p.get("account_age",0), p.get("billing_country",""), p.get("ip_country",""),
            p.get("hour",0), p.get("attempts",0), p.get("txns_today",0),
            int(p.get("new_device",0)), p.get("device_changes",0),
            p.get("customer_type",""), p.get("industry",""), p.get("source_of_funds",""), p.get("pep_status",""),
            p.get("customer_country",""), p.get("destination_country",""), p.get("behavior_change_pct",0),
            p.get("account_type",""), p.get("payment_channel",""), p.get("ownership_layers",0),
            p.get("linked_flagged",0), p.get("counterparty_country",""), p.get("sanctions_hit",""),
            p.get("adverse_media",""), p.get("law_enforcement",""),
            r["final_score"], txn["level"], txn["class"],
            r["base_total"], r["multiplier"], r["multiplier_reason"] or ""
        ))
        conn.commit()

def load_transactions(source_filter=None, level_filter=None, limit=500):
    q = "SELECT * FROM transactions WHERE 1=1"
    params = []
    if source_filter:
        q += f" AND source IN ({','.join('?'*len(source_filter))})"
        params += source_filter
    if level_filter:
        q += f" AND risk_level IN ({','.join('?'*len(level_filter))})"
        params += level_filter
    q += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(q, params).fetchall()
    return [dict(r) for r in rows]

def db_stats():
    with get_conn() as conn:
        total     = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        avg_score = conn.execute("SELECT ROUND(AVG(final_score),1) FROM transactions").fetchone()[0]
        critical  = conn.execute("SELECT COUNT(*) FROM transactions WHERE risk_class='critical'").fetchone()[0]
        high      = conn.execute("SELECT COUNT(*) FROM transactions WHERE risk_class='high'").fetchone()[0]
        medium    = conn.execute("SELECT COUNT(*) FROM transactions WHERE risk_class='medium'").fetchone()[0]
        low       = conn.execute("SELECT COUNT(*) FROM transactions WHERE risk_class='low'").fetchone()[0]
        scanner   = conn.execute("SELECT COUNT(*) FROM transactions WHERE source='scanner'").fetchone()[0]
        mock      = conn.execute("SELECT COUNT(*) FROM transactions WHERE source='mock'").fetchone()[0]
        top_ip    = conn.execute("SELECT ip_country, COUNT(*) as c FROM transactions GROUP BY ip_country ORDER BY c DESC LIMIT 1").fetchone()
    return {"total":total,"avg_score":avg_score or 0,"critical":critical,"high":high,
            "medium":medium,"low":low,"scanner":scanner,"mock":mock,
            "top_ip":top_ip[0] if top_ip else "—"}

init_db()

# ── Gemini AI ──────────────────────────────────────────────────────────────────
try:
    import google.generativeai as genai
    GEMINI_API_KEY = "AIzaSyDOIk8ugi5EvvprXMAYjFUMqhdt4gFWvNg"
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel("gemini-2.5-flash")
    GEMINI_AVAILABLE = True
    GEMINI_ERROR = ""
except Exception as _e:
    GEMINI_AVAILABLE = False
    GEMINI_ERROR = str(_e)
    gemini_model = None

# ── Neo4j ──────────────────────────────────────────────────────────────────────
NEO4J_URI      = "neo4j+s://c899d0d7.databases.neo4j.io"
NEO4J_USER     = "c899d0d7"
NEO4J_PASSWORD = "K0o9JInbogPIuFpBvx2SUVC19OWfW4BzH-yr3uTudn4"
NEO4J_DATABASE = "c899d0d7"

def get_neo4j_driver():
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        driver.verify_connectivity()
        return driver, None
    except Exception as e:
        return None, str(e)

def neo4j_push_transaction(txn):
    """Push a single scored transaction into Neo4j as Account + Transaction nodes."""
    driver, err = get_neo4j_driver()
    if not driver: return False, err
    p = txn["params"]
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            session.run("""
                MERGE (sender:Account {id: $txn_id})
                SET sender.name         = $name,
                    sender.country      = $customer_country,
                    sender.type         = $customer_type,
                    sender.industry     = $industry,
                    sender.pep_status   = $pep_status,
                    sender.risk_score   = $score,
                    sender.risk_level   = $level,
                    sender.account_age  = $account_age,
                    sender.sanctions    = $sanctions_hit,
                    sender.adverse      = $adverse_media

                MERGE (dest:Country {code: $destination_country})

                MERGE (sender)-[t:SENT_TO {txn_id: $txn_id}]->(dest)
                SET t.amount            = $amount,
                    t.channel           = $payment_channel,
                    t.hour              = $hour,
                    t.ip_country        = $ip_country,
                    t.score             = $score,
                    t.risk_level        = $level,
                    t.sanctions_hit     = $sanctions_hit,
                    t.timestamp         = $timestamp
            """, {
                "txn_id":             txn["txn_id"],
                "name":               txn["name"],
                "customer_country":   p.get("customer_country","IN"),
                "customer_type":      p.get("customer_type",""),
                "industry":           p.get("industry",""),
                "pep_status":         p.get("pep_status","Not a PEP"),
                "score":              txn["score"],
                "level":              txn["level"],
                "account_age":        p.get("account_age",0),
                "sanctions_hit":      p.get("sanctions_hit","No Hit"),
                "adverse_media":      p.get("adverse_media","None"),
                "destination_country":p.get("destination_country","IN"),
                "amount":             p.get("amount",0),
                "payment_channel":    p.get("payment_channel",""),
                "hour":               p.get("hour",12),
                "ip_country":         p.get("ip_country","IN"),
                "timestamp":          txn.get("time",""),
            })
        driver.close()
        return True, None
    except Exception as e:
        return False, str(e)

def neo4j_push_bulk(results):
    """Push all bulk scan results to Neo4j in one session."""
    driver, err = get_neo4j_driver()
    if not driver: return 0, err
    pushed = 0
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            for txn in results:
                p = txn["params"]
                session.run("""
                    MERGE (sender:Account {id: $txn_id})
                    SET sender.name         = $name,
                        sender.country      = $customer_country,
                        sender.type         = $customer_type,
                        sender.industry     = $industry,
                        sender.pep_status   = $pep_status,
                        sender.risk_score   = $score,
                        sender.risk_level   = $level,
                        sender.account_age  = $account_age,
                        sender.sanctions    = $sanctions_hit,
                        sender.adverse      = $adverse_media

                    MERGE (dest:Country {code: $destination_country})

                    MERGE (sender)-[t:SENT_TO {txn_id: $txn_id}]->(dest)
                    SET t.amount            = $amount,
                        t.channel           = $payment_channel,
                        t.hour              = $hour,
                        t.ip_country        = $ip_country,
                        t.score             = $score,
                        t.risk_level        = $level,
                        t.sanctions_hit     = $sanctions_hit,
                        t.timestamp         = $timestamp
                """, {
                    "txn_id":             txn["txn_id"],
                    "name":               txn["name"],
                    "customer_country":   p.get("customer_country","IN"),
                    "customer_type":      p.get("customer_type",""),
                    "industry":           p.get("industry",""),
                    "pep_status":         p.get("pep_status","Not a PEP"),
                    "score":              txn["score"],
                    "level":              txn["level"],
                    "account_age":        p.get("account_age",0),
                    "sanctions_hit":      p.get("sanctions_hit","No Hit"),
                    "adverse_media":      p.get("adverse_media","None"),
                    "destination_country":p.get("destination_country","IN"),
                    "amount":             p.get("amount",0),
                    "payment_channel":    p.get("payment_channel",""),
                    "hour":               p.get("hour",12),
                    "ip_country":         p.get("ip_country","IN"),
                    "timestamp":          txn.get("time",""),
                })
                pushed += 1
        driver.close()
        return pushed, None
    except Exception as e:
        return pushed, str(e)

def neo4j_detect_rings():
    """
    Run Cypher queries to detect suspicious account clusters from real data.
    Returns list of ring dicts compatible with the existing Mule Radar renderer.
    """
    driver, err = get_neo4j_driver()
    if not driver: return [], err

    rings = []
    try:
        with driver.session(database=NEO4J_DATABASE) as session:

            # ── Pattern 1: Sanctioned destination hubs ────────────────────────
            res1 = session.run("""
                MATCH (a:Account)-[t:SENT_TO]->(c:Country)
                WHERE t.sanctions_hit <> 'No Hit'
                  AND c.code IN ['KP','IR','SY','CU','BY','MM','SD','SO','YE','LY']
                WITH c.code AS dest, collect(a) AS senders, collect(t) AS txns,
                     sum(t.amount) AS total_val, count(a) AS n
                WHERE n >= 2
                RETURN dest, senders, txns, total_val, n
                ORDER BY total_val DESC LIMIT 3
            """)
            for i, rec in enumerate(res1):
                senders = rec["senders"]
                txns    = rec["txns"]
                dest    = rec["dest"]
                total   = rec["total_val"] or 0
                n       = rec["n"]
                score   = min(97, 70 + n * 3)
                accounts = []
                edges    = []
                ctrl_id  = f"DEST-{dest}"
                for s in senders:
                    acc_id = s.get("id","?")
                    accounts.append({"id": acc_id, "name": s.get("name","Unknown"),
                                     "role":"mule","age_days": s.get("account_age",0),
                                     "country": s.get("country","?")})
                    edges.append({"from": acc_id, "to": ctrl_id,
                                  "amount": int(total/max(n,1))})
                accounts.append({"id": ctrl_id, "name": f"Sanctioned: {dest}",
                                 "role":"controller","age_days":0,"country": dest})
                signals = ["Transactions to sanctioned destination country",
                           f"{n} accounts sending to {dest}",
                           "Sanctions screening hit on transactions"]
                rings.append({
                    "id": f"NEO-S{i+1}", "type":"Sanctioned Hub",
                    "desc": f"Multiple accounts sending to sanctioned country {dest}",
                    "pattern":"hub_spoke","level":"critical","cls":"critical",
                    "color":"#f43f5e","total_value": int(total),
                    "n_accounts": len(accounts),"n_mules": n,"n_victims":0,
                    "accounts": accounts,
                    "controller":{"id":ctrl_id,"name":f"Sanctioned Dest: {dest}",
                                  "role":"controller","age_days":0,"country":dest},
                    "edges": edges,"signals": signals,
                    "window":"Live — from uploaded data",
                    "ring_score": score, "source":"neo4j",
                })

            # ── Pattern 2: High-risk IP country clusters ──────────────────────
            res2 = session.run("""
                MATCH (a:Account)-[t:SENT_TO]->(c:Country)
                WHERE t.ip_country IN ['RU','NG','CN','PK','KP','IR','UA','VN']
                  AND t.score >= 45
                WITH t.ip_country AS ip, collect(a) AS accs, collect(t) AS txns,
                     sum(t.amount) AS total_val, count(a) AS n
                WHERE n >= 2
                RETURN ip, accs, txns, total_val, n
                ORDER BY total_val DESC LIMIT 3
            """)
            for i, rec in enumerate(res2):
                accs  = rec["accs"]
                ip    = rec["ip"]
                total = rec["total_val"] or 0
                n     = rec["n"]
                score = min(88, 50 + n * 4)
                cls   = "critical" if score>=70 else "high"
                clr   = "#f43f5e" if cls=="critical" else "#fb923c"
                accounts = []
                edges    = []
                ctrl_id  = f"IP-{ip}-{i}"
                for a in accs:
                    acc_id = a.get("id","?")
                    accounts.append({"id":acc_id,"name":a.get("name","Unknown"),
                                     "role":"mule","age_days":a.get("account_age",0),
                                     "country":a.get("country","?")})
                    edges.append({"from":acc_id,"to":ctrl_id,"amount":int(total/max(n,1))})
                accounts.append({"id":ctrl_id,"name":f"IP Cluster: {ip}",
                                 "role":"controller","age_days":0,"country":ip})
                signals = [f"All accounts logging in from high-risk IP country: {ip}",
                           f"{n} flagged accounts in this IP cluster",
                           "Elevated CAML scores across cluster"]
                rings.append({
                    "id": f"NEO-IP{i+1}", "type":"IP Geo Cluster",
                    "desc": f"Accounts sharing high-risk IP origin: {ip}",
                    "pattern":"fanout","level":cls,"cls":cls,
                    "color":clr,"total_value":int(total),
                    "n_accounts":len(accounts),"n_mules":n,"n_victims":0,
                    "accounts":accounts,
                    "controller":{"id":ctrl_id,"name":f"IP Origin: {ip}",
                                  "role":"controller","age_days":0,"country":ip},
                    "edges":edges,"signals":signals,
                    "window":"Live — from uploaded data",
                    "ring_score":score,"source":"neo4j",
                })

            # ── Pattern 3: PEP-linked high-value chains ───────────────────────
            res3 = session.run("""
                MATCH (a:Account)-[t:SENT_TO]->(c:Country)
                WHERE a.pep_status <> 'Not a PEP'
                  AND t.amount > 50000
                WITH a, collect(t) AS txns, collect(c) AS dests,
                     sum(t.amount) AS total_val, count(t) AS n
                WHERE n >= 1
                RETURN a, txns, dests, total_val, n
                ORDER BY total_val DESC LIMIT 3
            """)
            for i, rec in enumerate(res3):
                a     = rec["a"]
                dests = rec["dests"]
                total = rec["total_val"] or 0
                n     = rec["n"]
                score = min(95, 65 + n * 5)
                cls   = "critical" if score>=70 else "high"
                clr   = "#f43f5e" if cls=="critical" else "#fb923c"
                acc_id   = a.get("id","?")
                accounts = [{"id":acc_id,"name":a.get("name","Unknown"),
                             "role":"controller","age_days":a.get("account_age",0),
                             "country":a.get("country","?")}]
                edges = []
                for d in dests[:5]:
                    dest_id = f"DEST-{d.get('code','?')}-{i}"
                    accounts.append({"id":dest_id,"name":f"Dest: {d.get('code','?')}",
                                     "role":"mule","age_days":0,"country":d.get("code","?")})
                    edges.append({"from":acc_id,"to":dest_id,"amount":int(total/max(len(dests),1))})
                signals = [f"PEP status: {a.get('pep_status','?')}",
                           f"High-value transactions over ₹50,000",
                           f"Transacting to {len(dests)} destination(s)"]
                rings.append({
                    "id": f"NEO-PEP{i+1}", "type":"PEP High-Value",
                    "desc": "Politically Exposed Person sending large transactions",
                    "pattern":"chain","level":cls,"cls":cls,
                    "color":clr,"total_value":int(total),
                    "n_accounts":len(accounts),"n_mules":len(dests),"n_victims":0,
                    "accounts":accounts,
                    "controller":{"id":acc_id,"name":a.get("name","Unknown"),
                                  "role":"controller","age_days":a.get("account_age",0),
                                  "country":a.get("country","?")},
                    "edges":edges,"signals":signals,
                    "window":"Live — from uploaded data",
                    "ring_score":score,"source":"neo4j",
                })

        driver.close()
    except Exception as e:
        return rings, str(e)

    return rings, None

def neo4j_get_graph_stats():
    """Return high-level graph statistics from Neo4j."""
    driver, err = get_neo4j_driver()
    if not driver: return {}, err
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            n_accounts  = session.run("MATCH (a:Account) RETURN count(a) AS n").single()["n"]
            n_txns      = session.run("MATCH ()-[t:SENT_TO]->() RETURN count(t) AS n").single()["n"]
            n_countries = session.run("MATCH (c:Country) RETURN count(c) AS n").single()["n"]
            n_critical  = session.run("MATCH (a:Account) WHERE a.risk_level='CRITICAL' RETURN count(a) AS n").single()["n"]
            n_sanctions = session.run("MATCH ()-[t:SENT_TO]->() WHERE t.sanctions_hit <> 'No Hit' RETURN count(t) AS n").single()["n"]
            total_val   = session.run("MATCH ()-[t:SENT_TO]->() RETURN sum(t.amount) AS s").single()["s"] or 0
        driver.close()
        return {"accounts":n_accounts,"txns":n_txns,"countries":n_countries,
                "critical":n_critical,"sanctions":n_sanctions,"total_value":total_val}, None
    except Exception as e:
        return {}, str(e)


st.set_page_config(page_title="CyberAML Shield", page_icon="🛡️", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Syne:wght@400;600;700;800&display=swap');
:root {
  --bg:#07080f;--bg2:#0c0e1a;--bg3:#101326;--panel:#12152a;--panel2:#181b33;
  --teal:#00e5c3;--teal2:#00b8a0;--violet:#8b5cf6;--violet2:#6d28d9;--nebula:#c026d3;
  --red:#f43f5e;--orange:#fb923c;--gold:#fbbf24;--border:#1e2240;--border2:#2a2f5a;
  --text:#dde4f0;--muted:#6b7499;
}
html,body,[class*="css"]{font-family:'Syne',sans-serif;background-color:var(--bg);color:var(--text);}
.stApp{background:var(--bg);}
section[data-testid="stSidebar"]{background:linear-gradient(170deg,#0d0e20 0%,#0a0c1c 40%,#0c0918 100%);border-right:1px solid var(--border2);}
div[data-testid="stSidebar"] .stRadio,div[data-testid="stSidebar"] [data-testid="stRadio"],div[data-testid="stSidebar"] .row-widget.stRadio{display:none !important;visibility:hidden !important;height:0 !important;overflow:hidden !important;position:absolute !important;}
div[data-testid="stSidebar"] .stButton>button{background:transparent !important;border:1px solid transparent !important;border-radius:8px !important;color:var(--muted) !important;font-family:'Syne',sans-serif !important;font-size:0.9rem !important;font-weight:600 !important;letter-spacing:0.3px !important;padding:9px 14px !important;text-align:left !important;width:100% !important;transition:all 0.18s ease !important;box-shadow:none !important;transform:none !important;}
div[data-testid="stSidebar"] .stButton>button:hover{background:rgba(0,229,195,0.07) !important;border-color:rgba(0,229,195,0.25) !important;color:var(--teal) !important;box-shadow:0 0 14px rgba(0,229,195,0.1) !important;transform:translateX(2px) !important;}
div[data-testid="stSidebar"] .refresh-wrap .stButton>button{background:rgba(0,229,195,0.06) !important;border-color:rgba(0,229,195,0.2) !important;color:var(--teal2) !important;font-size:0.82rem !important;}
div[data-testid="stSidebar"] .refresh-wrap .stButton>button:hover{background:rgba(0,229,195,0.14) !important;border-color:var(--teal) !important;color:var(--teal) !important;box-shadow:0 0 20px rgba(0,229,195,0.25) !important;transform:none !important;}
div[data-testid="metric-container"]{background:linear-gradient(135deg,var(--panel),var(--panel2));border:1px solid var(--border2);border-radius:12px;padding:16px;box-shadow:0 0 24px rgba(0,229,195,0.04),inset 0 1px 0 rgba(255,255,255,0.03);transition:border-color 0.25s,box-shadow 0.25s;}
div[data-testid="metric-container"]:hover{border-color:var(--teal2);box-shadow:0 0 28px rgba(0,229,195,0.12);}
div[data-testid="metric-container"] [data-testid="stMetricValue"]{color:var(--teal) !important;font-family:'Share Tech Mono' !important;}
.stApp:not([data-testid="stSidebar"]) .stButton>button,section.main .stButton>button{background:linear-gradient(135deg,var(--panel),var(--panel2)) !important;border:1px solid var(--border2) !important;border-radius:8px !important;color:var(--text) !important;font-family:'Share Tech Mono' !important;font-size:0.82rem !important;letter-spacing:0.5px !important;padding:10px 18px !important;transition:all 0.18s ease !important;box-shadow:0 0 0 rgba(0,229,195,0) !important;position:relative;}
.stButton>button:hover{border-color:var(--teal) !important;color:var(--teal) !important;box-shadow:0 0 18px rgba(0,229,195,0.25),inset 0 0 12px rgba(0,229,195,0.05) !important;transform:translateY(-1px);}
.stButton>button:active{transform:translateY(0px) scale(0.98) !important;box-shadow:0 0 8px rgba(0,229,195,0.4) !important;}
.stButton>button:focus{box-shadow:0 0 0 2px rgba(0,229,195,0.4) !important;border-color:var(--teal) !important;}
.stDataFrame{border:1px solid var(--border2) !important;border-radius:10px !important;overflow:hidden;}
.stDataFrame thead th{background:var(--panel2) !important;color:var(--teal) !important;font-family:'Share Tech Mono' !important;font-size:0.78rem !important;}
.stDataFrame tbody tr:hover td{background:rgba(0,229,195,0.04) !important;}
.stError,.stWarning,.stInfo,.stSuccess{border-radius:10px !important;}
.section-header{font-family:'Share Tech Mono';font-size:0.7rem;letter-spacing:3px;color:var(--teal);text-transform:uppercase;border-bottom:1px solid var(--border);padding-bottom:6px;margin-bottom:16px;}
.risk-badge{display:inline-block;padding:3px 12px;border-radius:20px;font-family:'Share Tech Mono';font-size:0.78rem;letter-spacing:1px;font-weight:700;}
.badge-critical{background:rgba(244,63,94,0.15);border:1px solid var(--red);color:var(--red);}
.badge-high{background:rgba(251,146,60,0.15);border:1px solid var(--orange);color:var(--orange);}
.badge-medium{background:rgba(251,191,36,0.15);border:1px solid var(--gold);color:var(--gold);}
.badge-low{background:rgba(0,229,195,0.12);border:1px solid var(--teal);color:var(--teal);}
.factor-row{display:flex;justify-content:space-between;align-items:center;padding:9px 0;border-bottom:1px solid rgba(30,34,64,0.6);font-size:0.9rem;transition:background 0.15s;}
.factor-row:hover{background:rgba(0,229,195,0.03);border-radius:4px;}
.factor-tag{font-family:'Share Tech Mono';font-size:0.68rem;padding:2px 7px;border-radius:4px;background:rgba(0,229,195,0.06);border:1px solid var(--border2);margin-left:7px;letter-spacing:1px;}
.progress-bar-outer{background:var(--border);border-radius:6px;height:7px;width:100%;margin-top:6px;overflow:hidden;}
.progress-bar-inner{height:7px;border-radius:6px;transition:width 0.6s cubic-bezier(0.4,0,0.2,1);}
.why-box{background:linear-gradient(135deg,rgba(0,229,195,0.04),rgba(139,92,246,0.04));border:1px solid rgba(0,229,195,0.2);border-radius:12px;padding:18px 22px;margin-top:18px;font-size:0.9rem;box-shadow:0 0 30px rgba(0,229,195,0.06);}
.why-title{font-family:'Share Tech Mono';font-size:0.7rem;letter-spacing:3px;color:var(--teal);margin-bottom:12px;}
.why-line{display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid rgba(30,34,64,0.5);font-size:0.88rem;}
.why-multiplier{color:var(--gold);font-family:'Share Tech Mono';font-size:0.82rem;margin-top:10px;padding:10px 14px;border-radius:8px;background:rgba(251,191,36,0.07);border:1px solid rgba(251,191,36,0.2);}
.alert-card{background:linear-gradient(135deg,var(--panel),var(--panel2));border-left:3px solid;border-radius:10px;padding:14px 18px;margin-bottom:10px;font-size:0.92rem;transition:transform 0.15s,box-shadow 0.15s;cursor:default;}
.alert-card:hover{transform:translateX(3px);box-shadow:0 4px 20px rgba(0,0,0,0.3);}
.alert-critical{border-color:var(--red);}.alert-high{border-color:var(--orange);}.alert-medium{border-color:var(--gold);}.alert-low{border-color:var(--teal);}
@keyframes scorePulse{0%{box-shadow:0 0 20px var(--glow-col,#00e5c3)44;}50%{box-shadow:0 0 40px var(--glow-col,#00e5c3)66;}100%{box-shadow:0 0 20px var(--glow-col,#00e5c3)44;}}
.score-dial{animation:scorePulse 2.5s ease-in-out infinite;}
.stMultiSelect span[data-baseweb="tag"]{background:rgba(0,229,195,0.15) !important;border:1px solid var(--teal2) !important;color:var(--teal) !important;border-radius:6px !important;}
h1,h2,h3{font-family:'Syne',sans-serif;font-weight:800;letter-spacing:-0.5px;}
h1{font-size:1.9rem !important;}
.db-stat-card{background:linear-gradient(135deg,#12152a,#181b33);border:1px solid #2a2f5a;border-radius:12px;padding:18px 20px;text-align:center;}
.db-stat-val{font-family:'Share Tech Mono';font-size:2rem;font-weight:700;color:#00e5c3;}
.db-stat-label{font-size:0.75rem;color:#6b7499;letter-spacing:1.5px;text-transform:uppercase;margin-top:4px;}
.bulk-drop{background:linear-gradient(135deg,rgba(0,229,195,0.04),rgba(139,92,246,0.04));border:2px dashed rgba(0,229,195,0.3);border-radius:16px;padding:32px;text-align:center;margin-bottom:24px;}
.bulk-stat{background:linear-gradient(135deg,#12152a,#181b33);border:1px solid #2a2f5a;border-radius:12px;padding:16px 20px;text-align:center;}
.bulk-stat-val{font-family:'Share Tech Mono';font-size:1.7rem;font-weight:700;}
.bulk-stat-label{font-size:0.72rem;color:#6b7499;letter-spacing:1.5px;text-transform:uppercase;margin-top:4px;}
.col-chip{display:inline-block;font-family:'Share Tech Mono';font-size:0.68rem;padding:2px 8px;border-radius:4px;margin:2px;border:1px solid;}
.gemini-exec{background:linear-gradient(135deg,rgba(139,92,246,0.08),rgba(0,229,195,0.04));border:1px solid rgba(139,92,246,0.35);border-radius:14px;padding:22px 26px;margin-top:20px;}
</style>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
# CONSTANTS & LISTS
# ═══════════════════════════════════════════════════════════════════════════════
SANCTIONED_COUNTRIES = {"KP","IR","CU","SY","BY","MM","SD","SO","YE","LY"}
HIGH_RISK_GEO        = {"RU","NG","CN","PK","UA","VN","PH","KH","LA","TZ","ET","MZ"}
MED_RISK_GEO         = {"BR","ID","EG","ZA","BD","NP","KE","GH","AO","DZ"}
FATF_GREY_LIST       = {"TR","JO","ML","SN","TN","MR","AL","BB","BF","DZ"}
HIGH_RISK_INDUSTRIES = {"Cryptocurrency","Gambling","Arms & Defence","Real Estate","Money Services"}
MED_RISK_INDUSTRIES  = {"Legal Services","Accountancy","Import/Export","Precious Metals","Hospitality"}

COUNTRIES = ["IN","US","RU","CN","NG","BR","DE","PK","SG","AE","KP","IR"]
CUST_TYPES_LIST = ["Individual — Low Risk","Individual — High Net Worth","Sole Trader",
                   "Private Company","Shell / Holding Company","Trust / Foundation","Non-Profit (NGO)"]
INDUSTRIES_LIST = ["Technology","Healthcare","Retail","Cryptocurrency","Gambling","Real Estate",
                   "Legal Services","Import/Export","Manufacturing","Hospitality","Arms & Defence"]
SOF_LIST = ["Salary / Employment","Business Revenue","Investment Returns","Inheritance / Gift",
            "Loan Proceeds","Unknown / Undisclosed","Mixed / Complex"]
PEP_LIST = ["Not a PEP","Domestic PEP (Low Rank)","Domestic PEP (Senior)","Foreign PEP",
            "PEP Associate / Family","Former PEP (< 2 yrs)"]
SANCTIONS_LIST = ["No Hit","Name Similarity (Fuzzy Match)","Confirmed Partial Match","Confirmed Full Match","Entity / Org Match"]
ADVERSE_LIST   = ["None","Minor / Unverified","Financial Crime Related","Terrorism / Proliferation","Multiple Confirmed Reports"]
LE_LIST        = ["No Match","Internal Watchlist","Local LE Database","Interpol / International","Previous SAR Filed"]
ACCT_TYPES_LIST= ["Savings Account","Current / Checking","Business Account","Forex Account","Crypto Wallet","Prepaid Card"]
CHANNELS_LIST  = ["Branch / In-person","Internet Banking","Mobile Banking","SWIFT / International Wire",
                  "Crypto Transfer","Cash Deposit","Third-party Payment","Informal / Hawala"]
ALL_COUNTRIES  = sorted(set(["IN","US","UK","DE","AE","SG","AU","FR","CA","JP"] + COUNTRIES +
                             list(HIGH_RISK_GEO) + list(SANCTIONED_COUNTRIES) + list(MED_RISK_GEO)))

TAG_COLORS = {
    "CYBER":"#00e5c3","AML":"#8b5cf6","DEMO":"#f472b6","GEO":"#fb923c",
    "BEHAV":"#fbbf24","PROD":"#38bdf8","NETW":"#a78bfa","SCRN":"#f43f5e",
}

def h(val):
    """Sanitize a value for safe injection into HTML strings."""
    return (str(val)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )

# ── CSV column name aliases (flexible column mapping) ──────────────────────────
CSV_ALIASES = {
    "amount":             ["amount","txn_amount","transaction_amount","value","amt","sum","transfer_amount"],
    "account_age":        ["account_age","acct_age","age_days","account_age_days","age"],
    "billing_country":    ["billing_country","billing","bill_country","home_country","country"],
    "ip_country":         ["ip_country","ip","login_country","ip_location","ip_loc"],
    "hour":               ["hour","txn_hour","transaction_hour","time_hour","hr"],
    "attempts":           ["attempts","login_attempts","failed_attempts","tries"],
    "txns_today":         ["txns_today","transactions_today","daily_txns","txn_count","txn_velocity"],
    "new_device":         ["new_device","is_new_device","unknown_device","device_new"],
    "device_changes":     ["device_changes","device_change_count","num_device_changes"],
    "customer_type":      ["customer_type","cust_type","client_type","entity_type","type"],
    "industry":           ["industry","sector","occupation","business_type","industry_type"],
    "source_of_funds":    ["source_of_funds","sof","funds_source","income_source","funds_origin"],
    "pep_status":         ["pep_status","pep","politically_exposed","pep_type"],
    "customer_country":   ["customer_country","cust_country","client_country","origin_country"],
    "destination_country":["destination_country","dest_country","destination","receiver_country","to_country"],
    "behavior_change_pct":["behavior_change_pct","behaviour_change","behavior_deviation","activity_change","deviation_pct"],
    "account_type":       ["account_type","acct_type","acc_type","account_category"],
    "payment_channel":    ["payment_channel","channel","payment_method","transfer_method"],
    "ownership_layers":   ["ownership_layers","layers","beneficial_ownership","ownership_depth"],
    "linked_flagged":     ["linked_flagged","flagged_linked","linked_suspicious","flagged_accounts"],
    "counterparty_country":["counterparty_country","counterparty","cpty_country","receiver_country","beneficiary_country"],
    "sanctions_hit":      ["sanctions_hit","sanctions","sanctions_result","ofac_hit","sanctions_match"],
    "adverse_media":      ["adverse_media","adverse","media_hit","negative_news"],
    "law_enforcement":    ["law_enforcement","le_match","police_match","interpol","law_match"],
    "sender_name":        ["sender_name","name","customer_name","client_name","sender","account_holder"],
    "txn_id":             ["txn_id","transaction_id","id","ref","reference","txn_ref"],
}

def auto_map_columns(df_cols):
    """Returns dict: canonical_field -> actual_csv_column"""
    cols_lower = {c.lower().strip(): c for c in df_cols}
    mapping = {}
    for field, aliases in CSV_ALIASES.items():
        for alias in aliases:
            if alias in cols_lower:
                mapping[field] = cols_lower[alias]
                break
    return mapping

def safe_get(row, mapping, field, default=None):
    col = mapping.get(field)
    if col and col in row.index:
        val = row[col]
        if pd.isna(val):
            return default
        return val
    return default

def safe_str(row, mapping, field, valid_list, default):
    val = str(safe_get(row, mapping, field, default) or default).strip()
    if valid_list:
        # fuzzy match: find closest
        val_lower = val.lower()
        for item in valid_list:
            if val_lower in item.lower() or item.lower() in val_lower:
                return item
        return default
    return val if val else default

def safe_int(row, mapping, field, default=0, minval=None, maxval=None):
    val = safe_get(row, mapping, field, default)
    try:
        v = int(float(str(val)))
        if minval is not None: v = max(minval, v)
        if maxval is not None: v = min(maxval, v)
        return v
    except: return default

def safe_float(row, mapping, field, default=0.0):
    val = safe_get(row, mapping, field, default)
    try: return float(str(val).replace(",","").replace("₹","").replace("$","").strip())
    except: return default

def safe_bool(row, mapping, field, default=False):
    val = safe_get(row, mapping, field, default)
    if isinstance(val, bool): return val
    if isinstance(val, (int, float)): return bool(val)
    s = str(val).lower().strip()
    return s in ("1","true","yes","y","t")

def row_to_params(row, mapping):
    return {
        "amount":              safe_float(row, mapping, "amount", 5000.0),
        "account_age":         safe_int(row, mapping, "account_age", 30, minval=0),
        "billing_country":     safe_str(row, mapping, "billing_country", None, "IN"),
        "ip_country":          safe_str(row, mapping, "ip_country", None, "IN"),
        "hour":                safe_int(row, mapping, "hour", 12, minval=0, maxval=23),
        "attempts":            safe_int(row, mapping, "attempts", 1, minval=1),
        "txns_today":          safe_int(row, mapping, "txns_today", 1, minval=1),
        "new_device":          safe_bool(row, mapping, "new_device", False),
        "device_changes":      safe_int(row, mapping, "device_changes", 0, minval=0),
        "customer_type":       safe_str(row, mapping, "customer_type", CUST_TYPES_LIST, "Individual — Low Risk"),
        "industry":            safe_str(row, mapping, "industry", INDUSTRIES_LIST, "Technology"),
        "source_of_funds":     safe_str(row, mapping, "source_of_funds", SOF_LIST, "Salary / Employment"),
        "pep_status":          safe_str(row, mapping, "pep_status", PEP_LIST, "Not a PEP"),
        "customer_country":    safe_str(row, mapping, "customer_country", None, "IN"),
        "destination_country": safe_str(row, mapping, "destination_country", None, "IN"),
        "behavior_change_pct": safe_int(row, mapping, "behavior_change_pct", 0, minval=0),
        "account_type":        safe_str(row, mapping, "account_type", ACCT_TYPES_LIST, "Savings Account"),
        "payment_channel":     safe_str(row, mapping, "payment_channel", CHANNELS_LIST, "Internet Banking"),
        "ownership_layers":    safe_int(row, mapping, "ownership_layers", 0, minval=0),
        "linked_flagged":      safe_int(row, mapping, "linked_flagged", 0, minval=0),
        "counterparty_country":safe_str(row, mapping, "counterparty_country", None, "IN"),
        "sanctions_hit":       safe_str(row, mapping, "sanctions_hit", SANCTIONS_LIST, "No Hit"),
        "adverse_media":       safe_str(row, mapping, "adverse_media", ADVERSE_LIST, "None"),
        "law_enforcement":     safe_str(row, mapping, "law_enforcement", LE_LIST, "No Match"),
    }

def generate_sample_csv(n=50):
    """Generate a realistic sample CSV for demo purposes."""
    rng = random.Random(42)
    rows = []
    for i in range(n):
        rows.append({
            "txn_id": f"TXN{100000+i}",
            "sender_name": f"{rng.choice(['Arjun','Priya','Rohan','Neha','Vikram','Karan','Amit','Rahul','Suresh','Deepak'])} {rng.choice(['Mehta','Sharma','Singh','Patel','Gupta','Kumar','Joshi','Verma','Shah','Rao'])}",
            "amount": round(rng.uniform(500, 150000), 2),
            "account_age": rng.randint(1, 730),
            "billing_country": rng.choice(["IN","IN","IN","US","DE","AE"]),
            "ip_country": rng.choice(["IN","IN","RU","CN","NG","PK","KP","IR","US","DE"]),
            "hour": rng.randint(0, 23),
            "attempts": rng.randint(1, 12),
            "txns_today": rng.randint(1, 15),
            "new_device": rng.choice([0, 0, 0, 1]),
            "device_changes": rng.randint(0, 5),
            "customer_type": rng.choice(CUST_TYPES_LIST),
            "industry": rng.choice(INDUSTRIES_LIST),
            "source_of_funds": rng.choice(SOF_LIST),
            "pep_status": rng.choices(PEP_LIST, weights=[60,10,5,5,8,12])[0],
            "customer_country": rng.choice(["IN","IN","IN","RU","CN","NG","KP","IR"]),
            "destination_country": rng.choice(["IN","IN","US","DE","RU","CN","KP","NG","AE"]),
            "behavior_change_pct": rng.choice([0,0,0,25,75,150,300,600]),
            "account_type": rng.choice(ACCT_TYPES_LIST),
            "payment_channel": rng.choice(CHANNELS_LIST),
            "ownership_layers": rng.choice([0,0,1,1,2,3,5]),
            "linked_flagged": rng.choices([0,0,0,1,2,3,5], weights=[50,15,10,10,7,5,3])[0],
            "counterparty_country": rng.choice(["IN","IN","US","RU","CN","NG","IR","KP"]),
            "sanctions_hit": rng.choices(SANCTIONS_LIST, weights=[70,15,8,4,3])[0],
            "adverse_media": rng.choices(ADVERSE_LIST, weights=[65,15,10,5,5])[0],
            "law_enforcement": rng.choices(LE_LIST, weights=[70,12,8,5,5])[0],
        })
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()

# ═══════════════════════════════════════════════════════════════════════════════
# SCORING ENGINE
# ═══════════════════════════════════════════════════════════════════════════════
def score_account_age(days):
    if days < 7:     return 20, f"< 7 days old — very new"
    elif days < 30:  return 15, f"{days}d old — 1 wk to 1 mo"
    elif days < 90:  return 10, f"{days}d old — 1 to 3 mo"
    elif days < 180: return 6,  f"{days}d old — 3 to 6 mo"
    elif days < 365: return 3,  f"{days}d old — 6 to 12 mo"
    else:            return 1,  f"{days}d old — established (baseline)"

def score_amount(amount):
    if amount > 100000:  return 30, f"₹{amount:,.0f} — very high (> ₹1L)"
    elif amount > 50000: return 25, f"₹{amount:,.0f} — high (> ₹50k)"
    elif amount > 10000: return 18, f"₹{amount:,.0f} — elevated (> ₹10k)"
    elif amount > 5000:  return 8,  f"₹{amount:,.0f} — moderate (₹5k–₹10k)"
    elif amount > 1000:  return 3,  f"₹{amount:,.0f} — low (₹1k–₹5k)"
    else:                return 1,  f"₹{amount:,.0f} — minimal (baseline)"

def score_ip_mismatch(billing, ip):
    if billing == ip:     return 1,  f"IP matches billing ({ip}) — baseline"
    elif ip in HIGH_RISK_GEO.union(SANCTIONED_COUNTRIES): return 30, f"IP from high-risk country ({ip} ≠ {billing})"
    elif ip in MED_RISK_GEO:  return 20, f"IP from elevated-risk country ({ip} ≠ {billing})"
    else:                 return 12, f"IP country mismatch ({ip} ≠ {billing})"

def score_attempts(attempts):
    if attempts > 10:   return 25, f"{attempts} attempts — brute-force pattern"
    elif attempts > 5:  return 20, f"{attempts} attempts — high frequency"
    elif attempts > 3:  return 15, f"{attempts} attempts — above threshold"
    elif attempts == 3: return 8,  f"{attempts} attempts — at threshold"
    elif attempts == 2: return 4,  f"{attempts} attempts — slightly elevated"
    else:               return 1,  f"{attempts} attempt(s) — baseline"

def score_hour(hour):
    if 1 <= hour <= 4:     return 15, f"{hour:02d}:00 — deep night (1–4 AM)"
    elif hour in (0, 5):   return 10, f"{hour:02d}:00 — late/early night"
    elif hour >= 22:       return 7,  f"{hour:02d}:00 — late evening"
    elif hour >= 20:       return 4,  f"{hour:02d}:00 — evening"
    elif hour <= 9:        return 3,  f"{hour:02d}:00 — early morning"
    elif 10 <= hour <= 18: return 1,  f"{hour:02d}:00 — business hours (baseline)"
    else:                  return 2,  f"{hour:02d}:00 — off-peak"

def score_velocity(txns_today):
    if txns_today > 10:   return 20, f"{txns_today} txns today — structuring pattern"
    elif txns_today > 5:  return 14, f"{txns_today} txns today — high velocity"
    elif txns_today > 3:  return 9,  f"{txns_today} txns today — elevated"
    elif txns_today == 3: return 5,  f"{txns_today} txns today"
    elif txns_today == 2: return 2,  f"{txns_today} txns today"
    else:                 return 1,  f"{txns_today} txn today — baseline"

def score_device(new_device, device_changes):
    if new_device and device_changes > 3: return 18, "New device + frequent device changes"
    elif new_device:                      return 12, "Transaction from unrecognised device"
    elif device_changes > 3:             return 8,  f"{device_changes} device changes recently"
    elif device_changes > 1:             return 4,  f"{device_changes} device changes"
    else:                                return 1,  "Known device — baseline"

def score_customer_type(ctype):
    scores = {"Individual — Low Risk":1,"Individual — High Net Worth":8,"Sole Trader":6,
              "Private Company":10,"Shell / Holding Company":22,"Trust / Foundation":18,"Non-Profit (NGO)":14}
    return scores.get(ctype, 5), f"{ctype}"

def score_occupation(industry):
    if industry in HIGH_RISK_INDUSTRIES: return 20, f"{industry} — high-risk sector"
    elif industry in MED_RISK_INDUSTRIES: return 10, f"{industry} — elevated sector"
    else: return 2, f"{industry} — standard sector"

def score_source_of_funds(sof):
    scores = {"Salary / Employment":1,"Business Revenue":4,"Investment Returns":5,
              "Inheritance / Gift":10,"Loan Proceeds":12,"Unknown / Undisclosed":25,"Mixed / Complex":18}
    return scores.get(sof, 8), f"Source: {sof}"

def score_pep(pep_status):
    scores = {"Not a PEP":1,"Domestic PEP (Low Rank)":12,"Domestic PEP (Senior)":22,
              "Foreign PEP":28,"PEP Associate / Family":18,"Former PEP (< 2 yrs)":15}
    return scores.get(pep_status, 1), f"PEP: {pep_status}"

def score_customer_country(country):
    if country in SANCTIONED_COUNTRIES:  return 35, f"{country} — SANCTIONED country"
    elif country in HIGH_RISK_GEO:       return 22, f"{country} — high-risk jurisdiction"
    elif country in FATF_GREY_LIST:      return 15, f"{country} — FATF grey-listed"
    elif country in MED_RISK_GEO:        return 8,  f"{country} — elevated jurisdiction"
    else:                                return 1,  f"{country} — standard jurisdiction"

def score_destination_country(country):
    if country in SANCTIONED_COUNTRIES:  return 35, f"Dest: {country} — SANCTIONED"
    elif country in HIGH_RISK_GEO:       return 20, f"Dest: {country} — high-risk"
    elif country in FATF_GREY_LIST:      return 12, f"Dest: {country} — FATF grey-listed"
    elif country in MED_RISK_GEO:        return 6,  f"Dest: {country} — elevated"
    else:                                return 1,  f"Dest: {country} — standard"

def score_structuring(amount, txns_today):
    THRESHOLD = 50000
    structuring = amount < THRESHOLD * 0.9 and txns_today >= 3
    if structuring and txns_today >= 6:  return 25, f"Structuring pattern — ₹{amount:,.0f} × {txns_today} txns"
    elif structuring:                    return 15, f"Possible structuring — ₹{amount:,.0f} × {txns_today} txns"
    else:                                return 1,  "No structuring pattern detected"

def score_behavior_change(pct_change):
    if pct_change > 500:   return 22, f"{pct_change}% above baseline — extreme deviation"
    elif pct_change > 200: return 15, f"{pct_change}% above baseline — high deviation"
    elif pct_change > 100: return 8,  f"{pct_change}% above baseline — elevated deviation"
    elif pct_change > 50:  return 4,  f"{pct_change}% above baseline — slight deviation"
    else:                  return 1,  f"{pct_change}% vs baseline — within normal range"

def score_round_number(amount):
    s = str(int(amount))
    trailing_zeros = len(s) - len(s.rstrip("0"))
    if trailing_zeros >= 5:   return 12, f"₹{amount:,.0f} — highly round (5+ zeros)"
    elif trailing_zeros >= 4: return 7,  f"₹{amount:,.0f} — very round number"
    elif trailing_zeros >= 3: return 3,  f"₹{amount:,.0f} — round number"
    else:                     return 1,  f"₹{amount:,.0f} — not a round number"

def score_account_type(acct_type):
    scores = {"Savings Account":1,"Current / Checking":3,"Business Account":6,"Forex Account":12,
              "Crypto Wallet":22,"Prepaid Card":16,"Anonymous / Numbered":30}
    return scores.get(acct_type, 5), f"Account: {acct_type}"

def score_payment_channel(channel):
    scores = {"Branch / In-person":1,"Internet Banking":3,"Mobile Banking":3,
              "SWIFT / International Wire":14,"Crypto Transfer":22,"Cash Deposit":18,
              "Third-party Payment":16,"Informal / Hawala":30}
    return scores.get(channel, 5), f"Channel: {channel}"

def score_beneficial_ownership(layers):
    if layers >= 5:   return 25, f"{layers} ownership layers — highly complex"
    elif layers >= 3: return 15, f"{layers} ownership layers — complex structure"
    elif layers == 2: return 8,  f"{layers} ownership layers — moderate"
    elif layers == 1: return 3,  "Single-layer ownership — transparent"
    else:             return 1,  "Direct ownership — fully transparent"

def score_linked_accounts(linked_flagged):
    if linked_flagged >= 5:   return 25, f"{linked_flagged} linked flagged accounts"
    elif linked_flagged >= 3: return 18, f"{linked_flagged} linked flagged accounts"
    elif linked_flagged >= 1: return 10, f"{linked_flagged} linked flagged account(s)"
    else:                     return 1,  "No flagged linked accounts"

def score_counterparty_risk(cpty_country):
    if cpty_country in SANCTIONED_COUNTRIES:  return 35, f"Counterparty in {cpty_country} — SANCTIONED"
    elif cpty_country in HIGH_RISK_GEO:       return 18, f"Counterparty in {cpty_country} — high-risk"
    elif cpty_country in FATF_GREY_LIST:      return 10, f"Counterparty in {cpty_country} — FATF grey"
    elif cpty_country in MED_RISK_GEO:        return 5,  f"Counterparty in {cpty_country} — elevated"
    else:                                     return 1,  f"Counterparty in {cpty_country} — standard"

def score_sanctions_hit(hit_type):
    scores = {"No Hit":1,"Name Similarity (Fuzzy Match)":15,"Confirmed Partial Match":28,
              "Confirmed Full Match":40,"Entity / Org Match":35}
    return min(scores.get(hit_type, 1), 40), f"Sanctions: {hit_type}"

def score_adverse_media(severity):
    scores = {"None":1,"Minor / Unverified":8,"Financial Crime Related":22,
              "Terrorism / Proliferation":35,"Multiple Confirmed Reports":28}
    return scores.get(severity, 1), f"Adverse media: {severity}"

def score_law_enforcement(match):
    scores = {"No Match":1,"Internal Watchlist":15,"Local LE Database":22,
              "Interpol / International":35,"Previous SAR Filed":18}
    return scores.get(match, 1), f"LE match: {match}"

def compute_full_score(p):
    factors = [
        {"name":"Account Age",        "tag":"AML",   "s":score_account_age(p.get("account_age", 5))},
        {"name":"Transaction Amount", "tag":"AML",   "s":score_amount(p.get("amount", 0))},
        {"name":"IP / Country Risk",  "tag":"CYBER", "s":score_ip_mismatch(p.get("billing_country", ""), p.get("ip_country", ""))},
        {"name":"Login Attempts",     "tag":"CYBER", "s":score_attempts(p.get("attempts", 1))},
        {"name":"Transaction Hour",   "tag":"CYBER", "s":score_hour(p.get("hour", 12))},
        {"name":"Txn Velocity",       "tag":"AML",   "s":score_velocity(p.get("txns_today", 1))},
        {"name":"Device Risk",        "tag":"CYBER", "s":score_device(p.get("new_device", False), p.get("device_changes", 0))},
    ]
    if p.get("customer_type"): factors.append({"name":"Customer Type",        "tag":"DEMO","s":score_customer_type(p["customer_type"])})
    if p.get("industry"): factors.append({"name":"Industry / Occupation","tag":"DEMO","s":score_occupation(p["industry"])})
    if p.get("source_of_funds"): factors.append({"name":"Source of Funds",      "tag":"DEMO","s":score_source_of_funds(p["source_of_funds"])})
    if p.get("pep_status"): factors.append({"name":"PEP Status",           "tag":"DEMO","s":score_pep(p["pep_status"])})
    if p.get("customer_country"): factors.append({"name":"Customer Country",     "tag":"GEO", "s":score_customer_country(p["customer_country"])})
    if p.get("destination_country"): factors.append({"name":"Destination Country",  "tag":"GEO", "s":score_destination_country(p["destination_country"])})
    factors.append({"name":"Structuring Pattern",      "tag":"BEHAV","s":score_structuring(p.get("amount",0),p.get("txns_today",1))})
    if p.get("behavior_change_pct") is not None: factors.append({"name":"Behavior Deviation",   "tag":"BEHAV","s":score_behavior_change(p["behavior_change_pct"])})
    factors.append({"name":"Round Number Risk",        "tag":"BEHAV","s":score_round_number(p.get("amount",0))})
    if p.get("account_type"): factors.append({"name":"Account Type",         "tag":"PROD","s":score_account_type(p["account_type"])})
    if p.get("payment_channel"): factors.append({"name":"Payment Channel",      "tag":"PROD","s":score_payment_channel(p["payment_channel"])})
    if p.get("ownership_layers") is not None: factors.append({"name":"Ownership Complexity", "tag":"NETW","s":score_beneficial_ownership(p["ownership_layers"])})
    if p.get("linked_flagged") is not None: factors.append({"name":"Linked Flagged Accts", "tag":"NETW","s":score_linked_accounts(p["linked_flagged"])})
    if p.get("counterparty_country"): factors.append({"name":"Counterparty Country", "tag":"NETW","s":score_counterparty_risk(p["counterparty_country"])})
    if p.get("sanctions_hit"): factors.append({"name":"Sanctions Screening",  "tag":"SCRN","s":score_sanctions_hit(p["sanctions_hit"])})
    if p.get("adverse_media"): factors.append({"name":"Adverse Media",        "tag":"SCRN","s":score_adverse_media(p["adverse_media"])})
    if p.get("law_enforcement"): factors.append({"name":"Law Enforcement",      "tag":"SCRN","s":score_law_enforcement(p["law_enforcement"])})

    for f in factors: f["score"], f["label"] = f.pop("s")

    base = sum(f["score"] for f in factors)
    cyber_hi = sum(1 for f in factors if f["tag"]=="CYBER" and f["score"]>3)
    aml_hi   = sum(1 for f in factors if f["tag"]=="AML"   and f["score"]>3)
    demo_hi  = sum(1 for f in factors if f["tag"]=="DEMO"  and f["score"]>8)
    geo_hi   = sum(1 for f in factors if f["tag"]=="GEO"   and f["score"]>8)
    scrn_hi  = sum(1 for f in factors if f["tag"]=="SCRN"  and f["score"]>8)
    netw_hi  = sum(1 for f in factors if f["tag"]=="NETW"  and f["score"]>8)

    mult, mreason = 1.0, None
    if scrn_hi >= 2: mult, mreason = 1.50, f"Compliance convergence (×1.50) — {scrn_hi} screening hits"
    elif scrn_hi >= 1 and (geo_hi >= 1 or demo_hi >= 1): mult, mreason = 1.40, f"Screening + profile risk (×1.40)"
    elif cyber_hi >= 3 and aml_hi >= 2: mult, mreason = 1.35, f"Cyber-AML convergence (×1.35) — {cyber_hi} cyber + {aml_hi} AML signals"
    elif geo_hi >= 2 and (demo_hi >= 1 or aml_hi >= 1): mult, mreason = 1.30, f"Geo-profile convergence (×1.30) — {geo_hi} geo signals"
    elif cyber_hi >= 3: mult, mreason = 1.23, f"Cyber multiplier (×1.23) — {cyber_hi} elevated cyber signals"
    elif netw_hi >= 2: mult, mreason = 1.20, f"Network risk multiplier (×1.20) — {netw_hi} network signals"
    elif aml_hi >= 2: mult, mreason = 1.15, f"AML multiplier (×1.15) — {aml_hi} elevated AML signals"
    elif demo_hi >= 2: mult, mreason = 1.12, f"Customer profile multiplier (×1.12) — {demo_hi} profile signals"
    elif cyber_hi >= 2: mult, mreason = 1.10, f"Soft cyber multiplier (×1.10) — {cyber_hi} elevated cyber signals"

    final = min(200, round(base * mult))
    return {"factors":factors,"base_total":round(base),"multiplier":mult,
            "multiplier_reason":mreason,"multiplier_pts":final-round(base) if mult>1 else 0,"final_score":final}

def risk_level(score):
    if score>=70: return "CRITICAL","critical"
    elif score>=45: return "HIGH","high"
    elif score>=20: return "MEDIUM","medium"
    else: return "LOW","low"

def color_for(cls):
    return {"critical":"#f43f5e","high":"#fb923c","medium":"#fbbf24","low":"#00e5c3"}[cls]

def why_box_html(result, score, level, cls):
    clr = color_for(cls)
    lines = ""
    for f in sorted(result["factors"], key=lambda x: x["score"], reverse=True):
        tc = TAG_COLORS.get(f["tag"], "#00e5c3")
        if f["score"] >= 15:   pc = "#f43f5e"
        elif f["score"] >= 8:  pc = "#fb923c"
        elif f["score"] >= 4:  pc = "#fbbf24"
        else:                  pc = "#444e70"
        lines += f"""<div class='why-line'>
          <span><span class='factor-tag' style='color:{tc};border-color:{tc}22'>{f["tag"]}</span>
          &nbsp;{f["name"]} — <span style='color:#6b7499;font-size:0.82rem'>{f["label"]}</span></span>
          <span style='font-family:Share Tech Mono;color:{pc};font-weight:700;font-size:1.05rem'>+{f["score"]}</span>
        </div>"""
    multi = ""
    if result["multiplier"] > 1:
        multi = f"<div class='why-multiplier'>⚡ {result['multiplier_reason']} → <strong>+{result['multiplier_pts']} pts</strong></div>"
    return f"""<div class='why-box'>
      <div class='why-title'>💡 WHY THIS SCORE?</div>
      <div style='font-size:0.9rem;margin-bottom:14px;color:#aab'>
        Risk score <span style='font-family:Share Tech Mono;color:{clr};font-weight:700;font-size:1.15rem'>{score}</span>
        &nbsp;<span class='risk-badge badge-{cls}'>{level}</span>&nbsp;because:
      </div>{lines}
      <div class='why-line' style='font-weight:700;color:#6b7499;border:none;padding-top:10px'>
        <span>Base total before multiplier</span>
        <span style='font-family:Share Tech Mono;color:#aab'>+{result["base_total"]}</span>
      </div>{multi}
    </div>"""

def ask_gemini(score, result, level, params):
    if not GEMINI_AVAILABLE or gemini_model is None: return f"⚠️ Gemini unavailable: {GEMINI_ERROR}"
    top_factors = sorted(result["factors"], key=lambda x: x["score"], reverse=True)[:8]
    factors_str = ", ".join([f"{f['name']} (+{f['score']})" for f in top_factors if f["score"] > 3])
    mult_str = f"A convergence multiplier of ×{result['multiplier']} was applied ({result['multiplier_reason']})." if result["multiplier"] > 1 else ""
    prompt = f"""You are a senior financial crime analyst reviewing a flagged transaction.
Risk Score: {score}/200 — {level}
{mult_str}
Key risk factors: {factors_str}
Transaction details:
- Amount: ₹{params.get('amount',0):,.0f}
- IP country: {params.get('ip_country','')} → Billing country: {params.get('billing_country','')}
- Account age: {params.get('account_age',0)} days
- Customer type: {params.get('customer_type','N/A')}
- Industry: {params.get('industry','N/A')}
- PEP status: {params.get('pep_status','N/A')}
- Sanctions hit: {params.get('sanctions_hit','N/A')}

In 4-5 sentences, explain why this transaction is suspicious and what the analyst should do immediately. Be specific, professional, and actionable."""
    try: return gemini_model.generate_content(prompt).text
    except Exception as e: return f"Gemini error: {str(e)}"

def ask_gemini_ring(ring):
    if not GEMINI_AVAILABLE or gemini_model is None: return f"⚠️ Gemini unavailable: {GEMINI_ERROR}"
    prompt = f"""You are a financial crime analyst reviewing a detected money mule ring.
Ring ID: {ring['id']}
Pattern: {ring['type']} — {ring['desc']}
Risk Level: {ring['level'].upper()} (score: {ring['ring_score']}/100)
Total value moved: ₹{ring['total_value']:,}
Accounts: {ring['n_victims']} victim(s), {ring['n_mules']} mule(s), 1 controller
Controller origin: {ring['controller']['country']}, account age {ring['controller']['age_days']} days
Detection signals: {', '.join(ring['signals'])}
Active window: {ring['window']}

In 3-4 sentences, explain the money laundering pattern, why it is suspicious, and immediate investigative actions."""
    try: return gemini_model.generate_content(prompt).text
    except Exception as e: return f"Gemini error: {str(e)}"

def ask_gemini_bulk_summary(stats, top_risks, col_count, row_count):
    """Ask Gemini to write an executive summary of the entire batch scan."""
    if not GEMINI_AVAILABLE or gemini_model is None: return f"⚠️ Gemini unavailable: {GEMINI_ERROR}"
    top_str = "\n".join([f"- {r['name']} (score {r['score']}, {r['level']}, ₹{r['params'].get('amount',0):,.0f}, IP: {r['params'].get('ip_country','?')} → {r['params'].get('billing_country','?')}, sanctions: {r['params'].get('sanctions_hit','?')})" for r in top_risks[:5]])
    prompt = f"""You are the Chief AML Officer reviewing a bulk transaction scan report submitted by a compliance analyst.

BATCH SCAN SUMMARY:
- Total transactions scanned: {row_count}
- Columns detected: {col_count}
- CRITICAL (score ≥70): {stats['critical']} transactions ({stats['critical_pct']:.1f}%)
- HIGH (score 45–69): {stats['high']} transactions ({stats['high_pct']:.1f}%)
- MEDIUM (score 20–44): {stats['medium']} transactions ({stats['medium_pct']:.1f}%)
- LOW (score 0–19): {stats['low']} transactions ({stats['low_pct']:.1f}%)
- Average risk score: {stats['avg_score']:.1f}
- Total value at risk (CRITICAL + HIGH): ₹{stats['value_at_risk']:,.0f}
- Highest single score: {stats['max_score']}
- Transactions with sanctions hits: {stats['sanctions_hits']}
- PEP-linked transactions: {stats['pep_count']}
- Top 5 highest-risk transactions:
{top_str}

Write a concise, professional 5–6 sentence executive summary that:
1. States the overall risk profile of the batch
2. Highlights the most alarming patterns or clusters
3. Calls out specific red flags from the top transactions
4. Gives clear, immediate recommended actions for the compliance team
5. Mentions any regulatory concern (FATF, sanctions, structuring)

Write in formal financial crime compliance language, as if this will be read by a Chief Risk Officer."""
    try: return gemini_model.generate_content(prompt).text
    except Exception as e: return f"Gemini error: {str(e)}"

# ═══════════════════════════════════════════════════════════════════════════════
# GENERATORS
# ═══════════════════════════════════════════════════════════════════════════════
FIRST_NAMES = ["Arjun","Priya","Rohan","Neha","Vikram","Ananya","Karan","Divya","Amit","Sneha",
               "Rahul","Pooja","Suresh","Meena","Deepak","Kavya","Rajesh","Sunita","Anil","Rekha"]
LAST_NAMES  = ["Mehta","Sharma","Das","Iyer","Singh","Roy","Patel","Nair","Gupta","Reddy",
               "Kumar","Joshi","Verma","Shah","Mishra","Pillai","Tiwari","Rao","Bose","Jain"]
def random_name(): return f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
def random_acc():  return f"ACC{random.randint(10000,99999)}"

RING_TYPES = [
    {"name":"Hub & Spoke",      "desc":"Controller receives from multiple mules simultaneously",     "pattern":"hub_spoke"},
    {"name":"Chain Layering",   "desc":"Money hops sequentially through accounts to obscure origin", "pattern":"chain"},
    {"name":"Fan-out Smurfing", "desc":"Large sum split into small amounts across many mules",       "pattern":"fanout"},
    {"name":"Circular Loop",    "desc":"Funds cycle back to origin through intermediaries",           "pattern":"loop"},
]

def generate_rings(seed=42):
    rng = random.Random(seed)
    rings = []
    risk_profiles = [
        {"level":"critical","cls":"critical","color":"#f43f5e","size_range":(5,9),"value_range":(200000,800000)},
        {"level":"critical","cls":"critical","color":"#f43f5e","size_range":(4,7),"value_range":(150000,500000)},
        {"level":"high",    "cls":"high",    "color":"#fb923c","size_range":(4,7),"value_range":(80000,300000)},
        {"level":"high",    "cls":"high",    "color":"#fb923c","size_range":(3,5),"value_range":(50000,200000)},
        {"level":"medium",  "cls":"medium",  "color":"#fbbf24","size_range":(3,5),"value_range":(20000,80000)},
        {"level":"medium",  "cls":"medium",  "color":"#fbbf24","size_range":(3,4),"value_range":(15000,60000)},
    ]
    for i, prof in enumerate(risk_profiles):
        rtype=rng.choice(RING_TYPES); n_mules=rng.randint(*prof["size_range"]); total_value=rng.uniform(*prof["value_range"])
        controller={"id":random_acc(),"name":random_name(),"role":"controller","age_days":rng.randint(3,25),"country":rng.choice(["RU","CN","NG","PK"])}
        mules=[{"id":random_acc(),"name":random_name(),"role":"mule","age_days":rng.randint(1,60),"country":"IN"} for _ in range(n_mules)]
        victims=[{"id":random_acc(),"name":random_name(),"role":"victim","age_days":rng.randint(100,1000),"country":"IN"} for _ in range(rng.randint(1,3))]
        edges=[]
        if rtype["pattern"]=="hub_spoke":
            for v in victims: edges.append({"from":v["id"],"to":mules[0]["id"],"amount":round(total_value*rng.uniform(0.3,0.7))})
            for m in mules[1:]: edges.append({"from":mules[0]["id"],"to":m["id"],"amount":round(total_value/n_mules)})
            for m in mules: edges.append({"from":m["id"],"to":controller["id"],"amount":round(total_value/n_mules*0.9)})
        elif rtype["pattern"]=="chain":
            chain=victims+mules+[controller]
            for j in range(len(chain)-1): edges.append({"from":chain[j]["id"],"to":chain[j+1]["id"],"amount":round(total_value*(0.95**j))})
        elif rtype["pattern"]=="fanout":
            for v in victims: edges.append({"from":v["id"],"to":controller["id"],"amount":round(total_value*rng.uniform(0.4,0.8))})
            for m in mules: edges.append({"from":controller["id"],"to":m["id"],"amount":round(total_value/n_mules*rng.uniform(0.8,1.2))})
        elif rtype["pattern"]=="loop":
            all_accs=mules+[controller]
            for j in range(len(all_accs)): edges.append({"from":all_accs[j]["id"],"to":all_accs[(j+1)%len(all_accs)]["id"],"amount":round(total_value*rng.uniform(0.7,1.0))})
            if victims: edges.insert(0,{"from":victims[0]["id"],"to":all_accs[0]["id"],"amount":round(total_value)})
        signals=[]
        if rng.random()>0.3: signals.append("Same device fingerprint across accounts")
        if rng.random()>0.4: signals.append("Accounts created within same 48h window")
        if rng.random()>0.3: signals.append("Identical IP subnet on login")
        if rng.random()>0.5: signals.append("Coordinated transaction timing (< 3 min apart)")
        if rng.random()>0.4: signals.append("Sequential phone numbers at registration")
        if not signals: signals.append("Unusual money flow topology detected")
        all_accounts=victims+mules+[controller]
        activation_window=f"{rng.randint(1,28)} {rng.choice(['Jan','Feb','Mar','Apr'])} — {rng.randint(1,7)} {rng.choice(['Feb','Mar','Apr','May'])} 2025"
        rings.append({"id":f"RING-{1000+i}","type":rtype["name"],"desc":rtype["desc"],"pattern":rtype["pattern"],
            "level":prof["level"],"cls":prof["cls"],"color":prof["color"],"total_value":round(total_value),
            "n_accounts":len(all_accounts),"n_mules":n_mules,"n_victims":len(victims),"accounts":all_accounts,
            "controller":controller,"edges":edges,"signals":signals,"window":activation_window,
            "ring_score":rng.randint({"critical":72,"high":48,"medium":22}[prof["cls"]],{"critical":97,"high":69,"medium":44}[prof["cls"]])})
    return rings

def random_transaction(save=True):
    # Pick a risk profile: ~20% critical, ~25% high, ~30% medium, ~25% low
    profile = random.choices(["critical","high","medium","low"], weights=[20,25,30,25])[0]

    if profile == "critical":
        p = {
            "account_age": random.randint(1, 20),
            "amount": round(random.uniform(80000, 200000), 2),
            "billing_country": random.choice(["IN","US","DE"]),
            "ip_country": random.choice(["RU","NG","KP","IR","CN","PK"]),
            "hour": random.randint(1, 4),
            "attempts": random.randint(7, 15),
            "txns_today": random.randint(8, 15),
            "new_device": True,
            "device_changes": random.randint(3, 6),
            "customer_type": random.choice(["Shell / Holding Company","Trust / Foundation","Non-Profit (NGO)"]),
            "industry": random.choice(["Cryptocurrency","Gambling","Arms & Defence"]),
            "source_of_funds": random.choice(["Unknown / Undisclosed","Mixed / Complex"]),
            "pep_status": random.choice(["Foreign PEP","Domestic PEP (Senior)","PEP Associate / Family"]),
            "customer_country": random.choice(["RU","NG","KP","IR","CN"]),
            "destination_country": random.choice(["KP","IR","RU","NG","SY"]),
            "behavior_change_pct": random.choice([300,400,500,600,700]),
            "account_type": random.choice(["Crypto Wallet","Prepaid Card"]),
            "payment_channel": random.choice(["Informal / Hawala","Crypto Transfer","Cash Deposit"]),
            "ownership_layers": random.randint(3, 7),
            "linked_flagged": random.randint(2, 6),
            "counterparty_country": random.choice(["KP","IR","RU","NG"]),
            "sanctions_hit": random.choice(["Confirmed Full Match","Entity / Org Match","Confirmed Partial Match"]),
            "adverse_media": random.choice(["Terrorism / Proliferation","Financial Crime Related","Multiple Confirmed Reports"]),
            "law_enforcement": random.choice(["Interpol / International","Local LE Database","Previous SAR Filed"]),
        }
    elif profile == "high":
        p = {
            "account_age": random.randint(10, 60),
            "amount": round(random.uniform(30000, 85000), 2),
            "billing_country": random.choice(["IN","IN","US"]),
            "ip_country": random.choice(["RU","CN","NG","PK","UA","VN"]),
            "hour": random.randint(0, 6),
            "attempts": random.randint(4, 8),
            "txns_today": random.randint(4, 10),
            "new_device": random.choice([True, False]),
            "device_changes": random.randint(2, 4),
            "customer_type": random.choice(["Private Company","Individual — High Net Worth","Sole Trader"]),
            "industry": random.choice(["Real Estate","Legal Services","Import/Export","Precious Metals"]),
            "source_of_funds": random.choice(["Loan Proceeds","Inheritance / Gift","Investment Returns"]),
            "pep_status": random.choice(["Domestic PEP (Low Rank)","Former PEP (< 2 yrs)","Not a PEP"]),
            "customer_country": random.choice(["RU","CN","NG","PK","UA"]),
            "destination_country": random.choice(["AE","RU","CN","TR","NG"]),
            "behavior_change_pct": random.choice([100,150,200,250]),
            "account_type": random.choice(["Forex Account","Business Account","Crypto Wallet"]),
            "payment_channel": random.choice(["SWIFT / International Wire","Third-party Payment","Cash Deposit"]),
            "ownership_layers": random.randint(2, 4),
            "linked_flagged": random.randint(1, 3),
            "counterparty_country": random.choice(["RU","CN","AE","TR"]),
            "sanctions_hit": random.choice(["Name Similarity (Fuzzy Match)","Confirmed Partial Match","No Hit"]),
            "adverse_media": random.choice(["Financial Crime Related","Minor / Unverified","None"]),
            "law_enforcement": random.choice(["Internal Watchlist","Local LE Database","No Match"]),
        }
    elif profile == "medium":
        p = {
            "account_age": random.randint(30, 180),
            "amount": round(random.uniform(5000, 30000), 2),
            "billing_country": random.choice(["IN","IN","IN","US"]),
            "ip_country": random.choice(["IN","IN","BR","ID","EG","ZA"]),
            "hour": random.randint(6, 22),
            "attempts": random.randint(2, 4),
            "txns_today": random.randint(2, 5),
            "new_device": random.choice([False, False, True]),
            "device_changes": random.randint(0, 2),
            "customer_type": random.choice(["Individual — Low Risk","Individual — High Net Worth","Sole Trader","Private Company"]),
            "industry": random.choice(["Technology","Healthcare","Retail","Manufacturing","Hospitality"]),
            "source_of_funds": random.choice(["Salary / Employment","Business Revenue","Investment Returns"]),
            "pep_status": "Not a PEP",
            "customer_country": random.choice(["IN","IN","IN","BR","ID","EG"]),
            "destination_country": random.choice(["IN","IN","US","DE","AE","SG"]),
            "behavior_change_pct": random.choice([0,25,50,75,100]),
            "account_type": random.choice(["Savings Account","Current / Checking","Business Account"]),
            "payment_channel": random.choice(["Internet Banking","Mobile Banking","Branch / In-person"]),
            "ownership_layers": random.randint(0, 2),
            "linked_flagged": random.randint(0, 1),
            "counterparty_country": random.choice(["IN","US","DE","SG"]),
            "sanctions_hit": "No Hit",
            "adverse_media": random.choice(["None","None","Minor / Unverified"]),
            "law_enforcement": random.choice(["No Match","No Match","Internal Watchlist"]),
        }
    else:  # low
        p = {
            "account_age": random.randint(180, 730),
            "amount": round(random.uniform(200, 5000), 2),
            "billing_country": "IN",
            "ip_country": "IN",
            "hour": random.randint(9, 18),
            "attempts": 1,
            "txns_today": random.randint(1, 2),
            "new_device": False,
            "device_changes": 0,
            "customer_type": "Individual — Low Risk",
            "industry": random.choice(["Technology","Healthcare","Retail","Manufacturing"]),
            "source_of_funds": random.choice(["Salary / Employment","Business Revenue"]),
            "pep_status": "Not a PEP",
            "customer_country": "IN",
            "destination_country": random.choice(["IN","IN","US","DE"]),
            "behavior_change_pct": 0,
            "account_type": random.choice(["Savings Account","Current / Checking"]),
            "payment_channel": random.choice(["Internet Banking","Mobile Banking","Branch / In-person"]),
            "ownership_layers": 0,
            "linked_flagged": 0,
            "counterparty_country": "IN",
            "sanctions_hit": "No Hit",
            "adverse_media": "None",
            "law_enforcement": "No Match",
        }

    r = compute_full_score(p); score = r["final_score"]; level,cls = risk_level(score)
    txn = {"name":random_name(),"params":p,"result":r,"score":score,"level":level,"class":cls,
           "time":(datetime.now()-timedelta(minutes=random.randint(0,120))).strftime("%H:%M:%S"),
           "txn_id":f"TXN{random.randint(100000,999999)}"}
    if save: save_transaction(txn, source="mock")
    return txn

def render_ring_graph(ring):
    accounts=ring["accounts"]; edges=ring["edges"]
    role_color={"controller":"#f43f5e","mule":"#fb923c","victim":"#00e5c3"}
    role_size ={"controller":24,"mule":17,"victim":14}
    nodes=[{"id":a["id"],"label":a["name"].split()[0],"fullname":a["name"],"role":a["role"],
             "color":role_color[a["role"]],"size":role_size[a["role"]],"age":a["age_days"]} for a in accounts]
    links=[{"source":e["from"],"target":e["to"],"amount":e["amount"],"label":f"₹{e['amount']:,}"} for e in edges]
    nodes_json=json.dumps(nodes); links_json=json.dumps(links)
    return f"""<!DOCTYPE html><html><head><style>
  body{{margin:0;background:#07080f;font-family:'Share Tech Mono',monospace;overflow:hidden;}}
  #tooltip{{position:absolute;background:rgba(7,8,15,0.96);border:1px solid rgba(0,229,195,0.25);border-radius:8px;padding:10px 14px;font-size:11px;color:#dde4f0;pointer-events:none;display:none;z-index:10;line-height:1.7;box-shadow:0 0 20px rgba(0,229,195,0.15);}}
  .legend{{position:absolute;bottom:12px;left:12px;font-size:10px;color:#444e70;}}
  .legend-dot{{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px;}}
  .node-label{{font-size:9px;fill:#aab;pointer-events:none;}}
  .link-label{{font-size:8px;fill:#00b8a0;pointer-events:none;opacity:0.7;}}
</style></head><body>
<div id="tooltip"></div>
<svg id="graph" width="100%" height="480" style="display:block"></svg>
<div class="legend">
  <span><span class="legend-dot" style="background:#f43f5e"></span>Controller</span>&nbsp;&nbsp;
  <span><span class="legend-dot" style="background:#fb923c"></span>Mule</span>&nbsp;&nbsp;
  <span><span class="legend-dot" style="background:#00e5c3"></span>Victim</span>
  <span style="margin-left:14px;opacity:0.5">Drag · Hover · Scroll to zoom</span>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.8.5/d3.min.js"></script>
<script>
const nodes={nodes_json},links={links_json};
const W=document.getElementById('graph').clientWidth||800,H=480;
const svg=d3.select('#graph'),tip=document.getElementById('tooltip');
const defs=svg.append('defs');
['ctrl','mule','vic'].forEach((id,i)=>{{
  const col=['#f43f5e','#fb923c','#00e5c3'][i];
  const f=defs.append('filter').attr('id','glow-'+id).attr('x','-50%').attr('y','-50%').attr('width','200%').attr('height','200%');
  f.append('feGaussianBlur').attr('stdDeviation','3').attr('result','blur');
  const fm=f.append('feMerge');fm.append('feMergeNode').attr('in','blur');fm.append('feMergeNode').attr('in','SourceGraphic');
}});
[['ctrl','#f43f5e'],['mule','#fb923c'],['vic','#00e5c3'],['def','#2a2f5a']].forEach(([id,col])=>{{
  defs.append('marker').attr('id','arrow-'+id).attr('viewBox','0 -5 10 10').attr('refX',30).attr('refY',0).attr('markerWidth',6).attr('markerHeight',6).attr('orient','auto')
    .append('path').attr('d','M0,-5L10,0L0,5').attr('fill',col).attr('opacity',0.8);
}});
const arrowId=t=>t==='controller'?'ctrl':t==='mule'?'mule':t==='victim'?'vic':'def';
const sim=d3.forceSimulation(nodes)
  .force('link',d3.forceLink(links).id(d=>d.id).distance(120).strength(0.5))
  .force('charge',d3.forceManyBody().strength(-350))
  .force('center',d3.forceCenter(W/2,H/2))
  .force('collision',d3.forceCollide().radius(38));
const g=svg.append('g');
svg.call(d3.zoom().scaleExtent([0.3,3]).on('zoom',e=>g.attr('transform',e.transform)));
const link=g.append('g').selectAll('line').data(links).join('line')
  .attr('stroke',d=>{{const t=nodes.find(n=>n.id===(d.target.id||d.target));return t?t.color+'88':'#2a2f5a';}})
  .attr('stroke-width',1.6)
  .attr('marker-end',d=>{{const t=nodes.find(n=>n.id===(d.target.id||d.target));return'url(#arrow-'+arrowId(t?t.role:'def')+')';}});
const edgeLabel=g.append('g').selectAll('text').data(links).join('text').attr('class','link-label').attr('text-anchor','middle').text(d=>d.label);
const node=g.append('g').selectAll('g').data(nodes).join('g')
  .call(d3.drag()
    .on('start',(e,d)=>{{if(!e.active)sim.alphaTarget(0.3).restart();d.fx=d.x;d.fy=d.y;}})
    .on('drag',(e,d)=>{{d.fx=e.x;d.fy=e.y;}})
    .on('end',(e,d)=>{{if(!e.active)sim.alphaTarget(0);d.fx=null;d.fy=null;}}));
node.filter(d=>d.role==='controller').append('circle').attr('r',d=>d.size+12).attr('fill','none').attr('stroke','#f43f5e').attr('stroke-width',1.5).attr('opacity',0.25).attr('stroke-dasharray','5 4');
node.filter(d=>d.role==='controller').append('circle').attr('r',d=>d.size+6).attr('fill','none').attr('stroke','#f43f5e').attr('stroke-width',0.8).attr('opacity',0.15);
node.append('circle').attr('r',d=>d.size).attr('fill',d=>d.color+'18').attr('stroke',d=>d.color).attr('stroke-width',2).attr('filter',d=>'url(#glow-'+arrowId(d.role)+')').style('cursor','pointer')
  .on('mouseover',(e,d)=>{{d3.select(e.currentTarget).attr('stroke-width',3).attr('fill',d=>d.color+'33');tip.style.display='block';const rl=d.role.charAt(0).toUpperCase()+d.role.slice(1);tip.innerHTML=`<b style="color:${{d.color}}">${{d.fullname}}</b><br>Role: <span style="color:${{d.color}}">${{rl}}</span><br>Account: ${{d.id}}<br>Age: ${{d.age}} days`;}})
  .on('mousemove',e=>{{tip.style.left=(e.pageX+14)+'px';tip.style.top=(e.pageY-10)+'px';}})
  .on('mouseout',(e,d)=>{{d3.select(e.currentTarget).attr('stroke-width',2).attr('fill',d=>d.color+'18');tip.style.display='none';}});
node.append('text').attr('class','node-label').attr('text-anchor','middle').attr('dy','0.35em').text(d=>d.label.slice(0,7));
sim.on('tick',()=>{{
  link.attr('x1',d=>d.source.x).attr('y1',d=>d.source.y).attr('x2',d=>d.target.x).attr('y2',d=>d.target.y);
  edgeLabel.attr('x',d=>(d.source.x+d.target.x)/2).attr('y',d=>(d.source.y+d.target.y)/2-6);
  node.attr('transform',d=>`translate(${{d.x}},${{d.y}})`);
}});
</script></body></html>"""

# ── Session state init ─────────────────────────────────────────────────────────
if "transactions" not in st.session_state:
    st.session_state.transactions = [random_transaction(save=True) for _ in range(40)]
if "last_refresh" not in st.session_state:
    st.session_state.last_refresh = datetime.now()
if "rings" not in st.session_state:
    st.session_state.rings = generate_rings(seed=random.randint(0,9999))
if "scanner_history" not in st.session_state:
    st.session_state.scanner_history = []
if "bulk_results" not in st.session_state:
    st.session_state.bulk_results = None
if "bulk_gemini" not in st.session_state:
    st.session_state.bulk_gemini = None
if "neo4j_rings" not in st.session_state:
    st.session_state.neo4j_rings = []

# ═══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ═══════════════════════════════════════════════════════════════════════════════
NAV_PAGES  = ["Dashboard","CAML Score","Bulk CSV Scanner","Live Alert Feed","Mule Radar","Database","About"]
NAV_GLYPHS = {"Dashboard":"⊞","CAML Score":"⊕","Bulk CSV Scanner":"⬆","Live Alert Feed":"◉","Mule Radar":"⋈","Database":"⬡","About":"ℹ"}

if "page" not in st.session_state:
    st.session_state.page = "Dashboard"

with st.sidebar:
    st.markdown("""<div style='padding:8px 0 20px 0'>
      <div style='font-family:Syne,sans-serif;font-size:1.25rem;font-weight:800;background:linear-gradient(90deg,#00e5c3,#8b5cf6);-webkit-background-clip:text;-webkit-text-fill-color:transparent;'>CyberAML Shield</div>
      <div style='font-size:0.68rem;color:#2e3550;letter-spacing:2.5px;margin-top:3px;text-transform:uppercase'>Threat Detection Platform</div>
    </div>""", unsafe_allow_html=True)
    st.markdown("<div class='section-header'>Navigation</div>", unsafe_allow_html=True)
    active_page = st.session_state.page
    for p in NAV_PAGES:
        glyph = NAV_GLYPHS.get(p,"·"); is_active = (p == active_page)
        if st.button(f"{glyph}  {p}", key=f"nav_{p}", use_container_width=True):
            st.session_state.page = p; st.rerun()
        if is_active:
            st.markdown("<div style='height:3px;background:linear-gradient(90deg,#00e5c3,#8b5cf6);border-radius:2px;margin:-6px 4px 4px 4px;opacity:0.9'></div>", unsafe_allow_html=True)
    st.markdown("<div class='section-header' style='margin-top:24px'>Risk Levels</div>", unsafe_allow_html=True)
    for label,col in [("CRITICAL — 70+","#f43f5e"),("HIGH — 45–69","#fb923c"),("MEDIUM — 20–44","#fbbf24"),("LOW — 0–19","#00e5c3")]:
        st.markdown(f"<div style='display:flex;align-items:center;gap:8px;margin-bottom:5px'><div style='width:6px;height:6px;border-radius:50%;background:{col};flex-shrink:0'></div><span style='color:#6b7499;font-size:0.82rem'>{label}</span></div>", unsafe_allow_html=True)
    st.markdown("<div class='section-header' style='margin-top:16px'>Signal Domains</div>", unsafe_allow_html=True)
    for tag,desc,col in [("CYBER","Cybersecurity","#00e5c3"),("AML","Anti-Money Laundering","#8b5cf6"),
                          ("DEMO","Customer Profile","#f472b6"),("GEO","Geographic Risk","#fb923c"),
                          ("BEHAV","Behavior Analysis","#fbbf24"),("PROD","Product / Channel","#38bdf8"),
                          ("NETW","Network / Relations","#a78bfa"),("SCRN","Screening & Compliance","#f43f5e")]:
        st.markdown(f"<div style='display:flex;align-items:center;gap:8px;margin-bottom:4px'><span style='font-family:Share Tech Mono;font-size:0.65rem;padding:1px 6px;border-radius:3px;background:{col}22;border:1px solid {col}55;color:{col}'>{tag}</span><span style='color:#6b7499;font-size:0.75rem'>{desc}</span></div>", unsafe_allow_html=True)
    st.markdown("")
    st.markdown("<div class='refresh-wrap'>", unsafe_allow_html=True)
    if st.button("⟳  Refresh Data", key="refresh_btn", use_container_width=True):
        st.session_state.transactions = [random_transaction(save=True) for _ in range(40)]
        st.session_state.rings = generate_rings(seed=random.randint(0,9999))
        st.session_state.last_refresh = datetime.now(); st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)
    st.caption(f"Last refresh: {st.session_state.last_refresh.strftime('%H:%M:%S')}")

page = st.session_state.page
txns = st.session_state.transactions
rings = st.session_state.rings

# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 1 — DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════
if page == "Dashboard":
    st.markdown("# 📊 Unified Threat Dashboard")
    st.markdown("<div class='section-header'>Live overview · 8 signal domains · multipliers</div>", unsafe_allow_html=True)
    total=len(txns); critical=sum(1 for t in txns if t["class"]=="critical")
    high_r=sum(1 for t in txns if t["class"]=="high"); medium=sum(1 for t in txns if t["class"]=="medium")
    avg_s=round(np.mean([t["score"] for t in txns]),1)
    c1,c2,c3,c4,c5=st.columns(5)
    c1.metric("Total Transactions",total); c2.metric("🔴 Critical",critical,delta=f"{round(critical/total*100)}%")
    c3.metric("🟠 High",high_r,delta=f"{round(high_r/total*100)}%"); c4.metric("🟡 Medium",medium,delta=f"{round(medium/total*100)}%"); c5.metric("Avg Score",avg_s)
    st.markdown("---")
    col_left,col_right=st.columns(2)
    with col_left:
        st.markdown("<div class='section-header'>Risk Distribution</div>", unsafe_allow_html=True)
        dist={"CRITICAL":critical,"HIGH":high_r,"MEDIUM":medium,"LOW":total-critical-high_r-medium}
        bar_cols={"CRITICAL":"#f43f5e","HIGH":"#fb923c","MEDIUM":"#fbbf24","LOW":"#00e5c3"}
        for label,count in dist.items():
            pct=count/total
            st.markdown(f"<div style='display:flex;justify-content:space-between;margin-bottom:2px'><span style='color:{bar_cols[label]};font-weight:600'>{label}</span><span style='color:#6b7499;font-family:Share Tech Mono;font-size:0.85rem'>{count} &nbsp;·&nbsp; {round(pct*100)}%</span></div>", unsafe_allow_html=True)
            st.markdown(f"<div class='progress-bar-outer'><div class='progress-bar-inner' style='width:{pct*100:.1f}%;background:linear-gradient(90deg,{bar_cols[label]},{bar_cols[label]}88)'></div></div><div style='margin-bottom:10px'></div>", unsafe_allow_html=True)
        st.markdown("<div class='section-header' style='margin-top:8px'>Signals by Domain</div>", unsafe_allow_html=True)
        domain_counts={}
        for t in txns:
            for f in t["result"]["factors"]:
                if f["score"]>3: domain_counts[f["tag"]]=domain_counts.get(f["tag"],0)+1
        for tag,count in sorted(domain_counts.items(),key=lambda x:x[1],reverse=True):
            col=TAG_COLORS.get(tag,"#aaa"); pct=count/(sum(domain_counts.values()) or 1)
            st.markdown(f"<div style='display:flex;justify-content:space-between;margin-bottom:2px'><span style='font-family:Share Tech Mono;font-size:0.78rem;color:{col}'>{tag}</span><span style='color:#6b7499;font-size:0.8rem'>{count}</span></div>", unsafe_allow_html=True)
            st.markdown(f"<div class='progress-bar-outer'><div class='progress-bar-inner' style='width:{pct*100:.1f}%;background:{col}88'></div></div><div style='margin-bottom:6px'></div>", unsafe_allow_html=True)
    with col_right:
        st.markdown("<div class='section-header'>Top Triggered Factors</div>", unsafe_allow_html=True)
        factor_tags_map={f["name"]:f["tag"] for t in txns for f in t["result"]["factors"]}
        factor_counts={n:0 for n in factor_tags_map}
        for t in txns:
            for f in t["result"]["factors"]:
                if f["score"]>3: factor_counts[f["name"]]+=1
        for fname,count in sorted(factor_counts.items(),key=lambda x:x[1],reverse=True)[:14]:
            tc=TAG_COLORS.get(factor_tags_map.get(fname,"AML"),"#00e5c3")
            st.markdown(f"<div class='factor-row'><span>{fname} <span class='factor-tag' style='color:{tc};border-color:{tc}33'>{factor_tags_map.get(fname,'')}</span></span><span style='font-family:Share Tech Mono;color:#6b7499'>{count}</span></div>", unsafe_allow_html=True)
    st.markdown("---")
    st.markdown("<div class='section-header'>Recent High-Risk Transactions</div>", unsafe_allow_html=True)
    flagged=sorted([t for t in txns if t["class"] in ("critical","high")],key=lambda x:x["score"],reverse=True)[:8]
    df=pd.DataFrame([{"TXN ID":t["txn_id"],"Name":t["name"],"Amount (₹)":f"₹{t['params'].get('amount',0):,.0f}",
        "IP":t["params"].get("ip_country","—"),"PEP":t["params"].get("pep_status","—")[:18],
        "Sanctions":t["params"].get("sanctions_hit","—")[:22],
        "Score":t["score"],"Multiplier":f"×{t['result']['multiplier']:.2f}" if t["result"]["multiplier"]>1 else "—",
        "Level":t["level"],"Time":t["time"]} for t in flagged])
    st.dataframe(df,use_container_width=True,hide_index=True)

# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — CAML SCORE
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "CAML Score":
    st.markdown("# 🔍 CAML Risk Scanner")
    st.markdown("<div class='section-header'>8 signal domains · 24 risk factors · multipliers · database persistence</div>", unsafe_allow_html=True)

    tab1, tab2, tab3, tab4 = st.tabs(["⚙️ Core Signals", "👤 Customer & Geography", "🏦 Product & Behavior", "🔎 Screening & Network"])

    with tab1:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### 🏦 AML Signals")
            txn_amount = st.number_input("Transaction Amount (₹)", min_value=0.0, value=12000.0, step=500.0, key="sc_amount")
            account_age = st.number_input("Account Age (days)", min_value=0, value=5, step=1, key="sc_age")
            txns_today = st.number_input("Transactions today", min_value=1, value=2, step=1, key="sc_vel")
            st.markdown("#### 🌐 Cyber Signals")
            billing_c = st.selectbox("Billing Country", ["IN","US","UK","DE","AE","SG","AU","FR","CA","JP"], key="sc_bill")
            ip_c = st.selectbox("IP / Login Country", ["IN","US","RU","CN","NG","BR","PK","DE","SG","AE","UA","VN","PH","KP","IR"], key="sc_ip")
            txn_hour = st.slider("Transaction Hour (24h)", 0, 23, value=datetime.now().hour, key="sc_hour")
            attempts = st.number_input("Login Attempts (last 5 min)", min_value=1, value=4, step=1, key="sc_att")
            st.markdown("#### 💻 Device & Product")
            new_device = st.toggle("Transaction from unrecognised device", value=False, key="sc_dev")
            device_chg = st.number_input("Device changes in last 30 days", min_value=0, value=0, step=1, key="sc_dchg")

    with tab2:
        c3, c4 = st.columns(2)
        with c3:
            st.markdown("#### 👤 Customer / Demographic")
            customer_type = st.selectbox("Customer Type", CUST_TYPES_LIST, key="sc_ctype")
            industry = st.selectbox("Industry / Occupation", INDUSTRIES_LIST, key="sc_ind")
            source_of_funds = st.selectbox("Source of Funds", SOF_LIST, key="sc_sof")
            pep_status = st.selectbox("PEP Status", PEP_LIST, key="sc_pep")
        with c4:
            st.markdown("#### 🌍 Geographic Risk")
            customer_country = st.selectbox("Customer's Home Country", ALL_COUNTRIES, index=ALL_COUNTRIES.index("IN"), key="sc_cc")
            destination_country = st.selectbox("Transaction Destination Country", ALL_COUNTRIES, index=ALL_COUNTRIES.index("IN"), key="sc_dc")

    with tab3:
        c5, c6 = st.columns(2)
        with c5:
            st.markdown("#### 🏦 Product / Service")
            account_type = st.selectbox("Account Type", ACCT_TYPES_LIST, key="sc_acct")
            payment_channel = st.selectbox("Payment Channel", CHANNELS_LIST, key="sc_chan")
        with c6:
            st.markdown("#### 📈 Transaction Behavior")
            behavior_change = st.slider("Deviation from Expected Activity (%)", 0, 700, 0, step=10, key="sc_beh",
                help="How much higher is this transaction vs customer's usual activity baseline?")

    with tab4:
        c7, c8 = st.columns(2)
        with c7:
            st.markdown("#### 🔎 Screening & Compliance")
            sanctions_hit = st.selectbox("Sanctions Screening Result", SANCTIONS_LIST, key="sc_sanc")
            adverse_media = st.selectbox("Adverse Media", ADVERSE_LIST, key="sc_adv")
            law_enforcement = st.selectbox("Law Enforcement Match", LE_LIST, key="sc_le")
        with c8:
            st.markdown("#### 🕸️ Relationship / Network")
            ownership_layers = st.number_input("Ownership / Beneficial Ownership Layers", 0, 10, 0, key="sc_own")
            linked_flagged = st.number_input("Linked Accounts Already Flagged", 0, 20, 0, key="sc_link")
            counterparty_c = st.selectbox("Counterparty Country", ALL_COUNTRIES, index=ALL_COUNTRIES.index("IN"), key="sc_cpty")

    params = {
        "account_age": int(account_age), "amount": txn_amount, "billing_country": billing_c,
        "ip_country": ip_c, "hour": txn_hour, "attempts": int(attempts), "txns_today": int(txns_today),
        "new_device": new_device, "device_changes": int(device_chg), "customer_type": customer_type,
        "industry": industry, "source_of_funds": source_of_funds, "pep_status": pep_status,
        "customer_country": customer_country, "destination_country": destination_country,
        "behavior_change_pct": behavior_change, "account_type": account_type,
        "payment_channel": payment_channel, "ownership_layers": int(ownership_layers),
        "linked_flagged": int(linked_flagged), "counterparty_country": counterparty_c,
        "sanctions_hit": sanctions_hit, "adverse_media": adverse_media, "law_enforcement": law_enforcement
    }
    result = compute_full_score(params)
    score = result["final_score"]
    level, cls = risk_level(score)
    clr = color_for(cls)

    st.markdown("---")
    res1, res2 = st.columns([1, 1.4])

    with res1:
        with st.expander("📋 Submission Details (optional)", expanded=False):
            sender_name = st.text_input("Sender Name", placeholder="e.g. Arjun Mehta", key="sc_name")
            txn_ref = st.text_input("Transaction Reference", value=f"TXN{random.randint(100000,999999)}", key="sc_ref")

        mult_line = f"<div style='font-family:Share Tech Mono;font-size:0.78rem;color:#fbbf24;margin-top:5px'>base {result['base_total']} × {result['multiplier']}</div>" if result["multiplier"]>1 else ""
        st.markdown(f"""<div class='score-dial' style='text-align:center;padding:24px 20px;
            background:linear-gradient(135deg,#0c0e1a,#12152a);border:1.5px solid {clr}55;
            border-radius:16px;margin-bottom:18px;--glow-col:{clr};'>
          <div style='font-family:Share Tech Mono;font-size:0.65rem;letter-spacing:4px;color:#6b7499;margin-bottom:8px'>LIVE RISK SCORE</div>
          <div style='font-family:Share Tech Mono;font-size:4rem;font-weight:700;color:{clr};line-height:1;text-shadow:0 0 30px {clr}88'>{score}</div>
          {mult_line}<div style='margin-top:12px'><span class='risk-badge badge-{cls}'>{level}</span></div>
        </div>""", unsafe_allow_html=True)

        if cls=="critical":   st.error("🚨 **Block transaction.** Escalate to fraud & AML team immediately.")
        elif cls=="high":     st.warning("⚠️ **Manual review required.** Request additional KYC verification.")
        elif cls=="medium":   st.info("ℹ️ **Allow with monitoring.** Log for pattern analysis.")
        else:                 st.success("✅ **Low risk.** Standard processing.")

        if st.button("⟶  Save to Alert Feed & Database", key="scanner_submit", use_container_width=True, type="primary"):
            new_txn = {
                "name": st.session_state.get("sc_name") or "Anonymous",
                "params": params, "result": result, "score": score, "level": level, "class": cls,
                "time": datetime.now().strftime("%H:%M:%S"),
                "txn_id": st.session_state.get("sc_ref") or f"TXN{random.randint(100000,999999)}",
            }
            st.session_state.transactions.insert(0, new_txn)
            st.session_state.scanner_history.insert(0, new_txn)
            save_transaction(new_txn, source="scanner")
            neo4j_push_transaction(new_txn)
            st.success(f"✅ **{new_txn['txn_id']}** saved to database and added to alert feed.")

        if st.button("✦  Ask Gemini to Analyse This Score", key="gemini_scanner_btn", use_container_width=True):
            with st.spinner("Gemini is analysing the transaction..."):
                gemini_text = ask_gemini(score, result, level, params)
            st.session_state["gemini_scanner_result"] = gemini_text
            st.session_state["gemini_scanner_snap"] = score

        if st.session_state.get("gemini_scanner_result"):
            snap = st.session_state.get("gemini_scanner_snap","")
            snap_note = f"<div style='font-size:0.72rem;color:#6b7499;margin-bottom:10px;font-family:Share Tech Mono'>Analysis for score {snap} — re-run after changing inputs</div>" if snap else ""
            st.markdown(f"""<div class='why-box' style='border-color:rgba(139,92,246,0.4);background:linear-gradient(135deg,rgba(139,92,246,0.07),rgba(0,229,195,0.03));margin-top:0'>
              <div class='why-title' style='color:#8b5cf6'>🤖 GEMINI AI ANALYSIS</div>
              {snap_note}
              <p style='color:#dde4f0;font-size:0.92rem;line-height:1.75;margin:0'>{st.session_state["gemini_scanner_result"]}</p>
            </div>""", unsafe_allow_html=True)

    with res2:
        st.markdown("<div class='section-header'>Factor Breakdown — All Domains</div>", unsafe_allow_html=True)
        for f in sorted(result["factors"], key=lambda x: x["score"], reverse=True):
            tc = TAG_COLORS.get(f["tag"], "#00e5c3")
            if f["score"]>=15:   pc,icon="#f43f5e","🔴"
            elif f["score"]>=8:  pc,icon="#fb923c","🟠"
            elif f["score"]>=4:  pc,icon="#fbbf24","🟡"
            else:                pc,icon="#444e70","⚪"
            st.markdown(f"""<div class='factor-row'><span style='color:{pc}'>{icon} {f["name"]}
              <span class='factor-tag' style='color:{tc};border-color:{tc}33'>{f["tag"]}</span>
              <span style='color:#444e70;font-size:0.78rem;margin-left:6px'>{f["label"]}</span></span>
              <span style='font-family:Share Tech Mono;color:{pc};font-weight:700;font-size:1.05rem'>+{f["score"]}</span>
            </div>""", unsafe_allow_html=True)
        st.markdown(why_box_html(result, score, level, cls), unsafe_allow_html=True)

    if st.session_state.get("scanner_history"):
        st.markdown("---")
        st.markdown("<div class='section-header'>Submitted Transactions This Session</div>", unsafe_allow_html=True)
        for t in st.session_state.scanner_history[:10]:
            clr2 = color_for(t["class"])
            st.markdown(f"""<div class='alert-card alert-{t["class"]}' style='padding:10px 14px'>
              <div style='display:flex;justify-content:space-between;align-items:center'>
                <span style='font-weight:700'>{t["name"]}</span>
                <span style='display:flex;align-items:center;gap:8px'>
                  <span style='font-family:Share Tech Mono;font-size:1.2rem;color:{clr2};font-weight:700'>{t["score"]}</span>
                  <span class='risk-badge badge-{t["class"]}'>{t["level"]}</span>
                </span>
              </div>
              <div style='color:#6b7499;font-size:0.8rem;margin-top:4px'>{t["txn_id"]} · ₹{t["params"].get("amount",0):,.0f} · {t["params"].get("ip_country","")} → {t["params"].get("billing_country","")} · {t["time"]}</div>
            </div>""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 3 — BULK CSV SCANNER
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "Bulk CSV Scanner":
    st.markdown("# ⬆ Bulk CSV Scanner")
    st.markdown("<div class='section-header'>Upload hundreds or thousands of transactions · auto-scored · Gemini executive summary</div>", unsafe_allow_html=True)

    # Sample CSV download
    sample_csv = generate_sample_csv(100)
    st.download_button(
        label="⬇  Download Sample CSV (100 transactions)",
        data=sample_csv,
        file_name="sample_transactions.csv",
        mime="text/csv",
        key="sample_dl"
    )

    st.markdown("""<div class='bulk-drop'>
      <div style='font-family:Share Tech Mono;font-size:0.7rem;letter-spacing:3px;color:#00e5c3;margin-bottom:8px'>UPLOAD YOUR TRANSACTION FILE</div>
      <div style='color:#6b7499;font-size:0.88rem'>Accepts any CSV with transaction data. Columns are auto-detected — no template required.<br>
      Works with bank exports, core banking dumps, spreadsheet exports. Up to 10,000 rows.</div>
    </div>""", unsafe_allow_html=True)

    uploaded_file = st.file_uploader("Choose a CSV file", type=["csv"], key="bulk_upload", label_visibility="collapsed")

    if uploaded_file is not None:
        try:
            df_raw = pd.read_csv(uploaded_file)
            st.markdown(f"<div style='color:#00e5c3;font-family:Share Tech Mono;font-size:0.82rem;margin-bottom:12px'>✓ Loaded {len(df_raw):,} rows · {len(df_raw.columns)} columns detected</div>", unsafe_allow_html=True)

            # Show detected columns with colour coding
            mapping = auto_map_columns(df_raw.columns.tolist())
            mapped_fields = set(mapping.keys())
            all_fields = set(CSV_ALIASES.keys())
            unmapped = all_fields - mapped_fields - {"sender_name","txn_id"}

            st.markdown("<div class='section-header'>Column Mapping</div>", unsafe_allow_html=True)
            mapped_html = "".join([f"<span class='col-chip' style='color:#00e5c3;border-color:#00e5c344;background:rgba(0,229,195,0.07)'>✓ {f} → {c}</span>" for f,c in mapping.items() if f not in ("sender_name","txn_id")])
            unmapped_html = "".join([f"<span class='col-chip' style='color:#6b7499;border-color:#2a2f5a;background:rgba(30,34,64,0.5)'>— {f} (default)</span>" for f in sorted(unmapped)])
            st.markdown(f"<div style='margin-bottom:8px'>{mapped_html}</div>", unsafe_allow_html=True)
            if unmapped_html:
                st.markdown(f"<div style='margin-bottom:16px'>{unmapped_html}</div>", unsafe_allow_html=True)

            if st.button("🚀  Run Full CAML Scan on All Rows", key="bulk_run", use_container_width=True, type="primary"):
                st.session_state.bulk_results = None
                st.session_state.bulk_gemini = None

                progress_bar = st.progress(0, text="Initialising scan...")
                status_text = st.empty()

                results = []
                total_rows = min(len(df_raw), 10000)

                for i, (_, row) in enumerate(df_raw.iterrows()):
                    if i >= 10000:
                        break
                    params = row_to_params(row, mapping)
                    result = compute_full_score(params)
                    score = result["final_score"]
                    lv, cls = risk_level(score)
                    name = str(safe_get(row, mapping, "sender_name", f"Record {i+1}") or f"Record {i+1}")
                    txn_id = str(safe_get(row, mapping, "txn_id", f"ROW{i+1}") or f"ROW{i+1}")
                    results.append({
                        "row": i+1,
                        "txn_id": txn_id,
                        "name": name,
                        "params": params,
                        "result": result,
                        "score": score,
                        "level": lv,
                        "class": cls,
                        "time": datetime.now().strftime("%H:%M:%S"),
                    })
                    pct = (i+1) / total_rows
                    if i % 10 == 0 or i == total_rows - 1:
                        progress_bar.progress(pct, text=f"Scoring row {i+1:,} of {total_rows:,}...")
                        status_text.markdown(f"<span style='color:#6b7499;font-size:0.82rem;font-family:Share Tech Mono'>Last scored: {name} → score {score} ({lv})</span>", unsafe_allow_html=True)

                progress_bar.progress(1.0, text="✓ Scan complete!")
                status_text.empty()
                st.session_state.bulk_results = results
                # Merge into main transactions so Dashboard updates
                st.session_state.transactions = results + st.session_state.transactions
                st.rerun()

        except Exception as e:
            st.error(f"Error reading CSV: {str(e)}")

    # ── Show results ────────────────────────────────────────────────────────────
    if st.session_state.bulk_results:
        results = st.session_state.bulk_results
        n = len(results)
        critical  = [r for r in results if r["class"]=="critical"]
        high_r    = [r for r in results if r["class"]=="high"]
        medium_r  = [r for r in results if r["class"]=="medium"]
        low_r     = [r for r in results if r["class"]=="low"]
        scores    = [r["score"] for r in results]
        amounts   = [r["params"].get("amount",0) for r in results]
        val_at_risk = sum(r["params"].get("amount",0) for r in results if r["class"] in ("critical","high"))
        sanctions_hits = sum(1 for r in results if r["params"].get("sanctions_hit","No Hit") != "No Hit")
        pep_count = sum(1 for r in results if r["params"].get("pep_status","Not a PEP") != "Not a PEP")

        st.markdown("---")
        st.markdown("<div class='section-header'>Batch Scan Results</div>", unsafe_allow_html=True)

        # KPI row
        k1,k2,k3,k4,k5,k6 = st.columns(6)
        def bstat(col, val, label, color="#00e5c3"):
            col.markdown(f"<div class='bulk-stat'><div class='bulk-stat-val' style='color:{color}'>{val}</div><div class='bulk-stat-label'>{label}</div></div>", unsafe_allow_html=True)
        bstat(k1, f"{n:,}", "Total Scanned")
        bstat(k2, len(critical), "🔴 Critical", "#f43f5e")
        bstat(k3, len(high_r),   "🟠 High",     "#fb923c")
        bstat(k4, len(medium_r), "🟡 Medium",   "#fbbf24")
        bstat(k5, f"{np.mean(scores):.1f}", "Avg Score")
        bstat(k6, f"₹{val_at_risk/100000:.1f}L", "Value at Risk", "#f43f5e")

        st.markdown("<div style='margin-top:16px'></div>", unsafe_allow_html=True)

        k7, k8, k9 = st.columns(3)
        bstat(k7, max(scores), "Highest Score", "#f43f5e")
        bstat(k8, sanctions_hits, "Sanctions Hits", "#f43f5e" if sanctions_hits>0 else "#00e5c3")
        bstat(k9, pep_count, "PEP-Linked", "#fb923c" if pep_count>0 else "#00e5c3")

        # Risk distribution bars
        st.markdown("<div style='margin-top:20px'></div>", unsafe_allow_html=True)
        st.markdown("<div class='section-header'>Risk Distribution</div>", unsafe_allow_html=True)
        bar_cols={"CRITICAL":"#f43f5e","HIGH":"#fb923c","MEDIUM":"#fbbf24","LOW":"#00e5c3"}
        for label, count in [("CRITICAL",len(critical)),("HIGH",len(high_r)),("MEDIUM",len(medium_r)),("LOW",len(low_r))]:
            pct = count/n if n>0 else 0
            st.markdown(f"<div style='display:flex;justify-content:space-between;margin-bottom:2px'><span style='color:{bar_cols[label]};font-weight:600'>{label}</span><span style='color:#6b7499;font-family:Share Tech Mono;font-size:0.85rem'>{count:,} &nbsp;·&nbsp; {round(pct*100,1)}%</span></div>", unsafe_allow_html=True)
            st.markdown(f"<div class='progress-bar-outer'><div class='progress-bar-inner' style='width:{pct*100:.2f}%;background:linear-gradient(90deg,{bar_cols[label]},{bar_cols[label]}88)'></div></div><div style='margin-bottom:10px'></div>", unsafe_allow_html=True)

        # Gemini executive summary
        st.markdown("<div class='section-header' style='margin-top:8px'>Gemini AI Executive Summary</div>", unsafe_allow_html=True)
        top_risks = sorted(results, key=lambda x: x["score"], reverse=True)

        if st.session_state.bulk_gemini is None:
            if st.button("✦  Generate Gemini Executive Summary", key="bulk_gemini_btn", use_container_width=True):
                stats_for_gemini = {
                    "critical": len(critical), "high": len(high_r), "medium": len(medium_r), "low": len(low_r),
                    "critical_pct": len(critical)/n*100, "high_pct": len(high_r)/n*100,
                    "medium_pct": len(medium_r)/n*100, "low_pct": len(low_r)/n*100,
                    "avg_score": np.mean(scores), "max_score": max(scores),
                    "value_at_risk": val_at_risk, "sanctions_hits": sanctions_hits, "pep_count": pep_count,
                }
                with st.spinner("Gemini is writing the executive summary..."):
                    st.session_state.bulk_gemini = ask_gemini_bulk_summary(stats_for_gemini, top_risks, len(df_raw.columns) if uploaded_file else 0, n)
                st.rerun()
        else:
            st.markdown(f"""<div class='gemini-exec'>
              <div style='font-family:Share Tech Mono;font-size:0.7rem;letter-spacing:3px;color:#8b5cf6;margin-bottom:14px'>🤖 GEMINI — CHIEF AML OFFICER BRIEF</div>
              <p style='color:#dde4f0;font-size:0.95rem;line-height:1.85;margin:0'>{st.session_state.bulk_gemini}</p>
            </div>""", unsafe_allow_html=True)
            if st.button("↺  Regenerate Summary", key="bulk_gemini_regen"):
                st.session_state.bulk_gemini = None
                st.rerun()

        # Top 20 highest risk table
        st.markdown("<div class='section-header' style='margin-top:24px'>Top Flagged Transactions</div>", unsafe_allow_html=True)
        show_cls = st.multiselect("Filter by risk level", ["CRITICAL","HIGH","MEDIUM","LOW"], default=["CRITICAL","HIGH"], key="bulk_filter")
        filtered_results = [r for r in top_risks if r["level"] in show_cls]

        for r in filtered_results[:30]:
            clr2 = color_for(r["class"])
            top_f = sorted(r["result"]["factors"], key=lambda x: x["score"], reverse=True)[:3]
            tags_h = " ".join([
                '<span style="font-family:Share Tech Mono;font-size:0.65rem;padding:1px 6px;border-radius:4px;'
                'background:' + TAG_COLORS.get(f["tag"],"#aaa") + '18;border:1px solid ' + TAG_COLORS.get(f["tag"],"#aaa") + '44;'
                'color:' + TAG_COLORS.get(f["tag"],"#aaa") + ';margin-right:3px">' + h(f["name"]) + ' +' + str(f["score"]) + '</span>'
                for f in top_f
            ])
            mult_badge = ('<span style="color:#fbbf24;font-family:Share Tech Mono;font-size:0.7rem;margin-left:6px">&#x26a1;&times;' + f'{r["result"]["multiplier"]:.2f}' + '</span>') if r["result"]["multiplier"]>1 else ""
            pep_badge = '<span style="font-family:Share Tech Mono;font-size:0.65rem;padding:1px 6px;border-radius:3px;background:rgba(244,63,94,0.12);border:1px solid rgba(244,63,94,0.3);color:#f43f5e;margin-left:5px">PEP</span>' if r["params"].get("pep_status","Not a PEP")!="Not a PEP" else ""
            sanc_badge = '<span style="font-family:Share Tech Mono;font-size:0.65rem;padding:1px 6px;border-radius:3px;background:rgba(244,63,94,0.18);border:1px solid #f43f5e;color:#f43f5e;margin-left:4px">SANCTIONS</span>' if r["params"].get("sanctions_hit","No Hit")!="No Hit" else ""
            name_s = h(r["name"])
            txnid_s = h(r["txn_id"])
            ctype_s = h(r["params"].get("customer_type","")[:20])
            channel_s = h(r["params"].get("payment_channel","")[:20])
            ip_s = h(r["params"].get("ip_country","?"))
            bill_s = h(r["params"].get("billing_country","?"))
            amt_s = f'{r["params"].get("amount",0):,.0f}'
            score_s = str(r["score"])
            row_s = str(r["row"])
            card_cls = r["class"]
            lvl_s = r["level"]
            html_card = (
                '<div class="alert-card alert-' + card_cls + '">'
                '<div style="display:flex;justify-content:space-between;align-items:flex-start">'
                '<div>'
                '<span style="font-weight:700">' + name_s + '</span>'
                '<span style="color:#2a2f5a;font-family:Share Tech Mono;font-size:0.68rem;margin-left:8px">' + txnid_s + ' &middot; row ' + row_s + '</span>'
                + pep_badge + sanc_badge +
                '</div>'
                '<div style="display:flex;align-items:center;gap:8px">'
                '<span style="font-family:Share Tech Mono;font-size:1.4rem;font-weight:700;color:' + clr2 + ';text-shadow:0 0 10px ' + clr2 + '66">' + score_s + '</span>'
                + mult_badge +
                '<span class="risk-badge badge-' + card_cls + '">' + lvl_s + '</span>'
                '</div>'
                '</div>'
                '<div style="margin-top:5px;color:#6b7499;font-size:0.83rem">'
                '&#x1f4b0; &#8377;' + amt_s + ' &nbsp;&middot;&nbsp; '
                '&#x1f310; ' + ip_s + ' &rarr; ' + bill_s + ' &nbsp;&middot;&nbsp; '
                '&#x1f464; ' + ctype_s + ' &nbsp;&middot;&nbsp; '
                '&#x1f3e6; ' + channel_s +
                '</div>'
                '<div style="margin-top:7px">' + tags_h + '</div>'
                '</div>'
            )
            st.markdown(html_card, unsafe_allow_html=True)

        # Export results to CSV
        st.markdown("<div class='section-header' style='margin-top:20px'>Export Results</div>", unsafe_allow_html=True)
        export_rows = []
        for r in results:
            top3 = sorted(r["result"]["factors"], key=lambda x: x["score"], reverse=True)[:3]
            export_rows.append({
                "Row": r["row"],
                "TXN ID": r["txn_id"],
                "Name": r["name"],
                "CAML Score": r["score"],
                "Risk Level": r["level"],
                "Risk Class": r["class"],
                "Base Score": r["result"]["base_total"],
                "Multiplier": r["result"]["multiplier"],
                "Multiplier Reason": r["result"]["multiplier_reason"] or "",
                "Amount (₹)": r["params"].get("amount",0),
                "IP Country": r["params"].get("ip_country",""),
                "Billing Country": r["params"].get("billing_country",""),
                "Customer Country": r["params"].get("customer_country",""),
                "Destination Country": r["params"].get("destination_country",""),
                "Customer Type": r["params"].get("customer_type",""),
                "Industry": r["params"].get("industry",""),
                "PEP Status": r["params"].get("pep_status",""),
                "Sanctions Hit": r["params"].get("sanctions_hit",""),
                "Adverse Media": r["params"].get("adverse_media",""),
                "Law Enforcement": r["params"].get("law_enforcement",""),
                "Top Factor 1": f'{top3[0]["name"]} (+{top3[0]["score"]})' if len(top3)>0 else "",
                "Top Factor 2": f'{top3[1]["name"]} (+{top3[1]["score"]})' if len(top3)>1 else "",
                "Top Factor 3": f'{top3[2]["name"]} (+{top3[2]["score"]})' if len(top3)>2 else "",
            })
        export_df = pd.DataFrame(export_rows)
        csv_out = export_df.to_csv(index=False)

        col_exp1, col_exp2 = st.columns(2)
        with col_exp1:
            st.download_button(
                label=f"⬇  Export All {n:,} Results as CSV",
                data=csv_out,
                file_name=f"caml_scan_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
                key="bulk_export_all",
                use_container_width=True
            )
        with col_exp2:
            critical_high_df = export_df[export_df["Risk Class"].isin(["critical","high"])]
            st.download_button(
                label=f"⬇  Export Critical + High Only ({len(critical_high_df):,} rows)",
                data=critical_high_df.to_csv(index=False),
                file_name=f"caml_flagged_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
                key="bulk_export_flagged",
                use_container_width=True
            )

        # Optionally save all to DB
        st.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)
        if st.button(f"💾  Save All {n:,} Results to Database", key="bulk_save_db", use_container_width=True):
            saved = 0
            prog = st.progress(0, text="Saving to database...")
            for i, r in enumerate(results):
                save_transaction(r, source="bulk_csv")
                saved += 1
                if i % 50 == 0:
                    prog.progress((i+1)/n, text=f"Saved {i+1:,} of {n:,}...")
            prog.progress(1.0, text="✓ All saved!")
            st.success(f"✅ {saved:,} transactions saved to `cyberaml.db` (source: bulk_csv)")

        if st.button(f"🔗  Push All {n:,} Results to Neo4j Graph", key="bulk_neo4j", use_container_width=True):
            with st.spinner("Pushing to Neo4j..."):
                pushed, neo_err = neo4j_push_bulk(results)
            if neo_err:
                st.error(f"Neo4j error: {neo_err}")
            else:
                st.success(f"✅ {pushed:,} transactions pushed to Neo4j. Go to Mule Radar → Live Graph tab to see detected rings.")

    elif uploaded_file is None:
        st.markdown("""<div style='text-align:center;padding:40px 20px;color:#2a2f5a'>
          <div style='font-size:3rem;margin-bottom:12px'>⬆</div>
          <div style='font-family:Share Tech Mono;font-size:0.8rem;letter-spacing:2px;color:#2a2f5a'>Upload a CSV file above to begin</div>
          <div style='font-size:0.85rem;color:#1e2240;margin-top:8px'>Or download the sample CSV to try it instantly</div>
        </div>""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 4 — ALERT FEED
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "Live Alert Feed":
    st.markdown("# 📡 Live Alert Feed")
    st.markdown("<div class='section-header'>All transactions · sorted by risk score</div>", unsafe_allow_html=True)
    fc1,_=st.columns([1,3])
    with fc1:
        show_levels=st.multiselect("Filter by Level",["CRITICAL","HIGH","MEDIUM","LOW"],default=["CRITICAL","HIGH","MEDIUM"])
    filtered=sorted([t for t in txns if t["level"] in show_levels],key=lambda x:x["score"],reverse=True)
    st.markdown(f"<span style='color:#6b7499;font-size:0.88rem'>Showing <strong style='color:#dde4f0'>{len(filtered)}</strong> alerts</span>", unsafe_allow_html=True)
    st.markdown("")
    for t in filtered:
        clr=color_for(t["class"]); top_f=sorted(t["result"]["factors"],key=lambda x:x["score"],reverse=True)[:3]
        tags_h=" ".join([f'<span style="font-family:Share Tech Mono;font-size:0.68rem;padding:2px 7px;border-radius:4px;background:{TAG_COLORS.get(f["tag"],"#aaa")}18;border:1px solid {TAG_COLORS.get(f["tag"],"#aaa")}44;color:{TAG_COLORS.get(f["tag"],"#aaa")};margin-right:4px">{f["name"]} +{f["score"]}</span>' for f in top_f])
        mn=f' &nbsp;<span style="color:#fbbf24;font-family:Share Tech Mono;font-size:0.72rem">⚡×{t["result"]["multiplier"]}</span>' if t["result"]["multiplier"]>1 else ""
        pep_badge=f'<span style="font-family:Share Tech Mono;font-size:0.68rem;padding:2px 6px;border-radius:3px;background:rgba(244,63,94,0.12);border:1px solid rgba(244,63,94,0.3);color:#f43f5e;margin-left:6px">PEP</span>' if t["params"].get("pep_status","Not a PEP")!="Not a PEP" else ""
        sanc_badge=f'<span style="font-family:Share Tech Mono;font-size:0.68rem;padding:2px 6px;border-radius:3px;background:rgba(244,63,94,0.18);border:1px solid #f43f5e;color:#f43f5e;margin-left:4px">SANCTIONS HIT</span>' if t["params"].get("sanctions_hit","No Hit")!="No Hit" else ""
        st.markdown(f"""<div class='alert-card alert-{t["class"]}'>
          <div style='display:flex;justify-content:space-between;align-items:flex-start;'>
            <div><span style='font-weight:700;font-size:1rem'>{t["name"]}</span>
              <span style='color:#2a2f5a;font-family:Share Tech Mono;font-size:0.7rem;margin-left:10px'>{t["txn_id"]}</span>
              {pep_badge}{sanc_badge}</div>
            <div style='text-align:right;display:flex;align-items:center;gap:8px'>
              <span style='font-family:Share Tech Mono;font-size:1.5rem;font-weight:700;color:{clr};text-shadow:0 0 12px {clr}66'>{t["score"]}</span>
              {mn}<span class='risk-badge badge-{t["class"]}'>{t["level"]}</span></div>
          </div>
          <div style='margin-top:6px;color:#6b7499;font-size:0.85rem'>
            💰 ₹{t["params"].get("amount",0):,.0f} &nbsp;·&nbsp; 🌐 {t["params"].get("ip_country","")} → {t["params"].get("billing_country","")}
            &nbsp;·&nbsp; 👤 {t["params"].get("customer_type","—")[:22]} &nbsp;·&nbsp; 🕐 {t["time"]}</div>
          <div style='margin-top:9px'>{tags_h}</div>
        </div>""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 5 — MULE RADAR
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "Mule Radar":
    st.markdown("# 🕸️ Mule Radar")
    st.markdown("<div class='section-header'>Cross-account network analysis · coordinated ring detection · Neo4j live graph</div>", unsafe_allow_html=True)

    # ── Tabs: Live Neo4j Graph vs Generated Demo ───────────────────────────────
    neo_tab, demo_tab = st.tabs(["🔴 Live Graph (Neo4j)", "🔵 Demo Rings (Generated)"])

    # ════════════════════════════════════════════════════════════
    # TAB 1 — LIVE NEO4J
    # ════════════════════════════════════════════════════════════
    with neo_tab:
        st.markdown("<div class='section-header'>Real-time ring detection from your transaction graph</div>", unsafe_allow_html=True)

        # Connection status
        driver_test, conn_err = get_neo4j_driver()
        if conn_err:
            st.error(f"⚠️ Neo4j connection failed: {conn_err}. Make sure `neo4j` pip package is installed (`pip install neo4j`).")
        else:
            st.markdown("""<div style='display:inline-flex;align-items:center;gap:8px;background:rgba(0,229,195,0.07);
                border:1px solid rgba(0,229,195,0.25);border-radius:8px;padding:6px 14px;margin-bottom:16px;font-size:0.82rem;font-family:Share Tech Mono'>
                <span style='width:8px;height:8px;border-radius:50%;background:#00e5c3;display:inline-block'></span>
                Connected to Neo4j AuraDB · c899d0d7.databases.neo4j.io
            </div>""", unsafe_allow_html=True)
            driver_test.close()

            # Graph stats
            gstats, stats_err = neo4j_get_graph_stats()
            if gstats:
                gs1,gs2,gs3,gs4,gs5 = st.columns(5)
                gs1.metric("Account Nodes", gstats.get("accounts",0))
                gs2.metric("Transactions", gstats.get("txns",0))
                gs3.metric("Countries", gstats.get("countries",0))
                gs4.metric("🔴 Critical Accounts", gstats.get("critical",0))
                gs5.metric("Sanctions Hits", gstats.get("sanctions",0))

            st.markdown("---")

            # How to get data in
            if gstats.get("txns",0) == 0:
                st.info("""📋 **No transaction data in Neo4j yet.**
Upload a CSV in **Bulk CSV Scanner** and click **Push All Results to Neo4j Graph**, 
or submit a transaction via **CAML Score** to populate the graph.""")
            else:
                # Detect rings button
                if st.button("🔍  Run Ring Detection on Live Graph", key="neo_detect", use_container_width=True, type="primary"):
                    with st.spinner("Running Cypher ring detection queries on Neo4j..."):
                        detected, det_err = neo4j_detect_rings()
                    if det_err:
                        st.error(f"Detection error: {det_err}")
                    else:
                        st.session_state.neo4j_rings = detected
                        st.success(f"✅ Detected {len(detected)} suspicious patterns from live graph data.")
                        st.rerun()

                neo_rings = st.session_state.get("neo4j_rings", [])

                if not neo_rings:
                    st.markdown("""<div style='text-align:center;padding:40px;color:#2a2f5a'>
                        <div style='font-size:2.5rem;margin-bottom:12px'>🔍</div>
                        <div style='font-family:Share Tech Mono;font-size:0.8rem;letter-spacing:2px'>
                            Click "Run Ring Detection" to scan the live graph
                        </div>
                    </div>""", unsafe_allow_html=True)
                else:
                    # KPI row
                    nr_critical = sum(1 for r in neo_rings if r["cls"]=="critical")
                    nr_val = sum(r["total_value"] for r in neo_rings)
                    nr_accounts = sum(r["n_accounts"] for r in neo_rings)
                    nk1,nk2,nk3,nk4 = st.columns(4)
                    nk1.metric("Patterns Detected", len(neo_rings))
                    nk2.metric("🔴 Critical", nr_critical)
                    nk3.metric("Accounts in Rings", nr_accounts)
                    nk4.metric("Value at Risk", f"₹{nr_val/100000:.1f}L")
                    st.markdown("---")

                    # Ring selector + detail
                    left_n, right_n = st.columns([1, 1.8])
                    with left_n:
                        st.markdown("<div class='section-header'>Detected Patterns</div>", unsafe_allow_html=True)
                        sel_neo_id = st.session_state.get("selected_neo_ring", neo_rings[0]["id"])
                        for nr in neo_rings:
                            is_sel = nr["id"] == sel_neo_id
                            badge_col = "#f43f5e" if nr["cls"]=="critical" else "#fb923c" if nr["cls"]=="high" else "#fbbf24"
                            if st.button(
                                f"{'▶ ' if is_sel else ''}{nr['id']}  ·  {nr['type']}  ·  {nr['level'].upper()}",
                                key=f"neo_ring_{nr['id']}", use_container_width=True
                            ):
                                st.session_state.selected_neo_ring = nr["id"]; st.rerun()

                        st.markdown("")
                        st.markdown("<div class='section-header'>Pattern Legend</div>", unsafe_allow_html=True)
                        for ptype, pdesc in [
                            ("Sanctioned Hub",   "Multiple senders transacting to sanctioned countries"),
                            ("IP Geo Cluster",   "Accounts sharing a high-risk IP origin country"),
                            ("PEP High-Value",   "Politically exposed persons sending large transactions"),
                        ]:
                            st.markdown(f"<div style='margin-bottom:8px'><span style='color:#00e5c3;font-weight:600'>{ptype}</span><br><span style='color:#6b7499;font-size:0.82rem'>{pdesc}</span></div>", unsafe_allow_html=True)

                    with right_n:
                        nr = next((r for r in neo_rings if r["id"]==sel_neo_id), neo_rings[0])
                        clr = nr["color"]
                        st.markdown(f"<div class='section-header'>{h(nr['id'])} &middot; {h(nr['type'])} &middot; <span style='color:{clr}'>{nr['level'].upper()}</span> &nbsp;<span style='font-size:0.7rem;color:#6b7499'>[source: Neo4j live graph]</span></div>", unsafe_allow_html=True)

                        nm1,nm2,nm3 = st.columns(3)
                        nm1.metric("Ring Score",    nr["ring_score"])
                        nm2.metric("Accounts",      nr["n_accounts"])
                        nm3.metric("Value Moved",   f"₹{nr['total_value']:,}")

                        # D3 graph
                        st.markdown("<div style='background:#07080f;border:1px solid #1e2240;border-radius:12px;overflow:hidden;margin:10px 0'>", unsafe_allow_html=True)
                        st.components.v1.html(render_ring_graph(nr), height=490, scrolling=False)
                        st.markdown("</div>", unsafe_allow_html=True)

                        st.markdown("<div class='section-header' style='margin-top:12px'>Detection Signals</div>", unsafe_allow_html=True)
                        for sig in nr["signals"]:
                            st.markdown(f"<div style='color:#f43f5e;font-size:0.88rem;padding:3px 0'>◆ <span style='color:#dde4f0'>{h(sig)}</span></div>", unsafe_allow_html=True)

                        # Gemini analysis
                        gemini_neo_key = f"gemini_neo_{nr['id']}"
                        st.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)
                        if st.button(f"✦  Ask Gemini to Analyse {nr['id']}", key=f"gemini_neo_btn_{nr['id']}", use_container_width=True):
                            with st.spinner("Gemini is analysing the live ring..."):
                                st.session_state[gemini_neo_key] = ask_gemini_ring(nr)
                        if st.session_state.get(gemini_neo_key):
                            st.markdown(f"""<div class='why-box' style='border-color:rgba(139,92,246,0.4);background:linear-gradient(135deg,rgba(139,92,246,0.07),rgba(0,229,195,0.03))'>
                              <div class='why-title' style='color:#8b5cf6'>🤖 GEMINI RING ANALYSIS</div>
                              <p style='color:#dde4f0;font-size:0.92rem;line-height:1.75;margin:0'>{st.session_state[gemini_neo_key]}</p>
                            </div>""", unsafe_allow_html=True)

                        # Account table
                        st.markdown("<div class='section-header' style='margin-top:14px'>Accounts in Ring</div>", unsafe_allow_html=True)
                        acct_df = pd.DataFrame([{
                            "Name":    a["name"], "ID": a["id"],
                            "Role":    a["role"].title(),
                            "Country": a["country"],
                            "Age (days)": a["age_days"],
                        } for a in nr["accounts"]])
                        st.dataframe(acct_df, use_container_width=True, hide_index=True)

    # ════════════════════════════════════════════════════════════
    # TAB 2 — DEMO RINGS (original generated rings)
    # ════════════════════════════════════════════════════════════
    with demo_tab:
        total_rings=len(rings); critical_rings=sum(1 for r in rings if r["cls"]=="critical")
        total_accounts=sum(r["n_accounts"] for r in rings); total_value=sum(r["total_value"] for r in rings)
        k1,k2,k3,k4=st.columns(4)
        k1.metric("Rings Detected",total_rings); k2.metric("🔴 Critical Rings",critical_rings)
        k3.metric("Accounts Flagged",total_accounts); k4.metric("Value at Risk",f"₹{total_value/100000:.1f}L")
        st.markdown("---")
        left,right=st.columns([1,1.8])
        with left:
            st.markdown("<div class='section-header'>Detected Rings</div>", unsafe_allow_html=True)
            selected_ring_id=st.session_state.get("selected_ring",rings[0]["id"])
            for r in rings:
                is_sel=r["id"]==selected_ring_id
                if st.button(f"{'▶ ' if is_sel else ''}{r['id']}  ·  {r['type']}  ·  {r['level'].upper()}",key=f"ring_{r['id']}",use_container_width=True):
                    st.session_state.selected_ring=r["id"]; st.rerun()
            st.markdown(""); st.markdown("<div class='section-header'>Pattern Types</div>", unsafe_allow_html=True)
            for rt in RING_TYPES:
                st.markdown(f"<div style='margin-bottom:8px'><span style='color:#00e5c3;font-weight:600'>{rt['name']}</span><br><span style='color:#6b7499;font-size:0.82rem'>{rt['desc']}</span></div>", unsafe_allow_html=True)
        with right:
            ring=next((r for r in rings if r["id"]==selected_ring_id),rings[0]); clr=ring["color"]
            st.markdown(f"<div class='section-header'>{ring['id']} · {ring['type']} · <span style='color:{clr}'>{ring['level'].upper()}</span></div>", unsafe_allow_html=True)
            m1,m2,m3=st.columns(3); m1.metric("Ring Score",ring["ring_score"]); m2.metric("Accounts",ring["n_accounts"]); m3.metric("Value Moved",f"₹{ring['total_value']:,}")
            m4,m5,m6=st.columns(3); m4.metric("Mule Accounts",ring["n_mules"]); m5.metric("Victims",ring["n_victims"]); m6.metric("Risk Level",ring["level"].upper())
            st.markdown(f"<div style='background:#07080f;border:1px solid #1e2240;border-radius:12px;overflow:hidden;margin:10px 0'>", unsafe_allow_html=True)
            st.components.v1.html(render_ring_graph(ring),height=490,scrolling=False)
            st.markdown("</div>", unsafe_allow_html=True)
            st.markdown("<div class='section-header' style='margin-top:12px'>Detection Signals</div>", unsafe_allow_html=True)
            for sig in ring["signals"]:
                st.markdown(f"<div style='color:#f43f5e;font-size:0.88rem;padding:3px 0'>◆ <span style='color:#dde4f0'>{sig}</span></div>", unsafe_allow_html=True)
            gemini_ring_key=f"gemini_ring_{ring['id']}"
            st.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)
            if st.button(f"✦  Ask Gemini to Analyse {ring['id']}",key=f"gemini_ring_btn_{ring['id']}",use_container_width=True):
                with st.spinner("Gemini is analysing the ring..."):
                    st.session_state[gemini_ring_key]=ask_gemini_ring(ring)
            if st.session_state.get(gemini_ring_key):
                st.markdown(f"""<div class='why-box' style='border-color:rgba(139,92,246,0.4);background:linear-gradient(135deg,rgba(139,92,246,0.07),rgba(0,229,195,0.03))'>
                  <div class='why-title' style='color:#8b5cf6'>🤖 GEMINI RING ANALYSIS</div>
                  <p style='color:#dde4f0;font-size:0.92rem;line-height:1.75;margin:0'>{st.session_state[gemini_ring_key]}</p>
                </div>""", unsafe_allow_html=True)
            ctrl=ring["controller"]
            st.markdown("<div class='section-header' style='margin-top:14px'>Controller Account</div>", unsafe_allow_html=True)
            st.markdown(f"""<div style='background:rgba(244,63,94,0.06);border:1px solid rgba(244,63,94,0.2);border-radius:10px;padding:14px 18px;font-size:0.88rem'>
              <span style='color:#f43f5e;font-family:Share Tech Mono;font-weight:700'>{ctrl["name"]}</span>&nbsp;&nbsp;<span style='color:#2a2f5a'>{ctrl["id"]}</span><br>
              <span style='color:#6b7499'>IP Origin:</span> <span style='color:#fb923c'>{ctrl["country"]}</span>&nbsp;·&nbsp;
              <span style='color:#6b7499'>Age:</span> <span style='color:#fb923c'>{ctrl["age_days"]} days</span>&nbsp;·&nbsp;
              <span style='color:#6b7499'>Window:</span> <span style='color:#aab'>{ring["window"]}</span>
            </div>""", unsafe_allow_html=True)
            st.markdown("<div class='section-header' style='margin-top:14px'>Mule Accounts</div>", unsafe_allow_html=True)
            mule_df=pd.DataFrame([{"Name":a["name"],"Account":a["id"],"Role":a["role"].title(),"Age (days)":a["age_days"],"Country":a["country"]} for a in ring["accounts"] if a["role"]!="controller"])
            st.dataframe(mule_df,use_container_width=True,hide_index=True)

# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 6 — DATABASE VIEWER
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "Database":
    st.markdown("# ⬡ Database Viewer")
    st.markdown("<div class='section-header'>SQLite · cyberaml.db · transactions table</div>", unsafe_allow_html=True)

    s = db_stats()
    s1,s2,s3,s4,s5,s6,s7,s8 = st.columns(8)
    def stat_card(col, val, label, color="#00e5c3"):
        col.markdown(f"""<div class='db-stat-card'>
          <div class='db-stat-val' style='color:{color}'>{val}</div>
          <div class='db-stat-label'>{label}</div>
        </div>""", unsafe_allow_html=True)

    stat_card(s1, s["total"],    "Total Records")
    stat_card(s2, s["avg_score"],"Avg Score")
    stat_card(s3, s["critical"], "Critical", "#f43f5e")
    stat_card(s4, s["high"],     "High",     "#fb923c")
    stat_card(s5, s["medium"],   "Medium",   "#fbbf24")
    stat_card(s6, s["low"],      "Low",      "#00e5c3")
    stat_card(s7, s["scanner"],  "Scanner",  "#8b5cf6")
    stat_card(s8, s["mock"],     "Mock",     "#6b7499")

    st.markdown("---")
    st.markdown("<div class='section-header'>Filter Records</div>", unsafe_allow_html=True)
    fc1, fc2, fc3 = st.columns([1, 1, 1])
    with fc1: src_filter = st.multiselect("Source", ["scanner","mock","bulk_csv"], default=["scanner","mock","bulk_csv"], key="db_src")
    with fc2: lvl_filter = st.multiselect("Risk Level", ["CRITICAL","HIGH","MEDIUM","LOW"], default=["CRITICAL","HIGH","MEDIUM","LOW"], key="db_lvl")
    with fc3: row_limit = st.slider("Max rows to show", 10, 500, 100, step=10, key="db_limit")

    rows = load_transactions(source_filter=src_filter if src_filter else None, level_filter=lvl_filter if lvl_filter else None, limit=row_limit)
    st.markdown(f"<span style='color:#6b7499;font-size:0.88rem'>Showing <strong style='color:#dde4f0'>{len(rows)}</strong> records</span>", unsafe_allow_html=True)
    st.markdown("<div style='margin-top:10px'></div>", unsafe_allow_html=True)

    if rows:
        display_cols = ["id","txn_id","sender_name","source","timestamp","amount",
                        "customer_type","pep_status","sanctions_hit",
                        "billing_country","ip_country","final_score","risk_level","multiplier"]
        df = pd.DataFrame(rows)
        for col in display_cols:
            if col not in df.columns:
                df[col] = "—"
        df = df[display_cols]
        df.columns = ["ID","TXN ID","Name","Source","Time","Amount (₹)",
                      "Cust Type","PEP Status","Sanctions",
                      "Billing","IP","Score","Level","Multiplier"]
        df["Amount (₹)"] = pd.to_numeric(df["Amount (₹)"], errors="coerce").fillna(0).apply(lambda x: f"₹{x:,.0f}")
        st.dataframe(df, use_container_width=True, hide_index=True)

        st.markdown(f"""<div style='margin-top:16px;background:rgba(0,229,195,0.04);border:1px solid rgba(0,229,195,0.15);
            border-radius:10px;padding:14px 18px;font-family:Share Tech Mono;font-size:0.78rem;color:#6b7499'>
          📁 Database file: <span style='color:#00e5c3'>{DB_PATH.resolve()}</span><br>
          <span style='font-size:0.72rem;margin-top:4px;display:block'>
            Open with DB Browser for SQLite or any SQLite client to inspect raw data. The schema captures all 24 risk factors.
          </span>
        </div>""", unsafe_allow_html=True)
    else:
        st.info("No records match the current filters.")

# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 7 — ABOUT
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "About":
    st.markdown("# 📘 About CyberAML Shield")
    st.markdown("""### The Problem
CyberAML Shield unifies Cyber, AML, and full enterprise-grade compliance signals into a single graduated risk score with automatic multipliers when signal domains converge.

### 8 Signal Domains · 24 Risk Factors""")
    tiers=[
        ["Account Age","AML","< 7d → 20 · 1wk–1mo → 15 · 1–3mo → 10 · 3–6mo → 6 · 6–12mo → 3 · 1yr+ → 1"],
        ["Transaction Amount","AML","> ₹1L → 30 · > ₹50k → 25 · > ₹10k → 18 · > ₹5k → 8 · > ₹1k → 3 · < ₹1k → 1"],
        ["IP / Country Risk","CYBER","High-risk → 30 · Med-risk → 20 · Any mismatch → 12 · Match → 1"],
        ["Login Attempts","CYBER","> 10 → 25 · > 5 → 20 · > 3 → 15 · = 3 → 8 · = 2 → 4 · 1 → 1"],
        ["Transaction Hour","CYBER","1–4 AM → 15 · 0/5 AM → 10 · 10pm+ → 7 · 8pm → 4 · Business hrs → 1"],
        ["Txn Velocity","AML","> 10/day → 20 · > 5 → 14 · > 3 → 9 · 3 → 5 · 2 → 2 · 1 → 1"],
        ["Device Risk","CYBER","New + changes → 18 · New device → 12 · Multi-change → 8 · Known → 1"],
        ["Customer Type","DEMO","Shell/Holding → 22 · Trust → 18 · NGO → 14 · Private Co → 10 · Individual HNW → 8"],
        ["Industry / Occupation","DEMO","Crypto/Gambling/Arms/RE/MSB → 20 · Legal/Accy/IE/PMs → 10 · Standard → 2"],
        ["Source of Funds","DEMO","Unknown → 25 · Mixed/Complex → 18 · Loan → 12 · Inheritance → 10 · Business → 4"],
        ["PEP Status","DEMO","Foreign PEP → 28 · Domestic Senior → 22 · Former PEP → 15 · Associate → 18 · None → 1"],
        ["Customer Country","GEO","Sanctioned → 35 · High-risk → 22 · FATF Grey → 15 · Elevated → 8 · Standard → 1"],
        ["Destination Country","GEO","Sanctioned → 35 · High-risk → 20 · FATF Grey → 12 · Elevated → 6 · Standard → 1"],
        ["Structuring Pattern","BEHAV","Just-below-threshold × 6+ txns → 25 · × 3+ txns → 15 · None → 1"],
        ["Behavior Deviation","BEHAV","> 500% → 22 · > 200% → 15 · > 100% → 8 · > 50% → 4 · Normal → 1"],
        ["Round Number Risk","BEHAV","5+ trailing zeros → 12 · 4 zeros → 7 · 3 zeros → 3 · Normal → 1"],
        ["Account Type","PROD","Anon/Numbered → 30 · Crypto → 22 · Prepaid → 16 · Forex → 12 · Business → 6"],
        ["Payment Channel","PROD","Hawala → 30 · Crypto → 22 · Cash → 18 · 3rd-party → 16 · SWIFT → 14"],
        ["Ownership Complexity","NETW","5+ layers → 25 · 3+ layers → 15 · 2 layers → 8 · 1 layer → 3 · Direct → 1"],
        ["Linked Flagged Accounts","NETW","5+ linked → 25 · 3+ → 18 · 1+ → 10 · None → 1"],
        ["Counterparty Country","NETW","Sanctioned → 35 · High-risk → 18 · FATF Grey → 10 · Elevated → 5"],
        ["Sanctions Screening","SCRN","Full match → 40 · Entity match → 35 · Partial → 28 · Fuzzy → 15 · No hit → 1"],
        ["Adverse Media","SCRN","Terror/Prolif → 35 · Multi-confirmed → 28 · FinCrime → 22 · Minor → 8"],
        ["Law Enforcement","SCRN","Interpol → 35 · Local LE → 22 · Internal list → 15 · Prior SAR → 18"],
    ]
    st.dataframe(pd.DataFrame(tiers,columns=["Factor","Domain","Tiers (pts)"]),use_container_width=True,hide_index=True)
    st.markdown("""
### Multipliers
| Condition | Multiplier |
|---|---|
| 2+ SCRN compliance hits | ×1.50 |
| SCRN hit + geo/demo risk | ×1.40 |
| 3+ CYBER + 2+ AML | ×1.35 |
| 2+ GEO + profile/AML risk | ×1.30 |
| 3+ CYBER | ×1.23 |
| 2+ NETW signals | ×1.20 |
| 2+ AML | ×1.15 |
| 2+ DEMO signals | ×1.12 |
| 2 CYBER | ×1.10 |

### Risk Levels
| Level | Score | Action |
|---|---|---|
| 🟢 LOW | 0–19 | Standard processing |
| 🟡 MEDIUM | 20–44 | Enhanced monitoring |
| 🟠 HIGH | 45–69 | Manual review + KYC |
| 🔴 CRITICAL | 70+ | Block + escalate |

### Bulk CSV Scanner
Upload any CSV with transaction data — no fixed template required. The system auto-detects and maps columns using 24+ field aliases. Up to 10,000 rows scored in seconds. Gemini writes a board-level executive summary of the entire batch. Export flagged results back to CSV.

### Database
All transactions (mock, scanner, and bulk CSV) are persisted to `cyberaml.db` (SQLite) in the app directory.
Open with [DB Browser for SQLite](https://sqlitebrowser.org/) to inspect or export raw data.
""")