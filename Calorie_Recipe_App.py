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

# --- PAGE CONFIG ---
st.set_page_config(
    page_title="FitChef Pro",
    page_icon="🔥",
    layout="wide",
    initial_sidebar_state="collapsed" # Focus on content
)

# --- STYLING & CSS ---
st.markdown("""
    <style>
    /* Global Cleanliness */
    .block-container { padding-top: 2rem; }
    
    /* Card Styling */
    .css-card {
        background-color: #ffffff;
        padding: 1.5rem;
        border-radius: 12px;
        border: 1px solid #e0e0e0;
        box-shadow: 0 2px 5px rgba(0,0,0,0.05);
        margin-bottom: 1rem;
    }
    
    /* Segmented Progress Bars */
    .progress-label { font-size: 0.8rem; font-weight: bold; color: #555; }
    
    /* Urgency Text */
    .urgency-high { color: #e74c3c; font-weight: bold; }
    .urgency-ok { color: #27ae60; font-weight: bold; }
    
    /* Shopping List Rows */
    .shop-row {
        padding: 10px;
        border-bottom: 1px solid #eee;
        display: flex;
        align-items: center;
    }
    
    /* Cheat Negotiator Colors */
    .cheat-red { border-left: 5px solid #e74c3c; padding-left: 10px; }
    .cheat-yellow { border-left: 5px solid #f1c40f; padding-left: 10px; }
    .cheat-green { border-left: 5px solid #27ae60; padding-left: 10px; }
    </style>
""", unsafe_allow_html=True)

# --- DB & AUTH MANAGER ---
@st.cache_resource
def get_db_connection():
    """Connects to Google Sheets with error handling."""
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        
        # Try opening by Key first (Safest), then Name
        try:
             # Replace with your actual sheet key if you have it
             # sheet = client.open_by_key("YOUR_SHEET_KEY") 
             sheet = client.open("FitChef DB") 
        except:
             sheet = client.open("FitChef DB")
             
        return sheet
    except Exception as e:
        return None

def fetch_user_data():
    """Fetches data and structures it for the app."""
    default_data = {
        "hydration": {"logs": [], "daily_goal": 3000, "start_hour": 6, "weight": 70, "activity": "Moderate"},
        "shopping": [],
        "cheats": {"used_this_week": 0, "weekly_limit": 3, "history": []}
    }
    
    sh = get_db_connection()
    if not sh: return default_data # Offline mode
    
    try:
        # HYDRATION TAB
        try:
            ws = sh.worksheet("Hydration")
            recs = ws.get_all_records()
            if recs:
                # Parse JSON string from cell if complex data, or use simple cols
                # For robustness, we assume row 1 contains JSON config
                # But to keep it simple for GSheets, we will use a JSON dump in cell A2
                raw_json = ws.cell(2, 1).value
                if raw_json:
                    hydration_data = json.loads(raw_json)
                else:
                    hydration_data = default_data["hydration"]
            else:
                hydration_data = default_data["hydration"]
        except:
             hydration_data = default_data["hydration"]

        # SHOPPING TAB
        try:
            ws_s = sh.worksheet("Shopping")
            shopping_list = ws_s.get_all_records()
            # Normalize booleans
            for x in shopping_list:
                x['bought'] = str(x['bought']).lower() == 'true'
        except:
            shopping_list = []

        # CHEAT TAB
        try:
            ws_c = sh.worksheet("Cheats")
            c_recs = ws_c.get_all_records()
            if c_recs:
                raw_c = ws_c.cell(2, 1).value
                cheat_data = json.loads(raw_c) if raw_c else default_data["cheats"]
            else:
                cheat_data = default_data["cheats"]
        except:
             cheat_data = default_data["cheats"]

        return {"hydration": hydration_data, "shopping": shopping_list, "cheats": cheat_data}

    except Exception as e:
        st.error(f"Data Sync Error: {e}")
        return default_data

def save_data_to_cloud(key, new_data):
    """Saves specific sections to GSheets."""
    sh = get_db_connection()
    if not sh: return

    try:
        if key == "hydration":
            ws = sh.worksheet("Hydration")
            ws.clear()
            ws.append_row(["config_json"]) # Header
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
            rows = [[x["item"], x["qty"], x.get("category", "General"), 
                     x.get("price_min", 0), x.get("price_max", 0), x["bought"]] for x in new_data]
            if rows: ws.append_rows(rows)
            
    except Exception as e:
        st.warning(f"Could not save to cloud: {e}")

# --- AI WRAPPER ---
def ask_ai(prompt, image=None):
    if 'api_client' not in st.session_state or not st.session_state.api_client:
        return "⚠️ AI Offline. Connect API Key."
    try:
        c = [prompt]
        if image: c.append(image)
        res = st.session_state.api_client.models.generate_content(
            model="gemini-2.5-pro",
            contents=c,
            config=types.GenerateContentConfig(temperature=0.7)
        )
        return res.text
    except Exception as e:
        return f"AI Error: {e}"

# --- INITIALIZATION ---
if 'app_data' not in st.session_state:
    st.session_state.app_data = fetch_user_data()

# --- SIDEBAR: NAVIGATION & AUTH ---
with st.sidebar:
    st.title("🔥 FitChef Pro")
    
    # Auth
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
    st.caption("v3.0.1 Mobile Ready")

# =========================================================
# 1. UNIFIED DASHBOARD
# =========================================================
if nav == "Dashboard":
    st.title("Good Afternoon, Chef.")
    
    # 1. Summary Cards
    col1, col2, col3 = st.columns(3)
    
    # Hydro Logic
    hydro = st.session_state.app_data['hydration']
    today_str = datetime.now().strftime("%Y-%m-%d")
    today_logs = [l for l in hydro['logs'] if l['date'] == today_str]
    total_today = sum([l['amount'] for l in today_logs])
    pct = int((total_today / hydro['daily_goal']) * 100)
    
    with col1:
        st.metric("Hydration", f"{pct}%", f"{hydro['daily_goal'] - total_today}ml to go")
        if pct < 40: st.markdown(":red[⚠️ Dehydrated]")
        else: st.markdown(":green[✅ On Track]")

    # Cheat Logic
    cheats = st.session_state.app_data['cheats']
    left = cheats['weekly_limit'] - cheats['used_this_week']
    with col2:
        st.metric("Cheat Budget", f"{left} Left", f"{cheats['used_this_week']} used")
        
    # Shopping Logic
    shop = st.session_state.app_data['shopping']
    pending = len([x for x in shop if not x['bought']])
    with col3:
        st.metric("Shopping List", f"{pending} Items", "Pending")

    st.divider()
    
    # 2. Brutal Truth / Insight
    if pct < 50 and datetime.now().hour > 15:
        st.warning("📉 **Insight:** You are sabotaging your recovery. Drink 500ml NOW.")
    elif left == 0:
        st.error("⛔ **Insight:** No cheats left. Don't even think about pizza.")
    else:
        st.info("🚀 **Insight:** Solid pace today. Keep it up.")

# =========================================================
# 2. FUEL (HYDRATION)
# =========================================================
elif nav == "Fuel (Hydration)":
    st.header("💧 Fuel Status")
    
    h_data = st.session_state.app_data['hydration']
    
    # A. Adaptive Target Logic
    with st.expander("⚙️ Calibrate Target"):
        w = st.number_input("Weight (kg)", value=h_data.get('weight', 70))
        a = st.selectbox("Activity", ["Sedentary", "Moderate", "High"], index=1)
        
        # Simple formula: 35ml per kg + 500ml for activity
        rec_goal = (w * 35) + (500 if a != "Sedentary" else 0)
        
        st.caption(f"Recommended based on biology: {rec_goal}ml")
        new_goal = st.number_input("Your Goal", value=h_data.get('daily_goal', 3000))
        
        if st.button("Save Calibration"):
            h_data['weight'] = w
            h_data['activity'] = a
            h_data['daily_goal'] = new_goal
            save_data_to_cloud("hydration", h_data)
            st.rerun()

    # B. Time Segmentation Logic
    today_str = datetime.now().strftime("%Y-%m-%d")
    logs = [l for l in h_data['logs'] if l['date'] == today_str]
    
    morn = sum([l['amount'] for l in logs if int(l['time'].split(':')[0]) < 12])
    aft = sum([l['amount'] for l in logs if 12 <= int(l['time'].split(':')[0]) < 17])
    eve = sum([l['amount'] for l in logs if int(l['time'].split(':')[0]) >= 17])
    total = morn + aft + eve
    
    # Targets (Rough breakdown: 40% morn, 40% aft, 20% eve)
    g_morn = h_data['daily_goal'] * 0.4
    g_aft = h_data['daily_goal'] * 0.4
    g_eve = h_data['daily_goal'] * 0.2
    
    # C. Display Segments
    c1, c2, c3 = st.columns(3)
    c1.metric("Morning (6-12)", f"{morn}ml", f"Target: {int(g_morn)}")
    c2.metric("Afternoon (12-5)", f"{aft}ml", f"Target: {int(g_aft)}")
    c3.metric("Evening (5+)", f"{eve}ml", f"Target: {int(g_eve)}")
    
    # D. Urgency Banner
    now_hour = datetime.now().hour
    expected_pct = ((now_hour - 7) / 16) # Roughly awake 16 hours
    expected_pct = max(0.1, min(expected_pct, 1.0))
    current_pct = total / h_data['daily_goal']
    
    if current_pct < (expected_pct - 0.15):
        st.error(f"⚠️ **Urgency:** You are {int((expected_pct - current_pct)*100)}% behind schedule. Catch up!")
    
    # E. Smart Input (Chips)
    st.subheader("Quick Log")
    # Streamlit Pills (requires 1.40, falling back to columns for compatibility if needed)
    # using columns to simulate chips
    chip_vals = [150, 250, 350, 500]
    cols = st.columns(len(chip_vals) + 1)
    
    for i, val in enumerate(chip_vals):
        if cols[i].button(f"+{val}ml"):
            new_log = {
                "date": today_str,
                "time": datetime.now().strftime("%H:%M"),
                "amount": val
            }
            h_data['logs'].append(new_log)
            save_data_to_cloud("hydration", h_data)
            st.toast(f"✅ Logged {val}ml. Keep flowing!", icon="💧")
            st.rerun()
            
    # Custom Input
    with cols[-1].popover("Custom"):
        cust = st.number_input("Amount", 50, 1000, step=50)
        if st.button("Add"):
            h_data['logs'].append({"date": today_str, "time": datetime.now().strftime("%H:%M"), "amount": cust})
            save_data_to_cloud("hydration", h_data)
            st.rerun()

# =========================================================
# 3. PLAN (SHOPPING)
# =========================================================
elif nav == "Plan (Shopping)":
    st.header("🛒 Smart Grocery Plan")
    shop_list = st.session_state.app_data['shopping']
    
    # A. Budget & Nudges Header
    est_total = sum([ (x.get('price_min', 0) + x.get('price_max',0))/2 * int(x['qty']) for x in shop_list if not x['bought']])
    cheat_count = len([x for x in shop_list if x.get('category') == 'Junk' and not x['bought']])
    
    sc1, sc2 = st.columns([2, 1])
    sc1.metric("Estimated Cart Value", f"₹{int(est_total)}")
    if cheat_count >= 3:
        sc2.warning(f"⚠️ {cheat_count} Cheat items in cart!")
    
    st.divider()
    
    # B. Add Item (Quick)
    with st.expander("Add Item (Manual)", expanded=False):
        ac1, ac2, ac3, ac4 = st.columns([3, 1, 2, 1])
        new_item = ac1.text_input("Item Name")
        new_qty = ac2.text_input("Qty", "1")
        new_cat = ac3.selectbox("Category", ["Protein", "Veg", "Grain", "Dairy", "Staple", "Junk"])
        if ac4.button("Add"):
            shop_list.append({
                "item": new_item, "qty": new_qty, "category": new_cat, 
                "price_min": 0, "price_max": 0, "bought": False
            })
            save_data_to_cloud("shopping", shop_list)
            st.rerun()

    # C. Structured List (Grouped)
    categories = ["Protein", "Veg", "Dairy", "Grain", "Staple", "Junk", "General"]
    
    for cat in categories:
        items = [x for x in shop_list if x.get('category', 'General') == cat]
        if not items: continue
        
        st.subheader(f"{cat} ({len(items)})")
        
        for item in items:
            # Row Layout
            if item['bought']: continue # Hide bought items (Archived view can be separate)
            
            rc1, rc2, rc3, rc4 = st.columns([0.5, 3, 1.5, 1])
            
            # Checkbox
            if rc1.checkbox("", key=f"chk_{item['item']}"):
                item['bought'] = True
                save_data_to_cloud("shopping", shop_list)
                st.rerun()
                
            # Details
            rc2.markdown(f"**{item['item']}**")
            
            # Price Intelligence
            p_min = item.get('price_min', 0)
            p_max = item.get('price_max', 0)
            if p_max > 0:
                conf_color = "🟢" if (p_max - p_min) < 20 else "🟡"
                rc3.caption(f"{conf_color} ₹{p_min}-{p_max}")
            else:
                rc3.caption("price unknown")
                
            # Qty badge
            rc4.markdown(f"`x{item['qty']}`")
            
    # D. Auto-Archive Logic happens on checkbox click above

    # E. Price Intelligence Button
    if st.button("🤖 Analyze Prices & Sort"):
        if not st.session_state.get('is_verified'): st.error("Connect AI first")
        else:
            with st.spinner("Fetching market rates..."):
                # Construct simple prompt
                items_txt = ", ".join([x['item'] for x in shop_list if not x['bought']])
                prompt = f"""
                List: {items_txt}.
                Task:
                1. Categorize each into: Protein, Veg, Grain, Dairy, Staple, Junk.
                2. Estimate price range in INR (Hyderabad).
                Output JSON only:
                [
                  {{"item": "name", "category": "cat", "price_min": 10, "price_max": 20}},
                  ...
                ]
                """
                res = ask_ai(prompt)
                try:
                    # Clean json
                    clean = res.replace("```json","").replace("```","").strip()
                    updates = json.loads(clean)
                    
                    # Update local list
                    for u in updates:
                        for x in shop_list:
                            if x['item'].lower() in u['item'].lower():
                                x['category'] = u['category']
                                x['price_min'] = u['price_min']
                                x['price_max'] = u['price_max']
                    
                    save_data_to_cloud("shopping", shop_list)
                    st.rerun()
                except Exception as e:
                    st.error(f"AI parsing failed: {e}")

# =========================================================
# 4. SMART CHEF
# =========================================================
elif nav == "Smart Chef":
    st.header("👨‍🍳 Smart Chef")
    
    # ZONE 1: INPUT
    with st.container(border=True):
        st.markdown("### 1. What's available?")
        
        # Camera Flow
        use_cam = st.toggle("Scan Fridge/Pantry")
        detected_tags = []
        if use_cam:
            img = st.camera_input("Snap photo")
            if img:
                if st.button("🔍 Detect Ingredients"):
                    with st.spinner("Vision AI analyzing..."):
                        res = ask_ai("List visible ingredients. Comma separated only.", Image.open(img))
                        st.session_state['detected_ingredients'] = res
            
            if 'detected_ingredients' in st.session_state:
                st.info(f"Detected: {st.session_state['detected_ingredients']}")
                
        # Manual Tags
        ingredients = st.text_area("Or type ingredients", value=st.session_state.get('detected_ingredients', ""))

    # ZONE 2: CONSTRAINTS
    with st.container(border=True):
        st.markdown("### 2. Constraints")
        cc1, cc2, cc3 = st.columns(3)
        goal = cc1.selectbox("Goal", ["High Protein", "Fat Loss", "Bulking"])
        time_limit = cc2.select_slider("Time", options=["15m", "30m", "45m", "1h+"])
        equip = cc3.multiselect("Equipment", ["Stove", "Oven", "Air Fryer", "Microwave"], default=["Stove"])

    # ZONE 3: OUTPUT
    if st.button("Find Best Meal Option", type="primary"):
        if not st.session_state.get('is_verified'): st.error("Connect AI")
        else:
            with st.spinner("Chef is thinking..."):
                p = f"""
                Ingredients: {ingredients}.
                Goal: {goal}. Time: {time_limit}. Equipment: {equip}.
                
                Task: Create ONE best recipe. Prioritize Protein.
                
                Format:
                # [Recipe Name]
                **Est. Protein:** XXg | **Calories:** XX
                
                ### Ingredients (List for Shopping)
                * [qty] [item]
                
                ### Instructions
                1. ...
                
                ### Why this meal?
                One short sentence linking to {goal}.
                """
                st.session_state['recipe_result'] = ask_ai(p)
    
    if st.session_state.get('recipe_result'):
        st.divider()
        st.markdown(st.session_state['recipe_result'])
        
        # Cross-Tab Action
        if st.button("➕ Add Ingredients to Shopping List"):
            # Simple parser
            try:
                lines = st.session_state['recipe_result'].split('\n')
                in_ing_section = False
                added_count = 0
                for line in lines:
                    if "Ingredients" in line: in_ing_section = True
                    elif "Instructions" in line: in_ing_section = False
                    
                    if in_ing_section and "*" in line:
                        # Extract item
                        raw = line.replace("*", "").strip()
                        # Add to shop list
                        st.session_state.app_data['shopping'].append({
                            "item": raw, "qty": "1", "category": "General", 
                            "price_min": 0, "price_max": 0, "bought": False
                        })
                        added_count += 1
                
                save_data_to_cloud("shopping", st.session_state.app_data['shopping'])
                st.success(f"Added {added_count} items to Plan tab.")
            except:
                st.error("Could not auto-parse. Add manually.")

# =========================================================
# 5. CHEAT NEGOTIATOR
# =========================================================
elif nav == "Cheat Negotiator":
    st.header("😈 The Negotiator")
    
    # Weekly Budget Display
    c_data = st.session_state.app_data['cheats']
    used = c_data['used_this_week']
    limit = c_data['weekly_limit']
    
    st.progress(used/limit if limit > 0 else 0)
    st.caption(f"Weekly Budget: {used}/{limit} used")
    
    if used >= limit:
        st.error("⛔ BUDGET EXCEEDED. Proceed at your own risk.")
        
    craving = st.text_input("I want to eat...", placeholder="e.g., Large Pizza")
    
    if st.button("Talk me out of it") or st.button("Is this worth it?"):
        if not st.session_state.get('is_verified'): st.error("Connect AI")
        else:
            with st.spinner("Analyzing damage..."):
                p = f"""
                User wants: {craving}.
                Weekly budget status: {used}/{limit}.
                
                Act as a Strict Fitness Coach.
                Output 3 sections using Markdown headers:
                
                ## 🟥 Reality Check
                (Calories, Fat, Sugar impact. Be brutal.)
                
                ## 🟨 Negotiation
                (Offer a modification to save 50% calories OR a trade-off like 'Skip dinner').
                
                ## 🟩 Damage Control
                (If they eat it: Water intake? Walk duration? Next meal adjustment?)
                
                End with a Verdict: **APPROVED** or **DENIED**.
                """
                st.session_state['negotiation_res'] = ask_ai(p)

    if st.session_state.get('negotiation_res'):
        st.markdown("---")
        # Parsing blocks for UI (Simulated cards via markdown)
        res = st.session_state['negotiation_res']
        
        # Display raw structured markdown which looks good
        st.markdown(res)
        
        c1, c2 = st.columns(2)
        if c1.button("I ate it (Log Cheat)"):
            c_data['used_this_week'] += 1
            save_data_to_cloud("cheats", c_data)
            st.warning("Logged. Budget updated.")
            st.rerun()
            
        if c2.button("I resisted"):
            st.balloons()
            st.success("Strong work. Saving your goals.")
