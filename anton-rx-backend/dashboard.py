import streamlit as st
import sqlite3
import pandas as pd
import os
import subprocess
import sys

# Set page config
st.set_page_config(page_title="Anton Rx Policy Dashboard", page_icon="💊", layout="wide")

st.title("💊 Anton Rx - Medical Policy Dashboard")
st.markdown("Upload medical policies, run the pipeline, and view extracted data.")

# --- HELPERS ---
def delete_document(doc_id):
    conn = sqlite3.connect("anton_rx.db", timeout=30)
    cursor = conn.cursor()
    # Assuming 'id' is the primary key of documents table based on schema conventions
    cursor.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    cursor.execute("DELETE FROM drug_policies WHERE document_id = ?", (doc_id,))
    conn.commit()
    conn.close()
    load_data.clear()

def get_schema():
    conn = sqlite3.connect("anton_rx.db", timeout=30)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    
    schema = {}
    for (tbl_name,) in tables:
        df_info = pd.read_sql_query(f"PRAGMA table_info({tbl_name})", conn)
        schema[tbl_name] = df_info[['cid', 'name', 'type', 'notnull', 'dflt_value', 'pk']]
    conn.close()
    return schema

# --- DATA LOADING ---
@st.cache_data
def load_data():
    conn = sqlite3.connect("anton_rx.db", timeout=30)
    
    # Check if tables exist
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='drug_policies'")
    if not cursor.fetchone():
        conn.close()
        return pd.DataFrame(), pd.DataFrame()
        
    df_drugs = pd.read_sql_query("SELECT * FROM drug_policies", conn)
    df_docs = pd.read_sql_query("SELECT * FROM documents", conn)
    conn.close()
    return df_drugs, df_docs

try:
    df_drugs, df_docs = load_data()
except Exception as e:
    st.error(f"Database error: {e}. Ensure `anton_rx.db` exists in the folder.")
    df_drugs, df_docs = pd.DataFrame(), pd.DataFrame()

# --- SIDEBAR: PIPELINE UPLOADER ---
st.sidebar.header("1. Upload New Policy")
uploaded_file = st.sidebar.file_uploader("Upload a PDF to Ingest", type=["pdf"])

if uploaded_file is not None:
    if st.sidebar.button("Run Extraction Pipeline", type="primary"):
        upload_dir = "uploads"
        os.makedirs(upload_dir, exist_ok=True)
        pdf_path = os.path.join(upload_dir, uploaded_file.name)
        
        with open(pdf_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        
        # Start processing inline in the main page
        with st.status(f"Running Ingestion Pipeline on `{uploaded_file.name}`...", expanded=True) as status:
            cmd = [sys.executable, "main.py", "--pdf", pdf_path]
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, 
                text=True,
                bufsize=1,
                encoding='utf-8', 
                errors='replace'
            )
            
            # --- PROGRESS TRACKER UI ---
            steps = ["Discovery", "Page Maps", "Extraction", "Validation", "Database"]
            cols = st.columns(5)
            # Create a placeholder in each column
            step_boxes = [col.empty() for col in cols]
            
            def update_steps(active_idx):
                for i, box in enumerate(step_boxes):
                    if i < active_idx:
                        # Completed
                        box.success(f"✔️ {steps[i]}")
                    elif i == active_idx:
                        # Current
                        box.info(f"🔄 {steps[i]}...")
                    else:
                        # Pending
                        box.caption(f"⏳ {steps[i]}")
            
            # Initial state
            update_steps(0)
            
            for line in process.stdout:
                clean_line = line.strip()
                if not clean_line:
                    continue
                    
                # Match pipeline logging stages based on output
                if "Stage 1" in clean_line:
                    update_steps(0)
                elif "Stage 2" in clean_line:
                    update_steps(1)
                elif "Stage 3" in clean_line:
                    update_steps(2)
                elif "Stage 4" in clean_line:
                    update_steps(3)
                elif "Stage 5" in clean_line:
                    update_steps(4)
                
            process.wait()
            
            if process.returncode == 0:
                # Mark final step complete
                update_steps(5)
                status.update(label="Ingestion Complete!", state="complete", expanded=False)
                st.sidebar.success("Successfully ingested document.")
                load_data.clear()
                st.rerun()
            else:
                status.update(label="Ingestion Failed", state="error", expanded=True)
                st.error("Pipeline encountered an error during processing. Check terminal for raw logs.")

st.sidebar.divider()

# --- SIDEBAR: FILTERS ---
st.sidebar.header("2. Filter Data")

# Category Filter
if not df_drugs.empty and 'drug_category' in df_drugs.columns:
    categories = ["All"] + [str(x) for x in df_drugs['drug_category'].dropna().unique()]
    selected_cat = st.sidebar.selectbox("Drug Category", categories)
else:
    selected_cat = "All"

# Coverage Filter
if not df_drugs.empty and 'coverage_status' in df_drugs.columns:
    coverage_statuses = ["All"] + [str(x) for x in df_drugs['coverage_status'].dropna().unique()]
    selected_cov = st.sidebar.selectbox("Coverage Status", coverage_statuses)
else:
    selected_cov = "All"

# PA Required Filter
if not df_drugs.empty and 'prior_auth_required' in df_drugs.columns:
    pa_filter = st.sidebar.radio("Prior Auth Required?", ["All", "Yes", "No"])
else:
    pa_filter = "All"

# Search Bar
search_query = st.sidebar.text_input("Search Brand / Generic Name", "")

if st.sidebar.button("🔄 Force Reload Data"):
    load_data.clear()
    st.rerun()

# --- MAIN TABS ---
tab_dashboard, tab_docs, tab_schema = st.tabs(["Dashboard", "Processed Documents", "Database Schema"])

with tab_dashboard:
    # --- KPIs ---
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("📄 Processed Documents", len(df_docs))
    col2.metric("💊 Total Extracted Drugs", len(df_drugs))

    if not df_drugs.empty:
        high_conf = len(df_drugs[df_drugs['_confidence'] == 'HIGH'])
        pa_req = len(df_drugs[df_drugs['prior_auth_required'].astype(str).str.upper() == 'YES'])
        
        perc_high_conf = (high_conf / len(df_drugs)) * 100 if len(df_drugs) > 0 else 0
        col3.metric("🎯 High Confidence Extracts", f"{perc_high_conf:.1f}%")
        col4.metric("⚠️ Prior Auth Required", pa_req)

        st.divider()

        # Apply Filters
        filtered_df = df_drugs.copy()
        if selected_cat != "All":
            filtered_df = filtered_df[filtered_df['drug_category'].astype(str) == selected_cat]
        if selected_cov != "All":
            filtered_df = filtered_df[filtered_df['coverage_status'].astype(str) == selected_cov]
        if pa_filter != "All":
            pa_match = 'YES' if pa_filter == "Yes" else 'NO'
            filtered_df = filtered_df[filtered_df['prior_auth_required'].astype(str).str.upper() == pa_match]
        if search_query:
            # search across brand or generic names
            filtered_df = filtered_df[
                filtered_df['brand_name'].astype(str).str.contains(search_query, case=False, na=False) |
                filtered_df['generic_name'].astype(str).str.contains(search_query, case=False, na=False)
            ]

        # --- MAIN TABLE ---
        st.subheader(f"Extracted Drug Policies ({len(filtered_df)} results)")
        
        # Reorder columns to show important ones first
        display_cols = ['brand_name', 'generic_name', 'drug_category', 'coverage_status', 'prior_auth_required', '_confidence']
        available_cols = [c for c in display_cols if c in filtered_df.columns]
        
        st.dataframe(filtered_df[available_cols], width="stretch", hide_index=True)

        # --- DETAIL EXPLORER ---
        st.subheader("🔍 Prior Auth Criteria Explorer")
        st.markdown("Select a drug from the dropdown to read the full criteria paragraphs from the policy document.")
        
        if not filtered_df.empty:
            # Create a dropdown mapping brand/generic for the selector
            options = []
            for _, row in filtered_df.iterrows():
                lbl = f"{row.get('brand_name', 'Unknown')} ({row.get('generic_name', 'Unknown')})"
                options.append((row['brand_name'], lbl))
                
            selected_option = st.selectbox("Select Drug:", options, format_func=lambda x: str(x[1]))
            
            if selected_option:
                drug_name = selected_option[0]
                drug_data = filtered_df[filtered_df['brand_name'] == drug_name].iloc[0]
                
                st.info(f"**Coverage:** {drug_data.get('coverage_status', 'N/A')}  |  **PA Required:** {drug_data.get('prior_auth_required', 'N/A')}")
                
                pa_text = drug_data.get('prior_auth_criteria', '')
                if pd.isna(pa_text) or not str(pa_text).strip() or str(pa_text).strip().lower() == "nan":
                    st.write("*No prior authorization criteria listed.*")
                else:
                    st.write("**Full Criteria:**")
                    # display in a code block or markdown text so scrolling is easy to read
                    st.markdown(f"> {str(pa_text).replace(chr(10), chr(10)+'> ')}")

                if 'pdf_page_number' in drug_data and pd.notna(drug_data['pdf_page_number']):
                    st.caption(f"Found on page {drug_data['pdf_page_number']} of source document.")
                    
    else:
        st.info("No policy data available yet in the database. Use the sidebar to upload and run the pipeline on a PDF.")

with tab_docs:
    st.subheader("Processed Documents")
    if not df_docs.empty:
        st.dataframe(df_docs, width="stretch", hide_index=True)
        
        st.markdown("### Document Management")
        st.write("Deleting a document will permanently remove its metadata and all associated extracted drug policies from the database.")
        
        doc_options = {row['id']: f"{row['id']} - {row['source_file']}" for _, row in df_docs.iterrows()}
        selected_doc_id = st.selectbox("Select a document to delete:", options=list(doc_options.keys()), format_func=lambda x: doc_options[x])
        
        if st.button("🗑️ Delete Document", type="secondary"):
            if selected_doc_id:
                delete_document(selected_doc_id)
                st.success(f"Deleted document {selected_doc_id} and all associated drugs.")
                st.rerun()
    else:
        st.info("No documents have been processed yet.")

with tab_schema:
    st.subheader("Database Schema")
    st.markdown("Below is the structural schema of `anton_rx.db` including all tables and their columns.")
    
    schema_info = get_schema()
    for table_name, df_schema in schema_info.items():
        with st.expander(f"📦 Table: {table_name}", expanded=True):
            st.dataframe(df_schema, width="stretch", hide_index=True)
