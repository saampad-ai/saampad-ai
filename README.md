# AskAnujSir Practise — Computer Science study companion

Streamlit app: syllabus-restricted chat, PYQ practice (MCQ / Assertion-Reason quiz), smart-practice agent, code sandbox, teacher tools.

## Run
```bash
pip install -e .
export API_KEY_GROQ_ANUJ="..."      # default provider (model: openai/gpt-oss-20b)
export API_KEY_GEMINI_ANUJ="..."    # optional (model: gemini-3.1-flash-lite)
streamlit run Practise.py
```
(Windows PowerShell: `$env:API_KEY_GROQ_ANUJ="..."`.) A `.env` file also works.

Set `DATABASE_URL` to the Neon Postgres connection and configure `AWS_ENDPOINT_URL_S3`,
`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, and `AWS_BUCKET_NAME` for
Neon Object Storage. The configured bucket must exist and credentials need read/write
access. Runtime question/session data lives in Postgres; PDFs, other uploads, and the
trained classifier artifact live in Object Storage. The local seed files were removed
after the successful migration; the app reads runtime data from Neon.

Chat and quiz progress are saved in Neon under anonymous session IDs carried in the page
URL. This lets the same session resume after a refresh or when reopening the same link.
There are no user accounts yet: anyone with the session link can read its chat, so don't
share it or enter sensitive personal information. Use **Delete this conversation** to
remove its saved chat messages; quiz progress is stored separately.

Code execution is disabled until the separate executor service is deployed and
`CODE_EXECUTOR_URL` plus `CODE_EXECUTOR_TOKEN` are configured. The Streamlit process never
executes student code directly. The executor in `execution_service/` starts a disposable
Docker container for each run with no network, a read-only root filesystem, a non-root
user, CPU/memory/process limits, a short timeout, and capped output.

### Running the code executor

Use a dedicated Linux host for the executor and its Docker daemon. The executor needs
access to the Docker socket, which grants control of that host's daemon; never mount that
socket into the Streamlit app or expose the executor directly to the public internet.
Build the runner image and API image from the repository root:

```bash
docker build -f execution_service/runner.Dockerfile -t practise-python-runner:1 execution_service
docker build -f execution_service/Dockerfile -t practise-code-executor:1 execution_service
```

Run the API bound to loopback for local development, with a random token of at least 32
characters and the Docker socket mounted:

```bash
export CODE_EXECUTOR_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
docker run --rm --name practise-code-executor \
  -e CODE_EXECUTOR_TOKEN="$CODE_EXECUTOR_TOKEN" \
  -e CODE_RUNNER_IMAGE=practise-python-runner:1 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -p 127.0.0.1:8080:8080 practise-code-executor:1
```

For production, terminate HTTPS at a trusted reverse proxy, require the bearer token,
restrict ingress to the app, and keep the executor host separate from the database and
application hosts. Configure the app's `CODE_EXECUTOR_URL` to the HTTPS `/execute`
endpoint and set the same token in `CODE_EXECUTOR_TOKEN`. The runner image must be
prebuilt on the executor host; jobs use `--pull=never` and cannot access the network.
The executor also caps concurrent work and requests per anonymous session. Docker
containers still share the host kernel, so use a stronger runtime such as gVisor or Kata
Containers for higher-risk public workloads, and keep the execution host disposable. The
included service runs one API worker; its rate counters are process-local. Use a shared
rate limiter before running multiple service replicas.

## AI configuration
No API selection on the main page. Open **Settings** to change provider/model and configure an API key. Default is **groq**; keys are read from the environment variables above. Defaults are defined in `src/backend/ai_config.py`.

## Uploads
Upload a past-year paper or syllabus PDF, then explicitly select the active syllabus. It must be a readable Computer Science syllabus covering both Class 11 and Class 12. Papers can be converted to questions (AI extraction → review table → save). Other documents, images, and files can also be stored in the bucket.

## Folders
```
Practise.py            <- Streamlit entry point
pages/                 <- Streamlit multipage screens
src/backend/        <- application package and business logic
train_classifier.py    <- classifier training command
logo.png                 <- sidebar, chat avatar, and browser tab logo
```
After adding many questions run `python train_classifier.py` to retrain the topic classifier.

## PYQ's Practice
* **MCQ & Assertion-Reason Quiz**: ~10 questions per round, one option per line, Assertion and Reason on separate lines, Python code in a Consolas/Courier New block. Submit any time (unanswered allowed); results show correct/wrong, the answer key and an optional "Explain with AI".
* **Single question**: any question type, exact PYQ or AI-generated.
* Code in questions stored on one line is re-indented automatically (best effort). For best formatting, store code with real line breaks in the question text.
