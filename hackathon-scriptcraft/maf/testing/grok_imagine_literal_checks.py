"""Deterministic checks for literal Grok Imagine prompts.

These tests do not call Anthropic or xAI. They check the rewriter and the
instruction text. A live model can still phrase a shot differently; the
rewriter is what gets saved.
"""
import os
import re
import sys
import unittest
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
APP = os.path.join(REPO, "scriptcraft-app-v3")
if APP not in sys.path:
    sys.path.insert(0, APP)

from linedrive_azure.agents.grok_imagine_literals import (  # noqa: E402
    GROK_IMAGINE_SYSTEM,
    ensure_literal_image_prompt,
    rewrite_production_image_prompts,
)
from linedrive_azure.agents.pro_script_writer import (  # noqa: E402
    GROK_IMAGINE_STYLE_TAG,
    SCRIPT_WRITER_PRO_SYSTEM,
    build_pro_user_message,
)

OLD_STYLE = (
    "Landscape 16:9, dark navy background, cinematic soft lighting, clean "
    "modern editorial illustration, minimal or no text, no people, no faces, "
    "no hands."
)
_BLOCK_RE = re.compile(
    r"\[PRODUCTION\s+BEGIN\].*?\[PRODUCTION\s+END\]",
    re.IGNORECASE | re.DOTALL,
)
_GI_RE = re.compile(r"\[GROK IMAGINE[^\]]*\]\s*(.*)", re.IGNORECASE)


def _outside(script: str) -> str:
    return _BLOCK_RE.sub("[[BLOCK]]", script)


def _gi_lines(script: str):
    return _GI_RE.findall(script)


def _wrap(prompt: str, spoken: str, extra: str = "") -> str:
    lines = ["[PRODUCTION BEGIN]"]
    if extra:
        lines.append(extra)
    lines.append(f"[GROK IMAGINE / RESOLVE] {prompt} {OLD_STYLE}")
    lines.append("[PRODUCTION END]")
    lines.append(spoken)
    return "\n".join(lines) + "\n"


DEFINITION = (
    "First, two quick terms. A correction is a drop of at least ten percent "
    "from a recent peak. A bear market is a drop of twenty percent or more. "
    "On Thursday, parts of the market crossed that first line. That is a rough "
    "patch, and it deserves respect. It is not a collapse, and I will show you "
    "why. Here is our route. Where the selling started. What Democrats will "
    "probably do next. The funding strain underneath. The attack on the AI "
    "builders, and on Elon Musk. What the industry can do about it. Then the "
    "questions nobody can answer yet. Steady hands. Here we go."
)
TAPE = (
    "A long glowing measuring tape stretched across a dark floor, with two "
    "bright markers standing on it. The first is a small amber flag at the ten "
    "mark. The second is a tall red flag much farther along at the twenty mark. "
    "A softly glowing marble has rolled just past the amber flag and stopped "
    "well short of the red one."
)
POWER = (
    "Final stop on the trail. What can Musk and the industry actually do? "
    "First, take the power bill argument off the table. The strongest attack "
    "on data centers is that they raise electricity bills for ordinary "
    "families. Companies can answer that by building or paying for their own "
    "power, adding to the grid instead of draining it. Musk has an edge here, "
    "because Tesla already builds giant batteries for the grid."
)
JARS = (
    "Three tall glass jars on a dark shelf, each holding two glowing layers of "
    "liquid, warm amber on top of calm blue. A small blank calendar page leans "
    "against each jar."
)
MEETING = (
    "Second, show up locally. Data centers get approved or blocked in county "
    "meetings and state capitals, not just in Washington. Companies can sign "
    "community benefit agreements. Those are written promises for local jobs, "
    "tax revenue, water protection, and road repairs. Third, get ahead on "
    "safety."
)
ROPES = (
    "Two ropes hanging side by side from a glowing chip in a dark room. The "
    "left rope is short and pulled tight, wrapped in heavy iron chain. The "
    "right rope is long and slack and ends in a calm jar."
)
MUSK = (
    "But the biggest target is one man. Elon Musk. Democrats spent much of "
    "last year attacking him over his role in government, and now his AI "
    "company is in the line of fire."
)
HEARINGS = (
    "So what does that look like? Expect hearings, investigations into the "
    "deals these companies make with one another, and new safety rules for the "
    "most powerful models. Some Democrats argue that a few companies have too "
    "much power."
)
PIE = (
    "A glowing pie made of light floating above a dark table, sliced into "
    "hundreds of pieces, with a handful of giant marbles crowded in a jar beside it."
)
HOOK = (
    "Minus six point three six percent. One day. About two point three trillion "
    "dollars, erased from the biggest tech stocks. Is this your four oh one k? "
    "We will follow the money, find out who actually paid, and end with the one "
    "calm number in your own account worth checking this week."
)
THREAD = (
    "A towering stock ticker wall in an empty exchange hall. From a red line, a "
    "thin glowing red thread drops off the wall, winds across the floor, passes "
    "through an open doorway and along a row of glass jars, and ends at a "
    "kitchen table with a retirement envelope."
)
HEDGE = (
    "Some investors, including hedge funds, had borrowed money to make bigger "
    "bets on AI. When prices fell, their lenders demanded more cash, and they "
    "had to sell fast. People described that borrowed money as the tightest rope."
)


class LiteralPromptTests(unittest.TestCase):
    def test_definition_is_a_chart_not_the_route(self):
        src = _wrap(TAPE, DEFINITION, extra="[VERIFY BEFORE RENDER] Confirm the thresholds.")
        out = rewrite_production_image_prompts(src)
        gi = _gi_lines(out)[0].lower()
        self.assertIn("chart", gi)
        self.assertNotIn("measuring tape", gi)
        self.assertNotIn("marble", gi)
        self.assertNotIn("amber flag", gi)
        self.assertNotIn("musk", gi)
        self.assertNotIn("donkey", gi)
        self.assertNotIn("democrat", gi)
        self.assertIn('10%"', out)
        self.assertIn('20%"', out)
        self.assertIn("[ON SCREEN / RESOLVE]", out)
        self.assertIn("[VERIFY BEFORE RENDER]", out)
        self.assertNotIn("10%", gi)
        self.assertNotIn("no people, no faces, no hands", gi)
        self.assertIn("landscape 16:9", gi)
        self.assertIn("not documentary footage", gi)
        self.assertIn("not proof of any quote", gi)
        self.assertEqual(_outside(src), _outside(out))
        self.assertEqual(out, rewrite_production_image_prompts(out))

    def test_power_beat_is_the_grid_not_jars(self):
        src = _wrap(JARS, POWER)
        out = rewrite_production_image_prompts(src)
        gi = _gi_lines(out)[0].lower()
        self.assertIn("data", gi)
        self.assertIn("battery", gi)
        self.assertNotIn("jar", gi)
        self.assertNotIn("portrait", gi)
        self.assertNotIn("no people, no faces, no hands", gi)

    def test_meeting_beat_is_not_ropes(self):
        src = _wrap(ROPES, MEETING)
        out = rewrite_production_image_prompts(src)
        gi = _gi_lines(out)[0].lower()
        self.assertIn("meeting", gi)
        self.assertNotIn("rope", gi)
        self.assertNotIn("jar", gi)

    def test_musk_and_democrats_share_one_shot(self):
        src = _wrap("A balance scale and a stone bridge.", MUSK)
        out = rewrite_production_image_prompts(src)
        gi = _gi_lines(out)[0].lower()
        self.assertIn("elon musk", gi)
        self.assertIn("donkey", gi)
        self.assertIn("not a photograph of a real event", gi)
        self.assertNotIn("balance scale", gi)
        self.assertNotIn("stone bridge", gi)
        self.assertNotIn("no faces", gi)
        self.assertNotRegex(gi, r"\brope\b|\bjar\b|\bmarble\b")

    def test_hearings_are_not_a_pie(self):
        src = _wrap(PIE, HEARINGS)
        out = rewrite_production_image_prompts(src)
        gi = _gi_lines(out)[0].lower()
        self.assertIn("hearing", gi)
        self.assertIn("donkey", gi)
        self.assertNotIn("pie", gi)
        self.assertNotIn("marble", gi)
        self.assertNotIn("jar", gi)

    def test_hook_is_one_table_not_a_thread(self):
        # Hook speech comes before the production block.
        src = (
            "FINAL HOOK:\nHost:\n" + HOOK + "\n"
            "[PRODUCTION BEGIN]\n"
            f"[GROK IMAGINE / RESOLVE] {THREAD} {OLD_STYLE}\n"
            "[COLD OPEN / RESOLVE] 0:00 to 0:15 over the image above.\n"
            "[PRODUCTION END]\n"
        )
        out = rewrite_production_image_prompts(src)
        gi = _gi_lines(out)[0].lower()
        self.assertIn("envelope", gi)
        self.assertIn("chart", gi)
        self.assertNotIn("thread", gi)
        self.assertNotIn("jar", gi)
        self.assertNotIn("doorway", gi)
        self.assertIn("[COLD OPEN / RESOLVE]", out)
        self.assertIn(HOOK, out)
        self.assertEqual(out.count("[PRODUCTION BEGIN]"), out.count("[PRODUCTION END]"))

    def test_borrowed_money_is_not_drawn_as_a_rope(self):
        src = _wrap("A short rope wrapped in iron chain beside a glowing jar.", HEDGE)
        out = rewrite_production_image_prompts(src)
        gi = _gi_lines(out)[0].lower()
        self.assertIn("trading", gi)
        self.assertNotIn("rope", gi)
        self.assertNotIn("jar", gi)

    def test_paragraphs_stay_with_their_own_prompts(self):
        src = _wrap(JARS, POWER) + "\n" + _wrap(ROPES, MEETING)
        out = rewrite_production_image_prompts(src)
        lines = _gi_lines(out)
        self.assertEqual(len(lines), 2)
        self.assertIn("battery", lines[0].lower())
        self.assertNotIn("meeting", lines[0].lower())
        self.assertIn("meeting", lines[1].lower())
        self.assertNotIn("battery", lines[1].lower())
        self.assertLess(out.find(lines[0]), out.find(POWER))
        self.assertLess(out.find(POWER), out.find(lines[1]))
        self.assertLess(out.find(lines[1]), out.find(MEETING))

    def test_good_portrait_is_kept(self):
        good = (
            "An illustrative photo-style portrait of Elon Musk beside the "
            "Democratic Party donkey emblem. Not a photograph of a real event, "
            "and the person is not shown saying a quote."
        )
        out = rewrite_production_image_prompts(_wrap(good, MUSK))
        gi = _gi_lines(out)[0]
        self.assertIn("photo-style portrait of Elon Musk", gi)
        self.assertIn("donkey", gi.lower())
        self.assertTrue(gi.endswith(GROK_IMAGINE_STYLE_TAG))
        self.assertNotIn("no people, no faces, no hands", gi.lower())
        self.assertEqual(out, rewrite_production_image_prompts(out))

    def test_empty_model_prompt_still_aligns(self):
        prompt = ensure_literal_image_prompt("", POWER)
        self.assertIn("battery", prompt.lower())
        self.assertTrue(prompt.endswith(GROK_IMAGINE_STYLE_TAG))

    def test_instructions_allow_people_and_emblems(self):
        self.assertNotIn("no people, no faces, no hands", GROK_IMAGINE_STYLE_TAG)
        self.assertIn("Landscape 16:9", GROK_IMAGINE_STYLE_TAG)
        self.assertNotIn("NO people, NO faces", GROK_IMAGINE_SYSTEM)
        self.assertNotIn("symbolic objects", GROK_IMAGINE_SYSTEM)
        self.assertIn("Elon Musk", GROK_IMAGINE_SYSTEM)
        self.assertIn("Democratic", GROK_IMAGINE_SYSTEM)
        self.assertIn("donkey", GROK_IMAGINE_SYSTEM)
        self.assertNotIn("Use metaphor:", SCRIPT_WRITER_PRO_SYSTEM)
        self.assertIn("Democratic Party donkey", SCRIPT_WRITER_PRO_SYSTEM)
        self.assertIn("Do not append \"no people\"", SCRIPT_WRITER_PRO_SYSTEM)
        msg = build_pro_user_message("Example title", "A short brief about markets.")
        self.assertIn("do not copy", msg.lower())
        for rel in (
            "scriptcraft-app-v3/web_gui.py",
            "scriptcraft-app-v3-container/web_gui.py",
            "scriptcraft-app-v2/web_gui.py",
            "scriptcraft-app-v2-container/web_gui.py",
        ):
            text = Path(REPO, rel).read_text(encoding="utf-8")
            self.assertNotIn("depict its meaning as symbolic objects", text, rel)
            self.assertNotIn("NO people, NO faces", text, rel)
            self.assertIn("ensure_literal_image_prompt", text, rel)

    def test_copies_and_hosted_instructions_match(self):
        module = Path(APP, "linedrive_azure/agents/grok_imagine_literals.py").read_text(encoding="utf-8")
        for rel in (
            "scriptcraft-app-v3-container/linedrive_azure/agents/grok_imagine_literals.py",
            "scriptcraft-app-v2/linedrive_azure/agents/grok_imagine_literals.py",
            "scriptcraft-app-v2-container/linedrive_azure/agents/grok_imagine_literals.py",
        ):
            other = Path(REPO, rel).read_text(encoding="utf-8")
            self.assertEqual(module, other, rel)
        v3 = Path(APP, "linedrive_azure/agents/pro_script_writer.py").read_text(encoding="utf-8")
        v3c = Path(REPO, "scriptcraft-app-v3-container/linedrive_azure/agents/pro_script_writer.py").read_text(encoding="utf-8")
        self.assertEqual(v3, v3c)
        v2 = Path(REPO, "scriptcraft-app-v2/linedrive_azure/agents/pro_script_writer.py").read_text(encoding="utf-8")
        v2c = Path(REPO, "scriptcraft-app-v2-container/linedrive_azure/agents/pro_script_writer.py").read_text(encoding="utf-8")
        self.assertEqual(v2, v2c)
        md = Path(REPO, "scriptcraft-app-v2/agent_instructions/Script-Writer-Pro-Agent.md").read_text(encoding="utf-8")
        body = re.sub(r"^\s*<!--.*?-->\s*", "", md, count=1, flags=re.DOTALL).strip()
        self.assertEqual(body, SCRIPT_WRITER_PRO_SYSTEM.strip())


if __name__ == "__main__":
    unittest.main()
