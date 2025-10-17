# Setup 

## Installation Steps

### Step 1: Clone or Extract the Project

```bash
# If using git:
git clone <your-repo-url>
cd GoQuant

# Or if you have a ZIP file, extract it and navigate to the folder
cd GoQuant
```

### Step 2: Create a Virtual Environment

#### On Windows:
```bash
python -m venv venv
venv\Scripts\activate
```

#### On macOS/Linux:
```bash
python3 -m venv venv
source venv/bin/activate
```

You should see `(venv)` in your terminal prompt.

### Step 3: Upgrade pip

```bash
python -m pip install --upgrade pip
```

### Step 4: Install Dependencies

```bash
pip install -r requirements.txt
```

This will install all necessary packages. It should take 2-3 minutes.

### Step 5: Verify Installation

```bash
# Test imports
python -c "import fastapi; import uvicorn; import aiosqlite; print('All packages installed successfully!')"
```

If you see "All packages installed successfully!", you're good to go!

---

## Running the System

### Step 1: Start the Matching Engine Server

```bash
python main.py
```

**Expected Output:**
```
INFO:     Starting Crypto Matching Engine...
INFO:     Available trading pairs: BTC-USDT, ETH-USDT, SOL-USDT
INFO:     Starting recovery for BTC-USDT
INFO:     Recovery complete for BTC-USDT: 0 orders restored
INFO:     Starting recovery for ETH-USDT
INFO:     Recovery complete for ETH-USDT: 0 orders restored
INFO:     Starting recovery for SOL-USDT
INFO:     Recovery complete for SOL-USDT: 0 orders restored
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

**The server is now running!** Keep this terminal window open.

### Step 2: Open the Web Client

1. Open a **new browser window** (Chrome, Firefox, or Edge recommended)
2. Navigate to the `examples` folder in your project directory
3. **Double-click** `client.html` to open it in your browser

**Alternative:** Right-click `client.html` → "Open with" → Choose your browser

**Expected Result:**
- The page should load with the title "🚀 Crypto Matching Engine Client"
- Connection status should show "Connected" with a green indicator
- You should see three panels: Order Entry, Order Book, and Recent Trades

### Step 3: Verify Connection

In the **Messages** panel at the bottom, you should see:
```
[timestamp] Connected to matching engine
```

If you see "Disconnected" with a red indicator:
1. Make sure the server is running (`python main.py`)
2. Check that the server shows "Uvicorn running on http://0.0.0.0:8000"
3. Refresh the browser page

---

## Running Performance Benchmarks

### Benchmark: Concurrent Load Test

```bash
python examples/ws_benchmark_concurrent.py
```

**Expected Output:**
```
Starting 10 concurrent clients...
Client 0: 120 orders/sec
Client 1: 125 orders/sec
...
Total throughput: 1,250 orders/sec
```

---

## Quick Reference Commands

```bash
# Start server
python main.py

# Run tests
pytest tests/ -v

# Run benchmark
python examples/ws_benchmark.py

# Check server status
curl http://localhost:8000/

# Get order book
curl http://localhost:8000/orderbook/BTC-USDT

# Get performance metrics
curl http://localhost:8000/metrics
```