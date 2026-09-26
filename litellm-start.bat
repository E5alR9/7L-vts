@echo off
REM LiteLLM proxy - 34 keys load-balanced, OpenAI-compatible on :4000
cd /d "%~dp0"
litellm --config litellm-config.yaml --port 4000 --host 127.0.0.1
pause
