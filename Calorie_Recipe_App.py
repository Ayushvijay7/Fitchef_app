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

# --- STYLING ---
st.markdown("""
    <style>
    .block-container { padding-top: 2rem; }
    .css-card {
        background-color: #ffffff;
        padding: 1.5rem;
        border-radius: 12px;
        border: 1px solid #e0e0e0;
        box-shadow: 0 2px 5px rgba(0,0,0,0.05);
        margin-bottom: 1rem;
    }
    .urgency-high { color: #e74c3c; font-weight: bold; }
    /* Mobile-friendly adjustments */
    div[data-testid="column"] { min-width: 0; }
    </style>
""", unsafe_allow_html=True)

# --- HELPER: SAFE NUMBERS ---
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

# --- DB & AUTH MANAGER ---
@st.cache_resource
def get_db_connection():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        try:
             # Try opening by name
             sheet = client.open("FitChef DB") 
        except:
             return None
        return sheet
    except Exception as e:
        return None

def fetch_user_data():
    default_data = {
        "hydration": {"logs": [], "daily_goal": 3000, "weight": 70, "activity": "Moderate"},
        "shopping": [],
        "cheats": {"used_this_week": 0, "weekly_limit": 3}
    }
    
    sh = get_db_connection()
    if not sh: return default_data 
    
    try:
        # HYDRATION
        try:
            ws = sh.worksheet("Hydration")
            raw_json = ws.cell(2, 1).value
            hydration_data = json.loads(raw_json) if raw_json else default_data["hydration"]
        except:
             hydration_data = default_data["hydration"]

        # SHOPPING
        try:
            ws_s = sh.worksheet("Shopping")
            shopping_list = ws_s.get_all_records()
            for x in shopping_list:
                x['bought'] = str(x['bought']).lower() == 'true'
        except:
            shopping_list = []

        # CHEATS
        try:
            ws_c = sh.worksheet("Cheats")
            raw_c = ws_c.cell(2, 1).value
            cheat_data = json.loads(raw_c) if raw_c else default_data["cheats"]
        except:
             cheat_data = default_data["cheats"]

        return {"hydration": hydration_data, "shopping": shopping_list, "cheats": cheat_data}

    except Exception as e:
        return default_data

def save_data_to_cloud(key, new_data):
    sh = get_db_connection()
    if not sh: return

    try:
        if key == "hydration":
            ws = sh.worksheet("Hydration")
            ws.clear()
            ws.append_row(["config_json"]) 
            ws.append_row([json.dumps(new_data)])
            
        elif key == "cheats":
            ws = sh.worksheet("Cheats")
            ws.clear()
            ws.append_row(["config_json"])
            ws.append_row([json.dumps(new_data)])
            
        elif key == "shopping":
            ws = sh.worksheet("Shopping")
            ws.clear()
            ws.append_row(["item", "qty", "category", "price_min", "price_max", "bought"])
            # Ensure safe float conversion before saving
            rows = [[x["item"], x["qty"], x.get("category", "General"), 
                     safe_float(x.get("price_min", 0)), safe_float(x.get("price_max", 0)), x["bought"]] for x in new_data]
            if rows: ws.append_rows(rows)
            
    except Exception as e:
        st.warning(f"Cloud Save Error: {e}")

# --- AI WRAPPER (UPDATED FOR JSON MODE) ---
def ask_ai(prompt, image=None, json_mode=False):
    if 'api_client' not in st.session_state or not st.session_state.api_client:
        return None if json_mode else "⚠️ AI Offline. Connect API Key."
    try:
        c = [prompt]
        if image: c.append(image)
        
        # Configure JSON mode if requested
        config = types.GenerateContentConfig(
            temperature=0.7,
            response_mime_type="application/json" if json_mode else "text/plain"
        )
        
        res = st.session_state.api_client.models.generate_content(
            model="gemini-2.5-pro",
            contents=c,
            config=config
        )
        return res.text
    except Exception as e:
        return f"AI Error: {e}"

# --- APP INIT ---
if 'app_data' not in st.session_state:
    st.session_state.app_data = fetch_user_data()

# --- SIDEBAR ---
with st.sidebar:
    st.title("🔥 FitChef Pro")
    if not st.session_state.get('is_verified'):
        k = st.text_input("Gemini API Key", type="password")
        if k:
            try:
                cl = genai.Client(api_key=k)
                cl.models.get(model="gemini-2.5-pro")
                st.session_state.api_client = cl
                st.session_state.is_verified = True
                st.success("Connected")
            except:
                st.error("Invalid Key")
    
    st.divider()
    nav = st.radio("Go to", ["Dashboard", "Fuel (Hydration)", "Plan (Shopping)", "Smart Chef", "Cheat Negotiator"])

# =========================================================
# 1. DASHBOARD
# =========================================================
if nav == "Dashboard":
    st.title("Good Afternoon, Chef.")
    
    col1, col2, col3 = st.columns(3)
    
    hydro = st.session_state.app_data['hydration']
    today_str = datetime.now().strftime("%Y-%m-%d")
    today_logs = [l for l in hydro.get('logs',[]) if l['date'] == today_str]
    total_today = sum([safe_float(l['amount']) for l in today_logs])
    goal = safe_float(hydro.get('daily_goal', 3000))
    pct = int((total_today / goal) * 100) if goal > 0 else 0
    
    with col1:
        st.metric("Hydration", f"{pct}%", f"{int(goal - total_today)}ml to go")

    cheats = st.session_state.app_data['cheats']
    left = cheats['weekly_limit'] - cheats['used_this_week']
    with col2:
        st.metric("Cheat Budget", f"{left} Left", f"{cheats['used_this_week']} used")
        
    shop = st.session_state.app_data['shopping']
    pending = len([x for x in shop if not x['bought']])
    with col3:
        st.metric("Shopping List", f"{pending} Items", "Pending")
    
    st.divider()
    if pct < 50 and datetime.now().hour > 15:
        st.warning("📉 **Insight:** Behind on water. Catch up now.")
    else:
        st.info("🚀 **Insight:** Solid pace today.")

# =========================================================
# 2. FUEL (HYDRATION)
# =========================================================
elif nav == "Fuel (Hydration)":
    st.header("💧 Fuel Status")
    h_data = st.session_state.app_data['hydration']
    
    with st.expander("⚙️ Calibrate Target"):
        w = st.number_input("Weight (kg)", value=float(h_data.get('weight', 70)))
        a = st.selectbox("Activity", ["Sedentary", "Moderate", "High"], index=1)
        rec_goal = (w * 35) + (500 if a != "Sedentary" else 0)
        st.caption(f"Recommended: {int(rec_goal)}ml")
        
        new_goal = st.number_input("Goal", value=float(h_data.get('daily_goal', 3000)))
        if st.button("Save"):
            h_data['weight'] = w
            h_data['activity'] = a
            h_data['daily_goal'] = new_goal
            save_data_to_cloud("hydration", h_data)
            st.rerun()

    today_str = datetime.now().strftime("%Y-%m-%d")
    logs = [l for l in h_data.get('logs',[]) if l['date'] == today_str]
    
    morn = sum([l['amount'] for l in logs if int(l['time'].split(':')[0]) < 12])
    aft = sum([l['amount'] for l in logs if 12 <= int(l['time'].split(':')[0]) < 17])
    eve = sum([l['amount'] for l in logs if int(l['time'].split(':')[0]) >= 17])
    
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
            h_data['logs'].append({
                "date": today_str,
                "time": datetime.now().strftime("%H:%M"),
                "amount": val
            })
            save_data_to_cloud("hydration", h_data)
            st.toast(f"Logged {val}ml")
            st.rerun()

# =========================================================
# 3. PLAN (SHOPPING) - FIXED
# =========================================================
elif nav == "Plan (Shopping)":
    st.header("🛒 Smart Grocery Plan")
    shop_list = st.session_state.app_data['shopping']
    
    # Calculate Total
    est_total = sum([ 
        (safe_float(x.get('price_min', 0)) + safe_float(x.get('price_max',0)))/2 * safe_parse_qty(x['qty']) 
        for x in shop_list if not x['bought']
    ])
    
    sc1, sc2 = st.columns([2, 1])
    sc1.metric("Est. Cart Value", f"₹{int(est_total)}")
    
    # --- FIX 1: Split Unit Input ---
    with st.expander("Add Item (Manual)", expanded=True):
        c_item, c_qty, c_unit, c_btn = st.columns([3, 1, 1, 1])
        
        new_item = c_item.text_input("Item Name", placeholder="e.g. Chicken Breast")
        # Numeric input for quantity
        new_qty_num = c_qty.number_input("Qty", min_value=0.1, step=0.5, value=1.0)
        # Dropdown for UoM
        uom_options = ["kg", "g", "L", "ml", "pcs", "pack", "dozen", "can", "tbsp", "tsp"]
        new_unit = c_unit.selectbox("Unit", uom_options)
        
        if c_btn.button("Add"):
            if new_item:
                # Combine them for storage (e.g., "1.5 kg")
                final_qty_str = f"{new_qty_num} {new_unit}"
                
                shop_list.append({
                    "item": new_item, 
                    "qty": final_qty_str, 
                    "category": "General", 
                    "price_min": 0, 
                    "price_max": 0, 
                    "bought": False
                })
                save_data_to_cloud("shopping", shop_list)
                st.rerun()

    # List View
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
                save_data_to_cloud("shopping", shop_list)
                st.rerun()
            
            rc2.write(f"**{item['item']}** ({item['qty']})")
            p_avg = (safe_float(item.get('price_min',0)) + safe_float(item.get('price_max',0)))/2
            rc3.caption(f"₹{int(p_avg)}" if p_avg > 0 else "-")

    # --- FIX 2: AI Parse Error Fix (JSON Mode) ---
    if st.button("🤖 Analyze & Price (AI)"):
        if not st.session_state.get('is_verified'): 
            st.error("Connect AI first")
        else:
            with st.spinner("Analyzing..."):
                items_txt = ", ".join([x['item'] for x in shop_list if not x['bought']])
                
                # We simply ask for the list, but we pass json_mode=True to ask_ai
                prompt = f"""
                You are a grocery price estimator for Hyderabad, India.
                Items: {items_txt}
                
                Return a JSON list of objects with these keys:
                - item (exact name from input)
                - category (Protein, Veg, Grain, Dairy, Staple, Junk, General)
                - price_min (estimated price per unit in INR)
                - price_max (estimated price per unit in INR)
                """
                
                # Pass json_mode=True to force strict JSON output
                res = ask_ai(prompt, json_mode=True)
                
                try:
                    # It returns valid JSON now, so we can load it directly
                    updates = json.loads(res)
                    
                    match_count = 0
                    for u in updates:
                        for x in shop_list:
                            # Fuzzy matching item names
                            if x['item'].lower() in u['item'].lower():
                                x['category'] = u['category']
                                x['price_min'] = u['price_min']
                                x['price_max'] = u['price_max']
                                match_count += 1
                                
                    save_data_to_cloud("shopping", shop_list)
                    st.success(f"Updated prices for {match_count} items!")
                    time.sleep(1) # Pause so user sees success msg
                    st.rerun()
                except Exception as e:
                    st.error(f"Analysis Failed: {str(e)}")
                    st.caption("Raw AI Response (Debug): " + str(res))

# =========================================================
# 4. SMART CHEF
# =========================================================
elif nav == "Smart Chef":
    st.header("👨‍🍳 Smart Chef")
    
    with st.container(border=True):
        detected = st.session_state.get('detected', "")
        use_cam = st.toggle("Use Camera")
        if use_cam:
            img = st.camera_input("Scan")
            if img and st.button("Detect"):
                res = ask_ai("List visible ingredients", Image.open(img))
                st.session_state['detected'] = res
                st.rerun()
        
        ingredients = st.text_area("Ingredients", value=detected)
    
    if st.button("Find Meal"):
        if not st.session_state.get('is_verified'): st.error("Connect AI")
        else:
            with st.spinner("Cooking..."):
                p = f"Ingredients: {ingredients}. Create 1 high protein recipe. Format: # Name \n ## Ingredients \n * item \n ## Instructions"
                st.session_state['recipe'] = ask_ai(p)

    if st.session_state.get('recipe'):
        st.markdown(st.session_state['recipe'])
        if st.button("Add to Shopping List"):
             st.session_state.app_data['shopping'].append({"item": "Recipe Items", "qty": "1", "category": "General", "bought": False})
             save_data_to_cloud("shopping", st.session_state.app_data['shopping'])
             st.success("Added")

# =========================================================
# 5. CHEAT NEGOTIATOR
# =========================================================
elif nav == "Cheat Negotiator":
    st.header("😈 Negotiator")
    c_data = st.session_state.app_data['cheats']
    used = c_data['used_this_week']
    limit = c_data['weekly_limit']
    
    st.progress(used/limit if limit > 0 else 0)
    st.write(f"Used: {used}/{limit}")
    
    want = st.text_input("I want...")
    if st.button("Judge Me"):
         res = ask_ai(f"User wants {want}. Strict coach mode. 1. Reality Check 2. Compromise 3. Damage Control. Verdict: APPROVED/DENIED.")
         st.session_state['judge'] = res
         
    if st.session_state.get('judge'):
        st.markdown(st.session_state['judge'])
        c1, c2 = st.columns(2)
        if c1.button("I ate it"):
            c_data['used_this_week'] += 1
            save_data_to_cloud("cheats", c_data)
            st.rerun()
