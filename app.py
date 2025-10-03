import streamlit as st
import psycopg2
import json
import os
from dotenv import load_dotenv
from supabase import create_client, Client
import warnings
from streamlit_lottie import st_lottie
import requests

# --- Suppress warnings ---
warnings.filterwarnings("ignore", category=UserWarning, module="ctranslate2")

# --- Load environment variables once ---
load_dotenv()

# Get credentials (Streamlit Secrets first, then .env)
SUPABASE_URL = st.secrets.get("SUPABASE_URL") or os.getenv("SUPABASE_URL")
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY") or os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    st.error("Supabase credentials are missing! Please set them in Streamlit secrets or .env.")
else:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# --- Streamlit Page Config ---
st.set_page_config(page_title="Your Therapist", page_icon="💜", layout="wide")

# --- Helper for Lottie animations ---
def load_lottiefile(filepath: str):
    with open(filepath, "r") as f:
        return json.load(f)

# --- DB Connection ---
try:
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        port=os.getenv("DB_PORT")
    )
    st.success("✅ Connected to Supabase database")
except Exception as e:
    st.error(f"Database connection failed: {e}")

# --- Fetch MCQs ---
def fetch_mcqs():
    cur = conn.cursor()
    cur.execute("SELECT id, question_number, question_text, category, options FROM user_mcqs_v2 ORDER BY question_number;")
    rows = cur.fetchall()
    cur.close()
    return rows

# --- Save User Preferences (only free text now) ---
def save_user_preferences(user_name, user_email, free_text_intro, free_text_end):
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO users (name, email)
        VALUES (%s, %s)
        ON CONFLICT (email) DO NOTHING
        RETURNING id;
    """, (user_name, user_email))

    user_row = cur.fetchone()
    if user_row:
        user_id = user_row[0]
    else:
        cur.execute("SELECT id FROM users WHERE email=%s;", (user_email,))
        user_id = cur.fetchone()[0]

    combined_free_text = ""
    if free_text_intro:
        combined_free_text += f"Intro: {free_text_intro}\n\n"
    if free_text_end:
        combined_free_text += f"Additional: {free_text_end}"

    cur.execute("""
        INSERT INTO user_preferences (user_id, free_text_preference)
        VALUES (%s, %s);
    """, (user_id, combined_free_text))

    conn.commit()
    cur.close()
    return user_id

# --- Save MCQ answers into relational table ---
def save_user_mcq_answers(user_id, answers_dict):
    cur = conn.cursor()
    for q_num, ans in answers_dict.items():
        cur.execute("SELECT id FROM user_mcqs_v2 WHERE question_number = %s;", (q_num,))
        question_row = cur.fetchone()
        if question_row:
            question_id = question_row[0]
            cur.execute("""
                INSERT INTO user_mcq_answers (user_id, question_id, answer)
                VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING;
            """, (user_id, question_id, str(ans)))
    conn.commit()
    cur.close()

# --- Fetch therapist questions ---
def fetch_therapist_questions():
    cur = conn.cursor()
    cur.execute("SELECT id, question_number, question_text FROM therapist_questions ORDER BY question_number;")
    rows = cur.fetchall()
    cur.close()
    return rows

# --- UI ---
st.title("(❁´◡`❁) Welcome to Your Therapist")

role = st.radio("Are you here as a...", ["User / Client", "Therapist"], horizontal=True)

# Reset session state when switching roles
if "last_role" in st.session_state and st.session_state["last_role"] != role:
    for key in list(st.session_state.keys()):
        if key not in ["last_role"]:
            del st.session_state[key]
if "last_role" not in st.session_state:
    st.session_state["last_role"] = role
else:
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

        for q_id, q_num, q_text, category, options in mcqs:
            with st.expander(f"Q{q_num}: {q_text}"):
                if options:
                    # Ensure options is a proper list (not JSON string)
                    if isinstance(options, str):
                        try:
                            options = json.loads(options)
                        except:
                            options = [options]

                    if q_num in [1, 12, 18]:
                        answers[q_num] = st.multiselect("Select all that apply:", options, key=f"q{q_num}")
                    elif q_num == 26:  # Special handling for Languages
                        choice_list = st.multiselect("Select all that apply:", options, key=f"q{q_num}")
                        # If "Other" or "Indigenous specify" selected → add text input
                        if any("specify" in c.lower() for c in choice_list):
                            custom_lang = st.text_input("Please specify language(s):", key=f"q{q_num}_other")
                            if custom_lang.strip():
                                choice_list.append(custom_lang)
                        answers[q_num] = choice_list
                    else:
                        choice = st.radio("Choose one:", options, key=f"q{q_num}", index=None)
                        answers[q_num] = choice


                        # Special handling for Q26 (Other/Indigenous specify)
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
                st.session_state["user_submitted"] = True  # set a flag

        # After form (outside it), check session state
        if st.session_state.get("user_submitted", False):
            st.success("✅ Your preferences have been saved!")

            _, col2, _ = st.columns([1, 2, 1])
            with col2:
                lottie_json = load_lottiefile(
                    r"C:\Users\afrah khan\Major_Project\your_therapist_prototype\Mental Wellbeing - Seek Help.json"
                )
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

    # If already submitted
    if st.session_state["therapist_all_submitted"]:
        _, col2, _ = st.columns([1, 2, 1])
        with col2:
            confetti_json = load_lottiefile(
                r"C:\Users\afrah khan\Major_Project\your_therapist_prototype\success confetti.json"
            )
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

    # Normal flow
    st.markdown(
        """
        <div style="background: linear-gradient(135deg, #ffecd2, #fcb69f);
        padding:25px; border-radius:15px; text-align:center; margin-bottom:20px;">
        <h2 style="color:#6a1b9a;">🎙️ Therapist Interview Portal</h2>
        <p>Step 1: Provide your demographic details.  
        Step 2: Record OR type your answers to interview questions 🧠</p>
        </div>
        """,
        unsafe_allow_html=True
    )

    # Step 1: Info
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
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO therapists (name, email, gender, age, religious_belief, practice_location, languages, session_modes, charge)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (email) DO UPDATE SET
                        name = EXCLUDED.name,
                        gender = EXCLUDED.gender,
                        age = EXCLUDED.age,
                        religious_belief = EXCLUDED.religious_belief,
                        practice_location = EXCLUDED.practice_location,
                        languages = EXCLUDED.languages,
                        session_modes = EXCLUDED.session_modes,
                        charge = EXCLUDED.charge
                    RETURNING id;
                """, (name, email, gender, age, religious_belief, practice_location,
                      languages.split(","), session_modes, charge))
                therapist_id = cur.fetchone()[0]
                conn.commit()
                cur.close()
                st.success("✅ Basic information saved!")
                st.session_state["therapist_id"] = therapist_id

    # Step 2: Questions
    if "therapist_id" in st.session_state:
        st.subheader("🎤 Step 2: Record or type your answers")

        MAX_FILE_SIZE_MB = 10
        MAX_FILE_SIZE = MAX_FILE_SIZE_MB * 1024 * 1024

        questions = fetch_therapist_questions()
        section2_questions = [q for q in questions if q[1] >= 1]

        for q_id, _, _ in section2_questions:
            if f"answered_{q_id}" not in st.session_state:
                st.session_state[f"answered_{q_id}"] = False
            if f"text_{q_id}" not in st.session_state:
                st.session_state[f"text_{q_id}"] = ""

        for idx, (q_id, q_num, q_text) in enumerate(section2_questions, start=1):
            status = "✅ Answered" if st.session_state[f"answered_{q_id}"] else "⚪ Not started"
            with st.expander(f"Q{idx}: {q_text} ({status})"):
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
                if st.button(f"📥 Submit Text Answer for Q{idx}", key=f"submit_text_{q_id}"):
                    if text_input.strip():
                        st.session_state[f"text_{q_id}"] = text_input.strip()
                        st.session_state[f"audio_{q_id}"] = None  
                        st.session_state[f"answered_{q_id}"] = True
                        st.success("✅ Answer recorded!")
                    else:
                        st.warning("⚠️ Please enter some text before submitting.")

                if st.button(f"🔄 Clear Answer Q{idx}", key=f"clear_{q_id}"):
                    st.session_state[f"audio_{q_id}"] = None
                    st.session_state[f"text_{q_id}"] = ""
                    st.session_state[f"answered_{q_id}"] = False
                    st.warning("Answer cleared. Please record or type again.")

        if st.button("🚀 Submit All Answers"):
            try:
                cur = conn.cursor()
                for q_id, q_num, q_text in section2_questions:
                    audio_bytes = st.session_state.get(f"audio_{q_id}")
                    text_answer = st.session_state.get(f"text_{q_id}")

                    if audio_bytes or text_answer:
                        audio_url = None
                        if audio_bytes:
                            file_name = f"therapist_q{q_num}_recorded.wav"
                            file_path = f"{st.session_state['therapist_id']}/q{q_num}_{file_name}"

                            supabase.storage.from_("therapist-audio").upload(
                                file_path, audio_bytes, {"content-type": "audio/wav"}, upsert=True
                            )
                            audio_url = f"{SUPABASE_URL}/storage/v1/object/public/therapist-audio/{file_path}"

                        cur.execute("""
                            INSERT INTO therapist_answers (therapist_id, question_id, answer_text, audio_url)
                            VALUES (%s, %s, %s, %s)
                            ON CONFLICT (therapist_id, question_id) 
                            DO UPDATE SET answer_text = EXCLUDED.answer_text,
                                          audio_url = EXCLUDED.audio_url;
                        """, (st.session_state["therapist_id"], q_id, text_answer if text_answer else None, audio_url))

                conn.commit()
                cur.close()

                st.session_state["therapist_all_submitted"] = True
                st.rerun()

            except Exception as e:
                st.error(f"⚠️ Error during final submit: {e}")
