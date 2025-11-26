
import os, json, re
import numpy as np
from supabase import create_client



SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Please set SUPABASE_URL and SUPABASE_KEY in environment")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

print("🔥 Connected to Supabase (improved matcher)")

# -------------------------
# Canonical / default maps
# -------------------------
CANONICAL_ISSUES = {
    "anxiety": ["anxiety", "panic", "panic attack", "panic attacks", "worry", "overthinking", "gad", "fear", "racing thoughts"],
    "depression": ["depression", "depressed", "sad", "sadness", "low mood", "hopeless", "empty", "numb"],
    "trauma": ["trauma", "ptsd", "abuse", "flashback", "flashbacks", "violence", "complex trauma", "childhood trauma"],
    "grief": ["loss", "grief", "bereavement", "breakup", "death", "mourning"],
    "emotion_regulation": ["anger", "irritability", "mood swing", "mood swings", "emotion regulation", "overwhelmed"],
    "relationships": ["relationship", "relationships", "family", "marriage", "conflict", "attachment", "trust issues"],
    "neurodiversity": ["adhd", "autism", "aspergers", "neurodiverse"]
}

CANONICAL_EMOTIONAL = {
    "validation": ["being heard","emotional comfort","validate","validation","feel seen","feel understood","empathy","safe space"],
    "tools": ["clear guidance","practical strategies","coping skills","tools","skill","action plan","cbt","technique","strategies"],
    "insight": ["exploring patterns","self awareness","reflection","insight","explore deeper meaning","psychodynamic","patterns"],
    "challenge": ["gentle challenge","challenge","push me","accountability","challenge beliefs"],
    "soothing": ["comfort","warmth","soothing","supportive","compassion","hold space","stay with feelings"],
    "structure": ["structured","organized","framework","step by step","roadmap","routine","schedule"]
}

CANONICAL_COMM = {
    "gentle": ["gentle","soft","warm","reassuring","compassionate","calm tone"],
    "direct": ["direct","straightforward","honest","clear","to the point","no-nonsense"],
    "humor": ["humor","lightness","light-hearted","playful","funny"],
    "guidance": ["guidance","homework","assignments","tasks","structured guidance","actionable"]
}

# Default maps for semantic single-choice categories
DEPTH_MAP = {
    "not much": 0.1,
    "a bit": 0.4,
    "deep": 1.0
}
PACING_MAP = {
    "slow": 0.2,
    "balanced": 0.5,
    "fast": 0.9
}
BOUNDARY_MAP = {
    "i get attached": 1.0,
    "balanced": 0.5,
    "i prefer space": 0.2
}

DEFAULT_VOCAB = {
    "issues": list(CANONICAL_ISSUES.keys()),
    "emotional_style": list(CANONICAL_EMOTIONAL.keys()),
    "communication_style": list(CANONICAL_COMM.keys()),
    "depth": list(DEPTH_MAP.keys()),
    "pacing": list(PACING_MAP.keys()),
    "boundaries": list(BOUNDARY_MAP.keys())
}

# -------------------------
# Text normalization & fuzzy helpers
# -------------------------
def normalize_text(s):
    if s is None:
        return ""
    s = str(s).lower().strip()
    # normalize curly quotes
    s = re.sub(r'[\u2018\u2019\u201c\u201d]', "'", s)
    # remove punctuation except spaces & slashes
    s = re.sub(r'[^a-z0-9\s/]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def safe_json_load(s):
    """Parse JSON string or comma-separated string into list of normalized tokens."""
    if s is None:
        return []
    if isinstance(s, list):
        return [normalize_text(x) for x in s if x is not None]
    if not isinstance(s, str):
        return [normalize_text(s)]
    s = s.strip()
    try:
        parsed = json.loads(s)
        if isinstance(parsed, list):
            return [normalize_text(x) for x in parsed]
        return [normalize_text(parsed)]
    except Exception:
        parts = re.split(r'[,;|/]\s*', s.strip('[]"\' '))
        parts = [normalize_text(p) for p in parts if p.strip()]
        return parts

def contains_fuzzy(text, phrase):
    """Return True if phrase roughly appears inside text (multiple heuristics)."""
    if not text or not phrase:
        return False
    t = normalize_text(text)
    p = normalize_text(phrase)
    if not p:
        return False
    # direct substring
    if p in t:
        return True
    # direct word overlap (at least 1 meaningful token)
    tw = set(t.split())
    pw = set(p.split())
    if len(tw & pw) >= 1:
        return True
    # phrase words all present (looser)
    if all(w in tw for w in p.split() if len(w) > 2):
        return True
    return False

# For canonical mappings: check if any keyword matches fuzzy
def canonical_tokens_from_text(text, mapping):
    found = set()
    for canon, kws in mapping.items():
        for kw in kws:
            if contains_fuzzy(text, kw):
                found.add(canon)
                break
    return found

# -------------------------
# Vectorizers (canonical -> numeric vectors)
# -------------------------
def vector_issues(text):
    tokens = canonical_tokens_from_text(text, CANONICAL_ISSUES)
    return [1 if cat in tokens else 0 for cat in CANONICAL_ISSUES.keys()]

def vector_emotional(text):
    axes = list(CANONICAL_EMOTIONAL.keys())
    vec = {a:0 for a in axes}
    for axis, kws in CANONICAL_EMOTIONAL.items():
        for k in kws:
            if contains_fuzzy(text, k):
                vec[axis] += 1
    return [vec[a] for a in axes]

def vector_comm(text):
    axes = list(CANONICAL_COMM.keys())
    vec = {a:0 for a in axes}
    for axis, kws in CANONICAL_COMM.items():
        for k in kws:
            if contains_fuzzy(text, k):
                vec[axis] += 1
    return [vec[a] for a in axes]

def value_from_map(text, mapping):
    t = normalize_text(text)
    for k,v in mapping.items():
        if contains_fuzzy(t, k):
            return v
    return 0.5  # neutral fallback

def value_depth(text):
    return value_from_map(text, DEPTH_MAP)

def value_pacing(text):
    return value_from_map(text, PACING_MAP)

def value_boundary(text):
    return value_from_map(text, BOUNDARY_MAP)

def cosine_sim(v1, v2):
    v1, v2 = np.array(v1, dtype=float), np.array(v2, dtype=float)
    if np.linalg.norm(v1) == 0 or np.linalg.norm(v2) == 0:
        return 0.0
    return float(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2)))

# -------------------------
# DB helpers (Supabase)
# -------------------------
def get_answer(user_id, qid):
    resp = supabase.table("answers").select("answer").eq("user_id", user_id).eq("question_id", qid).execute()
    rows = resp.data if hasattr(resp, "data") else resp
    if rows:
        return normalize_text(rows[0].get("answer"))
    return ""

def fetch_all_questions():
    resp = supabase.table("questions").select("id, category, options").execute()
    rows = resp.data
    qid_to_cat = {}
    vocab_by_cat = {}
    for r in rows:
        qid = int(r["id"])
        cat = (r.get("category") or "uncategorized").strip().lower()
        qid_to_cat[qid] = cat
        opts = safe_json_load(r.get("options"))
        if cat not in vocab_by_cat:
            vocab_by_cat[cat] = set()
        for o in opts:
            vocab_by_cat[cat].add(o)
    # ensure core categories exist
    for k, default in DEFAULT_VOCAB.items():
        if k not in vocab_by_cat or len(vocab_by_cat[k]) == 0:
            vocab_by_cat[k] = set(default)
    # convert
    vocab_by_cat = {k: sorted(list(v)) for k, v in vocab_by_cat.items()}
    return vocab_by_cat, qid_to_cat

def fetch_answers_for_id(entity_id):
    resp = supabase.table("answers").select("question_id, answer").eq("user_id", entity_id).execute()
    rows = resp.data
    out = {}
    for r in rows:
        out[int(r["question_id"])] = r.get("answer")
    return out

def fetch_therapists():
    resp = supabase.table("therapist_profiles").select("user_id, name").execute()
    return resp.data

# -------------------------
# Build profiles (keeps your original qid mapping)
# -------------------------
def build_user_profile(user_id):
    return {
        "issues": get_answer(user_id, 260),
        "emotion_style": " ".join([get_answer(user_id, q) for q in [265,266,267,268,269,270,287]]),
        "depth": get_answer(user_id, 267) + " " + get_answer(user_id, 280),
        "pacing": get_answer(user_id, 275),
        "boundaries": get_answer(user_id, 278),
        "communication": " ".join([get_answer(user_id, q) for q in [271,272,273,274]])
    }

def build_therapist_profile(tid):
    return {
        "issues": get_answer(tid, 288),
        "emotion_style": " ".join([get_answer(tid, q) for q in [289,290,291,292,293,294,295,301]]),
        "depth": get_answer(tid, 292) + " " + get_answer(tid, 301),
        "pacing": get_answer(tid, 300),
        "boundaries": get_answer(tid, 298),
        "communication": " ".join([get_answer(tid, q) for q in [296,297]])
    }

# -------------------------
# Compatibility & matching
# -------------------------
WEIGHTS = {
    "issues": 0.40,
    "emotional_style": 0.25,
    "depth": 0.10,
    "pacing": 0.10,
    "boundaries": 0.10,
    "communication": 0.05
}
# normalize weights
s = sum(WEIGHTS.values())
WEIGHTS = {k: v/s for k, v in WEIGHTS.items()}

def compatibility(user, therapist):
    clinical = cosine_sim(vector_issues(user["issues"]), vector_issues(therapist["issues"]))
    emotional = cosine_sim(vector_emotional(user["emotion_style"]), vector_emotional(therapist["emotion_style"]))
    depth = 1 - abs(value_depth(user["depth"]) - value_depth(therapist["depth"]))
    pacing = 1 - abs(value_pacing(user["pacing"]) - value_pacing(therapist["pacing"]))
    boundaries = 1 - abs(value_boundary(user["boundaries"]) - value_boundary(therapist["boundaries"]))
    comm = cosine_sim(vector_comm(user["communication"]), vector_comm(therapist["communication"]))

    final = (
        WEIGHTS["issues"] * clinical
        + WEIGHTS["emotional_style"] * emotional
        + WEIGHTS["depth"] * depth
        + WEIGHTS["pacing"] * pacing
        + WEIGHTS["boundaries"] * boundaries
        + WEIGHTS["communication"] * comm
    )

    breakdown = {
        "clinical_issues": round(clinical * 100, 2),
        "emotional_style": round(emotional * 100, 2),
        "depth_orientation": round(depth * 100, 2),
        "pacing": round(pacing * 100, 2),
        "boundaries": round(boundaries * 100, 2),
        "communication": round(comm * 100, 2),
    }
    return round(final * 100, 2), breakdown

def match_all(user_id, top_k=20):
    user_prof = build_user_profile(user_id)
    therapists = fetch_therapists()
    results = []
    for t in therapists:
        tid = t["user_id"]
        t_prof = build_therapist_profile(tid)
        score, breakdown = compatibility(user_prof, t_prof)
        results.append({
            "name": t.get("name", ""),
            "score": score,
            "breakdown": breakdown
        })
    results = sorted(results, key=lambda x: x["score"], reverse=True)
    return results[:top_k]


    
