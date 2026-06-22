# 輔滿公開手機版

獨立 Streamlit 手機版，資料來源是 Supabase。

這個 repo 不放在原本 `fuman-terminal` Vercel 專案裡，避免主終端改版影響手機快訊。

## App Entry

Streamlit app file:

```text
streamlit_app.py
```

## Required Secrets

公開網站只需要讀資料，請使用 Supabase anon key，不要使用 service role key。

```toml
SUPABASE_URL = "https://jxnqyqnigsppqsxinlrq.supabase.co"
SUPABASE_ANON_KEY = "your anon public key"
```

## Local Run

```powershell
.\.venv\Scripts\streamlit.exe run streamlit_app.py --server.port 8502 --server.address 0.0.0.0
```

## Files

- `streamlit_app.py`: public deployment entry.
- `mobile_app.py`: mobile-first UI, night/sun modes.
- `supabase_client.py`: Supabase REST reader/writer.
- `supabase_schema.sql`: Supabase table and retention setup.
- `sync_to_supabase.py`: local sync script, use service role key only locally.
