import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def client(base_url=None, api_key=None):
    return OpenAI(
        base_url=base_url or os.environ.get("BASETEN_BASE_URL", "https://inference.baseten.co/v1"),
        api_key=api_key or os.environ.get("BASETEN_API_KEY", ""),
    )


def system_prompt():
    return (ROOT / "prompts" / "system.txt").read_text().strip()
