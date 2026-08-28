# build_db.py
import pandas as pd
import sqlite3

food_prices = pd.read_csv("food_prices.csv")
recipes = pd.read_csv("recipes.csv")
recipe_ingredients = pd.read_csv("recipe_ingredients.csv")

conn = sqlite3.connect("budget.db")
food_prices.to_sql("food_prices", conn, if_exists="replace", index=False)
recipes.to_sql("recipes", conn, if_exists="replace", index=False)
recipe_ingredients.to_sql("recipe_ingredients", conn, if_exists="replace", index=False)
conn.commit()
conn.close()
print("budget.db built successfully.")
