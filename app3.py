import streamlit as st
import pandas as pd
import fitz  # PyMuPDF
import plotly.express as px
from groq import Groq
import json
from io import BytesIO
import requests
from docx import Document as DocxDocument
import xml.etree.ElementTree as ET
import os

st.set_page_config(page_title="📊 DocSense AI", layout="wide")

GROQ_API_KEY = st.secrets["API_KEY"]
os.environ["API_KEY"] = GROQ_API_KEY
client = Groq(api_key=GROQ_API_KEY)

# function to load public S3 fiels
def load_public_s3_files(bucket_name):
    """Loads all files (pdf, csv, doc, docx) from a public S3 bucket."""
    base_url = f"https://{bucket_name}.s3.amazonaws.com"
    all_text = ""
    dfs = []
    total_files = 0
    debug_lines = []

    try:
        list_url = f"{base_url}?list-type=2"
        r = requests.get(list_url)
        if r.status_code != 200:
            return "", [], 0, debug_lines
        root = ET.fromstring(r.text)
        keys = [e.text for e in root.findall(".//{http://s3.amazonaws.com/doc/2006-03-01/}Key")]

        for key in keys:
            if not key or key.endswith("/"):
                continue
            file_url = f"{base_url}/{key}"
            file_resp = requests.get(file_url)
            if file_resp.status_code != 200:
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
        pass

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
S3_BUCKET_NAME = "hr-buddy-genai"
if not st.session_state.s3_loaded:
    s3_text, s3_dfs, debug_output = load_public_s3_files(S3_BUCKET_NAME)
    st.session_state.uploaded_text += "\n" + s3_text
    st.session_state.dataframes.extend(s3_dfs)
    st.session_state.s3_loaded = True


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

st.title("📈 DocSense AI")
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

        text_context = st.session_state.uploaded_text[:12000]
        data_context = summarize_dataframes_for_context(st.session_state.dataframes)
        context = text_context + "\n\n" + data_context
        prompt = f"""
    You are an AI assistant with strict rules.
    Your task is to interpret business data (from text, tables, or CSV summaries)
    and provide clear, concise, and insightful answers — similar to how ChatGPT responds.
 
    RULES:
    1. You must ONLY answer using the information provided in the DOCUMENT CONTEXT.
    2. If the answer is not found in the context, reply with:
    "I don't have enough information in the uploaded documents to answer that."
    3. Do NOT use outside knowledge, web search, assumptions, or training data.
    4. Be concise, factual, and reference the exact values from the documents.
    5. If visualization is requested, generate charts using the uploaded data only.
    6. Never hallucinate or assume values not present in the dataset.
    7. Do not provide opinions or predictions beyond the data.
    8. If question is about forecasting future data based on existing data, try to give answer.
    9. If the question is irrelevant, don't reply unnecessary data, just answer exactly according to the question
    
    Guidelines:
    1. Respond directly with the final insights — do NOT describe your process.
    2. Use precise, professional business language.
    3. If applicable, include numeric results (revenues, profits, trends, etc.) clearly.
    4. Avoid filler phrases like "we need to filter" or "from the sample data".
    5. If useful, include a well-structured JSON for visualization, with keys like:
    - chart_type (bar, line, pie, scatter, area)
    - relevant axes and values
    - provide the scale like millions or relevant value for the axes

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
        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3
            )
            answer = response.choices[0].message.content
            json_start = answer.find("{")
            json_end = answer.rfind("}")
            chart_json = None
            if json_start != -1 and json_end != -1:
                try:
                    json_str = answer[json_start:json_end+1]
                    chart_json = json_str
                except:
                    chart_json = None
        except Exception as e:
            st.error(f"Error from Groq API: {e}")
            st.stop()

        st.session_state.chat_history.append({
            "question": question,
            "answer": answer,
            "chart_json": chart_json
        })

st.markdown("<div class='chat-container'>", unsafe_allow_html=True)

for chat in st.session_state.chat_history:
    # User bubble
    st.markdown(f"<div class='chat-bubble-user'>{chat['question']}</div>", unsafe_allow_html=True)

    # Assistant bubble
    st.markdown(f"<div class='chat-bubble-ai'>{chat['answer']}</div>", unsafe_allow_html=True)

    # If chart exists, render it here
    if chat.get("chart_json"):
        try:
            data = json.loads(chat["chart_json"])
            chart_type = data.pop("chart_type", "line").lower()
            df = pd.DataFrame(data)

            st.write("📊 **Visualization:**")
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

        except Exception as e:
            st.warning(f"⚠️ Failed to render chart: {e}")

st.markdown("</div>", unsafe_allow_html=True)
