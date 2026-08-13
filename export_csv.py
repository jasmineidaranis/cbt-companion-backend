import sqlite3
import csv

# adjust filename if yours is named differently
conn = sqlite3.connect("cbt.db")
cursor = conn.cursor()

cursor.execute("SELECT * FROM wearable_data")
rows = cursor.fetchall()
columns = [description[0] for description in cursor.description]

with open("wearable_data_export.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(columns)
    writer.writerows(rows)

print(f"Exported {len(rows)} rows to wearable_data_export.csv")
conn.close()