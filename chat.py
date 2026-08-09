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

# Free-tier quota varies wildly by model and isn't documented anywhere obvious --
# gemini-flash-latest resolved to gemini-3.6-flash, which turned out to have a
# 20-requests/day free cap. The "-lite" tier of the same generation has a much
# higher quota and, as a bonus, doesn't seem to use "thinking" tokens for
# straightforward lookups like this, so it's less prone to the truncation
# issue too. If this changes again, check the actual model name in any 429
# error message -- it's often not the one you asked for.
DEFAULT_MODEL = "gemini-3.5-flash-lite"


def ask(question: str, docs: list[dict], gw: int, client, model: str) -> str:
    from google.genai import types

    relevant = retrieve(question, docs)
    context = "\n\n".join(d["text"] for d in relevant)

    response = client.models.generate_content(
        model=model,
        contents=f"Context (Gameweek {gw}):\n{context}\n\nQuestion: {question}",
        # This model's "thinking" tokens count against max_output_tokens and scale
        # with question complexity -- ~1100 for a single-position lookup, ~2500+
        # for a full starting-XI question. thinking_budget biases it toward less
        # (not a hard cap in practice), and max_output_tokens is the real backstop
        # sized well above the worst case observed during testing.
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            max_output_tokens=4096,
            thinking_config=types.ThinkingConfig(thinking_budget=1024),
        ),
    )
    if response.candidates[0].finish_reason.name == "MAX_TOKENS" and not response.text:
        return "(Response was cut off by the token budget before any answer was produced. Try a shorter question.)"
    return response.text


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask natural-language questions about your FPL data (RAG over this project's own computed data).")
    parser.add_argument("question", nargs="*", help="Your question. If omitted, starts an interactive prompt.")
    parser.add_argument("--model", type=str, default=os.environ.get("GEMINI_MODEL", DEFAULT_MODEL), help="Gemini model to use.")
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY is not set. Get a free key from aistudio.google.com/apikey and set it as an environment variable (or in a local .env file, see .env.example).")
        return

    from google import genai

    client = genai.Client(api_key=api_key)

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
