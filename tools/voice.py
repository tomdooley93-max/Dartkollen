#!/usr/bin/env python3
"""Creates or manages a TrebleEye caller voice with OpenAI text-to-speech.

Run by .github/workflows/voice.yml. Settings come from environment variables:
  ACTION  provlyssna | skapa | publicera | dolj
  NAME    display name of the voice, e.g. "Big Mike"
  VOICE   OpenAI voice (onyx, ash, echo, ...)
  STYLE   style instruction in English (empty = default)
  TEMPO   playback speed applied afterwards, 0.8-1.5 (default 1.1)
  TAKES   takes per clip, 1-3 (default 2); the app picks one at random so calls vary
  OPENAI_API_KEY
"""
import json, os, re, subprocess, sys, tempfile, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOICES_JSON = os.path.join(ROOT, "voices.json")
DEFAULT_STYLE = ("Voice: a charismatic British darts MC at a packed, noisy arena. Warm, gritty and full of life, "
                 "with a London accent. Delivery: lively, natural pace with real emotion and no artificial pauses. "
                 "Punch the numbers out with rhythm and swagger, lifting the pitch on big scores and only stretching "
                 "the final word slightly. Sound excited to be there, never robotic or monotone. "
                 "Say exactly the words given and nothing else.")
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
        return "Game on!", "Short, sharp and fired up."
    if name == "gameshot":
        return "Game shot, and the leg!", "Triumphant and loud, quick and celebratory."
    if name == "s0":
        return "No score.", "Quick, dry and a bit cheeky."
    if name == "s180":
        return ("One hundred and eightyyy!",
                "Maximum hype, the biggest moment of the night. Build quickly through 'One hundred and', "
                "then explode on a big, ringing 'eighty'. No pause in the middle.")
    n = int(name[1:])
    if name[0] == "r":
        return "You require " + en(n) + ".", "Brisk and clear with a hint of tension, like telling the player what they need to win."
    hint = ("Very excited and loud, a big lift on the last word." if n >= 140 else
            "Enthusiastic and upbeat, a lift on the last word." if n >= 100 else
            "Punchy and confident." if n >= 60 else "Quick and matter-of-fact.")
    return en(n) + ("!" if n >= 100 else "."), hint


def all_clips():
    names = ["gameon", "gameshot"] + ["s%d" % i for i in range(181)]
    names += ["r%d" % i for i in range(2, 171) if i not in BOGEY]
    return names


TAKE_HINTS = ["",
              " This is an alternative take: vary the rhythm and put the emphasis on a different word than usual.",
              " Another alternative take: a fresh, spontaneous read with a bit more grit and attitude."]


def tts(key, voice, style, name, take=1):
    text, hint = clip(name)
    hint += TAKE_HINTS[take - 1]
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


def normalise(mp3, out_path, tempo):
    """Trim silence at the edges, shorten long pauses, apply tempo and even loudness; small mono mp3."""
    with tempfile.NamedTemporaryFile(suffix=".mp3") as tmp:
        tmp.write(mp3)
        tmp.flush()
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp.name, "-af", "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.02:"
                        "stop_periods=-1:stop_duration=0.2:stop_threshold=-45dB:stop_silence=0.1,"
                        "atempo=%.2f,loudnorm=I=-16:TP=-1.5:LRA=7" % tempo,
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
    try:
        tempo = min(1.5, max(0.8, float(os.environ.get("TEMPO", "1.1") or 1.1)))
    except ValueError:
        tempo = 1.1
    try:
        takes = min(3, max(1, int(os.environ.get("TAKES", "2") or 2)))
    except ValueError:
        takes = 2
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
    base = ["s180", "r144", "gameshot"] if action == "provlyssna" else all_clips()
    # (clip name, take, file name): take 1 is "s60.mp3", take 2 "s60_2.mp3" and so on
    names = [(n, t, n if t == 1 else "%s_%d" % (n, t)) for n in base for t in range(1, takes + 1)]
    out_dir = os.path.join(ROOT, "audio", vid)
    os.makedirs(out_dir, exist_ok=True)

    done = [0]

    def work(item):
        n, t, fname = item
        normalise(tts(key, voice, style, n, t), os.path.join(out_dir, fname + ".mp3"), tempo)
        done[0] += 1
        if done[0] % 25 == 0 or done[0] == len(names):
            print("%d/%d klipp klara" % (done[0], len(names)), flush=True)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(work, names))

    # count distinct clips (not takes) so "publicera" can check the voice is complete
    clips = len({re.sub(r"_\d$", "", f[:-4]) for f in os.listdir(out_dir) if f.endswith(".mp3")})
    # new voices start as "preview" (only visible in admin mode); existing ones keep their status
    new = {"id": vid, "name": name, "status": (entry or {}).get("status", "preview"),
           "voice": voice, "style": style, "tempo": tempo, "takes": takes if action == "skapa" else (entry or {}).get("takes", takes),
           "model": "gpt-4o-mini-tts", "clips": clips}
    if entry:
        entry.update(new)
    else:
        data["voices"].append(new)
    save_voices(data)
    print("Klart: %s (%s), %d klipp, status %s." % (name, vid, clips, new["status"]))


if __name__ == "__main__":
    main()
