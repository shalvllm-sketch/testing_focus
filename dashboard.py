import streamlit as st
import requests
import json
import pandas as pd

# --- CONFIGURATION ---
API_URL = "https://functional-h3cjbjeeenhfapcx.canadacentral-01.azurewebsites.net/focus/faq"
API_KEY = "GN^CBB4185E5BFDAEDF7B1F172EE5F21"  # Your API Key

# Page Setup
st.set_page_config(page_title="Focus 2026 Bot Tester", layout="wide")
st.title("🤖 Focus 2026 API Tester")

# --- SIDEBAR CONFIG ---
with st.sidebar:
    st.header("⚙️ Configuration")
    user_type = st.selectbox("Select User Type", ["Employee", "Client"])
    
    st.divider()
    st.markdown("**Test Parameters**")
    vertical = st.text_input("Vertical", "")
    unit = st.text_input("Unit", "")
    company = st.text_input("Company", "Genpact")
    
# --- FUNCTION TO CALL API ---
def call_bot(query, u_type):
    headers = {
        "Content-Type": "application/json",
        "X-API-KEY": API_KEY
    }
    payload = {
        "query": query,
        "user_type": u_type,
        "vertical": vertical,
        "unit": unit,
        "company": company,
        "title": "Tester"
    }
    
    try:
        response = requests.post(API_URL, json=payload, headers=headers)
        return response.json()
    except Exception as e:
        return {"error": str(e)}

# --- TAB 1: MANUAL TESTING ---
tab1, tab2 = st.tabs(["📝 Manual Test", "🚀 Bulk Test Suite"])

with tab1:
    st.subheader("Single Query Test")
    
    col1, col2 = st.columns([3, 1])
    with col1:
        user_query = st.text_input("Enter your question:", placeholder="e.g., Who will arrange my airport transfer?")
    with col2:
        st.write("") # Spacer
        st.write("") # Spacer
        trigger = st.button("Ask Bot", type="primary")

    if trigger and user_query:
        with st.spinner("Bot is thinking..."):
            result = call_bot(user_query, user_type)
            
            # Display Answer nicely
            if "answer" in result:
                st.success("Response Received")
                st.markdown(f"**🗣️ Answer:** {result['answer']}")
                
                with st.expander("View Full JSON Response"):
                    st.json(result)
            else:
                st.error("Error or unexpected format")
                st.json(result)

# --- TAB 2: BULK TESTING ---
with tab2:
    st.subheader("Run All Test Cases")
    st.info(f"Running tests as: **{user_type}**")
    
    # Define your test cases here (Add as many as you want)
    test_cases = [
        "Who will be the local representative from Genpact at Kolkata Airport?",
        "Who will arrange my airport to hotel transfer?",
        "Can I get a room in ITC Royal?",
        "Whom to connect with in case on any change in my travel itenary?",
        "Will we have access to AV equipment and technical support during our sessions?",
        "What are my flight details?"
    ]
    
    if st.button("Run All Tests"):
        results_data = []
        progress_bar = st.progress(0)
        
        for i, q in enumerate(test_cases):
            res = call_bot(q, user_type)
            answer = res.get("answer", "Error")
            
            results_data.append({
                "Question": q,
                "Answer": answer,
                "Status": "✅" if "error" not in res else "❌"
            })
            progress_bar.progress((i + 1) / len(test_cases))
            
        # Show as a nice table
        df = pd.DataFrame(results_data)
        st.dataframe(df, use_container_width=True)
        
        # Download Button
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button("Download Report (CSV)", csv, "test_results.csv", "text/csv")
