# MK QUANTUM — Deployment Guide
## By Muzamil Khan

---

## STEP 1 — Deploy Backend FREE on Railway

1. Go to **railway.app** and sign up (free, use GitHub login)

2. Click **"New Project"** → **"Deploy from GitHub repo"**
   OR click **"Deploy from template"** → choose **"Empty project"**

3. Click **"Add Service"** → **"GitHub Repo"**
   - Upload this folder to a new GitHub repo called `mk-quantum-backend`
   - Connect it in Railway

4. Railway auto-detects Python and installs requirements.txt

5. Go to your service → **"Settings"** → **"Generate Domain"**
   You get a URL like: `https://mk-quantum-backend-production.up.railway.app`

6. **Copy that URL** — you need it in Step 3

---

## STEP 2 — Set Up Telegram Alerts (Optional but Recommended)

1. Open Telegram → search for **@BotFather**
2. Send: `/newbot`
3. Name it: `MK Quantum Signals`
4. Username: `mk_quantum_bot` (or any available name)
5. BotFather gives you a **token** — copy it

6. Search for **@userinfobot** on Telegram
7. Send any message to it — it gives you your **Chat ID**

8. In `main.py`, fill in:
   ```python
   TELEGRAM_BOT_TOKEN = "YOUR_TOKEN_HERE"
   TELEGRAM_CHAT_ID   = "YOUR_CHAT_ID_HERE"
   ```

9. Push to GitHub → Railway auto-redeploys

---

## STEP 3 — Connect Frontend to Backend

1. Open `index.html` in your code editor
2. Find line:
   ```javascript
   const API_BASE = 'https://YOUR-RAILWAY-URL.up.railway.app';
   ```
3. Replace with your actual Railway URL from Step 1

4. Save the file

---

## STEP 4 — Host Frontend FREE on Netlify

1. Go to **app.netlify.com**
2. Click **"Add new site"** → **"Deploy manually"**
3. Drag and drop your `index.html` file
4. Netlify gives you a link like: `https://mk-quantum.netlify.app`
5. Share this link with friends!

---

## STEP 5 — Install on Your Phone

### Android:
1. Open your Netlify link in Chrome
2. Tap 3-dot menu → "Add to Home Screen"
3. Name it "MK Quantum" → Add

### iPhone:
1. Open your Netlify link in Safari
2. Tap Share button (square with arrow)
3. "Add to Home Screen" → Add

---

## How Signals Work

The backend runs 24/7 on Railway (free tier).
Every 5 minutes it:
1. Fetches live NIFTY data from Yahoo Finance
2. Fetches NSE options chain (PCR, OI, Max Pain)
3. Computes Technical Score (RSI + MACD + EMA + VWAP)
4. Computes Options Score (PCR + Max Pain + VIX)
5. Computes Sentiment Score (SGX + S&P500 + DXY + Crude)
6. Outputs: BUY CALL / BUY PUT / NO TRADE with confidence %

Signal only fires if confidence > 62%.
VIX > 22 → forced NO TRADE (too dangerous).

Your app fetches the latest signal every 5 minutes.

---

## Free Tier Limits

| Service  | Free Limit         | What Happens After |
|----------|--------------------|--------------------|
| Railway  | $5 credit/month    | Service sleeps     |
| Netlify  | 100GB bandwidth    | More than enough   |
| Yahoo Finance | Unlimited     | Always free        |
| NSE API  | Unlimited          | Always free        |
| Telegram Bot | Unlimited     | Always free        |

Railway's $5 credit is enough for ~500 hours/month.
Your signal engine runs ~300 hours/month (market hours only).
**You will not exceed the free tier.**

---

## Questions?
Built by Muzamil Khan using Claude AI.
