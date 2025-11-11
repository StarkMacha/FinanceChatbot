import streamlit as st
import pandas as pd
import fitz
import plotly.express as px
from groq import Groq
import json
from io import BytesIO
import requests
import os
from docx import Document as DocxDocument
import xml.etree.ElementTree as ET

st.set_page_config(page_title="📊 Financial Chatbot", layout="wide")

GROQ_API_KEY = st.secrets["API_KEY"]
os.environ["API_KEY"] = GROQ_API_KEY
client = Groq(api_key=GROQ_API_KEY)

# function to load public S3 fiels
def load_public_s3_files(bucket_name):
    """Loads all files (pdf, csv, doc, docx) from a public S3 bucket."""
    base_url = f"https://{bucket_name}.s3.amazonaws.com"
    folders = ["pdf", "csv", "doc", ""]
    all_text = ""
    dfs = []
    total_files = 0
    debug_lines = []

    for folder in folders:
        try:
            list_url = f"{base_url}?list-type=2&prefix={folder}/"
            r = requests.get(list_url)
            debug_lines.append(f"📂 Listing {list_url} (status {r.status_code})")
            if r.status_code != 200:
                continue
            root = ET.fromstring(r.text)
            keys = [e.text for e in root.findall(".//{http://s3.amazonaws.com/doc/2006-03-01/}Key")]
            debug_lines.append(f"🔍 Keys in '{folder}/': {keys}")

            for key in keys:
                if not key or key.endswith("/"):
                    continue
                file_url = f"{base_url}/{key}"
                file_resp = requests.get(file_url)
                if file_resp.status_code != 200:
                    debug_lines.append(f"⚠️ Failed to load {key}")
                    continue
                total_files += 1
                file_bytes = BytesIO(file_resp.content)

                if key.endswith(".pdf"):
                    pdf = fitz.open(stream=file_bytes.read(), filetype="pdf")
                    text = "".join([page.get_text("text") for page in pdf])
                    all_text += f"\n\n### From {key}:\n{text}"

                elif key.endswith(".csv"):
                    df = pd.read_csv(BytesIO(file_resp.content))
                    dfs.append(df)
                    all_text += f"\n\n### From {key}:\n{df.to_string(index=False)}"

                elif key.endswith(".doc") or key.endswith(".docx"):
                    doc = DocxDocument(file_bytes)
                    text = "\n".join(p.text for p in doc.paragraphs)
                    all_text += f"\n\n### From {key}:\n{text}"

        except Exception as e:
            debug_lines.append(f"❌ Error reading {folder}: {e}")

    if total_files == 0:
        debug_lines.append("⚠️ No files found in any folder.")
    else:
        debug_lines.append(f"✅ Loaded {total_files} files successfully from S3.")
    return all_text.strip(), dfs, "\n".join(debug_lines)

def summarize_dataframes_for_context(dfs):
    """Convert loaded DataFrames into a concise text summary for the LLM."""
    if not dfs:
        return ""
    summaries = []
    for i, df in enumerate(dfs):

        sample_text = df.head(5).to_string(index=False)
        numeric_cols = df.select_dtypes(include='number').columns.tolist()
        summary = f"""
                CSV Dataset {i+1} Summary:
                - Shape: {df.shape[0]} rows × {df.shape[1]} columns
                - Columns: {', '.join(df.columns[:10])}
                - Numeric Columns: {', '.join(numeric_cols[:10])}
                - Sample Data (first 5 rows):
                {sample_text}
                """
        if len(numeric_cols) > 0:
            stats = df[numeric_cols].describe().to_string()
            summary += f"\nDescriptive Stats:\n{stats}"
        summaries.append(summary)
    return "\n\n".join(summaries)


# SESSION STATE INIT
for key, default in {
    "chat_history": [],
    "latest_answer": "",
    "selected_question_index": None,
    "uploaded_text": "",
    "dataframes": [],
    "s3_loaded": False
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# SIDEBAR: CHAT HISTORY
st.sidebar.header("Chat History")
st.markdown("""
<style>
.chat-bubble-user, .chat-bubble-ai, .sidebar-answer {
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 16px;
    line-height: 1.5;
    white-space: pre-wrap;
    word-wrap: break-word;
}
</style>
""", unsafe_allow_html=True)

for i, entry in enumerate(st.session_state.chat_history):
    if st.sidebar.button(f"Q{i+1}: {entry['question']}", key=f"btn_{i}"):
        st.session_state.selected_question_index = i

if st.session_state.selected_question_index is not None:
    entry = st.session_state.chat_history[st.session_state.selected_question_index]
    st.sidebar.markdown("<div class='sidebar-answer'><strong>Answer:</strong></div>", unsafe_allow_html=True)
    st.sidebar.markdown(f"<div class='sidebar-answer'>{entry['answer']}</div>", unsafe_allow_html=True)

# LOADING FILES FROM S3
# with st.expander("🧩 S3 Auto-Load Debug Info", expanded=False):
S3_BUCKET_NAME = st.secrets["s3_bucket"]
os.environ["s3_bucket"] = S3_BUCKET_NAME
if not st.session_state.s3_loaded:
    s3_text, s3_dfs, debug_output = load_public_s3_files(S3_BUCKET_NAME)
    st.session_state.uploaded_text += "\n" + s3_text
    st.session_state.dataframes.extend(s3_dfs)
    st.session_state.s3_loaded = True
    # st.code(debug_output, language="bash")
# else:
    # st.success("✅ S3 data already loaded.")
    # st.code("Loaded from session cache.", language="bash")


# 🎨 CHAT UI STYLING
st.markdown("""
<style>
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
.chat-container { display: flex; flex-direction: column; }
</style>
""", unsafe_allow_html=True)

st.title("📈 Financial Insights Chatbot")
st.caption("Auto-loads from S3 → Ask questions → Get analytical insights + charts (Groq Llama 3.3)")

# 💬 CHAT INPUT
question = st.chat_input("💬 Ask a question about your data...")


if question and (
    not st.session_state.chat_history
    or st.session_state.chat_history[-1]["question"] != question
):
    if not st.session_state.uploaded_text.strip():
        st.warning("⚠️ No data available (S3 or uploads). Please check S3 access or upload a file.")
        st.stop()

    with st.spinner("Analyzing your files..."):

        text_context = st.session_state.uploaded_text[:8000]
        data_context = summarize_dataframes_for_context(st.session_state.dataframes)
        context = text_context + "\n\n" + data_context
        prompt = f"""
    You are a professional financial analysis assistant.
    Your task is to interpret business data (from text, tables, or CSV summaries)
    and provide clear, concise, and insightful answers — similar to how ChatGPT responds.

    Guidelines:
    1. Respond directly with the final insights — do NOT describe your process.
    2. Use precise, professional business language.
    3. If applicable, include numeric results (revenues, profits, trends, etc.) clearly.
    4. Avoid filler phrases like "we need to filter" or "from the sample data".
    5. If useful, include a well-structured JSON for visualization, with keys like:
    - chart_type (bar, line, pie, scatter, area)
    - relevant axes and values

    Example JSON format:
    {{
    "chart_type": "bar",
    "Years": [2021, 2022, 2023],
    "Revenue": [100, 150, 200],
    "Profit": [20, 30, 45]
    }}

    Context:
    {context}

    User Question:
    {question}

    Now, provide a clear, insightful answer followed by (if relevant) a concise JSON for visualization.
    """

#         prompt = f"""
# You are a financial analysis AI assistant chatbot.
# You are given data (in text, CSV, or extracted tables) and a user question.
# 1. Analyze the data carefully.
# 2. Provide a concise, analytical answer.
# 3. If relevant, return a JSON summary of key metrics for visualization.
# 4. Suggest the most suitable chart type in the JSON output as "chart_type" (e.g., "bar", "line", "pie", "scatter", "area").

# Example JSON format:
# {{
#   "chart_type": "bar",
#   "Years": [2021, 2022, 2023],
#   "Revenue": [100, 150, 200],
#   "Profit": [20, 30, 45]
# }}

# Context:
# {context}

# Question:
# {question}
# """
        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
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

#  DISPLAY CHAT
st.markdown("<div class='chat-container'>", unsafe_allow_html=True)
for chat in st.session_state.chat_history:
    st.markdown(f"<div class='chat-bubble-user'>{chat['question']}</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='chat-bubble-ai'>{chat['answer']}</div>", unsafe_allow_html=True)
st.markdown("</div>", unsafe_allow_html=True)

# VISUALIZATION
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
                fig = px.bar(df, x=df.columns[0], y=df.columns[1:], barmode="group")
            elif chart_type == "pie":
                fig = px.pie(df, names=df.columns[0], values=df.columns[1])
            elif chart_type == "scatter":
                fig = px.scatter(df, x=df.columns[0], y=df.columns[1])
            elif chart_type == "area":
                fig = px.area(df, x=df.columns[0], y=df.columns[1:])
            else:
                fig = px.line(df, x=df.columns[0], y=df.columns[1:], markers=True)
            st.plotly_chart(fig, use_container_width=True)

    except Exception:
        if st.session_state.dataframes:
            df = st.session_state.dataframes[0]
            numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
            if len(numeric_cols) > 0:
                st.warning("No structured JSON found. Showing chart from CSV instead.")
                fig = px.line(df, x=df.columns[0], y=numeric_cols, markers=True)
                st.plotly_chart(fig, use_container_width=True)
