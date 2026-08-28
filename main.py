# main.py
# ---------------------------------------------------------------------------
# Render start command: uvicorn main:app --host 0.0.0.0 --port $PORT
# Requires budget.db in the same directory — built by build_db.py before this
# runs (see Render build/start command below).
# ---------------------------------------------------------------------------

import os
import sqlite3
import json
import re
import statistics
from typing import List, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from google import genai
from typing import List, Dict, Optional, Literal
from fastapi import FastAPI, HTTPException, Query

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
DB_PATH = "budget.db"
GEMINI_MODEL = "gemini-3.6-flash"
CURRENCY = "KES"

if not GEMINI_API_KEY:
    raise RuntimeError(
        "GEMINI_API_KEY environment variable is not set. "
        "Set it in Render's Environment tab before deploying."
    )

client = genai.Client(api_key=GEMINI_API_KEY)

DISCLAIMER = (
    "This tool provides general household budgeting support and is for "
    "informational purposes only. It does not constitute professional "
    "financial, investment, or clinical dietary advice."
)

# ---------------------------------------------------------------------------
# DATABASE LAYER
# ---------------------------------------------------------------------------
def get_read_conn():
    uri = f"file:{DB_PATH}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def get_write_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_app_tables():
    conn = get_write_conn()
    cur = conn.cursor()
    cur.execute(
        """
            cur.execute(
        """
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            item TEXT NOT NULL,
            amount REAL NOT NULL,
            category TEXT NOT NULL,
            expense_type TEXT NOT NULL DEFAULT 'food',
            notes TEXT
        )
        """
    )
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            item TEXT NOT NULL,
            amount REAL NOT NULL,
            category TEXT NOT NULL,
            notes TEXT
        )
        """
    )
    conn.commit()
    conn.close()


init_app_tables()

# ---------------------------------------------------------------------------
# DATA MODELS
# ---------------------------------------------------------------------------
class ProfileIn(BaseModel):
    income: float = Field(..., gt=0)
    food_budget: float = Field(..., gt=0)
    family_size: int = Field(..., gt=0)
    dietary_needs: str = ""


class ChatIn(BaseModel):
    message: str
    spent_so_far: Optional[float] = 0.0


class ChatOut(BaseModel):
    reply: str
    context_used: Dict
    disclaimer: str = DISCLAIMER


class ExpenseIn(BaseModel):
    date: str = Field(..., description="YYYY-MM-DD")
    item: str = Field(..., min_length=1)
    amount: float = Field(..., gt=0)
    notes: str = ""
    expense_type: Literal["food", "custom"] = "food"
    custom_category: Optional[str] = None


class ExpenseOut(BaseModel):
    id: int
    date: str
    item: str
    amount: float
    category: str
    expense_type: str
    notes: str
    disclaimer: str = DISCLAIMER

# ---------------------------------------------------------------------------
# APP
# ---------------------------------------------------------------------------
app = FastAPI(title="Household Budgeting & Meal Planning Assistant")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"status": "ok", "service": "budget-assistant-backend", "disclaimer": DISCLAIMER}


@app.post("/profile")
def set_profile(profile: ProfileIn):
    conn = get_write_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO user_profile (id, income, food_budget, family_size, dietary_needs)
        VALUES (1, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            income=excluded.income,
            food_budget=excluded.food_budget,
            family_size=excluded.family_size,
            dietary_needs=excluded.dietary_needs
        """,
        (profile.income, profile.food_budget, profile.family_size, profile.dietary_needs),
    )
    conn.commit()
    conn.close()
    return {"status": "saved", "profile": profile.dict(), "disclaimer": DISCLAIMER}


@app.get("/profile")
def read_profile():
    conn = get_write_conn()
    cur = conn.cursor()
    cur.execute("SELECT income, food_budget, family_size, dietary_needs FROM user_profile WHERE id=1")
    row = cur.fetchone()
    conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="No profile has been set yet.")
    return {"profile": dict(row), "disclaimer": DISCLAIMER}


# ---------------------------------------------------------------------------
# KEYWORD EXTRACTION + DB RETRIEVAL (recipes / prices)
# ---------------------------------------------------------------------------
STOPWORDS = {
    "the", "a", "an", "is", "are", "for", "of", "to", "and", "on", "in",
    "what", "how", "much", "can", "i", "we", "my", "me", "do", "does",
    "with", "make", "cook", "cheap", "cheapest", "buy", "get", "please",
    "recipe", "recipes", "food", "meal", "meals", "plan", "budget", "cost",
    "price", "prices", "afford", "family", "week", "weekly", "month",
    "monthly", "need", "want", "should", "would", "could", "it", "this",
    "that", "some", "any", "have", "has",
}


def extract_keywords(message: str) -> List[str]:
    words = re.findall(r"[a-zA-Z]+", message.lower())
    keywords = [w for w in words if w not in STOPWORDS and len(w) > 2]
    return list(dict.fromkeys(keywords))


def query_food_prices(keywords: List[str], limit: int = 15) -> List[Dict]:
    conn = get_read_conn()
    cur = conn.cursor()
    results: Dict[str, Dict] = {}
    for kw in keywords:
        cur.execute(
            """
            SELECT * FROM food_prices
            WHERE lower(item) LIKE ?
               OR lower(product_name) LIKE ?
               OR lower(brand) LIKE ?
               OR lower(category) LIKE ?
               OR lower(food_group) LIKE ?
            LIMIT ?
            """,
            (f"%{kw}%", f"%{kw}%", f"%{kw}%", f"%{kw}%", f"%{kw}%", limit),
        )
        for row in cur.fetchall():
            d = dict(row)
            results[json.dumps(d, sort_keys=True, default=str)] = d
    if not results:
        cur.execute("SELECT * FROM food_prices ORDER BY RANDOM() LIMIT ?", (limit,))
        for row in cur.fetchall():
            d = dict(row)
            results[json.dumps(d, sort_keys=True, default=str)] = d
    conn.close()
    return list(results.values())[:limit]


def query_prices_for_items(item_names: List[str], limit: int = 50) -> List[Dict]:
    if not item_names:
        return []
    conn = get_read_conn()
    cur = conn.cursor()
    results: Dict[str, Dict] = {}
    for name in item_names:
        cur.execute(
            """
            SELECT * FROM food_prices
            WHERE lower(item) LIKE ? OR lower(product_name) LIKE ?
            LIMIT ?
            """,
            (f"%{name.lower()}%", f"%{name.lower()}%", limit),
        )
        for row in cur.fetchall():
            d = dict(row)
            results[json.dumps(d, sort_keys=True, default=str)] = d
    conn.close()
    return list(results.values())[:limit]


def query_recipes(keywords: List[str], limit: int = 10) -> List[Dict]:
    conn = get_read_conn()
    cur = conn.cursor()
    results: Dict[str, Dict] = {}
    for kw in keywords:
        cur.execute(
            """
            SELECT * FROM recipes
            WHERE lower(recipe_name) LIKE ?
               OR lower(meal_type) LIKE ?
               OR lower(dietary_tags) LIKE ?
            LIMIT ?
            """,
            (f"%{kw}%", f"%{kw}%", f"%{kw}%", limit),
        )
        for row in cur.fetchall():
            d = dict(row)
            results[json.dumps(d, sort_keys=True, default=str)] = d
    if not results:
        cur.execute("SELECT * FROM recipes ORDER BY RANDOM() LIMIT ?", (limit,))
        for row in cur.fetchall():
            d = dict(row)
            results[json.dumps(d, sort_keys=True, default=str)] = d
    conn.close()
    return list(results.values())[:limit]


def query_ingredients_for_recipes(recipe_ids: List, limit: int = 100) -> List[Dict]:
    if not recipe_ids:
        return []
    conn = get_read_conn()
    cur = conn.cursor()
    placeholders = ",".join("?" for _ in recipe_ids)
    cur.execute(
        f"SELECT * FROM recipe_ingredients WHERE recipe_id IN ({placeholders}) LIMIT ?",
        (*recipe_ids, limit),
    )
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows


def get_user_profile() -> Optional[Dict]:
    conn = get_write_conn()
    cur = conn.cursor()
    cur.execute("SELECT income, food_budget, family_size, dietary_needs FROM user_profile WHERE id=1")
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# EXPENSE CLASSIFICATION
# ---------------------------------------------------------------------------
def get_distinct_categories() -> List[str]:
    conn = get_read_conn()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT category FROM food_prices WHERE category IS NOT NULL")
    cats = [row["category"] for row in cur.fetchall()]
    conn.close()
    return cats


def classify_via_db(item_name: str) -> Optional[str]:
    conn = get_read_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT category FROM food_prices
        WHERE lower(item) LIKE ? OR lower(product_name) LIKE ?
        LIMIT 1
        """,
        (f"%{item_name.lower()}%", f"%{item_name.lower()}%"),
    )
    row = cur.fetchone()
    conn.close()
    return row["category"] if row else None


def classify_via_gemini(item_name: str, categories: List[str]) -> str:
    options = categories + ["Non-Food/Household", "Other"]
    prompt = (
        f"Classify the household expense item '{item_name}' into exactly ONE of "
        f"these categories: {', '.join(options)}. "
        f"Respond with ONLY the category name, exactly as written above, and nothing else."
    )
    response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
    result = (response.text or "").strip()
    return result if result in options else "Other"


def classify_expense(item_name: str) -> str:
    db_match = classify_via_db(item_name)
    if db_match:
        return db_match
    categories = get_distinct_categories()
    try:
        return classify_via_gemini(item_name, categories)
    except Exception:
        return "Other"


# ---------------------------------------------------------------------------
# EXPENSE LOGGING + BUDGET ANALYTICS
# ---------------------------------------------------------------------------
@app.post("/expense", response_model=ExpenseOut)
@app.post("/expense", response_model=ExpenseOut)
def add_expense(expense: ExpenseIn):
    if expense.expense_type == "custom":
        category = (expense.custom_category or "Other").strip() or "Other"
    else:
        category = classify_expense(expense.item)

    conn = get_write_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO expenses (date, item, amount, category, expense_type, notes) VALUES (?, ?, ?, ?, ?, ?)",
        (expense.date, expense.item, expense.amount, category, expense.expense_type, expense.notes),
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return ExpenseOut(
        id=new_id,
        date=expense.date,
        item=expense.item,
        amount=expense.amount,
        category=category,
        expense_type=expense.expense_type,
        notes=expense.notes,
    )


@app.get("/expenses")
def list_expenses(start_date: Optional[str] = Query(None), end_date: Optional[str] = Query(None)):
    rows = get_expenses_raw(start_date, end_date)
    return {"expenses": rows, "disclaimer": DISCLAIMER}


@app.delete("/expenses")
def clear_expenses():
    conn = get_write_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM expenses")
    conn.commit()
    conn.close()
    return {"status": "cleared", "disclaimer": DISCLAIMER}


def get_expenses_raw(start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[Dict]:
    conn = get_write_conn()
    cur = conn.cursor()
    if start_date and end_date:
        cur.execute(
            "SELECT * FROM expenses WHERE date BETWEEN ? AND ? ORDER BY date DESC, id DESC",
            (start_date, end_date),
        )
    else:
        cur.execute("SELECT * FROM expenses ORDER BY date DESC, id DESC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def compute_budget_summary(start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict:
    profile = get_user_profile()
    expenses = get_expenses_raw(start_date, end_date)
    food_budget = profile["food_budget"] if profile else 0.0

    total_spent = sum(e["amount"] for e in expenses)
    food_total = sum(e["amount"] for e in expenses if e.get("expense_type") == "food")
    custom_total = sum(e["amount"] for e in expenses if e.get("expense_type") == "custom")

    by_category: Dict[str, float] = {}
    for e in expenses:
        by_category[e["category"]] = by_category.get(e["category"], 0.0) + e["amount"]

    all_categories = get_distinct_categories()
    planned_per_category = {}
    if food_budget > 0 and all_categories:
        even_share = food_budget / len(all_categories)
        planned_per_category = {c: round(even_share, 2) for c in all_categories}

    flagged_categories = []
    for cat, spent in by_category.items():
        planned = planned_per_category.get(cat)
        if planned and spent > planned * 1.3:
            flagged_categories.append(
                {
                    "category": cat,
                    "planned": round(planned, 2),
                    "actual": round(spent, 2),
                    "over_by_pct": round(((spent - planned) / planned) * 100, 1),
                }
            )

    unusual_expenses = []
    by_cat_amounts: Dict[str, List[float]] = {}
    for e in expenses:
        by_cat_amounts.setdefault(e["category"], []).append(e["amount"])
    for e in expenses:
        amounts = by_cat_amounts[e["category"]]
        if len(amounts) >= 3:
            mean = statistics.mean(amounts)
            stdev = statistics.pstdev(amounts)
            if stdev > 0 and e["amount"] > mean + 1.5 * stdev:
                unusual_expenses.append(
                    {
                        "id": e["id"],
                        "date": e["date"],
                        "item": e["item"],
                        "amount": e["amount"],
                        "category": e["category"],
                        "category_average": round(mean, 2),
                    }
                )

        return {
        "total_spent": round(total_spent, 2),
        "food_total": round(food_total, 2),
        "custom_total": round(custom_total, 2),
        "food_budget": food_budget,
        "remaining_budget": round(max(food_budget - total_spent, 0.0), 2),
        "percent_of_budget_used": round((total_spent / food_budget) * 100, 1) if food_budget > 0 else 0.0,
        "by_category": {k: round(v, 2) for k, v in by_category.items()},
        "planned_per_category": planned_per_category,
        "flagged_categories": flagged_categories,
        "unusual_expenses": unusual_expenses,
        "expense_count": len(expenses),
    }


@app.get("/budget-summary")
def budget_summary(start_date: Optional[str] = Query(None), end_date: Optional[str] = Query(None)):
    summary = compute_budget_summary(start_date, end_date)
    summary["disclaimer"] = DISCLAIMER
    return summary


# ---------------------------------------------------------------------------
# SAVINGS TARGET RECOMMENDATION
# ---------------------------------------------------------------------------
class SavingsOut(BaseModel):
    disposable_income: float
    recommended_rate_pct: float
    recommended_monthly_savings: float
    narrative: str
    disclaimer: str = DISCLAIMER


@app.post("/savings-target", response_model=SavingsOut)
def savings_target():
    profile = get_user_profile()
    if not profile:
        raise HTTPException(status_code=404, detail="No profile has been set yet.")

    summary = compute_budget_summary()
    disposable = profile["income"] - summary["total_spent"]

    if disposable <= 0:
        rate = 0.0
    elif disposable < profile["income"] * 0.2:
        rate = 0.10
    else:
        rate = 0.20

    recommended_amount = max(disposable * rate, 0.0)

    prompt = f"""
You are a household budgeting assistant. All figures are in {CURRENCY}.

Household profile: {json.dumps(profile, default=str)}
Current spending summary: {json.dumps(summary, default=str)}
Disposable income after food budget: {disposable}
Rule-based recommended monthly savings: {recommended_amount} (a {rate*100:.0f}% savings rate)

Write a short (3-5 sentence) plain-language explanation of this savings
recommendation for the household, referencing their actual food budget
utilization and family size. Be encouraging but realistic. Do not present
this as professional financial advice. Report all monetary values in {CURRENCY}.
"""
    try:
        response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        narrative = response.text
    except Exception as exc:
        narrative = (
            f"Based on your income of {CURRENCY} {profile['income']:,.2f} and food budget of "
            f"{CURRENCY} {profile['food_budget']:,.2f}, we recommend saving about "
            f"{CURRENCY} {recommended_amount:,.2f} per month ({rate*100:.0f}% of your disposable income). "
            f"(Note: AI narrative generation failed: {exc})"
        )

    return SavingsOut(
        disposable_income=round(disposable, 2),
        recommended_rate_pct=round(rate * 100, 1),
        recommended_monthly_savings=round(recommended_amount, 2),
        narrative=narrative,
    )


# ---------------------------------------------------------------------------
# CHAT CONTEXT BUILDER
# ---------------------------------------------------------------------------
def build_context(message: str) -> Dict:
    keywords = extract_keywords(message)

    food_prices = query_food_prices(keywords)
    recipes = query_recipes(keywords)
    recipe_ids = [r.get("recipe_id") for r in recipes if r.get("recipe_id") is not None]
    ingredients = query_ingredients_for_recipes(recipe_ids)

    ingredient_item_names = list({ing["item"] for ing in ingredients if ing.get("item")})
    ingredient_prices = query_prices_for_items(ingredient_item_names)

    profile = get_user_profile()
    budget_summary = compute_budget_summary()
    recent_expenses = get_expenses_raw()[:20]

    return {
        "keywords": keywords,
        "food_prices": food_prices,
        "recipes": recipes,
        "recipe_ingredients": ingredients,
        "ingredient_prices": ingredient_prices,
        "user_profile": profile,
        "budget_summary": budget_summary,
        "recent_expenses": recent_expenses,
    }


# ---------------------------------------------------------------------------
# GEMINI CHAT PIPELINE
# ---------------------------------------------------------------------------
SYSTEM_INSTRUCTION = f"""You are a household budgeting and healthy meal-planning assistant
serving a household in Kenya. All prices in the provided data are in Kenyan
Shillings ({CURRENCY}). You are given a user's household profile (income,
food budget, family size, dietary needs), their logged expenses, a computed
budget summary (spend by category, planned vs actual, flagged overspending
categories, unusual/outlier expenses), and locally sourced grocery data
(food_prices, recipes, recipe_ingredients, ingredient_prices) pulled from a
real SQLite database. Use ONLY the provided data as your source of truth —
do not invent products, prices, or figures not present in the context.
Always report costs in {CURRENCY}. Give practical, budget-conscious,
nutritionally sensible suggestions. Show simple math (price per serving,
weekly/monthly totals) when relevant. Reference the user's actual flagged
categories or unusual expenses when relevant to their question. Keep answers
concise and use markdown formatting (bullet points, bold, small tables) for
readability. If the data provided is insufficient to answer precisely, say
so honestly rather than guessing."""


def call_gemini(user_message: str, context: Dict, spent_so_far: float) -> str:
    profile = context.get("user_profile")
    profile_block = (
        json.dumps(profile, indent=2, default=str)
        if profile
        else "No profile has been set yet. Ask the user to fill in the sidebar profile form."
    )

    prompt = f"""
{SYSTEM_INSTRUCTION}

## USER PROFILE
{profile_block}

## BUDGET SUMMARY (computed from logged expenses, {CURRENCY})
{json.dumps(context['budget_summary'], indent=2, default=str)}

## RECENT LOGGED EXPENSES
{json.dumps(context['recent_expenses'], indent=2, default=str)}

## MATCHING FOOD PRICES
{json.dumps(context['food_prices'], indent=2, default=str)}

## MATCHING RECIPES
{json.dumps(context['recipes'], indent=2, default=str)}

## INGREDIENTS FOR MATCHED RECIPES
{json.dumps(context['recipe_ingredients'], indent=2, default=str)}

## KES PRICES FOR THOSE SPECIFIC INGREDIENTS
{json.dumps(context['ingredient_prices'], indent=2, default=str)}

## USER QUESTION
{user_message}

Respond directly to the user's question using the data above. Report all
monetary values in {CURRENCY}.
"""
    response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
    return response.text


@app.post("/chat", response_model=ChatOut)
def chat(chat_in: ChatIn):
    if not chat_in.message or not chat_in.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")
    context = build_context(chat_in.message)
    try:
        reply_text = call_gemini(chat_in.message, context, chat_in.spent_so_far or 0.0)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Gemini generation failed: {exc}")
    return ChatOut(reply=reply_text, context_used=context, disclaimer=DISCLAIMER)
