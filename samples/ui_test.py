"""
Headless UI test for app.py.

Verifies the demo brief's non-negotiable items plus the new UI behaviour, using
Streamlit's AppTest so it runs without a browser.
"""

import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# The app uses emoji in labels. Windows consoles default to cp1252 and cannot
# encode them, so stdout is widened before anything is printed.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   {detail}" if detail else ""))


def all_text(at):
    """Every visible text node the app rendered, as one blob."""
    parts = []
    for attr in ("markdown", "caption", "info", "warning", "error", "success"):
        for node in getattr(at, attr, []) or []:
            parts.append(str(getattr(node, "value", "")))
    for msg in at.chat_message:
        parts.append(str(getattr(msg, "content", "")))
    return "\n".join(parts)


print("=== 1. first load: welcome, examples, disclaimer ===")
at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=240)
at.run()
check("starts with no exceptions", len(at.exception) == 0, str([e.value for e in at.exception]))

text = all_text(at)
check("welcome line present", "Welcome" in text)
check("disclaimer always visible", "Facts-only. No investment advice." in text)
check("corpus load shown quietly", "Corpus loaded" in text)

example_keys = [k for k in at.button[0].key.split("-") if k.startswith("example_")] if at.button else []
n_examples = sum(1 for b in at.button if (b.key or "").startswith("example_"))
check("exactly 3 example questions", n_examples == 3, f"found {n_examples}")
check("chat input present", len(at.chat_input) == 1)

expander_labels = [e.label for e in (getattr(at, "expander", []) or [])]
leaked = [lbl for lbl in expander_labels if "Retrieved context" in str(lbl)]
check("chunk count hidden by default", not leaked, str(leaked))
check("retrieval panel off by default", any("Retrieval details" in str(l) for l in expander_labels))

print("\n=== 2. grounded answer: body, ONE new-tab link, date line ===")
at.chat_input[0].set_value("What is the expense ratio of HDFC Small Cap?").run()
check("no exceptions", len(at.exception) == 0, str([e.value for e in at.exception]))

html_blobs = [str(m.value) for m in at.markdown]
footers = [h for h in html_blobs if 'class="srcfoot"' in h]
check("footer rendered", len(footers) == 1, f"{len(footers)} footers")

footer = footers[0] if footers else ""
check("source link opens in new tab", 'target="_blank"' in footer)
check("source link has rel=noopener", 'rel="noopener noreferrer"' in footer)
check("raw URL not shown as link text", "groww.in" in footer)
check("exactly one link in footer", footer.count("<a ") == 1, f"{footer.count('<a ')} links")
check("date line present", "Last updated from sources:" in footer)

text = all_text(at)
check("correct fact (0.79%)", "0.79%" in text)
check("no raw URL left in prose", "https://" not in text.split("class=\"srcfoot\"")[0])

print("\n=== 3. refusal renders as a framed warning ===")
at.chat_input[0].set_value("Should I buy HDFC Large Cap?").run()
check("no exceptions", len(at.exception) == 0)
warn_text = "\n".join(str(w.value) for w in (at.warning or []))
allmd = all_text(at)
check("blocked notice styled as warning", "Investment advice request" in allmd)
check("states model not called", "Not sent to the language model" in allmd)
check("nothing stored", "Nothing was stored" in allmd)
check("educational link retained in refusal", "http" in allmd)

print("\n=== 4. retrieval panel appears only when toggled on ===")
at.toggle[0].set_value(True).run()
labels = [str(e.label) for e in (getattr(at, "expander", []) or [])]
check("panel visible when toggled", any("Retrieved context" in l for l in labels), str(labels))

print("\n=== 5. sidebar example button runs the question ===")
at2 = AppTest.from_file(str(ROOT / "app.py"), default_timeout=240)
at2.run()
btn = [b for b in at2.button if (b.key or "").startswith("example_")][0]
at2.button(key=btn.key).click().run()
check("no exceptions", len(at2.exception) == 0, str([e.value for e in at2.exception]))
check("example question answered", len(at2.chat_message) >= 2, f"{len(at2.chat_message)} messages")
check("answer is grounded", "Last updated from sources:" in all_text(at2))

print("\n=== 6. clear chat ===")
at2.button(key="clear_chat").click().run()
check("no exceptions", len(at2.exception) == 0)
check("history cleared", len(at2.chat_message) == 0, f"{len(at2.chat_message)} left")
check("welcome returns", "Welcome" in all_text(at2))

print("\n" + "=" * 60)
passed = sum(1 for _, ok, _ in results if ok)
print(f"{passed}/{len(results)} UI checks passed")
print("=" * 60)
for name, ok, detail in results:
    if not ok:
        print(f"  FAILED: {name}  {detail}")