import streamlit as st
import requests
import pandas as pd
import time
import io
from sentence_transformers import SentenceTransformer, util

# --- CONFIGURATION ---
API_URL = "https://functional-h3cjbjeeenhfapcx.canadacentral-01.azurewebsites.net/focus/faq"
API_KEY = "GN^CBB4185E5BFDAEDF7B1F172EE5F21"

st.set_page_config(page_title="Focus 2026 QA Dashboard", layout="wide", page_icon="🧪")

# --- LOAD AI MODEL (Cached) ---
@st.cache_resource
def load_semantic_model():
    return SentenceTransformer('all-MiniLM-L6-v2')

# --- HELPER: API CALL ---
def call_bot_safe(query, u_type, vertical="", unit="", company="Genpact"):
    # Fallback if User Type is missing
    if pd.isna(u_type) or str(u_type).strip() == "":
        u_type = "Employee"
        
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

# --- HELPER: TEST ENGINE (Reused for File & Paste) ---
def run_test_suite(df, model):
    lifecycle = st.info("🟡 Initializing Test Engine...")
    progress_bar = st.progress(0)
    
    # Live Metrics
    m1, m2, m3, m4 = st.columns(4)
    pass_box = m1.metric("PASS", 0)
    fail_box = m2.metric("FAIL", 0)
    avg_lat_box = m3.metric("Avg Latency", "0.00s")
    avg_acc_box = m4.metric("Avg Accuracy", "N/A")
    
    results = []
    latencies = []
    accuracies = []
    pass_cnt = 0
    fail_cnt = 0
    
    # Container for the "Live Feed" of chats
    st.markdown("### 📡 Live Execution Feed")
    live_feed = st.container()

    lifecycle.info("🟠 Running tests... Please wait.")
    
    for i, row in df.iterrows():
        question = row.get('Question')
        u_type = row.get('User Type', 'Employee')
        expected = row.get('Response', None) # Handle 'Response' or 'Expected Answer' column mapping before calling this
        
        # Skip empty rows
        if pd.isna(question) or str(question).strip() == "":
            continue

        # API Call
        api_res = call_bot_safe(question, u_type)
        actual = api_res["Actual Answer"]
        
        # AI Scoring
        similarity_score = None
        if expected and not pd.isna(expected) and api_res["Status"] == "PASS":
            emb1 = model.encode(str(expected), convert_to_tensor=True)
            emb2 = model.encode(str(actual), convert_to_tensor=True)
            similarity_score = round(util.pytorch_cos_sim(emb1, emb2).item() * 100, 1)
            accuracies.append(similarity_score)
            
        latencies.append(api_res["Time(s)"])
        
        if api_res["Status"] == "PASS":
            pass_cnt += 1
        else:
            fail_cnt += 1
            
        # Update Metrics
        pass_box.metric("PASS", pass_cnt)
        fail_box.metric("FAIL", fail_cnt)
        avg_lat_box.metric("Avg Latency", f"{sum(latencies)/len(latencies):.2f}s")
        if accuracies:
            avg_acc_box.metric("Avg Accuracy", f"{sum(accuracies)/len(accuracies):.1f}%")

        # Update Live Feed
        with live_feed:
            with st.expander(f"#{i+1}: {question[:50]}... ({api_res['Status']})", expanded=False):
                c1, c2 = st.columns(2)
                c1.markdown("**Expected:**")
                c1.info(expected if expected else "N/A")
                c2.markdown("**Actual:**")
                c2.success(actual) if api_res['Status'] == 'PASS' else c2.error(actual)
                st.caption(f"Latency: {api_res['Time(s)']}s | Similarity: {similarity_score}%")

        results.append({
            "ID": i+1,
            "User Type": u_type,
            "Question": question,
            "Expected": expected,
            "Actual": actual,
            "Accuracy (%)": similarity_score,
            "Latency": api_res["Time(s)"],
            "Status": api_res["Status"]
        })
        
        progress_bar.progress((i + 1) / len(df))
        
    lifecycle.success("🟢 Testing Complete!")
    return pd.DataFrame(results)

# --- MAIN UI ---
st.warning("⚠️ **INTERNAL TESTING ONLY**: This dashboard does not store sensitive client data. It is designed purely for functional API verification.")
st.title("🧪 Focus 2026 API QA Suite")

# Sidebar
with st.sidebar:
    st.header("⚙️ Configuration")
    with st.spinner("Loading AI Judge..."):
        model = load_semantic_model()
    st.success("✅ AI Judge Ready")
    
    st.divider()
    global_user_type = st.selectbox("Default User Type", ["Employee", "Client"])
    vertical = st.text_input("Vertical", "")
    unit = st.text_input("Unit", "")
    company = st.text_input("Company", "Genpact")

# Tabs
tab1, tab2, tab3 = st.tabs(["📝 Single Query", "📂 File Upload Test", "📋 Clipboard Paste Test"])

# --- TAB 1: MANUAL ---
with tab1:
    st.markdown("#### Quick Check")
    col1, col2 = st.columns([4, 1])
    with col1:
        q = st.text_input("Ask a question:", placeholder="e.g. Who is the Kolkata rep?")
    with col2:
        st.write("") 
        st.write("") 
        btn = st.button("Send Query", type="primary")

    if btn and q:
        with st.spinner("Thinking..."):
            res = call_bot_safe(q, global_user_type, vertical, unit, company)
            if res["Status"] == "PASS":
                st.success(f"Response ({res['Time(s)']}s)")
                st.markdown(f"**🤖 Answer:** {res['Actual Answer']}")
                with st.expander("Debug Info"):
                    st.json(res)
            else:
                st.error(f"Failed: {res['Actual Answer']}")

# --- TAB 2: FILE UPLOAD ---
with tab2:
    st.markdown("#### Bulk Test via File")
    st.info("Supported: `.csv` or `.xlsx`. Columns needed: `Question`, `Response` (optional), `User Type` (optional).")
    
    uploaded_file = st.file_uploader("Upload Variations File", type=["csv", "xlsx"])
    
    if uploaded_file:
        try:
            if uploaded_file.name.endswith('.csv'):
                df = pd.read_csv(uploaded_file)
            else:
                df = pd.read_excel(uploaded_file)
            
            # Normalize Headers
            df.columns = df.columns.str.strip()
            
            # Standardize Column Names
            col_map = {
                'Expected Answer': 'Response', 
                'User_type': 'User Type',
                'User_Type': 'User Type'
            }
            df = df.rename(columns=col_map)
            
            if "Question" not in df.columns:
                st.error("❌ File must have a 'Question' column.")
            else:
                st.write(f"Preview ({len(df)} rows):")
                st.dataframe(df.head(3), hide_index=True)
                
                if st.button("🚀 Run File Test"):
                    result_df = run_test_suite(df, model)
                    
                    # Display Results
                    st.divider()
                    st.markdown("### 📊 Final Report")
                    
                    def color_code(val):
                        if pd.isna(val): return ''
                        if val >= 85: return 'background-color: #c8e6c9' # Green
                        if val >= 65: return 'background-color: #fff9c4' # Yellow
                        return 'background-color: #ffcdd2' # Red

                    st.dataframe(result_df.style.map(color_code, subset=['Accuracy (%)']), use_container_width=True)
                    
                    csv = result_df.to_csv(index=False).encode('utf-8')
                    st.download_button("⬇️ Download Report", csv, "test_report_file.csv", "text/csv")
                    
        except Exception as e:
            st.error(f"Error reading file: {e}")

# --- TAB 3: CLIPBOARD PASTE ---
with tab3:
    st.markdown("#### Paste from Excel")
    st.markdown("Copy columns from Excel (`Question`, `Response`, `User Type`) and paste below. **Do not include headers in the paste if you want to use auto-mapping, or ensure the order is Question -> Response -> User Type**.")
    
    raw_text = st.text_area("Paste Data Here:", height=200, placeholder="Who is the rep?\tJohn Doe\tClient\nWhere is the hotel?\tHyatt\tEmployee")
    
    if st.button("🚀 Run Paste Test"):
        if raw_text.strip():
            try:
                # 1. Parse the pasted text
                # We assume tab-separated (standard Excel copy)
                data_io = io.StringIO(raw_text)
                
                # Try reading with headers first, if it fails validation, try headerless
                try:
                    df_paste = pd.read_csv(data_io, sep="\t", header=None)
                except:
                    st.error("Could not parse data. Ensure it is copied from Excel (Tab separated).")
                    st.stop()

                # 2. Map Columns based on count
                # Logic: Col 0 is always Question. Col 1 is Answer (opt). Col 2 is User Type (opt).
                num_cols = len(df_paste.columns)
                new_cols = {}
                
                new_cols[0] = "Question"
                if num_cols > 1: new_cols[1] = "Response"
                if num_cols > 2: new_cols[2] = "User Type"
                
                df_paste = df_paste.rename(columns=new_cols)
                
                st.success(f"Parsed {len(df_paste)} rows.")
                st.dataframe(df_paste.head(), hide_index=True)
                
                # 3. Run Test
                result_df = run_test_suite(df_paste, model)
                
                # 4. Results
                st.divider()
                st.markdown("### 📊 Final Report")
                
                def color_code(val):
                    if pd.isna(val): return ''
                    if val >= 85: return 'background-color: #c8e6c9'
                    if val >= 65: return 'background-color: #fff9c4'
                    return 'background-color: #ffcdd2'

                st.dataframe(result_df.style.map(color_code, subset=['Accuracy (%)']), use_container_width=True)
                
                csv = result_df.to_csv(index=False).encode('utf-8')
                st.download_button("⬇️ Download Report", csv, "test_report_paste.csv", "text/csv")
                
            except Exception as e:
                st.error(f"Error parsing data: {e}")
        else:
            st.warning("Please paste some data first.")




# import streamlit as st
# import requests
# import pandas as pd
# import time
# from sentence_transformers import SentenceTransformer, util

# # --- CONFIGURATION ---
# API_URL = "https://functional-h3cjbjeeenhfapcx.canadacentral-01.azurewebsites.net/focus/faq"
# API_KEY = "GN^CBB4185E5BFDAEDF7B1F172EE5F21"

# st.set_page_config(page_title="Focus 2026 QA Dashboard", layout="wide", page_icon="🧪")

# # --- LOAD AI MODEL (Cached) ---
# @st.cache_resource
# def load_semantic_model():
#     return SentenceTransformer('all-MiniLM-L6-v2')

# st.title("🧪 Focus 2026 API QA Suite")
# st.markdown("Upload your **Variations File**. The system auto-detects `Question`, `Response`, and `User Type`.")

# # --- SIDEBAR ---
# with st.sidebar:
#     st.header("⚙️ Configuration")
#     global_user_type = st.selectbox("Fallback User Type", ["Employee", "Client"])

#     st.divider()
#     with st.spinner("Loading AI Judge..."):
#         model = load_semantic_model()
#     st.success("✅ AI Judge Ready")

#     with st.expander("Advanced Params", expanded=False):
#         vertical = st.text_input("Vertical", "")
#         unit = st.text_input("Unit", "")
#         company = st.text_input("Company", "Genpact")

# # --- API FUNCTION (UNCHANGED) ---
# def call_bot_safe(query, u_type):
#     if pd.isna(u_type) or str(u_type).strip() == "":
#         u_type = global_user_type

#     headers = {"Content-Type": "application/json", "X-API-KEY": API_KEY}
#     payload = {
#         "query": str(query),
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

# # --- UI TABS ---
# tab1, tab2 = st.tabs(["📝 Manual Check", "🚀 Bulk Variations Test"])

# # --- TAB 1: MANUAL ---
# with tab1:
#     col1, col2 = st.columns([4, 1])
#     with col1:
#         q = st.text_input("Ask a question:", placeholder="e.g. Who is the Kolkata rep?")
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
#     st.subheader("Upload Test File")
#     st.info("Required Columns: `Question`, `Response`, `User Type`.")

#     uploaded_file = st.file_uploader("Choose file", type=["csv", "xlsx"])

#     if uploaded_file is not None:
#         try:
#             if uploaded_file.name.endswith('.csv'):
#                 df = pd.read_csv(uploaded_file)
#             else:
#                 df = pd.read_excel(uploaded_file)

#             df.columns = df.columns.str.strip()

#             if 'User Type' in df.columns:
#                 df['run_user_type'] = df['User Type']
#             elif 'User_type' in df.columns:
#                 df['run_user_type'] = df['User_type']
#             else:
#                 df['run_user_type'] = global_user_type

#             if 'Response' in df.columns:
#                 df['expected_answer'] = df['Response']
#             elif 'Expected Answer' in df.columns:
#                 df['expected_answer'] = df['Expected Answer']
#             else:
#                 df['expected_answer'] = None

#             if "Question" not in df.columns:
#                 st.error("❌ File MUST have a column named **'Question'**.")
#             else:
#                 st.success(f"✅ Loaded {len(df)} rows.")

#                 if st.button("Run AI Test Suite", type="primary"):

#                     lifecycle = st.info("🟡 Preparing test run...")
#                     progress = st.progress(0)

#                     m1, m2, m3, m4 = st.columns(4)
#                     pass_box = m1.metric("PASS", 0)
#                     fail_box = m2.metric("FAIL", 0)
#                     avg_lat_box = m3.metric("Avg Latency", "0.00s")
#                     avg_acc_box = m4.metric("Avg Accuracy", "N/A")

#                     live_feed = st.container()
#                     results = []

#                     pass_cnt = fail_cnt = 0
#                     latencies = []
#                     accuracies = []

#                     lifecycle.info("🟠 Running tests...")

#                     for i, row in df.iterrows():
#                         question = row['Question']
#                         u_type = row['run_user_type']
#                         expected = row['expected_answer']
#                         is_var = row.get('Is_variation', 'N/A')

#                         if pd.isna(expected): expected = None
#                         if pd.isna(u_type): u_type = global_user_type

#                         api_res = call_bot_safe(question, u_type)
#                         actual = api_res["Actual Answer"]

#                         similarity_score = None
#                         if expected and api_res["Status"] == "PASS":
#                             emb1 = model.encode(str(expected), convert_to_tensor=True)
#                             emb2 = model.encode(str(actual), convert_to_tensor=True)
#                             similarity_score = round(
#                                 util.pytorch_cos_sim(emb1, emb2).item() * 100, 1
#                             )
#                             accuracies.append(similarity_score)

#                         latencies.append(api_res["Time(s)"])

#                         if api_res["Status"] == "PASS":
#                             pass_cnt += 1
#                         else:
#                             fail_cnt += 1

#                         pass_box.metric("PASS", pass_cnt)
#                         fail_box.metric("FAIL", fail_cnt)
#                         avg_lat_box.metric("Avg Latency", f"{sum(latencies)/len(latencies):.2f}s")
#                         avg_acc_box.metric(
#                             "Avg Accuracy",
#                             f"{sum(accuracies)/len(accuracies):.1f}%" if accuracies else "N/A"
#                         )

#                         # 🔴 FULL REAL-TIME COMPARISON VIEW
#                         with live_feed:
#                             with st.expander(
#                                 f"🔎 Test {i+1} | {api_res['Status']} | {api_res['Time(s)']}s",
#                                 expanded=True
#                             ):
#                                 st.markdown("**🟦 Question**")
#                                 st.write(question)

#                                 colA, colB = st.columns(2)

#                                 with colA:
#                                     st.markdown("**📘 Expected Response**")
#                                     st.write(expected if expected else "—")

#                                 with colB:
#                                     st.markdown("**🤖 Actual Answer**")
#                                     st.write(actual)

#                                 c1, c2, c3 = st.columns(3)
#                                 c1.metric("Status", api_res["Status"])
#                                 c2.metric("Latency (s)", api_res["Time(s)"])
#                                 c3.metric(
#                                     "Semantic Score",
#                                     f"{similarity_score}%" if similarity_score is not None else "N/A"
#                                 )

#                         results.append({
#                             "ID": i+1,
#                             "User Type": u_type,
#                             "Is Variation": is_var,
#                             "Question": question,
#                             "Expected": expected,
#                             "Actual": actual,
#                             "Accuracy (%)": similarity_score,
#                             "Latency": api_res["Time(s)"],
#                             "Status": api_res["Status"]
#                         })

#                         progress.progress((i + 1) / len(df))

#                     lifecycle.success("🟢 Testing complete!")

#                     result_df = pd.DataFrame(results)

#                     def color_code(val):
#                         if pd.isna(val): return ''
#                         if val >= 85: return 'background-color: #c8e6c9'
#                         if val >= 65: return 'background-color: #fff9c4'
#                         return 'background-color: #ffcdd2'

#                     st.dataframe(
#                         result_df.style.map(color_code, subset=['Accuracy (%)']),
#                         use_container_width=True
#                     )

#                     csv_data = result_df.to_csv(index=False).encode('utf-8')
#                     st.download_button(
#                         "⬇️ Download Test Report",
#                         csv_data,
#                         "test_report.csv",
#                         "text/csv"
#                     )

#         except Exception as e:
#             st.error(f"Error processing file: {e}")
