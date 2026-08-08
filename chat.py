import argparse
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv

load_dotenv()

from knowledge_base import build_knowledge_base, retrieve

SYSTEM_PROMPT = (
    "You are a Fantasy Premier League assistant for a single manager's own tool. "
    "Answer using ONLY the context provided below, which comes from this "
    "project's own expected-points model, captaincy engine, and squad "
    "optimizer -- not general football knowledge. If the context doesn't "
    "contain enough information to answer confidently, say so rather than "
    "guessing. Be concise and specific: cite actual player names, prices, "
    "and projected points from the context."
)

DEFAULT_MODEL = "claude-haiku-4-5-20251001"


def ask(question: str, docs: list[dict], gw: int, client, model: str) -> str:
    relevant = retrieve(question, docs)
    context = "\n\n".join(d["text"] for d in relevant)

    message = client.messages.create(
        model=model,
        max_tokens=500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"Context (Gameweek {gw}):\n{context}\n\nQuestion: {question}"}],
    )
    return message.content[0].text


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask natural-language questions about your FPL data (RAG over this project's own computed data).")
    parser.add_argument("question", nargs="*", help="Your question. If omitted, starts an interactive prompt.")
    parser.add_argument("--model", type=str, default=os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL), help="Anthropic model to use.")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ANTHROPIC_API_KEY is not set. Get a key from console.anthropic.com and set it as an environment variable (or in a local .env file, see .env.example).")
        return

    from anthropic import Anthropic

    client = Anthropic(api_key=api_key)

    print("Loading this gameweek's data...")
    docs, gw = build_knowledge_base()
    print(f"Ready (GW{gw}, {len(docs)} documents indexed).\n")

    if args.question:
        question = " ".join(args.question)
        print(ask(question, docs, gw, client, args.model))
        return

    print("Ask a question (empty line to quit):")
    while True:
        try:
            question = input("> ").strip()
        except EOFError:
            break
        if not question:
            break
        print(ask(question, docs, gw, client, args.model))
        print()


if __name__ == "__main__":
    main()
