import json
from pathlib import Path

import pytest

from docsrag.config import settings
from docsrag.generate import generate_answer
from docsrag.llm import get_client


GOLDEN = json.loads((Path(__file__).parent / "golden_qa.json").read_text())

def judge(question: str, expected: str, actual: str) -> tuple[bool, str]:
  """Ask the LLM whether `actual` is consistent with `expected`. Returns (passed, verdict)."""
  prompt = (
    f"You are evaluating a documentation assistant's answer.\n\n"
    f"Question: {question}\n\n"
    f"Reference answer: {expected}\n\n"
    f"Assistant's answer: {actual}\n\n"
    f"Grade the assistant's answer. Respond PASS if it is factually consistent "
    f"with the reference — i.e. it states the same core technique correctly — even "
    f"if it uses different wording, adds extra detail, or omits code examples. "
    f"Respond FAIL only if it contradicts the reference, is missing the key point, "
    f"or is factually wrong.\n\n"
    f"Respond with exactly PASS or FAIL as the first word, optionally followed by a brief reason."
  )
  response = get_client().chat.completions.create(
    model=settings.llm_model,
    messages=[{"role": "user", "content": prompt}],
    temperature = 0.0,
  )
  verdict = response.choices[0].message.content.strip()
  passed = verdict.upper().startswith("PASS")
  return passed, verdict

@pytest.mark.parametrize("case", GOLDEN, ids=[c["question"] for c in GOLDEN])
def test_answer_is_correct(case):
  answer, _ = generate_answer(case["question"])
  passed, verdict = judge(case["question"], case["expected"], answer)
  assert passed, (
    f"\nQ: {case['question']}"
    f"\nExpected: {case['expected']}"
    f"\nGot: {answer}"
    f"\nVerdict: {verdict}"
  )