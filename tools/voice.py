#!/usr/bin/env python3
"""Creates or manages a TrebleEye caller voice with OpenAI text-to-speech.

Run by .github/workflows/voice.yml. Settings come from environment variables:
  ACTION  provlyssna | skapa | publicera | dolj
  NAME    display name of the voice, e.g. "Big Mike"
  VOICE   OpenAI voice (onyx, ash, echo, ...)
  STYLE   style instruction in English (empty = default)
  OPENAI_API_KEY
"""
import json, os, re, subprocess, sys, tempfile, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOICES_JSON = os.path.join(ROOT, "voices.json")
DEFAULT_STYLE = ("Voice: a legendary British darts MC at a sold-out arena. Deep, gravelly, booming and theatrical, "
                 "with a strong London accent. Delivery: slow and deliberate, stretch the vowels of the numbers and let "
                 "the last word ring out, building drama like a boxing ring announcer. Never rush. The energy rises with "
                 "the size of the score. Say exactly the words given and nothing else.")
BOGEY = {159, 162, 163, 165, 166, 168, 169}
ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def en(n):
    if n < 20:
        return ONES[n]
    if n < 100:
        return TENS[n // 10] + ("-" + ONES[n % 10] if n % 10 else "")
    return ONES[n // 100] + " hundred" + (" and " + en(n % 100) if n % 100 else "")


def clip(name):
    """Text and delivery hint for one clip. Mirrors the clip names the app plays."""
    if name == "gameon":
        return "Game on!", "Energetic and rallying, the start of the match."
    if name == "gameshot":
        return "Game shot, and the leg!", "Triumphant, loud and celebratory, stretch 'Game shot'."
    if name == "s0":
        return "No score.", "Flat and a little dry."
    if name == "s180":
        return ("One hundred... and eightyyy!",
                "Maximum hype, the biggest moment of the night. A long, rising 'One hundred', a short pause, "
                "then a huge, drawn-out 'and eighty'.")
    n = int(name[1:])
    if name[0] == "r":
        return "You require, " + en(n) + ".", "Clear and measured with a little tension, announcing what the player needs to win."
    hint = ("Very loud and excited, stretch the vowels of the number." if n >= 140 else
            "Loud and enthusiastic, stretch the number out." if n >= 100 else
            "Firm and punchy." if n >= 60 else "Calm, clear call.")
    return en(n) + ("!" if n >= 100 else "."), hint


def all_clips():
    names = ["gameon", "gameshot"] + ["s%d" % i for i in range(181)]
    names += ["r%d" % i for i in range(2, 171) if i not in BOGEY]
    return names


def tts(key, voice, style, name):
    text, hint = clip(name)
    body = json.dumps({"model": "gpt-4o-mini-tts", "voice": voice, "input": text,
                       "instructions": style + " " + hint, "response_format": "mp3"}).encode()
    for attempt in range(6):
        req = urllib.request.Request("https://api.openai.com/v1/audio/speech", data=body, method="POST",
                                     headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")[:300]
            if e.code == 401:
                sys.exit("OpenAI godtog inte API-nyckeln (401). Kontrollera hemligheten OPENAI_API_KEY.")
            if e.code == 429 and re.search(r"quota|billing", msg, re.I):
                sys.exit("OpenAI-kontot saknar kredit. Fyll på under Billing på platform.openai.com.")
            if e.code in (429, 500, 502, 503, 504) and attempt < 5:
                time.sleep(2 * 2 ** attempt)
                continue
            sys.exit("OpenAI svarade %d för %s: %s" % (e.code, name, msg))
        except urllib.error.URLError:
            if attempt < 5:
                time.sleep(3)
                continue
            raise


def normalise(mp3, out_path):
    """Even loudness across clips, small mono mp3 like the built-in voices."""
    with tempfile.NamedTemporaryFile(suffix=".mp3") as tmp:
        tmp.write(mp3)
        tmp.flush()
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp.name, "-af", "loudnorm=I=-16:TP=-1.5:LRA=7",
                        "-ac", "1", "-ar", "24000", "-b:a", "48k", out_path], check=True)


def slug(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.lower().replace("å", "a").replace("ä", "a").replace("ö", "o")).strip("-")
    return s or "rost"


def load_voices():
    with open(VOICES_JSON) as f:
        return json.load(f)


def save_voices(data):
    with open(VOICES_JSON, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main():
    action = os.environ.get("ACTION", "provlyssna").strip()
    name = os.environ.get("NAME", "").strip()
    voice = os.environ.get("VOICE", "onyx").strip()
    style = os.environ.get("STYLE", "").strip() or DEFAULT_STYLE
    if not name:
        sys.exit("Ange ett namn på rösten.")
    vid = slug(name)
    data = load_voices()
    entry = next((v for v in data["voices"] if v["id"] == vid), None)

    if action in ("publicera", "dolj"):
        if not entry:
            sys.exit("Rösten '%s' (%s) finns inte. Skapa den först." % (name, vid))
        if action == "publicera" and entry.get("clips", 0) < len(all_clips()):
            sys.exit("Rösten '%s' har bara förhandsklipp. Kör 'skapa' först." % name)
        entry["status"] = "public" if action == "publicera" else "hidden"
        save_voices(data)
        print("%s är nu %s." % (name, "publicerad" if action == "publicera" else "dold"))
        return

    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        sys.exit("Hemligheten OPENAI_API_KEY saknas. Lägg in den under Settings > Secrets and variables > Actions.")
    names = ["s180", "r144", "gameshot"] if action == "provlyssna" else all_clips()
    out_dir = os.path.join(ROOT, "audio", vid)
    os.makedirs(out_dir, exist_ok=True)

    done = [0]

    def work(n):
        normalise(tts(key, voice, style, n), os.path.join(out_dir, n + ".mp3"))
        done[0] += 1
        if done[0] % 25 == 0 or done[0] == len(names):
            print("%d/%d klipp klara" % (done[0], len(names)), flush=True)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(work, names))

    clips = len([f for f in os.listdir(out_dir) if f.endswith(".mp3")])
    # new voices start as "preview" (only visible in admin mode); existing ones keep their status
    new = {"id": vid, "name": name, "status": (entry or {}).get("status", "preview"),
           "voice": voice, "style": style, "model": "gpt-4o-mini-tts", "clips": clips}
    if entry:
        entry.update(new)
    else:
        data["voices"].append(new)
    save_voices(data)
    print("Klart: %s (%s), %d klipp, status %s." % (name, vid, clips, new["status"]))


if __name__ == "__main__":
    main()
