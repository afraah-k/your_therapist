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

# Get credentials (Streamlit Secrets first, then .env)
SUPABASE_URL = st.secrets.get("SUPABASE_URL") or os.getenv("SUPABASE_URL")
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY") or os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    st.error("Supabase credentials are missing! Please set them in Streamlit secrets or .env.")
    st.stop()

# Create Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Test connection ---
try:
    # Just try selecting 1 row from a small table
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

# --- Fetch MCQs ---
def fetch_mcqs():
    response = supabase.table("user_mcqs_v2").select(
        "id, question_number, question_text, category, options"
    ).order("question_number").execute()
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
        q_lookup = supabase.table("user_mcqs_v2").select("id").eq("question_number", q_num).execute()
        if q_lookup.data:
            question_id = q_lookup.data[0]["id"]
            supabase.table("user_mcq_answers").insert({
                "user_id": user_id,
                "question_id": question_id,
                "answer": str(ans)
            }).execute()

# --- Fetch therapist questions ---
def fetch_therapist_questions():
    response = supabase.table("therapist_questions").select(
        "id, question_number, question_text"
    ).order("question_number").execute()
    return response.data

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
            q_id = mcq["id"]
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

                    if q_num in [1, 12, 18]:
                        answers[q_num] = st.multiselect("Select all that apply:", options, key=f"q{q_num}")
                    elif q_num == 26:
                        choice_list = st.multiselect("Select all that apply:", options, key=f"q{q_num}")
                        if any("specify" in c.lower() for c in choice_list):
                            custom_lang = st.text_input("Please specify language(s):", key=f"q{q_num}_other")
                            if custom_lang.strip():
                                choice_list.append(custom_lang)
                        answers[q_num] = choice_list
                    else:
                        choice = st.radio("Choose one:", options, key=f"q{q_num}", index=None)
                        answers[q_num] = choice
                        if q_num == 26 and choice and "specify" in choice.lower():
                            custom_lang = st.text_input("Please specify language:", key=f"q{q_num}_other")
                            if custom_lang.strip():
                                answers[q_num] = custom_lang
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
                # Replace with online Lottie animation instead of local path
                lottie_json = requests.get("https://lottie.host/ef87f43a.json").json()
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
    if "therapist_all_submitted" not in st.session_state:
        st.session_state["therapist_all_submitted"] = False

    if st.session_state["therapist_all_submitted"]:
        _, col2, _ = st.columns([1, 2, 1])
        with col2:
            # Replace with online Lottie animation
            confetti_json = requests.get("https://lottie.host/5e8c77.json").json()
            st_lottie(confetti_json, height=250, key="confetti")
            st.markdown(
                """
                <div style="text-align:center; margin-top:-10px;">
                    <h3 style="color:#444;">You’ve successfully completed your interview 💜</h3>
                    <p style="font-size:18px; color:#555;">
                        Congratulations for taking a step towards making therapy easy and accessible. 🌱  
                    </p>
                    <p style="font-size:16px; color:#777;">
                        Our team will now review your answers and include you in the platform.  
                        We’ll notify you once everything is live! 🚀
                    </p>
                </div>
                """,
                unsafe_allow_html=True
            )
            if st.button("🏠 Back to Home"):
                for key in list(st.session_state.keys()):
                    del st.session_state[key]
                st.rerun()
            st.stop()

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

    if "therapist_id" in st.session_state:
        st.subheader("🎤 Step 2: Record or type your answers")

        MAX_FILE_SIZE_MB = 10
        MAX_FILE_SIZE = MAX_FILE_SIZE_MB * 1024 * 1024

        questions = fetch_therapist_questions()

        for q in questions:
            q_id = q["id"]
            q_num = q["question_number"]
            q_text = q["question_text"]

            if f"answered_{q_id}" not in st.session_state:
                st.session_state[f"answered_{q_id}"] = False
            if f"text_{q_id}" not in st.session_state:
                st.session_state[f"text_{q_id}"] = ""

            with st.expander(f"Q{q_num}: {q_text}"):
                if f"audio_{q_id}" not in st.session_state:
                    st.session_state[f"audio_{q_id}"] = None

                recorded_audio = st.audio_input("🎤 Record your answer", key=f"rec_{q_id}")
                if recorded_audio:
                    audio_bytes = recorded_audio.getvalue()
                    if len(audio_bytes) > MAX_FILE_SIZE:
                        st.error(f"⚠️ File too large! Max {MAX_FILE_SIZE_MB} MB allowed.")
                    else:
                        st.audio(audio_bytes, format="audio/wav")
                        st.session_state[f"audio_{q_id}"] = audio_bytes
                        st.session_state[f"text_{q_id}"] = ""  
                        st.session_state[f"answered_{q_id}"] = True
                        st.success("✅ Recording captured!")

                text_input = st.text_area("✍️ Or type your answer here:", value=st.session_state[f"text_{q_id}"], key=f"textbox_{q_id}")
                if st.button(f"📥 Submit Text Answer for Q{q_num}", key=f"submit_text_{q_id}"):
                    if text_input.strip():
                        st.session_state[f"text_{q_id}"] = text_input.strip()
                        st.session_state[f"audio_{q_id}"] = None  
                        st.session_state[f"answered_{q_id}"] = True
                        st.success("✅ Answer recorded!")
                    else:
                        st.warning("⚠️ Please enter some text before submitting.")

                if st.button(f"🔄 Clear Answer Q{q_num}", key=f"clear_{q_id}"):
                    st.session_state[f"audio_{q_id}"] = None
                    st.session_state[f"text_{q_id}"] = ""
                    st.session_state[f"answered_{q_id}"] = False
                    st.warning("Answer cleared. Please record or type again.")

        if st.button("🚀 Submit All Answers"):
            try:
                for q in questions:
                    q_id = q["id"]
                    q_num = q["question_number"]
                    q_text = q["question_text"]

                    audio_bytes = st.session_state.get(f"audio_{q_id}")
                    text_answer = st.session_state.get(f"text_{q_id}")
                    audio_url = None

                    if audio_bytes:
                        file_name = f"therapist_q{q_num}_recorded.wav"
                        file_path = f"{st.session_state['therapist_id']}/q{q_num}_{file_name}"

                        supabase.storage.from_("therapist-audio").upload(
                            file_path, audio_bytes, {"content-type": "audio/wav"}, upsert=True
                        )
                        audio_url = f"{SUPABASE_URL}/storage/v1/object/public/therapist-audio/{file_path}"

                    if audio_bytes or text_answer:
                        supabase.table("therapist_answers").upsert({
                            "therapist_id": st.session_state["therapist_id"],
                            "question_id": q_id,
                            "answer_text": text_answer if text_answer else None,
                            "audio_url": audio_url
                        }, on_conflict=["therapist_id", "question_id"]).execute()

                st.session_state["therapist_all_submitted"] = True
                st.rerun()

            except Exception as e:
                st.error(f"⚠️ Error during final submit: {e}")

