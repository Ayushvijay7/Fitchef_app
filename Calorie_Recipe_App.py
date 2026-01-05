import streamlit as st
from google import genai
from google.genai import types
from PIL import Image
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import pandas as pd
import random
import time
import re

# --- PAGE CONFIG ---
st.set_page_config(
    page_title="FitChef Pro",
    page_icon="🔥",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- MOBILE POLISH & CSS ---
# Hides Streamlit branding and optimizes padding for mobile
hide_st_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header {visibility: hidden;}
            .block-container { padding-top: 1rem; padding-bottom: 5rem; }
            </style>
            """
st.markdown(hide_st_style, unsafe_allow_html=True)

st.markdown("""
    <style>
    .css-card {
        background-color: #ffffff;
        padding: 1.5rem;
        border-radius: 12px;
        border: 1px solid #e0e0e0;
        box-shadow: 0 2px 5px rgba(0,0,0,0.05);
        margin-bottom: 1rem;
    }
    .urgency-high { color: #e74c3c; font-weight: bold; }
    /* Ensure columns don't shrink too much on mobile */
    div[data-testid="column"] { min-width: 0; }
    </style>
""", unsafe_allow_html=True)

# --- MOCKING FOR TESTING (SANDBOX MODE) ---
class MockWorksheet:
    def __init__(self, name):
        self.name = name
    def get_all_records(self):
        return []
    def clear(self): pass
    def append_row(self, row): pass
    def append_rows(self, rows): pass

class MockSheet:
    def worksheet(self, name):
        return MockWorksheet(name)

class MockModel:
    def generate_content(self, contents, config=None, **kwargs):
        class Res:
            text = """AI Response (Mock Mode):
## Recipe Name
**Protein:** 30g | **Cals:** 400
## Ingredients
* Mock Chicken
* Mock Veggies
## Instructions
1. Cook them.
"""
        return Res()

class MockClient:
    @property
    def models(self):
        return MockModel()

# --- HELPERS: SAFE MATH ---
def safe_parse_qty(qty_str):
    """Extracts a number from a string like '1.5 kg' -> 1.5. Defaults to 1."""
    try:
        match = re.search(r"(\d+(\.\d+)?)", str(qty_str))
        if match:
            return float(match.group(1))
        return 1.0
    except:
        return 1.0

def safe_float(val):
    try:
        return float(val)
    except:
        return 0.0

def clean_json_response(text):
    """Cleans Markdown code blocks and extracts JSON array."""
    try:
        # 1. Remove Markdown code blocks
        if "```" in text:
            text = re.sub(r"```json|```", "", text).strip()
        
        # 2. Extract outermost brackets [ ... ]
        # This handles cases where there is text before or after the JSON.
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            text = match.group(0)
            
        return text
    except:
        return text

def get_effective_date(log_dt, start_hour):
    """
    Returns the effective 'date' of a log based on the user's start hour.
    If log time is before start_hour, it counts as the previous day.
    """
    if log_dt.hour < start_hour:
        return (log_dt - timedelta(days=1)).strftime("%Y-%m-%d")
    return log_dt.strftime("%Y-%m-%d")

def calculate_streak(logs, goal, start_hour=0):
    """Calculates consecutive days where hydration goal was met."""
    if not logs: return 0
    
    # Group by Effective Date
    daily_totals = {}
    for l in logs:
        # Parse log datetime
        try:
            log_dt = datetime.strptime(f"{l['date']} {l['time']}", "%Y-%m-%d %H:%M")
            eff_date = get_effective_date(log_dt, start_hour)
            daily_totals[eff_date] = daily_totals.get(eff_date, 0) + safe_float(l['amount'])
        except:
            continue
    
    streak = 0
    # Current Effective Date
    now = datetime.now()
    eff_today = get_effective_date(now, start_hour)
    
    # Check backwards from yesterday (allow today to be in progress)
    # If we use effective dates, we just iterate backwards from eff_today - 1
    
    # Parse eff_today back to date object to iterate
    check_date = datetime.strptime(eff_today, "%Y-%m-%d").date() - timedelta(days=1)
    
    # If today is already met, include it
    if daily_totals.get(eff_today, 0) >= goal:
        streak += 1
        
    while True:
        d_str = check_date.strftime("%Y-%m-%d")
        if daily_totals.get(d_str, 0) >= goal:
            streak += 1
            check_date -= timedelta(days=1)
        else:
            break
    return streak

# --- DB MANAGER (MULTI-USER) ---
@st.cache_resource
def get_db_connection():
    try:
        # CHECK IF MOCK MODE IS NEEDED
        try:
            if "gcp_service_account" not in st.secrets:
                return MockSheet()
        except:
            return MockSheet()

        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        try:
             sheet = client.open("FitChef DB") 
        except:
             return None
        return sheet
    except Exception as e:
        # Fallback to mock if connection fails
        return MockSheet()

def fetch_user_data(username):
    """Fetches data only for the logged-in user."""
    default_data = {
        "hydration": {
            "logs": [], "daily_goal": 3000, "weight": 70, 
            "activity": "Moderate", "start_hour": 0
        },
        "shopping": [],
        "cheats": {"used_this_week": 0, "weekly_limit": 3}
    }
    
    sh = get_db_connection()
    if not sh: return default_data 
    
    try:
        # HYDRATION
        try:
            ws = sh.worksheet("Hydration")
            all_recs = ws.get_all_records()
            user_row = next((r for r in all_recs if str(r.get('username')) == username), None)
            if user_row and user_row.get('config_json'):
                hydration_data = json.loads(user_row['config_json'])
            else:
                hydration_data = default_data["hydration"]
        except:
             hydration_data = default_data["hydration"]

        # SHOPPING
        try:
            ws_s = sh.worksheet("Shopping")
            all_shop = ws_s.get_all_records()
            # Filter specifically for this user
            user_shop = [x for x in all_shop if str(x.get('username')) == username]
            for x in user_shop:
                x['bought'] = str(x['bought']).lower() == 'true'
            shopping_list = user_shop
        except:
            shopping_list = []

        # CHEATS
        try:
            ws_c = sh.worksheet("Cheats")
            all_c = ws_c.get_all_records()
            user_c = next((r for r in all_c if str(r.get('username')) == username), None)
            if user_c and user_c.get('config_json'):
                cheat_data = json.loads(user_c['config_json'])
            else:
                cheat_data = default_data["cheats"]
        except:
             cheat_data = default_data["cheats"]

        return {"hydration": hydration_data, "shopping": shopping_list, "cheats": cheat_data}

    except Exception as e:
        return default_data

def save_data_to_cloud(key, new_data, username):
    """Saves data while preserving other users' rows."""
    sh = get_db_connection()
    if not sh: return

    try:
        if key == "hydration":
            ws = sh.worksheet("Hydration")
            all_rows = ws.get_all_records()
            others = [r for r in all_rows if str(r.get('username')) != username]
            
            my_row = {"username": username, "config_json": json.dumps(new_data)}
            
            # Rebuild Table: Others + Mine
            final_data = [[r['username'], r['config_json']] for r in others]
            final_data.append([my_row['username'], my_row['config_json']])
            
            ws.clear()
            ws.append_row(["username", "config_json"])
            ws.append_rows(final_data)
            
        elif key == "cheats":
            ws = sh.worksheet("Cheats")
            all_rows = ws.get_all_records()
            others = [r for r in all_rows if str(r.get('username')) != username]
            
            my_row = {"username": username, "config_json": json.dumps(new_data)}
            
            final_data = [[r['username'], r['config_json']] for r in others]
            final_data.append([my_row['username'], my_row['config_json']])
            
            ws.clear()
            ws.append_row(["username", "config_json"])
            ws.append_rows(final_data)
            
        elif key == "shopping":
            ws = sh.worksheet("Shopping")
            all_rows = ws.get_all_records()
            others = [r for r in all_rows if str(r.get('username')) != username]
            
            # Convert my new data into rows
            my_rows = []
            for x in new_data:
                my_rows.append({
                    "username": username,
                    "item": x["item"], "qty": x["qty"], 
                    "category": x.get("category", "General"),
                    "price_min": safe_float(x.get("price_min", 0)), 
                    "price_max": safe_float(x.get("price_max", 0)), 
                    "bought": x["bought"]
                })
            
            # Combine
            export_rows = []
            for r in others:
                export_rows.append([r['username'], r['item'], r['qty'], r['category'], r['price_min'], r['price_max'], r['bought']])
            for r in my_rows:
                export_rows.append([r['username'], r['item'], r['qty'], r['category'], r['price_min'], r['price_max'], r['bought']])
                
            ws.clear()
            ws.append_row(["username", "item", "qty", "category", "price_min", "price_max", "bought"])
            if export_rows: ws.append_rows(export_rows)
            
    except Exception as e:
        st.warning(f"Cloud Save Error: {e}")

# --- AI WRAPPER ---
def ask_ai(prompt, image=None, json_mode=False, use_search=False):
    # Mock Mode handling for AI
    # Use type name check to avoid class redefinition issues in Streamlit
    if 'api_client' in st.session_state and type(st.session_state.api_client).__name__ == 'MockClient':
        if json_mode:
            return json.dumps([{"item": "Mock Chicken", "category": "Protein", "price_min": 220, "price_max": 280}])
        return "AI Response (Mock Mode): Here is your recipe or advice."

    if 'api_client' not in st.session_state or not st.session_state.api_client:
        # Auto-connect mock if no key provided in sandbox
        try:
            if "gcp_service_account" not in st.secrets:
                 st.session_state.api_client = MockClient()
                 return ask_ai(prompt, image, json_mode, use_search)
        except:
             st.session_state.api_client = MockClient()
             return ask_ai(prompt, image, json_mode, use_search)
             
        return None if json_mode else "⚠️ AI Offline. Connect API Key."
    try:
        c = [prompt]
        if image: c.append(image)
        
        tools = []
        if use_search:
            tools.append(types.Tool(google_search=types.GoogleSearch()))

        config = types.GenerateContentConfig(
            temperature=0.7,
            response_mime_type="application/json" if json_mode else "text/plain",
            tools=tools
        )
        
        res = st.session_state.api_client.models.generate_content(
            model="gemini-2.0-flash",
            contents=c,
            config=config
        )
        return res.text
    except Exception as e:
        return f"AI Error: {e}"

# =========================================================
# 1. LOGIN SCREEN
# =========================================================
if 'current_user' not in st.session_state:
    st.session_state.current_user = None

if not st.session_state.current_user:
    st.title("🔥 FitChef Pro")
    st.markdown("### Identify Yourself")
    
    with st.container(border=True):
        username_input = st.text_input("Username", placeholder="e.g. Rahul")
        if st.button("Start Cooking", type="primary"):
            if username_input:
                st.session_state.current_user = username_input.strip()
                st.rerun()
            else:
                st.error("Enter a name.")
    st.stop()

# =========================================================
# 2. MAIN APP SETUP (Logged In)
# =========================================================
current_user = st.session_state.current_user

# Load Data
if 'app_data' not in st.session_state:
    st.session_state.app_data = fetch_user_data(current_user)

# --- AUTHENTICATION (MOVED TO MAIN SCREEN) ---
# This is now visible on mobile without opening the sidebar
if not st.session_state.get('is_verified'):
    # Auto-login for Mock Mode (Sandbox)
    try:
        if "gcp_service_account" not in st.secrets:
            st.session_state.api_client = MockClient()
            st.session_state.is_verified = True
            st.rerun()
    except:
        st.session_state.api_client = MockClient()
        st.session_state.is_verified = True
        st.rerun()

    st.warning("⚠️ AI Disconnected")
    with st.expander("🔑 Connect Gemini API Key (Required)", expanded=True):
        st.write(f"Logged in as: **{current_user}**")
        k = st.text_input("Paste API Key", type="password", key="api_input")
        if k:
            try:
                cl = genai.Client(api_key=k)
                cl.models.get(model="gemini-2.5-pro")
                st.session_state.api_client = cl
                st.session_state.is_verified = True
                st.success("Connected! Loading...")
                time.sleep(1)
                st.rerun()
            except Exception as e:
                st.error(f"Connection failed: {e}")

# --- NAVIGATION (HORIZONTAL TOP BAR) ---
# Replaces Sidebar Navigation
nav_options = ["🏠 Home", "💧 Fuel", "🛒 Plan", "👨‍🍳 Chef", "😈 Cheat"]
if 'nav_selection' not in st.session_state: st.session_state.nav_selection = "🏠 Home"

cols = st.columns(5)
for i, option in enumerate(nav_options):
    if cols[i].button(option): 
        st.session_state.nav_selection = option

selected_nav = st.session_state.nav_selection
nav_map = {
    "🏠 Home": "Dashboard", 
    "💧 Fuel": "Fuel (Hydration)", 
    "🛒 Plan": "Plan (Shopping)", 
    "👨‍🍳 Chef": "Smart Chef", 
    "😈 Cheat": "Cheat Negotiator"
}
nav = nav_map[selected_nav]

# =========================================================
# TAB 1: DASHBOARD
# =========================================================
if nav == "Dashboard":
    st.header(f"Hello, {current_user}.")
    
    # Gamification: Badges
    hydro = st.session_state.app_data['hydration']
    goal = safe_float(hydro.get('daily_goal', 3000))
    start_hour = int(hydro.get('start_hour', 0))
    streak = calculate_streak(hydro.get('logs', []), goal, start_hour)
    
    badges = []
    if streak >= 3: badges.append("💧 Hydration Hero")
    if streak >= 7: badges.append("🔥 On Fire")
    
    cheats = st.session_state.app_data['cheats']
    if cheats['used_this_week'] == 0: badges.append("🥦 Clean Machine")
    
    if badges:
        st.success(f"**Achievements:** {' | '.join(badges)}")
        if "🔥 On Fire" in badges:
            st.toast("🔥 7-Day Streak! You are unstoppable!")

    col1, col2, col3 = st.columns(3)
    
    # Logic: Calculate Today's Total based on Effective Date
    now = datetime.now()
    eff_today = get_effective_date(now, start_hour)
    
    total_today = 0
    for l in hydro.get('logs', []):
        try:
            l_dt = datetime.strptime(f"{l['date']} {l['time']}", "%Y-%m-%d %H:%M")
            if get_effective_date(l_dt, start_hour) == eff_today:
                total_today += safe_float(l['amount'])
        except: pass
        
    pct = int((total_today / goal) * 100) if goal > 0 else 0
    
    with col1:
        st.metric("Hydration", f"{pct}%", f"{int(goal - total_today)}ml left")

    left = cheats['weekly_limit'] - cheats['used_this_week']
    with col2:
        st.metric("Cheat Budget", f"{left} Left", f"{cheats['used_this_week']} used")
        
    shop = st.session_state.app_data['shopping']
    pending = len([x for x in shop if not x['bought']])
    with col3:
        st.metric("Shopping", f"{pending} Items", "Pending")
    
    st.divider()
    if pct < 50 and datetime.now().hour > 15:
        st.warning("📉 **Insight:** You are behind on hydration. Drink 500ml now.")
    elif left == 0:
        st.error("⛔ **Insight:** No cheats left. Stay strict.")
    else:
        st.info("🚀 **Insight:** Solid pace today.")
        
    # LOGOUT BUTTON (Moved here from Sidebar)
    if st.button("Log Out"):
        st.session_state.current_user = None
        st.session_state.app_data = None
        st.rerun()

# =========================================================
# TAB 2: FUEL (HYDRATION)
# =========================================================
elif nav == "Fuel (Hydration)":
    st.header("💧 Fuel Status")
    h_data = st.session_state.app_data['hydration']
    
    with st.expander("⚙️ Calibrate Target"):
        w = st.number_input("Weight (kg)", value=float(h_data.get('weight', 70)))
        a = st.selectbox("Activity", ["Sedentary", "Moderate", "High"], index=1)
        rec_goal = (w * 35) + (500 if a != "Sedentary" else 0)
        st.caption(f"Recommended: {int(rec_goal)}ml")
        
        c1, c2 = st.columns(2)
        new_goal = c1.number_input("Goal (ml)", value=float(h_data.get('daily_goal', 3000)))
        start_h = c2.number_input("Day Start Hour (0-23)", min_value=0, max_value=23, value=int(h_data.get('start_hour', 0)))
        
        if st.button("Save Calibration"):
            h_data['weight'] = w
            h_data['activity'] = a
            h_data['daily_goal'] = new_goal
            h_data['start_hour'] = start_h
            save_data_to_cloud("hydration", h_data, current_user)
            st.rerun()

    # Determine "Today" based on Start Hour
    start_hour = int(h_data.get('start_hour', 0))
    now = datetime.now()
    eff_today = get_effective_date(now, start_hour)
    
    # Filter logs for THIS cycle
    current_cycle_logs = []
    for l in h_data.get('logs', []):
        try:
            l_dt = datetime.strptime(f"{l['date']} {l['time']}", "%Y-%m-%d %H:%M")
            if get_effective_date(l_dt, start_hour) == eff_today:
                current_cycle_logs.append(l)
        except: pass

    # Segmentation Logic (still based on clock time for "Morning/Afternoon", but using cycle logs)
    morn = sum([l['amount'] for l in current_cycle_logs if int(l['time'].split(':')[0]) < 12])
    aft = sum([l['amount'] for l in current_cycle_logs if 12 <= int(l['time'].split(':')[0]) < 17])
    eve = sum([l['amount'] for l in current_cycle_logs if int(l['time'].split(':')[0]) >= 17])
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Morning", f"{morn}ml")
    c2.metric("Afternoon", f"{aft}ml")
    c3.metric("Evening", f"{eve}ml")

    st.subheader("Quick Log")
    chip_vals = [150, 250, 350, 500]
    cols = st.columns(len(chip_vals) + 1)
    
    for i, val in enumerate(chip_vals):
        if cols[i].button(f"+{val}ml"):
            if 'logs' not in h_data: h_data['logs'] = []
            
            # Check if goal was NOT met before this add
            current_total = sum([safe_float(l['amount']) for l in current_cycle_logs])
            goal_val = safe_float(h_data.get('daily_goal', 3000))
            
            h_data['logs'].append({
                "date": today_str,
                "time": datetime.now().strftime("%H:%M"),
                "amount": val
            })
            save_data_to_cloud("hydration", h_data, current_user)
            
            # Check if goal IS met after this add
            new_total = current_total + val
            if current_total < goal_val and new_total >= goal_val:
                st.balloons()
                st.success("🎉 Daily Goal Reached!")
                time.sleep(2)
            
            st.toast(f"Logged {val}ml")
            st.rerun()

# =========================================================
# TAB 3: PLAN (SHOPPING)
# =========================================================
elif nav == "Plan (Shopping)":
    st.header("🛒 Smart Grocery Plan")
    shop_list = st.session_state.app_data['shopping']
    
    # Total Calculation
    est_total = sum([ 
        (safe_float(x.get('price_min', 0)) + safe_float(x.get('price_max',0)))/2 
        for x in shop_list if not x['bought']
    ])
    
    sc1, sc2 = st.columns([2, 1])
    sc1.metric("Est. Cart Value", f"₹{int(est_total)}")
    
    with st.expander("Add Item (Manual)", expanded=True):
        c_item, c_qty, c_unit, c_btn = st.columns([3, 1, 1, 1])
        
        new_item = c_item.text_input("Item Name", placeholder="e.g. Chicken")
        new_qty_num = c_qty.number_input("Qty", min_value=0.1, step=0.5, value=1.0)
        uom_options = ["kg", "g", "L", "ml", "pcs", "pack", "dozen", "can"]
        new_unit = c_unit.selectbox("Unit", uom_options)
        
        if c_btn.button("Add"):
            if new_item:
                final_qty_str = f"{new_qty_num} {new_unit}"
                shop_list.append({
                    "item": new_item, 
                    "qty": final_qty_str, 
                    "category": "General", 
                    "price_min": 0, "price_max": 0, 
                    "bought": False
                })
                save_data_to_cloud("shopping", shop_list, current_user)
                st.rerun()

    # Categorized View
    categories = ["Protein", "Veg", "Dairy", "Grain", "Staple", "Junk", "General"]
    for cat in categories:
        items = [x for x in shop_list if x.get('category', 'General') == cat]
        if not items: continue
        st.subheader(f"{cat}")
        for item in items:
            if item['bought']: continue
            rc1, rc2, rc3 = st.columns([0.5, 3, 1])
            
            if rc1.checkbox("", key=f"chk_{item['item']}"):
                item['bought'] = True
                save_data_to_cloud("shopping", shop_list, current_user)
                st.rerun()
            
            rc2.write(f"**{item['item']}** ({item['qty']})")
            p_min = safe_float(item.get('price_min',0))
            p_max = safe_float(item.get('price_max',0))
            if p_max > 0: rc3.caption(f"₹{int(p_min)} - ₹{int(p_max)}")
            else: rc3.caption("-")

    if st.button("🤖 Analyze & Price (AI)"):
        if not st.session_state.get('is_verified'): st.error("Connect AI")
        else:
            with st.spinner("Analyzing Hyderabad Market..."):
                items_txt = ", ".join([f"{x['item']} ({x['qty']})" for x in shop_list if not x['bought']])
                prompt = f"""
                You are a grocery price estimator for Hyderabad.
                Items: {items_txt}
                Task: 
                1. Categorize (Protein, Veg, etc). 
                2. Search online for current prices (Instamart, Blinkit, Zepto) in Hyderabad.
                3. Estimate TOTAL price for SPECIFIC QUANTITY (e.g. 500g Chicken = 120 INR, not 1kg price).
                Return JSON list: [{{ "item": "name", "category": "Protein", "price_min": 100, "price_max": 120 }}]
                """
                res = ask_ai(prompt, json_mode=True, use_search=True)
                try:
                    cleaned_res = clean_json_response(res)
                    updates = json.loads(cleaned_res)
                    count = 0
                    for u in updates:
                        for x in shop_list:
                            if x['item'].lower() in u['item'].lower():
                                x['category'] = u['category']
                                x['price_min'] = u['price_min']
                                x['price_max'] = u['price_max']
                                count+=1
                    save_data_to_cloud("shopping", shop_list, current_user)
                    st.success(f"Updated {count} items.")
                    time.sleep(1); st.rerun()
                except Exception as e: st.error(f"Error: {e}")

# =========================================================
# TAB 4: SMART CHEF
# =========================================================
elif nav == "Smart Chef":
    st.header("👨‍🍳 Smart Chef")
    
    with st.container(border=True):
        detected = st.session_state.get('detected', "")
        use_cam = st.toggle("Use Camera")
        if use_cam:
            img = st.camera_input("Scan")
            if img and st.button("Detect"):
                res = ask_ai("List visible ingredients. Comma separated.", Image.open(img))
                st.session_state['detected'] = res
                st.rerun()
        
        ingredients = st.text_area("Ingredients", value=detected)
    
    # Constraints
    cc1, cc2, cc3 = st.columns(3)
    goal = cc1.selectbox("Goal", ["High Protein", "Fat Loss", "Bulking"])
    time_limit = cc2.select_slider("Time", options=["15m", "30m", "45m", "1h+"])
    equip = cc3.multiselect("Equipment", ["Stove", "Oven", "Air Fryer", "Microwave"], default=["Stove"])

    if st.button("Find Best Meal Option", type="primary"):
        if not st.session_state.get('is_verified'): st.error("Connect AI")
        else:
            with st.spinner("Cooking..."):
                p = f"""
                Ingredients: {ingredients}. Goal: {goal}. Time: {time_limit}. Equipment: {equip}.
                Task: Create ONE best recipe. Prioritize Protein.
                Format: # Name \n **Protein:** XXg | **Cals:** XX \n ## Ingredients \n * item \n ## Instructions
                """
                st.session_state['recipe'] = ask_ai(p)

    if st.session_state.get('recipe'):
        st.markdown(st.session_state['recipe'])
        if st.button("Add to Shopping List"):
             try:
                 lines = st.session_state['recipe'].split('\n')
                 count = 0
                 capture = False
                 for line in lines:
                     # Start capturing after Ingredients header
                     if "## Ingredients" in line:
                         capture = True
                         continue
                     # Stop capturing at next header (e.g. Instructions)
                     if "##" in line and capture:
                         capture = False
                         break
                     
                     if capture:
                         clean_line = line.strip()
                         # Only add lines that look like list items
                         if clean_line.startswith("*") or clean_line.startswith("-"):
                             raw = clean_line.lstrip("*- ").strip()
                             if raw:
                                 st.session_state.app_data['shopping'].append({
                                     "item": raw, "qty": "1 unit", "category": "General", "price_min":0, "price_max":0, "bought": False
                                 })
                                 count += 1
                                 
                 save_data_to_cloud("shopping", st.session_state.app_data['shopping'], current_user)
                 if count > 0:
                    st.success(f"Added {count} ingredients.")
                 else:
                    st.warning("No ingredients found. Check recipe format.")
             except Exception as e: st.error(f"Error: {e}")

# =========================================================
# TAB 5: CHEAT NEGOTIATOR
# =========================================================
elif nav == "Cheat Negotiator":
    st.header("😈 Negotiator")
    c_data = st.session_state.app_data['cheats']
    used = c_data['used_this_week']
    limit = c_data['weekly_limit']
    
    st.progress(used/limit if limit > 0 else 0)
    st.caption(f"Used: {used}/{limit}")
    
    if used >= limit: st.error("⛔ BUDGET EXCEEDED.")
        
    want = st.text_input("I want...")
    if st.button("Judge Me"):
         p = f"""
         User wants: {want}. Budget used: {used}/{limit}.
         Act as Strict Coach. Output 3 sections Markdown:
         ## 🟥 Reality Check (Calories/Fat)
         ## 🟨 Negotiation (Compromise?)
         ## 🟩 Damage Control (If eaten)
         Verdict: APPROVED or DENIED.
         """
         with st.spinner("🧑‍⚖️ The Judge is deciding your fate..."):
             res = ask_ai(p)
         st.session_state['judge'] = res
         
    if st.session_state.get('judge'):
        st.markdown(st.session_state['judge'])
        c1, c2 = st.columns(2)
        if c1.button("I ate it"):
            c_data['used_this_week'] += 1
            save_data_to_cloud("cheats", c_data, current_user)
            st.rerun()
