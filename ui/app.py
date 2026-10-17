"""
Streamlit Web UI for Sovereign On-Premise Agentic AI Workbench.
Offline, privacy-first interface featuring:
- Sovereign Dark Glassmorphism design system
- Ollama runtime health & active model status badge
- Multi-tab navigation: Chat, Documents, Agents, Traces, Approvals, Audit Logs, Auth
- Interactive human-in-the-loop approval actions
- Full citation rendering and step latency breakdown
"""

import os
import json
import requests
import streamlit as st

# Configure page settings
st.set_page_config(
    page_title="Sovereign AI Workbench",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")

# ==============================================================================
# Custom CSS for Premium Sovereign Dark Aesthetics
# ==============================================================================
st.markdown("""
<style>
    /* Offline Native Typography (Zero Cloud Egress) */
    html, body, [class*="css"] {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    }
    
    code, pre {
        font-family: Consolas, "JetBrains Mono", "Courier New", monospace !important;
    }

    /* Main Container Padding */
    .block-container {
        padding-top: 1.8rem;
        padding-bottom: 3rem;
    }

    /* Sovereign Header Styling */
    .sov-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        background: linear-gradient(135deg, rgba(20, 24, 39, 0.85) 0%, rgba(15, 17, 26, 0.95) 100%);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 16px;
        padding: 1.2rem 1.6rem;
        margin-bottom: 1.5rem;
        backdrop-filter: blur(16px);
        box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
    }

    .sov-title {
        font-size: 1.5rem;
        font-weight: 700;
        background: linear-gradient(90deg, #60A5FA 0%, #A78BFA 50%, #F472B6 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin: 0;
    }

    .sov-subtitle {
        font-size: 0.85rem;
        color: #94A3B8;
        margin-top: 2px;
    }

    /* Status Pill Badges */
    .status-pill {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 5px 12px;
        border-radius: 9999px;
        font-size: 0.75rem;
        font-weight: 600;
        letter-spacing: 0.025em;
        text-transform: uppercase;
    }

    .status-pill-online {
        background: rgba(16, 185, 129, 0.15);
        color: #34D399;
        border: 1px solid rgba(16, 185, 129, 0.3);
    }

    .status-pill-offline {
        background: rgba(239, 68, 68, 0.15);
        color: #F87171;
        border: 1px solid rgba(239, 68, 68, 0.3);
    }

    .role-badge-admin {
        background: linear-gradient(135deg, #7C3AED 0%, #4F46E5 100%);
        color: #FFFFFF;
        padding: 3px 10px;
        border-radius: 8px;
        font-size: 0.7rem;
        font-weight: 700;
    }

    .role-badge-user {
        background: rgba(59, 130, 246, 0.2);
        color: #60A5FA;
        border: 1px solid rgba(59, 130, 246, 0.4);
        padding: 3px 10px;
        border-radius: 8px;
        font-size: 0.7rem;
        font-weight: 700;
    }

    /* Citation Card */
    .citation-card {
        background: rgba(30, 41, 59, 0.6);
        border-left: 3px solid #8B5CF6;
        border-radius: 8px;
        padding: 10px 14px;
        margin-top: 10px;
        margin-bottom: 10px;
        font-size: 0.85rem;
        color: #CBD5E1;
    }

    /* Approval Banner */
    .approval-box {
        background: linear-gradient(135deg, rgba(245, 158, 11, 0.1) 0%, rgba(217, 119, 6, 0.15) 100%);
        border: 1px solid rgba(245, 158, 11, 0.4);
        border-radius: 12px;
        padding: 1rem 1.4rem;
        margin: 1rem 0;
    }

    /* Step Trace Pill */
    .trace-step-type {
        font-size: 0.7rem;
        font-weight: 700;
        padding: 2px 8px;
        border-radius: 6px;
        text-transform: uppercase;
    }
    .trace-llm { background: #3B82F6; color: white; }
    .trace-tool { background: #10B981; color: white; }
    .trace-policy { background: #F59E0B; color: white; }
    .trace-retry { background: #EC4899; color: white; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# Session State Initialization
# ==============================================================================
if "token" not in st.session_state:
    st.session_state.token = None
if "user_info" not in st.session_state:
    st.session_state.user_info = None
if "active_agent" not in st.session_state:
    st.session_state.active_agent = None


# ==============================================================================
# Helper Functions for API Calls
# ==============================================================================
def get_auth_headers():
    if st.session_state.token:
        return {"Authorization": f"Bearer {st.session_state.token}"}
    return {}


# Check token validity and role sync on each render
if st.session_state.token:
    try:
        me_res = requests.get(f"{BACKEND_URL}/auth/me", headers={"Authorization": f"Bearer {st.session_state.token}"}, timeout=2.0)
        if me_res.status_code == 401:
            st.session_state.token = None
            st.session_state.user_info = None
            st.warning("⚠️ Session expired or invalid. Please log in again.")
        elif me_res.status_code == 200:
            data = me_res.json()
            if isinstance(data, dict) and "role" in data:
                st.session_state.user_info = data
    except Exception:
        pass


def fetch_health():
    try:
        r = requests.get(f"{BACKEND_URL}/health", timeout=3.0)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


# ==============================================================================
# Header & Runtime Health Banner
# ==============================================================================
health_data = fetch_health()
ollama_online = False
ollama_model_name = "N/A"

if health_data and "ollama" in health_data:
    ollama_info = health_data["ollama"]
    ollama_online = ollama_info.get("reachable", False)
    ollama_model_name = ollama_info.get("configured_chat_model", "mistral")

header_col1, header_col2 = st.columns([3, 1])

with header_col1:
    st.markdown("""
    <div style="margin-bottom: 0.8rem;">
        <h2 style="margin: 0; font-weight: 800; letter-spacing: -0.02em;">
            🛡️ Sovereign On-Premise AI Workbench
        </h2>
        <p style="margin: 2px 0 0 0; color: #94A3B8; font-size: 0.9rem;">
            Offline &bull; Zero Cloud Egress &bull; Built-in Policy Engine &bull; Human-in-the-Loop Governance
        </p>
    </div>
    """, unsafe_allow_html=True)

with header_col2:
    if ollama_online:
        st.markdown(
            f'<div style="text-align: right;"><span class="status-pill status-pill-online">🟢 Host Ollama Online ({ollama_model_name})</span></div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div style="text-align: right;"><span class="status-pill status-pill-offline">🔴 Host Ollama Offline</span></div>',
            unsafe_allow_html=True,
        )

# ==============================================================================
# Sidebar: User Profile & Authentication State
# ==============================================================================
with st.sidebar:
    st.markdown("### 🔐 User Session")
    if st.session_state.token and st.session_state.user_info:
        u = st.session_state.user_info
        role = u.get("role", "user")
        role_badge = '<span class="role-badge-admin">ADMIN</span>' if role == "admin" else '<span class="role-badge-user">USER</span>'
        
        st.markdown(f"""
        **Logged in as:** `{u.get('username')}`  
        **Role:** {role_badge}
        """, unsafe_allow_html=True)

        if st.button("🚪 Logout", use_container_width=True):
            st.session_state.token = None
            st.session_state.user_info = None
            st.rerun()
    else:
        st.info("Please register or log in using the **Account** tab.")

    st.markdown("---")
    st.markdown("### ⚙️ System Status")
    st.caption(f"**Backend API:** `{BACKEND_URL}`")
    st.caption(f"**Chat Model:** `{ollama_model_name}`")
    st.caption("**Embed Model:** `nomic-embed-text`")
    st.caption("**Context Window:** `4096 tokens max`")
    st.caption("**Memory Budget:** `8 GB RAM Native`")

# ==============================================================================
# Navigation Tabs
# ==============================================================================
is_admin = bool(
    st.session_state.token
    and st.session_state.user_info
    and st.session_state.user_info.get("role") == "admin"
)

if is_admin:
    tab_titles = [
        "💬 Chat",
        "📂 Documents",
        "🤖 Agents",
        "🔍 Traces",
        "🛡️ Approvals",
        "📋 Audit Log",
        "📊 Evaluation",
        "👤 Account",
    ]

else:
    tab_titles = [
        "💬 Chat",
        "📂 Documents",
        "🔍 Traces",
        "🛡️ Approvals",
        "👤 Account",
    ]

tabs = st.tabs(tab_titles)
tab_dict = {title: tab for title, tab in zip(tab_titles, tabs)}

# ------------------------------------------------------------------------------
# TAB: CHAT
# ------------------------------------------------------------------------------
with tab_dict["💬 Chat"]:
    st.subheader("💬 Chat with AI Agents")

    if not st.session_state.token:
        st.warning("⚠️ Please log in from the **Account** tab to chat with agents.")
    else:
        # Fetch available agents
        try:
            agents_res = requests.get(f"{BACKEND_URL}/agents", headers=get_auth_headers(), timeout=5.0)
            agents = agents_res.json() if agents_res.status_code == 200 else []
        except Exception:
            agents = []

        if not agents:
            st.info("No agents found. Start the backend or create an agent in the Agents tab.")
        else:
            agent_names = [a["name"] for a in agents]
            selected_name = st.selectbox("Select Agent", agent_names, key="chat_agent_selector")
            current_agent = next((a for a in agents if a["name"] == selected_name), None)

            if current_agent:
                with st.expander("ℹ️ Agent Capabilities & System Prompt", expanded=False):
                    st.write(f"**Model:** `{current_agent['model']}` | **Temperature:** `{current_agent['temperature']}`")
                    st.write(f"**Allowed Tools:** {', '.join([f'`{t}`' for t in current_agent['allowed_tools']])}")
                    st.caption(f"**System Prompt:** {current_agent['system_prompt']}")

                # User question input
                user_question = st.text_area(
                    "Ask a question or provide a task:",
                    placeholder="e.g. 'What is the highest GPA in the students table?' or 'Search documents for revenue figures'",
                    height=100,
                )

                col_run, col_clear = st.columns([1, 5])
                with col_run:
                    run_btn = st.button("🚀 Run Agent", type="primary", use_container_width=True)

                if run_btn:
                    if not user_question.strip():
                        st.error("Please enter a question or instruction.")
                    else:
                        with st.spinner("🤖 Agent is thinking, analyzing tools, and verifying policy..."):
                            try:
                                payload = {"question": user_question.strip()}
                                run_resp = requests.post(
                                    f"{BACKEND_URL}/agents/{current_agent['id']}/run",
                                    headers=get_auth_headers(),
                                    json=payload,
                                    timeout=130.0,
                                )

                                if run_resp.status_code == 200:
                                    res_data = run_resp.json()
                                    status = res_data.get("status")

                                    if status == "completed":
                                        st.success("✅ Run Completed Successfully")
                                        st.markdown("### Answer")
                                        st.markdown(res_data.get("answer", ""))

                                        sources = res_data.get("sources", [])
                                        if sources:
                                            st.markdown("#### 📚 Citations & Sources")
                                            for src in sources:
                                                st.markdown(f'<div class="citation-card">{src}</div>', unsafe_allow_html=True)

                                        st.caption(f"Trace Run ID: `#{res_data.get('run_id')}` — view full execution steps in the **Traces** tab.")

                                    elif status == "paused_for_approval":
                                        st.markdown(f"""
                                        <div class="approval-box">
                                            <h4>⚠️ Execution Paused: Human Approval Required</h4>
                                            <p>This agent attempted to invoke high-risk tool: <b><code>{res_data.get('tool_name')}</code></b> with arguments: <code>{json.dumps(res_data.get('tool_args'))}</code>.</p>
                                            <p>A supervisor must approve or deny this request before execution can proceed.</p>
                                        </div>
                                        """, unsafe_allow_html=True)
                                        st.info("👉 Switch to the **Approvals** tab to review, approve, or deny this action.")

                                    elif status == "failed":
                                        st.error(f"❌ Run Failed: {res_data.get('answer')}")

                                else:
                                    st.error(f"API Error ({run_resp.status_code}): {run_resp.text}")

                            except requests.exceptions.Timeout:
                                st.error("⏱️ Execution timed out after 120s. Ollama or host may be under heavy load.")
                            except Exception as e:
                                st.error(f"Failed to connect to backend: {str(e)}")

# ------------------------------------------------------------------------------
# TAB: DOCUMENTS (RAG)
# ------------------------------------------------------------------------------
with tab_dict["📂 Documents"]:
    st.subheader("📂 Document Management & Ingestion")

    if not st.session_state.token:
        st.warning("⚠️ Please log in from the **Account** tab to manage documents.")
    else:
        st.markdown("Upload documents (PDF, DOCX, TXT) into the local sovereign vector knowledge base.")

        uploaded_file = st.file_uploader(
            "Choose a file to ingest",
            type=["pdf", "docx", "txt"],
            help="Files are stored natively in ./data/uploads and embedded into ChromaDB with zero network calls.",
        )

        if uploaded_file is not None:
            if st.button("📥 Ingest Document", type="primary"):
                with st.spinner("Extracting text, chunking, and embedding with nomic-embed-text..."):
                    try:
                        files = {"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}
                        up_res = requests.post(
                            f"{BACKEND_URL}/documents/upload",
                            headers=get_auth_headers(),
                            files=files,
                            timeout=60.0,
                        )
                        if up_res.status_code == 200:
                            data = up_res.json()
                            st.success(f"✅ Successfully ingested '{data.get('filename')}' ({data.get('chunks')} chunks).")
                            st.rerun()
                        else:
                            st.error(f"Ingestion failed ({up_res.status_code}): {up_res.text}")
                    except Exception as e:
                        st.error(f"Error communicating with backend: {str(e)}")

        st.markdown("---")
        st.subheader("📚 Ingested Knowledge Base Documents")

        try:
            doc_res = requests.get(f"{BACKEND_URL}/documents", headers=get_auth_headers(), timeout=5.0)
            if doc_res.status_code == 200:
                docs = doc_res.json()
                if not docs:
                    st.info("No documents uploaded yet.")
                else:
                    for d in docs:
                        with st.container():
                            col1, col2, col3, col4, col5 = st.columns([3, 1, 1, 2, 1])
                            col1.markdown(f"📄 **{d['filename']}**")
                            col2.caption(f"Format: `{d['file_type'].upper()}`")
                            col3.caption(f"Chunks: `{d['chunk_count']}`")
                            col4.caption(f"Size: {round(d['file_size']/1024, 1)} KB | Uploaded: {d['created_at'][:10]}")
                            with col5:
                                if st.button("🗑️", key=f"del_doc_{d['id']}", help=f"Delete {d['filename']} and vectors"):
                                    del_res = requests.delete(
                                        f"{BACKEND_URL}/documents/{d['id']}",
                                        headers=get_auth_headers(),
                                        timeout=10.0,
                                    )
                                    if del_res.status_code == 200:
                                        st.success(f"Deleted '{d['filename']}'")
                                        st.rerun()
                                    else:
                                        st.error(f"Delete failed: {del_res.text}")
                            st.divider()
            else:
                st.error("Failed to load document list.")
        except Exception as e:
            st.error(f"Error loading documents: {str(e)}")

# ------------------------------------------------------------------------------
# TAB: AGENTS (Admin Only)
# ------------------------------------------------------------------------------
if "🤖 Agents" in tab_dict:
    with tab_dict["🤖 Agents"]:
        st.subheader("🤖 AI Agent Management")

        if not st.session_state.token:
            st.warning("⚠️ Please log in to inspect or manage agents.")
        else:
            user_role = st.session_state.user_info.get("role", "user")

            # Display registered agents
            try:
                agent_res = requests.get(f"{BACKEND_URL}/agents", headers=get_auth_headers(), timeout=5.0)
                agents = agent_res.json() if agent_res.status_code == 200 else []
            except Exception:
                agents = []

            col_left, col_right = st.columns([1, 1])

            with col_left:
                st.markdown("#### Configured Agents")
                for a in agents:
                    with st.expander(f"🤖 {a['name']}", expanded=True):
                        st.markdown(f"**Model:** `{a['model']}` | **Temperature:** `{a['temperature']}`")
                        st.markdown(f"**Allowed Tools:** {', '.join([f'`{t}`' for t in a['allowed_tools']])}")
                        st.caption(f"**System Prompt:**\n{a['system_prompt']}")

            with col_right:
                if user_role == "admin":
                    # Fetch available tool definitions
                    try:
                        tool_res = requests.get(f"{BACKEND_URL}/tools", headers=get_auth_headers(), timeout=3.0)
                        available_tools = [t["name"] for t in tool_res.json()] if tool_res.status_code == 200 else []
                    except Exception:
                        available_tools = []
                    if not available_tools:
                        available_tools = ["search_documents", "calculator", "read_file", "read_sql"]

                    action_choice = st.radio("Agent Management Action", ["➕ Create New", "✏️ Edit Existing"], horizontal=True)

                    if action_choice == "➕ Create New":
                        st.markdown("#### ➕ Create New Agent")
                        new_name = st.text_input("Agent Name", placeholder="e.g. Research Specialist")
                        new_prompt = st.text_area(
                            "System Prompt",
                            placeholder="Describe how the agent behaves and which tools it should prioritize...",
                            height=120,
                        )
                        new_model = st.text_input("Ollama Model", value=ollama_model_name)
                        valid_defaults = [t for t in ["search_documents", "calculator"] if t in available_tools]
                        selected_tools = st.multiselect(
                            "Allowed Tools",
                            options=available_tools,
                            default=valid_defaults,
                        )
                        new_temp = st.slider("Temperature", 0.0, 1.0, 0.2, 0.05)

                        if st.button("Create Agent", type="primary"):
                            if not new_name.strip() or not new_prompt.strip():
                                st.error("Agent name and system prompt are required.")
                            else:
                                payload = {
                                    "name": new_name.strip(),
                                    "system_prompt": new_prompt.strip(),
                                    "model": new_model.strip(),
                                    "allowed_tools": selected_tools,
                                    "temperature": new_temp,
                                }
                                create_res = requests.post(
                                    f"{BACKEND_URL}/agents",
                                    headers=get_auth_headers(),
                                    json=payload,
                                    timeout=5.0,
                                )
                                if create_res.status_code == 200:
                                    st.success(f"Agent '{new_name}' created successfully!")
                                    st.rerun()
                                else:
                                    st.error(f"Failed to create agent: {create_res.text}")

                    else:
                        st.markdown("#### ✏️ Edit Existing Agent")
                        if not agents:
                            st.info("No agents available to edit.")
                        else:
                            agent_names = [a["name"] for a in agents]
                            edit_agent_name = st.selectbox("Select Agent to Edit", agent_names, key="edit_agent_select")
                            target_a = next((a for a in agents if a["name"] == edit_agent_name), None)

                            if target_a:
                                edit_prompt = st.text_area("System Prompt", value=target_a["system_prompt"], height=120, key="edit_p")
                                edit_model = st.text_input("Ollama Model", value=target_a["model"], key="edit_m")
                                edit_temp = st.slider("Temperature", 0.0, 1.0, float(target_a["temperature"]), 0.05, key="edit_t")
                                edit_tools = st.multiselect(
                                    "Allowed Tools",
                                    options=available_tools,
                                    default=[t for t in target_a["allowed_tools"] if t in available_tools],
                                    key="edit_tools_sel",
                                )

                                if st.button("💾 Save Agent Updates", type="primary", key="save_agent_updates_btn"):
                                    up_payload = {
                                        "name": target_a["name"],
                                        "system_prompt": edit_prompt.strip(),
                                        "model": edit_model.strip(),
                                        "temperature": edit_temp,
                                        "allowed_tools": edit_tools,
                                    }
                                    up_res = requests.put(
                                        f"{BACKEND_URL}/agents/{target_a['id']}",
                                        headers=get_auth_headers(),
                                        json=up_payload,
                                        timeout=5.0,
                                    )
                                    if up_res.status_code == 200:
                                        st.success(f"Agent '{target_a['name']}' updated successfully!")
                                        st.rerun()
                                    else:
                                        st.error(f"Failed to update agent: {up_res.text}")
                else:
                    st.info("ℹ️ Only administrators can create or edit agents.")

# ------------------------------------------------------------------------------
# TAB: TRACES
# ------------------------------------------------------------------------------
with tab_dict["🔍 Traces"]:
    st.subheader("🔍 Execution Traces & Latencies")

    if not st.session_state.token:
        st.warning("⚠️ Please log in to view execution traces.")
    else:
        try:
            runs_res = requests.get(f"{BACKEND_URL}/runs", headers=get_auth_headers(), timeout=5.0)
            runs = runs_res.json() if runs_res.status_code == 200 else []
        except Exception as e:
            st.error(f"Failed to fetch runs: {str(e)}")
            runs = []

        if not runs:
            st.info("No execution runs recorded yet.")
        else:
            for r in runs:
                status_color = {
                    "completed": "🟢",
                    "running": "🟡",
                    "paused_for_approval": "🟠",
                    "failed": "🔴",
                }.get(r["status"], "⚪")

                with st.expander(
                    f"{status_color} Run #{r['id']} | Agent: {r['agent_name']} | Status: {r['status'].upper()} | Latency: {r['total_latency_ms']} ms",
                    expanded=False,
                ):
                    st.markdown(f"**User:** `{r['username']}` | **Date:** `{r['created_at'][:19]}`")
                    st.markdown(f"**Question:** {r['question']}")
                    if r.get("final_answer"):
                        st.markdown(f"**Final Answer:**\n{r['final_answer']}")

                    # Fetch detailed steps for this run
                    try:
                        detail_res = requests.get(f"{BACKEND_URL}/runs/{r['id']}", headers=get_auth_headers(), timeout=5.0)
                        if detail_res.status_code == 200:
                            details = detail_res.json()
                            steps = details.get("steps", [])

                            if steps:
                                st.markdown("##### ⏱️ Step-by-Step Execution Breakdown")
                                for s in steps:
                                    st_type = s["step_type"].lower()
                                    pill_class = f"trace-{st_type}" if st_type in ("llm", "tool", "policy", "retry") else "trace-llm"
                                    
                                    col1, col2 = st.columns([1, 6])
                                    with col1:
                                        st.markdown(
                                            f'<span class="trace-step-type {pill_class}">{s["step_type"]}</span><br><small>{s["latency_ms"]} ms</small>',
                                            unsafe_allow_html=True,
                                        )
                                    with col2:
                                        st.caption(f"**Step #{s['step_number']} Input:**")
                                        st.code(s["input_data"], language="json" if "{" in s["input_data"] else "text")
                                        st.caption("**Output / Observation:**")
                                        st.code(s["output_data"][:1000], language="json" if "{" in s["output_data"] else "text")
                                    st.divider()
                    except Exception as e:
                        st.caption(f"Could not load step details: {str(e)}")

# ------------------------------------------------------------------------------
# TAB: APPROVALS (Human-in-the-Loop)
# ------------------------------------------------------------------------------
with tab_dict["🛡️ Approvals"]:
    st.subheader("🛡️ Human-in-the-Loop Approvals")
    st.markdown("High-risk tools (such as direct SQL execution) pause agent runs and require explicit human confirmation.")

    if not st.session_state.token:
        st.warning("⚠️ Please log in to manage approvals.")
    else:
        try:
            apprv_res = requests.get(f"{BACKEND_URL}/approvals/pending", headers=get_auth_headers(), timeout=5.0)
            pending = apprv_res.json() if apprv_res.status_code == 200 else []
        except Exception as e:
            st.error(f"Error fetching pending approvals: {str(e)}")
            pending = []

        if not pending:
            st.success("✅ No pending approvals! All agent operations are running smoothly.")
        else:
            for item in pending:
                with st.container():
                    st.markdown(f"""
                    <div class="approval-box">
                        <h4>Request #{item['id']} &mdash; Tool: <code>{item['tool_name']}</code></h4>
                        <p><b>Requested By:</b> <code>{item['username']}</code> &bull; <b>Run ID:</b> #{item['run_id']}</p>
                        <p><b>User Question:</b> {item['question']}</p>
                        <p><b>Proposed Action Arguments:</b></p>
                        <pre style="background: rgba(0,0,0,0.3); padding: 8px; border-radius: 6px;">{item['tool_args']}</pre>
                    </div>
                    """, unsafe_allow_html=True)

                    btn_col1, btn_col2, _ = st.columns([1, 1, 4])
                    with btn_col1:
                        if st.button(f"✅ Approve #{item['id']}", key=f"app_{item['id']}", type="primary"):
                            with st.spinner("Approving and resuming agent loop..."):
                                dec_res = requests.post(
                                    f"{BACKEND_URL}/approvals/{item['id']}/decide",
                                    headers=get_auth_headers(),
                                    json={"decision": "approve"},
                                    timeout=130.0,
                                )
                                if dec_res.status_code == 200:
                                    st.success(f"Approval #{item['id']} granted. Run resumed!")
                                    st.rerun()
                                else:
                                    st.error(f"Failed to record decision: {dec_res.text}")

                    with btn_col2:
                        if st.button(f"❌ Deny #{item['id']}", key=f"deny_{item['id']}"):
                            with st.spinner("Denying request and resuming agent..."):
                                dec_res = requests.post(
                                    f"{BACKEND_URL}/approvals/{item['id']}/decide",
                                    headers=get_auth_headers(),
                                    json={"decision": "deny"},
                                    timeout=130.0,
                                )
                                if dec_res.status_code == 200:
                                    st.warning(f"Approval #{item['id']} denied.")
                                    st.rerun()
                                else:
                                    st.error(f"Failed to record decision: {dec_res.text}")

# ------------------------------------------------------------------------------
# TAB: AUDIT LOG (Admin Only)
# ------------------------------------------------------------------------------
if "📋 Audit Log" in tab_dict:
    with tab_dict["📋 Audit Log"]:
        st.subheader("📋 Security & Governance Audit Log")

        if not st.session_state.token:
            st.warning("⚠️ Please log in to view audit logs.")
        elif st.session_state.user_info.get("role") != "admin":
            st.error("🚫 Access Restricted: Only users with the 'admin' role may inspect the security audit trail.")
        else:
            st.caption("Immutable record of all actions, policy decisions, and approval outcomes. Sensitive PII (emails, phone numbers, Aadhaar) is automatically masked.")

            try:
                audit_res = requests.get(f"{BACKEND_URL}/audit", headers=get_auth_headers(), timeout=5.0)
                if audit_res.status_code == 200:
                    logs = audit_res.json()
                    if not logs:
                        st.info("Audit log is currently empty.")
                    else:
                        st.dataframe(
                            logs,
                            column_config={
                                "timestamp": st.column_config.TextColumn("Timestamp", width="medium"),
                                "user": st.column_config.TextColumn("User", width="small"),
                                "action": st.column_config.TextColumn("Action", width="medium"),
                                "outcome": st.column_config.TextColumn("Outcome", width="small"),
                                "details": st.column_config.TextColumn("Details (PII Masked)", width="large"),
                            },
                            use_container_width=True,
                            hide_index=True,
                        )
                else:
                    st.error(f"Failed to load audit logs: {audit_res.text}")
            except Exception as e:
                st.error(f"Error loading audit log: {str(e)}")

# ------------------------------------------------------------------------------
# TAB: EVALUATION (Admin Only)
# ------------------------------------------------------------------------------
if "📊 Evaluation" in tab_dict:
    with tab_dict["📊 Evaluation"]:
        st.subheader("📊 Evaluation Benchmark Results")
        st.markdown(
            "Headless, reproducible benchmarks measuring agent reliability, tool calling validity, "
            "RAG chunking retrieval hit rates, and resource consumption."
        )

        from pathlib import Path
        results_dir = Path(__file__).resolve().parent.parent / "eval" / "results"
        summary_csv = results_dir / "summary.csv"
        summary_md = results_dir / "summary.md"

        has_results = results_dir.exists() and (summary_csv.exists() or any(results_dir.glob("*.jsonl")))

        if not has_results:
            st.info("ℹ️ No evaluation benchmark results found in `eval/results/`. Run `python eval/run_eval.py` to generate benchmarks.")
        else:
            col_refresh, _ = st.columns([1, 4])
            with col_refresh:
                if st.button("🔄 Refresh Evaluation Data", key="refresh_eval_btn", use_container_width=True):
                    st.rerun()

            # Render Summary CSV if available
            if summary_csv.exists():
                st.markdown("#### 📋 Benchmark Summary Table")
                try:
                    import csv
                    with open(summary_csv, "r", encoding="utf-8") as f:
                        reader = csv.DictReader(f)
                        rows = list(reader)
                    if rows:
                        st.dataframe(rows, use_container_width=True, hide_index=True)
                except Exception as e:
                    st.error(f"Error reading summary.csv: {e}")

            # Render Charts
            st.markdown("#### 📈 Benchmark Visualizations")
            chart_col1, chart_col2 = st.columns(2)

            chart_e1 = results_dir / "e1_retrieval_hit_vs_chunk_size.png"
            chart_e1b = results_dir / "e1b_chunk_level_retrieval.png"
            chart_e2 = results_dir / "e2_reliability_factorial.png"
            chart_fail = results_dir / "failure_analysis.png"
            chart_perf = results_dir / "latency_and_memory.png"

            with chart_col1:
                if chart_e1.exists():
                    st.image(str(chart_e1), caption="E1: Document-Level Hit@3 vs Chunk Size", use_container_width=True)
                if chart_e1b.exists():
                    st.image(str(chart_e1b), caption="E1b: Chunk-Level Hit@1, Hit@3 & MRR (18-Doc Distractor Corpus)", use_container_width=True)
                if chart_perf.exists():
                    st.image(str(chart_perf), caption="Latency & Peak Ollama RSS Memory", use_container_width=True)

            with chart_col2:
                if chart_e2.exists():
                    st.image(str(chart_e2), caption="E2: Reliability Factorial (Validity & Success)", use_container_width=True)
                if chart_fail.exists():
                    st.image(str(chart_fail), caption="Failure Mode Classification Breakdown", use_container_width=True)

            # Render Markdown summary text if available
            if summary_md.exists():
                with st.expander("📄 Full Benchmark Findings & Report (Markdown)", expanded=False):
                    st.markdown(summary_md.read_text(encoding="utf-8"))

# ------------------------------------------------------------------------------
# TAB: ACCOUNT / LOGIN
# ------------------------------------------------------------------------------
with tab_dict["👤 Account"]:

    st.subheader("👤 User Authentication & Registration")

    if st.session_state.token and st.session_state.user_info:
        st.success(f"You are currently logged in as **{st.session_state.user_info.get('username')}** (Role: `{st.session_state.user_info.get('role')}`).")
        if st.button("Log Out"):
            st.session_state.token = None
            st.session_state.user_info = None
            st.rerun()
    else:
        auth_mode = st.radio("Choose Action", ["Login", "Register"], horizontal=True)

        auth_col1, auth_col2 = st.columns([1, 1])

        with auth_col1:
            username_input = st.text_input("Username")
            password_input = st.text_input("Password", type="password")

            if auth_mode == "Login":
                if st.button("🔐 Sign In", type="primary", use_container_width=True):
                    if not username_input or not password_input:
                        st.error("Please enter both username and password.")
                    else:
                        try:
                            login_resp = requests.post(
                                f"{BACKEND_URL}/auth/login",
                                json={"username": username_input.strip(), "password": password_input.strip()},
                                timeout=5.0,
                            )
                            if login_resp.status_code == 200:
                                data = login_resp.json()
                                st.session_state.token = data["access_token"]
                                st.session_state.user_info = {
                                    "username": data["username"],
                                    "role": data["role"],
                                    "user_id": data["user_id"],
                                }
                                st.success(f"Welcome back, {data['username']}! Logged in as {data['role'].upper()}.")
                                st.rerun()
                            else:
                                st.error("Invalid username or password.")
                        except Exception as e:
                            st.error(f"Could not connect to backend: {str(e)}")

            else:  # Register
                st.caption("ℹ️ The first user registered in the system automatically receives the **admin** role.")
                if st.button("📝 Register Account", type="primary", use_container_width=True):
                    if not username_input or not password_input:
                        st.error("Please enter both username and password.")
                    else:
                        try:
                            reg_resp = requests.post(
                                f"{BACKEND_URL}/auth/register",
                                json={"username": username_input.strip(), "password": password_input.strip()},
                                timeout=5.0,
                            )
                            if reg_resp.status_code == 200:
                                data = reg_resp.json()
                                st.session_state.token = data["access_token"]
                                st.session_state.user_info = {
                                    "username": data["username"],
                                    "role": data["role"],
                                    "user_id": data["user_id"],
                                }
                                st.success(f"Account created successfully! Assigned role: {data['role'].upper()}.")
                                st.rerun()
                            else:
                                st.error(f"Registration failed: {reg_resp.text}")
                        except Exception as e:
                            st.error(f"Could not connect to backend: {str(e)}")
