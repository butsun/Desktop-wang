# StockFloat

StockFloat is a local desktop floating watchlist for A-share quotes.

The first MVP is intentionally small:

- PySide6 desktop UI
- Eastmoney watchlist quote source
- local JSON configuration
- floating translucent always-on-top window
- system tray show/hide entry
- hover-to-expand quote card
- in-app watchlist, opacity, pin, collapse-delay, and Cookie settings
- background quote refresh with stale-data fallback

## Development

Create a Python 3.11 virtual environment:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

If downloads are slow in China, use a mirror:

```bash
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

If Eastmoney rejects anonymous quote requests, open the quote page in Chrome and copy the
request `Cookie` header into the settings window, or into an environment variable before
starting the app:

```bash
export STOCKFLOAT_EASTMONEY_COOKIE='qgqp_b_id=...; st_si=...'
python -m app.main
```

The settings window also includes buttons to open the Eastmoney quote page and test the
current Cookie against the watchlist quote API.

Run on macOS or Windows:

```bash
python -m app.main
```

On Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app.main
```

## Configuration

On first launch, StockFloat creates user config files under:

- macOS: `~/Library/Application Support/StockFloat/`
- Windows: `%APPDATA%\StockFloat\`

Example `stocks.json`:

```json
{
  "stocks": ["000001", "600519", "300750"]
}
```

Example `settings.json`:

```json
{
  "refresh_interval_seconds": 10,
  "opacity": 0.88,
  "always_on_top": true,
  "window": {
    "x": 80,
    "y": 80,
    "width": 460,
    "height": 320
  }
}
```

## Windows Build

Build the final exe on Windows:

```powershell
pip install -r requirements-dev.txt
pyinstaller stockfloat.spec
```

The generated executable will be in `dist/`.
