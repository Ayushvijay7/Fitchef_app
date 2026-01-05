import streamlit as st
from google import genai
from google.genai import types
from PIL import Image
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import ast

# --- PAGE CONFIG ---
st.set_page_config(page_title="FitChef Pro Mobile", page_icon="🥑", layout="wide")

# --- GOOGLE SHEETS CONNECTION ---
# We cache this function so we don't reconnect on every button click
@st.cache_resource
def get_gsheet_connection():
    # Load credentials from Streamlit Secrets
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    # Connect to the Sheet
    sheet = client.open("FitChef DB") # MAKE SURE THIS MATCHES YOUR SHEET NAME
    return sheet

# --- DATA MANAGER ---
def load_data():
    try:
        sh = get_gsheet_connection()
        
        # 1. Load Hydration
        try:
            ws_hydro = sh.worksheet("Hydration")
            data = ws_hydro.get_all_records()
            if data:
                hydration_data = data[0] # Expecting 1 row of data
            else:
                # Default Init
                hydration_data = {"last_log_date": "", "total_ml": 0, "daily_goal_ml": 3000, "day_start_hour": 6}
        except:
            hydration_data = {"last_log_date": "", "total_ml": 0, "daily_goal_ml": 3000, "day_start_hour": 6}

        # 2. Load Shopping
        try:
            ws_shop = sh.worksheet("Shopping")
            shopping_list = ws_shop.get_all_records()
            # Convert 'bought' from string "TRUE" to boolean if needed
            for item in shopping_list:
                if isinstance(item.get('bought'), str):
                    item['bought'] = True if item['bought'].upper() == 'TRUE' else False
        except:
            shopping_list = []

        return {"hydration": hydration_data, "shopping_list": shopping_list}
    except Exception as e:
        st.error(f"DB Connection Error: {e}")
        return {"hydration": {}, "shopping_list": []}

def save_hydration(h_data):
    sh = get_gsheet_connection()
    ws = sh.worksheet("Hydration")
    # Clear and rewrite row 1 (headers) and row 2 (data)
    ws.clear()
    ws.append_row(["last_log_date", "total_ml", "daily_goal_ml", "day_start_hour"])
    ws.append_row([h_data["last_log_date"], h_data["total_ml"], h_data["daily_goal_ml"], h_data["day_start_hour"]])

def save_shopping(s_list):
    sh = get_gsheet_connection()
    ws = sh.worksheet("Shopping")
    ws.clear()
    # Headers
    ws.append_row(["item", "qty", "user_price", "ai_price", "bought"])
    # Data
    rows = []
    for x in s_list:
        rows.append([x["item"], x["qty"], x["user_price"], x.get("ai_price", 0), x["bought"]])
    if rows:
        ws.append_rows(rows)

# --- INIT DATA ---
app_data = load_data()
if not app_data["hydration"]: # Fallback if empty
    app_data["hydration"] = {"last_log_date": "", "total_ml": 0, "daily_goal_ml": 3000, "day_start_hour": 6}

# --- DATE LOGIC ---
def get_logical_date(start_hour):
    now = datetime.now()
    if now.hour < int(start_hour):
        return (now - timedelta(days=1)).strftime("%Y-%m-%d")
    return now.strftime("%Y-%m-%d")

# --- UI & LOGIC ---
# (Standard UI CSS)
st.markdown("""<style>.stButton>button {border-radius: 8px; font-weight: 600;}</style>""", unsafe_allow_html=True)

# Session State for Keys
if 'api_client' not in st.session_state: st.session_state.api_client = None
if 'is_verified' not in st.session_state: st.session_state.is_verified = False

# SIDEBAR
with st.sidebar:
    st.title("FitChef Mobile ☁️")
    api_key = st.text_input("Gemini API Key", type="password")
    if api_key:
        try:
            client = genai.Client(api_key=api_key)
            client.models.get(model="gemini-2.5-pro")
            st.session_state.api_client = client
            st.session_state.is_verified = True
            st.success("AI Online")
        except:
            st.error("AI Offline")
    
    menu = st.radio("Menu", ["💧 Hydration", "🛒 Shopping", "👨‍🍳 Smart Chef", "😈 Cheat Negotiator"])

# HELPER
def ask_gemini(prompt, image=None):
    if not st.session_state.api_client: return "Connect API Key first."
    try:
        c = [prompt]
        if image: c.append(image)
        r = st.session_state.api_client.models.generate_content(model="gemini-2.5-pro", contents=c)
        return r.text
    except Exception as e: return str(e)

# --- TAB 1: HYDRATION ---
if menu == "💧 Hydration":
    st.header("💧 Hydration Tracker")
    
    # Check Day Reset
    current_date = get_logical_date(app_data["hydration"]["day_start_hour"])
    if app_data["hydration"]["last_log_date"] != current_date:
        app_data["hydration"]["last_log_date"] = current_date
        app_data["hydration"]["total_ml"] = 0
        save_hydration(app_data["hydration"])
        st.toast("Day reset!")

    # Display
    curr = app_data["hydration"]["total_ml"]
    goal = app_data["hydration"]["daily_goal_ml"]
    st.metric("Today", f"{curr} mL", f"{goal-curr} remaining")
    st.progress(min(curr/goal, 1.0))
    
    # Add Water
    c1, c2 = st.columns(2)
    if c1.button("Drink 250ml"):
        app_data["hydration"]["total_ml"] += 250
        save_hydration(app_data["hydration"])
        st.rerun()
    if c2.button("Drink 500ml"):
        app_data["hydration"]["total_ml"] += 500
        save_hydration(app_data["hydration"])
        st.rerun()

    with st.expander("Settings"):
        new_start = st.number_input("Day Start Hour", 0, 23, app_data["hydration"]["day_start_hour"])
        if st.button("Save Settings"):
            app_data["hydration"]["day_start_hour"] = new_start
            save_hydration(app_data["hydration"])
            st.rerun()

# --- TAB 2: SHOPPING ---
elif menu == "🛒 Shopping":
    st.header("🛒 Cloud Grocery List")
    
    # Add Item
    c1, c2, c3 = st.columns([2, 1, 1])
    item = c1.text_input("Item")
    qty = c2.text_input("Qty", "1")
    if c3.button("Add"):
        app_data["shopping_list"].append({"item": item, "qty": qty, "user_price": 0, "bought": False})
        save_shopping(app_data["shopping_list"])
        st.rerun()

    # View List
    if app_data["shopping_list"]:
        for i, row in enumerate(app_data["shopping_list"]):
            col_check, col_txt = st.columns([0.5, 4])
            checked = col_check.checkbox("", row["bought"], key=f"s_{i}")
            
            # Update DB if changed
            if checked != row["bought"]:
                row["bought"] = checked
                save_shopping(app_data["shopping_list"])
                st.rerun()
            
            st_style = "text-decoration: line-through; color:grey" if row["bought"] else ""
            col_txt.markdown(f"<span style='{st_style}'>{row['item']} ({row['qty']})</span>", unsafe_allow_html=True)
            
        if st.button("Clear Bought Items"):
            app_data["shopping_list"] = [x for x in app_data["shopping_list"] if not x["bought"]]
            save_shopping(app_data["shopping_list"])
            st.rerun()

# --- TAB 3: SMART CHEF ---
elif menu == "👨‍🍳 Smart Chef":
    st.header("👨‍🍳 Smart Chef")
    enable_cam = st.toggle("Enable Camera")
    img_file = st.camera_input("Scan") if enable_cam else None
    txt_ing = st.text_area("Ingredients")
    
    if st.button("Generate"):
        with st.spinner("Cooking..."):
            p = f"Create a recipe for: {txt_ing}. Location: Hyderabad. Return recipe & list ingredients in {{brackets}} at end."
            res = ask_gemini(p, Image.open(img_file) if img_file else None)
            st.markdown(res)
            
            # Shopping List Parser
            if "{" in res:
                try:
                    raw = res.split("{")[1].split("}")[0]
                    items = raw.split(",")
                    if st.button("Add to List"):
                        for itm in items:
                            app_data["shopping_list"].append({"item": itm.strip(), "qty": "1", "user_price": 0, "bought": False})
                        save_shopping(app_data["shopping_list"])
                        st.success("Added!")
                except: pass

# --- TAB 4: CHEAT NEGOTIATOR ---
elif menu == "😈 Cheat Negotiator":
    st.header("😈 Cheat Negotiator")
    craving = st.text_input("I want to eat...")
    if st.button("Negotiate"):
        with st.spinner("Analyzing..."):
            res = ask_gemini(f"User wants {craving}. Goal: Fitness. Estimate calories, calculate exercise to burn off, and suggest healthy swap.")
            st.info(res)
