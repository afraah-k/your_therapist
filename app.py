import streamlit as st
import json
import os
from dotenv import load_dotenv
from supabase import create_client, Client
import warnings
from streamlit_lottie import st_lottie
import requests
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

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
    response = supabase.table("users").upsert({
        "name": user_name,
        "email": user_email,
        "role": "user"
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

    supabase.table("preferences").upsert({
        "user_id": user_id,
        "free_text": combined_free_text
    }).execute()

    return user_id

# --- Save MCQ answers ---
def save_user_mcq_answers(user_id, answers_dict):
    for q_num, ans in answers_dict.items():
        q_lookup = supabase.table("questions").select("id").eq("question_number", q_num).execute()
        if q_lookup.data:
            question_id = q_lookup.data[0]["id"]
            supabase.table("answers").insert({
                "user_id": user_id,
                "question_id": question_id,
                "answer": json.dumps(ans) if isinstance(ans, (list, dict)) else str(ans)
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
                if q_num == 28:
                    st.markdown("⭐ **Please rate how true each statement feels for you (1 = Not at all true, 5 = Completely true):**")
                    if isinstance(options, str):
                        try:
                            options = json.loads(options)
                        except:
                            options = [options]
                    answers[q_num] = {}
                    for i, statement in enumerate(options, start=1):
                        answers[q_num][statement] = st.slider(
                            f"{statement}", 1, 5, 3, key=f"q{q_num}_slider_{i}"
                        )

                elif options:
                    if isinstance(options, str):
                        try:
                            options = json.loads(options)
                        except:
                            options = [options]
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
                st.session_state["user_id"] = user_id

        if st.session_state.get("user_submitted", False):
            st.success("✅ Your preferences have been saved!")
            _, col2, _ = st.columns([1, 2, 1])
            with col2:
                lottie_json = load_lottiefile("animations/mental_wellbeing.json")
                st_lottie(lottie_json, height=250, key="user_success")

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

            st.markdown(
                """
                <div style="text-align:center;">
                    <h3 style="color:#2d046e;">📝 We'd love your feedback!</h3>
                    <p style="font-size:16px; color:#555;">
                        Help us make this platform even better.  
                        Please take a minute to share your thoughts below 👇
                    </p>
                    <a href="https://forms.gle/de6JqeAo6mrM1iYv5" target="_blank"
                    style="background-color:#8ec5fc; color:white; padding:10px 20px;
                    border-radius:10px; text-decoration:none; font-weight:600;">
                    💜 Give Feedback
                    </a>
                </div>
                """,
                unsafe_allow_html=True
            )

# ---------------- THERAPIST FLOW ----------------
elif role == "Therapist":
    st.markdown(
        """
        <div style="background: linear-gradient(135deg, #ffecd2, #fcb69f);
        padding:25px; border-radius:15px; text-align:center; margin-bottom:20px;">
        <h2 style="color:#6a1b9a;">🎙️ Therapist Portal</h2>
        <p>Step 1: Provide your basic information.  
        Step 2: Answer your professional MCQs 💭</p>
        </div>
        """,
        unsafe_allow_html=True
    )

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

                # ✅ Step 1: Ensure therapist also exists in `users` table
                user_response = supabase.table("users").upsert({
                    "name": name,
                    "email": email,
                    "role": "therapist"
                }).execute()

                if user_response.data:
                    user_id = user_response.data[0]["id"]
                else:
                    existing = supabase.table("users").select("id").eq("email", email).execute()
                    user_id = existing.data[0]["id"]

                # ✅ Store this user_id for later use in answers
                st.session_state["therapist_user_id"] = user_id

                # ✅ Step 2: Insert into `therapist_profiles` linked to user_id
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

    # ✅ Step 2: Therapist MCQs (only if Step 1 completed)
    if "therapist_user_id" in st.session_state:
        st.subheader("🧾 Step 2: Answer Therapist MCQs")
        st.info("💜 Please answer these questions honestly — it takes about 5 minutes.")

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
                q_display = q_num - 100  # show question numbers starting from 1
                q_text = mcq["question_text"]
                options = mcq.get("options")

                with st.expander(f"Q{q_display}: {q_text}", expanded=False):
                    if q_num == 101:
                        answers[q_num] = st.text_area("Your areas of specialization:", key=f"tq{q_num}_text")

                    elif q_num in [108, 116]:
                        st.markdown("⭐ **Please rate how true each statement feels for you (1 = Not at all, 5 = Very much):**")
                        if isinstance(options, str):
                            try:
                                options = json.loads(options)
                            except:
                                options = [options]
                        answers[q_num] = {}
                        for i, statement in enumerate(options, start=1):
                            answers[q_num][statement] = st.slider(f"{statement}", 1, 5, 3, key=f"tq{q_num}_slider_{i}")

                    elif q_num == 119:
                        answers[q_num] = st.text_area("(Optional) Your thoughts:", key=f"tq{q_num}_optional")

                    elif options:
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
                try:
                    for q_num, ans in answers.items():
                        if q_num == 119 and (not ans or str(ans).strip() == ""):
                            continue

                        q_lookup = supabase.table("questions").select("id").eq("question_number", q_num).execute()
                        if q_lookup.data:
                            question_id = q_lookup.data[0]["id"]

                            supabase.table("answers").insert({
                                "user_id": st.session_state["therapist_user_id"],  # ✅ now defined properly
                                "question_id": question_id,
                                "answer": json.dumps(ans) if isinstance(ans, (list, dict)) else str(ans)
                            }).execute()

                    # 🎬 Therapist success animation
                    st.success("✅ All your MCQ answers have been submitted successfully!")
                    _, col2, _ = st.columns([1, 2, 1])
                    with col2:
                        confetti_json = load_lottiefile("animations/success_confetti.json")
                        st_lottie(confetti_json, height=250, key="therapist_confetti")
                        st.markdown(
                            """
                            <div style="text-align:center; margin-top:-10px;">
                                <h2 style="color:#6a1b9a;">🎉 You’ve successfully completed your interview!</h2>
                                <h3 style="font-size:18px; color:#555;">
                                    Congratulations for taking a step towards making therapy easy and accessible. 🌱  
                                </h3>
                            </div>
                            """,
                            unsafe_allow_html=True
                        )
                            # 💬 Feedback form link for therapists
                        st.markdown("---")
                        st.markdown(
                            """
                            <div style="text-align:center;">
                                <h3 style="color:#6a1b9a;">📝 We value your feedback!</h3>
                                <p style="font-size:16px; color:#555;">
                                    Your insights help us make the matching process smarter and more effective.  
                                    Please take a minute to share your thoughts below 👇
                                </p>
                                <a href="https://forms.gle/5txFuYQ6Gn4b9GMj6" target="_blank"
                                style="background-color:#fcb69f; color:white; padding:10px 20px;
                                border-radius:10px; text-decoration:none; font-weight:600;">
                                💜 Give Feedback
                                </a>
                            </div>
                            """,
                            unsafe_allow_html=True
                        )

                    st.session_state["therapist_all_submitted"] = True

                except Exception as e:
                    st.error(f"⚠️ Error saving your responses: {e}")


