import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv

load_dotenv()

from chat import DEFAULT_MODEL, ask
from knowledge_base import build_knowledge_base


def main() -> None:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY is not set. Get a free key from aistudio.google.com/apikey and put it in .env.")
        return

    import gradio as gr
    from google import genai

    client = genai.Client(api_key=api_key)

    print("Loading this gameweek's data...")
    docs, gw = build_knowledge_base()
    print(f"Ready (GW{gw}, {len(docs)} documents indexed). Starting web UI...")

    def respond(message: str, history: list) -> str:
        return ask(message, docs, gw, client, DEFAULT_MODEL)

    demo = gr.ChatInterface(
        respond,
        title="FPL AI Assistant",
        description=f"Ask about Gameweek {gw}. Answers are grounded only in this project's own computed data.",
        examples=["Who should I captain this week?", "Best defenders under £6m", "Is Haaland worth it?"],
    )
    demo.launch()


if __name__ == "__main__":
    main()
