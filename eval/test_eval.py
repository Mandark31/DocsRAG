import json
from pathlib import Path

from docsrag.generate import generate_answer
from docsrag.llm import chat


GOLDEN = json.loads((Path(__file__).parent / "golden_qa.json").read_text())
ACCURACY_THRESHOLD = 0.9  # fail the suite only if overall accuracy drops below this

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

  response = chat(
    [{"role": "user", "content": prompt}],
    temperature=0.0
  )
  verdict = response.choices[0].message.content.strip()
  passed = verdict.upper().startswith("PASS")
  return passed, verdict

def test_eval_accuracy():
  """Run every golden Q through the pipeline, judge each, assert overall accuracy."""
  results = []
  for case in GOLDEN:
    answer, _ = generate_answer(case["question"])
    passed, verdict = judge(case["question"], case["expected"], answer)
    results.append((case["question"], passed, verdict))

  passed_count = sum(1 for _, passed, _ in results if passed)
  accuracy = passed_count / len(results)

  print(f"\n=== Eval accuracy: {passed_count}/{len(results)} = {accuracy:.0%} ===")
  for question, passed, verdict in results:
    print(f"[{'PASS' if passed else 'FAIL'}] {question}")
    if not passed:
      print(f"    verdict: {verdict}")

  assert accuracy >= ACCURACY_THRESHOLD, (
    f"Accuracy {accuracy:.0%} below threshold {ACCURACY_THRESHOLD:.0%}"
  )