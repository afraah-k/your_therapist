# app.py — Minimal clean rewrite
import os
import json
import re
import warnings

import streamlit as st
from dotenv import load_dotenv
from supabase import create_client, Client
from streamlit_lottie import st_lottie
import matching_engine

# ---- local imports (matching engine expects env vars to be set first) ----
# We'll set environment variables from Streamlit secrets and then import the matching function.
load_dotenv()
warnings.filterwarnings("ignore", category=UserWarning, module="ctranslate2")

# ---- Load Supabase secrets into environment so matching_engine can read them ----
if "SUPABASE_URL" in st.secrets and "SUPABASE_KEY" in st.secrets:
    os.environ["SUPABASE_URL"] = st.secrets["SUPABASE_URL"]
    os.environ["SUPABASE_KEY"] = st.secrets["SUPABASE_KEY"]
else:
    # fallback to .env
    if os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_KEY"):
        os.environ["SUPABASE_URL"] = os.getenv("SUPABASE_URL")
        os.environ["SUPABASE_KEY"] = os.getenv("SUPABASE_KEY")
    else:
        st.error("Supabase credentials missing. Add them to Streamlit secrets or .env.")
        st.stop()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# ---- Supabase client ----
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---- Import matching function AFTER env vars are set ----
from matching_engine import match_all  # noqa: E402

# ---- Test DB connection early ----
try:
    _ = supabase.table("users").select("id").limit(1).execute()
except Exception as e:
    st.error(f"Cannot connect to Supabase: {e}")
    st.stop()

# ---- Streamlit page config ----
st.set_page_config(page_title="Your Therapist", page_icon="💜", layout="wide")

# ---- Helpers ----
def load_lottiefile(filepath: str):
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except Exception:
        return None

def fetch_mcqs_for(target="user"):
    resp = supabase.table("questions").select("id, question_number, question_text, options, target").eq("target", target).order("question_number").execute()
    return resp.data or []

def save_user_preferences(name: str, email: str, free_text_intro: str, free_text_end: str):
    # upsert user
    resp = supabase.table("users").upsert({"name": name, "email": email, "role": "user"}).execute()
    if resp.data:
        user_id = resp.data[0]["id"]
    else:
        existing = supabase.table("users").select("id").eq("email", email).execute()
        user_id = existing.data[0]["id"]
    combined = ""
    if free_text_intro:
        combined += f"Intro: {free_text_intro}\n\n"
    if free_text_end:
        combined += f"Additional: {free_text_end}"
    supabase.table("preferences").upsert({"user_id": user_id, "free_text": combined}).execute()
    return user_id

def save_user_mcq_answers(user_id: int, answers: dict):
    # answers keyed by question_number as in UI
    for q_num, ans in answers.items():
        q_lookup = supabase.table("questions").select("id").eq("question_number", q_num).limit(1).execute()
        if not q_lookup.data:
            continue
        qid = q_lookup.data[0]["id"]
        payload = {
            "user_id": user_id,
            "question_id": qid,
            "answer": json.dumps(ans) if isinstance(ans, (list, dict)) else str(ans)
        }
        # upsert to avoid duplicates if user resubmits
        supabase.table("answers").insert(payload).execute()

# ---- UI ----
st.title("(❁´◡`❁) Welcome to Your Therapist")
role = st.radio("Are you here as a...", ["User / Client", "Therapist"], horizontal=True)

# preserve role in session
if "last_role" in st.session_state and st.session_state["last_role"] != role:
    # clear session state except last_role
    for k in list(st.session_state.keys()):
        if k != "last_role":
            del st.session_state[k]
st.session_state["last_role"] = role

# ---------------- USER FLOW ----------------
if role == "User / Client":
    st.markdown(
        """
        <div style="background: linear-gradient(135deg, #e0c3fc, #8ec5fc);
                    padding:25px; border-radius:15px; text-align:center; margin-bottom:20px;">
            <h2 style="color:#2d046e;">🌱 Find the Right Therapist for You</h2>
            <p>Share in your own words ✍️ or answer our questions 🧾 to help us match you with a therapist.</p>
        </div>
        """, unsafe_allow_html=True
    )

    with st.form("user_form"):
        user_name = st.text_input("🧑 Your Name")
        user_email = st.text_input("📧 Your Email")
        free_text_intro = st.text_area("💬 Share in your own words (optional)", placeholder="I've been feeling anxious...")
        st.info("🌸 These questions help us understand you better. This will take ~3–5 minutes.")

        # render MCQs
        answers = {}
        mcqs = fetch_mcqs_for("user")
        for mcq in mcqs:
            q_num = mcq.get("question_number")
            q_text = mcq.get("question_text")
            options = mcq.get("options")
            with st.expander(f"Q{q_num}: {q_text}"):
                # special-case numeric sliders
                if q_num == 28:
                    # options may be JSON list or string
                    if isinstance(options, str):
                        try:
                            options = json.loads(options)
                        except Exception:
                            options = [options]
                    answers[q_num] = {}
                    for i, statement in enumerate(options, start=1):
                        answers[q_num][statement] = st.slider(statement, 1, 5, 3, key=f"q{q_num}_s{i}")
                elif options:
                    if isinstance(options, str):
                        try:
                            options = json.loads(options)
                        except Exception:
                            options = [options]
                    # check if this MCQ expects multiple answers
                    if "select all" in (mcq.get("question_text") or "").lower() or isinstance(options, list) and len(options) > 1 and q_num in [1, 12, 18]:
                        answers[q_num] = st.multiselect("Select all that apply:", options, key=f"q{q_num}")
                    else:
                        # radio for single choice
                        try:
                            answers[q_num] = st.radio("Choose one:", options, key=f"q{q_num}", index=None)
                        except Exception:
                            answers[q_num] = st.radio("Choose one:", options, key=f"q{q_num}")
                else:
                    answers[q_num] = st.text_area("Your answer:", key=f"q{q_num}_text")

        free_text_end = st.text_area("✨ Anything else you'd like your therapist to know?")

        submitted = st.form_submit_button("🚀 Submit My Preferences")

        if submitted:
            if not user_name or not user_email:
                st.error("⚠️ Please enter your name and email.")
            else:
                try:
                    user_id = save_user_preferences(user_name, user_email, free_text_intro, free_text_end)
                    save_user_mcq_answers(user_id, answers)
                    st.session_state["user_submitted"] = True
                    st.session_state["user_id"] = user_id
                except Exception as e:
                    st.error(f"Error saving preferences: {e}")

    # After successful submission — acknowledge and show matches
    if st.session_state.get("user_submitted", False):
        st.success("✅ Your preferences have been saved!")
        _, col2, _ = st.columns([1, 2, 1])
        with col2:
            lottie_json = load_lottiefile("animations/mental_wellbeing.json")
            if lottie_json:
                st_lottie(lottie_json, height=240)

        st.markdown(
            """
            <div style="text-align:center; margin-top:-10px;">
                <h3 style="color:#2d046e;">🌱 Thank you for trusting us!</h3>
                <p style="font-size:16px; color:#555;">
                    Your preferences will help us match you with the right therapist.  
                </p>
            </div>
            """, unsafe_allow_html=True
        )

        # --- New Matching Section (Top 6) ---
        st.markdown("### 💜 Your Top Therapist Matches")
        try:
            results = match_all(st.session_state["user_id"])
            top6 = results[:6]
            if not top6:
                st.info("We’re gathering more therapist data — please check back soon!")
            else:
                for r in top6:
                    name = r.get("name", "Unknown")
                    score = r.get("score", 0.0)
                    breakdown = r.get("breakdown", {})
                    st.markdown(f"""
                    <div style="background:#f9f9ff; padding:18px; border-radius:12px; margin-bottom:12px;">
                        <h3 style="color:#2d046e; margin:0;">{name}</h3>
                        <h4 style="color:#4b2ea0; margin:4px 0 8px;">⭐ Overall Match: {score}%</h4>
                        <div style="font-size:14px; color:#333;">
                            <p><b>Clinical Issues:</b> {breakdown.get('clinical_issues','N/A')}%</p>
                            <p><b>Emotional Style:</b> {breakdown.get('emotional_style','N/A')}%</p>
                            <p><b>Depth Orientation:</b> {breakdown.get('depth_orientation','N/A')}%</p>
                            <p><b>Pacing:</b> {breakdown.get('pacing','N/A')}%</p>
                            <p><b>Boundaries:</b> {breakdown.get('boundaries','N/A')}%</p>
                            <p><b>Communication:</b> {breakdown.get('communication','N/A')}%</p>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
        except Exception as e:
            st.error(f"Error computing matches: {e}")

        st.markdown(
            """
            <div style="text-align:center;">
                <a href="https://forms.gle/de6JqeAo6mrM1iYv5" target="_blank"
                style="background-color:#8ec5fc; color:white; padding:10px 20px;
                border-radius:10px; text-decoration:none; font-weight:600;">
                💜 Give Feedback
                </a>
            </div>
            """, unsafe_allow_html=True)

# ---------------- THERAPIST FLOW ----------------
elif role == "Therapist":
    st.markdown(
        """
        <div style="background: linear-gradient(135deg, #ffecd2, #fcb69f);
                    padding:25px; border-radius:15px; text-align:center; margin-bottom:20px;">
            <h2 style="color:#6a1b9a;">🎙️ Therapist Portal</h2>
            <p>Step 1: Provide your basic information. Step 2: Answer your professional MCQs.</p>
        </div>
        """, unsafe_allow_html=True)

    st.subheader("📋 Step 1: Basic Information")
    with st.form("therapist_info_form"):
        name = st.text_input("Name")
        email = st.text_input("Email (unique identifier)")
        gender = st.radio("Gender", ["Male", "Female", "Other"])
        age = st.number_input("Age", min_value=18, max_value=100, step=1)
        religious_belief = st.text_input("Religious Belief")
        practice_location = st.text_input("Practice Location")
        languages = st.text_area("Languages Known (comma-separated)")
        session_modes = st.multiselect("Modes of Session", ["In-person", "Video", "Phone", "Hybrid"])
        charge = st.text_input("💵 How much do you charge per session?")

        submitted_info = st.form_submit_button("💾 Save Info")
        if submitted_info:
            if not (name and email and gender and religious_belief and practice_location and charge):
                st.error("⚠️ Please fill in all required fields before proceeding.")
            else:
                try:
                    charge_value = int(charge)
                except ValueError:
                    charge_value = None
                language_list = [lang.strip() for lang in languages.split(",") if lang.strip()] if isinstance(languages, str) else []
                user_resp = supabase.table("users").upsert({"name": name, "email": email, "role": "therapist"}).execute()
                if user_resp.data:
                    user_id = user_resp.data[0]["id"]
                else:
                    existing = supabase.table("users").select("id").eq("email", email).execute()
                    user_id = existing.data[0]["id"]
                st.session_state["therapist_user_id"] = user_id
                insert_data = {
                    "user_id": user_id,
                    "name": name,
                    "email": email,
                    "gender": gender,
                    "age": int(age) if age else None,
                    "religious_belief": religious_belief,
                    "practice_location": practice_location,
                    "languages": language_list,
                    "session_modes": session_modes,
                    "charge": charge_value
                }
                try:
                    supabase.table("therapist_profiles").upsert(insert_data).execute()
                    st.success("✅ Basic information saved successfully!")
                except Exception as e:
                    st.error(f"⚠️ Database insert failed: {e}")

    # Step 2: Therapist MCQs
    if "therapist_user_id" in st.session_state:
        st.subheader("🧾 Step 2: Answer Therapist MCQs")
        st.info("💜 Please answer these questions honestly — it takes about 5 minutes.")

        def fetch_therapist_mcqs():
            resp = supabase.table("questions").select("id, question_number, question_text, options").eq("target", "therapist").order("question_number").execute()
            return resp.data or []

        mcqs = fetch_therapist_mcqs()
        answers = {}
        with st.form("therapist_mcq_form"):
            for mcq in mcqs:
                q_num = mcq.get("question_number")
                q_display = q_num - 100
                q_text = mcq.get("question_text")
                options = mcq.get("options")
                with st.expander(f"Q{q_display}: {q_text}", expanded=False):
                    if q_num == 101:
                        answers[q_num] = st.text_area("Your areas of specialization:", key=f"tq{q_num}")
                    elif q_num in [108, 116]:
                        if isinstance(options, str):
                            try:
                                options = json.loads(options)
                            except Exception:
                                options = [options]
                        answers[q_num] = {}
                        for i, statement in enumerate(options, start=1):
                            answers[q_num][statement] = st.slider(statement, 1, 5, 3, key=f"tq{q_num}_s{i}")
                    elif q_num == 119:
                        answers[q_num] = st.text_area("(Optional) Your thoughts:", key=f"tq{q_num}_optional")
                    elif options:
                        if isinstance(options, str):
                            try:
                                options = json.loads(options)
                            except Exception:
                                options = [options]
                        if "select all" in (q_text or "").lower() or "multiple" in (q_text or "").lower():
                            answers[q_num] = st.multiselect("Select all that apply:", options, key=f"tq{q_num}")
                        else:
                            answers[q_num] = st.radio("Choose one:", options, key=f"tq{q_num}", index=None)
                    else:
                        answers[q_num] = st.text_area("Your answer:", key=f"tq{q_num}_text")

            submitted = st.form_submit_button("🚀 Submit My Answers")
            if submitted:
                try:
                    for q_num, ans in answers.items():
                        if q_num == 119 and (not ans or str(ans).strip() == ""):
                            continue
                        q_lookup = supabase.table("questions").select("id").eq("question_number", q_num).limit(1).execute()
                        if not q_lookup.data:
                            continue
                        question_id = q_lookup.data[0]["id"]
                        supabase.table("answers").insert({
                            "user_id": st.session_state["therapist_user_id"],
                            "question_id": question_id,
                            "answer": json.dumps(ans) if isinstance(ans, (list, dict)) else str(ans)
                        }).execute()
                    st.success("✅ All your MCQ answers have been submitted successfully!")
                    _, col2, _ = st.columns([1, 2, 1])
                    with col2:
                        confetti_json = load_lottiefile("animations/success_confetti.json")
                        if confetti_json:
                            st_lottie(confetti_json, height=240)
                    st.markdown(
                        """
                        <div style="text-align:center; margin-top:10px;">
                            <h3 style="color:#6a1b9a;">📝 We value your feedback!</h3>
                            <a href="https://forms.gle/5txFuYQ6Gn4b9GMj6" target="_blank"
                            style="background-color:#fcb69f; color:white; padding:10px 20px;
                            border-radius:10px; text-decoration:none; font-weight:600;">
                            💜 Give Feedback
                            </a>
                        </div>
                        """, unsafe_allow_html=True)
                    st.session_state["therapist_all_submitted"] = True
                except Exception as e:
                    st.error(f"⚠️ Error saving your responses: {e}")

