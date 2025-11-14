import streamlit as st
import pandas as pd
import fitz
import plotly.express as px
from groq import Groq
from dotenv import load_dotenv
import json
import os
import requests
import xml.etree.ElementTree as ET
from io import BytesIO
import re
from unicodedata import normalize as unormalize
from docx import Document as DocxDocument

# ⚙️ Load environment variables
load_dotenv()


GROQ_API_KEY = st.secrets["API_KEY"]
os.environ["API_KEY"] = GROQ_API_KEY
client = Groq(api_key=GROQ_API_KEY)

GROQ_MODEL = "llama-3.3-70b-versatile"
# Safety checks
if not GROQ_API_KEY:
    st.error("❌ GROQ_API_KEY not found. Please set it in your .env file.")
    st.stop()
if not GROQ_MODEL:
    st.warning("⚠️ GROQ_MODEL not found. Using default: llama-3.3-70b-versatile")
    GROQ_MODEL = "llama-3.3-70b-versatile"

# ⚙️ Page Config
st.set_page_config(page_title="📊 Financial Chatbot", layout="wide")

# 🌐 Groq API Configuration
client = Groq(api_key=GROQ_API_KEY)

# SESSION STATE INIT
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "latest_answer" not in st.session_state:
    st.session_state.latest_answer = ""
if "selected_question_index" not in st.session_state:
    st.session_state.selected_question_index = None
if "uploaded_text" not in st.session_state:
    st.session_state.uploaded_text = ""
if "dataframes" not in st.session_state:
    st.session_state.dataframes = []

# SIDEBAR: Chat History
st.sidebar.header("Chat History")

for i, entry in enumerate(st.session_state.chat_history):
    if st.sidebar.button(f"Q{i+1}: {entry['question']}", key=f"btn_{i}"):
        st.session_state.selected_question_index = i

if st.session_state.selected_question_index is not None:
    selected_entry = st.session_state.chat_history[st.session_state.selected_question_index]
    st.sidebar.markdown("### Answer:")
    st.sidebar.write(selected_entry["answer"])

## 📂 Load Files from /uploads Directory

# UPLOAD_DIR = "uploads"
# if not os.path.exists(UPLOAD_DIR):
#     st.error("Uploads directory not found. Please create an 'uploads' folder and add files.")
#     st.stop()

# existing_files = os.listdir(UPLOAD_DIR)
# if not existing_files:
#     st.error("No files found in 'uploads' directory. Please add PDFs or CSVs manually.")
#     st.stop()

# # Parse files from uploads directory
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

BUCKET_NAME = st.secrets["s3_bucket"]
os.environ["s3_bucket"] = BUCKET_NAME
BASE_URL = f"https://{BUCKET_NAME}.s3.amazonaws.com"

def load_files_from_s3(bucket_url):
    all_text = ""
    dfs = []
    total_files = 0

    # Get list of ALL objects in bucket
    list_url = f"{bucket_url}?list-type=2"

    response = requests.get(list_url)
    if response.status_code != 200:
        st.error(f"❌ Failed to list S3 bucket {BUCKET_NAME}. Make sure it is public.")
        st.stop()

    # Parse XML list of keys
    root = ET.fromstring(response.text)
    keys = [elem.text for elem in root.findall(".//{http://s3.amazonaws.com/doc/2006-03-01/}Key")]

    if not keys:
        st.error("❌ No files found in the S3 bucket.")
        st.stop()

    for key in keys:
        if key.endswith("/"):  # Skip folder markers
            continue

        file_url = f"{bucket_url}/{key}"

        file_data = requests.get(file_url)
        if file_data.status_code != 200:
            st.warning(f"⚠ Failed to download {key}")
            continue

        file_bytes = BytesIO(file_data.content)

        # ---------------- PDF ----------------
        if key.lower().endswith(".pdf"):
            try:
                pdf = fitz.open(stream=file_bytes.read(), filetype="pdf")
                text = "".join(page.get_text("text") for page in pdf)
                all_text += f"\n\n### From {key}:\n{text}"
                total_files += 1
            except Exception as e:
                st.warning(f"⚠ Unable to read PDF {key}: {e}")

        # ---------------- CSV ----------------
        elif key.lower().endswith(".csv"):
            try:
                df = pd.read_csv(BytesIO(file_data.content))
                dfs.append(df)
                all_text += f"\n\n### From {key}:\n{df.to_string(index=False)}"
                total_files += 1
            except Exception as e:
                st.warning(f"⚠ Unable to read CSV {key}: {e}")

        elif key.lower().endswith(".docx") or key.lower().endswith(".doc"):
            try:
                doc = DocxDocument(BytesIO(file_data.content))
                # Extract paragraphs (ignores tables unless added below)
                paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
                text = "\n".join(paragraphs)
                all_text += f"\n\n### From {key}:\n{text}"
                total_files += 1
            except Exception as e:
                st.warning(f"⚠ Unable to read DOC/DOCX {key}: {e}")

    return all_text, dfs, total_files


# LOAD FROM S3
all_text, dfs, total_files = load_files_from_s3(BASE_URL)

if total_files == 0:
    st.error("❌ No usable PDF or CSV files found in S3 bucket.")
    st.stop()

st.success(f"✅ Loaded {total_files} documents from S3 bucket")

st.session_state.uploaded_text = all_text
st.session_state.dataframes = dfs

# 🎨 Chat Interface Styling
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

st.title("📈 Financial Insights Chatbot")
st.caption("Ask questions → Get analytical insights + charts (powered by Groq Llama 3)")

def clean_ocr_text(text: str) -> str:
    if not text:
        return ""

    s = unormalize("NFKC", text)

    # 2. Replace CR with LF, collapse multiple blank lines (keep paragraph breaks)
    s = s.replace('\r', '\n')
    s = re.sub(r'\n[ \t]+\n', '\n\n', s)        # tidy indented blank lines
    s = re.sub(r'[ \t]+', ' ', s)              # collapse spaces/tabs
    s = re.sub(r'\n{3,}', '\n\n', s)           # limit consecutive blank lines

    # 3. Join sequences of single letters separated by whitespace (e.g. "o n l y" -> "only")
    #    This targets patterns like: "o n l y" or "w h i c h"
    def _join_letters(m):
        tokens = re.findall(r'[A-Za-z]', m.group(0))
        return ''.join(tokens)
    s = re.sub(r'(?:\b[A-Za-z]\b[\s\r\n]+){2,}\b[A-Za-z]\b', _join_letters, s)

    # 4. Fix commas / thousands separators that got spaced: "1 , 942 , 152" -> "1,942,152"
    s = re.sub(r'\s*,\s*', ',', s)

    # 5. Remove spaces splitting digits "1 940 424" or "1 940,424" -> "1940,424" then normalize comas:
    s = re.sub(r'(?<=\d)[ \t]+(?=\d)', '', s)

    # 6. Remove spaces before/after parentheses and between parentheses and numbers
    s = s.replace('( ', '(').replace(' )', ')')

    # 7. Collapse multiple spaces one more time and trim
    s = re.sub(r' {2,}', ' ', s)
    s = s.strip()

    return s

# 💬 Question Input
question = st.chat_input("💬 Ask a question about your data...")

if question and (
    not st.session_state.chat_history
    or st.session_state.chat_history[-1]["question"] != question
):
    if not st.session_state.uploaded_text:
        st.warning("No data available. Please ensure files are in the 'uploads' folder.")
        st.stop()

    with st.spinner("Analyzing your files..."):
        # context = st.session_state.uploaded_text[:12000]
        raw_text = st.session_state.uploaded_text or ""
        context = clean_ocr_text(raw_text)[:10000]   # keep within token limits
        prompt = f"""
You are a financial analysis assistant.
You are given data (in text, CSV, or extracted tables) and a user question.
1. Analyze the data carefully.
2. Provide a concise, analytical answer.
3. If relevant, return a JSON summary of key metrics for visualization.
4. Suggest the most suitable chart type in the JSON output as "chart_type" (e.g., "bar", "line", "pie", "scatter", "area").

Example JSON format:
{{
  "chart_type": "bar",
  "Years": [2021, 2022, 2023],
  "Revenue": [100, 150, 200],
  "Profit": [20, 30, 45]
}}

Context:
{context}

Question:
{question}
"""
        try:
            response = client.chat.completions.create(
                model=GROQ_MODEL,  # ✅ Loaded dynamically from .env
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3
            )
            answer = response.choices[0].message.content
        except Exception as e:
            st.error(f"Error from Groq API: {e}")
            st.stop()

        st.session_state.chat_history.append({
            "question": question,
            "answer": answer
        })

# 💬 Chat Display
st.markdown("<div class='chat-container'>", unsafe_allow_html=True)
for chat in st.session_state.chat_history:
    st.markdown(f"<div class='chat-bubble-user'>{chat['question']}</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='chat-bubble-ai'>{chat['answer']}</div>", unsafe_allow_html=True)
st.markdown("</div>", unsafe_allow_html=True)

# 📊 Visualization
if st.session_state.chat_history:
    latest_answer = st.session_state.chat_history[-1]["answer"]
    try:
        json_start = latest_answer.find("{")
        json_end = latest_answer.rfind("}")
        if json_start != -1 and json_end != -1:
            json_str = latest_answer[json_start:json_end + 1]
            data = json.loads(json_str)
            chart_type = data.pop("chart_type", "line").lower()
            df = pd.DataFrame(data)

            st.subheader("📊 Visualization (AI-generated)")
            st.dataframe(df)

            if chart_type == "bar":
                fig = px.bar(df, x=df.columns[0], y=df.columns[1:], barmode="group", title="📊 Bar Chart")
            elif chart_type == "pie":
                fig = px.pie(df, names=df.columns[0], values=df.columns[1], title="🥧 Pie Chart")
            elif chart_type == "scatter":
                fig = px.scatter(df, x=df.columns[0], y=df.columns[1], title="📉 Scatter Plot")
            elif chart_type == "area":
                fig = px.area(df, x=df.columns[0], y=df.columns[1:], title="🌈 Area Chart")
            else:
                fig = px.line(df, x=df.columns[0], y=df.columns[1:], markers=True, title="📈 Line Chart")

            st.plotly_chart(fig, use_container_width=True)

    except Exception:
        if st.session_state.dataframes:
            df = st.session_state.dataframes[0]
            numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
            if len(numeric_cols) > 0:
                st.warning("No structured JSON found. Showing chart from CSV instead.")
                fig = px.line(df, x=df.columns[0], y=numeric_cols, markers=True, title="📈 CSV Data Chart")
                st.plotly_chart(fig, use_container_width=True)

