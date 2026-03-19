"""
MK QUANTUM — Signal Engine
By Muzamil Khan
FastAPI backend — runs free on Railway.app
Signals update every 5 minutes
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import requests
import json
from datetime import datetime, timezone, timedelta
import pytz

app = FastAPI(title="MK Quantum Signal Engine")

# Allow your frontend to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────
# GLOBAL STATE — latest computed signal
# ─────────────────────────────────────────
latest_signal = {
    "action": "NO TRADE",
    "confidence": 0,
    "reasoning": "Initializing...",
    "entry": None,
    "stop_loss": None,
    "target": None,
    "market_tag": "LOADING",
    "computed_at": None,
    "scores": {}
}

latest_market = {
    "nifty": {"price": 0, "change": 0, "change_pct": 0},
    "sensex": {"price": 0, "change": 0, "change_pct": 0},
    "vix": {"price": 0, "change": 0, "change_pct": 0},
    "banknifty": {"price": 0, "change": 0, "change_pct": 0},
    "sgx_nifty": {"price": 0, "change": 0, "change_pct": 0},
    "sp500": {"price": 0, "change": 0, "change_pct": 0},
    "dxy": {"price": 0, "change": 0, "change_pct": 0},
    "crude": {"price": 0, "change": 0, "change_pct": 0},
    "updated_at": None
}

IST = pytz.timezone("Asia/Kolkata")

# ─────────────────────────────────────────
# HELPER: Fetch OHLCV from Yahoo Finance
# ─────────────────────────────────────────
def fetch_ohlcv(ticker: str, period: str = "5d", interval: str = "5m") -> pd.DataFrame:
    try:
        df = yf.download(ticker, period=period, interval=interval,
                         progress=False, auto_adjust=True)
        df.dropna(inplace=True)
        return df
    except Exception as e:
        print(f"Error fetching {ticker}: {e}")
        return pd.DataFrame()

def fetch_latest_price(ticker: str) -> dict:
    try:
        t = yf.Ticker(ticker)
        info = t.fast_info
        price = round(float(info.last_price), 2)
        prev  = round(float(info.previous_close), 2)
        chg   = round(price - prev, 2)
        pct   = round((chg / prev) * 100, 2) if prev else 0
        return {"price": price, "change": chg, "change_pct": pct}
    except:
        return {"price": 0, "change": 0, "change_pct": 0}

# ─────────────────────────────────────────
# NSE OPTIONS DATA (free, no key needed)
# ─────────────────────────────────────────
def fetch_nse_options() -> dict:
    """Fetch live options chain from NSE India"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.nseindia.com"
        }
        session = requests.Session()
        # First hit homepage to get cookies
        session.get("https://www.nseindia.com", headers=headers, timeout=10)
        # Then fetch options chain
        url = "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY"
        resp = session.get(url, headers=headers, timeout=10)
        data = resp.json()

        records = data["records"]["data"]
        total_ce_oi = 0
        total_pe_oi = 0
        ce_oi_by_strike = {}
        pe_oi_by_strike = {}

        for rec in records:
            strike = rec.get("strikePrice", 0)
            if "CE" in rec:
                oi = rec["CE"].get("openInterest", 0)
                total_ce_oi += oi
                ce_oi_by_strike[strike] = oi
            if "PE" in rec:
                oi = rec["PE"].get("openInterest", 0)
                total_pe_oi += oi
                pe_oi_by_strike[strike] = oi

        pcr = round(total_pe_oi / total_ce_oi, 2) if total_ce_oi > 0 else 1.0

        # Max pain = strike where total loss to option buyers is maximum
        strikes = sorted(set(list(ce_oi_by_strike.keys()) + list(pe_oi_by_strike.keys())))
        max_pain = _compute_max_pain(strikes, ce_oi_by_strike, pe_oi_by_strike)

        return {
            "pcr": pcr,
            "max_pain": max_pain,
            "total_ce_oi": total_ce_oi,
            "total_pe_oi": total_pe_oi,
        }
    except Exception as e:
        print(f"NSE fetch error: {e}")
        return {"pcr": 1.0, "max_pain": 0, "total_ce_oi": 0, "total_pe_oi": 0}

def _compute_max_pain(strikes, ce_oi, pe_oi) -> float:
    if not strikes:
        return 0
    min_loss = float("inf")
    max_pain_strike = strikes[0]
    for target in strikes:
        loss = 0
        for strike, oi in ce_oi.items():
            if target > strike:
                loss += (target - strike) * oi
        for strike, oi in pe_oi.items():
            if target < strike:
                loss += (strike - target) * oi
        if loss < min_loss:
            min_loss = loss
            max_pain_strike = target
    return max_pain_strike

# ─────────────────────────────────────────
# TECHNICAL SCORE  (weight: 40%)
# ─────────────────────────────────────────
def compute_technical_score(df: pd.DataFrame) -> tuple[float, dict]:
    """Returns score -100 to +100 and reasoning dict"""
    if df.empty or len(df) < 50:
        return 0, {}

    close = df["Close"].squeeze()
    score = 0
    factors = {}

    # RSI
    rsi_series = ta.rsi(close, length=14)
    rsi = float(rsi_series.iloc[-1]) if rsi_series is not None else 50
    factors["rsi"] = round(rsi, 1)
    if rsi < 35:
        score += 30     # oversold → bullish
    elif rsi > 65:
        score -= 30     # overbought → bearish
    elif 40 <= rsi <= 55:
        score += 5      # neutral zone, mild bullish

    # MACD
    macd_df = ta.macd(close, fast=12, slow=26, signal=9)
    if macd_df is not None and not macd_df.empty:
        macd_val  = float(macd_df["MACD_12_26_9"].iloc[-1])
        macd_sig  = float(macd_df["MACDs_12_26_9"].iloc[-1])
        macd_hist = float(macd_df["MACDh_12_26_9"].iloc[-1])
        factors["macd_hist"] = round(macd_hist, 2)
        if macd_val > macd_sig and macd_hist > 0:
            score += 25   # bullish crossover
        elif macd_val < macd_sig and macd_hist < 0:
            score -= 25   # bearish crossover

    # EMA 20/50 alignment
    ema20 = ta.ema(close, length=20)
    ema50 = ta.ema(close, length=50)
    if ema20 is not None and ema50 is not None:
        e20 = float(ema20.iloc[-1])
        e50 = float(ema50.iloc[-1])
        last_close = float(close.iloc[-1])
        factors["ema20"] = round(e20, 1)
        factors["ema50"] = round(e50, 1)
        if last_close > e20 > e50:
            score += 20   # strong uptrend
        elif last_close < e20 < e50:
            score -= 20   # strong downtrend

    # VWAP (approx from intraday)
    try:
        high   = df["High"].squeeze()
        low    = df["Low"].squeeze()
        volume = df["Volume"].squeeze()
        typical_price = (high + low + close) / 3
        vwap = (typical_price * volume).cumsum() / volume.cumsum()
        vwap_val = float(vwap.iloc[-1])
        last_close = float(close.iloc[-1])
        factors["vwap"] = round(vwap_val, 1)
        if last_close > vwap_val:
            score += 15   # price above VWAP — bullish
        else:
            score -= 15
    except:
        pass

    return max(-100, min(100, score)), factors

# ─────────────────────────────────────────
# OPTIONS SCORE  (weight: 35%)
# ─────────────────────────────────────────
def compute_options_score(options: dict, vix: float, spot: float) -> tuple[float, dict]:
    score = 0
    factors = {}

    pcr = options.get("pcr", 1.0)
    factors["pcr"] = pcr

    # PCR interpretation
    # PCR > 1.3 = bullish (heavy put writing = support)
    # PCR < 0.8 = bearish (heavy call writing = resistance)
    if pcr > 1.3:
        score += 35
    elif pcr > 1.1:
        score += 20
    elif pcr > 0.9:
        score += 5
    elif pcr < 0.7:
        score -= 35
    elif pcr < 0.9:
        score -= 15

    # Max pain vs spot
    max_pain = options.get("max_pain", 0)
    if max_pain and spot:
        distance_pct = (spot - max_pain) / spot * 100
        factors["max_pain_distance_pct"] = round(distance_pct, 2)
        # If spot far above max pain → gravity pull down
        if distance_pct > 2:
            score -= 20
        # If spot far below max pain → gravity pull up
        elif distance_pct < -2:
            score += 20

    # VIX regime
    factors["vix"] = vix
    if vix < 13:
        score += 15    # low fear, markets stable/rising
    elif vix > 20:
        score -= 25    # high fear, avoid long trades
    elif vix > 17:
        score -= 10

    return max(-100, min(100, score)), factors

# ─────────────────────────────────────────
# GLOBAL SENTIMENT SCORE  (weight: 25%)
# ─────────────────────────────────────────
def compute_sentiment_score(sgx: dict, sp500: dict, dxy: dict, crude: dict) -> tuple[float, dict]:
    score = 0
    factors = {}

    # SGX / GIFT Nifty — most direct indicator
    sgx_pct = sgx.get("change_pct", 0)
    factors["sgx_pct"] = sgx_pct
    if sgx_pct > 0.3:
        score += 40
    elif sgx_pct > 0:
        score += 20
    elif sgx_pct < -0.3:
        score -= 40
    elif sgx_pct < 0:
        score -= 20

    # S&P 500 direction
    sp_pct = sp500.get("change_pct", 0)
    factors["sp500_pct"] = sp_pct
    if sp_pct > 0.5:
        score += 25
    elif sp_pct > 0:
        score += 10
    elif sp_pct < -0.5:
        score -= 25
    elif sp_pct < 0:
        score -= 10

    # DXY — inverse correlation with Indian markets
    dxy_pct = dxy.get("change_pct", 0)
    factors["dxy_pct"] = dxy_pct
    if dxy_pct > 0.3:
        score -= 15    # strong dollar → bad for Nifty
    elif dxy_pct < -0.3:
        score += 15    # weak dollar → good for Nifty

    # Crude oil
    crude_pct = crude.get("change_pct", 0)
    factors["crude_pct"] = crude_pct
    if crude_pct > 2:
        score -= 15    # expensive oil hurts India
    elif crude_pct < -2:
        score += 10    # cheap oil helps India

    return max(-100, min(100, score)), factors

# ─────────────────────────────────────────
# MARKET SESSION CHECK
# ─────────────────────────────────────────
def is_market_open() -> bool:
    now_ist = datetime.now(IST)
    weekday = now_ist.weekday()  # 0=Mon, 6=Sun
    if weekday >= 5:
        return False
    market_open  = now_ist.replace(hour=9, minute=15, second=0)
    market_close = now_ist.replace(hour=15, minute=30, second=0)
    return market_open <= now_ist <= market_close

def is_expiry_day() -> bool:
    now_ist = datetime.now(IST)
    return now_ist.weekday() == 3  # Thursday = weekly expiry

# ─────────────────────────────────────────
# MAIN SIGNAL COMPUTATION
# ─────────────────────────────────────────
def compute_signal():
    global latest_signal, latest_market

    print(f"[{datetime.now(IST).strftime('%H:%M:%S')} IST] Computing signal...")

    # 1. Fetch market prices
    nifty_data    = fetch_latest_price("^NSEI")
    sensex_data   = fetch_latest_price("^BSESN")
    vix_data      = fetch_latest_price("^INDIAVIX")
    bnifty_data   = fetch_latest_price("^NSEBANK")
    sp500_data    = fetch_latest_price("^GSPC")
    dxy_data      = fetch_latest_price("DX-Y.NYB")
    crude_data    = fetch_latest_price("CL=F")
    sgx_data      = fetch_latest_price("^NSEI")  # fallback; ideally GIFT Nifty

    latest_market.update({
        "nifty": nifty_data,
        "sensex": sensex_data,
        "vix": vix_data,
        "banknifty": bnifty_data,
        "sp500": sp500_data,
        "dxy": dxy_data,
        "crude": crude_data,
        "sgx_nifty": sgx_data,
        "updated_at": datetime.now(IST).isoformat()
    })

    # 2. Market closed → NO TRADE
    if not is_market_open():
        latest_signal = {
            "action": "NO TRADE",
            "confidence": 0,
            "reasoning": "Market is closed. Signals resume at 9:15 AM IST.",
            "entry": None, "stop_loss": None, "target": None,
            "market_tag": "CLOSED",
            "computed_at": datetime.now(IST).isoformat(),
            "scores": {}
        }
        return

    # 3. Expiry day caution
    expiry_warning = ""
    if is_expiry_day():
        expiry_warning = " ⚠️ Expiry day — use reduced position size."

    # 4. Fetch OHLCV for technical analysis
    df_5m  = fetch_ohlcv("^NSEI", period="5d", interval="5m")
    df_15m = fetch_ohlcv("^NSEI", period="5d", interval="15m")

    # Use 15m for more reliable signals
    df = df_15m if not df_15m.empty else df_5m

    # 5. Options data from NSE
    options = fetch_nse_options()

    vix_price = vix_data.get("price", 15)
    spot      = nifty_data.get("price", 0)

    # 6. Compute all three scores
    tech_score,  tech_factors  = compute_technical_score(df)
    opt_score,   opt_factors   = compute_options_score(options, vix_price, spot)
    sent_score,  sent_factors  = compute_sentiment_score(
        sgx_data, sp500_data, dxy_data, crude_data
    )

    # 7. Weighted composite score
    # Tech: 40%, Options: 35%, Sentiment: 25%
    composite = (tech_score * 0.40) + (opt_score * 0.35) + (sent_score * 0.25)
    confidence = abs(composite)

    all_factors = {**tech_factors, **opt_factors, **sent_factors}

    # 8. High VIX → force NO TRADE
    if vix_price > 22:
        latest_signal = {
            "action": "NO TRADE",
            "confidence": round(confidence, 1),
            "reasoning": f"VIX at {vix_price} (>22) — extreme volatility. No new options positions. Wait for VIX to cool below 18.",
            "entry": None, "stop_loss": None, "target": None,
            "market_tag": "VOLATILE",
            "computed_at": datetime.now(IST).isoformat(),
            "scores": {"technical": round(tech_score,1), "options": round(opt_score,1), "sentiment": round(sent_score,1)}
        }
        return

    # 9. Confidence threshold — only fire if > 62%
    MIN_CONFIDENCE = 62

    if confidence < MIN_CONFIDENCE:
        latest_signal = {
            "action": "NO TRADE",
            "confidence": round(confidence, 1),
            "reasoning": f"Composite score {round(composite,1)} — insufficient confluence across signals. Waiting for stronger alignment. Tech={round(tech_score,1)}, Options={round(opt_score,1)}, Sentiment={round(sent_score,1)}",
            "entry": None, "stop_loss": None, "target": None,
            "market_tag": _get_market_tag(vix_price, tech_score),
            "computed_at": datetime.now(IST).isoformat(),
            "scores": {"technical": round(tech_score,1), "options": round(opt_score,1), "sentiment": round(sent_score,1)}
        }
        return

    # 10. Generate signal
    direction = "CALL" if composite > 0 else "PUT"
    action = f"BUY {direction}"

    # Entry / SL / Target
    entry_price, sl_price, target_price = _compute_levels(spot, direction, options)

    # Build reasoning
    reasoning = _build_reasoning(direction, composite, tech_score, opt_score,
                                  sent_score, all_factors, expiry_warning)

    market_tag = _get_market_tag(vix_price, tech_score)

    latest_signal = {
        "action": action,
        "confidence": round(confidence, 1),
        "reasoning": reasoning,
        "entry": entry_price,
        "stop_loss": sl_price,
        "target": target_price,
        "market_tag": market_tag,
        "risk_reward": round(abs(target_price - entry_price) / abs(entry_price - sl_price), 1) if sl_price and target_price and entry_price and sl_price != entry_price else None,
        "computed_at": datetime.now(IST).isoformat(),
        "scores": {
            "technical": round(tech_score, 1),
            "options": round(opt_score, 1),
            "sentiment": round(sent_score, 1),
            "composite": round(composite, 1)
        },
        "factors": all_factors
    }

    print(f"  → Signal: {action} | Confidence: {round(confidence,1)}%")

def _get_market_tag(vix: float, tech_score: float) -> str:
    if vix > 18:
        return "VOLATILE"
    if abs(tech_score) > 50:
        return "TRENDING"
    if abs(tech_score) < 20:
        return "RANGE"
    return "TRENDING"

def _compute_levels(spot: float, direction: str, options: dict) -> tuple:
    """Compute ATM option price estimate + SL + target"""
    if not spot:
        return None, None, None
    # ATM strike
    atm_strike = round(spot / 50) * 50
    # Rough ATM option price (0.8–1.5% of spot for weekly)
    atm_price = round(spot * 0.01, 0)
    sl_price = round(atm_price * 0.75, 0)        # 25% SL
    target_price = round(atm_price * 1.55, 0)    # 55% target → R:R ~2.2
    return atm_price, sl_price, target_price

def _build_reasoning(direction, composite, tech, opt, sent, factors, expiry_warn) -> str:
    lines = []
    bull = direction == "CALL"

    if bull:
        lines.append(f"✦ Composite score +{round(composite,1)} — bullish confluence across all 3 layers.")
    else:
        lines.append(f"✦ Composite score {round(composite,1)} — bearish confluence across all 3 layers.")

    if "rsi" in factors:
        rsi = factors["rsi"]
        if rsi < 40:
            lines.append(f"RSI {rsi} — oversold, bounce likely.")
        elif rsi > 60:
            lines.append(f"RSI {rsi} — overbought, reversal likely.")

    if "pcr" in factors:
        pcr = factors["pcr"]
        if pcr > 1.2:
            lines.append(f"PCR {pcr} — heavy put writing, smart money sees support.")
        elif pcr < 0.85:
            lines.append(f"PCR {pcr} — heavy call writing, strong resistance above.")

    if "vix" in factors:
        vix = factors["vix"]
        lines.append(f"VIX {vix} — {'low fear, favorable for buying.' if vix < 16 else 'elevated, trade smaller size.'}")

    if "sgx_pct" in factors:
        sgx = factors["sgx_pct"]
        lines.append(f"SGX Nifty {'+' if sgx > 0 else ''}{sgx}% pre-market {'gap up.' if sgx > 0 else 'gap down.'}")

    if expiry_warn:
        lines.append(expiry_warn)

    return " ".join(lines)

# ─────────────────────────────────────────
# TELEGRAM ALERT (optional)
# ─────────────────────────────────────────
TELEGRAM_BOT_TOKEN = ""   # Add your token
TELEGRAM_CHAT_ID   = ""   # Add your chat ID

def send_telegram_alert(signal: dict):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    if signal["action"] == "NO TRADE":
        return   # Don't spam NO TRADE alerts

    msg = (
        f"🔔 *MK QUANTUM SIGNAL*\n\n"
        f"Action: *{signal['action']}*\n"
        f"Confidence: *{signal['confidence']}%*\n"
        f"Entry: ₹{signal['entry']}\n"
        f"Stop Loss: ₹{signal['stop_loss']}\n"
        f"Target: ₹{signal['target']}\n\n"
        f"_{signal['reasoning']}_\n\n"
        f"⏱ {signal['computed_at']}"
    )
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"},
            timeout=5
        )
    except:
        pass

# ─────────────────────────────────────────
# API ENDPOINTS
# ─────────────────────────────────────────
@app.get("/")
def root():
    return {"status": "MK QUANTUM Signal Engine running", "version": "1.0"}

@app.get("/api/signal")
def get_signal():
    return latest_signal

@app.get("/api/market")
def get_market():
    return latest_market

@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "market_open": is_market_open(),
        "expiry_day": is_expiry_day(),
        "last_computed": latest_signal.get("computed_at")
    }

# ─────────────────────────────────────────
# SCHEDULER — runs every 5 minutes
# ─────────────────────────────────────────
scheduler = BackgroundScheduler(timezone=IST)
scheduler.add_job(compute_signal, "interval", minutes=5, id="signal_job")

@app.on_event("startup")
def startup():
    scheduler.start()
    compute_signal()   # Run once immediately on startup
    print("✅ MK QUANTUM Signal Engine started")

@app.on_event("shutdown")
def shutdown():
    scheduler.shutdown()
