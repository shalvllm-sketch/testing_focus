import streamlit as st
import requests
import pandas as pd
import time
from sentence_transformers import SentenceTransformer, util

# --- CONFIGURATION ---
API_URL = "https://functional-h3cjbjeeenhfapcx.canadacentral-01.azurewebsites.net/focus/faq"
API_KEY = "GN^CBB4185E5BFDAEDF7B1F172EE5F21"

st.set_page_config(page_title="Focus 2026 QA Dashboard", layout="wide", page_icon="🧪")

# --- LOAD AI MODEL (Cached) ---
@st.cache_resource
def load_semantic_model():
    return SentenceTransformer('all-MiniLM-L6-v2')

st.title("🧪 Focus 2026 API QA Suite")
st.markdown("Upload your **Variations File**. The system auto-detects `Question`, `Response`, and `User Type`.")

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Configuration")
    global_user_type = st.selectbox("Fallback User Type", ["Employee", "Client"])

    st.divider()
    with st.spinner("Loading AI Judge..."):
        model = load_semantic_model()
    st.success("✅ AI Judge Ready")

    with st.expander("Advanced Params", expanded=False):
        vertical = st.text_input("Vertical", "")
        unit = st.text_input("Unit", "")
        company = st.text_input("Company", "Genpact")

# --- API FUNCTION (UNCHANGED) ---
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

# --- UI TABS ---
tab1, tab2 = st.tabs(["📝 Manual Check", "🚀 Bulk Variations Test"])

# --- TAB 1: MANUAL ---
with tab1:
    col1, col2 = st.columns([4, 1])
    with col1:
        q = st.text_input("Ask a question:", placeholder="e.g. Who is the Kolkata rep?")
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

# --- TAB 2: BULK TEST ---
with tab2:
    st.subheader("Upload Test File")
    st.info("Required Columns: `Question`, `Response`, `User Type`.")

    uploaded_file = st.file_uploader("Choose file", type=["csv", "xlsx"])

    if uploaded_file is not None:
        try:
            if uploaded_file.name.endswith('.csv'):
                df = pd.read_csv(uploaded_file)
            else:
                df = pd.read_excel(uploaded_file)

            df.columns = df.columns.str.strip()

            if 'User Type' in df.columns:
                df['run_user_type'] = df['User Type']
            elif 'User_type' in df.columns:
                df['run_user_type'] = df['User_type']
            else:
                df['run_user_type'] = global_user_type

            if 'Response' in df.columns:
                df['expected_answer'] = df['Response']
            elif 'Expected Answer' in df.columns:
                df['expected_answer'] = df['Expected Answer']
            else:
                df['expected_answer'] = None

            if "Question" not in df.columns:
                st.error("❌ File MUST have a column named **'Question'**.")
            else:
                st.success(f"✅ Loaded {len(df)} rows.")

                if st.button("Run AI Test Suite", type="primary"):

                    lifecycle = st.info("🟡 Preparing test run...")
                    progress = st.progress(0)

                    m1, m2, m3, m4 = st.columns(4)
                    pass_box = m1.metric("PASS", 0)
                    fail_box = m2.metric("FAIL", 0)
                    avg_lat_box = m3.metric("Avg Latency", "0.00s")
                    avg_acc_box = m4.metric("Avg Accuracy", "N/A")

                    live_feed = st.container()
                    results = []

                    pass_cnt = fail_cnt = 0
                    latencies = []
                    accuracies = []

                    lifecycle.info("🟠 Running tests...")

                    for i, row in df.iterrows():
                        question = row['Question']
                        u_type = row['run_user_type']
                        expected = row['expected_answer']
                        is_var = row.get('Is_variation', 'N/A')

                        if pd.isna(expected): expected = None
                        if pd.isna(u_type): u_type = global_user_type

                        api_res = call_bot_safe(question, u_type)
                        actual = api_res["Actual Answer"]

                        similarity_score = None
                        if expected and api_res["Status"] == "PASS":
                            emb1 = model.encode(str(expected), convert_to_tensor=True)
                            emb2 = model.encode(str(actual), convert_to_tensor=True)
                            similarity_score = round(
                                util.pytorch_cos_sim(emb1, emb2).item() * 100, 1
                            )
                            accuracies.append(similarity_score)

                        latencies.append(api_res["Time(s)"])

                        if api_res["Status"] == "PASS":
                            pass_cnt += 1
                        else:
                            fail_cnt += 1

                        pass_box.metric("PASS", pass_cnt)
                        fail_box.metric("FAIL", fail_cnt)
                        avg_lat_box.metric("Avg Latency", f"{sum(latencies)/len(latencies):.2f}s")
                        avg_acc_box.metric(
                            "Avg Accuracy",
                            f"{sum(accuracies)/len(accuracies):.1f}%" if accuracies else "N/A"
                        )

                        # 🔴 FULL REAL-TIME COMPARISON VIEW
                        with live_feed:
                            with st.expander(
                                f"🔎 Test {i+1} | {api_res['Status']} | {api_res['Time(s)']}s",
                                expanded=True
                            ):
                                st.markdown("**🟦 Question**")
                                st.write(question)

                                colA, colB = st.columns(2)

                                with colA:
                                    st.markdown("**📘 Expected Response**")
                                    st.write(expected if expected else "—")

                                with colB:
                                    st.markdown("**🤖 Actual Answer**")
                                    st.write(actual)

                                c1, c2, c3 = st.columns(3)
                                c1.metric("Status", api_res["Status"])
                                c2.metric("Latency (s)", api_res["Time(s)"])
                                c3.metric(
                                    "Semantic Score",
                                    f"{similarity_score}%" if similarity_score is not None else "N/A"
                                )

                        results.append({
                            "ID": i+1,
                            "User Type": u_type,
                            "Is Variation": is_var,
                            "Question": question,
                            "Expected": expected,
                            "Actual": actual,
                            "Accuracy (%)": similarity_score,
                            "Latency": api_res["Time(s)"],
                            "Status": api_res["Status"]
                        })

                        progress.progress((i + 1) / len(df))

                    lifecycle.success("🟢 Testing complete!")

                    result_df = pd.DataFrame(results)

                    def color_code(val):
                        if pd.isna(val): return ''
                        if val >= 85: return 'background-color: #c8e6c9'
                        if val >= 65: return 'background-color: #fff9c4'
                        return 'background-color: #ffcdd2'

                    st.dataframe(
                        result_df.style.map(color_code, subset=['Accuracy (%)']),
                        use_container_width=True
                    )

                    csv_data = result_df.to_csv(index=False).encode('utf-8')
                    st.download_button(
                        "⬇️ Download Test Report",
                        csv_data,
                        "test_report.csv",
                        "text/csv"
                    )

        except Exception as e:
            st.error(f"Error processing file: {e}")






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
#                         avg_lat_box.metric(
#                             "Avg Latency", f"{sum(latencies)/len(latencies):.2f}s"
#                         )
#                         avg_acc_box.metric(
#                             "Avg Accuracy",
#                             f"{sum(accuracies)/len(accuracies):.1f}%" if accuracies else "N/A"
#                         )

#                         # 🔴 FULL REAL-TIME QUESTION + ANSWER VIEW
#                         with live_feed:
#                             with st.expander(
#                                 f"🔎 Test {i+1} | {api_res['Status']} | {api_res['Time(s)']}s",
#                                 expanded=True
#                             ):
#                                 st.markdown("**🟦 Question**")
#                                 st.write(question)

#                                 st.markdown("**🤖 Actual Answer**")
#                                 st.write(actual)

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




# # import streamlit as st
# # import requests
# # import pandas as pd
# # import time
# # from sentence_transformers import SentenceTransformer, util

# # # --- CONFIGURATION ---
# # API_URL = "https://functional-h3cjbjeeenhfapcx.canadacentral-01.azurewebsites.net/focus/faq"
# # API_KEY = "GN^CBB4185E5BFDAEDF7B1F172EE5F21"

# # st.set_page_config(page_title="Focus 2026 QA Dashboard", layout="wide", page_icon="🧪")

# # # --- LOAD AI MODEL (Cached) ---
# # @st.cache_resource
# # def load_semantic_model():
# #     return SentenceTransformer('all-MiniLM-L6-v2')

# # st.title("🧪 Focus 2026 API QA Suite")
# # st.markdown("Upload your **Variations File**. The system auto-detects `Question`, `Response`, and `User Type`.")

# # # --- SIDEBAR ---
# # with st.sidebar:
# #     st.header("⚙️ Configuration")
# #     global_user_type = st.selectbox("Fallback User Type", ["Employee", "Client"])

# #     st.divider()
# #     with st.spinner("Loading AI Judge..."):
# #         model = load_semantic_model()
# #     st.success("✅ AI Judge Ready")

# #     with st.expander("Advanced Params", expanded=False):
# #         vertical = st.text_input("Vertical", "")
# #         unit = st.text_input("Unit", "")
# #         company = st.text_input("Company", "Genpact")

# # # --- API FUNCTION (UNCHANGED) ---
# # def call_bot_safe(query, u_type):
# #     if pd.isna(u_type) or str(u_type).strip() == "":
# #         u_type = global_user_type

# #     headers = {"Content-Type": "application/json", "X-API-KEY": API_KEY}
# #     payload = {
# #         "query": str(query),
# #         "user_type": u_type,
# #         "vertical": vertical,
# #         "unit": unit,
# #         "company": company
# #     }

# #     try:
# #         start_time = time.time()
# #         response = requests.post(API_URL, json=payload, headers=headers, timeout=10)
# #         duration = round(time.time() - start_time, 2)

# #         if response.status_code == 200:
# #             data = response.json()
# #             return {
# #                 "Actual Answer": data.get("answer", "No Answer Field"),
# #                 "Source": data.get("sources", [{}])[0].get("source", "AI") if data.get("sources") else "AI",
# #                 "Time(s)": duration,
# #                 "Status": "PASS"
# #             }
# #         else:
# #             return {
# #                 "Actual Answer": f"API Error: {response.status_code}",
# #                 "Source": "N/A",
# #                 "Time(s)": duration,
# #                 "Status": "FAIL"
# #             }
# #     except Exception as e:
# #         return {
# #             "Actual Answer": f"Exception: {str(e)}",
# #             "Source": "Error",
# #             "Time(s)": 0,
# #             "Status": "CRASH"
# #         }

# # # --- UI TABS ---
# # tab1, tab2 = st.tabs(["📝 Manual Check", "🚀 Bulk Variations Test"])

# # # --- TAB 1: MANUAL ---
# # with tab1:
# #     col1, col2 = st.columns([4, 1])
# #     with col1:
# #         q = st.text_input("Ask a question:", placeholder="e.g. Who is the Kolkata rep?")
# #     with col2:
# #         st.write("")
# #         st.write("")
# #         if st.button("Send", type="primary"):
# #             with st.spinner("Thinking..."):
# #                 res = call_bot_safe(q, global_user_type)
# #                 if res["Status"] == "PASS":
# #                     st.success(f"Response ({res['Time(s)']}s)")
# #                     st.markdown(f"**🤖 Answer:** {res['Actual Answer']}")
# #                 else:
# #                     st.error(f"Failed: {res['Actual Answer']}")

# # # --- TAB 2: BULK TEST ---
# # with tab2:
# #     st.subheader("Upload Test File")
# #     st.info("Required Columns: `Question`, `Response`, `User Type`.")

# #     uploaded_file = st.file_uploader("Choose file", type=["csv", "xlsx"])

# #     if uploaded_file is not None:
# #         try:
# #             if uploaded_file.name.endswith('.csv'):
# #                 df = pd.read_csv(uploaded_file)
# #             else:
# #                 df = pd.read_excel(uploaded_file)

# #             df.columns = df.columns.str.strip()

# #             if 'User Type' in df.columns:
# #                 df['run_user_type'] = df['User Type']
# #             elif 'User_type' in df.columns:
# #                 df['run_user_type'] = df['User_type']
# #             else:
# #                 df['run_user_type'] = global_user_type

# #             if 'Response' in df.columns:
# #                 df['expected_answer'] = df['Response']
# #             elif 'Expected Answer' in df.columns:
# #                 df['expected_answer'] = df['Expected Answer']
# #             else:
# #                 df['expected_answer'] = None

# #             if "Question" not in df.columns:
# #                 st.error("❌ File MUST have a column named **'Question'**.")
# #             else:
# #                 st.success(f"✅ Loaded {len(df)} rows.")

# #                 if st.button("Run AI Test Suite", type="primary"):

# #                     # --- LIVE UI CONTAINERS ---
# #                     lifecycle = st.info("🟡 Preparing test run...")
# #                     progress = st.progress(0)

# #                     metrics_col1, metrics_col2, metrics_col3, metrics_col4 = st.columns(4)
# #                     pass_box = metrics_col1.metric("PASS", 0)
# #                     fail_box = metrics_col2.metric("FAIL", 0)
# #                     avg_lat_box = metrics_col3.metric("Avg Latency", "0.00s")
# #                     avg_acc_box = metrics_col4.metric("Avg Accuracy", "N/A")

# #                     live_feed = st.container()
# #                     results = []

# #                     pass_cnt = fail_cnt = 0
# #                     latencies = []
# #                     accuracies = []

# #                     lifecycle.info("🟠 Running tests...")

# #                     for i, row in df.iterrows():
# #                         question = row['Question']
# #                         u_type = row['run_user_type']
# #                         expected = row['expected_answer']
# #                         is_var = row.get('Is_variation', 'N/A')

# #                         if pd.isna(expected): expected = None
# #                         if pd.isna(u_type): u_type = global_user_type

# #                         api_res = call_bot_safe(question, u_type)
# #                         actual = api_res["Actual Answer"]

# #                         similarity_score = None
# #                         if expected and api_res["Status"] == "PASS":
# #                             emb1 = model.encode(str(expected), convert_to_tensor=True)
# #                             emb2 = model.encode(str(actual), convert_to_tensor=True)
# #                             similarity_score = round(util.pytorch_cos_sim(emb1, emb2).item() * 100, 1)
# #                             accuracies.append(similarity_score)

# #                         latencies.append(api_res["Time(s)"])

# #                         if api_res["Status"] == "PASS":
# #                             pass_cnt += 1
# #                         else:
# #                             fail_cnt += 1

# #                         pass_box.metric("PASS", pass_cnt)
# #                         fail_box.metric("FAIL", fail_cnt)
# #                         avg_lat_box.metric("Avg Latency", f"{sum(latencies)/len(latencies):.2f}s")
# #                         avg_acc_box.metric(
# #                             "Avg Accuracy",
# #                             f"{sum(accuracies)/len(accuracies):.1f}%" if accuracies else "N/A"
# #                         )

# #                         with live_feed:
# #                             st.write(
# #                                 f"**{i+1}.** {question[:80]}… | "
# #                                 f"Status: `{api_res['Status']}` | "
# #                                 f"Latency: {api_res['Time(s)']}s | "
# #                                 f"Score: {similarity_score}"
# #                             )

# #                         results.append({
# #                             "ID": i+1,
# #                             "User Type": u_type,
# #                             "Is Variation": is_var,
# #                             "Question": question,
# #                             "Expected": expected,
# #                             "Actual": actual,
# #                             "Accuracy (%)": similarity_score,
# #                             "Latency": api_res["Time(s)"],
# #                             "Status": api_res["Status"]
# #                         })

# #                         progress.progress((i + 1) / len(df))

# #                     lifecycle.success("🟢 Testing complete!")

# #                     result_df = pd.DataFrame(results)

# #                     def color_code(val):
# #                         if pd.isna(val): return ''
# #                         if val >= 85: return 'background-color: #c8e6c9'
# #                         if val >= 65: return 'background-color: #fff9c4'
# #                         return 'background-color: #ffcdd2'

# #                     st.dataframe(
# #                         result_df.style.map(color_code, subset=['Accuracy (%)']),
# #                         use_container_width=True
# #                     )

# #                     csv_data = result_df.to_csv(index=False).encode('utf-8')
# #                     st.download_button(
# #                         "⬇️ Download Test Report",
# #                         csv_data,
# #                         "test_report.csv",
# #                         "text/csv"
# #                     )

# #         except Exception as e:
# #             st.error(f"Error processing file: {e}")







# # import streamlit as st
# # import requests
# # import pandas as pd
# # import time
# # from sentence_transformers import SentenceTransformer, util

# # # --- CONFIGURATION ---
# # API_URL = "https://functional-h3cjbjeeenhfapcx.canadacentral-01.azurewebsites.net/focus/faq"
# # API_KEY = "GN^CBB4185E5BFDAEDF7B1F172EE5F21"

# # st.set_page_config(page_title="Focus 2026 QA Dashboard", layout="wide", page_icon="🧪")

# # # --- LOAD AI MODEL (Cached) ---
# # @st.cache_resource
# # def load_semantic_model():
# #     # Downloads a small, fast AI model to judge answer quality
# #     return SentenceTransformer('all-MiniLM-L6-v2')

# # st.title("🧪 Focus 2026 API QA Suite")
# # st.markdown("Upload your **Variations File**. The system auto-detects `Question`, `Response`, and `User Type`.")

# # # --- SIDEBAR ---
# # with st.sidebar:
# #     st.header("⚙️ Configuration")
# #     global_user_type = st.selectbox("Fallback User Type", ["Employee", "Client"])
    
# #     st.divider()
# #     with st.spinner("Loading AI Judge..."):
# #         model = load_semantic_model()
# #     st.success("✅ AI Judge Ready")
    
# #     with st.expander("Advanced Params", expanded=False):
# #         vertical = st.text_input("Vertical", "")
# #         unit = st.text_input("Unit", "")
# #         company = st.text_input("Company", "Genpact")

# # # --- API FUNCTION ---
# # def call_bot_safe(query, u_type):
# #     # Fallback if User Type is missing in the file
# #     if pd.isna(u_type) or str(u_type).strip() == "":
# #         u_type = global_user_type
        
# #     headers = {"Content-Type": "application/json", "X-API-KEY": API_KEY}
# #     payload = {
# #         "query": str(query),
# #         "user_type": u_type,
# #         "vertical": vertical,
# #         "unit": unit,
# #         "company": company
# #     }
    
# #     try:
# #         start_time = time.time()
# #         response = requests.post(API_URL, json=payload, headers=headers, timeout=10)
# #         duration = round(time.time() - start_time, 2)
        
# #         if response.status_code == 200:
# #             data = response.json()
# #             return {
# #                 "Actual Answer": data.get("answer", "No Answer Field"),
# #                 "Source": data.get("sources", [{}])[0].get("source", "AI") if data.get("sources") else "AI",
# #                 "Time(s)": duration,
# #                 "Status": "PASS"
# #             }
# #         else:
# #             return {
# #                 "Actual Answer": f"API Error: {response.status_code}",
# #                 "Source": "N/A",
# #                 "Time(s)": duration,
# #                 "Status": "FAIL"
# #             }
# #     except Exception as e:
# #         return {
# #             "Actual Answer": f"Exception: {str(e)}",
# #             "Source": "Error",
# #             "Time(s)": 0,
# #             "Status": "CRASH"
# #         }

# # # --- UI TABS ---
# # tab1, tab2 = st.tabs(["📝 Manual Check", "🚀 Bulk Variations Test"])

# # # --- TAB 1: MANUAL ---
# # with tab1:
# #     col1, col2 = st.columns([4, 1])
# #     with col1:
# #         q = st.text_input("Ask a question:", placeholder="e.g. Who is the Kolkata rep?")
# #     with col2:
# #         st.write("") 
# #         st.write("") 
# #         if st.button("Send", type="primary"):
# #             with st.spinner("Thinking..."):
# #                 res = call_bot_safe(q, global_user_type)
# #                 if res["Status"] == "PASS":
# #                     st.success(f"Response ({res['Time(s)']}s)")
# #                     st.markdown(f"**🤖 Answer:** {res['Actual Answer']}")
# #                 else:
# #                     st.error(f"Failed: {res['Actual Answer']}")

# # # --- TAB 2: BULK TEST ---
# # with tab2:
# #     st.subheader("Upload Test File")
# #     st.info("Required Columns: `Question`, `Response`, `User Type`.")
    
# #     uploaded_file = st.file_uploader("Choose file", type=["csv", "xlsx"])
    
# #     if uploaded_file is not None:
# #         try:
# #             # Load Data
# #             if uploaded_file.name.endswith('.csv'):
# #                 df = pd.read_csv(uploaded_file)
# #             else:
# #                 df = pd.read_excel(uploaded_file)
            
# #             # 1. NORMALIZE COLUMNS
# #             df.columns = df.columns.str.strip()
            
# #             # 2. SMART MAPPING (Handles your specific file headers)
# #             # Map 'User Type' -> 'run_user_type'
# #             if 'User Type' in df.columns:
# #                 df['run_user_type'] = df['User Type']
# #             elif 'User_type' in df.columns:
# #                 df['run_user_type'] = df['User_type']
# #             else:
# #                 df['run_user_type'] = global_user_type

# #             # Map 'Response' -> 'expected_answer'
# #             if 'Response' in df.columns:
# #                 df['expected_answer'] = df['Response']
# #             elif 'Expected Answer' in df.columns:
# #                 df['expected_answer'] = df['Expected Answer']
# #             else:
# #                 df['expected_answer'] = None

# #             # Check Mandatory Column
# #             if "Question" not in df.columns:
# #                 st.error("❌ File MUST have a column named **'Question'**.")
# #                 st.write("Found columns:", list(df.columns))
# #             else:
# #                 st.success(f"✅ Loaded {len(df)} rows.")
                
# #                 if st.button(f"Run AI Test Suite", type="primary"):
                    
# #                     progress_bar = st.progress(0)
# #                     status_text = st.empty()
# #                     results = []
                    
# #                     for i, row in df.iterrows():
# #                         question = row['Question']
# #                         u_type = row['run_user_type']
# #                         expected = row['expected_answer']
# #                         is_var = row.get('Is_variation', 'N/A') # Capture variation flag if present
                        
# #                         # Handle NaN
# #                         if pd.isna(expected): expected = None
# #                         if pd.isna(u_type): u_type = global_user_type
                        
# #                         status_text.text(f"Testing {i+1}/{len(df)}...")
                        
# #                         # Call API
# #                         api_res = call_bot_safe(question, u_type)
# #                         actual = api_res["Actual Answer"]
                        
# #                         # --- AI SCORING ---
# #                         similarity_score = 0.0
# #                         if expected and api_res["Status"] == "PASS":
# #                             # Compare Meaning
# #                             emb1 = model.encode(str(expected), convert_to_tensor=True)
# #                             emb2 = model.encode(str(actual), convert_to_tensor=True)
# #                             similarity_score = util.pytorch_cos_sim(emb1, emb2).item() * 100
# #                             similarity_score = round(similarity_score, 1)
# #                         else:
# #                             similarity_score = None
                        
# #                         results.append({
# #                             "ID": i+1,
# #                             "User Type": u_type,
# #                             "Is Variation": is_var,
# #                             "Question": question,
# #                             "Expected": expected,
# #                             "Actual": actual,
# #                             "Accuracy (%)": similarity_score, # AI Score
# #                             "Latency": api_res["Time(s)"],
# #                             "Status": api_res["Status"]
# #                         })
                        
# #                         progress_bar.progress((i + 1) / len(df))
                    
# #                     status_text.text("✅ Testing Complete!")
# #                     result_df = pd.DataFrame(results)
                    
# #                     # METRICS
# #                     c1, c2, c3 = st.columns(3)
# #                     pass_rate = len(result_df[result_df["Status"]=="PASS"]) / len(result_df) * 100
# #                     c1.metric("System Stability", f"{pass_rate:.1f}%")
                    
# #                     # Avg AI Score (ignoring N/A)
# #                     scored_df = result_df.dropna(subset=["Accuracy (%)"])
# #                     if not scored_df.empty:
# #                         avg_acc = scored_df["Accuracy (%)"].mean()
# #                         c2.metric("🧠 Semantic Accuracy", f"{avg_acc:.1f}%")
                    
# #                     avg_lat = result_df["Latency"].mean()
# #                     c3.metric("Avg Latency", f"{avg_lat:.2f}s")

# #                     # COLOR CODING
# #                     def color_code(val):
# #                         if pd.isna(val): return ''
# #                         if val >= 85: return 'background-color: #c8e6c9' # Green (Excellent)
# #                         if val >= 65: return 'background-color: #fff9c4' # Yellow (Okay)
# #                         return 'background-color: #ffcdd2' # Red (Bad)

# #                     st.dataframe(
# #                         result_df.style.map(color_code, subset=['Accuracy (%)']), 
# #                         use_container_width=True
# #                     )
                    
# #                     # DOWNLOAD
# #                     csv_data = result_df.to_csv(index=False).encode('utf-8')
# #                     st.download_button("Download Report", csv_data, "test_report.csv", "text/csv")

# #         except Exception as e:
# #             st.error(f"Error processing file: {e}")
