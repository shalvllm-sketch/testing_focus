import streamlit as st
import requests
import pandas as pd
import time
from sentence_transformers import SentenceTransformer, util

# --- CONFIGURATION ---
API_URL = "https://functional-h3cjbjeeenhfapcx.canadacentral-01.azurewebsites.net/focus/faq"
API_KEY = "GN^CBB4185E5BFDAEDF7B1F172EE5F21"

st.set_page_config(page_title="Focus 2026 QA Dashboard", layout="wide", page_icon="🧪")

# --- LOAD AI MODEL (Cached for Speed) ---
@st.cache_resource
def load_semantic_model():
    # This downloads a small, fast model (80MB) optimized for sentence similarity
    return SentenceTransformer('all-MiniLM-L6-v2')

st.title("🧪 Focus 2026 API QA Suite (AI Powered)")
st.markdown("Upload your FAQ file. The system calculates **Semantic Accuracy** automatically.")

# --- SIDEBAR CONFIG ---
with st.sidebar:
    st.header("⚙️ Configuration")
    global_user_type = st.selectbox("Default User Type", ["Employee", "Client"])
    
    st.divider()
    # Load model status
    with st.spinner("Loading AI Model..."):
        model = load_semantic_model()
    st.success("✅ Semantic AI Ready")

    with st.expander("Advanced Params", expanded=False):
        vertical = st.text_input("Vertical", "")
        unit = st.text_input("Unit", "")
        company = st.text_input("Company", "Genpact")

# --- ROBUST API FUNCTION ---
def call_bot_safe(query, u_type):
    if pd.isna(u_type) or str(u_type).strip() == "":
        u_type = global_user_type
        
    headers = {"Content-Type": "application/json", "X-API-KEY": API_KEY}
    payload = {
        "query": str(query),
        "user_type": u_type,
        "vertical": vertical,
        "unit": unit,
        "company": company
    }
    
    try:
        start_time = time.time()
        response = requests.post(API_URL, json=payload, headers=headers, timeout=10)
        duration = round(time.time() - start_time, 2)
        
        if response.status_code == 200:
            data = response.json()
            return {
                "Actual Answer": data.get("answer", "No Answer Field"),
                "Source": data.get("sources", [{}])[0].get("source", "AI") if data.get("sources") else "AI",
                "Time(s)": duration,
                "Status": "PASS"
            }
        else:
            return {
                "Actual Answer": f"API Error: {response.status_code}",
                "Source": "N/A",
                "Time(s)": duration,
                "Status": "FAIL"
            }
    except Exception as e:
        return {
            "Actual Answer": f"Exception: {str(e)}",
            "Source": "Error",
            "Time(s)": 0,
            "Status": "CRASH"
        }

# --- TABS ---
tab1, tab2 = st.tabs(["📝 Single Query", "🚀 Bulk Upload & AI Test"])

# --- TAB 1: MANUAL ---
with tab1:
    col1, col2 = st.columns([4, 1])
    with col1:
        q = st.text_input("Ask a question:", placeholder="e.g. Where is my hotel?")
    with col2:
        st.write("") 
        st.write("") 
        if st.button("Send", type="primary"):
            with st.spinner("Thinking..."):
                res = call_bot_safe(q, global_user_type)
                if res["Status"] == "PASS":
                    st.success(f"Response ({res['Time(s)']}s)")
                    st.markdown(f"**🤖 Answer:** {res['Actual Answer']}")
                else:
                    st.error(f"Failed: {res['Actual Answer']}")

# --- TAB 2: BULK TEST WITH AI SCORING ---
with tab2:
    st.subheader("Upload FAQ File")
    st.info("Required column: **'Question'**. For AI Accuracy, you MUST have a column named **'Response'** (the expected answer).")
    
    uploaded_file = st.file_uploader("Choose file", type=["csv", "xlsx"])
    
    if uploaded_file is not None:
        try:
            if uploaded_file.name.endswith('.csv'):
                df = pd.read_csv(uploaded_file)
            else:
                df = pd.read_excel(uploaded_file)
            
            df.columns = df.columns.str.strip()
            
            if "Question" not in df.columns:
                st.error("❌ File MUST have a column named **'Question'**.")
            else:
                st.success(f"✅ Loaded {len(df)} rows.")
                
                if st.button(f"Run AI Test Suite", type="primary"):
                    
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    results = []
                    
                    for i, row in df.iterrows():
                        question = row['Question']
                        u_type = row['User Type'] if 'User Type' in df.columns else global_user_type
                        
                        # Expected Response (Clean NaN)
                        expected = row['Response'] if 'Response' in df.columns else None
                        if pd.isna(expected): expected = None
                        
                        status_text.text(f"Testing {i+1}/{len(df)}...")
                        
                        # 1. Call API
                        api_res = call_bot_safe(question, u_type)
                        actual = api_res["Actual Answer"]
                        
                        # 2. AI SEMANTIC SCORING
                        # Compare 'actual' vs 'expected' using embeddings
                        similarity_score = 0.0
                        if expected and api_res["Status"] == "PASS":
                            # Convert both sentences to vectors
                            emb1 = model.encode(expected, convert_to_tensor=True)
                            emb2 = model.encode(actual, convert_to_tensor=True)
                            # Calculate cosine similarity (0 to 1) -> Convert to %
                            similarity_score = util.pytorch_cos_sim(emb1, emb2).item() * 100
                            similarity_score = round(similarity_score, 1)
                        else:
                            similarity_score = None # Can't score if no expected answer
                        
                        results.append({
                            "ID": i+1,
                            "Question": question,
                            "Expected": expected,
                            "Actual": actual,
                            "Semantic Score": similarity_score, # The Magic Number
                            "Latency": api_res["Time(s)"],
                            "Status": api_res["Status"]
                        })
                        
                        progress_bar.progress((i + 1) / len(df))
                    
                    status_text.text("✅ Testing Complete!")
                    result_df = pd.DataFrame(results)
                    
                    # --- DASHBOARD METRICS ---
                    col_m1, col_m2, col_m3 = st.columns(3)
                    
                    # 1. Pass Rate (API Success)
                    pass_rate = len(result_df[result_df["Status"]=="PASS"]) / len(result_df) * 100
                    col_m1.metric("API Stability", f"{pass_rate:.1f}%")
                    
                    # 2. Average Latency
                    avg_lat = result_df["Latency"].mean()
                    col_m2.metric("Avg Latency", f"{avg_lat:.2f}s")
                    
                    # 3. AVERAGE SEMANTIC ACCURACY
                    # Filter out rows where we didn't have an expected answer
                    scored_rows = result_df.dropna(subset=["Semantic Score"])
                    if not scored_rows.empty:
                        avg_acc = scored_rows["Semantic Score"].mean()
                        col_m3.metric("🤖 Semantic Accuracy", f"{avg_acc:.1f}%")
                    else:
                        col_m3.metric("Accuracy", "N/A")

                    # --- COLOR CODED TABLE ---
                    # Logic: 
                    # Green = >85% Match
                    # Yellow = 60-85% Match
                    # Red = <60% Match or Fail
                    def color_code(val):
                        if pd.isna(val): return ''
                        if val >= 85: return 'background-color: #c8e6c9' # Green
                        if val >= 60: return 'background-color: #fff9c4' # Yellow
                        return 'background-color: #ffcdd2' # Red

                    st.dataframe(
                        result_df.style.map(color_code, subset=['Semantic Score']), 
                        use_container_width=True
                    )
                    
                    # Download
                    csv_data = result_df.to_csv(index=False).encode('utf-8')
                    st.download_button("Download AI Report", csv_data, "ai_test_results.csv", "text/csv")

        except Exception as e:
            st.error(f"Error: {e}")
            




# import streamlit as st
# import requests
# import pandas as pd
# import time

# # --- CONFIGURATION ---
# API_URL = "https://functional-h3cjbjeeenhfapcx.canadacentral-01.azurewebsites.net/focus/faq"
# API_KEY = "GN^CBB4185E5BFDAEDF7B1F172EE5F21"

# st.set_page_config(page_title="Focus 2026 QA Dashboard", layout="wide", page_icon="🧪")

# st.title("🧪 Focus 2026 API QA Suite")
# st.markdown("Upload your FAQ file directly. The system will handle missing S.No automatically.")

# # --- SIDEBAR CONFIG ---
# with st.sidebar:
#     st.header("⚙️ Configuration")
#     global_user_type = st.selectbox("Default User Type (Fallback)", ["Employee", "Client"])
    
#     st.divider()
#     with st.expander("Advanced Params", expanded=False):
#         vertical = st.text_input("Vertical", "")
#         unit = st.text_input("Unit", "")
#         company = st.text_input("Company", "Genpact")

# # --- ROBUST API FUNCTION ---
# def call_bot_safe(query, u_type):
#     """
#     Calls the bot and handles ANY crash so the loop never stops.
#     """
#     # Safety: If file has empty User Type, use the Global Default
#     if pd.isna(u_type) or str(u_type).strip() == "":
#         u_type = global_user_type
        
#     headers = {"Content-Type": "application/json", "X-API-KEY": API_KEY}
#     payload = {
#         "query": str(query), # Ensure it's a string
#         "user_type": u_type,
#         "vertical": vertical,
#         "unit": unit,
#         "company": company
#     }
    
#     try:
#         start_time = time.time()
#         response = requests.post(API_URL, json=payload, headers=headers, timeout=10)
#         duration = round(time.time() - start_time, 2)
        
#         if response.status_code == 200:
#             data = response.json()
#             return {
#                 "Actual Answer": data.get("answer", "No Answer Field"),
#                 "Source": data.get("sources", [{}])[0].get("source", "AI") if data.get("sources") else "AI",
#                 "Time(s)": duration,
#                 "Status": "PASS"
#             }
#         else:
#             return {
#                 "Actual Answer": f"API Error: {response.status_code}",
#                 "Source": "N/A",
#                 "Time(s)": duration,
#                 "Status": "FAIL"
#             }
            
#     except Exception as e:
#         return {
#             "Actual Answer": f"Exception: {str(e)}",
#             "Source": "Error",
#             "Time(s)": 0,
#             "Status": "CRASH"
#         }

# # --- TABS ---
# tab1, tab2 = st.tabs(["📝 Single Query", "🚀 Bulk Upload & Test"])

# # --- TAB 1: MANUAL ---
# with tab1:
#     col1, col2 = st.columns([4, 1])
#     with col1:
#         q = st.text_input("Ask a question:", placeholder="e.g. Where is my hotel?")
#     with col2:
#         st.write("") 
#         st.write("") 
#         if st.button("Send", type="primary"):
#             with st.spinner("Thinking..."):
#                 res = call_bot_safe(q, global_user_type)
#                 if res["Status"] == "PASS":
#                     st.success(f"Response ({res['Time(s)']}s)")
#                     st.markdown(f"**🤖 Answer:** {res['Actual Answer']}")
#                 else:
#                     st.error(f"Failed: {res['Actual Answer']}")

# # --- TAB 2: BULK TEST ---
# with tab2:
#     st.subheader("Upload FAQ File")
#     st.info("Supports CSV or Excel (.xlsx). Required column: **'Question'**. Optional: 'User Type', 'Response'.")
    
#     # Allow both CSV and Excel
#     uploaded_file = st.file_uploader("Choose file", type=["csv", "xlsx"])
    
#     if uploaded_file is not None:
#         try:
#             # Load based on extension
#             if uploaded_file.name.endswith('.csv'):
#                 df = pd.read_csv(uploaded_file)
#             else:
#                 df = pd.read_excel(uploaded_file)
            
#             # Clean column names (strip spaces like 'User Type ' -> 'User Type')
#             df.columns = df.columns.str.strip()
            
#             # Validation
#             if "Question" not in df.columns:
#                 st.error("❌ File MUST have a column named **'Question'**.")
#                 st.write("Found columns:", list(df.columns))
#             else:
#                 st.success(f"✅ Loaded {len(df)} rows. Ready to test.")
                
#                 if st.button(f"Run {len(df)} Tests", type="primary"):
                    
#                     progress_bar = st.progress(0)
#                     status_text = st.empty()
#                     results = []
                    
#                     for i, row in df.iterrows():
#                         question = row['Question']
                        
#                         # Handle potential missing User Type column
#                         u_type = row['User Type'] if 'User Type' in df.columns else global_user_type
                        
#                         # Handle Expected Response for comparison
#                         expected = row['Response'] if 'Response' in df.columns else "N/A"
                        
#                         status_text.text(f"Testing {i+1}/{len(df)}: {str(question)[:30]}...")
                        
#                         # API Call
#                         api_res = call_bot_safe(question, u_type)
                        
#                         results.append({
#                             "Row": i+1,
#                             "User Type": u_type if not pd.isna(u_type) else global_user_type,
#                             "Question": question,
#                             "Expected Response": expected,  # Added this column!
#                             "Actual Answer": api_res["Actual Answer"],
#                             "Source": api_res["Source"],
#                             "Latency": api_res["Time(s)"],
#                             "Status": api_res["Status"]
#                         })
                        
#                         progress_bar.progress((i + 1) / len(df))
                    
#                     status_text.text("✅ Testing Complete!")
                    
#                     # Create Result DF
#                     result_df = pd.DataFrame(results)
                    
#                     # Interactive Table
#                     st.dataframe(
#                         result_df.style.apply(
#                             lambda x: ['background-color: #ffcdd2' if v == 'FAIL' or v == 'CRASH' else '' for v in x], 
#                             axis=1
#                         ), 
#                         use_container_width=True
#                     )
                    
#                     # Download
#                     csv_data = result_df.to_csv(index=False).encode('utf-8')
#                     st.download_button("Download Comparison Report", csv_data, "faq_test_results.csv", "text/csv")

#         except Exception as e:
#             st.error(f"Error reading file: {e}")
