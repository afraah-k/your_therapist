import streamlit as st
import json
import os
from dotenv import load_dotenv
from supabase import create_client, Client
import warnings
from streamlit_lottie import st_lottie
import requests

# --- Suppress warnings ---
warnings.filterwarnings("ignore", category=UserWarning, module="ctranslate2")

# --- Load environment variables ---
load_dotenv()

SUPABASE_URL = st.secrets.get("SUPABASE_URL") or os.getenv("SUPABASE_URL")
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY") or os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    st.error("Supabase credentials are missing! Please set them in Streamlit secrets or .env.")
    st.stop()

# --- Create Supabase client ---
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Test connection ---
try:
    test = supabase.table("users").select("id").limit(1).execute()
    st.success("✅ Connected to Supabase successfully!")
except Exception as e:
    st.error(f"⚠️ Could not connect to Supabase: {e}")
    st.stop()

# --- Streamlit Page Config ---
st.set_page_config(page_title="Your Therapist", page_icon="💜", layout="wide")

# --- Helper for Lottie animations ---
def load_lottiefile(filepath: str):
    with open(filepath, "r") as f:
        return json.load(f)

# --- Fetch USER MCQs ---
def fetch_mcqs():
    response = supabase.table("questions").select(
        "id, question_number, question_text, options"
    ).eq("target", "user").order("question_number").execute()
    return response.data

# --- Save User Preferences ---
def save_user_preferences(user_name, user_email, free_text_intro, free_text_end):
    response = supabase.table("users").insert({
        "name": user_name,
        "email": user_email
    }).execute()

    if response.data:
        user_id = response.data[0]["id"]
    else:
        existing = supabase.table("users").select("id").eq("email", user_email).execute()
        user_id = existing.data[0]["id"]

    combined_free_text = ""
    if free_text_intro:
        combined_free_text += f"Intro: {free_text_intro}\n\n"
    if free_text_end:
        combined_free_text += f"Additional: {free_text_end}"

    supabase.table("user_preferences").insert({
        "user_id": user_id,
        "free_text_preference": combined_free_text
    }).execute()

    return user_id

# --- Save MCQ answers ---
def save_user_mcq_answers(user_id, answers_dict):
    for q_num, ans in answers_dict.items():
        q_lookup = supabase.table("questions").select("id").eq("question_number", q_num).execute()
        if q_lookup.data:
            question_id = q_lookup.data[0]["id"]
            supabase.table("user_mcq_answers").insert({
                "user_id": user_id,
                "question_id": question_id,
                "answer": str(ans)
            }).execute()

# ------------------- UI -------------------
st.title("(❁´◡`❁) Welcome to Your Therapist")

role = st.radio("Are you here as a...", ["User / Client", "Therapist"], horizontal=True)

# Reset session state when switching roles
if "last_role" in st.session_state and st.session_state["last_role"] != role:
    for key in list(st.session_state.keys()):
        if key not in ["last_role"]:
            del st.session_state[key]
st.session_state["last_role"] = role

# ---------------- USER FLOW ----------------
if role == "User / Client":
    st.markdown(
        """
        <div style="background: linear-gradient(135deg, #e0c3fc, #8ec5fc);
        padding:25px; border-radius:15px; text-align:center; margin-bottom:20px;">
        <h2 style="color:#2d046e;">🌱 Find the Right Therapist for You</h2>
        <p>Share freely in your own words ✍️ or answer our questions 🧾.  
        This helps us understand your needs and match you with the right therapist 💜</p>
        </div>
        """,
        unsafe_allow_html=True
    )

    with st.form("user_form"):
        user_name = st.text_input("🧑 Your Name")
        user_email = st.text_input("📧 Your Email")
        free_text_intro = st.text_area("💬 Share in your own words (optional)", placeholder="Example: I've been feeling anxious...")

        st.info("🌸 These questions are here to understand you better. This will take 3–5 minutes.")

        answers = {}
        mcqs = fetch_mcqs()

        for mcq in mcqs:
            q_num = mcq["question_number"]
            q_text = mcq["question_text"]
            options = mcq["options"]

            with st.expander(f"Q{q_num}: {q_text}"):
                if options:
                    if isinstance(options, str):
                        try:
                            options = json.loads(options)
                        except:
                            options = [options]

                    # Multiselects
                    if q_num in [1, 12, 18]:
                        answers[q_num] = st.multiselect("Select all that apply:", options, key=f"q{q_num}")
                    else:
                        answers[q_num] = st.radio("Choose one:", options, key=f"q{q_num}", index=None)
                else:
                    answers[q_num] = st.text_area("Your answer:", key=f"q{q_num}")

        free_text_end = st.text_area("✨ Anything else you'd like your therapist to know?")
        submitted = st.form_submit_button("🚀 Submit My Preferences")

        if submitted:
            if not user_name or not user_email:
                st.error("⚠️ Please enter your name and email.")
            else:
                user_id = save_user_preferences(user_name, user_email, free_text_intro, free_text_end)
                save_user_mcq_answers(user_id, answers)
                st.session_state["user_submitted"] = True

        if st.session_state.get("user_submitted", False):
            st.success("✅ Your preferences have been saved!")

            _, col2, _ = st.columns([1, 2, 1])
            with col2:
                lottie_json = load_lottiefile("animations/mental_wellbeing.json")
                st_lottie(lottie_json, height=250, key="mental_wellbeing")
                st.markdown(
                    """
                    <div style="text-align:center; margin-top:-10px;">
                        <h3 style="color:#2d046e;">🌱 Thank you for trusting us!</h3>
                        <p style="font-size:16px; color:#555;">
                            Your preferences will help us match you with the right therapist.  
                            You’ve already taken the first step towards better mental health 💜  
                        </p>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

# ---------------- THERAPIST FLOW ----------------
elif role == "Therapist":
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
            if not (name and email and gender and religious_belief and practice_location and languages and session_modes and charge):
                st.error("⚠️ Please fill in all fields before proceeding.")
            else:
                response = supabase.table("therapists").upsert({
                    "name": name,
                    "email": email,
                    "gender": gender,
                    "age": age,
                    "religious_belief": religious_belief,
                    "practice_location": practice_location,
                    "languages": [lang.strip() for lang in languages.split(",")],
                    "session_modes": session_modes,
                    "charge": charge
                }, on_conflict="email").execute()

                therapist_id = response.data[0]["id"]
                st.session_state["therapist_id"] = therapist_id
                st.success("✅ Basic information saved!")

    # --- Step 2: Therapist MCQs ---
    if "therapist_id" in st.session_state:
        st.subheader("🧾 Step 2: Answer Therapist MCQs")
        st.info("💜 These questions help us understand your therapeutic style and approach. Please answer honestly — it takes about 5 minutes.")

        def fetch_therapist_mcqs():
            response = supabase.table("questions").select(
                "id, question_number, question_text, options"
            ).eq("target", "therapist").order("question_number").execute()
            return response.data

        mcqs = fetch_therapist_mcqs()
        answers = {}

        with st.form("therapist_mcq_form"):
            for mcq in mcqs:
                q_num = mcq["question_number"]
                q_text = mcq["question_text"]
                options = mcq.get("options")

                with st.expander(f"Q{q_num}: {q_text}", expanded=False):
                    if options:
                        if isinstance(options, str):
                            try:
                                options = json.loads(options)
                            except:
                                options = [options]

                        if "select all" in q_text.lower() or "multiple" in q_text.lower():
                            answers[q_num] = st.multiselect("Select all that apply:", options, key=f"tq{q_num}")
                        else:
                            answers[q_num] = st.radio("Choose one:", options, key=f"tq{q_num}", index=None)
                    else:
                        answers[q_num] = st.text_area("Your answer:", key=f"tq{q_num}_text")

            submitted = st.form_submit_button("🚀 Submit My Answers")

            if submitted:
                if not answers:
                    st.warning("⚠️ Please answer at least one question.")
                else:
                    try:
                        for q_num, ans in answers.items():
                            q_lookup = supabase.table("questions").select("id").eq("question_number", q_num).execute()
                            if q_lookup.data:
                                question_id = q_lookup.data[0]["id"]
                                supabase.table("answers").insert({
                                    "user_id": st.session_state["therapist_id"],
                                    "question_id": question_id,
                                    "answer": json.dumps(ans) if isinstance(ans, list) else str(ans)
                                }).execute()

                        st.success("✅ All your MCQ answers have been submitted!")
                        st.session_state["therapist_all_submitted"] = True
                        st.balloons()
                        st.rerun()

                    except Exception as e:
                        st.error(f"⚠️ Error saving your responses: {e}")
