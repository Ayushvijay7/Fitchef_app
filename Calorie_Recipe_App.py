import streamlit as st
from google import genai
from google.genai import types
from PIL import Image
import json
import os
from datetime import datetime, timedelta
import ast

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="FitChef Pro",
    page_icon="🥑",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CONSTANTS & SETUP ---
DATA_FILE = "user_data.json"
DEFAULT_DATA = {
    "hydration": {
        "last_log_date": "",  # Format: YYYY-MM-DD representing the 'logical' day
        "total_ml": 0,
        "daily_goal_ml": 3000,
        "day_start_hour": 6   # 6 AM default
    },
    "shopping_list": []       # List of dicts: {item, qty, user_price, ai_price, bought}
}

# --- DATA PERSISTENCE HELPERS ---
def load_data():
    if not os.path.exists(DATA_FILE):
        return DEFAULT_DATA
    with open(DATA_FILE, "r") as f:
        try:
            return json.load(f)
        except:
            return DEFAULT_DATA

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

def get_logical_date(start_hour):
    """
    Calculates the 'current day' based on the user's start hour.
    If day starts at 6AM, then 5AM on Jan 6th is still Jan 5th.
    """
    now = datetime.now()
    if now.hour < start_hour:
        return (now - timedelta(days=1)).strftime("%Y-%m-%d")
    return now.strftime("%Y-%m-%d")

# Initialize Data
app_data = load_data()

# --- CSS STYLING ---
st.markdown("""
    <style>
    .status-ok { color: #2ecc71; font-weight: bold; }
    .status-err { color: #e74c3c; font-weight: bold; }
    div[data-testid="stMetricValue"] { font-size: 28px; color: #2E86C1; }
    
    /* Custom Card Styling */
    .css-card {
        background-color: #f9f9f9;
        padding: 15px;
        border-radius: 10px;
        border: 1px solid #ddd;
        margin-bottom: 10px;
    }
    </style>
""", unsafe_allow_html=True)

# --- SESSION STATE ---
if 'api_client' not in st.session_state:
    st.session_state.api_client = None
if 'is_verified' not in st.session_state:
    st.session_state.is_verified = False
if 'negotiation_result' not in st.session_state:
    st.session_state.negotiation_result = None

# --- SIDEBAR ---
with st.sidebar:
    st.title("🥑 FitChef Pro")
    
    # API Key
    api_key = st.text_input("Gemini API Key", type="password")
    if api_key:
        try:
            client = genai.Client(api_key=api_key)
            # Verify connection
            client.models.get(model="gemini-2.5-pro") 
            st.session_state.api_client = client
            st.session_state.is_verified = True
            st.markdown('<p class="status-ok">✅ Online</p>', unsafe_allow_html=True)
        except:
            st.session_state.is_verified = False
            st.markdown('<p class="status-err">❌ Offline</p>', unsafe_allow_html=True)
    
    st.divider()
    
    # User Profile (Saved in Session State for temporary context)
    st.subheader("👤 Context")
    fitness_goal = st.selectbox("Goal", ["Fat Loss", "Muscle Gain", "Maintenance"])
    
    st.divider()
    
    # Navigation
    menu = st.radio("Navigate", [
        "💧 Hydration Tracker", 
        "🛒 Smart Shopping", 
        "👨‍🍳 Chef & Scanner",
        "😈 Cheat Negotiator"
    ])
    
    st.divider()
    st.caption(f"📅 Date: {datetime.now().strftime('%d %b %Y')}")

# --- HELPER: GEMINI CALL ---
def ask_gemini(prompt, image=None):
    if not st.session_state.api_client: return None
    try:
        contents = [prompt]
        if image: contents.append(image)
        resp = st.session_state.api_client.models.generate_content(
            model="gemini-2.5-pro", contents=contents
        )
        return resp.text
    except Exception as e:
        return f"Error: {e}"

# ==========================================
# FEATURE 1: ADVANCED HYDRATION TRACKER
# ==========================================
if menu == "💧 Hydration Tracker":
    st.header("💧 Precision Hydration")
    
    # 1. Configuration
    with st.expander("⚙️ Configure Your Day Cycle"):
        st.caption("Set when your 'logical day' starts. E.g., if you sleep at 1 AM, set this to 04 (4 AM) so your late-night water counts for 'today'.")
        col_conf1, col_conf2 = st.columns(2)
        new_start_hour = col_conf1.number_input("Day Starts At (Hour 0-23)", 0, 23, app_data["hydration"]["day_start_hour"])
        new_goal = col_conf2.number_input("Daily Goal (mL)", 1000, 5000, app_data["hydration"]["daily_goal_ml"])
        
        if new_start_hour != app_data["hydration"]["day_start_hour"] or new_goal != app_data["hydration"]["daily_goal_ml"]:
            app_data["hydration"]["day_start_hour"] = new_start_hour
            app_data["hydration"]["daily_goal_ml"] = new_goal
            save_data(app_data)
            st.rerun()

    # 2. Logic: Check for New Day
    current_logical_date = get_logical_date(app_data["hydration"]["day_start_hour"])
    
    if app_data["hydration"]["last_log_date"] != current_logical_date:
        # It's a new day! Reset counter.
        app_data["hydration"]["last_log_date"] = current_logical_date
        app_data["hydration"]["total_ml"] = 0
        save_data(app_data)
        st.toast(f"Good Morning! Hydration reset for {current_logical_date}")

    # 3. Display & Input
    col_main, col_add = st.columns([1, 1])
    
    with col_main:
        current_ml = app_data["hydration"]["total_ml"]
        goal_ml = app_data["hydration"]["daily_goal_ml"]
        progress = min(current_ml / goal_ml, 1.0)
        
        st.metric("Today's Intake", f"{current_ml} mL", delta=f"{goal_ml - current_ml} mL remaining")
        st.progress(progress)
        
    with col_add:
        st.subheader("Log Water")
        glass_size = st.select_slider("Glass Size", options=[150, 250, 500, 750, 1000], value=250)
        
        if st.button(f"Drink {glass_size} mL 🥤", type="primary"):
            app_data["hydration"]["total_ml"] += glass_size
            save_data(app_data)
            st.rerun()

# ==========================================
# FEATURE 2: SMART SHOPPING LIST
# ==========================================
elif menu == "🛒 Smart Shopping":
    st.header("🛒 Intelligent Grocery List")

    # 1. Add Item Form
    with st.container():
        c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
        new_item = c1.text_input("Item Name", placeholder="e.g. 1kg Brown Rice")
        new_qty = c2.text_input("Qty", value="1")
        new_price = c3.number_input("Your Price (₹)", min_value=0.0, step=10.0)
        
        if c4.button("Add Item"):
            if new_item:
                # Add to local DB
                item_entry = {
                    "item": new_item, 
                    "qty": new_qty, 
                    "user_price": new_price, 
                    "ai_price": 0, # Placeholder
                    "bought": False
                }
                app_data["shopping_list"].append(item_entry)
                save_data(app_data)
                st.rerun()

    st.divider()

    # 2. List Display
    if not app_data["shopping_list"]:
        st.info("List is empty.")
    else:
        # Header
        h1, h2, h3, h4, h5 = st.columns([0.5, 3, 1, 1, 1])
        h1.write("**Done**")
        h2.write("**Item**")
        h3.write("**Qty**")
        h4.write("**My Price (₹)**")
        h5.write("**Market Est (₹)**")
        
        total_user_cost = 0

        for i, entry in enumerate(app_data["shopping_list"]):
            c1, c2, c3, c4, c5 = st.columns([0.5, 3, 1, 1, 1])
            
            # Checkbox updates 'bought' status
            is_checked = c1.checkbox("", value=entry["bought"], key=f"chk_{i}")
            if is_checked != entry["bought"]:
                entry["bought"] = is_checked
                save_data(app_data)
                st.rerun()
            
            # Strikethrough if bought
            style = "text-decoration: line-through; color: grey;" if entry["bought"] else ""
            
            c2.markdown(f"<span style='{style}'>{entry['item']}</span>", unsafe_allow_html=True)
            c3.write(entry["qty"])
            c4.write(f"₹{entry['user_price']}")
            
            # AI Price Display
            ai_p = entry.get('ai_price', 0)
            if ai_p > 0:
                diff = entry['user_price'] - ai_p
                # Green if user paid less than market, Red if paid more
                color = "green" if diff < 0 else "red" 
                c5.markdown(f"₹{ai_p} <span style='color:{color}; font-size:0.8em'>({diff:+.0f})</span>", unsafe_allow_html=True)
            else:
                c5.write("-")
            
            if not entry["bought"]:
                total_user_cost += entry["user_price"]

        st.divider()
        
        # 3. Features: Clear & AI Estimate
        f_col1, f_col2 = st.columns([1, 1])
        
        with f_col1:
            if st.button("🗑️ Clear Checked Items"):
                app_data["shopping_list"] = [x for x in app_data["shopping_list"] if not x["bought"]]
                save_data(app_data)
                st.rerun()
                
        with f_col2:
            if st.button("🤖 Estimate Market Prices (Gemini)"):
                if not st.session_state.is_verified:
                    st.error("Connect API first")
                else:
                    with st.spinner("Analyzing Hyderabad market prices..."):
                        # Prepare the list for Gemini
                        items_str = ", ".join([f"{x['item']} (Qty: {x['qty']})" for x in app_data["shopping_list"]])
                        
                        prompt = f"""
                        I am shopping in Hyderabad, India. Currency: INR (₹).
                        Estimate the current market price for these items: {items_str}.
                        
                        Return ONLY a JSON array of numbers representing the estimated price for the total quantity of each item, in the same order. 
                        Example format: [50, 200, 30]
                        Do not output markdown code blocks. Just the raw array.
                        """
                        
                        try:
                            resp = ask_gemini(prompt)
                            # Clean response to get just the list
                            cleaned_resp = resp.replace("```json", "").replace("```", "").strip()
                            prices = ast.literal_eval(cleaned_resp)
                            
                            if len(prices) == len(app_data["shopping_list"]):
                                for idx, p in enumerate(prices):
                                    app_data["shopping_list"][idx]["ai_price"] = p
                                save_data(app_data)
                                st.rerun()
                            else:
                                st.error("AI returned mismatched data count. Try again.")
                        except Exception as e:
                            st.error(f"Pricing Error: {e}")

        st.metric("Estimated Cart Value (Pending Items)", f"₹{total_user_cost}")

# ==========================================
# FEATURE 3: CHEF & SCANNER
# ==========================================
elif menu == "👨‍🍳 Chef & Scanner":
    st.header("👨‍🍳 Smart Kitchen")
    
    # Toggle Camera
    enable_cam = st.toggle("Enable Camera")
    
    c_col1, c_col2 = st.columns([2, 1])
    
    with c_col1:
        ingredients = st.text_area("Ingredients", placeholder="What's in your fridge? (Text)", height=100)
    with c_col2:
        img_file = None
        if enable_cam:
            img_file = st.camera_input("Scan Food")
    
    action = st.radio("Action", ["Generate Recipe", "Analyze Calories"], horizontal=True)
    
    if st.button("Go"):
        if not st.session_state.is_verified:
            st.error("API Key Needed")
        else:
            final_img = Image.open(img_file) if img_file else None
            
            with st.spinner("Processing..."):
                if action == "Generate Recipe":
                    prompt = f"""
                    Create a recipe for these ingredients: {ingredients}.
                    User Goal: {fitness_goal}.
                    Location: Hyderabad, India (Use metric units).
                    At the end, list ingredients in {{curly braces}} for the shopping list.
                    """
                    res = ask_gemini(prompt, final_img)
                    st.markdown(res)
                    
                    # Quick Add to Shopping List Logic
                    if "{" in res and "}" in res:
                        try:
                            raw = res.split("{")[1].split("}")[0]
                            items = [x.strip() for x in raw.split(",")]
                            if st.button("Add these ingredients to Shopping List"):
                                for itm in items:
                                    app_data["shopping_list"].append({
                                        "item": itm, "qty": "1", "user_price": 0, "ai_price": 0, "bought": False
                                    })
                                save_data(app_data)
                                st.success("Added!")
                        except: pass

                elif action == "Analyze Calories":
                    prompt = "Analyze this food image. Provide a table of items, calories, and macros. Total the calories."
                    res = ask_gemini(prompt, final_img)
                    st.markdown(res)

# ==========================================
# FEATURE 4: CHEAT NEGOTIATOR
# ==========================================
elif menu == "😈 Cheat Negotiator":
    st.header("😈 Cheat Meal Negotiator")
    st.write("Craving something bad? Let's see what it costs you.")

    craving = st.text_input("I really want to eat...", placeholder="A double cheeseburger and fries")

    if st.button("Negotiate"):
        if not st.session_state.is_verified:
            st.error("Please connect your API Key first!")
        else:
            with st.spinner("Calculating trade-off..."):
                prompt = f"""
                User Goal: {fitness_goal}.
                User wants to eat: {craving}.
                
                Act as a strict but fair fitness coach.
                1. Estimate calories for this cheat meal.
                2. Calculate the exact exercise needed to burn it off (e.g., "Run at 10km/h for 45 mins").
                3. Suggest a healthier "Swap" - a specific recipe or item that tastes similar but fits the goal.
                4. Give a verdict: "Worth it" or "Not worth it".
                """
                st.session_state.negotiation_result = ask_gemini(prompt)

    if st.session_state.negotiation_result:
        st.markdown("---")
        st.markdown(st.session_state.negotiation_result)
