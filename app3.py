import streamlit as st
import pandas as pd
import fitz  # PyMuPDF
import plotly.express as px
from groq import Groq
import json
import os
import re
import requests
import xml.etree.ElementTree as ET
from io import BytesIO
from docx import Document as DocxDocument
 

# ⚙️ Page Config
# -------------------------------
st.set_page_config(page_title="DocSense AI Chatbot", layout="wide")
# st.title("DocSense AI Chatbot")
st.markdown("""
<style>
.center-title {
    text-align: center;
    font-size: 46px;
    font-weight: 700;
    margin-top: 20px;
}
</style>
<div class="center-title">
    DocSense AI Chatbot
</div>
""", unsafe_allow_html=True)

st.markdown("""
<div style="text-align:center; color: gray; font-size:18px;">
Ask questions → Get insights + visualizations
</div>
""", unsafe_allow_html=True)

# st.caption("Ask questions → Get insights + visualizations")
 
# 🌐 Groq API Configuration
# -------------------------------
GROQ_API_KEY = st.secrets["API_KEY"]
os.environ["API_KEY"] = GROQ_API_KEY
client = Groq(api_key=GROQ_API_KEY)
 
# SESSION STATE INIT
# -------------------------------
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "latest_answer" not in st.session_state:
    st.session_state.latest_answer = ""
if "uploaded_text" not in st.session_state:
    st.session_state.uploaded_text = ""
if "dataframes" not in st.session_state:
    st.session_state.dataframes = []
if "selected_question_index" not in st.session_state:
    st.session_state.selected_question_index = None
 
# Helper: Enhanced Sanitization
# -------------------------------
def sanitize_text(text):
    """Remove HTML tags, Markdown symbols, and normalize whitespace."""
    if not text:
        return ""
    # Remove HTML tags
    text = re.sub(r'<[^>]*>', '', text)
    # Remove Markdown symbols like **, __, #, *, >, ~, -
    text = re.sub(r'[*_#>`~\-]', '', text)
    # Normalize whitespace
    return text.strip()
 
# Helper: Fix DataFrame for Streamlit Arrow Compatibility
# -------------------------------
def fix_arrow_df(df: pd.DataFrame):
    for col in df.columns:
        if df[col].dtype == "object":
            df[col] = df[col].astype(str)
    return df
 
# SIDEBAR: Chat History
# -------------------------------
st.sidebar.header("Chat History")
for i, entry in enumerate(st.session_state.chat_history):
    if st.sidebar.button(f"Q{i+1}: {entry['question']}", key=f"btn_{i}"):
        st.session_state.selected_question_index = i
if st.session_state.selected_question_index is not None:
    selected = st.session_state.chat_history[st.session_state.selected_question_index]
    st.sidebar.markdown("### Answer:")
    st.sidebar.write(sanitize_text(selected["answer"]))
 
# 📂 Load Files from S3
# -------------------------------
S3_BUCKET = "hr-buddy-genai"   # ← CHANGE THIS
BASE_URL = f"https://{S3_BUCKET}.s3.amazonaws.com"
# -----------------------------
def load_s3_public_files():
    """Load all PDFs / CSVs / DOCX from a PUBLIC S3 bucket."""
    list_url = f"{BASE_URL}?list-type=2"

    response = requests.get(list_url)
    if response.status_code != 200:
        st.error(f"❌ Cannot list S3 bucket: {S3_BUCKET}. Make sure it is PUBLIC.")
        st.stop()

    root = ET.fromstring(response.text)
    keys = [
        elem.text for elem in root.findall(".//{http://s3.amazonaws.com/doc/2006-03-01/}Key")
        if elem.text and not elem.text.endswith("/")
    ]

    if not keys:
        st.error("❌ No files found in S3 bucket.")
        st.stop()

    all_text = ""
    dfs = []

    for key in keys:
        file_url = f"{BASE_URL}/{key}"
        file_data = requests.get(file_url)

        if file_data.status_code != 200:
            st.warning(f"⚠ Failed to download: {key}")
            continue

        file_bytes = BytesIO(file_data.content)

        # ---- PDF ----
        if key.lower().endswith(".pdf"):
            try:
                pdf = fitz.open(stream=file_bytes.read(), filetype="pdf")
                text = "".join(page.get_text("text") for page in pdf)
                all_text += f"\n\n### From {key}:\n{text}"
            except Exception as e:
                st.warning(f"⚠ Cannot read PDF {key}: {e}")

        # ---- CSV ----
        elif key.lower().endswith(".csv"):
            try:
                df = pd.read_csv(BytesIO(file_data.content))
                dfs.append(df)
                all_text += f"\n\n### From {key}:\n{df.to_string(index=False)}"
            except Exception as e:
                st.warning(f"⚠ Cannot read CSV {key}: {e}")

        # ---- DOCX/DOC ----
        elif key.lower().endswith(".docx") or key.lower().endswith(".doc"):
            try:
                doc = DocxDocument(file_bytes)
                text = "\n".join(p.text for p in doc.paragraphs)
                all_text += f"\n\n### From {key}:\n{text}"
            except Exception as e:
                st.warning(f"⚠ Cannot read DOC/DOCX {key}: {e}")

    return all_text, dfs

# 🟦 Load automatically at startup
all_text, dfs = load_s3_public_files()

st.session_state.uploaded_text = all_text
st.session_state.dataframes = dfs
st.success("✅ Loaded all S3 documents successfully!")

# UPLOAD_DIR = "uploads"
# if not os.path.exists(UPLOAD_DIR):
#     st.error("Uploads directory not found. Create an 'uploads' folder.")
#     st.stop()
# existing_files = os.listdir(UPLOAD_DIR)
# if not existing_files:
#     st.error("No files found in uploads folder.")
#     st.stop()
 
# all_text = ""
# dfs = []
# for file_name in existing_files:
#     file_path = os.path.join(UPLOAD_DIR, file_name)
#     if file_name.endswith(".pdf"):
#         pdf = fitz.open(file_path)
#         text = "".join(page.get_text("text") for page in pdf)
#         all_text += f"\n\n### From {file_name}:\n{text}"
#     elif file_name.endswith(".csv"):
#         df = pd.read_csv(file_path)
#         dfs.append(df)
#         all_text += f"\n\n### From {file_name}:\n{df.to_string(index=False)}"
 
# st.session_state.uploaded_text = all_text
# st.session_state.dataframes = dfs
 
# -------------------------------
# 🎨 Chat Interface Styling
# -------------------------------
st.markdown("""
<style>
.chat-bubble-user, .chat-bubble-ai {
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 16px;
    line-height: 1.5;
    white-space: pre-wrap;
    word-wrap: break-word;
}
.chat-bubble-user {
    background-color: #0078ff;
    color: white;
    padding: 10px 14px;
    border-radius: 12px;
    margin: 5px 0px;
    width: fit-content;
    max-width: 80%;
    align-self: flex-end;
}
.chat-bubble-ai {
    background-color: #f1f1f1;
    color: #333;
    padding: 10px 14px;
    border-radius: 12px;
    margin: 5px 0px;
    width: fit-content;
    max-width: 80%;
    align-self: flex-start;
}
.chat-container {
    display: flex;
    flex-direction: column;
}
</style>
""", unsafe_allow_html=True)
 
# -------------------------------
# 💬 Question Input
# -------------------------------
question = st.chat_input("💬 Ask a question about your data...")
if question and (not st.session_state.chat_history or st.session_state.chat_history[-1]["question"] != question):
    if not st.session_state.uploaded_text:
        st.warning("No data available in uploads folder.")
        st.stop()
 
    with st.spinner("Analyzing your files..."):
        context = st.session_state.uploaded_text[:12000]
        prompt = f"""
You are a financial analysis assistant.
You are given ONLY the following data (in text, CSV, or extracted tables) and a user question.
Do NOT use any information outside this data.
If the answer cannot be found in the data, respond with: "The information is not available in the uploaded files."
 
Your response MUST have ONLY these two blocks:
<answer>
...clean explanation with no numbers modified...
</answer>

<json>
...valid JSON only...
</json>

 JSON RULES (IMPORTANT):
- JSON MUST be valid and parseable by Python json.loads().
- No comments, no trailing commas, no text outside JSON.
- Keys MUST be simple strings without spaces.
- All numbers MUST be plain integers (e.g., 14015150), NOT strings ("14,015,150").
- NEVER output commas inside numbers.
- NEVER output formatted numbers like "14.0M" or "$57M".
- If no chart is needed, output: {{}}

Example JSON format:
<json>
{{
  "chart_type": "bar",
  "col1": [2023, 2024],
  "values": [5732599, 14015150]
}}
</json>

NEVER wrap numbers in quotes unless they are real text labels.

DATA:
{context}
 
QUESTION:
{question}
"""
 
        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": "Strictly use uploaded files only."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2
            )
            raw_answer = response.choices[0].message.content 
            # Extract clean answer
            a_start = raw_answer.find("<answer>")
            a_end = raw_answer.find("</answer>")
            clean_answer = raw_answer[a_start+8:a_end].strip() if a_start != -1 else raw_answer
 
        except Exception as e:
            st.error(f"Groq API error: {e}")
            st.stop()
 
        # Save sanitized question and answer
        st.session_state.chat_history.append({
            "question": sanitize_text(question),
            "answer": sanitize_text(clean_answer),
            "raw_answer": raw_answer
        })
 
# -------------------------------
# 💬 Chat Display
# -------------------------------
st.markdown("<div class='chat-container'>", unsafe_allow_html=True)
for chat in st.session_state.chat_history:
    st.markdown(f"<div class='chat-bubble-user'>{sanitize_text(chat['question'])}</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='chat-bubble-ai'>{sanitize_text(chat['answer'])}</div>", unsafe_allow_html=True)
st.markdown("</div>", unsafe_allow_html=True)
 
# -------------------------------
# 📊 Visualization
# -------------------------------
if st.session_state.chat_history:
    latest_raw = st.session_state.chat_history[-1]["raw_answer"]
    json_start = latest_raw.find("<json>")
    json_end = latest_raw.find("</json>")
    if json_start != -1 and json_end != -1:
        try:
            json_str = latest_raw[json_start + 6:json_end].strip()
            data = json.loads(json_str)
            chart_type = data.pop("chart_type", "line").lower()
            df = pd.DataFrame(data)
            df = fix_arrow_df(df)
            xcol = df.columns[0]
            df[xcol] = df[xcol].astype(str)
            st.subheader("📊 Visualization")
            st.dataframe(df)
 
            # Plot Selection
            if chart_type == "bar":
                fig = px.bar(df, x=xcol, y=df.columns[1:], barmode="group")
            elif chart_type == "pie":
                fig = px.pie(df, names=xcol, values=df.columns[1])
            elif chart_type == "scatter":
                fig = px.scatter(df, x=xcol, y=df.columns[1])
            elif chart_type == "area":
                fig = px.area(df, x=df.xcol, y=df.columns[1:])
            else:
                fig = px.line(df, x=xcol, y=df.columns[1:], markers=True)
 
            fig.update_xaxes(type="category")
            st.plotly_chart(fig, use_container_width=True)
        except Exception as e:
            pass
    else:
        # CSV fallback
        if st.session_state.dataframes:
            df = st.session_state.dataframes[0]
            df = fix_arrow_df(df)
            xcol = df.columns[0]
            df[xcol] = df[xcol].astype(str)
            numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
            if numeric_cols:
                st.subheader("📊 CSV Data Visualization")
                fig = px.line(df, x=xcol, y=numeric_cols, markers=True)
                st.plotly_chart(fig, use_container_width=True)
