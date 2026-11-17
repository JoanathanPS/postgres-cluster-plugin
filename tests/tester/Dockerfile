# Minimal Linux "plugin runner": Python 3 + psycopg2-binary, the two
# prerequisites listed in the official postgres plugin README. It runs
# postgres.py the way the Site24x7 Linux agent does (CLI args per cfg section)
# and validates the JSON. It is a test harness, not the Site24x7 agent.
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY test_plugin.py .
# Runs as root on purpose: it is a throwaway test container and must be able to
# write its JSON reports into the ./test-output bind mount on Linux and Windows.

ENTRYPOINT ["python", "/app/test_plugin.py"]
