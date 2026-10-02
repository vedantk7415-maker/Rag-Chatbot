"""Full regression after the embedder swap. Every row must match the baseline."""

import sys
import threading
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

proc = psutil.Process()
peak = 0
stop = False


def watch():
    global peak
    while not stop:
        peak = max(peak, proc.memory_info().rss / 1048576)
        threading.Event().wait(0.02)


threading.Thread(target=watch, daemon=True).start()

import formatter  # noqa: E402
import generator as gen  # noqa: E402
import guardrails  # noqa: E402

results = []


def record(name, got, want, note=""):
    ok = got == want
    results.append((name, got, want, ok, note))
    print(f"  {'PASS' if ok else 'FAIL'}  {name:<44} {got}/{want} {note}")


def body(a):
    return a.split("\n\n")[0].strip()


print("=== 1. fact accuracy (12 queries, value must appear) ===")
FACTS = [
    ("What is the expense ratio of HDFC Large Cap?", "1.04%"),
    ("What is the expense ratio of HDFC Flexi Cap?", "0.77%"),
    ("What is the expense ratio of HDFC ELSS Tax Saver?", "1.21%"),
    ("What is the expense ratio of HDFC Small Cap?", "0.79%"),
    ("What is the expense ratio of HDFC Balanced Advantage?", "0.78%"),
    ("What is the minimum SIP amount for HDFC ELSS?", "500"),
    ("What is the minimum SIP for HDFC Large Cap?", "100"),
    ("What is the exit load of HDFC ELSS?", "Nil"),
    ("What is the lock-in period of HDFC ELSS?", "3 year"),
    ("What is the benchmark of HDFC Large Cap?", "NIFTY 100"),
    ("What is the benchmark of HDFC Small Cap?", "BSE 250"),
    ("What is the riskometer rating of HDFC Flexi Cap?", "oderately High"),
]
hits = 0
fmt_errors = []
for q, exp in FACTS:
    r = gen.answer_question(q)
    hits += exp.lower() in r.answer.lower()
    b = body(r.answer)
    if len(formatter.split_sentences(b)) > 3:
        fmt_errors.append(f"{q}: >3 sentences")
    if r.answer.count("http") != 1:
        fmt_errors.append(f"{q}: {r.answer.count('http')} URLs")
    if "Last updated from sources:" not in r.answer:
        fmt_errors.append(f"{q}: no footer")
record("factual answers correct", hits, len(FACTS))
record("format contract violations", len(fmt_errors), 0, str(fmt_errors[:2]))

print("\n=== 2. guardrails ===")
BLOCKED = [
    ("Should I buy HDFC Small Cap?", "advice"),
    ("Which HDFC fund gave better returns?", "performance"),
    ("Compare HDFC Large Cap and HDFC Small Cap", "performance"),
    ("What is the 1 year return of HDFC ELSS?", "performance"),
    ("My PAN is ABCDE1234F, show my holdings", "pii"),
    ("Email me at ravi.sharma@gmail.com", "pii"),
    ("Call me on 9876543210", "pii"),
    ("My OTP is 482913", "pii"),
    ("Is HDFC Small Cap a good buy?", "advice"),
    ("How much should I invest monthly?", "advice"),
    ("Any advice on HDFC Flexi Cap?", "advice"),
    ("What is the CAGR of HDFC Small Cap?", "performance"),
]
bok = 0
for q, kind in BLOCKED:
    r = gen.answer_question(q)
    bok += bool(r.blocked and r.block_kind == kind and not r.in_sources and not r.chunks_used)
record("guardrail blocks correct", bok, len(BLOCKED))

print("\n=== 3. PII leak + false positives ===")
leak = 0
for q, vals in [
    ("My PAN is ABCDE1234F and email ravi@x.com, what is the exit load?", ["ABCDE1234F", "ravi@x.com"]),
    ("aadhaar 2345 6789 0123 and phone 9876543210, tell me NAV", ["2345 6789 0123", "9876543210"]),
]:
    r = gen.answer_question(q)
    leak += sum(v in r.answer for v in vals)
record("PII values echoed back", leak, 0)

schemes = ["HDFC Large Cap", "HDFC Flexi Cap", "HDFC ELSS Tax Saver", "HDFC Small Cap", "HDFC Balanced Advantage"]
topics = ["expense ratio", "exit load", "minimum SIP amount", "maximum SIP amount", "benchmark index",
          "riskometer rating", "AUM", "NAV", "lock-in period", "stamp duty", "minimum lump sum",
          "fund manager", "launch date", "tax implication", "ISIN code", "portfolio turnover",
          "minimum withdrawal", "custodian name", "RTA name", "investment objective"]
fp = 0
for s in schemes:
    for t in topics:
        if guardrails.check(f"What is the {t} of {s}?").blocked:
            fp += 1
record("false positives on legit questions", fp, 0)

print("\n=== 4. out of scope ===")
oos_ok = 0
OOS = ["What is the expense ratio of HDFC Parag Parag?", "Who is the CEO of HDFC AMC?",
       "What is the NAV of HDFC Liquid Fund?"]
for q in OOS:
    r = gen.answer_question(q)
    oos_ok += bool((not r.in_sources) and r.answer.count("http") == 0)
record("honest refusals, no invented citation", oos_ok, len(OOS))

print("\n=== 5. corpus-scope questions ===")
SCOPE_OK = [
    "which are these 5 mutual funds",
    "which funds do you cover?",
    "list the funds",
    "What can you tell me?",
]
scope_ok = 0
for q in SCOPE_OK:
    r = gen.answer_question(q)
    scope_ok += bool(r.in_sources and not r.blocked and len(r.chunks_used) == 0)
record("scope questions answered from corpus", scope_ok, len(SCOPE_OK))

# A scope pattern that is too greedy would hijack these and answer with a list
# instead of a fact or a refusal, so each must NOT be treated as scope.
SCOPE_LEAK = [
    "Which HDFC fund has a lower expense ratio?",
    "which fund is better, large cap or small cap?",
    "What is the expense ratio of HDFC Large Cap?",
    "which HDFC fund gave better returns?",
]
leaks = sum(gen.is_scope_question(q) for q in SCOPE_LEAK)
record("scope pattern hijacks comparisons", leaks, 0)

record("schemes listed in scope answer", len(gen.corpus_schemes()), 5)

print("\n=== 6. torch must NOT be loaded ===")
import sys as _s  # noqa: E402

record("torch imported", "torch" in _s.modules, False)
record("transformers imported", "transformers" in _s.modules, False)
record("sentence_transformers imported", "sentence_transformers" in _s.modules, False)

stop = True
print("\n" + "=" * 62)
print(f"PEAK MEMORY: {peak:.0f} MB   (budget 512 MB, headroom {512 - peak:.0f} MB)")
passed = sum(1 for r in results if r[3])
print(f"REGRESSION:  {passed}/{len(results)} checks passed")
print("=" * 62)
for name, got, want, ok, note in results:
    if not ok:
        print(f"  FAILED: {name} -> got {got}, wanted {want} {note}")
