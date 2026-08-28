%%writefile frontend.py
# ---------------------------------------------------------------------------
# Run via: subprocess.Popen(["streamlit", "run", "frontend.py",
#                             "--server.port", "8501", "--server.headless", "true"])
# Then tunnel: !npx localtunnel --port 8501
# ---------------------------------------------------------------------------

import streamlit as st
import requests
import pandas as pd
from datetime import date

BACKEND_URL = st.secrets.get("BACKEND_URL", "http://localhost:8000")
CURRENCY = "KES"

DISCLAIMER = (
    "This tool provides general household budgeting support and is for "
    "informational purposes only. It does not constitute professional "
    "financial, investment, or clinical dietary advice."
)

st.set_page_config(page_title="AI Household Budget & Meal Planner", page_icon="🥗", layout="wide")

# ---------------------------------------------------------------------------
# SESSION STATE
# ---------------------------------------------------------------------------
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "profile" not in st.session_state:
    st.session_state.profile = None

# ---------------------------------------------------------------------------
# BACKEND HELPERS
# ---------------------------------------------------------------------------
def push_profile(income, food_budget, family_size, dietary_needs):
    try:
        resp = requests.post(
            f"{BACKEND_URL}/profile",
            json={"income": income, "food_budget": food_budget,
                  "family_size": family_size, "dietary_needs": dietary_needs},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as exc:
        st.sidebar.error(f"Could not reach backend: {exc}")
        return None


def fetch_profile():
    try:
        resp = requests.get(f"{BACKEND_URL}/profile", timeout=10)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()["profile"]
    except requests.exceptions.RequestException:
        return None


def log_expense(exp_date, item, amount, notes):
    try:
        resp = requests.post(
            f"{BACKEND_URL}/expense",
            json={"date": str(exp_date), "item": item, "amount": amount, "notes": notes},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as exc:
        st.error(f"Could not log expense: {exc}")
        return None


def fetch_budget_summary():
    try:
        resp = requests.get(f"{BACKEND_URL}/budget-summary", timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException:
        return None


def fetch_savings_target():
    try:
        resp = requests.post(f"{BACKEND_URL}/savings-target", timeout=30)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as exc:
        st.error(f"Could not fetch savings recommendation: {exc}")
        return None


def send_chat_message(message: str, spent_so_far: float):
    try:
        resp = requests.post(
            f"{BACKEND_URL}/chat",
            json={"message": message, "spent_so_far": spent_so_far},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as exc:
        return {"reply": f"⚠️ Error reaching backend: {exc}"}


# ---------------------------------------------------------------------------
# SIDEBAR: PROFILE
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("👨‍👩‍👧‍👦 Household Profile")

    existing = fetch_profile()
    default_income = existing["income"] if existing else 30000.0
    default_food_budget = existing["food_budget"] if existing else 8000.0
    default_family_size = existing["family_size"] if existing else 4
    default_dietary = existing["dietary_needs"] if existing else ""

    with st.form("profile_form"):
        income = st.number_input(f"Monthly Household Income ({CURRENCY})", min_value=0.0, value=float(default_income), step=500.0)
        food_budget = st.number_input(f"Monthly Food Budget ({CURRENCY})", min_value=0.0, value=float(default_food_budget), step=250.0)
        family_size = st.number_input("Family Size (# of people)", min_value=1, value=int(default_family_size), step=1)
        dietary_needs = st.text_area("Dietary Needs / Restrictions", value=default_dietary,
                                      placeholder="e.g. vegetarian, nut allergy, low-sodium")
        submitted = st.form_submit_button("💾 Save Profile")
        if submitted:
            result = push_profile(income, food_budget, int(family_size), dietary_needs)
            if result is not None:
                st.session_state.profile = result["profile"]
                st.success("Profile saved!")
                st.rerun()

    if existing:
        st.session_state.profile = existing

    st.divider()
    st.subheader("🧾 Log an Expense")
    with st.form("expense_form", clear_on_submit=True):
        exp_date = st.date_input("Date", value=date.today())
        exp_item = st.text_input("Item (e.g. maize flour, tomatoes)")
        exp_amount = st.number_input(f"Amount ({CURRENCY})", min_value=0.0, step=10.0)
        exp_notes = st.text_input("Notes (optional)")
        exp_submitted = st.form_submit_button("➕ Add Expense")
        if exp_submitted:
            if not exp_item.strip() or exp_amount <= 0:
                st.warning("Enter an item name and an amount greater than 0.")
            else:
                result = log_expense(exp_date, exp_item.strip(), exp_amount, exp_notes)
                if result:
                    st.success(f"Logged '{result['item']}' under **{result['category']}**")
                    st.rerun()

    st.divider()
    st.caption(DISCLAIMER)


# ---------------------------------------------------------------------------
# MAIN LAYOUT
# ---------------------------------------------------------------------------
st.title("🥗 AI Household Budgeting & Healthy Meal-Planning Assistant")
st.caption("AI BuildFest 2026 — Track 3")

profile = st.session_state.profile
summary = fetch_budget_summary() if profile else None

col1, col2, col3 = st.columns(3)

if profile and summary:
    total_spent = summary["total_spent"]
    remaining = summary["remaining_budget"]
    pct_used = min(summary["percent_of_budget_used"] / 100, 1.0)

    col1.metric("Monthly Food Budget", f"{CURRENCY} {profile['food_budget']:,.2f}")
    col2.metric("Spent So Far", f"{CURRENCY} {total_spent:,.2f}")
    col3.metric("Remaining Budget", f"{CURRENCY} {remaining:,.2f}")

    st.subheader("📊 Budget Utilization")
    st.progress(pct_used, text=f"{summary['percent_of_budget_used']:.1f}% of food budget used")

    if pct_used >= 1.0:
        st.error("🚨 You have reached or exceeded your monthly food budget.")
    elif pct_used >= 0.8:
        st.warning("⚠️ You are approaching your monthly food budget limit.")
    else:
        st.success("✅ You are within your monthly food budget.")

    per_person = profile["food_budget"] / profile["family_size"] if profile["family_size"] else 0
    st.caption(f"Per-person food budget: {CURRENCY} {per_person:,.2f} for a family of {profile['family_size']}")

    # ---- Planned vs Actual by category ----
    st.divider()
    st.subheader("📁 Planned vs Actual Spend by Category")
    if summary["by_category"]:
        cats = sorted(set(list(summary["by_category"].keys()) + list(summary["planned_per_category"].keys())))
        df = pd.DataFrame({
            "Category": cats,
            "Planned": [summary["planned_per_category"].get(c, 0.0) for c in cats],
            "Actual": [summary["by_category"].get(c, 0.0) for c in cats],
        }).set_index("Category")
        st.bar_chart(df)
    else:
        st.info("Log some expenses to see your category breakdown.")

    # ---- Flags ----
    if summary["flagged_categories"]:
        st.subheader("🚩 Categories Over Their Planned Share")
        for f in summary["flagged_categories"]:
            st.warning(
                f"**{f['category']}**: spent {CURRENCY} {f['actual']:,.2f} vs planned "
                f"{CURRENCY} {f['planned']:,.2f} ({f['over_by_pct']}% over)"
            )

    if summary["unusual_expenses"]:
        st.subheader("🔍 Unusually High Individual Expenses")
        for u in summary["unusual_expenses"]:
            st.warning(
                f"**{u['item']}** ({u['date']}) — {CURRENCY} {u['amount']:,.2f} in "
                f"**{u['category']}**, well above the category average of "
                f"{CURRENCY} {u['category_average']:,.2f}"
            )

    # ---- Savings target ----
    st.divider()
    st.subheader("💰 Savings Recommendation")
    if st.button("Get Savings Recommendation"):
        with st.spinner("Calculating a realistic savings target..."):
            rec = fetch_savings_target()
        if rec:
            c1, c2 = st.columns(2)
            c1.metric("Recommended Monthly Savings", f"{CURRENCY} {rec['recommended_monthly_savings']:,.2f}")
            c2.metric("Suggested Savings Rate", f"{rec['recommended_rate_pct']}%")
            st.info(rec["narrative"])

    # ---- Expense log ----
    st.divider()
    with st.expander("📋 View Full Expense Log"):
        try:
            exp_resp = requests.get(f"{BACKEND_URL}/expenses", timeout=10).json()
            if exp_resp["expenses"]:
                st.dataframe(pd.DataFrame(exp_resp["expenses"]), use_container_width=True)
            else:
                st.caption("No expenses logged yet.")
        except requests.exceptions.RequestException as exc:
            st.error(f"Could not load expenses: {exc}")

else:
    col1.metric("Monthly Food Budget", "—")
    col2.metric("Spent So Far", "—")
    col3.metric("Remaining Budget", "—")
    st.info("👈 Set up your household profile in the sidebar to enable budget tracking.")

st.divider()

# ---------------------------------------------------------------------------
# CHAT INTERFACE
# ---------------------------------------------------------------------------
st.subheader("💬 Chat with your Budgeting & Meal-Planning Assistant")

for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

user_message = st.chat_input("Ask about spending patterns, affordable recipes, or ingredient prices...")

if user_message:
    st.session_state.chat_history.append({"role": "user", "content": user_message})
    with st.chat_message("user"):
        st.markdown(user_message)

    spent_val = summary["total_spent"] if summary else 0.0

    with st.chat_message("assistant"):
        with st.spinner("Checking your budget, expenses, and local food data..."):
            result = send_chat_message(user_message, spent_val)
            reply = result.get("reply", "Sorry, I couldn't generate a response.")
        st.markdown(reply)

    st.session_state.chat_history.append({"role": "assistant", "content": reply})

st.divider()
st.caption(DISCLAIMER)
