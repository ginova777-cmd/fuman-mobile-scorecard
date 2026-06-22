# 輔滿公開手機版

這個資料夾可以獨立部署成一個公開手機版網站，不需要 Vercel，也不需要放進 `fuman-terminal` 專案。

公開網站入口只用一個網址，部署時指定：

```text
streamlit_app.py
```

打開該公開網址時，看到的就是手機快速版。

## 部署環境變數

公開網站只需要讀資料，建議使用 Supabase anon key，不要使用 service role key。

```text
SUPABASE_URL=https://jxnqyqnigsppqsxinlrq.supabase.co
SUPABASE_ANON_KEY=你的 anon public key
```

service role key 只留給本機同步腳本 `sync_to_supabase.py` 使用。

## Render 部署

這個資料夾已附 `render.yaml`。Render 建立 Web Service 後會使用：

```text
streamlit run streamlit_app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true
```

## Streamlit Community Cloud 部署

如果使用 Streamlit Community Cloud：

1. App file 選 `streamlit_app.py`
2. Python requirements 使用 `requirements.txt`
3. Secrets 加：

```toml
SUPABASE_URL = "https://jxnqyqnigsppqsxinlrq.supabase.co"
SUPABASE_ANON_KEY = "你的 anon public key"
```

## 本機測試

```powershell
cd C:\Users\ginov\Documents\Codex\2026-06-22\new-chat-7\outputs\backtest-scorecard
.\.venv\Scripts\streamlit.exe run streamlit_app.py --server.port 8502 --server.address 0.0.0.0
```

瀏覽器開：

```text
http://localhost:8502
```
