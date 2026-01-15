import streamlit as st
import requests
import pandas as pd
import time

# --- CONFIGURATION ---
API_URL = "https://functional-h3cjbjeeenhfapcx.canadacentral-01.azurewebsites.net/focus/faq"
API_KEY = "GN^CBB4185E5BFDAEDF7B1F172EE5F21"

st.set_page_config(page_title="Focus 2026 QA Dashboard", layout="wide", page_icon="🧪")

st.title("🧪 Focus 2026 API QA Suite")
st.markdown("Upload your FAQ file directly. The system will handle missing S.No automatically.")

# --- SIDEBAR CONFIG ---
with st.sidebar:
    st.header("⚙️ Configuration")
    global_user_type = st.selectbox("Default User Type (Fallback)", ["Employee", "Client"])
    
    st.divider()
    with st.expander("Advanced Params", expanded=False):
        vertical = st.text_input("Vertical", "")
        unit = st.text_input("Unit", "")
        company = st.text_input("Company", "Genpact")

# --- ROBUST API FUNCTION ---
def call_bot_safe(query, u_type):
    """
    Calls the bot and handles ANY crash so the loop never stops.
    """
    # Safety: If file has empty User Type, use the Global Default
    if pd.isna(u_type) or str(u_type).strip() == "":
        u_type = global_user_type
        
    headers = {"Content-Type": "application/json", "X-API-KEY": API_KEY}
    payload = {
        "query": str(query), # Ensure it's a string
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
tab1, tab2 = st.tabs(["📝 Single Query", "🚀 Bulk Upload & Test"])

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

# --- TAB 2: BULK TEST ---
with tab2:
    st.subheader("Upload FAQ File")
    st.info("Supports CSV or Excel (.xlsx). Required column: **'Question'**. Optional: 'User Type', 'Response'.")
    
    # Allow both CSV and Excel
    uploaded_file = st.file_uploader("Choose file", type=["csv", "xlsx"])
    
    if uploaded_file is not None:
        try:
            # Load based on extension
            if uploaded_file.name.endswith('.csv'):
                df = pd.read_csv(uploaded_file)
            else:
                df = pd.read_excel(uploaded_file)
            
            # Clean column names (strip spaces like 'User Type ' -> 'User Type')
            df.columns = df.columns.str.strip()
            
            # Validation
            if "Question" not in df.columns:
                st.error("❌ File MUST have a column named **'Question'**.")
                st.write("Found columns:", list(df.columns))
            else:
                st.success(f"✅ Loaded {len(df)} rows. Ready to test.")
                
                if st.button(f"Run {len(df)} Tests", type="primary"):
                    
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    results = []
                    
                    for i, row in df.iterrows():
                        question = row['Question']
                        
                        # Handle potential missing User Type column
                        u_type = row['User Type'] if 'User Type' in df.columns else global_user_type
                        
                        # Handle Expected Response for comparison
                        expected = row['Response'] if 'Response' in df.columns else "N/A"
                        
                        status_text.text(f"Testing {i+1}/{len(df)}: {str(question)[:30]}...")
                        
                        # API Call
                        api_res = call_bot_safe(question, u_type)
                        
                        results.append({
                            "Row": i+1,
                            "User Type": u_type if not pd.isna(u_type) else global_user_type,
                            "Question": question,
                            "Expected Response": expected,  # Added this column!
                            "Actual Answer": api_res["Actual Answer"],
                            "Source": api_res["Source"],
                            "Latency": api_res["Time(s)"],
                            "Status": api_res["Status"]
                        })
                        
                        progress_bar.progress((i + 1) / len(df))
                    
                    status_text.text("✅ Testing Complete!")
                    
                    # Create Result DF
                    result_df = pd.DataFrame(results)
                    
                    # Interactive Table
                    st.dataframe(
                        result_df.style.apply(
                            lambda x: ['background-color: #ffcdd2' if v == 'FAIL' or v == 'CRASH' else '' for v in x], 
                            axis=1
                        ), 
                        use_container_width=True
                    )
                    
                    # Download
                    csv_data = result_df.to_csv(index=False).encode('utf-8')
                    st.download_button("Download Comparison Report", csv_data, "faq_test_results.csv", "text/csv")

        except Exception as e:
            st.error(f"Error reading file: {e}")
