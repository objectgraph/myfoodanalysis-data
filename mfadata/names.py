"""Natural names for USDA's database-style food descriptions, written by Catalyst's language model.

    uv run python -m mfadata.names data/foods-2026-04-30.db            # resumes; writes mfadata/names.json

USDA's Foundation and SR Legacy foods are named like a card catalogue ("Cheese, cheddar"; "Fish, salmon,
Atlantic, wild, cooked, dry heat"). People search "cheddar cheese" and "wild salmon cooked". This asks a language
model (we use qwen3.8:27b through Ollama on our own server; set CATALYST_LLM_URL and CATALYST_LLM_MODEL) to rename
each one, 40 at a time, then checks every answer mechanically. Names are keyed by USDA's description, so they carry
over to the next release. Survey (FNDDS) names are mostly everyday English already ("Banana, raw"); they are sent
too, so the few catalogue-style ones ("Cheese, Cheddar") read the same way as the rest.
"""

import json
import os
import re
import sqlite3
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Ollama's native chat API: unlike its OpenAI-compatible endpoint it can switch the model's thinking off, which
# makes a batch ~8x faster (16 s instead of ~2.5 min for 40 names).
ENDPOINT = os.environ.get("CATALYST_LLM_URL", "http://localhost:11434/api/chat")
MODEL = os.environ.get("CATALYST_LLM_MODEL", "qwen3.8:27b")
OUT = Path(__file__).with_name("names.json")
BATCH = 40

PROMPT = """You rename USDA food database entries into the natural names people type into a search engine.

Rules:
- Name the food first, the way people say it, then its state after a comma: "Cheese, cheddar" -> "Cheddar cheese"; "Fish, salmon, Atlantic, wild, cooked, dry heat" -> "Wild Atlantic salmon, cooked"; "Plantains, green, boiled" -> "Green plantains, boiled"; "Nuts, chestnuts, chinese, raw" -> "Chinese chestnuts, raw". Never start with raw, cooked or a cooking method.
- Keep every detail that changes the nutrition: raw/cooked and how (boiled, fried, roasted), with/without skin or bone, lean/fat trim (e.g. 85% lean), fat content of milk, sweetened/unsweetened, canned/frozen/dried, with/without salt, enriched/fortified, and the cut of meat.
- Drop filler that does not: "separable lean and fat" -> "lean and fat"; "(Includes foods for USDA's Food Distribution Program)" -> drop; "NFS" -> drop; "commercial" -> drop unless it matters.
- Keep brand names only if they are in the input; never invent one.
- Plain English, sentence case (first word capitalised, proper nouns capitalised), at most 60 characters, no quotes, no trailing period.

Answer with JSON only: an object mapping each input id to its new name, e.g. {"12": "Cheddar cheese"}."""


def ask(batch: list[tuple[int, str]]) -> dict[str, str]:
    body = {
        "model": MODEL,
        "think": False,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.2},
        "messages": [
            {"role": "system", "content": PROMPT},
            {"role": "user", "content": json.dumps({str(i): d for i, d in batch})},
        ],
    }
    req = urllib.request.Request(ENDPOINT, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                text = json.load(r)["message"]["content"]
            text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
            return json.loads(text[text.index("{") : text.rindex("}") + 1])
        except Exception as e:  # noqa: BLE001 - retry any transport or parse failure
            if attempt == 2:
                print(f"batch failed: {e}", file=sys.stderr, flush=True)
            time.sleep(3)
    return {}


STOP = {"raw", "cooked", "with", "without", "and", "or", "in", "of", "the", "a", "all", "nfs", "type", "style", "made", "from", "ready", "to", "eat", "commercial", "commercially", "prepared"}


# USDA's older words for foods people call something else; the checker accepts the everyday word for them.
SYNONYMS = {
    "catsup": "ketchup",
    "cowpea": "black-eyed",
    "blackeye": "black-eyed",
    "lingenberry": "cranberr",
    "garbanzo": "chickpea",
    "filbert": "hazelnut",
    "aubergine": "eggplant",
}


def keeps_the_food(description: str, name: str) -> bool:
    """The new name must keep a word of the original (the food itself), singular or plural, joined or split
    ("broadbeans" / "broad beans"), or its everyday synonym."""
    stem = lambda w: re.sub(r"(ies|es|s)$", "", w.lower())  # noqa: E731
    words = {stem(w) for w in re.findall(r"[A-Za-z]{3,}", name)}
    compact = re.sub(r"[^a-z]", "", name.lower())
    heads = [w for w in re.findall(r"[A-Za-z]{3,}", description) if w.lower() not in STOP]
    for w in heads:
        s = stem(w)
        if s in words or (len(s) >= 5 and s in compact):
            return True
        if any(s.startswith(old) and new.replace("-", "") in compact for old, new in SYNONYMS.items()):
            return True
    return False


COOKING = r"\b(cooked|boiled|fried|roasted|roast|baked|braised|broiled|grilled|steamed|stewed|microwaved|simmered|sauteed|poached|toasted|scrambled|smoked)\b"

# Qualifiers that change what the food is. If USDA's description has the first pattern, the name must have the
# second: a name may reword a qualifier but never drop or flip it. Negations are checked as whole phrases, so
# "not reconstituted" is never satisfied by "reconstituted" (and the reverse).
QUALIFIERS: list[tuple[str, str, str]] = [
    ("not reconstituted", r"\bnot reconstituted\b|\bunreconstituted\b", r"\bnot reconstituted\b|\bunreconstituted\b|\bdry\b"),
    ("reconstituted", r"(?<!not )\breconstituted\b", r"(?<!not )\breconstituted\b|\bprepared\b"),
    ("without salt", r"\bwithout (added )?salt\b|\bno (added )?salt\b|\bunsalted\b|\bsalt[- ]free\b",
     r"\bwithout (added )?salt\b|\bno (added )?salt\b|\bunsalted\b|\bsalt[- ]free\b"),
    ("with salt", r"\bwith (added )?salt\b|(?<!un)\bsalted\b", r"\bwith (added )?salt\b|(?<!un)\bsalted\b"),
    ("processed", r"\bprocess(ed)?\b", r"\bprocess(ed)?\b"),
    ("powder", r"\bpowder(ed)?\b", r"\bpowder(ed)?\b|\bdry mix\b"),
    ("dried", r"\bdried\b|\bdehydrated\b", r"\bdried\b|\bdehydrated\b|\bdry\b"),
    ("frozen", r"\bfrozen\b", r"\bfrozen\b"),
    ("canned", r"\bcanned\b", r"\bcanned\b"),
    ("concentrate", r"\bconcentrate\b", r"\bconcentrate\b"),
    ("raw", r"\braw\b", r"\braw\b|\buncooked\b"),
    ("cooked", COOKING, COOKING),
    ("fat-free", r"\bnonfat\b|\bfat[- ]free\b|\bskim\b", r"\bnonfat\b|\bfat[- ]free\b|\bskim\b"),
    ("low fat", r"\blow[- ]?fat\b", r"\blow[- ]?fat\b|\b1(\.5)?%"),
    ("reduced fat", r"\breduced[- ]fat\b", r"\breduced[- ]fat\b|\b2%"),
    ("diet", r"\bdiet\b", r"\bdiet\b|\bsugar[- ]free\b|\blow[- ]calorie\b"),
    ("unsweetened", r"\bunsweetened\b|\bno sugar added\b|\bwithout added sugar\b",
     r"\bunsweetened\b|\bno sugar added\b|\bwithout added sugar\b"),
    ("sweetened", r"(?<!un)\bsweetened\b", r"(?<!un)\bsweetened\b"),
    ("decaffeinated", r"\bdecaf", r"\bdecaf"),
    ("without skin", r"\bwithout skin\b|\bskinless\b|\bskin not eaten\b", r"\bwithout skin\b|\bskinless\b|\bskin not eaten\b|\bskin removed\b|\bno skin\b"),
    ("with skin", r"\bwith skin\b|\bskin eaten\b", r"\bwith skin\b|\bskin eaten\b|\bskin[- ]on\b"),
]


def qualifiers_kept(description: str, name: str) -> list[str]:
    """The qualifiers of USDA's description that the name drops or flips (empty when it keeps them all). Every
    percentage in the description ("85% lean", "2% milkfat") must also appear in the name."""
    d, n = description.lower(), name.lower()
    lost = [label for label, in_desc, in_name in QUALIFIERS if re.search(in_desc, d) and not re.search(in_name, n)]
    lost += [p for p in re.findall(r"\d+(?:\.\d+)?%", d) if p not in n]
    return lost


def valid(description: str, name: str) -> bool:
    return (
        isinstance(name, str)
        and 2 <= len(name) <= 70
        and "\n" not in name
        and not name.endswith(".")
        and keeps_the_food(description, name)
        and not qualifiers_kept(description, name)
    )


def main(db_path: str) -> None:
    db = sqlite3.connect(db_path)
    rows = db.execute("select fdc_id, description from food where data_type in ('foundation', 'sr_legacy', 'survey') order by fdc_id").fetchall()
    names: dict[str, str] = json.loads(OUT.read_text()) if OUT.exists() else {}
    todo = [(i, d) for i, d in rows if d not in names]
    print(f"{len(rows)} foods, {len(names)} named already, {len(todo)} to go", flush=True)
    batches = [todo[k : k + BATCH] for k in range(0, len(todo), BATCH)]
    rejected = 0

    def run(batch):
        return batch, ask(batch)

    with ThreadPoolExecutor(max_workers=int(os.environ.get("CATALYST_LLM_PARALLEL", "1"))) as pool:
        for n, (batch, answer) in enumerate(pool.map(run, batches), 1):
            for fdc_id, desc in batch:
                name = answer.get(str(fdc_id))
                if name and valid(desc, name.strip()):
                    names[desc] = name.strip()
                else:
                    rejected += 1
            if n % 5 == 0 or n == len(batches):
                OUT.write_text(json.dumps(dict(sorted(names.items())), indent=0, ensure_ascii=False))
                print(f"{n}/{len(batches)} batches, {len(names)} names, {rejected} rejected", flush=True)
    OUT.write_text(json.dumps(dict(sorted(names.items())), indent=0, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1])
