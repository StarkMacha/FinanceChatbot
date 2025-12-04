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
st.set_page_config(page_title="DocSense AI", layout="wide")

# st.title("DocSense AI")
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
    DocSense AI
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

# Helper: format numeric columns for DISPLAY (adds commas and optional currency symbol)
# -------------------------------
def formatted_display_df(df: pd.DataFrame, currency_symbol: str = ""):
    """
    Returns a copy of df where numeric columns are formatted as
    comma-separated integers, optionally prefixed with a currency symbol.
    Example: 14015150 -> "$14,015,150"
    """
    disp = df.copy()
    for col in disp.columns:
        if pd.api.types.is_numeric_dtype(disp[col]):
            disp[col] = disp[col].apply(
                lambda x: f"{currency_symbol}{int(round(x)):,}" if pd.notna(x) else ""
            )
    return disp
 
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
FOLDER_PREFIX = "aarp/"   # 👈 only load files under this folder

# -----------------------------
def load_s3_public_files():
    """Load all PDFs / CSVs / DOCX from a PUBLIC S3 bucket."""
    list_url = f"{BASE_URL}?list-type=2&prefix={FOLDER_PREFIX}"

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

# # -------------------------------
# # 📂 Load files from local uploads folder
# # -------------------------------
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
        context = st.session_state.uploaded_text[:30000]
        prompt = f"""
You are an AI assistant with strict rules who is expert in analysing documents.
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
- If values in the documents are monetary, include a key "currency_symbol"
  with the exact symbol or text used (for example: "$", "₹", "Rs", "USD", "€", "¥").
- If no chart is needed, output: {{}}

Example JSON format if chart info is needed:
<json>
{{
  "chart_type": "bar",
  "currency_symbol": "¥",
  "col1": [2023, 2024],
  "values": [5732599, 14015150]
}}
</json>
Example JSON format if chart info is not needed:
<json>
{{}}
</json>

NEVER wrap numbers in quotes unless they are real text labels.
Never miss the chart_type and currency_type keys, if they dont have any value, please give empty string
please do not give keys names like col, values. Instead give the actual attribute names
 like years, revenue or anything that the actual values are about


RULES:
    1. You must ONLY answer using the information provided in the DOCUMENT CONTEXT.
    2. Do not provide opinions beyond the data.
    3. Do NOT use outside knowledge, web search, assumptions, or training data.
    4. Be concise, factual, and reference the exact values from the documents.
    5. If visualization is requested explicitly by the user, generate charts using the uploaded data only.
    6. Never hallucinate or assume values not present in the dataset.
    7. If the question is irrelevant, don't reply unnecessary data, just answer exactly according to the question.
    8. If question is about forecasting future data based on existing data, try to give answer.

Guardrails:
1. Respond directly with the final insights — do NOT describe your process.
2. Use precise, professional business language.
3. If applicable, include numeric results (revenues, profits, trends, etc.) clearly.
4. Avoid filler phrases like "we need to filter" or "from the sample data".
5. If useful, provide charts for visualization, with keys like:
- chart_type (bar, line, pie, scatter, area)
- relevant axes and values
- provide the scale like millions or relevant value for the axes


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
    json_str = latest_raw[json_start + 6:json_end].strip()
    if json_str != "{}":
        if json_start != -1 and json_end != -1:
            try:
                json_str = latest_raw[json_start + 6:json_end].strip()
                data = json.loads(json_str)
                st.write(json_str)

                # Extract chart type & currency symbol (if present)
                chart_type = data.pop("chart_type", "line").lower() if isinstance(data, dict) else "line"
                currency_symbol = data.pop("currency_symbol", "")

                # Build dataframe from returned JSON
                df = pd.DataFrame(data)
                # if isinstance(data, dict):
                #     # all remaining values are scalars? -> make Metric/Value table
                #     if all(not isinstance(v, (list, tuple, dict)) for v in data.values()):
                #         df = pd.DataFrame(
                #             {
                #                 "Metric": list(data.keys()),
                #                 "Value": list(data.values()),
                #             }
                #         )
                #     else:
                #         df = pd.DataFrame(data)
                # else:
                #     df = pd.DataFrame(data)

                # Try to coerce numeric columns
                for c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors="ignore")

                df = fix_arrow_df(df)
                xcol = df.columns[0]
                df[xcol] = df[xcol].astype(str)

                st.subheader("📊 Visualization")

                # Show formatted table (with currency if provided)
                df.index = df.index + 1  # start index from 1
                display_df = formatted_display_df(df, currency_symbol)

                st.dataframe(display_df)

                # ---- Plot Selection with numeric labels & no M/K abbreviations ----
                if chart_type == "bar":
                    fig = px.bar(
                        df,
                        x=xcol,
                        y=df.columns[1:],
                        barmode="group",
                        title="📊 Bar Chart",
                        text_auto=True,
                    )
                    fig.update_traces(
                        textposition="outside",
                        texttemplate=f"{currency_symbol}%{{y:,.0f}}",
                        hovertemplate=f"%{{x}}<br>%{{fullData.name}}: {currency_symbol}%{{y:,.0f}}<extra></extra>",
                        textfont_size=11,
                    )
                    fig.update_yaxes(tickformat=",.0f")
                    fig.update_layout(margin=dict(t=40, b=40))

                elif chart_type == "pie":
                    value_col = df.columns[1] if len(df.columns) > 1 else df.columns[0]
                    fig = px.pie(df, names=xcol, values=value_col, title="🥧 Pie Chart")
                    fig.update_traces(
                        textinfo="label+percent+value",
                        texttemplate=f"%{{label}}: %{{percent}} ({currency_symbol}%{{value:,.0f}})",
                        hovertemplate=f"%{{label}}<br>{currency_symbol}%{{value:,.0f}} (%{{percent}})<extra></extra>",
                        textfont_size=12,
                    )
                    fig.update_layout(margin=dict(t=40, b=40))

                elif chart_type == "scatter":
                    numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
                    if len(numeric_cols) >= 1:
                        ycol = numeric_cols[0]
                    else:
                        ycol = df.columns[1] if len(df.columns) > 1 else df.columns[0]
                    fig = px.scatter(df, x=xcol, y=ycol, title="📉 Scatter Plot", text=ycol)
                    fig.update_traces(
                        textposition="top center",
                        texttemplate=f"{currency_symbol}%{{y:,.0f}}",
                        hovertemplate=f"%{{x}}<br>{currency_symbol}%{{y:,.0f}}<extra></extra>",
                        marker=dict(size=8),
                    )
                    fig.update_yaxes(tickformat=",.0f")
                    fig.update_layout(margin=dict(t=40, b=40))

                elif chart_type == "area":
                    fig = px.area(df, x=xcol, y=df.columns[1:], title="🌈 Area Chart")
                    fig.update_traces(
                        mode="lines+markers+text",
                        texttemplate=f"{currency_symbol}%{{y:,.0f}}",
                        textposition="top center",
                        hovertemplate=f"%{{x}}<br>%{{fullData.name}}: {currency_symbol}%{{y:,.0f}}<extra></extra>",
                    )
                    fig.update_yaxes(tickformat=",.0f")
                    fig.update_layout(margin=dict(t=40, b=40))

                else:
                    # default line chart
                    fig = px.line(df, x=xcol, y=df.columns[1:], markers=True, title="📈 Line Chart")
                    fig.update_traces(
                        mode="lines+markers+text",
                        texttemplate=f"{currency_symbol}%{{y:,.0f}}",
                        textposition="top center",
                        hovertemplate=f"%{{x}}<br>%{{fullData.name}}: {currency_symbol}%{{y:,.0f}}<extra></extra>",
                    )
                    fig.update_yaxes(tickformat=",.0f")
                    fig.update_layout(margin=dict(t=40, b=40))

                fig.update_xaxes(type="category")
                st.plotly_chart(fig, use_container_width=True)

            except Exception as e:
                # st.warning(f"Visualization failed: {e}")
                # CSV fallback if JSON can't be parsed
                if st.session_state.dataframes:
                    df = st.session_state.dataframes[0]
                    df = fix_arrow_df(df)
                    xcol = df.columns[0]
                    df[xcol] = df[xcol].astype(str)
                    numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
                    if numeric_cols:
                        st.subheader("📊 CSV Data Visualization (fallback)")
                        display_df = formatted_display_df(df[[xcol] + numeric_cols], "")
                        st.dataframe(display_df)
                        fig = px.bar(
                            df,
                            x=xcol,
                            y=numeric_cols,
                            barmode="group",
                            title="📊 CSV Data Chart",
                            text_auto=True,
                        )
                        fig.update_traces(
                            textposition="outside",
                            texttemplate="%{y:,.0f}",
                            hovertemplate="%{x}<br>%{fullData.name}: %{y:,.0f}<extra></extra>",
                            textfont_size=11,
                        )
                        fig.update_yaxes(tickformat=",.0f")
                        fig.update_layout(margin=dict(t=40, b=40))
                        st.plotly_chart(fig, use_container_width=True)
        else:
            # JSON not present — CSV fallback
            if st.session_state.dataframes:
                df = st.session_state.dataframes[0]
                df = fix_arrow_df(df)
                xcol = df.columns[0]
                df[xcol] = df[xcol].astype(str)
                numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
                if numeric_cols:
                    st.subheader("📊 CSV Data Visualization")
                    display_df = formatted_display_df(df[[xcol] + numeric_cols], "")
                    st.dataframe(display_df)
                    fig = px.line(df, x=xcol, y=numeric_cols, markers=True, title="📈 CSV Data Chart")
                    fig.update_traces(
                        mode="lines+markers+text",
                        texttemplate="%{y:,.0f}",
                        hovertemplate="%{x}<br>%{fullData.name}: %{y:,.0f}<extra></extra>",
                        textposition="top center",
                    )
                    fig.update_yaxes(tickformat=",.0f")
                    fig.update_layout(margin=dict(t=40, b=40))
                    st.plotly_chart(fig, use_container_width=True)
