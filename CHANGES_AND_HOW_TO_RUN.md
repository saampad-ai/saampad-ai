# Practise: local run and resolved issues

## Run locally (Windows PowerShell)

1. From the repository root, create and activate a Python 3.11 environment:

   ```powershell
   py -3.11 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   pip install -e .
   ```

2. If you do not already have a local `.env`, copy the template and fill in the credentials:

   ```powershell
   Copy-Item .env.example .env
   ```

   `DATABASE_URL`, `AWS_ENDPOINT_URL_S3`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
   `AWS_REGION`, and `AWS_BUCKET_NAME` are required for Neon database and object storage.
   Set an AI provider key such as `API_KEY_GROQ_ANUJ` to enable AI features. Never commit
   `.env` or real credentials.

3. Start the app:

   ```powershell
   streamlit run Practise.py
   ```

   The browser opens the Practise home page. To use the Code Sandbox, separately deploy
   the Docker-based executor described in `README.md`, then configure
   `CODE_EXECUTOR_URL` and `CODE_EXECUTOR_TOKEN`. Code execution stays disabled without it.

## Earlier issues and how they were resolved

- **Cluttered project root** — Application modules were moved into `src/backend/`;
  Streamlit pages remain in `pages/`. The root entry point is `Practise.py`.
- **Wrong syllabus selected based on file modification time** — Syllabus PDFs are stored
  in object storage. A user selects the active syllabus in **Uploads**, and the app checks
  the PDF before activating it. The app no longer picks the newest local PDF automatically.
- **Unsafe in-process execution of submitted Python** — The app no longer uses `exec` to
  run student code. It sends code to a separately deployed executor, which starts a
  disposable Docker container with no network, a read-only root filesystem, a non-root
  user, and CPU, memory, process, time, and output limits. Execution remains disabled
  unless the executor URL and token are configured.
- **Question-bank writes could lose updates or count duplicates incorrectly** — Question
  rows are validated and saved to Postgres inside database transactions. A unique database
  constraint on question text and `ON CONFLICT DO NOTHING` handle duplicate writes safely.
- **Uploads could overwrite objects and had no configured size cap** — Uploads receive
  generated unique object keys. Streamlit's configured upload limit is 20 MB.
- **Chat and quiz history disappeared when a browser session ended** — Chat messages and
  quiz attempts are persisted in Neon Postgres and reloaded using an anonymous UUID session
  identifier.
- **Runtime data depended on local files** — Question and session records use Neon
  Postgres. Uploaded documents and the classifier artifact use Neon Object Storage.
- **UI text and errors were hard to read or exposed implementation details** — A shared
  dark theme sets the page, sidebar, text, input, and button colors. User-facing failure
  messages are generic while detailed diagnostics go to server logs.
- **Settings and uploads shared one screen** — AI provider, model, and API key controls
  are on **Settings**; file management is on **Uploads**.
- **Old Saampad AI product branding** — User-facing copy, AI persona, and package
  metadata now use `AskAnujSir`. The Python import package remains named `backend`.
- **The sidebar displayed the generic name `app`** — The Streamlit entry point was renamed
  to `Practise.py`, which gives the default navigation item the product name.

## Remaining deployment considerations

- **GitHub organization OAuth approval is a deployment prerequisite, not a code fix.**
  The GitHub organization is still named `saampad-ai`; its owner must approve
  Streamlit's OAuth app in the organization settings. Approve Streamlit specifically
  if possible; disabling the
  organization's OAuth restrictions grants broader access.
- Sessions are anonymous and identified through IDs in the page URL. Anyone who has a
  session link can access that session; there is no account-based authentication yet.
  Avoid entering sensitive personal information or sharing session links.
- The Docker executor is a separate service and is not started by Streamlit Community
  Cloud. Docker containers share the host kernel; isolate the executor host from the app
  and database. See `README.md` for its deployment requirements.
- The app requires valid Neon database and object-storage credentials at startup; it does
  not fall back to local storage.
- Input validation and container resource limits reduce execution risk but do not
  guarantee complete isolation. Higher-risk public execution may need a stronger runtime
  such as gVisor or Kata Containers.
